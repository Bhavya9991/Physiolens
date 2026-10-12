"""PhysioNet citation parsing and the published-research candidate list."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.agents.published import SAMPLE_NOTE, cite_band, classify, collect_citing, dedupe_candidates, usage_cards
from apps.agents.published import _choose, _counts, _pages, _resolve
from apps.agents.usage import (
    PaperClass,
    answer_class,
    apply_class,
    classify_overviews,
    html_candidates,
    load_card_html,
    load_paper_sections,
    pdf_candidates,
    overview_query,
    paper_html_url,
)
from apps.backend.runlog import append_log, delete_log, read_log
from apps.backend.citations import parse_citations
from apps.backend.paper_html import dataset_about, parse_paper, select_bundle
from apps.backend.paper_pdf import sections_from_lines
from apps.backend.report import render_report
from apps.backend.scholar import _record

RADQA = """
<div class="citation-section">
  <span class="citation-label">When using this resource, please cite:</span>
  <p class="citation-text">Soni, S., &amp; Roberts, K. (2022). RadQA (version 1.0.0). <i>PhysioNet</i>.
  <a href="https://doi.org/10.13026/ckkp-6y19">https://doi.org/10.13026/ckkp-6y19</a></p>
  <textarea id="bibtex-data">@article{PhysioNet-radqa-1.0.0,
  author = {Soni, Sarvesh and Roberts, Kirk},
  title = {{RadQA: A Question Answering Dataset to Improve Comprehension of Radiology Reports}},
  year = {2022},
  doi = {10.13026/ckkp-6y19},
  url = {https://doi.org/10.13026/ckkp-6y19}
}</textarea>
</div>
<div class="citation-section">
  <span class="citation-label">Additionally, please cite the original publication:</span>
  <p class="citation-text">Soni, S., Gudala, M., Pajouhi, A., &amp; Roberts, K. (2022, June). RadQA: A Question Answering Dataset to Improve Comprehension of Radiology Reports. In Proceedings of the Thirteenth Language Resources and Evaluation Conference (pp. 6250-6259). <a href="https://aclanthology.org/2022.lrec-1.672">https://aclanthology.org/2022.lrec-1.672</a></p>
</div>
<div class="citation-section">
  <span class="citation-label">Please include the standard citation for PhysioNet:</span>
  <p class="citation-text">Pollard, T. (2026). PhysioNet as a global platform. <a href="https://doi.org/10.1038/s44360-026-00096-z">https://doi.org/10.1038/s44360-026-00096-z</a></p>
  <textarea>@article{pollard, doi = {10.1038/s44360-026-00096-z}, title = {{PhysioNet}}}</textarea>
</div>
"""


class CitationParseTests(unittest.TestCase):
    def test_bibtex_resource_and_text_original_skip_the_platform(self):
        records = parse_citations(RADQA)
        self.assertEqual([item["kind"] for item in records], ["resource", "original"])
        resource, original = records
        self.assertEqual(resource["source"], "bibtex")
        self.assertEqual(resource["doi"], "10.13026/ckkp-6y19")
        self.assertEqual(resource["authors"], "Soni, Sarvesh and Roberts, Kirk")
        self.assertIn("Radiology Reports", resource["title"])
        self.assertEqual(original["source"], "citation_text")
        self.assertEqual(original["doi"], "")
        self.assertEqual(original["year"], "2022")
        self.assertEqual(original["url"], "https://aclanthology.org/2022.lrec-1.672")
        self.assertTrue(original["title"].startswith("RadQA:"))

    def test_a_page_with_only_the_resource_citation(self):
        html = """
        <div class="citation-section">
          <span class="citation-label">When using this resource, please cite:</span>
          <textarea>@article{x, title = {{MIT-BIH Arrhythmia Database}}, year = {2005}, doi = {10.13026/C2F305}}</textarea>
        </div>
        """
        records = parse_citations(html)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "resource")
        self.assertEqual(records[0]["doi"], "10.13026/c2f305")


class ScholarRecordTests(unittest.TestCase):
    def test_html_version_and_cached_page_are_kept(self):
        record = _record(
            {
                "title": "A paper",
                "link": "https://publisher.example/paper",
                "inline_links": {
                    "cited_by": {"total": 38, "cites_id": "99"},
                    "html_version": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/",
                    "cached_page_link": "https://scholar.googleusercontent.com/scholar?q=cache:abc",
                    "versions": {"serpapi_scholar_link": "https://serpapi.com/search.json?cluster=99"},
                },
            }
        )
        self.assertEqual(record["cited_by"], "99")
        self.assertEqual(record["cited_by_total"], 38)
        self.assertIn("pmc.ncbi.nlm.nih.gov", record["html_version"])
        self.assertIn("cache:abc", record["cached_page_link"])
        self.assertIn("cluster=99", record["versions_link"])

    def test_a_pdf_resource_is_kept(self):
        record = _record(
            {
                "title": "A paper",
                "link": "https://publisher.example/paper",
                "resources": [{"file_format": "PDF", "link": "https://publisher.example/paper.pdf"}],
            }
        )
        self.assertEqual(record["pdf_links"], ["https://publisher.example/paper.pdf"])


class SeedResolveTests(unittest.TestCase):
    def test_doi_miss_falls_back_to_the_title(self):
        calls = []

        def fake_search(query, _key, num=5):
            calls.append(query)
            if query == "10.13026/missing":
                return []
            return [{"title": "RadQA paper", "link": "https://aclanthology.org/2022.lrec-1.672", "snippet": "", "summary": "", "cited_by": "5", "cited_by_total": 12}]

        citation = {"doi": "10.13026/missing", "title": "RadQA: A Question Answering Dataset to Improve Comprehension of Radiology Reports"}
        with patch("apps.agents.published.search_scholar", side_effect=fake_search), patch("apps.agents.published._serp_key", return_value="k"):
            hit, how = _resolve(citation)
        self.assertEqual(calls, ["10.13026/missing", citation["title"]])
        self.assertEqual(how, "title")
        self.assertEqual(hit["cited_by"], "5")

    def test_several_unrelated_hits_are_not_a_match(self):
        hits = [
            {"title": "Something else entirely about radiology billing", "link": "", "snippet": "", "summary": ""},
            {"title": "Another unrelated cohort study of hospital notes", "link": "", "snippet": "", "summary": ""},
        ]
        citation = {"doi": "", "title": "RadQA: A Question Answering Dataset to Improve Comprehension of Radiology Reports"}
        self.assertIsNone(_choose(hits, citation))

    def test_a_single_doi_hit_is_kept(self):
        hits = [{"title": "RadQA", "link": "https://doi.org/10.13026/ckkp-6y19", "snippet": "", "summary": ""}]
        chosen = _choose(hits, {"doi": "10.13026/ckkp-6y19", "title": "RadQA"})
        self.assertEqual(chosen["title"], "RadQA")

    def test_both_lookups_empty_returns_nothing(self):
        with patch("apps.agents.published.search_scholar", return_value=[]), patch("apps.agents.published._serp_key", return_value="k"):
            hit, how = _resolve({"doi": "10.1/missing", "title": "No Such Paper Anywhere In The Catalog"})
        self.assertIsNone(hit)
        self.assertEqual(how, "")


class CandidateListTests(unittest.TestCase):
    def test_cite_bands_use_the_seed_total(self):
        self.assertEqual(cite_band(3), "lightly cited")
        self.assertEqual(cite_band(38), "moderately cited")
        self.assertEqual(cite_band(2000), "heavily cited")

    def test_the_same_paper_from_both_trails_is_one_row(self):
        paper = {
            "title": "A system for RadQA",
            "link": "https://example.test/paper",
            "snippet": "doi 10.5555/abc.123",
            "summary": "",
            "result_id": "abc",
            "cited_by": "1",
        }
        resource = dict(paper, trails=["resource"], cached_page_link="")
        original = dict(paper, trails=["original"], cached_page_link="https://scholar.googleusercontent.com/cache")
        rows = dedupe_candidates([resource, original])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["trails"], ["resource", "original"])
        self.assertIn("cache", rows[0]["cached_page_link"])

    def test_each_citing_page_is_its_own_search_and_the_list_is_capped(self):
        calls = []

        def fake_citing(_cites, _key, num=20, start=0):
            calls.append(start)
            return [{"title": f"Paper {start + index}", "link": f"https://example.test/{start + index}", "snippet": "", "summary": ""} for index in range(num)]

        with patch("apps.agents.published.search_citing", side_effect=fake_citing), patch("apps.agents.published._serp_key", return_value="k"):
            papers, call_count = _pages("99")
        self.assertEqual(calls, [0, 20, 40, 60, 80])
        self.assertEqual(call_count, 5)
        self.assertEqual(len(papers), 100)

    def test_the_sample_stops_at_twenty_unique_papers(self):
        calls = []

        def fake_citing(cites, _key, num=20, start=0):
            calls.append((cites, start))
            return [
                {"title": f"Paper {cites} {start + index} of the sample", "link": f"https://example.test/{cites}/{start + index}", "snippet": "", "summary": ""}
                for index in range(num)
            ]

        state = {
            "run_id": "run",
            "project": {"title": "RadQA"},
            "steps": [],
            "citations": [{"kind": "resource"}, {"kind": "original"}],
            "seeds": [
                {"kind": "resource", "hit": {"cited_by": "1"}, "cited_by_total": 400},
                {"kind": "original", "hit": {"cited_by": "2"}, "cited_by_total": 80},
            ],
        }
        with (
            patch("apps.agents.published.search_citing", side_effect=fake_citing),
            patch("apps.agents.published._serp_key", return_value="k"),
            patch("apps.agents.published.remember", side_effect=lambda current, item: [*(current.get("steps") or []), item]),
        ):
            result = collect_citing(state)
        self.assertEqual(calls, [("1", 0)])
        self.assertEqual(len(result["candidates"]), 10)
        self.assertIn("not a ranking", result["summary"])
        self.assertIn("stops at 10", result["summary"])

    def test_duplicate_pages_keep_being_requested_until_twenty_unique(self):
        calls = []

        def fake_citing(_cites, _key, num=20, start=0):
            calls.append(start)
            if start == 0:
                return [{"title": "Same paper title repeated", "link": "https://example.test/same", "snippet": "", "summary": ""} for _index in range(num)]
            return [
                {"title": f"Distinct paper number {start + index} here", "link": f"https://example.test/{start + index}", "snippet": "", "summary": ""}
                for index in range(num)
            ]

        state = {
            "run_id": "run",
            "project": {"title": "RadQA"},
            "steps": [],
            "citations": [{"kind": "resource"}],
            "seeds": [{"kind": "resource", "hit": {"cited_by": "1"}, "cited_by_total": 80}],
        }
        with (
            patch("apps.agents.published.search_citing", side_effect=fake_citing),
            patch("apps.agents.published._serp_key", return_value="k"),
            patch("apps.agents.published.remember", side_effect=lambda current, item: [*(current.get("steps") or []), item]),
        ):
            result = collect_citing(state)
        self.assertEqual(calls, [0, 20])
        self.assertEqual(len(result["candidates"]), 10)

    def test_a_failed_overview_leaves_the_paper_unclear(self):
        state = {
            "run_id": "run",
            "project": {"title": "RadQA"},
            "steps": [],
            "candidates": [{"title": "A paper about radiology reports", "link": "https://example.test/a", "summary": ""}],
        }
        with (
            patch("apps.agents.published.fetch_overview", side_effect=RuntimeError("quota")),
            patch("apps.agents.published.append_log"),
            patch("apps.agents.published._serp_key", return_value="k"),
            patch("apps.agents.published.remember", side_effect=lambda current, item: [*(current.get("steps") or []), item]),
        ):
            result = classify(state)
        self.assertEqual(result["candidates"][0]["usage_class"], "unclear")
        self.assertEqual(result["candidates"][0]["routing"], "report_only")


class PaperHtmlTests(unittest.TestCase):
    def test_scholar_cache_is_read_in_column_order_and_dehyphenated(self):
        html = """
        <span style="font-size:12px">
          <div style="position:absolute;top:10px;left:100px"><nobr>Abstract</nobr></div>
          <div style="position:absolute;top:30px;left:100px"><nobr>The study uses the ques-</nobr></div>
          <div style="position:absolute;top:50px;left:100px"><nobr>tions from the dataset.</nobr></div>
          <div style="position:absolute;top:70px;left:100px"><nobr>12 44 90 3.1 8</nobr></div>
        </span>
        <span style="font-size:15px">
          <div style="position:absolute;top:90px;left:100px"><nobr>1 Introduction</nobr></div>
          <div style="position:absolute;top:20px;left:400px"><nobr>Methods</nobr></div>
        </span>
        <span style="font-size:12px">
          <div style="position:absolute;top:110px;left:100px"><nobr>This section states the problem.</nobr></div>
          <div style="position:absolute;top:40px;left:400px"><nobr>A model is trained on the reports.</nobr></div>
        </span>
        """
        sections = {item["heading"]: item["text"] for item in parse_paper(html)}
        self.assertIn("questions from the dataset", sections["Abstract"])
        self.assertNotIn("12 44", sections["Abstract"])
        self.assertIn("trained on the reports", sections["Methods"])
        self.assertIn("states the problem", sections["1 Introduction"])
        bundle = select_bundle(parse_paper(html))
        self.assertLess(bundle.find("Abstract"), bundle.find("Methods"))
        self.assertLess(bundle.find("Methods"), bundle.find("Introduction"))

    def test_article_html_uses_headings_and_skips_navigation(self):
        html = """
        <nav><h2>Permalink</h2><p>Ignore this chrome.</p></nav>
        <h2>Abstract</h2>
        <p>Patients ask questions about radiology reports.</p>
        <h2>Methods</h2>
        <p>The model uses the dataset for training.</p>
        """
        sections = {item["heading"]: item["text"] for item in parse_paper(html)}
        self.assertEqual(set(sections), {"Abstract", "Methods"})
        self.assertIn("training", sections["Methods"])

    def test_results_and_related_work_are_left_out_of_the_bundle(self):
        html = """
        <h2>Abstract</h2><p>The dataset is used to classify sleep stages.</p>
        <h2>Dataset</h2><p>Recordings are used for training and testing.</p>
        <h2>Methods</h2><p>A transformer encodes each night.</p>
        <h2>Results</h2><p>Accuracy reached 91 percent on the held-out nights.</p>
        <h2>Related Work</h2><p>Earlier papers used a different corpus.</p>
        """
        bundle = select_bundle(parse_paper(html))
        self.assertIn("classify sleep stages", bundle)
        self.assertIn("training and testing", bundle)
        self.assertIn("transformer", bundle)
        self.assertNotIn("91 percent", bundle)
        self.assertNotIn("different corpus", bundle)

    def test_a_physionet_page_keeps_the_dataset_description(self):
        html = """
        <h2>Abstract</h2><p>We present a question answering dataset of radiology reports.</p>
        <h2>Data Description</h2><p>Each question is paired with a findings section.</p>
        <h2>References</h2><p>Zeng et al. surveyed medical QA.</p>
        """
        about = dataset_about(html)
        self.assertIn("question answering dataset", about)
        self.assertIn("findings section", about)
        self.assertNotIn("Zeng", about)


class UsageClassTests(unittest.TestCase):
    def test_low_confidence_does_not_open_a_usage_card(self):
        got = apply_class(
            PaperClass(
                index=0,
                usage_class="experimental_use",
                usage_tags=["training"],
                confidence="low",
                evidence="maybe",
                why="The overview is thin.",
            )
        )
        self.assertEqual(got["usage_class"], "unclear")
        self.assertEqual(got["routing"], "report_only")

    def test_a_use_tag_at_medium_confidence_opens_a_card(self):
        got = apply_class(
            PaperClass(
                index=1,
                usage_class="background_reference",
                usage_tags=["benchmarking"],
                confidence="medium",
                evidence="The paper benchmarks on the dataset.",
                why="It reports a benchmark.",
            )
        )
        self.assertEqual(got["routing"], "usage_card")
        self.assertEqual(got["usage_class"], "background_reference")

    def test_yes_sends_the_paper_to_a_usage_card(self):
        query = overview_query("AgentClinic: a multimodal agent benchmark to evaluate AI in simulated clinical environments", "MIMIC-IV")
        got = answer_class("Yes. The paper evaluates agents on MIMIC-IV.", query)
        self.assertEqual(got["routing"], "usage_card")
        echoed = answer_class(query + " No. It only cites MIMIC-IV in related work.", query)
        self.assertEqual(echoed["routing"], "report_only")
        self.assertIn("background", echoed["why"])

    def test_an_empty_overview_stays_unclear_without_a_model_call(self):
        papers = [{"title": "A paper", "overview": ""}]
        with patch("apps.agents.usage.ask") as ask:
            note = classify_overviews(papers, "RadQA")
        ask.assert_not_called()
        self.assertEqual(papers[0]["usage_class"], "unclear")
        self.assertIn("unclear", note)

    def test_a_blocked_cache_falls_through_to_the_paper_page(self):
        paper = {
            "cached_page_link": "https://scholar.googleusercontent.com/scholar?q=cache:abc",
            "link": "https://aclanthology.org/2025.bionlp-share.13/",
        }

        def fake(url):
            if "cache" in url:
                return "", "403 from scholar.googleusercontent.com"
            return "<html><h2>Abstract</h2><p>The dataset is used.</p></html>", "read 60 characters from aclanthology.org"

        with patch("apps.agents.usage.fetch_article_html", side_effect=fake):
            html, kind, notes = load_card_html(paper, "key")
        self.assertIn("Abstract", html)
        self.assertEqual(kind, "paper page")
        self.assertTrue(any("403" in note for note in notes))

    def test_an_arxiv_abs_link_has_an_html_page_and_a_pdf(self):
        paper = {"link": "https://arxiv.org/abs/2608.07796", "versions_link": "https://serpapi.example/versions"}
        pages = [url for url, _kind in html_candidates(paper)]
        self.assertEqual(pages, ["https://arxiv.org/html/2608.07796"])
        self.assertIn("https://arxiv.org/pdf/2608.07796.pdf", pdf_candidates(paper))

        def fail_if_scholar(*_args, **_kwargs):
            raise AssertionError("reading a paper must not call Scholar")

        with (
            patch("apps.agents.usage.fetch_article_html", return_value=("", "404 from arxiv.org")),
            patch("apps.agents.usage.fetch_pdf", return_value=(b"", "no pdf")),
            patch("apps.backend.scholar._payload", side_effect=fail_if_scholar),
        ):
            sections, kind, _notes = load_paper_sections(paper, "key")
        self.assertEqual(sections, [])
        self.assertEqual(kind, "")

    def test_a_pdf_link_is_not_treated_as_html(self):
        found = html_candidates(
            {
                "link": "https://aclanthology.org/paper.pdf",
                "html_version": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/",
            }
        )
        self.assertEqual(found, [("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/", "HTML article")])

    def test_a_run_log_is_one_file_and_delete_removes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("apps.backend.runlog.LOG_DIR", Path(tmp)):
                append_log("run-1", "classify", "Judgement for “Paper”: true. The overview says this paper uses the dataset.")
                self.assertIn("\tclassify\t", read_log("run-1"))
                self.assertIn("Judgement for", read_log("run-1"))
                delete_log("run-1")
                self.assertEqual(read_log("run-1"), "")

    def test_cache_is_preferred_over_an_article_url(self):
        url, kind = paper_html_url(
            {
                "cached_page_link": "https://scholar.googleusercontent.com/scholar?q=cache:abc",
                "html_version": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/",
            }
        )
        self.assertEqual(kind, "Scholar cache")
        self.assertIn("cache:abc", url)

    def test_pdf_lines_become_sections_by_font_size(self):
        prose = "The study uses the dataset for training and evaluation of the model."
        sections = sections_from_lines(
            [
                {"text": "Abstract", "size": 16},
                {"text": prose, "size": 11},
                {"text": "2 Methods", "size": 14},
                {"text": "Features were computed from the recordings and then classified.", "size": 11},
            ]
        )
        headings = [section["heading"] for section in sections]
        self.assertEqual(headings, ["Abstract", "2 Methods"])
        self.assertIn("training", sections[0]["text"])

    def test_a_pdf_is_used_when_the_html_has_no_paper_sections(self):
        paper = {"title": "A paper", "link": "https://publisher.example/a", "pdf_links": ["https://publisher.example/a.pdf"]}
        body = "The dataset is used for training. " * 20

        def fake_pdf(url):
            return b"%PDF-1.4", "read a PDF of 20 bytes from publisher.example"

        with (
            patch("apps.agents.usage.load_card_html", return_value=("", "", ["paper page: 403 from publisher.example"])),
            patch("apps.agents.usage.fetch_pdf", side_effect=fake_pdf),
            patch("apps.agents.usage.pdf_sections", return_value=[{"heading": "Methods", "text": body}]),
        ):
            sections, kind, notes = load_paper_sections(paper, "key")
        self.assertEqual(kind, "PDF")
        self.assertEqual(sections[0]["heading"], "Methods")
        self.assertTrue(any("Waiting for the PDF" in note for note in notes))

    def test_usable_html_is_kept_and_the_pdf_is_not_fetched(self):
        paper = {
            "title": "A paper",
            "link": "https://publisher.example/a",
            "pdf_links": ["https://publisher.example/a.pdf"],
            "versions_link": "https://scholar.example/versions",
        }
        html = "<h2>Methods</h2><p>" + ("The dataset is used for training. " * 20) + "</p>"
        with (
            patch("apps.agents.usage.load_card_html", return_value=(html, "paper page", [])),
            patch("apps.agents.usage.fetch_pdf") as fetch,
        ):
            sections, kind, _notes = load_paper_sections(paper, "key")
        fetch.assert_not_called()
        self.assertEqual(kind, "paper page")
        self.assertTrue(sections)

    def test_an_anthology_landing_page_opens_the_pdf(self):
        paper = {"title": "A paper", "link": "https://aclanthology.org/2025.bionlp-share.9/"}
        html = "<h1>A paper title</h1><p>Ada Lovelace BibTeX MODS XML Endnote " + ("citation " * 40) + "</p>"
        body = "The dataset is used for training. " * 30

        def fake_pdf(url):
            self.assertEqual(url, "https://aclanthology.org/2025.bionlp-share.9.pdf")
            return b"%PDF-1.4", "read a PDF of 20 bytes from aclanthology.org"

        with (
            patch("apps.agents.usage.load_card_html", return_value=(html, "paper page", [])),
            patch("apps.agents.usage.fetch_pdf", side_effect=fake_pdf),
            patch("apps.agents.usage.pdf_sections", return_value=[{"heading": "3 Methods", "text": body}]),
        ):
            sections, kind, notes = load_paper_sections(paper, "")
        self.assertEqual(kind, "PDF")
        self.assertEqual(sections[0]["heading"], "3 Methods")
        self.assertTrue(any("Waiting for the PDF" in note for note in notes))

    def test_counts_sum_to_the_sample(self):
        papers = [
            {"usage_class": "experimental_use", "card": {"dataset_role": "training"}},
            {"usage_class": "background_reference"},
            {"usage_class": "unclear"},
        ]
        counts = _counts(papers)
        self.assertEqual(counts["candidates"], 3)
        self.assertEqual(counts["users"] + counts["other"] + counts["unclear"], 3)


class UsageReportTests(unittest.TestCase):
    def test_the_html_report_names_the_sample_and_shows_a_card(self):
        html = render_report(
            {
                "project_title": "RadQA",
                "action_label": "Explore published research",
                "status": "completed",
                "result": {
                    "summary": "20 top-cited candidate papers.",
                    "groups": [],
                    "report": {
                        "retrieved_on": "2026-10-12",
                        "method": SAMPLE_NOTE,
                        "counts": {"candidates": 1, "users": 1, "other": 0, "unclear": 0},
                        "insights": {
                            "research_tasks": "Question answering on radiology reports.",
                            "methods_and_models": "A reader model.",
                            "setups_and_findings": "Accuracy on the held-out reports.",
                        },
                        "papers": [
                            {
                                "title": "A system for RadQA",
                                "link": "https://example.test/paper",
                                "byline": "Lee, 2024",
                                "cited_by_total": 4,
                                "usage_class": "experimental_use",
                                "label": "Used this dataset",
                                "confidence": "high",
                                "why": "The overview answered yes.",
                                "card": {
                                    "how_used": "The researchers used RadQA questions and report sections to build a reader.",
                                    "dataset_role": ["Training", "Testing"],
                                    "research_tasks": ["Question answering"],
                                    "techniques": ["Transformer"],
                                    "why_explore": "See how report sections were turned into question-answering examples.",
                                },
                            }
                        ],
                    },
                },
                "steps": [],
            }
        )
        self.assertIn("Used this dataset", html)
        self.assertIn("not a ranking", html)
        self.assertIn("stops at 10", html)
        self.assertIn("2026-10-12", html)
        self.assertIn("How the dataset was used", html)
        self.assertIn("Why explore this paper?", html)
        self.assertIn("Question answering", html)
        self.assertIn("turned into question-answering examples", html)
        self.assertNotIn("Evidence rows", html)
        self.assertNotIn("How the agent got there", html)
        self.assertLess(html.index("<h2>Used this dataset</h2>"), html.index("Across these papers"))
        self.assertIn("<article class='usage-card'>", html)

    def test_papers_are_grouped_and_every_row_is_a_card(self):
        html = render_report(
            {
                "project_title": "RadQA",
                "status": "completed",
                "result": {
                    "report": {
                        "retrieved_on": "2026-10-12",
                        "method": "stops at 10",
                        "counts": {"candidates": 3, "users": 1, "other": 1, "unclear": 1},
                        "papers": [
                            {"title": "Unread paper", "usage_class": "unclear", "why": "The paper text could not be read."},
                            {"title": "Other paper", "usage_class": "background_reference", "why": "It cites the dataset in related work."},
                            {
                                "title": "Used paper",
                                "usage_class": "experimental_use",
                                "card": {"how_used": "Training examples.", "why_explore": "See the split."},
                            },
                        ],
                    }
                },
                "steps": [],
            }
        )
        used_at = html.index("<h2>Used this dataset</h2>")
        other_at = html.index("<h2>Does not use it</h2>")
        unread_at = html.index("<h2>Could not be read</h2>")
        self.assertLess(used_at, other_at)
        self.assertLess(other_at, unread_at)
        self.assertNotIn("<article class='paper'>", html)
        self.assertEqual(html.count("<article class='usage-card'>"), 3)


class ReadingTests(unittest.TestCase):
    def test_a_paper_that_does_not_use_the_dataset_still_gets_a_reason(self):
        sections = [{"heading": "Methods", "text": "The parsers were compared on clinical notes. " * 20}]

        def fake_read(paper, _dataset, _source):
            if "Uses" in paper["title"]:
                return {
                    "card": {
                        "how_used": "Training examples.",
                        "dataset_role": ["Training"],
                        "research_tasks": ["Question answering"],
                        "techniques": ["Transformer"],
                        "why_explore": "See the split.",
                    },
                    "explore": None,
                }
            return {
                "card": None,
                "explore": {"why_open": "The paper compares two parsers on clinical notes.", "research_tasks": ["Parsing"], "techniques": []},
            }

        with (
            patch("apps.agents.published.load_paper_sections", return_value=(sections, "PDF", [])),
            patch("apps.agents.published.read_paper", side_effect=fake_read),
            patch("apps.agents.published.append_log"),
            patch("apps.agents.published.remember", side_effect=lambda current, item: [*(current.get("steps") or []), item]),
        ):
            result = usage_cards(
                {
                    "run_id": "run",
                    "project": {"title": "RadQA"},
                    "steps": [],
                    "candidates": [
                        {"title": "Uses the dataset", "routing": "report_only"},
                        {"title": "A parser paper", "routing": "report_only"},
                    ],
                }
            )
        papers = result["candidates"]
        self.assertEqual(papers[0]["usage_class"], "experimental_use")
        self.assertIsNone(papers[1]["card"])
        self.assertIn("parsers", papers[1]["explore"]["why_open"])


if __name__ == "__main__":
    unittest.main()

"""Find similar resources: quotes, catalog peers, and the comparison report."""

import unittest

from unittest.mock import patch

from apps.agents.resources import (
    build_queries,
    catalog_card,
    explain_similar,
    family_projects,
    keep_quoted,
    plain_insight,
    rank_catalog,
    web_cards,
    why_line,
)
from apps.backend.catalog_view import actions_for
from apps.backend.report import render_report


class QuoteTests(unittest.TestCase):
    def test_a_value_without_a_quote_in_the_text_is_dropped(self):
        text = "This database contains a chest radiograph from one hospital."
        reading = {
            "modality": ["chest radiograph"],
            "tasks": ["report generation"],
            "peer_hints": ["PadChest", "MIMIC-CXR"],
            "evidence": [
                {"field": "modality", "value": "chest radiograph", "quote": "contains a chest radiograph from one hospital"},
                {"field": "task", "value": "report generation", "quote": "The model invented this sentence about report generation."},
            ],
        }
        kept = keep_quoted(reading, text, allow_hints=True, title="MIMIC-CXR: a chest radiograph database")
        self.assertEqual(kept["modality"], ["chest radiograph"])
        self.assertEqual(kept["tasks"], [])
        self.assertEqual(kept["peer_hints"], ["PadChest"])

    def test_queries_stay_specific_and_stop_at_four(self):
        queries = build_queries(
            {"title": "MIMIC-CXR: chest radiographs", "resource_type": "Database"},
            {"peer_hints": ["PadChest", "VinDr-CXR", "NIH ChestX-ray14"], "modality": ["chest radiograph"], "tasks": ["classification"]},
        )
        self.assertLessEqual(len(queries), 4)
        self.assertIn("MIMIC-CXR", queries[0])
        self.assertIn("PadChest", " ".join(queries))
        self.assertNotIn("NIH", " ".join(queries))
        bare = " ".join(build_queries({"title": "ECG", "resource_type": "Database"}, {"peer_hints": ["figshare"]}))
        self.assertNotIn("figshare", bare)


class WebHitTests(unittest.TestCase):
    def test_a_blocked_page_stays_when_the_search_result_is_a_dataset(self):
        project = {"title": "A large scale 12-lead electrocardiogram database for arrhythmia study"}
        cards = web_cards(
            project,
            [
                {
                    "title": "A 12-lead electrocardiogram database for arrhythmia research",
                    "link": "https://www.scilit.com/publications/example",
                    "snippet": "This database contains 12-lead ECGs.",
                    "relation": "unread",
                },
                {
                    "title": "ecg_data",
                    "link": "https://www.kaggle.com/datasets/example",
                    "snippet": "ECG heartbeat dataset for arrhythmia classification.",
                    "relation": "unread",
                },
                {
                    "title": "How to Share, Cite or Embed your items",
                    "link": "https://info.figshare.com/user-guide/how-to-share",
                    "snippet": "Learn how to share your items.",
                    "relation": "peer",
                },
            ],
        )
        titles = [card["title"] for card in cards]
        self.assertEqual(len(cards), 2)
        self.assertNotIn("How to Share, Cite or Embed your items", titles)
        self.assertIn("search result", cards[0]["why"])
        self.assertEqual(cards[0]["relation"], "web")


class CatalogTests(unittest.TestCase):
    def test_family_links_are_separate_from_peers(self):
        html = '<a href="https://physionet.org/content/mimic-cxr/2.1.0/">parent</a>'
        family = family_projects(html, "lung-segment-mimic-cxr")
        self.assertTrue(any(item["slug"] == "mimic-cxr" for item in family))
        peers = rank_catalog(
            {"slug": "lung-segment-mimic-cxr", "subject": ["heart"], "data_form": ["images"], "topics": []},
            [
                {"slug": "mimic-cxr", "title": "Parent", "subject": ["heart"], "data_form": ["images"], "topics": []},
                {"slug": "other", "title": "Other", "subject": ["heart"], "data_form": [], "topics": []},
            ],
            {"mimic-cxr"},
        )
        self.assertEqual([item["slug"] for item in peers], ["other"])

    def test_a_shared_subject_is_same_and_a_different_kind_is_different(self):
        card = catalog_card(
            {"subject": ["heart"], "data_form": ["signals"], "resource_type": "Database", "access_policy": "Credentialed"},
            {"title": "Tool", "source_url": "https://physionet.org/content/tool/1.0.0/", "subject": ["heart"], "data_form": ["text"], "resource_type": "Software", "access_policy": "Open"},
        )
        verdicts = {item["field"]: item["verdict"] for item in card["dimensions"]}
        self.assertEqual(verdicts["Subject"], "same")
        self.assertEqual(verdicts["Data"], "different")
        self.assertEqual(verdicts["Kind"], "different")
        self.assertIn("Same subject", why_line(card["dimensions"]))


class ReportTests(unittest.TestCase):
    def test_every_project_offers_the_two_agents(self):
        for kind in ("Database", "Challenge", "Software", "Model"):
            labels = [item["label"] for item in actions_for({"resource_type": kind})]
            self.assertEqual(labels, ["Explore published research", "Find similar resources"])

    def test_the_report_uses_dimension_pills(self):
        html = render_report(
            {
                "project_title": "MIMIC-CXR",
                "status": "completed",
                "updated_at": "2026-10-12T00:00:00+00:00",
                "result": {
                    "report": {
                        "kind": "resources",
                        "retrieved_on": "2026-10-12",
                        "method": "This is not a ranking of every resource.",
                        "summary": "1 resources in this catalog share a subject.",
                        "seed": {"title": "MIMIC-CXR", "url": "https://physionet.org/content/mimic-cxr/2.1.0/", "kind": "Database", "access": "Credentialed", "subjects": ["Heart"], "forms": [], "modality": ["chest radiograph"], "tasks": [], "population": ""},
                        "catalog": [
                            {"title": "Other", "link": "https://example.org/other", "kind": "Software", "access": "Open", "relation": "peer", "dimensions": [{"field": "Subject", "verdict": "same"}, {"field": "Kind", "verdict": "different"}], "why": "Same subject. Kind differ."},
                        ],
                        "outside": [
                            {"title": "Unread", "link": "https://example.org/unread", "kind": "", "access": "", "relation": "unread", "dimensions": [], "why": "The page could not be read."},
                            {"title": "Chest dataset", "link": "https://example.org/chest", "kind": "", "access": "", "relation": "web", "dimensions": [], "why": "A chest radiograph dataset."},
                        ],
                        "family": [],
                    }
                },
            }
        )
        self.assertIn("This resource", html)
        self.assertIn("Same subject", html)
        self.assertIn("Different kind", html)
        self.assertIn("Insight", html)
        self.assertNotIn("The page could not be read.", html)
        self.assertIn("Chest dataset", html)
        self.assertIn("A chest radiograph dataset.", html)
        self.assertIn("not a ranking", html)
        self.assertNotIn("Evidence rows", html)
        self.assertIn("class='usage-card'", html)


class ExplainTests(unittest.TestCase):
    def test_a_card_with_no_shared_field_is_dropped_and_the_model_writes_the_insight(self):
        cards = [
            {
                "title": "Tool",
                "kind": "Software",
                "access": "Open",
                "bucket": "catalog",
                "dimensions": [
                    {"field": "Subject", "verdict": "same", "detail": "Heart"},
                    {"field": "Kind", "verdict": "different", "detail": "Database on this project, Software on the other"},
                ],
                "line": "Same subject. Kind differs.",
                "why": "Same subject. Kind differs.",
            },
            {
                "title": "Nope",
                "kind": "Database",
                "access": "",
                "bucket": "outside",
                "dimensions": [
                    {"field": "Task", "verdict": "different", "detail": "classification on this project, detection on the other"},
                    {"field": "Kind", "verdict": "different", "detail": "Software on this project, Database on the other"},
                ],
                "line": "Task and kind differ.",
                "why": "Task and kind differ.",
            },
        ]

        class Note:
            def __init__(self, title, explanation):
                self.title = title
                self.explanation = explanation

        class Batch:
            notes = [Note("Tool", "Both cover the heart. Tool is software and the source is a database.")]

        with patch("apps.agents.resources.ask", return_value=Batch()):
            kept = explain_similar({}, {"title": "Seed", "kind": "Database", "subjects": ["Heart"]}, cards)
        self.assertEqual([card["title"] for card in kept], ["Tool"])
        self.assertIn("heart", kept[0]["why"].casefold())
        self.assertNotIn("line", kept[0])

    def test_the_insight_names_both_resources(self):
        text = plain_insight(
            {"title": "CXR-LT: Multi-Label", "kind": "Challenge", "access": "Credentialed"},
            {
                "title": "Chest ImaGenome Dataset",
                "kind": "Database",
                "access": "Credentialed",
                "about": "The Chest ImaGenome dataset is a scene graph dataset for chest X-rays.",
                "dimensions": [
                    {"field": "Data", "verdict": "same", "detail": "Images, Chest imaging"},
                    {"field": "Kind", "verdict": "different", "detail": "Challenge on this project, Database on the other"},
                    {"field": "Access", "verdict": "same", "detail": "Credentialed"},
                ],
            },
        )
        self.assertIn("Chest ImaGenome Dataset is a database.", text)
        self.assertIn("CXR-LT is a challenge.", text)
        self.assertIn("scene graph", text)
        self.assertNotIn("on this project", text)
        self.assertNotIn("on the other", text)


if __name__ == "__main__":
    unittest.main()

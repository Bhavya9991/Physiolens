"""Pagination, the HTML report, and SerpAPI response handling."""

import os
import unittest
from unittest.mock import patch

from apps.agents.llm import endpoint, require_model
from apps.backend.catalog_view import list_projects, overview
from apps.backend.report import render_report
from apps.agents.pages import fetch_public_text
from apps.backend.scholar import google_overview, search_scholar


class BrowseTests(unittest.TestCase):
    def test_doors_use_plain_names(self):
        labels = [door["label"] for door in overview()["doors"]]
        self.assertEqual(labels, ["Clinical subject", "Kind of data"])
        heart = overview()["doors"][0]["nodes"][0]
        self.assertIn("cardiovascular", heart["blurb"].casefold())

    def test_project_list_is_paged(self):
        first = list_projects(hierarchy="subject", node="heart", page=1, page_size=25)
        second = list_projects(hierarchy="subject", node="heart", page=2, page_size=25)
        self.assertEqual(first["total"], 184)
        self.assertEqual(len(first["projects"]), 25)
        self.assertEqual(first["page_count"], 8)
        self.assertNotEqual(first["projects"][0]["slug"], second["projects"][0]["slug"])


class ReportTests(unittest.TestCase):
    def test_html_report_has_summary_cards_and_a_filter(self):
        html = render_report(
            {
                "project_title": "MIT-BIH Arrhythmia Database",
                "action_label": "Explore scholarly research",
                "status": "completed",
                "created_at": "2026-10-10T00:00:00+00:00",
                "updated_at": "2026-10-10T00:01:00+00:00",
                "error": "",
                "result": {"summary": "A short brief.", "groups": []},
                "steps": [
                    {
                        "title": "Searched Scholar",
                        "why": "Quoted title.",
                        "engine": "google_scholar",
                        "query": '"MIT-BIH Arrhythmia Database"',
                        "items": [
                            {
                                "title": "The impact of the MIT-BIH arrhythmia database",
                                "link": "https://example.test/paper",
                                "detail": "A snippet.",
                                "label": "snippet",
                                "access": "",
                            }
                        ],
                    }
                ],
            }
        )
        self.assertIn("<h1>MIT-BIH Arrhythmia Database</h1>", html)
        self.assertIn("Evidence", html)
        self.assertIn('id="filter"', html)
        self.assertIn("The impact of the MIT-BIH arrhythmia database", html)
        self.assertNotIn("```", html)


class AgentRouteTests(unittest.TestCase):
    def test_groq_is_a_provider_switch_and_not_a_different_agent(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "groq", "GROQ_MODEL": "", "GROQ_BASE_URL": ""}, clear=False):
            chosen = endpoint()
        self.assertEqual(chosen["provider"], "groq")
        self.assertEqual(chosen["model"], "openai/gpt-oss-120b")
        self.assertEqual(chosen["base_url"], "https://api.groq.com/openai/v1")
        self.assertNotIn("api_key", chosen)

    def test_missing_model_key_fails_before_a_search(self):
        import os

        previous = os.environ.pop("OPENAI_API_KEY", None)
        provider = os.environ.get("LLM_PROVIDER")
        os.environ["LLM_PROVIDER"] = "gemini"
        try:
            with self.assertRaises(RuntimeError):
                require_model()
        finally:
            if previous:
                os.environ["OPENAI_API_KEY"] = previous
            if provider is None:
                os.environ.pop("LLM_PROVIDER", None)
            else:
                os.environ["LLM_PROVIDER"] = provider


class ScholarQueryTests(unittest.TestCase):
    def test_no_results_message_is_an_empty_list(self):
        with patch("apps.backend.scholar.httpx.get", return_value=_json_response({"error": "Google hasn't returned any results for this query."})) as request:
            self.assertEqual(search_scholar('"Visual Question Answering evaluation dataset for MIMIC CXR"', "test-key"), [])
        self.assertIs(request.call_args.kwargs["params"]["no_cache"], True)

    def test_a_real_serp_error_still_fails(self):
        with patch("apps.backend.scholar.httpx.get", return_value=_json_response({"error": "Your account has run out of searches."})):
            with self.assertRaises(RuntimeError):
                search_scholar("MIMIC-CXR", "test-key")

    def test_overview_token_is_fetched_immediately(self):
        calls = []

        def fake_payload(_key, **params):
            calls.append(params["engine"])
            if params["engine"] == "google":
                return {"organic_results": [], "ai_overview": {"page_token": "tok"}}
            return {
                "ai_overview": {
                    "text_blocks": [{"snippet": "Introduced in Paper X."}],
                    "references": [{"title": "Paper X", "link": "https://example.test/x", "snippet": "A paper."}],
                }
            }

        with patch("apps.backend.scholar._payload", side_effect=fake_payload):
            found = google_overview("which paper", "test-key")
        self.assertEqual(calls, ["google", "google_ai_overview"])
        self.assertIn("Paper X", found["text"])
        self.assertEqual(found["references"][0]["link"], "https://example.test/x")

    def test_private_pages_are_not_fetched(self):
        self.assertEqual(fetch_public_text("http://127.0.0.1/secret"), "")
        self.assertEqual(fetch_public_text("http://169.254.169.254/latest"), "")
        self.assertEqual(fetch_public_text("file:///etc/passwd"), "")


def _json_response(payload):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    return Response()


if __name__ == "__main__":
    unittest.main()

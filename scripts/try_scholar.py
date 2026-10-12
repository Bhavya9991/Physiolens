"""Prove the SerpAPI key works before the web page is involved.

Run from the project folder, with the virtual environment active:

    uv run python scripts/try_scholar.py
    uv run python scripts/try_scholar.py "MIMIC-IV mortality prediction"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.backend.paths import ENV_PATH
from apps.backend.scholar import search_scholar


def main() -> None:
    load_dotenv(ENV_PATH)
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key:
        print("Set SERPAPI_API_KEY in .env (copy .env.sample to .env first).")
        sys.exit(1)

    query = " ".join(sys.argv[1:]).strip() or "MIMIC-III intensive care"
    print(f"Query: {query}\n")
    papers = search_scholar(query, api_key)
    if not papers:
        print("No organic results returned.")
        return

    for index, paper in enumerate(papers, start=1):
        print(f"{index}. {paper['title']}")
        if paper["summary"]:
            print(f"   {paper['summary']}")
        if paper["link"]:
            print(f"   {paper['link']}")
        print()


if __name__ == "__main__":
    main()

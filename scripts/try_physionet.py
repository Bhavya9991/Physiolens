"""Build a PhysioNet browse seed from the public catalog.

The seed keeps two overlapping browse trees, plus fields that only narrow a list.

Run from the project folder, with the virtual environment active:

    uv run python scripts/try_physionet.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.backend.catalog import PUBLISHED_URL, build_seed, tree_counts
from apps.backend.paths import DATA_DIR

SEED_PATH = DATA_DIR / "physionet_catalog.json"


def fetch_published() -> list[dict]:
    response = httpx.get(
        PUBLISHED_URL,
        timeout=90.0,
        headers={
            "Accept": "application/json",
            "User-Agent": "PhysioLens-browse/0.1",
        },
    )
    response.raise_for_status()
    projects = response.json()
    if not isinstance(projects, list):
        raise RuntimeError("PhysioNet catalog did not return a list.")
    return projects


def main() -> None:
    projects = fetch_published()
    seed = build_seed(projects)
    SEED_PATH.parent.mkdir(exist_ok=True)
    SEED_PATH.write_text(json.dumps(seed, indent=2) + "\n")

    print(f"Source rows: {seed['source_rows']}")
    print(f"Latest projects in seed: {seed['project_count']}")
    print(f"Wrote {SEED_PATH}")
    print()
    for label, count in tree_counts(seed):
        print(f"{label} ({count})")


if __name__ == "__main__":
    main()

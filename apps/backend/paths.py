"""Project folders. One place so moving a file does not break data or web paths."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"
ENV_PATH = ROOT / ".env"

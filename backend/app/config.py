"""Configuration via environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
try:
    DATA_DIR.mkdir(exist_ok=True)
except FileExistsError:
    pass

DB_PATH = DATA_DIR / "flowpilot.db"
DATABASE_URL = os.environ.get("FLOWPILOT_DB", f"sqlite:///{DB_PATH}")

# Admin UI + management API require this bearer token.
ADMIN_TOKEN = os.environ.get("FLOWPILOT_ADMIN_TOKEN", "demo-admin-token")

# Optional LLM upgrade for `llm` steps.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_MODEL = os.environ.get("FLOWPILOT_LLM_MODEL", "gpt-4o-mini")

MAX_STEP_ATTEMPTS = int(os.environ.get("FLOWPILOT_MAX_ATTEMPTS", "5"))
BACKOFF_BASE_SECONDS = float(os.environ.get("FLOWPILOT_BACKOFF_BASE", "1.5"))

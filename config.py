"""Central configuration: paths and pacing knobs (all overridable via .env)."""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # read .env before anything else reads os.environ

import os

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "talent.db"
PROFILE_DIR = BASE_DIR / "browser_profile"  # persistent LinkedIn login lives here
FIXTURES_DIR = BASE_DIR / "fixtures"

# --- pacing / safety knobs -------------------------------------------------
# Keep these small. The whole point of the POC is to be boring and slow.
# See README ("Safety rules") before raising any of them.
MIN_DELAY_S = float(os.getenv("CRAWL_MIN_DELAY_S", "6"))        # min seconds between page loads
MAX_DELAY_S = float(os.getenv("CRAWL_MAX_DELAY_S", "14"))       # max seconds between page loads
MAX_PAGES_PER_RUN = int(os.getenv("CRAWL_MAX_PAGES_PER_RUN", "3"))  # hard ceiling per run
DAILY_PAGE_CAP = int(os.getenv("CRAWL_DAILY_PAGE_CAP", "20"))   # page loads per calendar day

DATA_DIR.mkdir(parents=True, exist_ok=True)
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

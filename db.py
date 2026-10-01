"""SQLite storage: profile stubs + a tiny event log that enforces the daily cap."""
import sqlite3
from datetime import datetime

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    profile_url   TEXT PRIMARY KEY,   -- canonical https://www.linkedin.com/in/<slug>
    name          TEXT,
    headline      TEXT,
    location      TEXT,
    company       TEXT,
    source_query  TEXT,
    found_at      TEXT NOT NULL,
    classified_at TEXT,
    role_fit      TEXT,               -- frontend | ui_ux | both | related | other
    seniority     TEXT,               -- intern | junior | mid | senior | lead | unknown
    country       TEXT,               -- ISO-2 guess or 'unknown'
    in_sea        INTEGER,            -- 0/1
    relevance     REAL,               -- 0..10
    reason        TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,               -- e.g. 'page_load'
    ts   TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def upsert_profile(conn: sqlite3.Connection, stub: dict, source_query: str) -> int:
    """Insert a stub; returns 1 if new, 0 if we had it already (dedupe by URL)."""
    cur = conn.execute(
        """INSERT INTO profiles (profile_url, name, headline, location, source_query, found_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(profile_url) DO NOTHING""",
        (
            stub["profile_url"],
            stub.get("name"),
            stub.get("headline"),
            stub.get("location"),
            source_query,
            _now_iso(),
        ),
    )
    conn.commit()
    return cur.rowcount


def pages_loaded_today(conn: sqlite3.Connection) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    cur = conn.execute(
        "SELECT COUNT(*) FROM events WHERE kind = 'page_load' AND substr(ts, 1, 10) = ?",
        (today,),
    )
    return cur.fetchone()[0]


def log_event(conn: sqlite3.Connection, kind: str) -> None:
    conn.execute("INSERT INTO events (kind, ts) VALUES (?, ?)", (kind, _now_iso()))
    conn.commit()


def unclassified(conn: sqlite3.Connection) -> list:
    return conn.execute(
        "SELECT * FROM profiles WHERE classified_at IS NULL ORDER BY found_at"
    ).fetchall()


def save_classification(conn: sqlite3.Connection, url: str, c: dict) -> None:
    conn.execute(
        """UPDATE profiles
           SET classified_at = ?, role_fit = ?, seniority = ?, country = ?,
               in_sea = ?, relevance = ?, reason = ?
           WHERE profile_url = ?""",
        (
            _now_iso(),
            c.get("role_fit"),
            c.get("seniority"),
            c.get("country"),
            1 if c.get("in_sea") else 0,
            float(c.get("relevance") or 0),
            c.get("reason"),
            url,
        ),
    )
    conn.commit()


def all_profiles(conn: sqlite3.Connection) -> list:
    return conn.execute("SELECT * FROM profiles ORDER BY relevance DESC, found_at DESC").fetchall()

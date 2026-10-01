"""Export stored profiles to CSV (UTF-8 with BOM so Excel opens it cleanly)."""
import csv
from pathlib import Path

import db
from config import DATA_DIR

COLUMNS = [
    "profile_url", "name", "headline", "location", "company", "source_query",
    "found_at", "classified_at", "role_fit", "seniority", "country", "in_sea",
    "relevance", "reason",
]


def run(out=None, min_score=None, only_sea=False, roles=None) -> Path:
    conn = db.connect()
    db.init()
    rows = db.all_profiles(conn)
    if min_score is not None:
        rows = [r for r in rows if (r["relevance"] or 0) >= min_score]
    if only_sea:
        rows = [r for r in rows if r["in_sea"]]
    if roles:
        rows = [r for r in rows if r["role_fit"] in roles]

    out_path = Path(out) if out else DATA_DIR / "talent_export.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r[c] for c in COLUMNS])
    print(f"Exported {len(rows)} profiles -> {out_path}")
    return out_path

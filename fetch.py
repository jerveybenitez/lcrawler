"""Fetch full profile pages for stored stubs, slowly, and save the details.

Profile pages are the most-scrutinized pages on LinkedIn, so pacing is harder
than for search: a randomized 30-120s wait BEFORE each profile load, a small
per-run ceiling, and the same per-day page cap as search (every profile load
logs a page_load event).

The FIRST profile's raw HTML is auto-saved to fixtures/ so profile_parser can
be verified against real markup before any batch run.
"""
import random
import time
from datetime import datetime

import config
import db
import profile_parser
from browser import looks_logged_out, session


def _fetch_delay() -> None:
    t = random.uniform(config.FETCH_MIN_DELAY_S, config.FETCH_MAX_DELAY_S)
    print(f"  ...waiting {t:.0f}s before next profile (hard pacing)")
    time.sleep(t)


def run(limit=None, min_score=None, only_sea=False, roles=None) -> None:
    conn = db.connect()
    db.init()

    limit = min(limit or config.MAX_FETCHES_PER_RUN, config.MAX_FETCHES_PER_RUN)
    budget = config.DAILY_PAGE_CAP - db.pages_loaded_today(conn)
    if budget <= 0:
        print(f"Daily page cap reached ({config.DAILY_PAGE_CAP}). Try again tomorrow.")
        return
    if limit > budget:
        print(f"Trimming to {budget} fetch(es) to respect the daily cap.")
        limit = budget

    queue = db.fetch_queue(conn, limit, min_score=min_score, roles=roles, only_sea=only_sea)
    if not queue:
        print("Nothing to fetch: every stored profile is already fetched,")
        print("or the filters matched none. Try:  python cli.py stats")
        return
    print(f"Fetch queue: {len(queue)} profile(s)")

    saved_fixture = False
    with session() as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for i, row in enumerate(queue):
            url = row["profile_url"]
            _fetch_delay()  # BEFORE the load: even an aborted run looks human
            print(f"[{i + 1}/{len(queue)}] {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as e:
                print(f"  (load raised {type(e).__name__}: {str(e)[:100]} - continuing)")
            page.wait_for_timeout(3000)  # let lazy profile sections render
            if looks_logged_out(page):
                print("!! Login wall / challenge detected - aborting.")
                print("   Run:  python cli.py login")
                return
            db.log_event(conn, "page_load")
            html = page.content()

            if not saved_fixture:
                out = config.FIXTURES_DIR / f"profile_{datetime.now():%Y%m%d_%H%M%S}.html"
                out.write_text(html, encoding="utf-8")
                print(f"  first profile saved as fixture: {out}")
                saved_fixture = True

            detail = profile_parser.parse_profile_page(html)
            db.save_profile_detail(conn, url, detail)
            counts = {k: len((detail.get(k) or "").strip())
                      for k in ("about", "experience", "education")}
            print(f"  saved: about={counts['about']}ch "
                  f"experience={counts['experience']}ch education={counts['education']}ch")
            if sum(counts.values()) == 0:
                print("  !! parser extracted NOTHING - fixture saved above; tune")
                print("     profile_parser.py against it, then re-run fetch.")

    print("Done.")

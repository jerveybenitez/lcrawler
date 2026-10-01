"""Run ONE people-search query, slowly, and store the profile stubs.

Pacing is the safety mechanism: randomized delays between loads, a per-run
page ceiling, and a per-day page cap enforced through the events table.
"""
import random
import time
from urllib.parse import quote_plus

import config
import db
import search_parser
from browser import looks_logged_out, session

SEARCH_URL = "https://www.linkedin.com/search/results/people/?keywords={}"


def human_delay(lo=None, hi=None) -> None:
    t = random.uniform(
        config.MIN_DELAY_S if lo is None else lo,
        config.MAX_DELAY_S if hi is None else hi,
    )
    print(f"  ...waiting {t:.0f}s (human pacing)")
    time.sleep(t)


def run(keywords: str, pages=None) -> None:
    pages = min(pages or config.MAX_PAGES_PER_RUN, config.MAX_PAGES_PER_RUN)
    conn = db.connect()
    db.init()

    budget = config.DAILY_PAGE_CAP - db.pages_loaded_today(conn)
    if budget <= 0:
        print(f"Daily page cap reached ({config.DAILY_PAGE_CAP}). Try again tomorrow.")
        return
    if pages > budget:
        print(f"Trimming to {budget} page(s) to respect the daily cap.")
        pages = budget

    total_new = 0
    with session() as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        url = SEARCH_URL.format(quote_plus(keywords))
        print(f"Opening: {url}")
        page.goto(url, wait_until="domcontentloaded")
        human_delay()

        for i in range(pages):
            if looks_logged_out(page):
                print("!! Login wall / challenge detected.")
                print("   Run:  python cli.py login   (and log in by hand)")
                return
            db.log_event(conn, "page_load")
            cards = search_parser.parse_search_page(page.content())
            new = sum(db.upsert_profile(conn, c, keywords) for c in cards)
            total_new += new
            print(f"  page {i + 1}/{pages}: {len(cards)} profiles on page, {new} new")

            if i == pages - 1:
                break
            nxt = page.query_selector('button[aria-label="Next"]')
            if not nxt:
                print("  no more result pages for this query")
                break
            human_delay()
            nxt.click()
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                pass
            human_delay()

    print(f"Done. {total_new} new profile(s) saved to the database.")

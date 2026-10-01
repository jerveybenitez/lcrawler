"""Entry point for the LinkedIn SEA-talent POC.

Typical flow:
  python cli.py login                                          # once, by hand
  python cli.py capture --name frontend_manila                 # save a real fixture
  python cli.py parse <fixture.html>                           # verify the parser
  python cli.py search --keywords '"frontend developer" Manila' --pages 2
  python cli.py classify                                       # Qwen
  python cli.py export --only-sea --min-score 6
  python cli.py stats
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import config
import db
import search_parser


def cmd_login(args):
    from browser import looks_logged_out, session

    with session() as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        if not looks_logged_out(page):
            print("Already logged in. Session is kept in browser_profile/.")
            return
        print("A browser window is open. Log in BY HAND (email + password + 2FA).")
        print("Waiting for LinkedIn to let you through (max 10 minutes)...")
        deadline = time.time() + 600
        while time.time() < deadline:
            if not looks_logged_out(page):
                print("Logged in OK. Session saved in browser_profile/ - future runs")
                print("reuse it automatically until LinkedIn expires the session.")
                return
            time.sleep(2)
        print("Timed out waiting for login. Run `python cli.py login` and try again.")


def cmd_capture(args):
    from browser import session

    print("A browser window will open. In it, navigate to any LinkedIn PEOPLE SEARCH")
    print("results page (the list of person cards). I will detect it and save the")
    print("page HTML as a parser fixture. No automated actions are taken.")
    with session() as ctx:
        deadline = time.time() + 600
        target = None
        while time.time() < deadline and target is None:
            for p in ctx.pages:
                if "/search/results/people/" in (p.url or ""):
                    target = p
                    break
            time.sleep(1)
        if target is None:
            print("Timed out waiting for a people-search page.")
            return
        html = target.content()
        out = config.FIXTURES_DIR / f"{args.name}_{datetime.now():%Y%m%d_%H%M%S}.html"
        out.write_text(html, encoding="utf-8")
        print(f"Fixture saved: {out}")
        print(f'Verify the parser:  python cli.py parse "{out}"')


def cmd_parse(args):
    html = Path(args.file).read_text(encoding="utf-8")
    cards = search_parser.parse_search_page(html)
    print(f"Parsed {len(cards)} profile stub(s) from {args.file}")
    for c in cards:
        print(f"  - {c.get('name') or '(no name)'} | {c.get('headline') or ''} | "
              f"{c.get('location') or ''}")
    if args.save:
        conn = db.connect()
        db.init()
        n = sum(db.upsert_profile(conn, c, f"fixture:{Path(args.file).name}") for c in cards)
        print(f"Saved {n} new stub(s) to the database.")


def cmd_search(args):
    import search

    search.run(args.keywords, pages=args.pages)


def cmd_classify(args):
    import classify

    classify.run(mock=args.mock, limit=args.limit)


def cmd_export(args):
    import export

    roles = {r.strip() for r in (args.role or "").split(",") if r.strip()}
    export.run(out=args.out, min_score=args.min_score, only_sea=args.only_sea, roles=roles)


def cmd_stats(args):
    conn = db.connect()
    db.init()
    total = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
    classified = conn.execute(
        "SELECT COUNT(*) FROM profiles WHERE classified_at IS NOT NULL"
    ).fetchone()[0]
    print(f"Profiles stored : {total} (classified: {classified})")
    print(f"Pages today     : {db.pages_loaded_today(conn)}/{config.DAILY_PAGE_CAP}")
    for r in conn.execute(
        "SELECT role_fit, COUNT(*) AS n FROM profiles WHERE role_fit IS NOT NULL "
        "GROUP BY role_fit ORDER BY n DESC"
    ):
        print(f"  {r['role_fit']:<10} {r['n']}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(prog="crawler", description="LinkedIn SEA-talent POC")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="Open browser; log in by hand once; session is saved"
                   ).set_defaults(func=cmd_login)

    p = sub.add_parser("capture", help="Save the current people-search page as a parser fixture")
    p.add_argument("--name", default="search", help="fixture name prefix")
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("parse", help="Parse an HTML file and print the stubs (offline test)")
    p.add_argument("file", help="path to an HTML file (fixture)")
    p.add_argument("--save", action="store_true", help="also insert stubs into SQLite")
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser("search", help="Run ONE people search, slowly, and store stubs")
    p.add_argument("--keywords", required=True, help='e.g. \'"frontend developer" Manila\'')
    p.add_argument("--pages", type=int, default=None, help=f"default {config.MAX_PAGES_PER_RUN}")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("classify", help="Classify unclassified stubs (Qwen)")
    p.add_argument("--mock", action="store_true", help="offline fake classifier (no key needed)")
    p.add_argument("--limit", type=int, default=None, help="only classify N profiles")
    p.set_defaults(func=cmd_classify)

    p = sub.add_parser("export", help="Export profiles to CSV")
    p.add_argument("--out", default=None, help="output CSV path (default data/talent_export.csv)")
    p.add_argument("--min-score", type=float, default=None, help="only relevance >= N")
    p.add_argument("--only-sea", action="store_true", help="only rows flagged in_sea")
    p.add_argument("--role", default=None, help="comma list, e.g. frontend,ui_ux,both")
    p.set_defaults(func=cmd_export)

    sub.add_parser("stats", help="Database + daily budget summary").set_defaults(func=cmd_stats)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

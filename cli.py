"""Entry point for the LinkedIn SEA-talent POC.

Typical flow:
  python cli.py login                                          # once, by hand
  python cli.py capture --name frontend_manila                 # save a real fixture
  python cli.py parse <fixture.html>                           # verify the parser
  python cli.py search --keywords '"frontend developer" Manila' --pages 2
  python cli.py classify                                       # Qwen
  python cli.py fetch --limit 2                                # full profiles, very slow
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
    from browser import has_session, looks_logged_out, session

    with session() as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded",
                      timeout=60_000)
        except Exception as e:
            print(f"Page load slow ({type(e).__name__}) - continuing with what loaded.")
        page.bring_to_front()
        try:
            print(f'Browser window is showing: "{(page.title() or "")[:60]}"')
        except Exception:
            pass
        if not looks_logged_out(page):
            print("Already logged in. Session is kept in browser_profile/.")
            return
        if has_session(ctx):
            print("Feed page is loading slowly, but the session cookie (li_at) is")
            print("ALREADY SAVED in browser_profile/. Login succeeded.")
            return

        print("A browser window is open. Log in BY HAND in that window")
        print("(email + password + 2FA / email PIN if asked).")
        print("Keep the window OPEN - I am watching it. Waiting up to 10 minutes...")
        url = page.url
        deadline = time.time() + 600
        last_report = 0.0
        while time.time() < deadline:
            try:
                if page.is_closed():
                    print("Browser window was closed before login finished.")
                    print("Run `python cli.py login` again and keep the window open")
                    print("until you see your LinkedIn feed.")
                    return
                url = page.url
            except Exception:
                print("Browser was closed mid-wait. Run `python cli.py login` again.")
                return
            if not looks_logged_out(page) or has_session(ctx):
                print("Logged in OK. Session saved in browser_profile/ - future runs")
                print("reuse it automatically until LinkedIn expires the session.")
                return
            if time.time() - last_report >= 20:
                elapsed = int(600 - (deadline - time.time()))
                print(f"  [{elapsed:>3}s] still logged out - browser is showing: {url[:80]}")
                if "/checkpoint" in url:
                    print("         ^ LinkedIn is running a security check - complete it")
                    print("           in the browser window (PIN/2FA) to continue.")
                last_report = time.time()
            time.sleep(2)
        print("Timed out waiting for login.")
        print(f"Last page the browser showed: {url[:120]}")
        if has_session(ctx):
            print("BUT the session cookie was saved - login may have worked anyway.")
            print("Check with:  python cli.py status")
        else:
            print("If that page was a checkpoint or verification screen, complete it")
            print("fully, then run `python cli.py login` again.")


def cmd_status(args):
    from browser import has_session, looks_logged_out, session

    with session() as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded",
                      timeout=60_000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        sess = has_session(ctx)
        logged_out = looks_logged_out(page)
        print(f"Session cookie (li_at) : {'present' if sess else 'MISSING'}")
        print(f"Feed reachable as user : {'yes' if not logged_out else 'no'}")
        if sess and not logged_out:
            print("STATUS: logged in - ready for capture / search runs.")
        elif sess and logged_out:
            print("STATUS: cookie present but LinkedIn is challenging the session.")
            print("Run `python cli.py login` and complete any checkpoint shown.")
        else:
            print("STATUS: logged out. Run `python cli.py login`.")


def cmd_capture(args):
    from urllib.parse import quote_plus

    from browser import looks_logged_out, session

    with session() as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if args.keywords:
            # Automatic mode: navigate straight to the people-search URL.
            conn = db.connect()
            db.init()
            budget = config.DAILY_PAGE_CAP - db.pages_loaded_today(conn)
            if budget <= 0:
                print(f"Daily page cap reached ({config.DAILY_PAGE_CAP})."
                      " Try again tomorrow.")
                return
            url = ("https://www.linkedin.com/search/results/people/?keywords="
                   + quote_plus(args.keywords))
            print(f"Opening: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as e:
                print(f"(load raised {type(e).__name__}: {str(e)[:120]} - continuing)")
            page.wait_for_timeout(5000)  # let the result list render
            if looks_logged_out(page):
                print("!! Login wall / challenge detected - fixture NOT saved.")
                print("   Run:  python cli.py login")
                return
            db.log_event(conn, "page_load")  # counts toward the daily budget
            html = page.content()
            out = config.FIXTURES_DIR / f"{args.name}_{datetime.now():%Y%m%d_%H%M%S}.html"
            out.write_text(html, encoding="utf-8")
            print(f"Fixture saved: {out}")
            n_links = html.count("/in/")
            print(f"profile-link markers (/in/) in page: {n_links}")
            if n_links == 0:
                print("!! No /in/ links found - results may not have rendered.")
                print("   Open the fixture in a browser to see what LinkedIn served.")
            print(f'Verify the parser:  python cli.py parse "{out}"')
            return

        # Manual fallback: watch for the user to reach a people-search page.
        print("A browser window will open, already logged in with your saved session.")
        print("Use the LinkedIn search box (filter: People) to run any people search,")
        print("or paste a https://www.linkedin.com/search/results/people/... URL")
        print("into the address bar. When the results list loads, I save that page")
        print("as a parser fixture.")
        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded",
                      timeout=60_000)
        except Exception as e:
            print(f"(feed page is slow: {type(e).__name__} - you can navigate manually)")
        page.bring_to_front()
        page.wait_for_timeout(4000)  # let LinkedIn's JS hydrate before you type
        print("Watching for a /search/results/people/ page (up to 10 minutes)...")
        deadline = time.time() + 600
        last_report = 0.0
        target = None
        while time.time() < deadline and target is None:
            try:
                if page.is_closed():
                    print("Browser window was closed before a search page appeared.")
                    return
            except Exception:
                print("Browser was closed mid-wait.")
                return
            for p in ctx.pages:
                if "/search/results/people/" in (p.url or ""):
                    target = p
                    break
            if time.time() - last_report >= 30:
                print(f"  ...waiting ({int(600 - (deadline - time.time()))}s in). "
                      "Run your people search in the browser window.")
                last_report = time.time()
            time.sleep(1)
        if target is None:
            print("Timed out waiting for a people-search page.")
            return
        try:
            html = target.content()
        except Exception as e:
            print(f"Could not read the page ({type(e).__name__}). Try capture again.")
            return
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


def cmd_fetch(args):
    import fetch

    roles = {r.strip() for r in (args.role or "").split(",") if r.strip()}
    fetch.run(limit=args.limit, min_score=args.min_score, only_sea=args.only_sea,
              roles=roles)


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

    sub.add_parser("status", help="Check whether the saved LinkedIn session is alive"
                   ).set_defaults(func=cmd_status)

    p = sub.add_parser("capture", help="Save a people-search page as a parser fixture")
    p.add_argument("--name", default="search", help="fixture name prefix")
    p.add_argument("--keywords", default=None,
                   help='auto-navigate to this people search, e.g. \'"frontend developer" Manila\'')
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

    p = sub.add_parser("fetch", help="Fetch full profiles (about/experience/education), slowly")
    p.add_argument("--limit", type=int, default=None,
                   help=f"default {config.MAX_FETCHES_PER_RUN}")
    p.add_argument("--min-score", type=float, default=None, help="only relevance >= N")
    p.add_argument("--only-sea", action="store_true", help="only rows flagged in_sea")
    p.add_argument("--role", default=None, help="comma list, e.g. frontend,ui_ux,both")
    p.set_defaults(func=cmd_fetch)

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

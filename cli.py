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

    sub.add_parser("status", help="Check whether the saved LinkedIn session is alive"
                   ).set_defaults(func=cmd_status)

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

"""Dedicated stealth browser session (Patchright = anti-detection-patched Playwright).

The login state (cookies, localStorage) lives in browser_profile/ on disk:
  - First time:  python cli.py login   -> a visible browser opens, you log in BY HAND
                 (email + password + 2FA). The session is saved to browser_profile/.
  - Every run after that reuses the saved session automatically.

Patchright is imported lazily so offline commands (parse/export/stats) work
even before `pip install patchright` browsers are set up.
"""
from contextlib import contextmanager

from config import PROFILE_DIR


@contextmanager
def session(headless: bool = False, **kwargs):
    """Open the persistent, logged-in browser context. Headed (visible) by
    default because headless mode is itself a bot signal.

    Extra kwargs (e.g. channel="chrome", no_viewport=True) are forwarded to
    launch_persistent_context - used for A/B stealth comparisons."""
    from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=headless,
            **kwargs,
        )
        try:
            yield ctx
        finally:
            ctx.close()


def looks_logged_out(page) -> bool:
    """Heuristic: LinkedIn sends us to an authwall/login/checkpoint URL when
    the session is dead or under challenge."""
    url = page.url or ""
    return any(marker in url for marker in ("/authwall", "/login", "checkpoint"))


def has_session(ctx) -> bool:
    """True if the profile holds LinkedIn's session cookie (li_at).

    Needed because LinkedIn sometimes accepts the login (sets the cookie)
    but then silently hangs the redirect to /feed/ - the URL stays on
    /login/ even though the session is live and saved on disk."""
    try:
        return any(c.get("name") == "li_at" and c.get("value") for c in ctx.cookies())
    except Exception:
        return False

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
def session(headless: bool = False):
    """Open the persistent, logged-in browser context. Headed (visible) by
    default because headless mode is itself a bot signal."""
    from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=headless,
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

"""Extract profile stubs from LinkedIn people-search HTML.

Two strategies, tried in order:
  1. JSON payloads embedded in <code> tags (Voyager data) - most stable, because
     LinkedIn rotates obfuscated CSS class names but keeps shipping the data.
  2. DOM heuristics on the entity-result markup - fallback.

Test offline (no LinkedIn access needed):
  python cli.py parse fixtures/synthetic_json_search.html
  python cli.py parse fixtures/synthetic_dom_search.html
"""
import json
import re

from bs4 import BeautifulSoup

try:
    import lxml  # noqa: F401

    _PARSER = "lxml"
except ImportError:  # pragma: no cover
    _PARSER = "html.parser"

_IN_URL = re.compile(r"linkedin\.com/in/([^/?#\"'\\]+)", re.IGNORECASE)


def canonical_url(url: str):
    """Normalize any /in/ link to https://www.linkedin.com/in/<slug>."""
    m = _IN_URL.search(url or "")
    return f"https://www.linkedin.com/in/{m.group(1)}" if m else None


def parse_search_page(html: str) -> list:
    """Return deduped stubs: {profile_url, name, headline, location}."""
    stubs = _from_json_blobs(html) or _from_dom(html)
    out = {}
    for s in stubs:
        u = canonical_url(s.get("profile_url", ""))
        if not u:
            continue
        if u not in out:
            s["profile_url"] = u
            out[u] = s
    return list(out.values())


# --- strategy 1: embedded JSON ----------------------------------------------

def _code_text(code) -> str:
    raw = code.string
    if raw is None:
        return ""
    raw = str(raw).strip()
    if raw.startswith("<!--"):
        raw = raw[4:]
    if raw.endswith("-->"):
        raw = raw[:-3]
    return raw.strip()


def _text(value) -> str:
    """Flatten Voyager text views: {"text": ...}, lists of them, or plain strings."""
    if isinstance(value, dict):
        return value.get("text") or ""
    if isinstance(value, list):
        return " ".join(t for t in (_text(v) for v in value) if t)
    return value if isinstance(value, str) else ""


def _from_json_blobs(html: str) -> list:
    soup = BeautifulSoup(html, _PARSER)
    stubs = []
    for code in soup.find_all("code"):
        raw = _code_text(code)
        if not raw.startswith("{"):
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        included = data.get("included", []) if isinstance(data, dict) else []
        for ent in included:
            if not isinstance(ent, dict):
                continue
            url = ent.get("navigationUrl") or ""
            if "/in/" not in url:
                continue
            stubs.append(
                {
                    "profile_url": url,
                    "name": _text(ent.get("title")),
                    "headline": _text(ent.get("primarySnippet")) or _text(ent.get("primarySubtitle")),
                    "location": _text(ent.get("subLine")),
                }
            )
    return stubs


# --- strategy 2: DOM heuristics (fallback if markup/class names change) -----

_DEGREE = re.compile(r"(1st|2nd|3rd\+?)\s*$")
_BULLET = "•"


def _from_dom(html: str) -> list:
    soup = BeautifulSoup(html, _PARSER)
    cards = {}

    # Modern markup (2025+): every result card contains a <p> with
    # "Name • 3rd+" (degree badge); its parent holds two sibling divs -
    # headline then location. Class names are hashed, this structure isn't.
    for p in soup.find_all("p"):
        t = p.get_text(" ", strip=True)
        if _BULLET not in t or not _DEGREE.search(t):
            continue
        a = p.find_parent("a", href=re.compile("/in/"))
        if not a:
            continue
        url = canonical_url(a.get("href", ""))
        if not url:
            continue
        entry = cards.setdefault(
            url, {"profile_url": url, "name": "", "headline": "", "location": ""}
        )
        entry["name"] = entry["name"] or t.split(_BULLET)[0].strip()
        sib_divs = [
            d.get_text(" ", strip=True)
            for d in p.parent.find_all("div", recursive=False)
            if d.get_text(" ", strip=True)
        ]
        if sib_divs:
            entry["headline"] = entry["headline"] or sib_divs[0]
        if len(sib_divs) > 1:
            entry["location"] = entry["location"] or sib_divs[1]
    if cards:
        return list(cards.values())

    # Legacy markup: stable entity-result class names (older pages, fixtures).
    for a in soup.select('a[href*="/in/"]'):
        u = canonical_url(a.get("href", ""))
        if not u:
            continue
        entry = cards.setdefault(
            u, {"profile_url": u, "name": "", "headline": "", "location": ""}
        )
        txt = a.get_text(" ", strip=True)
        if txt and not entry["name"]:
            entry["name"] = txt
        card = a.find_parent("li")
        if card is None:
            continue
        t = card.select_one(".entity-result__title-text")
        if t and not entry["name"]:
            entry["name"] = t.get_text(" ", strip=True)
        p = card.select_one(".entity-result__primary-subtitle")
        if p:
            entry["headline"] = p.get_text(" ", strip=True)
        s = card.select_one(".entity-result__secondary-subtitle")
        if s:
            entry["location"] = s.get_text(" ", strip=True)
    return [e for e in cards.values() if e["name"] or e["headline"]]

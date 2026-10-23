"""Extract about/experience/education from a full LinkedIn profile page.

Three strategies, each filling only the fields still empty:
  1. Voyager JSON embedded in <code> blobs (most structured when present).
  2. JSON-LD <script type="application/ld+json"> Person block.
  3. DOM heuristics: <section> blocks located by their heading text
     ("About" / "Experience" / "Education") - class names are hashed but
     heading text and the section/li structure survive.

The first live `fetch` auto-saves its raw HTML to fixtures/ so this parser
can be tuned against real markup before any batch run.
"""
import json
import re

from bs4 import BeautifulSoup

try:
    import lxml  # noqa: F401

    _PARSER = "lxml"
except ImportError:  # pragma: no cover
    _PARSER = "html.parser"

_HEADINGS = {
    "about": re.compile(r"^about$", re.IGNORECASE),
    "experience": re.compile(r"^experience$", re.IGNORECASE),
    "education": re.compile(r"^education$", re.IGNORECASE),
}


def parse_profile_page(html: str) -> dict:
    """Return {about, experience, education}; empty strings when not found."""
    detail = {"about": "", "experience": "", "education": ""}
    soup = BeautifulSoup(html, _PARSER)
    _from_json_blobs(soup, detail)
    _from_ld_json(soup, detail)
    _from_dom(soup, detail)
    return detail


# --- strategy 1: Voyager JSON in <code> blobs --------------------------------

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


def _fmt_date(d) -> str:
    if not isinstance(d, dict):
        return ""
    y, m = d.get("year"), d.get("month")
    if y and m:
        return f"{m:02d}/{y}"
    return str(y) if y else ""


def _fmt_period(tp) -> str:
    if not isinstance(tp, dict):
        return ""
    s, e = _fmt_date(tp.get("startDate")), _fmt_date(tp.get("endDate"))
    if s and e:
        return f"{s} - {e}"
    if s:
        return f"{s} - Present"
    return e


def _position_line(ent: dict) -> str:
    title = (ent.get("title") or "").strip()
    co = ent.get("companyName")
    if not co and isinstance(ent.get("company"), dict):
        co = ent["company"].get("name")
    co = (co or "").strip()
    loc = (ent.get("locationName") or "").strip()
    period = _fmt_period(ent.get("timePeriod"))
    head = " at ".join(p for p in (title, co) if p)
    tail = " | ".join(p for p in (period, loc) if p)
    return f"{head} ({tail})" if tail else head


def _education_line(ent: dict) -> str:
    school = (ent.get("schoolName") or "").strip()
    bits = [b for b in ((ent.get("degreeName") or "").strip(),
                        (ent.get("fieldOfStudy") or "").strip()) if b]
    if bits:
        school = f"{school}, {' '.join(bits)}" if school else " ".join(bits)
    period = _fmt_period(ent.get("timePeriod"))
    return f"{school} ({period})" if period and school else (school or period)


def _from_json_blobs(soup, detail) -> None:
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
            t = ent.get("$type") or ""
            if not isinstance(t, str) or ".profile." not in t:
                continue
            if t.endswith("profile.Profile"):
                detail["about"] = detail["about"] or (ent.get("summary") or "").strip()
            elif t.endswith("profile.Position"):
                line = _position_line(ent)
                if line and line not in detail["experience"]:
                    detail["experience"] = (detail["experience"] + "\n" + line).strip()
            elif t.endswith("profile.Education"):
                line = _education_line(ent)
                if line and line not in detail["education"]:
                    detail["education"] = (detail["education"] + "\n" + line).strip()


# --- strategy 2: JSON-LD Person block ----------------------------------------

def _from_ld_json(soup, detail) -> None:
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or s.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict) or data.get("@type") != "Person":
            continue
        detail["about"] = detail["about"] or (data.get("description") or "").strip()
        if not detail["education"] and data.get("alumniOf"):
            al = data["alumniOf"]
            names = [a.get("name") for a in al if isinstance(a, dict) and a.get("name")]
            if isinstance(al, dict) and al.get("name"):
                names = [al["name"]]
            detail["education"] = "\n".join(names)


# --- strategy 3: DOM heuristics (heading text -> section) --------------------

def _find_section(soup, heading_rx):
    for h in soup.find_all(["h2", "h3"]):
        if heading_rx.match(h.get_text(" ", strip=True).strip()):
            return h.find_parent("section") or h.parent
    return None


def _from_dom(soup, detail) -> None:
    if not detail["about"]:
        sec = _find_section(soup, _HEADINGS["about"])
        if sec is not None:
            lines = [l.strip() for l in sec.get_text("\n", strip=True).split("\n") if l.strip()]
            if lines and _HEADINGS["about"].match(lines[0]):
                lines = lines[1:]  # drop the "About" heading itself
            detail["about"] = "\n".join(lines)

    for key in ("experience", "education"):
        if detail[key]:
            continue
        sec = _find_section(soup, _HEADINGS[key])
        if sec is None:
            continue
        items = []
        for li in sec.find_all("li"):
            t = re.sub(r"\s+", " ", li.get_text(" ", strip=True)).strip()
            if len(t) > 10 and "show all" not in t.lower():
                items.append(t)
        detail[key] = "\n".join(dict.fromkeys(items))

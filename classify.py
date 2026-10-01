"""Classify stored profile stubs with an OpenAI-compatible LLM (Qwen via DashScope).

Configure in .env (see .env.example). Offline pipeline test:
  python cli.py classify --mock
"""
import json
import os
import random
import re
import time

import db

DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-flash"

SEA_COUNTRIES = {"PH", "MY", "SG", "TH", "ID", "VN", "BN", "KH", "LA", "MM", "TL"}

SYSTEM_PROMPT = """You classify LinkedIn people-search stubs for a personal shortlist \
of Southeast-Asia-based frontend developers and UI/UX designers.
Count as SEA: PH, MY, SG, TH, ID, VN, BN, KH, LA, MM, TL.
role_fit: "frontend" (frontend/web engineer), "ui_ux" (UI/UX/product/interaction designer, \
UX researcher), "both" (hybrid such as UI engineer / design engineer), "related" (adjacent \
roles: full-stack heavy on UI, graphic/visual designer, etc.), "other".
seniority: intern | junior | mid | senior | lead (also head/principal/manager) | unknown.
relevance: 0-10 for "does this person plausibly belong on a frontend/UI-UX talent shortlist \
in SEA". Location matters: low relevance if clearly not in SEA.
Respond with STRICT JSON only, no prose:
{"role_fit":"...","seniority":"...","country":"XX or unknown","in_sea":true,"relevance":0,"reason":"max 15 words"}"""


def _user_prompt(row) -> str:
    return (
        f"NAME: {row['name'] or ''}\n"
        f"HEADLINE: {row['headline'] or ''}\n"
        f"LOCATION: {row['location'] or ''}\n"
        f"URL: {row['profile_url']}"
    )


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text or "", re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def _normalize(raw: dict) -> dict:
    fit = str(raw.get("role_fit", "other")).strip().lower()
    if fit not in {"frontend", "ui_ux", "both", "related", "other"}:
        fit = "other"
    sen = str(raw.get("seniority", "unknown")).strip().lower()
    if sen not in {"intern", "junior", "mid", "senior", "lead", "unknown"}:
        sen = "unknown"
    country = str(raw.get("country") or "unknown").strip()
    country = country.upper() if len(country) == 2 else "unknown"
    try:
        relevance = max(0.0, min(10.0, float(raw.get("relevance", 0))))
    except (TypeError, ValueError):
        relevance = 0.0
    in_sea = country in SEA_COUNTRIES if country != "unknown" else bool(raw.get("in_sea"))
    return {
        "role_fit": fit,
        "seniority": sen,
        "country": country,
        "in_sea": in_sea,
        "relevance": relevance,
        "reason": str(raw.get("reason", ""))[:200],
    }


def _mock_result(row) -> dict:
    """Deterministic offline classification so the pipeline can be tested without a key."""
    h = abs(hash(row["profile_url"]))
    fit = ["frontend", "ui_ux", "both", "related", "other"][h % 5]
    sen = ["junior", "mid", "senior", "lead", "unknown"][(h // 7) % 5]
    loc = (row["location"] or "").lower()
    names = {"PH": "philippines", "SG": "singapore", "MY": "malaysia",
             "TH": "thailand", "ID": "indonesia"}
    country = next((cc for cc, name in names.items() if name in loc), "unknown")
    return _normalize({
        "role_fit": fit,
        "seniority": sen,
        "country": country,
        "in_sea": country != "unknown",
        "relevance": (h % 10) + 1,
        "reason": "mock classification",
    })


def run(mock: bool = False, limit=None) -> None:
    conn = db.connect()
    db.init()
    rows = db.unclassified(conn)
    if limit:
        rows = rows[:limit]
    if not rows:
        print("Nothing to classify - every stored profile is already classified.")
        return

    client = None
    if not mock:
        key = os.getenv("DASHSCOPE_API_KEY")
        if not key:
            print("No DASHSCOPE_API_KEY in .env - add it, or use: python cli.py classify --mock")
            return
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=os.getenv("QWEN_BASE_URL", DEFAULT_BASE_URL))

    model = "mock" if mock else os.getenv("QWEN_MODEL", DEFAULT_MODEL)
    print(f"Classifying {len(rows)} profile(s) with {model}...")
    for row in rows:
        if mock:
            result = _mock_result(row)
        else:
            try:
                resp = client.chat.completions.create(
                    model=os.getenv("QWEN_MODEL", DEFAULT_MODEL),
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": _user_prompt(row)},
                    ],
                )
                result = _normalize(_extract_json(resp.choices[0].message.content))
            except Exception as exc:  # one bad row should not kill the run
                print(f"  !! failed: {row['profile_url']} ({exc})")
                continue
        db.save_classification(conn, row["profile_url"], result)
        print(f"  {row['name'] or row['profile_url']}: {result['role_fit']} / "
              f"{result['seniority']} / {result['country']} / rel={result['relevance']}")
        if not mock:
            time.sleep(random.uniform(1.0, 2.5))
    print("Classification done.")

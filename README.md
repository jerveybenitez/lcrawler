# LinkedIn SEA Talent Finder — POC

A personal, AI-assisted tool that slowly collects LinkedIn people-search results for
frontend / UI-UX talent in Southeast Asia (MY, SG, TH, ID, PH), stores them in SQLite,
classifies each profile stub with Qwen, and exports a clean CSV.

**Personal use only.** Scraping violates LinkedIn's User Agreement; at personal scale
the realistic risk is account restriction, not legal action. Use a dedicated account —
never your main one. See *Safety rules* below.

## How login works

The tool drives its **own browser instance** (Patchright — anti-detection-patched
Playwright) with a persistent profile in `browser_profile/`:

1. `python cli.py login` opens a real, visible browser window.
2. You log in **by hand** — email, password, 2FA. The session is saved to disk.
3. Every later run (`search`, `capture`) reuses that saved session automatically.

The login flow itself is never automated — it's the single most scrutinized moment,
and one manual login lasts a long time. Delete `browser_profile/` to log out.

Known LinkedIn behavior: sometimes it accepts your credentials and saves the
session cookie, but then silently hangs the redirect to the feed — the window
stays on the login page even though you're actually logged in. The tool detects
this via the session cookie (`li_at`), so trust the console message, and use
`python cli.py status` whenever in doubt.

## Setup (Windows)

```
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m patchright install chromium
copy .env.example .env      # then put your DashScope API key in .env
```

Qwen API key: create one in your Alibaba Cloud Model Studio (DashScope) console and
paste it as `DASHSCOPE_API_KEY` in `.env`. The defaults there target the international
endpoint with the cheap `qwen-flash` model.

## Workflow

| Step | Command | Notes |
|---|---|---|
| 1. Login (once) | `python cli.py login` | Log in by hand in the window that opens |
| 2. Save a real fixture | `python cli.py capture --name frontend_manila --keywords "\"frontend developer\" Manila"` | Auto-navigates to the people search and saves the HTML (counts toward the daily page cap). Without `--keywords` it falls back to watching a manual browser session |
| 3. Verify the parser | `python cli.py parse fixtures/<file>.html` | Add `--save` to also insert stubs into SQLite |
| 4. First live run | `python cli.py search --keywords "\"frontend developer\" Manila" --pages 2` | Deliberately tiny |
| 5. Classify | `python cli.py classify` | Or `classify --mock` to test the pipeline offline |
| 6. Fetch full profiles | `python cli.py fetch --limit 2` | Very slow on purpose: 30–120 s wait before each profile. First fetch saves a `fixtures/profile_*.html` so `profile_parser.py` can be verified on real markup |
| 7. Export | `python cli.py export --only-sea --min-score 6` | CSV in `data/`, Excel-friendly |
| — | `python cli.py stats` | Row counts + today's page budget |
| — | `python cli.py status` | Is the saved LinkedIn session still alive? |

Offline sanity check without touching LinkedIn (works right after setup):

```
python cli.py parse fixtures/synthetic_json_search.html
python cli.py parse fixtures/synthetic_dom_search.html
python cli.py parse fixtures/synthetic_json_search.html --save
python cli.py classify --mock
python cli.py export
python cli.py stats
```

## Safety rules (the design assumes you follow these)

- **Dedicated account, never your main identity.** Assume any account used for
  crawling may someday hit an ID-verification checkpoint or restriction.
- **Default caps are intentionally small:** 3 pages per run, 20 page loads per day,
  6–14 s randomized delays between loads (see `config.py` / `.env`). Raise slowly,
  only as the account tolerates it.
- **Profile fetches (step 6) are paced much harder:** a 30–120 s randomized wait
  *before* every profile page, max 5 per run — and every fetch spends from the same
  20-page daily budget as search.
- If LinkedIn shows a *"commercial use limit"* wall, a checkpoint, or anything
  unusual — **stop for the day**.
- Parsers are developed against **saved fixtures** (`capture`), never against live
  pages. Development iterations should never generate LinkedIn traffic.
- Sessions run **headed** (visible window). Headless is a bot signal.

## Troubleshooting

- `!! Login wall / challenge detected` → run `python cli.py login` and log in again.
- Parser returns 0 stubs from a real page → LinkedIn changed its markup. Capture a
  fresh fixture with `capture`, inspect it, and adjust `search_parser.py`
  (JSON-in-`<code>` first, DOM classes as fallback).
- Classification fails for every row → check `DASHSCOPE_API_KEY` / endpoint region;
  smoke-test with `classify --mock`.
- Database location: `data/talent.db` (plain SQLite — open with any SQLite browser).

## After the POC proves out

1. LLM query-matrix generator: keywords × 5 countries × major cities × seniority,
   including local-language variants (this defines total reach).
2. ~~Tier-2 detail fetches~~ **done** — `fetch` pulls about/experience/education for
   high-relevance profiles (verify `profile_parser.py` on the auto-saved fixture first).
3. Monthly refresh "drip" for the standing filters.
4. Optional zero-risk companion layer: SERP x-ray (`site:linkedin.com/in`) + GitHub
   API through the same classify/export pipeline.

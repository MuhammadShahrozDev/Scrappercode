# smart_scraper – setup & run guide

Sources: **ycombinator**, **wellfound**, **linkedin** (adds people to Wellfound jobs), **upwork**.

## What a run does (`source = all`)
- Goal: at least `target` leads **per source** (default 50 → 200 total), never more than
  `max_total` leads per run (default 1000), within `max_runtime` minutes (default 240).
- Sources run in rounds; each ingests its new leads immediately. A source that adds nothing is
  marked exhausted (e.g. blocked login) so the others keep their time.
- LinkedIn only counts jobs where a person was really found. If it runs out of Wellfound
  companies, Wellfound is re-run with a wider window (3 → 7 → 14 → 30 days) and bigger pool.
- Exit code 1 + status `failed`/`timeout` if any source stays below its minimum.

## GitHub secrets (Settings → Secrets and variables → Actions)
| Secret | Used by | Notes |
|---|---|---|
| `SMART_SCRAPER_API_URL`, `SMART_SCRAPER_INGEST_TOKEN` | ingestion | existing |
| `LINKEDIN_LI_AT` | LinkedIn + Upwork profile scrape | fresh `li_at` cookie of a logged-in account |
| `WELLFOUND_STORAGE_STATE_B64` | Wellfound | existing |
| `UPWORK_STORAGE_STATE_B64` | Upwork | create with `python Upwork/export_session.py` on your own PC |
| `GEMINI_API_KEY` | Upwork (company/industry/matching) | Google AI Studio key |
| `UPWORK_PROXY` | Upwork (optional) | `http://user:pass@host:port`, residential proxy if Upwork shows a bot check |

Optional repo variable: `UPWORK_QUERY` (default `agentic ai`).

## Upwork notes
- Upwork and LinkedIn often challenge datacenter IPs (GitHub runners). The code fails loudly with a
  clear message (`bot check`, `session not valid`) instead of reporting a fake success.
  If that happens: refresh the cookie secret, or use `UPWORK_PROXY` / a self-hosted runner.
- A lead = an Upwork job whose client was matched to a LinkedIn profile (`Upwork/to_leads.py`).
- Google blocks datacenter IPs, so on CI the profile search uses DuckDuckGo (`UPWORK_SEARCH_ENGINE=ddgs`).
- Local run: `cd Upwork && python upw_scraper.py` (browser opens, log in once), or `python main.py`.

## Local test of the whole pipeline
```
export SMART_SCRAPER_SOURCE=all SMART_SCRAPER_TARGET=50 SMART_SCRAPER_MAX_RUNTIME_MINUTES=240
python main.py
```

## Environment knobs
`SMART_SCRAPER_MIN_PER_SOURCE` (=target), `SMART_SCRAPER_MAX_TOTAL`, `SMART_SCRAPER_MAX_ROUNDS` (4),
`SMART_SCRAPER_WELLFOUND_POOL_FACTOR` (4), `UPWORK_JOBS_PER_RUN`, `UPWORK_MAX_PAGES`,
`UPWORK_SORT`, `LINKEDIN_MAX_EMPTY_STREAK` (15).

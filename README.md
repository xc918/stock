# Market Brief

Three snapshots per trading day, emailed to you as Markdown + CSV — attached, and with the full text inline in the body so you can copy it from your phone straight into Claude Code or DeepSeek.

| Slot | Time (ET) | Contents |
|---|---|---|
| Open | 9:30 | Full brief — prices, P/L, technicals, valuation, analyst targets, short interest, earnings, screens, headlines |
| Midday | 12:00 | Short brief — prices, intraday move, movers, screens, fresh headlines |
| Afternoon | 2:30 | Short brief |

Fundamentals are only in the 9:30 brief because they don't change intraday.

## Setup

**Your repo `xc918/stock` is public. Do not commit `holdings.csv`.** Cost basis goes into a repo secret instead; `.gitignore` already excludes the file.

1. Push these files:
   ```
   git init
   git add .
   git commit -m "market brief"
   git branch -M main
   git remote add origin https://github.com/xc918/stock.git
   git push -u origin main
   ```
   If the repo already has a README, run `git pull --rebase origin main` first. If git asks for a password, use a personal access token (github.com → Settings → Developer settings → Personal access tokens → Tokens (classic) → scope `repo`).

2. Add four secrets at https://github.com/xc918/stock/settings/secrets/actions → **New repository secret**:

   | Name | Value |
   |---|---|
   | `YAHOO_USER` | your full Yahoo address, e.g. `you@yahoo.com` |
   | `YAHOO_APP_PASSWORD` | the 16-character Yahoo app password, no spaces |
   | `MAIL_TO` | where the brief should land |
   | `HOLDINGS_CSV` | the whole holdings CSV pasted as text — see below |

   `HOLDINGS_CSV` value, header row included, real numbers substituted:
   ```
   ticker,shares,avg_cost,account
   ASTS,300,28.40,ETRADE
   HIMS,200,41.10,ETRADE
   RDDT,80,112.00,SCHWAB
   ```
   Add a row per position. Tickers here are valued and P/L'd; everything else comes from `config.json`.

3. Test it: **Actions → Market Brief → Run workflow**, pick a slot, run. Email arrives in ~2–4 minutes (the open slot is slower; it pulls fundamentals for every name).

## What's in the full brief

Market context (SPY/QQQ/IWM/SMH/XLK/XLF/XLE/VIX) and macro (3M/5Y/10Y/30Y yields, DXY, crude, gold, BTC). Holdings with day P/L, unrealized P/L and portfolio totals. Main and secondary watchlists. Per-name technicals: change vs prior close **and** vs today's open, RVOL, RSI-14, ATR%, distance from 52-week high, 20/50/200-day SMA. Breadth line across everything tracked. Movers ≥3%. Valuation/growth/margins. Analyst mean target, upside, and how the buy/hold/sell split shifted over three months. Short interest, % of float, days-to-cover, month-over-month change. Earnings within 30 days — and for anything reporting inside 14 days, the front-month implied vol, implied move, put/call volume ratio, and last four quarters of EPS beats/misses. Yahoo's day gainers / day losers / most actives. Headlines for holdings and any ±3% mover.

## Files

- `brief.py` — orchestration and Markdown/CSV rendering
- `fetch.py` — data layer; every call degrades to `—` rather than failing the run
- `send_email.py` — Yahoo SMTP over SSL, port 465
- `should_run.py` — slot gate: DST, weekends, NYSE holidays
- `config.json` — watchlists, macro symbols, screens, thresholds
- `holdings.example.csv` — template only; the real one lives in the `HOLDINGS_CSV` secret

## Notes

- GitHub cron is UTC-only and fires late under load, so every slot is scheduled twice (EDT and EST offsets) and `should_run.py` keeps whichever one is correct today. A firing is accepted up to 45 minutes past its target, so a delayed run still sends.
- RVOL reads low at 9:30 by construction — it's session volume so far against a 20-day average. It's most meaningful in the midday and afternoon briefs.
- NYSE holidays are hardcoded through 2027 in `should_run.py`.
- Every run also uploads the brief as a workflow artifact (30-day retention), so you can download it from the Actions tab if an email is ever lost.
- Yahoo has no official API and rate-limits aggressively. Fields degrade to `—` rather than crashing the run; if a whole section empties out, it's usually throttling, and the next slot will normally fill it back in.
- If mail stops, the cause is nearly always a regenerated or revoked Yahoo app password — update the secret.

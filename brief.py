"""Build the market brief. Modes: 'full' (9:30 open) and 'short' (midday snapshots)."""

import csv
import io
import json
import math
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf

import fetch

ET = ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
HOLDINGS_PATH = os.path.join(HERE, "holdings.csv")
OUT_DIR = os.path.join(HERE, "out")
DASH = "—"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_holdings():
    """Prefer the HOLDINGS_CSV secret; fall back to a local file for testing."""
    raw = os.environ.get("HOLDINGS_CSV", "").strip()
    if raw:
        handle = io.StringIO(raw)
    elif os.path.exists(HOLDINGS_PATH):
        handle = open(HOLDINGS_PATH, newline="")
    else:
        return []
    rows = []
    with handle:
        for row in csv.DictReader(handle):
            ticker = (row.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            rows.append({
                "ticker": ticker,
                "shares": float(row.get("shares") or 0),
                "avg_cost": float(row.get("avg_cost") or 0),
                "account": (row.get("account") or "").strip(),
            })
    return rows


# ---------- formatting ----------

def fmt(value, spec="{:,.2f}"):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return DASH
    return spec.format(value)


def pct(value):
    return fmt(value, "{:+.2f}%")


def big(value):
    if value is None:
        return DASH
    for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(value) >= size:
            return f"{value / size:.2f}{unit}"
    return f"{value:,.0f}"


def table(header, rows):
    if not rows:
        return "_none_"
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join(["---"] * len(header)) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


# ---------- collection ----------

def collect(tickers, mode, deep_tickers=(), news_tickers=(), news_per_ticker=4,
            deep_group=None):
    daily = fetch.download_daily(tickers)
    intra = fetch.download_intraday(tickers)
    rows = {}
    for ticker in tickers:
        frame = daily.get(ticker)
        if frame is None:
            rows[ticker] = {"ticker": ticker, "error": "no price history"}
            continue
        row = fetch.price_block(ticker, frame, intra.get(ticker))
        obj = yf.Ticker(ticker)
        row["earnings"] = fetch.earnings_date(obj)
        if mode == "full" and (deep_group is None or ticker in deep_group):
            row.update(fetch.fundamentals(obj))
            row.update(fetch.analyst(obj, row["price"]))
        if ticker in deep_tickers:
            row["surprises"] = fetch.earnings_surprises(obj)
            row["options"] = fetch.implied_move(obj, row["price"])
        if ticker in news_tickers:
            row["news"] = fetch.headlines(obj, news_per_ticker)
        rows[ticker] = row
    return rows


def pick_deep_tickers(rows, window_days):
    today = datetime.now(ET).date()
    horizon = today + timedelta(days=window_days)
    return {t for t, r in rows.items()
            if "error" not in r and r.get("earnings") and today <= r["earnings"] <= horizon}


def pick_news_tickers(rows, held, big_move_pct):
    movers = {t for t, r in rows.items()
              if "error" not in r and abs(r.get("change_pct") or 0) >= big_move_pct}
    return set(held) | movers


# ---------- sections ----------

QUOTE_HEADER = ["Ticker", "Price", "Chg%", "vs Open", "RVOL", "RSI", "ATR%",
                "vs 52wH", "20d", "50d", "200d", "Earnings"]


def quote_rows(rows, tickers):
    out = []
    for ticker in tickers:
        r = rows.get(ticker)
        if not r or "error" in r:
            out.append([ticker, "_no data_"] + [""] * (len(QUOTE_HEADER) - 2))
            continue
        out.append([
            ticker, fmt(r["price"]), pct(r["change_pct"]), pct(r["from_open_pct"]),
            fmt(r["rvol"], "{:.2f}x"), fmt(r["rsi14"], "{:.0f}"), fmt(r["atr_pct"], "{:.1f}%"),
            pct(r["pct_from_52w_high"]), fmt(r["sma20"]), fmt(r["sma50"]), fmt(r["sma200"]),
            str(r["earnings"] or DASH),
        ])
    return out


def holdings_section(rows, holdings):
    header = ["Ticker", "Acct", "Shares", "Avg Cost", "Price", "Chg%", "Day P/L",
              "Mkt Value", "Unreal P/L", "P/L %"]
    body = []
    total_value = total_cost = total_day = 0.0
    for h in holdings:
        r = rows.get(h["ticker"])
        if not r or "error" in r:
            body.append([h["ticker"], h["account"], f"{h['shares']:g}", fmt(h["avg_cost"]),
                         "_no data_", "", "", "", "", ""])
            continue
        value = r["price"] * h["shares"]
        cost = h["avg_cost"] * h["shares"]
        gain = value - cost
        gain_pct = (gain / cost * 100) if cost else None
        day = (r["price"] - r["prev_close"]) * h["shares"]
        total_value += value
        total_cost += cost
        total_day += day
        body.append([h["ticker"], h["account"], f"{h['shares']:g}", fmt(h["avg_cost"]),
                     fmt(r["price"]), pct(r["change_pct"]), fmt(day, "{:+,.2f}"),
                     fmt(value), fmt(gain, "{:+,.2f}"), pct(gain_pct)])
    total_gain = total_value - total_cost
    total_pct = (total_gain / total_cost * 100) if total_cost else None
    body.append(["**TOTAL**", "", "", fmt(total_cost), "", "",
                 f"**{fmt(total_day, '{:+,.2f}')}**", f"**{fmt(total_value)}**",
                 f"**{fmt(total_gain, '{:+,.2f}')}**", f"**{pct(total_pct)}**"])
    summary = (f"Portfolio {fmt(total_value)} | cost {fmt(total_cost)} | "
               f"unrealized {fmt(total_gain, '{:+,.2f}')} ({pct(total_pct)}) | "
               f"today {fmt(total_day, '{:+,.2f}')}")
    return table(header, body), summary


def fundamentals_section(rows, tickers):
    header = ["Ticker", "Mkt Cap", "P/E", "Fwd P/E", "P/S", "EV/EBITDA", "Rev Gr",
              "Earn Gr", "Gross M", "Op M", "Beta"]
    body = []
    for ticker in tickers:
        r = rows.get(ticker)
        if not r or "error" in r or "market_cap" not in r:
            continue
        body.append([ticker, big(r["market_cap"]), fmt(r["pe"], "{:.1f}"),
                     fmt(r["forward_pe"], "{:.1f}"), fmt(r["ps"], "{:.1f}"),
                     fmt(r["ev_ebitda"], "{:.1f}"), fmt(r["revenue_growth"], "{:+.1f}%"),
                     fmt(r["earnings_growth"], "{:+.1f}%"), fmt(r["gross_margin"], "{:.1f}%"),
                     fmt(r["operating_margin"], "{:.1f}%"), fmt(r["beta"], "{:.2f}")])
    return table(header, body)


def analyst_section(rows, tickers):
    header = ["Ticker", "Price", "Target", "Upside", "Low-High", "Ratings now", "3mo ago"]
    body = []
    for ticker in tickers:
        r = rows.get(ticker)
        if not r or "error" in r or not r.get("target_mean"):
            continue
        body.append([ticker, fmt(r["price"]), fmt(r["target_mean"]),
                     pct(r["target_upside_pct"]),
                     f"{fmt(r['target_low'])}–{fmt(r['target_high'])}",
                     r.get("ratings_now") or DASH, r.get("ratings_3mo") or DASH])
    return table(header, body)


def short_interest_section(rows, tickers):
    header = ["Ticker", "Float", "Shares Short", "% of Float", "Days to Cover", "MoM Chg"]
    body = []
    for ticker in tickers:
        r = rows.get(ticker)
        if not r or "error" in r or not r.get("shares_short"):
            continue
        body.append([ticker, big(r["float_shares"]), big(r["shares_short"]),
                     fmt(r["short_pct_float"], "{:.1f}%"), fmt(r["short_ratio"], "{:.1f}"),
                     pct(r["short_change_pct"])])
    return table(header, body)


def movers_section(rows, threshold):
    movers = [r for r in rows.values()
              if "error" not in r and abs(r.get("change_pct") or 0) >= threshold]
    movers.sort(key=lambda r: -abs(r["change_pct"]))
    if not movers:
        return f"_Nothing tracked moved {threshold:.0f}% or more._"
    return "\n".join(
        f"- **{r['ticker']}** {pct(r['change_pct'])} to {fmt(r['price'])} "
        f"(RVOL {fmt(r['rvol'], '{:.2f}x')})" for r in movers)


def screen_section(name, rows):
    header = ["Ticker", "Name", "Price", "Chg%", "Volume", "Mkt Cap"]
    body = [[r["ticker"] or DASH, r["name"], fmt(r["price"]), pct(r["change_pct"]),
             big(r["volume"]), big(r["market_cap"])] for r in rows if r.get("ticker")]
    return table(header, body)


def earnings_section(rows, horizon_days):
    today = datetime.now(ET).date()
    horizon = today + timedelta(days=horizon_days)
    hits = sorted((r["earnings"], t) for t, r in rows.items()
                  if "error" not in r and r.get("earnings") and today <= r["earnings"] <= horizon)
    if not hits:
        return f"_None in the next {horizon_days} days._"
    lines = []
    for day, ticker in hits:
        r = rows[ticker]
        extra = ""
        options = r.get("options")
        if options:
            extra = (f" — IV {fmt(options['iv_pct'], '{:.0f}%')}, "
                     f"implied move ±{fmt(options['implied_move_pct'], '{:.1f}%')} "
                     f"to {options['expiry']}, P/C vol {fmt(options['put_call_volume'], '{:.2f}')}")
        lines.append(f"- **{day}** {ticker}{extra}")
        for s in r.get("surprises", []):
            lines.append(f"    - {s['period']}: est {fmt(s['estimate'])} vs actual "
                         f"{fmt(s['actual'])} ({pct(s['surprise_pct'])})")
    return "\n".join(lines)


def news_section(rows):
    blocks = []
    for ticker, r in rows.items():
        items = r.get("news") or []
        if not items:
            continue
        lines = [f"**{ticker}**"]
        for item in items:
            stamp = f" ({item['published']})" if item["published"] else ""
            source = f" — {item['publisher']}" if item["publisher"] else ""
            link = f" [link]({item['link']})" if item["link"] else ""
            lines.append(f"- {item['title']}{source}{stamp}{link}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else "_No fresh headlines._"


def breadth_line(rows, tickers):
    tracked = [rows[t] for t in tickers if t in rows and "error" not in rows[t]]
    if not tracked:
        return ""
    above50 = sum(1 for r in tracked if r.get("sma50") and r["price"] > r["sma50"])
    above200 = sum(1 for r in tracked if r.get("sma200") and r["price"] > r["sma200"])
    up = sum(1 for r in tracked if (r.get("change_pct") or 0) > 0)
    return (f"Breadth across {len(tracked)} tracked names: {up} up / {len(tracked) - up} down, "
            f"{above50} above 50d SMA, {above200} above 200d SMA.")


# ---------- assembly ----------

def build(config, holdings, slot="open", mode="full", collector=collect,
          screener=fetch.run_screen):
    held = [h["ticker"] for h in holdings]
    focus = config["watchlist_focus"]
    general = config["watchlist_general"]
    recent = config["watchlist_recent"]
    context = config["market_context"]
    macro = config["macro"]
    big_move = config["big_move_pct"]

    # Fundamentals, analyst targets and short interest are pulled only for these.
    # The general watchlist is quotes and technicals only, to keep the run inside
    # Yahoo's rate limits.
    deep_group = list(dict.fromkeys(held + focus + recent))

    equities = list(dict.fromkeys(held + focus + recent + general))
    rows = collector(equities, mode, deep_group=deep_group)

    deep = set()
    news = set()
    if mode == "full":
        deep = pick_deep_tickers(rows, config["deep_earnings_window_days"])
        news = pick_news_tickers(rows, held, big_move)
    else:
        news = pick_news_tickers(rows, [], big_move)
    if deep or news:
        extra = collector(sorted(deep | news), mode, deep_tickers=deep,
                          news_tickers=news, news_per_ticker=config["news_per_ticker"],
                          deep_group=deep_group)
        for ticker, row in extra.items():
            rows.setdefault(ticker, row).update(row)

    index_rows = collector(context + macro, "short")
    rows.update({t: r for t, r in index_rows.items() if t not in rows})

    screens = {}
    for name in config["screens"]:
        screens[name] = screener(name, config["screen_count"])

    for ticker in equities:
        if ticker in rows:
            rows[ticker]["group"] = ("holding" if ticker in held else
                                     "focus" if ticker in focus else
                                     "recent" if ticker in recent else "general")
    for ticker in context + macro:
        if ticker in rows:
            rows[ticker]["group"] = "context"

    stamp = datetime.now(ET)
    holdings_md, summary = holdings_section(rows, holdings)
    label = {"open": "Open", "midday": "Midday", "afternoon": "Afternoon"}.get(slot, slot)

    parts = [
        f"# {label} Brief — {stamp:%A, %B %d, %Y %H:%M} ET",
        "",
        summary,
        "",
        breadth_line(rows, equities),
        "",
        "## 1. Market context",
        table(QUOTE_HEADER, quote_rows(rows, context)),
        "",
        "## 2. Macro",
        table(QUOTE_HEADER, quote_rows(rows, macro)),
        "",
        "## 3. Holdings",
        holdings_md,
        "",
        "## 4. Focus watchlist (重点观察)",
        table(QUOTE_HEADER, quote_rows(rows, focus)),
        "",
        "## 5. Recent additions (近期新增)",
        table(QUOTE_HEADER, quote_rows(rows, recent)),
        "",
        "## 6. General watchlist (一般观察)",
        table(QUOTE_HEADER, quote_rows(rows, general)),
        "",
        f"## 7. Notable moves (>= {big_move:.0f}%)",
        movers_section({t: rows[t] for t in equities if t in rows}, big_move),
        "",
    ]

    section = 8
    if mode == "full":
        parts += [f"## {section}. Valuation, growth and margins "
                  f"(holdings, focus and recent only)",
                  fundamentals_section(rows, deep_group), ""]
        section += 1
        parts += [f"## {section}. Analyst targets and rating trend",
                  analyst_section(rows, deep_group), ""]
        section += 1
        parts += [f"## {section}. Short interest",
                  short_interest_section(rows, deep_group), ""]
        section += 1

    parts += [f"## {section}. Earnings within {config['earnings_horizon_days']} days",
              earnings_section({t: rows[t] for t in equities if t in rows},
                               config["earnings_horizon_days"]), ""]
    section += 1

    parts += [f"## {section}. Market-wide screens", ""]
    titles = {"day_gainers": "Top gainers", "day_losers": "Top losers",
              "most_actives": "Most active"}
    for name, screen_rows in screens.items():
        parts += [f"### {titles.get(name, name)}", screen_section(name, screen_rows), ""]
    section += 1

    parts += [f"## {section}. Headlines",
              news_section({t: rows[t] for t in equities if t in rows}), ""]

    parts += [
        "---",
        f"Source: Yahoo Finance via yfinance, captured {stamp:%Y-%m-%d %H:%M:%S} ET ({slot} slot).",
        "RVOL = session volume vs 20-day average; it reads low early in the session by construction.",
        "Prices at 9:30 are opening prints and can be thin.",
    ]
    return "\n".join(parts), rows


CSV_FIELDS = ["ticker", "group", "shares", "avg_cost", "price", "prev_close", "change_pct",
              "day_open", "from_open_pct", "day_high", "day_low", "day_range_pos",
              "market_value", "unrealized_pl", "unrealized_pl_pct",
              "volume", "avg_volume_20d", "rvol", "atr14", "atr_pct", "rsi14",
              "sma20", "sma50", "sma200", "high_52w", "low_52w",
              "pct_from_52w_high", "pct_above_52w_low",
              "market_cap", "pe", "forward_pe", "ps", "ev_ebitda", "peg",
              "revenue_growth", "earnings_growth", "gross_margin", "operating_margin",
              "profit_margin", "beta", "float_shares", "shares_short", "short_pct_float",
              "short_ratio", "short_change_pct", "target_mean", "target_upside_pct",
              "ratings_now", "ratings_3mo", "earnings"]


def write_csv(path, rows, holdings):
    cost_map = {h["ticker"]: h for h in holdings}
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for ticker, r in rows.items():
            if "error" in r:
                writer.writerow({"ticker": ticker, "group": r.get("group", "")})
                continue
            out = dict(r)
            h = cost_map.get(ticker)
            if h and h["shares"]:
                out["shares"] = h["shares"]
                out["avg_cost"] = h["avg_cost"]
                out["market_value"] = r["price"] * h["shares"]
                out["unrealized_pl"] = out["market_value"] - h["avg_cost"] * h["shares"]
                if h["avg_cost"]:
                    out["unrealized_pl_pct"] = (r["price"] / h["avg_cost"] - 1) * 100
            writer.writerow(out)


def main():
    slot = os.environ.get("SLOT", "open")
    mode = os.environ.get("MODE", "full")
    os.makedirs(OUT_DIR, exist_ok=True)
    config = load_config()
    holdings = load_holdings()
    md, rows = build(config, holdings, slot=slot, mode=mode)

    stamp = datetime.now(ET).strftime("%Y-%m-%d")
    md_path = os.path.join(OUT_DIR, f"brief-{stamp}-{slot}.md")
    csv_path = os.path.join(OUT_DIR, f"brief-{stamp}-{slot}.csv")
    with open(md_path, "w") as f:
        f.write(md)
    write_csv(csv_path, rows, holdings)
    with open(os.path.join(OUT_DIR, "paths.txt"), "w") as f:
        f.write(f"{md_path}\n{csv_path}\n")
    print(md_path)
    print(csv_path)


if __name__ == "__main__":
    sys.exit(main())

"""Data layer. Every function degrades to None/empty rather than raising."""

import math
from datetime import datetime, date

import pandas as pd
import yfinance as yf

HISTORY_PERIOD = "1y"
INTRADAY_INTERVAL = "5m"
RSI_WINDOW = 14
ATR_WINDOW = 14
AVG_VOLUME_WINDOW = 20
SMA_WINDOWS = [20, 50, 200]
TRADING_DAYS_52W = 252


def safe(fn, default=None):
    try:
        value = fn()
    except Exception:
        return default
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    return value


def to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return safe(lambda: pd.to_datetime(value).date())


def download_daily(tickers):
    """1 year of daily bars, keyed by ticker."""
    if not tickers:
        return {}
    data = safe(lambda: yf.download(tickers, period=HISTORY_PERIOD, interval="1d",
                                   auto_adjust=False, group_by="ticker",
                                   progress=False, threads=True))
    if data is None or len(data) == 0:
        return {}
    frames = {}
    for ticker in tickers:
        frame = safe(lambda t=ticker: data[t] if isinstance(data.columns, pd.MultiIndex) else data)
        if frame is None:
            continue
        frame = frame.dropna(subset=["Close"])
        if not frame.empty:
            frames[ticker] = frame
    return frames


def download_intraday(tickers):
    """Today's 5-minute bars, keyed by ticker. Empty before the open."""
    if not tickers:
        return {}
    data = safe(lambda: yf.download(tickers, period="1d", interval=INTRADAY_INTERVAL,
                                   auto_adjust=False, group_by="ticker",
                                   progress=False, threads=True, prepost=False))
    if data is None or len(data) == 0:
        return {}
    frames = {}
    for ticker in tickers:
        frame = safe(lambda t=ticker: data[t] if isinstance(data.columns, pd.MultiIndex) else data)
        if frame is None:
            continue
        frame = frame.dropna(subset=["Close"])
        if not frame.empty:
            frames[ticker] = frame
    return frames


def rsi(close, window=RSI_WINDOW):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean().iloc[-1]
    if pd.isna(avg_gain) or pd.isna(avg_loss):
        return None
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def atr(frame, window=ATR_WINDOW):
    if len(frame) < window + 1:
        return None
    high = frame["High"]
    low = frame["Low"]
    prev_close = frame["Close"].shift(1)
    spans = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1)
    true_range = spans.max(axis=1)
    value = true_range.tail(window).mean()
    return None if pd.isna(value) else float(value)


def price_block(ticker, daily, intra):
    """Prices, technicals and volume for one ticker."""
    close = daily["Close"]
    prev_close = float(close.iloc[-1])
    day_open = None
    day_high = None
    day_low = None
    last = prev_close
    volume_today = None

    if intra is not None and not intra.empty:
        day_open = float(intra["Open"].iloc[0])
        day_high = float(intra["High"].max())
        day_low = float(intra["Low"].min())
        last = float(intra["Close"].iloc[-1])
        volume_today = int(intra["Volume"].sum())
        # If the daily frame already carries today's bar, step back one for prev close.
        if to_date(close.index[-1]) == to_date(intra.index[-1]):
            prev_close = float(close.iloc[-2]) if len(close) > 1 else prev_close
    elif len(close) > 1:
        prev_close = float(close.iloc[-2])
        last = float(close.iloc[-1])

    avg_volume = safe(lambda: float(daily["Volume"].tail(AVG_VOLUME_WINDOW).mean()))
    if volume_today is None:
        volume_today = safe(lambda: int(daily["Volume"].iloc[-1]))

    block = {
        "ticker": ticker,
        "price": last,
        "prev_close": prev_close,
        "change_pct": (last / prev_close - 1) * 100 if prev_close else None,
        "day_open": day_open,
        "from_open_pct": (last / day_open - 1) * 100 if day_open else None,
        "day_high": day_high,
        "day_low": day_low,
        "volume": volume_today,
        "avg_volume_20d": avg_volume,
        "rvol": (volume_today / avg_volume) if (avg_volume and volume_today) else None,
        "atr14": atr(daily),
        "rsi14": rsi(close),
        "high_52w": float(close.tail(TRADING_DAYS_52W).max()),
        "low_52w": float(close.tail(TRADING_DAYS_52W).min()),
    }
    for window in SMA_WINDOWS:
        block[f"sma{window}"] = (float(close.tail(window).mean())
                                 if len(close) >= window else None)
    block["atr_pct"] = (block["atr14"] / last * 100) if (block["atr14"] and last) else None
    block["pct_from_52w_high"] = (last / block["high_52w"] - 1) * 100 if block["high_52w"] else None
    block["pct_above_52w_low"] = (last / block["low_52w"] - 1) * 100 if block["low_52w"] else None
    if day_high and day_low and day_high > day_low:
        block["day_range_pos"] = (last - day_low) / (day_high - day_low) * 100
    else:
        block["day_range_pos"] = None
    return block


INFO_FIELDS = {
    "market_cap": "marketCap",
    "pe": "trailingPE",
    "forward_pe": "forwardPE",
    "ps": "priceToSalesTrailing12Months",
    "ev_ebitda": "enterpriseToEbitda",
    "peg": "trailingPegRatio",
    "revenue_growth": "revenueGrowth",
    "earnings_growth": "earningsGrowth",
    "gross_margin": "grossMargins",
    "operating_margin": "operatingMargins",
    "profit_margin": "profitMargins",
    "beta": "beta",
    "float_shares": "floatShares",
    "shares_short": "sharesShort",
    "short_pct_float": "shortPercentOfFloat",
    "short_ratio": "shortRatio",
    "short_prior": "sharesShortPriorMonth",
}


def fundamentals(ticker_obj):
    info = safe(lambda: ticker_obj.info, {}) or {}
    block = {}
    for key, source in INFO_FIELDS.items():
        value = info.get(source)
        if isinstance(value, (int, float)) and not (isinstance(value, float) and math.isnan(value)):
            block[key] = float(value)
        else:
            block[key] = None
    for pct_key in ("revenue_growth", "earnings_growth", "gross_margin",
                    "operating_margin", "profit_margin", "short_pct_float"):
        if block[pct_key] is not None:
            block[pct_key] *= 100
    if block["shares_short"] and block["short_prior"]:
        block["short_change_pct"] = (block["shares_short"] / block["short_prior"] - 1) * 100
    else:
        block["short_change_pct"] = None
    return block


def analyst(ticker_obj, price):
    targets = safe(lambda: ticker_obj.analyst_price_targets, {}) or {}
    mean = targets.get("mean")
    block = {
        "target_mean": float(mean) if isinstance(mean, (int, float)) else None,
        "target_high": targets.get("high"),
        "target_low": targets.get("low"),
    }
    block["target_upside_pct"] = ((block["target_mean"] / price - 1) * 100
                                  if block["target_mean"] and price else None)

    recs = safe(lambda: ticker_obj.recommendations)
    block["ratings_now"] = None
    block["ratings_3mo"] = None
    if isinstance(recs, pd.DataFrame) and not recs.empty:
        def summarize(row):
            buys = int(row.get("strongBuy", 0) or 0) + int(row.get("buy", 0) or 0)
            holds = int(row.get("hold", 0) or 0)
            sells = int(row.get("sell", 0) or 0) + int(row.get("strongSell", 0) or 0)
            return f"{buys}B/{holds}H/{sells}S"
        block["ratings_now"] = safe(lambda: summarize(recs.iloc[0]))
        if len(recs) > 3:
            block["ratings_3mo"] = safe(lambda: summarize(recs.iloc[3]))
    return block


def earnings_date(ticker_obj):
    calendar = safe(lambda: ticker_obj.calendar)
    value = None
    if isinstance(calendar, dict):
        value = calendar.get("Earnings Date")
    elif isinstance(calendar, pd.DataFrame) and "Earnings Date" in calendar.index:
        value = safe(lambda: calendar.loc["Earnings Date"].tolist())
    if isinstance(value, list):
        value = value[0] if value else None
    return to_date(value)


def earnings_surprises(ticker_obj, limit=4):
    history = safe(lambda: ticker_obj.earnings_history)
    if not isinstance(history, pd.DataFrame) or history.empty:
        return []
    rows = []
    for index, row in history.tail(limit).iterrows():
        rows.append({
            "period": str(to_date(index) or index),
            "estimate": safe(lambda r=row: float(r.get("epsEstimate"))),
            "actual": safe(lambda r=row: float(r.get("epsActual"))),
            "surprise_pct": safe(lambda r=row: float(r.get("surprisePercent")) * 100),
        })
    return rows


def implied_move(ticker_obj, price):
    """Front-month ATM implied vol and the implied move to that expiry."""
    expiries = safe(lambda: ticker_obj.options, []) or []
    if not expiries or not price:
        return None
    expiry = expiries[0]
    chain = safe(lambda: ticker_obj.option_chain(expiry))
    if chain is None:
        return None
    calls = getattr(chain, "calls", None)
    puts = getattr(chain, "puts", None)
    if not isinstance(calls, pd.DataFrame) or calls.empty:
        return None

    atm_call = calls.iloc[(calls["strike"] - price).abs().argsort()[:1]]
    call_iv = safe(lambda: float(atm_call["impliedVolatility"].iloc[0]))
    put_iv = None
    if isinstance(puts, pd.DataFrame) and not puts.empty:
        atm_put = puts.iloc[(puts["strike"] - price).abs().argsort()[:1]]
        put_iv = safe(lambda: float(atm_put["impliedVolatility"].iloc[0]))

    iv = call_iv if put_iv is None else (call_iv + put_iv) / 2
    if iv is None:
        return None
    expiry_date = to_date(expiry)
    days = max((expiry_date - date.today()).days, 1) if expiry_date else 30

    call_volume = safe(lambda: float(calls["volume"].fillna(0).sum()), 0.0)
    put_volume = safe(lambda: float(puts["volume"].fillna(0).sum()), 0.0) if puts is not None else 0.0
    return {
        "expiry": str(expiry),
        "iv_pct": iv * 100,
        "implied_move_pct": iv * math.sqrt(days / 365) * 100,
        "put_call_volume": (put_volume / call_volume) if call_volume else None,
    }


def headlines(ticker_obj, limit=4):
    items = safe(lambda: ticker_obj.news, []) or []
    out = []
    for item in items[:limit]:
        content = item.get("content", item) if isinstance(item, dict) else {}
        title = content.get("title") or item.get("title")
        if not title:
            continue
        publisher = ((content.get("provider") or {}).get("displayName")
                     if isinstance(content.get("provider"), dict) else item.get("publisher"))
        link = None
        canonical = content.get("canonicalUrl") or content.get("clickThroughUrl")
        if isinstance(canonical, dict):
            link = canonical.get("url")
        link = link or item.get("link")
        stamp = content.get("pubDate") or item.get("providerPublishTime")
        out.append({
            "title": title,
            "publisher": publisher or "",
            "link": link or "",
            "published": str(to_date(stamp) or ""),
        })
    return out


def run_screen(name, count):
    result = safe(lambda: yf.screen(name, count=count))
    quotes = []
    if isinstance(result, dict):
        quotes = result.get("quotes", [])
    elif isinstance(result, list):
        quotes = result
    rows = []
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        rows.append({
            "ticker": quote.get("symbol"),
            "name": (quote.get("shortName") or quote.get("longName") or "")[:32],
            "price": quote.get("regularMarketPrice"),
            "change_pct": quote.get("regularMarketChangePercent"),
            "volume": quote.get("regularMarketVolume"),
            "market_cap": quote.get("marketCap"),
        })
    return rows

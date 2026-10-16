"""Yahoo Finance access: symbol resolution, period/interval validation, history download."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd
import yfinance as yf

ALIASES = {
    "NIFTY 50": "^NSEI", "NIFTY": "^NSEI", "BANK NIFTY": "^NSEBANK",
    "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "INFY": "INFY.NS",
    "INFOSYS": "INFY.NS", "HDFCBANK": "HDFCBANK.NS", "ICICIBANK": "ICICIBANK.NS",
    "GOLD": "GC=F", "INTERNATIONAL GOLD": "GC=F", "CRUDE": "CL=F",
    "CRUDE OIL": "CL=F", "BRENT": "BZ=F", "NATURAL GAS": "NG=F",
}
PERIOD_DAYS = {"1d": 1, "5d": 5, "7d": 7, "1mo": 30, "60d": 60, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}
# Yahoo's free history limits: how far back each interval can go.
INTERVAL_MAX_DAYS = {"1m": 7, "2m": 60, "5m": 60, "15m": 60, "30m": 60, "60m": 730, "90m": 60,
                     "1d": 10**6, "1wk": 10**6, "1mo": 10**6}
PERIODS = set(PERIOD_DAYS)
INTERVALS = set(INTERVAL_MAX_DAYS)


def resolve_symbol(symbol: str, market: str = "auto") -> str:
    raw = (symbol or "").strip()
    if not raw:
        raise ValueError("Please enter an instrument symbol.")
    upper = raw.upper()
    if market.upper() == "MCX" or upper.startswith("MCX_"):
        raise ValueError("MCX data needs an authorized MCX data provider or licensed CSV; it is not substituted with another market.")
    if upper in ALIASES:
        return ALIASES[upper]
    if upper.startswith("^") or "=" in upper or upper.endswith(".NS") or upper.endswith(".BO"):
        return upper
    if market.upper() in {"NSE", "AUTO", "INDEX"}:
        return upper + ".NS"
    return upper


def validate_request(period: str, interval: str) -> None:
    if period not in PERIODS:
        raise ValueError(f"Unsupported period: {period}. Use one of {sorted(PERIODS, key=PERIOD_DAYS.get)}.")
    if interval not in INTERVALS:
        raise ValueError(f"Unsupported interval: {interval}. Use one of {sorted(INTERVALS)}.")
    limit = INTERVAL_MAX_DAYS[interval]
    if PERIOD_DAYS[period] > limit:
        allowed = [p for p in sorted(PERIODS, key=PERIOD_DAYS.get) if PERIOD_DAYS[p] <= limit]
        raise ValueError(f"Yahoo only provides about {limit} days of {interval} data, so period '{period}' will fail. "
                         f"Use one of {allowed} or a daily interval (1d).")


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _chart_json(ticker: str, days: int, interval: str) -> dict:
    """Call Yahoo's public chart endpoint directly (no yfinance). Returns the first result dict."""
    now = int(time.time())
    q = urllib.parse.urlencode({"period1": now - int(days * 86400), "period2": now + 60, "interval": interval,
                                "includePrePost": "false", "events": "div,split"})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Yahoo returned HTTP {exc.code} ({'rate limited, wait a minute' if exc.code == 429 else 'symbol or interval not available'}).")
    chart = payload.get("chart", {})
    if chart.get("error") or not chart.get("result"):
        desc = (chart.get("error") or {}).get("description", "no result")
        raise ValueError(f"Yahoo has no data for {ticker}: {desc}")
    return chart["result"][0]


def _frame_from_chart(result: dict) -> pd.DataFrame:
    ts = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    if not ts or not quote.get("close"):
        raise ValueError("Yahoo returned an empty candle list (market closed or symbol has no intraday data).")
    tz = result.get("meta", {}).get("exchangeTimezoneName") or "UTC"
    idx = pd.to_datetime(ts, unit="s", utc=True).tz_convert(tz)
    df = pd.DataFrame({"Open": quote.get("open"), "High": quote.get("high"), "Low": quote.get("low"),
                       "Close": quote.get("close"), "Volume": quote.get("volume")}, index=idx)
    return df.dropna(subset=["Open", "High", "Low", "Close"])      # Yahoo pads gaps with nulls


def fetch_history(symbol: str, period: str = "5d", interval: str = "5m", market: str = "auto") -> pd.DataFrame:
    validate_request(period, interval)
    ticker = resolve_symbol(symbol, market)
    data, first_error = None, None
    try:                                                    # 1) yfinance
        data = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    except Exception as exc:                                # e.g. KeyError('tradingPeriods') on older yfinance
        first_error = exc
    if data is None or data.empty:                          # 2) direct Yahoo chart API as backup
        try:
            data = _frame_from_chart(_chart_json(ticker, PERIOD_DAYS[period], interval))
        except Exception as exc:
            hint = ""
            if first_error is not None:
                hint = f" (yfinance failed first with {type(first_error).__name__}: {first_error}; run: pip install -U yfinance)"
            raise ValueError(f"No data for {ticker}: {exc}{hint}")
    data.columns = [str(c).title() for c in data.columns]
    data = data[~data.index.duplicated(keep="last")].sort_index()
    return data.dropna(subset=["Close"])


def get_live_quote(symbol: str, market: str = "auto"):
    """Latest traded price (fresher than the last candle). None if unavailable."""
    try:
        ticker = resolve_symbol(symbol, market)
    except Exception:
        return None
    try:
        price = float(yf.Ticker(ticker).fast_info["last_price"])
        if price == price and price > 0:
            return {"price": price, "source": "yahoo fast_info"}
    except Exception:
        pass
    try:                                                     # fallback: price in the chart metadata
        price = float(_chart_json(ticker, 5, "1d")["meta"]["regularMarketPrice"])
        return {"price": price, "source": "yahoo chart meta"} if price > 0 else None
    except Exception:
        return None

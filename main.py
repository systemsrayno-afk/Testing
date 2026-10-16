"""LIVE TESTING API (port 8000). Fetches the latest candles, produces signals and manages PAPER trades.
It never connects to a broker and never places real orders.

Run:  uvicorn main:app --host 127.0.0.1 --port 8000
Open: http://127.0.0.1:8000/
"""
import threading
import time
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import live_engine
import strategy_check
import paper_trading as pt
from data_provider import fetch_history, get_live_quote, resolve_symbol
from indicators import add_indicators, analyze_frame

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Live Testing (paper only)", version="1.0.0")

# Short cache: several tabs / rapid clicks share one Yahoo request instead of hammering it (rate limits).
CACHE_TTL = 3.0
_cache, _cache_lock = {}, threading.Lock()


def cached_history(symbol, period, interval, market):
    key = (symbol.strip().upper(), period, interval, market)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    df = fetch_history(symbol, period, interval, market)
    with _cache_lock:
        _cache[key] = (now, df)
        for k in [k for k, v in _cache.items() if now - v[0] > 60]:
            del _cache[k]
    return df


def _candle_rows(df, limit):
    """Indicators are computed on the FULL history, then the tail is returned (so EMAs/VWAP are warmed up)."""
    df = add_indicators(df).tail(max(10, min(limit, 300)))
    def num(row, key):
        v = row.get(key)
        return None if pd.isna(v) else float(v)
    return [{"time": str(ts), "open": num(r, "Open"), "high": num(r, "High"), "low": num(r, "Low"),
             "close": num(r, "Close"), "volume": num(r, "Volume"), "ema9": num(r, "EMA9"),
             "ema21": num(r, "EMA21"), "vwap": num(r, "VWAP")} for ts, r in df.iterrows()]


class SignalTradeRequest(BaseModel):
    symbol: str
    market: str = "auto"
    period: str = "5d"
    interval: str = "5m"


class CloseRequest(BaseModel):
    id: str


class ResetRequest(BaseModel):
    confirm: bool = False


def _guard(fn):
    try:
        return fn()
    except Exception as exc:
        # a bare KeyError prints as just 'name'; always say what kind of error it was
        detail = str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: {exc}"
        raise HTTPException(status_code=400, detail=detail)


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "LIVE_TESTING_PAPER_ONLY", "orders": "never placed",
            "account_size": live_engine.ACCOUNT_SIZE, "risk_percent": live_engine.RISK_PERCENT}


@app.get("/api/analyze")
def analyze(symbol: str = "RELIANCE", market: str = "auto", period: str = "5d", interval: str = "5m"):
    def run():
        df = fetch_history(symbol, period, interval, market)
        result = analyze_frame(df, live_engine.ACCOUNT_SIZE, live_engine.RISK_PERCENT)
        result.update({"requested_symbol": symbol, "provider_symbol": resolve_symbol(symbol, market),
                       "market": market, "period": period, "interval": interval})
        return result
    return _guard(run)


@app.get("/api/candles")
def candles(symbol: str = "RELIANCE", market: str = "auto", period: str = "5d", interval: str = "5m", limit: int = 100):
    """Real provider candles for charting; never generates synthetic prices."""
    def run():
        rows = _candle_rows(fetch_history(symbol, period, interval, market), limit)
        return {"symbol": resolve_symbol(symbol, market), "candles": rows, "count": len(rows), "interval": interval,
                "note": "Provider candles; may be delayed (Yahoo is typically ~15 min for NSE) or incomplete."}
    return _guard(run)


@app.get("/api/snapshot")
def snapshot(symbol: str = "RELIANCE", market: str = "auto", interval: str = "5m", limit: int = 100):
    """Everything the dashboard needs in ONE request: analysis + candles + live quote + data freshness."""
    def run():
        period = "1y" if interval == "1d" else "5d"
        df = cached_history(symbol, period, interval, market)
        a = analyze_frame(df, live_engine.ACCOUNT_SIZE, live_engine.RISK_PERCENT)
        a.update({"requested_symbol": symbol, "provider_symbol": resolve_symbol(symbol, market),
                  "market": market, "period": period, "interval": interval})
        rows = _candle_rows(df, limit)
        price, quote, applied = a["price"], get_live_quote(symbol, market), False
        if quote and abs(quote["price"] / rows[-1]["close"] - 1) <= 0.02:      # sanity guard against bad quotes
            price, applied = quote["price"], True
            last = rows[-1]
            last["close"] = price
            last["high"], last["low"] = max(last["high"], price), min(last["low"], price)
        last_ts = pd.Timestamp(df.index[-1])
        last_ts = last_ts.tz_localize("UTC") if last_ts.tzinfo is None else last_ts
        age = round((pd.Timestamp.now(tz="UTC") - last_ts).total_seconds() / 60, 1)
        step = strategy_check.INTERVAL_MINUTES.get(interval, 5)
        stale = age > (step * 3 + strategy_check.PROVIDER_DELAY_MIN if step < 1440 else 4 * 1440)
        return {"analysis": a, "candles": {"symbol": a["provider_symbol"], "candles": rows, "count": len(rows), "interval": interval},
                "price": round(price, 2), "quote_applied": applied, "age_minutes": age, "stale": stale,
                "server_time": pd.Timestamp.now(tz="UTC").isoformat()}
    return _guard(run)


@app.post("/api/paper/open-from-signal")
def paper_open(req: SignalTradeRequest):
    return _guard(lambda: live_engine.open_from_signal(req.symbol, req.market, req.period, req.interval))


@app.get("/api/paper/positions")
def paper_positions():
    return {"positions": live_engine.refresh_positions()}


@app.post("/api/paper/close")
def paper_close(req: CloseRequest):
    return _guard(lambda: live_engine.close_at_market(req.id))


@app.get("/api/paper/ledger")
def paper_ledger():
    return pt.stats()


@app.post("/api/paper/reset")
def paper_reset(req: ResetRequest):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Send {\"confirm\": true} to erase the paper ledger.")
    pt.reset()
    return {"status": "ledger cleared"}


@app.get("/api/strategy-check")
def strategy_check_scan(symbols: str = "RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK", market: str = "auto", interval: str = "5m"):
    """Rule-by-rule live scan of a comma-separated watchlist (max 15). Read-only."""
    def run():
        from data_provider import validate_request
        validate_request("5d", interval)
        return {"interval": interval, "results": strategy_check.scan(symbols.split(","), market, interval)}
    return _guard(run)


@app.get("/api/strategy-health")
def strategy_health(min_trades: int = 20):
    return _guard(lambda: strategy_check.performance_health(max(1, min_trades)))


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")

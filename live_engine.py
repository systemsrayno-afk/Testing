"""Live paper-testing logic shared by the API and the monitor script."""
import paper_trading as pt
from data_provider import fetch_history, resolve_symbol
from indicators import analyze_frame

ACCOUNT_SIZE = 25000.0
RISK_PERCENT = 0.5


def open_from_signal(symbol, market="auto", period="5d", interval="5m") -> dict:
    """Analyze the latest candles and open a PAPER trade if the rules say BUY/SELL."""
    df = fetch_history(symbol, period, interval, market)
    a = analyze_frame(df, ACCOUNT_SIZE, RISK_PERCENT)
    base = {"signal": a["signal"], "price": a["price"], "last_candle": a["last_candle"]}
    if a["signal"] == "HOLD":
        return {"opened": False, "reason": "Signal is HOLD - no trade.", **base}
    if a["quantity"] <= 0:
        return {"opened": False, "reason": "Risk rules give quantity 0.", **base}
    if pt.has_open(symbol):
        return {"opened": False, "reason": f"{symbol.upper()} already has an open paper trade.", **base}
    trade = pt.open_trade(symbol, a["signal"], a["quantity"], a["entry"], a["stop_loss"], a["target_1"],
                          provider_symbol=resolve_symbol(symbol, market), market=market)
    return {"opened": True, "trade": trade, **base}


def refresh_positions(period="5d", interval="5m") -> list:
    """Auto-close open paper trades whose stop/target was hit since opening; mark the rest to market."""
    out = []
    for t in pt.list_trades("OPEN"):
        try:
            df = fetch_history(t["symbol"], period, interval, t.get("market", "auto"))
            hit = pt.check_exit(t, df)
            if hit:
                price, reason, when = hit
                closed = pt.close_trade(t["id"], price, reason, when)
                out.append({**closed, "auto_closed": True})
                continue
            last = float(df["Close"].iloc[-1])
            out.append({**t, "last_price": round(last, 2), "unrealized_pnl": pt.unrealized(t, last), "last_candle": str(df.index[-1])})
        except Exception as exc:   # one bad symbol must not hide the other positions
            out.append({**t, "error": str(exc)})
    return out


def close_at_market(trade_id: str, period="5d", interval="5m") -> dict:
    t = next((x for x in pt.list_trades("OPEN") if x["id"] == trade_id), None)
    if not t:
        raise ValueError(f"No open trade with id {trade_id}.")
    df = fetch_history(t["symbol"], period, interval, t.get("market", "auto"))
    return pt.close_trade(trade_id, float(df["Close"].iloc[-1]), "manual", df.index[-1])

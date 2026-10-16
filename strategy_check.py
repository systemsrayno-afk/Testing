"""Live strategy check: (1) rule-by-rule scan of a watchlist, (2) health of your paper-trade results.
Read-only: it never opens or closes trades."""
import pandas as pd

import paper_trading as pt
from data_provider import fetch_history
from indicators import MIN_CANDLES, add_indicators, analyze_frame, signal_flags
import live_engine

INTERVAL_MINUTES = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "90m": 90, "1d": 1440}
PROVIDER_DELAY_MIN = 20          # Yahoo NSE data is typically ~15 min behind


def _trailing_true(series) -> int:
    n = 0
    for v in reversed(series.tolist()):
        if not v:
            break
        n += 1
    return n


def check_frame(df: pd.DataFrame, interval: str = "5m", now=None) -> dict:
    d = add_indicators(df)
    if len(d) < MIN_CANDLES:
        raise ValueError(f"Only {len(d)} candles; need {MIN_CANDLES}.")
    a = analyze_frame(df, live_engine.ACCOUNT_SIZE, live_engine.RISK_PERCENT)
    bull, bear = signal_flags(d)
    r = d.iloc[-1]
    price = float(r["Close"])
    rsi = float(r["RSI14"]) if pd.notna(r["RSI14"]) else 50.0
    vwap = float(r["VWAP"]) if pd.notna(r["VWAP"]) else None

    rules = [
        {"name": "EMA trend", "required": True, "buy": bool(r["EMA9"] > r["EMA21"]), "sell": bool(r["EMA9"] < r["EMA21"]),
         "detail": f"EMA9 {r['EMA9']:.2f} vs EMA21 {r['EMA21']:.2f}"},
        {"name": "MACD", "required": True, "buy": bool(r["MACD"] > r["MACDSignal"]), "sell": bool(r["MACD"] < r["MACDSignal"]),
         "detail": f"MACD {r['MACD']:.3f} vs signal {r['MACDSignal']:.3f}"},
        {"name": "RSI", "required": True, "buy": rsi >= 50, "sell": rsi <= 50, "detail": f"RSI14 {rsi:.1f} (BUY needs >= 50, SELL <= 50)"},
        {"name": "VWAP (context)", "required": False, "buy": vwap is not None and price > vwap,
         "sell": vwap is not None and price < vwap, "detail": "n/a" if vwap is None else f"price {price:.2f} vs VWAP {vwap:.2f}"},
    ]
    buy_score = sum(1 for x in rules if x["required"] and x["buy"])
    sell_score = sum(1 for x in rules if x["required"] and x["sell"])
    signal = a["signal"]
    active = bull if signal == "BUY" else bear if signal == "SELL" else None
    bars_since = _trailing_true(active) if active is not None else 0

    last = pd.Timestamp(d.index[-1])
    last = last.tz_localize("UTC") if last.tzinfo is None else last
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    age_min = round((now - last).total_seconds() / 60, 1)
    step = INTERVAL_MINUTES.get(interval, 5)
    stale = age_min > (step * 3 + PROVIDER_DELAY_MIN if step < 1440 else 4 * 1440)

    notes = []
    if stale:
        notes.append("Last candle is old: market may be closed or the feed is delayed. Do not act on this signal.")
    if signal != "HOLD" and bars_since > 1:
        notes.append(f"Signal has been on for {bars_since} candles; an entry normally waits for a fresh trigger.")
    if signal != "HOLD" and a["quantity"] == 0:
        notes.append("Risk rules size this trade at 0 shares.")
    return {"signal": signal, "price": a["price"], "buy_score": buy_score, "sell_score": sell_score, "rules_required": 3,
            "rules": rules, "fresh": signal != "HOLD" and bars_since == 1, "bars_in_signal": bars_since,
            "entry": a["entry"], "stop_loss": a["stop_loss"], "target": a["target_1"], "quantity": a["quantity"],
            "last_candle": str(d.index[-1]), "age_minutes": age_min, "stale": stale, "notes": notes}


def scan(symbols, market="auto", interval="5m", period="5d", fetch=None) -> list:
    fetch = fetch or fetch_history
    out = []
    for sym in [s.strip() for s in symbols if s.strip()][:15]:
        try:
            out.append({"symbol": sym.upper(), **check_frame(fetch(sym, period, interval, market), interval)})
        except Exception as exc:       # one bad symbol must not break the scan
            out.append({"symbol": sym.upper(), "error": str(exc)})
    order = {"BUY": 0, "SELL": 1, "HOLD": 2}
    return sorted(out, key=lambda x: (1 if "error" in x else 0, order.get(x.get("signal"), 3), -(max(x.get("buy_score", 0), x.get("sell_score", 0)))))


def performance_health(min_trades: int = 20) -> dict:
    closed = pt.list_trades("CLOSED")
    n = len(closed)
    base = {"closed_trades": n, "min_trades_for_verdict": min_trades}
    if n == 0:
        return {**base, "verdict": "NO_DATA", "message": "No closed paper trades yet. Open some from the Paper trades page or run monitor.py --auto-paper."}
    closed.sort(key=lambda t: pd.Timestamp(t["closed_at"]).tz_convert("UTC") if pd.Timestamp(t["closed_at"]).tzinfo else pd.Timestamp(t["closed_at"], tz="UTC"))
    pnls = [t["pnl"] for t in closed]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p <= 0]
    curve, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls:
        curve += p
        peak = max(peak, curve)
        max_dd = max(max_dd, peak - curve)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    pf = round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else None
    expectancy = round(sum(pnls) / n, 2)
    reasons = {}
    for t in closed:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    breakeven = round(abs(avg_loss) / (avg_win + abs(avg_loss)) * 100, 1) if wins and losses else None
    win_rate = round(len(wins) / n * 100, 1)
    if n < min_trades:
        verdict, msg = "TOO_EARLY", f"{n} closed trades. Need at least {min_trades} before the results mean anything ({min_trades - n} more)."
    elif expectancy > 0 and pf is not None and pf >= 1.2:
        verdict, msg = "HEALTHY", "Positive expectancy after costs on this sample. Keep forward-testing before risking real money."
    elif expectancy > 0:
        verdict, msg = "MARGINAL", "Slightly profitable, but the edge is thin and could be noise or costs."
    else:
        verdict, msg = "FAILING", "Negative expectancy after costs. Do not trade this live; revisit the rules."
    return {**base, "verdict": verdict, "message": msg, "net_pnl": round(sum(pnls), 2), "win_rate_pct": win_rate,
            "breakeven_win_rate_pct": breakeven, "profit_factor": pf, "expectancy_per_trade": expectancy,
            "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2), "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct_of_account": round(max_dd / live_engine.ACCOUNT_SIZE * 100, 2), "exit_reasons": reasons}

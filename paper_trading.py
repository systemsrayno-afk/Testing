"""Persistent PAPER trade ledger. No broker connection, no real orders - ever.

Trades are stored in data/paper_ledger.json so they survive restarts.
"""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
LEDGER_PATH = Path(os.environ.get("PAPER_LEDGER_PATH", ROOT / "data" / "paper_ledger.json"))
COMMISSION_PCT = 0.03          # per side, % of turnover (applied when a trade is closed)
_lock = threading.RLock()


def _load() -> list:
    if not LEDGER_PATH.exists():
        return []
    with open(LEDGER_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(trades: list) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2)
    os.replace(tmp, LEDGER_PATH)       # atomic: a crash can't leave a half-written ledger


def open_trade(symbol, side, quantity, entry, stop_loss, target, provider_symbol=None, market="auto") -> dict:
    side = str(side).upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("Side must be BUY or SELL.")
    if int(quantity) <= 0 or min(entry, stop_loss, target) <= 0:
        raise ValueError("Quantity, entry, stop-loss and target must be positive.")
    if side == "BUY" and not stop_loss < entry < target:
        raise ValueError("For BUY, expected stop-loss < entry < target.")
    if side == "SELL" and not target < entry < stop_loss:
        raise ValueError("For SELL, expected target < entry < stop-loss.")
    trade = {"id": uuid.uuid4().hex[:8], "symbol": symbol.upper(), "provider_symbol": provider_symbol or symbol.upper(),
             "market": market, "side": side, "quantity": int(quantity), "entry": float(entry),
             "stop_loss": float(stop_loss), "target": float(target), "status": "OPEN",
             "opened_at": datetime.now(timezone.utc).isoformat(), "mode": "PAPER_ONLY"}
    with _lock:
        trades = _load()
        trades.append(trade)
        _save(trades)
    return trade


def list_trades(status=None) -> list:
    with _lock:
        trades = _load()
    return [t for t in trades if status is None or t["status"] == status]


def has_open(symbol: str) -> bool:
    return any(t["symbol"] == symbol.upper() for t in list_trades("OPEN"))


def unrealized(trade: dict, price: float) -> float:
    d = 1 if trade["side"] == "BUY" else -1
    return round((price - trade["entry"]) * trade["quantity"] * d, 2)


def close_trade(trade_id: str, price: float, reason: str, when=None) -> dict:
    if price <= 0:
        raise ValueError("Exit price must be positive.")
    with _lock:
        trades = _load()
        for t in trades:
            if t["id"] == trade_id:
                if t["status"] != "OPEN":
                    raise ValueError("Trade is already closed.")
                gross = unrealized(t, price)
                cost = round(COMMISSION_PCT / 100 * (t["entry"] + price) * t["quantity"], 2)
                t.update({"status": "CLOSED", "exit_price": float(price), "exit_reason": reason,
                          "closed_at": str(when) if when is not None else datetime.now(timezone.utc).isoformat(),
                          "costs": cost, "pnl": round(gross - cost, 2)})
                _save(trades)
                return t
    raise ValueError(f"No trade with id {trade_id}.")


def check_exit(trade: dict, candles: pd.DataFrame):
    """Scan candles that formed after the trade opened. Returns (price, reason, time) or None.
    If one candle touches both stop and target, the STOP is assumed first (conservative)."""
    opened = pd.Timestamp(trade["opened_at"])
    idx = pd.DatetimeIndex(candles.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    after = candles[idx > opened]
    for ts, row in after.iterrows():
        hi, lo = float(row["High"]), float(row["Low"])
        if trade["side"] == "BUY":
            if lo <= trade["stop_loss"]:
                return trade["stop_loss"], "stop", ts
            if hi >= trade["target"]:
                return trade["target"], "target", ts
        else:
            if hi >= trade["stop_loss"]:
                return trade["stop_loss"], "stop", ts
            if lo <= trade["target"]:
                return trade["target"], "target", ts
    return None


def stats() -> dict:
    closed = list_trades("CLOSED")
    pnls = [t["pnl"] for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    return {"open_trades": len(list_trades("OPEN")), "closed_trades": len(closed),
            "net_pnl": round(sum(pnls), 2), "win_rate_pct": round(len(wins) / len(pnls) * 100, 2) if pnls else 0.0,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else None,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "closed": closed[-200:][::-1]}


def reset() -> None:
    with _lock:
        _save([])

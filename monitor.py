"""Live paper-testing loop (no UI needed). Polls the latest candles, prints signals,
and (optionally) opens/closes PAPER trades. Never places real orders.

  python monitor.py --symbols RELIANCE,TCS,INFY --interval 5m --every 60 --auto-paper
  python monitor.py --symbols RELIANCE --once
"""
import argparse
import time
from datetime import datetime

import live_engine
import paper_trading as pt
from data_provider import fetch_history
from indicators import analyze_frame


def tick(symbols, market, interval, auto_paper):
    stamp = datetime.now().strftime("%H:%M:%S")
    for closed in [p for p in live_engine.refresh_positions() if p.get("auto_closed")]:
        print(f"[{stamp}] CLOSED {closed['symbol']} {closed['side']} via {closed['exit_reason']}  PnL {closed['pnl']}")
    for sym in symbols:
        try:
            a = analyze_frame(fetch_history(sym, "5d", interval, market), live_engine.ACCOUNT_SIZE, live_engine.RISK_PERCENT)
            line = f"[{stamp}] {sym:<12} {a['signal']:<4} price {a['price']:<10} RSI {a['rsi14']:<6} last candle {a['last_candle'][:16]}"
            if auto_paper and a["signal"] != "HOLD":
                res = live_engine.open_from_signal(sym, market, "5d", interval)
                line += "  -> PAPER TRADE OPENED" if res["opened"] else f"  ({res['reason']})"
            print(line)
        except Exception as exc:
            print(f"[{stamp}] {sym:<12} ERROR {exc}")
    s = pt.stats()
    print(f"[{stamp}] ledger: {s['open_trades']} open, {s['closed_trades']} closed, net PnL {s['net_pnl']}\n")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbols", default="RELIANCE,TCS")
    p.add_argument("--market", default="auto")
    p.add_argument("--interval", default="5m")
    p.add_argument("--every", type=int, default=60, help="seconds between polls (min 15)")
    p.add_argument("--auto-paper", action="store_true", help="open paper trades automatically on BUY/SELL")
    p.add_argument("--once", action="store_true")
    args = p.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    while True:
        tick(symbols, args.market, args.interval, args.auto_paper)
        if args.once:
            break
        time.sleep(max(15, args.every))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.")

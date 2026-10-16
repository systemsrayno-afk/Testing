# NSE Live Testing (paper only)

Fetches the latest candles, shows rule-based signals, checks whether the strategy is firing, and runs
**paper** trades that close automatically at stop/target. **No broker connection, no real orders.**
Signals (EMA 9/21 + MACD + RSI) are educational, not financial advice.

## Windows (easiest)
1. Install Python 3.11+ from python.org (tick **Add python.exe to PATH**).
2. Double-click **`setup.bat`** once (installs everything and runs the tests).
3. Double-click **`start.bat`**. It opens `http://127.0.0.1:8000/`.
4. **`stop.bat`** stops the server. **`start_monitor.bat`** runs the no-browser paper monitor.

To start at logon, put a shortcut to `start.bat` in `shell:startup`. Keep it on `127.0.0.1` (there is no login screen).

## Manual
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q
uvicorn main:app --host 127.0.0.1 --port 8000
```

## Pages
- `/` signal dashboard: candles, EMA/VWAP, indicators, entry/stop/target, position size.
  **Live mode** (top-right, on by default): refreshes every 5/10/30/60 s with no clicking. The headline price and the
  forming candle follow Yahoo's live quote; the status shows `LIVE` (with last-update time), `MARKET CLOSED / FEED STALE`,
  or `reconnecting`. Untick *Live* to pause; it also pauses while the browser tab is hidden. Interval buttons
  (1m/5m/15m/1h/1D) reload the chart, show a loading state, and show any error right on the chart.
- `/check.html` **live strategy check** (read-only): scans a watchlist and shows which of the 3 rules pass per symbol,
  whether the signal is *new* or already running, and data age (flags stale feed / closed market). A second panel judges
  your paper results: win rate vs break-even win rate, profit factor, expectancy, drawdown, verdict
  (NO DATA / TOO EARLY / HEALTHY / MARGINAL / FAILING). No verdict before 20 closed trades.
- `/paper.html` paper trades: **Paper-trade current signal**, open positions with live P&L, closed trades, stats (refresh 30 s).

Trades are saved to `data/paper_ledger.json` and survive restarts. Open trades auto-close when a candle formed
*after* opening touches the stop or target (stop first if both). 0.03% commission per side is applied on close.

## No-UI mode
```bash
python monitor.py --symbols RELIANCE,TCS,INFY --interval 5m --every 60 --auto-paper
python monitor.py --symbols RELIANCE --once
```

## API
`GET /api/snapshot` (analysis + candles + live quote in one call), `GET /api/analyze`, `GET /api/candles`, `GET /api/strategy-check`, `GET /api/strategy-health`,
`POST /api/paper/open-from-signal`, `GET /api/paper/positions`, `POST /api/paper/close`,
`GET /api/paper/ledger`, `POST /api/paper/reset` (needs `{"confirm": true}`), `GET /api/health`

## Know the limits
**"Live" here means polling, not a tick-by-tick stream.** The page re-reads Yahoo every few seconds, and Yahoo's
NSE data is typically ~15 minutes behind (the status line shows the real age of the last candle). Faster refresh does not
make delayed data real-time, and refreshing too aggressively can get you rate-limited. For genuinely live NSE ticks you need a
broker/licensed feed (e.g. a WebSocket from your broker's API); `fetch_history` / `get_live_quote` in `data_provider.py` are the
two functions to replace.

Yahoo NSE data is typically **delayed ~15 minutes** and the newest candle may still be forming, so this forward-tests
the *logic*; it is not an execution-accurate simulation. It does not model slippage on paper fills, lot sizes, margin or
circuit limits. For real-time data, replace `fetch_history` in `data_provider.py` with a licensed feed.
Free Yahoo intraday limits: 1m ~ 7 days, 5/15/30m ~ 60 days, 60m ~ 2 years.

## Troubleshooting
- **`Could not load data: 'tradingPeriods'`**: an old `yfinance` crashing on Yahoo's response. This version retries through
  Yahoo's chart API directly, so it should load anyway. To fix the cause too, run `setup.bat` again (it upgrades packages),
  or inside the project folder: `.venv\Scripts\python -m pip install -U yfinance`.
- **`HTTP 429` / rate limited**: too many requests. Set Live to 30 s or 60 s and wait a minute.
- **`empty candle list` / `No data`**: market closed, wrong symbol, or that interval isn't offered for the symbol.
  Try 5m or 1D. Errors are shown on the chart itself and always name the error type.
- **Page looks old after an update**: hard-refresh with `Ctrl + F5`.

Darvas V6.2 — Independent research scanner (beta)
Installation
Download the ZIP, extract it, and copy `darvas_v62.py`, `requirements_v62.txt`, and both files under `.github/workflows/` into the same paths in your existing GitHub repository.
Keep your existing `symbols.txt` file; it is the safe fallback universe.
Commit and push these files. Existing V6/V7 Python scripts and workflows are not replaced.
GitHub > Actions > Darvas V6.2 Weekly Universe > Run workflow. Wait for it to complete. It writes `symbols_v6_1500.txt` when sufficient source data is available; otherwise it preserves the previous/fallback universe.
GitHub > Actions > Darvas V6.2 Intraday and Daily Scan > Run workflow > choose `intraday` or `daily`.
Open the completed run > Artifacts > download the Excel report ZIP.
Design / important limitations
This is a new standalone beta, not a validated drop-in replacement for your current V6 trade lifecycle/backtester. The Darvas box detector is a simplified 2-bar-confirmed pivot proxy. It MUST be compared against your original V6 before relying on it.
No broker orders or automated trades. `INTRADAY BREAKOUT` is provisional. Intraday volume ratio is intentionally unavailable: a partial session is not compared to a full-day 20-session average.
Weekly universe uses Nasdaq Trader public listings and Yahoo Finance historical OHLCV. Liquidity threshold: >=$5m average daily dollar turnover, price >=$5, >=100 trading bars. It ranks eligible stocks on momentum, 52-week-high proximity and liquidity. It does not apply a market-cap threshold because free listing data lacks dependable market caps. It may contain non-common securities not captured by name-based exclusions; review audit.
Universe refresh is expensive for thousands of symbols and may be rate-limited. The workflow can fail or fall back; always check counts.
Daily and intraday scan download data for all symbols and may take a long time. Scheduled GitHub runs are best effort, not guaranteed real-time; timestamps and data quality should be checked.
`STATUS HISTORY` compares only against the latest saved state. Previous Excel artifacts retain historical snapshots, but there is no permanent multi-year signal database or performance backtest in this package.
The scanner currently shows one confirmed unbroken box proxy per ticker; higher-box add-on lifecycle and $5k/$1250 position simulation remain in existing V6, not in this beta.
Intraday 5-minute data may be delayed or unavailable. For manual trades verify live price/volume and market session with your broker.
GitHub cron schedules may run on holidays; no exchange-calendar package is currently used. Manual `daily` run during market hours can misclassify incomplete candles. Run daily after the close.
Universe is not guaranteed exactly 1,500 if insufficient eligible market data. This is reported; it never pads with arbitrary illiquid stocks.
Local commands
```bash
python -m pip install -r requirements_v62.txt
python darvas_v62.py universe --fallback symbols.txt --limit 1500
python darvas_v62.py scan --mode intraday
python darvas_v62.py scan --mode daily
```
Files generated
`symbols_v6_1500.txt` weekly selected tickers
`darvas_v62_universe_audit.csv` eligible ranking audit
`darvas_v62_report.xlsx` multi-tab research report
`darvas_v62_signal_state.json` latest scan status per ticker
No backtest performance, actual live signals or 1,500-stock universe was verified during package creation; testing was limited to local syntax and synthetic data.

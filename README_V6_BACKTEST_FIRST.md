# Darvas V6 — Backtest first: installation and review

This is a **complete V6 backtest package**, not a live trading release. It is manual-only and will not trade or modify Schwab. Your existing V5 files/workflows are left intact. **Back up the repository first.**

## Install to `RamaRaju11/Darvas`, branch `main`
1. GitHub > your repository > **Code** > **Download ZIP** to make a backup.
2. Download and extract `Darvas_V6_Complete_Backtest_First.zip`.
3. Upload these files at repository ROOT: `darvas_v6_backtest.py`, `test_v6_backtest.py`, `DARVAS_V6_REQUIREMENTS_REVISED.md`, `README_V6_BACKTEST_FIRST.md`. The package also contains existing V5 dependency `darvas_fresh_v4.py` and `symbols.txt`: **only upload these if missing**, otherwise preserve your repository's current versions. Do **not** overwrite `existing_dar_stocks.txt`, your ledger, stop confirmations, or V5 workflow.
4. Open existing `requirements.txt`; preserve its contents and add `artifact-tool` if missing. (The new V6 workflow also installs it explicitly.) Keep pandas/numpy/yfinance dependencies.
5. Create `.github/workflows/darvas-v6-backtest.yml` using GitHub > **Add file > Create new file**, enter the exact nested filename, paste the package workflow content, and **Commit changes**.
6. Go to **Actions** > **Darvas V6 - Five Year Multi-Box Backtest (Manual)** > **Run workflow**. Choose `limit=5`, `period=5y` first. After success choose `limit=0`, `period=5y` for all symbols.
7. Open the completed workflow > **Artifacts** > download workbook `darvas_v6_backtest_report.xlsx`. Review `SUMMARY`, `TRADE LEDGER`, `TRADE JOURNEY`, `BOX HISTORY`, `ADD-ON HISTORY`, `STOP HISTORY`, `MILESTONES`, `OPEN AT END`, `RULES & AUDIT`, `DATA COVERAGE`.
8. Confirm at least one multi-box position and verify cash arithmetic manually: **net realized P/L = final proceeds − all initial/add-on purchase costs − fees**. Check `HT2 MILESTONE` does not close the trade; only STOP exit or OPEN AT TEST END.
9. Do not turn on any V6 schedule or replace the V5 monitor until you approve historical results and data quality.

## What this engine does and does not prove
- **Backtest only:** independent $5,000 initial positions and $1,250 higher-box add-on budgets. **No global portfolio cash cap**, no $25,000 combined equity curve, no portfolio drawdown. These require a later portfolio simulator.
- **Box detection:** causal two-following-bar pivots; documented approximation, not proven identical to Darvas's book or V5 monitor. Box/stop parity with live V6 monitoring must be implemented and regression-tested before live deployment.
- **Execution:** daily OHLC stop-first assumption. Stop gap fills use the open, not an ideal stop price. Entry/add-on at next session's open. Same-session entry and stop touch are conservatively treated as possible stop exit. No intraday path reconstruction.
- **Pricing:** Yahoo daily unadjusted OHLC. Historical splits/dividends, delistings and provider errors can materially distort results. This release does not fully normalize corporate actions. Treat outputs as **research estimates**, not verified trading performance.
- **History:** Five-year Yahoo data is best effort. Current 400 names introduce survivorship bias. Reported coverage is per ticker.
- **Stop timing:** a newly confirmed higher-box stop becomes effective for the *following* session; the event log date is the confirmation date.
- **No live data imports or Schwab trading**. Screenshot-to-ledger work will be a later stage after backtest review.

## Troubleshooting
- `ModuleNotFoundError`: verify the workflow installed requirements and `artifact-tool`.
- No trades: 0 valid signals is a valid outcome; inspect `DATA COVERAGE`, scan filters, and test 5 symbols before all 400.
- Workflow not shown: check YAML path `.github/workflows/darvas-v6-backtest.yml` on `main`.
- 400-symbol run too slow: test 5 first, then 50; market-data throttling can cause individual ticker errors.

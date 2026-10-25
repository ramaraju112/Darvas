DARVAS V6 BUY RANKING — STATUS CLARITY UPDATE (2026-10-25)

Replace/add the following files in your GitHub repository:

Repository root:
  darvas_buy_ranking.py          REPLACE
  requirements_v6.txt           REPLACE

.github/workflows/:
  darvas-v6-review.yml          REPLACE
  darvas-v6-five-year-multibox-backtest.yml   REPLACE (same dedicated backtest workflow)

Do NOT overwrite existing darvas_fresh_v4.py, darvas_v5_excel.py, darvas_v6_backtest.py,
or darvas_v6_portfolio.py. They are not included because this update does not change them.

For custom historical backtests, create/maintain backtest_symbols.txt in repository root.
Use workflow period=5y and limit=0 to test all tickers in that file.

To run current signal scan: Actions -> Darvas V6 Review -> Run workflow -> scan.
The output darvas_v5_scan_report.xlsx includes BUY RANKING and RANKING GUIDE.

NEW CLASSIFICATIONS:
  RESEARCH CANDIDATE: newest scan date; hard rules pass; score >=70.
  WATCH / RECHECK: newest scan date; hard rules pass; score below 70.
  STALE SIGNAL: older/missing signal date; all other hard rules pass.
  REJECT - FAILED RULES: at least one hard rule fails (may also be old).

These are experimental research categories, not trade orders.
The existing historical V6 backtest does not validate ranking profitability.
The GitHub workflows have NOT been run against your current repository.

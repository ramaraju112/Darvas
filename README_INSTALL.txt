DARVAS V6 — BUY RANKING + BREAKOUT PERFORMANCE TRACKER
=====================================================

UPLOAD / REPLACE in GitHub repository ramaraju112/Darvas:
ROOT:
  darvas_buy_ranking.py           REPLACE (previous latest classification logic)
  darvas_breakout_tracker.py      ADD (new)
  requirements_v6.txt             REPLACE
  v6_breakout_signals.csv         CREATED AUTOMATICALLY on first successful scan

.github/workflows/:
  darvas-v6-review.yml            REPLACE
  darvas-v6-five-year-multibox-backtest.yml   REPLACE (same as prior package; no strategy change)

KEEP UNCHANGED:
  darvas_fresh_v4.py, darvas_v5_excel.py, darvas_v6_backtest.py,
  darvas_v6_portfolio.py, symbols.txt, backtest_symbols.txt

RUN:
  GitHub > Actions > Darvas V6 Review - Manual Portfolio and V5 Scan
  > Run workflow > mode=scan.
  Download darvas-v6-review-scan-<runid> artifact and open
  darvas_v5_scan_report.xlsx in LibreOffice Calc.

REPORT SHEETS:
  BUY RANKING, BREAKOUT TRACKER, PERFORMANCE SUMMARY, RANKING GUIDE,
  plus existing original sheets.

PERSISTENCE:
  Successful scan workflows commit v6_breakout_signals.csv to your repo.
  Repository Actions settings must allow GITHUB_TOKEN write permissions
  and branch protection must permit the bot to push. If not, tracker
  still appears in the downloaded report for that run, but older signals
  won't be retained across runs until the registry is committed.
  The initial registry is seeded from the current BUY - Review worksheet,
  not from all older signals that may have disappeared before installation.

PRICE / STOP CONVENTIONS:
  Breakout close is the historical SIGNAL close, not a fill price.
  Subsequent daily bars exclude the signal day. Price change compares
  latest completed daily CLOSE to signal-day CLOSE.
  Stop touched = any later daily LOW <= original suggested stop.
  Stop touched does not mean an order was actually filled at that price.
  Price data: Yahoo Finance, auto_adjust=False. Splits, symbol changes,
  source adjustments and missing bars may make older comparisons unreliable.
  Review historical corporate actions before interpreting unusual returns.
  Missing price data is flagged, not treated as a loss or gain.
  This is NOT a V6 strategy backtest and is NOT a buy/sell instruction.

V7 multibagger scanner is NOT part of this V6 update.

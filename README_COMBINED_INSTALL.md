# Darvas V6 combined installation — BACKTEST FIRST

This package combines the V6 multi-box historical backtest with the V6 Stage A portfolio/Schwab-stop review. Both GitHub Actions workflows are **manual-only**. No automatic trading is included.

## 1. Protect existing GitHub files
1. Open https://github.com/RamaRaju11/Darvas on `main`.
2. Select **Code > Download ZIP** to back up your current repository.
3. Extract this ZIP locally. **Do not blindly upload the whole ZIP or replace existing populated files.**
4. Keep existing `existing_dar_stocks.txt`, populated `portfolio_ledger.csv`, `schwab_stop_confirmations.csv`, existing V5 source files, and scheduled workflows intact.

## 2. Install the BACKTEST FIRST (recommended)
Upload these NEW root-level files via GitHub **Add file > Upload files**:
- `darvas_v6_backtest.py`
- `test_v6_backtest.py`
- `requirements_v6.txt`
- `DARVAS_V6_REQUIREMENTS_REVISED.md`
- `README_COMBINED_INSTALL.md`

The package includes reference copies of `darvas_fresh_v4.py` and `symbols.txt` because the backtester imports the former and reads the latter. **Do not overwrite those files if they already exist in your repository.** Ensure `symbols.txt` contains your intended 400 stocks.

To create the workflow, select **Add file > Create new file**, enter `.github/workflows/darvas-v6-backtest.yml`, paste the file's contents, and commit to `main`. If that workflow already exists, review differences before updating.

Go to **Actions > Darvas V6 - Five Year Multi-Box Backtest (Manual) > Run workflow**. Start with `limit=5` and `period=5y`. Download the Excel report from **Artifacts**. Then run `limit=0` for all tickers.

Review `TRADE LEDGER`, `TRADE JOURNEY`, `ADD-ON HISTORY`, `STOP HISTORY`, `OPEN AT END`, and `DATA COVERAGE`. Check the $5,000 initial purchase, $1,250 per higher-box breakout, whole shares, stop exits, and dollar P/L. HT1/HT2 are milestones, not automatic exits.

## 3. Install PORTFOLIO REVIEW after you accept the backtest
Upload `darvas_v6_portfolio.py` and `portfolio_config.json` to repository root. If you have no existing `portfolio_ledger.csv`, `schwab_stop_confirmations.csv`, or `v6_alert_state.json`, add the included blank templates; **never replace populated copies with blank templates**.

Enter your actual starting capital in `portfolio_config.json`. Record every *confirmed* trade, deposit, withdrawal, and sale in `portfolio_ledger.csv` since the starting capital date. Confirm working Schwab stop orders manually in `schwab_stop_confirmations.csv`. Do not treat a recommendation or a stop touch as a completed transaction.

Create `.github/workflows/darvas-v6-review.yml` using the included YAML. This portfolio workflow currently depends on the existing V5 monitor and your existing `requirements.txt` and `existing_dar_stocks.txt`. Choose **Actions > Darvas V6 Review - Manual Portfolio and V5 Baseline > Run workflow > portfolio** only after your ledger and stop confirmations are reconciled. Telegram requires existing `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` repository secrets. It does not modify Schwab orders.

The portfolio review workflow may commit `v6_alert_state.json` to avoid repeat alerts; repository workflow write permissions may be needed. This is the only intentional repository-state write by that workflow.

## 4. Known limitations / acceptance gates
- Backtest is **per-position** and does not enforce a single $25,000 cash pool across concurrent positions. A portfolio-level capital-constrained historical simulator is still required to validate add-on versus new-buy selection.
- The historical box algorithm is an approximation and is not yet proven identical to the existing V5 live monitor. Before live V6 deployment, unify and regression-test both.
- Daily OHLC data cannot reconstruct intraday ordering; gap fills and stop-first assumptions are modeled. Corporate actions, survivorship bias and missing market data may distort results.
- Portfolio review opportunities are preliminary and **not yet ranked by a validated add-on-versus-new-buy scoring model**.
- Screenshots of Schwab orders are not automatically imported; the ledger and stop file require manual verification.
- No automatic Schwab trading or scheduled V6 monitoring is enabled by this package. Do not disable V5 yet.

## 5. Troubleshooting
- Missing `darvas_fresh_v4`: restore your existing source or use the bundled reference copy if absent.
- Missing dependencies: check that the V6 backtest workflow installs `requirements_v6.txt` and the portfolio workflow installs both existing `requirements.txt` and `requirements_v6.txt`.
- No backtest workbook: inspect Actions job logs and data coverage; start with 5 stocks.
- Inaccurate portfolio cash: reconcile all fills, dividends, fees, deposits and withdrawals against Schwab before relying on cash recommendations.

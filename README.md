# Darvas V7.4 Browser Application — Integrated MVP

## What is working
- Browser dashboard on Windows using FastAPI, with SQLite persistence
- Free-source daily historical OHLCV download for selected tickers, including SPY/QQQ
- Local price charts and data coverage
- Simplified Darvas breakout-watch and early-recovery-watch heuristics, clearly marked unconfirmed
- Schwab-style CSV position import (symbol,quantity,cost_basis,horizon,thesis)
- Portfolio values from last stored daily close, with explicit unknown order protection
- Per-stock persistent notes and copyable ChatGPT research briefs
- Optional **manual test** Telegram message when credentials are configured
- Exploratory 20-session forward-return study, not a validated backtest

## What is NOT yet working
- Complete point-in-time market universe download or certified market-wide coverage
- Full frozen V7.4 pivot/box, RS20/60, corporate-action and replay rules
- Live Schwab API connection, open-order checks, reliable intraday risk monitoring
- Automated Telegram monitoring/alerts or background service
- Live news/earnings/options feeds or automatic OpenAI API research
- Reliable production backtesting or trading

## Windows setup
1. Install Python 3.11+ from python.org. Enable **Add Python to PATH**.
2. Extract the ZIP to `C:\DarvasV74` (do not run from inside ZIP).
3. Double-click `START_DARVAS.bat`. First launch installs packages; Internet required.
4. Open `http://127.0.0.1:8000` in Edge/Chrome. Keep command window open.
5. In **Market Data**, click **Download starter symbols**. Initial download can take time and free sources may throttle or reject requests.
6. In **Portfolio**, import `sample_portfolio.csv` to test; replace it with a sanitized real CSV only after reviewing column mapping. Import replaces existing positions.
7. Use **Scanner**, **Research**, **History**, **Alerts** tabs.
8. To stop, close command window or press Ctrl+C.

## Downloading more symbols
Enter comma-separated tickers and select period. Max 150 per batch. This is deliberately not an unrestricted full-market downloader: free provider rate limits, terms and delisted-symbol gaps make that unsafe to claim. Data persists in `data/darvas.db`.

## Optional Telegram test
Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the environment BEFORE starting. Example in Command Prompt (values omitted intentionally):
```
set TELEGRAM_BOT_TOKEN=your_private_token
set TELEGRAM_CHAT_ID=your_chat_id
START_DARVAS.bat
```
Never share your bot token. Telegram send success does not verify phone receipt. No automatic alerts run.

## Security and data
Runs bound to 127.0.0.1, not exposed to Internet. No account login; do not expose port publicly. Local SQLite may contain sensitive portfolio data: secure the computer and backups. Never enter Schwab passwords. No orders are placed.

## Quality and disclaimers
The current screeners are **simplified research heuristics**, not the complete V7.4 specification. Prices may be delayed, stale, split-affected or incomplete. Research only, not investment advice. Verify provider usage rights before large-scale collection. The software has been syntax and API smoke tested locally; external live provider calls and Windows execution have not been verified here.

## GitHub portability
The repository contains code and synthetic example data only. The `data/` directory is intentionally excluded by `.gitignore`. When moving computers, either re-download prices or securely transfer your database separately.

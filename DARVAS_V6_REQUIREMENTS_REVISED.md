# Darvas V6 — Multi-Box Trade Lifecycle Requirements
**Status:** REVIEW DRAFT — not implemented or approved for live trading  
**Prepared:** 2026-10-18  
**Supersedes for planning:** Darvas V5 requirements where inconsistent; retain V5 source files until V6 is tested and approved.

## 1. Product goal
Build a cash-only, manually executed Darvas-style stock scanner, five-year historical backtester, and Schwab holdings monitor that explains the **entire life of each trade**: discovery → initial purchase → successive confirmed higher boxes → backtest fixed-budget add-ons / live user-chosen purchases → suggested protective-stop changes → actual or simulated exit → realized dollar P/L. Preserve chronological commentary and an auditable event log. HT1/HT2 are **milestones, not automatic exits**.

## 2. Non-negotiable safety and execution rules — agreed
- No automated buying, selling, or Schwab order modification; no leverage or margin assumed.
- Actual Schwab broker-held stops provide primary protection. GitHub Actions ~30-minute monitoring is supplementary, best effort, and not continuous. Stop-market orders can slip/gap.
- Differentiate **scanner suggestion**, **backtest simulated fill**, and **user-confirmed actual Schwab fill** in every report. Do not infer a trade occurred from market prices.
- A stock in the scan universe is not necessarily owned. Never overwrite actual holdings with a sample.
- Stop touches persist as RED / ACTION REQUIRED until explicitly reconciled; never silently mark an actual position closed.
- The original Darvas method supports holding through rising boxes and selective pyramiding; **fixed 25% add-ons, HMA38, and a 52-week proximity threshold are modern proposed parameters, not book mandates**.

## 3. Inputs and configuration
| File / parameter | Requirement |
|---|---|
| `symbols.txt` | 400 unique stock symbols, used by both SCAN and BACKTEST; report missing, delisted, renamed, and incomplete histories. Dynamic weekly refresh is a future enhancement, not an assumed live feature. |
| `existing_dar_stocks.txt` | Existing legacy holdings supported (`ticker,entry,stop,ht1,ht2`); migrate to a richer versioned holdings ledger without losing original records. |
| Holdings ledger | For accurate live lifecycle: ticker, position ID, purchase date, quantity, actual price, fees, manually recorded Schwab stop price, stop-enabled status, stop-confirmation status/date, and optional order ID; separate add-on transactions and exit confirmations. Missing data must be shown as UNKNOWN, not fabricated. |
| Historical period | Default **5 calendar years** ending on latest completed market session, with actual coverage dates and missing-data counts per ticker. |
| Initial allocation | **$5,000 per simulated new position** as a budget; use whole shares by default, unused cash remains uninvested. |
| Add-on allocation | **Fixed $1,250 budget at every newly confirmed higher-box breakout in BACKTEST, with no additional volume/HMA/return qualification for the add-on**, not 25% of current portfolio or position value. Whole shares, actual amount may be less. |
| Add-on controls | **BACKTEST:** add at each new confirmed higher-box breakout; no optional skip based on volume, HMA, profitability or other add-on signal filters. Record an attempted $1,250 add every time. Whole-share execution may spend less than $1,250; a zero-share fill or unavailable next-session price is reported explicitly. **MONITOR:** user decides whether and how much to buy at each stage; record actual confirmed shares, fill price, date and dollars, including $0/no add. Any separate portfolio capital constraints must be reported transparently, not silently treated as Darvas add-on filters. |
| Stop logic | Initial structural stop = confirmed box low; proposed stop may only rise after a newly confirmed higher box; no stop decrease. Timing and exact ratchet formula must be specified and backtested. |
| Schwab stop confirmation | **Approved: manual confirmation through the GitHub holdings file.** No Schwab API integration or Telegram reply workflow is required for V6. |
| Telegram | Existing `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` GitHub secrets; no secrets in logs or files. |

### Allocation examples (illustrative, no fees)
- BACKTEST Box 1: buy at $100, $5,000 budget → 50 shares; invested $5,000.
- BACKTEST Box 2: new confirmed higher-box breakout at $125 → **always attempt** $1,250 add → 10 shares; cumulative invested $6,250.
- BACKTEST Box 3: new confirmed higher-box breakout at $150 → **always attempt** $1,250 add → 8 whole shares, $1,200 actually spent; cumulative invested $7,450. Weak volume is **not** an add-on veto in this illustrative backtest rule.
- BACKTEST Box 4: new confirmed higher-box breakout at $175 → **always attempt** $1,250 add → 7 whole shares, $1,225 spent; cumulative invested **$8,675**, 75 shares. Assumes prices stated are the next-session execution opens and sufficient funds exist.
- Exit all 75 shares at $140 → gross proceeds **$10,500**; gross realized profit **+$1,825**; gross return on invested dollars **+21.04%** before fees/slippage.
- Stop example before add-ons: 50 shares bought at $100, stop fills at $90 → $4,500 proceeds, **−$500 (−10%)**; gap fill at $85 → $4,250 proceeds, **−$750 (−15%)**.
- Stop example after add-ons: the 75-share/$8,675 position stops at a modeled $105 fill → $7,875 proceeds, **−$800 (−9.22%)** before costs. Actual stop execution depends on gaps and order behavior.
- MONITOR: for the same Box 1–4 sequence, the user may buy $5,000 initially, add $600 at Box 2, add $0 at Box 3, and add $2,000 at Box 4. The monitor uses **actual confirmed fill quantities and prices**, not the backtest's $1,250 rule. The same box-confirmation and protective-stop logic applies to both modes, while live broker-stop changes require confirmation.

## 4. Daily SCAN: 400-symbol candidate discovery
- Use completed daily candles for **confirmed** buy/add signals; never label intraday provisional breakouts as confirmed.
- Confirm Darvas box high/low with subsequent completed bars and **no future-data lookahead**. Current provisional design uses 2 subsequent bars; test 3-bar variant.
- Require breakout close above confirmed box high, breakout-session volume ≥1.5× prior 20 completed sessions' average, HMA38 rising, breakout age 0–1 completed sessions, and proposed entry above box high but ≤3% extended. Validate thresholds by backtest.
- Compute 52-week high and % below high for display/ranking. **Do not enforce the previously proposed 10% filter until historical comparisons support and user approves it**.
- Include all 400 input outcomes, explicit reasons and data quality. Statuses: BUY CANDIDATE, WATCH, EXTENDED, REJECT, DATA ERROR. No manufactured BUY signals; 0 is valid.
- HT1 = box high + width and HT2 = box high + 2×width are **informational milestones only**; they do not close V6 positions.
- Keep user holdings monitored even if removed from the 400-symbol list.

## 5. Multi-box lifecycle engine — primary V6 strategy
1. Assign stable `position_id`, `box_id`, `event_id`, `strategy_version`, and as-of timestamp.
2. Initial confirmed breakout generates BUY CANDIDATE. Backtest simulates entry at **next completed session's open** (not same-day breakout close); live system awaits user-confirmed Schwab buy.
3. Track Box 1 → Box 2 → Box 3 → Box N with dates, confirmed highs/lows, breakout date, volume ratio, HMA trend, and commentary. No arbitrary final HT2/Box 2.
4. For each newly confirmed *higher* box (both high and low higher), detect its confirmed breakout. **BACKTEST: automatically attempt one $1,250-budget add at every unique higher-box breakout, without extra qualification or discretionary skipping.** MONITOR: present the stage and record whether the user actually added any shares, and how much. Never add on a lower box or average down.
5. Backtest simulates the $1,250-budget purchase at the **next session's open** for each higher-box breakout. Use whole shares; report actual invested amount and unspent remainder. Do **not** reject an add because of breakout-volume, HMA, extension, or existing profit tests. If there is no next-session price, not enough funds under an explicitly selected cash model, or the price exceeds the budget for one share, record UNFILLED with the exact operational reason. Do not fabricate a fill.
6. Raise the **recommended** stop only once the higher box is confirmed and stop rule passes. Never retroactively apply a stop before it was known. In live monitor, actual broker stop remains unchanged until user confirmation.
7. Do not exit automatically at HT1/HT2. Simulated final exit is triggered by active stop (including opening gaps) or an explicitly configured strategy exit rule. At historical end, mark **OPEN AT TEST END / CENSORED** and show unrealized mark-to-market separately; never invent a sale.
8. Record every material event with date, price, shares, capital deployed, stop before/after, holding age, reasons, and narrative commentary.

## 6. Five-year BACKTEST engine
- Use **the same box confirmation, breakout detection, and stop calculation logic** as scanner and monitor, with time-aware historical replay and no future-data lookahead. **Purchase decisions differ by mode:** automatic $1,250 add-on budget per new higher-box breakout in BACKTEST; only user-confirmed purchases in MONITOR.
- 400 symbols from `symbols.txt`; show ticker-level coverage start/end, eligible sessions, signals, data failures, splits/dividends treatment, and data source/version.
- Model whole shares, $5,000 initial budget, $1,250 at every confirmed higher-box breakout, actual invested dollars, unspent cash, per-trade cash availability, commissions/fees (configurable), slippage, next-open fills, stop gaps, and stop adjustments effective only after confirmation.
- A **per-position** isolated $5,000+$1,250 budget replay is acceptable as a diagnostic, but it is **not a realistic combined-portfolio equity curve**. Portfolio-wide return/drawdown requires a specified starting account balance, capital reservation, overlapping trade handling, concentration caps, and ordering rules; these are TO APPROVE.
- Intraday order ambiguity: daily OHLC cannot reveal which level occurred first. `ambiguous_bar_count` is numeric and increases **only when actual same-bar conflicting executable events occur**. `ambiguous_exit` TRUE only if a simulated exit is affected. `exit_assumption` = STOP_FIRST only for affected bars; otherwise NOT_APPLICABLE. Opening gap-through-stop uses open (plus modeled slippage), not ideal stop price. Avoid false conflict flags on HT milestones that are not exit orders.
- Log HT1 and HT2 first-touch **dates** as milestones, not exits; record all higher-box confirmation and add-on decision dates.
- The **primary required backtest** uses fixed $5,000 initial allocation and automatic $1,250 budget at every new confirmed higher-box breakout, with no additional add-on eligibility rule. Optional research comparisons (other add-on sizes or exit models) must be separate modes and must not change the primary report. Use train/test or walk-forward for any claimed performance advantage.
- Warn that backtesting **today's** 400 tickers across five years creates selection/survivorship bias; historical point-in-time universes/delisted names are a future data requirement for credible broader claims.

## 7. BACKTEST Excel outputs — mandatory
**File:** `darvas_v6_backtest_report.xlsx`

1. **SUMMARY** — universe count, 5-year coverage, data errors, number of positions, exits/open, total invested, gross/net P/L, realized/unrealized separated, win rate, profit factor, expectancy, drawdown **only when a portfolio simulation is actually supported**, costs, strategy version.
2. **TRADE LEDGER** — one row per position: ticker/ID, initial entry date/price/shares/$, add-on count and total add-on $, cumulative invested $, total shares, weighted average cost, box count, first/last box dates, holding duration calendar days and trading sessions, active/final stop, exit date/price/reason, proceeds $, realized P/L $, realized return %, unrealized P/L if open, maximum favorable/adverse excursion where supported, full summary commentary.
3. **TRADE JOURNEY** — chronological event-level history (BUY, BOX CONFIRMED, HT1/HT2 MILESTONE, ADD CANDIDATE, ADD EXECUTED, ADD SKIPPED, STOP RAISED, HOLD, EXIT, OPEN AT END), with event dates, price, quantities, cumulative invested, running P/L, commentary.
4. **BOX HISTORY** — all boxes 1…N, detection and confirmation dates, highs/lows, breakout validation, trend and volume metrics.
5. **ADD-ON HISTORY** — each higher-box breakout, automatic $1,250 add attempt, next-open fill or operational unfilled reason, actual $ invested, whole shares, incremental and aggregate risk. No extra add-on eligibility screen in the primary backtest.
6. **STOP HISTORY** — initial and raised stops, effective dates, rationale, stop gap and same-bar ambiguity details.
7. **MILESTONES** — HT1/HT2 first-touch dates, not confused with actual exit dates.
8. **OPEN AT END** — unrealized positions, marked at last available completed close, holding days, current stop, unrealized $ P/L.
9. **RULES & AUDIT** — assumptions, parameter versions, data sources, errors, counts, ambiguity policy, exclusions and limitations.

All numeric money fields use USD and clear gross vs net labels. A zero/blank must not conflate `not applicable`, `not reached`, and `missing data`. Historical commentary must explain **why bought, why added/unfilled, why held, why stop changed, and why exited**.

## 8. MONITOR Excel outputs — mandatory
**File:** `darvas_v6_monitor_report.xlsx` — actual owned positions only.

1. **HOLDINGS DASHBOARD** — actual confirmed shares, purchase date, days held, confirmed cost basis, latest quote/as-of, unrealized P/L $, broker-confirmed stop, suggested stop, current status, required action.
2. **POSITION JOURNEY** — append-only real event timeline, including every stage/box, user-confirmed buy/add/no-add decision with actual dollars, shares and dates, proposed stops, confirmed broker stop changes, touch alerts and confirmed exits; commentary on entire operation.
3. **BOX HISTORY** — successive confirmed boxes, provisional vs confirmed distinction, dates and levels.
4. **ADD MORE REVIEW** — higher-box breakout events and optional user purchase decisions. Show **actual amount invested at each stage**, confirmed shares, fill price/date and $0 for a deliberately skipped add. No fixed $1,250 live requirement; suggestions must be clearly labeled NOT PURCHASED until confirmed.
5. **STOP REVIEW** — previous proposed stop, new proposed stop, last confirmed Schwab stop, confirmation status/date; never pretend the order was updated.
6. **ALERTS & EXCEPTIONS** — new events only, persistent RED stop touches, ORDER UNKNOWN when appropriate, stale data, missing holdings metadata, duplicate suppression.
7. **CLOSED POSITIONS** — only user-confirmed Schwab exits, actual proceeds/fees and realized dollar P/L; touched stops alone remain unverified.
8. **RULES & AUDIT** — last successful monitor, state integrity, feed timestamps, strategy version, unknowns.

- Telegram: send scan Excel after each completed scan; monitor Excel **only when a new significant event/status change occurs**. Keep dated GitHub Actions artifacts. Avoid 30-minute repeat HOLD spam.
- Persistence must survive ephemeral GitHub Actions runs. Cache alone is not guaranteed durable; require recoverable, versioned event/position state, atomic updates and duplicate suppression. Fail visibly on lost/corrupt state.
- Monitor scheduled about every 30 minutes in US regular market hours, best effort, not a substitute for broker protection.

### 8.1 Schwab stop-loss change alert and manual GitHub confirmation — APPROVED
- When a **new higher box is confirmed** and the shared stop algorithm produces a **higher suggested stop**, emit a Telegram alert titled `SCHWAB STOP UPDATE REQUIRED`. Include ticker, position ID, box number, box confirmation date, prior suggested stop, new suggested stop, last user-recorded Schwab stop, actual held shares, dollar difference per share, market-data timestamp, and plain-language reason. Do not notify merely because price rises inside an existing box.
- Show explicit manual steps: review the working Schwab sell-stop order, replace/modify it as appropriate, verify order type, quantity, stop price, time in force and working status, then update the GitHub holdings ledger. Never claim a broker order was placed or changed.
- GitHub holdings ledger stores `schwab_stop_enabled` (YES/NO/UNKNOWN), `schwab_stop_price`, `schwab_stop_status` (CONFIRMED/PENDING/NOT_ENABLED/UNKNOWN), `schwab_stop_confirmed_at`, and optional `schwab_order_id`/notes. Record `suggested_stop` separately; generated monitor runs must **never overwrite user-confirmed broker fields**. Store historical confirmations as append-only events.
- A new higher recommended stop sets the **monitor action** to PENDING, but does not falsify or erase the last confirmed Schwab order. `CONFIRMED` is accepted only with an enabled stop, a valid recorded stop price matching the user's claimed update, and an explicit confirmation timestamp; when the broker stop is lower than the newly recommended stop, retain UPDATE REQUIRED even if the older broker order is confirmed working.
- NO/NOT_ENABLED or missing working-stop confirmation triggers an urgent `NO CONFIRMED SCHWAB STOP` alert. UNKNOWN means verify manually; do not assert the order is absent. Avoid repeated identical Telegram messages; send reminders at a configurable cadence while an action remains pending, and escalate on a new box or risk event.
- For stop-touch alerts, distinguish `PRICE TOUCHED SUGGESTED STOP`, `PRICE TOUCHED USER-RECORDED BROKER STOP`, and `USER CONFIRMED EXIT`. A touched price is not proof of an executed Schwab sale. Monitoring is advisory; actual broker orders provide protection between runs.
- Acceptance scenario: confirmed Box 2 stop $205; confirmed Box 3 raises suggestion to $218 → Telegram action PENDING; user verifies $218 working in Schwab and updates GitHub ledger → next run shows CONFIRMED; Box 4 raises suggestion to $230 → action becomes PENDING again, retaining $218 as last user-recorded broker stop. All prices hypothetical.

## 8.2 Book-inspired Darvas fidelity enhancements — proposed for V6 review
These items reflect broad themes of Nicolas Darvas's box-trading approach, **not exact numeric rules claimed to be specified by the book**. Distinguish book-inspired behavior from V6 engineering choices in reports.
1. **Precise price-box mechanics:** document an unambiguous box formation, top/bottom confirmation, breakout, and higher-box transition algorithm; use only information available at each historical date. Report box formation vs confirmation vs breakout separately. Existing V5 rules should be checked against the book before labeling them historically faithful.
2. **Volume and leadership at initial entry:** report abnormal volume, strength/new highs, and market leadership as context for initial buy selection. Keep V6's agreed initial scanner filters. **Do not introduce extra filters on the mandatory $1,250 historical add-ons.** HMA38 and the 1.5× volume threshold are V6-specific settings, not Darvas-prescribed constants.
3. **Re-entry after a stopped-out trade:** allow a stock to form a fresh qualifying initial breakout later. Start a **new position ID**, new $5,000 initial budget, new stop and journey; keep the earlier realized loss in the cumulative stock history. Prevent duplicate simultaneous entries into the same position.
4. **Broader market context:** log market trend/weakness and sector relative strength at entry, each add-on, and exit for explanatory commentary. Initially **informational only**, not a new veto on the approved backtest purchases; label data unavailable where appropriate.
5. **No averaging down; no fixed profit ceiling:** add only at confirmed higher-box breakouts; never add on declining/lower boxes. HT1/HT2 and round-number gains are observations, not automatic sell instructions. No artificial final Box N.
6. **Protective-stop discipline and gaps:** establish an initial stop for every entry and keep a chronological stop ledger; ratchet the suggested stop upward after higher-box confirmation under the agreed formula, never backward. Simulate stop-market gap/slippage risk; monitor user-confirmed broker orders separately. Never assume a stop guarantees the specified exit price.
7. **Trade journal and decision audit:** retain time-stamped entry, each box, each add, hold decision, stop recommendation, actual Schwab confirmation, and final exit with reasons and cumulative dollar exposure/P&L. Commentary must not invent discretionary decisions or executions.
8. **Original-method versus modern-rule labeling:** identify $5,000/$1,250 sizing, whole-share rounding, HMA38, 52-week-high distance, fixed historical universe, and 30-minute Telegram checks as project choices rather than rules from Darvas's book.

**Unresolved for implementation:** exact higher-box confirmation/stop-ratchet algorithm; backtest market data and market-context benchmark; re-entry cooldown or duplicate handling if needed. Do not silently impose an add-on count cap or a discretionary add-on veto.

## 9. Acceptance tests before release
- 400-symbol scan and five-year backtest, including missing/new/delisted symbols and download failures; accurate data coverage counts.
- Synthetic multi-box journey: Box 1 → Box 2 → Box 3 → Box 4 → Box 5; no HT2 automatic exit; mandatory $1,250 add attempts at each higher-box breakout and explicit operational unfilled cases; stop ratchets upward only after confirmation; no lookahead.
- Exact money reconciliation: sum of individual buys = invested $, sum of remaining shares × exit price = gross proceeds $, net P/L = proceeds − invested − modeled costs; whole-share residual cash retained; win/loss and gap-stop examples verified.
- Accurate calendar/trading-session holding duration, milestone dates, terminal exit date only for actual simulated exits, OPEN AT END otherwise.
- No `stop-first assumption` blanket label. Same-bar ambiguity count and reason only on actual conflicting events; stop gaps modeled at open.
- Live holdings never implicitly traded; stop touch remains RED until user reconciliation; actual manually confirmed broker stop distinct from proposed stop; add-on alert never changes holdings without confirmation.
- GitHub-file confirmation tests: YES/CONFIRMED with matching stop resolves pending; NO/NOT_ENABLED raises urgent alert; UNKNOWN prompts verification; missing price or contradictory confirmation is rejected; lower-than-suggested confirmed stop stays PENDING; duplicate alerts suppressed; confirmed stop never auto-updated.
- Correct workbook tabs, event commentary, no duplicated Telegram events, secret handling, single scheduled workflow and reliable report artifacts. Test stop-update Telegram content, GitHub confirmation transitions, pending reminders, and re-entry as a new position ID.
- Tests pass with synthetic OHLC data and representative historical samples; then perform full GitHub 400-symbol run. Performance remains unvalidated until out-of-sample results reviewed.

## 10. GitHub deployment and migration
- Target workflow name/path: **`.github/workflows/darvas-fresh-v6.yml`**, but **rename/remove or disable** the old scheduled V5 workflow in the **same change**. Never leave two scheduled Darvas workflows active. Retain a backup/rollback path.
- Continue accepting legacy holdings format during migration; enrich dates/shares via explicit user confirmation, not guesses. Do not overwrite user's holdings.
- Do not claim this document changes deployed code. Release only after user review, implementation, tests, and manual workflow verification.

## 11. Review decisions still required
1. **Backtest cash modeling:** fixed $1,250 add attempt at every higher box is agreed, without an arbitrary add-on count cap. Decide whether this is an unconstrained per-position diagnostic (capital grows with boxes) or a cash-constrained portfolio simulation; report any unfunded attempts rather than hiding them.
2. **Total capital available:** primary per-trade diagnostic may allocate another $1,250 per box; a separate combined-portfolio cash balance and portfolio-level drawdown model requires an explicit starting account balance. If portfolio simulation, choose starting capital and overlapping-trade allocation rules.
3. **Risk disclosure:** show aggregate dollars at risk after every backtest add and after each actual monitor fill. Decide portfolio risk constraints separately; do not introduce hidden filters that override the required primary backtest add-on rule. Trailing-stop logic is shared between both modes.
4. **Exact stop ratchet:** new confirmed box low vs buffer below box low; effective timing; gaps and simultaneous event ordering.
5. **Trade costs/slippage:** default assumptions, whether split/dividend adjusted data are used, and corporate-action handling.
6. **Exit beyond stops:** whether to add discretionary/time-based/market-regime exits; otherwise mark open at test end.
7. **Data persistence:** versioned GitHub artifact/branch/database backend for reliable cross-run event history.
8. **Historical universe:** current 400-stock fixed cohort for initial diagnostic vs point-in-time membership for stronger inference.

**Clarification approved for draft:** BACKTEST = automatic fixed-budget $1,250 at every confirmed higher-box breakout; MONITOR = actual user-decided dollar amounts and quantities at each stage; same protective-stop calculation, but simulated vs broker-confirmed execution kept distinct.

**Proposed approval checkpoint:** Approve requirements and unresolved settings **before** implementing V6. No claim of actual investment performance or live brokerage integration is made here.

**Approval recorded (2026-10-18):** Manual confirmation of Schwab stop enabled/updated status through the GitHub holdings file is the chosen V6 method; no API or Telegram interactive confirmation is assumed.

## 12. Portfolio capital manager and screenshot-to-ledger workflow — agreed 2026-10-18
- User enters `starting_capital` once (example $25,000). V6 maintains a **cash-only transaction ledger**: initial cash + deposits + dividends − withdrawals − fees − confirmed buys + confirmed net sale proceeds. Market price changes **never** change cash.
- Initial example: $25,000 capital, three confirmed $5,000 buys, $15,000 invested, $10,000 cash. Subsequent prices change marked holdings value and portfolio equity but not cash. This example is **not an instruction to buy**.
- `portfolio_ledger.csv` records every **user-confirmed** buy, sell, deposit, withdrawal, dividend and fee, with unique transaction ID, execution date, ticker, quantity, price, fees, amount, and notes. Never infer a fill from an alert, stop touch or screenshot of an unfilled order.
- `portfolio_config.json` records starting capital, optional capital limit, cash reserve, maximum positions, suggested initial/add-on budgets, and cash-only mode. No margin or borrowing.
- `schwab_stop_confirmations.csv` records manually confirmed Schwab working stop status and price. Preserve the last confirmed broker stop when a higher suggested stop appears. The monitor sends Telegram `SCHWAB STOP UPDATE REQUIRED` and does **not** place or change broker orders.
- V6 computes shares, remaining cost basis, average cost, realized P/L, current marked holdings value, unrealized P/L, portfolio equity and ledger cash. Unpriced holdings prevent a complete equity calculation; do not substitute zero.
- Recommend **ADD-ON vs NEW BUY vs WAIT** using available cash, cash reserve, existing position concentration, incremental stop-risk dollars, breakout strength and opportunity quality. Missing comparable inputs require `NEEDS REVIEW` instead of an invented ranking. A stop update must be sent regardless of available cash.
- Cash is **ledger-derived**, not broker-verified. If a user uploads Schwab order-history, positions and working-orders screenshots, extract visible data, reconcile duplicates and ambiguous fills, ask for missing details, and produce updated GitHub files. User reviews before uploading. No screenshot access or automatic repo modification is assumed.
- Track timestamp of last ledger reconciliation against Schwab. Missing fees, dividends, deposits, withdrawals, corporate actions or filled orders can cause drift; alert when cash cannot be reconciled.
- Never store full account numbers, credentials, or sensitive personal data in GitHub files. Do not overwrite existing user holdings or ledger records with templates.

### 12.1 Implementation staging and release gate
- **Stage A (included in review code package):** portable CSV/JSON portfolio ledger, cost-basis and cash calculations, monitor-derived stop review, opportunity listing, Telegram stop alerts, and manually triggered GitHub workflow. Stage A is **not the full V6 multi-box backtester** and does not automatically import screenshots or rank candidates by complete risk/strength metrics.
- **Stage B (not yet implemented):** unified no-lookahead multi-box historical replay, automatic $1,250 add at each higher box, realistic gap stops, complete dollar-level exit commentary and five-year V6 Excel workbook.
- **Stage C (not yet implemented):** robust cross-run market monitoring with durable box/event history, portfolio-risk scoring, reliable data freshness and scheduled V6 workflow after disabling V5 schedule.
- Stage A workflow runs manually and retains V5 scan/backtest as **clearly labeled baselines**. Do not call baseline results V6 multi-box performance.
- Confirmed Schwab broker stop changes remain manual through the GitHub stop file. A report or Telegram alert is never proof of a broker order.

## 16. V6 backtest-first delivery and acceptance (2026-10-19)
**User priority:** Finish and inspect the five-year historical backtest before preparing V6 for real trading. V6 backtest workflow must be **manual-only**; do not enable V6 live schedules or Schwab order changes.

### Historical engine acceptance
- Run up to 400 `symbols.txt` tickers across five calendar years (data provider availability permitting); report actual coverage and ticker errors.
- Initial purchase budget $5,000 per independent simulated position, next-session open, whole shares.
- Every **unique newly confirmed higher-box close breakout** triggers an automatic $1,250-budget add-on at next-session open, with no extra volume/HMA add-on veto. Log unaffordable/unfilled add-ons. Box confirmation itself does not imply a purchase without a breakout.
- HT1/HT2 are recorded as first-touch dates and never cause exits. Continue Box 3/4/5/... indefinitely until stop exit or historical end.
- Structural stop starts at original confirmed box low; when a higher box is confirmed, raise stop to its low only if higher and below current close, effective after the confirming close. Never lower.
- Stop-market historical approximation: gap below stop -> next open, otherwise stop touch -> stop price; apply optional slippage and fees; no guarantee of actual broker fills.
- Report every simulated trade's calendar days, trading sessions, total invested, all purchases, proceeds, realized net USD P/L and return; open trades show unrealized P/L separately. Event-level commentary must show entry, box formation, add-on, stop ratchet and exit.
- The first delivery is an **isolated per-position backtest**, not a combined $25,000 account simulation. Simultaneous trades may each deploy $5,000 and repeated $1,250 adds without global cash constraints. Do not present summed per-position P/L as a realizable portfolio equity curve or compute portfolio drawdown from it.
- Document methodology limitations: present-day ticker survivorship bias, daily-bar sequencing ambiguity, approximate box detection, corporate-action adjustment limitations, data gaps, and next-open assumptions. No claim of validated live returns.
- Only after reviewing historical results should the live portfolio-capital manager, manually confirmed Schwab orders and Telegram trading monitor be prepared for activation.


## Combined-package implementation status (2026-10-19)

The combined V6 package includes two **manual-only** workflows: the five-year per-position multi-box backtest, and a Stage A portfolio/Schwab-stop review that depends on the V5 monitor. The two components are distributed together for installation convenience, but **they do not yet share a validated identical box/stop engine**. Backtesting is the user's first acceptance gate; live V6 deployment is deferred.

**Delivered for review:** $5,000 initial and $1,250 higher-box add-on budgets in independent historical trades; trade journey, stop history and dollar P/L reports; ledger-based cash/holdings accounting; manually confirmed Schwab stop status; manual Telegram portfolio alerts.

**Still required before trade-system activation:** capital-constrained $25,000 shared-portfolio historical simulation, reliable ranking of add-on versus new breakout, regression-tested identical historical/live box and stop calculations, reconciliation of Schwab screenshots and confirmed fills, and user approval of real-data results. Do not claim these are implemented.

"""Darvas V6 portfolio ledger and advisory monitor; no broker orders.

Reads manually confirmed transactions/stops and optional pre-generated V4/V5 CSVs.
No brokerage connection, live price retrieval, or actual stop-order validation.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TX_FIELDS = ['transaction_id', 'date', 'ticker', 'type', 'shares', 'price', 'fees', 'amount', 'notes']
STOP_FIELDS = ['ticker', 'enabled', 'status', 'broker_stop_price', 'confirmed_at', 'order_id', 'notes']


def number(value, name, allow_zero=True):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be numeric, got {value!r}')
    if not math.isfinite(v) or (v < 0 if allow_zero else v <= 0):
        raise ValueError(f'{name} must be finite and nonnegative' if allow_zero else f'{name} must be finite and positive')
    return v


def read_csv(path):
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def load_ledger(config, transactions):
    cash = number(config['starting_capital'], 'starting_capital')
    shares, basis, realized, history, ids = {}, {}, 0., [], set()
    for row in transactions:
        txid = (row.get('transaction_id') or '').strip()
        if not txid or txid in ids:
            raise ValueError(f'Empty or duplicate transaction_id: {txid!r}')
        ids.add(txid)
        typ = (row.get('type') or '').upper().strip()
        ticker = (row.get('ticker') or '').upper().strip()
        qty = number(row.get('shares') or 0, f'{txid} shares')
        price = number(row.get('price') or 0, f'{txid} price')
        fee = number(row.get('fees') or 0, f'{txid} fees')
        amount = number(row.get('amount') or 0, f'{txid} amount')
        if typ in ('BUY', 'SELL'):
            if not ticker or qty <= 0 or price <= 0:
                raise ValueError(f'{txid}: BUY/SELL needs ticker, positive shares and price')
            held = shares.get(ticker, 0.)
            cost = basis.get(ticker, 0.)
            if typ == 'BUY':
                debit = qty * price + fee
                if debit > cash + .011:
                    raise ValueError(f'{txid}: insufficient ledger cash for buy ${debit:.2f} > ${cash:.2f}')
                cash -= debit
                shares[ticker] = held + qty
                basis[ticker] = cost + debit
            else:
                if qty > held + 1e-8:
                    raise ValueError(f'{txid}: sale exceeds recorded holdings of {ticker}')
                allocated = cost * (qty / held)
                proceeds = qty * price - fee
                cash += proceeds
                realized += proceeds - allocated
                shares[ticker] = max(0., held - qty)
                basis[ticker] = max(0., cost - allocated)
        elif typ in ('DEPOSIT', 'WITHDRAWAL', 'DIVIDEND', 'FEE'):
            if typ in ('DEPOSIT', 'DIVIDEND'):
                cash += amount
            else:
                cash -= amount
                if cash < -.011:
                    raise ValueError(f'{txid}: insufficient cash for {typ}')
        else:
            raise ValueError(f'{txid}: invalid type {typ}')
        history.append(dict(transaction_id=txid, type=typ, ticker=ticker,
                            cash_after=round(cash, 2), realized_total=round(realized, 2)))
    return cash, shares, basis, realized, history


def monitor_prices(rows):
    result = {}
    for row in rows:
        ticker = (row.get('ticker') or '').upper().strip()
        try:
            p = number(row.get('last_price'), 'last_price', False)
        except ValueError:
            continue
        if ticker:
            result[ticker] = (p, row)
    return result


def calculate(config, transactions, monitor, stops, scan):
    cash, shares, basis, realized, history = load_ledger(config, transactions)
    quotes = monitor_prices(monitor)
    stop_by = {(r.get('ticker') or '').upper().strip(): r for r in stops}
    positions, alerts, missing, market_value = [], [], [], 0.
    for ticker, qty in sorted(shares.items()):
        if qty <= 1e-8:
            continue
        quote, obs = quotes.get(ticker, (None, {}))
        if quote is None:
            missing.append(ticker)
        else:
            market_value += qty * quote
        stop = stop_by.get(ticker, {})
        enabled = (stop.get('enabled') or 'UNKNOWN').upper().strip()
        status = (stop.get('status') or 'UNKNOWN').upper().strip()
        broker_raw = stop.get('broker_stop_price') or ''
        broker = number(broker_raw, f'{ticker} broker_stop_price', False) if broker_raw else None
        try:
            suggested = number(obs.get('recommended_stop'), 'recommended_stop', False)
        except ValueError:
            suggested = None
        if enabled not in ('YES', 'NO', 'UNKNOWN'):
            raise ValueError(f'{ticker}: enabled must be YES/NO/UNKNOWN')
        if status not in ('CONFIRMED', 'PENDING', 'NOT_ENABLED', 'UNKNOWN'):
            raise ValueError(f'{ticker}: invalid stop status')
        confirmed = enabled == 'YES' and status == 'CONFIRMED' and broker is not None and bool(stop.get('confirmed_at'))
        if enabled == 'NO' or status == 'NOT_ENABLED':
            action = 'NO CONFIRMED SCHWAB STOP'
        elif not confirmed:
            action = 'VERIFY SCHWAB STOP'
        elif suggested is not None and suggested > broker + .005:
            action = 'SCHWAB STOP UPDATE REQUIRED'
        else:
            action = 'STOP CONFIRMED'
        if action != 'STOP CONFIRMED':
            alerts.append(dict(ticker=ticker, action=action, broker_stop=broker or '',
                               suggested_stop=suggested or '', shares=round(qty, 6),
                               box_high=obs.get('box_high', ''), box_low=obs.get('box_low', ''),
                               reason=obs.get('reason', '')))
        positions.append(dict(ticker=ticker, shares=round(qty, 6), total_cost=round(basis[ticker], 2),
                              avg_cost=round(basis[ticker] / qty, 4), last_price=quote or '',
                              market_value=round(qty * quote, 2) if quote is not None else '',
                              unrealized_pl=round(qty * quote - basis[ticker], 2) if quote is not None else '',
                              broker_stop=broker or '', suggested_stop=suggested or '',
                              stop_status=status, action=action, quote_timestamp=obs.get('last_bar', '')))
    equity = cash + market_value if not missing else None
    limit = number(config.get('portfolio_capital_limit', config['starting_capital']), 'portfolio_capital_limit')
    reserve = number(config.get('minimum_cash_reserve', 0), 'minimum_cash_reserve')
    deployable = max(0, cash - reserve)
    if equity is not None and config.get('treat_limit_as_hard_equity_cap', False):
        deployable = min(deployable, max(0, limit - equity))
    candidates = []
    for r in monitor:
        ticker = (r.get('ticker') or '').upper().strip()
        if shares.get(ticker, 0) <= 0 or str(r.get('add_more', '')).lower() not in ('true', 'yes', '1'):
            continue
        candidates.append(dict(ticker=ticker, kind='ADD-ON', signal='CONFIRMED HIGHER BOX (V5 monitor)',
                               suggested_budget=number(config.get('suggested_addon_budget', 1250), 'suggested_addon_budget'),
                               price=quotes.get(ticker, (None,))[0],
                               rationale='Existing winner; review stop and position concentration before buying'))
    for r in scan:
        ticker = (r.get('ticker') or r.get('symbol') or '').upper().strip()
        signal = ' '.join(str(x) for x in (r.get('status', ''), r.get('signal', ''))).upper()
        if 'BUY' not in signal or 'CANDIDATE' not in signal or shares.get(ticker, 0) > 0:
            continue
        candidates.append(dict(ticker=ticker, kind='NEW BUY', signal='BUY CANDIDATE (V5 scan)',
                               suggested_budget=number(config.get('initial_purchase_budget', 5000), 'initial_purchase_budget'),
                               price=None, rationale='New candidate; review signal and stop before buying'))
    max_positions = int(number(config.get('maximum_positions', 5), 'maximum_positions'))
    active = sum(q > 0 for q in shares.values())
    for c in candidates:
        c['cash_status'] = 'AVAILABLE' if deployable >= c['suggested_budget'] else 'INSUFFICIENT CASH'
        if c['kind'] == 'NEW BUY' and active >= max_positions:
            c['cash_status'] = 'POSITION LIMIT'
        c['risk_status'] = 'NEEDS MANUAL REVIEW'
        c['rank'] = 'NOT RANKED: comparable stop-risk data unavailable'
    summary = dict(
        starting_capital=number(config['starting_capital'], 'starting_capital'),
        cash_from_confirmed_ledger=round(cash, 2), holdings_market_value=round(market_value, 2),
        portfolio_market_value=round(equity, 2) if equity is not None else None,
        realized_pl=round(realized, 2), minimum_cash_reserve=reserve,
        cash_after_reserve=round(deployable, 2), unpriced_holdings=missing,
        positions=active, candidate_count=len(candidates),
        last_calculated_utc=datetime.now(timezone.utc).isoformat(),
        note=('Cash is computed only from recorded transactions, not verified Schwab buying power. '
              'Reconcile with Schwab. Prices depend on externally generated monitor CSV data.'),
    )
    return summary, positions, alerts, candidates, history


def send_telegram(message):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat:
        return False
    data = urlencode({'chat_id': chat, 'text': message}).encode()
    req = Request(f'https://api.telegram.org/bot{token}/sendMessage', data=data, method='POST')
    with urlopen(req, timeout=20) as r:
        r.read()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='portfolio_config.json')
    ap.add_argument('--ledger', default='portfolio_ledger.csv')
    ap.add_argument('--stops', default='schwab_stop_confirmations.csv')
    ap.add_argument('--monitor', default='darvas_v4_monitor_results.csv')
    ap.add_argument('--scan', default='darvas_v4_scan_results.csv')
    ap.add_argument('--state', default='v6_alert_state.json')
    ap.add_argument('--outdir', default='v6_reports')
    ap.add_argument('--telegram', action='store_true')
    args = ap.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    if not Path(args.ledger).exists():
        raise FileNotFoundError(f'Ledger is missing: {args.ledger}')
    if not Path(args.stops).exists():
        raise FileNotFoundError(f'Stop confirmations are missing: {args.stops}')
    tx = read_csv(args.ledger)
    monitor = read_csv(args.monitor)
    scan = read_csv(args.scan)
    if not monitor:
        print('WARNING: No monitor prices loaded. Portfolio values may be unavailable.', flush=True)
    summary, positions, alerts, candidates, history = calculate(config, tx, monitor, read_csv(args.stops), scan)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'portfolio_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    write_csv(out / 'portfolio_positions.csv', positions, ['ticker','shares','total_cost','avg_cost','last_price','market_value','unrealized_pl','broker_stop','suggested_stop','stop_status','action','quote_timestamp'])
    write_csv(out / 'schwab_stop_actions.csv', alerts, ['ticker','action','broker_stop','suggested_stop','shares','box_high','box_low','reason'])
    write_csv(out / 'portfolio_opportunities.csv', candidates, ['ticker','kind','signal','suggested_budget','price','cash_status','risk_status','rank','rationale'])
    write_csv(out / 'cash_journey.csv', history, ['transaction_id','type','ticker','cash_after','realized_total'])
    old = {}
    if Path(args.state).exists():
        old = json.loads(Path(args.state).read_text(encoding='utf-8'))
    current = {a['ticker']: hashlib.sha256(json.dumps(a, sort_keys=True).encode()).hexdigest() for a in alerts}
    new = [a for a in alerts if old.get(a['ticker']) != current[a['ticker']]]
    if args.telegram:
        for a in new:
            try:
                send_telegram(f"DARVAS V6: {a['action']}\nStock: {a['ticker']}\nShares: {a['shares']}\nRecorded Schwab stop: {a['broker_stop'] or 'UNKNOWN'}\nSuggested stop: {a['suggested_stop'] or 'UNKNOWN'}\nCheck your working Schwab order manually. NO ORDER WAS PLACED.")
            except Exception as exc:
                print(f'WARNING: Telegram notification failed for {a["ticker"]}: {exc}', flush=True)
                # Do not mark the alert as delivered if the send failed.
                current.pop(a['ticker'], None)
    Path(args.state).write_text(json.dumps(current, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
    print(f'Pending stop actions: {len(alerts)}, new since saved state: {len(new)}; candidate opportunities: {len(candidates)}')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Independent Darvas diagnostic scanner; not an exact clone of DarvasTracker."""
import argparse
import logging
from pathlib import Path
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

LOG = logging.getLogger('darvas')
FIELDS = ['ticker','date','status','reason','close','box_high','box_low','box_age','volume_ratio','hma38','hma38_prev','breakout','volume_pass','hma_pass','ht1','ht2','stop','bars']


def wma(s, length):
    weights = np.arange(1, length + 1, dtype=float)
    return s.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def hma(s, length=38):
    return wma(2 * wma(s, length // 2) - wma(s, length), int(np.sqrt(length)))


def load_symbols(path):
    values = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        sym = line.strip().split('#', 1)[0].strip().upper()
        if sym and sym not in values:
            values.append(sym)
    return values


def confirmed_box(history, idx, min_age=3):
    """Conservative diagnostic approximation: latest confirmed pivot high/low before breakout.

    A pivot at i is confirmed only if the NEXT TWO completed bars do not exceed
    its high (or undercut its low). Current breakout bar is never used for pivots.
    """
    highs = history['High'].to_numpy(dtype=float)
    lows = history['Low'].to_numpy(dtype=float)
    # idx is the candidate breakout bar; pivot confirmation ends before idx.
    highs_p = [j for j in range(2, idx - 2) if highs[j] > max(highs[j-2:j]) and highs[j] >= max(highs[j+1:j+3])]
    lows_p = [j for j in range(2, idx - 2) if lows[j] < min(lows[j-2:j]) and lows[j] <= min(lows[j+1:j+3])]
    if not highs_p or not lows_p:
        return None
    # Latest confirmed pivot high; low must come from after prior pivot high
    # or preceding the latest high within a reasonable window.
    hi = highs_p[-1]
    valid_lows = [j for j in lows_p if hi - 50 <= j <= idx - 3]
    if not valid_lows:
        return None
    low = valid_lows[-1]
    age = idx - max(hi, low)
    if age < min_age or lows[low] >= highs[hi]:
        return None
    return float(highs[hi]), float(lows[low]), age


def evaluate(df, ticker, idx):
    bar = df.iloc[idx]
    prev = df.iloc[:idx]
    close = float(bar['Close'])
    avg_vol = float(prev['Volume'].tail(20).mean())
    ratio = float(bar['Volume']) / avg_vol if avg_vol > 0 else np.nan
    curr_hma = float(bar['HMA38'])
    prev_hma = float(df.iloc[idx-1]['HMA38'])
    vol_pass = bool(np.isfinite(ratio) and ratio >= 1.5)
    hma_pass = bool(np.isfinite(curr_hma) and np.isfinite(prev_hma) and curr_hma >= prev_hma)
    box = confirmed_box(df, idx)
    row = dict(ticker=ticker, date=str(df.index[idx].date()), close=close,
               box_high=np.nan, box_low=np.nan, box_age=np.nan,
               volume_ratio=ratio, hma38=curr_hma, hma38_prev=prev_hma,
               breakout=False, volume_pass=vol_pass, hma_pass=hma_pass,
               ht1=np.nan, ht2=np.nan, stop=np.nan, bars=len(df))
    reasons = []
    if box is None:
        reasons.append('NO_CONFIRMED_BOX')
    else:
        high, low, age = box
        row.update(box_high=high, box_low=low, box_age=age, breakout=close > high,
                   ht1=high + (high - low), ht2=high + 2*(high-low), stop=low)
        if not row['breakout']:
            reasons.append('NO_CLOSE_BREAKOUT')
    if not vol_pass:
        reasons.append('LOW_VOLUME' if np.isfinite(ratio) else 'NO_VOLUME_DATA')
    if not hma_pass:
        reasons.append('HMA38_DOWN_OR_UNAVAILABLE')
    row['status'] = 'QUALIFIED' if not reasons else 'REJECTED'
    row['reason'] = 'PASS' if not reasons else ';'.join(reasons)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbols', default='symbols.txt')
    parser.add_argument('--days', type=int, choices=[1,5,10], default=5,
                        help='Number of latest completed sessions to inspect')
    parser.add_argument('--period', default='1y', choices=['6mo','1y','2y'])
    parser.add_argument('--outdir', default='results')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    symbols = load_symbols(args.symbols)
    if not symbols:
        raise SystemExit('symbols.txt contains no tickers')
    LOG.info('Loaded %d unique tickers; inspecting last %d completed trading sessions', len(symbols), args.days)
    results = []
    today_ny = datetime.now(ZoneInfo('America/New_York'))
    for num, ticker in enumerate(symbols, 1):
        LOG.info('[%d/%d] %s: downloading daily OHLCV...', num, len(symbols), ticker)
        try:
            df = yf.download(ticker, period=args.period, interval='1d', auto_adjust=False,
                             progress=False, threads=False, multi_level_index=False, timeout=20)
            if df is None or df.empty:
                raise ValueError('Empty price history returned')
            df = df[['Open','High','Low','Close','Volume']].copy()
            df.index = pd.to_datetime(df.index)
            if df.index.tz is not None:
                df.index = df.index.tz_convert('America/New_York').tz_localize(None)
            df = df.dropna(subset=['Open','High','Low','Close','Volume']).sort_index()
            # Exclude today's candle until US regular session is complete.
            if len(df) and df.index[-1].date() == today_ny.date() and (
                today_ny.hour < 16 or (today_ny.hour == 16 and today_ny.minute < 15)
            ):
                df = df.iloc[:-1]
            if len(df) < 80:
                raise ValueError(f'Insufficient completed bars: {len(df)} (need >=80)')
            df['HMA38'] = hma(df['Close'], 38)
            for idx in range(len(df)-min(args.days,len(df)-60), len(df)):
                row = evaluate(df, ticker, idx)
                results.append(row)
                LOG.info('  %s | close=%.2f box=%s vol=%s HMA=%s | %s: %s',
                         row['date'], row['close'],
                         f"{row['box_high']:.2f}" if np.isfinite(row['box_high']) else 'N/A',
                         f"{row['volume_ratio']:.2f}x" if np.isfinite(row['volume_ratio']) else 'N/A',
                         'UP/FLAT' if row['hma_pass'] else 'DOWN/N/A',
                         row['status'], row['reason'])
        except Exception as exc:
            LOG.warning('[%d/%d] %s DATA ERROR: %s', num, len(symbols), ticker, exc)
            results.append(dict(ticker=ticker, date='', status='DATA_ERROR', reason=str(exc)))
    all_rows = pd.DataFrame(results).reindex(columns=FIELDS)
    qualified = all_rows[all_rows['status'] == 'QUALIFIED'].copy()
    all_rows.to_csv(outdir/'darvas_diagnostics.csv', index=False)
    qualified.to_csv(outdir/'darvas_qualified.csv', index=False)
    counts = Counter(all_rows['status'])
    LOG.info('SUMMARY: tickers=%d rows=%d qualified=%d rejected=%d data_errors=%d',
             len(symbols), len(all_rows), counts['QUALIFIED'], counts['REJECTED'], counts['DATA_ERROR'])
    LOG.info('Saved %s and %s', outdir/'darvas_diagnostics.csv', outdir/'darvas_qualified.csv')
    if counts['DATA_ERROR'] == len(symbols):
        raise SystemExit('All ticker downloads failed; see diagnostic CSV')

if __name__ == '__main__':
    main()

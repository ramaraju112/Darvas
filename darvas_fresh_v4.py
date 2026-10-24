"""Independent implementation of DarvasTracker's publicly documented daily rules.
No brokerage connectivity. Research only. Python 3.10+.
"""
import argparse, csv, io, os, sys, time
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
import numpy as np


def wma(s, n):
    weights=np.arange(1,n+1,dtype=float)
    return s.rolling(n).apply(lambda x: np.dot(x,weights)/weights.sum(),raw=True)

def hma(s,n=38):
    return wma(2*wma(s,n//2)-wma(s,n),round(np.sqrt(n)))

@dataclass
class Signal:
    ticker:str; date:str; close:float; box_high:float; box_low:float; age:int; volume_ratio:float; hma38:float; ht1:float; ht2:float
    @property
    def stop(self): return self.box_low
    @property
    def risk_pct(self): return 100*(self.close-self.stop)/self.close
    def asdict(self):
        return {'ticker':self.ticker,'date':self.date,'breakout_close':round(self.close,4),'box_high':round(self.box_high,4),'box_low':round(self.box_low,4),'box_age':self.age,'volume_ratio':round(self.volume_ratio,3),'hma38':round(self.hma38,4),'ht1':round(self.ht1,4),'ht2':round(self.ht2,4),'stop':round(self.stop,4),'risk_pct':round(self.risk_pct,2)}

def normalize(df, preserve_tz=False):
    d=df.copy()
    if isinstance(d.columns,pd.MultiIndex): d.columns=d.columns.get_level_values(0)
    d.columns=[str(c).title() for c in d.columns]
    required=['Open','High','Low','Close','Volume']
    if any(c not in d for c in required): raise ValueError('OHLCV columns missing')
    d=d[required].apply(pd.to_numeric,errors='coerce').dropna()
    d=d[(d.High>=d.Low)&(d.Volume>=0)]
    d.index=pd.to_datetime(d.index)
    if not preserve_tz and d.index.tz is not None: d.index=d.index.tz_localize(None)
    return d.sort_index().loc[~d.index.duplicated(keep='last')]

def find_signals(df,ticker='TEST'):
    """Two-session top and bottom confirmations; minimum age 3; close breakout; 1.5x previous 20-day volume; HMA38 nondeclining.
    A candidate high is invalidated if a higher high occurs before a completed box breaks out.
    This is a documented-rule interpretation, not a byte-for-byte copy of proprietary site logic.
    """
    d=normalize(df)
    if len(d)<55:return []
    H=d.High.to_numpy(); L=d.Low.to_numpy(); C=d.Close.to_numpy(); V=d.Volume.to_numpy()
    ma=hma(d.Close,38).to_numpy(); signals=[]
    # Use a fresh box after each breakout; never reuse a broken box.
    search_start=0
    for i in range(54,len(d)):
        if not (np.isfinite(ma[i]) and np.isfinite(ma[i-1]) and ma[i]>=ma[i-1]):continue
        prevvol=V[i-20:i].mean()
        if prevvol<=0 or V[i]<1.5*prevvol:continue
        candidate=None
        # Identify the latest fully confirmed box available BEFORE breakout day.
        for top in range(max(search_start,i-120),i-4):
            if not (H[top+1]<=H[top] and H[top+2]<=H[top]):continue
            # No higher high before breakout (otherwise this top was superseded).
            if np.any(H[top+1:i]>H[top]):continue
            for bottom in range(top+2,i-2):
                if not (L[bottom+1]>=L[bottom] and L[bottom+2]>=L[bottom]):continue
                if np.any(L[bottom+1:i]<L[bottom]):continue
                if L[bottom]>=H[top]:continue
                age=i-top-1
                if age<3:continue
                # Keep most recently formed candidate (then prefer most recent bottom).
                if candidate is None: candidate=(top,bottom,H[top],L[bottom],age)
        if candidate is None:continue
        top,bottom,bh,bl,age=candidate
        if C[i]<=bh:continue
        width=bh-bl
        signals.append(Signal(ticker,str(d.index[i].date()),float(C[i]),float(bh),float(bl),int(age),float(V[i]/prevvol),float(ma[i]),float(bh+width),float(bh+2*width)))
        search_start=i+1
    return signals

def replay(df, signal, max_days=60):
    """Audit-friendly DAILY OHLC observation replay, not a brokerage execution model.

    If a bar spans both stop and target, count it and conservatively assume stop first.
    The label is emitted ONLY on an actual conflicting bar. Opening gaps are
    distinguished from intraday touches. HT1 is a milestone, not an exit order.
    """
    d = normalize(df)
    loc = np.where(d.index.strftime('%Y-%m-%d') == signal.date)[0]
    result = {
        'outcome': 'NO_NEXT_SESSION', 'entry_open': None,
        'ht1_touched': False, 'ht2_touched': False, 'days': 0,
        'ambiguous_bar_count': 0, 'ambiguous_exit': False,
        'exit_assumption': 'NOT_APPLICABLE', 'simulated_exit_reason': 'NOT_SIMULATED',
        'exit_date': '', 'exit_price_assumption': None,
        'ambiguous_daily_bars': 'NONE',
    }
    if len(loc) == 0 or loc[0] + 1 >= len(d):
        return result
    start = int(loc[0] + 1)
    entry = float(d.Open.iloc[start]); result['entry_open'] = round(entry, 4)
    if entry >= signal.ht2:
        result['outcome'] = 'GAP_ABOVE_HT2'
        result['simulated_exit_reason'] = 'NO_ENTRY_GAP_ABOVE_HT2'
        return result
    if entry <= signal.stop:
        result['outcome'] = 'GAP_BELOW_STOP'
        result['simulated_exit_reason'] = 'NO_ENTRY_GAP_BELOW_STOP'
        return result
    for j in range(start, min(len(d), start + max_days)):
        op = float(d.Open.iloc[j]); hi = float(d.High.iloc[j]); lo = float(d.Low.iloc[j])
        result['days'] += 1
        day = str(d.index[j].date())
        # At the open, chronology is known; a gap through the stop is not a
        # same-bar ambiguity. For an open position, use the opening price.
        if j > start and op <= signal.stop:
            result.update(outcome='SL', simulated_exit_reason='STOP_GAP',
                          exit_date=day, exit_price_assumption=round(op,4))
            break
        if j > start and op >= signal.ht2:
            result.update(outcome='HT2', ht1_touched=True, ht2_touched=True,
                          simulated_exit_reason='HT2_OPEN_GAP', exit_date=day,
                          exit_price_assumption=round(op,4))
            break
        stop_hit = lo <= signal.stop
        ht1_hit = hi >= signal.ht1
        ht2_hit = hi >= signal.ht2
        if stop_hit and (ht1_hit or ht2_hit):
            result['ambiguous_bar_count'] += 1
            result.update(ambiguous_exit=True, exit_assumption='STOP_FIRST',
                          ambiguous_daily_bars='STOP_AND_TARGET_SAME_BAR',
                          outcome='SL', simulated_exit_reason='STOP_FIRST_AMBIGUOUS',
                          exit_date=day, exit_price_assumption=round(float(signal.stop),4))
            # Do not mark targets touched as realized milestones on a stop-first bar.
            break
        if stop_hit:
            result.update(outcome='SL', simulated_exit_reason='STOP_INTRADAY',
                          exit_date=day, exit_price_assumption=round(float(signal.stop),4))
            break
        if ht1_hit:
            result['ht1_touched'] = True
            result['outcome'] = 'HT1'
        if ht2_hit:
            result.update(outcome='HT2', ht1_touched=True, ht2_touched=True,
                          simulated_exit_reason='HT2_OBSERVATION', exit_date=day,
                          exit_price_assumption=round(float(signal.ht2),4))
            break
    if result['outcome'] == 'OPEN':
        result['simulated_exit_reason'] = 'OPEN_END_OF_WINDOW'
    elif result['outcome'] == 'HT1':
        result['simulated_exit_reason'] = 'HT1_MILESTONE_ONLY'
    return result

def download(ticker,period='2y'):
    import yfinance as yf
    d=yf.Ticker(ticker).history(period=period,interval='1d',auto_adjust=False)
    if d.empty:raise ValueError(f'No Yahoo data for {ticker}')
    # yfinance can include today's unfinished daily candle: exclude until after 16:15 ET.
    now=pd.Timestamp.now(tz='America/New_York')
    dates=pd.to_datetime(d.index).date
    if now.weekday()<5 and (now.hour<16 or (now.hour==16 and now.minute<15)):
        d=d.loc[dates<now.date()]
    return normalize(d)

def telegram(message):
    import requests
    token=os.getenv('TELEGRAM_BOT_TOKEN');chat=os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat:raise RuntimeError('Telegram secrets missing')
    r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage',data={'chat_id':chat,'text':message[:4000]},timeout=20)
    r.raise_for_status()

def scan_with_diagnostics(symbols, args):
    """Scan completed bars with transparent reasons; keep original backtest unchanged.

    This uses the separate diagnostic pivot-box algorithm. It is NOT an exact
    reproduction of DarvasTracker's proprietary box construction.
    """
    from darvas_fresh_v4_helper import evaluate, hma as diagnostic_hma
    import yfinance as yf

    output_dir = Path(args.outdir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    errors = []
    for number, ticker in enumerate(symbols, 1):
        print(f"[{number}/{len(symbols)}] {ticker} downloading...", flush=True)
        try:
            if args.csv_dir:
                df = normalize(pd.read_csv(Path(args.csv_dir) / f"{ticker}.csv", index_col=0, parse_dates=True))
            else:
                df = download(ticker, args.period)
            if len(df) < 80:
                raise ValueError(f"Only {len(df)} bars (need at least 80)")
            df['HMA38'] = diagnostic_hma(df['Close'], 38)
            start_idx = max(60, len(df) - args.days)
            for idx in range(start_idx, len(df)):
                row = evaluate(df, ticker, idx)
                high = row['box_high']
                prev_close = float(df['Close'].iloc[idx - 1])
                # Compare with the SAME pre-breakout box high, not a later box.
                fresh = bool(np.isfinite(high) and prev_close <= high and row['close'] > high)
                row['previous_close'] = prev_close
                row['fresh_cross'] = fresh
                if row['status'] == 'QUALIFIED' and not fresh:
                    row['status'] = 'REJECTED'
                    row['reason'] = 'ALREADY_ABOVE_BOX_HIGH'
                rows.append(row)
                print(f"  {row['date']} close={row['close']:.2f} "
                      f"box={high:.2f} " if np.isfinite(high) else
                      f"  {row['date']} close={row['close']:.2f} box=N/A ", end='', flush=True)
                print(f"volume={row['volume_ratio']:.2f}x "
                      f"hma={'PASS' if row['hma_pass'] else 'FAIL'} "
                      f"fresh={'YES' if fresh else 'NO'} "
                      f"{row['status']}: {row['reason']}", flush=True)
        except Exception as exc:
            errors.append(f'{ticker}: {exc}')
            rows.append({'ticker': ticker, 'date': '', 'status': 'DATA_ERROR', 'reason': str(exc)})
            print(f"  DATA_ERROR: {exc}", flush=True)

    all_rows = pd.DataFrame(rows)
    # Guarantee meaningful CSV headers even for zero results.
    columns = ['ticker','date','status','reason','close','previous_close',
               'box_high','box_low','box_age','volume_ratio','hma38','hma38_prev',
               'breakout','fresh_cross','volume_pass','hma_pass','ht1','ht2','stop','bars']
    all_rows = all_rows.reindex(columns=columns)
    qualified = all_rows[all_rows.status == 'QUALIFIED'].copy()
    all_rows.to_csv(output_dir / 'darvas_v4_scan_diagnostics.csv', index=False)
    qualified.to_csv(output_dir / 'darvas_v4_scan_qualified.csv', index=False)
    qualified.to_csv(args.output, index=False)
    print(f"SUMMARY: {len(symbols)} tickers, {len(all_rows)} checks, "
          f"{len(qualified)} FRESH qualifying signals, {len(errors)} ticker errors", flush=True)
    print(f"Reports: {output_dir}/darvas_v4_scan_diagnostics.csv and darvas_v4_scan_qualified.csv", flush=True)
    if args.send_telegram:
        lines = [f"Darvas scan: {len(qualified)} fresh breakouts in last {args.days} sessions"]
        for _, row in qualified.head(15).iterrows():
            lines.append(f"{row.ticker} {row.date} close ${row.close:.2f} HT1 ${row.ht1:.2f} HT2 ${row.ht2:.2f} SL ${row.stop:.2f}")
        telegram('\n'.join(lines))
    if errors:
        print('Data errors: ' + '; '.join(errors[:10]), file=sys.stderr)
        # Partial data errors are visible in CSV and logs; fail only if all symbols failed.
        if len(errors) == len(symbols):
            sys.exit(1)




def load_monitor_file(path):
    """One ticker per row; optional CSV ticker,entry,stop,ht1,ht2.
    A header is allowed. Blank optional numbers are unknown, not inferred.
    """
    positions = []
    seen = set()
    with open(path, encoding='utf-8-sig', newline='') as handle:
        for number, raw in enumerate(handle, 1):
            raw = raw.split('#', 1)[0].strip()
            if not raw: continue
            fields = [x.strip() for x in next(csv.reader([raw]))]
            if fields[0].lower() in ('ticker', 'symbol'): continue
            if len(fields) > 5: raise ValueError(f'Line {number}: use ticker,entry,stop,ht1,ht2')
            ticker = fields[0].upper()
            if not ticker or ticker in seen: continue
            seen.add(ticker)
            values = {}
            for key, value in zip(('entry','stop','ht1','ht2'), fields[1:]):
                if value:
                    number_value = float(value)
                    if not np.isfinite(number_value) or number_value <= 0:
                        raise ValueError(f'Line {number}: {key} must be positive')
                    values[key] = number_value
            positions.append((ticker, values))
    return positions


def monitor_positions(args):
    """Observe 5-minute bars; alert on threshold touches, not broker fills."""
    import json
    from datetime import datetime, timezone
    positions = load_monitor_file(args.monitor_file)
    if not positions: raise SystemExit(f'No positions in {args.monitor_file}')
    state_path = Path(args.state_file)
    try: state = json.loads(state_path.read_text()) if state_path.exists() else {}
    except (ValueError, OSError): state = {}
    if not isinstance(state,dict): state={}
    events=[]; rows=[]; errors=0
    from darvas_v5_multibox import assess
    for ticker, levels in positions:
        now=datetime.now(timezone.utc).isoformat()
        try:
            if args.csv_dir:
                intraday=normalize(pd.read_csv(Path(args.csv_dir)/f'{ticker}.csv',index_col=0,parse_dates=True),preserve_tz=True)
                daily=intraday
            else:
                import yfinance as yf
                intraday=normalize(yf.Ticker(ticker).history(period='5d',interval='5m',auto_adjust=False),preserve_tz=True)
                daily=normalize(yf.Ticker(ticker).history(period='6mo',interval='1d',auto_adjust=False))
            if intraday.empty: raise ValueError('No intraday market data')
            # Exclude unfinished daily candle before assessing new boxes.
            if not args.csv_dir:
                daily=normalize(daily)
                etnow=pd.Timestamp.now(tz='America/New_York')
                if len(daily) and daily.index[-1].date()==etnow.date() and (etnow.hour<16 or (etnow.hour==16 and etnow.minute<15)):
                    daily=daily.iloc[:-1]
            if daily.empty: raise ValueError('No daily history')
            # Filter regular session only, then inspect bars since previous successful observation.
            ix=pd.DatetimeIndex(intraday.index)
            if ix.tz is not None:
                et=ix.tz_convert('America/New_York')
                mask=(et.dayofweek<5)&((et.hour>9)|((et.hour==9)&(et.minute>=30)))&(et.hour<16)
                intraday=intraday.loc[mask]
            if intraday.empty: raise ValueError('No regular-session bars')
            latest=intraday.iloc[-1]; last_ts=pd.Timestamp(intraday.index[-1]); price=float(latest.Close)
            # Reject old quotes, particularly weekends and API outages.
            utc_ts=last_ts.tz_convert('UTC') if last_ts.tzinfo else last_ts.tz_localize('UTC')
            age_min=(pd.Timestamp.now(tz='UTC')-utc_ts).total_seconds()/60
            if age_min>args.max_quote_age_minutes and not args.allow_stale:
                raise ValueError(f'STALE_DATA: newest bar is {age_min:.0f} minutes old')
            prior=state.get(ticker,{})
            if prior.get('entry')!=levels.get('entry') or prior.get('stop')!=levels.get('stop') or prior.get('ht1')!=levels.get('ht1') or prior.get('ht2')!=levels.get('ht2'):
                prior={'multibox':prior.get('multibox',{})}
            since=prior.get('last_bar')
            fresh=intraday.loc[intraday.index>pd.Timestamp(since)] if since else intraday.tail(1)
            # If a stop was hit before the monitor began, previous bars cannot establish a confirmed fill.
            triggered=[]
            for event,field,comparison in [('STOP_PRICE_REACHED','stop','low'),('HT1_PRICE_REACHED','ht1','high'),('HT2_PRICE_REACHED','ht2','high')]:
                level=levels.get(field)
                if level is None or fresh.empty: continue
                observed=float(fresh.Low.min() if comparison=='low' else fresh.High.max())
                if (observed<=level if comparison=='low' else observed>=level):
                    triggered.append(event)
            # New confirmed higher boxes and add-on opportunities; never modify broker stop.
            mb_state,mb,mb_events=assess(daily,prior.get('multibox',{}),levels.get('stop'))
            for e in mb_events:
                triggered.append(f"{e}@{mb_state.get('accepted_box_high')}:{mb_state.get('accepted_box_low')}")
            # Persist stop status across price recoveries and repeated scheduled runs.
            seen=set(prior.get('events',[])); novel=[e for e in triggered if e not in seen]
            seen.update(triggered)
            stop_hit='STOP_PRICE_REACHED' in seen
            status='RED_STOP_RECONCILE' if stop_hit else ('TARGET_ALERT' if any(x in seen for x in ('HT1_PRICE_REACHED','HT2_PRICE_REACHED')) else 'OPEN_WATCH')
            from darvas_fresh_v4_helper import hma
            hv=hma(daily.Close,38)
            h_down=bool(len(hv)>1 and pd.notna(hv.iloc[-1]) and pd.notna(hv.iloc[-2]) and hv.iloc[-1]<hv.iloc[-2])
            if h_down and 'HMA38_FALLING' not in seen:
                novel.append('HMA38_FALLING');seen.add('HMA38_FALLING')
            if len(fresh)>0 and levels.get('stop') is not None and levels.get('ht1') is not None and 'STOP_PRICE_REACHED' in triggered and 'HT1_PRICE_REACHED' in triggered:
                novel.append('AMBIGUOUS_STOP_AND_TARGET_SAME_WINDOW')
            for event in novel:
                events.append({'observed_at_utc':now,'ticker':ticker,'event':event,'observed_price':round(price,4),'stop':levels.get('stop',''),'ht1':levels.get('ht1',''),'ht2':levels.get('ht2',''),'note':'Observed market data only; verify orders in Schwab'})
            state[ticker]={'entry':levels.get('entry'),'stop':levels.get('stop'),'ht1':levels.get('ht1'),'ht2':levels.get('ht2'),'events':sorted(seen),'last_bar':str(last_ts),'multibox':mb_state}
            rows.append({'ticker':ticker,'observed_at_utc':now,'last_bar':str(last_ts),'last_price':round(price,4),'entry':levels.get('entry',''),'stop':levels.get('stop',''),'ht1':levels.get('ht1',''),'ht2':levels.get('ht2',''),'status':status,'color':'RED' if stop_hit else ('GREEN' if status=='TARGET_ALERT' else 'NEUTRAL'),'events_seen':';'.join(sorted(seen)),'new_alerts':';'.join(novel),'hma38_falling':h_down,**mb,'note':'NOT A BROKER FILL CONFIRMATION; RECOMMENDED STOP IS NOT SCHWAB STOP'})
            print(f'{ticker}: {status}, price={price:.2f}, new={novel}',flush=True)
        except Exception as exc:
            errors+=1
            rows.append({'ticker':ticker,'observed_at_utc':now,'status':'DATA_ERROR','color':'RED','note':str(exc)})
            print(f'{ticker}: DATA_ERROR {exc}',flush=True)
    Path(args.outdir).mkdir(parents=True,exist_ok=True)
    pd.DataFrame(rows,columns=['ticker','observed_at_utc','last_bar','last_price','entry','stop','ht1','ht2','status','color','events_seen','new_alerts','hma38_falling','box_high','box_low','box_age','volume_ratio','hma38_rising','higher_box_confirmed','add_more','recommended_stop','broker_stop_confirmed','stop_review','reason','note']).to_csv(args.output,index=False)
    event_columns=['observed_at_utc','ticker','event','observed_price','stop','ht1','ht2','note']
    # Append only newly detected events; preserve history when persistent state directory restored.
    log=Path(args.events_file);log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('a',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=event_columns)
        if log.stat().st_size==0:writer.writeheader()
        writer.writerows(events)
    state_path.parent.mkdir(parents=True,exist_ok=True)
    tmp=state_path.with_suffix('.tmp');tmp.write_text(json.dumps(state,indent=2));tmp.replace(state_path)
    if args.send_telegram and events:
        lines=['Darvas V4 NEW MONITOR ALERTS (not broker fills)']
        for e in events[:30]:
            prefix='🔴' if 'STOP' in e['event'] else ('🟢' if 'HT' in e['event'] else '⚠️')
            lines.append(f"{prefix} {e['ticker']} {e['event']} price ${e['observed_price']}")
        telegram('\n'.join(lines))
    print(f'MONITOR: {len(positions)} positions; {len(events)} new events; {errors} errors; {args.output}',flush=True)
    if errors==len(positions): raise SystemExit('All monitored symbols failed')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mode',choices=['scan','backtest','monitor'],default='scan')
    p.add_argument('--symbols',default='symbols.txt')
    p.add_argument('--monitor-file',default='existing_dar_stocks.txt',help='Ticker per line, optionally ticker,entry,stop,ht1,ht2')
    p.add_argument('--period',default='5y',help='Historical backtest lookback; default five years')
    p.add_argument('--csv-dir',default='')
    p.add_argument('--send-telegram',action='store_true')
    p.add_argument('--output',default='',help='Optional override; otherwise separate output filename per mode')
    p.add_argument('--max-days',type=int,default=60)
    p.add_argument('--days',type=int,choices=[1,5,10],default=5,
                   help='Completed trading sessions checked in scan mode')
    p.add_argument('--outdir',default='darvas_v4_reports')
    p.add_argument('--state-file',default='darvas_v4_state/monitor_state.json')
    p.add_argument('--events-file',default='darvas_v4_state/monitor_events.csv')
    p.add_argument('--max-quote-age-minutes',type=int,default=45)
    p.add_argument('--allow-stale',action='store_true',help='Offline testing only')
    a=p.parse_args()
    if not a.output:
        a.output = {'scan':'darvas_v4_scan_results.csv','backtest':'darvas_v4_backtest_results.csv','monitor':'darvas_v4_monitor_results.csv'}[a.mode]
    if a.mode == 'monitor':
        monitor_positions(a)
        return
    symbols=[]
    for line in Path(a.symbols).read_text(encoding='utf-8').splitlines():
        ticker=line.split('#',1)[0].strip().upper()
        if ticker and ticker not in symbols:
            symbols.append(ticker)
    if not symbols:
        raise SystemExit('No tickers in symbols file')
    if a.mode == 'scan':
        scan_with_diagnostics(symbols,a)
        return

    # Keep the original historical signal/replay logic for backtest mode.
    rows=[];errors=[]
    for ticker in symbols:
        try:
            path=Path(a.csv_dir)/f'{ticker}.csv' if a.csv_dir else None
            d=pd.read_csv(path,index_col=0,parse_dates=True) if path else download(ticker,a.period)
            for sig in find_signals(d,ticker):
                row=sig.asdict();row.update(replay(d,sig,a.max_days));rows.append(row)
        except Exception as exc:
            errors.append(f'{ticker}: {exc}')
    if rows:
        with open(a.output,'w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for row in rows for k in row)));writer.writeheader();writer.writerows(rows)
    else:
        pd.DataFrame(columns=['ticker','date','breakout_close','box_high','box_low','ht1','ht2','stop','outcome','entry_open','days']).to_csv(a.output,index=False)
    print(f'Darvas fresh backtest: {len(rows)} signals, {len(errors)} errors')
    for row in rows[:15]:
        print(f"{row['ticker']} {row['date']} close ${row['breakout_close']} "
              f"HT1 ${row['ht1']} HT2 ${row['ht2']} SL ${row['stop']} "
              f"outcome {row['outcome']}")
    if errors:
        print('Errors: '+'; '.join(errors[:10]),file=sys.stderr)
        sys.exit(1)

if __name__=='__main__': main()

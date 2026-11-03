#!/usr/bin/env python3
"""Darvas V6.2 independent research scanner. No trading/order execution."""
import argparse, csv, io, json, math, os, re, time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

CT = ZoneInfo('America/Chicago')
HEADERS = ['Ticker','Category','Status','Price','Box High','Box Low','Box Confirmed','Distance to Box High %','52W High','Distance to 52W High %','Volume Ratio','Volume Basis','HMA38 Rising','Stop Risk %','Score','Decision','Data As Of CT','Notes']

def read_symbols(path):
    p=Path(path)
    if not p.exists(): return []
    return list(dict.fromkeys(x.strip().upper().replace('.','-') for x in p.read_text().splitlines() if x.strip() and not x.startswith('#')))

def listing(url, market):
    try:
        r=requests.get(url,timeout=25,headers={'User-Agent':'Mozilla/5.0 Darvas research scanner'});r.raise_for_status()
        lines=[s for s in r.text.splitlines() if '|' in s and not s.startswith('File Creation Time')]
        rows=list(csv.DictReader(io.StringIO('\n'.join(lines)),delimiter='|'))
        out=[]
        for row in rows:
            sym=(row.get('Symbol') or row.get('ACT Symbol') or '').strip()
            if not sym or not re.fullmatch(r'[A-Z]{1,5}(?:[.-][A-Z]{1,2})?',sym):continue
            if row.get('ETF','N')=='Y' or row.get('Test Issue','N')=='Y':continue
            name=(row.get('Security Name') or '').lower()
            if any(t in name for t in ['warrant',' preferred',' depositary','depositary share','unit ',' units','right to','etf','exchange traded fund','etn','trust units']):continue
            out.append(sym.replace('.','-'))
        return out
    except Exception as e:
        print(f'WARNING listing {market}: {e}',flush=True);return []

def download(tickers,period='1y',interval='1d',chunk=60):
    results={}; errors={}
    for offset in range(0,len(tickers),chunk):
        group=tickers[offset:offset+chunk]
        for attempt in range(2):
            try:
                data=yf.download(group,period=period,interval=interval,group_by='ticker',auto_adjust=True,progress=False,threads=True,timeout=30)
                if data is None or data.empty:raise ValueError('Empty Yahoo response')
                for t in group:
                    try:
                        f=data[t].copy() if isinstance(data.columns,pd.MultiIndex) else data.copy()
                        f=f.dropna(subset=['Close'])
                        if len(f):results[t]=f
                        else:errors[t]='No usable bars'
                    except Exception:errors[t]='Ticker missing from download'
                break
            except Exception as e:
                if attempt==1:
                    for t in group:errors[t]=str(e)[:160]
                else:time.sleep(2)
        print(f'Downloaded {min(offset+chunk,len(tickers))}/{len(tickers)} {interval}',flush=True)
    return results,errors

def hma(series,n=38):
    def wma(s,w):
        weights=np.arange(1,w+1,dtype=float)
        return s.rolling(w).apply(lambda x:float(np.dot(x,weights)/weights.sum()),raw=True)
    return wma(2*wma(series,n//2)-wma(series,n),int(math.sqrt(n)))

def confirmed_box(df,confirmation=2,lookback=90):
    """Historical pivot-high/pivot-low box. A pivot at i only becomes known at i+confirmation.
    This is a simplified, explicit box proxy, not an exact reproduction of existing V6.
    """
    d=df.iloc[-lookback:].copy(); highs=d['High'].to_numpy(dtype=float); lows=d['Low'].to_numpy(dtype=float)
    if len(d)<max(55,confirmation*2+12):return None
    piv_hi=[];piv_lo=[]
    for i in range(confirmation,len(d)-confirmation):
        if highs[i]>=max(highs[i-confirmation:i]) and highs[i]>max(highs[i+1:i+confirmation+1]):piv_hi.append(i)
        if lows[i]<=min(lows[i-confirmation:i]) and lows[i]<min(lows[i+1:i+confirmation+1]):piv_lo.append(i)
    # Use a pivot high, paired with the most recent pivot low at or before its confirmation.
    for hi in reversed(piv_hi):
        if hi+confirmation>=len(d)-1:continue
        candidates=[lo for lo in piv_lo if lo<=hi+confirmation and lo>=hi-35]
        if not candidates:continue
        lo=candidates[-1]; upper=float(highs[hi]);lower=float(lows[lo])
        if lower>=upper or (upper-lower)/upper>0.30:continue
        # Breakout today must not be compared to a box that was already broken before today.
        if (d['Close'].iloc[hi+confirmation+1:-1]>upper).any():continue
        return {'high':upper,'low':lower,'confirmed':str(d.index[hi+confirmation].date()),'pivot':str(d.index[hi].date())}
    return None

def classify(ticker,df,mode,intra=None,near=3.0):
    if len(df)<80:return None,'Fewer than 80 daily bars'
    daily=df.iloc[:-1] if mode=='intraday' and df.index[-1].date()==datetime.now(CT).date() else df
    if len(daily)<80:return None,'Insufficient completed daily bars'
    box=confirmed_box(daily)
    if not box:return None,'No confirmed unbroken box'
    close=daily['Close'].astype(float); high=float(box['high']); low=float(box['low'])
    current=float(close.iloc[-1]); asof=str(daily.index[-1]); volume_basis='Completed daily'
    if mode=='intraday':
        if intra is None or intra.empty:return None,'No intraday data (cannot claim intraday breakout)'
        recent=intra.dropna(subset=['Close'])
        if recent.empty:return None,'No intraday bars'
        current=float(recent['Close'].iloc[-1]);asof=str(recent.index[-1]);volume_basis='Intraday partial; ratio unavailable'
    h=hma(close);rising=bool(pd.notna(h.iloc[-2]) and pd.notna(h.iloc[-1]) and h.iloc[-1]>h.iloc[-2])
    high52=float(daily['High'].iloc[-252:].max()); dist=(current/high-1)*100;dist52=(current/high52-1)*100
    vol_ratio=None
    if mode=='daily' and len(daily)>21:
        base=float(daily['Volume'].iloc[-21:-1].mean());vol_ratio=float(daily['Volume'].iloc[-1]/base) if base>0 else None
    stop_risk=(current-low)/current*100 if current>0 else None
    if dist>3:status='EXTENDED'
    elif dist>0:status='INTRADAY BREAKOUT' if mode=='intraday' else 'DAILY BREAKOUT'
    elif dist>=-near:status='NEAR BREAKOUT'
    else:status='FORMING BOX'
    if dist52>=-10:cat='CLASSIC DARVAS'
    elif rising and dist52>=-30:cat='EMERGING UPTREND'
    else:cat='RECOVERY WATCH'
    volume_ok=(vol_ratio is not None and vol_ratio>=1.5)
    strict=(status=='DAILY BREAKOUT' and volume_ok and rising and stop_risk is not None and 0<stop_risk<=8)
    if strict:decision='DAILY RESEARCH CANDIDATE'
    elif status=='INTRADAY BREAKOUT':decision='PROVISIONAL WATCH — VERIFY LIVE DATA'
    else:decision='WATCH / NOT QUALIFIED'
    score=round(max(0,min(100,35+(20 if rising else 0)+(15 if vol_ratio is not None and volume_ok else 0)+(15 if -near<=dist<=3 else 0)+(15 if stop_risk is not None and stop_risk<=8 else 0))),1)
    notes='Intraday volume is NOT treated as full-day confirmation' if mode=='intraday' else ('Daily strict conditions met' if strict else 'Does not meet all strict daily buy conditions')
    row=[ticker,cat,status,round(current,3),round(high,3),round(low,3),box['confirmed'],round(dist,2),round(high52,3),round(dist52,2),round(vol_ratio,2) if vol_ratio is not None else '',volume_basis,'YES' if rising else 'NO',round(stop_risk,2) if stop_risk is not None else '',score,decision,asof,notes]
    return row,None

def universe(args):
    current=read_symbols(args.fallback)
    pool=list(dict.fromkeys(current+listing('https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt','NASDAQ')+listing('https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt','OTHER')))
    if not pool:
        raise SystemExit('No symbols available. Supply --fallback with a valid existing list.')
    # Preliminary liquidity/strength selection using public daily OHLCV; no invented market cap data.
    data,errors=download(pool,period='1y',chunk=args.chunk)
    ranked=[]
    for t,d in data.items():
        if len(d)<100:continue
        c=d['Close'].astype(float);v=d['Volume'].astype(float)
        price=float(c.iloc[-1]);adv=float((c.iloc[-21:]*v.iloc[-21:]).mean())
        if price<5 or adv<5_000_000:continue
        ret6=price/float(c.iloc[-min(len(c),127)])-1
        ret12=price/float(c.iloc[0])-1
        hi=float(d['High'].iloc[-252:].max());near=price/hi
        score=ret6*35+ret12*20+near*20+math.log10(max(adv,1))*2
        ranked.append((score,t,price,adv,ret6,ret12,near))
    ranked.sort(reverse=True)
    selected=[r[1] for r in ranked[:args.limit]]
    # If source data is insufficient, preserve the previously saved universe rather than replace with an incomplete list.
    if len(selected)<args.min_success:
        previous=read_symbols(args.output)
        if previous:
            print(f'WARNING only {len(selected)} eligible; preserving {len(previous)} previous symbols',flush=True);return
        if current:
            print(f'WARNING only {len(selected)} eligible; using existing fallback of {len(current)} symbols',flush=True)
            selected=current[:args.limit]
        else:raise SystemExit('Universe refresh insufficient and no safe fallback available')
    Path(args.output).write_text('\n'.join(selected)+'\n')
    with open('darvas_v62_universe_audit.csv','w',newline='') as f:
        w=csv.writer(f);w.writerow(['Ticker','Selection Score','Price','Average Daily Dollar Volume','6M Return','12M Return','Fraction of 52W High'])
        for r in ranked:w.writerow([r[1],round(r[0],3),round(r[2],3),round(r[3],2),round(r[4],4),round(r[5],4),round(r[6],4)])
    print(f'Universe: {len(selected)} selected from {len(pool)} listed symbols; {len(errors)} download errors',flush=True)

def report(rows,errors,mode,output):
    wb=Workbook();wb.remove(wb.active)
    sections=['DASHBOARD','INTRADAY CANDIDATES','DAILY CONFIRMED','NEAR BREAKOUT','FORMING BOXES','EMERGING UPTREND','RECOVERY WATCH','BUY RANKING','BREAKOUT TRACKER','STATUS HISTORY','ALL STOCKS','DATA QUALITY']
    for s in sections:wb.create_sheet(s)
    def sheet(name,headers,data):
        ws=wb[name];ws.append(headers)
        for row in data:ws.append(row)
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for cell in ws[1]:cell.fill=PatternFill('solid',fgColor='183153');cell.font=Font(color='FFFFFF',bold=True);cell.alignment=Alignment(wrap_text=True)
        for j in range(1,len(headers)+1):ws.column_dimensions[get_column_letter(j)].width=min(38,max(14,len(str(headers[j-1]))+2))
        for i in range(2,ws.max_row+1):
            if i%2==0:
                for c in ws[i]:c.fill=PatternFill('solid',fgColor='EDF3FA')
    now=datetime.now(CT).isoformat(timespec='seconds')
    summary=[['Mode',mode],['Report generated CT',now],['Symbols with valid setups',len(rows)],['Symbols with data/setup errors',len(errors)],['Provisional signals',sum('INTRADAY' in r[2] for r in rows)],['Strict daily research candidates',sum(r[15]=='DAILY RESEARCH CANDIDATE' for r in rows)],['Disclaimer','Research only. No broker orders; data may be delayed.']]
    sheet('DASHBOARD',['Metric','Value'],summary)
    predicates={
        'INTRADAY CANDIDATES':lambda r:r[2]=='INTRADAY BREAKOUT',
        'DAILY CONFIRMED':lambda r:r[2]=='DAILY BREAKOUT',
        'NEAR BREAKOUT':lambda r:r[2]=='NEAR BREAKOUT',
        'FORMING BOXES':lambda r:r[2]=='FORMING BOX',
        'EMERGING UPTREND':lambda r:r[1]=='EMERGING UPTREND',
        'RECOVERY WATCH':lambda r:r[1]=='RECOVERY WATCH',
        'BUY RANKING':lambda r:r[15] in ('DAILY RESEARCH CANDIDATE','PROVISIONAL WATCH — VERIFY LIVE DATA'),
        'ALL STOCKS':lambda r:True}
    for name,p in predicates.items():sheet(name,HEADERS,sorted([r for r in rows if p(r)],key=lambda x:x[14],reverse=True))
    # Persistence across GitHub Actions runs requires explicit state storage, not ephemeral runner files.
    previous={}
    state=Path('darvas_v62_signal_state.json')
    if state.exists():
        try:previous=json.loads(state.read_text())
        except Exception:pass
    transitions=[];new={}
    for r in rows:
        old=previous.get(r[0],{}).get('status','NOT PREVIOUSLY TRACKED')
        if old!=r[2]:transitions.append([r[0],old,r[2],now,r[3]])
        new[r[0]]={'status':r[2],'price':r[3],'asof':now}
    sheet('STATUS HISTORY',['Ticker','Previous Status','Current Status','Scan Time CT','Price'],transitions)
    sheet('BREAKOUT TRACKER',['Ticker','Latest Status','Latest Price','Scan Time CT'],[[r[0],r[2],r[3],now] for r in rows if 'BREAKOUT' in r[2]])
    sheet('DATA QUALITY',['Ticker','Issue'],sorted(errors.items()))
    wb.save(output)
    # Persist only current state; history is in report artifact and requires external retention for long-term tracking.
    state.write_text(json.dumps(new,indent=2))
    print(f'Saved {output}: {len(rows)} setups; {len(errors)} missing/no-box symbols',flush=True)

def scan(args):
    syms=read_symbols(args.symbols)
    if not syms:raise SystemExit('Universe missing or empty. Run universe first or provide --symbols.')
    daily,err=download(syms,period='18mo',interval='1d',chunk=args.chunk)
    intra={}
    if args.mode=='intraday':
        # Current-day 5-minute bars, if available. Never fabricate live quotes.
        intra,intra_err=download(syms,period='1d',interval='5m',chunk=args.chunk)
        for t,e in intra_err.items():err[t]='Intraday: '+e
    rows=[]
    for t in syms:
        if t not in daily:err.setdefault(t,'No daily history');continue
        try:
            r,e=classify(t,daily[t],args.mode,intra.get(t),args.near)
            if r:rows.append(r);err.pop(t,None)
            else:err[t]=e
        except Exception as e:err[t]='Analysis error: '+str(e)[:160]
    report(rows,err,args.mode,args.output)

def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='command',required=True)
    u=sub.add_parser('universe');u.add_argument('--fallback',default='symbols.txt');u.add_argument('--output',default='symbols_v6_1500.txt');u.add_argument('--limit',type=int,default=1500);u.add_argument('--min-success',type=int,default=1000);u.add_argument('--chunk',type=int,default=60)
    s=sub.add_parser('scan');s.add_argument('--mode',choices=['daily','intraday'],default='daily');s.add_argument('--symbols',default='symbols_v6_1500.txt');s.add_argument('--near',type=float,default=3);s.add_argument('--chunk',type=int,default=60);s.add_argument('--output',default='darvas_v62_report.xlsx')
    a=ap.parse_args();universe(a) if a.command=='universe' else scan(a)
if __name__=='__main__':main()

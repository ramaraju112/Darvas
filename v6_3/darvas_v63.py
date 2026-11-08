#!/usr/bin/env python3
"""Darvas V6.3: daily US-market discovery, causal box breakouts and backtest.
Research software, not an order execution system. No intraday claims from daily OHLCV.
"""
import argparse, io, json, logging, math, os, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import yfinance as yf

LOG=logging.getLogger('darvas')
OUT=Path(os.environ.get('DARVAS_OUTPUT','v6_3/output'))
HEADERS={'User-Agent':'DarvasResearchScanner/0.1 (personal research)'}
DIRECTORIES={
 'nasdaq':'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt',
 'other':'https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt'
}

def universe(max_symbols=0, min_price=5, min_dollar_volume=2_000_000, history_days=100):
    """Build security-type-filtered *candidate* universe; liquidity tested during scan."""
    frames=[]
    for label,url in DIRECTORIES.items():
        r=requests.get(url,timeout=30,headers=HEADERS); r.raise_for_status()
        df=pd.read_csv(io.StringIO(r.text),sep='|',dtype=str).fillna('')
        if label=='nasdaq':
            df=df[(df['Test Issue']=='N') & (df['ETF']=='N')]
            df=df.rename(columns={'Symbol':'symbol','Security Name':'name'})
        else:
            df=df[(df['Test Issue']=='N') & (df['ETF']=='N')]
            df=df[df['Exchange'].isin(['N','A','P'])]  # NYSE, NYSE American, NYSE Arca (non-ETFs)
            df=df.rename(columns={'ACT Symbol':'symbol','Security Name':'name'})
        df=df[['symbol','name']]
        frames.append(df)
    data=pd.concat(frames,ignore_index=True).drop_duplicates('symbol')
    # Exclude common non-operating-company instruments; heuristic, not perfect.
    pattern=r'(?i)\b(warrant|rights?|unit[s]?|preferred|preference|depositary shares|notes due|debenture|etn|closed.end fund|acquisition right)\b'
    data=data[~data['name'].str.contains(pattern,regex=True,na=False)]
    data=data[data['symbol'].str.fullmatch(r'[A-Z][A-Z0-9.]{0,9}',na=False)]
    data['yf_symbol']=data['symbol'].str.replace('.','-',regex=False)
    data=data.sort_values('symbol').reset_index(drop=True)
    if max_symbols>0: data=data.head(max_symbols)
    OUT.mkdir(parents=True,exist_ok=True)
    data.to_csv(OUT/'universe.csv',index=False)
    (OUT/'universe_meta.json').write_text(json.dumps({'created_utc':datetime.now(timezone.utc).isoformat(),'count':len(data),'max_symbols':max_symbols,'liquidity_filter_applied':'during scan'},indent=2))
    return data

def confirmed_boxes(close, high, low, confirmation=3):
    """Causal research interpretation: candidate high confirmed after N subsequent sessions
    without higher high; then candidate low confirmed after N subsequent sessions without lower low.
    Outputs known levels at each close; never backfills earlier rows. This is one mechanical
    interpretation, not an assertion that Darvas wrote a unique executable specification.
    """
    n=len(high); tops=np.full(n,np.nan); bottoms=np.full(n,np.nan)
    candidate_hi=None; hi_index=None; candidate_lo=None; lo_index=None
    top=np.nan; bottom=np.nan; phase='top'
    for i in range(n):
        h=float(high.iloc[i]); l=float(low.iloc[i])
        if not np.isfinite(h) or not np.isfinite(l):
            tops[i]=top; bottoms[i]=bottom; continue
        if phase=='top':
            if candidate_hi is None or h>=candidate_hi:
                candidate_hi=h; hi_index=i
            elif i-hi_index>=confirmation:
                top=candidate_hi; phase='bottom'; candidate_lo=l; lo_index=i
        else:
            if candidate_lo is None or l<=candidate_lo:
                candidate_lo=l; lo_index=i
            elif i-lo_index>=confirmation:
                bottom=candidate_lo
                phase='top'; candidate_hi=h; hi_index=i
        tops[i]=top; bottoms[i]=bottom
    return pd.DataFrame({'box_top':tops,'box_bottom':bottoms},index=high.index)

def indicators(df,confirmation=3):
    x=df.copy().sort_index()
    x.columns=[str(c).lower() for c in x.columns]
    boxes=confirmed_boxes(x['close'],x['high'],x['low'],confirmation)
    x=x.join(boxes)
    x['avg_volume20']=x['volume'].rolling(20,min_periods=15).mean().shift(1)
    x['avg_dollar_volume20']=(x['close']*x['volume']).rolling(20,min_periods=15).mean().shift(1)
    x['volume_ratio']=x['volume']/x['avg_volume20'].replace(0,np.nan)
    x['prior_top']=x['box_top'].shift(1)
    x['prior_bottom']=x['box_bottom'].shift(1)
    x['breakout']=(x['high']>x['prior_top']) & (x['close']>x['prior_top']) & (x['close'].shift(1)<=x['prior_top'])
    x['near_breakout']=(x['close']<=x['box_top']) & (x['close']>=x['box_top']*0.97)
    x['low_252']=x['low'].rolling(252,min_periods=60).min().shift(1)
    x['high_252']=x['high'].rolling(252,min_periods=60).max().shift(1)
    x['recovery_from_low']=x['close']/x['low_252']-1
    x['below_high']=x['close']/x['high_252']-1
    x['higher_box']=x['box_top']>x['box_top'].shift(20)
    return x

def _download(symbols,period='2y',interval='1d'):
    raw=yf.download(symbols,period=period,interval=interval,group_by='ticker',auto_adjust=True,progress=False,threads=True)
    if raw is None or raw.empty: return {}
    if isinstance(raw.columns,pd.MultiIndex):
        # group_by=ticker generally produces (ticker, OHLCV)
        level0=set(map(str,raw.columns.get_level_values(0)))
        if len(symbols)==1 and symbols[0] not in level0:
            return {symbols[0]:raw}
        return {s:raw[s].dropna(how='all') for s in symbols if s in level0}
    return {symbols[0]:raw} if len(symbols)==1 else {}

def scan(args):
    path=Path(args.universe)
    if not path.exists(): raise SystemExit(f'Missing {path}. Run universe first.')
    items=pd.read_csv(path).dropna(subset=['yf_symbol'])
    if args.limit: items=items.head(args.limit)
    results=[]; failures=[]
    for start in range(0,len(items),args.batch_size):
        batch=items.iloc[start:start+args.batch_size]
        symbols=batch['yf_symbol'].tolist()
        try: data=_download(symbols,period=args.period)
        except Exception as exc:
            LOG.warning('Batch %s failed: %s',start,exc); failures.extend(symbols); continue
        for _,item in batch.iterrows():
            symbol=item['yf_symbol']; df=data.get(symbol)
            if df is None or len(df)<65: failures.append(symbol); continue
            try:
                x=indicators(df,args.confirmation)
                last=x.iloc[-1]
                if pd.isna(last['close']) or last['close']<args.min_price or pd.isna(last['avg_dollar_volume20']) or last['avg_dollar_volume20']<args.min_dollar_volume: continue
                status=('BREAKOUT' if bool(last['breakout']) else 'NEAR_BREAKOUT' if bool(last['near_breakout']) else 'HIGHER_BOX' if bool(last['higher_box']) and pd.notna(last['box_bottom']) else 'RECOVERY_WATCH' if pd.notna(last['recovery_from_low']) and last['recovery_from_low']>=args.recovery_threshold and last['below_high']<=-0.15 else 'WATCH')
                results.append({'symbol':item['symbol'],'name':item['name'],'asof':str(x.index[-1]),'status':status,'close':round(float(last['close']),3),'box_top':round(float(last['box_top']),3) if pd.notna(last['box_top']) else None,'box_bottom':round(float(last['box_bottom']),3) if pd.notna(last['box_bottom']) else None,'volume_ratio':round(float(last['volume_ratio']),2) if pd.notna(last['volume_ratio']) else None,'avg_dollar_volume20':round(float(last['avg_dollar_volume20']),0),'recovery_from_low_pct':round(float(last['recovery_from_low'])*100,1) if pd.notna(last['recovery_from_low']) else None,'below_52w_high_pct':round(float(last['below_high'])*100,1) if pd.notna(last['below_high']) else None,'strategy':'RECOVERY_EXTENSION' if status=='RECOVERY_WATCH' else 'CLASSIC_BOX_RESEARCH'})
            except Exception as exc:
                LOG.warning('Failed %s: %s',symbol,exc); failures.append(symbol)
        LOG.info('Scanned %s/%s',min(start+args.batch_size,len(items)),len(items))
        if args.pause: time.sleep(args.pause)
    OUT.mkdir(parents=True,exist_ok=True)
    columns=['symbol','name','asof','status','close','box_top','box_bottom','volume_ratio','avg_dollar_volume20','recovery_from_low_pct','below_52w_high_pct','strategy']
    result=pd.DataFrame(results,columns=columns)
    result['priority']=result['status'].map({'BREAKOUT':0,'NEAR_BREAKOUT':1,'HIGHER_BOX':2,'RECOVERY_WATCH':3,'WATCH':4})
    result=result.sort_values(['priority','volume_ratio'],ascending=[True,False]).drop(columns='priority')
    result.to_csv(OUT/'scan_all.csv',index=False)
    result[result.status!='WATCH'].to_csv(OUT/'signals.csv',index=False)
    pd.DataFrame({'failed_symbol':failures}).to_csv(OUT/'download_failures.csv',index=False)
    with pd.ExcelWriter(OUT/'darvas_v63_report.xlsx',engine='openpyxl') as writer:
        result.head(2000).to_excel(writer,'Ranked candidates',index=False)
        for label in ['BREAKOUT','NEAR_BREAKOUT','HIGHER_BOX','RECOVERY_WATCH']:
            result[result.status==label].head(1000).to_excel(writer,label[:31],index=False)
        pd.DataFrame({'failed_symbol':failures}).to_excel(writer,'Download failures',index=False)
    LOG.info('Saved %s candidates, %s data failures',len(result),len(failures))

def backtest(args):
    """Daily-bar, next-open entries, gap-aware stop fills, single-position baseline.
    Does not implement full pyramiding or portfolio-wide capital allocation.
    """
    data=_download([args.symbol],period=args.period)
    if args.symbol not in data: raise SystemExit('No data returned for symbol')
    x=indicators(data[args.symbol],args.confirmation)
    cash=float(args.capital); shares=0; stop=np.nan; entry=np.nan; trades=[]; equity=[]
    for i in range(65,len(x)):
        today=x.iloc[i]; yesterday=x.iloc[i-1]
        o=float(today['open']); lo=float(today['low']); cl=float(today['close'])
        if shares:
            if pd.notna(yesterday['box_bottom']):
                stop=max(stop,float(yesterday['box_bottom'])) if np.isfinite(stop) else float(yesterday['box_bottom'])
            if lo<=stop:
                fill=min(o,stop)*(1-args.slippage)
                cash+=shares*fill*(1-args.fee)
                trades.append({'date':str(x.index[i]),'action':'SELL','shares':shares,'price':fill,'cash':cash,'reason':'protective stop'})
                shares=0; stop=np.nan
        if not shares and bool(yesterday['breakout']) and pd.notna(yesterday['box_bottom']):
            fill=o*(1+args.slippage)
            initial_stop=float(yesterday['box_bottom'])
            risk_per_share=fill-initial_stop
            if risk_per_share>0:
                qty=min(int(cash*args.risk_fraction/risk_per_share),int(cash/(fill*(1+args.fee))))
                if qty>0:
                    cash-=qty*fill*(1+args.fee); shares=qty; entry=fill; stop=initial_stop
                    trades.append({'date':str(x.index[i]),'action':'BUY','shares':qty,'price':fill,'cash':cash,'reason':'prior-close confirmed breakout; next open'})
        equity.append({'date':str(x.index[i]),'equity':cash+shares*cl,'cash':cash,'shares':shares,'stop':stop})
    OUT.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(trades,columns=['date','action','shares','price','cash','reason']).to_csv(OUT/'backtest_trades.csv',index=False)
    curve=pd.DataFrame(equity); curve.to_csv(OUT/'backtest_equity.csv',index=False)
    peak=curve.equity.cummax(); drawdown=(curve.equity/peak-1).min()
    metrics={'symbol':args.symbol,'initial_capital':args.capital,'ending_equity':round(float(curve.equity.iloc[-1]),2),'total_return_pct':round((float(curve.equity.iloc[-1])/args.capital-1)*100,2),'max_drawdown_pct':round(float(drawdown)*100,2),'transactions':len(trades),'limitations':'Daily bars; no intraday order simulation, pyramiding, or multi-symbol portfolio accounting.'}
    (OUT/'backtest_metrics.json').write_text(json.dumps(metrics,indent=2))
    LOG.info('%s',metrics)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',default='v6_3/output')
    sub=p.add_subparsers(dest='command',required=True)
    u=sub.add_parser('universe'); u.add_argument('--limit',type=int,default=0)
    s=sub.add_parser('scan'); s.add_argument('--universe',default='v6_3/output/universe.csv'); s.add_argument('--limit',type=int,default=0); s.add_argument('--batch-size',type=int,default=40); s.add_argument('--pause',type=float,default=1.0); s.add_argument('--period',default='2y'); s.add_argument('--min-price',type=float,default=5); s.add_argument('--min-dollar-volume',type=float,default=2_000_000); s.add_argument('--confirmation',type=int,default=3); s.add_argument('--recovery-threshold',type=float,default=0.30)
    b=sub.add_parser('backtest'); b.add_argument('--symbol',required=True); b.add_argument('--period',default='5y'); b.add_argument('--capital',type=float,default=100000); b.add_argument('--risk-fraction',type=float,default=0.01); b.add_argument('--confirmation',type=int,default=3); b.add_argument('--slippage',type=float,default=0.001); b.add_argument('--fee',type=float,default=0.0)
    args=p.parse_args(); global OUT; OUT=Path(args.output)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    if args.command=='universe': LOG.info('Universe size %s',len(universe(args.limit)))
    elif args.command=='scan': scan(args)
    else: backtest(args)
if __name__=='__main__': main()

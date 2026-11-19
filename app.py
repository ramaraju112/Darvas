"""Darvas V7.4 integrated browser MVP. Research only, no trading."""
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import secrets
from contextlib import closing
import csv, io, json, os, sqlite3, threading, time, re
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
DB=DATA/'darvas.db'
DEFAULT=['ORCL','ACN','INTC','NKE','SEZL','MSFT','NVDA','PLTR','AMD','META','AMZN','AVGO','SPY','QQQ']
LOCK=threading.Lock()
app=FastAPI(title='Darvas V7.4 — Browser MVP',version='0.1.0')
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

def conn():
    c=sqlite3.connect(DB,timeout=30); c.row_factory=sqlite3.Row; return c

def init():
    with closing(conn()) as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS bars(symbol TEXT, day TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY(symbol,day));
        CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY, quantity REAL, cost_basis REAL, horizon TEXT DEFAULT 'position', thesis TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, symbol_count INTEGER, notes TEXT);
        CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, symbol TEXT, severity TEXT, message TEXT, delivered INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS notes(symbol TEXT PRIMARY KEY, text TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS market_universe(symbol TEXT PRIMARY KEY, exchange TEXT, name TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS sync_log(id INTEGER PRIMARY KEY AUTOINCREMENT, run_day TEXT, batch_offset INTEGER, attempted INTEGER, succeeded INTEGER, errors INTEGER, backup TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS screen_cache(symbol TEXT PRIMARY KEY, payload TEXT NOT NULL, updated TEXT NOT NULL);''')
        existing={r[1] for r in c.execute('PRAGMA table_info(market_universe)')}
        for col,definition in {
            'eligible':'INTEGER NOT NULL DEFAULT 0', 'active':'INTEGER NOT NULL DEFAULT 1',
            'reason':'TEXT', 'last_attempt':'TEXT', 'last_success':'TEXT',
            'failures':'INTEGER NOT NULL DEFAULT 0', 'last_error':'TEXT'
        }.items():
            if col not in existing: c.execute(f'ALTER TABLE market_universe ADD COLUMN {col} {definition}')
        c.execute('CREATE INDEX IF NOT EXISTS ix_universe_queue ON market_universe(active,eligible,last_attempt)')
        c.commit()
# Database initialization runs after the Oracle restore attempt below.

def clean_symbol(s):
    s=str(s).strip().upper()
    if not s or len(s)>16 or any(x not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^' for x in s):
        raise ValueError('Invalid ticker')
    return s

def rows(sql,params=()):
    with closing(conn()) as c: return [dict(r) for r in c.execute(sql,params).fetchall()]

def history(symbol):
    return pd.DataFrame(rows('SELECT day,open,high,low,close,volume FROM bars WHERE symbol=? ORDER BY day',(symbol,)))

def indicators(df):
    d=df.copy()
    if len(d)<45: return d
    c=d['close'].astype(float); v=d['volume'].astype(float)
    def wma(s,n): return s.rolling(n).apply(lambda a: np.dot(a,np.arange(1,n+1))*2/(n*(n+1)),raw=True)
    d['hma38']=wma(2*wma(c,19)-wma(c,38),6)
    d['hma_slope3']=d['hma38']/d['hma38'].shift(3)-1
    prev=c.shift(1)
    tr=pd.concat([d.high-d.low,(d.high-prev).abs(),(d.low-prev).abs()],axis=1).max(axis=1)
    d['atr14']=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    d['rvol20']=v/v.shift(1).rolling(20).mean()
    d['addv20']=(c*v).rolling(20).mean()
    d['ret20']=c/c.shift(20)-1
    return d

def classic_darvas_engine(d):
    """Conservative 20-session breakout *watch*, not a confirmed Darvas box."""
    last = d.iloc[-1]
    prior = d.iloc[-21:-1]  # exclude today's bar from reference high AND depth
    prior_high = float(prior.high.max())
    prior_low = float(prior.low.min())
    depth = (prior_high-prior_low)/max(prior_high, 0.01)
    price = float(last.close)
    volume = float(last.volume)
    rvol = float(last.rvol20) if pd.notna(last.rvol20) else None
    # Avoid falsely classifying new issues, empty volume, and insufficient history.
    enough_history = len(d) >= 120
    watch = (enough_history and price > prior_high and depth <= .15
             and volume > 0 and rvol is not None and rvol >= 1.2)
    reasons=[]
    if not enough_history: reasons.append('Less than 120 sessions of price history')
    if not price > prior_high: reasons.append('Close did not exceed preceding 20-session high')
    if depth > .15: reasons.append('Prior 20-session range exceeds 15%')
    if volume <= 0 or rvol is None: reasons.append('Volume missing or zero')
    elif rvol < 1.2: reasons.append('RVOL below provisional 1.2 threshold')
    if watch: reasons.append('Provisional breakout watch only; confirmed Darvas pivots not implemented')
    return {'watch':bool(watch),'stage':'BREAKOUT_WATCH' if watch else 'NONE',
            'base_depth_pct':round(depth*100,2),'prior_high':round(prior_high,3),
            'reasons':reasons,
            'reason':'Independent provisional breakout watch; confirmed Darvas boxes/pivots not implemented'}

def early_recovery_engine(d):
    """Independent early-recovery research discovery; no Darvas box/depth condition."""
    last=d.iloc[-1]; price=float(last['close']); base=d.iloc[-20:]
    prev=d.iloc[-140:-20] if len(d)>=140 else d.iloc[:-20]
    reference_high=float(prev.high.max()) if len(prev) else price
    low=float(base.low.min())
    decline=(reference_high-low)/max(reference_high,0.01)
    hma=float(last.hma38) if pd.notna(last.hma38) else None
    slope=float(last.hma_slope3) if pd.notna(last.hma_slope3) else None
    rvol=float(last.rvol20) if pd.notna(last.rvol20) else None
    # Discovery is deliberately broader than a trade-ready watch.
    discovery=decline>=0.20 and slope is not None and slope>0 and hma is not None and price>hma
    watch=discovery and rvol is not None and rvol>=1.0
    stage='RECOVERY_WATCH' if watch else 'DISCOVERY' if discovery else 'NONE'
    reasons=[]
    if decline<0.20: reasons.append('Prior decline below exploratory 20% discovery threshold')
    if slope is None or slope<=0: reasons.append('HMA slope not positive')
    if hma is None or price<=hma: reasons.append('Price not above HMA38')
    if discovery and not watch: reasons.append('RVOL below exploratory 1.0 watch threshold')
    if watch: reasons.append('Recovery discovery with volume confirmation; not an entry signal')
    return {'discovery':bool(discovery),'watch':bool(watch),'stage':stage,
            'prior_decline_pct':round(decline*100,2),'reasons':reasons,
            'reason':'Independent provisional recovery discovery; no Darvas box requirement'}

def signal(symbol):
    df=history(symbol)
    if len(df)<65:
        return {'symbol':symbol,'status':'DATA_INCOMPLETE','bars':len(df),
                'darvas_watch':False,'recovery_watch':False,'recovery_discovery':False,
                'darvas':{'stage':'DATA_INCOMPLETE'},'recovery':{'stage':'DATA_INCOMPLETE'},
                'reason':'At least 65 daily bars required for screening'}
    d=indicators(df); last=d.iloc[-1]
    darvas=classic_darvas_engine(d)
    recovery=early_recovery_engine(d)
    slope=float(last.hma_slope3) if pd.notna(last.hma_slope3) else None
    return {'symbol':symbol,'status':'RESEARCH_ONLY','date':str(last.day),
        'price':round(float(last['close']),3),'bars':len(d),
        'darvas_watch':darvas['watch'],'recovery_watch':recovery['watch'],
        'recovery_discovery':recovery['discovery'],
        'darvas_stage':darvas['stage'],'recovery_stage':recovery['stage'],
        'stage':recovery['stage'] if recovery['discovery'] else darvas['stage'],
        'darvas':darvas,'recovery':recovery,
        'base_depth_pct':darvas['base_depth_pct'],
        'prior_decline_pct':recovery['prior_decline_pct'],
        'hma38':round(float(last.hma38),3) if pd.notna(last.hma38) else None,
        'hma_slope3_pct':round(slope*100,2) if slope is not None else None,
        'atr14':round(float(last.atr14),3) if pd.notna(last.atr14) else None,
        'rvol20':round(float(last.rvol20),2) if pd.notna(last.rvol20) else None,
        'data_age_days':(datetime.now(timezone.utc).date()-pd.Timestamp(last.day).date()).days,
        'reason':'Separate provisional Darvas breakout and independent recovery discovery; neither is a verified entry signal'}

# V7.5 shadow research API. Existing V7.4 signals, caches, and sync remain unchanged.
from engines.v75 import classic as v75_classic, recovery as v75_recovery, VERSION as V75_ENGINE_VERSION

@app.get('/api/v75/shadow/{symbol}')
def v75_shadow(symbol: str):
    symbol = clean_symbol(symbol)
    df = history(symbol)
    if len(df) < 65:
        return {'symbol': symbol, 'version': V75_ENGINE_VERSION,
                'status': 'DATA_INCOMPLETE', 'bars': len(df),
                'classic': {'stage': 'DATA_INCOMPLETE'},
                'recovery': {'stage': 'DATA_INCOMPLETE'}}
    d = indicators(df)
    return {'symbol': symbol, 'version': V75_ENGINE_VERSION,
            'status': 'SHADOW_RESEARCH_ONLY', 'date': str(d.iloc[-1]['day']),
            'bars': len(d), 'classic': v75_classic(d),
            'recovery': v75_recovery(d),
            'warning': 'Experimental independent V7.5 engines; no trading recommendation. Existing V7.4 endpoints unchanged.'}

class Download(BaseModel):
    symbols:list[str]=DEFAULT
    period:str='10y'
class Note(BaseModel):
    symbol:str
    text:str
class Alert(BaseModel):
    symbol:str
    severity:str
    message:str

@app.get('/')
def index(): return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/status')
def status():
    return {
        'mode': 'RESEARCH_ONLY',
        'connected_broker': False,
        'live_feed': False,
        'telegram_configured': bool(
            os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID')
        ),
        'symbols': rows(
            'SELECT symbol, COUNT(*) AS bars, MIN(day) AS first_day, '
            'MAX(day) AS last_day FROM bars GROUP BY symbol ORDER BY symbol'
        ),
        'positions': rows('SELECT * FROM positions ORDER BY symbol'),
        'runs': rows('SELECT * FROM runs ORDER BY id DESC LIMIT 5')
    }
# Universe is a candidate pool, not a certified count of common equities.
# Do not silently discard ambiguous names: mark them UNVERIFIED and keep them
# in the download candidate pool. Audit before interpreting screening coverage.
NON_EQUITY_NAME = re.compile(
    r"\b(warrants?|units?|rights?|preferred|preference|etfs?|etns?|"
    r"closed.end fund|mutual fund|exchange.traded fund|"
    r"notes?|bonds?|debentures?|certificates?|subscription rights?|"
    r"depositary shares? representing preferred|"
    r"depositary shares? each representing.*preferred)\b", re.I)
COMMON_NAME = re.compile(
    r"\b(common stock|common shares?|ordinary shares?|ordinary stock|"
    r"class [a-z] (?:common )?stock|class [a-z] common|"
    r"american depositary shares?|american depositary receipts?|ads|adr)\b", re.I)
NON_EQUITY_SUFFIX = ('.WS', '.WT', '.U', '.R', '.W')

def equity_classification(symbol, name, etf=False, test=False):
    name = str(name or '').strip()
    if test: return 'EXCLUDED', 'exchange directory test issue'
    if etf: return 'EXCLUDED', 'exchange directory ETF flag'
    if symbol.endswith(NON_EQUITY_SUFFIX):
        return 'EXCLUDED', 'non-common security ticker suffix'
    if NON_EQUITY_NAME.search(name):
        return 'EXCLUDED', 'name indicates non-common instrument'
    if COMMON_NAME.search(name):
        return 'CONFIRMED_CANDIDATE', 'name explicitly describes common/ordinary/ADR equity'
    return 'UNVERIFIED', 'security type not proven by directory name; included pending review'

def classify_common_equity(symbol, name, etf=False, test=False):
    status, reason = equity_classification(symbol, name, etf, test)
    return status != 'EXCLUDED', reason

@app.get('/api/universe')
def universe(offset:int=0,limit:int=150):
    if offset<0 or not 1<=limit<=150: raise HTTPException(400,'Invalid pagination')
    total=rows('SELECT COUNT(*) AS n FROM market_universe WHERE active=1 AND eligible=1')[0]['n']
    entries=rows('SELECT symbol,exchange,name,reason FROM market_universe WHERE active=1 AND eligible=1 ORDER BY symbol LIMIT ? OFFSET ?',(limit,offset))
    return {'total':total,'offset':offset,'limit':limit,'symbols':entries,
            'note':'Candidate equity universe includes UNVERIFIED listings to reduce false exclusions; it is NOT a verified complete common-stock list.'}

@app.get('/api/universe/audit')
def universe_audit():
    summary=rows("""SELECT
        COUNT(*) AS stored,
        SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active,
        SUM(CASE WHEN active=1 AND eligible=1 THEN 1 ELSE 0 END) AS candidates,
        SUM(CASE WHEN active=1 AND eligible=1 AND reason LIKE 'security type not proven%' THEN 1 ELSE 0 END) AS unverified,
        SUM(CASE WHEN active=1 AND eligible=0 THEN 1 ELSE 0 END) AS excluded,
        SUM(CASE WHEN active=1 AND eligible=1 AND last_success IS NOT NULL THEN 1 ELSE 0 END) AS ever_downloaded
        FROM market_universe""")[0]
    reasons=rows("""SELECT reason,COUNT(*) AS count FROM market_universe
        WHERE active=1 GROUP BY reason ORDER BY count DESC""")
    sources=rows("""SELECT exchange, COUNT(*) AS count, MAX(updated) AS last_updated
        FROM market_universe WHERE active=1 GROUP BY exchange ORDER BY exchange""")
    return {'summary':summary,'reasons':reasons,'sources':sources,
            'warning':'Directory names are not a security master. Independently reconcile all unverified candidates and missing tickers.'}

@app.get('/api/universe/export.csv')
def universe_export(include_inactive:bool=False):
    where='' if include_inactive else 'WHERE active=1'
    records=rows('SELECT symbol,exchange,name,active,eligible,reason,updated,last_success,failures,last_error '
                 'FROM market_universe '+where+' ORDER BY symbol')
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(['symbol','exchange','name','active','candidate','classification_reason','directory_updated','last_success','failures','last_error'])
    for r in records:
        writer.writerow([r[k] for k in ('symbol','exchange','name','active','eligible','reason','updated','last_success','failures','last_error')])
    return StreamingResponse(iter([output.getvalue()]),media_type='text/csv',
                             headers={'Content-Disposition':'attachment; filename="darvas_universe_audit.csv"'})

def update_universe_from_directories():
    sources=[('NASDAQ','https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt','Symbol','Security Name'),
             ('OTHER','https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt','ACT Symbol','Security Name')]
    records=[]; errors=[]; now=datetime.now(timezone.utc).isoformat(); successful=0
    for exchange,url,symcol,namecol in sources:
        try:
            response=requests.get(url,timeout=25,headers={'User-Agent':'Darvas-Research/0.1'})
            response.raise_for_status()
            lines=list(csv.DictReader(io.StringIO(response.text),delimiter='|'))
            count=0
            for item in lines:
                symbol=(item.get(symcol) or '').strip().upper()
                if not symbol or symbol.startswith('FILE CREATION TIME'): continue
                try: symbol=clean_symbol(symbol)
                except ValueError: continue
                name=(item.get(namecol) or '').strip()[:240]
                eligible,reason=classify_common_equity(symbol,name,item.get('ETF','N')=='Y',item.get('Test Issue','N')=='Y')
                records.append((symbol,exchange,name,now,int(eligible),reason));count+=1
            if count<100: raise ValueError('directory unexpectedly short')
            successful+=1
        except Exception as exc:
            errors.append(exchange+': '+str(exc)[:120])
            records=[r for r in records if r[1]!=exchange]
    if not records: raise RuntimeError('Both symbol directories unavailable: '+'; '.join(errors))
    with closing(conn()) as c:
        for exchange in {r[1] for r in records}:
            c.execute('UPDATE market_universe SET active=0 WHERE exchange=?',(exchange,))
        c.executemany("""INSERT INTO market_universe(symbol,exchange,name,updated,eligible,reason,active)
             VALUES(?,?,?,?,?,?,1) ON CONFLICT(symbol) DO UPDATE SET
             exchange=excluded.exchange,name=excluded.name,updated=excluded.updated,
             eligible=excluded.eligible,reason=excluded.reason,active=1""",records)
        c.commit()
    counts=rows('SELECT COUNT(*) total, SUM(CASE WHEN active=1 AND eligible=1 THEN 1 ELSE 0 END) eligible FROM market_universe')[0]
    return {'listed':counts['total'],'eligible':counts['eligible'] or 0,'errors':errors,'sources_ok':successful,
            'note':'eligible is a broad CANDIDATE pool including unverified equity; use /api/universe/audit'}

@app.post('/api/universe/refresh')
def refresh_universe():
    if not LOCK.acquire(blocking=False): raise HTTPException(409,'Another database update is running')
    try:
        try: result=update_universe_from_directories()
        except RuntimeError as exc: raise HTTPException(502,str(exc)) from None
        backup_after_change()
        return {**result,'oracle_backup':'ok'}
    finally: LOCK.release()

@app.post('/api/download')
def download(req:Download):
    if req.period not in ('1y','2y','5y','10y','max'): raise HTTPException(400,'Invalid period')
    symbols=list(dict.fromkeys(clean_symbol(s) for s in req.symbols))
    if len(symbols)>150: raise HTTPException(400,'Maximum 150 tickers per request; use multiple batches')
    if not LOCK.acquire(blocking=False): raise HTTPException(409,'Another download is running')
    try:
        report=[]
        for symbol in symbols:
            try:
                raw=yf.download(symbol,period=req.period,interval='1d',auto_adjust=False,progress=False,threads=False,timeout=15)
                if raw.empty: raise ValueError('No price data returned')
                if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.get_level_values(0)
                raw=raw.reset_index()
                records=[]
                for _,r in raw.iterrows():
                    dt=pd.Timestamp(r.iloc[0]).strftime('%Y-%m-%d')
                    vals=[float(r[x]) for x in ['Open','High','Low','Close','Volume']]
                    if all(np.isfinite(vals)) and vals[1]>=vals[2] and vals[3]>0: records.append((symbol,dt,*vals))
                with closing(conn()) as c:
                    c.executemany('INSERT OR REPLACE INTO bars(symbol,day,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)',records);c.commit()
                cache_signal(symbol)
                report.append({'symbol':symbol,'saved':len(records)})
            except Exception as e: report.append({'symbol':symbol,'error':str(e)[:200]})
        with closing(conn()) as c:
            c.execute('INSERT INTO runs(created,symbol_count,notes) VALUES(?,?,?)',(datetime.now(timezone.utc).isoformat(),len(symbols),json.dumps(report)));c.commit()
        saved = sum(item.get('saved', 0) for item in report)
        backup = 'skipped_no_new_bars'
        if saved:
            try:
                oracle_backup_database()
                backup = 'ok'
            except Exception:
                import logging
                logging.exception('Oracle backup failed after market download')
                STORAGE_STATE['backup'] = 'failed'
                backup = 'failed_check_render_logs'
        return {'report': report, 'oracle_backup': backup,
                'note': 'Unofficial Yahoo source: availability, terms and bulk-download limits apply. This is NOT a complete market feed.'}
    finally: LOCK.release()
def cache_signal(symbol):
    """Compute a single symbol after its OHLCV commit; scan reads this precomputed result."""
    result=signal(symbol)
    with closing(conn()) as c:
        c.execute('INSERT OR REPLACE INTO screen_cache(symbol,payload,updated) VALUES(?,?,?)',
                  (symbol,json.dumps(result,allow_nan=False),datetime.now(timezone.utc).isoformat()))
        c.commit()
    return result

def excluded_security(symbol):
    # Conservative suffix filter. For reliable classification, use exchange security type metadata.
    entry=rows('SELECT name FROM market_universe WHERE symbol=?',(symbol,))
    name=(entry[0]['name'] if entry else '').lower()
    bad=(' warrant', ' warrants', ' unit ', ' units ', ' right ', ' rights ',
         ' preferred', ' depositary share')
    return any(term in ' '+name+' ' for term in bad) or symbol.endswith(('.WS','.WT','.U'))

@app.post('/api/stock/refresh/{symbol}')
def refresh_stock(symbol:str):
    symbol=clean_symbol(symbol)
    exists=rows('SELECT 1 FROM bars WHERE symbol=? LIMIT 1',(symbol,))
    return download(Download(symbols=[symbol],period='1y' if exists else '10y'))

def sync_coverage():
    return rows("""SELECT COUNT(*) total,
      SUM(CASE WHEN eligible=1 AND active=1 THEN 1 ELSE 0 END) eligible,
      SUM(CASE WHEN eligible=1 AND active=1 AND last_success IS NOT NULL THEN 1 ELSE 0 END) ever_downloaded,
      SUM(CASE WHEN eligible=1 AND active=1 AND last_success IS NULL THEN 1 ELSE 0 END) pending_initial,
      SUM(CASE WHEN eligible=1 AND active=1 AND failures>0 THEN 1 ELSE 0 END) with_failures
      FROM market_universe""")[0]

SYNC_ZONE = ZoneInfo('America/Chicago')

def in_sync_window(local=None):
    """Weekdays 16:00–16:49 Central; reserve time for a final network call/backup."""
    local = local or datetime.now(SYNC_ZONE)
    return local.weekday() < 5 and local.hour == 16 and local.minute < 50

def scheduled_sync_hour(local):
    return 16

@app.get('/api/sync/status')
def sync_status():
    return {'timezone':'America/Chicago','scheduled_hour':f"{scheduled_sync_hour(datetime.now(ZoneInfo('America/Chicago'))):02d}:00",
            'coverage':sync_coverage(),
            'recent_batches':rows('SELECT * FROM sync_log ORDER BY id DESC LIMIT 12'),
            'note':'Automatic weekday 4–5 PM Central processing; new batches stop by 4:50 PM to allow shutdown. No catch-up. Yahoo coverage not guaranteed.'}

@app.post('/api/sync/batch')
def sync_batch(limit:int=6, x_darvas_sync_token:str=Header(default='')):
    expected=os.getenv('DARVAS_SYNC_TOKEN','')
    if not expected or not secrets.compare_digest(x_darvas_sync_token,expected):
        raise HTTPException(403,'Invalid sync token')
    local=datetime.now(SYNC_ZONE)
    if not in_sync_window(local):
        raise HTTPException(409,'Outside permitted Central weekday sync window (4:00–4:50 PM)')
    if limit<1 or limit>8: raise HTTPException(400,'Batch limit must be 1-8')
    if not LOCK.acquire(blocking=False): raise HTTPException(409,'Another database update is running')
    try:
        # Refresh exchange listings at most once per local weekday, including first run.
        latest=rows('SELECT MAX(updated) updated FROM market_universe')[0]['updated']
        refreshed=None
        if not latest or latest[:10]!=local.date().isoformat():
            try: refreshed=update_universe_from_directories()
            except Exception as exc:
                if not rows('SELECT 1 FROM market_universe WHERE active=1 AND eligible=1 LIMIT 1'):
                    raise HTTPException(503,'Universe refresh failed and no cached universe exists') from None
                refreshed={'warning':'Universe refresh failed; using cached eligible listings'}
        # A symbol is attempted at most once per local day, avoiding repeated throttling.
        # Prioritize existing history needing daily updates, then initial 10y backfill.
        today=local.date().isoformat()
        batch=rows("""SELECT u.symbol, u.last_success,
               (SELECT MAX(b.day) FROM bars b WHERE b.symbol=u.symbol) last_day
               FROM market_universe u
               WHERE u.active=1 AND u.eligible=1
                 AND (u.last_attempt IS NULL OR u.last_attempt < ?)
               ORDER BY CASE WHEN EXISTS(SELECT 1 FROM bars b WHERE b.symbol=u.symbol)
                             THEN 0 ELSE 1 END,
                        COALESCE(u.last_attempt,'') ASC, u.symbol ASC LIMIT ?""",(today,limit))
        if not batch:
            backup_after_change() if refreshed else None
            return {'done':True,'coverage':sync_coverage(),'refreshed':refreshed,'attempted':0}
        report=[]
        for item in batch:
            # Never start another Yahoo download after the cutoff.
            if not in_sync_window():
                break
            sym=item['symbol'];last_day=item['last_day']
            try:
                kwargs={'interval':'1d','auto_adjust':False,'progress':False,'threads':False,'timeout':15}
                if last_day:
                    # Small overlap allows revisions of recently published daily bars.
                    start=(pd.Timestamp(last_day)-pd.Timedelta(days=7)).strftime('%Y-%m-%d')
                    raw=yf.download(sym,start=start,**kwargs)
                else:
                    raw=yf.download(sym,period='10y',**kwargs)
                if raw.empty: raise ValueError('No OHLCV returned')
                if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.get_level_values(0)
                records=[]
                for _,r in raw.reset_index().iterrows():
                    day=pd.Timestamp(r.iloc[0]).strftime('%Y-%m-%d')
                    vals=[float(r[x]) for x in ('Open','High','Low','Close','Volume')]
                    if all(np.isfinite(vals)) and vals[1]>=vals[2] and vals[3]>0:
                        records.append((sym,day,*vals))
                if not records: raise ValueError('No valid OHLCV records')
                with closing(conn()) as c:
                    c.executemany('INSERT OR REPLACE INTO bars(symbol,day,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)',records)
                    c.execute('UPDATE market_universe SET last_attempt=?,last_success=?,failures=0,last_error=NULL WHERE symbol=?',(today,today,sym))
                    c.commit()
                cache_signal(sym)
                report.append({'symbol':sym,'saved':len(records)})
            except Exception as exc:
                with closing(conn()) as c:
                    c.execute('UPDATE market_universe SET last_attempt=?,failures=failures+1,last_error=? WHERE symbol=?',(today,str(exc)[:150],sym))
                    c.commit()
                report.append({'symbol':sym,'error':type(exc).__name__})
        succeeded=sum('saved' in r for r in report)
        with closing(conn()) as c:
            c.execute('INSERT INTO sync_log(run_day,batch_offset,attempted,succeeded,errors,backup,created) VALUES(?,?,?,?,?,?,?)',
                      (today,0,len(report),succeeded,len(report)-succeeded,'pending',datetime.now(timezone.utc).isoformat()))
            log_id=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.commit()
        # Backup before returning. If backup fails, preserve an explicit error response.
        backup_after_change()
        with closing(conn()) as c:
            c.execute('UPDATE sync_log SET backup=? WHERE id=?', ('ok',log_id))
            c.commit()
        remaining=rows('SELECT COUNT(*) n FROM market_universe WHERE active=1 AND eligible=1 AND (last_attempt IS NULL OR last_attempt<?)',(today,))[0]['n']
        return {'done':remaining==0,'attempted':len(batch),'succeeded':succeeded,
                'failed':len(batch)-succeeded,'remaining_today':remaining,'coverage':sync_coverage(),
                'oracle_backup':'ok','refreshed':refreshed,'report':report}
    finally: LOCK.release()

@app.get('/api/scan')
def scan():
    # Cached screening avoids recalculating thousands of 10-year histories on every page view.
    cached=rows('''SELECT s.symbol,s.payload FROM screen_cache s LEFT JOIN market_universe u ON u.symbol=s.symbol
                   WHERE u.active=1 AND u.eligible=1 ORDER BY s.symbol''')
    results=[]
    for item in cached:
        try:
            if item['symbol'] not in ('SPY','QQQ'):
                results.append(json.loads(item['payload']))
        except (ValueError, TypeError): continue
    # Existing symbols from before this upgrade are lazily cached, bounded per request.
    uncached=rows("""SELECT DISTINCT b.symbol FROM bars b LEFT JOIN screen_cache s ON s.symbol=b.symbol
                    WHERE s.symbol IS NULL AND EXISTS (SELECT 1 FROM market_universe u WHERE u.symbol=b.symbol AND u.active=1 AND u.eligible=1) ORDER BY b.symbol LIMIT 100""")
    for item in uncached:
        sym=item['symbol']
        if sym in ('SPY','QQQ') or excluded_security(sym): continue
        try: results.append(cache_signal(sym))
        except Exception: continue
    darvas=sorted([x for x in results if x.get('darvas_watch')],key=lambda x:(x.get('rvol20') or 0),reverse=True)[:20]
    recovery=sorted([x for x in results if x.get('recovery_watch')],key=lambda x:(x.get('rvol20') or 0),reverse=True)
    discovery=sorted([x for x in results if x.get('recovery_discovery')],key=lambda x:(x.get('hma_slope3_pct') or 0),reverse=True)
    return {'scanned':len(results),'darvas':darvas,'recovery':recovery,'recovery_discovery':discovery,
            'all':results[:250],'total_results':len(results),'disclaimer':'Cached independent provisional screens. Data quality, universe completeness and confirmed Darvas pivots are not validated.'}
# V7.5 read-only paginated research scan. Does not mutate bars, caches or Oracle snapshots.
@app.get('/api/v75/scan')
def v75_scan(offset: int = 0, limit: int = 20):
    if offset < 0 or not 1 <= limit <= 30:
        raise HTTPException(400, 'offset must be >= 0 and limit between 1 and 30')
    # Only symbols with stored history and active eligible universe classification.
    # A symbol without enough history is reported rather than silently omitted.
    total = rows("""SELECT COUNT(*) AS n FROM (
        SELECT DISTINCT b.symbol FROM bars b JOIN market_universe u ON u.symbol=b.symbol
        WHERE u.active=1 AND u.eligible=1 AND b.symbol NOT IN ('SPY','QQQ')
    )""")[0]['n']
    symbols = rows("""SELECT DISTINCT b.symbol FROM bars b
        JOIN market_universe u ON u.symbol=b.symbol
        WHERE u.active=1 AND u.eligible=1 AND b.symbol NOT IN ('SPY','QQQ')
        ORDER BY b.symbol LIMIT ? OFFSET ?""", (limit, offset))
    output=[]
    for item in symbols:
        symbol=item['symbol']
        try:
            df=history(symbol)
            if len(df)<65:
                output.append({'symbol':symbol,'bars':len(df),'status':'DATA_INCOMPLETE',
                               'classic':{'stage':'DATA_INCOMPLETE','watch':False,'score':0},
                               'recovery':{'stage':'DATA_INCOMPLETE','watch':False,'discovery':False,'score':0}})
                continue
            d=indicators(df)
            latest=d.iloc[-1]
            output.append({'symbol':symbol,'bars':len(d),'status':'SHADOW_RESEARCH_ONLY',
                           'date':str(latest['day']),
                           'price':round(float(latest['close']),3),
                           'data_age_days':(datetime.now(timezone.utc).date()-pd.Timestamp(latest['day']).date()).days,
                           'classic':v75_classic(d),'recovery':v75_recovery(d)})
        except Exception as exc:
            import logging
            logging.exception('V7.5 shadow scan failed for %s',symbol)
            output.append({'symbol':symbol,'status':'CALCULATION_ERROR',
                           'error_type':type(exc).__name__})
    return {'version':V75_ENGINE_VERSION,'mode':'SHADOW_RESEARCH_ONLY',
            'offset':offset,'limit':limit,'total_stored_eligible':total,
            'processed':len(output),'next_offset':offset+len(output) if offset+len(output)<total else None,
            'results':output,
            'warning':'Read-only, stored OHLCV only. Universe coverage and data freshness are not guaranteed. No trading recommendations.'}

@app.get('/api/prices/{symbol}')
def prices(symbol:str):
    symbol=clean_symbol(symbol); d=history(symbol)
    return {'symbol':symbol,'bars':d.tail(1000).to_dict(orient='records') if len(d) else []}
@app.post('/api/portfolio/import')
async def portfolio_import(file:UploadFile=File(...)):
    if not file.filename.lower().endswith('.csv'): raise HTTPException(400,'Upload a CSV file')
    b=await file.read(2_000_001)
    if len(b)>2_000_000: raise HTTPException(400,'CSV max 2MB')
    try:
        text=b.decode('utf-8-sig'); reader=csv.DictReader(io.StringIO(text))
        data=[]
        for row in reader:
            norm={str(k).strip().lower().replace(' ','_'):v for k,v in row.items()}
            s=clean_symbol(norm.get('symbol') or norm.get('ticker') or '')
            q=float(norm.get('quantity') or norm.get('shares') or '')
            cb=float(norm.get('cost_basis') or norm.get('average_cost') or norm.get('cost') or '')
            if not all(np.isfinite([q,cb])) or q<0 or cb<0: raise ValueError('Invalid quantity or cost')
            horizon=(norm.get('horizon') or 'position').lower()
            if horizon not in ('swing','position','long-term'): horizon='position'
            data.append((s,q,cb,horizon,norm.get('thesis','')[:2000]))
        if not data: raise ValueError('No positions found')
    except (ValueError, UnicodeError, csv.Error, KeyError, TypeError) as e:
        raise HTTPException(400, str(e)) from None
    if not LOCK.acquire(blocking=False):
        raise HTTPException(409, 'Another database update is running; please retry')
    try:
        with closing(conn()) as c:
            c.execute('DELETE FROM positions')
            c.executemany('INSERT INTO positions(symbol,quantity,cost_basis,horizon,thesis) VALUES(?,?,?,?,?)',data)
            c.commit()
        backup_after_change()
        return {'imported':len(data), 'oracle_backup':'ok',
                'note':'Replaces saved positions; no brokerage connection or order verification.'}
    finally:
        LOCK.release()
@app.get('/api/portfolio')
def portfolio():
    out=[]
    for p in rows('SELECT * FROM positions ORDER BY symbol'):
        d=history(p['symbol']); latest=float(d.iloc[-1]['close']) if len(d) else None
        p['price']=latest;p['price_date']=str(d.iloc[-1]['day']) if len(d) else None
        p['value']=round(latest*p['quantity'],2) if latest is not None else None
        p['pnl']=round((latest-p['cost_basis'])*p['quantity'],2) if latest is not None else None
        p['order_protection']='UNKNOWN — no broker orders connected'
        out.append(p)
    return {'positions':out}
@app.get('/api/notes/{symbol}')
def getnote(symbol:str): return {'symbol':clean_symbol(symbol),'note':(rows('SELECT text FROM notes WHERE symbol=?',(clean_symbol(symbol),)) or [{'text':''}])[0]['text']}
@app.post('/api/notes')
def putnote(note:Note):
    s=clean_symbol(note.symbol)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(409, 'Another database update is running; please retry')
    try:
        with closing(conn()) as c:
            c.execute('INSERT OR REPLACE INTO notes(symbol,text,updated) VALUES(?,?,?)',
                      (s,note.text[:10000],datetime.now(timezone.utc).isoformat()))
            c.commit()
        backup_after_change()
        return {'saved':True, 'oracle_backup':'ok'}
    finally:
        LOCK.release()
@app.get('/api/research/{symbol}')
def research(symbol:str):
    s=clean_symbol(symbol); sig=signal(s); return {'symbol':s,'signal':sig,'brief':f'Research {s} with current cited sources. Analyze earnings, debt, cash flow, SEC filings, catalysts, risks, bull/bear cases, Darvas and early recovery. Historical local screen: {json.dumps(sig)}. This is not a verified trading signal.'}
@app.post('/api/alerts/test')
def test_alert(a:Alert):
    s=clean_symbol(a.symbol)
    token=os.getenv('TELEGRAM_BOT_TOKEN'); chat=os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat: raise HTTPException(400,'Telegram credentials not configured. See README.')
    if a.severity not in ('INFO','IMPORTANT','CRITICAL'): raise HTTPException(400,'Invalid severity')
    message=f'[DARVAS V7.4 TEST / RESEARCH ONLY] {a.severity} {s}: {a.message[:400]}'
    try:
        resp=requests.post(f'https://api.telegram.org/bot{token}/sendMessage',json={'chat_id':chat,'text':message},timeout=12)
        resp.raise_for_status(); ok=bool(resp.json().get('ok'))
    except Exception as e: raise HTTPException(502,f'Telegram API error: {str(e)[:160]}')
    if not LOCK.acquire(blocking=False):
        raise HTTPException(409, 'Another database update is running; please retry')
    try:
        with closing(conn()) as c:
            c.execute('INSERT INTO alerts(created,symbol,severity,message,delivered) VALUES(?,?,?,?,?)',
                      (datetime.now(timezone.utc).isoformat(),s,a.severity,message,int(ok)))
            c.commit()
        backup_after_change()
        return {'telegram_api_accepted':ok,'phone_received':'NOT_VERIFIED',
                'oracle_backup':'ok'}
    finally:
        LOCK.release()
@app.get('/api/alerts')
def alerts(): return {'alerts':rows('SELECT * FROM alerts ORDER BY id DESC LIMIT 100')}
@app.get('/api/backtest/{symbol}')
def backtest(symbol:str):
    s=clean_symbol(symbol);d=history(s)
    if len(d)<100: return {'symbol':s,'status':'DATA_INCOMPLETE','count':len(d)}
    d=indicators(d); trades=[]
    for i in range(65,len(d)-20):
        prev=d.iloc[i-20:i]; now=d.iloc[i]
        if float(now.close)>float(prev.high.max()) and (float(prev.high.max())-float(prev.low.min()))/float(prev.high.max())<=.15:
            future=float(d.iloc[i+20].close)/float(now.close)-1
            trades.append({'day':str(now.day),'entry':round(float(now.close),2),'return_20d_pct':round(100*future,2)})
    return {'symbol':s,'signals':len(trades),'mean_20d_pct':round(float(np.mean([x['return_20d_pct'] for x in trades])),2) if trades else None,'examples':trades[-25:],
        'disclaimer':'Exploratory forward-return study, NOT a tradable or point-in-time-certified backtest. Signals overlap; ignores execution, fees, delistings, and corporate action completeness.'}

# Oracle Object Storage connectivity test. Does not modify market data.
def oracle_client():
    import oci
    required = (
        'OCI_REGION', 'OCI_BUCKET_NAME', 'OCI_NAMESPACE',
        'OCI_TENANCY_OCID', 'OCI_USER_OCID', 'OCI_FINGERPRINT', 'OCI_PRIVATE_KEY',
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError('Missing Render environment variables: ' + ', '.join(missing))

    private_key = os.environ['OCI_PRIVATE_KEY'].strip()
    # Support both multiline PEM and PEM copied with literal escaped newlines.
    private_key = private_key.replace('\\r\\n', '\n').replace('\\n', '\n').strip() + '\n'
    config = {
        'user': os.environ['OCI_USER_OCID'].strip(),
        'tenancy': os.environ['OCI_TENANCY_OCID'].strip(),
        'fingerprint': os.environ['OCI_FINGERPRINT'].strip(),
        'region': os.environ['OCI_REGION'].strip(),
        'key_content': private_key,
    }
    oci.config.validate_config(config)
    return oci.object_storage.ObjectStorageClient(config)


# Rolling snapshot: the same object key is overwritten after successful updates.
# SQLite's backup API makes a transactionally consistent copy even if the DB is in use.
ORACLE_DB_OBJECT = 'snapshots/darvas.db'
STORAGE_STATE = {'restore': 'not_attempted', 'backup': 'not_attempted'}

def oracle_backup_database():
    import tempfile
    with tempfile.TemporaryDirectory(prefix='darvas-snapshot-') as folder:
        snapshot = Path(folder) / 'darvas.db'
        with closing(conn()) as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
        with snapshot.open('rb') as stream:
            oracle_client().put_object(
                os.environ['OCI_NAMESPACE'].strip(),
                os.environ['OCI_BUCKET_NAME'].strip(),
                ORACLE_DB_OBJECT,
                stream,
                content_type='application/octet-stream',
            )
    STORAGE_STATE['backup'] = 'ok'

def backup_after_change():
    """Persist committed changes and clearly report failures without leaking OCI secrets."""
    try:
        oracle_backup_database()
    except Exception:
        import logging
        logging.exception('Oracle backup failed after database change')
        STORAGE_STATE['backup'] = 'failed'
        raise HTTPException(
            status_code=503,
            detail={
                'local_change_saved': True,
                'oracle_backup': 'failed',
                'message': 'Change was saved locally but Oracle backup failed. '
                           'Check Render logs privately. Do not redeploy until resolved.',
            },
        ) from None

def oracle_restore_database():
    import tempfile
    import oci
    # Never overwrite an existing local DB, which could contain newer unsaved data.
    if DB.exists() and DB.stat().st_size:
        try:
            with closing(sqlite3.connect(DB)) as local:
                count = local.execute('SELECT COUNT(*) FROM bars').fetchone()[0]
            if count:
                STORAGE_STATE['restore'] = 'local_database_has_history'
                return
        except sqlite3.DatabaseError:
            # An invalid local file must not be trusted over a valid snapshot.
            pass
    try:
        result = oracle_client().get_object(
            os.environ['OCI_NAMESPACE'].strip(),
            os.environ['OCI_BUCKET_NAME'].strip(),
            ORACLE_DB_OBJECT,
        )
    except oci.exceptions.ServiceError as exc:
        if exc.status == 404:
            STORAGE_STATE['restore'] = 'no_snapshot_yet'
            return
        STORAGE_STATE['restore'] = 'failed'
        raise
    with tempfile.NamedTemporaryFile(dir=DATA, suffix='.db', delete=False) as temp:
        temporary_path = Path(temp.name)
    try:
        with temporary_path.open('wb') as output:
            for chunk in result.data.raw.stream(1024 * 1024, decode_content=False):
                output.write(chunk)
        with closing(sqlite3.connect(temporary_path)) as check:
            integrity = check.execute('PRAGMA integrity_check').fetchone()[0]
            if integrity != 'ok':
                raise RuntimeError('Oracle snapshot failed SQLite integrity check')
            table_names = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'bars' not in table_names:
                raise RuntimeError('Oracle snapshot has no bars table')
        os.replace(temporary_path, DB)
        STORAGE_STATE['restore'] = 'ok'
    finally:
        temporary_path.unlink(missing_ok=True)

# Restore before the first local DB is created. Fail closed if a remote snapshot
# exists but cannot be fetched, to avoid overwriting it with an empty database.
try:
    oracle_restore_database()
except Exception:
    import logging
    logging.exception('Oracle restore failed; refusing to start to protect saved history')
    raise
init()


@app.post('/api/oci/test')
def test_oracle_storage():
    import uuid
    object_name = 'connection-tests/darvas-' + uuid.uuid4().hex + '.txt'
    try:
        client = oracle_client()
        namespace = os.environ['OCI_NAMESPACE'].strip()
        bucket = os.environ['OCI_BUCKET_NAME'].strip()
        payload = b'Darvas V7.4 Oracle Object Storage connection test'
        client.put_object(namespace, bucket, object_name, payload)
        result = client.get_object(namespace, bucket, object_name)
        if result.data.content != payload:
            raise RuntimeError('Read-back did not match the uploaded test object')
        client.delete_object(namespace, bucket, object_name)
        return {
            'connected': True, 'upload': 'ok', 'read': 'ok',
            'delete': 'ok', 'bucket': bucket,
            'note': 'Connectivity test only; backups follow downloads, portfolio imports, notes and saved alert records.',
        }
    except Exception as exc:
        # Never expose SDK request headers, OCIDs, or private-key material to the browser.
        raise HTTPException(status_code=503, detail={
            'connected': False,
            'error_type': type(exc).__name__,
            'message': 'Oracle test failed. Check Render logs privately and verify OCI credentials and bucket permissions.',
        }) from None

@app.get('/api/storage/status')
def storage_status():
    """Non-secret local database and Oracle backup/restore status."""
    return {
        'oracle_restore': STORAGE_STATE['restore'],
        'oracle_backup': STORAGE_STATE['backup'],
        'database_exists': DB.exists(),
        'database_size_bytes': DB.stat().st_size if DB.exists() else 0,
        'stored_symbols': len(rows('SELECT DISTINCT symbol FROM bars')),
        'snapshot_object': ORACLE_DB_OBJECT,
        'note': 'Backup status reflects this running process; it does not independently verify remote snapshot contents.'
    }

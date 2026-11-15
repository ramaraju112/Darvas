"""Darvas V7.4 integrated browser MVP. Research only, no trading."""
from pathlib import Path
from datetime import datetime, timezone
from contextlib import closing
import csv, io, json, os, sqlite3, threading, time
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
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
        CREATE TABLE IF NOT EXISTS notes(symbol TEXT PRIMARY KEY, text TEXT, updated TEXT);'''); c.commit()
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

def signal(symbol):
    df=history(symbol)
    if len(df)<65: return {'symbol':symbol,'status':'DATA_INCOMPLETE','bars':len(df),'reason':'At least 65 daily bars required for screening'}
    d=indicators(df); last=d.iloc[-1]; base=d.iloc[-20:]; price=float(last['close']); lo=float(base.low.min()); hi=float(base.high.max())
    depth=(hi-lo)/max(hi,0.01)
    breakout=price>=float(d.high.iloc[-21:-1].max()) and depth<=.15
    prev120=d.iloc[-140:-20] if len(d)>=140 else d.iloc[:-20]
    drawdown=(float(prev120.high.max())-lo)/max(float(prev120.high.max()),0.01) if len(prev120) else 0
    slope=float(last['hma_slope3']) if pd.notna(last['hma_slope3']) else None
    recovery=drawdown>=.20 and depth<=.18 and slope is not None and slope>=-.01
    stage='DEVELOPING_WATCH' if recovery else 'NONE'
    if breakout: stage='BREAKOUT_WATCH'
    return {'symbol':symbol,'status':'RESEARCH_ONLY','date':str(last.day),'price':round(price,3),'bars':len(d),
        'darvas_watch':bool(breakout),'recovery_watch':bool(recovery),'stage':stage,'base_depth_pct':round(depth*100,2),
        'prior_decline_pct':round(drawdown*100,2),'hma38':round(float(last.hma38),3) if pd.notna(last.hma38) else None,
        'hma_slope3_pct':round(slope*100,2) if slope is not None else None,
        'atr14':round(float(last.atr14),3) if pd.notna(last.atr14) else None,
        'rvol20':round(float(last.rvol20),2) if pd.notna(last.rvol20) else None,
        'data_age_days':(datetime.now(timezone.utc).date()-pd.Timestamp(last.day).date()).days,
        'reason':'Simplified screening heuristic; NOT confirmed V7.4 pivots/RS/box validation'}

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
@app.get('/api/scan')
def scan():
    syms=[r['symbol'] for r in rows('SELECT DISTINCT symbol FROM bars ORDER BY symbol') if r['symbol'] not in ('SPY','QQQ')]
    results=[signal(s) for s in syms]
    darvas=sorted([x for x in results if x.get('darvas_watch')],key=lambda x:(x.get('rvol20') or 0),reverse=True)[:20]
    recovery=sorted([x for x in results if x.get('recovery_watch')],key=lambda x:(x.get('prior_decline_pct') or 0),reverse=True)
    return {'scanned':len(syms),'darvas':darvas,'recovery':recovery,'all':results,'disclaimer':'Exploratory heuristics only; full confirmed pivot, relative-strength and historical replay logic is not yet implemented.'}
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
        with closing(conn()) as c:
            c.execute('DELETE FROM positions')
            c.executemany('INSERT INTO positions(symbol,quantity,cost_basis,horizon,thesis) VALUES(?,?,?,?,?)',data);c.commit()
        return {'imported':len(data),'note':'Replaces local positions. CSV is stored as parsed positions, not uploaded file. No brokerage connection or order verification.'}
    except Exception as e: raise HTTPException(400,str(e))
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
    with closing(conn()) as c:
        c.execute('INSERT OR REPLACE INTO notes(symbol,text,updated) VALUES(?,?,?)',(s,note.text[:10000],datetime.now(timezone.utc).isoformat()));c.commit()
    return {'saved':True}
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
    with closing(conn()) as c:
        c.execute('INSERT INTO alerts(created,symbol,severity,message,delivered) VALUES(?,?,?,?,?)',(datetime.now(timezone.utc).isoformat(),s,a.severity,message,int(ok)));c.commit()
    return {'telegram_api_accepted':ok,'phone_received':'NOT_VERIFIED'}
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
            'note': 'Connectivity test only; market database backup is handled by /api/download.',
        }
    except Exception as exc:
        # Never expose SDK request headers, OCIDs, or private-key material to the browser.
        raise HTTPException(status_code=503, detail={
            'connected': False,
            'error_type': type(exc).__name__,
            'message': 'Oracle test failed. Check Render logs privately and verify OCI credentials and bucket permissions.',
        }) from None

"""Research-only Darvas portfolio engine. No broker order placement."""
import csv, io, re, sqlite3, hashlib, datetime as dt
from pathlib import Path
import pandas as pd

SCHEMA = '''
CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY, kind TEXT, digest TEXT UNIQUE, filename TEXT, imported_at TEXT, snapshot_at TEXT);
CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY, qty REAL, avg_cost REAL, schwab_price REAL, asset_type TEXT, snapshot_at TEXT);
CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY, symbol TEXT, status TEXT, action TEXT, qty REAL, price TEXT, fill_price REAL, placed_at TEXT, imported_at TEXT);
CREATE TABLE IF NOT EXISTS signals(symbol TEXT PRIMARY KEY, name TEXT, asof TEXT, status TEXT, close REAL, box_top REAL, box_bottom REAL, volume_ratio REAL, avg_dollar_volume20 REAL, strategy TEXT);
CREATE TABLE IF NOT EXISTS stops(symbol TEXT PRIMARY KEY, approved_stop REAL, updated_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, symbol TEXT, action TEXT, reason TEXT, calculated_at TEXT, signature TEXT UNIQUE);
'''
def db(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(path,check_same_thread=False,timeout=20)
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript(SCHEMA)
    return con

def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def number(x):
    if x is None: return None
    s=str(x).strip().replace('$','').replace(',','').replace('%','')
    if s in ('','--','N/A','nan'): return None
    try: return float(s.replace('(','-').replace(')',''))
    except ValueError: return None

def parse_csv(data):
    txt=data.decode('utf-8-sig',errors='replace')
    rows=list(csv.reader(io.StringIO(txt)))
    start=next((i for i,r in enumerate(rows) if r and (r[0].strip()=='Symbol')),None)
    if start is None: raise ValueError('Could not locate a Symbol header row')
    return pd.read_csv(io.StringIO('\n'.join(','.join('"'+v.replace('"','""')+'"' for v in row) for row in rows[start:])),dtype=str).fillna('')

def _import_record(con,kind,data,filename,snapshot):
    digest=hashlib.sha256(data).hexdigest()
    if con.execute('SELECT 1 FROM imports WHERE digest=?',(digest,)).fetchone():return False
    con.execute('INSERT INTO imports(kind,digest,filename,imported_at,snapshot_at) VALUES (?,?,?,?,?)',(kind,digest,filename,now(),snapshot))
    return True

def import_positions(con,data,filename):
    df=parse_csv(data)
    required=['Symbol','Qty (Quantity)','Cost/Share']
    if any(c not in df for c in required):raise ValueError('Not a supported Schwab Positions CSV')
    text=data.decode('utf-8-sig',errors='replace')
    match=re.search(r'as of (.+?)"',text)
    snapshot=match.group(1) if match else now()
    parsed=[]
    for _,r in df.iterrows():
        sym=str(r['Symbol']).strip().upper();qty=number(r['Qty (Quantity)'])
        if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,12}',sym) or qty is None or qty<=0:continue
        parsed.append((sym,qty,number(r['Cost/Share']),number(r.get('Price')),str(r.get('Asset Type','')),snapshot))
    if not parsed:raise ValueError('No positive share positions found')
    with con:
        if not _import_record(con,'positions',data,filename,snapshot):return 0,'duplicate'
        con.execute('DELETE FROM positions')
        con.executemany('INSERT INTO positions VALUES (?,?,?,?,?,?)',parsed)
    return len(parsed),'imported'

def import_orders(con,data,filename):
    df=parse_csv(data)
    required=['Symbol','Status','Action','Quantity|Face Value','Order Number']
    if any(c not in df for c in required):raise ValueError('Not a supported Schwab Order Status CSV')
    parsed=[]
    for _,r in df.iterrows():
        oid=str(r['Order Number']).strip()
        if not oid:continue
        parsed.append((oid,str(r['Symbol']).strip().upper(),str(r['Status']).strip(),str(r['Action']).strip(),number(str(r['Quantity|Face Value']).split(' ')[0]),str(r.get('Price','')),number(r.get('Fill Price')),str(r.get('Time and Date(ET)','')),now()))
    if not parsed:raise ValueError('No order records found')
    with con:
        if not _import_record(con,'orders',data,filename,now()):return 0,'duplicate'
        con.executemany('INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET status=excluded.status,qty=excluded.qty,fill_price=excluded.fill_price,imported_at=excluded.imported_at',parsed)
    return len(parsed),'imported'

def import_signals(con,data,filename):
    df=pd.read_csv(io.BytesIO(data)).fillna('')
    needed=['symbol','asof','status','close','box_top','box_bottom']
    if any(c not in df for c in needed):raise ValueError('Expected V6.3 scan_all.csv or signals.csv')
    parsed=[]
    for _,r in df.iterrows():
        sym=str(r['symbol']).upper().strip()
        if not sym:continue
        parsed.append((sym,str(r.get('name','')),str(r['asof']),str(r['status']),number(r['close']),number(r['box_top']),number(r['box_bottom']),number(r.get('volume_ratio')),number(r.get('avg_dollar_volume20')),str(r.get('strategy',''))))
    with con:
        if not _import_record(con,'signals',data,filename,str(df['asof'].max())):return 0,'duplicate'
        con.execute('DELETE FROM signals')
        con.executemany('INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET name=excluded.name,asof=excluded.asof,status=excluded.status,close=excluded.close,box_top=excluded.box_top,box_bottom=excluded.box_bottom,volume_ratio=excluded.volume_ratio,avg_dollar_volume20=excluded.avg_dollar_volume20,strategy=excluded.strategy',parsed)
    return len(parsed),'imported'

def read(con,sql,params=()):return pd.read_sql_query(sql,con,params=params)

def actions(con):
    """Conservative research classification; NOT an original-book-certified signal engine."""
    p=read(con,'SELECT * FROM positions');s=read(con,'SELECT * FROM signals');o=read(con,'SELECT * FROM orders');st=read(con,'SELECT * FROM stops')
    pos={r.symbol:r for r in p.itertuples()};sig={r.symbol:r for r in s.itertuples()};stops={r.symbol:r.approved_stop for r in st.itertuples()}
    active=o[o.status.str.lower().str.contains('open|working|pending|partially filled',regex=True,na=False)] if not o.empty else o
    out=[]
    for sym,r in pos.items():
        z=sig.get(sym);approved=stops.get(sym)
        working=active[(active.symbol==sym)&(active.action.str.lower().str.contains('sell',na=False))] if not active.empty else active
        stop_order=working[working.price.str.lower().str.contains('stop',na=False)] if not working.empty else working
        if z is None: action,reason='REVIEW','No matching market scan; cannot validate box or stop'
        elif approved is not None and z.close is not None and z.close<=approved:action,reason='EXIT REVIEW','Scan close at/below approved stop; verify actual market and Schwab order execution'
        elif z.box_bottom is None or z.box_top is None:action,reason='REVIEW','Missing box levels'
        elif not stop_order.empty:action,reason='HOLD / VERIFY STOP','Schwab export reports a working sell-stop; verify quantity and price'
        elif approved is None:action,reason='STOP REVIEW','No approved protective stop recorded; consider a protective order after validation'
        elif z.status=='HIGHER_BOX':action,reason='HOLD / ADD REVIEW','Higher-box research status; validate new confirmed breakout before adding'
        else:action,reason='HOLD / REVIEW','Review approved stop and current market data'
        out.append(dict(symbol=sym,shares=r.qty,cost=r.avg_cost,scan_close=getattr(z,'close',None),box_top=getattr(z,'box_top',None),box_bottom=getattr(z,'box_bottom',None),approved_stop=approved,action=action,reason=reason,scan_asof=getattr(z,'asof',None)))
    return pd.DataFrame(out,columns=['symbol','shares','cost','scan_close','box_top','box_bottom','approved_stop','action','reason','scan_asof'])

def opportunities(con):
    d=read(con,"SELECT * FROM signals WHERE status='BREAKOUT' AND close>0 AND box_top>0 AND box_bottom>0 AND close>box_top")
    if d.empty:return d
    d['extension_pct']=(d.close/d.box_top-1)*100
    d['box_risk_pct']=(d.close-d.box_bottom)/d.close*100
    d=d[(d.extension_pct<=5)&(d.box_risk_pct>0)&(d.box_risk_pct<=12)&(d.avg_dollar_volume20>=5e6)&(d.volume_ratio>=1.5)]
    return d.sort_values(['volume_ratio','extension_pct'],ascending=[False,True])

def log_actions(con,df):
    if df.empty:return
    with con:
        for r in df.itertuples():
            key=hashlib.sha256(f'{r.symbol}|{r.action}|{r.reason}|{r.scan_asof}|{r.approved_stop}'.encode()).hexdigest()
            con.execute('INSERT OR IGNORE INTO decisions(symbol,action,reason,calculated_at,signature) VALUES (?,?,?,?,?)',(r.symbol,r.action,r.reason,now(),key))

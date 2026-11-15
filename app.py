


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
            'note': 'Test only; database backup is not enabled yet.',
        }
    except Exception as exc:
        # Never expose SDK request headers, OCIDs, or private-key material to the browser.
        raise HTTPException(status_code=503, detail={
            'connected': False,
            'error_type': type(exc).__name__,
            'message': 'Oracle test failed. Check Render logs privately and verify OCI credentials and bucket permissions.',
        }) from None






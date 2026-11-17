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

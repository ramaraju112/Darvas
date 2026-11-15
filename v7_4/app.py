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
init()

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

import sqlite3
from core import db,import_positions,import_orders,import_signals,actions

def test_imports(tmp_path):
    c=db(tmp_path/'test.db')
    positions=b'"Positions for account Individual ...712 as of 08:38 AM ET, 2026/11/08"\n\n"Symbol","Qty (Quantity)","Cost/Share","Price","Asset Type"\n"ORCL","100","113.06","116.10","Equity"\n"Positions Total","--","--","--","--"\n'
    orders=b'Symbol,Status,Action,Quantity|Face Value,Order Number,Price,Fill Price\nORCL,Filled,Buy,100 Shares,123,Limit $113.12,$113.06\n'
    scan=b'symbol,name,asof,status,close,box_top,box_bottom,volume_ratio,avg_dollar_volume20,strategy\nORCL,Oracle,2026-11-06,BREAKOUT,116.10,115,110,2.2,100000000,CLASSIC_BOX_RESEARCH\n'
    assert import_positions(c,positions,'p.csv')[0]==1
    assert import_positions(c,positions,'p.csv')[1]=='duplicate'
    assert import_orders(c,orders,'o.csv')[0]==1
    assert import_signals(c,scan,'s.csv')[0]==1
    a=actions(c)
    assert len(a)==1 and a.iloc[0].action=='STOP REVIEW'

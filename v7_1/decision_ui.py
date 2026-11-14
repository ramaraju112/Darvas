"""Explanatory research labels for the V7.1 UI; never sends broker orders."""
import pandas as pd

def enrich_positions(df):
    d=df.copy()
    d['floor_distance_pct']=(pd.to_numeric(d.scan_close,errors='coerce')/pd.to_numeric(d.box_bottom,errors='coerce')-1)*100
    d['top_distance_pct']=(pd.to_numeric(d.scan_close,errors='coerce')/pd.to_numeric(d.box_top,errors='coerce')-1)*100
    labels=[]; explanations=[]; ranks=[]
    for r in d.itertuples():
        if pd.isna(r.scan_close) or pd.isna(r.box_bottom) or pd.isna(r.box_top):
            label,reason,rank='DATA REVIEW','Market data or box reference is missing. Do not infer a trade action.',1
        elif r.floor_distance_pct<0:
            label,reason,rank='RISK REVIEW','Snapshot price is below the recorded box floor. Check the current quote, validity of the box, and actual broker orders promptly. This alone is not an automatic sell instruction.',0
        elif pd.notna(r.approved_stop) and r.scan_close<=r.approved_stop:
            label,reason,rank='STOP TRIGGER REVIEW','Snapshot price is at or below the recorded approved stop. Confirm whether any protective order executed at Schwab.',0
        elif pd.isna(r.approved_stop):
            label,reason,rank='STOP NOT RECORDED','No approved stop is recorded in this app. Verify whether one exists at Schwab and assess protection before considering additional exposure.',1
        elif r.top_distance_pct>0:
            label,reason,rank='HOLD / BREAKOUT REVIEW','Snapshot is above the recorded box top. Verify breakout confirmation, current price, risk and existing exposure before considering any add.',2
        else:
            label,reason,rank='HOLD / MONITOR REVIEW','Price is within the recorded box and a stop is recorded. Recheck fresh market data and any working orders.',3
        labels.append(label);explanations.append(reason);ranks.append(rank)
    d['decision_label']=labels;d['decision_explanation']=explanations;d['priority_rank']=ranks
    d['priority']=d.priority_rank.map(lambda n:'HIGH' if n==0 else ('REVIEW' if n==1 else 'MONITOR'))
    return d

def enrich_opportunities(df):
    d=df.copy()
    d['research_label']='BREAKOUT RESEARCH'
    d['research_note']='Verify box history, fresh price, volume and entry risk'
    return d.sort_values(['volume_ratio','extension_pct'],ascending=[False,True])

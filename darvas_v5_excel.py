#!/usr/bin/env python3
"""Turn existing V4 scan/monitor CSVs into a readable Excel workbook; no invented signals."""
import argparse
from pathlib import Path
import pandas as pd

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mode',choices=['scan','monitor'],required=True)
    p.add_argument('--out',default='')
    a=p.parse_args()
    input_file={'scan':'darvas_v4_reports/darvas_v4_scan_diagnostics.csv','monitor':'darvas_v4_monitor_results.csv'}[a.mode]
    path=Path(input_file)
    if not path.exists(): raise SystemExit(f'Missing report {path}')
    df=pd.read_csv(path)
    out=Path(a.out or f'darvas_v5_{a.mode}_report.xlsx')
    with pd.ExcelWriter(out,engine='xlsxwriter',datetime_format='yyyy-mm-dd hh:mm') as writer:
        sheet='SCAN - All 400' if a.mode=='scan' else 'MONITOR - Holdings'
        df.to_excel(writer,sheet_name=sheet,index=False)
        book=writer.book
        ws=writer.sheets[sheet]
        ws.freeze_panes(1,2)
        ws.autofilter(0,0,max(1,len(df)),max(0,len(df.columns)-1))
        header=book.add_format({'bold':True,'font_color':'white','bg_color':'#17365D','text_wrap':True,'valign':'vcenter'})
        ws.set_row(0,35,header)
        for idx,name in enumerate(df.columns):
            ws.set_column(idx,idx,min(48,max(14,len(str(name))+4)))
        if a.mode=='scan':
            qualified=df[df['status'].astype(str).eq('QUALIFIED')].copy() if 'status' in df else df.iloc[:0]
            qualified.to_excel(writer,sheet_name='BUY - Review',index=False)
            bw=writer.sheets['BUY - Review'];bw.freeze_panes(1,1)
            for idx,name in enumerate(qualified.columns):bw.set_column(idx,idx,min(48,max(14,len(str(name))+4)))
            notes=[('Purpose','400 ticker universe, historical daily breakout screen; not trade orders'),('Qualified','V4 diagnostic QUALIFIED is not V5 fully validated BUY CANDIDATE'),('Data','Yahoo Finance data may be delayed, stale, incomplete or revised'),('Timing','Confirmed breakout uses completed daily bars only'),('Add-ons','Higher confirmed box + fresh daily close breakout + 1.5x volume + rising HMA38 + max 3% extension; manual review only'),('Stop','Broker-held stop remains essential; scanner never places orders'),('Backtest','Multi-box add-on and stop-ratchet logic NOT backtested; research alerts only')]
        else:
            notes=[('Purpose','Existing holdings only; not the 400 ticker universe'),('STOP alert','Market data touch does NOT prove Schwab order filled'),('Broker stop','Broker-held protective orders are essential'),('State','Cache persistence is best effort; reconcile events after state loss'),('Add-ons','Higher confirmed box + fresh daily close breakout + 1.5x volume + rising HMA38 + max 3% extension; manual review only')]
        pd.DataFrame(notes,columns=['Topic','Explanation']).to_excel(writer,sheet_name='READ ME',index=False)
        writer.sheets['READ ME'].set_column('A:A',25);writer.sheets['READ ME'].set_column('B:B',100)
    print(out)
if __name__=='__main__':main()

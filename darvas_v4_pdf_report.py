"""PDF chart add-on for Darvas Fresh V4. Research-only reports, not trade confirmations."""
import argparse, os, tempfile
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import inch
from xml.sax.saxutils import escape

FIELDS={'scan':('darvas_v4_scan_results.csv','darvas_v4_scan_detailed.pdf'),
        'backtest':('darvas_v4_backtest_results.csv','darvas_v4_backtest_detailed.pdf'),
        'monitor':('darvas_v4_monitor_results.csv','darvas_v4_monitor_detailed.pdf')}

def num(v):
    try:
        x=float(v)
        return x if np.isfinite(x) else None
    except (TypeError,ValueError):return None

def fmt(v,unit='$'):
    x=num(v)
    return f'{unit}{x:,.2f}' if x is not None else 'N/A'

def history(ticker,mode,csv_dir=''):
    if csv_dir:
        fp=Path(csv_dir)/f'{ticker}.csv'
        d=pd.read_csv(fp,index_col=0,parse_dates=True)
    else:
        import yfinance as yf
        d=yf.Ticker(ticker).history(period='9mo',interval='1d',auto_adjust=False)
    if d.empty:raise ValueError('No chart history')
    if isinstance(d.columns,pd.MultiIndex):d.columns=d.columns.get_level_values(0)
    d.columns=[str(c).title() for c in d.columns]
    d=d[['Open','High','Low','Close','Volume']].apply(pd.to_numeric,errors='coerce').dropna().tail(95)
    d.index=pd.to_datetime(d.index)
    if d.index.tz is not None:d.index=d.index.tz_localize(None)
    return d

def plot_chart(df,row,mode,outfile):
    d=df.tail(70).copy(); x=np.arange(len(d))
    fig,(ax,vol)=plt.subplots(2,1,figsize=(10.2,5.6),sharex=True,gridspec_kw={'height_ratios':[4,1]})
    fig.patch.set_facecolor('white')
    # OHLC candlesticks with distinct up/down colors
    for i,(_,bar) in enumerate(d.iterrows()):
        up=bar.Close>=bar.Open; color='#198754' if up else '#c0392b'
        ax.vlines(i,bar.Low,bar.High,color=color,linewidth=.8)
        ax.add_patch(plt.Rectangle((i-.32,min(bar.Open,bar.Close)),.64,max(abs(bar.Close-bar.Open),.025),facecolor=color,edgecolor=color,linewidth=.3))
    levels=[('Box high','box_high','#7c3aed','--'),('Box low','box_low','#7c3aed','--'),('Stop','stop','#c0392b','-'),('HT1','ht1','#087f8c','-.'),('HT2','ht2','#147d4e','-.')]
    if mode=='monitor':levels.insert(0,('Entry','entry','#e67e22',':'))
    seen=[]
    for label,key,color,style in levels:
        value=num(row.get(key))
        if value is not None and not any(abs(value-z)<.0001 for z in seen):
            ax.axhline(value,color=color,linestyle=style,linewidth=1.1,label=f'{label} {value:.2f}')
            seen.append(value)
    # HMA38 calculation on full input before slicing
    def wma(s,n):return s.rolling(n).apply(lambda z:np.dot(z,np.arange(1,n+1))/sum(range(1,n+1)),raw=True)
    hma=wma(2*wma(df.Close,19)-wma(df.Close,38),6).reindex(d.index)
    if hma.notna().any():ax.plot(x,hma,color='#2563eb',linewidth=1.25,label='HMA38')
    if mode!='monitor' and row.get('date'):
        try:
            signal_date=pd.Timestamp(str(row['date'])).date()
            match=np.where(d.index.date==signal_date)[0]
            if len(match):ax.axvline(int(match[0]),color='#444',alpha=.5,linestyle=':',label='Signal date')
        except ValueError:pass
    vol.bar(x,d.Volume/1e6,color=['#198754' if z.Close>=z.Open else '#c0392b' for _,z in d.iterrows()],alpha=.6)
    vol.set_ylabel('Vol (M)',fontsize=8);vol.grid(axis='y',alpha=.15)
    ticks=np.linspace(0,len(d)-1,min(7,len(d)),dtype=int)
    vol.set_xticks(ticks,[d.index[t].strftime('%b %d') for t in ticks],fontsize=8)
    ax.set_ylabel('Price ($)');ax.grid(alpha=.16);ax.legend(loc='best',fontsize=7,ncol=2)
    ax.set_title(f"{row['ticker']} | Daily OHLC (last {len(d)} sessions) | {mode.upper()}",loc='left',fontsize=11)
    fig.tight_layout();fig.savefig(outfile,dpi=130,bbox_inches='tight');plt.close(fig)

def make_pdf(args):
    csv_path=Path(args.input or FIELDS[args.mode][0]); output=Path(args.output or FIELDS[args.mode][1]);output.parent.mkdir(parents=True,exist_ok=True)
    if not csv_path.exists():raise SystemExit(f'Missing CSV: {csv_path}')
    df=pd.read_csv(csv_path).fillna('')
    if args.mode=='scan':
        if 'status' in df.columns:df=df.loc[df.status=='QUALIFIED']
        df=df.sort_values('date',ascending=False) if 'date' in df.columns else df
    elif args.mode=='backtest' and 'date' in df.columns:df=df.sort_values('date',ascending=False)
    df=df.head(args.max_charts)
    styles=getSampleStyleSheet();styles.add(ParagraphStyle(name='TinyCustom',parent=styles['Normal'],fontSize=8,leading=11,spaceAfter=6))
    styles.add(ParagraphStyle(name='HeadCustom',parent=styles['Heading1'],fontSize=17,textColor=colors.HexColor('#183153')))
    doc=SimpleDocTemplate(str(output),pagesize=(11*inch,8.5*inch),rightMargin=40,leftMargin=40,topMargin=35,bottomMargin=35)
    story=[Paragraph(f'Darvas Fresh V4 | {args.mode.title()} Detailed Report',styles['HeadCustom']),
           Paragraph(f'Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} | Source: {escape(str(csv_path))} | {len(df)} rows charted',styles['TinyCustom']),
           Paragraph('Research only. Charts show historical daily prices, not live quotes or confirmed Schwab executions. Box and target levels are from V4 CSV. Scan and backtest use different box construction methods.',styles['TinyCustom'])]
    if df.empty:
        story.append(Spacer(1,20));story.append(Paragraph('No qualifying rows in the source CSV. No stock charts to display. Check scan diagnostics for rejection reasons.',styles['Normal']))
    else:
        with tempfile.TemporaryDirectory() as td:
            for i,(_,r) in enumerate(df.iterrows()):
                row=r.to_dict();ticker=str(row.get('ticker','')).strip().upper()
                if not ticker:continue
                if i:story.append(PageBreak())
                status=str(row.get('status',row.get('outcome','')))
                title=f'{i+1}. {escape(ticker)} | {escape(status)}'
                story.append(Paragraph(title,styles['Heading2']))
                data=[['Metric','Value','Metric','Value']]
                for a,b in [('Entry / breakout', 'entry' if args.mode=='monitor' else 'breakout_close'),('Box high','box_high'),('Box low','box_low'),('Stop','stop'),('Target HT1','ht1'),('Target HT2','ht2'),('Last observed','last_price'),('Volume ratio','volume_ratio'),('Box age','box_age'),('Signal date','date')]:
                    value=row.get(b,'')
                    if value=='' or value is None:continue
                    formatted=fmt(value) if b in ('entry','breakout_close','box_high','box_low','stop','ht1','ht2','last_price') else escape(str(value))
                    data.append([a,formatted,'',''])
                # two compact columns of fields
                pairs=[(r[0],r[1]) for r in data[1:]]
                compact=[['Metric','Value','Metric','Value']]
                for j in range(0,len(pairs),2):
                    l=pairs[j];rr=pairs[j+1] if j+1<len(pairs) else ('','')
                    compact.append([l[0],l[1],rr[0],rr[1]])
                t=Table(compact,colWidths=[1.55*inch,1.25*inch,1.55*inch,1.25*inch]);t.setStyle(TableStyle([
                    ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f8')),('GRID',(0,0),(-1,-1),.25,colors.HexColor('#cbd5e1')),
                    ('FONTSIZE',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5)]))
                story.append(t);story.append(Spacer(1,9))
                if args.mode=='monitor' and status.startswith('RED_STOP'):
                    story.append(Paragraph('<font color="red"><b>RED: STOP PRICE REACHED - RECONCILE WITH SCHWAB. NOT A CONFIRMED FILL.</b></font>',styles['TinyCustom']))
                try:
                    d=history(ticker,args.mode,args.csv_dir)
                    png=Path(td)/f'{i}_{ticker}.png';plot_chart(d,row,args.mode,png)
                    story.append(Image(str(png),width=9.3*inch,height=5.1*inch,kind='proportional'))
                except Exception as exc:
                    story.append(Paragraph(f'Chart unavailable: {escape(str(exc))}',styles['TinyCustom']))
                story.append(Paragraph('Interpretation: price levels are indicative; daily candles cannot establish intraday order of stop and target touches. Verify positions and fills directly at Schwab.',styles['TinyCustom']))
            doc.build(story)
    if df.empty:doc.build(story)
    print(f'PDF REPORT: {output} ({len(df)} charts requested)')
    if args.send_telegram:
        import requests
        token=os.getenv('TELEGRAM_BOT_TOKEN');chat=os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat:
            print('Telegram PDF skipped: secrets unavailable')
        else:
            with output.open('rb') as fh:
                response=requests.post(f'https://api.telegram.org/bot{token}/sendDocument',data={'chat_id':chat,'caption':f'Darvas V4 {args.mode} detailed PDF'},files={'document':(output.name,fh,'application/pdf')},timeout=120)
            response.raise_for_status();print('PDF sent to Telegram')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=FIELDS,required=True);p.add_argument('--input',default='');p.add_argument('--output',default='');p.add_argument('--csv-dir',default='');p.add_argument('--max-charts',type=int,default=20);p.add_argument('--send-telegram',action='store_true');make_pdf(p.parse_args())

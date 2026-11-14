import os, io, zipfile
from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from core import db,import_positions,import_orders,import_signals,actions,opportunities,read,log_actions,number,now
from auto_scan import sync_bundled_scan

st.set_page_config(page_title='Darvas V7.1 Command Center',page_icon='📈',layout='wide')
st.markdown('''<style>.block-container{padding-top:1.2rem}div[data-testid="stMetric"]{background:#17223512;border-radius:12px;padding:12px}h1,h2,h3{letter-spacing:-.035em}</style>''',unsafe_allow_html=True)
DB_PATH=os.environ.get('DARVAS_DB_PATH','/data/darvas.sqlite3')
try:con=db(DB_PATH)
except OSError:
    st.error('Persistent data volume is not mounted or writable. Set DARVAS_DB_PATH to a persistent location.');st.stop()

# Basic optional single-user access gate. Use HTTPS and hosting-provider authentication for production.
password=os.environ.get('DARVAS_APP_PASSWORD','')
if not password:
    st.error('DARVAS_APP_PASSWORD is required. Set it as a private deployment environment variable.');st.stop()
if not st.session_state.get('authenticated'):
    st.title('🔐 Darvas Command Center')
    entered=st.text_input('Dashboard password',type='password')
    if st.button('Sign in'):
        import hmac
        if hmac.compare_digest(entered,password):st.session_state.authenticated=True;st.rerun()
        else:st.error('Incorrect password')
    st.stop()

try:
    scan_sync_status = sync_bundled_scan(con)
except Exception as exc:
    scan_sync_status = f'Automatic market scan import failed: {exc}'
    st.error(scan_sync_status)

st.title('📈 Darvas V7.1 | Trading Command Center')
st.caption('Research and portfolio oversight only • No automatic brokerage execution • V6.3 scan signals are not yet book-certified')
with st.sidebar:
    st.header('System status')
    scan_count=int(read(con,'SELECT COUNT(*) AS n FROM signals').iloc[0]['n'])
    st.caption(f'Market symbols available: {scan_count:,}')
    st.caption(scan_sync_status)
    imports=read(con,'SELECT kind,MAX(imported_at) AS last_import,COUNT(*) AS files FROM imports GROUP BY kind')
    for r in imports.itertuples():st.caption(f'{r.kind}: {r.last_import} UTC')
    st.info('Market scans update automatically after a successful GitHub Actions scan and Render deployment. Schwab data still requires manual upload.')
    if st.button('Log out'):st.session_state.authenticated=False;st.rerun()

# Streamlit refreshes the visible view every five minutes, but does not claim to fetch a new scan.
@st.fragment(run_every='5m')
def status_panel():
    a=actions(con);s=read(con,'SELECT COUNT(*) AS n,MAX(asof) AS last_asof FROM signals').iloc[0]
    cols=st.columns(4)
    cols[0].metric('Positions',len(a));cols[1].metric('Market symbols loaded',int(s['n']));cols[2].metric('Stop reviews',int(a.action.str.contains('STOP|EXIT',na=False).sum()) if not a.empty else 0);cols[3].metric('Last scan',str(s['last_asof'])[:10] if s['last_asof'] else 'None')
status_panel()

tabs=st.tabs(['📊 Dashboard','📤 Schwab & Scan Upload','💼 Portfolio','🎯 Opportunities','📦 Box Explorer','🛡️ Orders & Stops','📜 History'])
with tabs[0]:
    st.subheader('Your portfolio: what needs attention?')
    a=actions(con)
    if a.empty:
        st.info('No positions imported. Market research is available under Opportunities without Schwab data.')
    else:
        from decision_ui import enrich_positions
        enriched=enrich_positions(a)
        log_actions(con,a)
        critical=int((enriched['priority']=='HIGH').sum())
        missing=int(enriched['approved_stop'].isna().sum())
        c1,c2,c3=st.columns(3)
        c1.metric('High-priority reviews',critical)
        c2.metric('Missing recorded stops',missing)
        c3.metric('Holdings',len(enriched))
        for _,r in enriched.sort_values(['priority_rank','symbol']).iterrows():
            with st.container(border=True):
                l,m,n=st.columns([1.4,1,1])
                l.markdown(f'### {r["symbol"]} — {r["decision_label"]}')
                m.metric('Scan close',f'${r["scan_close"]:,.2f}' if pd.notna(r['scan_close']) else 'N/A')
                n.metric('Vs. box floor',f'{r["floor_distance_pct"]:+.1f}%' if pd.notna(r['floor_distance_pct']) else 'N/A')
                st.write(r['decision_explanation'])
                st.caption(f'As of {r["scan_asof"]} • Cost/share ${r["cost"]:,.2f} • {r["shares"]:g} shares • Approved stop: '+(f'${r["approved_stop"]:,.2f}' if pd.notna(r['approved_stop']) else 'Not recorded'))
        with st.expander('Detailed portfolio table'):
            st.dataframe(enriched.drop(columns=['priority_rank']),use_container_width=True,hide_index=True)
    st.warning('Research only, not trading instructions. Prices are historical snapshots. Verify live quotes, confirmed boxes, fills and protective orders at Schwab before acting.')
with tabs[1]:
    st.subheader('Import your Schwab and Darvas data')
    st.caption('Private files are stored in the application database, never in GitHub. Review the preview before importing.')
    for label,kind,fn in [('Schwab Positions CSV','positions',import_positions),('Schwab Order Status CSV','orders',import_orders),('V6.3 scan_all.csv or signals.csv','signals',import_signals)]:
        with st.container(border=True):
            f=st.file_uploader(label,type=['csv'],key=kind)
            if f:
                data=f.getvalue()
                try:
                    from core import parse_csv
                    preview=parse_csv(data) if kind!='signals' else pd.read_csv(io.BytesIO(data))
                    st.dataframe(preview.head(5),use_container_width=True,hide_index=True)
                    st.caption(f'{len(preview)} rows detected')
                    if st.button('Confirm '+label,key='confirm_'+kind):
                        n,status=fn(con,data,f.name)
                        st.success(f'{status}: {n} records');st.rerun()
                except Exception as exc:st.error(f'Invalid file: {exc}')
    st.divider()
    st.subheader('Optional: Import scan CSV from your V6.3 report ZIP')
    zf=st.file_uploader('V6.3 output ZIP',type=['zip'],key='zip')
    if zf and st.button('Import scan_all.csv from ZIP'):
        try:
            with zipfile.ZipFile(io.BytesIO(zf.getvalue())) as z:
                name=next(n for n in z.namelist() if n.endswith('scan_all.csv'))
                n,status=import_signals(con,z.read(name),name)
            st.success(f'{status}: {n} symbols');st.rerun()
        except Exception as exc:st.error(str(exc))
with tabs[2]:
    st.subheader('Positions from latest Schwab snapshot')
    st.dataframe(read(con,'SELECT * FROM positions ORDER BY symbol'),use_container_width=True,hide_index=True)
    st.caption('Snapshot positions are not live holdings. Orders may have changed after export.')
with tabs[3]:
    st.subheader('New-stock opportunity research')
    st.caption('Shortlist uses breakout, liquidity, volume and extension filters. Not a validated BUY signal.')
    d=opportunities(con)
    if d.empty:
        st.info('No candidates meet all current filters. This does not mean the scanner failed.')
    else:
        from decision_ui import enrich_opportunities
        ranked=enrich_opportunities(d)
        st.metric('Candidates passing preliminary filters',len(ranked))
        max_extension=st.slider('Maximum extension above box top (%)',1.0,5.0,5.0,0.5)
        min_volume=st.slider('Minimum relative volume',1.5,4.0,1.5,0.25)
        shown=ranked[(ranked.extension_pct<=max_extension)&(ranked.volume_ratio>=min_volume)]
        st.dataframe(shown[['symbol','name','asof','close','box_top','box_bottom','volume_ratio','extension_pct','box_risk_pct','research_label','research_note']],use_container_width=True,hide_index=True)
        st.caption('Candidates are sorted by relative volume, not predicted returns. Historical H1/H2/H3 box confirmation is not yet implemented.')
with tabs[4]:
    st.subheader('Darvas Box Explorer')
    symbols=read(con,'SELECT symbol FROM signals UNION SELECT symbol FROM positions ORDER BY symbol').symbol.tolist()
    if not symbols:st.info('Import market signals or positions first.')
    else:
        chosen=st.selectbox('Stock (select from the list; table double-click requires a custom grid)',symbols)
        row=read(con,'SELECT * FROM signals WHERE symbol=?',(chosen,))
        if not row.empty:
            r=row.iloc[0]
            st.caption(f'V6.3 research snapshot {r["asof"]} | {r["status"]} | not a verified historical box sequence')
        fetch=st.button('Fetch historical daily candles for chart',help='Downloads price history from Yahoo Finance for the selected symbol only; rate limits and data gaps are possible.')
        if fetch:
            try:
                import yfinance as yf
                data=yf.download(chosen,period='2y',interval='1d',auto_adjust=False,progress=False,threads=False)
                if isinstance(data.columns,pd.MultiIndex):data.columns=data.columns.get_level_values(0)
                if data.empty:st.error('No price history available')
                else:st.session_state[f'candles_{chosen}']=data
            except Exception as exc:st.error(f'Price download failed: {exc}')
        data=st.session_state.get(f'candles_{chosen}')
        if data is not None and not data.empty:
            fig=go.Figure()
            fig.add_trace(go.Candlestick(x=data.index,open=data.Open,high=data.High,low=data.Low,close=data.Close,name='Daily candles'))
            # One V6.3 box reference only. Historical H1/H2/H3 require verified time-stamped box events.
            if not row.empty:
                top,bottom=number(r['box_top']),number(r['box_bottom'])
                if top is not None and bottom is not None:
                    fig.add_hline(y=top,line_dash='dash',line_color='#16a34a',annotation_text='V6.3 box top (unverified)')
                    fig.add_hline(y=bottom,line_dash='dash',line_color='#ef4444',annotation_text='V6.3 box bottom (unverified)')
            p=read(con,'SELECT approved_stop FROM stops WHERE symbol=?',(chosen,))
            if not p.empty:fig.add_hline(y=float(p.iloc[0,0]),line_color='#f59e0b',annotation_text='Approved stop')
            fig.update_layout(template='plotly_dark',height=610,xaxis_rangeslider_visible=False,margin=dict(l=15,r=15,t=30,b=10))
            st.plotly_chart(fig,use_container_width=True)
            st.info('H1/H2/H3 confirmed historical boxes are not inferred from a single V6.3 snapshot. Future boxes are unknowable; scenario tools must not be labeled confirmed.')
        else:st.info('Click Fetch historical daily candles to display the chart. The app does not fabricate future price boxes.')
with tabs[5]:
    st.subheader('Schwab order ledger')
    st.dataframe(read(con,'SELECT symbol,status,action,qty,price,fill_price,placed_at,order_id FROM orders ORDER BY placed_at DESC'),use_container_width=True,hide_index=True)
    st.subheader('Approved stop ledger (manual record, not a Schwab order)')
    with st.form('stop_form'):
        symbol=st.text_input('Ticker').strip().upper();stop=st.number_input('Approved stop price',min_value=0.01,step=0.01);note=st.text_input('Reason / reference')
        submitted=st.form_submit_button('Save approved stop (does NOT place order)')
        if submitted:
            valid=read(con,'SELECT symbol FROM positions WHERE symbol=?',(symbol,))
            if valid.empty:st.error('Ticker must exist in uploaded positions')
            else:
                old=read(con,'SELECT approved_stop FROM stops WHERE symbol=?',(symbol,))
                if not old.empty and stop<float(old.iloc[0,0]):st.error('Cannot lower a previously approved stop in this Darvas workflow')
                else:
                    with con:con.execute('INSERT INTO stops VALUES (?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET approved_stop=excluded.approved_stop,updated_at=excluded.updated_at,note=excluded.note',(symbol,stop,now(),note))
                    st.success('Recorded locally; no broker order created');st.rerun()
    st.dataframe(read(con,'SELECT * FROM stops'),use_container_width=True,hide_index=True)
with tabs[6]:
    st.subheader('Decision audit trail')
    st.dataframe(read(con,'SELECT symbol,action,reason,calculated_at FROM decisions ORDER BY id DESC LIMIT 500'),use_container_width=True,hide_index=True)

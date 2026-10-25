"""Report on the existing baseline historical replay; not a multi-box portfolio backtest."""
from pathlib import Path
import pandas as pd

src = Path('darvas_v4_backtest_results.csv')
if not src.exists():
    raise SystemExit('Backtest CSV missing; run backtest first')
df = pd.read_csv(src)
symbols = [x.split('#',1)[0].strip().upper() for x in Path('symbols.txt').read_text().splitlines()]
symbols = list(dict.fromkeys(x for x in symbols if x))
if not df.empty and 'ticker' in df:
    counts = df.groupby('ticker').size().to_dict()
else:
    counts = {}
coverage = pd.DataFrame({'ticker':symbols, 'historical_signals':[counts.get(t,0) for t in symbols]})
coverage['coverage_status'] = coverage.historical_signals.map(lambda n:'SIGNALS FOUND' if n else 'NO SIGNALS OR DOWNLOAD ERROR — CHECK LOG')
summary = pd.DataFrame([
    ['Historical data requested','5 years per ticker'],
    ['Input ticker count',len(symbols)],
    ['Tickers with signals',sum(t in counts for t in symbols)],
    ['Total historical signals',len(df)],
    ['Simulation','Legacy daily-OHLC stop/target observation replay (NOT realized P&L)'],
    ['Ambiguity','Only actual same-bar stop AND target touches are marked; STOP_FIRST for those bars'],
    ['HT1','Milestone only; not a realized exit'],
    ['HT2','Observation milestone; not a brokerage execution'],
    ['Entry','Next session open'],
    ['Costs/slippage','NOT modeled'],
    ['Multi-box ADD MORE','NOT simulated'],
    ['Multi-box trailing stops','NOT simulated'],
    ['Portfolio P&L / drawdown','NOT calculated'],
    ['Historical-universe bias','Current 400 tickers used retroactively'],
],columns=['Metric','Value'])
with pd.ExcelWriter('darvas_v5_backtest_report.xlsx',engine='openpyxl') as writer:
    summary.to_excel(writer,sheet_name='READ ME - LIMITATIONS',index=False)
    df.to_excel(writer,sheet_name='HISTORICAL SIGNALS',index=False)
    coverage.to_excel(writer,sheet_name='400 STOCK COVERAGE',index=False)
    for sheet in writer.book:
        sheet.freeze_panes='A2'
        sheet.auto_filter.ref=sheet.dimensions
        for cell in sheet[1]:
            cell.font=__import__('openpyxl').styles.Font(bold=True,color='FFFFFF')
            cell.fill=__import__('openpyxl').styles.PatternFill('solid',fgColor='17365D')
        for col in sheet.columns:
            letter=col[0].column_letter
            sheet.column_dimensions[letter].width=min(62,max(15,max(len(str(c.value or '')) for c in list(col)[:120])+2))
print('Wrote darvas_v5_backtest_report.xlsx; historical baseline only, NOT multi-box backtest')

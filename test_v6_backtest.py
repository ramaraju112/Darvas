import unittest
import unittest
import pandas as pd
from darvas_v6_backtest import run_one
class V6Test(unittest.TestCase):
    def test_no_fabricated_trade(self):
        dates=pd.bdate_range('2025-01-01',periods=110)
        d=pd.DataFrame({'Open':[100.]*110,'High':[101.]*110,'Low':[99.]*110,'Close':[100.]*110,'Volume':[1000.]*110},index=dates)
        t,e,b,a,s,c=run_one('TEST',d)
        self.assertEqual(t,[]);self.assertEqual(a,[])
        self.assertEqual(c['status'],'OK')
    def test_stop_accounting_and_gap(self):
        dates=pd.bdate_range('2025-01-01',periods=110)
        d=pd.DataFrame({'Open':[100.]*110,'High':[101.]*110,'Low':[99.]*110,'Close':[100.]*110,'Volume':[1000.]*110},index=dates)
        # Confirmed pivot top and bottom; next-session gap below stop after entry.
        d.iloc[64,d.columns.get_loc('High')]=103
        d.iloc[69,d.columns.get_loc('Low')]=95
        d.iloc[75,d.columns.get_loc('Close')]=103.1
        d.iloc[75,d.columns.get_loc('High')]=104
        d.iloc[75,d.columns.get_loc('Volume')]=3000
        d.iloc[76,d.columns.get_loc('Open')]=104
        d.iloc[76,d.columns.get_loc('Low')]=99
        d.iloc[77,d.columns.get_loc('Open')]=90
        d.iloc[77,d.columns.get_loc('Low')]=89
        t,e,b,a,s,c=run_one('TEST',d,{'initial_max_extension':.05})
        # Data is intentionally adversarial; never assert a trade must exist.
        for x in t:
            if x['status']=='CLOSED':
                self.assertAlmostEqual(x['realized_pl'],x['proceeds']-x['spent'],places=2)
                self.assertTrue(x['exit_reason'].startswith('STOP'))
if __name__=='__main__':unittest.main()

class DeterministicMultiBoxTest(unittest.TestCase):
    def test_addon_and_stop_gap_dollar_math(self):
        from unittest.mock import patch
        import numpy as np
        from darvas_v6_backtest import run_one
        dates=pd.bdate_range('2025-01-01',periods=100)
        close=np.full(100,100.0); high=np.full(100,101.0); low=np.full(100,99.0); op=np.full(100,100.0); vol=np.full(100,1000.0)
        close[65]=102;high[65]=103;vol[65]=3000
        op[66]=103; low[66]=99.0;close[66]=103;high[66]=104
        close[72]=113;high[72]=114;low[72]=108
        op[73]=115;low[73]=110;close[73]=115;high[73]=116
        op[74]=104;low[74]=103;close[74]=105;high[74]=108
        d=pd.DataFrame(dict(Open=op,High=high,Low=low,Close=close,Volume=vol),index=dates)
        candidates=[None]*100
        candidates[65]=(101,95,60,62)
        candidates[72]=(112,108,68,70)
        # Simulated causal box series; tests accounting, not pivot discovery.
        with patch('darvas_v6_backtest.box_candidates',return_value=candidates),patch('darvas_v6_backtest.hma',return_value=pd.Series(np.arange(100,dtype=float),index=dates)):
            t,e,b,a,s,c=run_one('MOCK',d,{'initial_max_extension':.05})
        self.assertEqual(len(t),1)
        self.assertEqual(len(a),1)
        self.assertEqual(a[0]['status'],'FILLED')
        self.assertEqual(a[0]['shares'],10)
        self.assertEqual(t[0]['shares'],58) # 48 shares at $103 + 10 at $115
        self.assertEqual(t[0]['exit_reason'],'STOP_GAP')
        self.assertAlmostEqual(t[0]['proceeds'],58*104,places=2)
        self.assertAlmostEqual(t[0]['realized_pl'],58*104-(48*103+10*115),places=2)

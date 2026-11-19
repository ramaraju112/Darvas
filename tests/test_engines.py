import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'v7_4'))
import numpy as np
import pandas as pd
from engines.v75 import classic,recovery

def data(prices):
    c=np.asarray(prices,dtype=float)
    return pd.DataFrame({'open':c,'high':c+0.5,'low':c-0.5,'close':c,'volume':np.full(len(c),1000.)})

def test_insufficient():
    assert classic(data([10]*20))['stage']=='DATA_INCOMPLETE'
    assert recovery(data([10]*20))['stage']=='DATA_INCOMPLETE'

def test_recovery_without_hma():
    prices=list(np.linspace(100,65,60))+[65,64,65,64,65,66,65,66,67,68,69,70,70,71,72]
    result=recovery(data(prices))
    assert result['stage'] in ('STABILIZING','RECOVERY_EMERGING','RECOVERY_WATCH','DECLINE_MONITOR')
    assert 'version' in result

def test_no_future_peek():
    prices=list(np.linspace(50,90,55))+[95,94,93,92,90,89,90,91,92,93,94,96]
    df=data(prices)
    early=classic(df.iloc[:-1])
    later=classic(df)
    assert early['version']==later['version']

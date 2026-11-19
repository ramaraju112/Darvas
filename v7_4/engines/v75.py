"""V7.5 research-only shadow engines. OHLCV DataFrame ascending by date; no I/O."""
import numpy as np
import pandas as pd

VERSION='7.5-shadow-1'

def _num(x, default=0.0):
    return float(x) if pd.notna(x) and np.isfinite(float(x)) else default

def classic(df):
    """Causal pivots: 3 later completed sessions required; no future bars accessed."""
    d=df.reset_index(drop=True)
    n=len(d)
    out={'version':VERSION,'stage':'DATA_INCOMPLETE','watch':False,'score':0,'reasons':[]}
    if n<65: return out
    h=d.high.astype(float).to_numpy(); l=d.low.astype(float).to_numpy(); c=d.close.astype(float).to_numpy(); v=d.volume.astype(float).to_numpy()
    # Confirm a top only after 3 later sessions have completed. Start of box is the top pivot.
    tops=[i for i in range(3,n-3) if h[i]>max(h[i-3:i]) and max(h[i+1:i+4])<=h[i]]
    boxes=[]
    for t in tops:
        # Bottom pivot must occur after top; also requires three later completed sessions.
        bottoms=[j for j in range(t+1,n-3) if l[j]<=min(l[max(t,j-3):j],default=float('inf')) and min(l[j+1:j+4])>=l[j]]
        for b in bottoms:
            age=n-t
            if age<6 or age>40: continue
            top=float(h[t]); bottom=float(l[b]); depth=(top-bottom)/top if top>0 else 1
            if not (0<=depth<=.18): continue
            # Before latest breakout, no intervening closing invalidation below bottom.
            if np.any(c[b+4:n-1]<bottom): continue
            # A completed upper break before the latest bar makes this an older breakout, not a new one.
            if np.any(c[t+4:n-1]>top): continue
            boxes.append((t,b,top,bottom,depth,age))
    if not boxes:
        out.update(stage='BOX_FORMING' if tops else 'TREND_CANDIDATE',reasons=['No eligible confirmed box found'])
        return out
    t,b,top,bottom,depth,age=max(boxes,key=lambda x:x[0])
    rvol=float(v[-1]/np.mean(v[-21:-1])) if n>=21 and np.mean(v[-21:-1])>0 else 0
    breakout=bool(c[-1]>top)
    confirmed=bool(breakout and rvol>=1.5)
    near=bool(bottom<=c[-1]<=top and c[-1]>=top*.97)
    stage='BREAKOUT_CONFIRMED' if confirmed else 'BREAKOUT_UNCONFIRMED' if breakout else 'NEAR_BREAKOUT' if near else 'BOX_CONFIRMED'
    # Transparent exploratory quality score, not a success probability.
    box_points=max(0,30*(1-depth/.18)); vol_points=min(20,20*rvol/1.5)
    trend_points=25 if n>=50 and c[-1]>np.mean(c[-50:]) and np.mean(c[-20:])>np.mean(c[-50:]) else 0
    risk_points=15 if c[-1]>bottom and (c[-1]-bottom)/c[-1]<=.18 else 0
    score=round(min(100,box_points+vol_points+trend_points+risk_points+10),1)
    return dict(version=VERSION,stage=stage,watch=confirmed,score=score,box_top=round(top,4),box_bottom=round(bottom,4),box_depth_pct=round(depth*100,2),box_age=age,upper_pivot_index=t,lower_pivot_index=b,rvol20=round(rvol,2),target_1=round(c[-1]+(top-bottom),4) if confirmed else None,target_2=round(c[-1]+2*(top-bottom),4) if confirmed else None,reasons=['Research only; breakout volume confirmed' if confirmed else 'No confirmed breakout yet'])

def recovery(df):
    """Early stabilization can qualify with negative HMA slope; no Darvas dependence."""
    d=df.reset_index(drop=True)
    n=len(d)
    out={'version':VERSION,'stage':'DATA_INCOMPLETE','discovery':False,'watch':False,'score':0,'reasons':[]}
    if n<65:return out
    c=d.close.astype(float); h=d.high.astype(float); l=d.low.astype(float); v=d.volume.astype(float)
    high=float(h.iloc[max(0,n-126):n-20].max()); recent_low=float(l.iloc[-20:].min()); decline=(high-recent_low)/high if high>0 else 0
    weak=decline>=.15
    # Early stabilization: reduced downside extension and positive 5-day price change, not HMA confirmation.
    low_prev=float(l.iloc[-20:-10].min()); low_new=float(l.iloc[-10:].min()); hold=low_new>=low_prev*.98
    positive5=float(c.iloc[-1])>float(c.iloc[-6]); positive20=float(c.iloc[-1])>float(c.iloc[-21]); above20=float(c.iloc[-1])>float(c.iloc[-20:].mean())
    higher_low=low_new>low_prev
    up_vol=float(v.iloc[-10:][c.diff().iloc[-10:]>0].sum()); down_vol=float(v.iloc[-10:][c.diff().iloc[-10:]<0].sum())
    accumulation=up_vol>down_vol and up_vol>0
    vol_ratio=float(v.iloc[-1]/v.iloc[-21:-1].mean()) if v.iloc[-21:-1].mean()>0 else 0
    # Groups: price 25, momentum 25, relative-strength placeholder 0/20 (benchmark unavailable), volume 15, risk 15.
    price_score=(12 if hold else 0)+(13 if higher_low else 0)
    momentum_score=(10 if positive5 else 0)+(10 if positive20 else 0)+(5 if above20 else 0)
    volume_score=(10 if accumulation else 0)+(5 if vol_ratio>=1 else 0)
    risk_score=15 if hold and (float(c.iloc[-1])-recent_low)/float(c.iloc[-1])<=.20 else 0
    score=price_score+momentum_score+volume_score+risk_score
    discovery=bool(weak and hold and (positive5 or accumulation))
    watch=bool(discovery and higher_low and positive20 and above20 and accumulation and score>=50)
    stage='RECOVERY_WATCH' if watch else 'RECOVERY_EMERGING' if discovery and higher_low and positive20 else 'STABILIZING' if discovery else 'DECLINE_MONITOR' if weak else 'NONE'
    return dict(version=VERSION,stage=stage,discovery=discovery,watch=watch,score=score,score_provisional=True,relative_strength_status='NOT_AVAILABLE',prior_decline_pct=round(decline*100,2),support=round(recent_low,4),rvol20=round(vol_ratio,2),reasons=['Research-only early discovery; relative strength not scored'] if discovery else ['No early stabilization evidence or qualifying correction'])

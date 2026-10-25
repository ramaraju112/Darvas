"""Conservative, causal higher-box tracking. Research alerts; NEVER broker orders.

A box is eligible only after two subsequent completed daily candles confirm
both pivot extrema. A new ascending box must have higher high AND higher low.
The close-breakout bar cannot itself be used to confirm that box.
"""
import math
from darvas_fresh_v4_helper import confirmed_box, hma


def box_at(d, idx):
    if idx < 60: return None
    found=confirmed_box(d,idx)
    if found is None: return None
    high,low,age=found
    if not all(map(math.isfinite,(high,low))) or high<=low: return None
    return {'high':round(high,4),'low':round(low,4),'age':int(age)}


def assess(d, state, broker_stop=None, max_extension=0.03):
    """Only completed daily bars; last completed bar is the signal bar.

    state: last accepted higher-box and proposed stop, stored across runs.
    Returns (new_state, snapshot, novel_events). No automatic stop changes.
    """
    state=dict(state or {})
    result={'box_high':'','box_low':'','box_age':'','volume_ratio':'',
            'hma38_rising':False,'higher_box_confirmed':False,
            'add_more':'NO','recommended_stop':state.get('recommended_stop',''),
            'broker_stop_confirmed':broker_stop if broker_stop is not None else '',
            'stop_review':'','reason':'NO_CONFIRMED_BOX'}
    if len(d)<80: return state,result,[]
    i=len(d)-1
    b=box_at(d,i)
    if b is None:return state,result,[]
    result.update(box_high=b['high'],box_low=b['low'],box_age=b['age'])
    close=float(d.Close.iloc[i]);prev=float(d.Close.iloc[i-1]);volume=float(d.Volume.iloc[i]);avg=float(d.Volume.iloc[i-20:i].mean())
    ratio=volume/avg if avg>0 else 0
    hv=hma(d.Close,38)
    rising=bool(math.isfinite(float(hv.iloc[i])) and math.isfinite(float(hv.iloc[i-1])) and hv.iloc[i]>=hv.iloc[i-1])
    result.update(volume_ratio=round(ratio,3),hma38_rising=rising)
    # Require both limits to advance; otherwise a developing or sideways box.
    old_high=state.get('accepted_box_high');old_low=state.get('accepted_box_low')
    higher=old_high is not None and b['high']>float(old_high)+1e-8 and b['low']>float(old_low)+1e-8
    first=old_high is None
    events=[]
    day=str(d.index[i].date())
    if higher:
        state['accepted_box_high']=b['high'];state['accepted_box_low']=b['low'];state['accepted_date']=day
        state['pending_add_on_box']=f"{b['high']}:{b['low']}"
        result['higher_box_confirmed']=True
        events.append('HIGHER_BOX_CONFIRMED')
        prior_stop=state.get('recommended_stop')
        if prior_stop is None or b['low']>float(prior_stop):
            state['recommended_stop']=b['low']
            events.append('STOP_RAISE_REVIEW')
    elif first:
        # Initial baseline is NOT a new add-on signal or a request to raise stop.
        state['accepted_box_high']=b['high'];state['accepted_box_low']=b['low'];state['accepted_date']=day
    result['recommended_stop']=state.get('recommended_stop','')
    if state.get('recommended_stop') is not None and broker_stop is not None and float(state['recommended_stop'])>float(broker_stop):
        result['stop_review']='REVIEW IN SCHWAB - NOT UPDATED AUTOMATICALLY'
    fresh=prev<=b['high'] and close>b['high']
    extension=(close/b['high']-1) if b['high']>0 else 99
    qualifying=fresh and ratio>=1.5 and rising and extension<=max_extension
    # Only trigger ADD MORE for a confirmed *new* higher box on today's close,
    # and never again on repeated monitor runs.
    box_id=f"{b['high']}:{b['low']}"
    pending=state.get('pending_add_on_box')==box_id and state.get('last_add_on_box')!=box_id
    if pending and qualifying:
        state['last_add_on_box']=box_id
        state['pending_add_on_box']=None
        result['add_more']='ADD-ON CANDIDATE - MANUAL RISK REVIEW'
        events.append('ADD_ON_CANDIDATE')
        result['reason']='HIGHER_BOX_FRESH_BREAKOUT_VOLUME_HMA_PASS'
    elif pending:
        result['reason']='HIGHER_BOX_WAITING_FOR_FRESH_QUALIFYING_BREAKOUT'
    elif higher:
        result['reason']='HIGHER_BOX_CONFIRMED_NO_QUALIFYING_ADD_ON'
    else:
        result['reason']='NO_NEW_HIGHER_BOX'
    result['higher_box_confirmed']=higher
    return state,result,events

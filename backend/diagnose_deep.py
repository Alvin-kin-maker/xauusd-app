"""
diagnose_deep.py — Traces EXACTLY what resolve_direction returns on March 3 13:15
and why — step by step through every priority.

Run from: C:\\Users\\alvin\\xauusd_app\\backend
Command:  python diagnose_deep.py
"""
import sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime

if not mt5.initialize():
    print("MT5 not running"); sys.exit(1)

SYMBOL = "XAUUSD"
start  = datetime(2026, 2, 1)
end    = datetime(2026, 3, 31, 23, 59)

TF_MAP = {
    "M5":  mt5.TIMEFRAME_M5,  "M15": mt5.TIMEFRAME_M15,
    "H1":  mt5.TIMEFRAME_H1,  "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,  "W1":  mt5.TIMEFRAME_W1,
    "MN":  mt5.TIMEFRAME_MN1,
}
raw = {}
for tf, mt5_tf in TF_MAP.items():
    rates = mt5.copy_rates_range(SYMBOL, mt5_tf, start, end)
    if rates is not None and len(rates) > 0:
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"tick_volume": "volume"})
        raw[tf] = df[["time","open","high","low","close","volume"]].copy()
mt5.shutdown()

from engines.box2_trend  import run as run_b2
from engines.box3_liquidity import run as run_b3
from engines.box7_entry  import run as run_b7
from engines.box8_model  import run as run_b8
from engines.box9_confluence import resolve_direction
from engines.box1_market_context import run as run_b1
from engines.box4_levels import run as run_b4
from engines.box5_momentum import run as run_b5
from engines.box6_sentiment import run as run_b6
from engines.box13_breakout import run as run_b13

class SimpleStore:
    def __init__(self, snap, price):
        self._data  = snap
        self._price = price
    def get_closed(self, tf): return self._data.get(tf, pd.DataFrame())
    def get(self, tf):        return self._data.get(tf, pd.DataFrame())
    def get_price(self):      return self._price
    def get_pdh(self):
        d = self._data.get("D1", pd.DataFrame())
        return float(d.iloc[-2]["high"]) if len(d) >= 2 else None
    def get_pdl(self):
        d = self._data.get("D1", pd.DataFrame())
        return float(d.iloc[-2]["low"]) if len(d) >= 2 else None
    def get_pwh(self):
        w = self._data.get("W1", pd.DataFrame())
        return float(w.iloc[-2]["high"]) if len(w) >= 2 else None
    def get_pwl(self):
        w = self._data.get("W1", pd.DataFrame())
        return float(w.iloc[-2]["low"]) if len(w) >= 2 else None
    def get_pmh(self):
        m = self._data.get("MN", pd.DataFrame())
        return float(m.iloc[-2]["high"]) if len(m) >= 2 else None
    def get_pml(self):
        m = self._data.get("MN", pd.DataFrame())
        return float(m.iloc[-2]["low"]) if len(m) >= 2 else None
    @property
    def prev_day(self):
        d = self._data.get("D1", pd.DataFrame())
        if len(d) < 2: return None
        r = d.iloc[-2]
        return {"open":float(r.open),"high":float(r.high),"low":float(r.low),"close":float(r.close)}
    @property
    def prev_week(self):
        w = self._data.get("W1", pd.DataFrame())
        if len(w) < 2: return None
        r = w.iloc[-2]
        return {"open":float(r.open),"high":float(r.high),"low":float(r.low),"close":float(r.close)}
    @property
    def prev_month(self):
        mn = self._data.get("MN", pd.DataFrame())
        if len(mn) < 2: return None
        r = mn.iloc[-2]
        return {"open":float(r.open),"high":float(r.high),"low":float(r.low),"close":float(r.close)}
    def is_ready(self): return True

# Check multiple signal times
CHECK_TIMES = [
    "2026-03-03 13:10",  # just before first signal
    "2026-03-04 10:00",  # just before March 4 signal
    "2026-03-05 13:30",  # just before March 5 signal
    "2026-03-16 14:00",  # blocked — H4+H1 bearish, should SELL
]

for time_str in CHECK_TIMES:
    t = pd.Timestamp(time_str)
    snap = {}
    for tf, df in raw.items():
        snap[tf] = df[df["time"] < t].copy().reset_index(drop=True)

    mid = float(snap["M5"].iloc[-1]["close"]) if not snap["M5"].empty else 3000
    price = {"bid": mid-0.085, "ask": mid+0.085, "spread": 0.17, "mid": mid, "last": mid}
    store = SimpleStore(snap, price)

    try:
        b1  = run_b1(store)
        # Patch session
        from engines.box1_market_context import get_current_session
        sess = get_current_session(t.to_pydatetime())
        b1["primary_session"] = sess["primary_session"]
        b1["is_tradeable"]    = sess["primary_session"] in ["london","new_york","overlap"]

        b2  = run_b2(store)
        b3  = run_b3(store)
        b4  = run_b4(store)
        b5  = run_b5(store)
        b6  = run_b6(store)
        b7  = run_b7(store, b2)
        b13 = run_b13(store, b1, b2, b3, b4, b5, b7)
        b8  = run_b8(b1, b2, b3, b4, b5, b6, b7, b13)
    except Exception as e:
        print(f"\n{time_str} — ENGINE ERROR: {e}")
        import traceback; traceback.print_exc()
        continue

    tfs = b2["timeframes"]
    h1  = tfs["H1"]["bias"]
    m15 = tfs["M15"]["bias"]
    h4  = tfs["H4"]["bias"]
    d1  = tfs["D1"]["bias"]

    from engines.box9_confluence import run as run_b9
    b9 = run_b9(b1, b2, b3, b4, b5, b6, b7, b8, b13)

    direction = resolve_direction(b2, b3, b7, b8)

    print(f"\n{'='*65}")
    print(f"  {time_str}")
    print(f"{'='*65}")
    print(f"  H1={h1}  M15={m15}  H4={h4}  D1={d1}")
    print(f"  sweep_just_happened: {b3.get('sweep_just_happened')}  sweep_dir: {b3.get('sweep_direction')}")
    print(f"  active_model: {b8.get('best_model_name')}  model_validated: {b8.get('model_validated')}")
    print(f"  mss_m15_active: {b2.get('mss_m15_active')}  mss_m15_type: {b2.get('mss_m15_type')}")
    print(f"  entry_bias (b7): {b7.get('entry_bias')}")
    print(f"  → resolve_direction returned: {direction.upper()}")
    print(f"  → b9['direction']:            {b9.get('direction','?').upper()}")
    print(f"  → b9['should_trade']:         {b9.get('should_trade')}")
    print(f"  → b9['kill_switches']:        {b9.get('kill_switches',[])[:2]}")

    # Step through manually
    print(f"\n  Priority trace:")
    if b3.get("sweep_just_happened"):
        sd = b3.get("sweep_direction","")
        print(f"  P1 SWEEP fired → {sd} → would return {'sell' if 'bearish' in sd else 'buy'}")
    else:
        print(f"  P1 sweep: no fresh sweep")

    model = b8.get("best_model_name","")
    if b8.get("active_model") and b8.get("model_validated"):
        print(f"  P2 model={model}")
    else:
        print(f"  P2 model: none validated")

    if b2.get("mss_m15_active"):
        print(f"  P3 MSS fired: {b2.get('mss_m15_type')}")
    else:
        print(f"  P3 MSS: not active")

    if h1 == m15 and h1 not in ("neutral","unknown","ranging"):
        print(f"  P4 H1+M15 AGREE → {h1} → would return {'buy' if h1=='bullish' else 'sell'}")
    else:
        print(f"  P4 H1+M15 DISAGREE: H1={h1} M15={m15}")
        if h4 not in ("neutral","unknown","ranging"):
            eb = b7.get("entry_bias","")
            print(f"  P5 H4={h4}, entry_bias={eb}")
        print(f"  P6 D1={d1} H4={h4}")

print("\nDone.")
"""
diagnose_march.py — Run this to see exactly what box2 outputs
on the specific bars where signals fired, and on days where they should
have fired (March 6, 12, 17-31 correction days).

Run from: C:\\Users\\alvin\\xauusd_app\\backend
Command:  python diagnose_march.py
"""

import sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

import pandas as pd
import MetaTrader5 as mt5

if not mt5.initialize():
    print("MT5 not running"); sys.exit(1)

SYMBOL = "XAUUSD"

# ── Fetch data ────────────────────────────────────────────────
from datetime import datetime, timedelta
start = datetime(2026, 2, 1)   # warm-up from Feb
end   = datetime(2026, 3, 31, 23, 59)

raw = {}
TF_MAP = {
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
    "W1":  mt5.TIMEFRAME_W1,
    "MN":  mt5.TIMEFRAME_MN1,
}
for tf, mt5_tf in TF_MAP.items():
    rates = mt5.copy_rates_range(SYMBOL, mt5_tf, start, end)
    if rates is not None and len(rates) > 0:
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"tick_volume": "volume"})
        raw[tf] = df[["time","open","high","low","close","volume"]].copy()

mt5.shutdown()

# ── Load engines ──────────────────────────────────────────────
from engines.box2_trend import run as run_b2, analyze_timeframe

# ── Dates to inspect: signal fire dates + should-have-fired dates ──
CHECK_TIMES = [
    # Signal fired (all BUY — why?)
    ("2026-03-03 13:00", "SIGNAL FIRED BUY"),
    ("2026-03-05 13:00", "SIGNAL FIRED BUY"),
    ("2026-03-10 10:00", "SIGNAL FIRED BUY"),
    ("2026-03-17 14:00", "SIGNAL FIRED BUY"),
    # Should have fired SELL (kill switch blocked)
    ("2026-03-06 14:00", "BLOCKED — should be SELL?"),
    ("2026-03-12 14:00", "BLOCKED — should be SELL?"),
    ("2026-03-19 14:00", "BLOCKED — should be SELL?"),
    ("2026-03-25 14:00", "BLOCKED — should be SELL?"),
    ("2026-03-30 14:00", "BLOCKED — H1 exhaustion fired"),
]

print("=" * 70)
print("BOX2 BIAS DIAGNOSTIC — What H1/M15/H4/D1 read at each key bar")
print("=" * 70)

class SimpleStore:
    def __init__(self, snapshot):
        self._data = snapshot
    def get_closed(self, tf):
        return self._data.get(tf, pd.DataFrame())
    def get(self, tf):
        return self._data.get(tf, pd.DataFrame())
    def get_price(self):
        return {"bid": 0, "ask": 0, "spread": 0, "mid": 0}

for time_str, label in CHECK_TIMES:
    t = pd.Timestamp(time_str)
    
    # Build snapshot: only bars closed before t
    snapshot = {}
    for tf, df in raw.items():
        closed = df[df["time"] < t].copy().reset_index(drop=True)
        snapshot[tf] = closed

    store = SimpleStore(snapshot)
    
    try:
        b2 = run_b2(store)
    except Exception as e:
        print(f"\n{time_str} [{label}] — ERROR: {e}")
        continue

    tfs = b2["timeframes"]
    print(f"\n{'─'*70}")
    print(f"  {time_str}  |  {label}")
    print(f"{'─'*70}")
    print(f"  {'TF':<6} {'Bias':<10} {'Structure':<14} {'HH':<5} {'HL':<5} {'LH':<5} {'LL':<5} {'LastBOS'}")
    for tf in ["MN","W1","D1","H4","H1","M15","M5"]:
        r = tfs.get(tf, {})
        bias      = r.get("bias", "?")
        structure = r.get("structure", "?")
        hh = r.get("hh", "?")
        hl = r.get("hl", "?")
        lh = r.get("lh", "?")
        ll = r.get("ll", "?")
        bos_info = ""
        bos_list = r.get("bos", [])
        candle_count = r.get("candle_count", len(snapshot.get(tf, [])))
        if bos_list:
            last_bos = bos_list[-1]
            bars_ago = candle_count - last_bos.get("broken_at", 0)
            bos_info = f"{last_bos.get('type','?')[:12]}({bars_ago}b ago)"
        print(f"  {tf:<6} {bias:<10} {structure:<14} "
              f"{str(hh):<5} {str(hl):<5} "
              f"{str(lh):<5} {str(ll):<5} {bos_info}")
    
    print(f"\n  Overall bias: {b2['overall_bias']}  "
          f"(bull={b2['bull_score']:.2f} bear={b2['bear_score']:.2f})")
    
    # What would resolve_direction return?
    h1  = tfs["H1"]["bias"]
    m15 = tfs["M15"]["bias"]
    h4  = tfs["H4"]["bias"]
    d1  = tfs["D1"]["bias"]
    
    if h1 == m15 and h1 not in ("neutral","unknown","ranging"):
        resolved = "BUY" if h1 == "bullish" else "SELL"
        reason = f"H1+M15 both {h1}"
    elif h4 not in ("neutral","unknown","ranging"):
        resolved = "BUY" if h4 == "bullish" else "SELL"
        reason = f"H4={h4} (H1/M15 disagree or neutral)"
    elif d1 == h4 and d1 not in ("neutral",):
        resolved = "BUY" if d1 == "bullish" else "SELL"
        reason = f"D1+H4 fallback"
    else:
        resolved = "NONE"
        reason = "no agreement"
    
    print(f"  → resolve_direction would return: {resolved}  ({reason})")
    print(f"    H1={h1}  M15={m15}  H4={h4}  D1={d1}")

print(f"\n{'='*70}")
print("DONE — paste this output so we can see what's actually happening")
print("="*70)
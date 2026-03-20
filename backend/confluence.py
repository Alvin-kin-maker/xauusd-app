import sys
sys.path.insert(0, '.')
import MetaTrader5 as mt5
mt5.initialize()

from data.candle_store import store
store.refresh()

from engines.box1_market_context import run as b1r
from engines.box2_trend          import run as b2r
from engines.box3_liquidity      import run as b3r
from engines.box4_levels         import run as b4r
from engines.box5_momentum       import run as b5r
from engines.box6_sentiment      import run as b6r
from engines.box7_entry          import run as b7r
from engines.box8_model          import run as b8r
from engines.box9_confluence     import run as b9r
from engines.box13_breakout      import run as b13r

b1  = b1r(store)
b2  = b2r(store)
b3  = b3r(store)
b4  = b4r(store)
b5  = b5r(store)
b6  = b6r(store)
b7  = b7r(store, b2)
b13 = b13r(store, b1, b2, b3, b4, b5, b7)
b8  = b8r(b1, b2, b3, b4, b5, b6, b7, b13)
b9  = b9r(b1, b2, b3, b4, b5, b6, b7, b8, b13)

print(f"\nScore: {b9['score']} | Grade: {b9['grade']} | Direction: {b9['direction']}")
print(f"Should Trade: {b9['should_trade']}")

print("\nKill Switches:")
if b9['kill_switches']:
    for k in b9['kill_switches']:
        print(f"  {k}")
else:
    print("  None")

print("\nEngine Breakdown:")
total = 0
for name, e in b9['engines'].items():
    print(f"  {name:20} {e['raw']:3}/100  weight={e['weight']}  contribution={e['contribution']}pts")
    total += e['contribution']
print(f"  {'TOTAL':20} {round(total,1)}pts")

print(f"\nActive Model: {b8['best_model_name']} | Score: {b8['best_model_score']}")
print(f"Validated Models: {list(b8['validated_models'].keys())}")

print(f"\nTrend Detail:")
for tf, data in b2['timeframes'].items():
    print(f"  {tf}: {data['bias']}")

print(f"\nLiquidity Detail:")
print(f"  Sweep just happened: {b3['sweep_just_happened']}")
print(f"  Total sweeps: {b3['total_sweeps']}")
print(f"  PDH swept: {b3['pdh_swept']} | PDL swept: {b3['pdl_swept']}")
print(f"  Asian H swept: {b3['asian_high_swept']} | Asian L swept: {b3['asian_low_swept']}")

print(f"\nMomentum Detail:")
print(f"  RSI M5:  {b5.get('rsi_m5')} | signal: {b5.get('rsi_m5_signal')}")
print(f"  RSI M15: {b5.get('rsi_m15')} | signal: {b5.get('rsi_m15_signal')}")
print(f"  RSI H1:  {b5.get('rsi_h1')} | signal: {b5.get('rsi_h1_signal')}")
print(f"  Divergence: {b5.get('divergence_active')} | Volume spike: {b5['volume_m15']['is_spike']}")

mt5.shutdown()
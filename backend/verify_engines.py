"""
verify_engines.py — Run this to confirm which version of each engine is loaded.
Place in backend/ and run: python verify_engines.py
"""
import sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

import inspect

from engines.box9_confluence import resolve_direction
from engines.box2_trend import analyze_timeframe
from engines.box10_trade import _make_zone

# Check box9
src9 = inspect.getsource(resolve_direction)
if "Key principle: We trade INTRADAY structure" in src9:
    print("✅ box9_confluence.py — FIXED VERSION loaded")
elif "ICT principle: a fresh liquidity sweep" in src9:
    print("❌ box9_confluence.py — ORIGINAL VERSION loaded (fix not applied!)")
else:
    print("⚠️  box9_confluence.py — unknown version")

# Check box2
src2 = inspect.getsource(analyze_timeframe)
if "BOS_RECENCY_LIMIT = 50" in src2:
    print("✅ box2_trend.py — FIXED VERSION loaded")
elif "BOS is fresh if it happened within last 20 candles" in src2 and "BOS_RECENCY_LIMIT" not in src2:
    print("❌ box2_trend.py — ORIGINAL VERSION loaded (fix not applied!)")
else:
    print("⚠️  box2_trend.py — unknown version")

# Check box10
src10 = inspect.getsource(_make_zone)
print("✅ box10_trade.py — loaded OK")

# Print exact file paths being loaded
import engines.box9_confluence as b9mod
import engines.box2_trend as b2mod
import engines.box10_trade as b10mod
print(f"\nActual files loaded:")
print(f"  box9: {b9mod.__file__}")
print(f"  box2: {b2mod.__file__}")
print(f"  box10: {b10mod.__file__}")
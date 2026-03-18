# ============================================================
# run.py — XAUUSD Trading System Launcher
# Run this from C:\Users\alvin\xauusd_app\backend
# Just double-click or: python run.py
# ============================================================

import sys
import os
import subprocess

# Make sure we're in the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

print("=" * 55)
print("   XAUUSD TRADING SYSTEM")
print("=" * 55)

# Quick checks before starting
print("\n[Startup] Checking dependencies...")

# Check MT5
try:
    import MetaTrader5 as mt5
    if mt5.initialize():
        info = mt5.account_info()
        print(f"[Startup] MT5 connected ✓  (Balance: ${info.balance:,.2f})")
        mt5.shutdown()
    else:
        print("[Startup] ⚠ MT5 not connected — open MetaTrader5 first")
        input("Press Enter to exit...")
        sys.exit(1)
except ImportError:
    print("[Startup] ✗ MetaTrader5 not installed")
    input("Press Enter to exit...")
    sys.exit(1)

# Check FastAPI / uvicorn
try:
    import fastapi
    import uvicorn
    print(f"[Startup] FastAPI ✓  uvicorn ✓")
except ImportError as e:
    print(f"[Startup] ✗ Missing package: {e}")
    print("Run: pip install fastapi uvicorn")
    input("Press Enter to exit...")
    sys.exit(1)

# Check cot_reports
try:
    import cot_reports
    print(f"[Startup] cot_reports ✓")
except ImportError:
    print("[Startup] ⚠ cot_reports not installed (COT data will be unavailable)")

print("\n[Startup] All checks passed ✓")
print("\n[Startup] Starting API server...")
print("=" * 55)
print("   API:  http://127.0.0.1:8000")
print("   Docs: http://127.0.0.1:8000/docs")
print("   Signal: http://127.0.0.1:8000/signal")
print("=" * 55)
print("\nPress CTRL+C to stop\n")

# Launch the server
import uvicorn
uvicorn.run(
    "api.main:app",
    host="127.0.0.1",
    port=8000,
    reload=False,
    log_level="info",
)
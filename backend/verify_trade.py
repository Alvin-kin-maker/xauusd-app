"""
verify_trade.py — Manually verify what price actually did after a signal entry.
Checks the M1 candles around entry time to see if SL was actually hit or if
the backtest engine is reporting wrong outcomes.

Run: python verify_trade.py
"""
import sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime, timedelta

if not mt5.initialize():
    print("MT5 not running"); sys.exit(1)

SYMBOL = "XAUUSD"

# ── Trades to verify (from backtest output) ──────────────────
# Each: (signal_time, direction, entry, sl, tp1, tp3, reported_outcome)
TRADES = [
    # January
    ("2026-01-06 11:00", "buy",  4463.95, 4461.04, 4483.65, 4511.47, "SL_HIT -29p"),
    ("2026-01-09 14:55", "buy",  4466.08, 4461.95, 4477.63, 4511.47, "SL_HIT -41p"),
    ("2026-01-19 20:25", "buy",  4678.91, 4674.44, 4690.69, 4730.55, "SL_HIT -45p"),
    ("2026-01-20 16:40", "buy",  4736.97, 4732.21, 4750.00, 4785.37, "SL_HIT -48p"),
    ("2026-01-23 16:50", "buy",  4953.91, 4946.86, 4993.53, 5050.00, "SL_HIT -70p"),
    # March
    ("2026-03-03 13:15", "buy",  5281.53, 5266.70, 5320.95, 5393.50, "SL_HIT -148p"),
    ("2026-03-04 12:15", "buy",  5200.50, 5187.64, 5237.96, 5300.00, "SL_HIT -129p"),
    ("2026-03-05 13:15", "buy",  5160.22, 5154.75, 5180.61, 5202.64, "SL_HIT -55p"),
    ("2026-03-18 10:00", "sell", 4985.54, 4988.04, 4973.51, 4939.58, "SL_HIT -25p"),
]

print("=" * 75)
print("TRADE VERIFICATION — Did price actually hit SL or TP?")
print("Checking M1 candles after each entry time")
print("=" * 75)

for sig_time_str, direction, entry, sl, tp1, tp3, reported in TRADES:
    sig_time = datetime.strptime(sig_time_str, "%Y-%m-%d %H:%M")
    fetch_from = sig_time - timedelta(minutes=5)
    fetch_to   = sig_time + timedelta(hours=10)

    rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, fetch_from, fetch_to)
    if rates is None or len(rates) == 0:
        print(f"\n{sig_time_str} — NO M1 DATA FOUND")
        continue

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")

    # Find candles after signal time
    future = df[df["time"] > sig_time].head(200)
    if future.empty:
        print(f"\n{sig_time_str} — NO FUTURE CANDLES")
        continue

    sl_dist  = abs(entry - sl)
    tp1_dist = abs(entry - tp1)

    # Check if entry was ever filled
    entry_filled = False
    fill_bar     = None
    first_sl_bar = None
    first_tp1_bar= None

    for _, row in future.iterrows():
        if not entry_filled:
            if direction == "buy" and row["low"] <= entry:
                entry_filled = True
                fill_bar = row["time"]
            elif direction == "sell" and row["high"] >= entry:
                entry_filled = True
                fill_bar = row["time"]
            continue

        # After fill — check SL and TP
        if direction == "buy":
            if first_sl_bar is None and row["low"] <= sl:
                first_sl_bar = row["time"]
            if first_tp1_bar is None and row["high"] >= tp1:
                first_tp1_bar = row["time"]
        else:
            if first_sl_bar is None and row["high"] >= sl:
                first_sl_bar = row["time"]
            if first_tp1_bar is None and row["low"] <= tp1:
                first_tp1_bar = row["time"]

        if first_sl_bar and first_tp1_bar:
            break

    # What price did in first 5 candles after signal
    first_5 = future.head(5)
    price_range = f"H:{first_5['high'].max():.2f} L:{first_5['low'].min():.2f}"

    print(f"\n{'─'*75}")
    print(f"  {sig_time_str}  {direction.upper()}  E:{entry}  SL:{sl}  TP1:{tp1}")
    print(f"  Reported: {reported}")
    print(f"  SL distance: {round(sl_dist*10,1)} pips  |  TP1 distance: {round(tp1_dist*10,1)} pips")
    print(f"  First 5 M1 candles price range: {price_range}")
    print(f"  Entry filled: {entry_filled} {'at ' + str(fill_bar) if fill_bar else ''}")

    if entry_filled:
        if first_sl_bar and first_tp1_bar:
            outcome = "SL" if first_sl_bar < first_tp1_bar else "TP1"
            print(f"  ✅ SL hit at: {first_sl_bar}")
            print(f"  ✅ TP1 hit at: {first_tp1_bar}")
            print(f"  → ACTUAL OUTCOME: {outcome} hit first")
        elif first_sl_bar:
            print(f"  ✅ SL confirmed hit at: {first_sl_bar}")
            print(f"  ❌ TP1 never hit in 10h window")
            print(f"  → ACTUAL OUTCOME: SL_HIT ✓ (backtest correct)")
        elif first_tp1_bar:
            print(f"  ❌ SL never hit")
            print(f"  ✅ TP1 hit at: {first_tp1_bar}")
            print(f"  → ACTUAL OUTCOME: WIN — backtest reported SL_HIT INCORRECTLY ⚠️")
        else:
            print(f"  → Neither SL nor TP1 hit in 10h — trade still running or ghost")
    else:
        print(f"  → Entry never filled (GHOST) — backtest should show GHOST")

mt5.shutdown()
print(f"\n{'='*75}")
print("Done. If 'WIN — backtest reported SL_HIT INCORRECTLY' appears above,")
print("the backtest engine walk_to_outcome() has a bug.")
print("="*75)
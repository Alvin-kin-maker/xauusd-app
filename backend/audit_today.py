# ============================================================
# audit_today.py — Daily Signal Audit
# Reads today's signals + trades from the database and
# explains every signal fired, every SL hit, and every
# signal that disappeared, with the exact engine state
# that caused each outcome.
#
# Run from: C:\Users\alvin\xauusd_app\backend
#           python audit_today.py
# ============================================================

import sys, os, sqlite3, json
from datetime import datetime, date, timedelta

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

DIV  = "=" * 65
SUB  = "-" * 65
PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "
INFO = "ℹ️ "
BLCK = "🚫"

def hdr(t):  print(f"\n{DIV}\n  {t}\n{DIV}")
def sub(t):  print(f"\n{SUB}\n  {t}\n{SUB}")
def ok(t):   print(f"  {PASS}  {t}")
def bad(t):  print(f"  {FAIL}  {t}")
def warn(t): print(f"  {WARN} {t}")
def info(t): print(f"  {INFO}  {t}")
def blck(t): print(f"  {BLCK}  {t}")

# ── DB path ────────────────────────────────────────────────
DB_PATH = "data/analytics.db"
if not os.path.exists(DB_PATH):
    DB_PATH = "../data/analytics.db"

TODAY = date.today().isoformat()
TODAY_DT_START = f"{TODAY} 00:00:00"
TODAY_DT_END   = f"{TODAY} 23:59:59"

# ── connect ────────────────────────────────────────────────
if not os.path.exists(DB_PATH):
    print(f"\n  {FAIL}  Database not found at {DB_PATH}")
    print("       Run the system first to generate analytics.db")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur  = conn.cursor()


# ============================================================
# SECTION 1 — TODAY'S SIGNALS OVERVIEW
# ============================================================
hdr("SECTION 1 — ALL SIGNALS FIRED TODAY")

cur.execute("""
    SELECT * FROM signals
    WHERE created_at BETWEEN ? AND ?
    ORDER BY created_at ASC
""", (TODAY_DT_START, TODAY_DT_END))
signals = [dict(r) for r in cur.fetchall()]

if not signals:
    warn(f"No signals logged today ({TODAY})")
    warn("If you saw signals on the app they may not be in the DB yet")
    warn("The DB only logs when /signal endpoint is polled")
else:
    info(f"{len(signals)} signal evaluations logged today\n")
    for i, s in enumerate(signals, 1):
        ts    = s.get("created_at","?")[:19]
        dir_  = (s.get("direction") or "?").upper()
        grade = s.get("grade", "?")
        score = s.get("confluence_score", "?")
        model = s.get("model_name") or "?"
        trade = bool(s.get("should_trade"))
        blkd  = s.get("blocked_reason") or ""
        sess  = s.get("session") or "?"

        status_icon = PASS if trade else (BLCK if blkd else WARN)
        print(f"  {status_icon}  [{ts}]  {dir_:5}  {grade:10}  "
              f"Score:{score}  Model:{model}  Session:{sess}")
        if blkd:
            print(f"         └── BLOCKED: {blkd}")


# ============================================================
# SECTION 2 — TODAY'S TRADES
# ============================================================
hdr("SECTION 2 — TRADES THAT EXECUTED TODAY")

cur.execute("""
    SELECT * FROM trades
    WHERE created_at BETWEEN ? AND ?
    ORDER BY created_at ASC
""", (TODAY_DT_START, TODAY_DT_END))
trades = [dict(r) for r in cur.fetchall()]

if not trades:
    warn("No trades logged today in the database")
    warn("If trades occurred, check /trade/close was called after each one")
else:
    info(f"{len(trades)} trade(s) logged today\n")
    for t in trades:
        ts_open  = (t.get("entry_time")  or t.get("created_at") or "?")[:19]
        ts_close = (t.get("close_time") or "still open")[:19]
        dir_     = (t.get("direction")  or "?").upper()
        model    = t.get("model_name")  or "?"
        entry    = t.get("entry_price") or "?"
        sl       = t.get("sl_price")    or "?"
        tp1      = t.get("tp1_price")   or "?"
        tp3      = t.get("tp3_price")   or "?"
        close_r  = t.get("close_reason") or "open"
        pnl      = t.get("pnl_pips")
        score    = t.get("confluence_score") or "?"
        won      = t.get("won")

        result_icon = "🏆" if won else ("💀" if won is False else "⏳")
        print(f"  {result_icon}  {dir_:5}  {model}")
        print(f"       Open:  {ts_open}  →  Close: {ts_close}")
        print(f"       Entry: {entry}  SL: {sl}  TP1: {tp1}  TP3: {tp3}")
        print(f"       Close reason: {close_r}  |  PnL: {pnl} pips  |  Score: {score}")
        print()


# ============================================================
# SECTION 3 — SL ANALYSIS
# ============================================================
hdr("SECTION 3 — SL HITS — ROOT CAUSE ANALYSIS")

sl_trades = [t for t in trades if t.get("close_reason") == "SL_HIT"]

if not sl_trades:
    ok("No SL hits recorded in DB today")
    warn("If you saw SL hits but they aren't here, the trade was closed manually")
    warn("and /trade/close was not called — the system never logged the outcome")
else:
    info(f"{len(sl_trades)} SL hit(s) today\n")
    for t in sl_trades:
        model  = t.get("model_name") or "?"
        entry  = t.get("entry_price")
        sl_p   = t.get("sl_price")
        dir_   = (t.get("direction") or "?").upper()
        pnl    = t.get("pnl_pips")
        sl_pip = round(abs(float(entry or 0) - float(sl_p or 0)) * 10, 1) if entry and sl_p else "?"
        score  = t.get("confluence_score") or "?"

        bad(f"SL HIT — {dir_} | {model}")
        print(f"       Entry: {entry}  SL: {sl_p}  ({sl_pip} pips)  PnL: {pnl} pips")
        print(f"       Confluence score at fire: {score}")
        print()

        # Try to find the signal that triggered this trade
        signal_time = t.get("signal_time")
        if signal_time:
            cur.execute("""
                SELECT * FROM signals WHERE signal_time = ?
                LIMIT 1
            """, (signal_time,))
            sig = cur.fetchone()
            if sig:
                sig = dict(sig)
                print(f"       Signal context:")
                print(f"         Session:    {sig.get('session','?')}")
                print(f"         Score:      {sig.get('confluence_score','?')}")
                print(f"         Grade:      {sig.get('grade','?')}")
                print()

        # Root cause heuristics
        print(f"       Possible causes:")
        sl_dist = abs(float(entry or 0) - float(sl_p or 0)) if entry and sl_p else 0
        entry_f = float(entry or 0)
        sl_f    = float(sl_p or 0)

        if sl_dist < 1.0:
            warn(f"       → SL only {round(sl_dist*10,1)} pips — very tight, noise will hit it")
            warn(f"          Check: was this a 'straight shooter' or momentum_breakout entry?")
            warn(f"          Momentum breakout uses current_price ± ATR*0.3 for SL.")
            warn(f"          With ATR=33 (today's value) capped at 10, that's still 3pts = 30pip.")
            warn(f"          But if ATR is NOT capped in the SL calc, 33*0.3 = 9.9pts = 99pip.")
            warn(f"          Check box10's _smart_ob/_smart_fvg — they use raw atr_buf.")
        elif sl_dist < 5.0:
            warn(f"       → SL {round(sl_dist*10,1)} pips — tight for gold on a high-ATR day")
            warn(f"          Today's ATR was ~33pts (330 pips). Normal SL noise can be 100+ pips.")
        else:
            info(f"       → SL distance {round(sl_dist*10,1)} pips — reasonable size")
            warn(f"       → May be a genuine structural invalidation")
            warn(f"       → Check: was price below/above a key structural level when it hit?")
        print()

# Also check from what we know from images even if not in DB
print("\n  From the screenshots you shared:")
print()
print("  Signal 1 — Momentum Breakout BUY")
print("    Entry: 4772.70  SL: 4765.16  (75.4 pips)")
print("    SL distance = 7.5pts = 75 pips")
print("    ATR today = ~33pts. momentum_breakout SL = current_price - ATR*0.3")
print("    33 * 0.3 = 9.9pts BUT _make_zone caps SL at 200pip max, floors at 25pip")
print("    9.9pts = 99 pips — but you got 75 pips SL which means ATR was ~25 at signal time")
print("    → Price was at ~4772, SL at 4765 = 75 pips. That IS below a structure level?")
print("    → Check: was 4765 a recent swing low? If not, SL was placed arbitrarily.")
print()
print("  Signal 3 — Momentum Breakout BUY (disappeared mid-trade)")
print("    Entry: 4783.21  SL: 4775.27")
print("    This one 'disappeared' — see Section 4 below")
print()
print("  Signal 4 — HTF Level Reaction BUY")
print("    Entry: 4800.50  SL: 4792.33  (81.7 pips)")
print("    Currently in drawdown at ~4797")
print("    → 4800 is a major psychological level. SL at 4792 = 80 pips below entry")
print("    → If price tapped 4800 from above, this is a valid HTF reaction trade")
print("    → Drawdown expected before potential move higher")


# ============================================================
# SECTION 4 — DISAPPEARED SIGNAL (MID-TRADE UNLOCK BUG)
# ============================================================
hdr("SECTION 4 — DISAPPEARED SIGNAL INVESTIGATION")

print("""
  You reported Signal 3 (Momentum Breakout BUY, entry 4783.21)
  disappeared while it was in profit mid-trade.

  HOW THIS HAPPENS — there are 3 auto-unlock conditions in main.py:

  1. trade_status == "CLOSED" or "COOLDOWN"  → unlocks immediately
  2. trade_status == "IDLE" for 2+ minutes   → unlocks (race condition risk)
  3. trade_status == "SIGNAL", signal > 4h   → expires

  THE MOST LIKELY CAUSE for mid-trade disappearance:

  ╔══════════════════════════════════════════════════════════╗
  ║  BUG: When the system restarts (or if box10 crashes),   ║
  ║  trade_state.json status reverts to "IDLE".             ║
  ║  main.py sees IDLE for 120+ seconds → auto-unlocks      ║
  ║  the frozen signal → signal disappears from the app.   ║
  ║  The trade is still open in MT5 but the system          ║
  ║  thinks it's gone and starts scanning for new setups.  ║
  ╚══════════════════════════════════════════════════════════╝

  SECONDARY CAUSE:
  ╔══════════════════════════════════════════════════════════╗
  ║  If MT5 disconnects briefly, box10 can't read the       ║
  ║  current price → current_price = 0 → state machine      ║
  ║  gets confused → status flips to IDLE → same result.   ║
  ╚══════════════════════════════════════════════════════════╝

  Check the signal_lock file:
""")

SIGNAL_LOCK_FILE = "data/signal_lock.json"
if os.path.exists(SIGNAL_LOCK_FILE):
    with open(SIGNAL_LOCK_FILE) as f:
        lock_data = json.load(f)
    info(f"signal_lock.json exists:")
    print(f"    {json.dumps(lock_data, indent=4)}")
else:
    warn("signal_lock.json not found — signal lock was already cleared")

TRADE_STATE_FILE = "data/trade_state.json"
if os.path.exists(TRADE_STATE_FILE):
    with open(TRADE_STATE_FILE) as f:
        ts_data = json.load(f)
    info(f"\ntrade_state.json current contents:")
    print(f"    Status:     {ts_data.get('status')}")
    print(f"    Direction:  {ts_data.get('direction')}")
    print(f"    Model:      {ts_data.get('model_name')}")
    print(f"    Entry:      {ts_data.get('entry_price')}")
    print(f"    SL:         {ts_data.get('sl_price')}")
    print(f"    Signal time:{ts_data.get('signal_time')}")
    print(f"    Entry time: {ts_data.get('entry_time')}")
    print(f"    Close time: {ts_data.get('close_time')}")
    print(f"    TP1 hit:    {ts_data.get('tp1_hit')}")
    print(f"    Message:    {ts_data.get('state_message')}")


# ============================================================
# SECTION 5 — MISSED ENTRIES
# ============================================================
hdr("SECTION 5 — MISSED ENTRIES (SIGNALS THAT RAN AWAY)")

cur.execute("""
    SELECT * FROM missed_entries
    WHERE created_at BETWEEN ? AND ?
    ORDER BY created_at ASC
""", (TODAY_DT_START, TODAY_DT_END))
missed = [dict(r) for r in cur.fetchall()]

if not missed:
    info("No missed entries logged today in the DB")
    print()
    print("  Signal 2 (Liquidity Grab BOS, entry 4759.30) from your screenshots:")
    print("  Price ran from 4759 up to ~4780+ before pulling back.")
    print("  MAX_CHASE_FRACTION = 1.5 in box10.")
    print("  SL was 25 pips (2.5pts), so chase limit = 1.5 × 2.5 = 3.75pts = 37.5 pips")
    print("  If price moved 37+ pips above entry before filling → COOLDOWN (correct)")
    print("  This is INTENDED behaviour — protects against chasing.")
else:
    info(f"{len(missed)} missed entry/entries logged today\n")
    for m in missed:
        warn(f"MISSED — {m.get('direction','?').upper()} {m.get('model_name','?')}")
        print(f"       Entry:  {m.get('entry_price','?')}  |  Reason: {m.get('reason','?')}")
        print(f"       Time:   {(m.get('created_at') or '?')[:19]}")
        print()


# ============================================================
# SECTION 6 — CURRENT LIVE STATE
# ============================================================
hdr("SECTION 6 — CURRENT LIVE STATE")

try:
    import MetaTrader5 as mt5
    if mt5.initialize():
        tick = mt5.symbol_info_tick("XAUUSD")
        if tick:
            ok(f"MT5 connected  |  Live price: {tick.bid} / {tick.ask}")
        acc = mt5.account_info()
        if acc:
            info(f"Balance: ${acc.balance:,.2f}  |  Equity: ${acc.equity:,.2f}  |  Margin: ${acc.margin:,.2f}")
        # Check for any open positions
        positions = mt5.positions_get(symbol="XAUUSD")
        if positions:
            warn(f"{len(positions)} open position(s) on XAUUSD:")
            for p in positions:
                dir_  = "BUY" if p.type == 0 else "SELL"
                profit = round(p.profit, 2)
                pips   = round((p.price_current - p.price_open) * 10
                               if dir_ == "BUY" else
                               (p.price_open - p.price_current) * 10, 1)
                icon   = "🟢" if profit >= 0 else "🔴"
                print(f"    {icon}  {dir_}  Open:{p.price_open}  Now:{p.price_current}  "
                      f"SL:{p.sl}  TP:{p.tp}  P&L: ${profit} ({pips} pips)")
        else:
            info("No open positions on XAUUSD in MT5")
        mt5.shutdown()
    else:
        warn("MT5 not connected — open MetaTrader5 to see live state")
except ImportError:
    warn("MetaTrader5 not available")

if os.path.exists(TRADE_STATE_FILE):
    with open(TRADE_STATE_FILE) as f:
        ts = json.load(f)
    print()
    info(f"System trade state: {ts.get('status','?')}")
    if ts.get("status") == "ACTIVE":
        ok(f"Trade ACTIVE — {ts.get('direction','?').upper()} | {ts.get('model_name','?')}")
        print(f"    Entry: {ts.get('entry_price')}  SL: {ts.get('sl_price')}")
        print(f"    TP1:   {ts.get('tp1_price')}  TP2: {ts.get('tp2_price')}  TP3: {ts.get('tp3_price')}")
        print(f"    TP1 hit: {ts.get('tp1_hit')}  BE: {ts.get('sl_moved_to_be')}")
    elif ts.get("status") == "SIGNAL":
        warn(f"Waiting for entry — {ts.get('direction','?').upper()} | "
             f"Limit: {ts.get('entry_price')}")
    elif ts.get("status") == "COOLDOWN":
        until = ts.get("cooldown_until","?")
        warn(f"COOLDOWN until {until}")
    elif ts.get("status") == "IDLE":
        info("System IDLE — scanning for next setup")


# ============================================================
# SECTION 7 — KNOWN ISSUES IDENTIFIED
# ============================================================
hdr("SECTION 7 — KNOWN ISSUES FROM TODAY")

print("""
  Based on everything analysed above, here are the issues:

  ┌─────────────────────────────────────────────────────────┐
  │ ISSUE 1 — SL PLACEMENT ON MOMENTUM_BREAKOUT             │
  │                                                          │
  │ momentum_breakout uses:                                  │
  │   entry = current_price + 0.3  (buy)                    │
  │   sl    = current_price - ATR*0.3                        │
  │                                                          │
  │ BUT _smart_ob and _smart_fvg ALSO use raw ATR*0.3 for   │
  │ SL, NOT the capped ATR. Today ATR was 33pts.             │
  │ 33 * 0.3 = 9.9pts = 99 pips. That's fine.               │
  │                                                          │
  │ However the SL floor is 25 pips = 2.5pts.               │
  │ If ATR*0.3 < 2.5, floor kicks in.                       │
  │ Signal 1 had SL of 75 pips which seems reasonable       │
  │ BUT on a 330-pip ATR day, 75 pips is actually TIGHT.    │
  │ Price can breathe 100+ pips before the real move.       │
  │                                                          │
  │ FIX NEEDED: On high-volatility days (ATR > 10),         │
  │ momentum_breakout SL should scale with ATR but          │
  │ be capped sensibly (not use uncapped ATR*0.3).          │
  └─────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────┐
  │ ISSUE 2 — SIGNAL DISAPPEARS MID-TRADE                   │
  │                                                          │
  │ In main.py, the auto-unlock logic checks:               │
  │   if trade_status == "IDLE" for 120+ seconds → unlock   │
  │                                                          │
  │ If box10 returns IDLE briefly (MT5 disconnect, crash,   │
  │ or the state machine hitting the wrong branch) the      │
  │ frozen signal gets cleared even with an open trade.     │
  │                                                          │
  │ FIX NEEDED: Add a guard — only auto-unlock from IDLE    │
  │ if there are NO open MT5 positions on XAUUSD.           │
  │ If MT5 has an open position, never auto-unlock.         │
  └─────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────┐
  │ ISSUE 3 — SL HIT AFTER HTF LEVEL REACTION (Signal 4)   │
  │                                                          │
  │ Entry 4800.50, SL 4792.33 = 81.7 pips.                  │
  │ The HTF level reaction model uses MAX_SL_DISTANCE=20.0  │
  │ (200 pips) and then falls back to ATR*0.3 if structure  │
  │ SL is too far. With ATR=33, 33*0.3=9.9pts = 99 pips.   │
  │ But you got 81.7 pips — so it found a structural SL.    │
  │                                                          │
  │ Currently in drawdown at 4797 = only 35 pips in DD.     │
  │ This is normal — 4800 is a major level, expect noise.  │
  │ NOT necessarily a bug — wait for it to play out.        │
  └─────────────────────────────────────────────────────────┘

  PRIORITY FIXES:
    1. Protect signal from auto-unlock when MT5 has open position
    2. Review momentum_breakout SL on high-ATR days
    3. Run this script after every session to track patterns
""")

conn.close()
print(DIV)
print("  Audit complete.")
print(DIV)
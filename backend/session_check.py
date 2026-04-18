# ============================================================
# session_check.py — Session Diagnostic Tool
# Run this after ANY session to understand exactly what happened:
#   - What setups were visible on the chart
#   - Why the system fired or didn't fire
#   - Why a signal hit SL
#   - What kill switches were active
#   - What the market structure looked like all day
#
# Usage:
#   python session_check.py           → live current state
#   python session_check.py --today   → full today summary
#
# Run from: C:\Users\alvin\xauusd_app\backend
# ============================================================

import sys, os, json, sqlite3, argparse
from datetime import datetime, date, timedelta

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

# ── Formatting ────────────────────────────────────────────
D  = "=" * 65
SD = "-" * 55
def hdr(t):   print(f"\n{D}\n  {t}\n{D}")
def sub(t):   print(f"\n{SD}\n  {t}\n{SD}")
def ok(t):    print(f"  ✅  {t}")
def bad(t):   print(f"  ❌  {t}")
def warn(t):  print(f"  ⚠️   {t}")
def info(t):  print(f"  ℹ️   {t}")
def blk(t):   print(f"  🚫  {t}")

# ── Args ──────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--today", action="store_true", help="Full today summary from DB")
parser.add_argument("--live",  action="store_true", help="Run all engines live right now (needs MT5)")
args = parser.parse_args()

TODAY      = date.today().isoformat()
TODAY_START = f"{TODAY} 00:00:00"
TODAY_END   = f"{TODAY} 23:59:59"

# ── DB path ───────────────────────────────────────────────
DB_PATH = "data/analytics.db"
if not os.path.exists(DB_PATH):
    DB_PATH = "../data/analytics.db"

# ============================================================
# SECTION 1 — TODAY'S SIGNAL HISTORY (from DB)
# ============================================================
hdr("SECTION 1 — TODAY'S SIGNALS (from database)")

if not os.path.exists(DB_PATH):
    warn("No database found — system hasn't logged any signals yet")
    warn(f"Expected at: {DB_PATH}")
else:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()

    cur.execute("""
        SELECT * FROM signals
        WHERE created_at BETWEEN ? AND ?
        ORDER BY created_at ASC
    """, (TODAY_START, TODAY_END))
    signals = [dict(r) for r in cur.fetchall()]

    if not signals:
        warn(f"No signals logged today ({TODAY})")
    else:
        info(f"{len(signals)} signal evaluations today\n")
        for s in signals:
            ts    = s.get("created_at","?")[:19]
            dir_  = (s.get("direction") or "?").upper()
            grade = s.get("grade","?")
            score = s.get("confluence_score","?")
            model = s.get("model_name") or "?"
            trade = bool(s.get("should_trade"))
            blkd  = s.get("blocked_reason") or ""
            sess  = s.get("session") or "?"
            icon  = "✅" if trade else ("🚫" if blkd else "⚠️")
            print(f"  {icon}  [{ts}]  {dir_:5}  {grade:10}  Score:{score}  {model}  ({sess})")
            if blkd:
                print(f"         └── BLOCKED: {blkd}")

    # Today's trades
    cur.execute("""
        SELECT * FROM trades
        WHERE created_at BETWEEN ? AND ?
        ORDER BY created_at ASC
    """, (TODAY_START, TODAY_END))
    trades = [dict(r) for r in cur.fetchall()]

    sub("Trades Executed Today")
    if not trades:
        warn("No trades logged — /trade/close not called after each trade")
        warn("This means strike tracking and win-rate analytics are blind")
    else:
        for t in trades:
            dir_   = (t.get("direction") or "?").upper()
            model  = t.get("model_name") or "?"
            entry  = t.get("entry_price") or "?"
            sl     = t.get("sl_price") or "?"
            close_r= t.get("close_reason") or "open"
            pnl    = t.get("pnl_pips")
            icon   = "🏆" if t.get("won") else ("💀" if t.get("won") is False else "⏳")
            print(f"  {icon}  {dir_:5}  {model}")
            print(f"       Entry:{entry}  SL:{sl}  Close:{close_r}  PnL:{pnl}pips")

    conn.close()


# ============================================================
# SECTION 2 — CURRENT TRADE STATE
# ============================================================
hdr("SECTION 2 — CURRENT SYSTEM STATE")

TRADE_STATE  = "data/trade_state.json"
SIGNAL_LOCK  = "data/signal_lock.json"
STRIKE_STATE = "data/strike_state.json"

if os.path.exists(TRADE_STATE):
    with open(TRADE_STATE) as f: ts = json.load(f)
    status = ts.get("status","?")
    print(f"  Trade status:  {status}")
    if status == "ACTIVE":
        ok(f"ACTIVE — {ts.get('direction','?').upper()} | {ts.get('model_name','?')}")
        print(f"    Entry: {ts.get('entry_price')}  SL: {ts.get('sl_price')}")
        print(f"    TP1:   {ts.get('tp1_price')}  TP2: {ts.get('tp2_price')}  TP3: {ts.get('tp3_price')}")
        print(f"    TP1 hit: {ts.get('tp1_hit')}  BE: {ts.get('sl_moved_to_be')}")
    elif status == "SIGNAL":
        warn(f"Waiting for entry — {ts.get('direction','?').upper()} limit at {ts.get('entry_price')}")
        info(f"Signal time: {ts.get('signal_time','?')[:19]}")
    elif status == "COOLDOWN":
        warn(f"In cooldown until: {ts.get('cooldown_until','?')[:19]}")
    elif status == "IDLE":
        info("System IDLE — scanning for next setup")
    last_msg = ts.get("state_message","")
    if last_msg:
        info(f"Last message: {last_msg}")
else:
    warn("trade_state.json not found")

if os.path.exists(SIGNAL_LOCK):
    with open(SIGNAL_LOCK) as f: sl = json.load(f)
    locked = sl.get("locked", False)
    if locked:
        warn(f"Signal LOCKED — {sl.get('direction','?')} | {sl.get('model_name','?')}")
        info(f"Entry: {sl.get('entry')}  SL: {sl.get('sl')}  Score: {sl.get('frozen_score')}")
    else:
        ok("No signal locked")

if os.path.exists(STRIKE_STATE):
    with open(STRIKE_STATE) as f: ss = json.load(f)
    if ss.get("system_paused"):
        bad(f"SYSTEM PAUSED: {ss.get('system_pause_reason')}")
    models_with_strikes = {k:v for k,v in ss.get("models",{}).items() if v.get("strikes",0)>0}
    if models_with_strikes:
        warn("Models with strikes:")
        for name, data in models_with_strikes.items():
            strikes = data.get("strikes", 0)
            susp    = data.get("suspended_until")
            print(f"    {name}: {strikes} strike(s)" + (f" — suspended until {susp[:16]}" if susp else ""))


# ============================================================
# SECTION 3 — NEWS FILTER STATUS
# ============================================================
hdr("SECTION 3 — NEWS FILTER (Box 11)")

try:
    from engines.box11_news import run as run_b11, MANUAL_BLACKOUT_FILE, NEWS_CACHE_FILE
    b11 = run_b11()

    if b11["is_blocked"]:
        blk(f"TRADING BLOCKED: {b11['block_reason']}")
    else:
        ok("No news block right now")

    if b11["medium_warning"]:
        warn(f"Warning: {b11['medium_warning']}")

    if b11["upcoming_events"]:
        print("\n  Upcoming events (next 4h):")
        for ev in b11["upcoming_events"]:
            icon = "🔴" if ev["impact"]=="high" else "🟡"
            print(f"    {icon} {ev['minutes_away']:.0f}min — {ev['title']} ({ev['currency']})")
    else:
        ok("No major events in next 4 hours — clear to trade")

    print(f"\n  News score: {b11['engine_score']}/100")
except Exception as e:
    warn(f"Box 11 unavailable: {e}")


# ============================================================
# SECTION 4 — LIVE ENGINE SNAPSHOT (needs MT5)
# ============================================================
hdr("SECTION 4 — LIVE ENGINE SNAPSHOT")

try:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        warn("MT5 not running — start MetaTrader5 first for live analysis")
        sys.exit(0)

    tick = mt5.symbol_info_tick("XAUUSD")
    if tick:
        ok(f"Live price: {tick.bid:.2f} / {tick.ask:.2f}  spread: {round((tick.ask-tick.bid)/0.1,1)}pip")

    acc = mt5.account_info()
    if acc:
        info(f"Balance: ${acc.balance:,.2f}  Equity: ${acc.equity:,.2f}")

    positions = mt5.positions_get(symbol="XAUUSD")
    if positions:
        warn(f"{len(positions)} open position(s) in MT5:")
        for p in positions:
            d_    = "BUY" if p.type==0 else "SELL"
            pips  = round((p.price_current-p.price_open)*10 if p.type==0 else (p.price_open-p.price_current)*10, 1)
            icon  = "🟢" if p.profit>=0 else "🔴"
            print(f"    {icon}  {d_}  Open:{p.price_open}  Now:{p.price_current}  SL:{p.sl}  "
                  f"P&L:${p.profit:.2f} ({pips:+.1f}pips)")
    else:
        info("No open positions in MT5")

    from data.candle_store import store
    store.refresh()
    ok("Candles refreshed")

    from engines.box1_market_context import run as run_b1
    from engines.box2_trend          import run as run_b2
    from engines.box3_liquidity      import run as run_b3
    from engines.box4_levels         import run as run_b4
    from engines.box5_momentum       import run as run_b5
    from engines.box6_sentiment      import run as run_b6
    from engines.box7_entry          import run as run_b7
    from engines.box8_model          import run as run_b8
    from engines.box9_confluence     import run as run_b9
    from engines.box13_breakout      import run as run_b13

    b1  = run_b1(store)
    b2  = run_b2(store)
    b3  = run_b3(store)
    b4  = run_b4(store)
    b5  = run_b5(store)
    b6  = run_b6(store)
    b7  = run_b7(store, b2)
    b13 = run_b13(store, b1, b2, b3, b4, b5, b7)
    b8  = run_b8(b1, b2, b3, b4, b5, b6, b7, b13)
    b9  = run_b9(b1, b2, b3, b4, b5, b6, b7, b8, b13)

    sub("Market Context")
    print(f"  Session:    {b1['primary_session']} ({b1['current_gmt']} GMT)")
    print(f"  ATR:        {b1['atr']}  |  Volatility: {b1['volatility_regime']}")
    print(f"  Spread:     {b1['spread_pips']}pip  |  Tradeable: {b1['is_tradeable']}")

    sub("Trend Structure")
    print(f"  Overall: {b2['overall_bias'].upper()}  "
          f"Internal: {b2.get('internal_bias','?').upper()}  "
          f"External: {b2.get('external_bias','?').upper()}")
    for tf in ["D1","H4","H1","M15"]:
        data = b2["timeframes"].get(tf,{})
        bias = data.get("bias","?")
        mss  = f" [MSS:{data.get('mss_type','?')}]" if data.get("mss_active") else ""
        icon = "🟢" if bias=="bullish" else "🔴" if bias=="bearish" else "⚪"
        print(f"    {icon} {tf:4} {bias}{mss}")

    sub("Liquidity")
    print(f"  Sweep just happened: {b3['sweep_just_happened']}  Direction: {b3.get('sweep_direction','none')}")
    print(f"  PDH swept: {b3['pdh_swept']}  PDL swept: {b3['pdl_swept']}")
    print(f"  Asian H swept: {b3['asian_high_swept']}  Asian L swept: {b3['asian_low_swept']}")

    sub("Premium / Discount")
    print(f"  Price zone:   {b4.get('price_zone','?').upper()}")
    print(f"  Equilibrium:  {b4.get('equilibrium','?')}")
    print(f"  At key level: {b4.get('at_key_level')}  "
          + (f"→ {b4['closest_level']['label']} ({b4['closest_level'].get('level','')})"
             if b4.get('closest_level') else ""))

    sub("Momentum")
    print(f"  RSI M15: {b5.get('rsi_m15','?')}  H1: {b5.get('rsi_h1','?')}")
    print(f"  Divergence: {b5.get('divergence_active')}  Volume spike: {b5.get('volume_m15',{}).get('is_spike')}")

    sub("COT Sentiment")
    cot = b6.get("cot",{})
    if b6.get("cot_available"):
        print(f"  Sentiment: {b6['cot_sentiment'].upper()}  Long%: {b6['cot_long_pct']}%")
        print(f"  Net position: {cot.get('net_position','?')}  Week change: {cot.get('net_change','?')}")
        if b6["cot_long_pct"] >= 75:
            warn(f"  COT extreme bullish ({b6['cot_long_pct']}%) — needs bearish sweep for SELL bypass")
    else:
        warn("COT unavailable")

    sub("Model Validation")
    print(f"  Active model:    {b8['best_model_name'] or 'None'}")
    print(f"  Validated count: {b8['validated_count']}/13")
    print(f"  Model score:     {b8['best_model_score']}")
    if b8.get("validated_models"):
        for name, m in b8["validated_models"].items():
            print(f"    ✓ {name}: {m['score']}")

    sub("Confluence Result")
    print(f"  Direction:    {b9['direction'].upper()}")
    print(f"  Score:        {b9['score']}/100")
    print(f"  Grade:        {b9['grade']}")
    print(f"  Should trade: {b9['should_trade']}")

    if b9["kill_switches"]:
        print(f"\n  🚫 Kill Switches Active:")
        for k in b9["kill_switches"]:
            print(f"     {k}")
    else:
        ok("No kill switches active")

    print(f"\n  Engine scores:")
    for name, data in b9["engines"].items():
        bar = "█" * int(data["contribution"]/2)
        print(f"    {name:20} {data['raw']:3}/100 → {data['contribution']:5.1f}pts  {bar}")

    # Final verdict
    sub("VERDICT")
    if b9["should_trade"] and not b11["is_blocked"]:
        ok(f"SETUP VALID — {b9['direction'].upper()} | {b8['best_model_name']} | Score: {b9['score']}")
    elif b11["is_blocked"]:
        blk(f"NEWS BLOCKED — {b11['block_reason']}")
    elif b9["kill_switches"]:
        blk(f"KILL SWITCHES ACTIVE — {len(b9['kill_switches'])} blocking")
        for k in b9["kill_switches"]:
            print(f"     {k}")
    elif b9["grade"] in ["WEAK","NO_TRADE"]:
        warn(f"WEAK SETUP — Score: {b9['score']} Grade: {b9['grade']}")
    else:
        warn(f"No trade — Grade: {b9['grade']} Score: {b9['score']}")

    mt5.shutdown()

except ImportError as e:
    warn(f"MT5 not available: {e}")
except Exception as e:
    import traceback
    warn(f"Engine error: {e}")
    traceback.print_exc()

print(f"\n{D}")
print(f"  Diagnostic complete — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(D)
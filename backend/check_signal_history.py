# ============================================================
# check_signal_history.py — AURUM Signal History Checker
# Run from: cd C:\Users\alvin\xauusd_app\backend
#           python check_signal_history.py
# ============================================================

import sys
import os
import sqlite3
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join("..", "data", "analytics.db")
# Also try local data folder
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.join("data", "analytics.db")


def check_signal_log():
    print("\n" + "="*60)
    print("SIGNAL HISTORY (from analytics.db)")
    print("="*60)

    if not os.path.exists(DB_PATH):
        print(f"  No database found at: {DB_PATH}")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # ── Signals table ──────────────────────────────────────
        cursor.execute("""
            SELECT signal_time, direction, model_name,
                   confluence_score, grade, should_trade,
                   blocked_reason, session, created_at
            FROM signals
            ORDER BY created_at DESC
            LIMIT 50
        """)
        rows = cursor.fetchall()
        print(f"\n  {len(rows)} signals logged:\n")
        for row in rows:
            d = dict(row)
            blocked = f"  BLOCKED: {d['blocked_reason']}" if d.get('blocked_reason') else ""
            print(
                f"  [{d.get('created_at','?')[:19]}]  "
                f"{(d.get('direction') or '?').upper():5}  "
                f"Grade:{d.get('grade','?'):10}  "
                f"Score:{d.get('confluence_score','?')}  "
                f"Model:{d.get('model_name','?')}  "
                f"Trade:{bool(d.get('should_trade'))}"
                f"{blocked}"
            )

        # ── Trades table ───────────────────────────────────────
        cursor.execute("""
            SELECT signal_time, entry_time, close_time,
                   direction, model_name, entry_price,
                   sl_price, tp1_price, tp2_price, tp3_price,
                   sl_pips, lot_size, close_reason, pnl_pips,
                   pnl_usd, tp1_hit, tp2_hit, grade,
                   confluence_score, session
            FROM trades
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = cursor.fetchall()
        print(f"\n  {len(rows)} trades logged:\n")
        for row in rows:
            d = dict(row)
            pnl = d.get('pnl_pips')
            pnl_str = f"+{pnl}" if pnl and pnl > 0 else str(pnl)
            print(
                f"  [{d.get('signal_time','?')[:19]}]  "
                f"{(d.get('direction') or '?').upper():5}  "
                f"Entry:{d.get('entry_price','?')}  "
                f"SL:{d.get('sl_price','?')}  "
                f"SLpips:{d.get('sl_pips','?')}  "
                f"Result:{d.get('close_reason','open')}  "
                f"PnL:{pnl_str}pips  "
                f"Model:{d.get('model_name','?')}"
            )

        # ── Missed entries ─────────────────────────────────────
        cursor.execute("""
            SELECT signal_time, model_name, direction,
                   entry_price, reason, created_at
            FROM missed_entries
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = cursor.fetchall()
        if rows:
            print(f"\n  {len(rows)} missed entries:\n")
            for row in rows:
                d = dict(row)
                print(
                    f"  [{d.get('created_at','?')[:19]}]  "
                    f"{(d.get('direction') or '?').upper():5}  "
                    f"Entry:{d.get('entry_price','?')}  "
                    f"Model:{d.get('model_name','?')}  "
                    f"Reason:{d.get('reason','?')}"
                )

        conn.close()

    except Exception as e:
        print(f"  DB error: {e}")
        import traceback
        traceback.print_exc()


def check_signal_lock():
    print("\n" + "="*60)
    print("LAST LOCKED SIGNAL")
    print("="*60)

    for path in [
        os.path.join("..", "data", "signal_lock.json"),
        os.path.join("data", "signal_lock.json"),
    ]:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    lock = json.load(f)
                for k, v in lock.items():
                    print(f"  {k:25}: {v}")
            except Exception as e:
                print(f"  Lock file error: {e}")
            return

    print("  No signal lock file found.")


def check_trade_state():
    print("\n" + "="*60)
    print("CURRENT TRADE STATE")
    print("="*60)

    for path in [
        os.path.join("..", "data", "trade_state.json"),
        os.path.join("data", "trade_state.json"),
    ]:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    state = json.load(f)
                for k, v in state.items():
                    print(f"  {k:25}: {v}")
            except Exception as e:
                print(f"  State file error: {e}")
            return

    print("  No trade state file found.")


def check_live_engines():
    print("\n" + "="*60)
    print("LIVE ENGINE SNAPSHOT (requires MT5 open)")
    print("="*60)

    try:
        import MetaTrader5 as mt5
        from data.candle_store import store
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

        mt5.initialize()
        store.refresh()

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

        print(f"\n  Session : {b1['primary_session']}  ATR:{b1['atr']}  Volatility:{b1['volatility_regime']}  Tradeable:{b1['is_tradeable']}")
        print(f"  Trend   : {b2['overall_bias'].upper()}  D1:{b2['timeframes']['D1']['bias']}  H4:{b2['timeframes']['H4']['bias']}  H1:{b2['timeframes']['H1']['bias']}  M15:{b2['timeframes']['M15']['bias']}")
        print(f"  Sweep   : {b3['sweep_just_happened']}  Dir:{b3['sweep_direction']}  PDH:{b3['pdh_swept']}  PDL:{b3['pdl_swept']}")
        print(f"  Zone    : {b4.get('price_zone','?')}  Equilibrium:{b4.get('equilibrium','?')}  AtLevel:{b4['at_key_level']}")
        print(f"  RSI     : M5:{b5['rsi_m5']}  M15:{b5['rsi_m15']}  H1:{b5['rsi_h1']}  Divergence:{b5['divergence_active']}")
        print(f"  COT     : {b6['cot_sentiment']} ({b6['cot_long_pct']}% long)  OI:{b6['oi_signal']}")
        print(f"  Model   : {b8['best_model_name']}  Score:{b8['best_model_score']}  Validated:{b8['validated_count']}/13")
        print(f"\n  CONFLUENCE: {b9['direction'].upper()}  Score:{b9['score']}/100  Grade:{b9['grade']}  ShouldTrade:{b9['should_trade']}")

        print(f"\n  Engine Scores:")
        for name, data in b9['engines'].items():
            bar = "█" * int(data['contribution'])
            print(f"    {name:20} {data['raw']:3}/100  {data['contribution']:4.1f}pts  {bar}")

        if b9['kill_switches']:
            print(f"\n  KILL SWITCHES:")
            for k in b9['kill_switches']:
                print(f"    ⛔ {k}")
        else:
            print(f"\n  ✅ No kill switches — clear to trade")

        mt5.shutdown()

    except Exception as e:
        print(f"  Engine error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("\n" + "="*60)
    print("  AURUM — SIGNAL HISTORY & ENGINE CHECKER")
    print("="*60)
    check_signal_log()
    check_signal_lock()
    check_trade_state()
    check_live_engines()
    print("\n" + "="*60)
    print("  DONE")
    print("="*60 + "\n")
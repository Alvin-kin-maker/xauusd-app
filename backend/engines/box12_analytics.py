# ============================================================
# box12_analytics.py — Analytics Engine
# Logs every trade, tracks performance, generates stats
# Storage: SQLite database
# ============================================================

import sys
import os
import json
import sqlite3
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import DB_PATH


# ------------------------------------------------------------
# DATABASE SETUP
# ------------------------------------------------------------

def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Create all tables if they don't exist."""
    conn = get_db_connection()
    c    = conn.cursor()

    # Trades table
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id        TEXT UNIQUE,
            symbol          TEXT DEFAULT 'XAUUSD',
            direction       TEXT,
            model_name      TEXT,
            confluence_score REAL,
            grade           TEXT,

            entry_price     REAL,
            sl_price        REAL,
            tp1_price       REAL,
            tp2_price       REAL,
            tp3_price       REAL,
            sl_pips         REAL,
            lot_size        REAL,
            entry_zone      TEXT,

            signal_time     TEXT,
            entry_time      TEXT,
            close_time      TEXT,
            close_reason    TEXT,
            pnl_pips        REAL,
            pnl_usd         REAL,

            tp1_hit         INTEGER DEFAULT 0,
            tp2_hit         INTEGER DEFAULT 0,
            sl_moved_to_be  INTEGER DEFAULT 0,

            session         TEXT,
            atr_at_entry    REAL,

            b1_score        REAL,
            b2_score        REAL,
            b3_score        REAL,
            b4_score        REAL,
            b5_score        REAL,
            b6_score        REAL,
            b7_score        REAL,
            b8_score        REAL,
            b9_score        REAL,

            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Signals table (every signal generated, traded or not)
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_time     TEXT,
            direction       TEXT,
            model_name      TEXT,
            confluence_score REAL,
            grade           TEXT,
            should_trade    INTEGER,
            blocked_reason  TEXT,
            session         TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Missed entries table
    c.execute("""
        CREATE TABLE IF NOT EXISTS missed_entries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_time TEXT,
            model_name  TEXT,
            direction   TEXT,
            entry_price REAL,
            reason      TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Daily performance summary
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT UNIQUE,
            total_trades INTEGER DEFAULT 0,
            wins        INTEGER DEFAULT 0,
            losses      INTEGER DEFAULT 0,
            breakeven   INTEGER DEFAULT 0,
            total_pips  REAL DEFAULT 0,
            total_pnl   REAL DEFAULT 0,
            winrate     REAL DEFAULT 0,
            best_trade  REAL DEFAULT 0,
            worst_trade REAL DEFAULT 0,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    print("[Analytics] Database initialized ✓")


# ------------------------------------------------------------
# TRADE LOGGING
# ------------------------------------------------------------

def log_signal(b9, b11, blocked=False, blocked_reason=None):
    """
    Log every signal generated — traded or not.
    DEDUP: skip if same direction + model was logged within 5 minutes.
    Prevents 20 identical rows when a setup persists across poll cycles.
    """
    conn = get_db_connection()
    try:
        # Check for duplicate within last 5 minutes
        row = conn.execute("""
            SELECT created_at FROM signals
            WHERE direction = ? AND model_name = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (
            b9.get("direction"),
            b9.get("model_name"),
        )).fetchone()

        if row:
            try:
                last_logged = datetime.fromisoformat(row[0])
                seconds_since = (datetime.now() - last_logged).total_seconds()
                if seconds_since < 300:  # 5 minute cooldown per direction+model
                    return  # Same signal still active — skip duplicate log
            except Exception:
                pass

        conn.execute("""
            INSERT INTO signals
            (signal_time, direction, model_name, confluence_score, grade,
             should_trade, blocked_reason, session)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            b9.get("direction"),
            b9.get("model_name"),
            b9.get("score"),
            b9.get("grade"),
            1 if b9.get("should_trade") and not blocked else 0,
            blocked_reason,
            b9.get("session"),
        ))
        conn.commit()
    except Exception as e:
        print(f"[Analytics] Signal log error: {e}")
    finally:
        conn.close()


def log_trade_opened(trade_id, b9, b10, b1, b2, b3, b4, b5, b6, b7, b8):
    """Log when a trade is opened."""
    conn   = get_db_connection()
    levels = b10.get("levels") or {}

    try:
        conn.execute("""
            INSERT OR IGNORE INTO trades
            (trade_id, direction, model_name, confluence_score, grade,
             entry_price, sl_price, tp1_price, tp2_price, tp3_price,
             sl_pips, lot_size, entry_zone, signal_time, entry_time,
             session, atr_at_entry,
             b1_score, b2_score, b3_score, b4_score, b5_score,
             b6_score, b7_score, b8_score, b9_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_id,
            b9.get("direction"),
            b10.get("model_name"),
            b9.get("score"),
            b9.get("grade"),
            levels.get("entry"),
            levels.get("sl"),
            levels.get("tp1"),
            levels.get("tp2"),
            levels.get("tp3"),
            levels.get("sl_pips"),
            b10.get("lot_size"),
            levels.get("entry_zone_label"),
            b10["trade_state"].get("signal_time"),
            datetime.now().isoformat(),
            b1.get("primary_session"),
            b1.get("atr"),
            b1.get("engine_score"),
            b2.get("engine_score"),
            b3.get("engine_score"),
            b4.get("engine_score"),
            b5.get("engine_score"),
            b6.get("engine_score"),
            b7.get("engine_score"),
            b8.get("engine_score"),
            b9.get("score"),
        ))
        conn.commit()
        print(f"[Analytics] Trade opened: {trade_id}")
    except Exception as e:
        print(f"[Analytics] Trade open log error: {e}")
    finally:
        conn.close()


def log_trade_closed(trade_id, close_reason, pnl_pips, pnl_usd, tp1_hit, tp2_hit):
    """Update trade record when closed."""
    conn = get_db_connection()
    try:
        conn.execute("""
            UPDATE trades SET
                close_time   = ?,
                close_reason = ?,
                pnl_pips     = ?,
                pnl_usd      = ?,
                tp1_hit      = ?,
                tp2_hit      = ?
            WHERE trade_id = ?
        """, (
            datetime.now().isoformat(),
            close_reason,
            pnl_pips,
            pnl_usd,
            1 if tp1_hit else 0,
            1 if tp2_hit else 0,
            trade_id,
        ))
        conn.commit()

        # Update daily summary
        update_daily_summary(pnl_pips, pnl_usd, close_reason)
        print(f"[Analytics] Trade closed: {trade_id} | {close_reason} | {pnl_pips} pips")

    except Exception as e:
        print(f"[Analytics] Trade close log error: {e}")
    finally:
        conn.close()


def log_missed_entry(model_name, direction, entry_price, reason):
    """Log when a valid signal entry was missed."""
    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO missed_entries (signal_time, model_name, direction, entry_price, reason)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            model_name,
            direction,
            entry_price,
            reason,
        ))
        conn.commit()
    except Exception as e:
        print(f"[Analytics] Missed entry log error: {e}")
    finally:
        conn.close()


# ------------------------------------------------------------
# DAILY SUMMARY
# ------------------------------------------------------------

def update_daily_summary(pnl_pips, pnl_usd, close_reason):
    """Update today's performance summary."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn  = get_db_connection()
    try:
        # Get today's summary or create it
        row = conn.execute(
            "SELECT * FROM daily_summary WHERE date = ?", (today,)
        ).fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO daily_summary (date) VALUES (?)", (today,)
            )
            row = conn.execute(
                "SELECT * FROM daily_summary WHERE date = ?", (today,)
            ).fetchone()

        total  = (row["total_trades"] or 0) + 1
        wins   = row["wins"]   or 0
        losses = row["losses"] or 0
        be     = row["breakeven"] or 0
        t_pips = (row["total_pips"] or 0) + pnl_pips
        t_pnl  = (row["total_pnl"]  or 0) + pnl_usd
        best   = max(row["best_trade"]  or 0, pnl_pips)
        worst  = min(row["worst_trade"] or 0, pnl_pips)

        if "SL" in close_reason:
            losses += 1
        elif "TP3" in close_reason or "TP2" in close_reason:
            wins += 1
        elif "TP1" in close_reason:
            wins += 1
        elif abs(pnl_pips) < 2:
            be += 1
        elif pnl_pips > 0:
            wins += 1
        else:
            losses += 1

        winrate = round(wins / total * 100, 1) if total > 0 else 0

        conn.execute("""
            UPDATE daily_summary SET
                total_trades = ?,
                wins         = ?,
                losses       = ?,
                breakeven    = ?,
                total_pips   = ?,
                total_pnl    = ?,
                winrate      = ?,
                best_trade   = ?,
                worst_trade  = ?,
                updated_at   = ?
            WHERE date = ?
        """, (
            total, wins, losses, be,
            round(t_pips, 1), round(t_pnl, 2),
            winrate, best, worst,
            datetime.now().isoformat(), today
        ))
        conn.commit()

    except Exception as e:
        print(f"[Analytics] Daily summary error: {e}")
    finally:
        conn.close()


# ------------------------------------------------------------
# PERFORMANCE STATS
# ------------------------------------------------------------

def get_performance_stats(days=30):
    """
    Calculate performance statistics over last N days.
    Returns comprehensive trading metrics.
    """
    conn      = get_db_connection()
    since     = (datetime.now() - timedelta(days=days)).isoformat()

    try:
        trades = conn.execute("""
            SELECT * FROM trades
            WHERE entry_time >= ? AND close_time IS NOT NULL
            ORDER BY entry_time DESC
        """, (since,)).fetchall()

        if not trades:
            return get_empty_stats()

        total   = len(trades)
        wins    = sum(1 for t in trades if (t["pnl_pips"] or 0) > 2)
        losses  = sum(1 for t in trades if (t["pnl_pips"] or 0) < -2)
        be      = total - wins - losses

        total_pips = sum(t["pnl_pips"] or 0 for t in trades)
        total_pnl  = sum(t["pnl_usd"]  or 0 for t in trades)

        winrate = round(wins / total * 100, 1) if total > 0 else 0

        pips_list = [t["pnl_pips"] or 0 for t in trades]
        best      = round(max(pips_list), 1) if pips_list else 0
        worst     = round(min(pips_list), 1) if pips_list else 0
        avg_win   = round(sum(p for p in pips_list if p > 0) / max(wins, 1), 1)
        avg_loss  = round(sum(p for p in pips_list if p < 0) / max(losses, 1), 1)

        # Profit factor
        gross_profit = sum(p for p in pips_list if p > 0)
        gross_loss   = abs(sum(p for p in pips_list if p < 0))
        profit_factor = round(gross_profit / max(gross_loss, 0.01), 2)

        # RR ratio
        avg_rr = round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 0

        # Consecutive stats
        max_win_streak  = 0
        max_loss_streak = 0
        cur_win         = 0
        cur_loss        = 0

        for t in reversed(trades):
            if (t["pnl_pips"] or 0) > 2:
                cur_win   += 1
                cur_loss   = 0
                max_win_streak = max(max_win_streak, cur_win)
            elif (t["pnl_pips"] or 0) < -2:
                cur_loss  += 1
                cur_win    = 0
                max_loss_streak = max(max_loss_streak, cur_loss)

        # Per model stats
        model_stats = {}
        for t in trades:
            mn = t["model_name"] or "unknown"
            if mn not in model_stats:
                model_stats[mn] = {"trades": 0, "wins": 0, "pips": 0}
            model_stats[mn]["trades"] += 1
            if (t["pnl_pips"] or 0) > 2:
                model_stats[mn]["wins"] += 1
            model_stats[mn]["pips"] += (t["pnl_pips"] or 0)

        for mn in model_stats:
            t_count = model_stats[mn]["trades"]
            w_count = model_stats[mn]["wins"]
            model_stats[mn]["winrate"] = round(w_count / t_count * 100, 1) if t_count > 0 else 0

        # Session stats
        session_stats = {}
        for t in trades:
            sess = t["session"] or "unknown"
            if sess not in session_stats:
                session_stats[sess] = {"trades": 0, "wins": 0, "pips": 0}
            session_stats[sess]["trades"] += 1
            if (t["pnl_pips"] or 0) > 2:
                session_stats[sess]["wins"] += 1
            session_stats[sess]["pips"] += (t["pnl_pips"] or 0)

        return {
            "period_days":      days,
            "total_trades":     total,
            "wins":             wins,
            "losses":           losses,
            "breakeven":        be,
            "winrate":          winrate,
            "total_pips":       round(total_pips, 1),
            "total_pnl":        round(total_pnl, 2),
            "avg_win_pips":     avg_win,
            "avg_loss_pips":    avg_loss,
            "best_trade_pips":  best,
            "worst_trade_pips": worst,
            "profit_factor":    profit_factor,
            "avg_rr":           avg_rr,
            "max_win_streak":   max_win_streak,
            "max_loss_streak":  max_loss_streak,
            "model_stats":      model_stats,
            "session_stats":    session_stats,
            "recent_trades":    [dict(t) for t in trades[:10]],
        }

    except Exception as e:
        print(f"[Analytics] Stats error: {e}")
        return get_empty_stats()
    finally:
        conn.close()


def get_empty_stats():
    return {
        "period_days":      30,
        "total_trades":     0,
        "wins":             0,
        "losses":           0,
        "breakeven":        0,
        "winrate":          0,
        "total_pips":       0,
        "total_pnl":        0,
        "avg_win_pips":     0,
        "avg_loss_pips":    0,
        "best_trade_pips":  0,
        "worst_trade_pips": 0,
        "profit_factor":    0,
        "avg_rr":           0,
        "max_win_streak":   0,
        "max_loss_streak":  0,
        "model_stats":      {},
        "session_stats":    {},
        "recent_trades":    [],
    }


def get_today_summary():
    """Get today's trading summary."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn  = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM daily_summary WHERE date = ?", (today,)
        ).fetchone()
        return dict(row) if row else {"date": today, "total_trades": 0}
    except Exception:
        return {"date": today, "total_trades": 0}
    finally:
        conn.close()


# ------------------------------------------------------------
# MAIN ENGINE FUNCTION
# ------------------------------------------------------------

def run(b9=None, b10=None, b11=None):
    """
    Run analytics engine.
    Initializes DB, returns current stats and system health.
    """
    # Always init DB on run
    init_database()

    # Get performance stats
    stats_30d = get_performance_stats(days=30)
    stats_7d  = get_performance_stats(days=7)
    today     = get_today_summary()

    # System health score
    health_score = 100

    if stats_30d["total_trades"] >= 10:
        if stats_30d["winrate"] < 40:
            health_score -= 30
        elif stats_30d["winrate"] < 50:
            health_score -= 10

        if stats_30d["profit_factor"] < 1.0:
            health_score -= 20
        elif stats_30d["profit_factor"] < 1.5:
            health_score -= 5

        if stats_30d["max_loss_streak"] >= 5:
            health_score -= 20
        elif stats_30d["max_loss_streak"] >= 3:
            health_score -= 10

    health_score = max(0, health_score)

    # Current signal info
    current_signal = None
    if b9 and b10:
        current_signal = {
            "direction":    b9.get("direction"),
            "grade":        b9.get("grade"),
            "score":        b9.get("score"),
            "should_trade": b9.get("should_trade"),
            "model":        b10.get("model_name"),
            "entry":        b10.get("entry"),
            "sl":           b10.get("sl"),
            "tp1":          b10.get("tp1"),
            "lot_size":     b10.get("lot_size"),
            "trade_status": b10.get("trade_status"),
        }

    return {
        "db_initialized":   True,
        "stats_30d":        stats_30d,
        "stats_7d":         stats_7d,
        "today":            today,
        "health_score":     health_score,
        "current_signal":   current_signal,
        "engine_score":     health_score,
    }


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------

if __name__ == "__main__":
    import MetaTrader5 as mt5
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    from engines.box10_trade         import run as run_b10

    print("Testing Box 12 — Analytics Engine")
    print("=" * 50)

    mt5.initialize()
    store.refresh()

    b1  = run_b1(store)
    b2  = run_b2(store)
    b3  = run_b3(store)
    b4  = run_b4(store)
    b5  = run_b5(store)
    b6  = run_b6(store)
    b7  = run_b7(store)
    b8  = run_b8(b1, b2, b3, b4, b5, b6, b7)
    b9  = run_b9(b1, b2, b3, b4, b5, b6, b7, b8)
    acc = mt5.account_info()
    b10 = run_b10(b1, b2, b3, b4, b5, b6, b7, b8, b9, acc.balance)

    result = run(b9, b10)

    print(f"\nDatabase:       {result['db_initialized']} ✓")
    print(f"Health Score:   {result['health_score']}/100")

    print(f"\n30-Day Stats:")
    s = result["stats_30d"]
    print(f"  Trades:        {s['total_trades']}")
    print(f"  Winrate:       {s['winrate']}%")
    print(f"  Total Pips:    {s['total_pips']}")
    print(f"  Profit Factor: {s['profit_factor']}")
    print(f"  Avg RR:        {s['avg_rr']}")

    print(f"\nToday:")
    t = result["today"]
    print(f"  Trades: {t.get('total_trades', 0)}")
    print(f"  Pips:   {t.get('total_pips', 0)}")

    if result["current_signal"]:
        sig = result["current_signal"]
        print(f"\nCurrent Signal:")
        print(f"  Direction: {sig['direction']}")
        print(f"  Grade:     {sig['grade']}")
        print(f"  Model:     {sig['model']}")
        print(f"  Status:    {sig['trade_status']}")

    mt5.shutdown()
    print("\nBox 12 Test PASSED ✓")
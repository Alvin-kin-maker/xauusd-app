# ============================================================
# api/main.py — FastAPI Server
# Wires all 12 engines into REST endpoints
# Signal lock: one signal at a time, frozen confluence score
# ============================================================

import sys
import os
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import json
import numpy as np
import pandas as pd

class NumpySafeEncoder(json.JSONEncoder):
    """Handles numpy and pandas types that FastAPI can't serialize natively."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):                return int(obj)
        if isinstance(obj, (np.floating,)):               return float(obj)
        if isinstance(obj, np.ndarray):                   return obj.tolist()
        if isinstance(obj, pd.Timestamp):                 return obj.isoformat()
        if isinstance(obj, pd.Series):                    return obj.tolist()
        if hasattr(obj, 'isoformat'):                     return obj.isoformat()
        return super().default(obj)

def safe_json_response(data: dict) -> JSONResponse:
    """Return a JSONResponse that handles numpy/pandas types safely."""
    return JSONResponse(content=json.loads(json.dumps(data, cls=NumpySafeEncoder)))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5

from data.candle_store import store
from data.signal_lock  import (
    is_locked, lock_signal, unlock_signal, get_frozen_signal
)
from utils.config import API_HOST, API_PORT, SYMBOL

from engines.box1_market_context import run as run_b1
from engines.box2_trend          import run as run_b2
from engines.box3_liquidity      import run as run_b3
from engines.box4_levels         import run as run_b4
from engines.box5_momentum       import run as run_b5
from engines.box6_sentiment      import run as run_b6
from engines.box7_entry          import run as run_b7
from engines.box8_model          import run as run_b8
from engines.box9_confluence     import run as run_b9
from engines.box10_trade         import run as run_b10, load_trade_state, record_trade_result
from engines.box11_news          import run as run_b11
from engines.box12_analytics     import run as run_b12, init_database, log_signal, log_trade_closed
from engines.box13_breakout      import run as run_b13


# ------------------------------------------------------------
# STARTUP / SHUTDOWN
# ------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[API] Starting XAUUSD Trading System...")
    mt5.initialize()
    store.refresh()
    try:
        init_database()
    except Exception as e:
        print(f"[API] DB init warning: {e}")
    info = mt5.terminal_info()
    connected = info.connected if info else False
    print(f"[API] MT5 connected: {connected}")
    print(f"[API] Server ready on {API_HOST}:{API_PORT}")
    task = asyncio.create_task(background_refresh())
    yield
    task.cancel()
    mt5.shutdown()
    print("[API] Shutdown complete")


app = FastAPI(title="XAUUSD Trading System", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------
# BACKGROUND REFRESH
# ------------------------------------------------------------

async def background_refresh():
    while True:
        try:
            await asyncio.sleep(60)
            store.refresh()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[API] Refresh error: {e}")


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def get_account_balance():
    acc = mt5.account_info()
    return acc.balance if acc else 10000.0


def safe_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except Exception:
        return None


def run_all_engines():
    """
    Run all 13 engines with per-engine error isolation.
    If any engine crashes, it logs the error and returns a safe fallback
    so the API never returns 500 due to a single engine failure.
    """
    import traceback

    def safe_run(name, fn, *args, fallback=None):
        try:
            return fn(*args)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[ENGINE ERROR] {name} crashed: {type(e).__name__}: {e}")
            print(tb)
            if fallback is not None:
                return fallback
            raise  # re-raise for critical engines (b1, b2, b9, b10)

    b1  = run_b1(store)
    b2  = run_b2(store)
    b3  = safe_run("box3_liquidity", run_b3, store,
                   fallback={"engine_score":0,"sweep_just_happened":False,"sweep_direction":"",
                             "total_sweeps":0,"pdh_swept":False,"pdl_swept":False,
                             "asian_high_swept":False,"asian_low_swept":False,
                             "bsl_levels":[],"ssl_levels":[],"eqh_levels":[],"eql_levels":[],
                             "nearest_bsl":None,"nearest_ssl":None,
                             "asian_high":None,"asian_low":None,"pdh":None,"pdl":None,
                             "pwh":None,"pwl":None,"pwh_swept":False,"pwl_swept":False,
                             "eqh_count":0,"eql_count":0})
    b4  = safe_run("box4_levels", run_b4, store,
                   fallback={"engine_score":0,"current_price":None,"price_zone":"unknown",
                             "equilibrium":None,"in_ote":False,"in_buy_ote":False,"in_sell_ote":False,
                             "at_key_level":False,"closest_level":None,"all_levels":[],
                             "pivot_pp":None,"pivot_r1":None,"pivot_r2":None,"pivot_r3":None,
                             "pivot_s1":None,"pivot_s2":None,"pivot_s3":None,
                             "weekly_pp":None,"weekly_r1":None,"weekly_r2":None,
                             "weekly_s1":None,"weekly_s2":None,"weekly_s3":None,
                             "monthly_pp":None,"monthly_r1":None,"monthly_r2":None,
                             "monthly_s1":None,"monthly_s2":None,"monthly_s3":None,
                             "vwap":None,"nwog":None,"ndog":None,"nwog_ce":None,"ndog_ce":None})
    b5  = safe_run("box5_momentum", run_b5, store,
                   fallback={"engine_score":0,"rsi_h1":50,"rsi_m15":50,"rsi_m5":50,
                             "rsi_h1_signal":"neutral","rsi_m15_signal":"neutral","rsi_m5_signal":"neutral",
                             "rsi_above_mid_m15":False,"rsi_above_mid_h1":False,
                             "divergence_active":False,"divergence_type":None,"recent_divergence":None,
                             "divergences_m15":[],"divergences_h1":[],"momentum_direction":"neutral",
                             "volume_m15":{"is_spike":False,"is_declining":False,"relative_volume":1.0,
                                          "current_volume":0,"avg_volume":0,"volume_trend":"normal"},
                             "volume_h1":{"is_spike":False,"is_declining":False,"relative_volume":1.0,
                                         "current_volume":0,"avg_volume":0,"volume_trend":"normal"},
                             "volume_m5":{"is_spike":False,"is_declining":False,"relative_volume":1.0,
                                         "current_volume":0,"avg_volume":0,"volume_trend":"normal"}})
    b6  = safe_run("box6_sentiment", run_b6, store,
                   fallback={"engine_score":0,"cot_sentiment":"neutral","cot_long_pct":50.0,
                             "cot_net_position":0,"cot_net_change":0,"cot_available":False,
                             "oi_signal":"neutral","oi_trend":"neutral",
                             "retail_long_pct":50.0,"contrarian_signal":"neutral",
                             "overall_sentiment":"neutral",
                             "cot":{"long_pct":50,"sentiment":"neutral","available":False,
                                    "net_position":0,"net_change":0,"report_date":None,
                                    "commercial_bias":"neutral","managed_money_long":0,
                                    "managed_money_short":0,"commercial_long":0,
                                    "commercial_short":0,"commercial_net":0,"source":"fallback"},
                             "oi":{"oi_signal":"neutral","oi_trend":"neutral","price_trend":"neutral",
                                   "vol_trend":"neutral","available":False},
                             "retail":{"retail_long_pct":50,"contrarian_signal":"neutral","available":False}})
    b7  = safe_run("box7_entry", run_b7, store, b2,
                   fallback={"engine_score":0,"entry_bias":"neutral",
                             "bull_ob_count":0,"bear_ob_count":0,"bull_fvg_count":0,"bear_fvg_count":0,
                             "at_bull_ob":False,"at_bear_ob":False,"at_bull_fvg":False,"at_bear_fvg":False,
                             "at_bull_breaker":False,"at_bear_breaker":False,
                             "bull_breakers":[],"bear_breakers":[],"price_at_entry_zone":False,
                             "pattern_count":0,"candle_patterns":[],"patterns":[],
                             "bullish_obs":[],"bearish_obs":[],"bullish_fvgs":[],"bearish_fvgs":[],
                             "fibs":[],"golden_fibs":[],"fib_direction":"buy","in_ote":False,
                             "ote_direction":"buy","ote_m15":{"in_ote":False,"in_buy_ote":False,
                             "in_sell_ote":False,"ote_direction":"buy","swing_high":None,"swing_low":None,
                             "ote_618":None,"ote_705":None,"ote_79":None,
                             "sell_ote_618":None,"sell_ote_705":None,"sell_ote_79":None}})
    b13 = safe_run("box13_breakout", run_b13, store, b1, b2, b3, b4, b5, b7,
                   fallback={"consolidation":{"was_consolidating":False,"range_high":None,
                                              "range_low":None,"range_size":None},
                             "h1_consolidation":{"was_consolidating":False},
                             "best_breakout":None,"breakouts":[]})
    b8  = safe_run("box8_model", run_b8, b1, b2, b3, b4, b5, b6, b7, b13,
                   fallback={"engine_score":0,"active_model":None,"best_model_name":None,
                             "best_model_score":0,"validated_count":0,"model_validated":False,
                             "all_models":{},"validated_models":{},"total_models":13})
    b9  = run_b9(b1, b2, b3, b4, b5, b6, b7, b8, b13)
    b10 = run_b10(b1, b2, b3, b4, b5, b6, b7, b8, b9, get_account_balance())
    b11 = safe_run("box11_news", run_b11,
                   fallback={"is_blocked":False,"block_reason":None,"next_event":None,
                             "minutes_to_next":None,"events_today":[]})
    b12 = safe_run("box12_analytics", run_b12, b9, b10,
                   fallback={"health_score":100,"stats_30d":{"winrate":0,"total_trades":0},
                             "stats_7d":{"winrate":0,"total_trades":0}})
    return b1, b2, b3, b4, b5, b6, b7, b8, b9, b10, b11, b12, b13


# ------------------------------------------------------------
# ENDPOINTS
# ------------------------------------------------------------

@app.get("/")
def root():
    return {
        "system": "XAUUSD Trading System",
        "status": "running",
        "time":   datetime.now().isoformat(),
        "symbol": SYMBOL,
    }


@app.get("/health")
def health():
    mt5_ok     = mt5.terminal_info() is not None
    candles_ok = store.is_ready()
    acc        = mt5.account_info()
    return {
        "status":          "ok" if mt5_ok and candles_ok else "degraded",
        "mt5_connected":   mt5_ok,
        "candles_ready":   candles_ok,
        "last_refresh":    store.last_update.isoformat() if store.last_update else None,
        "account_balance": safe_float(acc.balance) if acc else None,
        "signal_locked":   is_locked(),
        "time":            datetime.now().isoformat(),
    }



def _get_silver_bullet_window():
    """Return which Silver Bullet window is currently active, or None."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    t   = now.hour * 60 + now.minute
    if  8*60 <= t < 9*60:  return "Asian KZ (03:00–04:00 EST)"
    if 15*60 <= t < 16*60: return "London/NY KZ (10:00–11:00 EST)"
    if 19*60 <= t < 20*60: return "NY PM KZ (14:00–15:00 EST)"
    return None


@app.get("/signal")
def get_signal():
    """
    Main signal endpoint.
    - If a signal is already locked (trade active/pending):
        → return frozen signal, no new engines run
    - If no signal locked:
        → run all 12 engines, check for new signal
        → if new signal fires, lock it and freeze confluence
    """
    try:
        # --------------------------------------------------------
        # CASE 1: Signal already locked — return frozen data
        # --------------------------------------------------------
        frozen = get_frozen_signal()
        trade_state = load_trade_state()
        trade_status = trade_state.get("status", "IDLE")

        if frozen:
            # Auto-unlock conditions
            auto_unlock_reason = None

            # 1. Trade closed (SL or TP hit)
            # Only unlock on IDLE if the signal has been active for at least 60 seconds
            # Prevents race condition where signal fires then immediately reads IDLE next cycle
            if trade_status in ["CLOSED", "COOLDOWN"]:
                auto_unlock_reason = "trade_finished"
            elif trade_status == "IDLE":
                # GUARD: Never auto-unlock from IDLE if MT5 still has an open position.
                # This prevents the signal disappearing mid-trade when box10 briefly
                # returns IDLE due to an MT5 disconnect, crash, or state machine glitch.
                mt5_has_open_position = False
                try:
                    open_positions = mt5.positions_get(symbol=SYMBOL)
                    if open_positions and len(open_positions) > 0:
                        mt5_has_open_position = True
                except Exception:
                    pass  # If MT5 fails, assume safe and do NOT unlock

                if mt5_has_open_position:
                    # MT5 still has a trade open — do not unlock, just log
                    print("[Signal] Auto-unlock blocked — MT5 has open position on XAUUSD")
                else:
                    # No open positions in MT5 — safe to check if signal genuinely finished
                    signal_time = frozen.get("signal_time")
                    if signal_time:
                        try:
                            signal_dt = datetime.fromisoformat(signal_time)
                            seconds_elapsed = (datetime.now() - signal_dt).total_seconds()
                            if seconds_elapsed > 120:  # signal existed for 2+ mins before unlocking
                                auto_unlock_reason = "trade_finished"
                        except Exception:
                            auto_unlock_reason = "trade_finished"
                    else:
                        auto_unlock_reason = "trade_finished"

            # 2. Signal expired — price never reached entry within 4 hours
            elif trade_status == "SIGNAL":
                signal_time = frozen.get("signal_time")
                if signal_time:
                    try:
                        signal_dt = datetime.fromisoformat(signal_time)
                        hours_elapsed = (datetime.now() - signal_dt).total_seconds() / 3600
                        if hours_elapsed > 4:
                            auto_unlock_reason = "signal_expired_4h"
                    except Exception:
                        pass

                # SL breached while waiting for entry — void signal immediately
                frozen_sl        = frozen.get("sl")
                frozen_direction = frozen.get("direction")
                tick = mt5.symbol_info_tick(SYMBOL)
                if frozen_sl and frozen_direction and tick:
                    live_price = tick.bid
                    sl_breached = (
                        (frozen_direction == "sell" and live_price >= float(frozen_sl)) or
                        (frozen_direction == "buy"  and live_price <= float(frozen_sl))
                    )
                    if sl_breached:
                        auto_unlock_reason = "sl_breached_before_entry"

            # 3. Active trade — price moved 3x SL distance past TP3 (full winner)
            #    OR SL hit (already covered by CLOSED status above)

            if auto_unlock_reason:
                unlock_signal(auto_unlock_reason)
                frozen = None
                # Return immediately after unlock — don't search for new signal same cycle
                # This prevents instant re-lock after expiry/SL breach
                b1  = run_b1(store)
                b11 = run_b11()
                b12 = run_b12()
                tick = mt5.symbol_info_tick(SYMBOL)
                return safe_json_response({
                    "should_trade":    False,
                    "score_frozen":    False,
                    "direction":       "none",
                    "grade":           "NO_TRADE",
                    "score":           0,
                    "signal_summary":  f"Signal cleared ({auto_unlock_reason}) — scanning next cycle",
                    "trade_status":    "IDLE",
                    "state_message":   f"Cleared: {auto_unlock_reason}",
                    "session":         b1["primary_session"],
                    "atr":             safe_float(b1["atr"]),
                    "spread_pips":     safe_float(b1["spread_pips"]),
                    "volatility":      b1["volatility_regime"],
                    "news_blocked":    b11["is_blocked"],
                    "health_score":    b12["health_score"],
                    "time":            datetime.now().isoformat(),
                })
            else:
                # Serve frozen signal + live context (session/COT still live)
                b1  = run_b1(store)
                b6  = run_b6(store)
                b11 = run_b11()
                b12 = run_b12()
                tick = mt5.symbol_info_tick(SYMBOL)
                current_price = round(tick.bid, 2) if tick else None

                return safe_json_response({
                    # Frozen core signal
                    "should_trade":    True,
                    "blocked":         b11["is_blocked"],
                    "blocked_reason":  b11["block_reason"],
                    "direction":       frozen["direction"],
                    "grade":           frozen["frozen_grade"],
                    "score":           frozen["frozen_score"],
                    "score_frozen":    True,
                    "signal_summary":  (
                        f"{frozen['direction'].upper()} | {frozen['model_name']} | "
                        f"Entry: {frozen['entry']} | SL: {frozen['sl']} | "
                        f"TP1: {frozen['tp1']} TP2: {frozen['tp2']} TP3: {frozen['tp3']} | "
                        f"Score: {frozen['frozen_score']} (frozen)"
                    ),

                    # Frozen levels — always same as original signal
                    "entry":           frozen.get("entry"),
                    "sl":              frozen.get("sl"),
                    "tp1":             frozen.get("tp1"),
                    "tp2":             frozen.get("tp2"),
                    "tp3":             frozen.get("tp3"),
                    "lot_size":        frozen.get("lot_size"),
                    "model_name":      frozen.get("model_name"),
                    "validated_count": frozen.get("validated_count", 0),
                    "entry_zone":      frozen.get("entry_zone"),
                    "sl_pips":         frozen.get("sl_pips"),

                    # Live context (updates every poll)
                    "trade_status":    trade_status,
                    "state_message":   trade_state.get("state_message", ""),
                    "current_price":   current_price,
                    "news_blocked":    b11["is_blocked"],
                    "next_news":       b11["next_event"]["title"] if b11["next_event"] else None,
                    "minutes_to_news": b11["minutes_to_next"],
                    "signal_time":     frozen.get("signal_time"),

                    # Live market context
                    "session":         b1["primary_session"],
                    "atr":             safe_float(b1["atr"]),
                    "spread_pips":     safe_float(b1["spread_pips"]),
                    "volatility":      b1["volatility_regime"],
                    "cot_sentiment":   b6["cot_sentiment"],
                    "cot_long_pct":    safe_float(b6["cot_long_pct"]),
                    "health_score":    b12["health_score"],
                    "winrate_30d":     safe_float(b12["stats_30d"]["winrate"]),
                    "total_trades_30d": b12["stats_30d"]["total_trades"],
                    "time":            datetime.now().isoformat(),
                })

        # --------------------------------------------------------
        # CASE 2: No lock — run engines and look for new signal
        # --------------------------------------------------------
        b1, b2, b3, b4, b5, b6, b7, b8, b9, b10, b11, b12, b13 = run_all_engines()

        # News block — warning displays but never stops market data from showing
        # should_trade is suppressed but all engine data still returns normally
        news_is_blocked = b11["is_blocked"]

        # Only lock/fire signal if news is clear AND not already locked
        # is_locked() check prevents overwriting an active signal mid-trade
        if not news_is_blocked and not is_locked() and b9["should_trade"] and b10["trade_status"] in ["SIGNAL", "ACTIVE"]:
            lock_signal(b9, b10, b8)
            log_signal(b9, b11)

        return safe_json_response({
            "should_trade":    b10["should_trade"] and not news_is_blocked,  # b10 accounts for no entry found
            "blocked":         news_is_blocked,
            "blocked_reason":  b11["block_reason"] if news_is_blocked else None,
            "score_frozen":    False,
            "direction":       b9["direction"],
            "grade":           "NO_TRADE" if news_is_blocked else b9["grade"],
            "score":           safe_float(b9["score"]),
            "signal_summary":  f"BLOCKED: {b11['block_reason']}" if news_is_blocked else b10["signal_summary"],

            "entry":           safe_float(b10["entry"]),
            "sl":              safe_float(b10["sl"]),
            "tp1":             safe_float(b10["tp1"]),
            "tp2":             safe_float(b10["tp2"]),
            "tp3":             safe_float(b10["tp3"]),
            "sl_pips":         safe_float(b10["sl_pips"]),
            "lot_size":        safe_float(b10["lot_size"]),
            "entry_zone":      b10["entry_zone"],

            "model_name":      b10["model_name"],
            "model_score":     safe_float(b8["best_model_score"]),
            "validated_count": b8["validated_count"],

            "trade_status":    b10["trade_status"],
            "state_message":   b10["state_message"],

            "session":         b1["primary_session"],
            "atr":             safe_float(b1["atr"]),
            "spread_pips":     safe_float(b1["spread_pips"]),
            "volatility":      b1["volatility_regime"],

            "news_blocked":    b11["is_blocked"],
            "next_news":       b11["next_event"]["title"] if b11["next_event"] else None,
            "minutes_to_news": b11["minutes_to_next"],

            "cot_sentiment":   b6["cot_sentiment"],
            "cot_long_pct":    safe_float(b6["cot_long_pct"]),

            "health_score":    b12["health_score"],
            "winrate_30d":     safe_float(b12["stats_30d"]["winrate"]),
            "total_trades_30d": b12["stats_30d"]["total_trades"],

            "time":            datetime.now().isoformat(),
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/market")
def get_market():
    """Full market analysis — all engine outputs."""
    try:
        b1, b2, b3, b4, b5, b6, b7, b8, b9, b10, b11, b12, b13 = run_all_engines()

        return safe_json_response({
            "market_context": {
                "session":    b1["primary_session"],
                "atr":        safe_float(b1["atr"]),
                "volatility": b1["volatility_regime"],
                "spread":     safe_float(b1["spread_pips"]),
                "tradeable":  b1["is_tradeable"],
                "score":      b1["engine_score"],
            },
            "trend": {
                "overall_bias":   b2["overall_bias"],
                "internal_bias":  b2.get("internal_bias"),
                "external_bias":  b2.get("external_bias"),
                "mss_m5_active":  b2.get("mss_m5_active", False),
                "mss_m15_active": b2.get("mss_m15_active", False),
                "mss_m5_type":    b2.get("mss_m5_type"),
                "mss_m15_type":   b2.get("mss_m15_type"),
                "timeframes": {
                    tf: {
                        "bias":           data["bias"],
                        "structure":      data["structure"],
                        "structure_type": data.get("structure_type", "internal"),
                        "mss_active":     data.get("mss_active", False),
                        "mss_type":       data.get("mss_type"),
                    }
                    for tf, data in b2["timeframes"].items()
                },
                "score": b2["engine_score"],
            },
            "liquidity": {
                "eqh_count":           b3["eqh_count"],
                "eql_count":           b3["eql_count"],
                "pdh_swept":           b3["pdh_swept"],
                "pdl_swept":           b3["pdl_swept"],
                "asian_high_swept":    b3["asian_high_swept"],
                "asian_low_swept":     b3["asian_low_swept"],
                "sweep_just_happened": b3["sweep_just_happened"],
                "sweep_direction":     b3["sweep_direction"],
                "bsl_levels":          b3.get("bsl_levels", [])[:3],
                "ssl_levels":          b3.get("ssl_levels", [])[:3],
                "nearest_bsl":         safe_float(b3.get("nearest_bsl")),
                "nearest_ssl":         safe_float(b3.get("nearest_ssl")),
                "score":               b3["engine_score"],
            },
            "levels": {
                # Daily pivots
                "pivot_pp":      safe_float(b4.get("pivot_pp")),
                "pivot_r1":      safe_float(b4.get("pivot_r1")),
                "pivot_r2":      safe_float(b4.get("pivot_r2")),
                "pivot_r3":      safe_float(b4.get("pivot_r3")),
                "pivot_s1":      safe_float(b4.get("pivot_s1")),
                "pivot_s2":      safe_float(b4.get("pivot_s2")),
                "pivot_s3":      safe_float(b4.get("pivot_s3")),
                # Weekly pivots
                "weekly_pp":     safe_float(b4.get("weekly_pp")),
                "weekly_r1":     safe_float(b4.get("weekly_r1")),
                "weekly_r2":     safe_float(b4.get("weekly_r2")),
                "weekly_r3":     safe_float(b4.get("weekly_r3")),
                "weekly_s1":     safe_float(b4.get("weekly_s1")),
                "weekly_s2":     safe_float(b4.get("weekly_s2")),
                "weekly_s3":     safe_float(b4.get("weekly_s3")),
                # Monthly pivots (full suite)
                "monthly_pp":    safe_float(b4.get("monthly_pp")),
                "monthly_r1":    safe_float(b4.get("monthly_r1")),
                "monthly_r2":    safe_float(b4.get("monthly_r2")),
                "monthly_r3":    safe_float(b4.get("monthly_r3")),
                "monthly_s1":    safe_float(b4.get("monthly_s1")),
                "monthly_s2":    safe_float(b4.get("monthly_s2")),
                "monthly_s3":    safe_float(b4.get("monthly_s3")),
                # Other levels
                "vwap":          safe_float(b4.get("vwap")),
                "at_key_level":  b4["at_key_level"],
                "closest_level": b4["closest_level"],
                # Premium/Discount
                "price_zone":    b4.get("price_zone", "unknown"),
                "equilibrium":   safe_float(b4.get("equilibrium")),
                "in_ote":        b4.get("in_ote", False),
                "in_buy_ote":    b4.get("in_buy_ote", False),
                "in_sell_ote":   b4.get("in_sell_ote", False),
                # Opening gaps
                "nwog":          b4.get("nwog"),
                "ndog":          b4.get("ndog"),
                "score":         b4["engine_score"],
            },
            "momentum": {
                "rsi_m5":          safe_float(b5["rsi_m5"]),
                "rsi_m15":         safe_float(b5["rsi_m15"]),
                "rsi_h1":          safe_float(b5["rsi_h1"]),
                "rsi_m15_signal":  b5["rsi_m15_signal"],
                "divergence":      b5["divergence_active"],
                "divergence_type": b5["divergence_type"],
                "volume_spike":    b5["volume_m15"]["is_spike"],
                "score":           b5["engine_score"],
            },
            "sentiment": {
                "cot_sentiment": b6["cot_sentiment"],
                "cot_long_pct":  safe_float(b6["cot_long_pct"]),
                "cot_available": b6["cot_available"],
                "oi_signal":     b6["oi_signal"],
                "score":         b6["engine_score"],
            },
            "entry": {
                "bull_ob_count":  b7["bull_ob_count"],
                "bear_ob_count":  b7["bear_ob_count"],
                "bull_fvg_count": b7["bull_fvg_count"],
                "bear_fvg_count": b7["bear_fvg_count"],
                "entry_bias":     b7["entry_bias"],
                "at_zone":        b7["price_at_entry_zone"],
                "patterns":       b7["pattern_count"],
                "fibs":           b7.get("fibs", []),
                "golden_fibs":    b7.get("golden_fibs", []),
                "fib_direction":  b7.get("fib_direction"),
                "in_ote":         b7.get("in_ote", False),
                "ote_direction":  b7.get("ote_direction"),
                "ote_m15":        b7.get("ote_m15"),
                "score":          b7["engine_score"],
            },
            "models": {
                "validated_count":      b8["validated_count"],
                "silver_bullet_active": b8["all_models"].get("silver_bullet", {}).get("validated", False),
                "silver_bullet_window": _get_silver_bullet_window(),
                "active_model":    b8["best_model_name"],
                "model_score":     b8["best_model_score"],
                "all_scores": {
                    name: m["score"]
                    for name, m in b8["all_models"].items()
                },
            },
            "confluence": {
                "direction": b9["direction"],
                "score":     safe_float(b9["score"]),
                "grade":     b9["grade"],
                "engines": {
                    name: {
                        "raw":          safe_float(data["raw"]),
                        "contribution": safe_float(data["contribution"]),
                    }
                    for name, data in b9["engines"].items()
                },
            },
            "news": {
                "blocked":         b11["is_blocked"],
                "block_reason":    b11["block_reason"],
                "next_event":      b11["next_event"],
                "minutes_to_next": b11["minutes_to_next"],
                "upcoming":        b11["upcoming_events"][:3],
                "score":           b11["engine_score"],
            },
            "time": datetime.now().isoformat(),
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.get("/analytics")
def get_analytics():
    try:
        b12 = run_b12()
        return {
            "health_score": b12["health_score"],
            "stats_30d":    b12["stats_30d"],
            "stats_7d":     b12["stats_7d"],
            "today":        b12["today"],
            "time":         datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/price")
def get_price():
    try:
        tick = mt5.symbol_info_tick(SYMBOL)
        if not tick:
            raise HTTPException(status_code=503, detail="No price data")
        return {
            "symbol": SYMBOL,
            "bid":    round(tick.bid, 2),
            "ask":    round(tick.ask, 2),
            "mid":    round((tick.bid + tick.ask) / 2, 2),
            "spread": round((tick.ask - tick.bid) / 0.1, 1),
            "time":   datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trade/state")
def get_trade_state():
    state  = load_trade_state()
    frozen = get_frozen_signal()

    # Only expose trade levels once signal tab has confirmed them via signal lock
    # Prevents trade tab from showing a signal before the signal tab has fired it
    signal_confirmed = frozen is not None

    return {
        "status":        state["status"],
        "direction":     state.get("direction")             if signal_confirmed else None,
        "model":         state.get("model_name")            if signal_confirmed else None,
        "entry":         safe_float(state.get("entry_price")) if signal_confirmed else None,
        "sl":            safe_float(state.get("sl_price"))    if signal_confirmed else None,
        "tp1":           safe_float(state.get("tp1_price"))   if signal_confirmed else None,
        "tp2":           safe_float(state.get("tp2_price"))   if signal_confirmed else None,
        "tp3":           safe_float(state.get("tp3_price"))   if signal_confirmed else None,
        "lot_size":      safe_float(state.get("lot_size"))    if signal_confirmed else None,
        "tp1_hit":       state.get("tp1_hit", False),
        "tp2_hit":       state.get("tp2_hit", False),
        "sl_at_be":      state.get("sl_moved_to_be", False),
        "m1_confirmed":  state.get("m1_confirmed", False),
        "entry_time":    state.get("entry_time")            if signal_confirmed else None,
        "signal_time":   state.get("signal_time"),
        "state_message": state.get("state_message", ""),
        "signal_locked": signal_confirmed,
        "time":          datetime.now().isoformat(),
    }


@app.post("/trade/unlock")
def manual_unlock():
    """Manually unlock signal — use if trade closed outside the system."""
    unlock_signal("manual_unlock")
    return {"success": True, "message": "Signal unlocked"}


class TradeResultRequest(BaseModel):
    trade_id:           str
    model_name:         str
    won:                bool
    pnl_pips:           float
    pnl_usd:            float
    close_reason:       str
    immediate_reversal: bool = False


@app.post("/trade/close")
def close_trade(req: TradeResultRequest):
    try:
        log_trade_closed(
            req.trade_id, req.close_reason, req.pnl_pips, req.pnl_usd,
            tp1_hit=req.close_reason != "SL_HIT",
            tp2_hit="TP2" in req.close_reason or "TP3" in req.close_reason,
        )
        strike_state = record_trade_result(
            req.model_name, req.won, req.immediate_reversal
        )
        unlock_signal(req.close_reason)
        return {
            "success":       True,
            "message":       f"Trade {req.trade_id} logged and signal unlocked",
            "model_strikes": strike_state["models"].get(req.model_name, {}).get("strikes", 0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/refresh")
def force_refresh():
    try:
        store.refresh()
        return {"success": True, "message": "Candles refreshed", "summary": store.summary()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------
# RUN
# ------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=API_HOST, port=API_PORT, reload=False, log_level="info")
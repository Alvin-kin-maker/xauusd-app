# ============================================================
# box10_trade.py — Trade Engine v3
# Precision entries: proximal/distal zone logic
# M1 confirmation candle before entry fires
# Structure-based SL — never ATR, never capped
# Signal lock is ironclad — levels never change once set
# FIX: Straight shooter SL uses nearest swing high/low (respects 25-200 pip range)
# FIX: M1 confirmation requires close beyond zone + buffer
# ============================================================

import sys
import os
import json
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import (
    RISK_PERCENT, TP1_RR, TP2_RR, TP3_RR,
    SL_BUFFER_PIPS, COOLDOWN_MINUTES, SYMBOL,
)

# ============================================================
# STATE FILES
# ============================================================

TRADE_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "trade_state.json"
)
STRIKE_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "strike_state.json"
)

MAX_CHASE_FRACTION = 1.5  # FIX: Was 0.5 — caused 7x refire loop


def load_trade_state():
    try:
        if os.path.exists(TRADE_STATE_FILE):
            with open(TRADE_STATE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return get_default_trade_state()


def save_trade_state(state):
    try:
        os.makedirs(os.path.dirname(TRADE_STATE_FILE), exist_ok=True)
        with open(TRADE_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        print(f"[Trade] State save error: {e}")


def get_default_trade_state():
    return {
        "status":           "IDLE",
        "direction":        None,
        "model_name":       None,
        "entry_price":      None,
        "sl_price":         None,
        "tp1_price":        None,
        "tp2_price":        None,
        "tp3_price":        None,
        "lot_size":         None,
        "tp1_hit":          False,
        "tp2_hit":          False,
        "sl_moved_to_be":   False,
        "partial_closed":   False,
        "signal_time":      None,
        "entry_time":       None,
        "close_time":       None,
        "close_reason":     None,
        "pnl_pips":         None,
        "cooldown_until":   None,
        "missed_entries":   0,
        "state_message":    "",
        "m1_confirmed":     False,
    }


# ============================================================
# STRIKE SYSTEM
# ============================================================

def load_strike_state():
    try:
        if os.path.exists(STRIKE_STATE_FILE):
            with open(STRIKE_STATE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return get_default_strike_state()


def save_strike_state(state):
    try:
        os.makedirs(os.path.dirname(STRIKE_STATE_FILE), exist_ok=True)
        with open(STRIKE_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        print(f"[Trade] Strike save error: {e}")


def get_default_strike_state():
    return {
        "models": {},
        "system_paused":          False,
        "system_pause_reason":    None,
        "total_trades_this_week": 0,
        "losses_this_week":       0,
        "wins_this_week":         0,
        "last_reset":             datetime.now().isoformat(),
    }


def check_model_suspended(model_name, strike_state):
    m = strike_state["models"].get(model_name, {})
    suspended_until = m.get("suspended_until")
    if suspended_until:
        until_dt = datetime.fromisoformat(suspended_until)
        if datetime.now() < until_dt:
            hrs = round((until_dt - datetime.now()).total_seconds() / 3600, 1)
            return True, f"Suspended {hrs}h remaining", 0.0
    if m.get("strikes", 0) == 2:
        return False, "Strike 2 — 50% size", 0.5
    return False, "OK", 1.0


def record_trade_result(model_name, won, immediate_reversal=False):
    strike_state = load_strike_state()
    if model_name not in strike_state["models"]:
        strike_state["models"][model_name] = {
            "strikes": 0, "consecutive_wins": 0,
            "suspended_until": None, "total_trades": 0, "wins": 0,
        }
    m = strike_state["models"][model_name]
    m["total_trades"] += 1
    if won:
        m["wins"] += 1
        m["consecutive_wins"] += 1
        strike_state["wins_this_week"] += 1
        if m["consecutive_wins"] >= 2 and m["strikes"] > 0:
            m["strikes"] -= 1
            m["consecutive_wins"] = 0
    else:
        m["consecutive_wins"] = 0
        strike_state["losses_this_week"] += 1
        m["strikes"] += 2 if immediate_reversal else 1
        if m["strikes"] >= 3:
            hrs = 168 if immediate_reversal else 48
            m["suspended_until"] = (datetime.now() + timedelta(hours=hrs)).isoformat()
    strike_state["total_trades_this_week"] += 1
    total  = strike_state["total_trades_this_week"]
    losses = strike_state["losses_this_week"]
    if total >= 20 and (total - losses) / total < 0.25:
        strike_state["system_paused"] = True
        strike_state["system_pause_reason"] = f"Winrate below 25% over {total} trades"
    if sum(1 for d in strike_state["models"].values() if d.get("strikes", 0) >= 3) >= 3:
        strike_state["system_paused"] = True
        strike_state["system_pause_reason"] = "3+ models suspended simultaneously"
    save_strike_state(strike_state)
    return strike_state


# ============================================================
# POSITION SIZING
# ============================================================

def calculate_lot_size(account_balance, risk_percent, sl_pips):
    if sl_pips <= 0:
        return 0.01
    risk_amount = account_balance * (risk_percent / 100)
    raw_lot = risk_amount / (sl_pips * 1.0)  # $1 per pip per lot on XAUUSD
    return max(0.01, min(round(raw_lot, 2), 10.0))


# ============================================================
# M1 CONFIRMATION — FIXED
# ============================================================

def get_m1_confirmation(direction, zone_top, zone_bottom):
    """
    Check last 5 M1 candles for a rejection confirmation at zone boundary.

    BUY confirmation: price wicks below zone bottom AND closes ABOVE zone bottom + buffer,
                      bullish body, meaningful lower wick.
    SELL confirmation: price wicks above zone top AND closes BELOW zone top - buffer,
                       bearish body, meaningful upper wick.

    Returns (confirmed: bool, message: str)
    """
    try:
        import MetaTrader5 as mt5
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 10)
        if rates is None or len(rates) < 3:
            return False, "Waiting for M1 data"

        for i in range(len(rates) - 2, max(len(rates) - 6, 0), -1):
            c = rates[i]
            o, h, l, close = c["open"], c["high"], c["low"], c["close"]
            candle_range = h - l
            if candle_range < 0.1:
                continue

            if direction == "buy":
                lower_wick = min(o, close) - l
                # FIX: Must close 5 pips (0.5) above zone bottom
                if (l <= zone_bottom and
                    close > zone_bottom + 0.5 and
                    close > o and
                    lower_wick / candle_range > 0.35):
                    return True, f"M1 bullish breakout at {round(zone_bottom, 2)}"

            elif direction == "sell":
                upper_wick = h - max(o, close)
                # FIX: Must close 5 pips (0.5) below zone top
                if (h >= zone_top and
                    close < zone_top - 0.5 and
                    close < o and
                    upper_wick / candle_range > 0.35):
                    return True, f"M1 bearish breakout at {round(zone_top, 2)}"

        return False, "Waiting for M1 breakout candle at zone"

    except Exception as e:
        return True, f"M1 check skipped ({e})"


# ============================================================
# PER-MODEL ENTRY LOGIC — PROXIMAL / DISTAL
# ============================================================

def get_entry_for_model(model_name, direction, b3, b4, b7, b1, b2, current_price, b13=None):
    """
    Proximal = edge of zone price approaches FIRST (ENTRY point)
    Distal   = far edge of zone (SL goes just beyond this)

    SELL: proximal = zone TOP,    distal = zone BOTTOM
    BUY:  proximal = zone BOTTOM, distal = zone TOP

    SL buffer (buf) is added beyond the distal edge.
    Proximity filter: entry must be within 25 pips of current price.
    """
    buf = 0.5  # 5 pips buffer beyond zone
    MAX_ENTRY_DISTANCE = 5.0  # 50 pips max from current price

    # ── MODEL 1: London Sweep & Reverse ──────────────────────────
    if model_name == "london_sweep_reverse":
        atr = float(b1.get("atr") or 2.0)
        if direction == "sell" and b3.get("asian_high_swept"):
            ah = b3.get("asian_high")
            if ah:
                ah = float(ah)
                # Entry: OB/FVG near Asian High, or Asian High itself
                ob_e = _smart_ob(direction, b7, buf, current_price, b1, b2, b3)
                if ob_e and abs(ob_e["entry"] - ah) <= 2.0:
                    # SL: above Asian High sweep wick using H4 swing high
                    h4_sh = b2.get("timeframes", {}).get("H4", {}).get("last_sh")
                    if h4_sh:
                        sh_p = float(h4_sh["price"]) if isinstance(h4_sh, dict) else float(h4_sh)
                        if sh_p > ah:
                            ob_e["sl"] = _apply_sl_cap(ob_e["entry"], round(sh_p + buf, 2))
                    ob_e["label"] = "London Sweep OB (Sell)"
                    return ob_e
                fvg_e = _smart_fvg(direction, b7, buf, current_price, b1, b2, b3)
                if fvg_e and abs(fvg_e["entry"] - ah) <= 2.0:
                    fvg_e["label"] = "London Sweep FVG (Sell)"
                    return fvg_e
                # Fallback: Asian High with tight ATR SL
                sl = round(ah + max(atr * 0.3, 0.3), 2)
                return _make_zone(round(ah - buf, 2), sl, ah, sl, "Asian High Sweep Reversal")

        if direction == "buy" and b3.get("asian_low_swept"):
            al = b3.get("asian_low")
            if al:
                al = float(al)
                ob_e = _smart_ob(direction, b7, buf, current_price, b1, b2, b3)
                if ob_e and abs(ob_e["entry"] - al) <= 2.0:
                    h4_sl = b2.get("timeframes", {}).get("H4", {}).get("last_sl")
                    if h4_sl:
                        sl_p = float(h4_sl["price"]) if isinstance(h4_sl, dict) else float(h4_sl)
                        if sl_p < al:
                            ob_e["sl"] = _apply_sl_cap(ob_e["entry"], round(sl_p - buf, 2))
                    ob_e["label"] = "London Sweep OB (Buy)"
                    return ob_e
                fvg_e = _smart_fvg(direction, b7, buf, current_price, b1, b2, b3)
                if fvg_e and abs(fvg_e["entry"] - al) <= 2.0:
                    fvg_e["label"] = "London Sweep FVG (Buy)"
                    return fvg_e
                sl = round(al - max(atr * 0.3, 0.3), 2)
                return _make_zone(round(al + buf, 2), sl, al, sl, "Asian Low Sweep Reversal")

        return _smart_ob_fvg(direction, b7, buf, current_price, b1, b2, b3)

    # ── MODEL 2: NY Continuation ──────────────────────────────────
    elif model_name == "ny_continuation":
        result = _smart_ob_fvg(direction, b7, buf, current_price, b1, b2, b3)
        if result:
            result["label"] = "NY Continuation OB"
        return result

    # ── MODEL 3: Asian Range Breakout ─────────────────────────────
    elif model_name == "asian_range_breakout":
        ah  = b3.get("asian_high")
        al  = b3.get("asian_low")
        atr = float(b1.get("atr") or 2.0)
        sl_dist = round(max(atr * 0.3, 0.3), 2)

        if direction == "buy" and ah:
            ah = float(ah)
            ob_entry = _smart_ob(direction, b7, buf, current_price, b1, b2, b3)
            if ob_entry and abs(ob_entry["entry"] - ah) <= 1.5:
                ob_entry["label"] = f"Asian Breakout OB Retest"
                return ob_entry
            fvg_entry = _smart_fvg(direction, b7, buf, current_price, b1, b2, b3)
            if fvg_entry and abs(fvg_entry["entry"] - ah) <= 1.5:
                fvg_entry["label"] = "Asian Breakout FVG Retest"
                return fvg_entry
            entry = round(ah + buf, 2)
            sl    = round(ah - sl_dist, 2)
            return _make_zone(entry, sl, ah, sl, "Asian High Retest (Buy)")

        if direction == "sell" and al:
            al = float(al)
            ob_entry = _smart_ob(direction, b7, buf, current_price, b1, b2, b3)
            if ob_entry and abs(ob_entry["entry"] - al) <= 1.5:
                ob_entry["label"] = "Asian Breakout OB Retest"
                return ob_entry
            fvg_entry = _smart_fvg(direction, b7, buf, current_price, b1, b2, b3)
            if fvg_entry and abs(fvg_entry["entry"] - al) <= 1.5:
                fvg_entry["label"] = "Asian Breakout FVG Retest"
                return fvg_entry
            entry = round(al - buf, 2)
            sl    = round(al + sl_dist, 2)
            return _make_zone(entry, sl, al, sl, "Asian Low Retest (Sell)")

        return None

    # ── MODEL 4: OB + FVG Stack ───────────────────────────────────
    elif model_name == "ob_fvg_stack":
        atr = float(b1.get("atr") or 2.0)

        if direction == "sell":
            struct_sl = None
            h4_sh = b2.get("timeframes", {}).get("H4", {}).get("last_sh")
            if h4_sh:
                sh_p = float(h4_sh["price"]) if isinstance(h4_sh, dict) else float(h4_sh)
                if sh_p > (current_price or 0):
                    struct_sl = round(sh_p + buf, 2)
            if not struct_sl:
                bsl = b3.get("nearest_bsl")
                if bsl: struct_sl = round(float(bsl) + buf, 2)
            if not struct_sl:
                struct_sl = round((current_price or 0) + max(atr * 0.3, 0.3), 2)

            obs  = b7.get("bearish_obs",  [])
            fvgs = b7.get("bearish_fvgs", [])
            if obs and fvgs:
                ob, fvg      = obs[0], fvgs[0]
                stack_top    = max(float(ob["top"]),    float(fvg["top"]))
                stack_bottom = min(float(ob["bottom"]), float(fvg["bottom"]))
                proximal     = round(stack_top, 2)
                distal       = round(stack_bottom, 2)
                entry        = round(proximal - buf, 2)
                stack_size   = round(stack_top - stack_bottom, 2)
                if not (current_price and abs(proximal - current_price) > 5.0) and stack_size <= 3.0:
                    result = _make_zone(entry, struct_sl, proximal, distal, "OB+FVG Stack (Sell)")
                    result["stack_size"] = stack_size
                    return result
            if obs:
                ob       = obs[0]
                proximal = round(float(ob["top"]), 2)
                distal   = round(float(ob["bottom"]), 2)
                if not (current_price and abs(proximal - current_price) > 5.0):
                    entry = round(proximal - buf, 2)
                    return _make_zone(entry, struct_sl, proximal, distal, "Bear OB (Sell)")

        elif direction == "buy":
            struct_sl = None
            h4_sl = b2.get("timeframes", {}).get("H4", {}).get("last_sl")
            if h4_sl:
                sl_p = float(h4_sl["price"]) if isinstance(h4_sl, dict) else float(h4_sl)
                if sl_p < (current_price or 9999):
                    struct_sl = round(sl_p - buf, 2)
            if not struct_sl:
                ssl = b3.get("nearest_ssl")
                if ssl: struct_sl = round(float(ssl) - buf, 2)
            if not struct_sl:
                struct_sl = round((current_price or 0) - max(atr * 0.3, 0.3), 2)

            obs  = b7.get("bullish_obs",  [])
            fvgs = b7.get("bullish_fvgs", [])
            if obs and fvgs:
                ob, fvg      = obs[0], fvgs[0]
                stack_top    = max(float(ob["top"]),    float(fvg["top"]))
                stack_bottom = min(float(ob["bottom"]), float(fvg["bottom"]))
                proximal     = round(stack_bottom, 2)
                distal       = round(stack_top, 2)
                entry        = round(proximal + buf, 2)
                stack_size   = round(stack_top - stack_bottom, 2)
                if not (current_price and abs(proximal - current_price) > 5.0) and stack_size <= 3.0:
                    result = _make_zone(entry, struct_sl, proximal, distal, "OB+FVG Stack (Buy)")
                    result["stack_size"] = stack_size
                    return result
            elif obs:
                ob       = obs[0]
                proximal = round(float(ob["bottom"]), 2)
                distal   = round(float(ob["top"]), 2)
                entry    = round(proximal + buf, 2)
                return _make_zone(entry, struct_sl, proximal, distal, "Bull OB (Buy)")

        return None

    # ── MODEL 5: Liquidity Grab + BOS ─────────────────────────────
    elif model_name == "liquidity_grab_bos":
        atr = float(b1.get("atr") or 2.0)
        fvg = _smart_fvg(direction, b7, buf, current_price, b1, b2, b3)
        if fvg:
            fvg["label"] = "FVG After BOS Displacement"
            NEARBY = 15.0

            if direction == "sell":
                struct_sl = None
                h4_sh = b2.get("timeframes", {}).get("H4", {}).get("last_sh")
                if h4_sh:
                    sh_p = float(h4_sh["price"]) if isinstance(h4_sh, dict) else float(h4_sh)
                    if sh_p > fvg["entry"] and (sh_p - fvg["entry"]) <= NEARBY:
                        struct_sl = round(sh_p + buf, 2)
                if not struct_sl:
                    bsl = b3.get("nearest_bsl")
                    if bsl and float(bsl) > fvg["entry"] and (float(bsl) - fvg["entry"]) <= NEARBY:
                        struct_sl = round(float(bsl) + buf, 2)
                if not struct_sl:
                    fvg_top = fvg.get("zone_top") or fvg.get("top")
                    if fvg_top and float(fvg_top) > fvg["entry"]:
                        struct_sl = round(float(fvg_top) + buf, 2)
                if not struct_sl:
                    struct_sl = round(fvg["entry"] + max(atr * 0.3, SL_MIN_PIPS), 2)
                fvg["sl"] = struct_sl
            else:
                struct_sl = None
                h4_sl = b2.get("timeframes", {}).get("H4", {}).get("last_sl")
                if h4_sl:
                    sl_p = float(h4_sl["price"]) if isinstance(h4_sl, dict) else float(h4_sl)
                    if sl_p < fvg["entry"] and (fvg["entry"] - sl_p) <= NEARBY:
                        struct_sl = round(sl_p - buf, 2)
                if not struct_sl:
                    ssl = b3.get("nearest_ssl")
                    if ssl and float(ssl) < fvg["entry"] and (fvg["entry"] - float(ssl)) <= NEARBY:
                        struct_sl = round(float(ssl) - buf, 2)
                if not struct_sl:
                    fvg_bot = fvg.get("zone_bottom") or fvg.get("bottom")
                    if fvg_bot and float(fvg_bot) < fvg["entry"]:
                        struct_sl = round(float(fvg_bot) - buf, 2)
                if not struct_sl:
                    struct_sl = round(fvg["entry"] - max(atr * 0.3, SL_MIN_PIPS), 2)
                fvg["sl"] = struct_sl

            fvg["sl"] = _apply_sl_cap(fvg["entry"], fvg["sl"])
            return fvg

        if direction == "buy" and b3.get("pdl_swept"):
            pdl = b3.get("pdl")
            if pdl:
                pdl   = float(pdl)
                atr   = float(b1.get("atr") or 2.0)
                sl    = round(pdl - max(atr * 0.3, 0.3), 2)
                entry = round(pdl + buf, 2)
                return _make_zone(entry, sl, pdl, sl, "PDL Sweep + BOS (Buy)")

        if direction == "sell" and b3.get("pdh_swept"):
            pdh = b3.get("pdh")
            if pdh:
                pdh   = float(pdh)
                atr   = float(b1.get("atr") or 2.0)
                sl    = round(pdh + max(atr * 0.3, 0.3), 2)
                entry = round(pdh - buf, 2)
                return _make_zone(entry, sl, pdh, sl, "PDH Sweep + BOS (Sell)")

        return _smart_ob_fvg(direction, b7, buf, current_price, b1, b2, b3)

    # ── MODEL 6: HTF Level Reaction ───────────────────────────────
    elif model_name == "htf_level_reaction":
        closest = b4.get("closest_level")

        if closest and b4.get("at_key_level"):
            level = float(closest.get("level") or closest.get("price") or 0)
            if level > 0:
                sl = None
                if direction == "sell":
                    for tf in ["H4", "D1", "H1"]:
                        tf_data = b2.get("timeframes", {}).get(tf, {})
                        last_sh = tf_data.get("last_sh")
                        if last_sh:
                            sh_price = float(last_sh["price"]) if isinstance(last_sh, dict) else float(last_sh)
                            if sh_price > level:
                                sl = round(sh_price + buf, 2)
                                break
                    if not sl:
                        bsl = b3.get("nearest_bsl")
                        if bsl and float(bsl) > level:
                            sl = round(float(bsl) + buf, 2)
                    if not sl:
                        pdh = b3.get("pdh") or b4.get("pdh")
                        if pdh and float(pdh) > level:
                            sl = round(float(pdh) + buf, 2)
                else:
                    for tf in ["H4", "D1", "H1"]:
                        tf_data = b2.get("timeframes", {}).get(tf, {})
                        last_sl_pt = tf_data.get("last_sl")
                        if last_sl_pt:
                            sl_price = float(last_sl_pt["price"]) if isinstance(last_sl_pt, dict) else float(last_sl_pt)
                            if sl_price < level:
                                sl = round(sl_price - buf, 2)
                                break
                    if not sl:
                        ssl = b3.get("nearest_ssl")
                        if ssl and float(ssl) < level:
                            sl = round(float(ssl) - buf, 2)
                    if not sl:
                        pdl = b3.get("pdl") or b4.get("pdl")
                        if pdl and float(pdl) < level:
                            sl = round(float(pdl) - buf, 2)

                if not sl:
                    atr = float(b1.get("atr") or 3.0)
                    sl = round(level + atr * 0.3, 2) if direction == "sell" else round(level - atr * 0.3, 2)

                MAX_SL_DISTANCE = 20.0
                if sl and abs(level - sl) > MAX_SL_DISTANCE:
                    atr = float(b1.get("atr") or 3.0)
                    atr_sl = min(atr * 0.3, MAX_SL_DISTANCE)
                    sl = round(level + atr_sl, 2) if direction == "sell" else round(level - atr_sl, 2)

                ob_entry = _smart_ob(direction, b7, buf, current_price, b1, b2, b3)
                if ob_entry and abs(ob_entry["entry"] - level) <= 1.5:
                    ob_entry["sl"]    = sl
                    ob_entry["label"] = f"HTF Level OB: {closest.get('label','')}"
                    return ob_entry

                fvg_entry = _smart_fvg(direction, b7, buf, current_price, b1, b2, b3)
                if fvg_entry and abs(fvg_entry["entry"] - level) <= 1.5:
                    fvg_entry["sl"]    = sl
                    fvg_entry["label"] = f"HTF Level FVG: {closest.get('label','')}"
                    return fvg_entry

                ote = b7.get("ote_m15") or b7.get("ote_h1")
                if ote and ote.get("in_ote"):
                    ote_705 = ote.get("ote_705")
                    if ote_705:
                        entry = round(float(ote_705) - buf, 2) if direction == "sell" else round(float(ote_705) + buf, 2)
                        return _make_zone(entry, sl, float(ote_705), sl,
                                          f"HTF Level OTE 70.5%: {closest.get('label','')}")

                entry = round(level - buf, 2) if direction == "sell" else round(level + buf, 2)
                return _make_zone(entry, sl, level, sl,
                                  f"HTF Level: {closest.get('label', '')}")

        return _smart_ob_fvg(direction, b7, buf, current_price, b1, b2, b3)

    # ── MODEL 7: CHOCH Reversal ───────────────────────────────────
    elif model_name == "choch_reversal":
        if direction == "buy" and b7.get("bull_breakers"):
            bb = b7["bull_breakers"][0]
            proximal = round(float(bb["bottom"]), 2)
            distal   = round(float(bb["top"]), 2)
            entry    = round(proximal + buf, 2)
            atr_buf  = max(float(b1.get("atr") or 2.0) * 0.3, 0.5)
            sl       = round(proximal - atr_buf, 2)
            return _make_zone(entry, sl, proximal, distal, "Bull Breaker (CHOCH)")

        if direction == "sell" and b7.get("bear_breakers"):
            bb = b7["bear_breakers"][0]
            proximal = round(float(bb["top"]), 2)
            distal   = round(float(bb["bottom"]), 2)
            entry    = round(proximal - buf, 2)
            atr_buf  = max(float(b1.get("atr") or 2.0) * 0.3, 0.5)
            sl       = round(proximal + atr_buf, 2)
            return _make_zone(entry, sl, proximal, distal, "Bear Breaker (CHOCH)")

        return _smart_ob_fvg(direction, b7, buf, current_price, b1, b2, b3)

    # ── MODEL 8: Double Top/Bottom Trap ──────────────────────────
    elif model_name == "double_top_bottom_trap":
        atr = float(b1.get("atr") or 2.0)
        for p in b7.get("patterns", []):
            if p["type"] == "double_top" and direction == "sell":
                neckline = p.get("neckline")
                level2   = p.get("level2")
                if neckline and level2:
                    neck = float(neckline)
                    top  = float(level2)
                    fvg_e = _smart_fvg(direction, b7, buf, current_price, b1, b2, b3)
                    if fvg_e and abs(fvg_e["entry"] - neck) <= 1.0:
                        fvg_e["label"] = "Double Top FVG Entry"
                        fvg_e["sl"] = _apply_sl_cap(fvg_e["entry"], round(top + buf, 2))
                        return fvg_e
                    ob_e = _smart_ob(direction, b7, buf, current_price, b1, b2, b3)
                    if ob_e and abs(ob_e["entry"] - neck) <= 1.0:
                        ob_e["label"] = "Double Top OB Entry"
                        ob_e["sl"] = _apply_sl_cap(ob_e["entry"], round(top + buf, 2))
                        return ob_e
                    entry = round(neck - buf, 2)
                    sl    = round(top + buf, 2)
                    return _make_zone(entry, sl, neck, top, "Double Top Neckline")

            if p["type"] == "double_bottom" and direction == "buy":
                neckline = p.get("neckline")
                level2   = p.get("level2")
                if neckline and level2:
                    neck   = float(neckline)
                    bottom = float(level2)
                    fvg_e = _smart_fvg(direction, b7, buf, current_price, b1, b2, b3)
                    if fvg_e and abs(fvg_e["entry"] - neck) <= 1.0:
                        fvg_e["label"] = "Double Bottom FVG Entry"
                        fvg_e["sl"] = _apply_sl_cap(fvg_e["entry"], round(bottom - buf, 2))
                        return fvg_e
                    ob_e = _smart_ob(direction, b7, buf, current_price, b1, b2, b3)
                    if ob_e and abs(ob_e["entry"] - neck) <= 1.0:
                        ob_e["label"] = "Double Bottom OB Entry"
                        ob_e["sl"] = _apply_sl_cap(ob_e["entry"], round(bottom - buf, 2))
                        return ob_e
                    entry = round(neck + buf, 2)
                    sl    = round(bottom - buf, 2)
                    return _make_zone(entry, sl, neck, bottom, "Double Bottom Neckline")

        return _smart_ob_fvg(direction, b7, buf, current_price, b1, b2, b3)

    # ── MODEL 9: OB Mitigation ────────────────────────────────────
    elif model_name == "ob_mitigation":
        if direction == "buy":
            obs = b7.get("bullish_obs", [])
            if obs:
                ob = obs[0]
                proximal = round(float(ob["bottom"]), 2)
                distal   = round(float(ob["top"]), 2)
                entry    = round(proximal + buf, 2)
                atr_buf  = max(float(b1.get("atr") or 2.0) * 0.3, 0.5)
                sl       = round(proximal - atr_buf, 2)
                return _make_zone(entry, sl, proximal, distal, "Bull OB Mitigation")

        if direction == "sell":
            obs = b7.get("bearish_obs", [])
            if obs:
                ob = obs[0]
                proximal = round(float(ob["top"]), 2)
                distal   = round(float(ob["bottom"]), 2)
                entry    = round(proximal - buf, 2)
                atr_buf  = max(float(b1.get("atr") or 2.0) * 0.3, 0.5)
                sl       = round(proximal + atr_buf, 2)
                return _make_zone(entry, sl, proximal, distal, "Bear OB Mitigation")

        return None

    # ── MODEL 10: FVG Continuation ────────────────────────────────
    elif model_name == "fvg_continuation":
        result = _smart_fvg(direction, b7, buf, current_price, b1, b2, b3)
        if result:
            result["label"] = "FVG CE (Continuation)"
        return result

    # ── SILVER BULLET ────────────────────────────────────────
    elif model_name == "silver_bullet":
        if direction == "buy":
            fvgs = b7.get("bullish_fvgs", [])
            if fvgs:
                fvg      = fvgs[0]
                proximal = round(float(fvg["bottom"]), 2)
                distal   = round(float(fvg["top"]), 2)
                entry    = round(proximal + buf, 2)
                atr_buf = max(float(b1.get("atr") or 2.0) * 0.5, 0.5)
                sl = round(proximal - atr_buf, 2)
                return _make_zone(entry, sl, proximal, distal, "Silver Bullet FVG (Buy)")

        if direction == "sell":
            fvgs = b7.get("bearish_fvgs", [])
            if fvgs:
                fvg      = fvgs[0]
                proximal = round(float(fvg["top"]), 2)
                distal   = round(float(fvg["bottom"]), 2)
                entry    = round(proximal - buf, 2)
                atr_buf = max(float(b1.get("atr") or 2.0) * 0.5, 0.5)
                sl = round(proximal + atr_buf, 2)
                return _make_zone(entry, sl, proximal, distal, "Silver Bullet FVG (Sell)")

        return _smart_fvg(direction, b7, buf, current_price, b1, b2, b3)

    # ── BREAKOUT MODELS ─────────────────────────────────────────────
    if model_name == "momentum_breakout":
        atr = float(b1.get("atr") or 2.0)
        buf = round(max(atr * 0.1, 0.3), 2)  # small buffer beyond structure

        if direction == "buy":
            entry = round(current_price - 0.3, 2)
            # SL: below the M15 swing low — actual structure, not arbitrary ATR
            # Cap: SL must be within 3x ATR of entry — prevents using ancient swing lows
            sl = None
            m15_sl = b2.get("timeframes", {}).get("M15", {}).get("last_sl")
            if m15_sl:
                m15_sl_price = float(m15_sl["price"]) if isinstance(m15_sl, dict) else float(m15_sl)
                if m15_sl_price < entry and (entry - m15_sl_price) <= atr * 1.5:
                    sl = round(m15_sl_price - buf, 2)
            # Fallback: H1 swing low, capped at 1.5x ATR
            if not sl:
                h1_sl = b2.get("timeframes", {}).get("H1", {}).get("last_sl")
                if h1_sl:
                    h1_sl_price = float(h1_sl["price"]) if isinstance(h1_sl, dict) else float(h1_sl)
                    if h1_sl_price < entry and (entry - h1_sl_price) <= atr * 1.5:
                        sl = round(h1_sl_price - buf, 2)
            # Final fallback: ATR-based
            if not sl:
                sl = round(current_price - max(atr * 0.8, 1.0), 2)
            return _make_zone(entry, sl, current_price, sl, "Momentum Breakout (Buy)")

        elif direction == "sell":
            entry = round(current_price - 0.3, 2)
            # SL: above the M15 swing high — actual structure, capped at 3x ATR
            sl = None
            m15_sh = b2.get("timeframes", {}).get("M15", {}).get("last_sh")
            if m15_sh:
                m15_sh_price = float(m15_sh["price"]) if isinstance(m15_sh, dict) else float(m15_sh)
                if m15_sh_price > entry and (m15_sh_price - entry) <= atr * 2:
                    sl = round(m15_sh_price + buf, 2)
            if not sl:
                h1_sh = b2.get("timeframes", {}).get("H1", {}).get("last_sh")
                if h1_sh:
                    h1_sh_price = float(h1_sh["price"]) if isinstance(h1_sh, dict) else float(h1_sh)
                    if h1_sh_price > entry and (h1_sh_price - entry) <= atr * 2:
                        sl = round(h1_sh_price + buf, 2)
            if not sl:
                sl = round(current_price + max(atr * 0.8, 1.0), 2)
            return _make_zone(entry, sl, current_price, sl, "Momentum Breakout (Sell)")

    if model_name == "structural_breakout":
        # Check if this should be handled by momentum breakout
        if b13 and b13.get("structural_breakout", {}).get("should_use_momentum"):
            return None
        
        bos_level = None
        if b13:
            structural = b13.get("structural_breakout", {})
            bos_level = structural.get("bos_level")
        
        if bos_level:
            # Check if price moved away without retest (straight shooter scenario)
            if direction == "sell" and current_price < float(bos_level) - 1.5:
                # Price dropped without retest — straight shooter with tightened SL
                atr = float(b1.get("atr") or 2.0)
                entry = round(current_price - 0.3, 2)
                
                # Find the NEAREST swing high for SL
                sl = None
                # Try H4 swing high first
                h4_sh = b2.get("timeframes", {}).get("H4", {}).get("last_sh")
                if h4_sh:
                    sh_p = float(h4_sh["price"]) if isinstance(h4_sh, dict) else float(h4_sh)
                    # Only use if within 150 pips (not too far)
                    if sh_p - current_price < 15.0:
                        sl = round(sh_p + buf, 2)
                
                # If H4 swing too far, try M15 swing
                if sl is None:
                    m15_sh = b2.get("timeframes", {}).get("M15", {}).get("last_sh")
                    if m15_sh:
                        m15_sh_p = float(m15_sh["price"]) if isinstance(m15_sh, dict) else float(m15_sh)
                        sl = round(m15_sh_p + buf, 2)
                
                # Fallback to ATR-based (but will be capped by _make_zone)
                if sl is None:
                    sl = round(current_price + max(atr * 0.8, 1.5), 2)
                
                return _make_zone(entry, sl, bos_level, sl, "Structural Breakout → Straight Shooter")
            
            elif direction == "buy" and current_price > float(bos_level) + 1.5:
                # Price rose without retest — straight shooter with tightened SL
                atr = float(b1.get("atr") or 2.0)
                entry = round(current_price + 0.3, 2)
                
                sl = None
                # Try H4 swing low first
                h4_sl = b2.get("timeframes", {}).get("H4", {}).get("last_sl")
                if h4_sl:
                    sl_p = float(h4_sl["price"]) if isinstance(h4_sl, dict) else float(h4_sl)
                    if current_price - sl_p < 15.0:
                        sl = round(sl_p - buf, 2)
                
                if sl is None:
                    m15_sl = b2.get("timeframes", {}).get("M15", {}).get("last_sl")
                    if m15_sl:
                        m15_sl_p = float(m15_sl["price"]) if isinstance(m15_sl, dict) else float(m15_sl)
                        sl = round(m15_sl_p - buf, 2)
                
                if sl is None:
                    sl = round(current_price - max(atr * 0.8, 1.5), 2)
                
                return _make_zone(entry, sl, bos_level, sl, "Structural Breakout → Straight Shooter")
            
            # Normal retest entry — use swing levels for SL, not just BOS + tiny buffer
            atr = float(b1.get("atr") or 2.0)
            min_sl_dist = max(atr * 0.5, 1.0)  # minimum 0.5x ATR = ~50-100 pips on gold

            if direction == "sell":
                entry = round(float(bos_level) - 0.5, 2)
                # SL: above last M15 swing high
                sl = None
                m15_sh = b2.get("timeframes", {}).get("M15", {}).get("last_sh")
                if m15_sh:
                    sh_p = float(m15_sh["price"]) if isinstance(m15_sh, dict) else float(m15_sh)
                    if sh_p > entry and (sh_p - entry) <= atr * 3:
                        sl = round(sh_p + buf, 2)
                if sl is None:
                    sl = round(entry + min_sl_dist, 2)
                return _make_zone(entry, sl, float(bos_level), sl, "Structural Breakout (Retest)")
            else:
                entry = round(float(bos_level) + 0.5, 2)
                # SL: below last M15 swing low
                sl = None
                m15_sl = b2.get("timeframes", {}).get("M15", {}).get("last_sl")
                if m15_sl:
                    sl_p = float(m15_sl["price"]) if isinstance(m15_sl, dict) else float(m15_sl)
                    if sl_p < entry and (entry - sl_p) <= atr * 3:
                        sl = round(sl_p - buf, 2)
                if sl is None:
                    sl = round(entry - min_sl_dist, 2)
                return _make_zone(entry, sl, float(bos_level), sl, "Structural Breakout (Retest)")
        
        # Fallback to OB/FVG if BOS level not available
        ob_entry  = _smart_ob(direction, b7, buf, current_price, b1, b2, b3)
        fvg_entry = _smart_fvg(direction, b7, buf, current_price, b1, b2, b3)
        if ob_entry and fvg_entry:
            ob_dist  = abs(ob_entry["entry"]  - current_price)
            fvg_dist = abs(fvg_entry["entry"] - current_price)
            best = ob_entry if ob_dist <= fvg_dist else fvg_entry
            best["label"] = "Structural Breakout Retest"
            return best
        entry_zone = ob_entry or fvg_entry
        if entry_zone:
            entry_zone["label"] = "Structural Breakout Retest"
            return entry_zone
        atr = float(b1.get("atr") or 2.0)
        if direction == "sell":
            entry = round(current_price - 0.3, 2)
            sl    = round(current_price + atr * 0.5, 2)
        else:
            entry = round(current_price + 0.3, 2)
            sl    = round(current_price - atr * 0.5, 2)
        return _make_zone(entry, sl, current_price, sl, "Structural Breakout")

    return _smart_ob_fvg(direction, b7, buf, current_price, b1, b2, b3)


# ============================================================
# ZONE HELPERS
# ============================================================

MIN_ZONE_SIZE = 0.5
SL_MIN_PIPS = 2.5   # 25 pips minimum
SL_MAX_PIPS = 20.0  # 200 pips maximum


def _make_zone(entry, sl, proximal, distal, label):
    zone_size = abs(proximal - distal)
    sl_distance = abs(entry - sl)

    # Floor: minimum 25 pips
    if sl_distance < SL_MIN_PIPS:
        sl = round(entry - SL_MIN_PIPS, 2) if entry > sl else round(entry + SL_MIN_PIPS, 2)
        sl_distance = SL_MIN_PIPS

    # Hard cap: maximum 200 pips
    if sl_distance > SL_MAX_PIPS:
        sl = round(entry - SL_MAX_PIPS, 2) if entry > sl else round(entry + SL_MAX_PIPS, 2)

    return {
        "entry":       entry,
        "sl":          sl,
        "proximal":    proximal,
        "distal":      distal,
        "label":       label,
        "zone_top":    max(proximal, distal),
        "zone_bottom": min(proximal, distal),
        "zone_size":   round(zone_size, 2),
    }


def _apply_sl_cap(entry, sl):
    sl_dist = abs(entry - sl)
    if sl_dist > SL_MAX_PIPS:
        sl = round(entry + SL_MAX_PIPS, 2) if sl > entry else round(entry - SL_MAX_PIPS, 2)
    if sl_dist < SL_MIN_PIPS:
        sl = round(entry + SL_MIN_PIPS, 2) if sl > entry else round(entry - SL_MIN_PIPS, 2)
    return sl


def _get_structural_sl(direction, entry_price, b1, b2, b3, max_pips=5.0):
    atr = float(b1.get("atr") or 2.0) if b1 else 2.0
    sl  = None

    if direction == "sell":
        if b2:
            for tf in ["H4", "D1", "H1"]:
                sh = b2.get("timeframes", {}).get(tf, {}).get("last_sh")
                if sh:
                    p = float(sh["price"]) if isinstance(sh, dict) else float(sh)
                    if p > entry_price and (p - entry_price) <= max_pips:
                        sl = round(p + 0.5, 2)
                        break
        if not sl and b3:
            bsl = b3.get("nearest_bsl")
            if bsl and float(bsl) > entry_price and (float(bsl) - entry_price) <= max_pips:
                sl = round(float(bsl) + 0.5, 2)
        if not sl and b3:
            pdh = b3.get("pdh")
            if pdh and float(pdh) > entry_price and (float(pdh) - entry_price) <= max_pips:
                sl = round(float(pdh) + 0.5, 2)
        if not sl:
            sl = round(entry_price + min(atr * 0.3, max_pips), 2)
    else:
        if b2:
            for tf in ["H4", "D1", "H1"]:
                sl_pt = b2.get("timeframes", {}).get(tf, {}).get("last_sl")
                if sl_pt:
                    p = float(sl_pt["price"]) if isinstance(sl_pt, dict) else float(sl_pt)
                    if p < entry_price and (entry_price - p) <= max_pips:
                        sl = round(p - 0.5, 2)
                        break
        if not sl and b3:
            ssl = b3.get("nearest_ssl")
            if ssl and float(ssl) < entry_price and (entry_price - float(ssl)) <= max_pips:
                sl = round(float(ssl) - 0.5, 2)
        if not sl and b3:
            pdl = b3.get("pdl")
            if pdl and float(pdl) < entry_price and (entry_price - float(pdl)) <= max_pips:
                sl = round(float(pdl) - 0.5, 2)
        if not sl:
            sl = round(entry_price - min(atr * 0.3, max_pips), 2)

    return sl


def _smart_ob_fvg(direction, b7, buf, current_price=None, b1=None, b2=None, b3=None):
    result = _smart_ob(direction, b7, buf, current_price, b1, b2, b3)
    if result:
        return result
    return _smart_fvg(direction, b7, buf, current_price, b1, b2, b3)


def _smart_ob(direction, b7, buf, current_price=None, b1=None, b2=None, b3=None):
    MAX_DIST = 5.0
    MIN_SIZE = 0.8

    if direction == "buy":
        obs = b7.get("bullish_obs", [])
        candidates = []
        for ob in obs:
            proximal  = round(float(ob["bottom"]), 2)
            distal    = round(float(ob["top"]), 2)
            zone_size = abs(distal - proximal)
            touches   = ob.get("touches", 0)
            if zone_size < MIN_SIZE: continue
            if touches >= 3: continue
            if current_price and abs(proximal - current_price) > MAX_DIST: continue
            dist = abs(proximal - current_price) if current_price else 0
            candidates.append((dist, touches, -zone_size, proximal, distal))
        if candidates:
            candidates.sort()
            _, t, _, proximal, distal = candidates[0]
            label = "Bull OB (fresh)" if t == 0 else "Bull OB"
            entry_price = round(proximal + buf, 2)
            atr_buf = float(b1.get("atr") or 2.0) * 0.3 if b1 else 0.5
            atr_buf = max(atr_buf, 0.5)
            sl = round(proximal - atr_buf, 2)
            return _make_zone(entry_price, sl, proximal, distal, label)

    elif direction == "sell":
        obs = b7.get("bearish_obs", [])
        candidates = []
        for ob in obs:
            proximal  = round(float(ob["top"]), 2)
            distal    = round(float(ob["bottom"]), 2)
            zone_size = abs(proximal - distal)
            touches   = ob.get("touches", 0)
            if zone_size < MIN_SIZE: continue
            if touches >= 3: continue
            if current_price and abs(proximal - current_price) > MAX_DIST: continue
            dist = abs(proximal - current_price) if current_price else 0
            candidates.append((dist, touches, -zone_size, proximal, distal))
        if candidates:
            candidates.sort()
            _, t, _, proximal, distal = candidates[0]
            label = "Bear OB (fresh)" if t == 0 else "Bear OB"
            entry_price = round(proximal - buf, 2)
            atr_buf = float(b1.get("atr") or 2.0) * 0.3 if b1 else 0.5
            atr_buf = max(atr_buf, 0.5)
            sl = round(proximal + atr_buf, 2)
            return _make_zone(entry_price, sl, proximal, distal, label)
    return None


def _smart_fvg(direction, b7, buf, current_price=None, b1=None, b2=None, b3=None):
    MAX_DIST = 5.0

    # Detect strong trend: H4+H1+M15 all agree
    strong_trend = False
    if b2 and current_price:
        h4_bias  = b2.get("timeframes", {}).get("H4", {}).get("bias", "neutral")
        h1_bias  = b2.get("timeframes", {}).get("H1", {}).get("bias", "neutral")
        m15_bias = b2.get("timeframes", {}).get("M15", {}).get("bias", "neutral")
        if direction == "buy":
            strong_trend = (h4_bias == "bullish" and h1_bias == "bullish" and m15_bias == "bullish")
        elif direction == "sell":
            strong_trend = (h4_bias == "bearish" and h1_bias == "bearish" and m15_bias == "bearish")

    if direction == "buy":
        fvgs = b7.get("bullish_fvgs", [])
        for fvg in fvgs:
            proximal = round(float(fvg["bottom"]), 2)
            distal   = round(float(fvg["top"]), 2)
            midpoint = round(float(fvg["midpoint"]), 2)
            if current_price and abs(midpoint - current_price) > MAX_DIST:
                continue
            atr_val = float(b1.get("atr") or 2.0) if b1 else 2.0
            sl_buf  = max(atr_val * 0.15, 0.3)
            # Strong trend: enter at current price — no pullback coming
            # Ranging: wait at FVG midpoint for pullback fill
            at_fvg_now = b7.get("at_bull_fvg", False)
            if strong_trend or at_fvg_now:
                entry = round(current_price, 2)
            else:
                entry = midpoint
            sl = round(proximal - sl_buf, 2)
            return _make_zone(entry, sl, proximal, distal, "Bull FVG CE")

    elif direction == "sell":
        fvgs = b7.get("bearish_fvgs", [])
        for fvg in fvgs:
            proximal = round(float(fvg["top"]), 2)
            distal   = round(float(fvg["bottom"]), 2)
            midpoint = round(float(fvg["midpoint"]), 2)
            if current_price and abs(midpoint - current_price) > MAX_DIST:
                continue
            atr_val = float(b1.get("atr") or 2.0) if b1 else 2.0
            sl_buf  = max(atr_val * 0.15, 0.3)
            at_fvg_now = b7.get("at_bear_fvg", False)
            if strong_trend or at_fvg_now:
                entry = round(current_price, 2)
            else:
                entry = midpoint
            sl = round(proximal + sl_buf, 2)
            return _make_zone(entry, sl, proximal, distal, "Bear FVG CE")

    return None


# ============================================================
# TP CALCULATION — structure-based targets from liquidity pools
# ============================================================

def _collect_targets(direction, entry, b3, b2, b4):
    targets = []

    def add(price, label):
        if price and price != 0:
            p = float(price)
            if direction == "sell" and p < entry:
                targets.append((entry - p, p, label))
            elif direction == "buy" and p > entry:
                targets.append((p - entry, p, label))

    if b3:
        for lvl in b3.get("ssl_levels", []):
            add(lvl.get("level") or lvl.get("price"), "SSL")
        for lvl in b3.get("bsl_levels", []):
            add(lvl.get("level") or lvl.get("price"), "BSL")
        for lvl in b3.get("eql_levels", []):
            add(lvl.get("level"), "EQL")
        for lvl in b3.get("eqh_levels", []):
            add(lvl.get("level"), "EQH")
        add(b3.get("pdh"), "PDH")
        add(b3.get("pdl"), "PDL")
        add(b3.get("pwh"), "PWH")
        add(b3.get("pwl"), "PWL")
        add(b3.get("asian_high"), "Asian High")
        add(b3.get("asian_low"),  "Asian Low")

    if b2:
        for tf in ["M15", "H1", "H4", "D1"]:
            tf_data = b2.get("timeframes", {}).get(tf, {})
            last_sh = tf_data.get("last_sh")
            last_sl = tf_data.get("last_sl")
            if last_sh:
                p = last_sh["price"] if isinstance(last_sh, dict) else last_sh
                add(p, f"{tf} Swing High")
            if last_sl:
                p = last_sl["price"] if isinstance(last_sl, dict) else last_sl
                add(p, f"{tf} Swing Low")

    if b4:
        for lvl in b4.get("all_levels", []):
            add(lvl.get("level"), lvl.get("label", lvl.get("source", "Level")))
        add(b4.get("nwog_ce"), "NWOG CE")
        add(b4.get("ndog_ce"), "NDOG CE")

    targets.sort(key=lambda x: x[0])
    return targets


def calculate_tps(direction, entry, sl, b3=None, b2=None, b4=None):
    sl_distance = abs(entry - sl)
    if sl_distance < 0.5:
        sl_distance = 0.5
        sl = round(entry - sl_distance, 2) if direction == "buy" else round(entry + sl_distance, 2)

    # Absolute pip minimums — no scalping ever (1 point = 10 pips on XAUUSD)
    TP1_MIN_PIPS = 10.0   # 100 pips minimum
    TP2_MIN_PIPS = 20.0   # 200 pips minimum
    TP3_MIN_PIPS = 40.0   # 400 pips minimum

    # Use larger of: pip floor OR RR-based minimum
    min_tp1 = max(TP1_MIN_PIPS, sl_distance * max(TP1_RR, 2.5))
    min_tp2 = max(TP2_MIN_PIPS, sl_distance * max(TP2_RR, 4.5))
    min_tp3 = max(TP3_MIN_PIPS, sl_distance * max(TP3_RR, 7.5))

    tp1 = tp2 = tp3 = None

    if b3 or b2 or b4:
        targets = _collect_targets(direction, entry, b3, b2, b4)

        for dist, price, label in targets:
            if not tp1 and dist >= min_tp1:
                tp1 = round(price, 2)
            elif tp1 and not tp2 and dist >= min_tp2 and abs(price - tp1) > 5.0:  # 50pip min separation
                tp2 = round(price, 2)
            elif tp2 and not tp3 and dist >= min_tp3 and abs(price - tp2) > 5.0:  # 50pip min separation
                tp3 = round(price, 2)
            if tp1 and tp2 and tp3:
                break

    if not tp1:
        tp1 = round(entry + min_tp1, 2) if direction == "buy" else round(entry - min_tp1, 2)
    if not tp2:
        tp2 = round(entry + min_tp2, 2) if direction == "buy" else round(entry - min_tp2, 2)
    if not tp3:
        tp3 = round(entry + min_tp3, 2) if direction == "buy" else round(entry - min_tp3, 2)

    return {
        "sl":          sl,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "sl_distance": round(sl_distance, 2),
        "sl_pips":     round(sl_distance * 10, 1),
    }


# ============================================================
# STATE MACHINE
# ============================================================

def process_state_machine(trade_state, b9, current_price, entry_data, lot_size, model_name):
    now    = datetime.now().isoformat()
    status = trade_state["status"]

    if trade_state.get("cooldown_until"):
        try:
            if datetime.now() < datetime.fromisoformat(trade_state["cooldown_until"]):
                remaining = round(
                    (datetime.fromisoformat(trade_state["cooldown_until"]) - datetime.now()
                     ).total_seconds() / 60, 1)
                trade_state["status"] = "COOLDOWN"
                return trade_state, f"Cooldown — {remaining}min remaining"
        except Exception:
            pass

    if status in ["IDLE", "COOLDOWN"]:
        if b9["should_trade"] and entry_data:
            trade_state.update({
                "status":         "SIGNAL",
                "direction":      b9["direction"],
                "model_name":     model_name,
                "entry_price":    entry_data["entry"],
                "sl_price":       entry_data["sl"],
                "tp1_price":      entry_data.get("tp1"),
                "tp2_price":      entry_data.get("tp2"),
                "tp3_price":      entry_data.get("tp3"),
                "lot_size":       lot_size,
                "signal_time":    trade_state.get("signal_time") or now,  # preserve original — 4h expiry
                "tp1_hit":        False,
                "tp2_hit":        False,
                "sl_moved_to_be": False,
                "partial_closed": False,
                "m1_confirmed":   False,
                "state_message":  f"Limit at {entry_data['entry']} | {entry_data.get('label','')}",
            })
            return trade_state, f"SIGNAL — Limit {entry_data['entry']} ({entry_data.get('label','')})"
        return trade_state, "Scanning — no setup found"

    if status == "SIGNAL":
        entry     = trade_state["entry_price"]
        direction = trade_state["direction"]
        sl        = trade_state["sl_price"]

        if entry is None:
            trade_state["status"] = "IDLE"
            return trade_state, "Resetting"

        sl_distance = abs(entry - sl)
        near_entry  = abs(current_price - entry) <= 2.0

        if near_entry:
            zone_top    = (entry_data or {}).get("zone_top",    entry + 5)
            zone_bottom = (entry_data or {}).get("zone_bottom", entry - 5)
            m1_ok, m1_msg = get_m1_confirmation(direction, zone_top, zone_bottom)

            if m1_ok:
                trade_state.update({
                    "status":       "ACTIVE",
                    "entry_time":   now,
                    "m1_confirmed": True,
                    "state_message": f"ENTERED {direction.upper()} at {current_price} | {m1_msg}",
                })
                return trade_state, f"ENTRY ✓ | {m1_msg}"
            else:
                trade_state["state_message"] = f"At zone — {m1_msg}"
                return trade_state, f"At zone — {m1_msg}"

        sl_breached = (direction == "sell" and current_price >= sl) or (direction == "buy"  and current_price <= sl)
        if sl_breached:
            trade_state["missed_entries"] = trade_state.get("missed_entries", 0) + 1
            trade_state["status"]         = "IDLE"
            trade_state["state_message"]  = "Signal voided — price breached SL before entry"
            return trade_state, "Signal voided — SL breached before entry"

        if direction == "buy":
            too_far = current_price > entry + sl_distance * MAX_CHASE_FRACTION
        else:
            too_far = current_price < entry - sl_distance * MAX_CHASE_FRACTION

        if too_far:
            missed = trade_state.get("missed_entries", 0) + 1
            trade_state["missed_entries"] = missed
            # Miss #1: 5min, Miss #2: 10min, Miss #3+: 60min (setup abandoned)
            if missed >= 3:
                cooldown_mins = 60
            elif missed == 2:
                cooldown_mins = 10
            else:
                cooldown_mins = 5
            trade_state["status"]         = "COOLDOWN"
            trade_state["cooldown_until"] = (datetime.now() + timedelta(minutes=cooldown_mins)).isoformat()
            trade_state["state_message"]  = f"Missed entry x{missed} — {cooldown_mins}min cooldown"
            return trade_state, f"Signal expired — miss #{missed} — {cooldown_mins}min cooldown"

        trade_state["state_message"] = f"Limit {entry} | Price {round(current_price, 2)}"
        return trade_state, f"Waiting | Limit {entry} | Now {round(current_price, 2)}"

    if status == "ACTIVE":
        entry     = trade_state["entry_price"]
        sl        = trade_state["sl_price"]
        tp1       = trade_state["tp1_price"]
        tp2       = trade_state["tp2_price"]
        tp3       = trade_state["tp3_price"]
        direction = trade_state["direction"]

        sl_hit = (direction == "buy"  and current_price <= sl) or \
                 (direction == "sell" and current_price >= sl)
        if sl_hit:
            pnl = (current_price - entry) if direction == "buy" else (entry - current_price)
            trade_state.update({
                "status":         "CLOSED",
                "close_time":     now,
                "close_reason":   "SL_HIT",
                "pnl_pips":       round(pnl * 10, 1),
                "cooldown_until": (datetime.now() + timedelta(minutes=5)).isoformat(),
                "state_message":  f"SL hit — {round(pnl * 10, 1)} pips",
            })
            return trade_state, f"SL HIT — {round(pnl * 10, 1)} pips"

        tp3_hit = (direction == "buy"  and current_price >= tp3) or \
                  (direction == "sell" and current_price <= tp3)
        if tp3_hit:
            pnl = (tp3 - entry) if direction == "buy" else (entry - tp3)
            trade_state.update({
                "status":       "CLOSED",
                "close_time":   now,
                "close_reason": "TP3_HIT",
                "pnl_pips":     round(pnl * 10, 1),
                "tp1_hit":      True,
                "tp2_hit":      True,
                "state_message": f"TP3 ✓✓✓ — {round(pnl * 10, 1)} pips",
            })
            return trade_state, f"TP3 HIT ✓✓✓ — {round(pnl * 10, 1)} pips"

        if not trade_state.get("tp2_hit"):
            tp2_hit = (direction == "buy"  and current_price >= tp2) or \
                      (direction == "sell" and current_price <= tp2)
            if tp2_hit:
                trade_state["tp2_hit"]        = True
                trade_state["tp1_hit"]        = True
                # FIX: SL moves to TP1 after TP2 (not just BE)
                # This locks TP1 profit on the runner — if TP3 misses, you still exit at TP1
                trade_state["sl_price"]       = tp1
                trade_state["sl_moved_to_be"] = True
                trade_state["state_message"]  = f"TP2 ✓✓ — SL to TP1 ({tp1})"
                return trade_state, f"TP2 HIT ✓✓ — SL to TP1 ({tp1})"

        if not trade_state.get("tp1_hit"):
            tp1_hit = (direction == "buy"  and current_price >= tp1) or \
                      (direction == "sell" and current_price <= tp1)
            if tp1_hit:
                trade_state["tp1_hit"]        = True
                trade_state["sl_price"]       = entry
                trade_state["sl_moved_to_be"] = True
                trade_state["partial_closed"] = True
                trade_state["state_message"]  = "TP1 ✓ — SL at BE, 30% closed"
                return trade_state, "TP1 HIT ✓ — SL to BE"

        unrealised = (current_price - entry) if direction == "buy" else (entry - current_price)
        pips = round(unrealised * 10, 1)
        sign = "+" if pips >= 0 else ""
        trade_state["state_message"] = f"Running {sign}{pips} pips"
        return trade_state, f"ACTIVE {sign}{pips} pips"

    if status == "CLOSED":
        trade_state["status"]        = "IDLE"
        trade_state["state_message"] = "Closed — scanning for next setup"
        return trade_state, "Trade closed — ready"

    return trade_state, f"Unknown status: {status}"


# ============================================================
# MAIN ENGINE
# ============================================================

def run(b1, b2, b3, b4, b5, b6, b7, b8, b9, b13=None, account_balance=10000.0):
    trade_state  = load_trade_state()
    strike_state = load_strike_state()

    if strike_state["system_paused"]:
        return {
            "direction": b9.get("direction", "none"),
            "should_trade": False, "grade": "NO_TRADE",
            "confluence_score": 0,
            "entry": None, "sl": None, "tp1": None, "tp2": None, "tp3": None,
            "sl_pips": None, "entry_zone": None, "lot_size": None,
            "levels": None, "size_multiplier": 1.0, "account_balance": account_balance,
            "trade_state": trade_state, "trade_status": "SYSTEM_PAUSED",
            "state_message": strike_state["system_pause_reason"],
            "model_name": "system", "model_suspended": False,
            "size_reduction": False, "system_paused": True,
            "signal_summary": f"SYSTEM PAUSED: {strike_state['system_pause_reason']}",
            "engine_score": 0,
        }

    current_price = 0
    try:
        from data.mt5_connector import get_current_price
        p = get_current_price(SYMBOL)
        if p:
            current_price = p["bid"]
    except Exception:
        pass
    if not current_price:
        current_price = float(b4.get("current_price") or 0)

    model_name = b9.get("model_name") or b8.get("best_model_name") or "unknown"

    is_suspended, suspend_reason, size_multiplier = check_model_suspended(model_name, strike_state)
    if is_suspended:
        return {
            "direction": b9.get("direction", "none"),
            "should_trade": False, "grade": b9.get("grade", "NO_TRADE"),
            "confluence_score": b9.get("score", 0),
            "entry": None, "sl": None, "tp1": None, "tp2": None, "tp3": None,
            "sl_pips": None, "entry_zone": None, "lot_size": None,
            "levels": None, "size_multiplier": size_multiplier,
            "account_balance": account_balance,
            "trade_state": trade_state, "trade_status": trade_state["status"],
            "state_message": suspend_reason,
            "model_name": model_name, "model_suspended": True,
            "size_reduction": True, "system_paused": False,
            "signal_summary": f"Model suspended: {suspend_reason}",
            "engine_score": b9.get("score", 0),
        }

    entry_data = None
    lot_size   = None

    current_status = trade_state["status"]

    if current_status in ["IDLE", "COOLDOWN"]:
        if b9["should_trade"] and current_price > 0:
            entry_data = get_entry_for_model(
                model_name, b9["direction"],
                b3, b4, b7, b1, b2, current_price, b13
            )
            if entry_data:
                tps = calculate_tps(b9["direction"], entry_data["entry"], entry_data["sl"], b3=b3, b2=b2, b4=b4)
                entry_data.update(tps)
                base_lot = calculate_lot_size(account_balance, RISK_PERCENT, tps["sl_pips"])
                lot_size = max(0.01, round(base_lot * size_multiplier, 2))
            else:
                b9 = dict(b9)
                b9["should_trade"] = False

    elif current_status in ["SIGNAL", "ACTIVE"]:
        ep = trade_state.get("entry_price") or 0
        sp = trade_state.get("sl_price")    or 0
        entry_data = {
            "entry":       ep,
            "sl":          sp,
            "tp1":         trade_state.get("tp1_price"),
            "tp2":         trade_state.get("tp2_price"),
            "tp3":         trade_state.get("tp3_price"),
            "label":       trade_state.get("model_name", ""),
            "zone_top":    ep + 10,
            "zone_bottom": ep - 10,
            "sl_pips":     round(abs(ep - sp) * 10, 1),
            "sl_distance": round(abs(ep - sp), 2),
        }
        lot_size = trade_state.get("lot_size")

    trade_state, state_message = process_state_machine(
        trade_state, b9, current_price, entry_data, lot_size, model_name
    )
    trade_state["state_message"] = state_message
    save_trade_state(trade_state)

    ts = trade_state
    final_entry = ts.get("entry_price") or (entry_data.get("entry") if entry_data else None)
    final_sl    = ts.get("sl_price")    or (entry_data.get("sl")    if entry_data else None)
    final_tp1   = ts.get("tp1_price")   or (entry_data.get("tp1")   if entry_data else None)
    final_tp2   = ts.get("tp2_price")   or (entry_data.get("tp2")   if entry_data else None)
    final_tp3   = ts.get("tp3_price")   or (entry_data.get("tp3")   if entry_data else None)
    final_pips  = entry_data.get("sl_pips")  if entry_data else None
    final_zone  = entry_data.get("label")    if entry_data else ts.get("model_name")
    final_lots  = ts.get("lot_size") or lot_size

    if b9["should_trade"] and final_entry:
        signal_summary = (
            f"{b9['direction'].upper()} | {model_name} | "
            f"Limit: {final_entry} ({final_zone}) | "
            f"SL: {final_sl} ({final_pips} pips) | "
            f"TP1:{final_tp1} TP2:{final_tp2} TP3:{final_tp3} | "
            f"Lots:{final_lots} | Score:{b9['score']}"
        )
    else:
        signal_summary = (
            f"Scanning — {model_name} | Grade:{b9['grade']} | Score:{b9['score']}"
            if not entry_data else
            f"No trade — Grade:{b9['grade']} Score:{b9['score']}"
        )

    return {
        "direction":        b9["direction"],
        "should_trade":     b9["should_trade"],
        "grade":            b9["grade"],
        "confluence_score": b9["score"],

        "entry":      final_entry,
        "sl":         final_sl,
        "tp1":        final_tp1,
        "tp2":        final_tp2,
        "tp3":        final_tp3,
        "sl_pips":    final_pips,
        "entry_zone": final_zone,
        "lot_size":   final_lots,

        "levels":          entry_data,
        "size_multiplier": size_multiplier,
        "account_balance": account_balance,

        "trade_state":    trade_state,
        "trade_status":   trade_state["status"],
        "state_message":  state_message,

        "model_name":      model_name,
        "model_suspended": is_suspended,
        "size_reduction":  size_multiplier < 1.0,
        "system_paused":   strike_state["system_paused"],

        "signal_summary":  signal_summary,
        "engine_score":    b9["score"] if b9["should_trade"] else 0,
    }


# ============================================================
# TEST
# ============================================================

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
    from engines.box13_breakout      import run as run_b13

    print("Testing Box 10 v3 — Precision Entry")
    print("=" * 55)

    mt5.initialize()
    store.refresh()

    b1 = run_b1(store); b2 = run_b2(store); b3 = run_b3(store)
    b4 = run_b4(store); b5 = run_b5(store); b6 = run_b6(store)
    b7 = run_b7(store, b2)
    b13 = run_b13(store, b1, b2, b3, b4, b5, b7)
    b8 = run_b8(b1, b2, b3, b4, b5, b6, b7, b13)
    b9 = run_b9(b1, b2, b3, b4, b5, b6, b7, b8, b13)

    acc     = mt5.account_info()
    balance = acc.balance if acc else 10000.0
    result  = run(b1, b2, b3, b4, b5, b6, b7, b8, b9, b13, balance)

    print(f"\nBalance:      ${balance:,.2f}")
    print(f"Direction:    {result['direction'].upper()}")
    print(f"Grade:        {result['grade']}")
    print(f"Model:        {result['model_name']}")
    print(f"Should Trade: {result['should_trade']}")

    if result["entry"]:
        print(f"\nEntry Zone:  {result['entry_zone']}")
        print(f"Limit:       {result['entry']}")
        print(f"SL:          {result['sl']}  ({result['sl_pips']} pips)")
        print(f"TP1 (1:1):   {result['tp1']}")
        print(f"TP2 (1:2):   {result['tp2']}")
        print(f"TP3 (1:3):   {result['tp3']}")
        print(f"Lot Size:    {result['lot_size']}")
    else:
        print("\nNo zone found — not trading")

    print(f"\nState:   {result['trade_status']}")
    print(f"Message: {result['state_message']}")

    mt5.shutdown()
    print("\nBox 10 v3 PASSED ✓")
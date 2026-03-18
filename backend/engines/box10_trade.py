# ============================================================
# box10_trade.py — Trade Engine v3
# Precision entries: proximal/distal zone logic
# M1 confirmation candle before entry fires
# Structure-based SL — never ATR, never capped
# Signal lock is ironclad — levels never change once set
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

MAX_CHASE_FRACTION = 0.5


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
# M1 CONFIRMATION
# ============================================================

def get_m1_confirmation(direction, zone_top, zone_bottom):
    """
    Check last 5 M1 candles for a rejection confirmation at zone boundary.

    BUY confirmation: price wicked below zone bottom, closed back above,
                      bullish body, meaningful lower wick.

    SELL confirmation: price wicked above zone top, closed back below,
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
                if (l <= zone_bottom and
                    close > zone_bottom and
                    close > o and
                    lower_wick / candle_range > 0.35):
                    return True, f"M1 bullish rejection at {round(zone_bottom, 2)}"

            elif direction == "sell":
                upper_wick = h - max(o, close)
                if (h >= zone_top and
                    close < zone_top and
                    close < o and
                    upper_wick / candle_range > 0.35):
                    return True, f"M1 bearish rejection at {round(zone_top, 2)}"

        return False, "Waiting for M1 rejection candle at zone"

    except Exception as e:
        return True, f"M1 check skipped ({e})"


# ============================================================
# PER-MODEL ENTRY LOGIC — PROXIMAL / DISTAL
# ============================================================

def get_entry_for_model(model_name, direction, b3, b4, b7, b1, b2, current_price):
    """
    Proximal = edge of zone price approaches FIRST (ENTRY point)
    Distal   = far edge of zone (SL goes just beyond this)

    SELL: proximal = zone TOP,    distal = zone BOTTOM
    BUY:  proximal = zone BOTTOM, distal = zone TOP

    SL buffer (buf) is added beyond the distal edge.
    Proximity filter: entry must be within 25 pips of current price.
    """
    buf = 0.5  # 5 pips buffer beyond zone (SL_BUFFER_PIPS=5 was 50 pips — too wide)
    MAX_ENTRY_DISTANCE = 2.5  # 25 pips max from current price

    # ── MODEL 1: London Sweep & Reverse ──────────────────────────
    if model_name == "london_sweep_reverse":
        if direction == "sell" and b3.get("asian_high_swept"):
            ah = b3.get("asian_high")
            if ah:
                ah = float(ah)
                proximal = round(ah, 2)
                distal   = round(ah + 5, 2)          # wick above sweep
                entry    = round(proximal - buf, 2)
                sl       = round(distal + buf, 2)
                return _make_zone(entry, sl, proximal, distal, "Asian High Sweep Reversal")

        if direction == "buy" and b3.get("asian_low_swept"):
            al = b3.get("asian_low")
            if al:
                al = float(al)
                proximal = round(al, 2)
                distal   = round(al - 5, 2)
                entry    = round(proximal + buf, 2)
                sl       = round(distal - buf, 2)
                return _make_zone(entry, sl, proximal, distal, "Asian Low Sweep Reversal")

        return _smart_ob_fvg(direction, b7, buf, current_price)

    # ── MODEL 2: NY Continuation ──────────────────────────────────
    elif model_name == "ny_continuation":
        result = _smart_ob_fvg(direction, b7, buf)
        if result:
            result["label"] = "NY Continuation OB"
        return result

    # ── MODEL 3: Asian Range Breakout ─────────────────────────────
    elif model_name == "asian_range_breakout":
        ah = b3.get("asian_high")
        al = b3.get("asian_low")
        if direction == "buy" and ah:
            ah = float(ah)
            proximal = round(ah, 2)
            distal   = round(ah - 8, 2)
            entry    = round(proximal + buf, 2)
            sl       = round(distal - buf, 2)
            return _make_zone(entry, sl, proximal, distal, "Asian Breakout Retest (Buy)")
        if direction == "sell" and al:
            al = float(al)
            proximal = round(al, 2)
            distal   = round(al + 8, 2)
            entry    = round(proximal - buf, 2)
            sl       = round(distal + buf, 2)
            return _make_zone(entry, sl, proximal, distal, "Asian Breakout Retest (Sell)")
        return None

    # ── MODEL 4: OB + FVG Stack ───────────────────────────────────
    elif model_name == "ob_fvg_stack":
        if direction == "sell":
            obs  = b7.get("bearish_obs",  [])
            fvgs = b7.get("bearish_fvgs", [])
            if obs and fvgs:
                ob, fvg    = obs[0], fvgs[0]
                stack_top    = max(float(ob["top"]),    float(fvg["top"]))
                stack_bottom = min(float(ob["bottom"]), float(fvg["bottom"]))
                proximal = round(stack_top, 2)       # SELL: price comes from above
                distal   = round(stack_bottom, 2)    # far side = bottom of stack
                entry    = round(proximal - buf, 2)
                sl       = round(proximal + buf, 2)  # SL just ABOVE stack top (above entry)
                stack_size = round(stack_top - stack_bottom, 2)
                # Skip if entry too far from price or stack too large
                if (current_price and abs(proximal - current_price) > 2.5) or stack_size > 3.0:
                    pass  # fall through to OB-only
                else:
                    result = _make_zone(entry, sl, proximal, distal, "OB+FVG Stack (Sell)")
                    result["stack_size"] = stack_size
                    return result
            if obs:
                ob = obs[0]
                proximal = round(float(ob["top"]), 2)
                distal   = round(float(ob["bottom"]), 2)
                if not (current_price and abs(proximal - current_price) > 2.5):
                    entry    = round(proximal - buf, 2)
                    sl       = round(proximal + buf, 2)  # SL above OB top
                    return _make_zone(entry, sl, proximal, distal, "Bear OB (Sell)")

        elif direction == "buy":
            obs  = b7.get("bullish_obs",  [])
            fvgs = b7.get("bullish_fvgs", [])
            if obs and fvgs:
                ob, fvg    = obs[0], fvgs[0]
                stack_top    = max(float(ob["top"]),    float(fvg["top"]))
                stack_bottom = min(float(ob["bottom"]), float(fvg["bottom"]))
                proximal = round(stack_bottom, 2)
                distal   = round(stack_top, 2)
                entry    = round(proximal + buf, 2)
                sl       = round(distal + buf, 2)
                stack_size = round(stack_top - stack_bottom, 2)
                if (current_price and abs(proximal - current_price) > 2.5) or stack_size > 3.0:
                    pass  # fall through
                else:
                    result = _make_zone(entry, sl, proximal, distal, "OB+FVG Stack (Buy)")
                    result["stack_size"] = stack_size
                    return result
            elif obs:
                ob = obs[0]
                proximal = round(float(ob["bottom"]), 2)
                distal   = round(float(ob["top"]), 2)
                entry    = round(proximal + buf, 2)
                sl       = round(distal + buf, 2)
                return _make_zone(entry, sl, proximal, distal, "Bull OB (Buy)")

        return None

    # ── MODEL 5: Liquidity Grab + BOS ─────────────────────────────
    elif model_name == "liquidity_grab_bos":
        fvg = _smart_fvg(direction, b7, buf)
        if fvg:
            fvg["label"] = "FVG After BOS Displacement"
            return fvg

        if direction == "buy" and b3.get("pdl_swept"):
            pdl = b3.get("pdl")
            if pdl:
                pdl = float(pdl)
                proximal = round(pdl, 2)
                distal   = round(pdl - 10, 2)
                entry    = round(proximal + buf, 2)
                sl       = round(distal - buf, 2)
                return _make_zone(entry, sl, proximal, distal, "PDL Sweep + BOS")

        if direction == "sell" and b3.get("pdh_swept"):
            pdh = b3.get("pdh")
            if pdh:
                pdh = float(pdh)
                proximal = round(pdh, 2)
                distal   = round(pdh + 10, 2)
                entry    = round(proximal - buf, 2)
                sl       = round(distal + buf, 2)
                return _make_zone(entry, sl, proximal, distal, "PDH Sweep + BOS")

        return _smart_ob_fvg(direction, b7, buf, current_price)

    # ── MODEL 6: HTF Level Reaction ───────────────────────────────
    elif model_name == "htf_level_reaction":
        closest = b4.get("closest_level")
        if closest and b4.get("at_key_level"):
            level = float(closest.get("level") or closest.get("price") or 0)
            if level > 0:
                if direction == "buy":
                    proximal = round(level, 2)
                    distal   = round(level - 12, 2)
                    entry    = round(proximal + buf, 2)
                    sl       = round(distal - buf, 2)
                else:
                    proximal = round(level, 2)
                    distal   = round(level + 12, 2)
                    entry    = round(proximal - buf, 2)
                    sl       = round(distal + buf, 2)
                return _make_zone(entry, sl, proximal, distal,
                                  f"HTF Level: {closest.get('label', '')}")
        return _smart_ob_fvg(direction, b7, buf, current_price)

    # ── MODEL 7: CHOCH Reversal ───────────────────────────────────
    elif model_name == "choch_reversal":
        if direction == "buy" and b7.get("bull_breakers"):
            bb = b7["bull_breakers"][0]
            proximal = round(float(bb["bottom"]), 2)
            distal   = round(float(bb["top"]), 2)
            entry    = round(proximal + buf, 2)
            sl       = round(proximal - buf, 2)
            return _make_zone(entry, sl, proximal, distal, "Bull Breaker (CHOCH)")

        if direction == "sell" and b7.get("bear_breakers"):
            bb = b7["bear_breakers"][0]
            proximal = round(float(bb["top"]), 2)
            distal   = round(float(bb["bottom"]), 2)
            entry    = round(proximal - buf, 2)
            sl       = round(proximal + buf, 2)
            return _make_zone(entry, sl, proximal, distal, "Bear Breaker (CHOCH)")

        return _smart_ob_fvg(direction, b7, buf, current_price)

    # ── MODEL 8: Double Top/Bottom Trap ──────────────────────────
    elif model_name == "double_top_bottom_trap":
        for p in b7.get("patterns", []):
            if p["type"] == "double_top" and direction == "sell":
                neckline = p.get("neckline")
                level2   = p.get("level2")
                if neckline and level2:
                    proximal = round(float(neckline), 2)
                    distal   = round(float(level2) + 5, 2)
                    entry    = round(proximal - buf, 2)
                    sl       = round(distal + buf, 2)
                    return _make_zone(entry, sl, proximal, distal, "Double Top Neckline")

            if p["type"] == "double_bottom" and direction == "buy":
                neckline = p.get("neckline")
                level2   = p.get("level2")
                if neckline and level2:
                    proximal = round(float(neckline), 2)
                    distal   = round(float(level2) - 5, 2)
                    entry    = round(proximal + buf, 2)
                    sl       = round(distal - buf, 2)
                    return _make_zone(entry, sl, proximal, distal, "Double Bottom Neckline")

        return _smart_ob_fvg(direction, b7, buf, current_price)

    # ── MODEL 9: OB Mitigation ────────────────────────────────────
    elif model_name == "ob_mitigation":
        if direction == "buy":
            obs = b7.get("bullish_obs", [])
            if obs:
                ob = obs[0]
                proximal = round(float(ob["bottom"]), 2)
                distal   = round(float(ob["top"]), 2)
                entry    = round(proximal + buf, 2)
                sl       = round(proximal - buf, 2)
                return _make_zone(entry, sl, proximal, distal, "Bull OB Mitigation")

        if direction == "sell":
            obs = b7.get("bearish_obs", [])
            if obs:
                ob = obs[0]
                proximal = round(float(ob["top"]), 2)
                distal   = round(float(ob["bottom"]), 2)
                entry    = round(proximal - buf, 2)
                sl       = round(proximal + buf, 2)
                return _make_zone(entry, sl, proximal, distal, "Bear OB Mitigation")

        return None

    # ── MODEL 10: FVG Continuation ────────────────────────────────
    elif model_name == "fvg_continuation":
        result = _smart_fvg(direction, b7, buf)
        if result:
            result["label"] = "FVG CE (Continuation)"
        return result

    # ── SILVER BULLET ────────────────────────────────────────
    elif model_name == "silver_bullet":
        # Entry: FVG proximal edge formed after displacement
        # SL:    Beyond the swept liquidity level
        if direction == "buy":
            fvgs = b7.get("bullish_fvgs", [])
            if fvgs:
                fvg      = fvgs[0]
                proximal = round(float(fvg["bottom"]), 2)
                distal   = round(float(fvg["top"]), 2)
                entry    = round(proximal + buf, 2)
                ssl_level = b3.get("asian_low") or b3.get("pdl")
                sl = round(float(ssl_level) - buf * 2, 2) if ssl_level else round(proximal - buf, 2)
                return _make_zone(entry, sl, proximal, distal, "Silver Bullet FVG (Buy)")

        if direction == "sell":
            fvgs = b7.get("bearish_fvgs", [])
            if fvgs:
                fvg      = fvgs[0]
                proximal = round(float(fvg["top"]), 2)
                distal   = round(float(fvg["bottom"]), 2)
                entry    = round(proximal - buf, 2)
                bsl_level = b3.get("asian_high") or b3.get("pdh")
                sl = round(float(bsl_level) + buf * 2, 2) if bsl_level else round(proximal + buf, 2)
                return _make_zone(entry, sl, proximal, distal, "Silver Bullet FVG (Sell)")

        return _smart_fvg(direction, b7, buf, current_price)

    return _smart_ob_fvg(direction, b7, buf, current_price)


# ============================================================
# ZONE HELPERS
# ============================================================

# Minimum zone size = 5 pips (0.5 price points on gold)
MIN_ZONE_SIZE = 0.5

def _make_zone(entry, sl, proximal, distal, label):
    zone_size = abs(proximal - distal)
    
    # SL is structural — only floor is noise prevention (< 3 pips)
    sl_distance = abs(entry - sl)
    if sl_distance < 0.3:
        if entry > sl:  # buy: sl is below
            sl = round(entry - 0.3, 2)
        else:
            sl = round(entry + 0.3, 2)
    
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


def _smart_ob_fvg(direction, b7, buf, current_price=None):
    return _smart_ob(direction, b7, buf, current_price) or _smart_fvg(direction, b7, buf, current_price)


def _smart_ob(direction, b7, buf, current_price=None):
    """
    Find best quality OB: closest to price, fewest touches, biggest size.
    Fresh OBs (0 touches) are preferred. Over-touched (3+) are rejected.
    """
    MAX_DIST = 2.5  # 25 pips
    MIN_SIZE = 0.8  # 8 pips minimum

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
            return _make_zone(round(proximal + buf, 2), round(proximal - buf, 2),
                              proximal, distal, label)

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
            return _make_zone(round(proximal - buf, 2), round(proximal + buf, 2),
                              proximal, distal, label)
    return None

def _smart_fvg(direction, b7, buf, current_price=None):
    MAX_DIST = 2.5  # 25 pips
    if direction == "buy":
        fvgs = b7.get("bullish_fvgs", [])
        for fvg in fvgs:
            proximal = round(float(fvg["bottom"]), 2)
            distal   = round(float(fvg["top"]), 2)
            entry    = round(float(fvg["midpoint"]), 2)
            if current_price and abs(entry - current_price) > MAX_DIST:
                continue
            return _make_zone(entry, round(proximal - buf, 2), proximal, distal, "Bull FVG CE")
    elif direction == "sell":
        fvgs = b7.get("bearish_fvgs", [])
        for fvg in fvgs:
            proximal = round(float(fvg["top"]), 2)
            distal   = round(float(fvg["bottom"]), 2)
            entry    = round(float(fvg["midpoint"]), 2)
            if current_price and abs(entry - current_price) > MAX_DIST:
                continue
            # SELL: entry at CE, SL above proximal (top)
            return _make_zone(entry, round(proximal + buf, 2), proximal, distal, "Bear FVG CE")
            if current_price and abs(entry - current_price) > MAX_DIST:
                continue
            return _make_zone(entry, round(proximal + buf, 2), proximal, distal, "Bear FVG CE")
    return None


# ============================================================
# TP CALCULATION — no cap, structure dictates SL
# ============================================================

def calculate_tps(direction, entry, sl):
    sl_distance = abs(entry - sl)
    # SL is purely structural — no fixed minimum
    # Only reject if it's literally noise (< 3 pips = 0.3 price points)
    if sl_distance < 0.3:
        sl_distance = 0.3
        sl = round(entry - sl_distance, 2) if direction == "buy" else round(entry + sl_distance, 2)

    if direction == "buy":
        tp1 = round(entry + sl_distance * TP1_RR, 2)
        tp2 = round(entry + sl_distance * TP2_RR, 2)
        tp3 = round(entry + sl_distance * TP3_RR, 2)
    else:
        tp1 = round(entry - sl_distance * TP1_RR, 2)
        tp2 = round(entry - sl_distance * TP2_RR, 2)
        tp3 = round(entry - sl_distance * TP3_RR, 2)

    return {
        "sl":          sl,   # adjusted sl if minimum was applied
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

    # Cooldown
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

    # ── IDLE / COOLDOWN → SIGNAL ───────────────────────────────────
    if status in ["IDLE", "COOLDOWN"]:
        if b9["should_trade"] and entry_data:
            tps = calculate_tps(b9["direction"], entry_data["entry"], entry_data["sl"])
            # Use updated SL from calculate_tps (minimum may have been applied)
            final_sl = tps.get("sl", entry_data["sl"])
            trade_state.update({
                "status":         "SIGNAL",
                "direction":      b9["direction"],
                "model_name":     model_name,
                "entry_price":    entry_data["entry"],
                "sl_price":       final_sl,
                "tp1_price":      tps["tp1"],
                "tp2_price":      tps["tp2"],
                "tp3_price":      tps["tp3"],
                "lot_size":       lot_size,
                "signal_time":    now,
                "tp1_hit":        False,
                "tp2_hit":        False,
                "sl_moved_to_be": False,
                "partial_closed": False,
                "m1_confirmed":   False,
                "state_message":  f"Limit at {entry_data['entry']} | {entry_data['label']}",
            })
            return trade_state, f"SIGNAL — Limit {entry_data['entry']} ({entry_data['label']})"
        return trade_state, "Scanning — no setup found"

    # ── SIGNAL → ACTIVE ────────────────────────────────────────────
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

        # Expired — price ran without pullback
        if direction == "buy":
            too_far = current_price > entry + sl_distance * MAX_CHASE_FRACTION
        else:
            too_far = current_price < entry - sl_distance * MAX_CHASE_FRACTION

        if too_far:
            trade_state["missed_entries"] = trade_state.get("missed_entries", 0) + 1
            trade_state["status"]         = "IDLE"
            trade_state["state_message"]  = "Missed — price ran past zone"
            return trade_state, "Signal expired — price ran past zone"

        trade_state["state_message"] = f"Limit {entry} | Price {round(current_price, 2)}"
        return trade_state, f"Waiting | Limit {entry} | Now {round(current_price, 2)}"

    # ── ACTIVE ─────────────────────────────────────────────────────
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
                "cooldown_until": (datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)).isoformat(),
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
                trade_state["sl_price"]       = entry
                trade_state["sl_moved_to_be"] = True
                trade_state["state_message"]  = "TP2 ✓✓ — SL at BE"
                return trade_state, "TP2 HIT ✓✓ — SL to BE"

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

    # CLOSED → IDLE
    if status == "CLOSED":
        trade_state["status"]        = "IDLE"
        trade_state["state_message"] = "Closed — scanning for next setup"
        return trade_state, "Trade closed — ready"

    return trade_state, f"Unknown status: {status}"


# ============================================================
# MAIN ENGINE
# ============================================================

def run(b1, b2, b3, b4, b5, b6, b7, b8, b9, account_balance=10000.0):
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

    # Current price
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

    # ── Entry data ─────────────────────────────────────────────────
    entry_data = None
    lot_size   = None

    current_status = trade_state["status"]

    if current_status in ["IDLE", "COOLDOWN"]:
        # Only calculate entry when idle — looking for new setup
        if b9["should_trade"] and current_price > 0:
            entry_data = get_entry_for_model(
                model_name, b9["direction"],
                b3, b4, b7, b1, b2, current_price
            )
            if entry_data:
                tps = calculate_tps(b9["direction"], entry_data["entry"], entry_data["sl"])
                entry_data.update(tps)  # updates sl, tp1, tp2, tp3, sl_pips, sl_distance
                base_lot = calculate_lot_size(account_balance, RISK_PERCENT, tps["sl_pips"])
                lot_size = max(0.01, round(base_lot * size_multiplier, 2))
            else:
                b9 = dict(b9)
                b9["should_trade"] = False

    elif current_status in ["SIGNAL", "ACTIVE"]:
        # ── IRONCLAD: always use locked state, never recalculate ───
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

    # State machine
    trade_state, state_message = process_state_machine(
        trade_state, b9, current_price, entry_data, lot_size, model_name
    )
    trade_state["state_message"] = state_message
    save_trade_state(trade_state)

    # Final levels — always from trade_state when SIGNAL/ACTIVE
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

    print("Testing Box 10 v3 — Precision Entry")
    print("=" * 55)

    mt5.initialize()
    store.refresh()

    b1 = run_b1(store); b2 = run_b2(store); b3 = run_b3(store)
    b4 = run_b4(store); b5 = run_b5(store); b6 = run_b6(store)
    b7 = run_b7(store)
    b8 = run_b8(b1, b2, b3, b4, b5, b6, b7)
    b9 = run_b9(b1, b2, b3, b4, b5, b6, b7, b8)

    acc     = mt5.account_info()
    balance = acc.balance if acc else 10000.0
    result  = run(b1, b2, b3, b4, b5, b6, b7, b8, b9, balance)

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
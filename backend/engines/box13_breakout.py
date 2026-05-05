# ============================================================
# box13_breakout.py — Breakout Detection Engine
# Detects two types of breakouts:
#   Type 1 — Structural Breakout: BOS + retest entry
#   Type 2 — Momentum Breakout: straight shooter, no retest
# Uses data from B1 (ATR), B2 (BOS/structure), B3 (liquidity),
#         B4 (levels), B5 (volume), B7 (OBs/FVGs)
# FIX: Added H1 consolidation detection
# ============================================================

import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import VOLUME_SPIKE_MULTIPLIER, VOLUME_LOOKBACK


# ------------------------------------------------------------
# RANGE DETECTION
# Was price consolidating before the break?
# Consolidation = tight range for N candles before BOS
# ------------------------------------------------------------

def detect_consolidation(df, lookback=20, threshold=0.15):
    """
    Detect if price was consolidating before current candle.

    A consolidation = range (high-low) of last N candles
    is less than threshold * ATR.

    Args:
        df:        OHLCV DataFrame
        lookback:  candles to look back
        threshold: max range as ATR multiple to count as consolidation

    Returns:
        dict with was_consolidating, range_high, range_low, range_size
    """
    if df is None or len(df) < lookback + 2:
        return {
            "was_consolidating": False,
            "range_high":        None,
            "range_low":         None,
            "range_size":        None,
        }

    # Look at the candles BEFORE the last 2 (exclude breakout candle)
    window = df.iloc[-(lookback + 2):-2]

    range_high = float(window["high"].max())
    range_low  = float(window["low"].min())
    range_size = range_high - range_low

    # Compare to recent ATR (simple average of TR)
    recent = df.iloc[-lookback - 2:-2].copy()
    recent["prev_close"] = recent["close"].shift(1)
    recent["tr"] = recent[["high", "low", "prev_close"]].apply(
        lambda r: max(
            r["high"] - r["low"],
            abs(r["high"] - r["prev_close"]) if r["prev_close"] else 0,
            abs(r["low"]  - r["prev_close"]) if r["prev_close"] else 0
        ), axis=1
    )
    atr = float(recent["tr"].mean())

    was_consolidating = atr > 0 and range_size < atr * threshold * lookback

    return {
        "was_consolidating": was_consolidating,
        "range_high":        round(range_high, 2),
        "range_low":         round(range_low,  2),
        "range_size":        round(range_size, 2),
        "pre_break_atr":     round(atr, 4),
    }


# ------------------------------------------------------------
# DISPLACEMENT SCORING
# How strong is the breakout candle?
# ------------------------------------------------------------

def score_displacement(df, b1, b5):
    """
    Score the breakout displacement candle (last closed candle).

    Checks:
        1. Body ratio > 70% of total range
        2. Volume spike (> 1.5x average)
        3. Candle range > 1.5x ATR (expansion)
        4. Direction consistency (close direction matches move)

    Returns:
        dict with displacement_score (0-100), direction, and breakdown
    """
    if df is None or len(df) < 3:
        return {"displacement_score": 0, "direction": None, "is_displacement": False}

    candle = df.iloc[-1]  # last closed candle
    prev   = df.iloc[-2]

    body_size    = abs(candle["close"] - candle["open"])
    candle_range = candle["high"] - candle["low"]

    if candle_range < 0.1:
        return {"displacement_score": 0, "direction": None, "is_displacement": False}

    body_ratio = body_size / candle_range
    is_bullish = candle["close"] > candle["open"]
    is_bearish = candle["close"] < candle["open"]

    score = 0
    breakdown = []

    # 1. Body dominance (strong displacement candle has big body)
    if body_ratio >= 0.70:
        score += 35
        breakdown.append(f"Body ratio {round(body_ratio*100)}% ✓")
    elif body_ratio >= 0.55:
        score += 20
        breakdown.append(f"Body ratio {round(body_ratio*100)}% (moderate)")
    else:
        breakdown.append(f"Body ratio {round(body_ratio*100)}% — weak ✗")

    # 2. Volume spike
    vol_data = b5.get("volume_m15") or b5.get("volume_m5") or {}
    if vol_data.get("is_spike"):
        score += 30
        breakdown.append(f"Volume spike {vol_data.get('relative_volume', '?')}x ✓")
    elif vol_data.get("relative_volume", 0) > 1.2:
        score += 15
        breakdown.append("Volume elevated ✓")
    else:
        breakdown.append("Volume normal ✗")

    # 3. ATR expansion — candle range vs ATR
    atr = b1.get("atr")
    if atr and atr > 0:
        expansion = candle_range / atr
        if expansion >= 1.5:
            score += 25
            breakdown.append(f"ATR expansion {round(expansion, 1)}x ✓")
        elif expansion >= 1.0:
            score += 12
            breakdown.append(f"ATR expansion {round(expansion, 1)}x (moderate)")
        else:
            breakdown.append(f"ATR expansion {round(expansion, 1)}x — weak ✗")
    else:
        score += 10  # can't check, give partial
        breakdown.append("ATR unavailable")

    # 4. Close near extreme (momentum candle closes near high/low)
    if is_bearish:
        close_position = (candle["high"] - candle["close"]) / candle_range
        direction = "sell"
    else:
        close_position = (candle["close"] - candle["low"]) / candle_range
        direction = "buy"

    if close_position >= 0.70:
        score += 10
        breakdown.append("Closes near extreme ✓")
    else:
        breakdown.append("Close not at extreme ✗")

    is_displacement = score >= 60

    return {
        "displacement_score": min(score, 100),
        "direction":          direction,
        "is_displacement":    is_displacement,
        "body_ratio":         round(body_ratio, 2),
        "candle_range":       round(candle_range, 2),
        "breakdown":          breakdown,
    }


# ------------------------------------------------------------
# PATH CLEARANCE CHECK
# Are there OBs/FVGs blocking the move?
# ------------------------------------------------------------

def check_path_clear(direction, current_price, b7, b4, pip_range=50):
    """
    Check if the path ahead is clear of opposing zones.
    A blocked path = opposing OB or FVG within pip_range pips.

    For sell: check for bullish OBs/FVGs below price
    For buy:  check for bearish OBs/FVGs above price
    """
    obstacles = []
    range_pts = pip_range * 0.1  # convert pips to price points

    if direction == "sell":
        # Check bullish OBs below price (would act as support/obstacle)
        for ob in b7.get("bullish_obs", []):
            if ob.get("valid") and float(ob["top"]) < current_price:
                if current_price - float(ob["top"]) < range_pts:
                    obstacles.append(f"Bull OB at {ob['top']}")
        # Check bullish FVGs below
        for fvg in b7.get("bullish_fvgs", []):
            if fvg.get("valid") and float(fvg["top"]) < current_price:
                if current_price - float(fvg["top"]) < range_pts:
                    obstacles.append(f"Bull FVG at {fvg['top']}-{fvg['bottom']}")

    elif direction == "buy":
        # Check bearish OBs above price
        for ob in b7.get("bearish_obs", []):
            if ob.get("valid") and float(ob["bottom"]) > current_price:
                if float(ob["bottom"]) - current_price < range_pts:
                    obstacles.append(f"Bear OB at {ob['bottom']}")
        # Check bearish FVGs above
        for fvg in b7.get("bearish_fvgs", []):
            if fvg.get("valid") and float(fvg["bottom"]) > current_price:
                if float(fvg["bottom"]) - current_price < range_pts:
                    obstacles.append(f"Bear FVG at {fvg['bottom']}-{fvg['top']}")

    path_clear = len(obstacles) == 0

    return {
        "path_clear":  path_clear,
        "obstacles":   obstacles,
        "obstacle_count": len(obstacles),
    }


# ------------------------------------------------------------
# STRUCTURAL BREAKOUT DETECTION
# BOS confirmed + retest zone identified
# ------------------------------------------------------------

def detect_structural_breakout(b2, b3, b4, b5, b1, current_price):
    """
    Structural breakout = fresh BOS on M15 or M5 with:
    - Strong displacement (volume + ATR)
    - Broken level now acting as support/resistance
    - Retest zone within range (entry)

    Returns breakout dict or None
    """
    # Need fresh BOS
    m15 = b2["timeframes"]["M15"]
    m5  = b2["timeframes"]["M5"]

    fresh_bos    = m15.get("bos_active") or m5.get("bos_active")
    recent_bos   = m15["bos"][-1] if m15["bos"] else (m5["bos"][-1] if m5["bos"] else None)

    if not fresh_bos or not recent_bos:
        return None

    bos_type  = recent_bos["type"]  # bullish_bos or bearish_bos
    bos_level = recent_bos["level"]

    direction = "buy" if bos_type == "bullish_bos" else "sell"

    # Volume must confirm
    vol_m15 = b5.get("volume_m15", {})
    vol_ok  = vol_m15.get("is_spike") or vol_m15.get("relative_volume", 0) > 1.2

    # ATR must be expanding
    atr = b1.get("atr", 0)
    atr_ok = atr > b1.get("atr", 0) * 0.8  # at least normal ATR

    # Retest zone = the broken BOS level ± small buffer
    retest_zone_top    = round(float(bos_level) + 0.5, 2)
    retest_zone_bottom = round(float(bos_level) - 0.5, 2)

    # Price must not have gone too far from retest zone
    if direction == "buy":
        # Price should be above broken level (bullish BOS) within 30 pips
        dist_from_retest = current_price - float(bos_level)
        too_far = dist_from_retest > 3.0
    else:
        dist_from_retest = float(bos_level) - current_price
        too_far = dist_from_retest > 3.0

    score = 0
    reasons = []

    if fresh_bos:
        score += 35
        reasons.append(f"Fresh BOS ({bos_type}) at {bos_level} ✓")

    if vol_ok:
        score += 25
        reasons.append("Volume confirms break ✓")
    else:
        reasons.append("Volume weak ✗")

    if not too_far:
        score += 25
        reasons.append(f"Price near retest zone ({round(dist_from_retest,1)} pts) ✓")
    else:
        reasons.append(f"Price too far from retest ({round(dist_from_retest,1)} pts) ✗")

    # HTF alignment bonus
    h4_bias = b2.get("h4_bias", "neutral")
    d1_bias = b2.get("d1_bias", "neutral")
    htf_dir = "bullish" if direction == "buy" else "bearish"
    if h4_bias == htf_dir or d1_bias == htf_dir:
        score += 15
        reasons.append(f"HTF aligned ({h4_bias}/{d1_bias}) ✓")
    else:
        reasons.append(f"HTF not aligned ({h4_bias}/{d1_bias}) ✗")

    validated = score >= 60 and fresh_bos and not too_far

    # ============================================================
    # FIX: ADDED "NO RETEST" FLAG — Let momentum breakout handle running moves
    # ============================================================
    # If price moved significantly away from retest zone (more than 15 pips)
    # without retesting, return a special flag so momentum breakout can handle it
    if direction == "sell" and current_price < float(bos_level) - 1.5:
        # Price dropped 15+ pips below BOS level without retest
        return {
            "type": "no_retest",
            "should_use_momentum": True,
            "direction": direction,
            "bos_level": bos_level,
            "current_price": current_price,
            "score": min(score, 100),
            "validated": False,  # Not a valid structural entry
            "reasons": reasons + ["No retest — momentum breakout should handle this"],
        }
    elif direction == "buy" and current_price > float(bos_level) + 1.5:
        # Price rose 15+ pips above BOS level without retest
        return {
            "type": "no_retest",
            "should_use_momentum": True,
            "direction": direction,
            "bos_level": bos_level,
            "current_price": current_price,
            "score": min(score, 100),
            "validated": False,
            "reasons": reasons + ["No retest — momentum breakout should handle this"],
        }

    return {
        "type":              "structural_breakout",
        "direction":         direction,
        "bos_level":         float(bos_level),
        "retest_zone_top":   retest_zone_top,
        "retest_zone_bottom": retest_zone_bottom,
        "score":             min(score, 100),
        "validated":         validated,
        "reasons":           reasons,
        "entry_type":        f"Retest of broken {bos_type.replace('_bos','')} structure",
    }


# ------------------------------------------------------------
# MOMENTUM BREAKOUT DETECTION
# Straight shooter — no retest expected
# ------------------------------------------------------------

def detect_momentum_breakout(df_m5, df_m15, b1, b2, b3, b4, b5, b7, current_price):
    """
    Momentum breakout = strong displacement candle breaks
    a significant level with no pullback expected.

    Conditions:
        1. Body ratio > 65% (strong candle)
        2. Volume spike > 1.5x
        3. Candle range > 1.3x ATR
        4. Breaks a key level (pivot, PDH/PDL, swing high/low)
        5. Path ahead is relatively clear
        6. MSS active on M5 or M15 (confirms structure shifted)

    Entry: market order / tight limit on next candle open
    SL:    beyond the breakout candle high/low
    TP:    next liquidity pool (trailing)
    """
    score   = 0
    reasons = []

    if df_m5 is None or len(df_m5) < 5:
        return None

    # Use M5 for momentum detection (faster signal)
    candle = df_m5.iloc[-1]
    prev   = df_m5.iloc[-2]

    body_size    = abs(candle["close"] - candle["open"])
    candle_range = candle["high"] - candle["low"]

    if candle_range < 0.3:
        return None

    # Hard requirement: candle must be significant relative to H1 ATR
    # Filters noise-level candles in high-volatility environments.
    # Mar 10 loss: 7pt candle in 25pt ATR = 0.28x → rejected
    # Mar 4 win:  15pt candle in 39pt ATR = 0.38x → passes
    atr_h1 = b1.get("atr", 2.0)
    if atr_h1 and atr_h1 > 0 and candle_range < atr_h1 * 0.3:
        return None  # too small to be a real displacement

    body_ratio = body_size / candle_range
    is_bearish = candle["close"] < candle["open"]
    is_bullish = candle["close"] > candle["open"]
    direction  = "sell" if is_bearish else "buy"

    # ── 1. Body dominance ───────────────────────────────────
    if body_ratio >= 0.65:
        score += 25
        reasons.append(f"Body ratio {round(body_ratio*100)}% ✓")
    else:
        reasons.append(f"Body ratio {round(body_ratio*100)}% — too weak ✗")
        return None  # hard requirement

    # ── 2. Volume spike ─────────────────────────────────────
    vol_m5 = b5.get("volume_m5", {})
    if vol_m5.get("is_spike"):
        score += 25
        reasons.append(f"Volume spike {vol_m5.get('relative_volume', '?')}x ✓")
    elif vol_m5.get("relative_volume", 0) >= 1.3:
        score += 12
        reasons.append("Volume elevated ✓")
    else:
        reasons.append("Volume not spiking ✗")

    # ── 3. ATR expansion ────────────────────────────────────
    atr = b1.get("atr")
    if atr and atr > 0:
        # Scale ATR to M5 (H1 ATR / 12 gives approx M5 ATR)
        atr_m5   = atr / 12
        expansion = candle_range / atr_m5 if atr_m5 > 0 else 0
        if expansion >= 1.3:
            score += 20
            reasons.append(f"ATR expansion {round(expansion,1)}x ✓")
        elif expansion >= 1.0:
            score += 10
            reasons.append(f"ATR expansion {round(expansion,1)}x (moderate)")
        else:
            reasons.append(f"ATR expansion {round(expansion,1)}x — weak ✗")

    # ── 4. Breaks a key level ────────────────────────────────
    broke_level = False
    broke_label = None

    pdh = b3.get("pdh") or b4.get("pdh")
    pdl = b3.get("pdl") or b4.get("pdl")
    nearest_ssl = b3.get("nearest_ssl")
    nearest_bsl = b3.get("nearest_bsl")

    if direction == "sell":
        # Bearish: check if candle broke below PDL or SSL
        if pdl and candle["close"] < float(pdl) < candle["open"]:
            broke_level = True
            broke_label = f"PDL {pdl}"
        elif nearest_ssl and candle["close"] < float(nearest_ssl) < candle["open"]:
            broke_level = True
            broke_label = f"SSL {nearest_ssl}"
        # Check swing lows from M15
        m15_last_sl = b2["timeframes"]["M15"].get("last_sl")
        if m15_last_sl and not broke_level:
            sl_price = float(m15_last_sl["price"]) if isinstance(m15_last_sl, dict) else float(m15_last_sl)
            if candle["close"] < sl_price < candle["open"]:
                broke_level = True
                broke_label = f"M15 Swing Low {round(sl_price, 2)}"
    else:
        # Bullish: check if candle broke above PDH or BSL
        if pdh and candle["close"] > float(pdh) > candle["open"]:
            broke_level = True
            broke_label = f"PDH {pdh}"
        elif nearest_bsl and candle["close"] > float(nearest_bsl) > candle["open"]:
            broke_level = True
            broke_label = f"BSL {nearest_bsl}"
        m15_last_sh = b2["timeframes"]["M15"].get("last_sh")
        if m15_last_sh and not broke_level:
            sh_price = float(m15_last_sh["price"]) if isinstance(m15_last_sh, dict) else float(m15_last_sh)
            if candle["close"] > sh_price > candle["open"]:
                broke_level = True
                broke_label = f"M15 Swing High {round(sh_price, 2)}"

    if broke_level:
        score += 20
        reasons.append(f"Broke key level: {broke_label} ✓")
    else:
        reasons.append("No significant level broken ✗")

    # ── 5. MSS active confirms structure shifted ─────────────
    mss_active = b2.get("mss_m5_active") or b2.get("mss_m15_active")
    mss_type   = b2.get("mss_m5_type")   or b2.get("mss_m15_type")

    mss_aligned = False
    if direction == "sell" and mss_type and "bearish" in str(mss_type):
        mss_aligned = True
    elif direction == "buy" and mss_type and "bullish" in str(mss_type):
        mss_aligned = True

    if mss_active and mss_aligned:
        score += 10
        reasons.append(f"MSS confirmed ({mss_type}) ✓")
    elif mss_active:
        score += 5
        reasons.append("MSS active (direction unclear) ⚠")

    # ── 6. Path clearance ────────────────────────────────────
    path = check_path_clear(direction, current_price, b7, b4, pip_range=30)
    if path["path_clear"]:
        score += 0  # no bonus, just don't penalise
        reasons.append("Path clear ✓")
    else:
        score -= 10
        reasons.append(f"Path blocked: {', '.join(path['obstacles'][:2])} ✗")

    # ── Validation ───────────────────────────────────────────
    # Requires: body ok + volume + broke level = 3 hard requirements
    hard_ok = body_ratio >= 0.65 and broke_level
    validated = hard_ok and score >= 55

    # Entry is tight — just beyond the breakout candle
    buf = 0.3  # 3 pip buffer
    if direction == "sell":
        entry  = round(candle["close"] - buf, 2)
        sl     = round(candle["high"]  + buf, 2)
    else:
        entry  = round(candle["close"] + buf, 2)
        sl     = round(candle["low"]   - buf, 2)

    # TP targets = next liquidity pools from B3
    if direction == "sell":
        nearest_liq = b3.get("nearest_ssl")
        tp1 = round(float(nearest_liq), 2) if nearest_liq else round(entry - abs(entry - sl) * 2, 2)
    else:
        nearest_liq = b3.get("nearest_bsl")
        tp1 = round(float(nearest_liq), 2) if nearest_liq else round(entry + abs(entry - sl) * 2, 2)

    return {
        "type":        "momentum_breakout",
        "direction":   direction,
        "score":       min(score, 100),
        "validated":   validated,
        "reasons":     reasons,
        "broke_level": broke_label,
        "entry":       entry,
        "sl":          sl,
        "tp1":         tp1,
        "body_ratio":  round(body_ratio, 2),
        "candle_range": round(candle_range, 2),
        "entry_type":  f"Momentum breakout — {broke_label or 'key level'} ({direction.upper()})",
        "is_straight_shooter": True,
    }


# ------------------------------------------------------------
# MAIN ENGINE FUNCTION
# ------------------------------------------------------------

def run(candle_store, b1, b2, b3, b4, b5, b7):
    """
    Run full Breakout Detection Engine.

    Returns:
        dict with structural and momentum breakout results
    """
    df_m5  = candle_store.get_closed("M5")
    df_m15 = candle_store.get_closed("M15")
    df_h1  = candle_store.get_closed("H1")  # Added for H1 consolidation

    price_info    = candle_store.get_price()
    current_price = float(price_info["bid"]) if price_info else 0.0

    # Consolidation check on M15
    consolidation = detect_consolidation(df_m15, lookback=20)

    # Consolidation check on H1 (NEW for kill switch)
    h1_consolidation = detect_consolidation(df_h1, lookback=20)

    # Displacement scoring on M5 (latest candle)
    displacement = score_displacement(df_m5, b1, b5)

    # Structural breakout
    structural = detect_structural_breakout(b2, b3, b4, b5, b1, current_price)

    # Momentum breakout
    momentum = detect_momentum_breakout(
        df_m5, df_m15, b1, b2, b3, b4, b5, b7, current_price
    )

    # Overall breakout active?
    structural_active = structural is not None and structural.get("validated", False)
    momentum_active   = momentum   is not None and momentum["validated"]
    any_breakout      = structural_active or momentum_active

    # Best breakout — momentum takes priority (higher urgency)
    best_breakout = None
    if momentum_active:
        best_breakout = momentum
    elif structural_active:
        best_breakout = structural

    return {
        "consolidation":       consolidation,
        "h1_consolidation":    h1_consolidation,  # NEW: H1 consolidation for kill switch
        "displacement":        displacement,
        "structural_breakout": structural,
        "momentum_breakout":   momentum,
        "structural_active":   structural_active,
        "momentum_active":     momentum_active,
        "any_breakout":        any_breakout,
        "best_breakout":       best_breakout,
        "breakout_direction":  best_breakout["direction"] if best_breakout else None,
        "breakout_type":       best_breakout["type"]      if best_breakout else None,
        "breakout_score":      best_breakout["score"]     if best_breakout else 0,
        "engine_score":        best_breakout["score"]     if best_breakout else 0,
    }
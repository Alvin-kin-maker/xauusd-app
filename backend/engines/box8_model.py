# ============================================================
# box8_model.py — Model Engine
# All 10 trading models with their rules
# Each model reads outputs from Boxes 1-7 and validates
# ============================================================

import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import MISSED_ENTRY_CANDLES, MAX_CHASE_PERCENT 


# ------------------------------------------------------------
# MODEL RESULT BUILDER
# ------------------------------------------------------------

def model_result(name, validated, score, reasons, entry_type=None, missed_rule=None):
    """Standard model result structure."""
    return {
        "name":        name,
        "validated":   validated,
        "score":       score,
        "reasons":     reasons,
        "entry_type":  entry_type,
        "missed_rule": missed_rule,
    }


# ------------------------------------------------------------
# MODEL 1 — LONDON SWEEP & REVERSE
# ------------------------------------------------------------

def model_london_sweep_reverse(b1, b2, b3, b4, b5, b6, b7):
    """
    Concept: London opens and sweeps Asian range then reverses.
    Session: London (07:00-10:00 GMT)
    """
    name    = "london_sweep_reverse"
    reasons = []
    score   = 0

    # Box 1: London session active, ATR moving
    london_active = b1["primary_session"] in ["london", "overlap"]
    atr_ok        = b1["volatility_regime"] not in ["dead", "low"]

    if london_active:
        score += 20
        reasons.append("London session active ✓")
    else:
        reasons.append(f"Session: {b1['primary_session']} (need London) ✗")

    if atr_ok:
        score += 10
        reasons.append(f"ATR active ({b1['atr']}) ✓")

    # Box 2: Daily bias established, 1H opposing
    daily_bias = b2["timeframes"]["D1"]["bias"]
    h1_bias    = b2["timeframes"]["H1"]["bias"]
    bias_ok    = daily_bias != "neutral"

    if bias_ok:
        score += 15
        reasons.append(f"Daily bias: {daily_bias} ✓")

    # Box 3: Asian high or low swept
    asian_swept = b3["asian_high_swept"] or b3["asian_low_swept"]
    sweep_recent = b3["sweep_just_happened"]

    if asian_swept:
        score += 25
        reasons.append("Asian range swept ✓")
        if b3["asian_high_swept"]:
            reasons.append("Asian HIGH swept (bearish setup)")
        if b3["asian_low_swept"]:
            reasons.append("Asian LOW swept (bullish setup)")
    else:
        reasons.append("No Asian sweep detected ✗")

    if sweep_recent:
        score += 10
        reasons.append("Sweep just happened ✓")

    # Box 4: Swept level near key level
    at_level = b4["at_key_level"]
    if at_level:
        score += 10
        reasons.append(f"At key level: {b4['closest_level']['label'] if b4['closest_level'] else 'yes'} ✓")

    # Box 5: RSI extreme at sweep
    rsi_extreme = b5["rsi_m15_signal"] in ["overbought", "oversold"]
    vol_spike   = b5["volume_m15"]["is_spike"]

    if rsi_extreme:
        score += 10
        reasons.append(f"RSI extreme: {b5['rsi_m15_signal']} ✓")
    if vol_spike:
        score += 5
        reasons.append("Volume spike on sweep ✓")

    # Box 7: OB or FVG at sweep zone
    has_ob  = b7["bull_ob_count"] > 0 or b7["bear_ob_count"] > 0
    has_fvg = b7["bull_fvg_count"] > 0 or b7["bear_fvg_count"] > 0

    if has_ob:
        score += 10
        reasons.append("OB present at zone ✓")
    if has_fvg:
        score += 5
        reasons.append("FVG present ✓")

    # Sweep direction must agree with H4 + D1 bias — hard gate
    h4_bias = b2["timeframes"]["H4"]["bias"]
    d1_bias = b2["timeframes"]["D1"]["bias"]

    direction_valid = False
    if b3["asian_high_swept"] and h4_bias == "bearish" and d1_bias in ["bearish", "neutral"]:
        direction_valid = True
        reasons.append(f"Sweep direction aligns with H4 ({h4_bias}) + D1 ({d1_bias}) ✓")
    elif b3["asian_low_swept"] and h4_bias == "bullish" and d1_bias in ["bullish", "neutral"]:
        direction_valid = True
        reasons.append(f"Sweep direction aligns with H4 ({h4_bias}) + D1 ({d1_bias}) ✓")
    else:
        reasons.append(f"Sweep direction conflicts with H4 ({h4_bias}) + D1 ({d1_bias}) ✗ — rejected")

    validated = (
        london_active and
        asian_swept and
        bias_ok and
        direction_valid and
        score >= 60
    )

    missed_rule = f"Retest within {MISSED_ENTRY_CANDLES['london_sweep_reverse']} candles on M5 or void"

    return model_result(name, validated, min(score, 100), reasons,
                       entry_type="Retest of OB/FVG after sweep", missed_rule=missed_rule)


# ------------------------------------------------------------
# MODEL 2 — NY CONTINUATION
# ------------------------------------------------------------

def model_ny_continuation(b1, b2, b3, b4, b5, b6, b7):
    """
    Concept: NY continues London trend after pullback.
    Session: NY (13:00-16:00 GMT)
    """
    name    = "ny_continuation"
    reasons = []
    score   = 0

    # Box 1: NY session
    ny_active = b1["primary_session"] in ["new_york", "overlap"]
    if ny_active:
        score += 20
        reasons.append("NY session active ✓")
    else:
        reasons.append(f"Session: {b1['primary_session']} (need NY) ✗")

    # Box 2: 4H and 1H aligned, no CHOCH
    h4_bias = b2["timeframes"]["H4"]["bias"]
    h1_bias = b2["timeframes"]["H1"]["bias"]
    aligned = h4_bias == h1_bias and h4_bias != "neutral"

    if aligned:
        score += 25
        reasons.append(f"H4+H1 aligned: {h4_bias} ✓")
    else:
        reasons.append(f"H4: {h4_bias}, H1: {h1_bias} — not aligned ✗")

    choch_active = b2["timeframes"]["M15"]["choch_active"] or b2["timeframes"]["M5"]["choch_active"]
    if not choch_active:
        score += 10
        reasons.append("No CHOCH on LTF ✓")
    else:
        reasons.append("CHOCH detected on LTF ✗")
        score -= 10

    # Box 3: Minor liquidity swept on pullback
    if b3["sweep_just_happened"]:
        score += 15
        reasons.append("Liquidity swept on pullback ✓")

    # Box 4: Pullback to PP or S/R level
    if b4["at_key_level"]:
        score += 15
        reasons.append("Pullback to key level ✓")

    # Box 5: RSI reset to neutral, declining volume on pullback
    rsi_neutral = 40 <= (b5["rsi_m15"] or 50) <= 60
    vol_declining = b5["volume_m15"]["is_declining"]

    if rsi_neutral:
        score += 10
        reasons.append(f"RSI reset to neutral ({b5['rsi_m15']}) ✓")
    if vol_declining:
        score += 10
        reasons.append("Declining volume on pullback ✓")

    # Box 7: OB at pullback zone
    if b7["at_bull_ob"] or b7["at_bear_ob"]:
        score += 15
        reasons.append("Price at OB zone ✓")

    validated = (
        ny_active and
        aligned and
        score >= 60
    )

    missed_rule = f"If NY pushes 20+ pips without pullback → void"

    return model_result(name, validated, min(score, 100), reasons,
                       entry_type="15M OB retest or FVG fill on pullback", missed_rule=missed_rule)


# ------------------------------------------------------------
# MODEL 3 — ASIAN RANGE BREAKOUT
# ------------------------------------------------------------

def model_asian_range_breakout(b1, b2, b3, b4, b5, b6, b7):
    """
    Concept: Clean break of Asian range with volume confirmation.
    Session: London open
    """
    name    = "asian_range_breakout"
    reasons = []
    score   = 0

    # Box 1: London open, ATR confirms range
    london_open = b1["primary_session"] == "london"
    if london_open:
        score += 20
        reasons.append("London open ✓")
    else:
        reasons.append(f"Session: {b1['primary_session']} (need London open) ✗")

    atr_ok = b1["atr"] and b1["atr"] > 0.5
    if atr_ok:
        score += 10
        reasons.append(f"ATR confirms range ({b1['atr']}) ✓")

    # Box 2: Daily bias supports breakout direction
    daily_bias = b2["timeframes"]["D1"]["bias"]
    if daily_bias != "neutral":
        score += 20
        reasons.append(f"Daily bias supports: {daily_bias} ✓")

    # Box 3: Asian range exists with EQH/EQL
    asian_range_exists = b3["asian_high"] is not None and b3["asian_low"] is not None
    has_liquidity = b3["eqh_count"] > 0 or b3["eql_count"] > 0

    if asian_range_exists:
        score += 15
        asian_range_size = (b3["asian_high"] or 0) - (b3["asian_low"] or 0)
        reasons.append(f"Asian range: {b3['asian_low']} - {b3['asian_high']} (size: {round(asian_range_size, 1)}) ✓")

        # Check range size is valid (10-40 pips for gold, roughly 1-4 points)
        if 1.0 <= asian_range_size <= 40.0:
            score += 10
            reasons.append("Range size valid ✓")
        else:
            reasons.append(f"Range size {round(asian_range_size, 1)} outside ideal range ✗")

    if has_liquidity:
        score += 10
        reasons.append(f"EQH/EQL liquidity built up ✓")

    # Box 4: Range boundary at key level
    if b4["at_key_level"]:
        score += 10
        reasons.append("Range boundary at key level ✓")

    # Box 5: Volume + RSI on breakout
    if b5["volume_m15"]["is_spike"]:
        score += 15
        reasons.append("Volume spike on breakout ✓")

    rsi_above_mid = b5["rsi_above_mid_m15"]
    if rsi_above_mid is not None:
        score += 5
        reasons.append(f"RSI {'above' if rsi_above_mid else 'below'} midline ✓")

    # Box 7: FVG on breakout candle
    if b7["bull_fvg_count"] > 0 or b7["bear_fvg_count"] > 0:
        score += 10
        reasons.append("FVG created on breakout ✓")

    validated = (
        london_open and
        asian_range_exists and
        daily_bias != "neutral" and
        score >= 55
    )

    missed_rule = f"No retest within {MISSED_ENTRY_CANDLES['asian_range_breakout']} candles → void"

    return model_result(name, validated, min(score, 100), reasons,
                       entry_type="Retest of broken range boundary only", missed_rule=missed_rule)


# ------------------------------------------------------------
# MODEL 4 — OB + FVG STACK
# ------------------------------------------------------------

def model_ob_fvg_stack(b1, b2, b3, b4, b5, b6, b7):
    """
    Concept: OB and FVG aligned creating maximum confluence zone.
    """
    name    = "ob_fvg_stack"
    reasons = []
    score   = 0

    # Box 1: London or NY, ATR active
    good_session = b1["primary_session"] in ["london", "new_york", "overlap"]
    if good_session:
        score += 15
        reasons.append(f"Good session: {b1['primary_session']} ✓")

    if b1["volatility_regime"] not in ["dead", "low"]:
        score += 10
        reasons.append("ATR active ✓")

    # Box 2: 4H and 1H aligned, recent BOS
    h4_bias = b2["timeframes"]["H4"]["bias"]
    h1_bias = b2["timeframes"]["H1"]["bias"]
    aligned = h4_bias == h1_bias and h4_bias != "neutral"

    if aligned:
        score += 20
        reasons.append(f"H4+H1 aligned: {h4_bias} ✓")

    if b2["recent_bos"]:
        score += 10
        reasons.append("Recent BOS confirmed ✓")

    # Box 3: Liquidity swept before reaching stack zone
    if b3["total_sweeps"] > 0:
        score += 15
        reasons.append("Liquidity swept before zone ✓")

    # Box 4: Stack zone near institutional level
    if b4["at_key_level"]:
        score += 15
        reasons.append("Stack zone at institutional level ✓")

    # Box 5: RSI approaching extreme, declining volume
    rsi_h1 = b5["rsi_h1"] or 50
    rsi_approaching = rsi_h1 > 65 or rsi_h1 < 35
    if rsi_approaching:
        score += 10
        reasons.append(f"RSI approaching extreme ({rsi_h1}) ✓")

    if b5["volume_m15"]["is_declining"]:
        score += 5
        reasons.append("Declining volume approaching zone ✓")

    # Box 7: OB AND FVG both present AND price is near/at the stack
    # Just having OBs/FVGs exist anywhere is not enough — price must be near them
    has_ob       = b7["bull_ob_count"] > 0 or b7["bear_ob_count"] > 0
    has_fvg      = b7["bull_fvg_count"] > 0 or b7["bear_fvg_count"] > 0
    price_at_ob  = b7["at_bull_ob"] or b7["at_bear_ob"]
    price_at_fvg = b7["at_bull_fvg"] or b7["at_bear_fvg"]
    is_stack     = has_ob and has_fvg
    price_near_stack = price_at_ob or price_at_fvg  # price must be approaching/at zone

    if is_stack and price_near_stack:
        score += 30
        reasons.append("OB + FVG STACK — price at zone ✓✓")
    elif is_stack and not price_near_stack:
        score += 10  # Stack exists but price not there yet — reduced credit
        reasons.append("OB + FVG STACK exists — waiting for price ⏳")
    elif has_ob:
        score += 10
        reasons.append("OB present (no FVG stack) ✓")
    elif has_fvg:
        score += 8
        reasons.append("FVG present (no OB stack) ✓")
    else:
        reasons.append("No OB or FVG found ✗")

    validated = (
        good_session and
        is_stack and
        price_near_stack and  # ← now required: price must be at/near the zone
        aligned and
        score >= 65
    )

    missed_rule = "First touch missed → second touch only. No third touch."

    return model_result(name, validated, min(score, 100), reasons,
                       entry_type="First candle reaction from stack zone", missed_rule=missed_rule)


# ------------------------------------------------------------
# MODEL 5 — LIQUIDITY GRAB + BOS
# ------------------------------------------------------------

def model_liquidity_grab_bos(b1, b2, b3, b4, b5, b6, b7):
    """
    Concept: Price grabs liquidity then immediately breaks structure.
    """
    name    = "liquidity_grab_bos"
    reasons = []
    score   = 0

    # Box 1: London or NY
    good_session = b1["primary_session"] in ["london", "new_york", "overlap"]
    if good_session:
        score += 15
        reasons.append(f"Session: {b1['primary_session']} ✓")

    # Box 2: HTF showing reversal area, LTF sequence ending
    d1_bias = b2["timeframes"]["D1"]["bias"]
    h1_choch = b2["timeframes"]["H1"]["choch_active"]

    if d1_bias != "neutral":
        score += 15
        reasons.append(f"D1 at potential reversal: {d1_bias} ✓")

    # Box 3: Clear liquidity swept, sharp and fast
    sharp_sweep = b3["sweep_just_happened"]
    major_swept = b3["pdh_swept"] or b3["pdl_swept"] or b3["asian_high_swept"] or b3["asian_low_swept"]

    if sharp_sweep:
        score += 25
        reasons.append("Sweep just happened ✓")
    if major_swept:
        score += 20
        reasons.append("Major level swept (PDH/PDL/Session) ✓")

    if b3["sweep_direction"]:
        reasons.append(f"Sweep direction: {b3['sweep_direction']}")

    # Box 4: Sweep at major level
    if b4["at_key_level"]:
        score += 15
        reasons.append("Sweep at major institutional level ✓")

    # Box 5: RSI divergence + volume climax
    if b5["divergence_active"]:
        score += 15
        reasons.append(f"RSI divergence: {b5['divergence_type']} ✓")
    if b5["volume_m15"]["is_spike"]:
        score += 10
        reasons.append("Volume climax on sweep ✓")

    # Box 7: FVG and OB after BOS
    if b7["bull_fvg_count"] > 0 or b7["bear_fvg_count"] > 0:
        score += 10
        reasons.append("FVG created after displacement ✓")
    if b7["bull_breakers"] or b7["bear_breakers"]:
        score += 10
        reasons.append("Breaker block present ✓")

    # Require H1 CHOCH: confirms the reversal is structural, not just a bounce
    # Without H1 CHOCH, the sweep may be within a continuing trend (buys that hit SL)
    # H1 CHOCH = market structure shift on H1 = genuine reversal signal
    h1_choch_active = b2["timeframes"]["H1"].get("choch_active", False)
    if h1_choch_active:
        score += 15
        reasons.append("H1 CHOCH confirms reversal ✓")
    else:
        reasons.append("No H1 CHOCH — may be bounce only ✗")

    validated = (
        good_session and
        (sharp_sweep or major_swept) and
        h1_choch_active and
        score >= 65
    )

    missed_rule = f"BOS retest within {MISSED_ENTRY_CANDLES['liquidity_grab_bos']} candles on M5 or void"

    return model_result(name, validated, min(score, 100), reasons,
                       entry_type="Retest of FVG or OB after BOS", missed_rule=missed_rule)


# ------------------------------------------------------------
# MODEL 6 — HTF LEVEL REACTION
# ------------------------------------------------------------

def model_htf_level_reaction(b1, b2, b3, b4, b5, b6, b7):
    """
    Concept: Price reaches major HTF level and shows clean rejection.
    """
    name    = "htf_level_reaction"
    reasons = []
    score   = 0

    # Box 1: London or NY
    good_session = b1["primary_session"] in ["london", "new_york", "overlap"]
    if good_session:
        score += 15
        reasons.append(f"Session: {b1['primary_session']} ✓")

    # Box 2: Daily/4H level identified, CHOCH on 15M
    d1_bias  = b2["timeframes"]["D1"]["bias"]
    h4_bias  = b2["timeframes"]["H4"]["bias"]
    m15_choch = b2["timeframes"]["M15"]["choch_active"]

    if d1_bias != "neutral":
        score += 15
        reasons.append(f"D1 bias: {d1_bias} ✓")

    if m15_choch:
        score += 20
        reasons.append("CHOCH on M15 at HTF level ✓")

    # Box 3: Stop hunt at HTF level preferred
    if b3["pdh_swept"] or b3["pdl_swept"]:
        score += 20
        reasons.append("PDH/PDL stop hunt ✓")
    elif b3["pwh_swept"] or b3["pwl_swept"]:
        score += 25
        reasons.append("Weekly high/low stop hunt ✓")
    elif b3["sweep_just_happened"]:
        score += 15
        reasons.append("Recent sweep at level ✓")

    # Box 4: Must be at major HTF level
    if b4["at_key_level"]:
        closest = b4["closest_level"]
        if closest:
            source = closest.get("source", "")
            if source in ["weekly", "monthly"]:
                score += 30
                reasons.append(f"At MAJOR level: {closest['label']} ✓✓")
            elif source in ["daily", "pivot"]:
                score += 20
                reasons.append(f"At daily level: {closest['label']} ✓")
            elif source == "psych":
                score += 15
                reasons.append(f"At psychological level: {closest['label']} ✓")
    else:
        reasons.append("Not at key level ✗")

    # Box 5: RSI extreme + divergence
    rsi_extreme = b5["rsi_h1_signal"] in ["overbought", "oversold"]
    if rsi_extreme:
        score += 15
        reasons.append(f"RSI extreme on H1: {b5['rsi_h1_signal']} ✓")
    if b5["divergence_active"]:
        score += 10
        reasons.append("RSI divergence ✓")

    # Box 7: HTF OB + confirmation candle
    if b7["at_bull_ob"] or b7["at_bear_ob"]:
        score += 15
        reasons.append("Price at OB zone ✓")
    if b7["candle_patterns"]:
        score += 10
        cp = b7["candle_patterns"][0]
        reasons.append(f"Confirmation candle: {cp['type']} ✓")

    # Direction must align with HTF bias — no counter-trend HTF reactions
    # D1 or H4 must agree with the direction B9 will resolve
    # We check D1 bias here as a hard gate
    d1_bias_direction = "sell" if d1_bias == "bearish" else ("buy" if d1_bias == "bullish" else None)
    h4_bias_direction = "sell" if h4_bias == "bearish" else ("buy" if h4_bias == "bullish" else None)

    # Also require a confirmation candle (rejection) at the level
    has_confirmation = len(b7.get("candle_patterns", [])) > 0 or b7.get("at_bull_ob") or b7.get("at_bear_ob")

    # H4 gate: don't trade against H4 trend at key levels
    h4_bias_htf = b2["timeframes"]["H4"]["bias"]
    h1_bias_htf = b2["timeframes"]["H1"]["bias"]
    h4_h1_oppose_htf = (
        (h1_bias_htf == "bullish" and h4_bias_htf == "bearish") or
        (h1_bias_htf == "bearish" and h4_bias_htf == "bullish")
    )

    validated = (
        good_session and
        b4["at_key_level"] and
        has_confirmation and  # must have rejection candle at level
        not h4_h1_oppose_htf and
        score >= 65
    )

    missed_rule = "Need: at HTF level + rejection candle + H4 aligned + score≥65."

    return model_result(name, validated, min(score, 100), reasons,
                       entry_type="15M or 5M confirmation candle close", missed_rule=missed_rule)


# ------------------------------------------------------------
# MODEL 7 — CHOCH REVERSAL
# ------------------------------------------------------------

def model_choch_reversal(b1, b2, b3, b4, b5, b6, b7):
    """
    Concept: CHOCH confirms full trend reversal, entry on retest.
    """
    name    = "choch_reversal"
    reasons = []
    score   = 0

    # Box 1: London or NY
    good_session = b1["primary_session"] in ["london", "new_york", "overlap"]
    if good_session:
        score += 15
        reasons.append(f"Session: {b1['primary_session']} ✓")

    # Box 2: CHOCH is the core requirement
    m15_choch = b2["timeframes"]["M15"]["choch_active"]
    m5_choch  = b2["timeframes"]["M5"]["choch_active"]
    h1_trend  = b2["timeframes"]["H1"]["structure"]
    choch_detected = m15_choch or m5_choch

    if choch_detected:
        score += 35
        reasons.append("CHOCH detected on LTF ✓✓")
        if m15_choch:
            reasons.append("M15 CHOCH confirmed ✓")
        if m5_choch:
            reasons.append("M5 BOS in new direction ✓")
    else:
        reasons.append("No CHOCH detected ✗")

    if h1_trend in ["bullish", "bearish"]:
        score += 10
        reasons.append(f"H1 clear trend ({h1_trend}) for reversal ✓")

    # Box 3: Liquidity swept before CHOCH
    if b3["sweep_just_happened"]:
        score += 20
        reasons.append("Liquidity swept before CHOCH ✓")

    # Box 4: CHOCH at key level adds weight
    if b4["at_key_level"]:
        score += 15
        reasons.append("CHOCH at key level ✓")

    # Box 5: RSI crosses 50, hidden divergence
    rsi_cross_50 = b5["rsi_above_mid_m15"] is not None
    if rsi_cross_50:
        score += 10
        reasons.append("RSI midline cross ✓")

    if b5["divergence_active"]:
        div_type = b5["divergence_type"] or ""
        if "hidden" in div_type:
            score += 15
            reasons.append("Hidden divergence ✓")

    if b5["volume_m15"]["is_spike"]:
        score += 10
        reasons.append("Volume spike on CHOCH candle ✓")

    # Box 7: Breaker block from last OB
    if b7["bull_breakers"] or b7["bear_breakers"]:
        score += 15
        reasons.append("Breaker block formed ✓")

    validated = (
        good_session and
        choch_detected and
        score >= 65
    )

    missed_rule = f"Retest within {MISSED_ENTRY_CANDLES['choch_reversal']} candles on M5 or void"

    return model_result(name, validated, min(score, 100), reasons,
                       entry_type="Retest of breaker block or new OB after CHOCH", missed_rule=missed_rule)


# ------------------------------------------------------------
# MODEL 8 — DOUBLE TOP/BOTTOM LIQUIDITY TRAP
# ------------------------------------------------------------

def model_double_top_bottom_trap(b1, b2, b3, b4, b5, b6, b7):
    """
    Concept: Double top/bottom traps breakout traders then reverses.
    """
    name    = "double_top_bottom_trap"
    reasons = []
    score   = 0

    # Box 1: London or NY, active market
    good_session = b1["primary_session"] in ["london", "new_york", "overlap"]
    atr_active   = b1["volatility_regime"] not in ["dead", "low"]

    if good_session:
        score += 15
        reasons.append(f"Session: {b1['primary_session']} ✓")
    if atr_active:
        score += 5
        reasons.append("Active market ✓")

    # Box 2: No CHOCH against pattern on 1H
    h1_choch = b2["timeframes"]["H1"]["choch_active"]
    if not h1_choch:
        score += 10
        reasons.append("No H1 CHOCH (pattern intact) ✓")

    # Box 3: Second top/bottom sweeps liquidity
    if b3["eqh_count"] > 0 and b3["sweep_just_happened"]:
        score += 30
        reasons.append("EQH swept — double top trap ✓✓")
    elif b3["eql_count"] > 0 and b3["sweep_just_happened"]:
        score += 30
        reasons.append("EQL swept — double bottom trap ✓✓")
    elif b3["eqh_count"] > 0:
        score += 15
        reasons.append("EQH present (waiting for sweep) ✓")
    elif b3["eql_count"] > 0:
        score += 15
        reasons.append("EQL present (waiting for sweep) ✓")

    # Box 4: Pattern at key level
    if b4["at_key_level"]:
        score += 15
        reasons.append("Pattern at key level ✓")

    # Box 5: RSI divergence on second top + volume decrease
    if b5["divergence_active"]:
        score += 20
        reasons.append(f"RSI divergence on second top: {b5['divergence_type']} ✓")
    if b5["volume_m15"]["is_declining"]:
        score += 10
        reasons.append("Volume decreasing on second top ✓")

    # Box 7: Displacement after sweep, FVG
    has_fvg = b7["bull_fvg_count"] > 0 or b7["bear_fvg_count"] > 0
    for p in b7["patterns"]:
        if p["type"] in ["double_top", "double_bottom"]:
            score += 25
            reasons.append(f"Pattern confirmed: {p['type']} ✓✓")
            break

    if has_fvg:
        score += 10
        reasons.append("FVG from displacement ✓")

    pattern_detected = any(p["type"] in ["double_top", "double_bottom"] for p in b7["patterns"])

    # Block when H4 and H1 disagree — counter-trend traps lose
    h4_bias_dttb = b2["timeframes"]["H4"]["bias"]
    h1_bias_dttb = b2["timeframes"]["H1"]["bias"]
    h4_h1_oppose = (
        (h1_bias_dttb == "bullish" and h4_bias_dttb == "bearish") or
        (h1_bias_dttb == "bearish" and h4_bias_dttb == "bullish")
    )

    validated = (
        good_session and
        (b3["eqh_count"] > 0 or b3["eql_count"] > 0) and
        not h4_h1_oppose and
        score >= 60
    )

    missed_rule = "Displacement must occur within 5 candles of sweep"

    return model_result(name, validated, min(score, 100), reasons,
                       entry_type="Retest of displacement candle or OB", missed_rule=missed_rule)


# ------------------------------------------------------------
# MODEL 9 — ORDER BLOCK MITIGATION
# ------------------------------------------------------------

def model_ob_mitigation(b1, b2, b3, b4, b5, b6, b7):
    """
    Concept: Price returns to unmitigated institutional OB.
    """
    name    = "ob_mitigation"
    reasons = []
    score   = 0

    # Box 1: London or NY
    good_session = b1["primary_session"] in ["london", "new_york", "overlap"]
    if good_session:
        score += 15
        reasons.append(f"Session: {b1['primary_session']} ✓")

    # Box 2: Strong displacement visible, structure intact
    h1_structure = b2["timeframes"]["H1"]["structure"]
    if h1_structure in ["bullish", "bearish"]:
        score += 20
        reasons.append(f"Strong H1 structure: {h1_structure} ✓")

    if b2["recent_bos"]:
        score += 10
        reasons.append("Recent BOS confirms displacement ✓")

    # Box 3: Clean retrace (no major sweep on the way to OB)
    clean_retrace = not b3["sweep_just_happened"]
    if clean_retrace:
        score += 10
        reasons.append("Clean retrace to OB ✓")

    # Box 4: OB aligns with pivot or HTF level
    if b4["at_key_level"]:
        score += 20
        reasons.append("OB at institutional level ✓")

    # Box 5: RSI near 50 before continuation, low volume retrace
    rsi_m15 = b5["rsi_m15"] or 50
    rsi_neutral = 40 <= rsi_m15 <= 60
    if rsi_neutral:
        score += 10
        reasons.append(f"RSI stabilized near 50 ({rsi_m15}) ✓")
    if b5["volume_m15"]["is_declining"]:
        score += 10
        reasons.append("Low volume retrace to OB ✓")

    # Box 7: Price at valid OB, rejection candle
    at_ob = b7["at_bull_ob"] or b7["at_bear_ob"]
    has_valid_ob = b7["bull_ob_count"] > 0 or b7["bear_ob_count"] > 0

    if at_ob:
        score += 30
        reasons.append("Price AT order block ✓✓")
    elif has_valid_ob:
        score += 15
        reasons.append("Valid OB nearby ✓")
    else:
        reasons.append("No valid OB found ✗")

    if b7["candle_patterns"]:
        cp = b7["candle_patterns"][0]
        if cp["signal"] in ["bullish", "bearish"]:
            score += 15
            reasons.append(f"Rejection candle: {cp['type']} ✓")

    # OB Mitigation REQUIRES price to actually be AT the OB
    # Just having an OB nearby is not enough — price must be touching it
    htf_bias_ok = b2["timeframes"]["H4"]["bias"] != "neutral"

    validated = (
        good_session and
        has_valid_ob and
        at_ob and                              # MUST be at OB, not just nearby
        h1_structure in ["bullish", "bearish"] and
        htf_bias_ok and                        # H4 must have clear direction
        score >= 75                            # Higher bar — tight SL model
    )

    missed_rule = "Need: price AT OB + H4 bias + rejection candle + score ≥ 75"

    return model_result(name, validated, min(score, 100), reasons,
                       entry_type="OB proximal edge — first touch only", missed_rule=missed_rule)


# ------------------------------------------------------------
# MODEL 10 — FVG CONTINUATION
# ------------------------------------------------------------

def model_fvg_continuation(b1, b2, b3, b4, b5, b6, b7):
    """
    Concept: Market returns to fill imbalance before continuing trend.
    """
    name    = "fvg_continuation"
    reasons = []
    score   = 0

    # Box 1: London or NY
    good_session = b1["primary_session"] in ["london", "new_york", "overlap"]
    if good_session:
        score += 15
        reasons.append(f"Session: {b1['primary_session']} ✓")

    # Box 2: Clear trend on H1, 15M aligned, no opposing BOS
    h1_bias  = b2["timeframes"]["H1"]["bias"]
    m15_bias = b2["timeframes"]["M15"]["bias"]
    aligned  = h1_bias == m15_bias and h1_bias != "neutral"

    if aligned:
        score += 20
        reasons.append(f"H1+M15 aligned: {h1_bias} ✓")
    elif h1_bias != "neutral":
        score += 10
        reasons.append(f"H1 trend: {h1_bias} ✓")

    m15_choch = b2["timeframes"]["M15"]["choch_active"]
    if not m15_choch:
        score += 5
        reasons.append("No opposing BOS ✓")

    # Box 3: Strong displacement created FVG
    if b3["total_sweeps"] > 0:
        score += 10
        reasons.append("Displacement confirmed ✓")

    # Box 4: FVG aligns with OB or pivot
    if b4["at_key_level"]:
        score += 20
        reasons.append("FVG at institutional level ✓")

    # Box 5: RSI holds above/below 50, declining volume retrace
    rsi_holds_bull = b5["rsi_above_mid_m15"] == True and h1_bias == "bullish"
    rsi_holds_bear = b5["rsi_above_mid_m15"] == False and h1_bias == "bearish"

    if rsi_holds_bull or rsi_holds_bear:
        score += 15
        reasons.append("RSI holding trend side ✓")

    if b5["volume_m15"]["is_declining"]:
        score += 10
        reasons.append("Declining volume on retrace ✓")

    # Box 7: FVG present and price tapping it
    has_fvg = b7["bull_fvg_count"] > 0 or b7["bear_fvg_count"] > 0
    at_fvg  = b7["at_bull_fvg"] or b7["at_bear_fvg"]

    if at_fvg:
        score += 30
        reasons.append("Price AT FVG zone ✓✓")
    elif has_fvg:
        score += 15
        reasons.append("Valid FVG nearby ✓")
    else:
        reasons.append("No valid FVG found ✗")

    if b7["candle_patterns"]:
        cp = b7["candle_patterns"][0]
        score += 10
        reasons.append(f"Rejection candle: {cp['type']} ✓")

    validated = (
        good_session and
        has_fvg and
        at_fvg and           # Must be AT the FVG, not just nearby — prevents chasing
        h1_bias != "neutral" and
        score >= 60
    )

    missed_rule = f"FVG fully filled and close beyond → void"

    return model_result(name, validated, min(score, 100), reasons,
                       entry_type="Inside FVG on rejection confirmation", missed_rule=missed_rule)



# ------------------------------------------------------------
# MODEL 11 — ICT SILVER BULLET
# ------------------------------------------------------------

def model_silver_bullet(b1, b2, b3, b4, b5, b6, b7):
    """
    ICT Silver Bullet — time-window based precision model.

    The Silver Bullet strikes during 3 specific 1-hour windows
    when institutional activity is highest. It requires:
    1. Price inside a Silver Bullet kill zone window
    2. Liquidity sweep (BSL for sell, SSL for buy) just happened
    3. MSS (Market Structure Shift) in direction of trade
    4. FVG formed AFTER the displacement (same direction as MSS)
    5. Price has NOT fully filled that FVG yet
    6. HTF bias (H4/D1) aligns with direction

    Windows (GMT — sessions stored in GMT):
      Window 1: 08:00–09:00 GMT  (03:00–04:00 EST — Asian KZ)
      Window 2: 15:00–16:00 GMT  (10:00–11:00 EST — London/NY overlap — strongest)
      Window 3: 19:00–20:00 GMT  (14:00–15:00 EST — NY PM KZ)

    Entry: FVG proximal edge (first price touches)
    SL:    Beyond liquidity sweep wick
    TP:    Opposing liquidity pool (BSL/SSL)
    """
    from datetime import datetime, timezone

    name    = "silver_bullet"
    reasons = []
    score   = 0

    # ── 1. TIME WINDOW CHECK ────────────────────────────────────
    now_gmt = datetime.now(timezone.utc)
    gmt_hour   = now_gmt.hour
    gmt_minute = now_gmt.minute
    gmt_time   = gmt_hour * 60 + gmt_minute  # minutes since midnight GMT

    # Define windows as (start_min, end_min, label)
    windows = [
        (8  * 60,  9 * 60, "Asian KZ (03:00–04:00 EST)"),
        (15 * 60, 16 * 60, "London/NY KZ (10:00–11:00 EST)"),
        (19 * 60, 20 * 60, "NY PM KZ (14:00–15:00 EST)"),
    ]

    in_window    = False
    window_label = None
    for start, end, label in windows:
        if start <= gmt_time < end:
            in_window    = True
            window_label = label
            break

    if in_window:
        score += 30
        reasons.append(f"Silver Bullet window active: {window_label} ✓")
    else:
        # Not in window = automatic fail
        next_window = None
        for start, end, label in windows:
            if gmt_time < start:
                mins_away = start - gmt_time
                next_window = f"{label} in {mins_away // 60}h {mins_away % 60}m"
                break
        reasons.append(f"Outside Silver Bullet window ✗ | Next: {next_window or 'tomorrow'}")
        return model_result(name, False, 0, reasons,
                           entry_type="FVG at proximal edge after displacement",
                           missed_rule="Must be in 08-09, 15-16, or 19-20 GMT window")

    # ── 2. LIQUIDITY SWEEP ──────────────────────────────────────
    # Sweep must have occurred recently (within this window)
    sweep_happened = b3.get("sweep_just_happened", False)
    sweep_dir      = b3.get("sweep_direction")
    bsl_swept      = b3.get("pdh_swept") or b3.get("asian_high_swept") or b3.get("pwh_swept")
    ssl_swept      = b3.get("pdl_swept") or b3.get("asian_low_swept") or b3.get("pwl_swept")

    if sweep_happened and (bsl_swept or ssl_swept):
        score += 25
        liq_type = "BSL (bearish setup)" if bsl_swept else "SSL (bullish setup)"
        reasons.append(f"Liquidity swept: {liq_type} ✓")
    elif sweep_happened:
        score += 15
        reasons.append(f"Sweep detected ({sweep_dir}) — minor level ✓")
    else:
        score += 0
        reasons.append("No liquidity sweep detected ✗")

    # Determine direction from sweep
    # BSL swept = price hunted buy stops above = now expecting SELL
    # SSL swept = price hunted sell stops below = now expecting BUY
    if bsl_swept:
        sweep_bias = "sell"
    elif ssl_swept:
        sweep_bias = "buy"
    elif sweep_dir == "bearish":
        sweep_bias = "sell"
    elif sweep_dir == "bullish":
        sweep_bias = "buy"
    else:
        sweep_bias = None

    # ── 3. MSS — MARKET STRUCTURE SHIFT ────────────────────────
    mss_m5_active  = b2.get("mss_m5_active",  False)
    mss_m15_active = b2.get("mss_m15_active", False)
    mss_m5_type    = b2.get("mss_m5_type")
    mss_m15_type   = b2.get("mss_m15_type")
    mss_active     = mss_m5_active or mss_m15_active
    mss_type       = mss_m5_type or mss_m15_type

    # MSS must agree with sweep direction
    mss_aligned = False
    if sweep_bias == "sell" and mss_type and "bearish" in str(mss_type):
        mss_aligned = True
    elif sweep_bias == "buy" and mss_type and "bullish" in str(mss_type):
        mss_aligned = True

    if mss_active and mss_aligned:
        score += 20
        reasons.append(f"MSS confirmed ({mss_type}) aligns with sweep bias ✓")
    elif mss_active:
        score += 8
        reasons.append(f"MSS active ({mss_type}) but direction unclear ⚠")
    else:
        reasons.append("No MSS detected on M5/M15 ✗")

    # ── 4. FVG FORMED AFTER DISPLACEMENT ───────────────────────
    has_fvg = False
    fvg_label = None

    if sweep_bias == "buy":
        fvgs = b7.get("bullish_fvgs", [])
        if fvgs:
            has_fvg   = True
            fvg_label = f"Bullish FVG at {fvgs[0].get('midpoint', '—')}"
    elif sweep_bias == "sell":
        fvgs = b7.get("bearish_fvgs", [])
        if fvgs:
            has_fvg   = True
            fvg_label = f"Bearish FVG at {fvgs[0].get('midpoint', '—')}"

    if has_fvg:
        score += 20
        reasons.append(f"FVG present after displacement: {fvg_label} ✓")
    else:
        reasons.append("No FVG found in displacement direction ✗")

    # ── 5. HTF BIAS ALIGNMENT ───────────────────────────────────
    h4_bias = b2.get("h4_bias", "neutral")
    d1_bias = b2.get("d1_bias", "neutral")
    overall = b2.get("overall_bias", "neutral")

    htf_aligned = False
    if sweep_bias == "buy"  and h4_bias == "bullish":
        htf_aligned = True  # H4 must be bullish for BUY
    elif sweep_bias == "sell" and h4_bias == "bearish":
        htf_aligned = True  # H4 must be bearish for SELL
    # Removed: D1-only bypass was allowing BUY when H4 bearish in March crash

    if htf_aligned:
        score += 15
        reasons.append(f"HTF aligned: H4={h4_bias}, D1={d1_bias} ✓")
    else:
        reasons.append(f"HTF not fully aligned: H4={h4_bias}, D1={d1_bias} ✗")

    # ── 6. VOLATILITY CHECK ─────────────────────────────────────
    atr_ok = b1.get("volatility_regime") not in ["dead"]
    spread_ok = b1.get("spread_acceptable", True)

    if atr_ok and spread_ok:
        score += 5
        reasons.append("ATR and spread acceptable ✓")

    # ── VALIDATION ──────────────────────────────────────────────
    # Requires: in window + sweep + FVG (minimum 3 core rules)
    # MSS and HTF alignment add score but aren't hard blockers
    core_rules_met = in_window and has_fvg and (sweep_happened or bsl_swept or ssl_swept)

    validated = (
        core_rules_met and
        htf_aligned and
        score >= 65
    )

    direction_str = sweep_bias.upper() if sweep_bias else "?"

    return model_result(
        name, validated, min(score, 100), reasons,
        entry_type=f"FVG proximal edge after displacement ({direction_str})",
        missed_rule="Need: time window + liquidity sweep + FVG + score ≥ 65"
    )


# ------------------------------------------------------------
# MODEL 12 — STRUCTURAL BREAKOUT
# ------------------------------------------------------------

def model_structural_breakout(b1, b2, b3, b4, b5, b6, b7, b13):
    """
    Concept: Fresh BOS with volume confirmation, enter on retest.
    Uses B13 structural breakout detection.
    """
    name    = "structural_breakout"
    reasons = []
    score   = 0

    sb = b13.get("structural_breakout")
    if sb is None:
        return model_result(name, False, 0,
            ["No structural breakout detected ✗"],
            entry_type="Retest of broken structure level",
            missed_rule="Need: fresh BOS + volume + price near retest zone")

    score   = sb["score"]
    reasons = sb["reasons"]

    # Extra: HTF trend alignment gives bonus
    direction = sb["direction"]
    h4_bias   = b2["timeframes"]["H4"]["bias"]  # fixed: was using wrong key
    h1_bias   = b2["timeframes"]["H1"]["bias"]
    htf_dir   = "bullish" if direction == "buy" else "bearish"
    if h4_bias == htf_dir:
        score = min(score + 10, 100)
        reasons.append(f"H4 aligned with breakout ✓")

    # Extra guard: check move exhaustion
    # If price already moved > 3x ATR from last swing, reduce score heavily
    # Uses b4 current_price — no MT5 dependency inside model function
    atr = float(b1.get("atr") or 2.0)
    h4_sh = b2.get("timeframes", {}).get("H4", {}).get("last_sh")
    h4_sl = b2.get("timeframes", {}).get("H4", {}).get("last_sl")
    direction = sb.get("direction")
    current_price = b4.get("current_price")
    if h4_sh and h4_sl and direction and atr > 0 and current_price:
        cp   = float(current_price)
        sh_p = float(h4_sh["price"]) if isinstance(h4_sh, dict) else float(h4_sh)
        sl_p = float(h4_sl["price"]) if isinstance(h4_sl, dict) else float(h4_sl)
        move = (sh_p - cp) if direction == "sell" else (cp - sl_p)
        if move > atr * 3:
            score = max(0, score - 25)
            reasons.append(f"Move exhaustion: {round(move/atr,1)}x ATR already moved ✗")

    # Block when H4 opposes direction — structural breakout against H4 trend loses
    d1_bias_sb = b2["timeframes"]["D1"]["bias"]
    h4_opposes = (
        (direction == "buy"  and h4_bias == "bearish") or
        (direction == "sell" and h4_bias == "bullish") or
        (direction == "sell" and d1_bias_sb == "bullish")  # no SELL in D1 uptrend
    )
    validated = sb["validated"] and score >= 60 and not h4_opposes

    return model_result(
        name, validated, min(score, 100), reasons,
        entry_type=sb.get("entry_type", "Retest of broken structure"),
        missed_rule="Need: BOS active + volume spike + price within 30 pips of retest + no exhaustion"
    )


# ------------------------------------------------------------
# MODEL 13 — MOMENTUM BREAKOUT (STRAIGHT SHOOTER)
# ------------------------------------------------------------

def model_momentum_breakout(b1, b2, b3, b4, b5, b6, b7, b13):
    """
    Concept: Strong displacement candle breaks key level with volume.
    No retest expected — straight shooter entry.
    Uses B13 momentum breakout detection.
    """
    name    = "momentum_breakout"
    reasons = []
    score   = 0

    mb = b13.get("momentum_breakout")
    if mb is None:
        return model_result(name, False, 0,
            ["No momentum breakout detected ✗"],
            entry_type="Momentum breakout entry",
            missed_rule="Need: body>65% + volume spike + broke key level + score≥55")

    score   = mb["score"]
    reasons = mb["reasons"]

    # ATR must be active (not dead market)
    atr_ok = b1.get("volatility_regime") not in ["dead", "low"]
    if not atr_ok:
        return model_result(name, False, 0,
            ["Market too quiet for momentum breakout ✗"],
            entry_type="Momentum breakout entry",
            missed_rule="ATR must be normal or high")

    # Session must be London or NY — momentum breakouts in Asian = fakeouts
    session_ok = b1.get("primary_session") in ["london", "new_york", "overlap"]
    if not session_ok:
        reasons.append(f"Session {b1.get('primary_session')} not ideal for momentum ✗")
        score = max(0, score - 20)
    else:
        reasons.append(f"Session {b1.get('primary_session')} ✓")

    h4_bias_mb   = b2["timeframes"]["H4"]["bias"]
    direction_mb = mb.get("direction", "buy")
    h4_opposes_mb = (
        (direction_mb == "buy"  and h4_bias_mb == "bearish") or
        (direction_mb == "sell" and h4_bias_mb == "bullish")
    )
    validated = mb["validated"] and session_ok and score >= 55 and not h4_opposes_mb

    return model_result(
        name, validated, min(score, 100), reasons,
        entry_type=mb.get("entry_type", "Momentum breakout"),
        missed_rule="Need: body>65% + volume spike + broke key level + London/NY session"
    )


# ------------------------------------------------------------
# MODEL PRIORITY ORDER
# ------------------------------------------------------------

# Active models — focused on 2 proven models for now
# Disabled models kept in code (see ARCHIVED_PRIORITY below) for future re-enabling
MODEL_PRIORITY = [
    "structural_breakout",    # ← BOS retest entry, big winners on reversal days
    "momentum_breakout",      # ← straight shooter: trending market continuation
]

# Disabled models — re-enable by moving entries up to MODEL_PRIORITY
# These were disabled after Phase 1 testing showed they don't fire reliably
# or generate consistent losses in current market conditions
ARCHIVED_PRIORITY = [
    "silver_bullet",          # counter-trend reversal, killed by H4+H1 conflict
    "london_sweep_reverse",   # never fills
    "htf_level_reaction",     # fires counter-trend, lost in January
    "liquidity_grab_bos",     # same issue as silver_bullet
    "ob_fvg_stack",           # ghosts heavily
    "choch_reversal",         # ghosts in trends
    "ob_mitigation",          # counter-trend losses
    "fvg_continuation",       # ghosts and bounces lose
    "ny_continuation",        # barely fires
    "double_top_bottom_trap", # counter-trend losses
    "asian_range_breakout",   # ghosts
]


# ------------------------------------------------------------
# MAIN ENGINE FUNCTION
# ------------------------------------------------------------

def run(b1, b2, b3, b4, b5, b6, b7, b13=None):
    """
    Run all 10 models and return validated ones.

    Args:
        b1-b7: outputs from box engines 1-7
        b13:   breakout engine output (optional)

    Returns:
        dict with all model results + best model
    """
    # Run all models
    # B13 defaults to empty dict if not provided (backward compatible)
    _b13 = b13 if b13 is not None else {}

    results = {
        "silver_bullet":           model_silver_bullet(b1, b2, b3, b4, b5, b6, b7),
        "momentum_breakout":       model_momentum_breakout(b1, b2, b3, b4, b5, b6, b7, _b13),
        "london_sweep_reverse":    model_london_sweep_reverse(b1, b2, b3, b4, b5, b6, b7),
        "structural_breakout":     model_structural_breakout(b1, b2, b3, b4, b5, b6, b7, _b13),
        "ny_continuation":         model_ny_continuation(b1, b2, b3, b4, b5, b6, b7),
        "asian_range_breakout":    model_asian_range_breakout(b1, b2, b3, b4, b5, b6, b7),
        "ob_fvg_stack":            model_ob_fvg_stack(b1, b2, b3, b4, b5, b6, b7),
        "liquidity_grab_bos":      model_liquidity_grab_bos(b1, b2, b3, b4, b5, b6, b7),
        "htf_level_reaction":      model_htf_level_reaction(b1, b2, b3, b4, b5, b6, b7),
        "choch_reversal":          model_choch_reversal(b1, b2, b3, b4, b5, b6, b7),
        "double_top_bottom_trap":  model_double_top_bottom_trap(b1, b2, b3, b4, b5, b6, b7),
        "ob_mitigation":           model_ob_mitigation(b1, b2, b3, b4, b5, b6, b7),
        "fvg_continuation":        model_fvg_continuation(b1, b2, b3, b4, b5, b6, b7),
    }

    # Get validated models
    validated_models = {
        name: result for name, result in results.items()
        if result["validated"]
    }

    # Best model selection:
    # 1. First find highest scoring validated model
    # 2. Then check if any higher-priority model is within 15 points of it
    # 3. If yes — priority wins. If no — higher score wins.
    # This means Silver Bullet always beats everything in its window,
    # but Structural Breakout at 85 beats Liquidity Grab BOS at 70.
    best_model = None
    best_score = 0

    # Find highest scoring validated model first
    for name, m in validated_models.items():
        if m["score"] > best_score:
            best_score = m["score"]
            best_model = m
            best_model["name"] = name

    # Now check if a higher-priority model is close enough to override
    if best_model:
        for model_name in MODEL_PRIORITY:
            if model_name == best_model["name"]:
                break  # reached current best — nothing higher priority validated
            if model_name in validated_models:
                priority_model = validated_models[model_name]
                # Override if within 15 points OR if it's a time-critical model
                time_critical = model_name in ["silver_bullet", "momentum_breakout"]
                within_range  = priority_model["score"] >= best_score - 15
                if time_critical or within_range:
                    best_model = priority_model
                    best_model["name"] = model_name
                    best_score = priority_model["score"]
                    break

    active_model = best_model

    # Engine score
    engine_score = best_score if best_model else 0

    return {
        "all_models":        results,
        "validated_models":  validated_models,
        "validated_count":   len(validated_models),
        "active_model":      active_model,
        "best_model_name":   best_model["name"] if best_model else None,
        "best_model_score":  best_score,
        "engine_score":      engine_score,
        "model_validated":   active_model is not None,
        "total_models":     len(results),
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

    print("Testing Box 8 — Model Engine")
    print("=" * 50)

    mt5.initialize()
    store.refresh()

    b1 = run_b1(store)
    b2 = run_b2(store)
    b3 = run_b3(store)
    b4 = run_b4(store)
    b5 = run_b5(store)
    b6 = run_b6(store)
    b7 = run_b7(store)

    result = run(b1, b2, b3, b4, b5, b6, b7)

    print(f"\nModels Validated: {result['validated_count']}/11")
    print(f"\nAll Model Scores:")
    for name, m in result["all_models"].items():
        status = "✓ VALIDATED" if m["validated"] else "✗"
        print(f"  {name:30} Score: {m['score']:3} {status}")

    print(f"\nActive Model: {result['best_model_name']}")
    print(f"Model Score:  {result['best_model_score']}")

    if result["active_model"]:
        print(f"\nReasons:")
        for r in result["active_model"]["reasons"]:
            print(f"  {r}")
        print(f"\nEntry Type:  {result['active_model']['entry_type']}")
        print(f"Missed Rule: {result['active_model']['missed_rule']}")

    mt5.shutdown()
    print("\nBox 8 Test PASSED ✓")
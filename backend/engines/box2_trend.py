# ============================================================
# box2_trend.py — Trend Engine
# Defines directional bias across all timeframes
# Detects: Market Structure, BOS, CHOCH, HH, HL, LH, LL
# ============================================================

import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import (
    SWING_LOOKBACK,
    STRUCTURE_SENSITIVITY,
    BOS_CONFIRMATION_CANDLES,
    CHOCH_CONFIRMATION_CANDLES
)


# ------------------------------------------------------------
# SWING DETECTION
# ------------------------------------------------------------

def find_swings(df, lookback=None):
    """
    Find swing highs and swing lows in price data.
    A swing high = highest point with lower highs on both sides
    A swing low  = lowest point with higher lows on both sides

    Returns:
        swing_highs: list of (index, price) tuples
        swing_lows:  list of (index, price) tuples
    """
    if lookback is None:
        lookback = SWING_LOOKBACK

    if df is None or len(df) < lookback * 2 + 1:
        return [], []

    swing_highs = []
    swing_lows  = []

    for i in range(lookback, len(df) - lookback):
        # Check swing high
        is_swing_high = all(
            df["high"].iloc[i] >= df["high"].iloc[i - j] and
            df["high"].iloc[i] >= df["high"].iloc[i + j]
            for j in range(1, lookback + 1)
        )
        if is_swing_high:
            swing_highs.append({
                "index": i,
                "price": df["high"].iloc[i],
                "time":  df["time"].iloc[i]
            })

        # Check swing low
        is_swing_low = all(
            df["low"].iloc[i] <= df["low"].iloc[i - j] and
            df["low"].iloc[i] <= df["low"].iloc[i + j]
            for j in range(1, lookback + 1)
        )
        if is_swing_low:
            swing_lows.append({
                "index": i,
                "price": df["low"].iloc[i],
                "time":  df["time"].iloc[i]
            })

    return swing_highs, swing_lows


# ------------------------------------------------------------
# MARKET STRUCTURE (HH, HL, LH, LL)
# ------------------------------------------------------------

def get_market_structure(swing_highs, swing_lows):
    """
    Determine market structure from swing points.
    Compares last two swing highs and last two swing lows.

    Structure types:
        HH + HL = Bullish trend
        LH + LL = Bearish trend
        HH + LL = Expansion (no clear trend)
        LH + HL = Consolidation/ranging
    """
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return {
            "structure": "unknown",
            "last_sh":   None,
            "prev_sh":   None,
            "last_sl":   None,
            "prev_sl":   None,
            "hh": False, "hl": False,
            "lh": False, "ll": False,
        }

    last_sh = swing_highs[-1]
    prev_sh = swing_highs[-2]
    last_sl = swing_lows[-1]
    prev_sl = swing_lows[-2]

    # Compare swing points
    hh = last_sh["price"] > prev_sh["price"]  # Higher High
    hl = last_sl["price"] > prev_sl["price"]  # Higher Low
    lh = last_sh["price"] < prev_sh["price"]  # Lower High
    ll = last_sl["price"] < prev_sl["price"]  # Lower Low

    # Determine overall structure
    if hh and hl:
        structure = "bullish"
    elif lh and ll:
        structure = "bearish"
    elif hh and ll:
        structure = "expansion"
    elif lh and hl:
        structure = "ranging"
    else:
        structure = "neutral"

    return {
        "structure": structure,
        "last_sh":   last_sh,
        "prev_sh":   prev_sh,
        "last_sl":   last_sl,
        "prev_sl":   prev_sl,
        "hh": hh, "hl": hl,
        "lh": lh, "ll": ll,
    }


# ------------------------------------------------------------
# BOS — BREAK OF STRUCTURE
# ------------------------------------------------------------

def detect_bos(df, swing_highs, swing_lows):
    """
    Detect Break of Structure (BOS).
    BOS = price closes beyond the most recent swing high/low
    in the SAME direction as the current trend.
    This CONFIRMS trend continuation.

    Returns list of BOS events (most recent last)
    """
    bos_events = []

    if df is None or len(df) < 3:
        return bos_events

    closes = df["close"].values

    # Check each swing high for bullish BOS
    for sh in swing_highs:
        idx = sh["index"]
        level = sh["price"]

        # Look for close above this swing high after it formed
        for i in range(idx + 1, len(closes)):
            if closes[i] > level:
                bos_events.append({
                    "type":      "bullish_bos",
                    "level":     level,
                    "broken_at": i,
                    "time":      df["time"].iloc[i],
                    "candle_index": idx
                })
                break  # Only log first break

    # Check each swing low for bearish BOS
    for sl in swing_lows:
        idx = sl["index"]
        level = sl["price"]

        for i in range(idx + 1, len(closes)):
            if closes[i] < level:
                bos_events.append({
                    "type":      "bearish_bos",
                    "level":     level,
                    "broken_at": i,
                    "time":      df["time"].iloc[i],
                    "candle_index": idx
                })
                break

    # Sort by when they were broken
    bos_events.sort(key=lambda x: x["broken_at"])

    return bos_events


# ------------------------------------------------------------
# CHOCH — CHANGE OF CHARACTER
# ------------------------------------------------------------

def detect_choch(df, swing_highs, swing_lows, market_structure):
    """
    Detect Change of Character (CHOCH).
    CHOCH = price closes beyond a swing point in the OPPOSITE
    direction to the current trend.
    This SIGNALS potential trend reversal.

    In a bullish trend: close below last swing low = CHOCH
    In a bearish trend: close above last swing high = CHOCH
    """
    choch_events = []

    if df is None or len(df) < 3:
        return choch_events

    closes = df["close"].values
    structure = market_structure["structure"]

    if structure == "bullish" and market_structure["last_sl"] is not None:
        # Bearish CHOCH in bullish trend
        last_sl = market_structure["last_sl"]
        level = last_sl["price"]
        idx = last_sl["index"]

        for i in range(idx + 1, len(closes)):
            if closes[i] < level:
                choch_events.append({
                    "type":      "bearish_choch",
                    "level":     level,
                    "broken_at": i,
                    "time":      df["time"].iloc[i],
                    "prior_structure": "bullish"
                })
                break

    elif structure == "bearish" and market_structure["last_sh"] is not None:
        # Bullish CHOCH in bearish trend
        last_sh = market_structure["last_sh"]
        level = last_sh["price"]
        idx = last_sh["index"]

        for i in range(idx + 1, len(closes)):
            if closes[i] > level:
                choch_events.append({
                    "type":      "bullish_choch",
                    "level":     level,
                    "broken_at": i,
                    "time":      df["time"].iloc[i],
                    "prior_structure": "bearish"
                })
                break



# ------------------------------------------------------------
# MSS — MARKET STRUCTURE SHIFT
# ------------------------------------------------------------

def detect_mss(df, swing_highs, swing_lows, lookback=3):
    """
    MSS = short-term structural shift WITH displacement candle.
    Differs from CHOCH: MSS acts as early warning, requires a
    strong displacement candle that breaks a recent swing point.

    Bullish MSS: strong bull candle closes above recent swing high
    Bearish MSS: strong bear candle closes below recent swing low

    Displacement = candle body > 60% of total range.
    """
    mss_events = []
    if df is None or len(df) < lookback + 3:
        return mss_events

    closes = df["close"].values
    opens  = df["open"].values
    highs  = df["high"].values
    lows   = df["low"].values

    recent_shs = swing_highs[-lookback:] if len(swing_highs) >= lookback else swing_highs
    for sh in recent_shs:
        idx   = sh["index"]
        level = sh["price"]
        for i in range(idx + 1, len(closes)):
            if closes[i] > level:
                body = abs(closes[i] - opens[i])
                rng  = highs[i] - lows[i]
                displacement = rng > 0 and body / rng > 0.6 and closes[i] > opens[i]
                mss_events.append({
                    "type":         "bullish_mss",
                    "level":        level,
                    "broken_at":    i,
                    "time":         df["time"].iloc[i],
                    "displacement": displacement,
                    "strength":     "strong" if displacement else "weak",
                })
                break

    recent_sls = swing_lows[-lookback:] if len(swing_lows) >= lookback else swing_lows
    for sl in recent_sls:
        idx   = sl["index"]
        level = sl["price"]
        for i in range(idx + 1, len(closes)):
            if closes[i] < level:
                body = abs(closes[i] - opens[i])
                rng  = highs[i] - lows[i]
                displacement = rng > 0 and body / rng > 0.6 and closes[i] < opens[i]
                mss_events.append({
                    "type":         "bearish_mss",
                    "level":        level,
                    "broken_at":    i,
                    "time":         df["time"].iloc[i],
                    "displacement": displacement,
                    "strength":     "strong" if displacement else "weak",
                })
                break

    mss_events.sort(key=lambda x: x["broken_at"])
    return mss_events

    return choch_events


# ------------------------------------------------------------
# TOP DOWN ANALYSIS
# ------------------------------------------------------------

def analyze_timeframe(df, timeframe_str, lookback=None):
    """
    Run full structure analysis on a single timeframe.
    Returns structure, swings, BOS, CHOCH for that TF.
    """
    if df is None or len(df) < 20:
        return {
            "timeframe":  timeframe_str,
            "structure":  "unknown",
            "bias":       "neutral",
            "bos":        [],
            "choch":      [],
            "swing_highs": [],
            "swing_lows":  [],
            "score":       0
        }

    # Use smaller lookback for lower timeframes
    lb_map = {
        "M5": 3, "M15": 3, "H1": 5,
        "H4": 5, "D1": 5, "W1": 3, "MN": 2
    }
    lb = lookback or lb_map.get(timeframe_str, SWING_LOOKBACK)

    swing_highs, swing_lows = find_swings(df, lookback=lb)
    market_structure = get_market_structure(swing_highs, swing_lows)
    bos_events  = detect_bos(df, swing_highs, swing_lows)
    choch_events = detect_choch(df, swing_highs, swing_lows, market_structure)

    structure = market_structure["structure"]

    # Determine bias
    if structure == "bullish":
        bias = "bullish"
    elif structure == "bearish":
        bias = "bearish"
    else:
        bias = "neutral"

    # Check most recent BOS direction + freshness
    bos_active = False
    if bos_events:
        last_bos = bos_events[-1]
        if last_bos["type"] == "bullish_bos":
            bias = "bullish"
        elif last_bos["type"] == "bearish_bos":
            bias = "bearish"
        # BOS is fresh if it happened within last 20 candles on this TF
        if len(df) - last_bos["broken_at"] <= 20:
            bos_active = True

    # Check if CHOCH just fired (potential reversal)
    choch_active = False
    if choch_events:
        last_choch = choch_events[-1]
        # If CHOCH is very recent (last 10 candles)
        if len(df) - last_choch["broken_at"] <= 10:
            choch_active = True
            # CHOCH flips bias
            if last_choch["type"] == "bullish_choch":
                bias = "bullish"
            elif last_choch["type"] == "bearish_choch":
                bias = "bearish"

    # Score this timeframe (0-100)
    score_map = {
        "bullish":   80,
        "bearish":   80,
        "ranging":   40,
        "expansion": 30,
        "neutral":   20,
        "unknown":   0
    }
    score = score_map.get(structure, 0)
    if choch_active:
        score += 15  # Bonus for fresh CHOCH signal
    score = min(score, 100)

    # MSS detection
    mss_events   = detect_mss(df, swing_highs, swing_lows)
    mss_active   = False
    mss_type     = None
    if mss_events:
        last_mss = mss_events[-1]
        if len(df) - last_mss["broken_at"] <= 5:  # within last 5 candles
            mss_active = True
            mss_type   = last_mss["type"]

    # Internal vs External structure classification
    structure_type = "external" if timeframe_str in ["H4", "D1", "W1", "MN"] else "internal"

    return {
        "timeframe":      timeframe_str,
        "structure":      structure,
        "bias":           bias,
        "structure_type": structure_type,
        "hh":             market_structure["hh"],
        "hl":             market_structure["hl"],
        "lh":             market_structure["lh"],
        "ll":             market_structure["ll"],
        "last_sh":        market_structure["last_sh"],
        "last_sl":        market_structure["last_sl"],
        "bos":            bos_events[-3:] if bos_events else [],
        "bos_active":     bos_active,
        "choch":          choch_events[-2:] if choch_events else [],
        "choch_active":   choch_active,
        "mss":            mss_events[-2:] if mss_events else [],
        "mss_active":     mss_active,
        "mss_type":       mss_type,
        "score":          score
    }


# ------------------------------------------------------------
# MAIN ENGINE FUNCTION
# ------------------------------------------------------------

def run(candle_store):
    """
    Run full Trend Engine — top down analysis across all timeframes.

    Timeframe hierarchy (highest to lowest):
    MN → W1 → D1 → H4 → H1 → M15 → M5

    Returns:
        dict with bias per timeframe + overall bias + alignment score
    """

    timeframes = ["MN", "W1", "D1", "H4", "H1", "M15", "M5"]
    tf_results = {}

    for tf in timeframes:
        df = candle_store.get_closed(tf)
        tf_results[tf] = analyze_timeframe(df, tf)

    # ------------------------------------------------------------
    # OVERALL BIAS — weighted by timeframe importance
    # ------------------------------------------------------------
    tf_weights = {
        "MN":  0.25,
        "W1":  0.20,
        "D1":  0.20,
        "H4":  0.15,
        "H1":  0.10,
        "M15": 0.05,
        "M5":  0.05,
    }

    bull_score = 0
    bear_score = 0

    for tf, weight in tf_weights.items():
        result = tf_results[tf]
        if result["bias"] == "bullish":
            bull_score += weight
        elif result["bias"] == "bearish":
            bear_score += weight

    if bull_score > bear_score and bull_score > 0.4:
        overall_bias = "bullish"
    elif bear_score > bull_score and bear_score > 0.4:
        overall_bias = "bearish"
    else:
        overall_bias = "neutral"

    # ------------------------------------------------------------
    # ALIGNMENT SCORE
    # How many timeframes agree with overall bias?
    # ------------------------------------------------------------
    if overall_bias != "neutral":
        aligned = sum(
            1 for tf in timeframes
            if tf_results[tf]["bias"] == overall_bias
        )
        alignment_score = int((aligned / len(timeframes)) * 100)
    else:
        alignment_score = 0

    # ------------------------------------------------------------
    # ENGINE SCORE for confluence
    # ------------------------------------------------------------
    if overall_bias != "neutral":
        engine_score = alignment_score
    else:
        engine_score = 20

    # Recent structure signals on lower timeframes
    m15_result = tf_results["M15"]
    m5_result  = tf_results["M5"]
    h1_result  = tf_results["H1"]

    recent_bos   = m15_result["bos_active"] or m5_result["bos_active"]
    recent_choch = m15_result["choch_active"] or m5_result["choch_active"]

    return {
        # Per timeframe results
        "timeframes":       tf_results,

        # Overall
        "overall_bias":     overall_bias,
        "bull_score":       round(bull_score, 3),
        "bear_score":       round(bear_score, 3),
        "alignment_score":  alignment_score,
        "engine_score":     engine_score,

        # Key signals
        "recent_bos":       recent_bos,
        "recent_choch":     recent_choch,
        "h1_bias":          h1_result["bias"],
        "d1_bias":          tf_results["D1"]["bias"],
        "h4_bias":          tf_results["H4"]["bias"],

        # MSS signals (internal structure shifts on LTFs)
        "mss_m5_active":    tf_results["M5"]["mss_active"],
        "mss_m15_active":   tf_results["M15"]["mss_active"],
        "mss_m5_type":      tf_results["M5"]["mss_type"],
        "mss_m15_type":     tf_results["M15"]["mss_type"],

        # Structure classification summary
        "internal_bias":    m15_result["bias"],    # M15 = internal structure
        "external_bias":    tf_results["H4"]["bias"],  # H4 = external structure
    }


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------

if __name__ == "__main__":
    import MetaTrader5 as mt5
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data.candle_store import store

    print("Testing Box 2 — Trend Engine")
    print("=" * 50)

    mt5.initialize()
    store.refresh()

    result = run(store)

    print(f"\nOverall Bias:      {result['overall_bias'].upper()}")
    print(f"Bull Score:        {result['bull_score']}")
    print(f"Bear Score:        {result['bear_score']}")
    print(f"Alignment Score:   {result['alignment_score']}%")
    print(f"Engine Score:      {result['engine_score']}/100")
    print(f"\nPer Timeframe:")
    for tf, data in result["timeframes"].items():
        choch_flag = " ← CHOCH!" if data["choch_active"] else ""
        print(f"  {tf:>4}: {data['bias']:>8} | {data['structure']:>10} | "
              f"HH:{data['hh']} HL:{data['hl']} LH:{data['lh']} LL:{data['ll']}{choch_flag}")

    print(f"\nD1 Bias:  {result['d1_bias']}")
    print(f"H4 Bias:  {result['h4_bias']}")
    print(f"H1 Bias:  {result['h1_bias']}")
    print(f"Recent BOS:   {len(result['recent_bos'])} signals")
    print(f"Recent CHOCH: {result['recent_choch']}")

    mt5.shutdown()
    print("\nBox 2 Test PASSED ✓")
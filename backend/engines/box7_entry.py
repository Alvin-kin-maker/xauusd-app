# ============================================================
# box7_entry.py — Entry Engine
# Finds precise sniped entries
# Tools: Order Blocks, FVGs, Breaker Blocks, Mitigation Blocks,
#        Fibonacci Zones, Pattern Detection, Candlestick Confirmation
# ============================================================

import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import (
    OB_MAX_ATR_MULTIPLIER,
    OB_SWING_LENGTH,
    FVG_MIN_SIZE,
    FIB_LEVELS,
    MAX_OB_TOUCHES
)


# ------------------------------------------------------------
# ATR HELPER
# ------------------------------------------------------------

def get_atr(df, period=14):
    if df is None or len(df) < period + 1:
        return 1.0
    df = df.copy()
    df["prev_close"] = df["close"].shift(1)
    df["tr"] = df[["high", "low", "prev_close"]].apply(
        lambda r: max(r["high"] - r["low"],
                      abs(r["high"] - r["prev_close"]),
                      abs(r["low"]  - r["prev_close"])), axis=1
    )
    atr = df["tr"].iloc[-period:].mean()
    return float(atr) if not np.isnan(atr) else 1.0


# ------------------------------------------------------------
# ORDER BLOCKS
# ------------------------------------------------------------

def find_order_blocks(df, atr=None, swing_length=None):
    """
    Detect Bullish and Bearish Order Blocks.

    Bullish OB: When price breaks above a swing high,
    the lowest candle in the move before the break = Bull OB

    Bearish OB: When price breaks below a swing low,
    the highest candle in the move before the break = Bear OB

    OB becomes a BREAKER when price closes through it.
    """
    if swing_length is None:
        swing_length = OB_SWING_LENGTH
    if atr is None:
        atr = get_atr(df)

    if df is None or len(df) < swing_length * 2 + 5:
        return [], []

    bullish_obs = []
    bearish_obs = []

    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values
    opens  = df["open"].values
    times  = df["time"].values

    # Find swing highs and lows
    swing_highs = []
    swing_lows  = []

    for i in range(swing_length, len(df) - swing_length):
        if all(highs[i] >= highs[i-j] and highs[i] >= highs[i+j]
               for j in range(1, swing_length + 1)):
            swing_highs.append({"index": i, "price": highs[i], "time": times[i]})

        if all(lows[i] <= lows[i-j] and lows[i] <= lows[i+j]
               for j in range(1, swing_length + 1)):
            swing_lows.append({"index": i, "price": lows[i], "time": times[i]})

    # Bullish OB — price breaks above swing high
    for sh in swing_highs:
        idx   = sh["index"]
        level = sh["price"]

        # Find where price closes above this swing high
        break_idx = None
        for i in range(idx + 1, min(idx + 50, len(closes))):
            if closes[i] > level:
                break_idx = i
                break

        if break_idx is None:
            continue

        # Find the lowest candle between swing high and break
        ob_idx   = idx
        ob_low   = lows[idx]
        ob_high  = highs[idx]

        for i in range(idx, break_idx):
            if lows[i] < ob_low:
                ob_low  = lows[i]
                ob_high = highs[i]
                ob_idx  = i

        ob_size = ob_high - ob_low

        # Filter: OB must not be too large
        if ob_size > atr * OB_MAX_ATR_MULTIPLIER:
            continue

        # Check if OB has been mitigated (price returned to it)
        touches   = 0
        breaker   = False
        break_time = None

        for i in range(break_idx + 1, len(closes)):
            if lows[i] <= ob_high and highs[i] >= ob_low:
                touches += 1
            if closes[i] < ob_low:
                breaker    = True
                break_time = times[i]
                break

        bullish_obs.append({
            "type":       "bullish_ob",
            "top":        round(float(ob_high), 2),
            "bottom":     round(float(ob_low),  2),
            "index":      ob_idx,
            "time":       times[ob_idx],
            "break_time": break_time,
            "touches":    touches,
            "breaker":    breaker,
            "size":       round(float(ob_size), 2),
            "valid":      not breaker and touches < MAX_OB_TOUCHES
        })

    # Bearish OB — price breaks below swing low
    for sl in swing_lows:
        idx   = sl["index"]
        level = sl["price"]

        break_idx = None
        for i in range(idx + 1, min(idx + 50, len(closes))):
            if closes[i] < level:
                break_idx = i
                break

        if break_idx is None:
            continue

        ob_idx  = idx
        ob_high = highs[idx]
        ob_low  = lows[idx]

        for i in range(idx, break_idx):
            if highs[i] > ob_high:
                ob_high = highs[i]
                ob_low  = lows[i]
                ob_idx  = i

        ob_size = ob_high - ob_low

        if ob_size > atr * OB_MAX_ATR_MULTIPLIER:
            continue

        touches    = 0
        breaker    = False
        break_time = None

        for i in range(break_idx + 1, len(closes)):
            if lows[i] <= ob_high and highs[i] >= ob_low:
                touches += 1
            if closes[i] > ob_high:
                breaker    = True
                break_time = times[i]
                break

        bearish_obs.append({
            "type":       "bearish_ob",
            "top":        round(float(ob_high), 2),
            "bottom":     round(float(ob_low),  2),
            "index":      ob_idx,
            "time":       times[ob_idx],
            "break_time": break_time,
            "touches":    touches,
            "breaker":    breaker,
            "size":       round(float(ob_size), 2),
            "valid":      not breaker and touches < MAX_OB_TOUCHES
        })

    # Sort by most recent
    bullish_obs.sort(key=lambda x: x["index"], reverse=True)
    bearish_obs.sort(key=lambda x: x["index"], reverse=True)

    return bullish_obs[:5], bearish_obs[:5]


# ------------------------------------------------------------
# FAIR VALUE GAPS (FVG)
# ------------------------------------------------------------

def find_fvgs(df):
    """
    Detect Fair Value Gaps (Imbalances).

    Bullish FVG: Gap between candle[i-1] high and candle[i+1] low
                 (price moved up so fast it left a gap)
    Bearish FVG: Gap between candle[i-1] low and candle[i+1] high
                 (price moved down so fast it left a gap)

    FVG is "filled" when price returns to close the gap.
    """
    if df is None or len(df) < 3:
        return [], []

    bullish_fvgs = []
    bearish_fvgs = []

    for i in range(1, len(df) - 1):
        prev = df.iloc[i - 1]
        curr = df.iloc[i]
        nxt  = df.iloc[i + 1]

        # Bullish FVG: gap above between prev high and next low
        if nxt["low"] > prev["high"]:
            gap_size = nxt["low"] - prev["high"]
            if gap_size >= FVG_MIN_SIZE:
                # Check if filled — 50% CE (consequent encroachment) is the fill threshold
                # Price touching the midpoint = FVG filled, consistent with bearish FVG logic
                filled = False
                ce = prev["high"] + gap_size * 0.5  # midpoint of gap
                for j in range(i + 2, len(df)):
                    if df.iloc[j]["low"] <= ce:
                        filled = True
                        break

                bullish_fvgs.append({
                    "type":      "bullish_fvg",
                    "top":       round(float(nxt["low"]),   2),
                    "bottom":    round(float(prev["high"]), 2),
                    "midpoint":  round(float((nxt["low"] + prev["high"]) / 2), 2),
                    "size":      round(float(gap_size), 2),
                    "index":     i,
                    "time":      curr["time"],
                    "filled":    filled,
                    "valid":     not filled
                })

        # Bearish FVG: gap below between prev low and next high
        if nxt["high"] < prev["low"]:
            gap_size = prev["low"] - nxt["high"]
            if gap_size >= FVG_MIN_SIZE:
                filled = False
                for j in range(i + 2, len(df)):
                    if df.iloc[j]["high"] >= nxt["high"] + gap_size * 0.5:
                        filled = True
                        break

                bearish_fvgs.append({
                    "type":      "bearish_fvg",
                    "top":       round(float(prev["low"]),  2),
                    "bottom":    round(float(nxt["high"]),  2),
                    "midpoint":  round(float((prev["low"] + nxt["high"]) / 2), 2),
                    "size":      round(float(gap_size), 2),
                    "index":     i,
                    "time":      curr["time"],
                    "filled":    filled,
                    "valid":     not filled
                })

    # Most recent first
    bullish_fvgs.sort(key=lambda x: x["index"], reverse=True)
    bearish_fvgs.sort(key=lambda x: x["index"], reverse=True)

    return bullish_fvgs[:5], bearish_fvgs[:5]


# ------------------------------------------------------------
# BREAKER BLOCKS
# ------------------------------------------------------------

def find_breaker_blocks(bullish_obs, bearish_obs):
    """
    Breaker blocks are invalidated OBs that flip polarity.

    Bullish OB that gets broken → becomes Bearish Breaker
    (price likely to react bearishly when it returns)

    Bearish OB that gets broken → becomes Bullish Breaker
    (price likely to react bullishly when it returns)
    """
    bullish_breakers = []
    bearish_breakers = []

    for ob in bullish_obs:
        if ob["breaker"]:
            bearish_breakers.append({
                "type":       "bearish_breaker",
                "top":        ob["top"],
                "bottom":     ob["bottom"],
                "origin":     "bullish_ob",
                "index":      ob["index"],
                "time":       ob["time"],
                "break_time": ob["break_time"]
            })

    for ob in bearish_obs:
        if ob["breaker"]:
            bullish_breakers.append({
                "type":       "bullish_breaker",
                "top":        ob["top"],
                "bottom":     ob["bottom"],
                "origin":     "bearish_ob",
                "index":      ob["index"],
                "time":       ob["time"],
                "break_time": ob["break_time"]
            })

    return bullish_breakers, bearish_breakers


# ------------------------------------------------------------
# FIBONACCI ZONES
# ------------------------------------------------------------

def calculate_fibonacci(swing_high, swing_low, direction="bullish"):
    """
    Calculate Fibonacci retracement levels.

    For bullish retracement (buying the dip):
        Measure from swing low to swing high
        Key levels: 0.5, 0.618, 0.705 (golden zone)

    For bearish retracement (selling the rally):
        Measure from swing high to swing low
        Key levels: 0.5, 0.618, 0.705
    """
    if swing_high is None or swing_low is None:
        return []

    diff   = swing_high - swing_low
    levels = []

    for fib in FIB_LEVELS:
        if direction == "bullish":
            # Retracement from high down
            price = swing_high - (diff * fib)
        else:
            # Retracement from low up
            price = swing_low + (diff * fib)

        levels.append({
            "level":  round(float(price), 2),
            "ratio":  fib,
            "label":  f"Fib {fib}",
            "is_golden": fib in [0.5, 0.618, 0.705]
        })

    return levels


def get_recent_fibonacci(df, b2_swing_high=None, b2_swing_low=None):
    """
    Calculate fibs anchored to confirmed B2 swing points (BOS/CHOCH).
    If B2 swings provided, use them — these are institutional swing points.
    Falls back to rolling window only if B2 data unavailable.
    """
    if df is None or len(df) < 20:
        return [], "unknown"

    swing_high = None
    swing_low  = None

    # Priority 1: confirmed B2 swing points (BOS/CHOCH anchors) — most accurate
    if b2_swing_high is not None and b2_swing_low is not None:
        swing_high = float(b2_swing_high)
        swing_low  = float(b2_swing_low)
    else:
        # Priority 2: use recent significant highs/lows from candle data
        # Find actual swing high/low using pivot detection instead of raw max/min
        # This avoids anchoring to random wicks on rolling window
        lookback = min(50, len(df))
        recent   = df.iloc[-lookback:]
        # Find the most significant high and low using 3-bar pivot logic
        highs = recent["high"].values
        lows  = recent["low"].values
        sig_highs = []
        sig_lows  = []
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and                highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                sig_highs.append(highs[i])
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and                lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                sig_lows.append(lows[i])
        if sig_highs and sig_lows:
            swing_high = float(max(sig_highs))
            swing_low  = float(min(sig_lows))
        else:
            # Last resort: rolling window max/min
            swing_high = float(recent["high"].max())
            swing_low  = float(recent["low"].min())

    if swing_high is None or swing_low is None or swing_high <= swing_low:
        return [], "unknown"

    current = float(df.iloc[-1]["close"])
    direction = "bullish" if current > (swing_high + swing_low) / 2 else "bearish"

    fibs = calculate_fibonacci(swing_high, swing_low, direction)
    return fibs, direction


def detect_ote_zone(df, b2_swing_high=None, b2_swing_low=None):
    """
    OTE = Optimal Trade Entry (61.8% to 79% retracement).
    Anchored to confirmed B2 BOS/CHOCH swing points when available.
    These are the real institutional swings the market respects.
    """
    if df is None or len(df) < 20:
        return {"in_ote": False, "ote_direction": None}

    current = float(df.iloc[-1]["close"])

    # Use B2 confirmed swings if available
    if b2_swing_high is not None and b2_swing_low is not None:
        swing_high = float(b2_swing_high)
        swing_low  = float(b2_swing_low)
    else:
        # Use pivot-detected swings not raw max/min
        lookback = min(50, len(df))
        recent   = df.iloc[-lookback:]
        highs = recent["high"].values
        lows  = recent["low"].values
        sig_highs = []
        sig_lows  = []
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and                highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                sig_highs.append(highs[i])
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and                lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                sig_lows.append(lows[i])
        if sig_highs and sig_lows:
            swing_high = float(max(sig_highs))
            swing_low  = float(min(sig_lows))
        else:
            swing_high = float(recent["high"].max())
            swing_low  = float(recent["low"].min())

    rng = swing_high - swing_low
    if rng < 0.5:
        return {"in_ote": False, "ote_direction": None}

    # Buy OTE — bullish retracement levels
    ote_618 = round(swing_high - rng * 0.618, 2)
    ote_705 = round(swing_high - rng * 0.705, 2)  # sweet spot
    ote_79  = round(swing_high - rng * 0.79,  2)

    # Sell OTE — bearish retracement levels
    sell_ote_618 = round(swing_low + rng * 0.618, 2)
    sell_ote_705 = round(swing_low + rng * 0.705, 2)
    sell_ote_79  = round(swing_low + rng * 0.79,  2)

    in_buy_ote  = ote_79  <= current <= ote_618
    in_sell_ote = sell_ote_618 <= current <= sell_ote_79

    direction = "buy" if in_buy_ote else ("sell" if in_sell_ote else None)

    return {
        "in_ote":           in_buy_ote or in_sell_ote,
        "in_buy_ote":       in_buy_ote,
        "in_sell_ote":      in_sell_ote,
        "ote_direction":    direction,
        "ote_618":          ote_618,
        "ote_705":          ote_705,
        "ote_79":           ote_79,
        "sell_ote_618":     sell_ote_618,
        "sell_ote_705":     sell_ote_705,
        "sell_ote_79":      sell_ote_79,
        "swing_high":       round(swing_high, 2),
        "swing_low":        round(swing_low, 2),
    }


# ------------------------------------------------------------
# PATTERN DETECTION
# ------------------------------------------------------------

def detect_double_top_bottom(df, lookback=50):
    """
    Detect Double Top and Double Bottom patterns.
    These are liquidity trap setups.
    """
    patterns = []

    if df is None or len(df) < lookback:
        return patterns

    recent = df.iloc[-lookback:].reset_index(drop=True)
    highs  = recent["high"].values
    lows   = recent["low"].values

    tolerance = 0.001  # 0.1% tolerance — tighter to avoid noise on gold

    # Find swing highs for double top
    swing_highs = []
    for i in range(3, len(highs) - 3):
        if highs[i] >= highs[i-1] and highs[i] >= highs[i-2] and highs[i] >= highs[i-3] and \
           highs[i] >= highs[i+1] and highs[i] >= highs[i+2] and highs[i] >= highs[i+3]:
            swing_highs.append({"index": i, "price": highs[i]})

    # Double top check — minimum 10 candles apart to be meaningful
    for i in range(len(swing_highs) - 1):
        sh1 = swing_highs[i]
        sh2 = swing_highs[i + 1]
        diff = abs(sh1["price"] - sh2["price"]) / sh1["price"]
        if diff <= tolerance and sh2["index"] - sh1["index"] >= 10:
            patterns.append({
                "type":    "double_top",
                "signal":  "bearish",
                "level1":  round(float(sh1["price"]), 2),
                "level2":  round(float(sh2["price"]), 2),
                "index1":  sh1["index"],
                "index2":  sh2["index"],
                "neckline": round(float(min(lows[sh1["index"]:sh2["index"]+1])), 2)
            })

    # Find swing lows for double bottom
    swing_lows = []
    for i in range(3, len(lows) - 3):
        if lows[i] <= lows[i-1] and lows[i] <= lows[i-2] and lows[i] <= lows[i-3] and \
           lows[i] <= lows[i+1] and lows[i] <= lows[i+2] and lows[i] <= lows[i+3]:
            swing_lows.append({"index": i, "price": lows[i]})

    # Double bottom check — minimum 10 candles apart to be meaningful
    for i in range(len(swing_lows) - 1):
        sl1 = swing_lows[i]
        sl2 = swing_lows[i + 1]
        diff = abs(sl1["price"] - sl2["price"]) / sl1["price"]
        if diff <= tolerance and sl2["index"] - sl1["index"] >= 10:
            patterns.append({
                "type":    "double_bottom",
                "signal":  "bullish",
                "level1":  round(float(sl1["price"]), 2),
                "level2":  round(float(sl2["price"]), 2),
                "index1":  sl1["index"],
                "index2":  sl2["index"],
                "neckline": round(float(max(highs[sl1["index"]:sl2["index"]+1])), 2)
            })

    return patterns


def detect_candlestick_patterns(df):
    """
    Detect key candlestick confirmation patterns.
    Used to confirm entries at OBs, FVGs, and key levels.
    """
    if df is None or len(df) < 3:
        return []

    patterns = []
    last     = df.iloc[-1]
    prev     = df.iloc[-2]

    body_size = abs(last["close"] - last["open"])
    candle_range = last["high"] - last["low"]
    upper_wick = last["high"] - max(last["close"], last["open"])
    lower_wick = min(last["close"], last["open"]) - last["low"]

    if candle_range == 0:
        return patterns

    # Pin Bar / Hammer (bullish)
    if (lower_wick > body_size * 2 and
        lower_wick > upper_wick * 2 and
        last["close"] > last["open"]):
        patterns.append({
            "type":   "hammer",
            "signal": "bullish",
            "index":  len(df) - 1,
            "time":   last["time"]
        })

    # Shooting Star (bearish)
    if (upper_wick > body_size * 2 and
        upper_wick > lower_wick * 2 and
        last["close"] < last["open"]):
        patterns.append({
            "type":   "shooting_star",
            "signal": "bearish",
            "index":  len(df) - 1,
            "time":   last["time"]
        })

    # Bullish Engulfing
    if (last["close"] > last["open"] and
        prev["close"] < prev["open"] and
        last["close"] > prev["open"] and
        last["open"]  < prev["close"]):
        patterns.append({
            "type":   "bullish_engulfing",
            "signal": "bullish",
            "index":  len(df) - 1,
            "time":   last["time"]
        })

    # Bearish Engulfing
    if (last["close"] < last["open"] and
        prev["close"] > prev["open"] and
        last["close"] < prev["open"] and
        last["open"]  > prev["close"]):
        patterns.append({
            "type":   "bearish_engulfing",
            "signal": "bearish",
            "index":  len(df) - 1,
            "time":   last["time"]
        })

    # Doji
    if body_size <= candle_range * 0.1:
        patterns.append({
            "type":   "doji",
            "signal": "indecision",
            "index":  len(df) - 1,
            "time":   last["time"]
        })

    return patterns


# ------------------------------------------------------------
# PRICE AT ZONE CHECK
# ------------------------------------------------------------

def price_at_zone(current_price, zones, proximity=5.0):
    """
    Check if current price is inside or near any zone.
    Returns the zone if price is at it, None otherwise.
    """
    if current_price is None or not zones:
        return None

    for zone in zones:
        top    = zone.get("top",    0)
        bottom = zone.get("bottom", 0)

        # Price inside zone
        if bottom - proximity <= current_price <= top + proximity:
            return zone

    return None


# ------------------------------------------------------------
# MAIN ENGINE FUNCTION
# ------------------------------------------------------------

def run(candle_store, b2=None):
    """
    Run full Entry Engine.
    Detects all entry zones across M15 and H1.
    """
    df_m15 = candle_store.get_closed("M15")
    df_h1  = candle_store.get_closed("H1")
    df_m5  = candle_store.get_closed("M5")

    price_info    = candle_store.get_price()
    current_price = price_info["bid"] if price_info else None

    # ATR for OB size filtering
    atr_m15 = get_atr(df_m15)
    atr_h1  = get_atr(df_h1)

    # --- Order Blocks ---
    bull_obs_m15, bear_obs_m15 = find_order_blocks(df_m15, atr=atr_m15)
    bull_obs_h1,  bear_obs_h1  = find_order_blocks(df_h1,  atr=atr_h1)

    # Valid OBs only
    valid_bull_obs = [ob for ob in bull_obs_m15 + bull_obs_h1 if ob["valid"]]
    valid_bear_obs = [ob for ob in bear_obs_m15 + bear_obs_h1 if ob["valid"]]

    # --- FVGs ---
    bull_fvgs_m15, bear_fvgs_m15 = find_fvgs(df_m15)
    bull_fvgs_h1,  bear_fvgs_h1  = find_fvgs(df_h1)

    valid_bull_fvgs = [f for f in bull_fvgs_m15 + bull_fvgs_h1 if f["valid"]]
    valid_bear_fvgs = [f for f in bear_fvgs_m15 + bear_fvgs_h1 if f["valid"]]

    # --- Breaker Blocks ---
    bull_breakers, bear_breakers = find_breaker_blocks(
        bull_obs_m15 + bull_obs_h1,
        bear_obs_m15 + bear_obs_h1
    )

    # --- Fibonacci ---
    # Extract confirmed swing anchors from B2 (BOS/CHOCH points)
    # These give accurate fibs vs arbitrary rolling window
    b2_sh_m15 = b2_sh_h4 = b2_sl_m15 = b2_sl_h4 = None
    if b2:
        m15_data = b2.get("timeframes", {}).get("M15", {})
        h4_data  = b2.get("timeframes", {}).get("H4",  {})
        last_sh_m15 = m15_data.get("last_sh")
        last_sl_m15 = m15_data.get("last_sl")
        last_sh_h4  = h4_data.get("last_sh")
        last_sl_h4  = h4_data.get("last_sl")
        if last_sh_m15: b2_sh_m15 = float(last_sh_m15["price"]) if isinstance(last_sh_m15, dict) else float(last_sh_m15)
        if last_sl_m15: b2_sl_m15 = float(last_sl_m15["price"]) if isinstance(last_sl_m15, dict) else float(last_sl_m15)
        if last_sh_h4:  b2_sh_h4  = float(last_sh_h4["price"])  if isinstance(last_sh_h4,  dict) else float(last_sh_h4)
        if last_sl_h4:  b2_sl_h4  = float(last_sl_h4["price"])  if isinstance(last_sl_h4,  dict) else float(last_sl_h4)

    df_h4 = candle_store.get_closed("H4")

    # M15 fibs — use B2 confirmed swings, fall back to PDH/PDL (never rolling window)
    # PDH/PDL are always available and more meaningful than arbitrary rolling max/min
    if b2_sh_m15 is None or b2_sl_m15 is None:
        # Try to get PDH/PDL from the dataframe as better anchors than rolling window
        if df_m15 is not None and len(df_m15) >= 2:
            # Use recent significant swing: last 20 candles high/low
            # Better than 50-candle rolling but not as good as confirmed BOS swing
            recent_20 = df_m15.iloc[-20:]
            b2_sh_m15 = b2_sh_m15 or float(recent_20["high"].max())
            b2_sl_m15 = b2_sl_m15 or float(recent_20["low"].min())

    fibs_m15, fib_direction = get_recent_fibonacci(df_m15, b2_sh_m15, b2_sl_m15)
    golden_fibs = [f for f in fibs_m15 if f["is_golden"]]

    # H4 fibs — same approach
    if b2_sh_h4 is None or b2_sl_h4 is None:
        if df_h4 is not None and len(df_h4) >= 2:
            recent_h4_20 = df_h4.iloc[-20:]
            b2_sh_h4 = b2_sh_h4 or float(recent_h4_20["high"].max())
            b2_sl_h4 = b2_sl_h4 or float(recent_h4_20["low"].min())

    fibs_h4, fib_direction_h4 = get_recent_fibonacci(df_h4, b2_sh_h4, b2_sl_h4)
    golden_fibs_h4 = [f for f in fibs_h4 if f["is_golden"]]

    # --- Patterns ---
    patterns_m15 = detect_double_top_bottom(df_m15)
    patterns_m5  = detect_double_top_bottom(df_m5)
    candle_patterns = detect_candlestick_patterns(df_m5)

    all_patterns = patterns_m15 + patterns_m5

    # --- OTE Zone detection — anchored to B2 swings ---
    ote_m15 = detect_ote_zone(df_m15, b2_sh_m15, b2_sl_m15)
    ote_h1  = detect_ote_zone(df_h1,  b2_sh_m15, b2_sl_m15)  # H1 uses M15 anchors (more precise)
    ote_h4  = detect_ote_zone(df_h4,  b2_sh_h4,  b2_sl_h4)
    in_ote  = ote_m15["in_ote"] or ote_h1["in_ote"]
    ote_direction = ote_m15["ote_direction"] or ote_h1["ote_direction"]

    # --- Check if price is at any zone ---
    at_bull_ob      = price_at_zone(current_price, valid_bull_obs)
    at_bear_ob      = price_at_zone(current_price, valid_bear_obs)
    at_bull_fvg     = price_at_zone(current_price, valid_bull_fvgs)
    at_bear_fvg     = price_at_zone(current_price, valid_bear_fvgs)
    at_bull_breaker = price_at_zone(current_price, bull_breakers)
    at_bear_breaker = price_at_zone(current_price, bear_breakers)

    price_at_entry_zone = any([
        at_bull_ob, at_bear_ob,
        at_bull_fvg, at_bear_fvg,
        at_bull_breaker, at_bear_breaker
    ])

    # --- Determine entry bias ---
    bull_entry_score = 0
    bear_entry_score = 0

    if at_bull_ob:      bull_entry_score += 30
    if at_bear_ob:      bear_entry_score += 30
    if at_bull_fvg:     bull_entry_score += 25
    if at_bear_fvg:     bear_entry_score += 25
    if at_bull_breaker: bull_entry_score += 20
    if at_bear_breaker: bear_entry_score += 20

    for cp in candle_patterns:
        if cp["signal"] == "bullish":
            bull_entry_score += 15
        elif cp["signal"] == "bearish":
            bear_entry_score += 15

    for p in all_patterns:
        if p["signal"] == "bullish":
            bull_entry_score += 10
        elif p["signal"] == "bearish":
            bear_entry_score += 10

    if bull_entry_score > bear_entry_score:
        entry_bias = "bullish"
    elif bear_entry_score > bull_entry_score:
        entry_bias = "bearish"
    else:
        entry_bias = "neutral"

    # --- Engine Score ---
    score = max(bull_entry_score, bear_entry_score)
    if in_ote:
        score = min(score + 20, 100)  # OTE = high probability zone bonus
    score = min(score, 100)

    return {
        # Order Blocks
        "bullish_obs":       valid_bull_obs[:3],
        "bearish_obs":       valid_bear_obs[:3],
        "bull_ob_count":     len(valid_bull_obs),
        "bear_ob_count":     len(valid_bear_obs),

        # FVGs
        "bullish_fvgs":      valid_bull_fvgs[:3],
        "bearish_fvgs":      valid_bear_fvgs[:3],
        "bull_fvg_count":    len(valid_bull_fvgs),
        "bear_fvg_count":    len(valid_bear_fvgs),

        # Breaker Blocks
        "bull_breakers":     bull_breakers[:2],
        "bear_breakers":     bear_breakers[:2],

        # Fibonacci
        "fibs":              fibs_m15,
        "golden_fibs":       golden_fibs,
        "fibs_h4":           fibs_h4,
        "golden_fibs_h4":    golden_fibs_h4,
        "fib_direction_h4":  fib_direction_h4,
        "ote_h4":            ote_h4,
        "fib_direction":     fib_direction,

        # Patterns
        "patterns":          all_patterns,
        "candle_patterns":   candle_patterns,
        "pattern_count":     len(all_patterns),

        # Price at zone
        "at_bull_ob":        at_bull_ob,
        "at_bear_ob":        at_bear_ob,
        "at_bull_fvg":       at_bull_fvg,
        "at_bear_fvg":       at_bear_fvg,
        "at_bull_breaker":   at_bull_breaker,
        "at_bear_breaker":   at_bear_breaker,
        "price_at_entry_zone": price_at_entry_zone,

        # Entry bias
        "entry_bias":        entry_bias,
        "bull_entry_score":  bull_entry_score,
        "bear_entry_score":  bear_entry_score,
        "engine_score":      score,

        # OTE zone
        "ote_m15":           ote_m15,
        "ote_h1":            ote_h1,
        "in_ote":            in_ote,
        "ote_direction":     ote_direction,
    }


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------

if __name__ == "__main__":
    import MetaTrader5 as mt5
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data.candle_store import store

    print("Testing Box 7 — Entry Engine")
    print("=" * 50)

    mt5.initialize()
    store.refresh()

    result = run(store)

    print(f"\nOrder Blocks:")
    print(f"  Bullish OBs: {result['bull_ob_count']}")
    print(f"  Bearish OBs: {result['bear_ob_count']}")
    if result["bullish_obs"]:
        ob = result["bullish_obs"][0]
        print(f"  Latest Bull OB: {ob['bottom']} - {ob['top']}")
    if result["bearish_obs"]:
        ob = result["bearish_obs"][0]
        print(f"  Latest Bear OB: {ob['bottom']} - {ob['top']}")

    print(f"\nFair Value Gaps:")
    print(f"  Bullish FVGs: {result['bull_fvg_count']}")
    print(f"  Bearish FVGs: {result['bear_fvg_count']}")
    if result["bullish_fvgs"]:
        fvg = result["bullish_fvgs"][0]
        print(f"  Latest Bull FVG: {fvg['bottom']} - {fvg['top']} (size: {fvg['size']})")

    print(f"\nBreaker Blocks:")
    print(f"  Bull Breakers: {len(result['bull_breakers'])}")
    print(f"  Bear Breakers: {len(result['bear_breakers'])}")

    print(f"\nFibonacci Direction: {result['fib_direction']}")
    print(f"Golden Zone Fibs:")
    for f in result["golden_fibs"]:
        print(f"  {f['label']}: {f['level']}")

    print(f"\nPatterns Detected: {result['pattern_count']}")
    for p in result["patterns"]:
        print(f"  {p['type']} ({p['signal']})")

    print(f"\nCandlestick Patterns:")
    for cp in result["candle_patterns"]:
        print(f"  {cp['type']} ({cp['signal']})")

    print(f"\nPrice at Entry Zone: {result['price_at_entry_zone']}")
    print(f"At Bull OB:  {result['at_bull_ob'] is not None}")
    print(f"At Bear OB:  {result['at_bear_ob'] is not None}")
    print(f"At Bull FVG: {result['at_bull_fvg'] is not None}")
    print(f"At Bear FVG: {result['at_bear_fvg'] is not None}")

    print(f"\nEntry Bias:  {result['entry_bias'].upper()}")
    print(f"Bull Score:  {result['bull_entry_score']}")
    print(f"Bear Score:  {result['bear_entry_score']}")
    print(f"Engine Score: {result['engine_score']}/100")

    mt5.shutdown()
    print("\nBox 7 Test PASSED ✓")
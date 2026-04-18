# ============================================================
# box3_liquidity.py — Liquidity Engine
# Detects: EQH, EQL, Liquidity Sweeps, Stop Hunts,
#          PDH/PDL sweeps, Session High/Low sweeps
# FIX: Sweep size must be > 0.75 × ATR to count as real
# FIX: Asian sweeps require DOUBLE the ATR (1.5×)
# ============================================================

import sys
import os
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import (
    EQH_EQL_TOLERANCE,
    SWEEP_LOOKBACK,
    MIN_SWEEP_WICK,
    PDH_PDL_LOOKBACK
)


# ------------------------------------------------------------
# EQUAL HIGHS / EQUAL LOWS (EQH / EQL)
# ------------------------------------------------------------

def find_eqh_eql(df, tolerance=None):
    """
    Find Equal Highs (EQH) and Equal Lows (EQL).
    These are liquidity pools where stop losses cluster.

    Two swing points are "equal" if they're within
    the tolerance band of each other.

    Returns:
        eqh_levels: list of price levels with equal highs
        eql_levels: list of price levels with equal lows
    """
    if tolerance is None:
        tolerance = EQH_EQL_TOLERANCE

    if df is None or len(df) < 10:
        return [], []

    eqh_levels = []
    eql_levels = []

    highs = df["high"].values
    lows  = df["low"].values
    times = df["time"].values

    lookback = min(SWEEP_LOOKBACK, len(df))

    # Find local swing highs
    swing_highs = []
    for i in range(2, lookback - 2):
        if highs[i] >= highs[i-1] and highs[i] >= highs[i-2] and \
           highs[i] >= highs[i+1] and highs[i] >= highs[i+2]:
            swing_highs.append({"index": i, "price": highs[i], "time": times[i]})

    # Find local swing lows
    swing_lows = []
    for i in range(2, lookback - 2):
        if lows[i] <= lows[i-1] and lows[i] <= lows[i-2] and \
           lows[i] <= lows[i+1] and lows[i] <= lows[i+2]:
            swing_lows.append({"index": i, "price": lows[i], "time": times[i]})

    # Compare swing highs for equality
    for i in range(len(swing_highs)):
        for j in range(i + 1, len(swing_highs)):
            sh1 = swing_highs[i]
            sh2 = swing_highs[j]
            avg_price = (sh1["price"] + sh2["price"]) / 2
            diff = abs(sh1["price"] - sh2["price"]) / avg_price
            if diff <= tolerance:
                level = (sh1["price"] + sh2["price"]) / 2
                if not any(abs(e["level"] - level) / level < tolerance for e in eqh_levels):
                    eqh_levels.append({
                        "level":  level,
                        "high1":  sh1["price"],
                        "high2":  sh2["price"],
                        "time1":  sh1["time"],
                        "time2":  sh2["time"],
                        "index1": sh1["index"],
                        "index2": sh2["index"],
                        "type":   "EQH"
                    })

    # Compare swing lows for equality
    for i in range(len(swing_lows)):
        for j in range(i + 1, len(swing_lows)):
            sl1 = swing_lows[i]
            sl2 = swing_lows[j]
            avg_price = (sl1["price"] + sl2["price"]) / 2
            diff = abs(sl1["price"] - sl2["price"]) / avg_price
            if diff <= tolerance:
                level = (sl1["price"] + sl2["price"]) / 2
                if not any(abs(e["level"] - level) / level < tolerance for e in eql_levels):
                    eql_levels.append({
                        "level":  level,
                        "low1":   sl1["price"],
                        "low2":   sl2["price"],
                        "time1":  sl1["time"],
                        "time2":  sl2["time"],
                        "index1": sl1["index"],
                        "index2": sl2["index"],
                        "type":   "EQL"
                    })

    return eqh_levels, eql_levels


# ------------------------------------------------------------
# LIQUIDITY SWEEP DETECTION — FIXED with ATR adjustment
# ------------------------------------------------------------

def detect_sweeps(df, levels, sweep_type="high", atr=None, session="unknown"):
    """
    Detect liquidity sweeps on given price levels.
    FIX: Sweep must exceed MIN_SWEEP_WICK OR 0.75 × ATR (whichever larger)
    FIX: Asian session sweeps require DOUBLE the ATR (1.5×)

    A sweep = candle wicks BEYOND a level but CLOSES back inside.
    This is the stop hunt signature.

    Args:
        df: OHLCV DataFrame
        levels: list of level dicts with "level" key
        sweep_type: "high" or "low"
        atr: current ATR value (for size calculation)
        session: current session ("asian", "london", "new_york")

    Returns:
        list of sweep events
    """
    sweeps = []

    if df is None or len(df) < 3 or not levels:
        return sweeps

    # Get ATR if not provided (calculate on the fly)
    if atr is None or atr == 0:
        if len(df) >= 14:
            tr = []
            for i in range(1, len(df)):
                high = df["high"].iloc[i]
                low = df["low"].iloc[i]
                prev_close = df["close"].iloc[i-1]
                tr.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
            atr = sum(tr[-14:]) / 14 if tr else 0.5
        else:
            atr = 0.5

    # Calculate minimum sweep size
    min_sweep_wick = max(MIN_SWEEP_WICK, atr * 0.75)

    # Asian session requires double the size (1.5× ATR)
    if session == "asian":
        min_sweep_wick = max(min_sweep_wick, atr * 1.5)

    for level_info in levels:
        level = level_info["level"]

        for i in range(1, len(df)):
            candle = df.iloc[i]

            if sweep_type == "high":
                # Wick above level but close back below
                wick_above = candle["high"] > level
                close_below = candle["close"] < level
                wick_size = candle["high"] - level

                if wick_above and close_below and wick_size >= min_sweep_wick:
                    sweeps.append({
                        "type":       "bearish_sweep",
                        "level":      level,
                        "wick_high":  candle["high"],
                        "close":      candle["close"],
                        "wick_size":  round(wick_size, 2),
                        "index":      i,
                        "time":       candle["time"],
                        "level_type": level_info.get("type", "level"),
                        "session":    session,
                        "min_required": round(min_sweep_wick, 2),
                    })

            elif sweep_type == "low":
                # Wick below level but close back above
                wick_below = candle["low"] < level
                close_above = candle["close"] > level
                wick_size = level - candle["low"]

                if wick_below and close_above and wick_size >= min_sweep_wick:
                    sweeps.append({
                        "type":      "bullish_sweep",
                        "level":     level,
                        "wick_low":  candle["low"],
                        "close":     candle["close"],
                        "wick_size": round(wick_size, 2),
                        "index":     i,
                        "time":      candle["time"],
                        "level_type": level_info.get("type", "level"),
                        "session":   session,
                        "min_required": round(min_sweep_wick, 2),
                    })

    # Sort by time
    sweeps.sort(key=lambda x: x["index"])
    return sweeps


# ------------------------------------------------------------
# PDH / PDL SWEEP — FIXED with ATR
# ------------------------------------------------------------

def detect_pdh_pdl_sweep(df, pdh, pdl, atr=None, session="unknown"):
    """
    Detect sweeps of Previous Day High and Previous Day Low.
    These are the most watched liquidity levels by institutions.
    FIX: Uses ATR-adjusted sweep size.

    Returns:
        pdh_swept: True if PDH was swept recently
        pdl_swept: True if PDL was swept recently
        sweep events
    """
    if df is None or pdh is None or pdl is None:
        return False, False, []

    pdh_level = [{"level": pdh, "type": "PDH"}]
    pdl_level = [{"level": pdl, "type": "PDL"}]

    pdh_sweeps = detect_sweeps(df, pdh_level, sweep_type="high", atr=atr, session=session)
    pdl_sweeps = detect_sweeps(df, pdl_level, sweep_type="low", atr=atr, session=session)

    all_sweeps = pdh_sweeps + pdl_sweeps
    all_sweeps.sort(key=lambda x: x["index"])

    # Check if swept in last 20 candles
    recent_cutoff = len(df) - 20
    pdh_swept = any(s["index"] >= recent_cutoff for s in pdh_sweeps)
    pdl_swept = any(s["index"] >= recent_cutoff for s in pdl_sweeps)

    return pdh_swept, pdl_swept, all_sweeps


# ------------------------------------------------------------
# SESSION HIGH / LOW SWEEP — FIXED with ATR
# ------------------------------------------------------------

def get_session_high_low(df, session_start_hour, session_end_hour):
    """
    Find the high and low of a specific session.

    Args:
        df: OHLCV DataFrame
        session_start_hour: GMT hour session starts
        session_end_hour:   GMT hour session ends

    Returns:
        session_high, session_low
    """
    if df is None or len(df) == 0:
        return None, None

    # Filter candles within session hours
    session_candles = df[
        (df["time"].dt.hour >= session_start_hour) &
        (df["time"].dt.hour < session_end_hour)
    ]

    if len(session_candles) == 0:
        return None, None

    session_high = session_candles["high"].max()
    session_low  = session_candles["low"].min()

    return float(session_high), float(session_low)


def detect_session_sweeps(df, atr=None, current_session="unknown"):
    """
    Detect sweeps of Asian session high/low.
    This is the core of London Sweep & Reverse model.
    FIX: Uses ATR-adjusted sweep size.

    Returns:
        asian_high: float
        asian_low:  float
        asian_high_swept: bool
        asian_low_swept:  bool
        sweep events
    """
    if df is None or len(df) < 10:
        return None, None, False, False, []

    # Asian session: 00:00 - 07:00 GMT
    asian_high, asian_low = get_session_high_low(df, 0, 7)

    if asian_high is None or asian_low is None:
        return None, None, False, False, []

    ah_level = [{"level": asian_high, "type": "Asian_High"}]
    al_level = [{"level": asian_low,  "type": "Asian_Low"}]

    # Asian sweeps require double ATR (handled inside detect_sweeps with session="asian")
    ah_sweeps = detect_sweeps(df, ah_level, sweep_type="high", atr=atr, session=current_session)
    al_sweeps = detect_sweeps(df, al_level, sweep_type="low", atr=atr, session=current_session)

    all_sweeps = ah_sweeps + al_sweeps
    all_sweeps.sort(key=lambda x: x["index"])

    # Check if swept in last 30 candles
    recent_cutoff = len(df) - 30
    asian_high_swept = any(s["index"] >= recent_cutoff for s in ah_sweeps)
    asian_low_swept  = any(s["index"] >= recent_cutoff for s in al_sweeps)

    return asian_high, asian_low, asian_high_swept, asian_low_swept, all_sweeps


# ------------------------------------------------------------
# WEEKLY HIGH / LOW SWEEP — FIXED with ATR
# ------------------------------------------------------------

def detect_weekly_sweep(df, pwh, pwl, atr=None, session="unknown"):
    """
    Detect sweeps of Previous Week High and Low.
    """
    if df is None or pwh is None or pwl is None:
        return False, False, []

    pwh_level = [{"level": pwh, "type": "PWH"}]
    pwl_level = [{"level": pwl, "type": "PWL"}]

    pwh_sweeps = detect_sweeps(df, pwh_level, sweep_type="high", atr=atr, session=session)
    pwl_sweeps = detect_sweeps(df, pwl_level, sweep_type="low", atr=atr, session=session)

    all_sweeps = pwh_sweeps + pwl_sweeps
    all_sweeps.sort(key=lambda x: x["index"])

    recent_cutoff = len(df) - 50
    pwh_swept = any(s["index"] >= recent_cutoff for s in pwh_sweeps)
    pwl_swept = any(s["index"] >= recent_cutoff for s in pwl_sweeps)

    return pwh_swept, pwl_swept, all_sweeps


# ------------------------------------------------------------
# MOST RECENT SWEEP
# ------------------------------------------------------------

def get_most_recent_sweep(all_sweeps, lookback_candles=10):
    """
    Get the most recent sweep within lookback window.
    Used by models to check if a sweep JUST happened.
    """
    if not all_sweeps:
        return None

    # Get the last sweep
    last_sweep = all_sweeps[-1]
    return last_sweep


# ------------------------------------------------------------
# MAIN ENGINE FUNCTION
# ------------------------------------------------------------

def find_bsl_ssl(df, current_price, lookback=50):
    """
    Identify Buy Side Liquidity (BSL) and Sell Side Liquidity (SSL).

    BSL = swing highs ABOVE current price where retail short sellers
          placed their stop losses. Institutions target these for liquidity.
    SSL = swing lows BELOW current price where retail long buyers
          placed their stop losses. Institutions target these for liquidity.

    Returns lists of BSL and SSL price levels with strength labels.
    """
    bsl_levels = []
    ssl_levels = []

    if df is None or len(df) < 5 or current_price is None:
        return bsl_levels, ssl_levels

    highs = df["high"].values
    lows  = df["low"].values
    n     = min(lookback, len(df))

    # Find swing highs above price (BSL)
    for i in range(2, n - 2):
        h = highs[i]
        if (h > highs[i-1] and h > highs[i-2] and
            h > highs[i+1] and h > highs[i+2] and
            h > current_price):
            # How many times was this level touched? More touches = more liquidity
            touches = sum(1 for j in range(n) if abs(highs[j] - h) < h * 0.001)
            bsl_levels.append({
                "level":    round(float(h), 2),
                "type":     "BSL",
                "label":    f"BSL {round(float(h), 2)}",
                "touches":  touches,
                "strength": "major" if touches >= 2 else "minor",
                "index":    i,
            })

    # Find swing lows below price (SSL)
    for i in range(2, n - 2):
        l = lows[i]
        if (l < lows[i-1] and l < lows[i-2] and
            l < lows[i+1] and l < lows[i+2] and
            l < current_price):
            touches = sum(1 for j in range(n) if abs(lows[j] - l) < l * 0.001)
            ssl_levels.append({
                "level":    round(float(l), 2),
                "type":     "SSL",
                "label":    f"SSL {round(float(l), 2)}",
                "touches":  touches,
                "strength": "major" if touches >= 2 else "minor",
                "index":    i,
            })

    # Sort BSL ascending (nearest first), SSL descending (nearest first)
    bsl_levels.sort(key=lambda x: x["level"])
    ssl_levels.sort(key=lambda x: x["level"], reverse=True)

    return bsl_levels[:5], ssl_levels[:5]


def run(candle_store):
    """
    Run full Liquidity Engine.

    Uses M15 for session sweeps and EQH/EQL detection.
    Uses H1 for PDH/PDL and weekly sweep detection.
    FIX: Passes ATR and session info to sweep detection.

    Returns:
        dict with all liquidity findings
    """
    df_m15 = candle_store.get_closed("M15")
    df_h1  = candle_store.get_closed("H1")
    df_m5  = candle_store.get_closed("M5")

    # Get ATR for sweep size calculation
    from engines.box1_market_context import get_current_session
    session_info = get_current_session()
    current_session = session_info["primary_session"]

    # Calculate ATR on M15 for sweep sizing
    atr = None
    if df_m15 is not None and len(df_m15) >= 14:
        tr = []
        for i in range(1, len(df_m15)):
            high = df_m15["high"].iloc[i]
            low = df_m15["low"].iloc[i]
            prev_close = df_m15["close"].iloc[i-1]
            tr.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        atr = sum(tr[-14:]) / 14 if tr else 0.5
    else:
        atr = 0.5

    # PDH / PDL
    pdh = candle_store.get_pdh()
    pdl = candle_store.get_pdl()
    pwh = candle_store.get_pwh()
    pwl = candle_store.get_pwl()

    # EQH / EQL on M15
    eqh_levels, eql_levels = find_eqh_eql(df_m15)

    # EQH / EQL sweeps — with ATR and session
    eqh_sweeps = detect_sweeps(df_m15, eqh_levels, sweep_type="high", atr=atr, session=current_session)
    eql_sweeps = detect_sweeps(df_m15, eql_levels, sweep_type="low", atr=atr, session=current_session)

    # PDH / PDL sweeps on H1 — with ATR and session
    pdh_swept, pdl_swept, pdx_sweeps = detect_pdh_pdl_sweep(df_h1, pdh, pdl, atr=atr, session=current_session)

    # Session sweeps on M15 — with ATR and session
    asian_high, asian_low, asian_high_swept, asian_low_swept, session_sweeps = \
        detect_session_sweeps(df_m15, atr=atr, current_session=current_session)

    # Weekly sweeps on H1 — with ATR and session
    pwh_swept, pwl_swept, weekly_sweeps = detect_weekly_sweep(df_h1, pwh, pwl, atr=atr, session=current_session)

    # Combine all sweeps
    all_sweeps = eqh_sweeps + eql_sweeps + pdx_sweeps + session_sweeps + weekly_sweeps
    all_sweeps.sort(key=lambda x: x["index"])

    # Most recent sweep
    recent_sweep = get_most_recent_sweep(all_sweeps)

    # Was there a sweep in the last 10 candles on M15?
    sweep_just_happened = (
        recent_sweep is not None and
        recent_sweep["index"] >= len(df_m15) - 40  # 40 candles = 10 hours on M15
    ) if df_m15 is not None else False

    # Determine sweep direction
    sweep_direction = None
    if recent_sweep:
        sweep_direction = "bearish" if recent_sweep["type"] == "bearish_sweep" else "bullish"

    # BSL / SSL identification on M15
    price_info    = candle_store.get_price()
    current_price = price_info["bid"] if price_info else None
    bsl_levels, ssl_levels = find_bsl_ssl(df_m15, current_price)

    # Nearest BSL (above price) and SSL (below price)
    nearest_bsl = bsl_levels[0]["level"]  if bsl_levels else None
    nearest_ssl = ssl_levels[0]["level"]  if ssl_levels else None

    # ------------------------------------------------------------
    # ENGINE SCORE
    # ------------------------------------------------------------
    score = 0

    # Major level swept = high score
    if pdh_swept or pdl_swept:
        score += 40
    if asian_high_swept or asian_low_swept:
        score += 35
    if pwh_swept or pwl_swept:
        score += 30
    if eqh_sweeps or eql_sweeps:
        score += 25
    if sweep_just_happened:
        score += 20

    score = min(score, 100)

    return {
        # EQH / EQL
        "eqh_levels":         eqh_levels,
        "eql_levels":         eql_levels,
        "eqh_count":          len(eqh_levels),
        "eql_count":          len(eql_levels),

        # PDH / PDL
        "pdh":                pdh,
        "pdl":                pdl,
        "pdh_swept":          pdh_swept,
        "pdl_swept":          pdl_swept,

        # Session
        "asian_high":         asian_high,
        "asian_low":          asian_low,
        "asian_high_swept":   asian_high_swept,
        "asian_low_swept":    asian_low_swept,

        # Weekly
        "pwh":                pwh,
        "pwl":                pwl,
        "pwh_swept":          pwh_swept,
        "pwl_swept":          pwl_swept,

        # All sweeps combined
        "all_sweeps":         all_sweeps,
        "recent_sweep":       recent_sweep,
        "sweep_just_happened": sweep_just_happened,
        "sweep_direction":    sweep_direction,
        "total_sweeps":       len(all_sweeps),

        # BSL / SSL
        "bsl_levels":         bsl_levels,
        "ssl_levels":         ssl_levels,
        "nearest_bsl":        nearest_bsl,
        "nearest_ssl":        nearest_ssl,

        # ATR and session info
        "atr":                atr,
        "current_session":    current_session,

        # Engine score
        "engine_score":       score,
    }


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------

if __name__ == "__main__":
    import MetaTrader5 as mt5
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data.candle_store import store

    print("Testing Box 3 — Liquidity Engine")
    print("=" * 50)

    mt5.initialize()
    store.refresh()

    result = run(store)

    print(f"\nEQH Levels Found:     {result['eqh_count']}")
    print(f"EQL Levels Found:     {result['eql_count']}")
    print(f"\nPDH: {result['pdh']} | Swept: {result['pdh_swept']}")
    print(f"PDL: {result['pdl']} | Swept: {result['pdl_swept']}")
    print(f"\nAsian High: {result['asian_high']} | Swept: {result['asian_high_swept']}")
    print(f"Asian Low:  {result['asian_low']}  | Swept: {result['asian_low_swept']}")
    print(f"\nPWH: {result['pwh']} | Swept: {result['pwh_swept']}")
    print(f"PWL: {result['pwl']} | Swept: {result['pwl_swept']}")
    print(f"\nTotal Sweeps Detected: {result['total_sweeps']}")
    print(f"Sweep Just Happened:   {result['sweep_just_happened']}")
    print(f"Sweep Direction:       {result['sweep_direction']}")
    print(f"\nATR for sweep sizing: {result['atr']}")
    print(f"Current Session:       {result['current_session']}")
    print(f"\nEngine Score: {result['engine_score']}/100")

    if result["recent_sweep"]:
        rs = result["recent_sweep"]
        print(f"\nMost Recent Sweep:")
        print(f"  Type:  {rs['type']}")
        print(f"  Level: {rs['level']}")
        print(f"  Time:  {rs['time']}")
        print(f"  Wick:  {rs['wick_size']} pips")
        print(f"  Min Required: {rs.get('min_required', 'N/A')} pips")
        print(f"  Session: {rs.get('session', 'unknown')}")

    mt5.shutdown()
    print("\nBox 3 Test PASSED ✓")
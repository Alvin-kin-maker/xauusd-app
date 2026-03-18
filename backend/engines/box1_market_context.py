# ============================================================
# box1_market_context.py — Market Context Engine
# Decides if the market is worth trading right now
# Checks: Session, ATR (volatility), Spread
# ============================================================

import sys
import os
import pandas as pd
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import (
    ATR_PERIOD,
    ATR_MIN_THRESHOLD,
    ATR_HIGH_THRESHOLD,
    DEAD_MARKET_ATR,
    SPREAD_MAX_PIPS,
    SESSIONS
)


# ------------------------------------------------------------
# SESSION DETECTION
# ------------------------------------------------------------

def get_current_session(dt=None):
    """
    Detect which trading session is currently active.
    Uses GMT time.

    Returns dict with:
        active_sessions: list of active sessions
        primary_session: most important active session
        is_overlap: True if London/NY overlap active
        session_quality: "high" / "medium" / "low"
    """
    if dt is None:
        dt = datetime.utcnow()

    # Get current time as minutes since midnight (GMT)
    current_minutes = dt.hour * 60 + dt.minute

    def time_to_minutes(time_str):
        h, m = map(int, time_str.split(":"))
        return h * 60 + m

    # Session boundaries in minutes
    asian_start  = time_to_minutes(SESSIONS["asian"]["start"])
    asian_end    = time_to_minutes(SESSIONS["asian"]["end"])
    london_start = time_to_minutes(SESSIONS["london"]["start"])
    london_end   = time_to_minutes(SESSIONS["london"]["end"])
    ny_start     = time_to_minutes(SESSIONS["new_york"]["start"])
    ny_end       = time_to_minutes(SESSIONS["new_york"]["end"])
    overlap_start = time_to_minutes(SESSIONS["overlap"]["start"])
    overlap_end   = time_to_minutes(SESSIONS["overlap"]["end"])

    active_sessions = []

    # Check each session
    if asian_start <= current_minutes < asian_end:
        active_sessions.append("asian")

    if london_start <= current_minutes < london_end:
        active_sessions.append("london")

    if ny_start <= current_minutes < ny_end:
        active_sessions.append("new_york")

    # Check overlap (London + NY both active)
    is_overlap = (london_start <= current_minutes < london_end and
                  ny_start <= current_minutes < ny_end)

    if is_overlap:
        active_sessions.append("overlap")

    # Determine primary session
    if is_overlap:
        primary_session = "overlap"
    elif "new_york" in active_sessions:
        primary_session = "new_york"
    elif "london" in active_sessions:
        primary_session = "london"
    elif "asian" in active_sessions:
        primary_session = "asian"
    else:
        primary_session = "off_hours"
        active_sessions.append("off_hours")

    # Session quality for confluence scoring
    quality_map = {
        "overlap":   "high",
        "london":    "high",
        "new_york":  "high",
        "asian":     "medium",
        "off_hours": "low"
    }
    session_quality = quality_map.get(primary_session, "low")

    return {
        "active_sessions": active_sessions,
        "primary_session": primary_session,
        "is_overlap":      is_overlap,
        "session_quality": session_quality,
        "current_gmt":     dt.strftime("%H:%M"),
    }


def is_tradeable_session():
    """
    Returns True if we're in London or NY session.
    Asian session = medium quality only.
    Off hours = never trade.
    """
    session = get_current_session()
    return session["primary_session"] in ["london", "new_york", "overlap"]


# ------------------------------------------------------------
# ATR CALCULATION (Volatility)
# ------------------------------------------------------------

def calculate_atr(df, period=None):
    """
    Calculate Average True Range (ATR) using Wilder's smoothing.
    ATR tells us how much gold is moving per candle.

    Args:
        df: DataFrame with high, low, close columns
        period: ATR period (uses config default if None)

    Returns:
        float: current ATR value
    """
    if period is None:
        period = ATR_PERIOD

    if df is None or len(df) < period + 1:
        return None

    df = df.copy()

    # True Range = max of:
    # 1. Current High - Current Low
    # 2. |Current High - Previous Close|
    # 3. |Current Low  - Previous Close|
    df["prev_close"] = df["close"].shift(1)
    df["tr1"] = df["high"] - df["low"]
    df["tr2"] = (df["high"] - df["prev_close"]).abs()
    df["tr3"] = (df["low"]  - df["prev_close"]).abs()
    df["tr"]  = df[["tr1", "tr2", "tr3"]].max(axis=1)

    # Wilder's smoothing (same as RMA in Pine Script)
    atr_values = [None] * len(df)

    # Seed with simple average of first `period` TR values
    first_valid = df["tr"].dropna().index[0]
    seed_end = first_valid + period

    if seed_end >= len(df):
        return None

    seed = df["tr"].iloc[first_valid:seed_end].mean()
    atr_values[seed_end - 1] = seed

    # Apply Wilder's smoothing
    for i in range(seed_end, len(df)):
        prev_atr = atr_values[i - 1]
        if prev_atr is None:
            continue
        atr_values[i] = (prev_atr * (period - 1) + df["tr"].iloc[i]) / period

    # Return most recent ATR value
    current_atr = atr_values[-1]
    return round(current_atr, 5) if current_atr is not None else None


def get_volatility_regime(atr_value):
    """
    Classify current volatility based on ATR.

    Returns:
        "dead"   — market not moving, skip
        "low"    — below average movement
        "normal" — good trading conditions
        "high"   — elevated volatility, be careful with SL
    """
    if atr_value is None:
        return "unknown"

    if atr_value < DEAD_MARKET_ATR:
        return "dead"
    elif atr_value < ATR_MIN_THRESHOLD:
        return "low"
    elif atr_value < ATR_HIGH_THRESHOLD:
        return "normal"
    else:
        return "high"


# ------------------------------------------------------------
# SPREAD CHECK
# ------------------------------------------------------------

def check_spread(spread_value):
    """
    Check if current spread is acceptable for trading.

    Args:
        spread_value: spread in pips

    Returns:
        dict with is_acceptable and reason
    """
    if spread_value is None:
        return {
            "is_acceptable": False,
            "spread_pips":   None,
            "reason":        "Could not read spread"
        }

    is_acceptable = spread_value <= SPREAD_MAX_PIPS

    return {
        "is_acceptable": is_acceptable,
        "spread_pips":   spread_value,
        "reason":        "Spread OK" if is_acceptable else f"Spread too wide: {spread_value} pips (max {SPREAD_MAX_PIPS})"
    }


# ------------------------------------------------------------
# MAIN ENGINE FUNCTION
# ------------------------------------------------------------

def run(candle_store):
    """
    Run the full Market Context Engine.

    Args:
        candle_store: CandleStore instance with loaded data

    Returns:
        dict with full market context output
    """
    # Get H1 candles for ATR calculation
    df_h1 = candle_store.get_closed("H1")

    # Calculate ATR on H1
    atr = calculate_atr(df_h1, ATR_PERIOD)
    volatility_regime = get_volatility_regime(atr)

    # Get current session
    session_info = get_current_session()

    # Get spread
    price = candle_store.get_price()
    spread_pips = None
    if price is not None:
        spread_pips = round(price["spread"] / 0.1, 2)
    spread_info = check_spread(spread_pips)

    # Decision — is market worth trading?
    is_tradeable = (
        is_tradeable_session() and
        volatility_regime not in ["dead", "unknown"] and
        spread_info["is_acceptable"]
    )

    # Confluence score contribution (0-100 for this engine)
    session_scores = {
        "overlap":   100,
        "london":    90,
        "new_york":  90,
        "asian":     50,
        "off_hours": 0
    }
    volatility_scores = {
        "high":    80,
        "normal":  100,
        "low":     50,
        "dead":    0,
        "unknown": 0
    }

    session_score    = session_scores.get(session_info["primary_session"], 0)
    volatility_score = volatility_scores.get(volatility_regime, 0)
    spread_score     = 100 if spread_info["is_acceptable"] else 0

    # Weighted score for this engine
    engine_score = int((session_score * 0.5) + (volatility_score * 0.4) + (spread_score * 0.1))

    result = {
        # Session
        "primary_session":  session_info["primary_session"],
        "active_sessions":  session_info["active_sessions"],
        "is_overlap":       session_info["is_overlap"],
        "session_quality":  session_info["session_quality"],
        "current_gmt":      session_info["current_gmt"],

        # Volatility
        "atr":               atr,
        "volatility_regime": volatility_regime,

        # Spread
        "spread_pips":       spread_pips,
        "spread_acceptable": spread_info["is_acceptable"],

        # Final decision
        "is_tradeable":      is_tradeable,
        "engine_score":      engine_score,

        # Reason if not tradeable
        "reason": (
            "Market conditions good ✓" if is_tradeable else
            f"Not tradeable — Session: {session_info['primary_session']}, "
            f"Volatility: {volatility_regime}, "
            f"Spread: {spread_info['reason']}"
        )
    }

    return result


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------

if __name__ == "__main__":
    import MetaTrader5 as mt5
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data.candle_store import store

    print("Testing Box 1 — Market Context Engine")
    print("=" * 50)

    mt5.initialize()
    store.refresh()

    result = run(store)

    print(f"Session:       {result['primary_session']} ({result['current_gmt']} GMT)")
    print(f"Active:        {result['active_sessions']}")
    print(f"Overlap:       {result['is_overlap']}")
    print(f"ATR:           {result['atr']}")
    print(f"Volatility:    {result['volatility_regime']}")
    print(f"Spread:        {result['spread_pips']} pips")
    print(f"Tradeable:     {result['is_tradeable']}")
    print(f"Engine Score:  {result['engine_score']}/100")
    print(f"Reason:        {result['reason']}")

    mt5.shutdown()
    print("\nBox 1 Test PASSED ✓")
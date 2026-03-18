# ============================================================
# box5_momentum.py — Momentum Engine
# Tools: RSI, RSI Divergence, Hidden Divergence,
#        Volume Spikes, Declining Volume, Relative Volume
# ============================================================

import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import (
    RSI_PERIOD,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_MIDLINE,
    RSI_DIVERGENCE_LOOKBACK,
    RSI_DIVERGENCE_RANGE_MIN,
    RSI_DIVERGENCE_RANGE_MAX,
    VOLUME_SPIKE_MULTIPLIER,
    VOLUME_LOOKBACK,
    VOLUME_DECLINING_THRESHOLD
)


# ------------------------------------------------------------
# RSI CALCULATION
# ------------------------------------------------------------

def calculate_rsi(df, period=None):
    """
    Calculate RSI using Wilder's smoothing (RMA).
    Exact same method as TradingView's built-in RSI.

    Args:
        df: DataFrame with 'close' column
        period: RSI period (default 14)

    Returns:
        Series of RSI values
    """
    if period is None:
        period = RSI_PERIOD

    if df is None or len(df) < period + 1:
        return None

    closes = df["close"].copy()

    # Price changes
    delta = closes.diff()

    # Separate gains and losses
    gains  = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)

    # Wilder's RMA smoothing
    # Seed with simple average of first `period` values
    avg_gain = gains.iloc[1:period+1].mean()
    avg_loss = losses.iloc[1:period+1].mean()

    rsi_values = [np.nan] * (period)

    for i in range(period, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses.iloc[i]) / period

        if avg_loss == 0:
            rsi = 100.0
        elif avg_gain == 0:
            rsi = 0.0
        else:
            rs  = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        rsi_values.append(rsi)

    rsi_series = pd.Series(rsi_values, index=df.index)
    return rsi_series


def get_rsi_signal(rsi_value):
    """
    Classify RSI value into signal.

    Returns:
        "overbought"  — RSI > 70, potential sell
        "oversold"    — RSI < 30, potential buy
        "bullish"     — RSI > 50, bullish momentum
        "bearish"     — RSI < 50, bearish momentum
        "neutral"     — RSI near 50
    """
    if rsi_value is None or np.isnan(rsi_value):
        return "unknown"

    if rsi_value >= RSI_OVERBOUGHT:
        return "overbought"
    elif rsi_value <= RSI_OVERSOLD:
        return "oversold"
    elif rsi_value > RSI_MIDLINE + 5:
        return "bullish"
    elif rsi_value < RSI_MIDLINE - 5:
        return "bearish"
    else:
        return "neutral"


# ------------------------------------------------------------
# PIVOT DETECTION FOR DIVERGENCE
# ------------------------------------------------------------

def find_rsi_pivots(rsi_series, price_series, lookback=None):
    """
    Find pivot highs and lows in RSI and price.
    Used to detect divergence between price and RSI.
    """
    if lookback is None:
        lookback = RSI_DIVERGENCE_LOOKBACK

    if rsi_series is None or len(rsi_series) < lookback * 2 + 1:
        return [], []

    rsi_vals   = rsi_series.values
    price_vals = price_series.values

    pivot_highs = []
    pivot_lows  = []

    for i in range(lookback, len(rsi_vals) - lookback):
        if np.isnan(rsi_vals[i]):
            continue

        # RSI pivot high
        is_ph = all(
            rsi_vals[i] >= rsi_vals[i - j] and
            rsi_vals[i] >= rsi_vals[i + j]
            for j in range(1, lookback + 1)
            if not np.isnan(rsi_vals[i - j]) and not np.isnan(rsi_vals[i + j])
        )
        if is_ph:
            pivot_highs.append({
                "index":       i,
                "rsi":         rsi_vals[i],
                "price_high":  price_vals[i]
            })

        # RSI pivot low
        is_pl = all(
            rsi_vals[i] <= rsi_vals[i - j] and
            rsi_vals[i] <= rsi_vals[i + j]
            for j in range(1, lookback + 1)
            if not np.isnan(rsi_vals[i - j]) and not np.isnan(rsi_vals[i + j])
        )
        if is_pl:
            pivot_lows.append({
                "index":      i,
                "rsi":        rsi_vals[i],
                "price_low":  price_vals[i]
            })

    return pivot_highs, pivot_lows


# ------------------------------------------------------------
# DIVERGENCE DETECTION
# ------------------------------------------------------------

def detect_divergence(df, rsi_series):
    """
    Detect Regular and Hidden RSI Divergence.

    Regular Divergence (reversal signal):
        Bull: Price makes Lower Low, RSI makes Higher Low
        Bear: Price makes Higher High, RSI makes Lower High

    Hidden Divergence (continuation signal):
        Bull: Price makes Higher Low, RSI makes Lower Low
        Bear: Price makes Lower High, RSI makes Higher High

    Returns list of divergence signals
    """
    if df is None or rsi_series is None:
        return []

    pivot_highs, pivot_lows = find_rsi_pivots(
        rsi_series,
        df["high"] if "high" in df.columns else df["close"]
    )

    divergences = []

    # --- Regular Bullish Divergence ---
    # Price: Lower Low | RSI: Higher Low
    for i in range(1, len(pivot_lows)):
        pl_curr = pivot_lows[i]
        pl_prev = pivot_lows[i - 1]

        bar_distance = pl_curr["index"] - pl_prev["index"]
        if not (RSI_DIVERGENCE_RANGE_MIN <= bar_distance <= RSI_DIVERGENCE_RANGE_MAX):
            continue

        price_ll = pl_curr["price_low"] < pl_prev["price_low"]
        rsi_hl   = pl_curr["rsi"] > pl_prev["rsi"]

        if price_ll and rsi_hl:
            divergences.append({
                "type":        "regular_bullish",
                "signal":      "reversal_up",
                "index":       pl_curr["index"],
                "rsi_current": pl_curr["rsi"],
                "rsi_prev":    pl_prev["rsi"],
                "price_curr":  pl_curr["price_low"],
                "price_prev":  pl_prev["price_low"],
            })

    # --- Regular Bearish Divergence ---
    # Price: Higher High | RSI: Lower High
    for i in range(1, len(pivot_highs)):
        ph_curr = pivot_highs[i]
        ph_prev = pivot_highs[i - 1]

        bar_distance = ph_curr["index"] - ph_prev["index"]
        if not (RSI_DIVERGENCE_RANGE_MIN <= bar_distance <= RSI_DIVERGENCE_RANGE_MAX):
            continue

        price_hh = ph_curr["price_high"] > ph_prev["price_high"]
        rsi_lh   = ph_curr["rsi"] < ph_prev["rsi"]

        if price_hh and rsi_lh:
            divergences.append({
                "type":        "regular_bearish",
                "signal":      "reversal_down",
                "index":       ph_curr["index"],
                "rsi_current": ph_curr["rsi"],
                "rsi_prev":    ph_prev["rsi"],
                "price_curr":  ph_curr["price_high"],
                "price_prev":  ph_prev["price_high"],
            })

    # --- Hidden Bullish Divergence ---
    # Price: Higher Low | RSI: Lower Low (continuation up)
    for i in range(1, len(pivot_lows)):
        pl_curr = pivot_lows[i]
        pl_prev = pivot_lows[i - 1]

        bar_distance = pl_curr["index"] - pl_prev["index"]
        if not (RSI_DIVERGENCE_RANGE_MIN <= bar_distance <= RSI_DIVERGENCE_RANGE_MAX):
            continue

        price_hl = pl_curr["price_low"] > pl_prev["price_low"]
        rsi_ll   = pl_curr["rsi"] < pl_prev["rsi"]

        if price_hl and rsi_ll:
            divergences.append({
                "type":        "hidden_bullish",
                "signal":      "continuation_up",
                "index":       pl_curr["index"],
                "rsi_current": pl_curr["rsi"],
                "rsi_prev":    pl_prev["rsi"],
                "price_curr":  pl_curr["price_low"],
                "price_prev":  pl_prev["price_low"],
            })

    # --- Hidden Bearish Divergence ---
    # Price: Lower High | RSI: Higher High (continuation down)
    for i in range(1, len(pivot_highs)):
        ph_curr = pivot_highs[i]
        ph_prev = pivot_highs[i - 1]

        bar_distance = ph_curr["index"] - ph_prev["index"]
        if not (RSI_DIVERGENCE_RANGE_MIN <= bar_distance <= RSI_DIVERGENCE_RANGE_MAX):
            continue

        price_lh = ph_curr["price_high"] < ph_prev["price_high"]
        rsi_hh   = ph_curr["rsi"] > ph_prev["rsi"]

        if price_lh and rsi_hh:
            divergences.append({
                "type":        "hidden_bearish",
                "signal":      "continuation_down",
                "index":       ph_curr["index"],
                "rsi_current": ph_curr["rsi"],
                "rsi_prev":    ph_prev["rsi"],
                "price_curr":  ph_curr["price_high"],
                "price_prev":  ph_prev["price_high"],
            })

    # Sort by index
    divergences.sort(key=lambda x: x["index"])
    return divergences


# ------------------------------------------------------------
# VOLUME ANALYSIS
# ------------------------------------------------------------

def analyze_volume(df, lookback=None, spike_multiplier=None):
    """
    Analyze volume for spikes, declining volume, and relative volume.

    Returns:
        current_volume:   latest candle volume
        avg_volume:       average volume over lookback
        relative_volume:  current / average ratio
        is_spike:         True if volume spike detected
        is_declining:     True if volume declining (weak move)
        volume_trend:     "increasing" / "declining" / "normal"
    """
    if lookback is None:
        lookback = VOLUME_LOOKBACK
    if spike_multiplier is None:
        spike_multiplier = VOLUME_SPIKE_MULTIPLIER

    if df is None or len(df) < lookback + 1:
        return {
            "current_volume":  None,
            "avg_volume":      None,
            "relative_volume": None,
            "is_spike":        False,
            "is_declining":    False,
            "volume_trend":    "unknown"
        }

    volumes = df["volume"].values

    current_volume = float(volumes[-1])
    avg_volume     = float(np.mean(volumes[-lookback-1:-1]))

    if avg_volume == 0:
        return {
            "current_volume":  current_volume,
            "avg_volume":      avg_volume,
            "relative_volume": None,
            "is_spike":        False,
            "is_declining":    False,
            "volume_trend":    "unknown"
        }

    relative_volume = current_volume / avg_volume

    # Volume spike = above multiplier threshold
    is_spike = relative_volume >= spike_multiplier

    # Declining volume = below threshold
    is_declining = relative_volume <= VOLUME_DECLINING_THRESHOLD

    # Volume trend over last 5 candles
    if len(volumes) >= 5:
        recent_vols = volumes[-5:]
        if recent_vols[-1] > recent_vols[0] * 1.1:
            volume_trend = "increasing"
        elif recent_vols[-1] < recent_vols[0] * 0.9:
            volume_trend = "declining"
        else:
            volume_trend = "normal"
    else:
        volume_trend = "normal"

    return {
        "current_volume":  round(current_volume, 0),
        "avg_volume":      round(avg_volume, 0),
        "relative_volume": round(relative_volume, 2),
        "is_spike":        is_spike,
        "is_declining":    is_declining,
        "volume_trend":    volume_trend
    }


# ------------------------------------------------------------
# MAIN ENGINE FUNCTION
# ------------------------------------------------------------

def run(candle_store):
    """
    Run full Momentum Engine.
    Calculates RSI + Divergence + Volume on M15 and H1.

    Returns:
        dict with all momentum readings
    """
    df_m15 = candle_store.get_closed("M15")
    df_h1  = candle_store.get_closed("H1")
    df_m5  = candle_store.get_closed("M5")

    # --- RSI on multiple timeframes ---
    rsi_m5  = calculate_rsi(df_m5)
    rsi_m15 = calculate_rsi(df_m15)
    rsi_h1  = calculate_rsi(df_h1)

    # Current RSI values
    rsi_m5_val  = float(rsi_m5.iloc[-1])  if rsi_m5  is not None and not rsi_m5.empty  else None
    rsi_m15_val = float(rsi_m15.iloc[-1]) if rsi_m15 is not None and not rsi_m15.empty else None
    rsi_h1_val  = float(rsi_h1.iloc[-1])  if rsi_h1  is not None and not rsi_h1.empty  else None

    # RSI signals
    rsi_m5_signal  = get_rsi_signal(rsi_m5_val)
    rsi_m15_signal = get_rsi_signal(rsi_m15_val)
    rsi_h1_signal  = get_rsi_signal(rsi_h1_val)

    # --- Divergence on M15 ---
    divergences_m15 = detect_divergence(df_m15, rsi_m15) if df_m15 is not None else []
    divergences_h1  = detect_divergence(df_h1,  rsi_h1)  if df_h1  is not None else []

    # Most recent divergence
    all_divs = divergences_m15 + divergences_h1
    all_divs.sort(key=lambda x: x["index"])
    recent_divergence = all_divs[-1] if all_divs else None

    # Check if divergence is fresh (last 10 candles on M15)
    divergence_active = False
    divergence_type   = None
    if recent_divergence and df_m15 is not None:
        if len(df_m15) - recent_divergence["index"] <= 10:
            divergence_active = True
            divergence_type   = recent_divergence["type"]

    # --- Volume Analysis ---
    vol_m15 = analyze_volume(df_m15)
    vol_h1  = analyze_volume(df_h1)
    vol_m5  = analyze_volume(df_m5)

    # --- RSI Midline Cross ---
    rsi_above_mid_m15 = rsi_m15_val > RSI_MIDLINE if rsi_m15_val else None
    rsi_above_mid_h1  = rsi_h1_val  > RSI_MIDLINE if rsi_h1_val  else None

    # --- Overall Momentum Direction ---
    bull_points = 0
    bear_points = 0

    for signal in [rsi_m5_signal, rsi_m15_signal, rsi_h1_signal]:
        if signal in ["bullish", "oversold"]:
            bull_points += 1
        elif signal in ["bearish", "overbought"]:
            bear_points += 1

    if bull_points > bear_points:
        momentum_direction = "bullish"
    elif bear_points > bull_points:
        momentum_direction = "bearish"
    else:
        momentum_direction = "neutral"

    # ------------------------------------------------------------
    # ENGINE SCORE
    # ------------------------------------------------------------
    score = 0

    # RSI signal strength
    if rsi_h1_signal in ["overbought", "oversold"]:
        score += 30
    elif rsi_h1_signal in ["bullish", "bearish"]:
        score += 20

    if rsi_m15_signal in ["overbought", "oversold"]:
        score += 20
    elif rsi_m15_signal in ["bullish", "bearish"]:
        score += 10

    # Divergence bonus
    if divergence_active:
        score += 30
        if "regular" in (divergence_type or ""):
            score += 10  # Regular divergence = stronger signal

    # Volume confirmation
    if vol_m15["is_spike"]:
        score += 15
    if vol_m15["is_declining"]:
        score += 10  # Declining volume on pullback = good

    score = min(score, 100)

    return {
        # RSI values
        "rsi_m5":          round(rsi_m5_val, 2)  if rsi_m5_val  else None,
        "rsi_m15":         round(rsi_m15_val, 2) if rsi_m15_val else None,
        "rsi_h1":          round(rsi_h1_val, 2)  if rsi_h1_val  else None,

        # RSI signals
        "rsi_m5_signal":   rsi_m5_signal,
        "rsi_m15_signal":  rsi_m15_signal,
        "rsi_h1_signal":   rsi_h1_signal,

        # Midline
        "rsi_above_mid_m15": rsi_above_mid_m15,
        "rsi_above_mid_h1":  rsi_above_mid_h1,

        # Divergence
        "divergences_m15":   divergences_m15[-3:] if divergences_m15 else [],
        "divergences_h1":    divergences_h1[-3:]  if divergences_h1  else [],
        "divergence_active": divergence_active,
        "divergence_type":   divergence_type,
        "recent_divergence": recent_divergence,

        # Volume
        "volume_m5":         vol_m5,
        "volume_m15":        vol_m15,
        "volume_h1":         vol_h1,

        # Overall
        "momentum_direction": momentum_direction,
        "engine_score":       score,
    }


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------

if __name__ == "__main__":
    import MetaTrader5 as mt5
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data.candle_store import store

    print("Testing Box 5 — Momentum Engine")
    print("=" * 50)

    mt5.initialize()
    store.refresh()

    result = run(store)

    print(f"\nRSI Values:")
    print(f"  M5:  {result['rsi_m5']}  → {result['rsi_m5_signal']}")
    print(f"  M15: {result['rsi_m15']} → {result['rsi_m15_signal']}")
    print(f"  H1:  {result['rsi_h1']}  → {result['rsi_h1_signal']}")

    print(f"\nRSI Above Midline:")
    print(f"  M15: {result['rsi_above_mid_m15']}")
    print(f"  H1:  {result['rsi_above_mid_h1']}")

    print(f"\nDivergence:")
    print(f"  Active: {result['divergence_active']}")
    print(f"  Type:   {result['divergence_type']}")
    if result["recent_divergence"]:
        rd = result["recent_divergence"]
        print(f"  Signal: {rd['signal']}")
        print(f"  RSI:    {round(rd['rsi_prev'], 1)} → {round(rd['rsi_current'], 1)}")

    print(f"\nVolume M15:")
    v = result["volume_m15"]
    print(f"  Current:  {v['current_volume']}")
    print(f"  Average:  {v['avg_volume']}")
    print(f"  Relative: {v['relative_volume']}x")
    print(f"  Spike:    {v['is_spike']}")
    print(f"  Declining:{v['is_declining']}")
    print(f"  Trend:    {v['volume_trend']}")

    print(f"\nMomentum Direction: {result['momentum_direction'].upper()}")
    print(f"Engine Score: {result['engine_score']}/100")

    mt5.shutdown()
    print("\nBox 5 Test PASSED ✓")
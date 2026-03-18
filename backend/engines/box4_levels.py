# ============================================================
# box4_levels.py — Levels Engine
# Finds institutional reaction zones
# Tools: Pivot Points, PDH/PDL, Weekly/Monthly H/L,
#        Session H/L, Psychological Levels, VWAP
# ============================================================

import sys
import os
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import (
    PSYCHOLOGICAL_ROUND_NUMBER,
    KEY_LEVEL_PROXIMITY,
    PIVOT_TYPE
)


# ------------------------------------------------------------
# PIVOT POINTS
# ------------------------------------------------------------

def calculate_pivot_points(prev_high, prev_low, prev_close, prefix="d"):
    """
    Standard Classic pivot points formula.
    Works for daily, weekly and monthly — same formula, different OHLC input.

    PP = (H + L + C) / 3
    R1 = (2 * PP) - L        S1 = (2 * PP) - H
    R2 = PP + (H - L)         S2 = PP - (H - L)
    R3 = H + 2 * (PP - L)     S3 = L - 2 * (H - PP)

    Args:
        prev_high, prev_low, prev_close: from the PREVIOUS period candle
        prefix: "d" = daily, "w" = weekly, "m" = monthly
                Used for labeling: dPP, wPP, mPP etc.
    """
    if prev_high is None or prev_low is None or prev_close is None:
        return None

    h, l, c = float(prev_high), float(prev_low), float(prev_close)

    pp = (h + l + c) / 3
    r1 = (2 * pp) - l
    r2 = pp + (h - l)
    r3 = h + 2 * (pp - l)
    s1 = (2 * pp) - h
    s2 = pp - (h - l)
    s3 = l - 2 * (h - pp)

    return {
        f"{prefix}pp": round(pp, 2),
        f"{prefix}r1": round(r1, 2),
        f"{prefix}r2": round(r2, 2),
        f"{prefix}r3": round(r3, 2),
        f"{prefix}s1": round(s1, 2),
        f"{prefix}s2": round(s2, 2),
        f"{prefix}s3": round(s3, 2),
    }


# ------------------------------------------------------------
# PSYCHOLOGICAL LEVELS
# ------------------------------------------------------------

def find_psychological_levels(current_price, range_pips=500):
    """
    Find round number psychological levels near current price.
    For XAUUSD every $50 is a major psychological level.
    Every $100 is an even bigger one.

    Returns list of nearby psychological levels with their type.
    """
    if current_price is None:
        return []

    levels = []
    step = PSYCHOLOGICAL_ROUND_NUMBER  # 50 for gold

    # Find nearest round numbers above and below
    lower = int(current_price / step) * step
    upper = lower + step

    # Generate levels in range
    start = lower - (range_pips // step) * step
    end   = upper + (range_pips // step) * step

    price = start
    while price <= end:
        distance = abs(price - current_price)
        level_type = "major" if price % 100 == 0 else "minor"

        levels.append({
            "level":    round(float(price), 2),
            "type":     level_type,
            "distance": round(distance, 2),
            "label":    f"Psych {price}"
        })
        price += step

    # Sort by distance from current price
    levels.sort(key=lambda x: x["distance"])

    return levels


# ------------------------------------------------------------
# VWAP CALCULATION
# ------------------------------------------------------------

def calculate_vwap(df):
    """
    Calculate Volume Weighted Average Price (VWAP).
    Resets daily — uses today's candles only.
    VWAP is a key institutional reference level.

    Returns current VWAP value.
    """
    if df is None or len(df) == 0:
        return None

    df = df.copy()

    # Filter to today's candles only
    if hasattr(df["time"].iloc[0], 'date'):
        today = df["time"].iloc[-1].date()
        df = df[df["time"].dt.date == today]

    if len(df) == 0:
        return None

    # Typical price = (high + low + close) / 3
    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
    df["tp_volume"]     = df["typical_price"] * df["volume"]

    cumulative_tp_vol = df["tp_volume"].cumsum()
    cumulative_vol    = df["volume"].cumsum()

    # Avoid division by zero
    if cumulative_vol.iloc[-1] == 0:
        return None

    vwap = cumulative_tp_vol.iloc[-1] / cumulative_vol.iloc[-1]
    return round(float(vwap), 2)




# ------------------------------------------------------------
# PREMIUM / DISCOUNT ZONES
# ------------------------------------------------------------

def calculate_premium_discount(swing_high, swing_low, current_price):
    """
    Premium/Discount zones based on the most recent H4 dealing range.

    Equilibrium (EQ) = midpoint of swing range = (H + L) / 2
    Discount = below EQ → buy zone (price is cheap)
    Premium  = above EQ → sell zone (price is expensive)

    OTE (Optimal Trade Entry):
        Buy OTE  = 61.8% to 79% retracement in discount zone
        Sell OTE = 61.8% to 79% retracement in premium zone
    """
    if swing_high is None or swing_low is None or current_price is None:
        return None

    h = float(swing_high)
    l = float(swing_low)
    c = float(current_price)

    if h <= l:
        return None

    rng  = h - l
    eq   = (h + l) / 2   # equilibrium = 50%

    # Determine zone
    if c > eq:
        zone = "premium"   # sell zone — price is expensive
    elif c < eq:
        zone = "discount"  # buy zone — price is cheap
    else:
        zone = "equilibrium"

    # OTE zone boundaries (Fibonacci 61.8% to 79%)
    # For buy setup (bullish bias, price in discount):
    #   OTE = swing_high - (rng * 0.618) to swing_high - (rng * 0.79)
    # For sell setup (bearish bias, price in premium):
    #   OTE = swing_low + (rng * 0.618) to swing_low + (rng * 0.79)
    buy_ote_top    = round(h - rng * 0.618, 2)
    buy_ote_bottom = round(h - rng * 0.79,  2)
    sell_ote_top   = round(l + rng * 0.79,  2)
    sell_ote_bottom = round(l + rng * 0.618, 2)

    in_buy_ote  = buy_ote_bottom <= c <= buy_ote_top
    in_sell_ote = sell_ote_bottom <= c <= sell_ote_top

    return {
        "zone":             zone,
        "equilibrium":      round(eq, 2),
        "swing_high":       round(h, 2),
        "swing_low":        round(l, 2),
        "premium_above":    round(eq, 2),
        "discount_below":   round(eq, 2),
        "buy_ote_top":      buy_ote_top,
        "buy_ote_bottom":   buy_ote_bottom,
        "sell_ote_top":     sell_ote_top,
        "sell_ote_bottom":  sell_ote_bottom,
        "in_buy_ote":       in_buy_ote,
        "in_sell_ote":      in_sell_ote,
        "in_ote":           in_buy_ote or in_sell_ote,
        "pct_from_eq":      round((c - eq) / rng * 100, 1),
    }


# ------------------------------------------------------------
# KEY LEVEL PROXIMITY CHECK
# ------------------------------------------------------------

def check_proximity(current_price, levels, proximity_pips=None):
    """
    Check if current price is near any key level.
    Returns the closest level and whether price is "at" it.

    Args:
        current_price: current gold price
        levels: list of level dicts with "level" key
        proximity_pips: max distance to count as "at level"
    """
    if proximity_pips is None:
        proximity_pips = KEY_LEVEL_PROXIMITY

    if current_price is None or not levels:
        return None, False

    closest = None
    min_distance = float("inf")

    for level_info in levels:
        level = level_info.get("level") or level_info
        if level is None:
            continue
        distance = abs(float(current_price) - float(level))
        if distance < min_distance:
            min_distance = distance
            closest = level_info

    at_level = min_distance <= proximity_pips

    return closest, at_level




# ------------------------------------------------------------
# PREMIUM / DISCOUNT ZONES
# ------------------------------------------------------------

def calculate_premium_discount(swing_high, swing_low, current_price):
    """
    ICT Premium / Discount / OTE zones.

    Based on the current dealing range (swing_high to swing_low):
    - Equilibrium (EQ) = 50% midpoint
    - Above EQ = PREMIUM zone  → institutional SELL area
    - Below EQ = DISCOUNT zone → institutional BUY area
    - OTE zone = 0.62 to 0.79 retracement (optimal trade entry)
      Sweet spot = 0.705

    For BUY setups: look for price in DISCOUNT + OTE zone
    For SELL setups: look for price in PREMIUM + OTE zone
    """
    if swing_high is None or swing_low is None or current_price is None:
        return None

    h = float(swing_high)
    l = float(swing_low)
    p = float(current_price)
    rng = h - l

    if rng <= 0:
        return None

    equilibrium = l + rng * 0.5

    # OTE zone for BUY = 0.62 to 0.79 retracement FROM high (discount side)
    ote_buy_top    = round(h - rng * 0.62, 2)
    ote_buy_bottom = round(h - rng * 0.79, 2)
    ote_buy_705    = round(h - rng * 0.705, 2)

    # OTE zone for SELL = 0.62 to 0.79 retracement FROM low (premium side)
    ote_sell_bottom = round(l + rng * 0.62, 2)
    ote_sell_top    = round(l + rng * 0.79, 2)
    ote_sell_705    = round(l + rng * 0.705, 2)

    # Where is current price?
    if p > equilibrium:
        zone = "premium"
        zone_pct = round((p - equilibrium) / (h - equilibrium) * 100, 1)
    else:
        zone = "discount"
        zone_pct = round((equilibrium - p) / (equilibrium - l) * 100, 1)

    # Is price in OTE zone?
    in_ote_buy  = ote_buy_bottom <= p <= ote_buy_top
    in_ote_sell = ote_sell_bottom <= p <= ote_sell_top

    return {
        "swing_high":      round(h, 2),
        "swing_low":       round(l, 2),
        "equilibrium":     round(equilibrium, 2),
        "zone":            zone,               # premium or discount
        "zone_pct":        zone_pct,
        "in_premium":      zone == "premium",
        "in_discount":     zone == "discount",

        # OTE zones (for entries)
        "ote_buy_top":     ote_buy_top,        # 0.62 retrace from high
        "ote_buy_bottom":  ote_buy_bottom,     # 0.79 retrace from high
        "ote_buy_705":     ote_buy_705,        # sweet spot for buy
        "in_ote_buy":      in_ote_buy,

        "ote_sell_top":    ote_sell_top,       # 0.79 retrace from low
        "ote_sell_bottom": ote_sell_bottom,    # 0.62 retrace from low
        "ote_sell_705":    ote_sell_705,       # sweet spot for sell
        "in_ote_sell":     in_ote_sell,

        "in_ote":          in_ote_buy or in_ote_sell,
    }


# ------------------------------------------------------------
# NWOG / NDOG — New Week/Day Opening Gaps
# ------------------------------------------------------------

def calculate_opening_gaps(candle_store):
    """
    NWOG = New Week Opening Gap
           Gap between Friday 4:59 PM EST close and Sunday 6:00 PM EST open
           Acts as a price magnet — institutions fill these gaps
           CE (Consequent Encroachment) = 50% midpoint of gap

    NDOG = New Day Opening Gap
           Gap between previous day close and today's open
           Key intraday magnet level

    Both are Fair Value Gaps at the macro scale.
    """
    nwog = None
    ndog = None

    try:
        # NWOG — from weekly candle open vs prior week close
        prev_week = candle_store.prev_week
        curr_week_df = candle_store.get("W1")

        if prev_week is not None and curr_week_df is not None and len(curr_week_df) > 0:
            friday_close  = float(prev_week["close"])
            sunday_open   = float(curr_week_df.iloc[-1]["open"])

            if abs(friday_close - sunday_open) > 0.1:  # min 1 pip gap
                nwog_high = max(friday_close, sunday_open)
                nwog_low  = min(friday_close, sunday_open)
                nwog = {
                    "high":   round(nwog_high, 2),
                    "low":    round(nwog_low,  2),
                    "ce":     round((nwog_high + nwog_low) / 2, 2),
                    "size":   round(nwog_high - nwog_low, 2),
                    "friday_close": round(friday_close, 2),
                    "sunday_open":  round(sunday_open,  2),
                    "bullish": sunday_open > friday_close,  # gap up = bullish
                }

        # NDOG — from previous day close vs today open
        prev_day = candle_store.prev_day
        curr_day_df = candle_store.get("D1")

        if prev_day is not None and curr_day_df is not None and len(curr_day_df) > 0:
            prev_close  = float(prev_day["close"])
            today_open  = float(curr_day_df.iloc[-1]["open"])

            if abs(prev_close - today_open) > 0.1:
                ndog_high = max(prev_close, today_open)
                ndog_low  = min(prev_close, today_open)
                ndog = {
                    "high":       round(ndog_high, 2),
                    "low":        round(ndog_low,  2),
                    "ce":         round((ndog_high + ndog_low) / 2, 2),
                    "size":       round(ndog_high - ndog_low, 2),
                    "prev_close": round(prev_close, 2),
                    "today_open": round(today_open, 2),
                    "bullish":    today_open > prev_close,
                }

    except Exception as e:
        print(f"[Levels] Opening gap error: {e}")

    return nwog, ndog

# ------------------------------------------------------------
# BUILD ALL LEVELS LIST
# ------------------------------------------------------------

def build_levels_list(pivots, weekly_pivots, monthly_pivots,
                      pdh, pdl, pwh, pwl, pmh, pml,
                      asian_high, asian_low, psych_levels, vwap,
                      nwog=None, ndog=None):
    """
    Combine all levels into one unified list.
    Daily, weekly and monthly pivots all included.
    Sorted by source strength: monthly > weekly > daily > session > psych
    """
    all_levels = []

    # Daily pivot points (dPP, dR1-R3, dS1-S3)
    if pivots:
        for key, value in pivots.items():
            label = key.upper()
            level_type = "resistance" if key[1:].startswith("r") else \
                         "support"    if key[1:].startswith("s") else "pivot"
            all_levels.append({
                "level":  value, "label": label,
                "type":   level_type, "source": "daily_pivot",
                "weight": 2,
            })

    # Weekly pivot points (wPP, wR1-R3, wS1-S3)
    if weekly_pivots:
        for key, value in weekly_pivots.items():
            label = key.upper()
            level_type = "resistance" if key[1:].startswith("r") else \
                         "support"    if key[1:].startswith("s") else "pivot"
            all_levels.append({
                "level":  value, "label": label,
                "type":   level_type, "source": "weekly_pivot",
                "weight": 3,  # Weekly pivots are stronger
            })

    # Monthly pivot points (mPP, mR1-R3, mS1-S3)
    if monthly_pivots:
        for key, value in monthly_pivots.items():
            label = key.upper()
            level_type = "resistance" if key[1:].startswith("r") else \
                         "support"    if key[1:].startswith("s") else "pivot"
            all_levels.append({
                "level":  value, "label": label,
                "type":   level_type, "source": "monthly_pivot",
                "weight": 4,  # Monthly pivots are strongest
            })

    # PDH / PDL
    if pdh:
        all_levels.append({"level": pdh, "label": "PDH", "type": "resistance", "source": "daily"})
    if pdl:
        all_levels.append({"level": pdl, "label": "PDL", "type": "support", "source": "daily"})

    # Weekly
    if pwh:
        all_levels.append({"level": pwh, "label": "PWH", "type": "resistance", "source": "weekly"})
    if pwl:
        all_levels.append({"level": pwl, "label": "PWL", "type": "support", "source": "weekly"})

    # Monthly
    if pmh:
        all_levels.append({"level": pmh, "label": "PMH", "type": "resistance", "source": "monthly"})
    if pml:
        all_levels.append({"level": pml, "label": "PML", "type": "support", "source": "monthly"})

    # Session
    if asian_high:
        all_levels.append({"level": asian_high, "label": "Asian High", "type": "resistance", "source": "session"})
    if asian_low:
        all_levels.append({"level": asian_low, "label": "Asian Low", "type": "support", "source": "session"})

    # VWAP
    if vwap:
        all_levels.append({"level": vwap, "label": "VWAP", "type": "dynamic", "source": "vwap"})

    # Top 5 psychological levels
    if psych_levels:
        for pl in psych_levels[:5]:
            all_levels.append({
                "level":  pl["level"],
                "label":  pl["label"],
                "type":   "psychological",
                "source": "psych"
            })

    # NWOG / NDOG — Opening Gaps (magnetic levels)
    if nwog:
        all_levels.append({"level": nwog["high"], "label": "NWOG High", "type": "gap", "source": "nwog", "weight": 3})
        all_levels.append({"level": nwog["low"],  "label": "NWOG Low",  "type": "gap", "source": "nwog", "weight": 3})
        all_levels.append({"level": nwog["ce"],   "label": "NWOG CE",   "type": "gap", "source": "nwog", "weight": 3})
    if ndog:
        all_levels.append({"level": ndog["high"], "label": "NDOG High", "type": "gap", "source": "ndog", "weight": 2})
        all_levels.append({"level": ndog["low"],  "label": "NDOG Low",  "type": "gap", "source": "ndog", "weight": 2})
        all_levels.append({"level": ndog["ce"],   "label": "NDOG CE",   "type": "gap", "source": "ndog", "weight": 2})

    return all_levels


# ------------------------------------------------------------
# MAIN ENGINE FUNCTION
# ------------------------------------------------------------

def run(candle_store):
    """
    Run full Levels Engine.
    Calculates all institutional reference levels for XAUUSD.

    Returns:
        dict with all levels + proximity to current price
    """
    # Get data
    df_m5  = candle_store.get_closed("M5")
    df_h1  = candle_store.get_closed("H1")

    # Current price
    price_info = candle_store.get_price()
    current_price = price_info["bid"] if price_info else None

    # Previous candles
    pdh = candle_store.get_pdh()
    pdl = candle_store.get_pdl()
    pwh = candle_store.get_pwh()
    pwl = candle_store.get_pwl()
    pmh = candle_store.get_pmh()
    pml = candle_store.get_pml()

    # Daily pivot points from previous day candle
    prev_day = candle_store.prev_day
    pivots = None
    if prev_day is not None:
        pivots = calculate_pivot_points(
            float(prev_day["high"]),
            float(prev_day["low"]),
            float(prev_day["close"]),
            prefix="d"
        )

    # Weekly pivot points from previous week candle
    # Recalculates every Monday using last week's OHLC
    prev_week = candle_store.prev_week
    weekly_pivots = None
    if prev_week is not None:
        weekly_pivots = calculate_pivot_points(
            float(prev_week["high"]),
            float(prev_week["low"]),
            float(prev_week["close"]),
            prefix="w"
        )

    # Monthly pivot points from previous month candle
    # Recalculates on 1st of each month using last month's OHLC
    prev_month = candle_store.prev_month
    monthly_pivots = None
    if prev_month is not None:
        monthly_pivots = calculate_pivot_points(
            float(prev_month["high"]),
            float(prev_month["low"]),
            float(prev_month["close"]),
            prefix="m"
        )

    # Psychological levels
    psych_levels = find_psychological_levels(current_price)

    # Premium / Discount / OTE zones
    # Use last 50 candles on H4 to define the dealing range
    df_h4 = candle_store.get_closed("H4")
    pd_zones = None
    if df_h4 is not None and len(df_h4) >= 10 and current_price:
        recent_h4 = df_h4.iloc[-50:]
        dealing_high = float(recent_h4["high"].max())
        dealing_low  = float(recent_h4["low"].min())
        pd_zones = calculate_premium_discount(dealing_high, dealing_low, current_price)

    # NWOG / NDOG
    nwog, ndog = calculate_opening_gaps(candle_store)

    # VWAP
    vwap = calculate_vwap(df_m5)

    # Asian session high/low from H1
    asian_high, asian_low = None, None
    if df_h1 is not None:
        from engines.box3_liquidity import get_session_high_low
        asian_high, asian_low = get_session_high_low(df_h1, 0, 7)

    # Build unified levels list
    all_levels = build_levels_list(
        pivots, weekly_pivots, monthly_pivots,
        pdh, pdl, pwh, pwl, pmh, pml,
        asian_high, asian_low, psych_levels, vwap
    )

    # Add gap levels to list after building
    if nwog:
        all_levels.append({
            "level":  nwog["ce"], "label": f"NWOG CE {nwog['ce']}",
            "type":   "gap_magnet", "source": "nwog", "weight": 3,
        })
    if ndog:
        all_levels.append({
            "level":  ndog["ce"], "label": f"NDOG CE {ndog['ce']}",
            "type":   "gap_magnet", "source": "ndog", "weight": 2,
        })

    # Sort by proximity to current price
    if current_price:
        all_levels.sort(key=lambda x: abs(x["level"] - current_price))

    # Check if price is at any key level
    closest_level, at_key_level = check_proximity(current_price, all_levels)

    # Nearest resistance and support
    nearest_resistance = None
    nearest_support    = None

    if current_price:
        resistances = [l for l in all_levels if l["level"] > current_price]
        supports    = [l for l in all_levels if l["level"] < current_price]

        if resistances:
            nearest_resistance = min(resistances, key=lambda x: x["level"])
        if supports:
            nearest_support = max(supports, key=lambda x: x["level"])

    # Extract key pivot levels early (needed for score calculation)
    pivot_pp = pivots.get("dpp") if pivots else None
    pivot_r1 = pivots.get("dr1") if pivots else None
    pivot_r2 = pivots.get("dr2") if pivots else None
    pivot_r3 = pivots.get("dr3") if pivots else None
    pivot_s1 = pivots.get("ds1") if pivots else None
    pivot_s2 = pivots.get("ds2") if pivots else None
    pivot_s3 = pivots.get("ds3") if pivots else None

    # ------------------------------------------------------------
    # ENGINE SCORE
    # ------------------------------------------------------------
    score = 0

    if at_key_level:
        score += 60

        # Extra weight based on pivot timeframe
        if closest_level:
            source = closest_level.get("source", "")
            if source == "monthly_pivot":
                score += 30
            elif source == "weekly_pivot":
                score += 22
            elif source in ["daily_pivot", "pivot"]:
                score += 15
            elif source in ["weekly", "monthly"]:
                score += 18
            elif source in ["daily"]:
                score += 12
            elif source == "psych":
                score += 8

        # Confluence bonus: multiple timeframe pivots near same price
        if pivots and weekly_pivots and monthly_pivots and current_price:
            all_pp = [
                abs(pivot_pp - current_price) if pivot_pp else 999,
                abs(weekly_pivots.get("wpp", 999) - current_price),
                abs(monthly_pivots.get("mpp", 999) - current_price),
            ]
            if min(all_pp) < 5:
                score += 10

    elif closest_level:
        # Not exactly at level but close
        distance = abs(current_price - closest_level["level"]) if current_price else 999
        if distance < KEY_LEVEL_PROXIMITY * 2:
            score += 30

    score = min(score, 100)

    # Score bonus if price is in OTE zone
    if pd_zones and pd_zones.get("in_ote"):
        score = min(score + 15, 100)

    return {
        # Daily pivot points
        "pivots":            pivots,
        "pivot_pp":          pivot_pp,
        "pivot_r1":          pivot_r1,
        "pivot_r2":          pivot_r2,
        "pivot_r3":          pivot_r3,
        "pivot_s1":          pivot_s1,
        "pivot_s2":          pivot_s2,
        "pivot_s3":          pivot_s3,

        # Weekly pivot points (full suite R1-R3, S1-S3)
        "weekly_pivots":     weekly_pivots,
        "weekly_pp":         weekly_pivots.get("wpp") if weekly_pivots else None,
        "weekly_r1":         weekly_pivots.get("wr1") if weekly_pivots else None,
        "weekly_r2":         weekly_pivots.get("wr2") if weekly_pivots else None,
        "weekly_r3":         weekly_pivots.get("wr3") if weekly_pivots else None,
        "weekly_s1":         weekly_pivots.get("ws1") if weekly_pivots else None,
        "weekly_s2":         weekly_pivots.get("ws2") if weekly_pivots else None,
        "weekly_s3":         weekly_pivots.get("ws3") if weekly_pivots else None,

        # Monthly pivot points (full suite R1-R3, S1-S3)
        "monthly_pivots":    monthly_pivots,
        "monthly_pp":        monthly_pivots.get("mpp") if monthly_pivots else None,
        "monthly_r1":        monthly_pivots.get("mr1") if monthly_pivots else None,
        "monthly_r2":        monthly_pivots.get("mr2") if monthly_pivots else None,
        "monthly_r3":        monthly_pivots.get("mr3") if monthly_pivots else None,
        "monthly_s1":        monthly_pivots.get("ms1") if monthly_pivots else None,
        "monthly_s2":        monthly_pivots.get("ms2") if monthly_pivots else None,
        "monthly_s3":        monthly_pivots.get("ms3") if monthly_pivots else None,

        # Key levels
        "pdh":               pdh,
        "pdl":               pdl,
        "pwh":               pwh,
        "pwl":               pwl,
        "pmh":               pmh,
        "pml":               pml,
        "asian_high":        asian_high,
        "asian_low":         asian_low,
        "vwap":              vwap,

        # Psychological levels
        "psych_levels":      psych_levels[:5] if psych_levels else [],

        # All levels combined
        "all_levels":        all_levels,
        "total_levels":      len(all_levels),

        # Proximity
        "current_price":     current_price,
        "at_key_level":      at_key_level,
        "closest_level":     closest_level,
        "nearest_resistance": nearest_resistance,
        "nearest_support":   nearest_support,

        # Premium / Discount / OTE (from H4 dealing range)
        "pd_zone":           pd_zones,
        "price_zone":        pd_zones["zone"]        if pd_zones else "unknown",
        "equilibrium":       pd_zones["equilibrium"] if pd_zones else None,
        "in_ote":            pd_zones.get("in_ote", False)      if pd_zones else False,
        "in_buy_ote":        pd_zones.get("in_buy_ote", pd_zones.get("in_ote_buy", False))   if pd_zones else False,
        "in_sell_ote":       pd_zones.get("in_sell_ote", pd_zones.get("in_ote_sell", False)) if pd_zones else False,

        # NWOG / NDOG opening gaps
        "opening_gaps":      [g for g in [nwog, ndog] if g is not None],
        "nwog":              nwog,
        "ndog":              ndog,
        "nwog_ce":           nwog["ce"] if nwog else None,
        "ndog_ce":           ndog["ce"] if ndog else None,

        # Engine score
        "engine_score":      score,
    }


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------

if __name__ == "__main__":
    import MetaTrader5 as mt5
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data.candle_store import store

    print("Testing Box 4 — Levels Engine")
    print("=" * 50)

    mt5.initialize()
    store.refresh()

    result = run(store)

    print(f"\nCurrent Price: {result['current_price']}")
    print(f"\nDaily Pivot Points:")
    if result["pivots"]:
        for k, v in result["pivots"].items():
            print(f"  {k.upper():>4}: {v}")

    print(f"\nWeekly Pivot Points:")
    if result["weekly_pivots"]:
        for k, v in result["weekly_pivots"].items():
            print(f"  {k.upper():>4}: {v}")

    print(f"\nMonthly Pivot Points:")
    if result["monthly_pivots"]:
        for k, v in result["monthly_pivots"].items():
            print(f"  {k.upper():>4}: {v}")

    print(f"\nKey Levels:")
    print(f"  PDH: {result['pdh']} | PDL: {result['pdl']}")
    print(f"  PWH: {result['pwh']} | PWL: {result['pwl']}")
    print(f"  PMH: {result['pmh']} | PML: {result['pml']}")
    print(f"  Asian High: {result['asian_high']} | Asian Low: {result['asian_low']}")
    print(f"  VWAP: {result['vwap']}")

    print(f"\nNearest Resistance: {result['nearest_resistance']}")
    print(f"Nearest Support:    {result['nearest_support']}")
    print(f"At Key Level:       {result['at_key_level']}")
    print(f"Closest Level:      {result['closest_level']}")

    print(f"\nTop Psychological Levels:")
    for pl in result["psych_levels"]:
        print(f"  {pl['label']}: {pl['level']} ({pl['type']}) — {pl['distance']} away")

    print(f"\nEngine Score: {result['engine_score']}/100")

    mt5.shutdown()
    print("\nBox 4 Test PASSED ✓")
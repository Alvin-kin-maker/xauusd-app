"""
patch_fvg_adaptive.py - Adaptive entry for fvg_continuation
When H4+H1+M15 all agree direction (strong trend), enter at current price
When ranging, use limit entry at FVG midpoint
Run from backend/ folder
"""
path = "engines/box10_trade.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

# Find fvg_continuation entry in _smart_fvg
old = """def _smart_fvg(direction, b7, buf, current_price=None, b1=None, b2=None, b3=None):
    MAX_DIST = 5.0
    if direction == "buy":
        fvgs = b7.get("bullish_fvgs", [])
        for fvg in fvgs:
            proximal = round(float(fvg["bottom"]), 2)
            distal   = round(float(fvg["top"]), 2)
            midpoint = round(float(fvg["midpoint"]), 2)
            if current_price and abs(midpoint - current_price) > MAX_DIST:
                continue
            # If price is currently AT the FVG (touching it), enter at current price
            # not the midpoint — this fills immediately instead of ghosting.
            at_fvg_now = b7.get("at_bull_fvg", False)
            entry = round(current_price - 0.1, 2) if (at_fvg_now and current_price) else midpoint
            atr_val = float(b1.get("atr") or 2.0) if b1 else 2.0
            sl_buf  = max(atr_val * 0.15, 0.3)
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
            at_fvg_now = b7.get("at_bear_fvg", False)
            entry = round(current_price + 0.1, 2) if (at_fvg_now and current_price) else midpoint
            atr_val = float(b1.get("atr") or 2.0) if b1 else 2.0
            sl_buf  = max(atr_val * 0.15, 0.3)
            sl = round(proximal + sl_buf, 2)
            return _make_zone(entry, sl, proximal, distal, "Bear FVG CE")
    return None"""

new = """def _smart_fvg(direction, b7, buf, current_price=None, b1=None, b2=None, b3=None):
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
                entry = round(current_price - 0.1, 2)
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
                entry = round(current_price + 0.1, 2)
            else:
                entry = midpoint
            sl = round(proximal + sl_buf, 2)
            return _make_zone(entry, sl, proximal, distal, "Bear FVG CE")

    return None"""

if old in src:
    src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("PATCHED - fvg_continuation adaptive entry added")
else:
    print("NOT FOUND")
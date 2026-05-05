"""
patch_structural_sl.py - Fix structural_breakout retest SL placement
Uses M15/H1 swing levels instead of BOS level + tiny buffer
Run from backend/ folder
"""
path = "engines/box10_trade.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

old = """            # Normal retest entry
            if direction == "sell":
                sl = round(float(bos_level) + buf, 2)
                entry = round(float(bos_level) - 0.5, 2)
                return _make_zone(entry, sl, float(bos_level), sl, "Structural Breakout (Retest)")
            else:
                sl = round(float(bos_level) - buf, 2)
                entry = round(float(bos_level) + 0.5, 2)
                return _make_zone(entry, sl, float(bos_level), sl, "Structural Breakout (Retest)")"""

new = """            # Normal retest entry — use swing levels for SL, not just BOS + tiny buffer
            atr = float(b1.get("atr") or 2.0)
            min_sl_dist = max(atr * 0.5, 1.0)  # minimum 0.5x ATR = ~50-100 pips on gold

            if direction == "sell":
                entry = round(float(bos_level) - 0.5, 2)
                # SL: above last M15 swing high
                sl = None
                m15_sh = b2.get("timeframes", {}).get("M15", {}).get("last_sh")
                if m15_sh:
                    sh_p = float(m15_sh["price"]) if isinstance(m15_sh, dict) else float(m15_sh)
                    if sh_p > entry and (sh_p - entry) <= atr * 3:
                        sl = round(sh_p + buf, 2)
                if sl is None:
                    sl = round(entry + min_sl_dist, 2)
                return _make_zone(entry, sl, float(bos_level), sl, "Structural Breakout (Retest)")
            else:
                entry = round(float(bos_level) + 0.5, 2)
                # SL: below last M15 swing low
                sl = None
                m15_sl = b2.get("timeframes", {}).get("M15", {}).get("last_sl")
                if m15_sl:
                    sl_p = float(m15_sl["price"]) if isinstance(m15_sl, dict) else float(m15_sl)
                    if sl_p < entry and (entry - sl_p) <= atr * 3:
                        sl = round(sl_p - buf, 2)
                if sl is None:
                    sl = round(entry - min_sl_dist, 2)
                return _make_zone(entry, sl, float(bos_level), sl, "Structural Breakout (Retest)")"""

if old in src:
    src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("PATCHED - structural_breakout retest SL now uses M15 swing levels")
else:
    print("NOT FOUND")
"""
patch_structural_d1.py - Block structural_breakout SELL when D1 is bullish
Prevents counter-trend SELLs during bull market pullbacks
Run from backend/ folder
"""
path = "engines/box8_model.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

old = """    h4_opposes = (
        (direction == "buy"  and h4_bias == "bearish") or
        (direction == "sell" and h4_bias == "bullish")
    )
    validated = sb["validated"] and score >= 60 and not h4_opposes"""

new = """    d1_bias_sb = b2["timeframes"]["D1"]["bias"]
    h4_opposes = (
        (direction == "buy"  and h4_bias == "bearish") or
        (direction == "sell" and h4_bias == "bullish") or
        (direction == "sell" and d1_bias_sb == "bullish")  # no SELL in D1 uptrend
    )
    validated = sb["validated"] and score >= 60 and not h4_opposes"""

if old in src:
    src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("PATCHED - structural_breakout SELL blocked when D1 bullish")
else:
    print("NOT FOUND")
"""
revert_momentum.py - Revert momentum_breakout H4 gate
Run from backend/ folder
"""
path = "engines/box8_model.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

old = """    h4_bias_mb   = b2["timeframes"]["H4"]["bias"]
    direction_mb = mb.get("direction", "buy")
    h4_opposes_mb = (
        (direction_mb == "buy"  and h4_bias_mb == "bearish") or
        (direction_mb == "sell" and h4_bias_mb == "bullish")
    )
    validated = mb["validated"] and session_ok and score >= 55 and not h4_opposes_mb"""

new = '    validated = mb["validated"] and session_ok and score >= 55'

if old in src:
    src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("REVERTED")
else:
    print("NOT FOUND - already reverted or different version")
"""
patch_d1h4_gate.py - Block ALL BUY signals when D1+H4 both bearish
Block ALL SELL signals when D1+H4 both bullish
This is the master gate that prevents counter-trend trading in established trends
Run from backend/ folder
"""
path = "engines/box9_confluence.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

# Add after the existing kill switches, before return kills
old = "    return kills"

new = """    # ── MASTER TREND GATE ─────────────────────────────────────────
    # When D1 AND H4 both agree on direction, the trend is established.
    # No counter-trend signals allowed regardless of sweep or H1/M15.
    # A bullish sweep in a D1+H4 downtrend is a liquidity grab — NOT a reversal.
    # This single gate prevents the most common loss pattern: buying bounces in downtrends.
    d1_bias_gate = b2["timeframes"]["D1"]["bias"]
    h4_bias_gate = b2["timeframes"]["H4"]["bias"]

    strong_downtrend = (d1_bias_gate == "bearish" and h4_bias_gate == "bearish")
    strong_uptrend   = (d1_bias_gate == "bullish" and h4_bias_gate == "bullish")

    if direction == "buy" and strong_downtrend:
        kills.append(
            f"KILL: D1+H4 both bearish — strong downtrend, no BUY signals allowed"
        )
    elif direction == "sell" and strong_uptrend:
        kills.append(
            f"KILL: D1+H4 both bullish — strong uptrend, no SELL signals allowed"
        )

    return kills"""

if "# ── MASTER TREND GATE" not in src:
    src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("PATCHED - Master D1+H4 trend gate added")
else:
    print("Already patched")
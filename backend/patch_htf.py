"""
patch_htf.py - Add H4 gate to htf_level_reaction
Run from backend/ folder
"""
path = "engines/box8_model.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

old = """    validated = (
        good_session and
        b4["at_key_level"] and
        has_confirmation and  # must have rejection candle at level
        score >= 65
    )

    missed_rule = "Need: at HTF level + rejection candle + score≥65. No counter-trend.\""""

new = """    # H4 gate: don't trade against H4 trend at key levels
    h4_bias_htf = b2["timeframes"]["H4"]["bias"]
    h1_bias_htf = b2["timeframes"]["H1"]["bias"]
    h4_h1_oppose_htf = (
        (h1_bias_htf == "bullish" and h4_bias_htf == "bearish") or
        (h1_bias_htf == "bearish" and h4_bias_htf == "bullish")
    )

    validated = (
        good_session and
        b4["at_key_level"] and
        has_confirmation and  # must have rejection candle at level
        not h4_h1_oppose_htf and
        score >= 65
    )

    missed_rule = "Need: at HTF level + rejection candle + H4 aligned + score≥65.\""""

if old in src:
    src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("PATCHED - htf_level_reaction H4 gate added")
else:
    print("NOT FOUND")
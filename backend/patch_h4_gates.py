"""
patch_h4_gates.py - Add H4 gates to htf_level_reaction and momentum_breakout
Run from backend/ folder
"""
path = "engines/box8_model.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

fixed = []

# Fix 1: momentum_breakout H4 gate
old1 = '    validated = mb["validated"] and session_ok and score >= 55'
new1 = '''    h4_bias_mb   = b2["timeframes"]["H4"]["bias"]
    direction_mb = mb.get("direction", "buy")
    h4_opposes_mb = (
        (direction_mb == "buy"  and h4_bias_mb == "bearish") or
        (direction_mb == "sell" and h4_bias_mb == "bullish")
    )
    validated = mb["validated"] and session_ok and score >= 55 and not h4_opposes_mb'''

if old1 in src:
    src = src.replace(old1, new1)
    fixed.append("momentum_breakout")

# Fix 2: htf_level_reaction H4 gate
# Find its validated line
import re
# Find htf_level_reaction function
htf_start = src.find('name    = "htf_level_reaction"')
if htf_start == -1:
    htf_start = src.find('name = "htf_level_reaction"')

if htf_start != -1:
    section = src[htf_start:htf_start+3000]
    # Find validated line in this section
    val_match = re.search(r'    validated = \([^\)]+\)', section, re.DOTALL)
    if val_match:
        old_val = val_match.group(0)
        if 'h4_opposes_htf' not in old_val:
            new_val = '''    h4_bias_htf = b2["timeframes"]["H4"]["bias"]
    h1_bias_htf = b2["timeframes"]["H1"]["bias"]
    direction_htf = "buy" if h1_bias_htf == "bullish" else "sell"
    h4_opposes_htf = (
        (direction_htf == "buy"  and h4_bias_htf == "bearish") or
        (direction_htf == "sell" and h4_bias_htf == "bullish")
    )

''' + old_val.replace(
                '    validated = (',
                '    validated = (\n        not h4_opposes_htf and'
            )
            new_section = section.replace(old_val, new_val)
            src = src[:htf_start] + new_section + src[htf_start+3000:]
            fixed.append("htf_level_reaction")

if fixed:
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"PATCHED: {', '.join(fixed)}")
else:
    print("NOT FOUND - check patterns")
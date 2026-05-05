"""
patch_disable_models.py - Reduce MODEL_PRIORITY to 2 models only
Run from backend/ folder
"""
path = "engines/box8_model.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

old = '''MODEL_PRIORITY = [
    "silver_bullet",          # ← highest priority: time-window precision
    "momentum_breakout",      # ← straight shooter: urgent, no retest
    "london_sweep_reverse",
    "structural_breakout",    # ← BOS retest entry
    "htf_level_reaction",
    "liquidity_grab_bos",
    "ob_fvg_stack",
    "choch_reversal",
    "ob_mitigation",
    "fvg_continuation",
    "ny_continuation",
    "double_top_bottom_trap",
    "asian_range_breakout",
]'''

new = '''# Active models — focused on 2 proven models for now
# Disabled models kept in code (see ARCHIVED_PRIORITY below) for future re-enabling
MODEL_PRIORITY = [
    "structural_breakout",    # ← BOS retest entry, big winners on reversal days
    "momentum_breakout",      # ← straight shooter: trending market continuation
]

# Disabled models — re-enable by moving entries up to MODEL_PRIORITY
# These were disabled after Phase 1 testing showed they don't fire reliably
# or generate consistent losses in current market conditions
ARCHIVED_PRIORITY = [
    "silver_bullet",          # counter-trend reversal, killed by H4+H1 conflict
    "london_sweep_reverse",   # never fills
    "htf_level_reaction",     # fires counter-trend, lost in January
    "liquidity_grab_bos",     # same issue as silver_bullet
    "ob_fvg_stack",           # ghosts heavily
    "choch_reversal",         # ghosts in trends
    "ob_mitigation",          # counter-trend losses
    "fvg_continuation",       # ghosts and bounces lose
    "ny_continuation",        # barely fires
    "double_top_bottom_trap", # counter-trend losses
    "asian_range_breakout",   # ghosts
]'''

if old in src:
    src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("PATCHED - Only structural_breakout and momentum_breakout active")
else:
    print("NOT FOUND - check current MODEL_PRIORITY structure")
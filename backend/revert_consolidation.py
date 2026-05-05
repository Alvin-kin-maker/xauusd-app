"""
revert_consolidation.py - Revert consolidation boundary patch
Run from backend/ folder
"""
path = "engines/box9_confluence.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

old = """                if not at_boundary and not at_entry_zone:
                    kills.append("KILL: M15 + H1 both consolidating — price in mid-range — wait for boundary")
                elif at_boundary and not at_entry_zone and not sweep_just_happened:
                    # At boundary but no OB/FVG and no sweep — marginal, block it
                    kills.append("KILL: M15 + H1 both consolidating — at boundary but no entry zone or sweep")
                # If at_boundary AND at_entry_zone — ALLOW: price at support/resistance with structure = valid entry"""

new = """                if not at_boundary and not at_entry_zone:
                    kills.append("KILL: M15 + H1 both consolidating — price in mid-range — wait for boundary")
                elif at_boundary and not sweep_just_happened and not at_entry_zone:
                    kills.append("KILL: M15 + H1 both consolidating — at boundary — waiting for sweep before entry")"""

if old in src:
    src = src.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("REVERTED - consolidation patch removed")
else:
    print("NOT FOUND - may already be reverted")
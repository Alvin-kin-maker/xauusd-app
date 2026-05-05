# CLAUDE CODE PROMPT — Phase 1: Individual Model Testing

You are working on an XAUUSD trading system at C:\Users\alvin\xauusd_app\backend\

## YOUR TASK
Execute Phase 1 of STRATEGIC_4MODEL_PLAN.md autonomously. Test 4 models across 4 months individually, document results, and report findings.

## CURRENT SYSTEM STATE

The system has been heavily patched. These patches ARE applied and should NOT be reverted:
1. patch_box9.py — H4 gate in resolve_direction
2. patch_mss.py — MSS window 5→20 candles  
3. patch_cache.py — box2 cache per M15 not H1
4. patch_dttb.py — double_top_bottom_trap H4 gate
5. patch_silver.py — silver_bullet H4 alignment required
6. patch_structural.py — structural_breakout H4 bias fix + gate
7. patch_structural_sl.py — structural_breakout SL uses M15 swings
8. patch_structural_d1.py — structural_breakout SELL needs D1 not bullish
9. patch_h4_gates.py — momentum_breakout H4 gate
10. patch_htf.py — htf_level_reaction H4 gate
11. patch_fvg_adaptive.py — fvg_continuation adaptive entry
12. patch_d1h4_gate.py — master D1+H4 gate in box9

**Verify these patches are present before starting:**
```powershell
python -c "
f = open('engines/box9_confluence.py', 'r', encoding='utf-8')
src = f.read()
f.close()
print('master_gate' if '# ── MASTER TREND GATE' in src else 'MISSING_master_gate')
print('h4_gate' if 'h4_bias != \"bearish\"' in src or 'h4_bias != ' + chr(34) + 'bearish' + chr(34) in src else 'MISSING_h4_gate')
"
```

If any patches are missing, STOP and notify me. Do not proceed.

## KNOWN BASELINE PERFORMANCE

Last test results before Phase 1:
- January 2026: 100% winrate, +2136 pips, 2 fills, 4 ghosts (momentum_breakout only winner)
- March 2026: 25% winrate, +2270 pips, 4 fills (structural_breakout March 18 the big winner)

These are the numbers to compare against. Phase 1 should give us per-model breakdowns to verify these are correct.

## RULES
1. Do NOT modify any engine files unless I tell you to. This phase is TESTING ONLY.
2. Run scans sequentially, not in parallel (avoid resource conflicts)
3. After each scan, immediately read the result file and document it
4. If a scan fails or produces empty output, log the error and continue to next month
5. Do NOT try to "fix" anything you see in results during Phase 1 — just document
6. Use UTF-8 encoding for all PowerShell commands

## THE 4 MODELS TO TEST
1. momentum_breakout
2. structural_breakout
3. silver_bullet
4. liquidity_grab_bos

## THE 4 MONTHS TO TEST
1. 2026-01-01 to 2026-01-31 (January)
2. 2026-02-01 to 2026-02-28 (February)
3. 2026-03-01 to 2026-03-31 (March)
4. 2026-04-01 to 2026-04-30 (April)

## EXECUTION PATTERN

For each model, run all 4 months sequentially:

```powershell
$env:PYTHONIOENCODING="utf-8"; python backtest.py --from 2026-01-01 --to 2026-01-31 --model MODEL_NAME > bt_MODEL_jan.txt 2>&1
$env:PYTHONIOENCODING="utf-8"; python backtest.py --from 2026-02-01 --to 2026-02-28 --model MODEL_NAME > bt_MODEL_feb.txt 2>&1
$env:PYTHONIOENCODING="utf-8"; python backtest.py --from 2026-03-01 --to 2026-03-31 --model MODEL_NAME > bt_MODEL_mar.txt 2>&1
$env:PYTHONIOENCODING="utf-8"; python backtest.py --from 2026-04-01 --to 2026-04-30 --model MODEL_NAME > bt_MODEL_apr.txt 2>&1
```

Replace MODEL_NAME with actual model name. Use short prefixes:
- mb (momentum_breakout)
- sb (structural_breakout)
- sib (silver_bullet)
- lgb (liquidity_grab_bos)

So filenames become: bt_mb_jan.txt, bt_sb_feb.txt, etc.

## AFTER EACH MODEL'S 4 MONTHS COMPLETE

Read all 4 result files and extract:
- Total signals
- Filled count
- Ghost count
- Win rate
- SL rate
- Net PnL
- Average win / Average loss
- R:R ratio

Then read the model breakdown section to confirm only that model fired.

## DOCUMENTATION FORMAT

Create a file `phase1_results.md` and append to it after each model. Extract ALL of the following data from each scan output:

```markdown
## MODEL: momentum_breakout

### January 2026 (bt_mb_jan.txt)
**Verdict line:** [from output]
**Signal counts:**
- Total signals: X
- Filled: X
- Ghost: X
- Blocked: X

**Performance:**
- Win rate: X%
- SL rate: X%
- Net PnL: X pips
- Expectancy: X pips per filled trade
- Avg win: +Xp
- Avg loss: -Xp
- Win/Loss ratio: X:1

**Each filled signal:**
| Date/Time | Direction | Entry | SL | TP1 | TP3 | Score | Zone | Outcome | PnL |
|-----------|-----------|-------|-----|-----|-----|-------|------|---------|-----|
| 2026-01-XX HH:MM | BUY/SELL | XXXX | XXXX | XXXX | XXXX | XX | premium/discount | TP3_HIT/SL_HIT/RUNNER | +/-XXX |

**Each ghost signal:**
| Date/Time | Direction | Entry | SL | TP1 | TP3 | Score | Zone | Reason ghosted |
|-----------|-----------|-------|-----|-----|-----|-------|------|----------------|

**Sessions when fired:**
- london: X signals
- new_york: X signals
- overlap: X signals
- asian: X signals

**Top kill switches (if any debug data):**
- KILL: [reason] — X times

**Notes:**
- Any patterns observed
- Specific market conditions (trending bull/bear/ranging)
- Anomalies

### February 2026 (bt_mb_feb.txt)
[same complete format]

### March 2026 (bt_mb_mar.txt)
[same complete format]

### April 2026 (bt_mb_apr.txt)
[same complete format]

### SUMMARY for momentum_breakout
- Months profitable: X/4
- Average winrate: X%
- Total signals across 4 months: X
- Total filled: X
- Total ghosts: X
- Total wins: X
- Total losses: X
- Combined PnL across 4 months: X pips
- Best month: [month] — [why it worked]
- Worst month: [month] — [why it failed]
- Pattern: [does it work in trending? ranging? specific session?]
- Verdict: KEEP / FIX / DROP
- If FIX needed: specific issue identified
```

Use this EXACT format for all 4 models so data is comparable.

## DATA EXTRACTION COMMANDS

For each result file, run these to get the data:

```powershell
# Verdict and summary
Get-Content bt_MODEL_MONTH.txt | Select-Object -Last 25

# Model breakdown
Get-Content bt_MODEL_MONTH.txt | Select-String "momentum|structural|fvg|silver|london|double|choch|htf|ob_|ny_|asian|liq" | Select-Object -First 20

# Individual signal details
Get-Content bt_MODEL_MONTH.txt | Select-String "BUY|SELL" | Select-Object -First 30

# Outcomes
Get-Content bt_MODEL_MONTH.txt | Select-String "SL_HIT|TP3|RUNNER|GHOST|BE_STOP|SPIKE|OPEN_AT_END" | Select-Object -First 30

# Sessions fired
Get-Content bt_MODEL_MONTH.txt | Select-String "session" | Select-Object -First 20

# Kill switches (if debug enabled)
Get-Content bt_MODEL_MONTH.txt | Select-String "KILL|blocked" | Select-Object -First 30

# Specific signal data
Get-Content bt_MODEL_MONTH.txt | Select-String "Score|Zone|sweep" | Select-Object -First 30
```

Run debug version if more detail needed:
```powershell
$env:PYTHONIOENCODING="utf-8"; python backtest.py --from DATE --to DATE --model MODEL --debug > bt_MODEL_MONTH_debug.txt 2>&1
```

## RESUMPTION LOGIC

If you start a session and `phase1_results.md` already exists:
1. Read it completely
2. Identify which model/month combinations are documented
3. Skip those, continue with the next undocumented combination
4. Append new results to the existing file

Example resumption check:
```powershell
if (Test-Path phase1_results.md) {
    Get-Content phase1_results.md | Select-String "MODEL: |### January 2026|### February 2026|### March 2026|### April 2026"
}
```

This shows what's already done. Continue from the next missing entry.

## TRACK COMPLETION STATUS

Maintain a simple progress file `phase1_progress.txt`:
```
momentum_breakout_jan: DONE
momentum_breakout_feb: DONE
momentum_breakout_mar: IN_PROGRESS
momentum_breakout_apr: PENDING
structural_breakout_jan: PENDING
...etc
```

Update this BEFORE starting each scan and AFTER it completes. So if interrupted, you know exactly where to resume.

## SCAN TIMING EXPECTATIONS

Each scan takes 45-90 minutes. Total Phase 1 time: ~24-32 hours of scan time.

You can run in background while reporting progress. Send me an update after each model completes (every 4 scans).

## ERROR HANDLING

If any scan fails:
1. Note the error in phase1_results.md
2. Continue to next scan
3. After all scans done, attempt to rerun failed scans

## DO NOT

- Do not modify engine files
- Do not apply patches
- Do not delete files
- Do not change box9_confluence.py, box8_model.py, box10_trade.py, or any engine
- Do not skip months even if results look bad
- Do not interpret results as "good enough" — just document

## WHEN PHASE 1 COMPLETE

Report final phase1_results.md to me. I will review and decide on Phase 2 fixes manually. Do not proceed to Phase 2 without my explicit approval.

## START NOW

Begin with momentum_breakout January. Confirm the working directory is correct first:
```
cd C:\Users\alvin\xauusd_app\backend
ls
```

Verify backtest.py exists, then start the first scan.

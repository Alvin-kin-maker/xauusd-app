# XAUUSD Trading System — 4-Model Strategic Roadmap
# Date: April 30, 2026
# Approach: Focus on 4 highest-probability models, disable the rest

## THE 4 MODELS WE'RE KEEPING

### 1. momentum_breakout (PROVEN)
**Why kept:** 100% winrate in January, +2136 pips
**Covers:** Strong trending markets with displacement
**Logic:** Strong candle body + volume spike + breaks key level = continuation
**Status:** Working in trending months, may need transitional period filter

### 2. structural_breakout (PROVEN — partial)
**Why kept:** One massive winner in March (+2748 pips)
**Covers:** Major structural breaks/reversals
**Logic:** Fresh BOS + retest = institutional re-entry
**Status:** Works in London, fails elsewhere — restrict to London session

### 3. silver_bullet (WORTH FIXING)
**Why kept:** ICT institutional methodology, time-precise
**Covers:** High-liquidity windows (08-09, 15-16, 19-20 GMT)
**Logic:** Liquidity sweep + FVG + MSS during killzone
**Status:** Recently fixed HTF alignment, needs proper testing

### 4. liquidity_grab_bos (WORTH TESTING)
**Why kept:** Strongest ICT confluence pattern
**Covers:** Reversal entries after liquidity sweeps
**Logic:** Sweep highs/lows + immediate BOS = reversal confirmed
**Status:** Hasn't fired enough yet, logic is sound

---

## MODELS WE'RE DISABLING

These will be permanently turned off in box8 priority list:
- fvg_continuation (ghosts in trends, loses on bounces)
- choch_reversal (ghosts constantly)
- double_top_bottom_trap (counter-trend losses)
- htf_level_reaction (fires counter-trend)
- ob_mitigation (counter-trend losses)
- ob_fvg_stack (fires often, ghosts always)
- london_sweep_reverse (never fills)
- ny_continuation (barely fires)
- asian_range_breakout (ghosts)

---

## TESTING PLAN

### Phase 1 — Individual Model Testing (Days 1-3)

#### Day 1: momentum_breakout (4 months)
**Morning:**
- Test January: `--model momentum_breakout`
- Document: signals, wins, losses, ghosts, exact entry conditions
**Afternoon:**
- Test February same way
**Evening:**
- Test March same way
**Night/Next morning:**
- Test April same way

**Output:** Performance matrix
| Month | Signals | Wins | Losses | Ghosts | WR% | PnL | R:R |

#### Day 2: structural_breakout (4 months)
Same testing structure as Day 1
Special focus: Compare London vs other sessions

#### Day 3: silver_bullet + liquidity_grab_bos (combined day)
- Morning/afternoon: silver_bullet 4 months
- Evening: liquidity_grab_bos 4 months

### Phase 2 — Targeted Fixes (Days 4-6)

Based on Phase 1 results, fix only what's clearly broken.

For each model that fails:
1. Identify the exact losing pattern (counter-trend? wrong session? bad SL?)
2. Apply ONE targeted fix
3. Re-test ONLY that model in the failing month
4. If fix works, move on. If not, try alternative.

**Time budget per model:** 1 day max for fixes
**Hard rule:** If a model can't reach 60% winrate in any month after 2 fix attempts, DISABLE IT.

### Phase 3 — Combined Testing (Day 7-8)

Run all 4 working models together across 4 months.

**Success criteria:**
- 60%+ overall winrate
- 8-15 fills per month minimum
- Profitable in 3/4 months
- No single trade loss exceeds 200 pips

If 4 models combined doesn't meet these — drop the weakest model and test with 3.

### Phase 4 — Telegram Bot + Paper Trade (Days 9-23)

Day 9: Build Telegram bot
Day 10-23: Paper trading (signals received, no trades placed)
- Verify live signals match backtest
- Track which signals would have won/lost
- Compare to backtest expectations

### Phase 5 — Live Trading (Day 24+)

Start with 0.01 lots. Trade every signal. Review weekly.

---

## DAILY EXECUTION SCHEDULE

### Today (Day 1)
**Right now:** Test momentum_breakout January
```
$env:PYTHONIOENCODING="utf-8"; python backtest.py --from 2026-01-01 --to 2026-01-31 --model momentum_breakout > bt_mb_jan.txt 2>&1
```

**Then in sequence:**
```
$env:PYTHONIOENCODING="utf-8"; python backtest.py --from 2026-02-01 --to 2026-02-28 --model momentum_breakout > bt_mb_feb.txt 2>&1
$env:PYTHONIOENCODING="utf-8"; python backtest.py --from 2026-03-01 --to 2026-03-31 --model momentum_breakout > bt_mb_mar.txt 2>&1
$env:PYTHONIOENCODING="utf-8"; python backtest.py --from 2026-04-01 --to 2026-04-30 --model momentum_breakout > bt_mb_apr.txt 2>&1
```

Can run in parallel terminals to save time.

### After all 4 momentum_breakout scans complete
Paste:
```
Get-Content bt_mb_jan.txt | Select-Object -Last 20
Get-Content bt_mb_feb.txt | Select-Object -Last 20
Get-Content bt_mb_mar.txt | Select-Object -Last 20
Get-Content bt_mb_apr.txt | Select-Object -Last 20
```

---

## TOTAL TIMELINE

| Phase | Days | Activity |
|-------|------|----------|
| Phase 1 | 3 | Individual model testing |
| Phase 2 | 3 | Targeted fixes |
| Phase 3 | 2 | Combined testing |
| Phase 4 | 15 | Bot + paper trading |
| Phase 5 | ongoing | Live trading |

**Total to live: ~3-4 weeks**

---

## SUCCESS CRITERIA (no fluff)

System ready when:
- [ ] 4 models each tested across 4 months
- [ ] Combined 60%+ winrate consistently
- [ ] 8+ fills per month minimum
- [ ] R:R minimum 2:1 average
- [ ] Profitable in 3/4 backtest months
- [ ] Profitable in 2 weeks paper trading

If criteria not met after Phase 3, we reassess — possibly drop to 2-3 models.

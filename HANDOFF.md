# XAUUSD Trading System — Project Handoff
# Created: 2026-04-26
# Status: Backtesting phase, targeting 75%+ winrate

## SYSTEM OVERVIEW
Gold (XAUUSD) algorithmic trading system built in Python.
- Backend: FastAPI + MetaTrader5 (MT5) data feed
- Frontend: Flutter mobile app
- Data: Real MT5 candles, all timeframes M5→MN
- Location: C:\Users\alvin\xauusd_app\backend\

## CURRENT BACKTEST STATUS

### January 2026 (bullish trending month):
- Signals: 7 | Filled: 2 | Ghost: 5 | Winrate: 50% | PnL: +465 pips
- momentum_breakout: 100% winrate, fills correctly, structural SL works
- Problem: Ghost rate 71% — fvg_continuation, double_top_bottom_trap, structural_breakout all ghosting

### March 2026 (900-pip crash month):
- Last result: 0% winrate, all signals BUY in downtrend
- Problem: COT kill + discount zone kill blocking valid SELL signals
- March 3 13:10 diagnostic: direction=SELL, should_trade=False due to kill switches

### Target: 75%+ winrate, 15-20 fills per month, <20% ghost rate

## ROOT CAUSES IDENTIFIED (in priority order)

### 1. Ghost rate — ROOT CAUSE IN box7_entry.py
`price_at_zone()` was using `proximity=5.0` (50 pips hardcoded).
FIXED to use `ATR * 0.15` (~25 pips dynamic).
BUT: fvg_continuation validates when `has_fvg` (FVG exists anywhere) not just `at_fvg`.
Entry is placed at FVG midpoint which is often 10-20 points below current price in trends.
Price never pulls back to fill — ghost.
REAL FIX NEEDED: fvg_continuation must require `at_fvg=True` AND entry must be at current_price
when `at_fvg` triggers, not at the midpoint.

### 2. March direction — KILL SWITCHES too aggressive
Two kills block valid SELLs:
- COT kill: fires when COT >75% long even when H1+M15+H4 all bearish (wrong)
- Discount zone kill: requires H1+M15+H4 all bearish but H4 lags 4-8h during reversals
PARTIAL FIX in box9_confluence.py:
- COT: now checks `selling_counter_trend = (sell AND H1=bullish AND M15=bullish)` before blocking
- Discount: added `intraday_sell_valid = H1+M15 bearish AND (D1 not strongly bullish OR MSS active)`

### 3. SL too tight on some models
structural_breakout: 25-pip SL = noise level on gold (ATR ~170 pips in Jan)
momentum_breakout: SL uses M15 swing low capped at 2x ATR — working correctly
fvg_continuation: SL at FVG proximal edge - ATR*0.15 — needs verification

### 4. momentum_breakout entry wrong side (FIXED)
Was: `entry = current_price + 0.3` for BUY (above price = never fills correctly)
Fixed: `entry = current_price - 0.3`

## FILES MODIFIED (all in engines/ folder unless noted)

| File | What changed |
|------|-------------|
| engines/box2_trend.py | BOS recency limit 50 bars — old BOS doesn't override current swing structure |
| engines/box7_entry.py | price_at_zone proximity: 5.0 → ATR*0.15 |
| engines/box8_model.py | momentum_breakout requires `at_fvg` not just `has_fvg` |
| engines/box9_confluence.py | resolve_direction: H1+M15 primary, no HTF gate blocking pullback trades |
| engines/box9_confluence.py | Kill switch #6: H4+H1 conflict (not D1+H4) |
| engines/box9_confluence.py | COT kill: only blocks counter-trend (H1+M15 agree with direction = allow) |
| engines/box9_confluence.py | Discount zone kill: H1+M15 bearish + MSS active = allow SELL even if H4 bullish |
| engines/box9_confluence.py | Exhaustion kills: only fire when trading AGAINST H1+M15 (not with-trend) |
| engines/box10_trade.py | momentum_breakout SL: M15 swing low capped at 2x ATR |
| engines/box10_trade.py | _smart_fvg: SL at proximal edge not proximal-ATR |
| engines/box10_trade.py | _smart_ob: SL at distal edge not proximal-ATR |
| engines/box10_trade.py | SL_MIN_PIPS: raised from 25 to 50 (25-pip SL = noise) |
| engines/box3_liquidity.py | run() accepts session_override param for backtest accuracy |
| backtest.py | H4 cache → H1 cache (box2 updates per H1 bar not H4) |
| backtest.py | Invalid entry filter: BUY entry must be <= current price |
| backtest.py | Stale entry: tightened from 1x ATR to 0.5x ATR |
| backtest.py | Ghost timeout: 48 bars → 6 bars (30 min) for all models |
| backtest.py | OPEN_AT_END with >50 pips profit counts as WIN in stats |

## WHAT NEEDS FIXING NEXT (in order)

### Priority 1 — Ghost rate (biggest impact)
fvg_continuation (box8_model.py line 906-911):
Currently validates when `has_fvg AND h1_bias != neutral AND score >= 60`
Should validate when `at_fvg AND h1_bias != neutral AND score >= 60`
AND in box10_trade.py _smart_fvg: when `at_fvg_now=True`, entry = current_price not midpoint

double_top_bottom_trap: same issue — entry placed at pattern level not current price
structural_breakout: 25-pip SL too tight — needs structural SL like momentum_breakout
choch_reversal: entry at OB level below current price — same ghost issue

### Priority 2 — Signal count (too few signals)
Only momentum_breakout reliably fires and fills.
Other 12 models either ghost or get blocked.
Need: 15-20 fills per month = need 4-5 models working not just 1.

### Priority 3 — March SELL signals
Verify box9 COT and discount zone fixes actually allow SELL on March 3.
Run diagnose_deep.py on March 3 13:10 after fixes to confirm should_trade=True.

## KEY DIAGNOSTIC TOOLS

### verify_engines.py (in backend/ root)
Confirms which version of each engine is loaded.
Run: `python verify_engines.py`

### diagnose_deep.py (in backend/ root)  
Shows exactly what b2, b3, b9 output on specific bars.
Shows resolve_direction priority trace and kill switches.
Run: `python diagnose_deep.py`
Edit CHECK_TIMES list to test specific dates.

### verify_trade.py (in backend/ root)
Verifies backtest outcome against real M1 data.
Confirms if SL/TP was genuinely hit or if engine reported wrong outcome.
Run: `python verify_trade.py`

## HOW TO RUN BACKTESTS
```
cd C:\Users\alvin\xauusd_app\backend
del data\news_cache.json
python backtest.py --from 2026-01-01 --to 2026-01-31 --debug
python backtest.py --from 2026-03-01 --to 2026-03-31 --debug
```

## WHAT A GOOD RESULT LOOKS LIKE
- January: 15+ signals, <20% ghost, 65%+ winrate, positive PnL
- March: Mix of BUY (early month) and SELL (after March 6 crash), some wins
- Both months positive = system works in bull AND bear conditions

## ARCHITECTURE SUMMARY
```
main.py → runs FastAPI server
engines/
  box1_market_context.py  — session, ATR, spread check
  box2_trend.py           — H1/M15/H4/D1 bias, BOS, MSS detection  ← MODIFIED
  box3_liquidity.py       — sweeps, PDH/PDL, asian range            ← MODIFIED
  box4_levels.py          — key levels, VWAP, pivots, price zone
  box5_momentum.py        — RSI, volume, divergence
  box6_sentiment.py       — COT data (CFTC, weekly)
  box7_entry.py           — OB/FVG detection, price_at_zone         ← MODIFIED
  box8_model.py           — 13 trading models, validation           ← MODIFIED
  box9_confluence.py      — direction resolver, kill switches        ← MODIFIED
  box10_trade.py          — entry/SL/TP calculation                 ← MODIFIED
  box11_news.py           — news calendar filter
  box12_analytics.py      — performance tracking
  box13_breakout.py       — breakout/consolidation detection
data/
  candle_store.py         — MT5 data management
utils/
  config.py               — all parameters
backtest.py               — historical simulation engine            ← MODIFIED
```

## TELEGRAM BOT (future — after system works)
Plan: webhook from FastAPI /signal endpoint → Telegram bot API
When signal fires with should_trade=True → send alert with entry/SL/TP
Simple implementation once signal quality is confirmed.
Don't build until January AND March both show 65%+ winrate.

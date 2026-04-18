# ============================================================
# box9_confluence.py — Confluence Engine
# Aggregates all 8 engines into a single trade signal
# Score 0-100 → STRONG / MODERATE / WEAK / NO TRADE
# FIX: Consolidation kill only if BOTH M15 AND H1 are consolidating
# FIX: H1 consolidation check added from b13
# FIX: COT sweep exception with ATR-adjusted sweeps
# ============================================================

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import (
    CONFLUENCE_WEIGHTS,
    CONFLUENCE_STRONG_THRESHOLD,
    CONFLUENCE_MODERATE_THRESHOLD,
    CONFLUENCE_WEAK_THRESHOLD,
    REQUIRED_ENGINES_FOR_TRADE,
)


# ------------------------------------------------------------
# SIGNAL GRADE
# ------------------------------------------------------------

def grade_signal(score):
    if score >= CONFLUENCE_STRONG_THRESHOLD:
        return "STRONG"
    elif score >= CONFLUENCE_MODERATE_THRESHOLD:
        return "MODERATE"
    elif score >= CONFLUENCE_WEAK_THRESHOLD:
        return "WEAK"
    else:
        return "NO_TRADE"


# ------------------------------------------------------------
# DIRECTION RESOLVER
# ------------------------------------------------------------

def resolve_direction(b2, b3, b7, b8):
    """
    Determine trade direction from engine signals.
    Priority: Fresh sweep reversal → Active model → Entry bias → Trend bias

    ICT principle: a fresh liquidity sweep OVERRIDES stale HTF bias.
    When price sweeps SSL and reverses UP, that is a BUY regardless of D1 trend.
    The sweep IS the new directional information.
    """
    # ── HIGHEST PRIORITY: Fresh sweep reversal ─────────────────
    # If a sweep just happened on a major level, that defines direction
    # This overrides stale D1/H4 bearish/bullish bias
    if b3.get("sweep_just_happened"):
        sweep_dir = b3.get("sweep_direction", "")
        # bearish_sweep = highs swept (wick above high, close below) = SELL reversal
        # bullish_sweep = lows swept  (wick below low, close above)  = BUY reversal
        if sweep_dir in ("bearish", "bearish_sweep"):
            return "sell"
        elif sweep_dir in ("bullish", "bullish_sweep"):
            return "buy"

    # Active model tells us direction from sweep + structure
    if b8["active_model"]:
        model_name = b8["best_model_name"] or ""

        # London sweep reverse: opposite of sweep direction
        if model_name == "london_sweep_reverse":
            if b3["asian_high_swept"]:
                return "sell"
            elif b3["asian_low_swept"]:
                return "buy"

        # Liquidity grab: opposite of sweep — only when sweep ACTUALLY happened
        # If no fresh sweep, sweep_direction is stale and must not override H1+M15
        if model_name == "liquidity_grab_bos":
            if b3.get("sweep_just_happened", False):
                sweep_dir = b3.get("sweep_direction", "")
                # Lows swept (bullish_sweep) = SSL grabbed = institutions buy = BUY
                # Highs swept (bearish_sweep) = BSL grabbed = institutions sell = SELL
                if sweep_dir in ("bullish", "bullish_sweep"):
                    return "buy"
                elif sweep_dir in ("bearish", "bearish_sweep"):
                    return "sell"
            # No fresh sweep → fall through to H1+M15 check

        # CHOCH reversal: direction of CHOCH
        if model_name == "choch_reversal":
            m15_struct = b2["timeframes"]["M15"]["structure"]
            if m15_struct == "bullish":
                return "buy"
            elif m15_struct == "bearish":
                return "sell"

    # ── PRIORITY 3: H1 + M15 structural agreement ──────────────
    # When H1 and M15 BOTH agree, this is a valid early trend signal.
    # This OVERRIDES stale entry bias from b7 (old OBs/FVGs that no longer apply).
    # H4 needs 4 candles to confirm new structure — H1+M15 catch it early.
    h1_bias  = b2["timeframes"]["H1"]["bias"]
    m15_bias = b2["timeframes"]["M15"]["bias"]
    if h1_bias == m15_bias and h1_bias not in ("neutral", "unknown", "ranging"):
        if h1_bias == "bullish":
            return "buy"
        elif h1_bias == "bearish":
            return "sell"

    # ── PRIORITY 4: Entry bias from b7 (only if H1+M15 disagree) ──
    # Only use this if H1 and M15 are mixed — avoids stale OB override
    entry_bias = b7["entry_bias"]
    if entry_bias == "bullish":
        return "buy"
    elif entry_bias == "bearish":
        return "sell"

    # ── PRIORITY 5: D1 trend as final fallback ──
    d1_bias = b2["timeframes"]["D1"]["bias"]
    if d1_bias == "bullish":
        return "buy"
    elif d1_bias == "bearish":
        return "sell"

    return "none"


# ------------------------------------------------------------
# ENGINE SCORER — each engine contributes weighted score
# ------------------------------------------------------------

def score_b1(b1):
    """Market Context — is the environment tradeable?"""
    s = b1["engine_score"]
    breakdown = {
        "raw":    s,
        "weight": CONFLUENCE_WEIGHTS["market_context"],
        "contribution": round(s * CONFLUENCE_WEIGHTS["market_context"] / 100, 1),
        "notes": []
    }
    if b1["is_tradeable"]:
        breakdown["notes"].append(f"Session: {b1['primary_session']}")
    if b1["volatility_regime"] in ["high", "extreme"]:
        breakdown["notes"].append(f"ATR: {b1['atr']} (active)")
    if not b1["spread_acceptable"]:
        breakdown["notes"].append("⚠ Wide spread")
    return breakdown


def score_b2(b2, direction):
    """Trend — is the trend aligned with direction?"""
    alignment_score = 0
    notes           = []

    bias_map = {
        "MN":  (b2["timeframes"]["MN"]["bias"],  1),
        "W1":  (b2["timeframes"]["W1"]["bias"],  2),
        "D1":  (b2["timeframes"]["D1"]["bias"],  3),
        "H4":  (b2["timeframes"]["H4"]["bias"],  3),
        "H1":  (b2["timeframes"]["H1"]["bias"],  2),
        "M15": (b2["timeframes"]["M15"]["bias"], 2),
        "M5":  (b2["timeframes"]["M5"]["bias"],  1),
    }

    dir_bias = "bullish" if direction == "buy" else "bearish"
    total_weight = sum(w for _, (_, w) in bias_map.items())
    weighted_hits = 0

    for tf, (bias, weight) in bias_map.items():
        if bias == dir_bias:
            weighted_hits += weight
            notes.append(f"{tf}: {bias} ✓")
        elif bias != "neutral":
            notes.append(f"{tf}: {bias} ✗")

    alignment_score = round((weighted_hits / total_weight) * 100)

    return {
        "raw":          alignment_score,
        "weight":       CONFLUENCE_WEIGHTS["trend"],
        "contribution": round(alignment_score * CONFLUENCE_WEIGHTS["trend"] / 100, 1),
        "notes":        notes,
        "overall_bias": b2["overall_bias"],
    }


def score_b3(b3, direction):
    """Liquidity — was liquidity swept in the right direction?"""
    s     = b3["engine_score"]
    notes = []

    sweep_ok = False
    if direction == "buy":
        sweep_ok = b3["asian_low_swept"] or b3["pdl_swept"] or b3["pwl_swept"]
        if sweep_ok:
            notes.append("Lows swept before buy ✓")
    elif direction == "sell":
        sweep_ok = b3["asian_high_swept"] or b3["pdh_swept"] or b3["pwh_swept"]
        if sweep_ok:
            notes.append("Highs swept before sell ✓")

    if b3["sweep_just_happened"]:
        notes.append("Sweep just happened ✓")

    sweep_direction = b3.get("sweep_direction", "")
    sweep_direction_ok = False
    if direction == "sell" and sweep_direction == "bearish":
        sweep_direction_ok = True
        notes.append("Bearish sweep context present ✓")
    elif direction == "buy" and sweep_direction == "bullish":
        sweep_direction_ok = True
        notes.append("Bullish sweep context present ✓")

    if sweep_ok and b3["sweep_just_happened"]:
        bonus = 20
    elif sweep_ok:
        bonus = 15
    elif sweep_direction_ok and b3["total_sweeps"] > 0:
        bonus = 10
    else:
        bonus = 0

    final = min(s + bonus, 100)

    return {
        "raw":          final,
        "weight":       CONFLUENCE_WEIGHTS["liquidity"],
        "contribution": round(final * CONFLUENCE_WEIGHTS["liquidity"] / 100, 1),
        "notes":        notes,
        "sweep_ok":     sweep_ok,
    }


def score_b4(b4):
    """Levels — is price at an institutional level?"""
    s     = b4["engine_score"]
    notes = []

    if b4["at_key_level"] and b4["closest_level"]:
        lvl = b4["closest_level"]
        notes.append(f"At: {lvl.get('label', 'key level')} ({lvl.get('level', '')})")
    if b4.get("vwap"):
        notes.append(f"VWAP: {b4['vwap']}")

    return {
        "raw":          s,
        "weight":       CONFLUENCE_WEIGHTS["levels"],
        "contribution": round(s * CONFLUENCE_WEIGHTS["levels"] / 100, 1),
        "notes":        notes,
    }


def score_b5(b5, direction):
    """Momentum — does RSI/volume confirm direction?"""
    s     = b5["engine_score"]
    notes = []

    dir_rsi_ok = False
    if direction == "buy":
        dir_rsi_ok = b5["rsi_m15_signal"] in ["bullish", "oversold"]
        if b5["rsi_above_mid_m15"]:
            notes.append("RSI above 50 on M15 ✓")
    elif direction == "sell":
        dir_rsi_ok = b5["rsi_m15_signal"] in ["bearish", "overbought"]
        if b5["rsi_above_mid_m15"] == False:
            notes.append("RSI below 50 on M15 ✓")

    if b5["divergence_active"]:
        notes.append(f"Divergence: {b5['divergence_type']} ✓")
    if b5["volume_m15"]["is_spike"]:
        notes.append("Volume spike ✓")
    if dir_rsi_ok:
        notes.append(f"RSI confirms direction ✓")

    return {
        "raw":          s,
        "weight":       CONFLUENCE_WEIGHTS["momentum"],
        "contribution": round(s * CONFLUENCE_WEIGHTS["momentum"] / 100, 1),
        "notes":        notes,
        "dir_rsi_ok":   dir_rsi_ok,
    }


def score_b6(b6, direction):
    """Sentiment — does institutional positioning align?"""
    s     = b6["engine_score"]
    notes = []

    cot_ok = False
    if direction == "buy" and b6["cot_sentiment"] == "bullish":
        cot_ok = True
        notes.append(f"COT bullish ({b6['cot_long_pct']}% long) ✓")
    elif direction == "sell" and b6["cot_sentiment"] == "bearish":
        cot_ok = True
        notes.append(f"COT bearish ({b6['cot_long_pct']}% long) ✓")
    elif not b6["cot_available"]:
        notes.append("COT unavailable (neutral)")
    else:
        notes.append(f"COT {b6['cot_sentiment']} vs direction {direction} ✗")

    if b6["oi_signal"] in ["strong_bullish", "weak_bullish"] and direction == "buy":
        notes.append("OI confirms bullish ✓")
    elif b6["oi_signal"] in ["strong_bearish", "weak_bearish"] and direction == "sell":
        notes.append("OI confirms bearish ✓")

    return {
        "raw":          s,
        "weight":       CONFLUENCE_WEIGHTS["sentiment"],
        "contribution": round(s * CONFLUENCE_WEIGHTS["sentiment"] / 100, 1),
        "notes":        notes,
        "cot_ok":       cot_ok,
    }


def score_b7(b7, direction, b13=None, is_breakout=False):
    """Entry — is there a valid entry zone?"""
    notes = []
    entry_ok = False

    at_zone = False
    if direction == "buy":
        if b7["at_bull_ob"]:
            entry_ok = True
            at_zone  = True
            notes.append("At bullish OB ✓")
        if b7["at_bull_fvg"]:
            entry_ok = True
            at_zone  = True
            notes.append("At bullish FVG ✓")
        if b7["at_bull_breaker"]:
            entry_ok = True
            at_zone  = True
            notes.append("At bullish breaker ✓")
    elif direction == "sell":
        if b7["at_bear_ob"]:
            entry_ok = True
            at_zone  = True
            notes.append("At bearish OB ✓")
        if b7["at_bear_fvg"]:
            entry_ok = True
            at_zone  = True
            notes.append("At bearish FVG ✓")
        if b7["at_bear_breaker"]:
            entry_ok = True
            at_zone  = True
            notes.append("At bearish breaker ✓")

    if is_breakout and b13:
        best_bo = b13.get("best_breakout")
        if best_bo and best_bo.get("direction") == direction and best_bo.get("validated"):
            s = min(best_bo.get("score", 80), 100)
            notes.append(f"Breakout entry confirmed: {best_bo.get('type','breakout')} ✓")
            return {
                "raw":          s,
                "weight":       CONFLUENCE_WEIGHTS["entry"],
                "contribution": round(s * CONFLUENCE_WEIGHTS["entry"] / 100, 1),
                "notes":        notes,
                "entry_ok":     True,
                "at_zone":      True,
                "zones_exist":  True,
                "breakout_entry": True,
            }

    zones_exist = False
    if direction == "buy":
        zones_exist = b7["bull_ob_count"] > 0 or b7["bull_fvg_count"] > 0
    elif direction == "sell":
        zones_exist = b7["bear_ob_count"] > 0 or b7["bear_fvg_count"] > 0

    if at_zone:
        s = b7["engine_score"]
        notes.append("Price at entry zone ✓")
    elif zones_exist:
        s = 50
        notes.append(f"Entry zones available — waiting for price ⏳")
    else:
        s = 0
        notes.append("No entry zones in direction ✗")

    for cp in b7["candle_patterns"]:
        if (cp["signal"] == "bullish" and direction == "buy") or \
           (cp["signal"] == "bearish" and direction == "sell"):
            notes.append(f"Candle: {cp['type']} ✓")

    for fib in b7["golden_fibs"]:
        notes.append(f"Golden fib: {fib['label']} at {fib['level']}")

    return {
        "raw":          s,
        "weight":       CONFLUENCE_WEIGHTS["entry"],
        "contribution": round(s * CONFLUENCE_WEIGHTS["entry"] / 100, 1),
        "notes":        notes,
        "entry_ok":     entry_ok,
        "at_zone":      at_zone,
        "zones_exist":  zones_exist,
    }


def score_b8(b8):
    """Model — did a model validate?"""
    s     = b8["engine_score"]
    notes = []

    if b8["model_validated"]:
        notes.append(f"Active: {b8['best_model_name']} ✓")
        notes.append(f"Validated: {b8['validated_count']}/10 models")
        for name, m in b8["validated_models"].items():
            notes.append(f"  {name}: {m['score']}")
    else:
        notes.append("No model validated ✗")

    return {
        "raw":          s,
        "weight":       CONFLUENCE_WEIGHTS["model"],
        "contribution": round(s * CONFLUENCE_WEIGHTS["model"] / 100, 1),
        "notes":        notes,
    }


# ------------------------------------------------------------
# KILL SWITCHES — conditions that override everything
# ------------------------------------------------------------

def check_kill_switches(b1, b2, b3, b4, b5, b6, b7, b8, b13, direction=None):
    """
    Hard rules that block any trade regardless of score.
    Returns list of active kill switches.
    FIX: Consolidation only blocks if BOTH M15 AND H1 are consolidating
    FIX: Added H1 consolidation detection
    """
    kills = []
    
    current_price = b4.get("current_price")
    sweep_just_happened = b3.get("sweep_just_happened", False)
    sweep_direction = b3.get("sweep_direction", "")
    if direction is None:
        direction = resolve_direction_simple(b2, b3, b8)
    
    # 1. Untradeable session
    if not b1["is_tradeable"]:
        kills.append(f"KILL: Untradeable session ({b1['primary_session']})")

    # 1b. Block pre-real-London hours
    # MT5 broker time is UTC+3. box1 treats broker time as GMT.
    # Real London = UTC 07:00-16:00 = broker 10:00-19:00.
    # Signals before broker 10:00 = actually Asian session (pre-London).
    # Signals after broker 19:00 = actually pure NY (post-London).
    # Mar 4 07:05 and 07:30 broker = Asian session spikes. Block these.
    try:
        _gmt_str = b1.get("current_gmt", "12:00")
        _gmt_hour = int(_gmt_str.split(":")[0]) if _gmt_str else 12
        if _gmt_hour < 10:
            kills.append(f"KILL: Pre-London hours (broker {_gmt_str}) — Asian session, low liquidity")
    except Exception:
        pass

    # 2. Spread too wide
    if not b1["spread_acceptable"]:
        kills.append(f"KILL: Spread too wide ({b1['spread_pips']} pips)")

    # 3. Dead market OR extreme volatility black swan
    if b1["volatility_regime"] == "dead":
        kills.append("KILL: Dead market (ATR too low)")
    elif b1.get("volatility_regime") == "extreme":
        # ATR > 15pts = 8x normal = unscheduled black swan (e.g. Trump tariff day ATR=30)
        # SL placement meaningless in these conditions — block all new entries
        kills.append(f"KILL: Extreme volatility (ATR={b1.get('atr',0):.1f}pts) — black swan, no new entries")

    # 4. No model validated
    if not b8["model_validated"]:
        kills.append("KILL: No model validated")

    # 4b. liquidity_grab_bos requires a FRESH sweep
    # Without a fresh sweep, LGB fires on stale OBs repeatedly = losses
    model_name = b8.get("best_model_name", "")
    if model_name == "liquidity_grab_bos":
        if not b3.get("sweep_just_happened", False):
            kills.append("KILL: liquidity_grab_bos requires fresh sweep — no recent sweep detected")

    # 5a. H4 fresh BOS opposing direction = block
    # If H4 just broke structure in the opposite direction of our trade,
    # the move is likely to continue against us. This is what caused all
    # the Mar 5, Mar 11, Mar 17 losses: H4 broke bearish then system bought.
    h4_data = b2["timeframes"]["H4"]
    h4_bos_active = h4_data.get("bos_active", False)
    h4_bias = h4_data.get("bias", "neutral")
    if h4_bos_active and h4_bias != "neutral":
        if direction == "buy" and h4_bias == "bearish":
            kills.append(f"KILL: H4 fresh bearish BOS — H4 just broke structure down, don't buy")
        elif direction == "sell" and h4_bias == "bullish":
            kills.append(f"KILL: H4 fresh bullish BOS — H4 just broke structure up, don't sell")

    # 5b. H4 ranging MID-RANGE = no trade
    h4_structure = b2["timeframes"]["H4"]["structure"]
    if h4_structure in ["ranging", "neutral"]:
        h4_last_sh = b2["timeframes"]["H4"].get("last_sh")
        h4_last_sl = b2["timeframes"]["H4"].get("last_sl")
        if h4_last_sh and h4_last_sl and current_price:
            range_high = float(h4_last_sh["price"]) if isinstance(h4_last_sh, dict) else float(h4_last_sh)
            range_low  = float(h4_last_sl["price"]) if isinstance(h4_last_sl, dict) else float(h4_last_sl)
            rng = range_high - range_low
            if rng > 0:
                price_pos  = (current_price - range_low) / rng
                in_mid     = 0.35 < price_pos < 0.65
                if in_mid:
                    kills.append(f"KILL: H4 ranging + price at mid-range ({round(price_pos*100)}%) — wait for boundary")

    # 6. Bias conflict — block ONLY if BOTH D1 AND H4 oppose the trade direction
    # ICT: D1 bullish + H4 bearish pullback + BUY = valid entry (DON'T block)
    #      D1 bearish + H4 bearish + BUY = fighting both HTF trends (BLOCK)
    # H4 alone being against direction = normal pullback = don't block
    internal_bias = b2.get("internal_bias", "neutral")
    external_bias = b2.get("external_bias", "neutral")  # H4
    d1_bias = b2["timeframes"]["D1"]["bias"]
    if (internal_bias != "neutral" and external_bias != "neutral"
            and internal_bias != external_bias
            and not sweep_just_happened):
        d1_vs_dir = (
            (direction == "buy"  and d1_bias == "bearish") or
            (direction == "sell" and d1_bias == "bullish")
        )
        h4_vs_dir = (
            (direction == "buy"  and external_bias == "bearish") or
            (direction == "sell" and external_bias == "bullish")
        )
        if d1_vs_dir and h4_vs_dir:
            kills.append(f"KILL: Bias conflict — D1 ({d1_bias}) and H4 ({external_bias}) both oppose {direction} without sweep")

    # 7. CONSOLIDATION KILL SWITCH — FIXED: Check BOTH M15 AND H1
    # Get consolidation from b13 (M15 based)
    m15_consolidation = b13.get("consolidation", {}).get("was_consolidating", False)
    
    # Get H1 consolidation from b13
    h1_consolidation = b13.get("h1_consolidation", {}).get("was_consolidating", False)
    
    # Only block if BOTH M15 AND H1 are consolidating AND not at an OB/FVG
    if m15_consolidation and h1_consolidation:
        range_high = b13.get("consolidation", {}).get("range_high")
        range_low  = b13.get("consolidation", {}).get("range_low")
        if range_high and range_low and current_price:
            range_size = range_high - range_low
            if range_size > 0:
                price_position = (current_price - range_low) / range_size
                at_boundary    = price_position > 0.85 or price_position < 0.15
                at_entry_zone  = b7.get("price_at_entry_zone", False) if b7 else False
                if not at_boundary and not at_entry_zone:
                    kills.append("KILL: M15 + H1 both consolidating — price in mid-range — wait for boundary")
                elif at_boundary and not sweep_just_happened and not at_entry_zone:
                    kills.append("KILL: M15 + H1 both consolidating — at boundary — waiting for sweep before entry")
    # If only M15 consolidating but H1 trending — ALLOW (no kill)

    # 8. No HTF alignment at all
    htf_biases = [
        b2["timeframes"]["MN"]["bias"],
        b2["timeframes"]["W1"]["bias"],
        b2["timeframes"]["D1"]["bias"],
    ]
    if all(b == "neutral" for b in htf_biases):
        kills.append("KILL: All HTF neutral — no directional bias")

    # 9. RSI extreme counter-direction
    rsi_m15 = b5.get("rsi_m15") or 50
    if direction == "sell" and rsi_m15 < 20:
        kills.append(f"KILL: RSI {round(rsi_m15,1)} extreme oversold — no sells at exhaustion")
    elif direction == "buy" and rsi_m15 > 80:
        kills.append(f"KILL: RSI {round(rsi_m15,1)} extreme overbought — no buys at exhaustion")

    # 10. Move exhaustion — M15, H1, D1 checks
    atr_raw = b1.get("atr") or 2.0
    # CAP ATR at 10.0 for exhaustion calculations.
    # During news spikes ATR can hit 30+ (300pip candles), inflating thresholds 10x.
    # This would make exhaustion kills fire only after 4000+ pip moves — useless.
    # Capped ATR ensures safety net always works: max threshold = 10*8 = 800pip for D1.
    atr = min(float(atr_raw), 10.0)
    if atr > 0 and not sweep_just_happened and current_price:
        # M15 exhaustion
        m15_data = b2.get("timeframes", {}).get("M15", {})
        last_sh = m15_data.get("last_sh")
        last_sl = m15_data.get("last_sl")
        if last_sh and last_sl:
            sh_price = float(last_sh["price"]) if isinstance(last_sh, dict) else float(last_sh)
            sl_price = float(last_sl["price"]) if isinstance(last_sl, dict) else float(last_sl)
            drop_from_high = sh_price - current_price
            rise_from_low  = current_price - sl_price
            if direction == "sell" and drop_from_high > atr * 4:
                kills.append(f"KILL: M15 move exhaustion — price dropped {round(drop_from_high*10,0)} pips ({round(drop_from_high/atr,1)}x ATR)")
            elif direction == "buy" and rise_from_low > atr * 4:
                kills.append(f"KILL: M15 move exhaustion — price rose {round(rise_from_low*10,0)} pips ({round(rise_from_low/atr,1)}x ATR)")
        
        # H1 exhaustion — only fires for RECENT swings (within 20 H1 bars = 20 hours)
        # Prevents "1885 pips from H1 low" blocking during multi-day bull runs
        h1_data = b2.get("timeframes", {}).get("H1", {})
        h1_last_sh = h1_data.get("last_sh")
        h1_last_sl = h1_data.get("last_sl")
        h1_candle_count = h1_data.get("candle_count", 300)
        if h1_last_sh and h1_last_sl:
            h1_sh_price  = float(h1_last_sh["price"]) if isinstance(h1_last_sh, dict) else float(h1_last_sh)
            h1_sl_price  = float(h1_last_sl["price"]) if isinstance(h1_last_sl, dict) else float(h1_last_sl)
            h1_sh_idx    = int(h1_last_sh["index"])   if isinstance(h1_last_sh, dict) else 0
            h1_sl_idx    = int(h1_last_sl["index"])   if isinstance(h1_last_sl, dict) else 0
            h1_sh_recency = h1_candle_count - h1_sh_idx
            h1_sl_recency = h1_candle_count - h1_sl_idx
            h1_drop = h1_sh_price - current_price
            h1_rise = current_price - h1_sl_price
            if direction == "sell" and h1_drop > atr * 4 and h1_sh_recency <= 20:
                kills.append(f"KILL: H1 move exhaustion — price dropped {round(h1_drop*10,0)} pips from recent H1 high")
            elif direction == "buy" and h1_rise > atr * 4 and h1_sl_recency <= 20:
                kills.append(f"KILL: H1 move exhaustion — price rose {round(h1_rise*10,0)} pips from recent H1 low")

        # D1 exhaustion — catches "2400pip run, now buying pullback" scenarios
        # If price has risen >8x ATR from D1 swing low → extended move, dangerous to buy
        # If price has dropped >8x ATR from D1 swing high → extended move, dangerous to sell
        d1_data = b2.get("timeframes", {}).get("D1", {})
        d1_sh = d1_data.get("last_sh")
        d1_sl = d1_data.get("last_sl")
        if d1_sh and d1_sl:
            d1_sh_price = float(d1_sh["price"]) if isinstance(d1_sh, dict) else float(d1_sh)
            d1_sl_price = float(d1_sl["price"]) if isinstance(d1_sl, dict) else float(d1_sl)
            d1_drop = d1_sh_price - current_price
            d1_rise = current_price - d1_sl_price
            # 8x ATR threshold for D1 — only block truly exhausted multi-day moves
            if direction == "sell" and d1_drop > atr * 8:
                kills.append(f"KILL: D1 move exhaustion — {round(d1_drop*10,0)} pips from D1 high — selling into extended drop")
            elif direction == "buy" and d1_rise > atr * 8:
                kills.append(f"KILL: D1 move exhaustion — {round(d1_rise*10,0)} pips from D1 low — buying into extended rally")

    # 11. COT extreme counter-direction — with sweep exception
    cot_long_pct  = b6.get("cot_long_pct", 50)
    cot_available = b6.get("cot_available", False)
    if cot_available and cot_long_pct is not None:
        # EXCEPTION: Bullish COT + bearish sweep = VALID sell setup (liquidity grab before reversal)
        if cot_long_pct >= 75 and sweep_just_happened and sweep_direction == "bearish" and direction == "sell":
            # This is the liquidity grab BEFORE reversal — ALLOW
            pass
        elif cot_long_pct <= 25 and sweep_just_happened and sweep_direction == "bullish" and direction == "buy":
            # This is the liquidity grab BEFORE reversal — ALLOW
            pass
        # Otherwise, block
        elif direction == "sell" and cot_long_pct >= 75:
            kills.append(f"KILL: COT extreme bullish ({cot_long_pct}% long) — no sweep reversal context")
        elif direction == "buy" and cot_long_pct <= 25:
            kills.append(f"KILL: COT extreme bearish ({cot_long_pct}% long) — no sweep reversal context")
    elif not cot_available:
        kills.append("KILL: COT data unavailable — manual block until verified")

    # 12. Selling in discount / buying in premium — absolute zone rule
    # Premium = institutions sell. Discount = institutions buy. No sweep bypass.
    # A sweep sets direction but doesn't override the zone. The direction resolver
    # already ensures BUY comes from discount context (lows swept = price in discount).
    price_zone = b4.get("price_zone", "unknown")
    if direction == "sell" and price_zone == "discount":
        kills.append(
            f"KILL: Selling in discount zone — "
            f"price below equilibrium, institutions buy here not sell"
        )
    elif direction == "buy" and price_zone == "premium":
        kills.append(
            f"KILL: Buying in premium zone — "
            f"price above equilibrium, institutions sell here not buy"
        )

    return kills


def resolve_direction_simple(b2, b3, b8):
    """Simple direction resolver for kill switch context."""
    if b8.get("best_model_name"):
        sweep_dir = b3.get("sweep_direction")
        if sweep_dir == "bearish": return "sell"
        if sweep_dir == "bullish": return "buy"
    d1 = b2["timeframes"]["D1"]["bias"]
    if d1 == "bearish": return "sell"
    if d1 == "bullish": return "buy"
    return None


# ------------------------------------------------------------
# CONFLUENCE SUMMARY
# ------------------------------------------------------------

def build_summary(direction, score, grade, scored_engines, kill_switches, b8):
    """Human-readable summary of the confluence analysis."""

    lines = [
        f"Direction: {direction.upper()}",
        f"Score:     {score}/100",
        f"Grade:     {grade}",
        "",
    ]

    if kill_switches:
        lines.append("⛔ KILL SWITCHES ACTIVE:")
        for k in kill_switches:
            lines.append(f"  {k}")
        lines.append("")

    lines.append("Engine Contributions:")
    for engine_name, data in scored_engines.items():
        bar  = "█" * int(data["contribution"] / 2)
        lines.append(
            f"  {engine_name:20} {data['contribution']:5.1f}pts "
            f"({data['raw']:3}/100 × {data['weight']}%)"
        )

    if b8["model_validated"]:
        lines.append(f"\nActive Model: {b8['best_model_name']}")

    return "\n".join(lines)


# ------------------------------------------------------------
# MAIN ENGINE FUNCTION
# ------------------------------------------------------------

def run(b1, b2, b3, b4, b5, b6, b7, b8, b13=None):
    """
    Aggregate all engine outputs into final confluence score.

    Returns:
        direction:  buy / sell / none
        score:      0-100
        grade:      STRONG / MODERATE / WEAK / NO_TRADE
        should_trade: True if grade >= MODERATE and no kill switches
    """
    # Resolve direction
    direction = resolve_direction(b2, b3, b7, b8)

    # Kill switches
    kill_switches = check_kill_switches(b1, b2, b3, b4, b5, b6, b7, b8, b13, direction)

    # Score each engine
    is_breakout_model = b8.get("best_model_name") in ["momentum_breakout", "structural_breakout"]
    scored_engines = {
        "market_context": score_b1(b1),
        "trend":          score_b2(b2, direction),
        "liquidity":      score_b3(b3, direction),
        "levels":         score_b4(b4),
        "momentum":       score_b5(b5, direction),
        "sentiment":      score_b6(b6, direction),
        "entry":          score_b7(b7, direction, b13=b13, is_breakout=is_breakout_model),
        "model":          score_b8(b8),
    }

    # Total weighted score
    total_score = sum(e["contribution"] for e in scored_engines.values())
    total_score = round(min(total_score, 100), 1)

    # Grade
    grade = grade_signal(total_score)

    # Should trade?
    hard_blocked   = len(kill_switches) > 0
    grade_ok       = grade in ["STRONG"]
    model_required = b8["model_validated"]

    should_trade = (
        not hard_blocked and
        grade_ok and
        model_required and
        direction != "none"
    )

    if hard_blocked:
        grade = "NO_TRADE"

    active_model = b8["active_model"]

    summary = build_summary(direction, total_score, grade, scored_engines, kill_switches, b8)

    return {
        "direction":       direction,
        "score":           total_score,
        "grade":           grade,
        "should_trade":    should_trade,

        "kill_switches":   kill_switches,
        "hard_blocked":    hard_blocked,

        "engines":         scored_engines,

        "active_model":    active_model,
        "model_name":      b8["best_model_name"],
        "model_score":     b8["best_model_score"],
        "validated_count": b8["validated_count"],

        "summary":         summary,

        "entry_zone":      b7["at_bull_ob"] or b7["at_bear_ob"] or
                           b7["at_bull_fvg"] or b7["at_bear_fvg"],
        "atr":             b1["atr"],
        "session":         b1["primary_session"],
    }


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------

if __name__ == "__main__":
    import MetaTrader5 as mt5
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data.candle_store import store
    from engines.box1_market_context import run as run_b1
    from engines.box2_trend          import run as run_b2
    from engines.box3_liquidity      import run as run_b3
    from engines.box4_levels         import run as run_b4
    from engines.box5_momentum       import run as run_b5
    from engines.box6_sentiment      import run as run_b6
    from engines.box7_entry          import run as run_b7
    from engines.box8_model          import run as run_b8
    from engines.box13_breakout      import run as run_b13

    print("Testing Box 9 — Confluence Engine")
    print("=" * 50)

    mt5.initialize()
    store.refresh()

    b1 = run_b1(store)
    b2 = run_b2(store)
    b3 = run_b3(store)
    b4 = run_b4(store)
    b5 = run_b5(store)
    b6 = run_b6(store)
    b7 = run_b7(store, b2)
    b13 = run_b13(store, b1, b2, b3, b4, b5, b7)
    b8 = run_b8(b1, b2, b3, b4, b5, b6, b7, b13)

    result = run(b1, b2, b3, b4, b5, b6, b7, b8, b13)

    print(f"\n{'='*50}")
    print(result["summary"])
    print(f"{'='*50}")
    print(f"\nShould Trade: {result['should_trade']}")
    if result["kill_switches"]:
        print("Kill Switches:")
        for k in result["kill_switches"]:
            print(f"  {k}")
    print(f"\nEngine Breakdown:")
    for name, data in result["engines"].items():
        print(f"  {name:20}: {data['raw']:3}/100 → {data['contribution']:.1f}pts")
        for note in data["notes"][:2]:
            print(f"    {note}")

    mt5.shutdown()
    print("\nBox 9 Test PASSED ✓")
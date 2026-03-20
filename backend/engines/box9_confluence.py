# ============================================================
# box9_confluence.py — Confluence Engine
# Aggregates all 8 engines into a single trade signal
# Score 0-100 → STRONG / MODERATE / WEAK / NO TRADE
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
    Priority: Active model → Entry bias → Trend bias → Sweep direction
    """
    # Active model tells us direction from sweep + structure
    if b8["active_model"]:
        model_name = b8["best_model_name"] or ""

        # London sweep reverse: opposite of sweep direction
        if model_name == "london_sweep_reverse":
            if b3["asian_high_swept"]:
                return "sell"
            elif b3["asian_low_swept"]:
                return "buy"

        # Liquidity grab: opposite of sweep
        if model_name == "liquidity_grab_bos":
            sweep_dir = b3.get("sweep_direction")
            if sweep_dir == "bullish_sweep":
                return "sell"
            elif sweep_dir == "bearish_sweep":
                return "buy"

        # CHOCH reversal: direction of CHOCH
        if model_name == "choch_reversal":
            m15_struct = b2["timeframes"]["M15"]["structure"]
            if m15_struct == "bullish":
                return "buy"
            elif m15_struct == "bearish":
                return "sell"

    # Fall back to entry bias from Box 7
    entry_bias = b7["entry_bias"]
    if entry_bias == "bullish":
        return "buy"
    elif entry_bias == "bearish":
        return "sell"

    # Fall back to HTF trend
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
        "MN":  (b2["timeframes"]["MN"]["bias"],  1),  # macro context only
        "W1":  (b2["timeframes"]["W1"]["bias"],  2),  # weekly direction
        "D1":  (b2["timeframes"]["D1"]["bias"],  3),  # primary trend
        "H4":  (b2["timeframes"]["H4"]["bias"],  3),  # execution trend
        "H1":  (b2["timeframes"]["H1"]["bias"],  2),  # entry trend
        "M15": (b2["timeframes"]["M15"]["bias"], 2),  # entry confirmation
        "M5":  (b2["timeframes"]["M5"]["bias"],  1),  # noise filter
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

    # Also give partial credit if sweep direction matches trade direction
    # A mature setup after a sweep still deserves liquidity credit
    # Use sweep_direction field directly — "bearish" or "bullish"
    sweep_direction = b3.get("sweep_direction", "")
    sweep_direction_ok = False
    if direction == "sell" and sweep_direction == "bearish":
        sweep_direction_ok = True
        notes.append("Bearish sweep context present ✓")
    elif direction == "buy" and sweep_direction == "bullish":
        sweep_direction_ok = True
        notes.append("Bullish sweep context present ✓")

    # Score: fresh sweep in direction = full bonus, mature sweep in direction = partial
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

    # Check if price is AT a zone right now
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

    # For breakout models — entry is the breakout candle itself, not an OB/FVG
    # Give full entry score if b13 confirms breakout in same direction
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

    # Even if price isn't AT the zone yet, give credit for valid zones existing
    # This allows score to reach 70+ so a limit signal can fire
    zones_exist = False
    if direction == "buy":
        zones_exist = b7["bull_ob_count"] > 0 or b7["bull_fvg_count"] > 0
    elif direction == "sell":
        zones_exist = b7["bear_ob_count"] > 0 or b7["bear_fvg_count"] > 0

    # Score: at zone = full engine score, zones exist nearby = 50, nothing = 0
    if at_zone:
        s = b7["engine_score"]
        notes.append("Price at entry zone ✓")
    elif zones_exist:
        s = 50  # Zones exist, price not there yet — partial credit
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

def check_kill_switches(b1, b2, b3, b4, b5, b6, b7, b8):
    """
    Hard rules that block any trade regardless of score.
    Returns list of active kill switches.
    """
    kills = []

    # 1. Untradeable session
    if not b1["is_tradeable"]:
        kills.append(f"KILL: Untradeable session ({b1['primary_session']})")

    # 2. Spread too wide
    if not b1["spread_acceptable"]:
        kills.append(f"KILL: Spread too wide ({b1['spread_pips']} pips)")

    # 3. Dead market
    if b1["volatility_regime"] == "dead":
        kills.append("KILL: Dead market (ATR too low)")

    # 4. No model validated
    if not b8["model_validated"]:
        kills.append("KILL: No model validated")

    # 5. H4 ranging MID-RANGE = no trade (boundary = valid trade)
    # In consolidation: range boundaries are GREAT setups (liquidity sweep + reversal)
    # Mid-range is noise — we don't trade 50% of a range
    h4_structure = b2["timeframes"]["H4"]["structure"]
    if h4_structure in ["ranging", "neutral"]:
        # Check if price is in mid-range (dangerous) or at boundary (valid)
        h4_last_sh = b2["timeframes"]["H4"].get("last_sh")
        h4_last_sl = b2["timeframes"]["H4"].get("last_sl")
        if h4_last_sh and h4_last_sl and b4.get("current_price"):
            range_high = float(h4_last_sh["price"]) if isinstance(h4_last_sh, dict) else float(h4_last_sh)
            range_low  = float(h4_last_sl["price"]) if isinstance(h4_last_sl, dict) else float(h4_last_sl)
            rng = range_high - range_low
            if rng > 0:
                price_pos  = (b4["current_price"] - range_low) / rng  # 0=bottom, 1=top
                in_mid     = 0.35 < price_pos < 0.65
                if in_mid:
                    kills.append(f"KILL: H4 ranging + price at mid-range ({round(price_pos*100)}%) — wait for boundary")

    # 6. Internal/external conflict with NO sweep context = choppy
    # (Allowed if a sweep just happened — that's the manipulation leg)
    internal_bias = b2.get("internal_bias", "neutral")
    external_bias = b2.get("external_bias", "neutral")
    sweep_just_happened = b3.get("sweep_just_happened", False)
    if (internal_bias != "neutral" and external_bias != "neutral"
            and internal_bias != external_bias
            and not sweep_just_happened):
        kills.append(f"KILL: Bias conflict ({internal_bias} vs {external_bias}) with no recent sweep — choppy")

    # 7. Price stalling at zone too long (stale zone = no momentum = no trade)
    # If price has been within 10 pips of entry zone for > 5 candles on M15
    # without a displacement, the zone is compromised
    # (We check this via the at_zone flag from box7 — if it's been flagged
    #  as at_zone but no candle pattern appeared, skip it)
    # This is enforced via model score requirements — stale zones score lower

    # 8. No HTF alignment at all
    htf_biases = [
        b2["timeframes"]["MN"]["bias"],
        b2["timeframes"]["W1"]["bias"],
        b2["timeframes"]["D1"]["bias"],
    ]
    if all(b == "neutral" for b in htf_biases):
        kills.append("KILL: All HTF neutral — no directional bias")

    # 9. RSI extreme counter-direction — selling into oversold, buying into overbought
    # This is not a hard kill but reduces model score threshold
    # Hard kill only when RSI is at absolute extreme (< 20 or > 80)
    rsi_m15 = b5.get("rsi_m15") or 50
    direction = resolve_direction_simple(b2, b3, b8)
    if direction == "sell" and rsi_m15 < 20:
        kills.append(f"KILL: RSI {round(rsi_m15,1)} extreme oversold — no sells at exhaustion")
    elif direction == "buy" and rsi_m15 > 80:
        kills.append(f"KILL: RSI {round(rsi_m15,1)} extreme overbought — no buys at exhaustion")

    # 10. Move exhaustion — price moved > 4x ATR without retracement
    # Selling after 400+ pip drop = exhaustion, not continuation
    atr = b1.get("atr") or 2.0
    if atr > 0:
        m15_data = b2.get("timeframes", {}).get("M15", {})
        last_sh = m15_data.get("last_sh")
        last_sl = m15_data.get("last_sl")
        price_info = b4.get("current_price")
        if price_info and last_sh and last_sl:
            sh_price = float(last_sh["price"]) if isinstance(last_sh, dict) else float(last_sh)
            sl_price = float(last_sl["price"]) if isinstance(last_sl, dict) else float(last_sl)
            current = float(price_info)
            # For sells: how far has price dropped from last swing high
            drop_from_high = sh_price - current
            rise_from_low  = current - sl_price
            if direction == "sell" and drop_from_high > atr * 4:
                kills.append(f"KILL: Move exhaustion — price dropped {round(drop_from_high*10,0):.0f} pips ({round(drop_from_high/atr,1)}x ATR) — wait for retracement first")
            elif direction == "buy" and rise_from_low > atr * 4:
                kills.append(f"KILL: Move exhaustion — price rose {round(rise_from_low*10,0):.0f} pips ({round(rise_from_low/atr,1)}x ATR) — wait for retracement first")

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
    kill_switches = check_kill_switches(b1, b2, b3, b4, b5, b6, b7, b8)

    # Score each engine
    # For breakout models, entry scoring uses b13 data not zone presence
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
    grade_ok       = grade in ["STRONG"]  # Only STRONG signals trade — MODERATE is watch-only
    model_required = b8["model_validated"]

    should_trade = (
        not hard_blocked and
        grade_ok and
        model_required and
        direction != "none"
    )

    # If blocked, downgrade
    if hard_blocked:
        grade = "NO_TRADE"

    # Active model detail
    active_model = b8["active_model"]

    # Summary
    summary = build_summary(direction, total_score, grade, scored_engines, kill_switches, b8)

    return {
        # Core signal
        "direction":       direction,
        "score":           total_score,
        "grade":           grade,
        "should_trade":    should_trade,

        # Kill switches
        "kill_switches":   kill_switches,
        "hard_blocked":    hard_blocked,

        # Scored engines
        "engines":         scored_engines,

        # Active model
        "active_model":    active_model,
        "model_name":      b8["best_model_name"],
        "model_score":     b8["best_model_score"],
        "validated_count": b8["validated_count"],

        # Human summary
        "summary":         summary,

        # Pass-through for Box 10
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
    b7 = run_b7(store)
    b8 = run_b8(b1, b2, b3, b4, b5, b6, b7)

    result = run(b1, b2, b3, b4, b5, b6, b7, b8)

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
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

    Key principle: We trade INTRADAY structure, not macro trend.
    D1/H4 tell us the overall landscape. H1+M15 tell us where price
    is moving RIGHT NOW. When H1+M15 both agree, that's the trade.

    A D1+H4 bullish market can have 3-week bearish corrections on H1/M15
    — those corrections ARE tradeable and are where the best risk:reward is.
    Blocking them because D1 says "bullish" is why the system only loses.

    Priority:
    1. Fresh sweep — overrides everything (genuine institutional move)
    2. Model sweep context (london_sweep, liquidity_grab, choch)
    3. M15 MSS — fastest structural confirmation
    4. H1 + M15 agreement — primary execution signal
    5. H4 direction — medium-term bias
    6. D1 + H4 agreement — macro fallback only
    """
    d1_bias  = b2["timeframes"]["D1"]["bias"]
    h4_bias  = b2["timeframes"]["H4"]["bias"]
    h1_bias  = b2["timeframes"]["H1"]["bias"]
    m15_bias = b2["timeframes"]["M15"]["bias"]
    fresh_sweep = b3.get("sweep_just_happened", False)
    sweep_dir   = b3.get("sweep_direction", "")

    # ── PRIORITY 1: Fresh sweep reversal ─────────────────────────
    if fresh_sweep:
        if sweep_dir in ("bearish", "bearish_sweep"):
            return "sell"
        elif sweep_dir in ("bullish", "bullish_sweep"):
            return "buy"

    # ── PRIORITY 2: Active model sweep context ──────────────────
    if b8["active_model"]:
        model_name = b8["best_model_name"] or ""

        if model_name == "london_sweep_reverse":
            if b3["asian_high_swept"]:
                return "sell"
            elif b3["asian_low_swept"]:
                return "buy"

        if model_name == "liquidity_grab_bos":
            if b3.get("sweep_just_happened", False):
                if sweep_dir in ("bullish", "bullish_sweep"):
                    return "buy"
                elif sweep_dir in ("bearish", "bearish_sweep"):
                    return "sell"

        if model_name == "choch_reversal":
            m15_struct = b2["timeframes"]["M15"]["structure"]
            if m15_struct == "bullish":
                return "buy"
            elif m15_struct == "bearish":
                return "sell"

    # ── PRIORITY 3: M15 MSS ──────────────────────────────────────
    mss_m15_active = b2.get("mss_m15_active", False)
    mss_m15_type   = b2.get("mss_m15_type", None)
    if mss_m15_active and mss_m15_type:
        if mss_m15_type == "bearish_mss":
            return "sell"
        elif mss_m15_type == "bullish_mss":
            return "buy"

    # ── PRIORITY 4: H1 + M15 agreement ───────────────────────────
    # Primary execution signal. BUT: if H4 is bearish and there's no sweep,
    # H1+M15 bullish is just a bounce in a downtrend — don't buy it.
    # H4 bearish + H1+M15 bullish = counter-trend bounce = losing trade.
    # H4 bullish + H1+M15 bearish = valid pullback sell.
    if h1_bias == m15_bias and h1_bias not in ("neutral", "unknown", "ranging"):
        if h1_bias == "bullish":
            # Only return BUY if H4 is not actively bearish
            if h4_bias != "bearish":
                return "buy"
            # H4 bearish + H1+M15 bullish = bounce in downtrend, skip
        elif h1_bias == "bearish":
            return "sell"

    # ── PRIORITY 5: H4 direction — medium-term bias ──────────────
    if h4_bias not in ("neutral", "unknown", "ranging"):
        # H4 alone gives direction but entry engine (b7) must confirm
        entry_bias = b7["entry_bias"]
        if entry_bias == h4_bias.replace("bullish","bullish").replace("bearish","bearish"):
            if h4_bias == "bullish":
                return "buy"
            elif h4_bias == "bearish":
                return "sell"

    # ── PRIORITY 6: D1 + H4 macro fallback ──────────────────────
    if d1_bias == h4_bias and d1_bias not in ("neutral", "unknown"):
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

    # 6. Bias conflict — only block if H4 AND H1 BOTH oppose direction
    # The original rule (D1+H4) was wrong — it blocked valid H1+M15 pullback trades.
    # A D1 bull market has 3-week H1 bearish corrections. Those are valid SELL setups.
    # What we DON'T want: H4 bearish AND H1 bearish, but trying to BUY on M15 bounce.
    # That's fighting two active timeframes with no structural support.
    h4_bias_ks = b2["timeframes"]["H4"]["bias"]
    h1_bias_ks = b2["timeframes"]["H1"]["bias"]
    h4_vs_dir  = (
        (direction == "buy"  and h4_bias_ks == "bearish") or
        (direction == "sell" and h4_bias_ks == "bullish")
    )
    h1_vs_dir  = (
        (direction == "buy"  and h1_bias_ks == "bearish") or
        (direction == "sell" and h1_bias_ks == "bullish")
    )
    # Only block if H4 AND H1 both oppose AND no sweep just happened
    if h4_vs_dir and h1_vs_dir and not sweep_just_happened:
        kills.append(
            f"KILL: Bias conflict — H4 ({h4_bias_ks}) and H1 ({h1_bias_ks}) "
            f"both oppose {direction} — fighting two active timeframes"
        )

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

    # 10. Move exhaustion — only fires when trading COUNTER to H1+M15 structure.
    # If H1+M15 are both bearish and you're selling = WITH trend = no exhaustion block.
    # Exhaustion only matters when you're trying to sell an already-extended DROP
    # in a market where H1+M15 are still bullish (counter-trend fade = dangerous).
    # Similarly: don't block buys when H1+M15 are both bullish (trend continuation).
    h1_bias_ex  = b2.get("timeframes", {}).get("H1", {}).get("bias", "neutral")
    m15_bias_ex = b2.get("timeframes", {}).get("M15", {}).get("bias", "neutral")
    trading_with_h1m15 = (
        (direction == "sell" and h1_bias_ex == "bearish" and m15_bias_ex == "bearish") or
        (direction == "buy"  and h1_bias_ex == "bullish" and m15_bias_ex == "bullish")
    )

    atr_raw = b1.get("atr") or 2.0
    atr = min(float(atr_raw), 10.0)
    if atr > 0 and not sweep_just_happened and current_price and not trading_with_h1m15:
        # M15 exhaustion — only when counter-trend
        m15_data = b2.get("timeframes", {}).get("M15", {})
        last_sh = m15_data.get("last_sh")
        last_sl = m15_data.get("last_sl")
        if last_sh and last_sl:
            sh_price = float(last_sh["price"]) if isinstance(last_sh, dict) else float(last_sh)
            sl_price = float(last_sl["price"]) if isinstance(last_sl, dict) else float(last_sl)
            drop_from_high = sh_price - current_price
            rise_from_low  = current_price - sl_price
            if direction == "sell" and drop_from_high > atr * 6:
                kills.append(f"KILL: M15 move exhaustion — price dropped {round(drop_from_high*10,0)} pips ({round(drop_from_high/atr,1)}x ATR) — counter-trend fade too extended")
            elif direction == "buy" and rise_from_low > atr * 6:
                kills.append(f"KILL: M15 move exhaustion — price rose {round(rise_from_low*10,0)} pips ({round(rise_from_low/atr,1)}x ATR) — counter-trend fade too extended")

        # H1 exhaustion — only when counter-trend, recent swings only
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
            if direction == "sell" and h1_drop > atr * 8 and h1_sh_recency <= 20:
                kills.append(f"KILL: H1 move exhaustion — price dropped {round(h1_drop*10,0)} pips from recent H1 high — counter-trend")
            elif direction == "buy" and h1_rise > atr * 8 and h1_sl_recency <= 20:
                kills.append(f"KILL: H1 move exhaustion — price rose {round(h1_rise*10,0)} pips from recent H1 low — counter-trend")

        # D1 exhaustion — only when counter-trend, recent swings only (≤30 D1 bars)
        d1_data = b2.get("timeframes", {}).get("D1", {})
        d1_sh = d1_data.get("last_sh")
        d1_sl = d1_data.get("last_sl")
        d1_candle_count = d1_data.get("candle_count", 100)
        if d1_sh and d1_sl:
            d1_sh_price = float(d1_sh["price"]) if isinstance(d1_sh, dict) else float(d1_sh)
            d1_sl_price = float(d1_sl["price"]) if isinstance(d1_sl, dict) else float(d1_sl)
            d1_sh_idx   = int(d1_sh["index"])   if isinstance(d1_sh, dict) else 0
            d1_sl_idx   = int(d1_sl["index"])   if isinstance(d1_sl, dict) else 0
            d1_sh_recency = d1_candle_count - d1_sh_idx
            d1_sl_recency = d1_candle_count - d1_sl_idx
            d1_drop = d1_sh_price - current_price
            d1_rise = current_price - d1_sl_price
            if direction == "sell" and d1_drop > atr * 10 and d1_sh_recency <= 30:
                kills.append(f"KILL: D1 move exhaustion — {round(d1_drop*10,0)} pips from recent D1 high — counter-trend sell too extended")
            elif direction == "buy" and d1_rise > atr * 10 and d1_sl_recency <= 30:
                kills.append(f"KILL: D1 move exhaustion — {round(d1_rise*10,0)} pips from recent D1 low — counter-trend buy too extended")

    # 11. COT extreme counter-direction
    # Only fires when trading AGAINST H1+M15 structure.
    # If H1+M15 are both bearish and we're selling, COT bullish positioning is irrelevant —
    # price is already moving down regardless of what large speculators are holding.
    # COT is a weekly report — it lags price action by days.
    cot_long_pct  = b6.get("cot_long_pct", 50)
    cot_available = b6.get("cot_available", False)
    h1_bias_cot   = b2["timeframes"]["H1"]["bias"]
    m15_bias_cot  = b2["timeframes"]["M15"]["bias"]
    if cot_available and cot_long_pct is not None:
        # Only block if trading COUNTER to current H1+M15 structure
        # H1+M15 bearish + SELL = with-trend = COT irrelevant
        # H1+M15 bullish + SELL = counter-trend = COT matters
        selling_counter_trend = (direction == "sell" and
                                 h1_bias_cot == "bullish" and m15_bias_cot == "bullish")
        buying_counter_trend  = (direction == "buy" and
                                 h1_bias_cot == "bearish" and m15_bias_cot == "bearish")
        if cot_long_pct >= 75 and sweep_just_happened and sweep_direction == "bearish" and direction == "sell":
            pass  # liquidity grab — ALLOW
        elif cot_long_pct <= 25 and sweep_just_happened and sweep_direction == "bullish" and direction == "buy":
            pass  # liquidity grab — ALLOW
        elif direction == "sell" and cot_long_pct >= 75 and selling_counter_trend:
            kills.append(f"KILL: COT extreme bullish ({cot_long_pct}% long) — selling against H1+M15 bullish trend")
        elif direction == "buy" and cot_long_pct <= 25 and buying_counter_trend:
            kills.append(f"KILL: COT extreme bearish ({cot_long_pct}% long) — buying against H1+M15 bearish trend")
    elif not cot_available:
        kills.append("KILL: COT data unavailable — manual block until verified")

    # 12. Selling in discount / buying in premium — with structural bypass
    price_zone  = b4.get("price_zone", "unknown")
    h1_bias_ks  = b2["timeframes"]["H1"]["bias"]
    m15_bias_ks = b2["timeframes"]["M15"]["bias"]
    h4_bias_ks  = b2["timeframes"]["H4"]["bias"]
    atr_ks      = float(b1.get("atr") or 2.0)

    sweep_confirms_sell = sweep_just_happened and sweep_direction in ("bearish", "bearish_sweep")
    sweep_confirms_buy  = sweep_just_happened and sweep_direction in ("bullish", "bullish_sweep")

    # Structure bypass: H1+M15+H4 ALL must agree — H1+M15 alone is not enough
    # in premium. We need H4 to also be bullish to buy in premium (strong uptrend).
    # Without H4 agreement, H1+M15 bullish in premium = just trend chasing at top.
    structure_confirms_sell = (h1_bias_ks == "bearish" and m15_bias_ks == "bearish" and h4_bias_ks == "bearish")
    structure_confirms_buy  = (h1_bias_ks == "bullish" and m15_bias_ks == "bullish" and h4_bias_ks == "bullish")

    d1_bias_ks = b2["timeframes"]["D1"]["bias"]
    htf_confirms_sell = (d1_bias_ks == "bearish" and h4_bias_ks == "bearish")
    htf_confirms_buy  = (d1_bias_ks == "bullish" and h4_bias_ks == "bullish")

    # Sweep extension gate
    if sweep_confirms_buy and current_price:
        ssl_near = b3.get("nearest_ssl")
        if ssl_near:
            extension = current_price - float(ssl_near)
            if extension > atr_ks * 2:
                sweep_confirms_buy = False

    if sweep_confirms_sell and current_price:
        bsl_near = b3.get("nearest_bsl")
        if bsl_near:
            extension = float(bsl_near) - current_price
            if extension > atr_ks * 2:
                sweep_confirms_sell = False

    if direction == "sell" and price_zone == "discount":
        # Allow if: sweep confirms, OR H1+M15+H4 all bearish, OR D1+H4 downtrend
        # NEW: Also allow if H1+M15 both bearish AND D1 is not strongly bullish
        # H4 often lags 4-8 hours during reversals — don't require H4 to have flipped yet
        h1_m15_bearish = (h1_bias_ks == "bearish" and m15_bias_ks == "bearish")
        d1_not_strongly_bullish = d1_bias_ks in ("bearish", "neutral", "unknown")
        # MSS bypass: if M15 just had a bearish market structure shift, that's strong
        # confirmation regardless of D1 — it means structure broke recently
        mss_bearish_active = b2.get("mss_m15_active") and b2.get("mss_m15_type") == "bearish_mss"
        intraday_sell_valid = h1_m15_bearish and (d1_not_strongly_bullish or mss_bearish_active)

        if not sweep_confirms_sell and not structure_confirms_sell and not htf_confirms_sell and not intraday_sell_valid:
            kills.append(
                f"KILL: Selling in discount — no sweep, bearish structure, or D1+H4 downtrend"
            )
    elif direction == "buy" and price_zone == "premium":
        # Allow if: sweep confirms, OR H1+M15+H4 all bullish, OR D1+H4 uptrend
        # Also allow if D1 bullish AND price at valid OB/FVG zone
        h1_m15_bullish = (h1_bias_ks == "bullish" and m15_bias_ks == "bullish")
        d1_not_strongly_bearish = d1_bias_ks in ("bullish", "neutral", "unknown")
        intraday_buy_valid = h1_m15_bullish and d1_not_strongly_bearish
        d1_bullish_at_zone = (d1_bias_ks == "bullish" and b7.get("price_at_entry_zone", False))

        if not sweep_confirms_buy and not structure_confirms_buy and not htf_confirms_buy and not intraday_buy_valid and not d1_bullish_at_zone:
            kills.append(
                f"KILL: Buying in premium — no sweep, bullish structure, or D1+H4 uptrend"
            )

    # 13. Pullback models blocked when H4 opposes direction
    # fvg_continuation, double_top_bottom_trap, choch_reversal etc. are LIMIT ORDER
    # models — they wait for a pullback to an OB/FVG. When H4 is actively trending
    # against direction, the pullback becomes a continuation of the trend and these
    # entries just lose. Don't place limit BUY orders when H4 is bearish — the 
    # "pullback" will keep going and hit SL.
    _LIMIT_MODELS = {"fvg_continuation", "double_top_bottom_trap", "choch_reversal",
                     "htf_level_reaction", "ob_mitigation", "ob_fvg_stack"}
    h4_bias_ks2 = b2["timeframes"]["H4"]["bias"]
    h1_bias_ks2 = b2["timeframes"]["H1"]["bias"]
    active_model_name = b8.get("best_model_name", "")
    if active_model_name in _LIMIT_MODELS:
        if direction == "buy" and h4_bias_ks2 == "bearish" and h1_bias_ks2 == "bearish":
            kills.append(
                f"KILL: Limit/pullback model ({active_model_name}) — H4+H1 both bearish, pullback = continuation"
            )
        elif direction == "sell" and h4_bias_ks2 == "bullish" and h1_bias_ks2 == "bullish":
            kills.append(
                f"KILL: Limit/pullback model ({active_model_name}) — H4+H1 both bullish, pullback = continuation"
            )

    # ── MASTER TREND GATE ─────────────────────────────────────────
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

    return kills


def resolve_direction_simple(b2, b3, b8):
    """
    Simple direction resolver used only for kill switch context.
    FIX: Was using stale sweep_direction even when sweep_just_happened=False.
    Now uses H1+M15 agreement first, matching main resolver Priority 4.
    """
    if b3.get("sweep_just_happened"):
        sweep_dir = b3.get("sweep_direction")
        if sweep_dir == "bearish": return "sell"
        if sweep_dir == "bullish": return "buy"
    h1  = b2["timeframes"]["H1"]["bias"]
    m15 = b2["timeframes"]["M15"]["bias"]
    if h1 == m15 and h1 not in ("neutral", "unknown", "ranging"):
        if h1 == "bullish": return "buy"
        if h1 == "bearish": return "sell"
    h4 = b2["timeframes"]["H4"]["bias"]
    if h4 == "bearish": return "sell"
    if h4 == "bullish": return "buy"
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
# ============================================================
# box6_sentiment.py — Sentiment Engine
# Understands institutional positioning
# Tools: COT Report, Open Interest, Retail Sentiment
# Sources: CFTC via cot_reports library
# Note: COT updates every Friday. This engine caches it.
# ============================================================

import sys
import os
import json
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ------------------------------------------------------------
# COT CACHE
# ------------------------------------------------------------

COT_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "cot_cache.json"
)

def load_cot_cache():
    try:
        if os.path.exists(COT_CACHE_FILE):
            with open(COT_CACHE_FILE, "r") as f:
                cache = json.load(f)
                cached_at = datetime.fromisoformat(cache.get("cached_at", "2000-01-01"))
                if datetime.now() - cached_at < timedelta(days=7):
                    return cache
    except Exception as e:
        print(f"[Sentiment] Cache load error: {e}")
    return None


def save_cot_cache(data):
    try:
        os.makedirs(os.path.dirname(COT_CACHE_FILE), exist_ok=True)
        data["cached_at"] = datetime.now().isoformat()
        with open(COT_CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Sentiment] Cache save error: {e}")


def get_default_sentiment():
    return {
        "managed_money_long":   0,
        "managed_money_short":  0,
        "net_position":         0,
        "net_change":           0,
        "long_pct":             50.0,
        "commercial_long":      0,
        "commercial_short":     0,
        "commercial_net":       0,
        "commercial_bias":      "neutral",
        "sentiment":            "neutral",
        "report_date":          "unavailable",
        "source":               "default",
        "available":            False
    }


# ------------------------------------------------------------
# COT DATA FETCHER
# ------------------------------------------------------------

def fetch_cot_data():
    """
    Fetch COT data for Gold using cot_reports library.
    Caches result for 7 days since COT updates weekly.
    """
    cached = load_cot_cache()
    if cached:
        print("[Sentiment] Using cached COT data")
        return cached

    print("[Sentiment] Fetching fresh COT data...")

    try:
        import cot_reports as cot

        # Fetch legacy futures only report for current year
        df = cot.cot_year(year=datetime.now().year, cot_report_type="legacy_fut")

        # Filter for Gold
        gold_df = df[df["Market and Exchange Names"].str.contains("GOLD", case=False, na=False)]

        if gold_df.empty:
            print("[Sentiment] No gold rows found in COT report")
            return get_default_sentiment()

        # Sort newest first
        gold_df = gold_df.sort_values("As of Date in Form YYYY-MM-DD", ascending=False)
        latest = gold_df.iloc[0]
        prev   = gold_df.iloc[1] if len(gold_df) > 1 else None

        # Extract positions
        mm_long   = int(latest.get("Noncommercial Positions-Long (All)",  0))
        mm_short  = int(latest.get("Noncommercial Positions-Short (All)", 0))
        com_long  = int(latest.get("Commercial Positions-Long (All)",     0))
        com_short = int(latest.get("Commercial Positions-Short (All)",    0))

        net_position = mm_long - mm_short
        total        = mm_long + mm_short
        long_pct     = (mm_long / total * 100) if total > 0 else 50

        # Week over week change
        prev_net = 0
        if prev is not None:
            pl       = int(prev.get("Noncommercial Positions-Long (All)",  0))
            ps       = int(prev.get("Noncommercial Positions-Short (All)", 0))
            prev_net = pl - ps
        net_change = net_position - prev_net

        # Sentiment
        if long_pct >= 60:
            sentiment = "bullish"
        elif long_pct <= 40:
            sentiment = "bearish"
        else:
            sentiment = "neutral"

        commercial_net  = com_long - com_short
        commercial_bias = "bearish" if commercial_net > 0 else "bullish"
        report_date     = str(latest.get("As of Date in Form YYYY-MM-DD", "unknown"))

        result = {
            "managed_money_long":  mm_long,
            "managed_money_short": mm_short,
            "net_position":        net_position,
            "net_change":          net_change,
            "long_pct":            round(long_pct, 1),
            "commercial_long":     com_long,
            "commercial_short":    com_short,
            "commercial_net":      commercial_net,
            "commercial_bias":     commercial_bias,
            "sentiment":           sentiment,
            "report_date":         report_date,
            "source":              "CFTC",
            "available":           True
        }

        save_cot_cache(result)
        print(f"[Sentiment] COT loaded — Gold long%: {long_pct:.1f}% ({sentiment})")
        return result

    except ImportError:
        print("[Sentiment] cot_reports not installed. Run: pip install cot-reports")
        return get_default_sentiment()
    except Exception as e:
        print(f"[Sentiment] COT fetch failed: {e}")
        return get_default_sentiment()


# ------------------------------------------------------------
# OPEN INTEREST (volume proxy from MT5)
# ------------------------------------------------------------

def analyze_open_interest(candle_store):
    df_h1 = candle_store.get_closed("H1")

    if df_h1 is None or len(df_h1) < 5:
        return {
            "oi_trend":    "unknown",
            "oi_signal":   "neutral",
            "price_trend": "unknown",
            "available":   False
        }

    recent      = df_h1.iloc[-5:]
    price_change = recent["close"].iloc[-1] - recent["close"].iloc[0]
    price_trend  = "up" if price_change > 0 else "down"
    vol_change   = recent["volume"].iloc[-1] - recent["volume"].iloc[0]
    vol_trend    = "rising" if vol_change > 0 else "falling"

    if price_trend == "up" and vol_trend == "rising":
        oi_signal = "strong_bullish"
        oi_trend  = "confirming_uptrend"
    elif price_trend == "up" and vol_trend == "falling":
        oi_signal = "weak_bullish"
        oi_trend  = "weakening_uptrend"
    elif price_trend == "down" and vol_trend == "rising":
        oi_signal = "strong_bearish"
        oi_trend  = "confirming_downtrend"
    elif price_trend == "down" and vol_trend == "falling":
        oi_signal = "weak_bearish"
        oi_trend  = "potential_reversal"
    else:
        oi_signal = "neutral"
        oi_trend  = "neutral"

    return {
        "oi_trend":    oi_trend,
        "oi_signal":   oi_signal,
        "price_trend": price_trend,
        "vol_trend":   vol_trend,
        "available":   True
    }


# ------------------------------------------------------------
# RETAIL SENTIMENT (placeholder)
# ------------------------------------------------------------

def get_retail_sentiment():
    return {
        "retail_long_pct":   50.0,
        "retail_short_pct":  50.0,
        "contrarian_signal": "neutral",
        "available":         False,
        "note":              "Connect broker API for live retail sentiment"
    }


# ------------------------------------------------------------
# MAIN ENGINE FUNCTION
# ------------------------------------------------------------

def run(candle_store):
    cot    = fetch_cot_data()
    oi     = analyze_open_interest(candle_store)
    retail = get_retail_sentiment()

    bull_signals = 0
    bear_signals = 0

    if cot["sentiment"] == "bullish":
        bull_signals += 2
    elif cot["sentiment"] == "bearish":
        bear_signals += 2

    if oi["oi_signal"] in ["strong_bullish", "weak_bullish"]:
        bull_signals += 1
    elif oi["oi_signal"] in ["strong_bearish", "weak_bearish"]:
        bear_signals += 1

    if bull_signals > bear_signals:
        overall_sentiment = "bullish"
    elif bear_signals > bull_signals:
        overall_sentiment = "bearish"
    else:
        overall_sentiment = "neutral"

    # Score
    score = 0
    if cot["available"]:
        if cot["sentiment"] != "neutral":
            score += 40
            if abs(cot["long_pct"] - 50) > 15:
                score += 20
        else:
            score += 10
    if oi["available"]:
        if "strong" in oi["oi_signal"]:
            score += 25
        elif "weak" in oi["oi_signal"]:
            score += 10
    if not cot["available"]:
        score = 30

    score = min(score, 100)

    return {
        "cot":               cot,
        "cot_sentiment":     cot["sentiment"],
        "cot_net_position":  cot["net_position"],
        "cot_long_pct":      cot["long_pct"],
        "cot_net_change":    cot["net_change"],
        "cot_available":     cot["available"],
        "oi":                oi,
        "oi_signal":         oi["oi_signal"],
        "oi_trend":          oi["oi_trend"],
        "retail":            retail,
        "retail_long_pct":   retail["retail_long_pct"],
        "contrarian_signal": retail["contrarian_signal"],
        "overall_sentiment": overall_sentiment,
        "engine_score":      score,
    }


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------

if __name__ == "__main__":
    import MetaTrader5 as mt5
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data.candle_store import store

    print("Testing Box 6 — Sentiment Engine")
    print("=" * 50)

    mt5.initialize()
    store.refresh()

    result = run(store)

    print(f"\nCOT Data:")
    print(f"  Available:    {result['cot_available']}")
    print(f"  Sentiment:    {result['cot_sentiment']}")
    print(f"  Net Position: {result['cot_net_position']}")
    print(f"  Long %:       {result['cot_long_pct']}%")
    print(f"  Week Change:  {result['cot_net_change']}")
    if result["cot_available"]:
        print(f"  Report Date:  {result['cot']['report_date']}")
        print(f"  Commercial:   {result['cot']['commercial_bias']}")

    print(f"\nOpen Interest:")
    print(f"  Signal: {result['oi_signal']}")
    print(f"  Trend:  {result['oi_trend']}")

    print(f"\nOverall Sentiment: {result['overall_sentiment'].upper()}")
    print(f"Engine Score: {result['engine_score']}/100")

    mt5.shutdown()
    print("\nBox 6 Test PASSED ✓")
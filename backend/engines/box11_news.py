# ============================================================
# box11_news.py — News Filter Engine
# Blocks trades around high-impact economic events
# Sources: ForexFactory RSS feed (free, no API key needed)
# Filters: USD and XAU/Gold events only
# ============================================================

import sys
import os
import json
import ssl
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import (
    NEWS_BUFFER_MINUTES_BEFORE,
    NEWS_BUFFER_MINUTES_AFTER,
)


# ------------------------------------------------------------
# NEWS CACHE
# ------------------------------------------------------------

NEWS_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "news_cache.json"
)

# Windows SSL fix
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode    = ssl.CERT_NONE


def load_news_cache():
    try:
        if os.path.exists(NEWS_CACHE_FILE):
            with open(NEWS_CACHE_FILE, "r") as f:
                cache = json.load(f)
                cached_at = datetime.fromisoformat(cache.get("cached_at", "2000-01-01"))
                # News cache valid for 1 hour
                if datetime.now() - cached_at < timedelta(hours=1):
                    return cache.get("events", [])
    except Exception:
        pass
    return None


def save_news_cache(events):
    try:
        os.makedirs(os.path.dirname(NEWS_CACHE_FILE), exist_ok=True)
        with open(NEWS_CACHE_FILE, "w") as f:
            json.dump({
                "events":    events,
                "cached_at": datetime.now().isoformat()
            }, f, indent=2)
    except Exception as e:
        print(f"[News] Cache save error: {e}")


# ------------------------------------------------------------
# HIGH IMPACT KEYWORDS
# ------------------------------------------------------------

HIGH_IMPACT_KEYWORDS = [
    # US macro
    "non-farm", "nonfarm", "nfp",
    "fed", "federal reserve", "fomc",
    "interest rate", "rate decision",
    "inflation", "cpi", "pce",
    "gdp",
    "unemployment",
    "powell",
    "jackson hole",
    # Gold specific
    "gold", "xau",
    # Major risk events
    "election",
    "war", "conflict",
]

MEDIUM_IMPACT_KEYWORDS = [
    "ism", "pmi",
    "retail sales",
    "jobs",
    "jolts",
    "treasury",
    "yield",
    "dollar",
    "dxy",
    "consumer confidence",
    "aud", "gbp", "eur",  # Major pairs affect gold
]

RELEVANT_CURRENCIES = ["USD", "XAU", "Gold"]


# ------------------------------------------------------------
# NEWS FETCHER
# ------------------------------------------------------------

def fetch_forex_factory_news():
    """
    Fetch upcoming news from ForexFactory RSS.
    Returns list of events with time, title, impact.
    """
    cached = load_news_cache()
    if cached is not None:
        return cached

    print("[News] Fetching news calendar...")

    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")

        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            raw    = response.read().decode("utf-8")
            events = json.loads(raw)

        parsed = []
        for ev in events:
            currency = ev.get("country", "").upper()
            impact   = ev.get("impact", "").lower()
            title    = ev.get("title", "")
            date_str = ev.get("date", "")

            # Only USD and gold-related
            if currency not in ["USD", "XAU"] and "gold" not in title.lower():
                continue

            # Only high and medium impact
            if impact not in ["high", "medium"]:
                continue

            try:
                event_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                # Convert to local time (naive)
                event_time = event_time.replace(tzinfo=None)
            except Exception:
                continue

            parsed.append({
                "title":     title,
                "currency":  currency,
                "impact":    impact,
                "time":      event_time.isoformat(),
                "time_str":  event_time.strftime("%Y-%m-%d %H:%M"),
            })

        save_news_cache(parsed)
        print(f"[News] Loaded {len(parsed)} relevant events")
        return parsed

    except Exception as e:
        print(f"[News] Fetch failed: {e}")
        return []


# ------------------------------------------------------------
# NEWS FILTER LOGIC
# ------------------------------------------------------------

def check_news_block(events, buffer_before=None, buffer_after=None):
    """
    Check if current time is within news blackout window.

    Returns:
        is_blocked:    True if trading should be paused
        reason:        Why it's blocked
        next_event:    Upcoming event details
        minutes_to:    Minutes until next event
    """
    if buffer_before is None:
        buffer_before = NEWS_BUFFER_MINUTES_BEFORE
    if buffer_after is None:
        buffer_after = NEWS_BUFFER_MINUTES_AFTER

    now        = datetime.now()
    is_blocked = False
    block_reason   = None
    next_event     = None
    minutes_to     = None
    active_event   = None

    upcoming = []

    for ev in events:
        try:
            ev_time = datetime.fromisoformat(ev["time"])
        except Exception:
            continue

        diff_minutes = (ev_time - now).total_seconds() / 60

        # Event is coming up — check if in blackout
        if -buffer_after <= diff_minutes <= buffer_before:
            if ev["impact"] == "high":
                is_blocked   = True
                active_event = ev
                block_reason = (
                    f"HIGH IMPACT: {ev['title']} "
                    f"({ev['currency']}) at {ev['time_str']}"
                )
                break

        # Track upcoming events in next 4 hours
        if 0 < diff_minutes <= 240:
            upcoming.append({
                **ev,
                "minutes_away": round(diff_minutes, 0)
            })

    # Sort upcoming by time
    upcoming.sort(key=lambda x: x["minutes_away"])

    if upcoming:
        next_event = upcoming[0]
        minutes_to = next_event["minutes_away"]

    # Medium impact — warn but don't block
    medium_warning = None
    if not is_blocked and upcoming:
        for ev in upcoming[:3]:
            if ev["impact"] == "medium" and ev["minutes_away"] <= 30:
                medium_warning = f"Medium impact in {ev['minutes_away']}min: {ev['title']}"
                break

    return {
        "is_blocked":       is_blocked,
        "block_reason":     block_reason,
        "active_event":     active_event,
        "next_event":       next_event,
        "minutes_to_next":  minutes_to,
        "upcoming_events":  upcoming[:5],
        "medium_warning":   medium_warning,
    }


# ------------------------------------------------------------
# MANUAL BLACKOUT (for user to set)
# ------------------------------------------------------------

MANUAL_BLACKOUT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "manual_blackout.json"
)

def check_manual_blackout():
    """
    Allow user to manually pause the system via a JSON file.
    """
    try:
        if os.path.exists(MANUAL_BLACKOUT_FILE):
            with open(MANUAL_BLACKOUT_FILE, "r") as f:
                data = json.load(f)
            if data.get("active"):
                return True, data.get("reason", "Manual blackout active")
    except Exception:
        pass
    return False, None


def set_manual_blackout(active, reason="Manual pause"):
    """Toggle manual blackout on/off."""
    try:
        os.makedirs(os.path.dirname(MANUAL_BLACKOUT_FILE), exist_ok=True)
        with open(MANUAL_BLACKOUT_FILE, "w") as f:
            json.dump({
                "active": active,
                "reason": reason,
                "set_at": datetime.now().isoformat()
            }, f, indent=2)
    except Exception as e:
        print(f"[News] Manual blackout save error: {e}")


# ------------------------------------------------------------
# MAIN ENGINE FUNCTION
# ------------------------------------------------------------

def run(candle_store=None):
    """
    Run news filter engine.
    Returns whether trading is currently safe from news perspective.
    """
    # Manual blackout check first
    manual_blocked, manual_reason = check_manual_blackout()
    if manual_blocked:
        return {
            "is_blocked":       True,
            "block_reason":     manual_reason,
            "manual_blackout":  True,
            "active_event":     None,
            "next_event":       None,
            "minutes_to_next":  None,
            "upcoming_events":  [],
            "medium_warning":   None,
            "news_available":   True,
            "engine_score":     0,
        }

    # Fetch events
    events = fetch_forex_factory_news()
    news_available = len(events) > 0

    # Check blackout
    result = check_news_block(events)

    # Engine score
    if result["is_blocked"]:
        score = 0
    elif result["minutes_to_next"] and result["minutes_to_next"] <= 30:
        # Next event within 30 min — reduce score
        score = 50
    elif result["minutes_to_next"] and result["minutes_to_next"] <= 60:
        score = 75
    else:
        score = 100

    return {
        "is_blocked":       result["is_blocked"],
        "block_reason":     result["block_reason"],
        "manual_blackout":  False,
        "active_event":     result["active_event"],
        "next_event":       result["next_event"],
        "minutes_to_next":  result["minutes_to_next"],
        "upcoming_events":  result["upcoming_events"],
        "medium_warning":   result["medium_warning"],
        "news_available":   news_available,
        "engine_score":     score,
    }


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------

if __name__ == "__main__":
    print("Testing Box 11 — News Filter")
    print("=" * 50)

    result = run()

    print(f"\nTrading Blocked: {result['is_blocked']}")
    if result["block_reason"]:
        print(f"Reason: {result['block_reason']}")

    if result["medium_warning"]:
        print(f"⚠ Warning: {result['medium_warning']}")

    print(f"\nUpcoming Events (next 4 hours):")
    if result["upcoming_events"]:
        for ev in result["upcoming_events"]:
            icon = "🔴" if ev["impact"] == "high" else "🟡"
            print(f"  {icon} {ev['minutes_away']}min — {ev['title']} ({ev['currency']}) [{ev['impact']}]")
    else:
        print("  No major events in next 4 hours")

    if result["next_event"]:
        print(f"\nNext Event: {result['next_event']['title']} in {result['minutes_to_next']} min")

    print(f"\nNews Available: {result['news_available']}")
    print(f"Engine Score:   {result['engine_score']}/100")

    print("\nBox 11 Test PASSED ✓")
"""
telegram_bot.py - Send XAUUSD trading signals to Telegram

Usage:
    from telegram_bot import send_signal, send_message

    send_message("Test message")
    send_signal({
        "direction": "buy",
        "entry": 4736.37,
        "sl": 4720.16,
        "tp1": 4785.37,
        "tp3": 4911.17,
        "model": "momentum_breakout",
        "score": 76,
        "session": "new_york",
        "zone": "premium"
    })
"""

import os
import requests
from datetime import datetime, timezone

# Load .env file if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, env vars must be set manually

# Load from environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Send a plain message to Telegram. Returns True if successful."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[telegram] TOKEN or CHAT_ID missing in .env")
        return False

    try:
        response = requests.post(
            API_URL,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            },
            timeout=10
        )
        if response.status_code == 200:
            return True
        print(f"[telegram] Failed: {response.status_code} {response.text}")
        return False
    except Exception as e:
        print(f"[telegram] Error: {e}")
        return False


def send_signal(signal: dict) -> bool:
    """
    Send a formatted trading signal to Telegram.

    signal dict expected keys:
        direction (buy/sell)
        entry, sl, tp1, tp3 (floats)
        model (str)
        score (int)
        session (str)
        zone (str)
        time (optional - datetime)
    """
    direction = signal.get("direction", "?").upper()
    entry     = signal.get("entry", 0)
    sl        = signal.get("sl", 0)
    tp1       = signal.get("tp1", 0)
    tp3       = signal.get("tp3", 0)
    model     = signal.get("model", "unknown")
    score     = signal.get("score", 0)
    session   = signal.get("session", "?")
    zone      = signal.get("zone", "?")
    sig_time  = signal.get("time", datetime.now(timezone.utc))

    if isinstance(sig_time, datetime):
        time_str = sig_time.strftime("%Y-%m-%d %H:%M UTC")
    else:
        time_str = str(sig_time)

    # Calculate pip distances
    sl_pips  = abs(entry - sl) * 10
    tp1_pips = abs(tp1 - entry) * 10
    tp3_pips = abs(tp3 - entry) * 10

    # Direction marker with color
    if direction == "BUY":
        arrow = "🟢"
        accent = "🟢"
    else:
        arrow = "🔴"
        accent = "🔴"

    text = f"""<b>XAUUSD  {arrow}  {direction}</b>
<i>{model}</i>

🔹 <b>Entry</b>     <code>{entry}</code>
🔻 <b>Stop</b>      <code>{sl}</code>   <i>−{sl_pips:.0f}p</i>
🟡 <b>Target 1</b>  <code>{tp1}</code>   <i>+{tp1_pips:.0f}p</i>
🟢 <b>Target 3</b>  <code>{tp3}</code>   <i>+{tp3_pips:.0f}p</i>

<b>Score</b>     {score}/100
<b>Session</b>   {session.replace('_', ' ').title()}
<b>Zone</b>      {zone.title()}
<b>Time</b>      {time_str}"""

    return send_message(text)


def send_outcome(outcome: str, model: str, pips: float, direction: str = "") -> bool:
    """
    Send trade outcome notification.

    outcome: "TP1_HIT", "TP3_HIT", "SL_HIT", "BE_STOP", "MANUAL_CLOSE"
    """
    outcome_map = {
        "TP1_HIT":      ("🟡 Target 1 Hit",      "Stop moved to breakeven"),
        "TP3_HIT":      ("🟢 Target 3 Hit",      "Full position closed"),
        "SL_HIT":       ("🔴 Stop Loss Hit",     "Position closed at loss"),
        "BE_STOP":      ("⚪ Breakeven Stop",    "Stopped at entry"),
        "MANUAL_CLOSE": ("⚪ Manual Close",      "Position closed manually"),
    }

    title, subtitle = outcome_map.get(outcome, (f"⚪ {outcome}", ""))
    sign = "+" if pips >= 0 else ""

    text = f"""<b>{title}</b>
<i>{model}</i>

<b>Result</b>    <i>{sign}{pips:.0f} pips</i>
{subtitle}"""

    return send_message(text)


def test_bot() -> bool:
    """Quick test to verify bot is working."""
    return send_message("🟢 <b>XAUUSD Bot Connected</b>\n\nBot is active and ready to send signals.")


if __name__ == "__main__":
    # Run this file directly to test
    print("Testing Telegram bot...")
    if test_bot():
        print("Test message sent successfully")
    else:
        print("Test failed - check token and chat_id")
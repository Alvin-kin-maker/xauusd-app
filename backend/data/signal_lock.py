# ============================================================
# signal_lock.py — Signal Lock & Confluence Freeze
# Once a signal fires, lock it until trade closes.
# No new signals. Confluence score frozen at signal time.
# ============================================================

import os
import json
from datetime import datetime

LOCK_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "signal_lock.json"
)


def get_default_lock():
    return {
        "locked":            False,
        "direction":         None,
        "model_name":        None,
        "frozen_score":      None,
        "frozen_grade":      None,
        "frozen_engines":    None,
        "signal_time":       None,
        "entry":             None,
        "sl":                None,
        "tp1":               None,
        "tp2":               None,
        "tp3":               None,
        "lot_size":          None,
    }


def load_lock():
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return get_default_lock()


def save_lock(data):
    try:
        with open(LOCK_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        print(f"[Lock] Save error: {e}")


def is_locked():
    """Returns True if a signal is currently active."""
    return load_lock().get("locked", False)


def lock_signal(b9, b10, b8=None):
    """
    Called when a new signal fires.
    Freezes confluence score and locks out new signals.
    """
    lock = {
        "locked":          True,
        "direction":       b9.get("direction"),
        "model_name":      b10.get("model_name"),
        "frozen_score":    b9.get("score"),
        "frozen_grade":    b9.get("grade"),
        "validated_count": b8.get("validated_count") if b8 else 0,
        "frozen_engines":  {
            name: {
                "raw":          data.get("raw"),
                "contribution": data.get("contribution"),
            }
            for name, data in b9.get("engines", {}).items()
        },
        "signal_time":    datetime.now().isoformat(),
        "entry":          b10.get("entry"),
        "sl":             b10.get("sl"),
        "tp1":            b10.get("tp1"),
        "tp2":            b10.get("tp2"),
        "tp3":            b10.get("tp3"),
        "sl_pips":        b10.get("sl_pips"),
        "lot_size":       b10.get("lot_size"),
        "entry_zone":     b10.get("entry_zone"),
    }
    save_lock(lock)
    print(f"[Lock] Signal LOCKED — {lock['direction'].upper()} | {lock['model_name']} | Score: {lock['frozen_score']}")
    return lock


def unlock_signal(reason="trade_closed"):
    """
    Called when trade closes (SL, TP, or manual).
    Unlocks system for next signal.
    """
    lock = get_default_lock()
    save_lock(lock)
    print(f"[Lock] Signal UNLOCKED — {reason}")


def get_frozen_signal():
    """
    Returns the frozen signal data if locked.
    Returns None if signal is older than 4 hours (auto-expire).
    """
    lock = load_lock()
    if not lock.get("locked"):
        return None

    # Auto-expire signals older than 4 hours
    signal_time = lock.get("signal_time")
    if signal_time:
        try:
            signal_dt = datetime.fromisoformat(signal_time)
            hours = (datetime.now() - signal_dt).total_seconds() / 3600
            if hours > 4:
                print(f"[Lock] Signal auto-expired after {round(hours, 1)}h")
                unlock_signal("auto_expired_4h")
                return None
        except Exception:
            pass

    return lock


def is_signal_stale():
    """Returns True if locked signal is older than 4 hours."""
    lock = load_lock()
    if not lock.get("locked"):
        return False
    signal_time = lock.get("signal_time")
    if not signal_time:
        return True
    try:
        signal_dt = datetime.fromisoformat(signal_time)
        return (datetime.now() - signal_dt).total_seconds() / 3600 > 4
    except Exception:
        return True
# ============================================================
# mt5_connector.py — MT5 Connection & Data Fetching
# Connects to MT5, pulls XAUUSD candles for all timeframes
# ============================================================

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import sys
import os

# Add parent directory so we can import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import (
    SYMBOL,
    TIMEFRAMES,
    ACTIVE_TIMEFRAMES,
    CANDLE_COUNT
)


# ------------------------------------------------------------
# CONNECTION
# ------------------------------------------------------------

def connect():
    """
    Initialize connection to MT5.
    MT5 must be open and running in background.
    Returns True if connected, False if failed.
    """
    if not mt5.initialize():
        print(f"[MT5] Failed to connect: {mt5.last_error()}")
        return False

    print(f"[MT5] Connected successfully")
    print(f"[MT5] Version: {mt5.version()}")
    return True


def disconnect():
    """
    Cleanly disconnect from MT5.
    Always call this when shutting down.
    """
    mt5.shutdown()
    print("[MT5] Disconnected")


def is_connected():
    """
    Check if MT5 is still connected.
    Returns True if connected.
    """
    info = mt5.terminal_info()
    return info is not None


# ------------------------------------------------------------
# SYMBOL INFO
# ------------------------------------------------------------

def get_symbol_info():
    """
    Get XAUUSD symbol details from MT5.
    Returns symbol info object or None.
    """
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        print(f"[MT5] Symbol {SYMBOL} not found")
        return None
    return info


def get_current_price():
    """
    Get current bid/ask price for XAUUSD.
    Returns dict with bid, ask, spread.
    """
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print(f"[MT5] Could not get tick for {SYMBOL}")
        return None

    return {
        "bid":    tick.bid,
        "ask":    tick.ask,
        "spread": round(tick.ask - tick.bid, 5),
        "time":   datetime.fromtimestamp(tick.time)
    }


def get_spread_pips():
    """
    Get current spread in pips.
    For XAUUSD 1 pip = 0.1
    """
    price = get_current_price()
    if price is None:
        return None
    # XAUUSD spread in pips (divide by 0.1)
    spread_pips = price["spread"] / 0.1
    return round(spread_pips, 2)


# ------------------------------------------------------------
# CANDLE FETCHING
# ------------------------------------------------------------

def get_candles(timeframe_str, count=None):
    """
    Fetch OHLCV candles for XAUUSD.

    Args:
        timeframe_str: One of "M5", "M15", "H1", "H4", "D1", "W1", "MN"
        count: Number of candles to fetch (uses config default if None)

    Returns:
        pandas DataFrame with columns:
        time, open, high, low, close, volume
        Or None if failed.
    """
    if timeframe_str not in TIMEFRAMES:
        print(f"[MT5] Unknown timeframe: {timeframe_str}")
        return None

    # Get MT5 timeframe constant
    tf_map = {
        "M1":  mt5.TIMEFRAME_M1,
        "M5":  mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1":  mt5.TIMEFRAME_H1,
        "H4":  mt5.TIMEFRAME_H4,
        "D1":  mt5.TIMEFRAME_D1,
        "W1":  mt5.TIMEFRAME_W1,
        "MN":  mt5.TIMEFRAME_MN1,
    }

    tf = tf_map.get(timeframe_str)
    if tf is None:
        print(f"[MT5] Timeframe mapping not found: {timeframe_str}")
        return None

    # Use config count if not specified
    candle_count = count or CANDLE_COUNT.get(timeframe_str, 200)

    # Fetch from MT5
    rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, candle_count)

    if rates is None or len(rates) == 0:
        print(f"[MT5] No data returned for {timeframe_str}: {mt5.last_error()}")
        return None

    # Convert to DataFrame
    df = pd.DataFrame(rates)

    # Convert time from unix timestamp to readable datetime
    df["time"] = pd.to_datetime(df["time"], unit="s")

    # Keep only what we need
    df = df[["time", "open", "high", "low", "close", "tick_volume"]].copy()
    df.rename(columns={"tick_volume": "volume"}, inplace=True)

    # Make sure it's sorted oldest to newest
    df = df.sort_values("time").reset_index(drop=True)

    return df


def get_all_timeframes():
    """
    Fetch candles for ALL active timeframes at once.
    Returns dict like:
    {
        "M5":  DataFrame,
        "M15": DataFrame,
        "H1":  DataFrame,
        ...
    }
    """
    all_data = {}

    for tf in ACTIVE_TIMEFRAMES:
        df = get_candles(tf)
        if df is not None:
            all_data[tf] = df
            print(f"[MT5] {tf}: {len(df)} candles loaded ✓")
        else:
            print(f"[MT5] {tf}: Failed to load ✗")

    return all_data


def get_latest_closed_candle(timeframe_str):
    """
    Get the most recently CLOSED candle.
    Index [0] = current forming candle (not closed yet)
    Index [1] = last closed candle ← this is what engines use
    Never calculate on an open candle to avoid repainting.
    """
    df = get_candles(timeframe_str, count=3)
    if df is None or len(df) < 2:
        return None

    # Return second to last row (last confirmed closed candle)
    return df.iloc[-2]


def get_previous_day_candle():
    """
    Get yesterday's full candle.
    Used for PDH/PDL calculations.
    """
    df = get_candles("D1", count=3)
    if df is None or len(df) < 2:
        return None
    return df.iloc[-2]


def get_previous_week_candle():
    """
    Get last week's full candle.
    Used for weekly high/low.
    """
    df = get_candles("W1", count=3)
    if df is None or len(df) < 2:
        return None
    return df.iloc[-2]


def get_previous_month_candle():
    """
    Get last month's full candle.
    Used for monthly high/low.
    """
    df = get_candles("MN", count=3)
    if df is None or len(df) < 2:
        return None
    return df.iloc[-2]


# ------------------------------------------------------------
# TEST — Run this file directly to verify MT5 connection
# ------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 50)
    print("Testing MT5 Connection...")
    print("=" * 50)

    # Step 1: Connect
    if not connect():
        print("CONNECTION FAILED — Make sure MT5 is open")
        sys.exit(1)

    # Step 2: Symbol info
    info = get_symbol_info()
    if info:
        print(f"\nSymbol:  {info.name}")
        print(f"Digits:  {info.digits}")
        print(f"Min Lot: {info.volume_min}")

    # Step 3: Current price
    price = get_current_price()
    if price:
        print(f"\nCurrent Price:")
        print(f"  Bid:    {price['bid']}")
        print(f"  Ask:    {price['ask']}")
        print(f"  Spread: {price['spread']}")
        print(f"  Time:   {price['time']}")

    # Step 4: Spread in pips
    spread = get_spread_pips()
    print(f"  Spread: {spread} pips")

    # Step 5: Fetch M5 candles
    print(f"\nFetching M5 candles...")
    df = get_candles("M5", count=10)
    if df is not None:
        print(f"Got {len(df)} candles:")
        print(df.tail(5).to_string())

    # Step 6: Fetch all timeframes
    print(f"\nFetching all timeframes...")
    all_data = get_all_timeframes()
    print(f"\nLoaded {len(all_data)} timeframes successfully")

    # Step 7: Latest closed candle
    print(f"\nLast closed H1 candle:")
    candle = get_latest_closed_candle("H1")
    if candle is not None:
        print(f"  Time:  {candle['time']}")
        print(f"  Open:  {candle['open']}")
        print(f"  High:  {candle['high']}")
        print(f"  Low:   {candle['low']}")
        print(f"  Close: {candle['close']}")
        print(f"  Vol:   {candle['volume']}")

    # Disconnect
    disconnect()

    print("\n" + "=" * 50)
    print("MT5 Connection Test PASSED ✓")
    print("=" * 50)
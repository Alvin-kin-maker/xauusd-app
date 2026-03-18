# ============================================================
# candle_store.py — Candle Data Manager
# Fetches, stores and refreshes candles for all timeframes
# Every engine pulls candles from here, not directly from MT5
# ============================================================

import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import ACTIVE_TIMEFRAMES, CANDLE_COUNT
from data.mt5_connector import (
    get_candles,
    get_previous_day_candle,
    get_previous_week_candle,
    get_previous_month_candle,
    get_current_price
)


# ------------------------------------------------------------
# CANDLE STORE — single source of truth for all candle data
# ------------------------------------------------------------

class CandleStore:
    """
    Central store for all OHLCV candle data.
    All engines call this instead of MT5 directly.
    This way MT5 is only called once per update cycle,
    not once per engine (much faster).
    """

    def __init__(self):
        # Main candle storage — dict of DataFrames per timeframe
        self.candles = {}

        # Special candles
        self.prev_day    = None
        self.prev_week   = None
        self.prev_month  = None

        # Current live price
        self.current_price = None

        # When we last updated
        self.last_update = None

        print("[CandleStore] Initialized")


    def refresh(self):
        """
        Pull fresh candles from MT5 for all timeframes.
        Call this once per candle close cycle.
        """
        print(f"[CandleStore] Refreshing all timeframes...")

        # Fetch all active timeframes
        success_count = 0
        for tf in ACTIVE_TIMEFRAMES:
            df = get_candles(tf)
            if df is not None:
                self.candles[tf] = df
                success_count += 1
                print(f"[CandleStore] {tf}: {len(df)} candles ✓")
            else:
                print(f"[CandleStore] {tf}: Failed to fetch ✗")

        # Fetch special candles
        self.prev_day   = get_previous_day_candle()
        self.prev_week  = get_previous_week_candle()
        self.prev_month = get_previous_month_candle()

        # Fetch current price
        self.current_price = get_current_price()

        # Record update time
        self.last_update = datetime.now()

        print(f"[CandleStore] Refresh complete — {success_count}/{len(ACTIVE_TIMEFRAMES)} timeframes loaded")
        print(f"[CandleStore] Last update: {self.last_update.strftime('%H:%M:%S')}")

        return success_count == len(ACTIVE_TIMEFRAMES)


    # ------------------------------------------------------------
    # GETTERS — engines use these to get candle data
    # ------------------------------------------------------------

    def get(self, timeframe_str):
        """
        Get all candles for a timeframe.
        Returns DataFrame or None.
        
        Usage:
            df = store.get("H1")
        """
        if timeframe_str not in self.candles:
            print(f"[CandleStore] No data for {timeframe_str} — did you call refresh()?")
            return None
        return self.candles[timeframe_str]


    def get_closed(self, timeframe_str):
        """
        Get candles excluding the currently forming candle.
        Use this in ALL engine calculations to avoid repainting.
        Last row = most recently closed candle.
        
        Usage:
            df = store.get_closed("H1")
            last_candle = df.iloc[-1]
        """
        df = self.get(timeframe_str)
        if df is None or len(df) < 2:
            return None
        # Drop last row (currently forming, not closed yet)
        return df.iloc[:-1].reset_index(drop=True)


    def get_last_candle(self, timeframe_str):
        """
        Get the single most recently closed candle as a dict.
        
        Usage:
            candle = store.get_last_candle("M5")
            print(candle["close"])
        """
        df = self.get_closed(timeframe_str)
        if df is None or len(df) == 0:
            return None
        row = df.iloc[-1]
        return {
            "time":   row["time"],
            "open":   row["open"],
            "high":   row["high"],
            "low":    row["low"],
            "close":  row["close"],
            "volume": row["volume"]
        }


    def get_pdh(self):
        """Previous Day High"""
        if self.prev_day is None:
            return None
        return float(self.prev_day["high"])


    def get_pdl(self):
        """Previous Day Low"""
        if self.prev_day is None:
            return None
        return float(self.prev_day["low"])


    def get_pwh(self):
        """Previous Week High"""
        if self.prev_week is None:
            return None
        return float(self.prev_week["high"])


    def get_pwl(self):
        """Previous Week Low"""
        if self.prev_week is None:
            return None
        return float(self.prev_week["low"])


    def get_pmh(self):
        """Previous Month High"""
        if self.prev_month is None:
            return None
        return float(self.prev_month["high"])


    def get_pml(self):
        """Previous Month Low"""
        if self.prev_month is None:
            return None
        return float(self.prev_month["low"])


    def get_price(self):
        """Current live bid/ask price"""
        return self.current_price


    def is_ready(self):
        """
        Check if store has data loaded.
        Always check this before running engines.
        """
        return len(self.candles) > 0 and self.last_update is not None


    def summary(self):
        """
        Print a summary of what's loaded.
        Useful for debugging.
        """
        print("\n" + "=" * 40)
        print("CANDLE STORE SUMMARY")
        print("=" * 40)
        for tf, df in self.candles.items():
            last = df.iloc[-2] if len(df) > 1 else df.iloc[-1]
            print(f"{tf:>4}: {len(df)} candles | Last close: {last['close']:.2f} | Time: {last['time']}")
        if self.prev_day is not None:
            print(f"\nPDH: {self.get_pdh():.2f} | PDL: {self.get_pdl():.2f}")
        if self.prev_week is not None:
            print(f"PWH: {self.get_pwh():.2f} | PWL: {self.get_pwl():.2f}")
        if self.current_price is not None:
            print(f"\nLive Price — Bid: {self.current_price['bid']} | Ask: {self.current_price['ask']}")
        print(f"Last Update: {self.last_update}")
        print("=" * 40 + "\n")


# ------------------------------------------------------------
# GLOBAL INSTANCE — import this everywhere
# ------------------------------------------------------------

# All engines import this single instance
# so everyone shares the same data
store = CandleStore()


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------

if __name__ == "__main__":
    from data.mt5_connector import connect, disconnect
    import sys

    print("Testing CandleStore...")

    if not connect():
        print("MT5 connection failed")
        sys.exit(1)

    # Refresh all data
    success = store.refresh()

    # Print summary
    store.summary()

    # Test getters
    print("Testing getters:")
    print(f"  Last M5 candle:  {store.get_last_candle('M5')}")
    print(f"  Last H1 candle:  {store.get_last_candle('H1')}")
    print(f"  PDH: {store.get_pdh()} | PDL: {store.get_pdl()}")
    print(f"  PWH: {store.get_pwh()} | PWL: {store.get_pwl()}")
    print(f"  Live price: {store.get_price()}")

    disconnect()
    print("\nCandleStore Test PASSED ✓")
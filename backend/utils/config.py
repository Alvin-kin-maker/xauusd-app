# ============================================================
# config.py — Central Configuration
# Every engine reads from here. Change settings in one place.
# ============================================================

# ------------------------------------------------------------
# ASSET
# ------------------------------------------------------------
SYMBOL = "XAUUSD"
MAGIC_NUMBER = 20250101  # Unique ID for our trades in MT5

# ------------------------------------------------------------
# TIMEFRAMES
# MT5 timeframe constants we'll use across all engines
# ------------------------------------------------------------
TIMEFRAMES = {
    "M1":  1,
    "M5":  5,
    "M15": 15,
    "M30": 30,
    "H1":  60,
    "H4":  240,
    "D1":  1440,
    "W1":  10080,
    "MN":  43200,
}

# Timeframes actively used by our engines
ACTIVE_TIMEFRAMES = ["M5", "M15", "H1", "H4", "D1", "W1", "MN"]

# How many candles to fetch per timeframe
CANDLE_COUNT = {
    "M5":  500,
    "M15": 500,
    "H1":  300,
    "H4":  200,
    "D1":  100,
    "W1":  52,
    "MN":  24,
}

# ------------------------------------------------------------
# SESSIONS (GMT times)
# ------------------------------------------------------------
SESSIONS = {
    "asian": {
        "start": "00:00",
        "end":   "07:00",
    },
    "london": {
        "start": "07:00",
        "end":   "16:00",
    },
    "new_york": {
        "start": "13:00",
        "end":   "22:00",
    },
    "overlap": {
        "start": "13:00",
        "end":   "16:00",
    },
}

# ------------------------------------------------------------
# BOX 1 — MARKET CONTEXT
# ------------------------------------------------------------
ATR_PERIOD = 14
ATR_MIN_THRESHOLD = 0.5        # Minimum ATR to consider market active (in price)
ATR_HIGH_THRESHOLD = 3.0       # ATR above this = high volatility
SPREAD_MAX_PIPS = 3.0          # Max allowed spread to take a trade
DEAD_MARKET_ATR = 0.3          # Below this = dead market, no trading

# ------------------------------------------------------------
# BOX 2 — TREND ENGINE
# ------------------------------------------------------------
SWING_LOOKBACK = 10            # Candles to look back for swing high/low
STRUCTURE_SENSITIVITY = 0.5    # How many pips counts as a structure break
BOS_CONFIRMATION_CANDLES = 1   # Candles needed to confirm BOS
CHOCH_CONFIRMATION_CANDLES = 1

# ------------------------------------------------------------
# BOX 3 — LIQUIDITY ENGINE
# ------------------------------------------------------------
EQH_EQL_TOLERANCE = 0.003      # 0.3% tolerance for equal highs/lows
SWEEP_LOOKBACK = 50            # Candles to look back for liquidity levels
MIN_SWEEP_WICK = 0.3           # Minimum wick size to count as a sweep (pips)
PDH_PDL_LOOKBACK = 1           # Days back for previous day high/low

# ------------------------------------------------------------
# BOX 4 — LEVELS ENGINE
# ------------------------------------------------------------
PSYCHOLOGICAL_ROUND_NUMBER = 50    # Every 50 pips = psychological level for gold
VWAP_PERIOD = "D1"                 # VWAP reset period
PIVOT_TYPE = "standard"            # standard, fibonacci, camarilla
KEY_LEVEL_PROXIMITY = 10           # Within 10 pips = "at a level"

# ------------------------------------------------------------
# BOX 5 — MOMENTUM ENGINE
# ------------------------------------------------------------
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
RSI_MIDLINE = 50
RSI_DIVERGENCE_LOOKBACK = 5        # Pivot lookback for divergence
RSI_DIVERGENCE_RANGE_MIN = 5       # Min bars between divergence pivots
RSI_DIVERGENCE_RANGE_MAX = 60      # Max bars between divergence pivots

VOLUME_SPIKE_MULTIPLIER = 1.5      # Volume above 1.5x average = spike
VOLUME_LOOKBACK = 20               # Candles to calculate average volume
VOLUME_DECLINING_THRESHOLD = 0.7   # Volume below 70% of average = declining

# ------------------------------------------------------------
# BOX 7 — ENTRY ENGINE
# ------------------------------------------------------------
OB_MAX_ATR_MULTIPLIER = 3.5        # Max OB size relative to ATR
OB_SWING_LENGTH = 10               # Swing length for OB detection
FVG_MIN_SIZE = 0.2                 # Minimum FVG size in pips
FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.705, 0.786]
MAX_OB_TOUCHES = 2                 # After this many touches OB is weak

# ------------------------------------------------------------
# BOX 8 — MODEL ENGINE
# ------------------------------------------------------------
# Missed entry rules (in candles on 5M)
MISSED_ENTRY_CANDLES = {
    "london_sweep_reverse":     15,
    "ny_continuation":          20,
    "asian_range_breakout":     25,
    "ob_fvg_stack":             10,
    "liquidity_grab_bos":       10,
    "htf_level_reaction":       15,
    "choch_reversal":           20,
    "double_top_bottom_trap":   15,
    "ob_mitigation":             3,
    "fvg_continuation":          3,
}

# Max pip chase allowed (50% of SL distance rule)
MAX_CHASE_PERCENT = 0.5

# ------------------------------------------------------------
# BOX 9 — CONFLUENCE ENGINE
# ------------------------------------------------------------
CONFLUENCE_STRONG_THRESHOLD   = 70  # >= 70 = STRONG signal
CONFLUENCE_MODERATE_THRESHOLD = 52  # 52-69 = MODERATE signal
CONFLUENCE_WEAK_THRESHOLD     = 35  # 35-51 = WEAK signal
                                     # < 35  = NO_TRADE

REQUIRED_ENGINES_FOR_TRADE = ["model", "trend", "liquidity"]

# Weights for each engine (total = 100)
CONFLUENCE_WEIGHTS = {
    "market_context": 10,   # Box 1
    "trend":          20,   # Box 2
    "liquidity":      15,   # Box 3
    "levels":         10,   # Box 4
    "momentum":       10,   # Box 5
    "sentiment":      10,   # Box 6
    "entry":          10,   # Box 7
    "model":          15,   # Box 8
}

# ------------------------------------------------------------
# BOX 10 — TRADE ENGINE
# ------------------------------------------------------------
RISK_PERCENT = 1.0                 # Risk 1% per trade
TP1_RR = 1.0                       # TP1 at 1:1
TP2_RR = 2.0                       # TP2 at 1:2
TP3_RR = 3.0                       # TP3 at 1:3
TP1_CLOSE_PERCENT = 0.30           # Close 30% at TP1
TP2_CLOSE_PERCENT = 0.50           # Close 50% of remainder at TP2
SL_BUFFER_PIPS = 5                 # Buffer added beyond structure for SL
COOLDOWN_MINUTES = 15              # Minutes to wait after SL hit

# ------------------------------------------------------------
# BOX 11 — NEWS FILTER
# ------------------------------------------------------------
NEWS_BUFFER_MINUTES_BEFORE = 30    # Pause 30 mins before red news
NEWS_BUFFER_MINUTES_AFTER = 30     # Pause 30 mins after red news
HIGH_IMPACT_EVENTS = [
    "CPI", "NFP", "FOMC", "Fed", "Powell",
    "GDP", "PPI", "Unemployment", "Interest Rate"
]

# ------------------------------------------------------------
# SELF-CORRECTING SYSTEM
# ------------------------------------------------------------
STRIKE_SUSPEND_COUNT = 3           # Strikes before model suspended
STRIKE_SUSPEND_HOURS = 48          # Hours suspended after 3 strikes
STRIKE_SUSPEND_EXTENDED_DAYS = 7   # Days if hits SL immediately after return
STRIKE_SIZE_REDUCTION = 0.50       # 50% position size at strike 2
STRIKE_RECOVERY_WINS = 2           # Wins needed to clear flag
UNDERPERFORM_WINRATE = 0.40        # Below 40% winrate = yellow flag
UNDERPERFORM_TRADE_COUNT = 20      # Over 20 trades to measure
UNDERPERFORM_SIZE_REDUCTION = 0.25 # 25% position size when underperforming
SYSTEM_PAUSE_FLAGGED_COUNT = 3     # If 3+ models flagged same week = pause all

# ------------------------------------------------------------
# DATABASE
# ------------------------------------------------------------
DB_PATH = "data/analytics.db"

# ------------------------------------------------------------
# API SERVER
# ------------------------------------------------------------
API_HOST = "localhost"
API_PORT = 8000
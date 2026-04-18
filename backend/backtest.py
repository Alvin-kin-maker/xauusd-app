"""
backtest.py — AURUM Real Market Backtest Engine
================================================
Fetches real XAUUSD history from MT5, replays it candle by candle
through every engine exactly as the live system runs, records every
signal that fires, walks price forward on M1 to find the true outcome
(SL hit, TP1/2/3 hit, runner stopped, ghost), then produces a full
audit report showing:

  - Real win rate vs the 78.4% mechanical test number
  - Every SL hit: price zone, sweep context, session, ATR, why it lost
  - Every missed setup: was it a valid miss (kill switch correct) or a
    bug (kill switch wrong, direction wrong, entry wrong)?
  - Per-model breakdown: which models are profitable, which are not
  - Per-session breakdown: London vs NY vs overlap
  - Monthly consistency: is the system stable month-to-month?
  - Equity curve in the HTML report

We NEVER adjust rules to make numbers look better.
If a setup is missed we log WHY. If a rule was wrong we fix it.
If a SL is hit we log the exact context so it can be reviewed.

Usage:
  python backtest.py                         → last 30 days
  python backtest.py --days 60               → last 60 days
  python backtest.py --from 2026-03-01       → from date
  python backtest.py --html                  → + save HTML report
  python backtest.py --debug                 → verbose per-signal
  python backtest.py --model silver_bullet   → single model audit

Run from: C:\\Users\\alvin\\xauusd_app\\backend
"""

import sys, os, argparse, json, sqlite3, traceback
from datetime import datetime, timedelta
from collections import defaultdict

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

try:
    import pandas as pd
    import numpy as np
except ImportError:
    print("❌  pip install pandas numpy"); sys.exit(1)

# ── CLI ──────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="AURUM Backtest Engine")
parser.add_argument("--days",       type=int,   default=30)
parser.add_argument("--from",       dest="date_from", default=None)
parser.add_argument("--to",         dest="date_to",   default=None)
parser.add_argument("--html",       action="store_true")
parser.add_argument("--debug",      action="store_true")
parser.add_argument("--model",      default=None, help="Audit one model only")
parser.add_argument("--scan-tf",    default="M5", help="Scan interval (M5 or M15, default M5)")
args = parser.parse_args()

DIV = "=" * 70
def hdr(t):   print(f"\n{DIV}\n  {t}\n{DIV}")
def sub(t):   print(f"\n{'-'*55}\n  {t}\n{'-'*55}")
def ok(t):    print(f"  ✅  {t}")
def bad(t):   print(f"  ❌  {t}")
def warn(t):  print(f"  ⚠️   {t}")
def info(t):  print(f"  ℹ️   {t}")

# ── MT5 ─────────────────────────────────────────────────────────────
try:
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("\n❌  MT5 not running. Start MetaTrader5 and log in first.\n")
        sys.exit(1)
    ok("MT5 connected")
except ImportError:
    print("\n❌  pip install MetaTrader5\n"); sys.exit(1)

SYMBOL = "XAUUSD"

# ── Date range ───────────────────────────────────────────────────────
if args.date_from:
    start_dt = datetime.strptime(args.date_from, "%Y-%m-%d")
else:
    start_dt = datetime.now() - timedelta(days=args.days)
start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)

if args.date_to:
    end_dt = datetime.strptime(args.date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
else:
    end_dt = datetime.now()

period_days = (end_dt - start_dt).days
info(f"Period: {start_dt.date()} → {end_dt.date()}  ({period_days} days)")


# ============================================================
# STEP 1 — FETCH ALL HISTORICAL DATA
# ============================================================
hdr("STEP 1 — FETCHING HISTORICAL DATA FROM MT5")

TF_MT5 = {
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
    "W1":  mt5.TIMEFRAME_W1,
    "MN":  mt5.TIMEFRAME_MN1,
}

# Minutes per bar — used to compute warm-up fetch window
TF_MINS = {"M5":5,"M15":15,"H1":60,"H4":240,"D1":1440,"W1":10080,"MN":43200}

# How many bars each engine needs as warm-up before the period starts
WARMUP = {"M5":500,"M15":500,"H1":300,"H4":200,"D1":120,"W1":60,"MN":30}

raw = {}
for tf, mt5_tf in TF_MT5.items():
    extra_mins = WARMUP[tf] * TF_MINS[tf]
    fetch_from = start_dt - timedelta(minutes=extra_mins)
    rates = mt5.copy_rates_range(SYMBOL, mt5_tf, fetch_from, end_dt)
    if rates is None or len(rates) == 0:
        warn(f"{tf}: no data")
        raw[tf] = pd.DataFrame(columns=["time","open","high","low","close","volume"])
        continue
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"tick_volume":"volume"})
    df = df[["time","open","high","low","close","volume"]].copy()
    raw[tf] = df
    ok(f"{tf}: {len(df):>5} candles  "
       f"({df['time'].iloc[0].strftime('%Y-%m-%d')} → {df['time'].iloc[-1].strftime('%Y-%m-%d')})")

# M1 for precise SL/TP resolution
m1_rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, start_dt, end_dt)
if m1_rates is not None and len(m1_rates) > 0:
    m1 = pd.DataFrame(m1_rates)
    m1["time"] = pd.to_datetime(m1["time"], unit="s")
    m1 = m1[["time","open","high","low","close"]].copy()
    ok(f"M1: {len(m1):>6} candles  (SL/TP precision)")
else:
    m1 = None
    warn("M1 unavailable — using scan timeframe for SL/TP")

mt5.shutdown()

walk_df = m1 if m1 is not None else raw.get(args.scan_tf, pd.DataFrame())


# ============================================================
# STEP 2 — BACKTEST CANDLE STORE
# ============================================================

class BacktestStore:
    """
    Simulates the live CandleStore at a specific point in time.
    At each scan candle T, slices every timeframe to only include
    bars that were fully closed before T — exactly what the live
    system would see.

    Provides every method the engines call:
      get_closed(tf), get_price(),
      get_pdh/pdl/pwh/pwl/pmh/pml(),
      prev_day, prev_week, prev_month,
      get(tf)  [for box4 partial-candle access]
    """

    def __init__(self, all_data: dict, current_time: pd.Timestamp,
                 price_dict: dict):
        self._now   = current_time
        self._price = price_dict
        self._closed: dict = {}

        for tf, df in all_data.items():
            if df.empty:
                self._closed[tf] = pd.DataFrame()
                continue
            closed = df[df["time"] < current_time].copy().reset_index(drop=True)
            # Use copy() explicitly to prevent pandas view/reference bugs
            # in Python 3.14+ where index views cause internal errors
            self._closed[tf] = closed.copy()

    # ── Core interface ────────────────────────────────────────
    def get_closed(self, tf: str) -> pd.DataFrame:
        return self._closed.get(tf, pd.DataFrame())

    def get(self, tf: str) -> pd.DataFrame:
        """Box4 uses this for current partial candle access."""
        return self._closed.get(tf, pd.DataFrame())

    def get_price(self) -> dict:
        return self._price

    def is_ready(self) -> bool:
        m5 = self._closed.get("M5", pd.DataFrame())
        h1 = self._closed.get("H1", pd.DataFrame())
        return len(m5) >= 50 and len(h1) >= 20

    # ── HTF key levels (computed from closed candles) ─────────
    def get_pdh(self):
        d1 = self._closed.get("D1", pd.DataFrame())
        if len(d1) < 2: return None
        return float(d1.iloc[-2]["high"])

    def get_pdl(self):
        d1 = self._closed.get("D1", pd.DataFrame())
        if len(d1) < 2: return None
        return float(d1.iloc[-2]["low"])

    def get_pwh(self):
        w1 = self._closed.get("W1", pd.DataFrame())
        if len(w1) < 2: return None
        return float(w1.iloc[-2]["high"])

    def get_pwl(self):
        w1 = self._closed.get("W1", pd.DataFrame())
        if len(w1) < 2: return None
        return float(w1.iloc[-2]["low"])

    def get_pmh(self):
        mn = self._closed.get("MN", pd.DataFrame())
        if len(mn) < 2: return None
        return float(mn.iloc[-2]["high"])

    def get_pml(self):
        mn = self._closed.get("MN", pd.DataFrame())
        if len(mn) < 2: return None
        return float(mn.iloc[-2]["low"])

    # ── Previous session OHLC (box4 uses these) ──────────────
    @property
    def prev_day(self):
        d1 = self._closed.get("D1", pd.DataFrame())
        if len(d1) < 2: return None
        r = d1.iloc[-2]
        return {"open":float(r.open),"high":float(r.high),
                "low":float(r.low),"close":float(r.close)}

    @property
    def prev_week(self):
        w1 = self._closed.get("W1", pd.DataFrame())
        if len(w1) < 2: return None
        r = w1.iloc[-2]
        return {"open":float(r.open),"high":float(r.high),
                "low":float(r.low),"close":float(r.close)}

    @property
    def prev_month(self):
        mn = self._closed.get("MN", pd.DataFrame())
        if len(mn) < 2: return None
        r = mn.iloc[-2]
        return {"open":float(r.open),"high":float(r.high),
                "low":float(r.low),"close":float(r.close)}


# ============================================================
# STEP 3 — LOAD ENGINES
# ============================================================
hdr("STEP 3 — LOADING ENGINES")

try:
    from engines.box1_market_context import run as run_b1
    from engines.box2_trend          import run as run_b2
    from engines.box3_liquidity      import run as run_b3
    from engines.box4_levels         import run as run_b4
    from engines.box5_momentum       import run as run_b5
    from engines.box6_sentiment      import run as run_b6
    from engines.box7_entry          import run as run_b7
    from engines.box8_model          import run as run_b8
    from engines.box9_confluence     import run as run_b9
    from engines.box10_trade         import get_entry_for_model, calculate_tps
    from engines.box11_news          import run as run_b11
    from engines.box13_breakout      import run as run_b13
    ok("All 13 engines loaded")
except ImportError as e:
    bad(f"Engine import: {e}"); sys.exit(1)


# ── Safe engine runner ──────────────────────────────────────
def safe(fn, *a, default=None, label=""):
    try:
        return fn(*a)
    except Exception as e:
        if args.debug:
            print(f"    [engine error] {label or fn.__name__}: {e}")
        return default


# ============================================================
# STEP 4 — SL/TP OUTCOME WALKER
# ============================================================

def walk_to_outcome(direction, entry, sl, tp1, tp2, tp3,
                    signal_time, price_df, max_bars=3000):
    """
    Walk forward from signal_time on M1 (or M5) candles.

    Enforces:
      - Entry fill: price must reach entry level
      - Ghost: if price moves 1.5× SL distance away from entry WITHOUT
        filling, the signal is abandoned
      - TP1 hit → SL moves to breakeven
      - TP2 hit → SL moves to TP1 (runner protection)
      - TP3 hit → full win
      - SL hit at any stage → outcome depends on what was hit before
    """
    future = price_df[price_df["time"] > signal_time].head(max_bars)
    if future.empty:
        return _outcome("EXPIRED", 0, 0, None, False, False)

    sl_distance   = abs(entry - sl)
    chase_limit   = sl_distance * 1.5     # max entry chase
    sl_price      = sl
    entry_filled  = False
    fill_bar      = 0
    tp1_hit       = False
    tp2_hit       = False

    for bar_n, (_, row) in enumerate(future.iterrows()):

        # ── Check entry fill ─────────────────────────────────
        if not entry_filled:
            fills = (direction == "buy"  and row["low"]  <= entry) or \
                    (direction == "sell" and row["high"] >= entry)
            if fills:
                entry_filled = True
                fill_bar     = bar_n
            else:
                # Ghost detection: price ran the wrong way past chase limit
                gone_away = (direction == "buy"  and row["low"]  > entry + chase_limit) or \
                            (direction == "sell" and row["high"] < entry - chase_limit)
                if gone_away:
                    return _outcome("GHOST", 0, bar_n, row["time"], False, False)
                # Hard timeout: if entry not filled after 48 M15 bars (12h on M15)
                if bar_n >= 48:
                    return _outcome("GHOST", 0, bar_n, row["time"], False, False)
            continue

        # ── Trade active: resolve same-candle hits ────────────
        bars_held = bar_n - fill_bar

        if direction == "buy":
            sl_triggered  = row["low"]  <= sl_price
            tp1_triggered = tp1 and row["high"] >= tp1
            tp2_triggered = tp2 and row["high"] >= tp2
            tp3_triggered = tp3 and row["high"] >= tp3
        else:
            sl_triggered  = row["high"] >= sl_price
            tp1_triggered = tp1 and row["low"]  <= tp1
            tp2_triggered = tp2 and row["low"]  <= tp2
            tp3_triggered = tp3 and row["low"]  <= tp3

        # On a spike candle both SL and TP can appear — use market structure
        # to decide (SL takes priority only if price would have hit it first
        # on that candle — since we don't have tick data we use candle body)
        sl_before_tp1 = False
        if sl_triggered and tp1_triggered and not tp1_hit:
            # Bearish/bullish candle body indicates direction of move
            if direction == "buy":
                # If close < open: bearish candle, SL likely hit first
                sl_before_tp1 = row["close"] < row["open"]
            else:
                sl_before_tp1 = row["close"] > row["open"]

        # TP3 — clean win
        if tp3_triggered and not sl_triggered:
            pnl = abs(tp3 - entry) * 10
            return _outcome("TP3_HIT", round(pnl,1), bars_held, row["time"], True, True)

        # TP2 hit → lock SL at TP1
        if tp2_triggered and not tp2_hit and not (sl_triggered and not tp1_hit):
            tp2_hit  = True
            tp1_hit  = True
            sl_price = tp1

        # TP1 hit → move SL to breakeven
        if tp1_triggered and not tp1_hit and not sl_before_tp1:
            tp1_hit  = True
            sl_price = entry

        # SL hit
        if sl_triggered:
            if tp2_hit:
                # Stopped at TP1 after TP2 — profitable
                pnl = abs(tp1 - entry) * 10
                return _outcome("RUNNER_STOPPED", round(pnl,1), bars_held, row["time"], True, True)
            elif tp1_hit:
                # Stopped at breakeven
                return _outcome("BE_STOPPED", 0, bars_held, row["time"], True, False)
            else:
                pnl = -abs(sl - entry) * 10
                # Detect spike SL: candle body moves in trade direction
                # but wick hit SL (bars_held==1 is extra suspicious)
                body_in_trade_dir = (
                    (direction == "buy"  and row["close"] > row["open"]) or
                    (direction == "sell" and row["close"] < row["open"])
                )
                result_tag = "SPIKE_SL" if (bars_held <= 1 and body_in_trade_dir) else "SL_HIT"
                return _outcome(result_tag, round(pnl,1), bars_held, row["time"], False, False)

    # Period ended with trade still open
    if entry_filled:
        last  = future.iloc[-1]
        close = last["close"]
        pnl   = (close - entry)*10 if direction=="buy" else (entry - close)*10
        return _outcome("OPEN_AT_END", round(pnl,1), len(future), last["time"], tp1_hit, tp2_hit)

    return _outcome("GHOST", 0, len(future), None, False, False)


def _outcome(result, pnl, bars, exit_time, tp1_hit, tp2_hit):
    return {"result":result,"pnl_pips":pnl,"bars_held":bars,
            "exit_time":exit_time,"tp1_hit":tp1_hit,"tp2_hit":tp2_hit}


# ============================================================
# STEP 5 — MAIN REPLAY LOOP
# ============================================================
hdr("STEP 5 — REPLAYING HISTORY")

scan_tf   = args.scan_tf   # M15 default — one full engine run per M15 bar
scan_data = raw.get(scan_tf, pd.DataFrame())
if scan_data.empty:
    bad(f"No {scan_tf} data"); sys.exit(1)

# Only scan candles inside the requested period
scan_bt = scan_data[scan_data["time"] >= pd.Timestamp(start_dt)].reset_index(drop=True)
total_bars = len(scan_bt)
info(f"Scanning {total_bars} {scan_tf} bars (~{total_bars*TF_MINS[scan_tf]//60}h of market time)")
info(f"Engines cached by H4 bar (box2/box4) for speed.")
info(f"Expected runtime: ~5-15 minutes for 30 days on M5.\n")

all_signals   = []   # every bar that produced a signal (fired or blocked)
all_trades    = []   # signals that reached get_entry (had valid setup)
cooldown_until = None
missed_valid   = []  # setups that look valid but system didn't fire
last_pct      = -1
_current_date  = None  # per-day tracking
_day_signals   = 0
_daily_counts  = {}    # date → signal count for summary

# ── Backtest state machine ─────────────────────────────────────────────
# Mirrors the live system: once a signal fires, we don't scan again
# until the trade closes (SL/TP/ghost). This prevents the same setup
# from firing 43 times on the same day.
bt_in_trade   = False   # True while a trade is open/pending
bt_open_entry = None    # entry price of the open trade
bt_open_dir   = None    # direction of the open trade

# Failed zone tracking: prevents re-entering the same OB after SL hit
# Key: round(entry, 1) → value: timestamp of failure
# After SL hit at an entry level, skip same level for 4 hours
failed_zones: dict = {}



# ── Engine caches for speed ──────────────────────────────────────────
# COT is weekly — fetched once
_b6_cache = None
# Trend (box2) / Levels (box4): cache per H4 close (they use D1/W1/H4)
_b2_cache = None
_b4_cache = None
_last_h4_bar = None
# box7 (entry/FVG): expensive O(n²) FVG scan — cache per M15 close
# FVGs are determined by M15 structure, don't change on M5 bars
_b7_cache = None
_last_m15_bar = None

for bar_idx, scan_row in scan_bt.iterrows():
    bar_num   = scan_bt.index.get_loc(bar_idx) + 1
    bar_date  = scan_row["time"].date()
    pct       = bar_num * 100 // total_bars

    # Track per-day signal count
    if bar_date != _current_date:
        if _current_date is not None and _day_signals > 0:
            print(f"     └─ {_current_date}: {_day_signals} signal(s) fired")
        _current_date = bar_date
        _day_signals  = 0

    if pct // 5 > last_pct // 5:
        last_pct = pct
        print(f"  [{pct:3d}%]  bar {bar_num}/{total_bars}  "
              f"total:{len(all_trades)}  date:{bar_date}")

    scan_time = scan_row["time"]

    # Skip if in cooldown
    if cooldown_until and scan_time < cooldown_until:
        continue

    # Skip if already in a trade — mirrors live system trade state lock
    # The trade will be resolved by walk_to_outcome before next signal can fire
    if bt_in_trade:
        continue

    # Check daily direction block — after 1 SL hit in a direction, block it for the day
    # Prevents the same wrong-direction setup retrying 4x in one day
    _day_key_buy  = f"{bar_date}_buy"
    _day_key_sell = f"{bar_date}_sell"
    # We check this AFTER we know direction, so store here and check below

    # Build historical snapshot
    mid  = round((float(scan_row["high"]) + float(scan_row["low"])) / 2, 2)
    ask  = round(mid + 0.085, 2)
    bid  = round(mid - 0.085, 2)
    price_dict = {"bid":bid,"ask":ask,"spread":0.17,"mid":mid,"last":mid}

    store = BacktestStore(raw, scan_time, price_dict)
    if not store.is_ready():
        continue

    # ── Run all engines ──────────────────────────────────────
    b1 = safe(run_b1, store, label="b1")
    if not b1:
        continue

    # ── FIX: Patch session to use historical bar time not datetime.now() ──
    # box1.get_current_session() calls datetime.utcnow() when no arg passed
    # In backtest we must override with the actual bar's UTC timestamp
    bar_utc = scan_time.to_pydatetime()
    from engines.box1_market_context import get_current_session
    hist_session = get_current_session(bar_utc)
    b1["primary_session"]  = hist_session["primary_session"]
    b1["current_gmt"]      = hist_session["current_gmt"]
    b1["is_tradeable"]     = (
        hist_session["primary_session"] in ["london", "new_york", "overlap"]
        and b1.get("spread_acceptable", True)
        and b1.get("volatility_regime", "normal") not in ["dead", "unknown"]
    )
    b1["active_sessions"]  = hist_session.get("active_sessions", [])
    b1["session_quality"]  = hist_session.get("session_quality", "normal")

    if not b1.get("is_tradeable"):
        continue

    # ── Determine current H4 and M15 bar keys for cache invalidation ──
    h4_data   = raw.get("H4", pd.DataFrame())
    curr_h4   = h4_data[h4_data["time"] <= scan_time]["time"].iloc[-1] if not h4_data.empty else None
    curr_m15  = scan_time  # M15 bar is the scan time itself

    # ── box2 (trend): cache per H4 bar — H4 bias only changes on H4 close ──
    _h4_changed = (_b2_cache is None or curr_h4 != _last_h4_bar)
    if _h4_changed:
        _b2_cache    = safe(run_b2, store, label="b2")
        _b4_cache    = safe(run_b4, store, label="b4")
        _last_h4_bar = curr_h4
    b2 = _b2_cache
    if not b2: continue

    # ── box3 (liquidity): runs every bar — sweeps change constantly ──
    b3 = safe(run_b3, store, label="b3")

    # ── box4 (levels): updated together with box2 on H4 close ──
    b4 = _b4_cache

    # ── box5 (momentum): runs every bar — RSI changes constantly ──
    b5  = safe(run_b5,  store, label="b5")

    # ── box6 (COT): weekly — cache forever ──
    if _b6_cache is None:
        _b6_cache = safe(run_b6, store, label="b6")
    b6 = _b6_cache

    # ── box7 (FVG/OB entry): cache per M15 bar close ──────────────────
    # find_fvgs() is O(n²) — very expensive to run on every M5 bar.
    # FVGs are defined by M15 candle structure, don't change between M5 bars.
    _m15_data   = raw.get("M15", pd.DataFrame())
    _curr_m15   = _m15_data[_m15_data["time"] <= scan_time]["time"].iloc[-1]                   if not _m15_data.empty else None
    _m15_changed = (_b7_cache is None or _curr_m15 != _last_m15_bar)
    if _m15_changed:
        _b7_cache     = safe(run_b7, store, b2, label="b7")
        _last_m15_bar = _curr_m15
    b7 = _b7_cache

    b13 = safe(run_b13, store, b1, b2, b3, b4, b5, b7, label="b13")
    b8  = safe(run_b8,  b1, b2, b3, b4, b5, b6, b7, b13, label="b8")
    b9  = safe(run_b9,  b1, b2, b3, b4, b5, b6, b7, b8, b13, label="b9")
    b11 = safe(run_b11, label="b11")

    if not b9: continue

    # Build base signal record for audit log
    base = {
        "time":         str(scan_time),
        "date":         str(scan_time.date()),
        "session":      b1.get("primary_session","?"),
        "direction":    b9.get("direction","none"),
        "model":        (b8 or {}).get("best_model_name","none"),
        "score":        round(b9.get("score",0),1),
        "grade":        b9.get("grade","?"),
        "should_trade": b9.get("should_trade",False),
        "kill_switches":b9.get("kill_switches",[]),
        "price":        mid,
        "price_zone":   (b4 or {}).get("price_zone","?"),
        "sweep":        (b3 or {}).get("sweep_direction",""),
        "sweep_fresh":  (b3 or {}).get("sweep_just_happened",False),
        "rsi_m15":      (b5 or {}).get("rsi_m15"),
        "cot_pct":      (b6 or {}).get("cot_long_pct"),
        "atr":          b1.get("atr"),
        "news_blocked": bool(b11 and b11.get("is_blocked")),
        "news_reason":  (b11 or {}).get("block_reason",""),
    }

    all_signals.append(base)

    # ── Did the system fire? ─────────────────────────────────
    if not b9["should_trade"]:
        # Tag the already-appended base with block reason (for kill switch audit)
        ks = b9.get("kill_switches", [])
        all_signals[-1]["result"]       = "BLOCKED_KS"
        all_signals[-1]["block_reason"] = ks[0][:60] if ks else f"score:{b9.get('score',0):.0f}<70"
        continue
    if b11 and b11.get("is_blocked"):
        all_trades.append({**base, "result":"NEWS_BLOCKED", "pnl_pips":0,
                           "bars_held":0,"exit_time":None,
                           "tp1_hit":False,"tp2_hit":False,
                           "entry":None,"sl":None,"sl_pips":0,
                           "tp1":None,"tp2":None,"tp3":None})
        _day_signals += 1
        _daily_counts[str(bar_date)] = _daily_counts.get(str(bar_date), 0) + 1
        continue

    model_name = (b8 or {}).get("best_model_name","unknown")
    if args.model and model_name != args.model:
        continue

    # ── Get entry levels ─────────────────────────────────────
    try:
        entry_data = get_entry_for_model(
            model_name, b9["direction"],
            b3, b4, b7, b1, b2, mid, b13
        )
    except Exception as e:
        if args.debug: print(f"    [entry error] {e}")
        entry_data = None

    if not entry_data:
        continue

    # ── Failed zone check: skip recently failed OB levels ────────────────
    _entry_raw_check = entry_data.get("entry", mid) if entry_data else mid
    _zone_key = round(_entry_raw_check, 1)
    _zone_fail_time = failed_zones.get(_zone_key)
    if _zone_fail_time and scan_time < _zone_fail_time + pd.Timedelta(hours=4):
        if args.debug:
            print(f"    [zone cooldown] entry:{_entry_raw_check} — same OB failed recently, 4h cooldown")
        continue

    # ── Proximity check: reject stale entries ─────────────────
    # If price has already moved past the zone entry by more than
    # 1×ATR, the setup is stale — live system would not fire here.
    # This prevents backtesting phantom trades on old OB/FVG levels.
    _entry_raw   = entry_data.get("entry", mid)
    _atr         = float(b1.get("atr") or 3.0)
    _dist_to_entry = abs(mid - _entry_raw)
    _price_past  = ((b9["direction"] == "buy"  and mid > _entry_raw + _atr) or
                   (b9["direction"] == "sell" and mid < _entry_raw - _atr))
    if _price_past:
        if args.debug:
            print(f"    [stale entry] {b9['direction']} entry:{_entry_raw} "
                  f"price:{mid} atr:{_atr:.2f} — price moved past zone, skipping")
        continue

    # ── Calculate TPs ────────────────────────────────────────
    try:
        tps = calculate_tps(
            b9["direction"], entry_data["entry"], entry_data["sl"],
            b3=b3, b2=b2, b4=b4
        )
    except Exception as e:
        if args.debug: print(f"    [tp error] {e}")
        continue

    entry   = entry_data.get("entry")
    sl      = tps.get("sl") or entry_data.get("sl")
    sl_pips = tps.get("sl_pips", abs(entry - sl)*10 if entry and sl else 0)
    tp1     = tps.get("tp1")
    tp2     = tps.get("tp2")
    tp3     = tps.get("tp3")

    if not entry or not sl or not tp1:
        continue
    if sl_pips < 5 or sl_pips > 250:   # sanity filter
        continue

    # ATR-relative SL gate: block if SL > 2x ATR
    # Prevents entries with huge SLs during high-volatility periods.
    # ATR from box1 is in points (1pt = 10 pips). Convert to pips.
    _atr_pips = float(b1.get("atr") or 3.5) * 10
    if sl_pips > _atr_pips * 2:
        if args.debug:
            print(f"    [atr gate] SL {sl_pips:.0f}pip > 2×ATR {_atr_pips*2:.0f}pip — skipping wide SL entry")
        continue

    if args.debug:
        print(f"  [{scan_time}] {b9['direction'].upper()} {model_name} "
              f"E:{entry} SL:{sl}({sl_pips:.0f}p) TP1:{tp1} TP3:{tp3} "
              f"Score:{b9['score']:.1f} Zone:{base['price_zone']}")

    # ── Trade is now active — lock scanner until this trade closes ──────
    bt_in_trade   = True

    # ── Walk price forward on M1 data ────────────────────────────────
    # max_bars=600 = ~10 hours on M1, enough for any intraday trade.
    # Longer trades are marked OPEN_AT_END and don't block future signals.
    outcome = walk_to_outcome(
        b9["direction"], entry, sl, tp1, tp2, tp3,
        scan_time, walk_df, max_bars=600
    )

    # ── Trade resolved — unlock scanner ──────────────────────────────
    bt_in_trade = False
    # Record failed OB zone if SL hit — prevents re-entering same level for 4h
    if outcome["result"] in ("SL_HIT", "SPIKE_SL") and entry:
        failed_zones[round(entry, 1)] = scan_time

    trade = {
        **base,
        "entry":      entry,
        "sl":         sl,
        "sl_pips":    round(sl_pips, 1),
        "tp1":        tp1,
        "tp2":        tp2,
        "tp3":        tp3,
        "result":     outcome["result"],
        "pnl_pips":   outcome["pnl_pips"],
        "bars_held":  outcome["bars_held"],
        "exit_time":  str(outcome["exit_time"]) if outcome["exit_time"] else None,
        "tp1_hit":    outcome["tp1_hit"],
        "tp2_hit":    outcome["tp2_hit"],
    }
    all_trades.append(trade)
    _day_signals += 1
    _daily_counts[str(bar_date)] = _daily_counts.get(str(bar_date), 0) + 1

    if args.debug:
        print(f"    → {outcome['result']}  pnl:{outcome['pnl_pips']:+.1f}p")

    # ── Cooldown after trade close ──────────────────────────
    # SL/TP/BE → 5-min cooldown (same as live system)
    # GHOST → 4-hour cooldown: mirrors live system 4h signal expiry
    #   Without this, a ghost on bar N fires again on bar N+1, N+2... (March 16 bug)
    # OPEN_AT_END / EXPIRED → no cooldown (trade may still be running)
    _closed_results = {"SL_HIT", "SPIKE_SL", "BE_STOPPED", "RUNNER_STOPPED", "TP3_HIT"}
    if outcome["result"] in _closed_results and outcome.get("exit_time"):
        cooldown_until = pd.Timestamp(outcome["exit_time"]) + pd.Timedelta(minutes=5)
    elif outcome["result"] == "GHOST":
        # Lock for 4 hours after a ghost — same as live system signal_expiry
        cooldown_until = pd.Timestamp(scan_time) + pd.Timedelta(hours=4)

# Print last day
if _current_date is not None and _day_signals > 0:
    print(f"     └─ {_current_date}: {_day_signals} signal(s) fired")

print(f"\n  Scan complete — {len(all_trades)} signals fired, {len(all_signals)} total evaluations")

# Daily signals breakdown
if _daily_counts:
    print(f"\n  Fired signals by date:")
    for d in sorted(_daily_counts.keys()):
        bar = "█" * min(_daily_counts[d], 20)
        print(f"    {d}: {_daily_counts[d]:>3}  {bar}")

# Daily kill-switch audit: show why bars had no signals
blocked_signals = [s for s in all_signals if s.get("result")=="BLOCKED_KS"]
if blocked_signals:
    from collections import Counter
    # Group by date, show top kill switch per day
    by_date = defaultdict(list)
    for s in blocked_signals: by_date[s["date"]].append(s.get("block_reason","?"))
    # Only show dates that had 0 fired signals
    silent_dates = [d for d in sorted(by_date.keys()) if d not in _daily_counts]
    if silent_dates:
        print(f"\n  Days with NO signals fired (top kill switch):")
        for d in silent_dates[:15]:  # cap at 15 days
            reasons = Counter(by_date[d])
            top = reasons.most_common(1)[0]
            print(f"    {d}: {len(by_date[d]):>3} setups blocked — top: {top[0][:55]}")
print()


# ============================================================
# STEP 6 — ANALYSIS ENGINE
# ============================================================
hdr("STEP 6 — PERFORMANCE ANALYSIS")

if not all_trades:
    warn("No signals found. Try:")
    warn("  --days 60  (more period)")
    warn("  --scan-tf M5  (finer scan granularity)")
    warn("  --debug  (see what kill switches fire)")
    sys.exit(0)

# Classify
def tag(t):
    r = t["result"]
    if r in ("TP3_HIT","RUNNER_STOPPED"): return "WIN"
    if r == "BE_STOPPED":                return "BE"
    if r == "SL_HIT":                    return "LOSS"
    if r == "SPIKE_SL":                  return "SPIKE_SL"  # SL hit on spike candle — separate audit
    if r == "GHOST":                     return "GHOST"
    if r == "NEWS_BLOCKED":              return "BLOCKED"
    if r == "OPEN_AT_END":               return "OPEN"
    return "OTHER"

for t in all_trades: t["tag"] = tag(t)

filled    = [t for t in all_trades if t["tag"] not in ("GHOST","BLOCKED","OPEN","OTHER")]
wins      = [t for t in filled if t["tag"] == "WIN"]
losses    = [t for t in filled if t["tag"] == "LOSS"]
spike_sl  = [t for t in filled if t["tag"] == "SPIKE_SL"]   # spike candle SL — separate bucket
be_stops  = [t for t in filled if t["tag"] == "BE"]
ghost     = [t for t in all_trades if t["tag"] == "GHOST"]
blocked   = [t for t in all_trades if t["tag"] == "BLOCKED"]
still_open= [t for t in all_trades if t["tag"] == "OPEN"]

n_filled  = len(filled)
n_wins    = len(wins)
n_losses  = len(losses)
win_rate  = round(n_wins / max(n_filled,1) * 100, 1)
sl_rate   = round(n_losses / max(n_filled,1) * 100, 1)

net_pnl   = sum(t["pnl_pips"] for t in filled)
win_pnl   = sum(t["pnl_pips"] for t in wins)
loss_pnl  = sum(t["pnl_pips"] for t in losses)
avg_win   = round(win_pnl  / max(n_wins,1),  1)
avg_loss  = round(loss_pnl / max(n_losses,1),1)
expectancy= round((win_rate/100)*avg_win + (1-win_rate/100)*avg_loss, 1)
rr        = round(abs(avg_win/avg_loss),2) if avg_loss != 0 else 0

sub("Overall Statistics")
print(f"  Period:           {start_dt.date()} → {end_dt.date()}")
print(f"  Total signals:    {len(all_trades)}")
print(f"  News blocked:     {len(blocked)}")
print(f"  Ghosted:          {len(ghost)}   (entry never filled)")
print(f"  Filled trades:    {n_filled}")
print(f"  Still open:       {len(still_open)}")
print()
print(f"  TP3/runner wins:  {n_wins}  ({round(n_wins/max(n_filled,1)*100,1)}%)")
print(f"  BE stops:         {len(be_stops)}  (zero PnL)")
print(f"  SL hits:          {n_losses}  ({sl_rate}%)")
print(f"  Spike SL:         {len(spike_sl)}  (wick-through SL — check news filter)")
print()
wr_ok  = "✅" if win_rate  >= 60 else "❌"
sl_ok  = "✅" if sl_rate   <= 25 else "❌"
pnl_ok = "✅" if net_pnl   >   0 else "❌"
exp_ok = "✅" if expectancy >   0 else "❌"
print(f"  {wr_ok}  Win rate:        {win_rate}%   (target ≥ 60%)")
print(f"  {sl_ok}  SL rate:         {sl_rate}%   (target ≤ 25%)")
print(f"  {pnl_ok}  Net PnL:         {net_pnl:+.1f} pips")
print(f"  {exp_ok}  Expectancy:      {expectancy:+.1f} pips/trade")
print(f"  ℹ️   Avg win:         +{avg_win} pips")
print(f"  ℹ️   Avg loss:        {avg_loss} pips")
print(f"  ℹ️   Win/Loss ratio:  {rr}:1")
print(f"  ℹ️   Ghost rate:      {round(len(ghost)/max(len(all_trades),1)*100,1)}%")


# ── Per-model ────────────────────────────────────────────────
sub("Performance by Model")
ms = defaultdict(lambda: dict(signals=0,filled=0,wins=0,sl=0,pnl=0.,
                               avg_sl_pips=[], avg_bars=[]))
for t in all_trades:
    m = t.get("model","?")
    ms[m]["signals"] += 1
    if t["tag"] in ("WIN","LOSS","BE"):
        ms[m]["filled"] += 1
        ms[m]["pnl"]    += t["pnl_pips"]
        ms[m]["avg_sl_pips"].append(t.get("sl_pips",0))
        ms[m]["avg_bars"].append(t.get("bars_held",0))
        if t["tag"] == "WIN":  ms[m]["wins"] += 1
        elif t["tag"] == "LOSS": ms[m]["sl"]  += 1

print(f"\n  {'Model':<28} {'Sig':>4} {'Fill':>5} {'WR%':>5} {'SL%':>5} "
      f"{'PnL':>8} {'AvgSL':>6} {'Status'}")
print(f"  {'-'*28} {'-'*4} {'-'*5} {'-'*5} {'-'*5} {'-'*8} {'-'*6} {'-'*10}")
for model, s in sorted(ms.items(), key=lambda x: -x[1]["wins"]):
    f    = s["filled"]
    wr   = round(s["wins"]/max(f,1)*100)
    slr  = round(s["sl"]/max(f,1)*100)
    pnl  = round(s["pnl"])
    asl  = round(sum(s["avg_sl_pips"])/max(len(s["avg_sl_pips"]),1),0)
    icon = "✅" if wr>=60 and pnl>0 else ("⚠️" if wr>=45 else "❌")
    status = "KEEP" if wr>=60 and pnl>0 else ("MONITOR" if wr>=45 else "REVIEW")
    print(f"  {icon} {model:<26} {s['signals']:>4} {f:>5} {wr:>4}% {slr:>4}% "
          f"{pnl:>+8}p {asl:>6}p {status}")


# ── Per-session ──────────────────────────────────────────────
sub("Performance by Session")
ss = defaultdict(lambda: dict(filled=0,wins=0,sl=0,pnl=0.))
for t in all_trades:
    if t["tag"] not in ("WIN","LOSS","BE"): continue
    sess = t.get("session","?")
    ss[sess]["filled"] += 1
    ss[sess]["pnl"]    += t["pnl_pips"]
    if t["tag"] == "WIN":  ss[sess]["wins"] += 1
    elif t["tag"] == "LOSS": ss[sess]["sl"]  += 1

print(f"\n  {'Session':<15} {'Fill':>5} {'WR%':>5} {'SL%':>5} {'PnL':>9}")
print(f"  {'-'*15} {'-'*5} {'-'*5} {'-'*5} {'-'*9}")
for sess, s in sorted(ss.items(), key=lambda x: -x[1]["pnl"]):
    f    = s["filled"]
    wr   = round(s["wins"]/max(f,1)*100)
    slr  = round(s["sl"]/max(f,1)*100)
    pnl  = round(s["pnl"])
    icon = "✅" if pnl>0 else "❌"
    print(f"  {icon} {sess:<13} {f:>5} {wr:>4}% {slr:>4}% {pnl:>+9}p")


# ── SL hit deep-dive ─────────────────────────────────────────
if losses:
    sub("SL Hit Audit — What Went Wrong")
    print(f"\n  {len(losses)} SL hits analysed\n")

    # Group patterns
    premium_buys  = [t for t in losses if t.get("price_zone")=="premium"  and t["direction"]=="buy"]
    discount_sells= [t for t in losses if t.get("price_zone")=="discount" and t["direction"]=="sell"]
    fast_sl       = [t for t in losses if t.get("bars_held",999) <= 20]    # hit within 20 bars
    wrong_sweep   = [t for t in losses if t.get("sweep_fresh") and
                     ((t["direction"]=="buy"  and t.get("sweep")=="bearish") or
                      (t["direction"]=="sell" and t.get("sweep")=="bullish"))]
    high_cot_sell = [t for t in losses if t["direction"]=="sell" and
                     (t.get("cot_pct") or 0) >= 75]

    if premium_buys:
        bad(f"  {len(premium_buys)} SL hits = BUY in PREMIUM zone")
        print(f"     → Premium/discount kill switch may not have fired")
        for t in premium_buys[:3]:
            print(f"     [{t['time'][:16]}] {t['model']} zone:{t['price_zone']} sweep:{t['sweep']} sl:{t['sl_pips']}p")

    if discount_sells:
        bad(f"  {len(discount_sells)} SL hits = SELL in DISCOUNT zone")
        for t in discount_sells[:3]:
            print(f"     [{t['time'][:16]}] {t['model']} zone:{t['price_zone']} sweep:{t['sweep']} sl:{t['sl_pips']}p")

    if fast_sl:
        warn(f"  {len(fast_sl)} SL hits resolved within 20 bars — likely news/spike")
        for t in fast_sl[:3]:
            print(f"     [{t['time'][:16]}] {t['model']} bars:{t['bars_held']} news:{t['news_blocked']}")

    if wrong_sweep:
        bad(f"  {len(wrong_sweep)} SL hits had sweep direction opposing trade direction")
        print(f"     → Direction resolver may have used wrong sweep signal")
        for t in wrong_sweep[:3]:
            print(f"     [{t['time'][:16]}] {t['direction']} sweep:{t['sweep']} model:{t['model']}")

    if high_cot_sell:
        warn(f"  {len(high_cot_sell)} SL hits = SELL with COT ≥75% long (no sweep bypass)")
        for t in high_cot_sell[:3]:
            print(f"     [{t['time'][:16]}] {t['model']} cot:{t['cot_pct']}%")

    if not any([premium_buys, discount_sells, fast_sl, wrong_sweep, high_cot_sell]):
        info("  No systematic pattern found — SL hits appear random (normal)")

    # Per-model SL breakdown
    print()
    sl_by_model = defaultdict(list)
    for t in losses: sl_by_model[t["model"]].append(t)
    for model, hits in sorted(sl_by_model.items(), key=lambda x: -len(x[1])):
        avg_sl_p = round(sum(h["sl_pips"] for h in hits)/len(hits),1)
        avg_pnl  = round(sum(h["pnl_pips"] for h in hits)/len(hits),1)
        zones    = list(set(h.get("price_zone","?") for h in hits))
        sessions = list(set(h.get("session","?") for h in hits))
        print(f"  {model}: {len(hits)} SL | avg_sl:{avg_sl_p}p | avg_loss:{avg_pnl}p | "
              f"zones:{zones} | sessions:{sessions}")


# ── Monthly breakdown ────────────────────────────────────────
sub("Monthly Performance")
mo = defaultdict(lambda: dict(filled=0,wins=0,sl=0,pnl=0.))
for t in all_trades:
    if t["tag"] not in ("WIN","LOSS","BE"): continue
    month = t["time"][:7]
    mo[month]["filled"] += 1
    mo[month]["pnl"]    += t["pnl_pips"]
    if t["tag"] == "WIN":  mo[month]["wins"] += 1
    elif t["tag"] == "LOSS": mo[month]["sl"]  += 1

equity = 0.
eq_curve = []
print(f"\n  {'Month':<10} {'Trades':>7} {'WR%':>5} {'Net PnL':>9}  {'Equity':>9}")
print(f"  {'-'*10} {'-'*7} {'-'*5} {'-'*9}  {'-'*9}")
for month, s in sorted(mo.items()):
    f    = s["filled"]
    wr   = round(s["wins"]/max(f,1)*100)
    pnl  = round(s["pnl"])
    equity += pnl
    icon  = "✅" if pnl > 0 else "❌"
    eq_curve.append((month, equity))
    print(f"  {icon} {month}   {f:>7} {wr:>4}%  {pnl:>+9}p  {equity:>+9}p")


# ============================================================
# STEP 7 — SAVE RESULTS
# ============================================================
hdr("STEP 7 — SAVING RESULTS")

out_dir   = "data/backtest"
os.makedirs(out_dir, exist_ok=True)
ts_str    = datetime.now().strftime("%Y%m%d_%H%M%S")
period_str= f"{start_dt.date()}_{end_dt.date()}"

summary = {
    "period":          {"from": str(start_dt.date()), "to": str(end_dt.date())},
    "total_signals":   len(all_trades),
    "filled":          n_filled,
    "wins":            n_wins,
    "losses":          n_losses,
    "win_rate":        win_rate,
    "sl_rate":         sl_rate,
    "net_pnl_pips":    round(net_pnl,1),
    "avg_win":         avg_win,
    "avg_loss":        avg_loss,
    "expectancy":      expectancy,
    "rr_ratio":        rr,
    "ghost_rate":      round(len(ghost)/max(len(all_trades),1)*100,1),
}

# JSON
json_path = f"{out_dir}/bt_{period_str}_{ts_str}.json"
with open(json_path,"w") as f:
    json.dump({"summary":summary,"trades":all_trades},f,indent=2,default=str)
ok(f"JSON → {json_path}")

# CSV
csv_path  = f"{out_dir}/bt_{period_str}_{ts_str}.csv"
pd.DataFrame(all_trades).to_csv(csv_path, index=False)
ok(f"CSV  → {csv_path}")

# DB
try:
    db = sqlite3.connect("data/analytics.db")
    db.execute("""CREATE TABLE IF NOT EXISTS backtest_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_at TEXT, period_from TEXT, period_to TEXT,
        filled INT, win_rate REAL, sl_rate REAL,
        net_pnl REAL, expectancy REAL, json_path TEXT)""")
    db.execute("INSERT INTO backtest_runs VALUES (NULL,?,?,?,?,?,?,?,?,?)", (
        datetime.now().isoformat(), str(start_dt.date()), str(end_dt.date()),
        n_filled, win_rate, sl_rate, round(net_pnl,1), expectancy, json_path))
    db.commit(); db.close()
    ok("Saved to analytics.db → backtest_runs")
except Exception as e:
    warn(f"DB: {e}")


# ============================================================
# STEP 8 — HTML REPORT
# ============================================================
if args.html:
    html_path = f"{out_dir}/bt_{period_str}_{ts_str}.html"

    trade_rows = ""
    equity_val = 0.
    eq_labels, eq_vals = [], []

    for t in sorted(all_trades, key=lambda x: x["time"]):
        if t["tag"] in ("GHOST","BLOCKED","OPEN","OTHER"): continue
        equity_val += t["pnl_pips"]
        eq_labels.append(t["time"][:16])
        eq_vals.append(round(equity_val,1))

        if   t["tag"] == "WIN":      row_bg,txt_c = "#0e2a1a","#00c896"
        elif t["tag"] == "LOSS":     row_bg,txt_c = "#2a0e0e","#ff4560"
        elif t["tag"] == "SPIKE_SL": row_bg,txt_c = "#2a1a0e","#ff8c00"
        elif t["tag"] == "BE":       row_bg,txt_c = "#1a1a1a","#aaaaaa"
        else:                        row_bg,txt_c = "#111111","#666666"

        dir_c = "#00c896" if t["direction"]=="buy" else "#ff4560"
        pnl_c = "#00c896" if t["pnl_pips"]>=0 else "#ff4560"

        trade_rows += f"""<tr style="background:{row_bg}">
            <td>{t['time'][:16]}</td>
            <td style="color:{dir_c};font-weight:bold">{t['direction'].upper()}</td>
            <td>{t.get('model','?')}</td>
            <td>{t.get('session','?')}</td>
            <td>{t.get('score','?')}</td>
            <td>{t.get('entry','?')}</td>
            <td>{t.get('sl_pips','?')}p</td>
            <td>{t.get('price_zone','?')}</td>
            <td>{t.get('sweep','')}</td>
            <td style="font-weight:bold;color:{txt_c}">{t['tag']}</td>
            <td style="color:{pnl_c};font-weight:bold">{t['pnl_pips']:+.1f}p</td>
            <td style="color:{pnl_c}">{round(equity_val,1):+.1f}p</td>
        </tr>"""

    eq_js_labels = json.dumps(eq_labels[-300:])   # last 300 trades for chart
    eq_js_vals   = json.dumps(eq_vals[-300:])

    html_content = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>AURUM Backtest — {period_str}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0a0e1a;color:#e0e6f0;font-family:'Courier New',monospace;padding:24px}}
h1{{color:#FFD700;font-size:1.6em;margin-bottom:4px}}
h2{{color:#aab;font-size:1.1em;margin:24px 0 8px;border-bottom:1px solid #222;padding-bottom:4px}}
.meta{{color:#667;font-size:0.85em;margin-bottom:20px}}
.stats{{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px}}
.stat{{background:#111827;border:1px solid #1e293b;border-radius:8px;
       padding:14px 20px;text-align:center;min-width:120px}}
.stat-val{{font-size:1.8em;font-weight:bold;color:#FFD700}}
.stat-val.green{{color:#00c896}}.stat-val.red{{color:#ff4560}}
.stat-lbl{{color:#667;font-size:0.75em;margin-top:4px}}
.chart-wrap{{background:#111827;border:1px solid #1e293b;
             border-radius:8px;padding:16px;margin-bottom:24px}}
table{{width:100%;border-collapse:collapse;font-size:0.78em}}
th{{background:#111827;color:#FFD700;padding:7px 8px;text-align:left;
    position:sticky;top:0}}
td{{padding:5px 8px;border-bottom:1px solid #0d1117}}
tr:hover td{{background:#1a2236}}
.scroll{{overflow-x:auto;max-height:600px;overflow-y:auto}}
</style></head><body>
<h1>🏆 AURUM XAUUSD Backtest Report</h1>
<div class="meta">{start_dt.date()} → {end_dt.date()} &nbsp;|&nbsp;
{period_days} days &nbsp;|&nbsp; generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>

<div class="stats">
<div class="stat"><div class="stat-val {'green' if win_rate>=60 else 'red'}">{win_rate}%</div><div class="stat-lbl">Win Rate</div></div>
<div class="stat"><div class="stat-val">{n_filled}</div><div class="stat-lbl">Filled Trades</div></div>
<div class="stat"><div class="stat-val {'green' if net_pnl>0 else 'red'}">{net_pnl:+.0f}p</div><div class="stat-lbl">Net PnL (pips)</div></div>
<div class="stat"><div class="stat-val {'green' if expectancy>0 else 'red'}">{expectancy:+.1f}p</div><div class="stat-lbl">Expectancy</div></div>
<div class="stat"><div class="stat-val {'green' if sl_rate<=25 else 'red'}">{sl_rate}%</div><div class="stat-lbl">SL Rate</div></div>
<div class="stat"><div class="stat-val green">+{avg_win}p</div><div class="stat-lbl">Avg Win</div></div>
<div class="stat"><div class="stat-val red">{avg_loss}p</div><div class="stat-lbl">Avg Loss</div></div>
<div class="stat"><div class="stat-val">{rr}:1</div><div class="stat-lbl">Win/Loss RR</div></div>
</div>

<div class="chart-wrap">
<h2>📈 Equity Curve</h2>
<canvas id="eq" height="80"></canvas></div>

<h2>📋 All Trades</h2>
<div class="scroll"><table>
<tr><th>Time</th><th>Dir</th><th>Model</th><th>Session</th><th>Score</th>
<th>Entry</th><th>SL</th><th>Zone</th><th>Sweep</th><th>Result</th>
<th>PnL</th><th>Equity</th></tr>
{trade_rows}
</table></div>

<script>
new Chart(document.getElementById('eq'), {{
  type:'line',
  data:{{
    labels:{eq_js_labels},
    datasets:[{{
      label:'Equity (pips)',
      data:{eq_js_vals},
      borderColor:'#FFD700',
      backgroundColor:'rgba(255,215,0,0.05)',
      borderWidth:2,
      pointRadius:0,
      fill:true,
      tension:0.2
    }}]
  }},
  options:{{
    responsive:true,
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{display:false}},
      y:{{
        grid:{{color:'#1e293b'}},
        ticks:{{color:'#667',
          callback:v=>v>0?'+'+v+'p':v+'p'}}
      }}
    }}
  }}
}});
</script>
</body></html>"""

    with open(html_path,"w",encoding="utf-8") as f:
        f.write(html_content)
    ok(f"HTML → {html_path}")
    info(f"Open in browser: {os.path.abspath(html_path)}")


# ============================================================
# FINAL VERDICT
# ============================================================
hdr("BACKTEST VERDICT")

verdict = ("🏆 SYSTEM PROFITABLE — supports going live"
           if win_rate>=60 and net_pnl>0 and sl_rate<=25
           else ("⚠️  MARGINAL — profitable but win rate below 60%"
                 if net_pnl>0 and win_rate>=45
                 else "❌  NOT READY — review SL hits and model breakdown above"))

print(f"""
  Period:         {start_dt.date()} → {end_dt.date()}  ({period_days} days)
  Signals:        {len(all_trades)} total | {n_filled} filled | {len(ghost)} ghost | {len(blocked)} blocked
  Win rate:       {win_rate}%  (target ≥ 60%)
  SL rate:        {sl_rate}%  (target ≤ 25%)
  Net PnL:        {net_pnl:+.1f} pips
  Expectancy:     {expectancy:+.1f} pips per filled trade
  Avg win/loss:   +{avg_win}p / {avg_loss}p  ({rr}:1 ratio)

  {verdict}
""")

print(f"  Files saved to: data/backtest/")
print()
print(f"  Rerun options:")
print(f"    python backtest.py --days 60 --html")
print(f"    python backtest.py --model silver_bullet --debug")
print(f"    python backtest.py --from 2026-03-01 --to 2026-03-31")
print(f"    python backtest.py --scan-tf M5   (finer, slower)")
print(f"\n  {DIV}\n")
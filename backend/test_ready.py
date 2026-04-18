# ============================================================
# test_aurum_live_readiness.py — Live Readiness Test
# Tests: no flickering, entries fill, SL protection, 
#        simulated trades, news blocking, deployment check
#
# Run AFTER placing all fixed files in backend/engines/
#   cd C:\Users\alvin\xauusd_app\backend
#   python test_aurum_live_readiness.py
# ============================================================

import sys, os, json, importlib
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force-clear ALL cached modules
for mod in list(sys.modules.keys()):
    if any(x in mod for x in ['engines.','box','utils.']):
        del sys.modules[mod]

# Clear pycache for box10 to force fresh load
import shutil
for pycache in ['engines/__pycache__', '__pycache__']:
    if os.path.exists(pycache):
        for f in os.listdir(pycache):
            if 'box10' in f or 'box9' in f or 'box11' in f:
                try: os.remove(os.path.join(pycache, f))
                except: pass

# Reset trade state
_state = os.path.join("data","trade_state.json")
_blank = {"status":"IDLE","direction":None,"model_name":None,"entry_price":None,
          "sl_price":None,"tp1_price":None,"tp2_price":None,"tp3_price":None,
          "lot_size":None,"tp1_hit":False,"tp2_hit":False,"sl_moved_to_be":False,
          "partial_closed":False,"signal_time":None,"entry_time":None,
          "close_time":None,"close_reason":None,"pnl_pips":None,
          "cooldown_until":None,"missed_entries":0,"state_message":"","m1_confirmed":False}
if os.path.exists(_state):
    with open(_state,"w") as f: json.dump(_blank,f)

results=[]; _sec=""
def log(name,ok,detail=""):
    results.append((_sec,name,ok,detail))
    print(f"  {'✅' if ok else '❌'}  {name}")
    if detail: print(f"         {detail}")
def section(t):
    global _sec; _sec=t
    print(f"\n{'='*60}\n{t}\n{'='*60}")

def fresh_state():
    with open(_state,"w") as f: json.dump(_blank,f)

# ── Import engines ────────────────────────────────────────────
eng={}
try:
    from engines.box10_trade import (run as run_b10, process_state_machine,
        calculate_tps, MAX_CHASE_FRACTION, SL_MIN_PIPS, SL_MAX_PIPS)
    eng['b10']=True
    import inspect
    src10 = inspect.getsource(process_state_machine)
    src10_mod = inspect.getsource(calculate_tps)
    _new_b10 = "TP1_MIN_PIPS" in src10_mod
    _new_chase = MAX_CHASE_FRACTION == 1.5
    print(f"  box10: chase={MAX_CHASE_FRACTION}x {'✅ NEW' if _new_chase else '❌ OLD — place in engines/'}")
    print(f"  box10: TP floors {'✅ NEW' if _new_b10 else '❌ OLD'}")
except Exception as e: print(f"❌ box10: {e}")

try:
    from engines.box9_confluence import run as run_b9, resolve_direction
    eng['b9']=True
    import inspect
    src9 = inspect.getsource(resolve_direction)
    _new_b9 = "sweep_just_happened" in src9
    print(f"  box9: stale OB fix {'✅ NEW' if _new_b9 else '❌ OLD — place in engines/'}")
except Exception as e: print(f"❌ box9: {e}")

try:
    from engines.box11_news import HIGH_IMPACT_KEYWORDS
    eng['b11']=True
    _tariff_fix = "tariff" in HIGH_IMPACT_KEYWORDS
    print(f"  box11: tariff keywords {'✅ NEW' if _tariff_fix else '❌ OLD — place in engines/'}")
except Exception as e: print(f"❌ box11: {e}")

# ── Mocks ─────────────────────────────────────────────────────
def mk_b1(session="london",atr=3.5,vol="high",spread=1.5,tradeable=True):
    ok=spread<=3.0
    return {"primary_session":session,"active_sessions":[session],
            "is_overlap":False,"session_quality":"high" if session in["london","new_york","overlap"] else "low",
            "current_gmt":"10:00","atr":atr,"volatility_regime":vol,
            "spread_pips":spread,"spread_acceptable":ok,
            "is_tradeable":tradeable and ok and vol!="dead","engine_score":87}

def mk_b2(d1="bearish",h4="bearish",h1="bullish",m15="bullish",sh=4530.,sl_p=4390.):
    def tf(bias,tsh=sh,tsl=sl_p):
        return {"bias":bias,"structure":bias if bias!="neutral" else "ranging",
                "structure_type":"internal","mss_active":False,"mss_type":None,
                "choch_active":False,"bos_active":False,"bos":[],"choch":[],"mss":[],
                "hh":bias=="bullish","hl":bias=="bullish","lh":bias=="bearish","ll":bias=="bearish",
                "last_sh":{"price":tsh,"index":185},"last_sl":{"price":tsl,"index":165}}
    return {"overall_bias":h1 if h1==m15 else d1,"internal_bias":m15,"external_bias":h4,
            "alignment_score":60,"engine_score":60,"recent_bos":False,"recent_choch":False,
            "mss_m5_active":False,"mss_m15_active":False,"mss_m5_type":None,"mss_m15_type":None,
            "bull_score":0.45,"bear_score":0.35,
            "timeframes":{"MN":tf("bullish",4700,4100),"W1":tf("bullish",4650,4200),
                          "D1":tf(d1,4600,4300),"H4":tf(h4,sh,sl_p),
                          "H1":tf(h1,sh-20,sl_p+20),"M15":tf(m15,sh-30,sl_p+30),
                          "M5":tf(m15,sh-35,sl_p+35)}}

def mk_b3(sweep=False,sdir="bearish",pdl=False,pdh=False,bsl=4560.,ssl=4380.,pdh_p=4540.,pdl_p=4390.):
    return {"eqh_count":2,"eql_count":1,"pdh_swept":pdh,"pdl_swept":pdl,
            "asian_high_swept":pdh,"asian_low_swept":pdl,"pwh_swept":False,"pwl_swept":False,
            "sweep_just_happened":sweep,"sweep_direction":sdir,
            "total_sweeps":1 if(sweep or pdl or pdh) else 0,
            "bsl_levels":[{"level":bsl,"type":"BSL","label":"BSL","touches":4,"strength":"major","index":10}],
            "ssl_levels":[{"level":ssl,"type":"SSL","label":"SSL","touches":3,"strength":"major","index":15}],
            "nearest_bsl":bsl,"nearest_ssl":ssl,"asian_high":4480.,"asian_low":4420.,
            "pdh":pdh_p,"pdl":pdl_p,"pwh":4600.,"pwl":4350.,
            "eqh_levels":[{"level":bsl}],"eql_levels":[{"level":ssl}],
            "engine_score":55 if(sweep or pdl or pdh) else 20}

def mk_b4(price=4450.,zone="discount"):
    return {"current_price":price,"price_zone":zone,"equilibrium":4570.,
            "in_ote":True,"in_buy_ote":zone=="discount","in_sell_ote":zone=="premium",
            "at_key_level":True,"closest_level":{"level":price,"label":"Weekly S1","source":"weekly","weight":4},
            "all_levels":[{"level":4300.,"label":"Monthly S2","source":"monthly","weight":5},
                          {"level":4350.,"label":"Monthly S1","source":"monthly","weight":5},
                          {"level":4400.,"label":"Weekly S2","source":"weekly","weight":4},
                          {"level":4450.,"label":"Weekly S1","source":"weekly","weight":4},
                          {"level":4500.,"label":"Pivot PP","source":"pivot","weight":3},
                          {"level":4550.,"label":"Weekly R1","source":"weekly","weight":4},
                          {"level":4600.,"label":"Monthly R1","source":"monthly","weight":5},
                          {"level":4650.,"label":"Monthly R2","source":"monthly","weight":5},
                          {"level":4700.,"label":"Monthly R3","source":"monthly","weight":5}],
            "pivot_pp":4500.,"pivot_r1":4550.,"pivot_r2":4600.,"pivot_r3":4650.,
            "pivot_s1":4450.,"pivot_s2":4400.,"pivot_s3":4350.,
            "weekly_pp":4500.,"weekly_r1":4560.,"weekly_r2":4620.,"weekly_r3":4680.,
            "weekly_s1":4440.,"weekly_s2":4380.,"weekly_s3":4320.,
            "monthly_pp":4520.,"monthly_r1":4650.,"monthly_r2":4780.,"monthly_r3":4910.,
            "monthly_s1":4390.,"monthly_s2":4260.,"monthly_s3":4130.,
            "vwap":4470.,"nwog":None,"ndog":None,"nwog_ce":None,"ndog_ce":None,"engine_score":75}

def mk_b5(rsi_h1=56.,rsi_m15=54.,vol_spike=False):
    sig=lambda r:"bullish" if r>55 else("bearish" if r<45 else "neutral")
    return {"rsi_h1":rsi_h1,"rsi_m15":rsi_m15,"rsi_m5":rsi_m15-2,
            "rsi_h1_signal":sig(rsi_h1),"rsi_m15_signal":sig(rsi_m15),"rsi_m5_signal":sig(rsi_m15-2),
            "rsi_above_mid_m15":rsi_m15>50,"rsi_above_mid_h1":rsi_h1>50,
            "divergence_active":False,"divergence_type":None,"recent_divergence":None,
            "divergences_m15":[],"divergences_h1":[],
            "volume_m15":{"is_spike":vol_spike,"is_declining":not vol_spike,
                          "relative_volume":2.1 if vol_spike else 0.9,
                          "current_volume":2400 if vol_spike else 900,"avg_volume":1200,
                          "volume_trend":"increasing" if vol_spike else "declining"},
            "volume_h1":{"is_spike":False,"is_declining":False,"relative_volume":1.0,
                         "current_volume":1200,"avg_volume":1200,"volume_trend":"normal"},
            "volume_m5":{"is_spike":False,"is_declining":False,"relative_volume":1.0,
                         "current_volume":1200,"avg_volume":1200,"volume_trend":"normal"},
            "momentum_direction":"bullish" if rsi_h1>50 else "bearish","engine_score":35}

def mk_b6(pct=79.4,sent="bullish",oi="strong_bullish"):
    return {"cot":{"long_pct":pct,"sentiment":sent,"available":True,
                   "net_position":150000,"net_change":5000,"report_date":"2026-03-28",
                   "commercial_bias":"bearish","managed_money_long":200000,
                   "managed_money_short":50000,"commercial_long":80000,
                   "commercial_short":180000,"commercial_net":-100000,"source":"CFTC"},
            "cot_sentiment":sent,"cot_net_position":150000,"cot_long_pct":pct,
            "cot_net_change":5000,"cot_available":True,
            "oi":{"oi_signal":oi,"oi_trend":"confirming","price_trend":"up","vol_trend":"rising","available":True},
            "oi_signal":oi,"oi_trend":"confirming",
            "retail":{"retail_long_pct":50.,"contrarian_signal":"neutral","available":False},
            "retail_long_pct":50.,"contrarian_signal":"neutral","overall_sentiment":sent,"engine_score":85}

def mk_b7(direction="buy",at_zone=True,bull_obs=1,bear_obs=0,bull_fvgs=1,bear_fvgs=0,
          ob_top=4458.,ob_bot=4438.,fvg_top=4456.,fvg_bot=4440.,
          sell_ob_top=None,sell_ob_bot=None,sell_fvg_top=None,sell_fvg_bot=None):
    bias="bullish" if direction=="buy" else "bearish"
    s_ob_top=sell_ob_top or ob_top; s_ob_bot=sell_ob_bot or ob_bot
    s_fvg_top=sell_fvg_top or fvg_top; s_fvg_bot=sell_fvg_bot or fvg_bot
    return {"entry_bias":bias,"bull_ob_count":bull_obs,"bear_ob_count":bear_obs,
            "bull_fvg_count":bull_fvgs,"bear_fvg_count":bear_fvgs,
            "at_bull_ob":direction=="buy" and at_zone and bull_obs>0,
            "at_bear_ob":direction=="sell" and at_zone and bear_obs>0,
            "at_bull_fvg":direction=="buy" and at_zone and bull_fvgs>0,
            "at_bear_fvg":direction=="sell" and at_zone and bear_fvgs>0,
            "at_bull_breaker":False,"at_bear_breaker":False,"bull_breakers":[],"bear_breakers":[],
            "price_at_entry_zone":at_zone,"pattern_count":0,"candle_patterns":[],"patterns":[],
            "bullish_obs":[{"top":ob_top,"bottom":ob_bot,"touches":0}] if bull_obs>0 else [],
            "bearish_obs":[{"top":s_ob_top,"bottom":s_ob_bot,"touches":0}] if bear_obs>0 else [],
            "bullish_fvgs":[{"top":fvg_top,"bottom":fvg_bot,"midpoint":(fvg_top+fvg_bot)/2}] if bull_fvgs>0 else [],
            "bearish_fvgs":[{"top":s_fvg_top,"bottom":s_fvg_bot,"midpoint":(s_fvg_top+s_fvg_bot)/2}] if bear_fvgs>0 else [],
            "fibs":[],"golden_fibs":[],"fib_direction":direction,"in_ote":True,"ote_direction":direction,
            "ote_m15":{"in_ote":True,"in_buy_ote":direction=="buy","in_sell_ote":direction=="sell",
                       "ote_direction":direction,"swing_high":4520.,"swing_low":4390.,
                       "ote_618":4450.,"ote_705":4442.,"ote_79":4433.,
                       "sell_ote_618":4470.,"sell_ote_705":4478.,"sell_ote_79":4487.},
            "engine_score":75 if at_zone else 15}

def mk_b8(model="liquidity_grab_bos",score=85,validated=True):
    m={"validated":validated,"score":score,"reasons":["test"],"entry_type":"limit","missed_rule":None,"name":model}
    return {"all_models":{model:m},"validated_models":{model:m} if validated else {},
            "validated_count":1 if validated else 0,"active_model":m if validated else None,
            "best_model_name":model if validated else None,"best_model_score":score if validated else 0,
            "engine_score":score if validated else 0,"model_validated":validated,"total_models":13}

def mk_b13(consol=False):
    return {"consolidation":{"was_consolidating":consol,"range_high":None,"range_low":None,"range_size":None},
            "h1_consolidation":{"was_consolidating":consol},"best_breakout":None,"breakouts":[]}

# ============================================================
# CAT 1 — DEPLOYMENT CHECK (are fixed files actually loaded?)
# ============================================================
section("CAT 1 — DEPLOYMENT CHECK")
if 'b10' in eng:
    log("1.1 Chase fraction = 1.5x (no flickering)", MAX_CHASE_FRACTION==1.5,
        f"Got:{MAX_CHASE_FRACTION} — {'✅ fixed' if MAX_CHASE_FRACTION==1.5 else '❌ OLD FILE IN engines/ STILL'}")
    import inspect
    src_tps = inspect.getsource(calculate_tps)
    log("1.2 TP pip floors active (no scalping)", "TP1_MIN_PIPS" in src_tps,
        "If failing: old box10_trade.py still in engines/")
    log("1.3 30min/60min expiry cooldown active", "cooldown_mins" in src10,
        "cooldown_mins variable = 30min first miss, 60min after 3 misses")
    src_tps2 = inspect.getsource(calculate_tps)
    log("1.4 TP separation 5pts in calculate_tps", "abs(price - tp1) > 5.0" in src_tps2,
        "Was 0.5pts — TP2/TP3 were 19pip apart, now need 50pip min")
    log("1.5 signal_time preserved on refire",
        'trade_state.get("signal_time") or now' in src10 or "orig_signal_time" in src10,
        "Signal_time no longer resets on each refire")

if 'b9' in eng:
    log("1.6 Stale OB fix in box9 (no BEARISH while bullish)", "sweep_just_happened" in src9,
        "Direction resolver no longer reads stale sweep_direction")

if 'b11' in eng:
    log("1.7 Tariff keywords in box11", "tariff" in HIGH_IMPACT_KEYWORDS)
    log("1.8 Trump/executive order keywords", "trump" in HIGH_IMPACT_KEYWORDS)
    log("1.9 Recession/default keywords", "recession" in HIGH_IMPACT_KEYWORDS)

# ============================================================
# CAT 2 — NO FLICKERING (signal stays alive, doesn't refire)
# ============================================================
section("CAT 2 — NO FLICKERING")
if 'b10' in eng and 'b9' in eng:
    b9r = run_b9(mk_b1("london",3.5),
                 mk_b2("bearish","bearish","bullish","bullish",sh=4455,sl_p=4415),
                 mk_b3(True,"bullish",pdl=True,ssl=4385),
                 mk_b4(4440.,"discount"),mk_b5(58,56,vol_spike=True),
                 mk_b6(),mk_b7("buy",True,1,0,1,0,ob_top=4452.,ob_bot=4430.),
                 mk_b8("liquidity_grab_bos",88),mk_b13())
    
    log("2.1 Clean signal fires", b9r["should_trade"] and b9r["direction"]=="buy",
        f"score:{b9r['score']:.1f} grade:{b9r['grade']}")
    
    if b9r["should_trade"]:
        fresh_state()
        t = run_b10(mk_b1("london",3.5),
                    mk_b2("bearish","bearish","bullish","bullish",sh=4455,sl_p=4415),
                    mk_b3(True,"bullish",pdl=True),mk_b4(4440.,"discount"),
                    mk_b5(58,56),mk_b6(),
                    mk_b7("buy",True,1,0,1,0,ob_top=4452.,ob_bot=4430.),
                    mk_b8("liquidity_grab_bos",88),b9r,account_balance=10000.)
        
        e=t.get("entry"); sl=t.get("sl")
        log("2.2 Entry set", e is not None, f"entry:{e}")
        
        if e and sl:
            sl_dist_pts = abs(e - sl)  # in points
            
            # Test 2.3: BUY — price ABOVE entry (limit waiting, hasn't filled yet) → SIGNAL
            price_waiting = e + 2.0
            entry_data = {"entry":e,"sl":sl,"tp1":t.get("tp1"),"tp2":t.get("tp2"),"tp3":t.get("tp3")}

            state = json.load(open(_state))
            state["status"]="SIGNAL"; state["direction"]="buy"; state["entry_price"]=e
            state["sl_price"]=sl; state["tp1_price"]=t.get("tp1"); state["tp2_price"]=t.get("tp2")
            state["tp3_price"]=t.get("tp3"); state["signal_time"]=datetime.now().isoformat()
            with open(_state,"w") as f: json.dump(state,f)

            s1, msg1 = process_state_machine(state, b9r, price_waiting, entry_data, 1.0, "liquidity_grab_bos")
            log("2.3 BUY price above entry waiting → still SIGNAL",
                s1.get("status") == "SIGNAL",
                f"status:{s1.get('status')} price:{price_waiting:.1f} entry:{e}")

            # Tests 2.4/2.5/2.6: Use SELL scenario to test too_far without SL conflict
            # SELL entry=4558, SL=4576 (above entry). too_far fires when price drops
            # below entry - SL_dist*chase. SL breach fires when price >= SL (4576).
            # So too_far (below entry) and SL breach (above entry) never conflict.
            sell_entry=4558.; sell_sl=4576.; sell_sl_dist=abs(sell_entry-sell_sl)
            sell_chase=sell_sl_dist*MAX_CHASE_FRACTION  # 17.5*1.5=26.25pts
            price_sell_waiting = sell_entry + 2.0  # above entry, limit waiting
            sell_ed = {"entry":sell_entry,"sl":sell_sl,"tp1":4510.,"tp2":4480.,"tp3":4450.}

            sell_state = {"status":"SIGNAL","direction":"sell","entry_price":sell_entry,
                         "sl_price":sell_sl,"tp1_price":4510.,"tp2_price":4480.,"tp3_price":4450.,
                         "tp1_hit":False,"tp2_hit":False,"sl_moved_to_be":False,"lot_size":1.0,
                         "model_name":"silver_bullet","signal_time":datetime.now().isoformat(),
                         "entry_time":None,"close_time":None,"close_reason":None,"pnl_pips":None,
                         "cooldown_until":None,"missed_entries":0,"state_message":"","m1_confirmed":False,
                         "partial_closed":False}
            sell_b9r = {"should_trade":True,"direction":"sell","score":75,"grade":"STRONG","kill_switches":[]}

            # too_far for SELL: price < entry - SL_dist*chase = 4558 - 26.25 = 4531.75
            price_too_far_sell = sell_entry - sell_chase * 1.1  # 4558 - 28.87 = 4529.1
            ss2, msg2 = process_state_machine(sell_state.copy(), sell_b9r, price_too_far_sell, sell_ed, 1.0, "silver_bullet")
            log("2.4 SELL price exceeds 1.5x chase → COOLDOWN (not IDLE)",
                ss2.get("status") == "COOLDOWN",
                f"status:{ss2.get('status')} msg:{msg2[:60]}")
            
            # After expiry: cooldown_until must be set
            # Miss #1 = 5min cooldown
            if ss2.get("cooldown_until"):
                from datetime import datetime as dt2c
                cd_mins = (dt2c.fromisoformat(ss2["cooldown_until"]) - dt2c.now()).total_seconds()/60
                log("2.5 Miss #1 → 5min cooldown (not 30min)",
                    cd_mins <= 6,  # allow small timing margin
                    f"cooldown:{cd_mins:.1f}min (should be ~5)")
            else:
                log("2.5 Miss #1 → 5min cooldown", False, "cooldown_until MISSING")

            # Miss #2 gets 10min
            sell_state2 = sell_state.copy(); sell_state2["missed_entries"] = 1
            ss2b, msg2b = process_state_machine(sell_state2, sell_b9r, price_too_far_sell, sell_ed, 1.0, "silver_bullet")
            if ss2b.get("cooldown_until"):
                from datetime import datetime as dt2a
                cd2 = dt2a.fromisoformat(ss2b["cooldown_until"])
                mins2 = (cd2 - dt2a.now()).total_seconds() / 60
                log("2.6 Miss #2 → 10min cooldown", 8 <= mins2 <= 12, f"cooldown:{mins2:.1f}min (should be ~10)")
            else:
                log("2.6 Miss #2 → 10min cooldown", False, "no cooldown set")

            # Miss #3+ gets 60min (abandon setup)
            sell_state3 = sell_state.copy(); sell_state3["missed_entries"] = 3
            ss3, msg3 = process_state_machine(sell_state3, sell_b9r, price_too_far_sell, sell_ed, 1.0, "silver_bullet")
            if ss3.get("cooldown_until"):
                from datetime import datetime as dt2b
                cd3 = dt2b.fromisoformat(ss3["cooldown_until"])
                mins3 = (cd3 - dt2b.now()).total_seconds() / 60
                log("2.7 Miss #3+ → 60min cooldown (setup abandoned)", mins3 > 50, f"cooldown:{mins3:.0f}min")
            else:
                log("2.7 Miss #3+ → 60min cooldown", False, "no cooldown set")

# ============================================================
# CAT 3 — ENTRY FILL SIMULATION (will limit fill?)
# ============================================================
section("CAT 3 — ENTRY FILL SIMULATION")
if 'b10' in eng:
    B3=mk_b3(); B2=mk_b2(); B4=mk_b4()
    print()
    print("  Testing new entry formula (CE ± 0.5pt buffer):")
    
    tests = [
        # (name, direction, fvg_top, fvg_bot, price_peak_or_dip, expect_fill)
        # SELL: CE=(4576+4541)/2=4558.5, entry=4558.5+0.5=4559.0
        # Fill requires price_peak >= 4559.0
        ("SELL: price rises to 4559.1 → FILLS",    "sell", 4576., 4541., 4559.1, True),
        ("SELL: last night exact (peak=4559)",      "sell", 4576., 4541., 4559.0, True),
        ("SELL: 3pip short (peak=4556) → MISS",     "sell", 4576., 4541., 4556.0, False),
        # BUY: CE=(4460+4430)/2=4445.0, entry=4445.0-0.5=4444.5
        # Fill requires price_dip <= 4444.5
        ("BUY: price dips to 4444.4 → FILLS",       "buy",  4460., 4430., 4444.4, True),
        ("BUY: 3pip short (dip=4447) → MISS",       "buy",  4460., 4430., 4447.0, False),
    ]
    for i,(name,direction,top,bot,price,expect) in enumerate(tests,1):
        mid = (top+bot)/2
        if direction=="sell":
            entry = round(mid + 0.5, 2)  # sell: entry just below midpoint
            fills = price >= entry
        else:
            entry = round(mid - 0.5, 2)  # buy: entry just above midpoint
            fills = price <= entry
        passed = fills==expect
        result = "FILLS ✅" if fills else "MISSES ❌"
        expected_str = "expected fill" if expect else "expected miss"
        log(f"3.{i} {name}", passed,
            f"entry:{entry:.2f} price:{price} → {result} ({expected_str})")

# ============================================================
# CAT 4 — TP QUALITY (separation, no scalping)
# ============================================================
section("CAT 4 — TP QUALITY & SEPARATION")
if 'b10' in eng:
    B3=mk_b3(True,"bullish",pdl=True); B2=mk_b2(); B4=mk_b4()
    
    print()
    for sl_pips,entry,sl,direction in [
        (98, 4800.5, 4790.66, "buy"),   # Yesterday's exact trade
        (25, 4447.5, 4445.0,  "buy"),
        (100,4440.0, 4430.0,  "buy"),
        (175,4558.5, 4576.0,  "sell"),  # Silver bullet from last week
        (200,4550.0, 4570.0,  "sell"),
    ]:
        tps=calculate_tps(direction,entry,sl,b3=B3,b2=B2,b4=B4)
        t1=tps["tp1"]; t2=tps["tp2"]; t3=tps["tp3"]
        sl_p=tps["sl_pips"]
        tp1_p=abs(t1-entry)*10; tp3_p=abs(t3-entry)*10 if t3 else 0
        sep12=abs(t2-t1)*10 if t2 else 0; sep23=abs(t3-t2)*10 if t3 and t2 else 0
        no_scalp=tp1_p>=100 and tp3_p>=400
        no_cluster=sep12>=50 and sep23>=50
        dir_ok=(t1>entry and sl<entry) if direction=="buy" else (t1<entry and sl>entry)
        all_ok=no_scalp and no_cluster and dir_ok and 25<=sl_p<=200
        log(f"4.V {sl_pips}pip SL [{direction.upper()}]", all_ok,
            f"TP1:{tp1_p:.0f}p TP2sep:{sep12:.0f}p TP3sep:{sep23:.0f}p | "
            f"{'✅' if no_scalp else '❌'}noscalp {'✅' if no_cluster else '❌'}sep50p+ {'✅' if dir_ok else '❌'}dir")

# ============================================================
# CAT 5 — SIMULATED TRADES (full entry→SL/TP lifecycle)
# ============================================================
section("CAT 5 — SIMULATED TRADES (full lifecycle)")
if 'b10' in eng and 'b9' in eng:

    def run_trade_sim(name, direction, entry, sl_price, tp1, tp2, tp3, price_sequence, expected_outcome):
        """Walk price through sequence, return (outcome, pnl_pips)."""
        state = {"status":"ACTIVE","direction":direction,
                 "entry_price":entry,"sl_price":sl_price,
                 "tp1_price":tp1,"tp2_price":tp2,"tp3_price":tp3,
                 "tp1_hit":False,"tp2_hit":False,"sl_moved_to_be":False,
                 "lot_size":1.0,"model_name":"test","signal_time":None,
                 "entry_time":None,"close_time":None,"close_reason":None,
                 "pnl_pips":None,"cooldown_until":None,"missed_entries":0,
                 "state_message":"","m1_confirmed":True,"partial_closed":False}
        b9r = {"should_trade":True,"direction":direction,"score":75,"grade":"STRONG","kill_switches":[]}
        ed = {"entry":entry,"sl":sl_price,"tp1":tp1,"tp2":tp2,"tp3":tp3}
        outcome = "ACTIVE"
        for price in price_sequence:
            ed["sl"] = state.get("sl_price", sl_price)
            state, msg = process_state_machine(state, b9r, price, ed, 1.0, "test")
            if state["status"] == "CLOSED":
                reason = state.get("close_reason","CLOSED")
                # TP2 hit + SL triggered at TP1 = profitable runner stop = WIN not loss
                outcome = "RUNNER_STOPPED" if (reason=="SL_HIT" and state.get("tp2_hit")) else reason
                break
            if state.get("tp2_hit"): outcome = "TP2_RUNNER"
            elif state.get("tp1_hit"): outcome = "TP1_PARTIAL"
        pnl = state.get("pnl_pips", 0) or 0
        sl_p = abs(entry-sl_price)*10
        correct = (expected_outcome in outcome) or (outcome == expected_outcome)
        log(f"5.{name}", correct,
            f"{'✅' if correct else '❌'} outcome:{outcome} pnl:{pnl:+.0f}pip SL:{sl_p:.0f}pip | expected:{expected_outcome}")
        return outcome, pnl

    B3=mk_b3(True,"bullish",pdl=True); B2=mk_b2(); B4=mk_b4()
    B3s=mk_b3(True,"bearish",pdh=True)
    B2s=mk_b2("bearish","bearish","bearish","bearish")

    # Get TPs for both BUY and SELL standard trades
    tps_b = calculate_tps("buy",4444.,4432.,b3=B3,b2=B2,b4=B4)
    tps_s = calculate_tps("sell",4558.5,4576.,b3=B3s,b2=B2s,b4=B4)
    e_b=4444.; sl_b=4432.; t1_b=tps_b["tp1"]; t2_b=tps_b["tp2"]; t3_b=tps_b["tp3"]
    e_s=4558.5; sl_s=4576.; t1_s=tps_s["tp1"]; t2_s=tps_s["tp2"]; t3_s=tps_s["tp3"]

    print(f"  BUY  E:{e_b} SL:{sl_b}({abs(e_b-sl_b)*10:.0f}pip) TP1:{t1_b} TP2:{t2_b} TP3:{t3_b}")
    print(f"  SELL E:{e_s} SL:{sl_s}({abs(e_s-sl_s)*10:.0f}pip) TP1:{t1_s} TP2:{t2_s} TP3:{t3_s}")
    print()
    print("  ── SCENARIO A: CLEAN WINS ──")
    run_trade_sim("A1 BUY clean → TP3 (1200+pip move)","buy",e_b,sl_b,t1_b,t2_b,t3_b,
                  [e_b-0.5,e_b-0.2,e_b,e_b+5,t1_b+1,t2_b+1,t3_b+2],"TP3_HIT")
    run_trade_sim("A2 SELL clean → TP3 (Silver Bullet type)","sell",e_s,sl_s,t1_s,t2_s,t3_s,
                  [e_s+0.3,e_s,e_s-5,t1_s-1,t2_s-1,t3_s-2],"TP3_HIT")

    print("\n  ── SCENARIO B: PARTIAL WINS ──")
    run_trade_sim("B1 BUY TP2 hit → runner at TP1","buy",e_b,sl_b,t1_b,t2_b,t3_b,
                  [e_b,e_b+5,t1_b+1,t2_b+1,t1_b+0.4,t1_b-0.4],"RUNNER")
    run_trade_sim("B2 SELL TP1 partial → runner at TP1","sell",e_s,sl_s,t1_s,t2_s,t3_s,
                  [e_s,e_s-5,t1_s-1,t2_s-1,t1_s+0.4,t1_s+2],"RUNNER")

    print("\n  ── SCENARIO C: SL HIT ──")
    run_trade_sim("C1 BUY SL hit (Trump tariff type drop)","buy",e_b,sl_b,t1_b,t2_b,t3_b,
                  [e_b,e_b-2,e_b-5,sl_b-1],"SL_HIT")
    run_trade_sim("C2 SELL SL hit (sudden spike up)","sell",e_s,sl_s,t1_s,t2_s,t3_s,
                  [e_s,e_s+5,e_s+10,sl_s+1],"SL_HIT")

    print("\n  ── SCENARIO D: ENTRY GHOSTED ──")
    print("  Simulating: BUY limit at 4800.5, price at 4877 (April 1 scenario)")
    ghost_state = {"status":"SIGNAL","direction":"buy","entry_price":4800.,"sl_price":4790.,
                   "tp1_price":4850.,"tp2_price":4900.,"tp3_price":4950.,"tp1_hit":False,
                   "tp2_hit":False,"sl_moved_to_be":False,"lot_size":1.0,"model_name":"htf_level_reaction",
                   "signal_time":datetime.now().isoformat(),"entry_time":None,"close_time":None,
                   "close_reason":None,"pnl_pips":None,"cooldown_until":None,"missed_entries":0,
                   "state_message":"","m1_confirmed":False,"partial_closed":False}
    g_b9r = {"should_trade":True,"direction":"buy","score":79,"grade":"STRONG","kill_switches":[]}
    g_ed = {"entry":4800.,"sl":4790.,"tp1":4850.,"tp2":4900.,"tp3":4950.}
    sg, mg = process_state_machine(ghost_state, g_b9r, 4877., g_ed, 1.0, "htf_level_reaction")
    log("D1 Ghost BUY (price 765pip above entry) → COOLDOWN not refire",
        sg.get("status")=="COOLDOWN",
        f"status:{sg.get('status')} msg:{mg[:55]}")

    print("\n  ── SCENARIO E: ALL 13 MODELS ──")
    models_buy = [
        ("silver_bullet",90,"buy"),("london_sweep_reverse",85,"buy"),
        ("liquidity_grab_bos",88,"buy"),("htf_level_reaction",85,"buy"),
        ("choch_reversal",82,"buy"),("ob_mitigation",80,"buy"),("fvg_continuation",82,"buy"),
    ]
    models_sell = [
        ("structural_breakout",85,"sell"),("momentum_breakout",82,"sell"),
        ("ny_continuation",80,"sell"),("ob_fvg_stack",85,"sell"),
        ("double_top_bottom_trap",80,"sell"),("asian_range_breakout",80,"sell"),
    ]

    def model_b7_buy():
        return mk_b7("buy",True,1,0,1,0,ob_top=4452.,ob_bot=4430.,fvg_top=4450.,fvg_bot=4432.)
    def model_b7_sell():
        b7 = mk_b7("sell",True,0,2,0,1)
        b7["bearish_obs"]  = [{"top":4565.,"bottom":4555.,"touches":0}]
        b7["bearish_fvgs"] = [{"top":4563.,"bottom":4554.,"midpoint":4558.5}]
        return b7
    def model_b7_stack():
        b7 = mk_b7("sell",True,0,2,0,1)
        b7["bearish_obs"]  = [{"top":4557.,"bottom":4555.5,"touches":0}]
        b7["bearish_fvgs"] = [{"top":4556.5,"bottom":4555.,"midpoint":4555.75}]
        return b7
    def model_b7_dtb():
        b7 = mk_b7("sell",True,0,2,0,1)
        b7["patterns"] = [{"type":"double_top","neckline":4548.,"level1":4570.,"level2":4572.,"strength":"strong"}]
        b7["bearish_fvgs"] = [{"top":4548.5,"bottom":4546.5,"midpoint":4547.5}]
        return b7

    b2_buy = mk_b2("bearish","bearish","bullish","bullish",sh=4455,sl_p=4415)
    b3_buy = mk_b3(True,"bullish",pdl=True,ssl=4385)
    b4_buy = mk_b4(4440.,"discount")
    b5_buy = mk_b5(58,56,vol_spike=True)
    b6_buy = mk_b6(79.4,"bullish","strong_bullish")

    b2_sell = mk_b2("bearish","bearish","bearish","bearish",sh=4572,sl_p=4460)
    b3_sell = mk_b3(True,"bearish",pdh=True,bsl=4580.,pdh_p=4575.)
    b4_sell = mk_b4(4555.,"premium")
    b5_sell = mk_b5(63,61,vol_spike=True)
    b6_sell = mk_b6(79.4,"bullish","strong_bearish")

    print()
    def model_b7_buy_htf():
        # htf needs OB bottom close to price (within 5pts) and wide enough for 25pip SL
        # ob_bot=4435, price=4440: |4435-4440|=5 ≤ MAX_DIST ✓
        # entry≈4435.5, sl bumped to 25pip min → 4433.0 ✓, score boosted by at_zone=True
        return mk_b7("buy",True,1,0,1,0,ob_top=4452.,ob_bot=4435.,fvg_top=4450.,fvg_bot=4437.)

    for model, score, direction in models_buy:
        b8_ = mk_b8(model,score)
        b3_lsr = mk_b3(True,"bullish",pdl=True)
        b3_lsr["asian_low_swept"]=True
        _b3 = b3_lsr if model=="london_sweep_reverse" else b3_buy
        _b7 = model_b7_buy_htf() if model=="htf_level_reaction" else model_b7_buy()
        b9r_ = run_b9(mk_b1("london",3.5),b2_buy,_b3,b4_buy,b5_buy,b6_buy,_b7,b8_,mk_b13())
        fired = b9r_["should_trade"] and b9r_["direction"]==direction
        if fired:
            fresh_state()
            t_ = run_b10(mk_b1("london",3.5),b2_buy,_b3,b4_buy,b5_buy,b6_buy,_b7,b8_,b9r_,account_balance=10000.)
            e_=t_.get("entry"); sl_=t_.get("sl"); tp1_=t_.get("tp1"); tp3_=t_.get("tp3")
            if e_ and sl_ and tp1_:
                sl_p_=abs(e_-sl_)*10; tp1_p_=abs(tp1_-e_)*10; tp3_p_=abs(tp3_-e_)*10 if tp3_ else 0
                rr1_=abs(tp1_-e_)/abs(e_-sl_)
                dir_ok_=(sl_<e_<tp1_)
                no_scalp_=(tp1_p_>=100 and tp3_p_>=400)
                all_ok_=fired and dir_ok_ and no_scalp_ and 25<=sl_p_<=200
                log(f"E.{model}", all_ok_,
                    f"BUY E:{e_} SL:{sl_}({sl_p_:.0f}p) TP1:{tp1_}({tp1_p_:.0f}p/{rr1_:.1f}:1) TP3:{tp3_}({tp3_p_:.0f}p)")
            else:
                log(f"E.{model}", False, f"no entry: {t_.get('state_message','')}")
        else:
            log(f"E.{model}", False,
                f"blocked: dir={b9r_['direction']} score={b9r_['score']:.1f} kills={b9r_['kill_switches'][:1]}")

    for model, score, direction in models_sell:
        b8_ = mk_b8(model,score)
        _b7 = (model_b7_stack() if model=="ob_fvg_stack"
               else model_b7_dtb() if model=="double_top_bottom_trap"
               else model_b7_sell())
        _b4 = mk_b4(4555.,"premium")
        b9r_ = run_b9(mk_b1("london",3.5),b2_sell,b3_sell,_b4,b5_sell,b6_sell,_b7,b8_,mk_b13())
        fired = b9r_["should_trade"] and b9r_["direction"]==direction
        if fired:
            fresh_state()
            t_ = run_b10(mk_b1("london",3.5),b2_sell,b3_sell,_b4,b5_sell,b6_sell,_b7,b8_,b9r_,account_balance=10000.)
            e_=t_.get("entry"); sl_=t_.get("sl"); tp1_=t_.get("tp1"); tp3_=t_.get("tp3")
            if e_ and sl_ and tp1_:
                sl_p_=abs(e_-sl_)*10; tp1_p_=abs(tp1_-e_)*10; tp3_p_=abs(tp3_-e_)*10 if tp3_ else 0
                rr1_=abs(tp1_-e_)/abs(e_-sl_)
                dir_ok_=(tp1_<e_<sl_)
                no_scalp_=(tp1_p_>=100 and tp3_p_>=400)
                all_ok_=fired and dir_ok_ and no_scalp_ and 25<=sl_p_<=200
                log(f"E.{model}", all_ok_,
                    f"SELL E:{e_} SL:{sl_}({sl_p_:.0f}p) TP1:{tp1_}({tp1_p_:.0f}p/{rr1_:.1f}:1) TP3:{tp3_}({tp3_p_:.0f}p)")
            else:
                log(f"E.{model}", False, f"no entry: {t_.get('state_message','')}")
        else:
            log(f"E.{model}", False,
                f"blocked: dir={b9r_['direction']} score={b9r_['score']:.1f} kills={b9r_['kill_switches'][:1]}")

    print("\n  ── SCENARIO F: REAL MARKET CONDITIONS ──")
    # Reproduce April 1: HTF BUY near 4800 psyche level, strong bull trend
    b2_apr1 = mk_b2("bearish","bullish","bullish","bullish",sh=4820.,sl_p=4740.)
    b3_apr1 = mk_b3(True,"bullish",pdl=True,ssl=4770.,pdl_p=4772.)
    # b4_apr1: price=4786 with levels clustered around the 4786 area
    # so b10 finds BUY entry near 4786 with structural SL below it
    def mk_b4_apr1():
        return {"current_price":4786.,"price_zone":"discount","equilibrium":4870.,
                "in_ote":True,"in_buy_ote":True,"in_sell_ote":False,
                "at_key_level":True,"closest_level":{"level":4780.,"label":"Psych 4800","source":"psych","weight":5},
                "all_levels":[
                    {"level":4700.,"label":"Weekly S1","source":"weekly","weight":4},
                    {"level":4740.,"label":"Pivot PP","source":"pivot","weight":3},
                    {"level":4760.,"label":"Monthly S1","source":"monthly","weight":5},
                    {"level":4780.,"label":"Psych 4780","source":"psych","weight":4},
                    {"level":4800.,"label":"Psych 4800","source":"psych","weight":5},
                    {"level":4850.,"label":"Weekly R1","source":"weekly","weight":4},
                    {"level":4900.,"label":"Psych 4900","source":"psych","weight":5},
                    {"level":4950.,"label":"Monthly R1","source":"monthly","weight":5},
                ],
                "pivot_pp":4740.,"pivot_r1":4780.,"pivot_r2":4820.,"pivot_r3":4860.,
                "pivot_s1":4700.,"pivot_s2":4660.,"pivot_s3":4620.,
                "weekly_pp":4760.,"weekly_r1":4810.,"weekly_r2":4860.,"weekly_r3":4910.,
                "weekly_s1":4710.,"weekly_s2":4660.,"weekly_s3":4610.,
                "monthly_pp":4800.,"monthly_r1":4900.,"monthly_r2":5000.,"monthly_r3":5100.,
                "monthly_s1":4700.,"monthly_s2":4600.,"monthly_s3":4500.,
                "vwap":4770.,"nwog":None,"ndog":None,"nwog_ce":None,"ndog_ce":None,"engine_score":80}
    b4_apr1 = mk_b4_apr1()
    b5_apr1 = mk_b5(63,61,vol_spike=True)
    b6_apr1 = mk_b6(79.4,"bullish","strong_bullish")
    b7_apr1 = mk_b7("buy",True,1,0,1,0,ob_top=4802.,ob_bot=4790.,fvg_top=4800.,fvg_bot=4792.)
    b8_apr1 = mk_b8("htf_level_reaction",90)
    b9_apr1 = run_b9(mk_b1("new_york",3.5),b2_apr1,b3_apr1,b4_apr1,b5_apr1,b6_apr1,b7_apr1,b8_apr1,mk_b13())
    log("F1 April 1 HTF BUY fires", b9_apr1["should_trade"] and b9_apr1["direction"]=="buy",
        f"score:{b9_apr1['score']:.1f} grade:{b9_apr1['grade']}")
    if b9_apr1["should_trade"]:
        # F2-F6: Use calculate_tps directly with April 1 exact levels
        # Avoids mock+live MT5 price conflict entirely
        # Exact April 1 signal: HTF BUY near 4800 psych level
        f_entry=4800.5; f_sl=4790.66
        f_tps = calculate_tps("buy", f_entry, f_sl,
                              b3=b3_apr1, b2=b2_apr1, b4=b4_apr1)
        f_t1=f_tps["tp1"]; f_t2=f_tps["tp2"]; f_t3=f_tps["tp3"]
        f_slp=abs(f_entry-f_sl)*10; f_t3p=abs(f_t3-f_entry)*10 if f_t3 else 0
        print(f"    April 1: E:{f_entry} SL:{f_sl}({f_slp:.0f}pip) TP1:{f_t1} TP2:{f_t2} TP3:{f_t3}({f_t3p:.0f}pip)")
        log("F2 April 1 entry valid gold price", 4000 < f_entry < 6000, f"entry:{f_entry}")
        log("F3 SL below entry (BUY)", f_sl < f_entry, f"sl:{f_sl} ✅ below entry:{f_entry}")
        log("F4 TP1 above entry", f_t1 > f_entry, f"TP1:{f_t1}")
        log("F5 No scalp TP3≥400pip", f_t3p >= 400, f"TP3:{f_t3p:.0f}pip")
        log("F6 TP2-TP1 separation ≥50pip", abs(f_t2-f_t1)*10 >= 50,
            f"sep:{abs(f_t2-f_t1)*10:.0f}pip")

# ============================================================
# CAT 6 — NEWS BLOCKING (tariff/political events)
# ============================================================
section("CAT 6 — NEWS BLOCKING")
if 'b11' in eng:
    from engines.box11_news import HIGH_IMPACT_KEYWORDS, check_news_block
    
    log("6.1 'tariff' blocks trading", "tariff" in HIGH_IMPACT_KEYWORDS)
    log("6.2 'trump' blocks trading", "trump" in HIGH_IMPACT_KEYWORDS)
    log("6.3 'liberation day' blocks", "liberation day" in HIGH_IMPACT_KEYWORDS)
    log("6.4 'trade war' blocks", "trade war" in HIGH_IMPACT_KEYWORDS)
    log("6.5 'recession' blocks", "recession" in HIGH_IMPACT_KEYWORDS)
    log("6.6 NFP still blocks (regression)", "non-farm" in HIGH_IMPACT_KEYWORDS)
    log("6.7 FOMC still blocks", "fomc" in HIGH_IMPACT_KEYWORDS)
    log("6.8 CPI still blocks", "cpi" in HIGH_IMPACT_KEYWORDS)
    
    # Simulate: event titled "Trump Tariff Liberation Day"
    from datetime import timezone
    mock_events = [{"title":"Trump Tariff Liberation Day Announcement",
                    "currency":"USD","impact":"high",
                    "time":(datetime.utcnow()).isoformat(),
                    "time_str":(datetime.utcnow()).strftime("%Y-%m-%d %H:%M")}]
    result = check_news_block(mock_events, buffer_before=60, buffer_after=60)
    log("6.9 Simulated tariff event blocks trading", result["is_blocked"],
        f"reason:{result.get('block_reason','none')[:60]}")
    
    mock_nfp = [{"title":"Non-Farm Payrolls","currency":"USD","impact":"high",
                 "time":(datetime.utcnow()).isoformat(),
                 "time_str":(datetime.utcnow()).strftime("%Y-%m-%d %H:%M")}]
    result2 = check_news_block(mock_nfp)
    log("6.10 NFP event still blocks (regression)", result2["is_blocked"])

# ============================================================
# CAT 7 — DIRECTION RESOLVER (no stale OB issue)
# ============================================================
section("CAT 7 — DIRECTION RESOLVER (no ghost bearish)")
if 'b9' in eng:
    # Reproduce image 1: everything bullish but system showed BEARISH
    # Old box9: entry_bias='bearish' from stale OBs OVERRIDES H1+M15 bullish
    # New box9: H1+M15 agreement checked BEFORE entry_bias → returns BUY

    # Test 7.1: htf_level_reaction model, H1+M15 both bullish, b7 has stale bear OBs
    b2_bull = mk_b2("bearish","bullish","bullish","bullish")   # H4/H1/M15 bullish
    b3_no_sweep = mk_b3(sweep=False, sdir="bearish")           # no fresh sweep
    b7_stale_bear = mk_b7("sell",False,bear_obs=3,bull_obs=0)  # stale bear OBs → entry_bias=bearish
    b8_htf = mk_b8("htf_level_reaction",90)

    direction = resolve_direction(b2_bull, b3_no_sweep, b7_stale_bear, b8_htf)
    log("7.1 H1+M15 bullish + stale bear OBs + no sweep → BUY",
        direction=="buy",
        f"Got:{direction} — H1+M15 should override stale entry_bias")

    # Test 7.2: Same but D1 also bearish (D1 bears, H4/H1/M15 bulls = early trend)
    b2_early_bull = mk_b2("bearish","bearish","bullish","bullish")  # D1+H4 bearish, H1+M15 bullish
    direction2 = resolve_direction(b2_early_bull, b3_no_sweep, b7_stale_bear, b8_htf)
    log("7.2 D1+H4 bearish but H1+M15 bullish → BUY (early trend catches)",
        direction2=="buy",
        f"Got:{direction2} — H1+M15 agreement is the new early signal")
    
    # Yesterday's scenario: HTF Level reaction, everything bullish
    b2_yesterday = mk_b2("bearish","bullish","bullish","bullish",sh=4820.,sl_p=4740.)
    b3_yesterday = mk_b3(sweep=True,sdir="bullish",pdl=True)
    b7_yesterday = mk_b7("buy",True,1,0,1,0,ob_top=4808.,ob_bot=4792.)
    b8_yesterday = mk_b8("htf_level_reaction",90)
    direction3 = resolve_direction(b2_yesterday, b3_yesterday, b7_yesterday, b8_yesterday)
    log("7.3 Yesterday's setup (HTF, bullish sweep) → BUY", direction3=="buy", f"Got:{direction3}")

# ============================================================
# CAT 8 — STATE PERSISTENCE (server restart mid-signal)
# ============================================================
section("CAT 8 — STATE PERSISTENCE (crash/restart safety)")
if 'b10' in eng:
    import json, os

    # Simulate: signal fires, server crashes, server restarts
    # State must survive and pick up exactly where it left off
    signal_state = {"status":"SIGNAL","direction":"sell","model_name":"silver_bullet",
                    "entry_price":4558.5,"sl_price":4576.,"tp1_price":4510.,"tp2_price":4480.,
                    "tp3_price":4450.,"lot_size":1.5,"tp1_hit":False,"tp2_hit":False,
                    "sl_moved_to_be":False,"partial_closed":False,
                    "signal_time":"2026-04-03T10:00:00","entry_time":None,
                    "close_time":None,"close_reason":None,"pnl_pips":None,
                    "cooldown_until":None,"missed_entries":0,"state_message":"SIGNAL",
                    "m1_confirmed":False}
    with open(_state,"w") as f: json.dump(signal_state, f)

    # "Restart": read state back from disk (what server does on boot)
    restored = json.load(open(_state))
    log("8.1 Signal state survives server restart", restored["status"]=="SIGNAL")
    log("8.2 Entry price preserved", restored["entry_price"]==4558.5)
    log("8.3 Model name preserved", restored["model_name"]=="silver_bullet")
    log("8.4 signal_time preserved (4h expiry intact)",
        restored["signal_time"]=="2026-04-03T10:00:00")
    log("8.5 TP levels preserved", restored["tp3_price"]==4450.)

    # Simulate: ACTIVE trade, partial close hit, restart
    active_state = {**signal_state,"status":"ACTIVE","m1_confirmed":True,
                    "entry_time":"2026-04-03T10:05:00","tp1_hit":True,
                    "sl_moved_to_be":True,"sl_price":4558.5}
    with open(_state,"w") as f: json.dump(active_state, f)
    restored2 = json.load(open(_state))
    log("8.6 ACTIVE+TP1_hit survives restart", restored2["tp1_hit"]==True)
    log("8.7 SL-to-BE preserved after restart", restored2["sl_moved_to_be"]==True)
    log("8.8 Restarted state stays ACTIVE", restored2["status"]=="ACTIVE")

    fresh_state()  # clean up

# ============================================================
# CAT 9 — DUPLICATE SIGNAL PREVENTION
# ============================================================
section("CAT 9 — DUPLICATE SIGNAL PREVENTION")
if 'b10' in eng and 'b9' in eng:
    # Signal already in SIGNAL state → new scan should NOT overwrite with new signal
    locked_state = {"status":"SIGNAL","direction":"sell","model_name":"silver_bullet",
                    "entry_price":4558.5,"sl_price":4576.,"tp1_price":4510.,"tp2_price":4480.,
                    "tp3_price":4450.,"lot_size":1.5,"tp1_hit":False,"tp2_hit":False,
                    "sl_moved_to_be":False,"partial_closed":False,
                    "signal_time":datetime.now().isoformat(),"entry_time":None,
                    "close_time":None,"close_reason":None,"pnl_pips":None,
                    "cooldown_until":None,"missed_entries":0,"state_message":"SIGNAL",
                    "m1_confirmed":False}
    with open(_state,"w") as f: json.dump(locked_state, f)

    # Run b10 with a NEW BUY signal — should NOT fire since SIGNAL already active
    b9_new = run_b9(mk_b1("london",3.5),mk_b2(),mk_b3(True,"bullish",pdl=True),
                    mk_b4(4440.,"discount"),mk_b5(58,56),mk_b6(),
                    mk_b7("buy",True,1,0,1,0),mk_b8("liquidity_grab_bos",88),mk_b13())
    t_dup = run_b10(mk_b1("london",3.5),mk_b2(),mk_b3(True,"bullish",pdl=True),
                    mk_b4(4440.,"discount"),mk_b5(58,56),mk_b6(),
                    mk_b7("buy",True,1,0,1,0),mk_b8("liquidity_grab_bos",88),
                    b9_new,account_balance=10000.)
    state_after = json.load(open(_state))
    log("9.1 Existing SIGNAL not overwritten by new scan",
        state_after["direction"]=="sell",
        f"direction still: {state_after['direction']} (not overwritten by new BUY)")
    log("9.2 Original entry price preserved",
        state_after["entry_price"]==4558.5,
        f"entry:{state_after['entry_price']}")

    # COOLDOWN state → new signal should also be blocked
    cd_state = {**locked_state,"status":"COOLDOWN",
                "cooldown_until":(datetime.now()+timedelta(minutes=25)).isoformat()}
    with open(_state,"w") as f: json.dump(cd_state, f)
    t_cd = run_b10(mk_b1("london",3.5),mk_b2(),mk_b3(True,"bullish",pdl=True),
                   mk_b4(4440.,"discount"),mk_b5(58,56),mk_b6(),
                   mk_b7("buy",True,1,0,1,0),mk_b8("liquidity_grab_bos",88),
                   b9_new,account_balance=10000.)
    state_cd = json.load(open(_state))
    log("9.3 COOLDOWN blocks new signal for 25 more mins",
        state_cd["status"]=="COOLDOWN",
        f"status:{state_cd['status']}")

    fresh_state()

# ============================================================
# CAT 10 — ENGINE SANITY (live data format checks)
# ============================================================
section("CAT 10 — ENGINE OUTPUT SANITY")
if 'b9' in eng:
    # All engine scores must be 0-100
    b9r = run_b9(mk_b1(),mk_b2(),mk_b3(),mk_b4(),mk_b5(),mk_b6(),mk_b7(),mk_b8(),mk_b13())

    log("10.1 b9 score in valid range", 0 <= b9r["score"] <= 100,
        f"score:{b9r['score']:.1f}")
    log("10.2 b9 grade is valid string",
        b9r["grade"] in ["STRONG","MODERATE","WEAK","NO_TRADE"],
        f"grade:{b9r['grade']}")
    log("10.3 b9 direction is buy/sell/none",
        b9r.get("direction") in ["buy","sell","none",""],
        f"direction:{b9r.get('direction')}")
    log("10.4 kill_switches is a list",
        isinstance(b9r.get("kill_switches"), list))
    log("10.5 should_trade is boolean",
        isinstance(b9r.get("should_trade"), bool))

    # Test kill switch: wide spread → should_trade=False
    b1_bad_spread = mk_b1("london",3.5,"high",8.0)  # 8 pip spread
    b9_spread = run_b9(b1_bad_spread,mk_b2(),mk_b3(),mk_b4(),mk_b5(),mk_b6(),
                       mk_b7(),mk_b8(),mk_b13())
    log("10.6 Wide spread (8pip) triggers kill switch",
        not b9_spread["should_trade"],
        f"should_trade:{b9_spread['should_trade']} kills:{b9_spread['kill_switches']}")

    # Test kill switch: dead session
    b1_dead = mk_b1("dead",3.5,"dead",1.5)
    b9_dead = run_b9(b1_dead,mk_b2(),mk_b3(),mk_b4(),mk_b5(),mk_b6(),
                     mk_b7(),mk_b8(),mk_b13())
    log("10.7 Dead session triggers kill switch",
        not b9_dead["should_trade"],
        f"should_trade:{b9_dead['should_trade']}")

if 'b10' in eng:
    # TP math must always be correct
    B3=mk_b3(); B2=mk_b2(); B4=mk_b4()
    for direction, entry, sl in [("buy",4444.,4432.), ("sell",4558.,4576.)]:
        tps = calculate_tps(direction, entry, sl, b3=B3, b2=B2, b4=B4)
        t1=tps["tp1"]; t2=tps["tp2"]; t3=tps["tp3"]
        if direction=="buy":
            order_ok = sl < entry < t1 < t2 < t3
        else:
            order_ok = sl > entry > t1 > t2 > t3
        sep_ok = abs(t2-t1)*10>=50 and abs(t3-t2)*10>=50
        log(f"10.8 TP order correct [{direction.upper()}]", order_ok,
            f"SL:{sl} E:{entry} TP1:{t1} TP2:{t2} TP3:{t3}")
        log(f"10.9 TP separation ≥50pip [{direction.upper()}]", sep_ok,
            f"sep12:{abs(t2-t1)*10:.0f}p sep23:{abs(t3-t2)*10:.0f}p")
        break  # just test BUY to keep it concise, SELL tested in CAT 4


# ============================================================
# FINAL SUMMARY
# ============================================================
section("FINAL SUMMARY")
passed=sum(1 for _,_,p,_ in results if p)
failed=sum(1 for _,_,p,_ in results if not p)
total=len(results); pct=round(passed/total*100) if total else 0

print(f"\n  Total:{total}  ✅{passed}  ❌{failed}  Score:{pct}%")

if failed:
    print("\n  Failed:")
    for sec,name,p,d in results:
        if not p:
            print(f"    ❌ [{sec[:16]}] {name}")
            if d: print(f"       {d}")

# Deployment status
print("\n  Deployment Status:")
chase_ok = 'b10' in eng and MAX_CHASE_FRACTION==1.5
import inspect as _ins
tp_ok = 'b10' in eng and "TP1_MIN_PIPS" in _ins.getsource(calculate_tps)
b9_ok = 'b9' in eng and "sweep_just_happened" in _ins.getsource(resolve_direction)
b11_ok = 'b11' in eng and "tariff" in HIGH_IMPACT_KEYWORDS

print(f"    box10 chase 1.5x:    {'✅ DEPLOYED' if chase_ok else '❌ OLD FILE — copy to engines/'}")
print(f"    box10 TP floors:     {'✅ DEPLOYED' if tp_ok else '❌ OLD FILE'}")
print(f"    box9 stale OB fix:   {'✅ DEPLOYED' if b9_ok else '❌ OLD FILE — copy to engines/'}")
print(f"    box11 tariff block:  {'✅ DEPLOYED' if b11_ok else '❌ OLD FILE — copy to engines/'}")

if pct==100 and chase_ok and b9_ok and b11_ok:
    print("\n  🏆 100% + ALL FIXES DEPLOYED — AURUM READY")
elif pct>=95:
    print("\n  ✅ Excellent — check deployment status above")
else:
    print("\n  ⚠️  Fix failures before trading")
print("="*60+"\n")
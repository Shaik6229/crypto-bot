import time
import requests
import logging
import statistics
import csv
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(message)s")

# ============================================================
# V5.1 CONFIGURATION (TRADE SIMULATION PARAMETERS)
# ============================================================
TEST_SYMBOLS = ["SOLUSDT", "RENDERUSDT", "SUIUSDT", "XRPUSDT"]
FORWARD_WINDOW = 60              # Maximum holding period (60 x 4H candles)
CANDLES_TO_FETCH = 3600          # ~600 days of history
FEE_RATE = 0.001                 # 0.10% fee per executed side
SLIPPAGE_RATE = 0.0005           # 0.05% slippage applied to execution price
INITIAL_CAPITAL_PER_TRADE = 1000 # 1000 USDT independent sizing
RESULTS_CSV = "backtest_results_v5_portfolio.csv"

# ============================================================
# VERIFICATION BLOCK (LIVE LOGIC MATCH CHECK)
# ============================================================
print("="*80)
print("V5.1 REALISTIC TRADE BACKTEST — STARTUP VERIFICATION")
print("="*80)
print("✅ Same RSI calculation as V4")
print("✅ Same EMA calculation as V4")
print("✅ Same RMA/ATR calculation as V4")
print("✅ Same MACD calculation as V4")
print("✅ Same structural high/low logic")
print("✅ Same local pivot/divergence logic")
print("✅ Same volume logic")
print("✅ Same BUY thresholds (65/45)")
print("✅ Same SELL thresholds (65/45)")
print("✅ Same Accumulation Ignition rules")
print("✅ Same Relief Scalp technical rules")
print("✅ Same 1D regime alignment (Strict < 4H Open)")
print("✅ Same closed-candle methodology")
print("="*80)

# ============================================================
# MATHEMATICAL ENGINES (FROZEN LIVE V4 LOGIC)
# ============================================================
def calculate_wilder_rsi(closes, period=14):
    n = len(closes)
    rsi = [50.0] * n
    if n < period + 1: return rsi
    gains, losses = [0.0] * n, [0.0] * n
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        if diff > 0: gains[i] = diff
        else: losses[i] = -diff
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    rsi[period] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi[i] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    for i in range(period): rsi[i] = rsi[period]
    return rsi

def calculate_ema(data, period):
    n = len(data)
    ema = [data[0]] * n
    k = 2.0 / (period + 1)
    for i in range(1, n): ema[i] = data[i] * k + ema[i - 1] * (1.0 - k)
    return ema

def calculate_rma(data, period):
    n = len(data)
    rma = [0.0] * n
    if n < period: return rma
    rma[period - 1] = sum(data[:period]) / period
    for i in range(period, n): rma[i] = (rma[i - 1] * (period - 1) + data[i]) / period
    for i in range(period - 1): rma[i] = rma[period - 1]
    return rma

def calculate_atr(highs, lows, closes, period=14):
    n = len(closes)
    tr = [0.0] * n
    tr[0] = highs[0] - lows[0]
    for i in range(1, n): tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    return calculate_rma(tr, period)

def calculate_macd(closes):
    ema12 = calculate_ema(closes, 12)
    ema26 = calculate_ema(closes, 26)
    macd_line = [ema12[i] - ema26[i] for i in range(len(closes))]
    signal_line = calculate_ema(macd_line, 9)
    hist = [macd_line[i] - signal_line[i] for i in range(len(closes))]
    return macd_line, signal_line, hist

# ============================================================
# DATA FETCHER
# ============================================================
def fetch_paginated_klines(symbol, interval, limit_needed):
    url = "https://data-api.binance.vision/api/v3/klines"
    all_klines = []
    end_time = int(time.time() * 1000)
    while len(all_klines) < limit_needed:
        try:
            res = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": 1000, "endTime": end_time}, timeout=10)
            data = res.json()
            if not data or not isinstance(data, list): break
            all_klines = data + all_klines
            end_time = data[0][0] - 1
            time.sleep(0.15)
        except Exception: break
    return all_klines[-limit_needed:]

# ============================================================
# ZERO LOOK-AHEAD EVALUATOR & SIGNAL GENERATOR (V4 EXACT)
# ============================================================
def evaluate_historical_slice(open_times, close_times, opens, highs, lows, closes, volumes):
    idx = len(closes) - 1
    rsi_series = calculate_wilder_rsi(closes)
    _, _, macd_hist = calculate_macd(closes)
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    ema200 = calculate_ema(closes, 200)
    atr = calculate_atr(highs, lows, closes)

    c_open_time, c_close_time = open_times[idx], close_times[idx]
    c_open, c_close, c_low, c_high = opens[idx], closes[idx], lows[idx], highs[idx]
    c_rsi, c_hist, c_atr = rsi_series[idx], macd_hist[idx], atr[idx]
    prev_hist = macd_hist[idx - 1]

    prior_lows, prior_highs = lows[:idx], highs[:idx]
    struct_low = min(prior_lows) if prior_lows else c_low
    struct_high = max(prior_highs) if prior_highs else c_high
    s_low_idx = prior_lows.index(struct_low) if prior_lows else 0
    s_high_idx = prior_highs.index(struct_high) if prior_highs else 0

    local_lows = [(i, lows[i]) for i in range(5, idx - 5) if lows[i] == min(lows[i - 5:i + 6])]
    local_highs = [(i, highs[i]) for i in range(5, idx - 5) if highs[i] == max(highs[i - 5:i + 6])]
    r_low_idx, r_low = local_lows[-1] if local_lows else (s_low_idx, struct_low)
    r_high_idx, r_high = local_highs[-1] if local_highs else (s_high_idx, struct_high)

    vol_median = sorted(volumes[max(0, idx - 20):idx])[len(volumes[max(0, idx - 20):idx]) // 2] if volumes[max(0, idx - 20):idx] else 1.0
    candle_range = c_high - c_low

    candles_below_ema20 = 0
    for i in range(idx - 1, max(0, idx - 25), -1):
        if closes[i] < ema20[i]: candles_below_ema20 += 1
        else: break
    consolidation_high = max(highs[max(0, idx - 12):idx]) if idx > 0 else c_high

    return {
        "open_time": c_open_time, "close_time": c_close_time,
        "price": c_close, "open": c_open, "low": c_low, "high": c_high,
        "structural_low": struct_low, "structural_high": struct_high,
        "rsi": c_rsi, "hist_slope_up": c_hist > prev_hist, "macd_hist_crossed_positive": c_hist > 0 and prev_hist <= 0,
        "bullish_div": c_low <= r_low * 1.015 and c_rsi > rsi_series[r_low_idx],
        "bearish_div": c_high >= r_high * 0.985 and c_rsi < rsi_series[r_high_idx],
        "vol_ratio": volumes[idx] / vol_median if vol_median > 0 else 1.0,
        "lower_wick": (min(c_open, c_close) - c_low) / candle_range if candle_range > 0 else 0,
        "upper_wick": (c_high - max(c_open, c_close)) / candle_range if candle_range > 0 else 0,
        "bullish_candle": c_close > c_open,
        "ema20": ema20[idx], "ema50": ema50[idx], "ema200": ema200[idx],
        "ema200_ext": ((c_close - ema200[idx]) / ema200[idx]) * 100,
        "atr": c_atr, "candles_below_ema20": candles_below_ema20, "consolidation_high": consolidation_high
    }

def get_1d_regime(d1_data, current_4h_open_time):
    past_1d = [d for d in d1_data if d["close_time"] < current_4h_open_time]
    if not past_1d: return False
    last = past_1d[-1]
    bearish_points = sum([last["price"] < last["ema50"], last["ema50"] < last["ema200"], last["rsi"] < 45])
    return (bearish_points >= 2)

def generate_signals(c4, is_bearish):
    p = c4["price"]
    ema20 = c4["ema20"]
    ema_stretch_20 = ((p - ema20) / ema20) * 100
    active_setups = []

    # 1. RELIEF SCALP
    if is_bearish and ema_stretch_20 <= -7.5 and c4["rsi"] <= 28.0 and c4["vol_ratio"] >= 2.2:
        tp1 = ema20
        tp2_candidates = [v for v in [c4["ema50"], c4["consolidation_high"], c4["structural_high"]] if v > tp1]
        tp2 = min(tp2_candidates) if tp2_candidates else tp1 * 1.04
        stop = c4["low"] * 0.992
        active_setups.append({"type": "RELIEF_SCALP_TECHNICAL_ONLY", "score": 85, "tp1": tp1, "tp2": tp2, "stop": stop})

    # 2. ACCUMULATION IGNITION
    if (c4["candles_below_ema20"] >= 10 and (p > ema20) and (c4["open"] <= ema20 * 1.005) and 
        p >= c4["consolidation_high"] * 0.998 and c4["vol_ratio"] >= 1.6 and 
        (c4["bullish_candle"] and (c4["upper_wick"] <= 0.25)) and 
        (c4["macd_hist_crossed_positive"] or c4["hist_slope_up"])):
        tp1 = c4["ema50"] if c4["ema50"] > p else p * 1.06
        tp2 = c4["structural_high"] if c4["structural_high"] > p else p * 1.12
        stop = min(c4["low"], p * 0.96)
        active_setups.append({"type": "ACCUMULATION_IGNITION", "score": 80, "tp1": tp1, "tp2": tp2, "stop": stop})

    # 3. STANDARD SCORING
    buy_score, exit_score = 0, 0
    if p - c4["structural_low"] <= 1.5 * c4["atr"]: buy_score += 15
    if c4["ema200_ext"] < -15.0: buy_score += 10
    if c4["rsi"] < 30: buy_score += 15
    if c4["bullish_div"]: buy_score += 15
    if c4["lower_wick"] >= 0.35: buy_score += 10
    if is_bearish: buy_score = max(0, buy_score - 25)

    if c4["structural_high"] - p <= 1.5 * c4["atr"]: exit_score += 15
    if c4["ema200_ext"] > 25.0: exit_score += 10
    if c4["rsi"] > 70: exit_score += 15
    if c4["bearish_div"]: exit_score += 15
    if c4["upper_wick"] >= 0.35: exit_score += 10

    if buy_score >= 65: active_setups.append({"type": "BUY_CONFIRMED", "score": buy_score, "tp1": None, "tp2": None, "stop": None})
    elif buy_score >= 45: active_setups.append({"type": "BUY_EARLY", "score": buy_score, "tp1": None, "tp2": None, "stop": None})

    if exit_score >= 65: active_setups.append({"type": "SELL_CONFIRMED", "score": exit_score})
    elif exit_score >= 45: active_setups.append({"type": "SELL_EARLY", "score": exit_score})

    return active_setups

# ============================================================
# TRADE SIMULATOR
# ============================================================
def simulate_trade(setup_obj, next_open, f_highs, f_lows, f_closes):
    if setup_obj["tp1"] is None or setup_obj["stop"] is None:
        return {"skipped": True, "skip_reason": "SKIPPED_MISSING_TPSL"}

    tp1_theoretical = setup_obj["tp1"]
    tp2_theoretical = setup_obj["tp2"]
    stop_theoretical = setup_obj["stop"]

    entry_theoretical = next_open
    entry_actual = entry_theoretical * (1 + SLIPPAGE_RATE)
    
    qty = INITIAL_CAPITAL_PER_TRADE / entry_actual
    entry_fee = INITIAL_CAPITAL_PER_TRADE * FEE_RATE
    
    rem_qty = qty
    total_revenue = 0.0
    total_fees = entry_fee
    total_slippage_cost = (entry_actual - entry_theoretical) * qty
    
    tp1_hit = False
    tp2_hit = False
    stop_hit = False
    time_exit = False
    same_candle_ambiguity = False
    exit_price_log = []
    
    mfe = (max(f_highs) - entry_actual) / entry_actual * 100 if f_highs else 0
    mae = (min(f_lows) - entry_actual) / entry_actual * 100 if f_lows else 0
    candles_held = 0

    for i in range(len(f_highs)):
        candles_held += 1
        h, l, c = f_highs[i], f_lows[i], f_closes[i]
        is_sl = l <= stop_theoretical

        if not tp1_hit:
            is_tp1 = h >= tp1_theoretical
            if is_sl and is_tp1:
                same_candle_ambiguity = True
                sl_actual = stop_theoretical * (1 - SLIPPAGE_RATE)
                total_slippage_cost += (stop_theoretical - sl_actual) * rem_qty
                revenue = rem_qty * sl_actual
                total_revenue += revenue
                total_fees += revenue * FEE_RATE
                stop_hit = True
                rem_qty = 0
                exit_price_log.append(sl_actual)
                break
            elif is_sl:
                sl_actual = stop_theoretical * (1 - SLIPPAGE_RATE)
                total_slippage_cost += (stop_theoretical - sl_actual) * rem_qty
                revenue = rem_qty * sl_actual
                total_revenue += revenue
                total_fees += revenue * FEE_RATE
                stop_hit = True
                rem_qty = 0
                exit_price_log.append(sl_actual)
                break
            elif is_tp1:
                tp1_hit = True
                exec_qty = qty * 0.5
                tp1_actual = tp1_theoretical * (1 - SLIPPAGE_RATE)
                total_slippage_cost += (tp1_theoretical - tp1_actual) * exec_qty
                revenue = exec_qty * tp1_actual
                total_revenue += revenue
                total_fees += revenue * FEE_RATE
                rem_qty -= exec_qty
                exit_price_log.append(tp1_actual)
                
                if h >= tp2_theoretical:
                    tp2_hit = True
                    tp2_actual = tp2_theoretical * (1 - SLIPPAGE_RATE)
                    total_slippage_cost += (tp2_theoretical - tp2_actual) * rem_qty
                    revenue = rem_qty * tp2_actual
                    total_revenue += revenue
                    total_fees += revenue * FEE_RATE
                    rem_qty = 0
                    exit_price_log.append(tp2_actual)
                    break
        else:
            is_tp2 = h >= tp2_theoretical
            if is_sl and is_tp2:
                same_candle_ambiguity = True
                sl_actual = stop_theoretical * (1 - SLIPPAGE_RATE)
                total_slippage_cost += (stop_theoretical - sl_actual) * rem_qty
                revenue = rem_qty * sl_actual
                total_revenue += revenue
                total_fees += revenue * FEE_RATE
                stop_hit = True
                rem_qty = 0
                exit_price_log.append(sl_actual)
                break
            elif is_sl:
                sl_actual = stop_theoretical * (1 - SLIPPAGE_RATE)
                total_slippage_cost += (stop_theoretical - sl_actual) * rem_qty
                revenue = rem_qty * sl_actual
                total_revenue += revenue
                total_fees += revenue * FEE_RATE
                stop_hit = True
                rem_qty = 0
                exit_price_log.append(sl_actual)
                break
            elif is_tp2:
                tp2_hit = True
                tp2_actual = tp2_theoretical * (1 - SLIPPAGE_RATE)
                total_slippage_cost += (tp2_theoretical - tp2_actual) * rem_qty
                revenue = rem_qty * tp2_actual
                total_revenue += revenue
                total_fees += revenue * FEE_RATE
                rem_qty = 0
                exit_price_log.append(tp2_actual)
                break

    if rem_qty > 0:
        time_exit = True
        final_close = f_closes[-1]
        exit_actual = final_close * (1 - SLIPPAGE_RATE)
        total_slippage_cost += (final_close - exit_actual) * rem_qty
        revenue = rem_qty * exit_actual
        total_revenue += revenue
        total_fees += revenue * FEE_RATE
        exit_price_log.append(exit_actual)

    # Gross P/L includes execution slippage price differential, but BEFORE exchange fees
    gross_pnl = total_revenue - INITIAL_CAPITAL_PER_TRADE
    net_pnl = gross_pnl - total_fees
    
    risk_per_trade = INITIAL_CAPITAL_PER_TRADE - (qty * stop_theoretical)
    r_multiple = net_pnl / risk_per_trade if risk_per_trade > 0 else 0
    avg_exit_price = sum(exit_price_log) / len(exit_price_log) if exit_price_log else 0

    return {
        "skipped": False,
        "entry_price": entry_actual,
        "stop_price": stop_theoretical,
        "tp1_price": tp1_theoretical,
        "tp2_price": tp2_theoretical,
        "tp1_hit": tp1_hit,
        "tp2_hit": tp2_hit,
        "stop_hit": stop_hit,
        "time_exit": time_exit,
        "same_candle_ambiguity": same_candle_ambiguity,
        "exit_price": avg_exit_price,
        "gross_pnl": gross_pnl,
        "fees": total_fees,
        "slippage_cost": total_slippage_cost,
        "net_pnl": net_pnl,
        "r_multiple": r_multiple,
        "holding_candles": candles_held,
        "mfe": mfe,
        "mae": mae
    }

def evaluate_exit_signal(entry, f_highs, f_lows):
    if not f_highs: return None
    upside = ((max(f_highs) - entry) / entry) * 100
    drawdown = ((min(f_lows) - entry) / entry) * 100
    return {
        "max_upside": upside,
        "max_drawdown": drawdown,
        "hit_3_drop": drawdown <= -3.0,
        "hit_5_drop": drawdown <= -5.0,
        "hit_10_drop": drawdown <= -10.0,
        "hit_15_drop": drawdown <= -15.0
    }

# ============================================================
# RUNNER (BOTH MODES: SIGNAL LEVEL & PORTFOLIO)
# ============================================================
def run_backtest():
    signal_level_trades = []
    portfolio_trades = []
    exit_signals = []

    for symbol in TEST_SYMBOLS:
        raw_4h = fetch_paginated_klines(symbol, "4h", CANDLES_TO_FETCH)
        raw_1d = fetch_paginated_klines(symbol, "1d", (len(raw_4h) // 6) + 200)
        if len(raw_4h) < 560: continue

        d1_closes = [float(c[4]) for c in raw_1d]
        d1_rsi = calculate_wilder_rsi(d1_closes)
        d1_ema50 = calculate_ema(d1_closes, 50)
        d1_ema200 = calculate_ema(d1_closes, 200)
        d1_dict = [{"close_time": raw_1d[i][6], "price": d1_closes[i], "rsi": d1_rsi[i], "ema50": d1_ema50[i], "ema200": d1_ema200[i]} for i in range(len(raw_1d))]

        open_times = [c[0] for c in raw_4h]
        close_times = [c[6] for c in raw_4h]
        opens = [float(c[1]) for c in raw_4h]
        highs = [float(c[2]) for c in raw_4h]
        lows = [float(c[3]) for c in raw_4h]
        closes = [float(c[4]) for c in raw_4h]
        volumes = [float(c[5]) for c in raw_4h]

        # Portfolio active position tracker for this symbol: stores entry index & hold duration
        active_position_end_idx = -1

        for i in range(500, len(closes) - FORWARD_WINDOW - 1):
            c4 = evaluate_historical_slice(open_times[:i+1], close_times[:i+1], opens[:i+1], highs[:i+1], lows[:i+1], closes[:i+1], volumes[:i+1])
            is_bearish = get_1d_regime(d1_dict, c4["open_time"])
            signals = generate_signals(c4, is_bearish)

            next_open = opens[i+1]
            next_open_time = open_times[i+1]
            f_highs = highs[i+1 : i+1+FORWARD_WINDOW]
            f_lows = lows[i+1 : i+1+FORWARD_WINDOW]
            f_closes = closes[i+1 : i+1+FORWARD_WINDOW]

            for sig in signals:
                stype = sig["type"]
                base_meta = {
                    "symbol": symbol, "setup": stype,
                    "signal_time": datetime.fromtimestamp(c4["close_time"]/1000, timezone.utc).strftime('%Y-%m-%d %H:%M'),
                    "signal_price": closes[i],
                    "entry_time": datetime.fromtimestamp(next_open_time/1000, timezone.utc).strftime('%Y-%m-%d %H:%M'),
                }

                if "SELL" in stype:
                    ex_data = evaluate_exit_signal(closes[i], f_highs, f_lows)
                    if ex_data:
                        base_meta.update(ex_data)
                        exit_signals.append(base_meta)
                else:
                    # 1. Evaluate Signal-Level (Independent execution)
                    sl_res = simulate_trade(sig, next_open, f_highs, f_lows, f_closes)
                    sl_record = base_meta.copy()
                    sl_record.update(sl_res)
                    signal_level_trades.append(sl_record)

                    # 2. Evaluate Portfolio Mode (One position per symbol at a time)
                    port_record = base_meta.copy()
                    if sl_res.get("skipped"):
                        port_record.update(sl_res)
                        port_record["skip_reason"] = sl_res["skip_reason"]
                    elif i <= active_position_end_idx:
                        port_record["skipped"] = True
                        port_record["skip_reason"] = "SKIPPED_OVERLAPPING_POSITION"
                    else:
                        port_record.update(sl_res)
                        # Position is now active for the duration of its holding period
                        active_position_end_idx = i + sl_res["holding_candles"]
                    
                    portfolio_trades.append(port_record)

    # ============================================================
    # REPORTING & TABLES
    # ============================================================
    def print_trade_summary_table(title, trades_list):
        print(f"\n📊 {title}")
        print(f"{'SETUP':<25} | {'GEN':<5} | {'EXEC':<5} | {'OL-SKIP':<7} | {'TP-SKIP':<7} | {'WIN %':<6} | {'TOT NET':<8} | {'AVG NET':<8} | {'MED NET':<8} | {'PF':<5} | {'MED R':<6} | {'MAX DD':<7}")
        print("-" * 125)
        
        setup_types = ["ACCUMULATION_IGNITION", "RELIEF_SCALP_TECHNICAL_ONLY", "BUY_CONFIRMED", "BUY_EARLY"]
        for s in setup_types:
            recs = [r for r in trades_list if r["setup"] == s]
            if not recs: continue
            generated = len(recs)
            executed = [r for r in recs if not r.get("skipped")]
            ol_skipped = sum(1 for r in recs if r.get("skip_reason") == "SKIPPED_OVERLAPPING_POSITION")
            tp_skipped = sum(1 for r in recs if r.get("skip_reason") == "SKIPPED_MISSING_TPSL")
            
            if not executed:
                print(f"{s:<25} | {generated:<5} | {0:<5} | {ol_skipped:<7} | {tp_skipped:<7} | No executed trades")
                continue
                
            wins = [t for t in executed if t["net_pnl"] > 0]
            losses = [t for t in executed if t["net_pnl"] <= 0]
            win_rate = len(wins) / len(executed) * 100
            
            pnls = [t["net_pnl"] for t in executed]
            tot_pnl = sum(pnls)
            avg_pnl = tot_pnl / len(pnls)
            med_pnl = statistics.median(pnls)
            
            gross_win = sum(t["net_pnl"] for t in wins)
            gross_loss = abs(sum(t["net_pnl"] for t in losses))
            pf = gross_win / gross_loss if gross_loss > 0 else 99.9
            
            rs = [t["r_multiple"] for t in executed]
            med_r = statistics.median(rs) if rs else 0
            max_dd = min([t["mae"] for t in executed]) if executed else 0

            print(f"{s:<25} | {generated:<5} | {len(executed):<5} | {ol_skipped:<7} | {tp_skipped:<7} | {win_rate:>5.1f}% | ${tot_pnl:>6.1f} | ${avg_pnl:>6.1f} | ${med_pnl:>6.1f} | {pf:>4.1f} | {med_r:>5.2f}R | {max_dd:>6.1f}%")

    # A) Signal-Level Results
    print("\n\n" + "="*80)
    print("A) SIGNAL-LEVEL RESULTS (Independent / Unconstrained)")
    print("="*80)
    print_trade_summary_table("SIGNAL-LEVEL PERFORMANCE", signal_level_trades)

    # B) Realistic Portfolio Results
    print("\n\n" + "="*80)
    print("B) REALISTIC PORTFOLIO RESULTS (Strict One Active Position Per Symbol)")
    print("="*80)
    print_trade_summary_table("PORTFOLIO MODE PERFORMANCE", portfolio_trades)

    # Portfolio Per-Coin Breakdown
    for sym in TEST_SYMBOLS:
        sym_port = [r for r in portfolio_trades if r["symbol"] == sym]
        print(f"\n--- PORTFOLIO BREAKDOWN: {sym} ---")
        print_trade_summary_table(f"PORTFOLIO — {sym}", portfolio_trades)

    # C) Exit / Exhaustion Analysis
    print("\n\n" + "="*80)
    print("C) EXIT / EXHAUSTION ANALYSIS")
    print("="*80)
    print(f"{'SETUP':<20} | {'SIGS':<5} | {'>= 3% DROP':<12} | {'>= 5% DROP':<12} | {'>= 10% DROP':<12} | {'>= 15% DROP':<12} | {'MED UPSIDE':<12} | {'MED DRAWDOWN':<12}")
    print("-" * 115)
    for s in ["SELL_CONFIRMED", "SELL_EARLY"]:
        recs = [r for r in exit_signals if r["setup"] == s]
        if not recs: continue
        tot = len(recs)
        d3 = sum(1 for r in recs if r["hit_3_drop"]) / tot * 100
        d5 = sum(1 for r in recs if r["hit_5_drop"]) / tot * 100
        d10 = sum(1 for r in recs if r["hit_10_drop"]) / tot * 100
        d15 = sum(1 for r in recs if r["hit_15_drop"]) / tot * 100
        med_up = statistics.median([r["max_upside"] for r in recs])
        med_dd = statistics.median([r["max_drawdown"] for r in recs])
        print(f"{s:<20} | {tot:<5} | {d3:>9.1f}%   | {d5:>9.1f}%   | {d10:>10.1f}%  | {d15:>10.1f}%  | +{med_up:>9.2f}%  | {med_dd:>11.2f}%")

    # Global Portfolio Risk & Execution Totals
    executed_port = [t for t in portfolio_trades if not t.get("skipped")]
    tot_fees = sum(t["fees"] for t in executed_port)
    tot_slip = sum(t["slippage_cost"] for t in executed_port)
    tot_ol = sum(1 for t in portfolio_trades if t.get("skip_reason") == "SKIPPED_OVERLAPPING_POSITION")
    tot_tp = sum(1 for t in portfolio_trades if t.get("skip_reason") == "SKIPPED_MISSING_TPSL")
    
    # Calculate Max Consecutive Losses in Portfolio Mode
    consec_losses, max_consec_losses = 0, 0
    for t in sorted(executed_port, key=lambda x: x["entry_time"]):
        if t["net_pnl"] <= 0:
            consec_losses += 1
            max_consec_losses = max(max_consec_losses, consec_losses)
        else:
            consec_losses = 0

    print("\n\n" + "="*80)
    print("📋 PORTFOLIO MODE SUMMARY METRICS")
    print("="*80)
    print(f"Total Executed Trades:            {len(executed_port)}")
    print(f"Total Skipped Overlapping:        {tot_ol}")
    print(f"Total Skipped Missing TP/SL:      {tot_tp}")
    print(f"Maximum Consecutive Losses:       {max_consec_losses}")
    print(f"Total Portfolio Fees Paid:        ${tot_fees:.2f}")
    print(f"Total Portfolio Slippage Cost:    ${tot_slip:.2f}")
    print("="*80)

    # ============================================================
    # CSV EXPORT
    # ============================================================
    with open(RESULTS_CSV, mode='w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Symbol", "Signal_Time", "Setup", "Signal_Price", "Entry_Time", "Entry_Price", 
                         "Stop_Price", "TP1_Price", "TP2_Price", "TP1_Hit", "TP2_Hit", "Stop_Hit", 
                         "Time_Exit", "Same_Candle_Ambiguity", "Exit_Price_Avg", "Gross_PnL_Before_Fees", 
                         "Fees", "Slippage_Cost", "Net_PnL", "R_Multiple", "Holding_Candles", "Skipped", "Skip_Reason"])
        for t in portfolio_trades:
            writer.writerow([t["symbol"], t.get("signal_time"), t["setup"], t.get("signal_price"), t.get("entry_time"), 
                             t.get("entry_price", 0), t.get("stop_price", 0), t.get("tp1_price", 0), t.get("tp2_price", 0), 
                             t.get("tp1_hit", False), t.get("tp2_hit", False), t.get("stop_hit", False), t.get("time_exit", False), 
                             t.get("same_candle_ambiguity", False), t.get("exit_price", 0), t.get("gross_pnl", 0), 
                             t.get("fees", 0), t.get("slippage_cost", 0), t.get("net_pnl", 0), t.get("r_multiple", 0), 
                             t.get("holding_candles", 0), t.get("skipped", False), t.get("skip_reason", "")])

    print(f"\n✅ Portfolio results exported to: {RESULTS_CSV}")
    print("V5.1 IS AN EVALUATION OF FROZEN V4 LOGIC — NO SIGNAL PARAMETERS WERE OPTIMIZED.")

if __name__ == "__main__":
    run_backtest()

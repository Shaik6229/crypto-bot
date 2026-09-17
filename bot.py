import logging
import os
import time
import statistics
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CryptoBot4H")

# --- ENVIRONMENT & EXECUTION MODE ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
RUN_MODE = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")

# --- VETTED ASSET UNIVERSES (Spot-Only) ---
CORE_WATCHLIST = [
    "SOLUSDT", "XRPUSDT", "CNPYUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT",
    "XLMUSDT", "ALGOUSDT", "NIGHTUSDT", "POLUSDT", "FETUSDT", "TONUSDT",
    "AVAXUSDT", "NEARUSDT", "TRXUSDT", "KITEUSDT"
]

L1_L2_UNIVERSE = [
    "APTUSDT", "SEIUSDT", "INJUSDT", "TIAUSDT", "ARBUSDT",
    "OPUSDT", "HBARUSDT", "ICPUSDT", "FTMUSDT",
    "EGLDUSDT", "FLOWUSDT", "STXUSDT", "ROSEUSDT", "CELOUSDT"
]

AI_UNIVERSE = [
    "TAOUSDT", "RENDERUSDT", "GRTUSDT", "THETAUSDT", "AKTUSDT",
    "ARKMUSDT", "GLMUSDT", "RLCUSDT", "IOUSDT", "JASMYUSDT",
    "IQUSDT", "NMRUSDT", "PHBUSDT", "TRACUSDT", "PHAUSDT"
]

# --- RESILIENT HTTP SESSION ---
def get_http_session():
    session = requests.Session()
    retries = Retry(total=4, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

HTTP = get_http_session()

# --- FORMATTING HELPER ---
def format_price(val):
    if val is None or val == 0:
        return "0.00"
    abs_val = abs(val)
    if abs_val >= 100: return f"{val:,.2f}"
    elif abs_val >= 1: return f"{val:.4f}"
    elif abs_val >= 0.01: return f"{val:.4f}"
    elif abs_val >= 0.0001: return f"{val:.6f}"
    else: return f"{val:.8f}"

# --- TELEGRAM BROADCASTER ---
def _send_single_telegram_chunk(text):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    for attempt in range(1, 4):
        try:
            res = HTTP.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=12)
            if res.status_code == 429:
                time.sleep(res.json().get("parameters", {}).get("retry_after", 3))
                continue
            if res.status_code == 400 and "can't parse entities" in res.text.lower():
                HTTP.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=12)
                return
            res.raise_for_status()
            return
        except requests.RequestException:
            time.sleep(1.5 * attempt)

def send_telegram(msg):
    if not msg: return
    max_len = 3800
    if len(msg) <= max_len:
        _send_single_telegram_chunk(msg)
        return
    paragraphs = msg.split("\n\n")
    current_chunk = ""
    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 <= max_len:
            current_chunk += (para + "\n\n")
        else:
            if current_chunk.strip():
                _send_single_telegram_chunk(current_chunk.strip())
                time.sleep(1.0)
            current_chunk = para + "\n\n"
    if current_chunk.strip():
        _send_single_telegram_chunk(current_chunk.strip())

# --- MATHEMATICAL ENGINES ---
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
    for i in range(period, n):
        rma[i] = (rma[i - 1] * (period - 1) + data[i]) / period
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

# --- 1D CONTEXT FETCH ---
def fetch_1d_context(symbol):
    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=1d&limit=500"
        res = HTTP.get(url, timeout=8)
        res.raise_for_status()
        raw = res.json()
        closes = [float(c[4]) for c in raw]
        idx = len(closes) - 2  # Anchor to closed daily candle
        
        rsi_series = calculate_wilder_rsi(closes)
        ema50 = calculate_ema(closes, 50)
        ema200 = calculate_ema(closes, 200)
        
        c_price, c_rsi, c_ema50, c_ema200 = closes[idx], rsi_series[idx], ema50[idx], ema200[idx]
        
        bearish_points = 0
        if c_price < c_ema50: bearish_points += 1
        if c_ema50 < c_ema200: bearish_points += 1
        if c_rsi < 45: bearish_points += 1
        
        return {"price": c_price, "rsi": c_rsi, "ema50": c_ema50, "ema200": c_ema200, "is_bearish": (bearish_points >= 2)}
    except Exception as e:
        logger.warning(f"Could not fetch 1D context for {symbol}: {e}")
        return {"price": 0, "rsi": 50.0, "ema50": 0, "ema200": 0, "is_bearish": False}

# --- 4H MARKET DATA FETCH ---
def fetch_4h_data(symbol, limit=500):
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=4h&limit={limit}"
    res = HTTP.get(url, timeout=10)
    res.raise_for_status()
    raw = res.json()

    opens, highs, lows, closes, volumes = [], [], [], [], []
    for c in raw:
        opens.append(float(c[1]))
        highs.append(float(c[2]))
        lows.append(float(c[3]))
        closes.append(float(c[4]))
        volumes.append(float(c[5]))

    idx = len(closes) - 2  # Anchor strictly to closed 4H candle
    rsi_series = calculate_wilder_rsi(closes)
    _, _, macd_hist = calculate_macd(closes)
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    ema200 = calculate_ema(closes, 200)
    atr = calculate_atr(highs, lows, closes)

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

    vol_median = statistics.median(volumes[max(0, idx - 20):idx]) if volumes[max(0, idx - 20):idx] else 1.0
    candle_range = c_high - c_low

    candles_below_ema20 = 0
    for i in range(idx - 1, max(0, idx - 25), -1):
        if closes[i] < ema20[i]: candles_below_ema20 += 1
        else: break

    consolidation_high = max(highs[max(0, idx - 12):idx]) if idx > 0 else c_high

    return {
        "price": c_close, "open": c_open, "low": c_low, "high": c_high,
        "structural_low": struct_low, "structural_high": struct_high,
        "rsi": c_rsi, "hist_slope_up": c_hist > prev_hist, "hist_slope_down": c_hist < prev_hist,
        "macd_hist_crossed_positive": c_hist > 0 and prev_hist <= 0,
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

# --- LIVE BINANCE ORDER BOOK DEPTH ---
def fetch_order_book(symbol, current_price):
    try:
        url = f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=100"
        res = HTTP.get(url, timeout=6)
        res.raise_for_status()
        raw = res.json()
        bids = [[float(p), float(q)] for p in raw.get("bids", [])]
        asks = [[float(p), float(q)] for p in raw.get("asks", [])]

        if not bids or not asks:
            return {"bid_depth_1pct": 0, "ask_depth_1pct": 0, "bid_wall_price": current_price, "ask_wall_price": current_price}

        bids_1pct_levels = [x for x in bids if x[0] >= current_price * 0.99]
        asks_1pct_levels = [x for x in asks if x[0] <= current_price * 1.01]

        bids_1pct = sum(p * q for p, q in bids_1pct_levels)
        asks_1pct = sum(p * q for p, q in asks_1pct_levels)

        largest_bid = max(bids_1pct_levels, key=lambda x: x[0] * x[1]) if bids_1pct_levels else [current_price, 0]
        largest_ask = max(asks_1pct_levels, key=lambda x: x[0] * x[1]) if asks_1pct_levels else [current_price, 0]

        return {
            "bid_depth_1pct": bids_1pct, "ask_depth_1pct": asks_1pct,
            "bid_wall_price": largest_bid[0], "ask_wall_price": largest_ask[0]
        }
    except Exception as e:
        logger.warning(f"Could not fetch order book for {symbol}: {e}")
        return {"bid_depth_1pct": 0, "ask_depth_1pct": 0, "bid_wall_price": current_price, "ask_wall_price": current_price}

# --- DIRECTIONAL PREDICTION ENGINE (FOR MANUAL DIAGNOSTIC) ---
def analyze_market_direction(c4, ob, d1):
    p = c4["price"]
    up_score = 0
    down_score = 0
    drivers = []

    # 1. EMA Trend Stack
    if p > c4["ema20"]:
        up_score += 2
        drivers.append("holding >20-EMA")
    else:
        down_score += 2
        drivers.append("trapped <20-EMA")

    if p > c4["ema50"]:
        up_score += 1
    else:
        down_score += 1

    # 2. MACD Momentum
    if c4["hist_slope_up"]:
        up_score += 2
        drivers.append("MACD curling up")
    elif c4["hist_slope_down"]:
        down_score += 2
        drivers.append("MACD fading down")

    # 3. RSI Flow
    if c4["rsi"] >= 52:
        up_score += 1
    elif c4["rsi"] <= 48:
        down_score += 1

    if c4["bullish_div"]:
        up_score += 2
        drivers.append("bullish divergence")
    elif c4["bearish_div"]:
        down_score += 2
        drivers.append("bearish divergence")

    # 4. Macro 1D Context
    if not d1["is_bearish"]:
        up_score += 1
    else:
        down_score += 1
        drivers.append("1D downtrend drag")

    # 5. Liquidity Support
    if ob["bid_depth_1pct"] > (1.2 * ob["ask_depth_1pct"]):
        up_score += 1
    elif ob["ask_depth_1pct"] > (1.2 * ob["bid_depth_1pct"]):
        down_score += 1

    # Determine Verdict & Targets
    reason_str = ", ".join(drivers[:2]) if drivers else "mixed technical factors"

    if up_score >= down_score + 2:
        verdict = "🔼 UP BIAS"
        targets = [v for v in [c4["ema50"], c4["ema200"], c4["consolidation_high"], c4["structural_high"]] if v > p * 1.005]
        target_price = min(targets) if targets else p * 1.05
        floors = [v for v in [c4["ema20"], ob["bid_wall_price"], c4["structural_low"]] if v < p * 0.995]
        floor_price = max(floors) if floors else p * 0.95
        action_note = f"Target: ${format_price(target_price)} | Support: ${format_price(floor_price)} ({reason_str})"
    elif down_score >= up_score + 2:
        verdict = "🔽 DOWN BIAS"
        targets = [v for v in [c4["ema20"], c4["ema50"], ob["bid_wall_price"], c4["structural_low"]] if v < p * 0.995]
        target_price = max(targets) if targets else p * 0.95
        ceilings = [v for v in [c4["ema20"], c4["ema50"], ob["ask_wall_price"]] if v > p * 1.005]
        ceiling_price = min(ceilings) if ceilings else p * 1.05
        action_note = f"Downside: ${format_price(target_price)} | Ceiling: ${format_price(ceiling_price)} ({reason_str})"
    else:
        verdict = "⚖️ SIDEWAYS"
        action_note = f"Range: ${format_price(c4['low'])} – ${format_price(c4['high'])} (Chop / Indecision)"

    return verdict, action_note

# --- 4H SCORING & SETUP EVALUATION (FROZEN LIVE STRATEGY) ---
def evaluate_market_condition(c4, ob, d1):
    p = c4["price"]
    ema20 = c4["ema20"]
    ema_stretch_20 = ((p - ema20) / ema20) * 100
    active_setups = []

    # 1. COUNTER-TREND RELIEF SCALP
    if (d1["is_bearish"] and ema_stretch_20 <= -7.5 and c4["rsi"] <= 28.0 and c4["vol_ratio"] >= 2.2 and 
        ob["bid_depth_1pct"] > 0 and ob["ask_depth_1pct"] > 0 and ob["bid_depth_1pct"] >= (1.5 * ob["ask_depth_1pct"])):
        
        tp1 = ema20
        tp2_candidates = [v for v in [c4["ema50"], c4["consolidation_high"], c4["structural_high"]] if v > tp1]
        tp2 = min(tp2_candidates) if tp2_candidates else tp1 * 1.04
        
        active_setups.append({
            "type": "RELIEF_SCALP",
            "ema_stretch": ema_stretch_20,
            "tp1": tp1,
            "tp2": tp2,
            "stop": c4["low"] * 0.992
        })

    # 2. ACCUMULATION IGNITION
    if (c4["candles_below_ema20"] >= 10 and (p > ema20) and (c4["open"] <= ema20 * 1.005) and 
        p >= c4["consolidation_high"] * 0.998 and c4["vol_ratio"] >= 1.6 and 
        (c4["bullish_candle"] and c4["upper_wick"] <= 0.25) and 
        (c4["macd_hist_crossed_positive"] or c4["hist_slope_up"])):
        
        tp1 = c4["ema50"] if c4["ema50"] > p else p * 1.06
        tp2 = c4["structural_high"] if c4["structural_high"] > p else p * 1.12
        
        active_setups.append({
            "type": "ACCUMULATION_IGNITION",
            "tp1": tp1,
            "tp2": tp2,
            "stop": min(c4["low"], p * 0.96),
            "reasons": [
                f"Breakout after {c4['candles_below_ema20']} candles compressed below 4H 20-EMA.",
                f"Ignition volume surge ({c4['vol_ratio']:.1f}x median).",
                f"Reclaimed local consolidation high at ${format_price(c4['consolidation_high'])}.",
                "MACD momentum flipped upward."
            ]
        })

    # 3. INDEPENDENT BUY & SELL SCORING
    buy_score, exit_score = 0, 0
    buy_factors, exit_factors = [], []

    if p - c4["structural_low"] <= 1.5 * c4["atr"]:
        buy_score += 15
        buy_factors.append("Lowest 4H low in the lookback window.")
    if c4["ema200_ext"] < -15.0:
        buy_score += 10
        buy_factors.append(f"Severely discounted below 4H 200-EMA ({c4['ema200_ext']:+.1f}%).")
    if c4["rsi"] < 30:
        buy_score += 15
        buy_factors.append(f"4H sellers exhausted (RSI {c4['rsi']:.1f}).")
    if c4["bullish_div"]:
        buy_score += 15
        buy_factors.append("Confirmed 4H Bullish Divergence.")
    if c4["lower_wick"] >= 0.35:
        buy_score += 10
        buy_factors.append("Strong lower wick absorption by spot buyers.")

    if c4["structural_high"] - p <= 1.5 * c4["atr"]:
        exit_score += 15
        exit_factors.append("Highest 4H high in the lookback window.")
    if c4["ema200_ext"] > 25.0:
        exit_score += 10
        exit_factors.append(f"Severely stretched above 4H 200-EMA ({c4['ema200_ext']:+.1f}%).")
    if c4["rsi"] > 70:
        exit_score += 15
        exit_factors.append(f"4H buyers exhausted (RSI {c4['rsi']:.1f}).")
    if c4["bearish_div"]:
        exit_score += 15
        exit_factors.append("Confirmed 4H Bearish Divergence.")
    if c4["upper_wick"] >= 0.35:
        exit_score += 10
        exit_factors.append("Strong upper wick rejection by sellers.")

    if ob["bid_depth_1pct"] > (1.3 * ob["ask_depth_1pct"]):
        buy_score += 10
        buy_factors.append("Order book bid depth significantly outpaces asks.")
    if ob["ask_depth_1pct"] > (1.3 * ob["bid_depth_1pct"]):
        exit_score += 10
        exit_factors.append("Order book ask resistance heavily outweighs bids.")

    if d1["is_bearish"]:
        buy_score = max(0, buy_score - 25)

    if buy_score >= 65: active_setups.append({"type": "BUY_CONFIRMED", "score": buy_score, "reasons": buy_factors})
    elif buy_score >= 45: active_setups.append({"type": "BUY_EARLY", "score": buy_score, "reasons": buy_factors})

    if exit_score >= 65: active_setups.append({"type": "SELL_CONFIRMED", "score": exit_score, "reasons": exit_factors})
    elif exit_score >= 45: active_setups.append({"type": "SELL_EARLY", "score": exit_score, "reasons": exit_factors})

    return active_setups

# --- DYNAMIC MOVER DISCOVERY ---
def get_dynamic_movers():
    try:
        res = HTTP.get("https://data-api.binance.vision/api/v3/ticker/24hr", timeout=10)
        tickers = res.json()
        l1s = sorted([t for t in tickers if t.get("symbol") in L1_L2_UNIVERSE and t.get("symbol") not in CORE_WATCHLIST], key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        ais = sorted([t for t in tickers if t.get("symbol") in AI_UNIVERSE and t.get("symbol") not in CORE_WATCHLIST], key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        return [t["symbol"] for t in l1s[:3]], [t["symbol"] for t in ais[:3]]
    except Exception: return [], []

# --- MAIN CONTROLLER ---
def check_4h_market():
    logger.info("Initializing 4H Tactical Scanner...")
    top_l1, top_ai = get_dynamic_movers()
    full_watchlist = list(dict.fromkeys(CORE_WATCHLIST + top_l1 + top_ai))
    alerts_fired = 0

    manual_summary = (
        "🧭 *[MANUAL 4H MARKET DIRECTION REPORT]* 🧭\n"
        "_Where prices are likely heading from current levels:_\n\n"
    )

    for symbol in full_watchlist:
        coin_name = symbol.replace("USDT", "")
        try:
            c4 = fetch_4h_data(symbol)
            ob = fetch_order_book(symbol, c4["price"])
            d1 = fetch_1d_context(symbol)
            
            p_str = format_price(c4["price"])
            support_str = format_price(ob["bid_wall_price"])
            resist_str = format_price(ob["ask_wall_price"])

            # 1. Compute Directional Prediction for Manual Runs
            if RUN_MODE != "schedule":
                verdict, action_note = analyze_market_direction(c4, ob, d1)
                manual_summary += (
                    f"• *{coin_name}* (${p_str}) : *{verdict}*\n"
                    f"  ↳ {action_note}\n\n"
                )

            # 2. Check Setups (Frozen Logic)
            setups = evaluate_market_condition(c4, ob, d1)

            for setup in setups:
                stype = setup["type"]
                alerts_fired += 1
                
                if stype == "RELIEF_SCALP":
                    msg = (
                        f"⚡ *4H COUNTER-TREND RELIEF SCALP* : {coin_name}\n\n"
                        f"• *Entry Region:* ${format_price(c4['low'])} – ${p_str}\n"
                        f"• 🛡️ *Largest Visible Bid Wall:* ${support_str}\n"
                        f"• 📉 *Deviation from 4H 20-EMA:* {setup['ema_stretch']:.1f}%\n"
                        f"• ⚡ *4H Panic RSI:* {c4['rsi']:.1f} | *Volume:* {c4['vol_ratio']:.1f}x Median\n"
                        f"• 🌍 *1D Macro Context:* 🔴 Bearish Downtrend\n\n"
                        f"*Tactical Plan:*\n"
                        f"• 🎯 *Take Profit 1 (70%):* ${format_price(setup['tp1'])} (Retest 4H 20-EMA)\n"
                        f"• 🎯 *Take Profit 2 (30%):* ${format_price(setup['tp2'])}\n"
                        f"• 🛑 *Invalidation Stop:* Clean 4H close below ${format_price(setup['stop'])}\n\n"
                        f"📍 *Execution Rule:* Bounce play. Scale out into USDT at targets."
                    )
                elif stype == "ACCUMULATION_IGNITION":
                    msg = (
                        f"🚀 *4H ACCUMULATION IGNITION* : {coin_name}\n\n"
                        f"• *Current Price:* ${p_str}\n"
                        f"• 📈 *Ignition Volume:* {c4['vol_ratio']:.1f}x Median\n"
                        f"• ⏳ *Suppression Duration:* {c4['candles_below_ema20']} candles ({c4['candles_below_ema20']*4}h) below 20-EMA\n"
                        f"• 🛡️ *Largest Visible Bid Wall:* ${support_str}\n\n"
                        f"*Why the bot flagged this:*\n• " + "\n• ".join(setup["reasons"]) + "\n\n"
                        f"*Tactical Plan:*\n"
                        f"• 🎯 *Take Profit 1 (50%):* ${format_price(setup['tp1'])}\n"
                        f"• 🎯 *Take Profit 2 (50%):* ${format_price(setup['tp2'])}\n"
                        f"• 🛑 *Invalidation Stop:* Clean 4H close below ${format_price(setup['stop'])}\n\n"
                        f"📍 *Execution Rule:* Scale into spot at market or on 20-EMA retest."
                    )
                elif stype in ["BUY_CONFIRMED", "BUY_EARLY"]:
                    header = "🟢 *CONFIRMED BOTTOM REVERSAL*" if stype == "BUY_CONFIRMED" else "🟡 *EARLY BOTTOM WARNING*"
                    msg = (
                        f"{header} : {coin_name}\n\n"
                        f"• *Current Price:* ${p_str}\n"
                        f"• 🛡️ *Largest Visible Bid Wall (Support):* ${support_str}\n"
                        f"• 💧 *Visible Ask Liquidity Within 1%:* ${ob['ask_depth_1pct']:,.0f}\n"
                        f"• 🌍 *1D Macro RSI:* {d1['rsi']:.1f}\n\n"
                        f"*Why the bot flagged this:*\n• " + "\n• ".join(setup["reasons"]) + "\n\n"
                        f"📍 *What to do:* Bottom confluence detected. Consider Spot Limit Buy near support at **${support_str}**."
                    )
                elif stype in ["SELL_CONFIRMED", "SELL_EARLY"]:
                    header = "🔴 *CONFIRMED TOP EXHAUSTION*" if stype == "SELL_CONFIRMED" else "🟠 *RALLY OVERHEATING*"
                    msg = (
                        f"{header} : {coin_name}\n\n"
                        f"• *Current Price:* ${p_str}\n"
                        f"• 🎯 *Largest Visible Ask Wall (Resistance):* ${resist_str}\n"
                        f"• 💧 *Visible Bid Liquidity Within 1%:* ${ob['bid_depth_1pct']:,.0f}\n"
                        f"• ⚡ *4H RSI:* {c4['rsi']:.1f}\n\n"
                        f"*Why the bot flagged this:*\n• " + "\n• ".join(setup["reasons"]) + "\n\n"
                        f"📍 *What to do:* Rally exhaustion detected. Consider spot profit-taking into USDT."
                    )
                    
                send_telegram(msg)
                time.sleep(1.0)

        except Exception as e:
            logger.error(f"Failed 4H analysis for {symbol}: {e}")
            continue

    # Send the detailed directional diagnostic when manually triggered
    if RUN_MODE != "schedule":
        manual_summary += f"──────────────\n✅ *Scan Complete.* {len(full_watchlist)} coins checked. {alerts_fired} active alert(s) sent."
        send_telegram(manual_summary)

if __name__ == "__main__":
    check_4h_market()

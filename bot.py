import json
import logging
import os
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CryptoScanner")

# --- ENVIRONMENT & EXECUTION MODE ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
RUN_MODE = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
STATE_FILE = "bot_state.json"

# --- VETTED ASSET UNIVERSES (Shariah-Audited, Spot-Only, No Riba/Memes) ---
CORE_WATCHLIST = [
    "SOLUSDT", "XRPUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT",
    "XLMUSDT", "ALGOUSDT", "POLUSDT", "FETUSDT", "TONUSDT",
    "AVAXUSDT", "NEARUSDT", "KITEUSDT"
]

# Vetted Layer 1 / Layer 2 Infrastructure (ROSE retained here as L1)
L1_L2_UNIVERSE = [
    "APTUSDT", "SEIUSDT", "INJUSDT", "TIAUSDT", "ARBUSDT",
    "OPUSDT", "HBARUSDT", "ICPUSDT", "KASUSDT", "FTMUSDT",
    "EGLDUSDT", "FLOWUSDT", "STXUSDT", "ROSEUSDT", "CELOUSDT"
]

# Vetted Decentralized AI / Compute Infrastructure (ROSE removed to prevent overlap)
AI_UNIVERSE = [
    "TAOUSDT", "RENDERUSDT", "GRTUSDT", "THETAUSDT", "AKTUSDT",
    "ARKMUSDT", "GLMUSDT", "RLCUSDT", "IOUSDT", "JASMYUSDT",
    "IQUSDT", "NMRUSDT", "PHBUSDT", "TRACUSDT", "PHAUSDT"
]

# --- RESILIENT HTTP SESSION WITH RETRIES ---
def get_http_session():
    session = requests.Session()
    retries = Retry(total=4, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

HTTP = get_http_session()

# --- DYNAMIC PRICE FORMATTER ---
def format_price(val):
    if val is None or val == 0:
        return "0.00"
    abs_val = abs(val)
    if abs_val >= 100:
        return f"{val:,.2f}"
    elif abs_val >= 1:
        return f"{val:.4f}"
    elif abs_val >= 0.01:
        return f"{val:.4f}"
    elif abs_val >= 0.0001:
        return f"{val:.6f}"
    else:
        return f"{val:.8f}"

# --- STATE PERSISTENCE (Alert Deduplication & Liquidity Memory) ---
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load state file: {e}")
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save state file: {e}")

STATE = load_state()

def check_alert_cooldown(symbol, signal_type, current_price, atr):
    """Suppresses duplicate alerts for 12 hours unless price moves > 2 ATR or signal flips."""
    last_record = STATE.get(symbol, {}).get("alert", {})
    if not last_record:
        return False
    if last_record.get("signal") != signal_type:
        return False
    time_elapsed = time.time() - last_record.get("time", 0)
    price_moved = abs(current_price - last_record.get("price", 0)) >= (2.0 * atr)
    if time_elapsed < 43200 and not price_moved:
        return True
    return False

def record_alert(symbol, signal_type, price):
    if symbol not in STATE:
        STATE[symbol] = {}
    STATE[symbol]["alert"] = {"signal": signal_type, "price": price, "time": time.time()}
    save_state(STATE)

def update_liquidity_state(symbol, bid_cluster, ask_cluster):
    if symbol not in STATE:
        STATE[symbol] = {}
    STATE[symbol]["liquidity"] = {
        "bid": bid_cluster,
        "ask": ask_cluster,
        "time": time.time()
    }
    save_state(STATE)

# --- TELEGRAM BROADCASTER (Safe Chunking, Rate Limiting & Fallback) ---
def _send_single_telegram_chunk(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    for attempt in range(1, 4):
        try:
            res = HTTP.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=12)
            
            # Handle rate-limiting (429)
            if res.status_code == 429:
                retry_after = 3
                try:
                    retry_after = res.json().get("parameters", {}).get("retry_after", 3)
                except Exception:
                    pass
                logger.warning(f"Telegram rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
                
            # Handle Markdown entity error fallback
            if res.status_code == 400 and "can't parse entities" in res.text.lower():
                logger.warning("Markdown formatting rejected. Retrying as plain text...")
                HTTP.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=12)
                return

            res.raise_for_status()
            return
        except requests.RequestException as e:
            logger.warning(f"Telegram delivery attempt {attempt} failed: {e}")
            time.sleep(1.5 * attempt)
            
    logger.error("Failed to deliver Telegram message after 3 attempts.")

def send_telegram(msg):
    if not msg:
        return

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
            if len(para) > max_len:
                lines = para.split("\n")
                sub_chunk = ""
                for line in lines:
                    if len(sub_chunk) + len(line) + 1 <= max_len:
                        sub_chunk += (line + "\n")
                    else:
                        _send_single_telegram_chunk(sub_chunk.strip())
                        time.sleep(1.0)
                        sub_chunk = line + "\n"
                current_chunk = sub_chunk
            else:
                current_chunk = para + "\n\n"

    if current_chunk.strip():
        _send_single_telegram_chunk(current_chunk.strip())

# --- MATHEMATICAL ENGINES (1:1 Aligned, Closed-Candle Anchored) ---
def calculate_wilder_rsi(closes, period=14):
    n = len(closes)
    rsi = [50.0] * n
    if n < period + 1:
        return rsi
    gains, losses = [0.0] * n, [0.0] * n
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains[i] = diff
        else:
            losses[i] = -diff

    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    rsi[period] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi[i] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    for i in range(period):
        rsi[i] = rsi[period]
    return rsi

def calculate_ema(data, period):
    n = len(data)
    ema = [data[0]] * n
    k = 2.0 / (period + 1)
    for i in range(1, n):
        ema[i] = data[i] * k + ema[i - 1] * (1.0 - k)
    return ema

def calculate_rma(data, period):
    n = len(data)
    rma = [0.0] * n
    if n < period:
        return rma
    rma[period - 1] = sum(data[:period]) / period
    for i in range(period, n):
        rma[i] = (rma[i - 1] * (period - 1) + data[i]) / period
    for i in range(period - 1):
        rma[i] = rma[period - 1]
    return rma

def calculate_atr(highs, lows, closes, period=14):
    n = len(closes)
    tr = [0.0] * n
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    return calculate_rma(tr, period)

def calculate_macd(closes):
    ema12 = calculate_ema(closes, 12)
    ema26 = calculate_ema(closes, 26)
    macd_line = [ema12[i] - ema26[i] for i in range(len(closes))]
    signal_line = calculate_ema(macd_line, 9)
    hist = [macd_line[i] - signal_line[i] for i in range(len(closes))]
    return macd_line, signal_line, hist

# --- MARKET DATA & PIVOT RETRIEVAL ---
def fetch_candle_data(symbol, interval, limit=200):
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
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

    closed_idx = len(closes) - 2
    rsi_series = calculate_wilder_rsi(closes)
    _, _, macd_hist = calculate_macd(closes)
    ema200 = calculate_ema(closes, 200)
    atr = calculate_atr(highs, lows, closes)

    c_close, c_low, c_high = closes[closed_idx], lows[closed_idx], highs[closed_idx]
    c_rsi, c_hist, c_atr = rsi_series[closed_idx], macd_hist[closed_idx], atr[closed_idx]
    prev_hist = macd_hist[closed_idx - 1]

    prior_lows, prior_highs = lows[:closed_idx], highs[:closed_idx]
    structural_low = min(prior_lows) if prior_lows else c_low
    structural_high = max(prior_highs) if prior_highs else c_high
    struct_low_idx = prior_lows.index(structural_low) if prior_lows else 0
    struct_high_idx = prior_highs.index(structural_high) if prior_highs else 0

    local_swings_low = [(i, lows[i]) for i in range(5, closed_idx - 5) if lows[i] == min(lows[i - 5:i + 6])]
    local_swings_high = [(i, highs[i]) for i in range(5, closed_idx - 5) if highs[i] == max(highs[i - 5:i + 6])]
    recent_swing_low_idx, recent_swing_low = local_swings_low[-1] if local_swings_low else (struct_low_idx, structural_low)
    recent_swing_high_idx, recent_swing_high = local_swings_high[-1] if local_swings_high else (struct_high_idx, structural_high)

    recent_vols = volumes[max(0, closed_idx - 20):closed_idx]
    vol_median = sorted(recent_vols)[len(recent_vols) // 2] if recent_vols else 1.0
    vol_ratio = volumes[closed_idx] / vol_median

    candle_range = c_high - c_low
    lower_wick = (min(opens[closed_idx], c_close) - c_low) / candle_range if candle_range > 0 else 0
    upper_wick = (c_high - max(opens[closed_idx], c_close)) / candle_range if candle_range > 0 else 0

    ema200_ext = ((c_close - ema200[closed_idx]) / ema200[closed_idx]) * 100

    return {
        "price": c_close,
        "structural_low": structural_low,
        "structural_high": structural_high,
        "rsi": c_rsi,
        "hist_slope_up": c_hist > prev_hist,
        "hist_slope_down": c_hist < prev_hist,
        "bullish_div": c_low <= recent_swing_low * 1.02 and c_rsi > rsi_series[recent_swing_low_idx],
        "macd_bullish_div": c_low <= recent_swing_low * 1.02 and c_hist > macd_hist[recent_swing_low_idx],
        "bearish_div": c_high >= recent_swing_high * 0.98 and c_rsi < rsi_series[recent_swing_high_idx],
        "macd_bearish_div": c_high >= recent_swing_high * 0.98 and c_hist < macd_hist[recent_swing_high_idx],
        "vol_ratio": vol_ratio,
        "lower_wick": lower_wick,
        "upper_wick": upper_wick,
        "ema200_ext": ema200_ext,
        "atr": c_atr
    }

# --- NOTIONAL & SIZE-AWARE LIQUIDITY ANALYSIS ---
def analyze_liquidity(symbol, current_price, atr):
    url = f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=100"
    try:
        res = HTTP.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()

        valid_band = max(1.5 * atr, current_price * 0.02)
        slip_band = current_price * 0.01

        bids, asks = [], []
        bid_depth_1pct, ask_depth_1pct = 0.0, 0.0

        for b in data.get("bids", []):
            p, q = float(b[0]), float(b[1])
            if current_price - p <= valid_band:
                n = p * q
                bids.append({"p": p, "n": n})
                if current_price - p <= slip_band:
                    bid_depth_1pct += n

        for a in data.get("asks", []):
            p, q = float(a[0]), float(a[1])
            if p - current_price <= valid_band:
                n = p * q
                asks.append({"p": p, "n": n})
                if p - current_price <= slip_band:
                    ask_depth_1pct += n

        best_bid, max_bid_notional = current_price, 0.0
        for b in bids:
            cluster_val = sum(x["n"] for x in bids if abs(x["p"] - b["p"]) <= current_price * 0.004)
            if cluster_val > max_bid_notional:
                best_bid, max_bid_notional = b["p"], cluster_val

        best_ask, max_ask_notional = current_price, 0.0
        for a in asks:
            cluster_val = sum(x["n"] for x in asks if abs(x["p"] - a["p"]) <= current_price * 0.004)
            if cluster_val > max_ask_notional:
                best_ask, max_ask_notional = a["p"], cluster_val

        prev_liq = STATE.get(symbol, {}).get("liquidity", {})
        bid_persistent, ask_persistent = False, False

        if prev_liq:
            pb = prev_liq.get("bid", {})
            if pb.get("price", 0) > 0:
                if abs(best_bid - pb["price"]) < current_price * 0.005 and max_bid_notional >= (pb.get("notional", 0) * 0.5):
                    bid_persistent = True
            pa = prev_liq.get("ask", {})
            if pa.get("price", 0) > 0:
                if abs(best_ask - pa["price"]) < current_price * 0.005 and max_ask_notional >= (pa.get("notional", 0) * 0.5):
                    ask_persistent = True

        update_liquidity_state(
            symbol,
            {"price": best_bid, "notional": max_bid_notional},
            {"price": best_ask, "notional": max_ask_notional}
        )

        return {
            "bid_support": best_bid,
            "ask_resistance": best_ask,
            "bid_depth_1pct": bid_depth_1pct,
            "ask_depth_1pct": ask_depth_1pct,
            "bid_persistent": bid_persistent,
            "ask_persistent": ask_persistent
        }
    except Exception as e:
        logger.warning(f"Order book analysis failed for {symbol}: {e}")
        return {
            "bid_support": current_price,
            "ask_resistance": current_price,
            "bid_depth_1pct": 0,
            "ask_depth_1pct": 0,
            "bid_persistent": False,
            "ask_persistent": False
        }

# --- PLAIN-ENGLISH CONFLUENCE ENGINE ---
def evaluate_signals(d4, d1, ob):
    buy_score, exit_score = 0, 0
    buy_factors, exit_factors = [], []
    p = d4["price"]

    # 1. STRUCTURAL CONTEXT (Max 20 Points)
    if p - d4["structural_low"] <= 1.2 * d4["atr"]:
        buy_score += 10
        buy_factors.append("Price has dropped to a major 4H historical floor.")
    if d4["ema200_ext"] < -15.0:
        buy_score += 10
        buy_factors.append("Price is unusually far below its average (heavy discount).")

    if d4["structural_high"] - p <= 1.2 * d4["atr"]:
        exit_score += 10
        exit_factors.append("Price has rallied into a major 4H historical ceiling.")
    if d4["ema200_ext"] > 25.0:
        exit_score += 10
        exit_factors.append("Price is stretched far above its normal average (overheated).")

    # 2. MOMENTUM (Max 25 Points)
    if d4["rsi"] < 32:
        buy_score += 10
        buy_factors.append("4H sellers are completely exhausted (Deeply Oversold).")
    elif d4["rsi"] < 40:
        buy_score += 5
        buy_factors.append("4H selling pressure is fading.")
    if d4["bullish_div"]:
        buy_score += 5
        buy_factors.append("4H buying momentum is shifting upward despite price dropping.")
    if d4["macd_bullish_div"]:
        buy_score += 5
        buy_factors.append("4H MACD shows downside pressure is dying out.")
    if d4["hist_slope_up"]:
        buy_score += 5
        buy_factors.append("The speed of the 4H drop is slowing down.")

    if d4["rsi"] > 70:
        exit_score += 10
        exit_factors.append("4H buyers are completely exhausted (Overbought).")
    elif d4["rsi"] > 62:
        exit_score += 5
        exit_factors.append("The 4H rally is starting to look overheated.")
    if d4["bearish_div"]:
        exit_score += 5
        exit_factors.append("4H price pushed higher, but buying strength is fading.")
    if d4["macd_bearish_div"]:
        exit_score += 5
        exit_factors.append("4H upward momentum is running out of steam.")
    if d4["hist_slope_down"]:
        exit_score += 5
        exit_factors.append("The speed of the 4H rally is slowing down.")

    # 3. VOLUME & REJECTION (Max 20 Points)
    if d4["vol_ratio"] >= 1.6:
        buy_score += 10
        buy_factors.append("Massive 4H panic selling occurred, but buyers absorbed it.")
        if d4["structural_high"] - p <= 1.5 * d4["atr"] or p >= d4["structural_high"] * 0.95:
            exit_score += 10
            exit_factors.append("Massive volume spike at the top (heavy distribution).")

    if d4["lower_wick"] >= 0.35:
        buy_score += 10
        buy_factors.append("4H price dipped hard, but buyers immediately forced it back up.")
    if d4["upper_wick"] >= 0.35:
        exit_score += 10
        exit_factors.append("4H price tried to push higher, but sellers aggressively rejected it.")

    # 4. SPOOF-RESISTANT LIQUIDITY (Max 20 Points)
    if ob["bid_depth_1pct"] > ob["ask_depth_1pct"] * 1.5:
        buy_score += 10
        buy_factors.append("The order book has significantly more buyers than sellers right now.")
    if ob["bid_persistent"]:
        buy_score += 10
        buy_factors.append("A massive, verified 'Buy Wall' has been sitting patiently without moving.")

    if ob["ask_depth_1pct"] > ob["bid_depth_1pct"] * 1.5:
        exit_score += 10
        exit_factors.append("The order book has significantly more sellers than buyers right now.")
    if ob["ask_persistent"]:
        exit_score += 10
        exit_factors.append("A massive, verified 'Sell Wall' is blocking the price from going higher.")

    # 5. 1D MACRO CONTEXT (Max 15 Points)
    if d1["price"] - d1["structural_low"] <= 1.5 * d1["atr"]:
        buy_score += 10
        buy_factors.append("The daily chart confirms we are near a major cycle bottom.")
    if d1["rsi"] < 40 or d1["bullish_div"]:
        buy_score += 5
        buy_factors.append("The daily chart shows sellers are out of strength.")

    if d1["structural_high"] - d1["price"] <= 1.5 * d1["atr"]:
        exit_score += 10
        exit_factors.append("The daily chart confirms we are at a major cycle top.")
    if d1["rsi"] > 65 or d1["bearish_div"]:
        exit_score += 5
        exit_factors.append("The daily chart shows the rally is exhausted.")

    buy_score = min(buy_score, 100)
    exit_score = min(exit_score, 100)

    buy_sig = "CONFIRMED_BUY" if buy_score >= 65 and (d4["hist_slope_up"] or d4["bullish_div"] or d4["macd_bullish_div"] or d4["lower_wick"] >= 0.35) else ("EARLY_ACCUM" if buy_score >= 45 else None)
    exit_sig = "CONFIRMED_EXIT" if exit_score >= 65 and (d4["hist_slope_down"] or d4["bearish_div"] or d4["macd_bearish_div"] or d4["upper_wick"] >= 0.35) else ("APPROACHING_TOP" if exit_score >= 45 else None)

    return buy_sig, buy_factors, exit_sig, exit_factors

# --- DYNAMIC MOVER DISCOVERY ---
def get_dynamic_movers(top_n=3):
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"
    try:
        res = HTTP.get(url, timeout=10)
        res.raise_for_status()
        tickers = res.json()
        if not isinstance(tickers, list):
            return [], []
            
        l1s = sorted([t for t in tickers if t.get("symbol") in L1_L2_UNIVERSE and t.get("symbol") not in CORE_WATCHLIST], key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        ais = sorted([t for t in tickers if t.get("symbol") in AI_UNIVERSE and t.get("symbol") not in CORE_WATCHLIST], key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        return [t["symbol"] for t in l1s[:top_n]], [t["symbol"] for t in ais[:top_n]]
    except Exception as e:
        logger.error(f"Error fetching dynamic movers: {e}")
        return [], []

# --- MAIN WORKFLOW CONTROLLER ---
def check_market():
    logger.info("Initializing multi-sector Spot Cycle Scanner...")

    top_l1, top_ai = get_dynamic_movers(top_n=3)
    full_watchlist = list(dict.fromkeys(CORE_WATCHLIST + top_l1 + top_ai))

    alerts_fired = 0
    manual_summary = "📊 *[MANUAL SCAN DIAGNOSTIC]* 📊\n_Scanner ran successfully. Current market status:_\n\n"

    for symbol in full_watchlist:
        coin_name = symbol.replace("USDT", "")

        try:
            d4 = fetch_candle_data(symbol, "4h")
            d1 = fetch_candle_data(symbol, "1d")
            ob = analyze_liquidity(symbol, d4["price"], d4["atr"])

            buy_sig, buy_factors, exit_sig, exit_factors = evaluate_signals(d4, d1, ob)

            p_str = format_price(d4["price"])
            floor_str = format_price(ob["bid_support"])
            ceil_str = format_price(ob["ask_resistance"])

            # 1D Macro Context Block (Included in Every Alert)
            d1_trend = "Bearish / Downtrend" if d1["ema200_ext"] < 0 else "Bullish / Uptrend"
            if d1["price"] - d1["structural_low"] <= 1.5 * d1["atr"]:
                d1_state = "At Major Cycle Floor (Strong Support)"
            elif d1["structural_high"] - d1["price"] <= 1.5 * d1["atr"]:
                d1_state = "At Major Cycle Peak (Strong Resistance)"
            elif d1["rsi"] < 35:
                d1_state = "Daily RSI Oversold (Selling Exhausted)"
            elif d1["rsi"] > 65:
                d1_state = "Daily RSI Overbought (Rally Overheated)"
            else:
                d1_state = f"{d1_trend} (Consolidating Mid-Range)"

            d1_floor_str = format_price(d1["structural_low"])
            d1_peak_str = format_price(d1["structural_high"])

            d1_info_str = (
                f"• 🌍 *1D Macro Context:* {d1_state}\n"
                f"  └─ 1D RSI: *{d1['rsi']:.1f}* | 200D Cycle Floor: *${d1_floor_str}* | 200D Peak: *${d1_peak_str}*"
            )

            # Human-readable execution sizing
            buy_depth_str = f"Safe Instant Buy Size: Up to ${ob['ask_depth_1pct']:,.0f} before price moves 1%"
            exit_depth_str = f"Safe Instant Sell Size: Up to ${ob['bid_depth_1pct']:,.0f} before price drops 1%"

            # Append to manual diagnostic report
            status = "⚪ Neutral"
            if buy_sig == "CONFIRMED_BUY":
                status = "🟢 Confirmed Reversal"
            elif buy_sig == "EARLY_ACCUM":
                status = "🟡 Setting up for a Buy"
            elif exit_sig == "CONFIRMED_EXIT":
                status = "🔴 Confirmed Top"
            elif exit_sig == "APPROACHING_TOP":
                status = "🟠 Overheated / Take Profit"

            wall_display = floor_str if buy_sig else (ceil_str if exit_sig else "--")
            manual_summary += f"• *{coin_name}*: ${p_str} | Status: {status} | Key Wall: ${wall_display}\n"

            # Dispatch Buy Alert (bypasses cooldown if triggered manually)
            if buy_sig and (RUN_MODE != "schedule" or not check_alert_cooldown(symbol, buy_sig, d4["price"], d4["atr"])):
                alerts_fired += 1
                tag = "🟢 CONFIRMED BOTTOM REVERSAL" if buy_sig == "CONFIRMED_BUY" else "🟡 EARLY BOTTOM WARNING"
                
                # Context-aware guidance based on 1D trend
                if "Bearish" in d1_trend and buy_sig == "EARLY_ACCUM":
                    exec_note = (
                        f"Big money is stepping in on 4H. However, the daily chart is still in a downtrend. "
                        f"Keep allocation small (25-30%) and place a Spot Limit Buy near support at **${floor_str}**. "
                        f"If broken, be prepared for price to retest the 200D cycle floor at **${d1_floor_str}**."
                    )
                else:
                    exec_note = (
                        f"Solid accumulation detected. Do NOT market buy. "
                        f"Consider placing a Spot Limit Buy near support at **${floor_str}**."
                    )

                msg = (f"{tag} : {coin_name}\n\n"
                       f"• *Current Price:* ${p_str}\n"
                       f"• 🛡️ *Whale Buy Wall (Support):* ${floor_str}\n"
                       f"• 💧 *{buy_depth_str}*\n"
                       f"{d1_info_str}\n\n"
                       f"*Why the bot flagged this:*\n• " + "\n• ".join(buy_factors) + "\n\n"
                       f"📍 *What to do:* {exec_note}")
                send_telegram(msg)
                record_alert(symbol, buy_sig, d4["price"])

            # Dispatch Exit Alert (bypasses cooldown if triggered manually)
            if exit_sig and (RUN_MODE != "schedule" or not check_alert_cooldown(symbol, exit_sig, d4["price"], d4["atr"])):
                alerts_fired += 1
                tag = "🔴 CONFIRMED TOP EXHAUSTION" if exit_sig == "CONFIRMED_EXIT" else "🟠 RALLY OVERHEATING"
                msg = (f"{tag} : {coin_name}\n\n"
                       f"• *Current Price:* ${p_str}\n"
                       f"• 🎯 *Whale Sell Wall (Resistance):* ${ceil_str}\n"
                       f"• 💧 *{exit_depth_str}*\n"
                       f"{d1_info_str}\n\n"
                       f"*Why the bot flagged this:*\n• " + "\n• ".join(exit_factors) + "\n\n"
                       f"📍 *What to do:* The rally is running out of steam. Consider taking spot profits into USDT near current prices. Do not chase or buy here.")
                send_telegram(msg)
                record_alert(symbol, exit_sig, d4["price"])

            time.sleep(1.2)

        except Exception as e:
            logger.error(f"Failed analysis for {symbol}: {e}")
            continue

    # Dispatch manual diagnostic summary when triggered via "Run workflow"
    if RUN_MODE != "schedule":
        manual_summary += f"\n──────────────\n✅ *Scan Complete.* {len(full_watchlist)} coins checked. {alerts_fired} active signal(s) triggered."
        send_telegram(manual_summary)

if __name__ == "__main__":
    check_market()

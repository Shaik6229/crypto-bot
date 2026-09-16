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

# --- VETTED ASSET UNIVERSES (Top-Ranked, Shariah-Audited, No Riba/Memes) ---
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

# Vetted Decentralized AI / Compute Infrastructure (ROSE removed to avoid overlap)
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
    """Formats prices dynamically so low-priced assets retain precision without visual clutter."""
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

# --- STATE PERSISTENCE (Alert Deduplication & Size-Aware Liquidity) ---
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"State file load error: {e}")
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.warning(f"State file save error: {e}")

STATE = load_state()

def check_alert_cooldown(symbol, signal_type, current_price, atr):
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

# --- TELEGRAM BROADCASTER WITH RETRIES, 429 HANDLING & SAFE CHUNKING ---
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
                logger.warning(f"Telegram 429 rate limit hit. Sleeping {retry_after}s...")
                time.sleep(retry_after)
                continue
                
            # If Markdown parsing failed (400), resend as plain text fallback
            if res.status_code == 400 and "can't parse entities" in res.text.lower():
                logger.warning("Telegram entity parsing failed. Retrying in plain text...")
                HTTP.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=12)
                return

            res.raise_for_status()
            return
        except requests.RequestException as e:
            logger.warning(f"Telegram dispatch attempt {attempt} failed: {e}")
            time.sleep(1.5 * attempt)
            
    logger.error("Failed to deliver Telegram alert after 3 attempts.")

def send_telegram(msg):
    """Splits oversized messages cleanly along paragraph/line breaks to avoid truncated alerts."""
    if not msg:
        return

    max_len = 3800
    if len(msg) <= max_len:
        _send_single_telegram_chunk(msg)
        return

    # Split into clean paragraphs
    paragraphs = msg.split("\n\n")
    current_chunk = ""
    
    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 <= max_len:
            current_chunk += (para + "\n\n")
        else:
            if current_chunk.strip():
                _send_single_telegram_chunk(current_chunk.strip())
                time.sleep(1.0)
            # If single paragraph exceeds max_len, split by line
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

# --- 1:1 ALIGNED MATHEMATICAL ENGINES ---
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
    """Wilder's RMA smoothing matching standard TradingView calculations."""
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

# --- MARKET DATA & INDEX-ANCHORED ANATOMY ---
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
    macd_line, sig_line, macd_hist = calculate_macd(closes)
    ema200 = calculate_ema(closes, 200)
    atr = calculate_atr(highs, lows, closes)

    c_close, c_low, c_high = closes[closed_idx], lows[closed_idx], highs[closed_idx]
    c_rsi, c_hist, c_atr = rsi_series[closed_idx], macd_hist[closed_idx], atr[closed_idx]
    prev_hist = macd_hist[closed_idx - 1]

    # 200-Candle Extremes
    prior_lows, prior_highs = lows[:closed_idx], highs[:closed_idx]
    structural_low = min(prior_lows) if prior_lows else c_low
    structural_high = max(prior_highs) if prior_highs else c_high
    struct_low_idx = prior_lows.index(structural_low) if prior_lows else 0
    struct_high_idx = prior_highs.index(structural_high) if prior_highs else 0

    # Confirmed Local Swing Pivots (Index, Price)
    local_swings_low = [(i, lows[i]) for i in range(5, closed_idx - 5) if lows[i] == min(lows[i - 5:i + 6])]
    local_swings_high = [(i, highs[i]) for i in range(5, closed_idx - 5) if highs[i] == max(highs[i - 5:i + 6])]
    recent_swing_low_idx, recent_swing_low = local_swings_low[-1] if local_swings_low else (struct_low_idx, structural_low)
    recent_swing_high_idx, recent_swing_high = local_swings_high[-1] if local_swings_high else (struct_high_idx, structural_high)

    # Momentum Slopes & True Divergences (Index Aligned)
    hist_slope_up = c_hist > prev_hist
    hist_slope_down = c_hist < prev_hist

    bullish_div = c_low <= recent_swing_low * 1.02 and c_rsi > rsi_series[recent_swing_low_idx]
    macd_bullish_div = c_low <= recent_swing_low * 1.02 and c_hist > macd_hist[recent_swing_low_idx]

    bearish_div = c_high >= recent_swing_high * 0.98 and c_rsi < rsi_series[recent_swing_high_idx]
    macd_bearish_div = c_high >= recent_swing_high * 0.98 and c_hist < macd_hist[recent_swing_high_idx]

    # Robust Volume Median
    recent_vols = volumes[max(0, closed_idx - 20):closed_idx]
    vol_median = sorted(recent_vols)[len(recent_vols) // 2] if recent_vols else 1.0
    vol_ratio = volumes[closed_idx] / vol_median

    # Wicks
    candle_range = c_high - c_low
    lower_wick = (min(opens[closed_idx], c_close) - c_low) / candle_range if candle_range > 0 else 0
    upper_wick = (c_high - max(opens[closed_idx], c_close)) / candle_range if candle_range > 0 else 0

    ema200_ext = ((c_close - ema200[closed_idx]) / ema200[closed_idx]) * 100

    return {
        "price": c_close,
        "structural_low": structural_low,
        "structural_high": structural_high,
        "rsi": c_rsi,
        "hist_slope_up": hist_slope_up,
        "hist_slope_down": hist_slope_down,
        "bullish_div": bullish_div,
        "macd_bullish_div": macd_bullish_div,
        "bearish_div": bearish_div,
        "macd_bearish_div": macd_bearish_div,
        "vol_ratio": vol_ratio,
        "lower_wick": lower_wick,
        "upper_wick": upper_wick,
        "ema200_ext": ema200_ext,
        "atr": c_atr
    }

# --- NOTIONAL & SIZE-AWARE LIQUIDITY ---
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

        # Size & Price Persistence Check
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

# --- CATEGORIZED CONFLUENCE ENGINE (Max 100 Points) ---
def evaluate_signals(d4, d1, ob):
    buy_score, exit_score = 0, 0
    buy_factors, exit_factors = [], []
    p = d4["price"]

    # 1. STRUCTURAL CONTEXT (Max 20 Points)
    if p - d4["structural_low"] <= 1.2 * d4["atr"]:
        buy_score += 10
        buy_factors.append("🏗️ Near Macro Structural Low")
    if d4["ema200_ext"] < -15.0:
        buy_score += 10
        buy_factors.append(f"🏗️ Extended Below EMA200 ({d4['ema200_ext']:+.1f}%)")

    if d4["structural_high"] - p <= 1.2 * d4["atr"]:
        exit_score += 10
        exit_factors.append("🏗️ Testing Macro Structural High")
    if d4["ema200_ext"] > 25.0:
        exit_score += 10
        exit_factors.append(f"🏗️ Extended Above EMA200 ({d4['ema200_ext']:+.1f}%)")

    # 2. MOMENTUM (Max 25 Points)
    if d4["rsi"] < 32:
        buy_score += 10
        buy_factors.append(f"⚡ RSI Deeply Oversold ({d4['rsi']:.1f})")
    elif d4["rsi"] < 40:
        buy_score += 5
        buy_factors.append(f"⚡ RSI Near Oversold ({d4['rsi']:.1f})")
    if d4["bullish_div"]:
        buy_score += 5
        buy_factors.append("⚡ Confirmed RSI Bullish Divergence")
    if d4["macd_bullish_div"]:
        buy_score += 5
        buy_factors.append("⚡ MACD Hist Bullish Divergence")
    if d4["hist_slope_up"]:
        buy_score += 5
        buy_factors.append("⚡ MACD Downside Momentum Weakening")

    if d4["rsi"] > 70:
        exit_score += 10
        exit_factors.append(f"⚡ RSI Exhaustion ({d4['rsi']:.1f})")
    elif d4["rsi"] > 62:
        exit_score += 5
        exit_factors.append(f"⚡ RSI Elevated ({d4['rsi']:.1f})")
    if d4["bearish_div"]:
        exit_score += 5
        exit_factors.append("⚡ Confirmed RSI Bearish Divergence")
    if d4["macd_bearish_div"]:
        exit_score += 5
        exit_factors.append("⚡ MACD Hist Bearish Divergence")
    if d4["hist_slope_down"]:
        exit_score += 5
        exit_factors.append("⚡ MACD Upside Momentum Weakening")

    # 3. VOLUME & CANDLE REJECTION (Max 20 Points)
    if d4["vol_ratio"] >= 1.6:
        buy_score += 10
        buy_factors.append(f"📊 Capitulation Volume ({d4['vol_ratio']:.1f}x Median)")
        # Structural proximity check for volume blow-off
        if d4["structural_high"] - p <= 1.5 * d4["atr"] or p >= d4["structural_high"] * 0.95:
            exit_score += 10
            exit_factors.append(f"📊 Blow-off/Distribution Volume ({d4['vol_ratio']:.1f}x Median)")

    if d4["lower_wick"] >= 0.35:
        buy_score += 10
        buy_factors.append(f"📊 Lower Wick Absorption ({d4['lower_wick']*100:.0f}%)")
    if d4["upper_wick"] >= 0.35:
        exit_score += 10
        exit_factors.append(f"📊 Upper Wick Rejection ({d4['upper_wick']*100:.0f}%)")

    # 4. SPOOF-RESISTANT LIQUIDITY (Max 20 Points)
    if ob["bid_depth_1pct"] > ob["ask_depth_1pct"] * 1.5:
        buy_score += 10
        buy_factors.append("💧 Strong Bid Depth Skew")
    if ob["bid_persistent"]:
        buy_score += 10
        buy_factors.append("💧 Persistent Clustered Bid Support (Size & Price Verified)")

    if ob["ask_depth_1pct"] > ob["bid_depth_1pct"] * 1.5:
        exit_score += 10
        exit_factors.append("💧 Strong Ask Resistance Skew")
    if ob["ask_persistent"]:
        exit_score += 10
        exit_factors.append("💧 Persistent Clustered Ask Wall (Size & Price Verified)")

    # 5. 1D HIGHER TIMEFRAME CONTEXT (Max 15 Points)
    if d1["price"] - d1["structural_low"] <= 1.5 * d1["atr"]:
        buy_score += 10
        buy_factors.append("🌍 1D Context: Near Macro Bottom")
    if d1["rsi"] < 40 or d1["bullish_div"]:
        buy_score += 5
        buy_factors.append("🌍 1D Context: RSI/Div Confluence")

    if d1["structural_high"] - d1["price"] <= 1.5 * d1["atr"]:
        exit_score += 10
        exit_factors.append("🌍 1D Context: Near Macro Peak")
    if d1["rsi"] > 65 or d1["bearish_div"]:
        exit_score += 5
        exit_factors.append("🌍 1D Context: RSI/Div Exhaustion")

    # Capping and Thresholds
    buy_score = min(buy_score, 100)
    exit_score = min(exit_score, 100)

    buy_sig = "CONFIRMED_BUY" if buy_score >= 65 and (d4["hist_slope_up"] or d4["bullish_div"] or d4["macd_bullish_div"] or d4["lower_wick"] >= 0.35) else ("EARLY_ACCUM" if buy_score >= 45 else None)
    exit_sig = "CONFIRMED_EXIT" if exit_score >= 65 and (d4["hist_slope_down"] or d4["bearish_div"] or d4["macd_bearish_div"] or d4["upper_wick"] >= 0.35) else ("APPROACHING_TOP" if exit_score >= 45 else None)

    return buy_sig, buy_score, buy_factors, exit_sig, exit_score, exit_factors

# --- DYNAMIC MOVER DISCOVERY WITH CLEAN ERROR LOGGING ---
def get_dynamic_movers(top_n=3):
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"
    try:
        res = HTTP.get(url, timeout=10)
        res.raise_for_status()
        tickers = res.json()
        if not isinstance(tickers, list):
            logger.error(f"Unexpected ticker format returned: {type(tickers)}")
            return [], []
            
        l1s = sorted([t for t in tickers if t.get("symbol") in L1_L2_UNIVERSE and t.get("symbol") not in CORE_WATCHLIST], key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        ais = sorted([t for t in tickers if t.get("symbol") in AI_UNIVERSE and t.get("symbol") not in CORE_WATCHLIST], key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        return [t["symbol"] for t in l1s[:top_n]], [t["symbol"] for t in ais[:top_n]]
    except requests.RequestException as e:
        logger.error(f"Network error fetching 24h tickers: {e}")
        return [], []
    except (ValueError, KeyError, TypeError) as e:
        logger.error(f"Data parsing error on 24h tickers: {e}")
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

            buy_sig, buy_score, buy_factors, exit_sig, exit_score, exit_factors = evaluate_signals(d4, d1, ob)

            # Price formatting
            p_str = format_price(d4["price"])
            floor_str = format_price(ob["bid_support"])
            ceil_str = format_price(ob["ask_resistance"])

            # Actionable depth (consumes asks for spot buy, bids for spot exit)
            buy_exec_depth = f"Available Asks (1% Slippage Band): ${ob['ask_depth_1pct']:,.0f}"
            exit_exec_depth = f"Available Bids (1% Slippage Band): ${ob['bid_depth_1pct']:,.0f}"

            # Append to manual summary report
            status = "⚪ Neutral"
            if buy_sig: status = f"🟢 {buy_sig} ({buy_score}/100)"
            elif exit_sig: status = f"🔴 {exit_sig} ({exit_score}/100)"
            
            manual_summary += (f"• *{coin_name}*: ${p_str} | Status: {status} | Floor: ${floor_str}\n")

            if buy_sig and not check_alert_cooldown(symbol, buy_sig, d4["price"], d4["atr"]):
                alerts_fired += 1
                tag = "🟢 CONFIRMED REVERSAL" if buy_sig == "CONFIRMED_BUY" else "🟡 EARLY ACCUMULATION"
                msg = (f"{tag} : {coin_name}\n\n"
                       f"• *Closed Price:* ${p_str} (EMA200: {d4['ema200_ext']:+.1f}%)\n"
                       f"• *Confluence Score:* {buy_score}/100\n"
                       f"• 🛡️ *Cluster Support:* ${floor_str}\n"
                       f"• 💧 *Execution Depth:* {buy_exec_depth}\n\n"
                       f"*Confluence Evidence:*\n• " + "\n• ".join(buy_factors) + "\n\n"
                       f"📍 *Execution:* Downside accumulation detected. Assess ask liquidity for entry sizing.")
                send_telegram(msg)
                record_alert(symbol, buy_sig, d4["price"])

            if exit_sig and not check_alert_cooldown(symbol, exit_sig, d4["price"], d4["atr"]):
                alerts_fired += 1
                tag = "🔴 TRUE EXHAUSTION" if exit_sig == "CONFIRMED_EXIT" else "🟠 APPROACHING TOP"
                msg = (f"{tag} : {coin_name}\n\n"
                       f"• *Closed Price:* ${p_str} (EMA200: {d4['ema200_ext']:+.1f}%)\n"
                       f"• *Confluence Score:* {exit_score}/100\n"
                       f"• 🎯 *Cluster Resistance:* ${ceil_str}\n"
                       f"• 💧 *Execution Depth:* {exit_exec_depth}\n\n"
                       f"*Exhaustion Evidence:*\n• " + "\n• ".join(exit_factors) + "\n\n"
                       f"📍 *Execution:* Peak distribution/exhaustion detected. Assess bid liquidity for exit sizing.")
                send_telegram(msg)
                record_alert(symbol, exit_sig, d4["price"])

            time.sleep(1.2)

        except Exception as e:
            logger.error(f"Failed analysis for {symbol}: {e}")
            continue

    # If triggered manually via GitHub button, send diagnostic summary so you know it ran
    if RUN_MODE != "schedule":
        manual_summary += f"\n──────────────\n✅ *Scan Complete.* {len(full_watchlist)} coins checked. {alerts_fired} active signal(s) triggered."
        send_telegram(manual_summary)

if __name__ == "__main__":
    check_market()

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
RUN_MODE = os.environ.get("BOT_RUN_MODE", os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch"))

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

# --- ADAPTIVE NORMALIZATION SETTINGS ---
# These settings add context without creating hard BUY/SELL blockers.
VOLUME_BASELINE_PERIOD = 50
IGNITION_VOLUME_RATIO_MIN = 1.60
RELIEF_VOLUME_RATIO_MIN = 2.20
IGNITION_VOLUME_PERCENTILE = 85.0
RELIEF_VOLUME_PERCENTILE = 95.0
LIQUIDITY_GOOD_SPREAD_PCT = 0.10
LIQUIDITY_WIDE_SPREAD_PCT = 0.50

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

# --- TELEGRAM BROADCASTER ---
def _send_single_telegram_chunk(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    for attempt in range(1, 4):
        try:
            res = HTTP.post(
                url,
                data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
                timeout=12,
            )
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
            current_chunk += para + "\n\n"
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
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
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
        idx = len(closes) - 2

        rsi_series = calculate_wilder_rsi(closes)
        ema50 = calculate_ema(closes, 50)
        ema200 = calculate_ema(closes, 200)

        c_price = closes[idx]
        c_rsi = rsi_series[idx]
        c_ema50 = ema50[idx]
        c_ema200 = ema200[idx]

        bearish_points = 0
        if c_price < c_ema50:
            bearish_points += 1
        if c_ema50 < c_ema200:
            bearish_points += 1
        if c_rsi < 45:
            bearish_points += 1

        return {
            "price": c_price,
            "rsi": c_rsi,
            "ema50": c_ema50,
            "ema200": c_ema200,
            "is_bearish": bearish_points >= 2,
        }
    except Exception as e:
        logger.warning(f"Could not fetch 1D context for {symbol}: {e}")
        return {"price": 0, "rsi": 50.0, "ema50": 0, "ema200": 0, "is_bearish": False}

# --- RECENT RESISTANCE MAP FOR TARGETS ONLY ---
def get_recent_resistance_levels(highs, closes, idx, atr):
    """Build a target-only resistance map without lookahead."""
    start = max(0, idx - 120)
    swing_highs = []

    # A swing high needs five completed candles on each side.
    for i in range(max(5, start), idx - 5):
        window = highs[i - 5:i + 6]
        if highs[i] == max(window):
            swing_highs.append((i, highs[i]))

    consolidation_high = max(highs[max(0, idx - 12):idx]) if idx > 0 else highs[idx]
    return swing_highs, consolidation_high


def select_resistance_targets(c4, live_price):
    """
    Select TP1/TP2/TP3 from meaningful resistance above live price.

    The first three meaningful resistance clusters are preferred. ATR-based
    fallbacks are used only when historical resistance is insufficient.
    All targets are spot-profit-taking targets, not guaranteed prices.
    """
    p = live_price
    atr = max(c4["atr"], p * 0.001)
    candidates = []

    if c4["ema50"] > p * 1.003:
        candidates.append({"price": c4["ema50"], "score": 3.0, "name": "4H 50-EMA"})

    if c4["ema200"] > p * 1.003:
        candidates.append({"price": c4["ema200"], "score": 3.0, "name": "4H 200-EMA"})

    if c4["consolidation_high"] > p * 1.003:
        candidates.append({"price": c4["consolidation_high"], "score": 4.0, "name": "Recent consolidation high"})

    for idx, price in c4["recent_swing_highs"]:
        if price <= p * 1.003:
            continue
        age = c4["closed_idx"] - idx
        recency_bonus = 2.0 if age <= 24 else 1.5 if age <= 48 else 1.0 if age <= 72 else 0.5
        candidates.append({
            "price": price,
            "score": 5.0 + recency_bonus,
            "name": f"Confirmed swing high ({age} candles ago)",
        })

    # Cluster nearby resistance levels so several references reinforce the
    # same zone instead of producing multiple nearly-identical targets.
    candidates.sort(key=lambda x: x["price"])
    clusters = []
    for candidate in candidates:
        tolerance = max(0.30 * atr, p * 0.003)
        if not clusters or candidate["price"] - clusters[-1]["price"] > tolerance:
            clusters.append({
                "price": candidate["price"],
                "score": candidate["score"],
                "members": [candidate],
            })
        else:
            cluster = clusters[-1]
            cluster["members"].append(candidate)
            cluster["price"] = sum(x["price"] for x in cluster["members"]) / len(cluster["members"])
            cluster["score"] += candidate["score"]

    for cluster in clusters:
        count = len(cluster["members"])
        if count >= 2:
            cluster["score"] += 2
        if count >= 3:
            cluster["score"] += 2

    meaningful = [
        c for c in clusters
        if (c["price"] - p) >= 0.5 * atr or c["score"] >= 8
    ]
    meaningful.sort(key=lambda x: x["price"])

    def cluster_name(cluster):
        return ", ".join(sorted(set(x["name"] for x in cluster["members"])))

    if not meaningful:
        return (
            p + atr, p + 2.5 * atr, p + 4.0 * atr,
            "1 ATR fallback", "2.5 ATR fallback", "4 ATR fallback"
        )

    tp1_cluster = meaningful[0]
    tp1 = tp1_cluster["price"]
    tp1_name = cluster_name(tp1_cluster)

    min_gap = max(0.25 * atr, p * 0.0025)
    tp2_cluster = next((c for c in meaningful[1:] if c["price"] >= tp1 + min_gap), None)

    if tp2_cluster is None:
        tp2 = p + 2.5 * atr
        tp2_name = "2.5 ATR extension"
        if tp2 <= tp1:
            tp2 = tp1 + 0.75 * atr
            tp2_name = "0.75 ATR beyond TP1"
    else:
        tp2 = tp2_cluster["price"]
        tp2_name = cluster_name(tp2_cluster)

    tp3_cluster = next(
        (c for c in meaningful if c["price"] >= tp2 + min_gap),
        None,
    )

    if tp3_cluster is None:
        tp3 = p + 4.0 * atr
        tp3_name = "4 ATR extension"
        if tp3 <= tp2:
            tp3 = tp2 + 0.75 * atr
            tp3_name = "0.75 ATR beyond TP2"
    else:
        tp3 = tp3_cluster["price"]
        tp3_name = cluster_name(tp3_cluster)

    # Prevent targets from becoming unrealistically distant. This is a cap,
    # not a directional filter; it only keeps the target engine practical.
    max_target = p + 5.0 * atr
    if tp2 > max_target:
        tp2 = max_target
        tp2_name = "5 ATR maximum extension"
    if tp3 > max_target:
        tp3 = max_target
        tp3_name = "5 ATR maximum extension"
    if tp3 <= tp2:
        tp3 = min(max_target, tp2 + 0.50 * atr)
        if tp3 <= tp2:
            tp3 = tp2
        tp3_name = "5 ATR maximum / fallback"

    return tp1, tp2, tp3, tp1_name, tp2_name, tp3_name


def select_ignition_targets(c4, live_price):
    return select_resistance_targets(c4, live_price)

# --- ADAPTIVE MARKET CONTEXT HELPERS ---
def percentile_rank(value, series):
    """Return the percentile rank of value within a historical series."""
    if not series:
        return 50.0
    less_equal = sum(1 for x in series if x <= value)
    return 100.0 * less_equal / len(series)


def classify_volume_regime(vol_ratio, vol_percentile):
    if vol_percentile >= 95 or vol_ratio >= 2.5:
        return "exceptional"
    if vol_percentile >= 80 or vol_ratio >= 1.5:
        return "elevated"
    if vol_percentile <= 20 or vol_ratio < 0.75:
        return "quiet"
    return "normal"


def classify_compression(candles_below_ema20):
    if candles_below_ema20 >= 20:
        return "extreme compression"
    if candles_below_ema20 >= 15:
        return "deep compression"
    if candles_below_ema20 >= 10:
        return "established compression"
    if candles_below_ema20 >= 6:
        return "developing compression"
    return "limited compression"


def liquidity_label(spread_pct, depth_ratio_pct):
    """Context label only; never a hard alert gate."""
    if spread_pct <= LIQUIDITY_GOOD_SPREAD_PCT and depth_ratio_pct >= 5.0:
        return "strong"
    if spread_pct <= LIQUIDITY_WIDE_SPREAD_PCT and depth_ratio_pct >= 1.0:
        return "healthy"
    if spread_pct > LIQUIDITY_WIDE_SPREAD_PCT or depth_ratio_pct < 0.25:
        return "thin"
    return "mixed"


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

    idx = len(closes) - 2
    rsi_series = calculate_wilder_rsi(closes)
    _, _, macd_hist = calculate_macd(closes)
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    ema200 = calculate_ema(closes, 200)
    atr = calculate_atr(highs, lows, closes)

    c_open, c_close, c_low, c_high = opens[idx], closes[idx], lows[idx], highs[idx]
    c_rsi, c_hist, c_atr = rsi_series[idx], macd_hist[idx], atr[idx]
    prev_hist = macd_hist[idx - 1]
    prev_rsi = rsi_series[idx - 1]
    prev_close = closes[idx - 1]
    prev_open = opens[idx - 1]
    prev_low = lows[idx - 1]
    prev_high = highs[idx - 1]
    prev_ema20 = ema20[idx - 1]

    prior_lows, prior_highs = lows[:idx], highs[:idx]
    struct_low = min(prior_lows) if prior_lows else c_low
    struct_high = max(prior_highs) if prior_highs else c_high
    s_low_idx = prior_lows.index(struct_low) if prior_lows else 0
    s_high_idx = prior_highs.index(struct_high) if prior_highs else 0

    local_lows = [(i, lows[i]) for i in range(5, idx - 5) if lows[i] == min(lows[i - 5:i + 6])]
    local_highs = [(i, highs[i]) for i in range(5, idx - 5) if highs[i] == max(highs[i - 5:i + 6])]
    r_low_idx, r_low = local_lows[-1] if local_lows else (s_low_idx, struct_low)
    r_high_idx, r_high = local_highs[-1] if local_highs else (s_high_idx, struct_high)

    vol_slice = volumes[max(0, idx - VOLUME_BASELINE_PERIOD):idx]
    vol_median = statistics.median(vol_slice) if vol_slice else 1.0
    current_volume = volumes[idx]
    vol_ratio = current_volume / vol_median if vol_median > 0 else 1.0
    vol_percentile = percentile_rank(current_volume, vol_slice)
    volume_regime = classify_volume_regime(vol_ratio, vol_percentile)
    candle_range = c_high - c_low

    candles_below_ema20 = 0
    for i in range(idx - 1, max(0, idx - 25), -1):
        if closes[i] < ema20[i]:
            candles_below_ema20 += 1
        else:
            break

    consolidation_high = max(highs[max(0, idx - 12):idx]) if idx > 0 else c_high
    recent_swing_highs, _ = get_recent_resistance_levels(highs, closes, idx, c_atr)

    lower_wick = (min(c_open, c_close) - c_low) / candle_range if candle_range > 0 else 0
    upper_wick = (c_high - max(c_open, c_close)) / candle_range if candle_range > 0 else 0
    bearish_candle = c_close < c_open
    bullish_candle = c_close > c_open

    # Rejection means the completed candle actually rejected higher prices.
    bearish_rejection = (
        bearish_candle and
        (
            upper_wick >= 0.25 or
            c_close < prev_close
        )
    )
    strong_bearish_rejection = (
        bearish_candle and
        upper_wick >= 0.35 and
        c_close < prev_close
    )

    rsi_turning_down = c_rsi < prev_rsi
    macd_hist_weakening = c_hist < prev_hist
    below_ema20 = c_close < ema20[idx]
    crossed_below_ema20 = below_ema20 and prev_close >= prev_ema20

    return {
        "price": c_close,
        "open": c_open,
        "low": c_low,
        "high": c_high,
        "prev_price": prev_close,
        "prev_open": prev_open,
        "prev_low": prev_low,
        "prev_high": prev_high,
        "structural_low": struct_low,
        "structural_high": struct_high,
        "rsi": c_rsi,
        "prev_rsi": prev_rsi,
        "hist_slope_up": c_hist > prev_hist,
        "hist_slope_down": c_hist < prev_hist,
        "macd_hist_crossed_positive": c_hist > 0 and prev_hist <= 0,
        "macd_hist_weakening": macd_hist_weakening,
        "rsi_turning_down": rsi_turning_down,
        "bullish_div": c_low <= r_low * 1.015 and c_rsi > rsi_series[r_low_idx],
        "bearish_div": c_high >= r_high * 0.985 and c_rsi < rsi_series[r_high_idx],
        "vol_ratio": vol_ratio,
        "vol_percentile": vol_percentile,
        "volume_regime": volume_regime,
        "compression_regime": classify_compression(candles_below_ema20),
        "avg_quote_volume_4h": statistics.median(
            [closes[i] * volumes[i] for i in range(max(0, idx - 20), idx)]
        ) if idx > 0 else 0.0,
        "lower_wick": lower_wick,
        "upper_wick": upper_wick,
        "bullish_candle": bullish_candle,
        "bearish_candle": bearish_candle,
        "bearish_rejection": bearish_rejection,
        "strong_bearish_rejection": strong_bearish_rejection,
        "ema20": ema20[idx],
        "prev_ema20": prev_ema20,
        "ema50": ema50[idx],
        "ema200": ema200[idx],
        "ema200_ext": ((c_close - ema200[idx]) / ema200[idx]) * 100,
        "atr": c_atr,
        "candles_below_ema20": candles_below_ema20,
        "consolidation_high": consolidation_high,
        "recent_swing_highs": recent_swing_highs,
        "closed_idx": idx,
        "below_ema20": below_ema20,
        "crossed_below_ema20": crossed_below_ema20,
    }

# --- LIVE BINANCE ORDER BOOK DEPTH ---
def fetch_order_book(symbol, current_price, reference_quote_volume=0.0):
    try:
        url = f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=100"
        res = HTTP.get(url, timeout=6)
        res.raise_for_status()
        raw = res.json()
        bids = [[float(p), float(q)] for p, q in raw.get("bids", [])]
        asks = [[float(p), float(q)] for p, q in raw.get("asks", [])]

        if not bids or not asks:
            return {
                "bid_depth_1pct": 0,
                "ask_depth_1pct": 0,
                "bid_wall_price": current_price,
                "ask_wall_price": current_price,
                "spread_pct": 0.0,
                "depth_to_4h_volume_pct": 0.0,
                "liquidity_label": "unknown",
            }

        bids_1pct_levels = [x for x in bids if x[0] >= current_price * 0.99]
        asks_1pct_levels = [x for x in asks if x[0] <= current_price * 1.01]

        bids_1pct = sum(p * q for p, q in bids_1pct_levels)
        asks_1pct = sum(p * q for p, q in asks_1pct_levels)

        largest_bid = max(bids_1pct_levels, key=lambda x: x[0] * x[1]) if bids_1pct_levels else [current_price, 0]
        largest_ask = max(asks_1pct_levels, key=lambda x: x[0] * x[1]) if asks_1pct_levels else [current_price, 0]

        best_bid = bids[0][0]
        best_ask = asks[0][0]
        spread_pct = ((best_ask - best_bid) / current_price) * 100 if current_price > 0 else 0.0
        total_depth = bids_1pct + asks_1pct
        depth_to_4h_volume_pct = (total_depth / reference_quote_volume) * 100 if reference_quote_volume > 0 else 0.0

        return {
            "bid_depth_1pct": bids_1pct,
            "ask_depth_1pct": asks_1pct,
            "bid_wall_price": largest_bid[0],
            "ask_wall_price": largest_ask[0],
            "spread_pct": spread_pct,
            "depth_to_4h_volume_pct": depth_to_4h_volume_pct,
            "liquidity_label": liquidity_label(spread_pct, depth_to_4h_volume_pct),
        }
    except Exception as e:
        logger.warning(f"Could not fetch order book for {symbol}: {e}")
        return {
            "bid_depth_1pct": 0,
            "ask_depth_1pct": 0,
            "bid_wall_price": current_price,
            "ask_wall_price": current_price,
            "spread_pct": 0.0,
            "depth_to_4h_volume_pct": 0.0,
            "liquidity_label": "unknown",
        }

# --- DIRECTIONAL PREDICTION ENGINE (MANUAL DIAGNOSTIC ONLY) ---
def analyze_market_direction(c4, ob, d1):
    p = c4["price"]
    up_score = 0
    down_score = 0
    drivers = []

    if p > c4["ema20"]:
        up_score += 2
        drivers.append("holding above 20-EMA")
    else:
        down_score += 2
        drivers.append("below 20-EMA")

    if p > c4["ema50"]:
        up_score += 1
    else:
        down_score += 1

    if c4["hist_slope_up"]:
        up_score += 2
        drivers.append("MACD momentum improving")
    elif c4["hist_slope_down"]:
        down_score += 2
        drivers.append("MACD momentum fading")

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

    if not d1["is_bearish"]:
        up_score += 1
    else:
        down_score += 1
        drivers.append("1D downtrend drag")

    if ob["bid_depth_1pct"] > 1.2 * ob["ask_depth_1pct"]:
        up_score += 1
    elif ob["ask_depth_1pct"] > 1.2 * ob["bid_depth_1pct"]:
        down_score += 1

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

# --- TOP EXHAUSTION ENGINE ---
def evaluate_top_exhaustion(c4, exit_score):
    """
    Three-stage top process.

    1) RALLY_OVERHEATING: background risk only.
    2) TOP_EXHAUSTION_DEVELOPING: actual momentum/rejection deterioration.
    3) TOP_REVERSAL_CONFIRMED: completed 4H close crosses below EMA20
       plus multiple deterioration confirmations.

    No cooldown, state file, or deduplication is used intentionally.
    """
    exhaustion_background = (
        exit_score >= 45 or
        c4["rsi"] > 70 or
        c4["ema200_ext"] > 25.0 or
        c4["bearish_div"]
    )

    deterioration_signals = [
        c4["rsi_turning_down"],
        c4["macd_hist_weakening"],
        c4["bearish_rejection"],
        c4["bearish_div"],
    ]
    deterioration_count = sum(1 for x in deterioration_signals if x)

    reversal_confirmation = (
        c4["crossed_below_ema20"] and
        c4["rsi_turning_down"] and
        c4["macd_hist_weakening"] and
        c4["bearish_rejection"] and
        (
            exit_score >= 45 or
            c4["bearish_div"] or
            c4["ema200_ext"] > 25.0 or
            c4["rsi"] > 65
        )
    )

    if reversal_confirmation:
        return "TOP_REVERSAL_CONFIRMED"

    if exhaustion_background and deterioration_count >= 2:
        return "TOP_EXHAUSTION_DEVELOPING"

    if exit_score >= 45:
        return "RALLY_OVERHEATING"

    return None

# --- 4H SCORING & SETUP EVALUATION ---
def evaluate_market_condition(c4, ob, d1):
    p = c4["price"]
    ema20 = c4["ema20"]
    ema_stretch_20 = ((p - ema20) / ema20) * 100
    active_setups = []

    # 1. COUNTER-TREND RELIEF SCALP
    if (
        d1["is_bearish"] and
        ema_stretch_20 <= -7.5 and
        c4["rsi"] <= 28.0 and
        (
            c4["vol_ratio"] >= RELIEF_VOLUME_RATIO_MIN or
            c4["vol_percentile"] >= RELIEF_VOLUME_PERCENTILE
        ) and
        ob["bid_depth_1pct"] > 0 and
        ob["ask_depth_1pct"] > 0 and
        ob["bid_depth_1pct"] >= 1.5 * ob["ask_depth_1pct"]
    ):
        tp1 = ema20
        tp2_candidates = [v for v in [c4["ema50"], c4["consolidation_high"], c4["structural_high"]] if v > tp1]
        tp2 = min(tp2_candidates) if tp2_candidates else tp1 * 1.04
        active_setups.append({
            "type": "RELIEF_SCALP",
            "ema_stretch": ema_stretch_20,
            "tp1": tp1,
            "tp2": tp2,
            "stop": c4["low"] * 0.992,
        })

    # 2. ACCUMULATION IGNITION
    if (
        c4["candles_below_ema20"] >= 10 and
        p > ema20 and
        c4["open"] <= ema20 * 1.005 and
        p >= c4["consolidation_high"] * 0.998 and
        (
            c4["vol_ratio"] >= IGNITION_VOLUME_RATIO_MIN or
            c4["vol_percentile"] >= IGNITION_VOLUME_PERCENTILE
        ) and
        c4["bullish_candle"] and
        c4["upper_wick"] <= 0.25 and
        (c4["macd_hist_crossed_positive"] or c4["hist_slope_up"])
    ):
        tp1, tp2, tp3, tp1_name, tp2_name, tp3_name = select_ignition_targets(c4, p)
        active_setups.append({
            "type": "ACCUMULATION_IGNITION",
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "tp1_name": tp1_name,
            "tp2_name": tp2_name,
            "tp3_name": tp3_name,
            "stop": min(c4["low"], p * 0.96),
            "reasons": [
                f"Breakout after {c4['candles_below_ema20']} completed 4H candles below the 20-EMA.",
                f"Strong buying volume: {c4['vol_ratio']:.1f}x the recent median.",
                f"Price reclaimed the recent consolidation high near ${format_price(c4['consolidation_high'])}.",
                "MACD momentum is turning upward.",
                f"Volume regime: {c4['volume_regime']} ({c4['vol_percentile']:.0f}th percentile of its recent 4H volume history).",
                f"Compression regime: {c4['compression_regime']}.",
                f"Liquidity context: {ob['liquidity_label']} (spread {ob['spread_pct']:.3f}%).",
            ],
        })

    # 3. BUY & SELL SCORING — POINT VALUES INTENTIONALLY UNCHANGED
    buy_score, exit_score = 0, 0
    buy_factors, exit_factors = [], []

    if p - c4["structural_low"] <= 1.5 * c4["atr"]:
        buy_score += 15
        buy_factors.append("Price is close to the lowest 4H low in the lookback window.")
    if c4["ema200_ext"] < -15.0:
        buy_score += 10
        buy_factors.append(f"Price is deeply below the 4H 200-EMA ({c4['ema200_ext']:+.1f}%).")
    if c4["rsi"] < 30:
        buy_score += 15
        buy_factors.append(f"Selling pressure is heavily stretched (RSI {c4['rsi']:.1f}).")
    if c4["bullish_div"]:
        buy_score += 15
        buy_factors.append("Bullish divergence is present on the completed 4H candle.")
    if c4["lower_wick"] >= 0.35:
        buy_score += 10
        buy_factors.append("The candle shows strong buying rejection from lower prices.")

    # SELL SCORE — KEEPING THE EXISTING POINT SYSTEM EXACTLY AS REQUESTED
    if c4["structural_high"] - p <= 1.5 * c4["atr"]:
        exit_score += 15
        exit_factors.append("Price is close to the highest 4H high in the lookback window.")
    if c4["ema200_ext"] > 25.0:
        exit_score += 10
        exit_factors.append(f"Price is deeply above the 4H 200-EMA ({c4['ema200_ext']:+.1f}%).")
    if c4["rsi"] > 70:
        exit_score += 15
        exit_factors.append(f"Buying pressure is heavily stretched (RSI {c4['rsi']:.1f}).")
    if c4["bearish_div"]:
        exit_score += 15
        exit_factors.append("Bearish divergence is present on the completed 4H candle.")
    if c4["upper_wick"] >= 0.35:
        exit_score += 10
        exit_factors.append("The candle shows strong rejection from higher prices.")

    if ob["bid_depth_1pct"] > 1.3 * ob["ask_depth_1pct"]:
        buy_score += 10
        buy_factors.append("Visible bids are significantly larger than visible asks.")
    if ob["ask_depth_1pct"] > 1.3 * ob["bid_depth_1pct"]:
        exit_score += 10
        exit_factors.append("Visible asks are significantly larger than visible bids.")

    if d1["is_bearish"]:
        buy_score = max(0, buy_score - 25)

    if buy_score >= 65:
        active_setups.append({"type": "BUY_CONFIRMED", "score": buy_score, "reasons": buy_factors})
    elif buy_score >= 45:
        active_setups.append({"type": "BUY_EARLY", "score": buy_score, "reasons": buy_factors})

    if exit_score >= 65:
        active_setups.append({"type": "SELL_CONFIRMED", "score": exit_score, "reasons": exit_factors})
    elif exit_score >= 45:
        active_setups.append({"type": "SELL_EARLY", "score": exit_score, "reasons": exit_factors})

    # Independent top engine. It does not change SELL scoring.
    top_stage = evaluate_top_exhaustion(c4, exit_score)
    if top_stage:
        active_setups.append({
            "type": top_stage,
            "score": exit_score,
            "reasons": exit_factors,
        })

    return active_setups

# --- DYNAMIC MOVER DISCOVERY ---
def get_dynamic_movers():
    try:
        res = HTTP.get("https://data-api.binance.vision/api/v3/ticker/24hr", timeout=10)
        res.raise_for_status()
        tickers = res.json()
        l1s = sorted(
            [t for t in tickers if t.get("symbol") in L1_L2_UNIVERSE and t.get("symbol") not in CORE_WATCHLIST],
            key=lambda x: float(x.get("quoteVolume", 0)),
            reverse=True,
        )
        ais = sorted(
            [t for t in tickers if t.get("symbol") in AI_UNIVERSE and t.get("symbol") not in CORE_WATCHLIST],
            key=lambda x: float(x.get("quoteVolume", 0)),
            reverse=True,
        )
        return [t["symbol"] for t in l1s[:3]], [t["symbol"] for t in ais[:3]]
    except Exception as e:
        logger.warning(f"Could not discover dynamic movers: {e}")
        return [], []

# --- MAIN CONTROLLER ---
def check_4h_market():
    logger.info(f"Initializing 4H Tactical Scanner | mode={RUN_MODE}")
    top_l1, top_ai = get_dynamic_movers()
    full_watchlist = list(dict.fromkeys(CORE_WATCHLIST + top_l1 + top_ai))
    alerts_fired = 0

    manual_summary = (
        "🧭 *[MANUAL 4H MARKET DIRECTION REPORT]* 🧭\n"
        "_Direction is based on completed 4H candles; live order-book data is only supporting context._\n\n"
    )

    for symbol in full_watchlist:
        coin_name = symbol.replace("USDT", "")
        try:
            c4 = fetch_4h_data(symbol)
            ob = fetch_order_book(symbol, c4["price"], c4["avg_quote_volume_4h"])
            d1 = fetch_1d_context(symbol)

            p_str = format_price(c4["price"])
            support_str = format_price(ob["bid_wall_price"])
            resist_str = format_price(ob["ask_wall_price"])

            if RUN_MODE != "schedule":
                verdict, action_note = analyze_market_direction(c4, ob, d1)
                manual_summary += (
                    f"• *{coin_name}* (${p_str}) : *{verdict}*\n"
                    f"  ↳ {action_note}\n\n"
                )

            setups = evaluate_market_condition(c4, ob, d1)

            for setup in setups:
                stype = setup["type"]
                alerts_fired += 1

                if stype == "RELIEF_SCALP":
                    msg = (
                        f"⚡ *4H SHORT-TERM BOUNCE ALERT* : {coin_name}\n\n"
                        f"• *Entry Region:* ${format_price(c4['low'])} – ${p_str}\n"
                        f"• 🛡️ *Largest Visible Bid Wall:* ${support_str}\n"
                        f"• 📉 *Distance below 4H 20-EMA:* {setup['ema_stretch']:.1f}%\n"
                        f"• ⚡ *4H RSI:* {c4['rsi']:.1f} | *Volume:* {c4['vol_ratio']:.1f}x median\n"
                        f"• 🌍 *1D Context:* 🔴 Bearish\n\n"
                        f"*Why:* Price is unusually stretched below the 20-EMA, sellers are heavily stretched, and buying volume/order-book support is present.\n\n"
                        f"*Tactical Plan:*\n"
                        f"• 🎯 *TP1 (70%):* ${format_price(setup['tp1'])} — 20-EMA retest\n"
                        f"• 🎯 *TP2 (30%):* ${format_price(setup['tp2'])}\n"
                        f"• 🛑 *Invalidation:* 4H close below ${format_price(setup['stop'])}\n\n"
                        f"📍 *Important:* This is a short-term bounce setup, not a claim that the larger downtrend has ended."
                    )

                elif stype == "ACCUMULATION_IGNITION":
                    msg = (
                        f"🚀 *4H ACCUMULATION IGNITION* : {coin_name}\n\n"
                        f"• *Current Price:* ${p_str}\n"
                        f"• 📈 *Ignition Volume:* {c4['vol_ratio']:.1f}x median | {c4['vol_percentile']:.0f}th percentile ({c4['volume_regime']})\n"
                        f"• ⏳ *Suppression:* {c4['candles_below_ema20']} candles ({c4['candles_below_ema20']*4}h) below 20-EMA\n"
                        f"• 🛡️ *Largest Visible Bid Wall:* ${support_str}\n\n"
                        f"*Why the bot flagged this:*\n• " + "\n• ".join(setup["reasons"]) + "\n\n"
                        f"*Tactical Plan:*\n"
                        f"• 🎯 *TP1 (50%):* ${format_price(setup['tp1'])} — {setup['tp1_name']}\n"
                        f"• 🎯 *TP2 (30%):* ${format_price(setup['tp2'])} — {setup['tp2_name']}\n"
                        f"• 🎯 *TP3 (20%):* ${format_price(setup['tp3'])} — {setup['tp3_name']}\n"
                        f"• 🛑 *Invalidation:* 4H close below ${format_price(setup['stop'])}\n\n"
                        f"📍 *Important:* This is a spot continuation/breakout setup. Targets are resistance areas, not guaranteed prices."
                    )

                elif stype in ["BUY_CONFIRMED", "BUY_EARLY"]:
                    header = "🟢 *STRONG BUYING SIGNAL*" if stype == "BUY_CONFIRMED" else "🟡 *EARLY BUYING WARNING*"
                    strength = "Multiple conditions agree." if stype == "BUY_CONFIRMED" else "Some conditions are improving, but confirmation is incomplete."
                    msg = (
                        f"{header} : {coin_name}\n\n"
                        f"• *Current Price:* ${p_str}\n"
                        f"• 🛡️ *Largest Visible Bid Wall:* ${support_str}\n"
                        f"• 💧 *Visible Ask Liquidity Within 1%:* ${ob['ask_depth_1pct']:,.0f}\n"
                        f"• 🌍 *1D RSI:* {d1['rsi']:.1f}\n"
                        f"• 📊 *Score:* {setup['score']}\n"
                        f"• 📈 *Volume Regime:* {c4['volume_regime']} ({c4['vol_percentile']:.0f}th percentile)\n"
                        f"• 💧 *Liquidity:* {ob['liquidity_label']} | Spread {ob['spread_pct']:.3f}%\n\n"
                        f"*Why the bot flagged this:*\n• " + "\n• ".join(setup["reasons"]) + "\n\n"
                        f"📍 *Meaning:* {strength}\n"
                        f"This is a spot-buying signal, not a guarantee that price cannot fall."
                    )

                elif stype in ["SELL_CONFIRMED", "SELL_EARLY"]:
                    # Keep the existing SELL scoring alerts visible, but clearly
                    # separate them from the independent top-reversal stages.
                    header = "🔴 *SELLING PRESSURE ALERT*" if stype == "SELL_CONFIRMED" else "🟠 *RALLY RUNNING HOT*"
                    meaning = (
                        "Several exhaustion conditions are present, but this is still a profit-taking warning, not proof of a reversal."
                        if stype == "SELL_EARLY"
                        else "The existing sell score is strongly elevated. This is a spot profit-taking warning, not a short-entry signal."
                    )
                    msg = (
                        f"{header} : {coin_name}\n\n"
                        f"• *Current Price:* ${p_str}\n"
                        f"• 🎯 *Largest Visible Ask Wall:* ${resist_str}\n"
                        f"• 💧 *Visible Bid Liquidity Within 1%:* ${ob['bid_depth_1pct']:,.0f}\n"
                        f"• ⚡ *4H RSI:* {c4['rsi']:.1f}\n"
                        f"• 📊 *Sell Score:* {setup['score']}\n"
                        f"• 📈 *Volume Regime:* {c4['volume_regime']} ({c4['vol_percentile']:.0f}th percentile)\n"
                        f"• 💧 *Liquidity:* {ob['liquidity_label']} | Spread {ob['spread_pct']:.3f}%\n\n"
                        f"*Why the bot flagged this:*\n• " + "\n• ".join(setup["reasons"]) + "\n\n"
                        f"📍 *Meaning:* {meaning}"
                    )

                elif stype == "RALLY_OVERHEATING":
                    msg = (
                        f"🟠 *RALLY RUNNING HOT* : {coin_name}\n\n"
                        f"• *Current Price:* ${p_str}\n"
                        f"• 🎯 *Visible Ask Wall:* ${resist_str}\n"
                        f"• ⚡ *4H RSI:* {c4['rsi']:.1f}\n"
                        f"• 📈 *Distance above 4H 200-EMA:* {c4['ema200_ext']:+.1f}%\n"
                        f"• 📊 *Sell Score:* {setup['score']}\n\n"
                        f"*Why the bot is warning:*\n"
                        f"• The move is extended enough to deserve caution.\n"
                        f"• This stage does *not* require evidence that momentum has turned down yet.\n\n"
                        f"📍 *Meaning:* This is a WARNING, not an exit signal and not a confirmed reversal. A strong trend can remain overbought and continue higher.\n"
                        f"*For spot holders:* Watch for the next stage before treating this as evidence of an actual reversal."
                    )

                elif stype == "TOP_EXHAUSTION_DEVELOPING":
                    msg = (
                        f"🟡 *TOP EXHAUSTION DEVELOPING* : {coin_name}\n\n"
                        f"• *Current Price:* ${p_str}\n"
                        f"• ⚡ *4H RSI:* {c4['rsi']:.1f} ({'turning down' if c4['rsi_turning_down'] else 'not turning down'})\n"
                        f"• 📉 *MACD:* {'weakening' if c4['macd_hist_weakening'] else 'not weakening'}\n"
                        f"• 🕯️ *Price Action:* {'bearish/rejection candle' if c4['bearish_rejection'] else 'no clear bearish rejection'}\n"
                        f"• 📊 *Sell Score:* {setup['score']}\n\n"
                        f"*Why the bot is warning:* Momentum is deteriorating while the rally is already stretched. This is stronger evidence than RSI alone, but the 4H reversal is not confirmed yet.\n\n"
                        f"📍 *Meaning:* For spot holders, this is a caution/profit-management alert — not an automatic exit signal. Wait for actual reversal confirmation if you want confirmation rather than an early warning."
                    )

                elif stype == "TOP_REVERSAL_CONFIRMED":
                    msg = (
                        f"🔴 *TOP REVERSAL CONFIRMED* : {coin_name}\n\n"
                        f"• *Current Price:* ${p_str}\n"
                        f"• 📉 *4H Price:* Closed below the 20-EMA\n"
                        f"• ⚡ *RSI:* {c4['rsi']:.1f} and turning down\n"
                        f"• 📉 *MACD:* weakening\n"
                        f"• 🕯️ *Price Action:* bearish/rejection confirmed\n"
                        f"• 📊 *Sell Score:* {setup['score']}\n\n"
                        f"*Why this is different from the earlier warning:* The bot now has an actual completed-4H reversal confirmation rather than relying only on an overbought RSI or an extended price.\n\n"
                        f"📍 *Meaning:* This is a spot profit-protection signal. It indicates that the upward move has produced a confirmed 4H deterioration/reversal structure. It is not a short-entry signal."
                    )

                else:
                    continue

                send_telegram(msg)
                time.sleep(1.0)

        except Exception as e:
            logger.error(f"Failed 4H analysis for {symbol}: {e}")
            continue

    if RUN_MODE != "schedule":
        manual_summary += f"──────────────\n✅ *Scan Complete.* {len(full_watchlist)} coins checked. {alerts_fired} alert(s) sent."
        send_telegram(manual_summary)


if __name__ == "__main__":
    check_4h_market()

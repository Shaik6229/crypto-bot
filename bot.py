import json
import logging
import os
import time
import statistics
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("CryptoBot4H")

# --- ENVIRONMENT & EXECUTION MODE ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
RUN_MODE = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
STATE_FILE = "bot_state.json"

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

    retries = Retry(
        total=4,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )

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


# --- STATE PERSISTENCE ---
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
    """
    Suppress duplicate 4H alerts for 12 hours unless price
    has moved >= 1.5 ATR from the previous alert.

    Manual workflow_dispatch runs intentionally bypass this.
    """

    last_record = STATE.get(symbol, {}).get("alert", {})

    if not last_record:
        return False

    if last_record.get("signal") != signal_type:
        return False

    time_elapsed = time.time() - last_record.get("time", 0)

    previous_price = last_record.get("price", 0)

    price_moved = (
        abs(current_price - previous_price) >= (1.5 * atr)
        if previous_price > 0 and atr > 0
        else False
    )

    if time_elapsed < 43200 and not price_moved:
        return True

    return False


def record_alert(symbol, signal_type, price):
    if symbol not in STATE:
        STATE[symbol] = {}

    STATE[symbol]["alert"] = {
        "signal": signal_type,
        "price": price,
        "time": time.time()
    }

    save_state(STATE)


# --- TELEGRAM BROADCASTER ---
def _send_single_telegram_chunk(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    for attempt in range(1, 4):
        try:
            res = HTTP.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text": text,
                    "parse_mode": "Markdown"
                },
                timeout=12
            )

            if res.status_code == 429:
                try:
                    retry_after = res.json().get(
                        "parameters", {}
                    ).get("retry_after", 3)
                except Exception:
                    retry_after = 3

                time.sleep(retry_after)
                continue

            if (
                res.status_code == 400
                and "can't parse entities" in res.text.lower()
            ):
                HTTP.post(
                    url,
                    data={
                        "chat_id": CHAT_ID,
                        "text": text
                    },
                    timeout=12
                )
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


# ============================================================
# MATHEMATICAL ENGINES
# ============================================================

def calculate_wilder_rsi(closes, period=14):
    n = len(closes)

    if n == 0:
        return []

    rsi = [50.0] * n

    if n < period + 1:
        return rsi

    gains = [0.0] * n
    losses = [0.0] * n

    for i in range(1, n):
        diff = closes[i] - closes[i - 1]

        if diff > 0:
            gains[i] = diff
        else:
            losses[i] = -diff

    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period

    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period + 1, n):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    # Keep the existing behavior for early values.
    for i in range(period):
        rsi[i] = rsi[period]

    return rsi


def calculate_ema(data, period):
    """
    EMA calculation.

    Uses the first available value as the seed, while the bot now
    fetches substantially more historical candles for proper warm-up.
    """

    n = len(data)

    if n == 0:
        return []

    if period <= 1:
        return list(data)

    ema = [data[0]] * n
    k = 2.0 / (period + 1)

    for i in range(1, n):
        ema[i] = (
            data[i] * k
            + ema[i - 1] * (1.0 - k)
        )

    return ema


def calculate_rma(data, period):
    n = len(data)

    if n == 0:
        return []

    rma = [0.0] * n

    if n < period:
        return rma

    rma[period - 1] = sum(data[:period]) / period

    for i in range(period, n):
        rma[i] = (
            rma[i - 1] * (period - 1)
            + data[i]
        ) / period

    for i in range(period - 1):
        rma[i] = rma[period - 1]

    return rma


def calculate_atr(highs, lows, closes, period=14):
    n = len(closes)

    if n == 0:
        return []

    tr = [0.0] * n

    tr[0] = highs[0] - lows[0]

    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )

    return calculate_rma(tr, period)


def calculate_macd(closes):
    ema12 = calculate_ema(closes, 12)
    ema26 = calculate_ema(closes, 26)

    macd_line = [
        ema12[i] - ema26[i]
        for i in range(len(closes))
    ]

    signal_line = calculate_ema(macd_line, 9)

    hist = [
        macd_line[i] - signal_line[i]
        for i in range(len(closes))
    ]

    return macd_line, signal_line, hist


# ============================================================
# 1D CONTEXT
# ============================================================

def fetch_1d_context(symbol):
    try:
        # 500 candles so EMA200 is genuinely calculated with
        # sufficient historical warm-up.
        url = (
            "https://data-api.binance.vision/api/v3/klines"
            f"?symbol={symbol}&interval=1d&limit=500"
        )

        res = HTTP.get(url, timeout=10)
        res.raise_for_status()

        raw = res.json()

        if len(raw) < 220:
            raise ValueError(
                f"Insufficient 1D candles: {len(raw)}"
            )

        closes = [float(c[4]) for c in raw]

        # Last candle may still be forming.
        # Use the previous closed daily candle.
        idx = len(closes) - 2

        if idx < 200:
            raise ValueError(
                f"Insufficient EMA200 warm-up at index {idx}"
            )

        rsi_series = calculate_wilder_rsi(closes)
        ema50 = calculate_ema(closes, 50)
        ema200 = calculate_ema(closes, 200)

        c_price = closes[idx]
        c_rsi = rsi_series[idx]
        c_ema50 = ema50[idx]
        c_ema200 = ema200[idx]

        # ----------------------------------------------------
        # 1D BEARISH REGIME
        #
        # 2 of these 3 conditions must be true:
        #
        # 1. Price below EMA50
        # 2. EMA50 below EMA200
        # 3. RSI below 45
        #
        # IMPORTANT:
        # This is ONLY macro context.
        # It is NOT an EMA200 BUY/EXIT blocker.
        # ----------------------------------------------------

        bearish_conditions = [
            c_price < c_ema50,
            c_ema50 < c_ema200,
            c_rsi < 45.0
        ]

        bearish_count = sum(
            1 for condition in bearish_conditions
            if condition
        )

        is_bearish = bearish_count >= 2

        return {
            "price": c_price,
            "rsi": c_rsi,
            "ema50": c_ema50,
            "ema200": c_ema200,
            "is_bearish": is_bearish,
            "bearish_count": bearish_count
        }

    except Exception as e:
        logger.warning(
            f"Could not fetch 1D context for {symbol}: {e}"
        )

        return {
            "price": 0,
            "rsi": 50.0,
            "ema50": 0,
            "ema200": 0,
            "is_bearish": False,
            "bearish_count": 0
        }


# ============================================================
# 4H MARKET DATA
# ============================================================

def fetch_4h_data(symbol, limit=500):
    url = (
        "https://data-api.binance.vision/api/v3/klines"
        f"?symbol={symbol}&interval=4h&limit={limit}"
    )

    res = HTTP.get(url, timeout=10)
    res.raise_for_status()

    raw = res.json()

    if len(raw) < 220:
        raise ValueError(
            f"Insufficient 4H candles: {len(raw)}"
        )

    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []

    for c in raw:
        opens.append(float(c[1]))
        highs.append(float(c[2]))
        lows.append(float(c[3]))
        closes.append(float(c[4]))
        volumes.append(float(c[5]))

    # Last candle may still be forming.
    # Anchor strictly to the previous closed candle.
    idx = len(closes) - 2

    if idx < 220:
        raise ValueError(
            f"Insufficient closed-candle history: {idx}"
        )

    rsi_series = calculate_wilder_rsi(closes)
    _, _, macd_hist = calculate_macd(closes)

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

    # Genuine 200-period EMA.
    # IMPORTANT: this is NOT a filter.
    ema200 = calculate_ema(closes, 200)

    atr = calculate_atr(
        highs,
        lows,
        closes
    )

    c_open = opens[idx]
    c_close = closes[idx]
    c_low = lows[idx]
    c_high = highs[idx]

    c_rsi = rsi_series[idx]
    c_hist = macd_hist[idx]
    c_atr = atr[idx]
    prev_hist = macd_hist[idx - 1]

    if c_atr <= 0:
        raise ValueError(
            "Invalid ATR"
        )

    # --------------------------------------------------------
    # STRUCTURAL HIGH / LOW
    # Uses the available 4H lookback.
    # --------------------------------------------------------

    prior_lows = lows[:idx]
    prior_highs = highs[:idx]

    if not prior_lows or not prior_highs:
        raise ValueError(
            "No prior candles available for structure"
        )

    struct_low = min(prior_lows)
    struct_high = max(prior_highs)

    s_low_idx = prior_lows.index(struct_low)
    s_high_idx = prior_highs.index(struct_high)

    # --------------------------------------------------------
    # LOCAL PIVOTS
    # --------------------------------------------------------

    local_lows = [
        (i, lows[i])
        for i in range(5, idx - 5)
        if lows[i] == min(lows[i - 5:i + 6])
    ]

    local_highs = [
        (i, highs[i])
        for i in range(5, idx - 5)
        if highs[i] == max(highs[i - 5:i + 6])
    ]

    r_low_idx, r_low = (
        local_lows[-1]
        if local_lows
        else (s_low_idx, struct_low)
    )

    r_high_idx, r_high = (
        local_highs[-1]
        if local_highs
        else (s_high_idx, struct_high)
    )

    # --------------------------------------------------------
    # VOLUME MEDIAN
    # --------------------------------------------------------

    volume_window = volumes[
        max(0, idx - 20):idx
    ]

    if not volume_window:
        raise ValueError(
            "Insufficient volume history"
        )

    vol_median = statistics.median(
        volume_window
    )

    if vol_median <= 0:
        vol_median = 1.0

    # --------------------------------------------------------
    # CANDLE GEOMETRY
    # --------------------------------------------------------

    candle_range = c_high - c_low

    # --------------------------------------------------------
    # CONSECUTIVE CANDLES BELOW EMA20
    #
    # Counts prior closed candles only.
    # --------------------------------------------------------

    candles_below_ema20 = 0

    for i in range(
        idx - 1,
        max(0, idx - 25),
        -1
    ):
        if closes[i] < ema20[i]:
            candles_below_ema20 += 1
        else:
            break

    # --------------------------------------------------------
    # CONSOLIDATION HIGH
    # --------------------------------------------------------

    consolidation_window = highs[
        max(0, idx - 12):idx
    ]

    consolidation_high = (
        max(consolidation_window)
        if consolidation_window
        else c_high
    )

    # --------------------------------------------------------
    # DIVERGENCE
    # --------------------------------------------------------

    bullish_div = (
        c_low <= r_low * 1.015
        and c_rsi > rsi_series[r_low_idx]
    )

    bearish_div = (
        c_high >= r_high * 0.985
        and c_rsi < rsi_series[r_high_idx]
    )

    return {
        "price": c_close,
        "open": c_open,
        "low": c_low,
        "high": c_high,

        "structural_low": struct_low,
        "structural_high": struct_high,

        "rsi": c_rsi,

        "hist_slope_up": c_hist > prev_hist,
        "hist_slope_down": c_hist < prev_hist,

        "macd_hist_positive": (
            c_hist > 0
            and prev_hist <= 0
        ),

        "bullish_div": bullish_div,
        "bearish_div": bearish_div,

        "vol_ratio": (
            volumes[idx] / vol_median
            if vol_median > 0
            else 1.0
        ),

        "lower_wick": (
            (min(c_open, c_close) - c_low)
            / candle_range
            if candle_range > 0
            else 0
        ),

        "upper_wick": (
            (c_high - max(c_open, c_close))
            / candle_range
            if candle_range > 0
            else 0
        ),

        "bullish_candle": c_close > c_open,

        "ema20": ema20[idx],
        "ema50": ema50[idx],
        "ema200": ema200[idx],

        # EMA200 extension is a SCORE component only.
        # It does NOT block BUY or EXIT.
        "ema200_ext": (
            ((c_close - ema200[idx]) / ema200[idx]) * 100
            if ema200[idx] > 0
            else 0
        ),

        "atr": c_atr,

        "candles_below_ema20": candles_below_ema20,

        "consolidation_high": consolidation_high
    }


# ============================================================
# LIVE BINANCE ORDER BOOK DEPTH
# ============================================================

def fetch_order_book(symbol, current_price):
    try:
        url = (
            "https://data-api.binance.vision/api/v3/depth"
            f"?symbol={symbol}&limit=100"
        )

        res = HTTP.get(url, timeout=6)
        res.raise_for_status()

        raw = res.json()

        bids = [
            [float(p), float(q)]
            for p, q in raw.get("bids", [])
        ]

        asks = [
            [float(p), float(q)]
            for p, q in raw.get("asks", [])
        ]

        if not bids or not asks:
            return {
                "bid_depth_1pct": 0,
                "ask_depth_1pct": 0,
                "bid_wall_price": current_price,
                "ask_wall_price": current_price,
                "bid_wall_usd": 0,
                "ask_wall_usd": 0
            }

        bids_1pct = sum(
            p * q
            for p, q in bids
            if p >= current_price * 0.99
        )

        asks_1pct = sum(
            p * q
            for p, q in asks
            if p <= current_price * 1.01
        )

        largest_bid = max(
            bids,
            key=lambda x: x[0] * x[1]
        )

        largest_ask = max(
            asks,
            key=lambda x: x[0] * x[1]
        )

        return {
            "bid_depth_1pct": bids_1pct,
            "ask_depth_1pct": asks_1pct,

            "bid_wall_price": largest_bid[0],
            "bid_wall_usd": (
                largest_bid[0] * largest_bid[1]
            ),

            "ask_wall_price": largest_ask[0],
            "ask_wall_usd": (
                largest_ask[0] * largest_ask[1]
            )
        }

    except Exception as e:
        logger.warning(
            f"Could not fetch order book for {symbol}: {e}"
        )

        return {
            "bid_depth_1pct": 0,
            "ask_depth_1pct": 0,
            "bid_wall_price": current_price,
            "ask_wall_price": current_price,
            "bid_wall_usd": 0,
            "ask_wall_usd": 0
        }


# ============================================================
# 4H SCORING & SETUP EVALUATION
# ============================================================

def evaluate_market_condition(c4, ob, d1):

    p = c4["price"]
    ema20 = c4["ema20"]

    ema_stretch_20 = (
        ((p - ema20) / ema20) * 100
        if ema20 > 0
        else 0
    )

    # ========================================================
    # 1. COUNTER-TREND RELIEF SCALP
    # ========================================================

    is_climax_volume = (
        c4["vol_ratio"] >= 2.2
    )

    is_capitulation_rsi = (
        c4["rsi"] <= 28.0
    )

    is_heavy_stretch = (
        ema_stretch_20 <= -7.5
    )

    # Stricter, more meaningful order-book imbalance.
    #
    # IMPORTANT:
    # Visible order-book liquidity is NOT treated as guaranteed
    # support and is NOT called whale activity.
    has_bid_support = (
        ob["bid_depth_1pct"] > 0
        and ob["ask_depth_1pct"] > 0
        and ob["bid_depth_1pct"]
        >= 1.5 * ob["ask_depth_1pct"]
    )

    if (
        d1["is_bearish"]
        and is_heavy_stretch
        and is_capitulation_rsi
        and is_climax_volume
        and has_bid_support
    ):

        tp1 = ema20

        # Use the nearest meaningful target above TP1.
        # Structural high is included only if it is actually
        # above TP1. Otherwise use the +8% fallback.
        tp2_candidates = []

        if c4["structural_high"] > tp1:
            tp2_candidates.append(
                c4["structural_high"]
            )

        tp2_candidates.append(
            p * 1.08
        )

        tp2 = min(tp2_candidates)

        # Guarantee TP2 > TP1.
        if tp2 <= tp1:
            tp2 = tp1 * 1.02

        stop_loss = c4["low"] * 0.992

        return {
            "type": "RELIEF_SCALP",
            "score": 85,
            "ema_stretch": ema_stretch_20,
            "tp1": tp1,
            "tp2": tp2,
            "stop": stop_loss,
            "reasons": [
                (
                    f"Severe rubber-band stretch "
                    f"({ema_stretch_20:.1f}% below 4H 20-EMA)."
                ),
                (
                    f"4H Capitulation RSI "
                    f"({c4['rsi']:.1f}) with panic volume "
                    f"({c4['vol_ratio']:.1f}x median)."
                ),
                (
                    f"Visible bid liquidity exceeds asks "
                    f"by {ob['bid_depth_1pct'] / ob['ask_depth_1pct']:.1f}x."
                )
            ]
        }

    # ========================================================
    # 2. ACCUMULATION IGNITION
    # ========================================================

    was_suppressed = (
        c4["candles_below_ema20"] >= 10
    )

    reclaimed_ema20 = (
        p > ema20
        and c4["open"] <= ema20 * 1.005
    )

    broke_range = (
        p >= c4["consolidation_high"] * 0.998
    )

    is_ignition_vol = (
        c4["vol_ratio"] >= 1.6
    )

    strong_bull_body = (
        c4["bullish_candle"]
        and c4["upper_wick"] <= 0.25
    )

    macd_turned = (
        c4["macd_hist_positive"]
        or c4["hist_slope_up"]
    )

    if (
        was_suppressed
        and reclaimed_ema20
        and broke_range
        and is_ignition_vol
        and strong_bull_body
        and macd_turned
    ):

        # TP1
        tp1 = (
            c4["ema50"]
            if c4["ema50"] > p
            else p * 1.06
        )

        # TP2 must ALWAYS be above TP1.
        tp2_candidates = []

        if c4["structural_high"] > tp1:
            tp2_candidates.append(
                c4["structural_high"]
            )

        tp2_candidates.append(
            p * 1.12
        )

        tp2 = min(tp2_candidates)

        # Final safety guarantee.
        if tp2 <= tp1:
            tp2 = tp1 * 1.02

        stop_loss = min(
            c4["low"],
            p * 0.96
        )

        return {
            "type": "ACCUMULATION_IGNITION",
            "score": 80,
            "tp1": tp1,
            "tp2": tp2,
            "stop": stop_loss,
            "reasons": [
                (
                    f"Breakout after "
                    f"{c4['candles_below_ema20']} candles "
                    f"({c4['candles_below_ema20'] * 4}h) "
                    f"compressed below 4H 20-EMA."
                ),
                (
                    f"Ignition volume surge "
                    f"({c4['vol_ratio']:.1f}x median) "
                    f"with clean close near highs."
                ),
                (
                    f"Reclaimed local consolidation high at "
                    f"${format_price(c4['consolidation_high'])}."
                ),
                "MACD momentum flipped upward."
            ]
        }

    # ========================================================
    # 3. STANDARD 4H TACTICAL SCORING
    # ========================================================

    buy_score = 0
    exit_score = 0

    buy_factors = []
    exit_factors = []

    # --------------------------------------------------------
    # STRUCTURAL SUPPORT / RESISTANCE
    # --------------------------------------------------------

    if (
        p - c4["structural_low"]
        <= 1.5 * c4["atr"]
    ):
        buy_score += 15
        buy_factors.append(
            "Price has reached a major 4H historical floor."
        )

    # EMA200 EXTENSION = SCORE ONLY.
    # It NEVER blocks a BUY.
    if c4["ema200_ext"] < -15.0:
        buy_score += 10
        buy_factors.append(
            f"Severely discounted below 4H 200-EMA "
            f"({c4['ema200_ext']:+.1f}%)."
        )

    if (
        c4["structural_high"] - p
        <= 1.5 * c4["atr"]
    ):
        exit_score += 15
        exit_factors.append(
            "Price has reached a major 4H historical ceiling."
        )

    # EMA200 EXTENSION = SCORE ONLY.
    # It NEVER blocks an EXIT.
    if c4["ema200_ext"] > 25.0:
        exit_score += 10
        exit_factors.append(
            f"Severely stretched above 4H 200-EMA "
            f"({c4['ema200_ext']:+.1f}%)."
        )

    # --------------------------------------------------------
    # BUY-SIDE TECHNICALS
    # --------------------------------------------------------

    if c4["rsi"] < 30:
        buy_score += 15
        buy_factors.append(
            f"4H sellers exhausted (RSI {c4['rsi']:.1f})."
        )

    if c4["bullish_div"]:
        buy_score += 15
        buy_factors.append(
            "Confirmed 4H Bullish Divergence."
        )

    if c4["lower_wick"] >= 0.35:
        buy_score += 10
        buy_factors.append(
            "Strong lower wick absorption by spot buyers."
        )

    # --------------------------------------------------------
    # EXIT-SIDE TECHNICALS
    # --------------------------------------------------------

    if c4["rsi"] > 70:
        exit_score += 15
        exit_factors.append(
            f"4H buyers exhausted (RSI {c4['rsi']:.1f})."
        )

    if c4["bearish_div"]:
        exit_score += 15
        exit_factors.append(
            "Confirmed 4H Bearish Divergence."
        )

    if c4["upper_wick"] >= 0.35:
        exit_score += 10
        exit_factors.append(
            "Strong upper wick rejection by sellers."
        )

    # --------------------------------------------------------
    # ORDER-BOOK LIQUIDITY
    # --------------------------------------------------------

    if (
        ob["bid_depth_1pct"] > 0
        and ob["ask_depth_1pct"] > 0
        and ob["bid_depth_1pct"]
        > 1.3 * ob["ask_depth_1pct"]
    ):
        buy_score += 10
        buy_factors.append(
            "Order-book bid depth significantly "
            "outpaces asks."
        )

    if (
        ob["bid_depth_1pct"] > 0
        and ob["ask_depth_1pct"] > 0
        and ob["ask_depth_1pct"]
        > 1.3 * ob["bid_depth_1pct"]
    ):
        exit_score += 10
        exit_factors.append(
            "Order-book ask liquidity significantly "
            "outweighs bids."
        )

    # --------------------------------------------------------
    # 1D BEARISH CONTEXT PENALTY
    #
    # This affects STANDARD BUY SCORE only.
    #
    # It does NOT prevent BUY.
    # It does NOT affect Relief or Accumulation gates.
    # It does NOT use EMA200 as a distance/proximity filter.
    # --------------------------------------------------------

    if d1["is_bearish"]:
        buy_score = max(
            0,
            buy_score - 25
        )

    # ========================================================
    # EXPLICIT BUY / EXIT CONFLICT HANDLING
    #
    # If both sides qualify, do not let Python's if/elif
    # ordering accidentally decide the signal.
    #
    # The stronger score wins.
    # Exact ties are suppressed as NEUTRAL.
    # ========================================================

    buy_qualifies = buy_score >= 45
    exit_qualifies = exit_score >= 45

    if buy_qualifies and exit_qualifies:

        if buy_score > exit_score:
            if buy_score >= 65:
                return {
                    "type": "BUY_CONFIRMED",
                    "score": buy_score,
                    "reasons": buy_factors
                }

            return {
                "type": "BUY_EARLY",
                "score": buy_score,
                "reasons": buy_factors
            }

        elif exit_score > buy_score:

            if exit_score >= 65:
                return {
                    "type": "SELL_CONFIRMED",
                    "score": exit_score,
                    "reasons": exit_factors
                }

            return {
                "type": "SELL_EARLY",
                "score": exit_score,
                "reasons": exit_factors
            }

        else:
            return {
                "type": "NEUTRAL",
                "score": buy_score,
                "reasons": [
                    "BUY/EXIT scores tied; signal suppressed."
                ]
            }

    # ========================================================
    # NORMAL BUY / EXIT SIGNALS
    # ========================================================

    if buy_score >= 65:
        return {
            "type": "BUY_CONFIRMED",
            "score": buy_score,
            "reasons": buy_factors
        }

    elif buy_score >= 45:
        return {
            "type": "BUY_EARLY",
            "score": buy_score,
            "reasons": buy_factors
        }

    elif exit_score >= 65:
        return {
            "type": "SELL_CONFIRMED",
            "score": exit_score,
            "reasons": exit_factors
        }

    elif exit_score >= 45:
        return {
            "type": "SELL_EARLY",
            "score": exit_score,
            "reasons": exit_factors
        }

    return {
        "type": "NEUTRAL",
        "score": max(
            buy_score,
            exit_score
        ),
        "reasons": []
    }


# ============================================================
# DYNAMIC MOVER DISCOVERY
# ============================================================

def get_dynamic_movers():
    try:
        res = HTTP.get(
            "https://data-api.binance.vision/api/v3/ticker/24hr",
            timeout=10
        )

        res.raise_for_status()

        tickers = res.json()

        l1s = sorted(
            [
                t
                for t in tickers
                if (
                    t.get("symbol") in L1_L2_UNIVERSE
                    and t.get("symbol") not in CORE_WATCHLIST
                )
            ],
            key=lambda x: float(
                x.get("quoteVolume", 0)
            ),
            reverse=True
        )

        ais = sorted(
            [
                t
                for t in tickers
                if (
                    t.get("symbol") in AI_UNIVERSE
                    and t.get("symbol") not in CORE_WATCHLIST
                )
            ],
            key=lambda x: float(
                x.get("quoteVolume", 0)
            ),
            reverse=True
        )

        return (
            [t["symbol"] for t in l1s[:3]],
            [t["symbol"] for t in ais[:3]]
        )

    except Exception as e:
        logger.warning(
            f"Could not discover dynamic movers: {e}"
        )
        return [], []


# ============================================================
# MAIN CONTROLLER
# ============================================================

def check_4h_market():

    logger.info(
        "Initializing 4H Tactical Scanner..."
    )

    top_l1, top_ai = get_dynamic_movers()

    full_watchlist = list(
        dict.fromkeys(
            CORE_WATCHLIST
            + top_l1
            + top_ai
        )
    )

    alerts_fired = 0

    manual_summary = (
        "📊 *[MANUAL 4H SCAN DIAGNOSTIC]* 📊\n"
        "_Closed candle analysis complete:_\n\n"
    )

    for symbol in full_watchlist:

        coin_name = symbol.replace(
            "USDT",
            ""
        )

        try:

            # ------------------------------------------------
            # FETCH MARKET DATA
            # ------------------------------------------------

            c4 = fetch_4h_data(symbol)

            ob = fetch_order_book(
                symbol,
                c4["price"]
            )

            d1 = fetch_1d_context(symbol)

            setup = evaluate_market_condition(
                c4,
                ob,
                d1
            )

            p_str = format_price(
                c4["price"]
            )

            support_str = format_price(
                ob["bid_wall_price"]
            )

            resist_str = format_price(
                ob["ask_wall_price"]
            )

            # ------------------------------------------------
            # STATUS
            # ------------------------------------------------

            status_desc = "⚪ Neutral"

            if setup["type"] == "RELIEF_SCALP":
                status_desc = (
                    "⚡ 4H Relief Scalp Active"
                )

            elif setup["type"] == "ACCUMULATION_IGNITION":
                status_desc = (
                    "🚀 4H Accumulation Ignition"
                )

            elif setup["type"] == "BUY_CONFIRMED":
                status_desc = (
                    "🟢 Confirmed Reversal"
                )

            elif setup["type"] == "BUY_EARLY":
                status_desc = (
                    "🟡 Early Bottom Warning"
                )

            elif setup["type"] == "SELL_CONFIRMED":
                status_desc = (
                    "🔴 Top Exhaustion"
                )

            elif setup["type"] == "SELL_EARLY":
                status_desc = (
                    "🟠 Rally Overheating"
                )

            manual_summary += (
                f"• *{coin_name}*: "
                f"${p_str} | "
                f"Status: {status_desc} | "
                f"4H RSI: {c4['rsi']:.1f}\n"
            )

            # =================================================
            # 1. RELIEF SCALP ALERT
            # =================================================

            if (
                setup["type"] == "RELIEF_SCALP"
                and (
                    RUN_MODE != "schedule"
                    or not check_alert_cooldown(
                        symbol,
                        "RELIEF_SCALP",
                        c4["price"],
                        c4["atr"]
                    )
                )
            ):

                alerts_fired += 1

                bid_ask_ratio = (
                    ob["bid_depth_1pct"]
                    / ob["ask_depth_1pct"]
                    if ob["ask_depth_1pct"] > 0
                    else 0
                )

                msg = (
                    f"⚡ *4H COUNTER-TREND RELIEF SCALP* : "
                    f"{coin_name}\n\n"

                    f"• *Entry Region:* "
                    f"${format_price(c4['low'])} – ${p_str}\n"

                    f"• 🛡️ *Largest Visible Bid:* "
                    f"${support_str}\n"

                    f"• 📉 *Deviation from 4H 20-EMA:* "
                    f"{setup['ema_stretch']:.1f}%\n"

                    f"• ⚡ *4H Panic RSI:* "
                    f"{c4['rsi']:.1f} | "
                    f"*Volume:* "
                    f"{c4['vol_ratio']:.1f}x Median\n"

                    f"• 📚 *Bid/Ask Depth Ratio:* "
                    f"{bid_ask_ratio:.1f}x\n"

                    f"• 🌍 *1D Macro Context:* "
                    f"🔴 Bearish Downtrend\n\n"

                    f"*Tactical Plan:*\n"

                    f"• 🎯 *Take Profit 1:* "
                    f"${format_price(setup['tp1'])} "
                    f"(Retest 4H 20-EMA)\n"

                    f"• 🎯 *Take Profit 2:* "
                    f"${format_price(setup['tp2'])}\n"

                    f"• 🛑 *Invalidation Stop:* "
                    f"Clean 4H close below "
                    f"${format_price(setup['stop'])}\n\n"

                    f"📍 *Execution Rule:* "
                    f"This is NOT a cycle bottom. "
                    f"Treat as a short-duration bounce play. "
                    f"Scale out into USDT at targets and "
                    f"do NOT hold if rejected by the 20-EMA."
                )

                send_telegram(msg)

                record_alert(
                    symbol,
                    "RELIEF_SCALP",
                    c4["price"]
                )

            # =================================================
            # 2. ACCUMULATION IGNITION ALERT
            # =================================================

            elif (
                setup["type"]
                == "ACCUMULATION_IGNITION"
                and (
                    RUN_MODE != "schedule"
                    or not check_alert_cooldown(
                        symbol,
                        "ACCUMULATION_IGNITION",
                        c4["price"],
                        c4["atr"]
                    )
                )
            ):

                alerts_fired += 1

                msg = (
                    f"🚀 *4H ACCUMULATION IGNITION* : "
                    f"{coin_name}\n\n"

                    f"• *Current Price:* "
                    f"${p_str}\n"

                    f"• 📈 *Ignition Volume:* "
                    f"{c4['vol_ratio']:.1f}x Median\n"

                    f"• ⏳ *Suppression Duration:* "
                    f"{c4['candles_below_ema20']} candles "
                    f"({c4['candles_below_ema20'] * 4}h) "
                    f"below 20-EMA\n"

                    f"• 🛡️ *Largest Visible Bid:* "
                    f"${support_str}\n\n"

                    f"*Why the bot flagged this:*\n"
                    f"• "
                    + "\n• ".join(
                        setup["reasons"]
                    )
                    + "\n\n"

                    f"*Tactical Plan:*\n"

                    f"• 🎯 *Take Profit 1 (50%):* "
                    f"${format_price(setup['tp1'])}\n"

                    f"• 🎯 *Take Profit 2 (50%):* "
                    f"${format_price(setup['tp2'])}\n"

                    f"• 🛑 *Invalidation Stop:* "
                    f"Clean 4H close below "
                    f"${format_price(setup['stop'])}\n\n"

                    f"📍 *Execution Rule:* "
                    f"Slow bleed broken. "
                    f"Scale into spot at market or on a "
                    f"retest of the broken 20-EMA."
                )

                send_telegram(msg)

                record_alert(
                    symbol,
                    "ACCUMULATION_IGNITION",
                    c4["price"]
                )

            # =================================================
            # 3. STANDARD BUY ALERT
            # =================================================

            elif (
                setup["type"]
                in ["BUY_CONFIRMED", "BUY_EARLY"]
                and (
                    RUN_MODE != "schedule"
                    or not check_alert_cooldown(
                        symbol,
                        setup["type"],
                        c4["price"],
                        c4["atr"]
                    )
                )
            ):

                alerts_fired += 1

                header = (
                    "🟢 *CONFIRMED BOTTOM REVERSAL*"
                    if setup["type"]
                    == "BUY_CONFIRMED"
                    else
                    "🟡 *EARLY BOTTOM WARNING*"
                )

                msg = (
                    f"{header} : {coin_name}\n\n"

                    f"• *Current Price:* "
                    f"${p_str}\n"

                    f"• 🛡️ *Largest Visible Bid:* "
                    f"${support_str}\n"

                    f"• 💧 *Visible Bid Liquidity "
                    f"within ±1%:* "
                    f"${ob['bid_depth_1pct']:,.0f}\n"

                    f"• 🌍 *1D Macro RSI:* "
                    f"{d1['rsi']:.1f}\n\n"

                    f"*Why the bot flagged this:*\n"
                    f"• "
                    + "\n• ".join(
                        setup["reasons"]
                    )
                    + "\n\n"

                    f"📍 *Execution Context:* "
                    f"Potential spot reversal setup. "
                    f"Consider using a Spot Limit Buy near "
                    f"the identified support/liquidity region "
                    f"rather than assuming the visible order "
                    f"book is guaranteed support."
                )

                send_telegram(msg)

                record_alert(
                    symbol,
                    setup["type"],
                    c4["price"]
                )

            # =================================================
            # 4. STANDARD EXIT ALERT
            # =================================================

            elif (
                setup["type"]
                in ["SELL_CONFIRMED", "SELL_EARLY"]
                and (
                    RUN_MODE != "schedule"
                    or not check_alert_cooldown(
                        symbol,
                        setup["type"],
                        c4["price"],
                        c4["atr"]
                    )
                )
            ):

                alerts_fired += 1

                header = (
                    "🔴 *CONFIRMED TOP EXHAUSTION*"
                    if setup["type"]
                    == "SELL_CONFIRMED"
                    else
                    "🟠 *RALLY OVERHEATING*"
                )

                msg = (
                    f"{header} : {coin_name}\n\n"

                    f"• *Current Price:* "
                    f"${p_str}\n"

                    f"• 🎯 *Largest Visible Ask:* "
                    f"${resist_str}\n"

                    f"• 💧 *Visible Ask Liquidity "
                    f"within ±1%:* "
                    f"${ob['ask_depth_1pct']:,.0f}\n"

                    f"• ⚡ *4H RSI:* "
                    f"{c4['rsi']:.1f}\n\n"

                    f"*Why the bot flagged this:*\n"
                    f"• "
                    + "\n• ".join(
                        setup["reasons"]
                    )
                    + "\n\n"

                    f"📍 *Execution Context:* "
                    f"Rally exhaustion conditions detected. "
                    f"For spot holdings, this is a profit-taking "
                    f"alert rather than a short-entry signal."
                )

                send_telegram(msg)

                record_alert(
                    symbol,
                    setup["type"],
                    c4["price"]
                )

            time.sleep(1.0)

        except Exception as e:

            logger.error(
                f"Failed 4H analysis for {symbol}: {e}"
            )

            continue

    # ========================================================
    # MANUAL SCAN SUMMARY
    # ========================================================

    if RUN_MODE != "schedule":

        manual_summary += (
            "\n──────────────\n"
            f"✅ *4H Scan Complete.* "
            f"{len(full_watchlist)} coins checked. "
            f"{alerts_fired} active alert(s) sent."
        )

        send_telegram(manual_summary)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    check_4h_market()

import logging
import os
import time
import statistics
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================================================================
# LOGGING SETUP
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("CryptoBot4H")


# ================================================================
# ENVIRONMENT & EXECUTION MODE
# ================================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# BOT_RUN_MODE can be explicitly set by GitHub Actions.
# If not set, fall back to the GitHub event name.
RUN_MODE = os.environ.get(
    "BOT_RUN_MODE",
    os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
)


# ================================================================
# VETTED ASSET UNIVERSES — SPOT ONLY
# ================================================================
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


# ================================================================
# RESILIENT HTTP SESSION
# ================================================================
def get_http_session():
    session = requests.Session()

    retries = Retry(
        total=4,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504]
    )

    adapter = HTTPAdapter(max_retries=retries)

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


HTTP = get_http_session()


# ================================================================
# FORMATTING HELPER
# ================================================================
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


# ================================================================
# TELEGRAM BROADCASTER
# ================================================================
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
                time.sleep(
                    res.json().get("parameters", {}).get("retry_after", 3)
                )
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
                _send_single_telegram_chunk(
                    current_chunk.strip()
                )
                time.sleep(1.0)

            current_chunk = para + "\n\n"

    if current_chunk.strip():
        _send_single_telegram_chunk(
            current_chunk.strip()
        )


# ================================================================
# MATHEMATICAL ENGINES
# ================================================================
def calculate_wilder_rsi(closes, period=14):
    n = len(closes)

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

    avg_gain = sum(
        gains[1:period + 1]
    ) / period

    avg_loss = sum(
        losses[1:period + 1]
    ) / period

    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rsi[period] = 100.0 - (
            100.0 / (
                1.0 + avg_gain / avg_loss
            )
        )

    for i in range(period + 1, n):
        avg_gain = (
            avg_gain * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i]
        ) / period

        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rsi[i] = 100.0 - (
                100.0 / (
                    1.0 + avg_gain / avg_loss
                )
            )

    for i in range(period):
        rsi[i] = rsi[period]

    return rsi


def calculate_ema(data, period):
    n = len(data)

    if n == 0:
        return []

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

    rma = [0.0] * n

    if n < period:
        return rma

    rma[period - 1] = (
        sum(data[:period]) / period
    )

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

    signal_line = calculate_ema(
        macd_line,
        9
    )

    hist = [
        macd_line[i] - signal_line[i]
        for i in range(len(closes))
    ]

    return macd_line, signal_line, hist


# ================================================================
# 1D CONTEXT FETCH
# ================================================================
def fetch_1d_context(symbol):
    try:
        url = (
            "https://data-api.binance.vision/api/v3/klines"
            f"?symbol={symbol}&interval=1d&limit=500"
        )

        res = HTTP.get(
            url,
            timeout=8
        )

        res.raise_for_status()

        raw = res.json()

        closes = [
            float(c[4])
            for c in raw
        ]

        if len(closes) < 3:
            raise ValueError(
                "Insufficient 1D candle data"
            )

        # Last completed daily candle.
        idx = len(closes) - 2

        rsi_series = calculate_wilder_rsi(
            closes
        )

        ema50 = calculate_ema(
            closes,
            50
        )

        ema200 = calculate_ema(
            closes,
            200
        )

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
            "is_bearish": (
                bearish_points >= 2
            )
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
            "is_bearish": False
        }


# ================================================================
# LIVE PRICE FETCH
# ================================================================
def fetch_live_price(symbol):
    try:
        url = (
            "https://data-api.binance.vision/api/v3/"
            f"ticker/price?symbol={symbol}"
        )

        res = HTTP.get(
            url,
            timeout=6
        )

        res.raise_for_status()

        return float(
            res.json()["price"]
        )

    except Exception as e:
        logger.warning(
            f"Could not fetch live price for {symbol}: {e}"
        )

        return None


# ================================================================
# 4H MARKET DATA FETCH
# ================================================================
def fetch_4h_data(symbol, limit=500):
    url = (
        "https://data-api.binance.vision/api/v3/klines"
        f"?symbol={symbol}&interval=4h&limit={limit}"
    )

    res = HTTP.get(
        url,
        timeout=10
    )

    res.raise_for_status()

    raw = res.json()

    if len(raw) < 50:
        raise ValueError(
            f"Insufficient 4H candle data for {symbol}"
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

    # ============================================================
    # LAST COMPLETED 4H CANDLE
    # ============================================================
    idx = len(closes) - 2

    rsi_series = calculate_wilder_rsi(
        closes
    )

    _, _, macd_hist = calculate_macd(
        closes
    )

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    ema200 = calculate_ema(
        closes,
        200
    )

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
    prev_rsi = rsi_series[idx - 1]

    # Previous completed candle.
    prev_close = closes[idx - 1]
    prev_open = opens[idx - 1]
    prev_high = highs[idx - 1]
    prev_low = lows[idx - 1]

    # ============================================================
    # ORIGINAL / FROZEN STRUCTURAL MAP
    #
    # IMPORTANT:
    # These values remain unchanged for:
    # - Buy scoring
    # - Sell scoring
    # - Divergence
    #
    # Target selection uses a SEPARATE recent resistance map.
    # ============================================================
    prior_lows = lows[:idx]
    prior_highs = highs[:idx]

    struct_low = (
        min(prior_lows)
        if prior_lows
        else c_low
    )

    struct_high = (
        max(prior_highs)
        if prior_highs
        else c_high
    )

    s_low_idx = (
        prior_lows.index(struct_low)
        if prior_lows
        else 0
    )

    s_high_idx = (
        prior_highs.index(struct_high)
        if prior_highs
        else 0
    )

    local_lows = [
        (i, lows[i])
        for i in range(
            5,
            idx - 5
        )
        if lows[i] == min(
            lows[i - 5:i + 6]
        )
    ]

    local_highs = [
        (i, highs[i])
        for i in range(
            5,
            idx - 5
        )
        if highs[i] == max(
            highs[i - 5:i + 6]
        )
    ]

    r_low_idx, r_low = (
        local_lows[-1]
        if local_lows
        else (
            s_low_idx,
            struct_low
        )
    )

    r_high_idx, r_high = (
        local_highs[-1]
        if local_highs
        else (
            s_high_idx,
            struct_high
        )
    )

    # ============================================================
    # SEPARATE RECENT TARGET RESISTANCE MAP
    #
    # 120 completed 4H candles ≈ 20 days.
    #
    # These variables are ONLY used by the target engine.
    # ============================================================
    resistance_lookback = min(
        120,
        idx
    )

    resistance_start = max(
        0,
        idx - resistance_lookback
    )

    recent_highs = highs[
        resistance_start:idx
    ]

    recent_swing_highs = [
        (i, highs[i])
        for i in range(
            max(5, resistance_start),
            idx - 5
        )
        if highs[i] == max(
            highs[i - 5:i + 6]
        )
    ]

    # ============================================================
    # 12-CANDLE CONSOLIDATION RESISTANCE
    # ============================================================
    consolidation_start = max(
        0,
        idx - 12
    )

    consolidation_high = (
        max(
            highs[
                consolidation_start:idx
            ]
        )
        if idx > 0
        else c_high
    )

    # ============================================================
    # VOLUME
    # ============================================================
    vol_window = volumes[
        max(0, idx - 20):idx
    ]

    vol_median = (
        statistics.median(
            vol_window
        )
        if vol_window
        else 1.0
    )

    # ============================================================
    # CANDLE STRUCTURE
    # ============================================================
    candle_range = (
        c_high - c_low
    )

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

    # ============================================================
    # RETURN DATA
    # ============================================================
    return {
        # --------------------------------------------------------
        # COMPLETED 4H CANDLE
        # --------------------------------------------------------
        "price": c_close,
        "open": c_open,
        "low": c_low,
        "high": c_high,

        # --------------------------------------------------------
        # PREVIOUS COMPLETED 4H CANDLE
        #
        # Used ONLY for top deterioration / reversal detection.
        # Existing scoring remains unchanged.
        # --------------------------------------------------------
        "prev_price": prev_close,
        "prev_open": prev_open,
        "prev_low": prev_low,
        "prev_high": prev_high,

        # --------------------------------------------------------
        # ORIGINAL / FROZEN STRUCTURE
        # --------------------------------------------------------
        "structural_low": struct_low,
        "structural_high": struct_high,

        # --------------------------------------------------------
        # TARGET-ONLY RECENT STRUCTURE
        # --------------------------------------------------------
        "recent_swing_highs": recent_swing_highs,

        "recent_resistance_high": (
            max(
                recent_swing_highs,
                key=lambda x: x[1]
            )[1]
            if recent_swing_highs
            else (
                max(recent_highs)
                if recent_highs
                else c_high
            )
        ),

        # Used for target recency scoring.
        "_idx": idx,

        # --------------------------------------------------------
        # MOMENTUM
        # --------------------------------------------------------
        "rsi": c_rsi,

        "prev_rsi": prev_rsi,

        "rsi_turning_down": (
            c_rsi < prev_rsi
        ),

        "hist_slope_up": (
            c_hist > prev_hist
        ),

        "hist_slope_down": (
            c_hist < prev_hist
        ),

        "macd_hist_weakening": (
            c_hist < prev_hist
        ),

        "macd_hist_crossed_positive": (
            c_hist > 0
            and prev_hist <= 0
        ),

        # --------------------------------------------------------
        # DIVERGENCE
        #
        # Uses ORIGINAL structure.
        # --------------------------------------------------------
        "bullish_div": (
            c_low <= r_low * 1.015
            and c_rsi > rsi_series[r_low_idx]
        ),

        "bearish_div": (
            c_high >= r_high * 0.985
            and c_rsi < rsi_series[r_high_idx]
        ),

        # --------------------------------------------------------
        # VOLUME / CANDLE
        # --------------------------------------------------------
        "vol_ratio": (
            volumes[idx] / vol_median
            if vol_median > 0
            else 1.0
        ),

        "lower_wick": (
            (
                min(c_open, c_close)
                - c_low
            ) / candle_range
            if candle_range > 0
            else 0
        ),

        "upper_wick": (
            (
                c_high
                - max(c_open, c_close)
            ) / candle_range
            if candle_range > 0
            else 0
        ),

        "bullish_candle": (
            c_close > c_open
        ),

        "bearish_candle": (
            c_close < c_open
        ),

        # --------------------------------------------------------
        # TOP REVERSAL EVIDENCE
        #
        # These do NOT modify the existing SELL score.
        # --------------------------------------------------------
        "bearish_rejection": (
            (
                (
                    c_high
                    - max(c_open, c_close)
                ) / candle_range
                if candle_range > 0
                else 0
            ) >= 0.25
            or (
                c_close < c_open
                and c_close < prev_close
            )
        ),

        "strong_bearish_rejection": (
            (
                (
                    c_high
                    - max(c_open, c_close)
                ) / candle_range
                if candle_range > 0
                else 0
            ) >= 0.35
            or (
                c_close < c_open
                and c_close < prev_close
                and c_close <= (
                    c_low
                    + candle_range * 0.40
                )
            )
        ),

        # --------------------------------------------------------
        # EMA / ATR
        # --------------------------------------------------------
        "ema20": ema20[idx],
        "ema50": ema50[idx],
        "ema200": ema200[idx],

        "prev_ema20": ema20[idx - 1],

        "below_ema20": (
            c_close < ema20[idx]
        ),

        "crossed_below_ema20": (
            c_close < ema20[idx]
            and prev_close >= ema20[idx - 1]
        ),

        "ema200_ext": (
            (
                (c_close - ema200[idx])
                / ema200[idx]
            ) * 100
            if ema200[idx] != 0
            else 0
        ),

        "atr": c_atr,

        "candles_below_ema20": (
            candles_below_ema20
        ),

        "consolidation_high": (
            consolidation_high
        )
    }


# ================================================================
# RESISTANCE-BASED TARGET SELECTION ENGINE
# ================================================================
def select_resistance_targets(
    c4,
    reference_price=None
):
    """
    Dedicated target engine.

    Existing signal logic is NOT modified.

    Target candidates:
        - Confirmed recent 4H swing highs
        - 12-candle consolidation resistance
        - 4H EMA50
        - 4H EMA200

    The engine:
        1. Removes levels below/too close to price.
        2. Scores resistance quality.
        3. Clusters nearby levels.
        4. Selects TP1 from meaningful resistance.
        5. Selects TP2 from the next meaningful resistance.
        6. Uses ATR only as a fallback / feasibility mechanism.
    """

    p = (
        reference_price
        if reference_price is not None
        else c4["price"]
    )

    atr = c4["atr"]

    if atr <= 0:
        atr = p * 0.03

    candidates = []

    # ============================================================
    # ADD CANDIDATE
    # ============================================================
    def add_candidate(
        price,
        level_type,
        base_score,
        index=None
    ):
        if price is None:
            return

        price = float(price)

        if price <= p * 1.003:
            return

        recency_score = 0.0

        if index is not None:
            age = max(
                0,
                c4["_idx"] - index
            )

            if age <= 24:
                recency_score = 2.0
            elif age <= 48:
                recency_score = 1.5
            elif age <= 72:
                recency_score = 1.0
            else:
                recency_score = 0.5

        candidates.append({
            "price": price,
            "type": level_type,
            "score": (
                base_score
                + recency_score
            ),
            "index": index
        })

    # ============================================================
    # EMA RESISTANCE
    # ============================================================
    add_candidate(
        c4["ema50"],
        "4H 50-EMA",
        3.0
    )

    add_candidate(
        c4["ema200"],
        "4H 200-EMA",
        3.0
    )

    # ============================================================
    # CONSOLIDATION RESISTANCE
    # ============================================================
    add_candidate(
        c4["consolidation_high"],
        "12-Candle Consolidation Resistance",
        4.0
    )

    # ============================================================
    # RECENT CONFIRMED SWING HIGHS
    # ============================================================
    for index, price in c4.get(
        "recent_swing_highs",
        []
    ):
        add_candidate(
            price,
            "Confirmed 4H Swing Resistance",
            5.0,
            index
        )

    # ============================================================
    # NO STRUCTURAL RESISTANCE
    # ============================================================
    if not candidates:
        tp1 = p + atr
        tp2 = p + 2.5 * atr

        return {
            "tp1": tp1,
            "tp2": tp2,

            "tp1_type": "1.0 ATR Projection",
            "tp2_type": "2.5 ATR Projection",

            "tp1_pct": (
                ((tp1 - p) / p) * 100
            ),

            "tp2_pct": (
                ((tp2 - p) / p) * 100
            ),

            "tp1_atr": (
                (tp1 - p) / atr
            ),

            "tp2_atr": (
                (tp2 - p) / atr
            ),

            "tp1_score": 0,
            "tp2_score": 0
        }

    # ============================================================
    # CLUSTER NEARBY RESISTANCE
    # ============================================================
    cluster_tolerance = max(
        0.30 * atr,
        p * 0.003
    )

    candidates.sort(
        key=lambda x: x["price"]
    )

    clusters = []

    for candidate in candidates:
        placed = False

        for cluster in clusters:
            cluster_price = (
                sum(
                    x["price"]
                    for x in cluster
                ) / len(cluster)
            )

            if abs(
                candidate["price"]
                - cluster_price
            ) <= cluster_tolerance:

                cluster.append(candidate)
                placed = True
                break

        if not placed:
            clusters.append([
                candidate
            ])

    resistance_levels = []

    # ============================================================
    # SCORE EACH RESISTANCE CLUSTER
    # ============================================================
    for cluster in clusters:
        cluster_price = (
            sum(
                x["price"]
                for x in cluster
            ) / len(cluster)
        )

        score = sum(
            x["score"]
            for x in cluster
        )

        if len(cluster) >= 2:
            score += 2.0

        if len(cluster) >= 3:
            score += 2.0

        types = list(
            dict.fromkeys(
                x["type"]
                for x in cluster
            )
        )

        resistance_levels.append({
            "price": cluster_price,
            "score": score,
            "types": types,
            "members": cluster
        })

    resistance_levels.sort(
        key=lambda x: x["price"]
    )

    # ============================================================
    # FILTER WEAK / TOO-CLOSE LEVELS
    # ============================================================
    meaningful = []

    for level in resistance_levels:
        distance_atr = (
            level["price"] - p
        ) / atr

        distance_pct = (
            (
                level["price"] - p
            ) / p
        ) * 100

        if (
            distance_atr < 0.50
            and level["score"] < 8
        ):
            continue

        meaningful.append({
            **level,
            "distance_atr": distance_atr,
            "distance_pct": distance_pct
        })

    # ============================================================
    # TP1
    # ============================================================
    if meaningful:
        tp1_info = meaningful[0]

    else:
        tp1_price = p + atr

        tp1_info = {
            "price": tp1_price,
            "score": 0,
            "types": [
                "1.0 ATR Projection"
            ],
            "distance_atr": 1.0,
            "distance_pct": (
                (tp1_price - p) / p
            ) * 100
        }

    tp1 = tp1_info["price"]

    # ============================================================
    # TP2
    # ============================================================
    tp2_candidates = [
        x
        for x in meaningful
        if x["price"] > (
            tp1
            + max(
                0.25 * atr,
                p * 0.0025
            )
        )
    ]

    if tp2_candidates:
        tp2_info = tp2_candidates[0]

    else:
        tp2_price = p + 2.5 * atr

        if tp2_price <= tp1:
            tp2_price = (
                tp1
                + 0.75 * atr
            )

        tp2_info = {
            "price": tp2_price,
            "score": 0,
            "types": [
                "2.5 ATR Projection"
            ],
            "distance_atr": (
                (tp2_price - p) / atr
            ),
            "distance_pct": (
                (tp2_price - p) / p
            ) * 100
        }

    tp2 = tp2_info["price"]

    # ============================================================
    # HARD 5-ATR MAXIMUM
    # ============================================================
    max_tp2 = p + 5.0 * atr

    if tp2 > max_tp2:
        tp2 = max_tp2

        tp2_info = {
            "price": tp2,
            "score": 0,
            "types": [
                "5 ATR Maximum Extension"
            ],
            "distance_atr": 5.0,
            "distance_pct": (
                (tp2 - p) / p
            ) * 100
        }

    return {
        "tp1": tp1,
        "tp2": tp2,

        "tp1_type": " + ".join(
            tp1_info["types"]
        ),

        "tp2_type": " + ".join(
            tp2_info["types"]
        ),

        "tp1_pct": (
            ((tp1 - p) / p) * 100
        ),

        "tp2_pct": (
            ((tp2 - p) / p) * 100
        ),

        "tp1_atr": (
            (tp1 - p) / atr
        ),

        "tp2_atr": (
            (tp2 - p) / atr
        ),

        "tp1_score": tp1_info.get(
            "score",
            0
        ),

        "tp2_score": tp2_info.get(
            "score",
            0
        )
    }


# ================================================================
# BACKWARD-COMPATIBLE IGNITION TARGET WRAPPER
# ================================================================
def select_ignition_targets(
    c4,
    reference_price=None
):
    return select_resistance_targets(
        c4,
        reference_price
    )


# ================================================================
# LIVE BINANCE ORDER BOOK DEPTH
# ================================================================
def fetch_order_book(
    symbol,
    current_price
):
    try:
        url = (
            "https://data-api.binance.vision/api/v3/depth"
            f"?symbol={symbol}&limit=100"
        )

        res = HTTP.get(
            url,
            timeout=6
        )

        res.raise_for_status()

        raw = res.json()

        bids = [
            [float(p), float(q)]
            for p, q in raw.get(
                "bids",
                []
            )
        ]

        asks = [
            [float(p), float(q)]
            for p, q in raw.get(
                "asks",
                []
            )
        ]

        if not bids or not asks:
            return {
                "bid_depth_1pct": 0,
                "ask_depth_1pct": 0,
                "bid_wall_price": current_price,
                "ask_wall_price": current_price
            }

        # ±1% centered around LIVE price.
        bids_1pct_levels = [
            x
            for x in bids
            if x[0] >= current_price * 0.99
        ]

        asks_1pct_levels = [
            x
            for x in asks
            if x[0] <= current_price * 1.01
        ]

        bid_depth = sum(
            p * q
            for p, q in bids_1pct_levels
        )

        ask_depth = sum(
            p * q
            for p, q in asks_1pct_levels
        )

        largest_bid = (
            max(
                bids_1pct_levels,
                key=lambda x: x[0] * x[1]
            )
            if bids_1pct_levels
            else [
                current_price,
                0
            ]
        )

        largest_ask = (
            max(
                asks_1pct_levels,
                key=lambda x: x[0] * x[1]
            )
            if asks_1pct_levels
            else [
                current_price,
                0
            ]
        )

        return {
            "bid_depth_1pct": bid_depth,
            "ask_depth_1pct": ask_depth,
            "bid_wall_price": largest_bid[0],
            "ask_wall_price": largest_ask[0]
        }

    except Exception as e:
        logger.warning(
            f"Could not fetch order book for {symbol}: {e}"
        )

        return {
            "bid_depth_1pct": 0,
            "ask_depth_1pct": 0,
            "bid_wall_price": current_price,
            "ask_wall_price": current_price
        }


# ================================================================
# DIRECTIONAL PREDICTION ENGINE
# ================================================================
def analyze_market_direction(
    c4,
    ob,
    d1,
    live_price=None
):
    # Technical scoring remains based on completed 4H candle.
    technical_price = c4["price"]

    p = (
        live_price
        if live_price is not None
        else technical_price
    )

    up_score = 0
    down_score = 0
    drivers = []

    # ============================================================
    # 1. EMA TREND STACK
    # ============================================================
    if technical_price > c4["ema20"]:
        up_score += 2
        drivers.append(
            "price is above the short-term trend"
        )
    else:
        down_score += 2
        drivers.append(
            "price is below the short-term trend"
        )

    if technical_price > c4["ema50"]:
        up_score += 1
    else:
        down_score += 1

    # ============================================================
    # 2. MACD MOMENTUM
    # ============================================================
    if c4["hist_slope_up"]:
        up_score += 2
        drivers.append(
            "momentum is improving"
        )

    elif c4["hist_slope_down"]:
        down_score += 2
        drivers.append(
            "momentum is weakening"
        )

    # ============================================================
    # 3. RSI FLOW
    # ============================================================
    if c4["rsi"] >= 52:
        up_score += 1

    elif c4["rsi"] <= 48:
        down_score += 1

    # ============================================================
    # 4. DIVERGENCE
    # ============================================================
    if c4["bullish_div"]:
        up_score += 2
        drivers.append(
            "buyers are showing stronger momentum"
        )

    elif c4["bearish_div"]:
        down_score += 2
        drivers.append(
            "buyers are showing weaker momentum"
        )

    # ============================================================
    # 5. MACRO 1D CONTEXT
    # ============================================================
    if not d1["is_bearish"]:
        up_score += 1

    else:
        down_score += 1
        drivers.append(
            "the daily trend is still weak"
        )

    # ============================================================
    # 6. LIVE ORDER-BOOK LIQUIDITY
    # ============================================================
    if (
        ob["bid_depth_1pct"]
        > 1.2 * ob["ask_depth_1pct"]
    ):
        up_score += 1

    elif (
        ob["ask_depth_1pct"]
        > 1.2 * ob["bid_depth_1pct"]
    ):
        down_score += 1

    reason_str = (
        ", ".join(drivers[:2])
        if drivers
        else "mixed conditions"
    )

    # ============================================================
    # UP BIAS
    # ============================================================
    if up_score >= down_score + 2:
        verdict = "🔼 UP BIAS"

        targets = select_resistance_targets(
            c4,
            reference_price=p
        )

        floors = [
            v
            for v in [
                c4["ema20"],
                ob["bid_wall_price"],
                c4["structural_low"]
            ]
            if v < p * 0.995
        ]

        floor_price = (
            max(floors)
            if floors
            else p * 0.95
        )

        action_note = (
            f"Target: ${format_price(targets['tp1'])} "
            f"({targets['tp1_type']} | "
            f"+{targets['tp1_pct']:.1f}% | "
            f"{targets['tp1_atr']:.1f} ATR) | "
            f"Support: ${format_price(floor_price)} "
            f"({reason_str})"
        )

    # ============================================================
    # DOWN BIAS
    # ============================================================
    elif down_score >= up_score + 2:
        verdict = "🔽 DOWN BIAS"

        downside_candidates = [
            v
            for v in [
                c4["ema20"],
                c4["ema50"],
                ob["bid_wall_price"],
                c4["structural_low"]
            ]
            if v < p * 0.995
        ]

        target_price = (
            max(downside_candidates)
            if downside_candidates
            else p * 0.95
        )

        ceilings = [
            v
            for v in [
                c4["ema20"],
                c4["ema50"],
                ob["ask_wall_price"]
            ]
            if v > p * 1.005
        ]

        ceiling_price = (
            min(ceilings)
            if ceilings
            else p * 1.05
        )

        action_note = (
            f"Downside: ${format_price(target_price)} | "
            f"Ceiling: ${format_price(ceiling_price)} "
            f"({reason_str})"
        )

    # ============================================================
    # SIDEWAYS
    # ============================================================
    else:
        verdict = "⚖️ SIDEWAYS"

        action_note = (
            f"Range: ${format_price(c4['low'])} – "
            f"${format_price(c4['high'])} "
            "(Price is moving without a clear direction)"
        )

    return verdict, action_note


# ================================================================
# TOP EXHAUSTION / REVERSAL DETECTOR
#
# IMPORTANT:
# This is ADDITIONAL alert logic.
#
# Existing BUY/SELL scoring is NOT changed.
# ================================================================
def evaluate_top_exhaustion(
    c4,
    exit_score
):
    """
    Three-stage top framework:

    1. RALLY OVERHEATING
       Existing sell score >=45.
       Means price is stretched / vulnerable.
       NOT a confirmed exit signal.

    2. TOP EXHAUSTION DEVELOPING
       Existing sell score >=45 plus actual deterioration:
       - RSI turning down
       - MACD weakening
       - rejection / bearish candle
       - bearish divergence

    3. TOP REVERSAL CONFIRMED
       Requires actual price reversal confirmation:
       - completed 4H close below EMA20
       - previous completed candle was at/above EMA20
       - RSI turning down
       - MACD weakening
       - bearish/rejection structure
       - meaningful exhaustion background

    No state, cooldown or deduplication is used.
    """

    # ============================================================
    # STAGE 3 — CONFIRMED REVERSAL
    #
    # This is deliberately stricter.
    # ============================================================
    reversal_confirmation = (
        c4["crossed_below_ema20"]
        and c4["rsi_turning_down"]
        and c4["macd_hist_weakening"]
        and c4["bearish_rejection"]
        and (
            exit_score >= 45
            or c4["bearish_div"]
            or c4["ema200_ext"] > 25.0
            or c4["rsi"] > 65
        )
    )

    if reversal_confirmation:
        reasons = [
            "Price has closed back below the 4H 20-EMA.",
            "Momentum is weakening instead of continuing upward.",
            "RSI has started turning down.",
            "The latest candle shows signs that sellers are taking control."
        ]

        if c4["bearish_div"]:
            reasons.append(
                "Price and momentum are no longer moving together."
            )

        return {
            "type": "TOP_REVERSAL_CONFIRMED",
            "reasons": reasons
        }

    # ============================================================
    # STAGE 2 — DEVELOPING EXHAUSTION
    #
    # Need at least TWO deterioration signals.
    # ============================================================
    deterioration_count = 0
    reasons = []

    if c4["rsi_turning_down"]:
        deterioration_count += 1

        reasons.append(
            f"RSI has started falling "
            f"({c4['prev_rsi']:.1f} → {c4['rsi']:.1f})."
        )

    if c4["macd_hist_weakening"]:
        deterioration_count += 1

        reasons.append(
            "Momentum is starting to weaken."
        )

    if c4["bearish_rejection"]:
        deterioration_count += 1

        reasons.append(
            "The latest candle shows selling/rejection near the top."
        )

    if c4["bearish_div"]:
        deterioration_count += 1

        reasons.append(
            "Price is making a stronger push while momentum is weaker."
        )

    # Existing exhaustion background.
    exhaustion_background = (
        exit_score >= 45
        or c4["rsi"] > 70
        or c4["ema200_ext"] > 25.0
        or c4["bearish_div"]
    )

    if (
        exhaustion_background
        and deterioration_count >= 2
    ):
        return {
            "type": "TOP_EXHAUSTION_DEVELOPING",
            "reasons": reasons
        }

    # ============================================================
    # STAGE 1 — EXISTING SELL SCORE
    # ============================================================
    if exit_score >= 45:
        return {
            "type": "RALLY_OVERHEATING",
            "reasons": []
        }

    return None


# ================================================================
# 4H SCORING & SETUP EVALUATION
# FROZEN LIVE STRATEGY
# ================================================================
def evaluate_market_condition(
    c4,
    ob,
    d1,
    target_price_reference=None
):
    # IMPORTANT:
    # This remains the completed 4H candle close.
    # Existing strategy conditions remain unchanged.
    p = c4["price"]

    ema20 = c4["ema20"]

    ema_stretch_20 = (
        (
            (p - ema20)
            / ema20
        ) * 100
        if ema20 != 0
        else 0
    )

    active_setups = []

    # ============================================================
    # 1. COUNTER-TREND RELIEF SCALP
    # ============================================================
    if (
        d1["is_bearish"]
        and ema_stretch_20 <= -7.5
        and c4["rsi"] <= 28.0
        and c4["vol_ratio"] >= 2.2
        and ob["bid_depth_1pct"] > 0
        and ob["ask_depth_1pct"] > 0
        and ob["bid_depth_1pct"]
        >= 1.5 * ob["ask_depth_1pct"]
    ):

        tp1 = ema20

        tp2_candidates = [
            v
            for v in [
                c4["ema50"],
                c4["consolidation_high"],
                c4["structural_high"]
            ]
            if v > tp1
        ]

        tp2 = (
            min(tp2_candidates)
            if tp2_candidates
            else tp1 * 1.04
        )

        active_setups.append({
            "type": "RELIEF_SCALP",
            "ema_stretch": ema_stretch_20,
            "tp1": tp1,
            "tp2": tp2,
            "stop": c4["low"] * 0.992
        })

    # ============================================================
    # 2. ACCUMULATION IGNITION
    #
    # ENTRY CONDITIONS ARE FROZEN.
    # ============================================================
    if (
        c4["candles_below_ema20"] >= 10
        and p > ema20
        and c4["open"] <= ema20 * 1.005
        and p >= c4["consolidation_high"] * 0.998
        and c4["vol_ratio"] >= 1.6
        and c4["bullish_candle"]
        and c4["upper_wick"] <= 0.25
        and (
            c4["macd_hist_crossed_positive"]
            or c4["hist_slope_up"]
        )
    ):

        targets = select_ignition_targets(
            c4,
            reference_price=target_price_reference
        )

        tp1 = targets["tp1"]
        tp2 = targets["tp2"]

        active_setups.append({
            "type": "ACCUMULATION_IGNITION",

            "tp1": tp1,
            "tp2": tp2,

            "tp1_type": targets["tp1_type"],
            "tp2_type": targets["tp2_type"],

            "tp1_pct": targets["tp1_pct"],
            "tp2_pct": targets["tp2_pct"],

            "tp1_atr": targets["tp1_atr"],
            "tp2_atr": targets["tp2_atr"],

            "tp1_score": targets["tp1_score"],
            "tp2_score": targets["tp2_score"],

            "stop": min(
                c4["low"],
                p * 0.96
            ),

            "reasons": [
                (
                    f"Price spent "
                    f"{c4['candles_below_ema20']} "
                    f"candles below its short-term trend "
                    f"before breaking upward."
                ),

                (
                    f"Trading activity suddenly increased "
                    f"({c4['vol_ratio']:.1f}x normal)."
                ),

                (
                    "Price pushed back above the recent "
                    "consolidation area."
                ),

                "Momentum has turned upward."
            ]
        })

    # ============================================================
    # 3. INDEPENDENT BUY & SELL SCORING
    #
    # FROZEN.
    # ============================================================
    buy_score = 0
    exit_score = 0

    buy_factors = []
    exit_factors = []

    # ------------------------------------------------------------
    # BUY FACTORS
    # ------------------------------------------------------------
    if (
        p - c4["structural_low"]
        <= 1.5 * c4["atr"]
    ):
        buy_score += 15

        buy_factors.append(
            "Price is close to the lowest major level in the 4H lookback."
        )

    if c4["ema200_ext"] < -15.0:
        buy_score += 10

        buy_factors.append(
            f"Price is far below its normal long-term 4H trend "
            f"({c4['ema200_ext']:+.1f}%)."
        )

    if c4["rsi"] < 30:
        buy_score += 15

        buy_factors.append(
            f"Selling has become extreme "
            f"(RSI {c4['rsi']:.1f})."
        )

    if c4["bullish_div"]:
        buy_score += 15

        buy_factors.append(
            "Price is showing stronger buying momentum than before."
        )

    if c4["lower_wick"] >= 0.35:
        buy_score += 10

        buy_factors.append(
            "Buyers strongly rejected lower prices."
        )

    # ------------------------------------------------------------
    # SELL FACTORS
    #
    # POINT VALUES REMAIN EXACTLY THE SAME.
    # ------------------------------------------------------------
    if (
        c4["structural_high"] - p
        <= 1.5 * c4["atr"]
    ):
        exit_score += 15

        exit_factors.append(
            "Price is close to the highest major level in the 4H lookback."
        )

    if c4["ema200_ext"] > 25.0:
        exit_score += 10

        exit_factors.append(
            f"Price is far above its normal long-term 4H trend "
            f"({c4['ema200_ext']:+.1f}%)."
        )

    if c4["rsi"] > 70:
        exit_score += 15

        exit_factors.append(
            f"The rally is extremely stretched "
            f"(RSI {c4['rsi']:.1f})."
        )

    if c4["bearish_div"]:
        exit_score += 15

        exit_factors.append(
            "Price is pushing higher while momentum is becoming weaker."
        )

    if c4["upper_wick"] >= 0.35:
        exit_score += 10

        exit_factors.append(
            "Sellers strongly rejected higher prices."
        )

    # ------------------------------------------------------------
    # ORDER BOOK BUY/SELL FACTORS
    # ------------------------------------------------------------
    if (
        ob["bid_depth_1pct"]
        > 1.3 * ob["ask_depth_1pct"]
    ):
        buy_score += 10

        buy_factors.append(
            "There are significantly more visible buy orders than sell orders."
        )

    if (
        ob["ask_depth_1pct"]
        > 1.3 * ob["bid_depth_1pct"]
    ):
        exit_score += 10

        exit_factors.append(
            "There are significantly more visible sell orders than buy orders."
        )

    # ------------------------------------------------------------
    # 1D BEARISH PENALTY
    #
    # FROZEN.
    # ------------------------------------------------------------
    if d1["is_bearish"]:
        buy_score = max(
            0,
            buy_score - 25
        )

    # ------------------------------------------------------------
    # BUY ALERTS
    # ------------------------------------------------------------
    if buy_score >= 65:
        active_setups.append({
            "type": "BUY_CONFIRMED",
            "score": buy_score,
            "reasons": buy_factors
        })

    elif buy_score >= 45:
        active_setups.append({
            "type": "BUY_EARLY",
            "score": buy_score,
            "reasons": buy_factors
        })

    # ============================================================
    # TOP ALERT SYSTEM
    #
    # IMPORTANT:
    # Existing SELL SCORE is preserved.
    #
    # Instead of calling score >=65 a "confirmed top",
    # it now feeds the exhaustion/reversal framework.
    # ============================================================
    top_setup = evaluate_top_exhaustion(
        c4,
        exit_score
    )

    if top_setup is not None:

        # --------------------------------------------------------
        # CONFIRMED REVERSAL
        # --------------------------------------------------------
        if (
            top_setup["type"]
            == "TOP_REVERSAL_CONFIRMED"
        ):
            active_setups.append(
                top_setup
            )

        # --------------------------------------------------------
        # DEVELOPING EXHAUSTION
        # --------------------------------------------------------
        elif (
            top_setup["type"]
            == "TOP_EXHAUSTION_DEVELOPING"
        ):
            top_setup["score"] = exit_score
            active_setups.append(
                top_setup
            )

        # --------------------------------------------------------
        # RALLY OVERHEATING
        # --------------------------------------------------------
        elif (
            top_setup["type"]
            == "RALLY_OVERHEATING"
        ):
            top_setup["score"] = exit_score
            top_setup["reasons"] = exit_factors
            active_setups.append(
                top_setup
            )

    return active_setups


# ================================================================
# DYNAMIC MOVER DISCOVERY
# ================================================================
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
                    t.get("symbol")
                    in L1_L2_UNIVERSE
                    and t.get("symbol")
                    not in CORE_WATCHLIST
                )
            ],
            key=lambda x: float(
                x.get(
                    "quoteVolume",
                    0
                )
            ),
            reverse=True
        )

        ais = sorted(
            [
                t
                for t in tickers
                if (
                    t.get("symbol")
                    in AI_UNIVERSE
                    and t.get("symbol")
                    not in CORE_WATCHLIST
                )
            ],
            key=lambda x: float(
                x.get(
                    "quoteVolume",
                    0
                )
            ),
            reverse=True
        )

        return (
            [
                t["symbol"]
                for t in l1s[:3]
            ],
            [
                t["symbol"]
                for t in ais[:3]
            ]
        )

    except Exception as e:
        logger.warning(
            f"Could not discover dynamic movers: {e}"
        )

        return [], []


# ================================================================
# MAIN CONTROLLER
# ================================================================
def check_4h_market():
    logger.info(
        "Initializing 4H Tactical Scanner..."
    )

    logger.info(
        f"Execution mode: {RUN_MODE}"
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
        "🧭 *[MANUAL 4H MARKET DIRECTION REPORT]* 🧭\n"
        "_Where prices are likely heading from current levels:_\n\n"
    )

    for symbol in full_watchlist:
        coin_name = symbol.replace(
            "USDT",
            ""
        )

        try:
            # ====================================================
            # 4H TECHNICAL DATA
            # ====================================================
            c4 = fetch_4h_data(
                symbol
            )

            # ====================================================
            # LIVE PRICE
            # ====================================================
            live_price = fetch_live_price(
                symbol
            )

            if live_price is None:
                live_price = c4["price"]

            # ====================================================
            # LIVE ORDER BOOK
            # Centered around LIVE price.
            # ====================================================
            ob = fetch_order_book(
                symbol,
                live_price
            )

            # ====================================================
            # 1D CONTEXT
            # ====================================================
            d1 = fetch_1d_context(
                symbol
            )

            # ====================================================
            # FORMATTING
            # ====================================================
            p_str = format_price(
                live_price
            )

            completed_4h_str = format_price(
                c4["price"]
            )

            support_str = format_price(
                ob["bid_wall_price"]
            )

            resist_str = format_price(
                ob["ask_wall_price"]
            )

            # ====================================================
            # MANUAL DIRECTION REPORT
            # ====================================================
            if RUN_MODE != "schedule":

                verdict, action_note = (
                    analyze_market_direction(
                        c4,
                        ob,
                        d1,
                        live_price=live_price
                    )
                )

                manual_summary += (
                    f"• *{coin_name}* "
                    f"(${p_str}) : *{verdict}*\n"
                    f"  ↳ {action_note}\n\n"
                )

            # ====================================================
            # CHECK SETUPS
            # ====================================================
            setups = evaluate_market_condition(
                c4,
                ob,
                d1,
                target_price_reference=live_price
            )

            # ====================================================
            # SEND ALERTS
            # ====================================================
            for setup in setups:

                stype = setup["type"]

                alerts_fired += 1

                # =================================================
                # RELIEF SCALP
                # =================================================
                if stype == "RELIEF_SCALP":

                    msg = (
                        "⚡ *SHORT-TERM BOUNCE ALERT* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 🛡️ *Strongest Visible Buy Support:* "
                        f"${support_str}\n"

                        f"• 📉 *Price is:* "
                        f"{abs(setup['ema_stretch']):.1f}% "
                        f"below the 4H 20-EMA\n"

                        f"• ⚡ *RSI:* "
                        f"{c4['rsi']:.1f}\n"

                        f"• 📊 *Trading Activity:* "
                        f"{c4['vol_ratio']:.1f}x normal\n\n"

                        "*Why the bot flagged this:*\n"
                        "• Price has fallen unusually far.\n"
                        "• Sellers may be exhausted.\n"
                        "• Buyers are showing stronger support.\n"
                        "• The daily trend is still weak, so this is "
                        "a bounce setup rather than a confirmed long-term reversal.\n\n"

                        "*Possible bounce levels:*\n"

                        f"• 🎯 *Target 1:* "
                        f"${format_price(setup['tp1'])} "
                        "(short-term trend)\n"

                        f"• 🎯 *Target 2:* "
                        f"${format_price(setup['tp2'])}\n"

                        f"• 🛑 *Invalidation:* "
                        f"4H close below "
                        f"${format_price(setup['stop'])}\n\n"

                        "📍 *What to do:* "
                        "This is a short-term bounce warning. "
                        "Open the chart and check whether buyers are actually holding support."
                    )

                # =================================================
                # ACCUMULATION IGNITION
                # =================================================
                elif stype == "ACCUMULATION_IGNITION":

                    msg = (
                        "🚀 *BUYING MOMENTUM BUILDING* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 📈 *Trading Activity:* "
                        f"{c4['vol_ratio']:.1f}x normal\n"

                        f"• ⏳ *Time Spent Below Short-Term Trend:* "
                        f"{c4['candles_below_ema20']} "
                        f"candles "
                        f"({c4['candles_below_ema20'] * 4}h)\n"

                        f"• 🛡️ *Strongest Visible Buy Support:* "
                        f"${support_str}\n\n"

                        "*Why the bot flagged this:*\n"
                        "• Price spent a long time weak before moving upward.\n"
                        "• Trading activity suddenly increased.\n"
                        "• Buyers pushed price back above the recent range.\n"
                        "• Momentum has turned upward.\n\n"

                        "*Possible upside levels:*\n"

                        f"• 🎯 *Target 1:* "
                        f"${format_price(setup['tp1'])} "
                        f"({setup['tp1_type']} | "
                        f"+{setup['tp1_pct']:.1f}%)\n"

                        f"• 🎯 *Target 2:* "
                        f"${format_price(setup['tp2'])} "
                        f"({setup['tp2_type']} | "
                        f"+{setup['tp2_pct']:.1f}%)\n"

                        f"• 🛑 *Invalidation:* "
                        f"4H close below "
                        f"${format_price(setup['stop'])}\n\n"

                        "📍 *What to do:* "
                        "Open the chart and check whether the breakout is holding. "
                        "This is a spot-buying setup, not a guarantee of continuation."
                    )

                # =================================================
                # BUY ALERTS
                # =================================================
                elif stype in [
                    "BUY_CONFIRMED",
                    "BUY_EARLY"
                ]:

                    if stype == "BUY_CONFIRMED":

                        header = (
                            "🟢 *STRONG BUYING SIGNAL*"
                        )

                        intro = (
                            "Several signs are lining up that "
                            "buyers may be taking control."
                        )

                    else:

                        header = (
                            "🟡 *EARLY BUYING WARNING*"
                        )

                        intro = (
                            "Some signs suggest that buyers "
                            "may be starting to take control."
                        )

                    msg = (
                        f"{header} : {coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 🛡️ *Strongest Visible Buy Support:* "
                        f"${support_str}\n"

                        f"• 💧 *Visible Sell Orders Within 1%:* "
                        f"${ob['ask_depth_1pct']:,.0f}\n"

                        f"• 🌍 *Daily RSI:* "
                        f"{d1['rsi']:.1f}\n\n"

                        f"*What this means:*\n"
                        f"• {intro}\n\n"

                        "*Why the bot flagged this:*\n"
                        "• "
                        + "\n• ".join(
                            setup["reasons"]
                        )
                        + "\n\n"

                        "📍 *What to do:* "
                        "Open the chart and check support, candle structure "
                        "and whether buyers are actually following through."
                    )

                # =================================================
                # RALLY OVERHEATING
                # =================================================
                elif stype == "RALLY_OVERHEATING":

                    msg = (
                        f"🟠 *RALLY RUNNING HOT* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 🎯 *Strongest Visible Sell Area:* "
                        f"${resist_str}\n"

                        f"• 💧 *Visible Buy Orders Within 1%:* "
                        f"${ob['bid_depth_1pct']:,.0f}\n"

                        f"• ⚡ *4H RSI:* "
                        f"{c4['rsi']:.1f}\n\n"

                        "*What this means:*\n"
                        "• Price has moved up very strongly.\n"
                        "• The move is becoming stretched.\n"
                        "• Buyers are very aggressive, but that does NOT mean the rally is over.\n"
                        "• Selling interest is appearing around the current price.\n\n"

                        "*Why the bot flagged this:*\n"
                        "• "
                        + "\n• ".join(
                            setup["reasons"]
                        )
                        + "\n\n"

                        "⚠️ *Important:* "
                        "This is a WARNING, not a sell signal and not a confirmed top.\n\n"

                        "📍 *What to do:* "
                        "Open the chart and watch for an actual loss of momentum "
                        "or a reversal before making a decision."
                    )

                # =================================================
                # TOP EXHAUSTION DEVELOPING
                # =================================================
                elif stype == "TOP_EXHAUSTION_DEVELOPING":

                    msg = (
                        f"🟡 *TOP EXHAUSTION DEVELOPING* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 🎯 *Strongest Visible Sell Area:* "
                        f"${resist_str}\n"

                        f"• ⚡ *4H RSI:* "
                        f"{c4['rsi']:.1f} "
                        f"(previously {c4['prev_rsi']:.1f})\n\n"

                        "*What this means:*\n"
                        "• The rally is still alive, but buyers are starting to lose strength.\n"
                        "• Momentum has begun weakening.\n"
                        "• The latest price action is showing some selling/rejection.\n"
                        "• This is more serious than simply having an overextended price.\n\n"

                        "*What the bot sees:*\n"
                        "• "
                        + "\n• ".join(
                            setup["reasons"]
                        )
                        + "\n\n"

                        "⚠️ *Important:* "
                        "This is still NOT a confirmed reversal.\n\n"

                        "📍 *What to do:* "
                        "Open the chart and watch whether price actually breaks back below "
                        "its short-term trend."
                    )

                # =================================================
                # TOP REVERSAL CONFIRMED
                # =================================================
                elif stype == "TOP_REVERSAL_CONFIRMED":

                    msg = (
                        f"🔴 *TOP REVERSAL CONFIRMED* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 📉 *4H 20-EMA:* "
                        f"${format_price(c4['ema20'])}\n"

                        f"• ⚡ *4H RSI:* "
                        f"{c4['rsi']:.1f}\n"

                        f"• 🎯 *Visible Sell Area:* "
                        f"${resist_str}\n\n"

                        "*What this means:*\n"
                        "• The price has now fallen back below its short-term trend.\n"
                        "• Momentum is weakening.\n"
                        "• RSI is turning downward.\n"
                        "• The latest 4H candle shows sellers gaining control.\n\n"

                        "*Why the bot flagged this:*\n"
                        "• "
                        + "\n• ".join(
                            setup["reasons"]
                        )
                        + "\n\n"

                        "🔴 *This is different from the earlier warning:* "
                        "the bot is no longer saying only that the rally is stretched. "
                        "It is now seeing actual reversal evidence.\n\n"

                        "📍 *What to do:* "
                        "This is the alert to open the chart and review profit-taking "
                        "or risk management for existing spot holdings."
                    )

                else:
                    continue

                send_telegram(
                    msg
                )

                time.sleep(1.0)

        except Exception as e:

            logger.error(
                f"Failed 4H analysis for {symbol}: {e}"
            )

            continue

    # ============================================================
    # MANUAL REPORT
    # ============================================================
    if RUN_MODE != "schedule":

        manual_summary += (
            "──────────────\n"
            "✅ *Scan Complete.* "
            f"{len(full_watchlist)} coins checked. "
            f"{alerts_fired} active alert(s) sent."
        )

        send_telegram(
            manual_summary
        )


# ================================================================
# PROGRAM ENTRY
# ================================================================
if __name__ == "__main__":
    check_4h_market()

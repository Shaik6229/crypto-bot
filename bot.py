import logging
import os
import time
import statistics
import traceback
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

RUN_MODE = os.environ.get(
    "BOT_RUN_MODE",
    os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")
)


# ================================================================
# VOLATILITY NORMALIZATION SETTINGS
#
# These replace fixed percentage price-distance thresholds
# with ATR-relative thresholds so the scanner adapts to
# different volatility characteristics across assets.
# ================================================================
RELIEF_EMA20_STRETCH_ATR = 2.5

EXTREME_EMA200_DISTANCE_ATR = 5.0


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
                    res.json().get(
                        "parameters",
                        {}
                    ).get(
                        "retry_after",
                        3
                    )
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

    avg_gain = (
        sum(gains[1:period + 1])
        / period
    )

    avg_loss = (
        sum(losses[1:period + 1])
        / period
    )

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


def calculate_atr(
    highs,
    lows,
    closes,
    period=14
):
    n = len(closes)

    if n == 0:
        return []

    tr = [0.0] * n

    tr[0] = highs[0] - lows[0]

    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(
                highs[i]
                - closes[i - 1]
            ),
            abs(
                lows[i]
                - closes[i - 1]
            )
        )

    return calculate_rma(
        tr,
        period
    )


def calculate_macd(closes):
    ema12 = calculate_ema(
        closes,
        12
    )

    ema26 = calculate_ema(
        closes,
        26
    )

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

    return (
        macd_line,
        signal_line,
        hist
    )


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


# ================================================================
# ADAPTIVE CONTEXT HELPERS
# ================================================================
VOLUME_BASELINE_PERIOD = 50
IGNITION_VOLUME_RATIO_MIN = 1.60
RELIEF_VOLUME_RATIO_MIN = 2.20
IGNITION_VOLUME_PERCENTILE = 85.0
RELIEF_VOLUME_PERCENTILE = 95.0

LIQUIDITY_GOOD_SPREAD_PCT = 0.10
LIQUIDITY_WIDE_SPREAD_PCT = 0.50


def percentile_rank(
    value,
    series
):
    """Return the percentile rank of value within historical data."""
    if not series:
        return 50.0

    less_equal = sum(
        1
        for x in series
        if x <= value
    )

    return (
        100.0
        * less_equal
        / len(series)
    )


def classify_volume_regime(
    vol_ratio,
    vol_percentile
):
    if (
        vol_percentile >= 95.0
        or vol_ratio >= 2.5
    ):
        return "exceptional"

    if (
        vol_percentile >= 80.0
        or vol_ratio >= 1.5
    ):
        return "elevated"

    if (
        vol_percentile <= 20.0
        or vol_ratio < 0.75
    ):
        return "quiet"

    return "normal"


def classify_compression(
    candles_below_ema20
):
    if candles_below_ema20 >= 20:
        return "extreme compression"

    if candles_below_ema20 >= 15:
        return "deep compression"

    if candles_below_ema20 >= 10:
        return "established compression"

    if candles_below_ema20 >= 6:
        return "developing compression"

    return "limited compression"


def liquidity_label(
    spread_pct,
    depth_ratio_pct
):
    """
    Context label only.

    It is deliberately not a BUY/SELL gate.
    """
    if (
        spread_pct <= LIQUIDITY_GOOD_SPREAD_PCT
        and depth_ratio_pct >= 5.0
    ):
        return "strong"

    if (
        spread_pct <= LIQUIDITY_WIDE_SPREAD_PCT
        and depth_ratio_pct >= 1.0
    ):
        return "healthy"

    if (
        spread_pct > LIQUIDITY_WIDE_SPREAD_PCT
        or depth_ratio_pct < 0.25
    ):
        return "thin"

    return "mixed"


def fetch_4h_data(symbol, limit=500):
    """
    Fetch completed 4H technical data.

    Important:
      - The last API candle is treated as live/incomplete and is NOT used
        for completed-candle signals.
      - Structural swing highs/lows require five candles on both sides,
        so the current completed candle is never treated as a confirmed
        swing.
      - Divergence compares the two most recent CONFIRMED swing lows or
        highs: price must make the new low/high while RSI makes the
        opposite move.
    """
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

    if len(raw) < 60:
        raise ValueError(
            f"Insufficient 4H candle history for {symbol}: {len(raw)}"
        )

    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []
    quote_volumes = []

    for candle in raw:
        opens.append(float(candle[1]))
        highs.append(float(candle[2]))
        lows.append(float(candle[3]))
        closes.append(float(candle[4]))
        volumes.append(float(candle[5]))

        # Binance kline field 7 = quote asset volume.
        if len(candle) > 7:
            quote_volumes.append(float(candle[7]))
        else:
            quote_volumes.append(
                float(candle[4]) * float(candle[5])
            )

    # The final candle can still be forming. All signal calculations below
    # intentionally anchor to the last completed candle.
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
    atr_series = calculate_atr(
        highs,
        lows,
        closes
    )

    c_open = opens[idx]
    c_close = closes[idx]
    c_low = lows[idx]
    c_high = highs[idx]

    prev_close = closes[idx - 1]
    prev_open = opens[idx - 1]
    prev_low = lows[idx - 1]
    prev_high = highs[idx - 1]

    c_rsi = rsi_series[idx]
    prev_rsi = rsi_series[idx - 1]

    c_hist = macd_hist[idx]
    prev_hist = macd_hist[idx - 1]

    c_atr = atr_series[idx]
    if c_atr <= 0:
        c_atr = max(
            c_close * 0.01,
            1e-12
        )

    # ------------------------------------------------------------
    # STRUCTURAL EXTREMES
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # CONFIRMED SWING DETECTION
    # ------------------------------------------------------------
    # A swing at i is confirmed only when five candles to the LEFT and
    # five candles to the RIGHT exist. Therefore the latest completed
    # candle and all still-forming candles can never become a confirmed
    # swing in this calculation.
    swing_start = 5
    swing_end = idx - 5

    confirmed_swing_lows = []
    confirmed_swing_highs = []

    if swing_end > swing_start:
        for i in range(
            swing_start,
            swing_end
        ):
            low_window = lows[
                i - 5:i + 6
            ]

            high_window = highs[
                i - 5:i + 6
            ]

            if lows[i] == min(
                low_window
            ):
                confirmed_swing_lows.append(
                    (i, lows[i])
                )

            if highs[i] == max(
                high_window
            ):
                confirmed_swing_highs.append(
                    (i, highs[i])
                )

    # ------------------------------------------------------------
    # CONFIRMED-SWING DIVERGENCE
    # ------------------------------------------------------------
    bullish_div = False
    bearish_div = False

    bullish_div_prev_index = None
    bullish_div_current_index = None
    bearish_div_prev_index = None
    bearish_div_current_index = None

    if len(confirmed_swing_lows) >= 2:
        prev_low_idx, prev_low_price = (
            confirmed_swing_lows[-2]
        )
        curr_low_idx, curr_low_price = (
            confirmed_swing_lows[-1]
        )

        prev_low_rsi = rsi_series[
            prev_low_idx
        ]
        curr_low_rsi = rsi_series[
            curr_low_idx
        ]

        bullish_div = (
            curr_low_price < prev_low_price
            and curr_low_rsi > prev_low_rsi
        )

        if bullish_div:
            bullish_div_prev_index = (
                prev_low_idx
            )
            bullish_div_current_index = (
                curr_low_idx
            )

    if len(confirmed_swing_highs) >= 2:
        prev_high_idx, prev_high_price = (
            confirmed_swing_highs[-2]
        )
        curr_high_idx, curr_high_price = (
            confirmed_swing_highs[-1]
        )

        prev_high_rsi = rsi_series[
            prev_high_idx
        ]
        curr_high_rsi = rsi_series[
            curr_high_idx
        ]

        bearish_div = (
            curr_high_price > prev_high_price
            and curr_high_rsi < prev_high_rsi
        )

        if bearish_div:
            bearish_div_prev_index = (
                prev_high_idx
            )
            bearish_div_current_index = (
                curr_high_idx
            )

    # ------------------------------------------------------------
    # TARGET-ONLY RECENT RESISTANCE MAP
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # CONSOLIDATION RESISTANCE
    #
    # IMPORTANT: current breakout candle is excluded.
    # ------------------------------------------------------------
    consolidation_start = max(
        0,
        idx - 12
    )

    if idx > consolidation_start:
        consolidation_high = max(
            highs[
                consolidation_start:idx
            ]
        )
    else:
        consolidation_high = c_high

    # ------------------------------------------------------------
    # VOLUME CONTEXT
    # ------------------------------------------------------------
    volume_baseline_period = 50

    vol_window = volumes[
        max(0, idx - volume_baseline_period):idx
    ]

    quote_volume_window = quote_volumes[
        max(0, idx - 20):idx
    ]

    vol_median = (
        statistics.median(
            vol_window
        )
        if vol_window
        else 1.0
    )

    current_volume = volumes[idx]

    vol_ratio = (
        current_volume / vol_median
        if vol_median > 0
        else 1.0
    )

    vol_percentile = percentile_rank(
        current_volume,
        vol_window
    )

    volume_regime = classify_volume_regime(
        vol_ratio,
        vol_percentile
    )

    avg_quote_volume_4h = (
        statistics.median(
            quote_volume_window
        )
        if quote_volume_window
        else 0.0
    )

    # ------------------------------------------------------------
    # CANDLE STRUCTURE
    # ------------------------------------------------------------
    candle_range = (
        c_high - c_low
    )

    lower_wick_ratio = (
        (
            min(c_open, c_close)
            - c_low
        ) / candle_range
        if candle_range > 0
        else 0.0
    )

    upper_wick_ratio = (
        (
            c_high
            - max(c_open, c_close)
        ) / candle_range
        if candle_range > 0
        else 0.0
    )

    bullish_candle = (
        c_close > c_open
    )

    bearish_candle = (
        c_close < c_open
    )

    # Rejection remains a completed-candle property.
    bearish_rejection = (
        upper_wick_ratio >= 0.25
        or (
            bearish_candle
            and c_close < prev_close
        )
    )

    strong_bearish_rejection = (
        upper_wick_ratio >= 0.35
        or (
            bearish_candle
            and c_close < prev_close
            and c_close <= (
                c_low
                + candle_range * 0.40
            )
        )
    )

    bullish_rejection = (
        lower_wick_ratio >= 0.25
        or (
            bullish_candle
            and c_close > prev_close
        )
    )

    strong_bullish_rejection = (
        lower_wick_ratio >= 0.35
        or (
            bullish_candle
            and c_close > prev_close
            and c_close >= (
                c_low
                + candle_range * 0.60
            )
        )
    )

    # ------------------------------------------------------------
    # MOMENTUM / EMA STATE
    # ------------------------------------------------------------
    rsi_turning_down = (
        c_rsi < prev_rsi
    )

    rsi_turning_up = (
        c_rsi > prev_rsi
    )

    hist_slope_up = (
        c_hist > prev_hist
    )

    hist_slope_down = (
        c_hist < prev_hist
    )

    macd_hist_weakening = (
        c_hist < prev_hist
    )

    macd_hist_strengthening = (
        c_hist > prev_hist
    )

    macd_hist_crossed_positive = (
        c_hist > 0
        and prev_hist <= 0
    )

    macd_hist_crossed_negative = (
        c_hist < 0
        and prev_hist >= 0
    )

    prev_ema20 = ema20[
        idx - 1
    ]

    above_ema20 = (
        c_close > ema20[idx]
    )

    below_ema20 = (
        c_close < ema20[idx]
    )

    crossed_above_ema20 = (
        above_ema20
        and prev_close <= prev_ema20
    )

    crossed_below_ema20 = (
        below_ema20
        and prev_close >= prev_ema20
    )

    ema20_distance_atr = (
        (
            c_close - ema20[idx]
        ) / c_atr
        if c_atr > 0
        else 0.0
    )

    ema200_distance_atr = (
        (
            c_close - ema200[idx]
        ) / c_atr
        if c_atr > 0
        else 0.0
    )

    ema200_ext_pct = (
        (
            (c_close - ema200[idx])
            / ema200[idx]
        ) * 100
        if ema200[idx] != 0
        else 0.0
    )

    # ------------------------------------------------------------
    # COMPRESSION / SUPPRESSION
    # ------------------------------------------------------------
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

    compression_regime = classify_compression(
        candles_below_ema20
    )

    # ------------------------------------------------------------
    # LATEST CONFIRMED SWING REFERENCES
    # ------------------------------------------------------------
    latest_confirmed_low = (
        confirmed_swing_lows[-1]
        if confirmed_swing_lows
        else None
    )

    previous_confirmed_low = (
        confirmed_swing_lows[-2]
        if len(confirmed_swing_lows) >= 2
        else None
    )

    latest_confirmed_high = (
        confirmed_swing_highs[-1]
        if confirmed_swing_highs
        else None
    )

    previous_confirmed_high = (
        confirmed_swing_highs[-2]
        if len(confirmed_swing_highs) >= 2
        else None
    )

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

        "_idx": idx,
        "closed_idx": idx,

        # --------------------------------------------------------
        # CONFIRMED STRUCTURE / DIVERGENCE
        # --------------------------------------------------------
        "confirmed_swing_lows": (
            confirmed_swing_lows[-10:]
        ),
        "confirmed_swing_highs": (
            confirmed_swing_highs[-10:]
        ),
        "latest_confirmed_low": (
            latest_confirmed_low
        ),
        "previous_confirmed_low": (
            previous_confirmed_low
        ),
        "latest_confirmed_high": (
            latest_confirmed_high
        ),
        "previous_confirmed_high": (
            previous_confirmed_high
        ),
        "bullish_div": bullish_div,
        "bearish_div": bearish_div,
        "bullish_div_prev_index": (
            bullish_div_prev_index
        ),
        "bullish_div_current_index": (
            bullish_div_current_index
        ),
        "bearish_div_prev_index": (
            bearish_div_prev_index
        ),
        "bearish_div_current_index": (
            bearish_div_current_index
        ),

        # --------------------------------------------------------
        # MOMENTUM
        # --------------------------------------------------------
        "rsi": c_rsi,
        "prev_rsi": prev_rsi,

        "rsi_turning_down": (
            rsi_turning_down
        ),
        "rsi_turning_up": (
            rsi_turning_up
        ),

        "hist_slope_up": hist_slope_up,
        "hist_slope_down": hist_slope_down,

        "macd_hist_weakening": (
            macd_hist_weakening
        ),
        "macd_hist_strengthening": (
            macd_hist_strengthening
        ),
        "macd_hist_crossed_positive": (
            macd_hist_crossed_positive
        ),
        "macd_hist_crossed_negative": (
            macd_hist_crossed_negative
        ),

        # --------------------------------------------------------
        # VOLUME
        # --------------------------------------------------------
        "vol_ratio": vol_ratio,
        "vol_percentile": vol_percentile,
        "volume_regime": volume_regime,
        "avg_quote_volume_4h": (
            avg_quote_volume_4h
        ),

        # --------------------------------------------------------
        # CANDLE
        # --------------------------------------------------------
        "lower_wick": lower_wick_ratio,
        "upper_wick": upper_wick_ratio,

        "bullish_candle": bullish_candle,
        "bearish_candle": bearish_candle,

        "bearish_rejection": (
            bearish_rejection
        ),
        "strong_bearish_rejection": (
            strong_bearish_rejection
        ),

        "bullish_rejection": (
            bullish_rejection
        ),
        "strong_bullish_rejection": (
            strong_bullish_rejection
        ),

        # --------------------------------------------------------
        # EMA / ATR
        # --------------------------------------------------------
        "ema20": ema20[idx],
        "ema50": ema50[idx],
        "ema200": ema200[idx],

        "prev_ema20": prev_ema20,

        "below_ema20": below_ema20,
        "crossed_below_ema20": (
            crossed_below_ema20
        ),

        "above_ema20": above_ema20,
        "crossed_above_ema20": (
            crossed_above_ema20
        ),

        "ema200_ext": ema200_ext_pct,
        "ema200_distance_atr": (
            ema200_distance_atr
        ),
        "ema20_distance_atr": (
            ema20_distance_atr
        ),

        "atr": c_atr,

        "candles_below_ema20": (
            candles_below_ema20
        ),
        "compression_regime": (
            compression_regime
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
    Select up to three spot-profit-taking targets from meaningful
    resistance above the reference price.

    Resistance sources:
      - 4H 50-EMA
      - 4H 200-EMA
      - pre-breakout consolidation high
      - confirmed 4H swing highs

    Nearby references are clustered. ATR fallbacks are used only when
    historical resistance is insufficient. Targets are capped at 5 ATR
    so a single distant historical level cannot create an impractical
    target.
    """
    p = (
        float(reference_price)
        if reference_price is not None
        else float(c4["price"])
    )

    atr = float(c4.get("atr", 0.0) or 0.0)
    if atr <= 0:
        atr = max(p * 0.03, 1e-12)

    candidates = []

    def add_candidate(price, level_type, base_score, index=None):
        if price is None:
            return

        price = float(price)

        # Ignore levels that are effectively at/inside the current price.
        if price <= p * 1.003:
            return

        recency_score = 0.0

        if index is not None:
            age = max(
                0,
                c4["_idx"] - int(index)
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
            "score": float(base_score) + recency_score,
            "index": index
        })

    add_candidate(
        c4.get("ema50"),
        "4H 50-EMA",
        3.0
    )

    add_candidate(
        c4.get("ema200"),
        "4H 200-EMA",
        3.0
    )

    add_candidate(
        c4.get("consolidation_high"),
        "12-Candle Consolidation Resistance",
        4.0
    )

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

    def make_fallback(distance_atr, name):
        price = p + distance_atr * atr
        return {
            "price": price,
            "score": 0.0,
            "types": [name],
            "distance_atr": distance_atr,
            "distance_pct": (
                ((price - p) / p) * 100
                if p
                else 0.0
            )
        }

    if not candidates:
        tp1_info = make_fallback(1.0, "1.0 ATR Projection")
        tp2_info = make_fallback(2.5, "2.5 ATR Projection")
        tp3_info = make_fallback(4.0, "4.0 ATR Projection")

        return {
            "tp1": tp1_info["price"],
            "tp2": tp2_info["price"],
            "tp3": tp3_info["price"],
            "tp1_type": tp1_info["types"][0],
            "tp2_type": tp2_info["types"][0],
            "tp3_type": tp3_info["types"][0],
            "tp1_pct": tp1_info["distance_pct"],
            "tp2_pct": tp2_info["distance_pct"],
            "tp3_pct": tp3_info["distance_pct"],
            "tp1_atr": tp1_info["distance_atr"],
            "tp2_atr": tp2_info["distance_atr"],
            "tp3_atr": tp3_info["distance_atr"],
            "tp1_score": 0,
            "tp2_score": 0,
            "tp3_score": 0,
        }

    # ------------------------------------------------------------
    # CLUSTER RESISTANCE
    # ------------------------------------------------------------
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
                )
                / len(cluster)
            )

            if abs(
                candidate["price"]
                - cluster_price
            ) <= cluster_tolerance:
                cluster.append(candidate)
                placed = True
                break

        if not placed:
            clusters.append([candidate])

    resistance_levels = []

    for cluster in clusters:
        cluster_price = (
            sum(
                x["price"]
                for x in cluster
            )
            / len(cluster)
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

    meaningful = []

    for level in resistance_levels:
        distance_atr = (
            level["price"] - p
        ) / atr

        distance_pct = (
            (
                level["price"] - p
            ) / p
        ) * 100 if p else 0.0

        # A level inside 0.5 ATR needs enough multi-source support
        # to count as meaningful resistance.
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

    if not meaningful:
        tp1_info = make_fallback(1.0, "1.0 ATR Projection")
    else:
        tp1_info = meaningful[0]

    tp1 = tp1_info["price"]

    min_gap = max(
        0.25 * atr,
        p * 0.0025
    )

    tp2_candidates = [
        x
        for x in meaningful
        if x["price"] > tp1 + min_gap
    ]

    if tp2_candidates:
        tp2_info = tp2_candidates[0]
    else:
        tp2_info = make_fallback(2.5, "2.5 ATR Projection")

        if tp2_info["price"] <= tp1:
            tp2_info = {
                "price": tp1 + 0.75 * atr,
                "score": 0.0,
                "types": ["0.75 ATR Beyond TP1"],
                "distance_atr": (
                    (tp1 + 0.75 * atr - p) / atr
                ),
                "distance_pct": (
                    ((tp1 + 0.75 * atr - p) / p) * 100
                    if p
                    else 0.0
                )
            }

    tp2 = tp2_info["price"]

    tp3_candidates = [
        x
        for x in meaningful
        if x["price"] > tp2 + min_gap
    ]

    if tp3_candidates:
        tp3_info = tp3_candidates[0]
    else:
        tp3_info = make_fallback(4.0, "4.0 ATR Projection")

        if tp3_info["price"] <= tp2:
            fallback_tp3 = tp2 + 0.75 * atr
            tp3_info = {
                "price": fallback_tp3,
                "score": 0.0,
                "types": ["0.75 ATR Beyond TP2"],
                "distance_atr": (
                    (fallback_tp3 - p) / atr
                ),
                "distance_pct": (
                    ((fallback_tp3 - p) / p) * 100
                    if p
                    else 0.0
                )
            }

    # Hard practical cap.
    max_target = p + 5.0 * atr

    if tp2 > max_target:
        tp2 = max_target
        tp2_info = {
            "price": tp2,
            "score": 0.0,
            "types": ["5 ATR Maximum Extension"],
            "distance_atr": 5.0,
            "distance_pct": (
                ((tp2 - p) / p) * 100
                if p
                else 0.0
            )
        }

    if tp3_info["price"] > max_target:
        tp3 = max_target
        tp3_info = {
            "price": tp3,
            "score": 0.0,
            "types": ["5 ATR Maximum Extension"],
            "distance_atr": 5.0,
            "distance_pct": (
                ((tp3 - p) / p) * 100
                if p
                else 0.0
            )
        }
    else:
        tp3 = tp3_info["price"]

    if tp3 <= tp2:
        fallback_tp3 = min(
            max_target,
            tp2 + 0.50 * atr
        )

        if fallback_tp3 > tp2:
            tp3 = fallback_tp3
            tp3_info = {
                "price": tp3,
                "score": 0.0,
                "types": ["0.50 ATR Beyond TP2"],
                "distance_atr": (
                    (tp3 - p) / atr
                ),
                "distance_pct": (
                    ((tp3 - p) / p) * 100
                    if p
                    else 0.0
                )
            }
        else:
            tp3 = tp2

    return {
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,

        "tp1_type": " + ".join(
            tp1_info["types"]
        ),
        "tp2_type": " + ".join(
            tp2_info["types"]
        ),
        "tp3_type": " + ".join(
            tp3_info["types"]
        ),

        "tp1_pct": (
            ((tp1 - p) / p) * 100
            if p
            else 0.0
        ),
        "tp2_pct": (
            ((tp2 - p) / p) * 100
            if p
            else 0.0
        ),
        "tp3_pct": (
            ((tp3 - p) / p) * 100
            if p
            else 0.0
        ),

        "tp1_atr": (tp1 - p) / atr,
        "tp2_atr": (tp2 - p) / atr,
        "tp3_atr": (tp3 - p) / atr,

        "tp1_score": tp1_info.get("score", 0),
        "tp2_score": tp2_info.get("score", 0),
        "tp3_score": tp3_info.get("score", 0),
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
#
# IMPORTANT:
# Order-book data is CONTEXT ONLY.
#
# It is NOT used to add points to BUY/SELL scores.
# It is NOT required to trigger the Relief Scalp setup.
#
# This reduces dependence on potentially spoofable
# instantaneous displayed liquidity.
# ================================================================

def fetch_order_book(
    symbol,
    current_price,
    reference_quote_volume=0.0
):
    """
    Fetch visible 1% depth for context.

    The order book is intentionally not used as a hard BUY/SELL score input.
    Visible depth is also normalized against recent quote volume so the
    displayed liquidity can be interpreted across assets of different scale.
    """
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
            [float(price), float(quantity)]
            for price, quantity in raw.get(
                "bids",
                []
            )
        ]

        asks = [
            [float(price), float(quantity)]
            for price, quantity in raw.get(
                "asks",
                []
            )
        ]

        if not bids or not asks:
            return {
                "bid_depth_1pct": 0.0,
                "ask_depth_1pct": 0.0,
                "bid_wall_price": current_price,
                "ask_wall_price": current_price,
                "bid_wall_notional": 0.0,
                "ask_wall_notional": 0.0,
                "spread_pct": 0.0,
                "visible_depth_ratio_pct": 0.0,
                "liquidity_label": "unknown",
            }

        bids_1pct_levels = [
            level
            for level in bids
            if level[0] >= current_price * 0.99
        ]

        asks_1pct_levels = [
            level
            for level in asks
            if level[0] <= current_price * 1.01
        ]

        bid_depth = sum(
            price * quantity
            for price, quantity in bids_1pct_levels
        )

        ask_depth = sum(
            price * quantity
            for price, quantity in asks_1pct_levels
        )

        largest_bid = (
            max(
                bids_1pct_levels,
                key=lambda x: x[0] * x[1]
            )
            if bids_1pct_levels
            else [
                current_price,
                0.0
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
                0.0
            ]
        )

        best_bid = (
            max(
                price
                for price, _ in bids
            )
            if bids
            else current_price
        )

        best_ask = (
            min(
                price
                for price, _ in asks
            )
            if asks
            else current_price
        )

        spread_pct = (
            (
                (best_ask - best_bid)
                / current_price
            ) * 100
            if current_price > 0
            else 0.0
        )

        visible_depth = (
            bid_depth
            + ask_depth
        )

        depth_ratio_pct = (
            (
                visible_depth
                / reference_quote_volume
            ) * 100
            if reference_quote_volume > 0
            else 0.0
        )

        return {
            "bid_depth_1pct": bid_depth,
            "ask_depth_1pct": ask_depth,
            "bid_wall_price": largest_bid[0],
            "ask_wall_price": largest_ask[0],
            "bid_wall_notional": (
                largest_bid[0]
                * largest_bid[1]
            ),
            "ask_wall_notional": (
                largest_ask[0]
                * largest_ask[1]
            ),
            "spread_pct": spread_pct,
            "visible_depth_ratio_pct": depth_ratio_pct,
            "liquidity_label": liquidity_label(
                spread_pct,
                depth_ratio_pct
            )
        }

    except Exception as e:
        logger.warning(
            f"Could not fetch order book for {symbol}: {e}"
        )

        return {
            "bid_depth_1pct": 0.0,
            "ask_depth_1pct": 0.0,
            "bid_wall_price": current_price,
            "ask_wall_price": current_price,
            "bid_wall_notional": 0.0,
            "ask_wall_notional": 0.0,
            "spread_pct": 0.0,
            "visible_depth_ratio_pct": 0.0,
            "liquidity_label": "unknown",
        }


# ================================================================
# DIRECTIONAL PREDICTION ENGINE
#
# Order book remains available here as CONTEXT for the separate
# manual direction report.
#
# It does NOT affect BUY/SELL alert scoring.
# ================================================================
def analyze_market_direction(
    c4,
    ob,
    d1,
    live_price=None
):
    technical_price = c4["price"]

    p = (
        live_price
        if live_price is not None
        else technical_price
    )

    up_score = 0
    down_score = 0
    drivers = []

    # EMA trend
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

    # MACD
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

    # RSI
    if c4["rsi"] >= 52:
        up_score += 1

    elif c4["rsi"] <= 48:
        down_score += 1

    # Divergence
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

    # Daily context
    if not d1["is_bearish"]:
        up_score += 1
    else:
        down_score += 1
        drivers.append(
            "the daily trend is still weak"
        )

    # ------------------------------------------------------------
    # ORDER BOOK — CONTEXT ONLY
    #
    # This does NOT contribute to BUY/SELL alert scores.
    # It is retained in the manual direction report because the
    # report is explicitly a broader market-context view.
    # ------------------------------------------------------------
    if (
        ob["bid_depth_1pct"] > 0
        and ob["ask_depth_1pct"] > 0
    ):
        if (
            ob["bid_depth_1pct"]
            > 1.2 * ob["ask_depth_1pct"]
        ):
            drivers.append(
                "visible bid liquidity is currently stronger"
            )

        elif (
            ob["ask_depth_1pct"]
            > 1.2 * ob["bid_depth_1pct"]
        ):
            drivers.append(
                "visible sell liquidity is currently stronger"
            )

    reason_str = (
        ", ".join(drivers[:2])
        if drivers
        else "mixed conditions"
    )

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
# ================================================================

def evaluate_top_exhaustion(
    c4
):
    """
    Three-stage top process built from price/momentum evidence only.

    This engine is intentionally independent of SELL score and position
    state, so an exit/top alert can occur even when no BUY alert was active.

    Stage 1:
        RALLY_OVERHEATING
        - price/RSI/ATR extension shows a stretched rally

    Stage 2:
        TOP_EXHAUSTION_DEVELOPING
        - the rally is stretched AND at least two independent deterioration
          signals are present

    Stage 3:
        TOP_REVERSAL_CONFIRMED
        - completed 4H candle crosses below EMA20 and momentum/rejection
          evidence confirms actual deterioration
    """
    background_signals = []

    if c4["rsi"] >= 70.0:
        background_signals.append(
            f"RSI is elevated at {c4['rsi']:.1f}."
        )
    elif c4["rsi"] >= 65.0:
        background_signals.append(
            f"RSI is elevated at {c4['rsi']:.1f}."
        )

    if (
        c4["ema200_distance_atr"]
        >= EXTREME_EMA200_DISTANCE_ATR
    ):
        background_signals.append(
            f"Price is {c4['ema200_distance_atr']:.1f} ATR above EMA200."
        )
    elif c4["ema200_distance_atr"] >= 3.5:
        background_signals.append(
            f"Price is extended {c4['ema200_distance_atr']:.1f} ATR above EMA200."
        )

    if (
        c4["structural_high"] - c4["price"]
        <= 1.5 * c4["atr"]
    ):
        background_signals.append(
            "Price is close to the major 4H structural high."
        )

    if c4["bearish_div"]:
        background_signals.append(
            "Bearish divergence is present between the two latest confirmed swing highs."
        )

    rally_background = bool(
        background_signals
    )

    deterioration_signals = []
    reasons = []

    if c4["rsi_turning_down"]:
        deterioration_signals.append(
            "RSI is turning downward."
        )
        reasons.append(
            f"RSI has started falling ({c4['prev_rsi']:.1f} → {c4['rsi']:.1f})."
        )

    if c4["macd_hist_weakening"]:
        deterioration_signals.append(
            "MACD histogram is weakening."
        )
        reasons.append(
            "MACD histogram is losing upward momentum."
        )

    if c4["bearish_rejection"]:
        deterioration_signals.append(
            "Bearish candle/rejection is present."
        )
        reasons.append(
            "The latest completed 4H candle shows rejection/selling near higher prices."
        )

    if c4["bearish_div"]:
        deterioration_signals.append(
            "Bearish divergence is present."
        )
        reasons.append(
            "The two latest confirmed swing highs show higher price with lower RSI momentum."
        )

    deterioration_count = len(
        deterioration_signals
    )

    # ------------------------------------------------------------
    # STAGE 3 — CONFIRMED REVERSAL
    # ------------------------------------------------------------
    reversal_confirmation = (
        c4["crossed_below_ema20"]
        and c4["rsi_turning_down"]
        and c4["macd_hist_weakening"]
        and c4["bearish_rejection"]
        and (
            c4["bearish_div"]
            or c4["ema200_distance_atr"]
            >= EXTREME_EMA200_DISTANCE_ATR
            or c4["rsi"] >= 70.0
        )
    )

    if reversal_confirmation:
        confirmed_reasons = [
            "The completed 4H candle closed back below the 20-EMA.",
            "RSI is turning downward.",
            "MACD histogram is weakening.",
            "The latest candle shows bearish rejection."
        ]

        if c4["bearish_div"]:
            confirmed_reasons.append(
                "Bearish divergence is present between confirmed swing highs."
            )

        return {
            "type": "TOP_REVERSAL_CONFIRMED",
            "reasons": confirmed_reasons
        }

    # ------------------------------------------------------------
    # STAGE 2 — DEVELOPING EXHAUSTION
    # ------------------------------------------------------------
    if (
        rally_background
        and deterioration_count >= 2
    ):
        if not reasons:
            reasons = list(
                background_signals
            )

        return {
            "type": "TOP_EXHAUSTION_DEVELOPING",
            "reasons": (
                background_signals
                + reasons
            )
        }

    # ------------------------------------------------------------
    # STAGE 1 — RALLY OVERHEATING
    # ------------------------------------------------------------
    if rally_background:
        return {
            "type": "RALLY_OVERHEATING",
            "reasons": background_signals
        }

    return None


# ================================================================
# BOTTOM EXHAUSTION / REVERSAL DETECTOR
#
# IMPORTANT:
# This is completely independent from BUY scoring.
#
# Existing BUY score point values are NOT changed.
# ================================================================

def evaluate_bottom_exhaustion(
    c4
):
    """
    Three-stage bottom process built from price/momentum evidence only.

    This engine is independent of BUY score. It does not require an
    active BUY setup to observe early bottoming evidence.
    """
    background_signals = []

    if c4["rsi"] <= 30.0:
        background_signals.append(
            f"RSI is deeply oversold at {c4['rsi']:.1f}."
        )
    elif c4["rsi"] < 35.0:
        background_signals.append(
            f"RSI is depressed at {c4['rsi']:.1f}."
        )

    if (
        c4["ema200_distance_atr"]
        <= -EXTREME_EMA200_DISTANCE_ATR
    ):
        background_signals.append(
            f"Price is {abs(c4['ema200_distance_atr']):.1f} ATR below EMA200."
        )
    elif c4["ema200_distance_atr"] <= -3.5:
        background_signals.append(
            f"Price is extended {abs(c4['ema200_distance_atr']):.1f} ATR below EMA200."
        )

    if (
        c4["price"] - c4["structural_low"]
        <= 1.5 * c4["atr"]
    ):
        background_signals.append(
            "Price is close to the major 4H structural low."
        )

    if c4["bullish_div"]:
        background_signals.append(
            "Bullish divergence is present between the two latest confirmed swing lows."
        )

    bottom_background = bool(
        background_signals
    )

    improvement_signals = []
    reasons = []

    if c4["rsi_turning_up"]:
        improvement_signals.append(
            "RSI is turning upward."
        )
        reasons.append(
            f"RSI has started recovering ({c4['prev_rsi']:.1f} → {c4['rsi']:.1f})."
        )

    if c4["macd_hist_strengthening"]:
        improvement_signals.append(
            "MACD histogram is strengthening."
        )
        reasons.append(
            "MACD histogram is becoming less negative / more positive."
        )

    if c4["bullish_rejection"]:
        improvement_signals.append(
            "Bullish rejection is present."
        )
        reasons.append(
            "The latest completed 4H candle shows buyers rejecting lower prices."
        )

    if c4["bullish_div"]:
        improvement_signals.append(
            "Bullish divergence is present."
        )
        reasons.append(
            "The two latest confirmed swing lows show lower price with higher RSI momentum."
        )

    improvement_count = len(
        improvement_signals
    )

    # ------------------------------------------------------------
    # STAGE 3 — CONFIRMED BOTTOM REVERSAL
    # ------------------------------------------------------------
    reversal_confirmation = (
        c4["crossed_above_ema20"]
        and c4["rsi_turning_up"]
        and c4["macd_hist_strengthening"]
        and c4["bullish_rejection"]
        and (
            c4["bullish_div"]
            or c4["ema200_distance_atr"]
            <= -EXTREME_EMA200_DISTANCE_ATR
            or c4["rsi"] <= 30.0
        )
    )

    if reversal_confirmation:
        confirmed_reasons = [
            "The completed 4H candle closed back above the 20-EMA.",
            "RSI is turning upward.",
            "MACD histogram is strengthening.",
            "The latest candle shows bullish rejection."
        ]

        if c4["bullish_div"]:
            confirmed_reasons.append(
                "Bullish divergence is present between confirmed swing lows."
            )

        return {
            "type": "BOTTOM_REVERSAL_CONFIRMED",
            "reasons": confirmed_reasons
        }

    # ------------------------------------------------------------
    # STAGE 2 — DEVELOPING BOTTOM EXHAUSTION
    # ------------------------------------------------------------
    if (
        bottom_background
        and improvement_count >= 2
    ):
        return {
            "type": "BOTTOM_EXHAUSTION_DEVELOPING",
            "reasons": (
                background_signals
                + reasons
            )
        }

    # ------------------------------------------------------------
    # STAGE 1 — SELLING PRESSURE EASING
    # ------------------------------------------------------------
    if (
        bottom_background
        and improvement_count >= 1
    ):
        return {
            "type": "SELLING_PRESSURE_EASING",
            "reasons": (
                background_signals
                + reasons
            )
        }

    return None


# ================================================================
# 4H SCORING & SETUP EVALUATION
# ================================================================

def evaluate_market_condition(
    c4,
    ob,
    d1,
    target_price_reference=None
):
    """
    Evaluate all 4H spot setups.

    BUY/SELL scoring remains separate from the exhaustion engines.
    Order-book data is context only and cannot manufacture a signal.

    SELL alerts are spot exit/profit-taking alerts. They do not mean shorts.
    They are intentionally allowed even when no BUY alert was active.
    """
    p = c4["price"]
    ema20 = c4["ema20"]

    ema20_distance_atr = (
        c4["ema20_distance_atr"]
    )

    active_setups = []

    # ============================================================
    # 1. COUNTER-TREND RELIEF SCALP
    # ============================================================
    # This remains a bounce setup, not a long-term reversal.
    # The old fixed -7.5% condition is replaced by ATR stretch.
    # Volume can qualify through ratio OR historical percentile so a
    # single normalization method cannot make the scanner blind.
    relief_volume_ok = (
        c4["vol_ratio"] >= RELIEF_VOLUME_RATIO_MIN
        or c4["vol_percentile"] >= RELIEF_VOLUME_PERCENTILE
    )

    relief_bounce_confirmation = (
        c4["bullish_rejection"]
        or (
            c4["rsi_turning_up"]
            and c4["hist_slope_up"]
            and c4["bullish_candle"]
        )
    )

    if (
        d1["is_bearish"]
        and ema20_distance_atr
        <= -RELIEF_EMA20_STRETCH_ATR
        and c4["rsi"] <= 28.0
        and relief_volume_ok
        and relief_bounce_confirmation
    ):
        tp1 = ema20

        tp2_candidates = [
            value
            for value in [
                c4["ema50"],
                c4["consolidation_high"],
                c4["structural_high"]
            ]
            if value > tp1
        ]

        tp2 = (
            min(tp2_candidates)
            if tp2_candidates
            else tp1 * 1.04
        )

        relief_reasons = [
            (
                f"Price is {abs(ema20_distance_atr):.1f} ATR below "
                "the 4H 20-EMA."
            ),
            f"RSI is deeply oversold at {c4['rsi']:.1f}.",
            (
                f"Trading activity is elevated "
                f"({c4['vol_ratio']:.1f}x median, "
                f"{c4['vol_percentile']:.0f}th percentile)."
            ),
        ]

        if c4["bullish_rejection"]:
            relief_reasons.append(
                "The completed 4H candle shows bullish rejection of lower prices."
            )
        else:
            relief_reasons.append(
                "RSI and MACD momentum are turning upward while the candle closes bullish."
            )

        active_setups.append({
            "type": "RELIEF_SCALP",
            "ema_stretch": (
                (
                    (p - ema20)
                    / ema20
                ) * 100
                if ema20 != 0
                else 0
            ),
            "ema_stretch_atr": abs(
                ema20_distance_atr
            ),
            "tp1": tp1,
            "tp2": tp2,
            "stop": c4["low"] * 0.992,
            "reasons": relief_reasons,
        })

    # ============================================================
    # 2. ACCUMULATION IGNITION
    # ============================================================
    ignition_volume_ok = (
        c4["vol_ratio"] >= IGNITION_VOLUME_RATIO_MIN
        or c4["vol_percentile"] >= IGNITION_VOLUME_PERCENTILE
    )

    if (
        c4["candles_below_ema20"] >= 10
        and p > ema20
        and c4["open"] <= ema20 * 1.005
        and p >= c4["consolidation_high"] * 0.998
        and ignition_volume_ok
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

        active_setups.append({
            "type": "ACCUMULATION_IGNITION",

            "tp1": targets["tp1"],
            "tp2": targets["tp2"],
            "tp3": targets["tp3"],

            "tp1_type": targets["tp1_type"],
            "tp2_type": targets["tp2_type"],
            "tp3_type": targets["tp3_type"],

            "tp1_pct": targets["tp1_pct"],
            "tp2_pct": targets["tp2_pct"],
            "tp3_pct": targets["tp3_pct"],

            "tp1_atr": targets["tp1_atr"],
            "tp2_atr": targets["tp2_atr"],
            "tp3_atr": targets["tp3_atr"],

            "tp1_score": targets["tp1_score"],
            "tp2_score": targets["tp2_score"],
            "tp3_score": targets["tp3_score"],

            "stop": min(
                c4["low"],
                p * 0.96
            ),

            "reasons": [
                (
                    f"Breakout after "
                    f"{c4['candles_below_ema20']} completed 4H candles "
                    "below the 20-EMA."
                ),
                (
                    f"Trading activity increased "
                    f"({c4['vol_ratio']:.1f}x median; "
                    f"{c4['vol_percentile']:.0f}th percentile)."
                ),
                (
                    "Price reclaimed the recent consolidation high "
                    f"near ${format_price(c4['consolidation_high'])}."
                ),
                "MACD momentum is turning upward.",
                (
                    f"Volume regime: {c4['volume_regime']}."
                ),
                (
                    f"Compression regime: {c4['compression_regime']}."
                ),
                (
                    f"Liquidity context: {ob.get('liquidity_label', 'unknown')} "
                    f"(spread {ob.get('spread_pct', 0.0):.3f}%)."
                ),
            ]
        })

    # ============================================================
    # 3. FROZEN BUY / SELL SCORE ENGINES
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

    if (
        c4["ema200_distance_atr"]
        <= -EXTREME_EMA200_DISTANCE_ATR
    ):
        buy_score += 10

        buy_factors.append(
            f"Price is deeply extended below the 4H EMA200 "
            f"({c4['ema200_distance_atr']:.1f} ATR)."
        )

    if c4["rsi"] < 30:
        buy_score += 15

        buy_factors.append(
            f"Selling has become extreme (RSI {c4['rsi']:.1f})."
        )

    if c4["bullish_div"]:
        buy_score += 15

        buy_factors.append(
            "Confirmed bullish divergence is present between the two latest swing lows."
        )

    if c4["lower_wick"] >= 0.35:
        buy_score += 10

        buy_factors.append(
            "Buyers strongly rejected lower prices."
        )

    # ------------------------------------------------------------
    # SELL / EXIT FACTORS — FROZEN VALUES
    # ------------------------------------------------------------
    if (
        c4["structural_high"] - p
        <= 1.5 * c4["atr"]
    ):
        exit_score += 15

        exit_factors.append(
            "Price is close to the highest major level in the 4H lookback."
        )

    if (
        c4["ema200_distance_atr"]
        >= EXTREME_EMA200_DISTANCE_ATR
    ):
        exit_score += 10

        exit_factors.append(
            f"Price is deeply extended above the 4H EMA200 "
            f"({c4['ema200_distance_atr']:.1f} ATR)."
        )

    if c4["rsi"] > 70:
        exit_score += 15

        exit_factors.append(
            f"The rally is extremely stretched (RSI {c4['rsi']:.1f})."
        )

    if c4["bearish_div"]:
        exit_score += 15

        exit_factors.append(
            "Confirmed bearish divergence is present between the two latest swing highs."
        )

    if c4["upper_wick"] >= 0.35:
        exit_score += 10

        exit_factors.append(
            "Sellers strongly rejected higher prices."
        )

    # ------------------------------------------------------------
    # ORDER BOOK IS CONTEXT ONLY
    # ------------------------------------------------------------
    # No bid/ask imbalance points are added here.

    # ------------------------------------------------------------
    # 1D BEARISH PENALTY
    # ------------------------------------------------------------
    if d1["is_bearish"]:
        buy_score = max(
            0,
            buy_score - 25
        )

    # ============================================================
    # BUY ALERTS
    # ============================================================
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
    # SELL / EXIT ALERTS
    #
    # IMPORTANT:
    # These are independent of active BUY state. They are spot
    # profit-taking / reduction alerts, not short-entry alerts.
    # ============================================================
    if exit_score >= 65:
        active_setups.append({
            "type": "SELL_CONFIRMED",
            "score": exit_score,
            "reasons": exit_factors
        })

    elif exit_score >= 45:
        active_setups.append({
            "type": "SELL_EARLY",
            "score": exit_score,
            "reasons": exit_factors
        })

    # ============================================================
    # TOP EXHAUSTION — INDEPENDENT OF SELL SCORE
    # ============================================================
    top_setup = evaluate_top_exhaustion(
        c4
    )

    if top_setup is not None:
        active_setups.append(
            top_setup
        )

    # ============================================================
    # BOTTOM EXHAUSTION — INDEPENDENT OF BUY SCORE
    # ============================================================
    bottom_setup = evaluate_bottom_exhaustion(
        c4
    )

    if bottom_setup is not None:
        active_setups.append(
            bottom_setup
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
        "_Direction uses completed 4H candles; live order-book data is context only._\n\n"
    )

    for symbol in full_watchlist:
        coin_name = symbol.replace(
            "USDT",
            ""
        )

        try:
            # ====================================================
            # COMPLETED 4H DATA
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
            # ORDER BOOK — CONTEXT ONLY
            # ====================================================
            ob = fetch_order_book(
                symbol,
                live_price,
                c4.get(
                    "avg_quote_volume_4h",
                    0.0
                )
            )

            # ====================================================
            # 1D CONTEXT
            # ====================================================
            d1 = fetch_1d_context(
                symbol
            )

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
                verdict, action_note = analyze_market_direction(
                    c4,
                    ob,
                    d1,
                    live_price=live_price
                )

                manual_summary += (
                    f"• *{coin_name}* "
                    f"(${p_str}) : *{verdict}*\n"
                    f"  ↳ {action_note}\n\n"
                )

            # ====================================================
            # SETUPS
            # ====================================================
            setups = evaluate_market_condition(
                c4,
                ob,
                d1,
                target_price_reference=live_price
            )

            # ====================================================
            # TELEGRAM ALERTS
            # ====================================================
            for setup in setups:
                stype = setup["type"]

                alerts_fired += 1

                reasons = setup.get(
                    "reasons",
                    []
                )

                reasons_text = (
                    "• "
                    + "\n• ".join(
                        reasons
                    )
                    if reasons
                    else "• No additional explanatory factors."
                )

                # =================================================
                # RELIEF SCALP
                # =================================================
                if stype == "RELIEF_SCALP":
                    msg = (
                        "⚡ *4H SHORT-TERM BOUNCE ALERT* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 🛡️ *Largest Visible Bid Wall:* "
                        f"${support_str}\n"

                        f"• 📉 *Distance below 4H 20-EMA:* "
                        f"{abs(setup['ema_stretch']):.1f}%\n"

                        f"• 📏 *EMA20 Distance:* "
                        f"{setup['ema_stretch_atr']:.1f} ATR\n"

                        f"• ⚡ *4H RSI:* "
                        f"{c4['rsi']:.1f}\n"

                        f"• 📊 *Volume:* "
                        f"{c4['vol_ratio']:.1f}x median | "
                        f"{c4['vol_percentile']:.0f}th percentile\n\n"

                        "*Why the bot flagged this:*\n"
                        f"{reasons_text}\n\n"

                        "*Possible bounce levels:*\n"
                        f"• 🎯 *TP1:* "
                        f"${format_price(setup['tp1'])} "
                        "(4H 20-EMA retest)\n"
                        f"• 🎯 *TP2:* "
                        f"${format_price(setup['tp2'])}\n"
                        f"• 🛑 *Invalidation:* "
                        f"4H close below "
                        f"${format_price(setup['stop'])}\n\n"

                        "📍 *Meaning:* This is a short-term spot bounce setup. "
                        "The daily trend is still bearish; this is not a claim that "
                        "the larger downtrend has ended."
                    )

                # =================================================
                # ACCUMULATION IGNITION
                # =================================================
                elif stype == "ACCUMULATION_IGNITION":
                    msg = (
                        "🚀 *4H ACCUMULATION IGNITION* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• 📈 *Ignition Volume:* "
                        f"{c4['vol_ratio']:.1f}x median | "
                        f"{c4['vol_percentile']:.0f}th percentile "
                        f"({c4['volume_regime']})\n"

                        f"• ⏳ *Suppression:* "
                        f"{c4['candles_below_ema20']} candles "
                        f"({c4['candles_below_ema20'] * 4}h) "
                        "below 20-EMA\n"

                        f"• 🛡️ *Largest Visible Bid Wall:* "
                        f"${support_str}\n"

                        f"• 💧 *Liquidity Context:* "
                        f"{ob.get('liquidity_label', 'unknown')} | "
                        f"Spread {ob.get('spread_pct', 0.0):.3f}%\n\n"

                        "*Why the bot flagged this:*\n"
                        f"{reasons_text}\n\n"

                        "*Tactical Target Map:*\n"
                        f"• 🎯 *TP1:* "
                        f"${format_price(setup['tp1'])} "
                        f"({setup['tp1_type']} | "
                        f"+{setup['tp1_pct']:.1f}%)\n"

                        f"• 🎯 *TP2:* "
                        f"${format_price(setup['tp2'])} "
                        f"({setup['tp2_type']} | "
                        f"+{setup['tp2_pct']:.1f}%)\n"

                        f"• 🎯 *TP3:* "
                        f"${format_price(setup['tp3'])} "
                        f"({setup['tp3_type']} | "
                        f"+{setup['tp3_pct']:.1f}%)\n"

                        f"• 🛑 *Invalidation:* "
                        f"4H close below "
                        f"${format_price(setup['stop'])}\n\n"

                        "📍 *Meaning:* This is a spot breakout/continuation setup. "
                        "Targets are resistance areas, not guaranteed prices."
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
                        meaning = (
                            "Multiple scoring conditions agree."
                        )
                    else:
                        header = (
                            "🟡 *EARLY BUYING WARNING*"
                        )
                        meaning = (
                            "Some bottom/entry conditions are present, "
                            "but confirmation is incomplete."
                        )

                    msg = (
                        f"{header} : {coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 🛡️ *Visible Buy Support:* "
                        f"${support_str}\n"

                        f"• 💧 *Visible Sell Liquidity Within 1%:* "
                        f"${ob['ask_depth_1pct']:,.0f}\n"

                        f"• ⚡ *4H RSI:* "
                        f"{c4['rsi']:.1f}\n"

                        f"• 📊 *BUY Score:* "
                        f"{setup['score']}\n"

                        f"• 📈 *Volume Regime:* "
                        f"{c4['volume_regime']} "
                        f"({c4['vol_percentile']:.0f}th percentile)\n"

                        f"• 💧 *Liquidity:* "
                        f"{ob.get('liquidity_label', 'unknown')} | "
                        f"Spread {ob.get('spread_pct', 0.0):.3f}%\n\n"

                        "*Why the bot flagged this:*\n"
                        f"{reasons_text}\n\n"

                        f"📍 *Meaning:* {meaning}\n"
                        "This is a spot-buying signal, not a guarantee that price cannot fall."
                    )

                # =================================================
                # SELL / EXIT ALERTS
                # =================================================
                elif stype in [
                    "SELL_CONFIRMED",
                    "SELL_EARLY"
                ]:
                    if stype == "SELL_CONFIRMED":
                        header = (
                            "🔴 *SELL / PROFIT-TAKING ALERT*"
                        )
                        meaning = (
                            "The frozen sell score is strongly elevated. "
                            "For spot holdings, this is an exit/reduction warning."
                        )
                    else:
                        header = (
                            "🟠 *EARLY SELL / PROFIT-TAKING WARNING*"
                        )
                        meaning = (
                            "Several sell-side conditions are present, but "
                            "this is earlier evidence rather than a confirmed reversal."
                        )

                    msg = (
                        f"{header} : {coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 🎯 *Visible Sell Area:* "
                        f"${resist_str}\n"

                        f"• ⚡ *4H RSI:* "
                        f"{c4['rsi']:.1f}\n"

                        f"• 📊 *SELL Score:* "
                        f"{setup['score']}\n"

                        f"• 📈 *Volume:* "
                        f"{c4['vol_ratio']:.1f}x median | "
                        f"{c4['vol_percentile']:.0f}th percentile\n"

                        f"• 💧 *Liquidity:* "
                        f"{ob.get('liquidity_label', 'unknown')} | "
                        f"Spread {ob.get('spread_pct', 0.0):.3f}%\n\n"

                        "*Why the bot flagged this:*\n"
                        f"{reasons_text}\n\n"

                        f"📍 *Meaning:* {meaning}\n"
                        "This is a spot exit/profit-taking alert, not a short-entry signal. "
                        "It can fire even if there was no earlier BUY alert."
                    )

                # =================================================
                # RALLY OVERHEATING
                # =================================================
                elif stype == "RALLY_OVERHEATING":
                    msg = (
                        "🟠 *RALLY RUNNING HOT* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 🎯 *Visible Sell Area:* "
                        f"${resist_str}\n"

                        f"• ⚡ *4H RSI:* "
                        f"{c4['rsi']:.1f}\n"

                        f"• 📏 *EMA200 Extension:* "
                        f"{c4['ema200_distance_atr']:+.1f} ATR\n\n"

                        "*Why the bot is warning:*\n"
                        f"{reasons_text}\n\n"

                        "⚠️ *Important:* This is an overheating warning, "
                        "not proof that the rally is over and not a standalone "
                        "short-entry signal."
                    )

                # =================================================
                # TOP EXHAUSTION DEVELOPING
                # =================================================
                elif stype == "TOP_EXHAUSTION_DEVELOPING":
                    msg = (
                        "🟡 *TOP EXHAUSTION DEVELOPING* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 🎯 *Visible Sell Area:* "
                        f"${resist_str}\n"

                        f"• ⚡ *4H RSI:* "
                        f"{c4['rsi']:.1f} "
                        f"(previous {c4['prev_rsi']:.1f})\n"

                        f"• 📉 *MACD Histogram:* "
                        f"{'weakening' if c4['macd_hist_weakening'] else 'not weakening'}\n"

                        f"• 🕯️ *Rejection:* "
                        f"{'present' if c4['bearish_rejection'] else 'not present'}\n\n"

                        "*What the bot sees:*\n"
                        f"{reasons_text}\n\n"

                        "⚠️ *Important:* This is not yet a confirmed 4H reversal. "
                        "For spot holders it is a profit-management/caution alert."
                    )

                # =================================================
                # TOP REVERSAL CONFIRMED
                # =================================================
                elif stype == "TOP_REVERSAL_CONFIRMED":
                    msg = (
                        "🔴 *TOP REVERSAL CONFIRMED* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 📉 *20-EMA Transition:* "
                        "Closed below 20-EMA\n"

                        f"• ⚡ *4H RSI:* "
                        f"{c4['rsi']:.1f} and turning down\n"

                        f"• 📉 *MACD Histogram:* "
                        "weakening\n"

                        f"• 🕯️ *Bearish Rejection:* "
                        "present\n"

                        f"• 🎯 *Visible Sell Area:* "
                        f"${resist_str}\n\n"

                        "*Why the bot flagged this:*\n"
                        f"{reasons_text}\n\n"

                        "📍 *Meaning:* The completed 4H candle now shows a "
                        "reversal structure. This is a spot profit-protection "
                        "signal, not a short-entry signal."
                    )

                # =================================================
                # SELLING PRESSURE EASING
                # =================================================
                elif stype == "SELLING_PRESSURE_EASING":
                    msg = (
                        "🔵 *SELLING PRESSURE EASING* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 🛡️ *Visible Buy Support:* "
                        f"${support_str}\n"

                        f"• ⚡ *4H RSI:* "
                        f"{c4['rsi']:.1f}\n"

                        f"• 📊 *Volume:* "
                        f"{c4['vol_ratio']:.1f}x median\n\n"

                        "*What the bot sees:*\n"
                        f"{reasons_text}\n\n"

                        "⚠️ *Important:* Early bottoming evidence is not a confirmed reversal. "
                        "Price can continue lower."
                    )

                # =================================================
                # BOTTOM EXHAUSTION DEVELOPING
                # =================================================
                elif stype == "BOTTOM_EXHAUSTION_DEVELOPING":
                    msg = (
                        "🟡 *BOTTOM EXHAUSTION DEVELOPING* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 🛡️ *Visible Buy Support:* "
                        f"${support_str}\n"

                        f"• ⚡ *4H RSI:* "
                        f"{c4['rsi']:.1f} "
                        f"(previous {c4['prev_rsi']:.1f})\n"

                        f"• 📈 *MACD Histogram:* "
                        f"{'strengthening' if c4['macd_hist_strengthening'] else 'not strengthening'}\n\n"

                        "*What the bot sees:*\n"
                        f"{reasons_text}\n\n"

                        "⚠️ *Important:* This is developing bottom evidence, "
                        "not a confirmed reversal yet."
                    )

                # =================================================
                # BOTTOM REVERSAL CONFIRMED
                # =================================================
                elif stype == "BOTTOM_REVERSAL_CONFIRMED":
                    msg = (
                        "🟢 *BOTTOM REVERSAL CONFIRMED* : "
                        f"{coin_name}\n\n"

                        f"• *Current Price:* "
                        f"${p_str}\n"

                        f"• *4H Candle Close:* "
                        f"${completed_4h_str}\n"

                        f"• 📈 *20-EMA Transition:* "
                        "Closed above 20-EMA\n"

                        f"• ⚡ *4H RSI:* "
                        f"{c4['rsi']:.1f} and turning up\n"

                        f"• 📈 *MACD Histogram:* "
                        "strengthening\n"

                        f"• 🕯️ *Bullish Rejection:* "
                        "present\n"

                        f"• 🛡️ *Visible Buy Support:* "
                        f"${support_str}\n\n"

                        "*Why the bot flagged this:*\n"
                        f"{reasons_text}\n\n"

                        "📍 *Meaning:* The completed 4H candle now shows a "
                        "bottom-reversal structure. This is evidence of reversal, "
                        "not a guarantee of continuation."
                    )

                else:
                    # Keep the scanner alive if a future setup type is added
                    # without a matching Telegram formatter.
                    logger.warning(
                        f"Unhandled setup type for {symbol}: {stype}"
                    )
                    continue

                send_telegram(
                    msg
                )

                time.sleep(1.0)

        except Exception as e:
            logger.error(
                f"Failed 4H analysis for {symbol}: {e}"
            )
            logger.debug(
                traceback.format_exc()
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

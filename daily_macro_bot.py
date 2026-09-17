import logging
import os
import time
import statistics

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# LOGGING SETUP
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger("DailyMacroBot")


# ============================================================
# ENVIRONMENT & EXECUTION MODE
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
RUN_MODE = os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch")


# ============================================================
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

# ============================================================
# RESILIENT HTTP SESSION
# ============================================================

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


# ============================================================
# FORMATTING HELPER
# ============================================================

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


# ============================================================
# TELEGRAM BROADCASTER
# ============================================================

def _send_single_telegram_chunk(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("Telegram credentials are missing.")
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
                    ).get(
                        "retry_after", 3
                    )
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

        except requests.RequestException as e:
            logger.warning(
                f"Telegram attempt {attempt}/3 failed: {e}"
            )

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


# ============================================================
# MATHEMATICAL ENGINES
# ============================================================

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

    # Fill warm-up section with the first valid RSI.
    for i in range(period):
        rsi[i] = rsi[period]

    return rsi


def calculate_ema(data, period):
    n = len(data)

    if n == 0:
        return []

    if n < period:
        return [data[0]] * n

    ema = [data[0]] * n

    seed = sum(data[:period]) / period

    ema[period - 1] = seed

    k = 2.0 / (period + 1)

    for i in range(period, n):
        ema[i] = (
            data[i] * k
            + ema[i - 1] * (1.0 - k)
        )

    for i in range(period - 1):
        ema[i] = seed

    return ema


def calculate_rma(data, period):
    n = len(data)

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

    tr = [0.0] * n

    if n == 0:
        return []

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


# ============================================================
# 1D MARKET DATA FETCH
# ============================================================

def fetch_1d_data(symbol, limit=450):

    url = (
        "https://data-api.binance.vision/api/v3/klines"
        f"?symbol={symbol}&interval=1d&limit={limit}"
    )

    res = HTTP.get(url, timeout=10)
    res.raise_for_status()

    raw = res.json()

    if not isinstance(raw, list):
        raise ValueError(
            f"{symbol}: Binance returned invalid kline data."
        )

    if len(raw) < 220:
        raise ValueError(
            f"{symbol}: insufficient daily history "
            f"({len(raw)} candles; minimum 220 required)."
        )

    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []

    for c in raw:

        if len(c) < 6:
            raise ValueError(
                f"{symbol}: malformed kline."
            )

        opens.append(float(c[1]))
        highs.append(float(c[2]))
        lows.append(float(c[3]))
        closes.append(float(c[4]))
        volumes.append(float(c[5]))

    if len(closes) < 220:
        raise ValueError(
            f"{symbol}: insufficient parsed daily candles."
        )

    # --------------------------------------------------------
    # CLOSED DAILY CANDLE ONLY
    # --------------------------------------------------------

    idx = len(closes) - 2

    if idx < 1:
        raise ValueError(
            f"{symbol}: no completed daily candle available."
        )

    # --------------------------------------------------------
    # INDICATORS
    # --------------------------------------------------------

    rsi_series = calculate_wilder_rsi(closes)

    _, _, macd_hist = calculate_macd(closes)

    ema200 = calculate_ema(closes, 200)

    atr = calculate_atr(
        highs,
        lows,
        closes
    )

    c_close = closes[idx]
    c_low = lows[idx]
    c_high = highs[idx]

    c_rsi = rsi_series[idx]
    c_hist = macd_hist[idx]
    c_atr = atr[idx]

    prev_hist = macd_hist[idx - 1]

    if c_atr <= 0:
        raise ValueError(
            f"{symbol}: invalid ATR."
        )

    if ema200[idx] <= 0:
        raise ValueError(
            f"{symbol}: invalid EMA200."
        )

    # --------------------------------------------------------
    # 200-DAY ROLLING STRUCTURAL EXTREMES
    # --------------------------------------------------------

    struct_start = max(
        0,
        idx - 200
    )

    recent_lows = lows[
        struct_start:idx
    ]

    recent_highs = highs[
        struct_start:idx
    ]

    struct_low = (
        min(recent_lows)
        if recent_lows
        else c_low
    )

    struct_high = (
        max(recent_highs)
        if recent_highs
        else c_high
    )

    # --------------------------------------------------------
    # RECENT CONFIRMED LOCAL SWING PIVOTS
    # --------------------------------------------------------

    local_lows = [
        (i, lows[i])
        for i in range(
            struct_start + 5,
            idx - 5
        )
        if lows[i] == min(
            lows[i - 5:i + 6]
        )
    ]

    local_highs = [
        (i, highs[i])
        for i in range(
            struct_start + 5,
            idx - 5
        )
        if highs[i] == max(
            highs[i - 5:i + 6]
        )
    ]

    if local_lows:
        r_low_idx, r_low = local_lows[-1]
    else:
        r_low_idx, r_low = (
            struct_start,
            struct_low
        )

    if local_highs:
        r_high_idx, r_high = local_highs[-1]
    else:
        r_high_idx, r_high = (
            struct_start,
            struct_high
        )

    # --------------------------------------------------------
    # ADVANCED DIVERGENCE CLASSIFICATION
    # --------------------------------------------------------

    # -------------------------
    # BULLISH
    # -------------------------

    c_low_is_lower_or_equal = (
        c_low <= r_low
    )

    c_low_is_prox = (
        c_low <= r_low + (0.5 * c_atr)
        and not c_low_is_lower_or_equal
    )

    rsi_is_higher = (
        c_rsi > rsi_series[r_low_idx]
    )

    macd_is_stronger = (
        c_hist > macd_hist[r_low_idx]
    )

    strong_rsi_bull_div = (
        c_low_is_lower_or_equal
        and rsi_is_higher
    )

    strong_macd_bull_div = (
        c_low_is_lower_or_equal
        and macd_is_stronger
    )

    early_bull_div = (
        c_low_is_prox
        and (
            rsi_is_higher
            or macd_is_stronger
        )
    )

    # -------------------------
    # BEARISH
    # -------------------------

    c_high_is_higher_or_equal = (
        c_high >= r_high
    )

    c_high_is_prox = (
        c_high >= r_high - (0.5 * c_atr)
        and not c_high_is_higher_or_equal
    )

    rsi_is_lower = (
        c_rsi < rsi_series[r_high_idx]
    )

    macd_is_weaker = (
        c_hist < macd_hist[r_high_idx]
    )

    strong_rsi_bear_div = (
        c_high_is_higher_or_equal
        and rsi_is_lower
    )

    strong_macd_bear_div = (
        c_high_is_higher_or_equal
        and macd_is_weaker
    )

    early_bear_div = (
        c_high_is_prox
        and (
            rsi_is_lower
            or macd_is_weaker
        )
    )

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    vol_window = volumes[
        max(0, idx - 20):idx
    ]

    if vol_window:
        vol_median = statistics.median(
            vol_window
        )
    else:
        vol_median = 1.0

    candle_range = c_high - c_low

    if candle_range <= 0:
        candle_range = 0.0

    return {
        "price": c_close,
        "structural_low": struct_low,
        "structural_high": struct_high,
        "rsi": c_rsi,
        "hist_slope_up": (c_hist > prev_hist),
        "hist_slope_down": (c_hist < prev_hist),
        "strong_rsi_bull_div": strong_rsi_bull_div,
        "strong_macd_bull_div": strong_macd_bull_div,
        "early_bull_div": early_bull_div,
        "strong_rsi_bear_div": strong_rsi_bear_div,
        "strong_macd_bear_div": strong_macd_bear_div,
        "early_bear_div": early_bear_div,
        "vol_ratio": (volumes[idx] / vol_median if vol_median > 0 else 1.0),
        "lower_wick": (
            (min(opens[idx], c_close) - c_low) / candle_range
            if candle_range > 0
            else 0.0
        ),
        "upper_wick": (
            (c_high - max(opens[idx], c_close)) / candle_range
            if candle_range > 0
            else 0.0
        ),
        "ema200_ext": (
            (c_close - ema200[idx]) / ema200[idx] * 100.0
        ),
        "atr": c_atr
    }


# ============================================================
# 1D MACRO SCORING ENGINE
# ============================================================

def evaluate_macro(d1):

    buy_score = 0
    exit_score = 0

    buy_factors = []
    exit_factors = []

    p = d1["price"]

    # ========================================================
    # MACRO BOTTOMING / ACCUMULATION CONDITIONS
    # BUY
    # ========================================================

    if (
        p - d1["structural_low"]
        <= 1.5 * d1["atr"]
    ):

        buy_score += 15

        buy_factors.append(
            "Price is near the "
            f"200D Rolling Structural Low "
            f"(${format_price(d1['structural_low'])})."
        )

        if d1["vol_ratio"] >= 1.5:

            buy_score += 10

            buy_factors.append(
                f"Abnormally high volume "
                f"({d1['vol_ratio']:.1f}x) near "
                "macro low (Potential Absorption)."
            )

    if d1["ema200_ext"] < -20.0:

        buy_score += 10

        buy_factors.append(
            "Severely discounted below "
            f"200D Moving Average "
            f"({d1['ema200_ext']:+.1f}%)."
        )

    if d1["rsi"] < 35:

        buy_score += 15

        buy_factors.append(
            f"Daily RSI deeply oversold "
            f"({d1['rsi']:.1f})."
        )

    if d1["strong_rsi_bull_div"]:

        buy_score += 15

        buy_factors.append(
            "Strong 1D RSI Bullish Divergence "
            "(Lower low with higher RSI)."
        )

    if d1["strong_macd_bull_div"]:

        buy_score += 10

        buy_factors.append(
            "Strong 1D MACD Histogram "
            "Bullish Divergence."
        )

    if (
        d1["early_bull_div"]
        and not (
            d1["strong_rsi_bull_div"]
            or d1["strong_macd_bull_div"]
        )
    ):

        buy_score += 8

        buy_factors.append(
            "Early 1D Bullish Proximity "
            "(Momentum improving near "
            "structural low)."
        )

    if d1["hist_slope_up"]:

        buy_score += 5

        buy_factors.append(
            "Daily MACD Histogram momentum "
            "is improving."
        )

    if d1["lower_wick"] >= 0.35:

        buy_score += 10

        buy_factors.append(
            "Strong daily lower-wick "
            "rejection / potential absorption."
        )

    # ========================================================
    # MACRO TOP / EXHAUSTION CONDITIONS
    # EXIT
    # ========================================================

    if (
        d1["structural_high"] - p
        <= 1.5 * d1["atr"]
    ):

        exit_score += 15

        exit_factors.append(
            "Price is near the "
            f"200D Rolling Structural High "
            f"(${format_price(d1['structural_high'])})."
        )

        if d1["vol_ratio"] >= 1.5:

            exit_score += 10

            exit_factors.append(
                f"Abnormally high volume "
                f"({d1['vol_ratio']:.1f}x) near "
                "macro high (Potential Distribution)."
            )

    if d1["ema200_ext"] > 35.0:

        exit_score += 10

        exit_factors.append(
            "Severely stretched above "
            f"200D Moving Average "
            f"({d1['ema200_ext']:+.1f}%)."
        )

    if d1["rsi"] > 65:

        exit_score += 15

        exit_factors.append(
            f"Daily RSI heavily overbought "
            f"({d1['rsi']:.1f})."
        )

    if d1["strong_rsi_bear_div"]:

        exit_score += 15

        exit_factors.append(
            "Strong 1D RSI Bearish Divergence "
            "(Higher high with lower RSI)."
        )

    if d1["strong_macd_bear_div"]:

        exit_score += 10

        exit_factors.append(
            "Strong 1D MACD Histogram "
            "Bearish Divergence."
        )

    if (
        d1["early_bear_div"]
        and not (
            d1["strong_rsi_bear_div"]
            or d1["strong_macd_bear_div"]
        )
    ):

        exit_score += 8

        exit_factors.append(
            "Early 1D Bearish Proximity "
            "(Momentum weakening near "
            "structural high)."
        )

    if d1["hist_slope_down"]:

        exit_score += 5

        exit_factors.append(
            "Daily MACD Histogram momentum "
            "is deteriorating."
        )

    if d1["upper_wick"] >= 0.35:

        exit_score += 10

        exit_factors.append(
            "Strong daily upper-wick rejection."
        )

    buy_sig = (
        "MACRO_BUY"
        if buy_score >= 40
        else None
    )

    exit_sig = (
        "MACRO_EXIT"
        if exit_score >= 40
        else None
    )

    return (
        buy_sig,
        buy_factors,
        exit_sig,
        exit_factors
    )


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

    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError
    ) as e:

        logger.error(
            f"Failed to fetch dynamic movers: {e}"
        )

        return [], []


# ============================================================
# MAIN WORKFLOW CONTROLLER
# ============================================================

def check_macro_market():

    logger.info(
        "Initializing 1D Macro Scanner..."
    )

    # --------------------------------------------------------
    # Dynamic top movers
    # --------------------------------------------------------

    top_l1, top_ai = get_dynamic_movers()

    full_watchlist = list(
        dict.fromkeys(
            CORE_WATCHLIST
            + top_l1
            + top_ai
        )
    )

    logger.info(
        f"Scanning {len(full_watchlist)} symbols."
    )

    alerts_fired = 0

    manual_summary = (
        "🌍 *[1D MACRO DIAGNOSTIC]* 🌍\n"
        "_Daily timeframe scan complete:_\n\n"
    )

    # ========================================================
    # SYMBOL LOOP
    # ========================================================

    for symbol in full_watchlist:

        coin_name = symbol.replace(
            "USDT",
            ""
        )

        try:

            # ------------------------------------------------
            # FETCH 1D DATA
            # ------------------------------------------------

            d1 = fetch_1d_data(symbol)

            # ------------------------------------------------
            # EVALUATE MACRO CONDITIONS
            # ------------------------------------------------

            (
                buy_sig,
                buy_factors,
                exit_sig,
                exit_factors
            ) = evaluate_macro(d1)

            p_str = format_price(
                d1["price"]
            )

            floor_str = format_price(
                d1["structural_low"]
            )

            peak_str = format_price(
                d1["structural_high"]
            )

            # ------------------------------------------------
            # INDEPENDENT STATUS DISPLAY
            # ------------------------------------------------

            status = "⚪ Neutral"

            if buy_sig and exit_sig:

                status = (
                    "🔵 Macro Bottoming + "
                    "🟣 Macro Exhaustion"
                )

            elif buy_sig:

                status = (
                    "🔵 Macro Bottoming Conditions"
                )

            elif exit_sig:

                status = (
                    "🟣 Macro Exhaustion Conditions"
                )

            manual_summary += (
                f"• *{coin_name}*: "
                f"${p_str} | "
                f"Status: {status} | "
                f"200D Rolling Low: ${floor_str}\n"
            )

            # =================================================
            # BUY ALERT
            # =================================================

            if buy_sig:

                alerts_fired += 1

                msg = (
                    "🔵 *1D MACRO BOTTOMING "
                    f"CONDITIONS* : {coin_name}\n\n"

                    f"• *Daily Closed Price:* "
                    f"${p_str}\n"

                    f"• 🛡️ *200D Rolling Structural Low:* "
                    f"${floor_str}\n"

                    f"• 📉 *Deviation from 200D Avg:* "
                    f"{d1['ema200_ext']:+.1f}%\n"

                    f"• ⚡ *Daily RSI:* "
                    f"{d1['rsi']:.1f}\n\n"

                    "*Why the bot flagged this:*\n"
                    "• "
                    + "\n• ".join(
                        buy_factors
                    )
                    + "\n\n"

                    "📍 *Context:* "
                    "1D macro bottoming/accumulation "
                    "conditions are present, with "
                    "increased confluence across "
                    "structural, momentum and "
                    "reversal measurements."
                )

                send_telegram(msg)


            # =================================================
            # EXIT ALERT
            # =================================================

            if exit_sig:

                alerts_fired += 1

                msg = (
                    "🟣 *1D MACRO EXHAUSTION "
                    f"CONDITIONS* : {coin_name}\n\n"

                    f"• *Daily Closed Price:* "
                    f"${p_str}\n"

                    f"• 🎯 *200D Rolling Structural High:* "
                    f"${peak_str}\n"

                    f"• 📈 *Deviation from 200D Avg:* "
                    f"{d1['ema200_ext']:+.1f}%\n"

                    f"• ⚡ *Daily RSI:* "
                    f"{d1['rsi']:.1f}\n\n"

                    "*Why the bot flagged this:*\n"
                    "• "
                    + "\n• ".join(
                        exit_factors
                    )
                    + "\n\n"

                    "📍 *Context:* "
                    "1D macro exhaustion conditions "
                    "are present, with increased "
                    "confluence across structural, "
                    "momentum and reversal measurements."
                )

                send_telegram(msg)


            # ------------------------------------------------
            # POLITELY SPACE TELEGRAM / API REQUESTS
            # ------------------------------------------------

            time.sleep(1.2)

        except Exception as e:

            logger.error(
                f"Failed analysis for {symbol}: {e}"
            )

            continue

    # ========================================================
    # MANUAL DIAGNOSTIC SUMMARY
    # ========================================================

    if RUN_MODE != "schedule":

        manual_summary += (
            "\n──────────────\n"
            f"✅ *1D Scan Complete.* "
            f"{len(full_watchlist)} coins checked. "
            f"{alerts_fired} macro alert(s) sent."
        )

        send_telegram(
            manual_summary
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    check_macro_market()

"""
Trade Assistant
---------------
Entry-based TP1 / TP2 / TP3 analysis for the existing 4H spot strategy.

This module is intentionally separate from bot.py so the existing scanner
logic is not changed.

Usage from another Python file:

    from trade_assistant import analyze_trade

    result = analyze_trade("SUIUSDT", 3.25)

"""

import math
import statistics
import requests


BINANCE_BASE = "https://data-api.binance.vision"

INTERVAL = "4h"
CANDLE_LIMIT = 500

# A resistance must normally be at least this far above price
MIN_RESISTANCE_DISTANCE_ATR = 0.50

# Resistance clustering tolerance
CLUSTER_ATR = 0.30
CLUSTER_PERCENT = 0.003

# Maximum target distance
MAX_TARGET_ATR = 5.0


# ============================================================
# HTTP
# ============================================================

SESSION = requests.Session()


def get_json(url, params=None):
    response = SESSION.get(
        url,
        params=params,
        timeout=20
    )
    response.raise_for_status()
    return response.json()


# ============================================================
# INDICATORS
# ============================================================

def calculate_ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(values[:period]) / period

    for value in values[period:]:
        ema = ((value - ema) * multiplier) + ema

    return ema


def calculate_rma(values, period):
    if len(values) < period:
        return None

    rma = sum(values[:period]) / period

    for value in values[period:]:
        rma = ((rma * (period - 1)) + value) / period

    return rma


def calculate_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(closes)):
        high = highs[i]
        low = lows[i]
        previous_close = closes[i - 1]

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        true_ranges.append(tr)

    return calculate_rma(true_ranges, period)


def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(symbol):
    symbol = symbol.upper().strip()

    if symbol.endswith("USDT"):
        return symbol

    return symbol + "USDT"


# ============================================================
# FETCH 4H DATA
# ============================================================

def fetch_4h_data(symbol):
    symbol = normalize_symbol(symbol)

    candles = get_json(
        f"{BINANCE_BASE}/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": INTERVAL,
            "limit": CANDLE_LIMIT
        }
    )

    if len(candles) < 220:
        raise ValueError(
            f"Not enough 4H candle data for {symbol}"
        )

    opens = [float(x[1]) for x in candles]
    highs = [float(x[2]) for x in candles]
    lows = [float(x[3]) for x in candles]
    closes = [float(x[4]) for x in candles]
    volumes = [float(x[5]) for x in candles]

    # Last candle may still be open.
    # Use the last COMPLETED candle for technical analysis.
    idx = len(closes) - 2

    close = closes[idx]
    open_price = opens[idx]
    high = highs[idx]
    low = lows[idx]
    volume = volumes[idx]

    atr = calculate_atr(
        highs[:idx + 1],
        lows[:idx + 1],
        closes[:idx + 1],
        14
    )

    ema20 = calculate_ema(closes[:idx + 1], 20)
    ema50 = calculate_ema(closes[:idx + 1], 50)
    ema200 = calculate_ema(closes[:idx + 1], 200)
    rsi = calculate_rsi(closes[:idx + 1], 14)

    # Volume baseline
    volume_start = max(0, idx - 20)
    previous_volumes = volumes[volume_start:idx]

    if previous_volumes:
        median_volume = statistics.median(previous_volumes)
    else:
        median_volume = volume

    volume_ratio = (
        volume / median_volume
        if median_volume > 0
        else 0
    )

    return {
        "symbol": symbol,
        "candles": candles,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "volumes": volumes,
        "idx": idx,
        "close": close,
        "open": open_price,
        "high": high,
        "low": low,
        "atr": atr,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
    }


# ============================================================
# CURRENT LIVE PRICE
# ============================================================

def get_live_price(symbol):
    symbol = normalize_symbol(symbol)

    data = get_json(
        f"{BINANCE_BASE}/api/v3/ticker/price",
        params={"symbol": symbol}
    )

    return float(data["price"])


# ============================================================
# RECENT SWING HIGHS
# ============================================================

def find_confirmed_swing_highs(highs, idx):
    """
    Find confirmed 4H swing highs.

    A high is considered a swing high when it is higher than the
    five candles on either side.

    Only COMPLETED candles are considered.
    """

    swings = []

    start = 5
    end = idx - 5

    for i in range(start, end):
        current = highs[i]

        left = highs[i - 5:i]
        right = highs[i + 1:i + 6]

        if current >= max(left) and current >= max(right):
            swings.append({
                "index": i,
                "price": current
            })

    return swings


# ============================================================
# RESISTANCE TARGET ENGINE
# ============================================================

def build_resistance_candidates(data, reference_price):
    highs = data["highs"]
    closes = data["closes"]
    idx = data["idx"]

    atr = data["atr"]

    candidates = []

    # --------------------------------------------------------
    # EMA50
    # --------------------------------------------------------

    if data["ema50"] is not None:
        if data["ema50"] > reference_price:
            candidates.append({
                "price": data["ema50"],
                "score": 3.0,
                "reason": "4H EMA50"
            })

    # --------------------------------------------------------
    # EMA200
    # --------------------------------------------------------

    if data["ema200"] is not None:
        if data["ema200"] > reference_price:
            candidates.append({
                "price": data["ema200"],
                "score": 3.0,
                "reason": "4H EMA200"
            })

    # --------------------------------------------------------
    # Recent consolidation high
    # --------------------------------------------------------

    recent_start = max(0, idx - 12)

    recent_high = max(
        highs[recent_start:idx + 1]
    )

    if recent_high > reference_price:
        candidates.append({
            "price": recent_high,
            "score": 4.0,
            "reason": "Recent 12-candle resistance"
        })

    # --------------------------------------------------------
    # Confirmed swing highs
    # --------------------------------------------------------

    swings = find_confirmed_swing_highs(
        highs,
        idx
    )

    for swing in swings:

        price = swing["price"]

        if price <= reference_price:
            continue

        age = idx - swing["index"]

        recency_bonus = 0

        if age <= 24:
            recency_bonus = 2.0
        elif age <= 48:
            recency_bonus = 1.5
        elif age <= 72:
            recency_bonus = 1.0
        else:
            recency_bonus = 0.5

        candidates.append({
            "price": price,
            "score": 5.0 + recency_bonus,
            "reason": f"Confirmed 4H swing high ({age} candles ago)"
        })

    return candidates


def cluster_resistances(candidates, atr):
    if not candidates:
        return []

    candidates = sorted(
        candidates,
        key=lambda x: x["price"]
    )

    clusters = []

    for candidate in candidates:

        placed = False

        for cluster in clusters:

            cluster_price = (
                sum(x["price"] for x in cluster)
                / len(cluster)
            )

            tolerance = max(
                atr * CLUSTER_ATR,
                cluster_price * CLUSTER_PERCENT
            )

            if abs(candidate["price"] - cluster_price) <= tolerance:

                cluster.append(candidate)
                placed = True
                break

        if not placed:
            clusters.append([candidate])

    results = []

    for cluster in clusters:

        price = (
            sum(x["price"] for x in cluster)
            / len(cluster)
        )

        score = sum(
            x["score"]
            for x in cluster
        )

        if len(cluster) >= 2:
            score += 2

        if len(cluster) >= 3:
            score += 2

        reasons = []

        for item in cluster:
            if item["reason"] not in reasons:
                reasons.append(item["reason"])

        results.append({
            "price": price,
            "score": score,
            "members": len(cluster),
            "reasons": reasons
        })

    return sorted(
        results,
        key=lambda x: x["price"]
    )


# ============================================================
# TARGET SELECTION
# ============================================================

def select_three_targets(data, reference_price):
    """
    Returns TP1 / TP2 / TP3 based on actual resistance.

    No arbitrary +4%, +8%, etc. targets are used when real
    resistance exists.

    ATR is used only for:
      - minimum meaningful distance
      - clustering
      - maximum target range
      - fallback targets
    """

    atr = data["atr"]

    if atr is None or atr <= 0:
        raise ValueError("ATR unavailable")

    candidates = build_resistance_candidates(
        data,
        reference_price
    )

    # Remove resistance that is too close to entry/current price.
    filtered = []

    minimum_distance = max(
        atr * MIN_RESISTANCE_DISTANCE_ATR,
        reference_price * 0.005
    )

    for candidate in candidates:

        distance = candidate["price"] - reference_price

        if distance < minimum_distance:
            continue

        filtered.append(candidate)

    clusters = cluster_resistances(
        filtered,
        atr
    )

    # Meaningful resistance:
    # normally >= 0.5 ATR away, unless it has strong confluence.
    meaningful = []

    for cluster in clusters:

        distance = cluster["price"] - reference_price

        if (
            distance >= atr * 0.50
            or cluster["score"] >= 8
        ):
            meaningful.append(cluster)

    # Only use resistance within the normal target search area.
    max_price = reference_price + (
        atr * MAX_TARGET_ATR
    )

    meaningful = [
        x for x in meaningful
        if x["price"] <= max_price
    ]

    meaningful.sort(
        key=lambda x: x["price"]
    )

    targets = []

    for cluster in meaningful:

        price = cluster["price"]

        if not targets:
            targets.append(cluster)
            continue

        previous = targets[-1]["price"]

        minimum_gap = max(
            atr * 0.25,
            reference_price * 0.0025
        )

        if price - previous >= minimum_gap:
            targets.append(cluster)

        if len(targets) == 3:
            break

    # --------------------------------------------------------
    # Fallbacks only when real resistance is insufficient.
    # --------------------------------------------------------

    fallback_multipliers = [
        1.0,
        2.5,
        4.0
    ]

    while len(targets) < 3:

        multiplier = fallback_multipliers[len(targets)]

        fallback_price = (
            reference_price +
            atr * multiplier
        )

        if targets:
            fallback_price = max(
                fallback_price,
                targets[-1]["price"] + atr * 0.75
            )

        if fallback_price > max_price:
            fallback_price = max_price

        targets.append({
            "price": fallback_price,
            "score": 0,
            "members": 0,
            "reasons": [
                f"ATR fallback ({multiplier:.1f} ATR)"
            ]
        })

        # Safety against impossible loops
        if len(targets) >= 3:
            break

    return targets[:3]


# ============================================================
# TRADE ANALYSIS
# ============================================================

def analyze_trade(symbol, entry_price):
    """
    Analyze an existing SPOT long entry.

    Entry price is used as the reference point for TP1/TP2/TP3.

    The analysis also reports:
      - current price
      - P/L %
      - distance from current price to targets
      - EMA context
      - RSI
      - ATR
      - volume
      - resistance reasons
    """

    symbol = normalize_symbol(symbol)

    try:
        entry_price = float(entry_price)
    except Exception:
        raise ValueError("Entry price must be a number")

    if entry_price <= 0:
        raise ValueError("Entry price must be greater than zero")

    data = fetch_4h_data(symbol)

    current_price = get_live_price(symbol)

    # Targets are based on the USER'S ENTRY.
    targets = select_three_targets(
        data,
        entry_price
    )

    tp1 = targets[0]["price"]
    tp2 = targets[1]["price"]
    tp3 = targets[2]["price"]

    # --------------------------------------------------------
    # P/L
    # --------------------------------------------------------

    pnl_pct = (
        (current_price - entry_price)
        / entry_price
    ) * 100

    # --------------------------------------------------------
    # Remaining upside to each target
    # --------------------------------------------------------

    def target_distance(price):
        return (
            (price - current_price)
            / current_price
        ) * 100

    # --------------------------------------------------------
    # Target profit from entry
    # --------------------------------------------------------

    def profit_from_entry(price):
        return (
            (price - entry_price)
            / entry_price
        ) * 100

    # --------------------------------------------------------
    # Position status
    # --------------------------------------------------------

    if current_price > tp3:
        status = "ABOVE TP3"
    elif current_price >= tp2:
        status = "BETWEEN TP2 AND TP3"
    elif current_price >= tp1:
        status = "BETWEEN TP1 AND TP2"
    elif current_price > entry_price:
        status = "PROFIT — BELOW TP1"
    else:
        status = "BELOW ENTRY"

    return {
        "symbol": symbol,

        "entry_price": entry_price,
        "current_price": current_price,

        "pnl_pct": pnl_pct,
        "status": status,

        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,

        "tp1_profit_pct": profit_from_entry(tp1),
        "tp2_profit_pct": profit_from_entry(tp2),
        "tp3_profit_pct": profit_from_entry(tp3),

        "tp1_distance_pct": target_distance(tp1),
        "tp2_distance_pct": target_distance(tp2),
        "tp3_distance_pct": target_distance(tp3),

        "atr": data["atr"],
        "rsi": data["rsi"],
        "ema20": data["ema20"],
        "ema50": data["ema50"],
        "ema200": data["ema200"],
        "volume_ratio": data["volume_ratio"],

        "target_details": targets
    }


# ============================================================
# TELEGRAM-FRIENDLY FORMATTER
# ============================================================

def format_trade_report(result):
    symbol = result["symbol"].replace("USDT", "")

    pnl_sign = "+" if result["pnl_pct"] >= 0 else ""

    lines = [
        f"📊 TRADE CHECK : {symbol}",
        "",
        f"💰 Entry: ${result['entry_price']:.8g}",
        f"📍 Current: ${result['current_price']:.8g}",
        "",
        f"📈 P/L: {pnl_sign}{result['pnl_pct']:.2f}%",
        f"📌 Status: {result['status']}",
        "",
        "🎯 TARGETS",
        "",
        (
            f"TP1: ${result['tp1']:.8g} "
            f"({result['tp1_profit_pct']:+.2f}% from entry)"
        ),
        (
            f"TP2: ${result['tp2']:.8g} "
            f"({result['tp2_profit_pct']:+.2f}% from entry)"
        ),
        (
            f"TP3: ${result['tp3']:.8g} "
            f"({result['tp3_profit_pct']:+.2f}% from entry)"
        ),
        "",
        "📐 FROM CURRENT PRICE",
        "",
        f"TP1: {result['tp1_distance_pct']:+.2f}%",
        f"TP2: {result['tp2_distance_pct']:+.2f}%",
        f"TP3: {result['tp3_distance_pct']:+.2f}%",
        "",
        "📊 4H CONTEXT",
        "",
        f"RSI: {result['rsi']:.1f}",
        f"ATR: ${result['atr']:.8g}",
        f"Volume: {result['volume_ratio']:.2f}x median",
        f"EMA20: ${result['ema20']:.8g}",
        f"EMA50: ${result['ema50']:.8g}",
        f"EMA200: ${result['ema200']:.8g}",
        "",
        "🧱 TARGET BASIS",
    ]

    for i, target in enumerate(
        result["target_details"],
        start=1
    ):
        reasons = ", ".join(
            target["reasons"]
        )

        if target["members"] > 0:
            lines.append(
                f"TP{i}: {reasons}"
            )
        else:
            lines.append(
                f"TP{i}: {reasons}"
            )

    return "\n".join(lines)


# ============================================================
# COMMAND-LINE TEST
# ============================================================

if __name__ == "__main__":

    import sys

    if len(sys.argv) != 3:
        print(
            "Usage: python trade_assistant.py SUI 3.25"
        )
        raise SystemExit(1)

    symbol = sys.argv[1]
    entry = float(sys.argv[2])

    result = analyze_trade(
        symbol,
        entry
    )

    print(
        format_trade_report(result)
    )

import requests
import os
import time

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RUN_MODE = os.environ.get('GITHUB_EVENT_NAME', 'workflow_dispatch') 

# 1. Permanent Core Halal Watchlist
CORE_WATCHLIST = [
    "SOLUSDT", "XRPUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT", 
    "XLMUSDT", "ALGOUSDT", "POLUSDT", "FETUSDT", "TONUSDT", 
    "AVAXUSDT", "NEARUSDT", "KITEUSDT"
]

# 2. Vetted Top-350 Halal L1 & L2 Infrastructure Pool (Strictly No Lending/Riba/Memes)
L1_L2_UNIVERSE = [
    "APTUSDT", "SEIUSDT", "INJUSDT", "TIAUSDT", "ARBUSDT", 
    "OPUSDT", "HBARUSDT", "ICPUSDT", "KASUSDT", "FTMUSDT", 
    "EGLDUSDT", "FLOWUSDT", "THETAUSDT", "STXUSDT", "ROSEUSDT",
    "PENDLEUSDT", "SPLUSDT", "COREUSDT", "CELOUSDT", "SKLUSDT"
]

# 3. Vetted Top-350 Halal AI Pool (Compute, Decentralized ML, Data Indexing)
AI_UNIVERSE = [
    "TAOUSDT", "FETUSDT", "RENDERUSDT", "GRTUSDT", "THETAUSDT", 
    "AKTUSDT", "ARKMUSDT", "GLMUSDT", "RLCUSDT", "IOUSDT", 
    "JASMYUSDT", "IQUSDT", "NMRUSDT", "PHBUSDT", "CTXCUSDT", 
    "TRACUSDT", "MDTUSDT", "NULSUSDT", "ROSEUSDT", "PHAUSDT"
]

def send_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    if len(msg) > 4000:
        chunks = msg.split("──────────────\n")
        current_chunk = ""
        for chunk in chunks:
            if len(current_chunk) + len(chunk) < 4000:
                current_chunk += chunk + "──────────────\n"
            else:
                requests.post(url, data={'chat_id': CHAT_ID, 'text': current_chunk, 'parse_mode': 'Markdown'})
                current_chunk = chunk + "──────────────\n"
                time.sleep(1)
        if current_chunk.strip():
            requests.post(url, data={'chat_id': CHAT_ID, 'text': current_chunk, 'parse_mode': 'Markdown'})
    else:
        requests.post(url, data={'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'})

def get_dynamic_market_leaders(top_n=5):
    """Scans L1/L2 and AI pools independently, picking top volume leaders under rank 350."""
    try:
        url = "https://data-api.binance.vision/api/v3/ticker/24hr"
        tickers = requests.get(url).json()
        
        # Sort L1/L2 Leaders
        l1_tickers = [t for t in tickers if t.get('symbol') in L1_L2_UNIVERSE and t.get('symbol') not in CORE_WATCHLIST]
        l1_tickers.sort(key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)
        top_l1 = [t['symbol'] for t in l1_tickers[:top_n]]
        
        # Sort AI Leaders
        ai_tickers = [t for t in tickers if t.get('symbol') in AI_UNIVERSE and t.get('symbol') not in CORE_WATCHLIST and t.get('symbol') not in top_l1]
        ai_tickers.sort(key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)
        top_ai = [t['symbol'] for t in ai_tickers[:top_n]]
        
        return top_l1, top_ai
    except:
        return [], []

def calculate_rsi_series(closes, period=14):
    if len(closes) < period + 1:
        return [50] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
        
    rsi_series = []
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_series.append(100 - (100 / (1 + (avg_gain / avg_loss))) if avg_loss != 0 else 100)
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi_val = 100 - (100 / (1 + (avg_gain / avg_loss))) if avg_loss != 0 else 100
        rsi_series.append(rsi_val)
        
    return rsi_series

def analyze_candles(symbol, interval, limit=200):
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    data = requests.get(url).json()
    
    if isinstance(data, dict) and 'code' in data:
        raise Exception("Symbol not found")
        
    opens = [float(c[1]) for c in data]
    highs = [float(c[2]) for c in data]
    lows = [float(c[3]) for c in data]
    closes = [float(c[4]) for c in data]
    volumes = [float(v[5]) for v in data]
    
    current_price = closes[-1]
    structural_low = min(lows[:-1])
    structural_high = max(highs[:-1])
    
    rsi_series = calculate_rsi_series(closes)
    current_rsi = rsi_series[-1]
    
    prev_high_idx = highs.index(max(highs[-40:-1])) if len(highs) > 40 else 0
    bearish_divergence = (current_price >= highs[prev_high_idx] * 0.98) and (current_rsi < rsi_series[prev_high_idx] - 5)
    
    candle_range = highs[-1] - lows[-1]
    upper_wick = highs[-1] - max(opens[-1], closes[-1])
    wick_rejection = (upper_wick / candle_range > 0.40) if candle_range > 0 else False
    
    avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 1
    vol_climax = volumes[-1] > (avg_vol * 1.6)
    
    return {
        "price": current_price,
        "structural_low": structural_low,
        "structural_high": structural_high,
        "rsi": current_rsi,
        "vol_climax": vol_climax,
        "wick_rejection": wick_rejection,
        "bearish_divergence": bearish_divergence
    }

def get_liquidity_walls(symbol, current_price):
    ob_url = f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=100"
    try:
        ob_data = requests.get(ob_url).json()
        bids = ob_data.get('bids', [])
        asks = ob_data.get('asks', [])
        
        total_bids = sum(float(b[1]) for b in bids) 
        total_asks = sum(float(a[1]) for a in asks) 
        ratio = total_bids / total_asks if total_asks > 0 else 1.0
        
        buy_wall_price = float(bids[0][0]) if bids else current_price
        max_bid = 0.0
        for b in bids:
            if float(b[1]) > max_bid:
                max_bid = float(b[1])
                buy_wall_price = float(b[0])
                
        return ratio, buy_wall_price
    except:
        return 1.0, current_price

def check_market():
    top_l1, top_ai = get_dynamic_market_leaders(top_n=5)
    full_watchlist = CORE_WATCHLIST + top_l1 + top_ai
    
    report_1d = "🌍 *[1D MACRO CYCLE OVERVIEW - 200D STRUCTURE]* 🌍\n\n"
    report_4h = "⚡ *[4H SWING REPORT - WITH 1D CONFLUENCE]* ⚡\n\n"
    
    if top_l1 or top_ai:
        clean_l1 = [c.replace("USDT", "") for c in top_l1]
        clean_ai = [c.replace("USDT", "") for c in top_ai]
        report_4h += (f"🌐 *Active L1/L2 Leaders:* {', '.join(clean_l1)}\n"
                      f"🤖 *Active AI Leaders:* {', '.join(clean_ai)}\n──────────────\n")

    for symbol in full_watchlist:
        coin_name = symbol.replace("USDT", "")
        
        # Visual badges for Telegram reports
        badge = "🔹"
        if symbol in top_l1: badge = "🌐"
        elif symbol in top_ai: badge = "🤖"

        try:
            d4 = analyze_candles(symbol, "4h", limit=200)
            d1 = analyze_candles(symbol, "1d", limit=200)
            ratio, buy_wall = get_liquidity_walls(symbol, d4["price"])
            
            price = d4["price"]
            pot_gain_4h = ((d4["structural_high"] - price) / price) * 100 if price > 0 else 0
            pot_gain_1d = ((d1["structural_high"] - price) / price) * 100 if price > 0 else 0

            # --- 1D MACRO EVALUATION ---
            if ratio >= 2.0 and price <= (d1["structural_low"] * 1.06):
                macro_status = "🟢 Major Cycle Accumulation Floor"
                is_1d_bullish = True
            elif d1["rsi"] >= 45 and ratio > 1.0:
                macro_status = "↗️ Leaning Bullish"
                is_1d_bullish = True
            elif d1["rsi"] < 40 or ratio < 0.7:
                macro_status = "↘️ Leaning Bearish"
                is_1d_bullish = False
            else:
                macro_status = "⚪ Neutral Consolidation"
                is_1d_bullish = None

            report_1d += (f"{badge} *{coin_name}* | Price: *${price}*\n"
                          f"• *Status:* {macro_status}\n"
                          f"• 🛡️ *Reversal Floor:* *${buy_wall}*\n"
                          f"• 🎯 *Macro Cycle Top (200D High):* *${d1['structural_high']}* (+{pot_gain_1d:.1f}%)\n"
                          f"──────────────\n")

            # --- 4H SWING EVALUATION ---
            is_4h_buy = (ratio >= 1.8 and price <= (d4["structural_low"] * 1.04)) or (d4["rsi"] < 35 and ratio > 1.4)
            is_4h_exit = (price >= d4["structural_high"] * 0.97) and (
                (d4["vol_climax"] and d4["wick_rejection"]) or 
                d4["bearish_divergence"] or 
                (ratio <= 0.55 and d4["rsi"] > 68)
            )

            if is_4h_buy:
                if is_1d_bullish is True:
                    swing_setup = "🟡 Buy Dip Setting Up"
                    confluence = "⭐ *HIGH CONFLUENCE* (Supported by 1D)"
                    action = f"Limit Buy near ${buy_wall}"
                else:
                    swing_setup = "🟡 Counter-Trend Bounce"
                    confluence = "⚠️ *LOW CONFLUENCE* (1D weak, high trap risk)"
                    action = "Caution. Wait for 1D stabilization."
            elif is_4h_exit:
                swing_setup = "🔴 Structural Rejection / Top"
                confluence = "🎯 *CONFIRMED EXIT* (Sellers Absorbing at Highs)"
                action = f"Secure spot profits near ${price}"
            else:
                swing_setup = "⚪ Range Trading"
                confluence = "Neutral"
                action = "No structural setup. Hold/Wait."

            report_4h += (f"{badge} *{coin_name}* | Price: *${price}*\n"
                          f"• *4H Setup:* {swing_setup}\n"
                          f"• *Confluence:* {confluence}\n"
                          f"• 🛡️ *Entry Floor:* *${buy_wall}*\n"
                          f"• 🎯 *Target (33D High):* *${d4['structural_high']}* (+{pot_gain_4h:.1f}%)\n"
                          f"• *Action:* {action}\n"
                          f"──────────────\n")

            # --- AUTOMATED CRITICAL ALERTS ---
            alert_tag = ""
            if symbol in top_l1: alert_tag = " [L1/L2 SECTOR]"
            elif symbol in top_ai: alert_tag = " [AI SECTOR]"

            if price <= (d1["structural_low"] * 1.03) and d1["vol_climax"] and ratio >= 2.0:
                send_alert(
                    f"🟢 *[1D MACRO BUY{alert_tag}] : {coin_name}*\n\n"
                    f"• *Current Price:* ${price}\n"
                    f"• 🛡️ *Accumulation Floor:* ${buy_wall}\n"
                    f"• 🎯 *Macro Cycle Target:* ${d1['structural_high']} (+{pot_gain_1d:.1f}%)\n\n"
                    f"📍 *Execution:* Macro capitulation absorbed on 200-day structure. High-conviction entry."
                )

            elif is_4h_buy and d4["vol_climax"] and (is_1d_bullish is True):
                send_alert(
                    f"🟡 *[4H SPOT SWING BUY{alert_tag}] : {coin_name}*\n\n"
                    f"• *Current Price:* ${price}\n"
                    f"• 1D Confluence: ⭐ HIGH\n"
                    f"• 🛡️ *Entry Floor:* ${buy_wall}\n"
                    f"• 🎯 *Swing Target (33D High):* ${d4['structural_high']} (+{pot_gain_4h:.1f}%)\n\n"
                    f"📍 *Execution:* Pullback absorbed into institutional buy wall. Place Limit Buy near *${buy_wall}*."
                )

            elif is_4h_exit:
                reasons = []
                if d4["bearish_divergence"]: reasons.append("Bearish RSI Divergence")
                if d4["wick_rejection"]: reasons.append("Upper Wick Rejection")
                if ratio <= 0.55: reasons.append("Heavy Sell Walls")
                
                send_alert(
                    f"🔴 *[4H SWING EXIT / TAKE PROFIT{alert_tag}] : {coin_name}*\n\n"
                    f"• *Exit Price:* ${price}\n"
                    f"• *Range High Tested:* ${d4['structural_high']}\n"
                    f"• *Exhaustion Signals:* {', '.join(reasons)}\n\n"
                    f"📍 *Execution:* Structural high reached with active seller absorption. Lock in spot profits!"
                )

            time.sleep(1.5)
            
        except Exception:
            report_1d += f"{badge} *{coin_name}* | ⚠️ Data unavailable\n──────────────\n"
            report_4h += f"{badge} *{coin_name}* | ⚠️ Data unavailable\n──────────────\n"
            continue 

    if RUN_MODE != 'schedule':
        send_alert(report_1d)
        time.sleep(2)
        send_alert(report_4h)

if __name__ == "__main__":
    check_market()

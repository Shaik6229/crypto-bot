import requests
import os
import time

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RUN_MODE = os.environ.get('GITHUB_EVENT_NAME', 'workflow_dispatch') 

WATCHLIST = [
    "SOLUSDT", "XRPUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT", 
    "XLMUSDT", "ALGOUSDT", "POLUSDT", "FETUSDT", "TONUSDT", 
    "AVAXUSDT", "NEARUSDT", "KITEUSDT"
]

def send_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'})

def analyze_candles(symbol, interval):
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit=21"
    data = requests.get(url).json()
    
    if isinstance(data, dict) and 'code' in data:
        raise Exception("Symbol not found")
        
    closes = [float(c[4]) for c in data]
    volumes = [float(v[5]) for v in data]
    lows = [float(c[3]) for c in data[:-1]]
    highs = [float(c[2]) for c in data[:-1]]
    
    recent_low = min(lows) if lows else closes[-1]
    recent_high = max(highs) if highs else closes[-1]
    
    # Calculate RSI
    gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
    losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
    avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else 0
    avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else 0
    rsi = 100 - (100 / (1 + (avg_gain / avg_loss))) if avg_loss != 0 else 50

    # Volume Climax check
    avg_vol = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 1
    vol_climax = volumes[-1] > (avg_vol * 1.5)
    
    return vol_climax, closes[-1], recent_low, recent_high, rsi

def get_liquidity_walls(symbol):
    ob_url = f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=100"
    ob_data = requests.get(ob_url).json()
    
    bids = ob_data.get('bids', [])
    asks = ob_data.get('asks', [])
    
    total_bids = sum(float(b[1]) for b in bids) 
    total_asks = sum(float(a[1]) for a in asks) 
    ratio = total_bids / total_asks if total_asks > 0 else 1.0
    
    # Locate largest single limit buy order (Support floor)
    buy_wall_price = float(bids[0][0]) if bids else 0.0
    max_bid = 0.0
    for b in bids:
        if float(b[1]) > max_bid:
            max_bid = float(b[1])
            buy_wall_price = float(b[0])
            
    # Locate largest single limit sell order (Resistance ceiling)
    sell_wall_price = float(asks[0][0]) if asks else 0.0
    max_ask = 0.0
    for a in asks:
        if float(a[1]) > max_ask:
            max_ask = float(a[1])
            sell_wall_price = float(a[0])
            
    return ratio, buy_wall_price, sell_wall_price

def check_market():
    # Reports are split into two clean, dedicated messages
    report_1d = "🌍 *[1D MACRO CYCLE OVERVIEW]* 🌍\n_Higher-Timeframe Big Money Trend:_\n\n"
    report_4h = "⚡ *[4H SWING REPORT - WITH 1D CONFLUENCE]* ⚡\n_Tactical setups checked against the Daily trend:_\n\n"
    
    for symbol in WATCHLIST:
        coin_name = symbol.replace("USDT", "")
        try:
            vol_4h, price, low_4h, high_4h, rsi_4h = analyze_candles(symbol, "4h")
            vol_1d, _, low_1d, high_1d, rsi_1d = analyze_candles(symbol, "1d")
            ratio, buy_wall, sell_wall = get_liquidity_walls(symbol)
            
            # --- 1. DETERMINE 1D MACRO STATUS ---
            if ratio >= 2.0 and price <= (low_1d * 1.05):
                macro_status = "🟢 Strong Accumulation Floor"
                macro_explanation = "Whales defending the daily chart with heavy cash walls."
                is_1d_bullish = True
            elif ratio <= 0.5 and price >= (high_1d * 0.95):
                macro_status = "🔴 Major Distribution Top"
                macro_explanation = "Whales placing heavy sell walls to cash out."
                is_1d_bullish = False
            elif ratio > 1.25 and rsi_1d >= 45:
                macro_status = "↗️ Leaning Bullish"
                macro_explanation = "Daily buyers in control, order book supportive."
                is_1d_bullish = True
            elif ratio < 0.75 or rsi_1d < 40:
                macro_status = "↘️ Leaning Bearish"
                macro_explanation = "Daily chart weak; downward drift active."
                is_1d_bullish = False
            else:
                macro_status = "⚪ Neutral Range"
                macro_explanation = "Consolidating. No clear daily breakout."
                is_1d_bullish = None

            report_1d += (f"🔹 *{coin_name}* | Current: *${price}*\n"
                         f"• *1D Status:* {macro_status}\n"
                         f"• 🛡️ *Big Money Floor:* *${buy_wall}*\n"
                         f"• 🎯 *Target Exit Zone:* *${sell_wall}*\n"
                         f"• *Outlook:* {macro_explanation}\n"
                         f"──────────────\n")

            # --- 2. DETERMINE 4H SWING STATUS & 1D CONFLUENCE ---
            is_4h_buy_setup = (ratio >= 1.8 and price <= (low_4h * 1.03)) or (rsi_4h < 35 and ratio > 1.4)
            is_4h_exit_setup = (ratio <= 0.55 and price >= (high_4h * 0.97)) or (rsi_4h > 65 and ratio < 0.7)

            if is_4h_buy_setup:
                if is_1d_bullish is True:
                    swing_setup = "🟡 Buy Dip Setting Up"
                    confluence = "⭐ *HIGH CONFLUENCE* (1D trend supports 4H entry)"
                    swing_action = f"Place Spot Buy near ${buy_wall}"
                else:
                    swing_setup = "🟡 Short-term Bounce"
                    confluence = "⚠️ *LOW CONFLUENCE* (1D is weak, risk of trap)"
                    swing_action = "Risky to buy. Wait for 1D stability."
            elif is_4h_exit_setup:
                swing_setup = "🟠 Take Profit Zone"
                confluence = "🎯 *SELL CONFLUENCE* (4H resistance hit)"
                swing_action = f"Lock in swing profits near ${sell_wall}"
            else:
                swing_setup = "⚪ Moving Sideways"
                confluence = "Neutral"
                swing_action = "No clean 4H entry. Be patient."

            report_4h += (f"🔹 *{coin_name}* | Current: *${price}*\n"
                         f"• *4H Setup:* {swing_setup}\n"
                         f"• *1D Confluence:* {confluence}\n"
                         f"• 🛡️ *Reversal Floor:* *${buy_wall}*\n"
                         f"• 🎯 *Swing Target:* *${sell_wall}*\n"
                         f"• *Execution:* {swing_action}\n"
                         f"──────────────\n")

            # --- 3. AUTOMATED ALERTS (Strict Confluence Required) ---
            # 1D Macro Bottom Alert
            if price <= (low_1d * 1.03) and vol_1d and ratio >= 2.0:
                send_alert(
                    f"🟢 *[1D MACRO BUY] : {coin_name}*\n\n"
                    f"• *Current Price:* ${price}\n"
                    f"• *Timeframe:* 1-Day Macro Capitulation\n"
                    f"• 🛡️ *Major Reversal Floor:* ${buy_wall}\n"
                    f"• 🎯 *Target Cycle Exit:* ${sell_wall}\n\n"
                    f"📍 *Execution:* Market Maker trap on Daily chart. Massive spot accumulation wall detected near *${buy_wall}*."
                )

            # 1D Macro Top Alert
            elif price >= (high_1d * 0.97) and vol_1d and ratio <= 0.5:
                send_alert(
                    f"🔴 *[1D MACRO EXIT] : {coin_name}*\n\n"
                    f"• *Current Price:* ${price}\n"
                    f"• *Timeframe:* 1-Day Macro Top\n"
                    f"• 🎯 *Target Exit Ceiling:* ${sell_wall}\n\n"
                    f"📍 *Execution:* Whales stacking massive sell walls at resistance. Sell spot near *${sell_wall}* and lock in cycle profits!"
                )

            # 4H Tactical Swing Buy (ONLY triggers if 1D does NOT oppose it!)
            elif is_4h_buy_setup and vol_4h and (is_1d_bullish is not False):
                send_alert(
                    f"🟡 *[4H SPOT SWING BUY] : {coin_name}*\n\n"
                    f"• *Current Price:* ${price}\n"
                    f"• *Timeframe:* 4-Hour Tactical Support\n"
                    f"• *1D Confluence:* ⭐ HIGH (Daily trend supports entry)\n"
                    f"• 🛡️ *Reversal Floor:* ${buy_wall}\n"
                    f"• 🎯 *Swing Target:* ${sell_wall}\n\n"
                    f"📍 *Execution:* Tactical pullback absorbed by limit orders. Place Spot Limit Buy near *${buy_wall}*."
                )

            # 4H Tactical Swing Exit
            elif is_4h_exit_setup and vol_4h:
                send_alert(
                    f"🟠 *[4H SWING EXIT] : {coin_name}*\n\n"
                    f"• *Current Price:* ${price}\n"
                    f"• *Timeframe:* 4-Hour Resistance Zone\n"
                    f"• 🎯 *Sell Wall Ceiling:* ${sell_wall}\n\n"
                    f"📍 *Execution:* 4H rally exhaustion. Place Spot Limit Sell near *${sell_wall}* to bank swing profit."
                )

            time.sleep(1.5)
            
        except Exception:
            report_1d += f"🔹 *{coin_name}* | ⚠️ Data unavailable\n──────────────\n"
            report_4h += f"🔹 *{coin_name}* | ⚠️ Data unavailable\n──────────────\n"
            continue 

    # Send the two separate reports if triggered manually
    if RUN_MODE != 'schedule':
        send_alert(report_1d)
        time.sleep(2) # Brief pause so Telegram delivers Message 1 first, then Message 2
        send_alert(report_4h)

if __name__ == "__main__":
    check_market()

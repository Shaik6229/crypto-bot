import requests
import os
import time

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
# Detects if you clicked "Run Workflow" (manual) or if it's the 2-hour timer (schedule)
RUN_MODE = os.environ.get('GITHUB_EVENT_NAME', 'workflow_dispatch') 

WATCHLIST = [
    "SOLUSDT", "XRPUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT", 
    "XLMUSDT", "ALGOUSDT", "POLUSDT", "FETUSDT", "TONUSDT", 
    "AVAXUSDT", "NEARUSDT", "KITEUSDT"
]

def send_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'})

def analyze_timeframe(symbol, interval):
    # FIXED: Uses Binance's global data URL to bypass US cloud IP blocks
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit=21"
    data = requests.get(url).json()
    
    # Catch missing coins (like KITE not being on Spot)
    if isinstance(data, dict) and 'code' in data:
        raise Exception("Symbol not found")
        
    closes = [float(c[4]) for c in data]
    volumes = [float(v[5]) for v in data]
    
    # Calculate Institutional Trap Zones
    lows = [float(c[3]) for c in data[:-1]]
    highs = [float(c[2]) for c in data[:-1]]
    recent_low = min(lows) if lows else closes[-1]
    recent_high = max(highs) if highs else closes[-1]
    
    avg_vol = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 1
    vol_climax = volumes[-1] > (avg_vol * 1.5)
    
    return vol_climax, closes[-1], recent_low, recent_high

def get_spot_liquidity(symbol):
    # FIXED: Uses Binance's global data URL to bypass US cloud IP blocks
    ob_url = f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}&limit=100"
    ob_data = requests.get(ob_url).json()
    
    bids = sum(float(b[1]) for b in ob_data.get('bids', [])) 
    asks = sum(float(a[1]) for a in ob_data.get('asks', [])) 
    ratio = bids / asks if asks > 0 else 1.0
    return ratio, bids, asks

def check_market():
    report = "📊 *LIVE MARKET DIAGNOSTIC* 📊\n_Institutional Order Flow Predictions_\n\n"
    
    for symbol in WATCHLIST:
        try:
            vol_4h, price, low_4h, high_4h = analyze_timeframe(symbol, "4h")
            vol_1d, _, low_1d, high_1d = analyze_timeframe(symbol, "1d")
            ratio, bids, asks = get_spot_liquidity(symbol)
            
            # --- PREDICTIVE AI LOGIC ---
            if ratio >= 2.0 and price <= (low_1d * 1.05):
                prediction = "🟢 *High Probability UP* (Whale Absorption at Support)"
            elif ratio <= 0.5 and price >= (high_1d * 0.95):
                prediction = "🔴 *High Probability DOWN* (Whale Distribution at Resistance)"
            elif ratio > 1.3:
                prediction = "↗️ *Leaning Bullish* (Bids outweighing Asks)"
            elif ratio < 0.7:
                prediction = "↘️ *Leaning Bearish* (Asks outweighing Bids)"
            else:
                prediction = "⚪ *Neutral Chop* (Wait for clear institutional footprint)"
                
            report += (f"🔹 *{symbol}* | Price: ${price}\n"
                       f"• *Prediction:* {prediction}\n"
                       f"• Limit Ratio: {ratio:.2f}x\n"
                       f"──────────────\n")
            
            # --- AUTOMATED ALERTS (Only triggers on absolute setups) ---
            if price <= (low_1d * 1.03) and vol_1d and ratio >= 2.0:
                send_alert(f"🟢 *[1D PERFECT ENTRY] : {symbol}*\n\nMarket Maker Trap detected! Retail panic selling into institutional buy wall.\n\n• *Price:* ${price}\n• *Absorption Ratio:* {ratio:.2f}x\n• *Spot Bids Defending:* {bids:.0f}")
                
            elif price >= (high_1d * 0.97) and vol_1d and ratio <= 0.5:
                send_alert(f"🔴 *[1D PERFECT EXIT] : {symbol}*\n\nMarket Maker Distribution! Whales are dumping via heavy limit sell walls.\n\n• *Price:* ${price}\n• *Distribution Ratio:* {(1/ratio):.2f}x\n• *Spot Asks Blocking:* {asks:.0f}")

            time.sleep(1.5) # Spacing requests to be safe
            
        except Exception:
            # If a coin fails (like KITE on Spot), it reports it but safely moves on to the next one!
            report += f"🔹 *{symbol}* | ⚠️ Data Not Found on Spot\n──────────────\n"
            continue 

    if RUN_MODE != 'schedule':
        send_alert(report)

if __name__ == "__main__":
    check_market()

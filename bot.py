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
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=21"
    klines = requests.get(url).json()
    closes = [float(c[4]) for c in klines]
    volumes = [float(v[5]) for v in klines]
    
    # Calculate Institutional Trap Zones (20-period highs and lows)
    lows = [float(c[3]) for c in klines[:-1]]
    highs = [float(c[2]) for c in klines[:-1]]
    recent_low = min(lows)
    recent_high = max(highs)
    
    avg_vol = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 1
    vol_climax = volumes[-1] > (avg_vol * 1.5)
    
    return vol_climax, closes[-1], recent_low, recent_high

def get_spot_liquidity(symbol):
    ob_url = f"https://api.binance.com/api/v3/depth?symbol={symbol}&limit=100"
    ob_data = requests.get(ob_url).json()
    bids = sum(float(b[1]) for b in ob_data['bids']) 
    asks = sum(float(a[1]) for a in ob_data['asks']) 
    ratio = bids / asks if asks > 0 else 1.0
    return ratio, bids, asks

def check_market():
    report = "📊 *LIVE MARKET DIAGNOSTIC* 📊\n_Institutional Order Flow Predictions_\n\n"
    
    for symbol in WATCHLIST:
        try:
            vol_4h, price, low_4h, high_4h = analyze_timeframe(symbol, "4h")
            vol_1d, _, low_1d, high_1d = analyze_timeframe(symbol, "1d")
            ratio, bids, asks = get_spot_liquidity(symbol)
            
            # --- 1. PREDICTIVE AI LOGIC (For Manual Reports) ---
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
            
            # --- 2. AUTOMATED INSTITUTIONAL TRAP ALERTS (Strict Entry/Exit) ---
            # BUY TRIGGER: Price is pushed to 20-day lows + Volume Spikes (Retail panic) + Massive Buy Wall absorbs it
            if price <= (low_1d * 1.03) and vol_1d and ratio >= 2.0:
                send_alert(f"🟢 *[1D PERFECT ENTRY] : {symbol}*\n\n"
                           f"Market Maker Trap detected! Retail is panic selling into a massive institutional buy wall at support.\n\n"
                           f"• *Price:* ${price}\n• *Absorption Ratio:* {ratio:.2f}x\n"
                           f"• *Spot Bids Defending:* {bids:.0f}")
                
            # SELL TRIGGER: Price is pushed to 20-day highs + Volume Spikes (Retail FOMO) + Massive Sell Wall blocks it
            elif price >= (high_1d * 0.97) and vol_1d and ratio <= 0.5:
                send_alert(f"🔴 *[1D PERFECT EXIT] : {symbol}*\n\n"
                           f"Market Maker Distribution! Retail is buying the breakout, but whales are dumping via heavy limit sell walls.\n\n"
                           f"• *Price:* ${price}\n• *Distribution Ratio:* {(1/ratio):.2f}x\n"
                           f"• *Spot Asks Blocking:* {asks:.0f}")

            time.sleep(1) 
            
        except Exception:
            continue 

    # Only send the massive multi-coin prediction report if you ran it manually
    if RUN_MODE != 'schedule':
        send_alert(report)

if __name__ == "__main__":
    check_market()

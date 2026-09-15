import requests
import os
import time

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

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
    
    gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
    losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
    avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else 0
    avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else 0
    rsi = 100 - (100 / (1 + (avg_gain / avg_loss))) if avg_loss != 0 else 50
    
    avg_vol = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 1
    vol_climax = volumes[-1] > (avg_vol * 1.5)
    
    return rsi, vol_climax, closes[-1]

def get_spot_liquidity(symbol):
    # Only fetches pure Spot market L2 order book data
    ob_url = f"https://api.binance.com/api/v3/depth?symbol={symbol}&limit=100"
    ob_data = requests.get(ob_url).json()
    
    bids = sum(float(b[1]) for b in ob_data['bids']) # Total resting Spot Buy limits
    asks = sum(float(a[1]) for a in ob_data['asks']) # Total resting Spot Sell limits
    ratio = bids / asks if asks > 0 else 1.0
    
    return ratio, bids, asks

def check_market():
    for symbol in WATCHLIST:
        try:
            rsi_4h, vol_4h, price = analyze_timeframe(symbol, "4h")
            rsi_1d, vol_1d, _ = analyze_timeframe(symbol, "1d")
            
            ratio, bids, asks = get_spot_liquidity(symbol)
            
            # --- 1D MACRO CYCLE ALERTS ---
            if rsi_1d < 35 and vol_1d and ratio >= 2.0:
                msg = (f"🟢 *[1D SPOT BUY] Macro Bottom : {symbol}*\n\n"
                       f"Massive Spot Limit Buy walls are absorbing panic selling. Strong entry zone.\n\n"
                       f"• *Current Price:* ${price}\n"
                       f"• *Buy/Sell Wall Ratio:* {ratio:.2f}x\n"
                       f"• *Resting Buy Orders:* {bids:.0f} coins\n"
                       f"• *Volume Climax:* ✅ Confirmed")
                send_alert(msg)
                
            elif rsi_1d > 65 and vol_1d and ratio <= 0.5:
                msg = (f"🔴 *[1D SPOT EXIT] Macro Top : {symbol}*\n\n"
                       f"Massive Spot Limit Sell walls are blocking upward momentum. Book your profits here.\n\n"
                       f"• *Current Price:* ${price}\n"
                       f"• *Sell/Buy Wall Ratio:* {(1/ratio):.2f}x\n"
                       f"• *Resting Sell Orders:* {asks:.0f} coins\n"
                       f"• *Volume Climax:* ✅ Confirmed")
                send_alert(msg)

            # --- 4H TACTICAL SWING ALERTS ---
            elif rsi_4h < 33 and vol_4h and ratio >= 2.0:
                msg = (f"🟡 *[4H SPOT BUY] Swing Bottom : {symbol}*\n\n"
                       f"Tactical pullback exhaustion. Limit buyers defending the 4H support zone.\n\n"
                       f"• *Current Price:* ${price}\n"
                       f"• *Buy/Sell Wall Ratio:* {ratio:.2f}x\n"
                       f"• *Volume Climax:* ✅ Confirmed")
                send_alert(msg)
                
            elif rsi_4h > 67 and vol_4h and ratio <= 0.5:
                msg = (f"🟠 *[4H SPOT EXIT] Swing Top : {symbol}*\n\n"
                       f"Tactical rally exhaustion. Limit sellers defending resistance. Good place to secure profits.\n\n"
                       f"• *Current Price:* ${price}\n"
                       f"• *Sell/Buy Wall Ratio:* {(1/ratio):.2f}x\n"
                       f"• *Volume Climax:* ✅ Confirmed")
                send_alert(msg)

            time.sleep(1.5) 
            
        except Exception:
            continue 

if __name__ == "__main__":
    check_market()

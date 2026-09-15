import requests
import os

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
SYMBOL = 'BTCUSDT' # You can change this to ETHUSDT, SOLUSDT, etc.

def send_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'})

def check_market():
    try:
        # Fetch Top 100 Orderbook Levels from free Binance API
        ob_url = f"https://api.binance.com/api/v3/depth?symbol={SYMBOL}&limit=100"
        ob_data = requests.get(ob_url).json()
        
        bids = sum(float(b[1]) for b in ob_data['bids']) # Resting Buy Limits
        asks = sum(float(a[1]) for a in ob_data['asks']) # Resting Sell Limits
        ratio = bids / asks if asks > 0 else 1
        
        # If Limit Buy orders are 2.5x larger than Limit Sells -> Macro Bottom Absorption
        if ratio > 2.5:
            msg = f"🟢 *MACRO BOTTOM ALERT ({SYMBOL})*\n\nMassive Limit Buy walls detected. Institutional absorption likely.\n\n• *Bid/Ask Ratio:* {ratio:.2f}x\n• *Buy Wall Support:* {bids:.2f} {SYMBOL[:3]}\n• *Sell Wall Resistance:* {asks:.2f} {SYMBOL[:3]}"
            send_alert(msg)
            
        # If Limit Sell orders are overwhelmingly larger than Limit Buys -> Macro Top Distribution
        elif ratio < 0.4:
            msg = f"🔴 *MACRO TOP ALERT ({SYMBOL})*\n\nMassive Limit Sell walls detected. Distribution likely.\n\n• *Ask/Bid Ratio:* {(1/ratio):.2f}x\n• *Sell Wall Resistance:* {asks:.2f} {SYMBOL[:3]}\n• *Buy Wall Support:* {bids:.2f} {SYMBOL[:3]}"
            send_alert(msg)
            
        else:
            print(f"Market Neutral. Ratio: {ratio:.2f}. No alert sent.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_market()

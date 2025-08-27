import requests

# === ENVIRONMENT VARS (SET ON RAILWAY) ===
import os
TD_API_KEY = os.getenv("TD_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PAIR_LIST = ["GBP/USD", "EUR/USD", "USD/JPY", "EUR/JPY", "AUD/JPY"]
TIMEFRAMES = ["4h", "1day"]
MIN_GAP_PIPS = 20  

def get_price(pair, timeframe):
    url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval={timeframe}&outputsize=2&apikey={TD_API_KEY}"
    response = requests.get(url)
    data = response.json()
    candles = data.get("values")

    if not candles or len(candles) < 2:
        return None

    curr_open = float(candles[0]['open'])
    prev_close = float(candles[1]['close'])

    return curr_open, prev_close

def check_gap(pair, timeframe):
    prices = get_price(pair, timeframe)
    if prices is None:
        return

    curr_open, prev_close = prices
    pip_value = 0.0001 if "JPY" not in pair else 0.01
    gap = abs(curr_open - prev_close)
    gap_pips = gap / pip_value

    if gap_pips >= MIN_GAP_PIPS:
        direction = "GAP UP" if curr_open > prev_close else "GAP DOWN"
        message = f"📊 {direction} Detected!\nPair: {pair}\nTimeframe: {timeframe}\nGap: {gap_pips:.1f} pips"
        send_to_telegram(message)

def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    requests.post(url, data=payload)

def run_bot():
    for pair in PAIR_LIST:
        for tf in TIMEFRAMES:
            try:
                check_gap(pair, tf)
            except Exception as e:
                print(f"❌ Error with {pair} {tf}: {e}")

run_bot()
import requests
import os

# ==== Load Sensitive Data from Railway Environment Variables ====
TD_API_KEY = os.getenv("TD_API_KEY")              # Twelve Data API Key
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")      # Your Telegram Bot Token
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Your Telegram Chat ID

# ==== Configuration ====
PAIR_LIST = ["GBP/USD", "EUR/USD", "USD/JPY", "EUR/JPY", "AUD/JPY"]
TIMEFRAMES = ["4h", "1day"]
MIN_GAP_PIPS = 20

# === Send Telegram Alert ===
def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

# === Get RSI from Twelve Data ===
def get_rsi(symbol, timeframe):
    url = f"https://api.twelvedata.com/rsi?symbol={symbol}&interval={timeframe}&apikey={TD_API_KEY}&outputsize=1"
    try:
        result = requests.get(url).json()
        if "values" in result:
            return float(result["values"][0]["rsi"])
        else:
            return None
    except:
        return None

# === Fetch last 2 candles (for gap detection) ===
def get_candles(symbol, timeframe):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={timeframe}&outputsize=2&apikey={TD_API_KEY}"
    try:
        result = requests.get(url).json()
        candles = result.get("values", [])
        if len(candles) >= 2:
            current_open = float(candles[0]['open'])
            previous_close = float(candles[1]['close'])
            return current_open, previous_close
        else:
            return None, None
    except:
        return None, None

# === Main Analyzer Logic ===
def analyze_gap(pair, timeframe, curr_open, prev_close):
    pip_value = 0.0001 if "JPY" not in pair else 0.01
    gap_pips = abs(curr_open - prev_close) / pip_value

    if gap_pips < MIN_GAP_PIPS:
        return  # Skip small gaps

    # Determine Direction
    direction = "GAP UP" if curr_open > prev_close else "GAP DOWN"

    # Fetch RSI
    rsi = get_rsi(pair, timeframe)
    rsi_str = f"{rsi:.1f}" if rsi else "N/A"

    # Suggest Strategy
    suggestion = ""
    if direction == "GAP UP":
        if rsi and rsi > 70:
            suggestion = "Market is overbought with Gap UP → High chance of gap fill. Consider SHORT."
        else:
            suggestion = "Gap UP detected. Wait for price structure or reversal signal."
    elif direction == "GAP DOWN":
        if rsi and rsi < 30:
            suggestion = "Gap DOWN with oversold RSI → Possible bounce. Consider LONG toward gap fill."
        else:
            suggestion = "Gap DOWN detected. Wait for structure confirmation before trading."

    # Alert Message
    message = f"""
📊 {direction} Detected!
📍 Pair: {pair}
🕒 TF: {timeframe}
📏 Gap: {gap_pips:.1f} pips
📉 RSI: {rsi_str}

🧠 Strategy Suggestion:
{suggestion}
    """

    send_to_telegram(message.strip())

# === Main Function ===
def run_bot():
    for pair in PAIR_LIST:
        for tf in TIMEFRAMES:
            curr_open, prev_close = get_candles(pair, tf)
            if curr_open and prev_close:
                try:
                    analyze_gap(pair, tf, curr_open, prev_close)
                except Exception as e:
                    print(f"❌ Error on {pair} {tf}: {e}")
            else:
                print(f"⚠️ Skipping {pair} {tf} - missing data")

run_bot()
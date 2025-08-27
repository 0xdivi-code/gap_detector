import os
import requests
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Set up Google Sheets Integration
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
sheet_client = gspread.authorize(creds)
sheet = sheet_client.open("Forex_Gap_Logger").sheet1

# Get ENV vars (for Railway, set these in Variables tab)
TD_API_KEY = os.getenv("TD_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Configuration
PAIR_LIST = ["GBP/USD", "EUR/USD", "USD/JPY", "EUR/JPY", "AUD/JPY"]
TF_MAP = {"4h": "240", "1day": "D"}
MIN_GAP_PIPS = 20

def send_to_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        print("Telegram error:", e)

def get_rsi(pair, tf):
    url = f"https://api.twelvedata.com/rsi?symbol={pair}&interval={tf}&apikey={TD_API_KEY}"
    try:
        data = requests.get(url).json()
        return float(data["values"][0]["rsi"]) if "values" in data else None
    except:
        return None

def get_candles(pair, tf, count=2):
    url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval={tf}&outputsize={count}&apikey={TD_API_KEY}"
    r = requests.get(url)
    try:
        data = r.json().get("values", [])
        return data
    except:
        return []

def build_chart_url(pair, tf):
    tv_pair = pair.replace("/", "")
    tv_tf = TF_MAP.get(tf, "240")
    return f"https://www.tradingview.com/chart/?symbol=FX:{tv_pair}&interval={tv_tf}"

def check_gap(pair, tf):
    candles = get_candles(pair, tf, 2)
    if len(candles) < 2:
        return

    curr_open = float(candles[0]["open"])
    prev_close = float(candles[1]["close"])
    pip_value = 0.0001 if "JPY" not in pair else 0.01
    gap_pips = abs(curr_open - prev_close) / pip_value

    if gap_pips < MIN_GAP_PIPS:
        return

    direction = "GAP UP" if curr_open > prev_close else "GAP DOWN"
    rsi = get_rsi(pair, tf)
    chart_url = build_chart_url(pair, tf)

    if direction == "GAP UP":
        suggestion = "Overbought GAP UP. Possible retracement. Consider SHORT." if rsi and rsi > 70 else "GAP UP. Wait for structure confirmation."
    else:
        suggestion = "Oversold GAP DOWN. Possible bounce. Consider LONG." if rsi and rsi < 30 else "GAP DOWN. Wait for structure confirmation."

    message = f"""
📊 {direction} Detected!
📍 Pair: {pair}
🕒 TF: {tf}
📏 Gap: {gap_pips:.1f} pips
📉 RSI: {round(rsi, 1) if rsi else 'N/A'}

🧠 Suggestion:
{suggestion}

🔗 {chart_url}
    """
    send_to_telegram(message.strip())

    # Log to Google Sheets
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([timestamp, pair, tf, f"{gap_pips:.1f}", round(rsi, 1) if rsi else "N/A", direction, suggestion, "Pending", chart_url])

def update_outcomes():
    data = sheet.get_all_records()
    for idx, entry in enumerate(data, start=2):  # skip header
        if entry["Outcome"] != "Pending":
            continue
        pair = entry["Pair"]
        tf = entry["TF"]
        gap_dir = entry["Direction"]
        gap_origin = float(entry["Gap (pips)"])
        pip_value = 0.0001 if "JPY" not in pair else 0.01

        # Fetch last n candles (check if filled)
        candles = get_candles(pair, tf, 5)
        if not candles:
            continue

        open_price = float(candles[0]["open"])
        curr_price = float(candles[0]["close"])

        # Define gap price level
        if gap_dir == "GAP UP":
            expected_fill = open_price - gap_origin * pip_value
            gap_filled = curr_price <= expected_fill
        else:
            expected_fill = open_price + gap_origin * pip_value
            gap_filled = curr_price >= expected_fill

        if gap_filled:
            sheet.update_cell(idx, 8, "Filled ✅")
        elif datetime.utcnow() - datetime.strptime(entry["Timestamp"], "%Y-%m-%d %H:%M:%S") > timedelta(hours=12):
            sheet.update_cell(idx, 8, "Not Filled ❌")

def run_bot():
    for pair in PAIR_LIST:
        for tf in TF_MAP:
            check_gap(pair, tf)
    update_outcomes()

run_bot()
import os
import json
import requests
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ============ GOOGLE SHEETS AUTH FROM ENV ============

def auth_gsheet():
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    creds_file = "temp-creds.json"
    with open(creds_file, "w") as f:
        f.write(creds_json)

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials = ServiceAccountCredentials.from_json_keyfile_name(creds_file, scope)
    return gspread.authorize(credentials)

sheet_client = auth_gsheet()
gap_sheet = sheet_client.open("Forex_Gap_Logger").worksheet("Sheet1")

# Create separate sheet for Order Blocks (Sheet2)
try:
    ob_sheet = sheet_client.open("Forex_Gap_Logger").worksheet("Order_Blocks")
except:
    ob_sheet = sheet_client.open("Forex_Gap_Logger").add_worksheet(title="Order_Blocks", rows="1000", cols="10")
    ob_sheet.append_row(["Timestamp", "Pair", "TF", "Type", "Zone Low", "Zone High", "Base Candle Time", "Chart URL"])

# ============ CONFIG ============
TD_API_KEY = os.getenv("TD_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PAIR_LIST = ["GBP/USD", "EUR/USD", "USD/JPY", "EUR/JPY", "AUD/JPY"]
TF_MAP = {"4h": "240", "1day": "D"}
MIN_GAP_PIPS = 20

# ============ UTILITIES ============

def send_to_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print("Telegram Error:", e)

def get_candles(pair, tf, count=5):
    url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval={tf}&outputsize={count}&apikey={TD_API_KEY}"
    try:
        return requests.get(url).json().get("values", [])
    except:
        return []

def get_rsi(pair, tf):
    url = f"https://api.twelvedata.com/rsi?symbol={pair}&interval={tf}&apikey={TD_API_KEY}"
    try:
        data = requests.get(url).json()
        return float(data["values"][0]["rsi"]) if "values" in data else None
    except:
        return None

def build_chart_url(pair, tf):
    symbol = pair.replace("/", "")
    interval = TF_MAP.get(tf, "240")
    return f"https://tradingview.com/chart/?symbol=FX:{symbol}&interval={interval}"

# ============ GAP DETECTION ============

def check_gap(pair, tf):
    candles = get_candles(pair, tf, 2)
    if len(candles) < 2:
        return

    curr_open = float(candles[0]['open'])
    prev_close = float(candles[1]['close'])
    pip_value = 0.0001 if "JPY" not in pair else 0.01
    gap_pips = abs(curr_open - prev_close) / pip_value

    if gap_pips < MIN_GAP_PIPS:
        return

    direction = "GAP UP" if curr_open > prev_close else "GAP DOWN"
    rsi = get_rsi(pair, tf)
    rsi_str = f"{rsi:.1f}" if rsi else "N/A"
    chart_url = build_chart_url(pair, tf)

    if direction == "GAP UP":
        suggestion = "Overbought GAP UP. Consider SHORT." if rsi and rsi > 70 else "GAP UP. Wait for structure."
    else:
        suggestion = "Oversold GAP DOWN. Consider LONG." if rsi and rsi < 30 else "GAP DOWN. Wait for confirmation."

    msg = f"""
📊 {direction}
📍 {pair} | {tf.upper()}
📏 Gap: {gap_pips:.1f} pips | RSI: {rsi_str}
🧠 {suggestion}
🔗 {chart_url}
"""
    send_to_telegram(msg.strip())

    time_now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    gap_sheet.append_row([time_now, pair, tf, f"{gap_pips:.1f}", rsi_str, direction, suggestion, "Pending", chart_url])

# ============ GAP OUTCOME UPDATE ============

def update_outcomes():
    records = gap_sheet.get_all_records()
    for idx, r in enumerate(records, start=2):
        if r["Outcome"] != "Pending":
            continue

        pair = r["Pair"]
        tf = r["TF"]
        gap_pips = float(r["Gap (pips)"])
        direction = r["Direction"]
        base_time = datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S")
        age = (datetime.utcnow() - base_time).total_seconds()
        wait_time = 6*3600 if tf == "4h" else 24*3600
        if age < wait_time:
            continue

        candles = get_candles(pair, tf, 1)
        if not candles: continue

        close = float(candles[0]['close'])
        open_price = float(candles[0]['open'])
        pip_value = 0.0001 if "JPY" not in pair else 0.01

        if direction == "GAP UP" and close <= open_price - gap_pips * pip_value:
            gap_sheet.update_cell(idx, 8, "Filled ✅")
        elif direction == "GAP DOWN" and close >= open_price + gap_pips * pip_value:
            gap_sheet.update_cell(idx, 8, "Filled ✅")
        else:
            gap_sheet.update_cell(idx, 8, "Not Filled ❌")

# ============ ORDER BLOCK DETECTOR ============

def detect_orderblock(pair, tf):
    candles = get_candles(pair, tf, 5)
    if len(candles) < 4:
        return
    
    # Use 2nd last candle as the "base" candle
    c1 = candles[2]  # base candle
    c2 = candles[1]
    c3 = candles[0]

    chart_url = build_chart_url(pair, tf)

    # Buy Order Block (Demand Zone)
    if float(c1['close']) < float(c1['open']):  # bearish base candle
        if float(c2['close']) > float(c2['open']) and float(c3['close']) > float(c2['close']):
            zone_low = float(c1["low"])
            zone_high = float(c1["high"])
            msg = f"""
📦 BUY ORDER BLOCK DETECTED
📍 {pair} | {tf.upper()}
📌 Zone: {zone_low:.4f} - {zone_high:.4f}
🕒 Base Candle: {c1['datetime']}
🔗 {chart_url}
"""
            send_to_telegram(msg.strip())
            ob_sheet.append_row([
                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                pair, tf, "Buy OB", zone_low, zone_high, c1['datetime'], chart_url
            ])

    # Sell Order Block (Supply Zone)
    if float(c1['close']) > float(c1['open']):  # bullish base candle
        if float(c2['close']) < float(c2['open']) and float(c3['close']) < float(c2['close']):
            zone_low = float(c1["low"])
            zone_high = float(c1["high"])
            msg = f"""
📦 SELL ORDER BLOCK DETECTED
📍 {pair} | {tf.upper()}
📌 Zone: {zone_low:.4f} - {zone_high:.4f}
🕒 Base Candle: {c1['datetime']}
🔗 {chart_url}
"""
            send_to_telegram(msg.strip())
            ob_sheet.append_row([
                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                pair, tf, "Sell OB", zone_low, zone_high, c1['datetime'], chart_url
            ])

# ============ MAIN RUN LOOP ============

def run_bot():
    for pair in PAIR_LIST:
        for tf in TF_MAP:
            check_gap(pair, tf)
            detect_orderblock(pair, tf)
    update_outcomes()

run_bot()
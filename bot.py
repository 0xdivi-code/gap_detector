import os
import json
import requests
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ============ AUTH GOOGLE SHEETS ============
def auth_gsheet():
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    with open("temp-creds.json", "w") as f:
        f.write(creds_json)

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("temp-creds.json", scope)
    return gspread.authorize(creds)

sheet_client = auth_gsheet()

gap_sheet = sheet_client.open("Forex_Gap_Logger").worksheet("Sheet1")
try:
    ob_sheet = sheet_client.open("Forex_Gap_Logger").worksheet("Order_Blocks")
except:
    ob_sheet = sheet_client.open("Forex_Gap_Logger").add_worksheet("Order_Blocks", rows="1000", cols="10")
    ob_sheet.append_row([
        "Timestamp", "Pair", "TF", "Type", "Zone Low", "Zone High", "Base Candle Time", "Chart URL", "Outcome"
    ])

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

    suggestion = ""
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

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    gap_sheet.append_row([timestamp, pair, tf, f"{gap_pips:.1f}", rsi_str, direction, suggestion, "Pending", chart_url])

# ============ GAP OUTCOME UPDATE ============

def update_outcomes():
    entries = gap_sheet.get_all_records()
    for i, r in enumerate(entries, start=2):
        if r["Outcome"] != "Pending":
            continue
        created = datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S")
        age = (datetime.utcnow() - created).total_seconds()
        tf = r["TF"]
        if tf == "4h" and age < 6*3600: continue
        if tf == "1day" and age < 48*3600: continue

        pair = r["Pair"]
        direction = r["Direction"]
        gap_pips = float(r["Gap (pips)"])
        candles = get_candles(pair, tf, 1)
        if len(candles) < 1: continue

        close = float(candles[0]["close"])
        open_price = float(candles[0]["open"])
        pip_val = 0.0001 if "JPY" not in pair else 0.01

        fill = False
        if direction == "GAP UP" and close <= open_price - gap_pips * pip_val:
            fill = True
        if direction == "GAP DOWN" and close >= open_price + gap_pips * pip_val:
            fill = True

        outcome = "Filled ✅" if fill else "Not Filled ❌"
        gap_sheet.update_cell(i, 8, outcome)

# ============ ORDER BLOCK DETECTION ============

def detect_orderblock(pair, tf):
    candles = get_candles(pair, tf, 5)
    if len(candles) < 3:
        return

    base = candles[2]
    c2 = candles[1]
    c3 = candles[0]
    chart_url = build_chart_url(pair, tf)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    # BUY OB
    if float(base['close']) < float(base['open']):
        if float(c2['close']) > float(c2['open']) and float(c3['close']) > float(c2['close']):
            zl = float(base['low'])
            zh = float(base['high'])
            msg = f"""
📦 BUY ORDER BLOCK DETECTED
📍 {pair} | {tf.upper()}
📌 Zone: {zl:.4f} – {zh:.4f}
📅 {base['datetime']}
🔗 {chart_url}
"""
            send_to_telegram(msg.strip())
            ob_sheet.append_row([now, pair, tf, "Buy OB", zl, zh, base['datetime'], chart_url, "Pending"])

    # SELL OB
    if float(base['close']) > float(base['open']):
        if float(c2['close']) < float(c2['open']) and float(c3['close']) < float(c2['close']):
            zl = float(base['low'])
            zh = float(base['high'])
            msg = f"""
📦 SELL ORDER BLOCK DETECTED
📍 {pair} | {tf.upper()}
📌 Zone: {zl:.4f} – {zh:.4f}
📅 {base['datetime']}
🔗 {chart_url}
"""
            send_to_telegram(msg.strip())
            ob_sheet.append_row([now, pair, tf, "Sell OB", zl, zh, base['datetime'], chart_url, "Pending"])

# ============ ORDER BLOCK OUTCOME TRACKING ============

def update_orderblock_outcomes():
    rows = ob_sheet.get_all_records()
    for i, r in enumerate(rows, start=2):
        if r["Outcome"] not in ["Pending", ""]:
            continue
        created = datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S")
        tf = r["TF"]
        age = (datetime.utcnow() - created).total_seconds()
        if tf == "4h" and age < 6*3600: continue
        if tf == "1day" and age < 48*3600: continue

        pair = r["Pair"]
        zl = float(r["Zone Low"])
        zh = float(r["Zone High"])
        ob_type = r["Type"]
        outcome = "Pending"

        candles = get_candles(pair, tf, 1)
        if len(candles) < 1: continue
        price = float(candles[0]["close"])

        if zl <= price <= zh:
            outcome = "Respected ✅"
        elif ob_type == "Buy OB" and price < zl:
            outcome = "Invalidated ❌"
        elif ob_type == "Sell OB" and price > zh:
            outcome = "Invalidated ❌"

        ob_sheet.update_cell(i, 9, outcome)
        if outcome != "Pending":
            send_to_telegram(f"📈 OB {outcome} – {ob_type} [{pair} {tf.upper()}]")

# ============ MAIN RUN ============
def run_bot():
    for pair in PAIR_LIST:
        for tf in TF_MAP:
            check_gap(pair, tf)
            detect_orderblock(pair, tf)
    update_outcomes()
    update_orderblock_outcomes()

run_bot()
import os
import json
import requests
from datetime import datetime, timedelta, timezone
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# === Helper: Get UTC timestamp string ===
def get_utc_now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

# === Google Sheets Auth ===
def auth_gsheet():
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    with open("temp-creds.json", "w") as f:
        f.write(creds_json)
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("temp-creds.json", scope)
    return gspread.authorize(creds)

sheet_client = auth_gsheet()
gap_sheet = sheet_client.open("Forex_Gap_Logger").worksheet("Sheet1")

# Create or access Order Blocks sheet
try:
    ob_sheet = sheet_client.open("Forex_Gap_Logger").worksheet("Order_Blocks")
except:
    ob_sheet = sheet_client.open("Forex_Gap_Logger").add_worksheet("Order_Blocks", rows=1000, cols=15)
    ob_sheet.append_row([
        "Timestamp", "Pair", "TF", "Type",
        "Zone Low", "Zone High", "Base Candle Time",
        "Chart URL", "Smart Summary", "Suggested Entry",
        "Confidence Tier", "Outcome"
    ])

# === Config ===
TD_API_KEY = os.getenv("TD_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PAIR_LIST = ["GBP/USD", "EUR/USD", "USD/JPY", "EUR/JPY", "AUD/JPY"]
TF_MAP = {"4h": "240", "1day": "D"}

# === Utility Functions ===
def send_to_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    requests.post(url, data=payload)

def get_candles(pair, tf, count=5):
    url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval={tf}&outputsize={count}&apikey={TD_API_KEY}"
    return requests.get(url).json().get("values", [])

def get_rsi(pair, tf):
    url = f"https://api.twelvedata.com/rsi?symbol={pair}&interval={tf}&apikey={TD_API_KEY}"
    data = requests.get(url).json()
    return float(data["values"][0]["rsi"]) if "values" in data else None

def build_chart_url(pair, tf):
    symbol = pair.replace("/", "")
    interval = TF_MAP[tf]
    return f"https://tradingview.com/chart/?symbol=FX:{symbol}&interval={interval}"

def assign_confidence_level(score):
    if score >= 4:
        return "👑 TIER 1 (HIGH CONFIDENCE)", "🟢"
    elif score == 2 or score == 3:
        return "⭐ TIER 2 (MEDIUM)", "🟡"
    else:
        return "⚠️ TIER 3 (LOW)", "🔴"

# === Smart Money Analyzer ===
def analyze_orderblock(pair, tf, ob_type, zone_low, zone_high, rsi, candles):
    c = candles[-5:]
    highs = [float(x['high']) for x in c]
    lows = [float(x['low']) for x in c]
    body = abs(float(c[-1]["close"]) - float(c[-1]["open"]))
    high = float(c[-1]["high"])
    low = float(c[-1]["low"])
    close = float(c[-1]["close"])
    open_ = float(c[-1]["open"])

    score = 0
    rsi_text = "Overbought" if rsi > 70 else "Oversold" if rsi < 30 else "Neutral"
    if rsi > 70 or rsi < 30:
        score += 1

    fvg = abs(float(c[-2]["close"]) - open_) > (high - low) * 0.3
    if fvg: score += 1

    body_prev = abs(float(c[-2]['close']) - float(c[-2]['open']))
    breaker = body_prev > body * 1.5
    if breaker: score += 1

    wick_thresh = (high - close) if ob_type == "Sell OB" else (close - low)
    rejection = wick_thresh > (high - low) * 0.4
    if rejection: score += 1

    is_old_high = zone_high >= max(highs[:-2])
    is_old_low = zone_low <= min(lows[:-2])
    if (ob_type == "Sell OB" and is_old_high) or (ob_type == "Buy OB" and is_old_low):
        score += 1

    if ob_type == "Buy OB":
        if fvg and rsi < 30:
            rec = "Buy Limit at zone low"
        elif rejection:
            rec = "Buy Stop Limit on break"
        else:
            rec = "Wait for confirmation on lower TF"
    else:
        if fvg and rsi > 70:
            rec = "Sell Limit at zone high"
        elif rejection:
            rec = "Sell Stop Limit on break"
        else:
            rec = "Wait for confirmation on lower TF"

    tier_text, emoji = assign_confidence_level(score)

    summary = f"""
{emoji} *{tier_text}*

🧠 Smart Money Analysis:
- RSI: {rsi:.1f} ({rsi_text})
- FVG Present? {"✅" if fvg else "❌"}
- Breaker Candle? {"✅" if breaker else "❌"}
- Rejection Wick? {"✅" if rejection else "❌"}
- Old High/Low? {"✅" if is_old_high or is_old_low else "❌"}

💡 Suggested Trade: {rec}
""".strip()

    return summary, rec, tier_text

# === Detect Order Blocks ===
def detect_orderblock(pair, tf):
    candles = get_candles(pair, tf, 5)
    if len(candles) < 3: return
    c2, c1, c0 = candles[-3], candles[-2], candles[-1]
    rsi = get_rsi(pair, tf) or 50
    chart_url = build_chart_url(pair, tf)
    now = get_utc_now_str()

    # Buy OB
    if float(c2['close']) < float(c2['open']) and float(c1['close']) > float(c1['open']) and float(c0['close']) > float(c1['close']):
        zl, zh = float(c2['low']), float(c2['high'])
        summary, trade, tier = analyze_orderblock(pair, tf, "Buy OB", zl, zh, rsi, candles)
        msg = f"""
📦 *BUY ORDER BLOCK DETECTED*
Pair: {pair} | TF: {tf.upper()}
📍 Zone: {zl:.4f} – {zh:.4f}
📅 Base: {c2['datetime']}
🔗 {chart_url}

{summary}
"""
        send_to_telegram(msg)
        ob_sheet.append_row([now, pair, tf, "Buy OB", zl, zh, c2['datetime'], chart_url, summary, trade, tier, "Pending"])

    # Sell OB
    if float(c2['close']) > float(c2['open']) and float(c1['close']) < float(c1['open']) and float(c0['close']) < float(c1['close']):
        zl, zh = float(c2['low']), float(c2['high'])
        summary, trade, tier = analyze_orderblock(pair, tf, "Sell OB", zl, zh, rsi, candles)
        msg = f"""
📦 *SELL ORDER BLOCK DETECTED*
Pair: {pair} | TF: {tf.upper()}
📍 Zone: {zl:.4f} – {zh:.4f}
📅 Base: {c2['datetime']}
🔗 {chart_url}

{summary}
"""
        send_to_telegram(msg)
        ob_sheet.append_row([now, pair, tf, "Sell OB", zl, zh, c2['datetime'], chart_url, summary, trade, tier, "Pending"])

# === Outcome Tracker ===
def update_orderblock_outcomes():
    rows = ob_sheet.get_all_records()
    for i, r in enumerate(rows, start=2):
        if r.get("Outcome") != "Pending": continue
        tf = r["TF"]
        age = (datetime.now(timezone.utc) - datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S")).total_seconds()
        if (tf == "4h" and age < 6*3600) or (tf == "1day" and age < 48*3600): continue

        candles = get_candles(r["Pair"], tf, 1)
        if len(candles) < 1: continue
        price = float(candles[0]["close"])
        low, high = float(r["Zone Low"]), float(r["Zone High"])

        if low <= price <= high:
            outcome = "Respected ✅"
        elif r["Type"] == "Buy OB" and price < low:
            outcome = "Invalidated ❌"
        elif r["Type"] == "Sell OB" and price > high:
            outcome = "Invalidated ❌"
        else:
            outcome = "Pending"

        if outcome != "Pending":
            ob_sheet.update_cell(i, 12, outcome)
            send_to_telegram(f"📊 OB {outcome} — {r['Type']} at {r['Pair']} ({tf.upper()})")

# === Main Bot Run ===
def run_bot():
    for pair in PAIR_LIST:
        for tf in TF_MAP:
            detect_orderblock(pair, tf)
    update_orderblock_outcomes()

run_bot()
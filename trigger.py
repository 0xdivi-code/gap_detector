from flask import Flask
import main  # ensure main.py is in same folder

app = Flask(__name__)

@app.route("/")
def status():
    return "✅ Forex Gap/OrderBlock Bot is Alive."

@app.route("/run")
def run_bot():
    try:
        main.run_bot()
        return "🟢 Bot executed successfully"
    except Exception as e:
        return f"❌ Bot Error: {str(e)}"
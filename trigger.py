from flask import Flask
import main  # This is your bot script

app = Flask(__name__)

@app.route('/')
def home():
    return "Gap Bot is alive ✅"

@app.route('/run')
def run_bot():
    try:
        main.run_bot()
        return "Bot executed successfully 👌"
    except Exception as e:
        return f"Bot error: {str(e)}"
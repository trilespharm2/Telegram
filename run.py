import threading
import subprocess
import sys

def run_bot():
    subprocess.run([sys.executable, "main.py"])

def run_webhook():
    subprocess.run([
        "gunicorn", "webhook.stripe_webhook:app",
        "--bind", "0.0.0.0:8080",
        "--workers", "1"
    ])

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot)
    webhook_thread = threading.Thread(target=run_webhook)

    bot_thread.start()
    webhook_thread.start()

    bot_thread.join()
    webhook_thread.join()

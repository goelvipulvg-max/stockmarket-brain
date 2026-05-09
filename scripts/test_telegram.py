from dotenv import load_dotenv
load_dotenv(override=True)

import os
from utils.telegram_client import send_message

BOT = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL = os.getenv("TELEGRAM_TRADES_CHANNEL_ID")

if not BOT:
    print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
elif not CHANNEL:
    print("ERROR: TELEGRAM_TRADES_CHANNEL_ID not set in .env")
else:
    print(f"Sending test message to channel {CHANNEL}...")
    send_message(BOT, CHANNEL, "\U0001f9e0 StockMarket-Brain connected!")
    print("Done!")

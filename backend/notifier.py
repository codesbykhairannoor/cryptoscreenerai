import requests
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8795701557:AAGZuF3s6mipPB-6fFBYWjLXM7dHBVUmMYg")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6050956737")

def send_telegram_message(message):
    """Kirim pesan ke Telegram secara sinkron."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")
        return False

def format_trade_message(data):
    """Format pesan trade agar cantik di Telegram."""
    emoji = "[PUMP]" if data.get('side', '').lower() in ['buy', 'long'] else "[DOWN]"
    
    msg = (
        f"<b>{emoji} NEW TRADE EXECUTED</b>\n\n"
        f"<b>Symbol:</b> <code>{data.get('symbol')}</code>\n"
        f"<b>Side:</b> {data.get('side').upper()}\n"
        f"<b>Price:</b> ${data.get('price')}\n"
        f"<b>Amount:</b> {data.get('amount')} contracts\n"
        f"<b>Score:</b> {data.get('score')}/100\n"
        f"----------------------------------\n"
        f"<b>[TP] TP:</b> {data.get('tp')} (+{data.get('tp_pct')}%)\n"
        f"<b>[SL] SL:</b> {data.get('sl')} (-{data.get('sl_pct')}%)\n"
        f"----------------------------------\n"
        f"<b>[WHY] Why:</b> {data.get('reason')}\n\n"
        f"<b>[TECH] [TECH]</b>\n"
        f"RSI: {data.get('rsi')}\n"
        f"VWAP: {data.get('vwap')}%\n"
        f"OBI: {data.get('obi_rest')}\n"
        f"Trend1h: {data.get('trend_1h')}\n\n"
        f"<b>[WHALE] [WS-RT]</b>\n"
        f"Whale Buy: ${data.get('rt_wbv'):,.0}\n"
        f"Whale Sell: ${data.get('rt_wsv'):,.0}\n"
        f"RT-OBI: {data.get('rt_obi'):+.2f}\n"
        f"Spread: {data.get('rt_spread'):.3f}%\n\n"
        f"<b>[HOT] [SMC 5M]</b>\n"
        f"Signal: {data.get('e5m')}\n"
        f"Quality: {data.get('q5m')}/100\n"
        f"Zone: {data.get('f5m')}\n"
    )
    return msg

if __name__ == "__main__":
    # Test message
    test_msg = "<b>[BOT] Bot Connection Test</b>\nBot is now connected to VPS. Ready to snipe! [PUMP]"
    if send_telegram_message(test_msg):
        print("Telegram test success!")
    else:
        print("Telegram test failed!")




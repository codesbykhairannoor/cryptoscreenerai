import hmac
import hashlib
import base64
import asyncio
import json
import websockets
import os
import time
import ssl
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BITGET_API_KEY")
SECRET_KEY = os.getenv("BITGET_SECRET_KEY")
PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

def get_signature(timestamp, secret_key):
    message = str(timestamp) + 'GET' + '/user/verify'
    mac = hmac.new(bytes(secret_key, encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
    return base64.b64encode(mac.digest()).decode('utf8')

async def test_auth(format_name, timestamp):
    url = "wss://ws.bitget.com/v2/ws/private"
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    print(f"\n--- Testing {format_name} (ts={timestamp}) ---")
    try:
        async with websockets.connect(url, ssl=ssl_context) as ws:
            login_msg = {
                "op": "login",
                "args": [{
                    "apiKey": API_KEY,
                    "passphrase": PASSPHRASE,
                    "timestamp": str(timestamp),
                    "sign": get_signature(timestamp, SECRET_KEY)
                }]
            }
            await ws.send(json.dumps(login_msg))
            resp = await ws.recv()
            print(f"Response: {resp}")
    except Exception as e:
        print(f"Error: {e}")

async def run_tests():
    # Test Seconds
    ts_sec = int(time.time())
    await test_auth("SECONDS", ts_sec)
    
    await asyncio.sleep(2)
    
    # Test Milliseconds
    ts_ms = int(time.time() * 1000)
    await test_auth("MILLISECONDS", ts_ms)

if __name__ == "__main__":
    asyncio.run(run_tests())

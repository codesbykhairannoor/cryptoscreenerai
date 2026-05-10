import hmac
import hashlib
import base64
import time
import requests
import os
import json
from dotenv import load_dotenv

# Suppress warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv('backend/.env')

API_KEY = os.getenv("BITGET_API_KEY")
SECRET_KEY = os.getenv("BITGET_SECRET_KEY")
PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

def get_signature(timestamp, method, request_path, body=""):
    message = str(timestamp) + method.upper() + request_path + body
    mac = hmac.new(bytes(SECRET_KEY, encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
    return base64.b64encode(mac.digest()).decode('utf8')

def get_server_time():
    try:
        res = requests.get("https://api.bitget.com/api/v2/public/time", verify=False, timeout=5)
        return int(res.json()['data']['serverTime'])
    except:
        return int(time.time() * 1000)

def check_pos():
    server_ts = get_server_time()
    offset = server_ts - int(time.time() * 1000)
    timestamp = str(int(time.time() * 1000) + offset)
    
    path = "/api/v2/mix/position/all-position?productType=USDT-FUTURES&marginCoin=USDT"
    sign = get_signature(timestamp, "GET", path)
    
    headers = {
        "ACCESS-KEY": API_KEY, "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE, "Content-Type": "application/json"
    }
    
    try:
        res = requests.get(f"https://api.bitget.com{path}", headers=headers, verify=False, timeout=10)
        data = res.json()
        print(f"Positions: {json.dumps(data, indent=2)}")
        
        # Check orders too
        ts2 = str(int(time.time() * 1000) + offset)
        path2 = "/api/v2/mix/order/plan-current-orders?productType=USDT-FUTURES"
        sign2 = get_signature(ts2, "GET", path2)
        headers2 = {
            "ACCESS-KEY": API_KEY, "ACCESS-SIGN": sign2, "ACCESS-TIMESTAMP": ts2,
            "ACCESS-PASSPHRASE": PASSPHRASE, "Content-Type": "application/json"
        }
        res2 = requests.get(f"https://api.bitget.com{path2}", headers=headers2, verify=False, timeout=10)
        print(f"Plan Orders: {json.dumps(res2.json(), indent=2)}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_pos()

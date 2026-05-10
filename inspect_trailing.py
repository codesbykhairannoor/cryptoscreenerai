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

def inspect_busdt():
    print("Syncing time...")
    server_ts = get_server_time()
    offset = server_ts - int(time.time() * 1000)
    
    timestamp = str(int(time.time() * 1000) + offset)
    
    # Path for active plan orders (SL/TP)
    # Symbol clean: BUSDT -> B/USDT:USDT in Bitget
    # Actually B/USDT is the symbol in the log. 
    # Log says: [MONITOR] B/USDT:USDT
    symbol = "BUSDT" # We'll try some variations
    
    path = "/api/v2/mix/order/plan-current-orders?productType=USDT-FUTURES"
    sign = get_signature(timestamp, "GET", path)
    
    headers = {
        "ACCESS-KEY": API_KEY, "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE, "Content-Type": "application/json"
    }
    
    try:
        res = requests.get(f"https://api.bitget.com{path}", headers=headers, verify=False, timeout=10)
        data = res.json()
        
        if data.get('code') != '00000':
            print(f"Error: {data}")
            return
            
        plans = data.get('data', [])
        print(f"\nFound {len(plans)} plan orders.")
        for p in plans:
            p_symbol = p.get('symbol')
            p_type = p.get('planType')
            trigger = p.get('triggerPrice')
            print(f"Symbol: {p_symbol} | Type: {p_type} | Trigger: {trigger}")
            
        # Check current position for entry price
        path_pos = "/api/v2/mix/position/all-position?productType=USDT-FUTURES&marginCoin=USDT"
        ts_pos = str(int(time.time() * 1000) + offset)
        sign_pos = get_signature(ts_pos, "GET", path_pos)
        headers_pos = {
            "ACCESS-KEY": API_KEY, "ACCESS-SIGN": sign_pos, "ACCESS-TIMESTAMP": ts_pos,
            "ACCESS-PASSPHRASE": PASSPHRASE, "Content-Type": "application/json"
        }
        res_pos = requests.get(f"https://api.bitget.com{path_pos}", headers=headers_pos, verify=False, timeout=10)
        positions = res_pos.json().get('data', [])
        
        for p in positions:
            if float(p.get('total', 0)) > 0:
                print(f"\n--- POSITION: {p.get('symbol')} ---")
                print(f"Entry: {p.get('averageOpenPrice')}")
                print(f"Mark:  {p.get('markPrice')}")
                print(f"Unrealized PnL: {p.get('unrealizedPL')}")
                print(f"Leverage: {p.get('leverage')}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_busdt()

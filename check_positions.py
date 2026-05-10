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

def check_bitget_positions():
    print(f"Syncing time with Bitget...")
    server_ts = get_server_time()
    local_ts = int(time.time() * 1000)
    offset = server_ts - local_ts
    print(f"Time Offset: {offset}ms")
    
    # Use synced timestamp
    timestamp = str(local_ts + offset)
    
    # Path untuk V2 positions (USDT-FUTURES)
    path = "/api/v2/mix/position/all-position?productType=USDT-FUTURES&marginCoin=USDT"
    sign = get_signature(timestamp, "GET", path)
    
    headers = {
        "ACCESS-KEY": API_KEY, "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE, "Content-Type": "application/json"
    }
    
    url = f"https://api.bitget.com{path}"
    
    try:
        res = requests.get(url, headers=headers, verify=False, timeout=10)
        data = res.json()
        
        if data.get('code') != '00000':
            print(f"Error from Bitget: {data}")
            return
            
        positions = data.get('data', [])
        # Di V2, size ada di 'total' atau 'available'
        active = [p for p in positions if float(p.get('total', 0)) > 0]
        
        print("\n" + "="*50)
        print("          LIVE BITGET POSITIONS (V2)")
        print("="*50)
        
        if not active:
            print("No active positions found.")
        else:
            for p in active:
                side = p.get('holdSide', 'N/A').upper()
                symbol = p.get('symbol', 'N/A')
                size = p.get('total', '0')
                entry = p.get('averageOpenPrice', '0')
                pnl = p.get('unrealizedPL', '0')
                print(f"Symbol:   {symbol}")
                print(f"Side:     {side}")
                print(f"Size:     {size} contracts")
                print(f"Entry:    {entry}")
                print(f"Unrealized PnL: {pnl} USDT")
                print("-" * 30)
                
        # Check Account Assets
        path_bal = "/api/v2/mix/account/accounts?productType=USDT-FUTURES&marginCoin=USDT"
        timestamp_bal = str(int(time.time() * 1000) + offset)
        sign_bal = get_signature(timestamp_bal, "GET", path_bal)
        headers_bal = {
            "ACCESS-KEY": API_KEY, "ACCESS-SIGN": sign_bal, "ACCESS-TIMESTAMP": timestamp_bal,
            "ACCESS-PASSPHRASE": PASSPHRASE, "Content-Type": "application/json"
        }
        res_bal = requests.get(f"https://api.bitget.com{path_bal}", headers=headers_bal, verify=False, timeout=10)
        data_bal = res_bal.json()
        
        if data_bal.get('code') == '00000':
            assets = data_bal.get('data', [])
            for asset in assets:
                if asset.get('marginCoin') == 'USDT':
                    print(f"\nEquity:    ${asset.get('equity')} USDT")
                    print(f"Available: ${asset.get('available')} USDT")
        
        print("="*50)
        
    except Exception as e:
        print(f"Network Error: {e}")

if __name__ == "__main__":
    check_bitget_positions()

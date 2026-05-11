import hmac
import hashlib
import base64
import requests
import time
import json
import os
from dotenv import load_dotenv

load_dotenv('backend/.env')

API_KEY = os.getenv("BITGET_API_KEY")
SECRET_KEY = os.getenv("BITGET_SECRET_KEY")
PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

def v2_request(method, path, query="", body=None):
    ts = str(int(time.time() * 1000))
    request_path = path + (f"?{query}" if query else "")
    body_str = json.dumps(body) if body else ""
    message = ts + method.upper() + request_path + body_str
    mac = hmac.new(bytes(SECRET_KEY, encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
    sign = base64.b64encode(mac.digest()).decode('utf8')
    headers = {
        "ACCESS-KEY": API_KEY, "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": PASSPHRASE, "Content-Type": "application/json"
    }
    url = f"https://api.bitget.com{request_path}"
    try:
        res = requests.request(method, url, headers=headers, data=body_str if body else None, timeout=10, verify=False)
        return res.json()
    except Exception as e:
        return {"error": str(e)}

def forensic_audit_direct():
    print("="*60)
    print("DIRECT BITGET V2 FORENSIC AUDIT")
    print("="*60)

    # 1. Fetch Active Positions
    print("\n[1] POSISI AKTIF (USDT-FUTURES):")
    res = v2_request("GET", "/api/v2/mix/position/all-position", "productType=USDT-FUTURES")
    if res.get('code') == '00000':
        data = res.get('data', [])
        for p in data:
            if float(p.get('total', 0)) > 0:
                print(f"    - {p['symbol']} | Side: {p['holdSide']} | Vol: {p['total']} | Entry: {p['openPriceAvg']}")
    else:
        print(f"    Failed: {res}")

    # 2. Fetch Recent Orders (History)
    print("\n[2] 10 ORDER TERAKHIR (FILLED/CANCELLED):")
    res = v2_request("GET", "/api/v2/mix/order/history", "productType=USDT-FUTURES&startTime=" + str(int(time.time()*1000 - 86400000)))
    if res.get('code') == '00000':
        data = res.get('data', [])[:10]
        for o in data:
            print(f"    - [{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(int(o['cTime'])/1000))}] {o['symbol']} {o['side']} {o['state']} | Vol: {o['size']} | Comment: {o.get('orderComment', 'NONE')} | ID: {o['orderId']}")
    else:
        print(f"    Failed: {res}")

    # 3. Balance Audit
    print("\n[3] AUDIT SALDO (USDT-FUTURES):")
    res = v2_request("GET", "/api/v2/mix/account/accounts", "productType=USDT-FUTURES")
    if res.get('code') == '00000':
        data = res.get('data', [])
        for a in data:
            if a['marginCoin'] == 'USDT':
                print(f"    - Total Equity: {a['equity']} USDT")
                print(f"    - Available: {a['available']} USDT")
                print(f"    - Locked Margin: {float(a['equity']) - float(a['available']):.4f} USDT")
    else:
        print(f"    Failed: {res}")

if __name__ == "__main__":
    forensic_audit_direct()

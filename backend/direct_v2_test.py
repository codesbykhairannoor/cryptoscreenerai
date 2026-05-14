import hmac
import hashlib
import base64
import time
import requests
import os
from dotenv import load_dotenv

# --- DIRECT V2 API TEST: BYPASS CCXT ---

def direct_v2_test():
    load_dotenv()
    api_key = os.getenv("BITGET_API_KEY")
    secret = os.getenv("BITGET_SECRET_KEY")
    passphrase = os.getenv("BITGET_PASSPHRASE")

    print("\n" + "="*60)
    print("DIRECT V2 API AUDIT: BYPASSING CCXT")
    print("="*60)

    def get_server_time():
        r = requests.get("https://api.bitget.com/api/v2/public/time")
        return int(r.json()['data']['serverTime'])

    server_ts = get_server_time()
    local_ts = int(time.time() * 1000)
    offset = server_ts - local_ts
    print(f"[1] Server Time: {server_ts}")
    print(f"[2] Local Time : {local_ts}")
    print(f"[3] Offset     : {offset}ms")

    # Path untuk ambil akun V2 (Classic/UTA compatible)
    path = "/api/v2/mix/account/accounts"
    query = "productType=USDT-FUTURES"
    method = "GET"
    ts = str(int(time.time() * 1000 + offset))
    
    message = ts + method + path + "?" + query
    mac = hmac.new(bytes(secret, encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
    sign = base64.b64encode(mac.digest()).decode('utf8')

    headers = {
        "ACCESS-KEY": api_key,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json"
    }

    print("\n[4] MENGIRIM PERMINTAAN SALDO V2...")
    url = f"https://api.bitget.com{path}?{query}"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        print(f"    Respon Code: {data.get('code')}")
        print(f"    Respon Msg : {data.get('msg')}")
        
        if data.get('code') == '00000':
            print("\n    [SUKSES] API KEY VALID!")
            for acc in data.get('data', []):
                if acc.get('marginCoin') == 'USDT':
                    print(f"    SALDO USDT: ${acc.get('available')}")
        else:
            print(f"\n    [GAGAL] Bitget menolak: {data.get('msg')}")
            if data.get('code') == '40012':
                print("    --> ERROR 40012: Jam VPS Bos ngaco parah! Sinkronkan jam Windows Bos sekarang.")
            elif data.get('code') == '40001':
                print("    --> ERROR 40001: API Key/Secret/Passphrase Bos SALAH!")
    except Exception as e:
        print(f"    [ERROR] Koneksi gagal: {e}")

    print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    direct_v2_test()




import requests, time, hmac, hashlib, base64, os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("BITGET_API_KEY")
secret_key = os.getenv("BITGET_SECRET_KEY")
passphrase = os.getenv("BITGET_PASSPHRASE", "")

def bitget_v2_request(path, query=""):
    ts = str(int(time.time() * 1000))
    message = ts + "GET" + path + ("?" + query if query else "")
    mac = hmac.new(bytes(secret_key, encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
    sign = base64.b64encode(mac.digest()).decode('utf8')
    
    headers = {
        "ACCESS-KEY": api_key,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json"
    }
    
    url = f"https://api.bitget.com{path}{'?' + query if query else ''}"
    res = requests.get(url, headers=headers, timeout=5, verify=False)
    try:
        return res.json()
    except:
        print(f"FAILED JSON: {res.text}")
        return {}

print("--- POSITIONS ---")
pos_data = bitget_v2_request("/api/v2/mix/position/all-position", "productType=USDT-FUTURES&marginCoin=USDT")
print(pos_data)

print("\n--- PLAN ORDERS (profit_loss) ---")
pl_data = bitget_v2_request("/api/v2/mix/order/orders-plan-pending", "productType=USDT-FUTURES&planType=profit_loss")
print(pl_data)

print("\n--- PLAN ORDERS (normal_plan) ---")
np_data = bitget_v2_request("/api/v2/mix/order/orders-plan-pending", "productType=USDT-FUTURES&planType=normal_plan")
print(np_data)

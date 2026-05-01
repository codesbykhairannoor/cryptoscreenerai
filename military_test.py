
import os
import sys
import requests
import time
from dotenv import load_dotenv

load_dotenv('backend/.env')

TOKEN = os.getenv("FOREX_META_API_TOKEN")
ACC_ID = os.getenv("FOREX_ACCOUNT_ID")
HEADERS = {"auth-token": TOKEN}

SERVERS = [
    "https://mt-client-api-v1.london.agiliumtrade.ai",
    "https://mt-client-api-v1.new-york.agiliumtrade.ai",
    "https://mt-client-api-v1.singapore.agiliumtrade.ai",
    "https://mt-client-api-v1.sydney.agiliumtrade.ai",
]

def log(tag, msg, status="INFO"):
    print(f"[{status}] [{tag}] {msg}", flush=True)

def test_all():
    print("=" * 60, flush=True)
    print("MILITARY TEST SUITE - Full MetaAPI Endpoint Audit", flush=True)
    print("=" * 60, flush=True)

    # =============================================
    # TEST 1: Find the correct server
    # =============================================
    log("SERVER-SCAN", "Scanning all MetaAPI regions for active server...")
    working_server = None
    for server in SERVERS:
        try:
            url = f"{server}/users/current/accounts/{ACC_ID}/account-information"
            r = requests.get(url, headers=HEADERS, timeout=5)
            if r.status_code == 200:
                info = r.json()
                log("SERVER-SCAN", f"FOUND WORKING SERVER: {server}", "SUCCESS")
                log("SERVER-SCAN", f"  Balance=${info.get('balance')} Equity=${info.get('equity')}", "SUCCESS")
                working_server = server
                break
            else:
                log("SERVER-SCAN", f"  {server} -> {r.status_code}", "SKIP")
        except Exception as e:
            log("SERVER-SCAN", f"  {server} -> TIMEOUT/ERROR", "SKIP")

    if not working_server:
        log("SERVER-SCAN", "ALL SERVERS FAILED! Check API token or account ID.", "ERROR")
        print("=" * 60, flush=True)
        return

    BASE = working_server

    # =============================================
    # TEST 2: Fetch Positions (The Bug)
    # =============================================
    log("POSITIONS", f"Fetching positions from {BASE}...")
    try:
        r = requests.get(f"{BASE}/users/current/accounts/{ACC_ID}/positions", headers=HEADERS, timeout=10)
        log("POSITIONS", f"  Status: {r.status_code}", "INFO")
        if r.status_code == 200:
            positions = r.json()
            log("POSITIONS", f"  Count: {len(positions)}", "SUCCESS")
            for p in positions:
                log("POSITIONS", f"    -> {p.get('symbol')} {p.get('type')} vol={p.get('volume')}", "SUCCESS")
        else:
            log("POSITIONS", f"  RESPONSE: {r.text[:200]}", "ERROR")
    except Exception as e:
        log("POSITIONS", f"  CRASH: {e}", "ERROR")

    # =============================================
    # TEST 3: Symbol Price Sync (XAUUSDc detection)
    # =============================================
    log("PRICE-SYNC", "Hunting for correct XAUUSD symbol suffix...")
    for suffix in ["", "c", ".m", ".i", "m", "+"]:
        sym = f"XAUUSD{suffix}"
        try:
            r = requests.get(f"{BASE}/users/current/accounts/{ACC_ID}/symbols/{sym}/current-price", headers=HEADERS, timeout=5)
            if r.status_code == 200:
                price = r.json().get('bid', 0)
                if price and float(price) > 0:
                    log("PRICE-SYNC", f"  FOUND: {sym} = {price}", "SUCCESS")
                    break
            else:
                log("PRICE-SYNC", f"  {sym} -> {r.status_code}", "SKIP")
        except Exception as e:
            log("PRICE-SYNC", f"  {sym} -> ERROR: {e}", "SKIP")

    # =============================================
    # TEST 4: Place Dry-Run Trade (to /trade)
    # =============================================
    log("TRADE-ENDPOINT", f"Testing /trade endpoint with 0.01 lot BUY...")
    try:
        payload = {
            "symbol": "XAUUSDc",
            "actionType": "ORDER_TYPE_BUY",
            "volume": 0.01,
            "comment": "DRY-RUN-TEST"
        }
        r = requests.post(f"{BASE}/users/current/accounts/{ACC_ID}/trade", headers={**HEADERS, "Content-Type": "application/json"}, json=payload, timeout=10)
        log("TRADE-ENDPOINT", f"  Status: {r.status_code}", "INFO")
        log("TRADE-ENDPOINT", f"  Response: {r.text[:300]}", "INFO")
    except Exception as e:
        log("TRADE-ENDPOINT", f"  CRASH: {e}", "ERROR")

    # =============================================
    # TEST 5: VERIFY FIXED get_forex_data (RSI + Broker Price)
    # =============================================
    sys.path.append('backend')
    log("FX-DATA", "Testing FIXED get_forex_data for XAUUSD...")
    try:
        from data_fetcher import get_forex_data
        data = get_forex_data("XAUUSD")
        if data and data.get('rsi'):
            log("FX-DATA", f"  RSI={data['rsi']} | Price={data.get('lastPrice')} | Symbol={data.get('working_symbol')}", "SUCCESS")
        else:
            log("FX-DATA", f"  EMPTY or MISSING RSI. Got keys: {list(data.keys()) if data else 'None'}", "ERROR")
    except Exception as e:
        log("FX-DATA", f"  CRASH: {e}", "ERROR")

    # =============================================
    # TEST 6: Bitget API connectivity
    # =============================================
    log("BITGET", "Testing Bitget API...")
    try:
        r = requests.get("https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES", timeout=10, verify=False)
        if r.status_code == 200:
            log("BITGET", "  V2 API: REACHABLE", "SUCCESS")
        else:
            log("BITGET", f"  V2 API: {r.status_code}", "ERROR")
    except Exception as e:
        log("BITGET", f"  CRASH: {e}", "ERROR")

    print("=" * 60, flush=True)
    print("AUDIT COMPLETE", flush=True)
    print("=" * 60, flush=True)

if __name__ == "__main__":
    test_all()

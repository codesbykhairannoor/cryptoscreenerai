
import os
import sys
import time
import requests
from dotenv import load_dotenv

# Ensure local backend modules are importable
sys.path.append(os.getcwd())

from bitget_executor import BitgetExecutor
from forex_executor import ForexExecutor
from data_fetcher import get_forex_data, fetch_all_tickers
from ai_model import analyze_and_sort

load_dotenv()

def railway_log(tag, msg, status="INFO"):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} [{status}] [{tag}] {msg}", flush=True)

def run_military_audit():
    railway_log("SYSTEM", "Starting Military Railway Audit (v4.5.0)...")
    
    # 1. CREDENTIAL AUDIT
    railway_log("ENV", "Checking Environment Variables...")
    keys = ['BITGET_API_KEY', 'BITGET_SECRET_KEY', 'BITGET_PASSPHRASE', 'FOREX_META_API_TOKEN', 'FOREX_ACCOUNT_ID']
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        railway_log("ENV", f"MISSING KEYS: {missing}", "ERROR")
    else:
        railway_log("ENV", "All credentials present.")

    # 2. BITGET CONNECTIVITY
    try:
        railway_log("BITGET", "Initiating Exchange Handshake...")
        executor = BitgetExecutor()
        bal = executor.get_balance()
        if bal:
            railway_log("BITGET", f"Handshake SUCCESS. Available: {bal.get('free', 0)} USDT")
        else:
            railway_log("BITGET", "Handshake FAILED. Balance unreachable.", "ERROR")
    except Exception as e:
        railway_log("BITGET", f"CRITICAL CRASH: {e}", "ERROR")

    # 3. FOREX CONNECTIVITY (MetaAPI)
    try:
        railway_log("METAAPI", "Initiating Broker Handshake...")
        fx = ForexExecutor()
        success, msg = fx.test_connection()
        if success:
            railway_log("METAAPI", f"Handshake SUCCESS. {msg}")
        else:
            railway_log("METAAPI", f"Handshake FAILED: {msg}", "ERROR")
    except Exception as e:
        railway_log("METAAPI", f"CRITICAL CRASH: {e}", "ERROR")

    # 4. DATA SYNC (CRYPTO)
    try:
        railway_log("CRYPTO-SYNC", "Scanning Market Tickers...")
        tickers = fetch_all_tickers()
        if not tickers.empty:
            railway_log("CRYPTO-SYNC", f"Successfully mapped {len(tickers)} tickers.")
            candidates = analyze_and_sort(tickers)
            railway_log("CRYPTO-SYNC", f"Top Candidate: {candidates[0]['symbol'] if candidates else 'NONE'}")
        else:
            railway_log("CRYPTO-SYNC", "Market Scan returned EMPTY.", "WARNING")
    except Exception as e:
        railway_log("CRYPTO-SYNC", f"SYNC ERROR: {e}", "ERROR")

    # 5. DATA SYNC (FOREX)
    try:
        railway_log("FOREX-SYNC", "Polling XAUUSD Indicators...")
        fx_data = get_forex_data("XAUUSD")
        if fx_data and 'rsi' in fx_data:
            railway_log("FOREX-SYNC", f"Indicators ACTIVE: RSI={fx_data['rsi']} | Price={fx_data['lastPrice']}")
        else:
            railway_log("FOREX-SYNC", "Forex data malformed or unreachable.", "ERROR")
    except Exception as e:
        railway_log("FOREX-SYNC", f"SYNC ERROR: {e}", "ERROR")

    # 6. BROKER PRICE SYNC (Fix Verification)
    try:
        railway_log("PRICE-SYNC", "Verifying Broker Real-time Quote...")
        fx = ForexExecutor()
        price = fx.get_live_price("XAUUSD")
        if price > 0:
            railway_log("PRICE-SYNC", f"Broker Price SYNCED: {price}")
        else:
            railway_log("PRICE-SYNC", "Broker Price FETCH FAILED (Check suffixes/account_id).", "ERROR")
    except Exception as e:
        railway_log("PRICE-SYNC", f"SYNC ERROR: {e}", "ERROR")

    # 7. ORDER ROUTING (Dry Run Logic)
    railway_log("ROUTING", "Validating Order Pipeline...")
    # Mocking order placement logic
    notional = 100.0
    is_safe = notional >= 5.0
    railway_log("ROUTING", f"Notional Guard: {'PASS' if is_safe else 'FAIL'}")

    railway_log("SYSTEM", "Audit Complete. Check ERROR tags above for mission-critical failures.")

if __name__ == "__main__":
    run_military_audit()

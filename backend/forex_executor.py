import requests
import json
import os
import time
from dotenv import load_dotenv

load_dotenv()

class ForexExecutor:
    """
    Dedicated Forex Engine for MetaTrader 5 (via MetaAPI).
    Isolated from Crypto and Stock logic.
    """
    def __init__(self):
        self.api_token = os.getenv("FOREX_META_API_TOKEN")
        self.account_id = os.getenv("FOREX_ACCOUNT_ID")
        self.base_url = "https://mt-client-api-v1.new-york.agiliumtrade.ai"
        self.is_active = self.api_token is not None and self.account_id is not None

    def get_account_information(self):
        """Fetch real-time Forex account balance and equity"""
        if not self.is_active: return None
        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/account-information"
            headers = {"auth-token": self.api_token}
            res = requests.get(url, headers=headers, timeout=10)
            return res.json()
        except Exception as e:
            print(f"❌ [FOREX ERROR] Failed to fetch account info: {e}")
            return None

    def place_forex_order(self, symbol, side, volume=0.01, tp=None, sl=None):
        """
        Executes a professional Forex trade on MT5.
        Supports 1-pip scalping strategies with simultaneous execution.
        """
        if not self.is_active: 
            return False, "Forex API Token/Account ID belum dikonfigurasi di .env"

        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/trade"
            headers = {
                "auth-token": self.api_token,
                "Content-Type": "application/json"
            }
            
            # Professional MT5 Order Structure
            payload = {
                "actionType": "ORDER_TYPE_BUY" if side.lower() == 'buy' else "ORDER_TYPE_SELL",
                "symbol": symbol,
                "volume": volume,
                "stopLoss": sl,
                "takeProfit": tp,
                "comment": "CryptoScreener AI Sniper"
            }
            
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            result = res.json()
            
            if res.status_code == 200:
                print(f"✅ [FOREX SUCCESS] {side.upper()} {symbol} (Vol: {volume}) Placed on MT5!")
                return True, result
            else:
                return False, result.get("message", "Unknown MT5 Error")

        except Exception as e:
            return False, f"System Error: {str(e)}"

    def monitor_forex_market(self):
        """
        Dedicated scanner for Forex pairs (EURUSD, GBPUSD, XAUUSD).
        This runs in its own thread to avoid interfering with Crypto.
        """
        print("🌍 [SYSTEM] Forex Monitoring Engine AKTIF!")
        while True:
            # Placeholder for Forex Analysis Logic
            # (RSI, Institutional Flow, news-driven signals)
            time.sleep(60) # Scan every minute

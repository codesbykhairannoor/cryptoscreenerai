import requests
import json
import os
import time
from dotenv import load_dotenv

load_dotenv()

class ForexExecutor:
    """
    Dedicated Forex Engine for MetaTrader 5 (via MetaAPI).
    Focused on XAUUSD Institutional Scalping.
    """
    def __init__(self):
        self.api_token = os.getenv("FOREX_META_API_TOKEN")
        self.account_id = os.getenv("FOREX_ACCOUNT_ID")
        self.base_url = "https://mt-client-api-v1.london.agiliumtrade.ai"
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

    def test_connection(self):
        """Verify if the Exness MT5 account is ready for combat"""
        info = self.get_account_information()
        if info and 'balance' in info:
            print(f"✅ [FOREX] MT5 Connected! Balance: ${info['balance']} | Equity: ${info['equity']}")
            return True, f"Connected to Exness MT5 (Balance: ${info['balance']})"
        return False, "Failed to connect to MetaAPI. Check Token/ID or Dashboard Status."

    def place_forex_order(self, symbol, side, volume=0.01, tp=None, sl=None):
        """Executes a single MT5 order via MetaAPI"""
        if not self.is_active: return False, "Inactive"
        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/trade"
            headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
            payload = {
                "actionType": "ORDER_TYPE_BUY" if side.lower() == 'buy' else "ORDER_TYPE_SELL",
                "symbol": symbol,
                "volume": volume,
                "stopLoss": sl,
                "takeProfit": tp,
                "comment": "CryptoScreener AI Sniper"
            }
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            return res.status_code == 200, res.json()
        except Exception as e:
            return False, str(e)

    def place_xauusd_scalp_batch(self, side, trades_count=5, volume=0.01):
        """
        XAUUSD SCALPER MODE: Strikes Gold with multiple simultaneous trades.
        Ideal for 1-pip or tight scalping during high-volatility news.
        """
        print(f"🚀 [XAUUSD SNIPER] Triggering {trades_count} Scalp Trades ({side.upper()})!")
        results = []
        for i in range(trades_count):
            success, res = self.place_forex_order("XAUUSD", side, volume)
            results.append(success)
            time.sleep(0.1)
            
        success_count = results.count(True)
        print(f"✅ [XAUUSD SUCCESS] {success_count}/{trades_count} Trades Executed!")
        return success_count > 0

    def monitor_forex_market(self):
        """
        Institutional Gold & FX Scanner.
        Detects 'Smart Money' moves on XAUUSD.
        """
        print("🌍 [SYSTEM] Forex Monitoring Engine (XAUUSD Focus) AKTIF!")
        while True:
            try:
                # Periodic Connection Heartbeat
                if int(time.time()) % 300 < 60:
                    self.test_connection()
                
                # Placeholder for XAUUSD Analysis (Institutional Flow)
                # In a real scenario, we'd use MetaAPI WebSocket for tick-by-tick data
                time.sleep(60)
            except Exception as e:
                print(f"❌ [FOREX SCANNER ERROR] {e}")
                time.sleep(10)

if __name__ == "__main__":
    # Local Test
    fx = ForexExecutor()
    fx.test_connection()

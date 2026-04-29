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
            # FIX: Auto-detect Cent Account suffix (Exness uses 'c' for cent symbols)
            # If the user's EURUSD is EURUSDc, then XAUUSD must be XAUUSDc
            actual_symbol = symbol
            if "c" in symbol or self.account_id: # Strategy: Try to match account type
                # For safety, let's force 'c' if it's an Exness Cent account
                actual_symbol = f"{symbol}c" if not symbol.endswith('c') else symbol

            url = f"{self.base_url}/users/current/accounts/{self.account_id}/trade"
            headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
            payload = {
                "actionType": "ORDER_TYPE_BUY" if side.lower() == 'buy' else "ORDER_TYPE_SELL",
                "symbol": actual_symbol,
                "volume": volume,
                "stopLoss": sl,
                "takeProfit": tp,
                "comment": "CryptoScreener AI Sniper"
            }
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            result = res.json()
            
            if res.status_code == 200:
                print(f"✅ [FOREX SUCCESS] {side.upper()} {actual_symbol} placed!")
                return True, result
            else:
                print(f"❌ [FOREX REJECTED] {actual_symbol}: {result.get('message')}")
                return False, result
        except Exception as e:
            return False, str(e)

    def place_xauusd_scalp_batch(self, side, trades_count=5, volume=0.01, tp=None, sl=None):
        """
        XAUUSD SCALPER MODE: Strikes Gold with multiple simultaneous trades.
        Now supports SL/TP for every trade in the batch.
        """
        from database import log_trade
        print(f"🚀 [XAUUSD SNIPER] Triggering {trades_count} Scalp Trades ({side.upper()}) with SL/TP!")
        results = []
        for i in range(trades_count):
            success, res = self.place_forex_order("XAUUSD", side, volume, tp=tp, sl=sl)
            results.append(success)
            if success:
                # Log the first successful trade of the batch to the journal for tracking
                if i == 0: 
                    # Fetch price for accurate log
                    from data_fetcher import get_forex_data
                    price = get_forex_data("XAUUSD").get('lastPrice', 0)
                    log_trade("XAUUSD", price, tp, sl, market='forex')
            time.sleep(0.1)
            
        success_count = results.count(True)
        print(f"✅ [XAUUSD SUCCESS] {success_count}/{trades_count} Trades Executed with Safety!")
        return success_count > 0

    def monitor_forex_market(self):
        """
        Institutional Gold & FX Scanner (Super Smart).
        Detects News Spikes and Institutional Divergence on XAUUSD.
        """
        from sentiment import get_forex_news
        from data_fetcher import get_forex_data
        from database import log_trade
        print("🌍 [SYSTEM] Forex Monitoring Engine (XAUUSD Focus) AKTIF!")
        
        last_news_check = 0
        last_auto_trade = 0
        AUTO_COOLDOWN = 3600 # 1 Hour cooldown for auto-trades
        
        while True:
            try:
                # 1. Connection Heartbeat (Every 5 mins)
                if int(time.time()) % 300 < 10:
                    self.test_connection()
                
                # 2. News Sniper Check (Every 10 mins)
                if time.time() - last_news_check > 600:
                    news = get_forex_news()
                    print(news)
                    last_news_check = time.time()
                
                # 3. High-Frequency XAUUSD Auto-Scan
                fx_data = get_forex_data("XAUUSD")
                if fx_data:
                    inst_flow = fx_data.get('inst_flow', "NORMAL")
                    rsi = fx_data.get('rsi', 50)
                    
                    # SMART AUTO-TRADE: Institutional Flow + Oversold/Overbought RSI
                    should_auto = False
                    side = 'buy'
                    
                    if inst_flow == "INSTITUTIONAL_ACCUMULATION" and rsi < 40:
                        should_auto = True
                        side = 'buy'
                    elif inst_flow == "INSTITUTIONAL_ABSORPTION" and rsi > 65:
                        should_auto = True
                        side = 'sell'
                        
                    if should_auto and (time.time() - last_auto_trade > AUTO_COOLDOWN):
                        print(f"🎯 [FOREX AUTO-SNIPER] Institutional Setup Found on XAUUSD! Trading {side.upper()}...")
                        
                        # DYNAMIC RISK CALCULATOR: Use 1.5x ATR or fixed pips for Gold
                        price = fx_data['lastPrice']
                        atr = fx_data.get('atr', 1.5) # Default 1.5 pips volatility
                        
                        if side == 'buy':
                            tp = price + (atr * 2) 
                            sl = price - (atr * 1.5)
                        else:
                            tp = price - (atr * 2)
                            sl = price + (atr * 1.5)
                            
                        success = self.place_xauusd_scalp_batch(side, trades_count=3, volume=0.01, tp=tp, sl=sl)
                        if success:
                            last_auto_trade = time.time()
                
                time.sleep(15) # Scan every 15 seconds
                
            except Exception as e:
                print(f"❌ [FOREX SCANNER ERROR] {e}")
                time.sleep(10)

if __name__ == "__main__":
    fx = ForexExecutor()
    fx.test_connection()

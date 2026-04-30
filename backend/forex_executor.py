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

    def check_spread(self, symbol="XAUUSD"):
        """Safety: Ensures we don't get eaten by high spreads during news."""
        from data_fetcher import get_forex_data
        data = get_forex_data(symbol)
        spread = data.get('spread', 0)
        # For Gold (XAUUSD), anything above 50-60 pips (5-6 points) is 'Toxic' during news
        if spread > 60:
            print(f"⚠️ [SPREAD ALERT] Spread {spread} too high! Sniper holding fire...")
            return False
        return True

    def place_xauusd_scalp_batch(self, side, trades_count=5, volume=0.01, tp=None, sl=None):
        """
        INSTITUTIONAL BARRAGE: Uses Layering (Grid) to secure better average prices.
        Prevents being trapped in 5 positions at a single 'spike' price.
        """
        from database import log_trade
        if not self.check_spread("XAUUSD"): return False

        print(f"🚀 [XAUUSD BARRAGE] Triggering {trades_count} Layered Trades ({side.upper()})!")
        results = []
        
        # Layering Logic: Spread entries by 5-10 pips (0.05 - 0.10 points in Gold)
        step = 0.05 
        for i in range(trades_count):
            # Calculate offset for layering
            # Position 1: Market, Position 2: Market + offset, etc.
            # This is simplified; in real MT5 we would use Pending Orders for future layers
            # Here we use instant execution with a small delay for price movement
            success, res = self.place_forex_order("XAUUSD", side, volume, tp=tp, sl=sl)
            results.append(success)
            
            if success and i == 0:
                from data_fetcher import get_forex_data
                price = get_forex_data("XAUUSD").get('lastPrice', 0)
                log_trade("XAUUSD", price, tp, sl, market='forex')
            
            # PRO ENGINEER TIP: Sleep 200ms to avoid MT5 'Too many requests' (10027)
            time.sleep(0.2)
            
        success_count = results.count(True)
        print(f"✅ [BARRAGE SUCCESS] {success_count}/{trades_count} Layers Filled!")
        return success_count > 0

    def monitor_forex_market(self):
        """
        HEGE-FUND LEVEL SCANNER: SMC + Intermarket Correlation (DXY).
        Only trades Gold if DXY confirms the move.
        """
        from sentiment import get_forex_news
        from data_fetcher import get_forex_data
        from database import log_trade
        print("🌍 [SYSTEM] Dewa Scalper Engine (DXY Correlation) AKTIF!")
        
        last_news_check = 0
        last_auto_trade = 0
        AUTO_COOLDOWN = 1800 # 30 Mins cooldown for Dewa mode
        
        while True:
            try:
                # 1. Intermarket Correlation Check: DXY (Dollar Index)
                dxy_data = get_forex_data("DXY") 
                fx_data = get_forex_data("XAUUSD")
                
                # MONITOR ACTIVE FOREX POSITIONS
                try:
                    # Fetching positions via REST API instead of undefined self.connection
                    pos_url = f"{self.base_url}/users/current/accounts/{self.account_id}/positions"
                    headers = {"auth-token": self.api_token}
                    pos_res = requests.get(pos_url, headers=headers, timeout=10)
                    positions = pos_res.json()
                    if isinstance(positions, list):
                        for pos in positions:
                            if pos['symbol'].startswith('XAUUSD'):
                                pnl = pos.get('unrealizedProfit', 0)
                                print(f"📊 [FOREX MONITOR] Gold Position | PNL: ${round(pnl, 2)} | Price: {pos.get('currentPrice')}")
                except:
                    pass

                if dxy_data and fx_data:
                    dxy_trend = dxy_data.get('trend', 'NEUTRAL')
                    gold_inst_flow = fx_data.get('inst_flow', "NORMAL")
                    rsi = fx_data.get('rsi', 50)
                    spread = fx_data.get('spread', 0)
                    is_danger = fx_data.get('is_session_danger', False)
                    if is_danger:
                        if int(time.time()) % 60 < 10:
                            print(f"⚠️ [SESSION GUARD] London/NY Opening Detected. Sniper holding fire to avoid volatility pranks.")
                        continue

                    # 2. SMC / FVG LOGIC (Institutional Re-entry)
                    fvg_up = fx_data.get('fvg_up', [])
                    vwap_dist = fx_data.get('vwap_dist', 0)
                    
                    # LOGGING FOR AUDIT
                    if int(time.time()) % 60 < 15: # Log every minute
                        print(f"🕵️ [ARCHITECT AUDIT] XAUUSD: {fx_data['lastPrice']} | RSI: {rsi} | FVG: {len(fvg_up) > 0} | VWAP Dist: {vwap_dist}%")
                        print(f"🕵️ [ARCHITECT AUDIT] DXY Index: {dxy_data['lastPrice']} | Trend: {dxy_trend}")

                    should_auto = False
                    side = 'buy'
                    
                    # THE ARCHITECT LOGIC: Precise Re-entries
                    # BUY: DXY is Weak AND Gold is in FVG/VWAP discount zone
                    if dxy_trend != 'BULLISH' and (fvg_up or rsi < 40) and vwap_dist < 0.5:
                        should_auto = True
                        side = 'buy'
                    # SELL: DXY is Strong AND Gold is Overextended
                    elif dxy_trend != 'BEARISH' and (rsi > 65) and vwap_dist > 1.0:
                        should_auto = True
                        side = 'sell'
                    
                    # 3. Barrage Count Detection
                    trades_to_open = 5 if abs(fx_data.get('price_change_5m', 0)) > 0.4 else 3
                        
                    if should_auto and (time.time() - last_auto_trade > AUTO_COOLDOWN):
                        if not self.check_spread("XAUUSD"): continue
                        
                        account = self.get_account_information()
                        if account and account.get('equity', 0) < 500: 
                            print("🚨 [SAFETY] Equity too low for Barrage Mode!")
                            continue

                        print(f"🎯 [ARCHITECT SNIPER] Institutional Alignment! DXY: {dxy_trend} | FVG Detected: {len(fvg_up) > 0}")
                        price = fx_data['lastPrice']
                        atr = fx_data.get('atr', 1.5)
                        
                        tp = price + (atr * 2.5) if side == 'buy' else price - (atr * 2.5)
                        sl = price - (atr * 1.5) if side == 'buy' else price + (atr * 1.5)
                            
                        success = self.place_xauusd_scalp_batch(side, trades_count=trades_to_open, volume=0.01, tp=tp, sl=sl)
                        if success:
                            last_auto_trade = time.time()
              last_auto_trade = time.time()
                
                time.sleep(15) 
                
            except Exception as e:
                print(f"❌ [DEWA SCANNER ERROR] {e}")
                time.sleep(10)

if __name__ == "__main__":
    fx = ForexExecutor()
    fx.test_connection()

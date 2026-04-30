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
            actual_symbol = symbol
            if "c" in symbol or self.account_id: 
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

    def check_spread(self, symbol="XAUUSD"):
        """Safety: Ensures we don't get eaten by high spreads during news."""
        from data_fetcher import get_forex_data
        data = get_forex_data(symbol)
        spread = data.get('spread', 0)
        if spread > 60:
            print(f"⚠️ [SPREAD ALERT] Spread {spread} too high! Sniper holding fire...")
            return False
        return True

    def update_forex_sl(self, position_id, new_sl):
        """Update Stop Loss for an active MetaTrader 5 position."""
        if not self.is_active: return False
        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/positions/{position_id}"
            headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
            payload = {"stopLoss": new_sl}
            res = requests.put(url, headers=headers, json=payload, timeout=10)
            
            if res.status_code == 200 or res.status_code == 204:
                print(f"🏃 [FOREX TRAIL] Position {position_id} SL moved to {round(new_sl, 2)}")
                return True
            return False
        except Exception as e:
            print(f"⚠️ [FOREX TRAIL ERROR] {e}")
            return False


    def place_xauusd_scalp_batch(self, side, trades_count=5, volume=0.01, tp=None, sl=None):
        """
        INSTITUTIONAL BARRAGE: Uses Layering (Grid) to secure better average prices.
        """
        from database import log_trade
        if not self.check_spread("XAUUSD"): return False

        print(f"🚀 [XAUUSD BARRAGE] Triggering {trades_count} Layered Trades ({side.upper()})!")
        results = []
        
        for i in range(trades_count):
            success, res = self.place_forex_order("XAUUSD", side, volume, tp=tp, sl=sl)
            results.append(success)
            
            if success and i == 0:
                from data_fetcher import get_forex_data
                price = get_forex_data("XAUUSD").get('lastPrice', 0)
                log_trade("XAUUSD", price, tp, sl, market='forex')
            
            time.sleep(0.2)
            
        success_count = results.count(True)
        print(f"✅ [BARRAGE SUCCESS] {success_count}/{trades_count} Layers Filled!")
        return success_count > 0

    def monitor_forex_market(self):
        """
        HEGE-FUND LEVEL SCANNER: SMC + Intermarket Correlation (DXY).
        """
        from data_fetcher import get_forex_data
        from database import log_trade
        print("🌍 [SYSTEM] Dewa Scalper Engine (DXY Correlation) AKTIF!")
        
        last_auto_trade = 0
        AUTO_COOLDOWN = 1800 # 30 Mins cooldown
        
        while True:
            try:
                dxy_data = get_forex_data("DXY") 
                fx_data = get_forex_data("XAUUSD")
                
                # MONITOR ACTIVE FOREX POSITIONS
                try:
                    pos_url = f"{self.base_url}/users/current/accounts/{self.account_id}/positions"
                    headers = {"auth-token": self.api_token}
                    pos_res = requests.get(pos_url, headers=headers, timeout=10)
                    positions = pos_res.json()
                    
                    active_count = 0
                    if isinstance(positions, list):
                        active_count = len([p for p in positions if p.get('symbol', '').startswith('XAUUSD')])
                        # Only log summary every 1 minute to avoid spam
                        if int(time.time()) % 60 < 15:
                            print(f"📊 [FOREX MONITOR] Active Gold Positions: {active_count}/10")
                            
                        # Trailing Stop Loss Logic
                        for p in positions:
                            if not p.get('symbol', '').startswith('XAUUSD'): continue
                            
                            pos_id = p.get('id')
                            pos_type = p.get('type', '')
                            open_price = float(p.get('openPrice', 0))
                            current_price = float(p.get('currentPrice', 0))
                            current_sl = float(p.get('stopLoss', 0) or 0)
                            
                            # For Gold, trailing based on spread and volatility
                            spread_pts = spread / 100 # Assuming spread is in points (e.g. 200 = $2.00)
                            safety_buffer = max(1.5, spread_pts * 1.5)
                            
                            if pos_type == 'POSITION_TYPE_BUY' and current_price - open_price > safety_buffer:
                                new_sl = current_price - (safety_buffer * 0.7)
                                if new_sl > current_sl:
                                    self.update_forex_sl(pos_id, new_sl)
                            elif pos_type == 'POSITION_TYPE_SELL' and open_price - current_price > safety_buffer:
                                new_sl = current_price + (safety_buffer * 0.7)
                                if current_sl == 0 or new_sl < current_sl:
                                    self.update_forex_sl(pos_id, new_sl)
                except Exception as e:
                    print(f"⚠️ [FOREX MONITOR ERROR] Failed to fetch positions: {e}")
                    positions = []
                    active_count = 0

                if dxy_data and fx_data:
                    dxy_trend = dxy_data.get('trend', 'NEUTRAL')
                    rsi = fx_data.get('rsi', 50)
                    spread = fx_data.get('spread', 0)
                    
                    is_danger = fx_data.get('is_session_danger', False)
                    if is_danger:
                        if int(time.time()) % 60 < 10:
                            print(f"⚠️ [SESSION GUARD] London/NY Opening Detected. Sniper holding fire.")
                        continue

                    fvg_up = fx_data.get('fvg_up', [])
                    vwap_dist = fx_data.get('vwap_dist', 0)
                    
                    if int(time.time()) % 60 < 15:
                        print(f"🕵️ [ARCHITECT AUDIT] XAUUSD: {fx_data['lastPrice']} | RSI: {rsi} | FVG: {len(fvg_up) > 0} | VWAP Dist: {vwap_dist}%")
                        print(f"🕵️ [ARCHITECT AUDIT] DXY Index: {dxy_data['lastPrice']} | Trend: {dxy_trend}")

                    should_auto = False
                    side = 'buy'
                    
                    # CREATIVE SCALPING: Allow entries even if DXY is neutral/counter if RSI is extreme
                    if (dxy_trend != 'BULLISH' and (fvg_up or rsi < 40) and vwap_dist < 0.5) or (rsi < 30):
                        should_auto = True
                        side = 'buy'
                    elif (dxy_trend != 'BEARISH' and (rsi > 60) and vwap_dist > 0.8) or (rsi > 75):
                        should_auto = True
                        side = 'sell'
                    
                    trades_to_open = 5 if abs(fx_data.get('price_change_5m', 0)) > 0.4 else 3
                        
                    if should_auto and (time.time() - last_auto_trade > AUTO_COOLDOWN):
                        if active_count >= 10:
                            if int(time.time()) % 300 < 15: # Log once every 5 mins
                                print(f"🚨 [FOREX LIMIT] Max positions reached ({active_count}). Skipping trade.")
                            continue

                        if not self.check_spread("XAUUSD"): continue
                        
                        account = self.get_account_information()
                        if account and account.get('equity', 0) < 500: 
                            print("🚨 [SAFETY] Equity too low for Barrage Mode!")
                            continue

                        print(f"🎯 [ARCHITECT SNIPER] Institutional Alignment! DXY: {dxy_trend}")
                        price = fx_data['lastPrice']
                        atr = fx_data.get('atr', 1.5)
                        
                        tp = price + (atr * 2.5) if side == 'buy' else price - (atr * 2.5)
                        sl = price - (atr * 1.5) if side == 'buy' else price + (atr * 1.5)
                            
                        success = self.place_xauusd_scalp_batch(side, trades_count=trades_to_open, volume=0.01, tp=tp, sl=sl)
                        if success:
                            last_auto_trade = time.time()
                
                time.sleep(15) 
                
            except Exception as e:
                print(f"❌ [DEWA SCANNER ERROR] {e}")
                time.sleep(10)

if __name__ == "__main__":
    fx = ForexExecutor()
    fx.test_connection()

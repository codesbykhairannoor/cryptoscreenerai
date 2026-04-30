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
            print(f"[FOREX ERROR] Failed to fetch account info: {e}")
            return None

    def test_connection(self):
        """Verify if the Exness MT5 account is ready for combat"""
        info = self.get_account_information()
        if info and 'balance' in info:
            print(f"[FOREX] MT5 Connected! Balance: ${info['balance']} | Equity: ${info['equity']}")
            return True, f"Connected to Exness MT5 (Balance: ${info['balance']})"
        return False, "Failed to connect to MetaAPI. Check Token/ID or Dashboard Status."

    def place_forex_order(self, symbol, side, volume=0.01, tp=None, sl=None):
        """Executes a single MT5 order via MetaAPI"""
        if not self.is_active: return False, "Inactive"
        try:
            actual_symbol = symbol
            # Smart suffix detection: try provided symbol first, then 'c' if fails
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/trade"
            headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
            
            payload = {
                "actionType": "ORDER_TYPE_BUY" if side.lower() == 'buy' else "ORDER_TYPE_SELL",
                "symbol": actual_symbol,
                "volume": volume,
                "stopLoss": sl,
                "takeProfit": tp,
                "comment": "CryptoScreener AI Sniper V2"
            }
            
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            result = res.json()
            
            # If symbol not found, try with 'c' suffix (common for Exness Pro/Raw)
            if res.status_code != 200 and "symbol not found" in str(result).lower() and not actual_symbol.endswith('c'):
                actual_symbol += 'c'
                payload['symbol'] = actual_symbol
                res = requests.post(url, headers=headers, json=payload, timeout=10)
                result = res.json()

            if res.status_code == 200:
                print(f"[FOREX SUCCESS] {side.upper()} {actual_symbol} placed!")
                return True, result
            else:
                print(f"[FOREX REJECTED] {actual_symbol}: {result.get('message')}")
                return False, result
        except Exception as e:
            return False, str(e)

    def check_spread(self, symbol="XAUUSD"):
        """Safety: Ensures we don't get eaten by high spreads during news."""
        from data_fetcher import get_forex_data
        data = get_forex_data(symbol)
        spread = data.get('spread', 0)
        # Relaxed spread limit for aggressiveness (from 60 to 100)
        if spread > 100:
            print(f"[SPREAD ALERT] Spread {spread} too high! Sniper holding fire...")
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
                print(f"[FOREX TRAIL] Position {position_id} SL moved to {round(new_sl, 2)}")
                return True
            return False
        except Exception as e:
            print(f"[FOREX TRAIL ERROR] {e}")
            return False

    def place_xauusd_scalp_batch(self, side, trades_count=5, volume=0.01, tp=None, sl=None):
        """
        INSTITUTIONAL BARRAGE: Uses Layering (Grid) to secure better average prices.
        """
        from database import log_trade
        if not self.check_spread("XAUUSD"): return False

        print(f"[XAUUSD BARRAGE] Triggering {trades_count} Layered Trades ({side.upper()})!")
        results = []
        
        for i in range(trades_count):
            success, res = self.place_forex_order("XAUUSD", side, volume, tp=tp, sl=sl)
            results.append(success)
            
            if success and i == 0:
                from data_fetcher import get_forex_data
                price = get_forex_data("XAUUSD").get('lastPrice', 0)
                log_trade("XAUUSD", price, tp, sl, market='forex')
            
            time.sleep(0.1) # Faster batch execution
            
        success_count = results.count(True)
        print(f"[BARRAGE SUCCESS] {success_count}/{trades_count} Layers Filled!")
        return success_count > 0

    def monitor_forex_market(self):
        """
        Dewa Scalper Engine V2: Aggressive SMC + DXY Correlation.
        """
        from data_fetcher import get_forex_data
        from database import log_trade
        print("[SYSTEM] Dewa Scalper Engine V2 (AGRESSIVE) AKTIF!")
        
        last_auto_trade = 0
        AUTO_COOLDOWN = 300 # 5 Mins cooldown (Aggressive)
        
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
                        active_count = len([p for p in positions if p.get('symbol', '').upper().startswith('XAUUSD')])
                        
                        if int(time.time()) % 60 < 15:
                            print(f"[FOREX MONITOR] Active Gold Positions: {active_count}/15")
                            
                        # Trailing Stop Loss Logic (PINTER: Breakeven strategy)
                        for p in positions:
                            if not p.get('symbol', '').upper().startswith('XAUUSD'): continue
                            
                            pos_id = p.get('id')
                            pos_type = p.get('type', '')
                            open_price = float(p.get('openPrice', 0))
                            current_price = float(p.get('currentPrice', 0))
                            current_sl = float(p.get('stopLoss', 0) or 0)
                            
                            spread = fx_data.get('spread', 0)
                            spread_pts = spread / 100 
                            safety_buffer = max(1.0, spread_pts * 1.2) # Tightened buffer
                            
                            if pos_type == 'POSITION_TYPE_BUY' and current_price - open_price > safety_buffer:
                                new_sl = open_price + 0.1 # Move to BE+1
                                if new_sl > current_sl:
                                    self.update_forex_sl(pos_id, new_sl)
                            elif pos_type == 'POSITION_TYPE_SELL' and open_price - current_price > safety_buffer:
                                new_sl = open_price - 0.1 # Move to BE+1
                                if current_sl == 0 or new_sl < current_sl:
                                    self.update_forex_sl(pos_id, new_sl)
                except Exception as e:
                    print(f"[FOREX MONITOR ERROR] {e}")
                    positions = []
                    active_count = 0

                if fx_data:
                    rsi = fx_data.get('rsi', 50)
                    vwap_dist = fx_data.get('vwap_dist', 0)
                    dxy_trend = dxy_data.get('trend', 'NEUTRAL') if dxy_data else 'NEUTRAL'
                    
                    if int(time.time()) % 60 < 15:
                        print(f"[ARCHITECT AUDIT] XAUUSD: {fx_data['lastPrice']} | RSI: {rsi} | VWAP Dist: {vwap_dist}%")
                        if dxy_data: print(f"[ARCHITECT AUDIT] DXY Index: {dxy_data['lastPrice']} | Trend: {dxy_trend}")

                    should_auto = False
                    side = 'buy'
                    confidence = 0
                    
                    # AGGRESSIVE LONG LOGIC
                    if rsi < 35 or (rsi < 45 and dxy_trend != 'BULLISH'):
                        should_auto = True
                        side = 'buy'
                        confidence = 1 if rsi < 30 else 0
                        
                    # AGGRESSIVE SHORT LOGIC
                    elif rsi > 65 or (rsi > 55 and dxy_trend != 'BEARISH'):
                        should_auto = True
                        side = 'sell'
                        confidence = 1 if rsi > 70 else 0
                    
                    # Dynamic Trade Sizing
                    trades_to_open = 5 if confidence == 1 else 3
                        
                    if should_auto and (time.time() - last_auto_trade > AUTO_COOLDOWN):
                        if active_count >= 15: # Increased limit
                            continue

                        if not self.check_spread("XAUUSD"): continue
                        
                        account = self.get_account_information()
                        if account and account.get('equity', 0) < 100: # Lower gate
                            print(f"[SAFETY] Equity too low for AGGRESSIVE Mode!")
                            continue

                        print(f"[ARCHITECT SNIPER] Aggressive Entry Triggered! Side: {side.upper()}")
                        price = fx_data['lastPrice']
                        atr = fx_data.get('atr', 1.0)
                        
                        # Institutional SL/TP Scaling
                        tp_mult = 3.0 if confidence == 1 else 2.0
                        sl_mult = 2.0
                        
                        tp = price + (atr * tp_mult) if side == 'buy' else price - (atr * tp_mult)
                        sl = price - (atr * sl_mult) if side == 'buy' else price + (atr * sl_mult)
                            
                        success = self.place_xauusd_scalp_batch(side, trades_count=trades_to_open, volume=0.01, tp=tp, sl=sl)
                        if success:
                            last_auto_trade = time.time()
                
                time.sleep(10) # Faster scanning
                
            except Exception as e:
                print(f"[DEWA SCANNER ERROR] {e}")
                time.sleep(5)

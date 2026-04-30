import requests
import json
import os
import time
from dotenv import load_dotenv

load_dotenv()

class ForexExecutor:
    """
    Dedicated Forex Engine for MetaTrader 5 (via MetaAPI).
    Focused on XAUUSD Institutional Scalping with SMC and Sentiment.
    """
    def __init__(self):
        self.api_token = os.getenv("FOREX_META_API_TOKEN")
        self.account_id = os.getenv("FOREX_ACCOUNT_ID")
        self.base_url = "https://mt-client-api-v1.london.agiliumtrade.ai"
        self.is_active = self.api_token is not None and self.account_id is not None

    def get_account_information(self):
        if not self.is_active: return None
        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/account-information"
            headers = {"auth-token": self.api_token}
            res = requests.get(url, headers=headers, timeout=10)
            return res.json()
        except Exception as e:
            print(f"[FOREX ERROR] Account fetch failed: {e}")
            return None

    def test_connection(self):
        info = self.get_account_information()
        if info and 'balance' in info:
            return True, f"Connected to MT5 (Balance: ${info['balance']})"
        return False, "MT5 Connection Failed."

    def place_forex_order(self, symbol, side, volume=0.01, tp=None, sl=None):
        if not self.is_active: return False, "Inactive"
        try:
            actual_symbol = symbol
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/trade"
            headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
            
            payload = {
                "actionType": "ORDER_TYPE_BUY" if side.lower() == 'buy' else "ORDER_TYPE_SELL",
                "symbol": actual_symbol,
                "volume": volume,
                "stopLoss": sl,
                "takeProfit": tp,
                "comment": "Dewa Sniper SMC V2"
            }
            
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            result = res.json()
            
            # Suffix auto-retry (Exness specific)
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

    def update_forex_sl(self, position_id, new_sl):
        if not self.is_active: return False
        try:
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/positions/{position_id}"
            headers = {"auth-token": self.api_token, "Content-Type": "application/json"}
            payload = {"stopLoss": new_sl}
            res = requests.put(url, headers=headers, json=payload, timeout=10)
            return res.status_code in [200, 204]
        except: return False

    def monitor_forex_market(self):
        """
        Dewa Scalper Engine V2 (SMC + Liquidity Sweep + Order Flow).
        """
        from data_fetcher import get_forex_data
        from database import log_trade
        print("[SYSTEM] Dewa Scalper Engine V2 (SMC & OrderFlow) AKTIF!")
        
        last_auto_trade = 0
        AUTO_COOLDOWN = 300 # 5 Mins
        
        while True:
            try:
                fx_data = get_forex_data("XAUUSD")
                dxy_data = get_forex_data("DXY")
                
                # Fetch positions for trailing and limits
                pos_url = f"{self.base_url}/users/current/accounts/{self.account_id}/positions"
                headers = {"auth-token": self.api_token}
                pos_res = requests.get(pos_url, headers=headers, timeout=10)
                positions = pos_res.json() if pos_res.status_code == 200 else []
                active_count = len([p for p in positions if 'XAU' in p.get('symbol', '').upper()])

                if fx_data:
                    rsi = fx_data.get('rsi', 50)
                    vwap_dist = fx_data.get('vwap_dist', 0)
                    spread = fx_data.get('spread', 0)
                    
                    # SMC INDICATORS (The 'Pinter' Part)
                    ob_status = fx_data.get('order_block', 'NONE')
                    fvg_status = fx_data.get('fvg', 'NONE')
                    liq_sweep = fx_data.get('is_liquidity_sweep', False)
                    inst_flow = fx_data.get('inst_flow', 'NORMAL')
                    
                    if int(time.time()) % 20 < 10:
                        total_lots = sum(float(p.get('volume', 0)) for p in positions)
                        print(f"🌍 [FOREX DASHBOARD] Price: {fx_data['lastPrice']} | Trades: {len(positions)} | Lots: {round(total_lots, 2)}")
                        print(f"📊 [FOREX METRICS] RSI: {rsi} | OB: {ob_status} | Flow: {inst_flow}")
                        if liq_sweep: print(f"🔥 [SMC ALERT] Liquidity Sweep Detected on Gold!")

                    # AGGRESSIVE STRATEGY: SMC + Sentiment
                    should_trade = False
                    side = None
                    confidence = 0
                    
                    # BUY LOGIC: Bullish OB/FVG + Oversold OR Liquidity Sweep + Institutional Accumulation
                    if (ob_status == 'BULLISH' or fvg_status == 'BULLISH' or liq_sweep) and rsi < 50:
                        should_trade = True
                        side = 'buy'
                        confidence = 1 if inst_flow == 'INSTITUTIONAL_ACCUMULATION' else 0
                        
                    # SELL LOGIC: Bearish OB/FVG + Overbought OR DXY Bullish Strong
                    elif (ob_status == 'BEARISH' or fvg_status == 'BEARISH' or rsi > 70):
                        should_trade = True
                        side = 'sell'
                        confidence = 1 if inst_flow == 'INSTITUTIONAL_ABSORPTION' else 0

                    if should_trade and (time.time() - last_auto_trade > AUTO_COOLDOWN):
                        if active_count >= 10: continue
                        if spread > 80: continue # Spread safety
                        
                        # Barrage based on confidence
                        trades_count = 5 if confidence == 1 else 3
                        atr = fx_data.get('atr', 1.0)
                        price = fx_data['lastPrice']
                        
                        tp = price + (atr * 3) if side == 'buy' else price - (atr * 3)
                        sl = price - (atr * 2) if side == 'buy' else price + (atr * 2)
                        
                        print(f"[ARCHITECT SNIPER] SMC Entry: {side.upper()} | Confidence: {confidence}")
                        
                        # Execute Batch
                        for i in range(trades_count):
                            success, _ = self.place_forex_order("XAUUSD", side, 0.01, tp=tp, sl=sl)
                            if success and i == 0:
                                log_trade("XAUUSD", price, tp, sl, market='forex')
                            time.sleep(0.1)
                        
                        last_auto_trade = time.time()

                    # PINTER TRAILING: Secure profits
                    for p in positions:
                        if 'XAU' not in p.get('symbol', '').upper(): continue
                        open_price = float(p.get('openPrice', 0))
                        current_price = float(p.get('currentPrice', 0))
                        pos_id = p.get('id')
                        
                        # Move to BE once profit is > 1.5 ATR points
                        if p.get('type') == 'POSITION_TYPE_BUY' and (current_price - open_price) > 1.2:
                            self.update_forex_sl(pos_id, open_price + 0.1)
                        elif p.get('type') == 'POSITION_TYPE_SELL' and (open_price - current_price) > 1.2:
                            self.update_forex_sl(pos_id, open_price - 0.1)

                time.sleep(10)
            except Exception as e:
                print(f"[FOREX ENGINE ERROR] {e}")
                time.sleep(10)

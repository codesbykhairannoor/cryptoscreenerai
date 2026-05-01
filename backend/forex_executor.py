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
        
        # Institutional Forex Audit
        if self.is_active:
            try:
                info = self.get_account_information()
                if info:
                    print(f"[FOREX STARTUP AUDIT] MT5 Balance: ${info.get('balance', 0)} (Equity: ${info.get('equity', 0)})")
                
                # Check for active positions on startup
                pos_url = f"{self.base_url}/users/current/accounts/{self.account_id}/positions"
                headers = {"auth-token": self.api_token}
                pos_res = requests.get(pos_url, headers=headers, timeout=10)
                if pos_res.status_code == 200:
                    positions = pos_res.json()
                    if positions:
                        print(f"[FOREX STARTUP AUDIT] Active Trades: {len(positions)}")
                        if len(positions) <= 5:
                            for p in positions:
                                print(f"   > {p.get('symbol')} | Vol: {p.get('volume')} | ID: {p.get('id')}")
                        else:
                            print("   > (Position list collapsed: >5 trades active)")
                    else:
                        print("[FOREX STARTUP AUDIT] No active trades found.")
            except:
                pass

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

    def get_live_price(self, symbol):
        """Fetches EXACT price seen by the broker with suffix detection"""
        suffixes = ["", "c", ".m", ".i", "+", "#"]
        for s in suffixes:
            try:
                actual_sym = symbol + s
                url = f"{self.base_url}/users/current/accounts/{self.account_id}/symbols/{actual_sym}/current-price"
                headers = {"auth-token": self.api_token}
                res = requests.get(url, headers=headers, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    p = float(data.get('bid', data.get('ask', 0)))
                    if p > 0: return p
            except: continue
        return 0

    def place_forex_order(self, symbol, side, amount, tp=None, sl=None):
        try:
            actual_symbol = symbol
            url = f"{self.base_url}/users/current/accounts/{self.account_id}/trade"
            headers = {
                "auth-token": self.api_token,
                "Content-Type": "application/json"
            }
            
            payload = {
                "symbol": actual_symbol,
                "actionType": "ORDER_TYPE_BUY" if side.lower() == 'buy' else "ORDER_TYPE_SELL",
                "volume": amount,
                "stopLoss": sl,
                "takeProfit": tp,
                "comment": "Dewa Sniper SMC V2"
            }
            
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            result = res.json()
            
            if res.status_code == 200:
                print(f"[FOREX SUCCESS] {side.upper()} {actual_symbol} placed!")
                return True, result
            else:
                # Suffix hunting if failed
                if "symbol not found" in str(result).lower() and not actual_symbol.endswith('c'):
                    return self.place_forex_order(symbol + 'c', side, amount, tp, sl)
                print(f"[FOREX FAILED] {actual_symbol}: {result.get('message', 'Unknown Error')}")
                return False, str(result)
        except Exception as e:
            print(f"[FOREX API CRASH] {e}")
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
        AUTO_COOLDOWN = 60 # Increased to 60s to prevent spamming
        
        while True:
            try:
                fx_data = get_forex_data("XAUUSD")
                dxy_data = get_forex_data("DXY")
                
                # Fetch positions for trailing and limits
                pos_url = f"{self.base_url}/users/current/accounts/{self.account_id}/positions"
                headers = {"auth-token": self.api_token}
                pos_res = requests.get(pos_url, headers=headers, timeout=10)
                positions = pos_res.json() if pos_res.status_code == 200 else []
                # Count ALL open positions
                active_count = len(positions) if isinstance(positions, list) else 0

                # GLOBAL EQUITY GUARD: Halt if drawdown > 5%
                info = self.get_account_information()
                if info:
                    balance = float(info.get('balance', 0))
                    equity = float(info.get('equity', 0))
                    if equity < (balance * 0.95):
                        print(f"[EQUITY GUARD] Extreme Drawdown! Equity: ${equity}. Halting new trades.")
                        time.sleep(60)
                        continue

                if fx_data:
                    rsi = fx_data.get('rsi', 50)
                    ob_status = fx_data.get('order_block', 'NONE')
                    fvg_status = fx_data.get('fvg', 'NONE')
                    liq_sweep = fx_data.get('is_liquidity_sweep', False)
                    inst_flow = fx_data.get('inst_flow', 'NORMAL')
                    spread = fx_data.get('spread', 0)
                    
                    # Fetch EXACT Price from Broker (MT5 Sync)
                    broker_price = self.get_live_price("XAUUSD")
                    if broker_price == 0: broker_price = fx_data['lastPrice']
                    
                    if int(time.time()) % 15 < 5:
                        total_lots = sum(float(p.get('volume', 0)) for p in positions)
                        print(f"[FOREX DASHBOARD] Price: {broker_price} | Trades: {len(positions)} | Lots: {round(total_lots, 2)}")

                    should_trade = False
                    side = 'buy'
                    confidence = 0
                    
                    # PREDICTIVE FUTURE LOGIC (MSS & CHoCH)
                    mss_bull = fx_data.get('mss_bullish', False)
                    mss_bear = fx_data.get('mss_bearish', False)
                    choch_bull = fx_data.get('choch_bullish', False)
                    choch_bear = fx_data.get('choch_bearish', False)
                    fib_ext = fx_data.get('fib_ext', broker_price)
                    trend = fx_data.get('trend', 'NEUTRAL')
                    
                    # WHALE & OBI CONFIRMATION (The Institutional Seal)
                    obi = fx_data.get('obi', 0)
                    whale_sig = fx_data.get('whale_signal', 'NORMAL')
                    
                    # BUY: Predictive Shift + Whale Support
                    if (mss_bull or (choch_bull and liq_sweep)) and trend == 'BULLISH':
                        if obi > 0.1 or whale_sig == 'WHALE_BUY':
                            should_trade = True
                            side = 'buy'
                            confidence = 1 if inst_flow == 'INSTITUTIONAL_ACCUMULATION' else 0
                    
                    # SELL: Predictive Shift + Whale Resistance
                    elif (mss_bear or (choch_bear and liq_sweep)) and trend == 'BEARISH':
                        if obi < -0.1 or whale_sig == 'WHALE_SELL':
                            should_trade = True
                            side = 'sell'
                            confidence = 1 if inst_flow == 'INSTITUTIONAL_ABSORPTION' else 0

                    # GENIUS DXY SHIELD: Don't fight the Dollar
                    dxy_trend = dxy_data.get('trend', 'NEUTRAL')
                    if should_trade:
                        if side == 'buy' and dxy_trend == 'BULLISH': should_trade = False
                        if side == 'sell' and dxy_trend == 'BEARISH': should_trade = False

                    if should_trade and (time.time() - last_auto_trade > AUTO_COOLDOWN):
                        if active_count >= 10:
                            print(f"[FOREX LIMIT] {active_count}/10 positions. Holding.")
                            continue
                        if spread > 150: continue  # Spread safety
                        
                        # Use working_symbol from fx_data (e.g. XAUUSDc)
                        trade_symbol = fx_data.get('working_symbol', 'XAUUSDc')
                        
                        # DYNAMIC LOT SIZING (Cent Account Awareness)
                        # Rule: 0.01 lot per $100 (10,000 cents) of balance
                        balance = float(info.get('balance', 0))
                        calculated_lot = round((balance / 10000) * 0.01, 2)
                        final_lot = max(0.01, min(calculated_lot, 1.0))
                        
                        # 1:2 RISK REWARD (Military Precision)
                        # 10 Pips = 1.0 Price Point on XAUUSD
                        sl_dist = 1.0
                        tp_dist = 2.0
                        
                        sl = broker_price - sl_dist if side == 'buy' else broker_price + sl_dist
                        tp = broker_price + tp_dist if side == 'buy' else broker_price - tp_dist
                        
                        print(f"[MILITARY FOREX] {side.upper()} Barrage! Price: {broker_price} | Lot: {final_lot} | SL: 10p | TP: 20p")
                        
                        for i in range(trades_count):
                            success, _ = self.place_forex_order(trade_symbol, side, final_lot, tp=tp, sl=sl)
                            if success and i == 0:
                                log_trade(trade_symbol, broker_price, tp, sl, market='forex')
                            time.sleep(0.1)
                        
                        last_auto_trade = time.time()

                    # MILITARY PIP TRAILING (Secure Profits Dynamically)
                    for p in positions:
                        if 'XAU' not in p.get('symbol', '').upper(): continue
                        open_price = float(p.get('openPrice', 0))
                        current_price = float(p.get('currentPrice', 0))
                        pos_id = p.get('id')
                        pos_type = p.get('type') # POSITION_TYPE_BUY or POSITION_TYPE_SELL
                        
                        # Calculate current profit in points (1.0 = 10 pips)
                        profit_dist = (current_price - open_price) if pos_type == 'POSITION_TYPE_BUY' else (open_price - current_price)
                        
                        # 1. MOVE TO BREAKEVEN (At +10 Pips)
                        if profit_dist >= 1.0: # 10 Pips
                            new_sl = open_price + 0.1 if pos_type == 'POSITION_TYPE_BUY' else open_price - 0.1
                            self.update_forex_sl(pos_id, new_sl)
                        
                        # 2. PROGRESSIVE TRAIL (Every +5 Pips after BE)
                        if profit_dist >= 1.5: # 15 Pips
                            # Trail 5 pips behind current price
                            trail_sl = current_price - 0.5 if pos_type == 'POSITION_TYPE_BUY' else current_price + 0.5
                            self.update_forex_sl(pos_id, trail_sl)

                time.sleep(1)
            except Exception as e:
                print(f"[FOREX ENGINE ERROR] {e}")
                time.sleep(1)

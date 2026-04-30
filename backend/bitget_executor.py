import ccxt
import os
import time
import traceback
from dotenv import load_dotenv

load_dotenv()

# Suppress InsecureRequestWarning for institutional-grade log cleanliness
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class BitgetExecutor:
    def __init__(self):
        self.api_key = os.getenv("BITGET_API_KEY")
        self.secret_key = os.getenv("BITGET_SECRET_KEY")
        self.passphrase = os.getenv("BITGET_PASSPHRASE", "")
        
        self.exchange = ccxt.bitget({
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'password': self.passphrase,
            'enableRateLimit': True,
            'timeout': 30000,
            'options': {
                'defaultType': 'swap',
                'posMode': 'unilateral' 
            }
        })
        print(f"[INIT] Bitget API Key: {self.api_key[:5]}...{self.api_key[-5:]}")
        print("[INIT] Bitget V3 UTA Ready.")

    def _clean_symbol(self, s):
        """Standardizes symbol format to base coin"""
        if not s: return ""
        return s.upper().replace('USDT', '').replace('/', '').split(':')[0].split('_')[0]

    def _v3_request(self, method, path, query=""):
        """Helper for Bitget V3 UTA Signed Requests"""
        import requests, hmac, hashlib, base64
        ts = str(int(time.time() * 1000))
        full_path = f"{path}?{query}" if query else path
        
        message = ts + method.upper() + full_path
        mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
        sign = base64.b64encode(mac.digest()).decode('utf8')
        
        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }
        
        url = f"https://api.bitget.com{full_path}"
        # Increased timeout to 20s for unstable connections
        res = requests.request(method, url, headers=headers, timeout=20, verify=False)
        return res.json()

    def test_connection(self):
        try:
            balance = self.get_balance()
            return True, f"Bitget UTA Connected. Balance: {balance['total']} USDT"
        except Exception as e:
            return False, f"Connection Failed: {str(e)}"

    def get_balance(self):
        """Fetches balance via V3 /api/v3/account/assets"""
        try:
            data = self._v3_request("GET", "/api/v3/account/assets", "category=USDT-FUTURES")
            if data.get('code') == '00000':
                assets = data.get('data', {}).get('list', [])
                for a in assets:
                    if a.get('marginCoin') == 'USDT':
                        return {
                            'total': float(a.get('equity', 0)),
                            'free': float(a.get('available', 0))
                        }
            return {'total': 0, 'free': 0}
        except Exception as e:
            print(f"[V3 BALANCE ERROR] {e}")
            return {'total': 0, 'free': 0}

    def get_all_positions(self):
        """Fetches positions via V3 /api/v3/position/current-position"""
        all_pos = []
        try:
            data = self._v3_request("GET", "/api/v3/position/current-position", "category=USDT-FUTURES")
            if data.get('code') == '00000':
                pos_list = data.get('data', {}).get('list', [])
                for p in pos_list:
                    sz = float(p.get('total', 0) or 0)
                    if sz > 0:
                        instId = p.get('symbol', '')
                        symbol = f"{instId.replace('USDT', '')}/USDT:USDT" if "USDT" in instId and ":" not in instId else instId
                        entry = float(p.get('avgPrice') or p.get('breakEvenPrice') or 0)
                        
                        all_pos.append({
                            'symbol': symbol,
                            'instId': instId,
                            'side': p.get('posSide', 'long'),
                            'size': sz,
                            'entry': entry,
                            'mark_price': float(p.get('markPrice', 0) or 0),
                            'pnl': float(p.get('unrealisedPnl', 0) or 0)
                        })
            else:
                print(f"[V3 POS ERROR] {data}")
        except Exception as e:
            print(f"[V3 POS CRITICAL] {e}")
        return all_pos

    def get_pending_plan_orders(self, symbol=None):
        """Fetches pending orders via V3 /api/v3/trade/unfilled-orders"""
        all_plans = []
        try:
            query = "category=USDT-FUTURES"
            if symbol:
                instId = symbol.replace('/', '').replace(':USDT', '')
                query += f"&symbol={instId}"
            
            data = self._v3_request("GET", "/api/v3/trade/unfilled-orders", query)
            if data.get('code') == '00000':
                order_list = data.get('data', {}).get('list', [])
                for o in order_list:
                    all_plans.append(o)
            else:
                print(f"[V3 PLAN ERROR] {data}")
        except Exception as e:
            pass
        return all_plans

    def place_order(self, symbol, side, amount, leverage=10, tp=None, sl=None):
        """Executes trade with SL/TP for Bitget V3 UTA"""
        try:
            # We use CCXT for ordering as it's more stable for complex params
            # CCXT usually handles the V2/V3 transition for orders if the symbol is correct
            self.exchange.set_leverage(leverage, symbol)
            order = self.exchange.create_order(
                symbol, 'market', side, amount, 
                params={'stopLossPrice': sl, 'takeProfitPrice': tp}
            )
            return True, order
        except Exception as e:
            print(f"Error placing order: {e}")
            return False, str(e)

    def sync_memory(self):
        print("🔄 [SYNC] Synchronizing Bitget UTA Memory...")
        try:
            positions = self.get_all_positions()
            open_symbols = [p['symbol'].upper() for p in positions]
            
            from database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol FROM trades WHERE status IN ('PENDING', 'RUNNING') AND market = 'crypto'")
            db_trades = cursor.fetchall()
            
            for trade_id, db_symbol in db_trades:
                clean_sym = f"{db_symbol.replace('USDT','')}/USDT:USDT" if not ":" in db_symbol else db_symbol
                if clean_sym not in open_symbols:
                    print(f"[RECOVERY] {db_symbol} closed. Syncing.")
                    cursor.execute("UPDATE trades SET status = 'CLOSED' WHERE id = %s", (trade_id,))
            
            conn.commit()
            conn.close()
            print("✨ [SYNC] V3 Sync Complete.")
        except Exception as e:
            print(f"[SYNC ERROR] {e}")

    def manage_open_positions(self):
        """Institutional-Grade Monitoring for V3 UTA"""
        try:
            positions = self.get_all_positions()
            active_symbols = []
            
            for pos in positions:
                try:
                    symbol = pos['symbol']
                    side = pos['side']
                    size = pos['size']
                    entry = pos['entry']
                    mark_price = pos['mark_price']
                    pnl = float(pos.get('pnl', 0))
                    
                    if int(time.time()) % 300 < 35:
                        print(f"[MONITOR] {symbol} | PNL: {round(pnl, 2)}% | Mark: {mark_price}")
                    
                    active_symbols.append(symbol)
                    
                    sl_price = 0
                    tp_price = 0
                    plan_orders = self.get_pending_plan_orders(symbol)
                    current_clean = self._clean_symbol(symbol)
                    
                    for o in plan_orders:
                        plan_clean = self._clean_symbol(o.get('symbol'))
                        if plan_clean == current_clean:
                            dtype = o.get('delegateType', '')
                            price = float(o.get('triggerPrice') or o.get('price') or 0)
                            
                            if 'stop_loss' in dtype: sl_price = price
                            elif 'stop_profit' in dtype: tp_price = price
                            elif price > 0:
                                # Fallback logic
                                is_long = side.lower() in ['long', 'buy']
                                if is_long:
                                    if entry > 0 and price > entry: tp_price = max(tp_price, price)
                                    else: sl_price = max(sl_price, price)
                                else:
                                    if entry > 0 and price < entry: tp_price = min(tp_price, price) if tp_price > 0 else price
                                    else: sl_price = min(sl_price, price) if sl_price > 0 else price
                    
                    # Risk Guards
                    if sl_price > 0:
                        if int(time.time()) % 300 < 15:
                            print(f"[VERIFIED] {symbol}: SL {sl_price} | TP {tp_price}")
                    elif entry > 0:
                        default_sl = entry * 0.95 if side.lower() in ['long', 'buy'] else entry * 1.05
                        print(f"[RISK] {symbol} NO SL! Setting V3 SL at {round(default_sl, 4)}")
                        self.update_sl_price(symbol, side, size, default_sl)
                    
                    if tp_price == 0 and entry > 0:
                        default_tp = entry * 1.05 if side.lower() in ['long', 'buy'] else entry * 0.95
                        print(f"[TP CHECK] {symbol} NO TP! Setting V3 TP at {round(default_tp, 4)}")
                        self.update_sl_price(symbol, side, size, default_tp, is_tp=True)
                    
                except Exception as e_pos:
                    print(f"[MONITOR ERROR] {e_pos}")

            # Database cleanup
            from database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM trades WHERE status IN ('PENDING', 'RUNNING') AND market = 'crypto'")
            db_trades = cursor.fetchall()
            for (db_symbol,) in db_trades:
                is_active = any(db_symbol.replace("USDT","") in s for s in active_symbols)
                if not is_active:
                    try:
                        clean_sym = f"{db_symbol.replace('USDT','')}/USDT:USDT" if not ":" in db_symbol else db_symbol
                        self.exchange.cancel_all_orders(clean_sym)
                        cursor.execute("UPDATE trades SET status = 'CLOSED' WHERE symbol = %s", (db_symbol,))
                        conn.commit()
                    except: pass
            conn.close()
                    
        except Exception as e:
            print(f"[MONITOR ERROR GLOBAL] {e}")

    def update_sl_price(self, symbol, side, amount, new_price, is_tp=False):
        try:
            tp_side = 'sell' if side.lower() in ['long', 'buy'] else 'buy'
            formatted_price = self.exchange.price_to_precision(symbol, new_price)
            dtype = 'position_stop_profit_market' if is_tp else 'position_stop_loss_market'
            
            params = {
                'triggerPrice': formatted_price,
                'triggerType': 'mark_price',
                'reduceOnly': 'YES',
                'delegateType': dtype
            }
            self.exchange.create_order(symbol, 'market', tp_side, amount, None, params=params)
            print(f"[BITGET V3] {dtype} updated at {formatted_price}")
        except Exception as e:
            print(f"[V3 SL/TP FAILED] {symbol}: {e}")

if __name__ == "__main__":
    executor = BitgetExecutor()
    success, msg = executor.test_connection()
    print(msg)

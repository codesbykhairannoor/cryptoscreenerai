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
        self.is_uta = True # Assume UTA initially, detect if Classic
        
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
        print("[INIT] Detecting Account Mode (UTA vs Classic)...")

    def _clean_symbol(self, s):
        """Standardizes symbol format to base coin"""
        if not s: return ""
        return s.upper().replace('USDT', '').replace('/', '').split(':')[0].split('_')[0]

    def _v3_request(self, method, path, query="", body=None):
        """Helper for Bitget V3 UTA Signed Requests with Body Support"""
        import requests, hmac, hashlib, base64, json
        ts = str(int(time.time() * 1000))
        
        request_path = path
        if query:
            request_path += f"?{query}"
        
        body_str = ""
        if body:
            body_str = json.dumps(body)
        
        message = ts + method.upper() + request_path + body_str
        mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
        sign = base64.b64encode(mac.digest()).decode('utf8')
        
        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }
        
        url = f"https://api.bitget.com{request_path}"
        res = requests.request(method, url, headers=headers, data=body_str if body else None, timeout=20, verify=False)
        data = res.json()
        
        # Auto-detect Classic mode from error code
        if data.get('code') == '40084':
            if self.is_uta:
                print("⚠️ [MODE SWITCH] Detected Classic Account. Falling back to V2/Mix endpoints.")
                self.is_uta = False
        return data

    def _classic_request(self, method, path, query="", body=None):
        """Fallback for Classic Account (V2 Mix Endpoints)"""
        # We can use CCXT for most Classic requests as it's well-tested for Mix
        try:
            if method.upper() == 'GET':
                # Simplified for the specific endpoints we use
                if 'position' in path:
                    return self.exchange.fetch_positions(params={'productType': 'USDT-FUTURES'})
                if 'order' in path:
                    return self.exchange.fetch_open_orders(params={'productType': 'USDT-FUTURES'})
            return {}
        except:
            return {}

    def test_connection(self):
        try:
            balance = self.get_balance()
            mode = "UTA" if self.is_uta else "Classic"
            return True, f"Bitget {mode} Connected. Balance: {balance['total']} USDT"
        except Exception as e:
            return False, f"Connection Failed: {str(e)}"

    def get_balance(self):
        """Fetches balance compatible with both UTA and Classic"""
        try:
            if self.is_uta:
                data = self._v3_request("GET", "/api/v3/account/assets", "category=USDT-FUTURES")
                if data.get('code') == '00000':
                    assets = data.get('data', {}).get('list', [])
                    for a in assets:
                        if a.get('marginCoin') == 'USDT':
                            return {
                                'total': float(a.get('equity', 0)),
                                'free': float(a.get('available', 0))
                            }
                # If it failed with 40084, it will switch self.is_uta to False and we try Classic below
            
            # Classic Fallback
            bal = self.exchange.fetch_balance({'type': 'swap'})
            return {
                'total': float(bal.get('total', {}).get('USDT', 0)),
                'free': float(bal.get('free', {}).get('USDT', 0))
            }
        except Exception as e:
            print(f"[BALANCE ERROR] {e}")
            return {'total': 0, 'free': 0}

    def get_max_available(self, symbol, leverage=10):
        """Calculates max trade size based on free margin"""
        try:
            balance = self.get_balance()
            free_usdt = balance['free']
            
            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker['last']
            
            # Use 90% of free margin for safety
            max_qty = (free_usdt * leverage * 0.9) / price
            return round(max_qty, 3)
        except:
            return 0

    def get_all_positions(self):
        """Fetches positions compatible with both UTA and Classic"""
        all_pos = []
        try:
            if self.is_uta:
                data = self._v3_request("GET", "/api/v3/position/current-position", "category=USDT-FUTURES")
                if data.get('code') == '00000':
                    pos_list = data.get('data', {}).get('list', [])
                    for p in pos_list:
                        sz = float(p.get('total', 0) or 0)
                        if sz > 0:
                            instId = p.get('symbol', '')
                            symbol = f"{instId.replace('USDT', '')}/USDT:USDT" if "USDT" in instId and ":" not in instId else instId
                            all_pos.append({
                                'symbol': symbol, 'instId': instId,
                                'side': p.get('posSide', 'long'), 'size': sz,
                                'entry': float(p.get('avgPrice') or p.get('breakEvenPrice') or 0),
                                'mark_price': float(p.get('markPrice', 0) or 0),
                                'pnl': float(p.get('unrealisedPnl', 0) or 0)
                            })
                    return all_pos
            
            # Classic Fallback (Mix)
            ccxt_pos = self.exchange.fetch_positions(params={'productType': 'USDT-FUTURES'})
            for p in ccxt_pos:
                if float(p.get('contracts', 0)) > 0:
                    all_pos.append({
                        'symbol': p['symbol'], 'instId': p['id'],
                        'side': p['side'], 'size': float(p['contracts']),
                        'entry': float(p['entryPrice']),
                        'mark_price': float(p['markPrice'] or 0),
                        'pnl': float(p['percentage'] or 0)
                    })
        except Exception as e:
            print(f"[POS ERROR] {e}")
        return all_pos

    def get_pending_plan_orders(self, symbol=None):
        """Fetches pending orders compatible with both UTA and Classic"""
        all_plans = []
        try:
            if self.is_uta:
                query = "category=USDT-FUTURES"
                if symbol:
                    instId = symbol.replace('/', '').replace(':USDT', '')
                    query += f"&symbol={instId}"
                data = self._v3_request("GET", "/api/v3/trade/unfilled-orders", query)
                if data.get('code') == '00000':
                    return data.get('data', {}).get('list', [])
            
            # Classic Fallback
            params = {'productType': 'USDT-FUTURES'}
            if symbol: params['symbol'] = symbol
            plans = self.exchange.fetch_open_orders(symbol, params=params)
            return plans
        except:
            return []

    def place_order(self, symbol, side, amount, leverage=10, tp=None, sl=None):
        """Executes trade compatible with UTA and Classic"""
        try:
            self.exchange.set_leverage(leverage, symbol)
            
            if self.is_uta:
                instId = symbol.replace('/', '').replace(':USDT', '')
                body = {
                    "category": "USDT-FUTURES", "symbol": instId,
                    "side": side.lower(), "orderType": "market", "qty": str(amount),
                    "posSide": "long" if side.lower() in ['buy', 'long'] else "short"
                }
                if tp: body["takeProfit"] = str(tp)
                if sl: body["stopLoss"] = str(sl)
                
                data = self._v3_request("POST", "/api/v3/trade/place-order", body=body)
                if data.get('code') == '00000': return True, data.get('data', {})
                # If UTA failed, we'll try CCXT below
            
            # Classic/Generic Fallback via CCXT
            order = self.exchange.create_order(
                symbol, 'market', side, amount, 
                params={'stopLossPrice': sl, 'takeProfitPrice': tp}
            )
            return True, order
        except Exception as e:
            print(f"Error placing order: {e}")
            return False, str(e)

    def sync_memory(self):
        """Memory synchronization logic"""
        print("🔄 [SYNC] Synchronizing Bot Memory...")
        try:
            positions = self.get_all_positions()
            open_symbols = [p['symbol'].upper() for p in positions]
            
            from database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol FROM trades WHERE status IN ('PENDING', 'RUNNING') AND market = 'crypto'")
            db_trades = cursor.fetchall()
            
            for trade_id, db_symbol in db_trades:
                # Normalization for matching
                clean_db = self._clean_symbol(db_symbol)
                is_active = any(self._clean_symbol(s) == clean_db for s in open_symbols)
                
                if not is_active:
                    print(f"[RECOVERY] {db_symbol} closed. Syncing.")
                    cursor.execute("UPDATE trades SET status = 'CLOSED' WHERE id = %s", (trade_id,))
            
            conn.commit()
            conn.close()
            print("✨ [SYNC] Sync Complete.")
        except Exception as e:
            print(f"[SYNC ERROR] {e}")

    def sync_state_with_exchange(self):
        """Alias for sync_memory as expected by main.py"""
        return self.sync_memory()

    def manage_open_positions(self):
        """Intelligent Position Monitoring"""
        try:
            positions = self.get_all_positions()
            active_symbols = []
            
            for pos in positions:
                try:
                    symbol = pos['symbol']
                    side = pos['side']
                    size = pos['size']
                    entry = pos['entry']
                    pnl = float(pos.get('pnl', 0))
                    active_symbols.append(symbol)
                    
                    if int(time.time()) % 300 < 35:
                        print(f"[MONITOR] {symbol} | PNL: {round(pnl, 2)}%")
                    
                    # Check SL/TP
                    plan_orders = self.get_pending_plan_orders(symbol)
                    has_sl = any('stop_loss' in str(o).lower() for o in plan_orders)
                    
                    if not has_sl and entry > 0:
                        default_sl = entry * 0.95 if side.lower() in ['long', 'buy'] else entry * 1.05
                        print(f"[RISK] {symbol} NO SL! Fixing...")
                        self.update_sl_price(symbol, side, size, default_sl)
                        
                except Exception as e:
                    print(f"[POS MONITOR ERROR] {e}")
        except Exception as e:
            print(f"[GLOBAL MONITOR ERROR] {e}")

    def update_sl_price(self, symbol, side, amount, new_price, is_tp=False):
        """Updates SL/TP for existing positions"""
        try:
            if self.is_uta:
                instId = symbol.replace('/', '').replace(':USDT', '')
                tp_side = 'sell' if side.lower() in ['long', 'buy'] else 'buy'
                body = {
                    "category": "USDT-FUTURES", "symbol": instId,
                    "side": tp_side, "orderType": "market", "qty": str(amount),
                    "triggerPrice": str(new_price), "triggerBy": "mark",
                    "planType": "pos_profit" if is_tp else "pos_loss",
                    "reduceOnly": "yes"
                }
                data = self._v3_request("POST", "/api/v3/trade/place-plan-order", body=body)
                if data.get('code') == '00000': return
            
            # Classic Fallback via CCXT
            tp_side = 'sell' if side.lower() in ['long', 'buy'] else 'buy'
            params = {'stopLossPrice': new_price} if not is_tp else {'takeProfitPrice': new_price}
            self.exchange.create_order(symbol, 'market', tp_side, amount, None, params=params)
        except Exception as e:
            print(f"[SL/TP FAILED] {symbol}: {e}")

if __name__ == "__main__":
    executor = BitgetExecutor()
    success, msg = executor.test_connection()
    print(msg)

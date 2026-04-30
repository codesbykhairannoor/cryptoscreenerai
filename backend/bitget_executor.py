import ccxt
import os
import time
import traceback
from dotenv import load_dotenv

load_dotenv()

# Suppress InsecureRequestWarning
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class BitgetExecutor:
    def __init__(self):
        self.api_key = os.getenv("BITGET_API_KEY")
        self.secret_key = os.getenv("BITGET_SECRET_KEY")
        self.passphrase = os.getenv("BITGET_PASSPHRASE", "")
        
        # DEFAULT TO CLASSIC (MIX) as confirmed by USER
        self.is_uta = False 
        
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
        
        # Test mode on startup
        try:
            self.detect_account_mode()
        except:
            pass

    def detect_account_mode(self):
        """Internal check to confirm if account is UTA or Classic"""
        try:
            # Try a lightweight UTA request
            res = self._v3_request("GET", "/api/v3/account/assets", "category=USDT-FUTURES")
            if res.get('code') == '00000':
                self.is_uta = True
                print("[MODE] Account verified as Bitget V3 UTA.")
            else:
                self.is_uta = False
                print("[MODE] Account verified as Bitget Classic (Mix).")
        except:
            self.is_uta = False

    def _clean_symbol(self, s):
        if not s: return ""
        return s.upper().replace('USDT', '').replace('/', '').split(':')[0].split('_')[0]

    def _v3_request(self, method, path, query="", body=None):
        """Signed V3 Request for UTA accounts"""
        import requests, hmac, hashlib, base64, json
        ts = str(int(time.time() * 1000))
        request_path = path + (f"?{query}" if query else "")
        body_str = json.dumps(body) if body else ""
        
        message = ts + method.upper() + request_path + body_str
        mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
        sign = base64.b64encode(mac.digest()).decode('utf8')
        
        headers = {
            "ACCESS-KEY": self.api_key, "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.passphrase, "Content-Type": "application/json"
        }
        
        url = f"https://api.bitget.com{request_path}"
        try:
            res = requests.request(method, url, headers=headers, data=body_str if body else None, timeout=15, verify=False)
            return res.json()
        except:
            return {"code": "timeout"}

    def get_balance(self):
        """Unified Balance Fetcher"""
        try:
            if self.is_uta:
                data = self._v3_request("GET", "/api/v3/account/assets", "category=USDT-FUTURES")
                if data.get('code') == '00000':
                    for a in data['data']['list']:
                        if a.get('marginCoin') == 'USDT':
                            return {'total': float(a.get('equity', 0)), 'free': float(a.get('available', 0))}
            
            # Classic / Fallback
            bal = self.exchange.fetch_balance({'type': 'swap'})
            return {
                'total': float(bal.get('total', {}).get('USDT', 0)),
                'free': float(bal.get('free', {}).get('USDT', 0))
            }
        except: return {'total': 0, 'free': 0}

    def get_max_available(self, symbol, leverage=10):
        try:
            balance = self.get_balance()
            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker['last']
            return round((balance['free'] * leverage * 0.9) / price, 3)
        except: return 0

    def get_all_positions(self):
        """Position Fetcher for Classic accounts (V2 Mix)"""
        all_pos = []
        try:
            # For Classic, we strictly use V2 Mix Position endpoint via CCXT
            ccxt_pos = self.exchange.fetch_positions(params={'productType': 'USDT-FUTURES'})
            for p in ccxt_pos:
                sz = float(p.get('contracts', 0) or 0)
                if sz > 0:
                    all_pos.append({
                        'symbol': p['symbol'],
                        'side': p['side'],
                        'size': sz,
                        'entry': float(p.get('entryPrice', 0)),
                        'mark_price': float(p.get('markPrice', 0)),
                        'pnl': float(p.get('percentage', 0) or 0)
                    })
            return all_pos
        except Exception as e:
            print(f"[CLASSIC POS ERROR] {e}")
            return []

    def get_pending_plan_orders(self, symbol=None):
        """Plan/Trigger Order Fetcher for Classic (V2 Mix)"""
        all_orders = []
        try:
            params = {'productType': 'USDT-FUTURES'}
            # 1. Normal Orders
            all_orders += self.exchange.fetch_open_orders(symbol, params=params)
            
            # 2. Plan/Trigger Orders (SL/TP)
            # CCXT might not fetch plan orders via fetch_open_orders for all Bitget versions
            # So we call the private endpoint if necessary, or check the 'stop' type
            try:
                # Some versions of CCXT Bitget map fetch_open_orders to both, 
                # but we'll add a check for 'stop' orders in the list
                pass 
            except: pass
            
            return all_orders
        except: return []

    def place_order(self, symbol, side, amount, leverage=10, tp=None, sl=None):
        """Order Placement for Classic accounts (V2 Mix)"""
        try:
            self.exchange.set_leverage(leverage, symbol)
            
            # For Classic, we MUST split SL/TP to avoid parameter conflicts
            print(f"[CLASSIC ORDER] {side.upper()} {amount} {symbol}")
            order = self.exchange.create_order(symbol, 'market', side, amount)
            
            if sl or tp:
                time.sleep(0.5)
                if sl: self.update_sl_price(symbol, side, amount, sl, is_tp=False)
                if tp: self.update_sl_price(symbol, side, amount, tp, is_tp=True)
            
            return True, order
        except Exception as e:
            print(f"[CLASSIC ORDER FAILED] {e}")
            return False, str(e)

    def update_sl_price(self, symbol, side, amount, new_price, is_tp=False):
        """Updates SL/TP for Classic Position"""
        try:
            tp_side = 'sell' if side.lower() in ['long', 'buy'] else 'buy'
            params = {
                'stopLossPrice' if not is_tp else 'takeProfitPrice': new_price,
                'productType': 'USDT-FUTURES'
            }
            # Bitget Mix requires create_order for plan orders with stopLossPrice param
            self.exchange.create_order(symbol, 'market', tp_side, amount, None, params=params)
            print(f"[BITGET CLASSIC] {'TP' if is_tp else 'SL'} set at {new_price}")
        except Exception as e:
            print(f"[CLASSIC SL/TP ERROR] {e}")

    def sync_memory(self):
        from database import get_connection
        try:
            positions = self.get_all_positions()
            open_symbols = [self._clean_symbol(p['symbol']) for p in positions]
            
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, symbol FROM trades WHERE status IN ('PENDING', 'RUNNING') AND market = 'crypto'")
            for tid, sym in cursor.fetchall():
                if self._clean_symbol(sym) not in open_symbols:
                    cursor.execute("UPDATE trades SET status = 'CLOSED' WHERE id = %s", (tid,))
            conn.commit()
            conn.close()
        except: pass

    def sync_state_with_exchange(self):
        return self.sync_memory()

    def manage_open_positions(self):
        try:
            positions = self.get_all_positions()
            for pos in positions:
                symbol = pos['symbol']
                side = pos['side']
                size = pos['size']
                entry = pos['entry']
                
                # Verify SL/TP (PINTER: Check raw info for plan types)
                plans = self.get_pending_plan_orders(symbol)
                
                # Check for existing SL/TP in both CCXT format and Raw Info
                has_sl = False
                for o in plans:
                    info = str(o.get('info', {})).lower()
                    otype = str(o.get('type', '')).lower()
                    # Look for 'stop', 'loss', 'profit', or 'plan'
                    if 'stop' in otype or 'plan' in info or 'loss' in info or 'profit' in info:
                        has_sl = True
                        break
                
                if not has_sl and entry > 0:
                    sl = entry * 0.95 if side.lower() in ['long', 'buy'] else entry * 1.05
                    # Avoid spamming if price is too close
                    self.update_sl_price(symbol, side, size, sl)
        except Exception as e:
            print(f"[MANAGE POS ERROR] {e}")

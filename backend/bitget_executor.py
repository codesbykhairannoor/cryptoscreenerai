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
        """Calculates max trade size with exchange precision awareness"""
        try:
            balance = self.get_balance()
            free_usdt = balance['free']
            
            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker['last']
            
            # 1. Raw calculation
            raw_amount = (free_usdt * leverage * 0.9) / price
            
            # 2. Apply exchange precision
            formatted_amount = float(self.exchange.amount_to_precision(symbol, raw_amount))
            
            # 3. Check against minimum limit
            market = self.exchange.market(symbol)
            min_amount = market.get('limits', {}).get('amount', {}).get('min', 0.01)
            
            if formatted_amount < min_amount:
                # Silently return 0 if balance too low for minimum trade
                return 0
                
            return formatted_amount
        except:
            return 0

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
        """Plan/Trigger Order Fetcher for Classic (V2 Mix) with Multi-Type Polling"""
        all_orders = []
        try:
            # 1. Normal Orders via CCXT
            try: all_orders += self.exchange.fetch_open_orders(symbol, params={'productType': 'usdt-futures'})
            except: pass
            
            # 2. Plan Orders (Direct V2 Mix API) - Polling multiple product types for safety
            # Bitget Classic uses different productTypes depending on account age/region
            for pt in ['usdt-futures', 'umcbl']:
                try:
                    plan_data = self.exchange.private_get_mix_order_orders_plan_pending({'productType': pt})
                    if plan_data.get('code') == '00000':
                        raw_plans = plan_data.get('data', [])
                        target_clean = self._clean_symbol(symbol) if symbol else None
                        for p in raw_plans:
                            p_sym = p.get('symbol', '')
                            if not target_clean or self._clean_symbol(p_sym) == target_clean:
                                all_orders.append({'info': p, 'type': 'stop', 'symbol': p_sym})
                except: pass
            
            return all_orders
        except Exception as e:
            return []

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
        """Intelligent Monitoring: SL/TP Verification + Trail to Entry"""
        try:
            positions = self.get_all_positions()
            for pos in positions:
                symbol = pos['symbol']
                side = pos['side']
                size = pos['size']
                entry = pos['entry']
                pnl = float(pos.get('pnl', 0))
                
                # 1. Check for existing SL/TP
                plans = self.get_pending_plan_orders(symbol)
                has_sl = False
                existing_sl_price = 0
                
                for o in plans:
                    info = o.get('info', {})
                    # Bitget V2 Mix Plan Order detection
                    if str(info).lower().find('stop') != -1 or str(info).lower().find('plan') != -1:
                        has_sl = True
                        existing_sl_price = float(info.get('triggerPrice') or info.get('executePrice') or 0)
                        break
                
                # 2. TRAIL TO ENTRY LOGIC (PINTER)
                # If PNL > 20%, move SL to Entry price to lock in profits
                if pnl >= 20.0 and entry > 0:
                    if (side.lower() in ['long', 'buy'] and existing_sl_price < entry) or \
                       (side.lower() in ['short', 'sell'] and (existing_sl_price > entry or existing_sl_price == 0)):
                        print(f"📈 [TRAIL TO ENTRY] {symbol} Profit {round(pnl,1)}%! Moving SL to Entry: {entry}")
                        self.update_sl_price(symbol, side, size, entry)
                        continue # Skip the "No SL" check for this loop

                # 3. NO SL GUARD: If absolutely no SL exists, set default
                if not has_sl and entry > 0:
                    sl = entry * 0.95 if side.lower() in ['long', 'buy'] else entry * 1.05
                    self.update_sl_price(symbol, side, size, sl)
                    
        except Exception as e:
            print(f"[MANAGE POS ERROR] {e}")

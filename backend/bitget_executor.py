import ccxt
import os
import time
import json
import hmac
import hashlib
import base64
import requests
import traceback
from dotenv import load_dotenv

# Standard loading
load_dotenv()

# Suppress InsecureRequestWarning
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class BitgetExecutor:
    def __init__(self):
        # [STABLE] Exact environment variables from Commit ae01681
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
        
        # Security Check
        if not self.api_key or not self.secret_key:
             print("❌ [CRITICAL] Bitget Credentials MISSING! Check your .env file.")
        
        self.is_uta = False
        self.startup_time = time.time()
        self.warmup_period = 15
        
        try:
            from shared_state import state
            state.last_order_update = self.startup_time
            state.last_algo_update = self.startup_time
            state.last_acc_update = self.startup_time
            
            self.detect_account_mode()
            bal = self.get_balance()
            print(f"💰 [STARTUP AUDIT] USDT Balance: {bal['total']} (Available: {bal['free']})")
            
            pos = self.get_all_positions()
            if pos:
                print(f"📊 [STARTUP AUDIT] Running Trades: {len(pos)}")
                for p in pos:
                    print(f"   > {p['symbol']} | Side: {p['side']} | PNL: {p['pnl']}%")
                    self.get_pending_plan_orders(p['symbol'])
        except Exception as e:
            print(f"[STARTUP AUDIT ERROR] {e}")

    def _v3_request(self, method, path, query="", body=None):
        """Signed V3 Request for UTA accounts (Stable Baseline)"""
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

    def detect_account_mode(self):
        """Internal check to confirm if account is UTA or Classic"""
        try:
            res = self._v3_request("GET", "/api/v3/account/assets", "category=USDT-FUTURES")
            if res.get('code') == '00000':
                self.is_uta = True
                print("[MODE] Account verified as Bitget V3 UTA.")
            else:
                self.is_uta = False
                print("[MODE] Account verified as Bitget Classic (Mix).")
        except:
            self.is_uta = False
            print("[MODE] Account fallback to Bitget Classic (Mix).")

    def _clean_symbol(self, s):
        if not s: return ""
        # Remove common Bitget suffixes and separators
        s = s.upper().replace('/USDT:USDT', '').replace('USDT', '').replace('/', '').replace(':', '').replace('_', '')
        return s.strip()

    def get_balance(self):
        """Unified Balance Fetcher"""
        try:
            if self.is_uta:
                data = self._v3_request("GET", "/api/v3/account/assets", "category=USDT-FUTURES")
                if data.get('code') == '00000' and data.get('data'):
                    for a in data['data'].get('list', []):
                        if a.get('marginCoin') == 'USDT':
                            return {'total': float(a.get('equity', 0)), 'free': float(a.get('available', 0))}
            
            bal = self.exchange.fetch_balance({'type': 'swap'})
            return {
                'total': float(bal.get('total', {}).get('USDT', 0)),
                'free': float(bal.get('free', {}).get('USDT', 0))
            }
        except: return {'total': 0, 'free': 0}

    def get_max_available(self, symbol, leverage=10):
        try:
            balance = self.get_balance()
            free_usdt = balance['free']
            
            # BITGET REQUIREMENT: Minimum notional must be at least 5 USDT
            if free_usdt * leverage < 5.5: # 5.5 for buffer
                return 0
                
            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker['last']
            raw_amount = (free_usdt * leverage * 0.9) / price
            formatted_amount = float(self.exchange.amount_to_precision(symbol, raw_amount))
            
            # Check against exchange limits
            market = self.exchange.market(symbol)
            min_amount = market.get('limits', {}).get('amount', {}).get('min', 0.01)
            
            # Final Notional Check
            if formatted_amount * price < 5.0:
                return 0
                
            return formatted_amount if formatted_amount >= min_amount else 0
        except: return 0

    def get_all_positions(self):
        all_pos = []
        try:
            from shared_state import state
            ccxt_pos = self.exchange.fetch_positions(params={'productType': 'usdt-futures'})
            for p in ccxt_pos:
                sz = float(p.get('contracts', 0) or 0)
                if sz > 0:
                    entry = float(p.get('entryPrice', 0))
                    mark = float(p.get('markPrice', 0))
                    side = p['side'].lower()
                    pnl_pct = 0
                    if entry > 0:
                        diff = (mark - entry) if side in ['long', 'buy'] else (entry - mark)
                        pnl_pct = (diff / entry) * float(p.get('leverage', 10)) * 100
                    
                    all_pos.append({
                        'symbol': p['symbol'],
                        'side': side,
                        'size': sz,
                        'entry': entry,
                        'mark_price': mark,
                        'pnl': round(pnl_pct, 2)
                    })
            state.update_positions(all_pos)
            return all_pos
        except Exception as e:
            return []

    def get_pending_plan_orders(self, symbol):
        try:
            clean_symbol = symbol.replace("/", "").split(":")[0]
            if not clean_symbol.endswith('USDT'): clean_symbol += 'USDT'
            res = self.exchange.private_get_v2_mix_order_plan_current_orders({
                'symbol': clean_symbol,
                'productType': 'USDT-FUTURES'
            })
            plans = []
            if res.get('code') == '00000' and res.get('data'):
                for order in res['data']:
                    st = order.get('state', order.get('status', 'unknown')).lower()
                    if st in ['live', 'active', 'not_trigger']:
                        p = float(order.get('triggerPrice', order.get('executePrice', order.get('stopPrice', 0))))
                        plans.append({
                            'id': order.get('orderId', order.get('planId')),
                            'type': order.get('planType', 'unknown').lower(),
                            'price': p
                        })
            return plans
        except: return []

    def place_order(self, symbol, side, amount, tp=None, sl=None):
        try:
            order = self.exchange.create_order(symbol, 'market', side, amount)
            print(f"[BITGET CLASSIC] {side.upper()} {symbol} executed.")
            params = {'productType': 'USDT-FUTURES'}
            tp_side = 'sell' if side.lower() in ['long', 'buy'] else 'buy'
            if sl:
                sl_params = {**params, 'stopLossPrice': sl}
                self.exchange.create_order(symbol, 'market', tp_side, amount, None, params=sl_params)
            if tp:
                tp_params = {**params, 'takeProfitPrice': tp}
                self.exchange.create_order(symbol, 'market', tp_side, amount, None, params=tp_params)
            else:
                # Institutional TP (100% PNL)
                price = float(order.get('price', 0))
                if price > 0:
                    smart_tp = price * 2.0 if side.lower() in ['long', 'buy'] else price * 0.1
                    tp_params = {**params, 'takeProfitPrice': smart_tp}
                    self.exchange.create_order(symbol, 'market', tp_side, amount, None, params=tp_params)
            return True, order
        except Exception as e:
            print(f"[CLASSIC ORDER FAILED] {e}")
            return False, str(e)

    def update_sl_price(self, symbol, side, amount, new_price, is_tp=False):
        try:
            tp_side = 'sell' if side.lower() in ['long', 'buy'] else 'buy'
            params = {
                'stopLossPrice' if not is_tp else 'takeProfitPrice': new_price,
                'productType': 'USDT-FUTURES'
            }
            self.exchange.create_order(symbol, 'market', tp_side, amount, None, params=params)
        except: pass

    def sync_memory(self):
        """Database Sync: Ensures local DB matches exchange reality"""
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
        """Military Position Manager: Progressive Trailing & Sideways Exit"""
        try:
            if not hasattr(self, '_last_sl_check'): self._last_sl_check = {}
            if not hasattr(self, '_last_sl_set'): self._last_sl_set = {}
            
            positions = self.get_all_positions()
            now = time.time()
            from shared_state import state
            
            for pos in positions:
                symbol = pos['symbol']
                side = pos['side']
                size = pos['size']
                entry = pos['entry']
                pnl = pos['pnl']
                mark_price = pos.get('mark_price', 0)
                
                # 0. SIDEWAYS DETECTION
                if symbol not in state.pos_start_time:
                    state.pos_start_time[symbol] = now
                
                duration_hours = (now - state.pos_start_time[symbol]) / 3600
                price_move_pct = abs((mark_price - entry) / entry * 100) if entry > 0 else 0
                
                if duration_hours > 4 and -1.5 < pnl < 1.5 and price_move_pct < 0.4:
                    print(f"⚖️ [SIDEWAYS EXIT] Closing {symbol} - Flat for {round(duration_hours, 1)}h")
                    self.exchange.create_order(symbol, 'market', 'sell' if side == 'long' else 'buy', size)
                    if symbol in state.pos_start_time: del state.pos_start_time[symbol]
                    continue

                if now - self._last_sl_check.get(symbol, 0) < 15: continue
                self._last_sl_check[symbol] = now
                
                plans = self.get_pending_plan_orders(symbol)
                has_sl = False
                sl_p = 0
                for p in plans:
                    p_type = p['type']
                    if 'sl' in p_type or 'loss' in p_type or 'stop' in p_type or p_type == 'pl':
                        has_sl = True
                        sl_p = p['price']

                # Military Status Log (Every 15s)
                if int(now) % 15 < 3:
                    o_h = "🟢" if now - state.last_order_update < 300 else "🔴"
                    a_h = "🟢" if now - state.last_algo_update < 300 else "🔴"
                    b_h = "🟢" if now - state.last_acc_update < 300 else "🔴"
                    print(f"💎 [MONITOR {o_h}{a_h}{b_h}] {symbol} | PNL: {pnl}% | SL: {'OK' if has_sl else 'MISSING'}")

                # 1. INITIAL GUARD
                if not has_sl and now - self.startup_time > self.warmup_period:
                    if now - self._last_sl_set.get(symbol, 0) > 300:
                        sl_price = entry * 0.98 if side in ['long', 'buy'] else entry * 1.02
                        print(f"🛡️ [GUARD] Setting Initial SL for {symbol}")
                        self.update_sl_price(symbol, side, size, sl_price)
                        self._last_sl_set[symbol] = now

                # 2. PROGRESSIVE 15% TRAILING
                new_sl = 0
                if pnl >= 90: new_sl = entry * 1.75 if side in ['long', 'buy'] else entry * 0.25 
                elif pnl >= 75: new_sl = entry * 1.60 if side in ['long', 'buy'] else entry * 0.40 
                elif pnl >= 60: new_sl = entry * 1.45 if side in ['long', 'buy'] else entry * 0.55 
                elif pnl >= 45: new_sl = entry * 1.30 if side in ['long', 'buy'] else entry * 0.70 
                elif pnl >= 30: new_sl = entry * 1.15 if side in ['long', 'buy'] else entry * 0.85 
                elif pnl >= 15: new_sl = entry + (0.001 if side in ['long', 'buy'] else -0.001) 
                
                if new_sl > 0:
                    is_better = (side in ['long', 'buy'] and new_sl > sl_p) or \
                                (side in ['short', 'sell'] and (new_sl < sl_p or sl_p == 0))
                    
                    if is_better and now - self._last_sl_set.get(symbol, 0) > 300:
                        print(f"🔥 [MILITARY TRAILING] Moving SL for {symbol} to {new_sl} (PNL: {pnl}%)")
                        self.update_sl_price(symbol, side, size, new_sl)
                        self._last_sl_set[symbol] = now
        except: pass

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
        """Position Fetcher with Real-time PNL Calculation (Hybrid WS/REST)"""
        all_pos = []
        try:
            # 1. Try to get from Shared State (WebSocket) first
            from shared_state import state
            if state.positions and (time.time() - state.last_update < 30):
                return state.positions

            # 2. Fallback to REST
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
            
            # Update Shared State for next call
            state.update_positions(all_pos)
            return all_pos
        except Exception as e:
            return []

    def get_pending_plan_orders(self, symbol=None):
        """Plan/Trigger Order Fetcher (Hybrid WS/REST)"""
        all_orders = []
        try:
            # 1. Check Shared State (WebSocket) first
            from shared_state import state
            ws_orders = state.orders
            if ws_orders:
                target_clean = self._clean_symbol(symbol) if symbol else None
                for o in ws_orders:
                    o_sym = o.get('symbol', '')
                    if not target_clean or self._clean_symbol(o_sym) == target_clean:
                        all_orders.append({'info': o, 'type': 'stop', 'symbol': o_sym})
                if all_orders: return all_orders

            # 2. Fallback to REST API
            try: all_orders += self.exchange.fetch_open_orders(symbol, params={'productType': 'usdt-futures'})
            except: pass
            
            for pt in ['usdt-futures', 'umcbl', 'dmcbl', 'cmcbl']:
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
        """Institutional Monitoring: Progressive Trailing & SL Guard"""
        try:
            # Persistent caches to prevent log spamming
            if not hasattr(self, '_last_sl_check'): self._last_sl_check = {}
            if not hasattr(self, '_last_sl_set'): self._last_sl_set = {}
            
            positions = self.get_all_positions()
            now = time.time()
            
            for pos in positions:
                symbol = pos['symbol']
                side = pos['side']
                size = pos['size']
                entry = pos['entry']
                pnl = pos['pnl']
                
                # Rate limit checks to prevent spam
                if now - self._last_sl_check.get(symbol, 0) < 15: continue
                self._last_sl_check[symbol] = now
                
                # 1. Fetch Plans
                plans = self.get_pending_plan_orders(symbol)
                has_sl = False
                has_tp = False
                sl_p = 0
                tp_p = 0
                
                for o in plans:
                    info = o.get('info', {})
                    p_type = str(info.get('planType', '')).lower()
                    # Bitget V2 Plan detection (psl=pos stop loss, ptp=pos take profit, pl=plan)
                    if p_type in ['stop', 'loss', 'psl', 'sl']:
                        has_sl = True
                        sl_p = float(info.get('triggerPrice') or info.get('executePrice') or 0)
                    elif p_type in ['profit', 'ptp', 'tp']:
                        has_tp = True
                        tp_p = float(info.get('triggerPrice') or info.get('executePrice') or 0)
                
                # Diagnostic Log (SL & TP) - Every 10 seconds
                if int(now) % 10 < 3:
                    sl_status = f"SL: {sl_p}" if has_sl else "SL: MISSING"
                    tp_status = f"TP: {tp_p}" if has_tp else "TP: MISSING"
                    # Add WS status indicator
                    from shared_state import state
                    ws_active = "🟢 WS" if (time.time() - state.last_update < 60) else "🔴 REST"
                    print(f"💎 [MONITOR {ws_active}] {symbol} | PNL: {pnl}% | {sl_status} | {tp_status}")

                # 2. PROGRESSIVE TRAILING LOGIC (PINTER)
                new_sl = 0
                if pnl >= 60.0: new_sl = entry * 1.25 if side in ['long', 'buy'] else entry * 0.75
                elif pnl >= 40.0: new_sl = entry * 1.10 if side in ['long', 'buy'] else entry * 0.90
                elif pnl >= 20.0: new_sl = entry 
                
                if new_sl > 0:
                    is_better = (side in ['long', 'buy'] and new_sl > sl_p) or \
                                (side in ['short', 'sell'] and (new_sl < sl_p or sl_p == 0))
                    
                    if is_better:
                        # Avoid updating too frequently (every 2 mins for trailing)
                        if now - self._last_sl_set.get(symbol + "_trail", 0) > 120:
                            print(f"🔥 [PINTER TRAIL] {symbol} {pnl}% PNL! Moving SL to {new_sl}")
                            self.update_sl_price(symbol, side, size, new_sl)
                            self._last_sl_set[symbol + "_trail"] = now
                        continue

                # 3. NO SL GUARD: Initial SL placement
                if not has_sl and entry > 0:
                    # Safety: Don't set SL again if we just set it in the last 5 minutes (waiting for exchange sync)
                    if now - self._last_sl_set.get(symbol + "_init", 0) > 300:
                        sl_price = entry * 0.95 if side in ['long', 'buy'] else entry * 1.05
                        print(f"🛡️ [GUARD] Setting Initial SL for {symbol} at {sl_price}")
                        self.update_sl_price(symbol, side, size, sl_price)
                        self._last_sl_set[symbol + "_init"] = now
                    
        except Exception as e:
            pass

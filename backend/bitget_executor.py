import ccxt
import os
import time
import json
from dotenv import load_dotenv

load_dotenv()

class BitgetExecutor:
    def __init__(self):
        self.exchange = ccxt.bitget({
            'apiKey': os.getenv('BITGET_API_KEY'),
            'secret': os.getenv('BITGET_API_SECRET'),
            'password': os.getenv('BITGET_PASSWORD'),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        
        # Security Check: Ensure keys are loaded
        if not self.exchange.apiKey or not self.exchange.secret:
             print("❌ [CRITICAL] Bitget Credentials MISSING! Check your .env file.")
        
        self.is_mix = True
        
        # Startup Intelligence
        self.startup_time = time.time()
        self.warmup_period = 15 # 15s observation phase
        
        try:
            from shared_state import state
            # Initialize health timestamps to prevent false red dots
            state.last_order_update = self.startup_time
            state.last_algo_update = self.startup_time
            state.last_acc_update = self.startup_time
            
            self.detect_account_mode()
            bal = self.get_balance()
            print(f"💰 [STARTUP AUDIT] USDT Balance: {bal['total']} (Available: {bal['free']})")
            
            # FORCE INITIAL REST SYNC to populate state
            pos = self.get_all_positions()
            if pos:
                print(f"📊 [STARTUP AUDIT] Running Trades: {len(pos)}")
                for p in pos:
                    print(f"   > {p['symbol']} | Side: {p['side']} | PNL: {p['pnl']}%")
                    # Populating plans via REST so Guard is aware immediately
                    self.get_pending_plan_orders(p['symbol'])
        except:
            pass

    def detect_account_mode(self):
        try:
            # Check if using Mix (Unified) account or Classic
            self.exchange.private_get_mix_v1_account_accounts({'productType': 'usdt-futures'})
            self.is_mix = True
            print("[MODE] Account verified as Bitget Classic (Mix).")
        except Exception as e:
            self.is_mix = False
            print(f"[MODE] Account verified as Bitget Standard (Reason: {e})")

    def get_balance(self):
        """Institutional Balance Audit"""
        try:
            if self.is_mix:
                res = self.exchange.private_get_mix_v1_account_accounts({'productType': 'usdt-futures'})
                if res.get('code') == '00000' and res.get('data'):
                    # Search for USDT in the data list
                    for item in res['data']:
                        if item.get('marginCoin') == 'USDT':
                            return {
                                'total': float(item.get('equity', 0)),
                                'free': float(item.get('available', 0))
                            }
            
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
            print(f"[FETCH POSITIONS ERROR] {e}")
            return []

    def get_pending_plan_orders(self, symbol):
        """
        [PLAN DETECTOR] - Finds active SL/TP in Bitget V2
        Uses hybrid price extraction to support multiple Bitget V2 field names
        """
        try:
            clean_symbol = symbol.replace("/", "").split(":")[0]
            if not clean_symbol.endswith('USDT'): clean_symbol += 'USDT'
            
            # Try V2 Private Plan Order API
            res = self.exchange.private_get_v2_mix_order_plan_current_orders({
                'symbol': clean_symbol,
                'productType': 'USDT-FUTURES'
            })
            
            plans = []
            if res.get('code') == '00000' and res.get('data'):
                for order in res['data']:
                    # Support multiple state/status fields for Bitget V2 stability
                    state = order.get('state', order.get('status', 'unknown')).lower()
                    if state in ['live', 'active', 'not_trigger']:
                        # Bitget V2 Plan Orders use triggerPrice, executePrice, or stopPrice
                        p = float(order.get('triggerPrice', order.get('executePrice', order.get('stopPrice', 0))))
                        plans.append({
                            'id': order.get('orderId', order.get('planId')),
                            'type': order.get('planType', 'unknown').lower(),
                            'price': p
                        })
            return plans
        except Exception as e:
            # print(f"[DEBUG] Plan fetch failed for {symbol}: {e}")
            return []

    def _clean_symbol(self, symbol):
        """Robust Symbol Normalizer"""
        s = symbol.split(":")[0].replace("/", "").replace("USDT", "")
        return s.upper()

    def place_order(self, symbol, side, amount, tp=None, sl=None):
        """
        [CLASSIC EXECUTOR] - Places market order with protective SL/TP
        """
        try:
            # 1. Main Order
            order = self.exchange.create_order(symbol, 'market', side, amount)
            print(f"[BITGET CLASSIC] {side.upper()} {symbol} executed at market.")
            
            # 2. Protective Orders (Plan Orders)
            params = {'productType': 'USDT-FUTURES'}
            tp_side = 'sell' if side.lower() in ['long', 'buy'] else 'buy'
            
            if sl:
                sl_params = {**params, 'stopLossPrice': sl}
                self.exchange.create_order(symbol, 'market', tp_side, amount, None, params=sl_params)
                print(f"[BITGET CLASSIC] SL set at {sl}")
            
            if tp:
                tp_params = {**params, 'takeProfitPrice': tp}
                self.exchange.create_order(symbol, 'market', tp_side, amount, None, params=tp_params)
                print(f"[BITGET CLASSIC] TP set at {tp}")
            else:
                # SUPER JENIUS TP (100% PNL)
                # Long: TP = Price * 2 | Short: TP = Price * 0.1
                price = float(order.get('price', 0))
                if price > 0:
                    smart_tp = price * 2.0 if side.lower() in ['long', 'buy'] else price * 0.1
                    tp_params = {**params, 'takeProfitPrice': smart_tp}
                    self.exchange.create_order(symbol, 'market', tp_side, amount, None, params=tp_params)
                    print(f"[BITGET CLASSIC] Institutional TP (100%) set at {smart_tp}")
            
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
                mark_price = pos.get('mark_price', 0)
                
                # 0. Sideways/Stale Trade Detection
                from shared_state import state
                if symbol not in state.pos_start_time:
                    state.pos_start_time[symbol] = now
                
                duration_hours = (now - state.pos_start_time[symbol]) / 3600
                price_move_pct = abs((mark_price - entry) / entry * 100) if entry > 0 else 0
                
                # Logic: If trade is > 4 hours old, PNL is near zero, and price hasn't moved much -> EXIT
                if duration_hours > 4 and -1.5 < pnl < 1.5 and price_move_pct < 0.4:
                    print(f"⚖️ [SIDEWAYS EXIT] Closing {symbol} - Flat for {round(duration_hours, 1)}h (Move: {round(price_move_pct, 2)}%)")
                    self.exchange.create_order(symbol, 'market', 'sell' if side == 'long' else 'buy', size)
                    if symbol in state.pos_start_time: del state.pos_start_time[symbol]
                    continue

                # Rate limit checks to prevent spam
                if now - self._last_sl_check.get(symbol, 0) < 15: continue
                self._last_sl_check[symbol] = now
                
                # 1. Fetch Plans
                plans = self.get_pending_plan_orders(symbol)
                has_sl = False
                has_tp = False
                sl_p = 0
                tp_p = 0
                
                for p in plans:
                    if p['type'] in ['pl', 'psl']: # Stop Loss types
                        has_sl = True
                        sl_p = p['price']
                    if p['type'] in ['ptp']: # Take Profit type
                        has_tp = True
                        tp_p = p['price']

                # Health Indicators (Dashboard logic)
                o_h = "🟢" if now - state.last_order_update < 300 else "🔴"
                a_h = "🟢" if now - state.last_algo_update < 300 else "🔴"
                b_h = "🟢" if now - state.last_acc_update < 300 else "🔴"
                
                sl_status = f"SL: {sl_p}" if has_sl else "SL: MISSING"
                tp_status = f"TP: {tp_p}" if has_tp else "TP: MISSING"
                
                if now - self.startup_time < self.warmup_period:
                    print(f"⏳ [WARM-UP] Observing {symbol}... Waiting for stream sync.")
                else:
                    if not has_sl and now - self._last_sl_set.get(symbol, 0) > 300:
                        # SET INITIAL SL AS GUARD
                        print(f"💎 [MONITOR {o_h}{a_h}{b_h}] {symbol} | PNL: {pnl}% | {sl_status} | {tp_status}")
                        print(f"🛡️ [GUARD] Setting Initial SL for {symbol} at {entry * 0.98 if side in ['long', 'buy'] else entry * 1.02}")
                        self.update_sl_price(symbol, side, size, entry * 0.98 if side in ['long', 'buy'] else entry * 1.02)
                        self._last_sl_set[symbol] = now
                    
                    print(f"💎 [MONITOR {o_h}{a_h}{b_h}] {symbol} | PNL: {pnl}% | {sl_status} | {tp_status}")

                # 2. PROGRESSIVE AGGRESSIVE TRAILING (PINTER v3)
                new_sl = 0
                if pnl >= 90: new_sl = entry * 1.75 if side in ['long', 'buy'] else entry * 0.25 # Lock +75%
                elif pnl >= 75: new_sl = entry * 1.60 if side in ['long', 'buy'] else entry * 0.40 # Lock +60%
                elif pnl >= 60: new_sl = entry * 1.45 if side in ['long', 'buy'] else entry * 0.55 # Lock +45%
                elif pnl >= 45: new_sl = entry * 1.30 if side in ['long', 'buy'] else entry * 0.70 # Lock +30%
                elif pnl >= 30: new_sl = entry * 1.15 if side in ['long', 'buy'] else entry * 0.85 # Lock +15%
                elif pnl >= 15: new_sl = entry + (0.001 if side in ['long', 'buy'] else -0.001) # Break-even
                
                if new_sl > 0:
                    is_better = (side in ['long', 'buy'] and new_sl > sl_p) or \
                                (side in ['short', 'sell'] and (new_sl < sl_p or sl_p == 0))
                    
                    if is_better and now - self._last_sl_set.get(symbol, 0) > 300:
                        print(f"🔥 [PINTER TRAILING] Moving SL for {symbol} to {new_sl} (PNL: {pnl}%)")
                        self.update_sl_price(symbol, side, size, new_sl)
                        self._last_sl_set[symbol] = now

        except Exception as e:
            print(f"[POSITION MANAGER ERROR] {e}")
            time.sleep(1)

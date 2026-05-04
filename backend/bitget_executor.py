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
             print("[CRITICAL] Bitget Credentials MISSING! Check your .env file.")
        
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
            print(f"[STARTUP AUDIT] USDT Balance: {bal['total']} (Available: {bal['free']})")
            
            pos = self.get_all_positions()
            if pos:
                print(f"[STARTUP AUDIT] Running Trades: {len(pos)}")
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
        """Unified Balance Fetcher (WS Priority)"""
        try:
            from shared_state import state
            # 1. WS CACHE PRIORITY (Full WebSocket Mode)
            if state.balances and time.time() - state.last_acc_update < 60:
                bal = state.balances.get('USDT', {})
                if bal:
                    return {'total': float(bal.get('equity', 0)), 'free': float(bal.get('available', 0))}

            # 2. REST SEED/FALLBACK
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

            # Bitget minimum notional: 5 USDT
            if free_usdt < 0.5:  # butuh minimal ~0.5 USDT margin untuk 5 USDT notional di 10x
                return 0

            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker['last']

            # Gunakan 80% dari free balance sebagai margin (sisakan 20% untuk fee & slippage)
            margin_to_use = free_usdt * 0.80
            notional      = margin_to_use * leverage
            raw_amount    = notional / price

            formatted_amount = float(self.exchange.amount_to_precision(symbol, raw_amount))

            # Check exchange minimum
            market     = self.exchange.market(symbol)
            min_amount = market.get('limits', {}).get('amount', {}).get('min', 0.001)

            # Final notional check — Bitget requires >= 5 USDT notional
            if formatted_amount * price < 5.0:
                return 0

            return formatted_amount if formatted_amount >= min_amount else 0
        except Exception as e:
            print(f"[GET_MAX ERROR] {e}")
            return 0

    def get_all_positions(self):
        try:
            from shared_state import state
            # 1. WS CACHE PRIORITY
            if state.positions and time.time() - state.last_update < 30:
                return state.positions

            # 2. REST SEED/FALLBACK
            all_pos = []
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
            from shared_state import state
            # 1. WS CACHE PRIORITY (Standardized Symbol check)
            clean_sym = self._clean_symbol(symbol)
            ws_plans = [o for o in state.orders if self._clean_symbol(o.get('symbol', o.get('instId', ''))) == clean_sym and o.get('planType')]
            if ws_plans:
                return [{
                    'id': o.get('orderId', o.get('planId')),
                    'type': o.get('planType', 'unknown').lower(),
                    'price': float(o.get('triggerPrice', o.get('executePrice', 0)))
                } for o in ws_plans]

            # 2. REST FALLBACK
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

    def place_order(self, symbol, side, amount, tp=None, sl=None, leverage=10):
        try:
            # 1. SET LEVERAGE
            try:
                self.exchange.set_leverage(leverage, symbol, params={'productType': 'USDT-FUTURES', 'marginCoin': 'USDT'})
            except Exception as lev_err:
                print(f"[LEVERAGE] Set {leverage}x for {symbol}: {lev_err}")

            # 2. MARKET ORDER
            order = self.exchange.create_order(symbol, 'market', side, amount)
            print(f"[BITGET CLASSIC] {side.upper()} {symbol} executed @ {leverage}x.")

            # 3. AMBIL HARGA FILL — handle NoneType
            raw_price = order.get('price') or order.get('average') or order.get('info', {}).get('priceAvg')
            if raw_price is None or float(raw_price) == 0:
                ticker = self.exchange.fetch_ticker(symbol)
                raw_price = ticker['last']
            price = float(raw_price)

            # 4. HITUNG SL/TP DARI HARGA FILL AKTUAL
            # Penting: pakai `price` (harga fill), bukan mark_price sebelum order
            # TP 80% PnL = 8% price move di 10x
            # SL 15% PnL = 1.5% price move di 10x
            if side.lower() in ['long', 'buy']:
                final_sl = sl if (sl and sl > 0 and sl < price) else price * 0.985
                final_tp = tp if (tp and tp > 0 and tp > price) else price * 1.08
            else:
                final_sl = sl if (sl and sl > 0 and sl > price) else price * 1.015
                final_tp = tp if (tp and tp > 0 and tp < price) else price * 0.92

            # Double-check: SL long harus < price, SL short harus > price
            if side.lower() in ['long', 'buy'] and final_sl >= price:
                final_sl = price * 0.985
            if side.lower() in ['short', 'sell'] and final_sl <= price:
                final_sl = price * 1.015

            # 5. SET SL/TP via Plan Order API (cara yang benar untuk Bitget Classic)
            self._set_sl_tp_bitget(symbol, side, amount, sl_price=final_sl, tp_price=final_tp)

            print(f"[ORDER OK] {symbol} {side.upper()} | Entry: {price} | TP: {final_tp} (+{round((final_tp/price-1)*100,2)}%) | SL: {final_sl} (-{round((1-final_sl/price)*100,2)}%)")
            return True, order
        except Exception as e:
            print(f"[CLASSIC ORDER FAILED] {e}")
            return False, str(e)

    def _set_sl_tp_bitget(self, symbol, side, size, sl_price=None, tp_price=None):
        """
        Set SL/TP untuk Bitget Classic.
        Berdasarkan testing: ccxt stopLossPrice/takeProfitPrice params BEKERJA.
        Skip API plan endpoint yang selalu NOT FOUND.
        """
        # Ambil mark price sekarang untuk validasi
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            current_price = float(ticker.get('last', 0))
        except Exception:
            current_price = 0

        hold_side = 'long' if side in ['long', 'buy'] else 'short'

        if sl_price and sl_price > 0:
            # Validasi: SL long harus di bawah current price
            if current_price > 0:
                if hold_side == 'long' and sl_price >= current_price * 0.999:
                    sl_price = current_price * 0.985
                    print(f"[SL ADJUST] {symbol} SL adjusted to {round(sl_price,6)}")
                elif hold_side == 'short' and sl_price <= current_price * 1.001:
                    sl_price = current_price * 1.015
                    print(f"[SL ADJUST] {symbol} SL adjusted to {round(sl_price,6)}")
            self._set_sl_ccxt(symbol, side, size, sl_price)

        if tp_price and tp_price > 0:
            self._set_tp_ccxt(symbol, side, size, tp_price)

    def _set_sl_ccxt(self, symbol, side, size, sl_price):
        """Set SL via ccxt dengan validasi harga."""
        try:
            tp_side = 'sell' if side in ['long', 'buy'] else 'buy'
            # Ambil mark price untuk validasi
            ticker = self.exchange.fetch_ticker(symbol)
            mark   = float(ticker.get('last', 0))
            hold   = 'long' if side in ['long', 'buy'] else 'short'

            if mark > 0:
                if hold == 'long' and sl_price >= mark:
                    sl_price = mark * 0.985
                elif hold == 'short' and sl_price <= mark:
                    sl_price = mark * 1.015

            self.exchange.create_order(
                symbol, 'market', tp_side, size, None,
                params={'productType': 'USDT-FUTURES', 'reduceOnly': True, 'stopLossPrice': sl_price}
            )
            print(f"[SL CCXT] {symbol} SL@{round(sl_price,6)} ✓")
        except Exception as e:
            print(f"[SL CCXT FAIL] {symbol}: {e}")

    def _set_tp_ccxt(self, symbol, side, size, tp_price):
        """Set TP via ccxt."""
        try:
            tp_side = 'sell' if side in ['long', 'buy'] else 'buy'
            self.exchange.create_order(
                symbol, 'market', tp_side, size, None,
                params={'productType': 'USDT-FUTURES', 'reduceOnly': True, 'takeProfitPrice': tp_price}
            )
            print(f"[TP CCXT] {symbol} TP@{round(tp_price,6)} ✓")
        except Exception as e:
            print(f"[TP CCXT FAIL] {symbol}: {e}")

    def _set_sl_tp_ccxt(self, symbol, side, size, sl_price=None, tp_price=None):
        """Fallback lengkap: set SL dan TP via ccxt."""
        if sl_price and sl_price > 0:
            self._set_sl_ccxt(symbol, side, size, sl_price)
        if tp_price and tp_price > 0:
            self._set_tp_ccxt(symbol, side, size, tp_price)

    def update_sl_price(self, symbol, side, amount, new_price, is_tp=False):
        """Update SL atau TP yang sudah ada via Plan Order API."""
        self._set_sl_tp_bitget(
            symbol, side, amount,
            sl_price=new_price if not is_tp else None,
            tp_price=new_price if is_tp else None
        )

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
        """Military Position Manager: Progressive Trailing & Small-Trade Cleanup"""
        try:
            if not hasattr(self, '_last_sl_check'): self._last_sl_check = {}
            if not hasattr(self, '_last_sl_set'): self._last_sl_set = {}
            
            positions = self.get_all_positions()
            now = time.time()
            from shared_state import state
            
            for pos in positions:
                symbol = pos['symbol']
                side = pos['side']
                size = float(pos.get('size', 0))
                entry = float(pos.get('entry', 0))
                pnl = float(pos.get('pnl', 0))
                mark_price = float(pos.get('mark_price', 0))
                
                # 0.5 SMALL TRADE SCRUBBER (Hapus modal dikit)
                notional = size * mark_price
                if 0 < notional < 5.0:
                    print(f"[SCRUBBER] Closing micro-position {symbol} (Notional ${round(notional, 2)})")
                    try:
                        # Use direct V2 close API for maximum priority
                        clean_sym = symbol.replace("/", "").split(":")[0]
                        params = {
                            'symbol': clean_sym,
                            'productType': 'USDT-FUTURES',
                            'holdSide': 'long' if side in ['long', 'buy'] else 'short',
                            'size': str(size)
                        }
                        self._v3_request("POST", "/api/v2/mix/order/close-positions", params)
                        continue
                    except Exception as e:
                        print(f"[SCRUBBER ERROR] {symbol}: {e}")

                # 0. SIDEWAYS DETECTION
                if symbol not in state.pos_start_time:
                    state.pos_start_time[symbol] = now
                
                duration_hours = (now - state.pos_start_time[symbol]) / 3600
                price_move_pct = abs((mark_price - entry) / entry * 100) if entry > 0 else 0
                
                if duration_hours > 4 and -1.5 < pnl < 1.5 and price_move_pct < 0.4:
                    print(f"[SIDEWAYS EXIT] Closing {symbol} - Flat for {round(duration_hours, 1)}h")
                    self.exchange.create_order(symbol, 'market', 'sell' if side in ['long', 'buy'] else 'buy', size)
                    if symbol in state.pos_start_time: del state.pos_start_time[symbol]
                    continue

                if now - self._last_sl_check.get(symbol, 0) < 10: continue
                self._last_sl_check[symbol] = now
                
                # DUAL-LAYER DETECTION (REST + WebSocket Cache)
                clean_sym = self._clean_symbol(symbol)
                plans = self.get_pending_plan_orders(symbol)
                ws_plans = [o for o in state.orders if self._clean_symbol(o.get('symbol', o.get('instId', ''))) == clean_sym]
                
                has_sl = False
                has_tp = False
                for p in (plans + ws_plans):
                    p_type = str(p.get('type', p.get('planType', ''))).lower()
                    # Bitget V2: psl = profit_stop_loss (usually SL), ptp = partial_take_profit
                    if any(x in p_type for x in ['sl', 'loss', 'stop', 'psl']):
                        has_sl = True
                    if any(x in p_type for x in ['tp', 'profit', 'ptp']):
                        has_tp = True

                # Military Status Log
                if int(now) % 60 < 2: # Reduced log frequency
                    print(f"[MONITOR] {symbol} | PNL: {pnl}% | SL: {'OK' if has_sl else 'MISSING'} | TP: {'OK' if has_tp else 'MISSING'}")

                # 1. EMERGENCY HARD EXIT (-15% PnL = 1.5x SL, proteksi ekstra)
                if pnl <= -15:
                    print(f"[HARD EXIT] {symbol} hit {pnl}% PNL. Closing immediately.")
                    self.exchange.create_order(symbol, 'market', 'sell' if side in ['long', 'buy'] else 'buy', size)
                    continue

                # 2. INITIAL GUARD — pasang SL/TP kalau belum ada
                if (not has_sl or not has_tp) and now - self.startup_time > self.warmup_period:
                    if now - self._last_sl_set.get(symbol, 0) > 60:
                        print(f"[GUARD] Protecting {symbol} | SL 15% PnL | TP 80% PnL")
                        # TP 80% PnL = 8% price move di 10x
                        # SL 15% PnL = 1.5% price move di 10x
                        sl_price = entry * 0.985 if side in ['long', 'buy'] else entry * 1.015
                        tp_price = entry * 1.08  if side in ['long', 'buy'] else entry * 0.92
                        if not has_sl:
                            self._set_sl_tp_bitget(symbol, side, size, sl_price=sl_price)
                        if not has_tp:
                            self._set_sl_tp_bitget(symbol, side, size, tp_price=tp_price)
                        self._last_sl_set[symbol] = now

                # 3. PROGRESSIVE TRAILING — naik setiap +10% PnL
                # Sesuai request: naik 10% → SL ke entry, naik 20% → SL ke +10%, dst
                new_sl = 0
                sl_p = 0
                for p in plans:
                    pt = p.get('type', '')
                    if 'sl' in pt or 'loss' in pt or 'psl' in pt:
                        sl_p = p['price']
                        break

                if side in ['long', 'buy']:
                    if pnl >= 45: new_sl = entry * 1.35   # Lock +35%
                    elif pnl >= 35: new_sl = entry * 1.25  # Lock +25%
                    elif pnl >= 25: new_sl = entry * 1.15  # Lock +15%
                    elif pnl >= 20: new_sl = entry * 1.10  # Lock +10%
                    elif pnl >= 10: new_sl = entry * 1.002 # Breakeven +0.2%
                else:
                    if pnl >= 45: new_sl = entry * 0.65
                    elif pnl >= 35: new_sl = entry * 0.75
                    elif pnl >= 25: new_sl = entry * 0.85
                    elif pnl >= 20: new_sl = entry * 0.90
                    elif pnl >= 10: new_sl = entry * 0.998

                if new_sl > 0:
                    is_better = (side in ['long', 'buy'] and new_sl > sl_p) or \
                                (side in ['short', 'sell'] and (new_sl < sl_p or sl_p == 0))

                    if is_better and now - self._last_sl_set.get(symbol, 0) > 60:
                        print(f"🔥 [TRAIL] {symbol} SL → {round(new_sl,6)} (PNL: {pnl}%)")
                        self._set_sl_tp_bitget(symbol, side, size, sl_price=new_sl)
                        self._last_sl_set[symbol] = now
        except Exception as e:
            print(f"[POSITION MANAGER CRASH] {e}")

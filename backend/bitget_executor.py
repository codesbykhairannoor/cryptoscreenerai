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

    def get_max_available(self, symbol, leverage=10, risk_usdt=3.0):
        """
        Hitung size untuk 1 trade maksimal.
        FIX: Dibatasi cuman $3 per trade sesuai permintaan USER.
        """
        try:
            balance   = self.get_balance()
            free_usdt = balance['free']

            if free_usdt < risk_usdt:
                print(f"[SIZE] Balance tidak cukup untuk trade ${risk_usdt}: ${free_usdt:.2f}")
                # Fallback ke sisa balance jika masih di atas $0.5 (untuk 10x leverage = $5 notional)
                if free_usdt >= 0.55:
                    margin_to_use = free_usdt * 0.90
                else:
                    return 0
            else:
                # Kunci di $3 sesuai request
                margin_to_use = risk_usdt

            # Minimum notional Bitget = 5 USDT
            if margin_to_use * leverage < 5.0:
                print(f"[SIZE] Notional terlalu kecil: ${margin_to_use * leverage:.2f} (Min $5)")
                return 0

            ticker = self.exchange.fetch_ticker(symbol)
            price  = ticker['last']

            notional   = margin_to_use * leverage
            raw_amount = notional / price

            formatted_amount = float(self.exchange.amount_to_precision(symbol, raw_amount))

            market     = self.exchange.market(symbol)
            min_amount = market.get('limits', {}).get('amount', {}).get('min', 0.001)

            if formatted_amount * price < 5.0:
                return 0

            print(f"[SIZE] Full balance | Margin=${margin_to_use:.2f} | Notional=${round(notional,1)} | {formatted_amount} {symbol}")
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

            # 3. AMBIL HARGA FILL   handle NoneType
            raw_price = order.get('price') or order.get('average') or order.get('info', {}).get('priceAvg')
            if raw_price is None or float(raw_price) == 0:
                ticker = self.exchange.fetch_ticker(symbol)
                raw_price = ticker['last']
            price = float(raw_price)

            # 4. VALIDASI SL/TP DARI HARGA FILL AKTUAL
            # Pakai SL/TP yang dikirim dari crypto_engine (sudah dihitung dengan benar).
            # Hanya override kalau SL arahnya salah (long SL di atas price, dll).
            # JANGAN recalculate dengan price * 0.985 karena itu bisa lebih kecil
            # dari SL yang sudah dihitung dengan benar di _calc_tp_sl.
            if side.lower() in ['long', 'buy']:
                # SL long harus di bawah fill price
                if sl and sl > 0 and sl < price:
                    final_sl = sl   # Pakai SL dari crypto_engine   sudah benar
                else:
                    final_sl = price * 0.976   # Fallback: 2.4% = 24% PnL
                    print(f"[SL FALLBACK] {symbol} SL invalid ({sl}), pakai 2.4%: {round(final_sl,6)}")
                # TP long harus di atas fill price
                if tp and tp > 0 and tp > price:
                    final_tp = tp
                else:
                    final_tp = price * 1.08   # Fallback: 8% = 80% PnL
                    print(f"[TP FALLBACK] {symbol} TP invalid ({tp}), pakai 8%: {round(final_tp,6)}")
            else:
                # SL short harus di atas fill price
                if sl and sl > 0 and sl > price:
                    final_sl = sl
                else:
                    final_sl = price * 1.024
                    print(f"[SL FALLBACK] {symbol} SL invalid ({sl}), pakai 2.4%: {round(final_sl,6)}")
                if tp and tp > 0 and tp < price:
                    final_tp = tp
                else:
                    final_tp = price * 0.92
                    print(f"[TP FALLBACK] {symbol} TP invalid ({tp}), pakai 8%: {round(final_tp,6)}")

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
                    sl_price = current_price * 0.976   # 2.4% = 24% PnL
                    print(f"[SL ADJUST] {symbol} SL adjusted to {round(sl_price,6)}")
                elif hold_side == 'short' and sl_price <= current_price * 1.001:
                    sl_price = current_price * 1.024   # 2.4% = 24% PnL
                    print(f"[SL ADJUST] {symbol} SL adjusted to {round(sl_price,6)}")
            self._set_sl_ccxt(symbol, side, size, sl_price)

        if tp_price and tp_price > 0:
            self._set_tp_ccxt(symbol, side, size, tp_price)

    def _set_sl_ccxt(self, symbol, side, size, sl_price):
        """Set SL via ccxt   cancel SL lama dulu, lalu buat yang baru."""
        try:
            tp_side = 'sell' if side in ['long', 'buy'] else 'buy'
            ticker  = self.exchange.fetch_ticker(symbol)
            mark    = float(ticker.get('last', 0))
            hold    = 'long' if side in ['long', 'buy'] else 'short'

            if mark > 0:
                if hold == 'long' and sl_price >= mark:
                    sl_price = mark * 0.976    # 2.4% = 24% PnL
                elif hold == 'short' and sl_price <= mark:
                    sl_price = mark * 1.024    # 2.4% = 24% PnL

            # Cancel semua SL order yang ada untuk symbol ini dulu
            # Ini mencegah duplikat SL order
            try:
                clean_sym = symbol.replace("/", "").split(":")[0]
                if not clean_sym.endswith('USDT'): clean_sym += 'USDT'
                existing = self.exchange.private_get_v2_mix_order_plan_current_orders({
                    'symbol': clean_sym, 'productType': 'USDT-FUTURES'
                })
                if existing.get('code') == '00000' and existing.get('data'):
                    for order in existing['data']:
                        plan_type = order.get('planType', '').lower()
                        if any(x in plan_type for x in ['loss', 'sl', 'stop', 'psl']):
                            order_id = order.get('orderId', order.get('planId'))
                            if order_id:
                                self._v3_request("POST", "/api/v2/mix/order/plan/cancelPlan", body={
                                    "symbol": clean_sym,
                                    "productType": "USDT-FUTURES",
                                    "marginCoin": "USDT",
                                    "orderId": str(order_id)
                                })
            except Exception:
                pass  # Kalau cancel gagal, tetap lanjut buat SL baru

            # Buat SL baru
            self.exchange.create_order(
                symbol, 'market', tp_side, size, None,
                params={'productType': 'USDT-FUTURES', 'reduceOnly': True, 'stopLossPrice': sl_price}
            )
            print(f"[SL CCXT] {symbol} SL@{round(sl_price,6)} OK", flush=True)
        except Exception as e:
            print(f"[SL CCXT FAIL] {symbol}: {e}", flush=True)

    def _set_tp_ccxt(self, symbol, side, size, tp_price):
        """Set TP via ccxt."""
        try:
            tp_side = 'sell' if side in ['long', 'buy'] else 'buy'
            self.exchange.create_order(
                symbol, 'market', tp_side, size, None,
                params={'productType': 'USDT-FUTURES', 'reduceOnly': True, 'takeProfitPrice': tp_price}
            )
            print(f"[TP CCXT] {symbol} TP@{round(tp_price,6)} OK", flush=True)
        except Exception as e:
            print(f"[TP CCXT FAIL] {symbol}: {e}", flush=True)

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
        """
        Position Manager: Trailing SL berbasis PEAK PnL.
        
        Prinsip kunci:
        - SL dihitung dari PEAK PnL (tertinggi yang pernah dicapai), bukan PnL saat ini
        - Kalau PnL pernah 50% lalu turun ke 30%, SL tetap di level dari puncak 50%
        - SL hanya bergerak NAIK (long) atau TURUN (short)   tidak pernah mundur
        - Gap SL = 15% dari peak PnL (misal peak 50%   SL di 35%)
        """
        try:
            if not hasattr(self, '_last_sl_check'): self._last_sl_check = {}
            if not hasattr(self, '_last_sl_set'):   self._last_sl_set = {}
            if not hasattr(self, '_tracked_positions'): self._tracked_positions = {}

            # Peak PnL disimpan di shared_state agar persist saat restart
            # Kalau bot restart saat trade jalan, peak PnL tidak hilang
            from shared_state import state
            if not hasattr(state, 'peak_pnl'): state.peak_pnl = {}
            self._peak_pnl = state.peak_pnl  # Reference ke shared state

            positions = self.get_all_positions()
            now = time.time()
            from shared_state import state

            # Normalisasi semua symbol ke format clean (tanpa /USDT:USDT, dll)
            # Ini mencegah duplikat tracking karena WS dan REST pakai format berbeda
            # Contoh: "SAHARA/USDT:USDT" dan "SAHARAUSDT" keduanya jadi "SAHARA"
            current_symbols = {self._clean_symbol(p['symbol']): p.get('pnl', 0) for p in positions}
            
            # Detect ANY position that was closed (TP hit, SL hit, manual close)
            closed_symbols = set(self._tracked_positions.keys()) - set(current_symbols.keys())
            for clean in closed_symbols:
                last_pnl = self._tracked_positions[clean]
                
                if not hasattr(state, 'recently_exited'): state.recently_exited = {}
                state.recently_exited[clean] = now
                
                if not hasattr(state, 'exit_pnl'): state.exit_pnl = {}
                state.exit_pnl[clean] = last_pnl
                
                print(f"[TRACKER] Trade {clean} closed with PnL {last_pnl}%. Cooldown initiated.")
            
            self._tracked_positions = current_symbols

            for pos in positions:
                symbol     = pos['symbol']
                side       = pos['side']
                size       = float(pos.get('size', 0))
                entry      = float(pos.get('entry', 0))
                pnl        = float(pos.get('pnl', 0))
                mark_price = float(pos.get('mark_price', 0))

                #    SMALL TRADE SCRUBBER                                       
                notional = size * mark_price
                if 0 < notional < 5.0:
                    print(f"[SCRUBBER] Closing micro-position {symbol} (${round(notional,2)})")
                    try:
                        clean_sym = symbol.replace("/", "").split(":")[0]
                        self._v3_request("POST", "/api/v2/mix/order/close-positions", {
                            'symbol': clean_sym, 'productType': 'USDT-FUTURES',
                            'holdSide': 'long' if side in ['long','buy'] else 'short',
                            'size': str(size)
                        })
                        continue
                    except Exception as e:
                        print(f"[SCRUBBER ERROR] {symbol}: {e}")

                #    SIDEWAYS DETECTION                                         
                if symbol not in state.pos_start_time:
                    state.pos_start_time[symbol] = now
                duration_hours = (now - state.pos_start_time[symbol]) / 3600
                price_move_pct = abs((mark_price - entry) / entry * 100) if entry > 0 else 0

                # MINIMUM HOLD TIME: 5 menit sebelum sideways detection aktif
                # Ini mencegah close terlalu cepat karena noise/spread
                # RAVE close 12 detik, CRCL close 11 detik   ini yang dicegah
                if duration_hours >= (5.0 / 60):  # Sudah > 5 menit
                    SIDEWAYS_WARN_HOURS    = 2.0
                    SIDEWAYS_TIMEOUT_HOURS = 2.667
                    is_sideways = (-5.0 < pnl < 5.0) and (price_move_pct < 3.0)

                    if duration_hours > SIDEWAYS_WARN_HOURS and is_sideways:
                        if duration_hours > SIDEWAYS_TIMEOUT_HOURS:
                            print(f"[SIDEWAYS TIMEOUT] {symbol} {round(duration_hours,1)}h. Force close.")
                            self.exchange.create_order(symbol, 'market',
                                'sell' if side in ['long','buy'] else 'buy', size)
                            if symbol in state.pos_start_time: del state.pos_start_time[symbol]
                            if symbol in self._peak_pnl: del self._peak_pnl[symbol]
                            clean = self._clean_symbol(symbol)
                            if not hasattr(state, 'recently_exited'): state.recently_exited = {}
                            state.recently_exited[clean] = time.time()
                            continue
                        elif pnl >= 5.0:
                            print(f"[SIDEWAYS EXIT] {symbol} {round(duration_hours,1)}h. PnL {pnl}% >= 5%.")
                            self.exchange.create_order(symbol, 'market',
                                'sell' if side in ['long','buy'] else 'buy', size)
                            if symbol in state.pos_start_time: del state.pos_start_time[symbol]
                            if symbol in self._peak_pnl: del self._peak_pnl[symbol]
                            clean = self._clean_symbol(symbol)
                            if not hasattr(state, 'recently_exited'): state.recently_exited = {}
                            state.recently_exited[clean] = time.time()
                            continue
                        else:
                            if int(now) % 60 < 2:
                                remaining_min = round((SIDEWAYS_TIMEOUT_HOURS - duration_hours) * 60)
                                print(f"[SIDEWAYS WARNING] {symbol} {round(duration_hours,1)}h. "
                                      f"PnL:{pnl}% (need 5%+). Timeout in {remaining_min}min.")
                else:
                    # Belum 5 menit   log saja, jangan close
                    if int(now) % 30 < 2:
                        print(f"[HOLD] {symbol} baru {round(duration_hours*60,1)} menit. Min hold 5 menit.")

                if now - self._last_sl_check.get(symbol, 0) < 10: continue
                self._last_sl_check[symbol] = now

                #    UPDATE PEAK PnL                                            
                # Ini kunci: track PnL tertinggi yang pernah dicapai
                prev_peak = self._peak_pnl.get(symbol, 0)
                if pnl > prev_peak:
                    self._peak_pnl[symbol] = pnl
                peak_pnl = self._peak_pnl.get(symbol, pnl)

                #    DETECT SL/TP                                               
                clean_sym = self._clean_symbol(symbol)
                plans     = self.get_pending_plan_orders(symbol)
                ws_plans  = [o for o in state.orders if self._clean_symbol(
                    o.get('symbol', o.get('instId', ''))) == clean_sym]

                has_sl = False
                has_tp = False
                sl_p   = 0
                for p in (plans + ws_plans):
                    p_type = str(p.get('type', p.get('planType', ''))).lower()
                    if any(x in p_type for x in ['sl', 'loss', 'stop', 'psl']):
                        has_sl = True
                        candidate = float(p.get('price', 0))
                        if candidate > 0:
                            sl_p = max(sl_p, candidate) if side in ['long','buy'] else (
                                candidate if sl_p == 0 else min(sl_p, candidate))
                    if any(x in p_type for x in ['tp', 'profit', 'ptp']):
                        has_tp = True

                if int(now) % 60 < 2:
                    print(f"[MONITOR] {symbol} | PNL:{pnl}% PEAK:{peak_pnl}% | "
                          f"SL:{'OK' if has_sl else 'MISSING'} TP:{'OK' if has_tp else 'MISSING'}")

                #    HARD EXIT                                                  
                if pnl <= -24:
                    print(f"[HARD EXIT] {symbol} hit {pnl}% PNL. Closing.")
                    self.exchange.create_order(symbol, 'market',
                        'sell' if side in ['long','buy'] else 'buy', size)
                    if symbol in self._peak_pnl: del self._peak_pnl[symbol]
                    
                    clean = self._clean_symbol(symbol)
                    if not hasattr(state, 'recently_exited'): state.recently_exited = {}
                    state.recently_exited[clean] = time.time()
                    continue

                #    INITIAL GUARD                                              
                if (not has_sl or not has_tp) and now - self.startup_time > self.warmup_period:
                    if now - self._last_sl_set.get(symbol, 0) > 60:
                        print(f"[GUARD] Protecting {symbol} | SL 24% | TP 90%")
                        sl_price = entry * 0.976 if side in ['long','buy'] else entry * 1.024
                        tp_price = entry * 1.09  if side in ['long','buy'] else entry * 0.91
                        if not has_sl: self._set_sl_tp_bitget(symbol, side, size, sl_price=sl_price)
                        if not has_tp: self._set_sl_tp_bitget(symbol, side, size, tp_price=tp_price)
                        self._last_sl_set[symbol] = now

                #    TRAILING SL — GRANULAR SETIAP 5% PnL, GAP 10%
                # ─────────────────────────────────────────────────────
                # peak=10%  → SL ke 0%   (breakeven)
                # peak=15%  → SL ke 5%
                # peak=20%  → SL ke 10%
                # peak=25%  → SL ke 15%
                # peak=30%  → SL ke 20%
                # peak=35%  → SL ke 25%
                # peak=40%  → SL ke 30%
                # peak=90%  → SL ke 80%  (TP target)
                # Formula: locked = floor(peak/5)*5 - 10, min 0
                # ─────────────────────────────────────────────────────
                LEVERAGE_FACTOR = 10.0
                new_sl = 0

                if peak_pnl >= 10:
                    locked_pnl = float(int(peak_pnl / 5) * 5 - 10)
                    locked_pnl = max(0.0, locked_pnl)

                    if side in ['long', 'buy']:
                        new_sl = entry * (1 + (locked_pnl / 100.0) / LEVERAGE_FACTOR)
                    else:
                        new_sl = entry * (1 - (locked_pnl / 100.0) / LEVERAGE_FACTOR)

                if new_sl > 0:
                    if side in ['long', 'buy']:
                        is_better = new_sl > sl_p
                    else:
                        is_better = (sl_p == 0) or (new_sl < sl_p)

                    if is_better and now - self._last_sl_set.get(symbol, 0) > 30:
                        locked = max(0, int(peak_pnl / 5) * 5 - 10)
                        print(
                            f"[TRAIL] {symbol} SL {round(sl_p,6)} -> {round(new_sl,6)} "
                            f"| PNL:{pnl:.1f}% PEAK:{peak_pnl:.1f}% LOCKED:{locked:.0f}%",
                            flush=True
                        )
                        self._set_sl_tp_bitget(symbol, side, size, sl_price=new_sl)
                        self._last_sl_set[symbol] = now

        except Exception as e:
            print(f"[POSITION MANAGER CRASH] {e}")

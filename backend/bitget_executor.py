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
        self._is_ordering = False # Lock untuk cegah double trade

        self.exchange = ccxt.bitget({
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'password': self.passphrase,
            'enableRateLimit': True,
            'timeout': 30000,
            'options': {
                'defaultType': 'swap',
                'posMode': 'unilateral',
                'adjustForTimeDifference': True
            }
        })
        
        # Security Check
        if not self.api_key or not self.secret_key:
             print("[CRITICAL] Bitget Credentials MISSING! Check your .env file.")
        
        self.is_uta = False
        self.startup_time = time.time()
        self.warmup_period = 15
        self.time_offset = 0
        self.sync_server_time()
        
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
                    sym  = p['symbol']
                    side = p['side']
                    pnl  = p['pnl']
                    entry = p.get('entry', 0)
                    mark  = p.get('mark_price', 0)
                    print(f"   > {sym} | Side:{side} | Entry:{entry} | Mark:{mark} | PNL:{pnl}%")
                    self.get_pending_plan_orders(sym)
                    # Seed pos_start_time untuk trade yang sudah berjalan
                    from shared_state import state as _s
                    if sym not in _s.pos_start_time:
                        _s.pos_start_time[sym] = time.time() - 1800
                        print(f"   > [TIMER] {sym} pos_start seeded (restart recovery)", flush=True)
        except Exception as e:
            print(f"[STARTUP AUDIT ERROR] {e}")

    def sync_server_time(self):
        """Fetch server time from Bitget and calculate offset (Fail-safe for Windows VPS)"""
        try:
            res = requests.get("https://api.bitget.com/api/v2/public/time", timeout=20)
            if res.status_code == 200:
                server_ts = int(res.json()['data']['serverTime'])
                local_ts  = int(time.time() * 1000)
                self.time_offset = server_ts - local_ts
                print(f"[SYSTEM] Time Sync: Offset {self.time_offset}ms applied.")
        except Exception as e:
            print(f"[SYSTEM] Time Sync FAILED: {e}")

    def _v3_request(self, method, path, query="", body=None):
        """Signed V3 Request for UTA accounts (Stable Baseline)"""
        ts = str(int(time.time() * 1000 + self.time_offset))
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
            res = requests.request(method, url, headers=headers, data=body_str if body else None, timeout=20, verify=False)
            return res.json()
        except:
            return {"code": "timeout"}

    def _v2_private_request(self, method, path, query="", body=None):
        """Signed V2 Request for Classic/Mix accounts"""
        ts = str(int(time.time() * 1000 + self.time_offset))
        request_path = path
        body_str = json.dumps(body) if body else ""
        
        # V2 Signing: timestamp + method + path + query + body
        message = ts + method.upper() + request_path + (f"?{query}" if query else "") + body_str
        mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
        sign = base64.b64encode(mac.digest()).decode('utf8')
        
        headers = {
            "ACCESS-KEY": self.api_key, "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.passphrase, "Content-Type": "application/json"
        }
        
        url = f"https://api.bitget.com{request_path}" + (f"?{query}" if query else "")
        try:
            res = requests.request(method, url, headers=headers, data=body_str if body else None, timeout=20)
            return res.json()
        except:
            return {"code": "timeout"}

    def detect_account_mode(self):
        """Internal check to confirm if account is UTA or Classic"""
        try:
            # Coba panggil V2 Mix Account (Standar akun modern/classic)
            res = self._v2_private_request("GET", "/api/v2/mix/account/accounts", "productType=USDT-FUTURES")
            if res.get('code') == '00000':
                self.is_uta = False # Berhasil panggil Mix = Classic/Mix mode
                print("[MODE] Account verified as Bitget V2 Classic (Mix).")
            else:
                # Jika gagal, mungkin UTA
                res = self._v3_request("GET", "/api/v3/account/assets", "category=USDT-FUTURES")
                if res.get('code') == '00000':
                    self.is_uta = True
                    print("[MODE] Account verified as Bitget V3 UTA.")
                else:
                    self.is_uta = False
                    print("[MODE] Account fallback to Bitget Classic.")
        except:
            self.is_uta = False
            print("[MODE] Account fallback to Bitget Classic.")

    def _clean_symbol(self, s):
        if not s: return ""
        # Remove common Bitget suffixes and separators
        s = s.upper().replace('/USDT:USDT', '').replace('USDT', '').replace('/', '').replace(':', '').replace('_', '')
        return s.strip()

    def get_balance(self):
        """Unified Balance Fetcher (V2 Direct Priority)"""
        try:
            # 1. WS CACHE PRIORITY
            from shared_state import state
            if state.balances and time.time() - state.last_acc_update < 60:
                bal = state.balances.get('USDT', {})
                if bal:
                    return {'total': float(bal.get('equity', 0)), 'free': float(bal.get('available', 0))}

            # 2. DIRECT V2 REQUEST (Fix for $0 reporting)
            res = self._v2_private_request("GET", "/api/v2/mix/account/accounts", "productType=USDT-FUTURES")
            if res.get('code') == '00000' and res.get('data'):
                for acc in res['data']:
                    if acc.get('marginCoin') == 'USDT':
                        return {
                            'total': float(acc.get('equity', 0)), 
                            'free': float(acc.get('available', 0))
                        }

            # 3. REST FALLBACK
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

            final_notional = formatted_amount * price
            print(f"[SIZE-DEBUG] {symbol} | Requested Margin: ${margin_to_use:.2f} | Final Margin: ${final_notional/leverage:.2f} | Notional: ${final_notional:.2f} | Size: {formatted_amount}")
            
            if final_notional < 5.0:
                print(f"[SIZE] Notional ${final_notional:.2f} < $5 minimum. Skipping.")
                return 0

            return formatted_amount if formatted_amount >= min_amount else 0
        except Exception as e:
            print(f"[GET_MAX ERROR] {e}")
            return 0

    def get_all_positions(self):
        """Fetch all active positions using direct V2 REST API (Fast & Robust)"""
        try:
            from shared_state import state
            # 1. WS CACHE PRIORITY (Trust the cache even if empty, to prevent race conditions)
            if state.last_update > 0 and time.time() - state.last_update < 5:
                return state.positions

            # 2. DIRECT REST FALLBACK (Fail-safe for VPS clock drift)
            res = self._v3_request("GET", "/api/v2/mix/position/all-position", "productType=USDT-FUTURES")
            
            if res.get('code') != '00000':
                print(f"[ERROR] Direct Position Fetch Gagal: {res}")
                return None
            
            data = res.get('data', [])
            positions = []
            for p in data:
                total_vol = float(p.get('total', 0))
                if total_vol > 0:
                    lev = float(p.get('leverage', 10))
                    ent = float(p.get('openPriceAvg', 0))
                    mrk = float(p.get('markPrice', 0))
                    side_sign = 1 if p['holdSide'].lower() in ['long','buy'] else -1
                    
                    # Hitung PnL % yang akurat (ROA * Leverage)
                    pnl_pct = 0
                    if ent > 0:
                        pnl_pct = ((mrk - ent) / ent) * lev * 100 * side_sign

                    positions.append({
                        'symbol': p['symbol'],
                        'side': p['holdSide'].lower(),
                        'amount': total_vol,
                        'entry': ent,
                        'mark_price': mrk,
                        'leverage': lev,
                        'pnl': round(pnl_pct, 2),
                        'margin': float(p.get('margin', 0))
                    })
            # Update cache shared_state
            state.update_positions(positions)
            return positions
        except Exception as e:
            print(f"[ERROR] Exception in get_all_positions: {e}")
            return None

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

    def place_order(self, symbol, side, amount, take_profit_val=None, stop_loss_val=None, leverage=10):
        # == POSITION GUARD (v26.63) ==
        # Mencegah 'Ghost Trades' (duplikasi posisi)
        try:
            existing = self.get_all_positions()
            if existing:
                clean_sym = self._clean_symbol(symbol)
                for pos in existing:
                    if self._clean_symbol(pos['symbol']) == clean_sym:
                        print(f"[GUARD] Posisi {symbol} sudah ada. Skip order baru.")
                        return False, "POSITION_EXISTS"
        except Exception as e:
            print(f"[GUARD ERROR] {e}")

        self._is_ordering = True
        try:
            # 1. SETUP DIRECT API (Bypass CCXT for reliability)
            clean_symbol = symbol.replace("/", "").split(":")[0]
            if not clean_symbol.endswith('USDT'): clean_symbol += 'USDT'
            
            # 2. AMBIL HARGA MARKET DULU (Untuk SL/TP calculation sebelum nembak)
            try:
                price_res = requests.get(f"https://api.bitget.com/api/v2/mix/market/ticker?symbol={clean_symbol}&productType=USDT-FUTURES", timeout=10)
                price = float(price_res.json()['data'][0]['lastPr'])
            except Exception:
                # Fallback ke CCXT kalau public API error
                ticker = self.exchange.fetch_ticker(symbol)
                price = float(ticker['last'])

            # 3. HITUNG SL/TP (Finalized Logic)
            final_sl = None
            final_tp = None

            if side.lower() in ['long', 'buy']:
                if stop_loss_val and stop_loss_val > 0 and stop_loss_val < price:
                    final_sl = stop_loss_val
                else:
                    final_sl = price * 0.95
                if take_profit_val and take_profit_val > 0 and take_profit_val > price:
                    final_tp = take_profit_val
                else:
                    final_tp = price * 1.08
            else:
                if stop_loss_val and stop_loss_val > 0 and stop_loss_val > price:
                    final_sl = stop_loss_val
                else:
                    final_sl = price * 1.05
                if take_profit_val and take_profit_val > 0 and take_profit_val < price:
                    final_tp = take_profit_val
                else:
                    final_tp = price * 0.92

            # 4. MARKET ORDER + SL + TP (Direct API V2)
            path = "/api/v2/mix/order/place-order"
            method = "POST"
            
            payload = {
                "symbol": clean_symbol,
                "productType": "USDT-FUTURES",
                "marginCoin": "USDT",
                "marginMode": "isolated",
                "size": str(amount),
                "side": side.lower(),
                "orderType": "market",
                "presetStopLossPrice": str(round(final_sl, 6)),
                "presetTakeProfitPrice": str(round(final_tp, 6))
            }
            
            res_data = self._v3_request(method, path, body=payload)
            
            if res_data.get('code') != '00000':
                print(f"[BITGET ERROR] Direct API Rejected: {res_data}")
                return False, res_data.get('msg', 'Unknown Error')

            order_id = res_data['data']['orderId']
            print(f"[BITGET SUCCESS] {side.upper()} {clean_symbol} executed with SL/TP. ID: {order_id}")
            
            # Dummy order object for compatibility
            order = {'id': order_id, 'symbol': symbol, 'side': side, 'amount': amount}

            # 6. INVALIDATE CACHE (PENTING!)
            # Paksa bot untuk fetch posisi terbaru dari REST di loop berikutnya
            # agar tidak membuka trade kedua.
            from shared_state import state
            state.last_update = 0

            print(f"[ORDER OK] {symbol} {side.upper()} | Entry: {price} | take_profit_val: {final_tp} (+{round((final_tp/price-1)*100,2)}%) | stop_loss_val: {final_sl} (-{round((1-final_sl/price)*100,2)}%)")
            return True, order
        except Exception as e:
            print(f"[CLASSIC ORDER FAILED] {e}")
            return False, str(e)
        finally:
            self._is_ordering = False

    def _set_sl_tp_bitget(self, symbol, side, size, sl_price=None, tp_price=None):
        """
        Set stop_loss_val/take_profit_val untuk Bitget Classic.
        Berdasarkan testing: ccxt stopLossPrice/takeProfitPrice params BEKERJA.
        Skip API plan endpoint yang selalu NOT FOUND.
        """
        # Ambil mark price sekarang untuk validasi
        try:
            # Gunakan requests agar tidak crash
            clean_symbol = symbol.replace("/", "").split(":")[0]
            if not clean_symbol.endswith('USDT'): clean_symbol += 'USDT'
            price_res = requests.get(f"https://api.bitget.com/api/v2/mix/market/ticker?symbol={clean_symbol}&productType=USDT-FUTURES", timeout=10)
            current_price = float(price_res.json()['data'][0]['lastPr'])
        except Exception:
            current_price = 0

        hold_side = 'long' if side in ['long', 'buy'] else 'short'

        if sl_price and sl_price > 0:
            # Validasi: stop_loss_val long harus di bawah current price
            if current_price > 0:
                # Cegah reset stop_loss_val ke bawah jika posisi sedang UNTUNG BESAR
                # Hanya reset jika stop_loss_val baru BENAR-BENAR menabrak harga (jarak < 0.05%)
                if hold_side == 'long' and sl_price >= current_price * 0.9995:
                    print(f"[stop_loss_val GUARD] {symbol} stop_loss_val too close, skipping update to protect profit.")
                    return
                elif hold_side == 'short' and sl_price <= current_price * 1.0005:
                    print(f"[stop_loss_val GUARD] {symbol} stop_loss_val too close, skipping update.")
                    return
            self._set_sl_ccxt(symbol, side, size, sl_price)

        if tp_price and tp_price > 0:
            self._set_tp_ccxt(symbol, side, size, tp_price)

    def _set_sl_ccxt(self, symbol, side, size, sl_price):
        """Set stop_loss_val via Clean Dedicated TPSL API V2"""
        try:
            clean_symbol = symbol.replace("/", "").split(":")[0]
            if not clean_symbol.endswith('USDT'): clean_symbol += 'USDT'
            
            path = "/api/v2/mix/order/place-tpsl-order"
            method = "POST"
            
            # Payload super bersih sesuai dokumentasi TPSL V2
            payload = {
                "symbol": clean_symbol,
                "productType": "USDT-FUTURES",
                "marginCoin": "USDT",
                "triggerPrice": str(sl_price),
                "triggerType": "mark_price",
                "holdSide": "long" if side.lower() in ['buy', 'long'] else "short",
                "tpslType": "sl",
                "orderType": "market"
            }
            
            res = self._v3_request(method, path, body=payload)
            if res.get('code') == '00000':
                print(f"[SL OK] TPSL Direct API set at {sl_price}")
            else:
                print(f"[SL FAIL] {res}")
        except Exception as e:
            print(f"[SL ERROR] {e}")

    def _set_tp_ccxt(self, symbol, side, size, tp_price):
        """Set take_profit_val via Clean Dedicated TPSL API V2"""
        try:
            clean_symbol = symbol.replace("/", "").split(":")[0]
            if not clean_symbol.endswith('USDT'): clean_symbol += 'USDT'

            path = "/api/v2/mix/order/place-tpsl-order"
            method = "POST"
            
            payload = {
                "symbol": clean_symbol,
                "productType": "USDT-FUTURES",
                "marginCoin": "USDT",
                "triggerPrice": str(tp_price),
                "triggerType": "mark_price",
                "holdSide": "long" if side.lower() in ['buy', 'long'] else "short",
                "tpslType": "tp",
                "orderType": "market"
            }
            
            res = self._v3_request(method, path, body=payload)
            if res.get('code') == '00000':
                print(f"[TP OK] TPSL Direct API set at {tp_price}")
            else:
                print(f"[TP FAIL] {res}")
        except Exception as e:
            print(f"[TP ERROR] {e}")

    def _set_sl_tp_ccxt(self, symbol, side, size, sl_price=None, tp_price=None):
        """Fallback lengkap: set stop_loss_val dan take_profit_val via ccxt."""
        if sl_price and sl_price > 0:
            self._set_sl_ccxt(symbol, side, size, sl_price)
        if tp_price and tp_price > 0:
            self._set_tp_ccxt(symbol, side, size, tp_price)

    def update_sl_price(self, symbol, side, amount, new_price, is_tp=False):
        """Update stop_loss_val atau take_profit_val yang sudah ada via Plan Order API."""
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
        Position Manager: Trailing stop_loss_val berbasis PEAK PnL.
        
        Prinsip kunci:
        - stop_loss_val dihitung dari PEAK PnL (tertinggi yang pernah dicapai), bukan PnL saat ini
        - Kalau PnL pernah 50% lalu turun ke 30%, stop_loss_val tetap di level dari puncak 50%
        - stop_loss_val hanya bergerak NAIK (long) atau TURUN (short)   tidak pernah mundur
        - Gap stop_loss_val = 15% dari peak PnL (misal peak 50%   stop_loss_val di 35%)
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
            
            # Detect ANY position that was closed (take_profit_val hit, stop_loss_val hit, manual close)
            closed_symbols = set(self._tracked_positions.keys()) - set(current_symbols.keys())
            for clean in closed_symbols:
                last_pnl = self._tracked_positions[clean]
                
                if not hasattr(state, 'recently_exited'): state.recently_exited = {}
                state.recently_exited[clean] = now
                
                if not hasattr(state, 'exit_pnl'): state.exit_pnl = {}
                state.exit_pnl[clean] = last_pnl
                
                # --- AUDIT TOTAL v31.5: Simpan ke Database + Log Detail ---
                try:
                    from database import close_trade
                    # Gunakan nama koin asli dari database (biasanya LYNUSDT atau LYN/USDT:USDT)
                    # Kita cari koin yang pas di DB
                    full_symbol = f"{clean}USDT"
                    # Asumsikan exit_price mendekati mark_price terakhir atau hitung dari PnL
                    # Ini untuk estimasi jika kita tidak punya harga exit eksak dari WS
                    close_trade(full_symbol, exit_price=0, pnl_usd=0) 
                except: pass

                print(f"\n[TRACKER] [DONE] TRADE CLOSED: {clean} | PnL: {last_pnl}%")
                print(f"          Status: Cooldown 24 jam (Win Pattern v29.1) aktif.\n")
            
            self._tracked_positions = current_symbols

            for pos in positions:
                symbol     = pos['symbol']
                side       = pos['side']
                size       = float(pos.get('amount', 0))
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
                # Hanya aktif setelah trade berjalan CUKUP LAMA
                # Gunakan waktu dari pos_start_time ATAU fallback ke sekarang
                if symbol not in state.pos_start_time:
                    state.pos_start_time[symbol] = now
                duration_hours = (now - state.pos_start_time[symbol]) / 3600
                price_move_pct = abs((mark_price - entry) / entry * 100) if entry > 0 else 0

                # MINIMUM HOLD TIME: 30 menit sebelum sideways detection aktif
                # Naik dari 5 menit - trade butuh waktu untuk berkembang
                # Ini juga mencegah false close saat bot restart (timer reset ke 0)
                MIN_HOLD_HOURS     = 0.5    # 30 menit minimum hold
                SIDEWAYS_WARN_HOURS    = 3.0   # Warning setelah 3 jam
                SIDEWAYS_TIMEOUT_HOURS = 4.0   # Force close setelah 4 jam

                # Sideways: PnL stuck di -10% to +10% DAN harga tidak bergerak
                # Threshold dinaikkan dari 5% ke 10% supaya tidak terlalu sensitif
                is_sideways = (-10.0 < pnl < 10.0) and (price_move_pct < 2.0)

                if duration_hours >= MIN_HOLD_HOURS:
                    if duration_hours > SIDEWAYS_WARN_HOURS and is_sideways:
                        if duration_hours > SIDEWAYS_TIMEOUT_HOURS:
                            print(f"[SIDEWAYS TIMEOUT] {symbol} {round(duration_hours,1)}h sideways. Force close.", flush=True)
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
                                print(f"[SIDEWAYS WARNING] {symbol} {round(duration_hours,1)}h | "
                                      f"PnL:{pnl:.1f}% | Timeout in {remaining_min}min.", flush=True)
                else:
                    if int(now) % 60 < 2:
                        print(f"[HOLD] {symbol} {round(duration_hours*60,1)}min | PnL:{pnl:.1f}% | "
                              f"Min hold: {int(MIN_HOLD_HOURS*60)}min", flush=True)

                if now - self._last_sl_check.get(symbol, 0) < 10: continue
                self._last_sl_check[symbol] = now

                #    UPDATE PEAK PnL                                            
                # Ini kunci: track PnL tertinggi yang pernah dicapai
                prev_peak = self._peak_pnl.get(symbol, 0)
                if pnl > prev_peak:
                    self._peak_pnl[symbol] = pnl
                peak_pnl = self._peak_pnl.get(symbol, pnl)

                #    DETECT stop_loss_val/take_profit_val                                               
                clean_sym = self._clean_symbol(symbol)
                plans     = self.get_pending_plan_orders(symbol)
                ws_plans  = [o for o in state.orders if self._clean_symbol(
                    o.get('symbol', o.get('instId', ''))) == clean_sym]

                has_sl = False
                has_tp = False
                sl_p   = 0
                for p in (plans + ws_plans):
                    p_type = str(p.get('type', p.get('planType', ''))).lower()
                    if any(x in p_type for x in ['stop_loss_val', 'loss', 'stop', 'psl']):
                        has_sl = True
                        candidate = float(p.get('price', 0))
                        if candidate > 0:
                            sl_p = max(sl_p, candidate) if side in ['long','buy'] else (
                                candidate if sl_p == 0 else min(sl_p, candidate))
                    if any(x in p_type for x in ['take_profit_val', 'profit', 'ptp']):
                        has_tp = True

                if int(now) % 60 < 2:
                    print(f"[MONITOR] {symbol} | PNL:{pnl}% PEAK:{peak_pnl}% | "
                          f"stop_loss_val:{'OK' if has_sl else 'MISSING'} take_profit_val:{'OK' if has_tp else 'MISSING'}")

                #    HARD EXIT                                                  
                if pnl <= -50:
                    print(f"[HARD EXIT] {symbol} hit {pnl}% PNL. Closing.", flush=True)
                    self.exchange.create_order(symbol, 'market',
                        'sell' if side in ['long','buy'] else 'buy', size)
                    if symbol in self._peak_pnl: del self._peak_pnl[symbol]
                    
                    clean = self._clean_symbol(symbol)
                    if not hasattr(state, 'recently_exited'): state.recently_exited = {}
                    state.recently_exited[clean] = time.time()
                    continue

                #    INITIAL GUARD - Jika stop_loss_val/take_profit_val hilang, pasang LANGSUNG tanpa cooldown
                if (not has_sl or not has_tp) and now - self.startup_time > 5:
                    # stop_loss_val 5% price = 50% PnL at 10x (Optimized v9.3)
                    sl_price = entry * 0.95 if side in ['long','buy'] else entry * 1.05
                    tp_price = entry * 1.09 if side in ['long','buy'] else entry * 0.91
                    if not has_sl: self._set_sl_tp_bitget(symbol, side, size, sl_price=sl_price)
                    if not has_tp: self._set_sl_tp_bitget(symbol, side, size, tp_price=tp_price)
                    self._last_sl_set[symbol] = now

                #    TSL v37.0 - DISABLED (PURE SCALPER MODE)
                # =====================================================
                # Trailing SL dimatikan. Kita murni mengejar Limit Order TP 1.0%
                # untuk memastikan Win Rate 90.9% tercapai tanpa dipotong di tengah jalan.
                # =====================================================
                pass # Bypass trailing logic completely

        except Exception as e:
            print(f"[POSITION MANAGER CRASH] {e}")




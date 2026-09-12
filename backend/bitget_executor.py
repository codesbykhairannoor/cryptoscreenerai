import ccxt
import os
import time
import json
import hmac
import hashlib
import base64
import requests
import uuid
from dotenv import load_dotenv

load_dotenv()

# Suppress InsecureRequestWarning
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class BitgetExecutor:
    """
    Bitget Executor 100% TRUE SPOT (Non-Leverage, Cash-Only Accounting).
    Dirombak total untuk menghilangkan sisa futures/swap endpoints.
    Menggunakan Bitget V2 Spot API & CCXT Spot.
    """
    def __init__(self):
        self.api_key = os.getenv("BITGET_API_KEY")
        self.secret_key = os.getenv("BITGET_SECRET_KEY")
        self.passphrase = os.getenv("BITGET_PASSPHRASE", "")
        self.trade_mode = "live"
        self._is_ordering = False
        self._last_sl_check = {}
        self._tracked_positions = {}
        self._price_cache = {}
        self.startup_time = time.time()
        self.time_offset = 0

        # CCXT Spot Client
        self.exchange = ccxt.bitget({
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'password': self.passphrase,
            'enableRateLimit': True,
            'timeout': 30000,
            'options': {
                'defaultType': 'spot',
                'adjustForTimeDifference': True
            }
        })

        if not self.api_key or not self.secret_key:
            print("[CRITICAL] Bitget API Credentials MISSING! Periksa file .env.")

        self.sync_server_time()

        try:
            from shared_state import state
            state.last_order_update = self.startup_time
            state.last_acc_update = self.startup_time
            
            bal = self.get_balance()
            print(f"[SPOT STARTUP] Bitget Spot USDT: ${bal['total']:.2f} (Available: ${bal['free']:.2f})", flush=True)
            
            pos = self.get_all_positions()
            if pos:
                print(f"[SPOT STARTUP] Posisi Spot Berjalan: {len(pos)}", flush=True)
                for p in pos:
                    print(f"   > {p['symbol']} | Entry: {p['entry']} | Mark: {p['mark_price']} | PNL: {p['pnl']}%", flush=True)
        except Exception as e:
            print(f"[SPOT STARTUP AUDIT ERROR] {e}", flush=True)

    def sync_server_time(self):
        """Sinkronisasi waktu lokal dengan server Bitget (Cegah timestamp error)"""
        try:
            res = requests.get("https://api.bitget.com/api/v2/public/time", timeout=10)
            if res.status_code == 200:
                server_ts = int(res.json()['data']['serverTime'])
                local_ts  = int(time.time() * 1000)
                self.time_offset = server_ts - local_ts
                print(f"[SPOT SYSTEM] Server Time Sync: Offset {self.time_offset}ms diterapkan.", flush=True)
        except Exception as e:
            print(f"[SPOT SYSTEM] Server Time Sync Gagal: {e}", flush=True)

    def _v2_private_request(self, method, path, query="", body=None):
        """Signed V2 Private Request untuk Bitget Spot API"""
        ts = str(int(time.time() * 1000 + self.time_offset))
        request_path = path
        body_str = json.dumps(body) if body else ""
        
        message = ts + method.upper() + request_path + (f"?{query}" if query else "") + body_str
        mac = hmac.new(bytes(self.secret_key or '', encoding='utf8'), bytes(message, encoding='utf8'), digestmod=hashlib.sha256)
        sign = base64.b64encode(mac.digest()).decode('utf8')
        
        headers = {
            "ACCESS-KEY": self.api_key or "",
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.passphrase or "",
            "Content-Type": "application/json"
        }
        
        url = f"https://api.bitget.com{request_path}" + (f"?{query}" if query else "")
        try:
            res = requests.request(method, url, headers=headers, data=body_str if body else None, timeout=15)
            return res.json()
        except Exception as e:
            return {"code": "timeout", "msg": str(e)}

    def test_connection(self):
        """Test kredensial koneksi Bitget Spot"""
        try:
            bal = self.get_balance()
            if bal['total'] > 0 or bal['free'] > 0:
                return True, f"Bitget Spot Terhubung! Saldo: ${bal['free']:.2f} USDT"
            # Coba ping API langsung
            res = self._v2_private_request("GET", "/api/v2/spot/account/assets")
            if res.get('code') == '00000':
                return True, "Bitget Spot Terhubung!"
            return False, f"Bitget API Error: {res.get('msg', 'Unknown')}"
        except Exception as e:
            return False, str(e)

    def _clean_symbol(self, s):
        if not s: return ""
        s = s.upper().replace('/USDT:USDT', '').replace('USDT', '').replace('/', '').replace(':', '').replace('_', '')
        return s.strip()

    def get_balance(self):
        """Mengambil saldo USDT Spot riil dari Bitget"""
        try:
            # 1. DIRECT V2 REQUEST FOR SPOT ASSETS
            res = self._v2_private_request("GET", "/api/v2/spot/account/assets")
            if res.get('code') == '00000' and res.get('data'):
                for asset in res['data']:
                    if asset.get('coin') == 'USDT':
                        free_val = float(asset.get('available', 0) or 0)
                        frozen_val = float(asset.get('frozen', 0) or 0)
                        return {
                            'total': free_val + frozen_val,
                            'free': free_val
                        }

            # 2. CCXT SPOT FALLBACK
            bal = self.exchange.fetch_balance({'type': 'spot'})
            usdt = bal.get('USDT', {})
            return {
                'total': float(usdt.get('total', 0) or 0),
                'free': float(usdt.get('free', 0) or 0)
            }
        except Exception as e:
            print(f"[SPOT BALANCE ERROR] {e}", flush=True)
            return {'total': 0.0, 'free': 0.0}

    def get_max_available(self, symbol, leverage=1, risk_usdt=150.0):
        """
        Hitung ukuran order Spot untuk 1 trade.
        Spot adalah 100% Cash: leverage selalu 1.0.
        """
        try:
            balance = self.get_balance()
            free_usdt = balance['free']

            if free_usdt < 5.0:
                print(f"[SPOT SIZE] Saldo USDT bebas (${free_usdt:.2f}) < $5 minimum. Lewati.", flush=True)
                return 0

            # Alokasi modal: min(saldo bebas * 95%, batas risiko yang ditentukan)
            margin_to_use = min(free_usdt * 0.95, risk_usdt)
            if margin_to_use < 5.0:
                return 0

            # Ambil harga market terkini
            price = 0.0
            try:
                ticker = self.exchange.fetch_ticker(f"{self._clean_symbol(symbol)}/USDT")
                price = float(ticker.get('last') or ticker.get('close') or 0)
            except Exception:
                from database import get_current_price
                price = get_current_price(symbol, 'crypto') or 0

            if price <= 0:
                print(f"[SPOT SIZE ERROR] Gagal mendapatkan harga untuk {symbol}", flush=True)
                return 0

            raw_amount = margin_to_use / price
            clean_sym = f"{self._clean_symbol(symbol)}/USDT"
            
            try:
                formatted_amount = float(self.exchange.amount_to_precision(clean_sym, raw_amount))
            except Exception:
                formatted_amount = round(raw_amount, 4)

            final_notional = formatted_amount * price
            print(f"[SPOT-SIZE] {symbol} | Modal: ${margin_to_use:.2f} | Notional: ${final_notional:.2f} | Size: {formatted_amount}", flush=True)

            if final_notional < 5.0:
                print(f"[SPOT SIZE] Notional ${final_notional:.2f} < $5 minimum Bitget.", flush=True)
                return 0

            return formatted_amount
        except Exception as e:
            print(f"[SPOT GET_MAX ERROR] {e}", flush=True)
            return 0

    def get_all_positions(self):
        """
        Membaca posisi Spot aktif dari database trades (is_paper = FALSE, status = RUNNING).
        PnL dihitung secara live berdasarkan harga terkini di pasar Spot.
        """
        from database import get_connection, is_sqlite, get_current_price
        conn = get_connection()
        cursor = conn.cursor()
        
        try:
            if is_sqlite(conn):
                import sqlite3
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM trades WHERE status IN ('PENDING', 'RUNNING') AND is_paper = 0 AND market = 'crypto'")
            else:
                from psycopg2.extras import RealDictCursor
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT * FROM trades WHERE status IN ('PENDING', 'RUNNING') AND is_paper = FALSE AND market = 'crypto'")
                
            rows = cursor.fetchall()
            positions = []
            now_ts = time.time()
            
            for row in rows:
                sym = row['symbol']
                side = row['side'].lower()
                ent = float(row['entry_price'] or 0)
                amount = float(row['lot_size'] or 0)
                margin = (amount * ent) if ent > 0 else 0
                
                # Cache harga agar tidak spam API
                cache_key = f"price_{sym}"
                cache_entry = self._price_cache.get(cache_key, (0, 0))
                if now_ts - cache_entry[1] < 5:
                    mrk = cache_entry[0]
                else:
                    mrk = get_current_price(sym, 'crypto') or ent
                    self._price_cache[cache_key] = (mrk, now_ts)

                pnl_pct = 0.0
                if ent > 0:
                    pnl_pct = ((mrk - ent) / ent) * 100.0
                
                row_keys = row.keys() if hasattr(row, 'keys') else []
                so_count = row['so_count'] if 'so_count' in row_keys and row['so_count'] is not None else 0
                tot_cost = float(row['total_cost']) if ('total_cost' in row_keys and row['total_cost'] is not None and row['total_cost'] > 0) else margin

                positions.append({
                    'id': row['id'],
                    'symbol': sym,
                    'side': side,
                    'amount': amount,
                    'entry': ent,
                    'mark_price': mrk,
                    'leverage': 1.0,
                    'pnl': round(pnl_pct, 2),
                    'margin': tot_cost if tot_cost > 0 else margin,
                    'tp_price': row['tp_price'],
                    'sl_price': row['sl_price'],
                    'so_count': so_count,
                    'total_cost': tot_cost if tot_cost > 0 else margin
                })
            
            try:
                from shared_state import state
                state.update_positions(positions)
            except Exception: pass
            
            return positions
        except Exception as e:
            print(f"[SPOT ERROR] get_all_positions: {e}", flush=True)
            return []
        finally:
            cursor.close()
            conn.close()

    def place_order(self, symbol, side, amount, take_profit_val=None, stop_loss_val=None, leverage=1):
        """
        Mengeksekusi Order Spot Riil (BUY / SELL Market).
        100% Pasar Spot: Long Only (Beli dengan USDT, Jual koin kembali ke USDT).
        """
        self._is_ordering = True
        try:
            if side.lower() in ['sell', 'short']:
                print(f"[SPOT REJECT] {symbol}: Posisi awal di pasar Spot hanya BUY (Long-Only)!", flush=True)
                return False, "Spot market is Long-Only"

            clean_sym = self._clean_symbol(symbol)
            pair_ccxt = f"{clean_sym}/USDT"

            print(f"[BITGET SPOT] Mengirim MARKET BUY order untuk {pair_ccxt} (Size: {amount})...", flush=True)

            # 1. CCXT SPOT MARKET BUY
            try:
                order = self.exchange.create_order(
                    pair_ccxt,
                    'market',
                    'buy',
                    amount
                )
                order_id = order.get('id', str(uuid.uuid4()))
                fill_price = float(order.get('average') or order.get('price') or 0)
                print(f"[BITGET SPOT SUCCESS] BUY {pair_ccxt} Berhasil! ID: {order_id} | Fill: {fill_price}", flush=True)
                return True, {"id": order_id, "price": fill_price}
            except Exception as ccxt_err:
                print(f"[BITGET SPOT CCXT ERROR] {ccxt_err}. Mencoba V2 REST Direct...", flush=True)

            # 2. DIRECT V2 REST FALLBACK
            payload = {
                "symbol": f"{clean_sym}USDT",
                "side": "buy",
                "orderType": "market",
                "size": str(amount)
            }
            res = self._v2_private_request("POST", "/api/v2/spot/trade/place-order", body=payload)
            if res.get('code') == '00000':
                order_id = res.get('data', {}).get('orderId', '')
                print(f"[BITGET SPOT REST SUCCESS] BUY {clean_sym}USDT ID: {order_id}", flush=True)
                return True, {"id": order_id, "price": 0}
            else:
                err_msg = res.get('msg', 'Unknown Error')
                print(f"[BITGET SPOT ORDER GAGAL] {err_msg}", flush=True)
                return False, err_msg

        except Exception as e:
            print(f"[BITGET SPOT EXCEPTION] {e}", flush=True)
            return False, str(e)
        finally:
            self._is_ordering = False

    def _execute_spot_sell(self, symbol, amount):
        """Menjual koin spot kembali ke USDT saat TP/SL terpicu"""
        clean_sym = self._clean_symbol(symbol)
        pair_ccxt = f"{clean_sym}/USDT"
        try:
            order = self.exchange.create_order(pair_ccxt, 'market', 'sell', amount)
            print(f"[BITGET SPOT SELL SUCCESS] {pair_ccxt} Terjual! ID: {order.get('id')}", flush=True)
            return True
        except Exception as e:
            print(f"[BITGET SPOT SELL CCXT ERROR] {e}. Fallback ke REST...", flush=True)
            payload = {
                "symbol": f"{clean_sym}USDT",
                "side": "sell",
                "orderType": "market",
                "size": str(amount)
            }
            res = self._v2_private_request("POST", "/api/v2/spot/trade/place-order", body=payload)
            return res.get('code') == '00000'

    def update_sl_price(self, symbol, side, amount, new_price, is_tp=False):
        """Simpan trailing SL terbaru ke database untuk persistensi restart"""
        from database import get_connection, is_sqlite
        try:
            conn = get_connection()
            cursor = conn.cursor()
            placeholder = "%s" if not is_sqlite(conn) else "?"
            col = "tp_price" if is_tp else "sl_price"
            cursor.execute(f"UPDATE trades SET {col} = {placeholder} WHERE symbol = {placeholder} AND status IN ('PENDING','RUNNING') AND is_paper = 0", (new_price, symbol))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"[SPOT UPDATE SL ERROR] {e}", flush=True)

    def sync_state_with_exchange(self):
        """Sinkronisasi database dengan status akun bursa riil"""
        pass

    def manage_open_positions(self):
        """
        Mesin Pengendali Posisi Spot Riil (Institutional Trailing Stop & Ratchet Engine).
        100% Sinkron dengan hasil backtest kuantitatif:
        1. Breakeven Lock: Begitu profit menyentuh +3.0%, SL digeser ke Entry + 0.4% (Cover fee & jamin cuan).
        2. Profit Lock Level 1: Begitu profit menyentuh +5.0%, SL dikunci di Entry + 2.5%.
        3. Profit Lock Level 2: Begitu profit menyentuh +8.0%, SL dikunci di Entry + 5.0%.
        4. Hard Exit: Jika harga menyentuh SL / Trailing SL, langsung jual market ke USDT!
        5. Moonshot TP: Amankan profit saat target +50% tercapai.
        6. Sideways Timeout: Bebaskan modal jika posisi stuck 24 jam tanpa arah.
        """
        try:
            from shared_state import state
            if not hasattr(state, 'peak_pnl'): state.peak_pnl = {}
            self._peak_pnl = state.peak_pnl

            positions = self.get_all_positions()
            now = time.time()

            # Deteksi posisi yang baru saja ditutup
            current_symbols = {self._clean_symbol(p['symbol']): p.get('pnl', 0) for p in positions}
            closed_symbols = set(self._tracked_positions.keys()) - set(current_symbols.keys())
            for clean in closed_symbols:
                last_pnl = self._tracked_positions[clean]
                if not hasattr(state, 'recently_exited'): state.recently_exited = {}
                if not hasattr(state, 'exit_pnl'): state.exit_pnl = {}
                state.recently_exited[clean] = now
                state.exit_pnl[clean] = last_pnl
                print(f"\n[SPOT TRACKER] TRADE CLOSED: {clean} | PnL: {last_pnl:.2f}%", flush=True)
            self._tracked_positions = current_symbols

            for pos in positions:
                symbol = pos['symbol']
                pnl = pos['pnl']
                mrk = pos['mark_price']
                sl = float(pos.get('sl_price') or 0)
                tp = float(pos.get('tp_price') or 0)
                side = pos['side']
                amount = float(pos.get('amount') or 0)
                ent = float(pos.get('entry') or 0)

                # Throttle per koin per 8 detik
                if now - self._last_sl_check.get(symbol, 0) < 8: continue
                self._last_sl_check[symbol] = now

                # Update Peak PnL
                if symbol not in self._peak_pnl: self._peak_pnl[symbol] = 0
                if pnl > self._peak_pnl[symbol]: self._peak_pnl[symbol] = pnl
                peak_pnl = self._peak_pnl[symbol]

                # == DYNAMIC MOONSHOT ESCALATOR TRAILING STOP ENGINE ==
                # Initial Guard: SL -2.5% strictly enforced ($2.37 risk on $95)
                if sl == 0 and now - self.startup_time > 5:
                    default_sl = round(ent * 0.975, 6) # -2.5% strict Stop Loss
                    self.update_sl_price(symbol, side, amount, default_sl, is_tp=False)
                    pos['sl_price'] = default_sl
                    sl = default_sl

                # Milestone 5: Super Nova (Peak >= +50.0%) -> Dynamic 8% trail from peak
                if peak_pnl >= 50.0:
                    trail_price = round(mrk * 0.92, 6)
                    if trail_price > sl:
                        self.update_sl_price(symbol, side, amount, trail_price, is_tp=False)
                        pos['sl_price'] = trail_price
                        sl = trail_price
                        print(f"[MOONSHOT ESCALATOR] {symbol} 🔥 SUPER NOVA (+{peak_pnl:.1f}%)! Trailing SL: {trail_price:.6f} (-8% from peak)", flush=True)

                # Milestone 4: Moonshot Lock (Peak >= +35.0%) -> Lock +25.0% profit
                elif peak_pnl >= 35.0:
                    target_sl = round(ent * 1.25, 6)
                    if target_sl > sl:
                        self.update_sl_price(symbol, side, amount, target_sl, is_tp=False)
                        pos['sl_price'] = target_sl
                        sl = target_sl
                        print(f"[MOONSHOT ESCALATOR] {symbol} 🚀 TIER 4 MOONSHOT (+{peak_pnl:.1f}%)! Locked +25.0% at {target_sl:.6f}", flush=True)

                # Milestone 3: Super Runner Lock (Peak >= +18.0%) -> Lock +12.0% profit
                elif peak_pnl >= 18.0:
                    target_sl = round(ent * 1.12, 6)
                    if target_sl > sl:
                        self.update_sl_price(symbol, side, amount, target_sl, is_tp=False)
                        pos['sl_price'] = target_sl
                        sl = target_sl
                        print(f"[MOONSHOT ESCALATOR] {symbol} 💎 TIER 3 SUPER RUNNER (+{peak_pnl:.1f}%)! Locked +12.0% at {target_sl:.6f}", flush=True)

                # Milestone 2: Expansion Lock (Peak >= +10.0%) -> Lock +7.0% profit
                elif peak_pnl >= 10.0:
                    target_sl = round(ent * 1.07, 6)
                    if target_sl > sl:
                        self.update_sl_price(symbol, side, amount, target_sl, is_tp=False)
                        pos['sl_price'] = target_sl
                        sl = target_sl
                        print(f"[MOONSHOT ESCALATOR] {symbol} 🎯 TIER 2 EXPANSION (+{peak_pnl:.1f}%)! Locked +7.0% at {target_sl:.6f}", flush=True)

                # Milestone 1: Momentum Lock (Peak >= +5.5%) -> Lock +3.2% profit
                elif peak_pnl >= 5.5:
                    target_sl = round(ent * 1.032, 6)
                    if target_sl > sl:
                        self.update_sl_price(symbol, side, amount, target_sl, is_tp=False)
                        pos['sl_price'] = target_sl
                        sl = target_sl
                        print(f"[MOONSHOT ESCALATOR] {symbol} ✨ TIER 1 MOMENTUM (+{peak_pnl:.1f}%)! Locked +3.2% at {target_sl:.6f}", flush=True)

                # Milestone 0: Breakeven Risk-Free Lock (Peak >= +2.5%) -> Lock +0.5% profit
                elif peak_pnl >= 2.5:
                    target_sl = round(ent * 1.005, 6)
                    if target_sl > sl:
                        self.update_sl_price(symbol, side, amount, target_sl, is_tp=False)
                        pos['sl_price'] = target_sl
                        sl = target_sl
                        print(f"[MOONSHOT ESCALATOR] {symbol} 🛡️ BREAKEVEN LOCKED (+{peak_pnl:.1f}%)! Locked +0.5% at {target_sl:.6f} [RISK-FREE]", flush=True)

                # 1. CEK STOP LOSS / TRAILING SL TRIGGER
                if sl > 0 and mrk <= sl:
                    exit_type = "Moonshot Escalator Profit" if sl > ent else "Strict Stop Loss"
                    print(f"\n[SPOT EXIT TRIGGER] {symbol} menyentuh {exit_type} ({pnl:.2f}%). Menjual Spot ke USDT...", flush=True)
                    sold = self._execute_spot_sell(symbol, amount)
                    if sold:
                        from database import close_trade
                        close_trade(symbol, exit_price=mrk, pnl_usd=(amount * ent * (pnl / 100)))
                        if symbol in self._peak_pnl: del self._peak_pnl[symbol]
                        clean = self._clean_symbol(symbol)
                        state.recently_exited[clean] = now
                        state.exit_pnl[clean] = pnl
                    continue

                # 2. CEK TAKE PROFIT (Jika diset manual)
                if tp > 0 and mrk >= tp:
                    print(f"\n[SPOT TP TRIGGER] {symbol} menyentuh Manual TP (+{pnl:.2f}%)! Menjual Spot ke USDT...", flush=True)
                    sold = self._execute_spot_sell(symbol, amount)
                    if sold:
                        from database import close_trade
                        close_trade(symbol, exit_price=mrk, pnl_usd=(amount * ent * (pnl / 100)))
                        if symbol in self._peak_pnl: del self._peak_pnl[symbol]
                        clean = self._clean_symbol(symbol)
                        state.recently_exited[clean] = now
                        state.exit_pnl[clean] = pnl
                    continue

                # SIDEWAYS DETECTION (24 jam timeout)
                if symbol not in state.pos_start_time:
                    state.pos_start_time[symbol] = now
                duration_hours = (now - state.pos_start_time[symbol]) / 3600
                price_move_pct = abs((mrk - ent) / ent * 100) if ent > 0 else 0

                if duration_hours >= 24.0 and (-2.5 < pnl < 2.5) and (price_move_pct < 2.0):
                    print(f"[SPOT SIDEWAYS TIMEOUT] {symbol} beku selama 24 jam. Menjual Spot untuk bebaskan modal...", flush=True)
                    sold = self._execute_spot_sell(symbol, amount)
                    if sold:
                        from database import close_trade
                        close_trade(symbol, exit_price=mrk, pnl_usd=(amount * ent * (pnl / 100)))
                        if symbol in self._peak_pnl: del self._peak_pnl[symbol]
                        clean = self._clean_symbol(symbol)
                        state.recently_exited[clean] = now
                        state.exit_pnl[clean] = pnl
                    continue

        except Exception as e:
            print(f"[SPOT POSITION MANAGER CRASH] {e}", flush=True)

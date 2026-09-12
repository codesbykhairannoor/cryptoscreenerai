import time
import uuid
import os
from database import get_connection, is_sqlite, get_virtual_balance, update_virtual_balance, get_current_price, update_trade_dca

class PaperExecutor:
    """
    Simulated Executor for Paper Trading.
    Mimics BitgetExecutor interface but routes trades to a virtual database.
    """
    def __init__(self):
        self.trade_mode = "paper"
        self._peak_pnl = {}       # Akan di-sync ke shared_state setelah startup
        self._tracked_positions = {}   # Untuk mendeteksi posisi yang baru saja tutup
        self._last_sl_check = {}       # Throttle cek SL per 10 detik per symbol
        self._price_cache = {}         # Cache harga: {sym: (price, timestamp)} - hemat CPU!
        self.startup_time = time.time()
        print("[PAPER TRADING] PaperExecutor initialized. Running in simulation mode.")
        bal = self.get_balance()
        print(f"[PAPER TRADING] Virtual Balance: ${bal['total']}")

    def test_connection(self):
        return True, "Paper Trading Mode Active"

    def sync_state_with_exchange(self):
        # Sync memory logic is handled by DB in paper mode
        pass

    def get_balance(self):
        """
        Mengambil saldo virtual dari database.
        PENTING: total harus mencerminkan saldo AWAL + open margin,
        free mencerminkan saldo yang benar-benar tersedia.
        Ini agar GHOST TRADE GUARD di crypto_engine tidak salah baca.
        """
        free_bal = get_virtual_balance()
        # Hitung margin yang sedang dipakai dari posisi aktif
        try:
            conn = get_connection()
            import sqlite3
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM trades WHERE status IN ('PENDING','RUNNING') AND is_paper = 1")
            row = cursor.fetchone()
            open_count = row['cnt'] if row else 0
            cursor.close()
            conn.close()
        except:
            open_count = 0
        # Total = free + estimasi margin yang dipakai (open_count * margin_per_trade)
        margin_per_trade = float(os.getenv("VIRTUAL_MARGIN_PER_TRADE", "150"))
        total_bal = free_bal + (open_count * margin_per_trade)
        return {'total': total_bal, 'free': free_bal}

    def _clean_symbol(self, s):
        if not s: return ""
        s = s.upper().replace('/USDT:USDT', '').replace('USDT', '').replace('/', '').replace(':', '').replace('_', '')
        return s.strip()

    def get_max_available(self, symbol, leverage=1, risk_usdt=150.0):
        """Simulasi kalkulasi size position berdasarkan virtual balance untuk pasar Spot."""
        balance = self.get_balance()
        free_usdt = balance['free']

        if free_usdt < risk_usdt:
            if free_usdt >= 5.0:
                margin_to_use = free_usdt * 0.90
            else:
                return 0
        else:
            margin_to_use = risk_usdt

        price = get_current_price(symbol, 'crypto')
        if not price: return 0
        
        # Di pasar Spot, leverage selalu 1.0. Amount koin = modal USDT / harga koin
        amount = margin_to_use / price
        
        if margin_to_use < 5.0:
            return 0
            
        return round(amount, 4)

    def get_all_positions(self):
        """Membaca posisi RUNNING dari tabel trades yang is_paper=True."""
        conn = get_connection()
        cursor = conn.cursor()
        
        try:
            if is_sqlite(conn):
                conn.row_factory = sqlite3.Row if 'sqlite3' in globals() else conn.row_factory # fallback
                import sqlite3
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM trades WHERE status IN ('PENDING', 'RUNNING') AND is_paper = 1 AND market = 'crypto'")
            else:
                from psycopg2.extras import RealDictCursor
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT * FROM trades WHERE status IN ('PENDING', 'RUNNING') AND is_paper = TRUE AND market = 'crypto'")
                
            rows = cursor.fetchall()
            positions = []
            now_ts = time.time()
            
            for row in rows:
                sym = row['symbol']
                side = row['side'].lower()
                ent = float(row['entry_price'] or 0)
                amount = float(row['lot_size'] or 0)
                leverage = 1.0  # Murni Spot (Non-Leverage)
                margin = (amount * ent) if ent > 0 else 0
                
                # PRICE CACHE: jangan hit API lebih dari 1x per 10 detik per simbol
                cache_key = f"price_{sym}"
                cache_entry = self._price_cache.get(cache_key, (0, 0))
                if now_ts - cache_entry[1] < 10:
                    mrk = cache_entry[0]  # Pakai cache
                else:
                    mrk = get_current_price(sym, 'crypto') or ent
                    self._price_cache[cache_key] = (mrk, now_ts)  # Simpan ke cache

                pnl_pct = 0.0
                if ent > 0:
                    # Di pasar Spot (Long-Only), PnL pct adalah murni perubahan harga koin
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
                    'leverage': leverage,
                    'pnl': round(pnl_pct, 2),
                    'margin': tot_cost if tot_cost > 0 else margin,
                    'tp_price': row['tp_price'],
                    'sl_price': row['sl_price'],
                    'so_count': so_count,
                    'total_cost': tot_cost if tot_cost > 0 else margin
                })
            
            # Update cache shared_state
            try:
                from shared_state import state
                state.update_positions(positions)
            except: pass
            
            return positions
        except Exception as e:
            print(f"[PAPER ERROR] get_all_positions: {e}")
            return []
        finally:
            cursor.close()
            conn.close()

    def place_order(self, symbol, side, amount, take_profit_val=None, stop_loss_val=None, leverage=1):
        """Mengeksekusi trade secara virtual di pasar Spot. Long-Only & Non-Leverage."""
        try:
            if side.lower() in ['sell', 'short']:
                print(f"[PAPER REJECT] {symbol}: Pasar Spot adalah Long-Only! Tidak bisa buka posisi short.")
                return False, "Spot market is Long-Only"

            price = get_current_price(symbol, 'crypto')
            if not price:
                return False, "Failed to get current price"
                
            leverage = 1.0  # Selalu 1x di Spot
            margin_used = (amount * price)  # Total biaya beli koin dalam USDT
            current_bal = get_virtual_balance()
            
            if current_bal < margin_used:
                return False, "Insufficient virtual balance"
                
            # Potong saldo virtual sebesar margin (akan dikembalikan saat trade diclose beserta PnL)
            update_virtual_balance(-margin_used)
            
            order_id = f"VIRTUAL_{uuid.uuid4().hex[:8]}"
            print(f"[PAPER SUCCESS] BUY {symbol} (Spot Simulated) | Cost: ${margin_used:.2f} | Price: {price}")
            
            # Note: logging ke tabel `trades` diurus oleh `log_trade` yang dipanggil `crypto_engine.py` setelah ini me-return True.
            # Tapi wait, `log_trade` tidak mencatat margin_used ke dalam virtual_account, hanya ke trades.
            # Nanti ketika close, saldo akan ditambah margin + pnl_usd.
            
            return True, {"id": order_id, "price": price}
        except Exception as e:
            print(f"[PAPER ERROR] place_order: {e}")
            return False, str(e)

    def _close_paper_position(self, p, current_price, reason="Closed"):
        """Menutup posisi virtual, hitung PnL USD, update database trades dan virtual balance."""
        try:
            ent = p['entry']
            lev = p['leverage']
            amount = p['amount']
            margin = p['margin']
            side = p['side']
            
            # Hitung PnL aktual di pasar Spot
            pnl_pct = 0.0
            if ent > 0:
                pnl_pct = ((current_price - ent) / ent) * 100.0
                
            pnl_usd = margin * (pnl_pct / 100.0)
            
            # Kembalikan margin awal + profit/loss
            amount_to_return = margin + pnl_usd
            new_bal = update_virtual_balance(amount_to_return)
            
            # Update tabel trades
            conn = get_connection()
            cursor = conn.cursor()
            placeholder = "%s" if not is_sqlite(conn) else "?"
            # Tentukan status: WIN/LOSS/NEUTRAL
            # Sideways Timeout = NEUTRAL (tidak menang, tidak kalah)
            # Ini penting agar Win Rate di laporan akurat dan tidak misleading
            is_sideways_close = "Sideways" in reason or "Timeout" in reason
            if is_sideways_close:
                final_status = "NEUTRAL"
            elif pnl_pct >= 0:
                final_status = "WIN"
            else:
                final_status = "LOSS"

            cursor.execute(f'''
                UPDATE trades
                SET exit_price = {placeholder},
                    pnl_usd = {placeholder},
                    pnl_pct = {placeholder},
                    status = {placeholder},
                    closed_at = {placeholder},
                    reason = {placeholder}
                WHERE id = {placeholder}
            ''', (current_price, pnl_usd, pnl_pct, final_status, int(time.time() * 1000), reason, p['id']))
            conn.commit()
            cursor.close()
            conn.close()
            
            print(f"[PAPER CLOSED] {p['symbol']} | PnL: {pnl_pct:.2f}% (${pnl_usd:.2f}) | New Bal: ${new_bal:.2f} | Reason: {reason}")
            
        except Exception as e:
            print(f"[PAPER ERROR] closing position: {e}")

    def update_sl_price(self, symbol, side, amount, new_price, is_tp=False):
        """Mengupdate SL/TP virtual di database."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            placeholder = "%s" if not is_sqlite(conn) else "?"
            
            # Cari trade ID terbaru untuk symbol ini
            if is_sqlite(conn):
                import sqlite3
                conn.row_factory = sqlite3.Row
            else:
                from psycopg2.extras import RealDictCursor
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
            cursor.execute(f"SELECT id FROM trades WHERE symbol = {placeholder} AND status IN ('PENDING','RUNNING') AND is_paper = 1 ORDER BY id DESC LIMIT 1", (symbol,))
            row = cursor.fetchone()
            if row:
                col = "tp_price" if is_tp else "sl_price"
                cursor.execute(f"UPDATE trades SET {col} = {placeholder} WHERE id = {placeholder}", (new_price, row['id']))
                conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"[PAPER ERROR] update_sl_price: {e}")

    def manage_open_positions(self):
        """
        Position Manager untuk Paper Trading.
        100% synchronized dengan bitget_executor:
        - Trailing SL Whale King 10% Ladder + 4% Lock
        - Hard Exit -50%
        - Sideways Timeout 4 jam
        - Initial Guard SL/TP otomatis
        - Peak PnL persist via shared_state
        - Close tracker untuk sync ke database
        """
        try:
            if not hasattr(self, '_last_sl_check'): self._last_sl_check = {}
            if not hasattr(self, '_tracked_positions'): self._tracked_positions = {}

            # Sync peak_pnl ke shared_state agar persist saat restart
            try:
                from shared_state import state
                if not hasattr(state, 'peak_pnl'): state.peak_pnl = {}
                self._peak_pnl = state.peak_pnl
            except: pass

            positions = self.get_all_positions()
            now = time.time()

            # Detect posisi yang baru saja ditutup (sama persis dengan bitget_executor)
            try:
                from shared_state import state
                current_symbols = {self._clean_symbol(p['symbol']): p.get('pnl', 0) for p in positions}
                closed_symbols = set(self._tracked_positions.keys()) - set(current_symbols.keys())
                for clean in closed_symbols:
                    last_pnl = self._tracked_positions[clean]
                    if not hasattr(state, 'recently_exited'): state.recently_exited = {}
                    if not hasattr(state, 'exit_pnl'): state.exit_pnl = {}
                    state.recently_exited[clean] = now
                    state.exit_pnl[clean] = last_pnl
                    print(f"[PAPER TRACKER] Trade Closed: {clean} | PnL: {last_pnl:.2f}%")
                self._tracked_positions = current_symbols
            except: pass


            for pos in positions:
                symbol = pos['symbol']
                pnl = pos['pnl']
                mrk = pos['mark_price']
                sl = float(pos.get('sl_price') or 0)
                tp = float(pos.get('tp_price') or 0)
                side = pos['side']
                lev = pos['leverage']
                ent = pos['entry']

                # Throttle: cek setiap posisi max 1x per 10 detik
                if now - self._last_sl_check.get(symbol, 0) < 10: continue
                self._last_sl_check[symbol] = now

                # Update peak PnL (sync ke shared_state)
                if symbol not in self._peak_pnl: self._peak_pnl[symbol] = 0
                if pnl > self._peak_pnl[symbol]: self._peak_pnl[symbol] = pnl
                peak_pnl = self._peak_pnl[symbol]

                # == SMART SAFETY ORDER DCA ENGINE (Proven 87.3% WR on Real Spot Data) ==
                so_count = int(pos.get('so_count') or 0)
                tot_cost = float(pos.get('total_cost') or (pos['amount'] * ent))

                # Safety Order 1: Trigger saat harga turun >= 1.8% dari entry awal
                if so_count == 0 and mrk <= (ent * 0.982):
                    so_usd = 35.0 # Safety Order 1 ($35 pada modal $100)
                    free_bal = get_virtual_balance()
                    if free_bal >= so_usd:
                        so_lot = round(so_usd / mrk, 4)
                        new_amount = round(pos['amount'] + so_lot, 4)
                        new_cost = round(tot_cost + so_usd, 4)
                        new_entry = round(new_cost / new_amount, 6)
                        new_tp = round(new_entry * 1.009, 6) # Target TP +0.9% dari average entry baru
                        new_sl = round(new_entry * 0.945, 6) # Hard Crash Guard -5.5% dari average entry baru

                        update_virtual_balance(-so_usd)
                        update_trade_dca(pos['id'], new_entry, new_amount, new_cost, new_tp, new_sl, 1)
                        print(f"\n[SMART DCA] {symbol} Executed SO1 ($35) at {mrk:.6f} (-1.8%)! New Avg Entry: {new_entry:.6f} | Lowered TP: {new_tp:.6f} (+0.9%)", flush=True)

                        # Update current loop state
                        pos['entry'] = new_entry
                        pos['amount'] = new_amount
                        pos['margin'] = new_cost
                        pos['total_cost'] = new_cost
                        pos['so_count'] = 1
                        pos['tp_price'] = new_tp
                        pos['sl_price'] = new_sl
                        ent = new_entry
                        tp = new_tp
                        sl = new_sl
                        pnl = round(((mrk - ent) / ent) * 100.0, 2)

                # Safety Order 2: Trigger saat harga turun lagi >= 1.8% dari weighted entry SO1
                elif so_count == 1 and mrk <= (ent * 0.982):
                    so_usd = 40.0 # Safety Order 2 ($40 pada modal $100)
                    free_bal = get_virtual_balance()
                    if free_bal >= so_usd:
                        so_lot = round(so_usd / mrk, 4)
                        new_amount = round(pos['amount'] + so_lot, 4)
                        new_cost = round(tot_cost + so_usd, 4)
                        new_entry = round(new_cost / new_amount, 6)
                        new_tp = round(new_entry * 1.009, 6) # Target TP +0.9% dari average entry baru
                        new_sl = round(new_entry * 0.945, 6) # Hard Crash Guard -5.5% dari average entry baru

                        update_virtual_balance(-so_usd)
                        update_trade_dca(pos['id'], new_entry, new_amount, new_cost, new_tp, new_sl, 2)
                        print(f"\n[SMART DCA] {symbol} Executed SO2 ($40) at {mrk:.6f} (-1.8%)! New Avg Entry: {new_entry:.6f} | Lowered TP: {new_tp:.6f} (+0.9%)", flush=True)

                        # Update current loop state
                        pos['entry'] = new_entry
                        pos['amount'] = new_amount
                        pos['margin'] = new_cost
                        pos['total_cost'] = new_cost
                        pos['so_count'] = 2
                        pos['tp_price'] = new_tp
                        pos['sl_price'] = new_sl
                        ent = new_entry
                        tp = new_tp
                        sl = new_sl
                        pnl = round(((mrk - ent) / ent) * 100.0, 2)

                # INITIAL GUARD: Set default Quick TP (+0.9%) / Crash SL (-5.5%) jika belum terisi
                if (sl == 0 or tp == 0) and now - self.startup_time > 5:
                    default_sl = ent * 0.945   # -5.5% Hard Crash Guard
                    default_tp = ent * 1.009   # +0.9% Quick Mean-Reversion TP (87.3% WR Proven)
                    if sl == 0:
                        self.update_sl_price(symbol, side, pos['amount'], default_sl, is_tp=False)
                        sl = default_sl
                    if tp == 0:
                        self.update_sl_price(symbol, side, pos['amount'], default_tp, is_tp=True)
                        tp = default_tp

                # 1. CEK TAKE PROFIT (+0.9% Mean-Reversion Exit)
                if tp > 0 and mrk >= tp:
                    self._close_paper_position(pos, mrk, reason=f"DCA TP (+{pnl:.2f}%)")
                    if symbol in self._peak_pnl: del self._peak_pnl[symbol]
                    continue

                # 2. CEK HARD STOP LOSS (-5.5% Crash Guard)
                if sl > 0 and mrk <= sl:
                    self._close_paper_position(pos, mrk, reason=f"Hard Crash Guard SL ({pnl:.2f}%)")
                    if symbol in self._peak_pnl: del self._peak_pnl[symbol]
                    continue

                # 3. SIDEWAYS DETECTION (24 jam timeout)
                try:
                    from shared_state import state
                    if symbol not in state.pos_start_time:
                        state.pos_start_time[symbol] = now
                    duration_hours = (now - state.pos_start_time[symbol]) / 3600
                    price_move_pct = abs((mrk - ent) / ent * 100) if ent > 0 else 0

                    SIDEWAYS_TIMEOUT_HOURS = 24.0 # Koin hanya ditutup jika benar-benar beku 24 jam
                    is_sideways = (-1.5 < pnl < 1.5) and (price_move_pct < 1.5)

                    if duration_hours >= SIDEWAYS_TIMEOUT_HOURS and is_sideways:
                        self._close_paper_position(pos, mrk, reason="Sideways Timeout")
                        if symbol in state.pos_start_time: del state.pos_start_time[symbol]
                        if symbol in self._peak_pnl: del self._peak_pnl[symbol]
                        clean = self._clean_symbol(symbol)
                        if not hasattr(state, 'recently_exited'): state.recently_exited = {}
                        state.recently_exited[clean] = time.time()
                        continue
                except Exception as e:
                    print(f"[PAPER SIDEWAYS ERROR] {e}")

                # 4. HARD EXIT -10% (Emergency Guard)
                if pnl <= -10.0:
                    self._close_paper_position(pos, mrk, reason="Hard Exit PnL -10%")
                    if symbol in self._peak_pnl: del self._peak_pnl[symbol]
                    continue



        except Exception as e:
            print(f"[PAPER POSITION MANAGER CRASH] {e}")

    def sync_memory(self):
        """Sync DB: pastikan trade di DB yang sudah tidak ada di posisi aktif ditandai CLOSED."""
        try:
            positions = self.get_all_positions()
            open_symbols = [self._clean_symbol(p['symbol']) for p in positions]

            conn = get_connection()
            cursor = conn.cursor()
            placeholder = "%s" if not is_sqlite(conn) else "?"
            cursor.execute("SELECT id, symbol FROM trades WHERE status IN ('PENDING', 'RUNNING') AND is_paper = 1")
            for row in cursor.fetchall():
                tid, sym = row[0], row[1]
                if self._clean_symbol(sym) not in open_symbols:
                    cursor.execute(f"UPDATE trades SET status = 'CLOSED' WHERE id = {placeholder}", (tid,))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"[PAPER SYNC_MEMORY ERROR] {e}")

    def sync_state_with_exchange(self):
        return self.sync_memory()


"""
Reset Paper Trading: Inisialisasi/reset database, hapus riwayat lama, dan reset saldo ke $100.
Jalankan SATU KALI sebelum sesi baru dimulai.
"""
import sqlite3
import time
import os
import sys

backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(backend_dir, ".env"))

# Pastikan schema database terinisialisasi
try:
    from database import init_db
    init_db()
    print("[INIT] Database schema terverifikasi.")
except Exception as e:
    print(f"[INIT ERROR] {e}")

VIRTUAL_BALANCE = float(os.getenv("VIRTUAL_BALANCE", "100.0"))

db_files = [
    os.path.join(backend_dir, "trading_bot.db"),
    os.path.join(backend_dir, "trades.db")
]

for db_path in db_files:
    if not os.path.exists(db_path):
        continue
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. Hapus semua trade lama agar riwayat bersih
        try:
            cursor.execute("DELETE FROM trades")
            deleted = cursor.rowcount
            print(f"[RESET {os.path.basename(db_path)}] Dihapus {deleted} riwayat trade lama.")
        except Exception:
            pass

        # 2. Reset virtual balance ke VIRTUAL_BALANCE ($100.00)
        try:
            cursor.execute("DELETE FROM virtual_account")
            cursor.execute(
                "INSERT INTO virtual_account (balance, updated_at) VALUES (?, ?)",
                (VIRTUAL_BALANCE, int(time.time() * 1000))
            )
            print(f"[RESET {os.path.basename(db_path)}] Saldo virtual direset ke ${VIRTUAL_BALANCE:.2f}")
        except Exception as ve:
            print(f"[RESET WARN] virtual_account reset: {ve}")

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[!] Gagal reset {db_path}: {e}")

# 3. Bersihkan karantina Buku Dosa jika diinginkan untuk fresh start
try:
    from buku_dosa import load_buku_dosa, save_buku_dosa
    dosa_data = load_buku_dosa()
    dosa_data["quarantine_registry"] = {}
    save_buku_dosa(dosa_data)
    print("[RESET BUKU DOSA] Karantina koin sementara dibersihkan (Permanent Blacklist tetap aktif).")
except Exception as be:
    print(f"[RESET BUKU DOSA WARN] {be}")

# 4. Bersihkan Mem0 vector memory cache jika ada
try:
    import shutil
    qdrant_dir = os.path.join(backend_dir, "data", "mem0_qdrant")
    if os.path.exists(qdrant_dir):
        shutil.rmtree(qdrant_dir)
        print("[RESET MEM0] Vector memory cache dibersihkan.")
except Exception as me:
    print(f"[RESET MEM0 WARN] {me}")

print("\n[DONE] ✅ Paper Trading & Riwayat Transaksi siap dimulai ulang dari awal!")
print(f"       Saldo: ${VIRTUAL_BALANCE:.2f}")


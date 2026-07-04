"""
Reset Paper Trading: Hapus SEMUA riwayat transaksi lama dan reset saldo ke $1000.
Jalankan SATU KALI sebelum sesi baru dimulai.
"""
import sqlite3
import time
import os

VIRTUAL_BALANCE = float(os.getenv("VIRTUAL_BALANCE", "1000"))

for db_path in ["trading_bot.db", "trades.db"]:
    if not os.path.exists(db_path):
        continue
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. Hapus semua trade lama (WIN/LOSS/PENDING/RUNNING) agar riwayat lama bersih
        cursor.execute("DELETE FROM trades")
        deleted = cursor.rowcount
        print(f"[RESET {db_path}] Dihapus {deleted} riwayat trade lama.")

        # 2. Reset virtual balance ke $1000
        try:
            cursor.execute("DELETE FROM virtual_account")
            cursor.execute(
                "INSERT INTO virtual_account (balance, updated_at) VALUES (?, ?)",
                (VIRTUAL_BALANCE, int(time.time() * 1000))
            )
            print(f"[RESET {db_path}] Saldo virtual direset ke ${VIRTUAL_BALANCE:.2f}")
        except Exception:
            pass

        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[!] Gagal reset {db_path}: {e}")

print("\n[DONE] Paper Trading & Riwayat Transaksi siap dimulai ulang dari awal!")
print(f"       Jalankan: pm2 restart crypto-bot")

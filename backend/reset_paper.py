"""
Reset Paper Trading: Hapus semua riwayat transaksi lama dan reset saldo ke $1000.
Jalankan SATU KALI sebelum sesi baru dimulai.
"""
import sqlite3
import time
import os

VIRTUAL_BALANCE = float(os.getenv("VIRTUAL_BALANCE", "1000"))

db_path = "trading_bot.db"
if not os.path.exists(db_path):
    print(f"[!] Database {db_path} tidak ditemukan.")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 1. Hapus semua trade paper (WIN/LOSS/PENDING/RUNNING)
cursor.execute("DELETE FROM trades WHERE is_paper = 1")
deleted = cursor.rowcount
print(f"[RESET] Dihapus {deleted} riwayat trade paper lama.")

# 2. Reset virtual balance ke $1000
cursor.execute("DELETE FROM virtual_account")
cursor.execute(
    "INSERT INTO virtual_account (balance, updated_at) VALUES (?, ?)",
    (VIRTUAL_BALANCE, int(time.time() * 1000))
)
print(f"[RESET] Saldo virtual direset ke ${VIRTUAL_BALANCE:.2f}")

conn.commit()
cursor.close()
conn.close()

print("\n[DONE] Paper Trading siap dimulai ulang dari awal!")
print(f"       Jalankan: pm2 restart crypto-bot")

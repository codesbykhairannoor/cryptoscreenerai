import os
import time
import subprocess

# SCRIPT SAKTI: BIAR VPS PINTAR KAYAK RAILWAY
# Script ini akan mengecek GitHub tiap 60 detik.
# Kalau saya (Antigravity) ada update kode, dia otomatis tarik & restart bot Anda.

def run_watcher():
    print("[WATCHER] Mesin Auto-Update AKTIF. Anda tidak perlu ngetik git pull lagi!")
    while True:
        try:
            # Cek apakah ada perubahan di GitHub
            subprocess.run(["git", "fetch"], check=True, capture_output=True)
            status = subprocess.run(["git", "status", "-uno"], capture_output=True, text=True).stdout
            
            if "Your branch is behind" in status:
                print("[WATCHER] Ada update baru dari Antigravity! Menarik kode...")
                subprocess.run(["git", "pull"], check=True)
                print("[WATCHER] Kode berhasil diperbarui. Merestart bot...")
                subprocess.run(["pm2", "restart", "MyTradingBot"], check=True)
                print("[WATCHER] Bot berhasil direstart dengan kode terbaru.")
            
        except Exception as e:
            print(f"[WATCHER ERROR] {e}")
            
        time.sleep(60) # Cek tiap 1 menit

if __name__ == "__main__":
    run_watcher()

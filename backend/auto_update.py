"""
AUTO-DEPLOY ENGINE v2.0 - Windows VPS Edition
===============================================
Otomatis tarik kode terbaru dari GitHub dan restart bot.
Cek setiap 60 detik. Tidak perlu git pull manual lagi.
"""
import os
import time
import subprocess
import sys

def find_pm2():
    """Cari path pm2 di Windows."""
    candidates = [
        "pm2",
        r"C:\Users\Administrator\AppData\Roaming\npm\pm2.cmd",
        r"C:\Program Files\nodejs\pm2.cmd",
        r"C:\Program Files (x86)\nodejs\pm2.cmd",
    ]
    for c in candidates:
        try:
            result = subprocess.run([c, "--version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return c
        except Exception:
            continue
    return "pm2"  # fallback

PM2 = find_pm2()

def run_watcher():
    # Tentukan working directory — folder dimana auto_update.py ini berada
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root  = os.path.dirname(script_dir)  # satu level di atas backend/

    # Kalau main.py ada di script_dir langsung (bukan subfolder), pakai script_dir
    if os.path.exists(os.path.join(script_dir, "main.py")):
        repo_root = script_dir

    print(f"[WATCHER] Auto-Deploy AKTIF. Repo: {repo_root}", flush=True)
    print(f"[WATCHER] PM2 path: {PM2}", flush=True)
    print(f"[WATCHER] Cek update setiap 60 detik...", flush=True)

    while True:
        try:
            # 1. Fetch dari GitHub
            subprocess.run(
                ["git", "fetch", "origin", "main"],
                cwd=repo_root, capture_output=True, timeout=30
            )

            # 2. Cek apakah lokal tertinggal dari remote
            status = subprocess.run(
                ["git", "status", "-uno"],
                cwd=repo_root, capture_output=True, text=True, timeout=10
            ).stdout

            if "Your branch is behind" in status or "can be fast-forwarded" in status:
                print(f"[WATCHER] Update ditemukan! Menarik kode terbaru...", flush=True)

                # 3. Pull
                pull = subprocess.run(
                    ["git", "pull", "origin", "main"],
                    cwd=repo_root, capture_output=True, text=True, timeout=60
                )
                print(f"[WATCHER] Git pull: {pull.stdout.strip()}", flush=True)

                # 4. Restart bot
                print(f"[WATCHER] Merestart MyTradingBot...", flush=True)
                subprocess.run([PM2, "restart", "MyTradingBot"], timeout=30)
                print(f"[WATCHER] Bot berhasil diperbarui dan direstart!", flush=True)
            else:
                # Tidak ada update — diam saja
                pass

        except subprocess.TimeoutExpired:
            print("[WATCHER] Timeout saat cek GitHub. Coba lagi 60 detik...", flush=True)
        except Exception as e:
            print(f"[WATCHER ERROR] {e}", flush=True)

        time.sleep(60)

if __name__ == "__main__":
    run_watcher()

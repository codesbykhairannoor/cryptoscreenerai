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
    # Tentukan working directory - folder dimana auto_update.py ini berada
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
            # 1. Fetch terbaru
            subprocess.run(["git", "fetch", "origin", "main"], cwd=repo_root, capture_output=True, timeout=30)

            # 2. Bandingkan Hash Local vs Remote (Cara paling akurat)
            local_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True).stdout.strip()
            remote_hash = subprocess.run(["git", "rev-parse", "origin/main"], cwd=repo_root, capture_output=True, text=True).stdout.strip()

            if local_hash != remote_hash:
                print(f"[WATCHER] Update ditemukan! {local_hash[:7]} -> {remote_hash[:7]}", flush=True)

                # 3. Pull
                pull = subprocess.run(
                    ["git", "pull", "origin", "main"],
                    cwd=repo_root, capture_output=True, text=True, timeout=60
                )

                # Cek apakah pull berhasil sebelum restart
                if pull.returncode != 0:
                    print(f"[WATCHER] Git pull GAGAL! Tidak restart.", flush=True)
                    print(f"[WATCHER] Error: {pull.stderr.strip()}", flush=True)
                    # Jangan restart - kode lama lebih baik dari kode rusak
                    time.sleep(60)
                    continue

                # Verifikasi hash setelah pull - pastikan benar-benar terupdate
                new_hash = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo_root, capture_output=True, text=True
                ).stdout.strip()

                if new_hash != remote_hash:
                    print(f"[WATCHER] Hash tidak cocok setelah pull. Abort restart.", flush=True)
                    time.sleep(60)
                    continue

                print(f"[WATCHER] Git pull sukses. Hash: {new_hash[:7]}", flush=True)

                # 4. Restart bot
                print(f"[WATCHER] Merestart MyTradingBot...", flush=True)
                restart_result = subprocess.run([PM2, "restart", "MyTradingBot"], timeout=30)
                if restart_result.returncode == 0:
                    print(f"[WATCHER] Bot berhasil diperbarui dan direstart!", flush=True)
                else:
                    print(f"[WATCHER] PM2 restart gagal (code {restart_result.returncode}).", flush=True)
            else:
                # Up to date
                pass

        except subprocess.TimeoutExpired:
            print("[WATCHER] Timeout saat cek GitHub. Coba lagi 60 detik...", flush=True)
        except Exception as e:
            print(f"[WATCHER ERROR] {e}", flush=True)

        time.sleep(60)

if __name__ == "__main__":
    run_watcher()




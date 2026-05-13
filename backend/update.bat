@echo off
echo [SYSTEM] Institutional Predator v26.17 - Persistence Mode
echo =========================================================

echo [1/4] Menghentikan semua proses lama...
pm2 delete all >nul 2>&1

echo [2/4] Mengambil kode terbaru (FORCE) dari GitHub...
git fetch origin
git reset --hard origin/main

echo [3/4] Menjalankan Mesin Predator...
pm2 start main.py --name "SmartPredator"

echo [4/4] Mengunci konfigurasi agar AUTO-RESTART saat laptop nyala...
pm2 save

echo.
echo [SUKSES] Bot telah diperbarui dan dikunci ke Startup Windows!
echo Menampilkan logs dalam 3 detik...
timeout /t 3
pm2 logs SmartPredator --lines 50

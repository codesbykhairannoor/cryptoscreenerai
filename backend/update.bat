@echo off
set VERSION=26.40
title Institutional Predator %VERSION% - Update Utility
echo [SYSTEM] Institutional Predator v%VERSION% - Persistence Mode
echo =========================================================
echo [1/4] Mengambil update terbaru dari GitHub...
git reset --hard origin/main
git pull origin main

echo [2/4] Membersihkan proses lama...
call pm2 delete all
call pm2 flush

echo [3/4] Menyalakan ulang mesin ForcePredator...
call pm2 start main.py --name "ForcePredator"

echo [4/4] Mengunci konfigurasi (Persistence Save)...
call pm2 save
call pm2 list

echo =========================================================
echo [DONE] Update selesai! Bot kembali berburu.
pause

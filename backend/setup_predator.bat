@echo off
title Predator Ultimate Setup
echo [SYSTEM] Memulai Setup Institusional Predator...
echo =================================================

echo [1/5] Sinkronisasi GitHub (Hard Reset)...
git fetch origin
git reset --hard origin/main

echo [2/5] Mengatur Persistensi Windows (Auto-Reboot)...
call npm install -g pm2-windows-startup
call pm2-startup install

echo [3/5] Membersihkan dan Menyalakan Bot...
call pm2 delete all
call pm2 flush
call pm2 start main.py --name "ForcePredator"

echo [4/5] Mengunci Konfigurasi PM2...
call pm2 save

echo [5/5] Selesai! Bot Aktif dan Tahan Reboot.
echo =================================================
call pm2 list
echo [INFO] Gunakan update.bat untuk update harian.
pause

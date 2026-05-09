# ============================================================
# AUTO UPDATE SCRIPT — CryptoScreener AI
# Jalankan sekali: Setup-AutoUpdate.ps1
# Script ini dicek setiap 5 menit oleh Windows Task Scheduler
# ============================================================

$BOT_DIR    = "C:\Users\Administrator\cryptoscreenerai\backend"
$LOG_FILE   = "C:\Users\Administrator\.pm2\logs\auto_update.log"
$PM2_NAME   = "MyTradingBot"

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts $msg" | Tee-Object -FilePath $LOG_FILE -Append
}

Set-Location $BOT_DIR

# 1. Fetch remote tanpa merge
git fetch origin main 2>&1 | Out-Null

# 2. Cek apakah ada commit baru
$LOCAL  = git rev-parse HEAD
$REMOTE = git rev-parse origin/main

if ($LOCAL -eq $REMOTE) {
    # Tidak ada update — diam saja (tidak log supaya tidak spam)
    exit 0
}

Write-Log "[AUTO-UPDATE] Update ditemukan! Local:$($LOCAL.Substring(0,7)) Remote:$($REMOTE.Substring(0,7))"

# 3. Pull update
$pullResult = git pull origin main 2>&1
Write-Log "[AUTO-UPDATE] git pull: $pullResult"

# 4. Kill port 8000 kalau masih dipakai
$pid8000 = (netstat -ano | Select-String ":8000.*LISTENING") -replace '.*\s(\d+)$','$1' | Select-Object -First 1
if ($pid8000 -and $pid8000 -match '^\d+$') {
    taskkill /PID $pid8000 /F 2>&1 | Out-Null
    Write-Log "[AUTO-UPDATE] Killed port 8000 (PID $pid8000)"
    Start-Sleep -Seconds 2
}

# 5. Restart PM2
pm2 restart $PM2_NAME 2>&1 | Out-Null
Write-Log "[AUTO-UPDATE] PM2 restarted: $PM2_NAME"
Write-Log "[AUTO-UPDATE] Done. Bot running latest version."

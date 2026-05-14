# ============================================================
# AUTO UPDATE SCRIPT - CryptoScreener AI
# Dicek setiap 5 menit oleh Windows Task Scheduler
# ============================================================

$BOT_DIR  = "C:\Users\Administrator\cryptoscreenerai\backend"
$LOG_FILE = "C:\Users\Administrator\.pm2\logs\auto_update.log"
$PM2_NAME = "MyTradingBot"

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
    exit 0  # Tidak ada update - diam
}

Write-Log "[AUTO-UPDATE] Update ditemukan! $($LOCAL.Substring(0,7)) -> $($REMOTE.Substring(0,7))"

# 3. Pull update
$pullResult = git pull origin main 2>&1
Write-Log "[AUTO-UPDATE] git pull: $pullResult"

# 4. Kill SEMUA proses Python (bersihkan instance lama)
$killed = 0
Get-Process -Name "python*" -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    $killed++
}
if ($killed -gt 0) {
    Write-Log "[AUTO-UPDATE] Killed $killed Python process(es)"
    Start-Sleep -Seconds 3
}

# 5. Kill port 8000 kalau masih dipakai
$portLine = netstat -ano | Select-String ":8000.*LISTENING" | Select-Object -First 1
if ($portLine) {
    $pid8000 = ($portLine -replace '.*\s(\d+)$','$1').Trim()
    if ($pid8000 -match '^\d+$') {
        taskkill /PID $pid8000 /F 2>&1 | Out-Null
        Write-Log "[AUTO-UPDATE] Killed port 8000 (PID $pid8000)"
        Start-Sleep -Seconds 2
    }
}

# 6. Restart PM2
pm2 restart $PM2_NAME 2>&1 | Out-Null
Write-Log "[AUTO-UPDATE] PM2 restarted. Bot running latest version."


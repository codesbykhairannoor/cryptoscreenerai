# ============================================================
# SETUP AUTO-UPDATE - Jalankan SEKALI sebagai Administrator
# Membuat Windows Task Scheduler yang cek GitHub setiap 5 menit
# ============================================================

$TASK_NAME  = "CryptoBot-AutoUpdate"
$SCRIPT     = "C:\Users\Administrator\cryptoscreenerai\backend\auto_update.ps1"
$LOG        = "C:\Users\Administrator\.pm2\logs\auto_update.log"

Write-Host "Setting up auto-update task..." -ForegroundColor Cyan

# Hapus task lama kalau ada
Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue

# Buat action: jalankan PowerShell script
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -NoProfile -ExecutionPolicy Bypass -File `"$SCRIPT`""

# Trigger: setiap 5 menit, mulai sekarang, selamanya
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -Once -At (Get-Date)

# Setting: jalankan sebagai SYSTEM, bahkan saat tidak login
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# Register task
Register-ScheduledTask `
    -TaskName $TASK_NAME `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Auto-update CryptoScreener AI bot from GitHub every 5 minutes" `
    -Force

Write-Host ""
Write-Host "Auto-update task created!" -ForegroundColor Green
Write-Host "  Task name : $TASK_NAME" -ForegroundColor White
Write-Host "  Interval  : Every 5 minutes" -ForegroundColor White
Write-Host "  Script    : $SCRIPT" -ForegroundColor White
Write-Host "  Log       : $LOG" -ForegroundColor White
Write-Host ""
Write-Host "To check status:" -ForegroundColor Yellow
Write-Host "  Get-ScheduledTask -TaskName '$TASK_NAME' | Select-Object State" -ForegroundColor White
Write-Host "  Get-Content '$LOG' -Tail 20" -ForegroundColor White
Write-Host ""
Write-Host "To remove auto-update:" -ForegroundColor Yellow
Write-Host "  Unregister-ScheduledTask -TaskName '$TASK_NAME' -Confirm:`$false" -ForegroundColor White


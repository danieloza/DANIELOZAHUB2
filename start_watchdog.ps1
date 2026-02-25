# Senior IT Watchdog for Danex Faktury Bot
$ErrorActionPreference = "Continue"

Write-Host "--- Starting Danex Faktury Bot Watchdog ---" -ForegroundColor Cyan

while ($true) {
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | Launching Bot..." -ForegroundColor Green
    
    # Run the bot and wait for exit
    & ".\.venv\Scripts\python.exe" -u bot.py
    
    $exitCode = $LASTEXITCODE
    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | Bot exited with code $exitCode" -ForegroundColor Yellow
    
    if ($exitCode -eq 0) {
        Write-Host "Bot stopped gracefully. Exiting watchdog." -ForegroundColor White
        break
    }
    
    Write-Host "Bot crashed or was killed. Restarting in 5 seconds..." -ForegroundColor Red
    Start-Sleep -Seconds 5
}

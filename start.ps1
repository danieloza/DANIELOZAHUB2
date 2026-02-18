# =========================
# Danex Faktury - START
# =========================

# Przejdź do folderu, w którym jest ten plik
Set-Location -Path $PSScriptRoot

# --- ustaw ENV tylko jeśli chcesz (albo trzymaj setx na stałe) ---
# $env:TELEGRAM_BOT_TOKEN="<PUT_NEW_TOKEN_HERE>"
# $env:DRIVE_FOLDER_ID="1GhY_zYgsKqYxigISlAaGGY12fV6InOi8"
# $env:SPREADSHEET_ID "1xDhM4nIZFnnXcvNKV0HnCeMZ9WiLeG73raaDCrnIy0k"
# $env:SHEET_NAME="Arkusz1"
# $env:GOOGLE_SERVICE_ACCOUNT_JSON="danex-faktury-bot.json"
# $env:TESSERACT_CMD="C:\Users\syfsy\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
# $env:ALLOWED_USER_IDS="1639287725,7941906792"
# $env:ENABLE_PANEL="1"
# $env:PANEL_PORT="8000"

Write-Host "✅ Startuję Danex Faktury..." -ForegroundColor Green

# Panel NIE jest potrzebny osobno, bo bot.py ma panel wbudowany.
# Jeśli jednak chcesz osobno:
# Start-Process -WindowStyle Hidden -FilePath "python" -ArgumentList "panel.py"

# Bot (tu zostaje okno z logami)
python bot.py

@echo off
chcp 65001 >nul
set PYTHONUTF8=1
setlocal
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
  echo [ERROR] Nie znaleziono %VENV_PY%
  echo Utworz venv: python -m venv .venv
  echo Zainstaluj zaleznosci: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

echo [INFO] Zatrzymuje stare instancje bot.py (jesli sa)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process ^| Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'danex-faktury-bot\\\\bot.py' } ^| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>nul

echo [INFO] Uzywam: %VENV_PY%
"%VENV_PY%" --version
if errorlevel 1 (
  echo [ERROR] Nie moge uruchomic interpretera z .venv
  pause
  exit /b 1
)

echo [INFO] Startuje bota...
"%VENV_PY%" bot.py
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
  echo [ERROR] Bot zakonczyl sie kodem: %EXITCODE%
) else (
  echo [INFO] Bot zakonczyl sie poprawnie.
)

pause
exit /b %EXITCODE%

@echo off
rem Starts the live testing server on port 8000 and opens the browser.
if not exist "%~dp0.venv\Scripts\python.exe" goto needsetup
start "Live testing (8000)" cmd /k "cd /d %~dp0 && .venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000"
timeout /t 4 >nul
start http://127.0.0.1:8000/
exit /b 0

:needsetup
echo Not set up yet. Run setup.bat first.
pause
exit /b 1

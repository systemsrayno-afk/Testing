@echo off
rem One-time setup: creates a virtual environment, installs packages, runs the tests.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 goto nopython
if not exist .venv python -m venv .venv
".venv\Scripts\python" -m pip install --upgrade pip -q
".venv\Scripts\python" -m pip install --upgrade -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python" -m pytest -q
echo.
echo Setup finished. Double-click start.bat to run.
pause
exit /b 0

:failed
echo Package install failed. Check your internet connection and try again.
pause
exit /b 1

:nopython
echo Python was not found.
echo Install Python 3.11 or newer from python.org and tick "Add python.exe to PATH", then run this again.
pause
exit /b 1

@echo off
rem Runs the no-browser paper-trading monitor. Optional: pass your own options, for example
rem   start_monitor.bat --symbols INFY,HDFCBANK --interval 15m --every 120 --auto-paper
if not exist "%~dp0.venv\Scripts\python.exe" goto needsetup
cd /d "%~dp0"
if "%~1"=="" goto defaults
".venv\Scripts\python" monitor.py %*
goto end

:defaults
".venv\Scripts\python" monitor.py --symbols RELIANCE,TCS --interval 5m --every 60 --auto-paper

:end
pause
exit /b 0

:needsetup
echo Not set up yet. Run setup.bat first.
pause
exit /b 1

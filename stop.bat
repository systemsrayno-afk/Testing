@echo off
rem Stops whatever is listening on port 8000.
for /f "tokens=5" %%I in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do taskkill /PID %%I /F >nul 2>nul
echo Server stopped.
timeout /t 2 >nul

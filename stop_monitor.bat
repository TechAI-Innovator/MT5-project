@echo off
REM Force-stop all MT5 Trade Monitor Python processes on this machine.
echo Stopping MT5 monitor processes...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq MT5*" 2>nul
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object { $_.CommandLine -match 'monitor\.main|run_monitor|MT5 project|mt5_monitor' } | ForEach-Object { Write-Host ('Killing PID ' + $_.ProcessId + ' ' + $_.CommandLine); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo Done. If Telegram still messages you, revoke the bot token in BotFather.
pause

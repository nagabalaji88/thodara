@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo Closing the internet link and stopping the demo (its data is kept)...
docker compose -p thodara-demo -f compose.yaml -f compose.demo.yaml --profile tunnel stop
echo Done. The demo address no longer works. Run start-demo.bat to start again (new address).
pause

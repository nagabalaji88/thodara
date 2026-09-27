@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo Stopping Thodara (your data is kept)...
docker compose stop
echo Done. Run start-thodara.bat to start it again.
pause

@echo off
setlocal EnableExtensions
title Thodara demo - reset
cd /d "%~dp0"
set "DC=docker compose -p thodara-demo -f compose.yaml -f compose.demo.yaml --profile tunnel"
echo.
echo This deletes everything in the DEMO database and loads the fictional company again,
echo with new passwords. Your trial install (start-thodara.bat) is not touched.
choice /c YN /m "Reset the demo now"
if errorlevel 2 exit /b 1
%DC% exec -T api /app/.venv/bin/thodara-api seed-demo --reset > demo-accounts.txt
if errorlevel 1 (
  type demo-accounts.txt
  echo [ERROR] The reset did not work. Is the demo running? Run start-demo.bat first.
  pause
  exit /b 1
)
echo Done. New accounts and passwords are in demo-accounts.txt.
start "" notepad "demo-accounts.txt"
pause

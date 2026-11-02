@echo off
setlocal EnableExtensions
title Thodara demo (internet)
cd /d "%~dp0"
set "DC=docker compose -p thodara-demo -f compose.yaml -f compose.demo.yaml"

echo.
echo  ======================================================
echo   Thodara DEMO - fictional data, reachable on the internet
echo   Never enter real customer, supplier or personal data.
echo  ======================================================
echo.

if not exist "compose.demo.yaml" (
  echo [ERROR] Put this file in the Thodara folder, next to compose.demo.yaml, and run it again.
  goto :fail
)
where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker Desktop is needed. Run start-thodara.bat once; it can install it.
  goto :fail
)
docker info >nul 2>&1
if not errorlevel 1 goto :docker_ready
echo Starting Docker Desktop...
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set /a tries=0
:wait_docker
timeout /t 3 /nobreak >nul
docker info >nul 2>&1
if not errorlevel 1 goto :docker_ready
set /a tries+=1
if %tries% lss 60 goto :wait_docker
echo [ERROR] Docker did not start within 3 minutes. Open Docker Desktop, wait until it is running, then try again.
goto :fail
:docker_ready
echo [ok] Docker is running.

rem ---- Settings: database password and the private two-step key ----------
if exist ".env" goto :env_exists
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')"`) do set "DBPASS=%%p"
if not defined DBPASS (
  echo [ERROR] Could not generate a password.
  goto :fail
)
(
  echo POSTGRES_DB=thodara
  echo POSTGRES_USER=thodara
  echo POSTGRES_PASSWORD=%DBPASS%
) > ".env"
set "DBPASS="
:env_exists
findstr /b /c:"THODARA_TWO_STEP_KEY=" ".env" >nul 2>&1
if not errorlevel 1 goto :env_ready
for /f "usebackq delims=" %%k in (`powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\demo-key.ps1"`) do set "TSKEY=%%k"
if not defined TSKEY (
  echo [ERROR] Could not generate the two-step key.
  goto :fail
)
>> ".env" echo THODARA_TWO_STEP_KEY=%TSKEY%
set "TSKEY="
:env_ready
echo [ok] Settings are in .env (keep this file).

rem ---- Build and start the demo (its own database, separate from start-thodara) --
echo Starting the demo database...
%DC% up -d --wait db
if errorlevel 1 goto :compose_fail
echo Updating the database schema...
%DC% run --rm --build migrate
if errorlevel 1 goto :compose_fail
echo Building and starting the app (the first run can take several minutes)...
%DC% up -d --build --wait api web
if errorlevel 1 goto :compose_fail

set "USERS="
for /f "usebackq delims=" %%c in (`%DC% exec -T db psql -U thodara -d thodara -tAc "select count(*) from users"`) do set "USERS=%%c"
if not "%USERS%"=="0" goto :tunnel
echo Loading the fictional demo company...
%DC% exec -T api /app/.venv/bin/thodara-api seed-demo > demo-accounts.txt
if errorlevel 1 (
  type demo-accounts.txt
  goto :compose_fail
)

:tunnel
echo Opening the internet link (free Cloudflare quick tunnel)...
%DC% up -d tunnel
if errorlevel 1 goto :compose_fail
set "DEMO_URL="
for /f "usebackq delims=" %%u in (`powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\demo-url.ps1"`) do set "DEMO_URL=%%u"
if not defined DEMO_URL (
  echo [ERROR] The tunnel did not report an address. Check your internet connection; its log:
  %DC% logs --tail 20 tunnel
  goto :fail
)
echo %DEMO_URL%| clip
echo.
echo  Demo address (copied; it changes each time the demo starts):
echo     %DEMO_URL%
echo.
echo  Sign-in accounts and passwords: demo-accounts.txt (this computer only)
echo  This computer can also use http://localhost:8090
echo  Keep this computer awake while you present. Run stop-demo.bat afterwards.
echo.
start "" "%DEMO_URL%"
start "" notepad "demo-accounts.txt"
pause
exit /b 0

:compose_fail
echo.
echo [ERROR] Something went wrong. The last lines of the log:
%DC% logs --tail 30 api web tunnel
:fail
echo.
pause
exit /b 1

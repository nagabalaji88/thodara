@echo off
setlocal EnableExtensions
title Thodara (local)
cd /d "%~dp0"

echo.
echo  ============================================
echo   Thodara - local setup and start
echo   For trying the app on this computer only.
echo  ============================================
echo.

if not exist "compose.yaml" (
  echo [ERROR] Put this file in the Thodara folder, next to compose.yaml, and run it again.
  goto :fail
)

rem ---- 1. Docker Desktop ---------------------------------------------------
where docker >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop is required but was not found.
  where winget >nul 2>&1
  if errorlevel 1 (
    echo Install it from https://www.docker.com/products/docker-desktop/ and run this file again.
    goto :fail
  )
  choice /c YN /m "Install Docker Desktop now with winget"
  if errorlevel 2 goto :fail
  winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
  echo.
  echo Docker Desktop was installed. Restart Windows if asked, start Docker Desktop once,
  echo accept its terms, then run this file again.
  goto :fail
)

docker compose version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Your Docker installation has no "docker compose". Update Docker Desktop and try again.
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
echo [ERROR] Docker did not start within 3 minutes. Open Docker Desktop, wait until it says "running", then run this file again.
goto :fail
:docker_ready
echo [ok] Docker is running.

rem ---- 2. Local settings (.env) --------------------------------------------
if exist ".env" goto :env_ready
echo Creating local settings with a random database password...
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')"`) do set "DBPASS=%%p"
if not defined DBPASS (
  echo [ERROR] Could not generate a password.
  goto :fail
)
(
  echo THODARA_APP_ENV=development
  echo THODARA_DATABASE_URL=postgresql+asyncpg://thodara:%DBPASS%@localhost:5432/thodara
  echo THODARA_ALLOWED_ORIGINS=["http://localhost:5173","http://localhost:8080"]
  echo THODARA_ALLOWED_HOSTS=["localhost","127.0.0.1","testserver"]
  echo THODARA_SESSION_TTL_HOURS=8
  echo THODARA_SESSION_COOKIE_SECURE=false
  echo POSTGRES_DB=thodara
  echo POSTGRES_USER=thodara
  echo POSTGRES_PASSWORD=%DBPASS%
) > ".env"
set "DBPASS="
:env_ready
echo [ok] Local settings are in .env (keep this file; the database password lives there).

rem ---- 3. Build and start --------------------------------------------------
echo.
echo Building and starting the database (the first run downloads images and can take several minutes)...
docker compose up -d --wait db
if errorlevel 1 goto :compose_fail

echo Updating the database schema...
docker compose run --rm --build migrate
if errorlevel 1 goto :compose_fail

echo Building and starting the app...
docker compose up -d --build --wait api web
if errorlevel 1 goto :compose_fail

set /a tries=0
:wait_web
curl.exe -sf http://localhost:8080/health/ready >nul 2>&1
if not errorlevel 1 goto :web_ready
set /a tries+=1
if %tries% geq 40 (
  echo [ERROR] The app did not answer on http://localhost:8080.
  goto :compose_fail
)
timeout /t 3 /nobreak >nul
goto :wait_web
:web_ready
echo [ok] The app is running.

rem ---- 4. First owner account ------------------------------------------------
set "USERS="
for /f "usebackq delims=" %%c in (`docker compose exec -T db psql -U thodara -d thodara -tAc "select count(*) from users"`) do set "USERS=%%c"
if not "%USERS%"=="0" goto :open_app

echo.
echo No account exists yet. Create the first owner account.
:ask_owner
set "OWNER_EMAIL="
set "OWNER_NAME="
set "OWNER_COMPANY="
set "OWNER_SITE="
set /p "OWNER_EMAIL=  Your work email: "
set /p "OWNER_NAME=  Your full name: "
set /p "OWNER_COMPANY=  Company name: "
set /p "OWNER_SITE=  Plant or site name (e.g. Main Plant): "
if not defined OWNER_EMAIL goto :ask_owner
if not defined OWNER_NAME goto :ask_owner
if not defined OWNER_COMPANY goto :ask_owner
if not defined OWNER_SITE goto :ask_owner
echo   Now choose a password (at least 14 characters). It will not be shown as you type.
docker compose exec api /app/.venv/bin/thodara-api provision-owner --email "%OWNER_EMAIL%" --name "%OWNER_NAME%" --tenant "%OWNER_COMPANY%" --site "%OWNER_SITE%"
if errorlevel 1 (
  echo   That did not work; see the message above. Let's try again.
  goto :ask_owner
)

rem ---- 5. Open the app -----------------------------------------------------
:open_app
echo.
echo Opening http://localhost:8080 ...
start "" http://localhost:8080
echo.
echo Thodara keeps running in the background. Run stop-thodara.bat to stop it.
echo.
pause
exit /b 0

:compose_fail
echo.
echo [ERROR] Something went wrong starting the app. The last lines of its log:
docker compose logs --tail 30 api web
:fail
echo.
pause
exit /b 1

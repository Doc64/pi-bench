@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  Pi Bench — build Windows installer
REM
REM  Output: dist\PiBenchSetup-<version>.exe
REM  Requirements: Inno Setup 6 or 7  — https://jrsoftware.org/isdl.php
REM ─────────────────────────────────────────────────────────────────────────────
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   Pi Bench Installer Builder
echo ============================================================
echo.

REM ── Read APP_VERSION from pi_bench.py ────────────────────────────────────
set VERSION=
for /f "tokens=3 delims= " %%v in ('findstr "APP_VERSION = " pi_bench.py') do set VERSION=%%v
set VERSION=%VERSION:"=%
if "%VERSION%"=="" (
    echo ERROR: Could not read APP_VERSION from pi_bench.py
    echo        Make sure pi_bench.py contains:  APP_VERSION = "x.y.z"
    if "%CI_APP_VERSION%"=="" pause
    exit /b 1
)
echo Version: %VERSION%
echo.

REM ── CI version override ───────────────────────────────────────────────────
if not "%CI_APP_VERSION%"=="" (
    set VERSION=%CI_APP_VERSION%
    echo Version overridden by CI: %VERSION%
    echo.
)

REM ── Find Inno Setup compiler ──────────────────────────────────────────────
REM
REM  IMPORTANT: Never use %ProgramFiles(x86)% in a bare "set VAR=..." or
REM  inside a "for %%p in (...)" loop.  CMD's batch parser sees the ) in
REM  (x86) as closing the statement before variable expansion runs, which
REM  gives "Files was unexpected at this time."
REM
REM  Fixes applied:
REM   1. On CI (CI_APP_VERSION is set), choco install innosetup puts
REM      ISCC.exe on PATH — skip all path detection and go straight there.
REM   2. For local builds, use hardcoded literal paths with set "VAR=value"
REM      syntax (quotes wrap the entire assignment, not just the path).
REM      This handles spaces and parens in paths without confusing CMD.
REM
set ISCC=

REM On CI, choco added ISCC.exe to PATH — skip local path search
if not "%CI_APP_VERSION%"=="" goto :ci_iscc

REM Local build: check standard install locations
if exist "C:\Program Files (x86)\Inno Setup 7\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
if exist "C:\Program Files\Inno Setup 7\ISCC.exe"       set "ISCC=C:\Program Files\Inno Setup 7\ISCC.exe"
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"       set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if exist "C:\Users\tom\AppData\Local\Programs\Inno Setup 7\ISCC.exe" set "ISCC=C:\Users\tom\AppData\Local\Programs\Inno Setup 7\ISCC.exe"
if not "%ISCC%"=="" goto :found_iscc

echo ERROR: Inno Setup 6 or 7 not found.
echo.
echo  1. Download from https://jrsoftware.org/isdl.php
echo  2. Install it  (default path, no special options needed)
echo  3. Re-run this script
echo.
pause & exit /b 1

:ci_iscc
set ISCC=ISCC.exe

:found_iscc
echo Using: %ISCC%
echo.

REM ── Ensure dist\ exists ───────────────────────────────────────────────────
if not exist dist mkdir dist

REM ── Compile ───────────────────────────────────────────────────────────────
echo Building PiBenchSetup-%VERSION%.exe ...
echo.
"%ISCC%" /DAppVersion=%VERSION% pi_bench_setup.iss
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Build failed.  See output above.
    if "%CI_APP_VERSION%"=="" pause
    exit /b 1
)

echo.
echo ============================================================
echo   Done!  dist\PiBenchSetup-%VERSION%.exe
echo ============================================================
echo.
if "%CI_APP_VERSION%"=="" pause

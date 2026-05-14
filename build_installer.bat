@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  Pi Bench — build Windows installer
REM
REM  Output: dist\PiBenchSetup-<version>.exe
REM  Requirements (local builds): Inno Setup 6 or 7  — https://jrsoftware.org/isdl.php
REM
REM  NOTE: This script deliberately avoids all  if (...) { block }  syntax.
REM  CMD's batch parser mis-handles parentheses in paths like %ProgramFiles(x86)%
REM  even inside quoted strings when they appear inside a block.  Every branch
REM  here uses a single-line IF + GOTO instead — this is the only safe pattern.
REM ─────────────────────────────────────────────────────────────────────────────
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   Pi Bench Installer Builder
echo ============================================================
echo.

REM ── In CI, CI_APP_VERSION is already set by the workflow — skip extraction ─
if not "%CI_APP_VERSION%"=="" goto :version_ready

REM ── Local build: read APP_VERSION from pi_bench.py ────────────────────────
set VERSION=
for /f "tokens=3 delims= " %%v in ('findstr "APP_VERSION = " pi_bench.py') do set VERSION=%%v
set VERSION=%VERSION:"=%
if not "%VERSION%"=="" goto :version_ok

echo ERROR: Could not read APP_VERSION from pi_bench.py
echo        Make sure pi_bench.py contains:  APP_VERSION = "x.y.z"
pause
exit /b 1

:version_ok
echo Version: %VERSION%
echo.
goto :find_iscc

:version_ready
set VERSION=%CI_APP_VERSION%
echo Version (from CI): %VERSION%
echo.
goto :ci_iscc

REM ── Local build: locate Inno Setup ───────────────────────────────────────
REM  Use  set "VAR=value"  (quotes around whole assignment) so CMD never sees
REM  the (x86) parens as block delimiters.
:find_iscc
set ISCC=
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
pause
exit /b 1

REM ── CI: choco put ISCC.exe on PATH ───────────────────────────────────────
:ci_iscc
set ISCC=ISCC.exe

:found_iscc
echo Using: %ISCC%
echo.

REM ── Ensure dist\ exists ──────────────────────────────────────────────────
if not exist dist mkdir dist

REM ── Compile ──────────────────────────────────────────────────────────────
echo Building PiBenchSetup-%VERSION%.exe ...
echo.
"%ISCC%" /DAppVersion=%VERSION% pi_bench_setup.iss
if %errorlevel% neq 0 goto :build_failed

echo.
echo ============================================================
echo   Done!  dist\PiBenchSetup-%VERSION%.exe
echo ============================================================
echo.
if "%CI_APP_VERSION%"=="" pause
exit /b 0

:build_failed
echo.
echo ERROR: Build failed.  See output above.
if "%CI_APP_VERSION%"=="" pause
exit /b 1

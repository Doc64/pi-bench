@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  Pi Bench — build Windows installer
REM
REM  Run this on your development machine.
REM  Output: dist\PiBenchSetup.exe  (copy this to your NAS)
REM
REM  Requirements:
REM    Inno Setup 6.x  — https://jrsoftware.org/isdl.php
REM    (free, 5 MB, install once on your dev machine)
REM ─────────────────────────────────────────────────────────────────────────────
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   Pi Bench Installer Builder
echo ============================================================
echo.

REM ── Find Inno Setup compiler ──────────────────────────────────────────────
set ISCC=
for %%p in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
) do (
    if exist %%p (
        set ISCC=%%p
    )
)

if "%ISCC%"=="" (
    echo ERROR: Inno Setup 6 not found.
    echo.
    echo  1. Download from https://jrsoftware.org/isdl.php
    echo  2. Install it  (default path, no special options needed)
    echo  3. Re-run this script
    echo.
    pause & exit /b 1
)

echo Using: %ISCC%
echo.

REM ── Ensure dist\ exists ───────────────────────────────────────────────────
if not exist dist mkdir dist

REM ── Compile ───────────────────────────────────────────────────────────────
echo Building PiBenchSetup.exe ...
echo.
%ISCC% pi_bench_setup.iss
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Build failed.  See output above.
    pause & exit /b 1
)

echo.
echo ============================================================
echo   Done!  Installer is at:  dist\PiBenchSetup.exe
echo
echo   Copy dist\PiBenchSetup.exe to your NAS.
echo   On any Windows PC:  run PiBenchSetup.exe to install.
echo   Uninstall:          Add / Remove Programs  ->  Pi Bench
echo ============================================================
echo.
pause

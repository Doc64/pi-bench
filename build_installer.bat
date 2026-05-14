@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  Pi Bench — build Windows installer
REM
REM  Run this on your development machine.
REM  Output: dist\PiBenchSetup-<version>.exe
REM
REM  Requirements:
REM    Inno Setup 6.x or 7.x  — https://jrsoftware.org/isdl.php
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
for /f "tokens=3 delims= " %%v in ('findstr /r "^APP_VERSION" pi_bench.py') do (
    set VERSION=%%v
)
REM Strip surrounding double-quotes
set VERSION=%VERSION:"=%
if "%VERSION%"=="" (
    echo ERROR: Could not read APP_VERSION from pi_bench.py
    echo        Make sure pi_bench.py contains:  APP_VERSION = "x.y.z"
    pause & exit /b 1
)
echo Version: %VERSION%
echo.

REM ── Allow CI to override the version via environment variable ─────────────
REM    (the GitHub Actions pipeline sets CI_APP_VERSION from the git tag)
if not "%CI_APP_VERSION%"=="" (
    set VERSION=%CI_APP_VERSION%
    echo Version overridden by CI: %VERSION%
    echo.
)

REM ── Find Inno Setup compiler ──────────────────────────────────────────────
REM
REM  NOTE: We intentionally do NOT use a "for %%p in (...)" loop here.
REM  %ProgramFiles(x86)% contains parentheses — the CMD batch parser
REM  misreads the ) in (x86) as closing the loop, causing "Files was
REM  unexpected at this time."  Pre-assign to plain variable names first.
REM
set _PF86=%ProgramFiles(x86)%
set _PF64=%ProgramFiles%
set ISCC=

if exist "%_PF86%\Inno Setup 7\ISCC.exe" set ISCC="%_PF86%\Inno Setup 7\ISCC.exe"
if exist "%_PF64%\Inno Setup 7\ISCC.exe" set ISCC="%_PF64%\Inno Setup 7\ISCC.exe"
if exist "%_PF86%\Inno Setup 6\ISCC.exe" set ISCC="%_PF86%\Inno Setup 6\ISCC.exe"
if exist "%_PF64%\Inno Setup 6\ISCC.exe" set ISCC="%_PF64%\Inno Setup 6\ISCC.exe"
if exist "C:\Users\tom\AppData\Local\Programs\Inno Setup 7\ISCC.exe" set ISCC="C:\Users\tom\AppData\Local\Programs\Inno Setup 7\ISCC.exe"

REM On CI (after choco install innosetup), ISCC.exe is on PATH as a shim
if "%ISCC%"=="" (
    where ISCC.exe >nul 2>&1
    if not errorlevel 1 set ISCC=ISCC.exe
)

if "%ISCC%"=="" (
    echo ERROR: Inno Setup 6 or 7 not found.
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

REM ── Compile — pass version as a define ───────────────────────────────────
echo Building PiBenchSetup-%VERSION%.exe ...
echo.
%ISCC% /DAppVersion=%VERSION% pi_bench_setup.iss
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Build failed.  See output above.
    pause & exit /b 1
)

echo.
echo ============================================================
echo   Done!  Installer is at:  dist\PiBenchSetup-%VERSION%.exe
echo.
echo   To release this version:
echo     git tag v%VERSION%
echo     git push --tags
echo     git push github --tags
echo   The CI pipeline will build and publish the release.
echo ============================================================
echo.
pause

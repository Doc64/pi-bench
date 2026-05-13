@echo off
REM ============================================================
REM  Pi Bench — zero-prerequisite Windows setup
REM
REM  Drop this folder anywhere, double-click setup.bat.
REM  No Python, no admin, no prerequisites required.
REM  (LHM sensor access will ask for admin on first run —
REM   that is a Windows kernel-driver requirement, not ours.)
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   Pi Bench Setup
echo ============================================================
echo.

REM ── Managed Python location ──────────────────────────────────
set PY_VER=3.12.8
set PY_DIR=%~dp0python
set PY_EXE=%PY_DIR%\python.exe

REM ── Step 1: Ensure Python + pip are available ────────────────
if exist "%PY_EXE%" (
    REM Python exists — check whether pip is also working.
    "%PY_EXE%" -m pip --version >nul 2>&1
    if not errorlevel 1 (
        echo [1/4] Python + pip ready  ^(embedded %PY_VER%^)
        goto :step2
    )
    REM python.exe is here but pip is missing — re-bootstrap pip only.
    echo [1/4] Python found but pip missing — re-bootstrapping pip ...
    goto :bootstrap_pip
)

echo [1/4] Python not found — downloading Python %PY_VER% embeddable  ^(^~26 MB^)
echo       This installs inside this folder.  No admin required.
echo.

set PY_URL=https://www.python.org/ftp/python/%PY_VER%/python-%PY_VER%-embed-amd64.zip
set PY_ZIP=%~dp0_py_embed.zip

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { (New-Object Net.WebClient).DownloadFile('%PY_URL%','%PY_ZIP%'); exit 0 } catch { Write-Error $_; exit 1 }"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Could not download Python.  Check internet connection.
    echo        Or install Python 3.12 from https://python.org and re-run.
    echo.
    pause & exit /b 1
)

echo       Extracting ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -Path '%PY_ZIP%' -DestinationPath '%PY_DIR%' -Force"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to extract Python.  Delete _py_embed.zip and try again.
    echo.
    pause & exit /b 1
)
del "%PY_ZIP%" 2>nul

REM Enable site-packages — required for pip and all installed packages.
REM The embeddable zip ships with "import site" commented out in the ._pth file.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$f=Get-ChildItem '%PY_DIR%' -Filter 'python3*._pth'|Select-Object -First 1; if($f){$c=(Get-Content $f.FullName) -replace '#import site','import site'; Set-Content $f.FullName $c; Write-Host '      site-packages enabled'} else {Write-Host 'WARNING: ._pth not found — pip may not work'}"

:bootstrap_pip
REM Bootstrap pip using PowerShell (handles HTTPS even before pip is installed).
echo       Bootstrapping pip ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://bootstrap.pypa.io/get-pip.py','%~dp0_get_pip.py')"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Could not download pip bootstrap.  Check internet connection.
    echo.
    pause & exit /b 1
)
"%PY_EXE%" "%~dp0_get_pip.py" --quiet
if %errorlevel% neq 0 (
    echo.
    echo ERROR: pip bootstrap failed.  Try deleting the python\ folder and re-running.
    echo.
    del "%~dp0_get_pip.py" 2>nul
    pause & exit /b 1
)
del "%~dp0_get_pip.py" 2>nul
echo       Python %PY_VER% + pip ready.
echo.

:step2
REM ── Steps 2-4 delegated to install.py ────────────────────────
echo [2-4/4] Installing packages and creating launchers ...
echo         ^(gpt4all is ~114 MB and may take a few minutes^)
echo.
"%PY_EXE%" "%~dp0install.py" %*
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Package installation failed.  See output above.
    echo.
    pause & exit /b 1
)

echo.
echo ============================================================
echo   Setup complete!
echo.
echo   run.bat         open Pi Bench
echo   run_dev.bat     open Pi Bench ^(dev build^)
echo   run_llm.bat     open Pi Bench + AI analysis
echo   uninstall.bat   remove everything
echo ============================================================
echo.
pause
exit /b 0

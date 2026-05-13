@echo off
REM _setup_python.bat - Pi Bench Python runtime bootstrap
REM Called by the Inno Setup installer before package installation.
REM Run with WorkingDir set to the app directory (no arguments needed).
setlocal

set "APPDIR=%~dp0"
if "%APPDIR:~-1%"=="\" set "APPDIR=%APPDIR:~0,-1%"
set "PYDIR=%APPDIR%\python"
set "PYEXE=%PYDIR%\python.exe"
set "PYZIP=%APPDIR%\_py_embed.zip"
set "PYVER=3.12.8"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-embed-amd64.zip"

if exist "%PYEXE%" goto :bootstrap_pip

echo Downloading Python %PYVER% embeddable (~26 MB)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('%PYURL%','%PYZIP%')"
if %errorlevel% neq 0 ( echo ERROR: Python download failed & exit /b 1 )

echo Extracting...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '%PYZIP%' -DestinationPath '%PYDIR%' -Force"
if %errorlevel% neq 0 ( echo ERROR: Extract failed & exit /b 1 )
del "%PYZIP%" 2>nul

echo Enabling site-packages...
for %%f in ("%PYDIR%\python3*._pth") do (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "(Get-Content '%%f') -replace '#import site','import site' | Set-Content '%%f'"
)

:bootstrap_pip
"%PYEXE%" -m pip --version >nul 2>&1
if %errorlevel% equ 0 ( echo pip already present & goto :done )

echo Bootstrapping pip...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://bootstrap.pypa.io/get-pip.py','%APPDIR%\_get_pip.py')"
if %errorlevel% neq 0 ( echo ERROR: get-pip download failed & exit /b 1 )
"%PYEXE%" "%APPDIR%\_get_pip.py" --quiet
if %errorlevel% neq 0 ( echo ERROR: pip bootstrap failed & exit /b 1 )
del "%APPDIR%\_get_pip.py" 2>nul
echo pip ready.

:done
echo Python runtime setup complete.
exit /b 0

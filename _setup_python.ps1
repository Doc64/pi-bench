# _setup_python.ps1 - Pi Bench Python runtime bootstrap
# Called by the Inno Setup installer before package installation.
# Usage:  powershell -File _setup_python.ps1 "<AppDir>"
param([string]$AppDir)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$PyVer = '3.12.8'
$PyUrl = "https://www.python.org/ftp/python/$PyVer/python-$PyVer-embed-amd64.zip"
$PyDir = Join-Path $AppDir 'python'
$PyExe = Join-Path $PyDir  'python.exe'
$PyZip = Join-Path $AppDir '_py_embed.zip'

# 1. Download + extract Python
if (-not (Test-Path $PyExe)) {
    Write-Host "Downloading Python $PyVer embeddable (~26 MB)..."
    (New-Object Net.WebClient).DownloadFile($PyUrl, $PyZip)

    Write-Host "Extracting..."
    Expand-Archive -Path $PyZip -DestinationPath $PyDir -Force
    Remove-Item $PyZip -ErrorAction SilentlyContinue

    # Enable site-packages - commented out by default in the embeddable zip's ._pth
    $Pth = Get-ChildItem $PyDir -Filter 'python3*._pth' | Select-Object -First 1
    if ($Pth) {
        (Get-Content $Pth.FullName) -replace '#import site', 'import site' |
            Set-Content $Pth.FullName
        Write-Host "site-packages enabled."
    } else {
        Write-Warning "._pth file not found - pip may not work correctly."
    }
} else {
    Write-Host "Python runtime already present - skipping download."
}

# 2. Bootstrap pip if missing
$null = & $PyExe -m pip --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Bootstrapping pip..."
    $GetPip = Join-Path $AppDir '_get_pip.py'
    (New-Object Net.WebClient).DownloadFile('https://bootstrap.pypa.io/get-pip.py', $GetPip)
    & $PyExe $GetPip --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "pip bootstrap failed - check internet connection."
    }
    Remove-Item $GetPip -ErrorAction SilentlyContinue
    Write-Host "pip ready."
} else {
    Write-Host "pip already present."
}

Write-Host "Python runtime setup complete."

# Build the Windows app and its installer. Run from the repository folder in PowerShell:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# Needs Python 3.11+ and Inno Setup 6 (https://jrsoftware.org/isinfo.php).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot)

python -m venv .build-venv
.\.build-venv\Scripts\python -m pip install --upgrade pip
.\.build-venv\Scripts\python -m pip install ".[app]" pyinstaller
.\.build-venv\Scripts\pyinstaller --noconfirm --distpath dist --workpath build packaging\omr.spec

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Host "The app is in dist\OMR (run OMR.exe). Install Inno Setup 6 to also make the installer."
    exit 0
}
$env:OMR_VERSION = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
& $iscc packaging\omr.iss
Write-Host "Installer: dist\OMR-Setup-$env:OMR_VERSION.exe"

# Build the Windows app, its installer and a portable zip. Run from the repository folder in PowerShell:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# Needs Python 3.11+ and Inno Setup 6.3 or newer (https://jrsoftware.org/isinfo.php).
#
# To code-sign (see packaging/README.md), set these first; without them nothing is signed:
#   $env:OMR_SIGN_CERT = "C:\path\to\certificate.pfx"   # or the certificate's SHA-1 thumbprint in the store
#   $env:OMR_SIGN_PASSWORD = "..."                      # only for a .pfx file
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot)

python -m venv .build-venv
.\.build-venv\Scripts\python -m pip install --upgrade pip
.\.build-venv\Scripts\python -m pip install ".[app]" pyinstaller
.\.build-venv\Scripts\pyinstaller --noconfirm --distpath dist --workpath build packaging\omr.spec
.\.build-venv\Scripts\python packaging\make_wizard_images.py
$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value

# Signing: the app first, so the installer and the portable zip both carry the signed OMR.exe.
$sign = $null
if ($env:OMR_SIGN_CERT) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" |
                Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signtool) { throw "OMR_SIGN_CERT is set but signtool.exe (Windows SDK) wasn't found." }
    $how = if (Test-Path $env:OMR_SIGN_CERT) { "/f `"$env:OMR_SIGN_CERT`" /p `"$env:OMR_SIGN_PASSWORD`"" }
           else { "/sha1 $env:OMR_SIGN_CERT" }
    $sign = "`"$($signtool.FullName)`" sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 $how"
    cmd /c "$sign `"dist\OMR\OMR.exe`""
    if ($LASTEXITCODE) { throw "Signing OMR.exe failed." }
}

# Portable copy: the same app with portable.txt beside it, so exams and settings stay in its data folder.
$portable = "dist\OMR-Portable-$version"
Remove-Item $portable, "$portable.zip" -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item dist\OMR $portable -Recurse
Set-Content "$portable\portable.txt" ("This copy keeps exams, scans and settings in the data folder next to it.",
                                      "Delete this file to use %LOCALAPPDATA%\OMR like the installed app.")
Compress-Archive -Path $portable -DestinationPath "$portable.zip"
Remove-Item $portable -Recurse -Force
Write-Host "Portable zip: $portable.zip"

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Host "The app is in dist\OMR (run OMR.exe). Install Inno Setup 6.3+ to also make the installer."
    exit 0
}
$env:OMR_VERSION = $version
if ($sign) {
    & $iscc /DSIGN "/Somrsign=$sign `$f" packaging\omr.iss
} else {
    & $iscc packaging\omr.iss
}
if ($LASTEXITCODE) { throw "Inno Setup failed." }
Write-Host "Installer: dist\OMR-Setup-$version.exe"

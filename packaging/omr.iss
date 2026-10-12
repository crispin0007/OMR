; Inno Setup script for the Windows installer: build the app first (packaging/build.ps1 does both).
; The installer only copies the app. Exams, scans and templates live in %LOCALAPPDATA%\OMR and are
; kept when the app is updated or uninstalled.

#define Version GetEnv("OMR_VERSION")
#if Version == ""
  #define Version "0.1.0"
#endif

[Setup]
AppId={{6B0D5A55-2C1E-4C8E-9C1B-0F6E4B7C2A31}
AppName=OMR
AppVersion={#Version}
AppPublisher=OMR contributors
DefaultDirName={autopf}\OMR
DefaultGroupName=OMR
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=OMR-Setup-{#Version}
SetupIconFile=omr.ico
UninstallDisplayIcon={app}\OMR.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\OMR\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\OMR"; Filename: "{app}\OMR.exe"
Name: "{autodesktop}\OMR"; Filename: "{app}\OMR.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OMR.exe"; Description: "Open OMR now"; Flags: nowait postinstall skipifsilent

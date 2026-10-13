; Inno Setup script for the Windows installer; packaging/build.ps1 builds the app, draws the wizard images
; and runs this. The installer only copies the app. Exams, scans, templates and settings live in
; %LOCALAPPDATA%\OMR and %APPDATA%\OMR: updating keeps them, and uninstalling asks before deleting them.

#define Version GetEnv("OMR_VERSION")
#if Version == ""
  #define Version "0.1.0"
#endif
#define W "..\build\wizard\"

[Setup]
; The same AppId on every version, so a new installer updates the installed app in place.
AppId={{6B0D5A55-2C1E-4C8E-9C1B-0F6E4B7C2A31}
AppName=OMR Checker
AppVersion={#Version}
AppVerName=OMR Checker {#Version}
AppPublisher=OMR Checker project
AppPublisherURL=https://github.com/crispin0007/omr
AppSupportURL=https://github.com/crispin0007/omr/issues
AppUpdatesURL=https://github.com/crispin0007/omr/releases
AppCopyright=Apache License 2.0
VersionInfoVersion={#Version}
VersionInfoProductName=OMR Checker
VersionInfoDescription=OMR Checker Setup
DefaultDirName={autopf}\OMR
DefaultGroupName=OMR Checker
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=OMR-Setup-{#Version}
SetupIconFile=omr.ico
UninstallDisplayIcon={app}\OMR.exe
UninstallDisplayName=OMR Checker
LicenseFile=..\LICENSE
WizardStyle=modern
WizardImageFile={#W}panel-100.bmp,{#W}panel-125.bmp,{#W}panel-150.bmp,{#W}panel-175.bmp,{#W}panel-200.bmp,{#W}panel-225.bmp,{#W}panel-250.bmp
WizardSmallImageFile={#W}corner-100.bmp,{#W}corner-125.bmp,{#W}corner-150.bmp,{#W}corner-175.bmp,{#W}corner-200.bmp,{#W}corner-225.bmp,{#W}corner-250.bmp
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Close a running OMR Checker before replacing its files.
CloseApplications=yes
RestartApplications=no
#ifdef SIGN
; build.ps1 defines SIGN and the omrsign tool when a code-signing certificate is given.
SignTool=omrsign
SignedUninstaller=yes
#endif

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nOMR Checker makes OMR answer sheets, reads them from your scanner and gives marks, ranks and merit lists, all offline.%n%nIf you are updating, your exams and settings are kept.

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\OMR\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[InstallDelete]
; Files of the previous version that this one no longer has (PyInstaller renames libraries between builds).
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\OMR Checker"; Filename: "{app}\OMR.exe"
Name: "{group}\Uninstall OMR Checker"; Filename: "{uninstallexe}"
Name: "{autodesktop}\OMR Checker"; Filename: "{app}\OMR.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OMR.exe"; Description: "Start OMR Checker now"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // Exams are kept unless the person removing the app says otherwise; a silent uninstall never deletes them.
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    if MsgBox('Also delete your exams, scanned sheets, templates and settings?' #13#10#13#10 +
              'Choose No to keep them for when you install OMR Checker again. ' +
              'Choose Yes only if you have a backup or no longer need them.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DelTree(ExpandConstant('{localappdata}\OMR'), True, True, True);
      DelTree(ExpandConstant('{userappdata}\OMR'), True, True, True);
    end;
end;

; Inno Setup script for the DeskMate installer.
;   1. pyinstaller packaging\deskmate.spec        (makes dist\DeskMate\)
;   2. iscc /DAppVersion=0.3.0 packaging\installer.iss   (makes dist\DeskMate-Setup-0.3.0.exe)
;
; Installs for the current user only (no admin prompt) into %LOCALAPPDATA%\Programs\DeskMate.
; Settings, chat history and the API key live in %APPDATA%\DeskMate and are kept on uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: Windows uses it to recognise upgrades of the same app.
AppId={{2900DCE3-BB01-4B9D-AF75-0EDB1C655EEF}
AppName=DeskMate
AppVersion={#AppVersion}
AppVerName=DeskMate {#AppVersion}
AppPublisher=MuizKmz
AppPublisherURL=https://github.com/MuizKmz/deskmate
AppSupportURL=https://github.com/MuizKmz/deskmate/issues
AppUpdatesURL=https://github.com/MuizKmz/deskmate/releases
DefaultDirName={autopf}\DeskMate
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=..\dist
OutputBaseFilename=DeskMate-Setup-{#AppVersion}
SetupIconFile=deskmate.ico
UninstallDisplayIcon={app}\DeskMate.exe
UninstallDisplayName=DeskMate
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Close a running DeskMate before replacing its files (and start it again afterwards).
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Start DeskMate when I sign in to Windows"; GroupDescription: "Startup:"

[InstallDelete]
; An upgrade replaces the whole _internal folder, so no old files are left behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\DeskMate\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\DeskMate"; Filename: "{app}\DeskMate.exe"
Name: "{autodesktop}\DeskMate"; Filename: "{app}\DeskMate.exe"; Tasks: desktopicon

[Registry]
; Same entry DeskMate's own "Start with Windows" menu option uses.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DeskMate"; ValueData: """{app}\DeskMate.exe"""; Tasks: autostart

[Run]
Filename: "{app}\DeskMate.exe"; Description: "{cm:LaunchProgram,DeskMate}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/im DeskMate.exe /f"; Flags: runhidden; RunOnceId: "StopDeskMate"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command: String;
begin
  { Remove "Start with Windows", however it was switched on, if it points at this copy. }
  if CurUninstallStep = usPostUninstall then
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DeskMate', Command) then
      if Pos(Lowercase(ExpandConstant('{app}')), Lowercase(Command)) > 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DeskMate');
end;

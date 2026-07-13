; pomski_installer.iss — Inno Setup script for POMSKI
;
; Prerequisites:
;   1. Install Inno Setup 6:  https://jrsoftware.org/isdl.php
;   2. Run both PyInstaller builds first:
;        pyinstaller aalink_bridge.spec
;        pyinstaller pomski.spec -y
;   3. Compile this script:
;        iscc pomski_installer.iss
;      or open it in the Inno Setup IDE and press Ctrl+F9.
;
; Output: Output\POMSKI_Setup.exe

#define AppName      "POMSKI"
#define AppVersion   "1.0.2"
#define AppPublisher "ThinkInSound"
#define AppURL       "https://github.com/ThinkInSound/POMSKI"
#define AppExeName   "POMSKI.exe"
#define SourceDir    "dist\POMSKI"

[Setup]
AppId={{A7F3C2D1-4B8E-4F2A-9C6D-1E5B7A3F8D2C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

; Install to Program Files
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; Installer output
OutputDir=Output
OutputBaseFilename=POMSKI_Setup
SetupIconFile=favicon.ico

; Compression
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Require Windows 10 or later (64-bit)
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; UI
WizardStyle=modern
WizardResizable=yes
DisableWelcomePage=no
LicenseFile=

; Uninstaller
UninstallDisplayIcon={app}\favicon.ico
UninstallDisplayName={#AppName}

; Admin required to write to Program Files
PrivilegesRequired=admin
UsedUserAreasWarning=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "favicon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\favicon.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\favicon.ico"; Tasks: desktopicon

[Registry]
; Tell Explorer to use favicon.ico for POMSKI.exe — bypasses the icon cache
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\DefaultIcon"; ValueType: string; ValueData: "{app}\favicon.ico,0"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent

[Code]
procedure SHChangeNotify(wEventId: DWORD; uFlags: UINT; dwItem1: DWORD; dwItem2: DWORD);
  external 'SHChangeNotify@shell32.dll stdcall';

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SHChangeNotify($8000000, 0, 0, 0);  // SHCNE_ASSOCCHANGED — forces shell to refresh all icon caches
end;

[UninstallDelete]
; Clean up log files written to %LOCALAPPDATA%\POMSKI at runtime
Type: files;    Name: "{localappdata}\POMSKI\pomski.log"
Type: files;    Name: "{localappdata}\POMSKI\fault.log"
Type: files;    Name: "{localappdata}\POMSKI\crash.log"
Type: dirifempty; Name: "{localappdata}\POMSKI"

; Icon file installed alongside the exe
Type: files; Name: "{app}\favicon.ico"

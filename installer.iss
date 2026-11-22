; Inno Setup Script for Gilgarips PrintOps Desktop Application
; Generates a clean, user-friendly per-user installer that installs into %LOCALAPPDATA%\Programs\Gilgarips PrintOps

#define MyAppName "Gilgarips PrintOps"
#define MyAppPublisher "Gilgarips 3D Studio"
#define MyAppURL "https://github.com/joeripari-lab/gilgarips-printops"
#define MyAppExeName "GilgaripsPrintOps.exe"

#ifndef MyAppVersion
#define MyAppVersion "2.5.0"
#endif

[Setup]
; Unique AppId so updates cleanly overwrite and register in Windows Add/Remove Programs
AppId={{5D874136-E93C-4C67-B9B2-3029D8E6F52A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={userpf}\{#MyAppName}
DisableProgramGroupPage=yes
; Per-user install: avoids UAC privilege elevation issues and writes to %LOCALAPPDATA%\Programs
PrivilegesRequired=lowest
OutputDir=dist-installer
OutputBaseFilename=GilgaripsPrintOps-Setup
SetupIconFile=assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Copy all binaries and assets from the PyInstaller folder output
Source: "dist\GilgaripsPrintOps\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Run application upon installer completion (and allow silent /SILENT /VERYSILENT for auto-updates)
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

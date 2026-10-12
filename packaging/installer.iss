#define AppVersion "0.7.0"
[Setup]
AppId={{D1A0230F-3B06-4BD1-9FE4-FAEED7DD4759}
AppName=Codex Mission Control
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\CodexMissionControl
DefaultGroupName=Codex Mission Control
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
DisableProgramGroupPage=yes
DisableDirPage=no
OutputDir=..\dist
OutputBaseFilename=MissionControl-Setup-{#AppVersion}-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\MissionControl.exe
CloseApplications=yes
RestartApplications=no
SetupMutex=CodexMissionControlSetup
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: unchecked
[Files]
Source: "..\dist\MissionControl\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userprograms}\Codex Mission Control"; Filename: "{app}\MissionControl.exe"
Name: "{userdesktop}\Codex Mission Control"; Filename: "{app}\MissionControl.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\MissionControl.exe"; Description: "Открыть Mission Control"; Flags: nowait postinstall skipifsilent
; No UninstallDelete section: user data and project files are never removed.

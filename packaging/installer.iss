#ifndef AppVersion
  #define AppVersion "0.7.1"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\dist\MissionControl"
#endif
[Setup]
#ifdef QaInstall
; Isolated lifecycle QA uses the same payload with a separate registration identity.
AppId=CodexMissionControlStage15QA
AppName=Codex Mission Control QA
#else
AppId={{D1A0230F-3B06-4BD1-9FE4-FAEED7DD4759}
AppName=Codex Mission Control
#endif
AppVersion={#AppVersion}
#ifdef QaInstall
DefaultDirName={localappdata}\Programs\CodexMissionControlStage15QA
DefaultGroupName=Codex Mission Control Stage 15 QA
#else
DefaultDirName={localappdata}\Programs\CodexMissionControl
DefaultGroupName=Codex Mission Control
#endif
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
LicenseFile=INSTALLER_LICENSE.txt
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; Flags: unchecked
[CustomMessages]
russian.DesktopIcon=Создать ярлык на рабочем столе
english.DesktopIcon=Create a desktop shortcut
russian.OpenApp=Открыть Mission Control
english.OpenApp=Open Mission Control
[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs notimestamp
[InstallDelete]
; Retired application-owned runtime files only; never user state or projects.
Type: files; Name: "{app}\_internal\PySide6\opengl32sw.dll"
Type: files; Name: "{app}\_internal\PySide6\plugins\imageformats\qgif.dll"
Type: files; Name: "{app}\_internal\PySide6\plugins\imageformats\qicns.dll"
Type: files; Name: "{app}\_internal\PySide6\plugins\imageformats\qico.dll"
Type: files; Name: "{app}\_internal\PySide6\plugins\imageformats\qjpeg.dll"
Type: files; Name: "{app}\_internal\PySide6\plugins\imageformats\qtga.dll"
Type: files; Name: "{app}\_internal\PySide6\plugins\imageformats\qtiff.dll"
Type: files; Name: "{app}\_internal\PySide6\plugins\imageformats\qwbmp.dll"
Type: files; Name: "{app}\_internal\PySide6\plugins\imageformats\qwebp.dll"
[Icons]
#ifndef QaInstall
Name: "{userprograms}\Codex Mission Control"; Filename: "{app}\MissionControl.exe"
Name: "{userdesktop}\Codex Mission Control"; Filename: "{app}\MissionControl.exe"; Tasks: desktopicon
#endif
[Run]
Filename: "{app}\MissionControl.exe"; Description: "{cm:OpenApp}"; Flags: nowait postinstall skipifsilent
; No UninstallDelete section: user data and project files are never removed.

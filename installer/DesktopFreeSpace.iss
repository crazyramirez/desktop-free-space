; Instalador de Windows de Desktop Free Space (Inno Setup 6).
; Lo compila GitHub Actions:  iscc /DMyAppVersion=X.Y.Z /DSourceDir=..\dist\DesktopFreeSpace installer\DesktopFreeSpace.iss
; Instala por usuario (sin pedir administrador) en %LOCALAPPDATA%\Programs\Desktop Free Space.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\DesktopFreeSpace"
#endif
#define MyAppName "Desktop Free Space"
#define MyAppExe "DesktopFreeSpace.exe"

[Setup]
AppId={{987D6724-D688-412D-9F51-5B2C68EE338B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=crazyramirez
AppPublisherURL=https://github.com/crazyramirez/desktop-free-space
AppSupportURL=https://github.com/crazyramirez/desktop-free-space/issues
AppUpdatesURL=https://github.com/crazyramirez/desktop-free-space/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\out
OutputBaseFilename=DesktopFreeSpace-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; La versión instalada anterior se sustituye entera (evita restos de librerías viejas)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
; Instalación normal: casilla «Abrir Desktop Free Space» al terminar
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
; Actualización silenciosa desde la propia app (/VERYSILENT /RELAUNCH): la vuelve a abrir
Filename: "{app}\{#MyAppExe}"; Flags: nowait; Check: WantsRelaunch

[Code]
function WantsRelaunch: Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), '/RELAUNCH') = 0 then
      Result := True;
end;

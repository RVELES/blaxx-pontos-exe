; ─────────────────────────────────────────────────────────────────
; Blaxx Pontos · Inno Setup installer script
; Gera um instalador .exe estilo "Next, Next, Finish" para Windows
; Compile com: iscc installer.iss   (instala Inno Setup primeiro)
; Pré-requisito: rodar `python build.py` antes (popula dist/BlaxxPontos/)
; ─────────────────────────────────────────────────────────────────

#define MyAppName      "Blaxx Pontos"
#define MyAppVersion   "0.1.0"
#define MyAppPublisher "Blaxx"
#define MyAppURL       "https://blaxxpontos.com"
#define MyAppExeName   "BlaxxPontos.exe"

[Setup]
AppId={{9F8E2F18-3C5C-4F2B-A4C8-8E2C9C6E1D11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\Blaxx Pontos
DefaultGroupName=Blaxx Pontos
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=BlaxxPontos-{#MyAppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Copia todo o conteúdo do dist/BlaxxPontos/ (pyinstaller onedir output)
Source: "dist\BlaxxPontos\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";       Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

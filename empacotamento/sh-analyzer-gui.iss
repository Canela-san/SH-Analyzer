; O instalador do Windows (Inno Setup 6; F7.12 em docs/gui-progress.md, 4h): a pasta do PyInstaller, o atalho no menu
; Iniciar (e, se pedido, na área de trabalho), a associação dos projetos .shproj e os avisos das licenças. A CI dos
; instaladores (.github/workflows/instaladores.yml) o compila depois do empacotamento/construir.sh, com:
;
;   SH_VERSAO        a versão (o git describe)
;   SH_PASTA_DO_APP  a pasta construída (PASTA\dist\sh-analyzer-gui)
;   SH_SAIDA         onde o instalador fica
;
; Instala só para o usuário, sem pedir o administrador (pode-se escolher para todos na primeira tela).

#define Versao GetEnv("SH_VERSAO")
#define Pasta GetEnv("SH_PASTA_DO_APP")
#define Saida GetEnv("SH_SAIDA")
#define Executavel "sh-analyzer-gui.exe"

[Setup]
AppId={{CE39F86A-61D4-48AD-92F5-456A0D44150E}
AppName=SH-Analyzer
AppVersion={#Versao}
AppPublisher=Gabriel Canela
AppPublisherURL=https://github.com/Canela-san/SH-Analyzer
AppSupportURL=https://github.com/Canela-san/SH-Analyzer/issues
DefaultDirName={autopf}\SH-Analyzer
DefaultGroupName=SH-Analyzer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
LicenseFile={#Pasta}\_internal\LICENSE
InfoBeforeFile={#Pasta}\_internal\AVISOS.txt
UninstallDisplayIcon={app}\{#Executavel}
OutputDir={#Saida}
OutputBaseFilename=sh-analyzer-{#Versao}-windows-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "portugues"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "atalho"; Description: "Um atalho na área de trabalho"; Flags: unchecked

[Files]
Source: "{#Pasta}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SH-Analyzer"; Filename: "{app}\{#Executavel}"
Name: "{group}\Avisos e licenças"; Filename: "{app}\_internal\AVISOS.txt"
Name: "{autodesktop}\SH-Analyzer"; Filename: "{app}\{#Executavel}"; Tasks: atalho

[Registry]
; O .shproj abre no SH-Analyzer (o aplicativo tira o projeto dos argumentos: app.ler_opcoes).
Root: HKA; Subkey: "Software\Classes\.shproj\OpenWithProgids"; ValueType: string; ValueName: "SHAnalyzer.Projeto"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\SHAnalyzer.Projeto"; ValueType: string; ValueName: ""; ValueData: "Projeto do SH-Analyzer"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SHAnalyzer.Projeto\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#Executavel},0"
Root: HKA; Subkey: "Software\Classes\SHAnalyzer.Projeto\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#Executavel}"" ""%1"""

[Run]
Filename: "{app}\{#Executavel}"; Description: "Abrir o SH-Analyzer"; Flags: nowait postinstall skipifsilent

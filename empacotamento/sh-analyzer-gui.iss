; O instalador do Windows (Inno Setup 6; F7.12 em docs/gui-progress.md, 4h): a pasta do PyInstaller, os atalhos no
; menu Iniciar e na área de trabalho, a associação dos projetos .shproj e os avisos das licenças. A CI dos instaladores
; (.github/workflows/instaladores.yml) o compila depois do empacotamento/construir.sh, com:
;
;   SH_VERSAO           a versão mostrada (o git describe)
;   SH_VERSAO_NUMERICA  a versão nos detalhes do arquivo (quatro números: 0.9.0.0)
;   SH_PASTA_DO_APP     a pasta construída (PASTA\dist\sh-analyzer-gui)
;   SH_ICONE            o ícone do instalador (o .ico que a receita gera em PASTA\obra)
;   SH_SAIDA            onde o instalador fica
;
; Feito para quem nunca instalou nada: só para o usuário, sem pedir o administrador nem perguntar a pasta, e duas
; telas (os atalhos e o fim, que abre o aplicativo). Por cima de uma versão instalada, é a atualização: mesma pasta,
; o aplicativo aberto é fechado antes, e as configurações e as capturas ficam (nem a desinstalação as apaga).
; O aviso de versão nova do aplicativo o roda calado, com /SILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS /REABRIR=1.

#define Versao GetEnv("SH_VERSAO")
#define Pasta GetEnv("SH_PASTA_DO_APP")
#define Saida GetEnv("SH_SAIDA")
#define Icone GetEnv("SH_ICONE")
#define VersaoNumerica GetEnv("SH_VERSAO_NUMERICA")
#if VersaoNumerica == ""
  #define VersaoNumerica "0.0.0.0"
#endif
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
PrivilegesRequiredOverridesAllowed=commandline
DisableDirPage=auto
DisableReadyPage=yes
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
UninstallDisplayIcon={app}\{#Executavel}
UninstallDisplayName=SH-Analyzer
VersionInfoVersion={#VersaoNumerica}
VersionInfoProductName=SH-Analyzer
VersionInfoDescription=Instalador do SH-Analyzer
#if Icone != ""
SetupIconFile={#Icone}
#endif
OutputDir={#Saida}
OutputBaseFilename=sh-analyzer-{#Versao}-windows-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "portugues"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "atalho"; Description: "Um atalho na área de trabalho"

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
; A atualização pelo aviso do aplicativo: calada, e o aplicativo volta aberto.
Filename: "{app}\{#Executavel}"; Flags: nowait; Check: Reabrir

[Code]
function Reabrir: Boolean;
begin
  Result := ExpandConstant('{param:REABRIR|0}') = '1';
end;

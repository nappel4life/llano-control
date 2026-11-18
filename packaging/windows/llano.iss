; Installationsprogramm fuer Windows (Inno Setup 6)
;
;   ISCC.exe /DVersion=1.0.0 packaging\windows\llano.iss
;
; Vorher müssen die Programmdateien gebaut sein:
;
;   pyinstaller --noconfirm --clean packaging\llano.spec
;
; Das Ergebnis liegt dann in dist\llano-control:
;
;   llano-control.exe   Oberflaeche, Doppelklick ohne Konsole
;   llano.exe           Kommandozeile (auch fuer llano.exe selftest)
;
; Auf GitHub wird Version und Ausgabename durch /D vorgegeben.

#define MyAppName    "llano Control"
#define MyAppVersion "1.0.0"
#if Defined(Version)
  #define MyAppVersion Version
#endif
#define MyAppPublisher "llano-control contributors"
#define MyAppURL       "https://github.com/nappel4life/llano-control"
#define MyAppExeName   "llano-control.exe"
#define MyCliExeName   "llano.exe"

[Setup]
AppId={{B7A6C4E2-5C1D-4C9B-8E4F-2A0D6F1C9E77}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\llano-control
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
OutputDir=..\..\out
OutputBaseFilename=llano-control-{#MyAppVersion}-windows-amd64
SetupIconFile=..\..\assets\llano.ico
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=force

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";  Description: "Symbol auf dem Schreibtisch anlegen"
Name: "autostart";    Description: "Beim Anmelden starten (Kuehler haelt die Kurve von allein)"
Name: "pathicon";     Description: "llano.exe in den Suchpfad setzen"; Flags: unchecked

[Files]
Source: "..\..\dist\llano-control\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";              Filename: "{app}\{#MyAppExeName}"; \
    Comment: "Oberflaeche fuer Luefter und Beleuchtung"
Name: "{group}\llano (Kommandozeile)";     Filename: "{app}\{#MyCliExeName}"; \
    Comment: "Kommandozeile, z. B. llano status"
Name: "{group}\Handbuch lesen";            Filename: "{#MyAppURL}"
Name: "{group}\{#MyAppName} deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";        Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Registry]
; Autostart im eigenen Konto, ohne Dienst und ohne Admin-Rechte noetig zu machen.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "llano-control"; \
    ValueData: """{app}\{#MyAppExeName}"" --tray"; Flags: uninsdeletevalue; \
    Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Oberflaeche jetzt starten"; \
    Flags: nowait postinstall skipifsilent runascurrentuser
Filename: "{app}\{#MyCliExeName}"; Parameters: "selftest"; \
    Description: "Pruefen, was Rechner und Kuehler zusammen koennen"; \
    Flags: nowait postinstall skipifsilent runascurrentuser

[Code]
// Der Suchpfad bekommt den Ordner nur, wenn die Aufgabe gewaehlt wurde - und
// verliert ihn beim Deinstallieren auch wieder.
procedure CurStepChanged(CurStep: TSetupStep);
var
  Path: String;
begin
  if CurStep <> ssPostInstall then Exit;
  if not TaskIsSelected('pathicon') then Exit;
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
      'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
      'Path', Path) then Path := '';
  if Pos('{app}', Path) = 0 then
  begin
    if (Length(Path) > 0) and (Path[Length(Path)] <> ';') then Path := Path + ';';
    Path := Path + ExpandConstant('{app}');
    RegWriteStringValue(HKEY_LOCAL_MACHINE,
      'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', Path);
    Log('Suchpfad ergaenzt um {app}');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Path: String;
  App: String;
begin
  if CurUninstallStep <> usPostUninstall then Exit;
  App := ExpandConstant('{app}');
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
      'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
      'Path', Path) then Exit;
  StringChangeEx(Path, App + ';', '', True);
  StringChangeEx(Path, App, '', True);
  RegWriteStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', Path);
end;

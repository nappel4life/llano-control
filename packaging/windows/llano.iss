; Installationsprogramm fuer Windows (Inno Setup 6)
;
;   ISCC.exe /DVersion=1.1.1 packaging\windows\llano.iss
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
#define MyAppVersion "1.1.1"
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
; Die drei Aufgaben erkaeren sich hier selbst. Das Setup zeigt sonst Punkte an,
; deren Folgen man erst viel spaeter merkt - und die man dann nicht ankreuzt.
Name: "desktopicon";  Description: "Verknüpfung auf dem Desktop anlegen"
Name: "autostart";    Description: "Bei jeder Anmeldung starten - der Kühler hält die Kurve auch ohne Fenster"
Name: "pathicon";     Description: "llano.exe im Suchpfad anmelden - dann genügt `llano status` in jedem Eingabefenster"; Flags: unchecked
; Die Prozessortemperatur kann nur ein Programm mit Kernel-Treiber holen. Die
; Messhilfe selbst liegt deshalb immer mit bei ({app}\messhilfe): ein Helfer
; ohne Fenster, den dieses Programm selbst startet und wieder beendet. Dieser
; Haken legt ausserdem das komplette fremde Programm dazu - das Fenster mit
; Symbolbereich, das als einziges den Prozessortreiber dazulegen weiss und der
; auch dann noch Werte liefert, wenn dieses Programm normal arbeitet.
Name: "cpu";          Description: "Messhilfe LibreHardwareMonitor mitinstallieren (Fenster im Symbolbereich, {app}\helfer)"

[InstallDelete]
; Ein Update ueberschreibt gleichnamige Dateien, aber was die alte Fassung
; zusaetzlich im Gepaeck hatte, bleibt stehen. Bei einem verpackten Programm
; ist das kein Kleinstd: Zwei Qt-Bibliotheken in einem Ordner, und die
; Oberflaeche startet gar nicht mehr - ohne Fenster, ohne Meldung und ohne
; eine einzige geschriebene Datei. Also vor dem Kopieren sauber machen.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\llano-control.exe"
Type: files; Name: "{app}\llano.exe"
Type: files; Name: "{app}\llano-rs.exe"
Type: filesandordirs; Name: "{app}\helfer"
Type: filesandordirs; Name: "{app}\messhilfe"

[Files]
Source: "..\..\dist\llano-control\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
; Die Messhilfe als Bibliothek: immer dabei, ohne Haken und ohne Frage. Ohne
; Ordner laeuft das Programm wie vorher - die Quelle schweigt dann halt, und
; die Oberflaeche sagt das. `skipifsourcedoesntexist` laesst einen Bau von Hand
; durchlaufen, der die Bauautomatik nicht hinter sich hat.
Source: "..\..\paket\messhilfe\*"; DestDir: "{app}\messhilfe"; \
    Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
; Das fremde Programm mit Fenster dazu; wird auf GitHub neben dem Installer
; geholt (siehe pakete.yml) und ist hier schon ausgepackt.
Source: "..\..\paket\programm\*"; DestDir: "{app}\helfer"; Tasks: cpu; \
    Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "helfer.config"; DestDir: "{app}\helfer"; DestName: "LibreHardwareMonitor.config"; \
    Tasks: cpu; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}";              Filename: "{app}\{#MyAppExeName}"; \
    Comment: "Oberfläche für Lüfter und Beleuchtung"
Name: "{group}\llano (Kommandozeile)";     Filename: "{app}\{#MyCliExeName}"; \
    Comment: "Kommandozeile, zum Beispiel: llano status"
Name: "{group}\Kühler prüfen";             Filename: "{sys}\cmd.exe"; \
    Parameters: "/k ""{app}\{#MyCliExeName}"" selftest"; \
    Comment: "Zeigt, was dieser Rechner am Kühler erkennt - und was nicht"
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
Filename: "{app}\{#MyAppExeName}"; Description: "Oberfläche jetzt starten"; \
    Flags: nowait postinstall skipifsilent runascurrentuser
; Ueber cmd /k bleibt das Fenster stehen: der Bericht ist der ganze Sinn des
; Punktes, und ein Fenster, das sich selbst wieder schliesst, zeigt nichts.
Filename: "{sys}\cmd.exe"; Parameters: "/k ""{app}\{#MyCliExeName}"" selftest"; \
    Description: "Bericht anzeigen: was dieser Rechner am Kühler erkennt"; \
    Flags: nowait postinstall skipifsilent runascurrentuser

[Code]
// Die Einstellungsdatei bleibt beim Deinstallieren absichtlich liegen: sie
// enthält die Lüfterkurve, die sich jemand erarbeitet hat, und ein Update soll
// sie nicht kosten. Was dabei leicht übersehen wird: Dieselbe Datei überlebt
// auch einen Wechsel der Fassung, und ein Feldbericht zeigte genau daraus den
// Verdacht, das neue Programm sei kaputt. Also fragt der Deinstaller jetzt
// direkt nach - und die Fassung selbst kommt ohnehin mit jeder alten Datei
// zurecht, seit sie beim Lesen geformt wird.
var
  EinstellungenWeg: Boolean;

function InitializeUninstall(): Boolean;
begin
  EinstellungenWeg := (MsgBox(
    'Auch die Einstellungen löschen?' + #13#10 + #13#10 +
    'Sie liegen unter AppData\Roaming\llano: die Lüfterkurve, die gewählten'
    + ' Messstellen, die Beleuchtung und die Protokolle der Oberfläche.'
    + #13#10 + 'Beim Update auf eine neue Fassung kannst du sie getrost behalten.',
    mbConfirmation, MB_YESNO) = IDYES);
  Result := True;
end;

// Der Suchpfad bekommt den Ordner nur, wenn die Aufgabe gewaehlt wurde - und
// verliert ihn beim Deinstallieren auch wieder.
procedure CurStepChanged(CurStep: TSetupStep);
var
  Path: String;
  Code: Integer;
begin
  if CurStep <> ssPostInstall then Exit;

  // Die Messhilfe braucht erhohte Rechte, um die Fuehler im Prozessor lesen zu
  // duerfen. Aus dem Eingabefenster heraus wuerde das bei jeder Anmeldung nach-
  // fragen; eine Anmeldungsaufgabe mit hoechsten Rechten fragt einmal - beim
  // Anlegen - und danach nie wieder.
  if WizardIsTaskSelected('cpu') then
  begin
    if not Exec(ExpandConstant('{sys}schtasks.exe'),
        '/Create /F /TN "llano Messhilfe" /SC ONLOGON /RL HIGHEST /TR """'
        + ExpandConstant('{app}\helfer\LibreHardwareMonitor.exe') + '"""',
        '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
      Log('Messhilfe konnte nicht als Anmeldungsaufgabe angemeldet werden ('
          + IntToStr(Code) + ')');
    Log('Messhilfe als Anmeldungsaufgabe angemeldet');
  end;

  if not WizardIsTaskSelected('pathicon') then Exit;
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
  Code: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    // Vor dem Loeschen: die Anmeldungsaufgabe abmelden und einen laufenden
    // Helfer schliessen. Sonst stehen die Dateien der Messhilfe noch im
    // Programmordner, und der Deinstaller meldet einen halbfertigen Stand.
    // Der kleine Helfer (llano-messhilfe.exe) haengt an seinem
    // Elternprozess und geht mit ihm aus - erhaelt er aber gerade Werte von
    // einem Processor, der nicht antwortet, kann er lange sitzen; die Dateien
    // des Ordners waeren danach beschaedigt.
    Exec(ExpandConstant('{sys}taskkill.exe'),
         '/F /IM LibreHardwareMonitor.exe', '', SW_HIDE,
         ewWaitUntilTerminated, Code);
    Exec(ExpandConstant('{sys}taskkill.exe'),
         '/F /IM llano-messhilfe.exe', '', SW_HIDE,
         ewWaitUntilTerminated, Code);
    Exec(ExpandConstant('{sys}schtasks.exe'),
         '/Delete /F /TN "llano Messhilfe"', '', SW_HIDE,
         ewWaitUntilTerminated, Code);
  end;
  if CurUninstallStep <> usPostUninstall then Exit;
  if EinstellungenWeg then
  begin
    // Der Programmdatenordner enthaelt ausser der Kurve auch die Protokolle,
    // die die Oberflaeche seit der 1.1.4 dazulegt.
    DelTree(ExpandConstant('{userappdata}\llano'), True, True, True);
    DelTree(ExpandConstant('{localappdata}\llano'), True, True, True);
    Log('Einstellungen und Protokolle geloescht');
  end;
  App := ExpandConstant('{app}');
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
      'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
      'Path', Path) then Exit;
  StringChangeEx(Path, App + ';', '', True);
  StringChangeEx(Path, App, '', True);
  RegWriteStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', Path);
end;

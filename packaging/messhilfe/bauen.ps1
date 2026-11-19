<#
.SYNOPSIS
  Macht aus der ausgepackten Messhilfe zwei Stuecke fur den Windows-Installer.

.DESCRIPTION
  Das Steuerprogramm legt die Messhilfe (LibreHardwareMonitor) auf zwei Arten
  bei, und beide kommen aus derselben heruntergeladenen Datei:

    -Messhilfe  ->  paket\messhilfe   immer mitinstalliert
        Die Bibliothek, ihre Abhaengigkeiten und der uebersetzte Helfer
        (messhilfe.cs -> llano-messhilfe.exe). Kein Fenster, kein Symbol-
        bereich, kein Port; das Steuerprogramm startet sie und hoert auf sie.
    -Programm   ->  paket\programm    nur bei gewaehltem Haken
        Das komplette fremde Programm mit Fenster und Web-Server, fuer
        jemanden, der die Prozessorfuehler ohne erhohte Rechte des
        Steuerprogramms lesen lassen will.

  Der Helfer wird mit dem Compiler uebersetzt, den Windows selbst mitbringt
  (%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe). Die Bibliothek ist
  eine .NET-Framework-4.7.2-Baugruppe, und die hat jeder aktuelle Windows-
  Rechner schon an Bord - ein nachtraeglich zu installierendes .NET waere
  genau die Zusatzinstallation, die dieses Stueck Arbeit ueberfluessig machen
  soll.

.BEISPIEL
  powershell -File packaging\messhilfe\bauen.ps1 -Entpackt $env:RUNNER_TEMP\entpackt
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Entpackt,
    [string]$Messhilfe = "paket\messhilfe",
    [string]$Programm = "paket\programm",
    [string]$Quelltext = ""
)

$ErrorActionPreference = "STOP"
$Wurzel = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Quelltext) { $Quelltext = Join-Path $PSScriptRoot "messhilfe.cs" }

function Write-Schritt([string]$Text) { Write-Host ">> $Text" }

# ------------------------------------------------------------------ die Quelle

if (-not (Test-Path (Join-Path $Entpackt "LibreHardwareMonitorLib.dll"))) {
    throw "In '$Entpackt' liegt keine LibreHardwareMonitorLib.dll."
}

# Die Ordner der Zipdatei sind nicht verlaesslich: mal liegt alles oben, mal in
# einem Unterordner. Beides auf eine Ebene bringen.
$Kinder = @(Get-ChildItem $Entpackt | Where-Object { $_.Name -notlike "*.zip" })
if ($Kinder.Count -eq 1 -and $Kinder[0].PSIsContainer -and
    (Test-Path (Join-Path $Kinder[0].FullName "LibreHardwareMonitorLib.dll"))) {
    $Quelle = $Kinder[0].FullName
} else { $Quelle = $Entpackt }

# Nur das Programm mit Fenster braucht diese Baugruppen; die Bibliothek nicht.
# Wer sie mitnimmt, zahlt zwei Megabyte fuer ein Diagramm, das niemand sieht.
# Nachgeprueft ist das an den referenzierten Baugruppen der Bibliotheksdatei
# selbst, nicht am Gefuehl: BlackSharp.Core zum Beispiel gehoert zum Schatten-
# werf eines Fensters, wird von der Bibliothek aber wirklich referenziert -
# es bleibt deshalb drin (32 Kilobyte) und nicht auf der Liste.
$Oberflaeche = @(
    "Aga.Controls.dll",
    "Microsoft.Win32.TaskScheduler.dll",
    "OxyPlot.dll",
    "OxyPlot.WindowsForms.dll"
)

function NeueMappe([string]$Pfad) {
    if (Test-Path $Pfad) { Remove-Item -Recurse -Force $Pfad }
    New-Item -ItemType Directory -Force -Path $Pfad | Out-Null
    return (Resolve-Path $Pfad).Path
}

function ImAntwortPfad([string]$Pfad) {
    # In einer Antwortdatei steht ein Argument pro Zeile, und die Zeile wird an
    # Leerzeichen geteilt. Pfade mit Leerzeichen (ein Benutzerordner heisst bei
    # vielen so) brauchen deshalb Anfuehrungszeichen - die anderen nicht.
    if ($Pfad -like "* *") { return '"' + $Pfad + '"' }
    return $Pfad
}

# ------------------------------------------------- 1) die Messhilfe als Helfer

$ZielMesshilfe = NeueMappe (Join-Path $Wurzel $Messhilfe)
Write-Schritt "Messhilfe: $ZielMesshilfe"

$mitgenommen = @()
Get-ChildItem (Join-Path $Quelle "*.dll") | ForEach-Object {
    if ($Oberflaeche -contains $_.Name) { return }
    Copy-Item $_.FullName -Destination $ZielMesshilfe -Force
    $mitgenommen += $_.Name
}

# Der Compiler, den Windows mitbringt. Zwei Pfade, weil es ihn sowohl in der
# 64-Bit- als auch in der 32-Bit-Fassung des Frameworks gibt.
$csc = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1

$Ausgabe = Join-Path $ZielMesshilfe "llano-messhilfe.exe"

if ($csc) {
    Write-Schritt "Uebersetzen mit $csc"
    $Bibliothek = Join-Path $ZielMesshilfe "LibreHardwareMonitorLib.dll"
    if (-not (Test-Path $Bibliothek)) {
        throw "Die Messhilfe wurde nicht mitgenommen: $Bibliothek fehlt."
    }

    # Die Argumente kommen in eine Antwortdatei und nicht in die Befehlszeile:
    # Uebersetzer dieser Art lesen so eine Datei (als '@pfad'), und dann haengt
    # nichts davon ab, wie eine Shell Doppelpunkte und Anfuehrungszeichen
    # weiterreicht.
    #
    # Und die Felder werden vorher ausgerechnet, nicht in der Mappe mit "+"
    # aneinandergefuegt. Genau daran sind die beiden ersten Bauversuche
    # zerbrochen: aus "/out:" + Pfad innerhalb von @( ) wurden zwei Felder, der
    # Uebersetzer sah ein "/out:" ohne Datei dahinter und nannte das "Missing
    # file specification". Ein Feld pro Zeile, keine Kommas, kein Addieren.
    $AusgabeAntwort = ImAntwortPfad $Ausgabe
    $BibliothekAntwort = ImAntwortPfad $Bibliothek
    $QuelltextAntwort = ImAntwortPfad $Quelltext
    $Zeilen = @(
        "/nologo"
        "/optimize+"
        "/target:exe"
        "/platform:anycpu"
        "/out:$AusgabeAntwort"
        "/reference:$BibliothekAntwort"
        "/reference:System.dll"
        "/reference:System.Core.dll"
        $QuelltextAntwort
    )
    $Behelf = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [System.IO.Path]::GetTempPath() }
    $Antwort = Join-Path $Behelf "llano-messhilfe.csc.rsp"
    # Mit Zeichensetzung am Anfang, damit der Uebersetzer die Datei als UTF-8
    # liest und ein Pfad mit Umlauten kein Ratbuchstabenraten wird.
    [System.IO.File]::WriteAllLines($Antwort, $Zeilen,
                                    (New-Object System.Text.UTF8Encoding($true)))
    Write-Schritt "Antwortdatei: $Antwort"
    # Was wirklich dort steht, wird nachgelesen: der erste und der zweite
    # Bauversuch haben gezeigt, dass die Zeilen unterwegs zerlegen koennen,
    # und ein Uebersetzer, der "/out:" ohne Datei sieht, raetet nicht - er
    # bricht ab, aber erst nach ihm.
    $Gelesen = @(Get-Content $Antwort)
    $AusgabeZeile = @($Gelesen | Where-Object { $_ -like "/out:*llano-messhilfe.exe*" })
    $ReferenzZeile = @($Gelesen | Where-Object { $_ -like "/reference:*LibreHardwareMonitorLib.dll*" })
    if ($Gelesen.Count -ne $Zeilen.Count -or $AusgabeZeile.Count -ne 1 -or
        $ReferenzZeile.Count -ne 1) {
        Write-Host "In der Antwortdatei steht:"
        $Gelesen | ForEach-Object { Write-Host "  [$_]" }
        throw "Die Uebersetzer-Angaben sind zerlegt angekommen."
    }
    & $csc "@$Antwort"
    if ($LASTEXITCODE -ne 0) {
        # Zweiter Versuch: dieselben Angaben direkt, hier ausdruecklich statt
        # als Mappe - was von beiden ankommt, entscheidet der Uebersetzer, und
        # der Versuch kostet zwei Sekunden statt eines Bau-Laufs.
        Write-Schritt "noch einmal ohne Antwortdatei"
        & $csc /nologo /optimize+ /target:exe /platform:anycpu `
              "/out:$Ausgabe" "/reference:$Bibliothek" `
              /reference:System.dll /reference:System.Core.dll $Quelltext
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Bekommen hat der Uebersetzer:"
            $Zeilen | ForEach-Object { Write-Host "  [$_]" }
            throw "Der Uebersetzer hat $LASTEXITCODE zurueckgegeben."
        }
    }
} else {
    # Keine Windows-Framework-Uebersetzer: zweiter Weg ueber das .NET-Werkzeug
    # und die Referenzbaugruppen als Paket. Langsamer, aber laeuft auch dort.
    Write-Schritt "Uebersetzen mit dotnet"
    $Entwurf = Join-Path $env:RUNNER_TEMP "messhilfe.csproj"
    @"
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net472</TargetFramework>
    <LangVersion>latest</LangVersion>
    <AssemblyName>llano-messhilfe</AssemblyName>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
    <Nullable>disable</Nullable>
  </PropertyGroup>
  <ItemGroup>
    <Compile Include="$($Quelltext -replace '\\','/')" />
  </ItemGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.NETFramework.ReferenceAssemblies" Version="1.0.3" PrivateAssets="all" />
    <Reference Include="LibreHardwareMonitorLib"><HintPath>$((Join-Path $ZielMesshilfe 'LibreHardwareMonitorLib.dll') -replace '\\','/')</HintPath></Reference>
  </ItemGroup>
</Project>
"@ | Set-Content -Encoding UTF8 $Entwurf
    dotnet build $Entwurf -c Release -o (Join-Path $env:RUNNER_TEMP "messhilfe-out") --nologo
    if ($LASTEXITCODE -ne 0) { throw "dotnet build hat $LASTEXITCODE zurueckgegeben." }
    Copy-Item (Join-Path $env:RUNNER_TEMP "messhilfe-out\llano-messhilfe.exe") -Destination $Ausgabe -Force
}

if (-not (Test-Path $Ausgabe)) { throw "Es fehlt: $Ausgabe" }

# Lizenztexte mit: Die Messhilfe steht unter der Mozilla Public License 2.0,
# ihre PawnIO-Bausteine unter GNU LGPL 2.1. Wer den Ordner im Programmordner
# aufmacht, soll sehen, was hier fremd ist und woher es kommt.
foreach ($Stueck in "LICENSE", "THIRD-PARTY-NOTICES.txt") {
    $wo = Join-Path $Quelle $Stueck
    if (Test-Path $wo) { Copy-Item $wo -Destination $ZielMesshilfe -Force }
    elseif (Test-Path (Join-Path $PSScriptRoot $Stueck)) {
        Copy-Item (Join-Path $PSScriptRoot $Stueck) -Destination $ZielMesshilfe -Force
    }
}
Copy-Item (Join-Path $PSScriptRoot "LESEAMICH.md") -Destination $ZielMesshilfe -Force

$grosse = [math]::Round(((Get-ChildItem $ZielMesshilfe -Recurse |
        Measure-Object Length -Sum).Sum / 1MB), 2)
Write-Schritt ("Messhilfe: " + (Get-ChildItem $ZielMesshilfe).Count + " Dateien, " +
               $grosse + " MB, davon Baugruppen: " + ($mitgenommen.Count))

# ---------------------------------------------- 2) das fremde Programm dazu

$ZielProgramm = NeueMappe (Join-Path $Wurzel $Programm)
Write-Schritt "Programm: $ZielProgramm"
Copy-Item -Path (Join-Path $Quelle "*") -Destination $ZielProgramm -Recurse -Force
Get-ChildItem $ZielProgramm -Recurse -Include "*.pdb", "*.xml" | Remove-Item -Force
foreach ($Stueck in "LICENSE", "THIRD-PARTY-NOTICES.txt") {
    $wo = Join-Path $Quelle $Stueck
    if (Test-Path $wo) { Copy-Item $wo -Destination $ZielProgramm -Force }
}
if (-not (Test-Path (Join-Path $ZielProgramm "LibreHardwareMonitor.exe"))) {
    throw "Das fremde Programm fehlt in '$ZielProgramm'."
}

# ------------------------------------------------------- 3) der Selbstversuch

# Die eine Frage, die hier niemand beantworten kann, ohne sie zu stellen: laeuft
# der Helfer in einem verpackten Umfeld und schreibt er die eine Zeile ueber
# sich selbst? Der Bauwagen hat weder Prozessorfuehler noch darf dort der
# Treiber - eine leere Liste ist also kein Grund zum Aufhalten, eine Zeile
# ueber sich selbst ist es immer.
Write-Schritt "Der Helfer probiert sich selbst"
$Zeilen = & $Ausgabe --einmal 2>&1
$erste = @($Zeilen | Where-Object { $_ -like "{*" } | Select-Object -First 1)
if (-not $erste) {
    Write-Host "Achtung: der Helfer hat keine Zeile ueber sich selbst geschrieben."
    $Zeilen | ForEach-Object { Write-Host "   $_" }
    throw "Der Helfer arbeitet nicht."
}
Write-Host ("   " + $erste)
if ($erste -like '"art":"fehler"*') {
    throw "Der Helfer meldet einen Fehler: $erste"
}
Write-Schritt "fertig"

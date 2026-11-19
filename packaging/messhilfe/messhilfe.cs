// llano-messhilfe.exe - die Messhilfe als Bibliothek, in einem eigenen Prozess.
//
// Die Messhilfe (LibreHardwareMonitor) ist eine .NET-Bibliothek. Sie liesse
// sich auch direkt in Python ansprechen (pythonnet), aber dieses kleine
// Programm hier ist der bewusst einfachere Weg:
//
//  * Es sind zwanzig Kilobyte, die Bibliothek bleibt, wo sie hingehoert, und
//    das Steuerprogramm behaelt seinen Grundsatz, keine dritte Paketsammlung
//    zu brauchen ("dependencies = []" in pyproject.toml).
//  * Ein Fremdprogramm, das durch einen Kernel-Treiber liest, faellt schon mal
//    um. Faellt es im eigenen Prozess, faellt die Oberflaeche mit - genau die
//    Erfahrung der letzten Tage (Zugriffsverletzung beim Aufraeumen). Hier
//    faellt nur die Messhilfe, und die Quelle schweigt, wie sie schon vorher
//    geschwiegen hat.
//  * Die Rechtefrage bleibt, wo sie hin gehoert: in einem eigenen Prozess, den
//    man spaeter erhoeht starten kann, ohne das ganze Programm zu erhoehen.
//
// Es haengt an seinem Elternprozess: die Standard-Eingabe ist ein
// Kanarienvogel, kein Datenkanal. Stirbt das Steuerprogramm, schliesst der
// Kanal, und dieses Programm geht von selbst aus. Ein Helfer, der ohne seinen
// Herrn weiterlaeuft, waere genau das zweite Programm, das wir abschaffen
// wollen.
//
// Ausgabe: eine Zeile pro Nachricht, JavaScript-Notation, im ASCII-Raum
// (Alles Nicht-Englische wird als \uXXXX geschrieben, damit keine
// Zeichenkodierung dazwischenfunkt). Erste Zeile: die Auskunft ueber sich
// selbst. Danach eine Zeile Messwerte pro Takt.
//
//   {"art":"start","erhoeht":true,"treiber":true,"treiber_fassung":"2.0.0",
//    "bibliothek":"0.9.6.0","geraete":9,"takt":1000}
//   {"art":"werte","zeit":1763542000,"temperaturen":[
//        {"geraet":"CPU","messstelle":"CPU (Package)","wert":54.3}]}
//   {"art":"fehler","text":"..."}
//
// Uebersetzt wird mit dem Compiler, den Windows selbst mitbringt
// (%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe), darum ohne neueren
// Sprachchatz: keine Zeichenketten-Einbettung, keine
// Ausdruckskoerper, kein nullbedingter Operator. Siehe bauen.ps1.
//
// Diese Datei steht - wie die Messhilfe selbst - unter der Mozilla Public
// License 2.0; siehe packaging/messhilfe/LESEAMICH.md.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Security.Principal;
using System.Text;
using System.Threading;
using LibreHardwareMonitor.Hardware;

internal static class Messhilfe
{
    // Wird gesetzt, wenn der Elternprozess seinen Eingabekanal geschlossen hat.
    private static volatile bool vaterWeg = false;

    private static int Main(string[] argumente)
    {
        // Konsolenzeichenkodierung ist hier gleichgueltig: wir schreiben nur
        // 7-Bit-Zeichen. Ohne diese Zeile haette ein Umlaut in einem
        // Geratenamen den Elternprozess vor ein Raten gestellt.
        try { Console.OutputEncoding = new UTF8Encoding(false); }
        catch (Exception) { }

        int takt = 1000;
        int dauer = 0;
        bool einmal = false;
        for (int i = 0; i < argumente.Length; i++)
        {
            if (argumente[i] == "--einmal") { einmal = true; }
            else if (argumente[i] == "--takt" && i + 1 < argumente.Length)
            { int.TryParse(argumente[++i], out takt); }
            else if (argumente[i] == "--dauer" && i + 1 < argumente.Length)
            { int.TryParse(argumente[++i], out dauer); }
        }
        if (takt < 250) { takt = 250; }

        string grund;
        Computer rechner = offnen(out grund);
        if (rechner == null)
        {
            Console.Out.WriteLine(zeile("fehler", "text", text(grund)));
            Console.Out.Flush();
            return 2;
        }

        List<IHardware> geraete = neueAlle(rechner.Hardware);
        Console.Out.WriteLine(zeile("start",
                                    "erhoeht", wahr(istErhoeht()),
                                    "treiber", wahr(treiberDa()),
                                    "treiber_fassung", text(treiberFassung()),
                                    "bibliothek", text(bibliothekFassung()),
                                    "geraete", geraete.Count.ToString(CultureInfo.InvariantCulture),
                                    "takt", takt.ToString(CultureInfo.InvariantCulture)));
        Console.Out.Flush();

        // Der Kanarienvogel: ein Faden, der nur liest. Er blockiert, bis der
        // Elternprozess den Kanal schliesst, und setzt dann das Merkmal.
        Thread wachter = null;
        if (einmal == false)
        {
            wachter = new Thread(new ThreadStart(beobachteEingabe));
            wachter.IsBackground = true;
            wachter.Name = "kanarienvogel";
            wachter.Start();
        }

        // Die erste Messung dauert am laengsten: die Bibliothek liest jetzt
        // zuerst die Tabellen der Geraete.
        sende(geraete);

        Stopwatch uhr = Stopwatch.StartNew();
        while (einmal == false)
        {
            if (vaterWeg) { break; }
            if (dauer > 0 && uhr.ElapsedMilliseconds >= dauer * 1000L) { break; }
            schlaft(takt);
            if (vaterWeg) { break; }
            sende(geraete);
        }

        try { rechner.Close(); }
        catch (Exception) { }
        return 0;
    }

    // Was beim Oeffnen angefasst werden darf. Arbeitsspeicher und Laufwerke
    // kosten Sekunden und bringen einer Kuehlerkurve nichts; das Netzteil
    // haengt an einer seriellen Schnittstelle.
    private static Computer offnen(out string grund)
    {
        grund = null;

        Computer rechner = neueKonfiguration(true);
        string grundVollstaendig = oeffne(rechner);
        if (grundVollstaendig == null) { return rechner; }

        // Der Prozessor ist das einzige Stueck, das einen Kernel-Treiber
        // anfasst. Scheitert das Oeffnen daran, sind Grafikkarte und Mainboard
        // immer noch gewonnen: Ohne diesen zweiten Versuch stuetze ein Rechner
        // ohne Treiber ganz ohne Werte ab, und die Kurve haette sich selbst
        // abgeschafft, wo sie doch nur eine Zahl sucht.
        Computer ohneProzessor = neueKonfiguration(false);
        string grundOhne = oeffne(ohneProzessor);
        if (grundOhne == null) { return ohneProzessor; }

        grund = grundVollstaendig;
        return null;
    }

    private static Computer neueKonfiguration(bool mitProzessor)
    {
        // Arbeitsspeicher und Laufwerke kosten Sekunden und bringen einer
        // Kuehlerkurve nichts; das Netzteil haengt an einer seriellen
        // Schnittstelle, und das Netz meldet keine Waerme.
        Computer rechner = new Computer();
        rechner.IsCpuEnabled = mitProzessor;
        rechner.IsGpuEnabled = true;
        rechner.IsMotherboardEnabled = true;
        rechner.IsControllerEnabled = true;
        rechner.IsMemoryEnabled = false;
        rechner.IsStorageEnabled = false;
        rechner.IsNetworkEnabled = false;
        rechner.IsPsuEnabled = false;
        rechner.IsBatteryEnabled = false;
        return rechner;
    }

    // Null, wenn das Geraet offen ist; sonst der Satz, warum nicht. Ein
    // halb geoeffnetes Stueck wird zurueckgegeben, sonst haelte der zweite
    // Versuch einen Treiber offen, der gerade abgelehnt hat.
    private static string oeffne(Computer rechner)
    {
        try
        {
            rechner.Open();
            return null;
        }
        catch (Exception ausnahme)
        {
            try { rechner.Close(); }
            catch (Exception) { }
            return ausnahme.GetType().Name + ": " + ausnahme.Message;
        }
    }

    private static void beobachteEingabe()
    {
        Stream eingabe;
        try { eingabe = Console.OpenStandardInput(); }
        catch (Exception) { vaterWeg = true; return; }
        byte[] puffer = new byte[1];
        while (true)
        {
            int gelesen;
            try { gelesen = eingabe.Read(puffer, 0, 1); }
            catch (Exception) { break; }
            if (gelesen <= 0) { break; }
        }
        vaterWeg = true;
    }

    private static void schlaft(int millisekunden)
    {
        // In Stuecken schlafen, damit der Tod des Elternprozesses nicht erst am
        // Ende des Takts auffaellt.
        int verblieben = millisekunden;
        while (verblieben > 0 && vaterWeg == false)
        {
            int schritt = verblieben > 200 ? 200 : verblieben;
            try { Thread.Sleep(schritt); }
            catch (Exception) { return; }
            verblieben -= schritt;
        }
    }

    private static void sende(List<IHardware> geraete)
    {
        StringBuilder temperaturen = new StringBuilder();
        for (int i = 0; i < geraete.Count; i++)
        {
            IHardware gerat = geraete[i];
            try { gerat.Update(); }
            catch (Exception) { continue; }      // ein Geraet, nicht die Welt
            ISensor[] messungen;
            try
            {
                List<ISensor> liste = new List<ISensor>();
                foreach (ISensor messung in gerat.Sensors) { liste.Add(messung); }
                messungen = liste.ToArray();
            }
            catch (Exception) { continue; }

            for (int m = 0; m < messungen.Length; m++)
            {
                ISensor messung = messungen[m];
                try
                {
                    if (messung.SensorType != SensorType.Temperature) { continue; }
                    float grad = messung.Value ?? float.NaN;
                    if (float.IsNaN(grad) || float.IsInfinity(grad)) { continue; }
                    if (temperaturen.Length > 0) { temperaturen.Append(','); }
                    temperaturen.Append(zeile(null,
                                              "geraet", text(gerat.Name),
                                              "messstelle", text(messung.Name),
                                              "wert", grad.ToString("R", CultureInfo.InvariantCulture)));
                }
                catch (Exception) { continue; }   // dieselbe Regel wie beim Geraet
            }
        }
        Console.Out.WriteLine(zeileMitListe("werte", "zeit", epochSekunden(),
                                            "temperaturen", temperaturen.ToString()));
        Console.Out.Flush();
    }

    // Alle Geraete, auch die unter einem anderen: die Fuehler eines
    // Prozessors haengen bei manchen Treibern am Unterknoten, und wer nur die
    // obere Ebene liest, haelt den Rechner fuer kalt.
    // Die Bibliothek liefert eine Liste und kein Feld, und ein Feld nimmt
    // diese Fassung auch an - danach haengt nichts mehr davon ab, welche der
    // beiden Sorten die Fassung gerade zurueckgibt.
    private static List<IHardware> neueAlle(IEnumerable<IHardware> oben)
    {
        List<IHardware> alle = new List<IHardware>();
        if (oben == null) { return alle; }
        foreach (IHardware geraet in oben)
        {
            if (geraet == null) { continue; }
            alle.Add(geraet);
            try
            {
                alle.AddRange(neueAlle(geraet.SubHardware));
            }
            catch (Exception) { }
        }
        return alle;
    }

    // ---------------------------------------------------------------- Auskunft

    private static bool istErhoeht()
    {
        try
        {
            WindowsIdentity wer = WindowsIdentity.GetCurrent();
            return new WindowsPrincipal(wer).IsInRole(WindowsBuiltInRole.Administrator);
        }
        catch (Exception) { return false; }
    }

    // Die Fuehler im Prozessor haelt Windows hinter einem Kernel-Treiber
    // (PawnIO) zurueck. Ob er auf diesem Rechner ueberhaupt installiert ist,
    // weiss die Bibliothek selbst - und diese Auskunft ist der Unterschied
    // zwischen "leg dir erst eine Messhilfe zu" und "dieser Rechner hat keinen
    // Treiber dafuer".
    private static bool treiberDa()
    {
        try { return LibreHardwareMonitor.PawnIo.PawnIo.IsInstalled; }
        catch (Exception) { return false; }
    }

    private static string treiberFassung()
    {
        try
        {
            Version fassung = LibreHardwareMonitor.PawnIo.PawnIo.Version;
            return fassung == null ? "" : fassung.ToString();
        }
        catch (Exception) { return ""; }
    }

    private static string bibliothekFassung()
    {
        try { return typeof(Computer).Assembly.GetName().Version.ToString(); }
        catch (Exception) { return ""; }
    }

    // ------------------------------------------------------- winzige Hilfsdienste

    private static long epochSekunden()
    {
        return (long)(DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0,
                                                     DateTimeKind.Utc)).TotalSeconds;
    }

    private static string wahr(bool wert)
    {
        return wert ? "true" : "false";
    }

    // Ein Textwert mit Anfuehrungszeichen, alles Nicht-7-Bit als \uXXXX. Ein
    // Geraetename mit einem " darin darf die ganze Zeile nicht zerstoeren.
    private static string text(string wert)
    {
        if (wert == null) { return "\"\""; }
        StringBuilder bau = new StringBuilder(wert.Length + 2);
        bau.Append('"');
        for (int i = 0; i < wert.Length; i++)
        {
            char c = wert[i];
            if (c == '"') { bau.Append("\\\""); }
            else if (c == '\\') { bau.Append("\\\\"); }
            else if (c == '\b') { bau.Append("\\b"); }
            else if (c == '\f') { bau.Append("\\f"); }
            else if (c == '\n') { bau.Append("\\n"); }
            else if (c == '\r') { bau.Append("\\r"); }
            else if (c == '\t') { bau.Append("\\t"); }
            else if (c < ' ' || c >= 127)
            {
                bau.Append("\\u");
                bau.Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
            }
            else { bau.Append(c); }
        }
        bau.Append('"');
        return bau.ToString();
    }

    // {"art":"...","schluessel":wert,...} - Zahlen und wahr/falsch stehen nackt
    // in der Zeile, Text kommt fertig mit Anfuehrungszeichen aus text().
    private static string zeile(string art, params string[] paar)
    {
        StringBuilder bau = new StringBuilder("{");
        if (art != null)
        {
            bau.Append(text("art"));
            bau.Append(':');
            bau.Append(text(art));
        }
        for (int i = 0; i + 1 < paar.Length; i += 2)
        {
            if (bau.Length > 1) { bau.Append(','); }
            bau.Append(text(paar[i]));
            bau.Append(':');
            bau.Append(paar[i + 1]);
        }
        bau.Append('}');
        return bau.ToString();
    }

    private static string zeileMitListe(string art, string schluessel1, long wert1,
                                        string schluessel2, string eintrag)
    {
        StringBuilder bau = new StringBuilder("{");
        bau.Append(text("art"));
        bau.Append(':');
        bau.Append(text(art));
        bau.Append(',');
        bau.Append(text(schluessel1));
        bau.Append(':');
        bau.Append(wert1.ToString(CultureInfo.InvariantCulture));
        bau.Append(',');
        bau.Append(text(schluessel2));
        bau.Append(":[");
        bau.Append(eintrag);
        bau.Append("]}");
        return bau.ToString();
    }
}

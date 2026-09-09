"""
Prueft, ob aus einer eingefuegten Adresse wieder das Muster wird.

Der Prueffstein steht im Projekt: sync-images.sh traegt neun von Hand
geschriebene Muster mit {version}. Setzt man dort eine Ausgabe ein und
laesst die Erkennung das Muster zurueckgewinnen, muss dasselbe
herauskommen. Damit prueft dieser Test nicht gegen meine Vorstellung
davon, wie Adressen aussehen, sondern gegen die Adressen, die dieser
Server wirklich benutzt.
"""
import re
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "webui"))

import muster  # noqa: E402

fehler = []


def pruefe(bedingung, text):
    print(("  OK   " if bedingung else "  FAIL ") + text)
    if not bedingung:
        fehler.append(text)


# --------------------------------------------------------------------------
print("Muster aus sync-images.sh zurueckgewinnen")
# --------------------------------------------------------------------------
# Je Quelle eine Ausgabe, wie sie dort wirklich vorkommt.
AUSGABEN = {
    "UBUNTU_ISO_URL": "26.04",
    "DEBIAN_LIVE_ISO_URL": "13.6.0",
    "FEDORA_URL": "44",
    "LEAP_URL": "16.1",
    "SYSRESC_ISO_URL": "13.02",
    "GPARTED_ISO_URL": "1.8.1-3",
    "CLONEZILLA_ISO_URL": "3.3.3-15",
    "MEMTEST_ZIP_URL": "8.10",
}

# Debian steht mit Absicht nicht in der Liste: Sein Netz-Installer liegt
# unter "dists/trixie/", und ein Wort ist keine Ausgabe, die sich erkennen
# liesse. Der Fall wird weiter unten eigens geprueft -- er muss nichts
# finden, statt etwas zu raten.
skript = (PROJ / "setup" / "sync-images.sh").read_text(encoding="utf-8")
gefunden = dict(re.findall(r'^([A-Z_]+)="(https?://[^"]*\{version\}[^"]*)"',
                           skript, re.M))
pruefe(len(gefunden) >= 9, f"{len(gefunden)} Muster im Skript gefunden")

for name, ausgabe in AUSGABEN.items():
    vorlage = gefunden.get(name)
    if not vorlage:
        pruefe(False, f"{name} steht nicht mehr im Skript")
        continue
    adresse = vorlage.replace("{version}", ausgabe)
    befund = muster.erkenne(adresse)
    pruefe(befund is not None and befund["muster"] == vorlage,
           f"{name}: {ausgabe} -> "
           + (befund["muster"] if befund else "nichts erkannt")
           + ("" if befund and befund["muster"] == vorlage
              else f"\n         erwartet: {vorlage}"))
    if befund:
        pruefe(befund["version"] == ausgabe,
               f"{name}: Ausgabe gelesen als {befund['version']}")

# --------------------------------------------------------------------------
print("\nWas nicht zu erkennen ist, wird nicht geraten")
# --------------------------------------------------------------------------
debian = gefunden.get("DEBIAN_URL", "")
adresse = debian.replace("{version}", "trixie")
befund = muster.erkenne(adresse)
# In der Adresse steht "installer-amd64" -- maskiert, also keine Ausgabe.
# Bleibt nichts uebrig, und genau das soll herauskommen.
pruefe(befund is None,
       "Debians Codename ergibt keinen Vorschlag"
       + ("" if befund is None else f" -- kam aber {befund['version']}"))

# --------------------------------------------------------------------------
print("\nDie Architektur zaehlt nicht als Ausgabe")
# --------------------------------------------------------------------------
for adresse, verboten in (
    ("https://beispiel.de/pub/linux/releases/44/Everything/x86_64/os/", "64"),
    ("https://beispiel.de/abbild-3.21-amd64.iso", "64"),
    ("https://beispiel.de/v8.10/mt86plus_8.10.binaries.zip", "86"),
    ("https://beispiel.de/images/aarch64/9.5/netboot/", "64"),
):
    werte = [k["version"] for k in muster.kandidaten(adresse)]
    pruefe(verboten not in werte,
           f"{verboten} gilt nicht als Ausgabe in {adresse.rsplit('/', 2)[-2]}"
           + (f" -- gefunden: {werte}" if verboten in werte else ""))

# --------------------------------------------------------------------------
print("\nAlle Vorkommen werden ersetzt, nicht nur das erste")
# --------------------------------------------------------------------------
befund = muster.erkenne(
    "https://releases.ubuntu.com/26.04/ubuntu-26.04-live-server-amd64.iso")
pruefe(befund is not None and befund["muster"].count("{version}") == 2,
       "Ubuntu: beide Stellen ersetzt"
       + ("" if befund is None else f" -- {befund['muster']}"))
pruefe(befund is not None and befund["stellen"] == 2,
       "... und die Karte kann sagen, dass es zwei sind")

# --------------------------------------------------------------------------
print("\nJeder Vorschlag sagt, woran er erkannt wurde")
# --------------------------------------------------------------------------
befund = muster.erkenne(
    "https://download.opensuse.org/distribution/leap/16.1/repo/oss/boot/x86_64/loader")
pruefe(befund is not None and "Pfadabschnitt" in befund["warum"],
       "Leap: als ganzer Pfadabschnitt erkannt"
       + ("" if befund is None else f" -- {befund['warum']}"))
befund = muster.erkenne(
    "https://fastly-cdn.system-rescue.org/releases/13.02/systemrescue-13.02-amd64.iso")
pruefe(befund is not None and "2-mal" in befund["warum"],
       "SystemRescue: als doppeltes Vorkommen erkannt"
       + ("" if befund is None else f" -- {befund['warum']}"))

# --------------------------------------------------------------------------
print("\nMehrdeutiges wird angeboten, nicht entschieden")
# --------------------------------------------------------------------------
# Zwei Zahlen, beide denkbar: die Ausgabe im Verzeichnis und eine Nummer
# im Dateinamen. Die Karte soll beide zeigen koennen.
alle = muster.kandidaten("https://beispiel.de/rel/7.4/abbild-2-amd64.iso")
pruefe(len(alle) >= 2, f"beide Zahlen stehen zur Wahl: {[k['version'] for k in alle]}")
pruefe(alle and alle[0]["version"] == "7.4",
       "... und die mit Unternummer und Pfadabschnitt steht vorn")

# --------------------------------------------------------------------------
print(chr(10) + "Host und Port sind keine Ausgabe")
# --------------------------------------------------------------------------
# Beim Bauen aufgefallen, und kein Sonderfall: Ein Spiegel im eigenen
# Netz heisst "http://192.168.178.30:8080/...", und darin stecken zwei
# Zahlenfolgen, die wie Ausgaben aussehen.
werte = [k["version"] for k in muster.kandidaten(
    "http://192.168.178.30:8080/spiegel/alpine/v3.22/netboot/")]
pruefe("192.168.178.30" not in werte and "8080" not in werte,
       "IP und Port bleiben aussen vor: " + str(werte))
pruefe(werte and werte[0] == "3.22",
       "... und die Ausgabe aus dem Pfad steht vorn: " + str(werte))

# --------------------------------------------------------------------------
print(chr(10) + "Die Gegenprobe beim Anbieter")
# --------------------------------------------------------------------------
# Erkennen allein ist eine Vermutung. Beweisen laesst sie sich nur dort, wo
# die Ausgaben liegen -- findet sich neben der eingefuegten auch ihre
# Nachbarschaft, stimmt das Muster. Der Anbieter ist hier nachgebaut: Der
# Test soll ohne Netz laufen und nicht davon abhaengen, was Alpine heute
# gerade veroeffentlicht.
import http.server
import threading

import quellen  # noqa: E402

INDEX = (b'<html><body>'
         b'<a href="../">..</a>'
         b'<a href="v3.21/">v3.21/</a>'
         b'<a href="v3.22/">v3.22/</a>'
         b'<a href="v3.23/">v3.23/</a>'
         b'<a href="latest-stable/">latest-stable/</a>'
         b'<a href="sha256sums.txt">sha256sums.txt</a>'
         b'</body></html>')
DATEIEN = (b'<html><body>'
           b'<a href="werkzeug-1.2.iso">werkzeug-1.2.iso</a>'
           b'<a href="werkzeug-1.3.iso">werkzeug-1.3.iso</a>'
           b'</body></html>')


class Anbieter(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        inhalt = DATEIEN if self.path.startswith("/dateien") else INDEX
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(inhalt)))
        self.end_headers()
        self.wfile.write(inhalt)

    def log_message(self, *_):
        pass


dienst = http.server.HTTPServer(("127.0.0.1", 0), Anbieter)
threading.Thread(target=dienst.serve_forever, daemon=True).start()
basis = "http://127.0.0.1:%d" % dienst.server_address[1]

# Der ganze Weg: eingefuegte Adresse -> Muster -> Nachbarn beim Anbieter.
eingefuegt = basis + "/alpine/v3.22/releases/netboot/"
befund = muster.erkenne(eingefuegt)
pruefe(befund is not None and befund["muster"].endswith("/v{version}/releases/netboot/"),
       "Alpine-Adresse ergibt ein Muster"
       + ("" if befund is None else " -- " + befund["muster"].replace(basis, "")))

probe = quellen.probe_muster(befund["muster"]) if befund else {}
pruefe(probe.get("ok"), "die Gegenprobe kommt beim Anbieter an: "
       + str(probe.get("meldung", "")))
pruefe(set(probe.get("gefunden", [])) >= {"3.21", "3.22", "3.23"},
       "sie findet die Nachbarausgaben: " + str(probe.get("gefunden")))
pruefe("latest-stable" not in probe.get("gefunden", []),
       "und nimmt kein Wort dafuer, das keine Ausgabe ist")

# Und derselbe Weg dort, wo die Ausgabe im Dateinamen steht.
befund = muster.erkenne(basis + "/dateien/werkzeug-1.2.iso")
probe = quellen.probe_muster(befund["muster"]) if befund else {}
pruefe(set(probe.get("gefunden", [])) >= {"1.2", "1.3"},
       "auch aus Dateinamen: " + str(probe.get("gefunden")))

# Ohne Ausgabe im Muster ist nichts zu proben -- und das wird gesagt,
# statt eine leere Liste zu liefern, die wie "nichts gefunden" aussaehe.
ohne = quellen.probe_muster(basis + "/irgendwas/")
pruefe(not ohne["ok"] and "keine Ausgabe" in ohne["meldung"],
       "ohne {version} sagt die Probe, woran es liegt: " + ohne["meldung"])

dienst.shutdown()

print()
if fehler:
    print(f"{len(fehler)} Test(s) fehlgeschlagen:")
    for f in fehler:
        print("  -", f)
    sys.exit(1)
print("Adressen werden richtig in Muster zurueckverwandelt.")

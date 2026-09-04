"""
Der Fehlerbericht -- was dieser Server über sich sagen kann.

**Wozu.** Meldet jemand einen Fehler, beginnt die Antwort sonst mit einer
Rueckfrage: worauf laeuft der Server, welche Fassung, welche Dienste in
welcher Version? Jede dieser Rueckfragen kostet einen Tag. Der Satz, an
dem der Wert dieses Berichts haengt, steht in A-020: **dnsmasq 2.89 und
2.90 verhalten sich beim proxyDHCP unterschiedlich.**

**Zwei Bloecke, und sie sind verschieden.**

    Technik    Auf jedem Server dieselbe Art Angabe: Distribution,
               Kernel, Architektur, Virtualisierung, die Dienste mit
               ihren Versionen, der Stand der Anwendung. Nichts davon
               gehoert einem Betrieb.
    Umgebung   Traegt Namen und Zahlen aus einem fremden Betrieb:
               Ablageorte, wieviel wo liegt, wieviele Rechner bekannt
               sind, der Auszug aus dem Journal.

**Deshalb ist der zweite abwaehlbar und der erste nicht.**

**Der Server verschickt nichts.** Er erzeugt Text, der Betreiber liest ihn
und traegt ihn weiter -- an `kontakt@exmig.de`. Das ist keine Bequemlichkeit,
die noch fehlt, sondern die Entscheidung: Eine Mail aus dem Server heraus
braeuchte SMTP-Zugangsdaten auf einem Bootserver und eine Ausgangsverbindung
aus einem Netz, das oft keine hat. **Die Zustimmung ist, dass er den Text
sieht** -- nicht ein Haken davor.

**Live gelesen, nichts gespeichert.** Ein `apt upgrade` aendert die
Versionen ohne unser Zutun; ein Bericht aus einer Datei waere die zweite
Wahrheit. Und erzeugt wird er erst auf Klick: Er kostet ein halbes Dutzend
Aufrufe nach draussen (dpkg, systemd, journalctl), und die haben auf einer
Seite nichts zu suchen, die man oeffnet, um einen Pfad nachzusehen.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

import dienste
import versionsstand

ZEITLIMIT = 5.0

# Was im Journal landet, wenn jemand einen Fehler meldet: die Anwendung
# selbst. Die anderen Dienste haben ihre eigene Seite (Protokoll), und
# drei Journale machen den Bericht doppelt so lang und halb so lesbar.
JOURNAL_EINHEIT = "pxeweb"
JOURNAL_ZEILEN = 40

# Geholt werden viel mehr Zeilen, als am Ende dastehen -- weil die meisten
# weggeworfen werden.
#
# **Der Grund stand im allerersten Bericht:** Die Befunde frischen sich
# alle zehn Sekunden auf, das sind sechs Zugriffe je Minute. Vierzig
# Zeilen Journal deckten damit knapp sieben Minuten ab und enthielten
# nichts als "GET /befunde.html". Eine echte Meldung waere darin nie zu
# finden gewesen.
JOURNAL_HOLEN = 500
_ZUGRIFF = re.compile(r'"(GET|POST|HEAD) [^"]*" [0-9]{3}')


def _lauf(befehl: list[str]) -> str:
    """Einen Befehl ausfuehren und seine Ausgabe holen -- oder "" ."""
    try:
        ergebnis = subprocess.run(befehl, capture_output=True, text=True,
                                  timeout=ZEITLIMIT, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (ergebnis.stdout or "").strip()


def _distribution() -> str:
    """Name und Version aus /etc/os-release."""
    werte = {}
    try:
        for zeile in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            schluessel, trenner, wert = zeile.partition("=")
            if trenner:
                werte[schluessel.strip()] = wert.strip().strip('"')
    except OSError:
        return ""
    return werte.get("PRETTY_NAME") or werte.get("NAME", "")


def _dienstversionen() -> list[tuple[str, str]]:
    """Die Pakete hinter den Diensten, mit Version -- in EINEM Aufruf.

    Ein dpkg-query je Dienst waere fuenf Prozessstarts fuer eine Zeile
    Ausgabe. Fehlt ein Paket, laesst dpkg die Zeile weg; der Dienst steht
    dann mit "nicht installiert" da statt gar nicht -- gerade das ist eine
    Auskunft.
    """
    # Je Dienst mehrere moegliche Pakete, in der Reihenfolge des Zutrauens.
    #
    # **nginx war im ersten Bericht leer**, weil dort "nginx-core" stand
    # und Debian das Paket kennt, ohne dass es installiert sein muss --
    # dpkg-query gibt dann eine Zeile mit leerer Version aus. Gefragt wird
    # deshalb nach mehreren Namen, und genommen wird der erste mit einer
    # Version. Eine leere Version ist keine Auskunft.
    pakete = {
        "nginx": ["nginx-core", "nginx-light", "nginx-full", "nginx"],
        "dnsmasq": ["dnsmasq", "dnsmasq-base"],
        "nfs-server": ["nfs-kernel-server"],
        "smbd": ["samba"],
    }
    alle = sorted({name for namen in pakete.values() for name in namen})
    ausgabe = _lauf(["dpkg-query", "-W", "-f=${Package} ${Version}\n", *alle])
    gefunden = {}
    for zeile in ausgabe.splitlines():
        name, _, version = zeile.partition(" ")
        if name and version.strip():
            gefunden[name] = version.strip()
    zeilen_aus = []
    for dienst, namen in pakete.items():
        treffer = "nicht installiert"
        for n in namen:
            if n in gefunden:
                # Der Paketname nur dann in Klammern, wenn er etwas sagt:
                # Er soll heissen "gefunden unter einem anderen Namen als
                # erwartet". Heisst das Paket wie der Dienst, ist die
                # Klammer Rauschen -- "nginx 1.26 (nginx)".
                treffer = gefunden[n]
                if n != namen[0] and n != dienst:
                    treffer += f" ({n})"
                break
        zeilen_aus.append((dienst, treffer))
    return zeilen_aus


def technik() -> list[tuple[str, str]]:
    """Was auf jedem Server dieselbe Art Angabe ist."""
    zeilen = [
        ("MARLEI Boot", versionsstand.kurz() or "kein Stempel (nicht über install.sh installiert)"),
        ("Distribution", _distribution() or "unbekannt"),
        ("Kernel", platform.release() or "unbekannt"),
        ("Architektur", platform.machine() or "unbekannt"),
        ("Virtualisierung", _lauf(["systemd-detect-virt"]) or "keine oder nicht feststellbar"),
        ("Python", platform.python_version()),
    ]
    zeilen.extend(_dienstversionen())
    return zeilen


def umgebung(assets_dir: Path, zusatz: list[tuple[str, str]] | None = None
             ) -> list[tuple[str, str]]:
    """Was Namen und Zahlen aus einem fremden Betrieb traegt."""
    zeilen: list[tuple[str, str]] = []
    laufzeit = _lauf(["uptime", "-p"])
    if laufzeit:
        zeilen.append(("Laufzeit", laufzeit))
    zeilen.append(("Ablage der Abbilder", str(assets_dir)))
    belegung = dienste.platz(assets_dir)
    if belegung:
        gb = 1024 ** 3
        zeilen.append(("Platte", "%d GB belegt, %d GB frei (%d %%)" % (
            belegung["belegt"] // gb, belegung["frei"] // gb,
            belegung.get("anteil", 0))))
    zeilen.extend(zusatz or [])
    return zeilen


def journal() -> str:
    """Die letzten Zeilen der Anwendung -- ohne die Zugriffe.

    Ein Zugriffsprotokoll sagt bei einem Fehlerbericht nichts: Dass jemand
    die Seite geoeffnet hat, steht ohnehin fest. Was zaehlt, sind Starts,
    Abbrueche und Ausnahmen -- und die gehen zwischen sechs Zugriffen je
    Minute unter.
    """
    ausgabe = _lauf(["journalctl", "-u", JOURNAL_EINHEIT,
                     "-n", str(JOURNAL_HOLEN), "--no-pager", "-o", "short-iso"])
    if not ausgabe:
        return "(kein Journal lesbar)"
    zeilen = [z for z in ausgabe.splitlines() if not _ZUGRIFF.search(z)]
    if not zeilen:
        return "(nur Zugriffe im Journal, nichts weiter)"
    return "\n".join(zeilen[-JOURNAL_ZEILEN:])


def _block(titel: str, zeilen: list[tuple[str, str]]) -> str:
    breite = max((len(name) for name, _ in zeilen), default=0)
    kopf = titel + "\n" + "-" * len(titel)
    leib = "\n".join("%-*s  %s" % (breite, name, wert) for name, wert in zeilen)
    return kopf + "\n" + leib


def text(assets_dir: Path, mit_umgebung: bool = True,
         zusatz: list[tuple[str, str]] | None = None) -> str:
    """Der ganze Bericht als Text -- so, wie ihn der Betreiber sieht.

    Genau so, wie er ihn sieht: Was hier entsteht, wird angezeigt und
    heruntergeladen. Zwei Wege, die auseinanderlaufen koennten, gibt es
    nicht.
    """
    teile = ["MARLEI Boot -- Fehlerbericht",
             "=" * 28,
             "",
             _block("Technik", technik())]
    if mit_umgebung:
        teile += ["", _block("Umgebung", umgebung(assets_dir, zusatz)),
                  "", "Journal (pxeweb, letzte %d Zeilen)" % JOURNAL_ZEILEN,
                  "-" * 40, journal()]
    teile += ["", "Bitte an kontakt@exmig.de schicken."]
    return "\n".join(teile) + "\n"

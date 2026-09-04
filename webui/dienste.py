"""
Laufen die Dienste? -- fuer die Uebersichtsseite.

Bisher stand die Antwort nur per SSH zur Verfuegung ("systemctl is-active
..."), obwohl es die erste Frage ist, wenn etwas nicht startet. Hier wird
dieselbe Auskunft eingeholt und angezeigt.

Bewusst zurueckhaltend: die Anwendung fragt nur nach dem Zustand, sie
startet und stoppt nichts. Wer einen Dienst neu starten will, tut das auf
dem Server -- eine Weboberflaeche ohne Anmeldung soll keine Dienste
umschalten koennen.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

# In dieser Reihenfolge auch angezeigt.
EINHEITEN = ["nginx", "dnsmasq", "pxeweb", "nfs-server", "smbd"]

WOFUER = {
    "nginx": "liefert Kernel, Initrd und die Weboberflaeche aus",
    "dnsmasq": "beantwortet PXE-Anfragen (proxyDHCP) und liefert iPXE per TFTP",
    "pxeweb": "diese Anwendung",
    "nfs-server": "haengt grosse Live-Systeme beim Client ein",
    "smbd": "gibt die Windows-Installationsquellen frei (nur lesend)",
}

# Die Abfrage kostet einen Prozessaufruf. Beim Aktualisieren der Seite im
# Sekundentakt waere das Verschwendung -- ein paar Sekunden alt reicht.
_CACHE: dict = {"zeit": 0.0, "werte": {}}
_CACHE_SEKUNDEN = 10


def _frag_systemd() -> dict[str, str]:
    """Zustand aller Einheiten in einem Aufruf holen.

    "systemctl is-active" gibt je Einheit eine Zeile aus und einen
    Rueckgabewert ungleich null, sobald eine davon nicht laeuft -- die
    Ausgabe ist trotzdem vollstaendig und genau die, die wir brauchen.
    """
    try:
        lauf = subprocess.run(
            ["systemctl", "is-active", *EINHEITEN],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Kein systemd erreichbar (etwa beim Entwickeln auf einem anderen
        # System). Dann lieber "unbekannt" sagen als etwas zu behaupten.
        return {}
    zeilen = lauf.stdout.split()
    return {name: zeilen[i] if i < len(zeilen) else "unbekannt"
            for i, name in enumerate(EINHEITEN)}


def zustaende() -> list[dict]:
    jetzt = time.monotonic()
    if jetzt - _CACHE["zeit"] > _CACHE_SEKUNDEN:
        _CACHE["werte"] = _frag_systemd()
        _CACHE["zeit"] = jetzt
    werte = _CACHE["werte"]
    return [
        {
            "name": name,
            "zustand": werte.get(name, "unbekannt"),
            "laeuft": werte.get(name) == "active",
            "wofuer": WOFUER.get(name, ""),
        }
        for name in EINHEITEN
    ]


# Ab wann der Platz knapp wird, in Prozent. Der Balken auf Server Health
# faerbt sich ab KNAPP. Zwei Schwellen an zwei Stellen liefen frueher oder
# spaeter auseinander -- dann sagte der Balken etwas anderes als die Karte;
# deshalb kommen beide bis heute von hier.
KNAPP = 75
VOLL = 90

# Die eigentliche Frage ist nicht, wie voll die Platte ist, sondern ob der
# Platz fuer das naechste Abbild reicht. Ein Prozentsatz beantwortet sie
# nur auf kleinen Platten: Auf 5 TB meldet sich VOLL bei 500 GB frei --
# Platz fuer Dutzende Abbilder. Wer diese Warnung eine Woche lang zu
# Unrecht sieht, liest sie danach nicht mehr.
#
# Gewarnt wird deshalb, wenn frei weniger ist als das groesste Abbild, das
# hier schon liegt -- mindestens aber SOCKEL, sonst bliebe ein frischer
# Server ohne Abbilder ungewarnt.
#
# **Und nur noch daran.** Der Prozentsatz sollte als zweite Bedingung
# bleiben, damit auch die kleine Platte versorgt ist; beim Aufschreiben der
# Tests zeigte sich, dass er das Gegenteil tut. Auf einer kleinen Platte
# ist die Reserve die strengere der beiden (9 GB frei sind auf 20 GB schon
# 55 % belegt), auf einer grossen holt der Prozentsatz genau den Fehlalarm
# zurueck, dessentwegen diese Aufgabe entstand -- 5 TB, 500 GB frei, Platz
# fuer Dutzende Abbilder, und trotzdem eine gelbe Karte.
#
# KNAPP und VOLL faerben weiterhin den Balken auf Server Health: Die Farbe
# sagt, wie voll es ist, die Karte sagt, ob es noch fuer ein Abbild reicht.
# Das sind zwei Fragen, und erst seit sie getrennt sind, beantwortet jede
# ihre eigene.
SOCKEL = 8 * 1024 ** 3
# Dieselbe Luft wie isoscan.platz_reicht(): ein Gigabyte, damit beim
# Entpacken nichts volllaeuft.
LUFT = 1024 ** 3

# Das groesste Abbild, das hier liegt -- gemerkt, nicht gesucht.
#
# Suchen waere zu teuer: Ein Befund entsteht auf JEDER Seite, und ein
# Verzeichnis mit ausgepacktem Abbild hat leicht 50.000 Dateien. Gemessen
# wird ohnehin schon, wenn jemand Server Health oder Systeme aufruft --
# dort meldet app.py die groesste Belegung hierher.
#
# Solange niemand hingesehen hat, gilt der SOCKEL. Und nach dem Loeschen
# eines grossen Abbilds steht die Zahl zu hoch, bis eine der beiden Seiten
# wieder aufgerufen wird: Das warnt zu frueh, nie zu spaet.
_GROESSTES: dict = {"bytes": 0}


def merke_groesstes_abbild(bytes_: int) -> None:
    """Was die Belegungsrechnung als groesste Ablage gesehen hat."""
    _GROESSTES["bytes"] = max(0, int(bytes_))


def groesstes_abbild() -> int:
    return _GROESSTES["bytes"]


def reserve() -> int:
    """Wieviel frei bleiben muss, damit das naechste Abbild noch passt."""
    return max(_GROESSTES["bytes"], SOCKEL) + LUFT


def platz_knapp(belegung: dict) -> bool:
    """Die eine Regel: Reicht der Platz noch fuer ein weiteres Abbild?

    Ohne lesbare Belegung ist die Antwort nein, nicht ja -- nichts zu
    wissen ist kein Alarm.
    """
    if not belegung:
        return False
    return belegung.get("frei", 0) < reserve()


def platz(pfad: Path) -> dict:
    """Belegung des Datentraegers, auf dem die Abbilder liegen."""
    try:
        nutzung = shutil.disk_usage(pfad)
    except OSError:
        return {}
    return {
        "gesamt": nutzung.total,
        "belegt": nutzung.used,
        "frei": nutzung.free,
        "anteil": round(nutzung.used / nutzung.total * 100) if nutzung.total else 0,
    }

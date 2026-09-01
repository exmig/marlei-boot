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
# faerbt sich ab KNAPP und warnt ab VOLL; die gelbe Seitenkarte haengt an
# derselben Zahl. Zwei Schwellen an zwei Stellen liefen frueher oder
# spaeter auseinander -- dann sagte der Balken etwas anderes als die Karte.
KNAPP = 75
VOLL = 90


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

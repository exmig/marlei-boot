"""
Wo liegt was auf dem Server -- fuer die Konfigurationsseite.

Die Anwendung kennt ihre Ablageorte aus /etc/pxeweb.env, aber nachsehen
konnte man bisher nur per SSH. Beim Suchen nach einer fehlenden Datei ist
genau das die erste Frage: liegt sie da, wo die Anwendung sie erwartet?

Nur lesen, nichts aendern. Einstellungen werden weiterhin in
/etc/pxeweb.env gepflegt und mit einem Neustart des Dienstes wirksam --
eine Weboberflaeche ohne Anmeldung soll die Ablageorte des Servers nicht
verschieben koennen.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

# Ein Verzeichnis mit ausgepackten Abbildern hat leicht 50.000 Dateien.
# Das einmal je Seitenaufruf durchzugehen waere Verschwendung.
_CACHE: dict = {"zeit": 0.0, "werte": {}}
_CACHE_SEKUNDEN = 30


def vergiss() -> None:
    """Das Gemerkte wegwerfen -- nach jedem Eingriff in die Ablage.

    Dreissig Sekunden alte Zahlen sind fuer eine Uebersicht in Ordnung.
    Direkt nach dem Loeschen sind sie es nicht: Die Seite zeigte dann noch
    die Belegung von Dateien, die es nicht mehr gibt, und das sieht aus,
    als haette das Loeschen nicht funktioniert.
    """
    _CACHE["werte"] = {}
    _CACHE["zeit"] = 0.0


def _messen(pfad: Path) -> dict:
    bytes_, dateien = 0, 0
    for ordner, _, namen in os.walk(pfad):
        for name in namen:
            try:
                bytes_ += (Path(ordner) / name).stat().st_size
                dateien += 1
            except OSError:
                pass
    return {"bytes": bytes_, "dateien": dateien}


def groesse(pfad: Path) -> dict:
    """Belegung eines Verzeichnisses, fuer kurze Zeit gemerkt."""
    schluessel = str(pfad)
    jetzt = time.monotonic()
    if jetzt - _CACHE["zeit"] > _CACHE_SEKUNDEN:
        _CACHE["werte"] = {}
        _CACHE["zeit"] = jetzt
    if schluessel not in _CACHE["werte"]:
        _CACHE["werte"][schluessel] = _messen(pfad) if pfad.is_dir() else {
            "bytes": pfad.stat().st_size if pfad.is_file() else 0,
            "dateien": 1 if pfad.is_file() else 0,
        }
    return _CACHE["werte"][schluessel]


def datei(pfad: Path) -> dict:
    """Gibt es diese Datei, und wie gross ist sie?

    Bewusst nur ein stat() je Datei und keine Verzeichnisgroesse: die
    Eintraege sind schnell zweistellig, und ein ausgepacktes Abbild zu
    durchlaufen wuerde die Seite fuer nichts aufhalten.
    """
    try:
        stat = pfad.stat()
        return {"da": True, "bytes": stat.st_size}
    except OSError:
        return {"da": False, "bytes": 0}


def zustand(pfad: Path) -> dict:
    """Gibt es den Ort, und darf der Dienst dort schreiben?"""
    da = pfad.exists()
    return {
        "da": da,
        "schreibbar": da and os.access(pfad, os.W_OK),
        "art": "Verzeichnis" if pfad.is_dir() else ("Datei" if pfad.is_file() else ""),
    }

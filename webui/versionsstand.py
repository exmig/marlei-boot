"""
Welcher Stand dieser Anwendung hier laeuft.

Die Frage stellt sich in zwei Lagen: beim Betreiber ("bin ich aktuell?")
und bei einer Fehlermeldung von jemand anderem ("welcher Stand war das?").
Beide Male hilft nur eine Angabe, die sich nachvollziehen laesst -- eine
handgepflegte Nummer waere eine zweite Wahrheit neben Git und liefe
frueher oder spaeter daneben.

**Warum eine Datei und nicht Git selbst?** /opt/pxeweb ist eine
rsync-Kopie des Projektordners, ohne .git. Die Anwendung kann Git also gar
nicht fragen -- sie findet nur vor, was install.sh beim Kopieren
hinterlassen hat. Wer das uebersieht, baut die Abfrage hier ein und
wundert sich, dass sie auf dem Server nichts findet.

Fehlt die Datei, wird nicht geraten: Dann laeuft die Anwendung aus einem
Projektordner (Entwicklung) oder wurde von Hand kopiert, und die Seite
sagt genau das. Lieber keine Angabe als eine erfundene.
"""

from __future__ import annotations

import os
from pathlib import Path

# Geschrieben von setup/install.sh, gleich nach dem rsync. Der Pfad laesst
# sich umbiegen -- die Tests legen sich eine eigene Datei an.
DATEI = Path(os.environ.get("PXE_VERSION_DATEI",
                            Path(__file__).resolve().parent / "VERSION"))

# Die Datei aendert sich nur bei einer Installation, wird aber auf jeder
# Einrichtungsseite gebraucht. Gemerkt wird deshalb ueber den Zeitstempel:
# neu geschrieben heisst neu gelesen, ohne dass jemand daran denken muss.
_CACHE: dict = {"stand": None, "werte": {}}

# Was install.sh schreibt. Alles andere in der Datei wird ignoriert --
# sonst waere jede spaetere Ergaenzung dort ein Fehler hier.
FELDER = ("stand", "commit", "zweig", "installiert")


def _lies() -> dict:
    try:
        mtime = DATEI.stat().st_mtime
    except OSError:
        return {}
    if _CACHE["stand"] == mtime:
        return _CACHE["werte"]

    werte: dict = {}
    try:
        for zeile in DATEI.read_text(encoding="utf-8").splitlines():
            schluessel, trenner, wert = zeile.partition("=")
            if trenner and schluessel.strip() in FELDER:
                werte[schluessel.strip()] = wert.strip()
    except OSError:
        return {}

    _CACHE["stand"] = mtime
    _CACHE["werte"] = werte
    return werte


def auskunft() -> dict:
    """Was auf der Einrichtungsseite steht.

    "da" trennt die beiden Faelle, die man sonst verwechselt: Eine leere
    Angabe heisst nicht "Version 0", sondern "hier steht nichts, weil
    diese Anwendung nicht ueber install.sh hierhergekommen ist".
    """
    werte = _lies()
    if not werte.get("stand"):
        return {"da": False, "stand": "", "commit": "", "zweig": "",
                "installiert": "", "datei": str(DATEI)}

    return {
        "da": True,
        "stand": werte.get("stand", ""),
        "commit": werte.get("commit", ""),
        # Ein anderer Zweig als main ist keine Stoerung, aber die haeufigste
        # Erklaerung dafuer, dass jemand etwas anderes sieht als erwartet.
        "zweig": werte.get("zweig", ""),
        "installiert": werte.get("installiert", ""),
        "datei": str(DATEI),
    }


def kurz() -> str:
    """Eine Zeile fuer Kopfzeilen und Fehlermeldungen -- oder leer."""
    return _lies().get("stand", "")

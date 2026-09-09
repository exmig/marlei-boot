"""
sync-images.sh aus der Weboberflaeche anstossen.

Das Skript laedt Kernel, Initrds und Abbilder nach /srv/pxe/assets. Es
braucht dafuer kein root -- es holt mit curl, packt mit bsdtar aus und setzt
Leserechte. Noetig ist nur, dass ihm das Verzeichnis gehoert; darum kuemmert
sich install.sh, und pxeweb.service gibt den Pfad frei.

Drei Dinge sind hier bewusst eng gefasst, weil die Oberflaeche keine
Anmeldung hat:

1. Nur die Komponenten, die das Skript selbst kennt. Die Liste wird aus ihm
   ausgelesen, nicht hier gepflegt -- und was nicht darin steht, wird
   abgewiesen, bevor irgendetwas startet.
2. Immer nur ein Lauf gleichzeitig. Sonst laedt sich der Server bei jedem
   Klick eine weitere Kopie derselben Gigabytes.
3. Die Ausgabe laesst sich mitlesen, damit ein Lauf nicht als schwarzer
   Kasten dasteht.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from collections import deque
from datetime import datetime, timezone

from quellen import skript

# Farbcodes des Skripts -- im Browser waeren sie nur Zeichensalat.
_FARBEN = re.compile(r"\x1b\[[0-9;]*m")

# So viele Zeilen bleiben sichtbar. Ein vollstaendiger Lauf schreibt
# hunderte, alle im Speicher zu halten waere unnoetig.
MAX_ZEILEN = 400

_riegel = threading.Lock()
_lauf: dict = {
    "laeuft": False,
    "komponenten": [],
    "begonnen": "",
    "beendet": "",
    "ergebnis": "",
    "zeilen": deque(maxlen=MAX_ZEILEN),
}


def komponenten() -> list[str]:
    """Was das Skript zu holen weiss -- ausgelesen, nicht hier gepflegt."""
    pfad = skript()
    if pfad is None:
        return []
    try:
        text = pfad.read_text(encoding="utf-8")
    except OSError:
        return []
    treffer = re.search(r"^COMPONENTS=\(([^)]*)\)", text, re.M)
    return treffer.group(1).split() if treffer else []


def zustand() -> dict:
    return {
        "laeuft": _lauf["laeuft"],
        "komponenten": list(_lauf["komponenten"]),
        "begonnen": _lauf["begonnen"],
        "beendet": _lauf["beendet"],
        "ergebnis": _lauf["ergebnis"],
        "text": "\n".join(_lauf["zeilen"]),
    }


def starte(auswahl: list[str], umgebung: dict | None = None) -> None:
    """Einen Lauf anstossen. Wirft ValueError, wenn etwas nicht stimmt."""
    bekannt = komponenten()
    if not bekannt:
        raise ValueError("sync-images.sh ist nicht auffindbar.")

    gewaehlt = [k for k in auswahl if k]
    # "debian" holt alle Ausgaben, "debian:trixie" nur diese eine. Geprueft
    # wird der Teil vor dem Doppelpunkt -- die Ausgabe kennt nur das
    # Skript, und es sagt selbst, wenn sie nicht taugt.
    unbekannt = [k for k in gewaehlt if k.split(":", 1)[0] not in bekannt]
    if unbekannt:
        raise ValueError("Unbekannte Komponente: " + ", ".join(unbekannt))
    if not gewaehlt:
        raise ValueError("Nichts ausgewaehlt.")

    with _riegel:
        if _lauf["laeuft"]:
            raise ValueError("Es laeuft bereits ein Abgleich.")
        _lauf.update(laeuft=True, komponenten=gewaehlt, ergebnis="", beendet="",
                     begonnen=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        _lauf["zeilen"].clear()

    threading.Thread(target=_arbeite, args=(gewaehlt, umgebung or {}),
                     daemon=True).start()


def _merke(zeile: str) -> None:
    _lauf["zeilen"].append(_FARBEN.sub("", zeile.rstrip()))


def _arbeite(gewaehlt: list[str], umgebung: dict) -> None:
    pfad = skript()
    _merke(f"$ {pfad} {' '.join(gewaehlt)}")
    try:
        prozess = subprocess.Popen(
            [str(pfad), *gewaehlt],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env={**os.environ, **umgebung},
        )
        # Zeile fuer Zeile mitlesen, statt am Ende alles auf einmal -- sonst
        # steht die Seite bei einem Download minutenlang leer da.
        for zeile in prozess.stdout:
            _merke(zeile)
        code = prozess.wait()
        ergebnis = "fertig" if code == 0 else f"mit Fehlern beendet (Code {code})"
    except Exception as fehler:
        _merke(str(fehler))
        ergebnis = "nicht ausfuehrbar"

    with _riegel:
        _lauf.update(laeuft=False, ergebnis=ergebnis,
                     beendet=datetime.now(timezone.utc).isoformat(timespec="seconds"))

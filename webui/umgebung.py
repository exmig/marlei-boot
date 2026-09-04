"""
Passt die Umgebung noch zu dem Code, der hier laeuft?

**Der Code weiss, was er braucht -- die Umgebung sagt, was da ist.**
Der Satz stammt aus B-044 und ist der ganze Trick: Es braucht keinen
gepflegten Katalog von Versionsnummern, sondern nur einen Vergleich
zwischen der Vorlage, die mit dem Code kommt
(`setup/files/pxeweb.env.example`), und dem, was der Dienst tatsaechlich
vorfindet.

**Der Fall vom 30.08.2026, an dem das auffiel:** Mit Samba kamen ein
neues Konto und eine neue Zeile in /etc/pxeweb.env. `update.sh` richtet
so etwas nicht ein, dafuer ist `install.sh` da -- nur stand das nirgends.
Server Health meldete sich gesund, die Anwendung lief, die Freigabe
fehlte, und niemand haette erraten koennen, warum.

**Geprueft werden Namen, keine Werte.** Ein leerer Wert ist eine
Entscheidung (PXE_WOL_BROADCAST etwa darf leer sein); ein fehlender Name
heisst, dass die Datei aelter ist als der Code, der sie liest.

**Verglichen wird Datei gegen Datei, nicht gegen die Prozessumgebung.**
Der erste Entwurf las os.environ -- und meldete auf jedem
Entwicklungsrechner eine unvollstaendige Einrichtung, weil dort niemand
zwoelf PXE_-Variablen setzt. Gibt es keine /etc/pxeweb.env, gibt es auch
nichts zu vergleichen: Dann laeuft die Anwendung aus einem Projektordner,
und das ist kein Mangel.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Was install.sh aus der Vorlage gemacht hat. Der Dienst liest sie beim
# Start ueber systemd; hier wird sie ein zweites Mal gelesen, und zwar als
# Datei -- geprueft wird, was drinsteht, nicht was im Prozess ankam.
DATEI = Path(os.environ.get("PXE_ENV_DATEI", "") or "/etc/pxeweb.env")

# Die Vorlage, die mit dem Code kommt. install.sh spiegelt setup/ nach
# /opt/pxe-setup, dort liegt sie im Betrieb; im Projektordner liegt sie
# neben der Anwendung.
VORLAGE = Path(os.environ.get("PXE_ENV_VORLAGE", "")
               or "/opt/pxe-setup/files/pxeweb.env.example")
_DANEBEN = BASE_DIR.parent / "setup" / "files" / "pxeweb.env.example"

_NAME = re.compile(r"^([A-Z][A-Z0-9_]*)=")


def _vorlage() -> Path | None:
    for pfad in (VORLAGE, _DANEBEN):
        if pfad.is_file():
            return pfad
    return None


def erwartet() -> list[str]:
    """Welche Namen die mitgelieferte Vorlage kennt."""
    pfad = _vorlage()
    return _namen(pfad) if pfad is not None else []


def _namen(pfad: Path) -> list[str]:
    namen = []
    try:
        for zeile in pfad.read_text(encoding="utf-8").splitlines():
            treffer = _NAME.match(zeile.strip())
            if treffer:
                namen.append(treffer.group(1))
    except OSError:
        return []
    return namen


def fehlend() -> list[str]:
    """Was der Code erwartet und in /etc/pxeweb.env nicht steht.

    Leer, wenn es die Datei nicht gibt: Dann laeuft die Anwendung aus
    einem Projektordner und wurde nicht eingerichtet.
    """
    if not DATEI.is_file():
        return []
    vorhanden = set(_namen(DATEI))
    if not vorhanden:
        return []
    return [name for name in erwartet() if name not in vorhanden]

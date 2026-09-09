"""
Journal der Dienste anzeigen -- das, was sonst "journalctl -u ... -f" macht.

Beim Einrichten ist das Mitlesen von dnsmasq das nuetzlichste Werkzeug
ueberhaupt: dort sieht man, ob ein Rechner ueberhaupt anfragt und was ihm
geantwortet wird. Bisher ging das nur ueber SSH.

Zwei Dinge sind hier bewusst eng gefasst:

1. Nur die fuenf Dienste dieses Servers. Es gibt keinen freien Parameter,
   ueber den sich ein beliebiges Journal abrufen liesse -- die Gruppe
   systemd-journal erlaubt dem Dienst zwar mehr, die Weboberflaeche gibt
   davon aber nichts preis.

2. Nur lesen, nur die letzten Zeilen. Kein "-f", stattdessen fragt die
   Seite regelmaessig nach. Ein dauerhaft offener Datenstrom waere fuer
   eine Seite, die man nebenbei offen hat, der falsche Aufwand.
"""

from __future__ import annotations

import subprocess

# Dieselben Einheiten wie in dienste.py -- mehr gibt es hier nicht zu sehen.
ERLAUBT = ["dnsmasq", "nginx", "pxeweb", "nfs-server"]

MAX_ZEILEN = 300


def darf_lesen() -> bool | None:
    """Kommt der Dienst ans Journal fremder Einheiten heran?

    Ohne die Gruppe systemd-journal liefert journalctl fuer fremde
    Einheiten schlicht nichts -- ohne Fehler. Das waere nicht von "noch
    keine Meldungen" zu unterscheiden, deshalb fragen wir vorher nach.

    None heisst: laesst sich hier nicht feststellen (kein Unix).
    """
    try:
        import grp
        import os
    except ImportError:                                # pragma: no cover
        return None
    try:
        eigene = set(os.getgroups())
        for name in ("systemd-journal", "adm", "wheel"):
            try:
                if grp.getgrnam(name).gr_gid in eigene:
                    return True
            except KeyError:
                continue
    except (OSError, AttributeError):                  # pragma: no cover
        return None
    return False


def lies(einheit: str, zeilen: int = 200) -> dict:
    """Die letzten Zeilen einer Einheit holen."""
    if einheit not in ERLAUBT:
        raise ValueError("Unbekannte Einheit: " + einheit)
    zeilen = max(10, min(MAX_ZEILEN, zeilen))

    try:
        lauf = subprocess.run(
            ["journalctl", "-u", einheit, "-n", str(zeilen),
             "--no-pager", "--output=short-iso"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError) as fehler:
        return {"text": "", "meldung": f"journalctl nicht ausfuehrbar: {fehler}"}

    text = lauf.stdout.strip()
    if not text:
        if darf_lesen() is False:
            return {
                "text": "",
                "meldung": "Der Dienst darf das Journal nicht lesen. Auf dem "
                           "Server einmal setup/install.sh laufen lassen -- es "
                           "nimmt das Konto pxeweb in die Gruppe "
                           "systemd-journal auf.",
            }
        return {"text": "", "meldung": "Keine Meldungen vorhanden."}
    return {"text": text, "meldung": ""}

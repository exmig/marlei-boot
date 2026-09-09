"""
Was der Betreiber in der Oberflaeche entscheidet -- neben der Datenbank.

**Zwei Ablagen, und sie unterscheiden sich nicht im Format, sondern
darin, wer sie aendern darf.** In /etc/pxeweb.env steht, *wie dieser
Server aufgesetzt ist*: Ablageorte, Adresse, Zeitgrenzen. Sie wird
**einmal beim Start** gelesen, gehoert root, und der Dienst laeuft als
pxeweb -- er kann dort nicht schreiben, und das ist Absicht.

Hier steht, *wie er betrieben wird*. Dieselbe Ecke, in der schon
freigabe.yaml, gruppen.yaml, kenntnis.yaml und quellen.env liegen: neben
der Datenbank, zur Laufzeit gelesen und geschrieben, ohne Neustart
wirksam.

**Eine eigene Datei und kein Anhaengsel an quellen.env** -- dort stehen
Ausgabenlisten, das ist etwas anderes. Der Offline-Schalter, der noch
kommt, braucht denselben Platz; dann ist er schon da.

Die Werkseinstellung erfasst die Datei von selbst, weil sie in diesem
Verzeichnis aufraeumt.

Warum so: docs/gestaltung.md und mappe/08-entscheidungen.md,
"Wohin der Server nach Aktualisierungen fragt".
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_DB = Path(os.environ.get("PXE_DB", "/var/lib/pxeweb/pxeweb.db"))
DATEI = Path(os.environ.get("PXE_EINSTELLUNGEN", "")
             or _DB.parent / "einstellungen.yaml")

# Was gilt, solange niemand etwas eingestellt hat. Eine fehlende Datei ist
# der Normalfall und kein Mangel: So sieht ein frisch aufgesetzter Server
# aus.
#
#   updatepruefung   Tage zwischen zwei Blicken ins Repository.
#                    0 = nie, 7 = woechentlich, 30 = monatlich.
VORGABEN: dict = {
    "updatepruefung": 7,
}


def _lesen() -> dict:
    try:
        with DATEI.open(encoding="utf-8") as fh:
            roh = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return roh if isinstance(roh, dict) else {}


def alle() -> dict:
    """Alle Einstellungen, fehlende mit ihrer Vorgabe."""
    werte = dict(VORGABEN)
    werte.update({k: v for k, v in _lesen().items() if k in VORGABEN})
    return werte


def hole(name: str):
    """Eine Einstellung -- oder ihre Vorgabe."""
    return alle().get(name, VORGABEN.get(name))


def setze(name: str, wert) -> None:
    """Eine Einstellung schreiben. Unbekannte Namen werden abgewiesen.

    Abgewiesen und nicht durchgereicht: Ein Tippfehler im Namen wuerde
    sonst eine Zeile in die Datei schreiben, die nie jemand liest -- und
    der Schalter, den man gerade umgelegt hat, bliebe wirkungslos.
    """
    if name not in VORGABEN:
        raise ValueError(f"Unbekannte Einstellung: {name}")
    daten = _lesen()
    daten[name] = wert
    DATEI.parent.mkdir(parents=True, exist_ok=True)
    # Erst daneben, dann umbenennen: Ein abgebrochener Schreibvorgang
    # laesst sonst eine halbe YAML-Datei zurueck, und die liest sich beim
    # naechsten Start als "keine Einstellungen".
    vorlaeufig = DATEI.with_suffix(".yaml.neu")
    with vorlaeufig.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(daten, fh, allow_unicode=True, sort_keys=False)
    os.replace(vorlaeufig, DATEI)

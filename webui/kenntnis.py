"""
Welche Befunde jemand zur Kenntnis genommen hat.

Eine Seitenkarte entsteht beim Aufbau der Seite und verschwindet erst,
wenn ihre Ursache weg ist. Das ist bei einem Fehler richtig und bei einer
Warnung laestig: Die volle Platte stuende bis zum Aufraeumen am
Wochenende auf jeder Seite, obwohl der Betreiber es laengst weiss.

**Weggeklickt heisst nicht weg.** Die Karte schrumpft auf eine graue
Zeile ueber der Seite -- wer nicht selbst geklickt hat, findet den Befund
also trotzdem. Nur leise. Damit faellt der Einwand, der sonst gegen das
Wegklicken steht: Ein Kollege sieht dieselbe Seite, nur eingeklappt.

**Weggeklickt heisst ausserdem: "ich weiss Bescheid, bis es schlimmer
wird."** Jeder Befund traegt dafuer eine Zahl, die nur steigt, wenn es
schlimmer wird -- die erreichte Fuenferstufe der Belegung, die Zahl der
ausgefallenen Dienste. Gespeichert wird sie mit; steigt sie, ist es ein
neuer Befund und die Karte kommt zurueck. Eine Frist gibt es bewusst
nicht: Jede Zahl darin waere gegriffen, und "sieben Tage" beantwortet
keine Frage, die jemand hat.

**Und: War der Befund weg und kommt wieder, ist er neu.** Deshalb wird
vergessen, was gerade nicht gilt -- sonst bliebe ein Ausfall von vorigem
Monat stumm, wenn er sich wiederholt.

Warum auf dem Server und nicht im Browser: Der Befund gilt dem Server,
nicht dem Geraet. Wer am Laptop wegklickt, will es am Telefon nicht
wiedersehen.

Warum so: docs/gestaltung.md, "Eine Karte zur Kenntnis nehmen".
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_DB = Path(os.environ.get("PXE_DB", "/var/lib/pxeweb/pxeweb.db"))

# Neben quellenwacht.yaml, aus demselben Grund: Es ist der Stand einer
# Mechanik, nicht die Einrichtung des Servers. Eine Werkseinstellung darf
# ihn wegwerfen.
DATEI = Path(os.environ.get("PXE_KENNTNIS", "") or _DB.parent / "kenntnis.yaml")

# Rot ist nie wegklickbar. Ein Server, der seine Arbeit nicht tut, darf
# nicht aussehen wie einer, der sie tut -- das ist der ganze Grund, warum
# es die rote Karte gibt.
WEGKLICKBAR = ("warnung", "info")


def _lesen() -> dict:
    try:
        with DATEI.open(encoding="utf-8") as fh:
            roh = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(roh, dict):
        return {}
    # Nur, was hier hingehoert: Kennung -> Zahl. Alles andere faellt weg,
    # damit eine von Hand verbogene Datei nichts kaputt macht.
    return {str(k): int(v) for k, v in roh.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def _schreiben(daten: dict) -> None:
    DATEI.parent.mkdir(parents=True, exist_ok=True)
    vorlaeufig = DATEI.with_suffix(".yaml.neu")
    with vorlaeufig.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(daten, fh, allow_unicode=True, sort_keys=True)
    os.replace(vorlaeufig, DATEI)


def nehmen(kennung: str, marke: int) -> None:
    """Diesen Befund auf diesem Stand zur Kenntnis nehmen."""
    daten = _lesen()
    daten[kennung] = int(marke)
    _schreiben(daten)


def teilen(befunde: list[dict]) -> tuple[list[dict], list[dict]]:
    """Trennt die geltenden Befunde in offene und zur Kenntnis genommene.

    Nebenbei wird vergessen, was gerade nicht gilt: Ein Befund, der weg
    war und wiederkommt, ist ein neuer und faengt offen an.
    """
    daten = _lesen()
    gelten = {b["kennung"] for b in befunde}

    veraltet = set(daten) - gelten
    if veraltet:
        _schreiben({k: v for k, v in daten.items() if k in gelten})
        for k in veraltet:
            daten.pop(k)

    offen: list[dict] = []
    bekannt: list[dict] = []
    for b in befunde:
        gemerkt = daten.get(b["kennung"])
        if (b["stufe"] in WEGKLICKBAR and gemerkt is not None
                and int(b.get("marke", 0)) <= gemerkt):
            bekannt.append(b)
        else:
            offen.append(b)
    return offen, bekannt


def zuruecksetzen() -> None:
    """Alles vergessen -- fuer die Werkseinstellung."""
    try:
        DATEI.unlink()
    except OSError:
        pass

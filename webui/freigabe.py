"""
Wo ein Eintrag angeboten wird: im Bootmenue, in den Boot-Optionen, beides.

Zwei Stufen, und sie haben verschiedene Reichweite:

    Bootmenue        sehen alle Rechner, die per Netz starten duerfen
    Boot-Optionen    steht unter Clients zur Auswahl, gilt also einem
                     einzelnen Rechner

Damit laesst sich eine neue Ausgabe erproben, bevor sie fuer alle gilt:
Haken nur bei den Boot-Optionen, einen Testrechner darauf setzen, starten.
Laeuft es, kommt der Haken beim Bootmenue dazu -- und bei der alten
Ausgabe geht er weg. Ohne diese Trennung muesste man ein ungeprueftes
System ins Menue stellen, wo es jeder erwischen kann.

**Beide Haken sind ab Werk leer.** Ein Eintrag, dessen Dateien gerade
fertig geworden sind, wird nicht angeboten, bis jemand das entscheidet.

Bis August 2026 war es umgekehrt, und das machte genau den Ablauf
unmoeglich, der oben beschrieben ist: Wer eine neue Ausgabe erproben
wollte, hatte sie in dem Moment, in dem der Download fertig war, schon
fuer alle im Menue. Den Ausschlag gab ShredOS -- ein Eintrag, der
Datentraeger unwiderruflich loescht und der sich so von selbst vor jeden
bootenden Rechner gestellt haette.

Gespeichert wird deshalb der ganze Stand und nicht mehr die Abweichung:
Bei einer Vorgabe "aus" hiesse eine leere Datei sonst "nichts wird
angeboten", und ein verlorengegangener Eintrag darin naehme still einen
Menuepunkt mit. Die Marke "stand" oben in der Datei sagt, nach welcher
Regel sie gelesen wird.

**Das steuert die Anzeige, nicht die Erreichbarkeit.** Ein Rechner mit
fester Vorauswahl holt sein Boot-Skript direkt; das funktioniert weiter,
auch wenn der Eintrag in keiner Liste mehr auftaucht. Sonst wuerde ein
Haken hier eine laufende Installation abwuergen.

Abgelegt neben der Datenbank unter /var/lib/pxeweb/, nicht im
Projektordner: install.sh spiegelt den mit "rsync --delete".
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_DB = Path(os.environ.get("PXE_DB", "/var/lib/pxeweb/pxeweb.db"))
DATEI = Path(os.environ.get("PXE_FREIGABE", "") or _DB.parent / "freigabe.yaml")

# Die beiden Schalter, wie sie in der Datei und im Formular heissen.
FELDER = ("menue", "optionen")


# Nach welcher Regel die Datei gelesen wird. 1 gab es nicht als Marke --
# so hiess das alte Format, in dem nur "aus" gespeichert wurde.
STAND = 2


def _roh() -> tuple[dict, bool]:
    """Der Inhalt der Datei und ob er schon im heutigen Format steht."""
    try:
        with DATEI.open(encoding="utf-8") as fh:
            roh = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}, False
    if not isinstance(roh, dict):
        return {}, False
    if roh.get("stand") == STAND:
        eintraege = roh.get("eintraege")
        return (eintraege if isinstance(eintraege, dict) else {}), True
    return roh, False


def alle() -> dict[str, dict]:
    """Was freigegeben ist, je Eintrag und Schalter.

    Fehlt ein Eintrag, ist er nicht freigegeben -- das ist die Vorgabe.
    Steht die Datei noch im alten Format, wird sie so gelesen, wie sie
    gemeint war: alles frei ausser dem, was ausdruecklich aus ist. Sonst
    waere zwischen dem Update und der Umstellung (siehe uebernimm_stand)
    fuer einen Augenblick nichts mehr im Menue.
    """
    roh, heutig = _roh()
    werte = {}
    for slug, daten in roh.items():
        if not isinstance(daten, dict):
            continue
        if heutig:
            eintrag = {feld: bool(daten.get(feld)) for feld in FELDER}
        else:
            eintrag = {feld: daten.get(feld) is not False for feld in FELDER}
        werte[str(slug)] = eintrag
    if not heutig:
        # Im alten Format stand nur das Abweichende drin; alles andere galt
        # als frei. Wer nicht dasteht, ist dort also freigegeben -- das
        # kann diese Funktion nicht wissen, deshalb faengt wende_an() es ab.
        werte["*"] = {feld: True for feld in FELDER}
    return werte


def uebernimm_stand(bereit: list[str]) -> bool:
    """Einmalig: hinschreiben, was heute angeboten wird.

    Die Vorgabe hat sich umgedreht -- frueher war ein Eintrag ohne Angabe
    freigegeben, heute ist er es nicht. Ohne diesen Schritt waere nach dem
    naechsten Update das Bootmenue eines laufenden Servers leer, und
    niemand wuesste warum.

    Uebernommen wird, was in diesem Moment wirklich angeboten wird: alle
    startbereiten Eintraege ausser denen, die ausdruecklich aus waren. Auf
    einem frisch aufgesetzten Server ist noch nichts geholt, die Liste ist
    also leer -- und damit gilt dort von Anfang an die neue Vorgabe.
    """
    roh, heutig = _roh()
    if heutig:
        return False
    aus = {str(slug) for slug, daten in roh.items()
           if isinstance(daten, dict) and any(daten.get(f) is False for f in FELDER)}
    setze({slug: {feld: True for feld in FELDER}
           for slug in bereit if slug not in aus})
    return True


def setze(werte: dict[str, dict]) -> None:
    """Den Stand sichern. Ersetzt, was vorher dastand."""
    daten = {"stand": STAND,
             "eintraege": {slug: {feld: bool(eintrag.get(feld)) for feld in FELDER}
                           for slug, eintrag in werte.items()}}
    DATEI.parent.mkdir(parents=True, exist_ok=True)
    # Erst daneben schreiben, dann umbenennen -- sonst liest ein zweiter
    # Browser eine halbe Datei, waehrend hier gespeichert wird.
    vorlaeufig = DATEI.with_suffix(".yaml.neu")
    with vorlaeufig.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(daten, fh, allow_unicode=True, sort_keys=True)
    os.replace(vorlaeufig, DATEI)


def wende_an(eintrag: dict) -> dict:
    """Die beiden Schalter an den Eintrag schreiben.

    Ohne Angabe ist ein Eintrag nicht freigegeben. Die Ausnahme ist eine
    Datei im alten Format -- dort galt das Umgekehrte, und bis
    uebernimm_stand() beim naechsten Start durchgelaufen ist, soll sich
    nichts aendern.
    """
    stand = alle()
    vorgabe = stand.get("*", {feld: False for feld in FELDER})
    eigen = stand.get(eintrag.get("slug", ""), vorgabe)
    return {**eintrag,
            "im_menue": eigen.get("menue", False),
            "in_optionen": eigen.get("optionen", False)}

"""
Reihenfolge der Gruppen -- auf der Systeme-Seite und im Bootmenue.

Bis hierher stand sie als feste Liste im Code (GRUPPEN in app.py). Das war
richtig, solange es drei Gruppen gab und niemand sie umstellen wollte;
sobald man sie umstellen will, ist eine Codeaenderung samt Update der
falsche Weg dafuer.

Gespeichert wird eine Zahl je Gruppe, nicht eine sortierte Liste. Der
Grund: eine Liste muesste vollstaendig sein. Taucht eine Gruppe auf, die
beim Speichern noch nicht da war -- ein Katalogeintrag mit neuer Kategorie
--, waere sie in einer Liste schlicht nicht enthalten und muesste
irgendwohin geraten. Mit Zahlen bekommt sie ihre Vorgabestelle und rutscht
dorthin, wo sie ohne diese Datei auch gestanden haette.

Abgelegt neben der Datenbank unter /var/lib/pxeweb/, nicht im
Projektordner: install.sh spiegelt den mit "rsync --delete", eine dort
abgelegte Reihenfolge waere beim naechsten Update ohne Warnung weg --
dasselbe gilt fuer quellen.env.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_DB = Path(os.environ.get("PXE_DB", "/var/lib/pxeweb/pxeweb.db"))
DATEI = Path(os.environ.get("PXE_GRUPPEN", "") or _DB.parent / "gruppen.yaml")

# Mehr als das kann keine sinnvolle Reihenfolge sein. Die Grenze steht hier
# nicht aus technischen Gruenden, sondern damit ein verrutschter Tastendruck
# ("11" statt "1") auffaellt, solange er sich noch erklaeren laesst.
MAX = 99


def zahlen() -> dict[str, int]:
    """Was eingetragen ist. Fehlt die Datei, ist das kein Fehler."""
    try:
        with DATEI.open(encoding="utf-8") as fh:
            roh = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(roh, dict):
        return {}
    werte = {}
    for name, zahl in roh.items():
        try:
            werte[str(name)] = int(zahl)
        except (TypeError, ValueError):
            continue
    return werte


def pruefe(roh: str) -> int:
    """Eine eingetippte Zahl annehmen -- oder sagen, was daran nicht geht.

    Abgewiesen wird mit einer Meldung statt still auf eine Vorgabe
    zurueckzufallen: wer "2" tippt und danach unveraendert "1" vorfindet,
    sucht den Fehler beim Server.
    """
    text = (roh or "").strip()
    if not text:
        raise ValueError("Es fehlt eine Zahl.")
    try:
        zahl = int(text)
    except ValueError:
        raise ValueError(f"„{text}“ ist keine Zahl.") from None
    if zahl < 1 or zahl > MAX:
        raise ValueError(f"Die Zahl muss zwischen 1 und {MAX} liegen.")
    return zahl


def setze(werte: dict[str, int]) -> None:
    """Die Reihenfolge sichern. Ersetzt, was vorher dastand."""
    daten = {str(name): int(zahl) for name, zahl in werte.items()}
    DATEI.parent.mkdir(parents=True, exist_ok=True)
    # Erst daneben schreiben, dann umbenennen -- sonst liest ein zweiter
    # Browser eine halbe Datei, waehrend hier gespeichert wird.
    vorlaeufig = DATEI.with_suffix(".yaml.neu")
    with vorlaeufig.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(daten, fh, allow_unicode=True, sort_keys=True)
    os.replace(vorlaeufig, DATEI)


def sortiere(namen: list[str]) -> list[str]:
    """Die Namen in der eingestellten Reihenfolge.

    Wer keine Zahl hat, behaelt seine Vorgabestelle: die Stelle in der
    uebergebenen Liste zaehlt dann als seine Zahl. Bei gleicher Zahl
    entscheidet ebenfalls die Vorgabe -- ein Gleichstand entsteht hier
    allerdings nur bei einer von Hand geschriebenen Datei: was ueber die
    Oberflaeche kommt, wird vor dem Speichern zu 1, 2, 3 aufgeloest, und
    zwar entlang der Folge, die der Bedienende gerade vor sich hatte.
    """
    werte = zahlen()
    with_stelle = list(enumerate(namen))
    with_stelle.sort(key=lambda p: (werte.get(p[1], p[0] + 1), p[0]))
    return [name for _, name in with_stelle]


def stand(namen: list[str]) -> dict[str, int]:
    """Welche Zahl gehoert in welches Feld -- fuer die Anzeige.

    Gezeigt wird immer 1, 2, 3 in der geltenden Reihenfolge, nicht das, was
    roh in der Datei steht. Wer einmal 5, 10, 20 eingetragen hat, findet
    beim naechsten Aufruf 1, 2, 3 vor: dieselbe Reihenfolge, nur ohne die
    Frage, ob zwischen 5 und 10 noch etwas fehlt.
    """
    return {name: stelle for stelle, name in enumerate(sortiere(namen), start=1)}

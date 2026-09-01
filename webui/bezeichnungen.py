"""
Eigene Namen fuer Menueeintraege -- Name und Version, im Browser aenderbar.

Woher ein Name kommt, ist von Eintrag zu Eintrag verschieden: aus
catalog.yaml, aus dem Volume-Label eines hochgeladenen Abbilds, aus dem
Formular fuer eigene Netz-Installer. Nur einer davon ist zuverlaessig
kurz. Ein Ubuntu-Desktop-Abbild meldet sich zum Beispiel als

    Ubuntu 26.04 "Resolute Raccoon" - Release amd64 (20260423.1)

-- 55 Zeichen, wo im Bootmenue 38 Platz haben. Alles dahinter (Version,
Beschreibung) rutscht dann nach rechts weg.

Deshalb hier ein eigener Name je Eintrag, der alle anderen Quellen
uebersteuert. Er gilt ueberall, wo der Eintrag vorkommt: Systeme-Liste,
Bootmenue, Vorschau, Server Health, Uebersicht -- sie alle lesen denselben
Katalog.

Zwei Dinge sind bewusst so:

1. **Die Version steht neben dem Namen, nicht darin.** Im Bootmenue hat
   sie eine eigene Spalte; wer sie in den Namen schreibt, bekommt sie an
   der falschen Stelle und untereinander stehen zwei Ausgaben desselben
   Systems dann nicht mehr.

2. **Ein leeres Feld setzt zurueck.** Es bedeutet nicht "kein Name",
   sondern "nimm wieder den, der von selbst entsteht". Ein Eintrag ohne
   Namen waere im Menue nicht anzusteuern.

Abgelegt neben der Datenbank unter /var/lib/pxeweb/, nicht im
Projektordner: install.sh spiegelt den mit "rsync --delete". Und nicht in
der eintrag.yaml des Abbilds, denn die schreibt "Neu einlesen" neu -- ein
eigener Name soll das ueberleben.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_DB = Path(os.environ.get("PXE_DB", "/var/lib/pxeweb/pxeweb.db"))
DATEI = Path(os.environ.get("PXE_NAMEN", "") or _DB.parent / "namen.yaml")

# Die Grenzen kommen vom Bildschirm des bootenden Rechners, nicht aus der
# Datenhaltung. iPXE zeichnet sein Menue in die Textkonsole -- ueblich sind
# 80 Spalten -- und schneidet zu lange Zeilen ab, statt sie umzubrechen.
# Ein Rechner, der die Auswahl nicht lesen kann, ist die Sorte Fehler, die
# erst am Geraet auffaellt.
#
#     Name + " " + Version   45   erste Spalte
#     Abstand                 2
#     ( Menue-Info )         31   Klammern mitgerechnet
#     --------------------------
#                            78   und damit innerhalb von 80
#
# MENUE_BREITE ist dieselbe Zahl von der anderen Seite gesehen: So weit
# reicht eine Zeile, danach schneidet iPXE ab. Die Vorschau unter Systeme
# setzt alles dahinter blass, statt einen Rollbalken anzubieten -- den gibt
# es vor dem bootenden Rechner nicht.
MENUE_BREITE = 78
MAX_ZEILE = 45
MAX_INFO = 29

def menue_titel(mac: str, platform: str) -> str:
    """Die Titelzeile des Bootmenues -- fuer das Menue und fuer die Vorschau.

    Sie stand zweimal da: einmal in menu.ipxe.j2, einmal in systeme.html.
    Aufgefallen ist das erst, als der Absender ins Menue kam und die
    Vorschau ihn nicht zeigte -- die Vorschau hatte ihre eigene Zeile.
    Zwei Stellen fuer denselben Text laufen frueher oder spaeter
    auseinander, und die Vorschau ist genau dann wertlos: Sie soll ja
    zeigen, was am bootenden Rechner steht.
    """
    return "exmig - MARLEI Boot  --  %s  (%s)" % (mac, platform)


# Je Feld noch eine Obergrenze, damit im Browser gar nicht erst mehr
# hineingeht, als zusammen erlaubt ist. Die eigentliche Regel ist MAX_ZEILE
# -- ein Name darf die ganzen 45 haben, wenn keine Version danebensteht.
MAX_NAME = MAX_ZEILE
MAX_VERSION = 20


def alle() -> dict[str, dict]:
    """Was eingetragen ist. Fehlt die Datei, ist das kein Fehler."""
    try:
        with DATEI.open(encoding="utf-8") as fh:
            roh = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(roh, dict):
        return {}

    werte = {}
    for slug, daten in roh.items():
        if not isinstance(daten, dict):
            continue
        eintrag = {}
        for feld in ("name", "version", "info"):
            wert = daten.get(feld)
            if isinstance(wert, (str, int, float)) and str(wert).strip():
                eintrag[feld] = str(wert).strip()
        if eintrag:
            werte[str(slug)] = eintrag
    return werte


def menuezeile(name: str, version: str) -> str:
    """Die erste Spalte, so wie sie im Menue steht."""
    return (f"{name} {version}" if name and version else (name or version)).strip()


def pruefe(name: str, version: str, info: str = "") -> tuple[str, str, str]:
    """Eingetipptes annehmen -- oder sagen, was daran nicht geht.

    Geprueft wird nur, was jemand eintippt. Was der Server selbst
    ausliest, darf laenger sein: Ein Abbild meldet sich nun einmal als
    'Ubuntu 26.04 "Resolute Raccoon" - Release amd64 (20260423.1)', und
    das abzulehnen hiesse, den Eintrag gar nicht erst anzubieten. Im Menue
    wird es dann abgeschnitten -- was der Anlass ist, ihm einen kuerzeren
    Namen zu geben.
    """
    name = (name or "").strip()
    version = (version or "").strip()
    info = (info or "").strip()
    # Zeilenumbrueche wuerden das iPXE-Skript zerlegen: dort ist jede Zeile
    # ein Befehl.
    if any(zeichen in name + version + info for zeichen in "\r\n"):
        raise ValueError("Zeilenumbrueche gehen nicht.")
    return name, version, info


def pruefe_laenge(name: str, version: str, info: str) -> None:
    """Passt das noch auf den Bildschirm des bootenden Rechners?

    Getrennt von pruefe(), weil es nur fuer Eingetipptes gilt -- der
    Aufrufer weiss, was von der Vorgabe abweicht, dieses Modul nicht.
    """
    zeile = menuezeile(name, version)
    if len(zeile) > MAX_ZEILE:
        raise ValueError(
            f"Name und Version sind zusammen {len(zeile)} Zeichen, erlaubt "
            f"sind {MAX_ZEILE} -- mehr passt im Menü nicht neben die Info.")
    if len(info) > MAX_INFO:
        raise ValueError(
            f"Die Menü-Info ist {len(info)} Zeichen lang, erlaubt sind "
            f"{MAX_INFO} -- danach ist die Bildschirmzeile voll.")


def setze(werte: dict[str, dict]) -> None:
    """Die eigenen Namen sichern. Ersetzt, was vorher dastand."""
    daten = {slug: dict(eintrag) for slug, eintrag in werte.items() if eintrag}
    DATEI.parent.mkdir(parents=True, exist_ok=True)
    # Erst daneben schreiben, dann umbenennen -- sonst liest ein zweiter
    # Browser eine halbe Datei, waehrend hier gespeichert wird.
    vorlaeufig = DATEI.with_suffix(".yaml.neu")
    with vorlaeufig.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(daten, fh, allow_unicode=True, sort_keys=True)
    os.replace(vorlaeufig, DATEI)


def wende_an(eintrag: dict) -> dict:
    """Den eigenen Namen einsetzen und die Vorgabe daneben merken.

    Die Vorgabe wird gebraucht, sobald jemand das Feld leert: dann gilt
    wieder, was von selbst entsteht. Und die Oberflaeche kann zeigen, wovon
    ein eigener Name abweicht.
    """
    eigen = alle().get(eintrag.get("slug", ""))
    vorgabe = {
        "name_vorgabe": eintrag.get("name", ""),
        "version_vorgabe": eintrag.get("version", "") or "",
    }
    if not eigen:
        return {**eintrag, **vorgabe}
    # Die Menue-Info wird hier nur durchgereicht: Was ohne sie im Menue
    # steht, weiss dieses Modul nicht -- es wird aus den Dateien gelesen
    # (_menue_info in app.py). Sie steht deshalb als "info" daneben und
    # ersetzt die Beschreibung erst dort.
    return {**eintrag, **vorgabe,
            "name": eigen.get("name") or eintrag.get("name", ""),
            "version": eigen.get("version") or eintrag.get("version", "") or "",
            # Wie bei Name und Version: Ein leeres Feld heisst "nimm
            # wieder die Vorgabe", nicht "loesche sie". Vorher stand hier
            # nur eigen.get("info", "") -- wer bloss den Namen aenderte,
            # loeschte damit still den Satz aus catalog.yaml mit.
            "info": eigen.get("info") or eintrag.get("info", "")}

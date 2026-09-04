"""
Hat sich das Projekt bewegt, seit dieser Server installiert wurde?

**Git ist ein Hol-Verfahren.** Wer nie `update.sh` tippt, bleibt ewig auf
dem Installationsstand, ohne es zu merken; der Server sieht dabei
kerngesund aus. Das ist derselbe Fall wie bei einem Eintrag, dem die
Dateien fehlen: Es fehlt etwas, und niemand sagt es.

**Verglichen werden Commits, nicht Versionsnummern -- und das war ein
Umbau.** Der erste Entwurf fragte nach dem hoechsten Tag und hielt ihn
gegen den Stempel. Das passt zu einem Projekt, das Ausgaben ausliefert;
dieses wird ueber `git clone` und `update.sh` verteilt, und wer dem README
folgt, landet auf dem Kopf von `main`. Der Stempel lautet dann
"v1.0.1-8-g7831a68" -- kein Tag, sondern ein Punkt dazwischen. Zwei solche
Angaben lassen sich nicht vergleichen: Ob das, was im Tag steckt, in den
acht Aenderungen danach schon enthalten ist, sagt keine von beiden.

Markus am 04.09.2026, als die Karte deshalb schwieg: *"Sinn der Suche ist
doch zu sehen, gibt es neue Versionen. Was habe ich von dem jetzigen
Ergebnis."* Nichts -- und die Frage war die falsche. Die richtige lautet:
**Liegen Aenderungen bereit?** Sie ist beantwortbar, weil `install.sh`
neben dem Stand auch den **Commit** stempelt: GitHub vergleicht ihn mit
dem Zweig und sagt, wie viele Aenderungen dazwischenliegen.

**Die Versionsnummern behalten davon unberuehrt ihre Aufgabe:** Sie sagen,
*was* drin ist (siehe mappe/08-entscheidungen.md, "Was die drei Ziffern
bedeuten") -- nicht, *ob* man holen soll.

**Wie oft, entscheidet der Betreiber** (einstellungen.updatepruefung):
nie, woechentlich, monatlich. Darueber steht die Notbremse: Ist der
Quellenwaechter per PXE_QUELLENWACHT abgeschaltet, ist auf diesem Server
jede Netzabfrage unerwuenscht -- dann fragt auch dieser Waechter nicht,
und die Oberflaeche bietet die Auswahl gar nicht erst an.

**Ohne Netz passiert nichts, und es sieht auch nicht danach aus.** Ein
fehlgeschlagener Blick wird vermerkt und nicht gemeldet.

Die Bauform ist die von quellenwacht.py -- stuendlicher Takt, Vorlauf nach
dem Start, Stand in einer Datei. Ein Prozess, der eine Woche am Stueck
schlaeft, ueberlebt kein Update.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import versionsstand

_DB = Path(os.environ.get("PXE_DB", "/var/lib/pxeweb/pxeweb.db"))

# Was der letzte Blick ergeben hat.
STAND_DATEI = Path(os.environ.get("PXE_UPDATEWACHT_STAND", "")
                   or _DB.parent / "updatewacht.yaml")

# Wessen Stand verglichen wird. Ueber die Umgebung zu setzen, damit ein
# Fork sich mit sich selbst vergleicht -- und damit der Test nicht ins Netz
# muss.
REPO = os.environ.get("PXE_REPO", "exmig/marlei-boot").strip("/ ")
VERGLEICH = os.environ.get("PXE_VERGLEICH_ADRESSE", "") or (
    "https://api.github.com/repos/" + REPO + "/compare/{commit}...{zweig}")

# Die Notbremse. Dieselbe Variable wie beim Quellenwaechter, und das ist
# Absicht: Sie bedeutet nicht "keine Quellenpruefung", sondern "dieser
# Server fragt nicht nach draussen".
_NOTBREMSE = os.environ.get("PXE_QUELLENWACHT", "").strip().lower()

# Was zur Auswahl steht. Mehr Werte waeren eine Einstellung, die niemand
# trifft -- und "alle drei Tage" beantwortet keine Frage, die jemand hat.
AUSWAHL = ((0, "nie"), (7, "wöchentlich"), (30, "monatlich"))

TAKT = 3600.0
VORLAUF = 120.0
ZEITLIMIT = 10.0

# Wie lange die Seite auf einen angestossenen Blick wartet, bevor sie ohne
# sein Ergebnis gebaut wird. Eine Anfrage dauert gemessen rund 150 ms; zwei
# Sekunden decken auch eine muede Leitung ab. Ohne dieses Warten ginge das
# Ergebnis ins Leere: Die Seite entsteht nach dem Speichern genau einmal.
BEDENKZEIT = 2.0


def gesperrt() -> bool:
    """Verbietet die Umgebung jede Netzabfrage?"""
    return _NOTBREMSE in ("aus", "off", "nein", "0")


def intervall_tage() -> int:
    """Tage zwischen zwei Blicken. 0 heisst: abgeschaltet."""
    if gesperrt():
        return 0
    import einstellungen
    try:
        tage = int(einstellungen.hole("updatepruefung"))
    except (TypeError, ValueError):
        return 7
    return tage if tage in dict(AUSWAHL) else 0


# --------------------------------------------------------------------------
# Der Stand
# --------------------------------------------------------------------------

def _lesen() -> dict:
    try:
        with STAND_DATEI.open(encoding="utf-8") as fh:
            roh = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return roh if isinstance(roh, dict) else {}


def _schreiben(daten: dict) -> None:
    STAND_DATEI.parent.mkdir(parents=True, exist_ok=True)
    vorlaeufig = STAND_DATEI.with_suffix(".yaml.neu")
    with vorlaeufig.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(daten, fh, allow_unicode=True, sort_keys=False)
    os.replace(vorlaeufig, STAND_DATEI)


def vergiss() -> None:
    """Den gemerkten Stand wegwerfen -- fuer die Werkseinstellung."""
    try:
        STAND_DATEI.unlink()
    except OSError:
        pass


def _woher() -> tuple[str, str]:
    """Commit und Zweig aus dem Stempel von install.sh.

    Beides oder nichts: Ohne Commit gibt es keinen Punkt, von dem aus
    verglichen wird. Und der Zweig entscheidet, wogegen verglichen wird --
    wer von einem anderen Zweig installiert hat, will nicht gegen `main`
    gemessen werden.
    """
    auskunft = versionsstand.auskunft()
    if not auskunft.get("da"):
        return "", ""
    return auskunft.get("commit", ""), (auskunft.get("zweig", "") or "main")


# --------------------------------------------------------------------------
# Ein Blick
# --------------------------------------------------------------------------

_laeuft = threading.Lock()


def laeuft() -> bool:
    return _laeuft.locked()


def naechster_blick() -> datetime | None:
    tage = intervall_tage()
    if not tage:
        return None
    zeit = _lesen().get("zeit")
    if not zeit:
        return None                       # noch nie gefragt -- sofort dran
    try:
        war = datetime.fromisoformat(zeit)
    except (TypeError, ValueError):
        return None
    if war.tzinfo is None:
        war = war.replace(tzinfo=timezone.utc)
    return war + timedelta(days=tage)


def faellig() -> bool:
    if not intervall_tage():
        return False
    naechster = naechster_blick()
    if naechster is None:
        return True
    return datetime.now(timezone.utc) >= naechster


def _frag_github(commit: str, zweig: str, hole=None) -> dict:
    """Wie weit liegt der Zweig vor dem installierten Commit?

    GitHub beantwortet das in einer Anfrage: "ahead_by" zaehlt, was auf
    dem Zweig dazugekommen ist, "behind_by" was dieser Server hat und der
    Zweig nicht -- letzteres bei einem Rechner mit eigenen Commits.
    """
    if hole is not None:
        return hole()
    ziel = VERGLEICH.format(commit=commit, zweig=zweig)
    anfrage = urllib.request.Request(
        ziel, headers={"User-Agent": "pxeweb/1.0",
                       "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT) as antwort:
        daten = json.loads(antwort.read().decode("utf-8", "replace"))
    return daten if isinstance(daten, dict) else {}


def blick(hole=None) -> bool:
    """Einmal nachsehen. Sagt, ob der Blick zustande kam."""
    if not intervall_tage() or _laeuft.locked():
        return False
    with _laeuft:
        commit, zweig = _woher()
        daten = {"zeit": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "commit": commit, "zweig": zweig,
                 "voraus": 0, "zurueck": 0,
                 "kein_stempel": not commit,
                 "ohne_netz": False, "erreicht": False}
        if not commit:
            # Ohne Stempel gibt es keinen Punkt, von dem aus verglichen
            # wird. Kein Fehler: Die Anwendung laeuft dann aus einem
            # Projektordner und kam nicht ueber install.sh hierher.
            _schreiben(daten)
            return False
        try:
            antwort = _frag_github(commit, zweig, hole)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as fehler:
            # Vermerkt, nicht gemeldet: Ohne Leitung ist nichts kaputt.
            #
            # "erreicht" trennt zwei Faelle, die man sonst verwechselt und
            # dann falsch benennt: gar keine Antwort (Leitung, DNS,
            # Zeitlimit) und eine Antwort, die keine Auskunft war -- etwa
            # 404, wenn der gestempelte Commit dort gar nicht existiert,
            # weil jemand mit eigener Historie arbeitet.
            daten["ohne_netz"] = True
            daten["erreicht"] = isinstance(fehler, urllib.error.HTTPError)
            daten["grund"] = str(fehler)[:200]
            _schreiben(daten)
            return False
        daten["voraus"] = int(antwort.get("ahead_by") or 0)
        daten["zurueck"] = int(antwort.get("behind_by") or 0)
        _schreiben(daten)
        return True


def stand() -> dict:
    """Was der letzte Blick ergeben hat -- fuer Karte und Befund."""
    daten = _lesen()
    naechster = naechster_blick()
    commit, zweig = _woher()
    voraus = int(daten.get("voraus") or 0)
    return {
        "zeit": daten.get("zeit", ""),
        "commit": daten.get("commit", "") or commit,
        "zweig": daten.get("zweig", "") or zweig,
        # Wieviele Aenderungen auf dem Zweig dazugekommen sind, seit dieser
        # Server eingespielt wurde. Das ist die ganze Auskunft.
        "voraus": voraus,
        # Und was dieser Server hat und der Zweig nicht -- eigene Commits.
        "zurueck": int(daten.get("zurueck") or 0),
        "neuer": voraus > 0,
        "kein_stempel": bool(daten.get("kein_stempel")) or not commit,
        "ohne_netz": bool(daten.get("ohne_netz")),
        "erreicht": bool(daten.get("erreicht")),
        "gesucht": bool(daten.get("zeit")),
        "gesperrt": gesperrt(),
        "intervall": intervall_tage(),
        "laeuft": laeuft(),
        "naechster": naechster.isoformat() if naechster else "",
    }


# --------------------------------------------------------------------------
# Der Waechter
# --------------------------------------------------------------------------

_wacht_laeuft = False


def starte_blick(hole=None, warten: float = 0.0) -> bool:
    """Einen Blick anstossen. False, wenn schon einer laeuft.

    **Fuer den Moment, in dem jemand gerade geklickt hat.** Die Wache
    schlaeft in Stunden-Schritten -- richtig fuers Warten, falsch fuers
    Klicken.

    In einem eigenen Faden, damit ein haengendes Netz die Seite nicht
    festhaelt -- aber mit ``warten`` sieht der Aufrufer ihm kurz zu.
    """
    if laeuft() or not intervall_tage():
        return False
    faden = threading.Thread(target=blick, args=(hole,), daemon=True)
    faden.start()
    if warten:
        faden.join(warten)
    return True


def _wache() -> None:
    time.sleep(VORLAUF)
    while True:
        try:
            if faellig():
                blick()
        except Exception:
            # Ein Waechter, der an einem Fehler stirbt, ist schlimmer als
            # keiner: Er meldet sich nie wieder, und niemand vermisst ihn.
            pass
        time.sleep(TAKT)


def wacht_starten() -> None:
    """Einmal beim Hochfahren der Anwendung.

    Der Takt haengt bewusst nicht am Intervall: Wer die Einstellung von
    "nie" auf "woechentlich" dreht, soll nicht bis zum naechsten
    Dienst-Neustart warten.
    """
    global _wacht_laeuft
    if _wacht_laeuft or gesperrt():
        return
    _wacht_laeuft = True
    threading.Thread(target=_wache, daemon=True).start()

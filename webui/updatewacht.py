"""
Gibt es eine neuere Version? -- der Blick ins Repository.

**Git ist ein Hol-Verfahren.** Wer nie `update.sh` tippt, bleibt ewig auf
dem Installationsstand, ohne es zu merken; der Server sieht dabei
kerngesund aus. Das ist derselbe Fall wie bei einem Eintrag, dem die
Dateien fehlen: Es fehlt etwas, und niemand sagt es.

**Gefragt wird bei GitHub, nicht bei uns.** Ein eigener Endpunkt haette
die Zaehlung der Installationen als Nebenprodukt abgeworfen -- dann haenge
aber eine Funktion, die jeder will, an einer Zaehlung, die niemand
verlangt hat. Begruendung in mappe/08-entscheidungen.md, "Wohin der Server
nach Aktualisierungen fragt".

**Wie oft, entscheidet der Betreiber** (einstellungen.updatepruefung):
nie, woechentlich, monatlich. Darueber steht die Notbremse: Ist der
Quellenwaechter per PXE_QUELLENWACHT abgeschaltet, ist auf diesem Server
jede Netzabfrage unerwuenscht -- dann fragt auch dieser Waechter nicht,
und die Oberflaeche bietet die Auswahl gar nicht erst an. Die Umgebung
setzt den Rahmen, die Oberflaeche waehlt darin.

**Ohne Netz passiert nichts, und es sieht auch nicht danach aus.** Ein
fehlgeschlagener Blick wird vermerkt und nicht gemeldet: Eine rote Zeile,
weil die Leitung fehlt, waere der Fehlalarm, den dieses Projekt an anderer
Stelle ausdruecklich bekaempft.

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

# Wo gefragt wird. Ueber die Umgebung zu setzen, damit ein Fork nicht
# unsere Versionen meldet -- und damit der Test nicht ins Netz muss.
#
# **Die Tags und nicht die Releases.** Der erste Entwurf fragte
# "releases/latest"; das Repository hat aber nur einen Tag und keine
# Release, und GitHub antwortet darauf mit 404. Aufgefallen am 04.09.2026
# auf dem Entwicklungsserver, wo die Karte daraufhin "nicht erreichbar"
# behauptete. Ein Tag ist hier ohnehin die Wahrheit: install.sh stempelt
# "git describe", und das nennt den Tag. Eine Release ist Beiwerk, das es
# geben kann und nicht geben muss.
REPO = os.environ.get("PXE_REPO", "exmig/marlei-boot").strip("/ ")
ADRESSE = os.environ.get("PXE_UPDATE_ADRESSE", "") or (
    f"https://api.github.com/repos/{REPO}/tags")

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


# --------------------------------------------------------------------------
# Versionen vergleichen
# --------------------------------------------------------------------------

def zahlen(version: str) -> tuple:
    """Aus "v1.2-3-gabc1234" wird (1, 2, 3) -- zum Vergleichen.

    Gelesen wird nur, was vorne steht und aus Ziffern besteht. Alles
    dahinter (der Commit, ein "-dirty") sagt nichts ueber neuer oder
    aelter und faellt weg.
    """
    teile: list[int] = []
    for stueck in version.strip().lstrip("vV").replace("-", ".").split("."):
        if not stueck.isdigit():
            break
        teile.append(int(stueck))
    return tuple(teile)


def marke(version: str) -> int:
    """Eine Zahl, die nur steigt, wenn die Version hoeher wird.

    Fuer das Wegklicken (siehe kenntnis.py): Wer eine Version zur Kenntnis
    nimmt, soll die Karte erst bei der naechsten wiedersehen -- und nicht
    beim naechsten Blick des Waechters, der dasselbe findet.

    Aus (1, 2, 3) wird 10203. Drei Stellen, zwei Ziffern je Stelle: Mehr
    braucht eine Versionsnummer nicht, und ein Ueberlauf bei 100 waere
    hier kein Schaden, sondern nur eine Karte, die einmal zu frueh kommt.
    """
    teile = (list(zahlen(version)) + [0, 0, 0])[:3]
    return teile[0] * 10000 + teile[1] * 100 + teile[2]


def ist_neuer(dort: str, hier: str) -> bool:
    """Ist "dort" eine hoehere Version als "hier"?

    Zwei Faelle sagen ausdruecklich nein: Wenn hier nichts steht (die
    Anwendung laeuft aus einem Projektordner, nicht ueber install.sh),
    und wenn sich eine der beiden Angaben nicht in Zahlen lesen laesst.
    **Lieber nichts sagen als raten** -- eine Karte, die eine Aktualisierung
    meldet, die es nicht gibt, kostet mehr Vertrauen als eine, die fehlt.
    """
    a, b = zahlen(dort), zahlen(hier)
    if not a or not b:
        return False
    return a > b


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


def _frag_github(hole=None) -> str:
    """Die hoechste Version, die dort getaggt ist -- oder "" ohne eine.

    Gewaehlt wird nach unserer eigenen Rechnung und nicht nach der
    Reihenfolge der Liste: GitHub sortiert Tags nicht nach Versionen, und
    "v1.10" stuende sonst hinter "v1.9".
    """
    if hole is not None:
        return hole()
    anfrage = urllib.request.Request(
        ADRESSE, headers={"User-Agent": "pxeweb/1.0",
                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT) as antwort:
        daten = json.loads(antwort.read().decode("utf-8", "replace"))
    if not isinstance(daten, list):
        return ""
    namen = [str(e.get("name") or "") for e in daten if isinstance(e, dict)]
    namen = [n for n in namen if zahlen(n)]
    return max(namen, key=zahlen, default="")


def blick(hole=None) -> bool:
    """Einmal nachsehen. Sagt, ob der Blick zustande kam."""
    if not intervall_tage() or _laeuft.locked():
        return False
    with _laeuft:
        hier = versionsstand.kurz()
        daten = {"zeit": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "hier": hier, "dort": "", "neuer": False, "ohne_netz": False}
        try:
            daten["dort"] = _frag_github(hole)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as fehler:
            # Vermerkt, nicht gemeldet: Ohne Leitung ist nichts kaputt.
            #
            # "erreicht" trennt zwei Faelle, die man sonst verwechselt und
            # dann falsch benennt: gar keine Antwort (Leitung, DNS,
            # Zeitlimit) und eine Antwort, die keine Auskunft war (404,
            # kaputtes JSON). Der zweite hiess bis zum 04.09.2026
            # faelschlich "nicht erreichbar".
            daten["ohne_netz"] = True
            daten["erreicht"] = isinstance(fehler, urllib.error.HTTPError)
            daten["grund"] = str(fehler)[:200]
            _schreiben(daten)
            return False
        daten["neuer"] = ist_neuer(daten["dort"], hier)
        _schreiben(daten)
        return True


def stand() -> dict:
    """Was der letzte Blick ergeben hat -- fuer Karte und Befund."""
    daten = _lesen()
    naechster = naechster_blick()
    return {
        "zeit": daten.get("zeit", ""),
        "hier": daten.get("hier", "") or versionsstand.kurz(),
        "dort": daten.get("dort", ""),
        "neuer": bool(daten.get("neuer")),
        "ohne_netz": bool(daten.get("ohne_netz")),
        "erreicht": bool(daten.get("erreicht")),
        # Nachgesehen worden ist ueberhaupt schon einmal?
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
    Dienst-Neustart warten. Deshalb laeuft die Wache immer und fragt jede
    Stunde, ob sie darf.
    """
    global _wacht_laeuft
    if _wacht_laeuft or gesperrt():
        return
    _wacht_laeuft = True
    threading.Thread(target=_wache, daemon=True).start()

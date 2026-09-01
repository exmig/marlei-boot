"""
Der Waechter ueber den Download-Adressen -- alle sieben Tage von selbst.

Warum ueberhaupt? Die Adressen im Katalog veralten, ohne dass jemand
etwas davon merkt: Ein Anbieter raeumt eine Ausgabe ins Archiv, und die
Adresse ist tot. Bisher fiel das erst auf, wenn jemand in den Quellen auf
"Pruefen" drueckte -- oder beim Abgleich, also genau dann, wenn man das
System eigentlich gebraucht haette.

Geprueft wird, was die Karte "Katalog" anbietet: alle Quellen aus
sync-images.sh samt ihrer eingetragenen Ausgaben. Die Arbeit macht
quellen.durchleuchten() -- dieselben drei Fragen wie hinter dem Knopf in
der Karte, damit es hier keine zweite Wahrheit gibt:

    1. Kommt dieser Server ueberhaupt zum Anbieter?
    2. Gilt die Adresse, die eingetragen ist, noch?
    3. Gibt es beim Anbieter etwas Neueres?

Zwei Befunde kommen dabei heraus, und sie haben verschiedene Uhren: Eine
neue Ausgabe erscheint alle paar Monate und hat Zeit. Eine tote Adresse
passiert ohne Vorwarnung, und der Schaden entsteht nicht beim Totgehen,
sondern in dem Moment, in dem das System gebraucht wird. Sieben Tage sind
der Kompromiss -- der Lauf kostet ein knappes Dutzend Anfragen, teuer
ist nur, was er hinschreibt.

Eingetragen wird nichts: Der Waechter sieht nach und schweigt sonst.
Adressen zu reparieren oder neue Ausgaben aufzunehmen bleibt eine
Entscheidung, und die faellt in der Karte -- dort steht auch, was dabei
herauskaeme.
"""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

import eigene
import quellen

_DB = Path(os.environ.get("PXE_DB", "/var/lib/pxeweb/pxeweb.db"))

# Was der letzte Lauf ergeben hat. Eine eigene Datei und nicht die
# quellenstand.yaml: Dort steht der Befund je Quelle, hier der Befund des
# Laufs -- wann er war, wie lange er brauchte, was er gefunden hat.
STAND_DATEI = Path(os.environ.get("PXE_QUELLENWACHT_STAND", "")
                   or _DB.parent / "quellenwacht.yaml")

# Voreinstellung in Tagen. "aus" oder "0" schaltet den Waechter ab -- auf
# einem Server ohne Weg ins Netz hat er nichts zu suchen, und wer die
# Adressen von Hand pflegt, soll das koennen.
_SCHALTER = os.environ.get("PXE_QUELLENWACHT", "").strip().lower()

# Wie oft nachgesehen wird, OB ein Lauf faellig ist. Nicht sieben Tage am
# Stueck schlafen: Ein Prozess, der eine Woche wartet, ueberlebt kein
# Update und keinen Neustart. Stuendlich nachzusehen kostet nichts und
# holt einen faelligen Lauf nach, sobald der Server wieder laeuft.
TAKT = 3600.0

# Nach dem Start nicht sofort losrennen. Wer den Dienst dreimal
# hintereinander neu startet, soll nicht dreimal alle Anbieter
# abklappern -- und ein faelliger Lauf hat die zwei Minuten Zeit.
VORLAUF = 120.0


def intervall_tage() -> int:
    """Wie viele Tage zwischen zwei Laeufen liegen. 0 heisst: abgeschaltet."""
    if _SCHALTER in ("aus", "off", "nein", "0"):
        return 0
    try:
        return max(1, int(_SCHALTER))
    except ValueError:
        return 7


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


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Ein Lauf
# --------------------------------------------------------------------------

_laeuft = threading.Lock()


def laeuft() -> bool:
    """Ist gerade einer unterwegs?"""
    return _laeuft.locked()


def naechster_lauf() -> datetime | None:
    """Wann der naechste Durchgang faellig wird -- oder None.

    None heisst: Es gibt keinen naechsten. Entweder ist der Waechter
    abgeschaltet, oder er ist noch nie gelaufen und damit sofort dran.

    Der Zeitpunkt ist der frueheste, nicht der genaue: Der Waechter sieht
    stuendlich nach (TAKT) und nur, solange die Anwendung laeuft. Wer die
    Zahl anzeigt, sollte sie deshalb rund nennen.
    """
    tage = intervall_tage()
    if not tage:
        return None
    zeit = _lesen().get("zeit")
    if not zeit:
        return None                       # noch nie gelaufen -- sofort dran
    try:
        war = datetime.fromisoformat(zeit)
    except (TypeError, ValueError):
        return None
    if war.tzinfo is None:
        war = war.replace(tzinfo=timezone.utc)
    return war + timedelta(days=tage)


def faellig() -> bool:
    """Ist der naechste Lauf dran?

    Rechnet nicht selbst: Sonst stuende dieselbe Rechnung an zwei Stellen
    und die Karte auf Server Health koennte etwas anderes sagen als der
    Waechter tut.
    """
    if not intervall_tage():
        return False
    naechster = naechster_lauf()
    if naechster is None:
        return True                       # noch nie gelaufen
    return datetime.now(timezone.utc) >= naechster


def _befund(name: str, ergebnis: dict) -> tuple[dict | None, dict | None]:
    """Aus einer durchleuchteten Quelle die zwei Befunde ziehen.

    Zurueck kommt (tot, neu) -- jeweils None, wenn es dazu nichts zu
    sagen gibt. Ohne Verbindung gilt nichts als tot: Dass dieser Server
    gerade nicht ins Netz kommt, ist kein Befund ueber die Adresse.
    """
    if not ergebnis.get("verbindung", {}).get("ok"):
        return None, None

    # Eine Quelle, fuer die keine Ausgabe eingetragen ist, ist nicht in
    # Betrieb -- ueber sie gibt es nichts zu melden. Weder eine tote
    # Adresse (es zeigt keine auf etwas) noch eine neuere Ausgabe (neuer
    # als was?). Sonst begruesste ein frisch aufgesetzter Server seinen
    # Betreiber mit zehn Meldungen ueber Systeme, die er nie gewaehlt hat.
    adressen = ergebnis.get("adressen") or []
    if adressen and all(a.get("leer") for a in adressen):
        return None, None

    # "leer" heisst: fuer diese Quelle ist keine Ausgabe eingetragen, sie
    # ist also gar nicht in Betrieb. Das ist keine tote Adresse, sondern
    # der Auslieferungszustand -- auf einem frisch aufgesetzten Server
    # traefe der Waechter sonst zehnmal Alarm, wo nichts kaputt ist.
    schlecht = [a for a in ergebnis.get("adressen", [])
                if not a.get("ok") and not a.get("kein_netz")
                and not a.get("leer")]
    tot = {
        "name": name,
        "adressen": [{"version": a.get("version", ""), "url": a.get("url", ""),
                      "meldung": a.get("meldung", "")} for a in schlecht],
    } if schlecht else None

    neu = {"name": name, "version": _neuere(name, ergebnis.get("neuere") or {})}
    return tot, (neu if neu["version"] else None)


def _neuere(name: str, neuere: dict) -> str:
    """Gibt es beim Anbieter wirklich etwas Neueres -- und was?

    Die Regel steht in quellen.wirklich_neuer() und gilt fuer die Karte
    genauso. Bis August 2026 stand sie hier, weil die Karte damals die
    volle Liste zum Anklicken zeigte und nur der Waechter sich auf eine
    beschraenkte -- seit "Pruefen" ebenfalls nur das Neueste anbietet,
    gibt es keinen Grund mehr fuer zwei Fassungen.
    """
    return quellen.wirklich_neuer(name, neuere)


def _eigene_gruppen() -> dict:
    """Selbst angelegte Eintraege nach ihrem Muster buendeln.

    Ein selbst angelegtes System liegt nicht als eine Quelle mit einer
    Versionsliste da, sondern als mehrere Eintraege, die sich ein Muster
    teilen -- netz-alma-10-2 neben netz-alma-10-1. Gefragt werden muss
    trotzdem nur einmal: Es ist dasselbe Verzeichnis beim Anbieter, und
    "neuer als was" beantwortet die Summe der schon vorhandenen Ausgaben,
    nicht eine einzelne.

    Eintraege ohne Muster bleiben aussen vor. Das sind die mit einer festen
    Adresse -- vor August 2026 angelegte und alle, in deren Adresse keine
    Ausgabe steckte. Ueber die laesst sich nichts fragen, und eine Meldung
    "keine Auskunft" waere jede Woche dieselbe.
    """
    gruppen: dict = {}
    for eintrag in eigene.alle():
        muster = eintrag.get("muster") or ""
        if "{version}" not in muster:
            continue
        gruppe = gruppen.setdefault(muster, {
            "name": eintrag.get("name", ""), "versionen": [], "eintraege": []})
        if eintrag.get("version"):
            gruppe["versionen"].append(eintrag["version"])
        gruppe["eintraege"].append(eintrag)
    return gruppen


def _eigene_durchsehen(proben=None) -> list[dict]:
    """Fuer jedes selbst angelegte System nachsehen, ob es etwas Neueres gibt.

    Dieselbe Regel wie beim Katalog: hoechstens eine Ausgabe, und nur eine,
    die ueber allem steht, was schon dasteht (quellen.hoehere_als und
    neueste_offene). Sonst meldete ein Eintrag mit Alma 10.2 jede Woche,
    dass es auch 9.6, 9.5 und 8.10 gibt.

    Tote Adressen bleiben hier aussen vor. Beim Katalog sind sie der
    wichtigere der beiden Befunde, weil sync-images.sh sie braucht; die
    Dateien eines selbst angelegten Eintrags liegen dagegen laengst hier,
    und ob der Anbieter sein Verzeichnis umbaut, faellt beim naechsten
    "Pruefen" in der Karte auf. Eine Meldung pro Woche ueber etwas, das
    nichts kaputt macht, waere Laerm.
    """
    fragen = proben or (lambda m: quellen.probe_muster(m, zeitlimit=15.0))
    gefunden = []
    for muster, gruppe in _eigene_gruppen().items():
        try:
            probe = fragen(muster)
        except Exception:                 # eine Quelle haelt den Lauf nicht auf
            continue
        # Kein Index, keine Verbindung: Dann ist nichts bekannt, und das
        # ist etwas anderes als "nichts Neues". Gemeldet wird nur, was da
        # ist -- geschwiegen wird ueber das, was nicht zu erfahren war.
        if not probe.get("ok"):
            continue
        offen = quellen.hoehere_als(probe.get("gefunden", []), gruppe["versionen"])
        dazu = quellen.neueste_offene({"neu": offen}, gruppe["name"])
        if dazu:
            gefunden.append({"name": gruppe["name"], "version": dazu,
                             # Damit die Karte den Weg dorthin kennt: Bei
                             # einer Katalogquelle fuehrt er zur Quelle, hier
                             # zum Eintrag.
                             "eigen": gruppe["eintraege"][0]["slug"]})
    return gefunden


def lauf(pruefer=None, namen: list[str] | None = None, proben=None) -> dict:
    """Alle Quellen einmal durchsehen und den Befund festhalten.

    "pruefer" und "namen" sind fuer die Tests da: So laesst sich der Lauf
    gegen einen eigenen Webserver fahren, statt zwoelf echte Anbieter zu
    behelligen.
    """
    if not _laeuft.acquire(blocking=False):
        return _lesen()                   # es laeuft schon einer
    try:
        pruefen = pruefer or (lambda n: quellen.durchleuchten(n))
        # vorgaben() und nicht alle_werte(): In sync-images.sh stehen auch
        # Versionslisten und Bausteine, die keine Adresse sind. Die Karte
        # "Katalog" zeigt genau diese dreizehn -- geprueft wird, was dort
        # steht, sonst meldete der Waechter Dinge, die niemand wiederfindet.
        liste = namen if namen is not None else sorted(quellen.vorgaben())
        begonnen = time.monotonic()
        _schreiben({**_lesen(), "laeuft": True, "begonnen": _jetzt()})

        tot: list[dict] = []
        neu: list[dict] = []
        ohne_netz: list[str] = []
        for name in liste:
            try:
                ergebnis = pruefen(name)
            except Exception as fehler:   # eine kaputte Quelle haelt den Lauf nicht auf
                tot.append({"name": name, "adressen": [
                    {"version": "", "url": "", "meldung": f"Pruefung fehlgeschlagen: {fehler}"}]})
                continue
            if not ergebnis.get("verbindung", {}).get("ok"):
                ohne_netz.append(name)
                continue
            t, n = _befund(name, ergebnis)
            if t:
                tot.append(t)
            if n:
                neu.append(n)

        # Und dieselbe Frage fuer die selbst angelegten Systeme. Sie stehen
        # in keiner Versionsliste, tragen ihr Muster aber selbst mit sich --
        # seit sie mehrversionig angelegt werden koennen, ist das die
        # einzige Stelle, an der jemand von einer neuen Ausgabe erfaehrt,
        # ohne von Hand nachzusehen.
        neu.extend(_eigene_durchsehen(proben))

        daten = {
            "zeit": _jetzt(),
            "dauer": round(time.monotonic() - begonnen, 1),
            # Die selbst angelegten zaehlen mit -- sonst stuende in der
            # Karte eine Zahl, die kleiner ist als das, was gefragt wurde.
            "geprueft": len(liste) + len(_eigene_gruppen()),
            "tot": tot,
            "neu": neu,
            # Wen dieser Server nicht erreicht hat. Das ist kein Befund
            # ueber die Adresse, sondern einer ueber die Leitung -- und er
            # muss trotzdem sichtbar sein, sonst sieht ein Lauf, der
            # nirgends hinkam, aus wie einer, bei dem alles in Ordnung war.
            "ohne_netz": ohne_netz,
            "laeuft": False,
        }
        _schreiben(daten)
        return daten
    finally:
        _laeuft.release()


def starte_lauf(pruefer=None, namen: list[str] | None = None, proben=None) -> bool:
    """Einen Lauf im Hintergrund anstossen. False, wenn schon einer laeuft."""
    if laeuft():
        return False
    threading.Thread(target=lauf, args=(pruefer, namen, proben),
                     daemon=True).start()
    return True


def stand() -> dict:
    """Was der letzte Lauf ergeben hat -- fuer die Karte auf Server Health."""
    daten = _lesen()
    return {
        "zeit": daten.get("zeit", ""),
        "dauer": daten.get("dauer", 0),
        "geprueft": daten.get("geprueft", 0),
        "tot": daten.get("tot") or [],
        "neu": daten.get("neu") or [],
        "ohne_netz": daten.get("ohne_netz") or [],
        "laeuft": laeuft(),
        "intervall": intervall_tage(),
        "faellig": faellig(),
        "naechste": (lambda n: n.isoformat() if n else "")(naechster_lauf()),
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
                lauf()
        except Exception:
            # Ein Waechter, der an einem Fehler stirbt, ist schlimmer als
            # keiner: Er meldet sich nie wieder, und niemand vermisst ihn.
            pass
        time.sleep(TAKT)


def wacht_starten() -> None:
    """Den Waechter starten -- einmal, beim Hochfahren der Anwendung."""
    global _wacht_laeuft
    if _wacht_laeuft or not intervall_tage():
        return
    _wacht_laeuft = True
    threading.Thread(target=_wache, daemon=True).start()

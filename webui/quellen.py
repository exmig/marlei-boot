"""
Download-Adressen der mitgelieferten Systeme -- anzeigen, pruefen, ersetzen.

Warum ueberhaupt? Die Adressen in sync-images.sh veralten. Ubuntu ersetzt
bei jeder Punktversion den Dateinamen, Fedora raeumt alte Ausgaben in die
Archive. Dann meldet der Sync einen 404, und man muesste sich per SSH
anmelden und das Skript bearbeiten. Stattdessen laesst sich hier die neue
Adresse einfuegen -- und vorher pruefen, ob sie stimmt.

Zwei Ebenen:

    sync-images.sh          die ausgelieferten Vorgaben (im Repository)
    /var/lib/pxeweb/quellen.env   was hier eingetragen wurde

Das Skript liest zuerst seine eigenen Vorgaben und danach die eigene Datei
-- was hier steht, gewinnt also. Und sie liegt ausserhalb des
Projektordners, weil install.sh mit "rsync --delete" arbeitet: alles im
Projektordner waere beim naechsten Update ohne Warnung weg.

Die Vorgaben werden aus sync-images.sh gelesen statt sie hier ein zweites
Mal zu pflegen. Das Format dort ist bewusst schlicht (NAME="wert", mit
${...} auf zuvor gesetzte Werte), sonst waere das Auslesen fragil.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path

import yaml

_DB = Path(os.environ.get("PXE_DB", "/var/lib/pxeweb/pxeweb.db"))

# Hier landet, was in der Weboberflaeche eingetragen wird.
EIGEN = Path(os.environ.get("PXE_QUELLEN", "") or _DB.parent / "quellen.env")

# Die ausgelieferten Vorgaben. Im Betrieb liegt das Skript unter /opt,
# beim Entwickeln im Projektordner.
_SUCHPFADE = [
    Path(os.environ.get("PXE_SYNC_SKRIPT", "")),
    Path("/opt/pxe-setup/sync-images.sh"),
    Path(__file__).resolve().parent.parent / "setup" / "sync-images.sh",
]

_ZUWEISUNG = re.compile(r'^([A-Z][A-Z0-9_]*)="([^"]*)"\s*(?:#.*)?$')
_VERWEIS = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")

# Was beim Pruefen als Datei durchgeht. Kleiner ist mit Sicherheit die
# HTML-Seite mit dem Downloadknopf darauf -- der haeufigste Fehler beim
# Kopieren einer Adresse von einer Downloadseite.
MIN_GROESSE = 1024 * 1024

# Wo diese Grenze nicht taugt. Memtest ist ein ZIP mit zwei winzigen
# Programmen darin, rund 220 KB -- die Grenze meldete es als
# "vermutlich eine Downloadseite", obwohl es die richtige Datei ist. Eine
# Downloadseite ist trotzdem noch deutlich kleiner.
MIN_EIGEN = {
    "MEMTEST_ZIP_URL": 50 * 1024,
}

# Zeichen, mit denen sich in einer von der Shell eingelesenen Datei
# Befehle unterschieben liessen. In einer Download-Adresse kommt
# keines davon vor -- also ablehnen statt maskieren.
VERBOTEN = set(chr(34) + chr(36) + chr(96)) | {chr(92), chr(10), chr(13)}

# Nicht jede Quelle ist eine Datei. Bei einigen haengt sync-images.sh den
# eigentlichen Dateinamen erst an -- die Adresse selbst liefert dann nur
# einen Verzeichnisindex, und dessen Groesse sagt nichts aus. Geprueft wird
# deshalb eine Datei darunter, von der wir wissen, dass es sie geben muss.
#
# Ein leerer Wert heisst: die Adresse selbst pruefen, aber ohne
# Groessenpruefung -- dort ist der Index tatsaechlich die Nutzlast.
# Mehrversionige Systeme: welche Adresse zu welcher Versionsliste gehoert.
# In der Adresse steht {version} als Platzhalter -- zum Pruefen wird die
# erste Version der Liste eingesetzt, sonst liefe die Pruefung gegen einen
# Platzhalter und meldete stets 404.
# Rocky ist der eine Fall, in dem die Vorgabe kein {version} enthaelt:
# dort steht nur die Basis, und sync-images.sh haengt den Rest an. Damit
# die Oberflaeche dieselbe Adresse zeigt, steht der Rest hier.
ROCKY_PFAD = "/{version}/BaseOS/x86_64/os/images/pxeboot"

VERSIONSLISTE = {
    "DEBIAN_URL": "DEBIAN_VERSIONS",
    "DEBIAN_LIVE_ISO_URL": "DEBIAN_LIVE_VERSIONS",
    "FEDORA_URL": "FEDORA_VERSIONS",
    "LEAP_URL": "LEAP_VERSIONS",
    "UBUNTU_ISO_URL": "UBUNTU_VERSIONS",
    "ROCKY_BASE": "ROCKY_VERSIONS",
    # Die vier Werkzeuge tragen ihre Nummer im Dateinamen. Frueher musste
    # dafuer die ganze Adresse ersetzt werden; jetzt sind sie mehrversionig
    # wie die Distributionen.
    "SYSRESC_ISO_URL": "SYSRESC_VERSIONS",
    "GPARTED_ISO_URL": "GPARTED_VERSIONS",
    "CLONEZILLA_ISO_URL": "CLONEZILLA_VERSIONS",
    "MEMTEST_ZIP_URL": "MEMTEST_VERSIONS",
}

# Erlaubt in einer Versionsliste: durch Leerzeichen getrennte Angaben aus
# Ziffern, Buchstaben, Punkt, Strich. Alles andere landete in Pfaden und
# Adressen -- da hat nichts Ausgefallenes zu suchen.
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Welche Komponente von sync-images.sh eine Quelle holt. Nicht ableitbar:
# LEAP_URL und TUMBLEWEED_URL teilen sich "opensuse", und ROCKY_BASE
# heisst anders als "rocky". Ausdruecklich hingeschrieben -- test_katalog
# prueft, dass keine Quelle ohne Komponente dasteht.
KOMPONENTE = {
    "DEBIAN_URL": "debian",
    "DEBIAN_LIVE_ISO_URL": "debian-live",
    "UBUNTU_ISO_URL": "ubuntu",
    "MINT_MIRROR": "mint",
    "FEDORA_URL": "fedora",
    "LEAP_URL": "opensuse",
    "TUMBLEWEED_URL": "opensuse",
    "ROCKY_BASE": "rocky",
    "SYSRESC_ISO_URL": "systemrescue",
    "GPARTED_ISO_URL": "gparted",
    "CLONEZILLA_ISO_URL": "clonezilla",
    "MEMTEST_ZIP_URL": "memtest",
    "SHREDOS_ISO_URL": "shredos",
}

# Was eine Quelle sagt, fuer die keine Ausgabe eingetragen ist. Kein
# Fehler, sondern der Auslieferungszustand -- und deshalb ein Satz, der
# den naechsten Schritt nennt statt eines Fehlercodes.
LEER_MELDUNG = "noch keine Ausgabe — „Prüfen“ trägt die neueste ein"

PRUEFPFAD = {
    "DEBIAN_URL": "linux",
    "FEDORA_URL": "vmlinuz",
    "LEAP_URL": "linux",
    "TUMBLEWEED_URL": "linux",
    # Geprueft wird die Adresse einer Ausgabe, nicht die Basis: dort steht
    # der Weg zum pxeboot-Ordner schon drin, es fehlt nur die Datei.
    "ROCKY_BASE": "vmlinuz",
    # Mint liest den Verzeichnisindex des Spiegels aus, um die neueste
    # Ausgabe zu finden. Hier ist die Seite selbst das Gesuchte.
    "MINT_MIRROR": "",
}


def skript() -> Path | None:
    for pfad in _SUCHPFADE:
        if pfad and pfad.is_file():
            return pfad
    return None


def _werte_aus(text: str) -> dict[str, str]:
    """NAME="wert"-Zeilen einlesen und ${...} aufloesen."""
    werte: dict[str, str] = {}
    for zeile in text.splitlines():
        treffer = _ZUWEISUNG.match(zeile.strip())
        if not treffer:
            continue
        name, roh = treffer.group(1), treffer.group(2)
        werte[name] = _VERWEIS.sub(lambda m: werte.get(m.group(1), m.group(0)), roh)
    return werte


def alle_werte() -> dict[str, str]:
    """Alle Variablen aus dem Skript, ueberschrieben durch die eigenen."""
    pfad = skript()
    werte = {}
    if pfad is not None:
        try:
            werte = _werte_aus(pfad.read_text(encoding="utf-8"))
        except OSError:
            werte = {}
    werte.update(eigene())
    return werte


def liste(name: str) -> list[str]:
    """Eine Versionsliste als Einzelwerte, in der eingetragenen Reihenfolge.

    Doppelte fliegen hier heraus und nicht erst beim Speichern: die Datei
    laesst sich auch von Hand bearbeiten, und aus zwei gleichen Angaben
    entstuenden zwei Menuepunkte mit derselben Sprungmarke.
    """
    gesehen, sauber = set(), []
    for v in alle_werte().get(name, "").split():
        if VERSION_RE.match(v) and v not in gesehen:
            gesehen.add(v)
            sauber.append(v)
    return sauber


def versionen() -> list[dict]:
    """Die pflegbaren Versionslisten, fuer die Weboberflaeche."""
    vorgabe, eigen = _versionsvorgaben(), eigene()
    liste_ = []
    for name in sorted(vorgabe):
        liste_.append({
            "name": name,
            "wert": eigen.get(name, vorgabe[name]),
            "vorgabe": vorgabe[name],
            "geaendert": name in eigen and eigen[name] != vorgabe[name],
            "adresse": next((u for u, v in VERSIONSLISTE.items() if v == name), ""),
        })
    return liste_


# Pruefstand und Adressverlauf. Neben der Datenbank, nicht im
# Projektordner -- install.sh spiegelt den mit "rsync --delete".
STAND_DATEI = Path(os.environ.get("PXE_QUELLENSTAND", "")
                   or _DB.parent / "quellenstand.yaml")

# So viele fruehere Adressen werden aufgehoben. Mehr braucht niemand: Der
# Verlauf beantwortet "was stand da vorher", nicht "was stand da 2019".
VERLAUF_TIEFE = 5


def _stand_lesen() -> dict:
    try:
        with STAND_DATEI.open(encoding="utf-8") as fh:
            roh = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return roh if isinstance(roh, dict) else {}


def _stand_schreiben(daten: dict) -> None:
    STAND_DATEI.parent.mkdir(parents=True, exist_ok=True)
    vorlaeufig = STAND_DATEI.with_suffix(".yaml.neu")
    with vorlaeufig.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(daten, fh, allow_unicode=True, sort_keys=True)
    os.replace(vorlaeufig, STAND_DATEI)


def stand(name: str) -> dict:
    """Was beim letzten Pruefen dieser Quelle herauskam.

    Gespeichert, damit die Ampel schon beim Oeffnen der Seite leuchtet.
    Ohne das muesste die Seite bei jedem Aufruf zwoelf Anbieter abklappern
    -- langsam, und die Anbieter haetten es auch nicht verdient.

    Mit Zeitpunkt und geprueter Adresse: Eine Ampel ohne Datum behauptet,
    sie sei von jetzt. Und wer die Adresse seither geaendert hat, soll
    sehen, dass sich der Befund auf die alte bezieht.
    """
    eintrag = _stand_lesen().get(name, {})
    return eintrag if isinstance(eintrag, dict) else {}


def merke_stand(name: str, befund: dict, adresse: str = "") -> None:
    """Das Ergebnis einer Pruefung festhalten."""
    daten = _stand_lesen()
    eintrag = dict(daten.get(name) or {})
    eintrag["stand"] = {
        "ok": bool(befund.get("ok")),
        "kein_netz": bool(befund.get("kein_netz")),
        # Muss mit: Die Karte leuchtet aus dem Gespeicherten, nicht aus
        # dem Befund von eben. Fehlte "leer" hier, staende die Ampel beim
        # naechsten Aufbau der Seite auf Rot -- mit dem richtigen Satz
        # daneben ("noch keine Ausgabe") und der falschen Farbe davor.
        # Ein frisch aufgesetzter Server begruesste seinen Betreiber dann
        # mit zehn roten Ampeln, von denen keine einen Fehler meint.
        "leer": bool(befund.get("leer")),
        "meldung": str(befund.get("meldung", "")),
        "adresse": adresse or str(befund.get("geprueft", "")),
        "zeit": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    daten[name] = eintrag
    _stand_schreiben(daten)


def merke_nummern(name: str, nummern: dict) -> None:
    """Was der Anbieter selbst ueber seine Ausgaben sagt, festhalten.

    Bisher nur Debian, und dort ist es keine Spielerei: Debians Pfade
    kennen ausschliesslich den Codenamen -- "dists/trixie/" antwortet,
    "dists/13.6/" gibt es nicht. In der Ausgaben-Zeile steht deshalb
    "trixie", waehrend beim Live-Abbild daneben "13.6.0" steht, denn dort
    ist die Nummer der Dateiname. Nebeneinander gelesen sieht das aus wie
    unsere Ungereimtheit, ist aber Debians.

    Beim Pruefen liest der Server ohnehin Debians Release-Datei, und darin
    steht die Nummer neben dem Codenamen. Sie stand danach nur im
    Meldungstext und war beim naechsten Seitenaufbau weg -- jetzt bleibt
    sie und kann in der Zeile daneben stehen.

    Geschrieben wird nur, was der Anbieter geliefert hat: Bleibt eine
    Auskunft aus, gilt weiter die zuletzt bekannte, statt sie zu loeschen.
    Eine Karte, die eine Nummer nach einem Netzaussetzer verliert, sieht
    aus, als waere etwas kaputt.
    """
    nummern = {k: v for k, v in (nummern or {}).items() if k and v}
    if not nummern:
        return
    daten = _stand_lesen()
    eintrag = dict(daten.get(name) or {})
    eintrag["nummern"] = {**(eintrag.get("nummern") or {}), **nummern}
    daten[name] = eintrag
    _stand_schreiben(daten)


def nummer(name: str, version: str) -> str:
    """Die Nummer, die der Anbieter zu dieser Ausgabe genannt hat."""
    gemerkt = stand(name).get("nummern")
    if not isinstance(gemerkt, dict):
        return ""
    return str(gemerkt.get(version, "") or "")


# Umgekehrt zu VERSIONSLISTE: von der Ausgabenliste zurueck zur Quelle.
# Gebraucht, wenn jemand die Liste aendert -- geurteilt wurde ueber die
# Quelle, und die heisst anders.
_QUELLE_ZU_LISTE = {liste: adresse for adresse, liste in VERSIONSLISTE.items()}


def vergiss_stand(name: str) -> None:
    """Das gespeicherte Urteil ueber eine Quelle wegwerfen.

    Die Ampel in der Karte leuchtet aus dem Gespeicherten -- die Seite
    fragt beim Aufbau ja nicht dreizehn Anbieter. Damit ist jedes Urteil
    eine Momentaufnahme, und sobald sich aendert, worueber geurteilt
    wurde, ist sie hinfaellig: Wer eine Ausgabe eintraegt, hat eine
    Quelle in Betrieb genommen, ueber die eben noch "nicht in Betrieb"
    stand; wer die letzte entfernt, das Gegenteil.

    Weggeworfen und nicht neu geprueft: Nachpruefen hiesse, dass ein
    Speichern-Knopf im Hintergrund ins Netz geht und daran haengen bleibt.
    Ohne Eintrag zeigt die Karte gar kein Abzeichen -- also "noch nicht
    geprueft", und das stimmt dann auch. Ein Klick auf "Pruefen" stellt
    sie neu.

    Der Verlauf frueherer Adressen bleibt: Der ist eine Chronik von
    Entscheidungen und veraltet nicht.
    """
    quelle = _QUELLE_ZU_LISTE.get(name, name)
    daten = _stand_lesen()
    eintrag = daten.get(quelle)
    if not isinstance(eintrag, dict) or "stand" not in eintrag:
        return
    eintrag = dict(eintrag)
    eintrag.pop("stand", None)
    if eintrag:
        daten[quelle] = eintrag
    else:
        daten.pop(quelle, None)
    _stand_schreiben(daten)


def verlauf(name: str) -> list[dict]:
    """Frueher benutzte Adressen dieser Quelle, neueste zuerst."""
    eintraege = stand(name).get("verlauf") or []
    return [e for e in eintraege if isinstance(e, dict)]


def merke_verlauf(name: str, alte_adresse: str) -> None:
    """Eine ersetzte Adresse aufheben.

    Geschrieben wird beim **Ersetzen**, nicht bei einer fehlgeschlagenen
    Pruefung. Eine Adresse ist nicht kaputt, nur weil eine Pruefung
    scheitert -- Spiegel werden umgebaut, Anbieter haben Aussetzer. Wuerde
    jeder Fehlschlag hier landen, stuende bald zwanzigmal dieselbe Adresse
    darin und der Verlauf waere ein Stoerungsprotokoll statt einer Liste
    von Entscheidungen.
    """
    alte_adresse = (alte_adresse or "").strip()
    if not alte_adresse:
        return
    daten = _stand_lesen()
    eintrag = dict(daten.get(name) or {})
    bisher = [e for e in (eintrag.get("verlauf") or []) if isinstance(e, dict)]
    if bisher and bisher[0].get("adresse") == alte_adresse:
        return                       # zweimal dasselbe ist kein Verlauf
    bisher.insert(0, {
        "adresse": alte_adresse,
        "bis": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    eintrag["verlauf"] = bisher[:VERLAUF_TIEFE]
    daten[name] = eintrag
    _stand_schreiben(daten)


def schluessel(adresse: str, version: str) -> str:
    """Der Name, unter dem die Adresse einer einzelnen Ausgabe liegt.

    Aus LEAP_URL und 16.1 wird LEAP_URL_16_1. Ersetzt wird dabei alles,
    was in einem Shell-Variablennamen nicht vorkommen darf -- nicht nur
    der Punkt.

    Der Bindestrich war der Grund: Clonezilla heisst "3.3.3-15", GParted
    "1.8.1-3". Daraus wurde CLONEZILLA_ISO_URL_3_3_3-15, und das ist kein
    gueltiger Variablenname. In sync-images.sh brach die indirekte
    Expansion darueber ab ("invalid variable name"), url_fuer() lieferte
    nichts zurueck, und curl bekam eine leere Adresse -- "Holen" meldete
    einen fehlgeschlagenen Download, waehrend dieselbe Adresse in der
    Download-Karte einwandfrei lief. Genau so ist es aufgefallen.

    Stand so ein Name in quellen.env, ging zusaetzlich sein Wert
    verloren: Die Shell liest die Zeile beim "source" nicht als Zuweisung,
    sondern als Befehl, findet ihn nicht und macht weiter. Der Rest der
    Datei gilt also -- die eine Adresse fehlt einfach.

    Dieselbe Regel steht in url_fuer(); wer eine aendert, aendert beide.
    """
    return f"{adresse}_{re.sub(r'[^A-Za-z0-9_]', '_', version)}"


def _alter_schluessel(adresse: str, version: str) -> str:
    """Wie der Name bis August 2026 gebildet wurde -- nur Punkte ersetzt.

    Gebraucht beim Lesen: Wer vor der Korrektur eine eigene Adresse fuer
    GParted 1.8.1-3 eingetragen hat, hat sie unter dem alten Namen stehen.
    Sie soll nicht stillschweigend verschwinden, nur weil die Regel
    genauer geworden ist -- beim naechsten Speichern wandert sie ohnehin
    auf den neuen.
    """
    return f"{adresse}_{version.replace('.', '_')}"


def ausgabenmuster(adresse: str) -> str:
    """Das Muster, aus dem die Adresse einer Ausgabe entsteht.

    Bei Rocky steht in der Quelle nur die Basis: sync-images.sh haengt den
    Rest selbst an. Fuer die Oberflaeche muss der ganze Weg dastehen --
    sonst schlaegt sie bei einer neuen Ausgabe die halbe Adresse vor.
    """
    muster = eigene().get(adresse) or vorgaben().get(adresse, "")
    if muster and "{version}" not in muster and adresse == "ROCKY_BASE":
        muster = muster.rstrip("/") + ROCKY_PFAD
    return muster


def aus_muster(adresse: str, version: str) -> str:
    """Was das Muster fuer diese Ausgabe ergibt -- ohne eigene Adresse."""
    return ausgabenmuster(adresse).replace("{version}", version)


def fuer_ausgabe(adresse: str, version: str) -> str:
    """Die Adresse, unter der eine bestimmte Ausgabe geholt wird.

    Zuerst die eigene, sonst die Version ins Muster eingesetzt. Das Muster
    ist eine Wette darauf, dass die Verzeichnisstruktur des Distributors
    bleibt; benennt Fedora eines Tages "Everything" um, sind sonst alle
    Ausgaben auf einmal tot -- auch die, die vorher liefen.
    """
    eigen = eigene()
    fest = (eigen.get(schluessel(adresse, version))
            or eigen.get(_alter_schluessel(adresse, version)))
    return fest or aus_muster(adresse, version)


def setze_ausgabe(adresse: str, version: str, url: str) -> None:
    """Einer einzelnen Ausgabe ihre eigene Adresse geben."""
    if adresse not in VERSIONSLISTE:
        raise ValueError("Keine mehrversionige Quelle: " + adresse)
    if not VERSION_RE.match(version):
        raise ValueError("Ungueltige Ausgabe: " + version)
    eigen = eigene()
    marke = schluessel(adresse, version)
    neu_ = _pruefe_url(url)
    vorher = fuer_ausgabe(adresse, version)
    if vorher and vorher != neu_:
        merke_verlauf(marke, vorher)
    eigen[marke] = neu_
    _schreibe(eigen)
    if vorher != neu_:
        vergiss_stand(adresse)


def loesche_ausgabe(adresse: str, version: str) -> None:
    """Die eigene Adresse wieder wegnehmen -- es gilt dann das Muster."""
    eigen = eigene()
    weg = [eigen.pop(name, None) for name in
           (schluessel(adresse, version), _alter_schluessel(adresse, version))]
    if any(w is not None for w in weg):
        _schreibe(eigen)
        # Danach gilt wieder das Muster -- also eine andere Adresse als
        # die, ueber die geurteilt wurde.
        vergiss_stand(adresse)


def ausgaben(adresse: str) -> list[dict]:
    """Alle Ausgaben einer Quelle mit ihrer Adresse, fuer die Oberflaeche."""
    listenname = VERSIONSLISTE.get(adresse)
    if not listenname:
        return []
    eigen = eigene()
    # Einmal fuer die ganze Quelle, nicht je Ausgabe: stand() liest die
    # Datei jedes Mal neu und wertet sie aus. Bei zwoelf Quellen mit
    # mehreren Ausgaben waere dieselbe kleine Datei sonst dreissigmal je
    # Seitenaufbau geparst -- fuer eine Angabe, die sich beim Pruefen
    # aendert und sonst nie.
    gemerkt = stand(adresse).get("nummern")
    gemerkt = gemerkt if isinstance(gemerkt, dict) else {}
    return [{
        "version": v,
        "url": fuer_ausgabe(adresse, v),
        # Was der Anbieter selbst zu dieser Ausgabe gesagt hat -- heute nur
        # Debian, siehe merke_nummern().
        "nummer": str(gemerkt.get(v, "") or ""),
        # Steht sie eigens da oder kommt sie aus dem Muster? Das ist der
        # Unterschied zwischen "geprueft und festgehalten" und "geraten".
        "eigen": (schluessel(adresse, v) in eigen
                  or _alter_schluessel(adresse, v) in eigen),
    } for v in liste(listenname)]


def _versionsvorgaben() -> dict[str, str]:
    pfad = skript()
    if pfad is None:
        return {}
    try:
        werte = _werte_aus(pfad.read_text(encoding="utf-8"))
    except OSError:
        return {}
    return {n: w for n, w in werte.items() if n in VERSIONSLISTE.values()}


def vorgaben() -> dict[str, str]:
    """Die ausgelieferten Adressen, nach Namen."""
    pfad = skript()
    if pfad is None:
        return {}
    try:
        werte = _werte_aus(pfad.read_text(encoding="utf-8"))
    except OSError:
        return {}
    return {n: w for n, w in werte.items() if w.startswith(("http://", "https://"))}


def eigene() -> dict[str, str]:
    """Was in der Weboberflaeche eingetragen wurde."""
    try:
        return _werte_aus(EIGEN.read_text(encoding="utf-8"))
    except OSError:
        return {}


def alle() -> list[dict]:
    """Alle Quellen mit Vorgabe, geltendem Wert und Herkunft."""
    vorgabe, eigen = vorgaben(), eigene()
    liste = []
    for name in sorted(vorgabe):
        wert = eigen.get(name, vorgabe[name])
        liste.append({
            "name": name,
            "url": wert,
            "vorgabe": vorgabe[name],
            "geaendert": name in eigen and eigen[name] != vorgabe[name],
            # Basisadresse? Dann steht hier, was zum Pruefen angehaengt wird.
            "basis": name in PRUEFPFAD,
            "pruefdatei": PRUEFPFAD.get(name, ""),
        })
    return liste


def _verzeichnis_ueber(muster: str) -> str:
    """Das Verzeichnis, in dem die Ausgaben nebeneinander liegen.

    Alles vor dem ersten {version} -- und wenn die Version im Dateinamen
    steckt, bis zum Schrägstrich davor:

        .../releases/{version}/Everything/...  ->  .../releases/
        .../gparted-live-{version}-amd64.iso   ->  .../gparted/
    """
    if "{version}" not in muster:
        return ""
    davor = muster.split("{version}")[0]
    return davor if davor.endswith("/") else davor.rsplit("/", 1)[0] + "/"


# Was in einem Verzeichnisindex wie eine Ausgabe aussieht: beginnt mit
# einer Ziffer, danach Ziffern, Punkte, Striche. "24.04/" faellt darunter,
# "Everything/" oder "sha256sum.txt" nicht.
_AUSGABE_RE = re.compile(r"^\d[\d.\-]*$")

# Wo das zu grob ist. Rockys Index fuehrt die Reihen und die
# Punktversionen nebeneinander -- 8/ 9/ 10/ neben 8.4/ ... 10.2/. Der
# Katalog benutzt die Reihen; eine Punktversion daraus waere ein zweiter
# Eintrag fuer dieselbe Ausgabe, mit eigenem Verzeichnis und eigenem
# Menuepunkt. Also nur die punktlosen gelten lassen.
AUSGABENFORM = {
    "ROCKY_BASE": re.compile(r"^\d+$"),
}


# Wo nachgesehen wird, wenn das Verzeichnis ueber den Ausgaben nichts
# hergibt. Jeder Eintrag hier ist die Antwort auf einen konkreten Befund:
SUCHORT = {
    # download.fedoraproject.org ist ein Verteiler und antwortet je nach
    # gewaehltem Spiegel mal mit einem Index, mal mit 404. Der Master
    # hat immer einen.
    "FEDORA_URL": "https://dl.fedoraproject.org/pub/fedora/linux/releases/",
    # SourceForge schickt auf ein Verzeichnis eine Downloadseite. Je
    # Projekt gibt es aber einen Feed, in dem die Dateien stehen.
    "GPARTED_ISO_URL":
        "https://sourceforge.net/projects/gparted/rss?path=/gparted-live-stable",
    "CLONEZILLA_ISO_URL":
        "https://sourceforge.net/projects/clonezilla/rss?path=/clonezilla_live_stable",
    # Beide CDNs geben ihre Verzeichnisse nicht preis (403). Die
    # Projektseiten nennen die Ausgaben im Dateinamen.
    "SYSRESC_ISO_URL": "https://www.system-rescue.org/Download/",
    "MEMTEST_ZIP_URL": "https://www.memtest.org/",
}


def _dateimuster(muster: str) -> re.Pattern | None:
    """Aus dem Adressmuster ein Suchmuster fuer Dateinamen bauen.

    Aus "gparted-live-{version}-amd64.iso" wird ein Ausdruck, der in einer
    beliebigen Seite genau diese Dateinamen findet. So laesst sich auch
    dort nachsehen, wo es keinen Verzeichnisindex gibt -- in einem Feed
    oder auf einer Downloadseite.
    """
    datei = muster.rsplit("/", 1)[-1]
    if "{version}" not in datei:
        return None
    davor, _, danach = datei.partition("{version}")
    danach = danach.split("{version}")[0]
    return re.compile(re.escape(davor) + r"(\d[\d.\-]*?)" + re.escape(danach))


# Debians Ausgaben stehen in keinem Verzeichnisindex. Unter "dists/"
# liegen Woerter -- trixie, bookworm, sid, stable --, und die Suche weiter
# unten erkennt eine Ausgabe an ihrer Ziffer. Debian sagt es dafuer selbst,
# in einer Textdatei je Suite:
#
#     Suite: stable      Version: 13.6      Codename: trixie
#     Suite: oldstable   Version: 12.15     Codename: bookworm
#
# Gefragt wird nach "stable" und "oldstable": die aktuelle und die
# vorhergehende Ausgabe, nach Debians eigener Auskunft. Damit braucht es
# hier auch kein "hoeher als" -- welche die neuere ist, sagt der Name der
# Suite. Ein Zahlenvergleich waere hier sogar falsch: "forky" steht
# alphabetisch vor "trixie", ist aber die spaetere Ausgabe.
DEBIAN_SUITEN = ("stable", "oldstable")


def _debian_release(text: str) -> dict:
    """Codename und Version aus einer Debian-Release-Datei lesen."""
    werte = {}
    for zeile in text.splitlines():
        if ":" not in zeile:
            continue
        feld, _, wert = zeile.partition(":")
        if feld.strip() in ("Codename", "Version", "Suite"):
            werte[feld.strip().lower()] = wert.strip()
    return werte


def _debian_ausgaben(adresse: str, zeitlimit: float) -> dict:
    """Debian nach seinen Ausgaben fragen -- eine Textdatei je Suite."""
    basis = _verzeichnis_ueber(ausgabenmuster(adresse))
    if not basis:
        return {"ok": False, "gefunden": [], "neu": [], "geprueft": "",
                "meldung": "Für diese Quelle gibt es keine Ausgaben."}

    netz = erreichbar(basis)
    if not netz["ok"]:
        return {"ok": False, "gefunden": [], "neu": [], "geprueft": basis,
                "kein_netz": True, "meldung": netz["meldung"]}

    gefunden, teile, letzter, aktuell = [], [], "", ""
    nummern: dict = {}
    for suite in DEBIAN_SUITEN:
        ziel = basis.rstrip("/") + "/" + suite + "/Release"
        anfrage = urllib.request.Request(ziel, headers={"User-Agent": "pxeweb/1.0"})
        try:
            with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:
                werte = _debian_release(antwort.read(64 * 1024).decode("utf-8", "replace"))
        except Exception as fehler:                  # Netz, DNS, TLS, 404
            letzter = f"{suite}: {fehler}"
            continue
        name = werte.get("codename", "")
        if not VERSION_RE.match(name or ""):
            letzter = f"{suite}: keine brauchbare Angabe"
            continue
        if name not in gefunden:
            gefunden.append(name)
        gesagte = werte.get("version", "")
        if gesagte:
            nummern[name] = gesagte
        if suite == "stable":
            aktuell = name
        teile.append(f"{suite} ist {name}" + (f" (Debian {gesagte})" if gesagte else ""))

    if not gefunden:
        return {"ok": False, "gefunden": [], "neu": [], "geprueft": basis,
                "meldung": "Debian antwortet nicht auf die Frage nach seinen "
                           "Ausgaben" + (f" — {letzter}" if letzter else "")}

    schon = liste(VERSIONSLISTE.get(adresse, ""))
    neu = [v for v in gefunden if v not in schon]
    # Ohne Doppelpunkt: Die Oberflaeche schneidet die Meldung sonst dort ab
    # und haengt die anklickbaren Ausgaben an -- so bleibt der ganze Satz
    # stehen und die Knoepfe kommen dahinter.
    return {"ok": True, "gefunden": gefunden, "neu": neu, "geprueft": basis,
            # Codename -> Nummer, wie Debian sie selbst nennt.
            "nummern": nummern,
            # Welcher davon die aktuelle Ausgabe ist. "oldstable" wird
            # zwar gefunden, ist aber nicht neuer -- von selbst aufnehmen
            # darf man nur den, der wirklich vorne steht.
            "aktuell": aktuell,
            "meldung": ", ".join(teile)
                       + ("" if neu else " — beides schon eingetragen")}


def hoehere_als(gefunden: list[str], schon: list[str]) -> list[str]:
    """Was davon ueber allem steht, was schon eingetragen ist.

    "Neu" heisst hoeher als die hoechste eingetragene -- nicht bloss "steht
    noch nicht in der Liste". Sonst meldete GParted zehn Funde, obwohl alle
    zehn aelter sind als das, was schon da ist.

    Steht noch gar nichts, ist alles offen: Ein frisch aufgesetzter Server
    hat leere Listen, und dort soll die erste Ausgabe angeboten werden.

    Eine eigene Funktion, seit auch selbst angelegte Eintraege danach
    gefragt werden -- die haben keine Versionsliste in sync-images.sh,
    sondern ihre Ausgaben liegen als eigene Eintraege da. Dieselbe Regel
    an zwei Stellen hinzuschreiben hiesse, sie beim naechsten Mal an einer
    zu aendern.
    """
    hoechste = max((_sortierschluessel(v) for v in schon), default=None)
    return [v for v in gefunden
            if v not in schon
            and (hoechste is None or _sortierschluessel(v) > hoechste)]


def neueste_offene(befund: dict, name: str) -> str:
    """Die eine Ausgabe, die von selbst aufgenommen werden darf.

    Nicht jede gefundene ist eine neue: Debians "oldstable" ist aelter als
    das, was schon dasteht, und bei den Werkzeugen taucht im Index auch
    Vergangenes auf. Genommen wird deshalb bei Debian ausdruecklich der
    Codename von "stable", sonst die hoechste Nummer -- und nur, wenn sie
    noch nicht eingetragen ist.
    """
    offen = befund.get("neu") or []
    if not offen:
        return ""
    aktuell = befund.get("aktuell")
    if aktuell:
        return aktuell if aktuell in offen else ""
    return sorted(offen, key=_sortierschluessel, reverse=True)[0]


def _zahlenhaft(version: str) -> bool:
    """Besteht die Ausgabe nur aus Zahlen? Dann ist sie vergleichbar.

    "16.1" ja, "trixie" nein. Der Unterschied entscheidet, ob gerechnet
    werden darf.
    """
    return bool(re.fullmatch(r"[0-9][0-9.\-]*", version))


def wirklich_neuer(name: str, befund: dict) -> str:
    """Die eine Ausgabe, die ueber allem steht, was schon eingetragen ist.

    Nicht jede gefundene ist eine neue. Im Rocky-Verzeichnis liegen 10, 9
    und 8 nebeneinander; Debian nennt sein oldstable, und bei openSUSE
    steht noch 42.3 von 2017 herum. Wer alle drei zum Anklicken anbietet,
    stellt jemanden vor eine Frage, die er nicht gestellt bekommen sollte:
    Wer Rocky 9 ausdruecklich will, weiss das und traegt es ueber "Neue
    Version" ein.

    Deshalb gilt ueberall dieselbe Regel -- in der Karte wie beim
    Waechter: hoechstens eine Ausgabe, und nur eine, die ueber allem
    Eingetragenen steht. Nennt der Anbieter selbst eine als die aktuelle
    (Debians "stable", openSUSEs Zustand), gilt seine Auskunft --
    Codenamen lassen sich nicht der Groesse nach sortieren, "forky" steht
    alphabetisch vor "trixie" und ist trotzdem neuer.
    """
    schon = [a["version"] for a in ausgaben(name) if a.get("version")]
    # Was schon dasteht, ist kein Vorschlag mehr. Neu gerechnet und nicht
    # aus dem Befund uebernommen: Der entstand beim Nachsehen, und seither
    # kann eine Ausgabe dazugekommen sein -- die eben aufgenommene.
    offen = [v for v in (befund.get("neu") or []) if v not in schon]
    dazu = neueste_offene({**befund, "neu": offen}, name)
    if not dazu:
        return ""
    if not schon:
        # Nichts eingetragen: Dann ist die neueste gefundene die, mit der
        # dieses System in Betrieb geht -- der Normalfall auf einem frisch
        # aufgesetzten Server.
        return dazu
    if _zahlenhaft(dazu) and all(_zahlenhaft(v) for v in schon):
        return dazu if neuer_als(dazu, schon) else ""
    # Sonst gilt, was der Anbieter selbst seine aktuelle nennt. Ohne eine
    # solche Auskunft wird geschwiegen -- eine gefundene Ausgabe allein
    # ist kein Befund, sonst meldete Debian sein oldstable als Neuigkeit.
    return dazu if befund.get("aktuell") else ""


def echte_adresse(name: str, version: str, zeitlimit: float = 20.0) -> str:
    """Die Adresse dieser Ausgabe suchen, wenn das Muster daneben liegt.

    Ubuntus Fall, und er ist ein anderer als Debians: Die Ausgabe bleibt,
    der Dateiname aendert sich. Unter releases.ubuntu.com/24.04/ liegt
    laengst "ubuntu-24.04.4-live-server-amd64.iso"; was das Muster
    erwartet -- "ubuntu-24.04-live-server-amd64.iso" -- gibt es dort nicht
    mehr. Bei Debian entsteht aus einer neuen Ausgabe ein neuer Eintrag,
    hier bleibt der Eintrag und nur seine Adresse veraltet.

    Gesucht wird im Verzeichnis der Ausgabe nach einem Dateinamen, der zum
    Muster passt -- dasselbe Suchmuster, mit dem auch Ausgaben in einem
    Feed gefunden werden. Genommen wird der hoechste Treffer: In 24.04/
    liegen 24.04.3 und 24.04.4 nebeneinander.

    Zurueck kommt eine ganze Adresse oder "" -- eingetragen wird sie
    hier nicht.
    """
    muster = ausgabenmuster(name)
    if "{version}" not in muster:
        return ""
    ordner = aus_muster(name, version).rsplit("/", 1)[0] + "/"
    dateien = _dateimuster(muster)
    if dateien is None:
        return ""

    anfrage = urllib.request.Request(ordner, headers={"User-Agent": "pxeweb/1.0"})
    try:
        with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:
            text = antwort.read(512 * 1024).decode("utf-8", "replace")
    except Exception:                                   # 404, Netz, alles
        return ""

    davor = muster.rsplit("/", 1)[-1].partition("{version}")[0]
    treffer = sorted({t for t in dateien.findall(text)
                      if t.startswith(version) or version.startswith(t)},
                     key=_sortierschluessel, reverse=True)
    if not treffer:
        return ""
    return ordner + davor + treffer[0] +         muster.rsplit("/", 1)[-1].partition("{version}")[2].split("{version}")[0]


def _gesamturteil(adressen: list[dict]) -> dict:
    """Aus den einzelnen Ausgaben ein Urteil ueber die Quelle machen.

    "Adresse gueltig" klingt wie eine Gesamtaussage -- dann muss sie auch
    eine sein: Bei zwei Rocky-Ausgaben sagte die Pruefung der ersten
    frueher nichts ueber die zweite.

    Drei Ausgaenge, nicht zwei. "leer" heisst, dass fuer diese Quelle
    keine Ausgabe eingetragen ist -- sie ist nicht in Betrieb, und das ist
    kein Fehler, sondern der Auslieferungszustand.
    """
    schlecht = [a for a in adressen if not a["ok"]]
    leer = bool(adressen) and all(a.get("leer") for a in adressen)
    return {
        "ok": not schlecht,
        "leer": leer,
        "meldung": (adressen[0]["meldung"] if leer
                    else ", ".join(f'{a["version"] or "Adresse"}: {a["meldung"]}'
                                   for a in (schlecht or adressen))),
    }


def durchleuchten(name: str, zeitlimit: float = 20.0,
                  aufnehmen: bool = False) -> dict:
    """Die drei Fragen zu einer Quelle auf einmal, in ihrer Reihenfolge.

        1. Kommt dieser Server ueberhaupt zum Anbieter?
        2. Gilt die Adresse, die eingetragen ist, noch?
        3. Gibt es beim Anbieter etwas Neueres?

    Die ersten beiden bauen aufeinander auf -- wo keine Verbindung
    besteht, ist der Pfad nicht das Problem, und weiter zu probieren
    verwirrt nur. Die dritte ist unabhaengig: Dass Debian 14 erschienen
    ist, macht die Adresse von Debian 13 nicht ungueltig. Sie liegt weiter
    unter dists/trixie/.

    Frueher waren das drei bis vier Knoepfe nebeneinander, und keiner
    sagte, in welcher Reihenfolge man sie druecken sollte.

    Der Befund wird festgehalten, damit die Ampel beim naechsten Oeffnen
    der Seite schon leuchtet.
    """
    werte = alle_werte()
    if name not in werte:
        raise ValueError("Unbekannte Quelle: " + name)

    adresse = werte[name]
    ergebnis = {"name": name, "adresse": adresse}

    ergebnis["verbindung"] = erreichbar(adresse)
    if not ergebnis["verbindung"]["ok"]:
        ergebnis["adresse_gilt"] = {"ok": False, "kein_netz": True,
                                    "meldung": "nicht geprüft — keine Verbindung"}
        ergebnis["neuere"] = {"ok": False, "kein_netz": True, "neu": [],
                              "meldung": "nicht gesucht — keine Verbindung"}
        merke_stand(name, ergebnis["adresse_gilt"], adresse)
        return ergebnis

    # Jede eingetragene Ausgabe einzeln, nicht nur die erste. "Adresse
    # gueltig" klingt wie eine Gesamtaussage -- dann muss sie auch eine
    # sein. Bei zwei Rocky-Ausgaben sagte die Pruefung der ersten bisher
    # nichts ueber die zweite, und die Zeile daneben hatte dafuer einen
    # eigenen Knopf, den man extra druecken musste.
    if name in VERSIONSLISTE:
        eingetragen = ausgaben(name)
        if not eingetragen:
            # Keine Ausgabe eingetragen: Diese Quelle ist nicht in Betrieb,
            # und es gibt nichts zu pruefen -- die Adresse, gegen die
            # geprueft wuerde, entstuende erst aus einer Ausgabe.
            #
            # Der Zweig muss hier stehen und nicht in pruefe(). Dort haengt
            # die Erkennung am "{version}" im Text, und ROCKY_BASE ist die
            # einzige Quelle ohne eines -- ihre Ausgabe wird an anderer
            # Stelle angehaengt (siehe fuer_ausgabe). Auf einem frisch
            # aufgesetzten Server meldete sie deshalb als einzige eine tote
            # Adresse, obwohl an ihr so wenig kaputt war wie an den zwoelf
            # anderen.
            ergebnis["adressen"] = [{
                "version": "", "url": adresse, "ok": False, "leer": True,
                "geprueft": adresse, "meldung": LEER_MELDUNG}]
        else:
            ergebnis["adressen"] = [
                {"version": a["version"], "url": a["url"],
                 **pruefe(a["url"], name, zeitlimit)}
                for a in eingetragen]

        # Eine Adresse, die nicht mehr gilt, muss nicht gleich falsch sein
        # -- oft hat nur der Dateiname sich geaendert. Ubuntu benennt bei
        # jeder Punktversion um: In 24.04/ liegt laengst
        # ubuntu-24.04.4-live-server-amd64.iso. Also im Verzeichnis der
        # Ausgabe nachsehen und die richtige eintragen, statt jemanden
        # eine Adresse abtippen zu lassen, die der Server selbst findet.
        if aufnehmen:
            for a in ergebnis["adressen"]:
                if a["ok"] or a.get("kein_netz") or not a["version"]:
                    continue
                echt = echte_adresse(name, a["version"], zeitlimit)
                if not echt or echt == a["url"]:
                    continue
                setze_ausgabe(name, a["version"], echt)
                a.update(pruefe(echt, name, zeitlimit), url=echt, repariert=True)
                ergebnis.setdefault("repariert", []).append(
                    {"version": a["version"], "url": echt})
    else:
        ergebnis["adressen"] = [{"version": "", "url": adresse,
                                 **pruefe(adresse, name, zeitlimit)}]

    ergebnis["adresse_gilt"] = _gesamturteil(ergebnis["adressen"])
    merke_stand(name, ergebnis["adresse_gilt"], adresse)

    if name in VERSIONSLISTE:
        ergebnis["neuere"] = neuere_ausgaben(name, zeitlimit)
        # Was der Anbieter ueber seine Ausgaben gesagt hat, bleibt --
        # sonst waere es beim naechsten Seitenaufbau wieder weg.
        merke_nummern(name, ergebnis["neuere"].get("nummern") or {})
        # Gefunden und noch nicht eingetragen? Dann eintragen -- die
        # Adresse entsteht aus dem Muster, wie beim Vorschlagsknopf, nur
        # ohne Klick. Geholt wird dabei nichts: Der Eintrag steht danach
        # auf "fehlt", bis der Abgleich laeuft.
        if aufnehmen and ergebnis["neuere"].get("ok"):
            dazu = wirklich_neuer(name, ergebnis["neuere"])
            if dazu:
                bisher = liste(VERSIONSLISTE[name])
                setze(VERSIONSLISTE[name], " ".join([dazu] + bisher))
                ergebnis["aufgenommen"] = {"version": dazu,
                                           "url": fuer_ausgabe(name, dazu)}

                # Und die Ampel noch einmal, mit der neuen Lage. Sie wurde
                # oben gestellt, als noch keine Ausgabe eingetragen war --
                # "nicht in Betrieb" stimmte da. Ohne diese Zeile steht das
                # danach neben der Ausgabe, die gerade dazugekommen ist,
                # und bliebe dort bis zum naechsten Pruefen stehen: eine
                # Karte, die sich selbst widerspricht.
                geprueft = {"version": dazu, "url": ergebnis["aufgenommen"]["url"],
                            **pruefe(ergebnis["aufgenommen"]["url"], name, zeitlimit)}
                ergebnis["adressen"] = [geprueft]
                ergebnis["adresse_gilt"] = _gesamturteil(ergebnis["adressen"])
                merke_stand(name, ergebnis["adresse_gilt"], adresse)

        # Was die Karte danach noch anbietet: hoechstens eine Ausgabe.
        _nur_das_neueste(name, ergebnis["neuere"])
    else:
        ergebnis["neuere"] = {"ok": False, "neu": [], "gefunden": [],
                              "meldung": "Diese Quelle hat nur eine Ausgabe."}
    return ergebnis


# openSUSE hat keinen Verzeichnisindex, den man lesen koennte:
# download.opensuse.org ist eine Web-Anwendung, und die Suche fand darin
# Zahlen, die keine Ausgaben sind -- unter anderem "42.3" von 2017, das
# durch den Zahlenvergleich hoeher stand als die aktuelle 16.x. Leap hat
# naemlich zweimal umnummeriert: 42.x, dann 15.x, jetzt 16.x.
#
# Es gibt aber eine maschinenlesbare Auskunft, und sie nennt sogar den
# Zustand:
#
#     {"Leap": [{"version": "16.1", "state": "Beta"},
#               {"version": "16.0", "state": "Stable"}, ...]}
#
# "upgrade-weight" sagt, was neuer ist -- verlaesslicher als ein
# Zahlenvergleich, der bei dieser Zaehlweise nur schiefgehen kann.
LEAP_AUSKUNFT = "https://get.opensuse.org/api/v0/distributions.json"


def _leap_ausgaben(adresse: str, zeitlimit: float) -> dict:
    """openSUSE nach seinen Ausgaben fragen -- es sagt auch, welche stabil ist."""
    netz = erreichbar(LEAP_AUSKUNFT)
    if not netz["ok"]:
        return {"ok": False, "gefunden": [], "neu": [], "geprueft": LEAP_AUSKUNFT,
                "kein_netz": True, "meldung": netz["meldung"]}

    anfrage = urllib.request.Request(LEAP_AUSKUNFT,
                                     headers={"User-Agent": "pxeweb/1.0"})
    try:
        with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:
            daten = json.loads(antwort.read(256 * 1024).decode("utf-8", "replace"))
    except Exception as fehler:
        return {"ok": False, "gefunden": [], "neu": [], "geprueft": LEAP_AUSKUNFT,
                "meldung": f"openSUSE antwortet nicht brauchbar — {_warum(fehler)}"}

    reihe = daten.get("Leap") if isinstance(daten, dict) else None
    if not isinstance(reihe, list):
        return {"ok": False, "gefunden": [], "neu": [], "geprueft": LEAP_AUSKUNFT,
                "meldung": "In der Auskunft steht keine Liste von Leap-Ausgaben."}

    # Nach "upgrade-weight" statt nach der Nummer: Leap hat zweimal
    # umnummeriert, ein Zahlenvergleich kann hier nur danebengehen.
    sauber = [e for e in reihe
              if isinstance(e, dict) and VERSION_RE.match(str(e.get("version", "")))]
    sauber.sort(key=lambda e: e.get("upgrade-weight") or 0, reverse=True)

    gefunden = [str(e["version"]) for e in sauber]
    stabil = [str(e["version"]) for e in sauber
              if str(e.get("state", "")).lower() == "stable"]
    aktuell = stabil[0] if stabil else ""

    schon = liste(VERSIONSLISTE.get(adresse, ""))
    neu = [v for v in gefunden if v not in schon]

    # Nur, was ueber der stabilen steht: Ein Beta darueber ist eine
    # Auskunft ("es kommt etwas"), ein EOL darunter nur Vergangenheit.
    gewicht_stabil = next((e.get("upgrade-weight") or 0 for e in sauber
                           if str(e["version"]) == aktuell), 0)
    unfertig = [f'{e["version"]} ist {e.get("state")}' for e in sauber
                if str(e.get("state", "")).lower() != "stable"
                and (e.get("upgrade-weight") or 0) > gewicht_stabil][:2]
    meldung = (f"aktuell ist Leap {aktuell}" if aktuell else "keine stabile Ausgabe genannt")
    if unfertig:
        meldung += " (" + ", ".join(unfertig) + ")"

    return {"ok": True, "gefunden": gefunden, "neu": neu,
            "geprueft": LEAP_AUSKUNFT, "aktuell": aktuell, "meldung": meldung}


# Anbieter, deren Ausgaben nicht in einem Verzeichnisindex stehen.
SONDERWEG = {"DEBIAN_URL": _debian_ausgaben,
             "LEAP_URL": _leap_ausgaben}


def _ausgaben_im_index(ordner: str, muster: str, form: re.Pattern,
                       zeitlimit: float) -> dict:
    """Ein Verzeichnis lesen und herausziehen, was darin nach Ausgabe aussieht.

    Herausgeloest, weil es zwei Aufrufer hat: neuere_ausgaben() fragt fuer
    eine eingetragene Quelle, probe_muster() fuer ein Muster, das gerade
    erst aus einer eingefuegten Adresse entstanden ist und noch nirgends
    steht. Zweimal derselbe Leser waere zweimal dieselbe Pflege -- und der
    Leser kennt die Eigenheiten mehrerer Anbieter.
    """
    anfrage = urllib.request.Request(ordner, headers={"User-Agent": "pxeweb/1.0"})
    try:
        with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:
            art = (antwort.headers.get("content-type") or "").lower()
            rohdaten = antwort.read(512 * 1024)
            wirklich = antwort.geturl()
    except urllib.error.HTTPError as fehler:
        return {"ok": False, "gefunden": [], "geprueft": ordner,
                "meldung": f"{fehler.code} {fehler.reason} — kein Verzeichnis zum Nachsehen."}
    except Exception as fehler:                      # Netz, DNS, TLS
        return {"ok": False, "gefunden": [], "geprueft": ordner,
                "meldung": f"nicht erreichbar: {fehler}"}

    if not any(w in art for w in ("html", "xml", "text")):
        return {"ok": False, "gefunden": [], "geprueft": wirklich,
                "meldung": "Dort steht nichts zum Nachlesen, sondern "
                           + (art or "etwas anderes")}

    text = rohdaten.decode("utf-8", "replace")
    gefunden = []
    # Nur Links auf Verzeichnisse: Eine Ausgabe ist ein Ordner, kein
    # "sha256sum.txt" und keine Zahl, die zufaellig irgendwo im Index
    # steht -- der Leap-Index etwa enthaelt Links, die sonst als "11780"
    # durchgingen.
    for ziel in re.findall(r'href="([^"?#]+/)"', text):
        name = ziel.rstrip("/").rsplit("/", 1)[-1]
        # Memtest legt seine Ausgaben unter "v8.10/" ab; eingetragen wird
        # die Nummer ohne das v, weil sie so auch im Dateinamen steht.
        if name[:1] == "v" and name[1:2].isdigit():
            name = name[1:]
        if form.match(name) and name not in gefunden:
            gefunden.append(name)

    # Und derselbe Blick auf die Dateinamen: Wo es keine Verzeichnisse
    # gibt, steht die Ausgabe im Namen der Datei.
    dateien = _dateimuster(muster)
    if dateien:
        for treffer in dateien.findall(text):
            nummer = treffer.strip(".-")
            if form.match(nummer) and nummer not in gefunden:
                gefunden.append(nummer)

    if not gefunden:
        return {"ok": False, "gefunden": [], "geprueft": wirklich,
                "meldung": "Nichts gefunden, was wie eine Ausgabe aussieht."}

    gefunden.sort(key=_sortierschluessel, reverse=True)
    return {"ok": True, "gefunden": gefunden, "geprueft": wirklich, "meldung": ""}


def probe_muster(muster: str, zeitlimit: float = 20.0) -> dict:
    """Die Gegenprobe zu einem frisch erkannten Muster.

    Ein Muster, das aus einer eingefuegten Adresse entstanden ist, ist
    zunaechst eine Vermutung: Vielleicht war die Zahl darin die Ausgabe,
    vielleicht die Nummer einer Variante. Beweisen laesst sich das nur
    beim Anbieter -- findet sich dort, wo die Ausgabe steht, auch ihre
    Nachbarn, dann stimmt die Vermutung.

    Das ist der Unterschied zwischen "der Server behauptet etwas" und
    "der Server zeigt, was er gefunden hat". Nur das Zweite kann jemand
    bestaetigen, ohne den Aufbau einer Adresse zu verstehen.
    """
    muster = (muster or "").strip()
    if "{version}" not in muster:
        return {"ok": False, "gefunden": [], "geprueft": "",
                "meldung": "In dieser Adresse steckt keine Ausgabe."}
    ordner = _verzeichnis_ueber(muster)
    if not ordner:
        return {"ok": False, "gefunden": [], "geprueft": "",
                "meldung": "Zu dieser Adresse gibt es kein Verzeichnis zum Nachsehen."}
    return _ausgaben_im_index(ordner, muster, _AUSGABE_RE, zeitlimit)


def neuere_ausgaben(adresse: str, zeitlimit: float = 20.0) -> dict:
    """Nachsehen, welche Ausgaben es beim Anbieter gibt.

    Gelesen wird der Verzeichnisindex ueber den Ausgaben -- mehr nicht:
    kein Herunterladen, kein Raten. Was dabei herauskommt, ist ein
    Vorschlag; eingetragen wird von Hand, denn ob eine Ausgabe taugt,
    entscheidet nicht ihre Nummer.

    Nicht jeder Anbieter liefert einen Index. SourceForge etwa (GParted,
    Clonezilla) antwortet mit einer Weiterleitung auf eine Downloadseite.
    Dann sagt das hier genau das -- statt eine leere Liste zu zeigen, die
    wie "nichts Neues" aussaehe.
    """
    sonderweg = SONDERWEG.get(adresse)
    if sonderweg is not None:
        return sonderweg(adresse, zeitlimit)

    muster = ausgabenmuster(adresse)
    ordner = SUCHORT.get(adresse) or _verzeichnis_ueber(muster)
    if not ordner:
        return {"ok": False, "meldung": "Für diese Quelle gibt es keine Ausgaben.",
                "gefunden": [], "neu": [], "geprueft": ""}

    netz = erreichbar(ordner)
    if not netz["ok"]:
        return {"ok": False, "gefunden": [], "neu": [], "geprueft": ordner,
                "kein_netz": True, "meldung": netz["meldung"]}

    befund = _ausgaben_im_index(
        ordner, muster, AUSGABENFORM.get(adresse, _AUSGABE_RE), zeitlimit)
    if not befund["ok"]:
        return {**befund, "neu": []}
    gefunden, wirklich = befund["gefunden"], befund["geprueft"]

    schon = liste(VERSIONSLISTE.get(adresse, ""))
    neu = hoehere_als(gefunden, schon)

    # Bewusst "hoehere Nummern" und nicht "neuere": Verglichen werden
    # Zahlen, und die sind nicht immer die Zeit. openSUSE zaehlte einmal
    # 42.x, dann 15.x, jetzt 16.x -- da steht die 42.3 von 2017 hoeher als
    # die aktuelle 16.1. Und Rockys 10.2 ist keine neue Ausgabe, sondern
    # eine Punktversion der 10. Was davon taugt, entscheidet der Mensch.
    if neu:
        meldung = ("höhere Nummern: " + ", ".join(neu[:5])
                   + (" …" if len(neu) > 5 else ""))
    elif schon:
        meldung = f"nichts Höheres — {schon[0]} ist dort die größte"
    else:
        meldung = f"{len(gefunden)} Ausgaben gefunden"
    return {"ok": True, "gefunden": gefunden[:20], "neu": neu[:20],
            "geprueft": wirklich, "meldung": meldung}


def _nur_das_neueste(name: str, befund: dict) -> None:
    """Den Befund auf das eindampfen, was wirklich anzubieten ist.

    "gefunden" bleibt unangetastet -- das ist die rohe Auskunft des
    Anbieters. Geaendert wird, was die Karte daraus macht: "neu" ist
    danach hoechstens eine Ausgabe, und die Meldung nennt auch nur sie.
    Vorher stand dort "hoehere Nummern: 10, 9, 8" und darunter drei
    Knoepfe -- bei Rocky also die Aufforderung, sich zwischen drei
    Ausgaben zu entscheiden, ohne dass jemand danach gefragt haette.
    """
    if not befund.get("ok"):
        return
    dazu = wirklich_neuer(name, befund)
    befund["neu"] = [dazu] if dazu else []
    schon = [a["version"] for a in ausgaben(name) if a.get("version")]
    if dazu:
        befund["meldung"] = "neuere Ausgabe: " + dazu
    elif schon:
        befund["meldung"] = "nichts Neueres — " + schon[0] + " ist die aktuelle"
    else:
        befund["meldung"] = str(len(befund.get("gefunden") or [])) + " Ausgaben gefunden"


def _sortierschluessel(version: str) -> list:
    """Damit 10 hinter 9 kommt und nicht davor."""
    return [int(teil) if teil.isdigit() else teil
            for teil in re.split(r"[.\-]", version)]


def neuer_als(version: str, andere: list[str]) -> bool:
    """Steht diese Ausgabe ueber allen anderen?

    Gebraucht vom Waechter: Was der Anbieter hergibt und hier noch nicht
    eingetragen ist, muss deshalb nicht neuer sein. Debians oldstable ist
    aelter als das, was dasteht, und im Leap-Verzeichnis liegt heute noch
    42.3 von 2017. "Es gibt etwas Neueres" darf nur heissen: hoeher als
    alles, was schon eingetragen ist.
    """
    marke = _sortierschluessel(version)
    return all(marke > _sortierschluessel(a) for a in andere)


def karten() -> list[dict]:
    """Alle Quellen als Karten -- mehrversionige mit einer Zeile je Ausgabe.

    Bis hierher war das eine Tabelle mit einer Adresse je System. Bei den
    mehrversionigen stand darin aber nur das Muster; was tatsaechlich
    geholt wird, sah man nirgends. Jetzt steht jede Ausgabe fuer sich.
    """
    vorgabe, eigen = vorgaben(), eigene()
    liste_ = []
    for name in sorted(vorgabe):
        mehrfach = name in VERSIONSLISTE
        liste_.append({
            "name": name,
            "mehrfach": mehrfach,
            "url": eigen.get(name, vorgabe[name]),
            # Woraus die naechste Ausgabe vorgeschlagen wird. Meist
            # dasselbe wie die Adresse -- bei Rocky nicht.
            "muster": ausgabenmuster(name) if mehrfach else "",
            "vorgabe": vorgabe[name],
            "geaendert": name in eigen and eigen[name] != vorgabe[name],
            "basis": name in PRUEFPFAD,
            "pruefdatei": PRUEFPFAD.get(name, ""),
            "ausgaben": ausgaben(name),
            "liste": VERSIONSLISTE.get(name, ""),
        })
    return liste_


def _pruefe_url(url: str) -> str:
    """Eine Adresse auf Unfug pruefen. Gibt die saubere Adresse zurueck."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Nur http:// und https:// sind erlaubt.")
    # Die Adressen landen in einer Datei, die die Shell einliest. Zeichen,
    # mit denen sich dort Befehle unterschieben liessen, kommen in einer
    # Download-Adresse nicht vor -- also lieber ablehnen als maskieren.
    if any(z in url for z in VERBOTEN) or any(ord(z) < 32 for z in url):
        raise ValueError("Die Adresse enthaelt unerlaubte Zeichen.")
    if len(url) > 1000:
        raise ValueError("Die Adresse ist unglaubwuerdig lang.")
    return url


def setze(name: str, wert: str) -> None:
    """Eine Adresse oder Versionsliste ersetzen. Unbekannte Namen fliegen raus."""
    if name in _versionsvorgaben():
        eigen = eigene()
        sauber = _pruefe_versionen(wert)
        geaendert = eigen.get(name, _versionsvorgaben()[name]) != sauber
        eigen[name] = sauber
        _schreibe(eigen)
        if geaendert:
            vergiss_stand(name)
        return
    if name not in vorgaben():
        raise ValueError("Unbekannte Quelle: " + name)
    eigen = eigene()
    neu_ = _pruefe_url(wert)
    vorher = alle_werte().get(name, "")
    if vorher and vorher != neu_:
        merke_verlauf(name, vorher)
    eigen[name] = neu_
    _schreibe(eigen)
    if vorher != neu_:
        vergiss_stand(name)


def _pruefe_versionen(wert: str) -> str:
    """Aus einer Eingabe eine saubere Versionsliste machen.

    Eine leere Liste ist erlaubt und bedeutet "dieses System ist nicht in
    Betrieb": Der Katalog macht daraus keinen Menuepunkt (siehe _entfalte
    in app.py), und geholt wird nichts. Genau so wird ein frisch
    aufgesetzter Server ausgeliefert -- ohne diesen Weg liesse sich ein
    System auch nicht wieder abschalten, ohne den Katalog anzufassen.
    """
    teile = wert.replace(",", " ").split()
    for t in teile:
        if not VERSION_RE.match(t):
            raise ValueError("Ungueltige Version: " + t)
    if len(teile) > 10:
        raise ValueError("Hoechstens zehn Versionen gleichzeitig.")
    # Doppelte entfernen, Reihenfolge behalten.
    gesehen, sauber = set(), []
    for t in teile:
        if t not in gesehen:
            gesehen.add(t)
            sauber.append(t)
    return " ".join(sauber)


# --------------------------------------------------------------------------
# Uebernahme: was vor den leeren Listen schon in Betrieb war
# --------------------------------------------------------------------------
# Bis August 2026 lieferte sync-images.sh diese Ausgaben als Vorgabe mit.
# Seitdem sind die Listen leer -- mitgeliefert wird die Auswahl der
# Distributionen, nicht die Nummer ihrer Ausgabe.
#
# Auf einem laufenden Server waere das ein Verlust: Wer nie eine Ausgabe
# von Hand eingetragen hat, hatte seine elf Systeme allein aus dieser
# Vorgabe. Mit der leeren Liste faellt jeder davon aus dem Bootmenue, und
# sein Verzeichnis stuende als verwaist da, mit Loeschknopf daneben.
#
# Deshalb einmalig festhalten, was wirklich schon geholt ist. Geprueft
# wird die Platte und nicht die Vorgabe: Was nie geholt wurde, soll auch
# nicht nachtraeglich in Betrieb gehen.
FRUEHERE_VORGABEN = {
    "DEBIAN_VERSIONS": "trixie",
    "DEBIAN_LIVE_VERSIONS": "13.6.0",
    "SYSRESC_VERSIONS": "13.02",
    "GPARTED_VERSIONS": "1.8.1-3",
    "CLONEZILLA_VERSIONS": "3.3.3-15",
    "MEMTEST_VERSIONS": "8.10",
    "FEDORA_VERSIONS": "44",
    "LEAP_VERSIONS": "16.1",
    "UBUNTU_VERSIONS": "26.04",
    "ROCKY_VERSIONS": "10 9",
}

# Dass die Uebernahme gelaufen ist, muss festgehalten werden -- und zwar
# getrennt davon, was sie eingetragen hat. Sonst kaeme sie beim naechsten
# Start wieder: Wer eine Liste absichtlich leert, steht danach wieder da,
# wo _schreibe() nichts festhaelt (leer ist ja die Vorgabe), und bekaeme
# seine Ausgaben zurueck. Die Marke steht in derselben Datei; sie ist
# keine Adresse und keine Ausgabenliste und taucht deshalb in keiner Karte
# auf.
UEBERNAHME_MARKE = "AUSGABEN_UEBERNOMMEN"


def uebernommen() -> bool:
    """Ist die einmalige Uebernahme schon gelaufen?"""
    return UEBERNAHME_MARKE in eigene()


def uebernimm_ausgaben(vorhanden: dict[str, list[str]], wann: str = "") -> list[str]:
    """Einmalig eintragen, welche frueheren Vorgaben wirklich dastehen.

    "vorhanden" sagt je Liste, welche Ausgaben ihre Dateien auf der Platte
    haben -- das weiss der Katalog und nicht diese Datei. Zurueck kommen
    die Listen, die geschrieben wurden.

    Eine Liste, in der schon etwas Eigenes steht, bleibt unangetastet: Wer
    selbst eingetragen hat, hat die Frage bereits beantwortet.
    """
    eigen = eigene()
    if UEBERNAHME_MARKE in eigen:
        return []

    geschrieben = []
    for name, ausgaben_ in vorhanden.items():
        if name in eigen or not ausgaben_:
            continue
        eigen[name] = " ".join(dict.fromkeys(ausgaben_))
        geschrieben.append(name)

    eigen[UEBERNAHME_MARKE] = wann or datetime.now(timezone.utc).date().isoformat()
    _schreibe(eigen)
    return geschrieben


def zuruecksetzen(name: str) -> None:
    eigen = eigene()
    if eigen.pop(name, None) is not None:
        _schreibe(eigen)


def _schreibe(eigen: dict[str, str]) -> None:
    vorgabe = {**vorgaben(), **_versionsvorgaben()}
    # Nur festhalten, was wirklich abweicht -- sonst frieren wir Vorgaben
    # ein, die spaeter im Projekt korrigiert werden.
    zeilen = [
        "# Von der Weboberflaeche gepflegt -- siehe Hilfe, Quellen.",
        "# sync-images.sh liest diese Datei nach seinen eigenen Vorgaben ein,",
        "# was hier steht gewinnt also. Von Hand aendern geht auch.",
        "",
    ]
    for name in sorted(eigen):
        # Was die Shell nicht als Variablennamen lesen kann, darf hier
        # nicht hinein: sync-images.sh macht "source" auf diese Datei, und
        # eine krumme Zeile darin ist fuer sie kein Eintrag, sondern ein
        # Befehl, den es nicht gibt. Der Wert waere lautlos weg. Seit
        # schluessel() alles Unerlaubte ersetzt, kann das eigentlich nicht
        # mehr vorkommen -- der Wachposten steht hier fuer den Fall, dass
        # jemand von Hand etwas eintraegt, und fuer den naechsten Namen,
        # den wir uns ausdenken.
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        if eigen[name] != vorgabe.get(name):
            zeilen.append(f'{name}="{eigen[name]}"')
    EIGEN.parent.mkdir(parents=True, exist_ok=True)
    vorlaeufig = EIGEN.with_suffix(".env.neu")
    vorlaeufig.write_text("\n".join(zeilen) + "\n", encoding="utf-8", newline="\n")
    vorlaeufig.replace(EIGEN)


# Erreichbarkeit je Rechner, kurz gemerkt. "Alle pruefen" geht sonst
# zwoelf Quellen durch und fragt dabei mehrmals denselben Rechner, ob es
# ihn gibt. Dreissig Sekunden reichen: Laenger dauert kein Durchlauf, und
# wer nach einem Netzausfall gleich noch einmal drueckt, soll die frische
# Antwort bekommen.
_ERREICHBAR: dict = {}
_ERREICHBAR_SEKUNDEN = 30


def vergiss_erreichbarkeit() -> None:
    """Das Gemerkte wegwerfen -- fuer Tests und nach einem Netzwechsel."""
    _ERREICHBAR.clear()


def _warum(fehler: Exception) -> str:
    """Aus dem Fehler einen Satz machen, den man lesen kann.

    Was Python hier liefert, ist fuer Menschen unbrauchbar --
    "<urlopen error [Errno 11001] getaddrinfo failed>" sagt niemandem,
    dass der Name nicht aufloesbar war. Und gerade diese Meldung ist die,
    die jemand liest, wenn etwas nicht geht.
    """
    text = str(getattr(fehler, "reason", fehler)) or fehler.__class__.__name__
    klein = text.lower()
    if "getaddrinfo" in klein or "name or service" in klein or "nodename" in klein:
        return ("der Name ist nicht aufloesbar. Kein DNS, kein Internet, "
                "oder der Anbieter gibt es nicht mehr.")
    if "refused" in klein or "verweigert" in klein:
        return "die Verbindung wurde abgelehnt."
    if "timed out" in klein or "timeout" in klein or "zeit" in klein:
        return "keine Antwort innerhalb der Wartezeit."
    if "certificate" in klein or "ssl" in klein or "zertifikat" in klein:
        return f"die verschluesselte Verbindung kam nicht zustande ({text})."
    if "unreachable" in klein or "erreichbar" in klein:
        return "das Netz ist von hier aus nicht erreichbar."
    return text


def erreichbar(url: str, zeitlimit: float = 6.0) -> dict:
    """Antwortet der Rechner hinter dieser Adresse ueberhaupt?

    Gefragt wird die Wurzel des Anbieters, nicht der Pfad -- also
    "https://deb.debian.org/" und nicht die Datei darunter. Damit ist
    unterscheidbar, was bisher gleich aussah:

        keine Verbindung   DNS scheitert, Verbindung abgelehnt, TLS kaputt,
                           Zeitlimit -- dieser Server kommt nicht hin
        Adresse veraltet   der Rechner antwortet, die Datei gibt es nicht

    **Jede** HTTP-Antwort zaehlt als erreichbar, auch 403 und 404: Sie
    beweist, dass eine Verbindung zustande kam. Manche Anbieter sperren
    ihre Wurzelseite, und die deshalb fuer offline zu halten waere falsch.

    Das Zeitlimit ist kurz. Diese Frage steht vor allen anderen, und wenn
    sie nicht binnen weniger Sekunden zu beantworten ist, lautet die
    Antwort ohnehin "nein".
    """
    try:
        teile = urlparse(url.strip())
    except ValueError:
        return {"ok": False, "wurzel": "", "meldung": "Keine gueltige Adresse."}
    if teile.scheme not in ("http", "https") or not teile.netloc:
        return {"ok": False, "wurzel": "",
                "meldung": "Nur http:// und https:// sind erlaubt."}

    wurzel = f"{teile.scheme}://{teile.netloc}/"
    gemerkt = _ERREICHBAR.get(wurzel)
    if gemerkt and time.monotonic() - gemerkt[0] < _ERREICHBAR_SEKUNDEN:
        return {**gemerkt[1], "gemerkt": True}

    anfrage = urllib.request.Request(
        wurzel, headers={"Range": "bytes=0-0", "User-Agent": "pxeweb/1.0"},
        method="GET")
    try:
        with urllib.request.urlopen(anfrage, timeout=zeitlimit):
            pass
        ergebnis = {"ok": True, "wurzel": wurzel, "meldung": "erreichbar"}
    except urllib.error.HTTPError:
        # Der Rechner hat geantwortet -- mehr wollten wir nicht wissen.
        ergebnis = {"ok": True, "wurzel": wurzel, "meldung": "erreichbar"}
    except Exception as fehler:                     # DNS, TCP, TLS, Zeitlimit
        ergebnis = {"ok": False, "wurzel": wurzel,
                    "meldung": f"Keine Verbindung zu {teile.netloc} — "
                               + _warum(fehler)}
    _ERREICHBAR[wurzel] = (time.monotonic(), ergebnis)
    return ergebnis


def pruefe(url: str, name: str = "", zeitlimit: float = 20.0) -> dict:
    """Nachsehen, ob es die Datei gibt -- ohne sie zu laden.

    Gefragt wird nach einem einzigen Byte ("Range"). Ein blosses HEAD waere
    naheliegender, aber SourceForge und der Fedora-Spiegelverteiler
    antworten darauf unzuverlaessig, obwohl der Download funktioniert.

    Ist die Quelle eine Basisadresse (siehe PRUEFPFAD), wird eine Datei
    darunter geprueft statt der Adresse selbst -- ein Verzeichnisindex
    waere sonst immer "zu klein".
    """
    try:
        sauber = _pruefe_url(url)
    except ValueError as fehler:
        return {"ok": False, "meldung": str(fehler)}

    if "{version}" in sauber:
        versionen_ = liste(VERSIONSLISTE.get(name, ""))
        if not versionen_:
            # Weder gut noch kaputt, sondern gar nicht in Betrieb -- der
            # Normalfall auf einem frisch aufgesetzten Server. "leer"
            # unterscheidet das von einer toten Adresse: Eine rote Ampel
            # waere hier eine Falschmeldung, und zehn davon liessen einen
            # neuen Server aussehen wie einen kaputten.
            return {"ok": False, "leer": True, "geprueft": sauber,
                    "meldung": LEER_MELDUNG}
        sauber = sauber.replace("{version}", versionen_[0])

    # Erst die Frage, die allen anderen vorausgeht: Kommt dieser Server
    # ueberhaupt zu dem Anbieter? Ohne sie sehen "Debian hat die Datei
    # verschoben" und "hier ist kein Internet" fast gleich aus -- beides
    # endete in "Nicht erreichbar: <irgendein Python-Fehler>". Und es
    # erspart die weitere Frage: Wo keine Verbindung besteht, ist der Pfad
    # nicht das Problem.
    netz = erreichbar(sauber)
    if not netz["ok"]:
        return {"ok": False, "geprueft": sauber, "kein_netz": True,
                "meldung": netz["meldung"]}

    groessenpruefung = True
    if name in PRUEFPFAD:
        anhang = PRUEFPFAD[name]
        if anhang:
            sauber = sauber.rstrip("/") + "/" + anhang
        else:
            # Der Verzeichnisindex ist hier das Gesuchte, nicht eine Datei.
            groessenpruefung = False

    anfrage = urllib.request.Request(
        sauber,
        headers={"Range": "bytes=0-0", "User-Agent": "pxeweb/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:
            kopf = antwort.headers
            ziel = antwort.geturl()
            bereich = kopf.get("content-range", "")
            if "/" in bereich:
                groesse = int(bereich.rsplit("/", 1)[1] or 0)
            else:
                # Der Server hat "Range" ignoriert und wuerde alles schicken.
                groesse = int(kopf.get("content-length") or 0)
            # Nichts weiterlesen -- die Verbindung wird gleich geschlossen.
    except urllib.error.HTTPError as fehler:
        return {"ok": False, "geprueft": sauber,
                "meldung": f"Server antwortet mit {fehler.code} {fehler.reason}"}
    except Exception as fehler:                        # Netz, DNS, TLS, Zeitlimit
        return {"ok": False, "geprueft": sauber, "meldung": f"Nicht erreichbar: {fehler}"}

    grenze = MIN_EIGEN.get(name, MIN_GROESSE)
    if groessenpruefung and groesse and groesse < grenze:
        return {
            "ok": False,
            "groesse": groesse,
            "ziel": ziel,
            "geprueft": sauber,
            "meldung": f"Nur {groesse} Byte gross -- das ist keine Abbilddatei, "
                       "sondern vermutlich eine Downloadseite.",
        }

    if groesse >= 1073741824:
        umfang = f", {groesse / 1073741824:.2f} GB"
    elif groesse:
        umfang = f", {groesse / 1048576:.1f} MB"
    else:
        umfang = ""
    return {
        "ok": True,
        "groesse": groesse,
        "ziel": ziel,
        "geprueft": sauber,
        "meldung": "erreichbar" + umfang,
    }

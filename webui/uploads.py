"""
Eigene ISO-Abbilder: entgegennehmen, einordnen, ins Bootmenue haengen.

Ablage -- alles unterhalb von /srv/pxe/assets/<slug>/:

    abbild.iso        das hochgeladene Abbild (nur, wenn es zum Start
                      gebraucht wird -- casper laedt es komplett nach)
    casper/vmlinuz    die zum Starten noetigen Dateien, aus dem Abbild geholt
    eintrag.yaml      Zustand und fertiger Katalogeintrag

Warum neben den Dateien und nicht in der Datenbank? Weil man so mit "ls"
sieht, was da ist, und ein "rm -r" den Eintrag wirklich loswird. Und weil
install.sh mit "rsync --delete" arbeitet: alles, was im Projektordner
liegt, waere beim naechsten Update weg. /srv/pxe fasst install.sh nicht an.

Der Upload selbst laeuft in app.py -- der Datenstrom wird direkt auf die
Platte geschrieben, ohne Umweg ueber den Arbeitsspeicher.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

from isoscan import (Befund, Iso, IsoFehler, platz_reicht, untersuche,
                     wim_konsole, windows_angaben)

ASSETS_DIR = Path(os.environ.get("PXE_ASSETS", "/srv/pxe/assets"))
# Ein Eintrag, ein Verzeichnis, und es heisst wie er. Der Behaelter
# "upload/" ist im August 2026 weggefallen: Die Kennung eines Uploads faengt
# ohnehin mit "iso-" an, ein selbst angelegter Eintrag mit "netz-", und ein
# Katalogeintrag mit keinem von beiden. Man sieht der Ablage also weiter an,
# was woher kam -- ohne dass der Ordner eines Eintrags erst gesucht werden
# muesste.
UPLOAD_PRAEFIX = "iso-"
# Gruppen im Bootmenue und in der Uebersicht. Entscheidend ist, ob der
# Installer seine Pakete vom Bootserver bekommt oder sie sich waehrend der
# Installation aus dem Internet holt -- das ist die Frage, die vor der
# Maschine zaehlt. Ein hochgeladenes Abbild liegt vollstaendig hier, ist
# also der Regelfall fuer "ohne Internet"; ausschlaggebend ist trotzdem die
# gebaute Kommandozeile und nicht die Herkunft.
OHNE_NETZ = "Offline-Installationen"
MIT_NETZ = "Online-Installationen"
# Was nichts installiert, sondern ein Werkzeug ist. Dazu gehoert die
# Windows-Konsole aus einem hochgeladenen Abbild, solange sie nur eine
# Konsole ist: an einem Rechner arbeiten, ohne von seiner Platte zu starten.
#
# Sind die Installationsquellen ausgepackt und per SMB freigegeben, ist sie
# das nicht mehr -- dann installiert sie, und der Eintrag gehoert zu den
# Offline-Installationen. Entschieden wird das in _wimboot_eintrag().
WERKZEUG = "Rettung und Wartung"

# Frueher hiessen die beiden Installationsgruppen ausfuehrlicher. Der Name
# steht aber nicht nur hier, sondern auch in jeder eintrag.yaml neben den
# Abbildern auf der Platte -- und die ueberleben ein Update. Ohne diese
# Tabelle landete ein vor der Umbenennung angelegter Eintrag unter
# "Sonstiges", also ganz unten und ohne erkennbaren Grund.
FRUEHER = {
    "Ohne Internet installieren": OHNE_NETZ,
    "Über das Internet installieren": MIT_NETZ,
}


def gruppe_heute(name: str) -> str:
    """Den heute gueltigen Gruppennamen liefern, auch fuer alte Eintraege."""
    return FRUEHER.get(name, name)

# Ist ein NFS-Export eingerichtet, steht hier sein Pfad auf dem Server
# (PXE_NFS_ROOT in /etc/pxeweb.env, gesetzt von install.sh). Dann werden
# grosse Live-Systeme gestreamt statt in den Arbeitsspeicher geladen --
# nur so startet ein 6 GB grosses Ubuntu-Desktop auf einem 8-GB-Rechner.
NFS_ROOT = os.environ.get("PXE_NFS_ROOT", "").rstrip("/")

# Dasselbe fuer Windows: Steht hier ein Pfad, gibt es eine SMB-Freigabe
# (PXE_SMB_ROOT, ebenfalls von install.sh gesetzt). Nur dann lohnt es
# sich, ein Windows-Medium vollstaendig auszupacken -- das Setup laedt
# seine mehrere Gigabyte grosse install.wim ueber SMB und ueber nichts
# sonst. Ohne Freigabe bleibt es bei der Konsole und ein paar hundert MB.
SMB_ROOT = os.environ.get("PXE_SMB_ROOT", "").rstrip("/")

# Entpacken laeuft im Hintergrund. Der Riegel sorgt dafuer, dass nicht zwei
# Abbilder gleichzeitig die Platte belegen und sich gegenseitig ausbremsen.
_riegel = threading.Lock()

# Wessen Download abgebrochen werden soll.
#
# **Abgebrochen wird nur, solange uebertragen wird -- nie beim Entpacken.**
# Markus am 05.09.2026: *"Die Entscheidung, dass es hochgeladen werden
# soll, hat der User schon getroffen."* Dahinter steht mehr als eine
# Vorliebe: Die Grenze liegt bei uebernehmen(), und sie ist scharf. Davor
# liegt die vorherige Fassung unberuehrt daneben, ein Abbruch kostet nur
# die Uebertragung. Danach ist sie ueberschrieben -- ausgepackt wird in
# dasselbe Verzeichnis --, und ein Abbruch koennte nur noch waehlen,
# welchen Scherbenhaufen er hinterlaesst. Ein Knopf, der etwas anbietet,
# was es nicht mehr gibt, ist schlimmer als keiner.
#
# **Ein Zeichen, kein Abschuss.** Einen Thread von aussen zu beenden gibt
# es in Python nicht, und es waere auch das Falsche: mitten im Schreiben
# abgeschnitten, bliebe genau der halbe Zustand liegen. Stattdessen liegt
# hier ein Zettel, und die Ladeschleife sieht bei jedem Brocken nach.
#
# **Nur fuer den Download.** Beim Upload traegt der Browser, und der
# bricht selbst ab (xhr.abort); der Server merkt es als ClientDisconnect
# und raeumt dort auf. Zwei Wege, weil es zwei Sender sind -- aber
# dieselbe Aufraeumung dahinter.
#
# **Im Speicher und nicht in der Zustandsdatei.** Ein Abbruch gilt fuer
# einen laufenden Vorgang; startet der Dienst neu, ist der Vorgang ohnehin
# tot, und ein Zettel, der das ueberlebt, braeche den naechsten Anlauf ab.
_abbrueche: set = set()
_abbruch_riegel = threading.Lock()


class Abgebrochen(Exception):
    """Jemand hat den Vorgang abgebrochen. Kein Fehler -- eine Bedienung."""


def brich_ab(slug: str) -> None:
    """Den Zettel hinlegen. Wirkt erst, wenn die Schleife nachsieht."""
    with _abbruch_riegel:
        _abbrueche.add(slug)


def abgebrochen(slug: str) -> bool:
    with _abbruch_riegel:
        return slug in _abbrueche


def vergiss_abbruch(slug: str) -> None:
    """Vor jedem neuen Anlauf: Ein alter Zettel gilt nicht fuer den naechsten."""
    with _abbruch_riegel:
        _abbrueche.discard(slug)


def _pruefe_abbruch(slug: str) -> None:
    if abgebrochen(slug):
        raise Abgebrochen()


ABBRUCH_MELDUNG = "Abgebrochen."

ZUSTAENDE = {
    "laedt": "wird geladen",
    "empfangen": "wird geprüft",
    "entpacken": "wird entpackt",
    "bereit": "bereit",
    "nicht-startbar": "kein Netzwerkstart möglich",
    "fehler": "Fehler",
}

WEGE = {
    "nfs": "wird über NFS gestreamt",
    "ram": "wird in den Arbeitsspeicher geladen",
    "smb": "Konsole im Arbeitsspeicher, Installationsquellen über SMB",
}


# --------------------------------------------------------------------------
# Ablage
# --------------------------------------------------------------------------


def sauberer_name(dateiname: str) -> str:
    """Aus einem beliebigen Dateinamen einen ungefaehrlichen machen.

    Der Name kommt vom Browser und darf nicht als Pfad missbraucht werden --
    deshalb bleibt nur der letzte Teil und davon nur harmlose Zeichen.
    """
    name = Path(dateiname.replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    return name[:100] or "abbild.iso"


def slug_fuer(dateiname: str) -> str:
    """Eindeutige Kennung fuer das Bootmenue, abgeleitet vom Dateinamen.

    Das Praefix "iso-" haelt die selbst hochgeladenen Eintraege von den
    fest eingebauten aus catalog.yaml getrennt -- so kann es keine
    Namenskollision geben.

    Abgeleitet wird nur -- ob unter dieser Kennung schon etwas liegt,
    entscheidet freier_slug(). Frueher wich diese Funktion selbst auf
    "-2" aus, sobald das Verzeichnis existierte. Damit war ein zweiter
    Upload derselben Datei stillschweigend ein zweiter Eintrag, und ein
    vorhandenes Abbild liess sich ueberhaupt nicht ersetzen: Es gab keinen
    Weg, dieselbe Kennung noch einmal zu treffen.
    """
    stamm = re.sub(r"\.iso$", "", sauberer_name(dateiname), flags=re.I)
    stamm = re.sub(r"[^a-z0-9]+", "-", stamm.lower()).strip("-")[:40].strip("-")
    return "iso-" + (stamm or "abbild")


def verzeichnis(slug: str) -> Path:
    """Ablageort eines Uploads -- mit Pruefung gegen Pfad-Tricks."""
    if not re.fullmatch(r"iso-[a-z0-9-]{1,60}", slug):
        raise ValueError("Ungueltige Kennung: " + slug)
    return ASSETS_DIR / slug


def _zustand_datei(slug: str) -> Path:
    return verzeichnis(slug) / "eintrag.yaml"


def _ohne_behaelter(daten: dict | None, slug: str) -> dict | None:
    """Alte Pfade aus der Zeit von "upload/" geradeziehen.

    In der eintrag.yaml steht ein fertiger Katalogeintrag, und der wurde
    bis August 2026 mit "upload/<slug>/..." gebaut. Die Datei liegt bei den
    Abbildern und uebersteht jedes Update -- nach dem Umzug der Ablage
    zeigte sie also weiter ins Leere, und der Eintrag waere aus dem Menue
    verschwunden, ohne dass man saehe warum.

    Repariert wird beim Lesen und nicht mit einem Skript: So ist es gleich,
    auf welchem Weg die Ordner umgezogen sind, und ein Abbild, das erst in
    einem Jahr von einer alten Sicherung zurueckkommt, findet sich auch
    dann noch zurecht. Geschrieben wird dabei nichts -- die naechste
    Aenderung am Eintrag schreibt die neue Fassung ohnehin.
    """
    # Auch der Wachposten fuer alles, was aus dieser Datei kommt: Sie liegt
    # bei den Abbildern, laesst sich von Hand aendern und kann abgeschnitten
    # sein. Steht dort etwas anderes als ein Zustand, hat die Liste der
    # Uploads dazu nichts zu sagen -- vorher legte so eine Datei jede Seite
    # lahm, die die Uploads durchgeht.
    if not isinstance(daten, dict):
        return None
    alt, neu = f"upload/{slug}", slug

    def geradeziehen(wert):
        if isinstance(wert, str):
            return wert.replace(alt, neu)
        if isinstance(wert, list):
            return [geradeziehen(w) for w in wert]
        if isinstance(wert, dict):
            return {k: geradeziehen(w) for k, w in wert.items()}
        return wert

    if isinstance(daten.get("eintrag"), dict):
        daten["eintrag"] = geradeziehen(daten["eintrag"])
    return daten


def lies_zustand(slug: str) -> dict | None:
    """Zustand einlesen -- mit ein paar Anlaeufen, siehe schreib_zustand.

    Waehrend die neue Fassung an ihre Stelle geschoben wird, laesst sich die
    Datei auf manchen Systemen kurz nicht oeffnen. Gleich aufzugeben hiesse,
    dass ein Upload fuer einen Seitenaufruf aus der Liste verschwindet.
    """
    for versuch in range(5):
        try:
            with _zustand_datei(slug).open(encoding="utf-8") as fh:
                return _ohne_behaelter(yaml.safe_load(fh) or None, slug)
        except FileNotFoundError:
            return None
        except (ValueError, yaml.YAMLError):
            return None
        except OSError:
            time.sleep(0.05)
    return None


def schreib_zustand(slug: str, daten: dict) -> None:
    ziel = _zustand_datei(slug)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    # Erst daneben schreiben, dann umbenennen: so liest niemand eine halbe
    # Datei, waehrend im Hintergrund entpackt wird.
    vorlaeufig = ziel.with_suffix(".yaml.neu")
    with vorlaeufig.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(daten, fh, allow_unicode=True, sort_keys=False)
    # Waehrend im Hintergrund entpackt wird, liest die Weboberflaeche
    # dieselbe Datei. Auf manchen Systemen scheitert das Umbenennen, solange
    # noch jemand hineinschaut -- ein paar Millisekunden spaeter geht es.
    for versuch in range(10):
        try:
            vorlaeufig.replace(ziel)
            return
        except OSError:
            if versuch == 9:
                raise
            time.sleep(0.05)


def verzeichnisse() -> list[Path]:
    """Die Verzeichnisse der Uploads -- kenntlich an ihrer Kennung."""
    try:
        return sorted((p for p in ASSETS_DIR.iterdir()
                       if p.is_dir() and p.name.startswith(UPLOAD_PRAEFIX)),
                      key=lambda p: p.name)
    except OSError:
        return []


def alle() -> list[dict]:
    """Alle Uploads, neueste zuerst."""
    liste = []
    for ordner in verzeichnisse():
        daten = lies_zustand(ordner.name)
        if daten:
            daten.setdefault("slug", ordner.name)
            daten["zustand_text"] = ZUSTAENDE.get(daten.get("status", ""), daten.get("status", ""))
            daten["weg_text"] = WEGE.get(daten.get("weg", ""), "")
            daten["iso_da"] = (ordner / daten.get("datei", "")).is_file()
            # Neu einlesen geht auf zwei Wegen: mit dem Abbild vollstaendig,
            # sonst aus dem gemerkten Befund -- damit laesst sich der
            # Menuepunkt auch dann auffrischen, wenn das Abbild nach dem
            # Entpacken geloescht wurde.
            daten["neu_lesbar"] = bool(
                daten["iso_da"] or daten.get("befund")
                or (daten.get("status") == "bereit"
                    and (ordner / "sources/boot.wim").is_file()))
            liste.append(daten)
    liste.sort(key=lambda d: d.get("hochgeladen", ""), reverse=True)
    return liste


def katalog_eintraege() -> list[dict]:
    """Die fertigen Menue-Eintraege der Uploads, fuer den Katalog."""
    return [d["eintrag"] for d in alle() if d.get("status") == "bereit" and d.get("eintrag")]


def loesche(slug: str) -> bool:
    ordner = verzeichnis(slug)
    if not ordner.is_dir():
        return False
    shutil.rmtree(ordner)
    return True


def belegung() -> int:
    """Wie viel Platz die Uploads zusammen belegen (Bytes)."""
    gesamt = 0
    for eigener in verzeichnisse():
        for pfad, _, dateien in os.walk(eigener):
            for name in dateien:
                try:
                    gesamt += (Path(pfad) / name).stat().st_size
                except OSError:
                    pass
    return gesamt


def vom_server(cmdline: str) -> bool:
    """Holt sich dieses System alles vom Bootserver?

    Zeigt die Kommandozeile auf ${assets} oder ${srvip}, kommt das
    Wurzeldateisystem beziehungsweise das Paketdepot von hier -- dann
    braucht der Client waehrend der Installation kein Internet. Steht dort
    eine Adresse nach draussen oder gar keine Quelle (dann sucht sich der
    Installer selbst einen Spiegel), ist es umgekehrt.
    """
    return "${assets}" in cmdline or "${srvip}" in cmdline


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Verarbeitung
# --------------------------------------------------------------------------


def dateiname_fuer(dateiname: str) -> str:
    """Der Name, unter dem das Abbild abgelegt wird."""
    datei = sauberer_name(dateiname)
    return datei if datei.lower().endswith(".iso") else datei + ".iso"


def freier_slug(basis: str) -> str:
    """Die naechste freie Kennung: basis, basis-2, basis-3 ...

    Angehaengt wird mit Bindestrich und nicht mit Unterstrich: Kennungen
    bestehen sonst nur aus a-z, 0-9 und "-", und sie sind ausser dem
    Verzeichnisnamen auch Sprungmarke im iPXE-Skript und Teil einer URL.
    Ein neues Zeichen dort einzufuehren hiesse, jede dieser Stellen noch
    einmal durchzusehen.
    """
    if not verzeichnis(basis).exists():
        return basis
    # Platz fuer das Anhaengsel schaffen: slug_fuer() kuerzt auf 40 Zeichen,
    # und darueber soll auch die zweite Ausgabe nicht hinausgehen.
    stamm = basis[:37].rstrip("-")
    for nummer in range(2, 100):
        kandidat = f"{stamm}-{nummer}"
        if not verzeichnis(kandidat).exists():
            return kandidat
    raise ValueError("Zu viele Ausgaben dieses Abbilds.")


def vorhanden(dateiname: str) -> dict | None:
    """Liegt unter dieser Kennung schon etwas? Dann sagen, was.

    Gefragt wird vor dem Uebertragen -- sechs Gigabyte umsonst zu schicken
    und erst danach zu fragen, waere die falsche Reihenfolge.
    """
    slug = slug_fuer(dateiname_fuer(dateiname))
    if not verzeichnis(slug).exists():
        return None
    daten = lies_zustand(slug) or {"slug": slug}
    return {
        "slug": slug,
        "datei": daten.get("datei", ""),
        "groesse": daten.get("groesse", 0),
        "hochgeladen": daten.get("hochgeladen", ""),
        "status": daten.get("status", ""),
        "erkannt": daten.get("erkannt", ""),
    }


def _sicherung_datei(slug: str) -> Path:
    """Die beiseitegelegte eintrag.yaml eines Eintrags, der ersetzt wird."""
    return _zustand_datei(slug).with_suffix(".yaml.vorher")


def _teil_datei(ordner: Path, datei: str) -> Path:
    """Wohin die ankommenden Daten geschrieben werden, bis alles da ist."""
    return ordner / (datei + ".teil")


def anlegen(dateiname: str, als_neue: bool = False) -> tuple[str, Path]:
    """Platz fuer einen neuen Upload schaffen und die Zieldatei nennen.

    "als_neue" legt daneben statt darueber: Dasselbe Abbild ein zweites Mal
    zu holen kann beides heissen -- die vorhandene Fassung ersetzen oder
    eine zweite Ausgabe daneben stellen, um sie zu erproben, bevor sie ins
    Menue kommt. Was gemeint ist, weiss nur der Mensch davor.

    **Ersetzen heisst nicht: erst wegraeumen, dann hoffen.** Bis August 2026
    trug dieser Aufruf sofort den neuen Zustand ein und schrieb die neuen
    Daten unter den endgueltigen Namen. Wer den Upload dann abbrach, verlor
    die vorher funktionierende Fassung -- der Aufraeumweg nimmt das ganze
    Verzeichnis mit, und das war zu diesem Zeitpunkt schon das des halb
    ueberschriebenen Eintrags.

    Jetzt wird die vorhandene eintrag.yaml beiseitegelegt und die Daten
    landen unter einem vorlaeufigen Namen. Bis "uebernehmen" gerufen wird,
    ist der alte Eintrag unberuehrt und startet weiter; "verwerfe" stellt
    ihn wieder her. Dasselbe Verfahren wie in schreib_zustand, nur eine
    Ebene hoeher.
    """
    datei = dateiname_fuer(dateiname)
    slug = slug_fuer(datei)
    if als_neue:
        slug = freier_slug(slug)
    ordner = verzeichnis(slug)
    ordner.mkdir(parents=True, exist_ok=True)

    # Ein Rest aus einem Lauf, der nicht mehr aufraeumen konnte -- etwa
    # weil der Dienst mitten im Upload neu startete. Er belegt Platz und
    # gehoert zu nichts mehr.
    _teil_datei(ordner, datei).unlink(missing_ok=True)

    vorher = lies_zustand(slug)
    if vorher is not None:
        # Kopieren, nicht verschieben: Die Karte in der Oberflaeche liest
        # waehrend des Uploads weiter mit, und ein Eintrag, der fuer die
        # Dauer der Uebertragung aus der Liste verschwindet, sieht aus wie
        # ein Fehler.
        shutil.copy2(_zustand_datei(slug), _sicherung_datei(slug))

    schreib_zustand(slug, {
        **({"eintrag": vorher["eintrag"]} if vorher and vorher.get("eintrag") else {}),
        "slug": slug,
        "datei": datei,
        "groesse": 0,
        "hochgeladen": _jetzt(),
        "status": "empfangen",
        "meldung": "",
        # Damit die Oberflaeche und "verwerfe" wissen, dass hier etwas zu
        # verlieren waere. Steht im Zustand und nicht nur als Datei daneben,
        # weil der Hintergrundlauf des Downloads sonst nachsehen muesste.
        "ersetzt": bool(vorher),
    })
    return slug, _teil_datei(ordner, datei)


def uebernehmen(slug: str) -> None:
    """Alles ist angekommen -- ab jetzt gilt das Neue.

    Erst hier faellt die vorherige Fassung. Vorher waere es geraten: Ein
    Upload kann an jeder Stelle abbrechen, und bis zum letzten Byte ist die
    alte die einzige, die startet.
    """
    daten = lies_zustand(slug) or {}
    ordner = verzeichnis(slug)
    datei = daten.get("datei", "abbild.iso")
    teil = _teil_datei(ordner, datei)
    if teil.exists():
        teil.replace(ordner / datei)
    _sicherung_datei(slug).unlink(missing_ok=True)
    if daten.pop("ersetzt", None) is not None:
        schreib_zustand(slug, daten)


def verwerfe(slug: str, meldung: str = "", als_fehler: bool = False) -> bool:
    """Aufraeumen nach einem Upload oder Download, der nicht zu Ende kam.

    Die halbe Datei kommt immer weg. Was mit dem Eintrag geschieht, haengt
    an zwei Fragen:

    **Gab es eine vorherige Fassung?** Dann ist sie die ganze Zeit ueber
    startbereit geblieben, und der beiseitegelegte Zustand kehrt zurueck.
    Die Meldung bekommt sie mit, ihr Status bleibt unangetastet: Sie ist ja
    weiter bereit -- fehlgeschlagen ist der Ersatz, nicht sie.

    **Hoert noch jemand zu?** Nur wenn es nichts wiederherzustellen gibt.
    Ein Download laeuft im Hintergrund, und dass der Link tot war, erfaehrt
    man ausschliesslich aus der Karte -- die muss also stehen bleiben, als
    Fehler ("als_fehler"). Ein Upload dagegen wird vom Browser abgebrochen,
    meist durch einen Seitenwechsel: Wer ihn abbricht, weiss davon, und ein
    Eintrag, den niemand angelegt hat, soll nicht zurueckbleiben.

    Gibt zurueck, ob das Verzeichnis wirklich weg ist.
    """
    daten = lies_zustand(slug) or {}
    _teil_datei(verzeichnis(slug), daten.get("datei", "abbild.iso")).unlink(missing_ok=True)

    sicherung = _sicherung_datei(slug)
    if not sicherung.exists():
        if als_fehler:
            daten.pop("ersetzt", None)
            # "gesamt" beschreibt einen Download, den es nicht mehr gibt --
            # bliebe die Zahl stehen, zeichnete die Karte weiter einen Balken.
            daten.update(status="fehler", meldung=meldung, gesamt=0)
            schreib_zustand(slug, daten)
            return False
        loesche(slug)
        return True

    # In einem Zug, nicht erst zurueckschieben und dann die Meldung
    # nachtragen: Zwischen zwei Schreibvorgaengen liest die Karte den
    # Eintrag wieder heil, aber ohne den Hinweis, dass der Ersatz nicht
    # durchkam -- und genau in dem Moment fragt die Oberflaeche nach, ob der
    # Vorgang fertig ist.
    try:
        with sicherung.open(encoding="utf-8") as fh:
            zurueck = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        zurueck = None

    if isinstance(zurueck, dict):
        zurueck.pop("ersetzt", None)
        if meldung:
            zurueck["meldung"] = meldung
        schreib_zustand(slug, zurueck)
        sicherung.unlink(missing_ok=True)
    else:
        # Die Sicherung ist unlesbar -- dann ist sie immer noch besser als
        # der halbfertige Zustand, der gerade darueber steht.
        sicherung.replace(_zustand_datei(slug))
    return False


def starte_verarbeitung(slug: str) -> None:
    """Erkennen und Entpacken laufen im Hintergrund weiter."""
    threading.Thread(target=verarbeite, args=(slug,), daemon=True).start()


# --------------------------------------------------------------------------
# Abbild von einer Adresse holen
# --------------------------------------------------------------------------


def name_aus_adresse(url: str) -> str:
    """Der Dateiname am Ende einer Adresse -- daraus entsteht die Kennung."""
    name = unquote(urlparse(url.strip()).path).rstrip("/").rsplit("/", 1)[-1]
    return name or "abbild.iso"


def hole_von_url(url: str, als_neue: bool = False) -> str:
    """Ein Abbild herunterladen und anschliessend wie einen Upload behandeln.

    Der Server laedt selbst statt ueber den Arbeitsplatz umzuleiten: eine
    Desktop-ISO waere sonst zweimal unterwegs, einmal ins Netz und einmal
    wieder heraus. Der Download laeuft im Hintergrund, die Weboberflaeche
    fragt seinen Fortschritt wie beim Entpacken ab.
    """
    adresse = url.strip()
    if not adresse.startswith(("http://", "https://")):
        raise ValueError("Nur http:// und https:// sind erlaubt.")

    slug, ziel = anlegen(name_aus_adresse(adresse), als_neue=als_neue)
    # Ein Zettel vom letzten Mal gilt nicht fuer diesen Lauf. Sonst braeche
    # ein Abbruch von gestern den Download von heute ab, und niemand kaeme
    # darauf, woran es liegt.
    vergiss_abbruch(slug)
    daten = lies_zustand(slug) or {"slug": slug}
    daten.update(status="laedt", quelle=adresse, meldung="Download beginnt ...")
    schreib_zustand(slug, daten)

    threading.Thread(target=_lade, args=(slug, adresse, ziel), daemon=True).start()
    return slug


def _lesbare_groesse(bytes_: int) -> str:
    if bytes_ >= 1073741824:
        return f"{bytes_ / 1073741824:.2f} GB"
    return f"{bytes_ / 1048576:.0f} MB"


def _lade(slug: str, url: str, ziel: Path) -> None:
    daten = lies_zustand(slug) or {"slug": slug}

    def merken(status: str, meldung: str = "", **rest) -> None:
        daten.update(status=status, meldung=meldung, **rest)
        schreib_zustand(slug, daten)

    try:
        anfrage = urllib.request.Request(url, headers={"User-Agent": "pxeweb/1.0"})
        with urllib.request.urlopen(anfrage, timeout=60) as antwort:
            gesamt = int(antwort.headers.get("content-length") or 0)

            # Beim Auspacken kommt der Inhalt noch einmal dazu, deshalb der
            # doppelte Bedarf. Lieber jetzt abbrechen als mit voller Platte.
            if gesamt and not platz_reicht(ziel.parent, gesamt * 2):
                verwerfe(slug, "Auf dem Server ist nicht genug Platz: dieses "
                               f"Abbild braucht rund {_lesbare_groesse(gesamt * 2)} "
                               "zum Laden und Auspacken.", als_fehler=True)
                return

            # Die Gesamtgroesse einmal festhalten. Beim Upload kennt der
            # Browser sie und zeichnet den Balken selbst -- hier weiss sie
            # nur der Server, also muss sie in den Zustand, damit die Karte
            # denselben Balken bekommt.
            merken("laedt", "Download beginnt ...", gesamt=gesamt)

            geladen = gemeldet = 0
            zuletzt = time.monotonic()
            with ziel.open("wb") as raus:
                while True:
                    # Bei 256 KB je Brocken sieht die Schleife oft genug
                    # nach, dass ein Abbruch sofort wirkt -- und die
                    # Abfrage selbst kostet nichts gegen das Lesen.
                    _pruefe_abbruch(slug)
                    brocken = antwort.read(1024 * 256)
                    if not brocken:
                        break
                    raus.write(brocken)
                    geladen += len(brocken)
                    # Nicht bei jedem Brocken schreiben -- das waeren
                    # Tausende Schreibvorgaenge fuer die Zustandsdatei.
                    # Aber auch nicht nur nach Menge: an einer langsamen
                    # Leitung stuenden zwischen zwei Meldungen Minuten,
                    # und der Balken in der Karte saehe aus, als haenge er.
                    if (geladen - gemeldet >= 32 * 1048576
                            or time.monotonic() - zuletzt >= 2):
                        gemeldet = geladen
                        zuletzt = time.monotonic()
                        anteil = f" ({geladen * 100 // gesamt} %)" if gesamt else ""
                        merken("laedt", f"Geladen: {_lesbare_groesse(geladen)}"
                                        + (f" von {_lesbare_groesse(gesamt)}" if gesamt else "")
                                        + anteil,
                               groesse=geladen)
    # Auf allen drei Wegen dasselbe: "verwerfe" entscheidet, ob hier ein
    # neuer Eintrag faellt oder eine vorherige Fassung zurueckkehrt. Ein
    # abgebrochener Ersatz darf nicht mehr kosten als den Ersatz selbst.
    except Abgebrochen:
        # Vor den anderen beiden, und ausdruecklich NICHT als Fehler: Wer
        # abbricht, weiss davon -- eine rote Karte, die ihm erzaehlt, was
        # er gerade selbst getan hat, ist keine Auskunft.
        verwerfe(slug, ABBRUCH_MELDUNG)
        vergiss_abbruch(slug)
        return
    except urllib.error.HTTPError as fehler:
        verwerfe(slug, f"Der Server antwortet mit {fehler.code} {fehler.reason}.",
                 als_fehler=True)
        return
    except Exception as fehler:                        # Netz, DNS, TLS, Platte
        verwerfe(slug, f"Der Download ist fehlgeschlagen: {fehler}", als_fehler=True)
        return

    if geladen == 0:
        verwerfe(slug, "Es kamen keine Daten an.", als_fehler=True)
        return

    # Erst jetzt faellt die vorherige Fassung -- bis zum letzten Byte ist
    # sie die einzige, die startet.
    uebernehmen(slug)
    daten = lies_zustand(slug) or daten
    # "gesamt" hat ausgedient, sobald alles da ist -- sonst bliebe eine
    # Zahl im Zustand stehen, die nichts mehr beschreibt.
    merken("empfangen", "", groesse=geladen, gesamt=0)
    # Ab hier ist es dasselbe wie ein Upload vom Arbeitsplatz.
    verarbeite(slug)


def _befund_sichern(befund: Befund) -> dict:
    """Den Befund in etwas verwandeln, das in die YAML passt."""
    return {feld.name: getattr(befund, feld.name) for feld in fields(Befund)}


def _befund_laden(gespeichert: dict) -> Befund:
    """Zurueck aus der YAML. Unbekannte Felder fliegen raus.

    Der Befund einer aelteren Fassung kann Felder nennen, die es nicht mehr
    gibt -- oder umgekehrt welche vermissen lassen. Beides darf hier nicht
    zum Fehler werden: was fehlt, bekommt seinen Vorgabewert.
    """
    erlaubt = {feld.name for feld in fields(Befund)}
    return Befund(**{name: wert for name, wert in gespeichert.items()
                     if name in erlaubt})


def _windows_nachlesen(befund: Befund, ordner: Path) -> None:
    """Was sich erst am ausgepackten Windows-Medium ablesen laesst.

    Zweierlei, und beides steht in den Anhaengen am Ende der WIM-Dateien:
    welches System die Konsole ist -- ohne diese Angabe startet das Setup
    und laeuft ueber das Netz in eine Sackgasse -- und was das Medium ueber
    sich selbst sagt: Generation, Fassung, Sprache, Ausgaben.

    An einer Stelle, weil es drei Wege hierher gibt: der frische Upload,
    das Neu-Einlesen und der Notbehelf fuer Abbilder aus der Zeit vor dem
    mitgespeicherten Befund. Drei Stellen zu pflegen hiesse, es zweimal zu
    vergessen.
    """
    befund.wimboot_index = wim_konsole(ordner / "sources/boot.wim")
    befund.windows_angaben = windows_angaben(ordner)


def _befund_aus_dateien(ordner: Path) -> Befund | None:
    """Den Befund eines Windows-Uploads aus den ausgepackten Dateien bilden.

    Fuer Abbilder, die vor dem Mitspeichern des Befunds hochgeladen wurden.
    Bei Windows geht das, weil die gebrauchten Dateien feste Namen haben --
    bei einem Linux-Abbild haengt die Kommandozeile vom Inhalt ab, den man
    ohne das Abbild nicht mehr sieht.
    """
    if not (ordner / "sources/boot.wim").is_file():
        return None

    befund = Befund(familie="windows", name="Windows-Konsole (WinPE)",
                    typ="wimboot", startbar=True)

    def da(*pfade: str) -> bool:
        return all((ordner / pfad).is_file() for pfad in pfade)

    if da("bootmgr", "boot/bcd", "boot/boot.sdi"):
        befund.wimboot_bios = {
            "bootmgr": "bootmgr", "BCD": "boot/bcd",
            "boot.sdi": "boot/boot.sdi", "boot.wim": "sources/boot.wim",
        }
    if da("efi/boot/bootx64.efi", "efi/microsoft/boot/bcd", "boot/boot.sdi"):
        befund.wimboot_efi = {
            "bootmgfw.efi": "efi/boot/bootx64.efi",
            "BCD": "efi/microsoft/boot/bcd",
            "boot.sdi": "boot/boot.sdi", "boot.wim": "sources/boot.wim",
        }
    if not (befund.wimboot_bios or befund.wimboot_efi):
        return None

    _windows_nachlesen(befund, ordner)
    return befund


def eintrag_neu_bauen(slug: str) -> dict:
    """Den Menueeintrag aus dem Befund neu erzeugen -- ohne das Abbild.

    Gebraucht, wenn sich die Eintragserzeugung geaendert hat: der abgelegte
    Eintrag stammt dann noch aus der alten Fassung, und das Abbild, aus dem
    er entstand, ist nach dem Entpacken geloescht. Ohne diesen Weg bliebe
    nur, mehrere Gigabyte erneut hochzuladen.
    """
    daten = lies_zustand(slug)
    if not daten:
        raise ValueError("Unbekannte Kennung")

    ordner = verzeichnis(slug)
    gespeichert = daten.get("befund")
    befund = (_befund_laden(gespeichert) if gespeichert
              else _befund_aus_dateien(ordner))
    if befund is None:
        raise ValueError(
            "Zu diesem Abbild ist nicht genug bekannt, um den Menuepunkt "
            "neu zu bauen. Dafuer bitte neu hochladen.")

    if befund.typ == "wimboot":
        _windows_nachlesen(befund, ordner)
        daten["wim_start"] = (f"Index {befund.wimboot_index} (Konsole)"
                              if befund.wimboot_index else "nicht erkannt")

    daten["befund"] = _befund_sichern(befund)
    daten["eintrag"] = baue_eintrag(slug, daten.get("datei", ""), befund)
    daten["status"] = "bereit"
    schreib_zustand(slug, daten)
    return daten


def verarbeite(slug: str) -> dict:
    """Abbild einordnen, noetige Dateien herausholen, Eintrag bauen.

    Hier faellt die Entscheidung, dass das Neue gilt: Wer bis zum Entpacken
    kommt, hat alle Daten beisammen. Vorher laesst sich noch zurueck --
    danach nicht mehr, denn ausgepackt wird in dasselbe Verzeichnis.

    Die Uebernahme steht deshalb an dieser Stelle und nicht bei den
    Aufrufern: Upload, Download und jeder Test kaemen sonst einzeln in die
    Lage, sie zu vergessen, und das faellt erst auf, wenn ein Abbild
    unauffindbar ist.
    """
    uebernehmen(slug)
    daten = lies_zustand(slug) or {"slug": slug}
    ordner = verzeichnis(slug)
    iso_pfad = ordner / daten.get("datei", "abbild.iso")

    def merken(status: str, meldung: str = "", **rest) -> dict:
        daten.update(status=status, meldung=meldung, **rest)
        schreib_zustand(slug, daten)
        return daten

    if not iso_pfad.exists():
        return merken("fehler", "Die hochgeladene Datei ist verschwunden.")

    daten["groesse"] = iso_pfad.stat().st_size

    # --- Erkennen (dauert Millisekunden) ----------------------------------
    try:
        befund = untersuche(iso_pfad)
    except IsoFehler as fehler:
        return merken("fehler", str(fehler))
    except Exception:                                  # pragma: no cover
        traceback.print_exc()
        return merken("fehler", "Das Abbild liess sich nicht lesen.")

    daten["familie"] = befund.familie
    daten["erkannt"] = befund.name or befund.volume_id

    if not befund.startbar:
        return merken("nicht-startbar", befund.hinweis)

    # --- Weg festlegen: Arbeitsspeicher oder NFS --------------------------
    # Der Vorgabeweg holt das Abbild ueber HTTP in eine RAM-Disk; das ist
    # einfach und braucht keinen weiteren Dienst, begrenzt die Groesse aber
    # auf den Arbeitsspeicher des bootenden Rechners. Steht ein NFS-Export
    # bereit, wird stattdessen das ausgepackte Abbild gestreamt.
    if NFS_ROOT and befund.cmdline_nfs:
        befund.cmdline = befund.cmdline_nfs.replace(
            "{nfsroot}", "${srvip}:" + f"{NFS_ROOT}/{slug}")
        befund.ganzes_iso = True
        befund.iso_behalten = False
        daten["weg"] = "nfs"
    elif SMB_ROOT and befund.typ == "wimboot" and befund.windows_quellen:
        # Windows mit Installationsquellen und einer Freigabe, die sie
        # ausliefern kann: Dann wird das ganze Medium ausgepackt und nicht
        # nur die Handvoll Startdateien. Aus ein paar hundert MB werden
        # mehrere Gigabyte -- dafuer laesst sich davon installieren.
        #
        # Die Konsole selbst startet weiter aus dem Arbeitsspeicher; die
        # Freigabe kommt erst dazu, wenn dort jemand setup.exe aufruft.
        befund.ganzes_iso = True
        befund.iso_behalten = False
        daten["weg"] = "smb"
    else:
        daten["weg"] = "ram"

    # --- Entpacken (dauert je nach Abbild Minuten) ------------------------
    merken("entpacken", "")
    with _riegel:
        try:
            gebraucht = daten["groesse"] if befund.ganzes_iso else 0
            if gebraucht and shutil.disk_usage(ordner).free < gebraucht + 1024 ** 3:
                return merken(
                    "fehler",
                    "Zu wenig Platz auf der Platte: dieses Abbild muss "
                    "vollstaendig entpackt werden und braucht noch einmal "
                    f"{gebraucht // 1024 ** 3} GB.",
                )
            with Iso(iso_pfad) as iso:
                if befund.ganzes_iso:
                    _entpacke_alles(iso, ordner)
                else:
                    for pfad in befund.dateien:
                        if not iso.entpacke(pfad, ordner / pfad):
                            return merken("fehler", f"{pfad} liess sich nicht entpacken.")
        except Exception:                              # pragma: no cover
            traceback.print_exc()
            return merken("fehler", "Beim Entpacken ist etwas schiefgegangen.")

    # Windows: welches System im boot.wim ist die Konsole? Ohne diese Angabe
    # startet das Setup, und das laeuft ueber das Netz in eine Sackgasse.
    # Erst jetzt zu bestimmen ist kein Umweg: die Namen stehen am Ende der
    # Datei, und die liegt vorher noch im Abbild.
    if befund.typ == "wimboot":
        _windows_nachlesen(befund, ordner)
        daten["wim_start"] = (f"Index {befund.wimboot_index} (Konsole)"
                              if befund.wimboot_index else "nicht erkannt")

    # Was nicht mehr gebraucht wird, kommt weg -- ein entpacktes Abbild
    # belegt sonst doppelt Platz.
    if not befund.iso_behalten:
        iso_pfad.unlink(missing_ok=True)

    # nginx liefert als www-data aus und braucht Lesezugriff.
    _lesbar_machen(ordner)

    # Den Befund mit ablegen. Damit laesst sich der Menueeintrag spaeter
    # neu bauen, ohne das Abbild noch einmal zu lesen -- und das Abbild ist
    # nach dem Entpacken meistens geloescht. Gebraucht wird das nach jeder
    # Aenderung an der Eintragserzeugung: der gespeicherte Eintrag stammt
    # sonst weiter aus der Fassung, unter der er entstanden ist.
    daten["befund"] = _befund_sichern(befund)
    daten["eintrag"] = baue_eintrag(slug, daten["datei"], befund)
    return merken("bereit", "")


def _entpacke_alles(iso: Iso, ziel: Path) -> None:
    """Den kompletten Inhalt des Abbilds herausschreiben.

    Reicht fuer archiso, Anaconda und openSUSE: die holen sich zur Laufzeit
    Pakete und Wurzeldateisystem per HTTP aus diesem Verzeichnis. Symbolische
    Verweise im Abbild werden dabei zu leeren Dateien -- fuer diese drei
    Familien spielt das keine Rolle.
    """
    for eintrag in iso.eintraege.values():
        # Gesucht wird kleingeschrieben, abgelegt unter der Schreibweise des
        # Abbilds: Ubuntu sucht seinen Bootloader unter "EFI/boot/", und auf
        # einem Linux-Dateisystem ist "efi" ein anderer Name.
        if eintrag.ordner:
            (ziel / eintrag.echter_pfad).mkdir(parents=True, exist_ok=True)
        elif eintrag.groesse > 0:
            iso.entpacke(eintrag.pfad, ziel / eintrag.echter_pfad)


def _lesbar_machen(ordner: Path) -> None:
    for pfad, ordnernamen, dateien in os.walk(ordner):
        for name in ordnernamen:
            _chmod(Path(pfad) / name, 0o755)
        for name in dateien:
            _chmod(Path(pfad) / name, 0o644)
    _chmod(ordner, 0o755)


def _chmod(pfad: Path, rechte: int) -> None:
    try:
        pfad.chmod(rechte)
    except OSError:
        pass


def menuename(text: str, ersatz: str) -> str:
    """Anzeigetext fuers Bootmenue entschaerfen.

    iPXE ersetzt in jeder Zeile ${...} durch Variablen. Ein Dollarzeichen im
    Namen des Abbilds -- etwa aus einem kaputten Datentraegernamen -- wuerde
    das Menue durcheinanderbringen. Deshalb fliegt es hier raus.
    """
    sauber = re.sub(r"[${}|\\]", "", text or "").strip()
    sauber = re.sub(r"\s+", " ", sauber)
    return sauber[:70] or ersatz


def version_aus(text: str) -> str:
    """Die Versionsnummer aus dem Namen eines Abbilds, wenn eine drinsteht.

    Ein Medium meldet sich mit allem, was es hat:

        Ubuntu 26.04 "Resolute Raccoon" - Release amd64 (20260423.1)
        Linux Mint 22.3 Cinnamon

    Gesucht wird eine ein- bis zweistellige Zahl mit Punkt, die als eigenes
    Wort dasteht -- "26.04", "22.3", "16.1". Drei Faelle fallen damit
    heraus, und zwar mit Absicht:

        20260423.1              das Baudatum am Ende (zu viele Stellen)
        Fedora-Server-44-1.5    dort waere "1.5" die Bau-, nicht die
                                Ausgabennummer -- sie klebt am Bindestrich
        Debian GNU/Linux 13     eine Zahl ohne Punkt ist von "amd64" oder
                                "x86_64" nicht sicher zu unterscheiden

    Findet sich nichts, bleibt das Feld leer. Ein falscher Vorschlag waere
    schlimmer als keiner: er stuende im Bootmenue, ohne dass jemand ihn
    eingetragen hat. Ueberschreiben laesst sich beides -- unter Quellen wie
    unter Systeme.
    """
    treffer = re.search(r"(?:^|\s)(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)(?=\s|$)",
                        text or "")
    return treffer.group(1) if treffer else ""


def baue_eintrag(slug: str, datei: str, befund) -> dict:
    """Aus dem Befund einen Katalogeintrag machen -- gleiche Form wie in
    catalog.yaml, damit die Vorlagen ihn ohne Sonderbehandlung rendern."""
    basis = "${assets}/" + slug

    def unter(pfad: str) -> str:
        return f"{slug}/{pfad}"

    if befund.typ == "wimboot":
        return _wimboot_eintrag(slug, datei, unter, befund)

    kernel = unter(befund.kernel)
    initrds = [unter(p) for p in befund.initrd]

    noetig = list(dict.fromkeys([kernel, *initrds]))
    if befund.iso_behalten:
        noetig.append(unter(datei))
    else:
        noetig += [unter(p) for p in befund.dateien if p not in (befund.kernel, *befund.initrd)]

    # Kein str.format hier: die Kommandozeile enthaelt "${assets}", das
    # format() als Platzhalter missverstehen wuerde.
    cmdline = befund.cmdline.replace("{basis}", basis).replace("{iso}", datei)

    return {
        "slug": slug,
        "name": menuename(befund.name, datei),
        "version": version_aus(befund.name),
        "description": "selbst hochgeladen",
        "category": OHNE_NETZ if vom_server(cmdline) else MIT_NETZ,
        "platforms": ["pcbios", "efi"],
        "type": "kernel",
        "kernel": kernel,
        "initrd": initrds,
        "cmdline": cmdline,
        "assets": noetig,
    }


def _wimboot_eintrag(slug: str, datei: str, unter, befund) -> dict:
    """Katalogeintrag fuer eine Windows-Konsole (WinPE).

    Kein Kernel, keine Kommandozeile -- stattdessen zwei Saetze benannter
    Dateien, einer fuer BIOS und einer fuer UEFI. Fehlt einer davon im
    Abbild, faellt die zugehoerige Plattform aus der Liste: der Eintrag
    erscheint dann gar nicht erst im Menue eines Rechners, der damit nichts
    anfangen koennte.
    """
    # Liegen die Installationsquellen ausgepackt daneben, ist dieser Eintrag
    # mehr als eine Konsole: Von ihm aus laesst sich Windows installieren.
    # Dann gehoert er nicht unter die Rettungswerkzeuge, sondern zu den
    # Offline-Installationen -- nach genau der Regel, die oben fuer die
    # Gruppen steht: Der Installer bekommt seine Dateien vom Bootserver.
    #
    # Der Name nennt beides und verspricht nichts Falsches: Gestartet wird
    # die Konsole, das Setup ist von dort aus erreichbar. Solange die zwei
    # Zeilen von Hand kommen (B-042), waere "Windows installieren" eine
    # halbe Wahrheit.
    installierbar = bool(befund.windows_quellen and befund.ganzes_iso)

    saetze = {}
    plattformen = []
    if befund.wimboot_bios:
        saetze["bios"] = {name: unter(pfad)
                          for name, pfad in befund.wimboot_bios.items()}
        plattformen.append("pcbios")
    if befund.wimboot_efi:
        saetze["efi"] = {name: unter(pfad)
                         for name, pfad in befund.wimboot_efi.items()}
        plattformen.append("efi")

    return {
        "slug": slug,
        "name": ("Windows-Setup (WinPE-Konsole)" if installierbar
                 else menuename(befund.name, "Windows-Konsole (WinPE)")),
        "version": version_aus(befund.name),
        # Alle Windows-Abbilder ergeben denselben Menuenamen -- ob Konsole
        # oder Setup, der Name sagt nichts ueber die Ausgabe. Damit zwei
        # hochgeladene im Menue auseinanderzuhalten sind, steht der
        # Dateiname daneben; er ist das Einzige, was sie unterscheidet.
        "description": menuename(datei, "hochgeladenes Abbild"),
        "category": OHNE_NETZ if installierbar else WERKZEUG,
        "platforms": plattformen,
        "type": "wimboot",
        "wimboot_loader": "wimboot/wimboot",
        "wimboot_index": befund.wimboot_index,
        "wimboot": saetze,
    }

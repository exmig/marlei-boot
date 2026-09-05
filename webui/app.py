"""
MARLEI Boot -- Weboberflaeche und iPXE-Skriptgenerator.

Ablauf eines Netzwerk-Boots:

  1. Der Client schaltet ein, sein PXE-ROM fragt per DHCP nach.
  2. Der Router vergibt die IP, dnsmasq (proxyDHCP) sagt zusaetzlich:
     "Deinen Bootloader findest du per TFTP hier."
  3. Der Client laedt iPXE (undionly.kpxe bzw. snponly.efi) und startet es.
  4. iPXE fragt erneut per DHCP -- dnsmasq erkennt es an Option 175 und
     schickt es zu  http://<server>/boot.ipxe
  5. /boot.ipxe ist nur ein Vorspann: es sammelt MAC, Architektur und
     Plattform ein und laedt damit /menu.ipxe nach.
  6. /menu.ipxe entscheidet:
        - Liegt fuer diese MAC eine Vorauswahl vor?  -> direkt durchbooten
        - sonst -> Auswahlmenue auf dem Bildschirm des Clients anzeigen
  7. Die Auswahl laedt /boot/<slug>.ipxe, das Kernel und Initrd startet.

Die Bootmenue-Eintraege stehen in catalog.yaml und werden bei jeder Aenderung
automatisch neu eingelesen -- kein Neustart des Dienstes noetig.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import yaml
from fastapi import FastAPI, Form, HTTPException, Request
from starlette.requests import ClientDisconnect
from fastapi.responses import (FileResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader

import auslastung
import befunde
import kenntnis
import bezeichnungen
import dienste
import eigene
import firewall
import freigabe
import gruppen
import isoscan
import journal
import konfiguration
import logs
import muster
import quellen
import bericht
import einstellungen
import quellenwacht
import umgebung
import updatewacht
import selbstauskunft
import serveradresse
import sync
import uploads
import versionsstand
import werkseinstellung
import wol

# --------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"

BASE_URL = os.environ.get("PXE_BASE_URL", "http://127.0.0.1").rstrip("/")
# Dieselbe Adresse ohne "http://" -- NFS-Angaben sind keine URLs.
SERVER_HOST = urlparse(BASE_URL).hostname or "127.0.0.1"
CATALOG_PATH = Path(os.environ.get("PXE_CATALOG", BASE_DIR / "catalog.yaml"))
ASSETS_DIR = Path(os.environ.get("PXE_ASSETS", "/srv/pxe/assets"))

# Die SMB-Freigabe fuer Windows-Installationen (B-027). Leer heisst: Samba
# ist nicht eingerichtet, dann bleibt es bei der Konsole.
#
# Das Passwort steht hier im Klartext und wird in der Hilfe angezeigt. Das
# ist Absicht und kein Versehen: Die freigegebenen Dateien liefert nginx
# ohnehin **ohne jede Anmeldung** ueber HTTP aus -- die Freigabe macht
# dieselben Abbilder nur auf einem zweiten Weg erreichbar, weil ein
# Windows-Setup nichts anderes annimmt. Das Konto schuetzt also nichts, was
# nicht ohnehin offen laege; es existiert allein, weil Windows seit Version
# 10 (1709) den Gastzugang auf SMB2/SMB3 selbst abschaltet.
SMB_ROOT = os.environ.get("PXE_SMB_ROOT", "").rstrip("/")
SMB_BENUTZER = os.environ.get("PXE_SMB_BENUTZER", "")
SMB_PASSWORT = os.environ.get("PXE_SMB_PASSWORT", "")
DB_PATH = Path(os.environ.get("PXE_DB", BASE_DIR / "pxeweb.db"))
MENU_TIMEOUT = int(os.environ.get("PXE_MENU_TIMEOUT", "30"))

# Vorgabereihenfolge der Gruppen im Bootmenue und auf der Systeme-Seite.
# Was ohne Internet auskommt, steht oben: das ist die Auswahl, die auch dann
# noch durchlaeuft, wenn die Leitung nicht mitspielt. Kategorien, die hier
# nicht stehen, kommen in ihrer Reihenfolge aus dem Katalog dahinter.
#
# Es ist die Vorgabe, nicht das letzte Wort: unter Systeme laesst sich die
# Reihenfolge umstellen, sie liegt dann in /var/lib/pxeweb/gruppen.yaml
# (siehe gruppen.py). Beide Seiten -- Karten und Bootmenue -- lesen sie
# ueber _nach_gruppen(), damit sie nicht auseinanderlaufen koennen.
GRUPPEN = [uploads.OHNE_NETZ, uploads.MIT_NETZ, "Rettung und Wartung"]
MENU_DEFAULT = os.environ.get("PXE_MENU_DEFAULT", "local")

# Ist das hier die Produktion, oder nicht?
#
# Wer zwei Server offen hat, aendert sonst irgendwann etwas auf dem
# falschen. Steht hier ein Wort, faerbt sich der Seitengrund und das Wort
# steht in der Kopfzeile -- LEER heisst Produktion, und damit bleibt der
# produktive Server unveraendert, ohne dass dort jemand etwas eintraegt.
#
# Nur ein Wort und keine Farbe: Kontrast wird in diesem Projekt gerechnet
# und nicht geraten, und ein freies Farbfeld hiesse geraten. Alle
# Nicht-Produktionsserver sehen deshalb gleich aus -- was auch die
# richtige Aussage ist.
#
# Gekuerzt, weil es in die Kopfzeile passen muss.
KENNZEICHNUNG = os.environ.get("PXE_KENNZEICHNUNG", "").strip()[:20]

app = FastAPI(title="MARLEI Boot", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def seiten_nicht_aufheben(request: Request, call_next):
    """Eine Seite dieser Oberflaeche darf der Browser nicht aufheben.

    **Der Fall vom 04.09.2026, und er kostete eine Stunde Suche:** Nach
    einem Update sah Markus im Befehlsblock einen schwarzen Balken ohne
    Text -- kopieren liess sich der Befehl trotzdem. Es war die alte Seite
    aus dem Zwischenspeicher; ein hartes Neuladen holte den Text zurueck.

    Die Seiten trugen bis dahin **keinen einzigen** Zwischenspeicher-Kopf.
    Ohne Anweisung entscheidet der Browser selbst, wie lange er eine Seite
    fuer frisch haelt -- und liegt bei einer Oberflaeche, deren Inhalt sich
    mit jedem Klick aendert, regelmaessig daneben.

    Nur HTML. Das Stylesheet und die Logos sollen weiter aufgehoben
    werden: Sie tragen ihre Aenderungszeit in der Adresse (siehe
    datei_version) und holen sich damit selbst zurueck, wenn sie sich
    aendern.
    """
    antwort = await call_next(request)
    art = antwort.headers.get("content-type", "")
    if art.startswith("text/html"):
        antwort.headers["Cache-Control"] = "no-store"
    return antwort

# Fuer HTML: mit Autoescaping (Schutz gegen kaputte Geraetenamen im Browser).
html = Jinja2Templates(directory=str(TEMPLATE_DIR))

def lesbare_zeit(roh: str) -> str:
    """Aus einem Zeitstempel etwas machen, das man lesen kann.

    Gespeichert wird in UTC nach ISO 8601 -- richtig, aber
    "2026-08-21T14:54:45+00:00" liest niemand gern, und es ist auch nicht
    die Uhrzeit des Betrachters. Angezeigt wird deshalb Ortszeit, und statt
    des Datums steht bei den letzten Tagen "heute" oder "gestern".
    """
    if not roh:
        return ""
    try:
        wann = datetime.fromisoformat(roh)
    except ValueError:
        try:                                   # Protokolle: 20260821T100924Z
            wann = datetime.strptime(roh, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return roh
    if wann.tzinfo is None:
        wann = wann.replace(tzinfo=timezone.utc)

    hier = wann.astimezone()
    heute = datetime.now().astimezone().date()
    tage = (heute - hier.date()).days
    if tage == 0:
        return hier.strftime("heute %H:%M")
    if tage == 1:
        return hier.strftime("gestern %H:%M")
    if hier.year == heute.year:
        return hier.strftime("%d.%m. %H:%M")
    return hier.strftime("%d.%m.%Y %H:%M")


def lesbare_frist(roh: str) -> str:
    """Wie lange es noch dauert -- "in 6 Tagen", "in 5 Stunden".

    Fuer Zeitpunkte, die noch kommen. Die Einheit richtet sich nach dem
    Abstand: Bei einem Waechter, der alle sieben Tage geht, waere "in 168
    Stunden" richtig und trotzdem unbrauchbar.

    Leer, wenn nichts kommt (der Waechter ist abgeschaltet oder noch nie
    gelaufen) -- die Vorlage entscheidet dann, was stattdessen dasteht.
    """
    if not roh:
        return ""
    try:
        wann = datetime.fromisoformat(roh)
    except (TypeError, ValueError):
        return ""
    if wann.tzinfo is None:
        wann = wann.replace(tzinfo=timezone.utc)

    rest = wann - datetime.now(timezone.utc)
    stunden = rest.total_seconds() / 3600
    if stunden <= 0:
        return "jetzt"
    if stunden < 1:
        return "in weniger als einer Stunde"
    if stunden < 48:
        n = round(stunden)
        return "in %d Stunde%s" % (n, "" if n == 1 else "n")
    n = round(stunden / 24)
    return "in %d Tagen" % n


# Fuer iPXE-Skripte: OHNE Autoescaping. Sonst wuerde Jinja das "&" in
# Query-Strings zu "&amp;" machen und iPXE bekaeme falsche Parameter.
ipxe = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=False,
    keep_trailing_newline=True,
)


def lesbare_groesse(bytes_: int) -> str:
    """Bytes als Zahl, die man vorlesen kann."""
    for grenze, einheit in ((1073741824, "GB"), (1048576, "MB"), (1024, "KB")):
        if bytes_ >= grenze:
            return f"{bytes_ / grenze:.2f} {einheit}".replace(".00 ", " ")
    return f"{bytes_} B"


def menuezeile(eintrag: dict) -> str:
    """Die Zeile, wie sie im Bootmenue steht.

    Gebaut wird sie hier und nicht in den Vorlagen, weil zwei sie
    brauchen: das Menue selbst und die Vorschau unter Systeme. Zweimal
    dieselbe Formatierung hinzuschreiben hiess bisher, sie zweimal aendern
    zu muessen -- und einmal zu vergessen.

    Der zweite Grund ist feiner. In der HTML-Vorlage ist die Ausgabe eines
    Makros bereits maskiert; ein Anfuehrungszeichen zaehlt dort als
    "&#34;", also fuenf Zeichen. Die Vorschau schnitt eine Zeile mit
    Anfuehrungszeichen deshalb acht Zeichen zu frueh ab und behauptete,
    im Menue fehle mehr, als wirklich fehlt. Als gewoehnliche Zeichenkette
    zaehlt hier, was auch der Bildschirm zaehlt.
    """
    name = eintrag.get("name", "")
    version = eintrag.get("version") or ""
    erste = f"{name} {version}" if name and version else (name or version)
    # Hart gekuerzt, nicht nur aufgefuellt: Eine Spalte, die bei einem
    # langen Namen mitwaechst, ist keine. Vorher schob ein Abbild mit
    # sechzig Zeichen Volume-Label die Angaben aller anderen Zeilen nach
    # rechts -- und weil das nur diese eine Zeile betraf, sah das Menue
    # aus, als sei es kaputt. Was hier wegfaellt, meldet die Karte unter
    # Quellen ("im Menü gekürzt"); dort laesst es sich auch kuerzen.
    erste = erste[:bezeichnungen.MAX_ZEILE]
    zusatz = eintrag.get("menue_text") or ""
    return f"{erste:<{bezeichnungen.MAX_ZEILE}}" + (f"  ({zusatz})" if zusatz else "")


html.env.filters["zeit"] = lesbare_zeit
html.env.filters["frist"] = lesbare_frist
html.env.filters["groesse"] = lesbare_groesse
html.env.filters["menuezeile"] = menuezeile
ipxe.filters["menuezeile"] = menuezeile


# --------------------------------------------------------------------------
# Katalog der Boot-Eintraege
# --------------------------------------------------------------------------

_catalog_cache: dict[str, Any] = {"mtime": None, "entries": []}


def load_catalog() -> list[dict]:
    """Alle Menue-Eintraege: die aus catalog.yaml plus die selbst hochgeladenen.

    catalog.yaml wird nur neu gelesen, wenn die Datei sich geaendert hat.
    Die Uploads kommen frisch dazu -- das sind ein paar kleine Dateien, und
    so erscheint ein gerade fertig entpacktes Abbild sofort im Menue.

    Ganz zum Schluss kommen die eigenen Namen darueber. Das passiert hier
    und nicht in _ergaenze(), weil die Katalogdatei zwischengespeichert
    wird: eine Umbenennung wuerde sonst erst greifen, wenn sich
    catalog.yaml aendert. wende_an() gibt eine Kopie zurueck und laesst den
    zwischengespeicherten Eintrag in Ruhe.
    """
    return [freigabe.wende_an(_mit_menue_info(bezeichnungen.wende_an(e))) for e in
            (_catalog_datei()
             + [_ergaenze(e) for e in uploads.katalog_eintraege()]
             + [_ergaenze(e) for e in eigene.katalog_eintraege()])]


def _abgelesene_info(eintrag: dict) -> str:
    """Was ohne eigenes Zutun im Menue hinter dem Namen steht.

    Bei den mitgelieferten Systemen das, was in ihren Dateien steht -- bei
    einem Upload der Name, unter dem sich das Abbild gemeldet hat. Bei
    einem selbst angelegten Eintrag der Text aus seinem Formular; den hat
    jemand hingeschrieben, er ist also schon eine Eingabe.

    Bleibt nichts uebrig, steht die Kennung da: Eine Zeile, die mal da ist
    und mal nicht, liest sich als Fehler, und die Kennung gibt es immer.
    """
    # Woher der Eintrag kam, sagt seine Kennung: "iso-" ist hochgeladen,
    # "netz-" selbst angelegt, alles andere kommt aus dem Katalog. Vorher
    # stand das im Pfad ("upload/...", "eigene/..."); seit jeder Eintrag in
    # seinem eigenen Verzeichnis wohnt, steht es in der Kennung selbst.
    slug = eintrag.get("slug", "")
    if slug.startswith(uploads.UPLOAD_PRAEFIX) or eintrag.get("type") == "wimboot":
        return eintrag.get("name_vorgabe") or eintrag.get("name", "") or slug
    if slug.startswith(eigene.EIGEN_PRAEFIX):
        return eintrag.get("description", "") or slug
    pfade = required_assets(eintrag)
    gelesen = selbstauskunft.aus_pfaden(ASSETS_DIR, [ASSETS_DIR / p for p in pfade])
    return gelesen or eintrag.get("slug", "")


def _mit_menue_info(eintrag: dict) -> dict:
    """Was im Bootmenue hinter Name und Version steht.

    Drei Stufen, und jede hat ihren Grund:

        eingetippt      dein Feld unter Quellen gewinnt immer
        menue_info      der kurze Satz aus catalog.yaml
        abgelesen       was das Abbild ueber sich selbst sagt
        Kennung         damit die Spalte nie leer bleibt

    Die mittlere Stufe fehlte lange, und das sah man: Im Menue stand
    "(debian-13)" und "(RESCUE1302)" -- eine Kennung und ein Volume-Label
    in der Spalte, die dem Menschen vor der Maschine sagen soll, worauf er
    sich einlaesst. Der gepflegte Satz lag daneben und wurde verworfen.

    Nicht angefasst wird "description". Das ist seit August 2026 der
    lange Text fuer die Weboberflaeche -- wofuer diese Distribution gut
    ist -- und hat im Menue nichts zu suchen: Dort sind 29 Zeichen Platz.
    """
    vorgabe = eintrag.get("menue_info") or _abgelesene_info(eintrag)
    return {**eintrag,
            "info_vorgabe": vorgabe,
            "menue_text": eintrag.get("info") or vorgabe}


def _entfalte(item: dict) -> list[dict]:
    """Aus einem mehrversionigen Eintrag je Version einen eigenen machen.

    Ein Eintrag mit "versionen_aus" beschreibt nur das Muster; die Liste der
    Ausgaben steht bei den Quellen und wird im Browser gepflegt. So bleibt
    das Installationsmedium einer aelteren Version verfuegbar, solange
    Rechner damit im Betrieb sind -- und eine neue Ausgabe aufzunehmen ist
    ein Eintrag in der Liste, keine Aenderung am Katalog.
    """
    quelle = item.get("versionen_aus")
    if not quelle:
        return [item]

    eintraege = []
    for version in quellen.liste(quelle):
        kopie = _mit_version(item, version)
        kopie.pop("versionen_aus", None)
        # Damit die Oberflaeche weiss, wo diese Version einzutragen ist,
        # wenn sie wieder weg soll.
        kopie["versionsliste"] = quelle
        eintraege.append(kopie)
    return eintraege


def _mit_version(item: dict, version: str) -> dict:
    """{version} ueberall einsetzen und einen eindeutigen Slug bilden."""
    # Der Slug wird im iPXE-Menue als Sprungmarke benutzt -- Punkte haben
    # dort nichts zu suchen, aus 26.04 wird deshalb 26-04.
    kennung = re.sub(r"[^a-z0-9]+", "-", version.lower()).strip("-")

    def ein(wert):
        if isinstance(wert, str):
            return wert.replace("{version}", version)
        if isinstance(wert, list):
            return [ein(w) for w in wert]
        return wert

    kopie = {schluessel: ein(wert) for schluessel, wert in item.items()}
    kopie["slug"] = f"{item['slug']}-{kennung}"
    kopie["version"] = version
    return kopie


def _mit_kennung(item: dict) -> dict:
    """{slug} ueberall einsetzen -- der Ordner heisst wie der Eintrag.

    Ein Eintrag besitzt genau ein Verzeichnis, und es traegt seine
    Kennung: assets/<slug>/. Damit ist die Frage "was gehoert diesem
    Eintrag?" nicht mehr zu beantworten, sondern abzulesen -- und die
    Regeln, die sie frueher beantworteten (der Zaun um die Startdateien,
    die Nachbarordner, das Lesen der Kommandozeile), sind ersatzlos weg.
    Zwei Fehler kamen aus diesen Regeln; keiner davon kann wiederkommen.

    Eingesetzt wird nach der Version: Bei einem mehrversionigen Eintrag
    ist {slug} die fertige Kennung mitsamt Ausgabe -- aus "gparted-live"
    und "1.8.1-3" wird "gparted-live-1-8-1-3", und genau so heisst sein
    Ordner.
    """
    kennung = item.get("slug", "")

    def ein(wert):
        if isinstance(wert, str):
            return wert.replace("{slug}", kennung)
        if isinstance(wert, list):
            return [ein(w) for w in wert]
        if isinstance(wert, dict):
            return {k: ein(w) for k, w in wert.items()}
        return wert

    return {schluessel: ein(wert) for schluessel, wert in item.items()}


def _nfs_weg(item: dict) -> None:
    """Zwischen den zwei Kommandozeilen eines Eintrags waehlen.

    Fuenf Eintraege koennen ihr Wurzeldateisystem per NFS einhaengen statt
    es zu laden -- Mint, Debian Live, SystemRescue, GParted und Clonezilla.
    Das ist der bessere Weg, solange ein Export bereitsteht: Ein 3 GB
    grosses Live-System startet damit auch auf einem Rechner, in dem 4 GB
    stecken. Steht keiner bereit, war die NFS-Zeile bisher trotzdem drin,
    und der Start scheiterte vor der Maschine -- die Zeile stand fest in
    catalog.yaml, samt ausgeschriebenem /srv/pxe/assets.

    Beides ist damit erledigt: Der Pfad kommt aus PXE_NFS_ROOT (dasselbe,
    was install.sh exportiert), und ohne Export gilt "cmdline" -- der Weg
    ueber HTTP. Wer nur "cmdline_nfs" hat, ist ohne NFS nicht startbereit;
    das sagt "braucht_nfs" weiter an entry_ready().
    """
    mit_nfs = item.pop("cmdline_nfs", "")
    if not mit_nfs:
        return
    if uploads.NFS_ROOT:
        item["cmdline"] = mit_nfs.replace(
            "{nfsroot}", "${srvip}:" + f"{uploads.NFS_ROOT}/{item.get('slug', '')}")
    elif not item.get("cmdline"):
        item["braucht_nfs"] = True


def _ergaenze(item: dict) -> dict:
    """Fehlende Felder mit den ueblichen Vorgaben auffuellen."""
    item = _mit_kennung(item)
    item.setdefault("category", "Sonstiges")
    # Ein Eintrag, der vor der Umbenennung der Gruppen entstanden ist, traegt
    # den alten Namen in seiner eintrag.yaml -- die liegt bei den Abbildern
    # und uebersteht jedes Update. Ohne diese Zeile stuende er unter
    # "Sonstiges" statt in seiner Gruppe.
    item["category"] = uploads.gruppe_heute(item["category"])
    item.setdefault("description", "")
    # Der kurze Satz fuers Bootmenue. Steht er nicht da, springt das
    # Abgelesene ein -- siehe _mit_menue_info.
    item.setdefault("menue_info", "")
    item.setdefault("type", "kernel")
    item.setdefault("cmdline", "")
    _nfs_weg(item)
    # Windows-Eintraege starten ueber wimboot. Das Programm liegt bei den
    # Abbildern, nicht im TFTP-Verzeichnis -- es geht wie alles nach dem
    # ersten Bootloader ueber HTTP. Geholt wird es von fetch-wimboot.sh.
    if item["type"] == "wimboot":
        item.setdefault("wimboot_loader", "wimboot/wimboot")
        item.setdefault("wimboot", {})
        # Welches System aus dem boot.wim starten soll. 0 heisst: keine
        # Angabe, dann entscheidet wimboot selbst -- bei einem
        # Installationsmedium faellt die Wahl dann auf das Setup.
        item.setdefault("wimboot_index", 0)
    # Auf welchen Plattformen darf der Eintrag erscheinen?
    # pcbios = Rechner im Legacy-/CSM-Modus, efi = moderne UEFI-Rechner.
    if not item.get("platforms"):
        item["platforms"] = _plattformen(item)
    return item


# Endungen, die eine Bauart verraten. Alles andere -- Kernel und Initrd,
# ein iPXE-Skript, eine ISO zum sanboot -- laeuft in beiden Firmwares.
NUR_EFI = (".efi",)
NUR_BIOS = (".lkrn", ".0", ".bin", ".kpxe", ".kkpxe", ".c32", ".img")


def _plattformen(eintrag: dict) -> list[str]:
    """Auf welchen Rechnern dieser Eintrag angeboten werden darf.

    Abgelesen an dem, was er laedt, statt von Hand gepflegt. Eine Zeile in
    catalog.yaml, die jemand beim naechsten Eintrag vergisst, ist der
    haeufigere Fehler als eine Bauart, die sich nicht ansehen laesst.

    Der Dateiname entscheidet, nicht der Dateiinhalt -- und zwar aus zwei
    Gruenden. Ein Eintrag muss auch dann eine Plattform haben, wenn seine
    Dateien noch fehlen (er steht ja in der Liste, mit "fehlt" daneben).
    Und der Inhalt gibt es nicht her: Memtests BIOS-Ausgabe "memtest.bin"
    ist ein ganz gewoehnliches Linux-Kernel-Abbild, im Kopf nicht von
    Debians vmlinuz zu unterscheiden. Dass es nur fuer BIOS gebaut ist,
    sagt allein sein Name.

    Wo das nicht reicht, gilt weiter, was in catalog.yaml steht: Eine
    eigene Angabe gewinnt. Sie steht dort nirgends mehr -- vergessen kann
    man nur, was man pflegen muss.
    """
    if eintrag.get("type") == "wimboot":
        # Windows: Je Firmware ein eigener Satz benannter Dateien. Fehlt
        # einer im Abbild, kann dieser Rechner damit nichts anfangen.
        saetze = eintrag.get("wimboot") or {}
        gefunden = [name for schluessel, name in (("bios", "pcbios"), ("efi", "efi"))
                    if saetze.get(schluessel)]
        return gefunden or ["pcbios", "efi"]

    geladen = (eintrag.get("url") or eintrag.get("kernel") or "")
    if isinstance(geladen, list):
        geladen = geladen[0] if geladen else ""
    # Ohne Anhaengsel und ohne Platzhalter: aus ".../memtest.efi?x=1" wird
    # ".efi".
    name = str(geladen).split("?")[0].split("#")[0].rstrip("/").lower()
    if name.endswith(NUR_EFI):
        return ["efi"]
    if name.endswith(NUR_BIOS):
        return ["pcbios"]
    return ["pcbios", "efi"]


def _catalog_datei() -> list[dict]:
    try:
        mtime = CATALOG_PATH.stat().st_mtime
    except FileNotFoundError:
        return []

    # Die Versionslisten gehoeren zum Zustand dazu: wird eine Ausgabe
    # eingetragen, muss der Katalog neu entstehen, obwohl die Datei
    # unveraendert ist.
    stand = (mtime, tuple(sorted(quellen.alle_werte().items())))
    if _catalog_cache["mtime"] == stand:
        return _catalog_cache["entries"]

    with CATALOG_PATH.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    entries = [_ergaenze(kopie)
               for item in raw.get("entries", [])
               for kopie in _entfalte(item)]

    _catalog_cache["mtime"] = stand
    _catalog_cache["entries"] = entries
    return entries


def find_entry(slug: str) -> dict | None:
    return next((e for e in load_catalog() if e["slug"] == slug), None)


def required_assets(entry: dict) -> list[str]:
    """Welche Dateien muss sync-images.sh fuer diesen Eintrag geholt haben?"""
    if entry.get("assets"):
        return list(entry["assets"])
    paths = []
    for key in ("kernel", "initrd"):
        value = entry.get(key)
        if isinstance(value, str):
            paths.append(value)
        elif isinstance(value, list):
            paths.extend(value)
    # Windows: statt Kernel und Initrd stehen hier benannte Dateien, je ein
    # Satz fuer BIOS und fuer UEFI -- und dazu wimboot selbst, ohne das
    # nichts davon startet. Gefragt wird mit .get, weil die Uebersicht auch
    # Eintraege hereinreicht, die noch nicht durch _ergaenze() gelaufen sind.
    if entry.get("type") == "wimboot":
        paths.append(entry.get("wimboot_loader", "wimboot/wimboot"))
        for satz in entry.get("wimboot", {}).values():
            paths.extend(satz.values())
    return list(dict.fromkeys(paths))


def entry_ready(entry: dict) -> bool:
    """True, wenn alle noetigen Dateien wirklich auf der Platte liegen.

    Eintraege vom Typ "chain" (z.B. netboot.xyz) und die eingebauten
    Menuepunkte brauchen normalerweise keine lokalen Dateien. Nennt ein
    solcher Eintrag trotzdem ein "assets:"-Feld -- etwa memtest, das per
    chain aus dem eigenen Assets-Verzeichnis geladen wird -- pruefen wir es.
    """
    # Ein Eintrag, der nur ueber NFS starten kann, ist ohne Export nicht
    # startbereit -- auch wenn alle Dateien daliegen. Ihn trotzdem ins
    # Menue zu stellen hiesse, den Fehlschlag vor die Maschine zu tragen.
    if entry.get("braucht_nfs"):
        return False
    assets = required_assets(entry)
    if entry["type"] in ("chain", "local", "shell", "reboot"):
        return all((ASSETS_DIR / p).exists() for p in assets)
    if not assets:
        return False
    return all((ASSETS_DIR / p).exists() for p in assets)


# --------------------------------------------------------------------------
# Datenbank (Clients und deren Vorauswahl)
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    mac        TEXT PRIMARY KEY,
    name       TEXT NOT NULL DEFAULT '',
    entry      TEXT,                        -- gewaehltes System, bleibt stehen
    pxe_aktiv  INTEGER NOT NULL DEFAULT 0,  -- 1 = beim naechsten Start durchbooten
    last_seen  TEXT,
    last_ip    TEXT,
    last_arch  TEXT,
    product    TEXT NOT NULL DEFAULT '',
    last_wake  TEXT                         -- zuletzt per Wake-on-LAN geweckt
);
CREATE TABLE IF NOT EXISTS boot_log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,
    mac    TEXT NOT NULL,
    entry  TEXT NOT NULL,
    ip     TEXT
);
"""


# Spalten, die erst spaeter dazugekommen sind. "CREATE TABLE IF NOT EXISTS"
# ruehrt eine schon vorhandene Tabelle nicht mehr an -- eine Datenbank aus
# einer aelteren Version braucht die neuen Spalten deshalb per ALTER TABLE.
NACHZUEGLER = {
    "clients": {"last_wake": "TEXT", "pxe_aktiv": "INTEGER NOT NULL DEFAULT 0"},
}


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.on_event("startup")
def wacht_starten() -> None:
    """Den Waechter ueber den Download-Adressen anwerfen.

    Er sieht alle sieben Tage nach, welche Adresse tot ist und wo es
    etwas Neueres gibt; der Befund steht danach auf Server Health.
    Abschaltbar ueber PXE_QUELLENWACHT in /etc/pxeweb.env.
    """
    quellenwacht.wacht_starten()
    # Und der Blick ins Repository -- ob und wie oft, entscheidet der
    # Betreiber unter Einrichtung; die Wache selbst laeuft immer und fragt
    # stuendlich, ob sie darf. Sonst muesste man den Dienst neu starten,
    # nur weil man von "nie" auf "woechentlich" gedreht hat.
    updatewacht.wacht_starten()


def _katalog_roh() -> list[dict]:
    """Die Eintraege aus catalog.yaml, ungefaltet -- mit "versionen_aus".

    Der gefaltete Katalog (load_catalog) taugt hier nicht: Aus einer leeren
    Ausgabenliste entsteht kein einziger Eintrag, und genau dann wird
    dieser Weg gebraucht -- bei der Uebernahme und beim Einordnen der
    Quellen-Karten. Beide fragen nach Eigenschaften des Systems, nicht
    nach denen einer Ausgabe.
    """
    try:
        with CATALOG_PATH.open(encoding="utf-8") as fh:
            return (yaml.safe_load(fh) or {}).get("entries", [])
    except OSError:
        return []


# Wozu eine Quelle gehoert, laesst sich meist ausrechnen: Ihre
# Ausgabenliste steht als "versionen_aus" an genau einem Katalogeintrag.
# Drei Quellen haben keine Liste -- Mint liegt versionslos beim Anbieter,
# Tumbleweed rollt, ShredOS traegt Ausgabe und Datum an zwei Stellen
# seiner Adresse. Fuer die steht es hier.
QUELLE_EINTRAG = {
    "MINT_MIRROR": "mint-cinnamon",
    "TUMBLEWEED_URL": "opensuse-tumbleweed",
    "SHREDOS_ISO_URL": "shredos",
}


def _quelle_eintrag(name: str, roh: list[dict] | None = None) -> dict | None:
    """Der Katalogeintrag, den diese Quelle beliefert.

    "roh" spart das erneute Lesen der Datei, wenn gleich mehrere Quellen
    nachgeschlagen werden -- beim Aufbau der Seite sind es dreizehn.
    """
    roh = _katalog_roh() if roh is None else roh
    liste = quellen.VERSIONSLISTE.get(name)
    if liste:
        return next((e for e in roh if e.get("versionen_aus") == liste), None)
    kennung = QUELLE_EINTRAG.get(name)
    return next((e for e in roh if e.get("slug") == kennung), None) if kennung else None


# Die Zwischenzeilen unter "Adressen". Zwei statt der drei Gruppen des
# Bootmenues: Ob eine Installation online oder offline laeuft, entscheidet
# sich am bootenden Rechner -- hier geht es darum, woher die Dateien
# kommen, und da stehen Distributionen und Werkzeuge nebeneinander.
QUELLEN_GRUPPEN = ("Installationen", "Rettung und Wartung", "Sonstiges")


def _quelle_titel(name: str, roh: list[dict] | None = None) -> str:
    """Wie diese Quelle heisst, wenn man sie nicht als Variable liest."""
    eintrag = _quelle_eintrag(name, roh)
    return (eintrag or {}).get("name", "") or name


def _quelleninfo_beschriftet(stand: dict) -> dict:
    """Den Befund des Waechters um die lesbaren Namen ergaenzen.

    Der Waechter kennt nur Variablennamen -- er arbeitet auf
    sync-images.sh. Auf Server Health steht der Befund aber neben Karten,
    die von Betriebssystemen sprechen, und die Zeile "ROCKY_BASE" gehoert
    dort erst uebersetzt hin. Die Variable bleibt sichtbar: Sie ist der
    Name, unter dem die Quelle unter /quellen zu finden ist.

    Angefasst wird nur die Anzeige. /quelleninfo.json liefert weiter den
    rohen Stand -- das ist die Auskunft fuer ein Skript, und die soll sich
    nicht aendern, weil eine Seite huebscher wird.
    """
    roh = _katalog_roh()

    def mit_titel(eintraege):
        # "ziel" ist der Weg von der Meldung zu der Stelle, an der sich
        # etwas tun laesst. Bei einer Katalogquelle ist das ihre Karte;
        # bei einem selbst angelegten Eintrag er selbst -- eine Quelle
        # unter seinem Namen gibt es dort nicht, der Verweis ginge ins
        # Leere.
        return [{**e, "titel": _quelle_titel(e.get("name", ""), roh),
                 "ziel": ("eintrag-" + e["eigen"]) if e.get("eigen")
                         else e.get("name", "")}
                for e in eintraege]

    return {
        **stand,
        "tot": mit_titel(stand.get("tot") or []),
        "neu": mit_titel(stand.get("neu") or []),
        # Hier stehen bisher nackte Namen, keine Datensaetze -- fuer die
        # Anzeige werden beide gebraucht.
        "ohne_netz": [{"name": n, "titel": _quelle_titel(n, roh)}
                      for n in (stand.get("ohne_netz") or [])],
    }


def _quellen_nach_gruppen(karten: list[dict]) -> list[dict]:
    """Die Quellen-Karten in dieselbe Ordnung bringen wie der Katalog darueber.

    Eine Gruppe ohne Karten faellt weg -- eine Zwischenzeile, unter der
    nichts steht, ist eine Behauptung ueber etwas, das es nicht gibt.
    "Sonstiges" faengt eine Quelle auf, die zu keinem Eintrag gehoert: Wer
    eine neue in sync-images.sh eintraegt und den Katalog noch nicht
    angefasst hat, soll sie sehen und nicht suchen.
    """
    roh = _katalog_roh()
    eimer: dict[str, list[dict]] = {g: [] for g in QUELLEN_GRUPPEN}
    for karte in karten:
        eintrag = _quelle_eintrag(karte["name"], roh)
        gruppe = (eintrag or {}).get("category", "")
        if gruppe != "Rettung und Wartung":
            gruppe = "Installationen" if eintrag else "Sonstiges"
        # Der Name des Systems statt des Namens der Shell-Variablen.
        # "UBUNTU_ISO_URL" beantwortet die Frage "wo steht das in
        # sync-images.sh", und die stellt hier niemand -- gesucht wird
        # Ubuntu. Die Variable bleibt trotzdem sichtbar: Sie ist der
        # Schluessel in quellen.env und der Name, unter dem der Waechter
        # meldet. Faellt sie weg, ist eine Meldung von Server Health hier
        # nicht mehr wiederzufinden.
        eimer[gruppe].append({**karte, "titel": (eintrag or {}).get("name", "")
                              or karte["name"]})
    # Innerhalb der Gruppe nach dem Namen, den man liest. Alphabetisch nach
    # der Variablen stuende "Debian Live" vor "Debian", weil
    # DEBIAN_LIVE_ISO_URL vor DEBIAN_URL kommt -- eine Ordnung, die nur
    # dem einleuchtet, der die Variablennamen kennt.
    return [{"name": g, "karten": sorted(eimer[g], key=lambda k: k["titel"].lower())}
            for g in QUELLEN_GRUPPEN if eimer[g]]


def _ausgaben_auf_platte() -> dict[str, list[str]]:
    """Welche der frueheren Vorgabe-Ausgaben liegen wirklich auf der Platte?

    Gefragt wird der Katalog und nicht die Ausgabenliste: Die ist zu
    diesem Zeitpunkt ja gerade leer geworden, sonst braeuchte es die
    Uebernahme nicht. Gebaut wird jeder Kandidat deshalb von Hand aus dem
    ungefalteten Eintrag -- derselbe Weg, den _entfalte() sonst geht.
    """
    gefunden: dict[str, list[str]] = {}
    for item in _katalog_roh():
        listenname = item.get("versionen_aus")
        if not listenname:
            continue
        for version in quellen.FRUEHERE_VORGABEN.get(listenname, "").split():
            eintrag = _ergaenze(_mit_version(dict(item), version))
            dateien = required_assets(eintrag)
            if dateien and all((ASSETS_DIR / pfad).exists() for pfad in dateien):
                gefunden.setdefault(listenname, []).append(version)
    return gefunden


@app.on_event("startup")
def ausgaben_uebernehmen() -> None:
    """Einmalig festhalten, welche Ausgaben schon in Betrieb sind.

    Muss vor der Freigabe-Uebernahme in init_db() laufen: Die liest den
    Katalog, und der entsteht aus den Ausgabenlisten. Waeren die noch
    leer, schriebe sie einen Stand fest, in dem die Haelfte fehlt.
    """
    if quellen.uebernommen():
        return
    geschrieben = quellen.uebernimm_ausgaben(_ausgaben_auf_platte())
    if geschrieben:
        print("Ausgaben uebernommen:", ", ".join(sorted(geschrieben)),
              "-- was geholt war, bleibt in Betrieb.")


def db_anlegen() -> None:
    """Die Tabellen anlegen, falls es sie nicht gibt -- sonst nichts.

    Getrennt von init_db(), weil dort auch Migrationen stehen: Die gelten
    einem Server, der schon lief. Nach einem Werksreset waere die
    Freigabe-Uebernahme sogar schaedlich -- sie schriebe freigabe.yaml
    gleich wieder hin, und der Server stuende nicht da wie frisch
    aufgesetzt.
    """
    with db() as conn:
        conn.executescript(SCHEMA)


@app.on_event("startup")
def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        for tabelle, spalten in NACHZUEGLER.items():
            vorhanden = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabelle})")}
            for name, typ in spalten.items():
                if name not in vorhanden:
                    conn.execute(f"ALTER TABLE {tabelle} ADD COLUMN {name} {typ}")

        # Aus "once" ist "pxe_aktiv" geworden -- aus einem Zusatz zur Auswahl
        # ein eigener Schalter. Wer bisher eine Vorauswahl stehen hatte, waere
        # beim naechsten Start durchgebootet; das bleibt so.
        spalten = {r["name"] for r in conn.execute("PRAGMA table_info(clients)")}
        if "once" in spalten:
            conn.execute("UPDATE clients SET pxe_aktiv = 1 WHERE entry IS NOT NULL")
            try:
                conn.execute("ALTER TABLE clients DROP COLUMN once")
            except sqlite3.OperationalError:
                pass                     # aeltere SQLite kann das nicht -- egal

    # Die Freigabe hat ihre Vorgabe umgedreht: Ein Eintrag, dessen Dateien
    # fertig werden, wird nicht mehr von selbst angeboten. Auf einem
    # laufenden Server waere danach das Bootmenue leer -- deshalb einmalig
    # hinschreiben, was heute wirklich angeboten wird. Auf einem frisch
    # aufgesetzten Server ist nichts geholt, die Liste bleibt leer, und die
    # neue Vorgabe gilt von Anfang an.
    if freigabe.uebernimm_stand([e["slug"] for e in _systeme() if e["ready"]]):
        print("Freigabe uebernommen: was jetzt angeboten wird, steht jetzt "
              "ausdruecklich in", freigabe.DATEI)


MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")

# Wie lang ein Clientname sein darf. Dreissig Zeichen sind keine
# technische Grenze -- der Hostname eines Windows-Rechners waere bei
# fuenfzehn zu Ende, ein DNS-Label bei dreiundsechzig, und die Datenbank
# nimmt beliebig viel. Es ist eine Aussage: **Das Feld ist ein Etikett zum
# Wiedererkennen, keine Beschreibung.** Markus am 03.09.2026: Wer
# "Empfang, 2. OG, Gebaeude C" eintragen will, betreibt Inventar, und
# genau dort verlaeuft die Grenze dieses Moduls. Die Zahl kommt aus der
# Breite des Feldes: So viel zeigt es, ohne dass etwas aus dem Blick
# rutscht.
MAX_CLIENTNAME = 30


def normalise_mac(value: str | None) -> str | None:
    """iPXE liefert 'aa-bb-cc-dd-ee-ff', wir speichern 'aa:bb:cc:dd:ee:ff'."""
    if not value:
        return None
    mac = value.strip().lower().replace("-", ":")
    return mac if MAC_RE.match(mac) else None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def touch_client(mac, ip, arch, product) -> sqlite3.Row:
    """Client-Datensatz anlegen oder auffrischen und zurueckgeben."""
    with db() as conn:
        conn.execute(
            """
            INSERT INTO clients (mac, last_seen, last_ip, last_arch, product)
                 VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(mac) DO UPDATE SET
                 last_seen = excluded.last_seen,
                 last_ip   = excluded.last_ip,
                 last_arch = excluded.last_arch,
                 product   = CASE WHEN excluded.product != ''
                                  THEN excluded.product ELSE clients.product END
            """,
            (mac, now(), ip, arch, product or ""),
        )
        return conn.execute("SELECT * FROM clients WHERE mac = ?", (mac,)).fetchone()


# --------------------------------------------------------------------------
# iPXE-Endpunkte (werden vom bootenden Rechner aufgerufen)
# --------------------------------------------------------------------------


def _nach_gruppen(eintraege: list[dict]) -> dict[str, list[dict]]:
    """Eintraege in ihre Gruppen legen, in der geltenden Reihenfolge.

    Leere Gruppen fallen weg -- eine Ueberschrift ohne Zeilen darunter
    behauptet, es gaebe dort etwas. Gruppen, die der Katalog mitbringt und
    GRUPPEN nicht kennt, stehen dahinter, in der Reihenfolge ihres
    Auftretens.
    """
    toepfe: dict[str, list[dict]] = {}
    for eintrag in eintraege:
        toepfe.setdefault(eintrag.get("category") or "Sonstiges", []).append(eintrag)
    bekannt = list(GRUPPEN)
    folge = gruppen.sortiere(
        bekannt + [name for name in toepfe if name not in bekannt])
    return {name: toepfe[name] for name in folge if toepfe.get(name)}


def menue_gruppen(platform: str) -> dict[str, list[dict]]:
    """Die Menuepunkte fuer diese Firmware, nach Gruppen und in fester Folge.

    Nur Eintraege, die zur Plattform passen, deren Dateien wirklich da sind
    und die fuers Menue freigegeben sind. Ein Menuepunkt, der beim
    Anklicken scheitert, ist schlimmer als keiner -- und ein ungeprueftes
    System im Menue erwischt frueher oder spaeter jemand, der es nicht
    erproben wollte (siehe freigabe.py). Dieselbe Funktion beliefert das echte Menue und die Vorschau in
    der Weboberflaeche; sonst liefen die beiden frueher oder spaeter
    auseinander.
    """
    return _nach_gruppen([entry for entry in load_catalog()
                          if entry.get("im_menue", True)
                          and platform in entry["platforms"]
                          and entry_ready(entry)])


def client_adresse(request: Request) -> str | None:
    """Die Adresse des bootenden Rechners -- nicht die des Reverse Proxys.

    Die Anwendung lauscht nur auf 127.0.0.1, alles kommt ueber nginx.
    request.client waere deshalb immer die Rueckschleife, und damit stuende
    bei jedem Rechner dieselbe "letzte IP". nginx traegt die echte Adresse
    seit jeher in X-Real-IP ein (siehe nginx-pxe.conf), gelesen wurde sie
    nur nie.

    Den Kopfzeilen zu trauen ist hier unbedenklich: an die Anwendung kommt
    ausser nginx niemand heran, sie ist an die Rueckschleife gebunden.
    """
    kopf = (request.headers.get("x-real-ip")
            or request.headers.get("x-forwarded-for", ""))
    erste = kopf.split(",")[0].strip()
    if erste:
        return erste
    return request.client.host if request.client else None


def ipxe_response(template: str, **ctx) -> PlainTextResponse:
    body = ipxe.get_template(template).render(base=BASE_URL, srvip=SERVER_HOST, **ctx)
    return PlainTextResponse(body, media_type="text/plain; charset=utf-8")


@app.get("/boot.ipxe")
def boot_bootstrap() -> PlainTextResponse:
    """Erster Kontakt: hierhin schickt dnsmasq jedes gestartete iPXE.

    Dieses Skript tut nichts weiter, als die Eigenschaften des Rechners
    einzusammeln und sie an /menu.ipxe weiterzureichen. Die Auswertung
    passiert dann serverseitig in Python.
    """
    return ipxe_response("boot.ipxe.j2")


@app.get("/menu.ipxe")
def boot_menu(request: Request) -> PlainTextResponse:
    q = request.query_params
    mac = normalise_mac(q.get("mac"))
    platform = q.get("platform", "pcbios")
    arch = q.get("arch", "x86_64")
    client_ip = client_adresse(request)

    client = None
    if mac:
        client = touch_client(mac, client_ip, platform + "/" + arch, q.get("product"))

    # Ohne Freigabe passiert nichts weiter. Der Rechner ist damit trotzdem
    # erfasst -- das ist eine Zeile weiter oben schon geschehen, und genau
    # dafuer taugt der Netzwerkstart auch ohne Freigabe. Er faellt hier in
    # seine normale Bootreihenfolge zurueck, also auf die Platte.
    #
    # Das ist der Normalfall und die Voreinstellung: Wer sich zum ersten Mal
    # meldet, bekommt weder Menue noch Installation, sondern landet in der
    # Rechnerliste. Erst ein Haken dort macht aus dem Netzwerkstart mehr als
    # eine Anmeldung.
    if client is None or not client["pxe_aktiv"]:
        return ipxe_response("gesperrt.ipxe.j2", mac=mac or "Dieser Rechner")

    # Freigegeben und ein System ausgewaehlt: ohne Menue direkt durchstarten.
    # Wer am Rechner sitzt, kann das mit Strg-C abbrechen -- dann kommt er
    # mit "nopreset" hierher zurueck und soll das Menue sehen statt noch
    # einmal dieselbe Vorauswahl.
    if client["entry"] and not q.get("nopreset"):
        target = find_entry(client["entry"])
        if target and platform in target["platforms"] and entry_ready(target):
            return ipxe_response(
                "direct.ipxe.j2", entry=target, mac=mac, name=client["name"] or mac
            )

    # Bleibt das Menue. Damit ist die Freigabe eingeloest, und der Haken geht
    # hier weg -- anders als beim Durchstarten, wo er erst faellt, wenn das
    # Boot-Skript wirklich abgeholt wurde. Der Unterschied ist Strg-C: beim
    # Durchstarten kann noch abgebrochen werden, das Menue dagegen *ist*
    # schon das Ausgelieferte. Ohne das hier bliebe ein Rechner, an dem
    # niemand sitzt, nach dem Zeitablauf freigeschaltet und bekaeme das
    # Menue bei jedem weiteren Start wieder.
    with db() as conn:
        conn.execute("UPDATE clients SET pxe_aktiv = 0 WHERE mac = ?", (mac,))

    categories = menue_gruppen(platform)

    return ipxe_response(
        "menu.ipxe.j2",
        categories=categories,
        mac=mac or "unbekannt",
        titel=bezeichnungen.menue_titel(mac or "unbekannt", platform),
        timeout_ms=MENU_TIMEOUT * 1000,
        default=MENU_DEFAULT,
        platform=platform,
    )


@app.get("/boot/{slug}.ipxe")
def boot_entry(slug: str, request: Request) -> PlainTextResponse:
    """Startet einen konkreten Eintrag -- Kernel und Initrd laden, los."""
    entry = find_entry(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unbekannter Eintrag: " + slug)

    mac = normalise_mac(request.query_params.get("mac"))
    client_ip = client_adresse(request)

    if mac:
        with db() as conn:
            conn.execute(
                "INSERT INTO boot_log (ts, mac, entry, ip) VALUES (?, ?, ?, ?)",
                (now(), mac, slug, client_ip),
            )
            # Zurueck auf Anfang: Haken weg und Auswahl weg. Der Rechner
            # steht damit wieder so da wie jeder andere -- er meldet sich
            # beim naechsten Netzwerkstart an und bootet von seiner Platte.
            #
            # Verhindert Endlosschleifen: Ein Rechner bootet nach der
            # Installation oft noch einmal vom Netz, und ohne das wuerde er
            # sich sofort wieder neu aufsetzen. Dagegen genuegte der Haken
            # allein; die Auswahl blieb frueher absichtlich stehen, damit
            # ein zweiter Anlauf ein Klick ist. Das war aber irrefuehrend:
            # In der Liste stand dann weiter "Ubuntu Server installieren"
            # bei einer Maschine, auf der Ubuntu laengst laeuft. Eine
            # erledigte Aufgabe soll nicht aussehen wie eine anstehende.
            conn.execute(
                "UPDATE clients SET pxe_aktiv = 0, entry = NULL WHERE mac = ?",
                (mac,))

    template = {
        "kernel": "kernel.ipxe.j2",
        "chain": "chain.ipxe.j2",
        "sanboot": "sanboot.ipxe.j2",
        "wimboot": "wimboot.ipxe.j2",
        "local": "local.ipxe.j2",
        "shell": "shell.ipxe.j2",
        "reboot": "reboot.ipxe.j2",
    }.get(entry["type"])

    if template is None:
        raise HTTPException(status_code=500, detail="Unbekannter Typ: " + entry["type"])

    return ipxe_response(template, entry=entry, mac=mac or "")


# --------------------------------------------------------------------------
# Weboberflaeche
# --------------------------------------------------------------------------


def datei_version(name: str) -> int:
    """Aenderungszeit einer Datei unter static/, als Anhang an ihre Adresse.

    Ohne das holt der Browser die zwischengespeicherte Fassung und man
    wundert sich, warum eine Aenderung nicht ankommt -- oder man erklaert
    jedem, er solle Strg+F5 druecken. Aendert sich die Datei, aendert sich
    die Adresse, und der Browser hat keine Wahl.
    """
    try:
        return int((BASE_DIR / "static" / name).stat().st_mtime)
    except OSError:
        return 0


def stil_version() -> int:
    """Aenderungszeit des Stylesheets. Siehe datei_version()."""
    return datei_version("style.css")


def marken_version() -> int:
    """Aenderungszeit der juengsten Logodatei.

    Die beiden Wortmarken, das Zeichen und das Favicon entstehen aus
    derselben Quelle und aendern sich zusammen. Eine gemeinsame Zahl reicht
    deshalb -- und erspart vier fast gleiche Werte in jeder Seite.
    """
    return max(datei_version(n) for n in
               ("exmig-logo.svg", "exmig-logo-band.svg", "exmig-zeichen.svg",
                "favicon.ico"))


# Wohin eine Seite nach einem Klick springen darf.
#
# Ohne Sprungmarke landet man nach der Weiterleitung ganz oben und muss
# sich zu der Karte zurueckscrollen, an der man gerade war -- bei den
# langen Seiten unter Quellen und Clients jedes Mal. Markus am 28.08.2026:
# "Das habe ich schon an mehreren Stellen gefunden."
#
# Zwei Stellen machten es schon richtig (der Quellenwaechter und die
# Werkseinstellung); der Rest zog nach.
#
# Geprueft wird gegen diese Liste, weil ein Teil der Marken aus dem
# Formular kommt: Dieselbe Eintragskarte steht in allen vier Karten unter
# Quellen, also muss sie sagen, aus welcher sie kommt. Was von aussen
# kommt, gehoert nicht ungeprueft in eine Adresse.
# Wohin ein Knopf zurueckfuehren darf, der auf JEDER Seite steht. Dieselbe
# Ueberlegung wie bei den Sprungmarken: Was von aussen kommt, gehoert nicht
# ungeprueft in eine Adresse -- sonst ist der Knopf eine Weiterleitung
# irgendwohin. Es sind genau die Reiter aus base.html.
SEITEN = ("/", "/clients", "/systeme", "/quellen", "/einrichtung",
          "/history", "/hilfe")

# Wohin install.sh die Skripte spiegelt -- und damit der Befehl, der einen
# Server aktualisiert. Bewusst ohne sudo: update.sh besteht darauf, dass
# "git pull" dem Benutzer gehoert, und fragt fuer install.sh selbst nach
# dem Passwort. Und bewusst ohne Pfadangabe zum Klon: Das Skript findet
# ihn ueber die Datei "projektpfad", die install.sh bei jedem Lauf
# danebenlegt.
#
# Bewusst als Zeichenkette und nicht als Path: Der Pfad gilt auf dem
# Server, und der laeuft Linux. Auf einem Windows-Arbeitsplatz machte
# pathlib daraus "\opt\pxe-setup" -- ein Befehl, den niemand tippen kann.
# Wohin ein Fehlerbericht geht. Der Server verschickt ihn nicht -- er
# nennt die Adresse, und der Betreiber traegt den Text weiter.
KONTAKT = os.environ.get("PXE_KONTAKT", "kontakt@exmig.de")

SETUP_DIR = os.environ.get("PXE_SETUP_DIR", "/opt/pxe-setup").rstrip("/")


def _update_befehl() -> str:
    """Der Befehl, mit dem dieser Server aktualisiert wird.

    **Genannt wird der Klon, nicht die Kopie.** Beide Wege gehen -- das
    gespiegelte /opt/pxe-setup/update.sh reicht an den Klon weiter --, aber
    im Klon liegt das Repository, dort gehoert "git pull" hin, und von dort
    ruft man es auch von Hand auf.

    Geraten wird der Pfad nicht: install.sh legt ihn bei jedem Lauf in
    "projektpfad" ab, genau dafuer. Fehlt die Datei, nennen wir den
    gespiegelten Weg -- der findet sich notfalls selbst. Lieber ein Befehl,
    der einen Umweg geht, als einer mit einem erfundenen Pfad.

    Einmal beim Start gelesen: Die Datei entsteht in install.sh, und das
    startet den Dienst hinterher ohnehin neu.
    """
    try:
        zeilen = (Path(SETUP_DIR) / "projektpfad").read_text(
            encoding="utf-8").splitlines()
        klon = zeilen[0].strip().rstrip("/")
    except (OSError, IndexError):
        klon = ""
    return f"{klon}/setup/update.sh" if klon else f"{SETUP_DIR}/update.sh"


UPDATE_BEFEHL = _update_befehl()

SPRUNGMARKEN = {
    "upload", "katalog", "download", "custom",          # Quellen
    "registrierte-clients", "manuelle-registrierung",   # Clients
    "installationsprotokolle",
    "stand", "ablageorte", "einstellungen", "ersteinrichtung",  # Einrichtung
    "fehlerbericht", "verbesserungen", "firewall",
    "quellenwaechter",                                  # Server Health
}


def sprung(ziel: str, marke: str) -> str:
    """Adresse mit Sprungmarke -- oder ohne, wenn die Marke nicht bekannt ist."""
    marke = (marke or "").lstrip("#")
    return f"{ziel}#{marke}" if marke in SPRUNGMARKEN else ziel


def antwort(seite: str, text: str, *, schlecht: bool = False,
            marke: str = "") -> str:
    """Die Adresse, auf die ein Formular zurueckfuehrt -- mit seiner Antwort.

    **Ein Weg, zwei Auspraegungen.** Jedes Formular der Oberflaeche
    antwortet ueber "?meldung=" (siehe _clients_meldung). Seit A-021 sagt
    ein zweiter Parameter dazu, *wie* es ausgegangen ist: ohne ihn ist es
    eine Zusage, mit "art=schlecht" eine Zurueckweisung -- und die steht
    dann in der Warnfarbe.

    Keine zweite Bauart: Es bleibt dieselbe Adresse, dieselbe Vorlage,
    dasselbe Feld. Wer eine Antwort braucht, nimmt diese Funktion.

    Die Meldung ueberlebt das Neuladen nicht -- dafuer sorgt das Skript in
    base.html, das die beiden Parameter nach dem Anzeigen aus der Adresse
    nimmt. Gerade eine rote Meldung, die nach F5 wiederkommt, waere
    schlechter als gar keine Auspraegung.
    """
    ziel = seite + "?meldung=" + quote(text)
    if schlecht:
        ziel += "&art=schlecht"
    return sprung(ziel, marke) if marke else ziel


def _rahmen(**ctx) -> dict:
    """Werte, die jede Seite braucht -- Kopfzeile, Navigation, Fusszeile."""
    grund = {
        "stil_version": stil_version(),
        "marken_version": marken_version(),
        "base_url": BASE_URL,
        # Fuer die Fusszeile. Leer, wenn die Anwendung nicht ueber
        # install.sh hierhergekommen ist -- dann steht dort nichts statt
        # einer erfundenen Nummer, siehe versionsstand.py.
        "stand_kurz": versionsstand.kurz(),
        # Steht hier ein Wort, ist das nicht die Produktion: Der Seitengrund
        # wechselt auf Sand, und das Wort steht als Marke in der Kopfzeile.
        # Siehe docs/gestaltung.md, "Ein Server, der nicht die Produktion ist".
        "kennzeichnung": KENNZEICHNUNG,
        # Der eine Befehl, der einen Server auf den neuesten Stand bringt.
        # Er steht in zwei Befundkarten und unter Einrichtung -- an drei
        # Stellen derselbe Satz waere frueher oder spaeter dreimal ein
        # anderer.
        "update_befehl": UPDATE_BEFEHL,
        # Der Katalog der Befunde. Die Hilfe rendert daraus die Tabelle
        # "Welche Karte wann kommt" -- aus derselben Quelle, aus der die
        # Karten entstehen. Von Hand geschrieben waere sie ein zweiter Ort
        # fuer dieselbe Angabe, und der veraltet.
        "katalog": befunde.KATALOG,
        "menu_default": MENU_DEFAULT,
        "menu_timeout": MENU_TIMEOUT,
        # Wieviel auf die Menuezeile passt. Die Felder tragen es als
        # maxlength, damit die Grenze beim Tippen auffaellt und nicht erst
        # beim Speichern -- und sie kommt aus derselben Quelle wie die
        # Pruefung, sonst laufen Feld und Regel auseinander.
        "max_zeile": bezeichnungen.MAX_ZEILE,
        "max_version": bezeichnungen.MAX_VERSION,
        "max_info": bezeichnungen.MAX_INFO,
        "menue_breite": bezeichnungen.MENUE_BREITE,
        "meldung": "",
        # Wie die Meldung ausgegangen ist: "" ist die Zusage, "schlecht"
        # die Zurueckweisung. Gesetzt wird sie von antwort(); hier steht
        # nur die Vorgabe, damit eine Seite ohne Meldung nichts erklaeren
        # muss.
        "meldungsart": "",
        # Was dem Server als Ganzem fehlt -- nicht einer Karte und nicht
        # einer Seite. Steht deshalb hier und nicht in den Handlern:
        # Sonst haengt ein Befund davon ab, welchen Reiter jemand gerade
        # geoeffnet hat. Siehe webui/befunde.py.
        #
        # Zwei Listen, nicht eine: Was jemand zur Kenntnis genommen hat,
        # verschwindet nicht, es wird leise -- eine graue Zeile statt einer
        # Karte. Siehe webui/kenntnis.py.
        **_befundlisten(),
    }
    grund.update(ctx)
    return grund


def _befundlisten() -> dict:
    """Die geltenden Befunde, getrennt in offene und zur Kenntnis genommene."""
    offen, bekannt = kenntnis.teilen(befunde.sammeln(SERVER_HOST, ASSETS_DIR))
    return {"befunde": offen, "bekannte": bekannt}


def _zustand(eintrag: dict) -> dict:
    """Was rechts am Eintrag steht: bereit, fehlt, oder was gerade laeuft.

    Steht hier und nicht in den Vorlagen, weil dieselbe Auskunft an zwei
    Stellen gebraucht wird: in der Liste unter Systeme und auf den Karten
    unter Quellen. Beide hatten ihre eigene Fassung, und die liefen
    auseinander -- Systeme zeigte gruen "bereit", Quellen nur rot "fehlt".
    Nebeneinander gelesen sah das aus, als sagten sie Verschiedenes.

    Die Reihenfolge ist die des Zweifels: Was gerade laeuft oder
    schiefging, geht vor; erst danach die Frage, ob die Dateien da sind.
    """
    eigen = eintrag.get("eigen") or {}
    upload = eintrag.get("upload") or {}
    if eigen and eigen.get("status") != "bereit":
        return {"text": "wird geholt" if eigen.get("status") == "laedt" else "Fehler",
                "gut": False, "laeuft": eigen.get("status") == "laedt",
                "meldung": eigen.get("meldung", "")}
    if upload and upload.get("status") != "bereit":
        return {"text": upload.get("zustand_text", ""), "gut": False,
                "laeuft": upload.get("status") in uploads.LAEUFT,
                "meldung": upload.get("meldung", "")}
    if eintrag.get("ready"):
        return {"text": "bereit", "gut": True, "laeuft": False, "meldung": ""}
    return {"text": "fehlt", "gut": False, "laeuft": False, "meldung": ""}


def _angefangen(eintrag: dict) -> bool:
    """Liegt von diesem Eintrag schon etwas auf der Platte?

    **Der Unterschied zwischen "noch nie geholt" und "war da und ist
    weg" -- ohne Buchfuehrung.** B-003 schlug dafuer einen Zustand je
    Eintrag vor, mitgefuehrt bei jedem Abgleich, Upload und Loeschen. Der
    ist nicht noetig: Die Ablage sagt es selbst.

    `sync-images.sh` legt das Verzeichnis an, *bevor* es laedt, und laesst
    bei einem Abbruch die `.part`-Datei darin liegen (siehe `get()` dort).
    Ein Eintrag, dem Dateien fehlen und von dem trotzdem etwas dasteht,
    ist also angefangen und nicht neu.

    Der Gegenfall traegt sich selbst: "Dateien loeschen" nimmt den Ordner
    samt leer gewordener Eltern mit (_raeume_ab), da bleibt nichts liegen
    -- und dort sagt die Meldung im Moment des Klicks, was weg ist.

    Nur auf /systeme gerechnet, nicht bei jedem Seitenaufbau: ein
    scandir je Eintrag, dem etwas fehlt.
    """
    ordner = eintragsordner(eintrag.get("slug", ""))
    if ordner is None or not ordner.is_dir():
        return False
    try:
        return any(ordner.iterdir())
    except OSError:
        return False


def _systeme() -> list[dict]:
    """Katalog und eigene Abbilder als eine Liste.

    Aus Sicht der Bedienung ist beides dasselbe -- was kann gebootet werden?
    Ein fertig verarbeiteter Upload steckt schon im Katalog (load_catalog),
    er wird hier nur um seine Herkunft ergaenzt. Was noch laedt, entpackt
    oder fehlgeschlagen ist, hat noch keinen Katalogeintrag und kommt
    hinten dran -- sonst waere es unsichtbar, gerade wenn man hinsieht.
    """
    offen = {u["slug"]: u for u in uploads.alle()}
    selbst = {e["slug"]: e for e in eigene.alle()}
    liste = []
    for entry in load_catalog():
        item = dict(entry)
        item["ready"] = entry_ready(entry)
        item["missing"] = [
            path for path in required_assets(entry) if not (ASSETS_DIR / path).exists()
        ]
        item["upload"] = offen.pop(entry["slug"], None)
        item["eigen"] = selbst.pop(entry["slug"], None)
        item["zustand"] = _zustand(item)
        liste.append(item)

    for rest in offen.values():
        liste.append({
            "slug": rest.get("slug", ""),
            "name": rest.get("erkannt") or rest.get("datei", ""),
            "description": "",
            "category": "",
            "platforms": [],
            "ready": False,
            "missing": [],
            "upload": rest,
            "eigen": None,
        })
        liste[-1]["zustand"] = _zustand(liste[-1])

    # Selbst angelegte Eintraege, die noch laden oder gescheitert sind: die
    # haben noch keinen Katalogeintrag und waeren sonst unsichtbar.
    for rest in selbst.values():
        liste.append({
            "slug": rest.get("slug", ""),
            "name": rest.get("name", ""),
            "description": rest.get("beschreibung", ""),
            "category": uploads.gruppe_heute(rest.get("gruppe", "")),
            "platforms": [],
            "ready": False,
            "missing": [],
            "upload": None,
            "eigen": rest,
        })
        liste[-1]["zustand"] = _zustand(liste[-1])
    return liste


def _vorgaenge() -> dict:
    """Was der Server gerade selbst holt oder entgegennimmt.

    Zwei Richtungen, die beide Zeit und Bandbreite kosten und deshalb neben
    die Auslastung gehoeren:

      herein   ein Abbild kommt vom Arbeitsplatz (wird empfangen, danach
               ausgepackt)
      hinaus   der Server laedt selbst -- entweder ein einzelnes Abbild von
               einer Adresse, oder sync-images.sh holt die mitgelieferten
               Systeme

    Ohne diese Anzeige sieht man auf der Startseite nur, dass der
    Netzdurchsatz hoch ist, aber nicht warum.
    """
    offen = uploads.alle()
    herein = [u for u in offen if u.get("status") in ("empfangen", "entpacken")]
    hinaus = [u for u in offen if u.get("status") == "laedt"]

    lauf = sync.zustand()
    if lauf["laeuft"]:
        # Der Abgleich holt mehrere Komponenten hintereinander; fuer diese
        # Zeile zaehlt er als ein Vorgang.
        hinaus = hinaus + [{"erkannt": "Abgleich: " + ", ".join(lauf["komponenten"]),
                            "zustand_text": "wird geholt"}]

    def zeigen(liste):
        return [{"was": u.get("erkannt") or u.get("datei", "Abbild"),
                 "zustand": u.get("zustand_text", "")} for u in liste]

    return {"herein": zeigen(herein), "hinaus": zeigen(hinaus)}


def _laufend() -> list[dict]:
    """Rechner, die gerade Daten von uns ziehen.

    Ausgeliefert wird von nginx und vom NFS-Dienst, davon sieht die
    Anwendung nichts. Sichtbar sind aber die offenen Verbindungen des
    Systems: wer sein Wurzeldateisystem oder seine Pakete holt, haelt eine
    Verbindung auf Port 80 oder 2049 offen.

    Zugeordnet wird ueber die MAC aus dem ARP-Zwischenspeicher, nicht ueber
    die IP. Grund: iPXE fragt beim Start per DHCP nach einer Adresse, und
    das danach gestartete Live-System fragt noch einmal selbst -- der Router
    vergibt dabei nicht zwingend dieselbe. Die beim Booten gemerkte Adresse
    ist also womoeglich eine andere als die, unter der der Rechner spaeter
    seine Pakete zieht. Die MAC bleibt. Ueber die IP wird nur ersatzweise
    zugeordnet, falls der ARP-Zwischenspeicher nichts hergibt.

    Nur Rechner, die schon einmal etwas von uns gestartet haben, zaehlen --
    sonst erschiene der Browser des Verwalters als laufende Installation.
    """
    aktiv = auslastung.uebertragungen()
    if not aktiv:
        return []

    nach_ip = auslastung.arp()

    with db() as conn:
        zeilen = conn.execute(
            """
            SELECT c.mac, c.name, c.last_ip, c.product,
                   (SELECT entry FROM boot_log b WHERE b.mac = c.mac
                     ORDER BY b.id DESC LIMIT 1) AS entry,
                   (SELECT ts FROM boot_log b WHERE b.mac = c.mac
                     ORDER BY b.id DESC LIMIT 1) AS ts
              FROM clients c
            """
        ).fetchall()

    per_mac = {c["mac"]: c for c in zeilen}
    per_ip = {c["last_ip"]: c for c in zeilen if c["last_ip"]}

    gefunden: dict[str, dict] = {}
    for adresse, wege in sorted(aktiv.items()):
        client = per_mac.get(nach_ip.get(adresse, "")) or per_ip.get(adresse)
        if client is None or not client["entry"]:
            continue

        # Zieht ein Rechner ueber zwei Wege gleichzeitig, bleibt es eine Zeile.
        eintrag = gefunden.get(client["mac"])
        if eintrag is None:
            katalog = find_entry(client["entry"])
            eintrag = gefunden[client["mac"]] = {
                "mac": client["mac"],
                "name": client["name"] or client["product"] or client["mac"],
                "ip": adresse,
                "slug": client["entry"],
                "system": katalog["name"] if katalog else client["entry"],
                "gruppe": katalog.get("category", "") if katalog else "",
                "seit": client["ts"] or "",
                "wege": set(),
            }
        eintrag["wege"] |= wege

    for eintrag in gefunden.values():
        eintrag["wege"] = sorted(eintrag["wege"])
    return list(gefunden.values())


def _auslastung() -> dict:
    return {
        "cpu": auslastung.cpu(),
        "kerne": auslastung.kerne(),
        "last": auslastung.last(),
        "speicher": auslastung.speicher(),
        "netz": auslastung.netz(),
    }


@app.get("/status.json")
def status():
    """Was gerade laeuft -- die Uebersicht fragt das im Sekundentakt ab."""
    return JSONResponse({"laufend": _laufend(), "auslastung": _auslastung(),
                         "vorgaenge": _vorgaenge()})


@app.get("/befunde.html")
def befunde_fragment(request: Request, von: str = ""):
    """Nur die Befunde, fertig gerendert -- jede Seite tauscht sie aus.

    Eigener Endpunkt und nicht /status.html: Der beantwortet, was auf
    Server Health tickt (Auslastung, laufende Uebertragungen), und das
    braucht keine andere Seite. Ein Befund dagegen gilt dem Server und
    nicht dem Reiter -- deshalb holt ihn jede Seite, und deshalb ist er
    hier fuer sich.
    """
    return html.TemplateResponse(
        request, "_befunde.html",
        # "von" sagt, welche Seite gerade nachfragt -- geprueft wie
        # ueberall, was von aussen kommt. Ohne die Angabe stuende im
        # Formular "/befunde.html", und der Knopf fuehrte ins Leere.
        dict(_befundlisten(), hier=von if von in SEITEN else "/"))


@app.post("/befund/kenntnis")
def befund_kenntnis(kennung: str = Form(""), zurueck: str = Form("")):
    """Diesen Befund zur Kenntnis nehmen -- auf dem Stand, den er hat.

    Geprueft wird gegen die geltenden Befunde und nicht gegen das, was das
    Formular schickt: Sonst liesse sich mit einer erfundenen Marke ein
    Befund stumm schalten, den es noch gar nicht gibt.
    """
    for b in befunde.sammeln(SERVER_HOST, ASSETS_DIR):
        if b["kennung"] == kennung and b["stufe"] in kenntnis.WEGKLICKBAR:
            kenntnis.nehmen(kennung, b.get("marke", 0))
            break
    # Zurueck, wo der Knopf stand: Ein Befund steht auf jeder Seite, also
    # gibt es kein festes Ziel. Die Seite sagt es im Formular -- geprueft
    # gegen SEITEN, denn ungeprueft waere der Knopf eine Weiterleitung
    # irgendwohin.
    return RedirectResponse(zurueck if zurueck in SEITEN else "/",
                            status_code=303)


@app.get("/status.html")
def status_fragment(request: Request):
    """Derselbe Abschnitt als fertiges HTML -- die Uebersicht tauscht ihn aus.

    Fertig gerendert und nicht als Daten, damit es die Darstellung genau
    einmal gibt: in der Vorlage. Sonst muesste dieselbe Tabelle ein zweites
    Mal in JavaScript entstehen und beide liefen auseinander.
    """
    return html.TemplateResponse(
        request, "_status.html",
        {"laufend": _laufend(), "auslastung": _auslastung(),
         "vorgaenge": _vorgaenge(), "dienste": dienste.zustaende(),
         # Muss mit, weil die Zeile in _dienste.html steht und dieses
         # Stueck alle fuenf Sekunden nachgeholt wird. Fehlt sie hier,
         # verschwindet die Firewall-Zeile beim ersten Auffrischen --
         # derselbe Fall wie am 02.09.2026 bei den Ampeln.
         "firewall": firewall.lage()},
    )


@app.get("/")
def serverhealth(request: Request, meldung: str = "", art: str = ""):
    """Laeuft alles, und was tut der Server gerade?"""
    zustand = dienste.zustaende()
    # Die Zahlen des Stands standen frueher auf der Uebersicht. Dort waren
    # sie am falschen Platz: Wer wissen will, ob alles in Ordnung ist,
    # kommt hierher -- und "10 von 15 Eintraegen startbereit" gehoert zu
    # derselben Frage wie "laeuft dnsmasq".
    systeme = _systeme()
    with db() as conn:
        clients_anzahl = conn.execute("SELECT count(*) AS n FROM clients").fetchone()["n"]

    # Was zu keinem Eintrag gehoert. Gesucht wird bei jedem Aufbau dieser
    # Seite -- sie ist die, auf der man nachsieht, ob etwas nicht stimmt.
    # Die Funde gehen weiter an die Aufteilung: dort sind sie eine Zeile,
    # und ohne sie ginge die Rechnung nicht auf.
    funde = verwaiste(systeme)
    aufteilung = platzaufteilung(systeme, funde)
    # Erst nach platzaufteilung(): Dort wird gemessen, woraus sich die
    # Reserve bemisst.
    belegung = dienste.platz(ASSETS_DIR)

    return html.TemplateResponse(
        request,
        "serverhealth.html",
        _rahmen(
            aktiv="serverhealth",
            meldung=meldung,
            meldungsart=art,
            # Der Adressbefund stand hier bis zum 28.08.2026. Er kommt
            # jetzt aus _rahmen() und steht auf jeder Seite -- siehe
            # webui/befunde.py.
            dienste=zustand,
            firewall=firewall.lage(),
            laufend=_laufend(),
            auslastung=_auslastung(),
            vorgaenge=_vorgaenge(),
            bereit=sum(1 for e in systeme if e["ready"]),
            gesamt=len(systeme),
            # Was ein bootender Rechner wirklich angeboten bekommt. Die Liste
            # beantwortet die Frage, die man auf dieser Seite hat: was kann
            # dieser Server gerade?
            startbereit=[e for e in systeme if e["ready"]],
            clients_anzahl=clients_anzahl,
            aufteilung=aufteilung,
            verwaist=funde,
            # Was der Waechter beim letzten Durchgang ueber die
            # Download-Adressen herausgefunden hat.
            quelleninfo=_quelleninfo_beschriftet(quellenwacht.stand()),
            assets_dir=str(ASSETS_DIR),
            platz=belegung,
            # Der Balken haengt an derselben Regel wie die gelbe
            # Seitenkarte -- sonst faerbt er sich irgendwann bei einer
            # anderen Zahl, als die Karte nennt. Rot heisst deshalb nicht
            # mehr "90 Prozent", sondern "es reicht nicht mehr fuer ein
            # Abbild"; die Prozentstufe traegt nur noch das Gelb.
            platte_knapp=dienste.KNAPP,
            platte_warnt=dienste.platz_knapp(belegung),
            platte_reserve=dienste.reserve(),
        ),
    )


@app.get("/history")
def history_seite(request: Request, meldung: str = "", art: str = ""):
    """Was wann von welchem Rechner gestartet wurde."""
    with db() as conn:
        recent = conn.execute(
            "SELECT * FROM boot_log ORDER BY id DESC LIMIT 100").fetchall()
        clients = conn.execute("SELECT mac, name FROM clients").fetchall()
    return html.TemplateResponse(
        request,
        "history.html",
        _rahmen(
            aktiv="history",
            meldung=meldung,
            meldungsart=art,
            recent=recent,
            namen={c["mac"]: c["name"] for c in clients if c["name"]},
        ),
    )


@app.get("/rechner")
def rechner_alt(request: Request):
    """Die Seite hiess bis zur Umbenennung /rechner.

    Ein Lesezeichen darauf soll nicht ins Leere laufen -- und in Notizen und
    aelteren Dokumenten steht die alte Adresse noch.

    Der Abfrageteil wird mitgenommen. Bis zum 28.08.2026 zeigte diese
    Weiterleitung auf einen festen Pfad, und alles dahinter fiel ab. Das
    traf nicht nur Lesezeichen: Fuenf Wege unter Clients leiteten selbst
    noch auf die alte Adresse, und ihre Meldung ging genau hier verloren --
    das Wecken funktionierte und sagte es nie.
    """
    ziel = "/clients"
    if request.url.query:
        ziel += "?" + request.url.query
    return RedirectResponse(ziel, status_code=301)


@app.get("/clients.json")
def clients_stand():
    """Der Stand aller Rechner -- die Seite frischt sich damit selbst auf.

    Als Daten und nicht als fertiges HTML: die Seite traegt Formulare, in
    denen jemand gerade tippen koennte. Ausgetauscht werden darf deshalb
    immer nur das, was niemand bearbeitet -- welche Zeile das ist, weiss
    nur der Browser.

    Die Zeitangaben kommen fertig formatiert mit, damit es die Umrechnung
    in Ortszeit nur einmal gibt: hier.
    """
    return JSONResponse({"clients": _rechner_liste()})


def _rechner_liste() -> list[dict]:
    """Der Stand aller Rechner als einfache Liste.

    Zwei Aufrufer: das Auffrischen der Seite und die Antwort auf das
    Speichern -- danach soll die Seite denselben Stand einsetzen koennen,
    ohne dafuer neu zu laden.
    """
    with db() as conn:
        zeilen = conn.execute(
            "SELECT * FROM clients ORDER BY last_seen DESC").fetchall()
    return [{
        "mac": c["mac"],
        "name": c["name"],
        "entry": c["entry"] or "",
        "pxe_aktiv": bool(c["pxe_aktiv"]),
        "gesehen": lesbare_zeit(c["last_seen"]) if c["last_seen"] else "noch nie",
        "gesehen_roh": c["last_seen"] or "",
        # Getrennt, seit die Adressen eine eigene Spalte haben: Die IP
        # steht sichtbar unter der MAC, die Architektur als deren Titel.
        "herkunft": c["last_ip"] or "—",
        "arch": ("startet über " + c["last_arch"]) if c["last_arch"] else "",
        "geweckt": ("geweckt " + lesbare_zeit(c["last_wake"])) if c["last_wake"] else "",
        "geweckt_roh": c["last_wake"] or "",
    } for c in zeilen]


@app.get("/clients")
def clients_seite(request: Request, meldung: str = "", art: str = ""):
    """Bekannte Rechner: Vorauswahl, Wecken, ihre Installationsprotokolle."""
    with db() as conn:
        clients = conn.execute("SELECT * FROM clients ORDER BY last_seen DESC").fetchall()

    bekannt = {c["mac"] for c in clients}
    nach_mac: dict[str, list] = {}
    verwaiste = []
    for eintrag in logs.alle():
        if eintrag["mac"] in bekannt:
            nach_mac.setdefault(eintrag["mac"], []).append(eintrag)
        else:
            verwaiste.append(eintrag)

    return html.TemplateResponse(
        request,
        "clients.html",
        _rahmen(
            aktiv="clients",
            meldung=meldung,
            meldungsart=art,
            clients=clients,
            entries=_systeme(),
            protokolle=nach_mac,
            verwaiste=verwaiste,
            protokolle_belegt=logs.belegung(),
            # Die Grenze kommt aus derselben Quelle wie die Pruefung: Das
            # Feld traegt sie als maxlength, damit sie beim Tippen auffaellt
            # und nicht erst beim Speichern.
            max_clientname=MAX_CLIENTNAME,
        ),
    )


def _gruppiert(systeme: list[dict]) -> dict[str, list[dict]]:
    """Nach Gruppen sortiert -- dieselbe Folge, die auch das Menue benutzt."""
    return _nach_gruppen(systeme)


# Die vier Karten auf der Seite Quellen, eine je Herkunft. Die Folge hier
# ist die Vorgabe; umstellen laesst sie sich im Browser, sie liegt dann in
# derselben Datei wie die Reihenfolge der Gruppen (siehe gruppen.py).
# Name, Vorlage und die Sprungmarke ihrer Hilfe. Die dritte Angabe steht
# hier und nicht in der Vorlage: Jede Karte traegt ein Hilfezeichen in
# ihrer Kopfzeile, und die Kopfzeile baut quellen.html fuer alle vier.
# Der eine Befehl, der die abgelesene Adresse in die vier Stellen des
# Bootservers uebernimmt. Er braucht keine Argumente: install.sh liest die
# Adresse selbst von der Karte mit der Standardroute -- dieselbe Regel, nach
# der auch serveradresse.netzlage() sucht.
UEBERNAHME_BEFEHL = "sudo /opt/pxe-setup/install.sh"

QUELLEN_KARTEN = [
    ("Upload", "_quelle_upload.html", "quellen-upload"),
    ("Katalog", "_quelle_katalog.html", "quellen-katalog"),
    ("Download", "_quelle_download.html", "quellen-download"),
    ("Custom", "_quelle_custom.html", "quellen-custom"),
]


# Die Punkte, die menu.ipxe.j2 unabhaengig vom Katalog immer anbietet.
SYSTEMPUNKTE = [
    ("local", "Von der lokalen Festplatte starten"),
    ("shell", "iPXE-Eingabeaufforderung"),
    ("reboot", "Neu starten"),
    ("poweroff", "Ausschalten"),
]


# Hier standen bis zum 26.08.2026 vier Weiterleitungen von "/systeme/..."
# nach "/quellen/...". Sie waren die Bruecke ueber ein einziges Update: Wer
# die Seite offen hatte, als es lief, sollte sein Formular nicht ins Leere
# schicken. Dieses Update ist lange her, und ein neu aufgesetzter Server
# kennt die alten Adressen nie -- was bleibt, ist eine Hintertuer, die
# erklaert werden muss und nichts mehr traegt.
#
# "/systeme/speichern" gibt es weiterhin, und das ist kein Rest: Er
# bestimmt, wo ein Eintrag erscheint. Systeme sagt, wo etwas steht --
# Quellen, was es ist.


@app.get("/systeme")
def systeme_seite(request: Request, meldung: str = "", art: str = "",
                  ansicht: str = "efi"):
    """Was gebootet werden kann -- Katalog und eigene Abbilder zusammen."""
    if ansicht not in ("efi", "pcbios"):
        ansicht = "efi"

    systeme = _systeme()
    # Nur, was der Server wirklich anbieten kann. Die Seite hatte bis
    # August 2026 zwei Listen, die einander widersprachen: die Tabelle
    # zeigte alle Eintraege, die Vorschau darunter nur die startbereiten --
    # beide beschrieben dasselbe Bootmenue. Jetzt zeigen sie dasselbe.
    #
    # Was fehlt, verschwindet nicht spurlos: Es steht als leise Zeile unter
    # den Karten, mit dem Weg dorthin, wo es zu holen ist. Sonst waere
    # "mein Ubuntu ist nicht mehr in der Liste" die Art, wie man von einem
    # abgebrochenen Abgleich erfaehrt.
    karten = _gruppiert([e for e in systeme if e["ready"]])

    # Was angefangen und nicht fertig ist. Bis zum 27.08.2026 nannte hier
    # eine Zeile ALLE Eintraege ohne Dateien -- auf einem frischen Server
    # war das der ganze Katalog, als waere er ein Mangel. Deshalb kam sie
    # weg, und damit auch die Auskunft ueber den abgebrochenen Abgleich.
    #
    # Jetzt steht sie wieder da, aber gefiltert: nur Eintraege, von denen
    # etwas auf der Platte liegt. Auf einem frischen Server ist das keiner.
    # Uploads und selbst Angelegtes bleiben draussen -- die tragen ihren
    # Zustand ohnehin sichtbar mit (siehe _systeme).
    unvollstaendig = [e for e in systeme
                      if not e["ready"] and not e.get("upload")
                      and not e.get("eigen") and _angefangen(e)]

    # Fuer die Vorschau eine echte MAC nehmen, wenn eine bekannt ist --
    # so sieht man auch gleich, wie lang die Zeile am Client wird.
    with db() as conn:
        zuletzt = conn.execute(
            "SELECT mac FROM clients WHERE last_seen IS NOT NULL "
            "ORDER BY last_seen DESC LIMIT 1"
        ).fetchone()

    return html.TemplateResponse(
        request,
        "systeme.html",
        _rahmen(
            aktiv="systeme",
            meldung=meldung,
            meldungsart=art,
            gruppen=karten,
            # Angezeigt wird immer 1, 2, 3 in der geltenden Folge -- nicht
            # das, was roh in der Datei steht.
            folge=gruppen.stand(list(karten)),
            # Was eingerichtet ist, aber keine Dateien hat. Namentlich,
            # nicht nur als Zahl: Wer etwas vermisst, will wissen, ob es
            # gerade das ist -- und die Formulare zum Holen stehen seit dem
            # Umzug unter Quellen.
            # Dateien fehlen -- und getrennt davon: Dateien sind da, aber
            # der Eintrag kann ohne NFS gar nicht starten. Zwei Gruende,
            # zwei Zeilen; "seine Dateien fehlen noch" waere hier falsch.
            ohne_nfs=[e for e in systeme if e.get("braucht_nfs")],
            unvollstaendig=unvollstaendig,
            # Bereit, aber niemandem angeboten. Seit die Freigabe leer
            # anfaengt, ist das der Zustand von allem frisch Geholten --
            # und der Grund, warum man auf diese Seite kommt.
            #
            # Je Gruppe und nicht in einem Topf: Die Zeile steht seit dem
            # 27.08.2026 im Fuss der Karte, zu der die Eintraege gehoeren.
            # Angekreuzt wird in derselben Karte -- eine gemeinsame Liste
            # unter allen dreien liesse einen suchen, wo.
            wartend={g: [e for e in liste
                         if not e["im_menue"] and not e["in_optionen"]]
                     for g, liste in karten.items()},
            ansicht=ansicht,
            vorschau=menue_gruppen(ansicht),
            systempunkte=SYSTEMPUNKTE,
            vorschau_mac=zuletzt["mac"] if zuletzt else "aa:bb:cc:dd:ee:ff",
            titel=bezeichnungen.menue_titel(
                zuletzt["mac"] if zuletzt else "aa:bb:cc:dd:ee:ff", ansicht),
            menu_default=MENU_DEFAULT,
            menu_timeout=MENU_TIMEOUT,
        ),
    )


def _namen_aus_formular(formular, systeme: list[dict]) -> tuple[dict, list[str]]:
    """Eigene Namen und Versionen aus einem Formular uebernehmen.

    Gebraucht von beiden Seiten: unter Systeme steht das Feld in der Liste
    der Eintraege, unter Quellen bei dem Abbild, aus dem der Eintrag
    entstanden ist. Es ist derselbe Name -- wer ihn hier aendert, aendert
    ihn dort.

    Angefasst wird nur, was im Formular stand -- und das gilt je Feld. Ein
    Eintrag, der gerade laedt oder nur auf der anderen Seite steht, hat
    dort gar kein Feld; sein eigener Name darf davon nicht verschwinden.
    Und die Menue-Info gibt es nur auf drei der vier Karten unter Quellen,
    unter Systeme auf keiner: Wo sie fehlt, bleibt sie, wie sie war.
    """
    werte = bezeichnungen.alle()
    fehler: list[str] = []
    for eintrag in systeme:
        slug = eintrag.get("slug", "")
        hat_namen = f"name:{slug}" in formular
        hat_info = f"info:{slug}" in formular
        if not hat_namen and not hat_info:
            continue
        try:
            name, version, info = bezeichnungen.pruefe(
                str(formular.get(f"name:{slug}", "")),
                str(formular.get(f"version:{slug}", "")),
                str(formular.get(f"info:{slug}", "")))
        except ValueError as grund:
            fehler.append(f"{eintrag.get('name', slug)}: {grund}")
            continue

        # Gespeichert wird nur, was von der Vorgabe abweicht. Ein leeres
        # Feld heisst deshalb "wieder die Vorgabe" und nicht "kein Name" --
        # ein Eintrag ohne Namen waere im Menue nicht anzusteuern.
        vorher = werte.get(slug, {})
        abweichung = {}
        if hat_namen:
            if name and name != eintrag.get("name_vorgabe", ""):
                abweichung["name"] = name
            if version and version != (eintrag.get("version_vorgabe", "") or ""):
                abweichung["version"] = version
        else:
            abweichung.update({f: w for f, w in vorher.items()
                               if f in ("name", "version")})
        # Auch dieses Feld ist vorbelegt -- mit dem Abgelesenen. Wer es so
        # stehen laesst, will nichts eigenes: Gespeichert wuerde sonst der
        # heutige Stand und bliebe stehen, wenn sich das Abbild aendert.
        if hat_info:
            if info and info != eintrag.get("info_vorgabe", ""):
                abweichung["info"] = info
        elif vorher.get("info"):
            abweichung["info"] = vorher["info"]
        # Auf die Laenge geprueft wird die Zeile, wie sie im Menue stehen
        # wird -- aber nur, wenn jemand an ihr getippt hat. Was der Server
        # aus einem Abbild liest, ist regelmaessig laenger als eine
        # Menuezeile; das abzulehnen hiesse, den Eintrag gar nicht erst
        # anzubieten. Wer selbst etwas eintraegt, soll dagegen erfahren,
        # dass es auf dem Bildschirm nicht mehr ankommt.
        eigene_zeile = (hat_namen
                        and (name != eintrag.get("name_vorgabe", "")
                             or version != (eintrag.get("version_vorgabe", "") or "")))
        eigene_info = hat_info and info != eintrag.get("info_vorgabe", "")
        try:
            bezeichnungen.pruefe_laenge(
                name if eigene_zeile else "",
                version if eigene_zeile else "",
                info if eigene_info else "")
        except ValueError as grund:
            fehler.append(f"{eintrag.get('name', slug)}: {grund}")
            continue

        if abweichung:
            werte[slug] = abweichung
        else:
            werte.pop(slug, None)
    return werte, fehler


@app.post("/systeme/speichern")
async def systeme_speichern(request: Request):
    """Was auf der Seite steht: Reihenfolge der Karten und Freigaben.

    Bezeichnungen nimmt diese Route nicht mehr entgegen. Sie standen hier
    als Felder, solange Systeme auch zum Bearbeiten da war; seit die
    Angaben dort nur noch angezeigt werden, gibt es genau einen Ort, an
    dem sie entstehen -- die Karte unter Quellen, bei dem Abbild, aus dem
    der Eintrag stammt. Zwei Orte fuer dieselbe Angabe waren einer zu
    viel.

    Ein Knopf sichert beides. Zwei Formulare nebeneinander waeren zwei
    Vorgaenge, wo der Bedienende einen sieht -- er hat eine Seite vor sich
    und will, dass das darauf Stehende gilt.

    Ein Feld mit etwas Unbrauchbarem bricht den ganzen Vorgang ab. Die
    Haelfte zu speichern und den Rest stillschweigend zu verwerfen waere
    schlimmer: die Seite zeigte danach einen Stand, den so niemand
    eingetragen hat.
    """
    formular = await request.form()
    systeme = _systeme()
    # Schon in der geltenden Folge -- die zaehlt gleich als Rueckfall.
    aktuell = list(_gruppiert(systeme))
    vorher = gruppen.stand(aktuell)

    fehler: list[str] = []

    # ---- Reihenfolge der Gruppen ------------------------------------
    folge_werte: dict[str, int] = {}
    for schluessel, roh in formular.items():
        if not schluessel.startswith("folge:"):
            continue
        name = schluessel[len("folge:"):]
        if name not in aktuell:
            continue
        try:
            folge_werte[name] = gruppen.pruefe(str(roh))
        except ValueError as grund:
            fehler.append(f"{name}: {grund}")

    # ---- Freigaben ---------------------------------------------------
    freigaben = freigabe.alle()
    for eintrag in systeme:
        slug = eintrag.get("slug", "")

        # Ein Kaestchen ohne Haken schickt gar nichts. Dass die beiden
        # ueberhaupt auf der Seite standen, sagt das verborgene Feld
        # "haken:<slug>" daneben -- ohne diesen Umweg waere "abgewaehlt"
        # nicht von "gar nicht angezeigt" zu unterscheiden, und ein
        # Formular ohne Kaestchen wuerde stumm alles zurueckziehen.
        if f"haken:{slug}" in formular:
            freigaben[slug] = {"menue": f"menue:{slug}" in formular,
                               "optionen": f"optionen:{slug}" in formular}

    if fehler:
        return RedirectResponse(
            antwort("/systeme", "Nicht gespeichert. " + " ".join(fehler),
                    schlecht=True),
            status_code=303)

    if folge_werte:
        # Sortiert wird nach drei Dingen, in dieser Ordnung:
        #
        #   1. die eingetragene Zahl
        #   2. ob das Feld angefasst wurde
        #   3. die Stelle, an der die Gruppe gerade steht
        #
        # Der mittlere Punkt ist der wichtige. Wer eine Gruppe nach vorn
        # holen will, schreibt eine 1 hinein -- und laesst die andere Karte
        # stehen, in der ebenfalls eine 1 steht. Ohne diesen Punkt geschaehe
        # dann nichts Sichtbares, waehrend oben "gespeichert" steht. Eine
        # angefasste Zahl ist ein Wunsch, eine stehengelassene nur der Stand
        # der Dinge -- und ein Wunsch gewinnt.
        #
        # Gespeichert wird danach 1, 2, 3 und nicht das Eingetippte: aus
        # 5, 10, 20 wird dieselbe Folge in kleinen Zahlen, sonst stuende
        # beim naechsten Aufruf die Frage im Raum, ob dazwischen etwas
        # fehlt.
        folge = sorted(folge_werte, key=lambda name: (
            folge_werte[name],
            0 if folge_werte[name] != vorher.get(name) else 1,
            aktuell.index(name),
        ))
        gruppen.setze({name: stelle for stelle, name in enumerate(folge, start=1)})

    freigaben.pop("*", None)
    freigabe.setze(freigaben)
    return RedirectResponse(
        antwort("/systeme", "Gespeichert."), status_code=303)


def wecken(mac: str) -> tuple[str, bool]:
    """Schickt das Weckpaket. Liefert den Satz fuer die Oberflaeche und ob es ging.

    Fehler werden gemeldet, nicht geworfen: ein misslungener Weckversuch ist
    kein Grund, die Seite mit einem Fehlercode abzuwerfen.

    Das zweite Stueck der Antwort ist seit A-021 noetig: Die Meldung traegt
    jetzt eine Auspraegung, und die aus dem Satz zurueckzulesen -- "steht da
    'konnte nicht'?" -- waere ein Zusammenhang, den der naechste Umbau am
    Wortlaut nicht bemerkt.
    """
    try:
        ziele = wol.wecken(mac)
    except OSError as fehler:
        return f"Weckpaket fuer {mac} konnte nicht gesendet werden: {fehler}", False

    with db() as conn:
        conn.execute("UPDATE clients SET last_wake = ? WHERE mac = ?", (now(), mac))

    return (
        f"Weckpaket an {mac} gesendet ({', '.join(ziele)}). "
        "Ob der Rechner angeht, sieht man erst, wenn er sich meldet."
    ), True


@app.post("/clients/wecken")
def clients_wecken(mac: list[str] = Form(default=[])):
    """Mehrere Rechner auf einmal einschalten.

    Der Knopf sitzt in der Spaltenueberschrift, angekreuzt wird in den
    Zeilen -- so weckt ein Klick eine ganze Reihe Maschinen, etwa wenn eine
    Werkstattreihe neu aufgesetzt werden soll.
    """
    gewaehlt = [m for m in (normalise_mac(x) for x in mac) if m]
    if not gewaehlt:
        return RedirectResponse(
            antwort("/clients", "Keinen Rechner angekreuzt.", schlecht=True,
                    marke="registrierte-clients"),
            status_code=303)

    with db() as conn:
        namen = {r["mac"]: r["name"] for r in
                 conn.execute("SELECT mac, name FROM clients")}

    geweckt, misslungen = [], []
    for adresse in gewaehlt:
        try:
            wol.wecken(adresse)
        except (OSError, ValueError) as fehler:
            misslungen.append(f"{namen.get(adresse) or adresse} ({fehler})")
            continue
        geweckt.append(namen.get(adresse) or adresse)
        with db() as conn:
            conn.execute("UPDATE clients SET last_wake = ? WHERE mac = ?",
                         (now(), adresse))

    teile = []
    if geweckt:
        teile.append(("Weckpaket gesendet an " if len(geweckt) == 1
                      else f"Weckpakete gesendet an {len(geweckt)} Rechner: ")
                     + ", ".join(geweckt))
    if misslungen:
        teile.append("Fehlgeschlagen: " + ", ".join(misslungen))
    # Misslungene Weckpakete stehen im selben Satz wie die gelungenen --
    # deshalb ist die Auspraegung schlecht, sobald eines dabei war.
    return RedirectResponse(antwort("/clients", ". ".join(teile),
                                    schlecht=bool(misslungen),
                                    marke="registrierte-clients"),
                            status_code=303)


@app.post("/clients/{mac}/wake")
def wake_client(mac: str):
    """Weckt einen Rechner per Wake-on-LAN, ohne sonst etwas zu aendern."""
    normalised = normalise_mac(mac)
    if not normalised:
        raise HTTPException(status_code=400, detail="Ungueltige MAC-Adresse")
    satz, ging = wecken(normalised)
    return RedirectResponse(antwort("/clients", satz, schlecht=not ging,
                                    marke="registrierte-clients"),
                            status_code=303)


@app.post("/clients/speichern")
async def clients_speichern(request: Request):
    """Die ganze Rechnerliste auf einmal sichern.

    Ein Knopf fuer die Tabelle statt einer je Zeile. Vorher hatte jede
    Zeile ein eigenes Formular und der Name noch ein zweites daneben --
    das sah aus, als gaebe es mehrere Sorten "gespeichert", und wer den
    Namen abschickte, verlor die Auswahl daneben. Jetzt haengen Name,
    Auswahl und Haken aller Zeilen an einem Formular.

    Geschrieben wird nur, was sich wirklich geaendert hat; jede Zeile
    schickt ihren Ausgangsstand als verstecktes Feld mit. Das spart nicht
    Schreibzugriffe, es ist eine Bremse: zwischen dem Aufbau der Seite und
    dem Klick kann ein Rechner gebootet haben, und der Server nimmt ihm
    dabei den Haken "PXE Boot aktiv" ab. Ohne den Vergleich wuerde das
    Speichern einer ganz anderen Zeile ihm den Haken wieder ansetzen -- und
    die Maschine beim naechsten Start ein zweites Mal aufsetzen.
    """
    formular = await request.form()

    def feld(art: str, mac: str) -> str:
        return str(formular.get(art + ":" + mac, ""))

    # Welche Zeilen standen auf der Seite? Der Ausgangsstand des Namens ist
    # in jeder Zeile dabei, auch wenn er leer ist -- daran haengt die Liste.
    macs = []
    for schluessel in formular:
        art, _, mac = str(schluessel).partition(":")
        if art == "war_name" and mac and mac not in macs:
            macs.append(mac)

    # Erst sammeln und pruefen, dann schreiben: eine unbekannte Auswahl soll
    # nicht die halbe Liste gespeichert zuruecklassen.
    aenderungen = []
    for mac in macs:
        normalised = normalise_mac(mac)
        if not normalised:
            continue

        name = feld("name", mac).strip()[:MAX_CLIENTNAME]
        entry = feld("entry", mac) or None
        pxe = 1 if formular.get("pxe_aktiv:" + mac) else 0
        war_name = feld("war_name", mac)
        war_entry = feld("war_entry", mac) or None
        war_pxe = 1 if feld("war_pxe", mac) == "1" else 0

        if entry and find_entry(entry) is None:
            raise HTTPException(status_code=400,
                                detail="Unbekannter Eintrag: " + entry)

        # Der Haken gilt auch ohne Auswahl: er heisst "darf per Netzwerk
        # starten", und ohne Auswahl heisst das "zeig ihm das Menue".
        # Frueher wurde er hier stillschweigend geloescht, weil es ohne
        # Auswahl nichts scharfzuschalten gab -- damals war das Menue der
        # Normalfall und brauchte keine Freigabe.
        if name != war_name or entry != war_entry or pxe != war_pxe:
            aenderungen.append((normalised, name, entry, pxe))

    with db() as conn:
        for normalised, name, entry, pxe in aenderungen:
            conn.execute(
                "UPDATE clients SET name = ?, entry = ?, pxe_aktiv = ? "
                "WHERE mac = ?", (name, entry, pxe, normalised))

    # Wie beim Umbenennen zwei Antworten auf denselben Aufruf: Die Seite
    # bittet um JSON und setzt den neuen Stand selbst ein, statt neu zu
    # laden -- sonst waeren angekreuzte WOL-Kaestchen nach dem Speichern
    # weg. Ohne JavaScript kommt das Formular normal an und bekommt die
    # Weiterleitung samt Meldung.
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"gespeichert": len(aenderungen),
                             "clients": _rechner_liste()})
    if not aenderungen:
        # Keine Zurueckweisung: Es war nichts zu tun, und das ist kein
        # Fehler. Die Auspraegung bleibt deshalb die neutrale.
        return RedirectResponse(
            antwort("/clients", "Nichts zu speichern.",
                    marke="registrierte-clients"),
            status_code=303)
    return RedirectResponse(
        antwort("/clients",
                ("Ein Rechner gespeichert." if len(aenderungen) == 1
                 else f"{len(aenderungen)} Rechner gespeichert."),
                marke="registrierte-clients"),
        status_code=303)


def _clients_meldung(text: str, anker: str = "manuelle-registrierung", *,
                     schlecht: bool = True):
    """Die eine Antwort dieser Seite: zurueck auf /clients, mit einer Karte.

    Jedes Formular der Oberflaeche antwortet ueber "?meldung=", und die
    Routen hier taten es bis zum 03.09.2026 als einzige nicht -- sie warfen
    eine HTTPException, und der Benutzer landete auf einer nackten
    JSON-Zeile ohne Kopf, ohne Reiter und ohne Weg zurueck. Wer eine
    weitere Antwort braucht, nimmt diese Funktion und baut sich keinen
    zweiten Weg.
    """
    return RedirectResponse(antwort("/clients", text, schlecht=schlecht,
                                    marke=anker),
                            status_code=303)


# Was der Benutzer eintippen soll, wenn er es falsch eingetippt hat --
# dieselbe Auskunft wie im title-Attribut des Eingabefeldes, egal ob der
# Browser abweist oder der Server.
MAC_FORM = ("Sechs Paare, getrennt durch Doppelpunkt oder Bindestrich "
            "— aa:bb:cc:dd:ee:ff.")


@app.post("/clients/loeschen")
def clients_loeschen(mac: list[str] = Form(default=[])):
    """Mehrere Rechner auf einmal aus der Liste nehmen.

    Gebaut wie das Wecken: Knopf in der Spaltenueberschrift, angekreuzt
    wird in den Zeilen. Vorher hatte jede Zeile ihren eigenen Loeschknopf
    -- der hielt die Zeile hoch und stand bei siebzig Rechnern siebzigmal
    da, obwohl man ihn selten braucht.

    **Weg ist hier nur die Zeile, nicht der Rechner.** Er kommt wieder
    herein, sobald er das naechste Mal ueber das Netz startet -- mit
    seinem Namen ist es dann allerdings vorbei.
    """
    gewaehlt = [m for m in (normalise_mac(x) for x in mac) if m]
    if not gewaehlt:
        return _clients_meldung("Keinen Rechner angekreuzt.",
                                "registrierte-clients")

    with db() as conn:
        namen = {r["mac"]: r["name"] for r in
                 conn.execute("SELECT mac, name FROM clients")}
        weg = [m for m in gewaehlt if m in namen]
        for adresse in weg:
            conn.execute("DELETE FROM clients WHERE mac = ?", (adresse,))

    if not weg:
        return _clients_meldung("Kein angekreuzter Rechner stand in der Liste.",
                                "registrierte-clients")
    bezeichnet = [namen.get(m) or m for m in weg]
    text = ("Gelöscht: " + bezeichnet[0] if len(weg) == 1
            else f"{len(weg)} Rechner gelöscht: " + ", ".join(bezeichnet))
    return _clients_meldung(text + ".", "registrierte-clients")


@app.post("/clients/{mac}/delete")
def delete_client(mac: str):
    normalised = normalise_mac(mac)
    if not normalised:
        return _clients_meldung("Das ist keine MAC-Adresse. " + MAC_FORM,
                                "registrierte-clients")
    with db() as conn:
        weg = conn.execute("DELETE FROM clients WHERE mac = ?",
                           (normalised,)).rowcount
    if not weg:
        return _clients_meldung(f"{normalised} war nicht registriert.",
                                "registrierte-clients")
    return _clients_meldung(f"{normalised} gelöscht.", "registrierte-clients")


@app.post("/clients/add")
def add_client(mac: str = Form(...), name: str = Form("")):
    """Rechner von Hand eintragen -- fuer Maschinen, die noch nie gebootet haben.

    Drei Ausgaenge, und jeder sagt, was geschehen ist. Bis zum 03.09.2026
    schwiegen zwei davon: Eine krumme Eingabe endete auf einer nackten
    Fehlerseite, und eine bereits bekannte MAC lud die Seite neu, ohne dass
    irgendetwas passierte -- "INSERT OR IGNORE" laesst die vorhandene Zeile
    in Ruhe und sagt es niemandem.

    Der Name eines bekannten Rechners wird dabei nicht ueberschrieben, ein
    leerer aber gefuellt. Dieselbe Regel gilt beim Booten fuer das Produkt
    (siehe touch_client): Was einmal dasteht, nimmt der Server niemandem
    weg -- umbenannt wird in der Liste, wo man sieht, was vorher dastand.
    """
    normalised = normalise_mac(mac)
    if not normalised:
        return _clients_meldung("Das ist keine MAC-Adresse. " + MAC_FORM)
    name = name.strip()[:MAX_CLIENTNAME]
    with db() as conn:
        zeile = conn.execute("SELECT name FROM clients WHERE mac = ?",
                             (normalised,)).fetchone()
        if zeile is None:
            conn.execute("INSERT INTO clients (mac, name) VALUES (?, ?)",
                         (normalised, name))
            return _clients_meldung(f"{normalised} registriert.")

        bisher = zeile["name"] or ""
        if name and not bisher:
            conn.execute("UPDATE clients SET name = ? WHERE mac = ?",
                         (name, normalised))
            return _clients_meldung(
                f"{normalised} war schon registriert und heißt jetzt „{name}“.")

    if name and name != bisher:
        return _clients_meldung(
            f"{normalised} ist bereits registriert, als „{bisher}“. "
            "Der Name bleibt — umbenannt wird in der Liste.")
    return _clients_meldung(f"{normalised} ist bereits registriert.")


# --------------------------------------------------------------------------
# Eigene ISO-Abbilder
# --------------------------------------------------------------------------


@app.get("/uploads/vorhanden")
def upload_vorhanden(datei: str = "", url: str = ""):
    """Liegt unter dieser Kennung schon etwas? Gefragt vor dem Uebertragen.

    Der Browser fragt, sobald eine Datei ausgewaehlt (oder eine Adresse
    eingetragen) ist. Erst danach entscheidet der Mensch davor, ob das
    Vorhandene ersetzt werden soll oder eine zweite Ausgabe danebengehoert
    -- und erst danach gehen die Gigabyte los. Andersherum waere die
    Uebertragung schon durch, wenn die Frage kaeme.
    """
    name = uploads.name_aus_adresse(url) if url else datei
    if not name:
        raise HTTPException(status_code=400, detail="Kein Dateiname angegeben.")
    da = uploads.vorhanden(name)
    basis = uploads.slug_fuer(uploads.dateiname_fuer(name))
    return JSONResponse({
        "datei": uploads.dateiname_fuer(name),
        "slug": basis,
        "vorhanden": da,
        # Die Kennung, unter der eine zweite Ausgabe entstuende.
        "naechste": uploads.freier_slug(basis),
    })


@app.put("/uploads/{dateiname}")
async def upload_iso(dateiname: str, request: Request, neu: int = 0):
    """Nimmt ein ISO-Abbild entgegen -- als roher Datenstrom, nicht als
    Formular.

    Grund: ein Formular-Upload wuerde erst komplett zwischengespeichert,
    bevor die Anwendung ihn zu sehen bekommt. Bei mehreren Gigabyte ist das
    einmal Platte zu viel, und im Browser gaebe es keinen Fortschritt zu
    sehen. So wandert jeder Brocken sofort an seinen endgueltigen Platz.
    """
    laenge = int(request.headers.get("content-length") or 0)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if laenge and not isoscan.platz_reicht(ASSETS_DIR, laenge):
        raise HTTPException(
            status_code=507,
            detail="Auf dem Server ist nicht genug Platz fuer dieses Abbild.",
        )

    # "neu=1" heisst: danebenlegen statt darueber. Ohne die Angabe bleibt
    # es beim Ersetzen -- das ist der Weg, den ein Skript mit curl nimmt,
    # und der soll sich nicht dadurch aendern, dass der Browser jetzt
    # nachfragt.
    slug, ziel = uploads.anlegen(dateiname, als_neue=bool(neu))
    geschrieben = 0
    try:
        with ziel.open("wb") as raus:
            async for brocken in request.stream():
                raus.write(brocken)
                geschrieben += len(brocken)
    except ClientDisconnect:
        # Der haeufigste Grund ist kein Fehler, sondern eine Bedienung: Beim
        # Upload uebertraegt der Browser, und wer waehrenddessen die Seite
        # wechselt, bricht die Uebertragung ab. Frueher stand das als voller
        # Traceback im Journal ("Exception in ASGI application") und sah nach
        # einem kaputten Server aus -- beim naechsten Fehlersuchen fuehrt das
        # auf eine falsche Faehrte.
        weg = uploads.verwerfe(
            slug, "Der Upload wurde abgebrochen -- diese Fassung steht "
                  "unveraendert weiter bereit.")
        logging.getLogger("pxeweb").info(
            "Upload %s abgebrochen (Browser weg), %s -- %.2f GB waren angekommen",
            slug, "Eintrag entfernt" if weg else "vorherige Fassung bleibt",
            geschrieben / 1073741824)
        # 499 ist der Code, den nginx fuer "Client hat aufgelegt" benutzt.
        # Ausgeliefert wird er nicht mehr, es hoert ja niemand mehr zu; er
        # macht nur in der Zugriffsspalte den Unterschied zu einem Fehler
        # des Servers sichtbar.
        return PlainTextResponse("Upload abgebrochen.", status_code=499)
    except Exception:
        # Alles Uebrige ist wirklich ein Fehler und soll im Journal stehen --
        # aber auch dann bleibt keine halbe Datei liegen.
        uploads.verwerfe(
            slug, "Der Upload ist fehlgeschlagen -- diese Fassung steht "
                  "unveraendert weiter bereit.")
        raise

    if geschrieben == 0:
        uploads.verwerfe(slug, "Es kamen keine Daten an -- diese Fassung "
                               "steht unveraendert weiter bereit.")
        raise HTTPException(status_code=400, detail="Es kamen keine Daten an.")

    # Die vorherige Fassung faellt jetzt -- aber nicht hier, sondern zu
    # Beginn der Verarbeitung (uploads.verarbeite). Bis dahin ist sie die
    # einzige, die startet.
    #
    # Erkennen dauert Millisekunden, Entpacken je nach Abbild Minuten --
    # deshalb laeuft beides im Hintergrund weiter und die Seite fragt nach.
    uploads.starte_verarbeitung(slug)
    return JSONResponse({"slug": slug, "bytes": geschrieben}, status_code=201)


def _ausgabe_in_adresse(adresse: str) -> dict | None:
    """Steckt in dieser Adresse eine Ausgabe -- und gibt es Nachbarn dazu?

    Zwei Schritte, und der zweite ist der wichtigere: Erkennen allein ist
    eine Vermutung, die der Server dem Menschen davor auch noch erklaeren
    muesste. Findet sich dagegen unter derselben Stelle auch die
    Nachbarschaft der eingefuegten Ausgabe, ist nichts mehr zu erklaeren --
    dann steht da, was es beim Anbieter gibt.

    Bleibt die Gegenprobe aus, wird der Vorschlag trotzdem gezeigt, aber
    ohne Fundliste. Ein Anbieter ohne Verzeichnisindex macht die Erkennung
    nicht falsch.
    """
    befund = muster.erkenne(adresse)
    if not befund:
        return None
    probe = quellen.probe_muster(befund["muster"], zeitlimit=8.0)
    # Die eingefuegte gehoert nicht zu den "anderen" -- sie steht ja schon
    # im Formular.
    andere = [v for v in probe.get("gefunden", []) if v != befund["version"]]
    return {**befund, "andere": andere[:12],
            "geprueft": probe.get("geprueft", ""),
            "meldung": "" if probe.get("ok") else probe.get("meldung", "")}


@app.get("/quellen/eintrag/pruefen")
def eintrag_pruefen(bauart: str, spiegel: str = "", suite: str = "", basis: str = "",
                    kernel_url: str = "", initrd_url: str = ""):
    """Liegen die Dateien wirklich dort? Ein Byte je Datei, kein Download.

    Damit wird aus "auf der Herstellerseite suchen, bis man etwas Brauchbares
    findet" ein "Adresse eintippen, Knopf druecken, sehen ob es stimmt".

    Seit August 2026 beantwortet derselbe Knopf noch eine zweite Frage:
    Steckt in der Adresse eine Ausgabe? Bewusst kein eigener Knopf daneben
    -- gedrueckt wird dieser hier ohnehin, bevor jemand etwas anlegt, und
    zwei Knoepfe fuer zwei Fragen an dieselbe Adresse waeren einer zu viel.
    """
    befund = eigene.pruefe(bauart, spiegel=spiegel, suite=suite,
                           basis=basis, kernel_url=kernel_url,
                           initrd_url=initrd_url)
    # Angesehen wird das Feld, in das jemand die Adresse eingefuegt hat --
    # nicht die daraus gebaute Dateiadresse. Die Ausgabe steht im Weg
    # dorthin, und den hat der Mensch davor kopiert, nicht wir.
    adresse = (basis or kernel_url or "").strip()
    if adresse:
        ausgabe = _ausgabe_in_adresse(adresse)
        if ausgabe:
            befund = {**befund, "ausgabe": ausgabe}
    return JSONResponse(befund)


@app.post("/quellen/eintrag")
def eintrag_anlegen(
    bauart: str = Form(...),
    name: str = Form(...),
    gruppe: str = Form(...),
    basis: str = Form(""),
    spiegel: str = Form(""),
    suite: str = Form(""),
    quelle: str = Form(""),
    kernel_url: str = Form(""),
    initrd_url: str = Form(""),
    cmdline: str = Form(""),
    beschreibung: str = Form(""),
    versionen: str = Form(""),
):
    """Einen eigenen Netz-Installer aufnehmen -- Kernel und Initrd holen.

    "versionen" ist der Weg fuer mehrere Ausgaben auf einmal: Der
    Pruefen-Knopf hat in der Adresse eine Ausgabe erkannt und beim Anbieter
    ihre Nachbarn gefunden; angekreuzt wird, welche davon mitkommen sollen.
    Bleibt das Feld leer, entsteht ein einzelner Eintrag wie bisher -- der
    Weg ohne JavaScript und der Weg fuer alles, wo keine Ausgabe drinsteht.
    """
    gewaehlt = [v for v in re.split(r"[\s,]+", versionen.strip()) if v]
    try:
        if gewaehlt:
            # Das Muster entsteht hier und nicht im Browser: Was gebaut
            # wird, soll der Server bestimmen -- der Browser schickt nur,
            # welche Ausgaben gemeint sind.
            adresse = (basis or kernel_url or "").strip()
            befund = muster.erkenne(adresse)
            if not befund:
                raise ValueError("In dieser Adresse steckt keine Ausgabe.")
            # Jedes Feld, in dem eine Ausgabe steckt, wird zum Muster --
            # auch die Paketquelle. Ein Kernel aus 3.23 mit dem Paketdepot
            # von 3.21 installiert Falsches, und zwar ohne Fehlermeldung.
            def als_muster(wert: str) -> str:
                erkannt = muster.erkenne(wert) if wert else None
                return erkannt["muster"] if erkannt else wert

            eigene.anlegen_mehrere(
                bauart, name, gruppe, befund["muster"], gewaehlt,
                basis=als_muster(basis), kernel_url=als_muster(kernel_url),
                initrd_url=als_muster(initrd_url), spiegel=als_muster(spiegel),
                suite=suite, quelle=als_muster(quelle),
                cmdline=als_muster(cmdline), beschreibung=beschreibung)
        else:
            eigene.anlegen(bauart=bauart, name=name, gruppe=gruppe, basis=basis,
                           spiegel=spiegel, suite=suite, quelle=quelle,
                           kernel_url=kernel_url, initrd_url=initrd_url,
                           cmdline=cmdline, beschreibung=beschreibung)
    except ValueError as fehler:
        return RedirectResponse(
            antwort("/quellen", str(fehler), schlecht=True, marke="custom"),
            status_code=303)
    if gewaehlt:
        wieviel = f"{name} in {len(gewaehlt)} Ausgaben wird geholt."
    else:
        wieviel = name + " wird geholt."
    return RedirectResponse(antwort("/quellen", wieviel, marke="custom"),
                            status_code=303)


@app.post("/eintraege/{kennung}/ausgabe")
def eintrag_ausgabe_dazu(kennung: str, version: str = Form(...)):
    """Eine weitere Ausgabe neben einen selbst angelegten Eintrag stellen.

    Der Gegenzug zur Meldung des Waechters: Er sagt, dass es beim Anbieter
    etwas Neueres gibt, und hier wird es geholt. Ohne diesen Weg waere die
    Meldung eine Sackgasse -- man muesste die Karte "Custom" noch einmal
    ausfuellen, mit denselben Angaben und einer anderen Nummer.
    """
    try:
        neu_slug = eigene.ausgabe_dazu(kennung, version)
    except ValueError as fehler:
        return RedirectResponse(
            antwort("/quellen", str(fehler), schlecht=True, marke="custom"),
            status_code=303)
    return RedirectResponse(
        antwort("/quellen", f"Ausgabe {version} wird geholt.", marke="custom")
        + "#eintrag-" + neu_slug, status_code=303)


@app.post("/eintraege/{kennung}/delete")
def eintrag_loeschen(kennung: str):
    try:
        eigene.loesche(kennung)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unbekannte Kennung")
    return RedirectResponse("/quellen#custom", status_code=303)


def _eintragsorte(systeme: list[dict]) -> dict[str, Path | None]:
    """Je Eintrag sein Verzeichnis -- und das heisst wie er.

    Frueher stand hier eine Regel, die den Ordner eines Eintrags aus den
    Pfaden seiner Startdateien erschloss: von unten nach oben, angehalten
    von fremden Dateien und von Nachbarordnern. Sie ist zweimal
    danebengegangen -- bei ubuntu/24.04 neben 26.04 und bei SystemRescue,
    wo das Wurzeldateisystem neben dem Kernel lag und zum Loeschen
    angeboten wurde.

    Seit jeder Eintrag in assets/<kennung>/ wohnt, gibt es nichts mehr zu
    erschliessen. Die Kennung ist ohnehin eindeutig -- sie ist Sprungmarke
    im Bootmenue, Teil der URL und Name des Verzeichnisses. Was darunter
    liegt, gehoert ihm; was nicht darunter liegt, gehoert ihm nicht.

    Kein Verzeichnis heisst: der Eintrag hat hier nichts liegen. Die
    Online-Installationen holen alles aus dem Netz.
    """
    orte: dict[str, Path | None] = {}
    for eintrag in systeme:
        ordner = eintragsordner(eintrag.get("slug", ""))
        orte[eintrag.get("slug", "")] = ordner if ordner and ordner.is_dir() else None
    return orte


def eintragsordner(slug: str) -> Path | None:
    """assets/<kennung> -- mit Pruefung gegen Pfad-Tricks.

    Die Kennung kommt aus dem Katalog oder aus einer eintrag.yaml neben
    den Abbildern; beides sind Dateien, die jemand von Hand aendern kann.
    Ein ".." darin wuerde sonst aus der Ablage herausfuehren, und dieser
    Pfad wird auch zum Loeschen benutzt.
    """
    if not slug or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", slug):
        return None
    return ASSETS_DIR / slug


def _eintragsbelegung(eintrag: dict, ort: Path | None) -> int:
    """Was ein Eintrag auf der Platte belegt: sein Verzeichnis.

    Eine Regel, eine Stelle: Dieselbe Zahl steht als "Belegt" in der
    Eintragskarte und in der Detailansicht unter Server Health.

    Nicht mitgezaehlt wird wimboot, obwohl ein Windows-Eintrag es zum
    Starten braucht: Es gehoert dem Server und allen Windows-Abbildern
    gemeinsam. Stuende es bei jedem einzeln, waere es bei dreien dreimal
    gezaehlt und die Summe ginge nicht mehr auf.
    """
    return konfiguration.groesse(ort)["bytes"] if ort is not None else 0


# Der einzige Ordner, der keinem Eintrag gehoert und trotzdem dazu:
# wimboot holt fetch-wimboot.sh, und ohne es startet kein Windows-Abbild --
# auch wenn gerade keines da ist.
UNANTASTBAR = {"wimboot"}


def _kennungen(systeme: list[dict]) -> set[str]:
    """Die Verzeichnisnamen, die vergeben sind.

    Auch die von Eintraegen, deren Dateien gerade fehlen: Ein Ordner ist
    nicht verwaist, nur weil sein System noch nicht geholt wurde. Und auch
    die von Uploads, die noch laufen -- ihr Ordner liegt schon da, bevor
    es einen Katalogeintrag gibt. Beides steckt in _systeme().
    """
    return {e.get("slug", "") for e in systeme if e.get("slug")}


def verwaiste(systeme: list[dict] | None = None) -> list[dict]:
    """Was unter der Ablage liegt und zu keinem Eintrag gehoert.

    Eine Ebene, ein Vergleich: Jedes Verzeichnis direkt unter der Ablage
    traegt die Kennung seines Eintrags. Steht die Kennung in keiner Liste
    mehr, gehoert der Ordner niemandem.

    Frueher stieg diese Suche durch den Baum und musste dabei erraten, wo
    ein Eintrag aufhoert und der naechste anfaengt. Sie hat dabei einmal
    3,3 GB uebersehen und einmal das Wurzeldateisystem von SystemRescue
    zum Loeschen angeboten. Beides kann nicht wiederkommen: Ein Ordner
    innerhalb von <kennung>/ wird gar nicht mehr angesehen.

    Gesucht wird beim Seitenaufbau und nicht auf Knopfdruck: Das Suchen
    liest nur Verzeichnisnamen. Teuer ist das Messen der Groesse -- und
    das passiert nur fuer die Funde, die es meistens nicht gibt. Ein Knopf
    haette den umgekehrten Fehler: Man drueckt ihn nicht, weil man nicht
    weiss, dass es etwas zu finden gibt. Genau deshalb lagen 3,3 GB Ubuntu
    24.04 tagelang unbemerkt herum.
    """
    systeme = _systeme() if systeme is None else systeme
    vergeben = _kennungen(systeme)

    funde = []
    for kind in _oberste_ebene():
        if not kind.is_dir() or kind.name in UNANTASTBAR or kind.name in vergeben:
            continue
        gemessen = konfiguration.groesse(kind)
        funde.append({
            "pfad": str(kind),
            "name": kind.name,
            "bytes": gemessen["bytes"],
            "dateien": gemessen["dateien"],
        })
    return funde


def _oberste_ebene() -> list[Path]:
    """Was direkt unter der Ablage liegt, nach Namen sortiert."""
    try:
        return sorted(ASSETS_DIR.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []


def _sonstiger_hinweis(pfad: Path) -> str:
    """Warum dieser Posten da ist -- soweit es der Ort schon verraet.

    Ein Fall sieht wie Abfall aus und ist keiner: wimboot gehoert dem
    Server selbst, und ohne die Datei startet kein Windows-Abbild, auch
    wenn gerade keines da ist.
    """
    if pfad.name in UNANTASTBAR:
        return "wird für Windows-Abbilder gebraucht"
    return ""


def _sonstige_posten(systeme: list[dict], funde: list[dict]) -> list[dict]:
    """Was unter der Ablage liegt und weder Eintrag noch verwaist ist.

    Auf einer Ebene bleibt dafuer wenig uebrig: wimboot und einzelne
    Dateien. Gerade die Dateien sind der Grund, dass es diese Liste gibt --
    verwaist sind immer nur Ordner, und ein Abbild, das neben seinem
    entpackten Ordner liegenblieb, stand deshalb frueher in keiner Liste.

    Die Summe dieser Posten ist die Zeile "Sonstiges". Sie geht auf, weil
    jeder Eintrag der obersten Ebene genau einmal vorkommt: entweder als
    Kennung, als Fund oder hier.
    """
    vergeben = _kennungen(systeme)
    verwaist = {f["name"] for f in funde}

    posten: list[dict] = []
    for kind in _oberste_ebene():
        if kind.name in vergeben or kind.name in verwaist:
            continue
        gemessen = konfiguration.groesse(kind)
        # Ein leerer Ordner ist kein Posten: Er belegt nichts, und eine
        # Zeile mit "0 B" macht die Liste laenger, nicht klarer.
        if not gemessen["bytes"]:
            continue
        posten.append({
            "name": kind.name + ("/" if kind.is_dir() else ""),
            "bytes": gemessen["bytes"],
            "hinweis": _sonstiger_hinweis(kind),
        })
    return sorted(posten, key=lambda p: (-p["bytes"], p["name"].lower()))


def platzaufteilung(systeme: list[dict], funde: list[dict]) -> dict:
    """Wohin die Ablage geht: je Eintrag, verwaist, und was uebrig bleibt.

    Die Karte "Speicherplatz" sagte bisher "davon X GB Abbilder" und
    meinte damit nur die hochgeladenen Abbilder. Alles Mitgelieferte
    fehlte darin --
    auf einem Server mit gefuelltem Katalog war die Zahl um ein Vielfaches
    zu klein, und wer Platz suchte, suchte an der falschen Stelle.

    Sortiert wird nach Groesse, nicht nach Namen: Die Frage an dieser
    Stelle ist "wo ist der Platz hin?", und darauf antwortet der dickste
    Brocken zuerst. Die Reihenfolge des Bootmenues hat weiter oben ihre
    eigene Karte.

    Aufgefuehrt sind auch Eintraege, die nicht startbereit sind. Gerade
    die gehoeren hierher: ein abgebrochener Download liegt mit mehreren
    Gigabyte da und taucht in keiner Startbereit-Liste auf.

    "Sonstiges" wird nicht gemessen, sondern ausgerechnet -- ganze Ablage
    minus Eintraege minus verwaist. So faellt darunter auch, woran niemand
    gedacht hat: wimboot, eine ISO, die neben ihrem Ordner liegengeblieben
    ist, ein halber Upload ohne Zustandsdatei.
    """
    orte = _eintragsorte(systeme)
    zeilen = []
    for eintrag in systeme:
        ort = orte.get(eintrag.get("slug", ""))
        zeilen.append({
            "name": eintrag.get("name", ""),
            "version": eintrag.get("version") or "",
            "slug": eintrag.get("slug", ""),
            "ready": bool(eintrag.get("ready")),
            "ablage": (str(ort.relative_to(ASSETS_DIR)).replace(os.sep, "/")
                       if ort is not None else ""),
            "bytes": _eintragsbelegung(eintrag, ort),
        })

    belegend = sorted((z for z in zeilen if z["bytes"] > 0),
                      key=lambda z: (-z["bytes"], z["name"].lower()))
    # Hier ist die Zahl ohnehin gemessen: die groesste Ablage eines
    # Eintrags. Die Plattenwarnung braucht sie, darf sie aber nicht selbst
    # suchen -- sie entsteht auf jeder Seite. Siehe dienste.reserve().
    dienste.merke_groesstes_abbild(belegend[0]["bytes"] if belegend else 0)
    eintraege_bytes = sum(z["bytes"] for z in belegend)
    verwaist_bytes = sum(f["bytes"] for f in funde)
    gesamt = konfiguration.groesse(ASSETS_DIR)["bytes"]
    return {
        "eintraege": belegend,
        "eintraege_bytes": eintraege_bytes,
        "verwaist_bytes": verwaist_bytes,
        "verwaist_anzahl": len(funde),
        # Nie unter null: Zwischen dem Messen der Teile und dem der ganzen
        # Ablage kann geloescht worden sein, dann ginge die Rechnung sonst
        # ins Minus und die Karte behauptete etwas Unmoegliches.
        "sonstiges_bytes": max(0, gesamt - eintraege_bytes - verwaist_bytes),
        # Woraus die Zeile "Sonstiges" besteht. Erst die Zahl, dann auf
        # Wunsch die Posten: Sonst haette die Karte eine Liste, die
        # meistens niemanden interessiert, und die Antwort ginge darin
        # unter.
        "sonstiges": _sonstige_posten(systeme, funde),
        "gesamt": gesamt,
    }


def _raeumgut(eintrag: dict) -> tuple[Path | None, list[Path]]:
    """Was zu diesem Eintrag geloescht werden darf: sein Verzeichnis.

    Frueher stand hier eine Abgrenzung, die von den Startdateien nach oben
    ging, solange darunter nichts Fremdes lag. Sie musste zu eng bleiben,
    um nicht zu viel mitzunehmen, und war damit regelmaessig zu eng: Bei
    SystemRescue haette sie 52 KB weggeraeumt, Erfolg gemeldet und 1,7 GB
    liegen lassen.

    Jetzt faellt das Verzeichnis des Eintrags, und das ist alles, was ihm
    gehoert. Die Dateien daneben in der Rueckgabe sind die, die er zum
    Starten braucht -- sie liegen bis auf wimboot ohnehin darunter und
    dienen nur noch dazu, den Fall "der Eintrag hat gar keine Dateien"
    von "sein Ordner ist weg" zu unterscheiden.
    """
    pfade = [ASSETS_DIR / p for p in required_assets(eintrag)]
    if not pfade:
        return None, []
    ordner = eintragsordner(eintrag.get("slug", ""))
    return (ordner if ordner and ordner.is_dir() else None), pfade


def _belegung(ordner: Path | None, pfade: list[Path]) -> int:
    """Wieviel Platz das freimacht -- vor dem Loeschen gezaehlt."""
    if ordner is not None:
        return sum(p.stat().st_size for p in ordner.rglob("*") if p.is_file())
    return sum(p.stat().st_size for p in pfade if p.is_file())


def _raeume_ab(eintrag: dict) -> tuple[str, int]:
    """Die Dateien eines Katalogeintrags wegraeumen. Sagt, was wegging."""
    ordner, pfade = _raeumgut(eintrag)
    frei = _belegung(ordner, pfade)
    # Die gemerkten Verzeichnisgroessen sind ab jetzt falsch. Sie stehen in
    # den Karten und auf der Uebersicht -- gleich nach dem Loeschen noch die
    # alte Belegung zu zeigen, saehe aus, als sei nichts passiert.
    konfiguration.vergiss()
    if ordner is not None:
        shutil.rmtree(ordner, ignore_errors=True)
        _leere_ordner_weg([ordner])
        return str(ordner), frei
    for pfad in pfade:
        try:
            pfad.unlink()
        except OSError:
            pass
    _leere_ordner_weg(pfade)
    return ", ".join(sorted({str(p) for p in pfade})), frei


def _leere_ordner_weg(pfade: list[Path]) -> None:
    """Was danach leer zurueckbleibt, mitnehmen -- aber nur das Leere.

    Ein zurueckgebliebenes "memtest/8.10/" waere dauerhaft im Weg. Und seit
    ein Eintrag seinen Ordner selbst benennen kann, faellt bei GParted
    "gparted/1.8.1-3" statt "gparted" -- das leere "gparted" daneben stuende
    sonst gleich als verwaister Ordner mit 0 B in der Liste.
    """
    for pfad in pfade:
        ordner = pfad if pfad.is_dir() else pfad.parent
        while ordner != ASSETS_DIR and ASSETS_DIR in ordner.parents:
            try:
                ordner.rmdir()
            except OSError:
                break
            ordner = ordner.parent


@app.post("/verwaist/loeschen")
def verwaist_loeschen(pfad: str = Form(...)):
    """Einen verwaisten Ordner wegraeumen -- nach erneuter Pruefung.

    Der Pfad kommt aus dem Browser, und was von dort kommt, wird nicht
    geglaubt: Geloescht wird nur, was in diesem Moment noch in der Liste
    der verwaisten Ordner steht. Damit ist zugleich das Wettrennen
    erledigt -- wer die Seite eine Stunde offen hatte und dann klickt,
    loescht nichts, was inzwischen wieder jemandem gehoert.
    """
    funde = {f["pfad"]: f for f in verwaiste()}
    fund = funde.get(pfad)
    if fund is None:
        return RedirectResponse(
            antwort("/", "Der Ordner gehört inzwischen zu einem Eintrag "
                         "oder ist schon weg.", schlecht=True),
            status_code=303)

    shutil.rmtree(Path(fund["pfad"]), ignore_errors=True)
    konfiguration.vergiss()
    return RedirectResponse(
        antwort("/", f"{fund['name']} gelöscht, "
                     f"{lesbare_groesse(fund['bytes'])} frei."),
        status_code=303)


@app.post("/quellen/dateien/loeschen")
def dateien_loeschen(slug: str = Form(...), zurueck: str = Form("")):
    """Die Dateien eines Katalogeintrags wegraeumen, den Eintrag behalten.

    Das ist die kleine Schwester von "Version entfernen": Bei Debian, Mint
    oder Tumbleweed gibt es nur eine Ausgabe, die sich nicht aus einer Liste
    nehmen laesst -- der Menuepunkt gehoert zum Katalog. Loswerden wollte
    man die Dateien trotzdem, und bisher ging das nur auf der Konsole.

    Danach steht der Eintrag auf "fehlt" und der Abgleich holt ihn wieder.
    """
    # Ueber _systeme() und nicht ueber find_entry(): erst dort steht am
    # Eintrag, ob er hochgeladen oder selbst angelegt wurde. Ohne das haette
    # dieser Knopf einem Upload die Dateien samt eintrag.yaml weggeraeumt --
    # und damit den ganzen Eintrag, ohne dass jemand danach gefragt haette.
    eintrag = next((e for e in _systeme() if e["slug"] == slug), None)
    if eintrag is None or eintrag.get("upload") or eintrag.get("eigen"):
        # Hochgeladenes und Selbstgebautes hat sein eigenes "Loeschen" --
        # dort verschwindet der ganze Eintrag, denn ohne seine Dateien
        # gaebe es ihn nicht mehr.
        return RedirectResponse(
            antwort("/quellen", "Für diesen Eintrag gibt es das nicht.",
                    schlecht=True, marke=zurueck),
            status_code=303)

    ordner, pfade = _raeumgut(eintrag)
    if not any(p.exists() for p in pfade):
        return RedirectResponse(
            antwort("/quellen", f"Bei {eintrag['name']} liegt nichts.",
                    schlecht=True, marke=zurueck),
            status_code=303)

    weg, frei = _raeume_ab(eintrag)
    meldung = (f"{eintrag['name']}: {weg} gelöscht, "
               f"{lesbare_groesse(frei)} frei — der Abgleich holt es wieder.")
    return RedirectResponse(antwort("/quellen", meldung, marke=zurueck),
                            status_code=303)


def _eintraege_der_ausgabe(liste: str, version: str) -> list[dict]:
    """Alle Katalogeintraege, die aus dieser einen Ausgabe entstehen.

    Meist genau einer. Memtest sind zwei: memtest-bios und memtest-efi
    haengen beide an MEMTEST_VERSIONS, weil es dieselbe Ausgabe in zwei
    Bauarten ist. Wer eine davon entfernte, nahm die Nummer aus der Liste
    -- und damit verschwand auch die Schwester aus dem Katalog, ihr Ordner
    blieb aber liegen. Von der Quellenkarte aus gibt es je Ausgabe nur
    eine Zeile; hier muessen deshalb beide fallen.
    """
    return [e for e in load_catalog()
            if e.get("versionsliste") == liste and e.get("version") == version]


@app.post("/quellen/version/loeschen")
def version_loeschen(slug: str = Form(""), adresse: str = Form(""),
                     version: str = Form("")):
    """Eine Ausgabe samt ihren Dateien entfernen.

    Drei Schritte: die Nummer aus der Ausgabenliste nehmen, damit kein
    Menuepunkt mehr daraus entsteht; die Verzeichnisse wegraeumen, damit
    der Platz frei wird; und eine eigene Adresse fuer genau diese Ausgabe
    mitnehmen. Ohne den letzten Schritt bliebe sie in quellen.env stehen
    und kaeme stillschweigend zurueck, wenn jemand die Nummer spaeter
    wieder eintraegt.

    Angesprochen wird die Ausgabe ueber Quelle und Nummer -- so steht der
    Knopf in der Quellenkarte, neben "Holen". Die alte Form ueber "slug"
    bleibt: Unter /systeme/version/loeschen leitet eine 308 hierher, und
    ein Formular, das beim Update offen war, soll nicht ins Leere gehen.
    """
    # Jede Absage ist eine Meldung, kein Absturz: Zurueck auf die Seite.
    # Eine JSON-Fehlerseite waere hier das Ende des Wegs -- der Browser
    # stuende auf einer weissen Seite mit einem englischen Satz, und die
    # Karte, von der der Knopf kam, waere weg.
    def absage(satz: str):
        return RedirectResponse(
            antwort("/quellen", satz, schlecht=True, marke="katalog"),
            status_code=303)

    if adresse:
        liste = quellen.VERSIONSLISTE.get(adresse, "")
        if not liste:
            return absage("Diese Quelle hat keine Ausgaben zum Entfernen.")
        version = version.strip()
        if version not in quellen.liste(liste):
            return absage(f"Ausgabe {version} ist nicht eingetragen.")
        eintraege = _eintraege_der_ausgabe(liste, version)
    else:
        eintrag = find_entry(slug)
        if eintrag is None or not eintrag.get("version"):
            return absage("Dieser Eintrag hat keine Ausgaben zum Entfernen.")
        version = eintrag["version"]
        liste = eintrag.get("versionsliste", "")
        adresse = next((a for a, l in quellen.VERSIONSLISTE.items() if l == liste), "")
        eintraege = _eintraege_der_ausgabe(liste, version)

    rest = [v for v in quellen.liste(liste) if v != version]
    # Auch die letzte darf gehen. Bis August 2026 musste eine uebrig
    # bleiben, denn die Liste kam gefuellt aus sync-images.sh und eine
    # leere haette nach einem Fehler ausgesehen. Seit die Listen leer
    # ausgeliefert werden, ist die leere Liste ein Zustand mit Bedeutung:
    # Dieses System ist nicht in Betrieb. Ohne diesen Weg liesse sich
    # eines auch gar nicht wieder abschalten -- der Knopf hier ist der
    # einzige, der eine Ausgabe aus der Liste nimmt.

    # Dasselbe Wegraeumen wie bei "Dateien loeschen" -- der Unterschied
    # steht weiter unten: hier faellt auch die Nummer aus der Liste.
    # Vorher wurde nur der gemeinsame Ordner der Startdateien geloescht;
    # bei GParted blieben damit ISO und entpacktes Abbild liegen.
    weggeraeumt, frei = [], 0
    for eintrag in eintraege:
        if any(p.exists() for p in [ASSETS_DIR / a for a in required_assets(eintrag)]):
            was, bytes_ = _raeume_ab(eintrag)
            if was:
                weggeraeumt.append(was)
                frei += bytes_

    quellen.setze(liste, " ".join(rest))
    # Und die eigene Adresse dieser Ausgabe. Sie ueberlebte den Loeschvorgang
    # bisher: Wer 9 spaeter wieder eintrug, bekam die alte Adresse zurueck,
    # ohne dass irgendwo stand, woher sie kam.
    if adresse:
        quellen.loesche_ausgabe(adresse, version)
    meldung = f"Ausgabe {version} entfernt"
    if weggeraeumt:
        meldung += (f" samt {', '.join(weggeraeumt)} "
                    f"({lesbare_groesse(frei)} frei)")
    if not rest:
        # Es war die letzte -- dann ist nicht nur eine Ausgabe weg,
        # sondern das System aus dem Betrieb. Das ist eine groessere
        # Aussage als "entfernt" und gehoert deshalb dazu.
        meldung += " — dieses System ist damit nicht mehr in Betrieb"
    # Zurueck dorthin, wo der Knopf steht: zur Herkunft unter Quellen.
    return RedirectResponse(antwort("/quellen", meldung, marke="katalog"),
                            status_code=303)


@app.get("/sync.txt")
def sync_ausgabe() -> PlainTextResponse:
    """Die Ausgabe des laufenden Abgleichs -- die Seite liest sie mit."""
    z = sync.zustand()
    kopf = ""
    if z["laeuft"]:
        kopf = "läuft: " + ", ".join(z["komponenten"]) + "\n\n"
    elif z["ergebnis"]:
        kopf = ", ".join(z["komponenten"]) + " — " + z["ergebnis"] + "\n\n"
    return PlainTextResponse(kopf + (z["text"] or "Noch kein Abgleich gelaufen."),
                             media_type="text/plain; charset=utf-8")


@app.post("/uploads/holen")
def upload_von_url(request: Request, url: str = Form(...), neu: str = Form(""),
                   ersetzen: str = Form("")):
    """Ein Abbild von einer Adresse holen, statt es vom Arbeitsplatz zu schicken.

    "neu" heisst danebenlegen, "ersetzen" heisst darueber. Fragt die Karte
    (sie schickt "Accept: application/json") ohne eines von beidem und die
    Kennung ist belegt, wird hier abgebrochen und zurueckgemeldet, was
    schon dort liegt.

    Der Riegel sitzt mit Absicht hier und nicht im Browser: Sah die Seite
    vorher selbst nach und ihre Nachfrage ging schief, ersetzte sie ein
    fertiges Abbild stillschweigend -- ein verschluckter Fehler kostete
    dann ein Abbild. Der Server weiss ohnehin, was auf seiner Platte
    liegt, also entscheidet er.
    """
    per_json = "application/json" in (request.headers.get("accept") or "")
    if per_json and not neu and not ersetzen:
        name = uploads.name_aus_adresse(url)
        da = uploads.vorhanden(name)
        if da:
            basis = uploads.slug_fuer(uploads.dateiname_fuer(name))
            return JSONResponse(
                {"vorhanden": da, "naechste": uploads.freier_slug(basis)},
                status_code=409)
    try:
        slug = uploads.hole_von_url(url, als_neue=bool(neu))
    except ValueError as fehler:
        raise HTTPException(status_code=400, detail=str(fehler))
    # Die Karte bekommt die Kennung zurueck und verfolgt den Download an
    # Ort und Stelle -- wie die Upload-Karte daneben. Ohne JavaScript
    # bleibt es beim alten Weg: zurueck auf /quellen, das Formular steht
    # dort und die Seite verfolgt es von da. Ein Skript mit curl faellt
    # ebenfalls hierher und ersetzt wie eh und je.
    if per_json:
        return JSONResponse({"slug": slug}, status_code=202)
    return RedirectResponse("/quellen#download", status_code=303)


@app.get("/quelleninfo.json")
def quelleninfo_stand():
    """Der Befund des Waechters -- die Karte fragt danach, waehrend er laeuft."""
    return JSONResponse(quellenwacht.stand())


@app.post("/quelleninfo/pruefen")
def quelleninfo_pruefen():
    """Jetzt nachsehen, statt auf den naechsten Durchgang zu warten.

    Der Lauf klappert zwoelf Anbieter ab und dauert eine knappe Minute --
    er laeuft deshalb im Hintergrund, und die Karte verfolgt ihn ueber
    /quelleninfo.json, so wie die Download-Karte ihren Download.
    """
    quellenwacht.starte_lauf()
    return RedirectResponse("/#quellenwaechter", status_code=303)


@app.get("/uploads.json")
def upload_status():
    """Zustand aller Uploads -- die Startseite fragt das im Sekundentakt ab."""
    return JSONResponse({
        "uploads": [
            {
                "slug": u.get("slug", ""),
                "datei": u.get("datei", ""),
                "status": u.get("status", ""),
                "zustand_text": u.get("zustand_text", ""),
                "meldung": u.get("meldung", ""),
                "erkannt": u.get("erkannt", ""),
                "familie": u.get("familie", ""),
                "weg": u.get("weg", ""),
                "weg_text": u.get("weg_text", ""),
                "groesse": u.get("groesse", 0),
                # Wie viel es im Ganzen wird -- nur beim Holen von einer
                # Adresse bekannt, und nur dafuer da: die Karte zeichnet
                # daraus ihren Balken.
                "gesamt": u.get("gesamt", 0),
                # Woher es kam. Die Seite entscheidet danach, welche der
                # beiden Karten den Fortschritt anzeigt.
                "quelle": u.get("quelle", ""),
            }
            for u in uploads.alle()
        ]
    })


@app.post("/uploads/{slug}/reload")
def upload_neu_einlesen(slug: str, zurueck: str = Form("")):
    """Ein schon hochgeladenes Abbild noch einmal einordnen.

    Nuetzlich, wenn sich die Voraussetzungen geaendert haben -- etwa weil
    seit dem Upload ein NFS-Export bereitsteht und das Abbild jetzt
    gestreamt statt in den Arbeitsspeicher geladen werden kann, oder weil
    eine neue Fassung des Servers den Menuepunkt anders baut.

    Liegt das Abbild noch da, wird es komplett neu durchgearbeitet. Sonst
    wird wenigstens der Menuepunkt neu gebaut -- das Abbild ist nach dem
    Entpacken meistens geloescht, und mehrere Gigabyte noch einmal
    hochzuladen waere ein hoher Preis fuer eine geaenderte Zeile.
    """
    try:
        zustand = uploads.lies_zustand(slug) or {}
        vorhanden = (uploads.verzeichnis(slug) / zustand.get("datei", "")).is_file()
    except ValueError:
        raise HTTPException(status_code=400, detail="Unbekannte Kennung")

    if vorhanden:
        uploads.starte_verarbeitung(slug)
        return RedirectResponse(sprung("/quellen", zurueck), status_code=303)

    # Ohne Abbild bleibt der zweite Weg: den Menuepunkt aus dem gemerkten
    # Befund neu bauen. Das reicht fuer den haeufigen Fall -- eine neue
    # Fassung des Servers baut den Eintrag anders, und der abgelegte stammt
    # noch aus der alten. Neu entpackt wird dabei nichts.
    try:
        uploads.eintrag_neu_bauen(slug)
    except ValueError as fehler:
        raise HTTPException(status_code=400, detail=str(fehler))
    return RedirectResponse(sprung("/quellen", zurueck), status_code=303)


@app.post("/uploads/{slug}/abbrechen")
def upload_abbrechen(slug: str, zurueck: str = Form("")):
    """Einen laufenden Download anhalten.

    **Nur waehrend geladen wird.** Die Grenze ist uploads.uebernehmen():
    Davor liegt die vorherige Fassung unberuehrt daneben und ein Abbruch
    kostet nur die Uebertragung; danach ist sie ueberschrieben, weil in
    dasselbe Verzeichnis ausgepackt wird. Ein Knopf am Entpacken koennte
    nur noch waehlen, welchen Scherbenhaufen er hinterlaesst -- deshalb
    gibt es ihn dort nicht, und deshalb weist diese Route ab, statt still
    nichts zu tun.

    **Der Upload vom Arbeitsplatz kommt hier nicht vorbei.** Dort traegt
    der Browser, und der bricht selbst ab; der Server sieht einen
    ClientDisconnect und raeumt in upload_iso auf.

    Angehalten wird nicht sofort, sondern beim naechsten Brocken -- das
    dauert Bruchteile einer Sekunde. Aufgeraeumt wird im ladenden Faden
    selbst, ueber denselben Weg wie ein Fehlschlag.
    """
    try:
        zustand = uploads.lies_zustand(slug) or {}
    except ValueError:
        raise HTTPException(status_code=400, detail="Unbekannte Kennung")

    if zustand.get("status") != "laedt":
        return RedirectResponse(
            antwort("/quellen",
                    "Hier wird gerade nichts geladen — abbrechen lässt sich "
                    "nur eine laufende Übertragung.",
                    schlecht=True, marke=zurueck),
            status_code=303)

    uploads.brich_ab(slug)
    return RedirectResponse(
        antwort("/quellen", "Wird abgebrochen …", marke=zurueck),
        status_code=303)


@app.post("/uploads/{slug}/delete")
def upload_loeschen(slug: str, zurueck: str = Form("")):
    """Abbild und Eintrag wieder entfernen."""
    try:
        uploads.loesche(slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unbekannte Kennung")
    return RedirectResponse(sprung("/quellen", zurueck), status_code=303)


# --------------------------------------------------------------------------
# Download-Quellen der mitgelieferten Systeme
# --------------------------------------------------------------------------


# Die Seite hiess erst Konfiguration, dann Uebersicht und jetzt
# Einrichtung. Alte Lesezeichen sollen trotzdem ankommen -- eine
# Weiterleitung kostet nichts und erspart die Suche nach der Seite, die
# gestern noch da war.
@app.get("/konfiguration")
@app.get("/uebersicht")
def einrichtung_alt():
    return RedirectResponse("/einrichtung", status_code=308)


@app.get("/einrichtung")
def einrichtung_seite(request: Request, meldung: str = "", art: str = "",
                      schritt: str = "", fehlerbericht: str = "",
                      umgebung_mit: str = ""):
    """Wie dieser Server eingerichtet ist: Ablageorte und Einstellungen.

    Hier standen einmal auch die Belegung je Verzeichnis und die Dateien
    je Eintrag. Beides sagt inzwischen jemand anders und genauer: die
    Belegung die Detailansicht unter Server Health, aufgeschluesselt nach
    Eintraegen statt nach Ordnern, und die Dateien jede Eintragskarte
    selbst -- mit Pfad, Groesse und dem, was fehlt. Zwei Seiten, die
    dasselbe sagen, laufen frueher oder spaeter auseinander, und dann
    glaubt man keiner mehr.

    Was bleibt, ist keine Uebersicht mehr, sondern die Antwort auf eine
    einzige Frage: Wo erwartet die Anwendung was, und mit welchen Werten
    laeuft sie? Deshalb heisst die Seite jetzt Einrichtung.
    """
    tftp = ASSETS_DIR.parent / "tftp"
    orte = [
        {"was": "Abbilder", "pfad": str(ASSETS_DIR),
         "hinweis": "Kernel, Initrds, ausgepackte Abbilder -- wird per NFS exportiert",
         "schreiben": False, "optional": False},
        {"was": "Eigene Abbilder", "pfad": str(ASSETS_DIR),
         "hinweis": "hochgeladen oder von einer Adresse geholt -- jeder "
                    "Eintrag in seinem eigenen Ordner, benannt nach seiner "
                    "Kennung (iso-... beziehungsweise netz-...)",
         "schreiben": True, "optional": False},
        {"was": "iPXE-Bootloader", "pfad": str(tftp),
         "hinweis": "das Einzige, was per TFTP geht",
         "schreiben": False, "optional": False},
        {"was": "Katalog", "pfad": str(CATALOG_PATH),
         "hinweis": "die fest eingebauten Menuepunkte",
         "schreiben": False, "optional": False},
        {"was": "Datenbank", "pfad": str(DB_PATH),
         "hinweis": "Rechner, Vorauswahl und Boot-Verlauf",
         "schreiben": True, "optional": False},
        {"was": "Installationsprotokolle", "pfad": str(logs.LOG_DIR),
         "hinweis": "entsteht, sobald der erste Rechner eines schickt",
         "schreiben": True, "optional": True},
        {"was": "Eigene Download-Quellen", "pfad": str(quellen.EIGEN),
         "hinweis": "entsteht, sobald eine Adresse ersetzt wird",
         "schreiben": True, "optional": True},
    ]
    for ort in orte:
        ort["zustand"] = konfiguration.zustand(Path(ort["pfad"]))

    # Heisst nicht "einstellungen": So heisst das Modul, in dem steht, was
    # der Betreiber in der Oberflaeche entscheidet -- und eine lokale
    # Variable desselben Namens verdeckte es hier lautlos. Was hier steht,
    # sind ohnehin die Werte aus der Umgebung, nicht Einstellungen der
    # Anwendung.
    umgebungswerte = [
        {"name": "PXE_BASE_URL", "wert": BASE_URL,
         "wofuer": "Adresse, die in die iPXE-Skripte geschrieben wird -- der "
                   "bootende Rechner muss sie erreichen koennen"},
        {"name": "PXE_ASSETS", "wert": str(ASSETS_DIR),
         "wofuer": "Ablage der Abbilder"},
        {"name": "PXE_CATALOG", "wert": str(CATALOG_PATH),
         "wofuer": "Datei mit den Menuepunkten"},
        {"name": "PXE_DB", "wert": str(DB_PATH),
         "wofuer": "Datenbank"},
        {"name": "PXE_NFS_ROOT", "wert": uploads.NFS_ROOT,
         "wofuer": "Ist er gesetzt, werden grosse Live-Systeme ueber NFS "
                   "gestreamt statt in den Arbeitsspeicher geladen. Ohne "
                   "ihn nehmen sie den Weg ueber HTTP -- nur Linux Mint "
                   "kann das nicht und faellt dann aus dem Bootmenue"},
        {"name": "PXE_MENU_TIMEOUT", "wert": str(MENU_TIMEOUT),
         "wofuer": "Sekunden, die das Bootmenue auf eine Auswahl wartet (0 = unbegrenzt)"},
        {"name": "PXE_MENU_DEFAULT", "wert": MENU_DEFAULT,
         "wofuer": "was nach Ablauf startet"},
        {"name": "PXE_WOL_BROADCAST", "wert": wol.BROADCAST,
         "wofuer": "Rundrufadresse fuer die Weckpakete"},
        {"name": "PXE_KENNZEICHNUNG", "wert": KENNZEICHNUNG,
         "wofuer": "Steht hier ein Wort -- etwa \"Entwicklung\" --, faerbt "
                   "sich der Seitengrund und das Wort steht in der "
                   "Kopfzeile. Leer heisst: das ist die Produktion"},
    ]

    # Der abgewaehlte Haken schickt gar nichts -- deshalb darf der
    # Vorgabewert nicht "1" heissen. Bis zum 05.09.2026 tat er es, und
    # damit war der Haken wirkungslos: Abwaehlen sah aus wie ein leeres
    # Feld, und ein leeres Feld sah aus wie die Vorgabe.
    #
    # Was die beiden Faelle trennt, ist das Formular selbst: Es schickt
    # immer fehlerbericht=1 mit. Kommt der Aufruf von dort, heisst "kein
    # umgebung_mit" ausdruecklich nein; kommt er ohne, ist es der erste
    # Aufruf der Seite, und dann steht der Haken.
    mit_umgebung = (umgebung_mit == "1") if fehlerbericht else True

    netzlage = serveradresse.netzlage()

    return html.TemplateResponse(
        request,
        "einrichtung.html",
        _rahmen(
            aktiv="einrichtung",
            meldung=meldung,
            meldungsart=art,
            assets_dir=str(ASSETS_DIR),
            # Welcher Stand hier laeuft. Steht auf dieser Seite, weil
            # es dieselbe Frage ist wie bei den Ablageorten: woran bin
            # ich eigentlich dran, wenn etwas nicht stimmt?
            stand=versionsstand.auskunft(),
            orte=orte,
            einstellungen=umgebungswerte,
            # Der Blick ins Repository: was er zuletzt ergeben hat, und
            # wie oft er stattfindet. Die Auswahl steht in der Karte
            # Stand, nicht in der Karte Einstellungen -- die zeigt, was in
            # /etc/pxeweb.env steht, und daran dreht die Oberflaeche nicht.
            updatestand=updatewacht.stand(),
            updateauswahl=updatewacht.AUSWAHL,
            # Der Fehlerbericht entsteht erst auf Klick: Er kostet ein
            # halbes Dutzend Aufrufe nach draussen (dpkg, systemd,
            # journalctl), und die haben auf einer Seite nichts zu suchen,
            # die man oeffnet, um einen Pfad nachzusehen.
            bericht_text=(bericht.text(ASSETS_DIR, mit_umgebung=mit_umgebung,
                                       zusatz=_bericht_zusatz())
                          if fehlerbericht else ""),
            bericht_umgebung=mit_umgebung,
            bericht_adresse=KONTAKT,
            # Die Firewall: gemeldet, nicht angefasst. Der Server richtet
            # keine ein -- sie gehoert der Maschine, auf der er laeuft.
            # Warum die Karte nur meldet und nicht prueft, steht im Kopf
            # von webui/firewall.py.
            firewall=firewall.lage(),
            firewall_ports=firewall.PORTS,
            firewall_nfs=firewall.NFS_HINWEIS,
            firewall_zu=firewall.NICHT_OEFFNEN,
            # Wie weit die Abfrage vor dem Werksreset gekommen ist:
            # "" nichts, "wort" das Feld steht offen, "sicher" das Wort
            # stimmt und es fehlt nur noch die Bestaetigung.
            schritt=schritt if schritt in ("wort", "sicher", "ip") else "",
            losung=werkseinstellung.LOSUNG,
            # Was der Host gerade an Netz hat -- abgelesen, nie geschrieben.
            # Seit dem 27.08.2026 ist die Netzkonfiguration des Hosts Sache
            # des Betreibers; diese Karte zeigt sie nur noch an. Siehe
            # webui/serveradresse.py.
            netz=netzlage,
            # Weicht die tatsaechliche Adresse von der eingerichteten ab,
            # zeigen alle Boot-Skripte ins Leere. Hier steht der Befehl,
            # der es nachzieht.
            abweichung=serveradresse.abweichung(SERVER_HOST, netzlage),
            uebernehmen=UEBERNAHME_BEFEHL,
            jetzige_ip=SERVER_HOST,
        ),
    )


def _bericht_zusatz() -> list[tuple[str, str]]:
    """Was nur die Anwendung ueber sich weiss -- fuer den Block Umgebung.

    Getrennt von bericht.py, weil dort steht, was das SYSTEM sagt, und
    hier, was dieser Server anbietet. Das Modul soll nicht den Katalog
    kennen muessen.
    """
    systeme = _systeme()
    with db() as conn:
        rechner = conn.execute("SELECT count(*) AS n FROM clients").fetchone()["n"]
    return [
        ("Einträge", "%d erfasst, %d startbereit"
         % (len(systeme), sum(1 for e in systeme if e["ready"]))),
        ("Bekannte Rechner", str(rechner)),
        ("NFS-Export", uploads.NFS_ROOT or "nicht eingerichtet"),
        ("Windows-Freigabe", SMB_ROOT or "nicht eingerichtet"),
    ]


@app.get("/einrichtung/bericht.txt")
def bericht_datei(umgebung_mit: str = "1"):
    """Derselbe Bericht als Datei -- zum Anhaengen an eine Mail.

    Erzeugt beim Aufruf und direkt ausgeliefert: Es bleibt nichts auf dem
    Server liegen. Vor allem nichts unter der Ablage -- die liefert nginx
    offen aus, und im Bericht stehen Namen aus einem fremden Netz.
    """
    inhalt = bericht.text(ASSETS_DIR, mit_umgebung=(umgebung_mit == "1"),
                          zusatz=_bericht_zusatz())
    name = "marlei-boot-bericht-%s.txt" % datetime.now().strftime("%Y%m%d-%H%M")
    return PlainTextResponse(
        inhalt, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/einrichtung/updatepruefung")
def updatepruefung_setzen(tage: str = Form("")):
    """Wie oft der Server nachsieht, ob es eine neuere Fassung gibt.

    Die einzige Einstellung, die diese Seite schreibt -- und sie schreibt
    sie **nicht** nach /etc/pxeweb.env, sondern neben die Datenbank. Warum:
    siehe einstellungen.py. Sie wirkt sofort; der Waechter fragt
    stuendlich, ob er darf.
    """
    if updatewacht.gesperrt():
        # Die Umgebung setzt den Rahmen, die Oberflaeche waehlt darin --
        # ueberstimmen kann sie ihn nicht.
        return RedirectResponse(
            antwort("/einrichtung",
                    "Abgeschaltet über PXE_QUELLENWACHT — daran dreht die "
                    "Oberfläche nicht.", schlecht=True, marke="stand"),
            status_code=303)
    erlaubt = dict(updatewacht.AUSWAHL)
    try:
        wert = int(tage)
    except (TypeError, ValueError):
        wert = -1
    if wert not in erlaubt:
        return RedirectResponse(
            antwort("/einrichtung", "Das ist kein gültiger Zeitraum.",
                    schlecht=True, marke="stand"),
            status_code=303)
    einstellungen.setze("updatepruefung", wert)
    # Der gemerkte Befund gilt nicht mehr fuer die neue Einstellung: Wer
    # auf "nie" stellt, soll die blaue Karte nicht behalten, bis der
    # Waechter, den es nicht mehr gibt, sie wegnimmt.
    if not wert:
        updatewacht.vergiss()
    else:
        # Und wer sie einschaltet, soll nicht bis zum naechsten
        # Stundenschlag warten -- die Seite sieht dem Blick kurz zu, damit
        # sie sein Ergebnis schon tragen kann. Danach laeuft er notfalls
        # allein weiter; festhalten laesst sich die Seite nicht.
        updatewacht.starte_blick(warten=updatewacht.BEDENKZEIT)
    return RedirectResponse(
        antwort("/einrichtung",
                f"Nachgesehen wird jetzt {erlaubt[wert]}.", marke="stand"),
        status_code=303)


@app.post("/einrichtung/werkseinstellung")
def werkseinstellung_abfrage(wort: str = Form("")):
    """Der mittlere Schritt: Stimmt das getippte Wort?

    Geprueft wird hier und nicht im Browser. Eine Bestaetigung, die nur im
    JavaScript stattfindet, ist keine -- sie faellt weg, sobald jemand das
    Formular direkt abschickt.
    """
    if not werkseinstellung.gepruefte_losung(wort):
        return RedirectResponse(
            "/einrichtung?schritt=wort&meldung="
            + quote(f"Dafür muss dort „{werkseinstellung.LOSUNG}“ stehen."),
            status_code=303)
    return RedirectResponse("/einrichtung?schritt=sicher#ersteinrichtung",
                            status_code=303)


@app.post("/einrichtung/werkseinstellung/bestaetigen")
def werkseinstellung_ausfuehren(wort: str = Form("")):
    """Der letzte Schritt -- danach ist alles weg.

    Das Wort wird noch einmal verlangt und noch einmal geprueft. Der
    Schritt davor ist eine Seite, kein Schloss: Ohne diese Zeile genuegte
    ein einzelner Aufruf dieses Pfades, um einen Server zu leeren -- und
    die ganze Abfrage waere Zierde.
    """
    if not werkseinstellung.gepruefte_losung(wort):
        return RedirectResponse(
            antwort("/einrichtung", "Zurücksetzen abgebrochen — das Wort fehlte.",
                    schlecht=True),
            status_code=303)

    befund = werkseinstellung.zuruecksetzen(ASSETS_DIR, DB_PATH.parent, DB_PATH)

    # Was die Anwendung im Kopf hatte, gilt jetzt nicht mehr: Der Katalog
    # entstand aus Ausgabenlisten, die es nicht mehr gibt, und die
    # Datenbank ist eine Datei, die gerade geloescht wurde.
    _catalog_cache["mtime"] = None
    konfiguration.vergiss()
    quellen.vergiss_erreichbarkeit()
    db_anlegen()

    teile = []
    if befund["abbilder"]:
        teile.append(f"{len(befund['abbilder'])} Ablagen gelöscht")
    if befund["zustand"]:
        teile.append(f"{len(befund['zustand'])} Dateien mit gemerktem Zustand")
    meldung = ("Auf Werkseinstellung zurückgesetzt"
               + (" — " + ", ".join(teile) if teile else " — es lag nichts vor"))
    if befund["geblieben"]:
        # Nicht verschweigen, was nicht wegging: Ein Reset, der etwas
        # uebrig laesst und "fertig" meldet, ist schlimmer als einer, der
        # es sagt.
        meldung += (". Nicht wegzubekommen war: "
                    + ", ".join(befund["geblieben"][:5]))
    # Schlecht, wenn etwas liegen blieb: Der Reset ist dann nicht das,
    # was draufsteht, und das soll man sehen und nicht lesen muessen.
    return RedirectResponse(antwort("/einrichtung", meldung,
                                    schlecht=bool(befund["geblieben"]),
                                    marke="ersteinrichtung"),
                            status_code=303)


@app.get("/protokoll")
def protokoll_seite(request: Request, einheit: str = "dnsmasq", zeilen: int = 200):
    """Das Journal eines Dienstes -- was sonst "journalctl -u ..." zeigt."""
    if einheit not in journal.ERLAUBT:
        einheit = journal.ERLAUBT[0]
    ergebnis = journal.lies(einheit, zeilen)
    return html.TemplateResponse(
        request,
        "protokoll.html",
        _rahmen(
            aktiv="protokoll",
            einheit=einheit,
            einheiten=journal.ERLAUBT,
            zeilen=zeilen,
            protokoll=ergebnis["text"],
            hinweis=ergebnis["meldung"],
        ),
    )


@app.get("/protokoll.txt")
def protokoll_text(einheit: str = "dnsmasq", zeilen: int = 200) -> PlainTextResponse:
    """Dieselben Zeilen als reiner Text -- die Seite holt sie sich damit ab."""
    try:
        ergebnis = journal.lies(einheit, zeilen)
    except ValueError as fehler:
        raise HTTPException(status_code=400, detail=str(fehler))
    return PlainTextResponse(ergebnis["text"] or ergebnis["meldung"],
                             media_type="text/plain; charset=utf-8")


@app.get("/hilfe")
def hilfe_seite(request: Request):
    # Die Zugangsdaten der Freigabe stehen nur hier und nicht im Rahmen:
    # Gebraucht werden sie an genau einer Stelle, und was auf jeder Seite
    # mitlaeuft, sollte auch auf jeder Seite gebraucht werden.
    return html.TemplateResponse(request, "hilfe.html", _rahmen(
        aktiv="hilfe",
        smb={
            "da": bool(SMB_ROOT),
            "server": SERVER_HOST,
            "benutzer": SMB_BENUTZER,
            "passwort": SMB_PASSWORT,
        },
    ))


@app.get("/quellen")
def quellen_seite(request: Request, meldung: str = "", art: str = ""):
    """Woher die Systeme kommen: Adressen pflegen und Neues hereinholen.

    Die Karte "Hinzufuegen und nachladen" stand bis zum Umzug unter
    Systeme. Sie gehoert hierher: eine Adresse zu ersetzen und danach zu
    holen ist ein Vorgang, und er lief vorher ueber zwei Reiter.
    """
    systeme = _systeme()
    # Einmal je Seitenaufbau: welcher Ordner welchem Eintrag gehoert.
    orte = _eintragsorte(systeme)
    return html.TemplateResponse(
        request,
        "quellen.html",
        _rahmen(
            aktiv="quellen",
            meldung=meldung,
            meldungsart=art,
            quellen=quellen.alle(),
            # Der letzte Prüfstand je Quelle und die früher benutzten
            # Adressen -- damit die Ampel schon beim Öffnen leuchtet und
            # nicht erst, wenn jemand drückt.
            quellstand={q["name"]: quellen.stand(q["name"]).get("stand", {})
                        for q in quellen.alle()},
            quellverlauf={q["name"]: quellen.verlauf(q["name"])
                          for q in quellen.alle()},
            quellengruppen=_quellen_nach_gruppen(quellen.karten()),
            versionen=quellen.versionen(),
            eigene_datei=str(quellen.EIGEN),
            # Was auf welchem Weg hereingekommen ist. Genommen wird der
            # Katalogeintrag und nicht die Zustandsdatei: nur dort steht der
            # Name, den jemand vergeben hat.
            hochgeladen=[_mit_herkunft(e, orte.get(e["slug"])) for e in systeme
                         if e.get("upload") and not e["upload"].get("quelle")],
            geholt=[_mit_herkunft(e, orte.get(e["slug"])) for e in systeme
                    if e.get("upload") and e["upload"].get("quelle")],
            selbst=[_mit_herkunft(e, orte.get(e["slug"])) for e in systeme if e.get("eigen")],
            # Der Katalog: alles, was weder hochgeladen noch selbst
            # angelegt wurde. Mehrversionige Eintraege stehen hier einzeln
            # -- rocky-10 und rocky-9 sind zwei Menuepunkte mit eigenen
            # Dateien und deshalb zwei Karten.
            # Nach Gruppen sortiert, in derselben Folge wie das Bootmenue
            # und die Karten unter Systeme: die Werkzeuge stehen damit
            # unten, ohne dass es hier eine zweite Regel dafuer braucht.
            katalog=_katalogliste(
                [_mit_herkunft(e, orte.get(e["slug"])) for e in systeme
                 if not e.get("upload") and not e.get("eigen")]),
            karten=_quellen_karten(),
            assets_dir=str(ASSETS_DIR),
            # Je Karte, was auf ihrem Weg hereingekommen ist. Gerechnet mit
            # derselben Funktion wie die Zahl in der Eintragskarte und in
            # der Detailansicht auf Server Health -- die vier zusammen
            # ergeben deshalb genau die Zeile "n Eintraege zusammen" von
            # dort. Nicht "Abbilder gesamt": Darin stecken zusaetzlich die
            # verwaisten Ordner und Sonstiges, und beides gehoert zu keinem
            # dieser vier Wege.
            #
            # Bis zum 27.08.2026 stand unter Upload und Download dieselbe
            # Zahl: die ganze Ablage der selbst hereingeholten Abbilder,
            # egal auf welchem Weg. Zwei Karten mit derselben Zahl liest
            # man aber als Fehler.
            belegt={
                "hochgeladen": sum(_eintragsbelegung(e, orte.get(e["slug"]))
                                   for e in systeme
                                   if e.get("upload")
                                   and not e["upload"].get("quelle")),
                "geholt": sum(_eintragsbelegung(e, orte.get(e["slug"]))
                              for e in systeme
                              if e.get("upload") and e["upload"].get("quelle")),
                "selbst": sum(_eintragsbelegung(e, orte.get(e["slug"]))
                              for e in systeme if e.get("eigen")),
                "katalog": sum(_eintragsbelegung(e, orte.get(e["slug"]))
                               for e in systeme
                               if not e.get("upload") and not e.get("eigen")),
            },
            nfs_root=uploads.NFS_ROOT,
            bauarten=eigene.BAUARTEN,
            spiegel_liste=eigene.SPIEGEL,
            eigene_gruppen=eigene.GRUPPEN,
            sync=sync.zustand(),
        ),
    )


def _zugriff(eintrag: dict) -> str:
    """Woher der Client waehrend des Startens zieht.

    Bei einem Upload ist das eine festgestellte Tatsache: Beim Einlesen des
    Abbilds hat der Server entschieden, ob es per NFS eingehaengt oder in
    den Arbeitsspeicher geladen wird, und das steht in seiner eintrag.yaml.

    Bei einem Katalogeintrag stand hier bisher nur die Gruppe: alles unter
    Online-Installationen "aus dem Internet", alles andere "vom Server".
    Das stimmte zwar immer, war aber groeber als die Auskunft daneben --
    Mint haengt sein Dateisystem per NFS ein und Ubuntu Server laedt sein
    ganzes ISO in den Arbeitsspeicher (deshalb die etwa 6 GB RAM), und
    beide sagten schlicht "vom Server".

    Abgelesen wird es jetzt an der Befehlszeile, mit der der Eintrag
    startet -- dort steht es, weil der Client danach handelt:

        netboot=nfs, nfsroot=, ..._nfs_srv=   haengt ein
        url=${assets}/....iso                 laedt das Abbild herunter
        inst.repo=, install=, url= auf http   holt es aus dem Netz

    Damit gilt dieselbe Regel fuer selbst angelegte Eintraege, ohne dass
    dort etwas einzutragen waere. Passt nichts davon, bleibt es bei der
    Gruppe -- Debians netinst zum Beispiel traegt seinen Spiegel nicht in
    der Befehlszeile, sondern fragt danach.
    """
    upload = eintrag.get("upload") or {}
    if upload.get("weg") == "nfs":
        return "über NFS vom Server"
    if upload.get("weg") == "smb":
        return "über SMB vom Server"
    if upload.get("weg") == "ram":
        return "vom Server in den Arbeitsspeicher"

    befehl = eintrag.get("cmdline") or ""
    if "netboot=nfs" in befehl or "nfsroot=" in befehl or "_nfs_srv=" in befehl:
        return "über NFS vom Server"
    if "_http_srv=" in befehl:
        return "über HTTP vom Server"
    # live-boot holt sein Wurzeldateisystem einzeln ueber HTTP und legt es
    # in eine RAM-Disk -- der Weg, den GParted und Clonezilla ohne
    # NFS-Export nehmen. Nicht dasselbe wie ein ganzes ISO, aber fuer den
    # bootenden Rechner dieselbe Frage: Passt es in den Arbeitsspeicher?
    if re.search(r"fetch=[^ ]*\$\{assets\}", befehl):
        return "vom Server in den Arbeitsspeicher"
    # "${assets}" und "${srvip}" sind Platzhalter fuer diesen Server; sie
    # werden erst beim Bauen des Bootskripts ersetzt. In einem url= heisst
    # das: der Client laedt das ganze Abbild von hier, bevor er startet.
    if re.search(r"url=[^ ]*\$\{assets\}", befehl):
        return "vom Server in den Arbeitsspeicher"
    if re.search(r"(inst\.repo|install|url)=https?://", befehl):
        return "aus dem Internet"
    # Sonst steht nur fest, dass die Dateien von hier kommen -- wie, sagt
    # die Befehlszeile dann nicht.
    if "${assets}" in befehl or "${srvip}" in befehl:
        return "vom Server"
    if eintrag.get("category") == uploads.MIT_NETZ:
        return "aus dem Internet"
    return "vom Server"


def _mit_herkunft(eintrag: dict, ort: Path | None = None) -> dict:
    """Zwei Angaben ergaenzen: woher der Client zieht und wo es liegt.

    "Quelle" hat auf diesem Server drei Bedeutungen, und alle drei sind
    Antworten auf dieselbe Frage aus verschiedenen Richtungen:

      1. woher der Server seine Dateien hat        -- die vier Karten
      2. woher der Client sie waehrend der
         Installation zieht                        -- diese Spalte
      3. wo sie auf der Platte liegen              -- und diese

    Die erste gliedert die Seite, die anderen beiden gehoeren in die Zeile:
    sie sind Eigenschaften eines einzelnen Abbilds und liegen quer zu den
    Karten. Ein Upload kann per NFS eingehaengt werden, ein Katalogeintrag
    laedt aus dem Internet -- das steht in derselben Zeile, egal auf
    welchem Weg das Abbild hereinkam.
    """
    zugriff = _zugriff(eintrag)

    # Wo das Abbild liegt. Bei einem Upload und bei einem selbst angelegten
    # Eintrag ist das sein eigener Ordner -- und nicht der gemeinsame Pfad
    # seiner Startdateien: die stecken bei Ubuntu in "casper/", das Abbild
    # daneben. Und bei Windows haetten die Dateien gar keinen gemeinsamen
    # Ordner, weil wimboot aus einem anderen Verzeichnis dazukommt.
    # Genau der Ordner, den "Belegt" weiter unten zaehlt. Vorher stand hier
    # eine zweite Rechnung, und die beiden widersprachen sich: Bei einem
    # Upload mit entpacktem Abbild sagte die Zeile "<kennung>", die
    # Belegung zaehlte aber nur "<kennung>/casper". Wer beides las, musste
    # eine von beiden fuer falsch halten -- und beide waren es halb.
    pfade = required_assets(eintrag)
    if ort is not None:
        ablage = str(ort.relative_to(ASSETS_DIR)).replace(os.sep, "/")
    elif not pfade:
        ablage = ""
    elif len(pfade) == 1:
        ablage = pfade[0]
    else:
        gemeinsam = os.path.commonpath(pfade).replace(os.sep, "/")
        ablage = gemeinsam or ", ".join(sorted({p.split("/")[0] for p in pfade}))
    # Und die Dateien selbst -- die Frage "was liegt da eigentlich?"
    # beantwortete bisher nur die Uebersicht. Die Pfade stehen relativ zu
    # /srv/pxe/assets: bei Windows kommt wimboot aus einem anderen
    # Verzeichnis, deshalb bringt jede Datei ihren ganzen Pfad mit.
    dateien = [{"pfad": rel, "voll": str(ASSETS_DIR / rel),
                **konfiguration.datei(ASSETS_DIR / rel)}
               for rel in required_assets(eintrag)]
    # Was das Abbild ueber sich selbst sagt. Bei einem Upload steht es seit
    # dem Einlesen in seiner eintrag.yaml; bei einem Katalogeintrag wird es
    # von der Platte gelesen -- dieselbe Auskunft, dieselbe Zeile.
    # Dieselbe Auskunft, die auch das Feld darueber vorbelegt und ohne
    # eigenen Eintrag im Menue steht -- eine Regel, eine Stelle. Vorher
    # stand hier eine zweite Fassung, und die suchte an anderer Stelle als
    # die erste: Unter ubuntu/ fand sie das Abbild der Nachbarausgabe.
    beschreibung = _abgelesene_info(eintrag)

    # Was der Eintrag wirklich belegt -- nicht, wie gross die Datei war,
    # die einmal hereinkam. Bei einem ausgepackten Abbild ist die laengst
    # geloescht; bei einem Katalogeintrag gab es sie nie.
    belegt = _eintragsbelegung(eintrag, ort)

    return {**eintrag, "zugriff": zugriff, "ablage": ablage,
            "dateien": dateien,
            "beschreibung": beschreibung, "belegt": belegt,
            # Liegt ueberhaupt etwas da? "Dateien loeschen" bei einem
            # Eintrag, der noch nie geholt wurde, waere ein Knopf ins Leere.
            "dateien_da": any(d.get("da") for d in dateien)}


def _katalogliste(eintraege: list[dict]) -> dict[str, list[dict]]:
    """Die mitgelieferten Eintraege fuer die Karte -- Inaktives ans Ende.

    Was seine Dateien nicht hat, kann nicht gebootet werden und steht in
    keinem Menue. In der Liste dazwischen zu stehen hiess: Man las sich
    durch Eintraege, die es gar nicht gibt, um den einen zu finden, um den
    es geht. Jetzt stehen sie hinter einer eigenen Trennlinie.

    Die aktiven bleiben nach Gruppen geordnet, in der Folge des Bootmenues.
    Die inaktiven kommen ohne Gruppen: Es sind wenige, und die Frage bei
    ihnen ist nicht "wozu gehoert das", sondern "hole ich es".
    """
    aktiv = _nach_gruppen([e for e in eintraege if e["ready"]])
    ruhend = [e for e in eintraege if not e["ready"]]
    if ruhend:
        # Zuletzt eingehaengt, damit es zuletzt steht -- Woerterbuecher
        # behalten die Reihenfolge, in der eingetragen wurde.
        aktiv["Inaktiv"] = ruhend
    return aktiv


def _quellen_karten() -> list[dict]:
    """Die vier Karten in der geltenden Reihenfolge, mit ihrer Stelle."""
    namen = [name for name, _, _ in QUELLEN_KARTEN]
    vorlagen = {name: v for name, v, _ in QUELLEN_KARTEN}
    hilfen = {name: h for name, _, h in QUELLEN_KARTEN}
    stellen = gruppen.stand(namen)
    return [{"name": name, "vorlage": vorlagen[name], "hilfe": hilfen[name],
             "stelle": stellen[name]}
            for name in gruppen.sortiere(namen)]


@app.post("/quellen/{name}/holen")
def quelle_holen(name: str, version: str = Form("")):
    """Die Dateien dieser Quelle holen -- auf Wunsch nur eine Ausgabe.

    Bisher fuehrte der Weg dorthin ueber eine Ankreuzliste weiter oben,
    mit anderen Namen als in der Karte ("gparted" statt
    "gparted-live-1-8-1-3"), und sie holte immer alle Ausgaben auf einmal.
    Wer eine neue erproben will, will aber nicht zugleich die beiden alten
    nachgeladen bekommen.
    """
    komponente = quellen.KOMPONENTE.get(name)
    if not komponente:
        raise HTTPException(status_code=400,
                            detail="Zu dieser Quelle gibt es nichts zu holen.")
    version = version.strip()
    if version and not quellen.VERSION_RE.match(version):
        raise HTTPException(status_code=400, detail="Ungueltige Ausgabe")
    auftrag = f"{komponente}:{version}" if version else komponente
    try:
        sync.starte([auftrag], {"PXE_ASSETS": str(ASSETS_DIR)})
    except ValueError as fehler:
        return RedirectResponse(
            antwort("/quellen", str(fehler), schlecht=True, marke="katalog"),
            status_code=303)
    return RedirectResponse(
        antwort("/quellen", "Wird geholt: " + auftrag, marke="katalog"),
        status_code=303)


@app.post("/quellen/{name}/durchleuchten")
def quelle_durchleuchten(name: str):
    """Die drei Fragen zu einer Quelle auf einmal -- siehe durchleuchten().

    POST und nicht GET, obwohl nichts geaendert wird, was der Benutzer
    eingetragen hat: Der Befund wird festgehalten, damit die Ampel beim
    naechsten Oeffnen schon leuchtet. Eine Anfrage, die schreibt, soll
    auch so aussehen.
    """
    try:
        # Findet die Pruefung eine neuere Ausgabe, wird sie eingetragen --
        # die Adresse entsteht aus dem Muster. Geholt wird nichts.
        return JSONResponse(quellen.durchleuchten(name, aufnehmen=True))
    except ValueError as fehler:
        raise HTTPException(status_code=400, detail=str(fehler))


# Muss vor "/quellen/{name}" stehen: sonst faengt dessen Platzhalter den
# Pfad ab und "speichern" landete als Name einer Download-Quelle.
@app.post("/quellen/speichern")
async def quellen_speichern(request: Request):
    """Was auf der Seite steht: die Reihenfolge der Karten und die Namen.

    Der Name eines Abbilds steht hier bei seiner Herkunft und unter Systeme
    in der Liste -- es ist derselbe. Beide Seiten benutzen dafuer denselben
    Helfer.

    Bei der Reihenfolge gilt dieselbe Regel wie unter Systeme: eine
    angefasste Zahl ist ein Wunsch, eine stehengelassene nur der Stand der
    Dinge -- und ein Wunsch gewinnt. Sonst geschaehe nichts Sichtbares,
    waehrend oben "gespeichert" steht.
    """
    formular = await request.form()
    aktuell = [karte["name"] for karte in _quellen_karten()]
    vorher = gruppen.stand(aktuell)

    eigene_namen, fehler = _namen_aus_formular(formular, _systeme())
    werte: dict[str, int] = {}
    for schluessel, roh in formular.items():
        if not schluessel.startswith("folge:"):
            continue
        name = schluessel[len("folge:"):]
        if name not in aktuell:
            continue
        try:
            werte[name] = gruppen.pruefe(str(roh))
        except ValueError as grund:
            fehler.append(f"{name}: {grund}")

    if fehler:
        return RedirectResponse(
            antwort("/quellen", "Nicht gespeichert. " + " ".join(fehler),
                    schlecht=True),
            status_code=303)

    if werte:
        folge = sorted(werte, key=lambda name: (
            werte[name],
            0 if werte[name] != vorher.get(name) else 1,
            aktuell.index(name),
        ))
        # Die Stellen der anderen Seite bleiben stehen: dieselbe Datei
        # traegt auch die Reihenfolge der Gruppen unter Systeme.
        alle = gruppen.zahlen()
        alle.update({name: stelle for stelle, name in enumerate(folge, start=1)})
        gruppen.setze(alle)

    bezeichnungen.setze(eigene_namen)
    return RedirectResponse(
        antwort("/quellen", "Gespeichert."), status_code=303)


@app.post("/quellen/ausgabe")
def quelle_ausgabe(adresse: str = Form(...), version: str = Form(...),
                   url: str = Form(""), war_version: str = Form("")):
    """Eine einzelne Ausgabe eintragen -- Nummer und Adresse zusammen.

    Beides gehoert in einen Vorgang: Eine Ausgabe ohne Adresse liesse sich
    nicht holen, eine Adresse ohne Eintrag in der Liste bliebe wirkungslos.

    Gespeichert wird die Adresse nur, wenn sie vom Muster abweicht. Solange
    das Muster stimmt, bleibt die Datei schlank; sobald ein Distributor
    seine Struktur aendert, traegt man hier die richtige ein und die
    anderen Ausgaben bleiben unberuehrt.
    """
    listenname = quellen.VERSIONSLISTE.get(adresse)
    if not listenname:
        raise HTTPException(status_code=400, detail="Keine mehrversionige Quelle")

    version = version.strip()
    if not quellen.VERSION_RE.match(version):
        return RedirectResponse(
            antwort("/quellen", f"„{version}“ ist keine Ausgabe.",
                    schlecht=True, marke="katalog"),
            status_code=303)

    ausgaben = quellen.liste(listenname)
    if war_version and war_version in ausgaben:
        # Umbenannt: die alte Stelle behalten, damit die Reihenfolge bleibt.
        ausgaben[ausgaben.index(war_version)] = version
        quellen.loesche_ausgabe(adresse, war_version)
    elif version not in ausgaben:
        # Neu: nach vorn, die Liste steht neueste zuerst.
        ausgaben.insert(0, version)

    try:
        quellen.setze(listenname, " ".join(dict.fromkeys(ausgaben)))
        if url.strip() and url.strip() != quellen.aus_muster(adresse, version):
            quellen.setze_ausgabe(adresse, version, url.strip())
        else:
            quellen.loesche_ausgabe(adresse, version)
    except ValueError as fehler:
        return RedirectResponse(
            antwort("/quellen", str(fehler), schlecht=True, marke="katalog"),
            status_code=303)

    return RedirectResponse(
        antwort("/quellen", f"Ausgabe {version} gespeichert.", marke="katalog"),
        status_code=303)


@app.get("/quellen/ausgabe/neuere")
def quelle_neuere(adresse: str = ""):
    """Beim Anbieter nachsehen, welche Ausgaben es gibt.

    Gelesen wird ein Verzeichnis oder eine Projektseite -- geholt wird
    nichts und eingetragen erst recht nicht. Was der Server findet, ist
    ein Vorschlag; ob eine Ausgabe taugt, entscheidet nicht ihre Nummer.
    """
    if adresse not in quellen.VERSIONSLISTE:
        raise HTTPException(status_code=400, detail="Keine mehrversionige Quelle")
    return JSONResponse(quellen.neuere_ausgaben(adresse))


@app.get("/quellen/ausgabe/pruefen")
def quelle_ausgabe_pruefen(adresse: str = "", version: str = "", url: str = ""):
    """Eine einzelne Ausgabe pruefen -- ein Byte, wie bei den Adressen."""
    ziel = url.strip() or quellen.fuer_ausgabe(adresse, version)
    return JSONResponse(quellen.pruefe(ziel, adresse))


@app.post("/quellen/{name}")
def quelle_setzen(name: str, url: str = Form(...)):
    try:
        quellen.setze(name, url)
    except ValueError as fehler:
        return RedirectResponse(
            antwort("/quellen", str(fehler), schlecht=True, marke="katalog"),
            status_code=303)
    return RedirectResponse(
        antwort("/quellen", f"{name} gespeichert.", marke="katalog"),
        status_code=303)


@app.post("/quellen/{name}/zuruecksetzen")
def quelle_zuruecksetzen(name: str):
    quellen.zuruecksetzen(name)
    return RedirectResponse(
        antwort("/quellen", f"{name} steht wieder auf der Vorgabe."),
        status_code=303,
    )


@app.get("/quellen/{name}/pruefen")
def quelle_pruefen(name: str):
    """Nachsehen, ob die Adresse noch gilt -- ohne die Datei zu laden.

    Die Seite ruft das je Quelle einzeln auf, damit die Ampel nacheinander
    umspringt statt alle zusammen nach einer halben Minute.
    """
    passende = [q for q in quellen.alle() if q["name"] == name]
    if not passende:
        raise HTTPException(status_code=404, detail="Unbekannte Quelle")
    ergebnis = quellen.pruefe(passende[0]["url"], name)
    ergebnis["name"] = name
    return JSONResponse(ergebnis)


# --------------------------------------------------------------------------
# Installationsprotokolle der Clients
# --------------------------------------------------------------------------


@app.get("/logs.sh")
def log_skript() -> PlainTextResponse:
    """Sammelskript, das im Live-System des Clients laeuft.

    Absichtlich ein Skript zum Herunterladen und nicht eine Anleitung zum
    Abtippen: die Zeile steht in der Weboberflaeche und muss im Live-System
    von Hand eingegeben werden -- je kuerzer, desto besser.
    """
    body = ipxe.get_template("logs.sh.j2").render(base=BASE_URL)
    return PlainTextResponse(body, media_type="text/x-shellscript; charset=utf-8")


@app.put("/logs/{mac}/{dateiname}")
async def log_annehmen(mac: str, dateiname: str, request: Request):
    """Nimmt ein Protokollpaket entgegen -- als roher Datenstrom wie beim ISO.

    Kein Formular und keine Anmeldung: das laeuft in einem Live-System, das
    ausser einer Netzwerkverbindung nichts hat. Der Schutz besteht darin,
    dass nur ins eigene LAN geliefert werden kann, jede Datei begrenzt ist
    und je Rechner nur eine feste Zahl Pakete liegen bleibt.
    """
    normalised = normalise_mac(mac)
    if not normalised:
        raise HTTPException(status_code=400, detail="Ungueltige MAC-Adresse")

    ziel = logs.zielpfad(normalised, dateiname)
    geschrieben = 0
    try:
        with ziel.open("wb") as raus:
            async for brocken in request.stream():
                geschrieben += len(brocken)
                if geschrieben > logs.MAX_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Groesser als {logs.MAX_BYTES // 1048576} MB.",
                    )
                raus.write(brocken)
    except Exception:
        # Abgebrochen oder zu gross: keine halbe Datei stehen lassen.
        ziel.unlink(missing_ok=True)
        raise

    if geschrieben == 0:
        ziel.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Es kamen keine Daten an.")

    logs.aufraeumen(normalised)

    # Ein Rechner, der ein Protokoll schickt, gehoert in die Liste -- auch
    # wenn er bisher nicht auffiel.
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO clients (mac) VALUES (?)", (normalised,))

    return JSONResponse(
        {"mac": normalised, "datei": ziel.name, "bytes": geschrieben}, status_code=201
    )


@app.get("/logs/{mac}/{datei}")
def log_holen(mac: str, datei: str):
    normalised = normalise_mac(mac)
    if not normalised:
        raise HTTPException(status_code=400, detail="Ungueltige MAC-Adresse")
    ziel = logs.pfad(normalised, datei)
    if ziel is None:
        raise HTTPException(status_code=404, detail="Kein solches Protokoll.")
    return FileResponse(ziel, filename=ziel.name, media_type="application/octet-stream")


@app.post("/logs/{mac}/{datei}/delete")
def log_loeschen(mac: str, datei: str):
    normalised = normalise_mac(mac)
    if not normalised:
        raise HTTPException(status_code=400, detail="Ungueltige MAC-Adresse")
    logs.loesche(normalised, datei)
    return RedirectResponse("/clients#installationsprotokolle", status_code=303)


@app.get("/health")
def health():
    entries = load_catalog()
    return {
        "status": "ok",
        "base_url": BASE_URL,
        "entries_total": len(entries),
        "entries_ready": sum(1 for e in entries if entry_ready(e)),
        "uploads": len(uploads.alle()),
        "assets_dir": str(ASSETS_DIR),
        # Leer heisst: kein NFS eingerichtet, grosse Live-Abbilder muessen
        # dann komplett in den Arbeitsspeicher des Clients passen.
        "nfs_root": uploads.NFS_ROOT,
    }

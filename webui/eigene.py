"""
Selbst angelegte Netz-Installer -- Kernel und Initrd von einer Adresse.

Fuer alles, was es nicht als ISO gibt: Debian-artige Netinstaller (Debian,
Kali, Devuan), Anaconda (Fedora, Rocky, Alma) und linuxrc (openSUSE). Dort
liegen nur Kernel und Initrd auf einem Spiegel, den Rest holt sich der
Installer waehrend des Laufs.

Die Schwierigkeit dabei ist nie der Download, sondern die
Kernel-Kommandozeile -- man muss wissen, dass Anaconda "inst.repo=" will
und linuxrc "install=". Genau dieses Wissen steckt schon in isoscan.py, und
hier steht es als Bauart zur Auswahl: wer die Bauart kennt, braucht nur
noch zwei Adressen einzutippen.

Abgelegt wird wie bei den Uploads neben den Dateien, unter
/srv/pxe/assets/<kennung>/. Nicht in catalog.yaml: die liegt im
Projektordner, und install.sh spiegelt den mit "rsync --delete" -- ein dort
eingetragener Eintrag waere beim naechsten Update ohne Warnung weg.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

ASSETS_DIR = Path(os.environ.get("PXE_ASSETS", "/srv/pxe/assets"))
# Wie bei den Uploads: ein Eintrag, ein Verzeichnis, benannt nach seiner
# Kennung. Das Praefix "netz-" haelt sie von den mitgelieferten Eintraegen
# auseinander, der Behaelter "eigene/" wird dafuer nicht gebraucht.
EIGEN_PRAEFIX = "netz-"

ONLINE = "Online-Installationen"
OFFLINE = "Offline-Installationen"
WERKZEUG = "Rettung und Wartung"

GRUPPEN = [ONLINE, OFFLINE, WERKZEUG]

# Bei Debian und seinen Abkoemmlingen liegt der netboot-Installer immer an
# derselben Stelle unterhalb des Spiegels. Man muss also nicht suchen, nur
# Spiegel und Suite kennen -- den Rest setzt der Server zusammen.
DEBIAN_PFAD = ("{spiegel}/dists/{suite}/main/installer-amd64/current"
               "/images/netboot/debian-installer/amd64")

# Bekannte Spiegel als Vorschlag. Ubuntu fehlt mit Absicht: dort wurde der
# Debian-Installer aufgegeben, deshalb steht im Katalog die live-server-ISO.
SPIEGEL = [
    ("Debian stable", "http://deb.debian.org/debian", "trixie"),
    ("Debian testing", "http://deb.debian.org/debian", "forky"),
    ("Kali Linux", "http://http.kali.org/kali", "kali-rolling"),
    ("Devuan", "http://deb.devuan.org/merged", "daedalus"),
]

# Bauarten -- je Familie: welche Dateien geholt werden, wie sie beim Ablegen
# heissen, und was in die Kommandozeile gehoert. Dieselben vier Familien,
# die auch isoscan.py in einem Abbild wiedererkennt.
BAUARTEN = {
    "debian": {
        "titel": "Debian-Abkoemmling (Debian, Kali, Devuan)",
        "felder": ["spiegel", "suite"],
        "dateien": [("linux", "linux"), ("initrd.gz", "initrd.gz")],
        "cmdline": "vga=788",
        "quelle_noetig": False,
        "hinweis": "Nur Spiegel und Suite -- den langen Pfad zum "
                   "netboot-Installer setzt der Server selbst zusammen, er ist "
                   "bei allen Abkoemmlingen derselbe.",
        "beispiel": "",
    },
    "anaconda": {
        "felder": ["basis", "quelle"],
        "titel": "Anaconda (Fedora, Rocky, AlmaLinux, CentOS)",
        "dateien": [("vmlinuz", "vmlinuz"), ("initrd.img", "initrd.img")],
        "cmdline": "inst.repo={quelle} ip=dhcp",
        "quelle_noetig": True,
        "hinweis": "Basisadresse des pxeboot-Verzeichnisses. Die Paketquelle ist "
                   "das os/-Verzeichnis derselben Ausgabe.",
        "beispiel": "https://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os/"
                    "images/pxeboot",
    },
    "linuxrc": {
        "felder": ["basis", "quelle"],
        "titel": "linuxrc (openSUSE, SLE)",
        "dateien": [("linux", "linux"), ("initrd", "initrd")],
        "cmdline": "install={quelle} netsetup=dhcp",
        "quelle_noetig": True,
        "hinweis": "Basisadresse des loader-Verzeichnisses. Die Paketquelle ist "
                   "das repo/oss/-Verzeichnis.",
        "beispiel": "https://download.opensuse.org/tumbleweed/repo/oss/boot/"
                    "x86_64/loader",
    },
    "frei": {
        "felder": ["kernel_url", "initrd_url", "cmdline"],
        "titel": "Frei -- Adressen und Kommandozeile selbst angeben",
        "dateien": [],
        "cmdline": "",
        "quelle_noetig": False,
        "hinweis": "Fuer alles Uebrige. Kernel- und Initrd-Adresse einzeln "
                   "angeben; die Kommandozeile musst du selbst kennen.",
        "beispiel": "",
    },
}

# Kernel und Initrd liegen im zweistelligen Megabyte-Bereich. Alles darueber
# ist keines von beidem -- vermutlich ein versehentlich verlinktes Abbild.
MAX_BYTES = 200 * 1024 * 1024


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def kennung_fuer(name: str, version: str = "") -> str:
    """Eindeutige Kennung, abgeleitet vom Namen -- und von der Ausgabe.

    Das Praefix "netz-" haelt selbst angelegte Eintraege von den eingebauten
    und von den hochgeladenen ("iso-") getrennt -- so kann nichts kollidieren.

    Die Ausgabe gehoert mit hinein, weil sie zur Identitaet gehoert: Zwei
    Ausgabe eines Systems sind zwei Eintraege mit eigenen Dateien, und ein
    Eintrag heisst wie sein Verzeichnis. Genauso liegen die mitgelieferten
    mehrversionigen da -- "gparted-live-1-8-1-3" neben seinem Nachbarn.
    """
    stamm = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    grund = "netz-" + (stamm or "eintrag")
    if version:
        grund += "-" + re.sub(r"[^a-z0-9]+", "-", version.lower()).strip("-")
    kennung, zaehler = grund, 2
    while (ASSETS_DIR / kennung).exists():
        kennung = grund + "-" + str(zaehler)
        zaehler += 1
    return kennung


def verzeichnis(kennung: str) -> Path:
    if not re.fullmatch(r"netz-[a-z0-9-]{1,60}", kennung):
        raise ValueError("Ungueltige Kennung: " + kennung)
    return ASSETS_DIR / kennung


def _pruefe_url(url: str, was: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ValueError(was + ": nur http:// und https:// sind erlaubt.")
    if any(z in url for z in (" ", chr(34), chr(92), "\n")) or len(url) > 1000:
        raise ValueError(was + ": das sieht nicht wie eine Adresse aus.")
    return url


def basis_fuer(bauart: str, basis: str = "", spiegel: str = "", suite: str = "") -> str:
    """Die Basisadresse, unter der Kernel und Initrd liegen.

    Bei Debian-Abkoemmlingen wird sie aus Spiegel und Suite gebaut; sonst
    ist sie direkt angegeben.
    """
    if bauart == "debian":
        spiegel = _pruefe_url(spiegel, "Spiegel")
        suite = (suite or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,40}", suite):
            raise ValueError("Suite: nur Buchstaben, Ziffern, Punkt und Strich.")
        return DEBIAN_PFAD.format(spiegel=spiegel, suite=suite)
    return _pruefe_url(basis, "Basisadresse")


def adressen_fuer(bauart: str, basis: str = "", spiegel: str = "", suite: str = "",
                  kernel_url: str = "", initrd_url: str = "") -> list:
    """Welche Dateien geholt wuerden -- (Adresse, Ablagename) je Datei."""
    if bauart not in BAUARTEN:
        raise ValueError("Unbekannte Bauart: " + bauart)
    if bauart == "frei":
        return [(_pruefe_url(kernel_url, "Kernel"), "linux"),
                (_pruefe_url(initrd_url, "Initrd"), "initrd.gz")]
    wurzel = basis_fuer(bauart, basis, spiegel, suite)
    return [(wurzel + "/" + dort, hier) for dort, hier in BAUARTEN[bauart]["dateien"]]


def pruefe(bauart: str, **felder) -> dict:
    """Nachsehen, ob die Dateien wirklich dort liegen -- ohne sie zu laden."""
    import quellen                                  # nur hier gebraucht

    try:
        holen = adressen_fuer(bauart, **{k: v for k, v in felder.items()
                                         if k in ("basis", "spiegel", "suite",
                                                  "kernel_url", "initrd_url")})
    except ValueError as fehler:
        return {"ok": False, "dateien": [], "meldung": str(fehler)}

    ergebnisse = []
    for url, _ in holen:
        befund = quellen.pruefe(url)
        ergebnisse.append({"url": url, **befund})
    return {
        "ok": all(e.get("ok") for e in ergebnisse),
        "dateien": ergebnisse,
        "meldung": "",
    }


def ausgabe_dazu(slug: str, version: str) -> str:
    """Eine weitere Ausgabe neben einen vorhandenen Eintrag stellen.

    Der Waechter meldet, dass es beim Anbieter etwas Neueres gibt --
    ohne diesen Weg waere das eine Sackgasse: Man muesste die Karte
    "Custom" noch einmal ausfuellen, mit denselben Angaben, nur einer
    anderen Nummer. Alles dafuer steht schon in der eintrag.yaml.

    Angelegt wird ein Geschwister, kein Ersatz. Die vorhandene Ausgabe
    bleibt, wie sie ist: Solange Rechner mit ihr laufen, soll ihr
    Installationsmedium verfuegbar bleiben -- dieselbe Ueberlegung wie bei
    den mitgelieferten mehrversionigen Systemen.
    """
    daten = lies(slug)
    if not daten:
        raise ValueError("Unbekannte Kennung: " + str(slug))
    muster = daten.get("muster") or ""
    if "{version}" not in muster:
        raise ValueError("Dieser Eintrag hat keine Ausgabe in seiner Adresse -- "
                         "eine weitere laesst sich daraus nicht ableiten.")
    version = (version or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", version):
        raise ValueError("Keine gueltige Ausgabe.")

    # Aeltere Eintraege haben noch keine Vorlage -- sie entstanden, bevor es
    # sie gab. Dann traegt das Muster die Adresse, und mehr wird auch nicht
    # gebraucht: Eine Bauart ohne Paketquelle kommt damit aus.
    vorlage = daten.get("vorlage") or {"basis": muster}
    return anlegen(daten.get("bauart", ""), daten.get("name", ""),
                   daten.get("gruppe", ""),
                   beschreibung=daten.get("beschreibung", ""),
                   muster=muster, version=version, **vorlage)


def anlegen_mehrere(bauart: str, name: str, gruppe: str, muster: str,
                    versionen: list[str], **felder) -> list[str]:
    """Aus einem Muster je Ausgabe einen eigenen Eintrag machen.

    Warum je Ausgabe ein eigener und nicht einer mit einer Liste darin:
    Jede Ausgabe hat eigene Dateien, belegt eigenen Platz und kann einzeln
    fehlschlagen, geholt oder geloescht werden. Ein Eintrag, der drei
    Ausgaben zugleich waere, muesste all das dreifach mit sich fuehren --
    und im Bootmenue stuende trotzdem dreimal etwas. So machen es die
    mitgelieferten mehrversionigen Systeme auch.

    Eingesetzt wird die Ausgabe hier nicht: Das tut anlegen() fuer sich
    selbst. Bis August 2026 geschah es hier, und dabei blieb die
    Paketquelle stehen -- drei Ausgaben mit drei Kerneln, aber alle drei
    mit dem inst.repo= der zuerst eingetippten. Wer eine Stelle vergisst,
    baut genau so einen Fehler; deshalb gibt es die Stelle nur noch einmal.
    """
    if "{version}" not in (muster or ""):
        raise ValueError("Ohne Ausgabe in der Adresse gibt es nichts zu vervielfachen.")
    sauber = []
    for version in versionen:
        version = (version or "").strip()
        # Dieselbe Form wie bei den eingetragenen Ausgaben der mitgelieferten
        # Quellen -- was dort nicht durchgeht, soll hier nicht hereinkommen.
        if (version and version not in sauber
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", version)):
            sauber.append(version)
    if not sauber:
        raise ValueError("Keine gueltige Ausgabe angegeben.")

    if not any(felder.get(f) for f in ("basis", "kernel_url", "spiegel")):
        felder = {**felder, "basis": muster}
    return [anlegen(bauart, name, gruppe, muster=muster, version=v, **felder)
            for v in sauber]


def anlegen(bauart: str, name: str, gruppe: str, basis: str = "", quelle: str = "",
            kernel_url: str = "", initrd_url: str = "", cmdline: str = "",
            beschreibung: str = "", spiegel: str = "", suite: str = "",
            muster: str = "", version: str = "") -> str:
    """Eintrag anlegen und die Dateien im Hintergrund holen."""
    if bauart not in BAUARTEN:
        raise ValueError("Unbekannte Bauart: " + bauart)
    art = BAUARTEN[bauart]

    name = (name or "").strip()
    if not 3 <= len(name) <= 80:
        raise ValueError("Name: bitte zwischen 3 und 80 Zeichen.")
    if gruppe not in GRUPPEN:
        raise ValueError("Unbekannte Gruppe.")

    # Die Vorlage, so wie sie hereinkam -- mit {version} darin, wenn dieser
    # Eintrag zu einer Reihe gehoert. Aufgehoben wird sie, damit spaeter
    # eine weitere Ausgabe daneben entstehen kann, ohne dass jemand alles
    # noch einmal eintippt: Der Waechter meldet sie, und ein Knopf an der
    # Karte legt sie an.
    vorlage = {"basis": basis, "spiegel": spiegel, "suite": suite,
               "kernel_url": kernel_url, "initrd_url": initrd_url,
               "quelle": quelle, "cmdline": cmdline}

    # Und ab hier gilt die Ausgabe dieses einen Eintrags. An EINER Stelle,
    # fuer alle Felder: Die Paketquelle gehoert genauso dazu wie die
    # Kerneladresse -- ein Kernel aus 3.23 mit dem Paketdepot von 3.21
    # installiert Falsches, und zwar ohne Fehlermeldung.
    def fuer_diese(wert: str) -> str:
        return wert.replace("{version}", version) if version and wert else wert

    basis, spiegel = fuer_diese(basis), fuer_diese(spiegel)
    kernel_url, initrd_url = fuer_diese(kernel_url), fuer_diese(initrd_url)
    quelle, cmdline = fuer_diese(quelle), fuer_diese(cmdline)

    holen = adressen_fuer(bauart, basis=basis, spiegel=spiegel, suite=suite,
                          kernel_url=kernel_url, initrd_url=initrd_url)
    if bauart == "frei":
        zeile = (cmdline or "").strip()
    else:
        zeile = art["cmdline"]
        if art["quelle_noetig"]:
            zeile = zeile.replace("{quelle}", _pruefe_url(quelle, "Paketquelle"))

    kennung = kennung_fuer(name, version)
    ordner = verzeichnis(kennung)
    ordner.mkdir(parents=True, exist_ok=True)

    daten = {
        "slug": kennung,
        "name": name,
        "beschreibung": (beschreibung or "").strip()[:120],
        "bauart": bauart,
        "gruppe": gruppe,
        "cmdline": zeile,
        # Die Ausgabe steht getrennt vom Namen, wie bei den mitgelieferten
        # Eintraegen: Der Name gehoert dem System, die Ausgabe dieser
        # Fassung davon. Zusammengeschrieben liessen sie sich spaeter nicht
        # mehr trennen -- und im Bootmenue haette jede Ausgabe einen
        # eigenen, leicht anderen Namen.
        "version": version,
        # Woraus diese Adresse entstanden ist. Ohne das Muster laesst sich
        # nicht fragen, ob es beim Anbieter etwas Neueres gibt.
        "muster": muster,
        # Und womit sie gebaut wurde -- damit eine weitere Ausgabe entstehen
        # kann, ohne dass jemand die Felder noch einmal ausfuellt.
        "vorlage": vorlage,
        "angelegt": _jetzt(),
        "status": "laedt",
        "meldung": "",
        "dateien": [ziel for _, ziel in holen],
        "adressen": [url for url, _ in holen],
    }
    _schreib(kennung, daten)
    threading.Thread(target=_hole, args=(kennung, holen), daemon=True).start()
    return kennung


def _schreib(kennung: str, daten: dict) -> None:
    ziel = verzeichnis(kennung) / "eintrag.yaml"
    # Erst daneben schreiben, dann umbenennen -- sonst liest jemand eine
    # halbe Datei, waehrend im Hintergrund noch geladen wird.
    vorlaeufig = ziel.with_suffix(".yaml.neu")
    with vorlaeufig.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(daten, fh, allow_unicode=True, sort_keys=False)
    _ersetze(vorlaeufig, ziel)


def _ersetze(vorlaeufig: Path, ziel: Path) -> None:
    """Umbenennen, notfalls mit ein paar Anlaeufen.

    Waehrend im Hintergrund geladen wird, liest die Weboberflaeche dieselbe
    Datei. Auf manchen Systemen -- Windows etwa -- scheitert das Umbenennen,
    solange noch jemand hineinschaut. Ein paar Millisekunden spaeter geht es.
    """
    for versuch in range(10):
        try:
            vorlaeufig.replace(ziel)
            return
        except OSError:
            if versuch == 9:
                raise
            time.sleep(0.05)


def lies(kennung: str) -> dict | None:
    """Den Zustand einlesen, notfalls mit ein paar Anlaeufen.

    Waehrend im Hintergrund die neue Fassung an ihre Stelle geschoben wird,
    laesst sich die Datei auf manchen Systemen fuer einen Wimpernschlag
    nicht oeffnen. Gleich aufzugeben hiesse, dass der Eintrag fuer einen
    Seitenaufruf aus der Liste verschwindet.
    """
    pfad = verzeichnis(kennung) / "eintrag.yaml"
    for versuch in range(5):
        try:
            with pfad.open(encoding="utf-8") as fh:
                return yaml.safe_load(fh) or None
        except FileNotFoundError:
            return None
        except (ValueError, yaml.YAMLError):
            return None
        except OSError:
            time.sleep(0.05)
    return None


def _hole(kennung: str, holen: list) -> None:
    daten = lies(kennung) or {}
    ordner = verzeichnis(kennung)
    try:
        for url, ziel in holen:
            anfrage = urllib.request.Request(url, headers={"User-Agent": "pxeweb/1.0"})
            with urllib.request.urlopen(anfrage, timeout=60) as antwort:
                geladen = 0
                with (ordner / ziel).open("wb") as raus:
                    while True:
                        brocken = antwort.read(1024 * 256)
                        if not brocken:
                            break
                        geladen += len(brocken)
                        if geladen > MAX_BYTES:
                            raise ValueError(
                                ziel + " ist groesser als "
                                + str(MAX_BYTES // 1048576)
                                + " MB -- das ist weder Kernel noch Initrd.")
                        raus.write(brocken)
                if geladen == 0:
                    raise ValueError(ziel + ": es kamen keine Daten an.")
            daten["meldung"] = ziel + " geholt"
            _schreib(kennung, daten)
    except urllib.error.HTTPError as fehler:
        daten.update(status="fehler",
                     meldung="Der Server antwortet mit "
                             + str(fehler.code) + " " + str(fehler.reason) + ".")
        _schreib(kennung, daten)
        return
    except Exception as fehler:
        daten.update(status="fehler", meldung=str(fehler))
        _schreib(kennung, daten)
        return

    daten.update(status="bereit", meldung="")
    _schreib(kennung, daten)


def verzeichnisse() -> list[Path]:
    """Die Verzeichnisse der selbst angelegten Eintraege."""
    try:
        return sorted((p for p in ASSETS_DIR.iterdir()
                       if p.is_dir() and p.name.startswith(EIGEN_PRAEFIX)),
                      key=lambda p: p.name)
    except OSError:
        return []


def alle() -> list[dict]:
    """Alle selbst angelegten Eintraege, neueste zuerst."""
    liste = []
    for ordner in verzeichnisse():
        daten = lies(ordner.name)
        if daten:
            daten.setdefault("slug", ordner.name)
            liste.append(daten)
    liste.sort(key=lambda d: d.get("angelegt", ""), reverse=True)
    return liste


def loesche(kennung: str) -> bool:
    ordner = verzeichnis(kennung)
    if not ordner.is_dir():
        return False
    shutil.rmtree(ordner, ignore_errors=True)
    return True


def katalog_eintraege() -> list[dict]:
    """Die fertigen Menuepunkte, fuer den Katalog."""
    eintraege = []
    for d in alle():
        dateien = d.get("dateien", [])
        if d.get("status") != "bereit" or not dateien:
            continue
        basis = d["slug"]
        eintraege.append({
            "slug": d["slug"],
            "name": d["name"],
            # Getrennt vom Namen -- so zeigt die Oberflaeche "Alpine 3.22"
            # und das Bootmenue kann beides eigens setzen.
            "version": d.get("version", ""),
            "description": d.get("beschreibung", "") or "selbst angelegt",
            "category": d.get("gruppe", ONLINE),
            "platforms": ["pcbios", "efi"],
            "type": "kernel",
            "kernel": basis + "/" + dateien[0],
            "initrd": [basis + "/" + n for n in dateien[1:]],
            "cmdline": d.get("cmdline", ""),
            "assets": [basis + "/" + n for n in dateien],
        })
    return eintraege

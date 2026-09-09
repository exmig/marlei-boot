"""
Installationsprotokolle, die ein Client nach einer misslungenen
Installation beim Bootserver ablegt.

Warum ueberhaupt? Bricht eine Installation ab, stehen die Antworten in
/var/log/installer und im Journal -- beides liegt im Arbeitsspeicher des
Live-Systems und ist mit dem naechsten Neustart weg. Wer neben der Maschine
sitzt, kann es rechtzeitig wegkopieren. Bei einem Rechner ohne Bildschirm
geht genau das nicht, und das ist der Fall, fuer den dieser Server gebaut
ist.

Ablage -- unterhalb von /var/lib/pxeweb/logs/<mac>/:

    20260821T101500Z-protokolle.tgz

Bewusst neben der Datenbank und nicht in ihr: Protokolle sind ein paar
Megabyte gross, das gehoert nicht in eine SQLite-Datei. Und ausserhalb von
/srv/pxe/assets, weil dieses Verzeichnis per NFS im ganzen Subnetz lesbar
ist -- Installationsprotokolle enthalten Geraetenamen, Partitionierung und
je nach Installer auch Benutzernamen.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

# Standardmaessig neben der Datenbank. install.sh legt /var/lib/pxeweb an
# und gibt es dem Dienstkonto; pxeweb.service erlaubt dort als einzigem Ort
# unterhalb von /var das Schreiben.
_DB = Path(os.environ.get("PXE_DB", "/var/lib/pxeweb/pxeweb.db"))
LOG_DIR = Path(os.environ.get("PXE_LOGS", "") or _DB.parent / "logs")

# Obergrenze je Datei. Ein eingepacktes /var/log/installer samt Journal
# liegt bei wenigen Megabyte; alles jenseits davon ist ein Versehen oder
# ein Versuch, die Platte vollzuschreiben.
MAX_BYTES = 64 * 1024 * 1024

# So viele Protokolle bleiben je Rechner liegen, aeltere werden entfernt.
# Sonst sammelt sich bei wiederholten Versuchen unbemerkt einiges an.
MAX_PRO_RECHNER = 20

_ERLAUBT = re.compile(r"[^A-Za-z0-9._-]")
_MAC_ORDNER = re.compile(r"^[0-9a-f]{2}(-[0-9a-f]{2}){5}$")


def ordnername(mac: str) -> str:
    """MAC als Verzeichnisname: aa:bb:... wird zu aa-bb-...

    Doppelpunkte sind in Dateinamen auf manchen Systemen nicht erlaubt, und
    iPXE liefert die Adresse ohnehin schon mit Bindestrichen.
    """
    return mac.strip().lower().replace(":", "-")


def sauberer_name(name: str) -> str:
    """Aus einem beliebigen Dateinamen einen ungefaehrlichen machen."""
    name = _ERLAUBT.sub("_", Path(name).name).strip("._") or "protokoll"
    return name[:80]


def _jetzt() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def zielpfad(mac: str, dateiname: str) -> Path:
    """Legt den Ablageort fuer ein neues Protokoll fest und schafft Platz."""
    ordner = LOG_DIR / ordnername(mac)
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner / (_jetzt() + "-" + sauberer_name(dateiname))


def aufraeumen(mac: str) -> int:
    """Aeltere Protokolle desselben Rechners entfernen. Zahl der Geloeschten."""
    ordner = LOG_DIR / ordnername(mac)
    if not ordner.is_dir():
        return 0
    dateien = sorted((p for p in ordner.iterdir() if p.is_file()), reverse=True)
    weg = 0
    for alt in dateien[MAX_PRO_RECHNER:]:
        try:
            alt.unlink()
            weg += 1
        except OSError:
            pass
    return weg


def pfad(mac: str, datei: str) -> Path | None:
    """Pfad eines abgelegten Protokolls, oder None wenn es das nicht gibt.

    Der Name wird nicht einfach angehaengt, sondern gegen die tatsaechlich
    vorhandenen Dateien geprueft -- so kann ein "../../etc/passwd" gar nicht
    erst irgendwo landen.
    """
    ordner = LOG_DIR / ordnername(mac)
    if not ordner.is_dir():
        return None
    gesucht = Path(datei).name
    for vorhanden in ordner.iterdir():
        if vorhanden.is_file() and vorhanden.name == gesucht:
            return vorhanden
    return None


def loesche(mac: str, datei: str) -> bool:
    ziel = pfad(mac, datei)
    if ziel is None:
        return False
    try:
        ziel.unlink()
    except OSError:
        return False
    ordner = ziel.parent
    if not any(ordner.iterdir()):
        ordner.rmdir()
    return True


def _eintrag(datei: Path, mac_ordner: str) -> dict:
    stat = datei.stat()
    # Der Zeitstempel steckt vorn im Namen -- verlaesslicher als die
    # Dateizeit, die ein Kopiervorgang veraendert haette.
    zeit, _, rest = datei.name.partition("-")
    return {
        "mac": mac_ordner.replace("-", ":"),
        "mac_ordner": mac_ordner,
        "datei": datei.name,
        "name": rest or datei.name,
        "zeit": zeit,
        "bytes": stat.st_size,
    }


def fuer(mac: str) -> list[dict]:
    """Protokolle eines Rechners, neueste zuerst."""
    ordner = LOG_DIR / ordnername(mac)
    if not ordner.is_dir():
        return []
    dateien = [p for p in ordner.iterdir() if p.is_file()]
    return [_eintrag(p, ordner.name) for p in sorted(dateien, reverse=True)]


def alle() -> list[dict]:
    """Protokolle aller Rechner, neueste zuerst."""
    if not LOG_DIR.is_dir():
        return []
    liste = []
    for ordner in LOG_DIR.iterdir():
        if ordner.is_dir() and _MAC_ORDNER.match(ordner.name):
            liste += [_eintrag(p, ordner.name) for p in ordner.iterdir() if p.is_file()]
    liste.sort(key=lambda d: d["datei"], reverse=True)
    return liste


def belegung() -> int:
    """Wie viel Platz alle Protokolle zusammen belegen (Bytes)."""
    return sum(d["bytes"] for d in alle())

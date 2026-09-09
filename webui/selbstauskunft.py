"""
Was ein Abbild ueber sich selbst sagt -- von der Platte gelesen.

Bei einem Upload steht diese Auskunft laengst da: Beim Einlesen hat der
Server die Volume-ID des ISO gelesen (oder ".disk/info" darin) und in der
eintrag.yaml abgelegt -- deshalb kann die Karte "Ubuntu 26.04 "Resolute
Raccoon" - Release amd64 (20260423.1)" zeigen, ohne dass jemand das
eintippen musste.

Bei den mitgelieferten Systemen fehlte sie, obwohl dieselben Angaben auf
der Platte liegen. Was sich lesen laesst, haengt davon ab, was der
Abgleich hinterlaesst:

    ausgepacktes Abbild     mint/.disk/info -- dieselbe Datei, die
                            isoscan im ISO liest, nur schon ausgepackt
    ISO liegt daneben       ubuntu/26.04/ubuntu-server-amd64.iso,
                            gparted/1.8.1-3/gparted.iso und die anderen
                            Werkzeuge -- gelesen mit isoscan
    nur Kernel und Initrd   Debian, Fedora, Leap, Tumbleweed, Rocky holen
                            zwei Dateien vom Spiegel. Da steht nichts.

Der letzte Fall ist kein Fehler und wird auch nicht als solcher gezeigt:
Die Zeile bleibt dann einfach leer.

**Gelesen wird nur, was billig ist.** Ein ausgepacktes Mint sind rund
50.000 Dateien -- gesucht wird deshalb an bekannten Stellen und hoechstens
eine Ebene tief, nicht rekursiv. Und das Ergebnis wird gemerkt, solange
sich die Datei nicht aendert (Pfad, Zeitstempel, Groesse): Sonst laege bei
jedem Seitenaufruf ein Dutzend ISO-Zugriffe an, fuer eine Zeile, die sich
nur beim Abgleich aendert.
"""

from __future__ import annotations

import os
from pathlib import Path

import isoscan

# Laenger als das ist keine Auskunft mehr, sondern ein Absatz.
MAX_LAENGE = 120

# Pfad, Zeitstempel, Groesse -> Text. Aendert sich die Datei, entsteht ein
# neuer Schluessel und es wird neu gelesen; verschwindet sie, faellt der
# alte Eintrag nicht auf, weil niemand mehr danach fragt.
_gemerkt: dict[tuple, str] = {}


def _sauber(text: str) -> str:
    """Eine Zeile daraus machen -- Steuerzeichen und Leerraum raus."""
    text = " ".join((text or "").split())
    return text[:MAX_LAENGE]


def _kennung(pfad: Path) -> tuple | None:
    try:
        stand = pfad.stat()
    except OSError:
        return None
    return (str(pfad), stand.st_mtime_ns, stand.st_size)


def _aus_datei(pfad: Path) -> str:
    """Eine ausgepackte .disk/info lesen."""
    try:
        return _sauber(pfad.read_text(encoding="utf-8", errors="replace").splitlines()[0])
    except (OSError, IndexError):
        return ""


def _aus_iso(pfad: Path) -> str:
    """Ein ISO fragen -- derselbe Weg wie beim Upload."""
    try:
        befund = isoscan.untersuche(pfad)
    except Exception:
        # Ein halb geladenes oder unbekanntes Abbild ist hier kein
        # Zwischenfall: Dann gibt es eben keine Auskunft. Der Zustand des
        # Eintrags haengt an seinen Dateien, nicht an dieser Zeile.
        return ""
    return _sauber(befund.name or befund.volume_id)


def aus_ordner(ordner: Path | None) -> str:
    """Was in diesem Verzeichnis ueber das Abbild zu erfahren ist."""
    if ordner is None:
        return ""
    try:
        if not ordner.is_dir():
            return ""
    except OSError:
        return ""

    # Erst die ausgepackte Textdatei: Sie ist genauer als die Volume-ID
    # ("Linux Mint 22.3 Cinnamon" statt "LINUX_MINT_22.3") und kostet einen
    # Lesevorgang statt eines ISO-Durchgangs. Dann ein Abbild daneben.
    #
    # In Unterordner wird nicht geschaut. Das war einmal anders und ging
    # schief: Unter ubuntu/ liegen 24.04 und 26.04 nebeneinander, und der
    # Eintrag fuer 26.04 bekam die Auskunft von 24.04 -- die stand in der
    # Liste weiter vorn. Was in einem Unterordner liegt, gehoert einer
    # anderen Ausgabe, und die hat ihren eigenen Eintrag.
    stellen = [(ordner / ".disk" / "info", _aus_datei)]
    stellen += [(p, _aus_iso) for p in sorted(ordner.glob("*.iso"))]

    for pfad, lies in stellen:
        schluessel = _kennung(pfad)
        if schluessel is None:
            continue
        if schluessel not in _gemerkt:
            _gemerkt[schluessel] = lies(pfad)
        if _gemerkt[schluessel]:
            return _gemerkt[schluessel]
    return ""


def aus_pfaden(wurzel: Path, pfade: list[Path]) -> str:
    """Von den Dateien des Eintrags aus nach oben suchen.

    Angefangen wird dort, wo seine Dateien liegen, und von da geht es
    Ebene fuer Ebene hoeher bis zur Ablage. Die Reihenfolge ist wichtig:

        ubuntu/26.04/vmlinuz         -> ubuntu/26.04/, dort liegt das ISO
        gparted/1.8.1-3/live/vmlinuz -> live/, dann 1.8.1-3/ mit dem ISO
        systemrescue/13.02/sysresccd/boot/... -> drei Ebenen hoeher

    So findet jeder Eintrag das Abbild seiner eigenen Ausgabe, und nur
    das: Nach unten wird nicht gesucht (siehe aus_ordner). Ein Eintrag,
    der selbst nichts hat, faellt hoechstens auf das zurueck, was fuer das
    ganze System dort liegt -- nie auf die Nachbarausgabe.
    """
    if not pfade:
        return ""
    try:
        gemeinsam = Path(os.path.commonpath([str(p) for p in pfade]))
    except ValueError:
        return ""
    if gemeinsam in pfade:
        gemeinsam = gemeinsam.parent

    ordner = gemeinsam
    while wurzel in ordner.parents or ordner == wurzel:
        if ordner == wurzel:
            break
        gefunden = aus_ordner(ordner)
        if gefunden:
            return gefunden
        ordner = ordner.parent
    return ""


def vergiss() -> None:
    """Das Gemerkte wegwerfen -- fuer Tests und nach dem Aufraeumen."""
    _gemerkt.clear()

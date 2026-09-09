"""
Liest das UDF-Dateisystem eines Abbilds -- fuer Windows-Medien noetig.

Warum ueberhaupt ein zweites Dateisystem? Ein Windows-Installationsmedium
ist formal auch ein ISO9660-Abbild, aber das ist nur eine leere Huelle. Der
ISO9660-Teil einer Windows-11-ISO enthaelt genau eine Datei, und die sagt:

    "This disc contains a UDF file system and requires an operating system
     that supports the ISO-13346 UDF file system specification."

Alles Weitere -- bootmgr, die BCD, boot.wim -- liegt im UDF-Teil. Der Grund
ist die 4-GB-Grenze von ISO9660: die install.wim ist groesser, und statt
zwei Dateisysteme nebeneinander zu pflegen, legt Microsoft alles ins UDF.

Aufbau, soweit wir ihn brauchen (alles in Bloecken zu 2048 Byte):

    Sektor 256   Anker: sagt, wo die Beschreibungen liegen
    dort         Partition Descriptor  -> ab welchem Sektor die Daten gehen
                 Logical Volume Descr. -> Blockgroesse, wo der Dateisatz liegt
    Dateisatz    File Set Descriptor   -> wo das Wurzelverzeichnis liegt
    danach       File Entries und Verzeichniseintraege

Ein Verzeichnis ist wie bei ISO9660 nur eine Datei aus aneinandergereihten
Eintraegen; jeder nennt einen Namen und zeigt auf einen "File Entry", in dem
Groesse und Fundort der eigentlichen Daten stehen. Damit laesst sich der
Baum ablaufen, ohne das Abbild zu durchsuchen -- ein paar Dutzend Sektoren
statt sechs Gigabyte.

Ein Unterschied zu ISO9660, der hier Folgen hat: Eine Datei muss nicht am
Stueck liegen. Deshalb merkt sich ein Eintrag eine Liste von Bereichen und
nicht nur einen Startsektor.

Nicht unterstuetzt: Metadaten-Partitionen (UDF 2.50 und neuer, etwa bei
Blu-ray). Windows-Medien benutzen UDF 1.02 bis 2.01 und kommen ohne aus;
tritt eine auf, sagt der Leser das deutlich, statt Unsinn zu liefern.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

BLOCK = 2048

# Sicherheitsnetze gegen kaputte oder boshafte Abbilder -- dieselben Grenzen
# wie beim ISO9660-Leser. Ohne sie wuerde ein Verzeichnis, das sich selbst
# enthaelt, uns endlos beschaeftigen.
MAX_TIEFE = 8
MAX_EINTRAEGE = 40000

# Die Descriptor-Typen, die wir auswerten.
ANKER = 2
PARTITION = 5
LOGISCHER_DATENTRAEGER = 6
ABSCHLUSS = 8
DATEISATZ = 256
NAMENSEINTRAG = 257
DATEI_EINTRAG = 261
DATEI_EINTRAG_LANG = 266

# FileType im ICB-Tag
TYP_ORDNER = 4


class UdfFehler(Exception):
    """Das Abbild hat keinen brauchbaren UDF-Teil."""


@dataclass
class UdfDatei:
    """Eine Datei oder ein Ordner im UDF-Baum."""

    pfad: str                 # kleingeschrieben, mit "/" getrennt
    echter_pfad: str          # in der Schreibweise des Abbilds
    ordner: bool
    groesse: int = 0
    # Wo die Daten liegen: (Byte-Offset im Abbild, Laenge). Mehrere Stuecke,
    # weil eine Datei nicht am Stueck liegen muss -- gerade grosse wie
    # boot.wim.
    stuecke: list[tuple[int, int]] = field(default_factory=list)
    # Sehr kleine Dateien stehen direkt im File Entry, ohne eigenen Block.
    eingebettet: bytes = b""


def hat_udf(datei) -> bool:
    """Steht in der Kennungsfolge ein UDF-Vermerk?

    Zwischen den ISO9660-Descriptoren und dem eigentlichen UDF liegt eine
    Liste von Kennungen; "NSR02" oder "NSR03" darin heisst: hier ist ein
    UDF-Dateisystem. Das kostet ein paar Sektoren und erspart es, den
    UDF-Leser auf jedes Abbild loszulassen.
    """
    for nummer in range(16, 64):
        datei.seek(nummer * BLOCK)
        block = datei.read(BLOCK)
        if len(block) < 7:
            return False
        kennung = block[1:6]
        if kennung in (b"NSR02", b"NSR03"):
            return True
        if kennung not in (b"CD001", b"BEA01", b"TEA01", b"BOOT2"):
            return False
    return False


def _typ(block: bytes) -> int:
    """Welcher Descriptor steht hier? 0 heisst: keiner."""
    if len(block) < 16:
        return 0
    return struct.unpack_from("<H", block, 0)[0]


def _langer_verweis(block: bytes, offset: int) -> tuple[int, int, int]:
    """Ein "long_ad": Laenge, Blocknummer, Partitionsnummer.

    Die oberen zwei Bits der Laenge sagen, ob der Bereich ueberhaupt
    beschrieben ist -- deshalb wird die Laenge maskiert. Ohne das kaeme bei
    einem nicht beschriebenen Bereich eine absurde Groesse heraus.
    """
    laenge, block_nr, partition = struct.unpack_from("<IIH", block, offset)
    return laenge & 0x3FFFFFFF, block_nr, partition


def _kurzer_verweis(block: bytes, offset: int) -> tuple[int, int]:
    laenge, block_nr = struct.unpack_from("<II", block, offset)
    return laenge & 0x3FFFFFFF, block_nr


def _name(roh: bytes) -> str:
    """Einen Dateinamen dekodieren (OSTA CS0).

    Das erste Byte sagt, wie breit die Zeichen sind: 8 heisst Latin-1,
    16 heisst UTF-16 in Big-Endian. Windows-Medien benutzen beides
    gemischt -- kurze ASCII-Namen 8-bittig, alles andere 16-bittig.
    """
    if not roh:
        return ""
    kennung, rest = roh[0], roh[1:]
    if kennung == 16:
        return rest.decode("utf-16-be", "replace").rstrip("\x00")
    # Unbekannte Kodierung lieber lesbar raten als aussteigen -- ein Name,
    # den wir nicht suchen, schadet nicht.
    return rest.decode("latin-1", "replace").rstrip("\x00")


class UdfLeser:
    """Laeuft den UDF-Baum eines geoeffneten Abbilds ab."""

    def __init__(self, datei):
        self.datei = datei
        self.blockgroesse = BLOCK
        self.partition_start = 0
        self.wurzel: int | None = None      # Blocknummer des Wurzelverzeichnisses

    # -- Rohzugriff ---------------------------------------------------------

    def _sektor(self, nummer: int, anzahl: int = 1) -> bytes:
        self.datei.seek(nummer * self.blockgroesse)
        return self.datei.read(anzahl * self.blockgroesse)

    def _partitionsblock(self, nummer: int, anzahl: int = 1) -> bytes:
        """Ein Block, dessen Nummer sich auf die Partition bezieht.

        Verzeichnisse und Dateien werden relativ zum Anfang der Partition
        adressiert, die Beschreibungen dagegen absolut. Diese Umrechnung
        einmal zu vergessen ist die haeufigste Art, UDF falsch zu lesen.
        """
        return self._sektor(self.partition_start + nummer, anzahl)

    # -- Aufbau -------------------------------------------------------------

    def oeffne(self) -> dict[str, UdfDatei]:
        self._lies_beschreibungen()
        if self.wurzel is None:
            raise UdfFehler("Kein Wurzelverzeichnis im UDF-Teil gefunden")
        eintraege: dict[str, UdfDatei] = {}
        self._lies_verzeichnis(self.wurzel, "", eintraege, 0)
        if not eintraege:
            raise UdfFehler("Der UDF-Teil ist leer")
        return eintraege

    def _anker(self) -> tuple[int, int]:
        """Wo steht die Liste der Beschreibungen?

        Der Anker liegt nach der Norm bei Sektor 256; als Reserve nennt sie
        den letzten Sektor und den 256. von hinten. Abbilder halten sich fast
        immer an 256, aber die Reserve kostet zwei Lesevorgaenge.
        """
        self.datei.seek(0, 2)
        letzter = self.datei.tell() // self.blockgroesse - 1
        for nummer in (256, letzter, letzter - 256):
            if nummer < 16:
                continue
            if _typ(self._sektor(nummer)) == ANKER:
                laenge, ort = struct.unpack_from("<II", self._sektor(nummer), 16)
                return ort, max(1, laenge // self.blockgroesse)
        raise UdfFehler("Kein UDF-Anker gefunden (weder bei Sektor 256 noch am Ende)")

    def _lies_beschreibungen(self) -> None:
        ort, anzahl = self._anker()
        dateisatz = None

        for nummer in range(ort, ort + max(anzahl, 32)):
            block = self._sektor(nummer)
            typ = _typ(block)
            if typ in (ABSCHLUSS, 0):
                break
            if typ == PARTITION:
                self.partition_start = struct.unpack_from("<I", block, 188)[0]
            elif typ == LOGISCHER_DATENTRAEGER:
                groesse = struct.unpack_from("<I", block, 212)[0]
                if groesse:
                    self.blockgroesse = groesse
                # Wo der Dateisatz liegt, steht mitten in der Beschreibung.
                dateisatz = _langer_verweis(block, 248)
                # Nur einfache Partitionsverweise (Typ 1) werden verstanden.
                # Typ 2 waere eine Metadaten-Partition -- die gibt es erst ab
                # UDF 2.50, und Windows-Medien benutzen sie nicht.
                anzahl_maps = struct.unpack_from("<I", block, 268)[0]
                if anzahl_maps and len(block) > 440 and block[440] != 1:
                    raise UdfFehler(
                        "Dieses UDF benutzt eine Metadaten-Partition "
                        "(UDF 2.50 oder neuer). Das wird hier nicht gelesen."
                    )

        if dateisatz is None:
            raise UdfFehler("Keine Beschreibung des Datentraegers gefunden")

        _, block_nr, _ = dateisatz
        block = self._partitionsblock(block_nr)
        if _typ(block) != DATEISATZ:
            raise UdfFehler("An der genannten Stelle steht kein Dateisatz")
        _, wurzel_block, _ = _langer_verweis(block, 400)
        self.wurzel = wurzel_block

    # -- Dateien ------------------------------------------------------------

    def _eintrag(self, block_nr: int) -> tuple[bool, int, list[tuple[int, int]], bytes]:
        """Einen File Entry auswerten: Ordner? Groesse? Wo liegen die Daten?

        Es gibt zwei Bauformen, die kurze und die lange -- sie unterscheiden
        sich nur darin, wo der Kopf endet. Alles Weitere ist gleich.
        """
        block = self._partitionsblock(block_nr)
        typ = _typ(block)
        if typ == DATEI_EINTRAG:
            kopf, ea_offset, ad_offset = 176, 168, 172
        elif typ == DATEI_EINTRAG_LANG:
            kopf, ea_offset, ad_offset = 216, 208, 212
        else:
            raise UdfFehler(f"Kein Dateieintrag an Block {block_nr} (Typ {typ})")

        dateityp = block[16 + 11]
        flags = struct.unpack_from("<H", block, 16 + 18)[0]
        groesse = struct.unpack_from("<Q", block, 56)[0]
        laenge_ea = struct.unpack_from("<I", block, ea_offset)[0]
        laenge_ad = struct.unpack_from("<I", block, ad_offset)[0]
        anfang = kopf + laenge_ea
        ist_ordner = dateityp == TYP_ORDNER

        art = flags & 0x07
        if art == 3:
            # Der Inhalt steckt direkt im Eintrag -- so werden sehr kleine
            # Dateien abgelegt, ohne einen eigenen Block zu belegen.
            ende = anfang + min(groesse, laenge_ad)
            return ist_ordner, groesse, [], bytes(block[anfang:ende])

        stuecke = []
        schritt = 8 if art == 0 else 16
        for offset in range(anfang, min(anfang + laenge_ad, len(block)), schritt):
            if offset + schritt > len(block):
                break
            if art == 0:
                laenge, ziel = _kurzer_verweis(block, offset)
            else:
                laenge, ziel, _ = _langer_verweis(block, offset)
            if laenge == 0:
                continue
            stuecke.append(((self.partition_start + ziel) * self.blockgroesse, laenge))

        return ist_ordner, groesse, stuecke, b""

    def _lies_daten(self, stuecke, grenze: int) -> bytes:
        """Den Inhalt einer Datei einlesen -- hier nur fuer Verzeichnisse."""
        teile = []
        offen = grenze
        for start, laenge in stuecke:
            if offen <= 0:
                break
            self.datei.seek(start)
            teile.append(self.datei.read(min(laenge, offen)))
            offen -= laenge
        return b"".join(teile)

    def _lies_verzeichnis(self, block_nr: int, pfad: str,
                          eintraege: dict[str, UdfDatei], tiefe: int) -> None:
        if tiefe > MAX_TIEFE or len(eintraege) > MAX_EINTRAEGE:
            return

        try:
            _, groesse, stuecke, eingebettet = self._eintrag(block_nr)
        except (UdfFehler, struct.error, IndexError):
            return

        inhalt = eingebettet or self._lies_daten(stuecke, groesse)

        offset = 0
        while offset + 38 <= len(inhalt):
            if _typ(inhalt[offset:offset + 16]) != NAMENSEINTRAG:
                break
            merkmale = inhalt[offset + 18]
            laenge_name = inhalt[offset + 19]
            _, kind_block, _ = _langer_verweis(inhalt, offset + 20)
            laenge_iu = struct.unpack_from("<H", inhalt, offset + 36)[0]
            name_ab = offset + 38 + laenge_iu
            name = _name(inhalt[name_ab:name_ab + laenge_name])

            # Auf die naechste Vierergrenze auffuellen -- so schreibt UDF.
            ganz = 38 + laenge_iu + laenge_name
            offset += ganz + (-ganz % 4)

            # Bit 3 markiert den Verweis auf das Elternverzeichnis, Bit 2 eine
            # geloeschte Datei. Beide gehen uns nichts an.
            if merkmale & 0x08 or merkmale & 0x04 or not name:
                continue

            voll = f"{pfad}/{name}" if pfad else name
            ist_ordner = bool(merkmale & 0x02)
            try:
                _, kind_groesse, kind_stuecke, kind_daten = self._eintrag(kind_block)
            except (UdfFehler, struct.error, IndexError):
                continue

            eintraege[voll.lower()] = UdfDatei(
                pfad=voll.lower(), echter_pfad=voll, ordner=ist_ordner,
                groesse=0 if ist_ordner else kind_groesse,
                stuecke=[] if ist_ordner else kind_stuecke,
                eingebettet=b"" if ist_ordner else kind_daten,
            )
            if ist_ordner:
                self._lies_verzeichnis(kind_block, voll, eintraege, tiefe + 1)


def lies_baum(datei) -> dict[str, UdfDatei]:
    """Das ganze Inhaltsverzeichnis des UDF-Teils.

    Erwartet eine geoeffnete Datei im Binaermodus; die Position darin wird
    veraendert. Wirft UdfFehler, wenn kein lesbares UDF vorliegt.
    """
    return UdfLeser(datei).oeffne()


if __name__ == "__main__":                                 # pragma: no cover
    # Von Hand: python3 udf.py <abbild.iso>
    import sys

    with Path(sys.argv[1]).open("rb") as fh:
        print("UDF vorhanden:", hat_udf(fh))
        baum = lies_baum(fh)
        print(len(baum), "Eintraege")
        for eintrag in sorted(baum.values(), key=lambda e: e.pfad)[:40]:
            art = "ordner" if eintrag.ordner else f"{eintrag.groesse:>13,} B"
            print(f"  {eintrag.echter_pfad:52s} {art}")

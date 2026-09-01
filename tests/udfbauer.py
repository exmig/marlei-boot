"""Baut winzige, aber echte UDF-Abbilder fuer die Tests.

Gegenstueck zu isobauer.py -- gebraucht, weil Windows-Medien ihre Dateien
nicht im ISO9660-Teil fuehren, sondern im UDF (siehe webui/udf.py). Ohne
diesen Bauer waere der UDF-Leser nur an echten, mehrere Gigabyte grossen
Abbildern zu pruefen, und die liegen nicht im Repository.

Nachgebaut wird der Aufbau eines echten Mediums:

    Sektor 16-17   ISO9660-Kopf mit Datentraegernamen und Abschluss
    Sektor 18-20   BEA01 / NSR02 / TEA01 -- der Vermerk "hier ist UDF"
    Sektor 24-25   die ISO9660-Wurzel, in der fast nichts steht
    Sektor 32-35   Beschreibungen: Partition, Datentraeger, Abschluss
    Sektor 256     Anker, der auf diese Beschreibungen zeigt
    ab Sektor 288  die Partition mit Dateisatz, Verzeichnissen und Dateien

Drei Eigenheiten von UDF lassen sich damit pruefen, die es bei ISO9660
nicht gibt und an denen ein Leser scheitern kann:

    add(...)                   normale Datei, ein Stueck
    add(..., stuecke=2)        Datei, die zerteilt abgelegt ist
    add(..., eingebettet=True) Datei, die im Verzeichniseintrag selbst steht
    add(..., breit=True)       Name in 16-Bit-Zeichen statt in 8-Bit

Benutzung:

    UdfBauer("WIN11").add("sources/boot.wim", b"MSWIM...").schreibe(pfad)

Nicht gesetzt werden die CRC-Felder der Descriptor-Tags: der Leser prueft
sie nicht, und sie nachzubilden wuerde diesen Bauer verdoppeln, ohne eine
Zeile mehr Code zu pruefen. Die Tag-Pruefsumme steht drin, sie ist billig.
"""

import struct
from pathlib import Path

BLOCK = 2048

# Wo was liegt. Grosszuegig gewaehlt, damit die Abschnitte auseinanderliegen
# wie bei einem echten Medium -- ein Leser, der Partitionsadressen mit
# absoluten verwechselt, faellt dadurch auf.
VDS_START = 32
ANKER = 256
PARTITION_START = 288


def _tag(kennung: int, block_nr: int, daten: bytearray) -> None:
    """Den Descriptor-Tag an den Anfang eines Blocks schreiben."""
    struct.pack_into("<HHBBHHHI", daten, 0,
                     kennung,      # TagIdentifier
                     2,            # DescriptorVersion (UDF 1.02)
                     0,            # TagChecksum -- gleich
                     0,            # Reserved
                     1,            # TagSerialNumber
                     0, 0,         # CRC und CRC-Laenge: siehe Modulkopf
                     block_nr)
    daten[4] = (sum(daten[0:4]) + sum(daten[5:16])) & 0xFF


def _long_ad(laenge: int, block_nr: int) -> bytes:
    return struct.pack("<IIH", laenge, block_nr, 0) + b"\x00" * 6


def _short_ad(laenge: int, block_nr: int) -> bytes:
    return struct.pack("<II", laenge, block_nr)


def _name(text: str, breit: bool) -> bytes:
    """Ein Dateiname in OSTA CS0: erstes Byte sagt, wie breit die Zeichen sind."""
    if breit:
        return b"\x10" + text.encode("utf-16-be")
    return b"\x08" + text.encode("latin-1")


class _Knoten:
    def __init__(self, name, ordner):
        self.name = name
        self.ordner = ordner
        self.kinder = {}
        self.inhalt = b""
        self.stuecke = 1
        self.eingebettet = False
        self.breit = False
        self.fe_block = 0            # Block mit dem File Entry
        self.daten_bloecke = []      # (Block, Laenge) der Daten


class UdfBauer:
    """Baut ein kleines, aber echtes UDF-Abbild."""

    def __init__(self, volume_id="TESTUDF", iso_readme=True):
        self.volume_id = volume_id
        # Echte Windows-Medien legen genau eine Datei ins ISO9660 -- einen
        # Zettel, der auf UDF verweist. Das ist der Normalfall und deshalb
        # die Vorgabe.
        self.iso_readme = iso_readme
        self.wurzel = _Knoten("", True)

    def add(self, pfad, inhalt=b"x", stuecke=1, eingebettet=False, breit=False):
        teile = pfad.split("/")
        knoten = self.wurzel
        for name in teile[:-1]:
            knoten = knoten.kinder.setdefault(name, _Knoten(name, True))
        datei = _Knoten(teile[-1], False)
        datei.inhalt = inhalt
        datei.stuecke = max(1, stuecke)
        datei.eingebettet = eingebettet
        datei.breit = breit
        knoten.kinder[teile[-1]] = datei
        return self

    # -- Aufbau ---------------------------------------------------------

    def _verzeichnis_daten(self, knoten) -> bytes:
        """Die Eintraege eines Verzeichnisses als Bytefolge.

        Zuerst der Verweis auf das Elternverzeichnis -- so schreibt es UDF
        vor, und ein Leser, der ihn nicht ueberspringt, findet den Baum
        doppelt.
        """
        roh = bytearray()

        eltern = bytearray(40)
        _tag(257, 0, eltern)
        struct.pack_into("<HBB", eltern, 16, 1, 0x08, 0)     # Version, "Eltern", Namenslaenge 0
        eltern[20:36] = _long_ad(BLOCK, knoten.fe_block)
        struct.pack_into("<H", eltern, 36, 0)
        roh += bytes(eltern[:38]) + b"\x00\x00"              # auf Vierergrenze

        for kind in knoten.kinder.values():
            name = _name(kind.name, kind.breit)
            satz = bytearray(38 + len(name))
            _tag(257, 0, satz)
            struct.pack_into("<HBB", satz, 16,
                             1,                              # FileVersionNumber
                             0x02 if kind.ordner else 0x00,  # FileCharacteristics
                             len(name))
            satz[20:36] = _long_ad(BLOCK, kind.fe_block)
            struct.pack_into("<H", satz, 36, 0)              # keine Implementierungsdaten
            satz[38:] = name
            fuellung = -len(satz) % 4
            roh += bytes(satz) + b"\x00" * fuellung
        return bytes(roh)

    def _plane(self, knoten, naechster: int) -> int:
        """Jedem Knoten seinen File Entry und seine Datenbloecke zuweisen."""
        knoten.fe_block = naechster
        naechster += 1

        if knoten.ordner:
            for kind in knoten.kinder.values():
                naechster = self._plane(kind, naechster)
            # Die Verzeichnisdaten kommen hinter die Kinder -- ihre Groesse
            # steht erst fest, wenn alle Kinder ihren File Entry haben.
            daten = self._verzeichnis_daten(knoten)
            anzahl = max(1, (len(daten) + BLOCK - 1) // BLOCK)
            knoten.daten_bloecke = [(naechster, len(daten))]
            naechster += anzahl
            return naechster

        if knoten.eingebettet:
            return naechster

        # Eine Datei in mehrere Stuecke zerlegen: jedes bekommt seinen
        # eigenen Bereich, und zwischen ihnen bleibt ein Block frei -- damit
        # ein Leser, der die Stuecke einfach aneinanderhaengt, auffliegt.
        teil = (len(knoten.inhalt) + knoten.stuecke - 1) // max(1, knoten.stuecke)
        offen = len(knoten.inhalt)
        while offen > 0:
            laenge = min(teil, offen)
            anzahl = max(1, (laenge + BLOCK - 1) // BLOCK)
            knoten.daten_bloecke.append((naechster, laenge))
            naechster += anzahl + 1                 # ein Block Luecke
            offen -= laenge
        return naechster

    def _schreibe_knoten(self, knoten, setze_partition) -> None:
        """File Entry und Daten eines Knotens ablegen."""
        fe = bytearray(BLOCK)
        _tag(261, knoten.fe_block, fe)

        # ICB-Tag: was fuer ein Eintrag ist das, und wie sind die Daten
        # adressiert?
        struct.pack_into("<IHHHBB", fe, 16, 0, 4, 0, 1, 0,
                         4 if knoten.ordner else 5)          # FileType
        art = 3 if (knoten.eingebettet and not knoten.ordner) else 0
        struct.pack_into("<H", fe, 16 + 18, art)

        if knoten.ordner:
            daten = self._verzeichnis_daten(knoten)
            groesse = len(daten)
        else:
            daten = knoten.inhalt
            groesse = len(knoten.inhalt)
        struct.pack_into("<Q", fe, 56, groesse)

        if art == 3:
            struct.pack_into("<I", fe, 168, 0)               # keine Attribute
            struct.pack_into("<I", fe, 172, groesse)
            fe[176:176 + groesse] = daten
        else:
            verweise = b"".join(_short_ad(laenge, block)
                                for block, laenge in knoten.daten_bloecke)
            struct.pack_into("<I", fe, 168, 0)
            struct.pack_into("<I", fe, 172, len(verweise))
            fe[176:176 + len(verweise)] = verweise
            # Die Daten selbst
            offset = 0
            for block, laenge in knoten.daten_bloecke:
                setze_partition(block, daten[offset:offset + laenge])
                offset += laenge

        setze_partition(knoten.fe_block, bytes(fe))

        for kind in knoten.kinder.values():
            self._schreibe_knoten(kind, setze_partition)

    def schreibe(self, ziel) -> Path:
        ziel = Path(ziel)
        # Block 0 der Partition ist der Dateisatz, ab Block 1 der Baum.
        ende = self._plane(self.wurzel, 1)
        gesamt = PARTITION_START + ende + 2

        abbild = bytearray(gesamt * BLOCK)

        def setze(sektor, daten):
            abbild[sektor * BLOCK:sektor * BLOCK + len(daten)] = daten

        def setze_partition(block, daten):
            setze(PARTITION_START + block, daten)

        # --- ISO9660-Huelle: Datentraegername und ein leeres Wurzelverzeichnis
        #
        # Die Reihenfolge ist nicht frei: die Kennungsfolge (BEA01/NSR02/
        # TEA01) muss unmittelbar hinter den ISO9660-Deskriptoren stehen.
        # Ein Leser darf beim ersten Sektor ohne bekannte Kennung aufhoeren
        # zu suchen -- eine Luecke dazwischen wuerde das UDF unsichtbar
        # machen. Deshalb liegen Wurzelverzeichnis und Zettel dahinter.
        wurzel_sektor = 24
        pvd = bytearray(BLOCK)
        pvd[0] = 1
        pvd[1:6] = b"CD001"
        pvd[6] = 1
        pvd[40:72] = self.volume_id.encode("ascii", "replace").ljust(32)[:32]
        pvd[80:88] = struct.pack("<I", gesamt) + struct.pack(">I", gesamt)
        pvd[128:132] = struct.pack("<H", BLOCK) + struct.pack(">H", BLOCK)
        satz = bytearray(34)
        satz[0] = 34
        satz[2:10] = struct.pack("<I", wurzel_sektor) + struct.pack(">I", wurzel_sektor)
        satz[10:18] = struct.pack("<I", BLOCK) + struct.pack(">I", BLOCK)
        satz[25] = 0x02
        satz[32] = 1
        pvd[156:190] = bytes(satz)
        setze(16, bytes(pvd))

        ende_deskriptor = bytearray(BLOCK)
        ende_deskriptor[0] = 255
        ende_deskriptor[1:6] = b"CD001"
        ende_deskriptor[6] = 1
        setze(17, bytes(ende_deskriptor))

        # Die Wurzel des ISO9660-Teils: "." und ".." und hoechstens der Zettel.
        wurzel = bytearray()
        for kennung in (b"\x00", b"\x01"):
            eintrag = bytearray(34)
            eintrag[0] = 34
            eintrag[2:10] = struct.pack("<I", wurzel_sektor) + struct.pack(">I", wurzel_sektor)
            eintrag[10:18] = struct.pack("<I", BLOCK) + struct.pack(">I", BLOCK)
            eintrag[25] = 0x02
            eintrag[32] = 1
            eintrag[33] = kennung[0]
            wurzel += bytes(eintrag)
        if self.iso_readme:
            text = (b"This disc contains a \"UDF\" file system and requires an "
                    b"operating system that supports the ISO-13346 \"UDF\" "
                    b"file system specification.\r\n")
            zettel_sektor = 25
            name = b"README.TXT;1"
            eintrag = bytearray(33 + len(name) + (1 - len(name) % 2))
            eintrag[0] = len(eintrag)
            eintrag[2:10] = struct.pack("<I", zettel_sektor) + struct.pack(">I", zettel_sektor)
            eintrag[10:18] = struct.pack("<I", len(text)) + struct.pack(">I", len(text))
            eintrag[32] = len(name)
            eintrag[33:33 + len(name)] = name
            wurzel += bytes(eintrag)
            setze(zettel_sektor, text)
        setze(wurzel_sektor, bytes(wurzel).ljust(BLOCK, b"\x00"))

        # --- Der Vermerk "hier ist UDF" ---------------------------------
        for versatz, kennung in enumerate((b"BEA01", b"NSR02", b"TEA01")):
            kopf = bytearray(BLOCK)
            kopf[1:6] = kennung
            kopf[6] = 1
            setze(18 + versatz, bytes(kopf))

        # --- Beschreibungen ---------------------------------------------
        partition = bytearray(BLOCK)
        _tag(5, VDS_START, partition)
        struct.pack_into("<I", partition, 188, PARTITION_START)
        struct.pack_into("<I", partition, 192, gesamt - PARTITION_START)
        setze(VDS_START, bytes(partition))

        datentraeger = bytearray(BLOCK)
        _tag(6, VDS_START + 1, datentraeger)
        struct.pack_into("<I", datentraeger, 212, BLOCK)      # LogicalBlockSize
        datentraeger[248:264] = _long_ad(BLOCK, 0)            # Dateisatz: Block 0
        struct.pack_into("<II", datentraeger, 264, 6, 1)      # eine Partitionsangabe
        datentraeger[440:446] = struct.pack("<BBHH", 1, 6, 1, 0)
        setze(VDS_START + 1, bytes(datentraeger))

        abschluss = bytearray(BLOCK)
        _tag(8, VDS_START + 2, abschluss)
        setze(VDS_START + 2, bytes(abschluss))

        anker = bytearray(BLOCK)
        _tag(2, ANKER, anker)
        struct.pack_into("<II", anker, 16, 3 * BLOCK, VDS_START)
        setze(ANKER, bytes(anker))

        # --- Dateisatz und Baum -----------------------------------------
        dateisatz = bytearray(BLOCK)
        _tag(256, 0, dateisatz)
        dateisatz[400:416] = _long_ad(BLOCK, self.wurzel.fe_block)
        setze_partition(0, bytes(dateisatz))

        self._schreibe_knoten(self.wurzel, setze_partition)

        ziel.write_bytes(bytes(abbild))
        return ziel

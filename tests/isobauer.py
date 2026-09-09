"""Baut winzige, aber echte ISO9660-Abbilder fuer die Tests.

Damit laesst sich die Erkennung in webui/isoscan.py pruefen, ohne mehrere
Gigabyte herunterzuladen. Die Abbilder haben denselben Aufbau wie echte:

    Sektor 16   Primary Volume Descriptor  (Namen in Grossbuchstaben, ";1")
    Sektor 17   Joliet-Descriptor          (Namen so, wie sie gemeint sind)
    Sektor 18   Abschluss
    danach      Verzeichnisse und Dateiinhalte

Benutzung:

    IsoBauer("MEIN-ABBILD").add("casper/vmlinuz", b"...").schreibe(pfad)
"""

import math

SEKTOR = 2048


def both32(wert):
    return wert.to_bytes(4, "little") + wert.to_bytes(4, "big")


def both16(wert):
    return wert.to_bytes(2, "little") + wert.to_bytes(2, "big")


def datensatz(name: bytes, lba: int, groesse: int, ordner: bool) -> bytes:
    laenge = 33 + len(name)
    laenge += laenge % 2                      # Datensaetze sind immer gerade lang
    satz = bytearray(laenge)
    satz[0] = laenge
    satz[2:10] = both32(lba)
    satz[10:18] = both32(groesse)
    satz[25] = 0x02 if ordner else 0x00
    satz[28:32] = both16(1)
    satz[32] = len(name)
    satz[33:33 + len(name)] = name
    return bytes(satz)


class IsoBauer:
    """Baut ein kleines, aber echtes ISO9660-Abbild mit Joliet."""

    def __init__(self, volume_id="TESTISO"):
        self.volume_id = volume_id
        self.dateien: dict[str, bytes] = {}

    def add(self, pfad: str, inhalt: bytes = b"x"):
        self.dateien[pfad] = inhalt
        return self

    # -- Aufbau ---------------------------------------------------------
    def _baum(self):
        """{Ordnerpfad: (Unterordner, Dateien)} -- "" ist die Wurzel."""
        ordner: dict[str, tuple[set, list]] = {"": (set(), [])}
        for pfad in self.dateien:
            teile = pfad.split("/")
            for i in range(len(teile) - 1):
                eltern = "/".join(teile[:i])
                kind = "/".join(teile[:i + 1])
                ordner.setdefault(kind, (set(), []))
                ordner[eltern][0].add(kind)
            ordner["/".join(teile[:-1])][1].append(pfad)
        return ordner

    def schreibe(self, ziel: Path) -> Path:
        ordner = self._baum()
        pfade = sorted(ordner)

        # Belegung: 16 PVD, 17 SVD, 18 Ende, danach je ein Sektor pro
        # Verzeichnis (einmal primaer, einmal Joliet), dann die Dateien.
        naechster = 19
        primaer_lba, joliet_lba = {}, {}
        for pfad in pfade:
            primaer_lba[pfad] = naechster
            naechster += 1
        for pfad in pfade:
            joliet_lba[pfad] = naechster
            naechster += 1

        datei_lba = {}
        for pfad, inhalt in self.dateien.items():
            datei_lba[pfad] = naechster
            naechster += max(1, math.ceil(len(inhalt) / SEKTOR))

        def verzeichnis(pfad, lba_tabelle, joliet):
            eltern = pfad.rsplit("/", 1)[0] if "/" in pfad else ""
            inhalt = bytearray()
            inhalt += datensatz(b"\x00", lba_tabelle[pfad], SEKTOR, True)
            inhalt += datensatz(b"\x01", lba_tabelle[eltern], SEKTOR, True)
            unter, dateien = ordner[pfad]
            for kind in sorted(unter):
                name = kind.rsplit("/", 1)[-1]
                roh = name.encode("utf-16-be") if joliet else name.upper().encode()
                inhalt += datensatz(roh, lba_tabelle[kind], SEKTOR, True)
            for kind in sorted(dateien):
                name = kind.rsplit("/", 1)[-1]
                roh = (name.encode("utf-16-be") if joliet
                       else (name.upper() + ";1").encode())
                inhalt += datensatz(roh, datei_lba[kind], len(self.dateien[kind]), False)
            assert len(inhalt) <= SEKTOR, f"Testabbild: {pfad} passt nicht in einen Sektor"
            return bytes(inhalt).ljust(SEKTOR, b"\x00")

        abbild = bytearray(naechster * SEKTOR)

        def setze(lba, daten):
            abbild[lba * SEKTOR:lba * SEKTOR + len(daten)] = daten

        def deskriptor(typ, wurzel_lba, joliet):
            block = bytearray(SEKTOR)
            block[0] = typ
            block[1:6] = b"CD001"
            block[6] = 1
            if joliet:
                block[40:72] = self.volume_id.encode("utf-16-be").ljust(32, b"\x00")[:32]
                block[88:91] = b"%/E"
            else:
                block[40:72] = self.volume_id.encode().ljust(32)[:32]
            block[80:88] = both32(naechster)
            block[128:132] = both16(SEKTOR)
            block[156:190] = datensatz(b"\x00", wurzel_lba, SEKTOR, True)
            return bytes(block)

        setze(16, deskriptor(1, primaer_lba[""], False))
        setze(17, deskriptor(2, joliet_lba[""], True))
        ende = bytearray(SEKTOR)
        ende[0] = 255
        ende[1:6] = b"CD001"
        ende[6] = 1
        setze(18, bytes(ende))

        for pfad in pfade:
            setze(primaer_lba[pfad], verzeichnis(pfad, primaer_lba, False))
            setze(joliet_lba[pfad], verzeichnis(pfad, joliet_lba, True))
        for pfad, inhalt in self.dateien.items():
            setze(datei_lba[pfad], inhalt)

        ziel.write_bytes(bytes(abbild))
        return ziel

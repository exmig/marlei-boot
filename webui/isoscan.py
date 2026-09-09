"""
Liest ein ISO-Abbild und erkennt, um welches Betriebssystem es sich handelt.

Warum eigener Code und nicht einfach "bsdtar -tf"?
Ein ISO-Abbild ist ein Dateisystem (ISO9660). Sein Inhaltsverzeichnis steht
an einer festen Stelle am Anfang und ist ein paar Kilobyte gross. Wir muessen
also nicht drei Gigabyte durchlesen, um zu sehen, was drin ist -- ein paar
Sektoren genuegen, das dauert Millisekunden.

Aufbau eines ISO9660-Abbilds (alles in Sektoren zu 2048 Byte):

    Sektor 0-15   Platz fuer Bootloader, fuer uns uninteressant
    Sektor 16     Primary Volume Descriptor: Datentraegername + Wurzelverzeichnis
    Sektor 17..   weitere Descriptoren, u.a. Joliet (Namen mit Gross-/
                  Kleinschreibung und Umlauten), Ende mit Typ 255
    danach        Verzeichnisse und Dateiinhalte

Ein Verzeichnis ist selbst nur eine Datei aus aneinandergereihten
Eintraegen -- jeder nennt Startsektor, Laenge und Namen. Damit laesst sich
der Baum ablaufen und jede Datei direkt lesen: Sektor mal 2048, hinspringen,
Laenge lesen. Genau das machen lies() und entpacke().

Erkannt wird an Dateien, die typisch fuer eine Familie sind -- casper/vmlinuz
gibt es nur bei Ubuntu-Abkoemmlingen, images/pxeboot/vmlinuz nur bei
RedHat-Abkoemmlingen und so weiter.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import udf

SEKTOR = 2048

# Sicherheitsnetze gegen kaputte oder boshafte Abbilder: ohne die wuerde
# ein Abbild mit einer Schleife im Verzeichnisbaum uns endlos beschaeftigen.
MAX_TIEFE = 8
MAX_EINTRAEGE = 40000


# --------------------------------------------------------------------------
# ISO9660 lesen
# --------------------------------------------------------------------------


class IsoFehler(Exception):
    """Das Abbild ist kein lesbares ISO9660."""


@dataclass
class Eintrag:
    pfad: str          # kleingeschrieben, mit "/" getrennt, ohne fuehrenden "/"
    lba: int           # Startsektor
    groesse: int       # Bytes
    ordner: bool
    # Derselbe Pfad in der Schreibweise des Abbilds. Gesucht wird immer
    # kleingeschrieben, herausgeschrieben wird unter diesem Namen -- sonst
    # findet ein Programm im gestarteten System seine Dateien nicht wieder.
    echter_pfad: str = ""
    # Nur bei UDF gefuellt: dort muss eine Datei nicht am Stueck liegen,
    # deshalb eine Liste von (Byte-Offset im Abbild, Laenge). Ist sie leer,
    # gilt der einfache Fall oben -- lba mal Sektorgroesse, dann groesse
    # Bytes am Stueck.
    stuecke: list[tuple[int, int]] = field(default_factory=list)
    # Ebenfalls nur UDF: sehr kleine Dateien stehen direkt im Verzeichnis.
    eingebettet: bytes = b""


class Iso:
    """Ein geoeffnetes ISO-Abbild mit seinem Inhaltsverzeichnis."""

    def __init__(self, pfad: Path):
        self.pfad = Path(pfad)
        self.datei = self.pfad.open("rb")
        self.volume_id = ""
        self.eintraege: dict[str, Eintrag] = {}
        try:
            self._lies_inhaltsverzeichnis()
        except Exception:
            self.datei.close()
            raise

    # -- Kontextmanager, damit die Datei sicher wieder zugeht ---------------
    def __enter__(self) -> "Iso":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        if not self.datei.closed:
            self.datei.close()

    # -- Aufbau -------------------------------------------------------------

    def _sektor(self, nummer: int, anzahl: int = 1) -> bytes:
        self.datei.seek(nummer * SEKTOR)
        return self.datei.read(anzahl * SEKTOR)

    def _lies_inhaltsverzeichnis(self) -> None:
        """Erst ISO9660 -- und wenn dort nichts steht, den UDF-Teil.

        Ein Windows-Medium hat zwar einen ISO9660-Kopf, aber darin liegt
        nichts als ein Hinweiszettel: alle Dateien stecken im UDF-Teil
        (siehe udf.py). Erkennbar ist das daran, dass der Baum kein einziges
        Verzeichnis hat -- ein Abbild mit Betriebssystem hat immer welche.
        """
        try:
            self._lies_iso9660()
        except IsoFehler:
            # Gar kein ISO9660: dann ist UDF die letzte Hoffnung, und wenn
            # auch das nichts hergibt, bleibt es bei der urspruenglichen
            # Meldung -- sie beschreibt den Fall genauer.
            if not self._lies_udf():
                raise
            return

        if not any(eintrag.ordner for eintrag in self.eintraege.values()):
            self._lies_udf()

    def _lies_udf(self) -> bool:
        """Den UDF-Teil einlesen. False, wenn es keinen brauchbaren gibt."""
        try:
            if not udf.hat_udf(self.datei):
                return False
            baum = udf.lies_baum(self.datei)
        except (udf.UdfFehler, OSError, ValueError):
            return False

        # Der Datentraegername bleibt, wo er war: ihn fuehrt auch ein
        # Windows-Medium im ISO9660-Kopf, und dort steht er lesbarer.
        self.eintraege = {
            datei.pfad: Eintrag(
                pfad=datei.pfad, lba=0, groesse=datei.groesse,
                ordner=datei.ordner, echter_pfad=datei.echter_pfad,
                stuecke=datei.stuecke, eingebettet=datei.eingebettet,
            )
            for datei in baum.values()
        }
        return True

    def _lies_iso9660(self) -> None:
        primaer = None      # (Wurzel-Datensatz, Kodierung)
        joliet = None

        for nummer in range(16, 100):
            block = self._sektor(nummer)
            if len(block) < SEKTOR or block[1:6] != b"CD001":
                break
            typ = block[0]
            if typ == 255:                      # Abschluss der Liste
                break
            if typ == 1 and primaer is None:    # Primary Volume Descriptor
                self.volume_id = block[40:72].decode("ascii", "replace").strip()
                primaer = (block[156:190], "iso")
            elif typ == 2 and joliet is None:   # Supplementary: Joliet?
                # Die Fluchtsequenz sagt, dass die Namen in UCS-2 stehen.
                if block[88:91] in (b"%/@", b"%/C", b"%/E"):
                    joliet = (block[156:190], "joliet")

        # Joliet bevorzugen: dort stehen die Namen so, wie sie gemeint sind
        # ("casper" statt "CASPER" und ohne die Endung ";1").
        wurzel = joliet or primaer
        if wurzel is None:
            raise IsoFehler("Kein ISO9660-Datentraeger (Kennung CD001 fehlt)")

        datensatz, kodierung = wurzel
        lba = int.from_bytes(datensatz[2:6], "little")
        groesse = int.from_bytes(datensatz[10:14], "little")
        self._durchlaufe(lba, groesse, "", kodierung, tiefe=0)

    def _durchlaufe(self, lba: int, groesse: int, prefix: str,
                    kodierung: str, tiefe: int) -> None:
        if tiefe > MAX_TIEFE or len(self.eintraege) > MAX_EINTRAEGE:
            return

        anzahl = max(1, (groesse + SEKTOR - 1) // SEKTOR)
        daten = self._sektor(lba, anzahl)[:groesse]
        unterordner: list[tuple[int, int, str]] = []

        pos = 0
        while pos < len(daten):
            laenge = daten[pos]
            if laenge == 0:
                # Datensaetze werden nie ueber eine Sektorgrenze verteilt --
                # eine Null heisst: Rest des Sektors ist leer.
                pos = (pos // SEKTOR + 1) * SEKTOR
                continue
            satz = daten[pos:pos + laenge]
            pos += laenge
            if len(satz) < 33:
                continue

            name_laenge = satz[32]
            roh = satz[33:33 + name_laenge]
            # "." und ".." tragen als Namen ein einzelnes Null- bzw. 0x01-Byte.
            if name_laenge == 1 and roh in (b"\x00", b"\x01"):
                continue

            name = self._name(roh, kodierung)
            if not name:
                continue

            ist_ordner = bool(satz[25] & 0x02)
            kind_lba = int.from_bytes(satz[2:6], "little")
            kind_groesse = int.from_bytes(satz[10:14], "little")
            # Joliet fuehrt die Namen so, wie sie gemeint sind -- dort bleibt
            # die Schreibweise, wie sie ist. Im primaeren ISO9660-Verzeichnis
            # stehen sie per Norm durchgehend gross ("CASPER"), da ist
            # Kleinschreiben die uebliche und richtige Umsetzung.
            echt = f"{prefix}{name}"
            if kodierung != "joliet":
                echt = echt.lower()
            pfad = echt.lower()

            # Mehrteilige Dateien (Flag 0x80) kommen bei Distributions-Abbildern
            # nicht vor; der erste Teil ist trotzdem besser als gar nichts.
            self.eintraege[pfad] = Eintrag(pfad, kind_lba, kind_groesse, ist_ordner, echt)
            if ist_ordner:
                unterordner.append((kind_lba, kind_groesse, echt + "/"))

        for kind_lba, kind_groesse, kind_prefix in unterordner:
            self._durchlaufe(kind_lba, kind_groesse, kind_prefix, kodierung, tiefe + 1)

    @staticmethod
    def _name(roh: bytes, kodierung: str) -> str:
        if kodierung == "joliet":
            name = roh.decode("utf-16-be", "replace")
        else:
            name = roh.decode("ascii", "replace")
        # ISO9660 haengt an Dateinamen eine Versionsnummer an: "VMLINUZ.;1"
        name = re.sub(r";\d+$", "", name)
        if name.endswith(".") and len(name) > 1:
            name = name[:-1]
        return name.strip("\x00").strip()

    # -- Abfragen -----------------------------------------------------------

    def hat(self, pfad: str) -> bool:
        return pfad.lower() in self.eintraege

    def dateien_in(self, ordner: str) -> list[str]:
        """Alle Dateien direkt in diesem Ordner (nicht rekursiv)."""
        prefix = ordner.lower().rstrip("/") + "/"
        return sorted(
            e.echter_pfad for e in self.eintraege.values()
            if not e.ordner and e.pfad.startswith(prefix)
            and "/" not in e.pfad[len(prefix):]
        )

    def erste(self, *kandidaten: str) -> str | None:
        """Den ersten Pfad zurueckgeben, den es wirklich gibt."""
        for pfad in kandidaten:
            eintrag = self.eintraege.get(pfad.lower())
            if eintrag is not None and not eintrag.ordner:
                # Nicht der gesuchte, sondern der tatsaechliche Pfad: unter
                # diesem Namen wird die Datei spaeter auch abgelegt.
                return eintrag.echter_pfad
        return None

    def _bereiche(self, eintrag: Eintrag) -> list[tuple[int, int]]:
        """Wo im Abbild liegen die Daten dieser Datei?

        Bei ISO9660 ist das eine einzige Stelle -- Startsektor mal 2048.
        Bei UDF koennen es mehrere sein: dort darf eine Datei in Stuecken
        abgelegt sein, und bei den grossen ist sie das auch.
        """
        if eintrag.stuecke:
            return eintrag.stuecke
        return [(eintrag.lba * SEKTOR, eintrag.groesse)]

    def lies(self, pfad: str, max_bytes: int = 64 * 1024) -> bytes:
        eintrag = self.eintraege.get(pfad.lower())
        if eintrag is None or eintrag.ordner:
            return b""
        if eintrag.eingebettet:
            return eintrag.eingebettet[:max_bytes]
        teile = []
        offen = min(eintrag.groesse, max_bytes)
        for start, laenge in self._bereiche(eintrag):
            if offen <= 0:
                break
            self.datei.seek(start)
            teile.append(self.datei.read(min(laenge, offen)))
            offen -= laenge
        return b"".join(teile)

    def entpacke(self, pfad: str, ziel: Path) -> bool:
        """Eine einzelne Datei aus dem Abbild herausschreiben."""
        eintrag = self.eintraege.get(pfad.lower())
        if eintrag is None or eintrag.ordner:
            return False
        ziel.parent.mkdir(parents=True, exist_ok=True)

        if eintrag.eingebettet:
            ziel.write_bytes(eintrag.eingebettet[:eintrag.groesse])
            return True

        offen = eintrag.groesse
        with ziel.open("wb") as raus:
            for start, laenge in self._bereiche(eintrag):
                if offen <= 0:
                    break
                self.datei.seek(start)
                rest = min(laenge, offen)
                while rest > 0:
                    brocken = self.datei.read(min(1024 * 1024, rest))
                    if not brocken:
                        break
                    raus.write(brocken)
                    rest -= len(brocken)
                    offen -= len(brocken)
        return offen == 0


# --------------------------------------------------------------------------
# Erkennung
# --------------------------------------------------------------------------


@dataclass
class Befund:
    """Was in dem Abbild steckt und wie man es ueber das Netz startet."""

    familie: str = "unbekannt"
    name: str = ""
    volume_id: str = ""
    startbar: bool = False
    hinweis: str = ""
    # Pfade IM Abbild
    kernel: str | None = None
    initrd: list[str] = field(default_factory=list)
    # {basis} = ${assets}/<slug>, {iso} = Dateiname des Abbilds
    cmdline: str = ""
    # Zweiter Weg fuer grosse Live-Systeme: das Dateisystem liegt auf einem
    # NFS-Export und wird gestreamt, statt in eine RAM-Disk zu wandern.
    # Platzhalter: {nfsroot} = <server>:/srv/pxe/assets/<slug>
    # Leer heisst: fuer diese Familie nicht vorgesehen.
    cmdline_nfs: str = ""
    # Welche Dateien muessen neben dem Abbild ausgepackt werden?
    # Leer und ganzes_iso=True heisst: der komplette Inhalt wird gebraucht.
    dateien: list[str] = field(default_factory=list)
    # Welche Art Start? "kernel" ist der Normalfall (Kernel + Initrd),
    # "wimboot" gilt fuer Windows: dort gibt es keinen Kernel, sondern eine
    # Handvoll Dateien, die unter festen Namen bereitstehen muessen. Deshalb
    # Zielname -> Pfad im Abbild, und getrennt nach Firmware -- BIOS und
    # UEFI starten aus verschiedenen Dateien mit je eigener BCD.
    typ: str = "kernel"
    wimboot_bios: dict[str, str] = field(default_factory=dict)
    wimboot_efi: dict[str, str] = field(default_factory=dict)
    # Welches System aus dem boot.wim gestartet werden soll. Steht erst
    # fest, wenn die Datei ausgepackt ist -- der Anhang mit den Namen liegt
    # an ihrem Ende. 0 heisst: unklar, dann entscheidet wimboot selbst.
    wimboot_index: int = 0
    # Pfad der Installationsquelle im Abbild (sources/install.wim oder
    # .esd). Sie ist mehrere Gigabyte gross und wird zum Starten der
    # Konsole nicht gebraucht -- wohl aber, um Windows zu installieren.
    # Ob sie ausgepackt wird, entscheidet uploads.py: nur wenn eine
    # SMB-Freigabe bereitsteht, denn das Windows-Setup laedt seine Dateien
    # ueber SMB und nicht ueber HTTP.
    windows_quellen: str = ""
    # Was das Medium ueber sich selbst sagt: Generation, Fassung, Sprache
    # und die Ausgaben in der install.wim. Steht wie wimboot_index erst
    # nach dem Auspacken fest, denn die Anhaenge liegen am Ende der
    # WIM-Dateien. Siehe windows_angaben() weiter unten.
    windows_angaben: dict = field(default_factory=dict)
    ganzes_iso: bool = False
    iso_behalten: bool = False


def _klartext(rohtext: bytes) -> str:
    """Erste sinnvolle Zeile aus einer Textdatei im Abbild."""
    for zeile in rohtext.decode("utf-8", "replace").splitlines():
        zeile = zeile.strip()
        if zeile:
            return zeile[:120]
    return ""


def _ucode(iso: Iso, ordner: str) -> list[str]:
    """Mikrocode-Abbilder, die vor der eigentlichen Initrd geladen werden.

    Arch nennt sie intel-ucode.img, SystemRescue intel_ucode.img -- deshalb
    wird gesucht statt geraten. Fehlen sie, ist das kein Problem.
    """
    return [p for p in iso.dateien_in(ordner) if "ucode" in p and p.endswith(".img")]


def _layerfs(iso: Iso) -> str:
    """Den Parameter "layerfs-path" aus der Startkonfiguration des Abbilds holen.

    Ubuntu-Desktop-Abbilder ab 23.10 bestehen aus mehreren aufeinander
    gestapelten Squashfs-Schichten. Welche davon die oberste ist, steht nur in
    grub.cfg -- und ohne diese Angabe findet das Live-System sein
    Wurzeldateisystem nicht.
    """
    for datei in ("boot/grub/grub.cfg", "boot/grub/loopback.cfg", "isolinux/txt.cfg"):
        treffer = re.search(r"layerfs-path=(\S+)", iso.lies(datei, 64 * 1024)
                            .decode("utf-8", "replace"))
        if treffer:
            return " layerfs-path=" + treffer.group(1)
    return ""


def untersuche(pfad: Path) -> Befund:
    """Ein Abbild einordnen und die passende Startanweisung bauen."""
    with Iso(pfad) as iso:
        befund = Befund(volume_id=iso.volume_id)
        # Fast alle Ubuntu-/Debian-Abkoemmlinge legen hier ihren Klarnamen ab.
        info = _klartext(iso.lies(".disk/info", 4096))

        # --- Ubuntu-Familie: Ubuntu, Mint, Pop!_OS, Zorin, elementary ------
        kernel = iso.erste("casper/vmlinuz", "casper/vmlinuz.efi", "casper/hwe-vmlinuz")
        if kernel:
            initrd = iso.erste("casper/initrd", "casper/initrd.lz", "casper/initrd.gz",
                               "casper/initrd.img", "casper/hwe-initrd")
            befund.familie = "casper"
            befund.name = info or iso.volume_id
            befund.kernel = kernel
            befund.initrd = [initrd] if initrd else []
            # Ubuntu ab 23.10 stapelt mehrere Squashfs-Schichten uebereinander
            # und sagt dem Live-System per "layerfs-path", welche oben liegt.
            # Der Wert steht in der Startkonfiguration des Abbilds -- ohne ihn
            # bleibt ein Ubuntu-Desktop beim Start haengen.
            schichten = _layerfs(iso)
            # Der Ubuntu-Server-Installer (subiquity) will das Abbild nur ueber
            # "url="; die Desktop-Ausgaben brauchen zusaetzlich "netboot=url".
            server = "server" in (info + " " + iso.volume_id).lower()
            deutsch = "locale=de_DE.UTF-8 keyboard-configuration/layoutcode=de"
            if server:
                befund.cmdline = "ip=dhcp url={basis}/{iso}" + schichten
            else:
                befund.cmdline = (
                    "boot=casper netboot=url url={basis}/{iso} ip=dhcp "
                    + deutsch + schichten
                )
            # Ueber NFS wird das Dateisystem gestreamt statt geladen: damit
            # startet auch ein 6 GB grosses Desktop-Abbild auf einem Rechner
            # mit 8 GB Arbeitsspeicher.
            befund.cmdline_nfs = (
                "boot=casper netboot=nfs nfsroot={nfsroot} ip=dhcp "
                + deutsch + schichten
            )
            # casper laedt das komplette Abbild in eine RAM-Disk, es bleibt liegen.
            befund.iso_behalten = True
            befund.dateien = [p for p in [kernel, initrd] if p]
            befund.startbar = bool(initrd)
            if not initrd:
                befund.hinweis = "casper/initrd fehlt im Abbild."
            return befund

        # --- Debian-Live: Debian Live, Kali, GParted, Clonezilla ------------
        kernel = iso.erste("live/vmlinuz", "live/vmlinuz1", "live/vmlinuz-amd64")
        squashfs = iso.erste("live/filesystem.squashfs")
        if kernel and squashfs:
            initrd = iso.erste("live/initrd.img", "live/initrd1.img",
                               "live/initrd.img-amd64", "live/initrd")
            befund.familie = "live"
            befund.name = info or iso.volume_id
            befund.kernel = kernel
            befund.initrd = [initrd] if initrd else []
            befund.cmdline = (
                # Kein "ip=dhcp": live-boot liest daraus eine statische
                # Adresse namens "dhcp" und ueberspringt DHCP ganz -- der
                # Start scheitert dann mit "Network is unreachable". Die
                # beiden Timeouts ersetzen die Vorgabe von je 15 Sekunden,
                # einmal fuer die DHCP-Antwort und einmal fuer den Link
                # der Karte. Ausfuehrlich steht das bei den
                # Katalogeintraegen derselben Familie in catalog.yaml.
                "boot=live components ethdevice-timeout=60 "
                "ethdevice-link-timeout=60 "
                "keyboard-layouts=de locales=de_DE.UTF-8 fetch={basis}/" + squashfs
            )
            # Das Wurzeldateisystem wird einzeln geholt, das Abbild selbst
            # danach nicht mehr gebraucht.
            befund.dateien = [p for p in [kernel, initrd, squashfs] if p]
            befund.startbar = bool(initrd)
            if not initrd:
                befund.hinweis = "live/initrd.img fehlt im Abbild."
            return befund

        # --- archiso: Arch Linux, SystemRescue, EndeavourOS ----------------
        for basis in sorted({p.split("/")[0] for p in iso.eintraege}):
            kernel = iso.erste(f"{basis}/boot/x86_64/vmlinuz-linux",
                               f"{basis}/boot/x86_64/vmlinuz")
            if not kernel:
                continue
            initrd = iso.erste(f"{basis}/boot/x86_64/initramfs-linux.img",
                               f"{basis}/boot/x86_64/{basis}.img",
                               f"{basis}/boot/x86_64/initramfs.img")
            befund.familie = "archiso"
            befund.name = iso.volume_id or basis
            befund.kernel = kernel
            # Mikrocode zuerst, danach die eigentliche Initrd -- diese
            # Reihenfolge erwartet der Kernel.
            befund.initrd = _ucode(iso, f"{basis}/boot") + ([initrd] if initrd else [])
            befund.cmdline = (
                f"archisobasedir={basis} archiso_http_srv={{basis}}/ ip=dhcp setkmap=de"
            )
            # archiso holt sich sein Wurzeldateisystem zur Laufzeit per HTTP
            # aus dem entpackten Verzeichnis -- deshalb muss alles raus.
            befund.ganzes_iso = True
            befund.startbar = bool(initrd)
            if not initrd:
                befund.hinweis = "Die Initrd (initramfs-linux.img) fehlt im Abbild."
            return befund

        # --- Anaconda: Fedora, Rocky, AlmaLinux, CentOS --------------------
        kernel = iso.erste("images/pxeboot/vmlinuz")
        if kernel:
            initrd = iso.erste("images/pxeboot/initrd.img")
            name = _klartext(iso.lies(".discinfo", 4096))
            befund.familie = "anaconda"
            # .discinfo beginnt mit einem Zeitstempel, der Name steht in Zeile 2.
            zeilen = iso.lies(".discinfo", 4096).decode("utf-8", "replace").splitlines()
            befund.name = (zeilen[1].strip() if len(zeilen) > 1 else "") or name or iso.volume_id
            befund.kernel = kernel
            befund.initrd = [initrd] if initrd else []
            # inst.repo zeigt auf das entpackte Abbild: damit installiert
            # Anaconda ohne Internet, direkt vom PXE-Server.
            befund.cmdline = "inst.repo={basis}/ ip=dhcp"
            befund.ganzes_iso = True
            befund.startbar = bool(initrd)
            if not initrd:
                befund.hinweis = "images/pxeboot/initrd.img fehlt im Abbild."
            return befund

        # --- linuxrc: openSUSE, SLE ----------------------------------------
        kernel = iso.erste("boot/x86_64/loader/linux")
        if kernel:
            initrd = iso.erste("boot/x86_64/loader/initrd")
            befund.familie = "linuxrc"
            befund.name = _klartext(iso.lies("content", 4096)) or iso.volume_id
            befund.kernel = kernel
            befund.initrd = [initrd] if initrd else []
            befund.cmdline = "install={basis}/ netsetup=dhcp"
            befund.ganzes_iso = True
            befund.startbar = bool(initrd)
            if not initrd:
                befund.hinweis = "boot/x86_64/loader/initrd fehlt im Abbild."
            return befund

        # --- Windows: die Konsole aus dem Abbild, nicht die Installation ---
        # Das boot.wim eines Installationsmediums ist bereits ein fertiges
        # WinPE -- also ein startbares Windows mit Eingabeaufforderung. Genau
        # das holen wir heraus, und dafuer reichen ein paar hundert MB.
        #
        # Die Installation braucht zusaetzlich die mehrere Gigabyte grosse
        # install.wim oder .esd, und die kann ein Windows-Setup nur ueber
        # eine SMB-Freigabe nachladen -- nicht ueber HTTP. Seit B-027 gibt
        # es diese Freigabe, wenn Samba eingerichtet ist; dann wird das
        # ganze Medium ausgepackt statt nur der Startdateien. Entschieden
        # wird das in uploads.py, weil hier noch niemand weiss, ob der
        # Server eine Freigabe hat.
        #
        # Gestartet wird nicht mit Kernel und Initrd, sondern mit wimboot:
        # der Windows-Bootmanager sucht seine Dateien unter festen Namen,
        # deshalb steht hier Zielname -> Pfad im Abbild.
        if iso.erste("sources/boot.wim", "sources/install.wim", "sources/install.esd"):
            befund.familie = "windows"
            befund.name = "Windows-Konsole (WinPE)"
            befund.typ = "wimboot"

            boot_wim = iso.erste("sources/boot.wim")
            sdi = iso.erste("boot/boot.sdi")
            # Die Installationsquelle wird hier nur vermerkt, nicht
            # eingeplant: Ob sie mit ausgepackt wird, haengt daran, ob der
            # Server eine SMB-Freigabe hat.
            befund.windows_quellen = iso.erste(
                "sources/install.wim", "sources/install.esd") or ""

            # BIOS-Satz: bootmgr mit der BCD aus dem boot-Verzeichnis.
            bootmgr = iso.erste("bootmgr")
            bcd = iso.erste("boot/bcd")
            if boot_wim and sdi and bootmgr and bcd:
                befund.wimboot_bios = {
                    "bootmgr": bootmgr,
                    "BCD": bcd,
                    "boot.sdi": sdi,
                    "boot.wim": boot_wim,
                }

            # UEFI-Satz: auf Windows-Medien ist efi/boot/bootx64.efi eine
            # Kopie des Bootmanagers, und die zugehoerige BCD liegt an
            # anderer Stelle -- eine UEFI-Firmware kaeme mit der BIOS-BCD
            # nicht zurecht.
            bootmgfw = iso.erste("efi/boot/bootx64.efi")
            bcd_efi = iso.erste("efi/microsoft/boot/bcd")
            if boot_wim and sdi and bootmgfw and bcd_efi:
                befund.wimboot_efi = {
                    "bootmgfw.efi": bootmgfw,
                    "BCD": bcd_efi,
                    "boot.sdi": sdi,
                    "boot.wim": boot_wim,
                }

            befund.startbar = bool(befund.wimboot_bios or befund.wimboot_efi)
            # Nur die genannten Dateien werden gebraucht -- zusammen ein paar
            # hundert MB. Das Abbild selbst kann danach weg, auch wenn es
            # mehrere Gigabyte gross ist.
            befund.dateien = list(dict.fromkeys(
                [*befund.wimboot_bios.values(), *befund.wimboot_efi.values()]))

            if not befund.startbar:
                # Hierher kommt nur, wessen beide Saetze unvollstaendig sind
                # -- dann ist jede der genannten Dateien wirklich nicht da.
                fehlt = ", ".join(
                    name for name, da in (
                        ("sources/boot.wim", boot_wim), ("boot/boot.sdi", sdi),
                        ("bootmgr", bootmgr), ("boot/bcd", bcd),
                        ("efi/boot/bootx64.efi", bootmgfw),
                        ("efi/microsoft/boot/bcd", bcd_efi),
                    ) if not da)
                befund.hinweis = (
                    "Das ist ein Windows-Abbild, aber die zum Netzwerkstart "
                    f"noetigen Dateien fehlen darin ({fehlt}). Bei einem "
                    "vollstaendigen Installationsmedium sind sie da; fehlen "
                    "sie, wurde das Abbild vermutlich nachtraeglich "
                    "abgespeckt."
                )
            elif not befund.wimboot_efi:
                befund.hinweis = "Nur fuer BIOS-Rechner -- im Abbild fehlt der UEFI-Teil."
            elif not befund.wimboot_bios:
                befund.hinweis = "Nur fuer UEFI-Rechner -- im Abbild fehlt bootmgr."
            elif not befund.windows_quellen:
                # Startbar, aber es laesst sich nichts damit installieren.
                # Das faellt sonst erst auf, wenn jemand setup.exe sucht.
                befund.hinweis = (
                    "Die Konsole startet, aber im Abbild fehlt "
                    "sources/install.wim beziehungsweise install.esd -- "
                    "damit laesst sich Windows nicht installieren."
                )
            return befund

        # --- Erkannt, aber ueber das Netz nicht startbar -------------------
        if iso.erste("install.amd/vmlinuz", "install.386/vmlinuz"):
            befund.familie = "debian-installer"
            befund.name = info or iso.volume_id
            befund.hinweis = (
                "Das ist ein Debian-Installations-Abbild fuer CD/USB. Sein "
                "Installer sucht nach einem Laufwerk und findet ueber das Netz "
                "keines. Fuer Debian den eingebauten Menuepunkt nehmen -- der "
                "benutzt den netboot-Installer und installiert aus dem Netz."
            )
            return befund

        befund.name = iso.volume_id or pfad.name
        befund.hinweis = (
            "Kein bekanntes Startverfahren gefunden. Erkannt werden "
            "Ubuntu/Mint (casper), Debian-Live, Arch/SystemRescue (archiso), "
            "Fedora/Rocky (Anaconda) und openSUSE."
        )
        return befund


def _wim_anhang(pfad: Path) -> str:
    """Der XML-Anhang am Ende einer WIM-Datei. Leer, wenn es keinen gibt.

    Wo er steht, verraet der 208 Byte grosse Kopf. Gelesen werden also zwei
    kleine Haeppchen und nicht die Gigabyte dazwischen -- das gilt auch
    fuer eine install.wim von sechs Gigabyte.
    """
    try:
        with pfad.open("rb") as fh:
            kopf = fh.read(208)
            if len(kopf) < 208 or kopf[:8] != b"MSWIM\x00\x00\x00":
                return ""
            # Der Verweis auf den Anhang: sieben Byte Laenge, ein Byte
            # Merkmale, dann die Position.
            laenge = int.from_bytes(kopf[72:79], "little")
            wo = int.from_bytes(kopf[80:88], "little")
            if not (0 < laenge < 4 * 1024 * 1024) or wo <= 0:
                return ""
            fh.seek(wo)
            return fh.read(laenge).decode("utf-16-le", "replace")
    except OSError:
        return ""


def _anhang_feld(block: str, name: str) -> str:
    """Ein einzelnes Feld aus einem <IMAGE>-Block. Leer, wenn es fehlt."""
    treffer = re.search(f"<{name}>(.*?)</{name}>", block, re.S)
    return treffer.group(1).strip() if treffer else ""


def wim_bilder(pfad: Path) -> list[dict]:
    """Was die WIM ueber ihre Systeme sagt -- ein Eintrag je System.

    Ein boot.wim ist kein einzelnes System, sondern ein Behaelter. Auf einem
    Installationsmedium sind zwei darin:

        1  Microsoft Windows PE      -- startet in die Eingabeaufforderung
        2  Microsoft Windows Setup   -- startet die Windows-Installation

    In einer install.wim stehen stattdessen die Ausgaben, die sich
    installieren lassen -- meist zehn, von Home bis Pro for Workstations.
    """
    bilder = []
    for treffer in re.finditer(r'<IMAGE INDEX="(\d+)">(.*?)</IMAGE>',
                               _wim_anhang(pfad), re.S):
        block = treffer.group(2)
        # MAJOR.MINOR.BUILD.SPBUILD, ohne die Teile, die fehlen.
        fassung = ".".join(x for x in (_anhang_feld(block, "MAJOR"),
                                       _anhang_feld(block, "MINOR"),
                                       _anhang_feld(block, "BUILD"),
                                       _anhang_feld(block, "SPBUILD")) if x)
        bilder.append({
            "nummer": int(treffer.group(1)),
            "name": _anhang_feld(block, "NAME"),
            "ausgabe": _anhang_feld(block, "EDITIONID"),
            "fassung": fassung,
            # <LANGUAGES> kann mehrere enthalten; das erste ist die des
            # Mediums, weitere sind nachgelegte Sprachpakete.
            "sprache": _anhang_feld(block, "LANGUAGE"),
        })
    return bilder


def wim_systeme(pfad: Path) -> list[tuple[int, str]]:
    """Welche Systeme stecken in dieser WIM-Datei? [(Nummer, Name), ...]"""
    return [(bild["nummer"], bild["name"]) for bild in wim_bilder(pfad)]


def wim_konsole(pfad: Path) -> int:
    """Nummer des Systems, das in die Eingabeaufforderung startet. 0 = unklar.

    Warum das gebraucht wird: Ueber das Netz ist das Setup eine Sackgasse.
    Es sucht seine Installationsquellen, findet sie nicht -- die stecken in
    der mehrere Gigabyte grossen install.esd, die hier niemand holt -- und
    meldet, es fehle ein "Medientreiber". Die Meldung ist
    beruehmt-irrefuehrend: mit Treibern hat sie nichts zu tun. Heraus kommt
    man nur mit Umschalt+F10.

    Welches System genommen wird, bekommt wimboot beim Start gesagt
    ("index="). Gesucht wird es am Namen und nicht an der Nummer -- dass die
    Konsole immer die 1 ist, sichert niemand zu.
    """
    for nummer, name in wim_systeme(pfad):
        klein = name.lower()
        if "setup" not in klein and "pe" in klein.split():
            return nummer
    return 0


def _generation_aus_fassung(fassung: str) -> str:
    """Windows 10 oder 11? Die Grenze liegt bei Build 22000.

    Nur der Notnagel fuer Medien ohne install.wim: Eine reine Konsole
    nennt ihre Generation nirgends im Klartext, sie heisst immer
    "Microsoft Windows PE".
    """
    teile = fassung.split(".")
    if len(teile) >= 3 and teile[2].isdigit():
        return "Windows 11" if int(teile[2]) >= 22000 else "Windows 10"
    return ""


def windows_angaben(ordner: Path) -> dict:
    """Was ein ausgepacktes Windows-Medium ueber sich selbst sagt.

    Bis zum 31.08.2026 stand in der Karte eines Windows-Abbilds nur der
    Dateiname, den der Benutzer mitgebracht hat -- er sagt nichts, was
    stimmen muesste. Die Angaben hier stehen in denselben WIM-Anhaengen,
    die ohnehin gelesen werden; sie zu zeigen kostet nichts.

    Wozu sie taugen:

    - Die **Generation** entscheidet, ob die Konsole ueber das Netz
      ueberhaupt startet (B-046: Windows-10-Medien brauchen erst einen
      geraden TargetPath). Sie steht im Klartext im Namen der install.wim.
    - Die **Ausgabe** muss beim Setup jemand auswaehlen. Wer vorher weiss,
      was drin ist, raet nicht.
    - Die **Sprache** erklaert nebenbei die englische Tastatur in der
      Konsole -- sie richtet sich nicht nach dem Medium.
    """
    angaben = {"generation": "", "fassung": "", "sprache": "",
               "ausgaben": [], "winpe": ""}

    konsole = wim_bilder(ordner / "sources/boot.wim")
    if konsole:
        angaben["winpe"] = konsole[0]["fassung"]
        angaben["sprache"] = konsole[0]["sprache"]

    # .esd ist dasselbe in staerker gepackt; der Anhang sitzt an derselben
    # Stelle und sieht gleich aus.
    for name in ("sources/install.wim", "sources/install.esd"):
        bilder = wim_bilder(ordner / name)
        if not bilder:
            continue
        angaben["fassung"] = bilder[0]["fassung"]
        angaben["sprache"] = bilder[0]["sprache"] or angaben["sprache"]
        angaben["ausgaben"] = [bild["name"] for bild in bilder if bild["name"]]
        break

    # "Windows 10 Pro" nennt die Generation im Klartext. Das ist
    # verlaesslicher als jede Grenze bei einer Build-Nummer -- die kommt
    # nur zum Zug, wenn gar keine install.wim dabei ist.
    if angaben["ausgaben"]:
        treffer = re.match(r"(Windows\s+\d+)", angaben["ausgaben"][0])
        if treffer:
            angaben["generation"] = treffer.group(1)
    if not angaben["generation"]:
        angaben["generation"] = _generation_aus_fassung(
            angaben["fassung"] or angaben["winpe"])

    # "Windows 10 Pro" -> "Pro": die Generation steht schon daneben, und
    # zehnmal dasselbe Wort davor liest sich wie ein Formularfehler.
    vorsatz = angaben["generation"] + " "
    if angaben["generation"]:
        angaben["ausgaben"] = [
            name[len(vorsatz):] if name.startswith(vorsatz) else name
            for name in angaben["ausgaben"]]
    return angaben


def platz_reicht(ziel: Path, gebraucht: int) -> bool:
    """Ist genug frei? Mit einem Gigabyte Luft, damit nichts volllaeuft."""
    frei = shutil.disk_usage(ziel).free
    return frei > gebraucht + 1024 ** 3


if __name__ == "__main__":                                 # pragma: no cover
    # Von Hand auf dem Server, wenn ein Abbild sich nicht so verhaelt wie
    # gedacht:
    #
    #   python3 isoscan.py <abbild.iso>    was steckt drin?
    #   python3 isoscan.py <datei.wim>     welche Systeme sind darin?
    import sys

    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[0])
        print()
        print("  python3 isoscan.py <abbild.iso>")
        print("  python3 isoscan.py <datei.wim>")
        raise SystemExit(2)

    if sys.argv[1].lower().endswith(".wim"):
        systeme = wim_systeme(Path(sys.argv[1]))
        if not systeme:
            print("Keine WIM-Datei, oder sie nennt ihre Systeme nicht.")
            raise SystemExit(1)
        konsole = wim_konsole(Path(sys.argv[1]))
        for nummer, name in systeme:
            marke = "  <- die Konsole" if nummer == konsole else ""
            print(f"  {nummer}  {name}{marke}")
        if not konsole:
            print("\nKeines davon sieht nach einer Konsole aus.")
        raise SystemExit(0)

    befund = untersuche(Path(sys.argv[1]))
    print(f"Datentraeger : {befund.volume_id}")
    print(f"Familie      : {befund.familie}")
    print(f"Name         : {befund.name}")
    print(f"Startbar     : {'ja' if befund.startbar else 'nein'}")
    if befund.hinweis:
        print(f"Hinweis      : {befund.hinweis}")
    if befund.typ == "wimboot":
        for art, satz in (("BIOS", befund.wimboot_bios), ("UEFI", befund.wimboot_efi)):
            print(f"{art}         : " + (", ".join(
                f"{name} <- {pfad}" for name, pfad in satz.items()) or "fehlt"))
    else:
        print(f"Kernel       : {befund.kernel}")
        print(f"Initrd       : {befund.initrd}")
        print(f"Kommandozeile: {befund.cmdline}")

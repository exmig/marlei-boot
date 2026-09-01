"""Prueft das Erkennen hochgeladener ISO-Abbilder -- ohne Download.

Die Abbilder dafuer bauen isobauer.py (ISO9660) und udfbauer.py (UDF, so
liegen Windows-Medien vor): echte Struktur, aber nur ein paar Kilobyte
gross. Darin liegen genau die Dateien, an denen isoscan.py eine Familie
erkennt.

    python tests/test_iso.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "webui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from isobauer import IsoBauer  # noqa: E402
from udfbauer import UdfBauer  # noqa: E402

problems = []


def pruefe(bedingung, text):
    if not bedingung:
        problems.append(text)


# --------------------------------------------------------------------------
# Testfaelle
# --------------------------------------------------------------------------

ARBEIT = Path(tempfile.mkdtemp(prefix="pxe-iso-test-"))

# uploads.py liest den Ablageort beim Import -- deshalb vorher setzen.
import os                                                    # noqa: E402
os.environ["PXE_ASSETS"] = str(ARBEIT / "assets")

import isoscan                                               # noqa: E402
import uploads                                               # noqa: E402


def mint_iso(ziel):
    return (IsoBauer("Linux Mint 22.3 Cinnamon 64-bit")
            .add(".disk/info", b"Linux Mint 22.3 \"Zara\" - Release amd64\n")
            .add("casper/vmlinuz", b"KERNEL")
            .add("casper/initrd.lz", b"INITRD")
            .add("casper/filesystem.squashfs", b"ROOT")
            .schreibe(ziel))


def ubuntu_server_iso(ziel):
    return (IsoBauer("Ubuntu-Server 26.04 LTS amd64")
            .add(".disk/info", b"Ubuntu-Server 26.04 LTS \"Resolute\" - Release amd64\n")
            .add("casper/vmlinuz", b"KERNEL")
            .add("casper/initrd", b"INITRD")
            .schreibe(ziel))


def ubuntu_desktop_iso(ziel):
    # Ubuntu-Desktop ab 23.10: mehrere Squashfs-Schichten, und welche oben
    # liegt, steht nur in grub.cfg. Ohne diese Angabe startet es nicht.
    return (IsoBauer("Ubuntu 26.04 LTS amd64")
            .add(".disk/info", b"Ubuntu 26.04 LTS 'Resolute' - Release amd64\n")
            .add("boot/grub/grub.cfg",
                 b"menuentry 'Try or Install Ubuntu' {\n"
                 b"  linux /casper/vmlinuz layerfs-path=minimal.standard.squashfs quiet\n"
                 b"  initrd /casper/initrd\n"
                 b"}\n")
            .add("casper/vmlinuz", b"KERNEL")
            .add("casper/initrd", b"INITRD")
            .add("casper/minimal.squashfs", b"ROOT")
            # Gross geschrieben, genau wie auf einem echten Abbild: snapd
            # sucht beim Partitionieren nach "EFI/boot/boot*.efi".
            .add("EFI/boot/bootx64.efi", b"SHIM")
            .add("EFI/boot/grubx64.efi", b"GRUB")
            .schreibe(ziel))


def debian_live_iso(ziel):
    return (IsoBauer("d-live 13 gnome amd64")
            .add(".disk/info", b"Debian GNU/Linux 13 (trixie) live\n")
            .add("live/vmlinuz", b"KERNEL")
            .add("live/initrd.img", b"INITRD")
            .add("live/filesystem.squashfs", b"ROOT")
            .schreibe(ziel))


def archiso_iso(ziel):
    return (IsoBauer("ARCH_202608")
            .add("arch/boot/x86_64/vmlinuz-linux", b"KERNEL")
            .add("arch/boot/x86_64/initramfs-linux.img", b"INITRD")
            .add("arch/boot/intel-ucode.img", b"UCODE")
            .add("arch/x86_64/airootfs.sfs", b"ROOT")
            .schreibe(ziel))


def fedora_iso(ziel):
    return (IsoBauer("Fedora-S-dvd-x86_64-44")
            .add(".discinfo", b"1755000000\nFedora 44\nx86_64\n")
            .add("images/pxeboot/vmlinuz", b"KERNEL")
            .add("images/pxeboot/initrd.img", b"INITRD")
            .schreibe(ziel))


def opensuse_iso(ziel):
    return (IsoBauer("openSUSE-Leap-16.1-DVD-x86_64")
            .add("content", b"openSUSE Leap 16.1\n")
            .add("boot/x86_64/loader/linux", b"KERNEL")
            .add("boot/x86_64/loader/initrd", b"INITRD")
            .schreibe(ziel))


def boot_wim(startet=2, images=("Windows PE (amd64)", "Windows Setup (amd64)"),
             fassung="", sprache="", ausgaben=()):
    """Ein boot.wim, so weit nachgebaut, wie der Server es liest.

    Ein echtes boot.wim enthaelt zwei Systeme -- die Konsole und das Setup --
    und im Kopf steht, welches davon gestartet wird. Ab Werk ist das das
    Setup, und ueber das Netz endet das in der Meldung, es fehle ein
    Medientreiber. Der Server stellt das um; geprueft wird hier, dass er die
    richtige Zahl an der richtigen Stelle findet.

    Nachgebaut sind der 208 Byte grosse Kopf und der XML-Anhang mit den
    Namen der Systeme; der Rest eines WIM interessiert den Server nicht.

    Mit `fassung`, `sprache` und `ausgaben` laesst sich derselbe Bauer als
    install.wim verwenden -- dort stehen im Anhang dieselben Felder, nur mit
    den Ausgaben statt der beiden Startsysteme.
    """
    namen = list(ausgaben) or list(images)
    teile = []
    for nr, name in enumerate(namen, 1):
        block = f"<NAME>{name}</NAME>"
        if fassung:
            gross, klein, build, sp = (fassung.split(".") + ["", "", "", ""])[:4]
            block += ("<WINDOWS><VERSION>"
                      f"<MAJOR>{gross}</MAJOR><MINOR>{klein}</MINOR>"
                      f"<BUILD>{build}</BUILD><SPBUILD>{sp}</SPBUILD>"
                      "</VERSION></WINDOWS>")
        if sprache:
            block += f"<LANGUAGES><LANGUAGE>{sprache}</LANGUAGE></LANGUAGES>"
        teile.append(f'<IMAGE INDEX="{nr}">{block}</IMAGE>')
    xml = "<WIM>" + "".join(teile) + "</WIM>"
    roh = xml.encode("utf-16-le")
    images = namen

    kopf = bytearray(208)
    kopf[0:8] = b"MSWIM" + bytes(3)
    kopf[8:12] = (208).to_bytes(4, "little")
    kopf[44:48] = len(images).to_bytes(4, "little")
    # Der Verweis auf den XML-Anhang: sieben Byte Laenge, ein Byte Merkmale,
    # dann Position und ungepackte Groesse.
    kopf[72:79] = len(roh).to_bytes(7, "little")
    kopf[80:88] = (208).to_bytes(8, "little")
    kopf[88:96] = len(roh).to_bytes(8, "little")
    kopf[120:124] = startet.to_bytes(4, "little")
    return bytes(kopf) + roh


def windows_iso(ziel):
    """Ein Windows-Medium, wie es fuer BIOS und UEFI gebaut wird.

    Gebaut wird es mit dem UDF-Bauer, denn genau so liegt ein echtes
    Windows-Medium vor: im ISO9660-Teil steht nur ein Zettel, der auf UDF
    verweist, alle Dateien stecken im UDF. Ein Abbild mit denselben Dateien
    im ISO9660 waere ein Test, den es in der Wirklichkeit nicht gibt.

    Nachgebildet sind auch die Eigenheiten, an denen ein UDF-Leser
    scheitern kann: die grosse boot.wim liegt in mehreren Stuecken, die
    kleine BCD steckt direkt im Verzeichniseintrag, und ein Name ist
    16-bittig kodiert.
    """
    return (UdfBauer("CCCOMA_X64FRE_DE-DE_DV9")
            .add("sources/boot.wim", boot_wim(startet=2), stuecke=3)
            .add("sources/install.esd", b"ESD" * 500, stuecke=2)
            .add("bootmgr", b"BOOTMGR")
            .add("boot/bcd", b"regfBCD-BIOS", eingebettet=True)
            .add("boot/boot.sdi", b"$SDI0001")
            .add("efi/boot/bootx64.efi", b"MZBOOTMGFW", breit=True)
            .add("efi/microsoft/boot/bcd", b"regfBCD-EFI")
            .add("setup.exe", b"EXE")
            .schreibe(ziel))


def windows_nur_bios_iso(ziel):
    """Aelteres Medium ohne UEFI-Teil -- der Eintrag darf dann nur fuer
    BIOS-Rechner im Menue stehen."""
    return (UdfBauer("GRMCULFRER_DE_DVD")
            .add("sources/boot.wim",
                 boot_wim(startet=1, images=("Windows PE (amd64)",)))
            .add("bootmgr", b"BOOTMGR")
            .add("boot/bcd", b"regfBCD-BIOS")
            .add("boot/boot.sdi", b"$SDI0001")
            .schreibe(ziel))


def windows_ohne_bootwim_iso(ziel):
    """Ein Windows-Medium, dem die Startdateien fehlen -- erkannt, aber
    nicht zu gebrauchen."""
    return (UdfBauer("CCCOMA_X64FRE_DE-DE_DV9")
            .add("sources/install.esd", b"ESD")
            .add("bootmgr", b"BOOTMGR")
            .schreibe(ziel))


def debian_netinst_iso(ziel):
    return (IsoBauer("Debian 13.0.0 amd64 n")
            .add(".disk/info", b"Debian GNU/Linux 13.0.0 \"Trixie\" - amd64 NETINST\n")
            .add("install.amd/vmlinuz", b"KERNEL")
            .add("install.amd/initrd.gz", b"INITRD")
            .schreibe(ziel))


ERWARTET = [
    # (Bauer, Familie, startbar, Textstueck in der Kommandozeile)
    (mint_iso, "casper", True, "boot=casper netboot=url"),
    (ubuntu_server_iso, "casper", True, "ip=dhcp url="),
    (ubuntu_desktop_iso, "casper", True, "layerfs-path=minimal.standard.squashfs"),
    (debian_live_iso, "live", True, "fetch="),
    (archiso_iso, "archiso", True, "archisobasedir=arch"),
    (fedora_iso, "anaconda", True, "inst.repo="),
    (opensuse_iso, "linuxrc", True, "install="),
    (windows_iso, "windows", True, ""),
    (windows_nur_bios_iso, "windows", True, ""),
    (windows_ohne_bootwim_iso, "windows", False, ""),
    (debian_netinst_iso, "debian-installer", False, ""),
]

print("Erkennung")
for bauer, familie, startbar, teil in ERWARTET:
    pfad = bauer(ARBEIT / (bauer.__name__ + ".iso"))
    befund = isoscan.untersuche(pfad)
    pruefe(befund.familie == familie,
           f"{bauer.__name__}: erkannt als {befund.familie}, erwartet {familie}")
    pruefe(befund.startbar == startbar,
           f"{bauer.__name__}: startbar={befund.startbar}, erwartet {startbar}")
    if teil:
        pruefe(teil in befund.cmdline,
               f"{bauer.__name__}: '{teil}' fehlt in '{befund.cmdline}'")
    if not startbar:
        pruefe(bool(befund.hinweis), f"{bauer.__name__}: Hinweis fehlt")
    print(f"  {bauer.__name__:24s} -> {befund.familie:17s} {befund.name[:40]}")

# Das Mikrocode-Abbild muss vor der eigentlichen Initrd stehen.
arch = isoscan.untersuche(ARBEIT / "archiso_iso.iso")
pruefe(arch.initrd == ["arch/boot/intel-ucode.img", "arch/boot/x86_64/initramfs-linux.img"],
       f"archiso: falsche Initrd-Reihenfolge {arch.initrd}")

# Fuer grosse Desktop-Abbilder muss der NFS-Weg angeboten werden.
desktop = isoscan.untersuche(ARBEIT / "ubuntu_desktop_iso.iso")
pruefe("netboot=nfs nfsroot={nfsroot}" in desktop.cmdline_nfs,
       f"NFS-Variante fehlt: {desktop.cmdline_nfs}")
pruefe("layerfs-path=minimal.standard.squashfs" in desktop.cmdline_nfs,
       "NFS-Variante ohne layerfs-path")

# Schreibweise der Namen: gesucht wird unabhaengig von Gross- und
# Kleinschreibung, abgelegt wird unter dem Namen aus dem Abbild. Ubuntu
# bricht sonst beim Partitionieren ab -- snapd sucht den Bootloader unter
# "/cdrom/EFI/boot/boot*.efi", und "efi" ist auf einem Linux-Dateisystem
# ein anderer Name.
with isoscan.Iso(ARBEIT / "ubuntu_desktop_iso.iso") as abbild:
    pruefe(abbild.hat("efi/boot/bootx64.efi"),
           "kleingeschrieben nicht gefunden -- Suche muss unabhaengig sein")
    pruefe(abbild.hat("EFI/boot/bootx64.efi"),
           "grossgeschrieben nicht gefunden")
    pruefe(abbild.erste("efi/boot/bootx64.efi") == "EFI/boot/bootx64.efi",
           f"echte Schreibweise geht verloren: {abbild.erste('efi/boot/bootx64.efi')}")
    pruefe(abbild.erste("CASPER/VMLINUZ") == "casper/vmlinuz",
           f"Kleinschreibung faelschlich veraendert: {abbild.erste('CASPER/VMLINUZ')}")

    # Und beim Auspacken muss es genauso auf der Platte landen.
    entpackt = ARBEIT / "entpackt"
    for eintrag in abbild.eintraege.values():
        if eintrag.ordner:
            (entpackt / eintrag.echter_pfad).mkdir(parents=True, exist_ok=True)
        elif eintrag.groesse > 0:
            abbild.entpacke(eintrag.pfad, entpackt / eintrag.echter_pfad)
    pruefe(sorted(p.name for p in (entpackt / "EFI" / "boot").iterdir())
           == ["bootx64.efi", "grubx64.efi"],
           "EFI-Verzeichnis landet nicht unter dem richtigen Namen")
    pruefe((entpackt / "casper" / "vmlinuz").is_file(),
           "casper/vmlinuz fehlt nach dem Auspacken")

# Kaputte Datei: klare Fehlermeldung statt Absturz.
kaputt = ARBEIT / "kaputt.iso"
kaputt.write_bytes(b"das ist kein ISO" * 2000)
try:
    isoscan.untersuche(kaputt)
    problems.append("kaputtes Abbild: kein IsoFehler ausgeloest")
except isoscan.IsoFehler:
    pass

# --------------------------------------------------------------------------
print("\nUDF: die Dateien eines Windows-Mediums herauslesen")
# --------------------------------------------------------------------------
# Der ISO9660-Teil eines Windows-Mediums ist leer -- deshalb muss isoscan
# auf den UDF-Teil ausweichen. Geprueft wird nicht nur, dass die Dateien
# gefunden werden, sondern dass ihr Inhalt Byte fuer Byte stimmt. Eine
# Datei aus mehreren Stuecken ist die Stelle, an der ein Leser lautlos
# Unsinn liefert: er nimmt das erste Stueck und haelt sich fuer fertig.

udf_inhalte = {
    "sources/boot.wim": boot_wim(startet=2),                  # drei Stuecke
    "boot/bcd": b"regfBCD-BIOS",                             # im Eintrag selbst
    "efi/boot/bootx64.efi": b"MZBOOTMGFW",                   # 16-bittiger Name
    "bootmgr": b"BOOTMGR",
}
udf_pfad = windows_iso(ARBEIT / "udf_pruefung.iso")

with isoscan.Iso(udf_pfad) as udf_iso:
    pruefe(udf_iso.volume_id == "CCCOMA_X64FRE_DE-DE_DV9",
           f"UDF: Datentraegername aus dem ISO9660-Kopf fehlt ({udf_iso.volume_id!r})")
    pruefe(udf_iso.hat("sources/boot.wim"), "UDF: boot.wim nicht gefunden")
    pruefe(not udf_iso.hat("readme.txt"),
           "UDF: der ISO9660-Zettel sollte vom UDF-Baum abgeloest worden sein")
    for udf_datei, soll in udf_inhalte.items():
        gelesen = udf_iso.lies(udf_datei, 10 ** 6)
        pruefe(gelesen == soll,
               f"UDF: {udf_datei} falsch gelesen "
               f"({len(gelesen)} statt {len(soll)} Bytes)")
        udf_ziel = ARBEIT / "udf_raus.bin"
        pruefe(udf_iso.entpacke(udf_datei, udf_ziel),
               f"UDF: {udf_datei} nicht entpackt")
        pruefe(udf_ziel.read_bytes() == soll, f"UDF: {udf_datei} falsch entpackt")
    print(f"  OK   {len(udf_iso.eintraege)} Eintraege, Inhalte stimmen")

# Ein gewoehnliches Abbild darf davon nichts merken: es hat einen gefuellten
# ISO9660-Teil und wird weiterhin darueber gelesen.
with isoscan.Iso(ARBEIT / "mint_iso.iso") as mint_iso:
    pruefe(not mint_iso.eintraege["casper/vmlinuz"].stuecke,
           "ISO9660-Abbild wurde ueber UDF gelesen -- das waere ein Rueckschritt")

# --------------------------------------------------------------------------
print("\nAblage und Katalogeintrag")
# --------------------------------------------------------------------------

def abbild_von(slug):
    """Wo das Abbild eines Eintrags endgueltig liegt.

    anlegen() nennt die vorlaeufige Datei -- unter diesem Namen kommen die
    Daten an, und erst verarbeite() benennt sie um. Wer hier "ziel" prueft,
    prueft also nach dem Verarbeiten einen Namen, den es nie mehr gibt: Ein
    "not ziel.exists()" waere immer wahr und damit keine Pruefung mehr.
    """
    daten = uploads.lies_zustand(slug) or {}
    return uploads.verzeichnis(slug) / daten.get("datei", "")


slug, ziel = uploads.anlegen("Linux Mint 22.3 Cinnamon.iso")
pruefe(slug.startswith("iso-"), f"Slug ohne Praefix: {slug}")
shutil.copyfile(ARBEIT / "mint_iso.iso", ziel)
zustand = uploads.verarbeite(slug)

pruefe(zustand["status"] == "bereit", f"Mint: Status {zustand['status']} {zustand.get('meldung')}")
eintrag = zustand.get("eintrag", {})
pruefe(eintrag.get("kernel") == f"{slug}/casper/vmlinuz",
       f"falscher Kernelpfad: {eintrag.get('kernel')}")
pruefe((uploads.verzeichnis(slug) / "casper/vmlinuz").exists(), "Kernel nicht entpackt")
pruefe(abbild_von(slug).exists(), "casper braucht das Abbild -- es haette liegenbleiben muessen")
pruefe("${assets}/" + slug in eintrag.get("cmdline", ""),
       f"Kommandozeile ohne ${{assets}}: {eintrag.get('cmdline')}")
pruefe(uploads.katalog_eintraege() and uploads.katalog_eintraege()[0]["slug"] == slug,
       "Eintrag taucht nicht im Katalog auf")

# Kommt spaeter ein NFS-Export dazu, laesst sich derselbe Upload ohne
# erneutes Hochladen umstellen -- solange das Abbild noch daliegt.
pruefe(uploads.alle()[0]["iso_da"], "Mint: Abbild sollte noch daliegen")
uploads.NFS_ROOT = "/srv/pxe/assets"
try:
    umgestellt = uploads.verarbeite(slug)
finally:
    uploads.NFS_ROOT = ""
pruefe(umgestellt.get("weg") == "nfs", f"Umstellen auf NFS: {umgestellt.get('weg')}")
pruefe("nfsroot=" in umgestellt["eintrag"]["cmdline"], "nach dem Umstellen kein nfsroot")
pruefe(not abbild_von(slug).exists(), "nach dem Umstellen wird das Abbild nicht mehr gebraucht")
pruefe(not uploads.alle()[0]["iso_da"], "iso_da muesste jetzt falsch sein")

# Dateiname mit Pfad-Trick darf nicht ausbrechen.
boes, boes_ziel = uploads.anlegen("../../etc/passwd.iso")
pruefe(uploads.ASSETS_DIR in boes_ziel.parents
       and boes_ziel.parent.name.startswith(uploads.UPLOAD_PRAEFIX),
       f"Upload landet ausserhalb: {boes_ziel}")
uploads.loesche(boes)

# Ein Abbild, das komplett entpackt wird: danach ist das ISO selbst weg.
slug2, ziel2 = uploads.anlegen("Fedora-Server-44.iso")
shutil.copyfile(ARBEIT / "fedora_iso.iso", ziel2)
zustand2 = uploads.verarbeite(slug2)
pruefe(zustand2["status"] == "bereit", f"Fedora: Status {zustand2['status']}")
pruefe((uploads.verzeichnis(slug2) / "images/pxeboot/vmlinuz").exists(),
       "Fedora: Baum nicht entpackt")
pruefe(not abbild_von(slug2).exists(), "Fedora: das Abbild wird nicht mehr gebraucht und sollte weg sein")

# Windows: wird zur Konsole (WinPE). Aus dem Abbild kommen nur die
# Startdateien heraus, das Abbild selbst wird danach nicht mehr gebraucht.
slug3, ziel3 = uploads.anlegen("Win11_24H2_German_x64.iso")
shutil.copyfile(ARBEIT / "windows_iso.iso", ziel3)
zustand3 = uploads.verarbeite(slug3)
pruefe(zustand3["status"] == "bereit", f"Windows: Status {zustand3['status']}")
eintrag3 = zustand3["eintrag"]
pruefe(eintrag3["type"] == "wimboot", f"Windows: Typ {eintrag3['type']}")
pruefe(sorted(eintrag3["platforms"]) == ["efi", "pcbios"],
       f"Windows: Plattformen {eintrag3['platforms']}")
pruefe(eintrag3["category"] == "Rettung und Wartung",
       f"Windows: Gruppe {eintrag3['category']}")
# Zwei Windows-Abbilder heissen im Menue beide "Windows-Konsole (WinPE)" --
# auseinanderhalten kann man sie nur am Dateinamen.
pruefe("Win11_24H2_German_x64" in eintrag3["description"],
       f"Windows: Dateiname fehlt in der Beschreibung ({eintrag3['description']})")
# Der Windows-Bootmanager sucht seine Dateien unter festen Namen -- die
# Zuordnung Zielname -> abgelegte Datei ist der ganze Trick an wimboot.
pruefe(eintrag3["wimboot"]["bios"] == {
    "bootmgr": f"{slug3}/bootmgr",
    "BCD": f"{slug3}/boot/bcd",
    "boot.sdi": f"{slug3}/boot/boot.sdi",
    "boot.wim": f"{slug3}/sources/boot.wim",
}, f"Windows: BIOS-Satz {eintrag3['wimboot']['bios']}")
pruefe(eintrag3["wimboot"]["efi"]["bootmgfw.efi"] == f"{slug3}/efi/boot/bootx64.efi",
       "Windows: UEFI nimmt nicht den Bootmanager aus efi/boot")
pruefe(eintrag3["wimboot"]["efi"]["BCD"] == f"{slug3}/efi/microsoft/boot/bcd",
       "Windows: UEFI braucht seine eigene BCD")
for pfad in eintrag3["wimboot"]["efi"].values():
    pruefe((uploads.ASSETS_DIR / pfad).exists(), f"Windows: {pfad} nicht entpackt")
pruefe(not abbild_von(slug3).exists(),
       "Windows: das Abbild wird nach dem Entpacken nicht mehr gebraucht")

# In der boot.wim stecken zwei Systeme: die Konsole und das Windows-Setup.
# Ohne Angabe startet wimboot das, was im Kopf der Datei als startbar
# markiert ist -- auf einem Installationsmedium das Setup, und das sucht
# ueber das Netz vergeblich seine Quellen und meldet, es fehle ein
# "Medientreiber". Der Eintrag muss die Konsole deshalb ausdruecklich
# benennen. Gesucht wird sie am Namen, nicht an der Nummer.
pruefe(eintrag3.get("wimboot_index") == 1,
       f"Windows: falsches System gewaehlt ({eintrag3.get('wimboot_index')})")
pruefe("Index 1" in zustand3.get("wim_start", ""),
       f"Windows: Konsole nicht erkannt ({zustand3.get('wim_start')!r})")

# Die Datei selbst wird dabei nicht angefasst -- sie ist mehrere hundert MB
# gross, und was ausgeliefert wird, soll dem entsprechen, was im Abbild lag.
wim3 = (uploads.verzeichnis(slug3) / "sources/boot.wim").read_bytes()
pruefe(wim3 == boot_wim(startet=2),
       "Windows: das boot.wim wurde veraendert, das soll es nicht")

# --- B-027: die Installationsquellen --------------------------------------
# Das Windows-Setup laedt install.wim beziehungsweise .esd ueber SMB nach,
# nicht ueber HTTP. Ausgepackt wird sie deshalb nur, wenn der Server eine
# Freigabe hat -- sonst laege ein mehrere Gigabyte grosser Brocken herum,
# den niemand erreichen kann.
pruefe(not (uploads.verzeichnis(slug3) / "sources/install.esd").exists(),
       "Windows ohne Freigabe: install.esd sollte gar nicht erst ausgepackt sein")
pruefe(zustand3.get("weg") == "ram",
       f"Windows ohne Freigabe: Weg {zustand3.get('weg')!r}")

# Steht eine Freigabe bereit, wird das ganze Medium ausgepackt.
uploads.SMB_ROOT = "/srv/pxe/assets"
try:
    slug4, ziel4 = uploads.anlegen("Win11_24H2_mit_Quellen.iso")
    shutil.copyfile(ARBEIT / "windows_iso.iso", ziel4)
    zustand4 = uploads.verarbeite(slug4)
finally:
    # Der Wert gilt modulweit -- er darf keinem spaeteren Test nachhaengen.
    uploads.SMB_ROOT = ""

pruefe(zustand4["status"] == "bereit", f"Windows mit Freigabe: Status {zustand4['status']}")
pruefe(zustand4.get("weg") == "smb", f"Windows mit Freigabe: Weg {zustand4.get('weg')!r}")
pruefe((uploads.verzeichnis(slug4) / "sources/install.esd").exists(),
       "Windows mit Freigabe: install.esd fehlt -- ohne sie installiert setup.exe nichts")
pruefe((uploads.verzeichnis(slug4) / "setup.exe").exists(),
       "Windows mit Freigabe: setup.exe fehlt")

# Die Konsole muss davon unberuehrt bleiben: derselbe Eintrag, dasselbe
# System aus dem boot.wim. Die Freigabe kommt erst dazu, wenn dort jemand
# setup.exe aufruft.
eintrag4 = zustand4["eintrag"]
pruefe(eintrag4["type"] == "wimboot", f"Windows mit Freigabe: Typ {eintrag4['type']}")

# Mit Quellen ist der Eintrag kein Rettungswerkzeug mehr, sondern eine
# Installation, die ihre Dateien vom Bootserver bekommt -- genau die Regel,
# nach der die Gruppen sonst vergeben werden.
pruefe(eintrag4["category"] == "Offline-Installationen",
       f"Windows mit Freigabe: Gruppe {eintrag4['category']}")
pruefe(eintrag4["name"] == "Windows-Setup (WinPE-Konsole)",
       f"Windows mit Freigabe: Name {eintrag4['name']!r}")
# Ohne Quellen bleibt es beim Werkzeug -- der Eintrag von oben.
pruefe(eintrag3["category"] == "Rettung und Wartung",
       f"Windows ohne Freigabe: Gruppe {eintrag3['category']}")
pruefe(eintrag4.get("wimboot_index") == 1,
       f"Windows mit Freigabe: falsches System ({eintrag4.get('wimboot_index')})")
pruefe(not abbild_von(slug4).exists(),
       "Windows mit Freigabe: das Abbild wird nach dem Entpacken nicht mehr gebraucht")

# Erkannt wird die Quelle beim Untersuchen -- ein Medium ohne sie ist zwar
# startbar, taugt aber nur als Konsole.
befund_mit = isoscan.untersuche(ARBEIT / "windows_iso.iso")
pruefe(befund_mit.windows_quellen == "sources/install.esd",
       f"Windows: Quelle nicht erkannt ({befund_mit.windows_quellen!r})")
befund_ohne = isoscan.untersuche(ARBEIT / "windows_nur_bios_iso.iso")
pruefe(befund_ohne.windows_quellen == "",
       f"Windows ohne Quelle: {befund_ohne.windows_quellen!r} statt leer")

# Die Systeme werden am Namen unterschieden, auch wenn sie andersherum
# stehen -- die Reihenfolge sichert niemand zu.
verdreht = ARBEIT / "verdreht.wim"
verdreht.write_bytes(boot_wim(startet=1, images=("Windows Setup (amd64)",
                                                "Windows PE (amd64)")))
pruefe(isoscan.wim_konsole(verdreht) == 2,
       f"Windows: Konsole an der falschen Stelle gesucht ({isoscan.wim_konsole(verdreht)})")

# Was kein WIM ist, ergibt keine Auswahl -- und keinen Absturz.
kein_wim = ARBEIT / "kein.wim"
kein_wim.write_bytes(b"nur Text, kein Abbild" * 20)
pruefe(isoscan.wim_konsole(kein_wim) == 0 and isoscan.wim_systeme(kein_wim) == [],
       "Windows: eine fremde Datei sollte keine Systeme melden")
pruefe(not (uploads.verzeichnis(slug3) / "setup.exe").exists(),
       "Windows: es sollen nur die Startdateien herauskommen, nicht das ganze Abbild")
pruefe(any(e["slug"] == slug3 for e in uploads.katalog_eintraege()),
       "Windows: kein Menuepunkt entstanden")

# --------------------------------------------------------------------------
print("\nWas ein Windows-Medium ueber sich selbst sagt")
# --------------------------------------------------------------------------
# Bis zum 31.08.2026 stand in der Karte nur der Dateiname, den der Benutzer
# mitgebracht hat. Generation, Fassung, Sprache und die Ausgaben stehen in
# denselben WIM-Anhaengen, die ohnehin gelesen werden.

winordner = Path(tempfile.mkdtemp(prefix="pxe-winangaben-"))
(winordner / "sources").mkdir(parents=True)
(winordner / "sources/boot.wim").write_bytes(
    boot_wim(fassung="10.0.19041.2965", sprache="de-DE"))
(winordner / "sources/install.wim").write_bytes(
    boot_wim(fassung="10.0.19041.2965", sprache="de-DE",
             ausgaben=("Windows 10 Home", "Windows 10 Pro",
                       "Windows 10 Pro for Workstations")))

angaben = isoscan.windows_angaben(winordner)
pruefe(angaben["generation"] == "Windows 10",
       f"Angaben: Generation {angaben['generation']!r} statt 'Windows 10'")
pruefe(angaben["fassung"] == "10.0.19041.2965",
       f"Angaben: Fassung {angaben['fassung']!r}")
pruefe(angaben["sprache"] == "de-DE", f"Angaben: Sprache {angaben['sprache']!r}")
# Der Vorsatz wird abgeschnitten -- die Generation steht schon daneben.
pruefe(angaben["ausgaben"] == ["Home", "Pro", "Pro for Workstations"],
       f"Angaben: Ausgaben {angaben['ausgaben']}")

# Ein reines Konsolenmedium hat keine install.wim. Dann bleibt die
# Build-Nummer, und deren Grenze liegt bei 22000.
nur_konsole = Path(tempfile.mkdtemp(prefix="pxe-winpe-"))
(nur_konsole / "sources").mkdir(parents=True)
(nur_konsole / "sources/boot.wim").write_bytes(
    boot_wim(fassung="10.0.22621.2861", sprache="de-DE"))
ohne = isoscan.windows_angaben(nur_konsole)
pruefe(ohne["generation"] == "Windows 11",
       f"Angaben ohne install.wim: {ohne['generation']!r} statt 'Windows 11'")
pruefe(ohne["ausgaben"] == [], "Angaben ohne install.wim: es sollte keine Ausgaben geben")
pruefe(ohne["winpe"] == "10.0.22621.2861", f"Angaben: Konsole {ohne['winpe']!r}")

# Kein Windows, keine Angaben -- und vor allem kein Fehler.
leerer = Path(tempfile.mkdtemp(prefix="pxe-nichts-"))
nichts = isoscan.windows_angaben(leerer)
pruefe(nichts["generation"] == "" and nichts["ausgaben"] == [],
       "Angaben: ein Ordner ohne WIM sollte leer ausgehen")

for weg in (winordner, nur_konsole, leerer):
    shutil.rmtree(weg, ignore_errors=True)

# --------------------------------------------------------------------------
print("\nMenuepunkt auffrischen, ohne das Abbild")
# --------------------------------------------------------------------------
# Der teuerste Fall im Betrieb: Eine neue Fassung des Servers baut den
# Menuepunkt anders, aber der abgelegte stammt noch aus der alten -- und das
# Abbild, aus dem er entstand, ist nach dem Entpacken geloescht. Ohne diesen
# Weg bliebe nur, mehrere Gigabyte erneut hochzuladen.

pruefe(not abbild_von(slug3).exists(), "Voraussetzung: das Abbild ist weg")
eintrag_vorher = dict(zustand3["eintrag"])

# So sieht ein Eintrag aus einer aelteren Fassung aus: die Nummer der
# Konsole kannte sie noch nicht.
alt = uploads.lies_zustand(slug3)
alt["eintrag"].pop("wimboot_index", None)
alt.pop("befund", None)
uploads.schreib_zustand(slug3, alt)
pruefe("wimboot_index" not in uploads.lies_zustand(slug3)["eintrag"],
       "Voraussetzung: die Nummer sollte jetzt fehlen")

aufgefrischt = uploads.eintrag_neu_bauen(slug3)
pruefe(aufgefrischt["eintrag"].get("wimboot_index") == 1,
       f"Auffrischen: Nummer fehlt weiter ({aufgefrischt['eintrag'].get('wimboot_index')})")
pruefe(aufgefrischt["eintrag"] == eintrag_vorher,
       "Auffrischen: der Eintrag sieht anders aus als der urspruengliche")
pruefe(aufgefrischt["status"] == "bereit",
       f"Auffrischen: Status {aufgefrischt['status']}")

# Beim zweiten Mal steht der Befund in der Ablage -- dann wird er benutzt
# und nicht wieder aus den Dateien geraten.
pruefe(uploads.lies_zustand(slug3).get("befund", {}).get("familie") == "windows",
       "Auffrischen: der Befund wurde nicht mitgeschrieben")
nochmal = uploads.eintrag_neu_bauen(slug3)
pruefe(nochmal["eintrag"] == eintrag_vorher,
       "Auffrischen: zweiter Lauf liefert etwas anderes")

# Ohne Befund und ohne Dateien geht es nicht -- dann muss das gesagt werden,
# statt einen halben Menuepunkt zu bauen.
leer, leer_ziel = uploads.anlegen("Leer.iso")
uploads.schreib_zustand(leer, {"slug": leer, "datei": "Leer.iso", "status": "bereit"})
try:
    uploads.eintrag_neu_bauen(leer)
    problems.append("Auffrischen: ohne Grundlage haette es scheitern muessen")
except ValueError as fehler:
    pruefe("hochladen" in str(fehler),
           f"Auffrischen: die Meldung nennt den Ausweg nicht ({fehler})")
uploads.loesche(leer)
print("  OK   Nummer nachgetragen, Eintrag unveraendert im Uebrigen")

# Ein Abbild ohne UEFI-Teil darf nur BIOS-Rechnern angeboten werden.
slug3b, ziel3b = uploads.anlegen("Win7.iso")
shutil.copyfile(ARBEIT / "windows_nur_bios_iso.iso", ziel3b)
zustand3b = uploads.verarbeite(slug3b)
pruefe(zustand3b["status"] == "bereit", f"Windows/BIOS: Status {zustand3b['status']}")
pruefe(zustand3b["eintrag"]["platforms"] == ["pcbios"],
       f"Windows/BIOS: Plattformen {zustand3b['eintrag']['platforms']}")
uploads.loesche(slug3b)

# Fehlt das boot.wim, ist nichts zu machen -- und der Grund muss dastehen.
slug3c, ziel3c = uploads.anlegen("Win-kaputt.iso")
shutil.copyfile(ARBEIT / "windows_ohne_bootwim_iso.iso", ziel3c)
zustand3c = uploads.verarbeite(slug3c)
pruefe(zustand3c["status"] == "nicht-startbar", f"Windows/leer: Status {zustand3c['status']}")
pruefe("boot.wim" in zustand3c["meldung"], "Windows/leer: Erklaerung nennt die Datei nicht")
pruefe(all(e["slug"] != slug3c for e in uploads.katalog_eintraege()),
       "Windows/leer: darf nicht im Bootmenue erscheinen")
uploads.loesche(slug3c)

# --------------------------------------------------------------------------
print("\nGrosses Desktop-Abbild ueber NFS")
# --------------------------------------------------------------------------
# Ist ein NFS-Export eingerichtet, wird das Abbild ausgepackt und beim Start
# gestreamt -- sonst muesste es komplett in den Arbeitsspeicher passen.

uploads.NFS_ROOT = "/srv/pxe/assets"
try:
    slug4, ziel4 = uploads.anlegen("ubuntu-26.04-desktop-amd64.iso")
    shutil.copyfile(ARBEIT / "ubuntu_desktop_iso.iso", ziel4)
    zustand4 = uploads.verarbeite(slug4)
finally:
    uploads.NFS_ROOT = ""

pruefe(zustand4["status"] == "bereit", f"Desktop: Status {zustand4['status']}")
pruefe(zustand4.get("weg") == "nfs", f"Desktop: Weg {zustand4.get('weg')}")
cmd4 = zustand4["eintrag"]["cmdline"]
pruefe("nfsroot=${srvip}:/srv/pxe/assets/" + slug4 in cmd4,
       f"falsche NFS-Wurzel: {cmd4}")
pruefe("url=" not in cmd4, f"Desktop laedt immer noch ueber HTTP: {cmd4}")
pruefe((uploads.verzeichnis(slug4) / "casper/minimal.squashfs").exists(),
       "Desktop: Dateisystem nicht entpackt -- NFS haette nichts zu liefern")
pruefe(not abbild_von(slug4).exists(), "Desktop: das Abbild selbst wird nicht mehr gebraucht")
uploads.loesche(slug4)

# --------------------------------------------------------------------------
print("\niPXE-Skript fuer einen Upload")
# --------------------------------------------------------------------------

from jinja2 import Environment, FileSystemLoader                 # noqa: E402

env = Environment(loader=FileSystemLoader(str(PROJ / "webui" / "templates")),
                  autoescape=False, keep_trailing_newline=True)
skript = env.get_template("kernel.ipxe.j2").render(
    base="http://192.168.1.50", srvip="192.168.1.50", entry=eintrag,
    mac="08:00:27:1a:2b:3c")

pruefe(skript.startswith("#!ipxe"), "Skript beginnt nicht mit #!ipxe")
pruefe("kernel ${assets}/iso-" in skript, "Kernel-Zeile fehlt")

# Dieselbe Falle wie in test_katalog.py: iPXE liest fuehrende Bindestriche
# als Optionen und bricht ab.
ERLAUBT = {"--gap", "--default", "--timeout", "--key", "--replace",
           "--no-describe", "--drive", "--name", "--autofree", "--", "-n"}
for nr, zeile in enumerate(skript.splitlines(), 1):
    zeile = zeile.strip()
    if not zeile or zeile.startswith("#") or zeile.startswith(":"):
        continue
    for token in zeile.split()[1:]:
        if not token.startswith("-"):
            break
        if token not in ERLAUBT:
            problems.append(f"kernel.ipxe:{nr}: '{token}' wird als Option gelesen")
            break

print("\n=== boot/" + slug + ".ipxe " + "=" * 30)
print("\n".join(l for l in skript.splitlines() if l and not l.startswith("#")))

# Aufraeumen
uploads.loesche(slug)
uploads.loesche(slug2)
uploads.loesche(slug3)
shutil.rmtree(ARBEIT, ignore_errors=True)

print()
if problems:
    print("PROBLEME:")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("Erkennung und Ablage arbeiten korrekt.")

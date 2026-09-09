"""Rendert alle iPXE-Vorlagen mit realistischen Daten und prueft sie."""
import re
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

PROJ = Path(__file__).resolve().parent.parent
TPL = PROJ / "webui" / "templates"

env = Environment(loader=FileSystemLoader(str(TPL)), autoescape=False,
                  keep_trailing_newline=True)

# Geprueft wird der Katalog so, wie ihn die Anwendung sieht -- also mit
# entfalteten Versionen. Wuerde hier die YAML roh gelesen, blieben in den
# Pfaden "{version}" stehen und der Test pruefte etwas, das nie laeuft.
import os                                                          # noqa: E402
os.environ.setdefault("PXE_CATALOG", str(PROJ / "webui" / "catalog.yaml"))
os.environ.setdefault("PXE_ASSETS", str(PROJ / "tests" / "keine-assets"))
# Wie ein von install.sh aufgesetzter Server: Assets-Verzeichnis und
# NFS-Export sind dasselbe. Fuenf Eintraege haengen darueber ein.
os.environ.setdefault("PXE_NFS_ROOT", str(PROJ / "tests" / "keine-assets"))
os.environ.setdefault("PXE_DB", str(PROJ / "tests" / "keine.db"))
import tempfile                                                    # noqa: E402
_quellen = Path(tempfile.mkdtemp()) / "quellen.env"
os.environ["PXE_QUELLEN"] = str(_quellen)

# Ein Server, auf dem gearbeitet wurde: Die Ausgabenlisten werden seit
# August 2026 leer ausgeliefert -- mitgeliefert ist die Auswahl der
# Distributionen, nicht die Nummer ihrer Ausgabe. Ein Test gegen leere
# Listen pruefte einen Katalog ohne Eintraege. Hier steht deshalb, was
# ein Betreiber unter "Quellen" eingetragen haette.
_quellen.write_text("""
DEBIAN_VERSIONS="trixie"
DEBIAN_LIVE_VERSIONS="13.6.0"
SYSRESC_VERSIONS="13.02"
GPARTED_VERSIONS="1.8.1-3"
CLONEZILLA_VERSIONS="3.3.3-15"
MEMTEST_VERSIONS="8.10"
FEDORA_VERSIONS="44"
LEAP_VERSIONS="16.1"
UBUNTU_VERSIONS="26.04"
ROCKY_VERSIONS="10 9"
""", encoding="utf-8")
sys.path.insert(0, str(PROJ / "webui"))
import app as pxeapp                                               # noqa: E402

entries = pxeapp.load_catalog()

# Dieselben Filter wie in der Anwendung. Sonst prueft der Test eine
# Umgebung, die es so nirgends gibt -- und faellt ueber jeden Filter, den
# eine Vorlage benutzt.
env.filters.update(pxeapp.ipxe.filters)

BASE = "http://192.168.1.50"
MAC = "08:00:27:1a:2b:3c"
problems = []

# Reservierte Slugs duerfen nicht im Katalog vorkommen (sonst Label-Kollision
# mit den Sprungmarken in menu.ipxe.j2).
RESERVED = {"local", "shell", "reboot", "poweroff", "start", "netboot", "fehler"}
slugs = [e["slug"] for e in entries]
for s in slugs:
    if s in RESERVED:
        problems.append(f"Slug '{s}' kollidiert mit einer Sprungmarke")
if len(set(slugs)) != len(slugs):
    problems.append("Doppelte Slugs im Katalog")

# iPXE wertet bei jedem Befehl zuerst Optionen aus und hoert damit beim
# ersten Argument auf, das nicht mit "-" beginnt. Ein dekoratives
# "echo ------" wird deshalb als unbekannte Option gelesen, das Skript
# bricht ab und der Client meldet nur "Could not boot image: Invalid
# argument". Diese Pruefung bildet dieses Verhalten nach.
ERLAUBTE_OPTIONEN = {
    "--gap", "--default", "--timeout", "--key", "--replace",
    "--no-describe", "--drive", "--name", "--autofree", "--", "-n",
}


def pruefe_optionen(tpl, text):
    for nr, zeile in enumerate(text.splitlines(), 1):
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or zeile.startswith(":"):
            continue
        teile = zeile.split()
        for token in teile[1:]:
            if not token.startswith("-"):
                break          # ab hier liest iPXE keine Optionen mehr
            if token not in ERLAUBTE_OPTIONEN:
                problems.append(
                    f"{tpl}:{nr}: '{token}' wird als Option gelesen -> {zeile!r}"
                )
                break


def render(tpl, **ctx):
    out = env.get_template(tpl).render(base=BASE, srvip="192.168.1.50", **ctx)
    if not out.startswith("#!ipxe"):
        problems.append(f"{tpl}: beginnt nicht mit #!ipxe")
    pruefe_optionen(tpl, out)
    return out

# --- Vorspann und Menue ---------------------------------------------------
render("boot.ipxe.j2")

cats = {}
for e in entries:
    if "efi" in e["platforms"]:
        cats.setdefault(e["category"], []).append(e)
menu = render("menu.ipxe.j2", categories=cats, mac=MAC, timeout_ms=30000,
              default="local", platform="efi")

# Jedes Menue-Item muss zu einem Katalog-Eintrag oder Systemeintrag passen
items = [ln.split()[1] for ln in menu.splitlines()
         if ln.startswith("item ") and not ln.startswith("item --gap")]
for it in items:
    if it not in slugs and it not in RESERVED:
        problems.append(f"Menuepunkt '{it}' hat kein Ziel")

# --- Jeder Katalog-Eintrag ------------------------------------------------
tpl_for = {"kernel": "kernel.ipxe.j2", "chain": "chain.ipxe.j2",
           "sanboot": "sanboot.ipxe.j2", "wimboot": "wimboot.ipxe.j2"}
for e in entries:
    name = tpl_for.get(e["type"])
    if name is None:
        problems.append(f"{e['slug']}: unbekannter Typ {e['type']}")
        continue
    out = render(name, entry=e, mac=MAC)
    if e["type"] == "kernel":
        if f"kernel {'${assets}'}/{e['kernel']}" not in out:
            problems.append(f"{e['slug']}: Kernel-Zeile fehlt")
        raw = e.get("initrd", [])
        raw = [raw] if isinstance(raw, str) else raw
        got = sum(1 for ln in out.splitlines() if ln.startswith("initrd "))
        if got != len(raw):
            problems.append(f"{e['slug']}: {got} initrd-Zeilen, erwartet {len(raw)}")
        if "${assets}/" in e.get("cmdline", "") and "set assets" not in out:
            problems.append(f"{e['slug']}: cmdline nutzt ${{assets}}, ist aber nicht gesetzt")

# Stimmt die Gruppe mit dem ueberein, was die Kommandozeile tatsaechlich
# tut? Ein Eintrag, der auf ${assets} oder ${srvip} zeigt, holt alles vom
# Bootserver -- der Client braucht dann kein Internet. Zeigt sie nach
# draussen oder nirgendwohin (dann sucht sich der Installer selbst einen
# Spiegel), ist es umgekehrt. Werkzeuge installieren nichts und stehen
# ausserhalb dieser Einteilung.
OHNE_NETZ = "Offline-Installationen"
MIT_NETZ = "Online-Installationen"

for e in entries:
    if e["category"] not in (OHNE_NETZ, MIT_NETZ):
        continue
    zeile = e.get("cmdline", "") + " " + e.get("url", "")
    # "braucht_nfs" heisst: Der Eintrag hat nur einen Weg, und der geht
    # ueber den NFS-Export dieses Servers -- also auch ohne Internet am
    # Client. Ohne Export ist seine Kommandozeile leer, und die Zeile
    # darunter saehe ihn sonst faelschlich als Online-Installation.
    vom_server = ("${assets}" in zeile or "${srvip}" in zeile
                  or e.get("braucht_nfs"))
    soll = OHNE_NETZ if vom_server else MIT_NETZ
    if e["category"] != soll:
        problems.append(
            f"{e['slug']}: steht unter \"{e['category']}\", die Kommandozeile "
            f"sagt aber \"{soll}\""
        )

# Mehrversionige Eintraege: nach dem Entfalten darf nirgends mehr ein
# Platzhalter stehen, und jede Ausgabe braucht ihr eigenes Verzeichnis --
# sonst ueberschrieben sich zwei Versionen gegenseitig.
mehrfach = [e for e in entries if e.get("version")]
if not mehrfach:
    problems.append("keine mehrversionigen Eintraege gefunden -- Entfaltung kaputt?")
for e in mehrfach:
    alles = " ".join([e["slug"], str(e.get("kernel", "")), str(e.get("initrd", "")),
                      e.get("cmdline", ""), str(e.get("assets", ""))])
    for platzhalter in ("{version}", "{slug}"):
        if platzhalter in alles:
            problems.append(f"{e['slug']}: Platzhalter {platzhalter} nicht ersetzt")

# Die Regel seit August 2026: Ein Eintrag besitzt genau ein Verzeichnis,
# und es traegt seine Kennung. Daran haengt alles -- Belegung, verwaiste
# Ordner, Loeschen. Wer einen Pfad danebenlegt, merkt es sonst erst, wenn
# die Anwendung den Ordner einem anderen zuschlaegt oder zum Loeschen
# anbietet. Ausgenommen ist wimboot: das gehoert allen gemeinsam.
for e in entries:
    for pfad in pxeapp.required_assets(e):
        if pfad.startswith("wimboot/"):
            continue
        if not pfad.startswith(e["slug"] + "/"):
            problems.append(f"{e['slug']}: {pfad} liegt nicht unter {e['slug']}/")

# Die Menue-Info geht auf eine nackte iPXE-Konsole: 29 Zeichen breit und
# ohne Umlaute. Was hier zu lang ist, faellt vor der Maschine ab -- und
# zwar bei jedem Rechner, der bootet, waehrend es hier niemandem auffaellt.
import bezeichnungen as pxebez                                    # noqa: E402
for e in entries:
    info = e.get("menue_info", "")
    if len(info) > pxebez.MAX_INFO:
        problems.append(f"{e['slug']}: menue_info ist {len(info)} Zeichen, "
                        f"erlaubt sind {pxebez.MAX_INFO}")
    if any(ord(z) > 127 for z in info):
        problems.append(f"{e['slug']}: menue_info enthaelt Sonderzeichen — "
                        "iPXE zeigt sie auf einer nackten Konsole")

# Was der Katalog verspricht, muss sync-images.sh auch holen koennen:
# Jeder Eintrag mit eigenen Dateien braucht dort eine Komponente. Fehlt
# sie, steht der Eintrag fuer immer auf "fehlt", ohne dass jemand sagt
# warum -- der Abgleich kennt ihn schlicht nicht.
skript = (PROJ / "setup" / "sync-images.sh").read_text(encoding="utf-8")
treffer = re.search(r"^COMPONENTS=\(([^)]*)\)", skript, re.M)
komponenten = set(treffer.group(1).split()) if treffer else set()
for e in entries:
    if not pxeapp.required_assets(e) or e.get("type") == "chain":
        continue
    basis = e["slug"]
    if e.get("version"):
        basis = basis[: -(len(e["version"].lower().replace(".", "-")) + 1)]
    # Absichtlich locker: Die Namen decken sich nicht eins zu eins --
    # "gparted-live" holt die Komponente "gparted", "memtest-bios" die
    # Komponente "memtest". Gesucht wird deshalb eine Komponente, mit der
    # die Kennung anfaengt. Das faengt den Fall, um den es geht: ein neuer
    # Eintrag mit eigenen Dateien, den der Abgleich gar nicht kennt.
    if not any(basis == k or basis.startswith(k) for k in komponenten):
        problems.append(f"{e['slug']}: keine Komponente in sync-images.sh, "
                        "die das holen koennte")

# Zwei Ausgaben duerfen sich nie denselben Ordner teilen -- die Kennung
# sorgt dafuer, aber nur solange sie wirklich verschieden ist.
kennungen = [e["slug"] for e in mehrfach]
if len(set(kennungen)) != len(kennungen):
    problems.append("zwei Ausgaben teilen sich eine Kennung")

# --- Windows-Konsole (wimboot) --------------------------------------------
# Im Katalog steht kein solcher Eintrag -- er entsteht erst, wenn jemand ein
# Windows-Abbild hochlaedt (webui/uploads.py). Geprueft wird deshalb mit
# einem nachgebauten Eintrag in genau der Form, die uploads.py liefert.
#
# Der springende Punkt ist der zweite Name hinter jedem Pfad: der
# Windows-Bootmanager sucht seine Dateien unter festen Namen, und nur mit
# dieser Angabe legt wimboot sie ihm unter diesen Namen hin. Ohne sie
# startet nichts, ohne eine Fehlermeldung, die das erklaeren wuerde.
winpe = pxeapp._ergaenze({
    "slug": "iso-win11",
    "name": "Windows-Konsole (WinPE)",
    "category": "Rettung und Wartung",
    "platforms": ["pcbios", "efi"],
    "type": "wimboot",
    "wimboot_index": 1,
    "wimboot": {
        "bios": {
            "bootmgr": "upload/iso-win11/bootmgr",
            "BCD": "upload/iso-win11/boot/bcd",
            "boot.sdi": "upload/iso-win11/boot/boot.sdi",
            "boot.wim": "upload/iso-win11/sources/boot.wim",
        },
        "efi": {
            "bootmgfw.efi": "upload/iso-win11/efi/boot/bootx64.efi",
            "BCD": "upload/iso-win11/efi/microsoft/boot/bcd",
            "boot.sdi": "upload/iso-win11/boot/boot.sdi",
            "boot.wim": "upload/iso-win11/sources/boot.wim",
        },
    },
})
winpe_out = render("wimboot.ipxe.j2", entry=winpe, mac=MAC)

if winpe_out.count("kernel ${assets}/wimboot/wimboot index=1") != 2:
    problems.append("wimboot: beide Firmware-Zweige muessen wimboot mit der "
                    "Nummer der Konsole laden")

# Ohne bekannte Nummer darf nichts erfunden werden: dann entscheidet wimboot
# selbst, und der Eintrag startet, was im boot.wim markiert ist.
ohne_wahl = pxeapp._ergaenze(dict(winpe, wimboot_index=0))
if "index=" in render("wimboot.ipxe.j2", entry=ohne_wahl, mac=MAC):
    problems.append("wimboot: ohne bekannte Nummer darf keine mitgegeben werden")
for satz in winpe["wimboot"].values():
    for zielname, pfad in satz.items():
        if f"initrd ${{assets}}/{pfad} {zielname} " not in winpe_out:
            problems.append(f"wimboot: '{pfad}' wird nicht als '{zielname}' bereitgestellt")
# wimboot selbst muss als benoetigte Datei zaehlen. Sonst gaelte der
# Menuepunkt als fertig, waere im Menue und in der Auswahlliste der
# Rechnerseite zu sehen -- und der Rechner bliebe vor der Maschine stehen,
# weil das Programm fehlt, das ihn starten soll.
noetig = pxeapp.required_assets(winpe)
if "wimboot/wimboot" not in noetig:
    problems.append("wimboot: das Programm selbst fehlt in den noetigen Dateien")
for satz in winpe["wimboot"].values():
    for pfad in satz.values():
        if pfad not in noetig:
            problems.append(f"wimboot: '{pfad}' wird nicht als noetige Datei gefuehrt")

# Jede initrd-Zeile braucht hier den Zielnamen -- eine ohne waere die stille
# Variante des Fehlers, den diese Vorlage gerade verhindern soll.
for zeile in winpe_out.splitlines():
    if zeile.startswith("initrd ") and len(zeile.split("||")[0].split()) != 3:
        problems.append(f"wimboot: initrd-Zeile ohne Zielname -> {zeile!r}")
# Reihenfolge: das mehrere hundert MB grosse boot.wim kommt zuletzt, sonst
# steht der Fortschrittsbalken die ganze Zeit auf der ersten Datei.
for block in winpe_out.split(":bios")[0:2]:
    zeilen = [z for z in block.splitlines() if z.startswith("initrd ")]
    if zeilen and "boot.wim" not in zeilen[-1]:
        problems.append("wimboot: boot.wim sollte als letztes geladen werden")

# Ein Abbild ohne UEFI-Teil: der Zweig muss erklaeren statt ins Leere zu laufen.
nur_bios = dict(winpe, wimboot={"bios": winpe["wimboot"]["bios"]},
                platforms=["pcbios"])
nur_bios_out = render("wimboot.ipxe.j2", entry=nur_bios, mac=MAC)
if nur_bios_out.count("kernel ${assets}/wimboot/wimboot") != 1:
    problems.append("wimboot: ohne UEFI-Satz darf kein UEFI-Start versucht werden")
if "keinen UEFI-Startsatz" not in nur_bios_out:
    problems.append("wimboot: fehlender UEFI-Satz wird nicht erklaert")

render("direct.ipxe.j2", entry=entries[0], mac=MAC, name="Testrechner")
for n in ("local.ipxe.j2", "shell.ipxe.j2", "reboot.ipxe.j2"):
    render(n, entry=entries[0], mac=MAC)

print("Katalog:", len(entries), "Eintraege,", len(cats), "Kategorien")
print("Menuepunkte (UEFI-Sicht):", ", ".join(items))
print()
print("=== menu.ipxe (Auszug) " + "=" * 40)
print("\n".join(l for l in menu.splitlines() if l and not l.startswith("#"))[:900])
print()
print("=== boot/systemrescue.ipxe " + "=" * 36)
# SystemRescue ist mehrversionig, der Slug traegt die Ausgabe -- gesucht
# wird deshalb nach dem Anfang.
sr = next(e for e in entries if e["slug"].startswith("systemrescue"))
print("\n".join(l for l in render("kernel.ipxe.j2", entry=sr, mac=MAC).splitlines()
                if l and not l.startswith("#")))
print()
print("=== boot/iso-win11.ipxe (Windows-Konsole) " + "=" * 18)
print("\n".join(l for l in winpe_out.splitlines()
                if l and not l.startswith("#")))
print()
if problems:
    print("PROBLEME:")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("Alle Vorlagen rendern sauber.")

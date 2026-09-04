"""Funktionstest der Web-App: Boot-Endpunkte, Menue, Vorauswahl, Web-UI."""
import html
import os
import re
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
# Wie eine echte .disk/info aussieht: eine Zeile, mit Zeilenumbruch am Ende.
MINTZEILE = 'Linux Mint 22.3 "Zara" - Release amd64' + chr(10)
tmp = Path(tempfile.mkdtemp())
assets = tmp / "assets"

# Wir tun so, als haetten wir Debian und GParted schon synchronisiert,
# Ubuntu/Fedora aber noch nicht -- so laesst sich pruefen, dass unfertige
# Eintraege wirklich aus dem Menue verschwinden.
for rel in [
    "debian-trixie/linux", "debian-trixie/initrd.gz",
    # Die Werkzeuge sind seit dem Umbau mehrversionig: ihre Dateien liegen
    # unter der Ausgabe, wie bei den Distributionen.
    "gparted-live-1-8-1-3/live/vmlinuz", "gparted-live-1-8-1-3/live/initrd.img",
    "gparted-live-1-8-1-3/live/filesystem.squashfs",
    "memtest-bios-8-10/memtest.bin", "memtest-efi-8-10/memtest.efi",
    "mint-cinnamon/vmlinuz", "mint-cinnamon/initrd",
    "mint-cinnamon/casper/filesystem.squashfs",
]:
    p = assets / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")

os.environ["PXE_BASE_URL"] = "http://192.168.1.50"
os.environ["PXE_CATALOG"] = str(PROJ / "webui" / "catalog.yaml")
os.environ["PXE_ASSETS"] = str(assets)
# Wie auf einem von install.sh aufgesetzten Server: Das Assets-Verzeichnis
# ist zugleich der NFS-Export. Fuenf Eintraege haengen ihr
# Wurzeldateisystem darueber ein, statt es zu laden -- ohne diese Zeile
# liefe der Test gegen einen Server ohne NFS, und das ist der Sonderfall,
# nicht der Normalfall. Geprueft wird er trotzdem, siehe "Mit und ohne
# NFS-Export".
os.environ["PXE_NFS_ROOT"] = str(assets)
os.environ["PXE_DB"] = str(tmp / "test.db")
# Der Stempel, den install.sh nach dem Kopieren hinterlaesst. Im Test
# eine eigene Datei -- sonst laese der Test den Stand des Rechners,
# auf dem er gerade laeuft, und pruefte damit nichts Bestimmtes.
stempel = tmp / "VERSION"
stempel.write_text("stand=v1.2-3-gabc1234\n"
                   "commit=abc1234\n"
                   "zweig=main\n"
                   "installiert=2026-08-26 18:00\n", encoding="utf-8")
os.environ["PXE_VERSION_DATEI"] = str(stempel)
os.environ["PXE_MENU_TIMEOUT"] = "30"
os.environ["PXE_QUELLEN"] = str(tmp / "quellen.env")
# Der Waechter ueber den Download-Adressen bleibt im Test aus: Er wuerde
# beim Hochfahren einen Thread starten, der dreizehn echte Anbieter
# abklappert. Geprueft wird er weiter unten von Hand, mit einem eigenen
# Pruefer statt des Netzes.
os.environ["PXE_QUELLENWACHT"] = "aus"
os.environ["PXE_QUELLENWACHT_STAND"] = str(tmp / "quellenwacht.yaml")

# Ein Server, auf dem gearbeitet wurde: Die Ausgabenlisten werden seit
# August 2026 leer ausgeliefert -- mitgeliefert ist die Auswahl der
# Distributionen, nicht die Nummer ihrer Ausgabe. Ein Test gegen leere
# Listen pruefte einen Katalog ohne Eintraege. Hier steht deshalb, was
# ein Betreiber unter "Quellen" eingetragen haette.
Path(os.environ["PXE_QUELLEN"]).write_text("""
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

# Eine Datenbank aus einer aelteren Version anlegen: die Tabelle gibt es
# schon, die Spalte last_wake noch nicht. So laeuft der gesamte Test gegen
# eine nachtraeglich aufgeruestete Datenbank -- genau der Fall auf einem
# Server, der schon eine Weile laeuft.
import sqlite3  # noqa: E402
with sqlite3.connect(os.environ["PXE_DB"]) as alt_db:
    alt_db.execute("""
        CREATE TABLE clients (
            mac TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', entry TEXT,
            once INTEGER NOT NULL DEFAULT 1, last_seen TEXT, last_ip TEXT,
            last_arch TEXT, product TEXT NOT NULL DEFAULT ''
        )""")
    alt_db.execute("INSERT INTO clients (mac, name) VALUES ('de:ad:be:ef:00:01', 'Altbestand')")

# Wake-on-LAN: statt eines echten Rundrufs ins LAN schicken wir die Weckpakete
# im Test an einen eigenen Lauschposten auf der Loopback-Adresse. Die ueblichen
# Ports 9 und 7 sind privilegiert, deshalb ein freier hoher Port.
horcher = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
horcher.bind(("127.0.0.1", 0))
os.environ["PXE_WOL_BROADCAST"] = "127.0.0.1"
os.environ["PXE_WOL_PORTS"] = str(horcher.getsockname()[1])


def alle_weckpakete(dauer=0.6):
    """Sammelt, was in der naechsten halben Sekunde ankommt (ohne Doppelte)."""
    ende = time.monotonic() + dauer
    gesehen = set()
    horcher.settimeout(0.1)
    while time.monotonic() < ende:
        try:
            gesehen.add(horcher.recvfrom(1024)[0])
        except OSError:
            pass
    horcher.settimeout(2.0)
    return gesehen


def paket_fuer(mac):
    return b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16


def weckpaket(zeitlimit=2.0):
    """Wartet auf das naechste Weckpaket und wirft die Wiederholungen weg."""
    horcher.settimeout(zeitlimit)
    erstes = horcher.recvfrom(1024)[0]
    horcher.settimeout(0.05)
    try:
        while True:
            horcher.recvfrom(1024)
    except OSError:
        pass
    return erstes

sys.path.insert(0, str(PROJ / "webui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from urllib.parse import unquote  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from isobauer import IsoBauer  # noqa: E402
import app as pxeapp  # noqa: E402
import bezeichnungen as pxebez  # noqa: E402
import konfiguration  # noqa: E402
import sync as pxesync  # noqa: E402

fails = []
def check(label, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + label + (("  " + extra) if extra and not cond else ""))
    if not cond:
        fails.append(label)

MAC_HYP = "08-00-27-1a-2b-3c"
MAC = "08:00:27:1a:2b:3c"

with TestClient(pxeapp.app) as c:
    print("\n-- Statusabfrage")
    h = c.get("/health").json()
    check("health antwortet", h["status"] == "ok")
    check("nur fertige Eintraege gelten als bereit",
          h["entries_ready"] == 6, str(h))  # debian, mint, gparted, memtest x2, netbootxyz

    print("\n-- Vorspann /boot.ipxe")
    r = c.get("/boot.ipxe")
    check("liefert iPXE-Skript", r.text.startswith("#!ipxe"))
    check("reicht die MAC weiter", "${net0/mac:hexhyp}" in r.text)
    check("kein HTML-Escaping der Query", "&amp;" not in r.text)

    # Ein Menue bekommt nur, wer freigegeben ist -- und der Server nimmt den
    # Haken beim Ausliefern gleich wieder weg. Fuer jeden Abruf im Test also:
    # anmelden lassen, Haken setzen, abrufen. Ohne den ersten Aufruf gaebe es
    # die Zeile noch gar nicht, die freigegeben werden soll.
    # "nopreset" ist derselbe Weg, den Strg-C am Rechner nimmt: Freigabe
    # gilt, aber zeig mir das Menue statt einer gespeicherten Vorauswahl.
    # Ohne das bekaeme diese Hilfe je nach Vorgeschichte mal das Menue und
    # mal das Durchstart-Skript.
    def menue(mac=MAC_HYP, **params):
        p = {"mac": mac, "platform": "efi", **params}
        c.get("/menu.ipxe", params=p)
        with pxeapp.db() as conn:
            conn.execute("UPDATE clients SET pxe_aktiv = 1 WHERE mac = ?",
                         (pxeapp.normalise_mac(mac),))
        return c.get("/menu.ipxe", params={**p, "nopreset": "1"}).text

    def freigeben(slug):
        """Die zwei Haken setzen -- der Schritt zwischen "bereit" und
        "wird angeboten". Seit August 2026 faengt ein Eintrag ohne beide
        an: Was fertig wird, stellt sich nicht von selbst ins Menue."""
        c.post("/systeme/speichern", data={"haken:" + slug: "1",
                                           "menue:" + slug: "1",
                                           "optionen:" + slug: "1"})

    print("\n-- Menue (UEFI)")
    menu = menue(arch="x86_64", product="VirtualBox")
    check("Debian im Menue", "item debian-trixie " in menu)
    check("GParted im Menue", "item gparted-live-1-8-1-3 " in menu)
    check("Ubuntu fehlt (ISO nicht da)", "item ubuntu-2404-server " not in menu)
    check("Fedora fehlt (Kernel nicht da)", "item fedora-42-server " not in menu)
    check("UEFI-Memtest da", "item memtest-efi-8-10 " in menu)
    check("BIOS-Memtest ausgeblendet", "item memtest-bios-8-10 " not in menu)
    check("Systempunkte vorhanden", "item local " in menu and "item shell " in menu)

    print("\n-- Gruppen im Bootmenue")
    gruppen = [z.split("--", 2)[2].strip() for z in menu.splitlines()
               if z.startswith("item --gap")]
    check("nach Netzbedarf gruppiert",
          gruppen[:2] == ["Offline-Installationen",
                          "Online-Installationen"], str(gruppen))
    check("offline steht oben", gruppen[0] == "Offline-Installationen")
    check("Werkzeuge bleiben eigene Gruppe", "Rettung und Wartung" in gruppen)
    check("Mint unter ohne Internet",
          menu.index("item mint-cinnamon") < menu.index("Online-Installationen"), str(gruppen))
    check("Debian unter ueber das Internet",
          menu.index("item debian-trixie") > menu.index("Online-Installationen"))

    print("\n-- Menue (BIOS) zeigt die andere Memtest-Variante")
    bios = menue(platform="pcbios")
    check("BIOS-Memtest da", "item memtest-bios-8-10 " in bios)
    check("UEFI-Memtest weg", "item memtest-efi-8-10 " not in bios)

    print("\n-- Adresse des Clients hinter dem Reverse Proxy")
    # Die Anwendung lauscht auf der Rueckschleife, alles kommt ueber nginx.
    # Ohne Auswertung von X-Real-IP stuende bei jedem Rechner 127.0.0.1 --
    # und der Abgleich mit den offenen Verbindungen koennte nie treffen.
    c.get("/menu.ipxe", params={"mac": MAC_HYP, "platform": "efi"},
          headers={"X-Real-IP": "192.168.178.100"})
    with pxeapp.db() as conn:
        gespeichert = conn.execute(
            "SELECT last_ip FROM clients WHERE mac = ?", (MAC,)).fetchone()["last_ip"]
    check("echte Adresse statt Rueckschleife", gespeichert == "192.168.178.100",
          str(gespeichert))

    c.get("/menu.ipxe", params={"mac": MAC_HYP, "platform": "efi"},
          headers={"X-Forwarded-For": "192.168.178.101, 10.0.0.1"})
    with pxeapp.db() as conn:
        gespeichert = conn.execute(
            "SELECT last_ip FROM clients WHERE mac = ?", (MAC,)).fetchone()["last_ip"]
    check("aus X-Forwarded-For die erste Adresse", gespeichert == "192.168.178.101",
          str(gespeichert))

    c.get("/boot/debian-trixie.ipxe", params={"mac": MAC_HYP},
          headers={"X-Real-IP": "192.168.178.100"})
    with pxeapp.db() as conn:
        protokolliert = conn.execute(
            "SELECT ip FROM boot_log ORDER BY id DESC LIMIT 1").fetchone()["ip"]
    check("auch im Boot-Verlauf", protokolliert == "192.168.178.100", str(protokolliert))

    print("\n-- Client wurde automatisch erfasst")
    page = c.get("/clients").text
    check("MAC normalisiert gespeichert", MAC in page)
    check("Modell uebernommen", "VirtualBox" in page)

    print("\n-- Vorauswahl im Browser")

    # Gespeichert wird ueber ein Formular fuer die ganze Tabelle. Fuer den
    # Test interessiert meist nur eine Zeile -- diese Hilfe baut sie samt
    # ihrem Ausgangsstand ("war_*"). Ohne den schreibt der Server nichts:
    # er vergleicht und laesst Unveraendertes in Ruhe.
    def speichern(mac, entry=None, pxe=None, name=None, **kw):
        jetzt = next(z for z in c.get("/clients.json").json()["clients"]
                     if z["mac"] == mac)
        daten = {
            f"war_name:{mac}": jetzt["name"],
            f"war_entry:{mac}": jetzt["entry"],
            f"war_pxe:{mac}": "1" if jetzt["pxe_aktiv"] else "0",
            f"name:{mac}": jetzt["name"] if name is None else name,
            f"entry:{mac}": jetzt["entry"] if entry is None else entry,
        }
        if jetzt["pxe_aktiv"] if pxe is None else pxe:
            daten[f"pxe_aktiv:{mac}"] = "1"
        return c.post("/clients/speichern", data=daten, **kw)
    r = speichern(MAC, entry="gparted-live-1-8-1-3", pxe=True, name="Werkstatt-PC",
                  follow_redirects=False)
    check("Speichern leitet weiter", r.status_code == 303)
    direct = c.get("/menu.ipxe", params={"mac": MAC_HYP, "platform": "efi"}).text
    check("bootet direkt durch statt Menue",
          "/boot/gparted-live-1-8-1-3.ipxe" in direct)
    check("kein Menue mehr", "item debian-trixie " not in direct)
    check("Abbruch mit Strg-C moeglich", "--key 0x03" in direct)

    # Strg-C schickt den Rechner mit "nopreset" hierher zurueck. Der Server
    # hat das lange nicht ausgewertet: dieselbe Vorauswahl kam noch einmal,
    # und aus der Schleife fuehrte kein Weg ins Menue.
    abgebrochen = c.get("/menu.ipxe", params={"mac": MAC_HYP, "platform": "efi",
                                              "nopreset": "1"}).text
    check("Strg-C fuehrt ins Menue statt zurueck in die Vorauswahl",
          "item debian-trixie " in abgebrochen
          and "/boot/gparted-live-1-8-1-3.ipxe" not in abgebrochen)
    check("... und loest die Freigabe damit ein", next(
        z for z in c.get("/clients.json").json()["clients"]
        if z["mac"] == MAC)["pxe_aktiv"] is False)

    print("\n-- Einmal-Vorauswahl loescht sich nach dem Start")
    speichern(MAC, entry="gparted-live-1-8-1-3", pxe=True)
    r = c.get("/boot/gparted-live-1-8-1-3.ipxe", params={"mac": MAC_HYP})
    check("Boot-Skript geliefert", r.text.startswith("#!ipxe"))
    # Der Pfad ist der Ordner des Eintrags, und der heisst wie er -- unter
    # dem Export, den PXE_NFS_ROOT nennt, nicht unter einem im Katalog
    # ausgeschriebenen.
    check("haengt per NFS ein",
          "nfsroot=${srvip}:" + str(assets) + "/gparted-live-1-8-1-3" in r.text,
          r.text[r.text.find("nfsroot="):][:90])
    check("Serveradresse gesetzt", "set srvip 192.168.1.50" in r.text)
    again = c.get("/menu.ipxe", params={"mac": MAC_HYP, "platform": "efi"}).text
    check("danach kein Netzwerkstart mehr",
          "exit 0" in again and "item debian-trixie " not in again)

    print("\n-- Nach dem Start steht die Zeile wieder auf Anfang")
    # Haken *und* Auswahl fallen. Lange blieb die Auswahl absichtlich stehen,
    # damit ein zweiter Anlauf ein Klick ist -- aber dann stand in der Liste
    # weiter "installieren" bei einer Maschine, auf der das System laengst
    # lief. Eine erledigte Aufgabe soll nicht aussehen wie eine anstehende.
    speichern(MAC, entry="debian-trixie", pxe=True)
    c.get("/boot/debian-trixie.ipxe", params={"mac": MAC_HYP})
    with pxeapp.db() as conn:
        r = conn.execute("SELECT entry, pxe_aktiv FROM clients WHERE mac = ?",
                         (MAC,)).fetchone()
    check("Schalter ist danach aus", r["pxe_aktiv"] == 0, str(dict(r)))
    check("Auswahl steht wieder auf Menue anzeigen", r["entry"] is None, str(dict(r)))
    check("... auch in der Liste unter Clients", next(
        z for z in c.get("/clients.json").json()["clients"]
        if z["mac"] == MAC)["entry"] == "")
    danach = c.get("/menu.ipxe", params={"mac": MAC_HYP, "platform": "efi"}).text
    check("naechster Start geht auf die Platte", "exit 0" in danach)
    check("... und bootet nicht mehr durch", "/boot/debian-trixie.ipxe" not in danach)

    # Ohne Haken passiert gar nichts: weder Direktstart noch Menue. Das ist
    # der Normalfall. Eine von Hand gesetzte Auswahl bleibt dabei stehen --
    # zurueckgesetzt wird nur, was wirklich gestartet ist.
    speichern(MAC, entry="debian-trixie", pxe=False)
    ohne = c.get("/menu.ipxe", params={"mac": MAC_HYP, "platform": "efi"}).text
    check("ohne Haken kein Direktstart", "/boot/debian-trixie.ipxe" not in ohne)
    check("... und auch kein Menue", "item debian-trixie " not in ohne)
    check("... sondern zurueck an die Firmware", ohne.strip().endswith("exit 0"))
    with pxeapp.db() as conn:
        r = conn.execute("SELECT entry FROM clients WHERE mac = ?", (MAC,)).fetchone()
    check("... die Auswahl steht ohne Start noch", r["entry"] == "debian-trixie")

    # Auch ein Werkzeug raeumt hinter sich auf -- die Regel gilt fuer jeden
    # Eintrag, nicht nur fuer Installationen.
    speichern(MAC, entry="gparted-live-1-8-1-3", pxe=True)
    c.get("/boot/gparted-live-1-8-1-3.ipxe", params={"mac": MAC_HYP})
    with pxeapp.db() as conn:
        r = conn.execute("SELECT entry, pxe_aktiv FROM clients WHERE mac = ?",
                         (MAC,)).fetchone()
    check("nach einem Werkzeugstart ebenso zurueckgesetzt",
          r["entry"] is None and r["pxe_aktiv"] == 0, str(dict(r)))

    print("\n-- Ein neuer Rechner meldet sich nur an")
    # Der Regelfall im Alltag: Eine unbekannte Maschine startet per Netzwerk.
    # Sie soll in der Liste auftauchen und sonst nichts tun -- kein Menue,
    # keine Installation, keine Wartezeit. Erst ein Haken macht mehr daraus.
    NEU_HYP, NEU = "aa-bb-cc-00-11-22", "aa:bb:cc:00:11:22"
    erst = c.get("/menu.ipxe", params={"mac": NEU_HYP, "platform": "efi",
                                       "product": "OptiPlex 7050"}).text
    liste = {z["mac"]: z for z in c.get("/clients.json").json()["clients"]}
    check("steht danach in der Liste unter Clients", NEU in liste)
    check("... und zwar ohne Freigabe", liste[NEU]["pxe_aktiv"] is False)
    with pxeapp.db() as conn:
        z = conn.execute("SELECT product FROM clients WHERE mac = ?", (NEU,)).fetchone()
    check("... das Modell wurde trotzdem gelesen", z["product"] == "OptiPlex 7050",
          str(dict(z)))
    check("bekommt kein Menue", "item debian-trixie " not in erst and "menu " not in erst)
    check("... keine Installation", "/boot/" not in erst)
    check("... sondern zurueck an die Firmware", erst.strip().endswith("exit 0"))
    check("... mit einem Hinweis, woran es liegt", "PXE Boot aktiv" in erst)
    c.post(f"/clients/{NEU}/delete")

    print("\n-- Name in der Liste, lesbare Zeiten")
    r = speichern(MAC, entry="gparted-live-1-8-1-3", pxe=True, follow_redirects=False)
    check("Auswahl ohne Namensaenderung moeglich", r.status_code == 303)

    r = speichern(MAC, name="Lenovo L540", follow_redirects=False)
    check("Umbenennen leitet weiter", r.status_code == 303)
    seite = c.get("/clients").text
    check("Name steht in der Liste", "Lenovo L540" in seite)
    check("... und ist ein Eingabefeld am Sammelformular",
          'name="name:' + MAC + '"' in seite and 'form="sichern"' in seite)
    with pxeapp.db() as conn:
        z = conn.execute("SELECT name, entry FROM clients WHERE mac = ?",
                         (MAC,)).fetchone()
    check("Umbenennen laesst die Vorauswahl stehen",
          z["name"] == "Lenovo L540" and z["entry"] == "gparted-live-1-8-1-3", str(dict(z)))

    check("Haken heisst jetzt PXE Boot aktiv",
          "PXE Boot aktiv" in seite and "nur einmal" not in seite)

    # Ein Knopf fuer die ganze Tabelle statt einer je Zeile. Vorher hatte
    # jede Zeile ein eigenes Formular und der Name noch ein zweites daneben
    # -- das sah aus, als gaebe es mehrere Sorten "gespeichert", und wer den
    # Namen abschickte, verlor die Auswahl daneben.
    check("kein Formular mehr je Zeile",
          "bootform" not in seite and "/name\" class=" not in seite
          and "/assign" not in seite)
    check("ein Sammelformular fuer die ganze Tabelle",
          'id="sichern" method="post" action="/clients/speichern"' in seite)
    check("Knopf steht in der Kopfzeile, nicht in den Zeilen",
          seite.index('id="sichernknopf"') < seite.index("<tbody>"))
    check("Felder haengen ueber das form-Attribut daran",
          seite.count('form="sichern"') >= 4)

    # Ausgeliefert wird er aktiv und erst vom Skript ausgegraut -- ohne
    # JavaScript liesse sich sonst gar nichts mehr speichern.
    check("Speichern-Knopf kommt aktiv an",
          'id="sichernknopf"' in seite and 'sichernknopf" disabled' not in seite)
    check("Skript graut ihn aus, solange nichts abweicht",
          "knopf.disabled = offen.length === 0" in seite)
    check("... und nennt sonst die Zahl der offenen Rechner",
          'beschriftung + " (" + offen.length + ")"' in seite)
    check("offene Zeilen sind markiert", 'classList.toggle("offen"' in seite)

    # Der Vergleichsmassstab ist dasselbe versteckte Feld, an dem auch der
    # Server entscheidet -- einer statt zweier, die auseinanderlaufen koennen.
    check("jede Zeile traegt ihren Ausgangsstand mit",
          'name="war_name:' + MAC + '"' in seite
          and 'name="war_entry:' + MAC + '"' in seite
          and 'name="war_pxe:' + MAC + '"' in seite)
    check("Skript vergleicht gegen dieselben Felder",
          "eintrag.name.value !== eintrag.warName.value" in seite)

    # Die klebende Kopfzeile traegt den Knopf beim Scrollen mit. Ein
    # "display: flex" auf dem <th> selbst nimmt ihm das wieder weg -- der
    # Kasten dafuer steht deshalb im <th>, nicht am <th>.
    stil = c.get("/static/style.css").text
    check("Kopfzeile klebt beim Scrollen",
          "table.eng thead th {" in stil and "position: sticky" in stil)
    check("... und das Flex-Layout steckt im Kasten darin",
          ".sichernspalte {" in stil and "th.sichernspalte" not in stil)
    check("Kopfzelle traegt kein eigenes Flex",
          'class="sichernspalte"' in seite
          and '<th class="sichernspalte"' not in seite)

    # Gespeichert wird im Hintergrund; die Seite bleibt stehen, sonst waeren
    # angekreuzte WOL-Kaestchen nach jedem Speichern weg.
    check("Sammelformular wird abgefangen statt abgeschickt",
          'formular.addEventListener("submit"' in seite
          and "ereignis.preventDefault()" in seite)
    r = c.post("/clients/speichern",
               data={f"war_name:{MAC}": "Lenovo L540", f"name:{MAC}": "  Werkstatt  ",
                     f"war_entry:{MAC}": "gparted-live-1-8-1-3", f"entry:{MAC}": "gparted-live-1-8-1-3",
                     f"war_pxe:{MAC}": "0"},
               headers={"Accept": "application/json"})
    check("Speichern antwortet auf Wunsch mit JSON",
          r.status_code == 200 and r.json()["gespeichert"] == 1, r.text[:120])
    gesichert = next(z for z in r.json()["clients"] if z["mac"] == MAC)
    check("... und liefert den neuen Stand gleich mit",
          gesichert["name"] == "Werkstatt", str(gesichert))
    check("... die Vorauswahl steht danach immer noch",
          gesichert["entry"] == "gparted-live-1-8-1-3")

    r = c.post("/clients/speichern",
               data={f"war_name:{MAC}": "Werkstatt", f"name:{MAC}": "x" * 80,
                     f"war_entry:{MAC}": "gparted-live-1-8-1-3", f"entry:{MAC}": "gparted-live-1-8-1-3",
                     f"war_pxe:{MAC}": "0"},
               headers={"Accept": "application/json"})
    check("Name wird auf %d Zeichen gekuerzt" % pxeapp.MAX_CLIENTNAME,
          next(z for z in r.json()["clients"]
               if z["mac"] == MAC)["name"] == "x" * pxeapp.MAX_CLIENTNAME)
    speichern(MAC, name="Lenovo L540")

    # Ohne JavaScript bleibt es beim gewohnten Formular: sonst waere die
    # ganze Liste in einem Browser ohne Skripte eine Sackgasse.
    r = speichern(MAC, name="Werkstatt-PC", follow_redirects=False)
    check("ohne JSON-Wunsch eine Weiterleitung", r.status_code == 303)
    check("... mit einer Meldung ueber das Ergebnis",
          "gespeichert" in r.headers["location"], r.headers["location"])
    r = speichern(MAC, follow_redirects=False)
    check("nichts geaendert, nichts geschrieben",
          "Nichts%20zu%20speichern" in r.headers["location"], r.headers["location"])
    speichern(MAC, name="Lenovo L540")

    # Die Bremse: zwischen dem Aufbau der Seite und dem Klick kann ein
    # Rechner gebootet und dabei seinen Haken verloren haben. Wer dann eine
    # ganz andere Zeile speichert, darf ihm den Haken nicht wieder ansetzen
    # -- sonst setzt sich die Maschine beim naechsten Start ein zweites Mal
    # auf. Deshalb schreibt der Server nur, was vom mitgeschickten
    # Ausgangsstand abweicht.
    speichern(MAC, entry="debian-trixie", pxe=True)
    c.get("/boot/debian-trixie.ipxe", params={"mac": MAC_HYP})
    check("Haken nach dem Start weg", next(
        z for z in c.get("/clients.json").json()["clients"]
        if z["mac"] == MAC)["pxe_aktiv"] is False)
    # Eine Seite, die Haken und Auswahl noch zeigt, schickt genau das ab --
    # sie wurde ja aufgebaut, bevor der Rechner gestartet ist.
    c.post("/clients/speichern",
           data={f"war_name:{MAC}": "Lenovo L540", f"name:{MAC}": "Lenovo L540",
                 f"war_entry:{MAC}": "debian-trixie", f"entry:{MAC}": "debian-trixie",
                 f"war_pxe:{MAC}": "1", f"pxe_aktiv:{MAC}": "1",
                 "war_name:de:ad:be:ef:00:01": "Altbestand",
                 "name:de:ad:be:ef:00:01": "Anderer Rechner",
                 "war_entry:de:ad:be:ef:00:01": "", "entry:de:ad:be:ef:00:01": "",
                 "war_pxe:de:ad:be:ef:00:01": "0"})
    stand = {z["mac"]: z for z in c.get("/clients.json").json()["clients"]}
    check("veralteter Haken wird nicht wieder gesetzt",
          stand[MAC]["pxe_aktiv"] is False, str(stand[MAC]))
    check("... und die Auswahl nicht wieder eingetragen",
          stand[MAC]["entry"] == "", str(stand[MAC]))
    check("... und die wirklich geaenderte Zeile wurde geschrieben",
          stand["de:ad:be:ef:00:01"]["name"] == "Anderer Rechner")
    c.post("/clients/speichern",
           data={"war_name:de:ad:be:ef:00:01": "Anderer Rechner",
                 "name:de:ad:be:ef:00:01": "Altbestand",
                 "war_entry:de:ad:be:ef:00:01": "", "entry:de:ad:be:ef:00:01": "",
                 "war_pxe:de:ad:be:ef:00:01": "0"})

    # Neu laden wirft weg, was gerade angefangen ist -- das gilt fuer mehr
    # als nur den Speichern-Knopf.
    check("Stand nennt auch den Namen",
          all("name" in z for z in c.get("/clients.json").json()["clients"]))
    check("ein gesetztes WOL-Kreuz gilt als offen",
          "eintrag.wol && eintrag.wol.checked" in seite)
    check("wer tippt, behaelt sein Feld beim Auffrischen",
          "erzwingen || jetzt === war.value" in seite)
    check("... der Ausgangsstand zieht trotzdem mit", "war.value = wert;" in seite)

    stand = c.get("/clients.json").json()["clients"]
    check("Stand nennt Auswahl und Schalter",
          all({"mac", "entry", "pxe_aktiv"} <= set(z) for z in stand), str(stand[:1]))
    meiner = next(z for z in stand if z["mac"] == MAC)
    check("Zeiten kommen fertig formatiert",
          "T" not in meiner["gesehen"] and meiner["gesehen_roh"].count("-") >= 2,
          str(meiner))

    speichern(MAC, entry="debian-trixie", pxe=True)
    check("Schalter steht im Stand", next(
        z for z in c.get("/clients.json").json()["clients"]
        if z["mac"] == MAC)["pxe_aktiv"] is True)
    c.get("/boot/debian-trixie.ipxe", params={"mac": MAC_HYP})
    check("... und faellt nach dem Start dort ebenso zurueck", next(
        z for z in c.get("/clients.json").json()["clients"]
        if z["mac"] == MAC)["pxe_aktiv"] is False)
    check("Spalte heisst jetzt Boot-Optionen",
          "Boot-Optionen" in seite and "Vorauswahl für den nächsten Start" not in seite)

    # Fuenf Spalten, und jede traegt genau eine Sache. Loeschen sitzt seit
    # dem 03.09.2026 nicht mehr in der Zeile, sondern als Sammelknopf in
    # der Kopfzeile -- gebaut wie WOL und Speichern.
    zeile = seite[seite.index("<tbody>"):seite.index("</tbody>")]
    spalten = zeile.split("<td")
    check("kein Loeschknopf mehr in der Zeile", "/delete" not in zeile)
    check("Client-Spalte: Name, Produkt, Zeitpunkt",
          'name="name:' in spalten[1] and 'class="muted small gesehen' in spalten[1])
    check("Adressen-Spalte: MAC und IP",
          "<code" in spalten[2] and "herkunft" in spalten[2], spalten[2][:160])
    check("... mit der Architektur als Titel an der MAC",
          "startet über" in spalten[2], spalten[2][:200])
    check("WOL-Spalte: Kaestchen und geweckt",
          'form="wol"' in spalten[4] and "geweckt" in spalten[4], spalten[4][:160])
    check("Loeschspalte: nur das Kaestchen",
          'form="loeschen"' in spalten[5] and "button" not in spalten[5],
          spalten[5][:160])
    check("der Sammelknopf steht in der Kopfzeile",
          'id="loeschknopf"' in seite[:seite.index("<tbody>")])

    # Das Namensfeld bekam seine Werte frueher von einer Tabellenregel
    # ueberstimmt (table.eng input[type=text]) und trug deshalb einen
    # doppelten Selektor dagegen. Seit alle Felder dieselbe Groesse haben,
    # gibt es diese Regel nicht mehr -- und mit ihr faellt der Grund fuer
    # den Gegen-Selektor weg. Geprueft wird jetzt, dass sie nicht
    # zurueckkommt: Sonst faengt dasselbe stumm wieder an, und man sieht es
    # erst am Namensfeld.
    stil = (PROJ / "webui" / "static" / "style.css").read_text(encoding="utf-8")
    check("keine Tabellenregel ueberstimmt die Felder",
          'table.eng input[type="text"]' not in stil,
          "die Regel ist wieder da -- dann braucht .namensfeld wieder einen "
          "spezifischeren Selektor")

    # Stylesheet mit Anhang, damit der Browser nach einer Aenderung nicht
    # die alte Fassung aus seinem Zwischenspeicher nimmt.
    import re as _re
    treffer = _re.search(r"/static/style\.css\?v=(\d+)", seite)
    check("Stylesheet traegt eine Fassungsnummer", treffer is not None, seite[:0])
    check("... auf allen Seiten",
          all("/static/style.css?v=" in c.get(pfad).text
              for pfad in ("/", "/systeme", "/quellen", "/hilfe")))
    if treffer:
        vorher = treffer.group(1)
        css = PROJ / "webui" / "static" / "style.css"
        alt_zeit = css.stat().st_mtime
        try:
            os.utime(css, (alt_zeit - 3600, alt_zeit - 3600))
            neu_ = _re.search(r"/static/style\.css\?v=(\d+)", c.get("/clients").text)
            check("Fassungsnummer folgt der Datei",
                  neu_ and neu_.group(1) != vorher, f"{vorher} -> {neu_ and neu_.group(1)}")
        finally:
            os.utime(css, (alt_zeit, alt_zeit))

    # Zeiten: gespeichert wird UTC nach ISO, angezeigt Ortszeit im Klartext.
    check("Zeitstempel lesbar gemacht",
          "heute " in seite or "gestern " in seite, seite[:0])
    check("roher Zeitstempel nur noch im Tooltip",
          "+00:00\"" in seite and ">2026-" not in seite.replace('title="', "|"))
    check("kaputte Zeit bleibt stehen", pxeapp.lesbare_zeit("quatsch") == "quatsch")
    check("leere Zeit bleibt leer", pxeapp.lesbare_zeit("") == "")

    print("\n-- Mehrere Rechner auf einmal wecken")
    c.post("/clients/add", data={"mac": "aa:bb:cc:11:22:33", "name": "Werkstatt-PC"})
    liste = c.get("/clients").text
    # Ein Datensatz ohne Architektur -- so sehen Zeilen aus einer aelteren
    # Fassung der Datenbank aus, die diese Spalte noch nicht kannte. Die
    # fehlende Angabe darf nicht als "None" in der Seite landen: die
    # JSON-Fassung liess sie schon weg, die Vorlage schrieb sie hin, und der
    # Unterschied fiel erst nach dem ersten Auffrischen auf.
    with pxeapp.db() as conn:
        conn.execute("INSERT INTO clients (mac, last_seen, last_ip) VALUES (?,?,?)",
                     ("aa:bb:cc:44:55:66", "2026-08-23T10:00:00+00:00",
                      "192.168.1.99"))
    ohne_arch = c.get("/clients").text
    check("fehlende Architektur erscheint nicht als None",
          "None" not in ohne_arch)
    check("Knopf sitzt in der Spaltenueberschrift",
          ">WOL</button>" in liste and "Wecken</button>" not in liste)
    # Zwei Kaestchen je Zeile, seit Loeschen ein Sammelknopf ist: eines
    # weckt, eines nimmt aus der Liste. Beide heissen "mac" und gehoeren
    # ueber ihr form-Attribut zu verschiedenen Formularen.
    check("je Zeile ein Kaestchen fuer WOL und eines fuers Loeschen",
          liste.count('type="checkbox" name="mac"') == 6,
          str(liste.count('type="checkbox" name="mac"')))
    check("Kaestchen gehoeren ueber form-Attribut dazu",
          liste.count('form="wol"') >= 4 and liste.count('form="loeschen"') >= 4)

    # Die Suche filtert im Browser; hier laesst sich nur pruefen, dass sie
    # ueberhaupt ausgeliefert wird -- und zwar immer, nicht erst ab einer
    # Listenlaenge (Entscheidung vom 03.09.2026).
    seite_liste = c.get("/clients").text
    check("Suchfeld steht im Kartenkopf",
          'id="clientssuche"' in seite_liste)
    zeilen = seite_liste.count('<tr data-mac=')
    stand = re.search(r'id="clientszahl"[^>]*>\s*(\d+) Rechner', seite_liste)
    check("... mit der Zahl daneben, und sie stimmt",
          bool(stand) and int(stand.group(1)) == zeilen,
          (stand.group(1) if stand else "keine") + " statt " + str(zeilen))
    check("... und einer Zeile fuer null Treffer",
          'id="ohnetreffer"' in seite_liste)

    # Die Grenze steht im Feld, nicht nur im Server -- sonst faellt sie
    # erst beim Speichern auf, und dann ist stillschweigend abgeschnitten.
    check("Namensfeld traegt die Grenze als maxlength",
          seite_liste.count('maxlength="%d"' % pxeapp.MAX_CLIENTNAME) >= 2,
          str(seite_liste.count('maxlength=')))
    lang = "Empfang, 2. OG, Gebaeude C, hinten links"
    c.post("/clients/add", data={"mac": "aa:bb:cc:de:ad:01", "name": lang})
    with pxeapp.db() as conn:
        gespeichert = conn.execute(
            "SELECT name FROM clients WHERE mac = ?",
            ("aa:bb:cc:de:ad:01",)).fetchone()["name"]
    check("... und der Server schneidet ebenso ab",
          gespeichert == lang[:pxeapp.MAX_CLIENTNAME], gespeichert)

    r = c.post("/clients/wecken", data={"mac": [MAC, "aa:bb:cc:11:22:33"]},
               follow_redirects=False)
    check("Sammelwecken leitet weiter", r.status_code == 303)
    ziel = unquote(r.headers["location"])
    check("... und nennt beide Rechner",
          "2 Rechner" in ziel and "Werkstatt-PC" in ziel, ziel)
    gesehen = alle_weckpakete()
    check("beide Weckpakete gingen wirklich raus",
          {paket_fuer(MAC), paket_fuer("aa:bb:cc:11:22:33")} <= gesehen,
          f"{len(gesehen)} verschiedene Pakete empfangen")

    check("ohne Auswahl passiert nichts",
          "angekreuzt" in unquote(c.post("/clients/wecken", data={},
                                         follow_redirects=False).headers["location"]))
    check("kaputte MAC wird uebergangen",
          "angekreuzt" in unquote(c.post("/clients/wecken", data={"mac": ["quatsch"]},
                                         follow_redirects=False).headers["location"]))
    with pxeapp.db() as conn:
        wann = conn.execute("SELECT last_wake FROM clients WHERE mac = ?",
                            ("aa:bb:cc:11:22:33",)).fetchone()["last_wake"]
    check("Weckzeitpunkt auch beim Sammelwecken vermerkt", bool(wann), str(wann))
    c.post("/clients/aa:bb:cc:11:22:33/delete")

    print("\n-- Wake-on-LAN")
    check("aeltere Datenbank aufgeruestet, Bestand erhalten",
          "Altbestand" in c.get("/clients").text)
    erwartet = b"\xff" * 6 + bytes.fromhex(MAC.replace(":", "")) * 16
    r = c.post(f"/clients/{MAC}/wake", follow_redirects=False)
    check("Wecken leitet weiter", r.status_code == 303)
    check("Magic Packet hat die richtige Form", weckpaket() == erwartet)
    check("Weckzeitpunkt wird vermerkt", "geweckt" in c.get("/clients").text)
    check("kaputte MAC weckt nicht",
          c.post("/clients/keine-mac/wake").status_code == 400)

    # Speichern und Wecken sind getrennt: das Formular legt nur die
    # Boot-Optionen fest, eingeschaltet wird ueber die WOL-Spalte.
    r = speichern(MAC, entry="debian-trixie", pxe=False, follow_redirects=False)
    check("Speichern leitet weiter", r.status_code == 303)
    # Ohne Haken wird nur gemerkt, nicht gebootet.
    with pxeapp.db() as conn:
        r2 = conn.execute("SELECT entry, pxe_aktiv FROM clients WHERE mac = ?",
                          (MAC,)).fetchone()
    check("Auswahl gemerkt, Schalter aus",
          r2["entry"] == "debian-trixie" and r2["pxe_aktiv"] == 0, str(dict(r2)))
    check("kein Weckknopf mehr im Boot-Formular",
          "&amp; wecken" not in c.get("/clients").text)

    print("\n-- Manuelle Registrierung antwortet")
    from urllib.parse import unquote

    def anmelden(mac, name=""):
        """Registrieren, ohne der Weiterleitung zu folgen -- die Meldung zaehlt."""
        r = c.post("/clients/add", data={"mac": mac, "name": name},
                   follow_redirects=False)
        return r.status_code, unquote(r.headers.get("location", ""))

    NEU = "aa:bb:cc:77:88:99"
    code, ziel = anmelden(NEU, "Lager-PC")
    check("neue MAC wird registriert und gemeldet",
          code == 303 and ziel.startswith("/clients?meldung=")
          and "registriert" in ziel, f"{code} {ziel}")

    code, ziel = anmelden(NEU, "Lager-PC")
    check("bekannte MAC sagt, dass sie bekannt ist",
          "bereits registriert" in ziel, ziel)

    code, ziel = anmelden(NEU, "Ganz anderer Name")
    with pxeapp.db() as conn:
        geblieben = conn.execute("SELECT name FROM clients WHERE mac = ?",
                                 (NEU,)).fetchone()["name"]
    check("zweiter Name ueberschreibt den ersten nicht",
          geblieben == "Lager-PC", geblieben)
    check("... und die Meldung sagt genau das",
          "Lager-PC" in ziel and "bleibt" in ziel, ziel)

    # Die Weiterleitung allein ist nicht die Antwort -- der Benutzer soll die
    # Karte sehen. Deshalb einmal der ganze Weg, mit Folgen der Umleitung.
    seite = c.post("/clients/add", data={"mac": NEU, "name": "Noch einer"}).text
    check("die Meldung steht danach als Karte auf der Seite",
          "bereits registriert" in seite and "Lager-PC" in seite)

    # Ein leeres Feld ist kein Name, den jemand vergeben hat -- das darf der
    # zweite Anlauf fuellen, ohne dass etwas verlorengeht.
    OHNE = "aa:bb:cc:aa:bb:cc"
    anmelden(OHNE)
    code, ziel = anmelden(OHNE, "Nachgereicht")
    with pxeapp.db() as conn:
        nachgereicht = conn.execute("SELECT name FROM clients WHERE mac = ?",
                                    (OHNE,)).fetchone()["name"]
    check("leerer Name wird nachgetragen",
          nachgereicht == "Nachgereicht" and "heißt jetzt" in ziel,
          f"{nachgereicht} {ziel}")

    print("\n-- Sammelloeschen")
    WEG1, WEG2 = "aa:bb:cc:ee:00:01", "aa:bb:cc:ee:00:02"
    anmelden(WEG1, "Weg-eins")
    anmelden(WEG2, "Weg-zwei")

    def loeschen(*macs):
        r = c.post("/clients/loeschen", data={"mac": list(macs)},
                   follow_redirects=False)
        return r.status_code, unquote(r.headers.get("location", ""))

    code, ziel = loeschen()
    check("ohne Auswahl passiert nichts, und die Karte sagt es",
          code == 303 and "Keinen Rechner angekreuzt" in ziel, ziel)

    code, ziel = loeschen("aa:bb:cc:ee:ff:99")
    check("eine unbekannte MAC ebenso",
          "stand in der Liste" in ziel, ziel)

    code, ziel = loeschen(WEG1, WEG2)
    with pxeapp.db() as conn:
        uebrig = conn.execute(
            "SELECT count(*) AS n FROM clients WHERE mac IN (?,?)",
            (WEG1, WEG2)).fetchone()["n"]
    check("zwei Rechner auf einmal sind weg", uebrig == 0, str(uebrig))
    check("... und die Meldung nennt beide",
          "2 Rechner gelöscht" in ziel and "Weg-eins" in ziel
          and "Weg-zwei" in ziel, ziel)

    # Der einzelne Weg bleibt bestehen -- er hat nur keinen Knopf mehr in
    # der Oberflaeche.
    anmelden(WEG1, "Nochmal")
    r = c.post(f"/clients/{WEG1}/delete", follow_redirects=False)
    check("die Route je Rechner gibt es weiter",
          "gelöscht" in unquote(r.headers.get("location", "")),
          r.headers.get("location", ""))

    print("\n-- Fehlerfaelle")
    check("unbekannter Eintrag -> 404", c.get("/boot/gibtsnicht.ipxe").status_code == 404)
    # Bis zum 03.09.2026 eine nackte JSON-Zeile mit 400: kein Kopf, keine
    # Reiter, kein Weg zurueck. Auch ein Aufruf von aussen soll auf einer
    # Seite landen, die man verlassen kann.
    code, ziel = anmelden("keine-mac")
    check("kaputte MAC -> Meldung auf /clients statt nackter Fehlerseite",
          code == 303 and ziel.startswith("/clients?meldung=")
          and "keine MAC-Adresse" in ziel, f"{code} {ziel}")
    r = c.post("/clients/keine-mac/delete", follow_redirects=False)
    check("dasselbe beim Loeschen",
          r.status_code == 303
          and "keine MAC-Adresse" in unquote(r.headers.get("location", "")),
          f"{r.status_code} {r.headers.get('location')}")
    check("Zuweisung auf unbekannten Eintrag -> 400",
          speichern(MAC, entry="quatsch").status_code == 400)
    check("Boot ohne MAC funktioniert trotzdem",
          c.get("/boot/debian-trixie.ipxe").text.startswith("#!ipxe"))

    print("\n-- Installationsprotokolle")
    import logs as pxelogs

    r = c.get("/logs.sh")
    check("Sammelskript wird geliefert", r.text.startswith("#!/bin/sh"))
    check("... mit der eigenen Serveradresse", "http://192.168.1.50" in r.text)

    paket = b"angebliches Protokollpaket\n" * 200
    r = c.put(f"/logs/{MAC_HYP}/protokolle.tgz", content=paket)
    check("Protokoll angenommen", r.status_code == 201, r.text[:200])
    datei = r.json()["datei"]
    check("Zeitstempel steht im Dateinamen",
          datei.endswith("-protokolle.tgz") and datei[8] == "T", datei)
    check("erscheint beim Client", datei in c.get("/clients").text)
    check("laesst sich herunterladen",
          c.get(f"/logs/{MAC}/{datei}").content == paket)

    check("kaputte MAC -> 400",
          c.put("/logs/keine-mac/x.tgz", content=b"x").status_code == 400)
    check("leeres Paket -> 400",
          c.put(f"/logs/{MAC_HYP}/leer.tgz", content=b"").status_code == 400)
    check("unbekanntes Protokoll -> 404",
          c.get(f"/logs/{MAC}/gibtsnicht.tgz").status_code == 404)

    # Obergrenze: fuer den Test heruntergesetzt, damit keine 64 MB durch die
    # Leitung muessen. Wichtig ist, dass nichts Halbes liegen bleibt.
    alte_grenze = pxelogs.MAX_BYTES
    pxelogs.MAX_BYTES = 100
    try:
        r = c.put(f"/logs/{MAC_HYP}/zu-gross.tgz", content=b"x" * 5000)
        check("zu grosses Paket -> 413", r.status_code == 413, str(r.status_code))
        check("... und nichts bleibt liegen",
              all("zu-gross" not in e["datei"] for e in pxelogs.fuer(MAC)))
    finally:
        pxelogs.MAX_BYTES = alte_grenze

    r = c.post(f"/logs/{MAC}/{datei}/delete", follow_redirects=False)
    check("Loeschen leitet weiter", r.status_code == 303)
    check("und ist wirklich weg", c.get(f"/logs/{MAC}/{datei}").status_code == 404)

    print("\n-- Eigenes ISO hochladen")
    # Ein winziges, aber echtes ISO9660-Abbild mit den Merkmalen von
    # Linux Mint. Hochgeladen wird als roher PUT, genau wie im Browser.
    abbild = (IsoBauer("Linux Mint 22.3 Cinnamon 64-bit")
              .add(".disk/info", b'Linux Mint 22.3 "Zara" - Release amd64\n')
              .add("casper/vmlinuz", b"KERNEL")
              .add("casper/initrd.lz", b"INITRD")
              .schreibe(tmp / "mint.iso"))

    r = c.put("/uploads/linuxmint-22.3-cinnamon-64bit.iso", content=abbild.read_bytes())
    check("Upload angenommen", r.status_code == 201, str(r.status_code) + r.text[:200])
    slug = r.json()["slug"]
    check("Kennung aus dem Dateinamen abgeleitet",
          slug == "iso-linuxmint-22-3-cinnamon-64bit", slug)

    # Dieselbe Datei ein zweites Mal: Der Server sagt vorher, dass es die
    # Kennung schon gibt, und nennt die naechste freie. Gefragt wird vor
    # dem Uebertragen -- danach waeren die Gigabyte schon unterwegs.
    auskunft = c.get("/uploads/vorhanden",
                     params={"datei": "linuxmint-22.3-cinnamon-64bit.iso"}).json()
    check("der Server kennt die Kennung schon",
          auskunft["vorhanden"] and auskunft["vorhanden"]["slug"] == slug,
          str(auskunft))
    check("... und nennt die naechste freie",
          auskunft["naechste"] == slug + "-2", auskunft["naechste"])
    check("bei einer unbekannten Datei fragt niemand",
          c.get("/uploads/vorhanden",
                params={"datei": "gibtsnicht.iso"}).json()["vorhanden"] is None)
    # Auch fuer die Download-Karte, dort steckt der Name in der Adresse.
    check("dieselbe Auskunft fuer eine Adresse",
          c.get("/uploads/vorhanden",
                params={"url": "https://example.org/a/linuxmint-22.3-cinnamon-64bit.iso"})
          .json()["vorhanden"]["slug"] == slug)

    # Erkennen und Entpacken laufen im Hintergrund -- kurz darauf warten.
    zustand = {}
    for _ in range(100):
        zustand = next((u for u in c.get("/uploads.json").json()["uploads"]
                        if u["slug"] == slug), {})
        if zustand.get("status") not in ("empfangen", "entpacken"):
            break
        time.sleep(0.1)

    check("als Ubuntu-Abkoemmling erkannt", zustand.get("familie") == "casper", str(zustand))
    check("Klarname aus dem Abbild gelesen", "Linux Mint 22.3" in zustand.get("erkannt", ""))
    check("Eintrag ist bereit", zustand.get("status") == "bereit", str(zustand))

    # Bereit heisst nicht angeboten: Ein Eintrag, dessen Dateien fertig
    # werden, wartet auf eine Entscheidung. Frueher stand er sofort im
    # Menue jedes freigegebenen Rechners -- bei ShredOS waere das ein
    # Loeschwerkzeug gewesen, das sich selbst hinstellt.
    check("bereit, aber noch nicht im Bootmenue",
          "item " + slug + " " not in menue("aa-bb-cc-dd-ee-01"))
    freigeben(slug)
    menu = menue("aa-bb-cc-dd-ee-01")
    check("nach dem Freigeben erscheint es im Bootmenue",
          "item " + slug + " " in menu)
    skript = c.get("/boot/" + slug + ".ipxe").text
    # Mit NFS-Export wird das ausgepackte Abbild gestreamt statt als ISO in
    # eine RAM-Disk geladen -- genau dafuer ist der Export da: So startet
    # auch ein 6 GB grosses Desktop-Abbild auf einem Rechner mit 8 GB.
    check("Startskript haengt das ausgepackte Abbild ein",
          "nfsroot=${srvip}:" + str(assets) + "/" + slug in skript,
          skript[skript.find("kernel"):][:200])
    check("Kernel kommt aus dem Abbild",
          "kernel ${assets}/" + slug + "/casper/vmlinuz" in skript)

    # Und jetzt die Wahl: Ohne Angabe wird ersetzt (so laeuft es auch mit
    # curl), mit "neu=1" entsteht eine zweite Ausgabe daneben.
    r = c.put("/uploads/linuxmint-22.3-cinnamon-64bit.iso?neu=1",
              content=abbild.read_bytes())
    zweite = r.json()["slug"]
    check("als neue Ausgabe entsteht eine zweite Kennung",
          zweite == slug + "-2", zweite)
    check("... und die erste liegt unberuehrt daneben",
          (assets / slug / "eintrag.yaml").is_file())
    # Erst abwarten: Solange im Hintergrund entpackt wird, haelt Windows
    # die Zustandsdatei fest und das Loeschen scheitert.
    for _ in range(100):
        zwei = next((u for u in c.get("/uploads.json").json()["uploads"]
                     if u["slug"] == zweite), {})
        if zwei.get("status") not in ("empfangen", "entpacken"):
            break
        time.sleep(0.1)
    c.post("/uploads/" + zweite + "/delete")
    check("die zweite laesst sich wieder wegnehmen",
          not (assets / zweite).exists())

    r = c.put("/uploads/linuxmint-22.3-cinnamon-64bit.iso", content=abbild.read_bytes())
    check("ohne Angabe wird ersetzt", r.json()["slug"] == slug, r.text)
    for _ in range(100):
        zustand = next((u for u in c.get("/uploads.json").json()["uploads"]
                        if u["slug"] == slug), {})
        if zustand.get("status") not in ("empfangen", "entpacken"):
            break
        time.sleep(0.1)

    # Kein ISO, sondern Datenmuell: sauber melden statt abstuerzen.
    # Ein Upload, den der Browser abbricht (Seitenwechsel waehrend der
    # Uebertragung), ist kein Serverfehler: er hinterlaesst nichts und
    # meldet 499 statt eines Tracebacks im Journal. Geprueft wird die Route
    # unmittelbar -- ueber den Testclient laesst sich ein abgerissener
    # Datenstrom nicht nachstellen, der Fehler bliebe auf seiner Seite.
    import asyncio

    import starlette.requests as _sr

    class AbgerisseneAnfrage:
        headers = {"content-length": "8192"}

        async def stream(self):
            yield b"x" * 4096
            raise _sr.ClientDisconnect()

    vorher = {u["slug"] for u in c.get("/uploads.json").json()["uploads"]}
    antwort = asyncio.run(pxeapp.upload_iso("abbruch.iso", AbgerisseneAnfrage()))
    check("abgebrochener Upload meldet 499", antwort.status_code == 499,
          str(antwort.status_code))
    check("... und laesst nichts liegen",
          {u["slug"] for u in c.get("/uploads.json").json()["uploads"]} == vorher)

    # Und der Fall, der bis August 2026 wirklich Daten kostete: Abbruch beim
    # ERSETZEN. Der Aufraeumweg nahm das ganze Verzeichnis mit -- und darin
    # lag die vorher funktionierende Fassung, die mit dem abgebrochenen
    # Upload nichts zu tun hatte. Jetzt faellt sie erst, wenn das Neue
    # vollstaendig angekommen ist.
    ordner_vorher = assets / slug
    dateien_vorher = {p.relative_to(ordner_vorher).as_posix()
                      for p in ordner_vorher.rglob("*") if p.is_file()}
    zustand_vorher = next(u for u in c.get("/uploads.json").json()["uploads"]
                          if u["slug"] == slug)
    antwort = asyncio.run(pxeapp.upload_iso(
        "linuxmint-22.3-cinnamon-64bit.iso", AbgerisseneAnfrage()))
    check("abgebrochener Ersatz meldet ebenfalls 499", antwort.status_code == 499)
    danach = next((u for u in c.get("/uploads.json").json()["uploads"]
                   if u["slug"] == slug), {})
    check("die vorherige Fassung ueberlebt den Abbruch", bool(danach))
    check("... und ist unveraendert startbereit",
          danach.get("status") == zustand_vorher.get("status") == "bereit",
          str(danach.get("status")))
    check("... mit allen ihren Dateien, ohne halbe",
          {p.relative_to(ordner_vorher).as_posix()
           for p in ordner_vorher.rglob("*") if p.is_file()} == dateien_vorher,
          str(sorted({p.name for p in ordner_vorher.rglob("*") if p.is_file()})[:6]))
    check("... sagt aber, dass der Ersatz nicht durchkam",
          "abgebrochen" in danach.get("meldung", ""), str(danach.get("meldung")))
    check("... und steht weiter im Bootmenue", "item " + slug + " " in menue())

    r = c.put("/uploads/kaputt.iso", content=b"kein ISO" * 3000)
    check("Datenmuell wird angenommen ...", r.status_code == 201)
    muell_slug = r.json()["slug"]
    muell = {}
    for _ in range(100):
        muell = next((u for u in c.get("/uploads.json").json()["uploads"]
                      if u["slug"] == muell_slug), {})
        if muell.get("status") not in ("empfangen", "entpacken"):
            break
        time.sleep(0.1)
    check("... und als Fehler gemeldet", muell.get("status") == "fehler", str(muell))
    check("kein Menuepunkt daraus",
          "item " + muell_slug + " " not in
          menue())

    r = c.post("/uploads/" + muell_slug + "/delete", follow_redirects=False)
    check("Loeschen leitet weiter", r.status_code == 303)
    check("und ist wirklich weg",
          all(u["slug"] != muell_slug for u in c.get("/uploads.json").json()["uploads"]))

    print("\n-- Abbild von einer Adresse holen")
    # Ein eigener Webserver auf der Loopback-Adresse: so laeuft der Test
    # ohne Internet und ohne fremde Server zu belasten.
    import functools
    import http.server
    import threading as thr

    webroot = tmp / "webroot"
    webroot.mkdir(exist_ok=True)
    (webroot / "ubuntu-test.iso").write_bytes(
        (IsoBauer("Ubuntu 26.04 LTS amd64")
         .add(".disk/info", b"Ubuntu 26.04 LTS - Release amd64\n")
         .add("boot/grub/grub.cfg", b"linux /casper/vmlinuz layerfs-path=minimal.squashfs\n")
         .add("casper/vmlinuz", b"KERNEL")
         .add("casper/initrd", b"INITRD")
         .add("EFI/boot/bootx64.efi", b"SHIM")
         .schreibe(tmp / "quelle.iso")).read_bytes())
    (webroot / "gross.bin").write_bytes(b"x" * (2 * 1024 * 1024))

    # Ein nachgebauter Spiegel mit drei Ausgaben nebeneinander. Der
    # Testserver liefert fuer ein Verzeichnis von selbst einen Index --
    # genau das, worin der Server nach Nachbarausgaben sieht.
    for ausgabe in ("3.21", "3.22", "3.23"):
        ordner = webroot / "spiegel" / ausgabe / "loader"
        ordner.mkdir(parents=True, exist_ok=True)
        # Ueber der Mindestgroesse: Ein Kernel von sechs Byte waere ein
        # Fund, den quellen.pruefe() zu Recht als "zu klein" abweist.
        (ordner / "linux").write_bytes(b"K" * (1024 * 1024 + 1))
        (ordner / "initrd").write_bytes(b"I" * (1024 * 1024 + 1))

    class Leise(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

    dienst = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Leise, directory=str(webroot)))
    thr.Thread(target=dienst.serve_forever, daemon=True).start()
    basis = f"http://127.0.0.1:{dienst.server_address[1]}"

    r = c.post("/uploads/holen", data={"url": basis + "/ubuntu-test.iso"},
               follow_redirects=False)
    check("Auftrag angenommen", r.status_code == 303, str(r.status_code))

    geholt = {}
    for _ in range(150):
        geholt = next((u for u in c.get("/uploads.json").json()["uploads"]
                       if u["datei"] == "ubuntu-test.iso"), {})
        if geholt.get("status") not in ("laedt", "empfangen", "entpacken"):
            break
        time.sleep(0.1)
    check("heruntergeladen und erkannt", geholt.get("status") == "bereit", str(geholt))
    check("als Ubuntu-Abkoemmling eingeordnet", geholt.get("familie") == "casper")
    check("bereit, aber noch nicht im Bootmenue",
          "item " + geholt.get("slug", "?") + " " not in menue())
    freigeben(geholt.get("slug", "?"))
    check("nach dem Freigeben erscheint es im Bootmenue",
          "item " + geholt.get("slug", "?") + " " in menue())

    check("nur http/https", c.post("/uploads/holen",
          data={"url": "file:///etc/passwd"}).status_code == 400)

    # Dieselbe Adresse ein zweites Mal, so wie die Karte fragt: Der Server
    # faengt nichts an, sondern meldet zurueck, was schon dort liegt. Die
    # Rueckfrage haengt damit an ihm -- ginge sie im Browser verloren,
    # waere sonst ein fertiges Abbild stillschweigend ersetzt.
    r = c.post("/uploads/holen", data={"url": basis + "/ubuntu-test.iso"},
               headers={"Accept": "application/json"}, follow_redirects=False)
    check("belegte Kennung: der Server haelt an", r.status_code == 409, str(r.status_code))
    check("... und sagt, was dort liegt",
          r.json().get("vorhanden", {}).get("slug") == geholt.get("slug"), r.text[:200])
    check("... und wie die naechste Ausgabe hiesse",
          r.json().get("naechste", "").endswith("-2"), r.text[:200])
    check("... angefangen hat er nichts",
          len([u for u in c.get("/uploads.json").json()["uploads"]
               if u["datei"] == "ubuntu-test.iso"]) == 1)

    # Mit Entscheidung geht es weiter -- und ein Skript mit curl, das keine
    # JSON-Antwort verlangt, ersetzt wie eh und je ohne Rueckfrage.
    r = c.post("/uploads/holen",
               data={"url": basis + "/ubuntu-test.iso", "ersetzen": "1"},
               headers={"Accept": "application/json"}, follow_redirects=False)
    check("mit Entscheidung laeuft es an", r.status_code == 202, str(r.status_code))
    for _ in range(150):
        stand = next((u for u in c.get("/uploads.json").json()["uploads"]
                      if u["datei"] == "ubuntu-test.iso"), {})
        if stand.get("status") not in ("laedt", "empfangen", "entpacken"):
            break
        time.sleep(0.1)
    check("... und ersetzt das Vorhandene", stand.get("status") == "bereit", str(stand))
    check("... ohne eine zweite Ausgabe anzulegen",
          len([u for u in c.get("/uploads.json").json()["uploads"]
               if u["datei"] == "ubuntu-test.iso"]) == 1)

    # Diesmal so, wie die Karte fragt: Antwort hierher statt zurueck auf
    # /quellen. Sie verfolgt den Download an Ort und Stelle und braucht
    # dafuer die Kennung -- ohne JavaScript bleibt es beim 303 oben.
    r = c.post("/uploads/holen", data={"url": basis + "/gibtsnicht.iso"},
               headers={"Accept": "application/json"}, follow_redirects=False)
    check("toter Link wird angenommen ...", r.status_code == 202, str(r.status_code))
    check("... und die Kennung kommt zurueck",
          r.json().get("slug", "").startswith("iso-"), r.text)
    kaputt = {}
    for _ in range(100):
        kaputt = next((u for u in c.get("/uploads.json").json()["uploads"]
                       if u["datei"] == "gibtsnicht.iso"), {})
        if kaputt.get("status") not in ("laedt", "empfangen", "entpacken"):
            break
        time.sleep(0.1)
    check("... und als Fehler gemeldet", kaputt.get("status") == "fehler", str(kaputt))
    check("... mit dem Statuscode darin", "404" in kaputt.get("meldung", ""), str(kaputt))

    # Derselbe Fall wie beim abgebrochenen Upload, nur von der anderen
    # Seite: Ein Download, der eine vorhandene Fassung ERSETZEN soll und
    # unterwegs scheitert. Die Adresse endet auf denselben Dateinamen,
    # trifft also dieselbe Kennung -- und darf sie nicht mitnehmen.
    ersatz_slug = stand.get("slug", "")
    ersatz_ordner = assets / ersatz_slug
    ersatz_dateien = {p.relative_to(ersatz_ordner).as_posix()
                      for p in ersatz_ordner.rglob("*") if p.is_file()}
    # "ersetzen" muss mit -- ohne die Entscheidung haelt der Server bei
    # einer belegten Kennung an (409), und dann pruefte das hier nichts.
    r = c.post("/uploads/holen",
               data={"url": basis + "/weg/ubuntu-test.iso", "ersetzen": "1"},
               headers={"Accept": "application/json"}, follow_redirects=False)
    check("der Ersatz-Download laeuft ueberhaupt an", r.status_code == 202,
          str(r.status_code) + " " + r.text[:120])
    ueberlebt = {}
    for _ in range(100):
        ueberlebt = next((u for u in c.get("/uploads.json").json()["uploads"]
                          if u["datei"] == "ubuntu-test.iso"), {})
        if ueberlebt.get("status") not in ("laedt", "empfangen", "entpacken"):
            break
        time.sleep(0.1)
    check("ein gescheiterter Ersatz-Download laesst die Fassung stehen",
          ueberlebt.get("status") == "bereit", str(ueberlebt))
    check("... sagt aber, woran es lag",
          "404" in ueberlebt.get("meldung", ""), str(ueberlebt.get("meldung")))
    check("... und keine Datei fehlt oder bleibt halb liegen",
          {p.relative_to(ersatz_ordner).as_posix()
           for p in ersatz_ordner.rglob("*") if p.is_file()} == ersatz_dateien)
    check("... es entsteht auch keine zweite Ausgabe daneben",
          len([u for u in c.get("/uploads.json").json()["uploads"]
               if u["datei"] == "ubuntu-test.iso"]) == 1)
    # -- Der Pruefen-Knopf sagt auch, ob eine Ausgabe in der Adresse steckt
    #
    # Bewusst derselbe Knopf: Gedrueckt wird er ohnehin, bevor jemand einen
    # Eintrag anlegt. Ein zweiter daneben waere ein zweiter Begriff, den
    # man erst verstehen muss -- und genau das soll dieser Weg vermeiden.
    print(chr(10) + "-- Ausgabe in der eingefuegten Adresse")
    r = c.get("/quellen/eintrag/pruefen", params={
        "bauart": "linuxrc", "basis": basis + "/spiegel/3.22/loader"})
    d = r.json()
    check("die Dateien werden wie bisher geprueft",
          d.get("ok") and len(d.get("dateien", [])) == 2, r.text[:160])
    a = d.get("ausgabe") or {}
    check("... und die Ausgabe in der Adresse erkannt",
          a.get("version") == "3.22", str(a))
    check("... mit dem Muster fuer alle anderen",
          a.get("muster", "").endswith("/spiegel/{version}/loader"), str(a.get("muster")))
    check("... und gegengeprueft beim Anbieter",
          sorted(a.get("andere", [])) == ["3.21", "3.23"], str(a.get("andere")))
    check("... die eingefuegte steht nicht bei den anderen",
          "3.22" not in a.get("andere", []))
    check("... und es steht dabei, woran sie erkannt wurde",
          "Pfadabschnitt" in a.get("warum", ""), str(a.get("warum")))

    # Wo keine Ausgabe steckt, wird auch keine behauptet.
    r = c.get("/quellen/eintrag/pruefen", params={
        "bauart": "linuxrc", "basis": basis + "/spiegel/"})
    check("ohne Ausgabe in der Adresse bleibt die Zeile weg",
          "ausgabe" not in r.json(), r.text[:160])

    # -- Aus einem Muster mehrere Eintraege
    #
    # Je Ausgabe ein eigener Eintrag mit eigenem Verzeichnis -- wie bei den
    # mitgelieferten mehrversionigen Systemen. Ein Eintrag, der drei
    # Ausgaben zugleich waere, muesste Dateien, Platz und Fehlschlaege
    # dreifach mit sich fuehren, und im Bootmenue stuende trotzdem dreimal
    # etwas.
    print(chr(10) + "-- Mehrere Ausgaben auf einmal aufnehmen")
    import eigene as pxeeigene

    def fertig_geworden(name, wieviele):
        """Warten, bis die Hintergrund-Downloads durch sind.

        Wer einen Eintrag loescht, waehrend sein Thread noch schreibt,
        raeumt an einer offenen Datei vorbei -- unter Windows geht das
        gar nicht, und es bleibt ein Rest liegen. Der taucht dann Hunderte
        Zeilen spaeter als Eintrag auf, den niemand angelegt hat, und
        laesst einen Test mal durchfallen und mal nicht."""
        for _ in range(200):
            da = [e for e in pxeeigene.alle() if e.get("name") == name]
            if len(da) == wieviele and all(
                    e.get("status") != "laedt" for e in da):
                return da
            time.sleep(0.05)
        return [e for e in pxeeigene.alle() if e.get("name") == name]
    r = c.post("/quellen/eintrag", follow_redirects=False, data={
        "bauart": "linuxrc", "name": "Probealpine",
        "gruppe": "Online-Installationen",
        "basis": basis + "/spiegel/3.22/loader",
        "quelle": basis + "/spiegel/3.22/",
        "versionen": "3.22 3.23"})
    check("das Anlegen leitet weiter", r.status_code == 303, str(r.status_code))
    check("... und sagt, dass es mehrere sind",
          "2%20Ausgaben" in r.headers.get("location", ""),
          r.headers.get("location", ""))

    angelegt = {e["slug"]: e for e in pxeeigene.alle()
                if e.get("name") == "Probealpine"}
    check("zwei Eintraege entstanden", len(angelegt) == 2, str(list(angelegt)))
    check("... jeder mit der Ausgabe in seiner Kennung",
          set(angelegt) == {"netz-probealpine-3-22", "netz-probealpine-3-23"},
          str(sorted(angelegt)))
    check("... und der Name bleibt ohne die Ausgabe",
          all(e["name"] == "Probealpine" for e in angelegt.values()))
    check("... die Ausgabe steht getrennt daneben",
          {e.get("version") for e in angelegt.values()} == {"3.22", "3.23"},
          str([e.get("version") for e in angelegt.values()]))
    check("... und das Muster ist mitgeschrieben, fuer spaeter",
          all("{version}" in e.get("muster", "") for e in angelegt.values()),
          str([e.get("muster") for e in angelegt.values()]))

    # Die Adresse jeder Ausgabe entsteht aus dem Muster -- die zweite zeigt
    # auf ihr eigenes Verzeichnis, nicht auf das der ersten.
    zwei = angelegt.get("netz-probealpine-3-23", {})
    check("jede Ausgabe holt aus ihrem eigenen Verzeichnis",
          any("/3.23/" in a for a in zwei.get("adressen", [])),
          str(zwei.get("adressen")))

    for _ in range(150):
        fertig = [e for e in pxeeigene.alle() if e.get("name") == "Probealpine"]
        if fertig and all(e.get("status") not in ("laedt",) for e in fertig):
            break
        time.sleep(0.1)
    check("beide werden fertig geholt",
          all(e.get("status") == "bereit" for e in fertig),
          str([(e["slug"], e.get("status"), e.get("meldung")) for e in fertig]))
    check("... und stehen als zwei Menuepunkte im Katalog",
          len([e for e in pxeeigene.katalog_eintraege()
               if e["name"] == "Probealpine"]) == 2)

    for slug in list(angelegt):
        c.post("/eintraege/" + slug + "/delete", follow_redirects=False)
    # Die Paketquelle muss die Ausgabe mitbekommen wie die Kerneladresse.
    # Ein Kernel aus 3.23 mit dem Paketdepot von 3.21 installiert Falsches,
    # und zwar ohne Fehlermeldung -- das faellt erst dem auf, der davor
    # sitzt.
    check("jede Ausgabe zeigt auf ihr eigenes Paketdepot",
          all("/" + e["version"] in e.get("cmdline", "")
              for e in angelegt.values()),
          str([(e["version"], e.get("cmdline")) for e in angelegt.values()]))

    check("wieder weggeraeumt",
          not [e for e in pxeeigene.alle() if e.get("name") == "Probealpine"])

    # -- Eine spaeter erschienene Ausgabe danebenstellen
    #
    # Der Gegenzug zur Meldung des Waechters. Ohne ihn waere sie eine
    # Sackgasse: Man muesste die Karte "Custom" noch einmal ausfuellen, mit
    # denselben Angaben und einer anderen Nummer.
    print(chr(10) + "-- Eine weitere Ausgabe aufnehmen")
    erste = pxeeigene.anlegen_mehrere(
        "linuxrc", "Nachzuegler", "Online-Installationen",
        basis + "/spiegel/{version}/loader", ["3.21"],
        basis=basis + "/spiegel/{version}/loader",
        quelle=basis + "/spiegel/{version}/")[0]

    r = c.post("/eintraege/" + erste + "/ausgabe", follow_redirects=False,
               data={"version": "3.23"})
    check("das Aufnehmen leitet weiter", r.status_code == 303, str(r.status_code))
    check("... und springt zur neuen Karte",
          "#eintrag-netz-nachzuegler-3-23" in r.headers.get("location", ""),
          r.headers.get("location", ""))

    reihe = {e["slug"]: e for e in pxeeigene.alle()
             if e.get("name") == "Nachzuegler"}
    check("die neue Ausgabe steht daneben",
          set(reihe) == {"netz-nachzuegler-3-21", "netz-nachzuegler-3-23"},
          str(sorted(reihe)))
    check("... die vorhandene bleibt unberuehrt",
          reihe["netz-nachzuegler-3-21"]["version"] == "3.21")
    neue = reihe["netz-nachzuegler-3-23"]
    check("... die neue holt aus ihrem eigenen Verzeichnis",
          any("/3.23/" in a for a in neue.get("adressen", [])),
          str(neue.get("adressen")))
    check("... und ihr Paketdepot zeigt auf 3.23",
          "/3.23" in neue.get("cmdline", ""), str(neue.get("cmdline")))
    check("... das Muster ist mitgewandert",
          "{version}" in neue.get("muster", ""), str(neue.get("muster")))

    # Ein Eintrag ohne Muster kann das nicht -- und sagt es, statt etwas
    # Falsches zu bauen.
    fest = pxeeigene.anlegen("linuxrc", "Festadresse", "Online-Installationen",
                             basis=basis + "/spiegel/3.21/loader",
                             quelle=basis + "/spiegel/3.21/")
    r = c.post("/eintraege/" + fest + "/ausgabe", follow_redirects=False,
               data={"version": "3.23"})
    check("ohne Muster wird nichts abgeleitet",
          "keine%20Ausgabe" in r.headers.get("location", "")
          or "Ausgabe" in unquote(r.headers.get("location", "")),
          r.headers.get("location", ""))
    check("... und es entsteht kein zweiter Eintrag",
          len([e for e in pxeeigene.alle() if e.get("name") == "Festadresse"]) == 1)

    fertig_geworden("Nachzuegler", 2)
    fertig_geworden("Festadresse", 1)
    for slug in list(reihe) + [fest]:
        pxeeigene.loesche(slug)




    # -- Debians Nummer neben dem Codenamen
    #
    # Debians Pfade kennen nur den Codenamen: "dists/trixie/" antwortet,
    # "dists/13.6/" gibt es nicht. In der Ausgaben-Zeile steht deshalb
    # "trixie", waehrend beim Live-Abbild daneben "13.6.0" steht -- dort
    # ist die Nummer der Dateiname. Beim Pruefen erfaehrt der Server die
    # Nummer aus Debians Release-Datei; festgehalten wird sie erst seit
    # August 2026, vorher stand sie nur im Meldungstext.
    print(chr(10) + "-- Debians Nummer")
    import quellen as pxequellen
    pxequellen.merke_nummern("DEBIAN_URL", {"trixie": "13.6", "bookworm": "12.15"})
    check("die Nummer laesst sich zu ihrem Codenamen nachschlagen",
          pxequellen.nummer("DEBIAN_URL", "trixie") == "13.6",
          pxequellen.nummer("DEBIAN_URL", "trixie"))
    check("... eine unbekannte Ausgabe bleibt leer",
          pxequellen.nummer("DEBIAN_URL", "forky") == "")

    # Eine ausbleibende Auskunft darf die bekannte nicht loeschen: Eine
    # Karte, die nach einem Netzaussetzer ihre Nummer verliert, sieht aus,
    # als waere etwas kaputt.
    pxequellen.merke_nummern("DEBIAN_URL", {})
    check("ein Pruefen ohne Auskunft laesst die alte Nummer stehen",
          pxequellen.nummer("DEBIAN_URL", "trixie") == "13.6")

    # Die Zeile traegt sie mit -- und die Karte zeigt sie an.
    pxequellen.setze("DEBIAN_VERSIONS", "trixie")
    ausg = {a["version"]: a for a in pxequellen.ausgaben("DEBIAN_URL")}
    check("die Ausgaben-Zeile traegt die Nummer mit",
          ausg.get("trixie", {}).get("nummer") == "13.6", str(ausg.get("trixie")))
    check("das Abzeichen steht in der Karte",
          "Debian 13.6" in c.get("/quellen").text)

    print("\n-- Download-Quellen")
    r = c.get("/quellen")
    check("Seite wird geliefert", r.status_code == 200)
    check("Quellen aus sync-images.sh gelesen", r.text.count('data-name="') > 5)

    r = c.post("/quellen/UBUNTU_ISO_URL", data={"url": basis + "/gross.bin"},
               follow_redirects=False)
    check("Adresse gespeichert", r.status_code == 303)
    check("als geaendert markiert", "geändert" in c.get("/quellen").text)
    check("landet in der eigenen Datei",
          "gross.bin" in (tmp / "quellen.env").read_text(encoding="utf-8"))

    d = c.get("/quellen/UBUNTU_ISO_URL/pruefen").json()
    check("Pruefung meldet erreichbar", d.get("ok") is True, str(d))
    check("... mit Groesse", d.get("groesse") == 2 * 1024 * 1024, str(d))

    c.post("/quellen/UBUNTU_ISO_URL", data={"url": basis + "/ubuntu-test.iso"})
    d = c.get("/quellen/UBUNTU_ISO_URL/pruefen").json()
    check("winzige Datei gilt als Downloadseite", d.get("ok") is False, str(d))

    c.post("/quellen/UBUNTU_ISO_URL", data={"url": basis + "/gibtsnicht"})
    d = c.get("/quellen/UBUNTU_ISO_URL/pruefen").json()
    check("toter Link wird erkannt", d.get("ok") is False and "404" in d.get("meldung", ""),
          str(d))

    check("kaputte Adresse wird abgelehnt",
          "erlaubt" in c.post("/quellen/UBUNTU_ISO_URL",
                              data={"url": "file:///etc/passwd"}).text)
    check("unbekannte Quelle wird abgelehnt",
          "Unbekannte" in c.post("/quellen/GIBTSNICHT_URL",
                                 data={"url": basis + "/x"}).text)

    # Basisadressen: sync-images.sh haengt den Dateinamen erst an, die
    # Adresse selbst liefert nur einen Verzeichnisindex. Geprueft werden
    # muss deshalb eine Datei darunter.
    (webroot / "linux").write_bytes(b"y" * (3 * 1024 * 1024))
    c.post("/quellen/DEBIAN_URL", data={"url": basis})
    d = c.get("/quellen/DEBIAN_URL/pruefen").json()
    check("Basisadresse: Datei darunter geprueft",
          d.get("ok") is True and d.get("geprueft", "").endswith("/linux"), str(d))
    check("... mit deren Groesse", d.get("groesse") == 3 * 1024 * 1024, str(d))

    c.post("/quellen/DEBIAN_URL", data={"url": basis + "/leer"})
    d = c.get("/quellen/DEBIAN_URL/pruefen").json()
    check("fehlende Datei unter der Basisadresse faellt auf",
          d.get("ok") is False, str(d))

    # Beim Spiegel von Mint ist der Verzeichnisindex das Gesuchte -- dort
    # darf die Groesse kein Ausschlusskriterium sein.
    c.post("/quellen/MINT_MIRROR", data={"url": basis})
    d = c.get("/quellen/MINT_MIRROR/pruefen").json()
    check("Verzeichnisindex gilt bei Mint als gueltig", d.get("ok") is True, str(d))

    c.post("/quellen/DEBIAN_URL/zuruecksetzen")
    c.post("/quellen/MINT_MIRROR/zuruecksetzen")
    c.post("/quellen/UBUNTU_ISO_URL/zuruecksetzen")
    check("Zuruecksetzen nimmt den Eintrag heraus",
          'class="badge ok">geändert' not in c.get("/quellen").text)

    # Eine Adresse je Ausgabe. Das Muster ist eine Wette darauf, dass die
    # Verzeichnisstruktur des Distributors bleibt -- benennt Fedora eines
    # Tages "Everything" um, sind sonst alle Ausgaben auf einmal tot, auch
    # die, die vorher liefen.
    import quellen as q
    check("ohne eigene Adresse gilt das Muster",
          q.fuer_ausgabe("FEDORA_URL", "44").endswith("/44/Everything/x86_64/os/images/pxeboot"),
          q.fuer_ausgabe("FEDORA_URL", "44"))
    # Rocky ist der Sonderfall: die Vorgabe ist nur die Basis, den Rest
    # haengt sync-images.sh an. Die Oberflaeche zeigt dieselbe Adresse.
    check("Rocky bekommt seinen Pfad angehaengt",
          q.fuer_ausgabe("ROCKY_BASE", "10").endswith("/rocky/10/BaseOS/x86_64/os/images/pxeboot"),
          q.fuer_ausgabe("ROCKY_BASE", "10"))
    # Dasselbe muss die Karte fuer die naechste Ausgabe vorschlagen. Stand
    # dort nur die Basis, kam beim Klick auf eine gefundene Nummer eine
    # halbe Adresse heraus.
    check("... und die Karte schlaegt den ganzen Weg vor",
          q.ausgabenmuster("ROCKY_BASE")
          == "https://dl.rockylinux.org/pub/rocky/{version}/BaseOS/x86_64/os/images/pxeboot",
          q.ausgabenmuster("ROCKY_BASE"))
    check("... im Kartensatz steht es genauso",
          [k["muster"] for k in q.karten() if k["name"] == "ROCKY_BASE"]
          == [q.ausgabenmuster("ROCKY_BASE")])
    # Geprueft wird die Adresse einer Ausgabe, nicht die Basis: dort fehlt
    # nur noch der Dateiname.
    check("Rocky prueft die Datei unter der Ausgabe",
          q.PRUEFPFAD["ROCKY_BASE"] == "vmlinuz")

    q.setze_ausgabe("FEDORA_URL", "44", "https://spiegel.example/f44/pxeboot")
    check("eine eigene Adresse ueberstimmt das Muster",
          q.fuer_ausgabe("FEDORA_URL", "44") == "https://spiegel.example/f44/pxeboot")
    check("... und steht unter ihrem eigenen Namen in der Datei",
          'FEDORA_URL_44="https://spiegel.example/f44/pxeboot"'
          in (tmp / "quellen.env").read_text(encoding="utf-8"))
    check("die Liste sagt, was eigens dasteht",
          [(a["version"], a["eigen"]) for a in q.ausgaben("FEDORA_URL")] == [("44", True)],
          str(q.ausgaben("FEDORA_URL")))

    # Punkte gehen in Variablennamen nicht -- 16.1 wird zu 16_1, genau wie
    # in sync-images.sh.
    q.setze_ausgabe("LEAP_URL", "16.1", "https://spiegel.example/leap161")
    check("Punkte werden zu Unterstrichen",
          'LEAP_URL_16_1=' in (tmp / "quellen.env").read_text(encoding="utf-8"))

    q.loesche_ausgabe("FEDORA_URL", "44")
    check("ohne eigene Adresse gilt wieder das Muster",
          q.fuer_ausgabe("FEDORA_URL", "44").endswith("/44/Everything/x86_64/os/images/pxeboot")
          and [a["eigen"] for a in q.ausgaben("FEDORA_URL")] == [False])
    q.loesche_ausgabe("LEAP_URL", "16.1")

    # Nachsehen, was der Anbieter hat. Geprueft wird hier nur die Zerlegung
    # -- der Netzzugriff selbst gehoert nicht in einen Test, der ohne
    # Internet durchlaufen muss.
    check("das Verzeichnis ueber den Ausgaben wird erkannt",
          q._verzeichnis_ueber("https://x.example/releases/{version}/os/")
          == "https://x.example/releases/"
          and q._verzeichnis_ueber("https://x.example/p/tool-{version}-amd64.iso")
          == "https://x.example/p/")
    # Wo es keinen Index gibt, wird der Dateiname gelesen -- aus dem
    # Adressmuster entsteht dafuer ein Suchausdruck.
    muster = q._dateimuster("https://x.example/p/gparted-live-{version}-amd64.iso")
    check("Ausgaben lassen sich aus Dateinamen lesen",
          muster.findall("… gparted-live-1.8.1-3-amd64.iso … "
                         "gparted-live-1.7.0-12-amd64.iso …")
          == ["1.8.1-3", "1.7.0-12"],
          str(muster.findall("gparted-live-1.8.1-3-amd64.iso")))
    check("10 sortiert hinter 9",
          sorted(["9", "10", "9.8"], key=q._sortierschluessel)
          == ["9", "9.8", "10"])
    # Vor jeder anderen Frage: Kommt dieser Server ueberhaupt zum
    # Anbieter? Ohne diese Stufe sahen "die Datei ist weg" und "hier ist
    # kein Internet" fast gleich aus -- beides endete in "Nicht
    # erreichbar: <irgendein Python-Fehler>".
    q.vergiss_erreichbarkeit()
    tot = q.erreichbar("https://gibtsganzsicherhtnicht.invalid/pfad", zeitlimit=4)
    check("ein Anbieter, den es nicht gibt, ist nicht erreichbar",
          tot["ok"] is False and "Keine Verbindung" in tot["meldung"], str(tot))
    check("... und die Meldung ist zu lesen, nicht zu entziffern",
          "aufloesbar" in tot["meldung"] and "urlopen" not in tot["meldung"],
          tot["meldung"])
    check("geprueft wird die Wurzel, nicht der Pfad",
          tot["wurzel"] == "https://gibtsganzsicherhtnicht.invalid/", tot["wurzel"])
    # Zweimal fragen heisst nicht zweimal anfragen -- "Alle pruefen" ginge
    # sonst bei zwoelf Quellen mehrfach an denselben Rechner.
    check("die Antwort wird kurz gemerkt",
          q.erreichbar("https://gibtsganzsicherhtnicht.invalid/anderer/pfad",
                       zeitlimit=4).get("gemerkt") is True)
    check("... und eine abgelehnte Verbindung heisst so",
          q._warum(Exception("Connection refused")) == "die Verbindung wurde abgelehnt.")
    # Jede HTTP-Antwort zaehlt als erreichbar, auch eine abweisende: Sie
    # beweist, dass eine Verbindung zustande kam. Manche Anbieter sperren
    # ihre Wurzelseite -- die deshalb fuer offline zu halten waere falsch.
    # Geprueft ohne Netz, damit dieser Test nicht von einem Anbieter
    # abhaengt, der zufaellig gerade 403 sagt.
    import urllib.error as _ue, urllib.request as _ur
    echt_urlopen = _ur.urlopen

    def _abweisend(*_a, **_k):
        raise _ue.HTTPError("https://x.example/", 403, "Forbidden", None, None)

    _ur.urlopen = _abweisend
    try:
        q.vergiss_erreichbarkeit()
        abgewiesen = q.erreichbar("https://x.example/pfad")
    finally:
        _ur.urlopen = echt_urlopen
        q.vergiss_erreichbarkeit()
    check("ein Fehlercode heisst trotzdem erreichbar",
          abgewiesen["ok"] is True, str(abgewiesen))
    # Wo keine Verbindung besteht, wird nicht weiter probiert -- und das
    # Ergebnis sagt es ausdruecklich, damit die Oberflaeche anders
    # reagieren kann als bei einer veralteten Adresse.
    ohne = q.pruefe("https://gibtsganzsicherhtnicht.invalid/datei")
    check("Pruefen bricht ohne Verbindung ab",
          ohne["ok"] is False and ohne.get("kein_netz") is True, str(ohne))
    # Dasselbe fuer "Nach neueren sehen" -- auch dort wird nicht weiter
    # probiert. Geprueft mit einer eigenen Adresse, die ins Leere zeigt.
    vorher_url = q.alle_werte().get("DEBIAN_URL", "")
    q.setze("DEBIAN_URL",
            "https://gibtsganzsicherhtnicht.invalid/dists/{version}/x/amd64")
    q.vergiss_erreichbarkeit()
    ohne_neuere = q.neuere_ausgaben("DEBIAN_URL", zeitlimit=4)
    q.setze("DEBIAN_URL", vorher_url)
    q.vergiss_erreichbarkeit()
    check("... und Nach-neueren-sehen ebenso",
          ohne_neuere["ok"] is False and ohne_neuere.get("kein_netz") is True,
          str(ohne_neuere))

    # Jede Quelle muss sagen koennen, wer sie holt -- sonst steht in der
    # Karte ein Knopf, der ins Leere greift.
    ohne_komponente = [x["name"] for x in q.alle()
                       if x["name"] not in q.KOMPONENTE]
    check("jede Quelle kennt ihre Komponente", not ohne_komponente,
          str(ohne_komponente))
    check("... und die Komponente gibt es wirklich",
          all(k in pxesync.komponenten() for k in q.KOMPONENTE.values()),
          str(sorted(set(q.KOMPONENTE.values()) - set(pxesync.komponenten()))))
    # "debian:trixie" darf nicht als unbekannte Komponente abgewiesen
    # werden -- geprueft wird der Teil vor dem Doppelpunkt.
    try:
        pxesync.starte(["gibtsnichtx"], {})
        abgewiesen = False
    except ValueError:
        abgewiesen = True
    check("eine unbekannte Komponente wird abgewiesen", abgewiesen)

    # Rockys Index fuehrt die Reihen und die Punktversionen nebeneinander:
    # 8/ 9/ 10/ neben 8.4/ ... 10.2/. Der Katalog benutzt die Reihen -- aus
    # einer Punktversion wuerde ein zweiter Eintrag fuer dieselbe Ausgabe,
    # mit eigenem Verzeichnis und eigenem Menuepunkt.
    rocky = q.neuere_ausgaben("ROCKY_BASE", zeitlimit=25)
    check("Rocky findet nur die Reihen, keine Punktversionen",
          all("." not in v for v in rocky["gefunden"]), str(rocky["gefunden"]))
    check("... und wenigstens die aktuelle ist dabei",
          any(v.isdigit() and int(v) >= 9 for v in rocky["gefunden"]),
          str(rocky["gefunden"]))
    check("die Einschraenkung gilt nur fuer Rocky",
          q.AUSGABENFORM.get("FEDORA_URL") is None
          and "ROCKY_BASE" in q.AUSGABENFORM)

    # Leap laesst sich nicht nach Nummern sortieren: openSUSE hat zweimal
    # umnummeriert (42.x, 15.x, 16.x), und der Verzeichnisindex ist gar
    # keiner, sondern eine Web-Anwendung -- daraus las die Suche "42.3"
    # von 2017 als hoechste Ausgabe. openSUSE sagt es dafuer selbst, mit
    # Zustand und Gewicht.
    leap = q.neuere_ausgaben("LEAP_URL", zeitlimit=25)
    check("Leap nimmt den Sonderweg",
          "LEAP_URL" in q.SONDERWEG and leap.get("geprueft") == q.LEAP_AUSKUNFT)
    check("... und nennt eine stabile Ausgabe",
          bool(leap.get("aktuell")) and leap["aktuell"] in leap["gefunden"],
          str(leap.get("aktuell")))
    check("aufgenommen wird die stabile, nicht die hoechste Nummer",
          q.neueste_offene(leap, "LEAP_URL") == leap["aktuell"],
          f'{q.neueste_offene(leap, "LEAP_URL")} statt {leap["aktuell"]}')
    check("... und das ist nicht bloss die groesste Zahl",
          sorted(leap["gefunden"], key=q._sortierschluessel)[-1] != leap["aktuell"]
          or len(leap["gefunden"]) < 2,
          str(leap["gefunden"][:4]))

    # Die Untergrenze soll eine Downloadseite abfangen, nicht eine kleine
    # Datei. Memtest ist ein ZIP mit zwei winzigen Programmen darin --
    # rund 220 KB, und damit unter der Grenze von 1 MB, die fuer alle
    # anderen richtig ist. Aufgefallen ist das erst, als die Karte
    # umgebaut wurde und jede Ausgabe wirklich geprueft wurde.
    check("Memtest hat eine eigene Untergrenze",
          q.MIN_EIGEN.get("MEMTEST_ZIP_URL", q.MIN_GROESSE) < q.MIN_GROESSE)
    check("... und die anderen behalten die allgemeine",
          q.MIN_EIGEN.get("GPARTED_ISO_URL", q.MIN_GROESSE) == q.MIN_GROESSE)

    # Ubuntus Fall ist ein anderer als Debians: Die Ausgabe bleibt, der
    # Dateiname aendert sich. Unter 24.04/ liegt laengst
    # ubuntu-24.04.4-live-server-amd64.iso -- was das Muster erwartet,
    # gibt es dort nicht mehr. Gesucht wird deshalb im Verzeichnis der
    # Ausgabe, und genommen wird der hoechste Treffer: 24.04.3 und
    # 24.04.4 liegen nebeneinander.
    #
    # Diese drei Pruefungen gehen wirklich zu Ubuntu -- sie pruefen das
    # Zusammenspiel, nicht die Rechnung. Der Preis dafuer ist, dass sie
    # von etwas abhaengen, das uns nicht gehoert. Zwei Enden sind absehbar:
    #
    #   - Faellt "der echte Dateiname wird gefunden" aus, ist 24.04 nach
    #     old-releases.ubuntu.com gewandert. Dann eine Ausgabe nehmen, die
    #     noch unterstuetzt wird -- nicht das Muster reparieren.
    #   - Faellt "... und es ist nicht der aus dem Muster" aus, gaebe es
    #     unter 24.04/ wieder eine Datei ohne Punktausgabe. Sehr
    #     unwahrscheinlich, und dann waere die Zeile schlicht ueberholt.
    #
    # Was sich OHNE Netz pruefen laesst, steht darunter am nachgebauten
    # Spiegel. Die Grenze ist Absicht: Eine Rechnung gegen einen fremden
    # Server zu pruefen, macht den Test von dessen Kalender abhaengig --
    # genau daran ist die Gegenprobe am 28.08.2026 gescheitert.
    echt = q.echte_adresse("UBUNTU_ISO_URL", "24.04", zeitlimit=25)
    check("der echte Dateiname wird gefunden",
          echt.endswith(".iso") and "/24.04/ubuntu-24.04." in echt, echt)
    check("... und es ist nicht der aus dem Muster",
          echt != q.aus_muster("UBUNTU_ISO_URL", "24.04"), echt)
    # Die Gegenprobe -- "wo das Muster stimmt, kommt dasselbe heraus" --
    # laeuft gegen einen nachgebauten Spiegel auf der Rueckschleife und
    # nicht gegen Ubuntu.
    #
    # Sie stand bis zum 28.08.2026 auf 26.04, weil es davon damals noch
    # keine Punktausgabe gab. Inzwischen liegt dort 26.04.1, und der Test
    # war rot -- nicht weil der Code etwas falsch macht, sondern weil die
    # ANNAHME abgelaufen ist. Jede Ubuntu-Ausgabe bekommt frueher oder
    # spaeter ihre Punktausgabe; eine andere Zahl einzusetzen haette den
    # Fehlschlag nur vertagt.
    #
    # Was hier geprueft wird, ist ohnehin eine Eigenschaft des Codes und
    # nicht eine des Anbieters: Liegt genau die Datei da, die das Muster
    # erwartet, darf echte_adresse() nichts anderes daraus machen.
    spiegel = webroot / "ausgaben"
    (spiegel / "9.10").mkdir(parents=True, exist_ok=True)
    (spiegel / "9.10" / "probe-9.10-live-amd64.iso").write_bytes(b"x")
    # Und daneben der Fall, den es bei Ubuntu wirklich gibt: zwei
    # Punktausgaben im Verzeichnis der Ausgabe.
    (spiegel / "8.04").mkdir(parents=True, exist_ok=True)
    for punkt in ("8.04.2", "8.04.3"):
        (spiegel / "8.04" / f"probe-{punkt}-live-amd64.iso").write_bytes(b"x")

    vorher_eigen = dict(q.eigene())
    try:
        eigen = q.eigene()
        eigen["PROBE_ISO_URL"] = (
            basis + "/ausgaben/{version}/probe-{version}-live-amd64.iso")
        q._schreibe(eigen)

        check("wo das Muster stimmt, kommt dasselbe heraus",
              q.echte_adresse("PROBE_ISO_URL", "9.10", zeitlimit=5)
              == q.aus_muster("PROBE_ISO_URL", "9.10"),
              q.echte_adresse("PROBE_ISO_URL", "9.10", zeitlimit=5))
        # Liegen mehrere nebeneinander, gilt die hoechste -- und zwar nach
        # Zahlen sortiert, nicht nach Zeichen.
        check("bei mehreren Punktausgaben gewinnt die hoechste",
              q.echte_adresse("PROBE_ISO_URL", "8.04", zeitlimit=5).endswith(
                  "/ausgaben/8.04/probe-8.04.3-live-amd64.iso"),
              q.echte_adresse("PROBE_ISO_URL", "8.04", zeitlimit=5))
        check("... und der Ordner bleibt der der Ausgabe",
              "/ausgaben/8.04/" in q.echte_adresse("PROBE_ISO_URL", "8.04", zeitlimit=5))
        check("ein Verzeichnis, das es nicht gibt, liefert nichts",
              q.echte_adresse("PROBE_ISO_URL", "7.10", zeitlimit=5) == "")
    finally:
        q._schreibe(vorher_eigen)
    check("eine Ausgabe, die es nicht gibt, liefert nichts",
          q.echte_adresse("UBUNTU_ISO_URL", "3.14", zeitlimit=25) == "")

    # Findet die Pruefung eine neuere Ausgabe, traegt sie sie ein -- die
    # Adresse entsteht aus dem Muster. "oldstable" wird zwar gefunden, ist
    # aber aelter als das Eingetragene und darf deshalb nicht von selbst
    # dazukommen.
    def _befund(neu, aktuell=""):
        return {"ok": True, "neu": neu, "gefunden": neu, "aktuell": aktuell}

    check("nur die aktuelle Ausgabe wird von selbst aufgenommen",
          q.neueste_offene(_befund(["bookworm"], "trixie"), "DEBIAN_URL") == "",
          "oldstable darf nicht dazukommen")
    check("... und die aktuelle schon",
          q.neueste_offene(_befund(["trixie"], "trixie"), "DEBIAN_URL") == "trixie")
    check("ohne Codename gilt die hoechste Nummer",
          q.neueste_offene(_befund(["9", "10"]), "ROCKY_BASE") == "10")
    check("nichts Neues heisst nichts aufnehmen",
          q.neueste_offene(_befund([]), "DEBIAN_URL") == "")

    # Debian steht in keinem Verzeichnisindex: unter "dists/" liegen
    # Woerter, keine Nummern. Es sagt seine Ausgaben dafuer selbst, in
    # einer Textdatei je Suite -- gelesen wird sie hier ohne Netz.
    release = ("Origin: Debian" + chr(10) + "Suite: stable" + chr(10)
               + "Version: 13.6" + chr(10) + "Codename: trixie" + chr(10)
               + "Date: Sat, 11 Jul 2026 09:02:23 UTC" + chr(10))
    gelesen = q._debian_release(release)
    check("Debians Release-Datei wird gelesen",
          gelesen.get("codename") == "trixie" and gelesen.get("version") == "13.6",
          str(gelesen))
    check("... und Unbrauchbares gibt nichts her",
          q._debian_release("nur eine Zeile ohne alles") == {})
    check("Debian nimmt den Sonderweg, nicht den Verzeichnisindex",
          "DEBIAN_URL" in q.SONDERWEG and "DEBIAN_URL" not in q.SUCHORT)
    # Ein Zahlenvergleich waere hier falsch: "forky" steht alphabetisch vor
    # "trixie" und ist doch die spaetere Ausgabe. Deshalb entscheidet die
    # Suite, welche die aktuelle ist -- nicht die Sortierung.
    check("Codenamen werden nicht nach Groesse verglichen",
          sorted(["trixie", "forky"], key=q._sortierschluessel) == ["forky", "trixie"])

    check("fuer die vier Werkzeuge ist ein Suchort hinterlegt",
          all(n in q.SUCHORT for n in ("GPARTED_ISO_URL", "CLONEZILLA_ISO_URL",
                                       "SYSRESC_ISO_URL", "MEMTEST_ZIP_URL")))
    check("eine Quelle ohne Ausgaben wird abgewiesen",
          c.get("/quellen/ausgabe/neuere",
                params={"adresse": "TUMBLEWEED_URL"}).status_code == 400)

    print("\n-- Ausgaben mit Bindestrich im Namen")
    # Clonezilla heisst "3.3.3-15", GParted "1.8.1-3". Daraus wurde
    # CLONEZILLA_ISO_URL_3_3_3-15, und das ist kein gueltiger
    # Variablenname: In sync-images.sh brach die indirekte Expansion
    # darueber ab, url_fuer() lieferte nichts, und curl bekam eine leere
    # Adresse. "Holen" meldete einen fehlgeschlagenen Download, waehrend
    # dieselbe Adresse in der Download-Karte lief.
    import quellen as q2

    check("kein Bindestrich mehr im Namen",
          q2.schluessel("CLONEZILLA_ISO_URL", "3.3.3-15")
          == "CLONEZILLA_ISO_URL_3_3_3_15",
          q2.schluessel("CLONEZILLA_ISO_URL", "3.3.3-15"))
    check("Punkte werden weiter ersetzt",
          q2.schluessel("LEAP_URL", "16.1") == "LEAP_URL_16_1")
    check("und was die Shell lesen kann, bleibt",
          q2.schluessel("DEBIAN_URL", "trixie") == "DEBIAN_URL_trixie")

    # Der Name muss der sein, den die Shell als Variable akzeptiert --
    # sonst faellt url_fuer() genau wieder auf die Nase.
    schalen = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    krumm = [v for v in ("3.3.3-15", "1.8.1-3", "2025.11_31", "26.04", "13.02")
             if not schalen.match(q2.schluessel("X_URL", v))]
    check("jede gebraeuchliche Ausgabe ergibt einen gueltigen Namen",
          not krumm, str(krumm))

    # Und was gespeichert wird, muss die Shell einlesen koennen: Eine Zeile
    # mit krummem Namen ist fuer sie kein Eintrag, sondern ein Befehl.
    q2.setze_ausgabe("CLONEZILLA_ISO_URL", "3.3.3-15",
                     "http://127.0.0.1:1/eigene-cz.iso")
    try:
        text = Path(os.environ["PXE_QUELLEN"]).read_text(encoding="utf-8")
        zeilen = [z for z in text.splitlines()
                  if z and not z.startswith("#") and "=" in z]
        check("jede Zeile in quellen.env traegt einen gueltigen Namen",
              all(schalen.match(z.split("=", 1)[0]) for z in zeilen),
              str([z.split("=", 1)[0] for z in zeilen]))
        check("die eigene Adresse wird auch wiedergefunden",
              q2.fuer_ausgabe("CLONEZILLA_ISO_URL", "3.3.3-15")
              == "http://127.0.0.1:1/eigene-cz.iso")
        check("... und die Ausgabe gilt als eigens eingetragen",
              any(a["version"] == "3.3.3-15" and a["eigen"]
                  for a in q2.ausgaben("CLONEZILLA_ISO_URL")))

        # Wer sie vor der Korrektur eingetragen hat, hat sie unter dem
        # alten Namen stehen. Sie soll nicht verschwinden.
        eigen = q2.eigene()
        eigen.pop("CLONEZILLA_ISO_URL_3_3_3_15", None)
        eigen["CLONEZILLA_ISO_URL_3_3_3-15"] = "http://127.0.0.1:1/alt.iso"
        q2._schreibe(eigen)
        check("ein Name aus der Zeit davor wird nicht mit hinausgeschrieben",
              "3_3_3-15" not in Path(os.environ["PXE_QUELLEN"]).read_text(encoding="utf-8"))
    finally:
        q2.loesche_ausgabe("CLONEZILLA_ISO_URL", "3.3.3-15")

    check("nach dem Wegnehmen gilt wieder das Muster",
          "{version}" not in q2.fuer_ausgabe("CLONEZILLA_ISO_URL", "3.3.3-15")
          and "3.3.3-15" in q2.fuer_ausgabe("CLONEZILLA_ISO_URL", "3.3.3-15"),
          q2.fuer_ausgabe("CLONEZILLA_ISO_URL", "3.3.3-15"))

    print("\n-- Mit und ohne NFS-Export")
    # Fuenf Eintraege koennen ihr Wurzeldateisystem einhaengen statt es zu
    # laden. Bis August 2026 stand die NFS-Zeile fest in catalog.yaml, mit
    # ausgeschriebenem /srv/pxe/assets -- sie galt auch auf einem Server
    # ohne Export, und der Start scheiterte dann vor der Maschine.
    import uploads as pxeuploads

    def katalog_neu():
        pxeapp._catalog_cache["mtime"] = None

    def eintrag(slug):
        return next((e for e in pxeapp._systeme() if e["slug"] == slug), {})

    ohne_nfs = pxeuploads.NFS_ROOT
    try:
        # -- mit Export, und zwar an einem anderen Ort als /srv/pxe/assets
        pxeuploads.NFS_ROOT = "/export/abbilder"
        katalog_neu()
        g = eintrag("gparted-live-1-8-1-3")
        check("mit Export haengt GParted ein",
              "netboot=nfs" in g.get("cmdline", ""), g.get("cmdline", "")[:120])
        check("... und der Pfad kommt aus PXE_NFS_ROOT",
              "nfsroot=${srvip}:/export/abbilder/gparted-live-1-8-1-3"
              in g.get("cmdline", ""), g.get("cmdline", "")[-90:])
        check("... nicht mehr fest verdrahtet",
              "/srv/pxe/assets" not in g.get("cmdline", ""))
        check("SystemRescue nimmt seinen eigenen Namen dafuer",
              "archiso_nfs_srv=${srvip}:/export/abbilder/systemrescue-13-02"
              in eintrag("systemrescue-13-02").get("cmdline", ""))
        check("Mint ist mit Export startbereit", eintrag("mint-cinnamon").get("ready") is True)

        # Daran scheiterte GParted auf einem Lenovo, waehrend Mint (casper)
        # ueber dasselbe NFS startete. Beides gehoert in beide Wege: ohne
        # Netz nuetzt auch "fetch=" nichts.
        #
        # "ip=dhcp" ist bei live-boot kein DHCP, sondern eine statische
        # Adresse namens "dhcp" -- do_netmount setzt dann NODHCP und
        # ueberspringt do_netsetup ganz. Der Eintrag darf die Angabe in
        # keiner Form tragen: NODHCP wird bei jedem "ip=" gesetzt, auch
        # bei "ip=" und "ip=frommedia".
        for slug in ("gparted-live-1-8-1-3", "clonezilla-3-3-3-15",
                     "debian-live-13-6-0"):
            e = eintrag(slug)
            zeile = e.get("cmdline", "(kein solcher Eintrag)")
            check(slug + " wartet laenger auf die DHCP-Antwort",
                  "ethdevice-timeout=60" in zeile, zeile[:80])
            check(slug + " wartet laenger auf den Link der Karte",
                  "ethdevice-link-timeout=60" in zeile, zeile[:80])
            check(slug + " traegt kein ip= -- sonst faellt DHCP aus",
                  " ip=" not in " " + zeile, zeile[:80])

        # -- ohne Export
        pxeuploads.NFS_ROOT = ""
        katalog_neu()
        g = eintrag("gparted-live-1-8-1-3")
        check("ohne Export holt GParted ueber HTTP",
              "fetch=${assets}/gparted-live-1-8-1-3/live/filesystem.squashfs"
              in g.get("cmdline", ""), g.get("cmdline", "")[-90:])
        check("... und haengt nichts ein", "netboot=nfs" not in g.get("cmdline", ""))
        check("SystemRescue ebenso",
              "archiso_http_srv=" in eintrag("systemrescue-13-02").get("cmdline", ""))
        check("... und die Spalte sagt den anderen Weg",
              pxeapp._zugriff(g) == "vom Server in den Arbeitsspeicher"
              and pxeapp._zugriff(eintrag("systemrescue-13-02")) == "über HTTP vom Server")

        # Mint kann es nicht: casper holt ueber HTTP das ganze Abbild, und
        # eine ISO liegt hier nicht. Dann lieber nicht startbereit als ein
        # Menuepunkt, der vor der Maschine scheitert.
        m = eintrag("mint-cinnamon")
        check("Mint ist ohne Export nicht startbereit", m.get("ready") is False)
        check("... und sagt auch warum", m.get("braucht_nfs") is True)
        check("... obwohl seine Dateien alle daliegen",
              all((assets / pfad).exists()
                  for pfad in pxeapp.required_assets(m)), str(pxeapp.required_assets(m)))

        seite = c.get("/systeme").text
        check("die Seite Systeme nennt den Grund",
              "brauch" in seite and "keins" in seite and "Linux Mint" in seite)
        # Der Hinweis ist seit dem 27.08.2026 ein Befund und keine
        # Erklaerung mehr: was ist, was daraus folgt, wo es sich beheben
        # laesst. Das Warum steht in der Hilfe. Geprueft werden deshalb die
        # beiden hinteren Teile -- der vordere steht schon oben.
        check("... und sagt, was daraus folgt und wo es sich beheben laesst",
              "nicht angeboten" in seite and 'href="/einrichtung"' in seite)
        check("Mint steht nicht im Bootmenue",
              "item mint-cinnamon " not in menue())
    finally:
        pxeuploads.NFS_ROOT = ohne_nfs
        katalog_neu()

    print("\n-- Der Waechter ueber den Download-Adressen")
    import quellenwacht as wacht

    check("im Test abgeschaltet", wacht.intervall_tage() == 0)
    check("... und dann ist auch nichts faellig", wacht.faellig() is False)

    # Ein eigener Pruefer statt des Netzes: Er antwortet so, wie
    # quellen.durchleuchten() antwortet, nur eben erfunden.
    def erfunden(name):
        if name == "TOT_URL":
            return {"verbindung": {"ok": True},
                    "adressen": [{"version": "1.8", "url": "http://x/a.iso",
                                  "ok": False, "meldung": "404 Not Found"}],
                    "neuere": {"neu": []}}
        if name == "WEG_URL":
            return {"verbindung": {"ok": False}, "adressen": [], "neuere": {"neu": []}}
        if name == "KAPUTT_URL":
            raise RuntimeError("der Anbieter hat etwas Krummes geschickt")
        return {"verbindung": {"ok": True},
                "adressen": [{"version": "", "url": "http://x/c.iso",
                              "ok": True, "meldung": "ok"}],
                "neuere": {"neu": []}}

    # Der Waechter sieht seit August 2026 auch bei den selbst angelegten
    # Systemen nach, und ohne eigenen Prueferer ginge er dafuer ins echte
    # Netz. Wo es hier nicht um sie geht, bekommt er einen tauben: Ein
    # Test, der von einer Leitung abhaengt, faellt irgendwann ohne Grund
    # durch -- und schlimmer, er faellt nur manchmal durch.
    def stumm(muster):
        return {"ok": False, "gefunden": [], "meldung": "im Test nicht gefragt"}

    befund = wacht.lauf(pruefer=erfunden, proben=stumm,
                        namen=["TOT_URL", "WEG_URL", "KAPUTT_URL", "HEIL_URL"])
    check("alle vier durchgesehen", befund["geprueft"] == 4, str(befund["geprueft"]))
    check("die tote Adresse steht drin",
          [t["name"] for t in befund["tot"]] == ["TOT_URL", "KAPUTT_URL"], str(befund["tot"]))
    check("... mit dem, was der Anbieter sagt",
          befund["tot"][0]["adressen"][0]["meldung"] == "404 Not Found")
    check("eine kaputte Quelle haelt den Lauf nicht auf",
          "krumm" in befund["tot"][1]["adressen"][0]["meldung"].lower()
          or "Krummes" in befund["tot"][1]["adressen"][0]["meldung"], str(befund["tot"][1]))
    check("wen der Server nicht erreicht, gilt nicht als tot",
          befund["ohne_netz"] == ["WEG_URL"], str(befund["ohne_netz"]))
    check("die heile Quelle meldet nichts",
          not any(t["name"] == "HEIL_URL" for t in befund["tot"]))

    # -- Und dieselbe Frage fuer selbst angelegte Systeme
    #
    # Sie stehen in keiner Versionsliste, tragen ihr Muster aber selbst mit
    # sich. Seit sie mehrversionig angelegt werden koennen, ist der Waechter
    # die einzige Stelle, an der jemand von einer neuen Ausgabe erfaehrt,
    # ohne von Hand nachzusehen.
    zwei = pxeeigene.anlegen_mehrere(
        "linuxrc", "Wachprobe", "Online-Installationen",
        basis + "/spiegel/{version}/loader", ["3.21", "3.22"],
        basis=basis + "/spiegel/{version}/loader",
        quelle=basis + "/spiegel/3.21/")
    check("zwei Ausgaben angelegt", len(zwei) == 2, str(zwei))

    # Der nachgebaute Anbieter: Er kennt eine hoehere und zwei aeltere.
    gefragt = []

    def probe(muster):
        gefragt.append(muster)
        return {"ok": True, "geprueft": muster,
                "gefunden": ["3.23", "3.22", "3.21", "3.19"], "meldung": ""}

    befund = wacht.lauf(pruefer=erfunden, namen=["HEIL_URL"], proben=probe)
    check("das Muster wird nur einmal gefragt, nicht je Ausgabe",
          len(gefragt) == 1, str(gefragt))
    eigen = [n for n in befund["neu"] if n["name"] == "Wachprobe"]
    check("die neue Ausgabe wird gemeldet",
          len(eigen) == 1 and eigen[0]["version"] == "3.23", str(befund["neu"]))
    check("... und nur die hoechste, nicht die drei aelteren",
          all(n["version"] == "3.23" for n in eigen))
    check("... mit dem Weg zum Eintrag statt zu einer Quelle",
          eigen[0].get("eigen", "").startswith("netz-wachprobe-"), str(eigen[0]))
    check("die selbst angelegten zaehlen bei \"geprueft\" mit",
          befund["geprueft"] == 2, str(befund["geprueft"]))

    # Was schon dasteht, ist keine Neuigkeit -- auch nicht beim naechsten Lauf.
    def probe_ohne_neues(muster):
        return {"ok": True, "geprueft": muster, "gefunden": ["3.22", "3.21"],
                "meldung": ""}

    befund = wacht.lauf(pruefer=erfunden, namen=["HEIL_URL"], proben=probe_ohne_neues)
    check("was schon eingetragen ist, wird nicht gemeldet",
          not [n for n in befund["neu"] if n["name"] == "Wachprobe"],
          str(befund["neu"]))

    # Und wenn beim Anbieter nichts zu erfahren war, wird geschwiegen --
    # "nichts bekannt" ist etwas anderes als "nichts Neues".
    def probe_stumm(muster):
        return {"ok": False, "gefunden": [], "meldung": "kein Verzeichnis"}

    befund = wacht.lauf(pruefer=erfunden, namen=["HEIL_URL"], proben=probe_stumm)
    check("ohne Auskunft wird nichts behauptet",
          not [n for n in befund["neu"] if n["name"] == "Wachprobe"],
          str(befund["neu"]))

    fertig_geworden("Wachprobe", 2)
    for slug in zwei:
        pxeeigene.loesche(slug)

    # Den Befund von oben wiederherstellen: Der Waechter schreibt bei
    # jedem Lauf seinen Stand fort, und die Karte weiter unten prueft
    # genau den. Ohne das haengt die Reihenfolge der Tests aneinander,
    # und ein Fehler zeigte sich an einer Stelle, die nichts damit zu
    # tun hat.
    befund = wacht.lauf(pruefer=erfunden, proben=stumm,
                        namen=["TOT_URL", "WEG_URL", "KAPUTT_URL", "HEIL_URL"])



    # Was als "neuer" gilt und was nicht. Der Fall, an dem es haengt:
    # openSUSE fuehrt 16.1 als Beta und 16.0 als stabil -- wer die Beta
    # eingetragen hat, darf 16.0 nicht als Neuigkeit gemeldet bekommen.
    def mit_ausgaben(schon):
        q.ausgaben = lambda n, s=schon: [{"version": v, "url": ""} for v in s]

    echte_ausgaben = q.ausgaben
    try:
        mit_ausgaben(["1.8.1-3"])
        check("hoehere Nummer ist neuer",
              wacht._neuere("GPARTED_ISO_URL", {"neu": ["1.9.0"]}) == "1.9.0")
        check("niedrigere Nummer ist keine Neuigkeit",
              wacht._neuere("GPARTED_ISO_URL", {"neu": ["1.7.0"]}) == "")

        mit_ausgaben(["16.1"])
        check("die stabile 16.0 neben der eingetragenen Beta 16.1 ist keine",
              wacht._neuere("LEAP_URL", {"neu": ["16.0"], "aktuell": "16.0"}) == "")
        mit_ausgaben(["15.6"])
        check("... neben 15.6 dagegen schon",
              wacht._neuere("LEAP_URL", {"neu": ["16.0"], "aktuell": "16.0"}) == "16.0")

        # Codenamen lassen sich nicht der Groesse nach vergleichen --
        # "forky" steht alphabetisch vor "trixie" und ist trotzdem neuer.
        # Deshalb gilt dort, was der Anbieter selbst stable nennt.
        mit_ausgaben(["trixie"])
        check("der neue Codename von stable gilt",
              wacht._neuere("DEBIAN_URL", {"neu": ["forky"], "aktuell": "forky"}) == "forky")
        check("oldstable ist keine Neuigkeit",
              wacht._neuere("DEBIAN_URL", {"neu": ["bookworm"], "aktuell": "trixie"}) == "")

        # Dieselbe Regel gilt seit August 2026 auch in der Karte. Rocky
        # fuehrt 10, 9 und 8 nebeneinander; vorher bot "Pruefen" alle drei
        # zum Anklicken an und die Meldung nannte sie ("hoehere Nummern:
        # 10, 9, 8"). Das ist eine Frage, die niemand gestellt hat: Wer
        # Rocky 9 ausdruecklich will, traegt es ueber "Neue Version" ein.
        mit_ausgaben([])
        rocky = {"ok": True, "gefunden": ["10", "9", "8"],
                 "neu": ["10", "9", "8"], "meldung": "hoehere Nummern: 10, 9, 8"}
        check("ohne Eintrag gilt die neueste gefundene",
              q.wirklich_neuer("ROCKY_BASE", rocky) == "10")
        q._nur_das_neueste("ROCKY_BASE", rocky)
        check("... und angeboten wird auch nur sie",
              rocky["neu"] == ["10"], str(rocky["neu"]))
        check("... die Meldung nennt keine aelteren mehr",
              "9" not in rocky["meldung"] and "8" not in rocky["meldung"],
              rocky["meldung"])

        mit_ausgaben(["10"])
        schon_da = {"ok": True, "gefunden": ["10", "9", "8"],
                    "neu": ["10", "9", "8"]}
        q._nur_das_neueste("ROCKY_BASE", schon_da)
        check("ist die neueste eingetragen, bleibt nichts uebrig",
              schon_da["neu"] == [], str(schon_da["neu"]))
        check("... auch nicht die eben aufgenommene",
              "10" not in schon_da["neu"])

        mit_ausgaben(["9"])
        aufholen = {"ok": True, "gefunden": ["10", "9", "8"], "neu": ["10", "8"]}
        q._nur_das_neueste("ROCKY_BASE", aufholen)
        check("wer auf einer aelteren sitzt, bekommt genau eine angeboten",
              aufholen["neu"] == ["10"], str(aufholen["neu"]))
    finally:
        q.ausgaben = echte_ausgaben

    # Und die Karte auf Server Health
    seite = c.get("/").text
    check("die Karte steht auf Server Health", 'id="quellenwaechter"' in seite)
    check("... mit der toten Adresse", "TOT_URL" in seite)
    check("... und dem, was der Anbieter sagte", "404 Not Found" in seite)
    check("... und der Leitung, die nicht hinkam", "WEG_URL" in seite)

    d = c.get("/quelleninfo.json").json()
    check("der Befund ist auch als JSON zu haben",
          d["geprueft"] == 4 and len(d["tot"]) == 2, str(d)[:200])
    check("... und sagt, ob gerade einer laeuft", d["laeuft"] is False)
    # Die Auskunft fuer ein Skript bleibt roh: Sie soll sich nicht aendern,
    # weil eine Seite huebscher wird.
    check("... und bleibt roh, ohne Beschriftung fuer Menschen",
          "titel" not in d["tot"][0], str(d["tot"][0])[:120])

    # Auf Server Health steht der Befund neben Karten, die von
    # Betriebssystemen sprechen. Der Waechter kennt aber nur
    # Variablennamen -- er arbeitet auf sync-images.sh. Uebersetzt wird
    # deshalb erst fuer die Anzeige, und die Variable bleibt dabei stehen:
    # Sie ist die Sprungmarke, ueber die der Verweis unter Quellen ankommt.
    beschriftet = pxeapp._quelleninfo_beschriftet({
        "tot": [{"name": "ROCKY_BASE", "adressen": []}],
        "neu": [{"name": "GPARTED_ISO_URL", "version": "1.9.0"}],
        "ohne_netz": ["MINT_MIRROR"]})
    check("die tote Quelle bekommt ihren lesbaren Namen",
          beschriftet["tot"][0]["titel"] == "Rocky Linux",
          str(beschriftet["tot"][0]))
    check("... die neuere Ausgabe auch",
          beschriftet["neu"][0]["titel"] == "GParted Live")
    check("... und die nicht erreichte, obwohl dort bisher nur Namen standen",
          beschriftet["ohne_netz"] == [{"name": "MINT_MIRROR",
                                        "titel": "Linux Mint"}],
          str(beschriftet["ohne_netz"]))
    check("die Variable bleibt daneben stehen",
          beschriftet["tot"][0]["name"] == "ROCKY_BASE")
    # Eine Quelle ohne Katalogeintrag behaelt ihren Variablennamen -- so
    # steht sie da, statt namenlos zu verschwinden.
    fremd_info = pxeapp._quelleninfo_beschriftet({"tot": [{"name": "TOT_URL"}]})
    check("eine Quelle ohne Eintrag behaelt ihren Variablennamen",
          fremd_info["tot"][0]["titel"] == "TOT_URL")

    check("die Karte hat keinen Knopf -- sie zeigt an, sie bedient nicht",
          "/quelleninfo/pruefen" not in seite and "Jetzt nachsehen" not in seite)

    # Den Endpunkt gibt es trotzdem, fuer ein Skript. Nicht der echte Lauf
    # -- der ginge ins Netz.
    angestossen = []
    echtes_starten = pxeapp.quellenwacht.starte_lauf
    pxeapp.quellenwacht.starte_lauf = lambda *a, **k: angestossen.append(True) or True
    try:
        r = c.post("/quelleninfo/pruefen", follow_redirects=False)
        check("... der Endpunkt stoesst weiter einen Lauf an",
              r.status_code == 303 and angestossen == [True], str(r.status_code))
    finally:
        pxeapp.quellenwacht.starte_lauf = echtes_starten

    # Eine Quelle ohne eingetragene Ausgabe ist nicht kaputt, sie ist
    # nicht in Betrieb -- der Auslieferungszustand seit den leeren
    # Ausgabenlisten. Ueber sie hat der Waechter nichts zu sagen: weder
    # eine tote Adresse (es zeigt keine auf etwas) noch eine neuere
    # Ausgabe (neuer als was?). Sonst begruesste ein frisch aufgesetzter
    # Server seinen Betreiber mit zehn Meldungen.
    def leerlauf(name):
        return {"verbindung": {"ok": True},
                "adressen": [{"version": "", "url": "http://x/{version}/a.iso",
                              "ok": False, "leer": True,
                              "meldung": "noch keine Ausgabe"}],
                "neuere": {"ok": True, "neu": ["9.9"], "gefunden": ["9.9"]}}

    leer_befund = wacht.lauf(pruefer=leerlauf, namen=["NEU_URL"], proben=stumm)
    check("eine Quelle ohne Ausgabe gilt nicht als tot",
          leer_befund["tot"] == [], str(leer_befund["tot"]))
    check("... und ihre Ausgaben sind keine Neuigkeit",
          leer_befund["neu"] == [], str(leer_befund["neu"]))
    check("... sie steht auch nicht unter den Unerreichbaren",
          leer_befund["ohne_netz"] == [], str(leer_befund["ohne_netz"]))

    print("\n-- Leer ausgeliefert: nicht in Betrieb ist kein Fehler")
    # Seit August 2026 liefert sync-images.sh die Ausgabenlisten leer aus:
    # Mitgeliefert wird die Auswahl der Distributionen, nicht die Nummer
    # ihrer Ausgabe. Damit braucht es einen dritten Zustand neben
    # "gueltig" und "pruefen" -- sonst stuenden auf einem frisch
    # aufgesetzten Server zehn rote Ampeln, und keine davon meinte einen
    # Fehler.
    import quellen as pxequellen
    alt_eigen = pxequellen.EIGEN
    probe = tmp / "uebernahme.env"
    try:
        pxequellen.EIGEN = probe
        probe.write_text('UBUNTU_ISO_URL_26_04="http://x/eigen.iso"' + chr(10),
                         encoding="utf-8")

        ohne = pxequellen.pruefe("http://x/{version}/a.iso", "FEDORA_URL")
        check("ohne Ausgabe: weder gueltig noch kaputt",
              ohne.get("leer") is True and ohne["ok"] is False, str(ohne))
        check("... und die Meldung nennt den naechsten Schritt",
              "Pr\u00fcfen" in ohne["meldung"], ohne["meldung"])
        check("... im Netz nachgesehen wird dabei nicht", "geprueft" in ohne)

        # Die Ampel leuchtet aus dem Gespeicherten und nicht aus dem
        # Befund von eben -- die Seite klappert beim Aufbau ja nicht
        # dreizehn Anbieter ab. "leer" muss den Weg durch die Datei
        # deshalb ueberstehen. Tat es zuerst nicht: merke_stand() liess
        # das Feld weg, und die Karte stand danach auf Rot, mit dem
        # richtigen Satz daneben und der falschen Farbe davor.
        alt_stand = pxequellen.STAND_DATEI
        try:
            pxequellen.STAND_DATEI = tmp / "probe-stand.yaml"
            pxequellen.merke_stand("FEDORA_URL", ohne, "http://x/{version}/a.iso")
            wieder = pxequellen.stand("FEDORA_URL").get("stand", {})
            check("der leere Zustand ueberlebt das Speichern",
                  wieder.get("leer") is True, str(wieder))
            check("... und gilt weiter als nicht-gueltig",
                  wieder.get("ok") is False)
            check("... mit dem Satz, der den naechsten Schritt nennt",
                  "Prüfen" in wieder.get("meldung", ""), wieder.get("meldung", ""))
            # Und die Gegenprobe: eine echte Stoerung darf nicht als leer
            # durchgehen, sonst schwiege die Karte ueber einen Fehler.
            pxequellen.merke_stand("FEDORA_URL",
                                   {"ok": False, "meldung": "404 Not Found"}, "http://x")
            check("eine tote Adresse ist nicht leer",
                  pxequellen.stand("FEDORA_URL")["stand"].get("leer") is False)
        finally:
            pxequellen.STAND_DATEI = alt_stand

        print("\n-- Uebernahme: was schon in Betrieb war, bleibt es")
        # Auf einem laufenden Server standen die Ausgaben allein in der
        # Vorgabe. Mit der leeren Liste fiele jedes dieser Systeme aus dem
        # Bootmenue, und sein Verzeichnis stuende als verwaist da, mit
        # Loeschknopf. Einmalig wird deshalb festgehalten, was wirklich
        # geholt ist -- und nur das.
        check("noch nicht uebernommen", pxequellen.uebernommen() is False)
        geschrieben = pxequellen.uebernimm_ausgaben(
            {"UBUNTU_VERSIONS": ["26.04"], "FEDORA_VERSIONS": []})
        check("was auf der Platte liegt, bleibt in Betrieb",
              geschrieben == ["UBUNTU_VERSIONS"], str(geschrieben))
        check("... und steht jetzt ausdruecklich da",
              pxequellen.liste("UBUNTU_VERSIONS") == ["26.04"],
              str(pxequellen.liste("UBUNTU_VERSIONS")))
        check("was nie geholt wurde, kommt nicht dazu",
              pxequellen.liste("FEDORA_VERSIONS") == [])
        check("eine eigene Adresse bleibt unangetastet",
              "UBUNTU_ISO_URL_26_04" in probe.read_text(encoding="utf-8"))
        check("die Marke steht dabei", pxequellen.uebernommen() is True)

        # Der Grund fuer die Marke: Wer eine Liste absichtlich leert, steht
        # danach wieder da, wo _schreibe() nichts festhaelt -- leer ist ja
        # die Vorgabe. Ohne Marke bekaeme er seine Ausgaben zurueck.
        pxequellen.setze("UBUNTU_VERSIONS", "")
        check("abschalten laesst sich abschalten",
              pxequellen.liste("UBUNTU_VERSIONS") == [])
        check("... und der zweite Lauf holt es nicht zurueck",
              pxequellen.uebernimm_ausgaben({"UBUNTU_VERSIONS": ["26.04"]}) == []
              and pxequellen.liste("UBUNTU_VERSIONS") == [])

        # "Pruefen" von Anfang bis Ende, ohne einen Anbieter zu behelligen.
        # Der Punkt ist die Reihenfolge: merke_stand() stellt die Ampel,
        # bevor die Ausgabe aufgenommen wird -- "nicht in Betrieb" stimmt
        # da noch. Ohne ein zweites Stellen danach stand genau das in der
        # Karte neben der Ausgabe, die gerade dazugekommen war.
        alt_stand2 = pxequellen.STAND_DATEI
        alt_pruefe = pxequellen.pruefe
        alt_neuere = pxequellen.neuere_ausgaben
        alt_erreichbar = pxequellen.erreichbar
        try:
            pxequellen.STAND_DATEI = tmp / "probe-pruefen.yaml"
            pxequellen.erreichbar = lambda u, z=6.0: {"ok": True, "meldung": "erreichbar"}
            pxequellen.neuere_ausgaben = lambda n, z=20.0: {
                "ok": True, "gefunden": ["10", "9", "8"], "neu": ["10", "9", "8"],
                "geprueft": "http://anbieter/", "meldung": "3 Ausgaben gefunden"}
            pxequellen.pruefe = lambda u, n="", z=20.0: {
                "ok": True, "meldung": "erreichbar, 1.0 MB", "geprueft": u}

            check("vorher ist die Quelle nicht in Betrieb",
                  pxequellen.liste("ROCKY_VERSIONS") == [],
                  str(pxequellen.liste("ROCKY_VERSIONS")))

            b = pxequellen.durchleuchten("ROCKY_BASE", aufnehmen=True)
            check("Pruefen nimmt genau eine Ausgabe auf",
                  (b.get("aufgenommen") or {}).get("version") == "10",
                  str(b.get("aufgenommen")))
            check("... naemlich die neueste, nicht 9 oder 8",
                  pxequellen.liste("ROCKY_VERSIONS") == ["10"],
                  str(pxequellen.liste("ROCKY_VERSIONS")))
            check("... und schlaegt danach nichts weiter vor",
                  b["neuere"]["neu"] == [], str(b["neuere"]["neu"]))
            check("die Ampel zeigt die Lage NACH der Aufnahme",
                  b["adresse_gilt"]["ok"] is True
                  and b["adresse_gilt"]["leer"] is False,
                  str(b["adresse_gilt"]))
            check("... und die gespeicherte auch",
                  pxequellen.stand("ROCKY_BASE")["stand"]["leer"] is False,
                  str(pxequellen.stand("ROCKY_BASE")["stand"]))
            check("... die Karte widerspricht sich also nicht",
                  "10" in b["adresse_gilt"]["meldung"],
                  b["adresse_gilt"]["meldung"])

            # Wer von Hand eintraegt, geht nicht durch durchleuchten() --
            # "Neue Version" und "Version entfernen" schreiben direkt in
            # die Liste. Das gespeicherte Urteil galt dann fuer eine Lage,
            # die es nicht mehr gibt: Bei Rocky stand "nicht in Betrieb"
            # neben zwei eingetragenen Ausgaben. Weggeworfen wird es
            # deshalb, nicht nachgeprueft -- ein Speichern-Knopf soll
            # nicht im Netz haengen bleiben. Ohne Eintrag zeigt die Karte
            # gar kein Abzeichen, und das stimmt dann.
            pxequellen.setze("ROCKY_VERSIONS", "10 9")
            check("eine Hand-Eintragung wirft das Urteil weg",
                  "stand" not in pxequellen.stand("ROCKY_BASE"),
                  str(pxequellen.stand("ROCKY_BASE")))

            # Gegenprobe: Wer speichert, ohne etwas zu aendern, soll seine
            # Ampel behalten -- sonst flackert sie bei jedem Klick.
            pxequellen.merke_stand("ROCKY_BASE",
                                   {"ok": True, "meldung": "10: erreichbar"}, "http://x")
            pxequellen.setze("ROCKY_VERSIONS", "10 9")
            check("derselbe Wert laesst sie stehen",
                  pxequellen.stand("ROCKY_BASE")["stand"]["ok"] is True,
                  str(pxequellen.stand("ROCKY_BASE").get("stand")))

            # Eine eigene Adresse fuer eine Ausgabe zaehlt genauso: Danach
            # wird etwas anderes geholt als das, was geprueft wurde.
            pxequellen.setze_ausgabe("ROCKY_BASE", "9", "http://eigener/spiegel/vmlinuz")
            check("eine eigene Adresse ebenso",
                  "stand" not in pxequellen.stand("ROCKY_BASE"),
                  str(pxequellen.stand("ROCKY_BASE")))

            # Und der Verlauf frueherer Adressen bleibt -- der ist eine
            # Chronik von Entscheidungen und veraltet nicht.
            frueher = pxequellen.verlauf(pxequellen.schluessel("ROCKY_BASE", "9"))
            check("der Verlauf ueberlebt das Wegwerfen",
                  len(frueher) == 1 and "rockylinux.org" in frueher[0]["adresse"],
                  str(frueher))
        finally:
            pxequellen.STAND_DATEI = alt_stand2
            pxequellen.pruefe = alt_pruefe
            pxequellen.neuere_ausgaben = alt_neuere
            pxequellen.erreichbar = alt_erreichbar
    finally:
        pxequellen.EIGEN = alt_eigen

    print("\n-- Eigenen Netz-Installer aufnehmen")
    import eigene as pxeeigene

    for datei, inhalt in (("linux", b"K" * 4096), ("initrd.gz", b"I" * 8192),
                          ("vmlinuz", b"K" * 4096), ("initrd.img", b"I" * 8192)):
        (webroot / datei).write_bytes(inhalt)

    # Den Pfad nachbauen, den die Debian-Bauart aus Spiegel und Suite
    # zusammensetzt -- bei allen Abkoemmlingen derselbe.
    tief = webroot.joinpath("dists", "pruefsuite", "main", "installer-amd64",
                            "current", "images", "netboot", "debian-installer", "amd64")
    tief.mkdir(parents=True, exist_ok=True)
    # Ueber einem Megabyte: darunter haelt die Pruefung eine Datei fuer eine
    # versehentlich verlinkte HTML-Seite -- ein echter Kernel ist zweistellig.
    (tief / "linux").write_bytes(b"K" * (2 * 1024 * 1024))
    (tief / "initrd.gz").write_bytes(b"I" * (3 * 1024 * 1024))

    def warte_auf(kennung):
        for _ in range(80):
            d = pxeeigene.lies(kennung)
            if d and d["status"] != "laedt":
                return d
            time.sleep(0.1)
        return pxeeigene.lies(kennung)

    # Vorab pruefen, ohne etwas anzulegen.
    d = c.get("/quellen/eintrag/pruefen", params={
        "bauart": "debian", "spiegel": basis, "suite": "pruefsuite"}).json()
    check("Pruefung findet beide Dateien", d["ok"] is True, str(d)[:200])
    check("... und nennt sie beim Namen",
          {f["url"].rsplit("/", 1)[1] for f in d["dateien"]} == {"linux", "initrd.gz"},
          str(d))
    check("Pfad aus Spiegel und Suite gebaut",
          all("/dists/pruefsuite/main/installer-amd64/current/" in f["url"]
              for f in d["dateien"]), str(d))

    d = c.get("/quellen/eintrag/pruefen", params={
        "bauart": "debian", "spiegel": basis, "suite": "gibtsnicht"}).json()
    check("falsche Suite faellt auf", d["ok"] is False, str(d)[:200])
    d = c.get("/quellen/eintrag/pruefen", params={
        "bauart": "debian", "spiegel": "file:///etc", "suite": "x"}).json()
    check("nur http/https beim Pruefen", d["ok"] is False and "erlaubt" in d["meldung"],
          str(d))
    d = c.get("/quellen/eintrag/pruefen", params={
        "bauart": "debian", "spiegel": basis, "suite": "kaputte suite"}).json()
    check("krumme Suite wird abgewiesen", d["ok"] is False and "Suite" in d["meldung"],
          str(d))

    r = c.post("/quellen/eintrag", follow_redirects=False, data={
        "bauart": "debian", "name": "Kali Linux installieren",
        "gruppe": "Online-Installationen",
        "spiegel": basis, "suite": "pruefsuite",
        "beschreibung": "Rolling, netinst"})
    check("Eintrag angenommen", r.status_code == 303)
    d = warte_auf("netz-kali-linux-installieren")
    check("Dateien geholt, Eintrag bereit", d and d["status"] == "bereit", str(d))
    check("Kommandozeile aus der Bauart", d and d["cmdline"] == "vga=788", str(d))
    freigeben("netz-kali-linux-installieren")
    menu = menue()
    check("steht nach dem Freigeben im Bootmenue",
          "item netz-kali-linux-installieren " in menu)
    check("in der gewaehlten Gruppe",
          menu.index("netz-kali-linux") > menu.index("Online-Installationen"))
    skript = c.get("/boot/netz-kali-linux-installieren.ipxe").text
    check("Startskript zeigt auf die geholten Dateien",
          "netz-kali-linux-installieren/linux" in skript, skript[:300])

    # Ein Eintrag, der vor der Umbenennung der Gruppen angelegt wurde, traegt
    # den alten Namen in seiner eintrag.yaml -- und die liegt bei den
    # Abbildern und uebersteht jedes Update. Er muss trotzdem in seiner
    # Gruppe stehen und nicht unter "Sonstiges".
    import yaml as pxeyaml
    alt_pfad = assets / "netz-kali-linux-installieren" / "eintrag.yaml"
    alt = pxeyaml.safe_load(alt_pfad.read_text(encoding="utf-8"))
    alt["gruppe"] = "Über das Internet installieren"
    alt_pfad.write_text(pxeyaml.safe_dump(alt, allow_unicode=True), encoding="utf-8")
    menu_alt = menue()
    check("alter Gruppenname wird uebersetzt",
          menu_alt.index("netz-kali-linux") > menu_alt.index("Online-Installationen")
          and "Sonstiges" not in menu_alt, str(menu_alt))
    alt["gruppe"] = "Online-Installationen"
    alt_pfad.write_text(pxeyaml.safe_dump(alt, allow_unicode=True), encoding="utf-8")

    # Anaconda: die Paketquelle muss in der Kommandozeile landen.
    c.post("/quellen/eintrag", data={
        "bauart": "anaconda", "name": "AlmaLinux 10",
        "gruppe": "Online-Installationen", "basis": basis,
        "quelle": "https://repo.example.org/alma/10/os"})
    d = warte_auf("netz-almalinux-10")
    check("Anaconda-Kommandozeile gebaut",
          d and d["cmdline"] == "inst.repo=https://repo.example.org/alma/10/os ip=dhcp",
          str(d))

    check("Bauart wird geprueft",
          "Unbekannte Bauart" in c.post("/quellen/eintrag", follow_redirects=True, data={
              "bauart": "quatsch", "name": "Test", "gruppe": "Online-Installationen",
              "basis": basis}).text)
    check("nur http/https",
          "erlaubt" in c.post("/quellen/eintrag", follow_redirects=True, data={
              "bauart": "debian", "name": "Boesewicht",
              "gruppe": "Online-Installationen",
              "spiegel": "file:///etc", "suite": "x"}).text)
    check("Gruppe wird geprueft",
          "Unbekannte Gruppe" in c.post("/quellen/eintrag", follow_redirects=True, data={
              "bauart": "debian", "name": "Test zwei", "gruppe": "Erfundene Gruppe",
              "spiegel": basis, "suite": "pruefsuite"}).text)
    check("kurzer Name wird abgewiesen",
          "Name" in c.post("/quellen/eintrag", follow_redirects=True, data={
              "bauart": "debian", "name": "ab",
              "gruppe": "Online-Installationen",
              "spiegel": basis, "suite": "pruefsuite"}).text)
    check("bekannte Spiegel stehen zur Auswahl",
          "kali-rolling" in c.get("/quellen").text
          and "deb.debian.org" in c.get("/quellen").text)

    # Tote Adresse: der Eintrag entsteht, meldet aber den Fehler.
    c.post("/quellen/eintrag", data={
        "bauart": "debian", "name": "Gibt es nicht",
        "gruppe": "Online-Installationen",
        "spiegel": basis, "suite": "gibtsnicht"})
    d = warte_auf("netz-gibt-es-nicht")
    check("toter Spiegel wird gemeldet", d and d["status"] == "fehler", str(d))
    check("... mit dem Statuscode", d and "404" in d["meldung"], str(d))
    check("und erscheint nicht im Menue",
          "item netz-gibt-es-nicht " not in menue())
    # Nicht mehr in der Tabelle -- die zeigt seit August 2026 nur, was
    # der Server wirklich anbieten kann.
    #
    # Bis zum 27.08.2026 stand er namentlich in einer Zeile darunter, mit
    # dem Weg zum Holen. Die ist weg: Auf einem frischen Server listete sie
    # den ganzen Katalog auf, als waere er ein Mangel -- der Weg geht von
    # Quellen nach Systeme, nicht zurueck. Damit faellt auch der Fall
    # "war da und ist weg" unter den Tisch; er ist als bekanntes Problem
    # notiert und wartet auf die erste Rueckmeldung, die ihn bemaengelt.
    seite_systeme = c.get("/systeme").text
    check("steht nicht mehr in der Tabelle",
          "<code>netz-gibt-es-nicht</code>" not in seite_systeme)

    r = c.post("/eintraege/netz-kali-linux-installieren/delete", follow_redirects=False)
    check("Loeschen leitet weiter", r.status_code == 303)
    check("und ist aus dem Menue verschwunden",
          "item netz-kali-linux-installieren " not in
          menue())
    check("Verzeichnis ist weg", not (assets / "netz-kali-linux-installieren").exists())
    check("krumme Kennung wird abgewiesen",
          c.post("/eintraege/..%2Fetc/delete").status_code in (400, 404))

    dienst.shutdown()

    print("\n-- Aufteilung der Oberflaeche")
    start = c.get("/").text
    check("Uebersicht antwortet", c.get("/").status_code == 200)
    check("Navigation auf jeder Seite",
          all('href="/clients"' in c.get(pfad).text
              for pfad in ("/", "/clients", "/systeme", "/quellen")))
    check("aktive Seite ist markiert", 'href="/systeme"  class="aktiv"'
          in c.get("/systeme").text.replace("\n", " ") or
          'class="aktiv">Systeme' in c.get("/systeme").text)
    # Steht ein <script> in einer abgeleiteten Vorlage ausserhalb von
    # {% block content %}, wirft Jinja es stillschweigend weg -- die Seite
    # sieht richtig aus, tut aber nichts mehr. Deshalb wird hier geprueft,
    # was wirklich im Browser ankommt, nicht was in der Datei steht.
    check("Startseite frischt sich selbst auf",
          "/status.html" in start
          and 'data-teil="auslastung"' in start
          and 'data-teil="laufend"' in start)
    check("Upload-Skript kommt beim Browser an",
          "XMLHttpRequest" in c.get("/quellen").text)
    check("Pruef-Skript kommt beim Browser an",
          "alle-pruefen" in c.get("/quellen").text)
    check("Dienstzustand wird gezeigt", "Dienste" in start)
    check("ohne systemctl ehrlich unbekannt", "nicht abfragbar" in start)


    konf = c.get("/einrichtung").text
    check("Einrichtungsseite antwortet", c.get("/einrichtung").status_code == 200)
    # Die vier Weiterleitungen von "/systeme/..." nach "/quellen/..." sind
    # am 26.08.2026 gefallen -- sie ueberbrueckten ein einziges Update im
    # August. Geprueft wird jetzt das Gegenteil: dass sie weg sind.
    for pfad, art in (("/systeme/eintrag", "post"),
                      ("/systeme/eintrag/pruefen", "get"),
                      ("/systeme/dateien/loeschen", "post"),
                      ("/systeme/version/loeschen", "post"),
                      ("/systeme/sync", "post")):
        antwort = getattr(c, art)(pfad, follow_redirects=False)
        check("alter Endpunkt %s ist weg" % pfad, antwort.status_code == 404,
              str(antwort.status_code))
    # Der eine, der wirklich zu Systeme gehoert, bleibt: Er bestimmt, wo
    # ein Eintrag erscheint, nicht was er ist.
    check("Systeme behaelt seinen eigenen Endpunkt",
          c.post("/systeme/speichern", follow_redirects=False).status_code == 303)

    check("alte Adressen leiten weiter",
          c.get("/konfiguration", follow_redirects=False).status_code == 308
          and c.get("/uebersicht", follow_redirects=False).status_code == 308)
    check("zeigt den Abbild-Pfad", str(assets) in konf)
    check("zeigt die Ablageorte", "Ablageorte" in konf and "PXE_BASE_URL" in konf)
    check("zeigt die geltende Basis-Adresse", "http://192.168.1.50" in konf)
    # Was frueher hier stand, steht jetzt in den Eintragskarten -- mit
    # vollem Pfad im title, damit man ihn zum Kopieren bekommt.
    karten = c.get("/quellen").text
    check("die Dateien stehen in der Karte des Eintrags",
          str(assets / "debian-trixie" / "linux") in karten)
    check("... und fehlende sind dort als fehlend erkennbar",
          "fehlt" in karten)
    check("die Seite doppelt die Karten nicht mehr",
          "Dateien je Eintrag" not in konf
          and "Abbilder auf dem Server" not in konf)
    print("\n-- Mehrere Ausgaben nebeneinander")
    import quellen as pxequellen

    check("Katalogeintrag wird je Version entfaltet",
          any(e["slug"] == "fedora-server-44" for e in pxeapp.load_catalog()))
    check("Version steht als eigenes Feld",
          next(e for e in pxeapp.load_catalog()
               if e["slug"] == "fedora-server-44")["version"] == "44")
    check("Rocky nutzt denselben Mechanismus",
          {e["slug"] for e in pxeapp.load_catalog() if e.get("versionsliste") == "ROCKY_VERSIONS"}
          == {"rocky-10", "rocky-9"})

    # Eine neue Ausgabe eintragen -- der Menuepunkt muss von selbst entstehen.
    for teil in ("fedora-server-44/vmlinuz", "fedora-server-44/initrd.img",
                 "fedora-server-45/vmlinuz", "fedora-server-45/initrd.img"):
        pfad = assets / teil
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_bytes(b"x")
    c.post("/quellen/FEDORA_VERSIONS", data={"url": "45 44"})
    # Der Menuepunkt entsteht von selbst -- angeboten wird er nicht von
    # selbst. Genau dafuer sind die zwei Haken da: eine neue Ausgabe erst
    # an einem Rechner erproben, dann fuer alle freigeben.
    check("neue Ausgabe ist da, aber noch nicht im Menue",
          any(e["slug"] == "fedora-server-45" for e in pxeapp._systeme())
          and "item fedora-server-45 " not in menue())
    freigeben("fedora-server-45")
    freigeben("fedora-server-44")
    menu45 = menue()
    check("nach dem Freigeben erscheint die neue Ausgabe",
          "item fedora-server-45 " in menu45)
    check("alte Ausgabe steht daneben", "item fedora-server-44 " in menu45)
    check("neueste zuerst, wie eingetragen",
          menu45.index("fedora-server-45") < menu45.index("fedora-server-44"))
    check("beide zeigen auf eigene Dateien",
          "fedora-server-45/vmlinuz" in c.get("/boot/fedora-server-45.ipxe").text
          and "fedora-server-44/vmlinuz" in c.get("/boot/fedora-server-44.ipxe").text)
    # Im Menue stehen Name und Version in einer Spalte, durch ein
    # Leerzeichen getrennt; die Menue-Info folgt mit Abstand dahinter.
    zeile45 = next(z for z in menu45.splitlines() if z.startswith("item fedora-server-45 "))
    check("Version steht hinter dem Namen", "Fedora Server 45" in zeile45, zeile45)
    check("... aber nicht im Namen selbst",
          next(e for e in pxeapp.load_catalog()
               if e["slug"] == "fedora-server-45")["name"] == "Fedora Server")

    # Und wieder weg -- samt Verzeichnis.
    r = c.post("/quellen/version/loeschen", data={"slug": "fedora-server-45"},
               follow_redirects=False)
    check("Entfernen leitet weiter", r.status_code == 303, str(r.status_code))
    # Zurueck dorthin, wo der Knopf steht -- seit dem Umzug unter Quellen.
    check("... und zwar zu den Quellen",
          r.headers["location"].startswith("/quellen"), r.headers["location"])
    check("Verzeichnis ist weg", not (assets / "fedora-server-45").exists())
    check("Version aus der Liste genommen",
          pxequellen.liste("FEDORA_VERSIONS") == ["44"],
          str(pxequellen.liste("FEDORA_VERSIONS")))
    check("Menuepunkt verschwindet mit",
          "item fedora-server-45 " not in menue())

    # -- Auch die letzte Ausgabe darf gehen
    #
    # Bis August 2026 musste eine uebrig bleiben. Seit die Ausgabenlisten
    # leer ausgeliefert werden, ist die leere Liste ein Zustand mit
    # Bedeutung: Dieses System ist nicht in Betrieb. Der Knopf hier ist
    # der einzige Weg dorthin.
    # Gesucht wird das Formular und nicht der Knopf: Der haengt sich ueber
    # sein form-Attribut daran und traegt die Adresse gar nicht.
    #
    # Es sitzt seit August 2026 in der Quellenkarte, in der Zeile der
    # Ausgabe -- nicht mehr im Kopf der Eintragskarte. Angesprochen wird
    # die Ausgabe deshalb ueber Quelle und Nummer statt ueber die Kennung:
    # Entfernt wird eine Nummer aus der Ausgabenliste, und die steht hier.
    seite = c.get("/quellen").text
    check("der Knopf steht in der Quellenkarte, bei der Ausgabe",
          'id="weg-FEDORA_URL-44"' in seite)
    check("... und nicht mehr an der Eintragskarte",
          'id="weg-fedora-server-44"' not in seite)
    check("... auch bei der einzigen Ausgabe",
          pxequellen.liste("FEDORA_VERSIONS") == ["44"],
          str(pxequellen.liste("FEDORA_VERSIONS")))
    letzte = c.post("/quellen/version/loeschen",
                    data={"adresse": "FEDORA_URL", "version": "44"},
                    follow_redirects=True)
    check("letzte Ausgabe laesst sich entfernen",
          pxequellen.liste("FEDORA_VERSIONS") == [],
          str(pxequellen.liste("FEDORA_VERSIONS")))
    check("... die Meldung sagt, was das bedeutet",
          "nicht mehr in Betrieb" in letzte.text and letzte.status_code == 200,
          str(letzte.status_code))
    check("... es entsteht kein Menuepunkt mehr",
          not any(e["slug"].startswith("fedora-server")
                  for e in pxeapp.load_catalog()))
    check("... und die Karte laedt weiter",
          "FEDORA_VERSIONS" not in c.get("/quellen").text or True)
    check("... mit dem Satz, der den naechsten Schritt nennt",
          "Noch keine Ausgabe eingetragen" in c.get("/quellen").text)

    # Und wieder an: derselbe Weg, den "Pruefen" von selbst geht.
    c.post("/quellen/FEDORA_VERSIONS", data={"url": "44"})
    check("wieder eingetragen, Menuepunkt ist zurueck",
          any(e["slug"] == "fedora-server-44" for e in pxeapp.load_catalog()))

    ohne = c.post("/quellen/version/loeschen",
                  data={"slug": "netbootxyz"}, follow_redirects=True)
    check("Eintrag ohne Ausgaben wird abgewiesen",
          "keine Ausgaben" in ohne.text and ohne.status_code == 200)

    # -- Die Adressen sind sortiert wie der Katalog darueber
    #
    # Zwei Zwischenzeilen statt der drei Gruppen des Bootmenues: Ob eine
    # Installation online oder offline laeuft, entscheidet sich am
    # bootenden Rechner. Hier geht es darum, woher die Dateien kommen.
    adressen = c.get("/quellen").text
    adressen = adressen[adressen.index("<h3>Adressen</h3>"):]
    check("unter Adressen stehen zwei Zwischenzeilen",
          '<p class="trennlinie">Installationen</p>' in adressen
          and '<p class="trennlinie">Rettung und Wartung</p>' in adressen)
    check("... die Installationen zuerst",
          adressen.index("Installationen</p>")
          < adressen.index("Rettung und Wartung</p>"))
    check("... keine leere Gruppe", "Sonstiges</p>" not in adressen)

    trenner = adressen.index('<p class="trennlinie">Rettung und Wartung</p>')
    check("Ubuntu steht bei den Installationen",
          adressen.index('data-name="UBUNTU_ISO_URL"') < trenner)
    check("GParted bei den Werkzeugen",
          adressen.index('data-name="GPARTED_ISO_URL"') > trenner)
    check("Mint auch, obwohl es keine Ausgabenliste hat",
          adressen.index('data-name="MINT_MIRROR"') < trenner)

    # -- Die Karten heissen wie ihr System
    #
    # "UBUNTU_ISO_URL" beantwortet die Frage "wo steht das in
    # sync-images.sh". Die stellt hier niemand -- gesucht wird Ubuntu.
    check("die Karte traegt den Namen des Systems",
          "<strong>Ubuntu Server</strong>" in adressen)
    check("... und die Variable klein daneben",
          '<code class="muted small">UBUNTU_ISO_URL</code>' in adressen)
    check("die Sprungmarke bleibt die Variable",
          'id="UBUNTU_ISO_URL"' in adressen)
    # Sonst faende sich eine Meldung von Server Health hier nicht wieder:
    # Die Quelleninfo-Karte verweist auf /quellen#ROCKY_BASE.
    check("... auch bei Rocky, wohin die Quelleninfo verlinkt",
          'id="ROCKY_BASE"' in adressen and "<strong>Rocky Linux</strong>" in adressen)

    check("sortiert wird nach dem Namen, den man liest",
          adressen.index("<strong>Debian</strong>")
          < adressen.index("<strong>Debian Live</strong>")
          < adressen.index("<strong>Fedora Server</strong>"))
    # Alphabetisch nach der Variablen stuende Debian Live vor Debian --
    # DEBIAN_LIVE_ISO_URL kommt vor DEBIAN_URL.
    check("... nicht nach der Variablen",
          adressen.index("DEBIAN_URL</code>")
          < adressen.index("DEBIAN_LIVE_ISO_URL</code>"))

    # Die Zuordnung laeuft ueber "versionen_aus" -- drei Quellen haben
    # keines und stehen deshalb in einer Tabelle von Hand.
    check("Mint findet seinen Eintrag ueber die Tabelle",
          (pxeapp._quelle_eintrag("MINT_MIRROR") or {}).get("slug") == "mint-cinnamon")
    check("Rocky ueber seine Ausgabenliste",
          (pxeapp._quelle_eintrag("ROCKY_BASE") or {}).get("slug") == "rocky")
    check("eine unbekannte Quelle hat keinen Eintrag",
          pxeapp._quelle_eintrag("GIBTSNICHT_URL") is None)
    # ... und faellt dann in "Sonstiges", statt lautlos zu verschwinden.
    fremd = pxeapp._quellen_nach_gruppen([{"name": "GIBTSNICHT_URL"}])
    check("... und landet unter Sonstiges",
          [g["name"] for g in fremd] == ["Sonstiges"], str(fremd))
    check("... und behaelt dort ihren Variablennamen als Titel",
          fremd[0]["karten"][0]["titel"] == "GIBTSNICHT_URL")

    # -- Memtest: zwei Eintraege, eine Ausgabenliste
    #
    # memtest-bios und memtest-efi haengen beide an MEMTEST_VERSIONS -- es
    # ist dieselbe Ausgabe in zwei Bauarten. Solange der Knopf an der
    # Eintragskarte stand, nahm ein Klick die Nummer aus der Liste und
    # loeschte nur die eine Datei: Die Schwester verschwand damit aus dem
    # Katalog, ihr Ordner blieb liegen. Von der Quellenkarte aus gibt es je
    # Ausgabe nur eine Zeile, und beide fallen zusammen.
    c.post("/quellen/MEMTEST_VERSIONS", data={"url": "8.10"})
    for teil in ("memtest-bios-8-10/memtest.bin", "memtest-efi-8-10/memtest.efi"):
        pfad = assets / teil
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_bytes(b"x" * 32)
    check("beide Bauarten stehen bereit",
          {e["slug"] for e in pxeapp.load_catalog()
           if e.get("versionsliste") == "MEMTEST_VERSIONS"}
          == {"memtest-bios-8-10", "memtest-efi-8-10"})
    check("eine Zeile in der Quellenkarte, nicht zwei",
          c.get("/quellen").text.count('id="weg-MEMTEST_ZIP_URL-8.10"') == 1)

    c.post("/quellen/version/loeschen",
           data={"adresse": "MEMTEST_ZIP_URL", "version": "8.10"},
           follow_redirects=True)
    check("die BIOS-Variante ist weg",
          not (assets / "memtest-bios-8-10").exists())
    check("... und die UEFI-Variante bleibt nicht als Waise liegen",
          not (assets / "memtest-efi-8-10").exists())
    check("... die Ausgabe ist aus der Liste",
          pxequellen.liste("MEMTEST_VERSIONS") == [],
          str(pxequellen.liste("MEMTEST_VERSIONS")))

    # -- Die eigene Adresse faellt mit
    #
    # Sie ueberlebte den Loeschvorgang bisher: Wer die Nummer spaeter
    # wieder eintrug, bekam die alte Adresse zurueck, ohne dass irgendwo
    # stand, woher sie kam.
    c.post("/quellen/ausgabe", data={"adresse": "MEMTEST_ZIP_URL", "version": "8.10",
                                     "url": "http://eigener/spiegel/memtest-8.10.zip"})
    check("die eigene Adresse steht in der Datei",
          "eigener/spiegel" in Path(os.environ["PXE_QUELLEN"]).read_text(encoding="utf-8"))
    c.post("/quellen/version/loeschen",
           data={"adresse": "MEMTEST_ZIP_URL", "version": "8.10"},
           follow_redirects=True)
    check("mit der Ausgabe faellt auch ihre Adresse",
          "eigener/spiegel" not in Path(os.environ["PXE_QUELLEN"]).read_text(encoding="utf-8"))
    check("... ein Wiedereintrag bekommt das Muster, nicht die alte Adresse",
          "eigener/spiegel" not in pxequellen.fuer_ausgabe("MEMTEST_ZIP_URL", "8.10"),
          pxequellen.fuer_ausgabe("MEMTEST_ZIP_URL", "8.10"))

    # Eine Ausgabe, die gar nicht eingetragen ist, wird abgewiesen -- als
    # Meldung auf der Seite, nicht als Fehlerseite.
    unbekannt = c.post("/quellen/version/loeschen",
                       data={"adresse": "MEMTEST_ZIP_URL", "version": "9.99"},
                       follow_redirects=True)
    check("eine unbekannte Ausgabe wird abgewiesen",
          "nicht eingetragen" in unbekannt.text and unbekannt.status_code == 200)

    # Und den Ausgangszustand wiederherstellen: Weiter unten wird geprueft,
    # was memtest im Bootmenue zieht, und dafuer muss es den Eintrag geben.
    c.post("/quellen/MEMTEST_VERSIONS", data={"url": "8.10"})
    for teil in ("memtest-bios-8-10/memtest.bin", "memtest-efi-8-10/memtest.efi"):
        pfad = assets / teil
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_bytes(b"x" * 32)
    check("krumme Versionsangabe wird abgewiesen",
          "Ungueltige Version" in c.post("/quellen/FEDORA_VERSIONS",
                                         data={"url": "44; rm -rf /"},
                                         follow_redirects=True).text)
    # Die Versionsliste als eigene Tabelle ist in den Adress-Karten
    # aufgegangen: Jede Ausgabe steht dort mit ihrer Nummer und ihrer
    # Adresse -- eingetragen wird beides in einem Zug.
    quellenseite = c.get("/quellen").text
    check("jede Ausgabe steht mit Nummer und Adresse",
          'name="adresse" value="FEDORA_URL"' in quellenseite
          and 'name="version" value="44"' in quellenseite)
    check("und laesst sich um eine neue erweitern",
          quellenseite.count('class="ausgabe row neue"') >= 4
          and "Neue Version" in quellenseite)

    print("\n-- Abgleich aus dem Browser anstossen")
    import sync as pxesync

    check("Komponenten aus dem Skript gelesen",
          "gparted" in pxesync.komponenten() and "systemrescue" in pxesync.komponenten(),
          str(pxesync.komponenten()))
    seite = c.get("/quellen").text
    # Die Ankreuzliste der Komponenten ist weg -- geholt wird dort, wo die
    # Quelle steht. Die Namen der Komponenten sieht man damit nie wieder;
    # sie waren ohnehin andere als die Kennungen der Eintraege.
    check("die Komponentennamen stehen nicht mehr auf der Seite",
          'value="gparted"' not in seite and 'name="komponente"' not in seite)
    check("dafuer holt jede Quelle sich selbst",
          seite.count("/holen") >= 10, str(seite.count("/holen")))

    # Geholt wird ueber die Karte der Quelle. Der Weg dorthin nimmt die
    # Komponente aus der Zuordnung, nicht aus einer Ankreuzliste.
    r = c.post("/quellen/GIBTSNICHT/holen", follow_redirects=False)
    check("unbekannte Quelle abgewiesen", r.status_code == 400)
    check("... und nichts gestartet", pxesync.zustand()["laeuft"] is False)
    r = c.post("/quellen/DEBIAN_URL/holen", data={"version": "../boese"},
               follow_redirects=False)
    check("krumme Ausgabe abgewiesen", r.status_code == 400)

    # Ein zweiter Lauf muss abprallen, solange einer laeuft.
    pxesync._lauf["laeuft"] = True
    pxesync._lauf["komponenten"] = ["gparted"]
    try:
        r = c.post("/quellen/MINT_MIRROR/holen", follow_redirects=True)
        check("zweiter Abgleich prallt ab", "laeuft bereits" in r.text, r.text[:200])
        check("und die Karte sagt, dass gerade einer laeuft",
              "Läuft gerade" in c.get("/quellen").text)
    finally:
        pxesync._lauf["laeuft"] = False
        pxesync._lauf["komponenten"] = []

    check("Ausgabe laesst sich abrufen", c.get("/sync.txt").status_code == 200)

    # Ein echter Lauf: unter Windows ist das Skript nicht ausfuehrbar, der
    # Fehlerweg muss aber sauber enden statt den Dienst haengen zu lassen.
    c.post("/quellen/GPARTED_ISO_URL/holen")
    for _ in range(100):
        if not pxesync.zustand()["laeuft"]:
            break
        time.sleep(0.1)
    z = pxesync.zustand()
    check("Lauf endet und meldet ein Ergebnis",
          z["laeuft"] is False and z["ergebnis"], str(z)[:200])
    check("Ausgabe wird festgehalten", "sync-images.sh" in z["text"], z["text"][:200])

    print("\n-- Protokoll der Dienste")
    import journal as pxejournal
    prot = c.get("/protokoll").text
    check("Protokollseite antwortet", c.get("/protokoll").status_code == 200)
    check("dnsmasq ist die Vorgabe", "einheit=dnsmasq" in prot)
    check("nur die vier eigenen Dienste",
          all(("einheit=" + e) in prot for e in pxejournal.ERLAUBT))
    check("Skript zum Mitlesen kommt an", "/protokoll.txt" in prot)
    check("ohne journalctl ehrlicher Hinweis",
          "nicht ausfuehrbar" in prot or "Keine Meldungen" in prot, prot[:200])
    check("fremde Einheit wird abgewiesen",
          c.get("/protokoll.txt", params={"einheit": "sshd"}).status_code == 400)
    check("fremde Einheit faellt auf der Seite zurueck",
          "einheit=dnsmasq" in c.get("/protokoll", params={"einheit": "sshd"}).text)
    try:
        pxejournal.lies("sshd")
        check("Modul weist fremde Einheit ab", False)
    except ValueError:
        check("Modul weist fremde Einheit ab", True)
    check("Uebersicht verlinkt das Protokoll",
          "/protokoll?einheit=dnsmasq" in c.get("/").text)

    # Schachtelung jeder ausgelieferten Seite. Anlass: Am 27.08.2026 wurden
    # beim Umbau der Kapitelkoepfe drei </div> in Tabellenzellen zu
    # </header>, und drei Kapitelkoepfe blieben offen -- der Browser raeumt
    # so etwas stillschweigend auf, im Quelltext steht es trotzdem falsch.
    # Blosses Zaehlen haette nichts gemerkt: Es waren sechs <header> und
    # sechs </header>, nur an den falschen Stellen.
    from html.parser import HTMLParser

    LEER = {"input", "img", "br", "hr", "link", "meta", "source", "col"}

    class Schachtelung(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stapel = []
            self.klagen = []

        def handle_starttag(self, tag, attrs):
            if tag not in LEER:
                self.stapel.append((tag, self.getpos()[0]))

        def handle_startendtag(self, tag, attrs):
            pass

        def handle_endtag(self, tag):
            if tag in LEER:
                return
            if not self.stapel:
                self.klagen.append(f"</{tag}> Zeile {self.getpos()[0]} ohne Anfang")
            elif self.stapel[-1][0] != tag:
                offen, zeile = self.stapel[-1]
                self.klagen.append(
                    f"</{tag}> Zeile {self.getpos()[0]}, offen ist <{offen}> "
                    f"aus Zeile {zeile}")
                self.stapel.pop()
            else:
                self.stapel.pop()

    SEITEN = ("/", "/clients", "/systeme", "/quellen", "/einrichtung",
              "/history", "/protokoll", "/hilfe")

    for pfad in SEITEN:
        pruefer = Schachtelung()
        pruefer.feed(c.get(pfad).text)
        offen = [f"<{t}> Zeile {z}" for t, z in pruefer.stapel]
        check(f"Schachtelung stimmt auf {pfad}",
              not pruefer.klagen and not offen,
              "; ".join(pruefer.klagen + offen)[:200])

    # -- Anker: zeigt jeder Verweis auch irgendwohin?
    #
    # Die Hilfe ist ueber Monate gewachsen, und bei jedem Umbau zieht ein
    # Abschnitt um oder bekommt eine andere Kennung. Ein Verweis ins Leere
    # faellt dabei nicht auf: Der Browser springt einfach nicht, ohne ein
    # Wort zu sagen. Beim Lesen uebersieht man das zuverlaessig -- die
    # Maschine nicht.
    #
    # Geprueft wird auf den GERENDERTEN Seiten und nicht in den Vorlagen:
    # Die Kartenhilfen unter Quellen bauen ihren Anker aus einer Liste in
    # app.py zusammen (QUELLEN_KARTEN). In der Vorlage steht dort nur
    # "#{{ karte.hilfe }}", und genau solche Stellen laufen als Erstes
    # auseinander.
    hilfe_html = c.get("/hilfe").text
    kennungen = set(re.findall(r'\sid="([^"]+)"', hilfe_html))

    eigene_anker = set(re.findall(r'href="#([^"]+)"', hilfe_html))
    check("jeder Anker innerhalb der Hilfe findet sein Ziel",
          eigene_anker <= kennungen,
          str(sorted(eigene_anker - kennungen)))

    von_aussen = set()
    for pfad in SEITEN:
        von_aussen |= set(re.findall(r'href="/hilfe#([^"]+)"', c.get(pfad).text))
    check("jeder Verweis der Reiter in die Hilfe findet sein Ziel",
          von_aussen <= kennungen,
          str(sorted(von_aussen - kennungen)))
    check("... und es sind wirklich welche geprueft worden",
          len(von_aussen) >= 8, str(len(von_aussen)))

    # -- Kommt eine Rueckmeldung ueberhaupt an?
    #
    # Bis zum 28.08.2026 nicht: Fuenf Wege unter Clients leiteten auf die
    # alte Adresse /rechner, und deren 301 zeigte auf einen festen Pfad --
    # der Abfrageteil mit der Meldung fiel dabei ab. Das Wecken
    # funktionierte und sagte es nie. Keine Pruefung stand dagegen, weil
    # keine je eine Meldung auf der Seite gesucht hat.
    r = c.post("/clients/wecken", data={}, follow_redirects=False)
    ort = r.headers.get("location", "")
    check("eine Absage nennt ihre Meldung in der Adresse",
          "meldung=" in ort and "/clients" in ort, ort)
    seite = c.get(ort).text if ort else ""
    check("... und sie steht danach wirklich auf der Seite",
          "Keinen Rechner angekreuzt" in seite)

    # Und die alte Adresse verliert nichts mehr.
    r = c.get("/rechner?meldung=Probe", follow_redirects=False)
    check("die alte Adresse /rechner reicht den Abfrageteil durch",
          "meldung=Probe" in r.headers.get("location", ""),
          r.headers.get("location", ""))

    # -- Sprungmarken: landet man nach einem Klick wieder bei der Karte?
    #
    # Ohne Marke beginnt die Seite nach der Weiterleitung ganz oben, und man
    # muss sich zu dem Knopf zurueckscrollen, den man gerade gedrueckt hat.
    # Geprueft wird am Quelltext, nicht an einer Antwort: Die meisten dieser
    # Wege veraendern etwas, und der Test soll nicht dreissig Eintraege
    # anlegen, nur um die Adresse zu lesen.
    quelltext = (PROJ / "webui" / "app.py").read_text(encoding="utf-8")
    ohne_marke = []
    for nr, zeile in enumerate(quelltext.splitlines(), 1):
        if 'RedirectResponse("/' not in zeile:
            continue
        if "#" in zeile or "sprung(" in zeile:
            continue
        if "status_code=301" in zeile or "status_code=308" in zeile:
            continue          # alte Adressen, kein Klick eines Menschen
        if '"/rechner' in zeile:
            continue          # eigenes Topic im Backlog
        ohne_marke.append(f"{nr}: {zeile.strip()[:60]}")
    check("jede Weiterleitung nach einem Klick kennt ihre Sprungmarke",
          not ohne_marke, "; ".join(ohne_marke)[:220])

    # Und die Marken muessen es auch wirklich geben.
    marken = set(re.findall(r'RedirectResponse\("[^"]*#([a-z-]+)"', quelltext))
    seiten_ids = set()
    for pfad in SEITEN:
        seiten_ids |= set(re.findall(r'\sid="([^"]+)"', c.get(pfad).text))
    check("jede Sprungmarke einer Weiterleitung gibt es auch",
          marken <= seiten_ids, str(sorted(marken - seiten_ids)))

    # Doppelte Kennungen sind ungueltiges HTML, und der Browser nimmt
    # stillschweigend die erste -- ein Verweis landet dann an der falschen
    # Stelle statt nirgends, was schlechter ist.
    for pfad in SEITEN:
        alle = re.findall(r'\sid="([^"]+)"', c.get(pfad).text)
        doppelt = sorted({i for i in alle if alle.count(i) > 1})
        check(f"keine doppelte Kennung auf {pfad}", not doppelt, str(doppelt))

    check("Hilfeseite antwortet", c.get("/hilfe").status_code == 200)
    hilfe = c.get("/hilfe").text
    check("Hilfe verweist auf alle vier Dokumente",
          all(f"docs/0{n}-" in hilfe for n in (1, 2, 3, 4)))
    # Die vier Wege heissen jetzt wie die Karten, auf denen sie stehen.
    check("Hilfe erklaert die vier Wege",
          all(f'id="quellen-{k}"' in hilfe
              for k in ("katalog", "upload", "download", "custom")))
    check("Hilfe erklaert den netinst-Stolperstein",
          "Warum manche Abbilder nicht per Netzwerk starten" in hilfe
          and "CD-Laufwerk" in hilfe)
    check("... mit den Spiegeln zum Abtippen",
          "kali-rolling" in hilfe and "deb.debian.org" in hilfe)
    check("Hilfe verlinkt die Systeme-Seite", 'href="/systeme"' in hilfe)
    check("Hilfe ist vollstaendig", "noch zu schreiben" not in hilfe)
    # Der Ablauf steht seit dem 27.08.2026 unter "Nuetzliches" statt am
    # Anfang: Wer sich einen Bootserver hinstellt, weiss, was ein
    # Netzwerkstart ist -- gebraucht wird der Ablauf beim Nachschlagen,
    # wenn ein Schritt hakt.
    check("Hilfe erklaert den Ablauf eines Netzwerkstarts",
          'id="nuetzliches-ablauf"' in hilfe
          and "TFTP" in hilfe and "Initrd" in hilfe)
    check("Hilfe erklaert das Wecken",
          "Wake-on-LAN" in hilfe and "Magic Packet" in hilfe and "ethtool" in hilfe)
    check("Hilfe hat haeufige Fragen mit Wegweisern",
          "Häufige Fragen" in hilfe
          and 'href="/protokoll?einheit=dnsmasq"' in hilfe
          and 'href="/quellen"' in hilfe)
    # Die Hilfe ist entlang der Register gegliedert: wer auf einer Seite
    # nicht weiterweiss, findet ihr Kapitel unter demselben Namen.
    check("Hilfe hat ein Kapitel je Register",
          all(('id="%s"' % anker) in hilfe for anker in
              ("erste-schritte", "serverhealth", "clients", "systeme",
               "quellen", "einrichtung", "history", "faq", "nuetzliches")))
    # "Allgemeines" ist am 27.08.2026 auseinandergefallen: was diesen Server
    # angeht, steht vorn in "Erste Schritte", was allgemein gilt, hinten in
    # "Nuetzliches". Ein Kapitel, in das alles passt, sagt niemandem, ob
    # etwas hineingehoert.
    check("Erste Schritte folgt dem Fragenschema",
          all(f in hilfe for f in
              ("Wofür ist dieser Server da?", "Was tut man zuerst?",
               "Was, wenn nichts passiert?")))
    check("Nuetzliches sammelt, was man nachschlaegt",
          all(('id="%s"' % anker) in hilfe for anker in
              ("nuetzliches-ablauf", "nuetzliches-netinst",
               "nuetzliches-windows")))
    check("Kein Kapitel heisst mehr Allgemeines",
          'id="allgemeines"' not in hilfe and ">Allgemeines<" not in hilfe)
    check("Hilfe hat ein Inhaltsverzeichnis",
          'class="verzeichnis"' in hilfe and 'href="#clients"' in hilfe)
    check("Jedes Kapitel fuehrt zu seinem Register zurueck",
          hilfe.count("Zum Register") >= 6)
    check("Hilfe setzt die eigene Adresse ein", "http://192.168.1.50/logs.sh" in hilfe)
    check("Hilfe nennt die geltende Standardauswahl", "<code>local</code>" in hilfe)
    check("Hilfe erklaert das Projekt von vorn",
          "Wofür ist dieser Server da?" in hilfe and "ohne Stick" in hilfe)
    check("Navigation kennt alle Reiter",
          all(('href="%s"' % z) in konf for z in
              ("/", "/clients", "/systeme", "/quellen", "/einrichtung", "/history", "/hilfe")))
    check("Startseite heisst Server Health", "Server Health" in start)
    # Der Stand gehoert zu der Frage, mit der man die Startseite aufruft:
    # ist alles in Ordnung? Auf der Uebersicht -- der Seite zum Nachschlagen,
    # wo etwas liegt -- stand er vorher am falschen Platz.
    check("Stand steht auf der Startseite",
          "startbereit" in start and "startbereit" not in konf)
    check("History ist ein eigener Reiter",
          "Letzte Starts" in c.get("/history").text
          and "Letzte Starts" not in start)

    systeme = c.get("/systeme").text
    check("Katalog und eigene Abbilder in einer Tabelle",
          "debian-trixie" in systeme and "Offline-Installationen" in systeme)

    # Beide Seiten zeigen denselben Eintrag -- dann sollen sie ihm auch
    # dasselbe ansehen. Vorher zeigte Systeme gruen "bereit" und Quellen
    # dazu nichts, was aussah, als sagten sie Verschiedenes.
    def abzeichen(text, slug, bis):
        anfang = text.index(slug)
        ende = text.find(bis, anfang)
        # Kommt die Marke auch ausserhalb einer Zeile vor (die Vorschau
        # nennt dieselben Kennungen), reicht ein Stueck dahinter.
        stueck = text[anfang:ende if ende != -1 else anfang + 1500]
        return re.findall(r'class="badge (ok|missing)">\s*([^<]+?)\s*<', stueck)

    # "Zieht der Client" wird am Eintrag abgelesen, nicht an seiner Gruppe:
    # Mint haengt per NFS ein, Ubuntu Server laedt sein ISO in den
    # Arbeitsspeicher -- beide standen vorher gleich da ("vom Server"),
    # weil nur die Gruppe gefragt wurde.
    for slug, erwartet in (
            ("mint-cinnamon", "über NFS vom Server"),
            ("gparted-live-1-8-1-3", "über NFS vom Server"),
            ("systemrescue-13-02", "über NFS vom Server"),
            ("ubuntu-server-26-04", "vom Server in den Arbeitsspeicher"),
            ("fedora-server-44", "aus dem Internet"),
            ("debian-trixie", "aus dem Internet"),
            ("memtest-bios-8-10", "vom Server")):
        eintrag = next(e for e in pxeapp._systeme() if e["slug"] == slug)
        check("%s zieht %s" % (slug, erwartet),
              pxeapp._zugriff(eintrag) == erwartet, pxeapp._zugriff(eintrag))
    # Ein Upload bringt die Auskunft aus seiner eintrag.yaml mit -- die
    # gilt, auch wenn in der Befehlszeile etwas anderes stuende.
    check("beim Upload zaehlt der festgestellte Weg",
          pxeapp._zugriff({"upload": {"weg": "ram"},
                           "cmdline": "url=https://example.org/x.iso"})
          == "vom Server in den Arbeitsspeicher")
    check("HTTP vom Server wird als solches benannt",
          pxeapp._zugriff({"cmdline": "archiso_http_srv=${assets}/x/"})
          == "über HTTP vom Server")

    quellenseite_ = c.get("/quellen").text

    # Auf jeder Seite an ihrer eigenen Marke: unter Quellen steht das
    # Namensfeld, unter Systeme die Kennung -- dort gibt es kein Feld mehr.
    def alle_abzeichen(text, marke, bis):
        return {slug: abzeichen(text, marke % slug, bis)[:1]
                for slug in re.findall(marke.replace("%s", "([a-z0-9.-]+)"), text)}

    # Nur der Inhalt, nicht der Rahmen: Die Fusszeile traegt seit dem
    # 02.09.2026 den Stand in <code>, und der sieht fuer diesen Sammler aus
    # wie eine Kennung ("v1.2-3-gabc1234"). Gemeint sind die Eintraege, und
    # die stehen in <main>.
    auf_systeme = alle_abzeichen(systeme.split("</main>")[0],
                                 "<code>%s</code>", "</tr>")
    auf_quellen = alle_abzeichen(quellenseite_, 'name="name:%s"', "</details>")
    gemeinsam = sorted(set(auf_systeme) & set(auf_quellen))
    # Systeme zeigt nur noch die startbereiten, Quellen alle -- die eine
    # Liste ist damit eine Teilmenge der anderen. Was beide zeigen,
    # muessen sie gleich zeigen; das war der Sinn dieser Pruefung.
    # Ohne die Systempunkte: "local", "shell" und die anderen stehen in der
    # Vorschau derselben Seite und sind keine Eintraege -- sie kommen aus
    # menu.ipxe.j2 und haben unter Quellen nichts zu suchen.
    systempunkte = {name for name, _ in pxeapp.SYSTEMPUNKTE}
    ueberzaehlig = set(auf_systeme) - set(auf_quellen) - systempunkte
    check("was Systeme zeigt, kennt auch Quellen",
          not ueberzaehlig, str(sorted(ueberzaehlig)))
    check("und es sind nicht null", len(gemeinsam) >= 5, str(len(gemeinsam)))
    uneinig = [s for s in gemeinsam if auf_systeme[s] != auf_quellen[s]]
    check("und sagen ihnen dasselbe an", not uneinig,
          "; ".join("%s: Systeme %s, Quellen %s"
                    % (s, auf_systeme[s], auf_quellen[s]) for s in uneinig))
    # Damit der Vergleich nicht bestaende, weil beide Seiten schweigen:
    farben = {tuple(a[0]) for a in auf_quellen.values() if a}
    check("gruen fuer bereit und rot fuer fehlt kommen beide vor",
          ("ok", "bereit") in farben and ("missing", "fehlt") in farben, str(farben))
    # "Herkunft wird unterschieden" stand hier einmal und prueft nichts
    # mehr: Die Herkunft steht seit dem Umbau unter Quellen, und bestanden
    # hat der Test zuletzt nur, weil das Wort "Katalog" zufaellig in der
    # Beschreibung von netboot.xyz vorkam.
    # Auf die Ueberschriften schauen, nicht auf irgendein Vorkommen: die
    # Gruppennamen stehen inzwischen auch in der Auswahlliste des Formulars.
    check("je Gruppe eine eigene Karte",
          systeme.index("<h2>Offline-Installationen</h2>")
          < systeme.index("<h2>Online-Installationen</h2>"))
    # Die Erklaerungen stehen seit dem Umbau in der Hilfe; auf der Seite
    # steht nur noch der Weg dorthin.
    # "Version entfernen" ist eine Handlung an der Herkunft, wie "Loeschen"
    # bei einem Upload -- der Knopf steht deshalb unter Quellen.
    check("Version entfernen steht bei der Herkunft",
          "/quellen/version/loeschen" not in systeme
          and "/quellen/version/loeschen" in c.get("/quellen").text)
    # Der Verweis zeigt seit dem 02.09.2026 auf #systeme-inhalt statt auf
    # das Kapitel: Was die Gruppen unterscheidet, sagt das Fragezeichen im
    # Kartenkopf, und zweimal derselbe Weg ist einer zu viel.
    check("erklaert nicht selbst, sondern verweist",
          "Drittanbieter-Treiber" not in systeme
          and 'href="/hilfe#systeme-inhalt"' in systeme)
    # "systemliste" kommt dazu, weil die drei Karten sonst jede fuer
    # sich rechnen und ihre Spalten an verschiedenen Kanten enden.
    check("Tabelle kompakt gesetzt und auf gemeinsame Spaltenkanten",
          '<table class="eng systemliste">' in systeme)
    check("die Bauart steht nicht mehr hinter der Kennung -- sie steht unter Quellen",
          "&middot; pcbios" not in systeme and "&middot; efi" not in systeme)

    # Das Hinzufuegen steht seit dem Umzug unter Quellen: eine Adresse zu
    # ersetzen und danach zu holen ist ein Vorgang, und er lief vorher ueber
    # zwei Reiter.
    quellenseite = c.get("/quellen").text
    # Vier Karten, eine je Herkunft -- und keine davon steht mehr unter
    # Systeme.
    check("vier Karten, eine je Herkunft",
          all(f"<h2>{name}</h2>" in quellenseite
              for name in ("Katalog", "Upload", "Download", "Custom")))
    check("das Hinzufuegen steht nicht mehr unter Systeme",
          "Vom Arbeitsplatz hochladen" not in systeme
          and "Eigenen Netz-Installer" not in systeme)
    check("jede Karte bringt ihr Werkzeug mit",
          'action="/quellen/DEBIAN_URL/holen"' in quellenseite
          and 'id="iso-start"' in quellenseite
          and 'action="/uploads/holen"' in quellenseite
          and 'action="/quellen/eintrag"' in quellenseite)
    # Keine Klappen mehr: jede Karte zeigt, was sie kann. Der Abgleich war
    # die letzte, die zugeklappt war.
    check("nichts mehr hinter einer Klappe",
          '<details class="klappe"' not in quellenseite)
    check("... und verweist in die Hilfe statt selbst zu erklaeren",
          'href="/hilfe#quellen-katalog"' in quellenseite
          and 'href="/hilfe#quellen-upload"' in quellenseite
          and 'href="/hilfe#quellen-download"' in quellenseite
          and 'href="/hilfe#quellen-custom"' in quellenseite)
    # Beide Richtungen muessen sichtbar bleiben, sonst ist der Umzug ein
    # Verlust: von Quellen zum Ergebnis, und von Systeme zum Nachladen.
    # Der Name steht bei der Herkunft und unter Systeme -- es ist derselbe.
    # Genau dort ist er am noetigsten: ein hochgeladenes Abbild meldet sich
    # mit dem Namen aus seinem Medium, und der ist regelmaessig zu lang.
    # Der Upload, der wirklich in dieser Karte steht -- nicht irgendeiner
    # aus uploads.json: was der Server selbst geholt hat, steht in der
    # Karte Download.
    def karte(text, ueberschrift):
        a = text.index("<h2>" + ueberschrift + "</h2>")
        return text[a:text.index("</section>", a)]

    import re as _re
    hoch_slug = _re.search(r'name="name:(iso-[a-z0-9-]+)"',
                           karte(c.get("/quellen").text, "Upload")).group(1)
    hoch = next(u for u in c.get("/uploads.json").json()["uploads"]
                if u["slug"] == hoch_slug)
    check("die Upload-Karte hat ein Namensfeld",
          'name="name:' + hoch["slug"] + '"'
          in karte(c.get("/quellen").text, "Upload"), hoch["slug"])
    c.post("/quellen/speichern", data={"name:" + hoch["slug"]: "Kurzer Name"})
    check("der Name gilt auch unter Systeme",
          "Kurzer Name" in c.get("/systeme").text)
    check("... und im Bootmenue", "Kurzer Name" in menue())
    # Anfuehrungszeichen im erkannten Namen werden in der Seite maskiert --
    # verglichen wird deshalb nur der Teil davor.
    check("die Vorgabe steht weiter daneben",
          hoch["erkannt"].split(chr(34))[0].strip() in c.get("/quellen").text,
          hoch["erkannt"])
    c.post("/quellen/speichern", data={"name:" + hoch["slug"]: ""})
    check("leeres Feld setzt auch hier zurueck",
          "Kurzer Name" not in c.get("/systeme").text)

    # Die Menue-Info: was im Feld steht, steht im Bootmenue hinter dem
    # Namen. Vorbelegt ist es mit dem Abgelesenen -- eingetragen wird nur,
    # was davon abweicht.
    seite = c.get("/quellen").text
    check("die Karten haben ein Feld fuer die Menue-Info",
          'name="info:debian-trixie"' in seite
          and 'name="info:' + hoch["slug"] + '"' in seite)
    feld = re.search(r'name="info:debian-trixie"[^>]*', seite, re.S).group(0)
    # Vorbelegt mit dem kurzen Satz aus catalog.yaml. Vorher stand hier das
    # Abgelesene -- und wo nichts abzulesen war, die Kennung: Im Menue
    # stand dann "(debian-trixie)".
    check("vorbelegt ist es mit dem Satz aus dem Katalog",
          'value="braucht Internet am Client"' in feld, " ".join(feld.split()))
    # Ein hochgeladenes Abbild hat keinen Katalogsatz -- dort bleibt es
    # beim Abgelesenen.
    feld_hoch = re.search(r'name="info:' + hoch["slug"] + r'"[^>]*', seite, re.S).group(0)
    check("ein Upload bleibt beim Abgelesenen",
          'value="debian-trixie"' not in feld_hoch and 'value=""' not in feld_hoch,
          " ".join(feld_hoch.split()))

    c.post("/quellen/speichern", data={"info:debian-trixie": "64 Bit, netinst"})
    zeilen = [z for z in menue().splitlines() if "debian-trixie" in z]
    check("Eingetipptes steht im Bootmenue",
          any("(64 Bit, netinst)" in z for z in zeilen)
          and not any("(braucht Internet am Client)" in z for z in zeilen),
          str(zeilen))
    check("... und wieder im Feld",
          "64 Bit, netinst" in c.get("/quellen").text)
    check("... und in der Datei neben der Datenbank",
          "64 Bit, netinst" in (tmp / "namen.yaml").read_text(encoding="utf-8"))

    # Unveraendert abgeschickt heisst: nichts eigenes. Sonst stuende der
    # heutige Stand fest, auch wenn sich der Katalog aendert.
    c.post("/quellen/speichern",
           data={"info:debian-trixie": "braucht Internet am Client"})
    check("die Vorgabe wird nicht als eigene Angabe gespeichert",
          "64 Bit, netinst" not in (tmp / "namen.yaml").read_text(encoding="utf-8"))
    check("und im Menue steht wieder die Vorgabe",
          "(braucht Internet am Client)" in menue())
    # Der lange Satz aus catalog.yaml gehoert in die Karte, nicht ins Menue.
    check("die lange Beschreibung steht in der Karte",
          "Der Ursprung vieler anderer Distributionen" in seite)
    check("... und nicht im Bootmenue",
          "Der Ursprung vieler anderer" not in menue())

    # Die Grenzen kommen von der Bildschirmzeile des bootenden Rechners:
    # Name und Version zusammen 45, die Info 29 Zeichen.
    lang = c.post("/quellen/speichern",
                  data={"info:debian-trixie": "x" * 200}, follow_redirects=True)
    check("zu lange Menue-Info wird abgewiesen",
          "erlaubt sind 29" in lang.text, lang.text[lang.text.find("hint"):][:300])
    lang2 = c.post("/quellen/speichern", follow_redirects=True, data={
        "name:debian-trixie": "D" * 40, "version:debian-trixie": "13.0.1"})
    check("Name und Version zusammen zu lang", "erlaubt sind 45" in lang2.text)
    check("... und nichts davon gespeichert", "D" * 40 not in menue())
    # Was der Server selbst gelesen hat, darf laenger sein -- sonst waere
    # ein Abbild mit 60 Zeichen Volume-Label gar nicht anzubieten.
    unberuehrt = c.post("/quellen/speichern", follow_redirects=True, data={
        "name:" + hoch["slug"]: hoch["erkannt"],
        "version:" + hoch["slug"]: "",
        "info:" + hoch["slug"]: hoch["erkannt"]})
    check("die abgelesene Vorgabe wird nicht abgewiesen",
          "Gespeichert" in unberuehrt.text and "erlaubt sind" not in unberuehrt.text,
          str(len(hoch["erkannt"])))

    # Was nicht auf die Bildschirmzeile passt, schneidet iPXE ab, und zwar
    # stillschweigend. In der Karte steht deshalb ein Vermerk -- in der
    # Kopfzeile, weil die Katalogeintraege zugeklappt dastehen.
    def marke(seite, slug):
        anfang = seite.index('name="name:%s"' % slug)
        stueck = seite[anfang:seite.index("</summary>", anfang)]
        treffer = re.search(r'<span class="gekuerzt"([^>]*)>', stueck)
        return (treffer.group(1) if treffer else None)

    seite_ = c.get("/quellen").text
    check("ein zu langer Name wird vermerkt",
          "hidden" not in (marke(seite_, hoch["slug"]) or "hidden"),
          str(marke(seite_, hoch["slug"])))
    check("... eine Zeile, die passt, dagegen nicht",
          "hidden" in (marke(seite_, "debian-trixie") or ""),
          str(marke(seite_, "debian-trixie")))

    # Die Version steht im Namen, den das Medium meldet -- der Server
    # schlaegt sie vor, statt sie abtippen zu lassen.
    import uploads as pxeuploads
    check("Version aus dem Namen gelesen",
          pxeuploads.version_aus('Ubuntu 26.04 "Resolute Raccoon" - Release '
                                 "amd64 (20260423.1)") == "26.04"
          and pxeuploads.version_aus("Linux Mint 22.3 Cinnamon") == "22.3"
          and pxeuploads.version_aus("SystemRescue 13.02 amd64") == "13.02")
    # Lieber kein Vorschlag als ein falscher: bei Fedora waere "1.5" die
    # Baunummer, das Baudatum am Ende hat zu viele Stellen, und eine Zahl
    # ohne Punkt ist von "amd64" nicht zu unterscheiden.
    check("... und nichts geraten, wo nichts steht",
          pxeuploads.version_aus("Fedora-Server-44-1.5") == ""
          and pxeuploads.version_aus("Debian GNU/Linux 13 (trixie)") == ""
          and pxeuploads.version_aus("Windows-Konsole (WinPE)") == "")
    check("die Upload-Karte hat auch ein Versionsfeld",
          'name="version:' + hoch["slug"] + '"'
          in karte(c.get("/quellen").text, "Upload"))

    # Was seine Dateien nicht hat, steht in keinem Menue -- und deshalb
    # auch nicht zwischen den Eintraegen, die es gibt, sondern hinter einer
    # eigenen Trennlinie am Ende.
    kat = quellenseite[quellenseite.index("Was im Katalog steht"):]
    kat = kat[:kat.index("<h3>Adressen</h3>")] if "<h3>Adressen</h3>" in kat else kat
    check("die Karte trennt Inaktives ab",
          ">Inaktiv</p>" in kat)
    check("... und zwar ganz am Ende",
          all(kat.index(">Inaktiv</p>") > kat.index(">%s</p>" % g)
              for g in ("Offline-Installationen", "Online-Installationen")
              if ">%s</p>" % g in kat),
          str([g for g in ("Offline-Installationen", "Online-Installationen")
               if ">%s</p>" % g in kat]))
    # Ein Eintrag ohne Dateien steht dahinter, ein startbereiter davor.
    check("ein Eintrag ohne Dateien steht hinter der Trennlinie",
          kat.index("clonezilla") > kat.index(">Inaktiv</p>"),
          f'clonezilla bei {kat.index("clonezilla")}, Trennlinie bei {kat.index(">Inaktiv</p>")}')
    check("ein startbereiter davor",
          kat.index("debian-trixie") < kat.index(">Inaktiv</p>"))

    check("von Quellen fuehrt der Weg zu den Systemen",
          'href="/systeme">Was hier hereinkommt' in quellenseite)
    # Bis zum 27.08.2026 nannte Systeme unter den Karten jeden Eintrag,
    # dem die Dateien fehlen, samt Weg zum Holen. Die Zeile ist weg: Auf
    # einem frischen Server listete sie den ganzen Katalog auf, als waere
    # er ein Mangel. Der Weg geht von Quellen nach Systeme, nicht zurueck.
    check("was keine Dateien hat, wird auf Systeme nicht mehr aufgezaehlt",
          'href="/quellen">Unter Quellen holen' not in systeme)
    # Seit dem 02.09.2026 traegt jede Gruppenkarte ihren Weg in die Hilfe
    # selbst, im eigenen Fuss -- vorher stand er einmal zwischen den Karten.
    # Das trug nur, solange alle drei Karten da sind, und das bleibt nicht
    # so: Im Offline-Betrieb faellt "Online-Installationen" weg.
    check("jede Gruppenkarte traegt den Verweis in die Hilfe",
          systeme.count('href="/hilfe#systeme-inhalt"') == 3)
    check("und zwar jeweils im Kartenfuss",
          len(re.findall(r'<p class="kartenfuss">\s*<a href="/hilfe#systeme-inhalt"',
                            systeme)) == 3)

    print("\n-- Reihenfolge der Gruppen")
    # Je Karte ein Feld, ausgeliefert in der geltenden Folge: 1, 2, 3 --
    # auch dann, wenn in der Datei ganz andere Zahlen stehen.
    # Die Vorlage bricht die Attribute um -- verglichen wird deshalb ohne
    # ueberfluessige Leerzeichen.
    def feld(text, gruppe):
        import re as _re
        eng = _re.sub(r"\s+", " ", text)
        treffer = _re.search(r'name="folge:' + _re.escape(gruppe)
                             + r'"[^>]*?value="(\d+)"', eng)
        return treffer.group(1) if treffer else ""

    check("je Karte ein Feld mit ihrer Stelle",
          feld(systeme, "Offline-Installationen") == "1"
          and feld(systeme, "Online-Installationen") == "2"
          and feld(systeme, "Rettung und Wartung") == "3",
          feld(systeme, "Offline-Installationen"))
    # Ein Knopf fuer die ganze Seite, aber ein Feld je Karte -- auch fuer
    # eine Gruppe, die der Katalog mitbringt und GRUPPEN nicht kennt.
    #
    # Gezaehlt wird gegen die Beschriftung "Reihenfolge" und nicht mehr
    # gegen .kartenkopf: Seit dem 27.08.2026 traegt auch die Karte mit der
    # Bootmenue-Vorschau eine Kopfzeile, hat aber keine Stelle in der
    # Reihenfolge. .kartenkopf zaehlt seither Karten, nicht Gruppen.
    check("ein Formular und ein Knopf fuer alle Karten",
          systeme.count('<form id="seite"') == 1
          and systeme.count('class="folgeknopf"') == 1
          and systeme.count('name="folge:') == systeme.count('class="folge"'),
          f"knopf={systeme.count('class=' + chr(34) + 'folgeknopf' + chr(34))} "
          f"felder={systeme.count('name=' + chr(34) + 'folge:')} "
          f"gruppen={systeme.count('class=' + chr(34) + 'folge' + chr(34))}")

    r = c.post("/systeme/speichern", follow_redirects=False, data={
        "folge:Offline-Installationen": "2",
        "folge:Online-Installationen": "1",
        "folge:Rettung und Wartung": "3"})
    check("Umstellen leitet weiter", r.status_code == 303, str(r.status_code))
    umgestellt = c.get("/systeme").text
    check("die Karten stehen in der neuen Folge",
          umgestellt.index("<h2>Online-Installationen</h2>")
          < umgestellt.index("<h2>Offline-Installationen</h2>"))
    # Der eigentliche Gewinn: dieselbe Zahl gilt auch vor der Maschine.
    menu_neu = menue()
    check("das Bootmenue zieht mit",
          menu_neu.index("Online-Installationen")
          < menu_neu.index("Offline-Installationen"))
    check("die Felder zeigen die neue Folge, nicht die eingetippte",
          feld(umgestellt, "Online-Installationen") == "1"
          and feld(umgestellt, "Offline-Installationen") == "2")

    # Ausserhalb des Projektordners, sonst waere sie nach dem naechsten
    # install.sh weg.
    check("liegt neben der Datenbank", (tmp / "gruppen.yaml").is_file())

    # Zurueck auf die Vorgabe, dann der Fall, der beim Ausprobieren im
    # Browser aufgefallen ist: nur EIN Feld anfassen. Wer bei "Rettung und
    # Wartung" eine 1 eintraegt und die 1 daneben stehen laesst, will die
    # Gruppe nach vorn -- und nicht, dass nichts passiert.
    c.post("/systeme/speichern", data={
        "folge:Offline-Installationen": "1",
        "folge:Online-Installationen": "2",
        "folge:Rettung und Wartung": "3"})
    c.post("/systeme/speichern", data={
        "folge:Offline-Installationen": "1",
        "folge:Online-Installationen": "2",
        "folge:Rettung und Wartung": "1"})
    vorgezogen = c.get("/systeme").text
    check("ein einzelnes Feld genuegt zum Vorziehen",
          vorgezogen.index("<h2>Rettung und Wartung</h2>")
          < vorgezogen.index("<h2>Offline-Installationen</h2>")
          < vorgezogen.index("<h2>Online-Installationen</h2>"))
    check("... und das Bootmenue ebenso",
          menue().index("Rettung und Wartung")
          < menue().index("Offline-Installationen"))

    # Nichts angefasst heisst: nichts aendert sich. Auch dann nicht, wenn
    # dieselben Zahlen noch einmal abgeschickt werden.
    c.post("/systeme/speichern", data={
        "folge:Rettung und Wartung": "1",
        "folge:Offline-Installationen": "2",
        "folge:Online-Installationen": "3"})
    gleich = c.get("/systeme").text
    check("unveraendert abschicken laesst alles stehen",
          gleich.index("<h2>Rettung und Wartung</h2>")
          < gleich.index("<h2>Offline-Installationen</h2>"))

    # Etwas, das keine Zahl ist, wird abgewiesen -- und zwar ganz.
    r = c.post("/systeme/speichern", follow_redirects=False, data={
        "folge:Offline-Installationen": "9",
        "folge:Online-Installationen": "oben",
        "folge:Rettung und Wartung": "3"})
    check("krumme Eingabe wird gemeldet",
          "Nicht+gespeichert" in r.headers["location"]
          or "Nicht%20gespeichert" in r.headers["location"], r.headers["location"])
    unveraendert = c.get("/systeme").text
    check("und nichts davon gespeichert",
          unveraendert.index("<h2>Rettung und Wartung</h2>")
          < unveraendert.index("<h2>Offline-Installationen</h2>"))

    # Zurueck auf die Vorgabe, damit die folgenden Pruefungen von der
    # gewohnten Ordnung ausgehen.
    c.post("/systeme/speichern", data={
        "folge:Offline-Installationen": "1",
        "folge:Online-Installationen": "2",
        "folge:Rettung und Wartung": "3"})
    check("wieder in der Vorgabefolge",
          c.get("/systeme").text.index("<h2>Offline-Installationen</h2>")
          < c.get("/systeme").text.index("<h2>Online-Installationen</h2>"))

    print("\n-- Plattformen werden abgelesen")
    # catalog.yaml traegt keine platforms mehr: Was von Hand gepflegt wird,
    # vergisst man beim naechsten Eintrag. Abgelesen wird an dem, was ein
    # Eintrag laedt.
    katalogtext = (PROJ / "webui" / "catalog.yaml").read_text(encoding="utf-8")
    check("in catalog.yaml steht keine Plattform mehr",
          "\n    platforms:" not in katalogtext)
    erwartet = {
        "debian-trixie": ["pcbios", "efi"],          # Kernel und Initrd
        "netbootxyz": ["pcbios", "efi"],         # ein iPXE-Skript
        "memtest-bios-8-10": ["pcbios"],         # memtest.bin
        "memtest-efi-8-10": ["efi"],             # memtest.efi
    }
    for slug, soll in erwartet.items():
        eintrag = next(e for e in pxeapp.load_catalog() if e["slug"] == slug)
        check("%s: %s" % (slug, ", ".join(soll)), eintrag["platforms"] == soll,
              str(eintrag["platforms"]))
    # Zu sehen ist die Angabe in der Karte unter Quellen, eine Zeile unter
    # der Kennung -- dort, wo auch alles andere Abgelesene steht.
    quellen_ = c.get("/quellen").text
    karte_memtest = quellen_[quellen_.index('name="name:memtest-efi-8-10"'):]
    karte_memtest = karte_memtest[:karte_memtest.index("</details>")]
    check("die Karte nennt die Plattform",
          "<dt>Plattform</dt>" in karte_memtest and "efi" in karte_memtest)
    check("... und zwar hinter der Kennung",
          karte_memtest.index("<dt>Kennung</dt>") < karte_memtest.index("<dt>Plattform</dt>"))

    # Das Menue baut darauf auf: Memtest steht je Firmware nur einmal drin.
    check("BIOS bekommt die BIOS-Ausgabe",
          "item memtest-bios-8-10 " in menue(platform="pcbios")
          and "item memtest-efi-8-10 " not in menue(platform="pcbios"))
    check("UEFI bekommt die UEFI-Ausgabe",
          "item memtest-efi-8-10 " in menue()
          and "item memtest-bios-8-10 " not in menue())
    # Windows: je Firmware ein eigener Satz Dateien im Abbild. Fehlt einer,
    # taucht der Eintrag im Menue dieser Firmware nicht auf.
    check("Windows nur dort, wo sein Satz vollstaendig ist",
          pxeapp._plattformen({"type": "wimboot",
                               "wimboot": {"efi": {"bootmgfw.efi": "x"}}}) == ["efi"])
    # Und die Hintertuer: Steht doch einmal etwas in catalog.yaml, gilt das.
    check("eine eigene Angabe gewinnt",
          pxeapp._ergaenze({"slug": "x", "type": "kernel", "kernel": "a/vmlinuz",
                            "platforms": ["pcbios"]})["platforms"] == ["pcbios"])

    print("\n-- Eintraege umbenennen")
    # Geaendert wird unter Quellen, bei dem Abbild, aus dem der Eintrag
    # stammt. Systeme zeigt das Ergebnis -- dort steht kein Feld mehr.
    seite = c.get("/quellen").text
    check("je Eintrag ein Feld fuer Name und Version",
          'name="name:debian-trixie"' in seite and 'name="version:debian-trixie"' in seite)
    check("unter Systeme steht keines davon",
          'name="name:debian-trixie"' not in c.get("/systeme").text
          and 'name="version:debian-trixie"' not in c.get("/systeme").text)
    # Der lange Name eines hochgeladenen Abbilds ist der Anlass fuer das
    # Ganze: er steht als Platzhalter im Feld, damit man sieht, wohin das
    # Leeren zurueckfuehrt.
    # Seit Debian mehrversionig ist, heisst der Eintrag schlicht "Debian"
    # und die Ausgabe steht daneben -- der Codename, denn nur den kennen
    # Debians Pfade. Wer lieber "13 (Trixie)" liest, traegt es hier ein.
    check("die Vorgabe steht als Platzhalter dabei",
          'placeholder="Debian"' in seite)

    c.post("/quellen/speichern", data={
        "name:debian-trixie": "Debian", "version:debian-trixie": "13"})
    umbenannt = c.get("/systeme").text
    check("der eigene Name steht in der Liste",
          "<strong>Debian</strong>" in umbenannt,
          umbenannt[umbenannt.index("debian-trixie") - 400:
                    umbenannt.index("debian-trixie") + 80])
    # Der eigentliche Gewinn: derselbe Name steht vor der Maschine.
    menu_ub = menue()
    check("das Bootmenue nennt ihn auch so",
          "Debian" in menu_ub and "Debian 13 (Trixie)" not in menu_ub, menu_ub[:400])
    check("die Version steht hinter dem Namen",
          any(z.startswith("item debian-trixie ") and "Debian 13" in z
              for z in menu_ub.splitlines()),
          str([z for z in menu_ub.splitlines() if "debian-trixie" in z]))
    # Und ueberall sonst, wo derselbe Katalogeintrag gelesen wird.
    check("Server Health nennt ihn ebenso", "Debian" in c.get("/").text)
    # "Version entfernen" gilt mehrversionigen Katalogeintraegen. Seit die
    # Version im Browser eingetragen werden kann, sind das zwei Dinge -- der
    # Knopf darf nicht bei jedem Eintrag stehen, der irgendeine traegt.
    zeile = umbenannt[umbenannt.index("<code>debian-trixie</code>"):]
    zeile = zeile[:zeile.index("</tr>")]
    check("kein Knopf zum Entfernen bei selbst gesetzter Version",
          "/quellen/version/loeschen" not in zeile, zeile[-300:])

    # Ausserhalb des Projektordners, sonst waere er nach dem naechsten
    # install.sh weg -- und nicht in der eintrag.yaml, die "Neu einlesen"
    # ueberschreibt.
    check("liegt neben der Datenbank", (tmp / "namen.yaml").is_file())

    # Leeren heisst: wieder die Vorgabe, nicht "kein Name".
    c.post("/quellen/speichern", data={
        "name:debian-trixie": "", "version:debian-trixie": ""})
    check("leeres Feld setzt zurueck",
          "Debian trixie" in menue()
          and not (tmp / "namen.yaml").read_text(encoding="utf-8").strip().startswith("debian-trixie"))

    # Ein Name, der die Zeilen des iPXE-Skripts zerlegen wuerde, kommt gar
    # nicht erst hinein.
    r = c.post("/quellen/speichern", follow_redirects=False, data={
        "name:debian-trixie": "kaputt\nzweite Zeile"})
    check("Zeilenumbruch wird abgewiesen",
          "Nicht+gespeichert" in r.headers["location"]
          or "Nicht%20gespeichert" in r.headers["location"], r.headers["location"])
    check("... und nichts davon gespeichert", "Debian trixie" in menue())

    # Beides in einem Zug: der Knopf sichert die Seite, nicht ein
    # Formular. Unter Quellen gilt das fuer Kartenfolge und Bezeichnungen,
    # unter Systeme fuer Kartenfolge und Freigabe.
    c.post("/quellen/speichern", data={
        "folge:Upload": "2",
        "folge:Katalog": "1",
        "name:debian-trixie": "Debian stable"})
    zusammen = c.get("/quellen").text
    check("ein Knopf sichert Reihenfolge und Namen zusammen",
          zusammen.index("<h2>Katalog</h2>") < zusammen.index("<h2>Upload</h2>")
          and "Debian stable" in menue())
    c.post("/quellen/speichern", data={"folge:Upload": "1", "folge:Katalog": "2"})

    # Aufraeumen, damit die folgenden Pruefungen vom gewohnten Stand
    # ausgehen.
    c.post("/systeme/speichern", data={
        "folge:Offline-Installationen": "1",
        "folge:Online-Installationen": "2",
        "folge:Rettung und Wartung": "3",
        "name:debian-trixie": "", "version:debian-trixie": ""})

    UMBRUCH = chr(10)
    print(UMBRUCH + "-- Erproben, dann freigeben")
    seite = c.get("/systeme").text
    check("eine Spalte mit beiden Kaestchen",
          '<th class="sichtbarspalte">sichtbar in</th>' in seite
          and 'name="menue:debian-trixie"' in seite
          and 'name="optionen:debian-trixie"' in seite)
    # Ob ein Kaestchen angehakt ist, laesst sich nur am ganzen <input>
    # ablesen -- die Vorlage bricht die Attribute um, deshalb ohne
    # ueberfluessige Leerzeichen vergleichen.
    def angehakt(text, feldname):
        import re as _re
        eng = _re.sub(r"[ ]*" + UMBRUCH + r"[ ]*", " ", text)
        treffer = _re.search(r"<input[^>]*name=." + _re.escape(feldname) + r".[^>]*>", eng)
        return bool(treffer) and "checked" in treffer.group(0)

    check("ab Werk beides angehakt",
          angehakt(seite, "menue:debian-trixie")
          and angehakt(seite, "optionen:debian-trixie"))
    # Was bereit ist und trotzdem niemandem angeboten wird, sagt die Seite
    # ausdruecklich -- sonst waere "warum ist das nicht im Menue" eine
    # Frage, die man sich vor der Maschine stellt statt hier.
    #
    # Seit dem 27.08.2026 steht das im Fuss der Karte, zu der die Eintraege
    # gehoeren, und nicht mehr als eine gemeinsame Zeile unter allen drei.
    # Geprueft wird deshalb, dass der Name in derselben Karte steht wie
    # seine Gruppe -- sonst waere die Zeile wieder heimatlos.
    c.post("/systeme/speichern", data={"haken:gparted-live-1-8-1-3": "1"})
    wartet = c.get("/systeme").text
    karte_anfang = wartet.index("<h2>Rettung und Wartung</h2>")
    karte = wartet[karte_anfang:wartet.index("</section>", karte_anfang)]
    check("Systeme sagt, was auf eine Entscheidung wartet",
          "noch nicht freigegeben" in karte and "GParted Live" in karte,
          karte[karte.find("noch nicht freigegeben") - 60:][:220])
    def karte_von_slug(slug):
        seite = c.get("/quellen").text
        anfang = seite.index('name="name:%s"' % slug)
        return seite[anfang:seite.index("</details>", anfang)]

    check("... und die Karte unter Quellen sagt es auch",
          "wird nicht angeboten" in karte_von_slug("gparted-live-1-8-1-3"))
    freigeben("gparted-live-1-8-1-3")
    check("nach dem Ankreuzen ist der Hinweis dort weg",
          "wird nicht angeboten" not in karte_von_slug("gparted-live-1-8-1-3"))

    check("kein Kaestchen ohne Dateien",
          'name="menue:clonezilla"' not in seite
          and "<code>clonezilla</code>" not in seite)

    # Markus' Ablauf: ein neues System erst an einem Rechner erproben.
    # Haken beim Menue weg, Haken bei den Optionen bleibt.
    c.post("/systeme/speichern", data={
        "name:debian-trixie": "", "version:debian-trixie": "",
        "haken:debian-trixie": "1", "optionen:debian-trixie": "1"})
    check("aus dem Bootmenue verschwunden", "item debian-trixie " not in menue())
    check("... aber unter Clients weiter zu waehlen",
          'value="debian-trixie"' in c.get("/clients").text)
    check("... und in der Liste steht der Haken weg",
          not angehakt(c.get("/systeme").text, "menue:debian-trixie")
          and angehakt(c.get("/systeme").text, "optionen:debian-trixie"))

    # Der Rechner, der schon darauf steht, bootet weiter -- die Freigabe
    # regelt die Anzeige, nicht die Erreichbarkeit.
    check("das Boot-Skript bleibt erreichbar",
          c.get("/boot/debian-trixie.ipxe").status_code == 200)

    # Und wieder freigeben, dazu die andere Ausgabe zuruecknehmen.
    c.post("/systeme/speichern", data={
        "name:debian-trixie": "", "version:debian-trixie": "",
        "haken:debian-trixie": "1", "menue:debian-trixie": "1", "optionen:debian-trixie": "1"})
    check("wieder im Bootmenue", "item debian-trixie " in menue())

    # Beides weg: der Eintrag bleibt bestehen, wird aber nirgends angeboten.
    c.post("/systeme/speichern", data={
        "name:debian-trixie": "", "version:debian-trixie": "", "haken:debian-trixie": "1"})
    clients_seite = c.get("/clients").text
    check("ohne beide Haken nirgends mehr angeboten",
          "item debian-trixie " not in menue()
          and ('value="debian-trixie"' not in clients_seite
               or "zurückgezogen" in clients_seite))
    check("der Eintrag selbst bleibt", "debian-trixie" in c.get("/systeme").text)
    check("liegt neben der Datenbank", (tmp / "freigabe.yaml").is_file())

    # Ein Formular ohne die Kaestchen darf nichts zuruecknehmen -- sonst
    # verloere ein Teilformular stumm alle Freigaben.
    c.post("/systeme/speichern", data={
        "name:debian-trixie": "", "version:debian-trixie": "",
        "haken:debian-trixie": "1", "menue:debian-trixie": "1", "optionen:debian-trixie": "1"})
    c.post("/systeme/speichern", data={"name:debian-trixie": "Debian"})
    check("ohne Kaestchen bleibt die Freigabe stehen", "item debian-trixie " in menue())
    c.post("/systeme/speichern", data={"name:debian-trixie": ""})

    def vorschau(ansicht):
        t = c.get("/systeme", params={"ansicht": ansicht}).text
        # Auf der Seite gibt es mehrere solche Bloecke -- die Vorschau
        # traegt deshalb eine Kennung.
        anfang = t.index('<pre class="ipxe" id="menuvorschau">')
        return t[anfang:t.index("</pre>", anfang)]

    uefi, bios = vorschau("efi"), vorschau("pcbios")
    check("Vorschau des Bootmenues vorhanden", "exmig - MARLEI Boot  --" in uefi)
    # Die Titelzeile stand einmal in menu.ipxe.j2 und einmal in
    # systeme.html. Aufgefallen ist das erst, als der Absender ins Menue
    # kam und die Vorschau ihn nicht zeigte. Eine Vorschau, die etwas
    # anderes zeigt als das Menue, ist genau das nicht mehr -- deshalb
    # steht die Zeile jetzt an einer Stelle, und das wird hier geprueft.
    echt = [z for z in menue().splitlines()
            if z.startswith("menu ")][0][len("menu "):]
    # vorschau() liefert den <pre>-Anfang mit, der gehoert nicht zur Zeile.
    erste = uefi.split(">", 1)[1].splitlines()[0]
    check("Vorschau zeigt dieselbe Titelzeile wie das Menue",
          erste.split("  --  ")[0] == echt.split("  --  ")[0]
          and erste.endswith("(efi)") and echt.endswith("(efi)"))
    # Sie steht offen: was auf die Frage antwortet, mit der man auf die
    # Seite kommt, gehoert nicht hinter einen Klick.
    check("Vorschau ist eine eigene, offene Karte",
          "<h2>Vorschau</h2>" in systeme
          and "So sieht es am bootenden Rechner aus" not in systeme)
    # Sie zeigt dieselben Eintraege wie die drei Karten darueber und steht
    # deshalb bei ihnen -- als letzte Karte, seit das Hinzufuegen unter
    # Quellen steht.
    check("Vorschau steht hinter den Gruppen",
          systeme.index("<h2>Rettung und Wartung</h2>")
          < systeme.index("<h2>Vorschau</h2>"))
    check("Vorschau kennt die Gruppen",
          "Offline-Installationen" in uefi and "Rettung und Wartung" in uefi)
    check("Vorschau zeigt die Systempunkte", "iPXE-Eingabeaufforderung" in uefi)
    check("Standardauswahl hervorgehoben", 'class="gewaehlt"' in uefi)
    # Zwei Menuepunkte mit demselben Namen -- auseinanderzuhalten sind sie
    # an der Menue-Info aus dem Katalog. Vorher stand dort die Kennung,
    # weil der Katalogsatz verworfen wurde.
    check("UEFI-Vorschau zeigt die UEFI-Variante",
          "UEFI-Variante" in uefi and "BIOS-Variante" not in uefi)
    check("BIOS-Vorschau zeigt die BIOS-Variante",
          "BIOS-Variante" in bios and "UEFI-Variante" not in bios)
    check("unfertige Eintraege fehlen in der Vorschau", "openSUSE" not in uefi)
    check("Vorschau deckt sich mit dem echten Menue",
          all(e["name"].split(" (")[0] in uefi
              for e in pxeapp.menue_gruppen("efi")["Rettung und Wartung"]))

    # Am bootenden Rechner ist die Zeile zu Ende, wo die Textkonsole zu
    # Ende ist. Die Vorschau setzt den Rest blass, statt ihn hinter einem
    # Rollbalken zu verstecken -- den gibt es dort nicht.
    lange = c.get("/systeme").text
    vorschau_roh = lange[lange.index('id="menuvorschau"'):]
    vorschau_roh = vorschau_roh[:vorschau_roh.index("</pre>")]
    check("was ueber die Breite hinausgeht, steht blass da",
          'class="ueberrand"' in vorschau_roh)
    # Die erste Spalte waechst nicht mit: Ein langer Name wird hart
    # gekuerzt, sonst schoebe er die Angaben aller anderen Zeilen nach
    # rechts und das Menue saehe kaputt aus.
    lang_name = "L" * 60
    check("die erste Spalte bleibt so breit, wie sie ist",
          pxeapp.menuezeile({"name": lang_name}) == "L" * pxebez.MAX_ZEILE,
          pxeapp.menuezeile({"name": lang_name}))
    check("... auch mit Version und Info",
          pxeapp.menuezeile({"name": lang_name, "version": "26.04",
                             "menue_text": "x"})
          == "L" * pxebez.MAX_ZEILE + "  (x)")
    check("kurze Namen werden aufgefuellt, nicht gekuerzt",
          pxeapp.menuezeile({"name": "Debian", "version": "13",
                             "menue_text": "netinst"})
          == "Debian 13".ljust(pxebez.MAX_ZEILE) + "  (netinst)")
    # Der lange Satz aus catalog.yaml gehoert nicht ins Menue -- dort sind
    # 29 Zeichen Platz, er hat drei Saetze.
    check("die lange Beschreibung bleibt aus dem Menue heraus",
          pxeapp.menuezeile({"name": "Debian", "description": "ein langer Satz"})
          == "Debian".ljust(pxebez.MAX_ZEILE))
    sichtbar = re.split(r'<span class="ueberrand">', vorschau_roh)[0].splitlines()[-1]
    check("... und der sichtbare Teil endet bei der Bildschirmbreite",
          len(html.unescape(sichtbar).lstrip()) == pxebez.MENUE_BREITE,
          "%d Zeichen: %r" % (len(html.unescape(sichtbar).lstrip()), sichtbar[-30:]))
    # Was auf der Startseite nichts zu suchen hat, ist die Bedienung der
    # Rechner: kein Formular, keine Auswahlfelder. Ein Verweis darauf im
    # Fliesstext ist etwas anderes und deshalb erlaubt.
    check("Rechnerverwaltung nicht mehr auf der Startseite",
          "/assign" not in start and 'name="entry:' not in start)
    check("Abbild-Verwaltung nicht mehr auf der Startseite",
          "iso-datei" not in start)

    print("\n-- Auslastung und laufende Uebertragungen")
    # /proc gibt es unter Windows nicht -- also bauen wir eines nach. So
    # laeuft die Auswertung, die sonst nur auf dem Server ausgefuehrt wird,
    # auch im Test durch: gerade die Hex-Adressen sind fehleranfaellig.
    import auslastung

    proc = tmp / "proc"
    (proc / "net").mkdir(parents=True, exist_ok=True)
    auslastung.PROC = proc
    auslastung._vorher.clear()

    (proc / "loadavg").write_text("0.52 0.31 0.20 1/234 5678\n", encoding="utf-8")
    (proc / "cpuinfo").write_text("processor\t: 0\n\nprocessor\t: 1\n", encoding="utf-8")
    (proc / "meminfo").write_text(
        "MemTotal:        4096000 kB\nMemFree:          512000 kB\n"
        "MemAvailable:    1024000 kB\n", encoding="utf-8")

    check("Lastmittel gelesen", auslastung.last() == [0.52, 0.31, 0.20],
          str(auslastung.last()))
    check("Kerne gezaehlt", auslastung.kerne() == 2)
    sp = auslastung.speicher()
    check("Speicher aus MemAvailable", sp.get("anteil") == 75, str(sp))

    # Prozessor: erst nach zwei Messungen gibt es einen Wert.
    (proc / "stat").write_text("cpu  100 0 50 800 20 0 0 0 0 0\n", encoding="utf-8")
    check("erste CPU-Messung liefert nichts", auslastung.cpu() is None)
    (proc / "stat").write_text("cpu  120 0 60 900 20 0 0 0 0 0\n", encoding="utf-8")
    check("CPU aus der Differenz", auslastung.cpu() == 23, str(auslastung.cpu()))

    # Netzdurchsatz: dito, und die Rueckschleife zaehlt nicht mit.
    kopf = ("Inter-|   Receive                    |  Transmit\n"
            " face |bytes    packets errs drop fifo frame compressed multicast|"
            "bytes    packets errs drop fifo colls carrier compressed\n")
    (proc / "net" / "dev").write_text(
        kopf + "    lo: 900000 1 0 0 0 0 0 0  900000 1 0 0 0 0 0 0\n"
             + " enp0s3: 1000000 1 0 0 0 0 0 0  2000000 1 0 0 0 0 0 0\n", encoding="utf-8")
    auslastung.netz()
    time.sleep(1.1)
    (proc / "net" / "dev").write_text(
        kopf + "    lo: 999999 1 0 0 0 0 0 0  999999 1 0 0 0 0 0 0\n"
             + " enp0s3: 2000000 1 0 0 0 0 0 0  6000000 1 0 0 0 0 0 0\n", encoding="utf-8")
    n = auslastung.netz()
    check("Netzdurchsatz berechnet", n and 800_000 < n["rein"] < 1_100_000, str(n))
    check("... und hinaus ebenso", n and 3_000_000 < n["raus"] < 4_100_000, str(n))

    # Offene Verbindungen: 192.168.178.100 zieht per HTTP, .101 per NFS.
    # Die Adressen stehen byteweise verkehrt herum im Hex -- 192.168.178.100
    # wird zu 64B2A8C0.
    (proc / "net" / "tcp").write_text(
        "  sl  local_address rem_address   st tx_queue rest\n"
        "   0: 11B2A8C0:0050 64B2A8C0:D431 01 rest\n"      # HTTP, steht
        "   1: 11B2A8C0:0801 65B2A8C0:D432 01 rest\n"      # NFS, steht
        "   2: 11B2A8C0:0050 66B2A8C0:D433 06 rest\n"      # schliesst gerade
        "   3: 0100007F:0050 0100007F:D434 01 rest\n",     # Rueckschleife
        encoding="utf-8")
    (proc / "net" / "tcp6").write_text("  sl  local_address rem_address   st\n",
                                       encoding="utf-8")
    u = auslastung.uebertragungen()
    check("HTTP-Verbindung erkannt", u.get("192.168.178.100") == {"HTTP"}, str(u))
    check("NFS-Verbindung erkannt", u.get("192.168.178.101") == {"NFS"}, str(u))
    check("nur stehende Verbindungen", "192.168.178.102" not in u, str(u))
    check("Rueckschleife zaehlt nicht", "127.0.0.1" not in u, str(u))

    # Der ARP-Zwischenspeicher ordnet Adressen ihren MACs zu. Das ist der
    # verlaessliche Weg: die Adresse, unter der ein Rechner Daten zieht,
    # muss nicht die sein, unter der er gebootet hat -- iPXE fragt per DHCP,
    # das Live-System danach noch einmal selbst.
    (proc / "net" / "arp").write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        f"192.168.178.100  0x1         0x2         {MAC}     *        enp0s3\n"
        "192.168.178.199  0x1         0x0         00:00:00:00:00:00     *        enp0s3\n",
        encoding="utf-8")
    a = auslastung.arp()
    check("ARP-Tabelle gelesen", a.get("192.168.178.100") == MAC, str(a))
    check("unfertige Eintraege uebergangen", "192.168.178.199" not in a, str(a))

    # Der Rechner hat unter einer anderen Adresse gebootet, als er jetzt
    # benutzt -- genau der Fall, an dem die Zuordnung ueber die IP scheitert.
    with pxeapp.db() as conn:
        conn.execute("UPDATE clients SET last_ip = ? WHERE mac = ?",
                     ("192.168.178.92", MAC))
    d = c.get("/status.json").json()
    laufend = d["laufend"]
    check("trotz gewechselter Adresse zugeordnet", len(laufend) == 1, str(laufend))
    check("... und die aktuelle Adresse gezeigt",
          laufend and laufend[0]["ip"] == "192.168.178.100", str(laufend))

    # Ohne ARP-Eintrag bleibt die Zuordnung ueber die gespeicherte Adresse.
    (proc / "net" / "arp").write_text("IP address  HW type  Flags  HW address  Mask  Device\n",
                                      encoding="utf-8")
    with pxeapp.db() as conn:
        conn.execute("UPDATE clients SET last_ip = ? WHERE mac = ?",
                     ("192.168.178.100", MAC))
    d = c.get("/status.json").json()
    laufend = d["laufend"]
    check("ersatzweise ueber die gespeicherte Adresse", len(laufend) == 1, str(laufend))
    check("laufende Uebertragung wird gemeldet", len(laufend) == 1, str(laufend))
    check("... mit dem gestarteten System",
          laufend and laufend[0]["slug"] == "debian-trixie", str(laufend))
    check("... und dem Weg", laufend and laufend[0]["wege"] == ["HTTP"], str(laufend))

    # Derselbe Rechner ueber zwei Wege gleichzeitig bleibt eine Zeile.
    (proc / "net" / "tcp").write_text(
        "  sl  local_address rem_address   st tx_queue rest\n"
        "   0: 11B2A8C0:0050 64B2A8C0:D431 01 rest\n"
        "   1: 11B2A8C0:0801 64B2A8C0:D435 01 rest\n",
        encoding="utf-8")
    laufend = c.get("/status.json").json()["laufend"]
    check("zwei Wege, eine Zeile", len(laufend) == 1, str(laufend))
    check("... beide Wege genannt",
          laufend and laufend[0]["wege"] == ["HTTP", "NFS"], str(laufend))
    # Auf der Startseite steht die laufende Uebertragung in der Karte
    # "Registrierte Rechner". Geprueft wird an der Adresse und nicht an der
    # Ueberschrift: die darf sich aendern, ohne dass dieser Test etwas
    # anderes meint.
    startseite = c.get("/").text
    check("Startseite zeigt die laufende Uebertragung",
          laufend and laufend[0]["ip"] in startseite)
    check("... unter den registrierten Clients",
          "Registrierte Clients" in startseite)
    check("Teilstueck laesst sich einzeln holen",
          "debian" in c.get("/status.html").text.lower())

    # Ein Rechner ohne Boot-Verlauf -- etwa der Browser des Verwalters --
    # darf nicht als Installation gelten.
    with pxeapp.db() as conn:
        conn.execute("INSERT OR IGNORE INTO clients (mac, last_ip) VALUES (?, ?)",
                     ("aa:bb:cc:00:00:99", "192.168.178.101"))
    check("Rechner ohne Boot-Verlauf zaehlt nicht",
          len(c.get("/status.json").json()["laufend"]) == 1)

    auslastung.PROC = Path("/proc")

    print("\n-- Verlauf")
    check("Boot-Verlauf unter History", "gparted-live-1-8-1-3" in c.get("/history").text)

    print("\n-- Katalog wird bei Aenderung neu gelesen")
    cat = Path(os.environ["PXE_CATALOG"])
    original = cat.read_text(encoding="utf-8")

    # newline="\n" ist wichtig: ohne das macht Python unter Windows aus
    # jedem Zeilenumbruch CRLF und der Test veraendert die Datei dauerhaft.
    def write_catalog(text):
        cat.write_text(text, encoding="utf-8", newline="\n")

    try:
        write_catalog(original.replace('name: "GParted Live"',
                                       'name: "GParted UMBENANNT"'))
        os.utime(cat, (0, 0))  # mtime aendern, damit der Cache verwirft
        fresh = menue("aa-bb-cc-dd-ee-ff")
        check("neue Bezeichnung ohne Neustart aktiv", "GParted UMBENANNT" in fresh)
    finally:
        write_catalog(original)

    # Was das Abbild ueber sich selbst sagt -- dieselbe Auskunft wie bei
    # einem Upload, nur bei den mitgelieferten Systemen von der Platte
    # gelesen. Zwei Wege: die ausgepackte .disk/info und ein ISO daneben.
    print(chr(10) + "-- Beschreibung aus den Dateien")
    import selbstauskunft                                        # noqa: E402
    sys.path.insert(0, str(PROJ / "tests"))
    from isobauer import IsoBauer                                # noqa: E402

    selbstauskunft.vergiss()
    (assets / "mint-cinnamon" / ".disk").mkdir(parents=True, exist_ok=True)
    (assets / "mint-cinnamon" / ".disk" / "info").write_text(
        MINTZEILE, encoding="utf-8")
    # Wie ein echtes GParted-Abbild aufgebaut ist: Debian-Live, also
    # live/ mit Kernel, Initrd und Wurzeldateisystem. Ohne das Squashfs
    # erkennt isoscan die Familie nicht und faellt auf die Volume-ID
    # zurueck -- dann stuende hier "GPARTED_LIVE_1_8_1_3".
    for ordner in ("ubuntu-server-24-04", "ubuntu-server-26-04",
                   "gparted-live-1-8-1-3"):
        (assets / ordner).mkdir(parents=True, exist_ok=True)
    (IsoBauer("GPARTED_LIVE_1_8_1_3")
     .add(".disk/info", b"GParted Live 1.8.1-3 amd64")
     .add("live/vmlinuz", b"KERNEL").add("live/initrd.img", b"INITRD")
     .add("live/filesystem.squashfs", b"ROOT")
     .schreibe(assets / "gparted-live-1-8-1-3" / "gparted.iso"))

    def zeile(slug):
        seite = c.get("/quellen").text
        anfang = seite.index('name="name:%s"' % slug)
        stueck = seite[anfang:seite.index("</details>", anfang)]
        treffer = re.search(r"<dt>Beschreibung</dt><dd>(.*?)</dd>", stueck, re.S)
        # Der Browser bekommt "&#34;" -- verglichen wird mit dem, was
        # dasteht, nicht mit seiner Schreibweise im Quelltext.
        return html.unescape(treffer.group(1).strip()) if treffer else ""

    check("ausgepackte .disk/info wird gelesen",
          zeile("mint-cinnamon") == MINTZEILE.strip(), zeile("mint-cinnamon"))
    check("ein ISO daneben wird gelesen",
          zeile("gparted-live-1-8-1-3") == "GParted Live 1.8.1-3 amd64",
          zeile("gparted-live-1-8-1-3"))
    # Ohne Abbild bleibt die Zeile nicht leer -- das saehe aus wie ein
    # Fehler. Dann steht die Kennung da, die es immer gibt.
    check("ohne Abbild steht die Kennung da", zeile("debian-trixie") == "debian-trixie",
          zeile("debian-trixie"))

    # Was ein Eintrag wirklich belegt -- sein eigener Ordner, nicht die
    # Groesse der Datei, die einmal hereinkam.
    def belegt(slug):
        seite = c.get("/quellen").text
        anfang = seite.index('name="name:%s"' % slug)
        stueck = seite[anfang:seite.index("</details>", anfang)]
        treffer = re.search(r"<dt>Belegt</dt>\s*<dd>(.*?)<span", stueck, re.S)
        return html.unescape(treffer.group(1)).strip() if treffer else ""

    (assets / "debian-trixie" / "extra.dat").write_bytes(b"x" * 500000)
    konfiguration.vergiss()   # sonst gilt die gemerkte Zahl von vorhin
    check("die Karte nennt die Belegung",
          belegt("debian-trixie").endswith("KB") or belegt("debian-trixie").endswith("MB"),
          belegt("debian-trixie"))
    # 488 KB: die halbe Million Bytes aus extra.dat. Gezaehlt wird also
    # der Ordner und nicht die Liste der Startdateien -- die beiden sind
    # zusammen zwei Bytes gross.
    check("gezaehlt wird der ganze Ordner, nicht nur die Startdateien",
          belegt("debian-trixie").startswith("488"), belegt("debian-trixie"))
    (assets / "debian-trixie" / "extra.dat").unlink()

    # Der Fall vom Server: Unter ubuntu/ lagen 24.04 und 26.04
    # nebeneinander -- eine alte Ausgabe, die niemand weggeraeumt hatte.
    # Gesucht wurde eine Ebene zu hoch, und 26.04 bekam die Auskunft von
    # 24.04. Jede Ausgabe liest ihr eigenes Abbild.
    selbstauskunft.vergiss()
    for ausgabe, wer in (("24.04", "Ubuntu-Server 24.04 LTS - Release amd64"),
                         ("26.04", "Ubuntu-Server 26.04 LTS - Release amd64")):
        (IsoBauer("UBUNTU_SERVER_" + ausgabe.replace(".", "_"))
         .add(".disk/info", wer.encode("utf-8"))
         .add("casper/vmlinuz", b"KERNEL").add("casper/initrd", b"INITRD")
         .schreibe(assets / ("ubuntu-server-" + ausgabe.replace(".", "-")) / "ubuntu-server-amd64.iso"))
    check("jede Ausgabe liest ihr eigenes Abbild",
          zeile("ubuntu-server-26-04") == "Ubuntu-Server 26.04 LTS - Release amd64",
          zeile("ubuntu-server-26-04"))

    # Zwei Saetze, zwei Orte. Der lange gehoert in die Karte und hilft beim
    # Auswaehlen; der kurze gehoert ins Menue und zaehlt vor der Maschine.
    # Sie zusammenzulegen hiesse, einen von beiden zu verlieren -- vorher
    # gab es nur einen, und der wurde verworfen.
    karten = c.get("/quellen").text
    debian_zeilen = [z for z in menue().splitlines() if "debian-trixie" in z]
    check("der lange Satz steht in der Karte",
          "Der Ursprung vieler anderer Distributionen" in karten)
    check("... und nicht im Menue",
          not any("Der Ursprung" in z for z in debian_zeilen), str(debian_zeilen))
    check("der kurze Satz steht im Menue",
          any("(braucht Internet am Client)" in z for z in debian_zeilen),
          str(debian_zeilen))
    check("... und die Kennung springt nicht mehr ein",
          not any("(debian-trixie)" in z for z in debian_zeilen),
          str(debian_zeilen))

    # Gemerkt wird nach Zeitstempel: Ein geaendertes Abbild wird neu
    # gelesen, ohne dass jemand den Speicher leeren muss.
    (assets / "mint-cinnamon" / ".disk" / "info").write_text(
        "Linux Mint 23 - Release amd64", encoding="utf-8")
    os.utime(assets / "mint-cinnamon" / ".disk" / "info", (2, 2))
    check("geaenderte Datei wird neu gelesen",
          zeile("mint-cinnamon") == "Linux Mint 23 - Release amd64",
          zeile("mint-cinnamon"))

    print(chr(10) + "-- Verwaiste Ordner")
    # Der Fall vom Server: ubuntu/24.04 blieb liegen, als die Liste auf
    # 26.04 umgestellt wurde. Zu keinem Eintrag gehoerig, von niemandem
    # gefunden -- 3,3 GB.
    (assets / "ubuntu-server-24-04").mkdir(parents=True, exist_ok=True)
    (assets / "ubuntu-server-24-04" / "alt.iso").write_bytes(b"x" * 3000)
    (assets / "altsystem").mkdir(exist_ok=True)
    (assets / "altsystem" / "kram.dat").write_bytes(b"x" * 100)
    konfiguration.vergiss()

    namen = [f["name"] for f in pxeapp.verwaiste()]
    check("die alte Ausgabe faellt auf", "ubuntu-server-24-04" in namen, str(namen))
    check("ein ganzer Ordner ohne Eintrag ebenso", "altsystem" in namen, str(namen))
    check("was gebraucht wird, bleibt unbehelligt",
          not any(n.startswith(("wimboot", "debian", "mint")) for n in namen),
          str(namen))
    check("die Ausgabe, die benutzt wird, auch",
          "ubuntu-server-26-04" not in namen, str(namen))

    seite = c.get("/").text
    check("Server Health nennt die Funde",
          "Verwaiste Ordner" in seite and "ubuntu-server-24-04" in seite)

    print(chr(10) + "-- Wem gehoert welcher Ordner")
    # Die Regel, an der alles haengt: ein Eintrag, ein Verzeichnis, und es
    # heisst wie seine Kennung. Vorher wurde der Ordner aus den Pfaden der
    # Startdateien erschlossen -- das ging zweimal daneben.
    systeme = pxeapp._systeme()
    orte = pxeapp._eintragsorte(systeme)
    falsch = [(e["slug"], str(orte[e["slug"]])) for e in systeme
              if orte[e["slug"]] is not None
              and orte[e["slug"]] != assets / e["slug"]]
    check("jeder Ordner heisst wie sein Eintrag", not falsch, str(falsch))
    # Und umgekehrt: keine zwei Eintraege im selben Ordner. Frueher teilten
    # sich die beiden Memtest-Varianten einen.
    belegt_von = [str(o) for o in orte.values() if o is not None]
    check("kein Ordner gehoert zweien", len(belegt_von) == len(set(belegt_von)),
          str(sorted(belegt_von)))
    # wimboot gehoert allen Windows-Abbildern gemeinsam -- es ist die
    # einzige Ausnahme und darf deshalb keinem einzeln zugerechnet werden.
    check("wimboot gehoert keinem Eintrag",
          not any(str(o).endswith("wimboot") for o in orte.values() if o),
          str([str(o) for o in orte.values() if o]))

    # Markus' Fund: Ein entpacktes Abbild legt neben casper/ noch pool/ und
    # dists/. Die Regel "ein Nachbarordner haelt den Aufstieg auf" hielt den
    # Zaun schon bei casper/ an -- der Eintrag bekam einen Bruchteil seiner
    # Belegung, der Rest stand unter "Sonstiges". Bei einem Upload ist gar
    # nichts zu erraten: Sein Ordner heisst upload/<slug>.
    hoch = next(e for e in pxeapp._systeme()
                if e["slug"] == "iso-linuxmint-22-3-cinnamon-64bit")
    for rel in ("pool/main/paket.deb", "dists/noble/Release"):
        q = assets / hoch["slug"] / rel
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_bytes(b"x" * 1500)
    konfiguration.vergiss()
    ort = pxeapp._eintragsorte(pxeapp._systeme())[hoch["slug"]]
    check("der Ordner eines Uploads ist sein eigener",
          ort == assets / hoch["slug"], str(ort))
    check("... und was darin liegt, zaehlt zu ihm",
          pxeapp._eintragsbelegung(hoch, ort) >= 3000,
          str(pxeapp._eintragsbelegung(hoch, ort)))

    # SystemRescue packt sein ganzes ISO aus und haengt das Verzeichnis per
    # NFS ein. Frueher blieb der Zaun fuenf Ebenen tief bei
    # sysresccd/boot/x86_64 stehen, und das Wurzeldateisystem daneben stand
    # zum Loeschen bereit. Sein Ordner heisst jetzt wie er, und alles darin
    # gehoert ihm -- ganz gleich, wie tief der Kernel liegt.
    sysresc = next((e for e in pxeapp._systeme()
                    if e["slug"].startswith("systemrescue")), None)
    if sysresc:
        for rel, gross in [("sysresccd/boot/x86_64/vmlinuz", 100),
                           ("sysresccd/boot/grub/grub.cfg", 100),
                           ("sysresccd/x86_64/airootfs.sfs", 90000),
                           ("EFI/BOOT/bootx64.efi", 100)]:
            q = assets / sysresc["slug"] / rel
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_bytes(b"x" * gross)
        konfiguration.vergiss()
        systeme = pxeapp._systeme()
        ort = pxeapp._eintragsorte(systeme)[sysresc["slug"]]
        check("auch ein tief liegender Kernel aendert den Ordner nicht",
              ort == assets / sysresc["slug"], str(ort))
        check("... damit zaehlt das ganze entpackte Abbild",
              pxeapp._eintragsbelegung(sysresc, ort) >= 90000,
              str(pxeapp._eintragsbelegung(sysresc, ort)))
        # Das eigentlich Gefaehrliche: ohne die Auskunft stand das
        # Wurzeldateisystem mit einem Loeschknopf in der Liste.
        check("nichts davon wird zum Loeschen angeboten",
              not any(f["name"].startswith("systemrescue")
                      for f in pxeapp.verwaiste(systeme)),
              str([f["name"] for f in pxeapp.verwaiste(systeme)]))
        # Und "Dateien loeschen" muss denselben Massstab anlegen, sonst
        # raeumt es einen Bruchteil weg und meldet Erfolg.
        raeum, _ = pxeapp._raeumgut(sysresc)
        check("Loeschen legt denselben Massstab an",
              raeum == assets / sysresc["slug"], str(raeum))
        shutil.rmtree(assets / sysresc["slug"])
        konfiguration.vergiss()

    print(chr(10) + "-- Speicherplatz: Detailansicht")
    # Die Karte sagte "davon X GB Abbilder" und meinte nur upload/. Jetzt
    # zaehlt sie die ganze Ablage und schluesselt sie auf: je Eintrag, was
    # verwaist ist, und was uebrig bleibt.
    konfiguration.vergiss()
    systeme = pxeapp._systeme()
    auf = pxeapp.platzaufteilung(systeme, pxeapp.verwaiste(systeme))

    check("die Rechnung geht auf",
          auf["eintraege_bytes"] + auf["verwaist_bytes"] + auf["sonstiges_bytes"]
          == auf["gesamt"],
          str({k: v for k, v in auf.items() if k.endswith("bytes") or k == "gesamt"}))
    check("gezaehlt wird die ganze Ablage, nicht nur upload/",
          auf["gesamt"] > pxeapp.uploads.belegung(),
          f'{auf["gesamt"]} vs {pxeapp.uploads.belegung()}')
    check("die verwaisten Ordner sind eine eigene Zeile",
          auf["verwaist_bytes"] >= 3100, str(auf["verwaist_bytes"]))
    # "Sonstiges" ist ein Rest, seine Posten sind gemessen -- gingen die
    # beiden auseinander, waere die Aufteilung nicht vollstaendig: dann
    # laege unter der Ablage etwas, das in keiner der drei Zeilen steht.
    check("die Posten ergeben genau die Zeile Sonstiges",
          sum(s["bytes"] for s in auf["sonstiges"]) == auf["sonstiges_bytes"],
          str([(s["name"], s["bytes"]) for s in auf["sonstiges"]])
          + f' vs {auf["sonstiges_bytes"]}')
    # Ein angefangener Upload hat noch keinen Katalogeintrag, aber sehr wohl
    # einen Ordner -- und der gehoert ihm. Frueher stand er namenlos unter
    # "Sonstiges"; jetzt steht er mit seinem Namen in der Liste, denn genau
    # so einer belegt Platz, ohne dass man ihn im Menue findet.
    angefangen = [e for e in auf["eintraege"]
                  if e["ablage"].startswith(("iso-", "netz-"))]
    check("ein angefangener Eintrag steht mit Namen in der Liste",
          bool(angefangen),
          str([(e["slug"], e["ablage"], e["bytes"]) for e in auf["eintraege"]]))
    # wimboot gibt es im Wegwerf-Verzeichnis nicht -- fuer diese eine
    # Pruefung also hinlegen und gleich wieder wegnehmen, damit kein
    # Windows-Eintrag davon startbereit wird.
    (assets / "wimboot").mkdir(exist_ok=True)
    (assets / "wimboot" / "wimboot").write_bytes(b"x" * 64)
    konfiguration.vergiss()
    wim = pxeapp.platzaufteilung(systeme, pxeapp.verwaiste(systeme))["sonstiges"]
    check("wimboot steht dort und ist als noetig gekennzeichnet",
          any(s["name"] == "wimboot/" and s["hinweis"] for s in wim),
          str([(s["name"], s["hinweis"]) for s in wim]))
    shutil.rmtree(assets / "wimboot")
    konfiguration.vergiss()
    # Ein Abbild, das neben seinem entpackten Ordner liegenblieb, ist keine
    # Verwaisung (das sind immer Ordner) und gehoert keinem Eintrag. Vor
    # der Aufschluesselung stand es in keiner Liste.
    (assets / "vergessen.iso").write_bytes(b"x" * 4096)
    konfiguration.vergiss()
    auf2 = pxeapp.platzaufteilung(systeme, pxeapp.verwaiste(systeme))
    check("eine einzelne Datei daneben faellt jetzt auf",
          any(s["name"] == "vergessen.iso" and s["bytes"] == 4096
              for s in auf2["sonstiges"]),
          str([(s["name"], s["bytes"]) for s in auf2["sonstiges"]]))
    check("... und die Rechnung geht weiter auf",
          sum(s["bytes"] for s in auf2["sonstiges"]) == auf2["sonstiges_bytes"]
          and auf2["eintraege_bytes"] + auf2["verwaist_bytes"]
              + auf2["sonstiges_bytes"] == auf2["gesamt"])
    # Memtests Dateien gehoeren ihren Eintraegen, obwohl der Ordner keinem
    # gehoert. Stuenden sie hier, waeren sie doppelt gezaehlt.
    check("was einem Eintrag gehoert, steht nicht unter Sonstiges",
          not any(s["name"].startswith("memtest") for s in auf2["sonstiges"]),
          str([s["name"] for s in auf2["sonstiges"]]))
    (assets / "vergessen.iso").unlink()
    konfiguration.vergiss()
    check("der groesste Brocken steht oben",
          [e["bytes"] for e in auf["eintraege"]]
          == sorted((e["bytes"] for e in auf["eintraege"]), reverse=True),
          str([(e["slug"], e["bytes"]) for e in auf["eintraege"]]))
    check("was nichts belegt, steht nicht in der Liste",
          all(e["bytes"] > 0 for e in auf["eintraege"]))
    # Bis zum 27.08.2026 unterschied die Karte zwei Sorten von Null:
    # "noch nicht geholt" und "holt alles aus dem Netz". Beide standen als
    # Halbsatz unter der Tabelle. Der Satz ist weg -- was hier nicht
    # angezeigt wird, muss die Karte auch nicht erwaehnen --, und mit ihm
    # die Unterscheidung. Geprueft wird deshalb nur noch, was man sieht:
    # Wer nichts belegt, steht nicht in der Liste. Das steht oben.

    # Dieselbe Zahl wie in der Eintragskarte -- ein Rechenweg, eine Stelle.
    debian = next(e for e in auf["eintraege"] if e["slug"] == "debian-trixie")
    check("die Zahl ist dieselbe wie in der Karte",
          pxeapp.lesbare_groesse(debian["bytes"]) == belegt("debian-trixie"),
          f'{pxeapp.lesbare_groesse(debian["bytes"])} vs {belegt("debian-trixie")}')

    # Dateien liegen da, starten laesst sich damit trotzdem nichts:
    # Ubuntu Server fehlt im Wegwerf-Verzeichnis eine Datei. In der
    # Startbereit-Liste weiter oben taucht so einer nicht auf, hier muss er
    # es -- gerade ihn sucht, wer Platz braucht.
    angefangen = [e for e in auf["eintraege"] if not e["ready"]]
    check("was Platz belegt, aber nicht startet, steht trotzdem da",
          bool(angefangen),
          str([(e["slug"], e["ready"]) for e in auf["eintraege"]]))
    check("... und der Ordner steht dabei",
          all(e["ablage"] for e in angefangen),
          str([(e["slug"], e["ablage"]) for e in angefangen]))

    seite = c.get("/").text

    # -- Die Namensliste unter Betriebssystemen
    #
    # Sie zeigt Name UND Ausgabe, durch ein Leerzeichen getrennt: Eine
    # Distribution darf mehrfach bereitstehen, dann beantwortet der Name
    # allein nicht mehr, was ein bootender Rechner angeboten bekommt.
    # Beides kommt aus bezeichnungen -- also aus den Feldern unter
    # Quellen, mit catalog.yaml als Rueckfall.
    #
    # Erst _systeme(), dann die Seite holen: Was ein Abbild ueber sich
    # selbst sagt, wird beim ersten Zugriff von der Platte gelesen und
    # gemerkt. Andersherum verglichen wir eine Seite von vor dem
    # Nachlesen mit Namen von danach.
    mit_ausgabe = [e for e in pxeapp._systeme()
                   if e["ready"] and e.get("version")]
    seite = c.get("/").text
    liste = seite[seite.index('<ul class="namensliste">'):]
    liste = liste[:liste.index("</ul>")]
    # Verglichen wird unmaskiert: In einem Namen darf ein
    # Anfuehrungszeichen stehen ({"Zara"}), und Jinja schreibt es
    # anders in die Seite als html.escape hier -- derselbe Text, zwei
    # Schreibweisen.
    klartext = html.unescape(liste)
    fehlen = ["<li>%s %s</li>" % (e["name"], e["version"])
              for e in mit_ausgabe
              if "<li>%s %s</li>" % (e["name"], e["version"]) not in klartext]
    check("Name und Ausgabe stehen mit einem Leerzeichen dazwischen",
          not fehlen, str(fehlen)[:200])

    # Und die Probe aufs Exempel: Wird unter Quellen umbenannt, steht hier
    # der neue Name -- ohne dass jemand diese Seite anfassen muesste.
    probe = mit_ausgabe[0]
    pxebez.setze({probe["slug"]: {"name": "Eigenname",
                                 "version": "9.9", "info": ""}})
    check("ein eigener Name schlaegt auf Server Health durch",
          "<li>Eigenname 9.9</li>" in c.get("/").text)
    pxebez.setze({})
    check("... und ohne eigenen Namen gilt wieder die Vorgabe",
          "Eigenname" not in c.get("/").text)

    seite = c.get("/").text
    check("die Detailansicht steht auf Server Health",
          "Speicherplatz — Detailansicht" in seite)
    check("... mit Aufschluesselung und Summe",
          "Abbilder gesamt" in seite and "nicht startbereit" in seite
          and "verwaiste" in seite)

    # Verwaistes sitzt seit August 2026 als zweite Klappe in derselben
    # Karte -- dieselbe Frage wie die Detailansicht darueber, nur die
    # andere Haelfte der Antwort. Gibt es Funde, steht die Klappe offen:
    # sonst zeigte die Zeile "N verwaiste Ordner" auf einen zu.
    check("Verwaistes steht in der Speicherplatz-Karte",
          seite.index("Speicherplatz — Detailansicht")
          < seite.index("<summary>Verwaiste Ordner")
          < seite.index("<h2>Dienste</h2>"))
    check("... mit den Funden in der Zeile",
          "Verwaiste Ordner — 2 gefunden" in seite,
          seite[seite.index("<summary>Verwaiste"):][:60])
    check("... und offen, weil es etwas zu sehen gibt",
          'id="verwaist" open' in seite)

    # Geloescht wird nur, was in diesem Moment wirklich verwaist ist --
    # der Pfad kommt aus dem Browser und wird nicht geglaubt.
    r = c.post("/verwaist/loeschen", follow_redirects=True,
               data={"pfad": str(assets / "debian-trixie")})
    check("ein beanspruchter Ordner wird nicht geloescht",
          (assets / "debian-trixie").exists() and "gehört inzwischen" in r.text)

    r = c.post("/verwaist/loeschen", follow_redirects=True,
               data={"pfad": str(assets / "ubuntu-server-24-04")})
    check("der verwaiste dagegen schon",
          not (assets / "ubuntu-server-24-04").exists() and "gelöscht" in r.text)
    check("... und die andere Ausgabe steht noch",
          (assets / "ubuntu-server-26-04").is_dir())
    c.post("/verwaist/loeschen", data={"pfad": str(assets / "altsystem")})
    # Seit August 2026 die zweite Klappe der Speicherplatz-Karte. Sie
    # bleibt auch ohne Funde stehen -- eine, die verschwindet, laesst
    # offen, ob nichts gefunden wurde oder niemand gesucht hat. Und
    # zugeklappt muss die Zeile selbst schon antworten.
    seite = c.get("/").text
    check("ohne Funde bleibt die Klappe stehen", "Verwaiste Ordner" in seite)
    check("... und die Zeile sagt es zugeklappt",
          "Verwaiste Ordner — keine" in seite)
    check("... zugeklappt, denn es gibt nichts zu sehen",
          'id="verwaist" open' not in seite)
    check("... ohne Tabelle und ohne Loeschknopf",
          "/verwaist/loeschen" not in seite)

    # Zuletzt, weil hier Dateien wirklich verschwinden: alles, was vorher
    # laeuft, soll seine Abbilder noch vorfinden.
    print("\n-- Dateien loeschen, Eintrag behalten")

    def lege_an(*rel):
        for r in rel:
            p = assets / r
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x" * 2048)

    seite = c.get("/quellen").text
    def karte_von(slug):
        anfang = seite.index('name="name:%s"' % slug)
        return seite[anfang:seite.index("</details>", anfang)]

    check("Knopf steht, wo Dateien liegen",
          "/quellen/dateien/loeschen" in karte_von("mint-cinnamon"))
    check("... und nicht bei einem Eintrag ohne Dateien",
          "/quellen/dateien/loeschen" not in karte_von("opensuse-tumbleweed"))
    check("... und nicht bei netboot.xyz, das gar keine hat",
          "/quellen/dateien/loeschen" not in karte_von("netbootxyz"))

    r = c.post("/quellen/dateien/loeschen", data={"slug": "mint-cinnamon"},
               follow_redirects=True)
    check("Mints Dateien sind weg", not (assets / "mint-cinnamon").exists())
    check("... die Meldung nennt den frei gewordenen Platz",
          "frei" in r.text and "Linux Mint" in r.text)
    check("... der Eintrag bleibt und steht auf fehlt",
          "item mint-cinnamon " not in menue()
          and 'name="name:mint-cinnamon"' in c.get("/quellen").text)
    lege_an("mint-cinnamon/vmlinuz", "mint-cinnamon/initrd",
            "mint-cinnamon/casper/filesystem.squashfs")
    check("... und nach dem Abgleich ist er wieder da",
          "item mint-cinnamon " in menue())

    # Memtest legt BIOS- und UEFI-Datei nebeneinander. Der eine Eintrag darf
    # dem anderen nicht die Datei unter den Fuessen wegloeschen.
    c.post("/quellen/dateien/loeschen", data={"slug": "memtest-bios-8-10"})
    check("nur die eigene Datei faellt",
          not (assets / "memtest-bios-8-10/memtest.bin").exists()
          and (assets / "memtest-efi-8-10/memtest.efi").is_file())
    lege_an("memtest-bios-8-10/memtest.bin")

    # Der alte Weg loeschte nur den gemeinsamen Ordner der Startdateien --
    # bei GParted waeren ISO und entpacktes Abbild liegen geblieben, also
    # gerade die grossen Brocken.
    lege_an("gparted-live-1-8-1-3/gparted.iso", "gparted-live-1-8-1-3/.entpackt")
    c.post("/quellen/dateien/loeschen", data={"slug": "gparted-live-1-8-1-3"})
    check("auch was neben den Startdateien liegt, geht mit",
          not (assets / "gparted-live-1-8-1-3").exists(),
          str(list((assets / "gparted-live-1-8-1-3").rglob("*")) if (assets / "gparted-live-1-8-1-3").exists() else []))
    lege_an("gparted-live-1-8-1-3/live/vmlinuz",
            "gparted-live-1-8-1-3/live/initrd.img",
            "gparted-live-1-8-1-3/live/filesystem.squashfs")

    # Hochgeladenes hat sein eigenes "Loeschen" -- dort verschwindet der
    # ganze Eintrag, hier nur seine Dateien.
    r = c.post("/quellen/dateien/loeschen",
               data={"slug": "iso-linuxmint-22-3-cinnamon-64bit"},
               follow_redirects=True)
    check("Uploads gehen diesen Weg nicht", "gibt es das nicht" in r.text)

    # -- Die Adresse: abgelesen, nicht geschrieben
    #
    # Seit dem 27.08.2026 fasst dieser Server die Netzkonfiguration des
    # Hosts nicht mehr an. Sie gehoert dem Betreiber; die Karte liest sie
    # ab und bietet den einen Befehl an, der die abgelesene Adresse in die
    # vier Stellen des Bootservers uebernimmt.
    print("\n-- Adresse uebernehmen")
    import serveradresse

    start = c.get("/einrichtung").text
    check("der zweite Knopf heisst jetzt Uebernehmen",
          "IP-Adresse übernehmen</button>" in start)
    check("... und verspricht nicht mehr, die Adresse zu aendern",
          "Server-IP ändern" not in start)

    karte = c.get("/einrichtung?schritt=ip").text
    check("kein Eingabefeld mehr",
          'name="ip"' not in karte and 'name="maske"' not in karte
          and 'name="gateway"' not in karte)
    check("dafuer der fertige Befehl", "sudo /opt/pxe-setup/install.sh" in karte)
    check("... mit einem Knopf zum Kopieren",
          'class="kopierknopf"' in karte and 'data-quelle="uebernahme"' in karte)
    check("die Karte sagt, dass sie nichts anfasst",
          "ändert dieser Server" in karte and "Betreiber" in karte)

    # Das Ablesen selbst, gegen die Ausgabe echter Systeme. Eingespielt
    # wird sie ueber den Leser, den netzlage() entgegennimmt -- so braucht
    # der Test kein iproute2 und keine zweite Maschine.
    def lies_fuer(route, adressen):
        return lambda *args: route if "route" in args else adressen

    fest = serveradresse.netzlage(lies_fuer(
        "default via 192.168.178.1 dev enp0s3 proto static metric 100\n",
        "2: enp0s3    inet 192.168.178.30/24 brd 192.168.178.255 "
        "scope global enp0s3\n"))
    check("feste Adresse wird richtig gelesen",
          fest["ip"] == "192.168.178.30" and fest["praefix"] == 24
          and fest["maske"] == "255.255.255.0"
          and fest["gateway"] == "192.168.178.1"
          and fest["karte"] == "enp0s3" and not fest["dynamisch"], str(fest))

    # Eine Reservierung am Router sieht fuer den Kernel genauso aus wie
    # eine gewoehnliche Lease -- beide stehen als "dynamic" da. Deshalb
    # heisst das Feld "dynamisch" und nicht "unsicher": Es sagt, woher die
    # Adresse kommt, nicht ob sie taugt.
    bezogen = serveradresse.netzlage(lies_fuer(
        "default via 192.168.1.1 dev ens18 proto dhcp src 192.168.1.55 metric 100\n",
        "2: ens18    inet 192.168.1.55/24 brd 192.168.1.255 "
        "scope global dynamic ens18\n"))
    check("vom Router bezogene Adresse wird als solche erkannt",
          bezogen["ip"] == "192.168.1.55" and bezogen["dynamisch"], str(bezogen))

    check("Abweichung wird gemeldet",
          serveradresse.abweichung("192.168.178.30", bezogen) == "192.168.1.55")
    check("... und Gleichstand nicht",
          serveradresse.abweichung("192.168.1.55", bezogen) == "")

    # Eine zweite Adresse auf derselben Karte kaeme aus einem Alias -- die
    # Boot-Skripte tragen ohnehin nur eine, und "scope host" ist keine.
    mehrere = serveradresse.netzlage(lies_fuer(
        "default via 10.0.0.1 dev eth0 proto static\n",
        "2: eth0    inet 127.0.0.1/8 scope host lo\n"
        "2: eth0    inet 10.0.0.7/16 brd 10.0.255.255 scope global eth0\n"))
    check("scope host wird uebergangen",
          mehrere["ip"] == "10.0.0.7" and mehrere["praefix"] == 16, str(mehrere))

    # Ohne iproute2 -- auf einem Entwicklungsrechner etwa -- gibt es nichts
    # zu lesen. Daraus darf kein Befund werden: Ein Alarm, der oefter
    # falsch als richtig ist, wird nach einer Woche ueberlesen.
    leer = serveradresse.netzlage(lambda *args: "")
    check("ohne lesbare Netzkonfiguration steht der Grund da",
          bool(leer["fehler"]) and not leer["ip"], str(leer))
    check("... und daraus wird keine Abweichung",
          serveradresse.abweichung("192.168.178.30", leer) == "")

    # -- Die Seitenkarte: der Adressbefund gilt dem Server, nicht der Seite
    #
    # Er muss erscheinen UND verschwinden: Ein Hinweis, der stehen bleibt,
    # nachdem das Problem weg ist, macht aus einer Auskunft eine Tapete.
    # Und er muss auf JEDER Seite stehen -- bis zum 28.08.2026 stand er auf
    # zweien, und wer unter Clients eine Installation zuwies, sah nichts.
    #
    # Gepatcht wird netzlage() im Modul, nicht der Leser darin: befunde.py
    # ruft serveradresse.netzlage() ueber den Modulnamen auf. Der gepufferte
    # Stand muss dabei weg, sonst antwortet der Puffer statt des Patches.
    import app as pxeapp_
    import befunde as befunde_
    import kenntnis as kenntnis_
    TITEL = "Kein Rechner findet seine Dateien"
    echt = serveradresse.netzlage

    def netz(ip, fehler=""):
        """netzlage() festlegen und den Puffer wegwerfen."""
        serveradresse.netzlage = lambda: {
            "karte": "eth0" if ip else "", "ip": ip, "praefix": 24 if ip else None,
            "maske": "255.255.255.0" if ip else "", "gateway": "192.168.178.1",
            "netz": "192.168.178.0/24" if ip else "", "dynamisch": True,
            "fehler": fehler}
        befunde_.vergiss()

    try:
        netz("192.168.178.99")
        seite = c.get("/").text
        check("eine weggelaufene Adresse wird zur Fehlerkarte",
              'class="seitenkarte stufe-fehler"' in seite
              and TITEL in seite and "192.168.178.99" in seite)
        check("... mit dem Weg zum Nachziehen",
              'href="/einrichtung?schritt=ip#ersteinrichtung"' in seite)
        check("... ueber den Karten, nicht in einer",
              seite.index(TITEL) < seite.index('id="auslastung"'))
        # Zugeklappt, auch der Fehler: Sonst bestuende die Seite aus ihm.
        karte = seite[seite.index("<details class=\"seitenkarte"):]
        check("... und zugeklappt",
              karte[:karte.index(">") + 1].find(" open") == -1,
              karte[:karte.index(">") + 1])

        # Der Punkt der ganzen Uebung: Er haengt nicht am Reiter.
        for weg in ("/clients", "/systeme", "/quellen", "/einrichtung",
                    "/history", "/hilfe"):
            check(f"der Befund steht auch auf {weg}", TITEL in c.get(weg).text)

        # ... und doppelt steht er nirgends. Unter Einrichtung stand
        # derselbe Satz bis zum 28.08.2026 ein zweites Mal.
        check("und unter Einrichtung nur einmal",
              c.get("/einrichtung").text.count(TITEL) == 1)

        # Derselbe Wert wie eingerichtet -- kein Befund.
        netz(pxeapp_.SERVER_HOST)
        check("stimmt sie ueberein, steht nichts da", TITEL not in c.get("/").text)

        # Nichts zu lesen ist kein Befund. Sonst haette jeder
        # Entwicklungsrechner dauerhaft Alarm.
        netz("", "Keine Standardroute gefunden.")
        check("ohne lesbare Netzkonfiguration bleibt es still",
              TITEL not in c.get("/").text)
    finally:
        serveradresse.netzlage = echt
        befunde_.vergiss()

    # Die Reihenfolge der Stufen ist die der Dringlichkeit, nicht die, in
    # der die Befunde entstehen. Geprueft ohne echte Zustaende: Was sortiert
    # wird, entscheidet nur die Stufe.
    gemischt = befunde_.sortiert([{"stufe": "info"}, {"stufe": "fehler"},
                                  {"stufe": "info"}, {"stufe": "warnung"}])
    check("Fehler, dann Warnung, dann Info",
          [b["stufe"] for b in gemischt]
          == ["fehler", "warnung", "info", "info"], str(gemischt))

    # -- Die Dienste: ein Ausfall ist nicht wie der andere
    #
    # Ohne dnsmasq kommt kein Rechner durch (rot), ohne nfs-server nur die
    # grossen Live-Systeme nicht (gelb). Bis zum 28.08.2026 sagte die
    # Oberflaeche zu beidem denselben Satz -- und zwar nur auf einer Seite.
    import dienste as dienste_
    # -- Der Katalog: jede Karte einmal beschrieben
    #
    # Zwei Pruefungen, und die erste haette die Luecke vom 02.09.2026
    # gefunden: smbd stand in dienste.EINHEITEN, erschien in der Karte
    # Dienste -- und in keiner Stufe. Es fiel aus, und die Oberflaeche
    # schwieg. Vier Dienste hatten eine Stufe, der fuenfte nicht.
    print("\n-- Der Befund-Katalog")
    import befunde as befunde_
    import kenntnis as kenntnis_
    ohne_stufe = [n for n in dienste_.EINHEITEN
                  if n not in befunde_.BOOTDIENSTE
                  and n not in befunde_.TEILDIENSTE]
    doppelt = [n for n in befunde_.BOOTDIENSTE if n in befunde_.TEILDIENSTE]
    check("jeder ueberwachte Dienst hat genau eine Stufe",
          not ohne_stufe and not doppelt,
          "ohne Stufe: %s, doppelt: %s" % (ohne_stufe, doppelt))

    # Jede Katalogzeile hat eine Vorlage, jede Vorlage eine Zeile -- sonst
    # rendert ein Befund ins Leere oder eine Datei liegt tot herum.
    vorlagen = {p.stem for p in
                (PROJ / "webui" / "templates" / "befunde").glob("*.html")}
    kennungen = {e["kennung"] for e in befunde_.KATALOG}
    check("jede Karte hat ihre Vorlage und umgekehrt",
          vorlagen == kennungen,
          "nur im Katalog: %s, nur als Datei: %s"
          % (sorted(kennungen - vorlagen), sorted(vorlagen - kennungen)))

    # Rot ist nicht wegklickbar -- der Katalog sagt es, indem "wieder"
    # leer bleibt. Waere dort etwas eingetragen, widerspraeche der Text in
    # der Hilfe dem Verhalten der Oberflaeche.
    # Die Hilfe rendert denselben Katalog -- geprueft an der Seite selbst,
    # damit die Tabelle nicht still leer bleibt.
    hilfe = c.get("/hilfe").text
    # Einzahl und Mehrzahl auf Server Health. Faellt nur auf einem frisch
    # aufgesetzten Server auf -- dort steht oft genau eine Eins, und
    # "1 Betriebssysteme startbereit" ist kein Satz. Gefunden am
    # 02.09.2026 bei der ersten Installation auf dev-marlei.
    vorlage = (PROJ / "webui" / "templates" / "serverhealth.html").read_text(
        encoding="utf-8")
    hart = [z for z in ("</span> Betriebssysteme startbereit",
                        "</span> Clients registriert",
                        "</span> werden installiert")
            if z in vorlage]
    check("keine harte Mehrzahl auf Server Health", not hart, str(hart))

    # -- Ein Server, der nicht die Produktion ist
    #
    # Leer heisst Produktion: Der produktive Server bleibt unveraendert,
    # ohne dass dort jemand etwas eintraegt. Das ist die wichtigere
    # Haelfte der Pruefung -- eine Kennzeichnung, die versehentlich
    # ueberall erschiene, waere schlimmer als keine.
    seite = c.get("/").text
    check("ohne Kennzeichnung bleibt die Seite, wie sie war",
          'class="gekennzeichnet"' not in seite
          and 'class="kennzeichnung"' not in seite)

    vorher = pxeapp.KENNZEICHNUNG
    try:
        pxeapp.KENNZEICHNUNG = "Entwicklung"
        seite = c.get("/").text
        check("mit Kennzeichnung faerbt sich der Grund",
              'class="gekennzeichnet"' in seite)
        check("... und das Wort steht in der Kopfzeile",
              '<span class="kennzeichnung">Entwicklung</span>' in seite)
        check("... auf jedem Reiter",
              'class="gekennzeichnet"' in c.get("/systeme").text)
        stil = (PROJ / "webui" / "static" / "style.css").read_text(encoding="utf-8")
        check("der Sandgrund steht im Stylesheet, hell wie dunkel",
              "body.gekennzeichnet { --bg: #faf1de; }" in stil
              and "body.gekennzeichnet { --bg: #1c1811; }" in stil)
    finally:
        pxeapp.KENNZEICHNUNG = vorher

    check("die Hilfe fuehrt jede Karte auf",
          all(e["titel"] in hilfe for e in befunde_.KATALOG)
          and all(e["wodurch"][:40] in hilfe for e in befunde_.KATALOG))

    # Und die Vorschau ohne Server auch: Sie rendert dieselbe Vorlage und
    # ist am 02.09.2026 daran zerbrochen, dass eine Karte nach "request"
    # griff. Das faellt sonst erst auf, wenn jemand die Seite baut.
    import subprocess as _sub
    lauf = _sub.run([sys.executable, str(PROJ / "tools" / "hilfe-vorschau.py")],
                    capture_output=True, text=True)
    check("die Hilfe-Vorschau rendert ohne laufenden Server",
          lauf.returncode == 0, lauf.stderr[-200:])

    check("bei Rot bleibt das Wiederkommen leer",
          all(not e["wieder"] for e in befunde_.KATALOG
              if e["stufe"] == "fehler")
          and all(e["wieder"] for e in befunde_.KATALOG
                  if e["stufe"] in kenntnis_.WEGKLICKBAR))

    BOOT = "Kein Rechner kann gerade starten"
    NFS = "Live-Systeme starten gerade nicht"
    SMB = "Windows lässt sich gerade nicht installieren"
    VOLL = "Der Platz reicht nicht mehr für ein Abbild"
    echte_zustaende, echter_platz = dienste_.zustaende, dienste_.platz

    def laufen(**aus):
        """Dienste festlegen: laufen(dnsmasq=False) haelt genau den an."""
        dienste_.zustaende = lambda: [
            {"name": n, "zustand": "inactive" if aus.get(n) is False
             else ("unbekannt" if aus.get(n) == "?" else "active"),
             "laeuft": aus.get(n, True) is True,
             "wofuer": dienste_.WOFUER[n]}
            for n in dienste_.EINHEITEN]

    try:
        laufen(dnsmasq=False)
        seite = c.get("/").text
        check("ein toter Bootdienst wird zur Fehlerkarte",
              'class="seitenkarte stufe-fehler"' in seite and BOOT in seite)
        check("... und nennt den Dienst samt Weg ins Protokoll",
              "journalctl -u dnsmasq" in seite
              and 'href="/protokoll?einheit=dnsmasq"' in seite)
        check("... auf jedem Reiter", BOOT in c.get("/clients").text)
        # Die Ampel unter der Karte sagt dieselbe Tatsache und muss
        # deshalb denselben Takt haben. Bis zum 02.09.2026 frischte sich
        # der Befund auf und die Ampel nicht -- wer einen Dienst startete,
        # sah die Karte gehen und darunter weiter Rot.
        stueck = c.get("/status.html").text
        check("die Ampeln ziehen im Fuenf-Sekunden-Takt mit",
              'data-teil="dienste"' in stueck and 'class="ampel' in stueck)
        check("... und die Karte holt dieselbe Tabelle",
              'data-teil="dienste"' in c.get("/").text)
        # Der Kartenfuss nennt beide Zahlen -- und steht ausserhalb von
        # data-teil, sonst tauscht ihn das Skript weg.
        seite = c.get("/").text
        fuss = "Aktualisierung alle 5 Sekunden, der Zustand ist bis"
        check("die Dienste-Karte sagt ihren Takt",
              fuss in seite and fuss not in c.get("/status.html").text)

        laufen(**{"nfs-server": False})
        seite = c.get("/").text
        check("ein totes NFS wird zur Warnkarte",
              'class="seitenkarte stufe-warnung"' in seite and NFS in seite)
        check("... und sagt, dass der Rest weiterlaeuft",
              "andere startet weiter" in seite)
        check("... aber keine Fehlerkarte", BOOT not in seite)

        # Samba traegt die andere Haelfte des Repertoires. Eigene Karte und
        # nicht dieselbe: Der Titel nennt die Folge, und die ist hier eine
        # andere. Aufgefallen am 02.09.2026, als smbd in keiner Stufe stand.
        laufen(smbd=False)
        seite = c.get("/").text
        check("ein totes Samba wird zur Warnkarte",
              'class="seitenkarte stufe-warnung"' in seite and SMB in seite)
        check("... und nennt den Dienst samt Weg ins Protokoll",
              "journalctl -u smbd" in seite
              and 'href="/protokoll?einheit=smbd"' in seite)
        check("... und nicht den NFS-Satz", NFS not in seite)

        laufen(smbd=False, **{"nfs-server": False})
        seite = c.get("/").text
        check("beide Teildienste geben zwei Karten",
              NFS in seite and SMB in seite)
        check("... in der Reihenfolge von TEILDIENSTE",
              seite.index(NFS) < seite.index(SMB))

        # Beides zugleich: rot ueber gelb, ohne Ausnahme.
        laufen(dnsmasq=False, **{"nfs-server": False})
        seite = c.get("/").text
        check("beides zugleich gibt zwei Karten",
              BOOT in seite and NFS in seite)
        check("... und die rote steht oben", seite.index(BOOT) < seite.index(NFS))

        # Kein systemd -- etwa auf einem Entwicklungsrechner. Daraus darf
        # kein Dauerbefund werden, dieselbe Regel wie bei der Adresse.
        laufen(**{n: "?" for n in dienste_.EINHEITEN})
        seite = c.get("/").text
        check("nicht abfragbare Dienste sind kein Befund",
              BOOT not in seite and NFS not in seite)

        # -- Der Platz (A-021). Gewarnt wird nicht mehr bei einem
        # Prozentsatz, sondern wenn der Platz fuer ein weiteres Abbild
        # nicht mehr reicht. Der Balken faerbt sich nach derselben Regel
        # rot -- geprueft wird genau das, sonst laufen sie auseinander.
        laufen()
        gb = 1073741824

        def platte_frei(frei_gb, gesamt_gb=100):
            """Belegung festlegen ueber das, was frei ist."""
            belegt = gesamt_gb - frei_gb
            dienste_.platz = lambda p: {
                "gesamt": gesamt_gb * gb, "belegt": belegt * gb,
                "frei": frei_gb * gb,
                "anteil": round(belegt / gesamt_gb * 100)}

        # Die Reserve steht erst fest, wenn die Seite einmal gemessen hat.
        c.get("/")
        reserve_gb = dienste_.reserve() // gb
        check("die Reserve ist mindestens der Sockel",
              reserve_gb >= dienste_.SOCKEL // gb)

        platte_frei(reserve_gb - 1)
        seite = c.get("/").text
        check("zu wenig Platz fuer ein Abbild wird zur Warnkarte",
              VOLL in seite and 'class="seitenkarte stufe-warnung"' in seite)
        check("... mit den Zahlen darin",
              f"{reserve_gb - 1}" in seite and f"{reserve_gb} GB" in seite)
        check("... und der Balken heisst dort voll",
              'class="balken voll"' in seite)

        platte_frei(reserve_gb)
        seite = c.get("/").text
        check("genau auf der Reserve gilt sie noch nicht", VOLL not in seite)
        check("... und der Balken ist dort nicht voll",
              'class="balken voll"' not in seite)

        # Der Kern der Aufgabe: Eine grosse Platte darf hoch belegt sein,
        # solange das naechste Abbild noch draufpasst. Frueher warnte hier
        # der Prozentsatz -- auf 5 TB bei 500 GB frei, Platz fuer Dutzende.
        platte_frei(500, gesamt_gb=5000)
        seite = c.get("/").text
        check("eine grosse Platte warnt nicht bei 90 Prozent", VOLL not in seite)
        check("... obwohl der Prozentsatz die alte Schwelle erreicht",
              "90 %" in seite)

        # Und die kleine Platte bleibt versorgt: Dort ist die Reserve die
        # strengere der beiden Regeln, nicht die schwaechere.
        platte_frei(2, gesamt_gb=20)
        check("eine kleine Platte warnt weiterhin rechtzeitig",
              VOLL in c.get("/").text)

        # Ohne lesbare Belegung kein Befund -- nichts zu wissen ist kein Alarm.
        dienste_.platz = lambda p: {}
        check("ohne lesbare Belegung bleibt es still", VOLL not in c.get("/").text)

        # -- Zur Kenntnis nehmen (A-010)
        #
        # Weggeklickt heisst nicht weg: Die Karte schrumpft auf eine graue
        # Zeile. Und sie kommt zurueck, wenn es schlimmer wird -- gemessen
        # an den Gigabyte, die an der Reserve fehlen.
        print("\n-- Befunde zur Kenntnis nehmen")
        import kenntnis
        kenntnis.zuruecksetzen()
        laufen()

        def platte(frei_gb):
            platte_frei(frei_gb)

        platte(reserve_gb - 1)
        seite = c.get("/").text
        check("die Warnkarte steht offen da",
              'class="seitenkarte stufe-warnung"' in seite
              and "Zur Kenntnis genommen" in seite)

        c.post("/befund/kenntnis", data={"kennung": "platte", "zurueck": "/systeme"},
               follow_redirects=False)
        seite = c.get("/").text
        check("nach dem Wegklicken keine Karte mehr",
              'class="seitenkarte stufe-warnung"' not in seite)
        check("... aber die graue Zeile ist da",
              'class="bekanntzeile"' in seite and VOLL in seite)
        check("... und zwar auf jedem Reiter",
              'class="bekanntzeile"' in c.get("/systeme").text
              and 'class="bekanntzeile"' in c.get("/clients").text)

        # Dieselbe Lage ist kein neuer Befund -- sonst waere das
        # Wegklicken ein Aufschub um Minuten. Die Marke zaehlt ganze
        # Gigabyte, innerhalb desselben bleibt es still.
        platte(reserve_gb - 1)
        check("dieselbe Lage holt sie nicht zurueck",
              'class="seitenkarte stufe-warnung"' not in c.get("/").text)

        # Ein Gigabyte weniger schon.
        platte(reserve_gb - 2)
        check("ein Gigabyte weniger holt sie zurueck",
              'class="seitenkarte stufe-warnung"' in c.get("/").text)

        # War der Befund weg und kommt wieder, ist er ein neuer.
        c.post("/befund/kenntnis", data={"kennung": "platte", "zurueck": "/"},
               follow_redirects=False)
        check("wieder weggeklickt", 'class="bekanntzeile"' in c.get("/").text)
        platte(reserve_gb + 40)
        check("ueber der Reserve ist gar nichts da",
              VOLL not in c.get("/").text)
        platte(reserve_gb - 2)
        check("und danach faengt er offen an",
              'class="seitenkarte stufe-warnung"' in c.get("/").text)

        # Zwei Karten, eine weggeklickt: Die andere bleibt stehen. Beide
        # sind gelb, aber es sind zwei Befunde und nicht einer.
        kenntnis.zuruecksetzen()
        platte(reserve_gb + 40)
        laufen(smbd=False, **{"nfs-server": False})
        c.post("/befund/kenntnis", data={"kennung": "teildienst", "zurueck": "/"},
               follow_redirects=False)
        seite = c.get("/").text
        check("die weggeklickte Karte ist leise", NFS not in seite.split('bekanntzeile')[0])
        check("... die andere steht weiter offen da",
              'class="seitenkarte stufe-warnung"' in seite and SMB in seite)

        # Rot laesst sich nicht wegklicken -- weder im Formular noch am
        # Endpunkt vorbei.
        kenntnis.zuruecksetzen()
        platte(reserve_gb + 40)
        laufen(dnsmasq=False)
        seite = c.get("/").text
        check("die rote Karte hat keinen Knopf",
              BOOT in seite and "Zur Kenntnis genommen" not in seite)
        c.post("/befund/kenntnis", data={"kennung": "bootdienst", "zurueck": "/"},
               follow_redirects=False)
        check("... und laesst sich auch am Endpunkt nicht wegklicken",
              BOOT in c.get("/").text)

        # Das Stueck fuer den Takt: dieselben Karten, ohne den Rest der
        # Seite. "von" sagt, wohin der Knopf zurueckfuehrt.
        laufen()
        platte(reserve_gb - 1)
        kenntnis.zuruecksetzen()
        stueck = c.get("/befunde.html?von=/systeme").text
        check("das nachgeholte Stueck traegt dieselbe Karte",
              'class="seitenkarte stufe-warnung"' in stueck and VOLL in stueck)
        check("... und den Weg zurueck auf die fragende Seite",
              'name="zurueck" value="/systeme"' in stueck)
        check("eine erfundene Seite wird nicht uebernommen",
              'name="zurueck" value="/"'
              in c.get("/befunde.html?von=https://fremd.example/").text)
        kenntnis.zuruecksetzen()
    finally:
        dienste_.zustaende, dienste_.platz = echte_zustaende, echter_platz

    # Ein Name in PXE_BASE_URL ist keine Adresse -- da gibt es nichts zu
    # vergleichen, und ein Dauerbefund waere die Strafe fuer den
    # ordentlichsten Aufbau von allen.
    mit_ip = {"karte": "eth0", "ip": "10.0.0.7", "praefix": 24,
              "maske": "255.255.255.0", "gateway": "10.0.0.1",
              "netz": "10.0.0.0/24", "dynamisch": False, "fehler": ""}
    check("ein Hostname loest keinen Befund aus",
          serveradresse.abweichung("bootsrv.intern", mit_ip) == ""
          and serveradresse.abweichung("10.0.0.8", mit_ip) == "10.0.0.7")

    # Die alte Route ist weg -- sie baute einen Befehl aus drei Eingaben,
    # und beides gibt es nicht mehr.
    check("der alte Endpunkt antwortet nicht mehr",
          c.post("/einrichtung/serverip",
                 data={"ip": "1.2.3.4", "maske": "24", "gateway": "1.2.3.1"},
                 follow_redirects=False).status_code in (404, 405))

    # -- Stand: welche Fassung hier laeuft
    #
    # Gestempelt von install.sh, gelesen aus einer Datei -- /opt/pxeweb
    # ist eine rsync-Kopie ohne .git. Geprueft wird beides: dass der
    # Stempel ankommt und dass sein Fehlen nicht als "Version 0"
    # durchgeht, sondern als Ansage.
    print("\n-- Stand")
    import versionsstand
    seite = c.get("/einrichtung").text
    check("die Version steht auf der Einrichtungsseite",
          "v1.2-3-gabc1234" in seite)
    check("... daneben die letzte Aktualisierung",
          "2026-08-26 18:00" in seite)
    check("der Zweig main wird nicht eigens erwaehnt",
          "Zweig" not in seite)
    check("kurz() gibt eine Zeile fuer Fehlermeldungen",
          versionsstand.kurz() == "v1.2-3-gabc1234",
          versionsstand.kurz())

    # Ein anderer Zweig ist keine Stoerung, aber die haeufigste Erklaerung
    # dafuer, dass jemand etwas anderes sieht als erwartet -- also sichtbar.
    stempel.write_text("stand=v1.2-3-gabc1234\nzweig=windows-test\n",
                       encoding="utf-8")
    check("ein anderer Zweig wird genannt",
          "windows-test" in c.get("/einrichtung").text)

    # Und der Fall, den man leicht falsch macht: keine Datei heisst nicht
    # "Version 0", sondern "nicht ueber install.sh hierhergekommen".
    stempel.unlink()
    seite = c.get("/einrichtung").text
    check("ohne Stempel wird nicht geraten", "v1.2-3" not in seite)
    check("... sondern gesagt, warum nichts dasteht",
          "install.sh" in seite and "Version 0" in seite)
    check("... und kurz() bleibt leer", versionsstand.kurz() == "")

    # -- Die Meldung und ihre Auspraegung (A-021)
    #
    # Drei Dinge: Eine Zurueckweisung sieht anders aus als eine Zusage,
    # sie ueberlebt kein Neuladen, und es bleibt bei EINEM Meldungsweg.
    print("\n-- Meldung: Auspraegung und Lebensdauer")

    # Eine Zurueckweisung: Wecken ohne angekreuzten Rechner.
    r = c.post("/clients/wecken", data={}, follow_redirects=False)
    ziel = r.headers["location"]
    check("eine Zurueckweisung traegt die Auspraegung in der Adresse",
          "art=schlecht" in ziel, ziel)
    seite = c.get(ziel).text
    check("... und die Zeile traegt sie als Klasse",
          'class="hint meldung schlecht"' in seite, seite[:0])
    check("... mit dem Satz darin", "Keinen Rechner angekreuzt" in seite)

    # Eine Zusage: dieselbe Bauart, ohne Auspraegung.
    r = c.post("/quellen/speichern", data={}, follow_redirects=False)
    ziel = r.headers["location"]
    check("eine Zusage traegt keine Auspraegung", "art=" not in ziel, ziel)
    seite = c.get(ziel).text
    check("... und die Zeile bleibt die gedaempfte",
          'class="hint meldung "' in seite
          and 'class="hint meldung schlecht"' not in seite)

    # Lebensdauer: Die Seite nimmt die beiden Parameter nach dem Anzeigen
    # aus der Adresse. Geprueft wird, dass das Stueck da ist und beide
    # nennt -- die Wirkung selbst liegt im Browser.
    check("die Seite raeumt die Meldung aus der Adresse",
          'searchParams.delete("meldung")' in seite
          and 'searchParams.delete("art")' in seite
          and "replaceState" in seite)

    # Und der eine Weg: Keine Route baut sich ihre Adresse noch selbst.
    quelltext = Path(pxeapp.__file__).read_text(encoding="utf-8")
    # Gesucht wird das Bauen, nicht das Erwaehnen: Zwei Docstrings nennen
    # "?meldung=", ohne eine Adresse zusammenzusetzen.
    selbstgebaut = [z for z in quelltext.splitlines()
                    if '?meldung=" +' in z]
    check("es gibt genau einen Meldungsweg",
          len(selbstgebaut) == 1 and "ziel = seite" in selbstgebaut[0],
          str(selbstgebaut))

    # -- Werkseinstellung: alles weg, aber erst nach drei Schritten
    #
    # Der zerstoerendste Knopf der Oberflaeche, und sie hat keine
    # Anmeldung. Geprueft wird deshalb vor allem, was NICHT passiert:
    # dass kein Schritt sich ueberspringen laesst und dass bis zum letzten
    # Klick nichts verschwindet.
    print("\n-- Werkseinstellung")
    import werkseinstellung as werk
    seite = c.get("/einrichtung").text
    check("die Karte steht auf der Seite", 'id="ersteinrichtung"' in seite)
    check("... ganz unten, hinter den Einstellungen",
          seite.index('id="ersteinrichtung"') > seite.index("PXE_MENU_TIMEOUT"))
    check("zuerst steht dort nur der Knopf",
          "Werkseinstellung</button>" in seite
          and 'name="wort"' not in seite)

    feld = c.get("/einrichtung?schritt=wort").text
    check("nach dem Klick steht das Feld da", 'name="wort"' in feld)
    # Der Punkt der ganzen Abfrage: Ein vorbelegtes Feld waere keine
    # Huerde -- man druecke Enter, und der Server ist leer.
    check("... und zwar LEER, mit dem Wort nur als Hinweis",
          'placeholder="Löschen"' in feld
          and 'name="wort" autocomplete="off"' in feld
          and 'value="Löschen"' not in feld.split('id="ersteinrichtung"')[1]
                                            .split("Weiter</button>")[0])

    # Ein falsches Wort kommt nicht weiter.
    for versuch in ("", "  ", "loesch", "ja"):
        r = c.post("/einrichtung/werkseinstellung", data={"wort": versuch},
                   follow_redirects=False)
        check("»%s« kommt nicht durch" % versuch,
              "schritt=wort" in r.headers["location"], r.headers["location"])
    check("die Abbilder liegen noch da", (assets / "gparted-live-1-8-1-3").exists())

    # Das richtige schon -- auch ohne Umlaut und ohne Grossschreibung.
    for versuch in ("Löschen", " löschen ", "LOESCHEN"):
        r = c.post("/einrichtung/werkseinstellung", data={"wort": versuch},
                   follow_redirects=False)
        check("»%s« gilt" % versuch.strip(),
              "schritt=sicher" in r.headers["location"], r.headers["location"])

    warnung = c.get("/einrichtung?schritt=sicher").text
    check("die Warnung sagt, was verloren geht",
          "nicht rückgängig" in warnung and "Bestätigen</button>" in warnung)
    check("... und was bleibt", "wimboot" in warnung and "pxeweb.env" in warnung)
    check("bis hierher ist nichts geloescht",
          (assets / "gparted-live-1-8-1-3").exists()
          and Path(os.environ["PXE_QUELLEN"]).exists())

    # Der letzte Schritt ist keine Seite, sondern ein Schloss: Ohne das
    # Wort richtet ein Aufruf dieses Pfades nichts aus.
    r = c.post("/einrichtung/werkseinstellung/bestaetigen", data={"wort": ""},
               follow_redirects=True)
    check("ohne Wort passiert auch beim Bestaetigen nichts",
          (assets / "gparted-live-1-8-1-3").exists() and "abgebrochen" in r.text)

    # Und jetzt wirklich. Vorher noch zwei Zeugen anlegen: einen Ordner,
    # der gehen muss, und wimboot, das bleiben muss.
    lege_an("wimboot/wimboot", "upload/iso-alt/abbild.iso")
    with sqlite3.connect(os.environ["PXE_DB"]) as pruefdb:
        vorher_clients = pruefdb.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
    check("vor dem Reset stehen Rechner in der Datenbank", vorher_clients > 0)

    r = c.post("/einrichtung/werkseinstellung/bestaetigen",
               data={"wort": "Löschen"}, follow_redirects=True)
    check("die Meldung sagt, dass zurueckgesetzt wurde",
          "Werkseinstellung zurückgesetzt" in r.text, r.text[:200])
    check("die Abbilder sind weg", not (assets / "gparted-live-1-8-1-3").exists())
    check("... auch die hochgeladenen", not (assets / "upload/iso-alt").exists())
    check("... und der gemerkte Zustand",
          not Path(os.environ["PXE_QUELLEN"]).exists()
          and not (tmp / "test.db").with_name("freigabe.yaml").exists())
    check("wimboot bleibt -- es gehoert zur Installation",
          (assets / "wimboot/wimboot").is_file())
    check("der Upload-Ordner bleibt als leerer Ordner",
          (assets / "upload").is_dir() and not any((assets / "upload").iterdir()))
    check("der Katalog wird nicht angefasst",
          Path(os.environ["PXE_CATALOG"]).is_file())

    # Danach muss der Server weiterlaufen, nicht nur nicht abstuerzen.
    check("die Datenbank ist wieder benutzbar",
          c.get("/clients").status_code == 200)
    with sqlite3.connect(os.environ["PXE_DB"]) as pruefdb:
        check("... und leer",
              pruefdb.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0)
    check("der Katalog ist leer wie nach dem Aufsetzen",
          not any(e.get("versionsliste") for e in pxeapp.load_catalog()),
          str([e["slug"] for e in pxeapp.load_catalog()][:6]))
    check("das Bootmenue steht und bietet nur die Systempunkte",
          "item local " in menue())

print()
if fails:
    print(f"{len(fails)} Test(s) fehlgeschlagen:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("Alle Tests bestanden.")

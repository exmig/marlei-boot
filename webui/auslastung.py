"""
Was tut der Server gerade? -- Last und laufende Uebertragungen.

Zwei Fragen, eine Quelle: alles kommt aus /proc, ohne Zusatzpakete und ohne
besondere Rechte. Auf einem System ohne /proc (etwa beim Entwickeln unter
Windows) liefert jede Funktion leere Werte statt einer Behauptung.

Der Trick bei "laufende Installationen": das eigentliche Ausliefern macht
nginx beziehungsweise der NFS-Dienst, die Anwendung sieht davon nichts. Was
sie sehen kann, sind die offenen TCP-Verbindungen des Systems -- ein Client,
der gerade sein Wurzeldateisystem oder seine Pakete zieht, haelt eine
Verbindung auf Port 80 oder 2049 offen. Genau daran erkennen wir ihn.
"""

from __future__ import annotations

import time
from pathlib import Path

PROC = Path("/proc")

# Port 80 = Kernel, Initrd, Squashfs und Paketdepots ueber nginx.
# Port 2049 = per NFS eingehaengte Live-Systeme.
PORTE = {80: "HTTP", 2049: "NFS"}

# Fuer Werte, die sich nur aus der Differenz zweier Messungen ergeben.
_vorher: dict = {}


def _lies(name: str) -> str:
    try:
        return (PROC / name).read_text(encoding="utf-8")
    except OSError:
        return ""


def last() -> list[float] | None:
    """Lastmittel der letzten 1, 5 und 15 Minuten."""
    roh = _lies("loadavg").split()
    if len(roh) < 3:
        return None
    try:
        return [float(w) for w in roh[:3]]
    except ValueError:
        return None


def kerne() -> int:
    return sum(1 for z in _lies("cpuinfo").splitlines() if z.startswith("processor")) or 1


def cpu() -> int | None:
    """Auslastung in Prozent seit der letzten Abfrage.

    Der Kernel zaehlt nur Zeitscheiben, keine Prozente -- der Wert ergibt
    sich aus der Differenz zweier Messungen. Die erste Abfrage nach dem
    Start hat noch keinen Vergleichswert und liefert deshalb nichts.
    """
    zeile = next((z for z in _lies("stat").splitlines() if z.startswith("cpu ")), "")
    felder = [int(w) for w in zeile.split()[1:] if w.isdigit()]
    if len(felder) < 5:
        return None

    gesamt = sum(felder)
    untaetig = felder[3] + felder[4]          # idle + iowait
    alt = _vorher.get("cpu")
    _vorher["cpu"] = (gesamt, untaetig)
    if alt is None or gesamt <= alt[0]:
        return None

    d_gesamt = gesamt - alt[0]
    d_untaetig = untaetig - alt[1]
    return max(0, min(100, round((d_gesamt - d_untaetig) / d_gesamt * 100)))


def speicher() -> dict:
    werte = {}
    for zeile in _lies("meminfo").splitlines():
        name, _, rest = zeile.partition(":")
        zahl = rest.strip().split(" ")[0]
        if zahl.isdigit():
            werte[name] = int(zahl) * 1024
    gesamt = werte.get("MemTotal", 0)
    frei = werte.get("MemAvailable", werte.get("MemFree", 0))
    if not gesamt:
        return {}
    return {"gesamt": gesamt, "belegt": gesamt - frei,
            "anteil": round((gesamt - frei) / gesamt * 100)}


def netz() -> dict:
    """Durchsatz seit der letzten Abfrage, in Byte je Sekunde.

    Alle Schnittstellen ausser der Rueckschleife zusammen -- die VM hat
    ohnehin nur eine, und so muss hier nichts konfiguriert werden.
    """
    rein = raus = 0
    gefunden = False
    for zeile in _lies("net/dev").splitlines():
        name, _, rest = zeile.partition(":")
        name = name.strip()
        if not rest or name in ("lo", "Inter-|   Receive"):
            continue
        felder = rest.split()
        if len(felder) < 9:
            continue
        gefunden = True
        rein += int(felder[0])
        raus += int(felder[8])
    if not gefunden:
        return {}

    jetzt = time.monotonic()
    alt = _vorher.get("netz")
    _vorher["netz"] = (rein, raus, jetzt)
    if alt is None or jetzt - alt[2] < 0.5 or rein < alt[0]:
        return {}
    dauer = jetzt - alt[2]
    return {"rein": int((rein - alt[0]) / dauer), "raus": int((raus - alt[1]) / dauer)}


def _ip_aus_hex(roh: str) -> str:
    """"0100A8C0:0050" -> "192.168.0.1". Die Bytes stehen verkehrt herum."""
    hexip = roh.split(":")[0]
    if len(hexip) == 8:                              # IPv4
        paare = [hexip[i:i + 2] for i in range(0, 8, 2)]
        return ".".join(str(int(p, 16)) for p in reversed(paare))
    if len(hexip) == 32:                             # IPv4 in IPv6 gekapselt
        letzte = hexip[24:]
        paare = [letzte[i:i + 2] for i in range(0, 8, 2)]
        return ".".join(str(int(p, 16)) for p in reversed(paare))
    return ""


def _port(roh: str) -> int:
    teile = roh.split(":")
    return int(teile[1], 16) if len(teile) == 2 else 0


def arp() -> dict[str, str]:
    """IP-Adresse -> MAC, aus dem ARP-Zwischenspeicher des Kernels.

    Noetig, weil die Adresse, unter der ein Rechner Daten zieht, nicht die
    sein muss, unter der er gebootet hat: iPXE fragt beim Start per DHCP,
    und das danach gestartete Live-System fragt noch einmal selbst. Der
    Router vergibt dabei nicht zwingend dieselbe Adresse. Die MAC bleibt.

    Wer gerade ueberträgt, steht mit Sicherheit im Zwischenspeicher -- man
    kann nicht mit jemandem sprechen, dessen Adresse man nicht kennt.
    """
    tabelle = {}
    for zeile in _lies("net/arp").splitlines()[1:]:
        felder = zeile.split()
        # Flags 0x0 heisst: Eintrag angelegt, aber noch keine Antwort da.
        if len(felder) >= 4 and felder[2] != "0x0":
            mac = felder[3].lower()
            if mac != "00:00:00:00:00:00":
                tabelle[felder[0]] = mac
    return tabelle


def uebertragungen() -> dict[str, set[str]]:
    """Welche Gegenstelle haelt gerade eine Verbindung wohin offen?

    Liefert Gegenstellen-IP -> Menge der Dienste ("HTTP", "NFS"). Gezaehlt
    wird nur, was wirklich steht (ESTABLISHED); wartende und sich gerade
    schliessende Verbindungen bleiben aussen vor.
    """
    aktiv: dict[str, set[str]] = {}
    for datei in ("net/tcp", "net/tcp6"):
        for zeile in _lies(datei).splitlines()[1:]:
            felder = zeile.split()
            if len(felder) < 4 or felder[3] != "01":   # 01 = ESTABLISHED
                continue
            dienst = PORTE.get(_port(felder[1]))
            if not dienst:
                continue
            gegenstelle = _ip_aus_hex(felder[2])
            if gegenstelle and not gegenstelle.startswith("127."):
                aktiv.setdefault(gegenstelle, set()).add(dienst)
    return aktiv

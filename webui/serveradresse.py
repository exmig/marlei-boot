"""
Was der Host gerade an Netz hat -- gelesen, nie geschrieben.

Bis August 2026 stand hier das Gegenteil: ein Pruefer fuer drei Eingaben
und der Befehl, der die Adresse in ``/etc/network/interfaces`` schrieb.
Markus' Entscheidung am 27.08.2026 hat das umgedreht:

    **Die Netzkonfiguration des Hosts ist Sache des Betreibers.**
    Was auf dem Host installiert wird und ob die Voraussetzungen
    erfuellt sind, ist unsere.

Drei Gruende, und der dritte war der Anlass:

1. Es ist nicht unsere Datei. Wer die Netzkonfiguration eines Hosts
   anfasst, muss sie ganz verstehen -- Bonding, VLANs, mehrere Karten,
   eine zweite Route. Davon sehen wir nichts.
2. Es ist der einzige Schritt, der den Server aus dem Netz werfen kann.
   Alles andere ist reparierbar; ein Zahlendreher im Gateway nur an der
   Konsole.
3. Es war die *einzige* Stelle, an der Debian, Ubuntu und Raspberry Pi OS
   wirklich auseinandergehen -- ifupdown, netplan, NetworkManager. Wer sie
   nicht anfasst, laeuft ueberall gleich.

Uebrig bleibt das Ablesen: Welche Adresse hat dieser Host, und stimmt sie
noch mit der ueberein, die beim letzten ``install.sh`` an vier Stellen
festgeschrieben wurde? Weichen sie ab, zeigen alle Boot-Skripte ins Leere
-- und zwar stumm. Genau das soll nicht mehr passieren: Wer die
Verantwortung abgibt, muss wenigstens sagen, wenn die Voraussetzung
weggefallen ist.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shutil
import subprocess


def _ip_befehl(*args: str) -> str:
    """``ip`` aufrufen und die Ausgabe zurueckgeben; leer, wenn es nicht geht.

    Ausgelagert, damit die Tests die Ausgabe echter Systeme einspielen
    koennen, ohne dass hier ein Testschalter steht. Auf einem
    Entwicklungsrechner ohne iproute2 -- Windows zum Beispiel -- gibt es
    schlicht nichts zu lesen, und die Oberflaeche sagt das.
    """
    if not shutil.which("ip"):
        return ""
    try:
        fertig = subprocess.run(["ip", *args], capture_output=True,
                                text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return fertig.stdout if fertig.returncode == 0 else ""


def netzlage(lies=_ip_befehl) -> dict:
    """Karte, Adresse, Maske, Gateway -- und ob die Adresse vom Router kommt.

    Gesucht wird die Karte mit der Standardroute; das ist dieselbe Regel,
    nach der ``install.sh`` die Adresse ermittelt, damit beide dasselbe
    sehen. ``PXE_IFACE`` sticht sie, wie dort auch -- auf einem Host mit
    mehreren Karten weiss nur der Betreiber, welche ins LAN zeigt.

    Nichts davon ist eine Fehlersituation: Ein Host ohne Standardroute ist
    ungewoehnlich, aber moeglich. Deshalb steht in ``fehler``, was nicht
    zu lesen war, statt dass eine Ausnahme fliegt.
    """
    lage = {"karte": "", "ip": "", "praefix": None, "maske": "",
            "gateway": "", "netz": "", "dynamisch": False, "fehler": ""}

    route = lies("-4", "route", "show", "default")
    if not route.strip():
        lage["fehler"] = "Keine Standardroute gefunden."
    else:
        # "default via 192.168.178.1 dev enp0s3 proto dhcp src ... metric 100"
        treffer = re.search(r"\bvia\s+(\S+)", route)
        if treffer:
            lage["gateway"] = treffer.group(1)
        treffer = re.search(r"\bdev\s+(\S+)", route)
        if treffer:
            lage["karte"] = treffer.group(1)

    if os.environ.get("PXE_IFACE"):
        lage["karte"] = os.environ["PXE_IFACE"]

    if not lage["karte"]:
        if not lage["fehler"]:
            lage["fehler"] = "Keine Netzwerkkarte gefunden."
        return lage

    adressen = lies("-4", "-o", "addr", "show", "dev", lage["karte"])
    if not adressen.strip():
        lage["fehler"] = f"Auf {lage['karte']} liegt keine IPv4-Adresse."
        return lage

    # "2: enp0s3    inet 192.168.178.30/24 brd ... scope global dynamic enp0s3"
    # Genommen wird die erste Adresse mit "scope global": Eine zweite auf
    # derselben Karte kaeme aus einem Alias, und die Boot-Skripte tragen
    # ohnehin nur eine.
    for zeile in adressen.splitlines():
        treffer = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", zeile)
        if not treffer or "scope global" not in zeile:
            continue
        lage["ip"] = treffer.group(1)
        lage["praefix"] = int(treffer.group(2))
        # Der Kernel schreibt "dynamic" an eine bezogene Adresse. Er kann
        # dabei NICHT unterscheiden, ob der Router sie diesem Host
        # reserviert hat -- beides sieht gleich aus. Deshalb heisst das
        # Feld "dynamisch" und nicht "unsicher": Es sagt, woher die
        # Adresse kommt, nicht ob sie taugt.
        lage["dynamisch"] = bool(re.search(r"\bdynamic\b", zeile))
        netz = ipaddress.IPv4Network(f"{lage['ip']}/{lage['praefix']}",
                                     strict=False)
        lage["maske"] = str(netz.netmask)
        lage["netz"] = netz.with_prefixlen
        break
    else:
        lage["fehler"] = f"Auf {lage['karte']} liegt keine IPv4-Adresse."

    return lage


def abweichung(eingerichtet: str, lage: dict) -> str:
    """Laeuft dieser Server unter einer anderen Adresse als der eingetragenen?

    Gibt die tatsaechliche Adresse zurueck, wenn sie abweicht -- sonst "".
    Ist nichts zu lesen, gilt das ausdruecklich **nicht** als Abweichung:
    Aus "wir wissen es nicht" einen Befund zu machen hiesse, auf jedem
    Entwicklungsrechner einen Fehlalarm auszuloesen. Ein Befund, der oefter
    falsch als richtig ist, wird nach einer Woche ueberlesen.
    """
    if not eingerichtet or not lage.get("ip") or lage.get("fehler"):
        return ""
    # Steht in PXE_BASE_URL ein Name statt einer Adresse -- "bootsrv" oder
    # "pxe.intern" --, gibt es hier nichts zu vergleichen. Wer einen Namen
    # eintraegt, hat sich fuer eine Ebene entschieden, auf der der Wechsel
    # einer Adresse gerade keine Rolle spielt; ihn deswegen zu warnen waere
    # ein Dauerbefund fuer den ordentlichsten Aufbau von allen.
    try:
        ipaddress.IPv4Address(eingerichtet)
    except ipaddress.AddressValueError:
        return ""
    return lage["ip"] if lage["ip"] != eingerichtet else ""

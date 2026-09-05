"""
Die lokale Firewall: gemeldet, nicht angefasst.

**Der Bootserver richtet keine Firewall ein.** Sie gehoert der Maschine,
auf der er laeuft, und damit dem Betreiber -- dieselbe Grenze wie bei der
Netzkonfiguration, die diese Anwendung ebenfalls nur abliest. Ein Werkzeug,
das ungefragt Regeln auf einer fremden Maschine setzt, ist das, wovor man
Werkzeuge sonst warnt; und `ufw enable` ueber eine SSH-Sitzung sperrt aus,
wer 22 vergisst.

**Was bleibt, ist der blinde Fleck.** Eine Firewall bringt den Netzstart
lautlos zum Schweigen: dnsmasq antwortet weiter, der Server sieht kerngesund
aus, und beim bootenden Rechner kommt nichts an. Deshalb sagt die Oberflaeche
wenigstens, DASS eine laeuft -- und welche Ports der Bootweg braucht.

**Gemeldet wird, nicht geprueft, und das hat einen technischen Grund.** Diese
Anwendung laeuft als Benutzer ``pxeweb`` mit ``NoNewPrivileges=yes``; ``sudo``
gibt es dort nicht, und das ist Absicht. Ohne root ist zu erfahren:

    ob eine Firewall installiert ist      ja
    ob sie eingeschaltet ist              ja
    ob sie 69/udp durchlaesst             NEIN -- die Regeln liegen root-only

Die Karte sagt das auch. Ein Kasten, der aussieht, als haette er geprueft,
waere schlimmer als einer, der sagt, was er nicht weiss.

**Die Falle beim Fragen:** ``systemctl is-active ufw`` meldet ``active``,
auch wenn die Firewall abgeschaltet ist -- die Unit laeuft dann als leerer
Rahmen. Gefragt wird deshalb ``/etc/ufw/ufw.conf`` nach ``ENABLED``; das ist
die Datei, die ``ufw enable`` schreibt, und sie ist ohne root lesbar.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Die Datei, die "ufw enable" umschreibt. Ueber die Umgebung zu setzen,
# damit der Test nicht auf ein echtes ufw angewiesen ist.
UFW_CONF = Path(os.environ.get("PXE_UFW_CONF", "") or "/etc/ufw/ufw.conf")

# Die anderen beiden fragt man ueber systemd. Bei ihnen gibt es die Falle
# von ufw nicht: Laeuft die Unit, ist ein Regelwerk geladen.
UEBER_SYSTEMD = ("nftables", "firewalld")

ZEITLIMIT = 5.0

_ENABLED = re.compile(r"^\s*ENABLED\s*=\s*(\w+)", re.M | re.I)

# --------------------------------------------------------------------------
# Was der Bootweg braucht
# --------------------------------------------------------------------------
#
# **Reine Auskunft, keine Pruefung.** Der Server sagt, worauf seine Dienste
# hoeren; ob die Firewall es durchlaesst, sieht nur der Betreiber.
#
# Abgelesen an einer laufenden Maschine (dev-marlei, 05.09.2026) und nicht
# aus dem Kopf geschrieben -- zwei Angaben waeren sonst falsch gewesen:
# Samba hoert nicht nur auf 445, und NFS bringt bewegliche Ports mit.
PORTS = (
    {"port": "67/udp", "dienst": "dnsmasq",
     "wofuer": "proxyDHCP — die Antwort auf die Bootanfrage"},
    {"port": "4011/udp", "dienst": "dnsmasq",
     "wofuer": "proxyDHCP, der zweite Weg (PXE-Redirection)"},
    {"port": "69/udp", "dienst": "dnsmasq",
     "wofuer": "TFTP — darüber geht ausschließlich der iPXE-Bootloader"},
    {"port": "80/tcp", "dienst": "nginx",
     "wofuer": "Kernel, Initrd, Abbilder — und diese Oberfläche"},
    {"port": "111/tcp+udp", "dienst": "rpcbind",
     "wofuer": "der Portmapper, den NFSv3 vorschaltet"},
    {"port": "2049/tcp", "dienst": "nfs-server",
     "wofuer": "NFS — große Live-Systeme werden von hier gestreamt"},
    {"port": "445/tcp", "dienst": "smbd",
     "wofuer": "die Windows-Installationsquellen"},
    {"port": "139/tcp · 137, 138/udp", "dienst": "smbd",
     "wofuer": "NetBIOS — ältere Windows-Fassungen suchen die Freigabe darüber"},
    {"port": "22/tcp", "dienst": "sshd",
     "wofuer": "gehört nicht zum Bootweg — aber wer ihn zumacht, während er "
               "über ihn angemeldet ist, sperrt sich aus"},
)

# Der Satz, den eine Portliste allein nicht sagt und der teuer wird, wenn
# ihn niemand sagt.
NFS_HINWEIS = (
    "NFSv3 hört nicht nur auf 111 und 2049: mountd, statd und nlockmgr "
    "bekommen bei jedem Start neue, zufällige Portnummern. Eine Regel, die "
    "nur die beiden bekannten öffnet, lässt große Live-Systeme trotzdem "
    "scheitern. Entweder die Ports in /etc/nfs.conf festnageln — oder dem "
    "eigenen Subnetz insgesamt erlauben, was dieser Server ohnehin nur "
    "lesend exportiert."
)

# Und der Port, der ausdruecklich NICHT offen gehoert.
NICHT_OEFFNEN = (
    "8080/tcp gehört nicht dazu. Dort hört die Anwendung selbst, aber nur "
    "auf 127.0.0.1 — von außen kommt man über nginx auf 80, und dabei soll "
    "es bleiben."
)


def _ufw() -> dict | None:
    """Ist ufw da, und steht es auf an?"""
    try:
        text = UFW_CONF.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    treffer = _ENABLED.search(text)
    return {"name": "ufw",
            "an": bool(treffer) and treffer.group(1).lower() == "yes"}


def _systemd(namen: tuple) -> list:
    """Welche der genannten Einheiten laufen -- in einem Aufruf."""
    try:
        lauf = subprocess.run(
            ["systemctl", "is-active", *namen],
            capture_output=True, text=True, timeout=ZEITLIMIT, check=False)
    except (OSError, subprocess.SubprocessError):
        # Kein systemd erreichbar -- etwa beim Entwickeln auf einem anderen
        # System. Dann lieber schweigen als etwas behaupten.
        return []
    zeilen = lauf.stdout.split()
    gefunden = []
    for i, name in enumerate(namen):
        zustand = zeilen[i] if i < len(zeilen) else "unknown"
        # "inactive" heisst: es gibt die Unit, sie laeuft nicht.
        # "unknown"/"failed" heisst hier: nicht installiert -- dann steht
        # sie gar nicht erst in der Liste, denn ein Eintrag "firewalld:
        # nicht vorhanden" ist keine Auskunft, sondern Fuellmaterial.
        if zustand in ("active", "inactive"):
            gefunden.append({"name": name, "an": zustand == "active"})
    return gefunden


def lage() -> dict:
    """Was diese Maschine an Firewall hat -- soweit es ohne root zu sehen ist.

    ``gefunden`` sind die installierten, jede mit ``an``. ``aktiv`` ist wahr,
    sobald eine davon eingeschaltet ist; ``namen`` nennt die eingeschalteten
    fuer die eine Zeile unter den Diensten.
    """
    gefunden = [f for f in (_ufw(),) if f] + _systemd(UEBER_SYSTEMD)
    laufende = [f["name"] for f in gefunden if f["an"]]
    return {
        "gefunden": gefunden,
        "aktiv": bool(laufende),
        "namen": laufende,
        # Wovon die Auskunft stammt -- damit auf der Karte steht, woher sie
        # kommt, und niemand sie fuer eine Pruefung haelt.
        "quelle": str(UFW_CONF),
    }

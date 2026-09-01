"""
Wake-on-LAN -- schlafende Rechner ueber das Netz einschalten.

Ein "Magic Packet" ist ein UDP-Paket, dessen Nutzdaten aus sechs 0xFF-Bytes
und der sechzehnmal wiederholten MAC-Adresse des Zielrechners bestehen. Die
Netzwerkkarte eines ausgeschalteten Rechners liest im Standby weiter mit und
schaltet ein, sobald sie genau dieses Muster mit ihrer eigenen Adresse sieht.

Warum ein Rundruf? Der Zielrechner ist aus und hat deshalb keine IP-Adresse
-- man kann ihn nicht direkt adressieren. Das Paket geht an die Rundrufadresse
des Netzes, alle hoeren es, aber nur die passende Karte reagiert darauf.

Der Rundruf verlaesst den Router nicht: Wecken funktioniert nur innerhalb des
eigenen LAN-Segments, in dem auch der PXE-Server steht.
"""

from __future__ import annotations

import os
import re
import socket

# Rundrufadresse. "255.255.255.255" geht ueber die Standardroute hinaus und
# tut es meistens; die gerichtete Adresse des eigenen Netzes (z. B.
# 192.168.178.255) ist zuverlaessiger, weil sie eindeutig auf dem LAN-
# Interface landet. install.sh traegt sie beim Einrichten passend ein.
BROADCAST = os.environ.get("PXE_WOL_BROADCAST", "").strip() or "255.255.255.255"

# Port 9 (discard) ist ueblich, manche aeltere Karten lauschen auf 7 (echo).
# Beides zu bedienen kostet nichts -- das Paket ist 102 Byte gross.
PORTS = tuple(
    int(p) for p in os.environ.get("PXE_WOL_PORTS", "9,7").replace(" ", "").split(",") if p
)

# UDP kennt keine Empfangsbestaetigung. Ein verlorenes Paket faellt niemandem
# auf, der Rechner bleibt einfach aus -- deshalb schicken wir es mehrfach.
WIEDERHOLUNGEN = 3

_MAC_ZEICHEN = re.compile(r"[^0-9a-fA-F]")


def magic_packet(mac: str) -> bytes:
    """Baut das Weckpaket fuer eine MAC-Adresse.

    Trennzeichen sind egal -- 'aa:bb:cc:dd:ee:ff', 'aa-bb-...' und
    'aabbccddeeff' ergeben dasselbe Paket.
    """
    roh = _MAC_ZEICHEN.sub("", mac)
    if len(roh) != 12:
        raise ValueError("Keine MAC-Adresse: " + mac)
    return b"\xff" * 6 + bytes.fromhex(roh) * 16


def wecken(mac: str, ziel: str | None = None) -> list[str]:
    """Schickt das Weckpaket und meldet zurueck, wohin es ging.

    Wirft ValueError bei kaputter MAC und OSError, wenn das Netz nicht
    mitspielt. Ein Erfolg heisst nur "abgeschickt": ob der Rechner wirklich
    angeht, laesst sich von hier aus nicht feststellen.
    """
    paket = magic_packet(mac)
    adresse = (ziel or BROADCAST).strip() or "255.255.255.255"

    gesendet = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in PORTS:
            for _ in range(WIEDERHOLUNGEN):
                sock.sendto(paket, (adresse, port))
            gesendet.append(f"{adresse}:{port}")
    return gesendet

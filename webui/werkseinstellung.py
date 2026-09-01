"""
Zurueck auf den Auslieferungszustand -- alles weg, was jemand hier
hingelegt hat.

Wozu das gut ist: Ein Server, der eine Weile gelaufen ist, traegt lauter
Entscheidungen mit sich herum -- geholte Abbilder, hochgeladene ISOs,
angemeldete Rechner, eigene Adressen, eine Reihenfolge der Gruppen. Wer
ihn weitergibt oder von vorn anfangen will, muesste das auf der Konsole
einzeln wegraeumen und dabei genau wissen, was wo liegt.

**Was geloescht wird**, ist deshalb genau das, was jemand hier abgelegt
hat: die Abbilder unter /srv/pxe/assets und der gemerkte Zustand neben der
Datenbank.

**Was bleibt**, ist die Einrichtung des Servers selbst:

- ``/etc/pxeweb.env`` -- dort steht, wer dieser Server ist (seine Adresse,
  sein NFS-Pfad). Die Anwendung kann die Datei ohnehin nicht schreiben:
  systemd gibt ihr nur /var/lib/pxeweb und /srv/pxe/assets frei. Ein Reset,
  der die Identitaet des Servers mitnimmt, waere kein Reset, sondern ein
  Ausfall.
- ``wimboot/`` unter den Abbildern -- das holt install.sh beim Aufsetzen,
  es ist Teil der Installation und nicht der Ablage. Ein frisch
  aufgesetzter Server hat es.
- ``upload/`` als leerer Ordner -- ebenso von install.sh angelegt.
- Der Katalog, die Vorlagen, das Skript: alles im Projektordner.

Gearbeitet wird ohne root und ohne Skript. Die Anwendung laeuft als
Benutzer pxeweb mit ``NoNewPrivileges=yes``; sudo gaebe es hier gar nicht.
Sie darf genau die zwei Pfade schreiben, um die es geht -- mehr braucht
dieser Vorgang nicht, und mehr soll er auch nicht koennen.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

# Das Wort, das jemand tippen muss. Es steht hier und nicht in der Vorlage:
# Der Server prueft es, nicht der Browser -- eine Bestaetigung, die nur im
# JavaScript stattfindet, ist keine.
LOSUNG = "Löschen"

# Was neben der Datenbank liegt und gemerkter Zustand ist. Ausgeschrieben
# und nicht "alles im Verzeichnis": Wer spaeter eine Datei dazulegt, soll
# sich ueberlegen muessen, ob sie ein Reset ueberleben soll. Eine Schleife
# ueber das ganze Verzeichnis entscheidet das stillschweigend mit.
ZUSTAND = (
    "quellen.env",           # eigene Adressen und Ausgabenlisten
    "quellenstand.yaml",     # die Ampeln der Quellen-Karten
    "quellenwacht.yaml",     # der letzte Lauf des Waechters
    "freigabe.yaml",         # was im Bootmenue angeboten wird
    "gruppen.yaml",          # Reihenfolge der Gruppen
    "namen.yaml",            # eigene Namen fuer Menueeintraege
    "logs",                  # Installationsprotokolle (ein Verzeichnis)
)

# Was unter den Abbildern zur Installation gehoert und nicht zur Ablage.
BEHALTEN = ("wimboot", "upload")


def _weg(pfad: Path) -> int:
    """Loeschen und sagen, ob wirklich etwas weg ist."""
    try:
        if pfad.is_dir() and not pfad.is_symlink():
            shutil.rmtree(pfad)
        elif pfad.exists() or pfad.is_symlink():
            pfad.unlink()
        else:
            return 0
    except OSError:
        # Ein Rest, den wir nicht loswerden, haelt den Vorgang nicht auf:
        # Die Meldung sagt hinterher, was blieb, und das ist ehrlicher als
        # ein Abbruch auf halbem Weg.
        return 0
    return 1


def _datenbank_leeren(db: Path) -> bool:
    """Alle Zeilen aus allen Tabellen -- der Rueckfallweg.

    Die Datei zu loeschen ist der geradere Weg, aber er gelingt nicht
    immer: Eine offene Verbindung sperrt sie auf manchen Systemen, und
    dann bliebe die Rechnerliste stehen, waehrend die Meldung
    "zurueckgesetzt" sagt. Das Ziel ist "keine Daten", nicht "keine
    Datei" -- also wird geleert, was sich nicht wegraeumen liess.

    Die Tabellen werden dabei nicht geworfen, nur ausgeraeumt: Das Schema
    soll stehen bleiben, damit der Server weiterlaeuft, ohne dass jemand
    ihn neu startet.
    """
    try:
        with sqlite3.connect(db) as conn:
            tabellen = [z[0] for z in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")]
            for name in tabellen:
                conn.execute(f'DELETE FROM "{name}"')
        return True
    except sqlite3.Error:
        return False


def zuruecksetzen(assets: Path, daten: Path, db: Path | None = None) -> dict:
    """Alles wegraeumen, was jemand abgelegt hat. Gibt zurueck, was fiel.

    Die Datenbank wird ueber ihren Pfad angesprochen und nicht ueber einen
    Namen in ZUSTAND: Wie sie heisst, steht in PXE_DB und ist nicht
    festgelegt. Ein fester Name hier hiesse, dass ein Server mit eigenem
    Pfad seine Rechnerliste behaelt, waehrend die Meldung "zurueckgesetzt"
    sagt -- der Test hat genau das gefunden.
    """
    abbilder, zustand, geblieben = [], [], []

    if assets.is_dir():
        for eintrag in sorted(assets.iterdir()):
            if eintrag.name in BEHALTEN:
                # Der Upload-Ordner bleibt als Ordner, sein Inhalt nicht.
                if eintrag.name == "upload" and eintrag.is_dir():
                    for darin in sorted(eintrag.iterdir()):
                        if _weg(darin):
                            abbilder.append("upload/" + darin.name)
                        else:
                            geblieben.append("upload/" + darin.name)
                continue
            if _weg(eintrag):
                abbilder.append(eintrag.name)
            else:
                geblieben.append(eintrag.name)

    # Die Datenbank samt ihren Beiwagen: SQLite legt neben der Datei je
    # nach Betriebsart ein -wal und ein -shm an. Bleiben die liegen,
    # traegt die neue Datenbank Reste der alten.
    if db is not None:
        for anhang in ("", "-wal", "-shm"):
            ziel = db.with_name(db.name + anhang)
            if not ziel.exists():
                continue
            if _weg(ziel):
                zustand.append(ziel.name)
            elif ziel == db and _datenbank_leeren(db):
                # Die Datei blieb, ihr Inhalt nicht. Fuer den Betreiber ist
                # das dasselbe Ergebnis, deshalb steht sie hier und nicht
                # unter "geblieben".
                zustand.append(ziel.name + " (geleert)")
            else:
                geblieben.append(ziel.name)

    for name in ZUSTAND:
        ziel = daten / name
        if not ziel.exists():
            continue
        if _weg(ziel):
            zustand.append(name)
        else:
            geblieben.append(name)

    # Den Upload-Ordner wieder anlegen, falls er gar nicht da war --
    # install.sh legt ihn beim Aufsetzen an, und die Anwendung erwartet ihn.
    try:
        (assets / "upload").mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    return {"abbilder": abbilder, "zustand": zustand, "geblieben": geblieben}


def gepruefte_losung(eingabe: str) -> bool:
    """Stimmt das getippte Wort?

    Grosskleinschreibung zaehlt nicht, Leerzeichen davor und dahinter auch
    nicht, und "loeschen" gilt wie "löschen" -- an einer Tastatur ohne
    Umlaute soll niemand scheitern. Wer eines davon tippt, hat verstanden,
    worum es geht.

    Ein leeres Feld genuegt nie, und das ist der ganze Sinn des Schrittes:
    Das Eingabefeld steht deshalb leer da und traegt das Wort nur als
    grauen Hinweis. Waere es vorbelegt, genuegte ein Druck auf die
    Eingabetaste -- dann koennte man die Abfrage auch weglassen.
    """
    def schlicht(wort: str) -> str:
        for um, ersatz in (("ö", "oe"), ("ä", "ae"), ("ü", "ue"), ("ß", "ss")):
            wort = wort.replace(um, ersatz)
        return wort

    if not eingabe:
        return False
    return schlicht(eingabe.strip().casefold()) == schlicht(LOSUNG.casefold())


def wo() -> tuple[Path, Path]:
    """Die zwei Pfade, um die es geht -- dieselben wie in der Anwendung."""
    assets = Path(os.environ.get("PXE_ASSETS", "/srv/pxe/assets"))
    daten = Path(os.environ.get("PXE_DB", "/var/lib/pxeweb/pxeweb.db")).parent
    return assets, daten

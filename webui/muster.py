"""
Aus einer eingefuegten Adresse ein Ausgabenmuster machen.

Die mitgelieferten Katalogeintraege haben eines: In DEBIAN_URL und den
anderen steht {version}, und daraus baut der Server die Adresse jeder
Ausgabe. Selbst angelegte Eintraege haben bisher keines -- sie tragen eine
feste Adresse, eine Ausgabe, fertig.

**Warum das nicht einfach ein weiteres Eingabefeld wird:** Wer "{version}"
von Hand eintippen muss, muss zuerst verstehen, was das ist, und tippt es
dann an der falschen Stelle ein. Der Fehler faellt nicht beim Eintippen
auf, sondern Wochen spaeter an einer Adresse, die ins Leere zeigt.

Stattdessen fuegt man die Adresse ein, die man ohnehin im Browser offen
hat -- eine echte, die funktioniert. Dieses Modul sucht darin die Ausgabe
und schlaegt das Muster vor. Bewiesen wird der Vorschlag erst danach, beim
Nachsehen wo die Ausgaben liegen: Findet er die Nachbarn, stimmt er.
Bestaetigen statt verstehen.

**Was hier nicht passiert:** Es wird nichts geraten, wo nichts zu erkennen
ist. Debians Netz-Installer liegt unter "dists/trixie/" -- ein Wort, keine
Nummer. Dann kommt hier nichts heraus, und das ist richtig so: Ein falsch
geratenes Muster ist schlimmer als gar keines.
"""

from __future__ import annotations

import re

# Zuerst unschaedlich gemacht, sonst gilt die 64 aus "x86_64" als Ausgabe.
# Nur Architekturen, und nur die, die wirklich in Adressen vorkommen --
# eine lange Liste waere eine lange Liste von Vermutungen.
ARCHITEKTUREN = ("x86_64", "aarch64", "ppc64le", "amd64", "arm64", "i686",
                 "i386", "s390x", "riscv64", "x64")

# Eine Ausgabe faengt mit einer Ziffer an und besteht aus Ziffern, Punkten
# und angehaengten Bindestrich-Zahlen: 44, 26.04, 13.6.0, 1.8.1-3.
#
# Davor und dahinter darf kein Buchstabe und keine Ziffer stehen. Das
# trennt die Ausgabe vom Rest des Dateinamens -- in "mt86plus_8.10" ist
# die 86 keine, weil ein "t" davorsteht, die 8.10 aber schon.
#
# Ein einzelnes "v" davor darf sein und gehoert NICHT zur Ausgabe:
# Memtest legt seine Ausgaben unter "v8.10/" ab, traegt die Nummer im
# Dateinamen daneben aber ohne v. Das Muster muss deshalb "v{version}"
# werden -- stuende das v mit in der Ausgabe, passte die andere Stelle
# nicht mehr. Dieselbe Regel kennt quellen.neuere_ausgaben() beim Lesen
# des Verzeichnisindex.
_AUSGABE = re.compile(r"(?<![0-9A-Za-z])[vV]?(\d[\d.]*(?:-\d+)*)(?![0-9A-Za-z])")


# Schema, Rechnername und Port. Dort steht nie eine Ausgabe, dafuer oft
# etwas, das wie eine aussieht: "http://192.168.178.30:8080/..." hat mit
# der IP und dem Port gleich zwei Kandidaten, und ein Spiegel im eigenen
# Netz ist bei diesem Server alles andere als abwegig.
_ANFANG = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://[^/]*")


def _maskiert(url: str) -> str:
    """Alles unschaedlich machen, was keine Ausgabe sein kann.

    Ersetzt wird durch gleich lange Platzhalter, damit die gefundenen
    Stellen weiter auf die echte Adresse passen -- gesucht wird in der
    Maske, ersetzt wird im Original.
    """
    maske = _ANFANG.sub(lambda t: "#" * len(t.group(0)), url, count=1)
    for wort in ARCHITEKTUREN:
        maske = re.sub(wort, "#" * len(wort), maske, flags=re.I)
    return maske


def _saeubern(wert: str) -> str:
    """Punkte und Bindestriche am Rand gehoeren nicht zur Ausgabe."""
    return wert.strip(".-")


def _stellen(url: str, version: str) -> list[int]:
    """Wo diese Ausgabe ueberall steht -- als Anfangsstellen."""
    maske = _maskiert(url)
    return [t.start(1) for t in _AUSGABE.finditer(maske)
            if _saeubern(t.group(1)) == version]


def _ganzer_abschnitt(url: str, stelle: int, version: str) -> bool:
    """Steht die Ausgabe allein zwischen zwei Schraegstrichen?

    "/releases/44/Everything/" ist ein deutlicheres Zeichen als eine Zahl
    irgendwo in einem Dateinamen.
    """
    davor = url[:stelle]
    danach = url[stelle + len(version):]
    return davor.endswith("/") and (danach.startswith("/") or not danach)


def kandidaten(url: str) -> list[dict]:
    """Was in dieser Adresse eine Ausgabe sein koennte -- bester zuerst.

    Mehrere, nicht einer: In einer Adresse steht selten nur eine Zahl, und
    welche die Ausgabe ist, weiss der Mensch davor sicherer als jede Regel.
    Die Oberflaeche zeigt deshalb den besten Vorschlag und daneben die
    anderen -- statt einen zu behaupten.

    Jeder Vorschlag bringt mit, woran er erkannt wurde. Das ist die
    eigentliche Erklaerung: "kommt zweimal vor" sagt mehr ueber die
    Verlaesslichkeit als jede Punktzahl.
    """
    url = url.strip()
    if not url:
        return []
    maske = _maskiert(url)

    gesehen: dict[str, list[int]] = {}
    for treffer in _AUSGABE.finditer(maske):
        wert = _saeubern(treffer.group(1))
        if not wert or not wert[0].isdigit():
            continue
        gesehen.setdefault(wert, []).append(treffer.start(1))

    vorschlaege = []
    for wert, stellen in gesehen.items():
        punkte, warum = 0, []
        if len(stellen) > 1:
            # Das staerkste Zeichen: Wer zweimal dieselbe Zahl in eine
            # Adresse schreibt, meint die Ausgabe -- einmal im Verzeichnis,
            # einmal im Dateinamen.
            punkte += 3
            warum.append(f"kommt {len(stellen)}-mal vor")
        if "." in wert:
            punkte += 2
            warum.append("hat eine Unternummer")
        if any(_ganzer_abschnitt(url, s, wert) for s in stellen):
            punkte += 2
            warum.append("steht allein als Pfadabschnitt")
        if punkte == 0:
            # Eine nackte kleine Zahl mitten in einem Dateinamen. Kann die
            # Ausgabe sein, ist aber oft eine Variante ("-2", "rev3").
            warum.append("nur eine Zahl im Namen")

        vorschlaege.append({
            "version": wert,
            "muster": _muster_mit(url, wert),
            "stellen": len(stellen),
            "punkte": punkte,
            "warum": ", ".join(warum),
        })

    # Bei Gleichstand die laengere Angabe zuerst: "13.6.0" ist eine
    # genauere Ausgabe als "13", und wer eine Adresse einfuegt, meint
    # meistens die genaue.
    vorschlaege.sort(key=lambda v: (v["punkte"], len(v["version"])), reverse=True)
    return vorschlaege


def _muster_mit(url: str, version: str) -> str:
    """Alle Vorkommen dieser Ausgabe durch {version} ersetzen.

    Alle, nicht nur das erste: Bei Ubuntu steht die Nummer im Verzeichnis
    UND im Dateinamen. Wuerde nur eines ersetzt, ergaebe das Muster fuer
    jede andere Ausgabe eine Adresse, die es nicht gibt.

    Ersetzt wird ueber die Stellen aus der Maske und nicht mit einem
    einfachen replace: Sonst wuerde in "x86_64" die 64 mitgenommen, wenn
    die Ausgabe zufaellig "64" heisst.
    """
    stellen = _stellen(url, version)
    if not stellen:
        return url
    stueck, zuletzt = [], 0
    for stelle in stellen:
        stueck.append(url[zuletzt:stelle])
        stueck.append("{version}")
        zuletzt = stelle + len(version)
    stueck.append(url[zuletzt:])
    return "".join(stueck)


def erkenne(url: str) -> dict | None:
    """Der beste Vorschlag -- oder nichts, wenn keiner taugt."""
    alle = kandidaten(url)
    return alle[0] if alle else None

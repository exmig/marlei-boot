"""
Befunde, die dem Server gelten -- und nicht einer einzelnen Karte.

Es gibt Zustaende, die keiner Seite gehoeren. Dass dieser Server unter
einer anderen Adresse laeuft als der eingerichteten, ist keine Auslastung,
kein Dienst und kein Speicherplatz -- es ist die Voraussetzung, unter der
alle drei ueberhaupt etwas bedeuten. Ein solcher Befund stand bisher als
Absatz auf zwei Seiten, und auf den drei anderen stand er nirgends: Wer
unter *Clients* eine Installation zuwies, sah nichts und wunderte sich
hinterher, warum der Rechner nichts findet.

Deshalb entstehen die Befunde hier, an einer Stelle, und ``_rahmen()``
gibt sie jeder Seite mit. Dargestellt werden sie in ``base.html`` als
Seitenkarten unterhalb der Reiter.

**Drei Stufen, eine Ampel** (siehe docs/gestaltung.md, "Die Karte und
ihre drei Bereiche"). Welche
Stufe gilt, haengt nicht daran, wie schlimm etwas klingt, sondern daran,
*wann jemand handeln muss*:

    fehler    Der Server erfuellt seine Aufgabe nicht -- jetzt handeln.
    warnung   Eingeschraenkt oder darauf zulaufend -- bald handeln.
    info      Wissenswert; niemand muss deswegen aufstehen.

Die mittlere Stufe hiess bis zum 28.08.2026 nur "laeuft auf einen roten
Zustand zu". Beim Durchgang durch die Oberflaeche fiel auf, dass damit ein
ganzer Fall herausfaellt: Ein ausgefallener nfs-server laeuft auf gar
nichts zu -- er ist bereits kaputt, nur eben nicht ganz. Markus' Regel
seitdem: **Gelb heisst Achtung, nicht Halt** -- eingeschraenkt zaehlt
genauso wie zulaufend.

Ohne diese Grenzen bekaeme jede Warnung eine rote Karte, und Rot hiesse
nach zwei Wochen nichts mehr.

Was hier steht, ist die *Entscheidung*: ob ein Befund gilt, welche Stufe
er hat, und mit welchem Satz er zugeklappt dasteht. Die Erklaerung
darunter steht in ``templates/befunde/<kennung>.html``, dort, wo aller
andere Text der Oberflaeche auch steht.
"""

from __future__ import annotations

import time

import dienste
import serveradresse

# Die Reihenfolge, in der die Karten stehen, wenn mehrere gleichzeitig
# gelten: dringend zuerst, von oben nach unten.
STUFEN = ("fehler", "warnung", "info")

# Welche Dienste den Bootweg tragen. Faellt einer davon aus, kommt kein
# Rechner mehr durch -- egal welcher:
#
#   nginx     liefert Kernel und Initrd aus
#   dnsmasq   beantwortet die PXE-Anfrage und liefert iPXE per TFTP
#   pxeweb    erzeugt boot.ipxe und menu.ipxe
#
# Dass man pxeweb und nginx im Ausfall kaum je zu sehen bekommt -- ohne
# sie gibt es keine Seite, auf der eine Karte stehen koennte --, ist kein
# Grund, sie hier auszulassen: Wer sie herausnimmt, verlaesst sich darauf,
# dass zwei Dinge immer zugleich ausfallen.
BOOTDIENSTE = ("nginx", "dnsmasq", "pxeweb")

# Und welcher nur einen Teil traegt. Ohne NFS starten die grossen
# Live-Systeme nicht; alles andere laeuft weiter. Das ist der Fall, fuer
# den die mittlere Stufe erweitert wurde.
TEILDIENSTE = ("nfs-server",)

# Wie lange die abgelesene Netzlage gilt, in Sekunden.
#
# ``netzlage()`` ruft zweimal "ip" auf. Das ist billig, aber nicht umsonst,
# und es geschieht jetzt beim Aufbau *jeder* Seite statt wie bisher nur auf
# zweien. Zehn Sekunden sind lang genug, dass ein Klick durch die Reiter
# nur einmal nachsieht, und kurz genug, dass niemand auf einen alten Stand
# schaut: Wer die Adresse des Hosts aendert, tut das an der Konsole und
# braucht dafuer laenger.
#
# Bewusst nicht laenger: Ein zwischengespeicherter Befund, der veraltet,
# waere genau das, was diese Oberflaeche sonst vermeidet.
NETZ_TAKT = 10.0

_netz_stand: dict = {"zeit": 0.0, "lage": None}


def _netzlage_gepuffert() -> dict:
    """Die Netzlage, hoechstens alle NETZ_TAKT Sekunden frisch gelesen.

    Nur fuer diesen Befund. Die Karte *IP-Adresse uebernehmen* unter
    Einrichtung liest weiterhin selbst und ungepuffert -- dort sieht
    jemand gerade nach, was der Host hat, und bekommt die Antwort auf
    genau diese Frage, nicht die von vor zehn Sekunden.
    """
    jetzt = time.monotonic()
    if _netz_stand["lage"] is None or jetzt - _netz_stand["zeit"] >= NETZ_TAKT:
        _netz_stand["lage"] = serveradresse.netzlage()
        _netz_stand["zeit"] = jetzt
    return _netz_stand["lage"]


def vergiss() -> None:
    """Den gepufferten Stand wegwerfen.

    Fuer die Tests, und fuer den Fall, dass eine Aenderung an der
    Einrichtung sofort sichtbar sein soll.
    """
    _netz_stand["zeit"] = 0.0
    _netz_stand["lage"] = None


def sortiert(befunde: list[dict]) -> list[dict]:
    """Nach Stufe ordnen: Fehler, Warnung, Info.

    ``STUFEN.index`` laesst einen Tippfehler in der Stufe auffliegen,
    statt die Karte still an die falsche Stelle zu setzen. Die Befunde
    entstehen hier im Code, nicht aus Benutzereingaben -- ein Fehler an
    dieser Stelle ist einer von uns und soll laut sein.
    """
    return sorted(befunde, key=lambda b: STUFEN.index(b["stufe"]))


def sammeln(eingerichtete_ip: str, assets_dir=None,
            netzlage=_netzlage_gepuffert, zustaende=None, platz=None) -> list[dict]:
    """Alle Befunde, die gerade gelten -- geordnet, oben der dringendste.

    Jeder Befund traegt:

        stufe      fehler | warnung | info
        kennung    heisst auch die Vorlage: templates/befunde/<kennung>.html
        titel      der Satz, der zugeklappt dasteht
        marke      eine Zahl, die NUR steigt, wenn es schlimmer wird
        ...        was die Vorlage sonst noch braucht

    Die Marke traegt das Wegklicken: Wer eine Warnung zur Kenntnis nimmt,
    speichert sie mit, und die Karte kommt erst zurueck, wenn die Marke
    darueber liegt. Sie muss deshalb grob sein -- eine Belegung, die bei
    jedem Prozentpunkt eine neue Marke bekaeme, waere kein Wegklicken,
    sondern ein Aufschub um Minuten. Siehe kenntnis.py.

    Der Titel nennt die **Folge**, nicht den Vorgang: Zugeklappt ist er
    das Einzige, was jemand sieht, und "Die Adresse hat sich geaendert"
    sagt nicht, was daran schlimm ist. Wo die Folge von etwas abhaengt,
    das wir nicht wissen -- wie gross das naechste Abbild ist --, nennt er
    den Zustand; behaupten ist schlimmer als beschreiben.

    ``zustaende`` und ``platz`` sind fuer die Tests da. Ohne sie fragt
    diese Funktion ``dienste`` selbst; dessen Antworten sind dort ohnehin
    schon zehn Sekunden gepuffert.
    """
    befunde: list[dict] = []

    # Laeuft der Host unter einer anderen Adresse als der eingerichteten,
    # dann laufen zwar alle Dienste, aber jedes Boot-Skript zeigt ins
    # Leere -- und zwar stumm. Das ist der Fall, fuer den es die rote
    # Karte gibt: Der Server erfuellt seine Aufgabe nicht, und es hilft
    # nur, dass jemand etwas tut.
    abweichung = serveradresse.abweichung(eingerichtete_ip, netzlage())
    if abweichung:
        befunde.append({
            "stufe": "fehler",
            "kennung": "adresse",
            "titel": "Kein Rechner findet seine Dateien",
            "marke": 0,
            "eingerichtet": eingerichtete_ip,
            "tatsaechlich": abweichung,
        })

    # -- Die Dienste. Ein ausgefallener Dienst ist nicht wie der andere:
    # Ohne dnsmasq kommt kein Rechner durch, ohne nfs-server nur die
    # grossen Live-Systeme nicht. Bis zum 28.08.2026 sagte die Oberflaeche
    # zu beidem denselben Satz.
    #
    # "unbekannt" ist ausdruecklich kein Befund -- auf einem Rechner ohne
    # systemd waere sonst Dauerbetrieb. Dieselbe Regel wie bei der Adresse.
    zustand = (zustaende or dienste.zustaende)()
    aus = {d["name"] for d in zustand
           if not d["laeuft"] and d["zustand"] != "unbekannt"}

    if aus & set(BOOTDIENSTE):
        befunde.append({
            "stufe": "fehler",
            "kennung": "bootdienst",
            "titel": "Kein Rechner kann gerade starten",
            "marke": 0,
            "dienste": [d for d in zustand if d["name"] in aus & set(BOOTDIENSTE)],
        })

    if aus & set(TEILDIENSTE):
        befunde.append({
            "stufe": "warnung",
            "kennung": "teildienst",
            "titel": "Große Live-Systeme starten gerade nicht",
            # Wieviele es sind. Faellt ein weiterer aus, ist es ein neuer
            # Befund -- der eine, den man zur Kenntnis genommen hat, war
            # ein anderer.
            "marke": len(aus & set(TEILDIENSTE)),
            "dienste": [d for d in zustand if d["name"] in aus & set(TEILDIENSTE)],
        })

    # -- Der Platz. Ein Abbild braucht mehrere Gigabyte; geht der Platz
    # mittendrin aus, bleibt ein halber Eintrag liegen. Die Schwelle ist
    # dieselbe, ab der der Balken auf Server Health "voll" heisst.
    belegung = platz if platz is not None else (
        dienste.platz(assets_dir) if assets_dir else {})
    if belegung and belegung.get("anteil", 0) >= dienste.VOLL:
        befunde.append({
            "stufe": "warnung",
            "kennung": "platte",
            "titel": "Die Platte ist fast voll",
            # Die erreichte Fuenferstufe: 90, 95, 100. Wer bei 91 Prozent
            # wegklickt, sieht die Karte bei 95 wieder -- und nicht schon
            # bei 92, sonst waere das Wegklicken keines.
            "marke": int(belegung.get("anteil", 0)) // 5 * 5,
            "platz": belegung,
        })

    return sortiert(befunde)

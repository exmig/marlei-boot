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
import umgebung
import updatewacht

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

# Und welche nur einen Teil tragen. Jeder bekommt einen eigenen Befund,
# denn der Titel nennt die Folge -- und die ist bei den beiden eine
# andere: Ohne NFS starten die grossen Live-Systeme nicht, ohne Samba
# kommt kein Windows-Setup an seine Quellen. Ein gemeinsamer Titel waere
# fuer beide Faelle ungenau.
#
# Dass beide Dienste auf einem Server laufen, der nur eine Haelfte
# braucht, ist der bekannte Preis: Das Repertoire aus Windows UND Linux
# ist der Standard. Wer eine Haelfte entfernt, bekommt einen Dauerbefund
# -- siehe B-053 Reine Windows- oder Linux-Konfiguration.
TEILDIENSTE = ("nfs-server", "smbd")

# Welcher Teildienst welche Karte bekommt.
TEILBEFUND = {
    "nfs-server": "teildienst",
    "smbd": "windowsdienst",
}

# ---------------------------------------------------------- der Katalog
#
# Jede Karte, die es gibt -- einmal beschrieben, an einer Stelle.
#
# Warum als Daten und nicht verstreut: Die Angaben standen bis zum
# 02.09.2026 an drei Orten -- die Bedingung hier im Quelltext, die Stufe
# in der Mappe, die Beispiele in der Hilfe. Drei Orte laufen auseinander,
# und sie taten es: "smbd" stand in keiner Stufe, fiel aus, und die
# Oberflaeche schwieg. Jetzt holt sich sammeln() Stufe und Titel von hier,
# und die Hilfe rendert dieselbe Tabelle. Ein Befund ohne Katalogzeile
# laesst sich nicht mehr bauen.
#
# Die Felder:
#
#   kennung   heisst auch die Vorlage: templates/befunde/<kennung>.html
#   stufe     fehler | warnung | info
#   titel     der Satz, der zugeklappt dasteht -- er nennt die FOLGE,
#             nicht den Vorgang. Zugeklappt ist er das Einzige, was
#             jemand sieht, und "Die Adresse hat sich geaendert" sagt
#             nicht, was daran schlimm ist. Wo die Folge von etwas
#             abhaengt, das wir nicht wissen -- wie gross das naechste
#             Abbild ist --, nennt er den Zustand; behaupten ist
#             schlimmer als beschreiben.
#   wodurch   wann die Karte kommt, in einem Satz. Fuer die Hilfe.
#   wieder    wann sie nach dem Wegklicken zurueckkommt, oder "" bei Rot
#             -- Rot laesst sich nicht wegklicken.
KATALOG = (
    {"kennung": "adresse", "stufe": "fehler",
     "titel": "Kein Rechner findet seine Dateien",
     "wodurch": "Der Host läuft unter einer anderen Adresse als der "
                "eingerichteten. Alle Dienste laufen, aber jedes "
                "Boot-Skript zeigt ins Leere.",
     "wieder": ""},
    {"kennung": "bootdienst", "stufe": "fehler",
     "titel": "Kein Rechner kann gerade starten",
     "wodurch": "Einer der Dienste nginx, dnsmasq oder pxeweb läuft "
                "nicht. Ohne sie kommt kein Rechner durch.",
     "wieder": ""},
    {"kennung": "teildienst", "stufe": "warnung",
     "titel": "Große Live-Systeme starten gerade nicht",
     "wodurch": "nfs-server läuft nicht. Betroffen sind nur Einträge, "
                "die ihr Wurzeldateisystem über das Netz einhängen.",
     "wieder": "wenn der Dienst zwischendurch wieder lief"},
    {"kennung": "windowsdienst", "stufe": "warnung",
     "titel": "Windows lässt sich gerade nicht installieren",
     "wodurch": "smbd läuft nicht. Die Windows-Installationsquellen "
                "liegen auf einer Freigabe dieses Servers.",
     "wieder": "wenn der Dienst zwischendurch wieder lief"},
    {"kennung": "platte", "stufe": "warnung",
     "titel": "Der Platz reicht nicht mehr für ein Abbild",
     "wodurch": "Frei ist weniger, als das größte Abbild hier belegt — "
                "mindestens werden %d GB zurückgehalten."
                % (dienste.SOCKEL // 1024 ** 3),
     "wieder": "wenn wieder ein Gigabyte weniger frei ist"},
    {"kennung": "einrichtung", "stufe": "warnung",
     "titel": "Die Einrichtung ist älter als der Code",
     "wodurch": "In /etc/pxeweb.env fehlen Werte, die der laufende Code "
                "erwartet. Der Server läuft, aber was daran hängt, ist "
                "nicht eingerichtet.",
     "wieder": "wenn wieder ein Wert mehr fehlt"},
    {"kennung": "neuefassung", "stufe": "info",
     "titel": "Es liegen Änderungen bereit",
     "wodurch": "Seit dieser Server eingespielt wurde, ist im Repository "
                "etwas dazugekommen. Wie oft nachgesehen wird, steht "
                "unter Einrichtung in der Karte Stand.",
     "wieder": "wenn weitere Änderungen dazukommen"},
)


def aus_katalog(kennung: str) -> dict:
    """Stufe und Titel einer Karte -- geschrieben steht beides nur oben."""
    for eintrag in KATALOG:
        if eintrag["kennung"] == kennung:
            return {"stufe": eintrag["stufe"], "kennung": kennung,
                    "titel": eintrag["titel"]}
    raise KeyError("kein Katalogeintrag fuer %r" % kennung)

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


def _plattenmarke(belegung: dict) -> int:
    """Eine Zahl, die nur steigt, wenn es schlimmer wird -- siehe kenntnis.py.

    Die fehlenden Gigabyte bis zur Reserve. Sie muss grob sein: Ein
    Wegklicken, das jedes freigewordene Byte aufhebt, waere keines. Ein
    Gigabyte ist grob genug und trotzdem eine Nachricht -- so gross ist die
    Luft, die beim Entpacken gebraucht wird.

    Frueher stand hier die Fuenferstufe der Belegung. Sie ist mit der
    Prozentschwelle gegangen: Auf einer grossen Platte sind fuenf Prozent
    Hunderte von Gigabyte, das ist keine Stufe, sondern ein halbes Jahr.
    """
    fehlend = dienste.reserve() - belegung.get("frei", 0)
    return max(0, fehlend // 1024 ** 3)


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
        befunde.append(dict(aus_katalog("adresse"),
                            marke=0,
                            eingerichtet=eingerichtete_ip,
                            tatsaechlich=abweichung))

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
        befunde.append(dict(
            aus_katalog("bootdienst"), marke=0,
            dienste=[d for d in zustand if d["name"] in aus & set(BOOTDIENSTE)]))

    # Je ausgefallenem Teildienst eine eigene Karte, in der Reihenfolge
    # von TEILDIENSTE. Zwei zugleich sind zwei Karten -- sie treffen
    # verschiedene Leute und haben verschiedene Wege hinaus.
    for name in TEILDIENSTE:
        if name not in aus:
            continue
        befunde.append(dict(
            aus_katalog(TEILBEFUND[name]),
            # Ein Dienst, ein Befund: Die Marke kann nur 1 sein. Sie steht
            # trotzdem da, damit jeder Befund dieselben Felder hat -- und
            # weil das Wegklicken sie liest.
            marke=1,
            dienste=[d for d in zustand if d["name"] == name]))

    # -- Der Platz. Ein Abbild braucht mehrere Gigabyte; geht der Platz
    # mittendrin aus, bleibt ein halber Eintrag liegen. Die Regel steht in
    # dienste.platz_knapp() -- dieselbe, an der sich der Balken auf Server
    # Health faerbt.
    belegung = platz if platz is not None else (
        dienste.platz(assets_dir) if assets_dir else {})
    if dienste.platz_knapp(belegung):
        befunde.append(dict(
            aus_katalog("platte"),
            marke=_plattenmarke(belegung),
            reserve=dienste.reserve(),
            # Woher die Reserve kommt. Die Karte sagt es unterschiedlich:
            # Steht hier 0 oder etwas Kleines, ist es der Sockel, und der
            # Satz "so viel, wie das groesste Abbild belegt" waere schlicht
            # falsch -- aufgefallen in der Vorschau am 04.09.2026.
            groesstes=dienste.groesstes_abbild(),
            sockel=dienste.SOCKEL,
            platz=belegung))

    # -- Passt die Umgebung noch zum Code? Der Fall vom 30.08.2026:
    # gesund gemeldet, Freigabe fehlt, und niemand haette erraten koennen,
    # warum. Siehe umgebung.py.
    luecken = umgebung.fehlend()
    if luecken:
        befunde.append(dict(
            aus_katalog("einrichtung"),
            # Die Zahl der fehlenden Werte: Sie steigt, wenn es schlimmer
            # wird, und faellt sonst weg.
            marke=len(luecken),
            fehlend=luecken))

    # -- Eine neuere Version. Die einzige blaue Karte: wissenswert, aber
    # niemand muss deswegen etwas tun -- der Server laeuft weiter, und was
    # er ausrollt, entscheidet der Betreiber (A-013).
    #
    # Gefragt wird hier nicht; gelesen wird nur, was der Waechter zuletzt
    # hinterlegt hat. Ein Befund entsteht auf jeder Seite -- eine
    # Netzabfrage darin waere ein Aufruf je Seitenaufbau.
    lage = updatewacht.stand()
    if lage["neuer"]:
        befunde.append(dict(
            aus_katalog("neuefassung"),
            # Die Zahl der Aenderungen: Sie steigt, wenn weitere
            # dazukommen -- und genau dann soll die Karte wiederkommen.
            marke=lage["voraus"],
            fassung=lage))

    return sortiert(befunde)

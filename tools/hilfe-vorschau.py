#!/usr/bin/env python3
"""Die Hilfe eigenstaendig ausgeben -- ohne laufenden Server.

Wofuer das da ist, zweimal:

**Beim Bearbeiten.** Die Hilfe ist die laengste Seite dieser Anwendung,
und wer einen Absatz umstellt, will ihn ansehen, ohne den Dienst zu
starten. Das Skript rendert die Vorlage mit denselben Werten, die der
Server einsetzt, und legt sie zusammen mit den Dateien ab, auf die sie
verweist. Was dabei herauskommt, laesst sich im Browser oeffnen.

**Fuer die Veroeffentlichung.** Wer im Repository stoebert, soll das
Kapitel *Der erste Durchgang* ansehen koennen, bevor er irgendetwas
installiert -- GitHub zeigt eine Vorlage aber als Quelltext. Was hier
entsteht, ist genau die Datei, die GitHub Pages ausliefern kann. Siehe
der Roadmap dieses Projekts.

Deshalb schreibt es nicht nur die HTML-Datei, sondern kopiert auch jede
Datei mit, die darin vorkommt. Eine Hilfe ohne ihr Stylesheet zeigt die
nachgebauten Ausschnitte des Kapitels als nackte Formulare -- und die
sind der Grund, warum es das Kapitel gibt.

Aufruf aus dem Projektordner:

    python tools/hilfe-vorschau.py [ZIELORDNER]

Ohne Angabe landet alles in build/hilfe/.
"""
import pathlib
import re
import shutil
import sys

WURZEL = pathlib.Path(__file__).resolve().parent.parent
WEBUI = WURZEL / "webui"
STATISCH = WEBUI / "static"

# Die Anwendung selbst wird NICHT importiert: app.py liest beim Laden
# Umgebung, Katalog und Zustandsdateien und braucht einen eingerichteten
# Server. Gebraucht werden hier zwei Module: die Laengenangaben -- sie
# stehen in den Titeln der Eingabefelder und sollen die echten sein -- und
# der Katalog der Befunde, aus dem die Hilfe ihre Tabelle rendert. Beide
# tun beim Laden nichts; sie sind reine Angaben.
sys.path.insert(0, str(WEBUI))
import bezeichnungen  # noqa: E402
import befunde  # noqa: E402

from jinja2 import Environment, FileSystemLoader  # noqa: E402

# Was der Server sonst einsetzt. Die Werte sind Beispiele und muessen es
# sein: Es gibt hier keinen Server, den man fragen koennte. Sie stehen
# ausschliesslich in der Fusszeile und in zwei Saetzen der Hilfe.
BEISPIEL = {
    # Ein Platzhalter und keine Adresse, und zwar dieselbe Schreibweise wie
    # in docs/02-installation.md. Hier stand bis zum 05.09.2026 die IP der
    # produktiven Maschine -- auf einer Seite im Netz waere das die Adresse
    # eines fremden Heimnetzes, und schlimmer: Die Zeile
    # "curl -sf http://.../logs.sh | sudo sh" laedt zum Abtippen ein.
    "base_url": "http://<BootServer-IP>",
    "menu_default": "local",
    "menu_timeout": 30,
    "aktiv": "hilfe",
    "meldung": "",
    # Leer, und das mit Absicht: Die Seitenkarten melden den Zustand
    # eines laufenden Servers. In einer Vorschau haetten sie keinen, den
    # sie melden koennten -- und auf einer veroeffentlichten Seite waere
    # eine Fehlerkarte eine Aussage ueber eine Maschine, die den Leser
    # nichts angeht.
    "befunde": [],
    # Wohin der Knopf einer Karte zurueckfuehrte. Hier fuehrt nichts
    # zurueck -- aber ohne die Angabe griffe die Vorlage nach "request",
    # und das gibt es in einer Vorschau nicht.
    "hier": "/",
    # Der Katalog dagegen gehoert dazu: Er sagt, WELCHE Karten es gibt und
    # wann sie kommen -- eine Auskunft ueber das Produkt, nicht ueber diese
    # Maschine. Genau die will jemand lesen, der noch keinen Server hat.
    "katalog": befunde.KATALOG,
    # Die Anhaengsel gegen den Zwischenspeicher des Browsers. Hier
    # stoeren sie nur: Die Dateien liegen daneben und heissen wie sie.
    "stil_version": "",
    "marken_version": "",
    "max_zeile": bezeichnungen.MAX_ZEILE,
    "max_version": bezeichnungen.MAX_VERSION,
    "max_info": bezeichnungen.MAX_INFO,
    "menue_breite": bezeichnungen.MENUE_BREITE,
}

# "/static/style.css?v=abc" -> "style.css". Gesucht wird mit einem Muster
# und nicht mit einer Liste von Dateinamen: Kommt in base.html ein Bild
# dazu, faellt es hier sonst still hinten runter, und die Vorschau haette
# eine Luecke, die niemand bemerkt.
VERWEIS = re.compile(r"/static/([A-Za-z0-9._-]+)(\?v=[^\"']*)?")

# Die Reiterleiste -- der Block, der stehen bleibt und sein Ziel verliert.
LEISTE = re.compile(r'<div class="reiterleiste">.*?</div>', re.S)

# Ein Verweis auf diese Seite selbst. Er wird nicht tot, er wird richtig:
# Auf dem Server heisst das Register /hilfe, hier ist es der Seitenanfang.
SELBST = re.compile(r'href="/hilfe(#[A-Za-z0-9_-]+)?"')

# Die beiden Rueckwege am Kopf und Fuss eines Abschnitts: "Zur Karte ->"
# und "Zum Register ->". Sie tragen keinen Inhalt, sie sind der Weg selbst
# -- ohne Ziel bliebe ein Pfeil stehen, der nirgendwohin zeigt. Also weg,
# und zwar der ganze Absatz.
WEGWEISER = re.compile(
    r'\s*<p class="(?:zurkarte|zumregister)">\s*<a\s[^>]*href="/[^"]*"'
    r'[^>]*>.*?</a>\s*</p>', re.S)

# Alles Uebrige, was auf eine Route des Servers zeigt: /systeme, /quellen,
# /protokoll?einheit=dnsmasq. Der Text bleibt, die Klammer faellt --
# "steht unter Server Health" liest sich ohne Verweis genauso.
ROUTE = re.compile(r'<a\s[^>]*href="/[^"]*"[^>]*>(.*?)</a>', re.S)

# Ein href, das nach der Behandlung noch auf eine Route zeigt -- danach
# sucht die Pruefung.
UEBRIG = re.compile(r'href="/(?!/)[^"]*"')


def veroeffentlichen(html: str) -> str:
    """Die Seite von allem befreien, was einen laufenden Server voraussetzt.

    **Der Grund ist ein Zahlenverhaeltnis.** Die gerenderte Hilfe traegt
    rund 110 Verweise auf Routen dieser Anwendung -- die Reiterleiste,
    jedes "unter *Systeme*", jeden Sprung ins Protokoll. Auf einem Server
    fuehren sie irgendwohin; auf einer veroeffentlichten Seite fuehren sie
    hundertzehnmal ins Leere. Eine Hilfe, in der jeder zweite Verweis
    stirbt, ist schlechter als eine ohne Verweise.

    **Vier Faelle, vier Antworten** -- und der erste ist der beste:

        /hilfe#lizenz   ist diese Seite selbst    -> #lizenz
        Reiterleiste    zeigt, wie es aussieht    -> bleibt, ohne Ziel
        "Zur Karte ->"  ist nur der Weg           -> faellt ganz weg
        /systeme        setzt einen Server voraus -> nur noch Text

    **Die Reiterleiste bleibt stehen**, weil sie zu dem gehoert, was die
    Seite zeigen soll: So sieht die Oberflaeche aus. Ohne ``href`` ist sie
    kein Verweis mehr -- ``nav a`` faerbt sie ohnehin gedaempft, sie sieht
    also aus wie vorher und tut nichts.

    **Im Fliesstext faellt die Klammer dagegen ganz weg.** Ein ``<a>`` ohne
    Ziel behielte dort die Verweisfarbe aus ``a { color: var(--accent) }``
    und saehe aus wie ein Verweis, der nicht geht. Das ist schlimmer als
    gar keiner.
    """
    html = SELBST.sub(lambda t: 'href="%s"' % (t.group(1) or "#"), html)
    html = LEISTE.sub(
        lambda t: re.sub(r'\s+href="/[^"]*"\s*', " ", t.group(0)), html)
    html = WEGWEISER.sub("", html)
    return ROUTE.sub(r"\1", html)


def pruefe(html: str) -> list:
    """Was auf dieser Seite nichts zu suchen hat.

    **Zwei Dinge, und beide faellt von selbst niemandem auf.** Eine
    Seitenkarte meldet den Zustand eines laufenden Servers -- oeffentlich
    waere das eine Aussage ueber eine Maschine, die den Leser nichts
    angeht. Und ein uebriggebliebener Verweis auf eine Route ist ein Klick,
    der auf einer fremden Seite im 404 endet.

    Gemeldet wird beides als Fehler und nicht als Hinweis: Diese Pruefung
    laeuft in dem Schritt, der die Seite veroeffentlicht, und dort ist ein
    Hinweis dasselbe wie Schweigen.
    """
    klagen = []
    uebrig = sorted(set(UEBRIG.findall(html)))
    if uebrig:
        klagen.append("Verweise auf Routen des Servers: "
                      + ", ".join(uebrig[:5])
                      + (" (und %d weitere)" % (len(uebrig) - 5)
                         if len(uebrig) > 5 else ""))
    if 'class="seitenkarte' in html:
        klagen.append("Eine Seitenkarte steht auf der Seite -- sie meldet "
                      "den Zustand eines laufenden Servers.")
    return klagen


def baue(ziel: pathlib.Path, streng: bool = False) -> pathlib.Path:
    # autoescape wie beim Server: FastAPIs Jinja2Templates schaltet es ein.
    # Eine Vorschau, die anders ausgibt als das Original, ist keine.
    umgebung = Environment(loader=FileSystemLoader(str(WEBUI / "templates")),
                           autoescape=True)
    html = umgebung.get_template("hilfe.html").render(**BEISPIEL)

    gebraucht = sorted(set(VERWEIS.findall(html)))
    html = VERWEIS.sub(r"\1", html)
    html = veroeffentlichen(html)

    klagen = pruefe(html)
    for klage in klagen:
        print("NICHT IN ORDNUNG: " + klage)
    if klagen and streng:
        raise SystemExit(1)

    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "hilfe.html").write_text(html, encoding="utf-8")
    # Dieselbe Seite noch einmal als index.html: Der Verweis im README
    # soll auf eine Adresse zeigen und nicht auf einen Dateinamen.
    (ziel / "index.html").write_text(html, encoding="utf-8")

    fehlend = []
    for name, _ in gebraucht:
        quelle = STATISCH / name
        if quelle.exists():
            shutil.copy2(quelle, ziel / name)
        else:
            fehlend.append(name)
    if fehlend:
        # Kein Abbruch: Eine Vorschau ohne Symbol ist brauchbar, eine
        # Vorschau, die gar nicht erst entsteht, nicht. Gesagt werden
        # muss es trotzdem.
        print("Nicht gefunden in webui/static: " + ", ".join(fehlend))

    print("%s -- %d Zeichen, %d Datei(en) daneben"
          % (ziel / "hilfe.html", len(html), len(gebraucht) - len(fehlend)))
    return ziel / "hilfe.html"


if __name__ == "__main__":
    # --streng bricht ab, wenn die Pruefung etwas findet. Beim Bearbeiten
    # waere das laestig; in dem Schritt, der veroeffentlicht, ist es der
    # ganze Zweck.
    ordner = [a for a in sys.argv[1:] if not a.startswith("--")]
    baue(pathlib.Path(ordner[0]) if ordner else WURZEL / "build" / "hilfe",
         streng="--streng" in sys.argv)

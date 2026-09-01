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
# Server. Gebraucht wird hier nur das Modul mit den Laengenangaben -- die
# stehen in den Titeln der Eingabefelder und sollen die echten sein.
sys.path.insert(0, str(WEBUI))
import bezeichnungen  # noqa: E402

from jinja2 import Environment, FileSystemLoader  # noqa: E402

# Was der Server sonst einsetzt. Die Werte sind Beispiele und muessen es
# sein: Es gibt hier keinen Server, den man fragen koennte. Sie stehen
# ausschliesslich in der Fusszeile und in zwei Saetzen der Hilfe.
BEISPIEL = {
    "base_url": "http://192.168.178.30",
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


def baue(ziel: pathlib.Path) -> pathlib.Path:
    umgebung = Environment(loader=FileSystemLoader(str(WEBUI / "templates")))
    html = umgebung.get_template("hilfe.html").render(**BEISPIEL)

    gebraucht = sorted(set(VERWEIS.findall(html)))
    html = VERWEIS.sub(r"\1", html)

    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "hilfe.html").write_text(html, encoding="utf-8")

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
    baue(pathlib.Path(sys.argv[1]) if len(sys.argv) > 1
         else WURZEL / "build" / "hilfe")

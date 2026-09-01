#!/usr/bin/env python3
"""Die Seitenkarten eigenstaendig ansehen -- ohne laufenden Server.

Die drei Stufen der Seitenkarten -- rot, gelb, blau -- bekommt man auf dem
Server nur zu sehen, wenn der Fall wirklich eintritt: Ein Dienst muss
ausfallen, die Platte volllaufen, die Adresse sich aendern. Wer an den
Farben dreht, will sie aber vorher sehen.

Das Skript baut eine Seite mit allen drei Stufen und den echten Texten aus
`webui/befunde.py`. Es bindet dabei **das echte `style.css` ein und
benutzt dieselben Klassen wie `base.html`** -- es ist also kein Nachbau,
der irgendwann auseinanderlaeuft, sondern zieht mit, sobald jemand eine
Farbe aendert.

Entstanden am 31.08.2026 beim Wechsel des Seitengrunds von Blaugrau auf
den Mint-Ton der Marke. Die Frage dabei war, ob die gelbe Warnkarte auf
einem gruenlichen Grund noch als eigene Flaeche zu erkennen ist -- ihr
Kontrast gegen den Grund betraegt 1,02:1, sie lebt allein von ihrer
Kante. Eine Zahl beantwortet das nicht, nur das Ansehen.

Aufruf aus dem Projektordner:

    python tools/karten-vorschau.py [ZIELDATEI]

Ohne Angabe landet sie in build/karten.html.
"""
import io
import pathlib
import sys

PROJEKT = pathlib.Path(__file__).resolve().parent.parent

# Titel und Texte stammen aus webui/befunde.py und
# webui/templates/befunde/. Sie stehen hier als Kopie, weil die Vorlagen
# Werte eines laufenden Servers einsetzen -- eine Zahl fuer den freien
# Platz, eine Adresse, eine Dienstliste. Fuer die Farbwirkung ist der
# genaue Wert gleichgueltig; die Laenge des Textes ist es nicht.
KARTEN = [
    ("fehler", "Kein Rechner findet seine Dateien", """
  <p>
    Eingerichtet ist <code>192.168.178.30</code>, tatsächlich läuft dieser
    Server unter <code>192.168.178.44</code>. Die Dienste laufen alle — aber
    jedes Boot-Skript zeigt auf die alte Adresse. Ein Rechner, der jetzt über
    das Netz startet, findet nichts und sagt nicht, warum.
  </p>
  <p class="kartenfuss">
    Nachgezogen wird das unter Einrichtung, mit einem Befehl auf dem Server
    &middot; <a href="#">IP-Adresse übernehmen &rarr;</a>
  </p>"""),

    ("fehler", "Kein Rechner kann gerade starten", """
  <p>
    <code>dnsmasq</code> läuft nicht. Ohne diesen Dienst bekommt kein Rechner
    im Netz eine Antwort auf seine Startanfrage — das Bootmenü erscheint
    nicht, der Rechner läuft in seinen eigenen Zeitüberlauf.
  </p>
  <p class="kartenfuss">
    Was los ist, zeigt auf dem Server
    <code>sudo journalctl -u dnsmasq -n 40</code>
  </p>"""),

    ("warnung", "Große Live-Systeme starten gerade nicht", """
  <p>
    <code>nfs-server</code> läuft nicht. Betroffen sind nur Einträge, die ihr
    Wurzeldateisystem über das Netz einhängen — große Live-Systeme also. Alles
    andere startet weiter, auch die Installationen.
  </p>
  <p>
    Wer jetzt einen solchen Eintrag wählt, kommt bis zum Ladebalken und bleibt
    dann stehen. Im Bootmenü sieht man ihm nichts an.
  </p>
  <p class="kartenfuss">
    Was los ist, zeigt auf dem Server
    <code>sudo journalctl -u nfs-server -n 40</code>
  </p>"""),

    ("warnung", "Die Platte ist fast voll", """
  <p>
    Der Datenträger unter den Abbildern ist zu 91 % belegt — frei sind noch
    <strong>6 GB</strong> von 77 GB.
  </p>
  <p>
    Ein vollständiges Abbild braucht je nach System mehrere Gigabyte. Geht der
    Platz mitten im Holen aus, bleibt ein halber Eintrag liegen: Im Bootmenü
    steht er, startbereit ist er nicht.
  </p>
  <p class="kartenfuss">
    Was wie viel belegt, steht auf Server Health unter <em>Speicherplatz</em>
    &middot; <a href="#">Nachsehen &rarr;</a>
    &middot; <a href="#">Einträge aufräumen &rarr;</a>
  </p>"""),

    ("info", "Die blaue Stufe", """
  <p>
    Für sie gibt es in <code>webui/befunde.py</code> derzeit keinen Fall.
    Sie steht hier, damit alle drei Stufen nebeneinander zu sehen sind —
    wer eine blaue Karte einführt, sieht vorher, wie sie wirkt.
  </p>"""),
]


def seite(css_pfad):
    teile = [
        f'\n<details class="seitenkarte stufe-{stufe}" open>\n'
        f"  <summary><h2>{titel}</h2></summary>{inhalt}\n</details>"
        for stufe, titel, inhalt in KARTEN
    ]
    return f"""<!doctype html>
<html lang="de"><meta charset="utf-8">
<title>Seitenkarten — Vorschau</title>
<link rel="stylesheet" href="{css_pfad}">
<style>
  /* Nur fuer diese Seite: der Rahmen drumherum. Die Karten selbst tragen
     ausschliesslich die Klassen der Oberflaeche. */
  .probe {{ max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }}
  .probe > h1 {{ margin-bottom: .3rem; }}
  .probe > p.hinweis {{ color: var(--muted); margin: 0 0 2rem; }}
  .grundprobe {{ display: flex; gap: 1rem; margin: 2.5rem 0 0; flex-wrap: wrap; }}
  .grundprobe div {{ padding: .6rem 1rem; border: 1px solid var(--line);
                     border-radius: 8px; font-size: .85rem; }}
</style>
<body>
<div class="probe">
  <h1>Seitenkarten — Vorschau</h1>
  <p class="hinweis">
    Echtes <code>style.css</code>, echte Klassen — kein Nachbau.
    Erzeugt von <code>tools/karten-vorschau.py</code>.
  </p>
{"".join(teile)}

  <div class="grundprobe">
    <div>Seitengrund <code>var(--bg)</code></div>
    <div style="background:var(--panel)">Karte <code>var(--panel)</code></div>
    <div style="background:var(--fehler-bg);border-left:5px solid var(--fehler-kante)">Fehler</div>
    <div style="background:var(--warn-bg);border-left:5px solid var(--warn-kante)">Warnung</div>
    <div style="background:var(--info-bg);border-left:5px solid var(--info-kante)">Info</div>
  </div>
</div>
</body></html>
"""


def main():
    ziel = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else PROJEKT / "build" / "karten.html"
    ziel.parent.mkdir(parents=True, exist_ok=True)

    # Der Verweis auf das Stylesheet ist relativ zur Zieldatei -- so laesst
    # sich die Seite verschieben, ohne dass die Farben verlorengehen.
    css = PROJEKT / "webui" / "static" / "style.css"
    try:
        pfad = css.relative_to(ziel.parent.resolve(), walk_up=True).as_posix()
    except (ValueError, TypeError):
        pfad = css.as_uri()

    io.open(ziel, "w", encoding="utf-8").write(seite(pfad))
    print(f"geschrieben: {ziel}")
    print(f"Stylesheet:  {pfad}")


if __name__ == "__main__":
    main()

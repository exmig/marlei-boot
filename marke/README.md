# Marke

**Dieser Ordner enthält die Marke, nicht die Anwendung.** Er steht getrennt,
weil für ihn etwas anderes gilt als für den übrigen Quelltext: Der Code
steht unter der AGPL-3.0, **Name und Logo sind davon ausgenommen** — siehe
den Abschnitt *Lizenz* im [README](../README.md).

Solange diese Ausnahme nur als Satz im README steht, weiß niemand, welche
Dateien gemeint sind. Deshalb stehen sie hier beim Namen.

## Was hier erzeugt wird

`logo-bauen.py` ist die **einzige Quelle** für alle drei Dateien. Sie sind
nicht nachgezeichnet, sondern monolinear aus benannten Zahlen aufgebaut —
wer das Logo ändern will, ändert eine davon und lässt das Skript laufen.

```
marke/logo-bauen.py  ──►  ../webui/static/exmig-logo.svg      Wortmarke
                          ../webui/static/exmig-zeichen.svg   Zeichen
                          ../webui/static/favicon.ico         Favicon
```

**Warum die Ergebnisse nicht hier liegen:** Die Anwendung liefert sie über
`/static/` aus. Ein zweiter Ablageort hier wäre eine Kopie, die
auseinanderläuft — und genau das soll nicht passieren.

**Diese drei Dateien sind die Marke.** Alles andere unter `webui/static/`
— `style.css` und was sonst dort liegt — ist gewöhnlicher Quelltext unter
der AGPL.

## Aufruf

```bash
cd marke
python logo-bauen.py
```

Für die beiden SVG braucht es nur Python. Die `.ico` zusätzlich
[Pillow](https://pypi.org/project/Pillow/) (`pip install pillow`); fehlt
es, wird sie übersprungen und die beiden SVG entstehen trotzdem.

## Wo die Begründungen stehen

**Nicht hier.** Warum das Logo so aussieht, welche Farben gelten und wie
sie sich ableiten, steht in [docs/gestaltung.md](../docs/gestaltung.md).
Dort stehen auch die Kontrastzahlen — sie werden gerechnet, nicht
geschätzt.

## Die Marke gehört nicht zur Lizenz

Die AGPL gilt für den Quelltext. **Name und Zeichen sind davon
ausgenommen** — sie stehen für dieses Projekt und seinen Herausgeber, nicht
für den Code. Der Abschnitt *Lizenz* im [README](../README.md) sagt es im
Zusammenhang.

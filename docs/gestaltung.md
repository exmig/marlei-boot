# Gestaltung

Was hier steht, ist keine Beschreibung der Oberfläche, sondern die
**Sammlung der Entscheidungen** — mit ihren Gründen und den Zahlen, an
denen sie hängen. Ohne das wird jede davon in drei Monaten neu diskutiert
und meistens anders entschieden.

Die Werte selbst stehen in `webui/static/style.css`, ganz oben als Token.
Dieses Dokument sagt, **warum** sie so sind.

Verwiesen wird hier und aus dem Quelltext mit dem **Titel** eines
Abschnitts, nicht mit einer Nummer: Ein Titel sagt, was einen erwartet,
und er überlebt ein Umsortieren. Was noch offen ist, steht nicht mehr hier,
sondern im Backlog des Projekts — zwei Orte für dieselbe Frage laufen
auseinander. Das Backlog wird nicht veröffentlicht: Es sammelt Ideen und
Absichten, und die gehen niemanden etwas an außer dem, der sie hat.

---

## Die Marke

Das Logo ist eine Wortmarke: **Es ist das Wort exmig selbst**, kein Symbol
daneben. Der Name besteht aus zwei Teilen, und die Zweifarbigkeit macht
genau diese Fuge sichtbar:

| Teil | steht für | Farbe |
|---|---|---|
| **ex** | Expertise | Navy `#063b6f` |
| **mig** | Made in Germany | Türkis `#15bcb4` |

**Die Buchstaben jedes Wortteils verschmelzen miteinander** — die Farbe
trennt die beiden Teile, die Verschmelzung bindet jeden für sich zusammen.
Am deutlichsten sieht man das dort, wo der Fuß des `e` in die Diagonale des
`x` läuft. Das ist Absicht und darf bei einer Überarbeitung nicht
wegoptimiert werden.

### Die Dateien

| Datei | wofür |
|---|---|
| `webui/static/exmig-logo.svg` | die Wortmarke — README, heller wie dunkler Seitengrund |
| `webui/static/exmig-logo-band.svg` | dieselbe Wortmarke fürs Navy-Band im Seitenkopf |
| `webui/static/exmig-zeichen.svg` | nur „ex", weiß auf navy Kachel — Browser-Reiter |
| `webui/static/favicon.ico` | dasselbe Zeichen als Rasterbild, 16/32/48/64 |

Alle vier entstehen aus **einer** Quelle, `marke/logo-bauen.py`.
Dort steht jede Zahl mit Namen: Grundlinie 713, x-Höhe 514, Unterlänge bis
815, Strichstärke 44 für „ex" und 36 für „mig". Das Logo ist nicht
vektorisiert, sondern monolinear aus Kreisen, Geraden und Bögen nachgebaut
— wer es ändern will, ändert eine Zahl und lässt das Skript laufen, statt
Stützpunkte zu schieben.

### Warum das Zeichen nur „ex" zeigt

Fünf Buchstaben sind bei 16 Pixeln ein Fleck. Also nur der Wortteil, der
die Verschmelzung trägt — weiß auf einer navy Kachel. Drei Varianten
wurden dafür bei 16 Pixeln gerastert und auf helle wie dunkle
Browserleiste gelegt: Ohne Kachel verschwindet das Zeichen und die Punze
des `e` läuft zu; Navy auf Türkis wird matschig. Weiß auf Navy liest sich
am klarsten und trägt auch auf dunkler Leiste.

**Bewusst ohne Themenumschaltung**, obwohl SVG-Favicons das könnten: Das
Zeichen steht auch in Lesezeichen, Verlauf und Taskleiste, und dort ist
ein stabiles Bild mehr wert als eines, das mitschaltet. Die `.ico` könnte
ohnehin nicht umschalten — zwei Verhaltensweisen für dasselbe Zeichen
wären schlechter als eine.

---

## Warum die Markenfarben die Oberfläche nicht direkt färben

**Die beiden Hälften sind fast Gegenspieler.** Gemessen als
Kontrastverhältnis gegen den jeweiligen Grund:

| | heller Grund `#f2f8f7` | dunkler Grund `#14171b` |
|---|---|---|
| Navy `#063b6f` | 10,5 : 1 | **1,6 : 1** — unsichtbar |
| Türkis `#15bcb4` | **2,2 : 1** — zu blass | 7,6 : 1 |

Roh eingesetzt wäre je nach Thema eine der beiden unbrauchbar.

Dazu ein zweiter Befund: **Das Marken-Navy steht der Textfarbe zu nahe** —
nur 1,5 : 1 Abstand. Ein Verweis in dieser Farbe sähe aus wie Text.

Daraus die Regel:

> Die Marke und der Akzent der Oberfläche sind **nicht dasselbe**. Je Thema
> wird die Hälfte gebraucht, die dort trägt — und wo die rohe Farbe nicht
> reicht, eine abgeleitete Fassung im selben Farbton.

Im **dunklen** Thema muss nichts abgeleitet werden: Das aufgehellte Navy
des Logos und das rohe Türkis tragen beide. Dort sind Marke und Akzent
dieselbe Farbe.

---

## Die Farbtoken

| Token | hell | dunkel | Aufgabe |
|---|---|---|---|
| `--marke-ex` | `#063b6f` | `#3585d4` | die Marke, exakt wie im Logo |
| `--marke-mig` | `#15bcb4` | `#15bcb4` | die zweite Hälfte |
| `--accent` | `#0a63bd` | = `--marke-ex` | Verweise, Knöpfe, Umrandungen, Fokusrahmen |
| `--accent-mig` | `#0e817b` | = `--marke-mig` | Flächen ohne Schrift — Balken |
| `--knopf1` | = `--marke-ex` | `#1170d0` | Fläche der Knopf-Variante 1 (siehe *Knöpfe*) |
| `--knopf-flaeche` | `#ffffff` | = `--panel` | Fläche der Knopf-Variante 2 |
| `--knopf2-schrift` | = `--marke-ex` | `#428cd7` | Schrift der Knopf-Variante 2 |
| `--bg` | `#f2f8f7` | `#14171b` | Seitengrund — aus dem Marken-Türkis, siehe unten |
| `--panel` | `#ffffff` | `#1c2026` | Karten |
| `--ink` | `#1b1f24` | `#e6e9ee` | Text |
| `--muted` | `#6b7480` | `#98a1ad` | Nebentext, inaktive Reiter |
| `--line` | `#dfe3e8` | `#2c323a` | Trennlinien, Rahmen |
| `--ok-bg` / `--ok-ink` | `#e3f4e8` / `#1c6b34` | `#16311f` / `#7ed69a` | „liegt vor", „läuft" |
| `--miss-bg` / `--miss-ink` | `#fdeceb` / `#a3271f` | `#351a18` / `#ff9c92` | „fehlt" |
| `--danger` | `#b3261e` | `#ff8079` | Löschen, Zurücksetzen |
| `--fehler-bg` / `--fehler-kante` | = `--miss-bg` / `--danger` | dito | die rote Seitenkarte (*Die Karte und ihre drei Bereiche*) |
| `--warn-bg` / `--warn-kante` | `#fdf4dd` / `#a86a00` | `#302512` / `#e3b341` | die gelbe |
| `--info-bg` / `--info-kante` | `#e9f1fb` / = `--marke-ex` | `#15263a` / = `--marke-ex` | die blaue |

Die Ampel der Seitenkarten steht damit auf schon vorhandenen Werten, wo es
ging: Rot ist `--miss-bg` und `--danger` unter neuem Namen, Blau ist das
Marken-Navy selbst. Nur Gelb ist neu — und war das einzige, das Arbeit
machte.

**Das Gelb, gerechnet.** Die Kante trägt die 3:1-Regel für
bedeutungstragende Flächen (*Regeln, nach denen Farbe vergeben wird*), die blasse Fläche schafft sie mit 1,1:1
nicht. Und ein Gelb, das aussieht wie ein Gelb, trägt sie im hellen Thema
auch nicht:

| Kandidat | gegen den hellen Grund |
|---|---|
| `#f5c518` — ein richtiges Gelb | **1,5 : 1** ✗ |
| `#d99400` — der Ton des Balkens | 2,4 : 1 ✗ |
| `#a86a00` — gewählt | 4,1 : 1 ✓ |

Wer auf hellem Grund 3:1 will, landet zwangsläufig bei einem **Ocker**. Im
dunklen Thema ist es umgekehrt: Dort trägt das satte Gelb mühelos
(`#e3b341`, 9,2:1) und der Ocker verschwände. Die Ampel ist deshalb keine
Farbe je Stufe, sondern **zwei Farben je Stufe** — derselbe Fall wie beim
Türkis, das im hellen Thema als `--accent-mig` abgedunkelt wird.

Die Kanten der drei Stufen, gegen den Seitengrund gemessen:

| Stufe | hell | dunkel |
|---|---|---|
| Fehler | 6,1 : 1 | 7,4 : 1 |
| Warnung | 4,1 : 1 | 9,2 : 1 |
| Info | 10,5 : 1 | 4,7 : 1 |

Der Text steht auf allen sechs Flächen zwischen 12,3:1 und 15,1:1 —
deshalb funktionieren in diesen Karten alle gewöhnlichen Farben weiter,
und es braucht keine Sonderfarbe für Verweise, `code` oder gedämpften Text.

**Der Belegungsbalken zieht mit** (28.08.2026). Er hatte bis dahin seine
eigene Ampel: türkis, ein fest verdrahtetes `#d99400` ab drei Vierteln,
`--danger` ab neun Zehnteln. Zwei Dinge stimmten daran nicht:

1. Bei 94 % war der Balken **rot** und die Warnkarte darüber **gelb** —
   zwei Farben für dieselbe Tatsache, übereinander auf einer Seite. Rot
   heißt bei den Karten *„der Server tut seine Arbeit nicht"*. Eine volle
   Platte tut das nicht; sie kostet den nächsten Download.
2. `#d99400` kam gegen die **Spur** des Balkens auf **2,11:1** und
   verfehlte damit als einzige Balkenfarbe die 3:1-Regel — und zwar nur im
   hellen Thema. Gemessen wird gegen die Spur, die eingefärbte Rille, nicht
   gegen den Seitengrund.

| Balkenfarbe | wofür | hell | dunkel |
|---|---|---|---|
| `--accent-mig` | normal | 3,88 ✓ | 5,29 ✓ |
| `#d99400` *(war: knapp)* | ab 75 % | **2,11 ✗** | 4,88 ✓ |
| `--danger` *(war: voll)* | ab 90 % | 5,37 ✓ | 5,13 ✓ |
| `--warn-kante` *(jetzt beide)* | ab 75 % | 3,65 ✓ | 6,43 ✓ |

Beide Warnstufen tragen jetzt `--warn-kante`. **Rot hat den Balken
verlassen:** Die dritte Stufe ist keine Farbe mehr, sondern die Karte
selbst, die ab neun Zehnteln erscheint — und die steht ohnehin weiter oben
und auf jeder Seite.

Dass `knapp` und `voll` damit gleich aussehen, ist der Preis und keine
Nachlässigkeit: **Zwei Gelbstufen, die beide 3:1 schaffen, gibt es auf
hellem Grund nicht.** Alles heller als `#b4740e` (3,17) fällt durch, und
zwischen `#b4740e` und `#a86a00` sieht niemand einen Unterschied. Die
beiden Klassen bleiben trotzdem getrennt — sie stehen im HTML, tragen die
Schwelle im `title`, und wer hier einmal etwas anderes als Farbe braucht,
findet die Stelle schon vor.

Die abgeleiteten Werte im hellen Thema und ihre Zahlen:

- `--accent` `#0a63bd` — 5,6 : 1 gegen den Grund, 5,9 : 1 für weiße Schrift
  darauf, 2,8 : 1 Abstand zur Textfarbe. Das Marken-Navy selbst hätte hier
  nur 1,5 : 1 Abstand zum Text.
- `--accent-mig` `#0e817b` — 4,4 : 1 gegen den Grund. Roh wären es 2,2 : 1.

*(Am Rande: Der Akzent vor der Umstellung, `#2f6feb`, lag mit 4,26 : 1
unter der Grenze von 4,5 — Verweise waren also schon vorher zu blass.)*

---

### Der Seitengrund kommt aus der Marke

Bis zum 31.08.2026 stand dort `#f6f7f9` — ein sehr helles Blaugrau, die
Vorgabe fast jedes Rahmenwerks. Seither trägt der Grund `#f2f8f7`: die
**mig-Hälfte des Logos, stark aufgehellt**. Gerade so viel Ton, dass die
weißen Karten darauf als Fläche zu erkennen sind.

**Der Grund für diese Wahl ist Verwandtschaft, nicht Geschmack.** Zwischen
Navy und Türkis stünde ein warmer Ton — Gold, Sandstein, Leinen — ohne
Bezug da; er käme von außen. Ein Grund aus dem Logo lässt sich begründen,
und das ist in diesem Dokument sonst überall der Maßstab.

**Die Zahlen ändern sich dabei nicht.** Gemessen gegen den neuen Grund:

| gegen | vorher | jetzt |
|---|---|---|
| Text `#1b1f24` | 15,4 : 1 | 15,4 : 1 |
| Verweise `#0a63bd` | 5,5 : 1 | 5,5 : 1 |
| Nebentext `#6b7480` | 4,42 : 1 | 4,41 : 1 |
| Karte `#ffffff` | 1,07 : 1 | 1,07 : 1 |

**Die Farbwahl entscheidet hier rechnerisch gar nichts.** Acht Kandidaten
wurden durchgerechnet — Gold, Mint, Sandstein, Salbei, Leinen,
Papierblau, Lavendelgrau und das alte Blaugrau. Alle liegen beim
Nebentext zwischen 4,36 und 4,42 : 1, weil sie gleich hell sind und sich
nur im Ton unterscheiden. **Die Entscheidung ist deshalb eine
gestalterische**, und dann zählt, was sich begründen lässt.

**Kräftiger geht nicht, ohne etwas aufzugeben.** Ein deutlicherer Ton
drückt den Nebentext unter 4,3 : 1. Die Tönung ist kein Regler, den man
beliebig aufdreht — sie kostet Kontrast, sobald sie auffällt.

**Der Nebentext liegt schon jetzt unter der Norm.** 4,4 : 1 gegen den
Grund, verlangt sind 4,5 : 1 für Text unter 18 pt. Das war vor der
Umfärbung genauso und ist kein Fehler dieser Änderung — aber es steht
hier, weil es beim Nachrechnen auffiel und beim nächsten Griff in die
Farben behoben gehört. Ein Schritt auf `#616a76` brächte 5,1 : 1.

**Die dunkle Ansicht bleibt, wie sie war.** Ein getönter Grund wirkt dort
nicht als Ton, sondern als Farbstich — dunkle Flächen nehmen Sättigung
anders auf. `#14171b` steht unverändert.

## Regeln, nach denen Farbe vergeben wird

**Die Grenzen**, an denen jede Farbe gemessen wird, bevor sie hineinkommt:

| Verwendung | Mindestkontrast |
|---|---|
| Schrift auf Grund | 4,5 : 1 |
| Fläche, die etwas bedeutet (Balken, Rahmen, Fokus) | 3 : 1 |
| Verweisfarbe gegen die Textfarbe | 2,5 : 1 — sonst erkennt man Verweise nicht |

**Türkis trägt keine Schrift.** Es ist auf hellem Grund die schwächere der
beiden Hälften; es färbt Flächen — Balken für Plattenplatz und Fortschritt
— und dort steht nichts drauf.

**Farbe ist nie das einzige Merkmal.** Der aktive Reiter ist fett, trägt
einen 2 Pixel starken Balken *und* ist navy. Nimmt man die Farbe weg,
bleibt die Aussage erhalten. Dasselbe gilt für „fehlt" und „liegt vor":
Dort steht immer auch ein Wort.

**Die Statusfarben sind Bedeutung, nicht Marke.** Grün, Rot und Gelb sagen
etwas über den Zustand; sie werden nicht auf Markenfarben umgestellt, auch
wenn es hübscher wäre. Wer sie überlädt, nimmt ihnen die Aussage.

**Die Bedeutung liegt auf der Kante, nicht auf der Fläche.** Bei den
Seitenkarten (*Die Karte und ihre drei Bereiche*) war ein sattes Rot als Fläche der erste Vorschlag. Es
geht nicht auf: `#b3261e` erzwingt weiße Schrift — und dann bräuchte in
dieser einen Karte *alles* eine Sonderfarbe, Verweise, `code`, gedämpfter
Text —, und im dunklen Thema verschwindet es mit 2,8:1 gegen den Grund.
Eine blasse Fläche mit kräftiger Kante trägt dieselbe Aussage: Die Kante
erfüllt die 3:1, die Fläche färbt nur, und drinnen bleibt alles wie
überall.

---

## Knöpfe

Am 27.08.2026 festgelegt.

### Variante 1 — der gefüllte Knopf

**Fläche in der Marke, Schrift weiß.** Das ist der Knopf, der etwas
auslöst: *Prüfen*, *Aufnehmen*, *Speichern* dort, wo gespeichert wird.

| | hell | dunkel |
|---|---|---|
| Fläche (`--knopf1`) | `#063b6f` = `--marke-ex` | `#1170d0` |
| Schrift | `#ffffff` | `#ffffff` |

### Eine Größe für alle Knöpfe

`padding: .15rem .5rem`, `font-size: .78rem`, `border-radius: 6px`, 1px
Rahmen. Das gilt für alle drei Varianten und für alles, was **aussieht**
wie ein Knopf: `a.knopf` (der Umschalter UEFI/BIOS) und `.dateiknopf` (die
Dateiauswahl) tragen dieselben Maße, obwohl das eine ein Link und das
andere ein Beschriftungsfeld ist.

Vorher gab es dafür **fünf** Regeln nebeneinander: die Grundgröße,
`.kopfknopf`, `.kompakt button`, `table.eng button` und `a.knopf`. Knöpfe
in verschiedenen Größen liest man als verschiedene Wichtigkeiten — und
gemeint war das an keiner der Stellen. Die vier Sonderregeln sind
entfallen, `.kopfknopf` auch aus den Vorlagen.

**Warum das dunkle Thema einen eigenen Wert braucht.** Die Knopffläche
zieht dort in zwei Richtungen: Weiße Schrift darauf will sie dunkel, ihre
eigene Kante gegen den Grund will sie hell. Das rohe Marken-Navy käme gegen
den dunklen Grund nur auf 1,6 : 1 — das wäre kein Knopf mehr, sondern ein
Loch. `#1170d0` erfüllt beides:

| | Wert |
|---|---|
| weiße Schrift darauf | 4,9 : 1 |
| Fläche gegen den Seitengrund | 3,6 : 1 |
| Fläche gegen eine Karte | 3,3 : 1 |

Im hellen Thema stellt sich die Frage nicht: Dort sind es 11,3 : 1 für die
Schrift und 10,5 : 1 für die Fläche.

### Variante 2 — der umrandete Knopf

**Fläche weiß, Schrift in der Marke, Rahmen grau.** Das ist der Knopf, der
etwas tut, aber nicht das Wichtigste auf der Karte: *Speichern*, *Holen*,
*Neue Version*. In der CSS ist es `button.ghost`.

| | hell | dunkel |
|---|---|---|
| Fläche (`--knopf-flaeche`) | `#ffffff` | `= --panel` |
| Schrift (`--knopf2-schrift`) | `#063b6f` = `--marke-ex` | `#428cd7` |
| Rahmen | `--line` | `--line` |

**Der Rahmen bleibt grau** — bewusst. Ein Rahmen in der Marke machte aus
dem zurückhaltenden Knopf einen zweiten lauten, und dann stünden zwei
gleich starke Knöpfe nebeneinander, von denen einer der wichtigere sein
soll.

Die Maße sind dieselben wie bei Variante 1; hier ändern sich nur die
Farben.

**Zwei Zahlen dazu.** Im hellen Thema trägt die weiße Fläche gegen den
Seitengrund nur 1,07 : 1 — das ist in Ordnung, weil nicht die Fläche die
Kante zeigt, sondern der Rahmen. Im dunklen Thema ist die Fläche die der
Karte, sonst säße dort ein heller Fleck; und die Schrift ist etwas heller
als `--marke-ex`, weil das Marken-Navy auf einer Karte nur auf 4,25 : 1
käme. Mit `#428cd7` sind es 4,65 : 1 auf der Karte und 5,1 : 1 auf dem
Seitengrund.

### Variante 3 — der Warnknopf

**Wie Variante 2 gebaut, nur die Schrift ist die Warnfarbe.** *Löschen*,
*Version entfernen*, *Auf Werkseinstellung zurücksetzen*. In der CSS ist es
`button.danger`.

| | hell | dunkel |
|---|---|---|
| Fläche | `--knopf-flaeche` — dieselbe wie Variante 2 | dito |
| Schrift | `--danger` `#b3261e` | `--danger` `#ff8079` |
| Rahmen | `--line` | `--line` |

6,5 : 1 im hellen Thema, 6,7 : 1 auf einer dunklen Karte.

**Die Warnfarbe bleibt außerhalb der Marke.** Rot sagt etwas über die
Folge des Klicks, nicht über den Absender — siehe die Regel zu den
Statusfarben in *Regeln, nach denen Farbe vergeben wird*.

### Ausgegraut ist ein Zustand, keine Variante

> **Ausgrauen ändert die Farbe, nie die Form.** Ein Knopf, der gerade
> nichts tun kann, bleibt derselbe Knopf — gleiche Fläche, gleicher
> Rahmen, gleiche Maße. Er verliert nur seine Farbe und kommt in der
> Farbe seiner Variante zurück.

Variante 1 bleibt ausgegraut **gefüllt** — die Fläche wird eine
12-prozentige Tönung der Textfarbe. Sie wird nicht zum umrandeten Knopf:
Das sähe aus wie eine andere Variante, nicht wie derselbe Knopf ohne
Aufgabe.

Die Varianten 2 und 3 behalten ihre Fläche und verlieren nur die
Schriftfarbe an `--muted`.

Der praktische Grund für die Regel: *Prüfen* graut sich beim Klick selbst
aus, bis die Antwort da ist. Änderte sich dabei die Fläche, zuckte die
Zeile bei jedem Prüfen.

**Ausdrücklich verworfen:** die ausgegraute Variante 1 in einem
abgetönten Navy zu füllen. Das sähe nach „gedimmt, aber noch aktiv" aus,
und der Unterschied zu einem echten Knopf wäre eine Frage der Helligkeit
— zu wenig, um sich darauf zu verlassen.

*(Ausgegraute Bedienelemente sind von der Kontrastregel ausgenommen; hier
gilt keine Zahl. Der graue Text soll lesbar bleiben, aber schwächer sein
— das ist ja die Aussage.)*

---

## Die Karte und ihre drei Bereiche

Am 27.08.2026 festgelegt. **Das ist eine Verabredung über Begriffe, kein
Bauplan.** Es gibt kein `<header>` und kein `<footer>` in der Karte und
soll auch keines geben — die Einteilung dient dem Reden über Karten, nicht
dem Erzeugen von Hüllen.

Einen Namen hat trotzdem einer der drei Bereiche: die Fußzeile heißt
`.kartenfuss`. Nicht als Element, sondern als Klasse — sie braucht ihn,
weil sie ein Aussehen hat. Kopf und Inhalt brauchen keinen: Der Kopf ist
über `section > h2` ansprechbar, und der Inhalt ist alles übrige.

Eine Karte ist ein `<section>`. Sie hat drei Bereiche:

| Bereich | was dort steht |
|---|---|
| **Kopf** | die Überschrift (`h2`) und, wenn nötig, eine Unterzeile darunter — was die Karte ist, in einer Zeile |
| **Inhalt** | alles, wofür man die Karte öffnet. Kann alles sein, auch eine Unterkarte |
| **Fußzeile** | die letzte Zeile oder die letzten Zeilen. Darf mehrzeilig sein. Trägt `.kartenfuss` |

So sieht die Fußzeile aus: `--muted`, 0,82rem, **kursiv** — und ohne
Trennlinie darüber, der Abstand genügt. Die Kursive ist ihr Zeichen: Man
sieht der Zeile an, dass sie über den Inhalt spricht, statt ihn zu sein.
Farbe und Größe sind dieselben, die solche Zeilen vorher als
`class="muted small"` trugen; der Name fasst nur zusammen, was schon da
war.

Dazu eine Regel für jede Karte: **Der letzte Eintrag bringt keinen eigenen
Abstand nach unten mit** (`section > *:last-child { margin-bottom: 0 }`).
Sonst stehen unter ihm sein eigener Abstand *und* die Polsterung der Karte
— zusammen zwei Zentimeter, und die Karte wirkt unten aufgerissen.

### Was eine Kartenüberschrift nennt

Am 02.09.2026 festgelegt, nachdem siebzehn Überschriften nebeneinander
lagen. **Die Kartenüberschrift nennt, wovon die Karte handelt — als
Substantiv, nicht als Satz.** Dazu drei Schärfungen:

- **Kein Füllwort.** *Info*, *Übersicht*, *Verwaltung* sagen nichts über
  die Karte, sondern nur, dass sie eine ist.
- **Vorgang oder Gegenstand — je nachdem, was die Karte ist.** Wo man
  etwas tut, darf die Handlung dastehen: *Manuelle Registrierung* ist ein
  Formular, und das Formular ist der Gegenstand. Wo etwas gezeigt wird,
  steht die Sache: *Auslastung*, *Dienste*, *Speicherplatz*.
- **Der Reiter wird nicht wiederholt.** Die Karte steht auf einer Seite,
  deren Name in der Reiterleiste steht — und die klebt oben.

**Die Seitenkarte ist die Ausnahme, und sie bleibt es.** Sie nennt die
*Folge* und nicht den Gegenstand — „Kein Rechner findet seine Dateien",
nicht „Die Adresse hat sich geändert". Warum, steht unter *Die Seitenkarte*.

**Die Sprungmarke zieht mit.** Sie ist der Kartenname, klein geschrieben
und ohne Umlaute (`#quellenwaechter`, `#letzte-starts`) — wer eine Karte
umbenennt, benennt Sprungmarke, Hilfeanker und alle Verweise darauf mit.
*Das ist der Preis, und er ist beim Umbenennen zu bedenken, nicht danach.*

#### Der Durchgang vom 02.09.2026

Dreizehn von siebzehn erfüllten die Regel schon. Drei wurden geändert:

| vorher | jetzt | woran es lag |
|---|---|---|
| *Quelleninfo* | **Quellenwächter** | *Info* war das Füllwort — und dieses Dokument nannte die Karte an anderer Stelle längst so |
| *Zuletzt gestartet* | **Letzte Starts** | der einzige Satzfetzen unter allen Überschriften |
| *PXE BootMenü - Vorschau* | **Vorschau** | Bindestrich statt Halbgeviert, Binnenmajuskel, und *PXE* wiederholte den Reiter. Sprungmarke und Hilfeanker hießen ohnehin schon `vorschau` |

**Die Endpunkte behalten ihre Namen.** `/quelleninfo.json` und
`/quelleninfo/pruefen` heißen weiter so: Sie sind eine Schnittstelle, die
ein Skript ruft, und die bricht man nicht wegen einer Überschrift. Dass
Endpunkt und Kartenname auseinandergehen dürfen, stand schon vorher im
Quelltext.

**Eine vierte wurde geprüft und nicht geändert:** *Ersteinrichtung*.
Sie sieht auf den ersten Blick falsch aus, weil der erste Absatz der Karte
vom Zurücksetzen spricht und der Knopf *Werkseinstellung* heißt. Die Karte
trägt aber zwei Dinge — das Zurücksetzen **und** *IP-Adresse übernehmen* —,
und beide gehören zu dem, was man einmal am Anfang tut oder wenn der Server
weitergegeben wird. *Ersteinrichtung* ist die Klammer darüber; *Werkseinstellung*
wäre die Hälfte davon.

---

### Was in die Fußzeile gehört

Nicht alles, was unten steht. Die Fußzeile ist der Teil, der **über den
Inhalt spricht**, statt ihn zu sein: ein Verweis in die Hilfe, ein Hinweis
auf eine Einschränkung, wann etwas zuletzt lief.

**Und sie bezieht sich auf die ganze Karte**, nicht auf einen Teil davon.
Am 27.08.2026 von Markus so festgelegt: Was nur für eine Zeile, eine
Unterkarte oder einen einzelnen Wert gilt, gehört dorthin, wo es gilt —
nicht nach unten. Sonst muss der Leser raten, worauf sich der Satz
bezieht, und findet es erst durch Ausprobieren heraus.

Die Probe darauf ist einfach:

> Nimmt man die Fußzeile weg, fehlt der Karte **keine Angabe, die man zum
> Handeln braucht.** Fehlt danach etwas, war es Inhalt.

Deshalb hat nicht jede Karte eine. Die Karten in der Hilfe zum Beispiel
enden mit Fließtext — der ist ihr Inhalt und keine Fußzeile, auch wenn er
ganz unten steht.

### Verweise gehören in die Fußzeile

Am 27.08.2026 festgelegt. **Ein Verweis in die Hilfe ist ein Kartenfuß** —
er gilt der ganzen Karte, und zum Handeln braucht man ihn nicht.

Gibt es schon eine Fußzeile, wird der Verweis **darunter** gesetzt. Der
Fuß hat dann zwei Zeilen:

```html
<p class="kartenfuss">Gemessen beim Aufbau der Seite …</p>
<p class="kartenfuss"><a href="/hilfe#…">Wie … funktioniert →</a></p>
```

Beide tragen dieselbe Klasse; die Reihenfolge macht die Aussage. **Die
Aussage steht oben, der Weg nach draußen unten** — wer die Karte liest,
soll zuerst erfahren, woran er ist, und erst danach, wo mehr steht.

Damit sie als ein Fuß und nicht als zwei Absätze wirken, rückt
`.kartenfuss` nach unten enger zusammen als ein gewöhnlicher Absatz
(`margin-bottom: .2rem`).

### Eine Unterkarte darf ebenfalls eine Fußzeile haben

Am 27.08.2026 festgelegt. Die drei Bereiche gelten nicht nur für die
äußere Karte, sondern für **jede abgegrenzte Einheit mit eigener
Überschrift**: die Karte in der Karte (`.quellenkarte`,
`.eintragskarte`) ebenso wie eine Klappe (`details.klappe`).

Die Proben bleiben dieselben, sie beziehen sich dann nur auf die
Unterkarte statt auf die Karte: Was dort steht, muss für die ganze
Unterkarte gelten und darf zum Handeln nicht nötig sein.

Beispiel: In der Klappe *Speicherplatz — Detailansicht* ist „Gemessen wird
beim Aufbau dieser Seite und 30 Sekunden lang gemerkt …" die Fußzeile.
Sie sagt, wie die Zahlen darüber zustande kommen — für alle, und ohne
dass man sie zum Handeln braucht.

### Was daran heute noch nicht stimmt

Dieselbe Sorte Zeile steht in manchen Karten **oben**: Die Katalog-Karte
unter *Quellen* führt ihre Verweise („Was der Abgleich holt … →") direkt
unter der Überschrift. Mit den Begriffen sieht man erst, dass das eine
Fußzeile an falscher Stelle ist. Aufgeräumt ist es damit nicht — aber
benannt.

**Nicht jede erklärende Zeile ist eine Fußzeile.** Manche sind eher
Hilfe: Sie erklären, was man vor sich hat, und müssen deshalb *vor* dem
Inhalt stehen — etwa „Was jeder Eintrag unter `…/assets` wirklich belegt"
über der Tabelle in der Detailansicht. Ein bloßer **Verweis** in die Hilfe
gehört dagegen nach unten, siehe oben. Welche Sorte Text wohin gehört,
steht in *Drei Sorten Text*.

**Zwei Verweise bleiben bewusst stehen, wo sie sind:**

- `/hilfe#quellen-adressen` steht unter der Zwischenüberschrift *Adressen*
  innerhalb der Katalog-Karte und gilt nur diesem Teil. Der Abschnitt
  reicht bis ans Ende der Karte — sein Fuß läge also genau dort, wo schon
  der Fuß der Karte steht. Zwei Füße an derselben Stelle, die Verschiedenes
  meinen, wären schlechter als der jetzige Zustand.
- ~~Die Zeile auf *Systeme* („Was die Gruppen unterscheidet …") steht
  **zwischen** den Karten und gilt allen Gruppenkarten zusammen. In eine
  Karte gesteckt gälte sie plötzlich nur dieser einen. Sie trägt dafür eine
  eigene Klasse, `.seitenzeile`.~~ *Aufgelöst am 02.09.2026 — siehe*
  Keine Zeile zwischen den Karten*.*

### Keine Zeile zwischen den Karten

Am 02.09.2026 aufgelöst. Auf *Systeme* stand ein Verweis in die Hilfe
**zwischen** den Gruppenkarten, mit eigener Klasse `.seitenzeile`. Die
Begründung von damals: Er gilt allen drei Karten, und in eine gesteckt
gälte er nur dieser einen.

**Markus' Einwand, und er schlägt das:** *Die drei Karten sind nicht
gesetzt.* Im geplanten Offline-Betrieb fällt *Online-Installationen* weg,
und *Rettung und Wartung* soll sich ausblenden lassen. Dann hängt eine
Zeile über einer einzigen Karte und behauptet, sie gelte allen — oder über
gar keiner.

**Eine Karte trägt ihren Weg in die Hilfe selbst.** Der Verweis steht
seither im Fuß **jeder** der drei Karten, dreimal derselbe. Das ist keine
Doppelung, die man auflösen müsste, sondern der Aufbau: *Was zur Karte
gehört, steht in der Karte* — auch wenn daneben eine zweite mit demselben
Fuß steht.

**Die Hälfte, die dabei entfallen ist.** Die alte Zeile trug zwei Verweise
in einem: *„Was die Gruppen unterscheidet"* führte auf `#systeme-gruppen`
— dorthin zeigt das Fragezeichen im Kartenkopf ohnehin —, und *„warum hier
nur steht, was startet"* auf `#systeme-inhalt`, wohin sonst nichts führte.
Im Kartenfuß steht deshalb nur noch die zweite Hälfte.

**Die Klasse `.seitenzeile` ist entfallen**, sie hatte keinen zweiten
Benutzer. Was zwischen den Karten bleibt, ist der NFS-Befund — und der
gehört dorthin, weil er die betroffenen Einträge namentlich nennt und
verschwindet, sobald NFS steht.

### Die Seitenkarte

Gebaut am 28.08.2026. Eine Karte wie jede andere — Überschrift, Inhalt,
Kartenfuß —, aber sie gehört keiner Seite. Sie steht in `base.html`
unterhalb der Reiter und damit auf **allen** Seiten, weil ihr Befund dem
Server gilt und nicht dem Reiter, auf dem jemand gerade steht.

Drei Stufen, eine Ampel. Welche gilt, hängt nicht daran, wie schlimm etwas
klingt, sondern daran, **wann jemand handeln muss**:

| Klasse | Farbe | Bedingung |
|---|---|---|
| `stufe-fehler` | rot | Der Server erfüllt seine Aufgabe nicht — **jetzt** handeln |
| `stufe-warnung` | gelb | Eingeschränkt oder darauf zulaufend — **bald** handeln |
| `stufe-info` | blau | Wissenswert; **niemand** muss deswegen aufstehen |

Stehen mehrere gleichzeitig, dann in dieser Reihenfolge — dringend zuerst.
Ohne diese Grenze bekäme jede Warnung eine rote Karte, und Rot hieße nach
zwei Wochen nichts mehr.

Die mittlere Stufe hieß bis zum 28.08.2026 enger: *„läuft auf einen roten
Zustand zu"*. Beim Durchgang durch die Oberfläche (siehe unten) fiel auf,
dass damit ein ganzer Fall herausfällt — ein ausgefallener `nfs-server`
läuft auf gar nichts zu, er ist bereits kaputt, nur eben nicht ganz.
**Markus' Regel seitdem: Gelb heißt Achtung, nicht Halt.** Eingeschränkt
zählt genauso wie zulaufend.

**Zugeklappt, auch der Fehler.** Sichtbar ist nur die Überschrift; der
Inhalt kommt über die `.klappe` von weiter unten — `<details>` mit
`<summary>`, kein Skript. Drei Befunde sind damit drei Zeilen statt einer
halben Seite. Die drei Gründe gegen eine offene Fehlerkarte: Sie wäre das
Erste, Größte und oft Einzige auf der Seite; wer den Fehler selbst
verursacht hat, weiß längst Bescheid; und wer nicht, soll bewusst hinsehen
statt vorbeizuscrollen.

**Der Preis steht in der Überschrift.** Sie ist zugeklappt das Einzige, was
jemand sieht, und muss deshalb die *Folge* nennen, nicht den Vorgang:
„Kein Rechner findet seine Dateien", nicht „Die Adresse hat sich geändert".

**Warum unterhalb der Reiter und nicht darüber:** Der `header` ist Kopf und
Navigation, ein Befund ist Inhalt. Vor allem aber schöbe eine auftauchende
Karte über den Reitern die Navigation nach unten und beim Verschwinden
wieder hoch — Reiter werden aus dem Gedächtnis angesteuert, nicht gelesen.
Und der Seitenkopf soll einmal ein durchgehendes Navy-Band werden; dort läge
die Karte im Weg.

Die Farbwerte stehen in *Die Farbtoken*, die Rechnung dazu in *Regeln, nach denen Farbe vergeben wird*. Wo die Befunde
entstehen: `webui/befunde.py`. Der Text je Befund:
`templates/befunde/<kennung>.html` — dort, wo aller andere Text auch steht.
Das Modul entscheidet nur, *ob* ein Befund gilt, welche Stufe er hat und
mit welchem Satz er zugeklappt dasteht.

**Der erste Fall ist der Adressbefund.** Er stand bis dahin als `hint` auf
*Server Health* und noch einmal unter *Einrichtung* — und auf den drei
anderen Reitern gar nicht. Beide Absätze sind entfallen: Unter
*Einrichtung* bleibt der Arbeitsschritt, der ihn behebt, aber nicht mehr
die Feststellung, die zwei Handbreit darüber schon steht.


### Eine Karte zur Kenntnis nehmen

Gebaut am 02.09.2026. **Eine Warnung lässt sich wegklicken, ein Fehler
nicht.** Wer eine gelbe oder blaue Karte zur Kenntnis genommen hat,
bekommt sie nicht auf jeder Seite noch einmal — die volle Platte stand
sonst bis zum Aufräumen am Wochenende überall.

**Weggeklickt heißt nicht weg.** Die Karte schrumpft auf eine graue
Zeile, aufklappbar:

```
2 Befunde zur Kenntnis genommen
```

*Das ist der Punkt und keine Halbheit.* Wer nicht selbst geklickt hat,
findet den Befund trotzdem; ein Kollege sieht dieselbe Seite, nur
eingeklappt. Ohne das wäre Wegklicken ein Weg, dem Server anzusehen, dass
alles in Ordnung ist, obwohl es das nicht ist.

**Rot hat keinen Knopf**, und der Endpunkt nimmt auch keinen an: Ein
Server, der seine Arbeit nicht tut, darf nie aussehen wie einer, der sie
tut. Die Prüfung steht auf dem Server, nicht in der Vorlage — ein Knopf,
den es im HTML nicht gibt, ist kein Schloss.

#### Die Form der grauen Zeile

Kein Rand, keine Fläche, keine Ampel — `.bekanntzeile` ist gedämpfter
Text in `--muted`, so groß wie ein Kartenfuß. Sie soll **da sein und
nichts verlangen**; jede Farbe daran hieße wieder *sieh her*.

Aufgeklappt stehen die Befunde wie zuvor, nur ohne Fläche: `.bekannt`
trägt links eine 3px-Kante in der Farbe ihrer Stufe, damit sichtbar
bleibt, was es war. Dieselbe Bauart wie ein Zitatblock — eine Kante sagt
*hier gehört etwas zusammen*, ohne eine Karte zu behaupten.

#### Die Karten ziehen von selbst nach

Jede Seite holt sich `/befunde.html` alle zehn Sekunden. **Nicht nur
Server Health** — ein Befund gilt dem Server und nicht dem Reiter, und
aus demselben Grund steht er in `base.html`.

Zehn Sekunden, nicht fünf: Die Auskünfte dahinter sind ohnehin zehn
Sekunden gepuffert (`dienste.zustaende`, `befunde.NETZ_TAKT`). Öfter zu
fragen brächte dieselbe Antwort.

**Eine aufgeklappte Karte wird nie ersetzt.** Wer den Weg hinaus im
Kartenfuß abliest, soll den Text nicht unter dem Blick weggenommen
bekommen — der Tausch wartet dann bis zum nächsten Takt. Geprüft wird
zweimal: vor der Frage und noch einmal vor dem Einsetzen, denn dazwischen
kann jemand aufklappen.

*Warum welche Stufe sich wegklicken lässt, wann eine Karte wiederkommt
und wo das Weggeklickte liegt, steht nicht hier* — das ist eine
Entscheidung über das Projekt und keine über diese Oberfläche.

---

### Was nicht in eine Seitenkarte gehört

Der Durchgang durch alle `hint`-Absätze, 28.08.2026. **39 Stellen, davon
18 in der Hilfe und 21 in der Oberfläche. Einer zieht um.** Das ist kein
enttäuschendes Ergebnis, sondern die Bestätigung, dass `.hint` überwiegend
das tut, wofür es da ist.

Die 18 in der Hilfe sind gar keine Befunde, sondern ein Schreibmittel:
*„Der Kern in einem Satz"*, *„Wo die Grenze verläuft"*. Sie heben in einem
langen Text den Satz hervor, auf den es ankommt. Dass sie dieselbe Klasse
tragen wie ein Befund in der Oberfläche, ist eine Doppelnutzung — sie fällt
niemandem auf, weil die Hilfe keine Befunde kennt, und sie zu trennen wäre
Arbeit ohne Ertrag.

Die 21 in der Oberfläche zerfallen in fünf Gruppen. **Vier davon sind
grundsätzlich keine Seitenkarten:**

| Gruppe | Anzahl | warum sie bleibt |
|---|---|---|
| **Meldungsplätze** — `meldung`, `hinweis`, die Rückfragen beim Holen und Hochladen | 8 | Antworten auf einen Klick, den jemand gerade getan hat. Ein Ereignis, kein Zustand |
| **Leerzustände** — „Noch kein Client bekannt", „Noch nichts gestartet" | 4 | Der Zustand *einer Karte*, und zwar der normale am Anfang. Sie stehen richtig dort, wo sonst die Liste stünde |
| **Erklärungen** — „Die Netzkonfiguration ändert dieser Server nicht" | 3 | Sagen, was etwas *ist*, nicht was gerade nicht stimmt |
| **„Kann ich nicht sagen"** — Belegung nicht abfragbar, Netzkonfiguration nicht lesbar | 2 | Eine Karte, die ihre eigene Auskunft nicht bekommt. Das ist ihr Zustand, nicht der des Servers |

Bleiben **vier echte Zustandsbefunde** — und drei davon bleiben trotzdem,
wo sie sind. Das sind die interessanten Fälle:

- **„Noch kein Eintrag ist startbereit"** (*Server Health*, Betriebssysteme)
  klingt nach einer roten Karte und ist die Falle: Genau so sieht ein
  **frisch aufgesetzter Server** aus. Der Katalog bringt Einträge mit,
  die Dateien holt man erst. Eine rote Karte beim ersten Öffnen wäre der
  Fehlalarm, den `serveradresse.abweichung()` an anderer Stelle
  ausdrücklich vermeidet.
- **„Nicht erreicht: …"** (*Server Health*, Quellenwächter) war in der
  Vorschau vom 28.08.2026 noch das Beispiel für die Infokarte. Beim
  Durchgang fiel auf, dass es keines ist: Der Satz sagt nicht, wie es dem
  Server geht, sondern **wie frisch die Zahlen in genau dieser Karte
  sind.** Von der Tabelle getrennt, die er einschränkt, wird er
  schlechter, nicht besser.
- **„n Einträge brauchen NFS und finden keins"** (*Systeme*) nennt die
  betroffenen Einträge namentlich — und das ist der Grund, es dort zu
  lassen: Der Befund ist ohne die Liste die halbe Auskunft, und die Liste
  gehört auf die Seite, auf der man die Einträge sieht.

**Der eine, der umgezogen ist:** *„Ein Dienst läuft nicht"* (*Server
Health*, Dienste) — und zwar aufgeteilt, denn die vier Dienste sind nicht
gleich viel wert:

| Dienst | Karte | warum |
|---|---|---|
| `dnsmasq`, `nginx`, `pxeweb` | rot | Fällt einer aus, kommt **kein** Rechner mehr durch — der eine beantwortet die PXE-Anfrage, der zweite liefert Kernel und Initrd, der dritte erzeugt die Boot-Skripte |
| `nfs-server` | gelb | Nur die großen Live-Systeme starten nicht; alles andere läuft weiter |

Dass man `nginx` und `pxeweb` im Ausfall kaum je zu sehen bekommt — ohne
sie gibt es keine Seite, auf der eine Karte stehen könnte —, ist kein
Grund, sie herauszulassen: Wer das tut, verlässt sich darauf, dass zwei
Dinge immer zugleich ausfallen.

Die Tabelle in der Dienste-Karte bleibt, was sie war. Sie sagt, welcher
Dienst wofür da ist — das ist eine Auskunft, keine Meldung.

**Dazugekommen ist einer, der vorher gar keinen Satz hatte:** die volle
Platte, ab derselben Schwelle, ab der sich der Balken „voll" färbt.
Damit die beiden nicht auseinanderlaufen, steht die Zahl seit dem
28.08.2026 an einer Stelle — `dienste.VOLL` — und der Balken holt sie
sich von dort.

Bei dieser Karte nennt die Überschrift ausnahmsweise den **Zustand** und
nicht die Folge: *„Die Platte ist fast voll"*. Ob der Platz noch reicht,
hängt daran, wie groß das nächste Abbild ist, und das wissen wir nicht.
Behaupten wäre schlimmer als beschreiben.

**Was der Durchgang außerdem ergeben hat:** Die blaue Karte hat keinen
einzigen Kandidaten. Kein heutiger Absatz sagt „wissenswert, niemand muss
handeln, und es gilt dem Server". Die beiden natürlichen Fälle sind noch
nicht gebaut — die Versions-Kachel mit GitHub-Abgleich
(vorgemerkt) und ein Offline-Schalter, den es noch
nicht gibt. **Blau bleibt deshalb vorerst ungenutzt**, und das ist in
Ordnung: Eine Stufe, die bereitsteht, kostet nichts.

---

## Drei Sorten Text

Am 27.08.2026 festgelegt, ausgelöst vom NFS-Hinweis auf *Systeme*: Dort
stand der längste Text der Seite — dass ein Eintrag NFS braucht, warum die
Bauart das verlangt, dass der Export fehlt, wie man ihn einrichtet. Der
erste Halbsatz war ein Befund, der Rest Erklärung, und beides stand im
selben roten Kasten.

| Sorte | wann sie erscheint | wo sie steht |
|---|---|---|
| **Befund** | nur wenn etwas der Fall ist | dort, wo es auffällt |
| **Feldhilfe** | immer | am Feld — man braucht sie zum Ausfüllen |
| **Erklärung** | immer | in der Hilfe, verlinkt aus dem Kartenfuß |

### Wie ein Befund gebaut ist

**Was ist — was daraus folgt — wo es sich beheben lässt.** In dieser
Reihenfolge, in einem oder zwei Sätzen. Das *Warum* gehört nicht hinein;
wer es wissen will, folgt dem Verweis.

```
1 Eintrag braucht NFS und findet keins: Linux Mint.     ← was ist
Er wird deshalb nicht angeboten.                        ← was folgt
Einrichten lässt sich NFS unter Einrichtung.            ← wo beheben
```

### Die Probe

Dieselbe wie beim Kartenfuß, nur andersherum:

> **Verschwindet der Text, sobald das Problem behoben ist?** Dann ist er ein
> Befund. Steht er immer da, ist er Erklärung — und gehört in die Hilfe.

Die Feldhilfe ist die Ausnahme, die keine ist: Sie steht immer da, bleibt
aber am Feld, weil man sie zum Ausfüllen braucht. Sie ist Teil des Inhalts,
nicht Hintergrund.

---

## Die Hilfe: ein Abschnitt je Karte

Am 27.08.2026 festgelegt. **Jede Karte hat einen Abschnitt in der Hilfe,
und jede Karte trägt ein Zeichen, das dorthin führt.** Wer wissen will, was
eine Karte tut, soll nicht suchen müssen; wer es weiß, soll nicht jedes Mal
einen erklärenden Satz überlesen.

### Das Zeichen

Ein `?` in einem Ring, rechts im Kartenkopf — an jeder Karte
dasselbe, an derselben Stelle. Ein Zeichen und etwas CSS, keine geladene
Schrift und keine Grafik.

Der Ring ist nicht Zierde: Er macht daraus sichtbar ein Bedienelement und
gibt der Klickfläche ihre Größe. Ein nacktes Fragezeichen ist acht Pixel
breit — das trifft man mit der Maus, aber nicht mit dem Finger. Er trägt
`--accent-mig`, die mig-Hälfte der Marke.

Für Vorlesegeräte trägt das Zeichen den Namen „Hilfe zu dieser Karte" —
ein Satzzeichen allein ist für sie stumm.

**Ein Verweis je Karte, nicht mehr.** Vorher standen Hilfeverweise als Sätze
in den Fußzeilen, teils zwei in einer Zeile.

### Zeichen heißt Hilfe, Text heißt Weg

Nicht jeder Verweis ist Hilfe. „Was hier hereinkommt, steht danach unter
*Systeme* →" ist ein **Wegweiser** — die nächste Station im Arbeitsablauf,
nicht eine Erklärung. Solche Sätze bleiben Text und stehen weiter im
Kartenfuß. Damit sagt schon die Form, worum es geht.

### Wie eine Kartenhilfe aufgebaut ist

Fünf Fragen, in dieser Reihenfolge, als `h4`:

1. **Wofür ist diese Karte da?** — die Frage, die sie beantwortet, in einem Satz
2. **Was steht darin?** — die Angaben, Spalten und Abzeichen und wie sie zu lesen sind
3. **Was kann man hier tun?** — je Knopf und Feld: was es auslöst, was hineingehört
4. **Was passiert dabei — und was nicht?** — Folgen, Grenzen, die häufigen Irrtümer
5. **Was, wenn nichts dasteht oder etwas gemeldet wird?** — der leere Zustand und die Befunde

**Die vierte ist die wichtigste.** Dort stehen die Sätze, die niemand von
selbst schreibt: „Gemessen wird nur dieser Server, nicht der bootende
Rechner." Eine Überschrift, die danach fragt, erzwingt sie.

**Die dritte darf „nichts" lauten.** Bei einer Karte, die nur anzeigt, ist
das die Antwort — und sie gehört hingeschrieben, statt offengelassen zu
werden.

Die Fragen sind ein **Gerüst, kein Formular**: Sie werden zuerst überall
hingeschrieben, damit die Lücken sichtbar werden. Was am Ende leer geblieben
ist, wird entfernt.

**Nicht im Schema:** wie oft sich die Karte auffrischt. Das beantwortet der
Kartenfuß (*Aktualisierung alle 5 Sekunden*), und zweimal dieselbe Auskunft
an zwei Orten ist genau die Doppelung, die wir sonst auflösen.

### Die neun Kapitel und was in welches gehört

Bis August 2026 stand vorn ein Kapitel *Allgemeines*. Markus' Befund am
27.08.2026: **Das ist kein Thema, sondern ein Sammelbecken** — darin mischte
sich, was diesen Server angeht, mit dem, was allgemein gilt. Ein Kapitel, in
das alles passt, sagt niemandem, ob etwas hineingehört.

Seitdem sind es neun Kapitel mit je einer prüfbaren Frage:

| | Frage, die darüber entscheidet |
|---|---|
| **1. Erste Schritte** | Braucht das jemand, der diesen Server zum ersten Mal sieht? |
| **2.–7. je Register** | Beschreibt es **eine Karte** dieses Registers? |
| **8. Häufige Fragen** | Ist es ein Symptom mit einem Griff, in einer Bildschirmhöhe? |
| **9. Nützliches** | Liest man es einmal und schlägt es danach nach? |

**Erste Schritte folgt sinngemäß dem Kartenschema** — dieselben fünf Fragen,
auf den Server statt auf eine Karte bezogen: *Wofür ist dieser Server da? ·
Was braucht er, damit es geht? · Was tut man zuerst? · Was passiert dabei —
und was nicht? · Was, wenn nichts passiert?* Die vierte passt fast
unheimlich: *Was passiert* ist der Ablauf eines Netzwerkstarts, *und was
nicht* ist die Tabelle der Dinge, die dieser Server bewusst unterlässt.

**Der Ablauf eines Netzwerkstarts steht in *Nützliches*, nicht vorn** —
Markus' Entscheidung, und der Abschnitt begründet sie selbst: „Wer weiß,
welcher Schritt gerade scheitert, findet die Ursache meist sofort." Das ist
ein Nachschlage-Moment. Wer sich einen Bootserver hinstellt, weiß, was ein
Netzwerkstart ist.

**Warum das Lange nicht ins FAQ darf:** Das FAQ verweist mit „Einzelheiten
unter …" auf die langen Blöcke. Stünden sie darin, verwiese es auf sich
selbst — und zwischen zehn kurzen Antworten stünden zwei Aufsätze.

### Der Trenner zwischen zwei Kartenhilfen

Eine Haarlinie in `--line`, darauf ein Stück in den Markenfarben — navy nach
türkis, wie im Logo. **Das farbige Stück wächst zum Kapitelende hin**; beim
letzten Abschnitt läuft es durch. So sieht man beim Lesen, wie weit man ist,
ohne dass irgendwo eine Zahl steht.

Gezählt wird mit `:nth-last-of-type`, also vom Ende her. Deshalb muss die
Regel nicht wissen, wie viele Abschnitte ein Kapitel hat — sie gilt für
zwei so wie für neun, und kommt eine Kartenhilfe dazu, verschieben sich die
Längen von selbst.

---

## Form und Maß

| | |
|---|---|
| Schrift | `system-ui`, 15px, Zeilenhöhe 1,55 — die Schrift des Betriebssystems, keine geladene |
| Textbreite | 60rem, mittig — Seitenkopf, Inhalt und Fußzeile teilen dieselbe Kante |
| Überschriften | h1 1,4rem · h2 1,25rem · h3 1,2rem · h4 0,78rem — siehe unten |
| Rundungen | 8px Karten · 6px Knöpfe · 999px Pillen |
| Knöpfe | `.15rem .5rem`, 0,78rem — eine Größe, siehe *Knöpfe* |
| Felder | `.05rem .28rem`, 0,9rem — Textfelder und Auswahlfelder, siehe unten |

**Beide Themen sind gleichwertig.** Es gibt keinen Umschalter in der
Oberfläche: Sie folgt dem Betriebssystem über `prefers-color-scheme`. Ein
Umschalter wäre eine Einstellung, die gespeichert und erklärt werden will,
und die Antwort darauf hat der Rechner schon.

### Überschriften tragen die Marke

**h2 und h3 stehen in Navy** (`--ueberschrift`), h1 und h4 nicht. Bis
August 2026 standen alle in der Textfarbe und kaum größer als der
Fließtext — eine Kartenüberschrift ging im Absatz darunter unter. Jetzt
sagt die Farbe, dass hier etwas anfängt, und die Größe, welche Ebene es
ist.

**Warum kein Türkis als Schrift:** Es käme auf hellem Grund auf 2,2:1. Die
zweite Markenhälfte trägt hier Flächen — den wachsenden Trenner (*Die Hilfe: ein Abschnitt je Karte*) und
den Ring des Hilfezeichens. So kommen beide Hälften auf der Seite vor,
jede dort, wo sie trägt.

**Warum das rohe Marken-Navy und nicht `--accent`:** 11,3:1 gegen die
Karte. Dass es der Textfarbe nahekommt (1,5:1), stört bei einer
Überschrift nicht — sie muss sich nicht als anklickbar zu erkennen geben,
dafür sorgen Größe und Fettung. Bei einem Verweis ist genau das der Grund,
warum dort `--accent` steht.

**Im dunklen Thema ein eigener Wert** (`#428cd7`). Das aufgehellte
Marken-Navy käme auf der Karte nur auf 4,25:1. Für die fette 20px-h2
reichte das — große Schrift, 3:1 —, für die 17,6px der h3 nicht mehr.

### Bei gesperrten Versalien täuscht die Zahl im Stylesheet

Die vierte Ebene (h4) steht in gedämpften Großbuchstaben. Sie stand auf
0,9rem und wirkte damit **größer als die 1,2rem-Überschrift darüber** —
gesperrte Versalien tragen über die ganze Zeile Versalhöhe, gemischte
Schrift nur bei wenigen Buchstaben. „WOFÜR IST DIESE KARTE DA?" stand über
dem Kartennamen, obwohl es eine Ebene darunter liegt.

Auf 0,78rem stimmt der Eindruck. **Merksatz:** Bei Versalien nicht die
Zahl vergleichen, sondern das, was im Browser danebensteht.

### Überschrift links, Weg rechts

Dieselbe Zeile an drei Stellen — eine Anordnung, drei Orte:

| | Überschrift | rechts daneben |
|---|---|---|
| Karte | *Auslastung* | das Hilfezeichen `?` |
| Hilfekapitel | *Server Health* | **Zum Register →** |
| Kartenhilfe | *Auslastung* | **Zur Karte →** |

Damit ist der Weg in beide Richtungen derselbe Griff: Karte → `?` →
Kartenhilfe → *Zur Karte* → zurück. Dafür hat **jede Karte eine
Sprungmarke** bekommen (der Name der Karte, klein geschrieben:
`/#speicherplatz`, `/quellen#katalog`).

**Ohne den Namen.** Der Verweis hieß erst *Zum Register Server Health* —
direkt neben der Überschrift *Server Health*. Der Name steht schon links;
ihn rechts zu wiederholen wäre die Doppelung, die wir sonst auflösen.

**Wer keinen Rückweg bekommt:** Abschnitte, die ein Thema beschreiben und
keine Karte — *Der Weg durch die Reiter*, *Wenn ein Eintrag NFS braucht*,
*Erproben, dann freigeben*, *Einträge umbenennen*. Es gibt nichts, wohin
der Verweis zeigen könnte.

**Falle beim Umbau:** Der wachsende Trenner (*Die Hilfe: ein Abschnitt je Karte*) hing an
`.kapitel > h3` und zählt vom Kapitelende her. Die Überschrift sitzt jetzt
in einem Kopf, also hängt er an dem — und der Kapitelkopf musste vom
`<div>` zum `<header>` werden, sonst hätte `:nth-last-of-type` ihn als
erstes `div` mitgezählt und alle Balken um eine Stufe verschoben. **Wer
den Trenner anfasst, prüft die Elementart der Nachbarn mit.**

### Eine Größe für alle Felder

Textfelder und Auswahlfelder tragen `padding: .05rem .28rem` und
`font-size: .9rem` — die Maße der Zeilen unter *Quellen*. Ein Feld neben
einem Knopf soll dieselbe Zeile füllen, nicht eine höhere.

Auch hier gab es vorher mehrere Regeln nebeneinander: die Grundgröße
(`.35rem .5rem` / 15px), `table.eng` (`.25rem .4rem` / 0,9rem) und
`.kompakt` beziehungsweise `.ausgabe` (die heutigen Werte). Die drei
Sonderregeln sind entfallen.

**Drei Felder bleiben ausgenommen**, weil sie keine gewöhnlichen Felder
sind:

| | warum |
|---|---|
| `.namensfeld` | sieht aus wie eine Überschrift und ist eine — man kann sie bearbeiten |
| `.bezeichnung` | dasselbe in der Eintragskarte |
| `.folge` | ein 2rem breiter Kasten für eine Zahl, kein Textfeld |

Mit den vereinheitlichten Feldern fiel nebenbei ein Kunstgriff weg: Die
beiden Überschrift-Felder trugen einen doppelten Selektor
(`table.eng .namensfeld input…`), nur um die Tabellenregel zu
überstimmen. Ohne diese Regel braucht es ihn nicht mehr.

### Das Band im Seitenkopf

**Der Seitenkopf beantwortet eine Frage, die man auf jeder Seite hat: *Wo
bin ich, und mit welchem Server rede ich?*** Titel und Reiter sagen das
Wo, die Adresse das Womit, das Logo das Wer. Damit ist auch entschieden,
was dort **nicht** hingehört: kein Zustand, keine Zahl, kein Befund.

Seit dem 02.09.2026 liegt die Kopfzeile auf einem Navy-Band. **Nur die
Kopfzeile** — die Reiter bleiben auf dem Seitengrund. Das ist kein halber
Schritt, sondern der Punkt: Ein Band unter den Reitern zwänge die ganze
Navigation in eine zweite Palette, weil `--muted` auf dem Band nur auf
2,4 : 1 käme.

**Das Band trägt in beiden Themen dasselbe Navy** (`--band`, `#063b6f`).
Alles darauf misst sich gegen das Band und nicht gegen den Seitengrund —
ein Themenwechsel ändert dort also nichts, und alle Zahlen gelten hell wie
dunkel:

| auf dem Band | Wert | |
|---|---|---|
| Titel | `--band-schrift` `#ffffff` | 11,27 : 1 |
| Adresse | `--band-neben` `#a9c0d8` | 6,02 : 1 |
| Logo, „ex" | `#b8dcfb` | 7,87 : 1 |
| Logo, „mig" | `--marke-mig` | 4,77 : 1 |

**Deshalb steht dort `#063b6f` und nicht `--marke-ex`:** Das Token hellt
im dunklen Thema auf `#3585d4` auf, und ein Band, das mitschaltet, würde
alle vier Zahlen bewegen.

#### Die Reiterleiste bleibt oben stehen

**Der Seitenkopf sind zwei Geschwister und kein Element.** Das Band scrollt
weg, die Reiterleiste klebt am oberen Rand: Wer unten in einer langen Liste
steht, soll den Reiter wechseln können, ohne erst hochzufahren.

**Warum getrennt und nicht ineinander:** Ein `position: sticky` klebt nur
innerhalb seines Elternteils. Läge die Navigation im Kopf, wäre ihr
Spielraum genau die Höhe des Kopfes minus ihrer eigenen — also null, und
sie klebte gar nicht. *Das ist die Falle, in die man hier zuerst tritt.*

Zwei Dinge sind an der Leiste Pflicht, und beide fallen erst beim Scrollen
auf: **ein Hintergrund**, sonst scheinen die Karten durch, und **die volle
Breite**, sonst läuft der Inhalt seitlich an ihr vorbei. Sie schiebt sich
dafür mit `margin: 0 -1.25rem` aus der Seitenpolsterung — wie das Band.

#### Was ebenfalls klebt, muss darunter halten

Die Kopfzeilen der langen Tabellen (`table.eng thead th`) kleben seit dem
27.08.2026 bei `top: 0`. Mit der Reiterleiste davor verschwänden sie
dahinter. Sie holen ihren Abstand deshalb aus `--leiste-hoehe`.

**Diese Zahl wird gemessen, nicht gepflegt.** Sie hängt daran, wieviele
Zeilen die sieben Reiter brauchen, und das sind je nach Fensterbreite
eine bis vier:

| Fensterbreite | Zeilen | Höhe |
|---|---|---|
| ab 662px | 1 | 3,42rem |
| 380 – 661px | 2 | 6,09rem |
| 300 – 379px | 3 | 8,77rem |
| darunter | 4 | 11,44rem |

Vier Stufen im Stylesheet zu pflegen wäre eine Fehlerquelle mit Ansage.
`base.html` misst die Leiste stattdessen und schreibt den Wert in die
Variable. **Der Wert in `style.css` bleibt als Rückfall stehen** und stimmt
für die einzeilige Leiste — läuft das Skript nicht, sieht die Seite richtig
aus, und nur im schmalen Fenster gerät eine Tabellenkopfzeile hinter die
Leiste.

*Gemessen am 02.09.2026 auf dem laufenden Server.*

#### Warum das Logo eine dritte Datei bekommt

Auf dem Band käme das Marken-Navy des Logos auf **1,0 : 1** — es wäre
schlicht nicht da. `exmig-logo-band.svg` trägt deshalb ein helles Blau,
und anders als die gewöhnliche Fassung **schaltet es nicht mit dem
Thema**: Sein Grund ist in beiden derselbe. Erzeugt wird es wie die
anderen aus `marke/logo-bauen.py`; dort steht die Farbe als `EXB`.

Damit hat das „ex" drei Werte, und jeder hat seinen Grund:

| Fassung | Wert | wofür |
|---|---|---|
| `EX` | `#063b6f` | heller Seitengrund |
| `EXD` | `#3585d4` | dunkler Seitengrund |
| `EXB` | `#b8dcfb` | das Band, in beiden Themen |

#### Verworfen, und warum

- **Ein weißes „ex".** Es trägt mit 11,3 : 1 mühelos, aber dann ist die
  linke Worthälfte keine Farbe mehr, sondern Abwesenheit — das Logo liest
  sich als *ein* helles Wort mit türkisem Ende. Die Zweifarbigkeit ist die
  Aussage der Marke; sie kostet hier zu viel.
- **Ein Orange für das „ex".** Am 02.09.2026 durchgerechnet und angesehen:
  Es trägt auf dem Band (3,2 bis 5,3) und macht die Fuge im Logo so
  deutlich wie nichts sonst. Es scheitert nicht an einer Zahl, sondern
  daran, dass es eine **dritte Markenfarbe** wäre — eine Entscheidung über
  Exmig und nicht über diese Oberfläche.
- **Ein hellerer Ton für das „ex" knapp über `#3585d4`.** Zwischen
  `#4491dc` und `#8ac4f6` fällt der Abstand zum Türkis unter 1,6 : 1, bei
  `#66acee` sogar auf 1,02 — beide Worthälften wären gleich hell und die
  Fuge verschwände für jeden, der Farben schlecht unterscheidet.
  `#b8dcfb` liegt mit 1,65 : 1 wieder darüber.
- **Ein heller Seitenkopf statt eines Bandes.** Weiß wäre der einzige
  helle Ton gewesen, der nichts verschlechtert — er hätte sogar den
  Nebentext von 4,41 auf 4,74 gehoben. Verworfen zugunsten des Bandes:
  Der Kopf soll als eigene Ebene lesbar sein, nicht als hellere Fläche.
  *Der Nebentext bleibt damit unter der Norm — siehe* Der Seitengrund kommt aus der Marke.

---

### Was in der Fußzeile steht

**Die Fußzeile beantwortet: *Welche Fassung ist das, und wo geht es
weiter?*** Am 02.09.2026 danach ausgeräumt. Sie trägt drei Dinge:

```
MARLEI Boot  ·  Version: v1.0-3-g1b8f106  ·  AGPL-3.0  ·  Quelltext
```

| | |
|---|---|
| **Name** | steht auch im Band — aber das scrollt weg |
| **Version** | `versionsstand.kurz()` — was `install.sh` aus `git describe --tags --always --dirty` gestempelt hat |
| **Lizenz** | verlinkt auf das Kapitel *Lizenz und Förderung* in der Hilfe |
| **Quelltext** | der Verweis, den AGPL §13 für eine über das Netz benutzte Oberfläche nahelegt |

**Vier Angaben, und der Punkt allein trennt sie nicht.** Mit dem
gewöhnlichen Wortabstand liest sich die Zeile als ein Satz durch. Die
Trennpunkte tragen deshalb `.fusstrenner` mit `margin: 0 .5rem` — erst
der Abstand macht aus der Zeile vier Angaben.

**Das Wort *Version:* steht dabei**, statt die Nummer für sich sprechen zu
lassen. Ohne es liest sich `MARLEI Boot debb6cf-dirty` wie ein
zusammengesetzter Produktname.

**Die Probe für diese Fläche:** *Steht der Wert auch auf einer Karte,
gehört er nicht in die Fußzeile.*

**Der Name steht doppelt, und das mit Grund.** Er steht auch im Band —
aber das scrollt weg, seit nur noch die Reiterleiste klebt. Wer unten
angekommen ist und einen Fehler meldet, hat Name und Version in einer
Zeile beieinander, zum Herauskopieren.

**Fehlt der Stand, steht dort nichts.** `versionsstand.py` rät nicht: Eine
leere Angabe heißt *„diese Anwendung ist nicht über `install.sh`
hierhergekommen"*, und das ist etwas anderes als Version 0.

#### Was herausgeflogen ist

- **Menü-Timeout und Standardauswahl.** Beide kommen aus
  `/etc/pxeweb.env` und stehen unter *Einrichtung* in der Karte
  *Einstellungen* — dort mit einer Zeile, was sie bewirken. In der
  Fußzeile standen sie ohne Erklärung und ohne Anlass.
- **Die Statusabfrage.** `/health` liefert JSON. Nützlich für ein Skript,
  verwirrend für einen Menschen, der darauf klickt. Sie gehört in der
  Hilfe beschrieben, nicht als Verweis in die Oberfläche.
- **Ein zweiter Weg in die Hilfe.** War als Kandidat vorgemerkt und hat
  sich am selben Tag erledigt: Seit die Reiterleiste oben klebt, ist
  *Hilfe* auf jeder Seite in Reichweite, gleich wie weit man gescrollt
  ist.
- **Die MARLEI Assistance Suite.** Nicht, weil sie nicht hierher gehörte,
  sondern weil eine Familie mit einem Mitglied keine ist. Ab dem zweiten
  Modul kehrt sie zurück — die Arbeit dazu liegt bereit.

#### Zwei Dinge, die beim nächsten Griff zu bedenken sind

- **Der Quelltext-Verweis ist der erste Verweis nach außen im ganzen
  Projekt.** Ein Server im abgeschotteten Netz erreicht ihn nicht — das
  ist kein Fehler: Geklickt wird im Browser des Betreuers, nicht auf dem
  Server.
- **Wer den Server ändert und weitergibt, muss dorthin zeigen, wo *sein*
  Quelltext liegt.** Die Adresse steht heute fest in `base.html`. Sollte
  das je einstellbar werden, ist hier die Stelle.

---

### Das Logo in der Kopfzeile

Es steht rechtsbündig in derselben Zeile wie Titel und Adresse, geschoben
von `margin-left: auto`. **Mittig ausgerichtet, nicht auf der
Schriftlinie** — das `g` hat eine Unterlänge, die sonst unter der Zeile
hinge. Die Höhe (1,5rem) ist der einzige Wert zum Drehen.

Welche der drei Dateien dort steht, sagt *Das Band im Seitenkopf*.

### Die Kante unter der Navigation

Der Balken des aktiven Reiters (2px) und die Trennlinie unter der
Navigation (1px) sind beide `--marke-ex`. Zusammen ergibt das eine
durchgehende Kante, aus der der aktive Reiter herausragt.

**Sie sitzt seit dem 02.09.2026 am `nav` und nicht mehr am Seitenkopf.**
Das Band braucht die volle Breite, die Kante die 60rem-Spalte — zwei
verschiedene Maße, also zwei Elemente. Sichtbar ändert sich dadurch
nichts.

---

## Die Navigation ist nach Häufigkeit sortiert, nicht nach Ablauf

Die Reiter stehen in dieser Reihenfolge:

```
Server Health · Clients · Systeme · Quellen · Einrichtung · History · Hilfe
```

Der Weg beim **Aufsetzen** läuft genau andersherum: erst *Einrichtung*
(stimmt die Adresse?), dann *Quellen* (ein System hereinholen), dann
*Systeme* (freigeben), dann *Clients* (einem Rechner etwas vorgeben),
zuletzt *Server Health* (hat es geklappt?).

**Das ist eine Entscheidung, keine Nachlässigkeit.** Aufgesetzt wird ein
Server einmal, benutzt wird er jahrelang — und im Betrieb schaut man
zuerst auf *Server Health* und *Clients*. Eine Navigation, die nach dem
Aufsetzweg sortiert wäre, stellte den seltensten Fall nach vorn und
zwänge bei jedem Besuch zu einem Weg quer durch die Leiste.

**Der Preis ist eine Stelle, an der man sich vertut**, und wir haben uns
dort vertan: Bis zum 29.08.2026 behaupteten drei Sätze in der Hilfe und
einer in `docs/02-installation.md`, die acht Schritte liefen „in der
Reihenfolge der Reiter" und man gehe sie „von links nach rechts" durch.
Die Tabelle direkt darunter lief andersherum und war richtig. **Wer diese
Reihenfolge beschreibt, prüfe sie an der Navigationsleiste**, nicht aus
dem Gedächtnis.

**Stand 29.08.2026, und das kann sich ändern.** Die Entscheidung hängt an
der Annahme, dass Betrieb häufiger ist als Einrichtung — für einen
Server, den jemand mehrmals im Jahr neu aufsetzt, kann sie anders
ausfallen. Sollte sich die Reihenfolge einmal drehen, sind es diese
Stellen: `webui/templates/base.html` (die Leiste selbst), das Kapitel
*Was tut man zuerst?* und *Der erste Durchgang* in `hilfe.html`, sowie
Abschnitt 2.3 in `docs/02-installation.md`.

---

## Eine Doppelung, die bleibt

Die Farbwerte stehen an **zwei** Orten: als Token in `style.css` und noch
einmal in den SVG-Dateien. Das ist nicht aus Nachlässigkeit so — die
Dateien werden als Bild eingebunden und können die Token der Seite nicht
lesen. Beide Stellen verweisen im Kommentar aufeinander.

**Wer eine Markenfarbe ändert, ändert sie an beiden Orten** und lässt
danach `marke/logo-bauen.py` laufen.

---

## Verworfen, mit Grund

- **Überschriften in Navy.** Am 27.08.2026 entschieden: `h2` bleibt in der
  Textfarbe. Die Marke steht schon in der Kopfzeile, im aktiven Reiter und
  auf jedem gefüllten Knopf; Überschriften dazu hätten sie zur
  Grundfarbe der Seite gemacht, und was überall ist, betont nichts mehr.
- **Eine Trennlinie über der Fußzeile der Karte.** Der Abstand trennt
  genug. Eine Linie zöge eine Grenze, wo nur ein Tonwechsel ist.
- **Eine Zeile „Noch kein Eintrag ist startbereit" auf *Systeme*.** Am
  27.08.2026 entfernt statt umformuliert. Sie war unerreichbar: Startbereit
  heißt „die Dateien liegen lokal", und die Online-Einträge brauchen keine
  — netboot.xyz lädt sein Menü beim Booten aus dem Netz. Die Gruppe
  *Online-Installationen* ist damit nie leer, auch nicht auf einem Server
  ohne Internet und auch nicht direkt nach der Ersteinrichtung. Und selbst
  wenn sie erreichbar wäre: Dass nach dem Aufsetzen noch nichts da ist,
  weiß man ohne Hinweis.
- **`<header>` und `<footer>` in der Karte.** Die drei Bereiche sind eine
  Verabredung über Begriffe, kein Bauplan — siehe *Die Karte und ihre drei Bereiche*. Hüllen in 29 Karten
  brächten Markup, das keine Regel braucht.

---

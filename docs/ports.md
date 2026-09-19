# Ports der MARLEI Assistance Suite

**Jedes Modul hat seinen festen Port — auf jedem Server derselbe.** Diese
Datei liegt byteweise gleich in jedem Modul (`tools/gemeinsam.txt`); wer
einen Port vergibt oder ändert, ändert ihn hier und trägt die Datei in
alle Module.

## Die Tabelle

| Modul | außen | innen | Stand |
|---|---|---|---|
| MARLEI Boot | 80 | 8080 | so installiert |
| MARLEI Tasks | 8081 | 18081 | so gebaut; eine ältere Installation zieht beim nächsten Update nach |

Das nächste Modul bekommt 8082 und 18082.

**Außen** ist die Adresse, die im Browser steht: unter Linux der
nginx-vhost, unter Windows uvicorn selbst — dort steht kein nginx davor.
**Innen** gibt es nur unter Linux: uvicorn hinter nginx, gebunden an
`127.0.0.1` und von außen nicht zu erreichen. Auch er ist vergeben und
nicht beliebig — zwei Module auf demselben inneren Port starten nicht
beide.

## Das Schema

**Außen `808x`, innen `1808x`, x ist das Modul.** Die Zahl lässt sich
ablesen, ohne nachzuschlagen, und ein neues Modul nimmt die nächste.

**Boot ist die Ausnahme und bleibt es.** Die bootenden Rechner holen ihre
Dateien über Port 80, und Boots vhost hält die 80 als `default_server`.
Boot läuft produktiv; ein Umzug brächte nichts und bräche jeden Client,
der die Adresse kennt.

**Die innere 8000 von Tasks ist abgelöst** (September 2026), weil sie der
Port ist, den halb Python als Vorgabe nimmt — neben einem fremden Dienst
ist das die erste Stelle, an der es kracht.

## Fest heißt nicht unveränderlich

**Wer einen Port ändern muss, kann es**, und die Installation merkt ihn
sich:

- Linux: `sudo MARLEI_PORT=9090 ./setup/linux/install.sh`
- Windows: `.\setup\windows\install.ps1 -Port 9090`

**Ein zweiter Lauf fällt nicht auf die Vorgabe zurück.** Das Update und
ein erneuter Aufruf des Installationsskripts nehmen den Port der
bestehenden Installation, nicht den aus dieser Tabelle. Sonst stellte
jedes Update einen geänderten Port still zurück, und jedes Lesezeichen
zeigte ins Leere.

## Warum keine Range

Beschlossen im September 2026. Eine Range, aus der sich jedes Modul bei
der Installation den ersten freien Port nimmt, war die Alternative. Dann
hinge der Port von der Reihenfolge der Installation ab: Tasks hätte auf
zwei Servern zwei Adressen, und Lesezeichen, Doku und Firewallregel wären
Glückssache. Ein fester Port je Modul kostet eine Zeile in dieser Tabelle.

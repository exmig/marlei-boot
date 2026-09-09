# Tests

Prüfen die Anwendung ohne echten PXE-Boot — nützlich nach jeder Änderung an
`catalog.yaml` oder an den Vorlagen.

```bash
python -m venv venv
./venv/bin/pip install -r ../webui/requirements.txt httpx
./venv/bin/python tests/test_katalog.py
./venv/bin/python tests/test_app.py
./venv/bin/python tests/test_iso.py
./venv/bin/python tests/test_muster.py
```

**test_katalog.py** rendert jede iPXE-Vorlage mit den echten Katalog-Daten
und prüft: gültiger Skriptkopf, keine doppelten oder mit Sprungmarken
kollidierenden `slug`s, passende Anzahl `initrd`-Zeilen, `${assets}` nur
dort verwendet, wo es auch gesetzt ist. Die Windows-Vorlage wird mit einem
nachgebauten Eintrag geprüft — dort muss hinter jedem Pfad der Zielname
stehen, unter dem der Windows-Bootmanager die Datei sucht; ohne ihn startet
nichts, und zwar ohne Fehlermeldung, die das erklären würde.

**test_app.py** startet die Anwendung gegen ein Wegwerf-Verzeichnis mit
teilweise vorhandenen Dateien und prüft den kompletten Ablauf: Menü je nach
BIOS/UEFI, Ausblenden unfertiger Einträge, Erfassen der Clients, Vorauswahl
einmalig und dauerhaft, Wake-on-LAN, Annahme und Ausgabe von
Installationsprotokollen, Holen eines Abbilds von einer Adresse, Pflege und
Prüfung der Download-Quellen, Fehlerfälle, Neuladen des Katalogs im
Betrieb. Die Weckpakete gehen dabei nicht ins echte LAN, sondern an einen
Lauschposten auf der Loopback-Adresse, der ihren Inhalt nachprüft. Die
Datenbank wird bewusst im alten Format angelegt, damit auch das
Nachrüsten neuer Spalten mitgeprüft wird.

Geprüft wird dort auch die **Seitenkarte**: Läuft der Server unter einer
anderen Adresse als der eingerichteten, muss die rote Karte auf *jedem*
Reiter stehen — nicht nur auf zweien, wie bis August 2026 —, zugeklappt
sein und unter *Einrichtung* genau einmal vorkommen. Und sie muss wieder
verschwinden: Ein Befund, der stehen bleibt, nachdem das Problem weg ist,
macht aus einer Auskunft eine Tapete.

Dasselbe für die anderen beiden Stufen: Ein toter `dnsmasq` gibt eine rote
Karte, ein totes `nfs-server` eine gelbe — und stehen beide an, steht die
rote oben. Ein Dienst, der von hier aus gar nicht abfragbar ist, gibt
keine. Bei der vollen Platte wird geprüft, dass Karte und Balken **an
derselben Zahl** umschlagen: Sie kommt aus `dienste.VOLL`, und der Test
rechnet mit dieser Konstante statt mit einer abgeschriebenen 90.

Bei den **Download-Quellen** verläuft eine Grenze mitten durch die
Prüfungen, und sie ist Absicht. Drei Zeilen gehen wirklich zu
`releases.ubuntu.com` — sie prüfen das Zusammenspiel und nehmen dafür in
Kauf, von etwas abzuhängen, das uns nicht gehört. Alles, was eine
**Rechnung** prüft, läuft dagegen am nachgebauten Spiegel auf der
Rückschleife. Der Anlass: Die Gegenprobe „wo das Muster stimmt, kommt
dasselbe heraus" stand auf Ubuntu 26.04, weil es davon damals keine
Punktausgabe gab. Am 28.08.2026 lag dort 26.04.1, und der Test war rot —
nicht weil der Code etwas falsch macht, sondern weil die Annahme abgelaufen
war. Eine andere Zahl einzusetzen hätte den Fehlschlag nur vertagt.

**test_muster.py** prüft, ob aus einer eingefügten Adresse wieder ein
Ausgabenmuster wird — die Grundlage dafür, dass man beim Anlegen eines
eigenen Eintrags kein `{version}` von Hand tippen muss. Der Prüfstein
steht im Projekt selbst: `sync-images.sh` trägt neun von Hand
geschriebene Muster. Setzt der Test dort eine Ausgabe ein und lässt sie
zurückgewinnen, muss dasselbe herauskommen. Geprüft wird auch, was
**nicht** als Ausgabe gilt: die Architektur (`x86_64`), Rechnername und
Port (`192.168.178.30:8080`) und Debians Codename — dort wird nichts
vorgeschlagen, statt etwas zu raten. Die Gegenprobe beim Anbieter läuft
gegen einen nachgebauten Index auf der Loopback-Adresse, damit der Test
ohne Netz auskommt.

**test_iso.py** prüft das Erkennen hochgeladener Abbilder. Dafür bauen
`isobauer.py` und `udfbauer.py` winzige, aber echte Abbilder mit den Merkmalen von
Mint, Ubuntu Server, Debian Live, Arch, Fedora, openSUSE, Windows und einem
Debian-Installations-Abbild — jedes nur ein paar Kilobyte groß, also ohne
einen einzigen Download. Von Windows gibt es drei Ausgaben: eine für BIOS
und UEFI, eine ältere nur mit BIOS-Teil und eine ohne `boot.wim`. Damit ist
geprüft, dass ein Abbild ohne UEFI-Teil auch nur BIOS-Rechnern angeboten
wird und ein unbrauchbares gar keinen Menüpunkt bekommt.

Die Windows-Abbilder entstehen mit `udfbauer.py`, weil echte Windows-Medien
ihre Dateien nicht im ISO9660-Teil führen, sondern im UDF daneben — im
ISO9660 steht nur ein Zettel, der darauf verweist. Der Bauer bildet auch die
zwei Eigenheiten nach, an denen ein UDF-Leser scheitern kann: eine Datei aus
mehreren Stücken (ein Leser, der nur das erste nimmt, liefert lautlos Müll)
und eine Datei, die direkt im Verzeichniseintrag steht. `test_iso.py`
vergleicht die herausgelesenen Inhalte Byte für Byte.

Geprüft wird dort auch das **Auffrischen eines Menüpunkts ohne das Abbild**:
Bei ausgepackten Abbildern wird das ISO gelöscht, und ohne diesen Weg bliebe
nach einer Änderung an der Eintragserzeugung nur, mehrere Gigabyte erneut
hochzuladen. Der Test baut dafür den Zustand einer älteren Fassung nach und
erwartet danach denselben Eintrag wie beim ersten Verarbeiten.

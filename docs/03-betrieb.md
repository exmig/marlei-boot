# 3. Betrieb an der Konsole

Was am **laufenden** Bootserver auf der Konsole zu tun ist. Es sind wenige
Dinge, und sie kommen selten vor — aber sie stehen nirgends sonst.

> **Die Grenze zur Hilfe des Servers.** Alles, was man **im Browser** tut,
> steht in der Hilfe der Anwendung und wird hier **nicht** wiederholt:
> Systeme holen und freigeben, Rechnern etwas vorgeben, Wecken,
> Protokolle, Ablageorte, Zurücksetzen. Die Hilfe liegt auf dem Server
> selbst und passt damit immer zu der Fassung, die dort läuft — eine
> zweite Beschreibung hier wäre in drei Monaten falsch.
>
> **Hier steht, was der Browser nicht kann.** Und das ist kein Zufall,
> sondern liegt in der Natur der Sache: Um eine Anleitung im Browser zu
> lesen, braucht man einen erreichbaren Server. Wenn sich seine Adresse
> geändert hat, ist genau das nicht mehr gegeben.

Geht etwas kaputt, ist [04-fehlersuche.md](04-fehlersuche.md) die
richtige Datei. Hier stehen Aufgaben, keine Störungen.

## 3.1 Einen neuen Stand übernehmen

Kommt eine neue Fassung des Projekts, holt ein einziger Befehl sie und
übernimmt sie — er zeigt vorher, was sich geändert hat:

```bash
~/marlei-boot/setup/update.sh
```

Bewusst **ohne** `sudo` aufrufen: `git pull` soll deinem Benutzer gehören.
Für `install.sh` fragt das Skript selbst nach dem Passwort.

Wer den Pfad zum Klon nicht zur Hand hat, nimmt die Kopie, die bei jeder
Installation entsteht — sie reicht an das Original weiter:

```bash
/opt/pxe-setup/update.sh
```

Das ist der einzige Weg. **Dateien unter `/opt/pxeweb` von Hand zu ändern
bringt nichts** — der nächste Lauf überschreibt sie, Quelle ist immer das
Repository.

## 3.2 Die Adresse der Maschine hat sich geändert

Zwei Schritte, und der erste gehört dir. Die Netzkonfiguration der
Maschine fasst der Bootserver nicht an — siehe
[01-voraussetzungen.md](01-voraussetzungen.md), *Netz, Adresse und
Zugang*.

1. **Die Adresse ändern**, auf dem Weg deines Systems: die Reservierung
   am Router umtragen oder die feste Adresse auf der Maschine ändern.
2. **Übernehmen lassen:**

```bash
sudo /opt/pxe-setup/install.sh
```

Der Aufruf braucht keine Argumente. Er liest die Adresse von der
Netzwerkkarte mit der Standardroute ab und schreibt sie in die vier
Stellen, an denen sie sonst noch steht: `/etc/dnsmasq.d/pxe.conf`,
`/etc/nginx/sites-available/pxe`, `PXE_BASE_URL` in `/etc/pxeweb.env` und
`/etc/exports.d/pxe.exports`.

Solange nur Schritt 1 erledigt ist, nennt dnsmasq den bootenden Rechnern
noch die alte Adresse, während die Maschine schon die neue trägt. In
diesem Fenster startet kein Rechner erfolgreich über das Netz — deshalb
beide Schritte hintereinander erledigen.

Steht die Oberfläche noch, sagt sie es von selbst: Der Befund erscheint
als farbige Karte über jeder Seite, und unter *Einrichtung* steht in der
Karte *Ersteinrichtung* die abgelesene Netzkonfiguration samt fertigem
Befehl zum Kopieren.

---

## 3.3 Betriebssysteme von der Konsole holen

**Der übliche Weg ist der Browser**, unter *Quellen*: dort sieht *Prüfen*
beim Anbieter nach und *Holen* lädt. Wer es trotzdem auf der Konsole
braucht — etwa in einem Skript oder weil die Oberfläche gerade nicht
erreichbar ist:

```bash
sudo /opt/pxe-setup/sync-images.sh --list          # zeigt, was es gibt
sudo /opt/pxe-setup/sync-images.sh                 # alles holen
sudo /opt/pxe-setup/sync-images.sh debian gparted  # nur diese beiden
```

Vollständig geladene Dateien werden übersprungen, abgebrochene Downloads
fortgesetzt — das Skript kann also jederzeit erneut laufen.

**Welche Ausgabe geholt wird, steht nicht im Skript**, sondern in
`/var/lib/pxeweb/quellen.env`, und dorthin schreibt sie das *Prüfen* aus
der Oberfläche. Ein frisch aufgesetzter Server hat dort noch nichts
stehen; ein Aufruf ohne vorheriges *Prüfen* holt deshalb nichts.

---

Geht etwas nicht: [04-fehlersuche.md](04-fehlersuche.md).

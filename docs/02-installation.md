# 2. PXE-Server installieren

Voraussetzung ist eine Maschine, wie sie
[01-voraussetzungen.md](01-voraussetzungen.md) beschreibt: Debian, Ubuntu
oder Raspberry Pi OS, mit Kabel im selben Netz wie die bootenden Rechner,
mit einer Adresse, die bleibt, und mit Internetzugang. Ob das echte
Hardware ist oder eine virtuelle Maschine, spielt keine Rolle. Dort sind
auch die Begriffe festgelegt, die hier durchgehalten werden: **die
Maschine**, auf der alles läuft, **der Bootserver**, den `install.sh`
darauf einrichtet, und **die Clients**, die später davon starten.

Die eine Zahl, die sich hinterher schlecht ändern lässt, ist die
**Platte**: 20 GB als Untergrenze, 60 GB, wenn eigene Abbilder dazukommen.
Alles Übrige zur Ausstattung steht dort ebenfalls, unter *Empfehlung für
die Ausstattung*.

`install.sh` prüft das System als Erstes und bricht ab, bevor es etwas
anfasst, wenn es keines der drei ist.

## 2.0 Debian oder Ubuntu — wo sie sich unterscheiden

Beide sind getestet, und `install.sh` läuft auf beiden gleich. Bevor es
so weit ist und danach im Betrieb gibt es aber vier Stellen, an denen sie
sich verschieden verhalten. Alle vier sind uns bei Probeläufen begegnet,
und jede hat mindestens einmal in die Irre geführt.

### `sudo` ist nicht überall da

Alles, was hier folgt, beginnt mit `sudo`. Der Stolperstein liegt gleich
im ersten Befehl:

```
$ sudo apt install git
-bash: sudo: Kommando nicht gefunden
```

Das sieht nach einem Tippfehler aus und ist keiner.

| | Root-Passwort | `sudo` |
|---|---|---|
| **Debian**, Root-Passwort bei der Installation gesetzt | ja | **fehlt** |
| **Debian**, Root-Passwort leer gelassen | nein | da — der erste Benutzer ist Administrator |
| **Ubuntu** | wird gar nicht erst gefragt | immer da |
| **Raspberry Pi OS** | kein Root-Passwort | immer da |

Debian stellt die Frage beim Installieren also indirekt: Wer ein
Root-Passwort vergibt, bekommt das klassische `su`-Modell und kein `sudo`;
wer das Feld leer lässt, bekommt es umgekehrt. Ubuntu und Raspberry Pi OS
kennen diese Wahl nicht — dort ist der erste Benutzer immer Administrator.

**Verwirrend daran:** `groups` zeigt trotzdem `sudo` an. Die **Gruppe**
gibt es auf jedem Debian, auch ohne das gleichnamige Paket. Man ist also
Mitglied einer Gruppe, deren Werkzeug fehlt — und sucht den Fehler
zunächst überall sonst.

Der Weg heraus, mit dem Root-Passwort:

```bash
su -
apt update
apt install -y sudo
# Falls der eigene Benutzer noch nicht in der Gruppe steht:
/usr/sbin/usermod -aG sudo <benutzer>
exit
```

Stand der Benutzer schon in der Gruppe, geht `sudo` sofort. Musstest du ihn
erst hinzufügen, gilt die Gruppe erst nach einer neuen Anmeldung — einmal
ab- und wieder anmelden.

### `sudo` fragt nach dem Passwort — auch aus der Ferne

Ist `sudo` da, heißt das noch nicht, dass es ohne Rückfrage arbeitet. Auf
beiden Systemen verlangt es beim ersten Mal je Sitzung das Passwort des
Benutzers. Für eine Installation, bei der jemand davorsitzt, ist das
belanglos; wer die Befehle aus einem Skript oder über eine
SSH-Verbindung schickt, läuft damit auf. `sudo -n true` sagt vorab, ob es
ohne Rückfrage geht.

Das gehört bewusst nicht geändert: Ein Bootserver, der Rechner neu
aufsetzen kann, ist kein Ort für ein passwortloses `sudo`.

### Port 53 ist auf Ubuntu schon belegt

Ubuntu betreibt `systemd-resolved`, Debian nicht. Frisch installiert
möchte dnsmasq auch DNS anbieten und stößt dabei auf diesen Dienst — dann
steht im Journal `Address already in use`. Unsere Konfiguration schaltet
den DNS-Teil ab (`port=0`), aber sie wird erst nach dem Installieren der
Pakete geschrieben. **Bei einem vollständigen Lauf merkt man davon
nichts.** Wer mitten in `apt` abbricht, sieht einen dnsmasq, der nicht
startet, und hält das für den Fehler — siehe
[04-fehlersuche.md](04-fehlersuche.md) unter *`install.sh` wurde
unterbrochen*.

### Ubuntu bringt eine Firewall mit

`ufw` ist auf Ubuntu installiert, auf Debian nicht. Ist sie an und lässt
den Bootweg nicht durch, ist der Server tadellos eingerichtet, meldet
sich gesund, die Oberfläche läuft — und trotzdem bootet kein einziger
Rechner, ohne dass irgendwo eine Meldung stünde. Der Bootweg braucht
**UDP 67, 4011, 69** und für NFS **111 und 2049**. Dazu **TCP 445**, wenn
Windows von der SMB-Freigabe installiert werden soll.

Nachsehen mit `sudo ufw status`, **nicht** mit `systemctl status ufw` —
die beiden sagen Verschiedenes, und das führt zuverlässig in die Irre.
Ausführlich in [04-fehlersuche.md](04-fehlersuche.md) unter *Der Client
meldet „No configuration methods succeeded"*.

## 2.1 Das Projekt auf die Maschine holen

Die Maschine ist reiner Empfänger: Entwickelt wird woanders, hier wird nur
geholt. Sie braucht dafür Git und sonst nichts — den Bootserver gibt es an
dieser Stelle noch gar nicht, den richtet der nächste Abschnitt ein.

```
   Entwicklung           Repository             Maschine
   (bearbeiten)  ──────► (origin)   ──────►   (nur pull)
                  push               pull
```

> **Seit dem 04.09.2026 ist das Repository öffentlich:**
> `https://github.com/exmig/marlei-boot.git`, AGPL-3.0, erste Fassung
> **v1.0**. Zum Klonen braucht es weder ein Konto noch einen Schlüssel —
> HTTPS genügt.

### Einmalig: klonen

```bash
sudo apt install git
git clone https://github.com/exmig/marlei-boot.git ~/marlei-boot
```

Ein `chmod` ist danach **nicht** nötig: Git speichert das Ausführbar-Bit
als Dateimodus, und die Skripte kommen ausführbar an. Nur wer das Projekt
als ZIP-Archiv statt über Git holt, muss es nachholen — dabei geht der
Modus verloren:

```bash
chmod +x ~/marlei-boot/setup/*.sh
```

### Zeilenenden

Die mitgelieferte `.gitattributes` sorgt dafür, dass alle Dateien mit
Unix-Zeilenenden auf der Maschine ankommen. Das ist keine Kosmetik: mit
Windows-Zeilenenden scheitern die Skripte dort mit der irreführenden
Meldung `/usr/bin/env: 'bash\r': No such file or directory`.

Kopierst du ausnahmsweise anders als über Git, prüfe mit
`file setup/install.sh` — steht dort „CRLF“, hilft
`sudo apt install dos2unix && dos2unix setup/*.sh`.

---

## 2.2 Installation starten

Auf der Maschine:

```bash
cd ~/marlei-boot
sudo ./setup/install.sh
```

*`~/marlei-boot` ist der Ordner aus dem `git clone` oben. `install.sh`
selbst schreibt in seinen Meldungen `<projekt>` dafür, und ebenso
[04-fehlersuche.md](04-fehlersuche.md) — gemeint ist immer derselbe
Ordner.*

**Das dauert je nach Leitung mehrere Minuten**, und der größte Teil davon
ist `apt`. Es sieht zwischendurch so aus, als geschehe nichts.
**Nicht abbrechen** — ein Abbruch mitten in `apt` hinterlässt einen halb
eingerichteten Stand, bei dem die Pakete liegen, die Konfiguration aber
noch fehlt. Das sieht dann nach einem Fehler aus und ist keiner; was dann
zu tun ist, steht in [04-fehlersuche.md](04-fehlersuche.md) unter
*`install.sh` wurde unterbrochen*.

Das Skript erledigt:

1. Netzwerkkarte und IP-Adresse erkennen — und warnen, falls die Maschine
   in einem NAT-Netz hängt, denn dorthin kommt kein PXE-Broadcast
2. Pakete installieren: `dnsmasq`, `nginx`, `nfs-kernel-server`, `samba`,
   `curl`, `ca-certificates`, `rsync`, `libarchive-tools` sowie `python3`,
   `python3-venv` und `python3-pip`
3. Dienstkonto `pxeweb` und die Verzeichnisse unter `/srv/pxe` anlegen
4. Web-Anwendung nach `/opt/pxeweb` kopieren, virtuelle Python-Umgebung bauen
5. Konfiguration schreiben: `/etc/dnsmasq.d/pxe.conf`, nginx-Site, systemd-Unit,
   NFS-Freigabe `/etc/exports.d/pxe.exports` und SMB-Freigabe
   `/etc/samba/pxe.conf` (beide nur lesend, beide nur eigenes Subnetz)
6. Die iPXE-Bootloader von `boot.ipxe.org` holen
7. Dienste starten und einen kurzen Selbsttest fahren

Am Ende steht die Adresse der Weboberfläche in der Ausgabe —
`http://<BootServer-IP>/`. Sie ist ab sofort von jedem Rechner im selben
Netz aus im Browser erreichbar.

> **Und zwar ohne Anmeldung.** Die Oberfläche hat kein Passwort: Wer sie
> erreicht, kann Rechner neu aufsetzen. Sie gehört deshalb ins eigene Netz
> und nicht ins Internet.
>
> Das ist für den heutigen Stand eine **bewusste Entscheidung** und keine
> Lücke, die jemand übersehen hat — der Server ist ein Werkzeug fürs eigene
> Netz, und dort sind die Grenzen des Netzes die Grenzen des Zugriffs. In
> einer künftigen Fassung kann das anders ausfallen.

Das Skript ist wiederholbar — nach Änderungen am Projekt einfach erneut
ausführen, es aktualisiert nur.

### Was danach auf der Maschine liegt

Zum Nachschlagen — angelegt hat das alles `install.sh`, von Hand ist hier
nichts zu tun:

| Pfad | Inhalt |
|---|---|
| `/srv/pxe/tftp` | iPXE-Bootloader (das Einzige, was per TFTP geht) |
| `/srv/pxe/assets` | Kernel, Initrds, ISOs, Squashfs-Dateien |
| `/srv/pxe/assets/iso-*` | Selbst hochgeladene Abbilder (bleiben bei Updates erhalten) |
| `/srv/pxe/assets/netz-*` | Selbst angelegte Netz-Installer (bleiben bei Updates erhalten) |
| `/srv/pxe/assets/wimboot` | wimboot, der Starthelfer für Windows-Abbilder |
| `/opt/pxeweb` | Die Web-Anwendung samt `catalog.yaml` |
| `/opt/pxe-setup` | Kopie der Setup-Skripte für spätere Läufe |
| `/var/lib/pxeweb` | Datenbank, Installationsprotokolle, eigene Download-Quellen |
| `/etc/pxeweb.env` | Einstellungen |
| `/etc/dnsmasq.d/pxe.conf` | proxyDHCP-Konfiguration |
| `/etc/exports.d/pxe.exports` | NFS-Freigabe der Assets (nur lesend, nur eigenes Subnetz) |

**Die Netzkonfiguration der Maschine steht nicht in dieser Liste, und das ist
Absicht.** Sie gehört dir. `install.sh` liest die Adresse ab, schreibt sie
in dnsmasq, nginx, `pxeweb.env` und den NFS-Export — und die Oberfläche
meldet auf *Server Health*, wenn sie sich geändert hat. Nachgezogen wird
mit `sudo /opt/pxe-setup/install.sh`.

## 2.3 Ab hier im Browser: der Arbeitsablauf

Öffne die Oberfläche: `http://<BootServer-IP>/`. Die Adresse steht am Ende
der Ausgabe von `install.sh`. **Alles Weitere geschieht dort** — auf der
Konsole ist nichts mehr zu tun.

Der Weg vom frisch installierten Server bis zu einem Rechner, der davon
startet, sind acht Schritte. Sie laufen quer durch die Reiter, und zwar
**gegen deren Reihenfolge** — die Navigation ist danach sortiert, was man
im Betrieb am häufigsten braucht, dieser Durchgang danach, was zuerst zu
tun ist. Das ist eine bewusste Entscheidung und kann sich in einer
künftigen Fassung ändern; die Begründung steht in
[gestaltung.md](gestaltung.md) unter *Die Navigation ist nach Häufigkeit
sortiert, nicht nach Ablauf*.

| | Wo | Was |
|---|---|---|
| 1 | Einrichtung | Nachsehen, dass die eingerichtete Adresse die der Maschine ist. Meist ist hier nichts zu tun. |
| 2 | Quellen | Ein Live-System holen — *Prüfen* trägt die aktuelle Ausgabe ein, *Holen* lädt sie. |
| 3 | Quellen | Dasselbe für einen Netz-Installer. Der ist klein, weil er seine Pakete erst beim Installieren zieht. |
| 4 | Quellen | Nachsehen, ob es geklappt hat: Der Eintrag steht jetzt auf *bereit*. |
| 5 | Systeme | Freigeben. Zwei Haken je Eintrag — fürs Bootmenü, für die Vorgabe an einen einzelnen Rechner. |
| 6 | Systeme | Die Vorschau zeigt, was der bootende Rechner zu sehen bekommt. |
| 7 | Clients | Einem Rechner etwas vorgeben und ihn auf Wunsch per Netzwerk einschalten. |
| 8 | Server Health | Der Blick zurück: Hat alles funktioniert? |

**Zwei Dinge daran überraschen erfahrungsgemäß.** Ein frisch aufgesetzter
Server ist leer: Mitgeliefert wird die *Auswahl* der Distributionen, nicht
die Nummer ihrer Ausgabe — welche es gerade gibt, weiß der Anbieter besser
als eine mitgelieferte Datei. Und was geholt ist, steht deshalb noch in
keinem Bootmenü; Schritt 5 fehlt dann noch.

> **Ausführlich steht das alles in der Hilfe des Servers**, Kapitel
> *Der erste Durchgang*: dieselben acht Schritte, jeder mit dem Ausschnitt
> der Oberfläche daneben, um den es geht. Das ist der schnellste Weg, den
> Server kennenzulernen — und die Fassung, die immer zu dem passt, was
> gerade auf dem Bildschirm steht.

## 2.4 Der erste Test

**Nimm dafür einen echten Rechner.** Im BIOS/UEFI den Netzwerkstart an
die erste Stelle setzen — oder beim Einschalten das Bootmenü der Firmware
aufrufen, meist mit F12 — und starten. Nach wenigen Sekunden sollte iPXE
laden und dein Bootmenü erscheinen.

Passiert nichts, ist **Secure Boot** der erste Verdächtige: iPXE ist
nicht signiert und wird sonst von der Firmware abgelehnt.

Für den zweiten Durchgang lohnt ein Rechner der jeweils anderen Bauart:
BIOS und UEFI starten über verschiedene Bootloader. Beide sind
eingerichtet — nachgesehen hat man es damit trotzdem.

> **Eine Wegwerf-VM als Testclient ist naheliegend, aber nicht
> verlässlich.** Bringt das Betriebssystem der Maschine dnsmasq 2.92 mit —
> etwa Ubuntu 26.04 —, bootet eine VirtualBox-VM nicht: Du siehst iPXE und
> danach *Connection timed out*, während der Server kerngesund aussieht. **Das
> ist kein Fehler deiner Installation**, echte Rechner booten davon
> einwandfrei. Welche Fassung läuft, sagt `dnsmasq --version`; betroffen
> ist 2.92, nicht 2.91 (Debian 13.6) und nicht 2.90 (Ubuntu 24.04).
> Untersucht und eingegrenzt: Es liegt am Zusammenspiel von PXE-ROM und
> dieser dnsmasq-Fassung, nicht an deiner Installation.

Was währenddessen auf der Maschine geschieht, siehst du live mit:

```bash
sudo journalctl -u dnsmasq -f
```

Dasselbe steht in der Oberfläche unter *Server Health* hinter jedem
Dienst — dort braucht es keine SSH-Sitzung dafür.

---

Weiter mit [03-betrieb.md](03-betrieb.md): was am laufenden Server auf der
Konsole zu tun ist — einen neuen Stand übernehmen, eine geänderte Adresse
nachziehen.

Wenn etwas nicht klappt: [04-fehlersuche.md](04-fehlersuche.md) — dort
steht, was zu tun ist, solange die Oberfläche noch nicht antwortet.
Sobald sie läuft, ist ihre eigene Hilfe die ausführlichere Quelle.

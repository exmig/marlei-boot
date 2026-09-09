# 4. Fehlersuche an der Konsole

**Wofür dieses Dokument da ist — und wofür nicht.**

Alles, was man *mit* einem laufenden Server tut, steht in seiner eigenen
Hilfe: `http://<BootServer-IP>/hilfe`. Sie ist ausführlicher als eine
Datei es sein kann, sie verweist von jeder Karte auf ihren Abschnitt, und
sie veraltet nicht — sie liegt neben dem Programm, das sie beschreibt. Wer
den Ablauf einmal im Ganzen sehen will, findet dort unter **Der erste
Durchgang** acht Schritte mit Abbildungen der Oberfläche.

Hier steht der Rest: **was zu tun ist, wenn man diese Hilfe gerade nicht
erreichen kann.** Ein abgebrochenes `install.sh`, ein Dienst, der nicht
startet, ein Rechner, der den Server nicht findet. In diesen Momenten
liegt die Hilfe auf genau der Maschine, die nicht antwortet — deshalb
steht das Nötige hier, im Repository, wo man es von einem anderen Rechner
aus liest.

**Der Aufbau:** Zuerst das Ablaufbild und der Werkzeugkasten — mit ihnen
findet man die Stelle. Danach die Fehlerbilder, in der Reihenfolge, in der
sie beim Booten auftreten können.

*Die Begriffe sind dieselben wie in
[01-voraussetzungen.md](01-voraussetzungen.md): **die Maschine**, auf der
alles läuft, **der Bootserver** darauf, und **die Clients**, die davon
starten. Bei einer Störung entscheidet oft genau diese Unterscheidung,
wo man sucht.*

---

## 4.1 Wo es klemmen kann

Ein Netzwerkstart hat acht Schritte. Wenn du weißt, welcher davon der
letzte war, der noch geklappt hat, ist die Ursache meist schnell gefunden:

```
1. Client an  ──► DHCP-Broadcast
2.                Router  : "Deine IP ist <Client-IP>"
                  dnsmasq : "Deinen Bootloader holst du per TFTP bei <BootServer-IP>"
3. Client ──► TFTP ──► undionly.kpxe  (BIOS)  /  snponly.efi  (UEFI)
4. iPXE startet, fragt nochmal DHCP
5.                dnsmasq erkennt iPXE (Option 175)
                  und antwortet: http://<BootServer-IP>/boot.ipxe
6. iPXE ──► HTTP ──► /boot.ipxe ──► /menu.ipxe
7. Menü auf dem Bildschirm  ODER  Vorauswahl aus der Weboberfläche
8. iPXE ──► HTTP ──► /boot/<name>.ipxe ──► Kernel + Initrd ──► Start
```

Schritt 1–3 laufen über **TFTP** (langsam, aber nur ein paar hundert KB),
ab Schritt 6 über **HTTP** (schnell, hier fließen die großen Dateien).

**Und hier steht, wo du weiterliest** — je nachdem, welcher Schritt der
letzte war, der noch geklappt hat:

| Es hängt bei | Das Bild | Weiter unter |
|---|---|---|
| *vor Schritt 1* | `install.sh` ist nicht durchgelaufen | **4.3** |
| **1–2** | Der Client bekommt gar keine Antwort | **4.4** |
| **3** | Er hat eine IP, holt aber die Datei nicht | **4.5** |
| **3**, nur UEFI | BIOS-Rechner starten, UEFI-Rechner nicht | **4.7** |
| **4–5** | iPXE lädt sich immer wieder selbst | **4.6** |
| **8** | Das Menü kam, das System hängt beim Start | **4.8** |

**Kommt der Rechner bis zum Menü — Schritt 7 —, ist der Bootserver im
Wesentlichen in Ordnung.** Dann führt der Weg in die Hilfe, nicht hierher.
Die Ausnahme ist Schritt 8: Bis zum Menü kann alles stimmen und das
Einhängen über NFS trotzdem scheitern.

## 4.2 Die wichtigsten Befehle

```bash
# Live mitlesen, was die bootenden Rechner anfragen -- das nützlichste Werkzeug
sudo journalctl -u dnsmasq -f

# Läuft alles?
systemctl status dnsmasq nginx pxeweb nfs-server

# Was holt sich der Client per HTTP?
tail -f /var/log/nginx/pxe-access.log

# Antwortet die Anwendung?
curl -s http://localhost/health

# Sieht das Bootskript gesund aus?
curl -s http://localhost/boot.ipxe

# Nach Änderungen an der Web-App
sudo systemctl restart pxeweb
```

Solange die Oberfläche läuft, braucht man davon nichts: Das Journal jedes
Dienstes steht dort im Browser, erreichbar über die Dienstliste auf
*Server Health*.

## 4.3 `install.sh` wurde unterbrochen — was jetzt?

**Noch einmal laufen lassen.** Das Skript ist wiederholbar: Ein zweiter
Aufruf überspringt, was schon da ist, und holt nur das Fehlende nach.

```bash
sudo <projekt>/setup/install.sh
```

Ein Lauf dauert je nach Leitung mehrere Minuten, und der größte Teil davon
ist `apt`. Wird er in dieser Zeit abgebrochen — Strg+C, geschlossenes
Fenster, abgerissene SSH-Verbindung —, bleibt ein **halb eingerichteter
Server** zurück: Die Pakete sind installiert, die Konfiguration ist noch
nicht geschrieben.

Das äußert sich in einer Meldung, die in die Irre führt:

```
● dnsmasq.service   loaded failed failed
```

und im Journal steht etwas von Port 53 oder `Address already in use`.
**Das ist nicht der Fehler, sondern seine Folge.** Frisch installiert
möchte dnsmasq auch DNS anbieten und stößt dabei auf `systemd-resolved`,
das diesen Port schon hat — das betrifft Ubuntu, Debian hat
`systemd-resolved` nicht in Betrieb. Unsere Konfiguration schaltet den
DNS-Teil ab (`port=0` in `/etc/dnsmasq.d/pxe.conf`), aber sie wird erst im
Schritt *Konfiguration schreiben* angelegt — also nach `apt`. Wer vorher
abbricht, hat die Pakete, aber nicht die Datei.

Nach einem vollständigen Lauf ist der Spuk vorbei, ohne dass man etwas von
Hand aufräumen muss.

> **Wenn ein zweiter Lauf sofort abbricht** mit *„Could not get lock
> /var/lib/dpkg/lock-frontend"*, läuft der erste noch. Die Meldung nennt
> die Prozessnummer:
>
> ```
> ps -o pid,ppid,stat,etime,cmd -p <pid>
> ```
>
> Steht in `STAT` ein **`T`**, ist der Vorgang nicht abgestürzt, sondern
> **angehalten** — meist durch ein Strg+Z. Dann im ursprünglichen Fenster
> `fg` eingeben oder von anderswo `sudo kill -CONT <pid>`; der Lauf setzt
> fort und gibt den Riegel frei.
>
> Bleibt dabei die Tastatureingabe unsichtbar, ist die Anzeige des
> Terminals aus: `sudo` schaltet sie für die Passwortabfrage ab, und ein
> Strg+Z genau in diesem Moment lässt sie ausgeschaltet zurück. Blind
> `stty sane` tippen und Enter drücken — die Eingaben kommen an, man sieht
> sie nur nicht.

*Beim Probelauf auf Ubuntu 26.04 genau so passiert, mit allen drei
Symptomen auf einmal.*

## 4.4 Der Client meldet „No configuration methods succeeded" oder findet gar nichts

Die DHCP-Antwort kommt nicht an. Prüfen:

- Steht die VM wirklich auf **Netzwerkbrücke**? (`ip -4 addr` in der VM: eine
  Adresse aus `10.0.2.x` bedeutet NAT — falsch)
- Läuft dnsmasq? `systemctl status dnsmasq`
- Sieht dnsmasq die Anfrage überhaupt? `sudo journalctl -u dnsmasq -f` beim
  Booten beobachten. Kommt dort nichts an, ist es ein Netzwerkproblem,
  keine Konfigurationsfrage.
- Hängen Client und Maschine im selben Subnetz? PXE-Broadcasts überqueren
  keine Router und keine VLAN-Grenzen.
- **Auf Ubuntu: Ist eine Firewall im Weg?** `sudo ufw status`

Zum letzten Punkt, denn dort steckt eine Falle: Ubuntu bringt `ufw` mit,
Debian nicht. Der Bootweg läuft über **UDP** — 67 und 4011 für die
proxyDHCP-Antwort, 69 für TFTP, dazu 111 und 2049 für NFS. Ist die
Firewall an und lässt sie das nicht durch, ist der Server tadellos
eingerichtet, meldet sich gesund, die Oberfläche läuft — und es bootet
trotzdem kein einziger Rechner, ohne dass irgendwo eine Meldung stünde.

**Frag dabei `ufw` selbst, nicht systemd.** Die beiden sagen
Verschiedenes, und das führt zuverlässig in die Irre:

```
$ systemctl is-active ufw
active
$ sudo ufw status
Status: inactive
```

Beides stimmt. Die Unit ist der Dienst, der beim Systemstart das Regelwerk
*anwendet*; sie läuft auch dann, wenn gar keines aktiv ist. Wer
`systemctl status ufw` fragt, liest `active` und sucht ab da an der
falschen Stelle.

*Beim Ubuntu-Probelauf genau so passiert — erst als Fehlalarm, dann als
Erkenntnis.*

## 4.5 Der Client bekommt eine IP, lädt aber nichts

Meist TFTP:

```bash
# Von der Maschine aus selbst testen
sudo apt install tftp-hpa
tftp <BootServer-IP> -c get undionly.kpxe

ls -l /srv/pxe/tftp/
```

Fehlen die Dateien unter `/srv/pxe/tftp`, hat `install.sh` sie nicht
bekommen. Nochmal holen:

```bash
sudo /opt/pxe-setup/fetch-ipxe.sh
```

**Scheitert auch das, liegt es fast immer am Weg nach draußen**, nicht am
Skript: Die Bootloader kommen von `https://boot.ipxe.org`, und in einem
abgeschotteten Netz ist genau diese Adresse gesperrt. Ein dritter Versuch
hilft dann nicht — ein Spiegel schon:

```bash
sudo IPXE_MIRROR=https://spiegel.example.invalid/ipxe      /opt/pxe-setup/fetch-ipxe.sh
```

## 4.6 Es bootet endlos iPXE neu (Schleife)

dnsmasq erkennt das bereits laufende iPXE nicht und schiebt ihm erneut
iPXE unter. In `sudo journalctl -u dnsmasq -f` siehst du dann immer wieder
dieselbe TFTP-Anfrage. Ursache ist fast immer, dass die `dhcp-match`-Zeilen
für Option 175 in `/etc/dnsmasq.d/pxe.conf` fehlen oder verändert wurden.
Ein Lauf von `install.sh` schreibt die Datei neu.

## 4.7 UEFI-Rechner booten nicht, BIOS-Rechner schon

**Zuerst Secure Boot am Client abschalten.** iPXE ist nicht signiert und
wird sonst von der Firmware abgelehnt, meist ohne verständliche Meldung.
Das ist die mit Abstand häufigste Ursache.

Klemmt es weiterhin, ist der Netzwerktreiber dran: In
`/etc/dnsmasq.d/pxe.conf` bei der Zeile `X86-64_EFI` testweise
`snponly.efi` durch `ipxe.efi` ersetzen und `sudo systemctl restart
dnsmasq`. `snponly` benutzt den Treiber der Firmware, `ipxe.efi` bringt
eigene mit — je nach Netzwerkkarte funktioniert mal der eine, mal der
andere Weg.

**Ein Sonderfall davon: Es lädt an und bricht dann ab.** Das Menü kommt,
die kleinen Dateien kommen, und dann bleibt eine große Datei nach wenigen
Megabyte stehen — *connection timed out*. Das trifft **VirtualBox-VMs im
UEFI-Modus**; an echten Rechnern ist es nie aufgetreten, dort gehen
dieselben 700 MB in rund fünfzehn Sekunden durch. Für Windows über das
Netz also einen Blechrechner nehmen. Wer es dennoch in einer VM braucht,
**Der Treiberwechsel aus dem vorigen Absatz hilft hier allerdings nicht.**
`snponly.efi` benutzt die Firmware-Schnittstelle, die einbricht — aber
`ipxe.efi` mit seinen eigenen Treibern bleibt in VirtualBox schon beim
Initialisieren der Geräte hängen und kommt gar nicht erst bis zum
Bootskript. Beide Wege scheitern, nur an verschiedenen Stellen.

Der Fall ist beim iPXE-Projekt gemeldet und dort **offen**:
[ipxe/ipxe#1023](https://github.com/ipxe/ipxe/issues/1023) beschreibt
dasselbe Bild, ebenfalls an einer `boot.wim` — der Download bleibt nach dem
ersten Block stehen. Am Server ist also nichts zu reparieren.

## 4.8 Ein Live-System hängt beim Einhängen über NFS

Die Fehlersuche *am bootenden Rechner* steht in der Hilfe unter *Häufige
Fragen* — dort auch der wichtigste Hinweis, dass die **Zeit bis zum
Fehlschlag** sagt, worum es geht. Hier steht nur die Serverseite:

```bash
systemctl status nfs-server rpcbind
sudo exportfs -v                 # zeigt, was für wen freigegeben ist
showmount -e localhost           # sollte /srv/pxe/assets auflisten
cat /etc/exports.d/pxe.exports   # was exportiert werden soll
sudo exportfs -ra                # nach einer Änderung neu einlesen
```

Fehlt der Export, `sudo /opt/pxe-setup/install.sh` noch einmal laufen
lassen — er schreibt `/etc/exports.d/pxe.exports` neu. Hängt der Client in
einem anderen Subnetz als die Maschine, greift die Freigabe nicht: Sie gilt
absichtlich nur für das eigene Netz.

Gegenprobe von einem beliebigen Linux-Rechner im LAN:

```bash
sudo mount -t nfs <BootServer-IP>:/srv/pxe/assets /mnt
```

## 4.9 Die Konsole der VM ist voller „Failed to query local AF_VSOCK CID"

```
systemd-ssh-generator[913]: Failed to query local AF_VSOCK CID:
Cannot assign requested address
```

**Harmlos, und es liegt nicht am Bootserver.** Debian 13 bringt einen
systemd-Generator mit, der SSH über einen Socket-Typ einrichten will, den
KVM und QEMU beherrschen, VirtualBox aber nicht. Er fragt an und bekommt
eine Absage. Auf dnsmasq, nginx, pxeweb und NFS hat das keinerlei
Auswirkung — störend ist nur, dass die Anmeldeaufforderung auf tty1
untergeht. Dass es in Schüben kommt, liegt daran, dass Generatoren bei
jedem `daemon-reload` neu laufen, also bei jedem `install.sh` und jedem
Dienst-Neustart.

Sofort wieder lesbar, bis zum nächsten Neustart:

```bash
sudo dmesg -n 1        # nur noch Notfälle auf die Konsole
```

Dauerhaft — den Generator abschalten, er hat in VirtualBox ohnehin nichts
zu tun:

```bash
# Das Verzeichnis gibt es auf einem frischen Debian noch nicht --
# ohne diese Zeile scheitert ln mit "No such file or directory".
sudo mkdir -p /etc/systemd/system-generators
sudo ln -s /dev/null /etc/systemd/system-generators/systemd-ssh-generator
sudo systemctl daemon-reload
```

**Das normale SSH über das Netzwerk bleibt unberührt** — dafür ist
`openssh-server` zuständig, nicht dieser Generator. Rückgängig mit
`sudo rm /etc/systemd/system-generators/systemd-ssh-generator`.

## Und alles andere?

In der Hilfe des laufenden Servers. Der Vollständigkeit halber, wo:

| Frage | Kapitel in der Hilfe |
|---|---|
| Wie ist der Ablauf, wenn ich neu anfange? | *Der erste Durchgang* |
| Wie kommt ein Betriebssystem auf den Server? | *Quellen* — auf der Konsole: [03-betrieb.md](03-betrieb.md) |
| Warum steht mein Eintrag nicht im Bootmenü? | *Systeme* |
| Wie gebe ich einem Rechner etwas vor, wie wecke ich ihn? | *Clients* |
| Was bedeutet diese Karte, diese Ampel, dieser Wert? | das Fragezeichen an jeder Kartenüberschrift |
| Ein Rechner bootet nicht — woran liegt es? | *Häufige Fragen* |
| Wie setze ich den Server zurück? | *Einrichtung* |

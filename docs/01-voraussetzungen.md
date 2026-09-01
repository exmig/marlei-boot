# 1. Die Maschine

Was vorhanden sein muss, bevor `install.sh` läuft: die Maschine selbst,
das Netz um sie herum, und am Ende die Rechner, die später von ihr starten
sollen. Alles Weitere richtet das Skript ein.

**Drei Dinge sind zu unterscheiden, und dieses Dokument hält sie
auseinander** — sonst weiß man bei keinem Satz, wovon er handelt:

| | |
|---|---|
| **Die Maschine** | Der Rechner selbst, Blech oder VM: sein Betriebssystem, sein Arbeitsspeicher, seine Platte, seine Netzwerkkarte, seine Adresse. **Sie gehört dir** — der Bootserver fasst sie nicht an, er richtet sich nach ihr. Andere Dokumente nennen sie auch *den Host*; gemeint ist dasselbe. |
| **Der Bootserver** | Was `install.sh` **auf** der Maschine einrichtet: dnsmasq, nginx, NFS, eine SMB-Freigabe und die Weboberfläche. Er ist das, was dieses Projekt liefert — sein Name ist **MARLEI Boot**, ein Produkt der *MARLEI Assistance Suite* von Exmig. In diesen Dokumenten steht durchweg *Bootserver*, weil es dort um die Maschine vor dir geht und nicht um das Produkt. |
| **Die Clients** | Die Rechner, die später vom Bootserver starten. Für sie gilt Eigenes — siehe *Die Rechner, die davon starten* am Ende. |

## 1.1 Betriebssystem

Als Betriebssystem **der Maschine** sind **Debian 12 und 13** sowie
**Ubuntu 26.04** getestet: dort ist der ganze Weg durchgelaufen —
installiert, ein Abbild geholt, ein Rechner davon gestartet.

**Unterstützt, aber noch nicht durchgespielt** sind Ubuntu 22.04 und
24.04 sowie Raspberry Pi OS 12. Verwandte Systeme derselben Familie —
Linux Mint, Devuan, Pop!\_OS — laufen durch, ohne dass wir sie zusagen:
Sie benutzen dieselben Paketnamen und dasselbe systemd.

Auf allem anderen bricht `install.sh` ab, **bevor es etwas anfasst**, und
sagt warum. Wer es trotzdem versuchen will:

```bash
sudo PXE_OS_EGAL=1 ./setup/install.sh
```

## 1.2 Empfehlung für die Ausstattung

| | Minimum | Empfohlen | Warum |
|---|---|---|---|
| Arbeitsspeicher | 1 GB | 2 GB | Der Bootserver ist genügsam: gemessen **0,4 GB** im Betrieb, mit allen vier Diensten und NFS |
| Prozessor | 1 Kern | 2 Kerne | 1 % Last im Leerlauf. Holen und Auspacken hängen an der Platte, nicht am Rechenwerk |
| Platte | 20 GB | 60 GB | **Die einzige Zahl, die wirklich wächst** — nicht der Bootserver wächst, sondern was er ablegt. Siehe unten |
| Netz | Kabel ins selbe LAN | | Über WLAN startet kein Rechner per PXE — mehr unter *Netz, Adresse und Zugang* |

**Zur Platte, denn danach richtet sich alles:** Das Betriebssystem der
Maschine braucht etwa 1 GB, der Bootserver selbst fast nichts — Platz
frisst allein das, was er ablegt. Der ganze Katalog sind 8–10 GB, und beim Auspacken liegen Abbild
und ausgepackter Inhalt kurz nebeneinander. 20 GB reichen für ein, zwei
Systeme; 60 GB sind der bequeme Wert, wenn eigene Abbilder dazukommen.

**Windows fällt dabei aus dem Rahmen.** Von einer Windows-ISO holt der
Server nur die Startdateien heraus — ein paar hundert MB —, solange es
allein um die Konsole geht. Sind die Installationsquellen im Abbild und
ist die SMB-Freigabe eingerichtet, wird stattdessen **das ganze Medium**
ausgepackt, damit ein Windows-Setup davon installieren kann. Dann sind es
je Ausgabe **5–7 GB**. Wer zwei oder drei Windows-Ausgaben vorhalten will,
rechnet also lieber mit 100 GB als mit 60.
Nachträglich vergrößern ist lästiger, als sie gleich großzügig zu nehmen —
eine dynamische Platte belegt ohnehin nur, was benutzt wird.

*Die Zahlen sind gemessen, nicht geschätzt: auf einem frisch installierten
Debian 13 mit geladenem Linux Mint (28.08.2026).*

> **Auf dem Raspberry Pi:** Abbilder auf der SD-Karte sind langsam und
> verschleißen sie. Für mehr als gelegentliche Nutzung `/srv/pxe` auf eine
> USB-SSD legen.

## 1.3 Echte Hardware oder virtuelle Maschine?

**Gleichgültig.** Ein alter Rechner, eine VM auf dem Arbeitsplatz, ein
Container, ein Raspberry Pi — dem Bootserver ist es einerlei, worauf er
läuft.

Eine einzige Ausnahme gibt es, und sie ist keine Kleinigkeit: **Eine
virtuelle Maschine braucht eine Netzwerkbrücke, nicht NAT.** Hinter NAT
sitzt sie hinter einem virtuellen Router und bekommt die Broadcasts der
Clients nie zu sehen — der Netzwerkstart kann dann grundsätzlich nicht
funktionieren. In VirtualBox heißt die Einstellung *Netzwerkbrücke
(Bridged Adapter)*.

**Das gilt für die Maschine. Für den Testclient gibt es eine zweite
Einschränkung**, und die ist leicht zu übersehen, weil sie erst beim
ersten Test auffällt: Eine VirtualBox-VM taugt nicht überall als
Probekandidat. Sie steht unten unter *Die Rechner, die davon starten*.

## 1.4 Netz, Adresse und Zugang

**Kabel ins selbe Netz** wie die Rechner, die davon starten sollen.
PXE-Broadcasts überqueren keine Router und keine VLAN-Grenzen, und über
WLAN startet kein Rechner per Netzwerk. Auch eine Brücke über einen
WLAN-Adapter genügt nicht: Viele WLAN-Chips lassen fremde MAC-Adressen
nicht durch.

**Eine Adresse, die bleibt.** Gemeint ist die Adresse **der Maschine**.
`install.sh` liest sie ab und schreibt sie in die Konfiguration **des
Bootservers** — in die Boot-Skripte, in dnsmasq, in nginx und in den
NFS-Export. Ändert die Maschine danach ihre Adresse, findet kein Client
mehr seine Dateien, und zwar ohne Fehlermeldung, die das erklären würde.

Zwei Wege führen zu einer bleibenden Adresse, **beide sind in Ordnung**:
eine Reservierung am Router oder eine feste Adresse auf der Maschine
selbst. Was *nicht* genügt, ist eine gewöhnliche DHCP-Lease ohne
Reservierung.

> **Die Netzkonfiguration der Maschine gehört dir, nicht dem
> Bootserver.** Er fasst sie nicht an — weder bei der Installation noch
> später über die Oberfläche. Er liest sie ab, richtet sich danach und
> sagt es, wenn sie sich geändert hat. Wie du sie einträgst, hängt davon
> ab, womit dein System das Netz verwaltet: Debian minimal benutzt
> *ifupdown*, Ubuntu *netplan*, Raspberry Pi OS den *NetworkManager*. Den
> Namen der Netzwerkkarte zeigt `ip -br addr`; die Adresse muss außerhalb
> des DHCP-Bereichs deines Routers liegen.

**SSH auf der Maschine.** Die Installation und jede spätere Aktualisierung
sind Befehle auf der Konsole. Über SSH lassen sie sich vom Arbeitsplatz
aus einfügen, statt sie abzutippen. Wo man es einschaltet, hängt vom
System ab: Bei **Debian** genügt es, in der Softwareauswahl des
Installationsprogramms *SSH-Server* anzukreuzen; **Ubuntu Server** fragt
im Installationsprogramm danach; beim **Raspberry Pi OS** setzt man den
Haken im Imager oder schaltet es später mit `sudo raspi-config` ein.

**Eine Desktop-Umgebung braucht keiner von beiden** — weder die Maschine
noch der Bootserver, der ohne Bildschirm auskommt und über den Browser
eines anderen Rechners bedient wird. Bei Debian also alles andere in der
Softwareauswahl abwählen.

**Internetzugang** — und zwar zu mehr als nur den Paketquellen. Das ist
die Stelle, an der eine Installation in einem abgeschotteten Firmennetz
mittendrin abbricht, obwohl `apt` funktioniert:

| Wohin | Wofür | Ohne |
|---|---|---|
| Die **Paketquellen deiner Distribution** | dnsmasq, nginx, nfs-kernel-server, samba, Python, `libarchive-tools`, `rsync`, `curl` | Abbruch |
| **`pypi.org`** und **`files.pythonhosted.org`** | die fünf Python-Pakete der Weboberfläche (FastAPI, uvicorn, Jinja2, python-multipart, PyYAML) | Abbruch |
| **`boot.ipxe.org`** | die iPXE-Bootloader — das Einzige, was per TFTP ausgeliefert wird | Abbruch |
| **`github.com`** | `wimboot`, der Starthelfer für Windows-Abbilder | **kein Abbruch:** `install.sh` warnt, macht weiter und nennt den Befehl zum Nachholen |

**Für einen eigenen Spiegel gibt es bisher nur einen Weg**, und zwar für
die iPXE-Dateien:

```bash
sudo IPXE_MIRROR=https://spiegel.example.invalid/ipxe ./setup/install.sh
```

Für PyPI hilft die übliche `pip`-Konfiguration der Maschine, für die
Pakete die Quellen, die dort ohnehin eingetragen sind.

**Danach ist der Internetzugang nicht mehr zwingend.** Ein Bootserver
lässt sich auch in einem Netz ohne Weg nach draußen betreiben — man füttert
ihn dann anders:

- **Ein Abbild über den Browser hochladen.** Es kommt vom Rechner, an dem
  du sitzt, und geht keinen Meter ins Internet.
- **Ein Abbild von einer Adresse holen.** Die darf ein interner
  HTTP-Server sein; der Bootserver fragt nicht, wem er gehört.

Was ohne Internetzugang **nicht** geht, ist zweierlei, und das Bootmenü
sagt es von selbst:

- Der **mitgelieferte Katalog** mit *Prüfen* und *Holen* — der sieht beim
  jeweiligen Anbieter nach und lädt von dort.
- Alles in der Menügruppe **Online-Installationen**. Diese Installer sind
  klein, weil sie ihre Pakete erst während der Installation aus dem Netz
  ziehen. Die Gruppe **Offline-Installationen** kommt dagegen vollständig
  vom Bootserver — genau dafür ist die Trennung da.

## 1.5 Die Rechner, die davon starten

Auch auf der anderen Seite gibt es drei Dinge, die man vorher wissen
sollte — sonst sucht man den Fehler später beim Bootserver, wo keiner ist.

**Der Arbeitsspeicher** ist eine andere Frage als der der Maschine. Steht
NFS bereit, hängen Live-Systeme ihr Dateisystem über das Netz ein und
brauchen kaum welchen. Ohne NFS wird das ganze Abbild in den Speicher des
Clients geladen — dann ist bei ungefähr der Hälfte seines RAM Schluss.

**Secure Boot muss aus.** iPXE ist nicht signiert und wird von der
Firmware sonst abgelehnt. Der Rechner bootet dann einfach von der Platte
weiter, ohne dass irgendwo eine Meldung stünde.

**Für den ersten Test lieber ein Blechrechner als eine VM.** Bringt das
Betriebssystem der Maschine dnsmasq **2.92** mit — etwa Ubuntu 26.04 —,
dann bootet eine VirtualBox-VM als Client nicht: Du siehst iPXE und danach
*Connection timed out*, während der Bootserver kerngesund aussieht. Echte
Rechner booten davon einwandfrei, im Betrieb ändert es also nichts. Welche
Fassung läuft, sagt `dnsmasq --version`; betroffen ist 2.92, nicht 2.91
(Debian 13.6) und nicht 2.90 (Ubuntu 24.04). Ausführlich in
[02-installation.md](02-installation.md) unter *Der erste Test*.

**Und für Windows-Abbilder gilt das unabhängig von dnsmasq.** Startet eine
VirtualBox-VM im **UEFI**-Modus, bricht das Laden großer Dateien ab: Das
Menü erscheint, die kleinen Dateien kommen an, und dann bleibt die
`boot.wim` nach wenigen Megabyte stehen — iPXE meldet wieder *connection
timed out*. Dieselbe VM im BIOS-Modus lädt sie vollständig, und ein echter
Rechner im UEFI-Modus auch. Wer Windows über das Netz ausprobieren will,
nimmt dafür also einen Blechrechner.

---

Weiter mit [02-installation.md](02-installation.md).

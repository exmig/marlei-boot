<img src="webui/static/exmig-logo.svg" alt="Exmig" width="200">

# MARLEI Boot

*Teil der MARLEI Assistance Suite — herausgegeben von Exmig.*

**Ein Netzwerk-Boot-Server für das eigene LAN.** Rechner im Netz booten ohne
Stick und bekommen ein Auswahlmenü mit Installern und Rettungssystemen.
Verwaltet wird das Ganze über eine Weboberfläche.

Er läuft auf **Debian, Ubuntu oder Raspberry Pi OS** — als VM, auf einem
alten Rechner oder auf einem Raspberry Pi. Der Server muss nicht ständig
laufen: Ist er aus, merkt das Netz nichts davon, und die Rechner starten
wie gewohnt von ihrer Platte.

```
                    ┌──────────────────────────┐
   Rechner im LAN   │  Debian · Ubuntu · RasPi │
   ┌──────────┐     │                          │
   │  bootet  │◄────┤  dnsmasq   proxyDHCP     │
   │   vom    │     │            + TFTP        │
   │   Netz   │◄────┤  nginx     Kernel/Initrd │
   └──────────┘     │  pxeweb    Menü + Web-UI │
        ▲           └──────────────────────────┘
        │                        ▲
    Bootmenü                     │ Browser
    am Bildschirm          Verwaltung vom Arbeitsplatz
```

## Was es kann

- **Auswahlmenü am bootenden Rechner** — Installer und Live-Systeme,
  automatisch passend für BIOS oder UEFI, gegliedert nach der Frage, die
  vor der Maschine zählt: braucht die Installation Internet, oder kommt
  alles von diesem Server?
- **Freigabe pro Rechner — ohne Haken passiert nichts.** Wer per Netzwerk
  startet, meldet sich am BootServer an und bootet danach ganz normal von
  seiner Platte weiter: kein Menü, keine Installation. Erst eine
  ausdrückliche Freigabe gibt den nächsten Netzwerkstart frei, und mit ihr
  wird festgelegt, was dann passiert — Menü auf dem Bildschirm oder direkt
  ein bestimmtes System, ohne dass jemand am Gerät etwas auswählt. So
  bekommt nicht jedes Notebook, das versehentlich mit F12 bootet, ein
  Installationsmenü angeboten.
- **Vorauswahl im Browser pro Rechner** — für Maschinen ohne Bildschirm:
  System auswählen, freigeben, fertig. Beim nächsten Start bootet er ohne
  Menü durch. Danach nimmt der Server die Freigabe von selbst wieder
  zurück — sonst würde sich eine frisch installierte Maschine sofort wieder
  neu aufsetzen, und in der Liste stünde weiter eine Installation, die
  längst erledigt ist.
- **Einschalten per Wake-on-LAN** — im Browser festlegen, was der Rechner
  starten soll, und ihn im selben Zug aufwecken. Er fährt hoch,
  bootet vom Netz und landet ohne Menü im gewünschten System — ohne dass
  jemand vor der Maschine steht.
- **Abbild von einer Adresse holen** — Download-Link einfügen, der Server
  lädt selbst und hängt das System ins Menü. So kommt eine neue
  Distribution dazu, ohne eine Kernel-Kommandozeile zu kennen. Und die
  Download-Quellen der mitgelieferten Systeme lassen sich im Browser
  pflegen und prüfen, wenn ein Link veraltet.
- **Protokolle misslungener Installationen** — bricht auf einem Rechner die
  Installation ab, schickt eine Zeile im Live-System alle Protokolle an den
  Server, bevor sie mit dem Neustart verloren gehen. Abzuholen im Browser.
- **Eigene Netz-Installer aufnehmen** — für Systeme ohne ISO, etwa Kali:
  Bauart wählen, Adresse des Spiegels eintragen, fertig. Die passende
  Kernel-Kommandozeile kennt der Server aus der Bauart.
- **Mehrere Ausgaben nebeneinander** — Fedora, openSUSE Leap, Ubuntu Server
  und Rocky dürfen in mehreren Versionen gleichzeitig bereitstehen, jede mit
  eigenem Menüpunkt und eigenem Verzeichnis. Solange Rechner mit einer
  älteren Version laufen, bleibt ihr Installationsmedium verfügbar.
- **Verträglich mit dem vorhandenen Router** — dnsmasq läuft als
  *proxyDHCP*: die IP-Vergabe bleibt beim Router, es gibt keinen zweiten
  DHCP-Server im Netz. Ist die VM aus, merkt das LAN nichts davon.
- **Eigene ISOs über den Browser** — Abbild hochladen, der Server erkennt
  selbst, welches System darin steckt, und hängt es ins Bootmenü. Große
  Live-Systeme wie Ubuntu Desktop werden dabei über NFS gestreamt, statt in
  den Arbeitsspeicher des bootenden Rechners geladen — sonst wäre bei
  ungefähr der Hälfte seines RAM Schluss.
- **Windows-Konsole aus einer Windows-ISO** — lädt man ein
  Windows-Abbild hoch, entsteht daraus kein Installer, sondern eine
  Eingabeaufforderung, die komplett im Arbeitsspeicher läuft. Praktisch für
  Herstellerprogramme, die es nur für Windows gibt — etwa BIOS-Updates —
  ohne dass auf dem Rechner ein Windows installiert sein muss. Windows
  *installieren* geht ebenfalls, in zwei Zeilen von Hand — das Setup lädt
  seine Quellen nur über eine Dateifreigabe, und die richtet
  `install.sh` mit ein.
- **Schnell** — nur der erste, wenige hundert KB große Bootloader geht
  über TFTP, alles Weitere über HTTP.

Mitgeliefert im Katalog: Debian 13, Ubuntu Server 26.04 LTS, Linux Mint,
Fedora 44, openSUSE Leap und Tumbleweed, Rocky Linux 9 und 10, SystemRescue,
GParted Live, Clonezilla, Memtest86+ sowie netboot.xyz als
Online-Katalog.

## Worauf es läuft

| | |
|---|---|
| **Debian** 12 / 13 | getestet |
| **Ubuntu** 22.04 / 24.04 | unterstützt, noch nicht durchgespielt |
| **Ubuntu** 26.04 | getestet — eine Einschränkung beim *Testen*, siehe unten |
| **Raspberry Pi OS** 12 (32 und 64 Bit) | unterstützt — der Durchlauf steht aus |

*Unterstützt* heißt: Die Installation ist dafür gebaut und `install.sh`
erkennt das System. *Getestet* heißt: Es ist dort von vorn bis hinten
durchgelaufen — installiert, ein Abbild geholt, ein Rechner davon
gestartet. Beides auseinanderzuhalten ist Absicht: Eine Zusage, die
niemand durchgespielt hat, fällt beim ersten fremden Nutzer auf.

Beim **Raspberry Pi** fehlt allein der Durchlauf von vorn bis hinten; das
Gerät dafür steht bereit. Wer nicht warten will und es selbst versucht:
Rückmeldung ist willkommen — dann wird daraus ein *getestet*.

> **Die Einschränkung betrifft nur das Testen, nicht den Betrieb:** Läuft
> auf dem Server dnsmasq 2.92, bootet eine **VirtualBox-VM als Testclient**
> nicht — echte Rechner booten einwandfrei. Für den ersten Test also einen
> Blechrechner nehmen. Was dahintersteckt und woran man es erkennt, steht
> in [docs/02-installation.md](docs/02-installation.md) unter *Der erste
> Test*.

## Loslegen

| Schritt | Dokument |
|---|---|
| 1. Was die Maschine mitbringen muss | [docs/01-voraussetzungen.md](docs/01-voraussetzungen.md) |
| 2. Server installieren und testen | [docs/02-installation.md](docs/02-installation.md) |
| 3. Im Betrieb: was auf der Konsole zu tun ist | [docs/03-betrieb.md](docs/03-betrieb.md) |
| 4. Fehlersuche, wenn der Server nicht antwortet | [docs/04-fehlersuche.md](docs/04-fehlersuche.md) |

**Ein Befehl installiert alles**, danach geschieht der Rest im Browser:
Ein frisch aufgesetzter Server bringt die *Auswahl* der Distributionen
mit, aber noch keine Dateien — welche Ausgabe es gerade gibt, weiß der
Anbieter besser als eine mitgelieferte Liste.

**Eigene Einträge entstehen über die Oberfläche**, nicht durch Bearbeiten
von `catalog.yaml`. Wer die Datei im Klon ändert, bei dem scheitert später
`git pull --ff-only` — und die Meldung verrät den Grund nicht.

*Der Zweig `main` ist der Entwicklungszweig:* Was dort liegt, ist der
Stand, an dem gearbeitet wird. Wer eine feste Fassung will, nimmt ein
Release.

Der ganze Weg bis zu einem Rechner, der vom Netz startet, steht in der
Hilfe unter **Der erste Durchgang** — acht Schritte, jeder mit dem
Ausschnitt der Oberfläche daneben, um den es geht. **Das ist der Weg, den
man einmal durcharbeitet und danach kann:** Wer ihn hinter sich hat, kennt
den Arbeitsablauf. Alles Weitere schlägt man in der Hilfe nach, statt es
vorher zu lernen.

**[Diese Hilfe steht im Netz](https://exmig.github.io/marlei-boot/)** — man
kann sie lesen, ohne etwas installiert zu haben. Es ist dieselbe Seite, die
der Server ausliefert; nur die Wege in die Oberfläche fehlen, denn dahin
führt von dort aus nichts.

## Was heute so ist, kann morgen anders sein

Dieser Server wird benutzt und weiterentwickelt. Wo eine Entscheidung
Gewicht hat, steht ihr Grund dabei — warum die Oberfläche so aussieht,
warum die Reiter in dieser Reihenfolge stehen, warum etwas bewusst fehlt.
**Ein aufgeschriebener Grund ist aber kein Versprechen für alle Zeit:**
Ändern sich die Annahmen, unter denen entschieden wurde, ändert sich auch
die Entscheidung.

Das gilt ausdrücklich dort, wo heute etwas *nicht* geht. Was als bewusste
Entscheidung dokumentiert ist, ist damit nicht für immer ausgeschlossen —
es ist begründet abgelehnt, und Gründe kann man widerlegen.
Rückmeldungen sind willkommen.

## Was die Versionsnummer sagt

Kein SemVer — dieses Projekt hat keine Programmierschnittstelle, die
brechen könnte. Die drei Stellen zählen Arbeit, nicht Verträglichkeit:

- **1.**x.x — gravierende Änderungen: neue Fähigkeiten, schwere Fehler
  behoben.
- x.**1**.x — ein Meilenstein ist abgenommen.
- x.x.**1** — eine Aufgabe ist abgenommen.

**Die dritte Stelle heißt also nicht „nur Fehlerbehebungen".** Hinter ihr
kann eine neue Karte, eine neue Einstellung oder ein neuer Dienst stecken.
Was drin ist, sagt der Name der Ausgabe; ob sich das Holen lohnt, sagt der
Server selbst — er sieht auf Wunsch nach, ob im Repository etwas
dazugekommen ist, und nennt die Zahl.

## Lizenz

Der Quelltext steht unter der **GNU Affero General Public License,
Version 3** — der volle Text liegt als `LICENSE` daneben. Kurz und ohne
Juristendeutsch:

- **Benutzen kostet nichts und verpflichtet zu nichts.** Wer diesen Server
  installiert und betreibt, hat mit der Lizenz nichts weiter zu tun — zu
  Hause wie im Betrieb. *Für Betriebe steht darunter trotzdem eine Bitte.*
- **Wer ihn ändert und weitergibt**, gibt seine Änderungen unter derselben
  Lizenz weiter. Das gilt auch dann, wenn die geänderte Fassung nicht als
  Datei weitergereicht, sondern nur über das Netz benutzbar gemacht wird —
  das ist der Unterschied zwischen AGPL und GPL.

**Name und Logo sind davon ausgenommen.** Die Lizenz gilt für den
Quelltext, nicht für die Marke: Wer eine eigene Fassung weitergibt, gibt
ihr bitte einen eigenen Namen.

**Rückmeldungen sind willkommen, Code kann ich derzeit nicht annehmen** —
warum, und womit du stattdessen am meisten hilfst, steht in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Wenn dieser Server bei Ihnen im Betrieb läuft

Privat, im Verein, in der Ausbildung: **nehmen Sie ihn, kostenlos und ohne
Gegenleistung.** Genau dafür ist die Lizenz da, und es wird nie jemand
nachfragen.

**Im Betrieb ist die Lage eine andere.** Ein Werkzeug, das Ihnen diese
Arbeit abnimmt, hätten Sie sonst einkaufen müssen — mit Lizenzkosten pro
Jahr und pro Gerät. Geleistet wurde die Arbeit trotzdem: von einer Person,
in ihrer Zeit, auf ihre Kosten. **Die Lizenz verlangt dafür nichts. Sie
kann es nicht, und das soll auch so bleiben.**

Deshalb keine Bedingung, sondern eine Bitte — und sie richtet sich an das
Haus, nicht an den Administrator, der ihn aufgesetzt hat:

> **Melden Sie sich.** Schon ein Satz darüber, wo dieser Server läuft und
> was er bei Ihnen ersetzt hat, ist etwas wert — er sagt mir, wofür ich das
> hier eigentlich baue, und niemand sonst kann mir das sagen. Und wenn Ihr
> Haus die Arbeit darüber hinaus finanziell anerkennen möchte, dann ist das
> der Weg dorthin.

Ein Betrieb, der ein freies Werkzeug jahrelang produktiv nutzt und dem, der
es gebaut hat, nie ein Wort schreibt, tut nichts Unrechtes. Er tut nur
nichts.

**Der Weg dorthin: [kontakt@exmig.de](mailto:kontakt@exmig.de).** Ein
Satz genügt. Alles, was den Server selbst betrifft — ein Fehler, eine
Frage, ein Vorschlag —, ist in den *Issues* und *Discussions* dieses
Repositorys besser aufgehoben; dort steht es öffentlich und hilft dem
Nächsten mit.

---

*Wer am Quelltext arbeitet: [docs/aufbau.md](docs/aufbau.md) sagt, welche
Datei wofür da ist, [docs/gestaltung.md](docs/gestaltung.md), warum die
Oberfläche so aussieht.*

© 2026 Exmig

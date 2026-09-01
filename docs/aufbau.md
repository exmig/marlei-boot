# Aufbau des Projekts

**Welche Datei wofür da ist.** Zum Nachschlagen, wenn du am Quelltext
arbeitest — zum Installieren und Benutzen brauchst du diese Seite nicht.

Diese Datei trägt keine Nummer, und das ist die Regel: **Die nummerierten
Dokumente 01 bis 04 gehören dem, der den Server aufsetzt und betreibt** —
Voraussetzungen, Installation, Betrieb, Fehlersuche. Alles ohne Nummer
beschreibt den Quelltext selbst: hier der Aufbau, in
[gestaltung.md](gestaltung.md) die Gestaltung.

```
setup/
  install.sh              Installiert alles auf einem frischen Debian
  fetch-ipxe.sh           Holt die iPXE-Bootloader
  fetch-wimboot.sh        Holt wimboot -- damit startet die Windows-Konsole
  sync-images.sh          Lädt Kernel, Initrds und ISOs; Ausgaben kommen aus quellen.env
  update.sh               Auf der Maschine: neuen Stand holen und übernehmen
  git-deploy.sh           Alternative ohne externes Repository (siehe docs/02)
  files/
    dnsmasq-pxe.conf      proxyDHCP + TFTP (kommentiert)
    nginx-pxe.conf        Ausliefern der Boot-Dateien + Reverse Proxy
    pxeweb.service        systemd-Unit
    pxeweb.env.example    Einstellungen der Web-App

webui/
  app.py                  FastAPI: Weboberfläche und iPXE-Skriptgenerator
  isoscan.py              Liest ISO-Abbilder und erkennt das Betriebssystem
  udf.py                  Liest das UDF-Dateisystem -- Windows-Medien haben nur das
  uploads.py              Eigene Abbilder: hochladen, holen, auspacken
  quellen.py              Download-Adressen anzeigen, prüfen, ersetzen
  wol.py                  Wake-on-LAN: Magic Packets bauen und senden
  logs.py                 Installationsprotokolle der Clients ablegen
  dienste.py              Laufen nginx, dnsmasq, pxeweb und NFS?
  auslastung.py           Last des Servers und laufende Übertragungen
  journal.py              Journal der Dienste lesen (nur diese vier)
  sync.py                 sync-images.sh aus der Oberfläche anstoßen
  eigene.py               Selbst angelegte Netz-Installer (Kernel + Initrd)
  konfiguration.py        Ablageorte und ihre Belegung nachschlagen
  quellenwacht.py         Sieht wöchentlich nach, welche Download-Adresse tot ist
  werkseinstellung.py     Zurück auf den Auslieferungszustand
  serveradresse.py        Prüft eine neue Server-IP und baut den Befehl dafür
  versionsstand.py        Welcher Stand läuft -- gestempelt von install.sh
  catalog.yaml            Die Bootmenü-Einträge -- hier wird gepflegt
  templates/
    *.ipxe.j2             Die generierten Boot-Skripte
    wimboot.ipxe.j2       Sonderfall Windows: Dateien mit festen Zielnamen
    base.html             Rahmen mit Navigation
    serverhealth.html     Startseite: Dienste, was gerade läuft, Auslastung
    _status.html          Der sich auffrischende Teil davon
    einrichtung.html      Ablageorte und geltende Einstellungen
    history.html          Was wann gestartet wurde
    clients.html          Clients, Vorauswahl, Wecken, Protokolle
    systeme.html          Startbare Systeme, Abbild hinzufügen
    quellen.html          Download-Quellen mit Prüfung
    protokoll.html        Journal eines Dienstes, mitlesend
    hilfe.html            Erklärt das System für neue Benutzer
```

Nicht in dieser Liste, weil sie nicht zum Server gehören:

| | |
|---|---|
| `marke/` | Wortmarke, Zeichen und Favicon — siehe [marke/README.md](../marke/README.md). **Sie liegen nicht unter der AGPL.** |
| `tools/hilfe-vorschau.py` | Gibt die Hilfe ohne laufenden Server aus, samt der Dateien, auf die sie verweist |
| `tools/karten-vorschau.py` | Zeigt die drei Stufen der Seitenkarten ohne laufenden Server — sie treten sonst erst auf, wenn wirklich etwas ausfällt |
| `tests/` | Prüfen die Anwendung ohne echten PXE-Boot — siehe [tests/README.md](../tests/README.md) |
| `diagnose/` | Eingesammelte Protokolle von Clients; bis auf die README nicht im Repository |

---

Warum die Oberfläche aussieht, wie sie aussieht — Farbwerte, Kontrastzahlen
und die Regeln dahinter — steht in [gestaltung.md](gestaltung.md).

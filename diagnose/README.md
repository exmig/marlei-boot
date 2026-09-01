# Diagnose

Ablage für Protokolle, die von einem Rechner eingesammelt wurden — die
Pakete aus *Installationsprotokolle* in der Weboberfläche oder von Hand
kopierte Dateien.

Hier hineingelegte Dateien werden **nicht** ins Repository übernommen (siehe
`.gitignore`). Absicht: in Installationsprotokollen stehen Gerätenamen,
Partitionierung und je nach Installer auch Benutzernamen. Zur Fehlersuche
sind sie nützlich, im Repository haben sie nichts verloren.

Auspacken:

```bash
tar xzf diagnose/protokolle.tgz -C diagnose/
```

Erkenntnisse, die bleiben sollen, gehören als Text nach
`docs/04-fehlersuche.md` — nicht als Rohdaten hierher.

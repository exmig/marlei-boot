#!/usr/bin/env bash
# ===========================================================================
# Holt wimboot nach /srv/pxe/assets/wimboot.
#
# wimboot ist das Gegenstueck zu "Kernel + Initrd" fuer Windows. Ein
# Windows-Bootmanager laesst sich nicht wie ein Linux-Kernel starten -- er
# erwartet eine Handvoll Dateien unter festen Namen in einem Dateisystem.
# wimboot ist ein winziges Programm (rund 40 KB), das iPXE als Kernel laedt:
# es nimmt die per "initrd" uebergebenen Dateien, blendet sie dem
# Bootmanager als Verzeichnis ein und uebergibt an ihn.
#
# Anders als die iPXE-Bootloader liegt wimboot deshalb nicht im
# TFTP-Verzeichnis, sondern bei den Abbildern: es geht ueber HTTP, wie
# alles nach dem ersten Bootloader.
#
# Gebraucht wird es nur, wenn ein Windows-Abbild hochgeladen wurde. Die
# Datei ist klein genug, um sie trotzdem immer zu holen.
# ===========================================================================
set -euo pipefail

ASSETS_DIR="${PXE_ASSETS:-/srv/pxe/assets}"
ZIEL_DIR="$ASSETS_DIR/wimboot"

# Achtung, anders als bei den iPXE-Bootloadern: auf boot.ipxe.org liegt
# wimboot NICHT -- die Adresse antwortet mit 404. Ausgeliefert wird es nur
# ueber die Freigaben des Projekts auf GitHub. "latest" zeigt immer auf die
# neueste Ausgabe; die Datei aendert sich selten, und eine feste
# Versionsnummer waere eine Stelle mehr, die mit der Zeit veraltet.
WIMBOOT_URL="${WIMBOOT_URL:-https://github.com/ipxe/wimboot/releases/latest/download/wimboot}"

mkdir -p "$ZIEL_DIR"

fetch() {
  local url="$1" name="$2"
  printf '    %-16s ' "$name"
  if ! curl -fsSL --retry 3 --max-time 120 -o "$ZIEL_DIR/$name.tmp" "$url"; then
    rm -f "$ZIEL_DIR/$name.tmp"
    printf 'FEHLGESCHLAGEN\n'
    printf '        %s\n' "$url"
    return 1
  fi

  # Ist das wirklich wimboot? Ein Server, der statt der Datei eine
  # Fehlerseite ausliefert, tut das gern mit Erfolgsmeldung -- dann laege
  # hier HTML, der Menuepunkt saehe vollstaendig aus, und stehen bliebe der
  # Rechner erst vor der Maschine. wimboot ist ein PE-Programm und faengt
  # wie jedes mit "MZ" an.
  if [[ "$(head -c 2 "$ZIEL_DIR/$name.tmp")" != "MZ" ]]; then
    rm -f "$ZIEL_DIR/$name.tmp"
    printf 'UNBRAUCHBAR\n'
    printf '        %s\n' "$url"
    printf '        Geliefert wurde kein Programm, vermutlich eine Fehlerseite.\n'
    return 1
  fi

  mv "$ZIEL_DIR/$name.tmp" "$ZIEL_DIR/$name"
  printf 'ok (%s)\n' "$(du -h "$ZIEL_DIR/$name" | cut -f1)"
}

echo "wimboot nach $ZIEL_DIR:"

if ! fetch "$WIMBOOT_URL" wimboot; then
  echo
  echo "[!] wimboot fehlt. Hochgeladene Windows-Abbilder erscheinen dann"
  echo "    im Bootmenue als unvollstaendig. Internetverbindung der VM"
  echo "    pruefen und das Skript erneut ausfuehren."
  exit 1
fi

chmod 0644 "$ZIEL_DIR/wimboot"

# nginx liefert als www-data aus und braucht Lesezugriff auf den Pfad.
chmod 0755 "$ZIEL_DIR"

#!/usr/bin/env bash
#
# Einmaliger Umzug der Ablage: ein Eintrag, ein Verzeichnis, benannt nach
# seiner Kennung.
#
#   ubuntu/26.04            ->  ubuntu-server-26-04
#   mint                    ->  mint-cinnamon
#   memtest/8.10            ->  memtest-bios-8-10 + memtest-efi-8-10
#   upload/iso-...          ->  iso-...
#   eigene/netz-...         ->  netz-...
#
# Vorher musste die Anwendung erraten, wo ein Eintrag anfaengt und aufhoert.
# Sie hat dabei 3,3 GB uebersehen und einmal das Wurzeldateisystem von
# SystemRescue zum Loeschen angeboten. Seit die Kennung den Ordner benennt,
# gibt es nichts mehr zu erraten -- aber die vorhandenen Dateien liegen noch
# am alten Platz, und ohne diesen Umzug wuerde alles neu geladen.
#
# Verschoben wird mit "mv" auf derselben Platte: Das kostet keine Zeit und
# keinen Platz, egal wie gross ein Abbild ist.
#
# Das Skript laesst sich mehrfach laufen. Es fasst nichts an, was schon am
# neuen Platz liegt, und es ueberschreibt nie: Gibt es das Ziel bereits,
# bleibt die Quelle stehen und wird gemeldet.
#
#   ./umzug-ablage.sh --probe   nur zeigen, was passieren wuerde
#   ./umzug-ablage.sh           wirklich verschieben
#
set -euo pipefail

ASSETS="${PXE_ASSETS:-/srv/pxe/assets}"
PROBE=0
[[ "${1:-}" == "--probe" ]] && PROBE=1

rot=$'\e[31m'; gruen=$'\e[32m'; gelb=$'\e[33m'; aus=$'\e[0m'
ok()   { echo "  ${gruen}✓${aus} $*"; }
warn() { echo "  ${gelb}!${aus} $*"; }
bad()  { echo "  ${rot}✗${aus} $*"; }

[[ -d "$ASSETS" ]] || { bad "Ablage nicht gefunden: $ASSETS"; exit 1; }
echo "Ablage: $ASSETS"
[[ $PROBE == 1 ]] && echo "(Probelauf -- es wird nichts verschoben)"
echo

bewegt=0
stehen=0

# Kennung aus einer Ausgabe: 26.04 -> 26-04. Dieselbe Regel wie in
# webui/app.py (_mit_version) und setup/sync-images.sh (ablage).
kennung() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'
}

# Verschiebt quelle -> ziel, wenn die Quelle da und das Ziel frei ist.
schiebe() {
  local quelle="$1" ziel="$2"
  [[ -e "$quelle" ]] || return 0
  if [[ -e "$ziel" ]]; then
    warn "${ziel#"$ASSETS"/} gibt es schon -- ${quelle#"$ASSETS"/} bleibt liegen"
    stehen=$((stehen + 1))
    return 0
  fi
  if [[ $PROBE == 1 ]]; then
    ok "${quelle#"$ASSETS"/}  ->  ${ziel#"$ASSETS"/}"
  else
    mkdir -p "$(dirname "$ziel")"
    mv "$quelle" "$ziel"
    ok "${quelle#"$ASSETS"/}  ->  ${ziel#"$ASSETS"/}"
  fi
  bewegt=$((bewegt + 1))
}

# Einen Behaelter leeren: alles darin eine Ebene hoeher, unter gleichem Namen.
behaelter() {
  local name="$1" kind
  [[ -d "$ASSETS/$name" ]] || return 0
  for kind in "$ASSETS/$name"/*; do
    [[ -e "$kind" ]] || continue
    schiebe "$kind" "$ASSETS/$(basename "$kind")"
  done
}

# Ein Verzeichnis mit Ausgaben darunter: <alt>/<ausgabe> -> <basis>-<ausgabe>
ausgaben() {
  local alt="$1" basis="$2" kind
  [[ -d "$ASSETS/$alt" ]] || return 0
  for kind in "$ASSETS/$alt"/*; do
    [[ -d "$kind" ]] || continue
    schiebe "$kind" "$ASSETS/${basis}-$(kennung "$(basename "$kind")")"
  done
}

echo "Hochgeladene und selbst angelegte Eintraege"
behaelter upload
behaelter eigene
echo

echo "Mitgelieferte Systeme"
# Debian ist seit August 2026 mehrversionig und wird ueber den Codenamen
# geholt. Beide Zwischenstaende koennen vorliegen: der ganz alte Pfad und
# der aus dem ersten Umzug.
schiebe "$ASSETS/debian/13/amd64"        "$ASSETS/debian-trixie"
schiebe "$ASSETS/debian-13"              "$ASSETS/debian-trixie"
schiebe "$ASSETS/mint"                   "$ASSETS/mint-cinnamon"
schiebe "$ASSETS/opensuse/tumbleweed"    "$ASSETS/opensuse-tumbleweed"
ausgaben ubuntu       ubuntu-server
ausgaben fedora       fedora-server
ausgaben rocky        rocky
ausgaben systemrescue systemrescue
ausgaben gparted      gparted-live
ausgaben clonezilla   clonezilla

# openSUSE Leap lag als "leap-<ausgabe>" -- das Praefix gehoert jetzt zur
# Kennung und darf nicht doppelt auftauchen.
if [[ -d "$ASSETS/opensuse" ]]; then
  for kind in "$ASSETS/opensuse"/leap-*; do
    [[ -d "$kind" ]] || continue
    schiebe "$kind" "$ASSETS/opensuse-leap-$(kennung "$(basename "$kind" | sed 's/^leap-//')")"
  done
fi

# Memtest teilte sich einen Ordner fuer zwei Eintraege -- BIOS und UEFI
# bekommen jetzt jeder seinen eigenen, mit je einer Datei darin.
if [[ -d "$ASSETS/memtest" ]]; then
  for kind in "$ASSETS/memtest"/*; do
    [[ -d "$kind" ]] || continue
    v="$(kennung "$(basename "$kind")")"
    schiebe "$kind/memtest.bin" "$ASSETS/memtest-bios-${v}/memtest.bin"
    schiebe "$kind/memtest.efi" "$ASSETS/memtest-efi-${v}/memtest.efi"
  done
fi
echo

# Was leer zurueckbleibt, geht mit. Was noch etwas enthaelt, bleibt stehen
# und faellt in der Oberflaeche als verwaister Ordner auf -- genau richtig:
# Dort liegt dann eine Ausgabe, zu der es keinen Eintrag mehr gibt.
if [[ $PROBE == 0 ]]; then
  for name in upload eigene debian ubuntu fedora opensuse rocky \
              systemrescue gparted clonezilla memtest; do
    [[ -d "$ASSETS/$name" ]] || continue
    if find "$ASSETS/$name" -mindepth 1 -type f -print -quit | grep -q .; then
      warn "$name/ ist nicht leer -- bleibt stehen (steht dann unter \"Verwaiste Ordner\")"
    else
      rm -rf "$ASSETS/$name"
      ok "$name/ war leer und ist weg"
    fi
  done
  echo
fi

echo "Verschoben: $bewegt   Liegen geblieben: $stehen"
if [[ $PROBE == 1 ]]; then
  echo "Das war ein Probelauf. Ohne --probe wird es wirklich gemacht."
fi

#!/usr/bin/env bash
# ===========================================================================
# Holt in der VM den neuesten Stand aus dem Repository und uebernimmt ihn.
#
#     ./setup/update.sh
#     /opt/pxe-setup/update.sh      -- geht ebenfalls, siehe unten
#
# Bewusst OHNE sudo aufrufen: "git pull" soll mit deinem Benutzer und
# deinem SSH-Schluessel laufen, nicht als root. Fuer install.sh fragt das
# Skript selbst nach dem Passwort.
# ===========================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[X]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -ne 0 ]] || die "Bitte OHNE sudo aufrufen -- git soll deinem Benutzer gehoeren."

# Aufruf aus der nach /opt/pxe-setup gespiegelten Kopie: Dort liegt nur
# setup/, PROJECT_DIR waere also /opt -- und das ist kein Repository. Den
# Weg zurueck legt install.sh bei jedem Lauf daneben ("projektpfad"), und
# install.sh selbst geht ihn seit jeher. Hier fehlte er: Es lag eine
# ausfuehrbare Datei, die nie funktionieren konnte, neben der Datei mit
# der Antwort. Aufgefallen am 04.09.2026, beim ersten Update nach der
# Veroeffentlichung.
if ! git -C "$PROJECT_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  ZURUECK="$(dirname "${BASH_SOURCE[0]}")/projektpfad"
  if [[ -r "$ZURUECK" ]]; then
    PROJEKT="$(head -n1 "$ZURUECK")"
    if [[ -d "$PROJEKT/.git" && -x "$PROJEKT/setup/update.sh" ]]; then
      log "Uebergabe an den Projektordner: $PROJEKT"
      exec "$PROJEKT/setup/update.sh" "$@"
    fi
  fi
fi

cd "$PROJECT_DIR"
git rev-parse --git-dir >/dev/null 2>&1 \
  || die "$PROJECT_DIR ist kein Git-Repository. Erst klonen (siehe docs/02)."

BEFORE="$(git rev-parse HEAD)"

log "Neuen Stand holen"
# --ff-only: lieber sauber abbrechen als einen Merge-Commit erzeugen.
# Die VM soll nur nachziehen, entwickelt wird auf dem Arbeitsplatz.
if ! git pull --ff-only; then
  echo
  echo "Der Stand laesst sich nicht ohne Weiteres uebernehmen."
  echo "Meist wurde hier in der VM etwas veraendert. Was, zeigt:"
  echo "    git -C $PROJECT_DIR status"
  echo
  echo "Wegwerfen und stur den Stand aus dem Repository nehmen:"
  echo "    git -C $PROJECT_DIR fetch origin && git -C $PROJECT_DIR reset --hard origin/main"
  exit 1
fi

AFTER="$(git rev-parse HEAD)"

if [[ "$BEFORE" == "$AFTER" ]]; then
  log "Schon aktuell ($(git log -1 --format='%h %s'))"
  echo "    install.sh trotzdem ausfuehren? Dann direkt:"
  echo "      sudo $PROJECT_DIR/setup/install.sh"
  exit 0
fi

log "Diese Aenderungen sind dazugekommen"
git --no-pager log --oneline "$BEFORE..$AFTER"
echo
git --no-pager diff --stat "$BEFORE..$AFTER"

# Wenn sich die Download-Quellen geaendert haben, ist danach meist auch ein
# Lauf von sync-images.sh faellig -- darauf hinweisen, aber nicht selbst
# starten, das kann Stunden dauern und Gigabytes ziehen.
IMAGES_CHANGED=0
git diff --name-only "$BEFORE..$AFTER" | grep -qE 'sync-images\.sh|catalog\.yaml' \
  && IMAGES_CHANGED=1

log "Uebernehmen"
chmod +x "$PROJECT_DIR"/setup/*.sh
sudo "$PROJECT_DIR/setup/install.sh"

if [[ $IMAGES_CHANGED -eq 1 ]]; then
  cat <<HINT

---------------------------------------------------------------------------
 Katalog oder Download-Quellen haben sich geaendert. Falls Eintraege in der
 Weboberflaeche als "fehlt" markiert sind:

   sudo /opt/pxe-setup/sync-images.sh

---------------------------------------------------------------------------
HINT
fi

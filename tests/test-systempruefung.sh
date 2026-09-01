#!/usr/bin/env bash
# ===========================================================================
# Prueft, auf welchen Systemen install.sh anlaeuft -- und auf welchen nicht.
#
#     bash tests/test-systempruefung.sh
#
# Warum als eigener Test: Seit dem 27.08.2026 steht im README die Zusage
# "Debian, Ubuntu, Raspberry Pi OS". Eine Zusage, die niemand nachprueft,
# ist eine Behauptung -- und die faellt beim ersten fremden Nutzer auf.
#
# Geprueft wird das echte Skript, nicht eine Kopie der Logik: install.sh
# liest /etc/os-release ueber PXE_OS_RELEASE und steigt bei
# PXE_NUR_PRUEFUNG=1 gleich danach aus. Deshalb braucht dieser Test weder
# root noch eine VM je Distribution.
# ===========================================================================
set -uo pipefail

HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="$HIER/../setup/install.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fails=0
ok()   { printf '  \033[32mOK  \033[0m %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; fails=$((fails + 1)); }

# erwartung: laeuft | warnt | bricht_ab
probe() {
  local erwartung="$1" name="$2"; shift 2
  local datei="$TMP/os-release"
  printf '%s\n' "$@" > "$datei"

  local ausgabe rc
  ausgabe="$(PXE_OS_RELEASE="$datei" PXE_NUR_PRUEFUNG=1 \
             PXE_OS_EGAL="${PXE_OS_EGAL:-0}" bash "$INSTALL" 2>&1)"
  rc=$?

  case "$erwartung" in
    laeuft)
      if [[ $rc -eq 0 ]] && ! grep -q '\[!\]' <<<"$ausgabe"; then
        ok "$name laeuft ohne Hinweis durch"
      else
        fail "$name -- erwartet: sauber durch, bekommen: rc=$rc"
        sed 's/^/        /' <<<"$ausgabe"
      fi ;;
    warnt)
      if [[ $rc -eq 0 ]] && grep -q '\[!\]' <<<"$ausgabe"; then
        ok "$name laeuft, aber mit Hinweis"
      else
        fail "$name -- erwartet: laeuft mit Hinweis, bekommen: rc=$rc"
        sed 's/^/        /' <<<"$ausgabe"
      fi ;;
    bricht_ab)
      if [[ $rc -ne 0 ]] && grep -q 'Debian, Ubuntu und Raspberry Pi OS' <<<"$ausgabe"; then
        ok "$name bricht ab und sagt warum"
      else
        fail "$name -- erwartet: Abbruch mit Begruendung, bekommen: rc=$rc"
        sed 's/^/        /' <<<"$ausgabe"
      fi ;;
  esac
}

echo
echo "Die drei zugesagten Systeme"
probe laeuft "Debian 13"          'ID=debian'    'VERSION_ID="13"'    'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"'
probe laeuft "Debian 12"          'ID=debian'    'VERSION_ID="12"'    'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"'
probe laeuft "Ubuntu 24.04"       'ID=ubuntu'    'ID_LIKE=debian' 'VERSION_ID="24.04"' 'PRETTY_NAME="Ubuntu 24.04.1 LTS"'
probe laeuft "Ubuntu 22.04"       'ID=ubuntu'    'ID_LIKE=debian' 'VERSION_ID="22.04"' 'PRETTY_NAME="Ubuntu 22.04.5 LTS"'
# Raspberry Pi OS meldet sich in 64 Bit selbst als Debian, in 32 Bit als
# Raspbian. Beide Wege muessen ankommen.
probe laeuft "Raspberry Pi OS 64" 'ID=debian'    'VERSION_ID="12"'    'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"'
probe laeuft "Raspberry Pi OS 32" 'ID=raspbian'  'ID_LIKE=debian' 'VERSION_ID="12"' 'PRETTY_NAME="Raspbian GNU/Linux 12 (bookworm)"'

echo
echo "Bekannte Familie, ungeprueftes Alter -- laeuft mit Hinweis"
probe warnt  "Debian 11"          'ID=debian'    'VERSION_ID="11"'    'PRETTY_NAME="Debian GNU/Linux 11 (bullseye)"'
probe warnt  "Ubuntu 20.04"       'ID=ubuntu'    'ID_LIKE=debian' 'VERSION_ID="20.04"' 'PRETTY_NAME="Ubuntu 20.04.6 LTS"'

echo
echo "Abkoemmlinge ohne eigenen Boden -- laufen durch"
# Mint meldet ID_LIKE=ubuntu, nicht debian. Das war beim ersten Entwurf
# der Pruefung uebersehen und haette Mint abgewiesen.
probe laeuft "Linux Mint 22"      'ID=linuxmint' 'ID_LIKE=ubuntu' 'VERSION_ID="22"' 'PRETTY_NAME="Linux Mint 22"'
probe laeuft "Devuan 5"           'ID=devuan'    'ID_LIKE=debian' 'VERSION_ID="5"'  'PRETTY_NAME="Devuan GNU/Linux 5"'

echo
echo "Fremde Familien -- Abbruch, bevor etwas angefasst ist"
probe bricht_ab "Arch Linux"      'ID=arch'                       'PRETTY_NAME="Arch Linux"'
probe bricht_ab "Fedora 42"       'ID=fedora'    'VERSION_ID="42"' 'PRETTY_NAME="Fedora Linux 42"'
probe bricht_ab "Alpine 3.20"     'ID=alpine'    'VERSION_ID="3.20"' 'PRETTY_NAME="Alpine Linux v3.20"'
probe bricht_ab "openSUSE Leap"   'ID=opensuse-leap' 'ID_LIKE="suse opensuse"' 'VERSION_ID="16.1"' 'PRETTY_NAME="openSUSE Leap 16.1"'

echo
echo "Ohne /etc/os-release -- unbekannt, also Abbruch"
rm -f "$TMP/os-release"
if ! PXE_OS_RELEASE="$TMP/os-release" PXE_NUR_PRUEFUNG=1 bash "$INSTALL" >/dev/null 2>&1; then
  ok "fehlende os-release bricht ab"
else
  fail "fehlende os-release haette abbrechen muessen"
fi

echo
echo "Der Notausgang"
printf 'ID=arch\nPRETTY_NAME="Arch Linux"\n' > "$TMP/os-release"
ausgabe="$(PXE_OS_RELEASE="$TMP/os-release" PXE_NUR_PRUEFUNG=1 PXE_OS_EGAL=1 \
           bash "$INSTALL" 2>&1)"
if [[ $? -eq 0 ]] && grep -q 'eigene Rechnung' <<<"$ausgabe"; then
  ok "PXE_OS_EGAL=1 laesst durch und sagt es"
else
  fail "PXE_OS_EGAL=1 haette durchlassen muessen"
  sed 's/^/        /' <<<"$ausgabe"
fi

echo
if [[ $fails -eq 0 ]]; then
  echo "Die Systempruefung trifft auf allen 15 Faellen das Richtige."
else
  echo "$fails Faelle stimmen nicht."
  exit 1
fi

# ===========================================================================
# Die Uebergabe aus /opt/pxe-setup an den Projektordner.
#
# `sudo /opt/pxe-setup/install.sh` ist der eine Befehl, den die Oberflaeche
# zum Kopieren hinlegt und den docs/03 nennt. Dort liegt nur setup/, also
# fehlt webui/ -- ohne die Uebergabe braeche genau dieser Befehl ab.
# ===========================================================================
echo
echo "Aufruf aus der Kopie unter /opt"

PROJEKT="$(cd "$HIER/.." && pwd)"
KOPIE="$TMP/opt-pxe-setup"
mkdir -p "$KOPIE"
cp "$PROJEKT/setup/install.sh" "$KOPIE/"
printf '%s\n' "$PROJEKT" > "$KOPIE/projektpfad"
printf 'ID=debian\nVERSION_ID="13"\nPRETTY_NAME="Debian GNU/Linux 13"\n' > "$TMP/os-release"

ausgabe="$(PXE_OS_RELEASE="$TMP/os-release" PXE_NUR_PRUEFUNG=1 bash "$KOPIE/install.sh" 2>&1)"
if [[ $? -eq 0 ]] && grep -q "Uebergabe an den Projektordner" <<<"$ausgabe"; then
  ok "die Kopie uebergibt an das Original"
else
  fail "die Kopie haette uebergeben muessen"
  sed 's/^/        /' <<<"$ausgabe"
fi

# Wurde der Projektordner verschoben, muss das dastehen -- nicht "webui/
# fehlt", das schickt die Fehlersuche in die falsche Richtung.
printf '%s\n' "$TMP/gibt-es-nicht" > "$KOPIE/projektpfad"
ausgabe="$(PXE_OS_RELEASE="$TMP/os-release" PXE_NUR_PRUEFUNG=1 bash "$KOPIE/install.sh" 2>&1)"
if [[ $? -ne 0 ]] && grep -q "dort liegt kein Projektordner mehr" <<<"$ausgabe"; then
  ok "ein verschobener Projektordner wird benannt"
else
  fail "der verschobene Projektordner haette benannt werden muessen"
  sed 's/^/        /' <<<"$ausgabe"
fi

rm -f "$KOPIE/projektpfad"
ausgabe="$(PXE_OS_RELEASE="$TMP/os-release" PXE_NUR_PRUEFUNG=1 bash "$KOPIE/install.sh" 2>&1)"
if [[ $? -ne 0 ]] && grep -q "kein Projektordner (webui/ fehlt)" <<<"$ausgabe"; then
  ok "ohne Wegweiser bleibt die alte Ansage"
else
  fail "ohne Wegweiser haette die alte Ansage kommen muessen"
  sed 's/^/        /' <<<"$ausgabe"
fi

if [[ $fails -ne 0 ]]; then exit 1; fi

#!/usr/bin/env bash
# ===========================================================================
# Laedt die Betriebssystem-Dateien nach /srv/pxe/assets.
#
#   sudo ./sync-images.sh                 alles holen
#   sudo ./sync-images.sh debian gparted  nur diese beiden
#   sudo ./sync-images.sh --list          zeigt, was es gibt
#
# Bereits vollstaendig geladene Dateien werden uebersprungen, abgebrochene
# Downloads fortgesetzt. Das Skript kann also jederzeit erneut laufen.
#
# Die Ausgabenlisten unten sind leer ausgeliefert -- welche Ausgabe es
# gibt, sagt der Anbieter. Unter "Quellen" traegt "Pruefen" sie ein.
# Adressen koennen dagegen veralten: Meldet ein Download 404, hilft
# ebenfalls "Pruefen" -- es sucht die richtige Adresse und traegt sie nach.
# ===========================================================================
set -uo pipefail

ASSETS="${PXE_ASSETS:-/srv/pxe/assets}"

# --- Versionen und Quellen -------------------------------------------------
MINT_EDITION="cinnamon"        # oder xfce, mate

# --- Mehrversionige Systeme ------------------------------------------------
# Diese Listen sind mit Absicht LEER, und das ist der Kern des Entwurfs:
# Mitgeliefert wird die Auswahl der Distributionen, nicht die Nummer ihrer
# Ausgabe. Welche es gerade gibt, weiss der Anbieter besser als eine Datei
# von 2026.
#
# So laeuft es auf einem frisch aufgesetzten Server: Unter "Quellen" steht
# jede Quelle mit den Knoepfen "Pruefen" und "Neue Version" da, sonst
# nichts. "Pruefen" sieht beim Anbieter nach, traegt die neueste Ausgabe
# samt Adresse ein -- und erst danach gibt es etwas zu holen.
#
# Zwei Dinge fallen damit weg, die vorher unvermeidlich waren. Erstens
# altert nichts mehr still: Es steht keine Nummer da, die in zwei Jahren
# ins Leere zeigt und dann wie ein kaputter Server aussieht. Zweitens
# gehoert die Liste ab dem ersten Eintrag dem Betreiber -- quellen.env
# haelt nur fest, was von der Vorgabe abweicht, und die Vorgabe ist leer.
# Ein Update kann also nie ein System nachschieben, das niemand wollte.
#
# Mehrere Ausgaben duerfen nebeneinander liegen: solange Rechner mit einer
# aelteren Version im Betrieb sind, will man ihr Installationsmedium
# behalten. Jede bekommt ihr eigenes Verzeichnis und ihren eigenen
# Menuepunkt; der Katalog beschreibt nur das Muster (siehe "versionen_aus"
# in catalog.yaml).
#
# Gepflegt werden die Listen ueber die Weboberflaeche unter "Quellen".
# Von Hand geht auch: mehrere Ausgaben durch Leerzeichen trennen, neueste
# zuerst. Debian wird dabei ueber den Codenamen geholt, nicht ueber die
# Nummer -- "dists/trixie/" gibt es, "dists/13/" nicht.
DEBIAN_VERSIONS=""
DEBIAN_LIVE_VERSIONS=""        # Punktversion, siehe DEBIAN_LIVE_ISO_URL
SYSRESC_VERSIONS=""
GPARTED_VERSIONS=""
CLONEZILLA_VERSIONS=""
MEMTEST_VERSIONS=""
FEDORA_VERSIONS=""
LEAP_VERSIONS=""
UBUNTU_VERSIONS=""
ROCKY_VERSIONS=""

# In den Adressen der mehrversionigen Systeme steht {version} als
# Platzhalter -- eingesetzt wird sie beim Holen und beim Pruefen.
DEBIAN_URL="https://deb.debian.org/debian/dists/{version}/main/installer-amd64/current/images/netboot/debian-installer/amd64"
UBUNTU_ISO_URL="https://releases.ubuntu.com/{version}/ubuntu-{version}-live-server-amd64.iso"
# Der versionsbezogene Pfad und nicht "current-live/": Der wandert bei
# jeder Punktversion weiter, und eine aeltere Ausgabe waere dort sofort
# nicht mehr zu holen -- genau das, was die Ausgabenlisten verhindern
# sollen. Andere Oberflaeche gewuenscht? "xfce" durch gnome, kde, mate,
# cinnamon, lxde, lxqt oder standard ersetzen; die Adresse laesst sich
# auch im Browser unter Quellen aendern.
DEBIAN_LIVE_ISO_URL="https://cdimage.debian.org/cdimage/release/{version}-live/amd64/iso-hybrid/debian-live-{version}-amd64-xfce.iso"
# ShredOS traegt Ausgabe und Datum an zwei verschiedenen Stellen der
# Adresse -- ein einzelner Platzhalter deckt das nicht ab. Deshalb
# einversionig wie Mint: Bei einer neuen Ausgabe die ganze Adresse
# ersetzen, "Pruefen" meldet vorher, dass die alte 404 gibt.
SHREDOS_ISO_URL="https://github.com/PartialVolume/shredos.x86_64/releases/download/v2025.11_31_x86-64_0.42/shredos-2025.11_31_x86-64_v0.42_20260716_lite.iso"
MINT_MIRROR="https://mirrors.edge.kernel.org/linuxmint/stable"
FEDORA_URL="https://download.fedoraproject.org/pub/fedora/linux/releases/{version}/Everything/x86_64/os/images/pxeboot"
LEAP_URL="https://download.opensuse.org/distribution/leap/{version}/repo/oss/boot/x86_64/loader"
TUMBLEWEED_URL="https://download.opensuse.org/tumbleweed/repo/oss/boot/x86_64/loader"
ROCKY_BASE="https://dl.rockylinux.org/pub/rocky"
SYSRESC_ISO_URL="https://fastly-cdn.system-rescue.org/releases/{version}/systemrescue-{version}-amd64.iso"
GPARTED_ISO_URL="https://downloads.sourceforge.net/gparted/gparted-live-{version}-amd64.iso"
CLONEZILLA_ISO_URL="https://downloads.sourceforge.net/clonezilla/clonezilla-live-{version}-amd64.iso"
MEMTEST_ZIP_URL="https://www.memtest.org/download/v{version}/mt86plus_{version}.binaries.zip"

# --- Eigene Quellen --------------------------------------------------------
# Wird eine Adresse ungueltig (Ubuntu ersetzt bei jeder Punktversion den
# Dateinamen, Fedora raeumt alte Ausgaben in die Archive), laesst sie sich in
# der Weboberflaeche unter "Download-Quellen" ersetzen. Das landet in dieser
# Datei und wird hier -- nach den Vorgaben oben -- eingelesen, gewinnt also.
#
# Sie liegt bewusst ausserhalb des Projektordners: install.sh spiegelt mit
# "rsync --delete", alles im Projektordner waere beim naechsten Update weg.
QUELLEN_DATEI="${PXE_QUELLEN:-/var/lib/pxeweb/quellen.env}"
if [[ -r "$QUELLEN_DATEI" ]]; then
  # shellcheck disable=SC1090
  source "$QUELLEN_DATEI"
  EIGENE_QUELLEN="$QUELLEN_DATEI"
else
  EIGENE_QUELLEN=""
fi

COMPONENTS=(debian debian-live ubuntu mint fedora opensuse rocky systemrescue gparted clonezilla memtest shredos)

# --- Hilfsfunktionen -------------------------------------------------------
ok()   { printf '  \033[32m+\033[0m %s\n' "$*"; }
info() { printf '  \033[36m.\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m!\033[0m %s\n' "$*"; }
head1() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

FAILURES=()

# Laedt eine Datei, wenn sie noch nicht da ist. Abgebrochene Downloads
# werden fortgesetzt (--continue-at -), deshalb landet alles zuerst in
# einer .part-Datei und wird erst nach Erfolg umbenannt.
get() {
  local url="$1" dest="$2"
  if [[ -s "$dest" ]]; then
    ok "$(basename "$dest") liegt bereits vor"
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  info "lade $(basename "$dest") ..."
  if curl -fL --retry 3 --continue-at - --progress-bar -o "$dest.part" "$url"; then
    mv "$dest.part" "$dest"
    ok "$(basename "$dest") ($(du -h "$dest" | cut -f1))"
    return 0
  fi
  bad "Download fehlgeschlagen: $url"
  return 1
}

# Der Ordner eines Eintrags. Er heisst wie die Kennung im Katalog, und die
# ist bei mehrversionigen Eintraegen "<basis>-<ausgabe>", wobei in der
# Ausgabe alles ausser a-z und 0-9 zu "-" wird: aus 26.04 wird 26-04.
#
# Dieselbe Regel steht in webui/app.py (_mit_version). Zwei Stellen sind
# eine zu viel, aber die Alternative waere, dass dieses Skript den Katalog
# liest -- und das hiesse einen YAML-Leser in der Shell. Wer eine der
# beiden aendert, aendert beide; tests/test_katalog.py prueft, dass jeder
# Pfad im Katalog unter der Kennung liegt.
ablage() {
  local basis="$1" ausgabe="${2:-}"
  if [[ -n "$ausgabe" ]]; then
    local kurz
    kurz="$(printf '%s' "$ausgabe" | tr '[:upper:]' '[:lower:]'             | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
    printf '%s/%s-%s' "$ASSETS" "$basis" "$kurz"
  else
    printf '%s/%s' "$ASSETS" "$basis"
  fi
}

# Entpackt Pfade aus einem ISO. Ohne Pfadangabe wird alles entpackt.
# bsdtar liest ISO-Abbilder direkt -- kein mount, keine root-Rechte noetig.
unpack() {
  local iso="$1" dest="$2"; shift 2
  mkdir -p "$dest"
  info "entpacke $(basename "$iso") ..."
  if bsdtar -x -f "$iso" -C "$dest" "$@"; then
    ok "entpackt nach ${dest#"$ASSETS"/}"
    return 0
  fi
  bad "Entpacken fehlgeschlagen: $iso"
  return 1
}

fail() { FAILURES+=("$1"); }

# Setzt die Version in eine Adresse mit {version}-Platzhalter ein.
fuer_version() { printf '%s' "${1//\{version\}/$2}"; }

# Die Adresse einer einzelnen Ausgabe. Zuerst wird nach einer eigenen
# gesucht -- "FEDORA_URL_45" fuer Fedora 45 --, und nur wenn es keine gibt,
# wird die Version in das Muster eingesetzt.
#
# Warum ueberhaupt: Das Muster ist eine Wette darauf, dass die
# Verzeichnisstruktur des Distributors bleibt. Aendert Fedora eines Tages
# "Everything", sind mit einem Schlag alle Ausgaben tot -- auch die, die
# vorher liefen. Mit einer eigenen Adresse je Ausgabe bricht nur die neue.
#
# In einem Variablennamen darf nur stehen, was die Shell zulaesst: aus 16.1
# wird 16_1, aus 3.3.3-15 wird 3_3_3_15. Frueher wurde nur der Punkt
# ersetzt -- dann entstand CLONEZILLA_ISO_URL_3_3_3-15, und die indirekte
# Expansion darunter bricht damit ab ("invalid variable name"). Mit
# "set -e" nahm sie den ganzen Lauf mit, und "Holen" tat gar nichts mehr.
# Dieselbe Regel steht in webui/quellen.py (schluessel).
url_fuer() {
  local muster_name="$1" version="$2" muster="$3"
  local schluessel="${muster_name}_${version//[^A-Za-z0-9_]/_}"
  local eigene="${!schluessel-}"
  if [[ -n "$eigene" ]]; then
    printf '%s' "$eigene"
  else
    fuer_version "$muster" "$version"
  fi
}

# --- Komponenten -----------------------------------------------------------

sync_debian() {
  local v d url
  for v in $DEBIAN_VERSIONS; do
    head1 "Debian ${v} Installer"
    d="$(ablage debian "$v")"
    url="$(url_fuer DEBIAN_URL "$v" "$DEBIAN_URL")"
    get "$url/linux"     "$d/linux"      || fail "debian ${v}: linux"
    get "$url/initrd.gz" "$d/initrd.gz"  || fail "debian ${v}: initrd.gz"
  done
}

sync_debian-live() {
  local v d iso
  for v in $DEBIAN_LIVE_VERSIONS; do
    head1 "Debian Live ${v}"
    d="$(ablage debian-live "$v")"
    iso="$d/debian-live.iso"
    # Fertig ausgepackt? Dann ist nichts zu tun -- das Abbild ist danach
    # geloescht, ein erneuter Lauf wuerde sonst 3,6 GB noch einmal holen.
    if [[ -s "$d/live/vmlinuz" && -s "$d/live/filesystem.squashfs" ]]; then
      ok "Debian Live ${v} liegt bereits ausgepackt vor"
      continue
    fi
    if ! get "$(url_fuer DEBIAN_LIVE_ISO_URL "$v" "$DEBIAN_LIVE_ISO_URL")" "$iso"; then
      fail "debian-live ${v}: ISO"
      continue
    fi
    # Drei Dateien genuegen, wie bei GParted und Clonezilla: live-boot
    # haengt das Verzeichnis per NFS ein und sucht darin die Squashfs.
    if unpack "$iso" "$d" live/vmlinuz live/initrd.img live/filesystem.squashfs; then
      rm -f "$iso"
      ok "ausgepackt, Abbild wieder geloescht"
    else
      fail "debian-live ${v}: entpacken"
    fi
  done
}

sync_shredos() {
  head1 "ShredOS"
  local d iso
  d="$(ablage shredos)"
  iso="$d/shredos.iso"
  if [[ -s "$d/bzImage" ]]; then
    ok "ShredOS liegt bereits vor"
    return
  fi
  if ! get "$SHREDOS_ISO_URL" "$iso"; then
    fail "shredos: ISO"
    return
  fi
  # Eine einzige Datei, kein Initrd: ShredOS steckt vollstaendig im
  # Kernel. Damit ist es der einfachste Eintrag im ganzen Katalog.
  if unpack "$iso" "$d" boot/bzImage; then
    mv -f "$d/boot/bzImage" "$d/bzImage"
    rmdir "$d/boot" 2>/dev/null || true
    rm -f "$iso"
    ok "bzImage, Abbild wieder geloescht"
  else
    fail "shredos: entpacken"
  fi
}

sync_ubuntu() {
  local v
  for v in $UBUNTU_VERSIONS; do
    head1 "Ubuntu Server ${v} LTS"
    local d; d="$(ablage ubuntu-server "$v")"
    # Name ohne Punktversion: bei 26.04.1 bleibt der Katalogeintrag gueltig.
    local iso="$d/ubuntu-server-amd64.iso"
    if ! get "$(url_fuer UBUNTU_ISO_URL "$v" "$UBUNTU_ISO_URL")" "$iso"; then
      fail "ubuntu ${v}: ISO"
      continue
    fi
    # Der Live-Installer braucht Kernel und Initrd separat; das restliche
    # System holt er sich zur Laufzeit selbst aus dem ISO per HTTP.
    if unpack "$iso" "$d" casper/vmlinuz casper/initrd; then
      mv -f "$d/casper/vmlinuz" "$d/vmlinuz"
      mv -f "$d/casper/initrd"  "$d/initrd"
      rmdir "$d/casper" 2>/dev/null || true
    else
      fail "ubuntu ${v}: casper/vmlinuz + casper/initrd"
    fi
  done
}

sync_mint() {
  head1 "Linux Mint (${MINT_EDITION})"
  local d; d="$(ablage mint-cinnamon)"
  local iso="$d/linuxmint.iso"

  # Fertig ausgepackt? Dann ist nichts zu tun. Das Abbild selbst wird nach
  # dem Auspacken geloescht -- es gaebe sonst nichts zu vergleichen, und
  # ein erneuter Lauf wuerde die drei Gigabyte noch einmal holen.
  if [[ -s "$d/vmlinuz" && -s "$d/casper/filesystem.squashfs" ]]; then
    ok "Linux Mint liegt bereits ausgepackt vor"
    return
  fi

  # Mint bietet keinen Netz-Installer an -- gebootet wird das Live-ISO.
  # Die neueste stabile Ausgabe steht im Verzeichnisindex des Spiegels,
  # deshalb muss hier (wie bei Rocky) keine Version gepflegt werden.
  local version
  version="$(curl -fsSL --retry 2 "$MINT_MIRROR/" \
             | grep -oE '"[0-9]+\.[0-9]+/"' | tr -d '"/' | sort -V | tail -1)"
  if [[ -z "$version" ]]; then
    bad "Aktuelle Mint-Version nicht ermittelbar: $MINT_MIRROR"
    fail "mint: Version"
    return
  fi
  info "neueste Ausgabe: Linux Mint $version"

  # Ablage unter versionslosem Namen -- so bleibt catalog.yaml unberuehrt,
  # wenn spaeter eine neuere Ausgabe geholt wird.
  if ! get "$MINT_MIRROR/$version/linuxmint-$version-${MINT_EDITION}-64bit.iso" "$iso"; then
    fail "mint: ISO"
    return
  fi

  # Komplett auspacken: das Live-System wird spaeter per NFS aus diesem
  # Verzeichnis eingehaengt und braucht dafuer seinen ganzen Inhalt.
  # Kurzzeitig liegen Abbild und Inhalt gleichzeitig da -- rund 6 GB.
  if ! unpack "$iso" "$d"; then
    fail "mint: entpacken"
    return
  fi

  # Kernel und Initrd zusaetzlich unter festem Namen ablegen: im Abbild
  # heisst die Initrd je nach Ausgabe casper/initrd oder casper/initrd.lz,
  # in catalog.yaml soll aber ein fester Pfad stehen.
  cp -f "$d"/casper/vmlinuz  "$d/vmlinuz"
  cp -f "$d"/casper/initrd*  "$d/initrd"

  if [[ ! -s "$d/casper/filesystem.squashfs" ]]; then
    bad "In diesem Abbild fehlt casper/filesystem.squashfs."
    bad "Vermutlich stapelt diese Ausgabe mehrere Schichten -- dann braucht"
    bad "der Eintrag in catalog.yaml zusaetzlich layerfs-path=<wert>."
    bad "Der Wert steht im Abbild in boot/grub/grub.cfg."
    fail "mint: unerwarteter Aufbau"
    return
  fi

  # Das Abbild wird jetzt nicht mehr gebraucht -- alles liegt ausgepackt da.
  rm -f "$iso"
  ok "Abbild ausgepackt und geloescht ($(du -sh "$d" | cut -f1) belegt)"
}

sync_fedora() {
  local v url
  for v in $FEDORA_VERSIONS; do
    head1 "Fedora ${v}"
    url="$(url_fuer FEDORA_URL "$v" "$FEDORA_URL")"
    local d; d="$(ablage fedora-server "$v")"
    get "$url/vmlinuz"    "$d/vmlinuz"     || fail "fedora ${v}: vmlinuz"
    get "$url/initrd.img" "$d/initrd.img"  || fail "fedora ${v}: initrd.img"
  done
}

sync_opensuse() {
  # openSUSE braucht nur Kernel und Initrd; den Rest holt sich der
  # Installer (linuxrc) zur Laufzeit aus dem Online-Repository.
  local v url
  for v in $LEAP_VERSIONS; do
    head1 "openSUSE Leap ${v}"
    url="$(url_fuer LEAP_URL "$v" "$LEAP_URL")"
    local d; d="$(ablage opensuse-leap "$v")"
    get "$url/linux"  "$d/linux"  || fail "opensuse ${v}: Leap linux"
    get "$url/initrd" "$d/initrd" || fail "opensuse ${v}: Leap initrd"
  done

  head1 "openSUSE Tumbleweed"
  local t; t="$(ablage opensuse-tumbleweed)"
  get "$TUMBLEWEED_URL/linux"  "$t/linux"  || fail "opensuse: Tumbleweed linux"
  get "$TUMBLEWEED_URL/initrd" "$t/initrd" || fail "opensuse: Tumbleweed initrd"
}

sync_rocky() {
  # Wie bei Fedora: nur die pxeboot-Dateien, installiert wird aus dem Netz.
  local major
  for major in $ROCKY_VERSIONS; do
    head1 "Rocky Linux ${major}"
    local url="$(url_fuer ROCKY_BASE "$major" \
                   "$ROCKY_BASE/{version}/BaseOS/x86_64/os/images/pxeboot")"
    local d; d="$(ablage rocky "$major")"
    get "$url/vmlinuz"    "$d/vmlinuz"    || fail "rocky ${major}: vmlinuz"
    get "$url/initrd.img" "$d/initrd.img" || fail "rocky ${major}: initrd.img"
  done
}

sync_systemrescue() {
  local v d iso
  for v in $SYSRESC_VERSIONS; do
  head1 "SystemRescue ${v}"
  d="$(ablage systemrescue "$v")"
  iso="$d/systemrescue.iso"
  if ! get "$(url_fuer SYSRESC_ISO_URL "$v" "$SYSRESC_ISO_URL")" "$iso"; then
    fail "systemrescue ${v}: ISO"
    continue
  fi
  # Hier muss der komplette ISO-Inhalt entpackt werden: archiso laedt das
  # Wurzeldateisystem zur Laufzeit ueber HTTP aus diesem Verzeichnis.
  unpack "$iso" "$d" || fail "systemrescue ${v}: entpacken"
  done
}

sync_gparted() {
  local v d iso
  for v in $GPARTED_VERSIONS; do
    head1 "GParted Live ${v}"
    d="$(ablage gparted-live "$v")"
    iso="$d/gparted.iso"
    # Fertig ausgepackt? Dann ist nichts zu tun -- wie bei Debian Live.
    # Das Abbild selbst wird nach dem Auspacken geloescht; gebraucht
    # werden nur die drei Dateien darunter.
    if [[ -s "$d/live/vmlinuz" && -s "$d/live/filesystem.squashfs" ]]; then
      ok "GParted Live ${v} liegt bereits ausgepackt vor"
      # Aus der Zeit, als hier nicht aufgeraeumt wurde: Bis August 2026
      # blieb das Abbild neben den ausgepackten Dateien liegen und belegte
      # ein halbes Gigabyte, das niemand mehr brauchte.
      if [[ -f "$iso" ]]; then
        rm -f "$iso"
        ok "altes Abbild daneben entfernt"
      fi
      continue
    fi
    if ! get "$(url_fuer GPARTED_ISO_URL "$v" "$GPARTED_ISO_URL")" "$iso"; then
      fail "gparted ${v}: ISO"
      continue
    fi
    if unpack "$iso" "$d" live/vmlinuz live/initrd.img live/filesystem.squashfs; then
      rm -f "$iso"
      ok "ausgepackt, Abbild wieder geloescht"
    else
      fail "gparted ${v}: entpacken"
    fi
  done
}

sync_clonezilla() {
  local v d iso
  for v in $CLONEZILLA_VERSIONS; do
    head1 "Clonezilla Live ${v}"
    d="$(ablage clonezilla "$v")"
    iso="$d/clonezilla.iso"
    # Fertig ausgepackt? Dann ist nichts zu tun -- wie bei Debian Live.
    # Das Abbild selbst wird nach dem Auspacken geloescht; gebraucht
    # werden nur die drei Dateien darunter.
    if [[ -s "$d/live/vmlinuz" && -s "$d/live/filesystem.squashfs" ]]; then
      ok "Clonezilla Live ${v} liegt bereits ausgepackt vor"
      # Aus der Zeit, als hier nicht aufgeraeumt wurde: Bis August 2026
      # blieb das Abbild neben den ausgepackten Dateien liegen und belegte
      # ein halbes Gigabyte, das niemand mehr brauchte.
      if [[ -f "$iso" ]]; then
        rm -f "$iso"
        ok "altes Abbild daneben entfernt"
      fi
      continue
    fi
    if ! get "$(url_fuer CLONEZILLA_ISO_URL "$v" "$CLONEZILLA_ISO_URL")" "$iso"; then
      fail "clonezilla ${v}: ISO"
      continue
    fi
    if unpack "$iso" "$d" live/vmlinuz live/initrd.img live/filesystem.squashfs; then
      rm -f "$iso"
      ok "ausgepackt, Abbild wieder geloescht"
    else
      fail "clonezilla ${v}: entpacken"
    fi
  done
}

sync_memtest() {
  local v d bios efidir zip
  for v in $MEMTEST_VERSIONS; do
  head1 "Memtest86+ ${v}"
  # Zwei Katalogeintraege, zwei Ordner: memtest-bios bekommt die .bin,
  # memtest-efi die .efi. Frueher lagen beide in memtest/<ausgabe>/ und
  # teilten sich einen Ordner -- der gehoerte damit keinem von beiden ganz.
  bios="$(ablage memtest-bios "$v")"
  efidir="$(ablage memtest-efi "$v")"
  d="$bios"
  mkdir -p "$bios" "$efidir"
  zip="$d/memtest.zip"
  if ! get "$(url_fuer MEMTEST_ZIP_URL "$v" "$MEMTEST_ZIP_URL")" "$zip"; then
    fail "memtest ${v}: Archiv"
    continue
  fi
  local tmp
  tmp="$(mktemp -d)"
  if bsdtar -x -f "$zip" -C "$tmp"; then
    # Das Archiv enthaelt je eine 32- und eine 64-Bit-Fassung.
    local bin efi
    bin="$(find "$tmp" -name 'memtest64.bin' -o -name 'memtest.bin' | head -1)"
    efi="$(find "$tmp" -name 'memtest64.efi' -o -name 'memtest.efi' | head -1)"
    [[ -n "$bin" ]] && install -m 0644 "$bin" "$bios/memtest.bin" && ok "memtest.bin"
    [[ -n "$efi" ]] && install -m 0644 "$efi" "$efidir/memtest.efi" && ok "memtest.efi"
    [[ -z "$bin" || -z "$efi" ]] && fail "memtest: Dateien im Archiv nicht gefunden"
  else
    fail "memtest: entpacken"
  fi
  rm -rf "$tmp"
  done
}

# --- Ablauf ----------------------------------------------------------------

if [[ "${1:-}" == "--list" ]]; then
  echo "Verfuegbare Komponenten:"
  printf '  %s\n' "${COMPONENTS[@]}"
  exit 0
fi

command -v bsdtar >/dev/null || {
  echo "bsdtar fehlt. Nachinstallieren mit: sudo apt install libarchive-tools" >&2
  exit 1
}

selected=("$@")
[[ ${#selected[@]} -eq 0 ]] && selected=("${COMPONENTS[@]}")

mkdir -p "$ASSETS"

if [[ -n "$EIGENE_QUELLEN" ]]; then
  info "Eigene Quellen aus $EIGENE_QUELLEN uebernommen"
fi

# "debian" holt alle eingetragenen Ausgaben, "debian:trixie" nur diese
# eine. Gebraucht wird das, sobald mehrere Ausgaben nebeneinander stehen:
# Wer eine neue erproben will, will nicht zugleich die beiden alten
# nachgeladen bekommen -- und wer eine alte behaelt, will sie nicht
# angefasst wissen.
#
# Eingesetzt wird die Ausgabe, indem die Versionsliste fuer diesen einen
# Lauf ueberschrieben wird. Die Funktionen lesen sie ohnehin; sie merken
# von der Einschraenkung nichts.
for eintrag in "${selected[@]}"; do
  name="${eintrag%%:*}"
  nur="${eintrag#*:}"
  [[ "$nur" == "$eintrag" ]] && nur=""

  if [[ " ${COMPONENTS[*]} " != *" $name "* ]]; then
    bad "Unbekannte Komponente: $name  (--list zeigt alle)"
    continue
  fi

  # Vollstaendig hingeschrieben und nicht aus dem Namen abgeleitet: Die
  # Listen heissen nicht wie ihre Komponente (opensuse liest
  # LEAP_VERSIONS, systemrescue liest SYSRESC_VERSIONS), und eine
  # Ableitung mit Ausnahmen versteht spaeter jemand falsch. Wer eine
  # Komponente hinzufuegt, traegt sie hier ein -- oder sie laesst sich
  # eben nicht auf eine Ausgabe einschraenken, und das sagt sie dann.
  case "$name" in
    debian)       liste_name="DEBIAN_VERSIONS" ;;
    debian-live)  liste_name="DEBIAN_LIVE_VERSIONS" ;;
    ubuntu)       liste_name="UBUNTU_VERSIONS" ;;
    fedora)       liste_name="FEDORA_VERSIONS" ;;
    opensuse)     liste_name="LEAP_VERSIONS" ;;
    rocky)        liste_name="ROCKY_VERSIONS" ;;
    systemrescue) liste_name="SYSRESC_VERSIONS" ;;
    gparted)      liste_name="GPARTED_VERSIONS" ;;
    clonezilla)   liste_name="CLONEZILLA_VERSIONS" ;;
    memtest)      liste_name="MEMTEST_VERSIONS" ;;
    *)            liste_name="" ;;
  esac

  if [[ -n "$nur" ]]; then
    if [[ -z "$liste_name" ]]; then
      bad "$name hat nur eine Ausgabe -- \":$nur\" geht hier nicht"
      continue
    fi
    printf -v "$liste_name" '%s' "$nur"
    info "nur Ausgabe $nur"
  fi

  # Steht keine Ausgabe in der Liste, holt die Funktion nichts -- ihre
  # Schleife laeuft null Mal. Das ist richtig so, sieht aber aus wie ein
  # Fehlschlag, wenn niemand es sagt: Seit August 2026 sind die Listen
  # leer ausgeliefert, und ein frisch aufgesetzter Server landet mit
  # "sudo ./sync-images.sh gparted" genau hier.
  if [[ -n "$liste_name" && -z "${!liste_name// }" ]]; then
    head1 "$name"
    info "keine Ausgabe eingetragen -- nichts zu holen"
    info "unter \"Quellen\" traegt \"Pruefen\" die neueste ein"
    continue
  fi

  "sync_$name"
done

# Ausgeliefert wird von nginx als Benutzer www-data -- Lesezugriff reicht.
chmod -R a+rX "$ASSETS" 2>/dev/null || true

echo
if [[ ${#FAILURES[@]} -eq 0 ]]; then
  echo "Alles vorhanden. Belegt: $(du -sh "$ASSETS" | cut -f1)"
  echo "Die Eintraege erscheinen jetzt im Bootmenue."
else
  echo "Fertig, aber mit Problemen:"
  printf '  - %s\n' "${FAILURES[@]}"
  echo
  echo "Meist ist die Adresse veraltet. Am schnellsten geht es ueber die"
  echo "Weboberflaeche: \"Download-Quellen\" -- dort laesst sich die neue"
  echo "Adresse einfuegen und vorher pruefen. Alternativ oben im Skript die"
  echo "Versionsnummer anpassen. Zeigt der Katalog danach auf einen anderen"
  echo "Pfad, in catalog.yaml nachziehen."
  exit 1
fi

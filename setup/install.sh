#!/usr/bin/env bash
# ===========================================================================
# Installiert MARLEI Boot auf Debian, Ubuntu oder Raspberry Pi OS.
#
# Aufruf in der VM, als root:
#     sudo ./setup/install.sh
#
# Netzwerkkarte/IP werden automatisch erkannt. Ueberschreiben geht so:
#     sudo PXE_IFACE=enp0s3 PXE_IP=192.168.178.30 ./setup/install.sh
#
# Das Skript ist wiederholbar: ein zweiter Aufruf aktualisiert nur.
# ===========================================================================
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APP_DIR=/opt/pxeweb
SETUP_DIR=/opt/pxe-setup
DATA_DIR=/var/lib/pxeweb
PXE_ROOT=/srv/pxe

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[X]\033[0m %s\n' "$*" >&2; exit 1; }


# Dieses Skript braucht den ganzen Projektordner -- webui/, setup/files/,
# catalog.yaml. Die nach /opt/pxe-setup gespiegelte Kopie hat nur setup/.
#
# Trotzdem soll `sudo /opt/pxe-setup/install.sh` gehen: Das ist der eine
# Befehl, den die Oberflaeche zum Kopieren hinlegt, wenn die Adresse des
# Hosts nachzuziehen ist -- und niemand soll sich merken muessen, wohin er
# das Projekt seinerzeit geklont hat. Den Weg zurueck kennt die Kopie: Jeder
# Lauf legt "projektpfad" daneben.
#
# Uebergeben wird an das Original, statt von dort zu kopieren. Ein Skript,
# das sich selbst aus einer halben Kopie zusammensucht, waere die Art von
# Findigkeit, die man drei Monate spaeter nicht mehr versteht.
if [[ ! -d "$SRC_DIR/webui" ]]; then
  ZURUECK="$SRC_DIR/setup/projektpfad"
  [[ -r "$ZURUECK" ]] || ZURUECK="$(dirname "${BASH_SOURCE[0]}")/projektpfad"
  if [[ -r "$ZURUECK" ]]; then
    PROJEKT="$(head -n1 "$ZURUECK")"
    if [[ -d "$PROJEKT/webui" && -x "$PROJEKT/setup/install.sh" ]]; then
      log "Uebergabe an den Projektordner: $PROJEKT"
      exec "$PROJEKT/setup/install.sh" "$@"
    fi
    die "In $ZURUECK steht \"$PROJEKT\" -- dort liegt kein Projektordner mehr.
    Wurde er verschoben oder geloescht? Dann von dort aufrufen:
        sudo <projekt>/setup/install.sh"
  fi
  die "$SRC_DIR ist kein Projektordner (webui/ fehlt).
    Aufrufen aus dem geklonten Projekt:  sudo <projekt>/setup/install.sh"
fi

# --------------------------------------------------------------------------
# Laeuft das hier ueberhaupt auf einem System, das wir kennen?
#
# Dieses Skript kennt eine Familie: Debian und was davon abstammt. Es
# benutzt apt-get, systemd und die Paketnamen dieser Familie. Auf Arch,
# Alpine oder Fedora laeuft es an und scheitert auf halber Strecke -- mit
# Meldungen, die nach einem Fehler dieses Servers aussehen statt nach einem
# System, fuer das er nie gedacht war. Deshalb hier, als Erstes, bevor
# irgendetwas angefasst ist.
#
# Raspberry Pi OS meldet in der 64-Bit-Fassung selbst ID=debian und faellt
# damit ohnehin in den Debian-Zweig; die 32-Bit-Fassung heisst raspbian.
#
# Der Ausweg ist Absicht: Wer weiss, was er tut, soll nicht an unserem
# Skript haengenbleiben. Er bekommt nur keine Zusage mehr.
OS_ID=""; OS_LIKE=""; OS_VER=""; OS_NAME="unbekannt"
OS_RELEASE="${PXE_OS_RELEASE:-/etc/os-release}"
if [[ -r "$OS_RELEASE" ]]; then
  # shellcheck source=/dev/null
  . "$OS_RELEASE"
  OS_ID="${ID:-}"; OS_LIKE="${ID_LIKE:-}"; OS_VER="${VERSION_ID:-}"
  OS_NAME="${PRETTY_NAME:-${NAME:-unbekannt}}"
fi

# Welcher Stand gilt als geprueft. Darunter laeuft es vermutlich auch,
# aber wir sagen es nicht zu.
case "$OS_ID" in
  debian|raspbian) BODEN=12   ;;
  ubuntu)          BODEN=22   ;;
  *)               BODEN=""   ;;
esac

# ID_LIKE deckt die Abkoemmlinge ab, die selbst keinen eigenen Boden haben:
# Linux Mint meldet ID_LIKE=ubuntu, Devuan und Pop!_OS debian. Sie laufen
# ohne Versionspruefung durch -- bekannte Familie, ungepruefter Stand.
if [[ -n "$BODEN" || "$OS_LIKE" == *debian* || "$OS_LIKE" == *ubuntu* ]]; then
  : # bekannte Familie
elif [[ "${PXE_OS_EGAL:-0}" == "1" ]]; then
  warn "$OS_NAME ist kein System, auf dem dieser Server geprueft ist."
  warn "PXE_OS_EGAL=1 ist gesetzt -- es geht weiter, auf eigene Rechnung."
else
  die "Dieses Skript ist fuer Debian, Ubuntu und Raspberry Pi OS gebaut.
    Gefunden: $OS_NAME
    Es benutzt apt-get, systemd und die Paketnamen dieser Familie -- auf
    einem anderen System scheitert es auf halber Strecke.
    Trotzdem versuchen:  sudo PXE_OS_EGAL=1 $0"
fi

# Zu alt heisst nicht kaputt, nur ungeprueft -- also warnen und weiter.
if [[ -n "$BODEN" && -n "$OS_VER" ]]; then
  if [[ "${OS_VER%%.*}" -lt "$BODEN" ]]; then
    warn "$OS_NAME ist aelter als der gepruefte Stand (ab $BODEN)."
    warn "Es laeuft vermutlich, geprueft ist es nicht."
  fi
fi
echo "    System        : $OS_NAME"
[[ "${PXE_NUR_PRUEFUNG:-0}" == "1" ]] && exit 0

[[ $EUID -eq 0 ]] || die "Bitte mit sudo starten."

# --------------------------------------------------------------------------
log "Netzwerk ermitteln"
# --------------------------------------------------------------------------
IFACE="${PXE_IFACE:-$(ip -4 route show default | awk '{print $5; exit}')}"
[[ -n "$IFACE" ]] || die "Keine Netzwerkkarte mit Standardroute gefunden. PXE_IFACE=... setzen."

SERVER_IP="${PXE_IP:-$(ip -4 -o addr show dev "$IFACE" | awk '{split($4,a,"/"); print a[1]; exit}')}"
[[ -n "$SERVER_IP" ]] || die "Keine IPv4-Adresse auf $IFACE gefunden. PXE_IP=... setzen."

echo "    Netzwerkkarte : $IFACE"
echo "    Server-IP     : $SERVER_IP"

case "$SERVER_IP" in
  10.0.2.*)
    warn "Diese IP gehoert zum VirtualBox-NAT-Netz."
    warn "Im NAT-Modus erreichen PXE-Broadcasts das LAN nicht."
    warn "In den VM-Einstellungen auf 'Netzwerkbruecke' umstellen!"
    read -r -p "    Trotzdem fortfahren? [j/N] " answer
    [[ "$answer" =~ ^[jJyY]$ ]] || exit 1
    ;;
esac

if ! ip -4 -o addr show dev "$IFACE" | grep -q "$SERVER_IP"; then
  warn "$SERVER_IP liegt nicht auf $IFACE -- bitte pruefen."
fi

# Woher diese Adresse stammt. Sie wird gleich an vier Stellen festgeschrieben
# -- dnsmasq, nginx, pxeweb.env, NFS-Export und damit in jedes generierte
# Boot-Skript. Die fuenfte, die Adresse des Hosts selbst, fasst dieser
# Server seit dem 27.08.2026 nicht mehr an: Sie gehoert dem Betreiber.
#
# Kommt sie aus DHCP, stimmt das alles genau so lange, wie der Router
# dieselbe vergibt. Mit einer Reservierung ist das dauerhaft der Fall, ohne
# eine nicht -- danach zeigen die Boot-Skripte ins Leere, und der bootende
# Rechner haengt, ohne dass eine Meldung das erklaeren wuerde. Die
# Oberflaeche merkt es und sagt es auf Server Health.
#
# Der Kernel weiss es selbst: Bei einer bezogenen Adresse steht "dynamic" in
# der Zeile, bei einer eingetragenen nicht.
#
# Anders als beim NAT-Netz oben wird hier nicht gefragt, sondern nur
# hingewiesen. Mit einer Adresse vom Router laeuft der Server ohne Weiteres
# -- es kommt nur darauf an, ob sie ihm reserviert ist. Ein Abbruch waere
# die falsche Antwort darauf. Eine Rueckfrage haenge ausserdem bei jedem
# Update erneut und in einem Lauf ohne Tastatur ueberhaupt.
#
# WICHTIG AN DER FORMULIERUNG: Der Kernel kann eine Reservierung nicht von
# einer gewoehnlichen Lease unterscheiden -- beide stehen als "dynamic" da.
# Der Hinweis darf deshalb nicht behaupten, hier sei etwas falsch: Eine
# Reservierung ist einer der beiden Wege, die dieser Server ausdruecklich
# vorsieht. Er fragt, statt anzuklagen. Stuende hier eine Warnung, bekaeme
# sie jeder mit sauberem Aufbau zu lesen -- und schriebe uns.
DHCP_ADRESSE=0
if ip -4 -o addr show dev "$IFACE" | grep -F "$SERVER_IP/" | grep -qw dynamic; then
  DHCP_ADRESSE=1
  echo "    Adresse       : vom Router vergeben"
  echo "                    Ist sie diesem Server reserviert, ist alles in Ordnung."
  echo "                    Ist sie es nicht, siehe den Hinweis am Ende."
fi

# --------------------------------------------------------------------------
log "Pakete installieren"
# --------------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  dnsmasq nginx curl ca-certificates \
  python3 python3-venv python3-pip \
  libarchive-tools rsync \
  nfs-kernel-server samba

# --------------------------------------------------------------------------
log "Verzeichnisse und Dienstkonto anlegen"
# --------------------------------------------------------------------------
id pxeweb &>/dev/null || useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin pxeweb

# Damit die Weboberflaeche das Journal der Dienste anzeigen kann. Ohne diese
# Gruppe sieht ein unprivilegiertes Konto nur seine eigenen Meldungen -- und
# zwar ohne Fehler, es kaeme schlicht nichts an. Rein lesend; die Oberflaeche
# gibt ausserdem nur die vier Dienste dieses Servers preis (webui/journal.py).
if getent group systemd-journal >/dev/null; then
  usermod -aG systemd-journal pxeweb
fi
mkdir -p "$APP_DIR" "$SETUP_DIR" "$DATA_DIR" "$PXE_ROOT/tftp" "$PXE_ROOT/assets"
chown -R pxeweb:pxeweb "$DATA_DIR"

# Hierhin legt die Weboberflaeche selbst hochgeladene ISO-Abbilder. Es ist
# das einzige Verzeichnis unterhalb von /srv/pxe, in das der Dienst
# schreiben darf (siehe ReadWritePaths in pxeweb.service).
mkdir -p "$PXE_ROOT/assets/upload"

# Die gesamte Abbild-Ablage gehoert dem Dienstkonto. Grund: die
# Weboberflaeche kann sync-images.sh anstossen, und das legt dort
# Verzeichnisse an und raeumt ausgepackte Abbilder wieder weg. Root braucht
# das Skript dafuer nicht -- nur einen Pfad, der ihm gehoert. Ausgeliefert
# wird weiterhin nur lesend: nginx als www-data, NFS als "ro".
chown -R pxeweb:pxeweb "$PXE_ROOT/assets"

# --------------------------------------------------------------------------
# Werkzeuge liegen seit dem Umbau unter ihrer Ausgabe
# --------------------------------------------------------------------------
# Frueher lagen GParted, Clonezilla, SystemRescue und Memtest direkt unter
# ihrem Namen -- es gab ja nur eine Ausgabe. Jetzt koennen zwei
# nebeneinander liegen, und dafuer traegt jede ihr eigenes Verzeichnis.
#
# Ohne diese Wanderung stuenden vorhandene Dateien nach dem Update am
# falschen Ort: Die Oberflaeche meldete "fehlt", und mehrere Gigabyte
# muessten erneut geladen werden, obwohl sie da sind. Verschoben wird nur,
# was eindeutig ist -- liegt schon ein Ausgabenverzeichnis daneben, bleibt
# alles unberuehrt.
wandere_werkzeug() {
  local name="$1" version="${2-}" alt="$PXE_ROOT/assets/$1"
  # Aus "13.02 12.01" wird 13.02: Die Wanderung gilt dem, was da liegt, und
  # das ist die Ausgabe, die bisher als einzige geholt wurde.
  version="${version%% *}"
  [[ -n "$version" && -d "$alt" && ! -d "$alt/$version" ]] || return 0
  # Gibt es ueberhaupt etwas zu verschieben?
  local inhalt
  inhalt="$(find "$alt" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null || true)"
  [[ -n "$inhalt" ]] || return 0

  log "  $name: Dateien nach $version/ verschieben"
  local ziel="$alt/.wanderung"
  mkdir -p "$ziel"
  find "$alt" -mindepth 1 -maxdepth 1 ! -name ".wanderung" \
       -exec mv -t "$ziel" {} +
  mv "$ziel" "$alt/$version"
  chown -R pxeweb:pxeweb "$alt"
}

# Gelesen wird das Skript aus dem Projektordner, nicht das installierte:
# $SETUP_DIR traegt an dieser Stelle noch den alten Stand -- kopiert wird
# erst weiter unten. Und gerade der alte kennt die Versionslisten nicht,
# die hier gebraucht werden.
WERKZEUG_LISTEN='^(SYSRESC|GPARTED|CLONEZILLA|MEMTEST)_VERSIONS='
if [[ -r "$SRC_DIR/setup/sync-images.sh" ]]; then
  # Die Vorgaben stehen im Skript, eigene Angaben in der Datei daneben --
  # dieselbe Reihenfolge wie beim Abgleich selbst.
  # shellcheck disable=SC1090
  source <(grep -E "$WERKZEUG_LISTEN" "$SRC_DIR/setup/sync-images.sh" || true)
  if [[ -r "$DATA_DIR/quellen.env" ]]; then
    # shellcheck disable=SC1091
    source <(grep -E "$WERKZEUG_LISTEN" "$DATA_DIR/quellen.env" || true)
  fi
  log "Werkzeuge auf Ausgabenverzeichnisse umstellen"
  # "${VAR-}" und nicht "$VAR": Fehlt eine Liste, wird dieses Werkzeug
  # uebersprungen. Ohne den Bindestrich beendet "set -u" die ganze
  # Installation -- und zwar bevor die Anwendung kopiert ist, sodass vom
  # Update nichts ankommt.
  #
  # Aus demselben Grund darf auch ein Fehler beim Verschieben die
  # Installation nicht anhalten: Das hier ist eine einmalige Bequemlichkeit,
  # damit niemand Gigabytes neu laden muss. Geht sie schief, meldet die
  # Oberflaeche "fehlt" und der Abgleich holt die Dateien -- laestig, aber
  # kein Grund, das Update stehen zu lassen.
  for werkzeug in "systemrescue:${SYSRESC_VERSIONS-}" "gparted:${GPARTED_VERSIONS-}" \
                  "clonezilla:${CLONEZILLA_VERSIONS-}" "memtest:${MEMTEST_VERSIONS-}"; do
    wandere_werkzeug "${werkzeug%%:*}" "${werkzeug#*:}" \
      || warn "${werkzeug%%:*}: Dateien blieben liegen -- der Abgleich holt sie neu"
  done
fi

# --------------------------------------------------------------------------
log "Anwendung kopieren"
# --------------------------------------------------------------------------
rsync -a --delete \
      --exclude '__pycache__' --exclude '*.db' --exclude 'venv' \
      "$SRC_DIR/webui/" "$APP_DIR/"
rsync -a "$SRC_DIR/setup/" "$SETUP_DIR/"
chmod +x "$SETUP_DIR"/*.sh
# Woher dieser Lauf kam. Die Kopie unter /opt hat kein webui/ und koennte
# sonst nicht laufen; mit dieser Datei uebergibt sie an das Original
# zurueck. Siehe die Uebergabe ganz oben.
printf '%s\n' "$SRC_DIR" > "$SETUP_DIR/projektpfad"

# Welcher Stand hier eingebaut wurde. Die Anwendung liegt als rsync-Kopie in
# /opt/pxeweb, ohne .git -- sie kann also nicht selbst nachsehen. Der Stempel
# muss NACH dem rsync entstehen: der laeuft mit --delete und raeumt die Datei
# sonst bei jedem Lauf wieder weg.
#
# "safe.directory": Dieses Skript laeuft als root, der Projektordner gehoert
# einem normalen Benutzer. Ohne die Angabe verweigert Git die Auskunft
# ("detected dubious ownership") -- und das faellt erst hier auf, nicht beim
# Klonen.
git_im_projekt() {
  git -C "$SRC_DIR" -c safe.directory="$SRC_DIR" "$@" 2>/dev/null
}

if git_im_projekt rev-parse --git-dir >/dev/null; then
  # --tags   nimmt auch unannotierte Tags
  # --always faellt auf den Kurz-Hash zurueck, solange es keinen Tag gibt
  # --dirty  haengt "-dirty" an, wenn im Projektordner Ungespeichertes liegt
  STAND="$(git_im_projekt describe --tags --always --dirty || echo unbekannt)"
  COMMIT="$(git_im_projekt rev-parse --short HEAD || true)"
  ZWEIG="$(git_im_projekt rev-parse --abbrev-ref HEAD || true)"
else
  # Kein Git -- etwa ein entpacktes Archiv. Kein Fehler, nur weniger Auskunft.
  STAND="ohne Git"
  COMMIT=""
  ZWEIG=""
fi

cat > "$APP_DIR/VERSION" <<STAND_EOF
# Von install.sh geschrieben. Aenderungen gehen beim naechsten Lauf verloren.
stand=$STAND
commit=$COMMIT
zweig=$ZWEIG
installiert=$(date '+%Y-%m-%d %H:%M')
STAND_EOF
chmod 0644 "$APP_DIR/VERSION"
echo "    Stand: $STAND"

if [[ ! -d "$APP_DIR/venv" ]]; then
  python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# --------------------------------------------------------------------------
log "Konfiguration schreiben"
# --------------------------------------------------------------------------

# dnsmasq: unsere Datei ergaenzt die Paket-Konfiguration ueber das
# Include-Verzeichnis, die Originaldatei bleibt unangetastet.
sed -e "s|@@INTERFACE@@|$IFACE|g" \
    -e "s|@@SERVER_IP@@|$SERVER_IP|g" \
    -e "s|@@SUBNET@@|$SERVER_IP|g" \
    "$SRC_DIR/setup/files/dnsmasq-pxe.conf" > /etc/dnsmasq.d/pxe.conf

# nginx: die mitgelieferte Standardseite wuerde sonst Port 80 belegen.
sed -e "s|@@SERVER_IP@@|$SERVER_IP|g" \
    "$SRC_DIR/setup/files/nginx-pxe.conf" > /etc/nginx/sites-available/pxe
ln -sf /etc/nginx/sites-available/pxe /etc/nginx/sites-enabled/pxe
rm -f /etc/nginx/sites-enabled/default

# Umgebung der Web-App. Eine vorhandene Datei wird nur in der Basis-URL
# angepasst, damit eigene Aenderungen (Timeout usw.) erhalten bleiben.
if [[ -f /etc/pxeweb.env ]]; then
  sed -i "s|^PXE_BASE_URL=.*|PXE_BASE_URL=http://$SERVER_IP|" /etc/pxeweb.env
else
  sed -e "s|^PXE_BASE_URL=.*|PXE_BASE_URL=http://$SERVER_IP|" \
      "$SRC_DIR/setup/files/pxeweb.env.example" > /etc/pxeweb.env
fi

# Einzelnen Wert in /etc/pxeweb.env setzen: vorhandene Zeile ersetzen, sonst
# mit einer kurzen Erklaerung anhaengen. Dadurch bleiben eigene Aenderungen an
# allen anderen Werten bei einem erneuten Lauf unangetastet.
env_setzen() {
  local schluessel="$1" wert="$2" erklaerung="${3:-}"
  if grep -q "^$schluessel=" /etc/pxeweb.env; then
    sed -i "s|^$schluessel=.*|$schluessel=$wert|" /etc/pxeweb.env
  else
    {
      echo ""
      if [[ -n "$erklaerung" ]]; then echo "# $erklaerung"; fi
      echo "$schluessel=$wert"
    } >> /etc/pxeweb.env
  fi
}

# Was die Vorlage kennt und die Datei nicht, wird nachgetragen -- mit dem
# Wert und den Kommentarzeilen aus der Vorlage.
#
# **Der dritte Fall.** Oben stehen zwei: Datei fehlt (aus der Vorlage
# erzeugen) und Datei ist da (nur die Basis-URL anfassen, eigene
# Aenderungen bleiben). Dazwischen fehlte einer: Ein Name, den die Vorlage
# kennt und die Datei nicht, ist keine eigene Aenderung, sondern eine
# Luecke. Ueberschrieben wird dabei nichts -- angehaengt wird nur, was
# fehlt.
#
# Aufgefallen am 04.09.2026 auf der produktiven Maschine: Dort fehlten
# PXE_WOL_PORTS und PXE_QUELLENWACHT, weil die Datei aelter ist als die
# beiden Werte. Die neue Karte "Die Einrichtung ist aelter als der Code"
# hat es gemeldet und auf install.sh verwiesen -- und install.sh haette es
# nicht behoben. Ein Befund, der einen Weg nennt, der ihn nicht behebt,
# ist eine Sackgasse.
nachtragen_aus_vorlage() {
  local vorlage="$SRC_DIR/setup/files/pxeweb.env.example"
  local schluessel zeile nachgetragen=0 kommentar=""

  [[ -r "$vorlage" ]] || return 0

  while IFS= read -r zeile; do
    # Kommentarbloecke sammeln: Sie gehoeren zu dem Wert, der ihnen folgt.
    if [[ "$zeile" =~ ^# ]]; then
      kommentar+="${zeile}"$'
'
      continue
    fi
    if [[ -z "$zeile" ]]; then
      kommentar=""
      continue
    fi
    if [[ "$zeile" =~ ^([A-Z][A-Z0-9_]*)= ]]; then
      schluessel="${BASH_REMATCH[1]}"
      if ! grep -q "^$schluessel=" /etc/pxeweb.env; then
        {
          echo ""
          [[ -n "$kommentar" ]] && printf '%s' "$kommentar"
          echo "$zeile"
        } >> /etc/pxeweb.env
        echo "    nachgetragen: $schluessel"
        nachgetragen=$((nachgetragen + 1))
      fi
    fi
    kommentar=""
  done < "$vorlage"

  if [[ $nachgetragen -gt 0 ]]; then
    ok "$nachgetragen Wert(e) aus der Vorlage nachgetragen"
  fi
}

nachtragen_aus_vorlage

install -m 0644 "$SRC_DIR/setup/files/pxeweb.service" /etc/systemd/system/pxeweb.service

# --------------------------------------------------------------------------
log "NFS-Export einrichten"
# --------------------------------------------------------------------------
# Wozu NFS, wo doch alles ueber HTTP laeuft? Ein Live-System wie Ubuntu
# Desktop laedt sein komplettes Abbild in eine RAM-Disk, bevor es startet --
# bei 6 GB Abbild scheitert das auf einem Rechner mit 8 GB Speicher. Ueber
# NFS wird das Dateisystem stattdessen gestreamt: der bootende Rechner liest
# nur, was er gerade braucht. Exportiert wird ausschliesslich lesend und nur
# ins eigene Subnetz.

CIDR="$(ip -4 -o addr show dev "$IFACE" | awk '{print $4; exit}')"
PREFIX="${CIDR#*/}"
IFS=. read -r o1 o2 o3 o4 <<< "${CIDR%/*}"
ipnum=$(( (o1 << 24) + (o2 << 16) + (o3 << 8) + o4 ))
maske=$(( (0xFFFFFFFF << (32 - PREFIX)) & 0xFFFFFFFF ))
netz=$(( ipnum & maske ))
SUBNET="$(( (netz >> 24) & 255 )).$(( (netz >> 16) & 255 )).$(( (netz >> 8) & 255 )).$(( netz & 255 ))/$PREFIX"
echo "    Freigegeben fuer: $SUBNET (nur lesend)"

# Aus derselben Rechnung faellt die Rundrufadresse ab (alle Hostbits auf 1).
# Sie wird weiter unten fuer Wake-on-LAN gebraucht.
bcast=$(( netz | (~maske & 0xFFFFFFFF) ))
BROADCAST="$(( (bcast >> 24) & 255 )).$(( (bcast >> 16) & 255 )).$(( (bcast >> 8) & 255 )).$(( bcast & 255 ))"

mkdir -p /etc/exports.d
cat > /etc/exports.d/pxe.exports <<EXPORTS
# Von install.sh erzeugt -- Aenderungen gehen beim naechsten Lauf verloren.
$PXE_ROOT/assets $SUBNET(ro,sync,no_subtree_check,insecure)
EXPORTS

# Der Dienst kann fehlen, wenn das Paket nicht installierbar war. Dann soll
# die Installation nicht scheitern -- ohne NFS laeuft alles wie vorher,
# nur eben mit der Groessengrenze durch den Arbeitsspeicher des Clients.
NFS_ROOT_PFAD=""
if systemctl cat nfs-server.service >/dev/null 2>&1; then
  systemctl enable --now nfs-server >/dev/null
  # NFSv3-Clients -- und die Initrd eines Live-Systems ist meist einer --
  # brauchen zusaetzlich den Portmapper.
  systemctl enable --now rpcbind >/dev/null 2>&1 || true
  exportfs -ra
  NFS_ROOT_PFAD="$PXE_ROOT/assets"
  echo "    NFS laeuft."
else
  warn "nfs-server ist nicht verfuegbar -- Paket nfs-kernel-server fehlt?"
  warn "Ohne NFS muessen Live-Abbilder in den Arbeitsspeicher des Clients passen."
fi

# Die Zeile fehlt in Konfigurationsdateien, die vor dem NFS-Umbau entstanden
# sind. Sie wird bei jedem Lauf auf den tatsaechlichen Zustand gesetzt.
env_setzen PXE_NFS_ROOT "$NFS_ROOT_PFAD" "NFS-Export fuer grosse Live-Abbilder (siehe Hilfe, Systeme)."

# --------------------------------------------------------------------------
log "SMB-Freigabe fuer Windows-Installationen einrichten"
# --------------------------------------------------------------------------
# Ein Windows-Setup laedt seine Quelldateien -- vor allem die mehrere
# Gigabyte grosse install.wim -- ausschliesslich ueber SMB nach. Weder HTTP
# noch NFS helfen dabei. Ohne diese Freigabe startet zwar die WinPE-Konsole,
# aber installieren laesst sich damit nichts.
#
# Freigegeben wird dasselbe Verzeichnis wie per NFS, nur lesend und nur ins
# eigene Subnetz. Die Erklaerungen zur Konfiguration stehen in
# setup/files/samba-pxe.conf.

SMB_ROOT_PFAD=""
SMB_BENUTZER="pxeinstall"
SMB_PASSWORT=""

if systemctl cat smbd.service >/dev/null 2>&1; then
  # Ein Konto, unter dem sich nichts aendern laesst: Systembenutzer ohne
  # Anmeldeshell und ohne Heimatverzeichnis. Gebraucht wird es nur, weil
  # Windows seit Version 10 (1709) den Gastzugang auf SMB2/SMB3 selbst
  # abschaltet -- eine offene Freigabe wuerde also gar nicht funktionieren.
  id "$SMB_BENUTZER" &>/dev/null || useradd --system \
    --home-dir /nonexistent --no-create-home \
    --shell /usr/sbin/nologin "$SMB_BENUTZER"

  # Das Passwort wird einmal erzeugt und bleibt dann stehen -- sonst
  # muesste es nach jedem Update jeder neu abschreiben.
  #
  # ACHTUNG bei beiden Zeilen unten: Dieses Skript laeuft mit
  # "set -euo pipefail". Steht ein "head -n" am ENDE einer Pipe, beendet es
  # sich, sobald es genug hat -- der Schreiber davor bekommt dann SIGPIPE
  # und endet mit Status 141, pipefail reicht den durch, und set -e bricht
  # das ganze Skript ab. Lautlos, mitten im Lauf. Genau das ist am
  # 30.08.2026 passiert. Deshalb begrenzt head hier die EINGABE, und am
  # Ende steht tail (das liest bis zum Schluss) statt head.
  if [[ -f /etc/pxeweb.env ]]; then
    SMB_PASSWORT="$(sed -n 's/^PXE_SMB_PASSWORT=//p' /etc/pxeweb.env | tail -1)"
  fi
  if [[ -z "$SMB_PASSWORT" ]]; then
    # Nur Kleinbuchstaben und Ziffern, und weder l noch 1, weder O noch 0:
    # Getippt wird das in WinPE, und dort liegt eine **englische** Tastatur.
    # Ein Sonderzeichen waere je nach Layout ein anderes.
    #
    # 512 Bytes ergeben nach dem Filtern rund 60 brauchbare Zeichen -- weit
    # mehr als die zwoelf, die gebraucht werden.
    smb_roh="$(head -c 512 /dev/urandom | LC_ALL=C tr -dc 'abcdefghkmnpqrstuvwxyz23456789')"
    SMB_PASSWORT="${smb_roh:0:12}"
  fi

  # Ohne Passwort wird der Rest uebersprungen und nicht abgebrochen: Eine
  # fehlende Freigabe soll die Installation so wenig aufhalten wie ein
  # fehlender NFS-Server ein paar Zeilen weiter oben.
  if [[ ${#SMB_PASSWORT} -lt 12 ]]; then
    warn "Es liess sich kein Passwort erzeugen -- Freigabe nicht aktiviert."
    SMB_PASSWORT=""
  else
    printf '%s\n%s\n' "$SMB_PASSWORT" "$SMB_PASSWORT" \
      | smbpasswd -s -a "$SMB_BENUTZER" >/dev/null
    smbpasswd -e "$SMB_BENUTZER" >/dev/null

    sed -e "s|@@SUBNET@@|$SUBNET|" \
        -e "s|@@ASSETS@@|$PXE_ROOT/assets|" \
        -e "s|@@BENUTZER@@|$SMB_BENUTZER|" \
        "$SRC_DIR/setup/files/samba-pxe.conf" > /etc/samba/pxe.conf

    # Samba kennt kein Verzeichnis wie dnsmasq.d -- die eigene Datei wird
    # deshalb ans Ende der Paket-Konfiguration eingebunden. Ein spaeter
    # genannter Abschnitt gewinnt, damit stechen unsere Werte.
    if ! grep -q '^include = /etc/samba/pxe.conf' /etc/samba/smb.conf; then
      printf '\n# Vom PXE-Bootserver eingebunden (B-027).\ninclude = /etc/samba/pxe.conf\n' \
        >> /etc/samba/smb.conf
    fi

    # Ein Tippfehler in der Konfiguration wuerde smbd stumm nicht starten.
    if testparm -s /etc/samba/smb.conf >/dev/null 2>&1; then
      systemctl enable --now smbd >/dev/null
      systemctl restart smbd
      SMB_ROOT_PFAD="$PXE_ROOT/assets"
      echo "    SMB laeuft. Freigabe: \\\\$SERVER_IP\\install (nur lesend, $SUBNET)"
      echo "    Anmeldung: $SMB_BENUTZER / $SMB_PASSWORT"
    else
      warn "Die Samba-Konfiguration ist fehlerhaft -- Freigabe nicht aktiviert."
      warn "Pruefen mit: testparm -s /etc/samba/smb.conf"
      SMB_PASSWORT=""
    fi
  fi
else
  warn "smbd ist nicht verfuegbar -- Paket samba fehlt?"
  warn "Ohne SMB bleibt es bei der Windows-Konsole; installieren geht nicht."
fi

# Steht hier ein Pfad, packt die Oberflaeche Windows-Medien vollstaendig aus
# statt nur die Startdateien -- siehe SMB_ROOT in webui/uploads.py.
env_setzen PXE_SMB_ROOT "$SMB_ROOT_PFAD" "Freigegebene Installationsquellen fuer Windows (siehe Hilfe, Systeme)."
env_setzen PXE_SMB_BENUTZER "$SMB_BENUTZER" "Konto fuer die SMB-Freigabe -- nur lesend, keine Anmeldeshell."
env_setzen PXE_SMB_PASSWORT "$SMB_PASSWORT" "Passwort dazu. Steht im Klartext, weil die Freigabe nur lesend ist und nur Installationsmedien enthaelt."

# --------------------------------------------------------------------------
log "Wake-on-LAN einrichten"
# --------------------------------------------------------------------------
# Die Weboberflaeche kann eingetragene Rechner per Magic Packet einschalten.
# Ein ausgeschalteter Rechner hat keine IP-Adresse, deshalb geht das Paket an
# die Rundrufadresse des Netzes. Sie steht in der Umgebungsdatei und laesst
# sich dort von Hand anpassen, falls der Server mehrere Netze bedient.
env_setzen PXE_WOL_BROADCAST "$BROADCAST" "Rundrufadresse fuer Wake-on-LAN-Weckpakete (siehe Hilfe, Clients)."
echo "    Weckpakete gehen an: $BROADCAST"

# --------------------------------------------------------------------------
log "iPXE-Bootloader holen"
# --------------------------------------------------------------------------
"$SETUP_DIR/fetch-ipxe.sh"

# --------------------------------------------------------------------------
log "wimboot holen"
# --------------------------------------------------------------------------
# Wird nur gebraucht, wenn jemand ein Windows-Abbild hochlaedt -- die Datei
# ist aber winzig, deshalb liegt sie immer bereit. Schlaegt der Download
# fehl, ist das kein Grund, die Installation abzubrechen: alles andere
# funktioniert ohne sie.
if ! PXE_ASSETS="$PXE_ROOT/assets" "$SETUP_DIR/fetch-wimboot.sh"; then
  warn "wimboot fehlt -- hochgeladene Windows-Abbilder bleiben unvollstaendig."
  warn "Nachholen mit: sudo $SETUP_DIR/fetch-wimboot.sh"
fi

# --------------------------------------------------------------------------
log "Ablage ordnen"
# --------------------------------------------------------------------------
# Seit August 2026 gilt: ein Eintrag, ein Verzeichnis, benannt nach seiner
# Kennung. Auf einem Server, der schon laeuft, liegen die Dateien noch am
# alten Platz -- der Umzug holt das nach. Verschoben wird mit "mv" auf
# derselben Platte, das kostet weder Zeit noch Platz.
#
# Vor dem Neustart der Dienste, damit die Anwendung die fertige Ablage
# vorfindet und nicht mitten im Umzug danebengreift. Schlaegt er fehl, ist
# das kein Grund abzubrechen: Was noch am alten Platz liegt, meldet die
# Oberflaeche dann als verwaisten Ordner.
if ! PXE_ASSETS="$PXE_ROOT/assets" "$SETUP_DIR/umzug-ablage.sh"; then
  warn "Umzug der Ablage unvollstaendig -- siehe Meldungen oben."
  warn "Nachsehen mit: sudo PXE_ASSETS=$PXE_ROOT/assets $SETUP_DIR/umzug-ablage.sh --probe"
fi

# --------------------------------------------------------------------------
log "Dienste starten"
# --------------------------------------------------------------------------
nginx -t
systemctl daemon-reload
systemctl enable --now nginx dnsmasq pxeweb >/dev/null
systemctl restart nginx dnsmasq pxeweb

sleep 2
DIENSTE=(nginx dnsmasq pxeweb)
[[ -n "$NFS_ROOT_PFAD" ]] && DIENSTE+=(nfs-server)
for unit in "${DIENSTE[@]}"; do
  if systemctl is-active --quiet "$unit"; then
    echo "    $unit: laeuft"
  else
    warn "$unit laeuft NICHT -- 'sudo journalctl -u $unit -n 40' zeigt warum."
  fi
done

# --------------------------------------------------------------------------
log "Selbsttest"
# --------------------------------------------------------------------------
if curl -fsS "http://127.0.0.1/health" >/dev/null; then
  echo "    Weboberflaeche antwortet."
else
  warn "Die Weboberflaeche antwortet nicht."
fi

if curl -fsS "http://127.0.0.1/boot.ipxe" | head -1 | grep -q '#!ipxe'; then
  echo "    Bootskript wird ausgeliefert."
else
  warn "/boot.ipxe liefert kein gueltiges iPXE-Skript."
fi

# Hier stand frueher noch, wie man Betriebssysteme herunterlaedt und dem
# dnsmasq zusieht. Das sind Schritte der ersten Einrichtung -- sie stehen
# in docs/02-installation.md. Dieses Skript laeuft aber bei jedem Update,
# und ein "Naechster Schritt" unter jedem Lauf ist keiner mehr: Was
# tatsaechlich fehlt, zeigt die Oberflaeche, und update.sh sagt selbst
# Bescheid, wenn sich am Katalog etwas geaendert hat.
cat <<INFO

===========================================================================
 Fertig.

   Weboberflaeche :  http://$SERVER_IP/
   Boot-Skript    :  http://$SERVER_IP/boot.ipxe

===========================================================================
INFO

# Zum zweiten Mal, und mit Absicht: Der Hinweis oben scrollt bei einem Lauf
# mit apt-get und Downloads laengst weg. Hier steht er da, wo man nach dem
# Lauf ohnehin hinsieht.
if [[ $DHCP_ADRESSE -eq 1 ]]; then
  cat <<HINWEIS
 $SERVER_IP hat dieser Server vom Router bekommen.

 Diese Adresse steht jetzt in den Boot-Skripten, im dnsmasq, im nginx und
 im NFS-Export. Damit das so bleibt, braucht dieser Server eine Adresse,
 die sich nicht aendert -- eine von zwei:

   1. eine Reservierung am Router (empfohlen -- der Router bleibt fuer
      Adressen zustaendig, dieser Server ergaenzt nur die Bootinformation)
   2. eine feste Adresse am Host, auf dem Weg deines Systems

 Beides richtest du selbst ein; dieser Server fasst deine Netzkonfiguration
 nicht an. Aendert sich die Adresse spaeter, sagt die Oberflaeche es unter
 Server Health -- nachgezogen wird sie mit einem erneuten Lauf:

   sudo /opt/pxe-setup/install.sh

===========================================================================
HINWEIS
fi

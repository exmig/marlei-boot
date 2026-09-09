#!/usr/bin/env bash
# ===========================================================================
# Holt die iPXE-Bootloader nach /srv/pxe/tftp.
#
# Diese vier Dateien sind der einzige Teil, der noch per TFTP uebertragen
# wird -- alles Weitere laeuft danach ueber HTTP.
#
#   undionly.kpxe   Rechner im BIOS-/Legacy-Modus
#   snponly.efi     UEFI 64 Bit  (nutzt den Netzwerktreiber der Firmware)
#   ipxe.efi        UEFI 64 Bit, Reserve mit eigenen Treibern
#   snponlyx32.efi  UEFI 32 Bit (selten, z.B. aeltere Atom-Tablets)
#
# Warum snponly und nicht ipxe.efi als Standard? snponly benutzt den
# Netzwerktreiber, den die Firmware schon geladen hat. Das ist bei
# UEFI-Boot deutlich vertraeglicher als iPXEs eigene Treiber.
# ===========================================================================
set -euo pipefail

TFTP_DIR="${PXE_TFTP_DIR:-/srv/pxe/tftp}"
BASE_URL="${IPXE_MIRROR:-https://boot.ipxe.org}"

mkdir -p "$TFTP_DIR"

fetch() {
  local url="$1" name="$2"
  printf '    %-16s ' "$name"
  if curl -fsSL --retry 3 --max-time 120 -o "$TFTP_DIR/$name.tmp" "$url"; then
    mv "$TFTP_DIR/$name.tmp" "$TFTP_DIR/$name"
    printf 'ok (%s)\n' "$(du -h "$TFTP_DIR/$name" | cut -f1)"
  else
    rm -f "$TFTP_DIR/$name.tmp"
    printf 'FEHLGESCHLAGEN\n'
    printf '        %s\n' "$url"
    return 1
  fi
}

echo "iPXE-Bootloader nach $TFTP_DIR:"

failed=0
fetch "$BASE_URL/undionly.kpxe"            undionly.kpxe   || failed=1
fetch "$BASE_URL/x86_64-efi/snponly.efi"   snponly.efi     || failed=1
fetch "$BASE_URL/x86_64-efi/ipxe.efi"      ipxe.efi        || failed=1
fetch "$BASE_URL/i386-efi/snponly.efi"     snponlyx32.efi  || failed=1

chmod 0644 "$TFTP_DIR"/*.kpxe "$TFTP_DIR"/*.efi 2>/dev/null || true

if [[ $failed -ne 0 ]]; then
  echo
  echo "[!] Mindestens eine Datei fehlt. Ohne sie koennen die betroffenen"
  echo "    Rechner nicht per Netzwerk starten. Internetverbindung der VM"
  echo "    pruefen und das Skript erneut ausfuehren."
  exit 1
fi

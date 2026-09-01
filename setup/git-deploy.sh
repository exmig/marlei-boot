#!/usr/bin/env bash
# ===========================================================================
# Richtet auf DER VM ein Git-Ziel ein, in das du vom Arbeitsplatz pushst.
#
# Einmalig in der VM ausfuehren:
#     ./setup/git-deploy.sh
#
# Danach vom Windows-Rechner aus:
#     git remote add vm ssh://BENUTZER@192.168.178.30/~/pxe-server.git
#     git push vm main
#
# Jeder Push aktualisiert automatisch das Arbeitsverzeichnis in der VM.
# Ein "bare" Repository ist noetig, weil man in ein Repository mit
# ausgechecktem Arbeitsverzeichnis nicht ohne Weiteres pushen kann.
# ===========================================================================
set -euo pipefail

REPO="${1:-$HOME/pxe-server.git}"
WORKTREE="${2:-$HOME/prj_pxe_server}"
BRANCH="${GIT_DEPLOY_BRANCH:-main}"

if ! command -v git >/dev/null; then
  echo "git fehlt. Installieren mit:  sudo apt install git"
  exit 1
fi

mkdir -p "$WORKTREE"

if [[ -d "$REPO" ]]; then
  echo "Repository besteht bereits: $REPO  (Hook wird aktualisiert)"
else
  git init --bare --initial-branch="$BRANCH" "$REPO" >/dev/null
  echo "Bare-Repository angelegt: $REPO"
fi

cat > "$REPO/hooks/post-receive" <<HOOK
#!/usr/bin/env bash
# Wird nach jedem Push ausgefuehrt: checkt den neuen Stand ins
# Arbeitsverzeichnis aus, damit dort sofort die aktuellen Dateien liegen.
set -euo pipefail

WORKTREE="$WORKTREE"
BRANCH="$BRANCH"

while read -r _old _new ref; do
  [[ "\$ref" == "refs/heads/\$BRANCH" ]] || continue

  git --work-tree="\$WORKTREE" --git-dir="$REPO" checkout -f "\$BRANCH"
  chmod +x "\$WORKTREE"/setup/*.sh 2>/dev/null || true

  echo ""
  echo "  Ausgecheckt nach \$WORKTREE"
  echo ""
  echo "  Uebernehmen mit:"
  echo "    sudo \$WORKTREE/setup/install.sh"
  echo ""
done
HOOK

chmod +x "$REPO/hooks/post-receive"

# Damit "git pull" spaeter auch im Arbeitsverzeichnis funktioniert.
if [[ ! -d "$WORKTREE/.git" ]]; then
  git --work-tree="$WORKTREE" --git-dir="$REPO" config core.bare true
fi

MY_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')"

cat <<INFO

===========================================================================
 Fertig. Auf dem Windows-Rechner jetzt einrichten:

   cd C:\\Users\\mel\\Documents\\prj_pxe_server
   git remote add vm ssh://$USER@${MY_IP:-<ip-der-vm>}/~/${REPO##*/}
   git push -u vm $BRANCH

 Ab dann genuegt fuer jede Aenderung:

   git add -A && git commit -m "..." && git push vm

 Und in der VM zum Uebernehmen:

   sudo $WORKTREE/setup/install.sh

===========================================================================
INFO

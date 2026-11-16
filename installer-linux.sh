#!/usr/bin/env bash
# installer-linux.sh - Cree le lanceur de Reels Vault pour Linux.
#
#   bash installer-linux.sh
#
# A lancer une seule fois (ou si tu deplaces le dossier du projet). Il cree :
#  - ~/.local/share/applications/reels-vault.desktop : Reels Vault apparait dans
#    le lanceur d'applications (Super+Espace sous Omarchy) ;
#  - "Reels Vault.desktop" dans ce dossier : double-clic depuis le gestionnaire
#    de fichiers (la premiere fois, il peut demander d'autoriser le lancement).
#
# Pas besoin de le relancer apres une modification de l'interface : le lanceur
# ne fait que demarrer interface/app.py.

set -e
DOSSIER="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$DOSSIER/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"

CONTENU="[Desktop Entry]
Type=Application
Name=Reels Vault
Comment=Tes Reels enregistres, transformes en second cerveau
Exec=\"$PYTHON\" \"$DOSSIER/interface/app.py\"
Path=$DOSSIER
Icon=$DOSSIER/interface/icone.svg
Terminal=false
Categories=Utility;"

mkdir -p "$HOME/.local/share/applications"
printf '%s\n' "$CONTENU" > "$HOME/.local/share/applications/reels-vault.desktop"
printf '%s\n' "$CONTENU" > "$DOSSIER/Reels Vault.desktop"
chmod +x "$DOSSIER/Reels Vault.desktop"
command -v gio >/dev/null && gio set "$DOSSIER/Reels Vault.desktop" metadata::trusted true 2>/dev/null || true

echo "Lanceur cree :"
echo "  - dans le menu des applications : Reels Vault"
echo "  - dans ce dossier : Reels Vault.desktop"

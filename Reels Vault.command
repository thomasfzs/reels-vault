#!/bin/bash
# Reels Vault - lanceur macOS : double-clic dans le Finder pour ouvrir la fenetre.
# (La premiere fois : clic droit > Ouvrir, pour autoriser le script.)
# Rien a refaire apres une modification de l'interface.
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python; else PYTHON=python3; fi
"$PYTHON" interface/app.py &
disown
# referme la fenetre du Terminal ouverte par le double-clic
osascript -e 'tell application "Terminal" to close front window' >/dev/null 2>&1 &
exit 0

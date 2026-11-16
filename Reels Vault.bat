@echo off
rem Reels Vault - lanceur Windows : double-clic pour ouvrir la fenetre.
rem Rien a refaire apres une modification de l'interface.
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "interface\app.py"
) else (
    start "" pythonw "interface\app.py"
)

#!/usr/bin/env python3
"""
mettre_a_jour.py - Fait tourner toute la chaine d'un coup, pour que le vault
se remplisse tout seul :

  1. lit tes derniers posts "Enregistres" directement sur Instagram
     (gallery-dl, avec la session de ton navigateur) + les liens de inbox.txt
  2. ingest.py     : recupere et transcrit ceux qui ne sont pas encore la
  3. resumer.py    : les resume avec Claude
  4. classer.py    : les range dans les themes existants
  5. construire.py : regenere index.md, vault.html et le coffre Obsidian

Tu n'as rien a faire de special : enregistre un Reel dans Instagram comme
d'habitude, il arrivera dans le vault au prochain passage. S'il n'y a rien de
nouveau, le script s'arrete tout de suite sans appeler Claude.

Prevu pour etre lance chaque jour par un minuteur (voir le README).

Usage :
    python mettre_a_jour.py --compte ton_pseudo --cookies "brave+gnomekeyring"
    python mettre_a_jour.py --compte ton_pseudo --cookies firefox --max 50
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent
PYTHON = sys.executable


def log(message):
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] {message}", flush=True)


def notifier(titre, texte):
    """Petite notification de bureau, si le systeme en propose une."""
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "Reels Vault", titre, texte], check=False)


def enregistres_instagram(compte, cookies, maximum):
    """Liens des derniers posts enregistres, du plus recent au plus ancien.
    gallery-dl liste une ligne par image : un carrousel apparait plusieurs
    fois, d'ou le dedoublonnage."""
    commande = [PYTHON, "-m", "gallery_dl", "--no-download",
                "--range", f"1-{maximum * 3}", "--print", "{post_url}",
                f"https://www.instagram.com/{compte}/saved/"]
    if cookies:
        commande[3:3] = ["--cookies-from-browser", cookies]
    r = subprocess.run(commande, capture_output=True, text=True, timeout=600)
    liens = []
    for ligne in r.stdout.splitlines():
        ligne = ligne.strip()
        if ligne.startswith("https://") and ligne not in liens:
            liens.append(ligne)
    if not liens and r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-300:] or "gallery-dl a echoue")
    return liens[:maximum]


def identifiant(lien):
    fin = lien.rstrip("/").split("/")[-1].split("?")[0]
    return re.sub(r"[^A-Za-z0-9_-]", "", fin)


def lancer(script, *args):
    log(f"-> {script} {' '.join(args)}")
    r = subprocess.run([PYTHON, str(DOSSIER / script), *args], cwd=DOSSIER)
    if r.returncode != 0:
        raise RuntimeError(f"{script} s'est arrete avec le code {r.returncode}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--compte", help="ton pseudo Instagram (pour lire tes Enregistres)")
    p.add_argument("--cookies", default=None,
                   help='navigateur ou tu es connecte : firefox, "brave+gnomekeyring"...')
    p.add_argument("--max", type=int, default=60,
                   help="nombre de posts enregistres recents a verifier (defaut 60)")
    args = p.parse_args()

    journal = {}
    if (DOSSIER / "journal.json").exists():
        journal = json.loads((DOSSIER / "journal.json").read_text(encoding="utf-8"))
    # les echecs sont retentes (souvent un souci reseau passager)
    deja_vus = {identifiant(l) for l, v in journal.items() if v.get("statut") == "ok"}

    candidats = []
    if args.compte:
        try:
            candidats = enregistres_instagram(args.compte, args.cookies, args.max)
            log(f"{len(candidats)} posts enregistres recents lus sur Instagram")
        except Exception as e:  # noqa: BLE001
            log(f"Lecture des Enregistres impossible : {e}")
            notifier("Reels Vault : souci de connexion",
                     "Impossible de lire tes Enregistrés. Es-tu toujours connecté à Instagram dans ton navigateur ?")
    inbox = DOSSIER / "inbox.txt"
    if inbox.exists():
        candidats += re.findall(r"https?://\S+", inbox.read_text(encoding="utf-8"))

    nouveaux = [l for l in dict.fromkeys(candidats) if identifiant(l) not in deja_vus]
    if not nouveaux:
        log("Rien de nouveau.")
        return

    log(f"{len(nouveaux)} nouveau(x) lien(s)")
    a_traiter = DOSSIER / ".a_traiter.txt"
    a_traiter.write_text("\n".join(nouveaux) + "\n", encoding="utf-8")

    avant = len(list((DOSSIER / "raw").glob("*.md"))) if (DOSSIER / "raw").exists() else 0
    options = ["--cookies", args.cookies] if args.cookies else []
    lancer("ingest.py", str(a_traiter), *options)
    apres = len(list((DOSSIER / "raw").glob("*.md")))
    a_traiter.unlink(missing_ok=True)

    if apres > avant:
        lancer("resumer.py")
        lancer("classer.py")
        lancer("construire.py")
    ajoutes = apres - avant
    log(f"Termine : {ajoutes} video(s) ajoutee(s) au vault.")
    if ajoutes:
        notifier("Reels Vault", f"{ajoutes} nouvelle(s) vidéo(s) dans ton vault.")


if __name__ == "__main__":
    main()

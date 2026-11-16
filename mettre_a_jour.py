#!/usr/bin/env python3
"""
mettre_a_jour.py - Ajoute tes derniers Reels enregistres au vault, en une
commande, quand TU le decides. Rien ne se lance tout seul.

    .venv/bin/python mettre_a_jour.py

Il affiche ce qu'il trouve, puis deroule les etapes une par une :

  1. Chercher   lit tes derniers posts "Enregistres" sur Instagram (avec la
                session de ton navigateur) + les liens de inbox.txt
  2. Recolter   ingest.py : telechargement + transcription (local, gratuit)
  3. Resumer    resumer.py : Claude    -> estimation des tokens, puis ton accord
  4. Classer    classer.py : Claude    -> estimation des tokens, puis ton accord
  5. Construire construire.py : index.md, vault.html, Obsidian (local, instantane)

Si tu refuses une etape, rien n'est perdu : la prochaine fois, le script voit
ce qui reste a faire et reprend a cette etape, sans tout recommencer.

La premiere fois, il te demande ton pseudo Instagram et ton navigateur, et
les garde dans config.json (non versionne).

Options :
    --max 300     verifier plus d'Enregistres (defaut 60), pour rattraper un retard
    --oui         repondre oui a toutes les questions
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from commun import charger_json, demander_accord, sauver_json

DOSSIER = Path(__file__).resolve().parent
PYTHON = sys.executable
SECONDES_PAR_REEL = 30  # recolte + transcription, en moyenne


def titre_etape(numero, texte):
    print(f"\n{'=' * 60}\n Etape {numero}/5 · {texte}\n{'=' * 60}", flush=True)


def identifiant(lien):
    """Meme logique que ingest.py : le code du post dans l'URL."""
    fin = lien.rstrip("/").split("/")[-1].split("?")[0]
    return re.sub(r"[^A-Za-z0-9_-]", "", fin)


def lancer(script, *args):
    """Lance un des autres scripts, dans ce meme terminal (il peut donc
    afficher sa progression et poser ses questions)."""
    return subprocess.run([PYTHON, str(DOSSIER / script), *args], cwd=DOSSIER).returncode


# ---------------------------------------------------------------- configuration

def charger_config(args):
    chemin = DOSSIER / "config.json"
    config = charger_json(chemin, {})
    if not config.get("compte"):
        print("Premiere utilisation : deux questions, gardees dans config.json.")
        config["compte"] = input("  Ton pseudo Instagram : ").strip().lstrip("@")
        print('  Navigateur ou tu es connecte a Instagram : firefox, chrome, brave...')
        print('  (sous Linux, Chrome/Brave demandent le trousseau : "brave+gnomekeyring")')
        config["cookies"] = input("  Navigateur : ").strip()
        sauver_json(chemin, config)
    return config


# ---------------------------------------------------------------- etape 1

def enregistres_instagram(compte, cookies, maximum):
    """Liens des derniers posts enregistres, du plus recent au plus ancien.

    gallery-dl ouvre la page instagram.com/<compte>/saved/ comme le ferait ton
    navigateur (avec ses cookies) et liste les posts. Il sort une ligne par
    image : un carrousel apparait plusieurs fois, d'ou le dedoublonnage."""
    commande = [PYTHON, "-m", "gallery_dl", "--no-download",
                "--range", f"1-{maximum * 3}", "--print", "{post_url}"]
    if cookies:
        commande += ["--cookies-from-browser", cookies]
    commande.append(f"https://www.instagram.com/{compte}/saved/")
    r = subprocess.run(commande, capture_output=True, text=True, timeout=900)
    liens = []
    for ligne in r.stdout.splitlines():
        ligne = ligne.strip()
        if ligne.startswith("https://") and ligne not in liens:
            liens.append(ligne)
    if not liens and r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-300:] or "gallery-dl a echoue")
    return liens[:maximum]


def chercher_nouveaux(config, maximum):
    journal = charger_json(DOSSIER / "journal.json", {})
    deja_ok = {identifiant(l) for l, v in journal.items() if v.get("statut") == "ok"}

    candidats = []
    print(f"Lecture de tes {maximum} derniers Enregistres sur Instagram...")
    try:
        candidats = enregistres_instagram(config["compte"], config.get("cookies"), maximum)
        print(f"  {len(candidats)} posts lus.")
    except Exception as e:  # noqa: BLE001
        print(f"  Impossible de lire tes Enregistres : {e}")
        print("  Verifie que tu es connecte a Instagram dans ton navigateur.")
    inbox = DOSSIER / "inbox.txt"
    if inbox.exists():
        liens_inbox = re.findall(r"https?://\S+", inbox.read_text(encoding="utf-8"))
        if liens_inbox:
            print(f"  + {len(liens_inbox)} lien(s) dans inbox.txt")
            candidats += liens_inbox

    return [l for l in dict.fromkeys(candidats) if identifiant(l) not in deja_ok]


# ---------------------------------------------------------------- etat du vault

def etat_du_vault():
    """Ce qui reste a faire aux etapes 3 et 4, meme sans nouveau reel (par
    exemple si tu avais refuse une etape la derniere fois)."""
    fiches = {p.stem for p in (DOSSIER / "raw").glob("*.md")} if (DOSSIER / "raw").exists() else set()
    resumes = charger_json(DOSSIER / "resumes.json", {})
    taxo = charger_json(DOSSIER / "taxonomie.json", {})
    a_resumer = len(fiches - set(resumes))
    a_classer = len(set(resumes) - set(taxo.get("affectations", {})))
    return a_resumer, a_classer


# ---------------------------------------------------------------- programme

def main():
    p = argparse.ArgumentParser(description="Ajoute tes derniers Reels enregistres au vault.")
    p.add_argument("--max", type=int, default=60,
                   help="nombre d'Enregistres recents a verifier (defaut 60)")
    p.add_argument("--oui", action="store_true", help="repondre oui a toutes les questions")
    args = p.parse_args()
    config = charger_config(args)
    oui = ["--oui"] if args.oui else []
    debut = time.time()

    # 1. chercher
    titre_etape(1, "Chercher les nouveaux reels")
    nouveaux = chercher_nouveaux(config, args.max)
    a_resumer, a_classer = etat_du_vault()
    print(f"\n  Nouveaux reels a recolter : {len(nouveaux)}")
    print(f"  Deja recoltes, pas encore resumes : {a_resumer}")
    print(f"  Deja resumes, pas encore classes : {a_classer}")
    if not nouveaux and not a_resumer and not a_classer:
        print("\nTout est a jour, rien a faire.")
        return

    # 2. recolter (local)
    titre_etape(2, "Recolter et transcrire (local, gratuit)")
    if not nouveaux:
        print("Rien de nouveau a recolter.")
    else:
        minutes = max(1, len(nouveaux) * SECONDES_PAR_REEL // 60)
        print(f"{len(nouveaux)} reel(s), environ {minutes} min (le PC doit rester allume).")
        if demander_accord("Lancer la recolte ?", args.oui):
            a_traiter = DOSSIER / ".a_traiter.txt"
            a_traiter.write_text("\n".join(nouveaux) + "\n", encoding="utf-8")
            options = ["--cookies", config["cookies"]] if config.get("cookies") else []
            lancer("ingest.py", str(a_traiter), *options)
            a_traiter.unlink(missing_ok=True)
        else:
            print("Recolte sautee : ces reels seront proposes la prochaine fois.")

    # 3. resumer (Claude) : resumer.py affiche l'estimation et demande l'accord
    titre_etape(3, "Resumer avec Claude")
    lancer("resumer.py", *oui)

    # 4. classer (Claude) : idem
    titre_etape(4, "Classer par themes avec Claude")
    lancer("classer.py", *oui)

    # 5. construire (local)
    titre_etape(5, "Construire le vault (index, page web, Obsidian)")
    lancer("construire.py")

    a_resumer, a_classer = etat_du_vault()
    print(f"\nTermine en {(time.time() - debut) / 60:.0f} min.")
    if a_resumer or a_classer:
        print(f"Il reste {a_resumer} fiche(s) a resumer et {a_classer} a classer : "
              "relance mettre_a_jour.py quand tu veux, il reprendra la.")


if __name__ == "__main__":
    main()

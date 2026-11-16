"""
commun.py - Fonctions partagees par resumer.py, classer.py et construire.py.

- lecture des fiches brutes de raw/ (produites par ingest.py)
- appel de Claude en mode non interactif (`claude -p`), qui utilise ton
  abonnement Claude : pas de cle API, pas de facturation au token.
"""

import base64
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DOSSIER_PROJET = Path(__file__).resolve().parent
MODELE_DEFAUT = "haiku"
LARGEUR_IMAGE = 512


# ---------------------------------------------------------------- fiches brutes

def _section(texte, titre):
    m = re.search(rf"^## {re.escape(titre)}\s*\n(.*?)(?=\n## |\Z)", texte, re.M | re.S)
    return m.group(1).strip() if m else ""


def _champ(texte, nom):
    m = re.search(rf"^{nom}:[ \t]*(.*)$", texte, re.M)
    return m.group(1).strip() if m else ""


def lire_fiche_brute(chemin, vault):
    """Lit une fiche de raw/ et renvoie un dict propre (sans le bruit)."""
    texte = chemin.read_text(encoding="utf-8", errors="ignore")

    description = _section(texte, "Description")
    if description == "(vide)":
        description = ""
    transcription = _section(texte, "Transcription audio")
    if "pas d'audio exploitable" in transcription:
        transcription = ""

    images = []
    for ligne in _section(texte, "Images").splitlines():
        ligne = ligne.strip().lstrip("-").strip()
        if ligne and ligne != "(aucune)" and (vault / ligne).exists():
            images.append(ligne)

    titre = re.search(r"^#\s+(.+)$", texte, re.M)
    duree = _champ(texte, "duree_s")
    return {
        "id": chemin.stem,
        "lien": _champ(texte, "source"),
        "plateforme": _champ(texte, "plateforme") or "Instagram",
        "genre": _champ(texte, "genre") or "video",
        "auteur": _champ(texte, "auteur") or "inconnu",
        "duree_s": float(duree) if re.fullmatch(r"[\d.]+", duree) else None,
        "titre_brut": titre.group(1).strip() if titre else chemin.stem,
        "description": description,
        "transcription": transcription,
        "images": images,
    }


def lire_toutes_les_fiches(vault):
    return [lire_fiche_brute(p, vault) for p in sorted((vault / "raw").glob("*.md"))]


# ---------------------------------------------------------------- JSON du vault

def charger_json(chemin, defaut):
    if chemin.exists():
        return json.loads(chemin.read_text(encoding="utf-8"))
    return defaut


def sauver_json(chemin, donnees):
    temp = chemin.with_suffix(".tmp")
    temp.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(chemin)  # ecriture atomique : jamais de fichier a moitie ecrit


# ---------------------------------------------------------------- appel de Claude

def demander_accord(question, oui=False):
    """Pose une question oui/non dans le terminal. `oui=True` (option --oui)
    repond oui d'office. Sans terminal (lancement automatique), c'est non."""
    if oui:
        return True
    if not sys.stdin.isatty():
        print(f"{question} -> non (pas de terminal pour repondre ; utilise --oui)")
        return False
    reponse = input(f"{question} [o/N] ").strip().lower()
    return reponse in ("o", "oui", "y", "yes")


def afficher_estimation(appels, entree, sortie, modele):
    n = lambda x: f"{x:,}".replace(",", " ")  # 12 345 plutot que 12,345
    print(f"Estimation : {appels} appel(s) a Claude ({modele}), "
          f"~{n(entree)} tokens en entree et ~{n(sortie)} en sortie, "
          f"soit ~{n(entree + sortie)} tokens au total.")


class ErreurClaude(RuntimeError):
    pass


# consommation cumulee de tous les appels (pour afficher un bilan)
CONSO = {"appels": 0, "entree": 0, "cache": 0, "sortie": 0, "cout_usd": 0.0}


def image_reduite_base64(chemin, largeur=LARGEUR_IMAGE):
    """Reduit l'image avec ffmpeg avant de l'envoyer : le cout d'une image
    est proportionnel a sa surface."""
    jpeg = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(chemin),
         "-vf", f"scale='min({largeur},iw)':-2", "-frames:v", "1",
         "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
        capture_output=True, check=True, timeout=60,
    ).stdout
    return base64.b64encode(jpeg).decode()


def _comptabiliser(sortie, nb_images=0, taille_prompt=0):
    u = sortie.get("usage") or {}
    # journal detaille de chaque appel, pour comprendre la consommation
    with (DOSSIER_PROJET / "conso.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "tours": sortie.get("num_turns"), "images": nb_images,
            "caracteres": taille_prompt, "erreur": sortie.get("is_error"),
            "entree": u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0),
            "cache": u.get("cache_read_input_tokens", 0),
            "sortie": u.get("output_tokens", 0),
            "modeles": list((sortie.get("modelUsage") or {}).keys()),
        }) + "\n")
    CONSO["appels"] += 1
    CONSO["entree"] += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    CONSO["cache"] += u.get("cache_read_input_tokens", 0)
    CONSO["sortie"] += u.get("output_tokens", 0)
    CONSO["cout_usd"] += sortie.get("total_cost_usd") or 0.0
    CONSO["reflexion"] = CONSO.get("reflexion", 0) + (u.get("output_tokens_details") or {}).get("thinking_tokens", 0)


def appeler_claude(prompt, systeme, schema, modele=MODELE_DEFAUT, images=(),
                   timeout=900):
    """Lance `claude -p` (un seul tour, aucun outil) et renvoie la sortie
    structuree (dict conforme a `schema`).

    `images` : liste de (legende, chemin). Elles sont jointes directement au
    message, reduites, en un seul envoi. (Laisser Claude les ouvrir lui-meme
    avec l'outil Read coute beaucoup plus cher : chaque image ouverte
    relance un tour complet avec toute la conversation.)"""
    contenu = [{"type": "text", "text": prompt}]
    for legende, chemin in images:
        contenu.append({"type": "text", "text": legende})
        contenu.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg",
            "data": image_reduite_base64(chemin)}})
    message = json.dumps({"type": "user", "message": {"role": "user", "content": contenu}})

    commande = [
        "claude", "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json", "--verbose",
        "--model", modele,
        "--effort", "low",  # pas besoin de "reflechir" pour resumer
        "--system-prompt", systeme,
        "--json-schema", json.dumps(schema),
        "--tools", "",
        "--setting-sources", "",
        "--no-session-persistence",
        "--disable-slash-commands",
    ]
    # dossier de travail vide : Claude ne charge aucun CLAUDE.md du projet
    with tempfile.TemporaryDirectory() as vide:
        resultat = subprocess.run(
            commande, input=message + "\n", capture_output=True, text=True,
            timeout=timeout, cwd=vide,
        )

    sortie = None
    for ligne in resultat.stdout.splitlines():
        try:
            evenement = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if evenement.get("type") == "result":
            sortie = evenement
    if sortie is None:
        raise ErreurClaude((resultat.stderr or resultat.stdout).strip()[-500:])

    _comptabiliser(sortie, len(images), len(prompt))
    if sortie.get("is_error"):
        raise ErreurClaude(str(sortie.get("result"))[:500])
    donnees = sortie.get("structured_output")
    if donnees is None:
        raise ErreurClaude(f"pas de sortie structuree : {str(sortie.get('result'))[:300]}")
    return donnees

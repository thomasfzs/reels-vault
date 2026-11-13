#!/usr/bin/env python3
"""
resumer.py - Transforme les fiches brutes de raw/ en resumes structures,
avec Claude (via `claude -p`, donc sur ton abonnement, sans cle API).

Pour chaque fiche, Claude lit la description, la transcription Whisper et,
quand le texte ne suffit pas (carrousels, videos sans voix off), les images
elles-memes pour y lire le texte incruste. Il produit :
  - un titre parlant
  - un resume concret (noms, lieux, prix, outils... jamais de generalites)
  - la liste des infos concretes a retenir
  - des mots-cles libres (servent ensuite a classer.py pour les themes)

Resultat : resumes.json (une entree par fiche). Le script est relancable a
volonte : il ne traite que les fiches qui n'y sont pas encore.

Usage :
    python resumer.py                  # tout ce qui reste a resumer
    python resumer.py --limite 10      # pour tester sur 10 fiches
    python resumer.py --refaire ID     # refaire une fiche precise
"""

import argparse
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from commun import (CONSO, DOSSIER_PROJET, MODELE_DEFAUT, ErreurClaude,
                    appeler_claude, charger_json, lire_toutes_les_fiches,
                    sauver_json)

FICHES_PAR_APPEL = 5
APPELS_EN_PARALLELE = 3
MAX_IMAGES_VIDEO = 3
MAX_IMAGES_CARROUSEL = 6
MAX_CARACTERES_TEXTE = 6000

SYSTEME = """Tu alimentes le "second cerveau" de Thomas : une base de ses Reels
Instagram et TikTok sauvegardes. Tu recois plusieurs fiches brutes (description
du post, transcription audio automatique, et parfois des images a lire avec
l'outil Read). Pour CHAQUE fiche, tu produis une entree structuree.

Regles :
- Ecris en francais, meme si la video est en anglais.
- "titre" : court (max ~70 caracteres) et specifique. "Raspberry Pi + PiKVM pour
  controler un PC a distance", pas "Astuce tech".
- "resume" : 2 a 5 phrases qui disent CONCRETEMENT ce que la video apporte.
  Aucune generalite ("cette video parle de..."), aucun commentaire sur la
  qualite de la source.
- "infos" : la liste des elements concrets a retenir, un par ligne courte :
  noms d'outils, de produits, de lieux, adresses, prix, horaires, chiffres,
  commandes, liens, etapes d'une methode, titres recommandes. C'est ce qui
  permettra de retrouver la video plus tard par une recherche. Liste vide si
  rien de concret.
- "mots_cles" : 2 a 5 mots-cles en minuscules decrivant le SUJET (pas le
  format) : "cyclisme", "bike fitting", "self-hosting", "trek"...
- "format" : la nature du contenu (voir les valeurs autorisees).
- La transcription automatique et le texte lu sur les images contiennent du
  bruit (mots deformes, repetitions). Corrige silencieusement les noms propres
  evidents, ignore le reste. N'invente JAMAIS une info absente de la fiche.
- Les accroches "commente X pour recevoir le lien" ne sont pas du contenu :
  ne les rapporte pas.
- Si une fiche ne contient vraiment rien d'exploitable, mets
  "exploitable": false, un titre descriptif de ce qu'on devine, et un resume
  d'une phrase.
- Certaines fiches sont accompagnees d'images (jointes au message) ou du
  texte lu dessus par OCR : c'est le texte incruste a l'ecran (listes, noms,
  prix). L'OCR est bruite : garde seulement ce qui est lisible et coherent.
- Renvoie exactement une entree par fiche recue, avec le meme "id"."""

FORMATS = ["outil", "tutoriel", "astuce", "lieu", "recette", "entrainement",
           "produit", "inspiration", "information", "divertissement", "autre"]

SCHEMA = {
    "type": "object",
    "properties": {
        "fiches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "titre": {"type": "string"},
                    "resume": {"type": "string"},
                    "infos": {"type": "array", "items": {"type": "string"}},
                    "mots_cles": {"type": "array", "items": {"type": "string"}},
                    "format": {"type": "string", "enum": FORMATS},
                    "exploitable": {"type": "boolean"},
                },
                "required": ["id", "titre", "resume", "infos", "mots_cles",
                             "format", "exploitable"],
            },
        }
    },
    "required": ["fiches"],
}


def images_a_lire(fiche):
    """Les images ne sont envoyees que si le texte est trop maigre : c'est ce
    qui coute le plus de quota."""
    if fiche["genre"] == "carrousel":
        return fiche["images"][:MAX_IMAGES_CARROUSEL]
    texte_maigre = len(fiche["transcription"]) < 200 and len(fiche["description"]) < 300
    return fiche["images"][:MAX_IMAGES_VIDEO] if texte_maigre else []


def ocr(chemin):
    """Lit le texte incruste dans une image avec tesseract (local, gratuit)."""
    try:
        r = subprocess.run(["tesseract", str(chemin), "-", "-l", "eng", "--psm", "11"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    # on garde les lignes qui ressemblent a des mots, pas le bruit
    lignes = [l.strip() for l in r.stdout.splitlines()
              if len(l.strip()) >= 3 and sum(c.isalpha() for c in l) >= 0.6 * len(l.strip())]
    return " / ".join(lignes)


def bloc_fiche(fiche, vault, mode_images):
    lignes = [
        f"=== FICHE id={fiche['id']} ===",
        f"plateforme : {fiche['plateforme']} | genre : {fiche['genre']}"
        + (f" | duree : {fiche['duree_s']:.0f} s" if fiche["duree_s"] else ""),
        f"auteur : {fiche['auteur']}",
        "",
        "Description du post :",
        fiche["description"][:MAX_CARACTERES_TEXTE] or "(vide)",
        "",
        "Transcription audio :",
        fiche["transcription"][:MAX_CARACTERES_TEXTE] or "(aucune)",
    ]
    images = images_a_lire(fiche)
    if images and mode_images == "ocr":
        textes = [t for t in (ocr(vault / p) for p in images) if t]
        lignes += ["", "Texte lu sur les images (OCR) :"] + [f"- {t[:800]}" for t in textes]
    elif images and mode_images == "vision":
        lignes += ["", f"({len(images)} image(s) jointe(s) a la fin du message)"]
    return "\n".join(lignes)


def resumer_lot(lot, vault, modele, mode_images):
    prompt = "\n\n".join(bloc_fiche(f, vault, mode_images) for f in lot)
    images = []
    if mode_images == "vision":
        for f in lot:
            for n, p in enumerate(images_a_lire(f), 1):
                images.append((f"Image {n} de la fiche id={f['id']} :", vault / p))
    reponse = appeler_claude(prompt, SYSTEME, SCHEMA, modele=modele, images=images)
    attendus = {f["id"] for f in lot}
    return [e for e in reponse["fiches"] if e.get("id") in attendus]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vault", default=str(DOSSIER_PROJET))
    p.add_argument("--modele", default=MODELE_DEFAUT)
    p.add_argument("--limite", type=int, default=0)
    p.add_argument("--par-appel", type=int, default=FICHES_PAR_APPEL)
    p.add_argument("--paralleles", type=int, default=APPELS_EN_PARALLELE)
    p.add_argument("--images", choices=["ocr", "vision", "aucune"], default="vision",
                   help="ocr = texte des images lu en local (gratuit, moins precis) ; "
                        "vision = images reduites envoyees a Claude (defaut, bien plus precis)")
    p.add_argument("--refaire", nargs="*", default=[],
                   help="identifiants de fiches a resumer de nouveau")
    args = p.parse_args()

    vault = Path(args.vault)
    chemin = vault / "resumes.json"
    resumes = charger_json(chemin, {})
    for ident in args.refaire:
        resumes.pop(ident, None)

    fiches = [f for f in lire_toutes_les_fiches(vault) if f["id"] not in resumes]
    if args.limite:
        fiches = fiches[: args.limite]
    print(f"{len(resumes)} fiches deja resumees, {len(fiches)} a faire.")
    if not fiches:
        return

    lots = [fiches[i:i + args.par_appel] for i in range(0, len(fiches), args.par_appel)]
    verrou = threading.Lock()
    faites = echecs = 0
    debut = time.time()

    with ThreadPoolExecutor(max_workers=args.paralleles) as pool:
        futurs = {pool.submit(resumer_lot, lot, vault, args.modele, args.images): lot for lot in lots}
        for futur in as_completed(futurs):
            lot = futurs[futur]
            try:
                entrees = futur.result()
            except (ErreurClaude, OSError, ValueError) as e:
                echecs += len(lot)
                print(f"  [echec] {', '.join(f['id'] for f in lot)} : {e}", file=sys.stderr)
                continue
            par_id = {f["id"]: f for f in lot}
            with verrou:
                for e in entrees:
                    brute = par_id[e["id"]]
                    resumes[e["id"]] = {
                        **{k: e[k] for k in ("titre", "resume", "infos", "mots_cles",
                                             "format", "exploitable")},
                        "lien": brute["lien"],
                        "auteur": brute["auteur"],
                        "plateforme": brute["plateforme"],
                        "genre": brute["genre"],
                        "images": brute["images"],
                        "resume_le": date.today().isoformat(),
                    }
                sauver_json(chemin, resumes)
                faites += len(entrees)
                echecs += len(lot) - len(entrees)
            ecoule = time.time() - debut
            print(f"  {faites}/{len(fiches)} resumees ({ecoule / 60:.1f} min)", flush=True)

    print(f"\nTermine : {faites} resumees, {echecs} en echec.")
    print(f"Consommation : {CONSO['appels']} appels, {CONSO['entree']:,} tokens en entree "
          f"(+{CONSO['cache']:,} en cache), {CONSO['sortie']:,} en sortie "
          f"(equivalent API : {CONSO['cout_usd']:.2f} $)")
    if echecs:
        print("Relance la meme commande pour retenter les echecs.")
    print("Etape suivante : python classer.py")


if __name__ == "__main__":
    main()

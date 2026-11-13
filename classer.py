#!/usr/bin/env python3
"""
classer.py - Range les fiches resumees dans une arborescence de themes :
    domaine  >  theme  >  fiches

Premier lancement : Claude lit les titres et mots-cles de TOUTES les fiches
et en deduit une arborescence (rien n'est predefini : tu decouvres ce que tu
sauvegardes vraiment). Puis chaque fiche est rangee dans 1 ou 2 themes.

Lancements suivants : l'arborescence est conservee, seules les nouvelles
fiches sont rangees dedans. `--refaire` reconstruit tout depuis zero (utile
quand la base a beaucoup grossi).

Resultat : taxonomie.json

Usage :
    python classer.py
    python classer.py --refaire
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from commun import (CONSO, DOSSIER_PROJET, MODELE_DEFAUT, appeler_claude,
                    charger_json, sauver_json)

# construire l'arborescence demande du recul : un seul appel, sur un modele
# plus capable. Ranger les fiches dedans est simple : modele leger.
MODELE_ARBORESCENCE = "sonnet"

FICHES_PAR_APPEL = 120
NON_CLASSE = "Non classé"

SYSTEME_ARBO = """Tu organises le "second cerveau" de Thomas : une base de Reels
Instagram/TikTok qu'il a sauvegardes. On te donne une ligne par fiche
(titre, mots-cles, format). Construis une arborescence a deux niveaux qui
reflete ce qu'il sauvegarde VRAIMENT :

- 6 a 12 "domaines" larges (ex. "Vélo & cyclisme", "Tech & logiciels").
- Dans chaque domaine, 2 a 7 "themes" precis, chacun assez gros pour
  regrouper plusieurs fiches (vise au moins 4 fiches par theme ; pas de theme
  pour une fiche isolee).
- Noms courts en francais, avec majuscule initiale, sans emoji.
- Une description d'une ligne par theme, qui dit ce qu'on y range.
- Pas de domaine fourre-tout du type "Divers" sauf si c'est inevitable."""

SYSTEME_RANGEMENT = """Tu ranges des fiches dans une arborescence de themes
deja definie. Pour chaque fiche, choisis 1 theme (2 au maximum si la fiche
releve vraiment de deux sujets), en utilisant EXACTEMENT les noms de themes
fournis. Renvoie une entree par fiche, avec le meme id."""

SCHEMA_ARBO = {
    "type": "object",
    "properties": {
        "domaines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nom": {"type": "string"},
                    "themes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "nom": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["nom", "description"],
                        },
                    },
                },
                "required": ["nom", "themes"],
            },
        }
    },
    "required": ["domaines"],
}

SCHEMA_RANGEMENT = {
    "type": "object",
    "properties": {
        "affectations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "themes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "themes"],
            },
        }
    },
    "required": ["affectations"],
}


def ligne_fiche(ident, r):
    return f"{ident} | {r['titre']} | {', '.join(r['mots_cles'])} | {r['format']}"


def texte_arborescence(domaines):
    lignes = []
    for d in domaines:
        lignes.append(f"## {d['nom']}")
        lignes += [f"- {t['nom']} : {t['description']}" for t in d["themes"]]
    return "\n".join(lignes)


def construire_arborescence(resumes, modele):
    prompt = "\n".join(ligne_fiche(i, r) for i, r in resumes.items())
    print(f"Construction de l'arborescence a partir de {len(resumes)} fiches...")
    return appeler_claude(prompt, SYSTEME_ARBO, SCHEMA_ARBO, modele=modele)["domaines"]


def ranger_lot(idents, resumes, domaines, modele):
    prompt = (
        "Arborescence :\n" + texte_arborescence(domaines)
        + "\n\nFiches a ranger (id | titre | mots-cles | format) :\n"
        + "\n".join(ligne_fiche(i, resumes[i]) for i in idents)
    )
    rep = appeler_claude(prompt, SYSTEME_RANGEMENT, SCHEMA_RANGEMENT, modele=modele)
    return rep["affectations"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vault", default=str(DOSSIER_PROJET))
    p.add_argument("--modele", default=MODELE_DEFAUT)
    p.add_argument("--modele-arborescence", default=MODELE_ARBORESCENCE)
    p.add_argument("--refaire", action="store_true",
                   help="reconstruire l'arborescence depuis zero")
    args = p.parse_args()

    vault = Path(args.vault)
    resumes = charger_json(vault / "resumes.json", {})
    if not resumes:
        print("resumes.json est vide : lance d'abord resumer.py")
        sys.exit(1)

    chemin = vault / "taxonomie.json"
    taxo = {} if args.refaire else charger_json(chemin, {})

    if not taxo.get("domaines"):
        taxo = {"domaines": construire_arborescence(resumes, args.modele_arborescence),
                "affectations": {}}
        sauver_json(chemin, taxo)

    themes_valides = {t["nom"] for d in taxo["domaines"] for t in d["themes"]}
    a_ranger = [i for i in resumes if i not in taxo["affectations"]]
    print(f"{len(themes_valides)} themes, {len(a_ranger)} fiches a ranger.")

    lots = [a_ranger[i:i + FICHES_PAR_APPEL] for i in range(0, len(a_ranger), FICHES_PAR_APPEL)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        resultats = pool.map(lambda lot: ranger_lot(lot, resumes, taxo["domaines"], args.modele), lots)
        for lot, affectations in zip(lots, resultats):
            recus = {a["id"]: a["themes"] for a in affectations}
            for ident in lot:
                themes = [t for t in recus.get(ident, []) if t in themes_valides][:2]
                taxo["affectations"][ident] = themes or [NON_CLASSE]
            sauver_json(chemin, taxo)

    # bilan
    compte = {}
    for themes in taxo["affectations"].values():
        for t in themes:
            compte[t] = compte.get(t, 0) + 1
    for d in taxo["domaines"]:
        total = sum(compte.get(t["nom"], 0) for t in d["themes"])
        print(f"\n{d['nom']} ({total})")
        for t in d["themes"]:
            print(f"   {compte.get(t['nom'], 0):4d}  {t['nom']}")
    if compte.get(NON_CLASSE):
        print(f"\n{compte[NON_CLASSE]} fiche(s) non classee(s)")
    print(f"\nConsommation : {CONSO['appels']} appels, {CONSO['entree'] + CONSO['cache']:,} tokens "
          f"en entree, {CONSO['sortie']:,} en sortie")
    print("Etape suivante : python construire.py")


if __name__ == "__main__":
    main()

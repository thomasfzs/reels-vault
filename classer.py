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

from commun import (CONSO, DOSSIER_PROJET, MODELE_DEFAUT, afficher_estimation,
                    appeler_claude, charger_json, demander_accord, sauver_json)

# construire l'arborescence demande du recul : un seul appel, sur un modele
# plus capable. Ranger les fiches dedans est simple : modele leger.
MODELE_ARBORESCENCE = "sonnet"

FICHES_PAR_APPEL = 120
NON_CLASSE = "Non classé"

# pour l'estimation, d'apres les mesures de conso.jsonl
CARACTERES_PAR_TOKEN = 2
TOKENS_FIXES_PAR_APPEL = 600
TOKENS_SORTIE_PAR_FICHE = 110
TOKENS_SORTIE_ARBORESCENCE = 2500

SYSTEME_ARBO = """Tu organises un "second cerveau" personnel : une base de Reels
Instagram/TikTok sauvegardes par une personne. On te donne une ligne par fiche
(titre, mots-cles, format). Construis une arborescence a deux niveaux qui
reflete ce qu'elle sauvegarde VRAIMENT :

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
fournis. Renvoie une entree par fiche, avec le meme id.

Prefere TOUJOURS un theme existant, meme approximatif. Seulement si une fiche
ne rentre vraiment dans aucun, tu peux creer un nouveau theme : declare-le
dans "nouveaux_themes" (nom court en francais, description d'une ligne, et le
domaine ou le ranger, existant de preference, ou nouveau si aucun ne
convient), puis utilise son nom pour la fiche. Ne cree pas deux themes pour
le meme sujet."""

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
        },
        "nouveaux_themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "domaine": {"type": "string"},
                    "nom": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["domaine", "nom", "description"],
            },
        },
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


def prompt_arborescence(resumes):
    return "\n".join(ligne_fiche(i, r) for i, r in resumes.items())


def construire_arborescence(resumes, modele):
    print(f"Construction de l'arborescence a partir de {len(resumes)} fiches...")
    return appeler_claude(prompt_arborescence(resumes), SYSTEME_ARBO, SCHEMA_ARBO,
                          modele=modele)["domaines"]


def prompt_rangement(idents, resumes, domaines):
    return (
        "Arborescence :\n" + texte_arborescence(domaines)
        + "\n\nFiches a ranger (id | titre | mots-cles | format) :\n"
        + "\n".join(ligne_fiche(i, resumes[i]) for i in idents)
    )


def ranger_lot(idents, resumes, domaines, modele):
    rep = appeler_claude(prompt_rangement(idents, resumes, domaines),
                         SYSTEME_RANGEMENT, SCHEMA_RANGEMENT, modele=modele)
    return rep["affectations"], rep.get("nouveaux_themes", [])


def ajouter_theme(domaines, proposition):
    """Ajoute un theme propose par Claude (et son domaine s'il est nouveau).
    Renvoie True s'il a vraiment ete cree."""
    nom = proposition["nom"].strip()
    if not nom or any(t["nom"] == nom for d in domaines for t in d["themes"]):
        return False
    domaine = next((d for d in domaines if d["nom"] == proposition["domaine"].strip()), None)
    if domaine is None:
        domaine = {"nom": proposition["domaine"].strip(), "themes": []}
        domaines.append(domaine)
    domaine["themes"].append({"nom": nom, "description": proposition["description"].strip()})
    return True


def estimer(resumes, taxo, a_ranger):
    """Estime les tokens sans rien envoyer. Renvoie (appels, entree, sortie)."""
    appels = entree = sortie = 0
    domaines = taxo.get("domaines") or []
    if not domaines:  # premier lancement : l'arborescence est a construire
        appels += 1
        entree += TOKENS_FIXES_PAR_APPEL + len(prompt_arborescence(resumes)) // CARACTERES_PAR_TOKEN
        sortie += TOKENS_SORTIE_ARBORESCENCE
        domaines = [{"nom": "x" * 30, "themes": [{"nom": "x" * 30, "description": "x" * 80}] * 4}] * 10
    for i in range(0, len(a_ranger), FICHES_PAR_APPEL):
        lot = a_ranger[i:i + FICHES_PAR_APPEL]
        appels += 1
        entree += TOKENS_FIXES_PAR_APPEL + len(prompt_rangement(lot, resumes, domaines)) // CARACTERES_PAR_TOKEN
        sortie += TOKENS_SORTIE_PAR_FICHE * len(lot)
    return appels, entree, sortie


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vault", default=str(DOSSIER_PROJET))
    p.add_argument("--modele", default=MODELE_DEFAUT)
    p.add_argument("--modele-arborescence", default=MODELE_ARBORESCENCE)
    p.add_argument("--refaire", action="store_true",
                   help="reconstruire l'arborescence depuis zero")
    p.add_argument("--oui", action="store_true",
                   help="ne pas demander de confirmation avant d'appeler Claude")
    args = p.parse_args()

    vault = Path(args.vault)
    resumes = charger_json(vault / "resumes.json", {})
    if not resumes:
        print("resumes.json est vide : lance d'abord resumer.py")
        sys.exit(1)

    chemin = vault / "taxonomie.json"
    taxo = {} if args.refaire else charger_json(chemin, {})

    a_ranger = [i for i in resumes if i not in taxo.get("affectations", {})]
    if taxo.get("domaines") and not a_ranger:
        print("Toutes les fiches sont deja rangees.")
        return

    appels, entree, sortie = estimer(resumes, taxo, a_ranger)
    if not taxo.get("domaines"):
        print(f"Premier classement : Claude ({args.modele_arborescence}) va inventer "
              f"l'arborescence, puis ranger les {len(a_ranger)} fiches.")
    else:
        print(f"{len(a_ranger)} fiche(s) a ranger dans les themes existants.")
    afficher_estimation(appels, entree, sortie, args.modele)
    if not demander_accord("Lancer le classement ?", args.oui):
        print("Rien n'a ete envoye. Relance quand tu veux : on reprendra ici.")
        return

    if not taxo.get("domaines"):
        taxo = {"domaines": construire_arborescence(resumes, args.modele_arborescence),
                "affectations": {}}
        sauver_json(chemin, taxo)

    print(f"Rangement de {len(a_ranger)} fiche(s)...")
    crees = []
    lots = [a_ranger[i:i + FICHES_PAR_APPEL] for i in range(0, len(a_ranger), FICHES_PAR_APPEL)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        resultats = pool.map(lambda lot: ranger_lot(lot, resumes, taxo["domaines"], args.modele), lots)
        for lot, (affectations, nouveaux) in zip(lots, resultats):
            for proposition in nouveaux:
                if ajouter_theme(taxo["domaines"], proposition):
                    crees.append(f"{proposition['nom']} (dans {proposition['domaine']})")
            themes_valides = {t["nom"] for d in taxo["domaines"] for t in d["themes"]}
            recus = {a["id"]: a["themes"] for a in affectations}
            for ident in lot:
                themes = [t for t in recus.get(ident, []) if t in themes_valides][:2]
                taxo["affectations"][ident] = themes or [NON_CLASSE]
            sauver_json(chemin, taxo)
    if crees:
        print("\nNouveaux themes crees : " + " ; ".join(crees))

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

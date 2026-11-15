#!/usr/bin/env python3
"""
construire.py - Genere tout ce qu'on consulte, a partir de resumes.json et
taxonomie.json. Aucun appel a Claude ici : c'est du templating pur, instantane.

Produit :
  - index.md    : le catalogue compact (une ligne par video), range par
                  domaine > theme. Claude le lit en premier pour s'orienter.
  - vault.html  : page autonome hors ligne (recherche + filtres), a ouvrir
                  d'un double-clic, lisible sur telephone.
  - fiches/     : une note Obsidian par video (resume, infos, images, lien).
  - themes/     : une note par domaine et par theme, qui relie les fiches
                  (c'est ce qui dessine le graphe dans Obsidian).

fiches/ et themes/ sont entierement regeneres a chaque lancement :
n'y ecris pas de notes perso, elles seraient effacees.

Usage :
    python construire.py
"""

import argparse
import html
import json
import re
import shutil
from collections import defaultdict
from datetime import date
from pathlib import Path

from commun import DOSSIER_PROJET, charger_json

NON_CLASSE = "Non classé"


def nom_de_fichier(texte, max_long=90):
    texte = re.sub(r'[\\/:*?"<>|\[\]#^]', " ", texte)
    texte = re.sub(r"\s+", " ", texte).strip(" .")
    return texte[:max_long].rstrip(" .") or "sans titre"


def charger(vault):
    resumes = charger_json(vault / "resumes.json", {})
    taxo = charger_json(vault / "taxonomie.json", {"domaines": [], "affectations": {}})
    domaine_de = {t["nom"]: d["nom"] for d in taxo["domaines"] for t in d["themes"]}
    description_de = {t["nom"]: t["description"] for d in taxo["domaines"] for t in d["themes"]}

    fiches = []
    noms_pris = set()
    for ident, r in resumes.items():
        themes = taxo["affectations"].get(ident) or [NON_CLASSE]
        nom = nom_de_fichier(r["titre"])
        base, n = nom, 2
        while nom.lower() in noms_pris:
            nom, n = f"{base} ({n})", n + 1
        noms_pris.add(nom.lower())
        fiches.append({
            **r,
            "id": ident,
            "note": nom,
            "themes": themes,
            "domaines": sorted({domaine_de.get(t, NON_CLASSE) for t in themes}),
        })
    fiches.sort(key=lambda f: f["titre"].lower())

    # arborescence ordonnee, avec "Non classe" a la fin si besoin
    arbo = [(d["nom"], [t["nom"] for t in d["themes"]]) for d in taxo["domaines"]]
    if any(NON_CLASSE in f["themes"] for f in fiches):
        arbo.append((NON_CLASSE, [NON_CLASSE]))
        domaine_de[NON_CLASSE] = NON_CLASSE
        description_de[NON_CLASSE] = "Fiches pas encore rangées (relance classer.py)."
    return fiches, arbo, description_de


# ---------------------------------------------------------------- index.md

def ecrire_index(vault, fiches, arbo, description_de):
    par_theme = defaultdict(list)
    for f in fiches:
        par_theme[f["themes"][0]].append(f)  # theme principal seulement : pas de doublon

    lignes = [
        "# Index du Vault",
        "",
        f"{len(fiches)} vidéos sauvegardées, rangées par domaine puis par thème. "
        f"Généré le {date.today():%d/%m/%Y} par construire.py — ne pas modifier à la main.",
        "",
        "Une ligne par vidéo : titre · mots-clés · format · fiche détaillée (dans fiches/). "
        "Le résumé complet et les infos concrètes sont dans la fiche.",
        "",
    ]
    for domaine, themes in arbo:
        lignes += [f"## {domaine}", ""]
        for t in themes:
            liste = par_theme.get(t, [])
            if not liste:
                continue
            lignes += [f"### {t} ({len(liste)})", f"_{description_de.get(t, '')}_", ""]
            for f in liste:
                lignes.append(
                    f"- {f['titre']} · {', '.join(f['mots_cles'])} · {f['format']}"
                    + ("" if f["exploitable"] else " (pauvre)")
                    + f" · `{f['note']}.md`"
                )
            lignes.append("")
    (vault / "index.md").write_text("\n".join(lignes), encoding="utf-8")


# ---------------------------------------------------------------- Obsidian

def ecrire_obsidian(vault, fiches, arbo, description_de):
    for dossier in ("fiches", "themes"):
        if (vault / dossier).exists():
            shutil.rmtree(vault / dossier)
    (vault / "fiches").mkdir()

    for f in fiches:
        yaml_liste = lambda xs: "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in xs) + "]"
        lignes = [
            "---",
            f"titre: {json.dumps(f['titre'], ensure_ascii=False)}",
            f"lien: {f['lien']}",
            f"auteur: {json.dumps(f['auteur'], ensure_ascii=False)}",
            f"format: {f['format']}",
            f"domaines: {yaml_liste(f['domaines'])}",
            f"themes: {yaml_liste(f['themes'])}",
            f"mots_cles: {yaml_liste(f['mots_cles'])}",
            f"id: {f['id']}",
            "---",
            "",
            f"# {f['titre']}",
            "",
            f["resume"],
            "",
        ]
        if f["infos"]:
            lignes += ["## À retenir", ""] + [f"- {i}" for i in f["infos"]] + [""]
        lignes += [
            "## Liens",
            "",
            "Thèmes : " + " · ".join(f"[[{t}]]" for t in f["themes"]),
            "",
            f"[Voir le post sur {f['plateforme']}]({f['lien']}) · fiche brute : [[{f['id']}]]",
            "",
        ]
        if f["images"]:
            lignes += ["## Images", ""] + [f"![[{p}|240]]" for p in f["images"][:3]] + [""]
        (vault / "fiches" / f"{f['note']}.md").write_text("\n".join(lignes), encoding="utf-8")

    par_theme = defaultdict(list)
    for f in fiches:
        for t in f["themes"]:
            par_theme[t].append(f)

    for domaine, themes in arbo:
        dossier = vault / "themes" / nom_de_fichier(domaine)
        dossier.mkdir(parents=True, exist_ok=True)
        total = sum(len(par_theme.get(t, [])) for t in themes)
        lignes = [f"# {domaine}", "", f"{total} fiches.", ""]
        lignes += [f"- [[{nom_de_fichier(t)}|{t}]] ({len(par_theme.get(t, []))})" for t in themes]
        (dossier / f"{nom_de_fichier(domaine)} (domaine).md").write_text(
            "\n".join(lignes) + "\n", encoding="utf-8")

        for t in themes:
            liste = par_theme.get(t, [])
            lignes = [f"# {t}", "", f"_{description_de.get(t, '')}_", "",
                      f"Domaine : [[{nom_de_fichier(domaine)} (domaine)|{domaine}]] · {len(liste)} fiches.", ""]
            lignes += [f"- [[{f['note']}]]" for f in liste]
            (dossier / f"{nom_de_fichier(t)}.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- vault.html

def ecrire_html(vault, fiches, arbo):
    donnees = [{
        "t": f["titre"], "r": f["resume"], "i": f["infos"], "a": f["auteur"],
        "l": f["lien"], "f": f["format"], "th": f["themes"], "k": f["mots_cles"],
        "img": f["images"][0] if f["images"] else "", "x": f["exploitable"],
    } for f in fiches]
    gabarit = (DOSSIER_PROJET / "gabarit_vault.html").read_text(encoding="utf-8")
    page = (gabarit
            .replace("__DONNEES__", json.dumps(donnees, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__ARBO__", json.dumps(arbo, ensure_ascii=False))
            .replace("__TOTAL__", str(len(fiches)))
            .replace("__DATE__", html.escape(f"{date.today():%d/%m/%Y}")))
    (vault / "vault.html").write_text(page, encoding="utf-8")


# ---------------------------------------------------------------- reglages Obsidian

COULEURS_DOMAINES = [0xE07A5A, 0x4CC3A3, 0x6EA8FE, 0xE5B84B, 0xB57EDC,
                     0xEF6F9A, 0x58B8D6, 0x9BC45B, 0xD98E4A, 0x8D9AA8]


def regler_obsidian(vault, arbo):
    """Prepare le coffre Obsidian : le graphe ne montre que fiches/ et themes/
    (une couleur par domaine), et les dossiers techniques sont masques.
    Seuls ces reglages-la sont modifies, le reste de ta config est garde."""
    dossier = vault / ".obsidian"
    dossier.mkdir(exist_ok=True)

    graphe = charger_json(dossier / "graph.json", {})
    graphe["search"] = "path:fiches OR path:themes"
    graphe["colorGroups"] = [
        {"query": f'path:"themes/{nom_de_fichier(d)}" OR [domaines:"{d}"]',
         "color": {"a": 1, "rgb": COULEURS_DOMAINES[i % len(COULEURS_DOMAINES)]}}
        for i, (d, _) in enumerate(arbo)
    ]
    (dossier / "graph.json").write_text(json.dumps(graphe, indent=2), encoding="utf-8")

    appli = charger_json(dossier / "app.json", {})
    filtres = set(appli.get("userIgnoreFilters", []))
    filtres |= {"_ancien/", ".venv/", ".temp/"}
    appli["userIgnoreFilters"] = sorted(filtres)
    (dossier / "app.json").write_text(json.dumps(appli, indent=2), encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vault", default=str(DOSSIER_PROJET))
    args = p.parse_args()
    vault = Path(args.vault)

    fiches, arbo, description_de = charger(vault)
    if not fiches:
        print("resumes.json est vide : lance d'abord resumer.py puis classer.py")
        return
    ecrire_index(vault, fiches, arbo, description_de)
    ecrire_obsidian(vault, fiches, arbo, description_de)
    ecrire_html(vault, fiches, arbo)
    regler_obsidian(vault, arbo)
    print(f"{len(fiches)} fiches -> index.md, vault.html, fiches/, themes/")
    print(f"Obsidian : ouvre le dossier {vault.resolve()} comme coffre, puis Ctrl+G pour le graphe.")


if __name__ == "__main__":
    main()

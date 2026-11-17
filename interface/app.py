#!/usr/bin/env python3
"""
interface/app.py - La fenetre de Reels Vault : une bulle par etape, et tu
fais avancer le flux toi-meme, etape par etape.

    .venv/bin/python interface/app.py          (ou double-clic sur le lanceur)
    .venv/bin/python interface/app.py --debug  (ouvre aussi l'inspecteur web)

Comment c'est construit
-----------------------
- pywebview ouvre une fenetre d'appli qui affiche une page web locale
  (index.html + app.js + style.css, dans ce dossier).
- La page appelle les methodes de la classe `Api` ci-dessous comme des
  fonctions JavaScript : `window.pywebview.api.etat()`, `.lancer("resumer")`...
- Dans l'autre sens, Python envoie des evenements a la page avec
  `fenetre.evaluate_js("recevoir({...})")` : debut / fin d'une etape,
  progression, et les "particules" qui glissent sur les fils.

Les scripts du projet restent le moteur et ne sont pas modifies :
- les estimations reutilisent leurs propres fonctions (`estimer()` de
  resumer.py et classer.py, `chercher_nouveaux()` de mettre_a_jour.py) ;
- quand tu valides dans la fenetre, le script est lance avec `--oui` (c'est
  la fenetre qui a pose la question, plus besoin du terminal) ;
- ce qui circule sur les fils, on le voit en surveillant ce que les scripts
  produisent deja : nouveaux fichiers dans raw/, nouvelles entrees dans
  resumes.json et taxonomie.json.
"""

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

import webview

# le dossier du projet (un cran au-dessus de interface/), pour importer les scripts
DOSSIER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DOSSIER))

import classer  # noqa: E402
import mettre_a_jour  # noqa: E402
import resumer  # noqa: E402
from commun import (charger_json, image_reduite_base64,  # noqa: E402
                    lire_fiche_brute, lire_toutes_les_fiches, sauver_json)

# liens trouves a l'etape 1, en attente de recolte (garde entre deux lancements)
FILE_ATTENTE = DOSSIER / ".a_recolter.txt"
ORDRE = ["chercher", "recolter", "resumer", "classer", "construire", "vault"]
MAX_ENREGISTRES = 60
MAX_PARTICULES_RAFALE = 40  # au-dela, on n'anime qu'un echantillon


# ---------------------------------------------------------------- etat du vault

def lire_attente():
    if not FILE_ATTENTE.exists():
        return []
    return [l.strip() for l in FILE_ATTENTE.read_text(encoding="utf-8").splitlines() if l.strip()]


def nettoyer_attente():
    """Retire de la file les liens deja recoltes (ou definitivement en echec).
    Meme comparaison que mettre_a_jour.py : le code du post dans l'URL."""
    journal = charger_json(DOSSIER / "journal.json", {})
    faits = {mettre_a_jour.identifiant(l) for l, v in journal.items()
             if v.get("statut") in ("ok", "echec")}
    reste = [l for l in lire_attente() if mettre_a_jour.identifiant(l) not in faits]
    if reste:
        FILE_ATTENTE.write_text("\n".join(reste) + "\n", encoding="utf-8")
    else:
        FILE_ATTENTE.unlink(missing_ok=True)
    return reste


def calculer_etat():
    """Tout ce que la page affiche sur les bulles. Rien n'est envoye a Claude :
    les estimations sont calculees en local avec les fonctions des scripts."""
    config = charger_json(DOSSIER / "config.json", {})
    journal = charger_json(DOSSIER / "journal.json", {})
    resumes = charger_json(DOSSIER / "resumes.json", {})
    taxo = charger_json(DOSSIER / "taxonomie.json", {})
    attente = nettoyer_attente()

    # etape 3 : memes calculs que resumer.py, sans rien envoyer
    toutes = lire_toutes_les_fiches(DOSSIER)
    a_resumer = [f for f in toutes if f["id"] not in resumes]
    lots = [a_resumer[i:i + resumer.FICHES_PAR_APPEL]
            for i in range(0, len(a_resumer), resumer.FICHES_PAR_APPEL)]
    entree_r, sortie_r = resumer.estimer(lots, DOSSIER, "vision")
    images_r = sum(len(resumer.images_a_lire(f)) for f in a_resumer)

    # etape 4 : memes calculs que classer.py
    a_classer = [i for i in resumes if i not in taxo.get("affectations", {})]
    if a_classer or (resumes and not taxo.get("domaines")):
        appels_c, entree_c, sortie_c = classer.estimer(resumes, taxo, a_classer)
    else:
        appels_c = entree_c = sortie_c = 0

    # mode auto : on ne connait pas encore les reels qui seront trouves, donc
    # on donne un cout moyen par reel, estime sur les 100 dernieres fiches
    echantillon = toutes[-100:]
    if echantillon:
        e, s_ = resumer.estimer([echantillon[i:i + resumer.FICHES_PAR_APPEL]
                                 for i in range(0, len(echantillon), resumer.FICHES_PAR_APPEL)],
                                DOSSIER, "vision")
        par_reel_resumer = (e + s_) // len(echantillon)
    else:
        par_reel_resumer = 3000
    par_reel_classer = classer.TOKENS_SORTIE_PAR_FICHE + 60  # une ligne par fiche dans le prompt

    # etape 5 : a refaire si les donnees sont plus recentes que index.md
    index = DOSSIER / "index.md"
    sources = [DOSSIER / "resumes.json", DOSSIER / "taxonomie.json"]
    date_index = index.stat().st_mtime if index.exists() else 0
    a_construire = any(s.exists() and s.stat().st_mtime > date_index for s in sources)

    raw = DOSSIER / "raw"
    fiches = DOSSIER / "fiches"
    return {
        "config": {"compte": config.get("compte", ""), "cookies": config.get("cookies", "")},
        "chercher": {"max": MAX_ENREGISTRES},
        "recolter": {
            "attente": len(attente),
            "minutes": max(1, len(attente) * mettre_a_jour.SECONDES_PAR_REEL // 60) if attente else 0,
            "echecs": sum(1 for v in journal.values() if v.get("statut") == "echec"),
        },
        "resumer": {
            "a_faire": len(a_resumer), "appels": len(lots), "images": images_r,
            "entree": entree_r, "sortie": sortie_r, "modele": resumer.MODELE_DEFAUT,
        },
        "classer": {
            "a_faire": len(a_classer), "appels": appels_c, "entree": entree_c,
            "sortie": sortie_c, "modele": classer.MODELE_DEFAUT,
            "premiere_fois": bool(resumes) and not taxo.get("domaines"),
            "modele_arborescence": classer.MODELE_ARBORESCENCE,
        },
        "construire": {"a_faire": a_construire, "jamais": not index.exists()},
        "auto": {"par_reel": par_reel_resumer + par_reel_classer,
                 "secondes_par_reel": mettre_a_jour.SECONDES_PAR_REEL},
        "vault": {
            "reels": len(list(fiches.glob("*.md"))) if fiches.exists() else 0,
            "recoltes": len(list(raw.glob("*.md"))) if raw.exists() else 0,
            "domaines": len(taxo.get("domaines") or []),
            "themes": sum(len(d.get("themes", [])) for d in taxo.get("domaines") or []),
        },
    }


# ---------------------------------------------------------------- Obsidian

def obsidian_installe():
    """Obsidian est-il installe ? (on regarde ou il s'installe selon le systeme)"""
    if sys.platform.startswith("linux"):
        if shutil.which("obsidian"):
            return True
        if shutil.which("flatpak") and subprocess.run(
                ["flatpak", "info", "md.obsidian.Obsidian"], capture_output=True).returncode == 0:
            return True
        r = subprocess.run(["xdg-mime", "query", "default", "x-scheme-handler/obsidian"],
                           capture_output=True, text=True) if shutil.which("xdg-mime") else None
        return bool(r and r.stdout.strip())
    if sys.platform == "darwin":
        return any(Path(d, "Obsidian.app").exists() for d in ("/Applications", Path.home() / "Applications"))
    if os.name == "nt":
        try:
            import winreg
            winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "obsidian").Close()
            return True
        except OSError:
            return Path(os.environ.get("LOCALAPPDATA", ""), "Programs", "Obsidian", "Obsidian.exe").exists()
    return False


def fichier_config_obsidian():
    """obsidian.json : la liste des coffres connus d'Obsidian."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", ""), "obsidian", "obsidian.json")
    flatpak = Path.home() / ".var/app/md.obsidian.Obsidian/config/obsidian/obsidian.json"
    if flatpak.exists():
        return flatpak
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"), "obsidian", "obsidian.json")


def enregistrer_coffre():
    """Ajoute ce dossier a la liste des coffres d'Obsidian s'il n'y est pas :
    sans ca, Obsidian ne saurait pas ouvrir le lien obsidian://open?path=..."""
    chemin = fichier_config_obsidian()
    try:
        config = charger_json(chemin, {})
        coffres = config.setdefault("vaults", {})
        if any(Path(v.get("path", "")) == DOSSIER for v in coffres.values()):
            return
        coffres[os.urandom(8).hex()] = {"path": str(DOSSIER), "ts": int(time.time() * 1000)}
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(config), encoding="utf-8")
    except (OSError, ValueError):
        pass  # au pire, Obsidian proposera de choisir le dossier


def ouvrir_url(url):
    """Ouvre un lien avec l'appli prevue par le systeme (ici : Obsidian)."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", url])
    elif os.name == "nt":
        os.startfile(url)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- surveillance

def vignette(chemin_relatif):
    """Petite image (96 px) en base64, pour l'afficher sur un fil."""
    if not chemin_relatif:
        return None
    chemin = DOSSIER / chemin_relatif
    if not chemin.is_file():
        return None
    try:
        return "data:image/jpeg;base64," + image_reduite_base64(chemin, largeur=96)
    except Exception:  # noqa: BLE001 - une vignette ratee n'est pas grave
        return None


class Surveillant:
    """Pendant qu'une etape tourne, regarde toutes les ~0,7 s ce qui est apparu
    dans raw/, resumes.json et taxonomie.json, et envoie une particule pour
    chaque nouveaute. C'est ce qu'on voit passer d'une bulle a l'autre."""

    def __init__(self, envoyer):
        self.envoyer = envoyer
        self.actif = False
        self.photo()

    def photo(self):
        raw = DOSSIER / "raw"
        self.raw = {p.name for p in raw.glob("*.md")} if raw.exists() else set()
        self.resumes = set(charger_json(DOSSIER / "resumes.json", {}))
        self.classes = set(charger_json(DOSSIER / "taxonomie.json", {}).get("affectations", {}))

    def demarrer(self):
        self.photo()
        self.actif = True
        threading.Thread(target=self._boucle, daemon=True).start()

    def arreter(self):
        self.actif = False
        self._regarder()  # un dernier coup d'oeil, pour ne rien rater

    def _boucle(self):
        while self.actif:
            time.sleep(0.7)
            try:
                self._regarder()
            except (OSError, ValueError):
                pass  # fichier en cours d'ecriture : on regardera au prochain tour

    def _regarder(self):
        # etape 2 -> 3 : un reel recolte (nouvelle fiche dans raw/)
        raw = DOSSIER / "raw"
        if raw.exists():
            for nom in sorted({p.name for p in raw.glob("*.md")} - self.raw):
                self.raw.add(nom)
                fiche = lire_fiche_brute(raw / nom, DOSSIER)
                self.envoyer({"type": "particule", "de": "recolter", "genre": "reel",
                              "label": fiche["titre_brut"],
                              "image": vignette(fiche["images"][0] if fiche["images"] else None)})
        # etape 3 -> 4 : un resume ecrit dans resumes.json
        resumes = charger_json(DOSSIER / "resumes.json", {})
        for ident in [i for i in resumes if i not in self.resumes]:
            self.resumes.add(ident)
            r = resumes[ident]
            self.envoyer({"type": "particule", "de": "resumer", "genre": "resume",
                          "label": r.get("titre", ident),
                          "image": vignette((r.get("images") or [None])[0])})
        # etape 4 -> 5 : une fiche rangee dans un theme
        affectations = charger_json(DOSSIER / "taxonomie.json", {}).get("affectations", {})
        nouvelles = [i for i in affectations if i not in self.classes]
        for ident in nouvelles:
            self.classes.add(ident)
            titre = resumes.get(ident, {}).get("titre", ident)
            self.envoyer({"type": "particule", "de": "classer", "genre": "fiche",
                          "label": f"{titre} → {' · '.join(affectations[ident])}"})
        if nouvelles:
            self.envoyer({"type": "progres", "etape": "classer", "fait": len(nouvelles),
                          "cumul": True})


# ---------------------------------------------------------------- pont avec la page

class Api:
    """Chaque methode publique est appelable depuis la page en JavaScript.
    Elles rendent la main tout de suite : le travail long part dans un fil
    d'execution (thread), et la page est prevenue par des evenements."""

    def __init__(self):
        self.fenetre = None
        self.processus = None
        self.etape_en_cours = None
        self.occupe = False      # une etape (ou la chaine auto) tourne
        self.stop_auto = False
        self.verrou = threading.Lock()
        self.surveillant = Surveillant(self._envoyer)

    # -- envoi d'un evenement a la page
    def _envoyer(self, evenement):
        if self.fenetre:
            try:
                self.fenetre.evaluate_js(f"window.recevoir({json.dumps(evenement)})")
            except Exception:  # noqa: BLE001 - fenetre en train de se fermer
                pass

    def _log(self, texte):
        self._envoyer({"type": "log", "texte": texte})

    # -- lecture
    def etat(self):
        etat = calculer_etat()
        etat["en_cours"] = self.etape_en_cours
        etat["obsidian"] = obsidian_installe()
        etat["systeme"] = sys.platform
        return etat

    # -- reglages (premiere utilisation)
    def sauver_config(self, compte, cookies):
        chemin = DOSSIER / "config.json"
        config = charger_json(chemin, {})
        config["compte"] = compte.strip().lstrip("@")
        config["cookies"] = cookies.strip()
        sauver_json(chemin, config)
        return self.etat()

    def choisir_export(self):
        """Boite de dialogue pour choisir l'export Instagram (.zip ou .json)."""
        choix = self.fenetre.create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=("Export Instagram (*.zip;*.json)", "Tous les fichiers (*.*)"))
        return choix[0] if choix else None

    # -- Obsidian
    def ouvrir_obsidian(self):
        """Clic sur la bulle Vault : ouvre le coffre dans Obsidian."""
        if not obsidian_installe():
            return {"ok": False, "raison": "absent"}
        enregistrer_coffre()
        ouvrir_url("obsidian://open?path=" + quote(str(DOSSIER)))
        return {"ok": True}

    def ouvrir_lien(self, url):
        if url.startswith("https://"):
            webbrowser.open(url)

    # -- lancement : une etape, ou toute la chaine
    def lancer(self, etape, export=None):
        """Lance une seule etape (clic sur sa bulle)."""
        with self.verrou:
            if self.occupe:
                return {"ok": False, "message": "Une etape tourne deja."}
            self.occupe = True
        threading.Thread(target=self._seul, args=(etape, export), daemon=True).start()
        return {"ok": True}

    def lancer_tout(self, export=None):
        """Mode auto : enchaine toutes les etapes qui ont du travail, sans
        redemander (tu as valide une fois, pour toute la chaine)."""
        with self.verrou:
            if self.occupe:
                return {"ok": False, "message": "Une etape tourne deja."}
            self.occupe = True
        self.stop_auto = False
        threading.Thread(target=self._chaine, args=(export,), daemon=True).start()
        return {"ok": True}

    def arreter(self):
        """Arrete le script en cours (et la chaine auto). Sans danger : chaque
        script reprend la ou il s'est arrete au prochain lancement."""
        self.stop_auto = True
        if self.processus and self.processus.poll() is None:
            self._log("Arret demande...")
            self.processus.terminate()
            return True
        return False

    def _seul(self, etape, export):
        try:
            self._executer(etape, export)
        finally:
            self.occupe = False

    def _chaine(self, export):
        self._envoyer({"type": "auto", "actif": True})
        try:
            for etape in ORDRE[:-1]:
                if self.stop_auto:
                    break
                e = calculer_etat()
                rien = {
                    "recolter": not e["recolter"]["attente"],
                    "resumer": not e["resumer"]["a_faire"],
                    "classer": not e["classer"]["a_faire"] and not e["classer"]["premiere_fois"],
                    "construire": not e["construire"]["a_faire"],
                }.get(etape, False)
                if rien:
                    continue  # rien a faire a cette etape : on passe a la suivante
                # meme si une etape echoue (ex. Instagram bloque la recolte),
                # on continue avec ce qui a deja ete fait
                self._executer(etape, export if etape == "chercher" else None)
        finally:
            final = self.etat()
            final["en_cours"] = None
            self._envoyer({"type": "auto", "actif": False, "etat": final})
            self.occupe = False

    def _executer(self, etape, export=None):
        cible = {"chercher": self._chercher, "recolter": self._recolter,
                 "resumer": self._resumer, "classer": self._classer,
                 "construire": self._construire}[etape]
        self.etape_en_cours = etape
        self._envoyer({"type": "debut", "etape": etape})
        self._log(f"── {etape} ──")
        self.surveillant.demarrer()
        code, message = 1, ""
        try:
            code, message = cible(export) if etape == "chercher" else cible()
        except Exception as e:  # noqa: BLE001
            code, message = 1, f"Erreur : {e}"
            self._log(message)
        finally:
            self.surveillant.arreter()
            self.processus = None
        final = calculer_etat()
        final["en_cours"] = None
        self._envoyer({"type": "fin", "etape": etape, "code": code, "message": message,
                       "etat": final})
        self.etape_en_cours = None

    def _script(self, nom, *args, progression=None):
        """Lance un script du projet et lit sa sortie ligne par ligne :
        chaque ligne part dans le journal de la page, et `progression`
        (une fonction) peut en tirer un "3 sur 12"."""
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.processus = subprocess.Popen(
            [sys.executable, str(DOSSIER / nom), *args], cwd=DOSSIER, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, **options)
        for ligne in self.processus.stdout:
            ligne = ligne.rstrip()
            if not ligne:
                continue
            self._log(ligne)
            if progression:
                progression(ligne)
        return self.processus.wait()

    # -- les 5 etapes
    def _chercher(self, export):
        """Etape 1 : on appelle directement chercher_nouveaux() de
        mettre_a_jour.py, puis on met les nouveaux liens en file d'attente
        devant Recolter. Rien d'autre ne se lance."""
        config = charger_json(DOSSIER / "config.json", {})
        if not config.get("compte") and not export:
            return 1, "Indique d'abord ton pseudo Instagram."
        args = argparse.Namespace(export=export, max=MAX_ENREGISTRES, retenter_echecs=False)
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):  # ses print() vont dans le journal
            nouveaux = mettre_a_jour.chercher_nouveaux(config, args)
        for ligne in sortie.getvalue().splitlines():
            if ligne.strip():
                self._log(ligne)
        attente = lire_attente()
        ajoutes = [l for l in nouveaux if l not in attente]
        if attente or ajoutes:
            FILE_ATTENTE.write_text("\n".join(attente + ajoutes) + "\n", encoding="utf-8")
        # les liens trouves glissent vers Recolter
        for lien in ajoutes[:MAX_PARTICULES_RAFALE]:
            court = re.sub(r"^https?://(www\.)?", "", lien).split("?")[0]
            self._envoyer({"type": "particule", "de": "chercher", "genre": "lien", "label": court})
        total = len(nettoyer_attente())
        return 0, f"{len(ajoutes)} nouveau(x) reel(s) trouve(s) · {total} en attente de recolte"

    def _recolter(self):
        if not lire_attente():
            return 0, "Rien a recolter : lance d'abord Chercher."
        config = charger_json(DOSSIER / "config.json", {})
        options = ["--cookies", config["cookies"]] if config.get("cookies") else []

        def progression(ligne):
            m = re.search(r"\[(\d+)/(\d+)\]", ligne)
            if m:
                self._envoyer({"type": "progres", "etape": "recolter",
                               "fait": int(m.group(1)) - 1, "total": int(m.group(2))})

        code = self._script("ingest.py", str(FILE_ATTENTE), *options, progression=progression)
        reste = len(nettoyer_attente())
        if code == mettre_a_jour.CODE_BLOCAGE:
            return code, (f"Instagram bloque ou t'a deconnecte : {reste} reel(s) restent en "
                          "attente. Attends quelques heures avant de relancer.")
        if code != 0:
            return code, f"Recolte interrompue · {reste} reel(s) restent en attente."
        return 0, f"Recolte terminee · {reste} en attente"

    def _resumer(self):
        def progression(ligne):
            m = re.search(r"(\d+)/(\d+) resumees", ligne)
            if m:
                self._envoyer({"type": "progres", "etape": "resumer",
                               "fait": int(m.group(1)), "total": int(m.group(2))})
        code = self._script("resumer.py", "--oui", progression=progression)
        return code, "Resumes termines" if code == 0 else "Resumes interrompus (voir le journal)"

    def _classer(self):
        code = self._script("classer.py", "--oui")
        return code, "Classement termine" if code == 0 else "Classement interrompu (voir le journal)"

    def _construire(self):
        code = self._script("construire.py")
        if code == 0:
            # une rafale de fiches part vers le vault
            n = len(list((DOSSIER / "fiches").glob("*.md")))
            self._envoyer({"type": "rafale", "de": "construire", "genre": "fiche",
                           "nombre": min(n, MAX_PARTICULES_RAFALE)})
        return code, "Vault reconstruit" if code == 0 else "Construction en echec (voir le journal)"


# ---------------------------------------------------------------- programme

def main():
    p = argparse.ArgumentParser(description="Fenetre de Reels Vault")
    p.add_argument("--debug", action="store_true", help="ouvrir l'inspecteur web")
    args = p.parse_args()

    api = Api()
    api.fenetre = webview.create_window(
        "Reels Vault", url=str(Path(__file__).resolve().parent / "index.html"),
        js_api=api, width=1320, height=780, min_size=(900, 560),
        background_color="#0c0e13")
    webview.start(debug=args.debug)


if __name__ == "__main__":
    main()

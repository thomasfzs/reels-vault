# Reels Vault — un second cerveau à partir de tes Reels sauvegardés

Tu as des centaines de Reels Instagram et de TikToks sauvegardés : des outils, des
adresses, des astuces, des idées de voyage. Et tu ne retrouves jamais rien, parce
que tout est enfermé dans des vidéos qu'aucune recherche ne sait lire.

Reels Vault télécharge chaque vidéo, la **transcrit** en local, la fait **résumer
par Claude** (qui lit aussi le texte incrusté dans les images), la **range par
thèmes**, et te donne deux façons de t'en servir :

- **un coffre Obsidian** : une note par vidéo, reliées à leurs thèmes (vue graphe) ;
- **`index.md` + `CLAUDE.md`** : tu poses tes questions à Claude en langage normal
  (« je pars dans les Alpes, ressors-moi tout ce que j'ai gardé »).

> Projet basé sur le tuto [sosoj92/reels-vault](https://github.com/sosoj92/reels-vault)
> (licence MIT). La récolte (`ingest.py`) vient de là. Tout ce qui suit la
> transcription a été réécrit : résumés et classement par Claude Code, arborescence
> de thèmes, coffre Obsidian, interface graphique.

## Démarrage rapide

```bash
git clone https://github.com/thomasfzs/reels-vault.git && cd reels-vault
uv venv --python 3.12 .venv && uv pip install -r requirements.txt

# la première fois : donne-lui l'export Instagram tel quel (le .zip reçu par mail)
.venv/bin/python mettre_a_jour.py --export ~/Downloads/instagram-ton_pseudo-xxxx.zip

# ensuite, pour ajouter tes nouveaux Reels enregistrés :
.venv/bin/python mettre_a_jour.py
```

Il déroule toutes les étapes (récolte, résumés, thèmes, construction) en te
demandant ton accord avant chacune. Pour poser des questions sur tes reels,
ouvre le dossier dans Claude Code et tape `/reels ta question`.

Puis ouvre ce dossier dans Obsidian. Le détail de chaque étape est plus bas.

### Ou avec la fenêtre (interface graphique)

Une bulle par étape (Chercher → Récolter → Résumer → Classer → Construire → Vault).
Chaque bulle montre ce qui attend, avec l'estimation des tokens pour les étapes
Claude. Tu cliques sur une bulle pour lancer l'étape, ou tu la laisses en attente
pour plus tard. Pendant le travail, on voit passer sur les fils ce qui circule :
liens, reels récoltés (avec leur image), résumés, fiches rangées.

Lanceurs (à faire une seule fois, rien à refaire après une modification de l'interface) :

- **Linux** : `bash installer-linux.sh`, puis « Reels Vault » dans le lanceur
  d'applications, ou double-clic sur `Reels Vault.desktop`.
- **Windows** : double-clic sur `Reels Vault.bat`.
- **macOS** : double-clic sur `Reels Vault.command` (la première fois : clic droit > Ouvrir).

Ou directement : `.venv/bin/python interface/app.py`. Le bouton « Démo » rejoue
de faux événements pour voir l'animation sans rien lancer.

---

## Comment ça marche

```
liens (export Instagram, inbox.txt…)
   │
   ▼  ingest.py ─── yt-dlp (vidéo + description) · Whisper (audio → texte) · ffmpeg (3 images)
raw/*.md + images/                       ← une fiche brute par vidéo
   │
   ▼  resumer.py ── Claude : titre, résumé concret, infos à retenir, mots-clés
resumes.json                             (lit les images quand il n'y a pas de voix off)
   │
   ▼  classer.py ── Claude : déduit une arborescence domaine › thème, range chaque fiche
taxonomie.json
   │
   ▼  construire.py ── sans IA, instantané
index.md · fiches/ · themes/  (coffre Obsidian)
```

Chaque étape est **relançable** : elle ne traite que ce qui n'a pas encore été fait.
Tu peux couper avec `Ctrl+C` et relancer la même commande plus tard.

**Coût** : 0 € de plus qu'un abonnement Claude. Les résumés passent par
`claude -p` (Claude Code en mode non interactif), donc par ton abonnement : pas de
clé API. Whisper et yt-dlp tournent en local.

Pour ménager tes quotas, `resumer.py` utilise **Claude Haiku** avec un effort
minimal, traite les fiches par lots de 5 et n'envoie les images (réduites à
512 px, en un seul envoi) que quand le texte ne suffit pas. Chaque appel est noté
dans `conso.jsonl`. À titre indicatif, environ 200 fiches coûtent l'équivalent de 1 à 2 $ au tarif
API. Avec `--images ocr`, les images sont lues en local par tesseract : c'est
encore moins cher, mais nettement moins précis.

---

## Installation

Il te faut Python (3.10 à 3.13), ffmpeg, et [Claude Code](https://claude.com/claude-code)
connecté à ton compte (la commande `claude` doit répondre dans un terminal).

**Linux**

```bash
sudo pacman -S ffmpeg        # ou apt install ffmpeg
uv venv --python 3.12 .venv  # ou python -m venv .venv
uv pip install -r requirements.txt
```

**Windows**

```
winget install Python.Python.3.12 Gyan.FFmpeg
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

---

## Utilisation

### 1. Récupérer ses liens

Instagram : **Paramètres → Centre des comptes → Vos informations et autorisations →
Télécharger vos informations**, format **JSON**. Les fichiers utiles sont
`saved_posts.json` et `saved_collections.json`. N'importe quel fichier texte qui
contient des liens Instagram ou TikTok marche aussi (`inbox.txt`, par exemple).

### 2. Récolter et transcrire

```bash
.venv/bin/python ingest.py saved_posts.json --cookies firefox --limite 10
```

Commence par 10 vidéos, ouvre une fiche dans `raw/` et vérifie la transcription,
puis relance sans `--limite`. Compter 20 à 40 secondes par vidéo. Le premier
lancement télécharge le modèle Whisper (~500 Mo).

### 3. Résumer, classer, construire

```bash
python resumer.py      # Claude résume chaque fiche → resumes.json (estimation + accord)
python classer.py      # Claude range les fiches par thèmes → taxonomie.json (idem)
python construire.py   # génère index.md, fiches/ et themes/
```

`resumer.py --limite 10` pour tester, `--refaire <id>` pour refaire une fiche.
`classer.py --refaire` reconstruit l'arborescence de zéro, ce qui est utile quand la
base a beaucoup grossi.

### 4. Consulter

- **Obsidian** ([obsidian.md](https://obsidian.md), gratuit) : dans la fenêtre, clic sur la bulle **Vault**. Sinon, « Ouvrir un autre coffre » → « Ouvrir un dossier comme coffre »,
  et choisis **ce dossier** (celui du projet). `construire.py` règle le graphe
  (`Ctrl+G`) pour n'afficher que les fiches et les thèmes, avec une couleur par
  domaine. Les notes `fiches/` et `themes/` sont **régénérées** à chaque
  `construire.py` : n'y écris pas de notes perso.
- **Claude, avec le skill `/reels`** : ouvre ce dossier dans Claude Code et pose
  ta question après `/reels`. Claude cherche dans les fiches, répond uniquement
  à partir d'elles et cite chaque fiche avec le lien du post. Par exemple :
  > /reels quels outils open source j'ai gardés pour mon home lab ?
  > /reels organise-moi un week-end vélo avec ce que j'ai sauvegardé sur les Alpes

  Pour l'avoir depuis **n'importe quel dossier**, copie `.claude/skills/reels/`
  dans `~/.claude/skills/` et remplace la ligne « Dossier du vault » par le
  chemin complet de ton vault.

---

## Ajouter ses nouveaux Reels

Une fois la base construite, tu n'as plus besoin de refaire l'export Instagram.
Quand tu en as envie, lance :

```bash
.venv/bin/python mettre_a_jour.py
```

La première fois, il te demande ton pseudo Instagram et le navigateur où tu es
connecté, et les garde dans `config.json`. Pour l'import initial (ou un gros
rattrapage), donne-lui l'export Instagram avec `--export fichier.zip` : il lit
le zip directement, sans que tu aies à le décompresser. Ensuite, il déroule 5 étapes en
t'affichant où il en est :

1. **Chercher** : il lit tes derniers posts **Enregistrés** (60 par défaut)
   directement sur Instagram. gallery-dl ouvre ta page « Enregistrés » avec la
   session de ton navigateur, comme si tu la consultais. Il ajoute les liens de
   `inbox.txt` et te dit combien sont nouveaux.
2. **Récolter** (local, gratuit) : il annonce la durée et te demande si tu veux
   y aller.
3. **Résumer** (Claude) : il estime les tokens et te demande ton accord.
4. **Classer** (Claude) : pareil.
5. **Construire** : il met à jour `index.md` et le coffre Obsidian.

**Si tu refuses une étape, rien n'est perdu** : la fois suivante, il voit ce qui
reste à résumer ou à classer et reprend à cette étape. Rien ne se lance tout seul.
Pour rattraper un gros retard, utilise `--max 300` ; pour ne répondre à aucune
question, `--oui`. Les posts déjà en échec (souvent supprimés) ne sont pas
retentés, sauf avec `--retenter-echecs`.

**Si Instagram bloque** (erreur 429, « patientez », vérification de compte) ou
si tu n'es plus connecté, la récolte **s'arrête immédiatement** au lieu
d'insister. Le post en cours n'est pas compté comme un échec : il sera repris
la fois suivante. Attends quelques heures avant de relancer.

`resumer.py` et `classer.py` affichent aussi leur estimation et demandent ton
accord quand tu les lances seuls.

**Cookies chiffrés** : Chrome, Brave et Edge sous Linux chiffrent leurs cookies
avec une clé rangée dans le trousseau du système. Si yt-dlp affiche
`cannot decrypt v11 cookies`, précise le trousseau : `--cookies "brave+gnomekeyring"`
(ou `+kwallet6` sous KDE). Firefox n'a pas ce problème.

---

## Les pièges connus

1. **Cookies Instagram** : beaucoup de posts ne s'affichent qu'une fois connecté.
   Connecte-toi à instagram.com dans **Firefox**, ferme-le, puis passe
   `--cookies firefox`. Sous Windows, Chrome chiffre ses cookies d'une façon que
   yt-dlp ne sait pas lire (`Failed to decrypt with DPAPI`).
2. **Carrousels** (`/p/…`) : ce sont des photos, pas des vidéos. C'est `gallery-dl`
   qui les récupère, et Claude lit les images.
3. **Posts supprimés** : sur un vieux stock, compte facilement un tiers de pertes.
   Il n'y a rien à faire.
4. **Rythme** : Instagram bloque si on va trop vite. Sur plusieurs centaines de
   posts, mieux vaut des lots de 50 étalés dans le temps.
5. **faster-whisper et PyAV** : selon les versions, le décodeur audio intégré
   plante. `ingest.py` décode donc l'audio avec ffmpeg.

---

## Fichiers

| Fichier | Rôle |
|---|---|
| `ingest.py` | liens → fiches brutes (`raw/`) + images (`images/`) |
| `resumer.py` | fiches brutes → résumés structurés (`resumes.json`) |
| `classer.py` | résumés → arborescence de thèmes (`taxonomie.json`) |
| `construire.py` | → `index.md`, `fiches/`, `themes/` (coffre Obsidian) |
| `mettre_a_jour.py` | lance tout dans l'ordre pour les nouveaux Reels, avec ta validation |
| `interface/` | la fenêtre (pywebview) : `app.py` pilote les scripts, `index.html`/`app.js`/`style.css` dessinent les bulles |
| `installer-linux.sh`, `Reels Vault.bat`, `Reels Vault.command` | lanceurs Linux, Windows, macOS |
| `.claude/skills/reels/` | le skill `/reels` pour interroger le vault avec Claude |
| `commun.py` | lecture des fiches, appel de `claude -p` |
| `CLAUDE.md` | consignes pour interroger la base avec Claude |

Les données (vidéos transcrites, résumés, images) restent sur ta machine et ne
sont pas versionnées (voir `.gitignore`).

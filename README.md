# Reels Vault — un second cerveau à partir de tes Reels sauvegardés

Tu as des centaines de Reels Instagram et de TikToks sauvegardés : des outils, des
adresses, des astuces, des idées de voyage. Et tu ne retrouves jamais rien, parce
que tout est enfermé dans des vidéos qu'aucune recherche ne sait lire.

Reels Vault télécharge chaque vidéo, la **transcrit** en local, la fait **résumer
par Claude** (qui lit aussi le texte incrusté dans les images), la **range par
thèmes**, et te donne trois façons de t'en servir :

- **`vault.html`** : une page hors ligne avec recherche instantanée et filtres par thème ;
- **un coffre Obsidian** : une note par vidéo, reliées à leurs thèmes (vue graphe) ;
- **`index.md` + `CLAUDE.md`** : tu poses tes questions à Claude en langage normal
  (« je pars dans les Alpes, ressors-moi tout ce que j'ai gardé »).

> Projet basé sur le tuto [sosoj92/reels-vault](https://github.com/sosoj92/reels-vault)
> (licence MIT). La récolte (`ingest.py`) vient de là. Tout ce qui suit la
> transcription a été réécrit : résumés et classement par Claude Code, arborescence
> de thèmes, notes Obsidian, nouvelle page de consultation.

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
index.md · vault.html · fiches/ · themes/
```

Chaque étape est **relançable** : elle ne traite que ce qui n'a pas encore été fait.
Tu peux couper avec `Ctrl+C` et relancer la même commande plus tard.

**Coût** : 0 € de plus qu'un abonnement Claude. Les résumés passent par
`claude -p` (Claude Code en mode non interactif), donc par ton abonnement : pas de
clé API. Whisper et yt-dlp tournent en local.

Pour ménager tes quotas, `resumer.py` utilise **Claude Haiku** avec un effort
minimal, traite les fiches par lots de 5 et n'envoie les images (réduites à
512 px, en un seul envoi) que quand le texte ne suffit pas. Chaque appel est noté
dans `conso.jsonl`. Pour 216 fiches, ça a coûté l'équivalent de 1,60 $ au tarif
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
python resumer.py      # Claude résume chaque fiche → resumes.json
python classer.py      # Claude range les fiches par thèmes → taxonomie.json
python construire.py   # génère index.md, vault.html, fiches/ et themes/
```

`resumer.py --limite 10` pour tester, `--refaire <id>` pour refaire une fiche.
`classer.py --refaire` reconstruit l'arborescence de zéro, ce qui est utile quand la
base a beaucoup grossi.

### 4. Consulter

- **`vault.html`** : double-clic, c'est tout. Ça marche hors ligne et sur téléphone.
- **Obsidian** : « Ouvrir un dossier comme coffre » sur ce dossier, puis `Ctrl+G`
  pour le graphe. Les notes `fiches/` et `themes/` sont **régénérées** à chaque
  `construire.py` : n'y écris pas de notes perso.
- **Claude** : ouvre ce dossier dans Claude Code (ou Cowork). `CLAUDE.md` lui dit
  de partir de `index.md` et de ne rien inventer. Par exemple :
  > Quels outils open source j'ai gardés pour mon home lab ?
  > Organise-moi un week-end vélo avec tout ce que j'ai sauvegardé sur les Alpes.

---

## Les pièges connus

1. **Cookies Instagram** : beaucoup de posts ne s'affichent qu'une fois connecté.
   Connecte-toi à instagram.com dans **Firefox**, ferme-le, puis passe
   `--cookies firefox`. Sous Windows, Chrome chiffre ses cookies d'une façon que
   yt-dlp ne sait pas lire (`Failed to decrypt with DPAPI`).
2. **Carrousels** (`/p/…`) : ce sont des photos, pas des vidéos. C'est `gallery-dl`
   qui les récupère, et Claude lit les images.
3. **Posts supprimés** : sur un vieux stock, compte facilement un tiers de pertes
   (ici, 224 sur 791). Il n'y a rien à faire.
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
| `construire.py` | → `index.md`, `vault.html`, `fiches/`, `themes/` |
| `gabarit_vault.html` | modèle de la page de consultation |
| `commun.py` | lecture des fiches, appel de `claude -p` |
| `CLAUDE.md` | consignes pour interroger la base avec Claude |

Les données (vidéos transcrites, résumés, images) restent sur ta machine et ne
sont pas versionnées (voir `.gitignore`).

# Reels Vault — consignes pour Claude

Ce dossier est un « second cerveau » : les Reels Instagram et TikTok
sauvegardés, transcrits et résumés.

## Répondre à une question sur le contenu

- Pour une question précise (un outil, un lieu, un nom), commence par
  chercher le mot dans `fiches/` avec grep : c'est le moins coûteux.
- Pour une question large (« tout ce que j'ai sur la montagne »), lis
  `index.md` : le catalogue compact, une ligne par vidéo, rangé par
  domaine > thème, avec le nom de la fiche détaillée.
- Ouvre ensuite seulement les fiches utiles dans `fiches/` (résumé, infos
  concrètes, lien). `raw/` (transcription brute) en dernier recours : le
  champ `id` de la fiche donne `raw/<id>.md`.
- Ne cite jamais un lieu, un outil, un prix ou un conseil qui ne vient pas
  des fiches. Si rien ne correspond, dis-le simplement.
- Donne le lien du post pour chaque élément cité.
- Réponds en français.

## Pipeline (ne pas modifier les fichiers générés à la main)

1. `ingest.py` : liens → `raw/` + `images/` (yt-dlp, Whisper, ffmpeg)
2. `resumer.py` : `raw/` → `resumes.json` (Claude)
3. `classer.py` : `resumes.json` → `taxonomie.json` (Claude)
4. `construire.py` : → `index.md`, `fiches/`, `themes/` (coffre Obsidian)

Après toute modification de `resumes.json` ou `taxonomie.json`, relancer
`python construire.py`.

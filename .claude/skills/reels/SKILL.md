---
name: reels
description: >
  Répond aux questions sur les Reels Instagram et TikTok enregistrés, à partir
  du Reels Vault (fiches résumées, index, transcriptions). À utiliser pour
  « qu'est-ce que j'ai gardé sur… », « retrouve le reel qui parlait de… »,
  « organise-moi un voyage avec ce que j'ai sauvegardé », ou toute question
  sur le contenu des vidéos enregistrées. Cite toujours les fiches utilisées.
argument-hint: "[ta question sur tes reels enregistrés]"
allowed-tools: Read, Grep, Glob
---

# Interroger le Reels Vault

Question : $ARGUMENTS

**Dossier du vault** : le dossier de ce projet, celui qui contient `index.md`,
`fiches/` et `raw/`.

## Où chercher, du moins coûteux au plus coûteux

1. **`fiches/`** : une note par vidéo (titre, résumé, « À retenir », thèmes,
   lien du post). Pour une question précise (un outil, un lieu, un nom, une
   marque), cherche d'abord avec Grep, sans tenir compte de la casse, dans
   `fiches/`. Essaie plusieurs formulations : synonymes, singulier et pluriel,
   français et anglais (« vélo » / « bike », « randonnée » / « trek »).
2. **`index.md`** : le catalogue compact, une ligne par vidéo, rangé par
   domaine › thème. Lis-le pour une question large (« tout ce que j'ai sur la
   montagne ») ou quand Grep ne donne rien : les thèmes aident à repérer les
   bonnes fiches.
3. **`raw/<id>.md`** : la description et la transcription complètes. Ne les
   ouvre que si la fiche ne suffit pas (un détail précis, une citation). Le
   champ `id` en haut de la fiche donne le nom du fichier.

N'ouvre que les fiches utiles. Ne lis pas tout le dossier.

## Comment répondre

- Réponds **uniquement** à partir des fiches. N'ajoute aucun lieu, outil, prix
  ou conseil qui n'y figure pas. Si tu complètes avec tes connaissances
  générales, dis-le clairement et sépare-le.
- **Cite chaque fiche utilisée** : son titre, le lien du post et le nom du
  fichier, par exemple :
  > Raspberry Pi Zero + PiKVM pour contrôler son PC à distance —
  > https://www.instagram.com/reel/Da3t9g5Tn5e/ · `fiches/Raspberry Pi Zero + PiKVM pour contrôler son PC à distance.md`
- Si plusieurs fiches se recoupent, regroupe-les. Si elles se contredisent,
  dis-le.
- Si rien ne correspond, dis simplement que rien d'enregistré ne parle de ce
  sujet, et propose les thèmes les plus proches tirés de `index.md`.
- Les fiches marquées « (pauvre) » dans l'index ont peu de contenu : signale-le
  si tu t'appuies dessus.
- Réponds dans la langue de la question.

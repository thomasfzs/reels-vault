/*
 * app.js - Les bulles, les fils et ce qui circule dessus.
 *
 * Deux couches :
 *  - un <canvas> plein ecran, redessine 60 fois par seconde : fils (courbes de
 *    Bezier), halo des bulles, particules qui glissent ;
 *  - des <div> HTML posees par-dessus pour le texte des bulles et la carte
 *    (plus simple a styler et a cliquer que du texte dans un canvas).
 *
 * Python -> page : app.py appelle window.recevoir({type: ...}).
 * Page -> Python : window.pywebview.api.lancer("resumer"), .etat(), ...
 */

// ------------------------------------------------------------------ donnees

const ETAPES = [
  { id: "chercher",   nom: "Chercher",   numero: 1 },
  { id: "recolter",   nom: "Récolter",   numero: 2 },
  { id: "resumer",    nom: "Résumer",    numero: 3 },
  { id: "classer",    nom: "Classer",    numero: 4 },
  { id: "construire", nom: "Construire", numero: 5 },
  { id: "vault",      nom: "Vault" },
];
const INDEX = Object.fromEntries(ETAPES.map((e, i) => [e.id, i]));

// une couleur par type de chose qui circule
const COULEURS = { lien: "#7cc4ff", reel: "#ffb86b", resume: "#c49bff", fiche: "#6be3a4" };

const etat = {
  vault: null,          // ce que renvoie api.etat()
  enCours: null,        // id de l'etape qui tourne
  progres: {},          // etape -> {fait, total}
  messages: {},         // etape -> {texte, classe} : resultat du dernier lancement
  trouves: null,        // nombre de nouveaux reels au dernier "Chercher"
  carte: null,          // id de l'etape dont la carte est ouverte
};

const nf = (n) => Math.round(n).toLocaleString("fr-FR");
// 13 553 -> "13,6 k" : plus court pour tenir dans une bulle
const court = (n) => n < 1000 ? String(n) : (n / 1000).toFixed(1).replace(".", ",") + " k";

// ------------------------------------------------------------------ pont avec Python

// Hors de la fenetre pywebview (simple navigateur), on simule une API pour
// pouvoir voir la page quand meme.
const apiFactice = {
  etat: async () => ({
    config: { compte: "demo", cookies: "firefox" }, chercher: { max: 60 },
    recolter: { attente: 12, minutes: 6, echecs: 3 },
    resumer: { a_faire: 3, appels: 1, images: 4, entree: 11000, sortie: 2400, modele: "haiku" },
    classer: { a_faire: 8, appels: 1, entree: 3400, sortie: 900, modele: "haiku", premiere_fois: false },
    construire: { a_faire: true, jamais: false },
    vault: { reels: 546, recoltes: 549, domaines: 10, themes: 34 }, en_cours: null,
  }),
  lancer: async () => ({ ok: false, message: "Pas de Python ici (aperçu navigateur)." }),
  arreter: async () => false, choisir_export: async () => null,
  sauver_config: async () => apiFactice.etat(), ouvrir_vault: async () => {},
};
const api = () => (window.pywebview && window.pywebview.api) || apiFactice;

window.recevoir = function (evt) {
  switch (evt.type) {
    case "debut":
      etat.enCours = evt.etape;
      etat.progres[evt.etape] = null;
      etat.messages[evt.etape] = null;
      break;
    case "fin":
      etat.enCours = null;
      etat.progres[evt.etape] = null;
      etat.messages[evt.etape] = {
        texte: evt.message,
        classe: evt.code === 0 ? "ok" : "erreur",
      };
      if (evt.etape === "chercher" && evt.code === 0) {
        const m = /^(\d+)/.exec(evt.message || "");
        etat.trouves = m ? Number(m[1]) : null;
      }
      if (evt.etat) etat.vault = evt.etat;
      break;
    case "progres": {
      const p = etat.progres[evt.etape] || { fait: 0, total: null };
      if (evt.cumul) p.fait += evt.fait;
      else { p.fait = evt.fait; p.total = evt.total; }
      etat.progres[evt.etape] = p;
      break;
    }
    case "particule":
      lancerParticule(evt.de, evt.genre, evt.label, evt.image);
      break;
    case "rafale":
      for (let i = 0; i < evt.nombre; i++) lancerParticule(evt.de, evt.genre, null);
      break;
    case "log":
      ajouterJournal(evt.texte);
      return;
  }
  majBulles();
  majCarte();
};

async function rafraichir() {
  etat.vault = await api().etat();
  etat.enCours = etat.vault.en_cours;
  majBulles();
  majCarte();
}

// ------------------------------------------------------------------ mise en page

const toile = document.getElementById("toile");
const ctx = toile.getContext("2d");
let W = 0, H = 0, R = 60;
const pos = [];  // centre de chaque bulle

function miseEnPage() {
  const dpr = window.devicePixelRatio || 1;
  W = window.innerWidth; H = window.innerHeight;
  toile.width = W * dpr; toile.height = H * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  // les bulles s'alignent sur une vague douce, de gauche a droite
  const marge = Math.max(80, W * 0.07);
  const pas = (W - 2 * marge) / (ETAPES.length - 1);
  R = Math.max(46, Math.min(72, pas * 0.36, H * 0.11));
  const centreY = H * 0.47;
  const amplitude = Math.min(H * 0.12, 90);
  ETAPES.forEach((e, i) => {
    const vague = i === ETAPES.length - 1 ? 0 : Math.sin(i * 1.15 + 0.4) * amplitude;
    pos[i] = { x: marge + i * pas, y: centreY + vague, r: e.id === "vault" ? R * 1.25 : R };
  });

  for (const [i, div] of divsBulles.entries()) {
    div.style.left = pos[i].x + "px";
    div.style.top = pos[i].y + "px";
    div.style.width = div.style.height = pos[i].r * 2 + "px";
    div.style.fontSize = (pos[i].r / R) * (R / 64) * 14 + "px";  // le texte suit la taille de la bulle
  }
  majCarte();
}

// ------------------------------------------------------------------ bulles (HTML)

const divsBulles = ETAPES.map((e) => {
  const d = document.createElement("div");
  d.className = "bulle" + (e.id === "vault" ? " vault" : "");
  d.innerHTML = `${e.numero ? `<span class="numero">${e.numero}</span>` : ""}
    <span class="nom">${e.nom}</span><span class="chiffre">·</span><span class="detail"></span>`;
  d.addEventListener("click", (ev) => { ev.stopPropagation(); ouvrirCarte(e.id); });
  document.getElementById("bulles").appendChild(d);
  return d;
});

// ce qu'affiche chaque bulle : [chiffre, detail, classe]
function contenuBulle(id) {
  const v = etat.vault;
  if (!v) return ["·", "", ""];
  const p = etat.progres[id];
  if (etat.enCours === id) {
    const avance = p && p.total ? `${p.fait}/${p.total}` : p ? `${p.fait}` : "…";
    return [avance, "en cours", "encours"];
  }
  const tokens = (o) => `~${court(o.entree + o.sortie)} tokens`;
  switch (id) {
    case "chercher":
      return etat.trouves === null ? ["?", "nouveaux reels", ""]
        : [etat.trouves, "nouveaux trouvés", etat.trouves ? "attente" : ""];
    case "recolter":
      if (etat.messages.recolter?.classe === "erreur" && v.recolter.attente)
        return [v.recolter.attente, "bloqué · en attente", "bloque"];
      return v.recolter.attente ? [v.recolter.attente, `en attente\n~${v.recolter.minutes} min`, "attente"]
        : ["0", "rien\nen attente", ""];
    case "resumer":
      return v.resumer.a_faire ? [v.resumer.a_faire, `à résumer\n${tokens(v.resumer)}`, "attente"]
        : ["0", "tout est résumé", ""];
    case "classer":
      return v.classer.a_faire || v.classer.premiere_fois
        ? [v.classer.a_faire, `à classer\n${tokens(v.classer)}`, "attente"]
        : ["0", "tout est classé", ""];
    case "construire":
      return v.construire.a_faire ? ["↻", "à reconstruire", "attente"] : ["✓", "à jour", ""];
    case "vault":
      return [nf(v.vault.reels), `reels\n${v.vault.themes} thèmes`, ""];
  }
}

function majBulles() {
  ETAPES.forEach((e, i) => {
    const [chiffre, detail, classe] = contenuBulle(e.id);
    const d = divsBulles[i];
    d.querySelector(".chiffre").textContent = chiffre;
    d.querySelector(".detail").textContent = detail;
    d.classList.toggle("attente", classe === "attente");
    d.classList.toggle("encours", classe === "encours");
    d.classList.toggle("bloque", classe === "bloque");
    halo[i].classe = classe;
  });
  const statut = document.getElementById("statut");
  if (etat.enCours) statut.textContent = `${ETAPES[INDEX[etat.enCours]].nom} en cours…`;
  else if (etat.vault) statut.textContent = `@${etat.vault.config.compte || "?"} · ${nf(etat.vault.vault.recoltes)} reels récoltés`;
}

// ------------------------------------------------------------------ carte

const carte = document.getElementById("carte");

function ouvrirCarte(id) {
  etat.carte = etat.carte === id ? null : id;
  majCarte();
}
document.addEventListener("click", (ev) => {
  if (!carte.contains(ev.target)) { etat.carte = null; majCarte(); }
});

function estimation(o, extra = "") {
  return `<div class="estimation">${o.appels} appel(s) à Claude (${o.modele})${extra}<br>
    ~${nf(o.entree)} tokens en entrée, ~${nf(o.sortie)} en sortie<br>
    soit <b>~${nf(o.entree + o.sortie)} tokens</b> au total</div>`;
}

function corpsCarte(id) {
  const v = etat.vault;
  const tourne = etat.enCours === id;
  const occupe = etat.enCours && !tourne;
  const lancer = (texte) => tourne
    ? `<button data-action="arreter" ${id === "chercher" ? "disabled" : ""}>Arrêter</button>`
    : `<button class="principal" data-action="lancer" ${occupe ? "disabled" : ""}>${texte}</button>
       <button data-action="fermer">Pas maintenant</button>`;
  const attente = occupe ? `<p class="petit">Attends la fin de « ${ETAPES[INDEX[etat.enCours]].nom} ».</p>` : "";

  switch (id) {
    case "chercher":
      if (!v.config.compte) return `<h2>Chercher les nouveaux reels</h2>
        <p>Première fois : deux réglages, gardés dans config.json.</p>
        <label class="petit">Ton pseudo Instagram</label><input id="champ-compte" placeholder="pseudo">
        <label class="petit">Navigateur où tu es connecté (firefox, chrome, brave+gnomekeyring…)</label>
        <input id="champ-cookies" placeholder="firefox">
        <div class="boutons"><button class="principal" data-action="config">Enregistrer</button></div>
        <p class="petit">Ou directement : <button class="lien" data-action="export">importer l'export Instagram (.zip)</button></p>`;
      return `<h2>Chercher les nouveaux reels</h2>
        <p>Lit tes ${v.chercher.max} derniers Enregistrés sur Instagram (@${v.config.compte}) et les liens de inbox.txt,
        puis met les nouveaux en attente devant <b>Récolter</b>. Rien d'autre ne se lance.</p>
        ${attente}<div class="boutons">${lancer("Chercher")}</div>
        ${tourne ? "" : `<p class="petit">Première fois ou gros rattrapage :
          <button class="lien" data-action="export" ${occupe ? "disabled" : ""}>importer l'export Instagram (.zip)</button></p>`}`;
    case "recolter": {
      const r = v.recolter;
      return `<h2>Récolter et transcrire</h2>
        ${r.attente ? `<p><b>${r.attente}</b> reel(s) en attente, environ <b>${r.minutes} min</b>.
          Local et gratuit, mais le PC doit rester allumé.</p>`
          : `<p>Rien en attente. Lance d'abord <b>Chercher</b>.</p>`}
        ${r.echecs ? `<p class="petit">${r.echecs} post(s) en échec dans le journal ne sont pas retentés.</p>` : ""}
        <p class="petit">Si Instagram bloque, la récolte s'arrête proprement : ce qui est récolté avance, le reste attend.</p>
        ${attente}${r.attente || tourne ? `<div class="boutons">${lancer("Lancer la récolte")}</div>` : ""}`;
    }
    case "resumer": {
      const o = v.resumer;
      return `<h2>Résumer avec Claude</h2>
        ${o.a_faire ? `<p><b>${o.a_faire}</b> fiche(s) récoltée(s) pas encore résumée(s)${o.images ? `, ${o.images} image(s) à joindre` : ""}.</p>
          ${estimation(o)}` : `<p>Toutes les fiches sont résumées.</p>`}
        ${attente}${o.a_faire || tourne ? `<div class="boutons">${lancer("Valider")}</div>` : ""}`;
    }
    case "classer": {
      const o = v.classer;
      const rien = !o.a_faire && !o.premiere_fois;
      return `<h2>Classer par thèmes avec Claude</h2>
        ${rien ? `<p>Toutes les fiches sont rangées.</p>`
          : `<p>${o.premiere_fois ? `Premier classement : Claude (${o.modele_arborescence}) invente l'arborescence, puis range les ${o.a_faire} fiches.`
            : `<b>${o.a_faire}</b> fiche(s) à ranger dans les thèmes existants.`}</p>${estimation(o)}`}
        ${attente}${!rien || tourne ? `<div class="boutons">${lancer("Valider")}</div>` : ""}`;
    }
    case "construire":
      return `<h2>Construire le vault</h2>
        <p>Refait index.md, vault.html et le coffre Obsidian (fiches/, themes/). Local, instantané.</p>
        <p class="petit">${v.construire.a_faire ? "Des résumés ou des classements sont plus récents que le vault." : "Le vault est à jour."}</p>
        ${attente}<div class="boutons">${lancer("Construire")}</div>`;
    case "vault":
      return `<h2>Ton vault</h2>
        <p><b>${nf(v.vault.reels)}</b> fiches lisibles, rangées en ${v.vault.domaines} domaines et ${v.vault.themes} thèmes.</p>
        <p class="petit">${nf(v.vault.recoltes)} reels récoltés au total.</p>
        <div class="boutons"><button class="principal" data-action="ouvrir">Ouvrir vault.html</button></div>`;
  }
}

function majCarte() {
  const id = etat.carte;
  if (!id || !etat.vault || !pos.length) { carte.classList.add("cachee"); return; }
  const m = etat.messages[id];
  carte.innerHTML = `<button class="fermer" data-action="fermer">×</button>${corpsCarte(id)}
    ${m && m.texte ? `<p class="message ${m.classe}">${m.texte}</p>` : ""}`;
  carte.dataset.etape = id;

  // sous la bulle si elle est haute, au-dessus si elle est basse
  const p = pos[INDEX[id]];
  const largeur = 320;
  const x = Math.min(Math.max(p.x - largeur / 2, 16), W - largeur - 16);
  carte.style.left = x + "px";
  carte.classList.remove("cachee");
  const hauteur = carte.offsetHeight;
  const y = p.y < H * 0.5 ? p.y + p.r + 18 : p.y - p.r - 18 - hauteur;
  carte.style.top = Math.min(Math.max(y, 60), H - hauteur - 56) + "px";
}

carte.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-action]");
  if (!b) return;
  const id = carte.dataset.etape;
  switch (b.dataset.action) {
    case "fermer": etat.carte = null; majCarte(); break;
    case "lancer": {
      const r = await api().lancer(id, null);
      if (!r.ok) { etat.messages[id] = { texte: r.message, classe: "erreur" }; majCarte(); }
      break;
    }
    case "export": {
      const chemin = await api().choisir_export();
      if (chemin) await api().lancer("chercher", chemin);
      break;
    }
    case "arreter": await api().arreter(); break;
    case "ouvrir": await api().ouvrir_vault(); break;
    case "config":
      etat.vault = await api().sauver_config(
        document.getElementById("champ-compte").value,
        document.getElementById("champ-cookies").value);
      majBulles(); majCarte();
      break;
  }
});

// ------------------------------------------------------------------ fils et particules

// fil i : de la bulle i a la bulle i+1, une courbe de Bezier en S
function fil(i) {
  const a = pos[i], b = pos[i + 1];
  const dx = (b.x - a.x) * 0.5;
  return [
    { x: a.x + a.r * 0.92, y: a.y },
    { x: a.x + dx, y: a.y },
    { x: b.x - dx, y: b.y },
    { x: b.x - b.r * 0.92, y: b.y },
  ];
}

function bezier(c, t) {
  const u = 1 - t;
  const k = [u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t];
  const d = [-3 * u * u, 3 * u * u - 6 * u * t, 6 * u * t - 3 * t * t, 3 * t * t];
  const p = { x: 0, y: 0 }, tg = { x: 0, y: 0 };
  for (let j = 0; j < 4; j++) {
    p.x += k[j] * c[j].x; p.y += k[j] * c[j].y;
    tg.x += d[j] * c[j].x; tg.y += d[j] * c[j].y;
  }
  const n = Math.hypot(tg.x, tg.y) || 1;
  return { x: p.x, y: p.y, nx: -tg.y / n, ny: tg.x / n };  // point + normale
}

const particules = [];
const filesDAttente = ETAPES.map(() => []);  // une file par fil, pour les espacer
const halo = ETAPES.map(() => ({ pouls: 0, classe: "" }));
const images = new Map();
let compteur = 0;

function lancerParticule(de, genre, label, image) {
  const i = INDEX[de];
  if (i === undefined || i >= ETAPES.length - 1) return;
  filesDAttente[i].push({ genre, label, image });
}

function sortirDesFiles(t) {
  filesDAttente.forEach((file, i) => {
    if (!file.length || t - (file.dernier || 0) < 260) return;
    file.dernier = t;
    const { genre, label, image } = file.shift();
    let img = null;
    if (image) { img = new Image(); img.src = image; }
    // 2 etiquettes lisibles par fil a la fois, pas plus : sinon elles se chevauchent
    const lisibles = particules.filter((p) => p.fil === i && p.label).length;
    particules.push({
      fil: i, genre,
      label: label && lisibles < 2 ? (label.length > 34 ? label.slice(0, 33) + "…" : label) : null,
      img, debut: t, duree: 2300 + Math.random() * 900,
      phase: Math.random() * 6.28, cote: compteur++ % 2 ? 1 : -1,
    });
  });
}

// quelques poussieres qui flottent en permanence sur les fils : ca vit meme au repos
const poussieres = [];
for (let i = 0; i < ETAPES.length - 1; i++)
  for (let k = 0; k < 3; k++) poussieres.push({ fil: i, t: Math.random(), v: 0.03 + Math.random() * 0.03, phase: Math.random() * 6.28 });

const douceur = (t) => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;  // lent-rapide-lent

function dessiner(t) {
  requestAnimationFrame(dessiner);
  if (!pos.length) return;
  ctx.clearRect(0, 0, W, H);
  sortirDesFiles(t);
  const s = t / 1000;
  const actif = etat.enCours ? INDEX[etat.enCours] : -1;

  // -- fils
  for (let i = 0; i < ETAPES.length - 1; i++) {
    const c = fil(i);
    ctx.beginPath();
    ctx.moveTo(c[0].x, c[0].y);
    ctx.bezierCurveTo(c[1].x, c[1].y, c[2].x, c[2].y, c[3].x, c[3].y);
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(255,255,255,0.07)";
    ctx.setLineDash([]);
    ctx.stroke();
    if (i === actif || i + 1 === actif) {  // le fil vit autour de l'etape en cours
      ctx.strokeStyle = "rgba(124,196,255,0.35)";
      ctx.setLineDash([3, 14]);
      ctx.lineDashOffset = -s * 40;
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // -- poussieres
  for (const p of poussieres) {
    p.t = (p.t + p.v / 60) % 1;
    const b = bezier(fil(p.fil), p.t);
    const o = Math.sin(s * 1.3 + p.phase) * 4;
    ctx.fillStyle = `rgba(255,255,255,${0.12 * Math.sin(Math.PI * p.t)})`;
    ctx.beginPath(); ctx.arc(b.x + b.nx * o, b.y + b.ny * o, 1.4, 0, 6.28); ctx.fill();
  }

  // -- halo des bulles
  ETAPES.forEach((e, i) => {
    const p = pos[i], h = halo[i];
    h.pouls *= 0.94;
    const respire = h.classe === "encours" ? Math.sin(s * 3) * 3 : h.classe === "attente" ? Math.sin(s * 1.6) * 1.5 : 0;
    const r = p.r + respire + h.pouls * 6;
    const couleur = h.classe === "attente" ? "255,184,107" : h.classe === "encours" ? "124,196,255"
      : h.classe === "bloque" ? "255,123,114" : e.id === "vault" ? "107,227,164" : "160,170,190";
    const g = ctx.createRadialGradient(p.x, p.y, r * 0.6, p.x, p.y, r * 1.7);
    g.addColorStop(0, `rgba(${couleur},${0.10 + h.pouls * 0.25})`);
    g.addColorStop(1, `rgba(${couleur},0)`);
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(p.x, p.y, r * 1.7, 0, 6.28); ctx.fill();

    ctx.fillStyle = "#151920";
    ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 6.28); ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = `rgba(${couleur},${h.classe ? 0.65 : 0.22})`;
    ctx.stroke();

    if (h.classe === "encours") {  // arc qui tourne + arc de progression
      const pr = etat.progres[e.id];
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(124,196,255,0.9)";
      ctx.beginPath();
      if (pr && pr.total) ctx.arc(p.x, p.y, r + 5, -Math.PI / 2, -Math.PI / 2 + 6.28 * Math.min(1, pr.fait / pr.total));
      else ctx.arc(p.x, p.y, r + 5, s * 2.5, s * 2.5 + 1.2);
      ctx.stroke();
    }
  });

  // -- particules
  ctx.font = "11px system-ui, sans-serif";
  for (let k = particules.length - 1; k >= 0; k--) {
    const q = particules[k];
    const avance = (t - q.debut) / q.duree;
    if (avance >= 1) {
      halo[q.fil + 1].pouls = Math.min(1, halo[q.fil + 1].pouls + 0.35);  // la bulle d'arrivee "recoit"
      particules.splice(k, 1);
      continue;
    }
    const u = douceur(avance);
    const b = bezier(fil(q.fil), u);
    const ondule = Math.sin(Math.PI * u) * Math.sin(s * 2.2 + q.phase) * 7;
    const x = b.x + b.nx * ondule, y = b.y + b.ny * ondule;
    const alpha = Math.min(1, Math.sin(Math.PI * avance) * 1.6);
    const couleur = COULEURS[q.genre] || "#fff";

    ctx.globalAlpha = alpha;
    const g = ctx.createRadialGradient(x, y, 0, x, y, 14);
    g.addColorStop(0, couleur + "88"); g.addColorStop(1, couleur + "00");
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(x, y, 14, 0, 6.28); ctx.fill();

    if (q.img && q.img.complete && q.img.naturalWidth) {
      ctx.save();
      ctx.beginPath(); ctx.arc(x, y, 11, 0, 6.28); ctx.clip();
      const ratio = q.img.naturalHeight / q.img.naturalWidth;
      ctx.drawImage(q.img, x - 11, y - 11 * ratio, 22, 22 * ratio);
      ctx.restore();
      ctx.strokeStyle = couleur; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(x, y, 11, 0, 6.28); ctx.stroke();
    } else {
      ctx.fillStyle = couleur;
      ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 6.28); ctx.fill();
    }

    if (q.label) {
      ctx.globalAlpha = 0.9 * Math.pow(Math.sin(Math.PI * u), 2);  // s'efface pres des bulles
      ctx.fillStyle = "#d9d6d0";
      ctx.textAlign = "center";
      ctx.fillText(q.label, x, y + q.cote * 22 + 4);
    }
    ctx.globalAlpha = 1;
  }
}

// ------------------------------------------------------------------ journal et demo

const journal = document.getElementById("journal");
function ajouterJournal(texte) {
  journal.textContent += texte + "\n";
  if (journal.textContent.length > 60000) journal.textContent = journal.textContent.slice(-50000);
  journal.scrollTop = journal.scrollHeight;
}
document.getElementById("bouton-journal").addEventListener("click", (ev) => {
  ev.stopPropagation();
  journal.classList.toggle("cache");
});

// Demo : rejoue de faux evenements pour voir l'animation. Ne lance rien,
// ne touche a aucun fichier.
document.getElementById("bouton-demo").addEventListener("click", (ev) => {
  ev.stopPropagation();
  const faux = {
    chercher: ["instagram.com/reel/DcJCJ4Wqb9q", "instagram.com/p/DcRCbwwgBCJ", "tiktok.com/@velo/video/73", "instagram.com/reel/Db8x2"],
    recolter: ["3 cols mythiques des Pyrénées", "Recette de granola maison", "Raccourcis Hyprland à connaître", "Lisbonne : 5 adresses"],
    resumer: ["Cols des Pyrénées à vélo", "Granola croustillant sans sucre", "Hyprland : 10 raccourcis", "Lisbonne hors des sentiers"],
    classer: ["Cols → Vélo & cyclisme", "Granola → Cuisine", "Hyprland → Tech & logiciels", "Lisbonne → Voyages"],
  };
  const genres = { chercher: "lien", recolter: "reel", resumer: "resume", classer: "fiche" };
  Object.keys(faux).forEach((de, i) => setTimeout(() => {
    for (let n = 0; n < 3; n++) faux[de].forEach((l) => lancerParticule(de, genres[de], l));
  }, i * 1800));
  setTimeout(() => { for (let n = 0; n < 18; n++) lancerParticule("construire", "fiche", null); }, 4 * 1800);
});

// ------------------------------------------------------------------ demarrage

window.addEventListener("resize", miseEnPage);
miseEnPage();
requestAnimationFrame(dessiner);

let demarre = false;
function demarrer() { if (!demarre) { demarre = true; rafraichir(); } }
window.addEventListener("pywebviewready", demarrer);
setTimeout(() => { if (window.pywebview) demarrer(); else rafraichir(); }, 1500);

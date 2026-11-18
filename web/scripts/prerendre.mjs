// Prérendu au build : une vraie page HTML par route (dist/explorer/etat/index.html...), une page par département
// et par commune de plus de 5 000 habitants (dist/local/44109-nantes/index.html), sitemap.xml et robots.txt.
//
// Aucune dépendance ajoutée : les écrans du site (src/ecrans) sont exécutés ici dans happy-dom (déjà utilisé par
// les tests), chargés par l'API de Vite (ssrLoadModule), avec un fetch qui lit dist/data sur le disque. Le HTML
// obtenu est posé dans le gabarit dist/index.html produit par « vite build ». Rien n'est ajouté au site servi :
// ni script, ni requête ; la CSP du gabarit est conservée telle quelle. Voir docs/SEO.md.
//
// Usage : node scripts/prerendre.mjs            (toutes les pages)
//         OVMI_PRERENDU_COMMUNES=0 node ...     (sans les pages département et commune)
//         OVMI_URL_SITE=https://exemple.fr/     (adresse publique : canonical, Open Graph, sitemap)
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Window } from 'happy-dom'
import { createServer } from 'vite'

const debut = Date.now()
const WEB = join(dirname(fileURLToPath(import.meta.url)), '..')
const DIST = join(WEB, 'dist')
const DONNEES = join(DIST, 'data')
const SITE = (process.env.OVMI_URL_SITE ?? 'https://mooneyes.github.io/Ou-vont-mes-impots/').replace(/\/*$/, '/')
const AVEC_COMMUNES = process.env.OVMI_PRERENDU_COMMUNES !== '0'
/** Limite de fichiers d'un déploiement Cloudflare (offre gratuite) : le build échoue au-delà. */
const LIMITE_FICHIERS = 20000

if (!existsSync(join(DIST, 'index.html')) || !existsSync(DONNEES)) {
  console.error('dist/index.html ou dist/data absent : lancer « vite build » avant le prérendu.')
  process.exit(1)
}
const gabarit = readFileSync(join(DIST, 'index.html'), 'utf8')
// Le gabarit doit être celui de Vite : une fois prérendu, dist/index.html est la page d'accueil et ne peut plus servir.
if (/data-racine=/.test(gabarit) || !gabarit.includes('<html lang="fr">') || !/<main id="contenu"[^>]*>[\s\S]*<\/main>/.test(gabarit)) {
  console.error('dist/index.html a déjà été prérendu (ou n’est pas le gabarit attendu) : relancer « vite build » avant le prérendu.')
  process.exit(1)
}

const json = (chemin) => {
  try {
    return JSON.parse(readFileSync(chemin, 'utf8'))
  } catch {
    return null
  }
}
const jour = (x) => (typeof x === 'string' && /^\d{4}-\d{2}-\d{2}/.test(x) ? x.slice(0, 10) : null)

// Dates des données (lastmod du plan du site, dateModified du jeu de données) : lues dans les données publiées.
const dateDonnees = jour(json(join(DONNEES, 'mise_a_jour.json'))?.genere_le) ?? jour(json(join(DONNEES, 'meta.json'))?.genere_le)
const dateLocal = jour(/\d{4}-\d{2}-\d{2}/.exec(json(join(DONNEES, 'local', 'index.json'))?.millesime ?? '')?.[0]) ?? dateDonnees

// --- happy-dom : le document dans lequel les écrans écrivent ---------------------------------------------------
const poser = (nom, valeur) => Object.defineProperty(globalThis, nom, { value: valeur, configurable: true, writable: true })
let fenetre = null
let main = null
/** Ouvre un document neuf (et ferme le précédent : happy-dom garde en mémoire les nœuds des pages déjà rendues). */
async function ouvrirDocument() {
  await fenetre?.happyDOM.close()
  fenetre = new Window({ url: SITE })
  poser('window', fenetre)
  for (const nom of ['document', 'location', 'history', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'MutationObserver']) poser(nom, fenetre[nom])
  poser('getComputedStyle', fenetre.getComputedStyle.bind(fenetre))
  fenetre.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} })
  fenetre.scrollTo = () => {}
  fenetre.document.body.innerHTML = '<main id="contenu"></main><div id="annonce"></div>'
  main = fenetre.document.getElementById('contenu')
}
await ouvrirDocument()
// Seule source de données : les fichiers de dist/data (les mêmes que ceux servis). Toute autre adresse est refusée.
poser('fetch', async (url) => {
  const u = String(url)
  if (/^[a-z]+:/i.test(u) || u.startsWith('//') || u.includes('..')) throw new Error(`appel externe interdit : ${u}`)
  const f = join(DIST, u.split('?')[0])
  if (!existsSync(f)) return { ok: false, status: 404, json: async () => null }
  const texte = readFileSync(f, 'utf8')
  return { ok: true, status: 200, json: async () => JSON.parse(texte) }
})

// --- le code du site, chargé par Vite (TypeScript, define, sans construction supplémentaire) ---------------------
const vite = await createServer({ root: WEB, logLevel: 'error', appType: 'custom', server: { middlewareMode: true, hmr: false, ws: false, watch: null }, optimizeDeps: { noDiscovery: true, include: [] } })
const { ROUTES } = await vite.ssrLoadModule('/src/routes.ts')
const { afficher, brancherAdresses, NOM_SITE } = await vite.ssrLoadModule('/src/routeur.ts')
const { versChemin, prefixeRacine, fragmentCommune, fragmentDepartement, aUnePage } = await vite.ssrLoadModule('/src/chemins.ts')
const { viderCache } = await vite.ssrLoadModule('/src/donnees.ts')
const { TOUS_DEPARTEMENTS } = await vite.ssrLoadModule('/src/departements.ts')

let courant = '#/'
brancherAdresses({ lire: () => courant, remplacer: (f) => (courant = f) })

const echapper = (x) => String(x).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
const jsonLd = (objet) => JSON.stringify(objet).replace(/</g, '\\u003c')

/** Jeu de données décrit par le pipeline (docs/datapackage/schemaorg.jsonld) : seuls des champs vérifiables y figurent. */
function jeuDeDonnees(defaut) {
  const s = json(join(WEB, '..', 'docs', 'datapackage', 'schemaorg.jsonld'))
  const createur = { '@type': 'Organization', name: 'Projet citoyen Où vont mes impôts' }
  const jeu = { ...defaut, url: SITE, creator: createur, isPartOf: { '@id': `${SITE}#site` } }
  if (dateDonnees) jeu.dateModified = dateDonnees
  jeu.spatialCoverage = { '@type': 'Place', name: 'France' }
  if (!s) return jeu
  if (s.sameAs) jeu.sameAs = s.sameAs
  if (Array.isArray(s.keywords)) jeu.keywords = s.keywords
  if (typeof s.temporalCoverage === 'string') jeu.temporalCoverage = s.temporalCoverage
  if (typeof s.version === 'string') jeu.version = s.version
  // Distributions : seulement les fichiers réellement présents dans le site construit, une par famille.
  const vus = new Set()
  const distribution = []
  for (const d of Array.isArray(s.distribution) ? s.distribution : []) {
    const m = /\/data\/(.+)$/.exec(d.contentUrl ?? '')
    if (!m || vus.has(d.name) || !existsSync(join(DONNEES, m[1]))) continue
    vus.add(d.name)
    distribution.push({ '@type': 'DataDownload', name: d.name, encodingFormat: d.encodingFormat ?? 'application/json', contentUrl: `${SITE}data/${m[1]}` })
  }
  if (distribution.length) jeu.distribution = distribution.slice(0, 25)
  return jeu
}
const ldSource = JSON.parse(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/.exec(gabarit)[1])
const siteLd = { ...ldSource['@graph'].find((x) => x['@type'] === 'WebSite'), '@id': `${SITE}#site`, url: SITE }
const jeuLd = jeuDeDonnees(ldSource['@graph'].find((x) => x['@type'] === 'Dataset'))

// Polices du premier écran (texte courant et titres), préchargées : elles arrivent avec la feuille de style, avant le
// premier affichage, ce qui évite le décalage de mise en page au remplacement de la police de repli.
const POLICES = ['figtree-latin-wght-normal', 'bricolage-grotesque-latin-opsz-normal']
const polices = readdirSync(join(DIST, 'assets')).filter((f) => f.endsWith('.woff2') && POLICES.some((p) => f.startsWith(p + '-')))
// Fond de carte partagé des pages département et commune (src/composants/trame-france.svg, docs/PERF.md) : Vite
// l'émet dans assets/ avec une empreinte ; dans le prérendu, le module le désigne par son chemin source, remplacé
// ici par le fichier construit, relatif à la page. Une seule copie, mise en cache, au lieu de 17 Ko par page.
const trameFrance = readdirSync(join(DIST, 'assets')).find((f) => /^trame-france-[\w-]+\.svg$/.test(f))

const pages = []

/** Compose la page : gabarit de Vite, en-tête propre à la page, contenu prérendu, liens en vrais chemins. */
function composer({ chemin, titre, description, fil, contenu, indexable, racine }) {
  // racine : préfixe absolu pour la page 404, servie par l'hébergeur à n'importe quelle profondeur
  const prefixe = racine ?? prefixeRacine(chemin)
  const url = SITE + chemin
  const rel = (fragment) => prefixe + versChemin(fragment)
  const graphe = [siteLd]
  if (!chemin) graphe.push(jeuLd)
  else
    graphe.push(
      { '@type': 'WebPage', '@id': url, url, name: titre, description, inLanguage: 'fr', isPartOf: { '@id': `${SITE}#site` } },
      ...(fil.length ? [{ '@type': 'BreadcrumbList', itemListElement: fil.map((m, i) => ({ '@type': 'ListItem', position: i + 1, name: m.nom, item: SITE + versChemin(m.fragment).split('?')[0] })) }] : []),
    )
  const active = '/' + (chemin.split('/')[0] ?? '')
  const meta = (html, re, valeur) => {
    if (!re.test(html)) throw new Error(`gabarit : balise attendue absente (${re})`)
    return html.replace(re, (_, a, b) => `${a}${echapper(valeur)}${b}`)
  }
  let html = gabarit
  html = html.replace('<html lang="fr">', `<html lang="fr" data-racine="${prefixe}" data-site="${echapper(SITE)}">`)
  html = meta(html, /(<title>)[\s\S]*?(<\/title>)/, titre)
  html = meta(html, /(<meta name="description" content=")[^"]*(")/, description)
  html = meta(html, /(<link rel="canonical" href=")[^"]*(")/, url)
  html = meta(html, /(<meta property="og:title" content=")[^"]*(")/, titre)
  html = meta(html, /(<meta property="og:description" content=")[^"]*(")/, description)
  html = meta(html, /(<meta property="og:url" content=")[^"]*(")/, url)
  html = meta(html, /(<meta name="twitter:title" content=")[^"]*(")/, titre)
  html = meta(html, /(<meta name="twitter:description" content=")[^"]*(")/, description)
  html = html.replace(/(<meta property="og:image" content=")[^"]*(")/, `$1${SITE}og.png$2`).replace(/(<meta name="twitter:image" content=")[^"]*(")/, `$1${SITE}og.png$2`)
  if (!html.includes('<link rel="stylesheet"')) throw new Error('gabarit : feuille de style absente')
  html = html.replace('<link rel="stylesheet"', `${polices.map((f) => `<link rel="preload" href="./assets/${f}" as="font" type="font/woff2" crossorigin />\n    `).join('')}<link rel="stylesheet"`)
  if (!indexable) html = html.replace('<title>', '<meta name="robots" content="noindex, follow" />\n    <title>')
  html = html.replace(/(<script type="application\/ld\+json">)[\s\S]*?(<\/script>)/, (_, a, b) => `${a}\n${jsonLd({ '@context': 'https://schema.org', '@graph': graphe })}\n    ${b}`)
  // Fichiers du site (scripts, styles, icône) et liens de l'en-tête et du pied : relatifs à la page.
  html = html.replace(/((?:src|href)=")\.\/(?!\/)/g, `$1${prefixe}`)
  html = html.replace(/href="(#\/[^"]*)"/g, (_, f) => `href="${echapper(rel(f.replace(/&amp;/g, '&')))}"`)
  html = html.replace(`data-rubrique="${active}"`, `data-rubrique="${active}" aria-current="page"`)
  html = html.replace(
    /(<main id="contenu"[^>]*>)[\s\S]*(<\/main>)/,
    (_, a, b) =>
      `${a}\n<noscript><p class="avertissement">Sans JavaScript, les pages se lisent telles quelles. Le calcul à partir du salaire et les choix (année, commune, programme) ont besoin de JavaScript, exécuté sur ton appareil sans rien envoyer.</p></noscript>\n${contenu}\n    ${b}`,
  )
  return html
}

/** Rend une adresse interne avec le routeur du site et écrit sa page. */
async function prerendre(fragment, { indexable = true, lastmod = dateDonnees } = {}) {
  courant = fragment
  main.innerHTML = ''
  const page = await afficher(ROUTES, main, fragment, false)
  const chemin = versChemin(fragment).split('?')[0]
  const prefixe = prefixeRacine(chemin)
  if (!main.querySelector('h1')) {
    // Écran qui dépend d'une saisie ou d'un paramètre (résultat du calcul, commune choisie) : page d'attente lisible.
    const parent = page.route.parent ?? '/'
    main.innerHTML = `<div class="ecran"><h1>${echapper(page.route.titre)}</h1><p class="chapeau">${echapper(page.route.description)}</p><p><a href="#${parent}">${echapper(ROUTES.find((r) => r.chemin === parent)?.titre ?? 'Accueil')}</a></p></div>`
  }
  // La CSP interdit les attributs style : les largeurs (data-l, data-g) sont reposées par le script une fois chargé.
  main.querySelectorAll('[style]').forEach((el) => el.removeAttribute('style'))
  main.querySelectorAll('a[href^="#/"]').forEach((a) => a.setAttribute('href', prefixe + versChemin(a.getAttribute('href'))))
  main.querySelectorAll('use[href$="#trame-france"]').forEach((u) => {
    if (!trameFrance) throw new Error('dist/assets/trame-france-*.svg absent : le fond de carte partagé n’a pas été construit.')
    u.setAttribute('href', `${prefixe}assets/${trameFrance}#trame-france`)
  })
  const html = composer({ chemin, titre: page.titre, description: page.description, fil: page.fil, contenu: main.innerHTML, indexable })
  const dossier = join(DIST, chemin)
  mkdirSync(dossier, { recursive: true })
  writeFileSync(join(dossier, 'index.html'), html)
  pages.push({ chemin, titre: page.titre, description: page.description, indexable, lastmod, octets: Buffer.byteLength(html) })
}

try {
  for (const r of ROUTES) await prerendre('#' + r.chemin, { indexable: !r.sansIndex })
  const nbRoutes = pages.length

  // Page introuvable : 404.html à la racine, avec des chemins absolus (elle répond à toute adresse inconnue).
  {
    const base = new URL(SITE).pathname
    courant = '#/introuvable'
    main.innerHTML = ''
    const page = await afficher(ROUTES, main, courant, false)
    main.querySelectorAll('a[href^="#/"]').forEach((a) => a.setAttribute('href', base + versChemin(a.getAttribute('href'))))
    writeFileSync(join(DIST, '404.html'), composer({ chemin: '404.html', titre: page.titre, description: page.description, fil: [], contenu: main.innerHTML, indexable: false, racine: base }))
  }

  if (AVEC_COMMUNES) {
    const noms = new Map(TOUS_DEPARTEMENTS)
    const codes = readdirSync(join(DONNEES, 'local', 'geo'))
      .filter((f) => f.endsWith('.json'))
      .map((f) => f.slice(0, -5))
      .sort()
    for (const dep of codes) {
      const geo = json(join(DONNEES, 'local', 'geo', `${dep}.json`))
      if (!geo?.communes) continue
      await prerendre(fragmentDepartement(dep, noms.get(dep) ?? geo.departement.nom), { lastmod: dateLocal })
      for (const [insee, c] of Object.entries(geo.communes)) if (aUnePage(c.population)) await prerendre(fragmentCommune(insee, c.nom, c.population), { lastmod: dateLocal })
      viderCache()
      await ouvrirDocument()
    }
  }

  // Plan du site : les pages indexables, datées par les données qu'elles affichent.
  const indexables = pages.filter((p) => p.indexable)
  writeFileSync(
    join(DIST, 'sitemap.xml'),
    `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${indexables
      .map((p) => `<url><loc>${echapper(SITE + p.chemin)}</loc>${p.lastmod ? `<lastmod>${p.lastmod}</lastmod>` : ''}</url>`)
      .join('\n')}\n</urlset>\n`,
  )
  // robots.txt n'est lu qu'à la racine d'un domaine : sous https://<compte>.github.io/<depot>/ il est ignoré
  // (docs/SEO.md). Il sert dès que le site est publié à la racine (Cloudflare, domaine personnalisé).
  writeFileSync(join(DIST, 'robots.txt'), `User-agent: *\nAllow: /\n\nSitemap: ${SITE}sitemap.xml\n`)

  // Bilan : nombre de fichiers et poids du site construit (limite Cloudflare : 20 000 fichiers).
  let fichiers = 0
  let octets = 0
  const compter = (d) => {
    for (const n of readdirSync(d)) {
      const p = join(d, n)
      const s = statSync(p)
      if (s.isDirectory()) compter(p)
      else {
        fichiers++
        octets += s.size
      }
    }
  }
  writeFileSync(join(DIST, 'prerendu.json'), '{}')
  compter(DIST)
  const bilan = {
    site: SITE,
    pages: pages.length,
    pages_routes: nbRoutes,
    pages_departements: pages.filter((p) => /^local\/(\d{2,3}|2[AB])-/.test(p.chemin)).length,
    pages_communes: pages.filter((p) => /^local\/(\d{5}|2[AB]\d{3})-/.test(p.chemin)).length,
    pages_indexables: indexables.length,
    octets_pages: pages.reduce((s, p) => s + p.octets, 0),
    octets_page_commune_max: Math.max(0, ...pages.filter((p) => /^local\/(\d{5}|2[AB]\d{3})-/.test(p.chemin)).map((p) => p.octets)),
    octets_page_departement_max: Math.max(0, ...pages.filter((p) => /^local\/(\d{2,3}|2[AB])-/.test(p.chemin)).map((p) => p.octets)),
    fichiers_dist: fichiers,
    octets_dist: octets,
    limite_fichiers: LIMITE_FICHIERS,
    date_donnees: dateDonnees,
    duree_prerendu_s: Math.round((Date.now() - debut) / 100) / 10,
  }
  writeFileSync(join(DIST, 'prerendu.json'), JSON.stringify(bilan, null, 1) + '\n')
  console.log(
    `${NOM_SITE} : ${bilan.pages} pages prérendues (${nbRoutes} routes, ${bilan.pages_departements} départements, ${bilan.pages_communes} communes), ` +
      `${(bilan.octets_pages / 1e6).toFixed(1)} Mo de HTML, ${bilan.fichiers_dist} fichiers et ${(octets / 1e6).toFixed(0)} Mo dans dist/, en ${bilan.duree_prerendu_s} s.`,
  )
  if (bilan.fichiers_dist > LIMITE_FICHIERS) {
    console.error(`Trop de fichiers pour un déploiement Cloudflare : ${bilan.fichiers_dist} > ${LIMITE_FICHIERS}.`)
    process.exitCode = 1
  }
} finally {
  await vite.close()
  await fenetre.happyDOM.close()
}

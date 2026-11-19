// Service worker du site « Le billet découpé » : relire hors ligne les pages déjà vues sur cet appareil.
// Ce n'est pas une application : rien à installer, aucune invite, aucune notification.
//
// - Coquille (scripts, styles, polices, images de assets/, au nom haché par Vite) : cache d'abord. Le cache porte la
//   version de la construction (paramètre « v » de l'adresse du service worker, calculé par src/hors-ligne.ts à partir
//   des noms de fichiers de la page) : une nouvelle construction ouvre un nouveau cache, les anciens sont purgés.
// - Pages et données (data/) : réseau d'abord, copie enregistrée en repli. Une copie servie hors ligne est toujours
//   signalée à la page avec sa date d'enregistrement et le millésime lu dans chaque fichier de données : la page
//   l'affiche (jamais une donnée ancienne sans son millésime).
// - Aucune requête externe : seules les adresses du site (même origine, sous la portée du service worker) sont
//   interceptées ; le reste suit son cours sans passer par ici.
'use strict'

const VERSION = new URL(self.location.href).searchParams.get('v') || 'local'
const PREFIXE = 'ovmi-'
const CACHE_COQUILLE = `${PREFIXE}coquille-${VERSION}`
const CACHE_PAGES = `${PREFIXE}pages-${VERSION}`
const CACHE_DONNEES = `${PREFIXE}donnees-${VERSION}`
const CACHES_ACTUELS = [CACHE_COQUILLE, CACHE_PAGES, CACHE_DONNEES]
/** Nombre d'entrées gardées : les plus anciennes sont retirées au-delà. */
const MAX_PAGES = 150
const MAX_DONNEES = 400
const MAX_COQUILLE = 200
/** Au-delà de ce délai sans réponse du réseau, la copie enregistrée est servie (si elle existe). */
const DELAI_RESEAU_MS = 6000
const ENTETE_DATE = 'x-ovmi-enregistre-le'
const ENTETE_HORS_LIGNE = 'x-ovmi-hors-ligne'
const MESSAGE = 'ovmi-hors-ligne'

const portee = () => new URL(self.registration.scope)

/** Nature d'une adresse : null (pas interceptée), « coquille », « donnees » ou « page ». */
function nature(adresse, navigation) {
  let u
  try {
    u = new URL(adresse)
  } catch {
    return null
  }
  const p = portee()
  if (u.origin !== p.origin || !u.pathname.startsWith(p.pathname)) return null
  const rel = u.pathname.slice(p.pathname.length)
  if (rel === 'sw.js') return null
  if (rel.startsWith('data/')) return 'donnees'
  if (navigation || rel === '' || rel.endsWith('/') || rel.endsWith('.html')) return 'page'
  return 'coquille'
}

/** Clé d'enregistrement : sans paramètres de requête ni fragment pour les pages (le HTML servi est le même). */
function cle(adresse, type) {
  const u = new URL(adresse)
  u.hash = ''
  if (type === 'page') u.search = ''
  return u.href
}

/** Copie de la réponse, datée, sans marque de redirection (une navigation refuse une réponse redirigée). */
async function copieDatee(r) {
  const entetes = new Headers(r.headers)
  entetes.set(ENTETE_DATE, new Date().toISOString())
  return new Response(await r.blob(), { status: r.status, statusText: r.statusText, headers: entetes })
}

function propre(r) {
  if (!r.redirected) return r
  return new Response(r.body, { status: r.status, statusText: r.statusText, headers: r.headers })
}

async function elaguer(cache, max) {
  const cles = await cache.keys()
  for (const k of cles.slice(0, Math.max(0, cles.length - max))) await cache.delete(k)
}

async function enregistrer(nomCache, k, r, max) {
  if (!r || !r.ok || (r.type && r.type !== 'basic' && r.type !== 'default')) return
  const cache = await self.caches.open(nomCache)
  await cache.put(k, await copieDatee(r))
  await elaguer(cache, max)
}

/** Millésime déclaré par un fichier de données (texte, ou valeurs texte d'un objet), sinon null. */
function millesimeDe(json) {
  const m = json && typeof json === 'object' ? json.millesime : null
  if (typeof m === 'string' && m.trim()) return m.trim()
  if (typeof m === 'number') return String(m)
  if (m && typeof m === 'object') {
    const v = Object.values(m).filter((x) => typeof x === 'string' && x.trim())
    if (v.length) return Array.from(new Set(v)).slice(0, 3).join(' ; ')
  }
  return null
}

// Copies servies hors ligne, par onglet : la page les demande au démarrage (une navigation est servie avant que
// son onglet existe), et les reçoit au fil de l'eau ensuite.
const avis = new Map()
function signaler(idClient, a) {
  if (!idClient) return
  const liste = avis.get(idClient) ?? []
  if (!liste.some((x) => x.url === a.url)) liste.push(a)
  avis.delete(idClient)
  avis.set(idClient, liste)
  while (avis.size > 30) avis.delete(avis.keys().next().value)
  Promise.resolve(self.clients.get(idClient))
    .then((c) => c && c.postMessage({ type: MESSAGE, avis: [a] }))
    .catch(() => {})
}

const avecDelai = (promesse, ms) =>
  new Promise((ok, ko) => {
    const t = setTimeout(() => ko(new Error('délai')), ms)
    promesse.then(
      (r) => {
        clearTimeout(t)
        ok(r)
      },
      (e) => {
        clearTimeout(t)
        ko(e)
      },
    )
  })

/** Page de repli : adresse jamais consultée sur cet appareil, et pas de connexion. */
function pageIndisponible() {
  const accueil = portee().pathname
  const html = `<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Pas de connexion : Le billet découpé</title></head><body><main><h1>Pas de connexion</h1><p>Cette page n’a pas encore été ouverte sur cet appareil : aucune copie n’est enregistrée. Les pages déjà consultées restent lisibles sans connexion.</p><p><a href="${accueil}">Revenir à l’accueil</a></p></main></body></html>`
  return new Response(html, {
    status: 503,
    statusText: 'Hors ligne',
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'content-security-policy': "default-src 'none'; base-uri 'none'; form-action 'none'",
      [ENTETE_HORS_LIGNE]: '1',
    },
  })
}

async function coquille(event) {
  const k = cle(event.request.url, 'coquille')
  const cache = await self.caches.open(CACHE_COQUILLE)
  const copie = await cache.match(k)
  if (copie) return copie
  const r = await fetch(event.request)
  event.waitUntil(enregistrer(CACHE_COQUILLE, k, r.clone(), MAX_COQUILLE).catch(() => {}))
  return r
}

/** Réseau d'abord ; en repli, la copie enregistrée, signalée à la page avec sa date et son millésime. */
async function reseauDabord(event, type, reseau) {
  const nomCache = type === 'page' ? CACHE_PAGES : CACHE_DONNEES
  const k = cle(event.request.url, type)
  let r = null
  try {
    r = await avecDelai(reseau, DELAI_RESEAU_MS)
    if (r.status < 500) return type === 'page' ? propre(r) : r
  } catch {
    r = null
  }
  const copie = await (await self.caches.open(nomCache)).match(k)
  if (copie) {
    const a = { type, url: k, enregistre_le: copie.headers.get(ENTETE_DATE) }
    if (type === 'donnees') {
      a.chemin = k.slice(portee().href.length + 'data/'.length)
      try {
        a.millesime = millesimeDe(await copie.clone().json())
      } catch {
        a.millesime = null
      }
    }
    signaler(type === 'page' ? event.resultingClientId || event.clientId : event.clientId, a)
    const entetes = new Headers(copie.headers)
    entetes.set(ENTETE_HORS_LIGNE, '1')
    return new Response(copie.body, { status: copie.status, statusText: copie.statusText, headers: entetes })
  }
  if (r) return type === 'page' ? propre(r) : r
  try {
    const tard = await reseau
    return type === 'page' ? propre(tard) : tard
  } catch (e) {
    if (type === 'page') return pageIndisponible()
    throw e
  }
}

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET' || req.headers.has('range')) return
  const type = nature(req.url, req.mode === 'navigate')
  if (!type) return
  if (type === 'coquille') {
    event.respondWith(coquille(event))
    return
  }
  const reseau = fetch(req)
  // Toute réponse du réseau, même arrivée après le délai, met la copie à jour.
  event.waitUntil(
    reseau
      .then((r) => enregistrer(type === 'page' ? CACHE_PAGES : CACHE_DONNEES, cle(req.url, type), r.clone(), type === 'page' ? MAX_PAGES : MAX_DONNEES))
      .catch(() => {}),
  )
  event.respondWith(reseauDabord(event, type, reseau))
})

/** Enregistre des adresses déjà chargées par la page avant que le service worker la contrôle (première visite). */
async function retenir(adresses) {
  const vues = new Set()
  for (const brut of adresses.slice(0, 200)) {
    if (typeof brut !== 'string') continue
    const type = nature(brut, false)
    if (!type) continue
    const k = cle(brut, type)
    if (vues.has(k)) continue
    vues.add(k)
    const nomCache = type === 'page' ? CACHE_PAGES : type === 'donnees' ? CACHE_DONNEES : CACHE_COQUILLE
    const cache = await self.caches.open(nomCache)
    if (await cache.match(k)) continue
    try {
      const r = await fetch(k, { credentials: 'same-origin' })
      await enregistrer(nomCache, k, r, type === 'page' ? MAX_PAGES : type === 'donnees' ? MAX_DONNEES : MAX_COQUILLE)
    } catch {
      // pas de connexion : rien à retenir
    }
  }
}

self.addEventListener('message', (event) => {
  const m = event.data
  if (!m || typeof m !== 'object') return
  const source = event.source
  if (m.type === 'ovmi-etat' && source && source.id) {
    const liste = avis.get(source.id) ?? []
    if (liste.length) source.postMessage({ type: MESSAGE, avis: liste })
  } else if (m.type === 'ovmi-retenir' && Array.isArray(m.adresses)) {
    event.waitUntil(retenir(m.adresses))
  }
})

/** Coquille de la construction : page d'accueil et fichiers qu'elle référence (scripts, styles, polices, icônes). */
async function prechargerCoquille() {
  const p = portee()
  const r = await fetch(p.href, { cache: 'no-cache', credentials: 'same-origin' })
  if (!r.ok) return
  await enregistrer(CACHE_PAGES, cle(p.href, 'page'), r.clone(), MAX_PAGES)
  const html = await r.text()
  const adresses = new Set(['favicon.svg', 'manifest.webmanifest'].map((f) => new URL(f, p).href))
  for (const m of html.matchAll(/(?:src|href)="([^"#]+)"/g)) {
    const u = new URL(m[1].replace(/&amp;/g, '&'), r.url || p.href)
    if (nature(u.href, false) === 'coquille' && u.pathname.slice(p.pathname.length).startsWith('assets/')) adresses.add(u.href)
  }
  await retenir(Array.from(adresses))
}

self.addEventListener('install', (event) => {
  self.skipWaiting()
  event.waitUntil(prechargerCoquille().catch(() => {}))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      for (const nom of await self.caches.keys()) if (nom.startsWith(PREFIXE) && !CACHES_ACTUELS.includes(nom)) await self.caches.delete(nom)
      await self.clients.claim()
    })(),
  )
})

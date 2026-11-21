// Comptage anonyme des pages vues, côté serveur (Worker Cloudflare), dans une base D1 (liaison AUDIENCE).
//
// Ce qui est écrit : une ligne d'agrégat par jour (heure de Paris), chemin de page, pays, domaine du référent,
// type d'appareil et robot ou humain, avec un compteur. Rien d'autre : ni adresse IP, ni user-agent, ni
// identifiant, ni cookie, ni heure précise. Aucun script n'est ajouté à la page, la CSP ne change pas.
// Lignes directrices CNIL (délibération 2020-091, points 50 à 52) et docs/AUDIENCE.md.
//
// Rien ici ne doit retarder ni casser une page : l'écriture part dans ctx.waitUntil et toute erreur est avalée.

/** Sous-ensemble de l'API D1 utilisé (pas de dépendance aux types Cloudflare). */
export interface D1Like {
  prepare(sql: string): { bind(...valeurs: unknown[]): { run(): Promise<unknown> } }
}

/** Ligne d'agrégat : exactement ces colonnes, rien de plus. */
export interface LigneAudience {
  jour: string
  chemin: string
  pays: string
  referent: string
  appareil: 'mobile' | 'ordinateur'
  robot: 0 | 1
}

/** Durée de conservation des agrégats (en mois), purge quotidienne par le déclencheur planifié. */
export const CONSERVATION_MOIS = 13

export const SCHEMA = `CREATE TABLE IF NOT EXISTS visites (
  jour TEXT NOT NULL,
  chemin TEXT NOT NULL,
  pays TEXT NOT NULL,
  referent TEXT NOT NULL,
  appareil TEXT NOT NULL,
  robot INTEGER NOT NULL,
  vues INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (jour, chemin, pays, referent, appareil, robot)
) WITHOUT ROWID`

const UPSERT = `INSERT INTO visites (jour, chemin, pays, referent, appareil, robot, vues) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 1)
ON CONFLICT (jour, chemin, pays, referent, appareil, robot) DO UPDATE SET vues = vues + 1`

export const PURGE = `DELETE FROM visites WHERE jour < date('now', '-${CONSERVATION_MOIS} months')`

// Heuristique robot : marqueurs usuels des robots, outils en ligne de commande, navigateurs sans tête,
// aperçus de liens et sondes de disponibilité.
const ROBOT =
  /bot\b|bot\/|bot;|crawl|spider|slurp|scrap|curl|wget|python|httpie|libwww|perl|ruby|php\/|java\/|okhttp|go-http|axios|node-fetch|undici|got \(|headless|phantom|puppeteer|playwright|selenium|lighthouse|pagespeed|gtmetrix|preview|monitor|uptime|pingdom|statuscake|check|scan|validator|facebookexternalhit|embedly|whatsapp|telegram|discord|slack|skype|feed|rss|archive|fetch|http-client|httpclient|postman|insomnia|ahrefs|semrush|mj12|dataprovider|yandex|baidu|petal|bytespider|gpt|claude|anthropic|perplexity|ccbot|cohere|diffbot/i

const MOBILE = /mobi|android|iphone|ipod|ipad|windows phone|blackberry|opera mini/i

/** Robot si l'user-agent est absent ou porte un marqueur de robot, ou si Accept-Language manque. */
export function estRobot(userAgent: string | null, acceptLanguage: string | null): boolean {
  const ua = (userAgent ?? '').trim()
  if (!ua || !(acceptLanguage ?? '').trim()) return true
  // Cubot est une marque de téléphones, pas un robot.
  return ROBOT.test(ua.replace(/cubot/gi, ''))
}

export function appareil(userAgent: string | null): 'mobile' | 'ordinateur' {
  return MOBILE.test(userAgent ?? '') ? 'mobile' : 'ordinateur'
}

/** Chemin seul (sans paramètres ni fragment), « index.html » retiré, caractères limités, 200 caractères au plus. */
export function normaliserChemin(adresse: string): string {
  let chemin: string
  try {
    chemin = new URL(adresse).pathname
  } catch {
    return '/autre'
  }
  try {
    chemin = decodeURIComponent(chemin)
  } catch {
    return '/autre'
  }
  chemin = chemin.toLowerCase().replace(/\/{2,}/g, '/').replace(/\/index\.html$/, '/')
  if (!chemin.startsWith('/')) chemin = '/' + chemin
  if (chemin.length > 200 || !/^[a-z0-9/_.\-àâäçéèêëîïôöùûüÿœæ]*$/.test(chemin)) return '/autre'
  return chemin
}

/** Nom de domaine du référent seulement (jamais l'URL complète) ; « aucun » si absent, « interne » si même site. */
export function domaineReferent(referent: string | null, hoteSite: string): string {
  if (!referent) return 'aucun'
  let u: URL
  try {
    u = new URL(referent)
  } catch {
    return 'autre'
  }
  if (u.protocol !== 'https:' && u.protocol !== 'http:') return 'autre'
  const hote = u.hostname.toLowerCase().replace(/^www\./, '').replace(/\.$/, '')
  if (!hote || hote.length > 100 || !/^[a-z0-9.-]+$/.test(hote)) return 'autre'
  if (hote === hoteSite.toLowerCase().replace(/^www\./, '')) return 'interne'
  return hote
}

export function pays(cf: { country?: unknown } | undefined): string {
  const c = typeof cf?.country === 'string' ? cf.country.toUpperCase() : ''
  return /^[A-Z][A-Z0-9]$/.test(c) ? c : 'XX'
}

/** Date du jour à Paris, AAAA-MM-JJ. */
export function jourParis(date: Date): string {
  return new Intl.DateTimeFormat('fr-CA', { timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}

const EXCLUS = /^\/(assets|data)\/|^\/sw\.js$/

/**
 * Page HTML de navigation à compter ? GET seulement, ni asset ni donnée ni sw.js, réponse 200 en text/html,
 * navigation réelle (pas de préchargement ni de requête du service worker), pas d'opposition (DNT, GPC).
 */
export function aCompter(requete: Request, reponse: Response): boolean {
  if (requete.method !== 'GET') return false
  const url = new URL(requete.url)
  if (EXCLUS.test(url.pathname)) return false
  if (reponse.status !== 200) return false
  if (!(reponse.headers.get('content-type') ?? '').toLowerCase().startsWith('text/html')) return false
  const h = requete.headers
  const mode = h.get('sec-fetch-mode')
  if (mode !== null) {
    if (mode !== 'navigate') return false
  } else if (!(h.get('accept') ?? '').toLowerCase().includes('text/html')) {
    // Navigateur ancien ou outil : sans Sec-Fetch-Mode, il faut au moins demander du HTML.
    return false
  }
  if (/prefetch|prerender/i.test(`${h.get('sec-purpose') ?? ''} ${h.get('purpose') ?? ''}`)) return false
  // Opposition exprimée par le navigateur : Do Not Track ou Global Privacy Control.
  if (h.get('dnt') === '1' || h.get('sec-gpc') === '1') return false
  return true
}

/** Construit la ligne d'agrégat : seules des catégories, jamais une valeur brute de la requête. */
export function ligne(requete: Request, maintenant: Date = new Date()): LigneAudience {
  const h = requete.headers
  const ua = h.get('user-agent')
  const cf = (requete as unknown as { cf?: { country?: unknown } }).cf
  return {
    jour: jourParis(maintenant),
    chemin: normaliserChemin(requete.url),
    pays: pays(cf),
    referent: domaineReferent(h.get('referer'), new URL(requete.url).hostname),
    appareil: appareil(ua),
    robot: estRobot(ua, h.get('accept-language')) ? 1 : 0,
  }
}

let schemaPret: Promise<unknown> | null = null

export async function enregistrer(db: D1Like, l: LigneAudience): Promise<void> {
  // Table créée au premier passage de chaque instance (sans effet si elle existe déjà).
  schemaPret ??= db.prepare(SCHEMA).bind().run().catch((e) => {
    schemaPret = null
    throw e
  })
  await schemaPret
  await db.prepare(UPSERT).bind(l.jour, l.chemin, l.pays, l.referent, l.appareil, l.robot).run()
}

export async function purger(db: D1Like): Promise<void> {
  await db.prepare(SCHEMA).bind().run()
  await db.prepare(PURGE).bind().run()
}

/** Pour les tests : oublie que la table a été créée. */
export function _reinitialiser(): void {
  schemaPret = null
}

interface Contexte {
  waitUntil(p: Promise<unknown>): void
}

/** Compte la requête si besoin, en arrière-plan ; ne lève jamais d'erreur. */
export function compter(requete: Request, reponse: Response, db: D1Like | undefined, ctx: Contexte): void {
  if (!db) return
  try {
    if (!aCompter(requete, reponse)) return
    ctx.waitUntil(enregistrer(db, ligne(requete)).catch(() => {}))
  } catch {
    // le comptage ne doit jamais toucher la page
  }
}

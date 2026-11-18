// Lecture hors ligne des pages déjà vues : enregistrement du service worker (public/sw.js) et avis affiché quand
// la page ou ses données viennent d'une copie enregistrée sur l'appareil (date de la copie et millésime des données).
// Tout est facultatif : si le navigateur n'a pas de service worker, ou le refuse, le site fonctionne comme avant.

export interface AvisHorsLigne {
  type: 'page' | 'donnees'
  url: string
  enregistre_le: string | null
  chemin?: string
  millesime?: string | null
}

const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']

/** Date en toutes lettres (« 16 novembre 2026 »), à l'heure de l'appareil ; null si illisible. */
export function dateEnLettres(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return `${d.getDate() === 1 ? '1er' : d.getDate()} ${MOIS[d.getMonth()]} ${d.getFullYear()}`
}

/**
 * Version de la construction : empreinte des noms de fichiers de assets/ cités par la page (hachés par Vite, ils
 * changent à chaque construction qui change le code ou les styles). « dev » hors construction.
 */
export function versionDuSite(doc: Document): string {
  const noms = Array.from(doc.querySelectorAll<HTMLElement>('script[src], link[href]'))
    .map((el) => el.getAttribute('src') ?? el.getAttribute('href') ?? '')
    .filter((a) => /(^|\/)assets\//.test(a))
    .map((a) => a.slice(a.lastIndexOf('/') + 1))
    .sort()
  if (!noms.length) return 'dev'
  // FNV-1a 32 bits : courte, stable d'une page à l'autre de la même construction.
  let h = 0x811c9dc5
  for (const c of noms.join('|')) {
    h ^= c.charCodeAt(0)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, '0')
}

/** Texte de l'avis : date de la copie la plus ancienne, millésime de chaque donnée enregistrée. */
export function texteAvis(liste: AvisHorsLigne[]): { date: string | null; millesimes: string[]; sansMillesime: number } {
  const dates = liste.map((a) => a.enregistre_le).filter((x): x is string => !!x && !Number.isNaN(new Date(x).getTime()))
  dates.sort()
  const donnees = liste.filter((a) => a.type === 'donnees')
  const millesimes = Array.from(new Set(donnees.map((a) => a.millesime).filter((m): m is string => !!m)))
  return { date: dateEnLettres(dates[0]), millesimes, sansMillesime: donnees.filter((a) => !a.millesime).length }
}

const ID_AVIS = 'avis-hors-ligne'
const MAX_MILLESIMES = 6

/** Affiche (ou met à jour) l'avis sous l'en-tête. Ne touche pas au contenu de la page. */
export function afficherAvis(liste: AvisHorsLigne[], doc: Document = document): HTMLElement | null {
  if (!liste.length) return null
  const { date, millesimes, sansMillesime } = texteAvis(liste)
  let boite = doc.getElementById(ID_AVIS)
  if (!boite) {
    boite = doc.createElement('div')
    boite.id = ID_AVIS
    boite.className = 'conteneur'
    const entete = doc.querySelector('header.entete')
    const main = doc.getElementById('contenu')
    if (entete) entete.after(boite)
    else if (main) main.before(boite)
    else doc.body.prepend(boite)
  }
  const avis = doc.createElement('div')
  avis.className = 'avertissement'
  avis.setAttribute('role', 'status')
  const titre = doc.createElement('p')
  const fort = doc.createElement('strong')
  fort.textContent = 'Pas de connexion : tu lis une copie enregistrée sur ton appareil.'
  titre.append(fort)
  const quand = doc.createElement('p')
  quand.textContent = date
    ? `Cette copie date du ${date}, lors d’une visite précédente. Les montants sont ceux publiés à ce moment-là.`
    : 'Cette copie vient d’une visite précédente. Les montants sont ceux publiés à ce moment-là.'
  avis.append(titre, quand)
  if (millesimes.length || sansMillesime) {
    const m = doc.createElement('p')
    const vus = millesimes.slice(0, MAX_MILLESIMES)
    const reste = millesimes.length - vus.length
    const morceaux: string[] = []
    if (vus.length) morceaux.push(`Millésime des données enregistrées : ${vus.join(' ; ')}${reste > 0 ? ` (et ${reste} autre${reste > 1 ? 's' : ''})` : ''}.`)
    if (sansMillesime) morceaux.push(`${sansMillesime} fichier${sansMillesime > 1 ? 's' : ''} sans millésime indiqué.`)
    m.textContent = morceaux.join(' ')
    avis.append(m)
  }
  boite.replaceChildren(avis)
  return boite
}

/** Adresses du site déjà chargées par la page (page elle-même, scripts, styles, données), pour la première visite. */
function adressesChargees(base: URL): string[] {
  const out = [location.href]
  try {
    for (const e of performance.getEntriesByType('resource')) {
      const u = new URL(e.name)
      if (u.origin === base.origin && u.pathname.startsWith(base.pathname)) out.push(u.href)
    }
  } catch {
    // pas de mesure des ressources : seule la page est retenue
  }
  return out.slice(0, 200)
}

/**
 * Enregistre le service worker du site publié (pages prérendues). racine : chemin relatif vers la racine du site
 * (data-racine de <html>), si bien que le site marche à la racine d'un domaine comme sous /Ou-vont-mes-impots/.
 */
export function brancherHorsLigne(racine: string, doc: Document = document, nav: Navigator = navigator): boolean {
  try {
    const conteneur = nav?.serviceWorker
    if (!conteneur || typeof conteneur.register !== 'function') return false
    const base = new URL(racine || './', location.href)
    const sw = new URL(`sw.js?v=${encodeURIComponent(versionDuSite(doc))}`, base)
    const recus: AvisHorsLigne[] = []
    conteneur.addEventListener('message', (e: MessageEvent) => {
      const m = e.data
      if (!m || m.type !== 'ovmi-hors-ligne' || !Array.isArray(m.avis)) return
      for (const a of m.avis as AvisHorsLigne[]) if (a && typeof a.url === 'string' && !recus.some((x) => x.url === a.url)) recus.push(a)
      afficherAvis(recus, doc)
    })
    conteneur.startMessages?.()
    // Copies déjà servies à cette page (dont la page elle-même, servie avant que l'onglet existe).
    conteneur.controller?.postMessage({ type: 'ovmi-etat' })
    conteneur
      .register(sw.href, { scope: base.pathname })
      .then(() => conteneur.ready)
      .then((reg) => reg.active?.postMessage({ type: 'ovmi-retenir', adresses: adressesChargees(base) }))
      .catch(() => {})
    return true
  } catch {
    return false
  }
}

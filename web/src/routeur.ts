// Routage par fragment (#/rubrique/page?param=valeur) : fonctionne sur GitHub Pages sans réécriture.
// Arborescence de trois niveaux au plus ; fil d'Ariane et liens « voir aussi » déduits de la table des routes.
import { annoncer, appliquerLargeurs, h } from './util'

export type Ecran = (cible: HTMLElement, params: URLSearchParams) => Promise<void> | void

export interface Route {
  chemin: string
  titre: string
  /** libellé court (fil d'Ariane, cartes, liens) */
  court?: string
  charger: () => Promise<{ rendre: Ecran }>
  /** chemin du parent (hub) ; absent pour l'accueil et les entrées de premier niveau */
  parent?: string
  /** rayons voisins proposés en fin de page (2 au plus) */
  voisins?: string[]
  /** phrase de description, reprise par les cartes des hubs */
  resume?: string
  /** pas de bloc « voir aussi » ajouté automatiquement */
  sansVoisins?: boolean
}

/** Anciennes adresses (V1) vers les nouvelles ; les paramètres sont conservés. */
export const REDIRECTIONS: Record<string, string> = {
  '/paie': '/calcul/resultat',
  '/etat': '/explorer/etat',
  '/detail': '/explorer/etat/detail',
  '/concret': '/beneficiaires/programme',
  '/realisations': '/decisions/realisations',
  '/vie-politique': '/decisions/vie-politique',
  '/recettes': '/explorer/recettes',
}

export function lireFragment(fragment = location.hash): { chemin: string; params: URLSearchParams } {
  const brut = fragment.replace(/^#/, '') || '/'
  const [chemin, requete = ''] = brut.split('?')
  return { chemin: (chemin || '/').replace(/(.)\/$/, '$1'), params: new URLSearchParams(requete) }
}

export function lien(chemin: string, params: Record<string, string | number | undefined | null> = {}): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  const s = q.toString()
  return `#${chemin}${s ? '?' + s : ''}`
}

/** Nouvelle adresse d'un fragment ancien, ou null. */
export function redirection(fragment: string): string | null {
  const { chemin, params } = lireFragment(fragment)
  const cible = REDIRECTIONS[chemin]
  if (!cible) return null
  const p = params.toString()
  return `#${cible}${p ? '?' + p : ''}`
}

export const nomCourt = (r: Route) => r.court ?? r.titre

export function chaine(routes: Route[], route: Route): Route[] {
  const out: Route[] = []
  let r: Route | undefined = route
  while (r) {
    out.unshift(r)
    r = r.parent ? routes.find((x) => x.chemin === r!.parent) : undefined
  }
  return out
}

function filAriane(routes: Route[], route: Route): string {
  const c = chaine(routes, route)
  if (c.length < 2) return ''
  const accueil = routes.find((r) => r.chemin === '/')!
  const items = [accueil, ...c]
  return `<nav class="fil-ariane" aria-label="Fil d'Ariane"><ol>${items
    .map((r, i) =>
      i === items.length - 1
        ? `<li><a href="#${r.chemin}" aria-current="page">${h(nomCourt(r))}</a></li>`
        : `<li><a href="#${r.chemin}">${h(nomCourt(r))}</a></li>`,
    )
    .join('')}</ol></nav>`
}

function voirAussi(routes: Route[], route: Route): string {
  if (route.sansVoisins || !route.parent) return ''
  const hub = routes.find((r) => r.chemin === route.parent)
  const voisins = (route.voisins ?? []).map((v) => routes.find((r) => r.chemin === v)).filter((r): r is Route => !!r)
  if (!hub && !voisins.length) return ''
  return `<nav class="voir-aussi" aria-label="Voir aussi"><h2>Voir aussi</h2><ul>${[
    ...voisins.map((v) => `<li><a href="#${v.chemin}">${h(v.titre)}</a></li>`),
    hub ? `<li><a href="#${hub.chemin}">Retour à : ${h(hub.titre)}</a></li>` : '',
  ].join('')}</ul></nav>`
}

let jeton = 0

export async function afficher(routes: Route[], cible: HTMLElement, fragment = location.hash, focus = true) {
  const nouveau = redirection(fragment)
  if (nouveau) {
    if (typeof history !== 'undefined' && history.replaceState) history.replaceState(null, '', nouveau)
    else location.hash = nouveau
    fragment = nouveau
  }
  const { chemin, params } = lireFragment(fragment)
  const route = routes.find((r) => r.chemin === chemin) ?? routes[0]
  const moi = ++jeton
  cible.setAttribute('aria-busy', 'true')
  cible.innerHTML = '<p class="chargement">Chargement…</p>'
  try {
    const mod = await route.charger()
    if (moi !== jeton) return
    const zone = document.createElement('div')
    zone.className = 'ecran'
    await mod.rendre(zone, params)
    if (moi !== jeton) return
    const redirige = lireFragment(location.hash).chemin
    if (redirige !== chemin && routes.some((r) => r.chemin === redirige)) return
    zone.insertAdjacentHTML('afterbegin', filAriane(routes, route))
    zone.insertAdjacentHTML('beforeend', voirAussi(routes, route))
    appliquerLargeurs(zone)
    cible.replaceChildren(zone)
  } catch (e) {
    if (moi !== jeton) return
    console.error(e)
    cible.innerHTML = `${filAriane(routes, route)}<h1>${h(route.titre)}</h1><p class="erreur">Cette page n’a pas pu s’afficher : une donnée est manquante ou illisible. Le reste du site reste disponible.</p><p><a href="#/explorer">Explorer les dépenses publiques</a></p>`
  } finally {
    if (moi === jeton) cible.removeAttribute('aria-busy')
  }
  document.title = route.chemin === '/' ? 'Où vont mes impôts : vois où va l’argent que tu paies' : `${route.titre} · Où vont mes impôts`
  const racine = '/' + (route.chemin.split('/')[1] ?? '')
  document.querySelectorAll('.navigation [data-rubrique]').forEach((a) => {
    const r = a.getAttribute('data-rubrique')
    if (r === racine || (r === '/plus' && ['/beneficiaires', '/decisions', '/methode', '/mentions'].includes(racine))) a.setAttribute('aria-current', 'page')
    else a.removeAttribute('aria-current')
  })
  if (focus) {
    const titre = cible.querySelector('h1') as HTMLElement | null
    if (titre) {
      titre.setAttribute('tabindex', '-1')
      titre.focus({ preventScroll: false })
    }
    window.scrollTo?.(0, 0)
    annoncer(route.titre)
  }
}

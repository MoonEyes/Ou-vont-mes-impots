// Routage : une adresse s'écrit « #/rubrique/page?param=valeur » dans le code (notation interne).
// En développement et dans les tests, c'est le fragment de l'adresse. Sur le site publié, chaque route a sa page
// HTML prérendue (scripts/prerendre.mjs) et src/main.ts branche ici de vrais chemins (voir src/chemins.ts).
// Arborescence de trois niveaux au plus ; fil d'Ariane et liens « voir aussi » déduits de la table des routes.
import { versChemin } from './chemins'
import { picto } from './composants/pictos'
import { marquerSigles } from './composants/sigles'
import { brancherExports } from './composants/exporter'
import { annoncer, appliquerLargeurs, h } from './util'

/**
 * Un écran remplit cible. Il peut rendre la main avant d'avoir tout chargé en renvoyant { suite } :
 * la page est alors affichée tout de suite et complétée ensuite (afficher attend la suite avant de se résoudre).
 * titre et description remplacent ceux de la route quand la page dépend d'un paramètre (une commune, un département).
 */
export interface Rendu {
  suite?: Promise<void>
  titre?: string
  description?: string
  /** adresse interne propre de la page quand elle diffère de celle demandée (commune qui a sa page : /local/<insee>-<nom>/) */
  adresse?: string
  /** fin du fil d'Ariane propre à la page (département, commune), à la place du libellé de la route */
  fil?: Maillon[]
}
export interface Maillon {
  nom: string
  /** adresse interne « #/… » */
  fragment: string
}
export type Ecran = (cible: HTMLElement, params: URLSearchParams) => Promise<void | Rendu> | void | Rendu

export interface Route {
  chemin: string
  titre: string
  /** titre du document (balise title) quand il diffère du titre court de la page */
  titrePage?: string
  /** phrase de présentation de la page (balise meta description), propre à chaque route */
  description: string
  /** page sans contenu propre hors paramètre ou saisie : ni indexée, ni dans le plan du site */
  sansIndex?: boolean
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
  /** famille de dépense de la page (couleur des barres et du picto) : secu, etat, collectivites, ue, dette, niches, operateurs, prestations */
  famille?: string
  /** picto du thème, posé devant le titre de la page (src/composants/pictos.ts) */
  picto?: string
  /** rubrique de la page dans le hub de son parent (clé de THEMES, src/composants/hub.ts) ; sans thème : rubrique « Autres pages » */
  theme?: string
}

/** Adresse inconnue : page « introuvable » (elle n'est ni dans la table des routes ni dans le plan du site). */
export const ROUTE_INTROUVABLE: Route = {
  chemin: '/introuvable',
  titre: 'Page introuvable',
  description: 'Cette adresse ne correspond à aucune page du site.',
  sansIndex: true,
  sansVoisins: true,
  charger: () => import('./ecrans/introuvable'),
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

/** Fil d'Ariane d'une page, accueil compris ; vide pour l'accueil. Sert aussi aux données structurées du prérendu. */
export function maillons(routes: Route[], route: Route, fil?: Maillon[]): Maillon[] {
  if (route.chemin === '/') return []
  const accueil = routes.find((r) => r.chemin === '/')!
  const c = chaine(routes, route).map((r) => ({ nom: nomCourt(r), fragment: '#' + r.chemin }))
  return [{ nom: nomCourt(accueil), fragment: '#/' }, ...(fil ? [...c.slice(0, -1), ...fil] : c)]
}

function filAriane(items: Maillon[]): string {
  if (items.length < 2) return ''
  return `<nav class="fil-ariane" aria-label="Fil d'Ariane"><ol>${items
    .map((m, i) => `<li><a href="${h(m.fragment)}"${i === items.length - 1 ? ' aria-current="page"' : ''}>${h(m.nom)}</a></li>`)
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

export const NOM_SITE = 'Où vont mes impôts'
export const TITRE_ACCUEIL = 'Où vont mes impôts : vois où va l’argent que tu verses'
/** Titre du document d'une page ; propre (titre donné par l'écran) pour une commune ou un département. */
export const titreDocument = (route: Route, propre?: string) =>
  route.chemin === '/' ? TITRE_ACCUEIL : `${propre ?? route.titrePage ?? route.titre} · ${NOM_SITE}`

/** Adresse canonique d'une adresse interne, relative à la racine du site : sans paramètre de vue. */
export const cheminCanonique = (fragment: string) => versChemin(fragment).split('?')[0]

// Lecture et remplacement de l'adresse courante : le fragment par défaut, de vrais chemins sur le site publié.
let adresse = {
  lire: (): string => location.hash,
  remplacer: (fragment: string) => {
    if (typeof history !== 'undefined' && history.replaceState) history.replaceState(null, '', fragment)
    else location.hash = fragment
  },
}
export function brancherAdresses(a: typeof adresse) {
  adresse = a
}

/** Balises de l'en-tête tenues à jour pendant la navigation (pages prérendues : data-site sur <html>). */
function majEntete(titre: string, description: string, fragment: string) {
  document.title = titre
  const site = document.documentElement?.dataset?.site
  if (!site) return
  const url = site + cheminCanonique(fragment)
  const poser = (selecteur: string, attribut: string, valeur: string) => document.head.querySelector(selecteur)?.setAttribute(attribut, valeur)
  poser('link[rel="canonical"]', 'href', url)
  poser('meta[property="og:url"]', 'content', url)
  poser('meta[name="description"]', 'content', description)
  poser('meta[property="og:description"]', 'content', description)
  poser('meta[name="twitter:description"]', 'content', description)
  poser('meta[property="og:title"]', 'content', titre)
  poser('meta[name="twitter:title"]', 'content', titre)
}

let jeton = 0

export async function afficher(routes: Route[], cible: HTMLElement, fragment = adresse.lire(), focus = true) {
  const nouveau = redirection(fragment)
  if (nouveau) {
    adresse.remplacer(nouveau)
    fragment = nouveau
  }
  const { chemin, params } = lireFragment(fragment)
  const route = routes.find((r) => r.chemin === chemin) ?? ROUTE_INTROUVABLE
  const moi = ++jeton
  let suite: Promise<void> | null = null
  let propre: Rendu = {}
  cible.setAttribute('aria-busy', 'true')
  // Navigation interne : retour en haut avant de vider l'écran, pour que le pied de page ne remonte pas
  // dans la zone visible pendant le chargement (décalage de mise en page, CLS).
  if (focus) window.scrollTo?.(0, 0)
  // Premier affichage d'une page prérendue : son contenu reste en place jusqu'à ce que l'écran soit complet
  // (suite comprise), puis il est remplacé d'un coup, sans état intermédiaire ni décalage de mise en page.
  const prerendu = !focus && !!cible.querySelector('.ecran')
  if (!prerendu) cible.innerHTML = '<p class="chargement">Chargement…</p>'
  try {
    const mod = await route.charger()
    if (moi !== jeton) return
    const zone = document.createElement('div')
    zone.className = `ecran${route.famille ? ` f-${route.famille}` : ''}`
    const rendu = await mod.rendre(zone, params)
    if (rendu && typeof rendu === 'object') {
      propre = rendu
      suite = rendu.suite ?? null
    }
    // Sigles : leur première occurrence devient un lien vers le glossaire, une fois l'écran complet (src/composants/sigles.ts).
    suite = marquerSigles(zone, suite)
    if (prerendu && suite) {
      await suite.catch((e) => console.error(e))
      suite = null
    }
    if (moi !== jeton) return
    const redirige = lireFragment(adresse.lire()).chemin
    if (redirige !== chemin && routes.some((r) => r.chemin === redirige)) return
    zone.insertAdjacentHTML('afterbegin', route === ROUTE_INTROUVABLE ? '' : filAriane(maillons(routes, route, propre.fil)))
    if (route.picto) {
      const t = zone.querySelector('h1')
      if (t && !t.querySelector('.picto')) {
        t.classList.add('avec-picto')
        t.insertAdjacentHTML('afterbegin', picto(route.picto, 'picto-grand'))
      }
    }
    zone.insertAdjacentHTML('beforeend', voirAussi(routes, route))
    appliquerLargeurs(zone)
    cible.replaceChildren(zone)
    brancherExports(cible)
  } catch (e) {
    if (moi !== jeton) return
    console.error(e)
    cible.innerHTML = `${filAriane(maillons(routes, route))}<h1>${h(route.titre)}</h1><p class="erreur">Cette page n’a pas pu s’afficher : une donnée est manquante ou illisible. Le reste du site reste disponible.</p><p><a href="#/explorer">Explorer les dépenses publiques</a></p>`
  } finally {
    if (moi === jeton) cible.removeAttribute('aria-busy')
  }
  if (propre.adresse && propre.adresse !== fragment && moi === jeton && lireFragment(adresse.lire()).chemin === chemin) {
    adresse.remplacer(propre.adresse)
    fragment = propre.adresse
  }
  const page = { route, titre: titreDocument(route, propre.titre), description: propre.description ?? route.description, fil: maillons(routes, route, propre.fil) }
  majEntete(page.titre, page.description, fragment)
  const racine = '/' + (route.chemin.split('/')[1] ?? '')
  document.querySelectorAll('.entete [data-rubrique]').forEach((a) => {
    if (a.getAttribute('data-rubrique') === racine && route !== ROUTE_INTROUVABLE) a.setAttribute('aria-current', 'page')
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
  if (suite) {
    try {
      await suite
    } catch (e) {
      console.error(e)
    }
  }
  return page
}

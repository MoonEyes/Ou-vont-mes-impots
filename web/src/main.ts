import './styles.css'
import { versChemin, versFragment } from './chemins'
import { definirRacine } from './donnees'
import { afficher, brancherAdresses, lireFragment, REDIRECTIONS } from './routeur'
import { rendreDefilables } from './util'
import { ROUTES } from './routes'

export { ROUTES }

function demarrer() {
  const main = document.getElementById('contenu') as HTMLElement
  const plus = document.querySelector<HTMLButtonElement>('#bouton-plus')
  const feuille = document.getElementById('feuille-plus')
  const fermer = () => {
    plus?.setAttribute('aria-expanded', 'false')
    if (feuille) feuille.hidden = true
  }
  plus?.addEventListener('click', () => {
    const ouvert = plus.getAttribute('aria-expanded') === 'true'
    plus.setAttribute('aria-expanded', String(!ouvert))
    if (feuille) feuille.hidden = ouvert
    if (!ouvert) feuille?.querySelector<HTMLElement>('a')?.focus()
  })
  feuille?.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).closest('a')) fermer()
  })
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && feuille && !feuille.hidden) {
      fermer()
      plus?.focus()
    }
  })
  // La feuille « Plus » se ferme quand le focus clavier en sort (elle ne masque plus l'élément actif).
  document.getElementById('navigation')?.addEventListener('focusout', (e) => {
    const vers = (e as FocusEvent).relatedTarget as Node | null
    if (feuille && !feuille.hidden && vers && !document.getElementById('navigation')!.contains(vers)) fermer()
  })
  // Tableaux insérés après le rendu (fiches dépliées, pagination) : rendus atteignables au clavier.
  if (typeof MutationObserver !== 'undefined') new MutationObserver(() => rendreDefilables(main)).observe(main, { childList: true, subtree: true })
  const racine = document.documentElement.dataset.racine
  if (racine !== undefined) return demarrerChemins(racine, main, fermer)
  // Développement et tests : page unique, adresses en fragment.
  window.addEventListener('hashchange', () => {
    fermer()
    afficher(ROUTES, main)
  })
  afficher(ROUTES, main, location.hash, false)
}

/**
 * Site publié : chaque route a sa page HTML prérendue (data-racine sur <html> donne le chemin vers la racine).
 * Le script reprend la main : adresses en vrais chemins (History API), liens internes suivis sans rechargement,
 * anciens fragments « #/… » (liens déjà partagés, écrans qui posent location.hash) remplacés par le chemin.
 */
function demarrerChemins(racineRelative: string, main: HTMLElement, fermer: () => void) {
  const base = new URL(racineRelative || './', location.href).pathname
  definirRacine(base)
  const url = (fragment: string) => base + versChemin(fragment)
  const interne = () => (location.hash.startsWith('#/') ? location.hash : versFragment(decodeURI(location.pathname.slice(base.length)), location.search))
  let courant = ''
  brancherAdresses({
    lire: interne,
    remplacer: (fragment) => {
      courant = fragment
      history.replaceState(null, '', url(fragment))
    },
  })
  // Les liens relatifs du prérendu deviennent absolus : ils restent justes quand l'adresse change sans rechargement.
  document.querySelectorAll<HTMLAnchorElement>('a[href]').forEach((a) => {
    const brut = a.getAttribute('href')!
    if (!/^(#|\/|[a-z][a-z0-9+.-]*:)/i.test(brut)) a.setAttribute('href', new URL(brut, location.href).pathname + new URL(brut, location.href).search)
  })
  // Même chose pour l'icône du site, que le navigateur redemande à chaque changement d'adresse.
  const icone = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
  if (icone) icone.setAttribute('href', new URL(icone.getAttribute('href')!, location.href).pathname)
  // Les écrans écrivent leurs liens en notation interne « #/… » : chaque lien reçoit son vrai chemin.
  const relier = (zone: ParentNode) => zone.querySelectorAll<HTMLAnchorElement>('a[href^="#/"]').forEach((a) => a.setAttribute('href', url(a.getAttribute('href')!)))
  relier(document)
  new MutationObserver(() => relier(main)).observe(main, { childList: true, subtree: true })

  const montrer = (fragment: string, focus = true) => {
    courant = fragment
    fermer()
    return afficher(ROUTES, main, fragment, focus)
  }
  const surChangement = () => {
    const fragment = interne()
    if (location.hash.startsWith('#/')) history.replaceState(null, '', url(fragment))
    if (fragment !== courant) montrer(fragment)
  }
  window.addEventListener('popstate', surChangement)
  window.addEventListener('hashchange', surChangement)
  document.addEventListener('click', (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    const a = (e.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null
    if (!a || a.target || a.hasAttribute('download')) return
    const brut = a.getAttribute('href')!
    let fragment: string | null = null
    if (brut.startsWith('#/')) fragment = brut
    else if (!brut.startsWith('#')) {
      const u = new URL(a.href)
      if (u.origin === location.origin && u.pathname.startsWith(base) && !u.hash) fragment = versFragment(decodeURI(u.pathname.slice(base.length)), u.search)
    }
    if (!fragment) return
    const chemin = lireFragment(fragment).chemin
    if (!ROUTES.some((r) => r.chemin === chemin) && !REDIRECTIONS[chemin]) return
    e.preventDefault()
    if (fragment === courant) return
    history.pushState(null, '', url(fragment))
    montrer(fragment)
  })
  const depart = interne()
  if (location.hash.startsWith('#/')) history.replaceState(null, '', url(depart))
  montrer(depart, false)
}

if (typeof document !== 'undefined' && document.getElementById('contenu')) demarrer()

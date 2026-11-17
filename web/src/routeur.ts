// Routage par fragment (#/ecran?param=valeur) : fonctionne sur GitHub Pages sans réécriture.
import { annoncer, appliquerLargeurs } from './util'

export type Ecran = (cible: HTMLElement, params: URLSearchParams) => Promise<void> | void

export interface Route {
  chemin: string
  titre: string
  charger: () => Promise<{ rendre: Ecran }>
}

export function lireFragment(fragment = location.hash): { chemin: string; params: URLSearchParams } {
  const brut = fragment.replace(/^#/, '') || '/'
  const [chemin, requete = ''] = brut.split('?')
  return { chemin: chemin || '/', params: new URLSearchParams(requete) }
}

export function lien(chemin: string, params: Record<string, string | number | undefined | null> = {}): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  const s = q.toString()
  return `#${chemin}${s ? '?' + s : ''}`
}

let jeton = 0

export async function afficher(routes: Route[], cible: HTMLElement, fragment = location.hash, focus = true) {
  const { chemin, params } = lireFragment(fragment)
  const route = routes.find((r) => r.chemin === chemin) ?? routes[0]
  const moi = ++jeton
  cible.setAttribute('aria-busy', 'true')
  cible.innerHTML = '<p class="chargement">Chargement…</p>'
  try {
    const mod = await route.charger()
    if (moi !== jeton) return
    const zone = document.createElement('div')
    await mod.rendre(zone, params)
    appliquerLargeurs(zone)
    if (moi !== jeton) return
    zone.className = "ecran"
    cible.replaceChildren(zone)
  } catch (e) {
    if (moi !== jeton) return
    console.error(e)
    cible.innerHTML = `<h1>${route.titre}</h1><p class="erreur">Cette page n’a pas pu s’afficher : une donnée est manquante ou illisible. Le reste du site reste disponible.</p>`
  } finally {
    if (moi === jeton) cible.removeAttribute('aria-busy')
  }
  document.title = `${route.titre} · Où vont mes impôts`
  document.querySelectorAll('.navigation a').forEach((a) => {
    const href = a.getAttribute('href') ?? ''
    if (lireFragment(href).chemin === route.chemin) a.setAttribute('aria-current', 'page')
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

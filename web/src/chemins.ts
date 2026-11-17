// Adresses publiques en vrais chemins (/explorer/etat/, /local/44109-nantes/), lisibles par les moteurs de recherche.
// Dans le code, une adresse reste écrite « #/chemin?param=valeur » (notation interne, celle des anciens fragments) :
// ce module fait la conversion dans les deux sens, pour le site (src/main.ts) comme pour le prérendu (scripts/prerendre.mjs).

/** Une commune a sa propre page HTML au-dessus de ce nombre d'habitants ; les autres passent par /local/commune/?insee=. */
export const SEUIL_PAGE_COMMUNE = 5000

export const aUnePage = (population: number | undefined | null) => typeof population === 'number' && population > SEUIL_PAGE_COMMUNE

/** « Saint-Étienne-du-Rouvray » devient « saint-etienne-du-rouvray ». */
export function slug(nom: string): string {
  return nom
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/œ/gi, 'oe')
    .replace(/æ/gi, 'ae')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

const INSEE = /^(\d{5}|2[AB]\d{3})$/
const DEP = /^(\d{2,3}|2[AB])$/

/** Adresse interne de la page d'une commune : avec « page », elle mène à /local/<insee>-<nom>/. */
export function fragmentCommune(insee: string, nom: string, population?: number | null): string {
  return aUnePage(population) ? `#/local/commune?insee=${insee}&page=${slug(nom)}` : `#/local/commune?insee=${insee}`
}

export const fragmentDepartement = (code: string, nom: string) => `#/local/departement?dep=${code}&page=${slug(nom)}`

/** Adresse interne vers chemin relatif à la racine du site : « #/explorer/etat?m=x » devient « explorer/etat/?m=x ». */
export function versChemin(fragment: string): string {
  const brut = fragment.replace(/^#/, '').replace(/^\//, '')
  const [chemin, requete = ''] = brut.split('?')
  const propre = chemin.replace(/\/+$/, '')
  const p = new URLSearchParams(requete)
  const page = p.get('page')
  if (page && /^[a-z0-9-]+$/.test(page)) {
    const code = propre === 'local/commune' ? p.get('insee') : propre === 'local/departement' ? p.get('dep') : null
    if (code && (propre === 'local/commune' ? INSEE : DEP).test(code)) {
      p.delete('page')
      p.delete(propre === 'local/commune' ? 'insee' : 'dep')
      const q = p.toString()
      return `local/${code}-${page}/${q ? '?' + q : ''}`
    }
  }
  const q = p.toString()
  return `${propre ? propre + '/' : ''}${q ? '?' + q : ''}`
}

/** Chemin relatif à la racine du site (et sa requête) vers adresse interne. */
export function versFragment(chemin: string, requete = ''): string {
  const propre = chemin.replace(/^\/+|\/+$/g, '').replace(/(^|\/)index\.html$/, '').replace(/\/+$/, '')
  const p = new URLSearchParams(requete)
  const m = /^local\/(\d{5}|2[AB]\d{3}|\d{2,3}|2[AB])-([a-z0-9-]+)$/.exec(propre)
  let base = propre
  if (m) {
    const commune = INSEE.test(m[1])
    base = commune ? 'local/commune' : 'local/departement'
    const q = new URLSearchParams()
    q.set(commune ? 'insee' : 'dep', m[1])
    q.set('page', m[2])
    p.forEach((v, k) => q.set(k, v))
    return `#/${base}?${q.toString()}`
  }
  const q = p.toString()
  return `#/${base}${q ? '?' + q : ''}`
}

/** Préfixe relatif d'une page vers la racine du site : « explorer/etat/ » donne « ../../ », la racine « ./ ». */
export function prefixeRacine(chemin: string): string {
  const n = chemin.split('?')[0].split('/').filter(Boolean).length
  return n ? '../'.repeat(n) : './'
}

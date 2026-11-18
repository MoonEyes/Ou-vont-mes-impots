// Lecture des fichiers JSON du site (copie de site/data au build).
// Seule source réseau du site : des chemins relatifs vers data/, jamais un autre domaine.

export class DonneeAbsente extends Error {
  constructor(public fichier: string) {
    super(`Donnée non disponible : ${fichier}`)
  }
}

export class ContratIncompatible extends Error {}

export const VERSION_CONTRAT_SITE = '1.0'

const cache = new Map<string, Promise<unknown>>()

// Racine du site devant data/ : vide tant que la page est à la racine (développement, tests), chemin absolu
// (« /Ou-vont-mes-impots/ ») sur les pages prérendues, qui vivent dans des sous-dossiers.
let racineSite = ''
export function definirRacine(r: string) {
  racineSite = r
}

function cheminSur(chemin: string): string {
  // Refuse tout ce qui ressemble à une URL absolue ou à une remontée d'arborescence.
  if (!/^[A-Za-z0-9_\-./]+$/.test(chemin) || chemin.includes('..') || chemin.startsWith('/'))
    throw new DonneeAbsente(chemin)
  return racineSite + 'data/' + chemin
}

/** Adresse d'un fichier de données, pour un lien de téléchargement (même règle que charger). */
export const urlDonnee = (chemin: string) => cheminSur(chemin)

export function charger<T = any>(chemin: string): Promise<T> {
  const deja = cache.get(chemin)
  if (deja) return deja as Promise<T>
  const p = (async () => {
    const url = cheminSur(chemin)
    let r: Response
    try {
      r = await fetch(url, { credentials: 'same-origin' })
    } catch {
      throw new DonneeAbsente(chemin)
    }
    if (!r.ok) throw new DonneeAbsente(chemin)
    try {
      return (await r.json()) as T
    } catch {
      throw new DonneeAbsente(chemin)
    }
  })()
  cache.set(chemin, p)
  p.catch(() => cache.delete(chemin))
  return p
}

/** Variante qui renvoie null quand le fichier est absent. */
export async function chargerSiPresent<T = any>(chemin: string): Promise<T | null> {
  try {
    return await charger<T>(chemin)
  } catch (e) {
    if (e instanceof DonneeAbsente) return null
    throw e
  }
}

export interface Manifeste {
  genere_le?: string
  version_contrat?: string | null
  optionnels: {
    prelevements: string[] | null
    tracabilite: string[] | null
    affectation_prelevements: boolean
  }
}

export async function manifeste(): Promise<Manifeste> {
  const m = await chargerSiPresent<Manifeste>('_manifeste.json')
  return m ?? { optionnels: { prelevements: null, tracabilite: null, affectation_prelevements: false } }
}

/** Contrôle de version du contrat (CONTRAT_INCOMPATIBLE si version majeure différente). */
export function verifierContrat(meta: { version_contrat?: string } | null) {
  const v = meta?.version_contrat
  if (v && v.split('.')[0] !== VERSION_CONTRAT_SITE.split('.')[0])
    throw new ContratIncompatible(`Les données sont au contrat ${v}, le site attend ${VERSION_CONTRAT_SITE}.`)
}

export function viderCache() {
  cache.clear()
}

// Arbres de l'État disponibles : dossier et millésime.
export interface VueArbre {
  cle: string
  dossier: string
  libelle: string
  millesime: string
  /** Période en clair, sans sigle, pour l'affichage. */
  periode?: string
}

export const VUES_ARBRE: VueArbre[] = [
  { cle: 'execution2024', dossier: 'arbre', libelle: 'Dépensé en 2024 (par politique)', millesime: 'Exécution 2024', periode: 'dépenses réelles 2024' },
  { cle: 'lfi2025', dossier: 'arbre_lfi2025', libelle: 'Budget voté 2025 (par politique)', millesime: 'LFI 2025', periode: 'budget voté 2025' },
  { cle: 'nature2025', dossier: 'arbre_plf2025_nature', libelle: 'Budget proposé 2025 (par type de dépense)', millesime: 'PLF 2025', periode: 'budget proposé 2025' },
  { cle: 'execution2025', dossier: 'millesimes/execution2025', libelle: 'Dépensé en 2025 (par politique)', millesime: 'Exécution 2025', periode: 'dépenses réelles 2025' },
]

export const vueArbre = (cle: string | null) => VUES_ARBRE.find((v) => v.cle === cle) ?? VUES_ARBRE[0]

export interface Noeud {
  id: string
  nom: string
  niveau: string
  md: number
  enfants?: Noeud[]
  fichier?: string
  nb_enfants?: number
  millesime?: string
  source?: string
  unite?: string
}

/**
 * Retrouve un nœud par son identifiant (chemin « a/b/c »), en chargeant à la demande
 * les sous-arbres (« fichier »). Renvoie aussi le chemin des ancêtres pour le fil d'Ariane.
 */
export async function trouverNoeud(dossier: string, id: string): Promise<{ noeud: Noeud; chemin: Noeud[]; racine: Noeud }> {
  const racine = await charger<Noeud>(`${dossier}/racine.json`)
  const chemin: Noeud[] = [racine]
  if (!id || id === 'racine') return { noeud: await deplier(racine), chemin, racine }
  let courant: Noeud = racine
  for (;;) {
    courant = await deplier(courant)
    const suivant: Noeud | undefined = (courant.enfants ?? []).find((e) => id === e.id || id.startsWith(e.id + '/'))
    if (!suivant) throw new DonneeAbsente(`${dossier} : ${id}`)
    chemin.push(suivant)
    if (suivant.id === id) return { noeud: await deplier(suivant), chemin, racine }
    courant = suivant
  }
}

/** Remplace un point de découpe par le sous-arbre chargé. */
export async function deplier(n: Noeud): Promise<Noeud> {
  if (n.enfants || !n.fichier) return n
  const sous = await charger<Noeud>(n.fichier)
  return { ...n, enfants: sous.enfants }
}

/** Liste des programmes (numéro, nom, mission, grand poste) d'après l'arbre d'exécution 2024. */
export async function listeProgrammes(): Promise<{ numero: string; nom: string; mission: string; poste: string; id: string; md: number }[]> {
  const racine = await charger<Noeud>('arbre/racine.json')
  const out: { numero: string; nom: string; mission: string; poste: string; id: string; md: number }[] = []
  const parcourir = (n: Noeud, poste: string, mission: string) => {
    if (n.niveau === 'programme') {
      const m = /(\d{3})$/.exec(n.id)
      if (m) out.push({ numero: m[1], nom: n.nom, mission, poste, id: n.id, md: n.md })
      return
    }
    for (const e of n.enfants ?? [])
      parcourir(e, n.niveau === 'grand_poste' ? n.nom : poste, n.niveau === 'mission' ? n.nom : mission)
  }
  parcourir(racine, '', '')
  return out
}

// Recherche dans tout le site, faite dans le navigateur : l'index est construit au build (scripts/index-recherche.mjs)
// et lu seulement à la première saisie (data/_recherche.json, noyau d'environ 60 Ko compressés, et ses morceaux par
// type : communes, parlementaires), sans aucune requête vers un autre domaine, sans rien envoyer ni garder de ce qui
// est tapé (ni stockage local, ni cookie). Les organisations (entreprises, associations) sont cherchées à la demande
// dans les fichiers publiés par préfixe de mot (entites/recherche/), leur ligne de contexte dans un petit morceau par
// début de SIREN. Insensible aux accents et à la casse, tolérante à une faute de
// frappe par mot (deux pour les mots de 8 lettres et plus). Le champ de l'en-tête suit le motif « combobox » de
// l'ARIA 1.2 (WAI-ARIA APG) : suggestions en liste, flèches haut et bas, Entrée, Échap, nombre de suggestions annoncé.
import { fragmentCommune, fragmentDepartement, SEUIL_PAGE_COMMUNE } from '../chemins'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { eur, eur2, h } from '../util'

export const FORMAT_INDEX = 'recherche-2'
/** Ordre des résultats, écrit à l'écran ; l'index porte le même texte (regle_ordre). */
export const REGLE_ORDRE =
  'Ordre des résultats : correspondance du texte seulement (nom identique, puis début du nom, puis mot approchant), à égalité nom le plus court puis ordre alphabétique ; jamais par montant, par taille ni par groupe politique.'

export interface Famille {
  cle: string
  nom: string
  groupe: string
  /** modèle d'adresse : préfixe auquel ajouter la cible, ou « @commune », « @departement » */
  modele?: string
  source?: string
  millesime?: string
}
export interface IndexBrut {
  format: string
  date_donnees?: string
  familles: Famille[]
  entrees: [number, string, string, string?, string?][]
  departements: Record<string, string>
  communes: { famille: number; par_departement: Record<string, string> }
  /** morceaux par type (chemins dans data/), réunis au noyau au chargement */
  morceaux?: Record<string, string>
  organisations?: Organisations
  regle_ordre?: string
}
/** Morceau d'un type : entrées (familles numérotées comme le noyau) et, pour les communes, la chaîne par département. */
export interface MorceauBrut {
  format: string
  entrees: IndexBrut['entrees']
  communes?: Record<string, string>
}
/** Recherche des organisations : fichiers publiés par préfixe de mot, morceaux de contexte par début de SIREN. */
export interface Organisations {
  famille: number
  prefixes: Record<string, string>
  tailles?: Record<string, number>
  frequents: string[]
  canaux: string[]
  contexte: string
  morceaux?: string[]
  total?: number | null
}
/** Entrée d'un fichier de recherche publié : SIREN, dénomination, nombre de sources, département. */
type EntreeOrg = [string, string, number, string | null]
/** Contexte d'une organisation : dénomination, sources, département, année, montant tel que publié, indice de la source. */
type ContexteOrg = [string, number | null, string | null, number | null, number | null, number | null]
interface Entree {
  f: number
  nom: string
  cible: string
  precision: string
  /** mots du nom, des mots-clés et de la précision : numéros dans le vocabulaire du moteur */
  n: number[]
  k: number[]
  p: number[]
  complet: string
  /** taille de la commune (0 à 13), pour départager deux noms semblables */
  poids: number
  page?: boolean
}
export interface Moteur {
  familles: Famille[]
  entrees: Entree[]
  vocabulaire: string[]
  departements: Record<string, string>
  communes: Map<string, Entree>
  date?: string
  comptes: number[]
  /** notes des derniers mots cherchés (la frappe ne change que le dernier mot) */
  memoire: Map<string, Uint8Array>
  organisations?: Organisations
}
export interface Resultat {
  e: Entree
  score: number
}
export interface Recherche {
  texte: string
  resultats: Resultat[]
  /** aucun résultat ne contenait tous les mots : résultats qui en contiennent une partie */
  elargie: boolean
}

/** « Saint-Étienne » et « SAINT ETIENNE » donnent « saint etienne » : minuscules, sans accents ni ponctuation. */
export function normaliser(x: string): string {
  return x
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/œ/g, 'oe')
    .replace(/æ/g, 'ae')
    .replace(/ß/g, 'ss')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}
export const mots = (x: string): string[] => {
  const n = normaliser(x)
  return n ? n.split(' ') : []
}

/** Distance d'édition (substitution, insertion, suppression, inversion de deux lettres), bornée : max + 1 au-delà. */
export function distance(a: string, b: string, max: number): number {
  if (Math.abs(a.length - b.length) > max) return max + 1
  let avant: number[] = []
  let prec = Array.from({ length: b.length + 1 }, (_, j) => j)
  for (let i = 1; i <= a.length; i++) {
    const ligne = [i]
    let min = i
    for (let j = 1; j <= b.length; j++) {
      let v = Math.min(prec[j] + 1, ligne[j - 1] + 1, prec[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, avant[j - 2] + 1)
      ligne[j] = v
      if (v < min) min = v
    }
    if (min > max) return max + 1
    avant = prec
    prec = ligne
  }
  return prec[b.length]
}

const MOTS_VIDES = new Set(['a', 'au', 'aux', 'ce', 'ces', 'd', 'de', 'des', 'du', 'en', 'et', 'l', 'la', 'le', 'les', 'ma', 'mes', 'mon', 'ou', 'par', 'pour', 'sa', 'ses', 'son', 'sur', 'ta', 'tes', 'ton', 'un', 'une'])
const ABREGES: Record<string, string> = { st: 'saint', ste: 'sainte', sts: 'saints', stes: 'saintes' }
const INSEE = /^(\d{5}|2[ab]\d{3})$/
const VIDE: number[] = []

/** Décode l'index (communes comprises) et prépare les mots de chaque entrée. */
export function construireMoteur(brut: IndexBrut): Moteur {
  const familles = brut.familles.map((f) => ({ ...f }))
  const entrees: Entree[] = []
  const communes = new Map<string, Entree>()
  const vocabulaire: string[] = []
  const numeros = new Map<string, number>()
  const coder = (liste: string[]) =>
    liste.map((t) => {
      let i = numeros.get(t)
      if (i === undefined) {
        i = vocabulaire.length
        vocabulaire.push(t)
        numeros.set(t, i)
      }
      return i
    })
  for (const [f, nom, cible, precision = '', cles = ''] of brut.entrees) {
    const n = mots(nom)
    entrees.push({ f, nom, cible, precision, n: coder(n), k: cles ? coder(mots(cles)) : VIDE, p: precision ? coder(mots(precision)) : VIDE, complet: n.join(' '), poids: 0 })
  }
  const fc = brut.communes?.famille ?? -1
  if (fc >= 0) {
    familles[fc].modele = '@commune'
    for (const [dep, chaine] of Object.entries(brut.communes.par_departement)) {
      const precision = `${brut.departements[dep] ?? dep} (${dep})`
      const p = coder(mots(precision))
      let numero = 0
      for (const morceau of chaine.split('|')) {
        const m = /^(\d*)([a-zA-Z])(.+)$/.exec(morceau)
        if (!m) continue
        numero = m[1] ? Number(m[1]) : numero + 1
        const insee = dep + String(numero).padStart(5 - dep.length, '0')
        const n = mots(m[3])
        const e: Entree = { f: fc, nom: m[3], cible: insee, precision, n: coder(n), k: VIDE, p, complet: n.join(' '), poids: m[2].toLowerCase().charCodeAt(0) - 97, page: m[2] < 'a' }
        entrees.push(e)
        communes.set(insee.toLowerCase(), e)
      }
    }
  }
  const comptes = familles.map(() => 0)
  for (const e of entrees) comptes[e.f]++
  if (brut.organisations && familles[brut.organisations.famille]) comptes[brut.organisations.famille] = brut.organisations.total ?? 0
  return { familles, entrees, vocabulaire, departements: brut.departements ?? {}, communes, date: brut.date_donnees, comptes, memoire: new Map(), organisations: brut.organisations }
}

/** Réunit le noyau et ses morceaux par type en un seul index (un morceau absent : son type manque, sans erreur). */
export function assembler(noyau: IndexBrut, morceaux: (MorceauBrut | null)[]): IndexBrut {
  const brut: IndexBrut = { ...noyau, entrees: [...noyau.entrees], communes: { famille: noyau.communes?.famille ?? -1, par_departement: { ...(noyau.communes?.par_departement ?? {}) } } }
  for (const m of morceaux) {
    if (!m || m.format !== noyau.format) continue
    brut.entrees.push(...(m.entrees ?? []))
    Object.assign(brut.communes.par_departement, m.communes ?? {})
  }
  return brut
}

/**
 * Note de chaque mot du vocabulaire pour un mot cherché : 10 identique, 7 début de mot, 5 une faute, 4 contenu ou
 * début de mot avec une faute. Une faute se cherche seulement si l'une des deux premières lettres concorde (ou
 * qu'elles sont inversées) : c'est rapide, et une faute sur la première lettre est rare.
 */
function notesMot(m: Moteur, q: string, dernier: boolean): Uint8Array {
  const cle = `${q}|${dernier}`
  const deja = m.memoire.get(cle)
  if (deja) return deja
  const notes = new Uint8Array(m.vocabulaire.length)
  const seuil = q.length >= 8 ? 2 : q.length >= 4 ? 1 : 0
  const a = q.charCodeAt(0)
  const b = q.charCodeAt(1)
  m.vocabulaire.forEach((v, i) => {
    let s = 0
    if (v === q) s = 10
    else if (v.startsWith(q)) s = q.length >= 3 || dernier ? 7 : 0
    else if (seuil) {
      const c = v.charCodeAt(0)
      const d = v.charCodeAt(1)
      const proche = c === a || d === b || (c === b && d === a)
      if (proche && Math.abs(v.length - q.length) <= seuil && distance(q, v, seuil) <= seuil) s = 5
      else if (v.includes(q)) s = 4
      else if (proche && dernier && v.length > q.length && distance(q, v.slice(0, q.length), 1) <= 1) s = 4
    }
    notes[i] = s
  })
  if (m.memoire.size > 40) m.memoire.clear()
  m.memoire.set(cle, notes)
  return notes
}

const meilleure = (notes: Uint8Array, liste: number[]) => {
  let s = 0
  for (const t of liste) if (notes[t] > s) s = notes[t]
  return s
}

/**
 * Cherche dans l'index. Une entrée doit contenir tous les mots cherchés (hors petits mots « de », « la »...), dont au
 * moins un dans son nom ou ses mots-clés ; la précision (département, mission) ne sert qu'à affiner. Sans résultat,
 * la recherche s'élargit aux entrées qui contiennent une partie des mots. Classement : qualité de la correspondance
 * du texte seulement (nom identique ou commençant par le texte cherché, mot exact, début de mot, faute de frappe) ;
 * à égalité, ordre des familles, nom le plus court, ordre alphabétique (REGLE_ORDRE). Jamais un montant, une taille
 * ni un groupe politique.
 */
export function chercher(m: Moteur, texte: string): Recherche {
  const brut = mots(texte).slice(0, 8)
  const qn = brut.join(' ')
  if (qn.length < 2) return { texte, resultats: [], elargie: false }
  // Les petits mots ne comptent pas, sauf le dernier, peut-être en cours de frappe (« saint et » pour « saint-étienne »).
  const requete = brut.filter((x, i) => !MOTS_VIDES.has(x) || i === brut.length - 1)
  const dernier = requete.length - 1
  const optionnel = requete.map((x, i) => i === dernier && requete.length > 1 && MOTS_VIDES.has(x))
  const notes = requete.map((q, i) => {
    const a = notesMot(m, q, i === dernier)
    const long = ABREGES[q]
    if (!long) return a
    const b = notesMot(m, long, i === dernier)
    return a.map((x, j) => Math.max(x, b[j]))
  })
  const evaluer = (e: Entree, tous: boolean): number => {
    let total = 0
    let principal = false
    let trouves = 0
    for (let i = 0; i < requete.length; i++) {
      let s = meilleure(notes[i], e.n)
      const k = meilleure(notes[i], e.k) * 0.9
      if (k > s) s = k
      if (!s && e.page !== undefined && INSEE.test(requete[i]) && e.cible.toLowerCase() === requete[i]) s = 10
      if (s) principal = true
      else {
        const p = meilleure(notes[i], e.p)
        if (p >= 7) s = p === 10 ? 3 : 2
      }
      if (!s) {
        if (tous && !optionnel[i]) return 0
        continue
      }
      trouves++
      total += s
    }
    if (!principal) return 0
    if (!tous) total += trouves * 10
    if (e.complet === qn) total += 30
    else if (e.complet.startsWith(qn)) total += 12
    return total
  }
  let resultats: Resultat[] = []
  for (const e of m.entrees) {
    const score = evaluer(e, true)
    if (score) resultats.push({ e, score })
  }
  let elargie = false
  if (!resultats.length && requete.length > 1) {
    elargie = true
    for (const e of m.entrees) {
      const score = evaluer(e, false)
      if (score) resultats.push({ e, score })
    }
  }
  resultats.sort(comparer)
  return { texte, resultats, elargie }
}

/** Ordre des résultats : note du texte, puis famille, nom le plus court, ordre alphabétique, cible. */
const comparer = (a: Resultat, b: Resultat) =>
  b.score - a.score || a.e.f - b.e.f || a.e.nom.length - b.e.nom.length || (a.e.nom < b.e.nom ? -1 : a.e.nom > b.e.nom ? 1 : 0) || (a.e.cible < b.e.cible ? -1 : a.e.cible > b.e.cible ? 1 : 0)

/** Note d'un nom pour les mots cherchés, comme pour l'index : 0 si un mot (hors petits mots) manque. */
export function noteNom(nom: string, requete: string[], qn: string): number {
  const n = mots(nom)
  let total = 0
  for (let i = 0; i < requete.length; i++) {
    const q = ABREGES[requete[i]] ?? requete[i]
    const dernier = i === requete.length - 1
    const seuil = q.length >= 8 ? 2 : q.length >= 4 ? 1 : 0
    let s = 0
    for (const v of n) {
      let x = 0
      if (v === q) x = 10
      else if (v.startsWith(q)) x = q.length >= 3 || dernier ? 7 : 0
      else if (seuil && Math.abs(v.length - q.length) <= seuil && distance(q, v, seuil) <= seuil) x = 5
      else if (q.length >= 4 && v.includes(q)) x = 4
      if (x > s) s = x
    }
    if (!s) {
      if (MOTS_VIDES.has(requete[i])) continue
      return 0
    }
    total += s
  }
  const complet = n.join(' ')
  return total + (complet === qn ? 30 : complet.startsWith(qn) ? 12 : 0)
}

/** SIREN à 9 chiffres d'après une saisie (espaces et points retirés ; un SIRET est ramené à son SIREN). */
export function sirenDe(texte: string): string | null {
  const t = texte.replace(/[\s.]/g, '')
  if (/^\d{14}$/.test(t)) return t.slice(0, 9)
  return /^\d{9}$/.test(t) ? t : null
}

/** Fichiers publiés qui peuvent contenir un mot commençant par `w` (règle de entites/index.json, regle_recherche). */
export function fichiersMot(o: Organisations, w: string): string[] {
  const out = new Set<string>()
  const cles = Object.keys(o.prefixes)
  const prefixe = cles.filter((k) => !k.endsWith('_') && w.startsWith(k)).sort((a, b) => b.length - a.length)[0]
  if (prefixe) out.add(o.prefixes[prefixe])
  for (const k of cles) {
    const base = k.endsWith('_') ? k.slice(0, -1) : k
    if (base.startsWith(w) && base !== prefixe) out.add(o.prefixes[k])
  }
  return [...out].sort()
}

/** Morceau de contexte d'un SIREN : le plus long début du SIREN parmi les morceaux. */
export function morceauOrg(o: Organisations, siren: string): string | null {
  const k = (o.morceaux ?? []).filter((x) => siren.startsWith(x)).sort((a, b) => b.length - a.length)[0]
  return k ? `${o.contexte}${k}.json` : null
}

const MAX_FICHIERS_ORG = 4
const sirenLisible = (s: string) => s.replace(/^(\d{3})(\d{3})(\d{3})$/, '$1 $2 $3')
const montant = (x: number) => (Number.isInteger(x) ? eur(x) : eur2(x))

/** Ligne de contexte d'une organisation : SIREN, sources, département, et le montant le plus récent tel que publié (aucun total). */
export function contexteOrg(o: Organisations, siren: string, sources: number | null, dep: string | null, c?: ContexteOrg | null): string {
  const parts = [`SIREN ${sirenLisible(siren)}`]
  if (sources) parts.push(`${sources} source${sources > 1 ? 's' : ''} du site`)
  if (dep) parts.push(`département ${dep}`)
  if (c && c[3] != null && c[4] != null) {
    const canal = c[5] != null ? o.canaux[c[5]] : null
    parts.push(`dernier montant publié : ${montant(c[4])} en ${c[3]}${canal ? ` (${canal})` : ''}`)
  }
  return parts.join(' · ')
}

/**
 * Organisations qui ont une fiche : fichiers publiés du mot le plus rare (au plus 4 fichiers), puis note du nom ;
 * un SIREN (ou SIRET) exact mène à sa fiche. Les `contexte` premières reçoivent leur montant publié le plus récent.
 */
export async function chercherOrganisations(m: Moteur, texte: string, contexte = 0): Promise<Resultat[]> {
  const o = m.organisations
  if (!o || !m.familles[o.famille]) return []
  const f = o.famille
  const entree = (siren: string, nom: string, precision: string): Entree => ({ f, nom, cible: siren, precision, n: VIDE, k: VIDE, p: VIDE, complet: mots(nom).join(' '), poids: 0 })
  const siren = sirenDe(texte)
  if (siren) {
    const chemin = morceauOrg(o, siren)
    const c = chemin ? (await chargerSiPresent<{ entrees: Record<string, ContexteOrg> }>(chemin))?.entrees?.[siren] : null
    return c ? [{ e: entree(siren, c[0], contexteOrg(o, siren, c[1], c[2], c)), score: 40 }] : []
  }
  const brut = mots(texte).slice(0, 8)
  const qn = brut.join(' ')
  const requete = brut.filter((x, i) => !MOTS_VIDES.has(x) || i === brut.length - 1)
  const frequents = new Set(o.frequents)
  const poids = (fichiers: string[]) => {
    const parFichier = new Map(Object.entries(o.prefixes).map(([k, x]) => [x, o.tailles?.[k] ?? 1e6]))
    return fichiers.reduce((a, x) => a + (parFichier.get(x) ?? 1e6), 0)
  }
  const choix = requete
    .filter((w) => w.length >= 3 && !frequents.has(w) && !MOTS_VIDES.has(w))
    .map((w) => ({ w, f: fichiersMot(o, ABREGES[w] ?? w) }))
    .filter((x) => x.f.length > 0 && x.f.length <= MAX_FICHIERS_ORG)
    .sort((a, b) => poids(a.f) - poids(b.f) || b.w.length - a.w.length || (a.w < b.w ? -1 : 1))[0]
  if (!choix) return []
  const fichiers = await Promise.all(choix.f.map((x) => chargerSiPresent<{ entrees: EntreeOrg[] }>(x).catch(() => null)))
  const vus = new Map<string, EntreeOrg>()
  for (const x of fichiers) for (const e of x?.entrees ?? []) if (Array.isArray(e) && /^\d{9}$/.test(e[0])) vus.set(e[0], e)
  const out: Resultat[] = []
  for (const e of vus.values()) {
    const score = noteNom(e[1], requete, qn)
    if (score) out.push({ e: entree(e[0], e[1], contexteOrg(o, e[0], e[2], e[3])), score })
  }
  out.sort(comparer)
  // Montant publié le plus récent des premiers résultats : morceaux de contexte (quelques Ko chacun).
  const premiers = out.slice(0, contexte)
  const chemins = [...new Set(premiers.map((r) => morceauOrg(o, r.e.cible)).filter((x): x is string => !!x))]
  const lus = new Map(await Promise.all(chemins.map(async (c) => [c, (await chargerSiPresent<{ entrees: Record<string, ContexteOrg> }>(c).catch(() => null))?.entrees ?? {}] as const)))
  for (const r of premiers) {
    const c = lus.get(morceauOrg(o, r.e.cible) ?? '')?.[r.e.cible]
    const e = vus.get(r.e.cible)!
    if (c) r.e.precision = contexteOrg(o, r.e.cible, e[2], e[3], c)
  }
  return out
}

/** Recherche complète : index (noyau et morceaux) et organisations, dans un seul classement par la note du texte. */
export async function chercherTout(m: Moteur, texte: string, contexte = 0): Promise<Recherche> {
  const r = chercher(m, texte)
  const org = await chercherOrganisations(m, texte, contexte)
  if (!org.length) return r
  // Une recherche élargie (mots en partie seulement) passe après des organisations qui ont tous les mots.
  const resultats = (r.elargie ? org : [...r.resultats, ...org]).sort(comparer)
  return { texte, resultats, elargie: r.elargie && !org.length }
}

/** Adresse interne d'un résultat. */
export function adresse(m: Moteur, e: Entree): string {
  if (e.cible.startsWith('#')) return e.cible
  const modele = m.familles[e.f]?.modele
  if (modele === '@commune') {
    const c = m.communes.get(e.cible.toLowerCase())
    return c ? fragmentCommune(c.cible, c.nom, c.page ? SEUIL_PAGE_COMMUNE + 1 : 0) : lien('/local/commune', { insee: e.cible })
  }
  if (modele === '@departement') return fragmentDepartement(e.cible, m.departements[e.cible] ?? e.nom)
  return `${modele ?? '#/'}${encodeURIComponent(e.cible || e.nom)}`
}

/** Ligne de précision d'un résultat (famille, département, mission...). */
export function precision(m: Moteur, e: Entree, avecFamille = true): string {
  const f = m.familles[e.f]
  // Commune : son département ; entrée qui mène à une commune (intercommunalité) : département du siège et commune.
  if (e.page !== undefined) return avecFamille ? `${f.nom} · ${e.precision}` : e.precision
  if (f.modele === '@commune') {
    const c = m.communes.get(e.cible.toLowerCase())
    const dep = m.departements[e.precision] ? ` (${m.departements[e.precision]})` : ''
    return `${f.nom}${dep}${c ? ` · présentée sur la page de ${c.nom}, sa commune la plus peuplée` : ''}`
  }
  if (f.cle === 'page') return avecFamille || !e.precision ? f.nom : e.precision
  if (f.cle === 'organisation' && avecFamille) return `${f.nom} · ${e.precision}`
  return e.precision || f.nom
}

/** Suggestions variées : les meilleurs résultats, pas plus de parFamille d'une même famille. */
export function selection(resultats: Resultat[], n: number, parFamille: number): Resultat[] {
  const vus = new Map<number, number>()
  const out: Resultat[] = []
  for (const r of resultats) {
    const c = vus.get(r.e.f) ?? 0
    if (c >= parFamille) continue
    vus.set(r.e.f, c + 1)
    out.push(r)
    if (out.length >= n) break
  }
  return out
}

/** Résultats par famille, la famille du meilleur résultat d'abord. */
export function grouper(resultats: Resultat[]): { f: number; resultats: Resultat[] }[] {
  const groupes = new Map<number, Resultat[]>()
  for (const r of resultats) {
    const g = groupes.get(r.e.f)
    if (g) g.push(r)
    else groupes.set(r.e.f, [r])
  }
  return [...groupes.entries()].map(([f, liste]) => ({ f, resultats: liste }))
}

let promesse: Promise<Moteur | null> | null = null
let pret = false
/** Charge l'index (une seule fois) ; null s'il manque ou n'est pas au format attendu (nouvel essai au prochain appel). */
export function chargerMoteur(): Promise<Moteur | null> {
  promesse ??= chargerSiPresent<IndexBrut>('_recherche.json')
    .then(async (brut) => {
      if (brut?.format !== FORMAT_INDEX) return null
      const morceaux = await Promise.all(Object.values(brut.morceaux ?? {}).map((c) => chargerSiPresent<MorceauBrut>(c).catch(() => null)))
      return construireMoteur(assembler(brut, morceaux))
    })
    .catch(() => null)
    .then((m) => {
      if (!m) promesse = null
      pret = !!m
      return m
    })
  return promesse
}
/** L'index est-il déjà chargé ? */
export const moteurCharge = () => pret
/** Oublie l'index chargé (tests). */
export function oublierMoteur() {
  promesse = null
  pret = false
}

export const pluriel = (n: number, mot: string) => `${new Intl.NumberFormat('fr-FR').format(n)} ${mot}${n > 1 ? 's' : ''}`

/** Branche le champ « Rechercher » de l'en-tête : suggestions au fil de la saisie, page de résultats sur Entrée. */
export function brancherEntete(form = document.getElementById('recherche-entete') as HTMLFormElement | null) {
  const champ = form?.querySelector<HTMLInputElement>('input[type="search"]')
  if (!form || !champ || form.dataset.branche) return
  form.dataset.branche = 'oui'
  const liste = document.createElement('ul')
  liste.id = 'recherche-suggestions'
  liste.className = 'recherche-suggestions'
  liste.setAttribute('role', 'listbox')
  liste.setAttribute('aria-label', 'Suggestions')
  liste.hidden = true
  const consigne = document.createElement('p')
  consigne.id = 'recherche-consigne-entete'
  consigne.className = 'visuellement-cache'
  consigne.textContent = 'Suggestions au fil de la saisie : flèches haut et bas pour les parcourir, Entrée pour ouvrir, Échap pour fermer. Touche « / » pour revenir à ce champ depuis n’importe où dans la page.'
  // Règle d'ordre des suggestions, écrite sous la liste quand elle est ouverte.
  const regle = document.createElement('p')
  regle.id = 'recherche-regle-entete'
  regle.className = 'recherche-regle'
  regle.textContent = REGLE_ORDRE
  regle.hidden = true
  const etat = document.createElement('p')
  etat.className = 'visuellement-cache'
  etat.setAttribute('role', 'status')
  // Panneau sous le champ : la liste des suggestions, puis la règle d'ordre.
  const panneau = document.createElement('div')
  panneau.className = 'recherche-panneau'
  panneau.append(liste, regle)
  champ.parentElement!.append(panneau)
  form.append(consigne, etat)
  champ.setAttribute('role', 'combobox')
  champ.setAttribute('aria-autocomplete', 'list')
  champ.setAttribute('aria-expanded', 'false')
  champ.setAttribute('aria-controls', liste.id)
  champ.setAttribute('aria-describedby', consigne.id)
  champ.setAttribute('aria-keyshortcuts', '/')

  let options: string[] = []
  let actif = -1
  let minuterie = 0
  let tour = 0
  const fermer = () => {
    liste.hidden = true
    regle.hidden = true
    champ.setAttribute('aria-expanded', 'false')
    champ.removeAttribute('aria-activedescendant')
    actif = -1
  }
  const activer = (i: number) => {
    actif = i
    liste.querySelectorAll<HTMLElement>('[role="option"]').forEach((li, j) => li.setAttribute('aria-selected', String(j === i)))
    const li = i >= 0 ? (liste.children[i] as HTMLElement | undefined) : undefined
    if (li) {
      champ.setAttribute('aria-activedescendant', li.id)
      li.scrollIntoView?.({ block: 'nearest' })
    } else champ.removeAttribute('aria-activedescendant')
  }
  const aller = (fragment: string) => {
    fermer()
    champ.value = ''
    etat.textContent = ''
    location.hash = fragment
  }
  const proposer = async () => {
    const moi = ++tour
    const texte = champ.value.trim()
    if (normaliser(texte).length < 2) {
      options = []
      liste.innerHTML = ''
      etat.textContent = ''
      fermer()
      return
    }
    if (!pret) etat.textContent = 'Chargement de la recherche…'
    const m = await chargerMoteur()
    if (moi !== tour) return
    if (!m) {
      etat.textContent = 'La recherche n’est pas disponible pour le moment.'
      return
    }
    const r = await chercherTout(m, texte, 4)
    if (moi !== tour) return
    const choix = selection(r.resultats, 8, 4)
    const tous = lien('/recherche', { q: texte })
    options = [...choix.map((r) => adresse(m, r.e)), tous]
    liste.innerHTML =
      choix
        .map(
          (r, i) =>
            `<li role="option" id="recherche-option-${i}" aria-selected="false" data-i="${i}"><span class="recherche-nom">${h(r.e.nom)}</span><span class="visuellement-cache">, </span><span class="recherche-precision">${h(precision(m, r.e))}</span></li>`,
        )
        .join('') +
      `<li role="option" id="recherche-option-${choix.length}" aria-selected="false" data-i="${choix.length}" class="recherche-tous">Tous les résultats pour « ${h(texte)} »</li>`
    actif = -1
    champ.removeAttribute('aria-activedescendant')
    liste.hidden = false
    regle.hidden = !choix.length
    champ.setAttribute('aria-expanded', 'true')
    etat.textContent = choix.length ? `${pluriel(choix.length, 'suggestion')}, et le lien vers tous les résultats.` : `Aucune suggestion pour « ${texte} » : Entrée pour la page de recherche.`
  }
  champ.addEventListener('input', () => {
    window.clearTimeout(minuterie)
    minuterie = window.setTimeout(proposer, 120)
  })
  champ.addEventListener('keydown', (e) => {
    const n = options.length
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!n) return
      e.preventDefault()
      if (liste.hidden) {
        liste.hidden = false
        regle.hidden = n <= 1
        champ.setAttribute('aria-expanded', 'true')
      }
      activer(e.key === 'ArrowDown' ? (actif + 1) % n : actif <= 0 ? n - 1 : actif - 1)
    } else if (e.key === 'Escape' && !liste.hidden) {
      e.preventDefault()
      fermer()
    }
  })
  // Un clic dans la liste garde le focus dans le champ (motif combobox), puis ouvre la suggestion.
  liste.addEventListener('mousedown', (e) => e.preventDefault())
  liste.addEventListener('click', (e) => {
    const li = (e.target as Element).closest<HTMLElement>('[data-i]')
    if (li) aller(options[Number(li.dataset.i)])
  })
  form.addEventListener('submit', (e) => {
    e.preventDefault()
    window.clearTimeout(minuterie)
    const texte = champ.value.trim()
    aller(actif >= 0 && options[actif] ? options[actif] : lien('/recherche', texte ? { q: texte } : {}))
  })
  // La liste se ferme dès que le champ perd le focus (Tab, clic ailleurs) ; un clic dans la liste ne le lui retire pas.
  champ.addEventListener('blur', fermer)
  // Raccourci « / » : donne le focus au champ, sauf pendant une saisie ailleurs (champ, zone de texte, liste).
  document.addEventListener('keydown', (e) => {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return
    const t = e.target as HTMLElement | null
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return
    e.preventDefault()
    champ.focus()
    champ.select()
  })
}

// Recherche dans tout le site, faite dans le navigateur : l'index est construit au build (scripts/index-recherche.mjs)
// et lu seulement à la première saisie (data/_recherche.json, environ 0,3 Mo compressé), sans aucune requête vers un
// autre domaine ni rien envoyer de ce qui est tapé. Insensible aux accents et à la casse, tolérante à une faute de
// frappe par mot (deux pour les mots de 8 lettres et plus). Le champ de l'en-tête suit le motif « combobox » de
// l'ARIA 1.2 (WAI-ARIA APG) : suggestions en liste, flèches haut et bas, Entrée, Échap, nombre de suggestions annoncé.
import { fragmentCommune, fragmentDepartement, SEUIL_PAGE_COMMUNE } from '../chemins'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { h } from '../util'

export const FORMAT_INDEX = 'recherche-1'

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
}
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
  return { familles, entrees, vocabulaire, departements: brut.departements ?? {}, communes, date: brut.date_donnees, comptes, memoire: new Map() }
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
 * la recherche s'élargit aux entrées qui contiennent une partie des mots. Classement : qualité de la correspondance,
 * nom identique ou commençant par le texte cherché, puis taille de la commune ; à égalité, ordre des familles.
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
    return total + e.poids * 0.8
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
  resultats.sort((a, b) => b.score - a.score || a.e.f - b.e.f || a.e.nom.length - b.e.nom.length || (a.e.nom < b.e.nom ? -1 : a.e.nom > b.e.nom ? 1 : 0))
  return { texte, resultats, elargie }
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
    .then((brut) => (brut?.format === FORMAT_INDEX ? construireMoteur(brut) : null))
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
  consigne.textContent = 'Suggestions au fil de la saisie : flèches haut et bas pour les parcourir, Entrée pour ouvrir, Échap pour fermer.'
  const etat = document.createElement('p')
  etat.className = 'visuellement-cache'
  etat.setAttribute('role', 'status')
  champ.parentElement!.append(liste)
  form.append(consigne, etat)
  champ.setAttribute('role', 'combobox')
  champ.setAttribute('aria-autocomplete', 'list')
  champ.setAttribute('aria-expanded', 'false')
  champ.setAttribute('aria-controls', liste.id)
  champ.setAttribute('aria-describedby', consigne.id)

  let options: string[] = []
  let actif = -1
  let minuterie = 0
  let tour = 0
  const fermer = () => {
    liste.hidden = true
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
    const choix = selection(chercher(m, texte).resultats, 8, 4)
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
}

// Sigles expliqués, en amélioration progressive : après le rendu d'un écran, la première occurrence de chaque sigle
// du glossaire (src/glossaire.json) dans le contenu principal devient un lien vers sa définition (/methode/glossaire),
// la forme développée dans un <abbr title> (survol) et dans le nom accessible du lien (lecteurs d'écran), le lien
// étant atteignable au clavier. Le texte de la page ne change pas (textContent identique) : ni ajout visible, ni
// modification des titres, liens, boutons, champs, sommaires de <details>, graphiques ou fils d'Ariane.
// Sens ambigus (ARS : agence régionale de santé ou allocation de rentrée scolaire) : le sens est choisi d'après les
// mots de la page (champ « indices ») ; sans indice, le sigle n'est pas marqué plutôt que mal expliqué.

export interface TermeGlossaire {
  id: string
  terme: string
  /** graphie principale du sigle (« LFI », « Insee ») ; absent pour un mot (« Mission ») */
  sigle?: string
  /** autres graphies reconnues (« INSEE », « Smic ») */
  variantes?: string[]
  /** forme développée, en minuscules sauf nom propre */
  forme?: string
  /** mots dont l'un doit figurer dans la page pour que ce sens y soit retenu (sens ambigu, sigle de deux lettres) */
  indices?: string[]
  definition: string
  source: { nom: string; url: string }
  /** renvois vers d'autres entrées (identifiants) */
  voir?: string[]
}

export interface Glossaire {
  termes: TermeGlossaire[]
  /** mots en capitales qui ne sont pas des sigles (types d'organismes, noms de fichiers) */
  pas_des_sigles?: { mot: string; raison: string }[]
}

export const ROUTE_GLOSSAIRE = '/methode/glossaire'
/** Adresse interne de la définition d'un terme (l'écran du glossaire place le focus sur l'entrée). */
export const lienTerme = (id: string) => `#${ROUTE_GLOSSAIRE}?terme=${encodeURIComponent(id)}`

/** Texte comparable : minuscules, sans accents, apostrophes droites, espaces simples. */
export const normaliser = (x: string) =>
  x.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[’`]/g, "'").replace(/\s+/g, ' ')

export interface Index {
  motif: RegExp
  /** graphie vers ses sens possibles */
  sens: Map<string, TermeGlossaire[]>
}

const echapper = (x: string) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

export function indexer(g: Glossaire): Index {
  const sens = new Map<string, TermeGlossaire[]>()
  for (const t of g.termes) {
    if (!t.sigle || !t.forme) continue
    for (const graphie of [t.sigle, ...(t.variantes ?? [])]) sens.set(graphie, [...(sens.get(graphie) ?? []), t])
  }
  const graphies = [...sens.keys()].sort((a, b) => b.length - a.length).map(echapper)
  // Ni lettre, ni chiffre, ni tiret, ni soulignement de part et d'autre : « NFP-LFI », « PLF2025 », « ex-TICPE » restent tels quels.
  // (Pas d'assertion arrière : groupe de préfixe, pour les navigateurs qui ne la connaissent pas.)
  const motif = new RegExp(`(^|[^\\p{L}\\p{N}_-])(${graphies.join('|') || '(?!)'})(?![\\p{L}\\p{N}_-])`, 'gu')
  return { motif, sens }
}

const BALISES_EXCLUES = new Set([
  'A', 'BUTTON', 'LABEL', 'SUMMARY', 'SELECT', 'OPTION', 'OPTGROUP', 'TEXTAREA', 'INPUT', 'SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE',
  'CODE', 'PRE', 'KBD', 'SAMP', 'VAR', 'ABBR', 'DFN', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'IFRAME', 'CANVAS', 'OBJECT', 'VIDEO', 'AUDIO',
  'TITLE', 'MATH', 'SVG', 'DIALOG',
])
const ROLES_EXCLUS = new Set(['button', 'link', 'tab', 'menuitem', 'option', 'switch', 'checkbox', 'radio', 'heading', 'img', 'math', 'textbox', 'combobox', 'searchbox', 'slider', 'spinbutton', 'tooltip'])
const CLASSES_EXCLUES = ['fil-ariane', 'voir-aussi', 'surligne']
const XHTML = 'http://www.w3.org/1999/xhtml'

function exclu(el: Element): boolean {
  if (el.namespaceURI && el.namespaceURI !== XHTML) return true
  if (BALISES_EXCLUES.has(el.tagName.toUpperCase())) return true
  if (el.hasAttribute('hidden') || el.hasAttribute('inert') || el.getAttribute('aria-hidden') === 'true') return true
  if (el.hasAttribute('data-sans-sigles') || el.getAttribute('translate') === 'no') return true
  const editable = el.getAttribute('contenteditable')
  if (editable !== null && editable !== 'false') return true
  const role = el.getAttribute('role')
  if (role && ROLES_EXCLUS.has(role)) return true
  return CLASSES_EXCLUES.some((c) => el.classList.contains(c))
}

/** Nœuds texte de la zone, dans l'ordre du document, hors éléments exclus. */
function textes(racine: Element): Text[] {
  const out: Text[] = []
  const marcher = (n: Node) => {
    for (let c = n.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 3) out.push(c as Text)
      else if (c.nodeType === 1 && !exclu(c as Element)) marcher(c)
    }
  }
  if (!exclu(racine)) marcher(racine)
  return out
}

// Adresses, chemins et noms de domaine : jamais de sigle marqué dedans.
const ADRESSES = /\S*[/\\]\S*|\bhttps?:\S+|\b[\w.-]+\.(?:fr|com|org|eu|net|io|int)\b\S*/g
const plages = (texte: string): [number, number][] => [...texte.matchAll(ADRESSES)].map((m) => [m.index!, m.index! + m[0].length])

const MOTS_VIDES = new Set(['a', 'au', 'aux', 'd', 'de', 'des', 'du', 'en', 'et', 'l', 'la', 'le', 'les', 'par', 'pour', 'sur', 'un', 'une'])
const sansAccent = (x: string) => x.normalize('NFD').replace(/[̀-ͯ]/g, '')

/** Les lettres du sigle se retrouvent, dans l'ordre, parmi les initiales des mots qui précèdent (« Allocation d'aide au retour à l'emploi » : ARE). */
function initialesCorrespondent(avant: string, sigle: string): boolean {
  const initiales = avant
    .split(/[^\p{L}]+/u)
    .filter((m) => m && !MOTS_VIDES.has(sansAccent(m).toLowerCase()))
    .slice(-12)
    .map((m) => sansAccent(m[0]).toUpperCase())
  const lettres = sansAccent(sigle).toUpperCase()
  let i = 0
  for (const c of initiales) if (i < lettres.length && c === lettres[i]) i++
  return i === lettres.length
}

/**
 * Sigle déjà expliqué à cet endroit : « forme développée (SIGLE) », « forme développée (SIGLE, …) » quand les initiales
 * correspondent, « SIGLE (forme développée) » ou « SIGLE - Forme développée ».
 */
export function expliqueSurPlace(texte: string, debut: number, fin: number): boolean {
  const avant = texte.slice(0, debut)
  const apres = texte.slice(fin)
  const ouvrante = /\p{L}{2,}[^()]*\s\(\s*$/u.test(avant)
  if (ouvrante && /^\s*\)/.test(apres)) return true
  if (ouvrante && /^\s*(?:[,;]|et\s)/.test(apres) && initialesCorrespondent(avant.replace(/\(\s*$/, ''), texte.slice(debut, fin))) return true
  return /^[\s ]?\(\s*\p{L}{3,}/u.test(apres) || /^\s[-–]\s\p{Lu}\p{Ll}/u.test(apres)
}

/** Le sigle est expliqué au moins une fois dans ce texte (un nœud) : aucune de ses occurrences n'y est à expliquer. */
export function expliqueDansLeTexte(texte: string, graphie: string): boolean {
  const motif = new RegExp(`(^|[^\\p{L}\\p{N}_-])${echapper(graphie)}(?![\\p{L}\\p{N}_-])`, 'gu')
  for (const m of texte.matchAll(motif)) {
    const debut = m.index! + m[1].length
    if (expliqueSurPlace(texte, debut, debut + graphie.length)) return true
  }
  return false
}

/** Valeur seule dans une cellule de tableau (code de nuance, statut) : laissée telle quelle. */
function celluleEntiere(noeud: Text, graphie: string): boolean {
  const cellule = noeud.parentElement?.closest('td, th')
  return !!cellule && (cellule.textContent ?? '').trim() === graphie
}

/** Sens retenus d'après le texte de la page ; vide si aucun ne convient (le sigle n'est alors pas marqué). */
export function choisir(candidats: TermeGlossaire[], contexte: string): TermeGlossaire[] {
  const compatibles = candidats.filter((t) => !t.indices?.length || t.indices.some((i) => contexte.includes(normaliser(i))))
  if (compatibles.length <= 1) return compatibles
  const parForme = compatibles.filter((t) => t.forme && contexte.includes(normaliser(t.forme)))
  return parForme.length ? parForme : compatibles
}

function lienSigle(doc: Document, graphie: string, cle: string, sens: TermeGlossaire[]): HTMLAnchorElement {
  const forme = sens.map((t) => t.forme).join(' ou ')
  const plusieurs = sens.length > 1 ? ' selon le contexte' : ''
  const a = doc.createElement('a')
  a.className = 'glossaire-sigle'
  a.setAttribute('href', lienTerme(sens[0].id))
  a.setAttribute('aria-label', `${graphie} : ${forme}${plusieurs}, définition dans le glossaire`)
  const abbr = doc.createElement('abbr')
  abbr.setAttribute('title', `${forme}${plusieurs}`)
  abbr.setAttribute('data-sigle', cle)
  abbr.textContent = graphie
  a.append(abbr)
  return a
}

/** Marque la première occurrence de chaque sigle connu dans la zone ; renvoie le nombre de sigles marqués. */
export function marquer(zone: Element, index: Index): number {
  const deja = new Set(Array.from(zone.querySelectorAll('abbr[data-sigle]')).map((a) => a.getAttribute('data-sigle')!))
  let contexte: string | null = null
  let n = 0
  for (const noeud of textes(zone)) {
    let courant: Text | null = noeud
    while (courant) {
      const texte = courant.nodeValue ?? ''
      if (!texte.trim()) break
      const adresses = plages(texte)
      index.motif.lastIndex = 0
      let suivant: Text | null = null
      for (let m = index.motif.exec(texte); m; m = index.motif.exec(texte)) {
        const graphie = m[2]
        const debut = m.index + m[1].length
        const fin = debut + graphie.length
        const candidats = index.sens.get(graphie)!
        const cle = candidats[0].sigle!
        if (deja.has(cle)) continue
        if (adresses.some(([a, b]) => debut < b && fin > a)) continue
        if (expliqueDansLeTexte(texte, graphie) || celluleEntiere(courant, graphie)) continue
        contexte ??= normaliser(zone.textContent ?? '')
        const sens = choisir(candidats, contexte)
        if (!sens.length) continue
        const milieu: Text = courant.splitText(debut)
        suivant = milieu.splitText(graphie.length)
        milieu.replaceWith(lienSigle(courant.ownerDocument, graphie, cle, sens))
        deja.add(cle)
        n++
        break
      }
      courant = suivant
    }
  }
  return n
}

let chargement: Promise<Index | null> | null = null
/** Glossaire chargé à part (le premier affichage n'attend pas ce fichier), une seule fois ; null s'il est illisible. */
export function chargerIndex(): Promise<Index | null> {
  chargement ??= import('../glossaire.json').then((m) => indexer(m.default as unknown as Glossaire)).catch(() => null)
  return chargement
}

/**
 * Crochet du routeur (src/routeur.ts) : marque la zone une fois l'écran complet (suite comprise) et renvoie la suite
 * prolongée. Une erreur de l'écran est transmise telle quelle ; une erreur du marquage n'interrompt jamais l'affichage.
 */
export function marquerSigles(zone: Element, suite?: Promise<unknown> | null): Promise<void> {
  const marquage = () =>
    chargerIndex().then((index) => {
      if (!index) return
      try {
        marquer(zone, index)
      } catch (e) {
        console.error(e)
      }
    })
  return suite ? suite.then(marquage, (e) => marquage().then(() => Promise.reject(e))) : marquage()
}

// Chargement lancé dès le démarrage, en parallèle de celui du premier écran.
if (typeof window !== 'undefined') void chargerIndex()

// Recherche « Ma commune » : code postal ou nom, dans les fichiers site/data/ma_commune (base officielle des codes
// postaux de La Poste, contrat 2.71), lus à la demande ; aucune requête hors du site, rien n'est envoyé ni conservé.
// Module léger (sans les blocs de la synthèse) : aussi branché sur la page « Chez moi » (/local).
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { entier, h } from '../util'

const MAX_PROPOSITIONS = 12
const MAX_FICHIERS_NOMS = 4


export interface IndexMaCommune {
  millesime: string
  source: string
  date_sources: string
  prefixes_cp: string[]
  cles_noms: string[]
  couverture: Record<string, number | string[]>
  arrondissements: Record<string, { nom: string; arrondissements: number; note: string }>
  hors_perimetre: { motif: string; territoires: Record<string, string[]>; codes_postaux: number }
  regles: string[]
  limites: string[]
}
type LigneCp = [string, string, string, number | null, string | null]
type LigneNom = [string, string, string, number | null, string, 'commune' | 'localite' | 'arrondissement']
export interface Proposition {
  insee: string
  nom: string
  dep: string
  population: number | null
  /** Codes postaux (nom) ou code postal saisi (code postal). */
  cps: string
  type: 'commune' | 'localite' | 'arrondissement'
  /** Commune de rattachement (localité, arrondissement) ou précision de La Poste (arrondissement, localités). */
  precision: string | null
}
export interface Resultat {
  propositions: Proposition[]
  /** Nombre total de réponses (au-delà de MAX_PROPOSITIONS, seules les premières sont listées). */
  total: number
  message: string | null
}

/** Même règle que pipeline/ma_commune.py (norm) : sans accents, minuscules, ponctuation en espaces, st/ste développés. */
export function normaliser(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/œ/g, 'oe')
    .replace(/æ/g, 'ae')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .split(' ')
    .filter(Boolean)
    .map((m) => (m === 'st' ? 'saint' : m === 'ste' ? 'sainte' : m))
    .join(' ')
}
export const compacte = (cle: string) => cle.replace(/ /g, '')

/** Fichiers de noms à lire pour une saisie : clés préfixes de la saisie, ou qui la prolongent (au plus quatre). */
export function fichiersNoms(saisie: string, cles: string[]): string[] {
  const q = compacte(normaliser(saisie))
  if (q.length < 2) return []
  const avant = cles.filter((k) => q.startsWith(k))
  const apres = cles.filter((k) => k.startsWith(q) && !avant.includes(k))
  const tous = [...avant, ...apres]
  return tous.length <= MAX_FICHIERS_NOMS ? tous : avant
}

const DEP_FINAL = /^(.*?)[\s,(]+(\d{2,3}|2[AaBb])\)?$/

/** Ordre neutre : nom identique, puis qui commence par la saisie, puis qui la contient ; alphabétique, puis département. */
function ordonner(liste: Proposition[], q: string): Proposition[] {
  const rang = (p: Proposition) => {
    const k = normaliser(p.nom)
    return k === q ? 0 : k.startsWith(q) || compacte(k).startsWith(compacte(q)) ? 1 : 2
  }
  return liste
    .map((p) => ({ p, r: rang(p) }))
    .sort((a, b) => a.r - b.r || a.p.nom.localeCompare(b.p.nom, 'fr') || a.p.dep.localeCompare(b.p.dep) || a.p.insee.localeCompare(b.p.insee))
    .map((x) => x.p)
}

export async function chargerIndex(): Promise<IndexMaCommune | null> {
  return chargerSiPresent<IndexMaCommune>('ma_commune/index.json')
}

/** Recherche dans les fichiers du site : code postal (5 chiffres ou début), nom, ou nom suivi du département. */
export async function chercher(saisie: string, idx?: IndexMaCommune | null): Promise<Resultat> {
  const index = idx ?? (await chargerIndex())
  const vide = (message: string | null): Resultat => ({ propositions: [], total: 0, message })
  if (!index) return vide('La recherche par code postal n’est pas disponible pour le moment.')
  const brut = saisie.trim()
  if (!brut) return vide(null)
  const chiffres = brut.replace(/\s/g, '')
  if (/^\d{2,5}$/.test(chiffres)) {
    const prefixe = chiffres.slice(0, 2)
    const horsExact = Object.entries(index.hors_perimetre.territoires).find(([, l]) => l.includes(chiffres))
    if (horsExact) return vide(`Code postal de ${horsExact[0]} : ${index.hors_perimetre.motif}.`)
    if (!index.prefixes_cp.includes(prefixe)) {
      const hors = Object.entries(index.hors_perimetre.territoires).find(([, cps]) => cps.some((c) => c.startsWith(chiffres)))
      return vide(hors ? `Code postal de ${hors[0]} : ${index.hors_perimetre.motif}.` : 'Aucun code postal ne commence ainsi.')
    }
    const f = await chargerSiPresent<{ codes_postaux: Record<string, LigneCp[]> }>(`ma_commune/cp/${prefixe}.json`)
    if (!f) return vide('Les codes postaux ne sont pas disponibles pour le moment.')
    const cps = Object.keys(f.codes_postaux)
      .filter((c) => c.startsWith(chiffres))
      .sort()
    const toutes: Proposition[] = cps.flatMap((cp) => f.codes_postaux[cp].map(([insee, nom, dep, population, precision]) => ({ insee, nom, dep, population, cps: cp, type: 'commune' as const, precision })))
    if (!toutes.length) return vide(chiffres.length === 5 ? 'Ce code postal n’est pas dans la base officielle de La Poste.' : 'Aucun code postal ne commence ainsi.')
    const message = chiffres.length === 5 && toutes.length > 1 ? `Ce code postal dessert ${toutes.length} communes : choisis la tienne.` : null
    return { propositions: toutes.slice(0, MAX_PROPOSITIONS), total: toutes.length, message }
  }
  // Nom, éventuellement suivi du numéro du département (« Grandchamp 44 »).
  const m = DEP_FINAL.exec(brut)
  const nom = m ? m[1] : brut
  const depFiltre = m ? m[2].toUpperCase() : null
  const q = normaliser(nom)
  if (compacte(q).length < 2) return vide('Tape au moins deux lettres ou le début du code postal.')
  const fichiers = fichiersNoms(q, index.cles_noms)
  if (!fichiers.length) return vide(index.cles_noms.some((k) => k.startsWith(compacte(q))) ? 'Continue de taper : plusieurs centaines de noms commencent ainsi.' : 'Aucune commune ne porte ce nom.')
  const lus = await Promise.all(fichiers.map((k) => chargerSiPresent<{ noms: LigneNom[] }>(`ma_commune/noms/${k}.json`)))
  const nomsCommunes = new Map<string, string>()
  for (const f of lus) for (const l of f?.noms ?? []) if (l[5] === 'commune') nomsCommunes.set(l[0], l[1])
  const cq = compacte(q)
  const toutes: Proposition[] = []
  for (const f of lus)
    for (const [insee, n, dep, population, cps, type] of f?.noms ?? []) {
      if (depFiltre && dep !== depFiltre) continue
      const k = normaliser(n)
      if (!(k.startsWith(q) || compacte(k).startsWith(cq) || k.includes(` ${q}`))) continue
      toutes.push({ insee, nom: n, dep, population, cps, type, precision: type === 'commune' ? null : (nomsCommunes.get(insee) ?? null) })
    }
  if (!toutes.length) return vide(depFiltre ? `Aucune commune de ce nom dans le département ${depFiltre}.` : 'Aucune commune ne porte ce nom.')
  const ordre = ordonner(toutes, q)
  return { propositions: ordre.slice(0, MAX_PROPOSITIONS), total: ordre.length, message: null }
}

const libelleProposition = (p: Proposition, idx: IndexMaCommune | null) => {
  const lieu = `${p.dep}`
  if (p.type === 'arrondissement') return `${p.nom} : la commune ${p.precision ?? ''} (${lieu})${p.cps ? `, ${p.cps}` : ''}`
  if (p.type === 'localite') return `${p.nom} (${p.cps}) : localité rattachée à ${p.precision ?? 'une commune'} (${lieu})`
  const arr = idx?.arrondissements[p.insee]
  const pop = p.population !== null ? `, ${entier(p.population)} habitants` : ''
  return `${p.nom} (${lieu}${pop})${p.cps ? `, ${arr && p.cps.split(' ').length > 3 ? 'codes postaux ' + p.cps.split(' ')[0] + ' à ' + p.cps.split(' ').slice(-1)[0] : p.cps}` : ''}${p.precision ? ` : ${p.precision}` : ''}`
}

/** Formulaire de recherche (réutilisé par la page « Chez moi »). */
export function formulaire(id: string, valeur = ''): string {
  return `<form id="${id}" class="carte carte-contour ma-commune-champ" role="search" autocomplete="off">
  <label for="${id}-saisie">Code postal ou nom de la commune</label>
  <p class="aide" id="${id}-aide">Par exemple 44119, Grandchamp-des-Fontaines ou Saint-Herblain 44. Flèche bas pour parcourir les propositions. Recherche faite sur ton appareil, rien n’est envoyé.</p>
  <div class="ma-commune-ligne"><input type="search" id="${id}-saisie" name="q" inputmode="text" autocomplete="off" spellcheck="false" aria-describedby="${id}-aide ${id}-etat" aria-controls="${id}-liste" data-propositions="${id}-liste" value="${h(valeur)}">
  <button type="submit" class="bouton-principal">Voir ma commune</button></div>
  <p id="${id}-etat" class="message-champ" role="status" aria-live="polite"></p>
  <ul id="${id}-liste" class="ma-commune-propositions" aria-label="Communes proposées" data-propositions-de="${id}-saisie"></ul>
</form>`
}

/** Adresse de la synthèse d'une commune : seul le code Insee passe dans l'adresse. */
export const adresseSynthese = (insee: string) => lien('/local/ma-commune', { insee })

/** Branche la recherche au fil de la saisie (fichiers lus à la demande, mis en cache par donnees.ts). */
export function brancherFormulaire(racine: ParentNode, id: string): void {
  const form = racine.querySelector<HTMLFormElement>(`#${id}`)
  if (!form) return
  const champ = form.querySelector<HTMLInputElement>(`#${id}-saisie`)!
  const etat = form.querySelector<HTMLElement>(`#${id}-etat`)!
  const liste = form.querySelector<HTMLElement>(`#${id}-liste`)!
  let idx: IndexMaCommune | null = null
  let dernier: Resultat = { propositions: [], total: 0, message: null }
  let tour = 0
  let minuterie: ReturnType<typeof setTimeout> | undefined
  const afficher = (r: Resultat) => {
    dernier = r
    liste.innerHTML = r.propositions.map((p) => `<li><a href="${h(adresseSynthese(p.insee))}" data-insee="${h(p.insee)}">${h(libelleProposition(p, idx))}</a></li>`).join('')
    const n = r.total
    etat.textContent = r.message ?? (n === 0 ? '' : n > r.propositions.length ? `${n} réponses, les ${r.propositions.length} premières dans l’ordre alphabétique : précise ta saisie (nom complet ou numéro du département).` : `${n} réponse${n > 1 ? 's' : ''}.`)
  }
  const lancer = async () => {
    const t = ++tour
    idx = idx ?? (await chargerIndex())
    const r = await chercher(champ.value, idx)
    if (t === tour) afficher(r)
    return r
  }
  champ.addEventListener('input', () => {
    clearTimeout(minuterie)
    minuterie = setTimeout(() => void lancer().catch((e) => console.error(e)), 120)
  })
  form.addEventListener('submit', async (e) => {
    e.preventDefault()
    clearTimeout(minuterie)
    const r = await lancer().catch(() => dernier)
    const insees = [...new Set(r.propositions.map((p) => p.insee))]
    if (insees.length === 1 && r.total === r.propositions.length) location.hash = adresseSynthese(insees[0])
    else if (r.propositions.length) liste.querySelector<HTMLAnchorElement>('a')?.focus()
    else if (!r.message) etat.textContent = 'Tape un code postal ou le nom d’une commune.'
  })
  if (champ.value) void lancer()
}

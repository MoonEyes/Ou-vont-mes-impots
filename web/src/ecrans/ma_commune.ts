// « Ma commune » (/local/ma-commune) : un champ unique, code postal ou nom, autocomplété dans le navigateur à partir
// de site/data/ma_commune (base officielle des codes postaux de La Poste, contrat 2.71), puis une page de synthèse
// qui assemble ce que le site publie déjà : budgets de la commune, de l'intercommunalité, du département et de la
// région (chacun à part, jamais additionnés), bénéficiaires nommés (personnes morales seulement), projets aidés par
// l'État, délibérations, fonds européens, repères parmi les communes qui se ressemblent.
// Aucune requête hors du site ; aucune donnée saisie n'est envoyée ni conservée ; le salaire n'est jamais lu ici.
import { fragmentCommune, fragmentDepartement } from '../chemins'
import { departementDe } from '../departements'
import { chargerSiPresent } from '../donnees'
import { session } from '../etat'
import { lien, type Rendu } from '../routeur'
import { absent, appliquerLargeurs, badgeCalcule, badgeStatut, barres, entier, eur, eurLisible, h, repli, source, sur100 } from '../util'
import { blocBudget, deCommune, type Budgets, type Geo } from './commune'
import { encadreManque, MANQUES } from '../composants/manque'
import { adresseSynthese, brancherFormulaire, chargerIndex, formulaire } from './ma_commune_recherche'

export * from './ma_commune_recherche'

export const TITRE = 'Ma commune en un écran'
export const CHAPEAU = 'Tape ton code postal ou le nom de ta commune : ce que ta commune, ton intercommunalité, ton département et ta région font de l’argent public, sur une seule page.'
export const NE_PAS_ADDITIONNER = 'Chaque collectivité a son propre budget : ne pas additionner commune, intercommunalité, département et région (une partie de l’argent passe de l’une à l’autre).'

// ------------------------------------------------------------------------------------------------ synthèse

interface Fonctions {
  millesime: string
  source: string
  colonnes: string[]
  methode: string
  non_publie: string
  communes?: Record<string, ColFonctions>
  epci?: Record<string, ColFonctions>
  regions?: Record<string, ColFonctions>
}
interface ColFonctions {
  nom: string
  statut?: string
  annees?: Record<string, { nomenclature: string; population: number | null; total: number[]; non_ventile: number[]; f: Record<string, number[]> } | null>
}
interface IndexFonctions {
  nomenclatures: Record<string, Record<string, string>>
}

export const METHODE_SUR100_FONCTION = 'part de la fonction dans les dépenses de fonctionnement et d’investissement (hors remboursements d’emprunts) du budget principal, une même année, publiée par le pipeline pour chaque section puis additionnée'

/** Dépenses par grande fonction sur 100 € (niveau 1 de la nomenclature), dernier exercice publié ; null sinon. */
export function blocFonctions(f: Fonctions, c: ColFonctions | undefined, noms: IndexFonctions | null, titre: string): string | null {
  if (!c?.annees || !noms) return null
  const an = Object.keys(c.annees)
    .sort()
    .reverse()
    .find((a) => c.annees![a])
  const d = an ? c.annees[an] : null
  if (!an || !d) return null
  const libelles = noms.nomenclatures[d.nomenclature] ?? {}
  const i100 = [f.colonnes.indexOf('fonctionnement_sur_100'), f.colonnes.indexOf('investissement_sur_100')]
  const ieur = [f.colonnes.indexOf('fonctionnement_eur'), f.colonnes.indexOf('investissement_eur')]
  const part = (v: number[]) => (v[i100[0]] ?? 0) + (v[i100[1]] ?? 0)
  const euros = (v: number[]) => (v[ieur[0]] ?? 0) + (v[ieur[1]] ?? 0)
  const total = euros(d.total)
  if (!(total > 0)) return null
  const lignes = Object.keys(d.f)
    .filter((k) => k.length === 1)
    .sort()
    .map((k) => ({ nom: libelles[k] ?? `Fonction ${k}`, valeur: part(d.f[k]), detail: euros(d.f[k]) }))
  if (euros(d.non_ventile) > 0) lignes.push({ nom: 'Non ventilé par fonction', valeur: part(d.non_ventile), detail: euros(d.non_ventile) })
  const visibles = lignes.filter((x) => x.valeur > 0)
  return `<h3>${h(titre)}</h3>
<p>${h(eurLisible(total))} dépensés en ${h(an)} (budget principal, fonctionnement et investissement hors remboursements d’emprunts)${d.population ? `, soit ${h(eur(total / d.population))} par habitant` : ''}. Sur 100 € dépensés :</p>
${barres(
  visibles.map((x) => ({ nom: x.nom, valeur: x.valeur, texte: sur100(x.valeur), detail: eurLisible(x.detail) })),
  undefined,
  `Dépenses de ${c.nom} par fonction, en euros sur 100 €`,
  -1,
)}
<p class="aide">Ordre des fonctions : celui de la nomenclature ${h(d.nomenclature)}. Sur 100 € et total : ${badgeCalcule(METHODE_SUR100_FONCTION)}</p>
${source(f.source, `exercice ${an}`)}`
}

/** Budget d'une collectivité : par fonction si publié, sinon par nature (OFGL), sinon le motif. Titre porté par la section. */
function blocCollectivite(opts: { titre: string; f: Fonctions | null; fc: ColFonctions | undefined; noms: IndexFonctions | null; b: Budgets | null; bc: Budgets['collectivites'][string] | undefined; motif: string; sansFonction?: string }): string {
  const parFonction = opts.f ? blocFonctions(opts.f, opts.fc, opts.noms, 'Par grande fonction') : null
  if (parFonction) return parFonction
  const parNature = opts.b && opts.bc ? blocBudget(opts.b, opts.bc, opts.titre, false).replace(/^\s*<h2>[\s\S]*?<\/h2>/, '') : null
  if (parNature && !parNature.includes('class="absent"')) {
    const pourquoi = opts.sansFonction ?? (opts.fc?.statut === 'non_publie' && opts.f ? opts.f.non_publie : 'présentation par fonction absente des balances comptables lues par le site pour cette collectivité.')
    return `<h3>Par nature de dépense</h3>${parNature}<details class="aide"><summary>Pourquoi par nature et non par fonction</summary><p>Par nature (personnel, achats, aides versées, équipements) et non par fonction : ${h(pourquoi)}</p></details>`
  }
  return absent(opts.motif)
}

/** Présentation fonctionnelle des départements (OFGL), local/budgets/fonctions/departements.json. */
export interface FonctionsDepartements {
  millesime: string
  source: string
  annees: string[]
  colonnes: string[]
  note: string
  departements: Record<string, { nom: string; population: Record<string, number>; nomenclature?: Record<string, string>; fonctions: Record<string, { libelle: string | null; libelles?: Record<string, string>; eur: Record<string, (number | null)[]> }> }>
}

export const METHODE_SUR100_DEPARTEMENT =
  'part de la fonction dans les dépenses de fonctionnement et d’investissement (hors remboursements d’emprunts) publiées par l’OFGL pour chaque fonction, une même année, budget principal et budgets annexes additionnés ; une section sans ligne publiée pour une fonction n’ajoute rien'

/** Libellé de l'OFGL tel quel, sauf écrit tout en capitales (« SERVICES GÉNÉRAUX ») : remis en minuscules. */
const libelleOfgl = (x: string) => (x === x.toUpperCase() ? x.charAt(0) + x.slice(1).toLowerCase() : x)

/** Dépenses d'un département par fonction (niveau 1) sur 100 €, dernier exercice publié ; null si absent. */
export function blocFonctionsDepartement(fd: FonctionsDepartements | null, code: string): string | null {
  const d = fd?.departements[code]
  if (!fd || !d) return null
  const an = [...fd.annees].sort().reverse().find((a) => Object.values(d.fonctions).some((f) => f.eur[a]))
  if (!an) return null
  const somme = (v: (number | null)[] | undefined) => (v ?? []).reduce<number>((t, x) => t + (typeof x === 'number' ? x : 0), 0)
  const lignes = Object.keys(d.fonctions)
    .sort()
    .filter((k) => d.fonctions[k].eur[an])
    .map((k) => ({ nom: libelleOfgl(d.fonctions[k].libelles?.[an] ?? d.fonctions[k].libelle ?? `Fonction ${k}`), eur: somme(d.fonctions[k].eur[an]) }))
  const total = lignes.reduce((t, x) => t + x.eur, 0)
  if (!(total > 0)) return null
  const pop = d.population[an]
  const visibles = lignes.filter((x) => x.eur > 0)
  const horsApa = lignes.find((x) => /hors APA/i.test(x.nom))
  return `<h3>Par grande fonction</h3>
<p>${h(eurLisible(total))} dépensés en ${h(an)} (fonctionnement et investissement hors remboursements d’emprunts, budget principal et budgets annexes)${pop ? `, soit ${h(eur(total / pop))} par habitant` : ''}. Sur 100 € dépensés :</p>
${barres(
  visibles.map((x) => ({ nom: x.nom, valeur: (x.eur / total) * 100, texte: sur100((x.eur / total) * 100), detail: eurLisible(x.eur) })),
  undefined,
  `Dépenses de ${d.nom} par fonction, en euros sur 100 €`,
  -1,
)}
<p class="aide">Ordre des fonctions et libellés : ceux de la nomenclature ${h(d.nomenclature?.[an] ?? 'budgétaire')} de l’exercice ${h(an)}, tels que publiés par l’OFGL (un même numéro de fonction ne désigne pas la même chose d’une nomenclature à l’autre). Les flux entre le budget principal et les budgets annexes ne sont pas retirés par la source.${horsApa ? ` « ${h(horsApa.nom)} » : libellé publié tel quel ; le montant publié pour cette fonction comprend l’allocation personnalisée d’autonomie (APA) et le revenu de solidarité active (RSA), qui sont deux de ses sous-fonctions dans la présentation de l’OFGL.` : ''} Sur 100 € et total : ${badgeCalcule(METHODE_SUR100_DEPARTEMENT)}</p>
${source(fd.source, `exercice ${an}`)}`
}

type Decisions = { source: string; limites?: string; regle?: string; collectivites: Record<string, { type: string; code: string; nom: string; lignes: number; annees: string[] }> }
type DecisionsAnnee = { source: string; millesime: string; annee: string; colonnes: string[]; lignes: (string | number | null)[][] }

/** Même règle que pipeline/sirene.py (personne_morale) : catégories 2xxx à 9xxx hors groupements de personnes physiques. */
export const personneMorale = (cj: unknown): boolean => {
  const s = String(cj ?? '')
  return /^[2-9]\d{3}$/.test(s) && !['2110', '2210', '2310', '2385'].includes(s)
}

/** Principaux bénéficiaires des subventions publiées par une collectivité, dernière année, personnes morales seulement. */
export function blocSubventions(nom: string, d: DecisionsAnnee | null, max = 5): string {
  if (!d) return ''
  const c = (k: string) => d.colonnes.indexOf(k)
  const parBenef = new Map<string, { nom: string; montant: number; lignes: number }>()
  let autres = 0
  for (const l of d.lignes) {
    const siren = l[c('siren')] as string | null
    const den = l[c('denomination')] as string | null
    const m = l[c('montant_eur')] as number | null
    if (typeof m !== 'number') continue
    if (!siren || !den || !personneMorale(l[c('categorie_juridique')])) {
      autres += m
      continue
    }
    const e = parBenef.get(siren) ?? { nom: den, montant: 0, lignes: 0 }
    e.montant += m
    e.lignes += 1
    parBenef.set(siren, e)
  }
  const tri = [...parBenef.values()].sort((a, b) => b.montant - a.montant || a.nom.localeCompare(b.nom, 'fr'))
  if (!tri.length) return `<p>${h(nom)} : aucune subvention à une personne morale dans la liste publiée pour ${h(d.annee)}.</p>`
  return `<div class="tableau-defile"><table><caption>Subventions votées par ${h(nom)} en ${h(d.annee)} : les ${Math.min(max, tri.length)} montants les plus élevés (sur ${entier(tri.length)} bénéficiaires nommés)</caption><thead><tr><th scope="col">Bénéficiaire</th><th scope="col" class="nombre">Montant ${h(d.annee)}</th><th scope="col" class="nombre">Lignes</th></tr></thead><tbody>${tri
    .slice(0, max)
    .map((b) => `<tr><th scope="row">${h(b.nom)}</th><td class="nombre">${h(eur(b.montant))}</td><td class="nombre">${h(entier(b.lignes))}</td></tr>`)
    .join('')}</tbody></table></div>
<p class="aide">Ordre : montant décroissant, puis nom. Montant par bénéficiaire ${badgeCalcule('somme des lignes publiées pour un même bénéficiaire (même SIREN), une même année, par la même collectivité')}${autres > 0 ? ` Lignes sans personne morale identifiée (non nommées) : ${h(eurLisible(autres))}.` : ''}</p>
${source(d.source, d.millesime)}`
}

type OperationsIndex = { listes: { id: string; fichier: string; autorite_de_gestion: string; region: string; collecte_le?: string }[]; sources_inaccessibles?: { url: string; constat: string }[] }
type Operations = { source: string; millesime: string; autorite_de_gestion: string; colonnes: string[]; operations: (string | number | null)[][] }

/** Opérations des fonds européens situées dans la commune (listes des autorités de gestion), contribution de l'Union. */
export function blocFondsEuropeens(insee: string, nom: string, region: { code: string; nom: string }, idx: OperationsIndex | null, listes: (Operations | null)[], max = 5): string {
  const lien_ = `<a href="#/explorer/fonds-europeens">Les fonds européens en France, par région</a>`
  if (!idx) return `${absent('Listes d’opérations des fonds européens non disponibles.')}<p>${lien_}</p>`
  const lues = listes.filter((l): l is Operations => !!l)
  if (!lues.length)
    return `${encadreManque(MANQUES.fondsEuropeensCommunes({ region: region.nom, listes: idx.listes, inaccessible: idx.sources_inaccessibles?.[0] }))}<p>Les montants par région restent consultables : ${lien_}.</p>`
  const lignes: { den: string; intitule: string; periode: string; fonds: string; ue: number | null; annee: number | null; autorite: string }[] = []
  for (const o of lues) {
    const c = (k: string) => o.colonnes.indexOf(k)
    for (const l of o.operations) {
      if (l[c('commune_insee')] !== insee) continue
      const den = l[c('denomination')] as string | null
      if (!den || !personneMorale(l[c('categorie_juridique')])) continue
      lignes.push({ den, intitule: String(l[c('intitule')] ?? ''), periode: String(l[c('periode')] ?? ''), fonds: String(l[c('fonds')] ?? ''), ue: (l[c('montant_ue_eur')] as number | null) ?? null, annee: (l[c('annee_debut')] as number | null) ?? null, autorite: o.autorite_de_gestion })
    }
  }
  const sources = lues.map((o) => source(o.source, o.millesime)).join('')
  if (!lignes.length) return `<p>Aucune opération nommée située à ${h(nom)} dans les listes publiées par ${h([...new Set(lues.map((o) => o.autorite_de_gestion))].join(', '))}.</p>${sources}`
  lignes.sort((a, b) => (b.ue ?? -1) - (a.ue ?? -1) || a.den.localeCompare(b.den, 'fr'))
  return `<div class="tableau-defile"><table><caption>Opérations cofinancées par l’Union situées à ${h(nom)} : les ${Math.min(max, lignes.length)} contributions les plus élevées (sur ${entier(lignes.length)})</caption><thead><tr><th scope="col">Bénéficiaire</th><th scope="col">Opération</th><th scope="col">Fonds, période</th><th scope="col" class="nombre">Contribution de l’Union</th></tr></thead><tbody>${lignes
    .slice(0, max)
    .map((x) => `<tr><th scope="row">${h(x.den)}</th><td>${h(x.intitule)}${x.annee ? ` (début ${x.annee})` : ''}</td><td>${h(x.fonds)}, ${h(x.periode)}</td><td class="nombre">${x.ue === null ? 'non publié' : h(eur(x.ue))}</td></tr>`)
    .join('')}</tbody></table></div>
<p class="aide">Ordre : contribution décroissante, puis nom. Bénéficiaires nommés : personnes morales seulement.</p>${sources}`
}

type TypIndex = { variables: Record<string, { libelle: string; annee: number; unite: string }>; facettes: Record<string, { libelle: string; cases: { code: string; libelle: string }[] }>; avertissement: string; source: string; millesime: string }
type TypCommunes = { colonnes: string[]; communes: Record<string, { nom: string; densite: string | null; strate: string | null; v: (number | null)[] }>; source: string; millesime: string }
type TypCase = { code?: string; n: number; x: { q: number[] }; y: { q: number[] } }
type TypCroisement = { x: { variable: string }; y: { variable: string }; annee: number; facettes: Record<string, { cases: TypCase[] }>; source: string; millesime: string; methode?: string }

/** Repères parmi les communes de même densité et de même strate : valeur de la commune, quartiles de sa case. */
export function blocTypologie(insee: string, idx: TypIndex | null, com: TypCommunes | null, croisements: (TypCroisement | null)[]): string {
  const ligne = com?.communes[insee]
  if (!idx || !com || !ligne) return absent('Typologie de la commune non disponible (commune absente des grilles de l’Insee ou des comptes de l’OFGL lus par le site).')
  const lignes: string[] = []
  for (const cr of croisements) {
    if (!cr) continue
    for (const axe of ['y', 'x'] as const) {
      const variable = cr[axe].variable
      const def = idx.variables[variable]
      const iv = com.colonnes.indexOf(variable)
      if (!def || iv < 0 || lignes.some((l) => l.includes(`data-v="${variable}"`))) continue
      const val = ligne.v[iv]
      const cases = (['densite', 'strate'] as const).map((f) => {
        const code = f === 'densite' ? ligne.densite : ligne.strate
        const cs = cr.facettes[f]?.cases.find((c) => c.code === code)
        const lib = idx.facettes[f]?.cases.find((c) => c.code === code)?.libelle
        return cs && lib ? `<li>${h(lib)} (${h(entier(cs.n))} communes) : la moitié entre ${h(eur(cs[axe].q[1]))} et ${h(eur(cs[axe].q[3]))}, médiane ${h(eur(cs[axe].q[2]))}</li>` : ''
      })
      lignes.push(`<li data-v="${h(variable)}"><strong>${h(def.libelle)} en ${h(def.annee)}</strong> : ${val === null || val === undefined ? 'non publié pour cette commune' : h(eur(val))}<ul>${cases.join('')}</ul></li>`)
    }
  }
  if (!lignes.length) return absent('Repères non disponibles.')
  return `<p>Les communes qui ressemblent à ${h(ligne.nom)} par leur densité (grille de l’Insee) et par leur nombre d’habitants (strate de l’OFGL), une même année.</p>
<ul class="ma-commune-reperes">${lignes.join('')}</ul>
<p class="aide">${h(idx.avertissement)} Quartiles des communes de chaque groupe : ${badgeCalcule('quartiles des montants par habitant publiés par l’OFGL, communes d’un même groupe, une même année')}</p>
${source(idx.source, idx.millesime)}
<p><a href="${h(lien('/local/croiser', { insee }))}">Comparer ${h(ligne.nom)} avec des communes qui se ressemblent, chiffre par chiffre</a></p>`
}

/** Les quatre collectivités, en onglets (audit du 19/11, lot 3, problèmes 2 et 13) : une seule ouverte à la fois. */
const ONGLETS: [string, string, string][] = [
  ['mc-commune', 'La commune', 'Commune'],
  ['mc-epci', 'L’intercommunalité', 'Intercommunalité'],
  ['mc-departement', 'Le département', 'Département'],
  ['mc-region', 'La région', 'Région'],
]
/** Le reste de la page, replié : titre et contenu annoncés, ouvert à la demande. */
const SECTIONS: [string, string, string][] = [
  ['mc-beneficiaires', 'Subventions publiées', 'Bénéficiaires nommés'],
  ['mc-europe', 'Fonds européens', 'Opérations dans la commune'],
  ['mc-projets', 'Projets aidés', 'Dotations de l’État et Fonds vert'],
  ['mc-deliberations', 'Délibérations', 'Ce qui est publié'],
  ['mc-comparer', 'Communes semblables', 'Même densité, même taille'],
]

/**
 * Onglets accessibles (motif « tabs » de l'APG ARIA) : flèches gauche et droite, Début et Fin ; la sélection suit le
 * focus. Aucune donnée n'est retirée : chaque panneau est dans la page, les autres sont seulement masqués.
 */
export function brancherOnglets(racine: HTMLElement): void {
  const onglets = [...racine.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
  const choisir = (o: HTMLButtonElement, focus: boolean) => {
    for (const x of onglets) {
      const actif = x === o
      x.setAttribute('aria-selected', String(actif))
      x.tabIndex = actif ? 0 : -1
      const panneau = racine.querySelector<HTMLElement>(`#${x.getAttribute('aria-controls')}`)
      if (panneau) panneau.hidden = !actif
    }
    if (focus) o.focus()
  }
  onglets.forEach((o, i) => {
    o.addEventListener('click', () => choisir(o, false))
    o.addEventListener('keydown', (e) => {
      const k = e.key
      const j = k === 'ArrowRight' ? (i + 1) % onglets.length : k === 'ArrowLeft' ? (i - 1 + onglets.length) % onglets.length : k === 'Home' ? 0 : k === 'End' ? onglets.length - 1 : -1
      if (j < 0) return
      e.preventDefault()
      choisir(onglets[j], true)
    })
  })
}

async function synthese(cible: HTMLElement, insee: string): Promise<Rendu | void> {
  const dep = departementDe(insee)
  const geo = await chargerSiPresent<Geo>(`local/geo/${dep}.json`)
  const g = geo?.communes[insee]
  if (!geo || !g) {
    cible.innerHTML = `<h1>${h(TITRE)}</h1>${absent('Commune introuvable dans les données publiées.')}${formulaire('mc-recherche')}<p><a href="#/local">Budget de ma commune : choisir par département</a></p>`
    brancherFormulaire(cible, 'mc-recherche')
    return
  }
  const epci = g.epci ? geo.epci[g.epci] : null
  const idxMc = await chargerIndex()
  const arr = idxMc?.arrondissements[insee]
  const titres: Record<string, string> = {
    'mc-commune': `La commune : ${g.nom}`,
    'mc-epci': epci ? `L’intercommunalité : ${epci.nom}` : 'L’intercommunalité',
    'mc-departement': `Le département : ${geo.departement.nom}`,
    'mc-region': `La région : ${geo.region.nom}`,
  }
  const zone = (id: string) => `<div id="${id}" class="section-donnees" aria-busy="true"><p class="chargement">Chargement…</p></div>`
  cible.innerHTML = `<div class="entete-local entete-serre">
  <div>
    <h1>${h(g.nom)}</h1>
    <p class="chapeau">${h(entier(g.population))} habitants${epci ? `, ${h(epci.nom)}` : ''}, ${h(geo.departement.nom)} (${h(dep)}), région ${h(geo.region.nom)}.</p>
    <p class="aide">${h(NE_PAS_ADDITIONNER)}</p>
    ${arr ? `<p class="aide">${h(arr.note)}</p>` : ''}
  </div>
</div>
<div class="onglets-collants"><div role="tablist" aria-label="Budget de chaque collectivité, une à la fois" class="onglets">${ONGLETS.map(
    ([id, , court], i) => `<button type="button" role="tab" id="${id}-onglet" aria-controls="${id}-panneau" aria-selected="${i === 0}" tabindex="${i === 0 ? 0 : -1}">${h(court)}</button>`,
  ).join('')}</div></div>
${ONGLETS.map(([id, t], i) => `<section role="tabpanel" id="${id}-panneau" aria-labelledby="${id}-onglet" class="ma-commune-bloc"${i === 0 ? '' : ' hidden'}><h2 id="${id}-titre" tabindex="-1">${h(titres[id] ?? t)}</h2>${zone(id)}</section>`).join('\n')}
${SECTIONS.map(([id, t, resume]) => repli({ id: `${id}-repli`, idTitre: `${id}-titre`, titre: titres[id] ?? t, resume: h(resume), contenu: zone(id) })).join('\n')}
${repli({
  id: 'mc-plus-repli',
  idTitre: 'mc-plus-titre',
  titre: 'Pour aller plus loin',
  resume: 'Budget détaillé, comparer',
  contenu: `<ul class="liens-sortie">
  <li><a href="${fragmentCommune(insee, g.nom, g.population)}">Le budget ${h(deCommune(g.nom))} en détail : dotations, taux votés, organismes rattachés</a></li>
  <li><a href="${h(lien('/local/comparer', { a: insee }))}">Comparer ${h(g.nom)} avec une autre commune</a></li>
  <li><a href="${h(lien('/local/projets', { insee }))}">Tous les projets subventionnés par l’État pour ${h(g.nom)}</a></li>
  <li><a href="${fragmentDepartement(dep, geo.departement.nom)}">Les communes du département ${h(geo.departement.nom)}</a></li>
  <li><a href="${h(lien('/local/ma-commune'))}">Chercher une autre commune</a></li>
</ul>
${idxMc ? source(idxMc.source, idxMc.millesime) : ''}`,
})}`
  brancherOnglets(cible)
  const remplir = (id: string, html: string) => {
    const z = cible.querySelector<HTMLElement>(`#${id}`)
    if (!z) return
    z.innerHTML = html
    z.removeAttribute('aria-busy')
    appliquerLargeurs(z)
  }
  const proteger = (id: string, p: Promise<string>) =>
    p.then((html) => remplir(id, html)).catch((e) => {
      console.error(e)
      remplir(id, absent())
    })

  const nomsFonctions = chargerSiPresent<IndexFonctions>('local/fonctions/index.json')
  const fonctionsDep = chargerSiPresent<Fonctions>(`local/fonctions/${dep}.json`)

  const budgets = (async () => {
    const [noms, fc, fe, fr, bc, be, bd, br, fdep] = await Promise.all([
      nomsFonctions,
      fonctionsDep,
      epci && epci.departement_siege !== dep ? chargerSiPresent<Fonctions>(`local/fonctions/${epci.departement_siege}.json`) : fonctionsDep,
      chargerSiPresent<Fonctions>('local/fonctions/regions.json'),
      chargerSiPresent<Budgets>(`local/budgets/communes/${dep}.json`),
      epci ? chargerSiPresent<Budgets>(`local/budgets/epci/${epci.departement_siege}.json`) : Promise.resolve(null),
      chargerSiPresent<Budgets>('local/budgets/departements.json'),
      chargerSiPresent<Budgets>('local/budgets/regions.json'),
      chargerSiPresent<FonctionsDepartements>('local/budgets/fonctions/departements.json'),
    ])
    remplir('mc-commune', blocCollectivite({ titre: `Le budget ${deCommune(g.nom)}`, f: fc, fc: fc?.communes?.[insee], noms, b: bc, bc: bc?.collectivites[insee], motif: 'Budget de la commune non disponible.' }))
    remplir(
      'mc-epci',
      epci && g.epci
        ? blocCollectivite({ titre: epci.nom, f: fe, fc: fe?.epci?.[g.epci], noms, b: be, bc: be?.collectivites[g.epci], motif: 'Budget de l’intercommunalité non disponible.' })
        : `<p>${h(g.nom)} n’appartient à aucune intercommunalité à fiscalité propre dans le code officiel géographique (cas des communes isolées et des îles mono-communales).</p>`,
    )
    const parNatureDep = blocCollectivite({ titre: geo.departement.nom, f: null, fc: undefined, noms, b: bd, bc: bd?.collectivites[g.departement], motif: `Budget du département ${geo.departement.nom} non disponible (collectivité à statut particulier : ses comptes sont publiés avec ceux de la région ou de la ville).`, sansFonction: 'la présentation par fonction de l’OFGL ne couvre pas ce département.' })
    const parFonctionDep = blocFonctionsDepartement(fdep, g.departement)
    remplir(
      'mc-departement',
      parFonctionDep
        ? `${parFonctionDep}${bd?.collectivites[g.departement] ? `<details class="aide"><summary>Le même département par nature de dépense (personnel, aides versées, équipements)</summary>${blocBudget(bd, bd.collectivites[g.departement], geo.departement.nom, false).replace(/^\s*<h2>[\s\S]*?<\/h2>/, '')}</details>` : ''}${encadreManque(MANQUES.departementFonctions(geo.departement.nom, fdep?.millesime, fdep ? Object.keys(fdep.departements).length : undefined))}`
        : parNatureDep,
    )
    remplir('mc-region', blocCollectivite({ titre: `Région ${geo.region.nom}`, f: fr, fc: fr?.regions?.[g.region], noms, b: br, bc: br?.collectivites[g.region], motif: `Budget de la région ${geo.region.nom} non disponible.` }))
  })()

  // Bénéficiaires nommés : subventions publiées par la commune et l'intercommunalité (format national SCDL).
  const beneficiaires = proteger(
    'mc-beneficiaires',
    (async () => {
      const di = await chargerSiPresent<Decisions>('local/decisions/index.json')
      if (!di) return absent('Listes de subventions non disponibles.')
      const qui: { siren: string | null; nom: string }[] = [
        { siren: g.siren ?? null, nom: g.nom },
        { siren: g.epci, nom: epci?.nom ?? 'L’intercommunalité' },
      ]
      const morceaux = await Promise.all(
        qui.map(async ({ siren, nom }) => {
          const c = siren ? di.collectivites[siren] : undefined
          const an = c?.annees.filter((a) => /^\d{4}$/.test(a)).sort().pop()
          if (!siren || !c || !an) return `<p>${h(nom)} : aucune liste de subventions publiée en données ouvertes au format national (obligatoire au-delà de 23 000 € par bénéficiaire).</p>`
          return `<h3>${h(nom)}</h3>${blocSubventions(nom, await chargerSiPresent<DecisionsAnnee>(`local/decisions/${siren}/${an}.json`))}`
        }),
      )
      return `${morceaux.join('')}${di.regle ? `<p class="aide">${h(di.regle)}</p>` : ''}<p>Les subventions du département et de la région ne sont pas rattachées à une commune dans les listes publiées : <a href="${h(lien('/beneficiaires/organisation'))}">chercher une organisation dans toutes les sources</a>.</p>`
    })(),
  )

  const europe = proteger(
    'mc-europe',
    (async () => {
      const idx = await chargerSiPresent<OperationsIndex>('fonds_europeens/operations.json')
      const listes = idx ? await Promise.all(idx.listes.filter((l) => l.region === g.region).map((l) => chargerSiPresent<Operations>(l.fichier))) : []
      return blocFondsEuropeens(insee, g.nom, geo.region, idx, listes)
    })(),
  )

  const projets = proteger(
    'mc-projets',
    import('./projets').then((m) => m.contenuCommune(insee, g.nom, 5)),
  )

  const deliberations = proteger(
    'mc-deliberations',
    (async () => {
      const [m, di] = await Promise.all([import('./commune_investissement'), chargerSiPresent<import('./commune_investissement').DelibIndex>('deliberations/index.json')])
      if (!di) return absent('Délibérations non disponibles.')
      const qui = [
        { siren: g.siren ?? null, nom: g.nom },
        { siren: g.epci, nom: epci?.nom ?? 'L’intercommunalité' },
      ].filter((x) => x.siren)
      const colls = await Promise.all(qui.map((x) => (di.collectivites[x.siren!] ? chargerSiPresent<import('./commune_investissement').DelibColl>(`deliberations/collectivites/${x.siren}.json`) : Promise.resolve(null))))
      return `${qui.map((x, i) => m.blocDeliberations(di, colls[i], x.nom)).join('')}${m.phraseCouverture(di)}${source(di.source, di.millesime)}`
    })(),
  )

  const comparer = proteger(
    'mc-comparer',
    (async () => {
      const [idx, com, a, b] = await Promise.all([
        chargerSiPresent<TypIndex>('typologies/index.json'),
        chargerSiPresent<TypCommunes>(`typologies/communes/${dep}.json`),
        chargerSiPresent<TypCroisement>('typologies/croisements/dgf_depenses_2024.json'),
        chargerSiPresent<TypCroisement>('typologies/croisements/equipement_dette_2024.json'),
      ])
      return blocTypologie(insee, idx, com, [a, b])
    })(),
  )

  const suite = Promise.all([budgets.catch((e) => {
    console.error(e)
    for (const id of ['mc-commune', 'mc-epci', 'mc-departement', 'mc-region']) if (cible.querySelector(`#${id}[aria-busy]`)) remplir(id, absent())
  }), beneficiaires, europe, projets, deliberations, comparer]).then(() => undefined)

  return {
    titre: `${g.nom} (${geo.departement.nom}) : budgets, bénéficiaires, projets`,
    adresse: adresseSynthese(insee),
    fil: [
      { nom: geo.departement.nom, fragment: fragmentDepartement(dep, geo.departement.nom) },
      { nom: g.nom, fragment: adresseSynthese(insee) },
    ],
    description: `${g.nom} en un écran : budgets de la commune, de l’intercommunalité, du département et de la région, bénéficiaires nommés, projets, délibérations, fonds européens, communes qui se ressemblent.`,
    suite,
  }
}

export async function rendre(cible: HTMLElement, params: URLSearchParams): Promise<Rendu | void> {
  const insee = params.get('insee') ?? ''
  if (/^(\d{5}|2[AB]\d{3})$/.test(insee)) return synthese(cible, insee)
  const saisie = (params.get('q') ?? '').slice(0, 60)
  const deCalcul = session.profil?.residence.commune_insee
  cible.innerHTML = `<h1>${h(TITRE)}</h1>
<p class="chapeau">${h(CHAPEAU)}</p>
${formulaire('mc-recherche', saisie)}
${deCalcul ? `<p class="actions"><a class="bouton" href="${h(adresseSynthese(deCalcul))}">Voir la commune saisie dans ton calcul</a></p>` : ''}
<p class="aide">Codes postaux : base officielle de La Poste ; un code postal peut desservir plusieurs communes, une commune peut avoir plusieurs codes postaux. ${badgeStatut('trace')}</p>
<h2>Pour aller plus loin</h2>
<ul class="liens-sortie">
  <li><a href="#/local">Budget de ma commune : choisir par département</a></li>
  <li><a href="#/local/croiser">Comparer des communes qui se ressemblent</a></li>
  <li><a href="#/explorer/collectivites">Les collectivités locales en France</a></li>
</ul>`
  brancherFormulaire(cible, 'mc-recherche')
}

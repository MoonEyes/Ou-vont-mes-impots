// Solidarités des départements (site/data/solidarites_departements/, contrat 2.43).
// Ce que les départements versent pour le revenu de solidarité active, l'allocation personnalisée d'autonomie et la
// prestation de compensation du handicap d'après leurs comptes (OFGL, 2012-2025), les recettes que ces comptes
// rattachent à ces allocations (part de taxe sur les carburants et fonds d'insertion versés par l'État, dotations de
// la caisse de l'autonomie), le nombre de bénéficiaires publié par la DREES et, pour l'aide sociale à l'enfance, que
// les comptes n'isolent pas, les dépenses brutes publiées par la DREES (lues dans territoires/, jamais additionnées).
// Allocations et recettes sont posées côte à côte, sans soustraction : le « reste à charge » calculé par le pipeline
// (reste_a_charge_calcule*) n'est PAS affiché, en attente d'une décision du propriétaire sur les chiffres calculés
// par le site ; aucun reste à charge officiel n'est publié par département. Écarts entre sources montrés tels quels.
// Les pages Prestations, Collectivités, Sécurité sociale et Budget du département montrent des montants voisins :
// elles sont reliées, pas recopiées. Agrégats seulement, aucune personne nommée.
import { listeRecherche } from '../composants/choix'
import { partPersonnelle } from '../composants/hub'
import { TOUS_DEPARTEMENTS } from '../departements'
import { chargerSiPresent } from '../donnees'
import type { Rendu } from '../routeur'
import { absent, appliquerLargeurs, badgeStatut, entier, eurLisible, h, pct, traitStatut, badgeCalcule, LEGENDE_CALCULE } from '../util'
import { enCours } from './dette'

type Nombre = number | null

interface SourceIdx {
  titre: string
  producteur?: string
  licence?: string
  millesime?: string
  page?: string
  url?: string
  collecte_le?: string
}
interface DepIdx {
  code: string
  nom: string
  comptes: string[]
  beneficiaires: string[]
  liens?: { depenses_drees_par_poste?: string }
}
interface CollIdx {
  code: string
  nom: string
  departements: string[]
  perimetre?: string
  perimetre_beneficiaires?: string
}
interface EcartNational {
  annee: number
  grandeur: string
  valeur: Nombre
  autre_valeur: Nombre
  ecart: Nombre
  ecart_pct: Nombre
  lecture_ecart?: string
}
export interface IndexSolidarites {
  millesime: string
  source: string
  date_sources?: string
  annees_comptes: number[]
  departements: DepIdx[]
  collectivites: CollIdx[]
  totaux: Record<string, { collectivites: number; eur: Record<string, Nombre>; collectivites_par_colonne?: Record<string, number> }>
  ecarts: EcartNational[]
  rsa_recentralise: Record<string, { premiere_annee_entiere?: number; debut?: string }>
  methode?: Record<string, string>
  limites?: string[]
  sources: Record<string, SourceIdx>
  sources_inaccessibles?: { source: string; motif: string; constat_le?: string }[]
  recherche_publique?: { date?: string; conclusion?: string }
}
interface CollComptes {
  nom: string
  departements: string[]
  population?: Record<string, number>
  eur: Record<string, Nombre[]>
  eur_hab?: Record<string, Nombre[]>
  financeur_rsa?: Record<string, string>
  perimetre?: string
}
interface Comptes {
  millesime: string
  source: string
  annees: string[]
  colonnes: string[]
  definitions: Record<string, string>
  collectivites: Record<string, CollComptes>
}
interface Serie {
  id: string
  libelle: string
  definition?: string
  champ?: string
  annees: number[]
  rupture?: string | null
}
interface Beneficiaires {
  millesime: string
  source: string
  series: Serie[]
  collectivites: Record<string, { nom: string; valeurs: Record<string, Nombre[]>; perimetre?: string; rsa_2016_ancien_systeme?: number }>
  totaux: Record<string, Record<string, Nombre[]>>
}
interface Ecarts {
  colonnes: string[]
  grandeurs: Record<string, { lecture_ecart?: string }>
  lignes: (string | number | null)[][]
}
interface TerritoiresIndex {
  totaux?: { aide_sociale_drees?: { france?: Record<string, Record<string, Nombre>> } }
  sources?: Record<string, { titre: string; page?: string; licence?: string }>
}
interface TerritoiresDep {
  aide_sociale?: { collectivites?: { code: string; nom: string; postes: Record<string, { brute?: { eur?: Record<string, Nombre> } }> }[] }
}

/** Colonnes des comptes : allocations versées (et frais d'hébergement), puis recettes rattachées. */
export const ALLOCATIONS: [string, string][] = [
  ['allocations_rsa', 'Revenu de solidarité active'],
  ['allocations_apa', 'Allocation personnalisée d’autonomie'],
  ['allocations_pch', 'Prestation de compensation du handicap (et ancienne allocation compensatrice)'],
  ['frais_hebergement', 'Frais d’hébergement (personnes âgées, handicapées, enfants placés)'],
]
export const RECETTES: [string, string][] = [
  ['ticpe', 'Part de la taxe sur les carburants versée par l’État'],
  ['fmdi', 'Fonds d’insertion versé par l’État'],
  ['cnsa', 'Dotations de la caisse de l’autonomie'],
]
/** Séries de bénéficiaires retenues (libellés du site ; libellé de la DREES dans les définitions). */
export const SERIES: [string, string][] = [
  ['rsa', 'Allocataires du revenu de solidarité active (au 31 décembre)'],
  ['apa', 'Bénéficiaires de l’allocation personnalisée d’autonomie'],
  ['pch', 'Bénéficiaires de la prestation de compensation du handicap'],
  ['actp', 'Bénéficiaires de l’allocation compensatrice pour tierce personne'],
  ['ase_accueillis', 'Enfants accueillis à l’aide sociale à l’enfance'],
  ['ase_actions_educatives', 'Enfants suivis par une action éducative'],
]
const GRANDEURS: Record<string, { nom: string; source: string; autre: string; nombre?: boolean }> = {
  allocations_rsa: { nom: 'Allocations du revenu de solidarité active', source: 'comptes du département (OFGL)', autre: 'dépenses brutes déclarées à la DREES' },
  allocations_apa: { nom: 'Allocation personnalisée d’autonomie', source: 'comptes du département (OFGL)', autre: 'dépenses brutes déclarées à la DREES' },
  allocations_pch: { nom: 'Prestation de compensation du handicap et allocation compensatrice', source: 'comptes du département (OFGL)', autre: 'dépenses brutes déclarées à la DREES' },
  beneficiaires_apa_domicile: { nom: 'Bénéficiaires de l’allocation d’autonomie à domicile, payés en décembre', source: 'séries longues de la DREES', autre: 'jeu « montants versés » de la DREES', nombre: true },
  beneficiaires_pch_payes: { nom: 'Bénéficiaires de la prestation de compensation payés en décembre', source: 'séries longues de la DREES', autre: 'jeu « montants versés » de la DREES', nombre: true },
  beneficiaires_rsa: { nom: 'Allocataires du revenu de solidarité active', source: 'DREES (CAF et MSA, au 31 décembre)', autre: 'CNAF (foyers payés par les CAF en décembre)', nombre: true },
}

const NOMS_DEP = new Map(TOUS_DEPARTEMENTS)
const NON_PUBLIE = 'non publié'
const montant = (v: Nombre | undefined) => (typeof v === 'number' ? eurLisible(v) : NON_PUBLIE)
const nombre = (v: Nombre | undefined) => (typeof v === 'number' ? entier(v) : NON_PUBLIE)
const cellule = (texte: string) => `<td class="nombre">${h(texte)}</td>`
const majuscule = (t: string) => t.charAt(0).toUpperCase() + t.slice(1)
/** Texte de la source sans nom de clé technique (« `rsa_2016_ancien_systeme` »). */
const propre = (t: string) => t.replace(/\s*\([^()]*`[^()]*\)/g, '').replace(/`/g, '')
const dateFr = (iso?: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? '')
  return m ? `${Number(m[3])}/${m[2]}/${m[1]}` : (iso ?? '')
}

/** Département de l'URL (« ?dep=44 ») s'il figure dans l'index. */
export const departementChoisi = (idx: IndexSolidarites, dep: string | null) => idx.departements.find((d) => d.code === dep) ?? null

/** Lignes d'écarts (ecarts.json) d'une collectivité, regroupées par grandeur, années croissantes. */
export function ecartsCollectivite(e: Ecarts, code: string): Map<string, Record<string, string | number | null>[]> {
  const out = new Map<string, Record<string, string | number | null>[]>()
  for (const l of e.lignes) {
    const r = Object.fromEntries(e.colonnes.map((c, i) => [c, l[i]]))
    if (r.code !== code) continue
    const g = String(r.grandeur)
    out.set(g, [...(out.get(g) ?? []), r])
  }
  for (const v of out.values()) v.sort((a, b) => Number(a.annee) - Number(b.annee))
  return out
}

function tableauAnnees(legende: string, annees: string[], colonnes: [string, string][], valeur: (an: string, col: string) => string): string {
  return `<div class="tableau-defile"><table><caption>${h(legende)}</caption><thead><tr><th scope="col">Année</th>${colonnes
    .map(([, l]) => `<th scope="col" class="nombre">${h(l)}</th>`)
    .join('')}</tr></thead><tbody>${annees
    .map((a) => `<tr><th scope="row">${h(a)}</th>${colonnes.map(([c]) => cellule(valeur(a, c))).join('')}</tr>`)
    .join('')}</tbody></table></div>`
}

const sourceComptes = (idx: IndexSolidarites) => {
  const s = idx.sources.ofgl_departements
  return s
    ? `<p class="source">Source : <a href="${h(s.page ?? s.url ?? '')}" rel="noopener noreferrer">${h(s.titre)}</a> (${h(s.millesime ?? '')}, ${h(s.licence ?? '')})${badgeStatut('trace')}</p>`
    : ''
}
const sourceDrees = (s: SourceIdx | undefined, extra = '') =>
  s ? `<p class="source">Source : <a href="${h(s.page ?? s.url ?? '')}" rel="noopener noreferrer">${h(s.titre)}</a> (${h(s.millesime ?? '')}, ${h(s.licence ?? '')})${extra} ${badgeStatut('trace')}</p>` : ''

// ---------------------------------------------------------------------------------------------------------------
// Vue nationale
// ---------------------------------------------------------------------------------------------------------------

function blocCles(idx: IndexSolidarites): string {
  const annees = Object.keys(idx.totaux).sort()
  const an = annees[annees.length - 1]
  const t = idx.totaux[an]
  if (!t) return ''
  const n = t.collectivites_par_colonne ?? {}
  const item = (col: string, texte: string) =>
    `<li><strong>${h(montant(t.eur[col]))}</strong> <span>${h(texte)} en ${h(an)}, d’après les comptes de ${h(entier(n[col] ?? t.collectivites))} collectivités</span> ${badgeStatut(
      typeof t.eur[col] === 'number' ? 'trace' : 'nonpub',
    )}</li>`
  return `<ul class="cles" aria-label="Allocations versées par les départements en ${h(an)}">
${item('allocations_rsa', 'versés pour le revenu de solidarité active (RSA)')}
${item('allocations_apa', 'versés pour l’allocation personnalisée d’autonomie (APA)')}
${item('allocations_pch', 'versés pour la prestation de compensation du handicap (PCH) et l’allocation compensatrice pour tierce personne (ACTP)')}
</ul>
<p class="aide">Trois allocations, trois montants lus dans les mêmes comptes : chacun se lit seul. Le nombre de collectivités comptées change selon la ligne, car l’État finance le revenu de solidarité active à la place de ${h(
    entier(Object.keys(idx.rsa_recentralise).length),
  )} départements (voir plus bas).</p>`
}

function blocNational(idx: IndexSolidarites, comptes: Comptes | null, terr: TerritoiresIndex | null): string {
  const annees = Object.keys(idx.totaux).sort()
  const val = (an: string, col: string) => montant(idx.totaux[an]?.eur[col])
  const ase = terr?.totaux?.aide_sociale_drees?.france?.['ase.brute'] ?? null
  const srcTerr = terr?.sources?.drees_aide_sociale
  const anneesAse = ase ? Object.keys(ase).filter((a) => Number(a) >= Number(annees[0] ?? 0)).sort() : []
  const defs = comptes?.definitions ?? {}
  const dernier = annees[annees.length - 1]
  const n = idx.totaux[dernier]?.collectivites_par_colonne ?? {}
  return `<h2>En France : ce que les départements versent</h2>
<p>Montants des comptes de chaque exercice, additionnés pour toutes les collectivités qui exercent les compétences d’un département (départements, Métropole de Lyon, collectivités uniques de Corse, de Martinique, de Guyane et d’Alsace). Euros courants, sans correction de l’inflation.</p>
${tableauAnnees('Allocations versées par les départements, somme des comptes publiés, en euros', annees, ALLOCATIONS, val)}
<p class="aide">Frais d’hébergement : ${h(defs.frais_hebergement ?? 'frais de séjour et d’hébergement payés par le département')}. Les comptes publiés ne séparent pas l’aide sociale à l’enfance des autres postes.</p>
${sourceComptes(idx)}
<h3>L’aide sociale à l’enfance</h3>
${
  ase && anneesAse.length
    ? `<p>Les comptes ne l’isolent pas : le montant ci-dessous vient d’une autre source, l’enquête Aide sociale de la DREES (dépenses brutes déclarées par les départements). Il ne s’ajoute pas aux montants des comptes ci-dessus, dont les frais d’hébergement comprennent déjà les placements d’enfants.</p>
${tableauAnnees('Aide sociale à l’enfance, dépenses brutes des départements (total France publié par la DREES), en euros', anneesAse, [['ase', 'Aide sociale à l’enfance']], (a) => montant(ase[a]))}
${srcTerr ? `<p class="source">Source : <a href="${h(srcTerr.page ?? '')}" rel="noopener noreferrer">${h(srcTerr.titre)}</a> (${h(srcTerr.licence ?? '')}) ${badgeStatut('trace')}</p>` : ''}`
    : absent('Dépenses d’aide sociale à l’enfance : donnée non disponible.')
}
<h2>Les recettes que leurs comptes rattachent à ces allocations</h2>
<p>Quand l’État a confié ces allocations aux départements, il leur a transféré des recettes : une part de la taxe intérieure de consommation sur les produits énergétiques (TICPE, la taxe sur les carburants) et le fonds de mobilisation départementale pour l’insertion (FMDI), pour le revenu de solidarité active. La Caisse nationale de solidarité pour l’autonomie (CNSA), branche autonomie de la Sécurité sociale, leur verse des dotations pour l’autonomie et le handicap.</p>
${tableauAnnees('Recettes rattachées aux allocations dans les comptes des départements, somme des comptes publiés, en euros', annees, RECETTES, val)}
<ul class="limites">
  <li>${traitStatut('trace')}<span><strong>Part de la taxe sur les carburants</strong> : ${h(defs.ticpe ?? '')}.</span></li>
  <li>${traitStatut('trace')}<span><strong>Fonds d’insertion</strong> : ${h(defs.fmdi ?? '')}.</span></li>
  <li>${traitStatut('trace')}<span><strong>Dotations de la caisse de l’autonomie</strong> : ${h(defs.cnsa ?? '')}.</span></li>
</ul>
<div class="carte carte-contour">
<h3>Pourquoi le site ne soustrait pas les recettes des allocations</h3>
<p>Allocations et recettes sont publiées côte à côte, sans soustraction. Aucun reste à charge officiel n’est publié par département : aucun jeu de données ouvert de l’administration ne donne, département par département, la part de ces allocations que les recettes de l’État ne couvrent pas. Les recettes ci-dessus ne recouvrent pas exactement les allocations : les dotations de la caisse de l’autonomie comprennent d’autres concours (maisons départementales des personnes handicapées, prévention, aide à domicile), la part de taxe sur les carburants compense aussi d’autres transferts de compétences, et la dotation de compensation versée par l’État (dispositif de compensation péréquée) et les fonds de péréquation n’apparaissent pas séparément dans les comptes publiés.</p>
</div>
<p class="aide">Nombre de collectivités dont les comptes publient chaque recette en ${h(dernier)} : ${RECETTES.map(([c, l]) => `${h(l)}, ${h(typeof n[c] === 'number' ? entier(n[c]) : NON_PUBLIE)}`).join(' ; ')}.</p>
${sourceComptes(idx)}`
}

function blocEcartsNationaux(idx: IndexSolidarites): string {
  if (!idx.ecarts.length) return ''
  const parGrandeur = new Map<string, EcartNational[]>()
  for (const e of idx.ecarts) parGrandeur.set(e.grandeur, [...(parGrandeur.get(e.grandeur) ?? []), e])
  return `<h2>Deux sources pour les mêmes allocations</h2>
<p>Les montants des comptes (OFGL, Observatoire des finances et de la gestion publique locales) et les dépenses que les départements déclarent à la Direction de la recherche, des études, de l’évaluation et des statistiques (DREES, enquête Aide sociale) ne sont pas lus de la même façon : comptes de l’exercice d’un côté, dépenses brutes déclarées de l’autre, complétées par une estimation de la DREES pour les départements qui n’ont pas répondu. Les deux sont montrées ; le site ne choisit pas entre elles et ne les additionne pas.</p>
${[...parGrandeur.entries()]
  .map(([g, lignes]) => {
    const d = GRANDEURS[g]
    lignes.sort((a, b) => a.annee - b.annee)
    return `<div class="tableau-defile"><table><caption>${h(d?.nom ?? g)} : comptes (somme hors Mayotte) et total estimé de la DREES (hors Mayotte), en euros</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Comptes (OFGL)</th><th scope="col" class="nombre">Enquête Aide sociale (DREES)</th><th scope="col" class="nombre">Écart</th><th scope="col" class="nombre">Écart, en part du montant de la DREES</th></tr></thead><tbody>${lignes
      .map(
        (e) =>
          `<tr><th scope="row">${h(e.annee)}</th>${cellule(montant(e.valeur))}${cellule(montant(e.autre_valeur))}${cellule(montant(e.ecart))}${cellule(typeof e.ecart_pct === 'number' ? pct(e.ecart_pct) : NON_PUBLIE)}</tr>`,
      )
      .join('')}</tbody></table></div>${lignes[0]?.lecture_ecart ? `<p class="aide">${h(majuscule(lignes[0].lecture_ecart))}.</p>` : ''}`
  })
  .join('\n')}
<p class="aide">Écart ${badgeCalcule('montant des comptes moins montant de la DREES, même année et même département')}. Un écart positif ou négatif ne dit pas laquelle des deux sources est juste.</p>`
}

function blocBeneficiairesNationaux(b: Beneficiaires | null, idx: IndexSolidarites): string {
  if (!b) return `<h2>Combien de bénéficiaires</h2>${absent('Bénéficiaires : donnée non disponible.')}`
  const fr = b.totaux.france ?? {}
  const series = SERIES.map(([id, l]) => ({ s: b.series.find((x) => x.id === id), l })).filter((x): x is { s: Serie; l: string } => !!x.s)
  const premiere = Math.min(...idx.annees_comptes)
  const annees = [...new Set(series.flatMap(({ s }) => s.annees))].filter((a) => a >= premiere).sort((a, c) => a - c)
  const v = (id: string, an: number) => {
    const s = series.find((x) => x.s.id === id)!.s
    const i = s.annees.indexOf(an)
    return i < 0 ? NON_PUBLIE : nombre(fr[id]?.[i])
  }
  return `<h2>Combien de bénéficiaires</h2>
<p>Nombre de personnes (ou de foyers pour le revenu de solidarité active) qui reçoivent chaque aide en fin d’année, publié par la DREES pour toute la France. Une personne peut recevoir plusieurs aides : ces nombres ne s’additionnent pas. Ce sont des totaux publiés, estimés par la DREES pour les départements qui n’ont pas répondu ; aucune personne n’est nommée.</p>
${tableauAnnees(
  'Bénéficiaires de l’aide sociale des départements, France entière, en fin d’année',
  annees.map(String),
  series.map(({ s, l }) => [s.id, l]),
  (an, id) => v(id, Number(an)),
)}
<details><summary>Champ et ruptures de chaque série</summary><ul>${series
    .map(
      ({ s, l }) =>
        `<li><strong>${h(l)}</strong> : ${h(propre(s.definition ?? s.libelle))} ; champ : ${h(s.champ ?? '')}${s.rupture ? ` ; rupture : ${h(propre(s.rupture))}` : ''}.</li>`,
    )
    .join('')}</ul><p class="aide">Champ : la France métropolitaine et les départements et régions d’outre-mer (DROM), Mayotte selon les séries.</p></details>
${sourceDrees(idx.sources.drees_paph)}${sourceDrees(idx.sources.drees_ase)}${sourceDrees(idx.sources.drees_minima)}`
}

// ---------------------------------------------------------------------------------------------------------------
// Vue par département
// ---------------------------------------------------------------------------------------------------------------

function noteRecentralise(idx: IndexSolidarites, dep: string): string {
  const r = idx.rsa_recentralise[dep]
  if (!r) return ''
  return `<p>${badgeStatut('trace')} Le revenu de solidarité active est financé par l’État dans ce département${r.debut ? ` depuis ${h(r.debut)}` : ''}${
    r.premiere_annee_entiere ? ` (première année entière : ${h(r.premiere_annee_entiere)})` : ''
  } : à partir de cette date, l’allocation et les recettes qui lui étaient rattachées ne figurent plus, ou plus en entier, dans les comptes du département.</p>`
}

function noteAlsace(code: string): string {
  if (code !== '67' && code !== '68') return ''
  return `<p class="aide"><strong>Bas-Rhin et Haut-Rhin jusqu’en 2020 :</strong> dans les comptes publiés par l’OFGL, le code 67A regroupe les deux départements, avec une ligne pour chacun par exercice. Le site lit chaque ligne par le numéro d’entreprise (SIREN) du département. Depuis 2021, la Collectivité européenne d’Alsace exerce leurs compétences : un seul compte pour les deux départements, à ne pas additionner.</p>`
}

function blocComptesCollectivite(code: string, c: CollComptes, comptes: Comptes, idx: IndexSolidarites): string {
  const annees = comptes.annees.filter((a) => (c.eur[a] ?? []).some((x) => x !== null && x !== undefined))
  if (!annees.length) return ''
  const i = (col: string) => comptes.colonnes.indexOf(col)
  const val = (an: string, col: string) => montant(c.eur[an]?.[i(col)])
  const dernier = annees[annees.length - 1]
  const parHab = (col: string) => {
    const x = c.eur_hab?.[dernier]?.[i(col)]
    return typeof x === 'number' ? `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(x)} €` : NON_PUBLIE
  }
  return `<h4>${h(c.nom)} (${h(annees[0])}${annees.length > 1 ? ` à ${h(dernier)}` : ''})</h4>
${c.perimetre ? `<p class="aide">Périmètre : ${h(c.perimetre)}.</p>` : ''}
${noteAlsace(code)}
${tableauAnnees(`${c.nom} : allocations versées, d’après ses comptes, en euros`, annees, ALLOCATIONS, val)}
${tableauAnnees(`${c.nom} : recettes rattachées aux allocations dans ses comptes, en euros`, annees, RECETTES, val)}
<p class="aide">Par habitant en ${h(dernier)} : revenu de solidarité active ${h(parHab('allocations_rsa'))}, allocation personnalisée d’autonomie ${h(parHab('allocations_apa'))}, prestation de compensation du handicap ${h(parHab('allocations_pch'))} (montant divisé par la population publiée par l’OFGL).</p>
${sourceComptes(idx)}`
}

function blocAse(codes: string[], terr: TerritoiresDep | null, annees: string[], idx: IndexSolidarites): string {
  const colls = (terr?.aide_sociale?.collectivites ?? []).filter((c) => codes.includes(c.code) && c.postes.ase?.brute?.eur)
  if (!colls.length) return `<h3>L’aide sociale à l’enfance</h3>${absent('Dépenses d’aide sociale à l’enfance de ce département : non publiées par la DREES dans les fichiers repris par le site.')}`
  const ans = annees.filter((a) => colls.some((c) => c.postes.ase.brute!.eur![a] !== undefined))
  const s = idx.sources.territoires
  return `<h3>L’aide sociale à l’enfance</h3>
<p>Dépenses brutes déclarées à la DREES (enquête Aide sociale), autre source que les comptes : elles ne s’ajoutent pas aux montants des comptes, dont les frais d’hébergement comprennent déjà les placements d’enfants. Valeurs telles que publiées ; pour l’Alsace, la Corse et le Rhône, la DREES publie aussi la collectivité d’aujourd’hui sur les années passées : colonnes à ne pas additionner.</p>
${tableauAnnees(
  'Aide sociale à l’enfance, dépenses brutes publiées par la DREES, en euros',
  ans,
  colls.map((c) => [c.code, c.nom]),
  (a, code) => montant(colls.find((c) => c.code === code)!.postes.ase.brute!.eur![a]),
)}
${s ? `<p class="source">Source : DREES, enquête Aide sociale, lue dans les fichiers du site sur les territoires (${h(s.millesime ?? '')}, ${h(s.licence ?? '')}) ${badgeStatut('trace')}</p>` : ''}`
}

function blocBeneficiairesDep(codes: string[], b: Beneficiaires, idx: IndexSolidarites): string {
  const colls = codes.map((c) => [c, b.collectivites[c]] as const).filter(([, x]) => !!x)
  if (!colls.length) return `<h3>Combien de bénéficiaires</h3>${absent('Bénéficiaires de ce département : non publiés par la DREES.')}`
  const premiere = Math.min(...idx.annees_comptes)
  return `<h3>Combien de bénéficiaires</h3>
<p>Nombres publiés par la DREES en fin d’année. Une personne peut recevoir plusieurs aides : ces nombres ne s’additionnent pas.</p>
${colls
  .map(([code, x]) => {
    const series = SERIES.map(([id, l]) => ({ s: b.series.find((y) => y.id === id), l })).filter((y): y is { s: Serie; l: string } => !!y.s)
    const annees = [...new Set(series.flatMap(({ s }) => s.annees))].filter((a) => a >= premiere && series.some(({ s }) => typeof x.valeurs[s.id]?.[s.annees.indexOf(a)] === 'number')).sort((a, c) => a - c)
    if (!annees.length) return ''
    return `${tableauAnnees(
      `${x.nom} (${code}) : bénéficiaires en fin d’année`,
      annees.map(String),
      series.map(({ s, l }) => [s.id, l]),
      (an, id) => {
        const s = series.find((y) => y.s.id === id)!.s
        const i = s.annees.indexOf(Number(an))
        return i < 0 ? NON_PUBLIE : nombre(x.valeurs[id]?.[i])
      },
    )}${x.perimetre ? `<p class="aide">Périmètre : ${h(x.perimetre)}.</p>` : ''}${
      typeof x.rsa_2016_ancien_systeme === 'number'
        ? `<p class="aide">Revenu de solidarité active en 2016 : la DREES publie aussi ${h(entier(x.rsa_2016_ancien_systeme))} allocataires selon l’ancien système de la CNAF ; le tableau reprend la valeur du nouveau système, comparable aux années suivantes.</p>`
        : ''
    }`
  })
  .join('')}
${sourceDrees(idx.sources.drees_paph)}`
}

function blocEcartsDep(codes: string[], e: Ecarts): string {
  const blocs = codes.flatMap((code) =>
    [...ecartsCollectivite(e, code).entries()].map(([g, lignes]) => {
      const d = GRANDEURS[g] ?? { nom: g, source: 'source', autre: 'autre source' }
      const f = (v: unknown) => (typeof v === 'number' ? (d.nombre ? entier(v) : eurLisible(v)) : NON_PUBLIE)
      return `<div class="tableau-defile"><table><caption>${h(d.nom)} (${h(code)}) : ${h(d.source)} et ${h(d.autre)}</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">${h(
        majuscule(d.source),
      )}</th><th scope="col" class="nombre">${h(majuscule(d.autre))}</th><th scope="col" class="nombre">Écart</th><th scope="col" class="nombre">Écart, en part de la seconde source</th></tr></thead><tbody>${lignes
        .map(
          (r) =>
            `<tr><th scope="row">${h(r.annee)}</th>${cellule(f(r.valeur))}${cellule(f(r.autre_valeur))}${cellule(f(r.ecart))}${cellule(typeof r.ecart_pct === 'number' ? pct(r.ecart_pct) : NON_PUBLIE)}</tr>`,
        )
        .join('')}</tbody></table></div>${e.grandeurs[g]?.lecture_ecart ? `<p class="aide">${h(majuscule(e.grandeurs[g].lecture_ecart!))}.</p>` : ''}`
    }),
  )
  if (!blocs.length) return ''
  return `<details class="sol-ecarts"><summary>Écarts entre sources pour ce département</summary>
<p>Les mêmes allocations et les mêmes bénéficiaires, vus par deux sources. Écart ${badgeCalcule('première source moins seconde source, même année et même champ')} ; le site ne choisit pas entre elles.</p>
${blocs.join('\n')}</details>`
}

const INVITE_DEP = '<p class="aide">Choisis un département pour voir ses comptes, ses bénéficiaires et les écarts entre sources.</p>'

export async function blocDepartement(idx: IndexSolidarites, code: string): Promise<string> {
  const d = departementChoisi(idx, code)
  if (!d) return INVITE_DEP
  const [comptes, benef, ecarts, terr] = await Promise.all([
    chargerSiPresent<Comptes>('solidarites_departements/comptes.json'),
    chargerSiPresent<Beneficiaires>('solidarites_departements/beneficiaires.json'),
    chargerSiPresent<Ecarts>('solidarites_departements/ecarts.json'),
    d.liens?.depenses_drees_par_poste ? chargerSiPresent<TerritoiresDep>(d.liens.depenses_drees_par_poste) : Promise.resolve(null),
  ])
  const nom = NOMS_DEP.get(code) ?? d.nom
  const collsComptes = d.comptes.filter((c) => comptes?.collectivites[c])
  const plusieurs = collsComptes.length > 1
  return `<h3>${h(nom)} (${h(code)}) : ce que versent ses comptes</h3>
${
  plusieurs
    ? `<p>Plusieurs collectivités ont exercé les compétences du département sur la période : chacune a ses comptes, présentés l’un après l’autre. ${
        idx.collectivites.some((c) => d.comptes.includes(c.code) && c.departements.length > 1) ? 'Une collectivité unique figure aussi sur la page de l’autre département : ses montants ne s’additionnent pas entre départements.' : ''
      }</p>`
    : ''
}
${noteRecentralise(idx, code)}
${comptes && collsComptes.length ? collsComptes.map((c) => blocComptesCollectivite(c, comptes.collectivites[c], comptes, idx)).join('\n') : absent('Comptes de ce département : donnée non disponible.')}
<p>Allocations et recettes sont publiées côte à côte, sans soustraction : aucun reste à charge officiel n’est publié pour ce département.</p>
${blocAse(d.beneficiaires, terr, comptes?.annees ?? idx.annees_comptes.map(String), idx)}
${benef ? blocBeneficiairesDep(d.beneficiaires, benef, idx) : `<h3>Combien de bénéficiaires</h3>${absent('Bénéficiaires : donnée non disponible.')}`}
${ecarts ? blocEcartsDep([...new Set([...d.comptes, ...d.beneficiaires])], ecarts) : ''}
<ul class="liens-sortie">
  <li><a href="#/explorer/prestations?dep=${h(code)}">Foyers du revenu de solidarité active payés par les caisses d’allocations familiales dans ce département</a></li>
  <li><a href="#/local/departement?dep=${h(code)}">Le budget du département et de ses communes</a></li>
</ul>`
}

// ---------------------------------------------------------------------------------------------------------------

/** Le reste à charge calculé par le pipeline n'est pas affiché (décision du propriétaire en attente) : le motif publié, qui l'annonce, est réécrit. */
export const motifInaccessible = (s: { source: string; motif: string }) =>
  /reste à charge/i.test(s.source) ? 'aucun jeu de données ouvert de l’administration ne le publie par département ; cette page n’en affiche pas d’estimation' : s.motif

function blocSources(idx: IndexSolidarites): string {
  const externes = Object.values(idx.sources).filter((s) => /^https:\/\//.test(s.page ?? s.url ?? ''))
  return `<h2>Ce que ces chiffres ne disent pas</h2>
<ul class="limites">
  ${(idx.sources_inaccessibles ?? []).map((s) => `<li>${traitStatut('nonpub')}<span><strong>${h(s.source)}</strong> : ${h(motifInaccessible(s))}.</span></li>`).join('')}
  ${(idx.limites ?? [])
    .filter((l) => !/reste_a_charge|ecarts\.json|catalogue|mise_a_jour/.test(l))
    .map((l) => `<li>${traitStatut('approche')}<span>${h(l.replace(/territoires\/<dep>\.json/g, 'les fichiers du site sur les territoires'))}</span></li>`)
    .join('')}
</ul>
<h2>Sources</h2>
<details><summary>Les jeux de données de cette page</summary><ul>${externes
    .map((s) => `<li><a href="${h(s.page ?? s.url ?? '')}" rel="noopener noreferrer">${h(s.titre)}</a>${s.producteur ? `, ${h(s.producteur)}` : ''} (${h(s.millesime ?? '')}, ${h(s.licence ?? '')})</li>`)
    .join('')}</ul>
${idx.methode?.comptes ? `<p class="aide">Méthode des comptes : ${h(idx.methode.comptes)}.</p>` : ''}
${idx.date_sources ? `<p class="aide">Sources lues le ${h(dateFr(idx.date_sources))}.</p>` : ''}
</details>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams): Promise<Rendu | void> {
  const idx = await chargerSiPresent<IndexSolidarites>('solidarites_departements/index.json')
  if (!idx) {
    cible.innerHTML =
      enCours(
        'Ce que les départements versent pour les solidarités',
        'Revenu de solidarité active, allocation personnalisée d’autonomie, prestation de compensation du handicap, aide sociale à l’enfance : montants versés, bénéficiaires et recettes reçues pour ces allocations.',
      ) +
      `<ul class="liens-sortie"><li><a href="#/explorer/prestations">Les prestations versées aux ménages</a></li><li><a href="#/explorer/collectivites">Les collectivités locales</a></li></ul>` +
      partPersonnelle()
    return
  }
  const [comptes, benef, terr] = await Promise.all([
    chargerSiPresent<Comptes>('solidarites_departements/comptes.json'),
    chargerSiPresent<Beneficiaires>('solidarites_departements/beneficiaires.json'),
    chargerSiPresent<TerritoiresIndex>('territoires/index.json'),
  ])
  const depInitial = departementChoisi(idx, params.get('dep'))?.code ?? ''
  const options = idx.departements
    .map((d) => `<option value="${h(d.code)}"${d.code === depInitial ? ' selected' : ''}>${h(d.code)} ${h(NOMS_DEP.get(d.code) ?? d.nom)}</option>`)
    .join('')
  const annees = idx.annees_comptes

  cible.innerHTML = `
<h1>Ce que les départements versent pour les solidarités</h1>
<p class="chapeau">Les départements versent le revenu de solidarité active (RSA), l’allocation personnalisée d’autonomie (APA) des personnes âgées, la prestation de compensation du handicap (PCH) et l’aide sociale à l’enfance (ASE). Cette page montre, de ${h(annees[0])} à ${h(
    annees[annees.length - 1],
  )}, ce que leurs comptes publiés indiquent pour ces aides, en France puis dans le département de ton choix, combien de personnes les reçoivent et quelles recettes l’État et la Sécurité sociale leur versent pour ces allocations.</p>
<p class="chapeau">Elle ne montre pas ce que reçoit une personne, ni la part de ces allocations qui reste payée par les impôts du département : aucun chiffre officiel de cette part n’est publié par département. Elle ne contient que des totaux publiés, sans aucune personne nommée.</p>
<ul class="legende-statuts" aria-label="Statuts des chiffres de cette page">
  <li>${traitStatut('trace')}<span><strong>Tracé</strong> : montant ou nombre lu tel quel dans une source publiée.</span></li>
  ${LEGENDE_CALCULE}
  <li>${traitStatut('nonpub')}<span><strong>Non publié</strong> : la source ne publie pas cette case ; elle n’est jamais remplacée par 0.</span></li>
</ul>
${blocCles(idx)}
${blocNational(idx, comptes, terr)}
${blocBeneficiairesNationaux(benef, idx)}
${blocEcartsNationaux(idx)}
<h2>Dans ton département</h2>
<p>Les comptes de chaque collectivité, ses bénéficiaires et les écarts entre sources. Depuis 2015 dans le Rhône, 2018 en Corse et 2021 en Alsace, une autre collectivité exerce les compétences du département : ses comptes sont présentés à part.</p>
<form id="sol-dep" class="recherche">
  <div>${listeRecherche({ id: 'sol-dep-choix', etiquette: 'Département', options: [], optionsHtml: `<option value="">Choisir un département</option>${options}` })}</div>
</form>
<div id="sol-dep-resultat" aria-live="polite">${depInitial ? '<p class="chargement">Chargement…</p>' : INVITE_DEP}</div>
<h2>Montants voisins sur d’autres pages</h2>
<p>D’autres pages du site montrent des montants proches, lus dans d’autres sources ou à un autre niveau. Ils ne sont pas recopiés ici et ne s’additionnent pas avec ceux de cette page.</p>
<ul class="liens-sortie">
  <li><a href="#/explorer/prestations">Les prestations versées aux ménages</a> : le revenu de solidarité active vu des caisses d’allocations familiales qui le paient (foyers et montants versés, par département).</li>
  <li><a href="#/explorer/collectivites">Les collectivités locales</a> : l’ensemble des dépenses et des recettes des départements.</li>
  <li><a href="#/explorer/secu">Sécurité sociale et protection sociale</a> : la branche autonomie, dont relève la caisse qui verse les dotations pour l’autonomie et le handicap.</li>
  <li><a href="#/explorer/hopitaux">Hôpitaux et établissements de santé</a> : ce que les départements versent aux établissements pour personnes âgées et handicapées.</li>
</ul>
${blocSources(idx)}
${partPersonnelle()}`
  appliquerLargeurs(cible)

  const zone = cible.querySelector<HTMLElement>('#sol-dep-resultat')!
  const choix = cible.querySelector<HTMLSelectElement>('#sol-dep-choix')!
  let jeton = 0
  const maj = async (code: string) => {
    const moi = ++jeton
    zone.setAttribute('aria-busy', 'true')
    const html = code ? await blocDepartement(idx, code) : INVITE_DEP
    if (moi !== jeton) return
    zone.innerHTML = html
    zone.removeAttribute('aria-busy')
    appliquerLargeurs(zone)
  }
  cible.querySelector('#sol-dep')?.addEventListener('submit', (e) => e.preventDefault())
  choix.addEventListener('change', () => void maj(choix.value))
  const d = depInitial ? departementChoisi(idx, depInitial) : null
  return {
    suite: depInitial ? maj(depInitial) : undefined,
    ...(d
      ? {
          titre: `${NOMS_DEP.get(d.code) ?? d.nom} (${d.code}) : ce que le département verse pour les solidarités`,
          description: `${NOMS_DEP.get(d.code) ?? d.nom} (${d.code}) : allocations versées pour le revenu de solidarité active, l’autonomie et le handicap, recettes reçues pour ces allocations, bénéficiaires et écarts entre sources.`,
        }
      : {}),
  }
}

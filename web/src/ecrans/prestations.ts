// Prestations versées aux ménages (site/data/prestations/) : combien est versé par prestation et par an, à combien
// de foyers, qui verse et qui finance, l'évolution publiée et le détail par département quand il existe.
// Agrégats publiés seulement, aucune donnée individuelle. Chaque série garde sa source : deux sources ne sont jamais
// additionnées et leurs écarts sont montrés tels que le pipeline les publie. Les liens vers les arbres (budget de
// l'État, Sécurité sociale) désignent le même argent vu du côté du financeur : jamais ajoutés au montant versé.
import { fragmentDepartement } from '../chemins'
import { partPersonnelle } from '../composants/hub'
import { TOUS_DEPARTEMENTS } from '../departements'
import { chargerSiPresent, VUES_ARBRE } from '../donnees'
import { lien } from '../routeur'
import { route } from '../routes'
import { appliquerLargeurs, badgeStatut, barres, entier, eur, eurLisible, h, pct, source, sur100, surligne, traitStatut } from '../util'
import { enCours } from './dette'

type Valeur = number | null
type Serie = Record<string, Valeur>

interface LienFinanceur {
  vue: string
  fichier: string
  id: string
  nom: string
  md?: number
  millesime: string
  lecture?: string
  partage_avec?: string[]
}
interface PrestationIndex {
  id: string
  nom: string
  financeur: string
  serie_principale: string
  liens: LienFinanceur[]
}
interface Ecart {
  prestation: string
  annee: number
  source: string
  montant: number
  autre_source: string
  autre_montant: number
  ecart: number
  ecart_pct: number
  lecture_ecart: string
  lien?: string
  grandeur?: string
  note?: string
  codes_mois_manquants?: string[]
}
interface Source {
  titre: string
  url: string
  page?: string
  producteur?: string
  millesime: string
  licence: string
}
export interface IndexPrestations {
  millesime: string
  date_sources?: string
  annees: number[]
  prestations: PrestationIndex[]
  fichiers: { departements: Record<string, string> }
  totaux: {
    drees_cps?: { prestations: string[]; montant_eur: Serie; total_prestations_protection_sociale_eur: Serie; part_du_total_pct?: Serie; lecture: string }
    cnaf_depenses?: { prestations: string[]; montant_eur: Serie; lecture: string }
  }
  ecarts: Ecart[]
  ecarts_departements: Ecart[]
  couverture_departementale: {
    non_couvert: string[]
    grandeurs?: Record<string, string>
    rsa_recentralise: Record<string, { premiere_annee_entiere?: number; debut?: string }>
  }
  regle: string
  sources: Record<string, Source>
  sources_inaccessibles: { source: string; motif: string }[]
}
interface Prestation {
  nom: string
  financeur: string
  serie_principale: string
  sources_montant: Record<string, Serie>
  derniere_annee: number
  detail?: Record<string, { nom?: string; source: string; montant_eur: Serie }>
  beneficiaires: Serie
  beneficiaires_definition?: string
  source_beneficiaires?: string
  beneficiaires_moyenne_mensuelle?: Serie
  comparaison_beneficiaires?: { source: string; definition: string; valeurs: Serie }
  montant_moyen_eur: Serie
  montant_moyen_periode?: string
  montant_moyen_methode: string
  par_regime?: { code_secteur: string; regime: string; fichier: string; montant_eur: Serie }[]
}
export interface NationalesPrestations {
  annees: number[]
  prestations: Record<string, Prestation>
}
type Triplet = [Valeur, Valeur, Valeur]
interface Departements {
  millesime: string
  source: string
  annee: number
  definitions: Record<string, string>
  prestations: Record<string, string>
  departements: Record<string, Record<string, Triplet | string>>
  note_perimetre: string
}

const PAGE_SECU = '/explorer/secu'
const MOINS = '−'
const CAF_MSA = 'les caisses d’allocations familiales ; la Mutualité sociale agricole pour les personnes du régime agricole'

/** Séries de montants, sans sigle seul : libellé court (en-têtes, milieu de phrase) et long (phrases). */
const SERIES: Record<string, [string, string]> = {
  cnaf_depenses: ['caisses d’allocations familiales et Mutualité sociale agricole', 'dépenses de toutes les caisses (caisses d’allocations familiales et Mutualité sociale agricole), publiées par la Caisse nationale des allocations familiales'],
  drees_cps: ['comptes de la protection sociale', 'comptes de la protection sociale, publiés par la DREES, le service statistique des ministères sociaux'],
  unedic: ['assurance chômage selon l’Unédic', 'allocations et aides versées par l’assurance chômage, publiées par l’Unédic'],
  drees_minima_depenses: ['dépenses des minima sociaux', 'dépenses des minima sociaux, publiées par la DREES, le service statistique des ministères sociaux'],
  arbre_etat: ['budget de l’État', 'budget de l’État, crédits dépensés'],
  secu_arbre: ['comptes des organismes de sécurité sociale', 'comptes des organismes de sécurité sociale'],
  cnaf_departements: ['somme des départements', 'somme des montants versés par les caisses d’allocations familiales dans chaque département'],
}
/** Effectifs : libellé de la ligne et producteur. */
const EFFECTIFS: Record<string, [string, string]> = {
  cnaf_beneficiaires: ['Foyers', 'Caisse nationale des allocations familiales'],
  drees_minima_nationales: ['Allocataires', 'DREES, service statistique des ministères sociaux'],
  francetravail_indemnises: ['Allocataires indemnisés', 'France Travail'],
}
const serie = (k: string) => SERIES[k] ?? [k, k]
const majuscule = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** Ce qu'est chaque prestation et qui la verse, en langage courant (le financeur, lui, est lu dans les données). */
const FICHES: Record<string, { quoi: string; verse: string }> = {
  allocations_familiales: {
    quoi: 'Versées chaque mois aux familles qui ont au moins deux enfants à charge de moins de 20 ans (dès le premier enfant dans les départements d’outre-mer). Le montant dépend du nombre d’enfants et des revenus du foyer.',
    verse: CAF_MSA,
  },
  aides_logement: {
    quoi: 'Elles aident à payer le loyer de la résidence principale, ou dans certains cas les mensualités d’un prêt pour l’acheter. Trois aides : l’aide personnalisée au logement (APL), l’allocation de logement familiale (ALF) et l’allocation de logement sociale (ALS). Le montant dépend des revenus, du loyer, du lieu et de la composition du foyer.',
    verse: CAF_MSA,
  },
  rsa: {
    quoi: 'Revenu minimum versé sous conditions de ressources aux personnes de 25 ans ou plus, et dans certains cas plus jeunes (parent isolé, jeune ayant déjà travaillé). Il complète les ressources du foyer jusqu’à un montant forfaitaire qui dépend de sa composition.',
    verse: CAF_MSA,
  },
  prime_activite: {
    quoi: 'Complément de revenu versé sous conditions de ressources aux personnes de 18 ans ou plus qui travaillent, salariées ou indépendantes. Le montant dépend des revenus d’activité et de la composition du foyer.',
    verse: CAF_MSA,
  },
  aah: {
    quoi: 'Revenu minimum versé sous conditions de ressources aux adultes dont le handicap est reconnu par la commission de la maison départementale des personnes handicapées. Les montants comprennent ses compléments.',
    verse: CAF_MSA,
  },
  aspa: {
    quoi: 'Le minimum vieillesse : l’allocation de solidarité aux personnes âgées (Aspa) et l’ancienne allocation supplémentaire vieillesse (ASV) complètent, sous conditions de ressources, les revenus des personnes de 65 ans ou plus, ou plus tôt en cas d’inaptitude au travail.',
    verse: 'la caisse de retraite qui verse déjà une pension (Assurance retraite, Mutualité sociale agricole et autres régimes) ; un service géré par la Caisse des dépôts pour les personnes sans pension',
  },
  paje: {
    quoi: 'Aides liées à l’arrivée et à la garde d’un jeune enfant : prime à la naissance ou à l’adoption, allocation de base, aide pour faire garder l’enfant (complément de libre choix du mode de garde) et prestation partagée d’éducation de l’enfant, pour le parent qui réduit ou arrête son activité.',
    verse: CAF_MSA,
  },
  ars: {
    quoi: 'Versée une fois par an, avant la rentrée, sous conditions de ressources, pour chaque enfant scolarisé de 6 à 18 ans. Le montant dépend de l’âge de l’enfant.',
    verse: CAF_MSA,
  },
  are: {
    quoi: 'L’allocation chômage : revenu de remplacement versé aux personnes qui ont perdu leur emploi et ont suffisamment travaillé auparavant, y compris pendant une formation. Le montant dépend de l’ancien salaire.',
    verse: 'France Travail, pour le compte de l’assurance chômage',
  },
  pensions_retraite: {
    quoi: 'Pensions versées aux retraités au titre de leur carrière (droit direct) ou de celle d’un conjoint décédé (réversion), par les régimes de base, complémentaires et supplémentaires.',
    verse: 'chaque régime de retraite (détail par régime ci-dessous)',
  },
  indemnites_journalieres: {
    quoi: 'Revenu de remplacement versé pendant un arrêt de travail pour maladie, accident du travail ou maladie professionnelle, et pendant les congés de maternité et de paternité.',
    verse: 'les caisses primaires d’assurance maladie ; la Mutualité sociale agricole et les autres régimes pour leurs assurés',
  },
}
/** Libellés des parties détaillées sans nom dans les données (indemnités journalières). */
const PARTIES: Record<string, string> = {
  maladie: 'maladie',
  at_mp: 'accidents du travail et maladies professionnelles',
  maternite_paternite: 'maternité et paternité',
}
/** Pages du site qui détaillent une prestation : renvoi plutôt que bloc recopié (lien posé seulement si la route existe). */
const VOIR_AUSSI: Record<string, string> = { pensions_retraite: '/explorer/retraites' }
/** Codes de la CNAF qui ne sont pas des départements. */
const HORS_DEPARTEMENT: Record<string, string> = { '978': 'Saint-Martin', '99': 'résidence à l’étranger ou inconnue', XX: 'résidence inconnue' }
/** Colonnes du tableau départemental et leur libellé (le financeur du RSA est dit en mots sous le tableau). */
const DEFINITIONS_DEP: Record<string, string> = {
  foyers_decembre: 'Foyers',
  montant_annuel_eur: 'Montant versé dans l’année',
  montant_moyen_eur: 'Montant moyen',
}
/** Notes de la source lues par le public : une valeur absente se dit « non publié ». */
const enMots = (s: string) =>
  s
    .replace(/\bnull\b/g, 'non publié')
    .replace(/\bnœud(s?)\b/g, 'bloc$1')
    .replace(/\(voir sources_inaccessibles\)/g, '(voir « Ce que ces chiffres ne disent pas »)')
const INVITE_DEP = '<p class="aide">Choisis un département pour voir les foyers et les montants versés.</p>'

const NON_PUBLIE = badgeStatut('nonpub')
const estNombre = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x)
const cellule = (x: Valeur | undefined, f: (n: number) => string) => (estNombre(x) ? h(f(x)) : NON_PUBLIE)
const signe = (x: number, f: (n: number) => string) => `${x > 0 ? '+' : x < 0 ? MOINS : ''}${f(Math.abs(x))}`
const ecartTexte = (e: Ecart, f: (n: number) => string) => `${signe(e.ecart, f)} (${signe(e.ecart_pct, (n) => pct(n))})`
const anneesDe = (s: Serie | undefined) => Object.keys(s ?? {}).filter((a) => estNombre(s![a])).sort()
/** Dernière année où toutes les séries ont une valeur. */
const derniere = (...series: (Serie | undefined)[]) => anneesDe(series[0]).filter((a) => series.every((s) => estNombre(s?.[a]))).pop()
/** Montant d'un bloc d'arbre (milliards d'euros dans les données), en unité lisible : « 57,8 Md€ », « 4,6 M€ ». */
const mdLisible = (x: number) => eurLisible(Math.round(x * 1e9))
const periode = (p?: Prestation) => (p?.montant_moyen_periode === 'an' ? 'an' : 'mois')
const moyenne = (x: Valeur | undefined, p?: Prestation) => (estNombre(x) ? h(`${eur(x)} par ${periode(p)}`) : NON_PUBLIE)
const nomsDepartements = new Map(TOUS_DEPARTEMENTS)
const nomCode = (c: string) => nomsDepartements.get(c) ?? HORS_DEPARTEMENT[c] ?? c
const dateFr = (iso?: string) => (iso && /^\d{4}-\d{2}-\d{2}/.test(iso) ? iso.slice(0, 10).split('-').reverse().join('/') : '')

/** Visionneuse où ouvrir un bloc de financeur : le dossier du fichier lié désigne la vue. */
const VUES_SECU: [string, string][] = [
  ['secu/arbre_2025/', 'organismes2025'],
  ['secu/arbre/', 'organismes2024'],
  ['secu/cps/', 'protection2024'],
]
export function adresseBloc(l: { vue?: string; fichier: string; id: string }): string | null {
  const etat = VUES_ARBRE.find((v) => l.fichier.startsWith(v.dossier + '/'))
  if (etat) return lien('/explorer/etat/detail', { m: etat.cle, id: l.id })
  const secu = VUES_SECU.find(([d]) => l.fichier.startsWith(d))
  if (secu) return lien(PAGE_SECU, { m: secu[1], id: l.id })
  if (l.vue === 'local') return lien('/explorer/collectivites')
  return null
}
const lienBloc = (l: { vue?: string; fichier: string; id: string; nom: string }) => {
  const a = adresseBloc(l)
  return a ? `<a href="${h(a)}">${h(l.nom)}</a>` : h(l.nom)
}

/** Sources citées avec leur lien, leur millésime et leur licence. */
function citer(index: IndexPrestations, cles: string[]): string {
  const vues = [...new Set(cles)].map((k) => index.sources[k]).filter((s): s is Source => !!s)
  if (!vues.length) return ''
  return `<p class="source">${vues.map((s) => `<a href="${h(s.page ?? s.url)}" rel="noopener noreferrer">${h(s.titre)}</a> (${h(s.millesime)}, ${h(s.licence)})`).join(' ; ')}</p>`
}

/** Ligne « Écart » d'un tableau de séries : un écart publié par année, « sans objet » quand l'une des sources manque. */
function ligneEcart(titre: string, annees: string[], ecarts: Ecart[], f: (n: number) => string): string {
  if (!ecarts.length) return ''
  const par = new Map(ecarts.map((e) => [String(e.annee), e]))
  return `<tr><th scope="row">${h(titre)}</th>${annees.map((a) => `<td class="nombre">${par.has(a) ? h(ecartTexte(par.get(a)!, f)) : 'sans objet'}</td>`).join('')}</tr>`
}
const ligneSerie = (titre: string, statut: 'trace' | 'approche', annees: string[], s: Serie | undefined, f: (n: number) => string) =>
  `<tr><th scope="row">${titre} ${badgeStatut(statut)}</th>${annees.map((a) => `<td class="nombre">${cellule(s?.[a], f)}</td>`).join('')}</tr>`

function fiche(p: PrestationIndex, n: Prestation, index: IndexPrestations, annees: string[]): string {
  const an = String(n.derniere_annee)
  const principale = n.serie_principale
  const sources = [principale, ...Object.keys(n.sources_montant).filter((k) => k !== principale)]
  const montant = n.sources_montant[principale]?.[an]
  const ben = n.beneficiaires?.[an]
  const moy = n.montant_moyen_eur?.[an]
  const [libBen, prodBen] = EFFECTIFS[n.source_beneficiaires ?? ''] ?? ['Bénéficiaires', '']
  const texte = FICHES[p.id]
  const miens = index.ecarts.filter((e) => e.prestation.split('+').includes(p.id))
  // Évolution : première et dernière année publiées de la série principale, en euros courants.
  const ans = anneesDe(n.sources_montant[principale])
  const [a0, a1] = [ans[0], ans[ans.length - 1]]
  const v0 = a0 ? n.sources_montant[principale][a0] : null
  const v1 = a1 ? n.sources_montant[principale][a1] : null
  const ansBen = anneesDe(n.beneficiaires)
  const evolution =
    ans.length > 1 && estNombre(v0) && estNombre(v1) && v0 > 0
      ? `<p>De ${h(a0)} à ${h(a1)}, le montant versé (${h(serie(principale)[0])}) passe de ${h(eurLisible(v0))} à ${h(eurLisible(v1))}, soit ${h(signe((v1 / v0 - 1) * 100, (x) => pct(x)))} en euros courants, sans correction de l’inflation.${
          ansBen.length > 1
            ? ` ${h(libBen)} : ${h(entier(n.beneficiaires[ansBen[0]]!))} en ${h(ansBen[0])}, ${h(entier(n.beneficiaires[ansBen[ansBen.length - 1]]!))} en ${h(ansBen[ansBen.length - 1])}.`
            : ''
        }</p>`
      : ''
  // Tableau des séries : une ligne par source, jamais additionnées ; une ligne d'écart sous chaque comparaison publiée.
  const ecMontant = miens.filter((e) => !e.grandeur && sources.includes(e.source) && sources.includes(e.autre_source))
  const ecBen = miens.filter((e) => e.grandeur === 'beneficiaires')
  const comp = n.comparaison_beneficiaires
  const lignes: string[] = sources.map((k) => ligneSerie(`Montant versé : ${h(serie(k)[0])}`, 'trace', annees, n.sources_montant[k], eurLisible))
  if (ecMontant.length) lignes.push(ligneEcart(`Écart : ${serie(ecMontant[0].source)[0]} moins ${serie(ecMontant[0].autre_source)[0]}`, annees, ecMontant, eurLisible))
  for (const [cle, d] of Object.entries(n.detail ?? {})) lignes.push(ligneSerie(`dont ${h(d.nom ?? PARTIES[cle] ?? cle)}`, 'trace', annees, d.montant_eur, eurLisible))
  if (anneesDe(n.beneficiaires).length) lignes.push(ligneSerie(`${h(libBen)}${prodBen ? ` (${h(prodBen)})` : ''}`, 'trace', annees, n.beneficiaires, entier))
  if (comp && anneesDe(comp.valeurs).length) lignes.push(ligneSerie(`${h(EFFECTIFS[comp.source]?.[0] ?? 'Allocataires')} (${h(EFFECTIFS[comp.source]?.[1] ?? comp.source)})`, 'trace', annees, comp.valeurs, entier))
  if (ecBen.length) lignes.push(ligneEcart('Écart entre les deux effectifs', annees, ecBen, entier))
  if (n.beneficiaires_moyenne_mensuelle) lignes.push(ligneSerie(`${h(libBen)}, moyenne des douze mois`, 'trace', annees, n.beneficiaires_moyenne_mensuelle, entier))
  if (anneesDe(n.montant_moyen_eur).length) lignes.push(ligneSerie(`Montant moyen par foyer et par ${periode(n)}`, 'approche', annees, n.montant_moyen_eur, eur))
  const lectures = [...new Set([...ecMontant, ...ecBen].map((e) => e.lecture_ecart))]
  const tableau = `<details><summary>Évolution année par année et écarts entre sources</summary>
<div class="tableau-defile"><table><caption>${h(p.nom)} : une ligne par source, jamais additionnées</caption><thead><tr><th scope="col">Série</th>${annees.map((a) => `<th scope="col" class="nombre">${h(a)}</th>`).join('')}</tr></thead><tbody>${lignes.join('')}</tbody></table></div>
<ul class="aide">
${n.beneficiaires_definition ? `<li>${h(libBen)} : ${h(enMots(n.beneficiaires_definition))}.</li>` : ''}
${comp ? `<li>${h(EFFECTIFS[comp.source]?.[0] ?? 'Allocataires')} : ${h(enMots(comp.definition))}.</li>` : ''}
<li>Montant moyen : ${h(enMots(n.montant_moyen_methode))}.</li>
${lectures.map((l) => `<li>Écart (première source moins la seconde, en part de la seconde) : ${h(enMots(l))}.</li>`).join('')}
<li>« Non publié » : la source ne publie pas cette année ; la case n’est jamais remplacée par 0.</li>
</ul></details>`
  // Le même argent vu du côté du financeur : blocs des arbres (les lignes de la protection sociale sont listées par régime).
  const blocs = p.liens.filter((l) => l.vue !== 'secu_cps')
  const nomDe = (id: string) => index.prestations.find((x) => x.id === id)?.nom ?? id
  const items = blocs.map((l) => {
    const e = miens.find((x) => x.lien === l.id)
    return `<li>${lienBloc(l)} : ${typeof l.md === 'number' ? `${h(mdLisible(l.md))} (${h(l.millesime)}) ${badgeStatut('trace')}` : h(l.millesime)}${
      e ? `. Écart entre ${h(serie(e.source)[0])} et ce bloc en ${e.annee} : ${h(ecartTexte(e, eurLisible))}` : ''
    }${l.partage_avec?.length ? `. Ce bloc finance aussi : ${h(l.partage_avec.map(nomDe).join(', '))}` : ''}.${
      l.lecture || e ? ` <span class="aide">${[l.lecture, e?.lecture_ecart, e?.note].filter(Boolean).map((x) => `${h(majuscule(enMots(x!)))}.`).join(' ')}</span>` : ''
    }</li>`
  })
  for (const e of miens.filter((x) => !x.grandeur && !ecMontant.includes(x) && !blocs.some((l) => l.id === x.lien)))
    items.push(
      `<li>${h(majuscule(serie(e.autre_source)[0]))}${e.lien ? ` (${h(e.lien.split(' + ').length)} blocs réunis)` : ''}, ${e.annee} : ${h(eurLisible(e.autre_montant))}, contre ${h(eurLisible(e.montant))} (${h(serie(e.source)[0])}). Écart : ${h(ecartTexte(e, eurLisible))}. <span class="aide">${h(majuscule(enMots(e.lecture_ecart)))}.${e.note ? ` ${h(majuscule(enMots(e.note)))}.` : ''}</span></li>`,
    )
  const financeurs = items.length
    ? `<details><summary>Le même argent dans les comptes du financeur</summary><ul>${items.join('')}</ul><p class="aide">Ces blocs désignent le même argent vu du côté de celui qui finance : ils ne s’ajoutent pas au montant versé.</p></details>`
    : ''
  // Lignes des comptes de la protection sociale, par régime ; pensions : tous les régimes publiés.
  const cps = p.liens.filter((l) => l.vue === 'secu_cps')
  const anRegime = n.par_regime?.length ? derniere(...n.par_regime.map((r) => r.montant_eur)) : undefined
  const regimes =
    n.par_regime?.length && anRegime
      ? `<details><summary>Par régime de retraite, en ${h(anRegime)}</summary><div class="tableau-defile"><table><caption>Pensions de retraite par régime en ${h(anRegime)} (comptes de la protection sociale), du montant le plus élevé au plus faible</caption><thead><tr><th scope="col">Régime</th><th scope="col" class="nombre">Montant ${badgeStatut('trace')}</th></tr></thead><tbody>${[...n.par_regime]
          .sort((a, b) => (b.montant_eur[anRegime] ?? 0) - (a.montant_eur[anRegime] ?? 0))
          .map((r) => `<tr><th scope="row">${lienBloc({ fichier: r.fichier, id: `${r.code_secteur}/${r.regime}`, nom: r.regime })}</th><td class="nombre">${cellule(r.montant_eur[anRegime], eurLisible)}</td></tr>`)
          .join('')}</tbody></table></div></details>`
      : cps.length
        ? `<details><summary>Dans les comptes de la protection sociale, par régime</summary><ul>${cps
            .map((l) => `<li>${lienBloc(l)}, ${h(l.id.split('/')[1] ?? '')} : ${typeof l.md === 'number' ? `${h(mdLisible(l.md))} ` : ''}(${h(l.millesime)}) ${badgeStatut('trace')}</li>`)
            .join('')}</ul></details>`
        : ''
  const detaillee = VOIR_AUSSI[p.id] ? route(VOIR_AUSSI[p.id]) : undefined
  return `<section class="carte" aria-labelledby="pr-${h(p.id)}">
<h3 id="pr-${h(p.id)}">${h(p.nom)}</h3>
${texte ? `<p>${h(texte.quoi)}</p>` : ''}
<ul class="lignes">
<li><span>Montant versé en ${h(an)}</span><span class="montant">${cellule(montant, eurLisible)}</span><span class="dest">${estNombre(montant) ? `${badgeStatut('trace')} ` : ''}${h(majuscule(serie(principale)[1]))}</span></li>
<li><span>${h(libBen)} en ${h(an)}</span><span class="montant">${cellule(ben, entier)}</span><span class="dest">${
    estNombre(ben) ? `${badgeStatut('trace')} ${h(majuscule(enMots(n.beneficiaires_definition ?? '')))}` : 'Aucun effectif annuel repris pour cette prestation (voir « Ce que ces chiffres ne disent pas »).'
  }</span></li>
<li><span>Montant moyen par foyer</span><span class="montant">${moyenne(moy, n)}</span><span class="dest">${estNombre(moy) ? `${badgeStatut('approche')} ` : ''}${h(majuscule(enMots(n.montant_moyen_methode)))}</span></li>
${texte ? `<li><span>Qui verse</span><span class="dest">${h(majuscule(texte.verse))}</span></li>` : ''}
<li><span>Qui finance</span><span class="dest">${h(p.financeur)}</span></li>
</ul>
${evolution}
${tableau}
${financeurs}
${regimes}
${detaillee ? `<p class="liens-sortie"><a href="#${h(detaillee.chemin)}">${h(detaillee.titre)}</a></p>` : ''}
${citer(index, [...sources, n.source_beneficiaires ?? '', comp?.source ?? ''])}
</section>`
}

const triplet = (x: Triplet | string | undefined): Triplet | null => (Array.isArray(x) ? x : null)

/** Bloc d'un département pour une année : foyers, montants, montant moyen, part dans la somme des départements. */
async function blocDepartement(index: IndexPrestations, nat: NationalesPrestations, ordre: string[], code: string, an: string): Promise<string> {
  const f = index.fichiers.departements[an]
  const d = f ? await chargerSiPresent<Departements>(f) : null
  const ligne = d?.departements[code]
  if (!d || !ligne) return `<p class="absent">Pas de données publiées pour ${h(nomCode(code))} en ${h(an)}.</p>`
  const nom = nomsDepartements.get(code) ?? String(ligne.nom ?? code).replace(/\s*\(\d+\)\s*$/, '')
  // Renvoi « (1) » de la source : effectifs estimés par la DREES (Corse, minimum vieillesse).
  const estime = /\(\d+\)\s*$/.test(String(ligne.nom ?? ''))
  const dreesDep = (k: string) => /DREES/.test(index.couverture_departementale.grandeurs?.[k] ?? '')
  const cles = [...ordre.filter((k) => k in d.prestations), ...Object.keys(d.prestations).filter((k) => !ordre.includes(k))]
  const total = Object.keys(d.departements).length
  const comptes: number[] = []
  const lignes = cles
    .map((k) => {
      const t = triplet(ligne[k])
      if (!t) return ''
      const publies = Object.values(d.departements)
        .map((r) => triplet(r[k])?.[1])
        .filter(estNombre)
      const somme = publies.reduce((s, x) => s + x, 0)
      if (publies.length) comptes.push(publies.length)
      const foyers = estNombre(t[0]) ? `${h(entier(t[0]))}${estime && dreesDep(k) ? ` ${badgeStatut('approche')}` : ''}` : NON_PUBLIE
      return `<tr><th scope="row">${h(d.prestations[k])}</th><td class="nombre">${foyers}</td><td class="nombre">${cellule(t[1], eurLisible)}</td><td class="nombre">${moyenne(t[2], nat.prestations[k])}</td><td class="nombre">${
        estNombre(t[1]) && somme > 0 ? h(sur100((t[1] / somme) * 100)) : NON_PUBLIE
      }</td></tr>`
    })
    .join('')
  const [cMin, cMax] = [Math.min(...comptes), Math.max(...comptes)]
  const rec = index.couverture_departementale.rsa_recentralise[code]
  const fin = typeof ligne.financeur_rsa === 'string' ? ligne.financeur_rsa : ''
  const financeurRsa =
    fin === 'etat'
      ? `l’État : le RSA y est recentralisé${rec?.premiere_annee_entiere ? ` (première année entière de financement par l’État : ${rec.premiere_annee_entiere})` : ''}`
      : fin === 'departement_puis_etat'
        ? `le département, puis l’État${rec?.debut ? ` à partir de ${rec.debut}` : ''}`
        : fin === 'departement'
          ? 'le département'
          : ''
  const ecarts = index.ecarts_departements.filter((e) => String(e.annee) === an)
  const manquants = [...new Set(ecarts.flatMap((e) => e.codes_mois_manquants ?? []))]
  const comparaison = ecarts.length
    ? `<details><summary>Somme des départements et total national en ${h(an)}</summary><div class="tableau-defile"><table><caption>Somme des départements comparée aux dépenses nationales de toutes les caisses, ${h(an)}</caption><thead><tr><th scope="col">Prestation</th><th scope="col" class="nombre">${h(majuscule(serie(ecarts[0].source)[0]))}</th><th scope="col" class="nombre">${h(majuscule(serie(ecarts[0].autre_source)[0]))}</th><th scope="col" class="nombre">Écart</th></tr></thead><tbody>${ecarts
        .map((e) => `<tr><th scope="row">${h(d.prestations[e.prestation] ?? nat.prestations[e.prestation]?.nom ?? e.prestation)}</th><td class="nombre">${h(eurLisible(e.montant))}</td><td class="nombre">${h(eurLisible(e.autre_montant))}</td><td class="nombre">${h(ecartTexte(e, eurLisible))}</td></tr>`)
        .join('')}</tbody></table></div><ul class="aide">${[...new Set(ecarts.map((e) => e.lecture_ecart))].map((l) => `<li>${h(majuscule(enMots(l)))}.</li>`).join('')}${
        manquants.length ? `<li>Mois manquants à la source cette année-là : ${h(manquants.map((c) => `${nomCode(c)} (${c})`).join(', '))}.</li>` : ''
      }</ul></details>`
    : ''
  const ans = Object.keys(index.fichiers.departements).sort()
  const srcRsa = index.sources.rsa_recentralise
  const rienDesCaisses = cles.filter((k) => !dreesDep(k)).every((k) => (triplet(ligne[k]) ?? [null, null, null]).every((x) => x === null))
  return `<h3>${h(nom)} (${h(code)}) en ${h(an)}</h3>
${rienDesCaisses ? `<p class="absent">La source ne publie, pour ${h(nom)} en ${h(an)}, ni foyers ni montants des caisses d’allocations familiales : voir les notes sous le tableau.</p>` : ''}
<div class="tableau-defile"><table><caption>${h(nom)}, ${h(an)} : foyers et montants versés par les caisses d’allocations familiales (sans la Mutualité sociale agricole)</caption>
<thead><tr><th scope="col">Prestation</th><th scope="col" class="nombre">Foyers ${badgeStatut('trace')}</th><th scope="col" class="nombre">Montant versé dans l’année ${badgeStatut('trace')}</th><th scope="col" class="nombre">Montant moyen par foyer ${badgeStatut('approche')}</th><th scope="col" class="nombre">Sur 100 € versés dans les départements</th></tr></thead>
<tbody>${lignes}</tbody></table></div>
${financeurRsa ? `<p>Qui finance le revenu de solidarité active ici en ${h(an)} : ${h(financeurRsa)}.</p>` : ''}
<ul class="aide">${Object.entries(d.definitions)
    .filter(([k]) => k in DEFINITIONS_DEP)
    .map(([k, v]) => `<li>${h(DEFINITIONS_DEP[k])} : ${h(enMots(v))}.</li>`)
    .join('')}${
    comptes.length ? `<li>Sur 100 € : part du département dans la somme des départements dont le montant est publié cette année-là (${cMin === cMax ? cMin : `${cMin} à ${cMax}`} sur ${total}), même source.</li>` : ''
  }<li>${h(majuscule(enMots(d.note_perimetre)))}.</li>${estime ? '<li>Minimum vieillesse : effectif estimé par la DREES pour ce département (renvoi de la source), d’où le statut « approché ».</li>' : ''}</ul>
${source(d.source, d.millesime)}
${fin && fin !== 'departement' && srcRsa ? `<p class="source">Financement du revenu de solidarité active : <a href="${h(srcRsa.page ?? srcRsa.url)}" rel="noopener noreferrer">${h(srcRsa.titre)}</a></p>` : ''}
${comparaison}
<details class="pr-evolution" data-code="${h(code)}"><summary>Évolution de ${h(ans[0] ?? '')} à ${h(ans[ans.length - 1] ?? '')} dans ce département</summary><div class="pr-evolution-zone"></div></details>
<p class="liens-sortie"><a href="${h(fragmentDepartement(code, nom))}">Le budget des communes de ce département : ${h(nom)}</a></p>`
}

/** Tables d'évolution d'un département, toutes années : montants versés et foyers. */
async function evolutionDepartement(index: IndexPrestations, ordre: string[], code: string): Promise<string> {
  const ans = Object.keys(index.fichiers.departements).sort()
  const fichiers = await Promise.all(ans.map((a) => chargerSiPresent<Departements>(index.fichiers.departements[a])))
  const noms = new Map<string, string>()
  for (const f of fichiers) for (const [k, v] of Object.entries(f?.prestations ?? {})) noms.set(k, v)
  const cles = [...ordre.filter((k) => noms.has(k)), ...[...noms.keys()].filter((k) => !ordre.includes(k))]
  const nom = nomCode(code)
  const tableau = (i: 0 | 1, titre: string, f: (n: number) => string) =>
    `<div class="tableau-defile"><table><caption>${h(titre)}</caption><thead><tr><th scope="col">Prestation</th>${ans.map((a) => `<th scope="col" class="nombre">${h(a)}</th>`).join('')}</tr></thead><tbody>${cles
      .map((k) => `<tr><th scope="row">${h(noms.get(k))}</th>${fichiers.map((fd) => `<td class="nombre">${cellule(triplet(fd?.departements[code]?.[k])?.[i], f)}</td>`).join('')}</tr>`)
      .join('')}</tbody></table></div>`
  return `${tableau(1, `${nom} : montant versé dans l’année, en euros courants`, eurLisible)}${tableau(0, `${nom} : foyers (allocataires pour le minimum vieillesse)`, entier)}<p class="aide">Chaque colonne vient du fichier de l’année. « Non publié » : case absente ou incomplète à la source, jamais remplacée par 0.</p>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const [index, nat] = await Promise.all([chargerSiPresent<IndexPrestations>('prestations/index.json'), chargerSiPresent<NationalesPrestations>('prestations/nationales.json')])
  if (!index || !nat) {
    cible.innerHTML =
      enCours('Les prestations versées aux ménages', 'Allocations familiales, aides au logement, RSA, prime d’activité, minimum vieillesse, chômage, retraites : montants versés chaque année et foyers concernés.') +
      partPersonnelle()
    return
  }
  const tot = index.totaux.drees_cps
  const anRef = derniere(tot?.montant_eur, tot?.total_prestations_protection_sociale_eur)
  const drees = (id: string): Valeur => (anRef ? (nat.prestations[id]?.sources_montant.drees_cps?.[anRef] ?? null) : null)
  // Ordre affiché partout : montant de l'année de référence dans une même source, du plus élevé au plus faible.
  const prestations = index.prestations.filter((p) => nat.prestations[p.id]).sort((a, b) => (drees(b.id) ?? -1) - (drees(a.id) ?? -1))
  const ordre = prestations.map((p) => p.id)
  const annees = (nat.annees ?? index.annees).map(String)
  const montantRef = anRef ? (tot?.montant_eur[anRef] ?? null) : null
  const totalRef = anRef ? (tot?.total_prestations_protection_sociale_eur[anRef] ?? null) : null
  const part = anRef ? (tot?.part_du_total_pct?.[anRef] ?? (estNombre(montantRef) && estNombre(totalRef) ? (montantRef / totalRef) * 100 : null)) : null

  const cle =
    tot && anRef && estNombre(montantRef) && estNombre(totalRef)
      ? `<div class="carte" data-cle>
  <p class="grand-chiffre">${surligne(eurLisible(montantRef))}</p>
  <p class="sous-chiffre">versés en ${h(anRef)} par les ${h(tot.prestations.length)} prestations de cette page${estNombre(part) ? `, soit ${h(sur100(part))} sur 100 € de l’ensemble des prestations de protection sociale (${h(eurLisible(totalRef))})` : ''}. ${badgeStatut('trace')}</p>
  <p class="aide">${h(majuscule(enMots(tot.lecture)))}. Les montants publiés par la Caisse nationale des allocations familiales et par l’Unédic suivent d’autres règles de compte : ils sont donnés à part, jamais ajoutés à celui-ci.</p>
  ${citer(index, ['drees_cps'])}
</div>`
      : ''

  const barresPrestations =
    anRef && estNombre(totalRef)
      ? `<h2>Sur 100 € de prestations sociales en ${h(anRef)}</h2>
${barres(
  prestations.map((p) => {
    const v = drees(p.id)
    return {
      nom: p.nom,
      valeur: v ?? 0,
      texte: estNombre(v) ? eurLisible(v) : '',
      detail: estNombre(v) ? `${sur100((v / totalRef) * 100)} sur 100 € de prestations de protection sociale` : 'Montant non publié pour cette année.',
      statut: estNombre(v) ? ('trace' as const) : ('nonpub' as const),
    }
  }),
  undefined,
  `Prestations versées en ${anRef}, comptes de la protection sociale`,
)}
<p class="aide" data-regle-ordre>Ordre : montant versé en ${h(anRef)} dans les comptes de la protection sociale, du plus élevé au plus faible. Le même ordre est suivi plus bas.</p>
${
  estNombre(montantRef)
    ? `<p>Le reste, soit ${h(sur100(((totalRef - montantRef) / totalRef) * 100))} sur 100 € (${h(eurLisible(totalRef - montantRef))}), va aux autres prestations de protection sociale, détaillées par risque dans la vue <a href="${h(lien(PAGE_SECU, { m: 'protection2024' }))}">Protection sociale de la page Sécurité sociale</a>.</p>`
    : ''
}
${citer(index, ['drees_cps'])}`
      : ''

  // Les autres comptes publiés (caisses d'allocations familiales, assurance chômage) : donnés à part, jamais ajoutés.
  const cnaf = index.totaux.cnaf_depenses
  const anCnaf = derniere(cnaf?.montant_eur)
  const autres = [
    cnaf && anCnaf
      ? `${h(eurLisible(cnaf.montant_eur[anCnaf]!))} versés en ${h(anCnaf)} par les caisses d’allocations familiales et la Mutualité sociale agricole pour ${h(cnaf.prestations.length)} des prestations de cette page ${badgeStatut('trace')}`
      : '',
    ...prestations
      .filter((p) => p.serie_principale !== 'drees_cps' && p.serie_principale !== 'cnaf_depenses')
      .map((p) => {
        const s = nat.prestations[p.id].sources_montant[p.serie_principale]
        const a = derniere(s)
        return a ? `${h(eurLisible(s[a]!))} en ${h(a)} : ${h(serie(p.serie_principale)[1])} ${badgeStatut('trace')}` : ''
      }),
  ].filter(Boolean)

  const resume = `<div class="tableau-defile"><table><caption>Dernière année publiée pour chaque prestation : montant versé, foyers ou allocataires, montant moyen</caption>
<thead><tr><th scope="col">Prestation</th><th scope="col" class="nombre">Montant versé ${badgeStatut('trace')}</th><th scope="col" class="nombre">Foyers ou allocataires ${badgeStatut('trace')}</th><th scope="col" class="nombre">Montant moyen par foyer ${badgeStatut('approche')}</th></tr></thead>
<tbody>${prestations
    .map((p) => {
      const n = nat.prestations[p.id]
      const an = String(n.derniere_annee)
      return `<tr><th scope="row">${h(p.nom)}<br /><span class="aide">${h(an)} · ${h(serie(n.serie_principale)[0])}</span></th><td class="nombre">${cellule(n.sources_montant[n.serie_principale]?.[an], eurLisible)}</td><td class="nombre">${cellule(
        n.beneficiaires?.[an],
        entier,
      )}</td><td class="nombre">${moyenne(n.montant_moyen_eur?.[an], n)}</td></tr>`
    })
    .join('')}</tbody></table></div>`

  // Qui finance : une ligne par financeur publié, avec les blocs de ses comptes (même argent, jamais ajouté).
  const parFinanceur = new Map<string, PrestationIndex[]>()
  for (const p of prestations) parFinanceur.set(p.financeur, [...(parFinanceur.get(p.financeur) ?? []), p])
  const financement = `<div class="tableau-defile"><table><caption>Qui finance chaque prestation, et où voir cet argent dans ses comptes</caption>
<thead><tr><th scope="col">Financeur</th><th scope="col">Prestations</th><th scope="col">Dans ses comptes publiés</th></tr></thead>
<tbody>${[...parFinanceur]
    .map(([f, ps]) => {
      const vus = new Set<string>()
      const blocs = ps.flatMap((p) => p.liens.filter((l) => l.vue !== 'secu_cps')).filter((l) => !vus.has(l.fichier + l.id) && !!vus.add(l.fichier + l.id))
      return `<tr><th scope="row">${h(f)}</th><td>${h(ps.map((p) => p.nom).join(' ; '))}</td><td>${
        blocs.length ? blocs.map((l) => `${lienBloc(l)}${typeof l.md === 'number' ? ` : ${h(mdLisible(l.md))} (${h(l.millesime)}) ${badgeStatut('trace')}` : ` (${h(l.millesime)})`}`).join('<br />') : 'aucun bloc publié à relier'
      }</td></tr>`
    })
    .join('')}</tbody></table></div>`

  const deps = Object.keys(index.fichiers.departements).sort()
  const depChoisi = params.get('dep') ?? ''
  const anParam = params.get('an') ?? ''
  const anChoisi = deps.includes(anParam) ? anParam : (deps[deps.length - 1] ?? '')
  const nonCouvert = index.couverture_departementale.non_couvert.map((k) => nat.prestations[k]?.nom ?? k)
  const depInitial = nomsDepartements.has(depChoisi) && anChoisi ? await blocDepartement(index, nat, ordre, depChoisi, anChoisi) : ''

  cible.innerHTML = `
<h1>Les prestations versées aux ménages</h1>
<p class="chapeau">Chaque année, des caisses publiques versent de l’argent aux foyers : allocations familiales, aides au logement, revenu de solidarité active (RSA), prime d’activité, allocation aux adultes handicapés (AAH), minimum vieillesse, allocation chômage, pensions de retraite, indemnités journalières. Cette page montre, pour chacune, combien est versé chaque année, à combien de foyers, qui verse et qui finance, depuis ${h(annees[0] ?? '')}. Elle ne montre que des totaux publiés : aucune donnée sur une personne, et elle ne calcule pas tes droits.</p>
${cle}
<ul class="legende-statuts" aria-label="Statuts des chiffres de cette page">
  <li>${traitStatut('trace')}<span><strong>Tracé</strong> : montant ou effectif lu tel quel dans une source publiée.</span></li>
  <li>${traitStatut('approche')}<span><strong>Approché</strong> : calculé à partir de chiffres publiés, méthode écrite à côté (montant moyen par foyer).</span></li>
  <li>${traitStatut('nonpub')}<span><strong>Non publié</strong> : la source ne publie pas cette case ; elle n’est jamais remplacée par 0.</span></li>
</ul>
${barresPrestations}
${autres.length ? `<p>Autres comptes publiés, jamais ajoutés au total ci-dessus : ${autres.join(' ; ')}.</p>${cnaf ? `<p class="aide">${h(majuscule(enMots(cnaf.lecture)))}.</p>` : ''}` : ''}
<h2>Combien, pour combien de foyers</h2>
<p>Pour chaque prestation, la dernière année publiée par sa source principale. Un foyer peut recevoir plusieurs prestations : les nombres de foyers ne s’additionnent pas.</p>
${resume}
<h2>Qui verse, qui finance</h2>
<p>Celui qui verse l’argent n’est pas toujours celui qui le finance : une caisse d’allocations familiales verse aussi des prestations financées par l’État ou par le département. Le tableau relie chaque prestation à son financeur et au bloc correspondant de ses comptes publiés. Ces blocs désignent le même argent vu du côté du financeur : ils ne s’ajoutent pas aux montants versés, et un même bloc peut financer plusieurs prestations ou d’autres dépenses.</p>
${financement}
<p>Pour savoir d’où vient l’argent de chaque financeur (cotisations, contribution sociale généralisée, impôts, emprunt), voir <a href="#/explorer/recettes">D’où vient l’argent : les recettes</a> et <a href="#/explorer/dette">La dette publique</a>.</p>
<h2>Chaque prestation en détail</h2>
<p class="aide">Même ordre que plus haut. Montants en euros courants, sans correction de l’inflation.</p>
${prestations.map((p) => fiche(p, nat.prestations[p.id], index, annees)).join('\n')}
<h2>Dans ton département</h2>
<p>Les caisses d’allocations familiales publient, pour chaque département, le nombre de foyers payés et les montants versés (sans la Mutualité sociale agricole). Pour le minimum vieillesse, seul le nombre d’allocataires est publié par département. Ne sont pas publiés par département : ${h(nonCouvert.join(' ; '))}.</p>
<form id="pr-dep" class="recherche">
  <div><label for="pr-dep-choix">Département</label><select id="pr-dep-choix"><option value="">Choisir un département</option>${TOUS_DEPARTEMENTS.map(
    ([k, n]) => `<option value="${h(k)}"${k === depChoisi ? ' selected' : ''}>${h(k)} ${h(n)}</option>`,
  ).join('')}</select></div>
  <div><label for="pr-dep-an">Année</label><select id="pr-dep-an">${[...deps]
    .reverse()
    .map((a) => `<option${a === anChoisi ? ' selected' : ''}>${h(a)}</option>`)
    .join('')}</select></div>
</form>
<div id="pr-dep-resultat" aria-live="polite">${depInitial || INVITE_DEP}</div>
<h2>Ce que ces chiffres ne disent pas</h2>
<ul class="limites">
  ${index.sources_inaccessibles.map((s) => `<li>${traitStatut('nonpub')}<span><strong>${h(s.source)}</strong> : ${h(enMots(s.motif))}.</span></li>`).join('')}
  <li>${traitStatut('approche')}<span><strong>Montant moyen par foyer</strong> : une moyenne calculée à partir des montants et des foyers publiés, pas le montant reçu par un foyer donné.</span></li>
  <li>${traitStatut('trace')}<span><strong>Règle de lecture</strong> : ${h(enMots(index.regle))}.</span></li>
</ul>
<h2>Sources</h2>
<ul>${Object.values(index.sources)
    .map((s) => `<li><a href="${h(s.page ?? s.url)}" rel="noopener noreferrer">${h(s.titre)}</a> (${s.producteur ? `${h(s.producteur)}, ` : ''}${h(s.millesime)}, ${h(s.licence)})</li>`)
    .join('')}</ul>
${index.date_sources ? `<p class="aide">Sources lues le ${h(dateFr(index.date_sources))}. Fichiers publiés par le site : prestations/index.json, prestations/nationales.json et un fichier par année dans prestations/departements/.</p>` : ''}
${partPersonnelle()}`

  // Département et année : le bloc se recalcule sur place, sans recharger la page.
  const zone = cible.querySelector('#pr-dep-resultat') as HTMLElement
  const choixDep = cible.querySelector('#pr-dep-choix') as HTMLSelectElement
  const choixAn = cible.querySelector('#pr-dep-an') as HTMLSelectElement
  let jeton = 0
  const brancherEvolution = () =>
    zone.querySelectorAll<HTMLDetailsElement>('details.pr-evolution').forEach((d) =>
      d.addEventListener('toggle', async () => {
        const z = d.querySelector('.pr-evolution-zone') as HTMLElement
        if (!d.open || z.innerHTML) return
        z.innerHTML = '<p class="chargement">Chargement…</p>'
        z.innerHTML = await evolutionDepartement(index, ordre, d.dataset.code ?? '')
        appliquerLargeurs(z)
      }),
    )
  const majDepartement = async () => {
    const moi = ++jeton
    const code = choixDep.value
    const html = nomsDepartements.has(code) ? await blocDepartement(index, nat, ordre, code, choixAn.value) : INVITE_DEP
    if (moi !== jeton) return
    zone.innerHTML = html
    appliquerLargeurs(zone)
    brancherEvolution()
  }
  cible.querySelector('#pr-dep')?.addEventListener('submit', (e) => e.preventDefault())
  choixDep.addEventListener('change', majDepartement)
  choixAn.addEventListener('change', majDepartement)
  brancherEvolution()
}

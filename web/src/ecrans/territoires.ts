// Blocs « territoires » des pages département et commune (pas de route propre) : ce que l'État finance par projet
// (site/data/territoires/<dep>.json, contrat 2.25), logement social (inventaire SRU), aide sociale départementale,
// et les organismes rattachés à chaque commune : syndicats, CCAS ou CIAS, mobilité, eau
// (site/data/local_satellites/<bloc>/<dep>.json, contrat 2.37).
// Les données sont rangées par département et par commune : elles complètent les pages déjà prérendues de chaque
// département et de chaque commune plutôt qu'un écran à part, qui ne serait pas prérendu par territoire.
// Règles : aucune somme entre sources ni entre organismes (budgets non consolidés), null = non publié, jamais 0.
import { absent, barres, entier, eur, eur2, eurLisible, h, pct, source, sur100 } from '../util'

// ---------------------------------------------------------------- types (sous-ensemble des schémas utilisés ici)
type Totaux = Record<string, Record<string, { projets: number; subvention_eur: number }>>
export interface Beneficiaire {
  id: string
  type: string
  nom: string
  perimetre?: string | null
  totaux: Record<string, { projets: number; subvention_eur: number; cout_ht_eur?: number | null }>
  subvention_totale_eur: number
  projets: [number, string, string | null, number | null, number | null, number | null][]
}
interface EditionSru {
  population?: number
  lls?: number | null
  lls_texte?: string
  taux_sru?: number | null
  taux_sru_texte?: string
  taux_cible?: number
  deficitaire?: boolean | null
  carencee?: boolean
  exemptee?: boolean
  prelevement_net_eur?: number | null
  prelevement_texte?: string
}
type Mesure = { eur?: Record<string, number | null>; eur_hab?: Record<string, number | null> }
interface AideSociale {
  code: string
  nom: string
  perimetre?: string | null
  postes: Record<string, { nette?: Mesure; brute?: Mesure }>
}
export interface Territoire {
  millesime: string
  source: string
  departement: { code: string; nom: string }
  investissement_etat: {
    annees: number[]
    ordre: string
    beneficiaires: Beneficiaire[]
    par_commune: Record<string, [string, string][]>
    totaux: Totaux
    exclus_personnes_physiques_ou_non_identifies: Record<string, { projets: number; subvention_eur: number }>
    anomalies: unknown[]
  }
  sru?: { editions: { edition: number; inventaire_au: string; prelevement_annee: number | null }[]; communes: Record<string, { nom: string; editions: Record<string, EditionSru> }> }
  aide_sociale?: { collectivites: AideSociale[] }
}

type Serie = Record<string, (number | null)[]>
export interface Syndicat {
  nom: string | null
  nature: string | null
  categorie: string
  population: number | null
  membres: number | null
  comptes: boolean
  budgets: number | null
  serie: Serie | null
  eur_hab: number | null
  eur_hab_exercice: number | null
}
export interface FichierSyndicats {
  source: string
  millesime: string
  annees: number[]
  syndicats: Record<string, Syndicat>
  organismes_departementaux: string[]
  communes: Record<string, [string, string][]>
}
export interface FichierCcas {
  source: string
  millesime: string
  annees: number[]
  centres: Record<string, { nom: string | null; type: string; commune_siege: string | null; population: number | null; budgets: number | null; serie: Serie | null; eur_hab: number | null; eur_hab_exercice: number | null }>
  communes: Record<string, string[]>
}
export interface FichierMobilite {
  source: string
  millesime: string
  mention: string
  licence: string
  date_reference: string
  aom: Record<string, { nom: string | null; forme: string | null; population: number | null; communes: number | null }>
  communes: Record<string, [string | null, number | null, number | null, number | null, string | null, string | null, unknown]>
}
type Service = [string, string | null, string | null, string | null, string[] | null, number | null, number | null, string | null, number | null]
export interface FichierEau {
  source: string
  millesime: string
  exercice: number
  collectivites: Record<string, { nom: string | null; type: string | null; services: string[] }>
  services: Record<string, Service>
  communes: Record<string, [string, string][]>
}

// ---------------------------------------------------------------- libellés (jamais de sigle seul)
export const DISPOSITIFS: Record<string, string> = {
  DETR: 'Dotation d’équipement des territoires ruraux (DETR)',
  DSIL: 'Dotation de soutien à l’investissement local (DSIL)',
  'DSIL Exceptionnelle': 'Dotation de soutien à l’investissement local, part exceptionnelle (DSIL exceptionnelle)',
  'DSIL RT': 'Dotation de soutien à l’investissement local, rénovation thermique (DSIL RT)',
  DPV: 'Dotation politique de la ville (DPV)',
  DSID: 'Dotation de soutien à l’investissement des départements (DSID)',
  'DSID RT': 'Dotation de soutien à l’investissement des départements, rénovation thermique (DSID RT)',
}
const dispositif = (d: string) => DISPOSITIFS[d] ?? d
const NATURES: Record<string, string> = {
  SIVU: 'Syndicat intercommunal à vocation unique',
  SIVOM: 'Syndicat intercommunal à vocation multiple',
  SMF: 'Syndicat mixte fermé',
  SMO: 'Syndicat mixte ouvert',
  PETR: 'Pôle d’équilibre territorial et rural',
  POLEM: 'Pôle métropolitain',
}
const CATEGORIES: Record<string, string> = {
  mdph: 'Maison départementale des personnes handicapées',
  petr: 'Pôle d’équilibre territorial et rural',
  pole_metropolitain: 'Pôle métropolitain',
  syndicat: 'Syndicat',
}
const VIA: Record<string, string> = {
  commune: 'la commune est membre',
  epci: 'par l’intercommunalité',
  syndicat: 'par un autre syndicat',
}
const VIA_EAU: Record<string, string> = {
  commune: 'la commune',
  epci: 'l’intercommunalité',
  syndicat_via_commune: 'syndicat dont la commune est membre',
  syndicat_via_epci: 'syndicat dont l’intercommunalité est membre',
}
const COMPETENCES_EAU: Record<string, string> = {
  eau_potable: 'Eau potable',
  assainissement_collectif: 'Assainissement collectif',
  assainissement_non_collectif: 'Assainissement non collectif',
}
const POSTES: [string, string][] = [
  ['personnes_agees', 'Personnes âgées (dont allocation personnalisée d’autonomie)'],
  ['personnes_handicapees', 'Personnes handicapées (dont prestation de compensation du handicap)'],
  ['ase', 'Aide sociale à l’enfance'],
  ['rsa_insertion', 'Revenu de solidarité active (RSA) et insertion'],
  ['autres', 'Autres dépenses (frais communs, personnel)'],
]
const nomOrganisme = (nom: string | null) => nom ?? 'Organisme non nommé (catégorie juridique hors personne morale)'
const nf = (x: number | null | undefined, f: (v: number) => string) => (typeof x === 'number' ? h(f(x)) : 'non publié')

/** Dernier exercice publié d'une série : [année, valeur] ou null. */
function dernier(serie: Serie | null, cle: string, annees: number[]): [number, number] | null {
  const v = serie?.[cle]
  if (!v) return null
  for (let i = v.length - 1; i >= 0; i--) if (typeof v[i] === 'number') return [annees[i], v[i] as number]
  return null
}
const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
/** « 2026-01-01 » devient « 1er janvier 2026 ». */
export function dateFr(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m) return iso
  const j = Number(m[3])
  return `${j === 1 ? '1er' : j} ${MOIS[Number(m[2]) - 1]} ${m[1]}`
}
const annexes = (b: number | null) => (b && b > 1 ? `budget principal et ${b - 1} budget${b > 2 ? 's' : ''} annexe${b > 2 ? 's' : ''}` : '')

// ---------------------------------------------------------------- projets financés par l'État (programme 119)

/** Tableau par exercice et dispositif des subventions attribuées dans le département (montants d'une même source). */
export function blocInvestissementDepartement(t: Territoire): string {
  const ie = t.investissement_etat
  const annees = Object.keys(ie.totaux).sort().reverse()
  if (!annees.length) return absent('Aucun projet publié pour ce département.')
  const disp = [...new Set(annees.flatMap((a) => Object.keys(ie.totaux[a]).filter((d) => d !== 'non_nommes')))].sort()
  const cellule = (x?: { projets: number; subvention_eur: number }) =>
    x ? `${h(eurLisible(x.subvention_eur))}<br><span class="aide">${h(entier(x.projets))} projet${x.projets > 1 ? 's' : ''}</span>` : '–'
  const top = ie.beneficiaires.slice(0, 10)
  const exclus = Object.entries(ie.exclus_personnes_physiques_ou_non_identifies ?? {}).sort()
  return `<p>Subventions attribuées par l’État (programme 119 du budget de l’État) aux projets d’investissement des communes, intercommunalités, départements et syndicats : montants décidés, pas les paiements.</p>
<div class="tableau-defile"><table><caption>Subventions attribuées par exercice et par dotation, ${h(t.departement.nom)}</caption><thead><tr><th scope="col">Exercice</th>${disp
    .map((d) => `<th scope="col" class="nombre">${h(dispositif(d))}</th>`)
    .join('')}<th scope="col" class="nombre">Bénéficiaires non nommés</th></tr></thead><tbody>${annees
    .map((a) => `<tr><th scope="row">${h(a)}</th>${disp.map((d) => `<td class="nombre">${cellule(ie.totaux[a][d])}</td>`).join('')}<td class="nombre">${cellule(ie.totaux[a].non_nommes)}</td></tr>`)
    .join('')}</tbody></table></div>
<h3>Les dix bénéficiaires aux subventions les plus élevées, ${h(ie.annees[0])} à ${h(ie.annees[ie.annees.length - 1])}</h3>
<p class="aide">Ordre : subvention totale décroissante. Sur ${h(entier(ie.beneficiaires.length))} bénéficiaires nommés (collectivités et personnes morales).</p>
<ol>${top
    .map((b) => {
      const n = Object.values(b.totaux).reduce((s, x) => s + x.projets, 0)
      return `<li>${h(b.nom)} : ${h(eurLisible(b.subvention_totale_eur))} pour ${h(entier(n))} projet${n > 1 ? 's' : ''}${b.perimetre ? ` <span class="aide">(${h(b.perimetre)})</span>` : ''}</li>`
    })
    .join('')}</ol>
${
  exclus.length
    ? `<p class="aide">Projets dont le bénéficiaire n’est pas une personne morale identifiée : agrégés sans nom ni intitulé (${exclus
        .map(([a, x]) => `${h(a)} : ${h(entier(x.projets))} projet${x.projets > 1 ? 's' : ''}, ${h(eurLisible(x.subvention_eur))}`)
        .join(' ; ')}).</p>`
    : ''
}${ie.anomalies?.length ? `<p class="aide">${h(entier(ie.anomalies.length))} projet${ie.anomalies.length > 1 ? 's' : ''} dont la subvention publiée dépasse le coût hors taxes publié : repris tels quels.</p>` : ''}
${source('Direction générale des collectivités locales, projets financés par les dotations de soutien à l’investissement', t.millesime)}`
}

/** Projets de la commune et de son intercommunalité (bénéficiaires listés par par_commune). */
export function blocInvestissementCommune(beneficiaires: Beneficiaire[], t: Territoire): string {
  if (!beneficiaires.length) return '<p>Aucun projet de la commune ni de son intercommunalité dans les listes publiées de 2018 à 2025.</p>'
  return `<p>Subventions de l’État (programme 119) attribuées aux projets de la commune et des collectivités dont elle fait partie. Chaque collectivité a son propre budget : ne pas additionner les lignes.</p>
${beneficiaires
  .map((b) => {
    const annees = Object.keys(b.totaux).sort().reverse()
    const derniers = b.projets.slice(0, 3)
    return `<h3>${h(b.nom)}</h3>
<div class="tableau-defile"><table><caption>Subventions attribuées à ${h(b.nom)}, par exercice</caption><thead><tr><th scope="col">Exercice</th><th scope="col" class="nombre">Projets</th><th scope="col" class="nombre">Subventions attribuées</th></tr></thead><tbody>${annees
      .map((a) => `<tr><th scope="row">${h(a)}</th><td class="nombre">${h(entier(b.totaux[a].projets))}</td><td class="nombre">${h(eur(b.totaux[a].subvention_eur))}</td></tr>`)
      .join('')}</tbody></table></div>
${
  derniers.length
    ? `<ul>${derniers
        .map(
          ([a, d, intitule, cout, sub]) =>
            `<li>${h(a)}, ${h(dispositif(d))} : ${intitule ? `« ${h(intitule)} »` : 'intitulé non repris'}, ${nf(sub, eurLisible)} de subvention${typeof cout === 'number' ? ` pour ${h(eurLisible(cout))} de coût hors taxes` : ''}.</li>`,
        )
        .join('')}</ul>`
    : ''
}`
  })
  .join('')}
${source('Direction générale des collectivités locales, projets financés par les dotations de soutien à l’investissement', t.millesime)}`
}

// ---------------------------------------------------------------- logement social (loi SRU)

const statutSru = (e: EditionSru) =>
  [e.exemptee ? 'exemptée' : '', e.carencee ? 'carencée (arrêté de carence)' : '', e.deficitaire === true ? 'déficitaire (taux sous l’objectif)' : e.deficitaire === false ? 'non déficitaire' : ''].filter(Boolean).join(', ') ||
  'non publié'
const tauxSru = (e: EditionSru) => (typeof e.taux_sru === 'number' ? h(pct(e.taux_sru, 2)) : e.taux_sru_texte ? `« ${h(e.taux_sru_texte)} »` : 'non publié')
const prelevement = (e: EditionSru) =>
  typeof e.prelevement_net_eur === 'number'
    ? `${h(eur(e.prelevement_net_eur))}${e.prelevement_texte ? ` <span class="aide">(publié « ${h(e.prelevement_texte)} »)</span>` : ''}`
    : e.prelevement_texte
      ? `« ${h(e.prelevement_texte)} »`
      : 'non publié'

const INTRO_SRU =
  'La loi relative à la solidarité et au renouvellement urbains (SRU) fixe aux communes concernées une part de logements locatifs sociaux parmi leurs résidences principales (objectif de 20 ou 25 %). Une commune sous l’objectif peut faire l’objet d’un prélèvement sur ses ressources.'

export function blocSruCommune(c: { nom: string; editions: Record<string, EditionSru> } | undefined, t: Territoire): string {
  if (!t.sru) return absent('Inventaire non publié pour ce département.')
  if (!c) return `<p>La commune ne figure dans aucune édition de l’inventaire de 2023 à 2026 : seules les communes soumises au dispositif ou qui y entrent y figurent.</p>`
  const eds = Object.keys(c.editions).sort().reverse()
  return `<p>${h(INTRO_SRU)}</p>
<div class="tableau-defile"><table><caption>Inventaire des logements sociaux, ${h(c.nom)}</caption><thead><tr><th scope="col">Édition</th><th scope="col" class="nombre">Logements sociaux</th><th scope="col" class="nombre">Taux</th><th scope="col" class="nombre">Objectif</th><th scope="col">Statut publié</th><th scope="col" class="nombre">Prélèvement net</th></tr></thead><tbody>${eds
    .map((a) => {
      const e = c.editions[a]
      return `<tr><th scope="row">${h(a)}</th><td class="nombre">${typeof e.lls === 'number' ? h(entier(e.lls)) : e.lls_texte ? `« ${h(e.lls_texte)} »` : 'non publié'}</td><td class="nombre">${tauxSru(e)}</td><td class="nombre">${typeof e.taux_cible === 'number' ? h(pct(e.taux_cible, 0)) : 'non publié'}</td><td>${h(statutSru(e))}</td><td class="nombre">${prelevement(e)}</td></tr>`
    })
    .join('')}</tbody></table></div>
<p class="aide">Édition N : inventaire au 1er janvier N-1, prélèvement de l’année N. Une valeur entre guillemets est reprise telle que publiée.</p>
${source('Ministère chargé du logement, inventaire des communes soumises à la loi SRU', t.millesime)}`
}

export function blocSruDepartement(t: Territoire): string {
  const s = t.sru
  if (!s || !Object.keys(s.communes).length) return '<p>Aucune commune du département dans l’inventaire publié de 2023 à 2026.</p>'
  const ed = String(Math.max(...s.editions.map((e) => e.edition)))
  const lignes = Object.entries(s.communes)
    .filter(([, c]) => c.editions[ed])
    .sort((a, b) => a[1].nom.localeCompare(b[1].nom, 'fr'))
  const deficitaires = lignes.filter(([, c]) => c.editions[ed].deficitaire === true).length
  const carencees = lignes.filter(([, c]) => c.editions[ed].carencee).length
  return `<p>${h(INTRO_SRU)}</p>
<p>Édition ${h(ed)} : ${h(entier(lignes.length))} commune${lignes.length > 1 ? 's' : ''} dans l’inventaire, dont ${h(entier(deficitaires))} déficitaire${deficitaires > 1 ? 's' : ''} et ${h(entier(carencees))} carencée${carencees > 1 ? 's' : ''}.</p>
${
  lignes.length
    ? `<div class="tableau-defile"><table><caption>Communes de l’inventaire, édition ${h(ed)} (ordre alphabétique)</caption><thead><tr><th scope="col">Commune</th><th scope="col" class="nombre">Taux</th><th scope="col" class="nombre">Objectif</th><th scope="col">Statut publié</th><th scope="col" class="nombre">Prélèvement net</th></tr></thead><tbody>${lignes
        .map(([, c]) => {
          const e = c.editions[ed]
          return `<tr><th scope="row">${h(c.nom)}</th><td class="nombre">${tauxSru(e)}</td><td class="nombre">${typeof e.taux_cible === 'number' ? h(pct(e.taux_cible, 0)) : 'non publié'}</td><td>${h(statutSru(e))}</td><td class="nombre">${prelevement(e)}</td></tr>`
        })
        .join('')}</tbody></table></div>`
    : ''
}
${source('Ministère chargé du logement, inventaire des communes soumises à la loi SRU', t.millesime)}`
}

// ---------------------------------------------------------------- aide sociale départementale (DREES)

export function blocAideSociale(t: Territoire): string {
  const cols = t.aide_sociale?.collectivites ?? []
  if (!cols.length) return absent('Aide sociale non publiée pour ce département.')
  return `<p>Dépenses nettes d’aide sociale (après récupérations et recouvrements) publiées par la direction de la recherche, des études, de l’évaluation et des statistiques (DREES). Elles comprennent la part prise en charge par l’État (par la Caisse nationale de solidarité pour l’autonomie, le fonds de mobilisation départementale pour l’insertion et une part de la taxe intérieure sur les produits énergétiques).</p>
${cols
  .map((c) => {
    const tot = c.postes.total?.nette
    const an = Object.keys(tot?.eur ?? {})
      .filter((a) => typeof tot?.eur?.[a] === 'number')
      .sort()
      .pop()
    if (!tot || !an) return `<h3>${h(c.nom)}</h3>${absent()}`
    const total = tot.eur![an] as number
    const parHab = tot.eur_hab?.[an]
    const lignes = POSTES.map(([k, n]) => ({ n, v: c.postes[k]?.nette?.eur?.[an] })).filter((x): x is { n: string; v: number } => typeof x.v === 'number')
    return `<h3>${h(c.nom)}</h3>
${c.perimetre ? `<p class="aide">Périmètre : ${h(c.perimetre)}.</p>` : ''}
<p><strong>${h(eurLisible(total))}</strong> de dépenses nettes en ${h(an)}${typeof parHab === 'number' ? `, soit ${h(eur(parHab))} par habitant` : ''}. Sur 100 € :</p>
${barres(
  lignes.map((x) => ({ nom: x.n, valeur: x.v, texte: total > 0 ? sur100((x.v / total) * 100) : '–', detail: eurLisible(x.v) })),
  undefined,
  `Aide sociale de ${c.nom} en ${an}, sur 100 €`,
  -1,
)}`
  })
  .join('')}
<p class="aide">Ne pas additionner ce montant au budget du département affiché plus haut : il en fait partie. Alsace, Corse et Rhône : la collectivité qui exerce les compétences départementales est indiquée avec son périmètre.</p>
${source('DREES, enquête Aide sociale (séries longues)', t.millesime)}`
}

// ---------------------------------------------------------------- organismes rattachés (local_satellites)

function ligneSyndicat(s: Syndicat, annees: number[], anRef: number | null, via?: string): string {
  const d = dernier(s.serie, 'depenses_totales_hors_remb', annees)
  const type = s.nature ? NATURES[s.nature] ?? s.nature : CATEGORIES[s.categorie] ?? s.categorie
  const budgets = annexes(s.budgets)
  return `<tr><th scope="row">${h(nomOrganisme(s.nom))}${budgets ? `<br><span class="aide">${h(budgets)}</span>` : ''}</th><td>${h(type)}</td>${via !== undefined ? `<td>${h(VIA[via] ?? via)}</td>` : ''}<td class="nombre">${
    d ? `${h(eurLisible(d[1]))}${d[0] !== anRef ? `<br><span class="aide">${h(d[0])}</span>` : ''}` : s.comptes ? 'non publié' : 'comptes non publiés'
  }</td><td class="nombre">${typeof s.eur_hab === 'number' ? h(eur2(s.eur_hab)) : 'non publié'}</td></tr>`
}
/** Exercice le plus fréquent parmi les derniers exercices publiés (l'année n'est répétée par ligne que s'il diffère). */
function anCommun(liste: Syndicat[], annees: number[]): number | null {
  const n = new Map<number, number>()
  for (const s of liste) {
    const d = dernier(s.serie, 'depenses_totales_hors_remb', annees)
    if (d) n.set(d[0], (n.get(d[0]) ?? 0) + 1)
  }
  return [...n.entries()].sort((a, b) => b[1] - a[1] || b[0] - a[0])[0]?.[0] ?? null
}
const legende = (titre: string, an: number | null) => `${titre}, ${an ? `exercice ${an} (autre exercice indiqué sous le montant)` : 'dernier exercice publié'}`
const enteteSyndicats = (caption: string, avecVia: boolean) =>
  `<div class="tableau-defile"><table><caption>${h(caption)}</caption><thead><tr><th scope="col">Organisme</th><th scope="col">Type</th>${
    avecVia ? '<th scope="col">Rattachement</th>' : ''
  }<th scope="col" class="nombre">Dépenses (hors remboursements d’emprunts)</th><th scope="col" class="nombre">Par habitant du périmètre</th></tr></thead><tbody>`

const PAS_DE_DOUBLE_COMPTE =
  'Chaque organisme a son propre budget, financé en partie par les contributions des communes et intercommunalités membres, déjà comptées dans leurs dépenses : ne pas additionner ces montants entre eux ni au budget de la commune.'

export function blocOrganismesCommune(
  insee: string,
  syn: FichierSyndicats | null,
  ccas: FichierCcas | null,
  mob: FichierMobilite | null,
  eau: FichierEau | null,
): string {
  const parties: string[] = []
  // Syndicats
  const liste = syn?.communes[insee] ?? []
  if (syn && liste.length) {
    const rang: Record<string, number> = { commune: 0, epci: 1, syndicat: 2 }
    const depense = (s: string) => dernier(syn.syndicats[s]?.serie ?? null, 'depenses_totales_hors_remb', syn.annees)?.[1] ?? -1
    const an = anCommun(liste.map(([s]) => syn.syndicats[s]).filter(Boolean), syn.annees)
    const tri = [...liste].filter(([s]) => syn.syndicats[s]).sort((a, b) => (rang[a[1]] ?? 9) - (rang[b[1]] ?? 9) || depense(b[0]) - depense(a[0]) || a[0].localeCompare(b[0]))
    parties.push(`<h3>Les syndicats</h3>
<p>${h(entier(tri.length))} syndicat${tri.length > 1 ? 's' : ''} ou pôle${tri.length > 1 ? 's' : ''} dont la commune fait partie, directement ou par son intercommunalité. Ordre : rattachement direct d’abord, puis dépenses décroissantes.</p>
${enteteSyndicats(legende('Syndicats rattachés à la commune', an), true)}${tri.map(([s, via]) => ligneSyndicat(syn.syndicats[s], syn.annees, an, via)).join('')}</tbody></table></div>
<p class="aide">Une intercommunalité peut n’adhérer à un syndicat que pour une partie de ses communes : une commune rattachée par son intercommunalité peut ne pas être desservie.</p>
${source('Observatoire des finances et de la gestion publique locales (OFGL), comptes des syndicats ; périmètres BANATIC', syn.millesime)}`)
  }
  // CCAS et CIAS
  const centres = (ccas?.communes[insee] ?? []).filter((s) => ccas?.centres[s])
  if (ccas && centres.length) {
    parties.push(`<h3>L’action sociale : centre communal ou intercommunal</h3>
<ul>${centres
      .map((s) => {
        const c = ccas.centres[s]
        const d = dernier(c.serie, 'depenses_totales_hors_remb', ccas.annees)
        const i = d ? ccas.annees.indexOf(d[0]) : -1
        const part = i >= 0 ? c.serie?.participations_communes?.[i] : null
        const type = c.type === 'cias' ? 'Centre intercommunal d’action sociale' : 'Centre communal d’action sociale'
        return `<li>${h(nomOrganisme(c.nom))} (${h(type)}) : ${
          d ? `${h(eurLisible(d[1]))} de dépenses en ${h(d[0])}${typeof c.eur_hab === 'number' ? `, soit ${h(eur2(c.eur_hab))} par habitant` : ''}${typeof part === 'number' ? ` ; ${h(eurLisible(part))} reçus des communes (participations, déjà comptées dans leurs dépenses)` : ''}` : 'comptes non publiés'
        }${annexes(c.budgets) ? ` ; ${h(annexes(c.budgets))}` : ''}.</li>`
      })
      .join('')}</ul>
${source('OFGL, comptes des centres communaux et intercommunaux d’action sociale ; commune du siège dans SIRENE', ccas.millesime)}`)
  }
  // Mobilité
  const m = mob?.communes[insee]
  if (mob && m) {
    const aom = m[0] ? mob.aom[m[0]] : null
    const taux: string[] = []
    if (typeof m[1] === 'number') taux.push(`versement mobilité : ${pct(m[1], 2)}`)
    if (typeof m[2] === 'number') taux.push(`versement additionnel d’un syndicat mixte de transport : ${pct(m[2], 2)}`)
    if (typeof m[3] === 'number') taux.push(`versement mobilité régional et rural : ${pct(m[3], 2)}`)
    parties.push(`<h3>Les transports : autorité organisatrice de la mobilité</h3>
<p>${aom ? `${h(nomOrganisme(aom.nom))}${aom.forme ? ` (${h(aom.forme === 'CC' ? 'communauté de communes' : aom.forme === 'CA' ? 'communauté d’agglomération' : aom.forme === 'CU' ? 'communauté urbaine' : aom.forme)})` : ''} organise les transports publics de la commune.` : 'Aucune autorité organisatrice publiée pour la commune dans la base du Cerema.'}</p>
<p>${
      taux.length
        ? `Taux en vigueur au ${h(dateFr(mob.date_reference))}, en pourcentage de la masse salariale, versés par les employeurs de 11 salariés et plus : ${h(taux.join(' ; '))}.`
        : 'Aucun taux de versement mobilité en vigueur publié pour la commune.'
    }</p>
${source(`${mob.mention} Licence ${mob.licence}`, mob.millesime)}`)
  }
  // Eau et assainissement
  const orgs = (eau?.communes[insee] ?? []).filter(([s]) => eau?.collectivites[s])
  if (eau && orgs.length) {
    const lignes: string[] = []
    for (const [s, via] of orgs) {
      const col = eau.collectivites[s]
      const services = col.services.map((id) => eau.services[id]).filter(Boolean)
      for (const comp of Object.keys(COMPETENCES_EAU)) {
        const sv = services.filter((x) => x[0] === comp)
        if (!sv.length) continue
        const prix = sv.map((x) => x[6]).filter((x): x is number => typeof x === 'number')
        let detail: string
        if (sv.length === 1) {
          const x = sv[0]
          detail = `${h(x[2] ?? 'mode de gestion non publié')}${x[3] ? `, ${h(x[3].toLowerCase())}` : ''}`
        } else detail = `${h(entier(sv.length))} entités de gestion`
        const p = comp === 'assainissement_non_collectif' ? 'sans objet' : !prix.length ? 'non publié' : prix.length === 1 && sv.length === 1 ? h(eur2(prix[0])) : `de ${h(eur2(Math.min(...prix)))} à ${h(eur2(Math.max(...prix)))}`
        lignes.push(`<tr><th scope="row">${h(COMPETENCES_EAU[comp])}</th><td>${h(nomOrganisme(col.nom))}<br><span class="aide">${h(VIA_EAU[via] ?? via)}</span></td><td>${detail}</td><td class="nombre">${p}</td></tr>`)
      }
    }
    if (lignes.length)
      parties.push(`<h3>L’eau et l’assainissement</h3>
<p>Services financés par les factures d’eau des abonnés (budget annexe), et non par les impôts locaux.</p>
<div class="tableau-defile"><table><caption>Services d’eau et d’assainissement, exercice ${h(eau.exercice)}</caption><thead><tr><th scope="col">Service</th><th scope="col">Collectivité organisatrice</th><th scope="col">Gestion</th><th scope="col" class="nombre">Prix toutes taxes comprises par m³ (120 m³)</th></tr></thead><tbody>${lignes.join('')}</tbody></table></div>
<p class="aide">Une collectivité peut avoir plusieurs entités de gestion sur son territoire : le prix applicable à la commune n’est alors pas désigné, l’écart entre les prix publiés est montré.</p>
${source('Observatoire des services publics d’eau et d’assainissement (SISPEA, Office français de la biodiversité) ; périmètres BANATIC', eau.millesime)}`)
  }
  if (!parties.length) return absent('Aucun organisme rattaché publié pour cette commune.')
  return `<p>${h(PAS_DE_DOUBLE_COMPTE)}</p>${parties.join('\n')}`
}

/** Organismes départementaux (maison départementale des personnes handicapées) et principaux syndicats du département. */
export function blocOrganismesDepartement(syn: FichierSyndicats | null, ccas: FichierCcas | null): string {
  if (!syn) return absent('Syndicats non publiés pour ce département.')
  const deps = syn.organismes_departementaux.filter((s) => syn.syndicats[s])
  const depense = (s: string) => dernier(syn.syndicats[s].serie, 'depenses_totales_hors_remb', syn.annees)?.[1] ?? -1
  const autres = Object.keys(syn.syndicats)
    .filter((s) => !deps.includes(s) && syn.syndicats[s].categorie !== 'mdph')
    .sort((a, b) => depense(b) - depense(a) || a.localeCompare(b))
  const anD = anCommun(deps.map((s) => syn.syndicats[s]), syn.annees)
  const anA = anCommun(autres.slice(0, 10).map((s) => syn.syndicats[s]), syn.annees)
  const nbCcas = ccas ? Object.keys(ccas.centres).length : 0
  return `<p>${h(PAS_DE_DOUBLE_COMPTE)}</p>
${deps.length ? `${enteteSyndicats(legende('Organismes départementaux', anD), false)}${deps.map((s) => ligneSyndicat(syn.syndicats[s], syn.annees, anD)).join('')}</tbody></table></div>` : ''}
<p>${h(entier(autres.length))} syndicat${autres.length > 1 ? 's' : ''} et pôle${autres.length > 1 ? 's' : ''} publiés dans le département${nbCcas ? `, et ${h(entier(nbCcas))} centre${nbCcas > 1 ? 's' : ''} communaux ou intercommunaux d’action sociale` : ''}. Le détail par commune est sur chaque page commune.</p>
${
  autres.length
    ? `${enteteSyndicats(legende('Les dix syndicats aux dépenses les plus élevées (ordre : dépenses décroissantes)', anA), false)}${autres
        .slice(0, 10)
        .map((s) => ligneSyndicat(syn.syndicats[s], syn.annees, anA))
        .join('')}</tbody></table></div>`
    : ''
}
${source('OFGL, comptes des syndicats et des centres d’action sociale ; périmètres BANATIC', syn.millesime)}`
}

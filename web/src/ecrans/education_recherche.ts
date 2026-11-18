// Éducation et recherche : qui dépense pour chaque niveau d'enseignement et pour la recherche (comptes publics
// d'Eurostat par fonction), budgets des collectivités pour l'enseignement supérieur et la recherche, montant par
// étudiant (calcul du site, toujours signalé comme tel), montants par élève publiés par l'État, compte de l'éducation
// (part des familles et des entreprises, dépense moyenne par élève et par niveau), lycées de trois régions et projets
// de l'Agence nationale de la recherche (site/data/education_recherche/). Une absence publiée (null) s'affiche
// « non publié », jamais 0.
// Deux sources ne sont jamais additionnées. Seuls les organismes que le pipeline a classés personnes morales sont
// nommés ; les autres restent agrégés. Aucune année n'est écrite ici : elles sont lues dans les fichiers.
import { partPersonnelle } from '../composants/hub'
import { chargerSiPresent } from '../donnees'
import { TOUS_DEPARTEMENTS } from '../departements'
import type { Rendu } from '../routeur'
import { lien } from '../routeur'
import { absent, appliquerLargeurs, badgeStatut, barres, entier, eur, eurLisible, h, legendeStatuts, libelle, md, pct, source, sur100, surligne, traitStatut } from '../util'
import { enCours } from './dette'

// ---------- Formats des fichiers lus (seuls les champs utilisés) ----------
interface NoeudAdm {
  id: string
  nom: string
  md: number
  enfants?: NoeudAdm[]
}
interface ArbreAdm extends NoeudAdm {
  millesime: string
  source: string
}
interface Cofog {
  millesime: string
  source: string
  annee: string
  fonctions: { code: string; nom: string; md: number }[]
  total: number
}
interface SourceEr {
  titre: string
  producteur: string
  page: string
  licence: string
  millesime: string
}
interface Ecart {
  objet: string
  source: string
  montant: number | null
  autre_source: string
  autre_montant: number | null
  ecart: number | null
  ecart_pct: number | null
  lecture: string
}
interface PointCout {
  annee: number
  qualite_budget: string
  budget_esve_eur: number | null
  etudiants: number | null
  cout_par_etudiant_eur: number | null
}
interface TotalLycees {
  region: string
  annees: number[]
  total_eur: number | null
  nommes: { nombre: number; montant_eur: number | null }
  non_nommes: { nombre: number; montant_eur: number | null; part_pct: number | null }
  nature_des_montants: string
  fichier: string
}
interface Index {
  millesime: string
  source: string
  sources: SourceEr[]
  fichiers?: { compte_education?: string }
  licences?: { note?: string; odbl?: { producteur: string; url_licence: string }[] }
  totaux: {
    anr_pia_france2030?: { projets: number; aide_eur: number | null; participations: number }
    anr_2005_2009?: { projets: number; aide_projets_eur: number | null; participations: number; aide_partenaires_eur: number | null }
    lycees?: Record<string, TotalLycees>
    etudiants?: { annee: number; annee_universitaire: string; etudiants_hors_cpge: number }
  }
  cout_par_etudiant?: { statut: string; formule: string; national: PointCout[] }
  ecarts?: Ecart[]
  limites?: string[]
  sources_inaccessibles?: { source: string; motif: string }[]
}
interface CollectivitesEsr {
  millesime: string
  source: string
  annees: number[]
  categories: Record<string, string>
  types_collectivite: Record<string, string>
  national: { annee: number; qualite: string; total_eur: number | null; rt_eur: number | null; esve_eur: number | null; par_type: Record<string, number | null> }[]
  regions: { code: string; nom: string; esve_eur: (number | null)[] }[]
  note?: string
}
interface Etudiants {
  source: string
  cout_par_etudiant?: {
    statut: string
    producteur?: string
    perimetre?: string
    limites?: string[]
    regions?: { code: string; nom: string; valeurs: PointCout[] }[]
  }
}
interface BlocAnrProjets {
  millesime: string
  source: string
  note?: string
  par_annee: { annee: number; projets: number; aide_eur?: number | null; aide_projets_eur?: number | null; aide_partenaires_eur?: number | null }[]
}
interface AnrProjets {
  pia_france2030?: BlocAnrProjets
  anr_2005_2009?: BlocAnrProjets
}
type Ligne = (string | number | boolean | string[] | null)[]
interface BlocAnrEtab {
  millesime: string
  source: string
  lecture: string
  colonnes: string[]
  etablissements: Ligne[]
  ordre?: { regle: string }
  nommes: { nombre: number; participations: number }
  non_nommes: {
    organismes: number
    participations: number
    motifs?: Record<string, number>
    par_categorie: { categorie: string; organismes: number; participations: number; aide_projets_coordonnes_eur?: number | null; aide_allouee_eur?: number | null }[]
  }
  total: Record<string, number | null>
}
interface AnrEtab {
  pia_france2030?: BlocAnrEtab
  anr_2005_2009?: BlocAnrEtab
}
interface Lycees {
  millesime: string
  source: string
  licence: string
  region: { code: string; nom: string }
  nature_des_montants: string
  annees: number[]
  colonnes: string[]
  etablissements: Ligne[]
  ordre?: { regle: string }
  nommes: { nombre: number; montant_eur: number | null }
  non_nommes: { nombre: number; montant_eur: number | null; motifs?: Record<string, { nombre: number; montant_eur: number | null }> }
  par_annee: { annee: number; total_eur: number | null; beneficiaires: number; lignes: number; lignes_montant_zero: number }[]
  par_dispositif: { dispositif: string; total_eur: number | null }[]
  total_eur: number | null
  controles?: { annee: number; somme_des_dotations_eur: number | null; total_publie_eur: number | null; ecart_eur: number | null; lignes_total_absent?: number }[]
}
interface Indicateur {
  id: string
  indicateur: string
  sous_indicateur?: string | null
  unite?: string | null
  valeurs: { annee: number; valeur: number | null; source: string }[]
}
interface Realisations {
  programme: string
  libelle: string
  source: string
  resultats_mesures?: { indicateurs?: Indicateur[] }
}
/** Compte de l'éducation (DEPP), tableur de l'Insee : valeurs publiées, sans calcul du site. */
interface CompteEducation {
  millesime: string
  source: string
  licence: string
  producteur: string
  annees_provisoires: number[]
  financement_initial: {
    annees: number[]
    provisoire: boolean[]
    financeurs: { id: string; libelle: string; parent: string | null; part_pct: (number | null)[] }[]
    familles_et_entreprises: { annee: number; provisoire: boolean; menages_pct: number | null; entreprises_pct: number | null; lecture: string }
    lecture: string
  }
  die: { annees: number[]; provisoire: boolean[]; die_md_eur_courants: (number | null)[]; depense_moyenne_eur_courants: (number | null)[]; lecture: string }
  die_serie: { annees: number[]; part_pib_pct: (number | null)[]; die_md_eur_constants: (number | null)[]; prix_constants: string }
  depense_moyenne_par_niveau: {
    annee: number
    provisoire: boolean
    niveaux: { degre: string; libelle_degre: string; niveau: string; ensemble_du_degre: boolean; depense_moyenne_eur: number | null }[]
    lecture: string
  }
  depense_moyenne_evolution: {
    annees: number[]
    provisoire: boolean[]
    prix_constants: string
    series: { id: string; libelle_source: string; eur_constants: (number | null)[] }[]
  }
}

// ---------- Libellés en langage courant ----------
/** Niveaux d'enseignement de la classification des fonctions des administrations (Eurostat), dits simplement. */
const NIVEAUX: Record<string, string> = {
  GF0901: 'École maternelle et élémentaire',
  GF0902: 'Collège et lycée',
  GF0903: 'Après le bac, hors enseignement supérieur',
  GF0904: 'Enseignement supérieur',
  GF0905: 'Enseignement sans niveau défini',
  GF0906: 'Transport, restauration et hébergement des élèves',
  GF0908: 'Autres dépenses d’enseignement',
}
/** Sigles présents dans des libellés publiés tels quels : expliqués à côté, jamais laissés seuls. */
const SIGLES: Record<string, string> = {
  DGF: 'dotation globale de fonctionnement',
  EPLE: 'établissement public local d’enseignement (lycée public)',
  EPS: 'éducation physique et sportive',
  INSA: 'institut national des sciences appliquées',
  INP: 'institut national polytechnique',
  EPIC: 'établissement public à caractère industriel et commercial',
  EPST: 'établissement public à caractère scientifique et technologique',
  EPA: 'établissement public administratif',
  GIP: 'groupement d’intérêt public',
  GIE: 'groupement d’intérêt économique',
  COMUE: 'communauté d’universités et établissements',
  ENS: 'école normale supérieure',
  IEP: 'institut d’études politiques',
  INHA: 'Institut national d’histoire de l’art',
}
const MOTIFS: Record<string, string> = {
  aucune_denomination_identique: 'nom sans équivalent unique dans le répertoire des entreprises (SIRENE)',
  plusieurs_unites_legales: 'nom porté par plusieurs unités légales',
  non_personne_morale: 'pas une personne morale',
  denomination_absente: 'nom absent de la source',
  personne_physique_ou_groupement: 'personne physique ou groupement de personnes physiques',
  siren_absent_du_stock_sirene: 'numéro SIREN absent du répertoire',
  uai_absent_de_l_annuaire_ou_sans_siret: 'établissement absent de l’annuaire de l’éducation ou sans numéro SIRET',
}

/** Programmes dont les rapports annuels de performances publient une dépense de l'État en euros par élève ou par
 * étudiant (relevé du 18/11/2026 sur les 14 programmes « Enseignement scolaire » et « Recherche et enseignement supérieur »). */
const PROGRAMMES_COUT_PUBLIE = ['143', '142']

const PAR_PAGE = 10
const NOMS_DEP = new Map(TOUS_DEPARTEMENTS)

/** Année universitaire d'une année de la source : 2025 devient « 2024-25 ». */
export const universitaire = (a: number) => `${a - 1}-${String(a % 100).padStart(2, '0')}`
const montantEur = (x: number | null | undefined) => (typeof x === 'number' ? eurLisible(x) : '–')
/** Sigles des rapports budgétaires écrits en toutes lettres. */
export const nomRapport = (s: string) =>
  s
    .replace(/\bRAP (\d{4})/g, 'rapport annuel de performances $1')
    .replace(/\bPAP (\d{4})/g, 'projet annuel de performances $1')
    .replace(/\bPLR (\d{4})/g, 'loi de règlement $1')
    .replace(/\bPLF (\d{4})/g, 'projet de loi de finances $1')
    .replace(/\bLFI (\d{4})/g, 'budget voté (loi de finances initiale) $1')
/** Jeu publié d'où vient une valeur des rapports de performances (« RAP 2025 ») : le segment de la source qui le nomme. */
function jeuDuRapport(sourceFichier: string, sourceValeur: string): string | null {
  const an = /\b(?:RAP|PAP) (\d{4})/.exec(sourceValeur)?.[1]
  if (!an) return null
  const type = /\bPAP/.test(sourceValeur) ? 'pap' : 'rap'
  return sourceFichier.split(' ; ').find((x) => new RegExp(`${type}[- ]${an}(?!\\d)`, 'i').test(x)) ?? null
}
const nonPublie = (texte = 'non publié') => `${traitStatut('nonpub')}${h(texte)}`
/** Montant en HTML : la valeur publiée, ou « non publié » (motif hachuré) quand la source n'en publie pas. Jamais 0. */
const montantOuNonPublie = (x: number | null | undefined, format: (v: number) => string = eurLisible) => (typeof x === 'number' ? h(format(x)) : nonPublie())
/** Fichiers du site cités dans des textes de données : nommés par ce qu'ils montrent. */
const FICHIERS_LISIBLES: Record<string, string> = { 'beneficiaires/france2030.json': 'France 2030 par bénéficiaire' }
/** Texte de données affiché tel quel, sans les termes techniques (chemin de fichier, « null », nom de champ). */
export function lisible(t: string): string {
  return t
    .replace(/\s*\((?:[a-z0-9_]+\/)*[a-z0-9_]+\.json\)/g, '')
    .replace(/(?:[a-z0-9_]+\/)*[a-z0-9_]+\.json/g, (f) => FICHIERS_LISIBLES[f] ?? 'fichier du site')
    .replace(/\bmontants null\b/g, 'montants non publiés')
    .replace(/\bnull\b/g, 'absente')
    .replace(/ ; le rapprochement est écrit dans [a-z_]+/g, ' ; le site rapproche les deux codes')
}

export function glossaire(textes: string[]): string {
  const vus = Object.keys(SIGLES).filter((s) => textes.some((t) => new RegExp(`(^|[^\\p{L}])${s}([^\\p{L}]|$)`, 'u').test(t)))
  return vus.length ? `<p class="aide">Sigles des libellés publiés : ${vus.map((s) => `${s} : ${h(SIGLES[s])}`).join(' ; ')}.</p>` : ''
}

function lienExterne(url: string, texte: string): string {
  return /^https:\/\//.test(url) ? `<a href="${h(url)}" rel="noopener noreferrer">${h(texte)}</a>` : h(texte)
}

/** Liste nommée paginée : PAR_PAGE lignes, puis un bouton qui en ajoute ; branchée après insertion dans la page. */
function liste(id: string, lignes: string[], etiquette: string): string {
  const reste = lignes.length - PAR_PAGE
  return `<ul class="lignes" id="${id}" aria-label="${h(etiquette)}">${lignes.slice(0, PAR_PAGE).join('')}</ul>${
    reste > 0 ? `<button type="button" id="${id}-plus">Afficher ${Math.min(PAR_PAGE, reste)} de plus</button>` : ''
  }`
}
function brancherListe(racine: ParentNode, id: string, lignes: string[]) {
  const ul = racine.querySelector<HTMLElement>(`#${id}`)
  const bouton = racine.querySelector<HTMLButtonElement>(`#${id}-plus`)
  if (!ul || !bouton) return
  let n = PAR_PAGE
  bouton.addEventListener('click', () => {
    n += PAR_PAGE
    ul.innerHTML = lignes.slice(0, n).join('')
    const reste = lignes.length - n
    if (reste > 0) bouton.textContent = `Afficher ${Math.min(PAR_PAGE, reste)} de plus`
    else bouton.remove()
  })
}

// ---------- Qui dépense : comptes des administrations par fonction ----------
const administrations = (adm: ArbreAdm | null) => [...(adm?.enfants ?? [])].sort((a, b) => a.id.localeCompare(b.id))
const fonction = (a: NoeudAdm, code: string) => a.enfants?.find((f) => f.id.endsWith('/' + code))
const nomAdmin = (a: NoeudAdm) => (a.nom === 'Etat' ? 'État et ses organismes' : libelle(a.nom))
/** Sujet d'une phrase pour chaque administration (secteurs de la comptabilité nationale). */
const SUJETS: Record<string, string> = { S1311: 'l’État et ses organismes', S1313: 'les collectivités locales', S1314: 'la Sécurité sociale' }

function blocCle(cofog: Cofog | null): string {
  const gf09 = cofog?.fonctions.find((f) => f.code === 'GF09')
  if (!cofog || !gf09 || !(cofog.total > 0)) return ''
  return `<div class="carte" data-cle>
  <p class="grand-chiffre">${surligne(md(gf09.md))}</p>
  <p class="sous-chiffre">dépensés pour l’enseignement par l’ensemble des administrations publiques en ${h(cofog.annee)}, soit ${h(sur100((gf09.md / cofog.total) * 100))} sur 100 € de dépense publique. Un euro passé d’une administration à une autre n’est compté qu’une fois.</p>
  <p>${badgeStatut('trace')} Montant publié par Eurostat, de l’école à l’université. La recherche est comptée à part (plus bas).</p>
  ${source(cofog.source, cofog.millesime)}
</div>`
}

function blocCles(adm: ArbreAdm | null, idx: Index | null): string {
  const items = administrations(adm)
    .map((a) => ({ a, f: fonction(a, 'GF09') }))
    .filter((x): x is { a: NoeudAdm; f: NoeudAdm } => !!x.f && x.a.md > 0)
    .map(
      ({ a, f }) =>
        `<li${a.id === 'S1311' ? ' class="cle-famille"' : ''}><strong>${h(md(f.md))}</strong><span>pour l’enseignement par ${h(SUJETS[a.id] ?? libelle(a.nom))} en ${h(adm!.millesime)}, soit ${h(sur100((f.md / a.md) * 100))} sur 100 € de ${a.id === 'S1314' ? 'ses' : 'leurs'} dépenses</span>${badgeStatut('trace')}</li>`,
    )
  const e = idx?.totaux.etudiants
  if (e) items.push(`<li><strong>${h(entier(e.etudiants_hors_cpge))}</strong><span>étudiants inscrits en ${h(e.annee_universitaire)} dans les établissements publics sous tutelle du ministère de l’enseignement supérieur</span>${badgeStatut('trace')}</li>`)
  return items.length ? `<ul class="cles" aria-label="Chiffres clés de l’éducation">${items.join('')}</ul>` : ''
}

function tableauFonctions(adm: ArbreAdm, codes: string[], nomLigne: (code: string, officiel: string) => string, legende: string, total?: string): string {
  const admins = administrations(adm).filter((a) => codes.some((c) => a.enfants?.some((f) => f.enfants?.some((s) => s.id.endsWith('/' + c)))))
  const sous = (a: NoeudAdm, code: string) => {
    for (const f of a.enfants ?? []) for (const s of f.enfants ?? []) if (s.id.endsWith('/' + code)) return s
    return undefined
  }
  const officiel = (code: string) => admins.map((a) => sous(a, code)?.nom).find(Boolean) ?? code
  const lignes = codes
    .filter((c) => admins.some((a) => sous(a, c)))
    .map((c) => `<tr><th scope="row">${nomLigne(c, officiel(c))}</th>${admins.map((a) => `<td class="nombre">${h(montantEur(sous(a, c) ? sous(a, c)!.md * 1e9 : null))}</td>`).join('')}</tr>`)
  const ligneTotal = total
    ? `<tr><th scope="row">${h(total)}</th>${admins.map((a) => `<td class="nombre">${h(montantEur(fonction(a, 'GF09') ? fonction(a, 'GF09')!.md * 1e9 : null))}</td>`).join('')}</tr>`
    : ''
  return `<div class="tableau-defile"><table><caption>${h(legende)}</caption><thead><tr><th scope="col">Niveau ou domaine</th>${admins
    .map((a) => `<th scope="col" class="nombre">${h(nomAdmin(a))}</th>`)
    .join('')}</tr></thead><tbody>${lignes.join('')}${ligneTotal}</tbody></table></div>`
}

function blocNiveaux(adm: ArbreAdm | null, cofog: Cofog | null): string {
  if (!adm) return `<h2>Qui dépense, et pour quel niveau</h2>${absent('Dépenses par administration non disponibles.')}`
  const codes = Object.keys(NIVEAUX)
  const gf09 = cofog?.fonctions.find((f) => f.code === 'GF09')
  const PRECISIONS: Record<string, string> = { S1311: ' (dont les universités)', S1313: ' (communes, intercommunalités, départements, régions)' }
  const qui = administrations(adm)
    .filter((a) => fonction(a, 'GF09'))
    .map((a) => `${SUJETS[a.id] ?? libelle(a.nom)}${PRECISIONS[a.id] ?? ''}`)
  return `<h2>Qui dépense, et pour quel niveau</h2>
<p>Les dépenses d’enseignement publiées sont celles de ${h(qui.join(' et de ').replace(/de les /g, 'des '))}. ${badgeStatut('trace')}</p>
${tableauFonctions(
  adm,
  codes,
  (c, off) =>
    `${h(NIVEAUX[c])}${off.toLowerCase() !== NIVEAUX[c].toLowerCase() ? `<br><span class="aide">(${h(off.charAt(0).toLowerCase() + off.slice(1).replace('n.c.a.', 'non classé ailleurs'))})</span>` : ''}`,
  `Dépenses d’enseignement par niveau et par administration, ${adm.millesime}`,
  'Total enseignement',
)}
<p class="aide">– : aucune ligne publiée pour cette administration. Les colonnes ne s’additionnent pas : une partie de l’argent passe d’une administration à l’autre (dotations, subventions).${gf09 ? ` Sans double compte, l’ensemble des administrations dépense ${h(md(gf09.md))} pour l’enseignement.` : ''} Une seule année est publiée dans ce fichier : il ne montre pas d’évolution.</p>
${source(adm.source, adm.millesime)}
<p class="liens-sortie"><a href="${lien('/explorer/etat/detail', { id: 'Education et recherche' })}">Les crédits de l’État pour l’école et pour l’enseignement supérieur, programme par programme</a></p>`
}

function blocRecherche(adm: ArbreAdm | null): string {
  if (!adm) return ''
  const codes = [
    ...new Set(
      administrations(adm).flatMap((a) =>
        (a.enfants ?? []).flatMap((f) => (f.enfants ?? []).filter((s) => /recherche|R & D/i.test(s.nom)).map((s) => s.id.split('/').pop() ?? '')),
      ),
    ),
  ].sort()
  if (!codes.length) return ''
  const domaine = (nom: string) =>
    /^R & D/.test(nom) ? `Recherche et développement : ${nom.replace(/^R & D (concernant (les |la |des )?|dans le domaine de (la |l’|l')?)/, '')}` : nom
  return `<h2>La recherche</h2>
<p>Dans ces comptes, la recherche n’est pas une fonction à part : la recherche fondamentale a sa ligne, et chaque domaine (santé, défense, économie, environnement) a sa ligne « recherche et développement ». ${badgeStatut('trace')}</p>
${tableauFonctions(adm, codes, (_c, off) => h(domaine(off)), `Dépenses de recherche par domaine et par administration, ${adm.millesime}`)}
<p class="aide">Les colonnes ne s’additionnent pas (une partie de l’argent passe d’une administration à l’autre). Une seule année est publiée dans ce fichier.</p>
${source(adm.source, adm.millesime)}
<p class="liens-sortie"><a href="${lien('/explorer/operateurs', { mission: 'Recherche et enseignement supérieur' })}">Universités et organismes de recherche : ce que l’État leur verse</a></p>`
}

// ---------- Toute la dépense d'éducation : compte de l'éducation (familles et entreprises comprises) ----------
/** Année suivie de « (provisoire) » quand la source la marque ainsi. */
const anneeP = (a: number, provisoire: boolean) => `${a}${provisoire ? ' (provisoire)' : ''}`
/** Niveaux publiés avec un appel de note et un sigle : écrits en toutes lettres. */
const NIVEAUX_COMPTE: Record<string, string> = { STS: 'Sections de technicien supérieur', CPGE: 'Classes préparatoires aux grandes écoles' }
export const nomNiveau = (n: string) => {
  const sans = n.replace(/[¹²³⁴⁵⁶⁷⁸⁹⁰]+$/u, '').trim()
  return NIVEAUX_COMPTE[sans] ?? sans
}
const pctOuNonPublie = (x: number | null | undefined) => montantOuNonPublie(x, (v) => pct(v))
const sur100OuNonPublie = (x: number | null | undefined) => montantOuNonPublie(x, sur100)

export function blocCompte(ce: CompteEducation | null): string {
  if (!ce) return ''
  const fi = ce.financement_initial
  const fe = fi.familles_et_entreprises
  const die = ce.die
  const iDie = die.annees.length - 1
  const anDie = die.annees[iDie]
  const iPib = ce.die_serie.annees.indexOf(anDie)
  const pib = iPib >= 0 ? ce.die_serie.part_pib_pct[iPib] : null
  const nv = ce.depense_moyenne_par_niveau
  const ev = ce.depense_moyenne_evolution
  const serie = (id: string) => ev.series.find((x) => x.id === id)
  const colonnesEv = [
    { id: 'premier_degre', nom: 'Premier degré (école)' },
    { id: 'second_degre', nom: 'Second degré (collège et lycée)' },
    { id: 'superieur', nom: 'Enseignement supérieur' },
    { id: 'ensemble', nom: 'Tous niveaux' },
  ].filter((c) => serie(c.id))
  const lecture = (t: string) => lisible(t).replace(/\s*\([a-z]+_[a-z_]+\)/g, '')
  const lignesNiveaux = nv.niveaux.map(
    (x) =>
      `<tr><th scope="row">${x.ensemble_du_degre ? `Ensemble : ${h(x.libelle_degre.charAt(0).toLowerCase() + x.libelle_degre.slice(1))}` : `${h(nomNiveau(x.niveau))} <span class="aide">(${h(x.libelle_degre.toLowerCase())})</span>`}</th><td class="nombre">${montantOuNonPublie(x.depense_moyenne_eur, eur)}</td></tr>`,
  )
  return `<section id="er-compte" aria-labelledby="er-compte-titre">
<h2 id="er-compte-titre">Toute la dépense d’éducation, familles et entreprises comprises</h2>
<p>Le compte de l’éducation, tenu par le service statistique du ministère de l’Éducation nationale, rassemble ce que dépensent pour l’éducation en France l’État, les collectivités, les autres administrations, les entreprises et les familles. En ${h(anneeP(anDie, die.provisoire[iDie]))}, cette dépense intérieure d’éducation est de ${montantOuNonPublie(die.die_md_eur_courants[iDie], md)}${typeof pib === 'number' ? `, soit ${h(pct(pib))} de la richesse produite dans l’année (produit intérieur brut)` : ''}. ${badgeStatut('trace')}</p>
<ul class="cles" aria-label="Compte de l’éducation : chiffres clés">
  <li><strong>${sur100OuNonPublie(fe.menages_pct)}</strong><span>sur 100 € de dépense d’éducation payés au départ par les familles en ${h(anneeP(fe.annee, fe.provisoire))} (cantine, internat, fournitures, cours, droits d’inscription)</span>${badgeStatut('trace')}</li>
  <li><strong>${sur100OuNonPublie(fe.entreprises_pct)}</strong><span>sur 100 € payés au départ par les entreprises en ${h(anneeP(fe.annee, fe.provisoire))} (dont taxe d’apprentissage et formation des apprentis)</span>${badgeStatut('trace')}</li>
  <li><strong>${montantOuNonPublie(die.depense_moyenne_eur_courants[iDie], eur)}</strong><span>de dépense moyenne par élève, apprenti ou étudiant en ${h(anneeP(anDie, die.provisoire[iDie]))}, tous niveaux et tous financeurs</span>${badgeStatut('trace')}</li>
</ul>
<p class="aide">Les parts des familles et des entreprises sont publiées séparément ; le site ne les additionne pas.</p>
<h3>Qui paie au départ</h3>
<div class="tableau-defile"><table><caption>Part de chaque financeur dans la dépense intérieure d’éducation (financement initial), en pourcentage</caption><thead><tr><th scope="col">Financeur</th>${fi.annees
    .map((a, i) => `<th scope="col" class="nombre">${h(anneeP(a, fi.provisoire[i]))}</th>`)
    .join('')}</tr></thead><tbody>${fi.financeurs
    .map(
      (f) =>
        `<tr><th scope="row">${f.parent ? `<span class="aide">${h(f.libelle)}</span>` : h(f.libelle)}</th>${f.part_pct.map((v) => `<td class="nombre">${pctOuNonPublie(v)}</td>`).join('')}</tr>`,
    )
    .join('')}</tbody></table></div>
<p class="aide">${h(lecture(fi.lecture))}</p>
<h3>Dépense moyenne par élève ou étudiant, selon le niveau</h3>
<div class="tableau-defile"><table><caption>Dépense moyenne par élève ou étudiant en ${h(anneeP(nv.annee, nv.provisoire))}, tous financeurs, en euros</caption><thead><tr><th scope="col">Niveau</th><th scope="col" class="nombre">Dépense moyenne</th></tr></thead><tbody>${lignesNiveaux.join('')}</tbody></table></div>
<p class="aide">${h(lecture(nv.lecture))} Ces montants couvrent toute la dépense d’éducation, tous financeurs confondus.</p>
<details><summary>Évolution depuis ${h(ev.annees[0])}, en euros constants de ${h(ev.prix_constants)}</summary>
<div class="tableau-defile"><table><caption>Dépense intérieure d’éducation et dépense moyenne par élève ou étudiant, ${h(ev.annees[0])} à ${h(ev.annees[ev.annees.length - 1])}, en euros constants de ${h(ev.prix_constants)}</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Dépense intérieure d’éducation</th><th scope="col" class="nombre">Part du produit intérieur brut</th>${colonnesEv
    .map((c) => `<th scope="col" class="nombre">Par élève : ${h(c.nom.charAt(0).toLowerCase() + c.nom.slice(1))}</th>`)
    .join('')}</tr></thead><tbody>${[...ev.annees.keys()]
    .reverse()
    .map((i) => {
      const a = ev.annees[i]
      const j = ce.die_serie.annees.indexOf(a)
      return `<tr><th scope="row">${h(anneeP(a, ev.provisoire[i]))}</th><td class="nombre">${montantOuNonPublie(j >= 0 ? ce.die_serie.die_md_eur_constants[j] : null, md)}</td><td class="nombre">${pctOuNonPublie(j >= 0 ? ce.die_serie.part_pib_pct[j] : null)}</td>${colonnesEv
        .map((c) => `<td class="nombre">${montantOuNonPublie(serie(c.id)!.eur_constants[i], eur)}</td>`)
        .join('')}</tr>`
    })
    .join('')}</tbody></table></div>
<p class="aide">Euros constants : montants corrigés de la hausse des prix, pour comparer les années entre elles.</p>
</details>
${source(`${ce.source} ; producteur : ${ce.producteur} ; licence ${ce.licence}`, ce.millesime)}
</section>`
}

// ---------- Collectivités : enseignement supérieur, vie étudiante, recherche ----------
/** Première année où la source publie au moins une ligne « enseignement supérieur et vie étudiante » (null = pas de ligne). */
export function premiereAnneeEsve(esr: CollectivitesEsr | null): number | null {
  if (!esr) return null
  for (let i = 0; i < esr.annees.length; i++) if (esr.regions.some((r) => typeof r.esve_eur[i] === 'number')) return esr.annees[i]
  return null
}

function blocCollectivites(esr: CollectivitesEsr | null, debutEsve: number | null): string {
  if (!esr?.national.length) return `<h2>Les collectivités, l’enseignement supérieur et la recherche</h2>${absent('Budgets des collectivités non disponibles.')}`
  const der = esr.national[esr.national.length - 1]
  const rt = esr.categories.rt ?? 'Recherche et transfert de technologie'
  const esve = esr.categories.esve ?? 'Enseignement supérieur et vie étudiante'
  const parType = (t: string) => der.par_type[t] as number
  const types = Object.keys(esr.types_collectivite)
    .filter((t) => typeof der.par_type[t] === 'number')
    .sort((a, b) => parType(b) - parType(a))
  const total = der.total_eur
  return `<h2>Les collectivités, l’enseignement supérieur et la recherche</h2>
<p>Les régions, les départements, les communes et les intercommunalités déclarent chaque année ce qu’elles consacrent à la recherche et à l’enseignement supérieur. En ${h(der.annee)} (montants ${h(der.qualite)}s) : ${montantOuNonPublie(total)}, dont ${montantOuNonPublie(der.rt_eur)} pour la recherche et le transfert de technologie et ${montantOuNonPublie(der.esve_eur)} pour l’enseignement supérieur et la vie étudiante. ${badgeStatut('trace')}</p>
${barres(
  types.map((t) => ({
    nom: esr.types_collectivite[t],
    valeur: parType(t),
    texte: eurLisible(parType(t)),
    detail: typeof total === 'number' && total > 0 ? `${sur100((parType(t) / total) * 100)} sur 100 € de ce total` : undefined,
  })),
  undefined,
  `Montants ${der.annee} par type de collectivité`,
)}
<div class="tableau-defile"><table><caption>Budgets des collectivités pour la recherche et l’enseignement supérieur, par année</caption><thead><tr><th scope="col">Année</th><th scope="col">Qualité</th><th scope="col" class="nombre">${h(rt)}</th><th scope="col" class="nombre">${h(esve)}</th><th scope="col" class="nombre">Total</th></tr></thead><tbody>${[...esr.national]
    .reverse()
    .map(
      (n) =>
        `<tr><th scope="row">${h(n.annee)}</th><td>${h(n.qualite)}</td><td class="nombre">${montantOuNonPublie(n.rt_eur)}</td><td class="nombre">${montantOuNonPublie(n.esve_eur)}</td><td class="nombre">${montantOuNonPublie(n.total_eur)}</td></tr>`,
    )
    .join('')}</tbody></table></div>
<p class="aide">${debutEsve !== null ? `La source ne publie la part « ${h(esve.toLowerCase())} » qu’à partir de ${h(debutEsve)} : avant, cette part et le total sont non publiés (et non pas nuls). ` : ''}Montants semi-définitifs et prévisionnels révisés ensuite par le producteur.</p>
${source(esr.source, esr.millesime)}`
}

// ---------- Montants par élève publiés (aucun montant par étudiant calculé par le site) ----------
// Règle « chiffre calculé par le site » (docs/NEUTRALITE.md) : le montant par étudiant que le pipeline calcule
// (dépenses des collectivités d'une année civile divisées par les inscrits d'une année universitaire) rapproche deux
// années différentes ; il n'est pas affiché.
function blocCout(idx: Index | null, _debutEsve: number | null): string {
  if (!idx?.cout_par_etudiant?.national.length) return ''
  return `<h2>Combien par élève ou par étudiant</h2>
<p class="aide">Le site ne calcule pas de montant par étudiant : les dépenses des collectivités sont publiées par année civile et les effectifs d’étudiants par année universitaire, deux périodes différentes.</p>
<h3>Les montants par élève ou par étudiant publiés par l’État</h3>
<div id="er-couts-publies"><p class="chargement">Chargement des rapports de performances…</p></div>`
}

function blocCoutsPublies(rs: (Realisations | null)[], avecCompte: boolean): string {
  const items: string[] = []
  const jeux = new Set<string>()
  for (const r of rs) {
    if (!r) continue
    const candidats = (r.resultats_mesures?.indicateurs ?? [])
      .map((i) => ({ i, nom: i.sous_indicateur || i.indicateur, vals: i.valeurs.filter((v) => typeof v.valeur === 'number').sort((a, b) => a.annee - b.annee) }))
      .filter((x) => /(dépense|coût)/i.test(x.nom) && /(élève|étudiant)/i.test(x.nom) && !/^part\b/i.test(x.nom) && /^(€|euros?)$/i.test(x.i.unite ?? '') && x.vals.length)
    const recent = Math.max(...candidats.map((x) => x.vals[x.vals.length - 1].annee))
    for (const x of candidats.filter((y) => y.vals[y.vals.length - 1].annee === recent)) {
      const der = x.vals[x.vals.length - 1]
      const avant = x.vals.slice(-3, -1).reverse()
      items.push(
        `<li><span>${h(x.nom)}</span><span class="montant">${h(eur(der.valeur!))}</span><span class="dest">${badgeStatut('trace')} en ${h(der.annee)}${
          avant.length ? ` (${avant.map((v) => `${h(eur(v.valeur!))} en ${h(v.annee)}`).join(', ')})` : ''
        } · programme ${h(r.programme)} « ${h(r.libelle)} » · ${h(nomRapport(der.source))} · <a href="${lien('/decisions/realisations', { p: r.programme })}">indicateurs du programme ${h(r.programme)}</a></span></li>`,
      )
      const jeu = jeuDuRapport(r.source, der.source)
      if (jeu) jeux.add(jeu)
    }
  }
  return `${
    items.length
      ? `<p>Les rapports annuels de performances de l’État publient une dépense par élève ou par étudiant pour l’enseignement agricole :</p><ul class="lignes" aria-label="Montants par élève ou par étudiant publiés par l’État">${items.join('')}</ul>${jeux.size ? source(nomRapport(`Rapports annuels de performances de l’État : ${[...jeux].join(' ; ')}`)) : ''}`
      : ''
  }<p>${badgeStatut('nonpub')} Pour l’école, le collège, le lycée et l’université, les rapports de performances repris par le site ne publient pas de dépense de l’État par élève ou par étudiant.${avecCompte ? ' La dépense moyenne de tous les financeurs par élève ou étudiant est donnée plus haut (compte de l’éducation).' : ''}</p>`
}

// ---------- Lycées de trois régions ----------
function blocLycees(idx: Index | null, region: string | null): string {
  const t = idx?.totaux.lycees
  if (!t || !region) return ''
  return `<h2>Les lycées : ce que versent trois régions</h2>
<p>D’après le code de l’éducation, la région a la charge des bâtiments, de l’équipement et du fonctionnement des lycées publics, et verse aussi des aides aux lycées privés sous contrat ; l’État rémunère les enseignants. Trois régions publient en données ouvertes ce qu’elles versent à chaque lycée. Leurs montants n’ont pas la même nature (votés, versés, aides à des actions) : ils ne se comparent pas d’une région à l’autre et ne s’additionnent pas.</p>
<div class="bascule" role="group" aria-label="Région">${Object.keys(t)
    .sort()
    .map((c) => `<button type="button" data-region="${h(c)}" aria-pressed="${c === region}">${h(t[c].region)}</button>`)
    .join('')}</div>
<div id="er-lycee" aria-live="polite"><p class="chargement">Chargement de la région…</p></div>`
}

function lignesLycees(d: Lycees): string[] {
  const c = (n: string) => d.colonnes.indexOf(n)
  return d.etablissements.map((e) => {
    const dep = String(e[c('departement')] ?? '')
    const montants = (e[c('montants_eur')] as (number | null)[] | null) ?? []
    const parAn = d.annees
      .map((a, i) => (typeof montants[i] === 'number' ? `${a} : ${eurLisible(montants[i] as number)}` : ''))
      .filter(Boolean)
      .join(' ; ')
    const secteur = e[c('secteur')] ? String(e[c('secteur')]).toLowerCase() : ''
    return `<li><span>${h(e[c('nom')])}</span><span class="montant">${montantOuNonPublie(e[c('total_eur')] as number | null)}</span><span class="dest">${[
      secteur && h(secteur),
      dep && h(`${NOMS_DEP.get(dep) ?? 'département'} (${dep})`),
      h(parAn),
    ]
      .filter(Boolean)
      .join(' · ')}</span></li>`
  })
}

function blocRegion(d: Lycees): string {
  const motifs = Object.entries(d.non_nommes.motifs ?? {})
  const dispositifs = d.par_dispositif
    .filter((x): x is { dispositif: string; total_eur: number } => typeof x.total_eur === 'number')
    .sort((a, b) => b.total_eur - a.total_eur)
    .slice(0, 5)
  const premier = d.annees[0]
  const dernier = d.annees[d.annees.length - 1]
  return `<h3>${h(d.region.nom)}</h3>
<p><strong>Nature des montants :</strong> ${h(d.nature_des_montants)}.</p>
<p>${badgeStatut('trace')} De ${h(premier)} à ${h(dernier)} : ${montantOuNonPublie(d.total_eur)} au total. ${h(entier(d.nommes.nombre))} bénéficiaires sont nommés (personnes morales) pour ${montantOuNonPublie(d.nommes.montant_eur)}${
    d.non_nommes.nombre
      ? ` ; ${h(entier(d.non_nommes.nombre))} restent agrégés pour ${montantOuNonPublie(d.non_nommes.montant_eur)}${motifs.length ? ` (${motifs.map(([k, v]) => `${h(MOTIFS[k] ?? k)} : ${h(entier(v.nombre))}`).join(' ; ')})` : ''}`
      : ''
  }.</p>
<div class="tableau-defile"><table><caption>${h(d.region.nom)} : montants versés aux lycées par année</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Montant</th><th scope="col" class="nombre">Bénéficiaires</th></tr></thead><tbody>${d.par_annee
    .map(
      (p) =>
        `<tr><th scope="row">${h(p.annee)}</th><td class="nombre">${montantOuNonPublie(p.total_eur)}${p.total_eur === 0 && p.lignes > 0 && p.lignes_montant_zero === p.lignes ? ' <span class="aide">(montants publiés à 0)</span>' : ''}</td><td class="nombre">${h(entier(p.beneficiaires))}</td></tr>`,
    )
    .join('')}</tbody></table></div>
${(d.controles ?? []).map((k) => `<p class="aide">Contrôle ${h(k.annee)} : somme des dotations ${montantOuNonPublie(k.somme_des_dotations_eur)}, total publié ${montantOuNonPublie(k.total_publie_eur)}, écart ${montantOuNonPublie(k.ecart_eur, eur)}${k.lignes_total_absent ? ` (${h(entier(k.lignes_total_absent))} ${k.lignes_total_absent > 1 ? 'totaux publiés absents' : 'total publié absent'})` : ''}.</p>`).join('')}
${
  dispositifs.length
    ? `<h4>Les cinq dispositifs aux montants les plus élevés</h4>${barres(
        dispositifs.map((x) => ({ nom: x.dispositif, valeur: x.total_eur, texte: eurLisible(x.total_eur), detail: typeof d.total_eur === 'number' && d.total_eur > 0 ? `${sur100((x.total_eur / d.total_eur) * 100)} sur 100 € versés de ${premier} à ${dernier}` : undefined })),
        undefined,
        `${d.region.nom} : dispositifs`,
      )}<p class="aide">Libellés tels que publiés par la région.</p>${glossaire(dispositifs.map((x) => x.dispositif))}`
    : ''
}
<h4>Les lycées nommés</h4>
${liste('er-lycees-noms', lignesLycees(d), `${d.region.nom} : lycées nommés`)}
<p class="aide">Ordre : ${h(lisible(d.ordre?.regle ?? 'montant total décroissant'))}. Montant total de ${h(premier)} à ${h(dernier)}, puis le détail par année.</p>
${source(`${d.source} ; licence ${d.licence}`, d.millesime)}`
}

async function afficherRegion(racine: HTMLElement, idx: Index, code: string) {
  const zone = racine.querySelector<HTMLElement>('#er-lycee')
  const t = idx.totaux.lycees?.[code]
  if (!zone || !t) return
  racine.querySelectorAll<HTMLButtonElement>('[data-region]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.region === code)))
  const d = await chargerSiPresent<Lycees>(t.fichier)
  if (racine.querySelector('[data-region][aria-pressed="true"]')?.getAttribute('data-region') !== code) return
  zone.innerHTML = d ? blocRegion(d) : absent('Données de cette région non disponibles.')
  if (d) brancherListe(zone, 'er-lycees-noms', lignesLycees(d))
  appliquerLargeurs(zone)
}

// ---------- Agence nationale de la recherche ----------
function blocAnr(idx: Index | null, anr: AnrProjets | null): string {
  const pia = anr?.pia_france2030
  const ancien = anr?.anr_2005_2009
  const tp = idx?.totaux.anr_pia_france2030
  const ta = idx?.totaux.anr_2005_2009
  if (!pia && !ancien) return ''
  const tableau = (b: BlocAnrProjets, legende: string, cle: 'aide_eur' | 'aide_projets_eur') =>
    `<div class="tableau-defile"><table><caption>${h(legende)}</caption><thead><tr><th scope="col">Édition</th><th scope="col" class="nombre">Projets</th><th scope="col" class="nombre">Aide allouée</th></tr></thead><tbody>${b.par_annee
      .map((p) => `<tr><th scope="row">${h(p.annee)}</th><td class="nombre">${h(entier(p.projets))}</td><td class="nombre">${montantOuNonPublie(p[cle])}</td></tr>`)
      .join('')}</tbody></table></div>`
  return `<h2>La recherche sur projets : l’Agence nationale de la recherche</h2>
<p>L’Agence nationale de la recherche (ANR) finance des projets choisis sur appel à projets. Elle gère aussi une partie des programmes d’investissements d’avenir et de France 2030.</p>
${
  pia
    ? `<h3>Programmes d’investissements d’avenir et France 2030 gérés par l’agence</h3>
${tp ? `<p>${badgeStatut('trace')} ${montantOuNonPublie(tp.aide_eur)} d’aide allouée à ${h(entier(tp.projets))} projets (${h(entier(tp.participations))} participations d’organismes), ${h(pia.millesime)}.</p>` : ''}
${tableau(pia, 'Aide allouée par édition de l’action', 'aide_eur')}
<p class="aide">Année : édition de l’action, telle que publiée par l’agence. Les montants sont l’aide allouée à chaque projet.</p>
<div id="er-anr-pia"></div>
<p class="liens-sortie"><a href="${lien('/beneficiaires', { onglet: 'france2030' })}">France 2030 par bénéficiaire (autre source, montants non additionnés)</a></p>
${source(pia.source)}`
    : ''
}
${
  ancien
    ? `<h3>Projets financés de 2005 à 2009</h3>
${ta ? `<p>${badgeStatut('trace')} ${montantOuNonPublie(ta.aide_projets_eur)} d’aide allouée à ${h(entier(ta.projets))} projets, ${h(ancien.millesime)}. Pour cette période, l’aide est aussi publiée par partenaire.</p>` : ''}
${tableau(ancien, 'Aide allouée par édition de l’appel à projets, 2005 à 2009', 'aide_projets_eur')}
<p class="aide">Année : édition de l’appel à projets. La source ne publie pas de répartition par territoire pour cette période.</p>
<div id="er-anr-ancien"></div>
${source(ancien.source)}`
    : ''
}`
}

function lignesAnr(b: BlocAnrEtab, cleMontant: string): string[] {
  const c = (n: string) => b.colonnes.indexOf(n)
  return b.etablissements.map((e) => {
    const sans = Number(e[c('lignes_sans_montant')] ?? 0)
    return `<li><span>${h(e[c('denomination')])}</span><span class="montant">${montantOuNonPublie(e[c(cleMontant)] as number | null)}</span><span class="dest">${h(entier(Number(e[c('participations')] ?? 0)))} participations, dont ${h(
      entier(Number(e[c('projets_coordonnes')] ?? 0)),
    )} projets coordonnés · éditions ${h(e[c('premiere_edition')])} à ${h(e[c('derniere_edition')])}${sans ? ` · ${h(entier(sans))} participations sans aide publiée` : ''}${e[c('lien_france2030')] === true ? ' · aussi nommé parmi les bénéficiaires de France 2030' : ''}</span></li>`
  })
}

function blocAnrNoms(b: BlocAnrEtab, id: string, cleMontant: 'aide_projets_coordonnes_eur' | 'aide_allouee_eur'): string {
  const statut = cleMontant === 'aide_allouee_eur' ? 'trace' : 'approche'
  const nn = b.non_nommes
  const motifs = Object.entries(nn.motifs ?? {})
  const categories = [...nn.par_categorie].sort((x, y) => (y[cleMontant] ?? -1) - (x[cleMontant] ?? -1) || x.categorie.localeCompare(y.categorie, 'fr'))
  return `<h4>Les organismes nommés</h4>
<p>${badgeStatut(statut)} ${
    cleMontant === 'aide_allouee_eur'
      ? 'Montant affiché : l’aide allouée par l’agence à l’organisme, telle que publiée. Les participations sans aide publiée (financement autre que l’agence, fonds propres ou montant absent) sont comptées à part, jamais comme 0 €.'
      : 'Montant affiché : l’aide allouée aux projets que l’organisme coordonne. L’agence publie l’aide par projet, pas sa répartition entre partenaires : ce montant n’est pas la somme reçue par l’organisme.'
  }</p>
${liste(id, lignesAnr(b, cleMontant), 'Organismes nommés')}
<p class="aide">Ordre : ${h(lisible(b.ordre?.regle ?? 'montant décroissant'))}. Seules les personnes morales retrouvées dans le répertoire des entreprises (SIRENE) sont nommées, sous leur dénomination officielle : ${h(entier(b.nommes.nombre))} organismes.</p>
<details><summary>Les ${h(entier(nn.organismes))} organismes non nommés, regroupés par catégorie</summary>
<div class="tableau-defile"><table><caption>Organismes non nommés par catégorie publiée par l’agence</caption><thead><tr><th scope="col">Catégorie</th><th scope="col" class="nombre">Organismes</th><th scope="col" class="nombre">Participations</th><th scope="col" class="nombre">${
    cleMontant === 'aide_allouee_eur' ? 'Aide allouée' : 'Aide des projets coordonnés'
  }</th></tr></thead><tbody>${categories
    .map((k) => `<tr><th scope="row">${h(k.categorie)}</th><td class="nombre">${h(entier(k.organismes))}</td><td class="nombre">${h(entier(k.participations))}</td><td class="nombre">${montantOuNonPublie(k[cleMontant])}</td></tr>`)
    .join('')}</tbody></table></div>
${glossaire(categories.map((k) => k.categorie))}
${motifs.length ? `<p class="aide">Raisons du regroupement, en nombre de participations : ${motifs.map(([k, v]) => `${h(MOTIFS[k] ?? k)} : ${h(entier(v))}`).join(' ; ')}.</p>` : ''}
</details>`
}

// ---------- Écarts, limites, sources ----------
function blocEcarts(idx: Index | null): string {
  const e = idx?.ecarts ?? []
  if (!e.length) return ''
  return `<h2>Écarts entre sources</h2>
<p>Quand deux sources publient un montant pour le même objet, les deux sont donnés ; ils ne s’additionnent pas et le site ne choisit pas entre eux.</p>
<div class="tableau-defile"><table><caption>Montants publiés par deux sources pour le même objet</caption><thead><tr><th scope="col">Objet</th><th scope="col" class="nombre">Montant</th><th scope="col" class="nombre">Autre montant</th><th scope="col" class="nombre">Écart</th></tr></thead><tbody>${e
    .map(
      (x) =>
        `<tr><th scope="row">${h(x.objet)}<br><span class="aide">${h(lisible(x.lecture))}</span></th><td class="nombre">${montantOuNonPublie(x.montant)}<br><span class="aide">${h(lisible(x.source))}</span></td><td class="nombre">${montantOuNonPublie(x.autre_montant)}<br><span class="aide">${h(lisible(x.autre_source))}</span></td><td class="nombre">${montantOuNonPublie(x.ecart)}${typeof x.ecart_pct === 'number' ? ` (${h(pct(x.ecart_pct, 2))})` : ''}</td></tr>`,
    )
    .join('')}</tbody></table></div>`
}

function blocLimites(idx: Index | null, avecCompte: boolean): string {
  const l = idx?.limites ?? []
  const s = idx?.sources_inaccessibles ?? []
  return `<h2>Ce que ces données ne disent pas</h2>
<ul class="limites">
  <li>${traitStatut('nonpub')}<span>${
    avecCompte
      ? 'Ce que paie une famille en particulier, et le détail du financement après les transferts entre financeurs (bourses, par exemple), ne sont pas dans les données reprises par le site.'
      : 'Ce que versent les familles et les entreprises pour l’éducation n’est pas dans les données reprises par le site.'
  }</span></li>
</ul>
${l.length ? `<ul>${l.map((x) => `<li>${h(lisible(x))}</li>`).join('')}</ul>` : ''}
${s.length ? `<details><summary>Sources non reprises</summary><ul>${s.map((x) => `<li>${h(lisible(x.source))} : ${h(lisible(x.motif))}.</li>`).join('')}</ul></details>` : ''}`
}

function blocSources(idx: Index | null): string {
  if (!idx?.sources.length) return ''
  const odbl = [...new Set((idx.licences?.odbl ?? []).map((x) => x.producteur))]
  return `<h2>Sources et licences</h2>
<ul>${idx.sources.map((s) => `<li>${lienExterne(s.page, s.titre)} : ${h(s.producteur)}, ${h(s.millesime)}, ${h(s.licence)}.</li>`).join('')}</ul>
${
  odbl.length
    ? `<p class="aide">Les jeux publiés par ${h(odbl.join(', '))} sont sous ${lienExterne(idx.licences!.odbl![0].url_licence, 'Open Database License 1.0')} (ODbL) : les données que le site en tire gardent cette licence et la mention de leur producteur. Les autres jeux sont sous Licence Ouverte 2.0.</p>`
    : ''
}`
}

const SORTIES = `<ul class="liens-sortie">
  <li><a href="${lien('/explorer/etat/detail', { id: 'Education et recherche' })}">Le budget de l’État pour l’éducation et la recherche, programme par programme</a></li>
  <li><a href="${lien('/explorer/operateurs', { mission: 'Recherche et enseignement supérieur' })}">Universités et organismes de recherche : ce que l’État leur verse</a></li>
  <li><a href="${lien('/beneficiaires', { onglet: 'france2030' })}">Les bénéficiaires de France 2030</a></li>
  <li><a href="${lien('/explorer/collectivites')}">Les collectivités locales et leurs dépenses</a></li>
</ul>`

// ---------- Suite : fichiers plus lourds, chargés après le premier affichage ----------
async function completer(cible: HTMLElement, idx: Index | null, region: string | null): Promise<void> {
  const [etu, anrEtab, rs] = await Promise.all([
    idx?.cout_par_etudiant ? chargerSiPresent<Etudiants>('education_recherche/etudiants.json') : Promise.resolve(null),
    idx ? chargerSiPresent<AnrEtab>('education_recherche/anr_etablissements.json') : Promise.resolve(null),
    idx?.cout_par_etudiant ? Promise.all(PROGRAMMES_COUT_PUBLIE.map((p) => chargerSiPresent<Realisations>(`realisations/${p}.json`))) : Promise.resolve([] as (Realisations | null)[]),
  ])
  const poser = (sel: string, html: string) => {
    const z = cible.querySelector<HTMLElement>(sel)
    if (z) z.innerHTML = html
  }
  void etu // fichier des étudiants : montant par étudiant non affiché (règle « chiffre calculé par le site »)
  poser('#er-couts-publies', blocCoutsPublies(rs, !!cible.querySelector('#er-compte')))
  if (anrEtab?.pia_france2030) {
    poser('#er-anr-pia', blocAnrNoms(anrEtab.pia_france2030, 'er-anr-pia-noms', 'aide_projets_coordonnes_eur'))
    brancherListe(cible, 'er-anr-pia-noms', lignesAnr(anrEtab.pia_france2030, 'aide_projets_coordonnes_eur'))
  }
  if (anrEtab?.anr_2005_2009) {
    poser('#er-anr-ancien', blocAnrNoms(anrEtab.anr_2005_2009, 'er-anr-ancien-noms', 'aide_allouee_eur'))
    brancherListe(cible, 'er-anr-ancien-noms', lignesAnr(anrEtab.anr_2005_2009, 'aide_allouee_eur'))
  }
  if (idx && region) {
    cible.querySelectorAll<HTMLButtonElement>('[data-region]').forEach((b) => b.addEventListener('click', () => void afficherRegion(cible, idx, b.dataset.region ?? '')))
    await afficherRegion(cible, idx, region)
  }
  appliquerLargeurs(cible)
}

export async function rendre(cible: HTMLElement, params: URLSearchParams): Promise<Rendu | void> {
  const [idx, cofog, adm, esr, anr, compte] = await Promise.all([
    chargerSiPresent<Index>('education_recherche/index.json'),
    chargerSiPresent<Cofog>('cofog.json'),
    chargerSiPresent<ArbreAdm>('arbre_administrations/racine.json'),
    chargerSiPresent<CollectivitesEsr>('education_recherche/collectivites_esr.json'),
    chargerSiPresent<AnrProjets>('education_recherche/anr_projets.json'),
    chargerSiPresent<CompteEducation>('education_recherche/compte_education.json'),
  ])
  if (!idx && !adm && !cofog) {
    cible.innerHTML = `${enCours('L’éducation et la recherche', 'Dépenses d’enseignement par niveau, budgets des collectivités, lycées, projets de recherche.')}${SORTIES}${partPersonnelle()}`
    return
  }
  const regions = Object.keys(idx?.totaux.lycees ?? {}).sort()
  const demandee = params.get('region')
  const region = demandee && regions.includes(demandee) ? demandee : (regions[0] ?? null)
  const debutEsve = premiereAnneeEsve(esr)
  cible.innerHTML = `
<h1>L’éducation et la recherche</h1>
<p class="chapeau">Tu vois ici ce que les administrations publiques dépensent pour l’école, le collège, le lycée, l’enseignement supérieur et la recherche, qui dépense (l’État, les collectivités locales), et à qui vont certains de ces montants : les lycées de trois régions et les organismes de recherche soutenus par l’Agence nationale de la recherche. ${
  compte
    ? 'Tu vois aussi la part que paient au départ les familles et les entreprises, et la dépense moyenne par élève ou étudiant, de l’école à l’université (compte de l’éducation). La page ne montre pas ce que paie une famille en particulier, ni une dépense par élève lycée par lycée.'
    : 'Ce que versent les familles et les entreprises n’est pas dans les données reprises ici, pas plus qu’un montant moyen par élève de l’école, du collège ou du lycée.'
}</p>
<p>Chaque montant porte son année, sa source et son statut :</p>
${legendeStatuts()}
${blocCle(cofog)}
${blocCles(adm, idx)}
${blocNiveaux(adm, cofog)}
${blocRecherche(adm)}
${blocCompte(compte)}
${
  idx
    ? `${blocCollectivites(esr, debutEsve)}
${blocCout(idx, debutEsve)}
${blocLycees(idx, region)}
${blocAnr(idx, anr)}
${blocEcarts(idx)}`
    : `<div class="en-cours"><p><strong>Données en cours d’intégration.</strong> Budgets des collectivités pour l’enseignement supérieur, lycées de trois régions, projets de l’Agence nationale de la recherche.</p></div>`
}
${blocLimites(idx, !!compte)}
${blocSources(idx)}
<h2>Pour aller plus loin</h2>
${SORTIES}
${partPersonnelle()}`
  return { suite: completer(cible, idx, region) }
}


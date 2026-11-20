// Hôpitaux et établissements de santé (site/data/sante_etablissements/, contrat 2.29).
// Qui les finance : montants nationaux lus dans les comptes de la Sécurité sociale, le budget de l'État et l'aide
// sociale des départements, posés côte à côte et jamais additionnés (comptes différents, transferts entre financeurs).
// Le détail de ces montants reste sur leurs pages (Sécurité sociale, budget de l'État) : ici, un renvoi par ligne.
// Comptes agrégés publiés par l'ATIH (2020-2024), comptes par établissement jusqu'en 2015 (Hospi Diag).
// Recherche par département (un fichier de moins de 200 Ko, chargé à la demande) ou par nom dans toute la France
// (Hospi Diag, moins de 1 Mo, chargé seulement quand aucun département n'est choisi). Seuls les établissements dont
// le gestionnaire est une personne morale sont nommés (filtre du pipeline) ; aucune donnée de patient, aucun
// professionnel nommé.
import { brancherTerritoire, repliTerritoire } from './explorer_territoires'
import { choix, listeRecherche, segmente, valeurChoix } from '../composants/choix'
import { billet } from '../composants/billet'
import { partPersonnelle } from '../composants/hub'
import { TOUS_DEPARTEMENTS } from '../departements'
import { chargerSiPresent, listeProgrammes, trouverNoeud, type Noeud } from '../donnees'
import { lien } from '../routeur'
import { absent, badgeStatut, entier, eur2, eurLisible, h, lireLesMotifs, md, nomVille, type Statut, sur100, surligne, traitStatut, badgeCalcule } from '../util'
import { enCours } from './dette'

type Valeur = string | number | null
type Ligne = Valeur[]
interface SourceIdx {
  titre: string
  producteur?: string
  url: string
  licence: string
  millesime?: string
  mention_obligatoire?: string
}
interface Index {
  millesime: string
  collecte_le: string
  avertissement: string
  perimetre: string
  regle_personnes: string
  note_prix: string
  domaines: { id: string; libelle: string }[]
  secteurs: { id: string; libelle: string }[]
  categories: { code: string | null; libelle: string | null; domaine: string }[]
  colonnes: string[]
  colonnes_prix: string[]
  totaux: { comptes: number[]; actes_ccam: Record<string, number>; prix_ehpad: Record<string, (number | null)[]>; etablissements_nommes: number }
  confidentialite?: { motifs?: Record<string, string> }
  ecarts: { objet: string; source: string; date: string; nombre: number; autre_source: string; autre_date: string; autre_nombre: number; ecart: number; lecture_ecart: string }[]
  liens: { vue: string; fichier: string; id?: string }[]
  regle_liens: string
  sources: Record<string, SourceIdx>
  fichiers: Record<string, string | number>
  recherche_publique?: { date: string; verdict: string }
}
interface Finances {
  millesime: string
  source: string
  avertissement: string
  definitions: Record<string, string>
  colonnes: string[]
  lignes: Ligne[]
  totaux: { methode: string; par_annee: Record<string, Record<string, number>> }
}
interface Limites {
  avertissement: string
  non_ouvert: { sujet: string; etat: string; ce_qui_existe: string }[]
  limites: string[]
}
interface ResumeDep {
  comptes: (number | null)[]
  actes_ccam: (number | null)[]
  prix_ehpad: Record<string, (number | null)[]>
  etablissements_nommes: number
  fichier: string
}
interface Departements {
  millesime: string
  note: string
  colonnes: string[]
  colonnes_prix: string[]
  annees_ccam: number[]
  departements: Record<string, ResumeDep>
}
interface Departement {
  source: string
  millesime: string
  communes: { colonnes: string[]; lignes: Ligne[] }
  etablissements: { colonnes: string[]; lignes: Ligne[]; annee_prix: number; ordre: string }
  non_nommes: { total: number; par_motif: Record<string, number> }
}
interface HospiDiag {
  millesime: string
  source: string
  avertissement: string
  definitions: Record<string, string>
  colonnes: string[]
  lignes: Ligne[]
}
interface Fir {
  millesime: string
  source: string
  attribuant: string
  total_eur: number
  conventions: number
  nommes?: { nombre: number }
  beneficiaires?: { top: { siren: string; montant_eur: number; conventions: number }[] }
}
interface Territoires {
  sources?: Record<string, { titre: string; page: string; licence: string }>
  mesures?: Record<string, string>
  postes?: { id: string; nom: string }[]
  totaux?: { aide_sociale_drees?: { france?: Record<string, Record<string, number | null>> } }
}
type NoeudSecu = Noeud & { mode?: string; tracabilite_pct?: number; sources?: string[] }
type RacineSecu = NoeudSecu & { sources_detail?: Record<string, { titre: string; url: string; millesime: string }> }
interface LigneFin {
  nom: string
  lien?: string
  montant: string
  quand: string
  statut: Statut
  note?: string
}

const PAR_PAGE = 30
const NOMS_DEP = new Map<string, string>([...TOUS_DEPARTEMENTS, ['975', 'Saint-Pierre-et-Miquelon'], ['986', 'Wallis-et-Futuna']])
const nomDep = (c: string) => `${NOMS_DEP.get(c) ?? 'Département'} (${c})`
const VUE_SECU: Record<string, string> = { 'secu/arbre': 'organismes2024', 'secu/arbre_2025': 'organismes2025', 'secu/cps': 'protection2024' }
const GROUPES_SECU: Record<string, { titre: string; texte: string }> = {
  maladie: {
    titre: 'Assurance maladie',
    texte: 'L’assurance maladie paie les hôpitaux et les cliniques pour les soins qu’ils donnent (tarifs par séjour et dotations). Le même objectif de dépenses compte le fonds d’intervention régional, réparti par les agences régionales de santé, et le soutien national à l’investissement.',
  },
  autonomie: {
    titre: 'Branche autonomie de la Sécurité sociale',
    texte: 'La branche autonomie finance les établissements et services pour personnes âgées, dont les soins dans les EHPAD (établissements d’hébergement pour personnes âgées dépendantes), et ceux pour personnes handicapées.',
  },
}
/** Catégories des comptes agrégés de l'ATIH (tranches de taille en millions d'euros, définies par l'ATIH). */
const CATEGORIES_ATIH: Record<string, string> = {
  CHU: 'Centres hospitaliers régionaux et universitaires',
  'CH > 150M': 'Centres hospitaliers, tranche de plus de 150 M€',
  '70M<CH<150M': 'Centres hospitaliers, tranche de 70 à 150 M€',
  '20M<CH<70M': 'Centres hospitaliers, tranche de 20 à 70 M€',
  'CH < 20M': 'Centres hospitaliers, tranche de moins de 20 M€',
  CLCC: 'Centres de lutte contre le cancer',
  EBNL: 'Autres établissements privés à but non lucratif',
}
const ACTIVITES: Record<string, string> = {
  mco: 'Médecine, chirurgie, obstétrique',
  psy: 'Psychiatrie',
  smr: 'Soins médicaux et de réadaptation',
  had: 'Hospitalisation à domicile',
  mixte: 'Plusieurs activités, aucune à 80 % ou plus',
}
const MESURES: [string, string][] = [
  ['etablissements', 'Établissements'],
  ['produits_eur', 'Produits'],
  ['charges_eur', 'Charges du compte principal'],
  ['charges_personnel_eur', 'dont charges de personnel'],
  ['resultat_principal_eur', 'Résultat du compte principal'],
  ['encours_dette_eur', 'Dette en cours'],
]
const PRIX: Record<string, string> = {
  prix_hebergement_chambre_seule: 'Hébergement en chambre seule',
  prix_hebergement_chambre_seule_aide_sociale: 'Hébergement en chambre seule, place habilitée à l’aide sociale',
  tarif_dependance_gir_1_2: 'Dépendance, GIR 1 et 2 (perte d’autonomie la plus forte)',
  tarif_dependance_gir_3_4: 'Dépendance, GIR 3 et 4',
  tarif_dependance_gir_5_6: 'Dépendance, GIR 5 et 6 (perte d’autonomie la plus faible)',
}
const libellePrix = (c: string) => PRIX[c.replace(/(_median)?_eur$/, '')] ?? c
const HD_CATEGORIES: Record<string, string> = {
  CHR: 'centre hospitalier régional',
  CH: 'centre hospitalier',
  CLCC: 'centre de lutte contre le cancer',
  EBNL: 'établissement privé à but non lucratif',
  CLI: 'clinique privée',
}
const HD_MESURES: [string, string][] = [
  ['produits_eur', 'Produits courants'],
  ['recettes_t2a_eur', 'dont tarification à l’activité'],
  ['recettes_migac_eur', 'dont dotations pour missions d’intérêt général (MIGAC)'],
  ['charges_eur', 'Charges courantes'],
  ['resultat_eur', 'Résultat'],
  ['encours_dette_eur', 'Dette en cours'],
]
const REFERENTIELS: Record<string, string> = { D: 'comptes financiers', O: 'liasses fiscales' }
const SIGLES: [string, string][] = [
  ['APA', 'allocation personnalisée d’autonomie, versée par les départements'],
  ['ARS', 'agence régionale de santé'],
  ['ATIH', 'Agence technique de l’information sur l’hospitalisation'],
  ['CCAM', 'classification commune des actes médicaux'],
  ['CNSA', 'Caisse nationale de solidarité pour l’autonomie (branche autonomie)'],
  ['DREES', 'service statistique des ministères sociaux'],
  ['EHPAD', 'établissement d’hébergement pour personnes âgées dépendantes'],
  ['FINESS', 'fichier national des établissements sanitaires et sociaux'],
  ['FIR', 'fonds d’intervention régional, géré par les agences régionales de santé'],
  ['GIR', 'groupe iso-ressources : niveau de perte d’autonomie, de 1 (la plus forte) à 6'],
  ['MIGAC', 'missions d’intérêt général et aide à la contractualisation (dotations)'],
  ['ONDAM', 'objectif national de dépenses d’assurance maladie, voté chaque année'],
  ['PNRR', 'plan national de relance et de résilience, financé en partie par l’Union européenne'],
]

const enObjet = (colonnes: string[], l: Ligne): Record<string, Valeur> => Object.fromEntries(colonnes.map((c, i) => [c, l[i] ?? null]))
const nombre = (v: Valeur | undefined): number | null => (typeof v === 'number' ? v : null)
const texte = (v: Valeur | undefined): string => (v === null || v === undefined ? '' : String(v))
const dateFr = (iso: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso
}
const annee = (millesime?: string) => /\b(\d{4})\b/.exec(millesime ?? '')?.[1] ?? ''
const quand = (millesime?: string) => (/^Exécution \d{4}$/.test(millesime ?? '') ? `dépensé en ${annee(millesime)}` : (millesime ?? ''))
const plage = (x: string) => x.replace(/^(\d{4})-(\d{4})$/, '$1 à $2')
const normaliser = (s: string) =>
  s
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
const majuscule = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const sourceLien = (titre: string, url?: string, millesime?: string) =>
  `<p class="source">${url ? `<a href="${h(url)}" rel="noopener noreferrer">${h(titre)}</a>` : h(titre)}${millesime ? ` (${h(millesime)})` : ''}</p>`
/** Retire du texte publié avec les données ses renvois techniques (fichiers, nœuds, colonnes) : ils n'ont pas de sens ici. */
export const sansRenvoisTechniques = (t: string) =>
  t
    .replace(/\s*\([^()]*(?:\.json|\.py|[a-z_]+\/(?!\d)|nœud|colonnes)[^()]*\)/g, '')
    .replace(/,?\s*repris dans [\w./-]+\.json/g, '')
    .replace(/\s*:\s*(?:elles|ils) sont trait[ée]+s? par [\w./-]+\.py et ne sont pas repris[es]* ici/g, '')
    .replace(/\s+est dans [a-z_]+\/(?=[\s.;]|$)/g, ' est dans les comptes de la Sécurité sociale')

function liste(lignes: LigneFin[]): string {
  return `<ul class="lignes">${lignes
    .map(
      (l) =>
        `<li><span>${l.lien ? `<a href="${h(l.lien)}">${h(l.nom)}</a>` : h(l.nom)}</span> <span class="montant">${h(l.montant)}</span> <span class="dest">${h(l.quand)} ${badgeStatut(l.statut)}${l.note ? ` · ${h(l.note)}` : ''}</span></li>`,
    )
    .join('')}</ul>`
}
const carte = (id: string, titre: string, corps: string) => `<section class="carte carte-contour" aria-labelledby="${id}"><h3 id="${id}">${h(titre)}</h3>${corps}</section>`

function statutNoeud(n: NoeudSecu): Statut {
  if (n.mode) return n.mode === 'publie' || n.mode === 'tableau_image' ? 'trace' : 'approche'
  return (n.tracabilite_pct ?? 0) >= 99.95 ? 'trace' : 'approche'
}

interface Lu {
  noeud: NoeudSecu
  parent: NoeudSecu
  racine: RacineSecu
  dossier: string
}
async function lireNoeud(dossier: string, id: string): Promise<Lu | null> {
  try {
    const { noeud, chemin, racine } = await trouverNoeud(dossier, id)
    return { noeud, parent: chemin[chemin.length - 2] ?? racine, racine, dossier }
  } catch {
    return null
  }
}

/** Assurance maladie et branche autonomie : les nœuds de l'arbre Sécurité sociale désignés par index.json (liens). */
async function blocsSecu(idx: Index, fir: Fir | null): Promise<{ cartes: string[]; cle: Lu | null; fir: Lu | null }> {
  const lus = (await Promise.all(idx.liens.filter((l) => l.vue === 'secu_arbre' && l.id).map((l) => lireNoeud(l.fichier.replace(/\/racine\.json$/, ''), l.id!)))).filter(
    (x): x is Lu => !!x,
  )
  const groupes = new Map<string, Lu[]>()
  for (const x of lus) groupes.set(x.parent.id, [...(groupes.get(x.parent.id) ?? []), x])
  const cartes = [...groupes.values()].map((g) => {
    const p = g[0].parent
    const cleGroupe = p.id.split('/').pop() ?? ''
    const def = GROUPES_SECU[cleGroupe]
    const sources = [...new Set(g.flatMap((x) => x.noeud.sources ?? []))].map((k) => g[0].racine.sources_detail?.[k]).filter((s): s is { titre: string; url: string; millesime: string } => !!s)
    const lignes: LigneFin[] = g.map((x) => ({
      nom: majuscule(x.noeud.nom.replace(/^ONDAM\s*:\s*/, '')),
      lien: lien('/explorer/secu', { m: VUE_SECU[x.dossier], id: x.noeud.id }),
      montant: md(x.noeud.md),
      quand: quand(x.racine.millesime),
      statut: statutNoeud(x.noeud),
      note: `${sur100((x.noeud.md / p.md) * 100)} sur 100 € dépensés par « ${p.nom} »`,
    }))
    const extraFir =
      cleGroupe === 'maladie' && fir
        ? `<p>Ce fonds est réparti par chaque agence régionale de santé. Celle des Pays de la Loire publie ses subventions : ${h(eurLisible(fir.total_eur))} en ${h(annee(fir.millesime))}, ${h(entier(fir.conventions))} conventions${
            fir.nommes ? `, ${h(entier(fir.nommes.nombre))} bénéficiaires nommés` : ''
          } ${badgeStatut('trace')}. Le montant reçu par chaque gestionnaire s’affiche dans sa fiche, dans la recherche plus bas.</p>${sourceLien(fir.source.replace(/,?\s*https?:\/\/\S+$/, ''), /https?:\/\/\S+$/.exec(fir.source)?.[0], fir.millesime)}`
        : ''
    return carte(
      `fin-${cleGroupe || 'secu'}`,
      def?.titre ?? p.nom,
      `<p>${h(def?.texte ?? '')}</p>${liste(lignes)}${sources.map((s) => sourceLien(s.titre, s.url, s.millesime)).join('')}${extraFir}`,
    )
  })
  const cle = lus.filter((x) => x.parent.md > 0).sort((a, b) => b.noeud.md - a.noeud.md)[0] ?? null
  return { cartes, cle, fir: lus.find((x) => /fir/.test(x.noeud.id.split('/').pop() ?? '')) ?? null }
}

/** Budget de l'État : la ligne « Ségur investissement » (programme 379, action 02), reversée à la Sécurité sociale. */
async function blocEtat(): Promise<{ carte: string; segur: { md: number; millesime: string } | null }> {
  const progs = await listeProgrammes().catch(() => [])
  const p = progs.find((x) => x.numero === '379')
  const t = p ? await lireNoeud('arbre', `${p.id}/379-02`) : null
  const mission = p ? p.id.split('/').slice(0, -1).join('/') : ''
  const corps = t
    ? `<p>L’État reverse à la Sécurité sociale les fonds européens du plan de relance prévus pour le volet « Ségur investissement » (investissement en santé). Ce montant est versé à la Sécurité sociale : il ne s’ajoute pas aux dépenses de l’assurance maladie ci-dessus.</p>
${liste([{ nom: 'Ségur investissement (plan de relance)', montant: md(t.noeud.md), quand: quand(t.racine.millesime), statut: 'trace', note: `intitulé publié : « ${t.noeud.nom} », programme 379` }])}
${sourceLien(t.racine.source ?? '', undefined, t.racine.millesime)}`
    : absent('Ligne « Ségur investissement » du budget de l’État : donnée non disponible.')
  const suite = mission
    ? `<p>Les autres lignes de santé du budget de l’État (prévention, sécurité sanitaire, aide médicale de l’État) sont dans <a href="${h(lien('/explorer/etat/detail', { id: mission }))}">le détail de la mission Santé du budget de l’État</a>.</p>`
    : ''
  return { carte: carte('fin-etat', 'Budget de l’État', corps + suite), segur: t ? { md: t.noeud.md, millesime: t.racine.millesime ?? '' } : null }
}

/** Départements : APA en établissement, aide sociale à l'hébergement, hébergement des personnes handicapées (DREES). */
async function blocDepartements(): Promise<string> {
  const [t, transferts] = await Promise.all([chargerSiPresent<Territoires>('territoires/index.json'), lireNoeud('secu/arbre', 'robss/autonomie/transferts')])
  const fr = t?.totaux?.aide_sociale_drees?.france
  if (!t || !fr) return carte('fin-departements', 'Départements', absent('Dépenses d’aide sociale des départements : donnée non disponible.'))
  const postes: [string, string][] = [
    ['apa_etablissement', 'brute'],
    ['ash_pa_etablissement', 'apres_recuperations'],
    ['ph_hebergement_etablissement', 'brute'],
  ]
  const lignes: LigneFin[] = []
  for (const [poste, mesure] of postes) {
    const serie = fr[`${poste}.${mesure}`]
    const nom = t.postes?.find((x) => x.id === poste)?.nom
    const an = serie ? Object.keys(serie).filter((a) => typeof serie[a] === 'number').sort().pop() : undefined
    if (serie && an && nom)
      lignes.push({
        nom: nom.replace(/,\s*après récupérations.*$/, ''),
        montant: eurLisible(serie[an]!),
        quand: `${an}, dépense ${mesure === 'brute' ? 'brute' : 'après récupérations'}`,
        statut: 'approche',
        note: 'total estimé par la DREES',
      })
  }
  const s = t.sources?.drees_aide_sociale
  const definitions = postes
    .map(([, m]) => m)
    .filter((m, i, a) => a.indexOf(m) === i)
    .map((m) => t.mesures?.[m])
    .filter((x): x is string => !!x)
  return carte(
    'fin-departements',
    'Départements',
    `<p>Les départements versent l’allocation personnalisée d’autonomie (APA) aux personnes âgées accueillies en établissement, l’aide sociale à l’hébergement (sous conditions) et des aides à l’hébergement et à l’accueil de jour de personnes handicapées en établissement.</p>
${lignes.length ? liste(lignes) : absent('Montants non disponibles.')}
<p class="aide">Totaux de la France métropolitaine et de l’outre-mer hors Mayotte, estimés par la DREES : ils complètent les départements qui n’ont pas répondu à l’enquête. ${
      transferts
        ? `Une partie de ces dépenses est compensée aux départements par la branche autonomie (<a href="${h(lien('/explorer/secu', { id: transferts.noeud.id }))}">concours aux départements</a>) : ne pas les additionner avec le bloc de la branche autonomie.`
        : 'Une partie de ces dépenses est compensée aux départements par la branche autonomie : ne pas les additionner avec le bloc de la branche autonomie.'
    }</p>
${definitions.length ? `<details><summary>Définitions des dépenses</summary><ul>${definitions.map((d) => `<li>${h(d)}</li>`).join('')}</ul></details>` : ''}
${s ? sourceLien(s.titre, s.page, s.licence) : ''}`,
  )
}

/** Résidents des EHPAD : prix médians déclarés (sommes facturées aux résidents, pas une dépense publique). */
function blocResidents(idx: Index): string {
  const an = Object.keys(idx.totaux.prix_ehpad).sort().pop()
  const v = an ? idx.totaux.prix_ehpad[an] : null
  const s = idx.sources.cnsa_prix_ehpad
  if (!an || !v) return carte('fin-residents', 'Résidents des EHPAD', absent('Prix des EHPAD : donnée non disponible.'))
  const lignes: LigneFin[] = idx.colonnes_prix.slice(1).map((c, i) => ({
    nom: libellePrix(c),
    montant: typeof v[i + 1] === 'number' ? `${eur2(v[i + 1]!)} par jour` : 'non publié',
    quand: `médiane au 31/12/${an}`,
    statut: 'approche',
  }))
  return carte(
    'fin-residents',
    'Résidents des EHPAD',
    `<p>${h(idx.note_prix)}</p>
<p>Prix médians déclarés par ${h(entier(v[0] ?? 0))} EHPAD au 31 décembre ${h(an)}, toutes taxes comprises :</p>
${liste(lignes)}
<p class="aide">Médiane ${badgeCalcule('médiane des prix déclarés par les établissements pour la même année ; les valeurs hors bornes restent publiées pour l’établissement mais n’entrent pas dans la médiane')}</p>
${s ? sourceLien(s.titre, s.url, s.millesime ? plage(s.millesime) : undefined) : ''}`,
  )
}

/** Tableau d'un regroupement des comptes agrégés (catégorie, activité, secteur) pour une année. */
export function tableComptes(f: Finances, an: string, cle: 'categorie' | 'activite_principale' | 'secteur'): string {
  const i = (c: string) => f.colonnes.indexOf(c)
  const groupes = new Map<string, Record<string, number>>()
  for (const l of f.lignes) {
    if (String(l[i('annee')]) !== an) continue
    const g = texte(l[i(cle)])
    const acc = groupes.get(g) ?? {}
    for (const [m] of MESURES) {
      const v = nombre(l[i(m)])
      if (v !== null) acc[m] = (acc[m] ?? 0) + v
    }
    groupes.set(g, acc)
  }
  const nom = (g: string) => (cle === 'categorie' ? (CATEGORIES_ATIH[g] ?? g) : cle === 'activite_principale' ? (ACTIVITES[g] ?? g) : majuscule(g))
  const lignes = [...groupes.entries()].sort((a, b) => (b[1].produits_eur ?? 0) - (a[1].produits_eur ?? 0) || a[0].localeCompare(b[0], 'fr'))
  const titre = { categorie: 'catégorie', activite_principale: 'activité principale', secteur: 'secteur' }[cle]
  return `<div class="tableau-defile"><table><caption>Comptes ${h(an)} par ${titre}, en euros (ordre : produits décroissants)</caption><thead><tr><th scope="col">${majuscule(titre)}</th>${MESURES.map(
    ([, l]) => `<th scope="col" class="nombre">${h(l)}</th>`,
  ).join('')}</tr></thead><tbody>${lignes
    .map(
      ([g, v]) =>
        `<tr><th scope="row">${h(nom(g))}</th>${MESURES.map(([m]) => `<td class="nombre">${v[m] === undefined ? 'non publié' : h(m === 'etablissements' ? entier(v[m]) : eurLisible(v[m]))}</td>`).join('')}</tr>`,
    )
    .join('')}</tbody></table></div>`
}

function sectionComptes(f: Finances | null, fir: Lu | null, segur: { md: number; millesime: string } | null, idx: Index): string {
  const investissement = `<h3>Investissement</h3>
<div class="absent"><p>${badgeStatut('nonpub')} Les dépenses d’investissement des hôpitaux (bâtiments, équipements) ne figurent pas dans les comptes repris ici, ni par catégorie ni par établissement.</p>
${
  fir || segur
    ? `<p>Ce qui est publié au niveau national : ${[
        fir ? `le soutien à l’investissement, compté avec le fonds d’intervention régional dans les dépenses de l’assurance maladie (${h(md(fir.noeud.md))}, ${h(quand(fir.racine.millesime))})` : '',
        segur ? `la part « Ségur investissement » reversée par l’État à la Sécurité sociale (${h(md(segur.md))}, ${h(quand(segur.millesime))})` : '',
      ]
        .filter(Boolean)
        .join(' ; ')}.${fir && segur ? ' Ces deux montants ne s’additionnent pas.' : ''}</p>`
    : ''
}</div>`
  const hd = idx.sources.hospi_diag
  const parHopital = `<h3>Comptes de chaque hôpital</h3>
<p>Les comptes de chaque hôpital et de chaque clinique (produits, recettes de la tarification à l’activité, dotations pour missions d’intérêt général, charges, résultat, dette) sont publiés en données ouvertes pour les exercices ${h(plage(hd?.millesime ?? '2011-2015'))} ${badgeStatut('trace')}. Ils s’affichent dans la recherche ci-dessous.</p>
<p>${badgeStatut('nonpub')} Pour les exercices suivants, ils ne sont pas publiés en données ouvertes par établissement.</p>`
  if (!f) return `<h2>Les comptes des hôpitaux</h2>${absent('Comptes agrégés : donnée non disponible.')}${investissement}${parHopital}`
  const annees = Object.keys(f.totaux.par_annee).sort()
  const an = annees[annees.length - 1]
  const t = f.totaux.par_annee[an]
  const autres = t.charges_eur - t.charges_personnel_eur
  const partPersonnel = (t.charges_personnel_eur / t.charges_eur) * 100
  const nf1 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  return `<h2>Les comptes des hôpitaux publics et privés à but non lucratif</h2>
<p>L’Agence technique de l’information sur l’hospitalisation (ATIH) publie les comptes de ces hôpitaux regroupés par catégorie, sans nommer d’établissement. ${h(f.avertissement)} Ces comptes et les dépenses de l’assurance maladie plus haut ne couvrent pas le même champ : ils ne se comparent pas terme à terme.</p>
<ul class="cles" aria-label="Comptes ${h(an)} des hôpitaux publics et privés à but non lucratif">
  <li class="cle-famille"><strong>${h(eurLisible(t.produits_eur))}</strong> <span>de produits en ${h(an)}, pour ${h(entier(t.etablissements))} établissements</span> ${badgeStatut('trace')}</li>
  <li><strong>${h(eurLisible(t.charges_eur))}</strong> <span>de charges du compte principal, résultat de ce compte : ${h(eurLisible(t.resultat_principal_eur))}</span> ${badgeStatut('trace')}</li>
  <li><strong>${h(eurLisible(t.encours_dette_eur))}</strong> <span>de dette en cours en ${h(an)}</span> ${badgeStatut('trace')}</li>
</ul>
<p class="aide">Les produits et les charges n’ont pas le même périmètre dans la source : les produits sont le « ${h(f.definitions.produits_eur ?? 'total des produits')} », les charges celles du compte de résultat principal. Leur différence n’est donc pas un résultat : le résultat publié est donné à part.</p>
<h3>Sur 100 € de charges du compte principal en ${h(an)}</h3>
${billet(
  [
    { nom: 'Personnel', valeur: t.charges_personnel_eur, texte: `${nf1.format(partPersonnel)} €`, famille: 'secu', detail: eurLisible(t.charges_personnel_eur) },
    { nom: 'Autres charges', valeur: autres, texte: `${nf1.format(100 - partPersonnel)} €`, famille: 'papier', detail: eurLisible(autres) },
  ],
  { etiquette: `Sur 100 € de charges du compte principal des hôpitaux publics et privés à but non lucratif en ${an} : personnel et autres charges`, legendes: true },
)}
<p>Sur 100 € de charges du compte principal, ${h(sur100(partPersonnel))} sont des charges de personnel (${h(eurLisible(t.charges_personnel_eur))}) ${badgeStatut('trace')} et ${h(sur100(100 - partPersonnel))} d’autres charges (${h(eurLisible(autres))}) ${badgeCalcule('part = charges de personnel divisées par le total des charges du compte principal, autres charges = total moins charges de personnel, mêmes établissements et même année')}.</p>
<h3>De ${h(annees[0])} à ${h(an)}</h3>
<div class="tableau-defile"><table><caption>Comptes des hôpitaux publics et privés à but non lucratif, en euros</caption><thead><tr><th scope="col">Grandeur</th>${annees
    .map((a) => `<th scope="col" class="nombre">${h(a)}</th>`)
    .join('')}</tr></thead><tbody>${MESURES.map(
    ([m, l]) =>
      `<tr><th scope="row">${h(l)}</th>${annees
        .map((a) => {
          const v = f.totaux.par_annee[a]?.[m]
          return `<td class="nombre">${typeof v === 'number' ? h(m === 'etablissements' ? entier(v) : eurLisible(v)) : 'non publié'}</td>`
        })
        .join('')}</tr>`,
  ).join('')}</tbody></table></div>
<p class="aide">${h(majuscule(f.totaux.methode))}.</p>
<h3>Par catégorie, activité ou secteur</h3>
${segmente({ id: 'hop-groupe', etiquette: 'Regrouper les comptes', options: [{ valeur: 'categorie', libelle: 'Par catégorie' }, { valeur: 'activite_principale', libelle: 'Par activité' }, { valeur: 'secteur', libelle: 'Par secteur' }], valeur: 'categorie' })}
${choix({ id: 'hop-annee', etiquette: 'Année des comptes', options: [...annees].reverse().map((a) => ({ valeur: a, libelle: a })), valeur: an })}
<div id="hop-groupes">${tableComptes(f, an, 'categorie')}</div>
<p class="aide">Catégories et tranches de taille (en millions d’euros) définies par l’ATIH. Activité principale : au moins 80 % de l’activité de l’établissement.</p>
<details><summary>Définitions de l’ATIH</summary><ul>${Object.entries(f.definitions)
    .map(([k, v]) => `<li><strong>${h(MESURES.find(([m]) => m === k)?.[1] ?? (k === 'activite_principale' ? 'Activité principale' : k))}</strong> : ${h(v)}</li>`)
    .join('')}</ul></details>
${sourceLien(f.source, undefined, f.millesime)}
${investissement}
${parHopital}`
}

/** Comptes Hospi Diag d'un établissement (ou de son entité juridique), années en colonnes. */
export function tableHospiDiag(nom: string, lignes: Record<string, Valeur>[], hd: HospiDiag, entite: boolean): string {
  const tri = [...lignes].sort((a, b) => Number(a.annee) - Number(b.annee))
  const refs = [...new Set(tri.map((l) => texte(l.referentiel)))].map((r) => REFERENTIELS[r] ?? 'référentiel non renseigné')
  return `<div class="tableau-defile"><table><caption>${h(nom)} : comptes publiés, en euros (${h(refs.join(', '))})</caption><thead><tr><th scope="col">Grandeur</th>${tri
    .map((l) => `<th scope="col" class="nombre">${h(texte(l.annee))}</th>`)
    .join('')}</tr></thead><tbody>${HD_MESURES.map(
    ([m, lib]) => `<tr><th scope="row">${h(lib)}</th>${tri.map((l) => `<td class="nombre">${nombre(l[m]) === null ? 'non publié' : h(eurLisible(nombre(l[m])!))}</td>`).join('')}</tr>`,
  ).join('')}</tbody></table></div>
<p>${badgeStatut('trace')} ${entite ? 'Comptes de l’entité juridique, tous ses sites compris. ' : ''}${h(hd.avertissement)}</p>
<details><summary>Définitions de Hospi Diag</summary><ul>${HD_MESURES.map(([m, lib]) => (hd.definitions[m] ? `<li><strong>${h(lib)}</strong> : ${h(hd.definitions[m])}</li>` : '')).join('')}${
    hd.definitions.referentiel ? `<li>${h(hd.definitions.referentiel)}</li>` : ''
  }</ul></details>
${sourceLien(hd.source, undefined, hd.millesime)}`
}

function tableDepartements(deps: Departements): string {
  const c = (n: string) => deps.colonnes.indexOf(n)
  const anCcam = deps.annees_ccam[deps.annees_ccam.length - 1]
  const anPrix = Object.keys(Object.values(deps.departements)[0]?.prix_ehpad ?? {})
    .sort()
    .pop()
  const iPrix = deps.colonnes_prix.indexOf('prix_hebergement_chambre_seule_median_eur')
  const val = (x: number | null | undefined, f: (n: number) => string) => (typeof x === 'number' ? h(f(x)) : 'non publié')
  return `<details><summary>Tous les départements en tableau</summary><div class="tableau-defile"><table><caption>Établissements par département (ordre : code du département)</caption><thead><tr><th scope="col">Département</th><th scope="col" class="nombre">Établissements actifs</th><th scope="col" class="nombre">Loi hospitalière</th><th scope="col" class="nombre">EHPAD</th><th scope="col" class="nombre">Listés par leur nom</th><th scope="col" class="nombre">Actes médicaux publiés en ${h(
    String(anCcam),
  )}</th><th scope="col" class="nombre">Prix médian d’hébergement en EHPAD au 31/12/${h(anPrix ?? '')}</th></tr></thead><tbody>${Object.keys(deps.departements)
    .sort()
    .map((k) => {
      const d = deps.departements[k]
      const prix = anPrix ? d.prix_ehpad[anPrix]?.[iPrix] : null
      return `<tr><th scope="row">${h(nomDep(k))}</th><td class="nombre">${val(d.comptes[c('etablissements')], entier)}</td><td class="nombre">${val(d.comptes[c('hospitalier')], entier)}</td><td class="nombre">${val(
        d.comptes[c('ehpad')],
        entier,
      )}</td><td class="nombre">${h(entier(d.etablissements_nommes))}</td><td class="nombre">${val(d.actes_ccam[d.actes_ccam.length - 1], entier)}</td><td class="nombre">${val(prix, eur2)}</td></tr>`
    })
    .join('')}</tbody></table></div><p class="aide">${h(deps.note)} Source OpenCCAM, ${h(deps.annees_ccam.join(', '))}, https://www.scansante.fr/</p></details>`
}

function sectionRecherche(idx: Index, deps: Departements | null, depInitial: string, qInitial: string): string {
  const c = (n: string) => idx.colonnes.indexOf(n)
  const total = idx.totaux.comptes[c('etablissements')]
  const domaines = idx.domaines.map((d) => ({ nom: d.libelle, n: idx.totaux.comptes[c(d.id)] }))
  const secteurs = idx.secteurs.map((s) => ({ nom: s.libelle, n: idx.totaux.comptes[c(s.id)] }))
  const nomSource = (k: string) => idx.sources[k]?.titre.split(/ : | \(|, données| au \d{2}\/\d{2}\/\d{4}/)[0] ?? k
  return `<h2>Chercher un établissement</h2>
<p>Le fichier national des établissements sanitaires et sociaux (FINESS) compte <strong>${h(entier(total))}</strong> établissements actifs dans le périmètre retenu, au ${h(
    dateFr(idx.sources.finess_structures?.millesime ?? idx.collecte_le),
  )}. ${h(entier(idx.totaux.etablissements_nommes))} sont listés par leur nom : hôpitaux, cliniques, autres établissements relevant de la loi hospitalière, EHPAD et établissements ayant une activité ou un prix publié. Les autres sont comptés sans être nommés.</p>
<p class="aide">${h(idx.regle_personnes)} ${h(idx.perimetre)}</p>
<form id="hop-form" class="carte" role="search" aria-label="Chercher un établissement">
  ${listeRecherche({ id: 'hop-dep', etiquette: 'Département', options: [], optionsHtml: `<option value="">Toute la France : hôpitaux et cliniques dont les comptes ${h(plage(idx.sources.hospi_diag?.millesime ?? '2011-2015'))} sont publiés</option>${
    deps
      ? Object.keys(deps.departements)
          .sort()
          .map((k) => `<option value="${h(k)}"${k === depInitial ? ' selected' : ''}>${h(k)} ${h(NOMS_DEP.get(k) ?? '')}</option>`)
          .join('')
      : ''
  }` })}
  <label for="hop-q">Nom, commune ou numéro FINESS</label>
  <input id="hop-q" type="search" autocomplete="off" value="${h(qInitial)}" />
  ${choix({ id: 'hop-type', etiquette: 'Type d’établissement (dans un département)', options: [{ valeur: '', libelle: 'Tous les établissements listés' }, { valeur: 'hospitalier', libelle: 'Hôpitaux, cliniques et autres établissements de la loi hospitalière' }, { valeur: 'ehpad', libelle: 'EHPAD' }], valeur: '' })}
</form>
<p id="hop-statut" class="aide" aria-live="polite"></p>
<div id="hop-resultats"><p>Choisis un département pour voir ses établissements, ou écris au moins trois lettres du nom d’un hôpital ou d’une clinique pour chercher dans toute la France.</p></div>
${deps ? tableDepartements(deps) : ''}
<details><summary>Établissements actifs par domaine et par secteur, France entière</summary><div class="tableau-defile"><table><caption>Établissements actifs du périmètre, FINESS au ${h(
    dateFr(idx.sources.finess_structures?.millesime ?? idx.collecte_le),
  )}</caption><thead><tr><th scope="col">Domaine ou secteur</th><th scope="col" class="nombre">Établissements</th></tr></thead><tbody>${[...domaines, ...secteurs, { nom: 'dont EHPAD', n: idx.totaux.comptes[c('ehpad')] }]
    .map((x) => `<tr><th scope="row">${h(x.nom)}</th><td class="nombre">${typeof x.n === 'number' ? h(entier(x.n)) : 'non publié'}</td></tr>`)
    .join('')}</tbody></table></div><p class="aide">Les domaines suivent le premier chiffre de la catégorie FINESS ; les secteurs regroupent les statuts juridiques des gestionnaires.</p></details>
<details><summary>Écarts entre sources</summary><ul>${idx.ecarts
    .map(
      (e) =>
        `<li><strong>${h(majuscule(e.objet))}</strong> : ${h(entier(e.nombre))} selon ${h(nomSource(e.source))} (${h(dateFr(e.date))}), ${h(entier(e.autre_nombre))} selon ${h(nomSource(e.autre_source))} (${h(
          dateFr(e.autre_date),
        )}), écart de ${h(entier(e.ecart))}. ${h(majuscule(e.lecture_ecart))}</li>`,
    )
    .join('')}</ul><p class="aide">Les écarts sont publiés tels quels : aucune des deux sources n’est retenue contre l’autre.</p></details>`
}

interface Etab {
  r: Record<string, Valeur>
  cherche: string
  domaine: string
}
interface EntreeHD {
  finess: string
  nom: string
  departement: string
  categorie: string
  lignes: Record<string, Valeur>[]
  cherche: string
}

function ficheEtab(e: Etab, d: Departement, idx: Index, deps: Departements, fir: Map<string, { montant_eur: number; conventions: number }>, firInfo: Fir | null, categories: Map<string, string>, secteurs: Map<string, string>): string {
  const r = e.r
  const anneesCcam = deps.annees_ccam.filter((a) => `actes_ccam_${a}` in r)
  const actes = anneesCcam.map((a) => nombre(r[`actes_ccam_${a}`]))
  const prix = Object.keys(PRIX).map((k) => [k, nombre(r[`${k}_eur`])] as const)
  const f = fir.get(texte(r.siren))
  const cat = texte(r.categorie)
  return `<p>Gestionnaire : <strong>${h(texte(r.entite_juridique))}</strong> (numéro SIREN ${h(texte(r.siren))}, numéro FINESS juridique ${h(texte(r.finess_entite_juridique))}).</p>
<p>Catégorie : ${h(categories.get(cat) ?? cat)} · secteur ${h(secteurs.get(texte(r.secteur)) ?? texte(r.secteur))} · numéro FINESS ${h(texte(r.finess))}.</p>
${
  actes.some((x) => x !== null)
    ? `<div class="tableau-defile"><table><caption>Actes médicaux publiés (minimum : les lignes de moins de 11 séjours sont absentes de la source)</caption><thead><tr><th scope="col">Année</th>${anneesCcam
        .map((a) => `<th scope="col" class="nombre">${a}</th>`)
        .join('')}</tr></thead><tbody><tr><th scope="row">Actes</th>${actes.map((x) => `<td class="nombre">${x === null ? 'non publié' : h(entier(x))}</td>`).join('')}</tr></tbody></table></div>
<p class="source sans-prefixe">Source OpenCCAM, ${h(anneesCcam.join(', '))}, <a href="https://www.scansante.fr/" rel="noopener noreferrer">https://www.scansante.fr/</a></p>`
    : ''
}
${
  prix.some(([, v]) => v !== null)
    ? `<div class="tableau-defile"><table><caption>Prix déclarés${r.prix_declares_le ? ` le ${h(dateFr(texte(r.prix_declares_le)))}` : ''}, situation au 31/12/${h(String(d.etablissements.annee_prix))}, euros par jour</caption><thead><tr><th scope="col">Prix</th><th scope="col" class="nombre">Euros par jour</th></tr></thead><tbody>${prix
        .map(([k, v]) => `<tr><th scope="row">${h(PRIX[k])}</th><td class="nombre">${v === null ? 'non déclaré' : h(eur2(v))}</td></tr>`)
        .join('')}</tbody></table></div>
<p class="aide">${badgeStatut('trace')} Valeurs déclarées par l’établissement : sommes facturées aux résidents, pas une dépense publique.</p>${idx.sources.cnsa_prix_ehpad ? sourceLien(idx.sources.cnsa_prix_ehpad.titre, idx.sources.cnsa_prix_ehpad.url) : ''}`
    : ''
}
${
  f && firInfo
    ? `<p>Subventions du fonds d’intervention régional des Pays de la Loire reçues par le gestionnaire en ${h(annee(firInfo.millesime))} : <strong>${h(eurLisible(f.montant_eur))}</strong> (${h(entier(f.conventions))} conventions) ${badgeStatut(
        'trace',
      )}. Montant du gestionnaire, tous ses établissements compris.</p>${sourceLien(firInfo.attribuant, undefined, firInfo.millesime)}`
    : ''
}
${
  e.domaine === 'hospitalier'
    ? `<p><button type="button" class="bouton" data-hd="${h(texte(r.finess))}" data-ej="${h(texte(r.finess_entite_juridique))}">Chercher ses comptes publiés de ${h(plage(idx.sources.hospi_diag?.millesime ?? '2011-2015'))}</button></p><div class="hd-zone"></div>`
    : ''
}
<p class="aide">${badgeStatut('nonpub')} Ce que l’établissement reçoit de l’assurance maladie, de l’État ou des collectivités depuis 2016 n’est pas publié en données ouvertes${
    firInfo && !f ? ' ; les subventions du fonds d’intervention régional sont publiées par une seule agence régionale de santé (Pays de la Loire), dont le site reprend les principaux bénéficiaires' : ''
  }.</p>`
}

function resumeDepartement(code: string, d: ResumeDep, dep: Departement, idx: Index, deps: Departements): string {
  const c = (n: string) => deps.colonnes.indexOf(n)
  const v = (n: string) => d.comptes[c(n)]
  const n = (x: number | null | undefined) => (typeof x === 'number' ? entier(x) : 'non publié')
  const anCcam = deps.annees_ccam[deps.annees_ccam.length - 1]
  const actes = d.actes_ccam[d.actes_ccam.length - 1]
  const anPrix = Object.keys(d.prix_ehpad).sort().pop()
  const iPrix = deps.colonnes_prix.indexOf('prix_hebergement_chambre_seule_median_eur')
  const prix = anPrix ? d.prix_ehpad[anPrix] : null
  const national = anPrix ? idx.totaux.prix_ehpad[anPrix]?.[idx.colonnes_prix.indexOf('prix_hebergement_chambre_seule_median_eur')] : null
  const sec = (id: string) => (idx.secteurs.find((s) => s.id === id)?.libelle ?? id).split(' (')[0].toLowerCase()
  const motifs = Object.entries(dep.non_nommes.par_motif ?? {})
  return `<section class="carte" aria-labelledby="hop-dep-titre"><h3 id="hop-dep-titre">${h(nomDep(code))}</h3><ul>
<li>${h(n(v('etablissements')))} établissements actifs du périmètre, dont ${h(n(v('hospitalier')))} relevant de la loi hospitalière et ${h(n(v('ehpad')))} EHPAD.</li>
<li>Secteur du gestionnaire : ${['public', 'prive_non_lucratif', 'prive_commercial'].map((id) => `${h(sec(id))} ${h(n(v(id)))}`).join(', ')}.</li>
<li>Actes médicaux publiés en ${h(String(anCcam))} : ${typeof actes === 'number' ? `${h(entier(actes))} (minimum publié ; source OpenCCAM, ${h(String(anCcam))}, https://www.scansante.fr/)` : 'non publié'}.</li>
${
  prix && anPrix
    ? `<li>Prix médian d’hébergement en EHPAD, chambre seule, au 31/12/${h(anPrix)} : ${typeof prix[iPrix] === 'number' ? `${h(eur2(prix[iPrix]!))} par jour` : 'non publié'} (${h(n(prix[0]))} EHPAD avec un prix déclaré)${
        typeof national === 'number' ? ` ; France entière : ${h(eur2(national))}` : ''
      } ${badgeStatut('approche')}</li>`
    : ''
}
<li>${h(entier(d.etablissements_nommes))} établissements listés par leur nom${
    dep.non_nommes.total ? ` ; ${h(entier(dep.non_nommes.total))} comptés sans être nommés (${motifs.map(([m, x]) => `${h(entier(x))} pour le motif « ${h(motifConfidentialite(m, idx))} »`).join(' ; ')})` : ''
  }.</li>
</ul>${sourceLien(dep.source, undefined, dep.millesime)}</section>`
}
const motifConfidentialite = (m: string, idx: Index) => idx.confidentialite?.motifs?.[m] ?? m

function sectionLimites(lim: Limites | null): string {
  if (!lim) return ''
  return `<h2>Ce qui n’est pas publié</h2>
<p>${h(lim.avertissement)}</p>
<ul class="lignes">${lim.non_ouvert
    .map((x) => `<li><span>${h(x.sujet)}</span> <span class="dest">${/^non publi/i.test(x.etat) ? traitStatut('nonpub') : `${badgeStatut('nonpub')} `}${h(majuscule(x.etat))}. Ce qui existe : ${h(sansRenvoisTechniques(x.ce_qui_existe))}</span></li>`)
    .join('')}</ul>
<details><summary>Limites des données</summary><ul>${lim.limites.map((l) => `<li>${h(sansRenvoisTechniques(l))}</li>`).join('')}</ul></details>`
}

function sectionSources(idx: Index): string {
  return `<h2>Sources</h2>
<details><summary>Les jeux de données de cette page</summary><ul>${Object.values(idx.sources)
    .map(
      (s) =>
        `<li><a href="${h(s.url)}" rel="noopener noreferrer">${h(s.titre)}</a>${s.producteur ? `, ${h(s.producteur)}` : ''} (${h(plage(dateFr(s.millesime ?? '')))}, ${h(s.licence)})${s.mention_obligatoire ? `. Mention : ${h(s.mention_obligatoire)}` : ''}</li>`,
    )
    .join('')}</ul>${
    idx.recherche_publique ? `<p class="aide">Recherche préalable du projet (${h(dateFr(idx.recherche_publique.date))}) : ${h(idx.recherche_publique.verdict)}.</p>` : ''
  }<p class="aide">${h(majuscule(idx.regle_liens))}</p></details>
<details><summary>Les sigles de cette page</summary><ul>${SIGLES.map(([s, d]) => `<li><strong>${s}</strong> : ${h(d)}</li>`).join('')}</ul></details>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const [idx, fin, lim, deps] = await Promise.all([
    chargerSiPresent<Index>('sante_etablissements/index.json'),
    chargerSiPresent<Finances>('sante_etablissements/finances_agregees.json'),
    chargerSiPresent<Limites>('sante_etablissements/limites.json'),
    chargerSiPresent<Departements>('sante_etablissements/departements.json'),
  ])
  if (!idx) {
    cible.innerHTML =
      enCours('Les hôpitaux et établissements de santé', 'Qui finance les hôpitaux, cliniques et EHPAD, leurs comptes publiés et la recherche d’un établissement par nom ou par département.') +
      `<ul class="liens-sortie"><li><a href="#/explorer/secu">Les dépenses de la Sécurité sociale</a></li></ul>` +
      partPersonnelle()
    return
  }
  const fichierFir = idx.liens.find((l) => l.vue === 'subventions')?.fichier
  const firInfo = fichierFir ? await chargerSiPresent<Fir>(fichierFir) : null
  const [secu, etat, departements] = await Promise.all([blocsSecu(idx, firInfo), blocEtat(), blocDepartements()])
  const cle = secu.cle
  const depInitial = deps && params.get('dep') && deps.departements[params.get('dep')!] ? params.get('dep')! : ''
  const qInitial = (params.get('q') ?? '').slice(0, 80)

  cible.innerHTML = `
<h1>Les hôpitaux et établissements de santé</h1>
<p class="chapeau">Hôpitaux, cliniques, EHPAD (maisons de retraite médicalisées) : cette page montre qui leur verse de l’argent public (assurance maladie, branche autonomie de la Sécurité sociale, État, départements), ce que paient les résidents des EHPAD et les comptes publiés des hôpitaux publics et privés à but non lucratif. Tu peux aussi chercher un établissement par son nom ou son département.</p>
<p class="chapeau">Elle ne montre pas ce que reçoit chaque établissement depuis 2016 : ces montants ne sont pas publiés en données ouvertes. Elle ne contient aucune donnée sur les patients et ne nomme aucun membre du personnel.</p>
${
  cle
    ? `<div class="carte" data-cle>
  <p class="grand-chiffre">${surligne(md(cle.noeud.md))}</p>
  <p class="sous-chiffre">${annee(cle.racine.millesime) ? `dépensés en ${h(annee(cle.racine.millesime))}` : h(cle.racine.millesime ?? '')} par l’assurance maladie pour les ${h(cle.noeud.nom.replace(/^ONDAM\s*:\s*/, ''))}, soit ${h(
        sur100((cle.noeud.md / cle.parent.md) * 100),
      )} sur 100 € dépensés par « ${h(cle.parent.nom)} » (${h(md(cle.parent.md))}).</p>
  <p>${badgeStatut(statutNoeud(cle.noeud))} Montant national publié dans les comptes de la Sécurité sociale ; la part de chaque établissement n’est pas publiée.</p>
  ${(cle.noeud.sources ?? [])
    .map((k) => cle.racine.sources_detail?.[k])
    .filter((s): s is { titre: string; url: string; millesime: string } => !!s)
    .map((s) => sourceLien(s.titre, s.url, s.millesime))
    .join('')}
</div>`
    : ''
}
<h2>Qui finance les hôpitaux et les établissements</h2>
<p>Chaque financeur a ses propres comptes, et une partie de l’argent passe de l’un à l’autre : les montants ci-dessous se lisent côte à côte, ils ne s’additionnent pas.</p>
${lireLesMotifs()}
<div class="grille-2">
${secu.cartes.join('\n')}
${etat.carte}
${departements}
${blocResidents(idx)}
</div>
${absent(
  `Par établissement : ce que chacun reçoit de ces financeurs depuis 2016 n’est pas publié en données ouvertes.${
    firInfo ? ' Les subventions du fonds d’intervention régional des Pays de la Loire font exception : elles s’affichent dans la fiche du gestionnaire, dans la recherche.' : ''
  }`,
)}
${sectionComptes(fin, secu.fir, etat.segur, idx)}
${sectionRecherche(idx, deps, depInitial, qInitial)}
${sectionLimites(lim)}
${sectionSources(idx)}
${repliTerritoire('pathologies', 'Patients par pathologie, par département', 'Diabète et cancers (Assurance maladie)')}
<ul class="liens-sortie"><li><a href="#/explorer/secu">Toutes les dépenses de la Sécurité sociale</a></li><li><a href="#/explorer/operateurs">Les agences régionales de santé parmi les opérateurs de l’État</a></li></ul>
${partPersonnelle()}`

  brancherTerritoire(cible, 'pathologies')
  brancherComptes(cible, fin)
  return { suite: brancherRecherche(cible, idx, deps, firInfo, depInitial, qInitial) }
}

function brancherComptes(cible: HTMLElement, f: Finances | null) {
  const zone = cible.querySelector<HTMLElement>('#hop-groupes')
  const choixAnnee = cible.querySelector<HTMLElement>('#hop-annee')
  if (!f || !zone || !choixAnnee) return
  const dessiner = () => (zone.innerHTML = tableComptes(f, valeurChoix(cible, 'hop-annee'), valeurChoix(cible, 'hop-groupe') as 'categorie' | 'activite_principale' | 'secteur'))
  cible.querySelector('#hop-groupe')?.addEventListener('change', dessiner)
  choixAnnee.addEventListener('change', dessiner)
}

async function brancherRecherche(cible: HTMLElement, idx: Index, deps: Departements | null, firInfo: Fir | null, depInitial: string, qInitial: string): Promise<void> {
  const form = cible.querySelector<HTMLFormElement>('#hop-form')
  const zone = cible.querySelector<HTMLElement>('#hop-resultats')
  const statut = cible.querySelector<HTMLElement>('#hop-statut')
  if (!form || !zone || !statut) return
  const categories = new Map(idx.categories.filter((c) => c.code).map((c) => [c.code!, c.libelle ?? c.code!]))
  const domaines = new Map(idx.categories.filter((c) => c.code).map((c) => [c.code!, c.domaine]))
  const secteurs = new Map(idx.secteurs.map((s) => [s.id, s.libelle.split(' (')[0].toLowerCase()]))
  const fir = new Map((firInfo?.beneficiaires?.top ?? []).map((b) => [b.siren, b]))
  const cheminHD = String(idx.fichiers.hospi_diag ?? 'sante_etablissements/hospi_diag.json')
  let hd: HospiDiag | null = null
  let entreesHD: EntreeHD[] | null = null
  const chargerHD = async () => {
    if (!hd) {
      hd = await chargerSiPresent<HospiDiag>(cheminHD)
      if (hd) {
        const parFiness = new Map<string, EntreeHD>()
        for (const l of hd.lignes) {
          const r = enObjet(hd.colonnes, l)
          const k = texte(r.finess)
          const e = parFiness.get(k) ?? { finess: k, nom: '', departement: '', categorie: '', lignes: [], cherche: '' }
          e.lignes.push(r)
          if (r.nom) e.nom = texte(r.nom)
          if (r.departement) e.departement = texte(r.departement)
          if (r.categorie) e.categorie = texte(r.categorie)
          parFiness.set(k, e)
        }
        entreesHD = [...parFiness.values()].map((e) => ({ ...e, cherche: normaliser(`${e.nom} ${e.finess}`) })).sort((a, b) => normaliser(a.nom).localeCompare(normaliser(b.nom), 'fr') || a.finess.localeCompare(b.finess))
      }
    }
    return hd
  }
  const etat = { dep: depInitial, q: qInitial, type: '', page: 1 }
  let jeton = 0
  const fichiers = new Map<string, Departement | null>()

  const dessiner = async () => {
    const moi = ++jeton
    const q = normaliser(etat.q)
    const mots = q ? q.split(' ') : []
    if (etat.dep && deps) {
      const resume = deps.departements[etat.dep]
      if (!fichiers.has(etat.dep)) fichiers.set(etat.dep, await chargerSiPresent<Departement>(resume.fichier))
      const d = fichiers.get(etat.dep)
      if (moi !== jeton) return
      if (!d) {
        zone.innerHTML = absent('Pas de données pour ce département.')
        statut.textContent = ''
        return
      }
      const communes = new Map(d.communes.lignes.map((l) => [texte(l[d.communes.colonnes.indexOf('code')]), nomVille(texte(l[d.communes.colonnes.indexOf('nom')]))]))
      const tous: Etab[] = d.etablissements.lignes.map((l) => {
        const r = enObjet(d.etablissements.colonnes, l)
        return {
          r,
          domaine: domaines.get(texte(r.categorie)) ?? '',
          cherche: normaliser(`${texte(r.nom)} ${texte(r.entite_juridique)} ${communes.get(texte(r.commune)) ?? ''} ${texte(r.finess)} ${texte(r.finess_entite_juridique)} ${texte(r.siren)}`),
        }
      })
      const liste = tous.filter(
        (e) => (!etat.type || (etat.type === 'ehpad' ? texte(e.r.categorie) === '500' : e.domaine === etat.type)) && mots.every((m) => e.cherche.includes(m)),
      )
      const visibles = liste.slice(0, etat.page * PAR_PAGE)
      const anCcam = deps.annees_ccam[deps.annees_ccam.length - 1]
      statut.textContent = `${entier(liste.length)} établissement${liste.length > 1 ? 's' : ''} sur ${entier(tous.length)} listés dans ce département. Ordre de la liste : ${d.etablissements.ordre}.`
      zone.innerHTML = `${resumeDepartement(etat.dep, resume, d, idx, deps)}${
        liste.length
          ? `<ul class="lignes">${visibles
              .map((e, i) => {
                const actes = nombre(e.r[`actes_ccam_${anCcam}`])
                const prix = nombre(e.r.prix_hebergement_chambre_seule_eur)
                const cat = texte(e.r.categorie)
                return `<li><details data-i="${i}"><summary>${h(texte(e.r.nom))}</summary><div class="fiche"></div></details> <span class="dest">${h(communes.get(texte(e.r.commune)) ?? texte(e.r.commune))} · ${h(categories.get(cat) ?? cat)} · ${h(
                  secteurs.get(texte(e.r.secteur)) ?? texte(e.r.secteur),
                )}${actes !== null ? ` · ${h(entier(actes))} actes médicaux publiés en ${anCcam}` : ''}${prix !== null ? ` · hébergement déclaré à ${h(eur2(prix))} par jour` : ''}</span></li>`
              })
              .join('')}</ul>${liste.length > visibles.length ? `<button type="button" class="bouton" id="hop-plus">Afficher ${Math.min(PAR_PAGE, liste.length - visibles.length)} de plus</button>` : ''}`
          : absent('Aucun établissement listé ne correspond dans ce département.')
      }`
      zone.querySelectorAll<HTMLDetailsElement>('details[data-i]').forEach((x) =>
        x.addEventListener('toggle', () => {
          const fz = x.querySelector<HTMLElement>('.fiche')!
          if (!x.open || fz.innerHTML) return
          fz.innerHTML = ficheEtab(visibles[Number(x.dataset.i)], d, idx, deps, fir, firInfo, categories, secteurs)
          fz.querySelector<HTMLButtonElement>('[data-hd]')?.addEventListener('click', async (ev) => {
            const b = ev.currentTarget as HTMLButtonElement
            const cibleHD = fz.querySelector<HTMLElement>('.hd-zone')!
            b.disabled = true
            const h2 = await chargerHD()
            const ids = [b.dataset.hd ?? '', b.dataset.ej ?? '']
            const trouves = (entreesHD ?? []).filter((x2) => ids.includes(x2.finess))
            cibleHD.innerHTML =
              h2 && trouves.length
                ? trouves.map((t) => tableHospiDiag(t.nom, t.lignes, h2, t.finess !== ids[0])).join('')
                : absent(`Aucun compte publié pour cet établissement ni pour son entité juridique dans Hospi Diag (${plage(idx.sources.hospi_diag?.millesime ?? '2011-2015')}).`)
            b.remove()
          })
        }),
      )
      zone.querySelector('#hop-plus')?.addEventListener('click', () => plus('i'))
      return
    }
    if (q.length < 3) {
      statut.textContent = ''
      zone.innerHTML = `<p>Choisis un département pour voir ses établissements, ou écris au moins trois lettres du nom d’un hôpital ou d’une clinique pour chercher dans toute la France.</p>`
      return
    }
    const h2 = await chargerHD()
    if (moi !== jeton) return
    if (!h2 || !entreesHD) {
      statut.textContent = ''
      zone.innerHTML = absent('Comptes par établissement : donnée non disponible. Choisis un département pour voir ses établissements.')
      return
    }
    const liste = entreesHD.filter((e) => mots.every((m) => e.cherche.includes(m)))
    const visibles = liste.slice(0, etat.page * PAR_PAGE)
    statut.textContent = `${entier(liste.length)} hôpita${liste.length > 1 ? 'ux' : 'l'} ou clinique${liste.length > 1 ? 's' : ''} dont les comptes ${plage(idx.sources.hospi_diag?.millesime ?? '2011-2015')} sont publiés. Ordre de la liste : nom, alphabétique.`
    zone.innerHTML = liste.length
      ? `<p class="aide">Toute la France : la recherche porte sur les hôpitaux et cliniques présents dans Hospi Diag. Pour un EHPAD ou un autre établissement, choisis d’abord son département.</p><ul class="lignes">${visibles
          .map(
            (e, i) =>
              `<li><details data-j="${i}"><summary>${h(e.nom)}</summary><div class="fiche"></div></details> <span class="dest">${h(e.departement ? nomDep(e.departement) : 'département non renseigné')} · ${h(
                HD_CATEGORIES[e.categorie] ?? e.categorie,
              )}</span></li>`,
          )
          .join('')}</ul>${liste.length > visibles.length ? `<button type="button" class="bouton" id="hop-plus">Afficher ${Math.min(PAR_PAGE, liste.length - visibles.length)} de plus</button>` : ''}`
      : absent('Aucun hôpital ni aucune clinique de Hospi Diag ne correspond. Pour un EHPAD ou un autre établissement, choisis d’abord son département.')
    zone.querySelectorAll<HTMLDetailsElement>('details[data-j]').forEach((x) =>
      x.addEventListener('toggle', () => {
        const fz = x.querySelector<HTMLElement>('.fiche')!
        if (!x.open || fz.innerHTML) return
        const e = visibles[Number(x.dataset.j)]
        fz.innerHTML = `${tableHospiDiag(e.nom, e.lignes, h2, false)}${
          deps && deps.departements[e.departement]
            ? `<p><button type="button" class="bouton" data-voir="${h(e.departement)}" data-finess="${h(e.finess)}">Voir cet établissement dans ${h(nomDep(e.departement))}</button></p>`
            : ''
        }`
        fz.querySelector<HTMLButtonElement>('[data-voir]')?.addEventListener('click', (ev) => {
          const b = ev.currentTarget as HTMLButtonElement
          etat.dep = b.dataset.voir ?? ''
          etat.q = b.dataset.finess ?? ''
          etat.page = 1
          ;(form.querySelector('#hop-dep') as HTMLSelectElement).value = etat.dep
          ;(form.querySelector('#hop-q') as HTMLInputElement).value = etat.q
          void dessiner().then(() => {
            // Le résultat remplace la liste : le focus va au titre du département, pour ne pas le perdre.
            const t = zone.querySelector<HTMLElement>('#hop-dep-titre')
            if (t) {
              t.tabIndex = -1
              t.focus()
            }
          })
        })
      }),
    )
    zone.querySelector('#hop-plus')?.addEventListener('click', () => plus('j'))
  }
  // « Afficher plus » : la liste est redessinée, le focus va au premier établissement ajouté.
  const plus = (cle: 'i' | 'j') => {
    const premier = etat.page * PAR_PAGE
    etat.page += 1
    void dessiner().then(() => zone.querySelector<HTMLElement>(`details[data-${cle}="${premier}"] summary`)?.focus())
  }

  form.addEventListener('submit', (e) => e.preventDefault())
  form.addEventListener('input', (e) => {
    if ((e.target as HTMLElement).matches('.choix-filtre')) return
    etat.dep = (form.querySelector('#hop-dep') as HTMLSelectElement).value
    etat.q = (form.querySelector('#hop-q') as HTMLInputElement).value
    etat.type = valeurChoix(form, 'hop-type')
    etat.page = 1
    void dessiner()
  })
  if (etat.dep || normaliser(etat.q).length >= 3) await dessiner()
}

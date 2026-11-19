// Fonds européens en France (site/data/fonds_europeens/) : ce que l'Union finance en France par ses fonds structurels
// et d'investissement (FEDER, FSE, FSE+, IEJ, FTJ, FEADER hors aides individuelles de la PAC, FEAMP, FEAMPA) et la
// facilité pour la reprise et la résilience (Eurostat). Montants prévus, décidés, dépensés et payés par période,
// cofinancement national, régions, thèmes, années, et recherche dans six listes régionales d'opérations chargées à la
// demande. Ce que la France verse au budget de l'Union est sur /explorer/ue : les deux pages se renvoient l'une à
// l'autre, rien n'est additionné ni compensé, aucun solde n'est calculé ici.
// Prévu, décidé, dépensé et payé se lisent côte à côte, jamais additionnés ni rapportés l'un à l'autre en taux.
// null = non publié (jamais 0). Aucun classement par montant : fonds dans l'ordre publié, régions par code Insee,
// opérations par ordre alphabétique. Seules les personnes morales sont nommées (règle appliquée par le pipeline).
import { choix, listeRecherche, valeurChoix } from '../composants/choix'
import { partPersonnelle } from '../composants/hub'
import { encadreManque, MANQUES } from '../composants/manque'
import { charger, chargerSiPresent, DonneeAbsente } from '../donnees'
import type { Rendu } from '../routeur'
import { absent, appliquerLargeurs, badgeStatut, barres, entier, eurLisible, h, legendeStatuts, pct, source, sur100, surligne, badgeCalcule } from '../util'

// ---------- Formats des fichiers lus (seuls les champs utilisés) ----------
export interface Bloc {
  prevu_ue_eur: number | null
  prevu_national_eur?: number | null
  prevu_total_eur: number | null
  decide_eur: number | null
  depense_eur: number | null
  paye_ue_eur?: number | null
}
interface Fonds {
  code: string
  libelle: string
}
interface TotalPeriode {
  periode: string
  par_fonds: Record<string, Bloc>
  total: Bloc
  date_execution: string | null
  annee_paiements: number | null
}
interface Ecart {
  periode: string
  fonds: string
  grandeur: string
  source: string
  montant_eur: number | null
  autre_source: string
  autre_montant_eur: number | null
  ecart_eur: number | null
  lecture_ecart: string
}
interface SourceFe {
  id: string
  titre: string
  producteur: string
  url: string
  licence: string
  mise_a_jour_source?: string | null
  collecte_le?: string | null
}
interface Inaccessible {
  source: string
  url?: string
  constat: string
  effet?: string
}
export interface Index {
  millesime: string
  source: string
  collecte_le?: string
  fonds: Fonds[]
  definitions: Record<string, string>
  perimetre: {
    hors_perimetre: { periode: string; fonds: string; libelle: string; raison: string; prevu_ue_eur: number | null; paye_ue_eur: number | null }[]
    interreg: string
  }
  totaux: TotalPeriode[]
  feader_psp_2023_2027?: {
    prevu_ue_feader_eur: number | null
    paye_ue_feader_eur: number | null
    plan_strategique_pac?: { version?: string; financement_national_obligatoire_eur: number | null; financement_national_additionnel_eur: number | null; budget_total_plan_eur?: number | null }
  }
  ecarts: Ecart[]
  sources: SourceFe[]
  sources_inaccessibles: Inaccessible[]
  limites: string[]
  confidentialite: string
}
interface PeriodeRegion {
  periode: string
  par_fonds: Record<string, Bloc>
  total: Bloc
  annees: { annee: number; decide_cumule_eur: number | null; depense_cumulee_eur: number | null; paye_ue_cumule_eur: number | null }[]
}
export interface Region {
  code: string
  nom: string
  type: string
  programmes: string[]
  periodes: PeriodeRegion[]
}
interface Regions {
  millesime: string
  source: string
  avertissement: string
  regions: Region[]
}
interface Theme {
  code: string
  libelle: string
  libelle_source: string
  total: Bloc
  objectifs_specifiques?: { code: string; libelle: string; libelle_source: string; total: Bloc }[]
}
export interface Domaine {
  fonds: string
  code: string
  libelle_source: string
  prevu_ue_eur: number | null
  prevu_total_eur: number | null
  decide_eur: number | null
  depense_eur: number | null
  operations: number | null
}
interface Themes {
  millesime: string
  source: string
  avertissement: string
  periodes: {
    periode: string
    themes: Theme[]
    mesures_feader?: ({ code: string; libelle: string; libelle_source: string } & Bloc)[]
    domaines_intervention?: Domaine[]
  }[]
}
interface Annees {
  millesime: string
  source: string
  avertissement: string
  periodes: {
    periode: string
    engagements_ue: { annees: number[]; total_eur: (number | null)[] }
    paiements_ue: { annees: number[]; annee_partielle: number | null; cumul_total_eur: (number | null)[]; annuel_total_eur: (number | null)[] }
    execution: { annees: number[]; decide_cumule_par_fonds_eur: Record<string, (number | null)[]>; depense_cumulee_par_fonds_eur: Record<string, (number | null)[]> }
  }[]
}
interface Frr {
  millesime: string
  source: string
  avertissement: string
  annees: number[]
  fonds_recus: { total_eur: (number | null)[]; subventions_eur: (number | null)[]; prets_eur: (number | null)[]; pct_pib: (number | null)[]; cumul_eur: number | null }
  emplois: { categories: { code: string; libelle: string; parent: string | null; montants_eur: (number | null)[] }[]; lecture: string }
}
export interface ListeResume {
  id: string
  fichier: string
  autorite_de_gestion: string
  region: string
  periodes: string[]
  fonds: string[]
  operations: number
  operations_nommees: number
  part_cout_nommee: number | null
  url: string
  licence: string
  collecte_le: string
}
export interface IndexOperations {
  millesime: string
  source: string
  listes: ListeResume[]
  couverture: { programmes_couverts: string[]; programmes_regionaux: number; lecture: string }
  rapprochement?: { stock_sirene?: string }
  sources_inaccessibles?: Inaccessible[]
}
export interface Liste {
  millesime: string
  source: string
  autorite_de_gestion: string
  region: { code: string; nom: string }
  colonnes: string[]
  operations: (string | number | null)[][]
  montant_ue_mode: string
  non_nommes: { periode: string; fonds: string; annee_debut: number | null; motif: string; nombre: number; cout_total_eur: number | null; montant_ue_eur: number | null }[]
  motifs: Record<string, string>
  totaux: { periode: string; fonds: string; operations: number; cout_total_eur: number | null; montant_ue_eur: number | null; operations_nommees: number }[]
  comparaison_commission: { periode: string; fonds: string; montant_eur: number | null; autre_montant_eur: number | null; date_reference: string | null; ecart_eur: number | null; ecart_pct: number | null; lecture_ecart: string }[]
}

// ---------- Textes du site ----------
/** Explication en langage courant de chaque fonds (rédaction du site). */
export const EXPLICATIONS: Record<string, string> = {
  FEDER: 'Finance des investissements dans les régions : recherche et innovation, numérique, aide aux petites et moyennes entreprises, énergie et climat, transports, équipements.',
  FSE: 'Finance l’emploi, la formation, l’insertion et la lutte contre la pauvreté (2014-2020).',
  'FSE+': 'Suite du Fonds social européen depuis 2021 : emploi, formation, insertion, lutte contre la pauvreté, et aide alimentaire et matérielle aux plus démunis.',
  IEJ: 'Finance l’accompagnement vers l’emploi des jeunes sans emploi ni formation, dans les régions où le chômage des jeunes dépassait 25 % (2014-2020).',
  FTJ: 'Depuis 2021, accompagne les territoires où l’industrie émet beaucoup de gaz à effet de serre : formation, reconversion, nouvelles activités.',
  FEADER: 'Le volet « développement rural » de la politique agricole commune : installation, investissements des exploitations, environnement, services en zone rurale. Les aides versées directement à chaque exploitant (paiements directs) ne sont pas reprises ici.',
  FEAMP: 'Pêche, aquaculture et économie maritime (2014-2020).',
  FEAMPA: 'Suite du fonds pour la pêche depuis 2021 : pêche, aquaculture, économie maritime.',
}

/** Les quatre grandeurs, en langage courant. */
const GRANDEURS: [keyof Bloc, string, string][] = [
  ['prevu_ue_eur', 'Prévu par l’Union', 'part de l’Union inscrite au plan de chaque programme (dernière version adoptée)'],
  ['prevu_national_eur', 'Cofinancement national prévu', 'ce que les financeurs publics et privés français prévoient d’apporter en plus'],
  ['decide_eur', 'Décidé', 'coût total des projets sélectionnés (Union, financeurs français et privés)'],
  ['depense_eur', 'Dépensé', 'dépenses déclarées par les porteurs de projets'],
  ['paye_ue_eur', 'Payé par l’Union', 'versements nets de la Commission européenne, cumulés depuis le début de la période'],
]

/** Motifs d'agrégation des opérations non nommées (repli si la liste ne les définit pas). */
const MOTIFS: Record<string, string> = {
  personne_physique: 'bénéficiaire personne physique ou entrepreneur individuel',
  siren_inconnu: 'numéro d’entreprise absent du répertoire SIRENE',
  sans_nom: 'bénéficiaire non publié',
  nom_de_personne_possible: 'nom pouvant désigner une personne : jamais rapproché',
  non_rapproche: 'aucune entreprise ou organisme de même nom dans le répertoire SIRENE',
  ambigu: 'plusieurs entreprises ou organismes de même nom dans le répertoire SIRENE',
}

/**
 * Domaines d'intervention 2021-2027 (règlement (UE) 2021/1060, annexe I) et types d'intervention du FEAMPA :
 * traduction en français courant rédigée par le site à partir du libellé anglais publié par la Commission.
 */
export const DOMAINES_FR: Record<string, string> = {
  '001': 'Équipements et infrastructures de recherche des microentreprises, liés à la recherche et à l’innovation',
  '002': 'Équipements et infrastructures de recherche des petites et moyennes entreprises (dont centres de recherche privés), liés à la recherche et à l’innovation',
  '003': 'Équipements et infrastructures de recherche des grandes entreprises, liés à la recherche et à l’innovation',
  '004': 'Équipements et infrastructures des centres de recherche publics et de l’enseignement supérieur, liés à la recherche et à l’innovation',
  '006': 'Investissements immatériels (brevets, logiciels) des petites et moyennes entreprises, liés à la recherche et à l’innovation',
  '008': 'Investissements immatériels des centres de recherche publics et de l’enseignement supérieur, liés à la recherche et à l’innovation',
  '009': 'Recherche et innovation dans les microentreprises, mise en réseau comprise (recherche industrielle, développement expérimental, études de faisabilité)',
  '010': 'Recherche et innovation dans les petites et moyennes entreprises, mise en réseau comprise',
  '011': 'Recherche et innovation dans les grandes entreprises, mise en réseau comprise',
  '012': 'Recherche et innovation dans les centres de recherche publics, l’enseignement supérieur et les centres de compétences, mise en réseau comprise',
  '013': 'Passage au numérique des petites et moyennes entreprises (commerce en ligne, pôles d’innovation numérique, jeunes entreprises du numérique)',
  '014': 'Passage au numérique des grandes entreprises (commerce en ligne, pôles d’innovation numérique)',
  '015': 'Passage au numérique des entreprises, conforme aux critères de réduction des gaz à effet de serre ou d’efficacité énergétique',
  '016': 'Services numériques et applications des administrations',
  '017': 'Services numériques et applications des administrations, conformes aux critères de réduction des émissions ou d’efficacité énergétique',
  '018': 'Services et applications pour les compétences numériques et l’inclusion numérique',
  '019': 'Services et applications de santé en ligne (soins à distance, objets connectés pour l’activité physique et l’autonomie)',
  '020': 'Locaux et zones d’activité pour les petites et moyennes entreprises (parcs et sites industriels)',
  '021': 'Développement et activité à l’international des petites et moyennes entreprises, investissements productifs compris',
  '022': 'Soutien aux grandes entreprises par des instruments financiers (prêts, garanties, fonds propres), investissements productifs compris',
  '023': 'Compétences pour la spécialisation intelligente, la transition industrielle, l’entrepreneuriat et l’adaptation des entreprises',
  '024': 'Services de conseil aux petites et moyennes entreprises (gestion, commercialisation, design)',
  '025': 'Incubateurs, aide à la création d’entreprises et de jeunes pousses',
  '026': 'Pôles d’innovation et réseaux d’entreprises, avec des organismes de recherche et des autorités publiques, surtout au profit des petites et moyennes entreprises',
  '027': 'Innovation dans les petites et moyennes entreprises (procédés, organisation, commercialisation, conception avec les usagers)',
  '028': 'Transfert de technologie et coopération entre entreprises, centres de recherche et enseignement supérieur',
  '029': 'Recherche, innovation et transfert de technologie tournés vers l’économie bas carbone et l’adaptation au changement climatique',
  '030': 'Recherche, innovation et transfert de technologie entre entreprises tournés vers l’économie circulaire',
  '032': 'Très haut débit : réseau de collecte (dorsale)',
  '033': 'Très haut débit : réseau de desserte, équivalent à la fibre jusqu’au pied des immeubles collectifs',
  '034': 'Très haut débit : réseau de desserte, équivalent à la fibre jusqu’aux logements et aux locaux professionnels',
  '036': 'Autres infrastructures numériques (calcul de grande capacité, centres de données, capteurs, équipements sans fil)',
  '037': 'Autres infrastructures numériques, conformes aux critères de réduction des émissions et d’efficacité énergétique',
  '038': 'Efficacité énergétique et projets de démonstration dans les petites et moyennes entreprises',
  '039': 'Efficacité énergétique et projets de démonstration dans les grandes entreprises',
  '040': 'Efficacité énergétique et projets de démonstration dans les entreprises, conformes aux critères d’efficacité énergétique',
  '041': 'Rénovation énergétique des logements existants, projets de démonstration et mesures d’accompagnement',
  '042': 'Rénovation énergétique des logements existants, conforme aux critères d’efficacité énergétique',
  '043': 'Construction de bâtiments neufs économes en énergie',
  '044': 'Rénovation énergétique ou économies d’énergie des bâtiments et équipements publics',
  '045': 'Rénovation énergétique ou économies d’énergie des bâtiments et équipements publics, conformes aux critères d’efficacité énergétique',
  '046': 'Soutien aux organismes qui contribuent à l’économie bas carbone et à l’adaptation au changement climatique, sensibilisation comprise',
  '047': 'Énergie renouvelable : éolien',
  '048': 'Énergie renouvelable : solaire',
  '049': 'Énergie renouvelable : biomasse',
  '050': 'Énergie renouvelable : biomasse à forte réduction des gaz à effet de serre',
  '051': 'Énergie renouvelable : énergies marines',
  '052': 'Autres énergies renouvelables (dont géothermie)',
  '053': 'Systèmes énergétiques intelligents (réseaux intelligents, outils numériques) et stockage',
  '054': 'Cogénération à haut rendement, réseaux de chaleur et de froid',
  '055': 'Cogénération à haut rendement, réseaux de chaleur et de froid à faibles émissions sur leur cycle de vie',
  '058': 'Adaptation au changement climatique et prévention des risques : inondations et glissements de terrain (sensibilisation, protection civile, ouvrages, solutions fondées sur la nature)',
  '059': 'Adaptation au changement climatique et prévention des risques : incendies (sensibilisation, protection civile, ouvrages, solutions fondées sur la nature)',
  '060': 'Adaptation au changement climatique et prévention des risques : autres risques, par exemple tempêtes et sécheresse',
  '061': 'Prévention des risques naturels non climatiques et des risques liés aux activités humaines (sensibilisation, protection civile, ouvrages)',
  '062': 'Eau potable (captage, traitement, stockage, distribution, économies d’eau)',
  '063': 'Eau potable (captage, traitement, stockage, distribution), conforme aux critères d’efficacité',
  '064': 'Gestion et préservation de la ressource en eau (bassins versants, adaptation au changement climatique, réutilisation, réduction des fuites)',
  '065': 'Collecte et traitement des eaux usées',
  '066': 'Collecte et traitement des eaux usées, conformes aux critères d’efficacité énergétique',
  '067': 'Déchets ménagers : prévention, réduction, tri, réemploi, recyclage',
  '068': 'Déchets ménagers : traitement des déchets résiduels',
  '069': 'Déchets des entreprises : prévention, réduction, tri, réemploi, recyclage',
  '070': 'Déchets des entreprises : déchets résiduels et dangereux',
  '071': 'Utilisation de matériaux recyclés comme matières premières',
  '072': 'Utilisation de matériaux recyclés comme matières premières, conforme aux critères d’efficacité',
  '073': 'Réhabilitation des friches industrielles et des sols pollués',
  '074': 'Réhabilitation des friches industrielles et des sols pollués, conforme aux critères d’efficacité',
  '075': 'Production respectueuse de l’environnement et utilisation efficace des ressources dans les petites et moyennes entreprises',
  '076': 'Production respectueuse de l’environnement et utilisation efficace des ressources dans les grandes entreprises',
  '077': 'Qualité de l’air et réduction du bruit',
  '078': 'Protection, restauration et usage durable des sites Natura 2000',
  '079': 'Protection de la nature et de la biodiversité, patrimoine naturel, trames vertes et bleues',
  '080': 'Autres mesures de réduction des gaz à effet de serre par la préservation et la restauration de milieux naturels qui stockent le carbone (remise en eau des tourbières, captage du gaz des décharges)',
  '081': 'Infrastructures de transport urbain propre',
  '082': 'Véhicules de transport urbain propre',
  '083': 'Aménagements cyclables',
  '084': 'Passage au numérique des transports urbains',
  '085': 'Passage au numérique des transports urbains, en partie consacré à la réduction des gaz à effet de serre',
  '086': 'Infrastructures pour carburants alternatifs (recharge électrique, hydrogène)',
  '090': 'Autres routes d’accès nationales, régionales ou locales, neuves ou améliorées',
  '093': 'Autres routes reconstruites ou modernisées (autoroutes, routes nationales, régionales ou locales)',
  '095': 'Passage au numérique des transports routiers, en partie consacré à la réduction des gaz à effet de serre',
  '099': 'Autres voies ferrées neuves ou améliorées, électriques ou à zéro émission',
  '100': 'Voies ferrées reconstruites ou modernisées du réseau transeuropéen de transport (réseau central)',
  '101': 'Voies ferrées reconstruites ou modernisées du réseau transeuropéen de transport (réseau global)',
  '104': 'Passage au numérique du transport ferroviaire',
  '108': 'Transport multimodal du réseau transeuropéen',
  '109': 'Transport multimodal (hors transport urbain)',
  '110': 'Ports maritimes du réseau transeuropéen',
  '111': 'Ports maritimes du réseau transeuropéen, hors installations pour les combustibles fossiles',
  '113': 'Autres ports maritimes, hors installations pour les combustibles fossiles',
  '116': 'Voies navigables et ports intérieurs (régionaux et locaux)',
  '117': 'Voies navigables et ports intérieurs (régionaux et locaux), hors installations pour les combustibles fossiles',
  '119': 'Passage au numérique des autres modes de transport',
  '120': 'Passage au numérique des autres modes de transport, en partie consacré à la réduction des gaz à effet de serre',
  '121': 'Bâtiments et équipements pour l’accueil et l’éducation de la petite enfance',
  '122': 'Bâtiments et équipements pour l’enseignement primaire et secondaire',
  '123': 'Bâtiments et équipements pour l’enseignement supérieur',
  '124': 'Bâtiments et équipements pour la formation professionnelle et la formation des adultes',
  '126': 'Logements (hors accueil des migrants, des réfugiés et des demandeurs d’asile)',
  '127': 'Autres équipements sociaux favorisant l’inclusion',
  '128': 'Bâtiments de santé',
  '129': 'Équipements de santé',
  '130': 'Équipements de santé mobiles',
  '131': 'Passage au numérique des soins de santé',
  '133': 'Accueil temporaire des migrants, des réfugiés et des demandeurs d’asile (bâtiments)',
  '134': 'Accès à l’emploi',
  '135': 'Accès à l’emploi des chômeurs de longue durée',
  '136': 'Emploi et insertion des jeunes',
  '137': 'Travail indépendant et création d’entreprise',
  '138': 'Économie sociale et entreprises sociales',
  '139': 'Modernisation des services de l’emploi et anticipation des besoins en compétences',
  '140': 'Rapprochement entre offres et demandes d’emploi, transitions professionnelles',
  '141': 'Mobilité professionnelle',
  '142': 'Accès des femmes au marché du travail, réduction de la ségrégation entre les femmes et les hommes au travail',
  '143': 'Conciliation entre vie professionnelle et vie privée, dont garde d’enfants et aide aux personnes dépendantes',
  '144': 'Santé et conditions de travail, dont activité physique',
  '145': 'Compétences numériques',
  '145a': 'Compétences et accès à l’emploi dans le numérique, les technologies de pointe, les biotechnologies et les technologies de défense',
  '145b': 'Compétences et accès à l’emploi dans les technologies propres et économes en ressources',
  '146': 'Adaptation des travailleurs, des entreprises et des entrepreneurs au changement',
  '147': 'Vieillissement actif et en bonne santé',
  '148': 'Accueil et éducation de la petite enfance (hors bâtiments)',
  '149': 'Enseignement primaire et secondaire (hors bâtiments)',
  '150': 'Enseignement supérieur (hors bâtiments)',
  '151': 'Formation des adultes (hors bâtiments)',
  '152': 'Égalité des chances et participation active à la société',
  '153': 'Parcours d’insertion et de retour à l’emploi des personnes défavorisées',
  '155': 'Soutien aux associations qui travaillent avec les communautés marginalisées, comme les Roms',
  '158': 'Accès égal et rapide à des services de qualité, durables et abordables',
  '160': 'Accessibilité, efficacité et résilience des systèmes de santé (hors bâtiments)',
  '161': 'Accès aux soins de longue durée (hors bâtiments)',
  '163': 'Inclusion sociale des personnes menacées de pauvreté ou d’exclusion, dont les plus démunis et les enfants',
  '164': 'Aide alimentaire ou matérielle aux plus démunis, avec mesures d’accompagnement',
  '165': 'Protection, développement et promotion du patrimoine et des services touristiques publics',
  '166': 'Protection, développement et promotion du patrimoine culturel et des services culturels',
  '167': 'Protection, développement et promotion du patrimoine naturel et de l’écotourisme (hors sites Natura 2000)',
  '168': 'Réaménagement et sécurité des espaces publics',
  '169': 'Projets de développement territorial, dont préparation des stratégies territoriales',
  '170': 'Renforcement des autorités et organismes chargés de gérer les fonds',
  '175': 'Régions ultrapériphériques : compensation des surcoûts liés à l’éloignement et à l’insularité',
  '176': 'Régions ultrapériphériques : compensation des surcoûts liés à la taille du marché',
  '177': 'Régions ultrapériphériques : compensation des surcoûts liés au climat et au relief',
  '178': 'Régions ultrapériphériques : aéroports',
  '188': 'Investissements productifs des grandes entreprises dans les technologies propres et économes en ressources',
  '189': 'Investissements productifs des petites et moyennes entreprises dans les technologies propres et économes en ressources',
  '190': 'Investissements productifs des grandes entreprises dans les biotechnologies',
  '191': 'Investissements productifs des petites et moyennes entreprises dans les biotechnologies',
  '192': 'Investissements productifs des grandes entreprises dans le numérique et les technologies de pointe',
  '193': 'Investissements productifs des petites et moyennes entreprises dans le numérique et les technologies de pointe',
  '194': 'Investissements productifs des grandes entreprises dans les technologies de défense et à double usage (civil et militaire)',
  '195': 'Investissements productifs des petites et moyennes entreprises dans les technologies de défense et à double usage (civil et militaire)',
  '197': 'Protection des infrastructures critiques',
  '198': 'Infrastructures de défense et infrastructures à double usage (civil et militaire), dont mobilité militaire',
  '999': 'Assistance technique forfaitaire (article 36, paragraphe 5, du règlement portant dispositions communes)',
  // Types d'intervention du fonds pour la pêche (FEAMPA)
  '01': 'Réduire les effets négatifs sur l’environnement, ou y contribuer positivement, et contribuer au bon état écologique',
  '02': 'Favoriser une pêche, une aquaculture et une transformation viables, compétitives et attractives',
  '03': 'Contribuer à la neutralité climatique',
  '04': 'Arrêt temporaire des activités de pêche',
  '05': 'Arrêt définitif des activités de pêche',
  '06': 'Bon état écologique par la gestion et le suivi des aires marines protégées, dont Natura 2000',
  '07': 'Indemnisation d’événements environnementaux, climatiques ou sanitaires imprévus',
  '08': 'Compensation des surcoûts dans les régions ultrapériphériques',
  '10': 'Contrôle et application des règles',
  '11': 'Collecte et analyse de données, connaissance du milieu marin',
  '12': 'Surveillance et sécurité maritimes',
  '13': 'Développement local mené par les acteurs locaux : préparation',
  '14': 'Développement local mené par les acteurs locaux : mise en œuvre de la stratégie',
  '15': 'Développement local mené par les acteurs locaux : fonctionnement et animation',
  '997': 'Assistance technique forfaitaire (article 36, paragraphe 5, du règlement portant dispositions communes)',
}

// ---------- Outils ----------
/** Montant ou « non publié » (null n'est jamais 0). */
export const montant = (x: number | null | undefined) => (typeof x === 'number' ? eurLisible(x) : 'non publié')
const td = (x: number | null | undefined) => `<td class="nombre">${h(montant(x))}</td>`
const normaliser = (x: string) =>
  x
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[’`]/g, "'")
    .replace(/\s+/g, ' ')
    .trim()
const COLLATION = new Intl.Collator('fr', { sensitivity: 'base' })
/** Date ISO (AAAA-MM-JJ ou AAAA-MM) en toutes lettres. */
export function dateFr(d: string | null | undefined): string {
  if (!d) return 'date non publiée'
  const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(d)
  if (!m) return d
  const mois = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'][Number(m[2]) - 1]
  return m[3] ? `${Number(m[3]) === 1 ? '1er' : Number(m[3])} ${mois} ${m[1]}` : `${mois} ${m[1]}`
}
/** Nom du fonds sans le sigle entre parenthèses quand il est déjà dit (« Fonds européen de développement régional »). */
const sansSigle = (x: string) => x.replace(/\s*\([A-Z+]{2,}\)\s*$/, '')
/** Retire des textes publiés les renvois techniques vers des champs ou des fichiers (« champ `territoire` de programmes.json »). */
const lisible = (x: string) =>
  x
    .replace(/\s*\(champ `[^`]*`[^)]*\)/g, '')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\s+([.;,])/g, '$1')
const majuscule = (x: string) => (x ? x[0].toUpperCase() + x.slice(1) : x)
const somme = (xs: (number | null | undefined)[]) => (xs.length && xs.every((x) => typeof x === 'number') ? (xs as number[]).reduce((a, b) => a + b, 0) : null)

/** Libellé lisible d'un domaine d'intervention : traduction du site si elle existe, sinon libellé d'origine. */
export function traduireDomaine(d: Pick<Domaine, 'code' | 'libelle_source'>): { texte: string; traduit: boolean } {
  const t = DOMAINES_FR[d.code]
  return t ? { texte: t, traduit: true } : { texte: d.libelle_source, traduit: false }
}

// ---------- Blocs de la page ----------
function nomsFonds(idx: Index): Map<string, string> {
  return new Map(idx.fonds.map((f) => [f.code, f.libelle]))
}
function ordreFonds(idx: Index, codes: string[]): string[] {
  const ordre = idx.fonds.map((f) => f.code)
  return [...codes].sort((a, b) => (ordre.indexOf(a) === -1 ? 99 : ordre.indexOf(a)) - (ordre.indexOf(b) === -1 ? 99 : ordre.indexOf(b)))
}

function blocCle(idx: Index): string {
  const p = idx.totaux.find((t) => t.periode === '2021-2027')
  const t = p?.total
  if (!t || typeof t.prevu_ue_eur !== 'number') return ''
  const part = typeof t.prevu_total_eur === 'number' && t.prevu_total_eur > 0 ? (t.prevu_ue_eur / t.prevu_total_eur) * 100 : null
  return `<div class="carte" data-cle>
  <p class="grand-chiffre">${surligne(eurLisible(t.prevu_ue_eur))}</p>
  <p class="sous-chiffre">prévus par l’Union européenne pour ses programmes 2021-2027 en France (fonds régionaux, social, transition juste et pêche). ${badgeStatut('trace')}</p>
  ${
    part !== null
      ? `<p>Sur 100 € prévus par ces programmes, ${h(sur100(part))} viennent de l’Union et ${h(sur100(100 - part))} des financeurs français, publics et privés. ${badgeCalcule('part de l’Union = montant prévu par l’Union divisé par le total prévu des mêmes programmes et de la même période de programmation, montants publiés par la Commission européenne')}</p>`
      : ''
  }
  ${source(idx.source, idx.millesime)}
</div>`
}

function blocFonds(idx: Index): string {
  const items = idx.fonds
    .map((f) => `<li><strong>${h(sansSigle(f.libelle))}</strong>${/\(([A-Z+]+)\)$/.test(f.libelle) ? ` (${h(/\(([A-Z+]+)\)$/.exec(f.libelle)![1])})` : ''} : ${h(EXPLICATIONS[f.code] ?? '')}</li>`)
    .join('')
  const hors = idx.perimetre.hors_perimetre
  return `<h2 id="fe-fonds">Les fonds, en quelques mots</h2>
<ul class="fe-fonds">${items}
<li><strong>Facilité pour la reprise et la résilience</strong> : subventions de l’Union au plan de relance de la France depuis 2021, financées par un emprunt commun des pays de l’Union (NextGenerationEU), et non par la contribution que la France verse chaque année au budget européen. Elle a sa partie plus bas.</li></ul>
<p class="aide">Ne sont pas repris : les aides de la politique agricole commune versées directement à chaque exploitant, les programmes de coopération entre pays (Interreg), dont la source ne publie pas la part française, et quatre fonds présents dans les mêmes données mais régis par d’autres règles.</p>
${
  hors.length
    ? `<details><summary>Fonds présents dans les données mais non repris dans les totaux</summary><div class="tableau-defile"><table><caption>Fonds hors du périmètre de la page, montants publiés par la Commission européenne</caption><thead><tr><th scope="col">Fonds</th><th scope="col">Période</th><th scope="col" class="nombre">Prévu par l’Union</th><th scope="col" class="nombre">Payé par l’Union</th><th scope="col">Raison</th></tr></thead><tbody>${hors
        .map((x) => `<tr><th scope="row">${h(sansSigle(x.libelle))}</th><td>${h(x.periode)}</td>${td(x.prevu_ue_eur)}${td(x.paye_ue_eur)}<td>${h(majuscule(x.raison))}</td></tr>`)
        .join('')}</tbody></table></div></details>`
    : ''
}`
}

/** Phrases factuelles quand le décidé publié dépasse le prévu (aucune interprétation, la source n'en donne pas la raison). */
export function phrasesDecideAuDessus(idx: Index, t: TotalPeriode): string[] {
  const noms = nomsFonds(idx)
  return ordreFonds(idx, Object.keys(t.par_fonds))
    .map((f) => [f, t.par_fonds[f]] as const)
    .filter(([, b]) => typeof b.decide_eur === 'number' && typeof b.prevu_total_eur === 'number' && b.decide_eur > b.prevu_total_eur)
    .map(
      ([f, b]) =>
        `${sansSigle(noms.get(f) ?? f)}, ${t.periode} : le décidé publié (${eurLisible(b.decide_eur!)}) dépasse le prévu total (${eurLisible(b.prevu_total_eur!)}), de ${eurLisible(b.decide_eur! - b.prevu_total_eur!)}.`,
    )
}

function tablePeriode(idx: Index, t: TotalPeriode): string {
  const noms = nomsFonds(idx)
  const fonds = ordreFonds(idx, Object.keys(t.par_fonds))
  const calcule = t.periode === '2021-2027'
  const dates = `décidé et dépensé à la dernière transmission (${h(dateFr(t.date_execution))}), payé jusqu’en ${h(String(t.annee_paiements ?? 'année non publiée'))} (année en cours)`
  const decides = phrasesDecideAuDessus(idx, t)
  return `<div class="tableau-defile"><table><caption>Programmes ${h(t.periode)} en France, par fonds : ${dates}</caption><thead><tr><th scope="col">Fonds</th>${GRANDEURS.map(
    ([, nom]) => `<th scope="col" class="nombre">${h(nom)}</th>`,
  ).join('')}</tr></thead><tbody>${fonds
    .map((f) => {
      const b = t.par_fonds[f]
      return `<tr><th scope="row">${h(noms.get(f) ?? f)}</th>${GRANDEURS.map(([k]) => td(b[k] as number | null)).join('')}</tr>`
    })
    .join('')}</tbody><tfoot><tr><th scope="row">Ensemble des fonds</th>${GRANDEURS.map(([k]) => td(t.total[k] as number | null)).join('')}</tr></tfoot></table></div>
<p>${badgeStatut('trace')} Montants publiés par la Commission européenne.${
    calcule ? ` Pour 2021-2027, le cofinancement national ${badgeCalcule('total prévu moins la part de l’Union, pour le même programme et la même période de programmation')}` : ' Pour 2014-2020, le cofinancement national prévu est publié.'
  } Chaque colonne a sa date : les colonnes se lisent côte à côte et ne s’additionnent pas.</p>
${decides.length ? `<ul class="fe-decide">${decides.map((d) => `<li>${h(d)}</li>`).join('')}</ul><p class="aide">Le décidé peut dépasser le prévu : la source le publie ainsi, sans en donner la raison. Les montants sont repris tels quels.</p>` : ''}`
}

function blocPeriodes(idx: Index): string {
  const psp = idx.feader_psp_2023_2027
  const pac = psp?.plan_strategique_pac
  return `<h2 id="fe-periodes">Prévu, décidé, dépensé, payé : les deux périodes</h2>
<p>Chaque programme européen dure sept ans et se paie encore plusieurs années après. Pour chacun, la Commission européenne publie quatre montants qui ne disent pas la même chose :</p>
<ul>${GRANDEURS.map(([, nom, def]) => `<li><strong>${h(nom)}</strong> : ${h(def)}.</li>`).join('')}</ul>
${idx.totaux
  .filter((t) => t.periode !== '2023-2027')
  .map((t) => `<h3>Programmes ${h(t.periode)}</h3>${tablePeriode(idx, t)}`)
  .join('')}
${
  psp
    ? `<h3>Développement rural 2023-2027 (plan stratégique de la politique agricole commune)</h3>
<p>Depuis 2023, le fonds pour le développement rural fait partie du plan stratégique national de la politique agricole commune. Part de l’Union prévue : <strong>${h(montant(psp.prevu_ue_feader_eur))}</strong> ; payé par l’Union à ce jour : <strong>${h(
        montant(psp.paye_ue_feader_eur),
      )}</strong>. ${badgeStatut('trace')}</p>${
        pac
          ? `<p>Pour l’ensemble du plan, aides directes aux exploitants comprises, la source publie aussi un financement national obligatoire de ${h(montant(pac.financement_national_obligatoire_eur))} et un financement national additionnel de ${h(
              montant(pac.financement_national_additionnel_eur),
            )}, sans les rattacher à un fonds : ils sont montrés à côté, sans addition. ${badgeStatut('trace')}</p>`
          : ''
      }<p class="aide">Les années 2021 et 2022 du développement rural sont comptées avec les programmes 2014-2020 (période de transition).</p>`
    : ''
}`
}

function blocRegions(regions: Regions | null, idx: Index, choisie: string | null): string {
  if (!regions) return `<h2 id="fe-regions">Par région</h2>${absent('Répartition par région non disponible.')}`
  const val = (r: Region, p: string, k: keyof Bloc) => r.periodes.find((x) => x.periode === p)?.total[k] as number | null | undefined
  const cell = (r: Region, p: string, k: keyof Bloc) => (r.periodes.some((x) => x.periode === p) ? td(val(r, p, k)) : '<td class="nombre">sans programme</td>')
  return `<h2 id="fe-regions">Par région</h2>
<p>${h(lisible(regions.avertissement))}</p>
<div class="tableau-defile"><table><caption>Fonds européens par région, part de l’Union prévue et payée, ${h(regions.millesime)}</caption><thead><tr><th scope="col">Région ou groupe de programmes</th><th scope="col" class="nombre">2014-2020 : prévu par l’Union</th><th scope="col" class="nombre">2014-2020 : payé par l’Union</th><th scope="col" class="nombre">2021-2027 : prévu par l’Union</th><th scope="col" class="nombre">2021-2027 : payé par l’Union</th></tr></thead><tbody>${regions.regions
    .map((r) => `<tr><th scope="row">${h(r.nom)}</th>${cell(r, '2014-2020', 'prevu_ue_eur')}${cell(r, '2014-2020', 'paye_ue_eur')}${cell(r, '2021-2027', 'prevu_ue_eur')}${cell(r, '2021-2027', 'paye_ue_eur')}</tr>`)
    .join('')}</tbody></table></div>
<p class="aide">${badgeStatut('trace')} Régions dans l’ordre de leur code officiel, sans classement. Le développement rural 2023-2027 est un programme national.</p>
${source(regions.source)}
<form class="recherche carte" id="fe-region-form" aria-label="Choisir une région">${listeRecherche({ id: 'fe-region', etiquette: 'Détail d’une région', options: [], optionsHtml: `<option value="">Choisir</option>${regions.regions
    .map((r) => `<option value="${h(r.code)}"${r.code === choisie ? ' selected' : ''}>${h(r.nom)}</option>`)
    .join('')}` })}</form>
<div id="fe-region-detail" aria-live="polite">${choisie ? detailRegion(regions.regions.find((r) => r.code === choisie) ?? null, idx) : ''}</div>`
}

export function detailRegion(r: Region | null, idx: Index): string {
  if (!r) return absent('Région inconnue.')
  const noms = nomsFonds(idx)
  return `<h3>${h(r.nom)}</h3><p>${h(entier(r.programmes.length))} programme${r.programmes.length > 1 ? 's' : ''} européen${r.programmes.length > 1 ? 's' : ''} rattaché${r.programmes.length > 1 ? 's' : ''}.</p>${r.periodes
    .map(
      (p) => `<div class="tableau-defile"><table><caption>${h(r.nom)}, programmes ${h(p.periode)}, par fonds</caption><thead><tr><th scope="col">Fonds</th>${GRANDEURS.map(([, nom]) => `<th scope="col" class="nombre">${h(nom)}</th>`).join('')}</tr></thead><tbody>${ordreFonds(
        idx,
        Object.keys(p.par_fonds),
      )
        .map((f) => `<tr><th scope="row">${h(noms.get(f) ?? f)}</th>${GRANDEURS.map(([k]) => td(p.par_fonds[f][k] as number | null)).join('')}</tr>`)
        .join('')}</tbody></table></div>${
        p.annees.length
          ? `<details><summary>${h(r.nom)}, ${h(p.periode)} : montants cumulés année par année</summary><div class="tableau-defile"><table><caption>${h(r.nom)}, programmes ${h(p.periode)}, montants cumulés depuis le début de la période</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Décidé (cumul)</th><th scope="col" class="nombre">Dépensé (cumul)</th><th scope="col" class="nombre">Payé par l’Union (cumul)</th></tr></thead><tbody>${p.annees
              .map((a) => `<tr><th scope="row">${h(a.annee)}</th>${td(a.decide_cumule_eur)}${td(a.depense_cumulee_eur)}${td(a.paye_ue_cumule_eur)}</tr>`)
              .join('')}</tbody></table></div></details>`
          : ''
      }`,
    )
    .join('')}`
}

function blocThemes(themes: Themes | null, idx: Index): string {
  if (!themes) return `<h2 id="fe-themes">Par thème</h2>${absent('Répartition par thème non disponible.')}`
  const t14 = themes.periodes.find((p) => p.periode === '2014-2020')
  const t21 = themes.periodes.find((p) => p.periode === '2021-2027')
  const tete = `<th scope="col" class="nombre">Prévu par l’Union</th><th scope="col" class="nombre">Cofinancement national prévu</th><th scope="col" class="nombre">Décidé</th><th scope="col" class="nombre">Dépensé</th>`
  const cellules = (b: Bloc) => `${td(b.prevu_ue_eur)}${td(b.prevu_national_eur)}${td(b.decide_eur)}${td(b.depense_eur)}`
  const noms = nomsFonds(idx)
  const rang = (f: string) => {
    const i = idx.fonds.findIndex((x) => x.code === f)
    return i === -1 ? 99 : i
  }
  const domaines = [...(t21?.domaines_intervention ?? [])].sort((a, b) => rang(a.fonds) - rang(b.fonds) || COLLATION.compare(a.code, b.code))
  return `<h2 id="fe-themes">Par thème</h2>
<p>${h(lisible(themes.avertissement))} Les montants par thème ne comprennent pas les paiements de l’Union, qui ne sont publiés que par programme.</p>
${
  t14
    ? `<h3>Programmes 2014-2020, par objectif</h3><div class="tableau-defile"><table><caption>Programmes 2014-2020 en France, par objectif thématique</caption><thead><tr><th scope="col">Objectif</th>${tete}</tr></thead><tbody>${t14.themes
        .map((x) => `<tr><th scope="row">${h(x.libelle)}</th>${cellules(x.total)}</tr>`)
        .join('')}</tbody></table></div>${
        t14.mesures_feader?.length
          ? `<details><summary>Développement rural 2014-2020, par mesure</summary><div class="tableau-defile"><table><caption>Fonds pour le développement rural, programmes 2014-2020, par mesure</caption><thead><tr><th scope="col">Mesure</th>${tete}</tr></thead><tbody>${t14.mesures_feader
              .map((x) => `<tr><th scope="row">${h(x.libelle)}</th>${cellules(x)}</tr>`)
              .join('')}</tbody></table></div></details>`
          : ''
      }`
    : ''
}
${
  t21
    ? `<h3>Programmes 2021-2027, par objectif</h3><div class="tableau-defile"><table><caption>Programmes 2021-2027 en France, par objectif stratégique</caption><thead><tr><th scope="col">Objectif</th>${tete}</tr></thead><tbody>${t21.themes
        .map((x) => `<tr><th scope="row">${h(x.libelle)}</th>${cellules(x.total)}</tr>`)
        .join('')}</tbody></table></div>
<p class="aide">Cofinancement national 2021-2027 ${badgeCalcule('total prévu moins la part de l’Union, pour le même thème et la même période de programmation')}</p>
${t21.themes
  .filter((x) => x.objectifs_specifiques?.length)
  .map(
    (x) => `<details><summary>${h(x.libelle)} : détail par objectif</summary><div class="tableau-defile"><table><caption>${h(x.libelle)}, programmes 2021-2027, par objectif spécifique</caption><thead><tr><th scope="col">Objectif spécifique</th>${tete}</tr></thead><tbody>${x
      .objectifs_specifiques!.map((o) => `<tr><th scope="row">${h(o.libelle)}</th>${cellules(o.total)}</tr>`)
      .join('')}</tbody></table></div></details>`,
  )
  .join('')}
${
  domaines.length
    ? `<details id="fe-domaines"><summary>Les ${h(entier(domaines.length))} domaines d’intervention 2021-2027 (libellés traduits par le site)</summary>
<p>La Commission publie ces domaines avec un libellé en anglais. Le libellé en français est une <strong>traduction rédigée par le site</strong> ; le libellé d’origine est donné dessous.</p>
<div class="tableau-defile"><table><caption>Domaines d’intervention des programmes 2021-2027 en France, par fonds</caption><thead><tr><th scope="col">Domaine (traduction du site)</th><th scope="col">Fonds</th><th scope="col" class="nombre">Prévu par l’Union</th><th scope="col" class="nombre">Prévu au total</th><th scope="col" class="nombre">Décidé</th><th scope="col" class="nombre">Dépensé</th><th scope="col" class="nombre">Opérations</th></tr></thead><tbody>${domaines
        .map((d) => {
          const t = traduireDomaine(d)
          return `<tr><th scope="row">${h(t.texte)}${
            t.traduit ? `<span class="aide fe-origine"> Libellé d’origine (anglais) : <span lang="en">${h(d.libelle_source)}</span></span>` : ' <span class="aide">(libellé d’origine, non traduit)</span>'
          }</th><td>${h(sansSigle(noms.get(d.fonds) ?? d.fonds))}</td>${td(d.prevu_ue_eur)}${td(d.prevu_total_eur)}${td(d.decide_eur)}${td(d.depense_eur)}<td class="nombre">${typeof d.operations === 'number' ? h(entier(d.operations)) : 'non publié'}</td></tr>`
        })
        .join('')}</tbody></table></div></details>`
    : ''
}`
    : ''
}
${source(themes.source, themes.millesime)}`
}

function blocAnnees(annees: Annees | null, frr: Frr | null): string {
  if (!annees) return `<h2 id="fe-annees">Année par année</h2>${absent('Séries annuelles non disponibles.')}`
  const tables = annees.periodes
    .map((p) => {
      const ans = [...new Set([...p.engagements_ue.annees, ...p.paiements_ue.annees, ...p.execution.annees])].sort((a, b) => a - b)
      if (!ans.length) return ''
      const de = (serie: number[], valeurs: (number | null)[], a: number) => {
        const i = serie.indexOf(a)
        return i === -1 ? undefined : valeurs[i]
      }
      const exec = (par: Record<string, (number | null)[]>, a: number) => {
        const i = p.execution.annees.indexOf(a)
        return i === -1 ? undefined : somme(Object.values(par).map((v) => v[i]))
      }
      const c = (x: number | null | undefined) => (x === undefined ? '<td class="nombre">sans objet</td>' : td(x))
      const titre = p.periode === '2023-2027' ? 'Développement rural 2023-2027' : `Programmes ${p.periode}`
      const barresPaye = p.paiements_ue.annees.map((a, i) => ({ a, v: p.paiements_ue.annuel_total_eur[i] })).filter((x) => typeof x.v === 'number')
      return `<h3>${h(titre)}</h3>
${
  barresPaye.length
    ? barres(
        barresPaye.map((x) => ({
          nom: `${x.a}${x.a === p.paiements_ue.annee_partielle ? ' (année en cours)' : ''}`,
          valeur: Math.max(0, x.v as number),
          texte: eurLisible(x.v as number),
          statut: 'approche' as const,
        })),
        undefined,
        `${titre} : payé par l’Union dans l’année`,
      )
    : ''
}
<div class="tableau-defile"><table><caption>${h(titre)} : crédits prévus par l’Union, paiements et exécution, par année</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Crédits d’engagement prévus par l’Union</th><th scope="col" class="nombre">Payé par l’Union dans l’année</th><th scope="col" class="nombre">Payé par l’Union (cumul)</th><th scope="col" class="nombre">Décidé (cumul)</th><th scope="col" class="nombre">Dépensé (cumul)</th></tr></thead><tbody>${ans
        .map(
          (a) =>
            `<tr><th scope="row">${h(a)}${a === p.paiements_ue.annee_partielle ? ' (en cours)' : ''}</th>${c(de(p.engagements_ue.annees, p.engagements_ue.total_eur, a))}${c(de(p.paiements_ue.annees, p.paiements_ue.annuel_total_eur, a))}${c(
              de(p.paiements_ue.annees, p.paiements_ue.cumul_total_eur, a),
            )}${c(exec(p.execution.decide_cumule_par_fonds_eur, a))}${c(exec(p.execution.depense_cumulee_par_fonds_eur, a))}</tr>`,
        )
        .join('')}</tbody></table></div>
<p class="aide">Payé par l’Union dans l’année ${badgeCalcule('cumul payé à la fin de l’année moins cumul payé à la fin de l’année précédente, publiés par la Commission pour les mêmes programmes')}</p>`
    })
    .join('')
  return `<h2 id="fe-annees">Année par année</h2>
<p>${h(lisible(annees.avertissement))} ${badgeStatut('approche')} Le payé dans l’année est la différence entre deux cumuls publiés ; une valeur négative (recouvrement) est montrée telle quelle. « Sans objet » : aucune valeur pour cette année dans la série publiée.</p>
${tables}
${source(annees.source, annees.millesime)}
${blocFrr(frr)}`
}

function blocFrr(frr: Frr | null): string {
  if (!frr) return ''
  const tot = frr.emplois.categories.find((c) => c.code === 'TOTAL')
  return `<h2 id="fe-frr">Facilité pour la reprise et la résilience</h2>
<p>${h(frr.avertissement)}</p>
<div class="tableau-defile"><table><caption>Facilité pour la reprise et la résilience : fonds reçus par les administrations publiques françaises, ${h(frr.millesime)}</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Fonds reçus</th><th scope="col" class="nombre">dont subventions</th><th scope="col" class="nombre">dont prêts</th><th scope="col" class="nombre">Part de la richesse produite (PIB)</th><th scope="col" class="nombre">Dépenses publiques financées</th></tr></thead><tbody>${frr.annees
    .map(
      (a, i) =>
        `<tr><th scope="row">${h(a)}</th>${td(frr.fonds_recus.total_eur[i])}${td(frr.fonds_recus.subventions_eur[i])}${td(frr.fonds_recus.prets_eur[i])}<td class="nombre">${
          typeof frr.fonds_recus.pct_pib[i] === 'number' ? h(pct(frr.fonds_recus.pct_pib[i]!)) : 'non publié'
        }</td>${td(tot?.montants_eur[i])}</tr>`,
    )
    .join('')}</tbody></table></div>
<p>${badgeStatut('trace')} Montants publiés par Eurostat. ${
    typeof frr.fonds_recus.cumul_eur === 'number' ? `De ${h(frr.annees[0])} à ${h(frr.annees[frr.annees.length - 1])}, ${h(eurLisible(frr.fonds_recus.cumul_eur))} reçus au total ${badgeCalcule(`somme des montants reçus chaque année de ${frr.annees[0]} à ${frr.annees[frr.annees.length - 1]}, publiés par Eurostat pour la même facilité`)}.` : ''
  }</p>
<p class="aide">${h(frr.emplois.lecture)}</p>
<details><summary>Dépenses financées, par nature</summary><div class="tableau-defile"><table><caption>Dépenses publiques financées par la facilité pour la reprise et la résilience, par nature et par année</caption><thead><tr><th scope="col">Nature</th>${frr.annees
    .map((a) => `<th scope="col" class="nombre">${h(a)}</th>`)
    .join('')}</tr></thead><tbody>${frr.emplois.categories
    .map((c) => `<tr><th scope="row">${c.parent && c.parent !== 'TOTAL' ? 'dont ' : ''}${h(c.libelle)}</th>${c.montants_eur.map((x) => td(x)).join('')}</tr>`)
    .join('')}</tbody></table></div></details>
<p class="aide">Les bénéficiaires finaux ne sont pas repris : la Commission les publie dans une application en ligne sans fichier téléchargeable.</p>
${source(frr.source)}`
}

function blocOperations(ops: IndexOperations | null, choisie: string | null, q: string): string {
  if (!ops) return `<h2 id="fe-operations">Chercher une opération</h2>${absent('Listes d’opérations non disponibles.')}`
  const c = ops.couverture
  return `<h2 id="fe-operations">Chercher une opération dans les listes régionales</h2>
<p>Chaque région qui gère des fonds européens doit publier la liste des opérations qu’elle finance. Le site reprend ${h(entier(ops.listes.length))} listes publiées en données ouvertes : elles couvrent <strong>${h(
    entier(c.programmes_couverts.length),
  )} programmes régionaux sur ${h(entier(c.programmes_regionaux))}</strong> (fonds régionaux, fonds social, emploi des jeunes et transition juste). Les autres régions ne sont pas reprises, et le développement rural n’a volontairement aucune liste.</p>
${encadreManque(MANQUES.fondsEuropeensCommunes({ listes: ops.listes, inaccessible: ops.sources_inaccessibles?.[0] }))}
<p>${badgeStatut('trace')} Seuls les organismes et les entreprises en société (personnes morales) sont nommés, sous leur nom au répertoire SIRENE. Les autres opérations sont comptées ensemble, sans nom ni intitulé, avec la raison : <strong>agrégées</strong>.</p>
<div class="tableau-defile"><table><caption>Listes d’opérations reprises, ${h(ops.millesime)}</caption><thead><tr><th scope="col">Liste</th><th scope="col">Périodes</th><th scope="col">Fonds</th><th scope="col" class="nombre">Opérations</th><th scope="col" class="nombre">dont nommées</th><th scope="col" class="nombre">Part du coût des opérations nommées</th></tr></thead><tbody>${ops.listes
    .map(
      (l) =>
        `<tr><th scope="row">${h(l.autorite_de_gestion)}</th><td>${h(l.periodes.join(', '))}</td><td>${h(l.fonds.join(', '))}</td><td class="nombre">${h(entier(l.operations))}</td><td class="nombre">${h(entier(l.operations_nommees))}</td><td class="nombre">${
          typeof l.part_cout_nommee === 'number' ? h(pct(l.part_cout_nommee * 100, 0)) : 'non publié'
        }</td></tr>`,
    )
    .join('')}</tbody></table></div>
<form class="recherche carte" id="fe-ops-form" role="search" aria-label="Chercher une opération">
  ${choix({ id: 'fe-ops-liste', etiquette: 'Liste', options: ops.listes.map((l) => ({ valeur: l.id, libelle: `${l.autorite_de_gestion} (${l.periodes.join(', ')})` })), valeur: choisie ?? undefined })}
  <label for="fe-ops-q">Nom du bénéficiaire, intitulé ou commune</label>
  <input id="fe-ops-q" type="search" autocomplete="off" value="${h(q)}" />
</form>
<p id="fe-ops-statut" class="aide" aria-live="polite">${choisie ? 'Chargement de la liste…' : 'Choisis une liste : elle est chargée seulement à ce moment.'}</p>
<div id="fe-ops-resultats"></div>
${source(ops.source)}`
}

const PAR_PAGE = 25

/** Opérations nommées d'une liste qui contiennent le texte cherché, par ordre alphabétique du bénéficiaire. */
export function filtrer(l: Liste, q: string): Record<string, string | number | null>[] {
  const lignes = l.operations.map((o) => Object.fromEntries(l.colonnes.map((c, i) => [c, o[i] ?? null])))
  const n = normaliser(q)
  return lignes
    .filter((o) => !n || normaliser([o.denomination, o.intitule, o.siren, o.commune_insee, o.departement, o.theme].filter(Boolean).join(' ')).includes(n))
    .sort((a, b) => COLLATION.compare(String(a.denomination ?? ''), String(b.denomination ?? '')) || COLLATION.compare(String(a.id ?? ''), String(b.id ?? '')))
}

export function rendreListe(l: Liste, r: ListeResume, q: string, page: number): string {
  const calcule = l.montant_ue_mode !== 'publié'
  const trouvees = filtrer(l, q)
  const vues = trouvees.slice(0, page * PAR_PAGE)
  // Agrégats par période, fonds et motif (les années sont regroupées).
  const groupes = new Map<string, { periode: string; fonds: string; motif: string; nombre: number; cout: (number | null)[]; ue: (number | null)[] }>()
  for (const x of l.non_nommes) {
    const k = `${x.periode}|${x.fonds}|${x.motif}`
    const g = groupes.get(k) ?? { periode: x.periode, fonds: x.fonds, motif: x.motif, nombre: 0, cout: [], ue: [] }
    g.nombre += x.nombre
    g.cout.push(x.cout_total_eur)
    g.ue.push(x.montant_ue_eur)
    groupes.set(k, g)
  }
  return `<h3>${h(l.autorite_de_gestion)}</h3>
<p>${h(entier(r.operations))} opérations, dont ${h(entier(r.operations_nommees))} avec un bénéficiaire nommé. Liste collectée le ${h(dateFr(r.collecte_le))}, licence ${h(r.licence)}.</p>
<p>${
    calcule
      ? `La contribution de l’Union n’est pas publiée dans cette liste. ${badgeCalcule('coût total de l’opération multiplié par le taux de cofinancement publié pour la même opération')}`
      : `${badgeStatut('trace')} La contribution de l’Union est publiée dans cette liste.`
  }</p>
<div class="tableau-defile"><table><caption>${h(l.autorite_de_gestion)} : opérations par période et par fonds</caption><thead><tr><th scope="col">Période et fonds</th><th scope="col" class="nombre">Opérations</th><th scope="col" class="nombre">dont nommées</th><th scope="col" class="nombre">Coût total</th><th scope="col" class="nombre">Contribution de l’Union</th></tr></thead><tbody>${l.totaux
    .map((t) => `<tr><th scope="row">${h(t.periode)}, ${h(t.fonds)}</th><td class="nombre">${h(entier(t.operations))}</td><td class="nombre">${h(entier(t.operations_nommees))}</td>${td(t.cout_total_eur)}${td(t.montant_ue_eur)}</tr>`)
    .join('')}</tbody></table></div>
${
  l.comparaison_commission.length
    ? `<div class="tableau-defile"><table><caption>${h(l.autorite_de_gestion)} : coût des opérations de la liste et décidé transmis à la Commission européenne</caption><thead><tr><th scope="col">Période et fonds</th><th scope="col" class="nombre">Liste de la région</th><th scope="col" class="nombre">Transmis à la Commission</th><th scope="col" class="nombre">Écart</th></tr></thead><tbody>${l.comparaison_commission
        .map(
          (x) =>
            `<tr><th scope="row">${h(x.periode)}, ${h(x.fonds)}</th>${td(x.montant_eur)}<td class="nombre">${h(montant(x.autre_montant_eur))} (${h(dateFr(x.date_reference))})</td><td class="nombre">${h(montant(x.ecart_eur))}${
              typeof x.ecart_pct === 'number' ? ` (${h(pct(x.ecart_pct))})` : ''
            }</td></tr>`,
        )
        .join('')}</tbody></table></div><p class="aide">${h(l.comparaison_commission[0].lecture_ecart)}</p>`
    : ''
}
${
  groupes.size
    ? `<div class="tableau-defile"><table><caption>${h(l.autorite_de_gestion)} : opérations non nommées, agrégées</caption><thead><tr><th scope="col">Raison</th><th scope="col">Période et fonds</th><th scope="col" class="nombre">Opérations</th><th scope="col" class="nombre">Coût total</th><th scope="col" class="nombre">Contribution de l’Union</th></tr></thead><tbody>${[
        ...groupes.values(),
      ]
        .map(
          (g) =>
            `<tr><th scope="row">${h(majuscule(MOTIFS[g.motif] ?? l.motifs[g.motif] ?? g.motif))}</th><td>${h(g.periode)}, ${h(g.fonds)}</td><td class="nombre">${h(entier(g.nombre))}</td>${td(somme(g.cout))}${td(somme(g.ue))}</tr>`,
        )
        .join('')}</tbody></table></div>`
    : '<p>Toutes les opérations de cette liste ont un bénéficiaire nommé.</p>'
}
<h4>Opérations nommées${q.trim() ? ` contenant « ${h(q.trim())} »` : ''}</h4>
<p>${h(entier(trouvees.length))} opération${trouvees.length > 1 ? 's' : ''}, par ordre alphabétique du bénéficiaire.</p>
${
  vues.length
    ? `<div class="tableau-defile"><table><caption>${h(l.autorite_de_gestion)} : opérations nommées${q.trim() ? ` contenant « ${h(q.trim())} »` : ''}</caption><thead><tr><th scope="col">Bénéficiaire</th><th scope="col">Opération</th><th scope="col">Période et fonds</th><th scope="col" class="nombre">Début</th><th scope="col" class="nombre">Coût total</th><th scope="col" class="nombre">Contribution de l’Union</th></tr></thead><tbody>${vues
        .map(
          (o, i) =>
            `<tr${i === (page - 1) * PAR_PAGE ? ' data-premier' : ''}><th scope="row" tabindex="-1">${h(o.denomination)}</th><td>${o.intitule ? h(o.intitule) : 'intitulé non publié'}</td><td>${h(o.periode)}, ${h(o.fonds)}</td><td class="nombre">${h(o.annee_debut ?? 'non publié')}</td>${td(
              o.cout_total_eur as number | null,
            )}${td(o.montant_ue_eur as number | null)}</tr>`,
        )
        .join('')}</tbody></table></div>${
        trouvees.length > vues.length ? `<p><button type="button" class="bouton" id="fe-ops-plus">Afficher ${h(entier(Math.min(PAR_PAGE, trouvees.length - vues.length)))} opérations de plus</button></p>` : ''
      }`
    : ''
}
${source(l.source, l.millesime)}`
}

async function brancherOperations(cible: HTMLElement, ops: IndexOperations) {
  const form = cible.querySelector<HTMLFormElement>('#fe-ops-form')
  const zone = cible.querySelector<HTMLElement>('#fe-ops-resultats')
  const statut = cible.querySelector<HTMLElement>('#fe-ops-statut')
  if (!form || !zone || !statut) return
  const etat = { page: 1 }
  const dessiner = async (focusPremier = false) => {
    const id = valeurChoix(form, 'fe-ops-liste')
    const q = (form.querySelector('#fe-ops-q') as HTMLInputElement).value
    const r = ops.listes.find((x) => x.id === id)
    if (!r) {
      zone.innerHTML = ''
      statut.textContent = 'Choisis une liste : elle est chargée seulement à ce moment.'
      return
    }
    statut.textContent = 'Chargement de la liste…'
    let l: Liste
    try {
      l = await charger<Liste>(r.fichier)
    } catch (e) {
      if (!(e instanceof DonneeAbsente)) throw e
      zone.innerHTML = absent('Cette liste n’a pas pu être chargée.')
      statut.textContent = 'Liste non disponible.'
      return
    }
    zone.innerHTML = rendreListe(l, r, q, etat.page)
    appliquerLargeurs(zone)
    const n = filtrer(l, q).length
    statut.textContent = `${l.autorite_de_gestion} : ${entier(n)} opération${n > 1 ? 's' : ''} nommée${n > 1 ? 's' : ''} trouvée${n > 1 ? 's' : ''}.`
    zone.querySelector('#fe-ops-plus')?.addEventListener('click', () => {
      etat.page += 1
      void dessiner(true)
    })
    if (focusPremier) zone.querySelector<HTMLElement>('tr[data-premier] th')?.focus()
  }
  form.addEventListener('submit', (e) => e.preventDefault())
  form.addEventListener('input', (e) => {
    // Choix partagés (liste, recherche) : traités par l'écouteur change ci-dessous, une seule fois.
    if ((e.target as HTMLElement).closest('[data-choix]')) return
    etat.page = 1
    void dessiner()
  })
  form.addEventListener('change', () => {
    etat.page = 1
    void dessiner()
  })
  if (valeurChoix(form, 'fe-ops-liste')) await dessiner()
}

function blocEcarts(idx: Index): string {
  if (!idx.ecarts.length) return ''
  const noms = nomsFonds(idx)
  return `<h2 id="fe-ecarts">Écarts entre sources</h2>
<p>Quand deux jeux de données donnent deux montants pour la même chose, les deux sont publiés côte à côte. Aucun n’est retenu contre l’autre.</p>
<div class="tableau-defile"><table><caption>Écarts publiés entre les jeux de données de la Commission européenne</caption><thead><tr><th scope="col">Période et fonds</th><th scope="col">Ce qui est comparé</th><th scope="col" class="nombre">Montant</th><th scope="col" class="nombre">Autre montant</th><th scope="col" class="nombre">Écart</th><th scope="col">Lecture</th></tr></thead><tbody>${idx.ecarts
    .map(
      (e) =>
        `<tr><th scope="row">${h(e.periode)}, ${h(sansSigle(noms.get(e.fonds) ?? e.fonds))}</th><td>${h(majuscule(e.grandeur))}</td><td class="nombre">${h(montant(e.montant_eur))} (${h(e.source)})</td><td class="nombre">${h(montant(e.autre_montant_eur))} (${h(
          e.autre_source,
        )})</td>${td(e.ecart_eur)}<td>${h(majuscule(e.lecture_ecart))}</td></tr>`,
    )
    .join('')}</tbody></table></div>`
}

function blocLimitesSources(idx: Index, ops: IndexOperations | null): string {
  const inacc = [...idx.sources_inaccessibles]
  for (const s of ops?.sources_inaccessibles ?? []) if (!inacc.some((x) => x.source === s.source)) inacc.push(s)
  return `<h2 id="fe-limites">Limites et sources</h2>
<ul class="limites">${idx.limites.map((l) => `<li>${h(lisible(l))}</li>`).join('')}<li>${h(idx.perimetre.interreg)}</li><li>${h(idx.confidentialite)}</li></ul>
${
  inacc.length
    ? `<h3>Sources inaccessibles</h3><ul>${inacc
        .map((s) => `<li><strong>${h(s.source)}</strong> : ${h(s.constat)}.${s.effet ? ` ${h(majuscule(s.effet))}.` : ''}</li>`)
        .join('')}</ul>`
    : ''
}
<details><summary>Les ${h(entier(idx.sources.length))} jeux de données utilisés</summary><ul>${idx.sources
    .map(
      (s) =>
        `<li>${h(s.producteur)}, <span lang="${/^Liste des opérations/.test(s.titre) ? 'fr' : 'en'}">${h(s.titre)}</span> (${h(s.url)}), ${h(s.licence)}${s.mise_a_jour_source ? `, mis à jour le ${h(dateFr(s.mise_a_jour_source))}` : ''}${
          s.collecte_le ? `, collecté le ${h(dateFr(s.collecte_le))}` : ''
        }.</li>`,
    )
    .join('')}</ul></details>`
}

const SORTIES = `<p class="liens-sortie"><a href="#/explorer/ue">Ce que la France verse au budget de l’Union européenne</a> <a href="#/explorer/etat">Le budget de l’État, dont la contribution européenne</a></p>`

const LIEN_UE = `<p class="carte carte-contour">Cette page montre ce que l’Union européenne finance en France. Ce que la France verse chaque année au budget de l’Union est sur la page <a href="#/explorer/ue">La France et l’Union européenne</a>. Les montants des deux pages ne s’additionnent pas et ne se compensent pas : le site ne calcule aucun solde entre ce qui est versé et ce qui est financé.</p>`

export async function rendre(cible: HTMLElement, params: URLSearchParams): Promise<Rendu | void> {
  const idx = await chargerSiPresent<Index>('fonds_europeens/index.json')
  if (!idx) {
    cible.innerHTML = `<h1>Les fonds européens en France</h1>
<p class="chapeau">Ce que l’Union européenne finance en France par ses fonds régionaux, social, agricole et pour la pêche.</p>
${absent('Données en cours d’intégration.')}
${SORTIES}
${partPersonnelle()}`
    return
  }
  const [regions, themes, annees, frr, ops] = await Promise.all([
    chargerSiPresent<Regions>('fonds_europeens/regions.json'),
    chargerSiPresent<Themes>('fonds_europeens/themes.json'),
    chargerSiPresent<Annees>('fonds_europeens/annees.json'),
    chargerSiPresent<Frr>('fonds_europeens/frr.json'),
    chargerSiPresent<IndexOperations>('fonds_europeens/operations.json'),
  ])
  const regionDemandee = params.get('region')
  const region = regionDemandee && regions?.regions.some((r) => r.code === regionDemandee) ? regionDemandee : null
  const listeDemandee = params.get('liste')
  const liste = listeDemandee && ops?.listes.some((l) => l.id === listeDemandee) ? listeDemandee : null
  const q = params.get('q') ?? ''
  cible.innerHTML = `
<h1>Les fonds européens en France</h1>
<p class="chapeau">Tu vois ici ce que l’Union européenne finance en France par ses fonds pour les régions, l’emploi, le développement rural et la pêche, et par son plan de relance : les montants prévus, décidés, dépensés et payés, ce qu’ajoutent les financeurs français, par région, par thème et par année, et les opérations de six listes régionales. La page ne montre pas les aides de la politique agricole commune versées directement aux exploitants, ni les bénéficiaires des autres régions, ni ce que la France verse au budget européen.</p>
${LIEN_UE}
<p>Chaque montant porte son année, sa source et son statut :</p>
${legendeStatuts()}
${blocCle(idx)}
${blocFonds(idx)}
${blocPeriodes(idx)}
${blocRegions(regions, idx, region)}
${blocThemes(themes, idx)}
${blocAnnees(annees, frr)}
${blocOperations(ops, liste, q)}
${blocEcarts(idx)}
${blocLimitesSources(idx, ops)}
<h2>Pour aller plus loin</h2>
${SORTIES}
${partPersonnelle()}`
  appliquerLargeurs(cible)
  cible.querySelector<HTMLSelectElement>('#fe-region')?.addEventListener('change', (e) => {
    const code = (e.target as HTMLSelectElement).value
    const zone = cible.querySelector<HTMLElement>('#fe-region-detail')
    if (zone && regions) {
      zone.innerHTML = code ? detailRegion(regions.regions.find((r) => r.code === code) ?? null, idx) : ''
      appliquerLargeurs(zone)
    }
  })
  return { suite: ops ? brancherOperations(cible, ops) : undefined }
}

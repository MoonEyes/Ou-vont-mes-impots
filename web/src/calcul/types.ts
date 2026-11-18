// Types du contrat d'interface 1.0 (docs/contrat_interface.md, docs/schemas/).

export type Zone = 'metropole' | 'dom' | 'etranger'
export type Situation = 'celibataire' | 'parent_isole' | 'couple_marie_pacse' | 'couple_union_libre'
export type StatutActivite =
  | 'salarie_prive'
  | 'sans_activite'
  | 'fonctionnaire'
  | 'contractuel_public'
  | 'independant'
  | 'retraite'
  | 'demandeur_emploi'
  | 'apprenti'
  | 'etudiant'

export interface Enfant {
  annee_naissance: number
  garde_alternee?: boolean
}

export interface Personne {
  role: 'declarant1' | 'declarant2'
  annee_naissance?: number
  statut_activite: StatutActivite
  frontalier?: boolean
  cadre?: boolean
  temps_travail?: { type: 'temps_plein' } | { type: 'temps_partiel'; quotite: number }
  salaire_net_avant_impot_mensuel?: number
}

export interface Profil {
  version_contrat: '1.0'
  annee_revenus: number
  residence: { zone: Zone; alsace_moselle: boolean; commune_insee?: string }
  foyer: { situation: Situation; enfants: Enfant[] }
  logement?: { statut: 'locataire' | 'proprietaire' | 'loge_gratuitement'; taxe_fonciere_annuelle_eur?: number | null }
  personnes: Personne[]
}

export interface Fourchette {
  bas: number
  central: number
  haut: number
}

export type IdDestinataire =
  | 'cnam'
  | 'cnav'
  | 'cnaf'
  | 'branche_atmp'
  | 'cnsa'
  | 'cades'
  | 'agirc_arrco'
  | 'unedic'
  | 'ags'
  | 'apec'
  | 'fnal'
  | 'france_competences'
  | 'aom'
  | 'etat'
  | 'commune'
  | 'epci'
  | 'departement'
  | 'plusieurs'
  | 'fsv'
  | 'cas_pensions'
  | 'cnracl'
  | 'ircantec'
  | 'erafp'
  | 'rci_independants'
  | 'regime_local_am'

export type Administration = 'Etat' | 'Collectivites locales' | 'Securite sociale' | 'Plusieurs'

export interface Destinataire {
  /** identifiant du contrat (3.5) ou de prelevements/affectation.json (contrat 1.4) */
  id: IdDestinataire | string
  nom: string
  administration: Administration
}

// taxe_consommation : lignes hors bulletin calculées par le site (contrat 1.4, prelevements/tva_conso.json).
export type Famille = 'cotisation_salariale' | 'csg_crds' | 'impot_revenu' | 'cotisation_patronale' | 'impot_local' | 'taxe_consommation'

export interface Prelevement {
  id: string
  libelle: string
  famille: Famille
  personne: 'declarant1' | 'declarant2' | 'foyer' | 'logement'
  assiette_annuelle_eur?: number | null
  taux?: number | null
  montant_annuel_eur: Fourchette
  nature?: 'prelevement' | 'reduction'
  destinataire: Destinataire
  ventilation?: { destinataire: string; part: number; source?: string }[]
  /** statut de la répartition dans prelevements/affectation.json */
  statut_affectation?: 'sourcee' | 'non sourcee'
  /** montant non chiffrable faute de source (ex. tabac pour un fumeur) : exclu des totaux */
  non_chiffre?: boolean
  note?: string
  source?: string
  inclus_dans_total_paye: boolean
  regle: string
  hypothese_fourchette?: string
}

export type CodeAvertissement =
  | 'RECOUPEMENT_DIVERGENT'
  | 'RECOUPEMENT_INDISPONIBLE'
  | 'DONNEE_ABSENTE'
  | 'COMMUNE_INCONNUE'
  | 'TEOM_ABSENTE'
  | 'SAISIE_ATYPIQUE'

export interface Avertissement {
  code: CodeAvertissement
  message: string
  champ?: string
  details?: Record<string, unknown>
}

export interface ResultatOk {
  statut: 'ok'
  version_contrat: '1.0'
  annee_legislation: number
  moteur: { nom: 'modele-social'; version: string; publicodes?: string }
  entree: {
    personnes: {
      role: 'declarant1' | 'declarant2'
      salaire_net_avant_impot_annuel: number
      salaire_brut_annuel_estime: Fourchette
    }[]
  }
  prelevements: Prelevement[]
  totaux: {
    paye_par_le_foyer: Fourchette
    patronal: Fourchette
    cout_total_employeur?: Fourchette
    par_destinataire: { destinataire: string; montant_annuel_eur: Fourchette; inclut_patronal: boolean }[]
  }
  avertissements: Avertissement[]
}

export type CodeErreur =
  | 'PROFIL_HORS_V1'
  | 'SAISIE_INVALIDE'
  | 'COMMUNE_INCONNUE'
  | 'DONNEE_ABSENTE'
  | 'MOTEUR_INDISPONIBLE'
  | 'CONTRAT_INCOMPATIBLE'

export type MotifHorsV1 =
  | 'fonctionnaire'
  | 'contractuel_public'
  | 'independant'
  | 'retraite'
  | 'demandeur_emploi'
  | 'apprenti'
  | 'etudiant'
  | 'sans_activite_seul'
  | 'dom'
  | 'etranger'
  | 'frontalier'
  | 'alsace_moselle'

export interface ResultatErreur {
  statut: 'erreur'
  version_contrat: '1.0'
  erreur: {
    code: CodeErreur
    message: string
    motif?: MotifHorsV1
    champ?: string
    fichier?: string
    redirection?: { libelle: string; url: string }
  }
}

export type Resultat = ResultatOk | ResultatErreur

// ---------------------------------------------------------------------------------------------------------------
// Profils étendus (calculerProfil, moteur-etendu.ts). Sur-ensemble du contrat 1.0 : tous les champs ajoutés sont
// optionnels, un profil du contrat 1.0 reste valide. Détail des champs par profil : calcul/README.md.
// ---------------------------------------------------------------------------------------------------------------

export type Versant = 'etat' | 'territoriale' | 'hospitaliere'
export type ActiviteMicro = 'vente' | 'service_bic' | 'service_bnc'
export type TauxCsgRetraite = 'exonere' | 'reduit' | 'median' | 'normal'

export interface Independant {
  /** micro : micro-entrepreneur (vérifié) ; reel : artisan, commerçant ou profession libérale au réel (non vérifié, désactivé par défaut) */
  regime: 'micro' | 'reel'
  /** micro : vente de marchandises, prestation de service commerciale ou artisanale (BIC), prestation libérale (BNC, régime général) */
  activite?: ActiviteMicro
  /** micro : activité artisanale (contribution à la formation et taxe de chambre de métiers différentes) */
  artisan?: boolean
  /** micro : chiffre d'affaires encaissé sur l'année, hors taxes */
  chiffre_affaires_annuel?: number
  /** micro : option pour le versement libératoire de l'impôt sur le revenu */
  versement_liberatoire?: boolean
  /** reel : nature de l'activité */
  categorie?: 'artisan' | 'commercant' | 'liberale'
  /** reel : résultat fiscal annuel (revenu professionnel) */
  revenu_professionnel_annuel?: number
}

export interface PersonneEtendue extends Personne {
  // Fonctionnaire titulaire
  versant?: Versant
  /** traitement indiciaire brut mensuel (avec NBI) ; s'il manque, il est retrouvé à partir du net saisi */
  traitement_indiciaire_brut_mensuel?: number
  /** total mensuel brut des primes et indemnités (résidence, supplément familial, indemnités) ; 0 s'il n'y en a pas */
  primes_mensuelles?: number
  // Retraité
  /** pensions de base (régime général, fonction publique, etc.) et complémentaires (Agirc-Arrco, Ircantec), par mois */
  pension_base_mensuelle?: number
  pension_complementaire_mensuelle?: number
  /** nature des montants de pension saisis (défaut : nette avant impôt) */
  pension_saisie?: 'nette_avant_impot' | 'brute'
  /** taux de CSG lu sur le relevé de pension, ou revenu fiscal de référence de l'avant-dernière année et nombre de parts */
  csg_pension?: { taux: TauxCsgRetraite } | { revenu_fiscal_reference: number; parts: number }
  // Indépendant
  independant?: Independant
  // Apprenti
  apprentissage?: { contrat_avant_mars_2025: boolean }
}

export interface ProfilEtendu extends Omit<Profil, 'personnes'> {
  personnes: PersonneEtendue[]
}

export type ProfilCalcule =
  | 'salarie_prive'
  | 'fonctionnaire'
  | 'contractuel_public'
  | 'retraite'
  | 'micro_entrepreneur'
  | 'independant_reel'
  | 'apprenti'
  | 'sans_activite'

export interface EntreePersonneEtendue {
  role: 'declarant1' | 'declarant2'
  profil: ProfilCalcule
  /** revenu net avant impôt de l'année (salaire, pension ; chiffre d'affaires moins cotisations pour un indépendant) */
  salaire_net_avant_impot_annuel: number
  /** revenu brut de l'année (salaire brut, traitement et primes, pension brute, chiffre d'affaires) */
  salaire_brut_annuel_estime: Fourchette
  /** revenu retenu pour l'impôt avant abattement (salaire ou pension imposable, chiffre d'affaires du régime micro) */
  revenu_imposable_annuel: number
  /** précisions propres au profil (traitement, primes, taux de CSG appliqué, pensions brutes) */
  detail?: Record<string, number | string>
}

export interface AffectationManquante {
  /** identifiant de la ligne de prélèvement sans entrée dans prelevements/affectation.json */
  id: string
  libelle: string
  /** identifiant proposé pour l'entrée à créer dans affectation.json (aucune répartition n'est supposée) */
  cle_proposee: string
}

export interface VerificationProfil {
  profil: ProfilCalcule | 'alsace_moselle' | 'foyer'
  statut: 'verifie' | 'non verifie'
  /** source de la vérification et tolérance (détail dans web/ECARTS.md) */
  reference: string
}

export interface ResultatOkEtendu extends Omit<ResultatOk, 'entree'> {
  entree: { personnes: EntreePersonneEtendue[] }
  /** millésime des barèmes appliqués (une seule année gérée) */
  millesime: { annee_revenus: number; baremes: string }
  verifications: VerificationProfil[]
  /** lignes sans affectation publiée : destinataire « non publié », jamais de répartition supposée */
  affectations_manquantes: AffectationManquante[]
}

export type MotifHorsPerimetre =
  | MotifHorsV1
  | 'annee_non_couverte'
  | 'independant_reel_non_verifie'
  | 'retraite_alsace_moselle'
  | 'independant_alsace_moselle_non_verifie'

export interface ResultatErreurEtendu {
  statut: 'erreur'
  version_contrat: '1.0'
  erreur: Omit<ResultatErreur['erreur'], 'motif'> & { motif?: MotifHorsPerimetre }
}

export type ResultatEtendu = ResultatOkEtendu | ResultatErreurEtendu

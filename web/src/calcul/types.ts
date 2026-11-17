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

// Barèmes 2025 (revenus 2025) des profils que modele-social ne couvre pas : fonction publique, retraités,
// impôt sur les pensions et le micro-entrepreneur. Chaque valeur porte sa source ; les valeurs marquées
// « OpenFisca » ont été relues dans les paramètres publics d'openfisca-france 175.0.45 (API publique OpenFisca, /parameter).
// Millésime unique : toute autre année de revenus est refusée par calculerProfil (pas de barème extrapolé).

export const MILLESIME_BAREMES = 2025

export const BAREMES_2025 = {
  /** Plafond annuel de la Sécurité sociale 2025 (arrêté du 19/12/2024 ; OpenFisca prelevements_sociaux.pss). */
  pass: 47100,
  /** SMIC horaire brut au 01/11/2024, inchangé en 2025 (décret 2024-951) ; 151,67 h par mois. */
  smicHoraire: 11.88,
  smicAnnuel: 11.88 * 151.67 * 12,

  csgCrdsActivite: {
    /** CSG et CRDS sur les revenus d'activité : assiette 98,25 % du brut jusqu'à 4 plafonds, 100 % au-delà (CSS L136-1-1). */
    abattementAssiette: 0.9825,
    plafondAbattementEnPass: 4,
    csgDeductible: 0.068,
    csgNonDeductible: 0.024,
    crds: 0.005,
  },

  fonctionPublique: {
    /** Retenue pour pension civile et CNRACL : 11,10 % du traitement indiciaire depuis 2020 (décret 2010-1749 ; OpenFisca). */
    retenuePension: 0.111,
    /** RAFP : 5 % agent et 5 % employeur sur les primes, dans la limite de 20 % du traitement indiciaire (décret 2004-569 ; OpenFisca). */
    rafp: 0.05,
    rafpPlafondAssiette: 0.2,
    employeur: {
      /** Contribution employeur au CAS Pensions, personnels civils : 78,28 % en 2025 (décret 2024-1255 ; OpenFisca). */
      casPensionsCivils: 0.7828,
      /** Allocation temporaire d'invalidité (État) : 0,32 % (OpenFisca). */
      ati: 0.0032,
      /** Contribution employeur à la CNRACL : 34,65 % en 2025 (décret 2025-86 du 30/01/2025 ; OpenFisca). */
      cnracl: 0.3465,
      /** ATIACL (territoriale et hospitalière) : 0,40 % (OpenFisca). */
      atiacl: 0.004,
      /** Fonds pour l'emploi hospitalier : 0,80 % (OpenFisca). */
      feh: 0.008,
      /** Maladie, maternité, invalidité, décès : 9,70 % pour l'État (OpenFisca). */
      maladieEtat: 0.097,
      /**
       * Maladie des employeurs territoriaux et hospitaliers : 9,88 % en 2025. Le taux de 8,88 % n'a valu que pour 2024
       * (décret 2024-49) ; OpenFisca 175.0.45 garde 8,88 % en 2025 (écart documenté dans ECARTS.md).
       * Source 2025 : récapitulatif des cotisations du CDG 33 au 01/05/2025.
       */
      maladieCnracl: 0.0988,
      allocationsFamiliales: 0.0525,
      csa: 0.003,
      /** FNAL : 0,10 % du traitement plafonné (moins de 50 agents) ou 0,50 % du traitement (50 et plus). */
      fnalMoinsDe50: 0.001,
      fnal50EtPlus: 0.005,
    },
  },

  ircantec: {
    /** Taux appelés depuis 2017 (OpenFisca) : tranche A jusqu'au plafond, tranche B de 1 à 8 plafonds. */
    salarieA: 0.028,
    salarieB: 0.0695,
    employeurA: 0.042,
    employeurB: 0.1255,
    plafondBEnPass: 8,
  },

  pensions: {
    /** Seuils de revenu fiscal de référence (RFR de 2023, pour une part) appliqués en 2025, métropole (CSS L136-8 ; OpenFisca). */
    seuilExoneration: { unePart: 12817, demiPartSupplementaire: 3422 },
    seuilTauxReduit: { unePart: 16755, demiPartSupplementaire: 4474 },
    seuilTauxMedian: { unePart: 26004, demiPartSupplementaire: 6941 },
    taux: {
      exonere: { deductible: 0, nonDeductible: 0 },
      reduit: { deductible: 0.038, nonDeductible: 0 },
      median: { deductible: 0.042, nonDeductible: 0.024 },
      normal: { deductible: 0.059, nonDeductible: 0.024 },
    },
    crds: 0.005,
    /** Contribution additionnelle de solidarité pour l'autonomie : 0,3 %, aux taux médian et normal seulement (OpenFisca). */
    casa: 0.003,
    /** Cotisation d'assurance maladie sur les retraites complémentaires : 1 %, sauf exonération de CSG (CSS D242-8 ; paramètre OpenFisca mmid_ret.regimes_comp). */
    maladieComplementaire: 0.01,
  },

  impot: {
    /** Abattement de 10 % sur les pensions, revenus 2025 : minimum 454 € par pensionné, plafond 4 439 € par foyer (CGI art. 158, 5-a ; loi de finances pour 2026). */
    abattementPensions: { taux: 0.1, minimumParPensionne: 454, plafondParFoyer: 4439 },
    /**
     * Abattement des personnes de plus de 65 ans au 31 décembre (nées avant 1961 pour les revenus 2025), CGI art. 157 bis,
     * revenus 2025 : 2 822 € par personne si le revenu net global ne dépasse pas 17 670 €, 1 411 € jusqu'à 28 430 €.
     * OpenFisca 175.0.45 garde les montants des revenus 2024 (2 795 € et 1 398 €, seuils 17 510 € et 28 170 €).
     */
    abattementAge: { ageMinimum: 65, plein: 2822, seuilPlein: 17670, reduit: 1411, seuilReduit: 28430 },
    /** Abattements forfaitaires du régime micro (CGI art. 50-0 et 102 ter ; OpenFisca), minimum 305 €. */
    abattementMicro: { vente: 0.71, service_bic: 0.5, service_bnc: 0.34, minimum: 305 },
    /** Plafonds de chiffre d'affaires du régime micro, 2023 à 2025 (OpenFisca). */
    plafondMicro: { vente: 188700, service_bic: 77700, service_bnc: 77700 },
    /** Salaire des apprentis exonéré d'impôt à hauteur du SMIC annuel (CGI art. 81 bis) : 11,88 x 151,67 x 12, arrondi à l'euro. */
    exonerationApprenti: 21622,
  },

  outreMer: {
    /**
     * Réduction de l'impôt sur le revenu des foyers domiciliés dans un département d'outre-mer (CGI art. 197, I-3),
     * appliquée à l'impôt après plafonnement du quotient familial et avant la décote : 30 % plafonnés à 2 450 €
     * (Guadeloupe, Martinique, La Réunion), 40 % plafonnés à 4 050 € (Guyane, Mayotte), plafonds en vigueur depuis
     * les revenus 2018. OpenFisca 175.0.45, impot_revenu.calcul_impot_revenu.plaf_qf.abat_dom (référence Légifrance
     * LEGIARTI000006308322).
     */
    reductionImpot: {
      guadeloupe: { taux: 0.3, plafond: 2450 },
      martinique: { taux: 0.3, plafond: 2450 },
      reunion: { taux: 0.3, plafond: 2450 },
      guyane: { taux: 0.4, plafond: 4050 },
      mayotte: { taux: 0.4, plafond: 4050 },
    },
    /**
     * TVA : 8,5 % (taux normal) et 2,1 % (taux réduit) en Guadeloupe, Martinique et à La Réunion (CGI art. 296) ;
     * provisoirement non applicable en Guyane et à Mayotte (CGI art. 294). Source : impots.gouv.fr, « Quels sont les
     * différents taux de TVA applicables dans les DOM ? », consulté le 19/11/2026. Affichés seulement : le site
     * n'estime pas la TVA payée outre-mer (voir hors-bulletin.ts).
     */
    tva: {
      source: 'https://www.impots.gouv.fr/professionnel/questions/quels-sont-les-differents-taux-de-tva-applicables-dans-les-dom',
      consulte: '2026-11-19',
      guadeloupe: { normal: 0.085, reduit: 0.021 },
      martinique: { normal: 0.085, reduit: 0.021 },
      reunion: { normal: 0.085, reduit: 0.021 },
      guyane: null,
      mayotte: null,
    },
  },
} as const

export type TauxCsgPension = keyof typeof BAREMES_2025.pensions.taux

/** Assiette de la CSG et de la CRDS sur un revenu d'activité brut annuel. */
export function assietteCsgActivite(brutAnnuel: number): number {
  const c = BAREMES_2025.csgCrdsActivite
  const limite = c.plafondAbattementEnPass * BAREMES_2025.pass
  return c.abattementAssiette * Math.min(brutAnnuel, limite) + Math.max(0, brutAnnuel - limite)
}

/** Taux de CSG d'un retraité d'après le revenu fiscal de référence de l'avant-dernière année et le nombre de parts. */
export function tauxCsgPension(revenuFiscalReference: number, parts: number): TauxCsgPension {
  const p = BAREMES_2025.pensions
  const seuil = (s: { unePart: number; demiPartSupplementaire: number }) => s.unePart + (parts - 1) * 2 * s.demiPartSupplementaire
  if (revenuFiscalReference <= seuil(p.seuilExoneration)) return 'exonere'
  if (revenuFiscalReference <= seuil(p.seuilTauxReduit)) return 'reduit'
  if (revenuFiscalReference <= seuil(p.seuilTauxMedian)) return 'median'
  return 'normal'
}

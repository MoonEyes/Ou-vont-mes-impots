// Calcul personnel étendu à tous les profils (calculerProfil), exécuté dans le navigateur, sans appel réseau.
//
// - salarié du privé, apprenti, temps partiel, SMIC, Alsace-Moselle : règles de modele-social telles quelles ;
// - micro-entrepreneur : règles de modele-social telles quelles (cotisations, versement libératoire) ;
// - contractuel de droit public : règles de modele-social pour le régime général, barème Ircantec du site ;
// - fonctionnaire titulaire, retraité : barèmes 2025 du site (baremes-2025.ts), absents de modele-social ;
// - impôt sur le revenu : barème et quotient familial de modele-social, abattements par nature de revenu.
//
// Chaque profil est vérifié sur des cas types (tests/cas_types/cas_types_profils.json, web/ECARTS.md).
// Ce qui n'a pas pu être vérifié est refusé par défaut (option autoriserNonVerifie). API décrite dans README.md.
import { DESTINATAIRES } from './destinataires'
import { BAREMES_2025 as B, MILLESIME_BAREMES, assietteCsgActivite, tauxCsgPension } from './baremes-2025'
// Contrôle de saisie et de périmètre : module léger, partagé avec l'écran de saisie (fil principal).
import { profilDe, verifierProfilEtendu } from './perimetre-etendu'
export { profilDe, verifierProfilEtendu }
import {
  HYPOTHESE_FOURCHETTE_PATRONALE,
  SCENARIOS_OPENFISCA,
  SCENARIOS_SITE,
  arrondi,
  assemblerResultat,
  calculerSalarie,
  evaluer,
  f,
  f3,
  impotFoyer,
  lignesSalarie,
  obtenirMoteur,
  situationSalarie,
  suffixe,
  type Affectation,
  type Hypotheses,
  type OptionsCalcul,
  type Scenarios,
  type VarianteSalarie,
} from './moteur'
import type {
  ActiviteMicro,
  AffectationManquante,
  Avertissement,
  Destinataire,
  EntreePersonneEtendue,
  Fourchette,
  PersonneEtendue,
  Prelevement,
  ProfilEtendu,
  ResultatEtendu,
  TauxCsgRetraite,
  VerificationProfil,
} from './types'

export interface OptionsCalculEtendu extends OptionsCalcul {
  /** accepte les profils et combinaisons non vérifiés (indépendant au réel, régime local hors salarié du privé) */
  autoriserNonVerifie?: boolean
}

type Role = 'declarant1' | 'declarant2'

/** Destinataire des lignes sans entrée dans prelevements/affectation.json : aucune répartition n'est supposée. */
export const NON_AFFECTE: Destinataire = {
  id: 'non_affecte',
  nom: 'Destinataire non publié dans les données du site',
  administration: 'Plusieurs',
}

/**
 * Lignes sans affectation publiée, avec la clé à créer dans prelevements/affectation.json.
 * Tant que la clé manque, la ligne garde le destinataire NON_AFFECTE.
 */
export const CLES_AFFECTATION_A_CREER: Record<string, string> = {
  retenue_pension_civile: 'pension_civile_etat',
  retenue_cnracl: 'cnracl',
  rafp_salarie: 'rafp',
  rafp_employeur: 'rafp',
  contribution_cas_pensions: 'pension_civile_etat',
  contribution_cnracl: 'cnracl',
  ati: 'allocation_temporaire_invalidite',
  atiacl: 'atiacl',
  fonds_emploi_hospitalier: 'fonds_emploi_hospitalier',
  ircantec_salarie: 'ircantec',
  ircantec_employeur: 'ircantec',
  csg_pension_deductible: 'csg_remplacement',
  csg_pension_non_deductible: 'csg_remplacement',
  casa: 'casa',
  maladie_retraite_complementaire: 'maladie_retraite_complementaire',
  micro_maladie_maternite: 'independants_maladie_maternite',
  micro_invalidite_deces: 'independants_invalidite_deces',
  micro_retraite_base: 'independants_retraite_base',
  micro_retraite_complementaire: 'independants_retraite_complementaire',
  micro_formation_professionnelle: 'independants_formation_professionnelle',
  micro_taxe_chambre_consulaire: 'taxe_frais_chambre_consulaire',
  maladie_regime_local: 'regime_local_alsace_moselle',
  independant_maladie: 'independants_maladie_maternite',
  independant_indemnites_journalieres: 'independants_maladie_maternite',
  independant_retraite_base: 'independants_retraite_base',
  independant_retraite_complementaire: 'independants_retraite_complementaire',
  independant_invalidite_deces: 'independants_invalidite_deces',
  independant_formation_professionnelle: 'independants_formation_professionnelle',
  independant_allocations_familiales: 'independants_allocations_familiales',
  // Lignes du contrat 1.0 déjà sans entrée dans affectation.json (destinataire du contrat 3.5 conservé).
  cet_salarie: 'cet',
  cet_employeur: 'cet',
  apec_salarie: 'apec',
  apec_employeur: 'apec',
  ags: 'ags',
  formation_professionnelle: 'formation_professionnelle',
  taxe_apprentissage: 'taxe_apprentissage',
  versement_mobilite: 'versement_mobilite',
  forfait_social: 'forfait_social',
  reduction_generale: 'reduction_generale',
  autres_cotisations_salarie: 'autres_cotisations_salarie',
}

export const VERIFICATIONS: Record<VerificationProfil['profil'], VerificationProfil> = {
  salarie_prive: { profil: 'salarie_prive', statut: 'verifie', reference: 'OpenFisca, 20 cas types de salariés et 6 cas à temps partiel ou au SMIC, tolérance 1 %' },
  fonctionnaire: { profil: 'fonctionnaire', statut: 'verifie', reference: 'OpenFisca, 5 cas types (État, territoriale, hospitalière), tolérance 1 %' },
  contractuel_public: { profil: 'contractuel_public', statut: 'verifie', reference: 'OpenFisca, 3 cas types, tolérance 1 %' },
  retraite: { profil: 'retraite', statut: 'verifie', reference: 'OpenFisca, 5 cas types (4 taux de CSG, couple), tolérance 1 % ; cotisation maladie de 1 % : taux relu dans OpenFisca, montant non recoupé' },
  micro_entrepreneur: { profil: 'micro_entrepreneur', statut: 'verifie', reference: 'simulateur mon-entreprise de l’Urssaf (cotisations) et OpenFisca (impôt, versement libératoire), 6 cas types, tolérance 1 %' },
  independant_reel: { profil: 'independant_reel', statut: 'non verifie', reference: 'aucune référence indépendante : OpenFisca applique l’assiette d’avant la réforme de 2025' },
  apprenti: { profil: 'apprenti', statut: 'verifie', reference: 'simulateur mon-entreprise de l’Urssaf (3 cas types) et OpenFisca (1 cas sous le seuil), tolérance 1 %' },
  sans_activite: { profil: 'sans_activite', statut: 'verifie', reference: 'aucun prélèvement sur le revenu' },
  alsace_moselle: { profil: 'alsace_moselle', statut: 'verifie', reference: 'OpenFisca corrigé du taux en vigueur (1,3 %) et simulateur mon-entreprise de l’Urssaf, 3 cas types, tolérance 1 %' },
  foyer: { profil: 'foyer', statut: 'verifie', reference: 'OpenFisca, 6 foyers à revenus de natures différentes, tolérance 1 % sur l’impôt' },
}

// --- Calcul par personne ----------------------------------------------------------------------------------------

interface RevenusImposables {
  /** personne de plus de 65 ans au 31 décembre de l'année de revenus (abattement de l'article 157 bis du CGI) */
  plusDe65?: boolean
  /** salaire imposable (abattement de 10 % appliqué ensuite, par personne) */
  salaire?: number
  /** pension imposable (abattement de 10 % appliqué ensuite, plafonné par foyer) */
  pension?: number
  /** revenu net déjà abattu, imposé au barème (bénéfice du régime micro ou réel) */
  net?: number
  /** revenu net déjà abattu soumis au versement libératoire (compte pour le taux effectif) */
  liberatoire?: number
}

interface CalculPersonne {
  entree: EntreePersonneEtendue
  prelevements: Prelevement[]
  avertissements: Avertissement[]
  /** brut versé par un employeur, pour le coût total employeur (0 hors salariat) */
  brutEmployeur: number
  revenus: RevenusImposables
  /** valeurs agrégées comparées aux références dans les tests */
  agregats: Record<string, number>
}

interface Brouillon {
  id: string
  libelle: string
  famille: Prelevement['famille']
  montant: Fourchette | number
  regle: string
  assiette?: number | null
  taux?: number | null
  /** destinataire du contrat (3.5) quand l'affectation existe ; sinon la ligne est « non affectée » */
  destinataire?: Destinataire
  hypothese?: string
  note?: string
  nature?: 'reduction'
}

function ligne(role: Role, b: Brouillon): Prelevement {
  const montant = typeof b.montant === 'number' ? f(b.montant) : b.montant
  return {
    id: suffixe(b.id, role),
    libelle: b.libelle,
    famille: b.famille,
    personne: role,
    assiette_annuelle_eur: b.assiette === undefined || b.assiette === null ? null : arrondi(b.assiette),
    taux: b.taux ?? null,
    montant_annuel_eur: montant,
    ...(b.nature ? { nature: b.nature } : {}),
    destinataire: b.destinataire ?? NON_AFFECTE,
    ...(b.destinataire ? {} : { statut_affectation: 'non sourcee' as const }),
    inclus_dans_total_paye: b.famille !== 'cotisation_patronale',
    regle: b.regle,
    ...(b.hypothese ? { hypothese_fourchette: b.hypothese } : {}),
    ...(b.note ? { note: b.note } : {}),
  }
}

function lignesCsgCrdsActivite(role: Role, assiette: number, regle: string): Prelevement[] {
  const c = B.csgCrdsActivite
  return [
    ligne(role, { id: 'csg_deductible', libelle: 'CSG déductible', famille: 'csg_crds', assiette, taux: c.csgDeductible, montant: assiette * c.csgDeductible, destinataire: DESTINATAIRES.plusieurs, regle }),
    ligne(role, { id: 'csg_non_deductible', libelle: 'CSG non déductible', famille: 'csg_crds', assiette, taux: c.csgNonDeductible, montant: assiette * c.csgNonDeductible, destinataire: DESTINATAIRES.plusieurs, regle }),
    ligne(role, { id: 'crds', libelle: 'CRDS (remboursement de la dette sociale)', famille: 'csg_crds', assiette, taux: c.crds, montant: assiette * c.crds, destinataire: DESTINATAIRES.cades, regle }),
  ]
}

const HYPOTHESE_FOURCHETTE_PUBLIQUE =
  'Bas : moins de 50 agents (FNAL 0,1 % du traitement plafonné), pas de versement mobilité. Haut : 50 agents et plus (FNAL 0,5 %), versement mobilité 3,2 % (Paris). Central : 50 agents et plus, sans versement mobilité.'

const SEUILS_MOINS_DE_50 = ['moins de 5', 'moins de 11', 'moins de 20', 'moins de 50']
function fnalPublic(assiette: number, h: Hypotheses): number {
  const e = B.fonctionPublique.employeur
  return h.effectifSeuil && SEUILS_MOINS_DE_50.includes(h.effectifSeuil) ? e.fnalMoinsDe50 * Math.min(assiette, B.pass) : e.fnal50EtPlus * assiette
}
const parScenario = (sc: Scenarios, calcul: (h: Hypotheses) => number): Fourchette => f3(calcul(sc.bas), calcul(sc.central), calcul(sc.haut))

// Fonctionnaire titulaire ------------------------------------------------------------------------------------------

/** Net avant impôt annuel d'un fonctionnaire à partir du traitement indiciaire et des primes (bruts annuels). */
function retenuesFonctionnaire(traitement: number, primes: number) {
  const fp = B.fonctionPublique
  const c = B.csgCrdsActivite
  const pension = fp.retenuePension * traitement
  const assietteRafp = Math.min(primes, fp.rafpPlafondAssiette * traitement)
  const rafp = fp.rafp * assietteRafp
  const assietteCsg = assietteCsgActivite(traitement + primes)
  const csgDeductible = c.csgDeductible * assietteCsg
  const csgNonDeductible = c.csgNonDeductible * assietteCsg
  const crds = c.crds * assietteCsg
  const net = traitement + primes - pension - rafp - csgDeductible - csgNonDeductible - crds
  return { pension, assietteRafp, rafp, assietteCsg, csgDeductible, csgNonDeductible, crds, net }
}

function calculerFonctionnaire(p: PersonneEtendue, sc: Scenarios): CalculPersonne {
  const role = p.role
  const primes = (p.primes_mensuelles ?? 0) * 12
  let traitement: number
  if (p.traitement_indiciaire_brut_mensuel !== undefined) traitement = p.traitement_indiciaire_brut_mensuel * 12
  else {
    // Le net croît avec le traitement : recherche par dichotomie du traitement donnant le net saisi.
    const cible = (p.salaire_net_avant_impot_mensuel ?? 0) * 12
    let bas = 0
    let haut = Math.max(cible * 2, 1000)
    for (let i = 0; i < 80; i++) {
      const milieu = (bas + haut) / 2
      if (retenuesFonctionnaire(milieu, primes).net < cible) bas = milieu
      else haut = milieu
    }
    traitement = (bas + haut) / 2
  }
  const r = retenuesFonctionnaire(traitement, primes)
  const fp = B.fonctionPublique
  const e = fp.employeur
  const etat = p.versant === 'etat'
  const brut = traitement + primes
  const regle = 'barème 2025 de la fonction publique (calcul/baremes-2025.ts)'
  const lignes: Prelevement[] = [
    ligne(role, {
      id: etat ? 'retenue_pension_civile' : 'retenue_cnracl',
      libelle: etat ? 'Retenue pour pension civile' : 'Retenue pour pension (CNRACL)',
      famille: 'cotisation_salariale',
      assiette: traitement,
      taux: fp.retenuePension,
      montant: r.pension,
      regle,
    }),
  ]
  if (r.rafp > 0.005)
    lignes.push(ligne(role, { id: 'rafp_salarie', libelle: 'Retraite additionnelle de la fonction publique (RAFP)', famille: 'cotisation_salariale', assiette: r.assietteRafp, taux: fp.rafp, montant: r.rafp, regle }))
  lignes.push(...lignesCsgCrdsActivite(role, r.assietteCsg, regle))

  const tauxMaladie = etat ? e.maladieEtat : e.maladieCnracl
  const employeur: Brouillon[] = [
    etat
      ? { id: 'contribution_cas_pensions', libelle: 'Contribution employeur aux pensions civiles (CAS Pensions)', famille: 'cotisation_patronale', assiette: traitement, taux: e.casPensionsCivils, montant: e.casPensionsCivils * traitement, regle }
      : { id: 'contribution_cnracl', libelle: 'Contribution employeur à la CNRACL', famille: 'cotisation_patronale', assiette: traitement, taux: e.cnracl, montant: e.cnracl * traitement, regle },
    etat
      ? { id: 'ati', libelle: "Allocation temporaire d'invalidité", famille: 'cotisation_patronale', assiette: traitement, taux: e.ati, montant: e.ati * traitement, regle }
      : { id: 'atiacl', libelle: "Allocation temporaire d'invalidité (ATIACL)", famille: 'cotisation_patronale', assiette: traitement, taux: e.atiacl, montant: e.atiacl * traitement, regle },
    { id: 'rafp_employeur', libelle: 'Retraite additionnelle de la fonction publique (RAFP)', famille: 'cotisation_patronale', assiette: r.assietteRafp, taux: fp.rafp, montant: r.rafp, regle },
    { id: 'maladie_employeur', libelle: 'Assurance maladie', famille: 'cotisation_patronale', assiette: traitement, taux: tauxMaladie, montant: tauxMaladie * traitement, destinataire: DESTINATAIRES.cnam, regle },
    { id: 'allocations_familiales', libelle: 'Allocations familiales', famille: 'cotisation_patronale', assiette: traitement, taux: e.allocationsFamiliales, montant: e.allocationsFamiliales * traitement, destinataire: DESTINATAIRES.cnaf, regle },
    { id: 'csa', libelle: 'Contribution solidarité autonomie', famille: 'cotisation_patronale', assiette: traitement, taux: e.csa, montant: e.csa * traitement, destinataire: DESTINATAIRES.cnsa, regle },
    { id: 'fnal', libelle: "Fonds national d'aide au logement", famille: 'cotisation_patronale', assiette: traitement, montant: parScenario(sc, (h) => fnalPublic(traitement, h)), destinataire: DESTINATAIRES.fnal, regle, hypothese: HYPOTHESE_FOURCHETTE_PUBLIQUE },
    { id: 'versement_mobilite', libelle: 'Versement mobilité (transports)', famille: 'cotisation_patronale', assiette: traitement, montant: parScenario(sc, (h) => ((h.tauxVM ?? 0) / 100) * traitement), destinataire: DESTINATAIRES.aom, regle, hypothese: HYPOTHESE_FOURCHETTE_PUBLIQUE },
  ]
  if (p.versant === 'hospitaliere')
    employeur.push({ id: 'fonds_emploi_hospitalier', libelle: "Fonds pour l'emploi hospitalier", famille: 'cotisation_patronale', assiette: traitement, taux: e.feh, montant: e.feh * traitement, regle })
  for (const b of employeur) {
    const l = ligne(role, b)
    if (l.montant_annuel_eur.haut > 0.005) lignes.push(l)
  }
  const patronal = employeur.reduce((s, b) => s + (typeof b.montant === 'number' ? b.montant : b.montant.central), 0)
  const imposable = brut - r.pension - r.rafp - r.csgDeductible
  return {
    entree: {
      role,
      profil: 'fonctionnaire',
      salaire_net_avant_impot_annuel: arrondi(r.net),
      salaire_brut_annuel_estime: f(brut),
      revenu_imposable_annuel: arrondi(imposable),
      detail: { versant: p.versant ?? '', traitement_indiciaire_brut_annuel: arrondi(traitement), primes_annuelles: arrondi(primes) },
    },
    prelevements: lignes,
    avertissements: [],
    brutEmployeur: brut,
    revenus: { salaire: imposable },
    agregats: {
      salaire_brut: brut,
      traitement_indiciaire_brut: traitement,
      salaire_net_avant_impot: r.net,
      salaire_imposable: imposable,
      cotisations_salariales: r.pension + r.rafp,
      pension_salarie: r.pension,
      rafp_salarie: r.rafp,
      csg: r.csgDeductible + r.csgNonDeductible,
      crds: r.crds,
      cotisations_patronales: patronal,
    },
  }
}

// Contractuel de droit public --------------------------------------------------------------------------------------

const TAUX_VIEILLESSE_PLAFONNEE_SALARIE = 0.069

function calculerContractuel(p: PersonneEtendue, profil: ProfilEtendu, sc: Scenarios): CalculPersonne {
  const role = p.role
  const annee = profil.annee_revenus
  const e = obtenirMoteur()
  const irc = B.ircantec
  const pers: PersonneEtendue = { ...p, cadre: false }
  // Employeur public : pas de taux réduits liés à la réduction générale (maladie 13 %, allocations familiales 5,25 %).
  const variante: VarianteSalarie = {
    situation: {
      'salarié . cotisations . maladie . employeur . taux': '13%',
      'salarié . cotisations . allocations familiales . taux': '5.25%',
      ...(profil.residence.alsace_moselle ? { 'salarié . régimes spécifiques . alsace moselle': 'oui' } : {}),
    },
  }
  const C = 'salarié . cotisations . '
  const lire = (brut: number, h: Hypotheses) => {
    e.setSituation(situationSalarie(pers, annee, h, brut, variante) as never)
    const plafonnee = evaluer(e, C + 'vieillesse . plafonnée . salarié')
    const deplafonnee = evaluer(e, C + 'vieillesse . déplafonnée . salarié')
    const maladie = evaluer(e, C + 'maladie . salarié')
    const csg = evaluer(e, C + 'CSG-CRDS . CSG')
    const csgDeductible = evaluer(e, C + 'CSG-CRDS . CSG . déductible')
    const crds = evaluer(e, C + 'CSG-CRDS . CRDS')
    // Tranche A de l'Ircantec : même assiette plafonnée que la vieillesse de base.
    const trancheA = plafonnee / TAUX_VIEILLESSE_PLAFONNEE_SALARIE
    const trancheB = Math.min(Math.max(0, brut - trancheA), (irc.plafondBEnPass - 1) * trancheA)
    const ircantec = irc.salarieA * trancheA + irc.salarieB * trancheB
    const net = brut - plafonnee - deplafonnee - maladie - csg - crds - ircantec
    return { plafonnee, deplafonnee, maladie, csg, csgDeductible, crds, trancheA, trancheB, ircantec, net }
  }
  const cible = (p.salaire_net_avant_impot_mensuel ?? 0) * 12
  let brut = cible * 1.25
  let s = lire(brut, sc.central)
  for (let i = 0; i < 80 && Math.abs(s.net - cible) >= 0.005; i++) {
    brut += cible - s.net
    s = lire(brut, sc.central)
  }
  const employeurDe = (h: Hypotheses) => {
    e.setSituation(situationSalarie(pers, annee, h, brut, variante) as never)
    return {
      maladie_employeur: evaluer(e, C + 'maladie . employeur'),
      vieillesse_plafonnee_employeur: evaluer(e, C + 'vieillesse . plafonnée . employeur'),
      vieillesse_deplafonnee_employeur: evaluer(e, C + 'vieillesse . déplafonnée . employeur'),
      allocations_familiales: evaluer(e, C + 'allocations familiales'),
      atmp: evaluer(e, C + 'ATMP'),
      csa: evaluer(e, C + 'CSA'),
      fnal: evaluer(e, C + 'FNAL'),
      versement_mobilite: evaluer(e, C + 'versement mobilité'),
    }
  }
  const E = { bas: employeurDe(sc.bas), central: employeurDe(sc.central), haut: employeurDe(sc.haut) }
  const regleG = (r: string) => C + r
  const regleI = 'barème Ircantec 2025 (calcul/baremes-2025.ts)'
  const lignes: Prelevement[] = []
  const ajouter = (b: Brouillon) => {
    const l = ligne(role, b)
    if (l.montant_annuel_eur.haut > 0.005) lignes.push(l)
  }
  ajouter({ id: 'vieillesse_plafonnee_salarie', libelle: 'Retraite de base (plafonnée)', famille: 'cotisation_salariale', assiette: brut, montant: s.plafonnee, destinataire: DESTINATAIRES.cnav, regle: regleG('vieillesse . plafonnée . salarié') })
  ajouter({ id: 'vieillesse_deplafonnee_salarie', libelle: 'Retraite de base (déplafonnée)', famille: 'cotisation_salariale', assiette: brut, montant: s.deplafonnee, destinataire: DESTINATAIRES.cnav, regle: regleG('vieillesse . déplafonnée . salarié') })
  ajouter({ id: 'ircantec_salarie', libelle: 'Retraite complémentaire Ircantec', famille: 'cotisation_salariale', assiette: brut, montant: s.ircantec, regle: regleI })
  ajouter({ id: 'maladie_regime_local', libelle: "Assurance maladie, régime local d'Alsace-Moselle", famille: 'cotisation_salariale', assiette: brut, montant: s.maladie, regle: regleG('maladie . salarié') })
  const assietteCsg = s.csgDeductible / B.csgCrdsActivite.csgDeductible
  lignes.push(
    ligne(role, { id: 'csg_deductible', libelle: 'CSG déductible', famille: 'csg_crds', assiette: assietteCsg, taux: 0.068, montant: s.csgDeductible, destinataire: DESTINATAIRES.plusieurs, regle: regleG('CSG-CRDS . CSG . déductible') }),
    ligne(role, { id: 'csg_non_deductible', libelle: 'CSG non déductible', famille: 'csg_crds', assiette: assietteCsg, taux: 0.024, montant: s.csg - s.csgDeductible, destinataire: DESTINATAIRES.plusieurs, regle: regleG('CSG-CRDS . CSG') }),
    ligne(role, { id: 'crds', libelle: 'CRDS (remboursement de la dette sociale)', famille: 'csg_crds', assiette: assietteCsg, taux: 0.005, montant: s.crds, destinataire: DESTINATAIRES.cades, regle: regleG('CSG-CRDS . CRDS') }),
  )
  const employeur: [keyof typeof E.central, string, string, Destinataire][] = [
    ['maladie_employeur', 'Assurance maladie', 'maladie . employeur', DESTINATAIRES.cnam],
    ['vieillesse_plafonnee_employeur', 'Retraite de base (plafonnée)', 'vieillesse . plafonnée . employeur', DESTINATAIRES.cnav],
    ['vieillesse_deplafonnee_employeur', 'Retraite de base (déplafonnée)', 'vieillesse . déplafonnée . employeur', DESTINATAIRES.cnav],
    ['allocations_familiales', 'Allocations familiales', 'allocations familiales', DESTINATAIRES.cnaf],
    ['atmp', 'Accidents du travail et maladies professionnelles', 'ATMP', DESTINATAIRES.branche_atmp],
    ['csa', 'Contribution solidarité autonomie', 'CSA', DESTINATAIRES.cnsa],
    ['fnal', "Fonds national d'aide au logement", 'FNAL', DESTINATAIRES.fnal],
    ['versement_mobilite', 'Versement mobilité (transports)', 'versement mobilité', DESTINATAIRES.aom],
  ]
  for (const [id, libelle, r, dest] of employeur) {
    const m = f3(E.bas[id], E.central[id], E.haut[id])
    ajouter({ id, libelle, famille: 'cotisation_patronale', assiette: brut, montant: m, destinataire: dest, regle: regleG(r), ...(m.bas !== m.haut ? { hypothese: HYPOTHESE_FOURCHETTE_PATRONALE } : {}) })
  }
  const ircantecEmployeur = irc.employeurA * s.trancheA + irc.employeurB * s.trancheB
  ajouter({ id: 'ircantec_employeur', libelle: 'Retraite complémentaire Ircantec', famille: 'cotisation_patronale', assiette: brut, montant: ircantecEmployeur, regle: regleI })
  const cotisations = s.plafonnee + s.deplafonnee + s.maladie + s.ircantec
  const imposable = brut - cotisations - s.csgDeductible
  return {
    entree: { role, profil: 'contractuel_public', salaire_net_avant_impot_annuel: arrondi(s.net), salaire_brut_annuel_estime: f(brut), revenu_imposable_annuel: arrondi(imposable) },
    prelevements: lignes,
    avertissements: [],
    brutEmployeur: brut,
    revenus: { salaire: imposable },
    agregats: {
      salaire_brut: brut,
      salaire_net_avant_impot: s.net,
      salaire_imposable: imposable,
      cotisations_salariales: cotisations,
      ircantec_salarie: s.ircantec,
      csg: s.csg,
      crds: s.crds,
      cotisations_patronales: Object.values(E.central).reduce((a, b) => a + b, 0) + ircantecEmployeur,
      ircantec_employeur: ircantecEmployeur,
    },
  }
}

// Salarié du privé, apprenti, Alsace-Moselle -----------------------------------------------------------------------

function calculerSalarieEtendu(p: PersonneEtendue, profil: ProfilEtendu, sc: Scenarios, index: number): CalculPersonne {
  const role = p.role
  const annee = profil.annee_revenus
  const apprenti = p.statut_activite === 'apprenti'
  const am = profil.residence.alsace_moselle
  const situation: Record<string, string> = {}
  if (am) situation['salarié . régimes spécifiques . alsace moselle'] = 'oui'
  if (apprenti) situation['salarié . contrat'] = "'apprentissage'"
  const variante: VarianteSalarie | undefined =
    am || apprenti
      ? {
          situation,
          // modele-social distingue les contrats par la date de simulation : exonération jusqu'à 79 % du SMIC
          // et CSG nulle avant mars 2025, 50 % du SMIC ensuite.
          ...(apprenti ? { inversionManuelle: true, date: p.apprentissage?.contrat_avant_mars_2025 ? `'01/02/${annee}'` : `'01/06/${annee}'` } : {}),
        }
      : undefined
  const c = calculerSalarie({ ...p, cadre: !!p.cadre }, annee, sc, variante)
  const l = lignesSalarie(p, c, `/personnes/${index}/salaire_net_avant_impot_mensuel`)
  const prelevements = l.prelevements.map((x) =>
    am && x.id === suffixe('maladie_salarie', role)
      ? { ...x, id: suffixe('maladie_regime_local', role), libelle: "Assurance maladie, régime local d'Alsace-Moselle", destinataire: NON_AFFECTE, statut_affectation: 'non sourcee' as const }
      : x,
  )
  const cotisations = c.cotisationsSalarieTotal - c.csgDeductible - c.csgNonDeductible - c.crds
  // modele-social met à 0 le net imposable d'un apprenti : on le recalcule, puis on applique l'exonération d'impôt.
  const imposableAvantExoneration = apprenti ? c.brut - cotisations - c.csgDeductible : c.imposable
  const imposable = apprenti ? Math.max(0, imposableAvantExoneration - B.impot.exonerationApprenti) : c.imposable
  return {
    entree: {
      role,
      profil: apprenti ? 'apprenti' : 'salarie_prive',
      salaire_net_avant_impot_annuel: arrondi(c.netAnnuel),
      salaire_brut_annuel_estime: f(c.brut),
      revenu_imposable_annuel: arrondi(imposable),
      ...(apprenti ? { detail: { salaire_imposable_avant_exoneration: arrondi(imposableAvantExoneration), exoneration_impot_apprenti: B.impot.exonerationApprenti } } : {}),
    },
    prelevements,
    // Un apprenti est rémunéré sous le SMIC par construction : l'alerte « inférieur au SMIC » ne s'applique pas.
    avertissements: apprenti ? [] : l.avertissements,
    brutEmployeur: c.brut,
    revenus: { salaire: imposable },
    agregats: {
      salaire_brut: c.brut,
      salaire_net_avant_impot: c.netAnnuel,
      salaire_imposable: imposable,
      cotisations_salariales: cotisations,
      cotisation_regime_local: am ? c.salarie.maladie_salarie : 0,
      csg: c.csgDeductible + c.csgNonDeductible,
      csg_deductible: c.csgDeductible,
      crds: c.crds,
      cotisations_patronales: c.employeur.central.total,
      reduction_generale: c.employeur.central.reduction_generale,
    },
  }
}

// Retraité ---------------------------------------------------------------------------------------------------------

const LIBELLE_TAUX_CSG: Record<TauxCsgRetraite, string> = {
  exonere: 'exonération',
  reduit: 'taux réduit de 3,8 %',
  median: 'taux médian de 6,6 %',
  normal: 'taux normal de 8,3 %',
}

function calculerRetraite(p: PersonneEtendue): CalculPersonne {
  const role = p.role
  const P = B.pensions
  const c = p.csg_pension
  const categorie: TauxCsgRetraite = c && 'taux' in c ? c.taux : tauxCsgPension(c?.revenu_fiscal_reference ?? 0, c?.parts ?? 1)
  const t = P.taux[categorie]
  const exonere = categorie === 'exonere'
  const tauxCrds = exonere ? 0 : P.crds
  const tauxCasa = categorie === 'median' || categorie === 'normal' ? P.casa : 0
  const tauxMaladie = exonere ? 0 : P.maladieComplementaire
  const commun = t.deductible + t.nonDeductible + tauxCrds + tauxCasa
  const nette = p.pension_saisie !== 'brute'
  const base = ((p.pension_base_mensuelle ?? 0) * 12) / (nette ? 1 - commun : 1)
  const complementaire = ((p.pension_complementaire_mensuelle ?? 0) * 12) / (nette ? 1 - commun - tauxMaladie : 1)
  const brut = base + complementaire
  const csgDeductible = t.deductible * brut
  const csgNonDeductible = t.nonDeductible * brut
  const crds = tauxCrds * brut
  const casa = tauxCasa * brut
  const maladie = tauxMaladie * complementaire
  const net = brut - csgDeductible - csgNonDeductible - crds - casa - maladie
  const imposable = brut - csgDeductible - maladie
  const regle = 'barème 2025 des pensions de retraite (calcul/baremes-2025.ts)'
  const lignes: Prelevement[] = []
  const ajouter = (b: Brouillon) => {
    const l = ligne(role, b)
    if (l.montant_annuel_eur.haut > 0.005) lignes.push(l)
  }
  ajouter({ id: 'csg_pension_deductible', libelle: 'CSG déductible sur la pension', famille: 'csg_crds', assiette: brut, taux: t.deductible, montant: csgDeductible, regle })
  ajouter({ id: 'csg_pension_non_deductible', libelle: 'CSG non déductible sur la pension', famille: 'csg_crds', assiette: brut, taux: t.nonDeductible, montant: csgNonDeductible, regle })
  ajouter({ id: 'crds', libelle: 'CRDS (remboursement de la dette sociale)', famille: 'csg_crds', assiette: brut, taux: tauxCrds, montant: crds, destinataire: DESTINATAIRES.cades, regle })
  ajouter({ id: 'casa', libelle: "Contribution additionnelle de solidarité pour l'autonomie (Casa)", famille: 'csg_crds', assiette: brut, taux: tauxCasa, montant: casa, regle })
  ajouter({
    id: 'maladie_retraite_complementaire',
    libelle: 'Cotisation maladie sur la retraite complémentaire',
    famille: 'cotisation_salariale',
    assiette: complementaire,
    taux: tauxMaladie,
    montant: maladie,
    regle,
    note: 'Taux relu dans les paramètres OpenFisca ; montant non recoupé par un calcul tiers (OpenFisca ne calcule pas cette cotisation).',
  })
  return {
    entree: {
      role,
      profil: 'retraite',
      salaire_net_avant_impot_annuel: arrondi(net),
      salaire_brut_annuel_estime: f(brut),
      revenu_imposable_annuel: arrondi(imposable),
      detail: { taux_csg: LIBELLE_TAUX_CSG[categorie], pension_base_brute_annuelle: arrondi(base), pension_complementaire_brute_annuelle: arrondi(complementaire) },
    },
    prelevements: lignes,
    avertissements: [],
    brutEmployeur: 0,
    revenus: { pension: imposable },
    agregats: {
      retraite_brute: brut,
      retraite_nette: net,
      retraite_imposable: imposable,
      csg: csgDeductible + csgNonDeductible,
      csg_deductible: csgDeductible,
      crds,
      casa,
      maladie_retraite_complementaire: maladie,
    },
  }
}

// Indépendants -----------------------------------------------------------------------------------------------------

const NATURE_MICRO: Record<ActiviteMicro, string> = { vente: "'commerciale'", service_bic: "'commerciale'", service_bnc: "'libérale'" }
const AE = 'dirigeant . auto-entrepreneur . cotisations et contributions'
const PART_CSG_DANS_CSG_CRDS = 9.2 / 9.7

function calculerMicro(p: PersonneEtendue, profil: ProfilEtendu): CalculPersonne {
  const role = p.role
  const ind = p.independant!
  const activite = ind.activite as ActiviteMicro
  const ca = ind.chiffre_affaires_annuel ?? 0
  const e = obtenirMoteur()
  const s: Record<string, string> = {
    date: `'01/06/${profil.annee_revenus}'`,
    'entreprise . catégorie juridique': "'EI'",
    'entreprise . catégorie juridique . EI . auto-entrepreneur': 'oui',
    'entreprise . activité . nature': ind.artisan ? "'artisanale'" : NATURE_MICRO[activite],
    "dirigeant . auto-entrepreneur . chiffre d'affaires": `${ca} €/an`,
    'dirigeant . auto-entrepreneur . impôt . versement libératoire': ind.versement_liberatoire ? 'oui' : 'non',
  }
  if (activite !== 'service_bnc') s['entreprise . activités . service ou vente'] = activite === 'vente' ? "'vente'" : "'service'"
  e.setSituation(s as never)
  const total = evaluer(e, AE)
  const rep = (x: string) => evaluer(e, `${AE} . cotisations . répartition . ${x}`)
  const csgCrds = rep('autres contributions')
  const cfp = evaluer(e, `${AE} . CFP`)
  const tfc = evaluer(e, `${AE} . TFC`)
  const liberatoire = ind.versement_liberatoire ? evaluer(e, 'dirigeant . auto-entrepreneur . impôt . versement libératoire . montant') : 0
  const lignes: Prelevement[] = []
  const ajouter = (b: Brouillon) => {
    const l = ligne(role, b)
    if (l.montant_annuel_eur.haut > 0.005) lignes.push(l)
  }
  const regle = (x: string) => `${AE} . cotisations . répartition . ${x}`
  ajouter({ id: 'micro_maladie_maternite', libelle: 'Assurance maladie et maternité', famille: 'cotisation_salariale', assiette: ca, montant: rep('maladie-maternité'), regle: regle('maladie-maternité') })
  ajouter({ id: 'micro_invalidite_deces', libelle: 'Invalidité et décès', famille: 'cotisation_salariale', assiette: ca, montant: rep('invalidité-décès'), regle: regle('invalidité-décès') })
  ajouter({ id: 'micro_retraite_base', libelle: 'Retraite de base', famille: 'cotisation_salariale', assiette: ca, montant: rep('retraite de base'), regle: regle('retraite de base') })
  ajouter({ id: 'micro_retraite_complementaire', libelle: 'Retraite complémentaire', famille: 'cotisation_salariale', assiette: ca, montant: rep('retraite complémentaire'), regle: regle('retraite complémentaire') })
  // « Autres contributions » du forfait : CSG (9,2 %) et CRDS (0,5 %) ont la même assiette, d'où le partage 9,2 / 9,7.
  ajouter({ id: 'csg_micro', libelle: 'CSG (part du forfait micro-social)', famille: 'csg_crds', assiette: ca, montant: csgCrds * PART_CSG_DANS_CSG_CRDS, destinataire: DESTINATAIRES.plusieurs, regle: regle('autres contributions') })
  ajouter({ id: 'crds', libelle: 'CRDS (part du forfait micro-social)', famille: 'csg_crds', assiette: ca, montant: csgCrds * (1 - PART_CSG_DANS_CSG_CRDS), destinataire: DESTINATAIRES.cades, regle: regle('autres contributions') })
  ajouter({ id: 'micro_formation_professionnelle', libelle: 'Contribution à la formation professionnelle', famille: 'cotisation_salariale', assiette: ca, montant: cfp, regle: `${AE} . CFP` })
  ajouter({
    id: 'micro_taxe_chambre_consulaire',
    libelle: 'Taxe pour frais de chambre consulaire',
    famille: 'cotisation_salariale',
    assiette: ca,
    montant: tfc,
    regle: `${AE} . TFC`,
    ...(profil.residence.alsace_moselle && ind.artisan ? { note: "Taux hors Alsace-Moselle : les taux propres aux chambres de métiers d'Alsace et de Moselle ne sont pas appliqués." } : {}),
  })
  ajouter({
    id: 'impot_revenu_versement_liberatoire',
    libelle: "Versement libératoire de l'impôt sur le revenu",
    famille: 'impot_revenu',
    assiette: ca,
    montant: liberatoire,
    destinataire: DESTINATAIRES.etat,
    regle: 'dirigeant . auto-entrepreneur . impôt . versement libératoire . montant',
  })
  const ab = B.impot.abattementMicro
  const beneficeImposable = Math.max(0, ca - Math.max(ab.minimum, ab[activite] * ca))
  return {
    entree: {
      role,
      profil: 'micro_entrepreneur',
      salaire_net_avant_impot_annuel: arrondi(ca - total),
      salaire_brut_annuel_estime: f(ca),
      revenu_imposable_annuel: arrondi(beneficeImposable),
      detail: { activite, versement_liberatoire: ind.versement_liberatoire ? 'oui' : 'non', abattement_forfaitaire: ab[activite] },
    },
    prelevements: lignes,
    avertissements: [],
    brutEmployeur: 0,
    revenus: ind.versement_liberatoire ? { liberatoire: beneficeImposable } : { net: beneficeImposable },
    agregats: {
      chiffre_affaires: ca,
      cotisations_et_contributions: total,
      cotisations: evaluer(e, `${AE} . cotisations`),
      maladie_maternite: rep('maladie-maternité'),
      invalidite_deces: rep('invalidité-décès'),
      retraite_base: rep('retraite de base'),
      retraite_complementaire: rep('retraite complémentaire'),
      csg_crds: csgCrds,
      formation_professionnelle: cfp,
      taxe_chambre_consulaire: tfc,
      versement_liberatoire: liberatoire,
      benefice_imposable: beneficeImposable,
    },
  }
}

const IND = 'dirigeant . indépendant . cotisations et contributions'
const NATURE_REEL = { artisan: "'artisanale'", commercant: "'commerciale'", liberale: "'libérale'" } as const

/** Indépendant au régime réel : règles de modele-social, NON VÉRIFIÉES contre une autre source (option autoriserNonVerifie). */
function calculerIndependantReel(p: PersonneEtendue, profil: ProfilEtendu): CalculPersonne {
  const role = p.role
  const ind = p.independant!
  const revenu = ind.revenu_professionnel_annuel ?? 0
  const e = obtenirMoteur()
  const s: Record<string, string> = {
    date: `'01/06/${profil.annee_revenus}'`,
    'entreprise . catégorie juridique': "'EI'",
    'entreprise . catégorie juridique . EI . auto-entrepreneur': 'non',
    'entreprise . imposition': "'IR'",
    'entreprise . activité . nature': NATURE_REEL[ind.categorie ?? 'artisan'],
    'dirigeant . indépendant . revenu professionnel': `${revenu} €/an`,
  }
  if (ind.categorie === 'liberale') s['entreprise . activité . nature . libérale . réglementée'] = 'non'
  e.setSituation(s as never)
  const total = evaluer(e, IND)
  const note = 'Non vérifié : aucune référence indépendante pour le régime réel (réforme 2025 de l’assiette).'
  const postes: [string, string, string][] = [
    ['independant_maladie', 'Assurance maladie et maternité', 'maladie'],
    ['independant_indemnites_journalieres', 'Indemnités journalières maladie', 'indemnités journalières maladie'],
    ['independant_retraite_base', 'Retraite de base', 'retraite de base'],
    ['independant_retraite_complementaire', 'Retraite complémentaire', 'retraite complémentaire'],
    ['independant_invalidite_deces', 'Invalidité et décès', 'invalidité et décès'],
    ['independant_allocations_familiales', 'Allocations familiales', 'allocations familiales'],
    ['independant_formation_professionnelle', 'Contribution à la formation professionnelle', 'formation professionnelle'],
  ]
  const lignes: Prelevement[] = []
  for (const [id, libelle, r] of postes) {
    const m = evaluer(e, `${IND} . ${r}`)
    if (m > 0.005) lignes.push(ligne(role, { id, libelle, famille: 'cotisation_salariale', assiette: revenu, montant: m, regle: `${IND} . ${r}`, note }))
  }
  const csgCrds = evaluer(e, `${IND} . CSG-CRDS`)
  lignes.push(
    ligne(role, { id: 'csg_micro', libelle: 'CSG', famille: 'csg_crds', montant: csgCrds * PART_CSG_DANS_CSG_CRDS, destinataire: DESTINATAIRES.plusieurs, regle: `${IND} . CSG-CRDS`, note }),
    ligne(role, { id: 'crds', libelle: 'CRDS (remboursement de la dette sociale)', famille: 'csg_crds', montant: csgCrds * (1 - PART_CSG_DANS_CSG_CRDS), destinataire: DESTINATAIRES.cades, regle: `${IND} . CSG-CRDS`, note }),
  )
  return {
    entree: { role, profil: 'independant_reel', salaire_net_avant_impot_annuel: arrondi(revenu), salaire_brut_annuel_estime: f(revenu + total), revenu_imposable_annuel: arrondi(revenu) },
    prelevements: lignes,
    avertissements: [],
    brutEmployeur: 0,
    revenus: { net: revenu },
    agregats: { revenu_professionnel: revenu, cotisations_et_contributions: total, csg_crds: csgCrds },
  }
}

function calculerPersonne(p: PersonneEtendue, profil: ProfilEtendu, sc: Scenarios, index: number): CalculPersonne | null {
  switch (profilDe(p)) {
    case 'salarie_prive':
    case 'apprenti':
      return calculerSalarieEtendu(p, profil, sc, index)
    case 'fonctionnaire':
      return calculerFonctionnaire(p, sc)
    case 'contractuel_public':
      return calculerContractuel(p, profil, sc)
    case 'retraite':
      return calculerRetraite(p)
    case 'micro_entrepreneur':
      return calculerMicro(p, profil)
    case 'independant_reel':
      return calculerIndependantReel(p, profil)
    default:
      return null
  }
}

// --- Impôt sur le revenu du foyer ---------------------------------------------------------------------------------

/** Pensions nettes d'abattement : 10 % par pensionné avec minimum, plafond commun au foyer. */
export function pensionsApresAbattement(pensions: number[]): number {
  const a = B.impot.abattementPensions
  const total = pensions.reduce((s, x) => s + x, 0)
  const abattement = pensions.reduce((s, x) => s + Math.min(x, Math.max(a.minimumParPensionne, a.taux * x)), 0)
  return Math.max(0, total - Math.min(abattement, a.plafondParFoyer))
}

function impotDuFoyer(couple: boolean, parentIsole: boolean, enfants: ProfilEtendu['foyer']['enfants'], revenus: RevenusImposables[], annee: number): number {
  const ages = revenus.filter((r) => r.plusDe65).length
  const a = B.impot.abattementAge
  return impotFoyer(
    {
      ...(ages ? { abattementAge: { plein: ages * a.plein, seuilPlein: a.seuilPlein, reduit: ages * a.reduit, seuilReduit: a.seuilReduit } } : {}),
      couple,
      parentIsole,
      enfants,
      imposables: revenus.filter((r) => (r.salaire ?? 0) > 0).map((r) => r.salaire as number),
      autresRevenusNets: pensionsApresAbattement(revenus.filter((r) => (r.pension ?? 0) > 0).map((r) => r.pension as number)) + revenus.reduce((s, r) => s + (r.net ?? 0), 0),
      revenusTauxEffectif: revenus.reduce((s, r) => s + (r.liberatoire ?? 0), 0),
    },
    annee,
  )
}

// --- Affectation ----------------------------------------------------------------------------------------------------

/** Lignes du résultat sans entrée dans prelevements/affectation.json (après application de l'affectation). */
export function affectationsManquantes(prelevements: Prelevement[], affectation?: Affectation | null): AffectationManquante[] {
  const vus = new Map<string, AffectationManquante>()
  for (const l of prelevements) {
    if (l.ventilation?.length && affectation) continue
    const base = l.id.replace(/_declarant2$/, '')
    const cle = CLES_AFFECTATION_A_CREER[base]
    if (!cle) continue
    if (!vus.has(base)) vus.set(base, { id: base, libelle: l.libelle, cle_proposee: cle })
  }
  return [...vus.values()]
}

// --- Entrée principale ----------------------------------------------------------------------------------------------

/**
 * Calcule ce que verse un foyer, quel que soit le profil de ses membres (voir README.md).
 * Synchrone, sans appel réseau ; prévoir environ 0,5 s au premier appel (chargement des règles).
 */
export function calculerProfil(profil: ProfilEtendu, options: OptionsCalculEtendu = {}): ResultatEtendu {
  const erreur = verifierProfilEtendu(profil, options)
  if (erreur) return erreur
  const sc = options.scenarios ?? SCENARIOS_SITE
  const annee = profil.annee_revenus
  let calculs: CalculPersonne[]
  try {
    calculs = profil.personnes
      .map((p, i) => {
        const c = calculerPersonne(p, profil, sc, i)
        if (c && typeof p.annee_naissance === 'number' && annee - p.annee_naissance >= B.impot.abattementAge.ageMinimum) c.revenus.plusDe65 = true
        return c
      })
      .filter((c): c is CalculPersonne => c !== null)
  } catch {
    return {
      statut: 'erreur',
      version_contrat: '1.0',
      erreur: { code: 'MOTEUR_INDISPONIBLE', message: 'Le calcul est indisponible pour le moment. Tu peux toujours explorer le budget.' },
    }
  }
  const prelevements = calculs.flatMap((c) => c.prelevements)
  const avertissements = calculs.flatMap((c) => c.avertissements)
  const revenusDe = (role: Role) => calculs.filter((c) => c.entree.role === role).map((c) => c.revenus)
  const sit = profil.foyer.situation
  const enfants = profil.foyer.enfants
  const lignesIR: { id: string; libelle: string; montant: number }[] = []
  if (sit === 'couple_union_libre') {
    lignesIR.push({ id: 'impot_revenu', libelle: 'Impôt sur le revenu (foyer de la personne 1)', montant: impotDuFoyer(false, false, enfants, revenusDe('declarant1'), annee) })
    lignesIR.push({ id: 'impot_revenu_declarant2', libelle: 'Impôt sur le revenu (foyer de la personne 2)', montant: impotDuFoyer(false, false, [], revenusDe('declarant2'), annee) })
  } else
    lignesIR.push({
      id: 'impot_revenu',
      libelle: 'Impôt sur le revenu du foyer',
      montant: impotDuFoyer(sit === 'couple_marie_pacse', sit === 'parent_isole', enfants, calculs.map((c) => c.revenus), annee),
    })
  for (const l of lignesIR)
    prelevements.push({
      id: l.id,
      libelle: l.libelle,
      famille: 'impot_revenu',
      personne: 'foyer',
      assiette_annuelle_eur: null,
      taux: null,
      montant_annuel_eur: f(l.montant),
      destinataire: DESTINATAIRES.etat,
      inclus_dans_total_paye: true,
      regle: 'impôt . foyer fiscal . impôt sur le revenu',
      hypothese_fourchette:
        "Sans autres revenus, frais réels ni réductions ou crédits d'impôt (dons, emploi à domicile, garde d'enfants) : non pris en compte.",
    })
  const brutTotal = calculs.reduce((s, c) => s + c.brutEmployeur, 0)
  const base = assemblerResultat(profil, options, prelevements, avertissements, calculs.map((c) => c.entree), brutTotal)
  const profils = [...new Set(calculs.map((c) => c.entree.profil))]
  const verifications = profils.map((x) => VERIFICATIONS[x])
  if (profil.residence.alsace_moselle && profils.some((x) => x === 'salarie_prive' || x === 'apprenti' || x === 'contractuel_public')) verifications.push(VERIFICATIONS.alsace_moselle)
  if (profil.personnes.length > 1 || sit === 'parent_isole') verifications.push(VERIFICATIONS.foyer)
  return {
    ...base,
    millesime: { annee_revenus: annee, baremes: `Barèmes sociaux et fiscaux des revenus ${MILLESIME_BAREMES} (modele-social ${base.moteur.version} et calcul/baremes-2025.ts)` },
    verifications,
    affectations_manquantes: affectationsManquantes(base.prelevements, options.affectation),
  }
}

/** Valeurs agrégées d'une personne, comparables aux références des cas types (tests). */
export function agregatsProfil(profil: ProfilEtendu, role: Role, sc: Scenarios = SCENARIOS_OPENFISCA): Record<string, number> {
  const i = profil.personnes.findIndex((x) => x.role === role)
  if (i < 0) throw new Error('personne absente')
  const c = calculerPersonne(profil.personnes[i], profil, sc, i)
  if (!c) throw new Error('personne sans revenu calculable')
  return c.agregats
}

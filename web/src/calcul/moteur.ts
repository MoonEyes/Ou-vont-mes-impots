// Module de calcul personnel (contrat, section 3), exécuté dans le navigateur.
// modele-social (règles publicodes de l'Urssaf, MIT) + publicodes (MIT).
// Aucune donnée ne sort de l'appareil : ce module ne fait aucun appel réseau.
import rules from 'modele-social'
import Engine from 'publicodes'
import { DESTINATAIRES } from './destinataires'
import { verifierProfil } from './perimetre'
import type {
  Avertissement,
  Fourchette,
  IdDestinataire,
  Personne,
  Prelevement,
  Profil,
  Resultat,
  ResultatOk,
} from './types'

export const VERSION_MODELE_SOCIAL = __VERSION_MODELE_SOCIAL__
export const VERSION_PUBLICODES = __VERSION_PUBLICODES__

/** Paramètres que le profil ne dit pas (contrat 3.4). */
export interface Hypotheses {
  /** seuil d'effectif modele-social : 'moins de 5' ... 'plus de 250' */
  effectifSeuil?: string
  /** taux AT-MP en % (défaut modele-social : taux collectif) */
  tauxATMP?: number
  /** taux de versement mobilité en % */
  tauxVM?: number
  /** réduction générale de cotisations patronales appliquée (défaut oui) */
  reductionGenerale?: boolean
}

export interface Scenarios {
  bas: Hypotheses
  central: Hypotheses
  haut: Hypotheses
}

/** Fourchette du site : central = valeurs par défaut de modele-social. */
export const SCENARIOS_SITE: Scenarios = {
  bas: { tauxATMP: 0.45, tauxVM: 0, effectifSeuil: 'moins de 5', reductionGenerale: true },
  central: {},
  haut: { tauxATMP: 4, tauxVM: 3.2, effectifSeuil: 'plus de 250', reductionGenerale: false },
}

/** Hypothèses des cas types OpenFisca (tests/cas_types : effectif 50, pas de versement mobilité). */
export const SCENARIOS_OPENFISCA: Scenarios = {
  bas: { effectifSeuil: 'moins de 150', tauxVM: 0, tauxATMP: 0.7 },
  central: { effectifSeuil: 'moins de 150', tauxVM: 0, tauxATMP: 0.7 },
  haut: { effectifSeuil: 'moins de 150', tauxVM: 0, tauxATMP: 0.7 },
}

export const HYPOTHESE_FOURCHETTE_PATRONALE =
  "Bas : taux AT-MP 0,45 %, pas de versement mobilité, moins de 11 salariés, réduction générale appliquée. Haut : taux AT-MP 4 %, versement mobilité 3,2 % (Paris), 250 salariés et plus, sans réduction générale. Central : valeurs par défaut de modele-social."

/** Affectation des prélèvements partagés (site/data/affectation_prelevements.json, prévu). */
export interface Affectation {
  annee?: string | number
  source?: string
  prelevements: Record<string, { ventilation: { destinataire: string; part: number }[] }>
}

/** Commune choisie : [nom, taux TFB %, taux TEOM % ou null] ; null = code inconnu. */
export type CommuneSaisie = [string, number | null, number | null] | null | undefined

export interface OptionsCalcul {
  scenarios?: Scenarios
  affectation?: Affectation | null
  commune?: CommuneSaisie
}

// Prélèvements hors administrations publiques, non comptés (expliqué sur la page Méthode).
export const EXCLUS_NON_PUBLICS = [
  { regle: 'PEEC', libelle: "Participation à l'effort de construction (Action Logement, organisme privé)" },
  { regle: 'contribution au dialogue social', libelle: 'Contribution au dialogue social (fonds paritaire)' },
]

type Ligne = [id: string, libelle: string, regle: string, dest: IdDestinataire]

const LIGNES_SALARIE: Ligne[] = [
  ['maladie_salarie', 'Assurance maladie', 'maladie . salarié', 'cnam'],
  ['vieillesse_plafonnee_salarie', 'Retraite de base (plafonnée)', 'vieillesse . plafonnée . salarié', 'cnav'],
  ['vieillesse_deplafonnee_salarie', 'Retraite de base (déplafonnée)', 'vieillesse . déplafonnée . salarié', 'cnav'],
  ['retraite_complementaire_salarie', 'Retraite complémentaire', 'retraite complémentaire . salarié', 'agirc_arrco'],
  ['ceg_salarie', "Contribution d'équilibre général", 'CEG . salarié', 'agirc_arrco'],
  ['cet_salarie', "Contribution d'équilibre technique", 'CET . salarié', 'agirc_arrco'],
  ['apec_salarie', 'Apec (cadres)', 'APEC . salarié', 'apec'],
]

const LIGNES_EMPLOYEUR: Ligne[] = [
  ['maladie_employeur', 'Assurance maladie', 'maladie . employeur', 'cnam'],
  ['vieillesse_plafonnee_employeur', 'Retraite de base (plafonnée)', 'vieillesse . plafonnée . employeur', 'cnav'],
  ['vieillesse_deplafonnee_employeur', 'Retraite de base (déplafonnée)', 'vieillesse . déplafonnée . employeur', 'cnav'],
  ['retraite_complementaire_employeur', 'Retraite complémentaire', 'retraite complémentaire . employeur', 'agirc_arrco'],
  ['ceg_employeur', "Contribution d'équilibre général", 'CEG . employeur', 'agirc_arrco'],
  ['cet_employeur', "Contribution d'équilibre technique", 'CET . employeur', 'agirc_arrco'],
  ['allocations_familiales', 'Allocations familiales', 'allocations familiales', 'cnaf'],
  ['atmp', 'Accidents du travail et maladies professionnelles', 'ATMP', 'branche_atmp'],
  ['chomage', 'Assurance chômage', 'chômage', 'unedic'],
  ['ags', 'Garantie des salaires (AGS)', 'AGS', 'ags'],
  ['apec_employeur', 'Apec (cadres)', 'APEC . employeur', 'apec'],
  ['csa', 'Contribution solidarité autonomie', 'CSA', 'cnsa'],
  ['fnal', "Fonds national d'aide au logement", 'FNAL', 'fnal'],
  ['formation_professionnelle', 'Formation professionnelle', 'formation professionnelle', 'france_competences'],
  ['taxe_apprentissage', "Taxe d'apprentissage", "taxe d'apprentissage", 'france_competences'],
  ['versement_mobilite', 'Versement mobilité (transports)', 'versement mobilité', 'aom'],
  ['forfait_social', 'Forfait social', 'forfait social', 'cnav'],
]

// SMIC horaire brut 2025 : 11,88 € (151,67 h par mois)
const SMIC_ANNUEL_2025 = 11.88 * 151.67 * 12
const SMIC_NET_MENSUEL_2025 = 1426.3
const PASS_ANNUEL_2025 = 47100

let moteur: Engine | null = null
function obtenirMoteur(): Engine {
  if (!moteur) {
    const silencieux = { log() {}, warn() {}, error() {} }
    moteur = new Engine(rules as never, { logger: silencieux } as never)
  }
  return moteur
}

const arrondi = (x: number) => Math.round(x * 100) / 100
const f = (x: number): Fourchette => ({ bas: arrondi(x), central: arrondi(x), haut: arrondi(x) })
function f3(a: number, b: number, c: number): Fourchette {
  const v = [a, b, c].map((x) => arrondi(Math.max(0, x)))
  return { bas: Math.min(...v), central: v[1], haut: Math.max(...v) }
}

function situationSalarie(p: Personne, annee: number, h: Hypotheses, brut?: number): Record<string, string> {
  const s: Record<string, string> = {
    date: `'01/06/${annee}'`,
    'salarié . contrat . statut cadre': p.cadre ? 'oui' : 'non',
    // Hors complémentaire santé et prévoyance d'entreprise (variables d'une entreprise à l'autre,
    // et absentes d'OpenFisca) : même convention que les cas types de référence.
    'salarié . cotisations . prévoyances . santé . montant': '0 €/mois',
    'salarié . cotisations . prévoyances . employeur . cadres': '0 €/mois',
  }
  if (brut !== undefined) s['salarié . contrat . salaire brut'] = `${brut} €/an`
  else s['salarié . rémunération . net . à payer avant impôt'] = `${p.salaire_net_avant_impot_mensuel} €/mois`
  const t = p.temps_travail
  if (t && t.type === 'temps_partiel' && t.quotite < 1) {
    s['salarié . contrat . temps de travail . temps partiel'] = 'oui'
    s['salarié . contrat . temps de travail . temps partiel . heures par semaine'] = `${35 * t.quotite} heure/semaine`
  }
  if (h.effectifSeuil) s['entreprise . salariés . effectif . seuil'] = `'${h.effectifSeuil}'`
  if (h.tauxATMP !== undefined) s['établissement . taux ATMP'] = `${h.tauxATMP}%`
  if (h.tauxVM !== undefined) s['établissement . commune . taux versement mobilité'] = `${h.tauxVM}%`
  if (h.reductionGenerale === false) s['salarié . cotisations . exonérations . RGDU'] = '0 €/mois'
  else if (annee === 2025 && brut !== undefined) {
    // modele-social 11 ne connaît que la RGDU de 2026 ; en 2025 s'applique l'ancienne réduction générale.
    s['salarié . cotisations . exonérations . RGDU'] = `${reductionGenerale2025(brut, quotite(p), h)} €/an`
  }
  if (annee === 2025 && brut !== undefined) {
    // Taux réduits 2025 (supprimés en 2026, seule loi codée dans modele-social 11) :
    // maladie 7 % jusqu'à 2,25 SMIC, allocations familiales 3,45 % jusqu'à 3,3 SMIC.
    const smic = SMIC_ANNUEL_2025 * quotite(p)
    s['salarié . cotisations . maladie . employeur . taux'] = brut <= 2.25 * smic ? '7%' : '13%'
    s['salarié . cotisations . allocations familiales . taux'] = brut <= 3.3 * smic ? '3.45%' : '5.25%'
  }
  return s
}

const quotite = (p: Personne) => (p.temps_travail && p.temps_travail.type === 'temps_partiel' ? p.temps_travail.quotite : 1)

/**
 * Réduction générale 2025 (article L241-13 CSS, barème au 1er janvier 2025) :
 * C = T / 0,6 x (1,6 x SMIC annuel / rémunération annuelle brute - 1), plafonné à T,
 * T = 0,3194 (moins de 50 salariés) ou 0,3234 (50 et plus), coefficient arrondi à 4 décimales.
 */
export function reductionGenerale2025(brutAnnuel: number, q: number, h: Hypotheses): number {
  const smicAnnuel = SMIC_ANNUEL_2025 * q
  const seuils = ['moins de 5', 'moins de 11', 'moins de 20', 'moins de 50']
  const T = !h.effectifSeuil || seuils.includes(h.effectifSeuil) ? 0.3194 : 0.3234
  if (brutAnnuel <= 0 || brutAnnuel >= 1.6 * smicAnnuel) return 0
  const C = Math.min(T, Math.round((T / 0.6) * ((1.6 * smicAnnuel) / brutAnnuel - 1) * 10000) / 10000)
  return Math.max(0, Math.round(C * brutAnnuel * 100) / 100)
}

function evaluer(e: Engine, regle: string): number {
  const n = e.evaluate({ valeur: regle, unité: '€/an' } as never) as { nodeValue: unknown }
  return typeof n.nodeValue === 'number' && Number.isFinite(n.nodeValue) ? n.nodeValue : 0
}

interface CalculSalarie {
  brut: number
  netAnnuel: number
  imposable: number
  salarie: Record<string, number>
  csgDeductible: number
  csgNonDeductible: number
  crds: number
  cotisationsSalarieTotal: number
  employeur: { bas: Record<string, number>; central: Record<string, number>; haut: Record<string, number> }
}

function calculerSalarie(p: Personne, annee: number, sc: Scenarios): CalculSalarie {
  const e = obtenirMoteur()
  e.setSituation(situationSalarie(p, annee, sc.central) as never)
  const brut = evaluer(e, 'salarié . contrat . salaire brut')
  const sal: Record<string, number> = {}
  for (const [id, , regle] of LIGNES_SALARIE) sal[id] = evaluer(e, 'salarié . cotisations . ' + regle)
  const csgTotal = evaluer(e, 'salarié . cotisations . CSG-CRDS . CSG')
  const csgDeductible = evaluer(e, 'salarié . cotisations . CSG-CRDS . CSG . déductible')
  const crds = evaluer(e, 'salarié . cotisations . CSG-CRDS . CRDS')
  const cotisationsSalarieTotal = evaluer(e, 'salarié . cotisations . salarié')
  const imposable = evaluer(e, 'salarié . rémunération . net . imposable')
  const netAnnuel = evaluer(e, 'salarié . rémunération . net . à payer avant impôt')
  const lireEmployeur = () => {
    const r: Record<string, number> = {}
    for (const [id, , regle] of LIGNES_EMPLOYEUR) r[id] = evaluer(e, 'salarié . cotisations . ' + regle)
    r.reduction_generale = evaluer(e, 'salarié . cotisations . exonérations . employeur')
    for (const x of EXCLUS_NON_PUBLICS) r['exclu:' + x.regle] = evaluer(e, 'salarié . cotisations . ' + x.regle)
    r.total = evaluer(e, 'salarié . cotisations . employeur')
    return r
  }
  // Côté employeur, on repart du brut obtenu (la réduction 2025 se calcule sur le brut).
  e.setSituation(situationSalarie(p, annee, sc.central, brut) as never)
  const central = lireEmployeur()
  // Bornes : le brut ne dépend pas des hypothèses patronales, on le fixe (pas d'inversion).
  e.setSituation(situationSalarie(p, annee, sc.bas, brut) as never)
  const bas = lireEmployeur()
  e.setSituation(situationSalarie(p, annee, sc.haut, brut) as never)
  const haut = lireEmployeur()
  return {
    brut,
    netAnnuel,
    imposable,
    salarie: sal,
    csgDeductible,
    csgNonDeductible: csgTotal - csgDeductible,
    crds,
    cotisationsSalarieTotal,
    employeur: { bas, central, haut },
  }
}

/** Parts rattachées aux enfants (garde alternée : demi-valeur, enfants à charge exclusive comptés d'abord). */
export function partsEnfants(enfants: { garde_alternee?: boolean }[]): number {
  const tri = [...enfants].sort((a, b) => Number(!!a.garde_alternee) - Number(!!b.garde_alternee))
  return tri.reduce((s, enf, i) => s + (i < 2 ? 0.5 : 1) * (enf.garde_alternee ? 0.5 : 1), 0)
}

interface FoyerFiscal {
  couple: boolean
  parentIsole: boolean
  enfants: { garde_alternee?: boolean }[]
  imposables: number[]
}

/** Impôt sur le revenu d'un foyer (barème de l'année de revenus, appliqué l'année suivante). */
export function impotFoyer(ff: FoyerFiscal, anneeRevenus: number): number {
  const e = obtenirMoteur()
  const date = `'01/01/${anneeRevenus + 1}'`
  const base = { date, 'impôt . méthode de calcul': "'barème standard'" }
  // Abattement de 10 % appliqué à chaque salaire séparément (plancher et plafond individuels).
  let abattu = 0
  for (const x of ff.imposables) {
    e.setSituation({ ...base, "impôt . foyer fiscal . revenu imposable . revenu d'activité": `${x} €/an` } as never)
    abattu += evaluer(e, "impôt . foyer fiscal . revenu imposable . revenu d'activité abattu")
  }
  const s: Record<string, string> = {
    ...base,
    'impôt . foyer fiscal . situation de famille': ff.couple ? "'couple'" : "'célibataire'",
    'impôt . foyer fiscal . enfants à charge': `${ff.enfants.length} enfant`,
    "impôt . foyer fiscal . revenu imposable . revenu d'activité": '0 €/an',
    'impôt . foyer fiscal . revenu imposable . autres revenus imposables': `${abattu} €/an`,
  }
  if (ff.enfants.length) s['impôt . foyer fiscal . nombre de parts . rattachées'] = `${partsEnfants(ff.enfants)} part`
  if (ff.parentIsole && ff.enfants.length) {
    s['impôt . foyer fiscal . parent isolé'] = 'oui'
    if (ff.enfants.every((x) => x.garde_alternee))
      s['impôt . foyer fiscal . nombre de parts . majoration personne seule avec enfant'] = '0.25 part'
  }
  e.setSituation(s as never)
  return Math.max(0, Math.round(evaluer(e, 'impôt . foyer fiscal . impôt sur le revenu')))
}

function additionner(lignes: Prelevement[]): Fourchette {
  const t = { bas: 0, central: 0, haut: 0 }
  for (const l of lignes) {
    if (l.nature === 'reduction') {
      t.bas -= l.montant_annuel_eur.haut
      t.central -= l.montant_annuel_eur.central
      t.haut -= l.montant_annuel_eur.bas
    } else {
      t.bas += l.montant_annuel_eur.bas
      t.central += l.montant_annuel_eur.central
      t.haut += l.montant_annuel_eur.haut
    }
  }
  return { bas: arrondi(Math.max(0, t.bas)), central: arrondi(Math.max(0, t.central)), haut: arrondi(Math.max(0, t.haut)) }
}

/** Totaux par destinataire ; avec inclutPatronal, ajoute les cotisations patronales (réductions déduites). */
export function parDestinataire(prelevements: Prelevement[], inclutPatronal: boolean) {
  const groupes = new Map<IdDestinataire, Prelevement[]>()
  for (const l of prelevements) {
    if (!l.inclus_dans_total_paye && !inclutPatronal) continue
    if (l.ventilation && l.ventilation.length) {
      for (const v of l.ventilation) {
        const part: Prelevement = {
          ...l,
          montant_annuel_eur: {
            bas: l.montant_annuel_eur.bas * v.part,
            central: l.montant_annuel_eur.central * v.part,
            haut: l.montant_annuel_eur.haut * v.part,
          },
        }
        const g = groupes.get(v.destinataire) ?? []
        g.push(part)
        groupes.set(v.destinataire, g)
      }
    } else {
      const g = groupes.get(l.destinataire.id) ?? []
      g.push(l)
      groupes.set(l.destinataire.id, g)
    }
  }
  return [...groupes.entries()]
    .map(([destinataire, ls]) => ({ destinataire, montant_annuel_eur: additionner(ls), inclut_patronal: inclutPatronal }))
    .sort((a, b) => b.montant_annuel_eur.central - a.montant_annuel_eur.central)
}

function ventiler(id: string, affectation?: Affectation | null) {
  const a = affectation?.prelevements?.[id]?.ventilation
  if (!a || !a.length) return undefined
  const somme = a.reduce((s, v) => s + v.part, 0)
  if (Math.abs(somme - 1) > 0.001) return undefined
  if (!a.every((v) => v.destinataire in DESTINATAIRES)) return undefined
  return a.map((v) => ({ destinataire: v.destinataire as IdDestinataire, part: v.part }))
}

/** Calcule le résultat (contrat 3.3) pour un profil. Synchrone ; prévoir ~0,5 s la première fois. */
export function calculer(profil: Profil, options: OptionsCalcul = {}): Resultat {
  const erreur = verifierProfil(profil)
  if (erreur) return erreur
  const sc = options.scenarios ?? SCENARIOS_SITE
  const annee = profil.annee_revenus
  const prelevements: Prelevement[] = []
  const avertissements: Avertissement[] = []
  const entree: ResultatOk['entree']['personnes'] = []
  const imposables: Record<string, number> = {}
  let brutTotal = 0
  let calculs: { p: Personne; c: CalculSalarie }[]
  try {
    calculs = profil.personnes
      .filter((p) => p.statut_activite === 'salarie_prive')
      .map((p) => ({ p, c: calculerSalarie(p, annee, sc) }))
  } catch (e) {
    return {
      statut: 'erreur',
      version_contrat: '1.0',
      erreur: { code: 'MOTEUR_INDISPONIBLE', message: 'Le calcul est indisponible pour le moment. Tu peux toujours explorer le budget.' },
    }
  }

  for (const { p, c } of calculs) {
    const role = p.role
    brutTotal += c.brut
    imposables[role] = c.imposable
    entree.push({ role, salaire_net_avant_impot_annuel: arrondi(c.netAnnuel), salaire_brut_annuel_estime: f(c.brut) })
    const regle = (r: string) => 'salarié . cotisations . ' + r
    for (const [id, libelle, r, dest] of LIGNES_SALARIE) {
      const m = c.salarie[id]
      if (m > 0.005)
        prelevements.push({
          id: `${id}_${role}`.replace(/_declarant1$/, ''),
          libelle,
          famille: 'cotisation_salariale',
          personne: role,
          assiette_annuelle_eur: arrondi(c.brut),
          taux: null,
          montant_annuel_eur: f(m),
          destinataire: DESTINATAIRES[dest],
          inclus_dans_total_paye: true,
          regle: regle(r),
        })
    }
    // Contrôle de complétude : ce que modele-social compte et qui n'est pas listé ci-dessus.
    const listees = LIGNES_SALARIE.reduce((s, [id]) => s + c.salarie[id], 0) + c.csgDeductible + c.csgNonDeductible + c.crds
    const reste = c.cotisationsSalarieTotal - listees
    if (Math.abs(reste) > 1)
      prelevements.push({
        id: suffixe('autres_cotisations_salarie', role),
        libelle: 'Autres cotisations salariales',
        famille: 'cotisation_salariale',
        personne: role,
        montant_annuel_eur: f(Math.max(0, reste)),
        destinataire: DESTINATAIRES.plusieurs,
        inclus_dans_total_paye: true,
        regle: 'salarié . cotisations . salarié',
      })
    const assietteCsg = c.csgDeductible / 0.068
    const csgVentil = (id: string) => {
      const v = ventiler(id, options.affectation)
      return v ? { ventilation: v } : {}
    }
    prelevements.push(
      {
        id: suffixe('csg_deductible', role),
        libelle: 'CSG déductible',
        famille: 'csg_crds',
        personne: role,
        assiette_annuelle_eur: arrondi(assietteCsg),
        taux: 0.068,
        montant_annuel_eur: f(c.csgDeductible),
        destinataire: DESTINATAIRES.plusieurs,
        inclus_dans_total_paye: true,
        regle: regle('CSG-CRDS . CSG . déductible'),
        ...csgVentil('csg_deductible'),
      },
      {
        id: suffixe('csg_non_deductible', role),
        libelle: 'CSG non déductible',
        famille: 'csg_crds',
        personne: role,
        assiette_annuelle_eur: arrondi(assietteCsg),
        taux: 0.024,
        montant_annuel_eur: f(c.csgNonDeductible),
        destinataire: DESTINATAIRES.plusieurs,
        inclus_dans_total_paye: true,
        regle: regle('CSG-CRDS . CSG'),
        ...csgVentil('csg_non_deductible'),
      },
      {
        id: suffixe('crds', role),
        libelle: 'CRDS (remboursement de la dette sociale)',
        famille: 'csg_crds',
        personne: role,
        assiette_annuelle_eur: arrondi(assietteCsg),
        taux: 0.005,
        montant_annuel_eur: f(c.crds),
        destinataire: DESTINATAIRES.cades,
        inclus_dans_total_paye: true,
        regle: regle('CSG-CRDS . CRDS'),
      },
    )
    const E = c.employeur
    for (const [id, libelle, r, dest] of LIGNES_EMPLOYEUR) {
      const m = f3(E.bas[id], E.central[id], E.haut[id])
      if (m.haut > 0.005)
        prelevements.push({
          id: suffixe(id, role),
          libelle,
          famille: 'cotisation_patronale',
          personne: role,
          assiette_annuelle_eur: arrondi(c.brut),
          taux: null,
          montant_annuel_eur: m,
          destinataire: DESTINATAIRES[dest],
          inclus_dans_total_paye: false,
          regle: regle(r),
          ...(m.bas !== m.haut ? { hypothese_fourchette: HYPOTHESE_FOURCHETTE_PATRONALE } : {}),
        })
    }
    const red = f3(E.bas.reduction_generale, E.central.reduction_generale, E.haut.reduction_generale)
    if (red.haut > 0.005)
      prelevements.push({
        id: suffixe('reduction_generale', role),
        libelle: 'Réduction générale de cotisations patronales (à déduire)',
        famille: 'cotisation_patronale',
        personne: role,
        montant_annuel_eur: red,
        nature: 'reduction',
        destinataire: DESTINATAIRES.plusieurs,
        inclus_dans_total_paye: false,
        regle: regle('exonérations . employeur'),
        hypothese_fourchette: HYPOTHESE_FOURCHETTE_PATRONALE,
      })
    const net = p.salaire_net_avant_impot_mensuel ?? 0
    const q = quotite(p)
    if (net / q < SMIC_NET_MENSUEL_2025 * 0.98 || c.brut > 4 * PASS_ANNUEL_2025)
      avertissements.push({
        code: 'SAISIE_ATYPIQUE',
        message:
          net / q < SMIC_NET_MENSUEL_2025 * 0.98
            ? "Ce salaire, ramené à un temps plein, est inférieur au SMIC net : vérifie la saisie. Le résultat reste affiché mais il est moins fiable."
            : 'Au-delà de 4 plafonds de la Sécurité sociale, certaines règles (prévoyance, retraite supplémentaire) pèsent davantage : résultat moins fiable.',
        champ: `/personnes/${profil.personnes.indexOf(p)}/salaire_net_avant_impot_mensuel`,
      })
  }

  // Impôt sur le revenu : un foyer, sauf union libre (deux foyers, enfants rattachés au déclarant 1).
  const sit = profil.foyer.situation
  const enfants = profil.foyer.enfants
  const lignesIR: { id: string; libelle: string; montant: number }[] = []
  if (sit === 'couple_union_libre') {
    const ir1 = impotFoyer({ couple: false, parentIsole: false, enfants, imposables: imposables.declarant1 ? [imposables.declarant1] : [] }, annee)
    const ir2 = impotFoyer({ couple: false, parentIsole: false, enfants: [], imposables: imposables.declarant2 ? [imposables.declarant2] : [] }, annee)
    lignesIR.push({ id: 'impot_revenu', libelle: 'Impôt sur le revenu (foyer de la personne 1)', montant: ir1 })
    lignesIR.push({ id: 'impot_revenu_declarant2', libelle: 'Impôt sur le revenu (foyer de la personne 2)', montant: ir2 })
  } else {
    const ir = impotFoyer(
      {
        couple: sit === 'couple_marie_pacse',
        parentIsole: sit === 'parent_isole',
        enfants,
        imposables: Object.values(imposables),
      },
      annee,
    )
    lignesIR.push({ id: 'impot_revenu', libelle: 'Impôt sur le revenu du foyer', montant: ir })
  }
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

  // Taxe foncière : uniquement le montant lu sur l'avis (sinon, seul le taux communal est montré).
  const tf = profil.logement?.taxe_fonciere_annuelle_eur
  if (profil.logement?.statut === 'proprietaire' && typeof tf === 'number' && tf > 0)
    prelevements.push({
      id: 'taxe_fonciere',
      libelle: "Taxe foncière (montant de ton avis, TEOM comprise s'il y en a une)",
      famille: 'impot_local',
      personne: 'logement',
      assiette_annuelle_eur: null,
      taux: null,
      montant_annuel_eur: f(tf),
      destinataire: DESTINATAIRES.commune,
      inclus_dans_total_paye: true,
      regle: 'saisie : avis de taxe foncière',
    })
  if (options.commune === null)
    avertissements.push({
      code: 'COMMUNE_INCONNUE',
      message: "Commune introuvable dans les taux 2025 : le calcul continue sans taxe foncière ni TEOM.",
      champ: '/residence/commune_insee',
    })
  else if (options.commune && options.commune[2] === null)
    avertissements.push({
      code: 'TEOM_ABSENTE',
      message: "Pas de TEOM dans ta commune : les déchets y sont financés par une redevance ou par le budget général.",
    })
  if (!options.affectation)
    avertissements.push({
      code: 'DONNEE_ABSENTE',
      message: "La répartition de la CSG entre les branches de la Sécurité sociale n'est pas encore publiée par le site : elle apparaît comme « plusieurs branches ».",
      details: { fichier: 'affectation_prelevements.json' },
    })

  const paye = additionner(prelevements.filter((l) => l.inclus_dans_total_paye))
  const patronal = additionner(prelevements.filter((l) => l.famille === 'cotisation_patronale'))
  const resultat: ResultatOk = {
    statut: 'ok',
    version_contrat: '1.0',
    annee_legislation: annee,
    moteur: { nom: 'modele-social', version: VERSION_MODELE_SOCIAL, publicodes: VERSION_PUBLICODES },
    entree: { personnes: entree },
    prelevements,
    totaux: {
      paye_par_le_foyer: paye,
      patronal,
      cout_total_employeur: {
        bas: arrondi(brutTotal + patronal.bas),
        central: arrondi(brutTotal + patronal.central),
        haut: arrondi(brutTotal + patronal.haut),
      },
      par_destinataire: parDestinataire(prelevements, false),
    },
    avertissements,
  }
  return resultat
}

function suffixe(id: string, role: string) {
  return role === 'declarant1' ? id : `${id}_${role}`
}

/** Valeurs agrégées comparables à OpenFisca (contrat 3.6), utilisées par les tests. */
export function agregatsPersonne(profil: Profil, role: 'declarant1' | 'declarant2', sc: Scenarios = SCENARIOS_OPENFISCA) {
  const p = profil.personnes.find((x) => x.role === role)
  if (!p) throw new Error('personne absente')
  const c = calculerSalarie(p, profil.annee_revenus, sc)
  return {
    salaire_brut: c.brut,
    cotisations_salariales: c.cotisationsSalarieTotal - c.csgDeductible - c.csgNonDeductible - c.crds,
    csg: c.csgDeductible + c.csgNonDeductible,
    crds: c.crds,
    cotisations_patronales: c.employeur.central.total,
    reduction_generale: c.employeur.central.reduction_generale,
    salaire_imposable: c.imposable,
  }
}

// Prélèvements hors bulletin de paie (contrat 1.4, site/data/prelevements/) :
// taxes sur la consommation par décile de niveau de vie, taxe foncière et TEOM par commune.
// Aucun appel réseau ici : les fichiers sont fournis par l'écran.
import { destinataire } from './destinataires'
import { additionner, appliquerAffectation, type Affectation } from './moteur'
import type { Fourchette, Prelevement, Profil, ResultatOk } from './types'

type F = { bas: number; central: number; haut: number }
interface Tranche {
  decile: number
  niveau_de_vie_min_eur: number | null
  niveau_de_vie_max_eur: number | null
  taxes_produits_eur_par_uc: F
  detail_eur_par_uc: Record<string, F & { part: number }>
  ajustements: {
    voiture?: { taux_equipement_pct_2017: number; ticpe_si_voiture_eur_par_uc: number; ticpe_sans_voiture_eur_par_uc: number; source?: string }
    fumeur?: { tabac_non_fumeur_eur_par_uc: number; tabac_fumeur_eur_par_uc: number | null; note?: string }
  }
}
export interface TvaConso {
  millesime: string
  source: string
  unite: string
  methode: string[]
  limites: string[]
  deciles_niveau_de_vie: { annee: string; bornes_eur_par_an: number[]; source: string }
  ecarts_au_total_national: Record<string, { estime_md: number; reel_md: number; ecart_pct: number }>
  tranches: Tranche[]
  non_sourcé?: string[]
}
/** Ligne d'une commune dans prelevements/taxe_fonciere/<dep>.json. */
export type CommuneTF = (number | null)[] | null
export interface TaxeFonciereDep {
  millesime: string
  source: string
  communes: Record<string, CommuneTF>
}

export type Choix = 'oui' | 'non' | 'inconnu'
export interface HabitudesConso {
  voiture: Choix
  fumeur: Choix
}

export interface Placement {
  unites_consommation: number
  revenu_disponible_eur: number
  niveau_de_vie_eur: number
  decile: number
}

const LIBELLES_CONSO: Record<string, string> = {
  tva: 'TVA',
  ticpe: 'Taxe sur les carburants (accise ex-TICPE)',
  tabac: 'Taxes sur le tabac',
  alcool: 'Taxes sur les alcools',
  autres: 'Autres taxes sur les produits (électricité, gaz, assurances, etc.)',
}

/** Unités de consommation (échelle OCDE modifiée, comme tva_conso.json) ; enfant en garde alternée compté pour moitié. */
export function unitesConsommation(profil: Profil): number {
  const adultes = profil.foyer.situation.startsWith('couple') ? 2 : 1
  const age = (n: number) => profil.annee_revenus - n
  const enfants = profil.foyer.enfants.reduce(
    (s, e) => s + (age(e.annee_naissance) >= 14 ? 0.5 : 0.3) * (e.garde_alternee ? 0.5 : 1),
    0,
  )
  return Math.round((1 + 0.5 * (adultes - 1) + enfants) * 1000) / 1000
}

/** Revenu disponible approché : salaires nets avant impôt moins impôt sur le revenu (sans prestations ni autres revenus). */
export function placer(profil: Profil, r: ResultatOk, t: TvaConso): Placement {
  const net = r.entree.personnes.reduce((s, p) => s + p.salaire_net_avant_impot_annuel, 0)
  const ir = r.prelevements.filter((l) => l.famille === 'impot_revenu').reduce((s, l) => s + l.montant_annuel_eur.central, 0)
  const dispo = Math.max(0, net - ir)
  const uc = unitesConsommation(profil)
  const nv = dispo / uc
  const bornes = t.deciles_niveau_de_vie.bornes_eur_par_an
  const decile = bornes.filter((b) => nv >= b).length + 1
  return { unites_consommation: uc, revenu_disponible_eur: Math.round(dispo), niveau_de_vie_eur: Math.round(nv), decile }
}

const fois = (f: F, k: number): Fourchette => ({ bas: arr(f.bas * k), central: arr(f.central * k), haut: arr(f.haut * k) })
const arr = (x: number) => Math.round(x * 100) / 100

/** Lignes de taxes sur la consommation du ménage (euros par an), avec ajustements voiture et tabac sourcés. */
export function taxesConsommation(placement: Placement, t: TvaConso, h: HabitudesConso): Prelevement[] {
  const tr = t.tranches.find((x) => x.decile === placement.decile)
  if (!tr) return []
  const uc = placement.unites_consommation
  const lignes: Prelevement[] = []
  for (const [taxe, d] of Object.entries(tr.detail_eur_par_uc)) {
    let f: F = d
    let note = ''
    let non_chiffre = false
    const v = tr.ajustements.voiture
    if (taxe === 'ticpe' && v && h.voiture !== 'inconnu') {
      if (h.voiture === 'oui') {
        const k = d.central > 0 ? v.ticpe_si_voiture_eur_par_uc / d.central : 1
        f = { bas: d.bas * k, central: d.central * k, haut: d.haut * k }
        note = `Ajusté : foyer équipé d’une voiture (dépense de carburant des ménages équipés, ${v.taux_equipement_pct_2017} % des ménages de ce décile en 2017).`
      } else {
        f = { bas: v.ticpe_sans_voiture_eur_par_uc, central: v.ticpe_sans_voiture_eur_par_uc, haut: v.ticpe_sans_voiture_eur_par_uc }
        note = 'Ajusté : foyer sans voiture.'
      }
    }
    const fu = tr.ajustements.fumeur
    if (taxe === 'tabac' && fu && h.fumeur !== 'inconnu') {
      if (h.fumeur === 'non') {
        f = { bas: fu.tabac_non_fumeur_eur_par_uc, central: fu.tabac_non_fumeur_eur_par_uc, haut: fu.tabac_non_fumeur_eur_par_uc }
        note = 'Ajusté : personne ne fume dans le foyer.'
      } else if (fu.tabac_fumeur_eur_par_uc === null) {
        non_chiffre = true
        note = 'Non chiffré : le montant payé par un fumeur n’est pas publié (la moyenne du décile le sous-estimerait).'
      } else {
        const x = fu.tabac_fumeur_eur_par_uc
        f = { bas: x, central: x, haut: x }
      }
    }
    if (taxe === 'tabac' && h.fumeur === 'inconnu') note = 'Moyenne du décile, fumeurs et non-fumeurs confondus.'
    if (taxe === 'ticpe' && h.voiture === 'inconnu') note = 'Moyenne du décile, avec ou sans voiture.'
    const m = fois(f, uc)
    lignes.push({
      id: taxe,
      libelle: LIBELLES_CONSO[taxe] ?? taxe,
      famille: 'taxe_consommation',
      personne: 'foyer',
      assiette_annuelle_eur: null,
      taux: null,
      montant_annuel_eur: { bas: Math.min(m.bas, m.central), central: m.central, haut: Math.max(m.haut, m.central) },
      destinataire:
        taxe === 'autres'
          ? { id: 'autres_taxes_produits', nom: 'Plusieurs bénéficiaires (répartition non sourcée)', administration: 'Plusieurs' }
          : destinataire('etat'),
      inclus_dans_total_paye: true,
      regle: `prelevements/tva_conso.json, décile ${placement.decile}, ${taxe} × ${uc} UC`,
      hypothese_fourchette: 'Central : taxes réparties comme la consommation (hypothèse Insee de référence). Bas et haut : variante Insee où ces taxes sont imputées aux revenus.',
      ...(taxe === 'autres' ? { statut_affectation: 'non sourcee' as const } : {}),
      ...(note ? { note } : {}),
      ...(non_chiffre ? { non_chiffre: true } : {}),
      source: t.source,
    })
  }
  return lignes
}

const DEST_TF = ['commune', 'epci', 'syndicats', 'tse', 'region_idf', 'etat']

/**
 * Taxe foncière (propriétaire) et TEOM (propriétaire ou locataire via les charges).
 * Le montant de l'avis saisi remplace l'estimation (TEOM comprise) ; seules les parts servent alors.
 */
export function impotsLocaux(profil: Profil, ligne: CommuneTF | undefined, tfDep: TaxeFonciereDep | null): Prelevement[] {
  const statut = profil.logement?.statut
  if (!statut || statut === 'loge_gratuitement') return []
  const avis = profil.logement?.taxe_fonciere_annuelle_eur
  const parts = ligne ? ligne.slice(6, 12).map((x) => Number(x ?? 0)) : null
  const ventTF =
    parts && Math.abs(parts.reduce((s, x) => s + x, 0) - 1) < 0.01
      ? DEST_TF.map((d, i) => ({ destinataire: d, part: parts[i] })).filter((v) => v.part > 0)
      : undefined
  const base = {
    personne: 'logement' as const,
    assiette_annuelle_eur: null,
    taux: null,
    inclus_dans_total_paye: true,
    source: tfDep ? `${tfDep.source} (${tfDep.millesime})` : undefined,
  }
  const out: Prelevement[] = []
  const fx = (i: number): Fourchette | null =>
    ligne && ligne[i] !== null && ligne[i + 1] !== null && ligne[i + 2] !== null
      ? { bas: Number(ligne[i]), central: Number(ligne[i + 1]), haut: Number(ligne[i + 2]) }
      : null
  if (statut === 'proprietaire') {
    if (typeof avis === 'number' && avis > 0) {
      out.push({
        ...base,
        id: 'taxe_fonciere',
        libelle: 'Taxe foncière (montant de ton avis, TEOM comprise s’il y en a une)',
        famille: 'impot_local',
        montant_annuel_eur: { bas: avis, central: avis, haut: avis },
        destinataire: destinataire('commune'),
        regle: 'saisie : avis de taxe foncière',
        ...(ventTF ? { ventilation: ventTF, statut_affectation: 'sourcee' as const } : {}),
      })
      return out
    }
    const tf = fx(0)
    out.push({
      ...base,
      id: 'taxe_fonciere',
      libelle: 'Taxe foncière estimée (ta commune, logement moyen)',
      famille: 'impot_local',
      montant_annuel_eur: tf ?? { bas: 0, central: 0, haut: 0 },
      destinataire: destinataire('commune'),
      regle: 'prelevements/taxe_fonciere/<dep>.json, positions 0 à 2',
      hypothese_fourchette: 'La valeur locative de ton logement (surface, catégorie) est inconnue : estimation à partir des logements de ta commune ou de ton département.',
      ...(tf ? {} : { non_chiffre: true, note: ligne === undefined ? 'Non chiffré : indique ta commune pour l’estimer.' : 'Non chiffré : pas d’estimation publiée pour cette commune.' }),
      ...(ventTF ? { ventilation: ventTF, statut_affectation: 'sourcee' as const } : {}),
    })
  }
  const teom = fx(3)
  const sansTeom = ligne && ligne[3] === null
  if (!sansTeom)
    out.push({
      ...base,
      id: 'teom',
      libelle:
        statut === 'locataire'
          ? 'Taxe d’enlèvement des ordures ménagères (dans tes charges, estimée)'
          : 'Taxe d’enlèvement des ordures ménagères (avec la taxe foncière, estimée)',
      famille: 'impot_local',
      montant_annuel_eur: teom ?? { bas: 0, central: 0, haut: 0 },
      destinataire: destinataire('commune'),
      regle: 'prelevements/taxe_fonciere/<dep>.json, positions 3 à 5',
      hypothese_fourchette: 'Taux de TEOM de la commune appliqué à une base de logement estimée.',
      ...(teom ? {} : { non_chiffre: true, note: 'Non chiffré : indique ta commune pour l’estimer.' }),
    })
  return out
}

export interface Complet {
  lignes: Prelevement[]
  total: Fourchette
  placement: Placement | null
  conso: Prelevement[]
  locaux: Prelevement[]
}

/** Assemble le total « ce que tu paies » : prélevé sur salaire + taxes sur la consommation + impôts locaux. */
export function assembler(
  profil: Profil,
  r: ResultatOk,
  donnees: { tva: TvaConso | null; affectation: Affectation | null; tfDep: TaxeFonciereDep | null; ligneCommune: CommuneTF | undefined },
  habitudes: HabitudesConso,
): Complet {
  // La taxe foncière de l'avis éventuellement calculée par le moteur est reprise ici avec ses parts : pas de doublon.
  const salaire = r.prelevements.filter((l) => l.inclus_dans_total_paye && l.famille !== 'impot_local')
  const placement = donnees.tva ? placer(profil, r, donnees.tva) : null
  const conso = placement && donnees.tva ? appliquerAffectation(taxesConsommation(placement, donnees.tva, habitudes), donnees.affectation) : []
  const locaux = appliquerAffectation(impotsLocaux(profil, donnees.ligneCommune, donnees.tfDep), donnees.affectation)
  const lignes = [...salaire, ...conso, ...locaux]
  return { lignes, total: additionner(lignes), placement, conso, locaux }
}

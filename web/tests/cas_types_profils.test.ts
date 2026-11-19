// Cas types des profils étendus (tests/cas_types/cas_types_profils.json) : chaque profil doit tomber à moins de 1 %
// de ses valeurs de référence (API OpenFisca, API mon-entreprise). Détail et écarts hors critère : web/ECARTS.md.
// Avec ECARTS_PROFILS=1, le test écrit le détail dans ecarts_cas_types_profils.json (non versionné).
import { readFileSync, writeFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { SCENARIOS_OPENFISCA } from '../src/calcul/moteur'
import { affectationsManquantes, agregatsProfil, calculerProfil, pensionsApresAbattement, profilDe, verifierProfilEtendu } from '../src/calcul/moteur-etendu'
import { tauxCsgPension } from '../src/calcul/baremes-2025'
import type { Affectation } from '../src/calcul/agregats'
import type { PersonneEtendue, ProfilEtendu } from '../src/calcul/types'

const donnees = JSON.parse(readFileSync(new URL('../../tests/cas_types/cas_types_profils.json', import.meta.url), 'utf8'))
const affectation = JSON.parse(readFileSync(new URL('../../site/data/prelevements/affectation.json', import.meta.url), 'utf8')) as Affectation
const TOL = donnees.tolerance_relative as number
const ecart = (a: number, ref: number) => (ref === 0 ? (Math.abs(a) < 1 ? 0 : Infinity) : (a - ref) / ref)
// Impôt des foyers avec un retraité : OpenFisca 175.0.45 garde pour 2025 les abattements des revenus 2024 (pensions
// 450 € et 4 399 €, plus de 65 ans 2 795 € et 1 398 €) ; le site applique ceux des revenus 2025. Écart admis : 1 % ou 5 €.
const TOLERANCE_IMPOT_RETRAITES_EUR = 5
const rapport: Record<string, unknown>[] = []

type Ref = Record<string, number>
const SALARIAL = ['salaire_brut', 'cotisations_salariales', 'csg', 'crds'] as const
const MICRO = ['cotisations_et_contributions', 'cotisations', 'maladie_maternite', 'invalidite_deces', 'retraite_base', 'retraite_complementaire', 'csg_crds', 'formation_professionnelle', 'taxe_chambre_consulaire'] as const

/** Même profil, pensions complémentaires fondues dans la pension de base : comparable à OpenFisca, qui ignore la cotisation de 1 %. */
function sansCotisationComplementaire(profil: ProfilEtendu): ProfilEtendu {
  return {
    ...profil,
    personnes: profil.personnes.map((p) =>
      p.statut_activite === 'retraite'
        ? { ...p, pension_base_mensuelle: (p.pension_base_mensuelle ?? 0) + (p.pension_complementaire_mensuelle ?? 0), pension_complementaire_mensuelle: 0 }
        : p,
    ),
  }
}
const impot = (profil: ProfilEtendu) => {
  const r = calculerProfil(profil, { scenarios: SCENARIOS_OPENFISCA })
  if (r.statut !== 'ok') throw new Error(JSON.stringify(r.erreur))
  return r.prelevements.filter((l) => l.famille === 'impot_revenu' && !l.id.startsWith('impot_revenu_versement_liberatoire')).reduce((s, l) => s + l.montant_annuel_eur.central, 0)
}

describe('cas types des profils étendus (tolérance 1 %)', () => {
  it('la référence est générée', () => {
    expect(donnees.reference.statut).toBe('ok')
    expect(donnees.cas.length).toBeGreaterThanOrEqual(37)
    const parGroupe = new Map<string, number>()
    for (const c of donnees.cas) parGroupe.set(c.groupe, (parGroupe.get(c.groupe) ?? 0) + 1)
    for (const [g, n] of parGroupe) expect(n, g).toBeGreaterThanOrEqual(3)
  })

  for (const cas of donnees.cas) {
    it(`${cas.id} ${cas.libelle}`, () => {
      const profil = cas.profil as ProfilEtendu
      const ref = cas.reference
      const verifier = (role: string, source: string, cle: string, obtenu: number, attendu: number, critere = true) => {
        const e = ecart(obtenu, attendu)
        rapport.push({ cas: cas.id, groupe: cas.groupe, role, source, cle, obtenu: Math.round(obtenu * 100) / 100, reference: attendu, ecart: e, critere })
        if (critere) expect(Math.abs(e), `${cas.id} ${role} ${cle} (${source}) : ${obtenu} contre ${attendu}`).toBeLessThan(TOL)
      }
      for (const p of profil.personnes) {
        const a = agregatsProfil(profil, p.role, SCENARIOS_OPENFISCA)
        const of = ref.personnes[p.role] as Ref | undefined
        const me = ref.mon_entreprise[p.role] as Ref | undefined
        const type = profilDe(p)
        if (type === 'retraite' && of) {
          for (const k of ['retraite_brute', 'csg', 'crds', 'casa'] as const) verifier(p.role, 'openfisca', k, a[k], of[k])
          // OpenFisca ne retire pas la cotisation maladie de 1 % sur la pension complémentaire.
          verifier(p.role, 'openfisca', 'retraite_nette', a.retraite_nette + a.maladie_retraite_complementaire, of.retraite_nette)
          verifier(p.role, 'openfisca', 'retraite_imposable', a.retraite_imposable + a.maladie_retraite_complementaire, of.retraite_imposable)
        } else if (type === 'micro_entrepreneur' && me) {
          for (const k of MICRO) verifier(p.role, 'mon-entreprise', k, a[k], me[k])
          if (me.versement_liberatoire !== undefined) {
            verifier(p.role, 'mon-entreprise', 'versement_liberatoire', a.versement_liberatoire, me.versement_liberatoire)
            verifier(p.role, 'openfisca', 'versement_liberatoire', a.versement_liberatoire, ref.foyer.versement_liberatoire)
          }
        } else {
          if (of) {
            for (const k of SALARIAL) verifier(p.role, 'openfisca', k, a[k], of[k])
            verifier(p.role, 'openfisca', 'salaire_imposable', a.salaire_imposable, of.salaire_imposable)
            if (of.cotisation_regime_local !== undefined) verifier(p.role, 'openfisca', 'cotisation_regime_local', a.cotisation_regime_local, of.cotisation_regime_local)
            if (cas.groupe === 'smic') verifier(p.role, 'openfisca', 'reduction_generale', a.reduction_generale, of.reduction_generale)
            // Hors critère : part employeur (écarts expliqués dans ECARTS.md).
            if (type !== 'apprenti') verifier(p.role, 'openfisca', 'cotisations_patronales', a.cotisations_patronales, of.cotisations_patronales, false)
          }
          if (me) for (const k of SALARIAL) verifier(p.role, 'mon-entreprise', k, a[k], me[k])
        }
      }
      const ir = impot(sansCotisationComplementaire(profil))
      if (ref.foyer.impot_revenu === null) {
        // Apprentis hors référence OpenFisca : salaire sous l'exonération d'impôt, impôt nul attendu.
        expect(ir).toBe(0)
        rapport.push({ cas: cas.id, groupe: cas.groupe, role: 'foyer', source: 'non recoupé', cle: 'impot_revenu', obtenu: ir, reference: null, ecart: null, critere: false })
      } else if (profil.personnes.some((p) => p.statut_activite === 'retraite') && Math.abs(ir - ref.foyer.impot_revenu) <= TOLERANCE_IMPOT_RETRAITES_EUR)
        rapport.push({ cas: cas.id, groupe: cas.groupe, role: 'foyer', source: 'openfisca', cle: 'impot_revenu', obtenu: ir, reference: ref.foyer.impot_revenu, ecart: ecart(ir, ref.foyer.impot_revenu), critere: true, tolerance: '5 €' })
      else verifier('foyer', 'openfisca', 'impot_revenu', ir, ref.foyer.impot_revenu)
      // La cotisation de 1 % est déductible : l'impôt réel du foyer ne dépasse jamais celui du calcul comparable.
      expect(impot(profil)).toBeLessThanOrEqual(ir)
    })
  }

  it('écrit le rapport des écarts sur demande', () => {
    if (process.env.ECARTS_PROFILS) writeFileSync(new URL('../ecarts_cas_types_profils.json', import.meta.url), JSON.stringify(rapport, null, 1))
    expect(rapport.length).toBeGreaterThan(150)
  })
})

describe('profils étendus : saisie, inversion, périmètre, affectation', () => {
  const base = (personnes: PersonneEtendue[], extra: Partial<ProfilEtendu> = {}): ProfilEtendu => ({
    version_contrat: '1.0',
    annee_revenus: 2025,
    residence: { zone: 'metropole', alsace_moselle: false },
    foyer: { situation: 'celibataire', enfants: [] },
    personnes,
    ...extra,
  })
  const ok = (p: ProfilEtendu, o = {}) => {
    const r = calculerProfil(p, { scenarios: SCENARIOS_OPENFISCA, affectation, ...o })
    if (r.statut !== 'ok') throw new Error(JSON.stringify(r.erreur))
    return r
  }

  it('fonctionnaire : le net saisi redonne le traitement indiciaire', () => {
    const brut = base([{ role: 'declarant1', statut_activite: 'fonctionnaire', versant: 'territoriale', traitement_indiciaire_brut_mensuel: 2200, primes_mensuelles: 450 }])
    const a = agregatsProfil(brut, 'declarant1')
    const net = base([{ role: 'declarant1', statut_activite: 'fonctionnaire', versant: 'territoriale', salaire_net_avant_impot_mensuel: a.salaire_net_avant_impot / 12, primes_mensuelles: 450 }])
    expect(agregatsProfil(net, 'declarant1').traitement_indiciaire_brut).toBeCloseTo(26400, 1)
  })

  it('retraité : la pension nette saisie redonne la pension brute, taux lu ou déduit du revenu fiscal de référence', () => {
    const brut = base([{ role: 'declarant1', statut_activite: 'retraite', pension_saisie: 'brute', pension_base_mensuelle: 1900, pension_complementaire_mensuelle: 1300, csg_pension: { revenu_fiscal_reference: 36000, parts: 1 } }])
    const r = ok(brut)
    const lignes = Object.fromEntries(r.prelevements.map((l) => [l.id, l.montant_annuel_eur.central]))
    expect(lignes.maladie_retraite_complementaire).toBeCloseTo(156, 2)
    expect(lignes.casa).toBeCloseTo(115.2, 2)
    const nette = base([{ role: 'declarant1', statut_activite: 'retraite', pension_base_mensuelle: (1900 * (1 - 0.091)), pension_complementaire_mensuelle: 1300 * (1 - 0.101), csg_pension: { taux: 'normal' } }])
    expect(agregatsProfil(nette, 'declarant1').retraite_brute).toBeCloseTo(38400, 2)
    expect(tauxCsgPension(12817, 1)).toBe('exonere')
    expect(tauxCsgPension(12818, 1)).toBe('reduit')
    expect(tauxCsgPension(16756, 1)).toBe('median')
    expect(tauxCsgPension(26005, 1)).toBe('normal')
    expect(tauxCsgPension(26004 + 2 * 6941, 2)).toBe('median')
    expect(pensionsApresAbattement([3000])).toBe(2546)
    expect(pensionsApresAbattement([30000, 30000])).toBe(60000 - 4439)
  })

  it('refuse par défaut ce qui n’est pas vérifié, et les années sans barème', () => {
    const motif = (p: ProfilEtendu, o = {}) => {
      const r = calculerProfil(p, o)
      return r.statut === 'erreur' ? (r.erreur.motif ?? r.erreur.code) : 'ok'
    }
    const reel: PersonneEtendue = { role: 'declarant1', statut_activite: 'independant', independant: { regime: 'reel', categorie: 'artisan', revenu_professionnel_annuel: 40000 } }
    expect(motif(base([reel]))).toBe('independant_reel_non_verifie')
    const r = calculerProfil(base([reel]), { autoriserNonVerifie: true })
    expect(r.statut).toBe('ok')
    if (r.statut === 'ok') expect(r.verifications[0].statut).toBe('non verifie')
    const retraite: PersonneEtendue = { role: 'declarant1', statut_activite: 'retraite', pension_base_mensuelle: 1500, pension_complementaire_mensuelle: 0, csg_pension: { taux: 'median' } }
    expect(motif(base([retraite], { residence: { zone: 'metropole', alsace_moselle: true } }))).toBe('retraite_alsace_moselle')
    expect(motif(base([retraite], { annee_revenus: 2026 }))).toBe('annee_non_couverte')
    // Outre-mer : territoire exigé ; Mayotte et les collectivités à fiscalité propre restent hors calcul.
    expect(verifierProfilEtendu(base([retraite], { residence: { zone: 'dom', alsace_moselle: false } }))?.erreur.champ).toBe('/residence/territoire')
    expect(motif(base([retraite], { residence: { zone: 'dom', alsace_moselle: false, territoire: 'mayotte' } }))).toBe('mayotte')
    expect(motif(base([retraite], { residence: { zone: 'dom', alsace_moselle: false, territoire: 'autre_com' } }))).toBe('collectivite_outre_mer')
    expect(motif(base([retraite], { residence: { zone: 'dom', alsace_moselle: false, territoire: 'reunion' } }))).toBe('ok')
    expect(motif(base([{ role: 'declarant1', statut_activite: 'demandeur_emploi' }]))).toBe('demandeur_emploi')
    expect(motif(base([{ role: 'declarant1', statut_activite: 'sans_activite' }]))).toBe('sans_activite_seul')
    expect(verifierProfilEtendu(base([{ role: 'declarant1', statut_activite: 'retraite', pension_base_mensuelle: 1500, pension_complementaire_mensuelle: 0 }]))?.erreur.champ).toBe('/personnes/0/csg_pension')
    expect(verifierProfilEtendu(base([{ role: 'declarant1', statut_activite: 'fonctionnaire', versant: 'etat', traitement_indiciaire_brut_mensuel: 2000 }]))?.erreur.champ).toBe('/personnes/0/primes_mensuelles')
    expect(verifierProfilEtendu(base([{ role: 'declarant1', statut_activite: 'independant', independant: { regime: 'micro', activite: 'service_bnc', chiffre_affaires_annuel: 90000, versement_liberatoire: false } }]))?.erreur.champ).toBe('/personnes/0/independant/chiffre_affaires_annuel')
  })

  it('outre-mer : taux de CSG du relevé exigé, commune du territoire, réduction d’impôt plafonnée, pas de part employeur du privé', () => {
    const dom = (territoire: 'reunion' | 'guyane', commune_insee?: string) => ({ residence: { zone: 'dom' as const, alsace_moselle: false, territoire, ...(commune_insee ? { commune_insee } : {}) } })
    const retraiteRfr: PersonneEtendue = { role: 'declarant1', statut_activite: 'retraite', pension_base_mensuelle: 1500, pension_complementaire_mensuelle: 0, csg_pension: { revenu_fiscal_reference: 20000, parts: 1 } }
    expect(verifierProfilEtendu(base([retraiteRfr], dom('reunion')))?.erreur.champ).toBe('/personnes/0/csg_pension')
    const salarie: PersonneEtendue = { role: 'declarant1', statut_activite: 'salarie_prive', cadre: false, temps_travail: { type: 'temps_plein' }, salaire_net_avant_impot_mensuel: 2600 }
    expect(verifierProfilEtendu(base([salarie], dom('reunion', '97302')))?.erreur.champ).toBe('/residence/commune_insee')
    expect(verifierProfilEtendu(base([salarie], { residence: { zone: 'metropole', alsace_moselle: false, commune_insee: '97411' } }))?.erreur.champ).toBe('/residence/zone')
    const metro = ok(base([salarie]))
    const reunion = ok(base([salarie], dom('reunion', '97411')))
    const ir = (r: typeof metro) => r.prelevements.find((l) => l.id === 'impot_revenu')!.montant_annuel_eur.central
    // Mêmes cotisations et CSG ; impôt réduit ; aucune ligne de l'employeur (Lodeom non modélisé), pas de coût employeur.
    const salariales = (r: typeof metro) => r.prelevements.filter((l) => l.famille !== 'impot_revenu' && l.famille !== 'cotisation_patronale').map((l) => [l.id, l.montant_annuel_eur.central])
    expect(salariales(reunion)).toEqual(salariales(metro))
    expect(ir(reunion)).toBeLessThan(ir(metro))
    expect(reunion.prelevements.some((l) => l.famille === 'cotisation_patronale')).toBe(false)
    expect(reunion.totaux.cout_total_employeur?.central).toBe(0)
    expect(reunion.verifications.map((v) => v.profil)).toContain('outre_mer')
    expect(reunion.prelevements.find((l) => l.id === 'impot_revenu')?.note).toContain('197, I-3')
    // Plafond : 40 % de l'impôt au plus 4 050 € en Guyane.
    const cadre: PersonneEtendue = { ...salarie, cadre: true, salaire_net_avant_impot_mensuel: 12000 }
    const avant = ir(ok(base([cadre])))
    expect(avant - ir(ok(base([cadre], dom('guyane'))))).toBeCloseTo(4050, 0)
    // Fonctionnaire outre-mer : la part employeur reste calculée (pas de Lodeom pour un employeur public).
    const f: PersonneEtendue = { role: 'declarant1', statut_activite: 'fonctionnaire', versant: 'etat', traitement_indiciaire_brut_mensuel: 2000, primes_mensuelles: 800 }
    expect(ok(base([f], dom('reunion'))).prelevements.some((l) => l.id === 'contribution_cas_pensions')).toBe(true)
  })

  it('un salarié du privé donne les mêmes lignes que le calcul du contrat 1.0, et les totaux se recoupent', () => {
    const cas = donnees.cas.find((c: { id: string }) => c.id === 'X01')
    const r = ok(cas.profil)
    const somme = r.prelevements.filter((l) => l.inclus_dans_total_paye).reduce((s, l) => s + l.montant_annuel_eur.central, 0)
    expect(r.totaux.paye_par_le_foyer.central).toBeCloseTo(somme, 1)
    expect(r.entree.personnes.map((p) => p.profil)).toEqual(['fonctionnaire', 'salarie_prive'])
    expect(r.millesime.annee_revenus).toBe(2025)
    expect(r.verifications.map((v) => v.profil)).toEqual(['fonctionnaire', 'salarie_prive', 'foyer'])
  })

  it('affectation : aucune répartition supposée, les lignes sans entrée sont listées', () => {
    const manquantes = new Set<string>()
    for (const cas of donnees.cas) {
      const r = ok(cas.profil)
      for (const l of r.prelevements) {
        if (l.destinataire.id === 'non_affecte') {
          expect(l.ventilation, l.id).toBeUndefined()
          expect(l.statut_affectation).toBe('non sourcee')
          expect(r.affectations_manquantes.map((m) => m.id)).toContain(l.id.replace(/_declarant2$/, ''))
        }
      }
      for (const m of r.affectations_manquantes) {
        manquantes.add(m.id)
        // Clé absente, ou présente sans répartition publiée (« non sourcee », jamais complétée par une estimation).
        const a = affectation.prelevements[m.cle_proposee]
        if (a) {
          expect(a.statut, m.cle_proposee).toBe('non sourcee')
          expect(a.ventilation, m.cle_proposee).toEqual([])
        }
      }
      // CSG d'activité (salaire, traitement, forfait micro) : répartition publiée appliquée.
      for (const l of r.prelevements.filter((x) => /^csg_(deductible|non_deductible|micro)/.test(x.id))) expect(l.ventilation?.length, l.id).toBe(5)
    }
    expect([...manquantes].sort()).toEqual(
      [
        // Depuis le commit 32e891c : pensions des fonctionnaires, Ircantec, RAFP, CSG sur les pensions, Casa, retraite des
        // indépendants et régime local d'Alsace-Moselle sont répartis ; restent les lignes sans source publiée.
        'ags', 'apec_employeur', 'apec_salarie', 'atiacl', 'cet_employeur', 'cet_salarie',
        'fonds_emploi_hospitalier', 'formation_professionnelle', 'maladie_retraite_complementaire',
        'micro_formation_professionnelle', 'micro_invalidite_deces', 'micro_maladie_maternite', 'micro_taxe_chambre_consulaire',
        'reduction_generale', 'taxe_apprentissage',
      ].sort(),
    )
    expect(affectationsManquantes([], affectation)).toEqual([])
  })
})

// Les 20 cas types (tests/cas_types/cas_types.json) doivent tomber à moins de 1 %
// des valeurs OpenFisca sur : brut, cotisations salariales, CSG, CRDS, impôt du foyer.
import { readFileSync, writeFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { agregatsPersonne, calculer, SCENARIOS_OPENFISCA } from '../src/calcul/moteur'
import type { Profil } from '../src/calcul/types'

const fichier = new URL('../../tests/cas_types/cas_types.json', import.meta.url)
const donnees = JSON.parse(readFileSync(fichier, 'utf8'))
const TOL = donnees.tolerance_relative as number

const ecart = (a: number, ref: number) => (ref === 0 ? (Math.abs(a) < 1 ? 0 : Infinity) : (a - ref) / ref)
const rapport: Record<string, unknown>[] = []

describe('cas types OpenFisca (tolérance 1 %)', () => {
  for (const cas of donnees.cas) {
    it(`${cas.id} ${cas.libelle}`, () => {
      const profil = cas.profil as Profil
      const ref = cas.reference_openfisca
      for (const p of profil.personnes) {
        if (p.statut_activite !== 'salarie_prive') continue
        const a = agregatsPersonne(profil, p.role, SCENARIOS_OPENFISCA)
        const r = ref.personnes[p.role]
        const ligne: Record<string, unknown> = { cas: cas.id, role: p.role }
        for (const k of ['salaire_brut', 'cotisations_salariales', 'csg', 'crds'] as const) {
          const e = ecart(a[k], r[k])
          ligne[k] = e
          expect(Math.abs(e), `${cas.id} ${p.role} ${k} : ${a[k]} contre ${r[k]}`).toBeLessThan(TOL)
        }
        // Hors critère : cotisations patronales (documentées dans ECARTS.md).
        ligne.cotisations_patronales = ecart(a.cotisations_patronales, r.cotisations_patronales)
        ligne.patronal_avant_reduction = ecart(a.cotisations_patronales + a.reduction_generale, r.cotisations_patronales_avant_reduction)
        ligne.reduction_generale = ecart(a.reduction_generale, r.reduction_generale)
        rapport.push(ligne)
      }
      const res = calculer(profil, { scenarios: SCENARIOS_OPENFISCA })
      expect(res.statut).toBe('ok')
      if (res.statut !== 'ok') return
      const ir = res.prelevements.filter((l) => l.famille === 'impot_revenu').reduce((s, l) => s + l.montant_annuel_eur.central, 0)
      const e = ecart(ir, ref.foyer.impot_revenu)
      rapport.push({ cas: cas.id, role: 'foyer', impot_revenu: e, calcule: ir, reference: ref.foyer.impot_revenu })
      expect(Math.abs(e), `${cas.id} IR : ${ir} contre ${ref.foyer.impot_revenu}`).toBeLessThan(TOL)
    })
  }
  it('écrit le rapport des écarts', () => {
    writeFileSync(new URL('../ecarts_cas_types.json', import.meta.url), JSON.stringify(rapport, null, 1))
  })
})

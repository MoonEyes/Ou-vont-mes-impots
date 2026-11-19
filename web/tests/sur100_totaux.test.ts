// Répartition « sur 100 € » du simulateur (docs/VERIFICATION_TOTAUX.md, contrôle interne C3) : pour chaque cas type,
// la répartition par administration (Sécurité sociale, État, collectivités, sans destinataire publié) conserve le total
// payé (aucune ligne comptée deux fois ni oubliée, ventilations de somme 1) et les euros entiers affichés totalisent 100.
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import type { Affectation } from '../src/calcul/agregats'
import { SCENARIOS_OPENFISCA } from '../src/calcul/moteur'
import { calculerProfil } from '../src/calcul/moteur-etendu'
import { ORDRE_ADMIN, parAdministration, sur100Entiers } from '../src/calcul/repartition'
import type { ProfilEtendu } from '../src/calcul/types'

const lire = (chemin: string) => JSON.parse(readFileSync(new URL(chemin, import.meta.url), 'utf8'))
const affectation = lire('../../site/data/prelevements/affectation.json') as Affectation
const CAS = lire('../../tests/cas_types/cas_types_profils.json').cas as { id: string; profil: ProfilEtendu }[]

describe('sur 100 € du simulateur : conservation et total de 100', () => {
  it('sur100Entiers totalise 100 et reste à moins d’un euro de la part exacte', () => {
    const jeux: Record<string, number>[] = [{ a: 1, b: 1, c: 1 }, { a: 0.333, b: 0.333, c: 0.334 }, { a: 99.5, b: 0.25, c: 0.25 }, { a: 7, b: 0, c: 3 }, { x: 1 }]
    for (const v of jeux) {
      const s = sur100Entiers(v)
      const total = Object.values(v).reduce((p, q) => p + q, 0)
      expect(Object.values(s).reduce((p, q) => p + q, 0)).toBe(100)
      for (const [k, x] of Object.entries(v)) expect(Math.abs(s[k] - (x / total) * 100)).toBeLessThan(1)
    }
    expect(sur100Entiers({})).toEqual({})
  })

  for (const c of CAS) {
    it(`cas ${c.id} : somme des administrations = total payé, sur 100 € = 100`, () => {
      const r = calculerProfil(c.profil, { scenarios: SCENARIOS_OPENFISCA, affectation })
      if (r.statut !== 'ok') return
      const lignes = r.prelevements.filter((l) => l.inclus_dans_total_paye)
      for (const l of lignes) {
        // parts publiées à 6 décimales : la somme peut s'écarter de 1 d'un millionième au plus
        if (l.ventilation?.length) expect(Math.abs(l.ventilation.reduce((s, v) => s + v.part, 0) - 1), l.id).toBeLessThan(2e-6)
      }
      const parAdmin = parAdministration(lignes)
      for (const a of Object.keys(parAdmin)) expect(ORDRE_ADMIN as readonly string[]).toContain(a)
      const somme = Object.values(parAdmin).reduce((s, v) => s + v, 0)
      const attendu = lignes.filter((l) => !l.non_chiffre).reduce((s, l) => s + l.montant_annuel_eur.central, 0)
      expect(Math.abs(somme - attendu)).toBeLessThan(0.01 + attendu * 2e-6)
      if (somme > 0) expect(Object.values(sur100Entiers(parAdmin)).reduce((s, v) => s + v, 0)).toBe(100)
    })
  }
})

describe('écran État : chiffres officiels à côté du total (docs/VERIFICATION_TOTAUX.md)', async () => {
  const { noteChiffresOfficiels } = await import('../src/ecrans/etat')
  const deficit = lire('../../site/data/deficit.json') as { etat: { annees: Record<string, { depenses_nettes_bg_md: number; prelevements_sur_recettes_md: number }> } }
  it('cite les deux agrégats publiés du même millésime, sans chiffre calculé', () => {
    for (const [m, a] of Object.entries(deficit.etat.annees)) {
      const t = noteChiffresOfficiels(m, a)
      expect(t).toContain('dépenses nettes du budget général')
      expect(t).toContain(m.startsWith('LFI') ? 'loi de finances initiale' : 'au 31 décembre')
      expect(t).toMatch(/\d{4}, DGFiP/)
    }
    expect(noteChiffresOfficiels('Exécution 2024', undefined)).toBe('')
  })
})

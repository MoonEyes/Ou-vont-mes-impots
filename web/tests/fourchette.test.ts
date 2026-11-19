// @vitest-environment happy-dom
// Fourchette du total « ce que tu verses en un an » (audit design du 19/11/2026, problème 11) : l'estimation de
// référence est toujours dans la fourchette, sa place est écrite (haut, bas ou entre les deux) et la méthode du chiffre
// calculé par le site est affichée à côté du badge (règle 13). Cause de « environ 13 781 € = borne haute » : la
// fourchette encadre deux hypothèses de l'Insee pour les taxes sur les achats ; l'hypothèse de référence est la plus
// haute pour les déciles 1 à 7 (prelevements/tva_conso.json), donc l'estimation est la borne haute, sans erreur de calcul.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { additionner } from '../src/calcul/agregats'
import { METHODE_TOTAL, phrasePosition, positionCentrale } from '../src/calcul/fourchette'
import { assembler, type TvaConso } from '../src/calcul/hors-bulletin'
import { calculer } from '../src/calcul/moteur'
import type { Profil, ResultatOk } from '../src/calcul/types'
import { session } from '../src/etat'
import { blocTotal } from '../src/ecrans/paie'
import { eur, LIBELLE_CALCULE } from '../src/util'

const lire = (p: string) => JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'data', p), 'utf8'))
const tva: TvaConso = lire('prelevements/tva_conso.json')
const affectation = lire('prelevements/affectation.json')
const tf69 = lire('prelevements/taxe_fonciere/69.json')
const net = (x: string | null | undefined) => (x ?? '').replace(/\s+/g, ' ').trim()

const profil = (salaire: number, statut: 'locataire' | 'proprietaire', commune?: string): Profil => ({
  version_contrat: '1.0',
  annee_revenus: 2025,
  residence: { zone: 'metropole', alsace_moselle: false, ...(commune ? { commune_insee: commune } : {}) },
  foyer: { situation: 'celibataire', enfants: [] },
  logement: { statut },
  personnes: [{ role: 'declarant1', statut_activite: 'salarie_prive', cadre: false, temps_travail: { type: 'temps_plein' }, salaire_net_avant_impot_mensuel: salaire }],
})
const complet = (p: Profil) => {
  const r = calculer(p, { affectation }) as ResultatOk
  const c = assembler(p, r, { tva, affectation, tfDep: tf69, ligneCommune: p.residence.commune_insee ? tf69.communes[p.residence.commune_insee] : undefined }, { voiture: 'inconnu', fumeur: 'inconnu' })
  return { r, c }
}

describe('estimation de référence dans la fourchette', () => {
  it('pour tous les déciles, locataire ou propriétaire, avec ou sans commune : bas <= central <= haut', () => {
    for (const salaire of [900, 1400, 1800, 2100, 2600, 3200, 4000, 5500, 8000, 12000])
      for (const statut of ['locataire', 'proprietaire'] as const)
        for (const commune of ['69123', undefined]) {
          const { c } = complet(profil(salaire, statut, commune))
          const t = c.total
          const cas = `${salaire} € ${statut} ${commune ?? 'sans commune'}`
          expect(t.bas, cas).toBeLessThanOrEqual(t.central)
          expect(t.central, cas).toBeLessThanOrEqual(t.haut)
          expect(positionCentrale(t), cas).not.toBe('hors')
          for (const l of c.lignes.filter((x) => !x.non_chiffre)) {
            expect(l.montant_annuel_eur.bas, `${cas} ${l.id}`).toBeLessThanOrEqual(l.montant_annuel_eur.central)
            expect(l.montant_annuel_eur.central, `${cas} ${l.id}`).toBeLessThanOrEqual(l.montant_annuel_eur.haut)
          }
        }
  })

  it('la somme garde l’ordre des bornes, réductions comprises', () => {
    const t = additionner([
      { montant_annuel_eur: { bas: 100, central: 150, haut: 200 } },
      { montant_annuel_eur: { bas: 10, central: 20, haut: 40 }, nature: 'reduction' },
    ] as never)
    expect(t).toEqual({ bas: 60, central: 130, haut: 190 })
  })

  it('cas de l’audit (2 100 € net, seul, sans commune) : l’estimation est la borne haute, et la page le dit', () => {
    const p = profil(2100, 'locataire')
    const { r, c } = complet(p)
    const tr = tva.tranches.find((x) => x.taxes_produits_eur_par_uc.central === x.taxes_produits_eur_par_uc.haut)!
    expect(tr, 'au moins un décile où l’hypothèse de référence est la borne haute').toBeTruthy()
    expect(positionCentrale(c.total)).toBe('haut')
    session.profil = p
    const d = document.createElement('div')
    d.innerHTML = blocTotal(r, c)
    const titre = net(d.querySelector('.recap-titre')?.textContent)
    expect(titre).not.toContain('environ')
    expect(titre).toContain('estimation de référence')
    expect(net(d.querySelector('.grand-chiffre')?.textContent)).toBe(net(eur(c.total.central)))
    expect(net(d.querySelector('.recap-fourchette')?.textContent)).toBe(net(`Fourchette : entre ${eur(c.total.bas)} et ${eur(c.total.haut)}`))
    expect(net(d.textContent)).toContain(net(phrasePosition('haut')))
    // Repère de l'estimation sur la jauge, au bon endroit.
    const repere = d.querySelector<HTMLElement>('.jauge .j-repere')!
    expect(Number(repere.dataset.g)).toBeCloseTo((c.total.central / c.total.haut) * 100, 0)
    // Règle 13 : badge « calculé par le site » et méthode écrite à côté.
    expect(d.querySelector('[data-calcule]')?.textContent).toContain(LIBELLE_CALCULE)
    expect(net(d.querySelector('.methode-calcul')?.textContent)).toBe(net(`Méthode : ${METHODE_TOTAL}`))
    expect(METHODE_TOTAL).toMatch(/2025/)
    expect(METHODE_TOTAL).toMatch(/hypothèse de référence de l’Insee/)
  })

  it('position écrite pour chaque cas', () => {
    expect(positionCentrale({ bas: 10, central: 10, haut: 10 })).toBe('unique')
    expect(positionCentrale({ bas: 10, central: 20, haut: 20 })).toBe('haut')
    expect(positionCentrale({ bas: 10, central: 10, haut: 20 })).toBe('bas')
    expect(positionCentrale({ bas: 10, central: 15, haut: 20 })).toBe('dedans')
    expect(positionCentrale({ bas: 10, central: 25, haut: 20 })).toBe('hors')
    for (const p of ['haut', 'bas', 'dedans'] as const) expect(phrasePosition(p)).not.toBe('')
    expect(phrasePosition('hors')).toBe('')
  })
})

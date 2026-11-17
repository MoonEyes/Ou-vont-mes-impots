// Prélèvements hors bulletin (contrat 1.4) : décile, taxes sur la consommation, impôts locaux, affectation.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { assembler, impotsLocaux, placer, taxesConsommation, unitesConsommation, type TvaConso } from '../src/calcul/hors-bulletin'
import { calculer } from '../src/calcul/moteur'
import type { Profil, ResultatOk } from '../src/calcul/types'

const lire = (p: string) => JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'data', p), 'utf8'))
const tva: TvaConso = lire('prelevements/tva_conso.json')
const affectation = lire('prelevements/affectation.json')
const tf69 = lire('prelevements/taxe_fonciere/69.json')

const profil = (o: Partial<Profil> = {}): Profil => ({
  version_contrat: '1.0',
  annee_revenus: 2025,
  residence: { zone: 'metropole', alsace_moselle: false, commune_insee: '69123' },
  foyer: { situation: 'celibataire', enfants: [] },
  logement: { statut: 'locataire' },
  personnes: [{ role: 'declarant1', statut_activite: 'salarie_prive', cadre: false, temps_travail: { type: 'temps_plein' }, salaire_net_avant_impot_mensuel: 2100 }],
  ...o,
})

describe('hors bulletin', () => {
  const p = profil()
  const r = calculer(p, { affectation }) as ResultatOk

  it('unités de consommation (OCDE modifiée, garde alternée pour moitié)', () => {
    expect(unitesConsommation(p)).toBe(1)
    const couple = profil({
      foyer: { situation: 'couple_marie_pacse', enfants: [{ annee_naissance: 2015 }, { annee_naissance: 2008 }, { annee_naissance: 2018, garde_alternee: true }] },
    })
    expect(unitesConsommation(couple)).toBeCloseTo(1 + 0.5 + 0.3 + 0.5 + 0.15, 5)
  })

  it('cas 2 100 € net seul : 5e décile, taxes conso centrales = tva_conso.json × 1 UC', () => {
    const pl = placer(p, r, tva)
    expect(pl.revenu_disponible_eur).toBe(25200 - 1004)
    expect(pl.decile).toBe(5)
    const lignes = taxesConsommation(pl, tva, { voiture: 'inconnu', fumeur: 'inconnu' })
    const tr = tva.tranches.find((t) => t.decile === 5)!
    const central = lignes.reduce((s, l) => s + l.montant_annuel_eur.central, 0)
    expect(central).toBeCloseTo(tr.taxes_produits_eur_par_uc.central, 0)
    expect(lignes.find((l) => l.id === 'tva')!.montant_annuel_eur.central).toBeCloseTo(tr.detail_eur_par_uc.tva.central, 2)
    for (const l of lignes) expect(l.montant_annuel_eur.bas).toBeLessThanOrEqual(l.montant_annuel_eur.haut)
  })

  it('ajustements : sans voiture, non-fumeur ; fumeur = non chiffré, exclu du total', () => {
    const pl = placer(p, r, tva)
    const sans = taxesConsommation(pl, tva, { voiture: 'non', fumeur: 'non' })
    expect(sans.find((l) => l.id === 'ticpe')!.montant_annuel_eur.central).toBe(0)
    expect(sans.find((l) => l.id === 'tabac')!.montant_annuel_eur.central).toBe(0)
    const fumeur = taxesConsommation(pl, tva, { voiture: 'oui', fumeur: 'oui' })
    const tabac = fumeur.find((l) => l.id === 'tabac')!
    expect(tabac.non_chiffre).toBe(true)
    expect(fumeur.find((l) => l.id === 'ticpe')!.montant_annuel_eur.central).toBeCloseTo(tva.tranches[4].ajustements.voiture!.ticpe_si_voiture_eur_par_uc, 2)
    const c = assembler(p, r, { tva, affectation, tfDep: tf69, ligneCommune: tf69.communes['69123'] }, { voiture: 'oui', fumeur: 'oui' })
    expect(c.lignes.some((l) => l.non_chiffre)).toBe(true)
    const somme = c.lignes.filter((l) => !l.non_chiffre).reduce((s, l) => s + l.montant_annuel_eur.central, 0)
    expect(c.total.central).toBeCloseTo(somme, 1)
  })

  it('locataire à Lyon : TEOM via les charges, pas de taxe foncière ; propriétaire : fourchette et parts de la commune', () => {
    const loc = impotsLocaux(p, tf69.communes['69123'], tf69)
    expect(loc.map((l) => l.id)).toEqual(['teom'])
    expect(loc[0].montant_annuel_eur.central).toBe(tf69.communes['69123'][4])
    const pro = impotsLocaux(profil({ logement: { statut: 'proprietaire' } }), tf69.communes['69123'], tf69)
    const tf = pro.find((l) => l.id === 'taxe_fonciere')!
    expect(tf.montant_annuel_eur).toEqual({ bas: 720.52, central: 729.32, haut: 1614.62 })
    expect(tf.ventilation!.reduce((s, v) => s + v.part, 0)).toBeCloseTo(1, 3)
    const avis = impotsLocaux(profil({ logement: { statut: 'proprietaire', taxe_fonciere_annuelle_eur: 1500 } }), tf69.communes['69123'], tf69)
    expect(avis).toHaveLength(1)
    expect(avis[0].montant_annuel_eur.central).toBe(1500)
  })

  it('affectation : la CSG est ventilée (Assurance maladie 4,25 pts sur 9,2), plus de « plusieurs branches » non ventilé', () => {
    const csg = r.prelevements.find((l) => l.id === 'csg_deductible')!
    expect(csg.ventilation!.find((v) => v.destinataire === 'cnam')!.part).toBeCloseTo(4.25 / 9.2, 3)
    expect(csg.ventilation!.map((v) => v.destinataire).sort()).toEqual(['cades', 'cnaf', 'cnam', 'cnsa', 'unedic'])
    expect(r.avertissements.some((a) => a.code === 'DONNEE_ABSENTE')).toBe(false)
    const tvaLigne = assembler(p, r, { tva, affectation, tfDep: tf69, ligneCommune: tf69.communes['69123'] }, { voiture: 'inconnu', fumeur: 'inconnu' }).conso.find((l) => l.id === 'tva')!
    expect(tvaLigne.ventilation!.some((v) => v.destinataire === 'collectivites_territoriales')).toBe(true)
  })

  it('total = prélevé sur salaire + taxes conso + impôts locaux', () => {
    const c = assembler(p, r, { tva, affectation, tfDep: tf69, ligneCommune: tf69.communes['69123'] }, { voiture: 'inconnu', fumeur: 'inconnu' })
    const salaire = r.totaux.paye_par_le_foyer.central
    const conso = c.conso.reduce((s, l) => s + l.montant_annuel_eur.central, 0)
    const locaux = c.locaux.reduce((s, l) => s + l.montant_annuel_eur.central, 0)
    expect(c.total.central).toBeCloseTo(salaire + conso + locaux, 1)
    expect(c.total.bas).toBeLessThanOrEqual(c.total.central)
    expect(c.total.haut).toBeGreaterThanOrEqual(c.total.central)
  })
})

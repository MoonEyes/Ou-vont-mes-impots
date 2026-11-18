// Affectation des prélèvements des profils étendus (site/data/prelevements/affectation.json, commit 32e891c) :
// correspondance_calcul et correspondance_calcul_selon_taux (CSG sur les pensions par taux), nouveaux destinataires,
// lignes « sans destinataire publié » qui baissent d'autant, salarié du privé inchangé à l'euro près.
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { appliquerAffectation, cleAffectation, parDestinataire, tauxCsgPensionDesLignes, type Affectation } from '../src/calcul/agregats'
import { DESTINATAIRES, destinataire } from '../src/calcul/destinataires'
import { calculer, SCENARIOS_OPENFISCA } from '../src/calcul/moteur'
import { CLES_AFFECTATION_A_CREER, CLES_AFFECTATION_A_CREER_SELON_TAUX, calculerProfil } from '../src/calcul/moteur-etendu'
import { parAdministration } from '../src/calcul/repartition'
import { lignesSansDestinataire } from '../src/calcul/profils-ui'
import type { Prelevement, Profil, ProfilEtendu, ResultatOk, ResultatOkEtendu } from '../src/calcul/types'

const lire = (chemin: string) => JSON.parse(readFileSync(new URL(chemin, import.meta.url), 'utf8'))
const affectation = lire('../../site/data/prelevements/affectation.json') as Affectation
const CAS = lire('../../tests/cas_types/cas_types_profils.json').cas as { id: string; groupe: string; profil: ProfilEtendu }[]
const exempleLyon = JSON.parse(readFileSync(new URL('../src/exemple-lyon.json', import.meta.url), 'utf8'))

const NOUVELLES_CLES = [
  'csg_remplacement_taux_normal', 'csg_remplacement_taux_median', 'csg_remplacement_taux_reduit', 'casa', 'pension_civile_etat',
  'allocation_temporaire_invalidite', 'cnracl', 'ircantec', 'rafp', 'regime_local_alsace_moselle', 'independants_retraite_base',
  'independants_retraite_complementaire', 'independants_maladie_maternite', 'independants_invalidite_deces',
  'independants_formation_professionnelle', 'taxe_frais_chambre_consulaire',
]
const NON_PUBLIEES = ['independants_maladie_maternite', 'independants_invalidite_deces', 'independants_formation_professionnelle', 'taxe_frais_chambre_consulaire']
const NOUVEAUX_DESTINATAIRES = ['fsv', 'cas_pensions', 'cnracl', 'ircantec', 'erafp', 'rci_independants', 'regime_local_am']

/** affectation.json tel qu'avant le commit 32e891c : sans les 16 clés ni leurs correspondances. */
function sansNouvellesCles(a: Affectation): Affectation {
  const prelevements = Object.fromEntries(Object.entries(a.prelevements).filter(([k]) => !NOUVELLES_CLES.includes(k)))
  const correspondance_calcul = Object.fromEntries(Object.entries(a.correspondance_calcul ?? {}).filter(([, v]) => !NOUVELLES_CLES.includes(v)))
  const { correspondance_calcul_selon_taux: _, ...reste } = a
  return { ...reste, prelevements, correspondance_calcul }
}
const avant = sansNouvellesCles(affectation)

const ok = (profil: ProfilEtendu, a: Affectation | null = affectation): ResultatOkEtendu => {
  const r = calculerProfil(profil, { scenarios: SCENARIOS_OPENFISCA, affectation: a })
  if (r.statut !== 'ok') throw new Error(JSON.stringify(r.erreur))
  return r
}
const cas = (id: string) => CAS.find((c) => c.id === id)!.profil
const sansDestinataire = (r: ResultatOkEtendu) => r.prelevements.filter((l) => l.destinataire.id === 'non_affecte' && !l.non_chiffre)
const montantSans = (r: ResultatOkEtendu) => sansDestinataire(r).reduce((s, l) => s + l.montant_annuel_eur.central, 0)
const base = (l: Prelevement) => l.id.replace(/_declarant2$/, '')

describe('données lues : affectation.json du commit 32e891c', () => {
  it('16 clés, 12 réparties (parts sommant à 1), 4 sans répartition publiée', () => {
    for (const k of NOUVELLES_CLES) expect(affectation.prelevements[k], k).toBeDefined()
    for (const k of NOUVELLES_CLES.filter((x) => !NON_PUBLIEES.includes(x))) {
      const a = affectation.prelevements[k]
      expect(a.statut, k).toBe('sourcee')
      expect(a.ventilation.reduce((s, v) => s + v.part, 0), k).toBeCloseTo(1, 3)
    }
    for (const k of NON_PUBLIEES) {
      expect(affectation.prelevements[k].statut, k).toBe('non sourcee')
      expect(affectation.prelevements[k].ventilation, k).toEqual([])
    }
    expect(affectation.correspondance_calcul_selon_taux).toEqual(CLES_AFFECTATION_A_CREER_SELON_TAUX)
  })

  it('nouveaux destinataires : libellés en clair, famille de couleur existante, jamais l’identifiant', () => {
    for (const id of NOUVEAUX_DESTINATAIRES) {
      const d = destinataire(id)
      expect(d.nom, id).not.toBe(id)
      expect(d.nom, id).not.toMatch(/^[A-Z]{2,}$/)
      expect(d.nom, id).not.toContain('—')
      expect(['Securite sociale', 'Etat'], id).toContain(d.administration)
      expect(d.administration, id).toBe(affectation.destinataires![id].administration)
      expect((DESTINATAIRES as Record<string, unknown>)[id], id).toBeDefined()
    }
  })
})

describe('CSG sur les pensions : clé selon le taux de la personne', () => {
  const attendus = { R02: 'reduit', R03: 'median', R04: 'normal' } as const
  for (const [id, taux] of Object.entries(attendus)) {
    it(`${id} : taux ${taux}, répartition csg_remplacement_taux_${taux}`, () => {
      const r = ok(cas(id))
      const csg = r.prelevements.filter((l) => base(l).startsWith('csg_pension_'))
      expect(csg.length).toBe(taux === 'reduit' ? 1 : 2)
      expect(tauxCsgPensionDesLignes(r.prelevements, 'declarant1')).toBe(taux)
      const cle = `csg_remplacement_taux_${taux}`
      for (const l of csg) {
        expect(cleAffectation(l, r.prelevements, affectation)).toBe(cle)
        expect(l.ventilation?.map((v) => [v.destinataire, v.part])).toEqual(affectation.prelevements[cle].ventilation.map((v) => [v.destinataire, v.part]))
        expect(l.statut_affectation).toBe('sourcee')
        // Répartie entre branches de la sécurité sociale : plus « sans destinataire publié ».
        expect(l.destinataire.id).toBe('plusieurs')
      }
      expect(r.affectations_manquantes.map((m) => m.id)).not.toContain('csg_pension_deductible')
    })
  }

  it('couple de retraités (R05) : chaque personne garde son propre taux', () => {
    const r = ok(cas('R05'))
    for (const p of ['declarant1', 'declarant2'] as const) expect(tauxCsgPensionDesLignes(r.prelevements, p)).toBe('median')
    const csg = r.prelevements.filter((l) => base(l).startsWith('csg_pension_'))
    expect(csg.length).toBe(4)
    for (const l of csg) expect(l.ventilation?.find((v) => v.destinataire === 'fsv')?.part).toBe(0.445455)
  })

  it('taux différents dans un foyer : la répartition suit la personne, pas le foyer', () => {
    const p = cas('R05')
    const profil: ProfilEtendu = {
      ...p,
      personnes: [
        { ...p.personnes[0], csg_pension: { taux: 'normal' } },
        { ...p.personnes[1], csg_pension: { taux: 'reduit' } },
      ],
    }
    const r = ok(profil)
    const fsv = (role: string) => r.prelevements.find((l) => l.id === (role === 'declarant1' ? 'csg_pension_deductible' : 'csg_pension_deductible_declarant2'))!.ventilation!
    expect(fsv('declarant1').map((v) => v.destinataire)).toContain('fsv')
    expect(fsv('declarant2').map((v) => v.destinataire)).not.toContain('fsv')
  })

  it('exonéré (R01) : aucune ligne de CSG, rien à répartir', () => {
    const r = ok(cas('R01'))
    expect(r.prelevements.filter((l) => base(l).startsWith('csg_pension_'))).toEqual([])
    expect(tauxCsgPensionDesLignes(r.prelevements, 'declarant1')).toBeNull()
  })

  it('sans affectation : la clé proposée dépend du taux', () => {
    const r = ok(cas('R03'), null)
    const m = r.affectations_manquantes.find((x) => x.id === 'csg_pension_deductible')
    expect(m?.cle_proposee).toBe('csg_remplacement_taux_median')
    expect(CLES_AFFECTATION_A_CREER).not.toHaveProperty('csg_pension_deductible')
    expect(Object.values(CLES_AFFECTATION_A_CREER)).not.toContain('csg_remplacement')
  })
})

describe('lignes « sans destinataire publié » : baissent d’autant, les non publiées restent signalées', () => {
  // Profil : cas types, avec les lignes qui doivent quitter « sans destinataire publié ».
  const attendus: Record<string, string[]> = {
    F01: ['retenue_pension_civile', 'contribution_cas_pensions', 'ati', 'rafp_salarie', 'rafp_employeur'],
    F03: ['retenue_cnracl', 'contribution_cnracl', 'rafp_salarie', 'rafp_employeur'],
    P01: ['ircantec_salarie', 'ircantec_employeur'],
    R04: ['csg_pension_deductible', 'csg_pension_non_deductible', 'casa'],
    M01: ['micro_retraite_base', 'micro_retraite_complementaire'],
    A02: ['maladie_regime_local'],
  }
  for (const [id, lignes] of Object.entries(attendus)) {
    it(`${id} (${CAS.find((c) => c.id === id)!.groupe}) : ${lignes.join(', ')}`, () => {
      const r0 = ok(cas(id), avant)
      const r1 = ok(cas(id))
      const ids0 = new Set(sansDestinataire(r0).map(base))
      const ids1 = new Set(sansDestinataire(r1).map(base))
      for (const l of lignes) {
        expect(ids0.has(l), `${l} sans destinataire avant`).toBe(true)
        expect(ids1.has(l), `${l} affecté après`).toBe(false)
      }
      // Baisse exacte : le montant des lignes devenues affectées.
      const affectees = r1.prelevements.filter((l) => lignes.includes(base(l)))
      const baisse = affectees.reduce((s, l) => s + l.montant_annuel_eur.central, 0)
      expect(baisse).toBeGreaterThan(0)
      expect(montantSans(r0) - montantSans(r1)).toBeCloseTo(baisse, 2)
      const adm0 = parAdministration(r0.prelevements)
      const adm1 = parAdministration(r1.prelevements)
      expect((adm0.Plusieurs ?? 0) - (adm1.Plusieurs ?? 0)).toBeCloseTo(baisse, 2)
      // Les montants ne changent pas, seule l'affectation change.
      expect(r1.totaux.paye_par_le_foyer).toEqual(r0.totaux.paye_par_le_foyer)
      expect(r1.totaux.patronal).toEqual(r0.totaux.patronal)
      for (const l of affectees) {
        expect(l.statut_affectation, l.id).toBe('sourcee')
        expect(l.ventilation?.length, l.id).toBeGreaterThan(0)
      }
      // Ce qui reste sans source reste signalé, sans répartition supposée.
      for (const l of sansDestinataire(r1)) {
        expect(l.ventilation, l.id).toBeUndefined()
        expect(l.statut_affectation, l.id).toBe('non sourcee')
        expect(r1.affectations_manquantes.map((m) => m.id)).toContain(base(l))
      }
    })
  }

  it('destinataires des lignes affectées : caisses publiées dans affectation.json', () => {
    const dest = (id: string, ligne: string) => ok(cas(id)).prelevements.find((l) => base(l) === ligne)!.destinataire.id
    expect(dest('F01', 'retenue_pension_civile')).toBe('cas_pensions')
    expect(dest('F01', 'ati')).toBe('cas_pensions')
    expect(dest('F01', 'rafp_salarie')).toBe('erafp')
    expect(dest('F03', 'retenue_cnracl')).toBe('cnracl')
    expect(dest('P01', 'ircantec_salarie')).toBe('ircantec')
    expect(dest('R04', 'casa')).toBe('cnsa')
    expect(dest('M01', 'micro_retraite_base')).toBe('cnav')
    expect(dest('M01', 'micro_retraite_complementaire')).toBe('rci_independants')
    expect(dest('A02', 'maladie_regime_local')).toBe('regime_local_am')
    const pd = parDestinataire(ok(cas('F01')).prelevements, true).map((x) => x.destinataire)
    expect(pd).toContain('cas_pensions')
    expect(pd).toContain('erafp')
  })

  it('micro-entrepreneur : maladie-maternité, invalidité-décès, formation, chambre consulaire restent « non publié »', () => {
    const r = ok(cas('M06'))
    const sans = new Set(sansDestinataire(r).map(base))
    for (const l of ['micro_maladie_maternite', 'micro_invalidite_deces', 'micro_formation_professionnelle', 'micro_taxe_chambre_consulaire']) {
      expect(sans.has(l), l).toBe(true)
      const m = r.affectations_manquantes.find((x) => x.id === l)
      expect(m, l).toBeDefined()
      // La clé existe désormais, mais sans répartition publiée.
      expect(affectation.prelevements[m!.cle_proposee].statut, l).toBe('non sourcee')
    }
    expect(lignesSansDestinataire(r.prelevements).verse.length).toBeGreaterThan(0)
  })
})

describe('salarié du privé (exemple de Lyon, 2 100 €) : identique à l’euro près', () => {
  const profil: Profil = {
    version_contrat: '1.0',
    annee_revenus: 2025,
    residence: { zone: 'metropole', alsace_moselle: false, commune_insee: '69123' },
    foyer: { situation: 'celibataire', enfants: [] },
    logement: { statut: 'locataire' },
    personnes: [{ role: 'declarant1', statut_activite: 'salarie_prive', cadre: false, temps_travail: { type: 'temps_plein' }, salaire_net_avant_impot_mensuel: exempleLyon.profil.net_mensuel }],
  }
  const euros = (r: ResultatOk) => ({
    lignes: r.prelevements.map((l) => [l.id, l.destinataire.id, Math.round(l.montant_annuel_eur.central), l.ventilation?.map((v) => [v.destinataire, v.part])]),
    total: r.totaux.paye_par_le_foyer,
    patronal: r.totaux.patronal,
    administrations: Object.fromEntries(Object.entries(parAdministration(r.prelevements)).map(([k, v]) => [k, Math.round(v)])),
    destinataires: r.totaux.par_destinataire.map((d) => [d.destinataire, Math.round(d.montant_annuel_eur.central)]),
  })

  it('contrat 1.0 et moteur étendu : mêmes lignes, mêmes destinataires, même total qu’avant les 16 clés', () => {
    for (const calc of [(a: Affectation) => calculer(profil, { affectation: a }), (a: Affectation) => calculerProfil(profil as ProfilEtendu, { affectation: a })]) {
      const r0 = calc(avant) as ResultatOk
      const r1 = calc(affectation) as ResultatOk
      expect(r1.statut).toBe('ok')
      expect(euros(r1)).toEqual(euros(r0))
      expect(Math.round(r1.totaux.paye_par_le_foyer.central)).toBe(exempleLyon.sources.salaire.central)
    }
  })

  it('appliquerAffectation sur les lignes du salarié : rien ne dépend du taux de CSG des pensions', () => {
    const r = calculer(profil, { affectation }) as ResultatOk
    expect(tauxCsgPensionDesLignes(r.prelevements, 'declarant1')).toBeNull()
    expect(appliquerAffectation(r.prelevements, affectation)).toEqual(appliquerAffectation(r.prelevements, avant))
  })
})

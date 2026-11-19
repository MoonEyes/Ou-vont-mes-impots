// Adresses publiques en vrais chemins : conversion dans les deux sens avec la notation interne « #/… ».
import { describe, expect, it } from 'vitest'
import { aUnePage, fragmentCommune, fragmentDepartement, prefixeRacine, slug, versChemin, versFragment } from '../src/chemins'
import { TOUS_DEPARTEMENTS } from '../src/departements'
import { ROUTES } from '../src/routes'
import { cheminCanonique, lireFragment, titreDocument } from '../src/routeur'

describe('chemins', () => {
  it('chaque route a un chemin propre et se relit à l’identique', () => {
    const chemins = ROUTES.map((r) => versChemin('#' + r.chemin))
    expect(new Set(chemins).size).toBe(ROUTES.length)
    expect(versChemin('#/')).toBe('')
    expect(versChemin('#/explorer/etat')).toBe('explorer/etat/')
    for (const r of ROUTES) expect(lireFragment(versFragment(versChemin('#' + r.chemin))).chemin, r.chemin).toBe(r.chemin)
  })

  it('paramètres conservés dans la requête', () => {
    expect(versChemin('#/explorer/etat?m=lfi2025')).toBe('explorer/etat/?m=lfi2025')
    expect(versFragment('explorer/etat/', '?m=lfi2025')).toBe('#/explorer/etat?m=lfi2025')
    expect(versFragment('explorer/etat/index.html')).toBe('#/explorer/etat')
    expect(versFragment('')).toBe('#/')
    expect(cheminCanonique('#/explorer/etat?m=lfi2025')).toBe('explorer/etat/')
  })

  it('communes et départements : /local/<code>-<nom>/', () => {
    expect(slug('Saint-Étienne-du-Rouvray')).toBe('saint-etienne-du-rouvray')
    expect(slug('L’Haÿ-les-Roses')).toBe('l-hay-les-roses')
    expect(slug('Œuilly')).toBe('oeuilly')
    expect(aUnePage(5000)).toBe(false)
    expect(aUnePage(5001)).toBe(true)
    expect(versChemin(fragmentCommune('44109', 'Nantes', 327734))).toBe('local/44109-nantes/')
    expect(versChemin(fragmentCommune('2A004', 'Ajaccio', 73822))).toBe('local/2A004-ajaccio/')
    // Sous le seuil : pas de page propre, la page commune générique reçoit le code.
    expect(versChemin(fragmentCommune('44001', 'Abbaretz', 2073))).toBe('local/commune/?insee=44001')
    expect(versChemin(fragmentDepartement('44', 'Loire-Atlantique'))).toBe('local/44-loire-atlantique/')
    expect(versChemin(fragmentDepartement('971', 'Guadeloupe'))).toBe('local/971-guadeloupe/')
    const c = lireFragment(versFragment('local/44109-nantes/'))
    expect([c.chemin, c.params.get('insee')]).toEqual(['/local/commune', '44109'])
    const d = lireFragment(versFragment('local/2B-haute-corse/'))
    expect([d.chemin, d.params.get('dep')]).toEqual(['/local/departement', '2B'])
    const o = lireFragment(versFragment('local/97101-les-abymes/'))
    expect([o.chemin, o.params.get('insee')]).toEqual(['/local/commune', '97101'])
    for (const [code, nom] of TOUS_DEPARTEMENTS) expect(versFragment(versChemin(fragmentDepartement(code, nom)))).toBe(fragmentDepartement(code, nom))
    expect(TOUS_DEPARTEMENTS).toHaveLength(101)
    expect(cheminCanonique(fragmentCommune('44109', 'Nantes', 327734))).toBe('local/44109-nantes/')
    expect(cheminCanonique('#/local/commune?insee=44001')).toBe('local/commune/')
  })

  it('préfixe relatif vers la racine du site', () => {
    expect(prefixeRacine('')).toBe('./')
    expect(prefixeRacine('calcul/')).toBe('../')
    expect(prefixeRacine('explorer/etat/detail/')).toBe('../../../')
    expect(prefixeRacine('local/44109-nantes/?x=1')).toBe('../../')
  })

  it('titre et description : uniques, renseignés pour chaque route', () => {
    const titres = ROUTES.map((r) => titreDocument(r))
    expect(new Set(titres).size).toBe(ROUTES.length)
    const descriptions = ROUTES.map((r) => r.description)
    expect(new Set(descriptions).size).toBe(ROUTES.length)
    for (const r of ROUTES) {
      expect(r.description.length, r.chemin).toBeGreaterThanOrEqual(70)
      expect(r.description.length, r.chemin).toBeLessThanOrEqual(200)
      expect(titreDocument(r).length, r.chemin).toBeLessThanOrEqual(100)
    }
    expect(titreDocument(ROUTES.find((r) => r.chemin === '/calcul')!)).toBe('Combien je verse d’impôts : calcul à partir du salaire')
  })
})

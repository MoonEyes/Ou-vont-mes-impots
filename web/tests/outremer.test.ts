// @vitest-environment happy-dom
// Écran « L'État dans les collectivités d'outre-mer » (/explorer/outre-mer) sur des extraits réels de site/data/outremer.
import { beforeAll, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { viderCache } from '../src/donnees'
import { COLONNES_CP, REGLE_MISSIONS, REGLE_TERRITOIRES, missionsCumulees, parHabitant, trierMissions, valeurColonne, type IndexOutremer, type TerritoireOutremer } from '../src/ecrans/outremer'
import { eurLisible, eur, sur100 } from '../src/util'
import { monterPage } from './aide-dom'

const FIX = join(process.cwd(), 'tests', 'fixtures')
const lire = <T>(f: string): T => JSON.parse(readFileSync(join(FIX, f), 'utf8')) as T
const idx = lire<IndexOutremer>('data/outremer/index.json')
const terrs = idx.territoires.map((t) => lire<TerritoireOutremer>(`data/${t.fichier}`))
const esp = (x: string) => x.replace(/\s+/g, ' ')

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => esp(main.textContent ?? '')
const LEXIQUE = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[] }[] }

// Le fichier des dépenses fiscales par programme est servi depuis les fixtures propres à cet écran.
function servirNiches(present: boolean) {
  const vrai = globalThis.fetch
  globalThis.fetch = (async (u: string) => {
    if (String(u).endsWith('niches/programmes.json'))
      return present ? new Response(readFileSync(join(FIX, 'outremer', 'niches_programmes.json'), 'utf8'), { status: 200 }) : new Response('', { status: 404 })
    return vrai(u)
  }) as typeof fetch
  return () => {
    globalThis.fetch = vrai
  }
}

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('outre-mer', () => {
  it('route déclarée sous Explorer, avec voisins existants', () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/outre-mer')!
    expect(r.parent).toBe('/explorer')
    for (const v of r.voisins ?? []) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
  })

  it('chiffre clé : somme des six territoires (dépensé en 2024), sur 100 € dépensés par l’État', async () => {
    viderCache()
    const remettre = servirNiches(true)
    await ecran('#/explorer/outre-mer')
    remettre()
    expect(main.querySelector('h1')?.textContent).toBe('L’État dans les collectivités d’outre-mer')
    const total = terrs.reduce((s, t) => s + valeurColonne(t.credits_etat.dpt_plf2026.colonnes, t.credits_etat.dpt_plf2026.total_general, 'execution_2024_cp')!, 0)
    const cle = main.querySelector('[data-cle]')!
    expect(esp(cle.querySelector('.surligne')!.textContent!)).toBe(esp(eurLisible(total)))
    const budget = lire<{ md: number }>('data/arbre/racine.json').md * 1e9
    expect(esp(cle.textContent!)).toContain(`${esp(sur100((total / budget) * 100))} sur 100 €`)
    expect(main.querySelectorAll('.surligne')).toHaveLength(1)
  })

  it('tableau par territoire : ordre des codes, trois colonnes de nature distincte, montant par habitant calculé', async () => {
    const table = Array.from(main.querySelectorAll('table')).find((t) => t.caption?.textContent?.startsWith('Crédits de paiement de l’État par territoire'))!
    expect(table.querySelectorAll('th[scope=col]').length).toBe(6)
    const lignes = Array.from(table.querySelectorAll('tbody tr'))
    expect(lignes.map((l) => l.querySelector('th')!.textContent)).toEqual([...terrs].sort((a, b) => a.territoire.code.localeCompare(b.territoire.code)).map((t) => t.territoire.nom))
    expect(main.querySelector('[data-regle-ordre]')?.textContent).toBe(REGLE_TERRITOIRES)
    const t987 = terrs.find((t) => t.territoire.code === '987')!
    const ligne = lignes.find((l) => l.querySelector('th')!.textContent === t987.territoire.nom)!
    const d = t987.credits_etat.dpt_plf2026
    const cellules = Array.from(ligne.querySelectorAll('td')).map((c) => esp(c.textContent!))
    COLONNES_CP.forEach((c, i) => expect(cellules[i + 1]).toBe(esp(eurLisible(valeurColonne(d.colonnes, d.total_general, c.cle)!))))
    expect(cellules[4]).toBe(esp(eur(valeurColonne(d.colonnes, d.total_general, 'execution_2024_cp')! / t987.territoire.population!)))
    expect(ligne.querySelector('a')?.getAttribute('href')).toBe('#/explorer/outre-mer?t=987')
  })

  it('Cour des comptes 2018 à 2020 et dépenses fiscales : séries séparées, statut et source', async () => {
    expect(texte()).toContain('les deux séries ne se raccordent pas et ne s’additionnent pas')
    const t975 = terrs.find((t) => t.territoire.code === '975')!
    const cour = Array.from(main.querySelectorAll('table')).find((t) => t.caption?.textContent?.includes('Cour des comptes'))!
    const l = Array.from(cour.querySelectorAll('tbody tr')).find((tr) => tr.querySelector('th')!.textContent === t975.territoire.nom)!
    const c = Array.from(l.querySelectorAll('td')).map((x) => esp(x.textContent!))
    expect(c[0]).toBe(esp(eurLisible(t975.credits_etat.cour_des_comptes_2018_2020.annees!['2018'].execution_cp_eur!)))
    expect(c[3]).toBe(esp(eur(t975.credits_etat.cour_des_comptes_2018_2020.cp_executes_par_habitant_eur!['2018']!)))
    const fisc = Array.from(main.querySelectorAll('table')).find((t) => t.caption?.textContent?.startsWith('Dépenses fiscales rattachées'))!
    expect(fisc.querySelectorAll('tbody tr').length).toBe(2)
    expect(texte()).toContain('souvent appelée niche fiscale')
    expect(texte()).toContain('Approché')
    expect(main.querySelector('a[href="#/explorer/niches"]')).not.toBeNull()
    for (const s of ['Cour des comptes', 'document de politique transversale « Outre-mer »', 'Licence Ouverte 2.0', 'ODbL']) expect(texte()).toContain(s)
  })

  it('les six ensemble : missions additionnées colonne par colonne, ordre explicite', async () => {
    const { colonnes, missions } = missionsCumulees(terrs)
    const triees = trierMissions(missions, colonnes).filter((m) => (valeurColonne(colonnes, m.valeurs, 'execution_2024_cp') ?? 0) > 0)
    const noms = Array.from(main.querySelectorAll('ul.barres .barre-tete .nom')).map((x) => x.textContent)
    expect(noms).toEqual(triees.map((m) => m.mission))
    const ens = triees.find((m) => m.mission === 'Enseignement scolaire')!
    const attendu = terrs.reduce((s, t) => s + valeurColonne(colonnes, t.credits_etat.dpt_plf2026.missions!.find((m) => m.mission === 'Enseignement scolaire')!.valeurs, 'execution_2024_cp')!, 0)
    expect(valeurColonne(colonnes, ens.valeurs, 'execution_2024_cp')).toBe(attendu)
    expect(Array.from(main.querySelectorAll('[data-regle-ordre]')).map((x) => x.textContent)).toContain(REGLE_MISSIONS)
    expect(main.querySelector('.bascule [aria-current="true"]')?.textContent).toBe('Les six ensemble')
  })

  it('un territoire choisi : ses missions, ses blocs publiés ou non, le recoupement de la dotation globale', async () => {
    viderCache()
    const remettre = servirNiches(true)
    await ecran('#/explorer/outre-mer?t=988')
    remettre()
    const t = terrs.find((x) => x.territoire.code === '988')!
    expect(main.querySelector('.bascule [aria-current="true"]')?.textContent).toBe(t.territoire.nom)
    expect(main.querySelector('#missions')?.textContent).toContain(t.territoire.nom)
    const d = t.credits_etat.dpt_plf2026
    const premiere = trierMissions(d.missions!, d.colonnes!)[0]
    expect(main.querySelector('ul.barres .barre-tete .nom')?.textContent).toBe(premiere.mission)
    expect(texte()).toContain(`Ce qui est publié pour ${t.territoire.nom}`)
    expect(texte()).toContain('Non publié')
    const rec = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.startsWith('Dotation globale de fonctionnement'))!
    expect(rec.querySelectorAll('tbody tr').length).toBe(idx.ecarts.filter((e) => e.territoire === '988').length)
    // Code inconnu : retour à la vue des six ensemble.
    await ecran('#/explorer/outre-mer?t=999')
    expect(main.querySelector('.bascule [aria-current="true"]')?.textContent).toBe('Les six ensemble')
  })

  it('aucune valeur absente affichée comme 0, calculs par habitant prudents', () => {
    expect(valeurColonne(['a', 'b'], [1, null], 'b')).toBeNull()
    expect(valeurColonne(['a'], [1], 'z')).toBeNull()
    expect(parHabitant(null, 100)).toBeNull()
    expect(parHabitant(100, null)).toBeNull()
    expect(parHabitant(100, 0)).toBeNull()
    expect(parHabitant(1000, 10)).toBe(100)
    const { valeurs } = missionsCumulees([
      { territoire: { code: '1', nom: 'A', population: 1 }, blocs: {}, credits_etat: { cour_des_comptes_2018_2020: { statut: 'x' }, dpt_plf2026: { statut: 'publié', colonnes: ['c'], total_general: [1], missions: [{ mission: 'M', valeurs: [null], programmes: [] }] } } },
      { territoire: { code: '2', nom: 'B', population: 1 }, blocs: {}, credits_etat: { cour_des_comptes_2018_2020: { statut: 'x' }, dpt_plf2026: { statut: 'publié', colonnes: ['c'], total_general: [1], missions: [{ mission: 'M', valeurs: [null], programmes: [] }] } } },
    ]).missions[0]
    expect(valeurs).toEqual([null])
  })

  it('sans fichier des dépenses fiscales : renvoi vers la page dédiée ; sans index : état en cours', async () => {
    viderCache()
    const remettre = servirNiches(false)
    await ecran('#/explorer/outre-mer')
    remettre()
    expect(main.querySelector('.erreur')).toBeNull()
    expect(main.querySelector('a[href="#/explorer/niches"]')?.textContent).toBe('Dépenses fiscales et exonérations de cotisations')
    viderCache()
    const vrai = globalThis.fetch
    globalThis.fetch = (async (u: string) => (String(u).includes('outremer/') ? new Response('', { status: 404 }) : vrai(u))) as typeof fetch
    const z = document.createElement('div')
    const { rendre } = await import('../src/ecrans/outremer')
    await rendre(z, new URLSearchParams())
    globalThis.fetch = vrai
    expect(z.textContent).toContain('Données en cours d’intégration')
    viderCache()
  })

  it('neutralité : lexique partagé, pas de tiret long, pas de style en ligne', async () => {
    viderCache()
    const remettre = servirNiches(true)
    for (const f of ['#/explorer/outre-mer', '#/explorer/outre-mer?t=975', '#/explorer/outre-mer?t=977']) {
      await ecran(f)
      const t = texte()
      for (const r of LEXIQUE.regles) expect(t, f).not.toMatch(new RegExp(`(?<![\\p{L}\\p{N}_])(?:${r.termes.join('|')})(?![\\p{L}\\p{N}_])`, 'iu'))
      expect(t, f).not.toContain('—')
      expect(main.querySelectorAll('[style]:not([data-l])').length, f).toBe(0)
      for (const table of Array.from(main.querySelectorAll('table'))) expect(table.querySelector('caption'), f).not.toBeNull()
    }
    remettre()
  })
})

// @vitest-environment happy-dom
// Bloc « Le budget de chaque université » de /explorer/education-recherche (site/data/universites/, extrait réel dans
// tests/fixtures/universites/) : montants lus dans les données, ratios « sur 100 € » repris de la source et jamais
// calculés, null affiché « non publié », nature de l'exercice écrite, encadré de ce qui manque à la source, choix
// partagés, lexique neutre.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { blocUniversite } from '../src/ecrans/education_recherche'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { eur } from '../src/util'
import { attendreQue, choisirValeur, monterPage } from './aide-dom'

const RACINE = process.cwd()
const PROPRES = join(RACINE, 'tests', 'fixtures', 'universites')
const ER = join(RACINE, 'tests', 'fixtures', 'education_recherche')
const COMMUNES = join(RACINE, 'tests', 'fixtures')
const lire = (rel: string) => JSON.parse(readFileSync(join(PROPRES, 'data', rel), 'utf8'))
const n = (t: string | null | undefined) => (t ?? '').replace(/\s+/g, ' ').trim()
const IDX = lire('universites/index.json')
const ETABS = lire('universites/etablissements.json')
let main: HTMLElement

beforeAll(() => {
  monterPage()
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const rel = u.split('?')[0]
    for (const base of [PROPRES, ER, COMMUNES]) {
      const f = join(base, rel)
      if (existsSync(f)) return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    return new Response('introuvable', { status: 404 })
  })
  main = document.getElementById('contenu') as HTMLElement
})

describe('budget de chaque université', () => {
  it('rend le dernier compte financier, les ratios de la source et les absences', () => {
    const e = ETABS.etablissements.find((x: { nom: string }) => x.nom === 'La Rochelle Université')
    const d = document.createElement('div')
    d.innerHTML = blocUniversite(IDX, ETABS, e.uai, null)
    const t = n(d.textContent)
    const an = Object.keys(e.exercices).sort().reverse().find((a) => e.exercices[a][0] === 'compte_financier')!
    expect(t).toContain(`Exercice ${an} : compte financier (exécution)`)
    const v = e.exercices[an]
    const col = (c: string) => v[ETABS.colonnes.indexOf(c)]
    expect(t).toContain(n(eur(col('produits_encaissables'))))
    const ratio = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(col('personnel_sur_100'))
    expect(t).toContain(`Sur 100 € de produits encaissables`)
    expect(n(t)).toContain(n(`${ratio} € correspondent aux charges de personnel`))
    expect(t).toContain('ratios publiés par le ministère, pas calculés par le site')
    const nulls = IDX.indicateurs.filter((i: { cle: string; unite: string }) => i.unite !== 'euros sur 100 €' && col(i.cle) === null).length
    expect(d.querySelectorAll('td [data-statut="nonpub"]').length).toBe(nulls)
    expect(d.querySelector('caption')?.textContent).toContain('compte financier')
  })

  it('le budget initial est signalé comme une prévision', () => {
    const e = ETABS.etablissements[0]
    const budget = Object.keys(e.exercices).find((a) => e.exercices[a][0] === 'budget_initial')
    if (!budget) return
    const d = document.createElement('div')
    d.innerHTML = blocUniversite(IDX, ETABS, e.uai, budget)
    expect(n(d.textContent)).toContain('budget initial (prévision)')
    expect(n(d.textContent)).toContain('à ne pas comparer à un compte financier')
  })

  it('dans la page : choix d’établissement et d’exercice, encadré de ce qui manque, source', async () => {
    const e = ETABS.etablissements[1]
    const fragment = `#/explorer/education-recherche?etab=${e.uai}`
    location.hash = fragment
    await afficher(ROUTES, main, fragment)
    await attendreQue(() => !!main.querySelector('#er-univ-detail'))
    const zone = main.querySelector('#er-universites') as HTMLElement
    expect(n(zone.querySelector('#er-univ-detail')?.textContent)).toContain(e.nom)
    expect(zone.querySelector('aside.manque')?.textContent).toContain('subvention pour charges de service public')
    expect(zone.querySelector('.source')?.textContent).toContain('data.enseignementsup-recherche.gouv.fr')
    const autre = ETABS.etablissements[2]
    choisirValeur(zone, 'er-univ', autre.uai)
    expect(n(zone.querySelector('#er-univ-detail')?.textContent)).toContain(autre.nom)
    const annees = Object.keys(autre.exercices).sort()
    choisirValeur(zone, 'er-univ-annee', annees[0])
    expect(n(zone.querySelector('#er-univ-detail')?.textContent)).toContain(`Exercice ${annees[0]}`)
  })

  it('lexique neutre, pas de tiret long, tableaux légendés', () => {
    const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[] }[]; exceptions: string[] }
    const zone = main.querySelector('#er-universites') as HTMLElement
    let x = n(zone.textContent)
    for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
    for (const r of LEXIQUE.regles) for (const terme of r.termes) expect(x).not.toMatch(new RegExp(`(?<![\\p{L}\\d])(?:${terme})(?![\\p{L}\\d])`, 'iu'))
    expect(zone.innerHTML).not.toContain('—')
    for (const t of zone.querySelectorAll('table')) expect(t.querySelector('caption')).not.toBeNull()
  })
})

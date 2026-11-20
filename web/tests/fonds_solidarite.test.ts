// @vitest-environment happy-dom
// Bloc « Le fonds de solidarité dans ton département » de /decisions/controle (site/data/fonds_solidarite/, extrait
// réel dans tests/fixtures/fonds_solidarite/) : agrégats repris tels quels, aucune entreprise nommée, cumuls de fin de
// mois jamais additionnés ni différenciés, volets séparés, null affiché « non publié », encadrés de ce qui manque.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { blocFondsMois, blocFondsSolidarite } from '../src/ecrans/controle'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { entier, eur } from '../src/util'
import { attendreQue, choisirValeur, monterPage } from './aide-dom'

const RACINE = process.cwd()
const PROPRES = join(RACINE, 'tests', 'fixtures', 'fonds_solidarite')
const COMMUNES = join(RACINE, 'tests', 'fixtures')
const lire = (rel: string) => JSON.parse(readFileSync(join(PROPRES, 'data', rel), 'utf8'))
const n = (t: string | null | undefined) => (t ?? '').replace(/\s+/g, ' ').trim()
const IDX = lire('fonds_solidarite/index.json')
const DEPS = lire('fonds_solidarite/departements.json')
const MOIS = lire('fonds_solidarite/regions_mois.json')
let main: HTMLElement

beforeAll(() => {
  monterPage()
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const rel = u.split('?')[0]
    for (const base of [PROPRES, COMMUNES]) {
      const f = join(base, rel)
      if (existsSync(f)) return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    return new Response('introuvable', { status: 404 })
  })
  main = document.getElementById('contenu') as HTMLElement
})

describe('fonds de solidarité', () => {
  it('département : une ligne par secteur, chiffres de la source, aucune somme', () => {
    const d = document.createElement('div')
    d.innerHTML = blocFondsSolidarite(IDX, DEPS, '44')
    const lignes = DEPS.par_section.lignes.filter((l: string[]) => l[0] === '44')
    const t = d.querySelector('table')!
    expect(t.querySelectorAll('tbody tr')).toHaveLength(lignes.length)
    const l = lignes[0]
    const tr = t.querySelector('tbody tr')!
    expect(n(tr.textContent)).toContain(n(entier(l[2])))
    expect(n(tr.textContent)).toContain(n(eur(l[4])))
    expect(n(d.textContent)).toContain('Le site n’additionne pas les lignes')
    expect(n(d.textContent)).toContain('24/06/2022')
    expect(n(d.textContent)).not.toMatch(/total/i)
  })

  it('mois : cumuls de chaque fin de mois, volets séparés, absence affichée non publié', () => {
    const d = document.createElement('div')
    d.innerHTML = blocFondsMois(IDX, MOIS, '52', 'I')
    const t = d.querySelector('table')!
    expect(t.querySelector('caption')?.textContent).toContain('jamais additionnés')
    const premiere = MOIS.lignes.filter((l: [string, number, string, string]) => l[2] === '52' && l[3] === 'I').map((l: string[]) => l[0]).sort()[0]
    expect(n(t.querySelector('tbody tr th')?.textContent)).toBe(premiere.split('-').reverse().join('/'))
    // le volet 2 n'existe pas encore au premier instantané : non publié, jamais 0
    expect(t.querySelector('tbody tr td:nth-child(3) [data-statut="nonpub"]')).not.toBeNull()
  })

  it('dans la page /decisions/controle : choix du département, encadrés de ce qui manque', async () => {
    const fragment = '#/decisions/controle?fsd=2A'
    location.hash = fragment
    await afficher(ROUTES, main, fragment)
    await attendreQue(() => !!main.querySelector('#fsd-detail'))
    const zone = main.querySelector('#fsd') as HTMLElement
    expect(n(zone.querySelector('#fsd-detail')?.textContent)).toContain('Corse-du-Sud')
    expect(zone.querySelectorAll('aside.manque').length).toBe(IDX.manques.length)
    choisirValeur(zone, 'fsd-dep', '44')
    expect(n(zone.querySelector('#fsd-detail')?.textContent)).toContain('Loire-Atlantique')
    choisirValeur(zone, 'fsd-section', 'G')
    expect(n(zone.querySelector('#fsd-mois caption')?.textContent)).toContain(IDX.sections.G)
    expect(zone.innerHTML).not.toContain('—')
    for (const t of zone.querySelectorAll('table')) expect(t.querySelector('caption')).not.toBeNull()
  })
})

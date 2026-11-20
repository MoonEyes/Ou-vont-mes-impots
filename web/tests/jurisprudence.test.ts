// @vitest-environment happy-dom
// Bloc « Les décisions de la justice administrative sur l'impôt et le budget » de /decisions/controle
// (site/data/jurisprudence/, extrait réel dans tests/fixtures/jurisprudence/) : comptes repris tels quels, deux
// critères fiscaux côte à côte, liens vers Légifrance seulement, aucun texte ni nom.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { blocJurComptes, blocJurDecisions } from '../src/ecrans/controle'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { entier } from '../src/util'
import { attendreQue, choisirValeur, monterPage } from './aide-dom'

const RACINE = process.cwd()
const PROPRES = join(RACINE, 'tests', 'fixtures', 'jurisprudence')
const COMMUNES = join(RACINE, 'tests', 'fixtures')
const lire = (rel: string) => JSON.parse(readFileSync(join(PROPRES, 'data', rel), 'utf8'))
const n = (t: string | null | undefined) => (t ?? '').replace(/\s+/g, ' ').trim()
const IDX = lire('jurisprudence/index.json')
const C = lire('jurisprudence/comptes.json')
const D24 = lire('jurisprudence/decisions/2024.json')
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

describe('jurisprudence administrative', () => {
  it('comptes par année : chiffres de la source, critères fiscaux séparés', () => {
    const j = IDX.juridictions[0]
    const d = document.createElement('div')
    d.innerHTML = blocJurComptes(IDX, C, j)
    const l = C.lignes.filter((x: [number, string]) => x[1] === j).sort((a: number[], b: number[]) => b[0] - a[0])[0]
    const tr = d.querySelector('tbody tr')!
    expect(n(tr.querySelector('th')?.textContent)).toBe(String(l[0]))
    expect(Array.from(tr.querySelectorAll('td')).map((x) => n(x.textContent))).toEqual(l.slice(2).map((v: number) => n(entier(v))))
    expect(d.querySelectorAll('thead th')).toHaveLength(6)
  })

  it('liste : liens Légifrance, sans texte ni nom', () => {
    const d = document.createElement('div')
    d.innerHTML = blocJurDecisions(IDX, D24, 0)
    const liens = Array.from(d.querySelectorAll('a'))
    expect(liens.length).toBe(Math.min(200, D24.decisions.filter((x: number[]) => x[1] === 0).length))
    for (const a of liens) expect(a.getAttribute('href')).toMatch(/^https:\/\/www\.legifrance\.gouv\.fr\/ceta\/id\/[A-Z]+TEXT\d{12}$/)
    expect(n(d.textContent)).not.toMatch(/\b(M\.|Mme) /)
  })

  it('dans la page : choix de juridiction et d’année', async () => {
    const fragment = '#/decisions/controle?jur=4'
    location.hash = fragment
    await afficher(ROUTES, main, fragment)
    await attendreQue(() => !!main.querySelector('#jur-liste') && !n(main.querySelector('#jur-liste')?.textContent).includes('Chargement'))
    const zone = main.querySelector('#jur') as HTMLElement
    expect(n(zone.querySelector('#jur-comptes caption')?.textContent)).toContain(IDX.juridictions[4])
    choisirValeur(zone, 'jur-j', '0')
    expect(n(zone.querySelector('#jur-comptes caption')?.textContent)).toContain('Conseil d’État'.replace('’', "'"))
    choisirValeur(zone, 'jur-an', '2024')
    await attendreQue(() => n(zone.querySelector('#jur-liste')?.textContent).includes('2024'))
    expect(zone.querySelector('aside.manque')).not.toBeNull()
    expect(zone.innerHTML).not.toContain('—')
  })
})

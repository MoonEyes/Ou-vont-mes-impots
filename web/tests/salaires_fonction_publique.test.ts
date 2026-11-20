// @vitest-environment happy-dom
// Bloc « Salaires nets moyens depuis 1995 (Insee) » de /explorer/fonction-publique (site/data/salaires_fonction_publique/,
// extrait réel dans tests/fixtures/salaires_fonction_publique/) : chiffres de l'Insee repris tels quels, évolution
// publiée (jamais recalculée), centiles, absence affichée « non publié », euros courants et constants jamais mêlés.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { blocSalaires } from '../src/ecrans/fonction_publique'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { eur } from '../src/util'
import { attendreQue, choisirValeur, monterPage } from './aide-dom'

const RACINE = process.cwd()
const PROPRES = join(RACINE, 'tests', 'fixtures', 'salaires_fonction_publique')
const COMMUNES = join(RACINE, 'tests', 'fixtures')
const lire = (rel: string) => JSON.parse(readFileSync(join(PROPRES, 'data', rel), 'utf8'))
const n = (t: string | null | undefined) => (t ?? '').replace(/\s+/g, ' ').trim()
const IDX = lire('salaires_fonction_publique/index.json')
const SL = lire('salaires_fonction_publique/series_longues.json')
const AN = lire('salaires_fonction_publique/annuel.json')
const M = 'SALAIRE_NET_EQTP_MENSUEL_MOYEN_EUROS_CONSTANTS'
let main: HTMLElement

const valeur = (versant: string, annee: number, mesure = M, extra: Record<string, string> = {}) => {
  const dims = SL.colonnes.slice(1, -1) as string[]
  const f: Record<string, string> = { DERA_MEASURE: mesure, PUBLIC_LEGAL_FORM: versant, ...extra }
  return SL.observations.find((o: (string | number)[]) => o[0] === annee && dims.every((d, i) => d === 'UNIT_MEASURE' || o[i + 1] === (f[d] ?? '_T')))?.at(-1)
}

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

describe('salaires de la fonction publique (Insee)', () => {
  it('séries longues : salaire moyen et évolution publiée, dernière année en tête', () => {
    const d = document.createElement('div')
    d.innerHTML = blocSalaires(IDX, SL, AN, '_T')
    const t = d.querySelector('table')!
    const der = Math.max(...SL.observations.filter((o: (string | number)[]) => o[1] === M && o[2] === '_T').map((o: (string | number)[]) => o[0] as number))
    const tr = t.querySelector('tbody tr')!
    expect(n(tr.querySelector('th')?.textContent)).toBe(String(der))
    expect(n(tr.textContent)).toContain(n(eur(valeur('_T', der) as number)))
    expect(n(d.textContent)).toContain('publiées par l’Insee')
    expect(n(d.textContent)).toContain('ne se comparent pas aux séries en euros constants')
  })

  it('centiles et statuts de la dernière année, absence affichée non publié', () => {
    const d = document.createElement('div')
    d.innerHTML = blocSalaires(IDX, SL, AN, '2')
    const centiles = Array.from(d.querySelectorAll('table')).find((x) => n(x.querySelector('caption')?.textContent).includes('centiles'))!
    expect(centiles.querySelectorAll('tbody tr').length).toBe(9)
    expect(n(centiles.textContent)).toContain('50 % des agents gagnent moins que')
    // le statut « personnels médicaux » n'est pas publié pour tous les versants ou toutes les années
    for (const td of d.querySelectorAll('td')) expect(n(td.textContent)).not.toBe('0 €')
  })

  it('dans la page : choix du versant', async () => {
    const fragment = '#/explorer/fonction-publique'
    location.hash = fragment
    await afficher(ROUTES, main, fragment)
    await attendreQue(() => !!main.querySelector('#fp-sal-detail'))
    const zone = main.querySelector('#fp-salaires') as HTMLElement
    expect(n(zone.querySelector('caption')?.textContent)).toContain('Ensemble de la fonction publique')
    choisirValeur(zone, 'fp-sal-versant', '2')
    expect(n(zone.querySelector('#fp-sal-detail caption')?.textContent)).toContain('Territoriale')
    expect(zone.innerHTML).not.toContain('—')
    for (const t of zone.querySelectorAll('table')) expect(t.querySelector('caption')).not.toBeNull()
  })
})

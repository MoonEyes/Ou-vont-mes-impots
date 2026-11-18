// @vitest-environment happy-dom
// Bloc « Investissement réalisé et délibérations publiées » de la page commune, sur des extraits réels de
// site/data/investissement_communes et site/data/deliberations (tests/fixtures/commune_investissement/data/ :
// Acigné, qui publie budget et délibérations, et Lécousse, qui ne publie ni l'un ni l'autre au format national).
// Rien dans le HTML prérendu (sans IntersectionObserver), section ajoutée dans le navigateur, données au clic,
// exercices absents « non publié », aucun taux calculé, phrase d'absence factuelle, aucune requête externe.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { viderCache } from '../src/donnees'
import { blocDeliberations, blocInvestissement, brancher, phraseCouverture, section, TITRE, type Contexte, type DelibIndex, type InvDep, type InvIndex } from '../src/ecrans/commune_investissement'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { attendreQue, monterPage } from './aide-dom'

const RACINE = process.cwd()
const MES_FIXTURES = join(RACINE, 'tests', 'fixtures', 'commune_investissement')
const lire = (f: string) => JSON.parse(readFileSync(join(MES_FIXTURES, 'data', f), 'utf8'))
const IDX = lire('investissement_communes/index.json') as InvIndex
const DEP = lire('investissement_communes/communes/35.json') as InvDep
const DI = lire('deliberations/index.json') as DelibIndex
const ACIGNE: Contexte = { insee: '35001', dep: '35', nom: 'Acigné', siren: '213500010', epci: '243500139', nomEpci: 'Rennes Métropole' }
const LECOUSSE: Contexte = { insee: '35150', dep: '35', nom: 'Lécousse', siren: '213501505', epci: null, nomEpci: null }

const requetes: string[] = []
let main: HTMLElement
function servir() {
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const f = join(MES_FIXTURES, u.split('?')[0])
    if (!existsSync(f)) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}
const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function verifierLexique(t: string, ou: string) {
  let x = t.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
}
const texte = (el: Element) => el.textContent?.replace(/\s+/g, ' ') ?? ''

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu') as HTMLElement
})
afterAll(() => {
  vi.unstubAllGlobals()
})
beforeEach(() => {
  viderCache()
  requetes.length = 0
})

describe('rendu des blocs', () => {
  it('investissement : exercices, colonnes, crédits votés à côté, aucun taux', () => {
    const div = document.createElement('div')
    div.innerHTML = blocInvestissement(IDX, DEP, ACIGNE)
    const t = texte(div)
    const lignes = div.querySelectorAll('tbody tr')
    expect(lignes.length).toBe(DEP.annees.length)
    expect(div.querySelector('caption')?.textContent).toContain('Acigné')
    expect(div.querySelectorAll('th[scope="col"]').length).toBe(8)
    expect(t).toContain('Crédits votés au budget primitif')
    expect(t).toContain('Calculé par le site')
    expect(t).not.toMatch(/taux de réalisation\s*:|\d\s*%/i)
    const a = DEP.communes['35001']
    const an = Object.keys(a.m).sort().pop() as string
    const cellule = [...lignes].find((l) => l.querySelector('th')?.textContent === an)?.querySelectorAll('td')[0].textContent ?? ''
    expect(cellule.replace(/\s/g, '')).toBe(new Intl.NumberFormat('fr-FR').format(a.m[an][0]).replace(/\s/g, '') + '€')
    verifierLexique(t, 'investissement')
  })

  it('exercice sans balance : « non publié », jamais 0', () => {
    const dep: InvDep = JSON.parse(JSON.stringify(DEP))
    delete dep.communes['35150'].m[dep.annees[0]]
    const div = document.createElement('div')
    div.innerHTML = blocInvestissement(IDX, dep, LECOUSSE)
    const premiere = [...div.querySelectorAll('tbody tr')].find((l) => l.querySelector('th')?.textContent === dep.annees[0])
    expect(premiere?.textContent).toContain('Non publié')
    expect(texte(div)).toContain('ne publie pas son budget au format national')
    expect(div.querySelectorAll('th[scope="col"]').length).toBe(6)
  })

  it('délibérations : comptes, plus récentes avec lien, exclusions comptées ; absence factuelle', () => {
    const coll = lire('deliberations/collectivites/213500010.json')
    const div = document.createElement('div')
    div.innerHTML = blocDeliberations(DI, coll, 'Acigné')
    expect(div.querySelector('caption')?.textContent).toContain('par année et par thème')
    expect(div.querySelectorAll('details').length).toBeGreaterThan(0)
    for (const a of div.querySelectorAll<HTMLAnchorElement>('details a')) expect(a.getAttribute('href')).toMatch(/^https:\/\//)
    expect(texte(div)).toMatch(/n’apparaissent pas ci-dessous/)
    verifierLexique(texte(div), 'délibérations')
    div.innerHTML = blocDeliberations(DI, null, 'Lécousse')
    expect(texte(div)).toContain('Lécousse ne publie pas ses délibérations en données ouvertes')
  })

  it('couverture : nombre, parts et badge « calculé par le site »', () => {
    const div = document.createElement('div')
    div.innerHTML = phraseCouverture(DI)
    const t = texte(div)
    expect(t).toMatch(/communes sur 34\s875/)
    expect(t).toContain('de la population')
    expect(t).toContain('Calculé par le site')
  })
})

describe('branchement sur la page commune', () => {
  it('sans IntersectionObserver (prérendu) : rien n’est ajouté', () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const cible = document.createElement('div')
    cible.innerHTML = '<div id="sec-subventions"></div>'
    const avant = cible.innerHTML
    brancher(cible, ACIGNE)
    expect(cible.innerHTML).toBe(avant)
    vi.unstubAllGlobals()
    servir()
  })

  it('page commune rendue sans IntersectionObserver : HTML sans le bloc', async () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    location.hash = '#/local/commune?insee=35001'
    await afficher(ROUTES, main, '#/local/commune?insee=35001')
    expect(main.querySelector('h1')?.textContent).toBe('Acigné')
    expect(main.innerHTML).not.toContain(TITRE)
    expect(requetes.some((r) => r.includes('investissement_communes') || r.includes('deliberations'))).toBe(false)
    vi.unstubAllGlobals()
    servir()
  })

  it('dans le navigateur : section après les subventions, données au clic seulement', async () => {
    let rappel: ((e: { isIntersecting: boolean }[]) => void) | null = null
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        constructor(f: (e: { isIntersecting: boolean }[]) => void) {
          rappel = f
        }
        observe() {}
        disconnect() {}
      },
    )
    const cible = document.createElement('div')
    cible.innerHTML = '<h2>Subventions</h2><div id="sec-subventions"></div><h2>Pour aller plus loin</h2>'
    document.body.appendChild(cible)
    brancher(cible, ACIGNE)
    expect(cible.querySelector('#titre-investissement')).toBeNull()
    rappel!([{ isIntersecting: true }])
    const h2 = cible.querySelector('#titre-investissement')
    expect(h2?.textContent).toBe(TITRE)
    expect(cible.querySelector('#sec-subventions')?.nextElementSibling?.tagName).toBe('SECTION')
    expect(requetes.length).toBe(0)
    cible.querySelector<HTMLButtonElement>('section button')!.click()
    await attendreQue(() => !!cible.querySelector('#zone-investissement table'))
    await attendreQue(() => !cible.querySelector('#zone-investissement')?.hasAttribute('aria-busy'))
    const zone = cible.querySelector('#zone-investissement') as HTMLElement
    expect(zone.querySelectorAll('table').length).toBeGreaterThanOrEqual(2)
    expect(texte(zone)).toContain('Rennes Métropole')
    expect(requetes.every((r) => r.startsWith('data/'))).toBe(true)
    expect(requetes).toContain('data/investissement_communes/communes/35.json')
    verifierLexique(texte(zone), 'zone')
    cible.remove()
    vi.unstubAllGlobals()
    servir()
  })

  it('section seule : bouton accessible relié à sa zone', () => {
    const s = section(LECOUSSE)
    const b = s.querySelector('button') as HTMLButtonElement
    expect(b.getAttribute('aria-controls')).toBe('zone-investissement')
    expect(b.getAttribute('aria-expanded')).toBe('false')
    expect(s.querySelector('h2')?.id).toBe('titre-investissement')
  })
})

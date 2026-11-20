// @vitest-environment happy-dom
// « Ma commune » : sections du lot 2 (contrat 2.72 à 2.78), chargées à leur première ouverture, sur des extraits réels
// de site/data (tests/fixtures/ma_commune_complements/data : Loire-Atlantique réduite à Nantes 44109 et
// Grandchamp-des-Fontaines 44066 et à leurs intercommunalités ; le reste de la page vient de tests/fixtures/ma_commune).
// Valeurs non modifiées. Vérifie : rien n'est lu tant qu'une section est fermée, chaque bloc a sa source, un bloc sans
// donnée affiche l'encadré « Donnée non publiée à la source », aucun texte de valeur.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { encadreManque, MANQUES } from '../src/composants/manque'
import { viderCache } from '../src/donnees'
import { SECTIONS_COMPLEMENTS } from '../src/ecrans/ma_commune'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { attendreQue, monterPage } from './aide-dom'

const RACINE = process.cwd()
const DOSSIERS = [join(RACINE, 'tests', 'fixtures', 'ma_commune_complements'), join(RACINE, 'tests', 'fixtures', 'ma_commune')]
const requetes: string[] = []
let main: HTMLElement

const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function verifierLexique(t: string, ou: string) {
  let x = t.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
}
const LOT2 = /^data\/(ofgl_complements|elus_indemnites|caf_communes|ifi_communes|emploi_territoires|pathologies_departements|police_municipale)\//

beforeAll(() => {
  monterPage()
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const f = DOSSIERS.map((d) => join(d, u.split('?')[0])).find((x) => existsSync(x))
    if (!f) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })
  main = document.getElementById('contenu') as HTMLElement
})
beforeEach(() => {
  requetes.length = 0
  viderCache()
})
afterAll(() => vi.unstubAllGlobals())

const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  await attendreQue(() => !main.querySelector('[aria-busy="true"]'))
}
async function ouvrir(id: string): Promise<HTMLElement> {
  const d = main.querySelector<HTMLDetailsElement>(`#${id}-repli`)!
  d.open = true
  d.dispatchEvent(new Event('toggle'))
  await attendreQue(() => !main.querySelector(`#${id}`)!.querySelector('.chargement') && !main.querySelector(`#${id}[aria-busy]`))
  return main.querySelector<HTMLElement>(`#${id}`)!
}
const t = (el: Element) => el.textContent?.replace(/\s+/g, ' ') ?? ''

describe('sections du lot 2 dans « Ma commune »', () => {
  it('trois sections repliées après les autres, un H2 chacune, rien de chargé tant qu’elles restent fermées', async () => {
    await ecran('#/local/ma-commune?insee=44066')
    for (const [id, titre] of SECTIONS_COMPLEMENTS) {
      const d = main.querySelector<HTMLDetailsElement>(`#${id}-repli`)!
      expect(d.open, id).toBe(false)
      expect(d.closest('section')!.querySelector(':scope > h2')?.textContent).toBe(titre)
    }
    expect(main.querySelector<HTMLDetailsElement>('#mc-dep-services-repli')!.closest('#mc-departement-panneau')).not.toBeNull()
    expect(requetes.filter((u) => LOT2.test(u))).toEqual([])
  })

  it('Grandchamp-des-Fontaines : flux et FPIC, patrimoine, élus, police, CAF, France Travail ; IFI sous les seuils', async () => {
    await ecran('#/local/ma-commune?insee=44066')
    const sol = await ouvrir('mc-solidarite')
    expect(t(sol)).toContain('Attribution de compensation reçue (fonctionnement)')
    expect(t(sol)).toContain('Fonds de péréquation (FPIC)')
    expect(t(sol)).toContain('Erdre et Gesvres')
    expect(sol.querySelector('.source')).not.toBeNull()
    const moy = await ouvrir('mc-moyens')
    expect(t(moy)).toContain('Actif brut')
    expect(t(moy)).toContain('compte 653')
    expect(t(moy)).toContain('ni le nombre d’élus indemnisés ni le montant de chacun')
    expect(moy.querySelectorAll('.source').length).toBeGreaterThanOrEqual(2)
    const hab = await ouvrir('mc-habitants')
    expect(t(hab)).toContain('Revenu de solidarité active (RSA)')
    expect(t(hab)).toContain('Montant de décembre')
    expect(t(hab)).toContain('arrondis à 5')
    expect(t(hab)).toContain('allocation aux adultes handicapés')
    expect(t(hab)).toContain('Inscrits à France Travail')
    // IFI : Grandchamp est sous les seuils de diffusion, l'encadré le dit.
    const encadres = [...hab.querySelectorAll('aside.manque')].map(t)
    expect(encadres.some((x) => x.includes('20 000 habitants'))).toBe(true)
    for (const z of [sol, moy, hab]) verifierLexique(t(z), z.id)
    expect(main.textContent).not.toContain('—')
    expect(requetes.every((u) => u.startsWith('data/'))).toBe(true)
  })

  it('Nantes : impôt sur la fortune immobilière publié ; département : SDIS, chômage, pathologies, établissements', async () => {
    await ecran('#/local/ma-commune?insee=44109')
    const hab = await ouvrir('mc-habitants')
    expect(t(hab)).toContain('Foyers redevables de l’impôt sur la fortune immobilière domiciliés à Nantes')
    expect(t(hab)).toContain('ISF')
    const dep = await ouvrir('mc-dep-services')
    expect(t(dep)).toContain('Comptes du SDIS de Loire-Atlantique')
    expect(t(dep)).toContain('Allocataires indemnisés')
    expect(t(dep)).toContain('Diabète')
    expect(t(dep)).toContain('ODbL')
    expect(t(dep)).toContain('Ordre : dépenses décroissantes')
    expect(dep.querySelectorAll('.source').length).toBeGreaterThanOrEqual(4)
    for (const tab of dep.querySelectorAll('table')) {
      expect(tab.querySelector('caption')).not.toBeNull()
      expect(tab.querySelectorAll('th[scope="col"]').length).toBeGreaterThan(0)
    }
    verifierLexique(t(dep), 'département')
  })

  it('ouverte deux fois : chargée une seule fois', async () => {
    await ecran('#/local/ma-commune?insee=44066')
    await ouvrir('mc-moyens')
    const n = requetes.length
    const d = main.querySelector<HTMLDetailsElement>('#mc-moyens-repli')!
    d.open = false
    d.dispatchEvent(new Event('toggle'))
    d.open = true
    d.dispatchEvent(new Event('toggle'))
    expect(requetes.length).toBe(n)
  })
})

describe('encadrés du lot 2', () => {
  it('quoi, pourquoi, depuis, source https, sans jugement', () => {
    const cas = [
      MANQUES.fluxIntercommunalite('X', '2025'),
      MANQUES.policeMunicipale('X', ['2019', '2024']),
      MANQUES.aahCommune('X'),
      MANQUES.ifiSousSeuil('X', ['2018', '2025']),
      MANQUES.sdisAbsent('Paris'),
    ]
    for (const m of cas) {
      expect(m.source.url).toMatch(/^https:\/\//)
      const d = document.createElement('div')
      d.innerHTML = encadreManque(m)
      verifierLexique(t(d), m.quoi)
      expect(t(d)).not.toMatch(/refus|opacit|devrait|malgré|pourtant/i)
    }
  })
})

describe('tableaux par département des écrans Explorer', () => {
  it('SDIS, Unédic, pathologies : ordre des codes, caption, source, sans jugement', async () => {
    const { tableauSdis, tableauUnedic, tableauPathologies } = await import('../src/ecrans/explorer_territoires')
    for (const [nom, f, attendu] of [
      ['sdis', tableauSdis, 'Loire-Atlantique (44)'],
      ['unedic', tableauUnedic, 'Loire-Atlantique (44)'],
      ['pathologies', tableauPathologies, 'Diabète'],
    ] as const) {
      const d = document.createElement('div')
      d.innerHTML = await f()
      expect(d.querySelector('caption'), nom).not.toBeNull()
      expect(d.querySelector('.source'), nom).not.toBeNull()
      expect(t(d), nom).toContain(attendu)
      verifierLexique(t(d), nom)
    }
    const d = document.createElement('div')
    d.innerHTML = await tableauSdis()
    const codes = [...d.querySelectorAll('tbody th')].map((x) => /\(([^)]+)\)$/.exec(x.textContent ?? '')?.[1] ?? '')
    expect(codes).toEqual([...codes].sort((a, b) => a.localeCompare(b, 'fr', { numeric: true })))
  })
})

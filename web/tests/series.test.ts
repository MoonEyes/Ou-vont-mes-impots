// @vitest-environment happy-dom
// Écran /explorer/series : grandes masses depuis 2005, en euros courants, constants ou part du PIB (fixtures réelles).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { convertir, echelleCommune, phraseLecture, type Index } from '../src/ecrans/series'
import { attendre, monterPage, requetes } from './aide-dom'

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''
const lire = (f: string) => JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/data', f), 'utf8'))
const idx = lire('series/index.json') as Index
const fr = (x: number, d = 1) => new Intl.NumberFormat('fr-FR', { minimumFractionDigits: d, maximumFractionDigits: d }).format(x).replace(/\s/g, ' ')
const norm = (s: string) => s.replace(/\s/g, ' ')

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('séries longues : calculs', () => {
  it('euros constants et part du PIB à partir de l’indice des prix et du PIB publiés', () => {
    const ref = idx.annee_reference
    expect(convertir(100, ref, 'constants', idx)).toBeCloseTo(100)
    expect(convertir(100, '2005', 'constants', idx)).toBeCloseTo((100 * idx.prix.indice[ref]) / idx.prix.indice['2005'], 3)
    expect(convertir(idx.pib.md['2020'] / 2, '2020', 'pib', idx)).toBeCloseTo(50)
    expect(convertir(42, '2010', 'courants', idx)).toBe(42)
    // Valeur absente : null, jamais 0 ; année sans indice : null.
    expect(convertir(null, '2010', 'pib', idx)).toBeNull()
    expect(convertir(10, '1990', 'constants', idx)).toBeNull()
  })

  it('phrase de lecture factuelle (première et dernière valeur), échelle qui inclut zéro', () => {
    const p = phraseLecture('Dette', [['2005', 1000], ['2006', null], ['2025', 3460.1]], 'courants', '2025')
    expect(norm(p)).toBe(norm(`Dette : passe de ${fr(1000)} Md€ en 2005 à ${fr(3460.1)} Md€ en 2025 (en euros courants).`))
    expect(phraseLecture('X', [['2005', null]], 'pib', '2025')).toContain('pas assez de valeurs')
    const e = echelleCommune([[-150, -60], [10, null]])
    expect(e.min).toBeLessThanOrEqual(-150)
    expect(e.max).toBeGreaterThanOrEqual(10)
    expect(echelleCommune([[1000, 3460]]).min).toBe(0)
  })
})

describe('séries longues : écran', () => {
  it('route sous Explorer, six blocs, chaque courbe avec sa phrase et un tableau par bloc', async () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/series')!
    expect(r.parent).toBe('/explorer')
    await ecran('#/explorer/series')
    expect(main.querySelector('h1')?.textContent).toBe('Les finances publiques depuis 2005')
    const titres = Array.from(main.querySelectorAll('h2')).map((x) => x.textContent)
    for (const t of ['Les recettes et les grands impôts', 'Les dépenses par administration', 'Les dépenses par fonction', 'Le solde : déficit ou excédent', 'La dette publique', 'Les intérêts de la dette'])
      expect(titres).toContain(t)
    const courbes = Array.from(main.querySelectorAll('svg.sl-courbe'))
    expect(courbes.length).toBe(1 + 6 + 1 + 3 + 10 + 1 + 3 + 1 + 1)
    for (const svg of courbes) {
      // Nom accessible : titre de la courbe + phrase de lecture visible.
      const ids = svg.getAttribute('aria-labelledby')!.split(' ')
      expect(svg.getAttribute('role')).toBe('img')
      for (const id of ids) expect(main.querySelector(`#${id}`)?.textContent, id).toBeTruthy()
      expect(main.querySelector(`#${ids[1]}`)?.textContent).toMatch(/passe de|reste à/)
    }
    const blocs = main.querySelectorAll('section.sl-bloc')
    expect(blocs.length).toBe(6)
    for (const b of Array.from(blocs)) {
      const t = b.querySelector('table')!
      expect(t.querySelector('caption')?.textContent).toBeTruthy()
      expect(t.querySelectorAll('thead th[scope="col"]').length).toBeGreaterThan(1)
      expect(t.querySelector('tbody th[scope="row"]')?.textContent).toBe('2025')
      expect(b.querySelector('.source')?.textContent).toBeTruthy()
    }
    // Aucune requête hors data/.
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })

  it('euros courants par défaut : dette 2025 telle que publiée, valeurs provisoires signalées', async () => {
    await ecran('#/explorer/series')
    const enc = lire('dette/encours.json')
    const dette = main.querySelector('section[aria-labelledby="sl-h-dette"]')!
    expect(norm(dette.textContent ?? '')).toContain(norm(`${fr(enc.insee.Ensemble.md['2025'])} Md€ en 2025`))
    expect(main.querySelector('button[data-mode="courants"]')?.getAttribute('aria-pressed')).toBe('true')
    expect(main.querySelectorAll('path.sl-provisoire').length).toBeGreaterThan(0)
    expect(texte()).toContain('* valeur provisoire')
    expect(texte()).toContain('Pointillé : valeur provisoire')
  })

  it('bascule : euros constants puis part du PIB, sans changer de page, ruptures de série affichées', async () => {
    await ecran('#/explorer/series')
    const enc = lire('dette/encours.json')
    main.querySelector<HTMLButtonElement>('button[data-mode="pib"]')!.click()
    await attendre(80)
    expect(main.querySelector('button[data-mode="pib"]')?.getAttribute('aria-pressed')).toBe('true')
    expect(main.querySelector('button[data-mode="courants"]')?.getAttribute('aria-pressed')).toBe('false')
    const partDette = (enc.insee.Ensemble.md['2025'] / idx.pib.md['2025']) * 100
    expect(norm(main.querySelector('section[aria-labelledby="sl-h-dette"]')!.textContent ?? '')).toContain(norm(`${fr(partDette)} % en 2025 du PIB`))
    expect(texte()).toContain('part du PIB, en %')
    expect(texte()).toContain('le PIB en euros courants baisse')
    main.querySelector<HTMLButtonElement>('button[data-mode="constants"]')!.click()
    await attendre(80)
    expect(texte()).toContain(`milliards d’euros de ${idx.annee_reference}`)
    expect(texte()).toContain('base 2025')
    const ens2005 = lire('administrations.json').annees['2005'].Ensemble.TE as number
    const attendu = ens2005 * idx.prix.coefficient['2005']
    expect(norm(main.querySelector('section[aria-labelledby="sl-h-administrations"]')!.textContent ?? '')).toContain(norm(`${fr(attendu)} Md€ en 2005`))
    // Ruptures et précautions de lecture.
    expect(texte()).toContain('base 2020')
    expect(texte()).toContain('leur somme dépasse le total consolidé')
  })

  it('paramètre u : ouvre directement le mode demandé ; mode inconnu ramené aux euros courants', async () => {
    await ecran('#/explorer/series?u=pib')
    expect(main.querySelector('button[data-mode="pib"]')?.getAttribute('aria-pressed')).toBe('true')
    await ecran('#/explorer/series?u=autre')
    expect(main.querySelector('button[data-mode="courants"]')?.getAttribute('aria-pressed')).toBe('true')
  })

  it('fichiers de séries absents : état « en cours d’intégration » avec des sorties', async () => {
    const { rendre } = await import('../src/ecrans/series')
    const { viderCache } = await import('../src/donnees')
    viderCache()
    const vrai = globalThis.fetch
    globalThis.fetch = (async (u: string) => (String(u).includes('series/') ? new Response('', { status: 404 }) : vrai(u))) as typeof fetch
    const z = document.createElement('div')
    await rendre(z)
    expect(z.textContent).toContain('Données en cours d’intégration')
    expect(z.querySelector('a[href="#/explorer/dette"]')).not.toBeNull()
    globalThis.fetch = vrai
    viderCache()
  })
})

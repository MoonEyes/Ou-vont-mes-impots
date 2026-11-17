// @vitest-environment happy-dom
// Site publié : la page prérendue porte data-racine ; le script reprend la main avec de vrais chemins
// (liens, History API), et les anciens fragments « #/… » redirigent vers le chemin.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { attendreQue, monterPage } from './aide-dom'

const BASE = '/Ou-vont-mes-impots/'
const FIXTURES = join(process.cwd(), 'tests', 'fixtures')
const requetes: string[] = []
let main: HTMLElement

const titre = () => main.querySelector('h1')?.textContent ?? ''

beforeAll(async () => {
  // Page prérendue de /explorer/etat/, ouverte avec un ancien fragment partagé (#/explorer/dette).
  ;(window as unknown as { happyDOM: { setURL(u: string): void } }).happyDOM.setURL(`https://exemple.test${BASE}explorer/etat/#/explorer/dette`)
  monterPage()
  document.documentElement.dataset.racine = '../../'
  document.documentElement.dataset.site = `https://exemple.test${BASE}`
  document.head.innerHTML = '<title></title><meta name="description" content="" /><link rel="canonical" href="" />'
  main = document.getElementById('contenu') as HTMLElement
  // Contenu et liens tels que le prérendu les écrit : relatifs à la page.
  main.innerHTML = '<div class="ecran"><h1>Sur 100 € dépensés par l’État</h1><a id="relatif" href="../../explorer/secu/">Sécurité sociale</a></div>'
  document.querySelector('.marque')!.setAttribute('href', '../../')
  vi.stubGlobal('fetch', async (url: string) => {
    requetes.push(String(url))
    const u = String(url)
    if (!u.startsWith(BASE + 'data/')) throw new Error(`adresse de données inattendue : ${u}`)
    const f = join(FIXTURES, u.slice(BASE.length))
    if (!existsSync(f)) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200 })
  })
  await import('../src/main')
})

describe('navigation en vrais chemins', () => {
  it('ancien fragment : remplacé par le chemin, sans rechargement, et la bonne page est rendue', async () => {
    expect(location.pathname).toBe(`${BASE}explorer/dette/`)
    expect(location.hash).toBe('')
    await attendreQue(() => titre() === 'La dette publique')
    expect(document.title).toBe('La dette publique · Où vont mes impôts')
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(`https://exemple.test${BASE}explorer/dette/`)
    expect(document.querySelector('meta[name="description"]')?.getAttribute('content')).toContain('dette publique')
  })

  it('données lues sous la racine du site, quel que soit le dossier de la page', () => {
    expect(requetes.length).toBeGreaterThan(0)
    for (const r of requetes) expect(r.startsWith(`${BASE}data/`), r).toBe(true)
  })

  it('liens : vrais chemins absolus dans l’en-tête, le pied et le contenu ; plus aucun fragment', async () => {
    expect(document.querySelector('.marque')?.getAttribute('href')).toBe(BASE)
    expect(document.querySelector('.navigation a[data-rubrique="/calcul"]')?.getAttribute('href')).toBe(`${BASE}calcul/`)
    expect(document.querySelector('.pied a')?.getAttribute('href')).toBe(`${BASE}methode/`)
    await attendreQue(() => main.querySelectorAll('a[href^="#/"]').length === 0 && main.querySelectorAll('a').length > 2)
    expect(main.querySelector('.fil-ariane a')?.getAttribute('href')).toBe(BASE)
    expect(document.querySelectorAll('a[href^="#/"]')).toHaveLength(0)
  })

  it('clic sur un lien interne : adresse changée par l’historique, page rendue sans rechargement', async () => {
    const lien = document.querySelector<HTMLAnchorElement>('.navigation a[data-rubrique="/explorer"]')!
    const clic = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
    lien.dispatchEvent(clic)
    expect(clic.defaultPrevented).toBe(true)
    expect(location.pathname).toBe(`${BASE}explorer/`)
    await attendreQue(() => titre() === 'Explorer les dépenses publiques')
    expect(document.querySelector('.navigation [aria-current=page]')?.getAttribute('data-rubrique')).toBe('/explorer')
  })

  it('écran qui pose un fragment (choix dans une liste) : converti en chemin avec ses paramètres', async () => {
    location.hash = '#/explorer/recettes?i=D211'
    window.dispatchEvent(new Event('hashchange'))
    expect(location.pathname + location.search).toBe(`${BASE}explorer/recettes/?i=D211`)
    expect(location.hash).toBe('')
    await attendreQue(() => titre().includes('recettes'))
  })

  it('page de commune : /local/<insee>-<nom>/ rend la commune', async () => {
    history.pushState(null, '', `${BASE}local/69123-lyon/`)
    window.dispatchEvent(new Event('popstate'))
    await attendreQue(() => titre() === 'Lyon')
    expect(document.title).toBe('Budget de Lyon (Rhône) : dépenses, dotations, taux · Où vont mes impôts')
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(`https://exemple.test${BASE}local/69123-lyon/`)
    await attendreQue(() => !!main.querySelector(`a[href="${BASE}local/69-rhone/"]`))
  })

  it('ancienne adresse d’une commune qui a sa page : remplacée par /local/<insee>-<nom>/', async () => {
    history.pushState(null, '', `${BASE}explorer/`)
    window.dispatchEvent(new Event('popstate'))
    await attendreQue(() => titre() === 'Explorer les dépenses publiques')
    history.pushState(null, '', `${BASE}local/commune/?insee=69123`)
    window.dispatchEvent(new Event('popstate'))
    await attendreQue(() => location.pathname === `${BASE}local/69123-lyon/`)
    expect(location.search).toBe('')
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(`https://exemple.test${BASE}local/69123-lyon/`)
  })

  it('lien externe, ancre de page et fichier de données : laissés au navigateur', () => {
    main.insertAdjacentHTML('beforeend', `<a id="ext" href="https://exemple.org/">x</a><a id="ancre" href="#contenu">y</a><a id="fichier" href="${BASE}data/meta.json">z</a>`)
    for (const id of ['ext', 'ancre', 'fichier']) {
      const clic = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
      main.querySelector(`#${id}`)!.dispatchEvent(clic)
      expect(clic.defaultPrevented, id).toBe(false)
    }
  })
})

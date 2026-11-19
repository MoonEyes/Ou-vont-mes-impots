// Lecture hors ligne : manifeste web, service worker (public/sw.js) exécuté dans un environnement simulé (caches,
// réseau, onglets), et branchement côté page (src/hors-ligne.ts). Aucune construction nécessaire.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { Window } from 'happy-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { afficherAvis, brancherHorsLigne, dateEnLettres, texteAvis, versionDuSite } from '../src/hors-ligne'

const RACINE = process.cwd()
const PUBLIC = join(RACINE, 'public')
const CODE_SW = readFileSync(join(PUBLIC, 'sw.js'), 'utf8')
const INDEX = readFileSync(join(RACINE, 'index.html'), 'utf8')
const ORIGINE = 'https://exemple.github.io'
const PORTEE = `${ORIGINE}/Ou-vont-mes-impots/`

// --- environnement simulé du service worker ------------------------------------------------------------------
type Stocke = { corps: ArrayBuffer; status: number; statusText: string; entetes: [string, string][] }
class FauxCache {
  entrees = new Map<string, Stocke>()
  private url = (r: Request | string) => (typeof r === 'string' ? r : r.url)
  async match(r: Request | string, o?: { ignoreSearch?: boolean }) {
    const u = this.url(r)
    let s = this.entrees.get(u)
    if (!s && o?.ignoreSearch) for (const [k, v] of this.entrees) if (k.split('?')[0] === u.split('?')[0]) s = v
    return s ? new Response(s.corps.slice(0), { status: s.status, statusText: s.statusText, headers: s.entetes }) : undefined
  }
  async put(r: Request | string, rep: Response) {
    const u = this.url(r)
    this.entrees.delete(u)
    this.entrees.set(u, { corps: await rep.arrayBuffer(), status: rep.status, statusText: rep.statusText, entetes: [...rep.headers] })
  }
  async keys() {
    return [...this.entrees.keys()].map((u) => new Request(u))
  }
  async delete(r: Request | string) {
    return this.entrees.delete(this.url(r))
  }
}
class FauxCaches {
  noms = new Map<string, FauxCache>()
  async open(n: string) {
    if (!this.noms.has(n)) this.noms.set(n, new FauxCache())
    return this.noms.get(n)!
  }
  async keys() {
    return [...this.noms.keys()]
  }
  async delete(n: string) {
    return this.noms.delete(n)
  }
}

type Reponse = { corps: string; type?: string; status?: number; redirige?: boolean }

/** Charge sw.js dans un faux contexte. reseau : adresse → réponse (absente = 404), ou null pour « pas de connexion ». */
function demarrerSw(version = 'abc123') {
  const ecouteurs: Record<string, (e: any) => void> = {}
  const caches = new FauxCaches()
  const messages: { client: string; data: any }[] = []
  const appels: string[] = []
  const etat = { enLigne: true, pages: {} as Record<string, Reponse>, lent: false }
  const fauxFetch = async (entree: Request | string) => {
    const u = typeof entree === 'string' ? entree : entree.url
    appels.push(u)
    if (!u.startsWith(ORIGINE)) throw new Error(`requête externe : ${u}`)
    if (etat.lent) await new Promise(() => {})
    if (!etat.enLigne) throw new TypeError('Failed to fetch')
    const p = etat.pages[u.split('?')[0]]
    const r = new Response(p ? p.corps : 'introuvable', { status: p ? (p.status ?? 200) : 404, headers: { 'content-type': p?.type ?? 'application/json' } })
    if (p?.redirige) Object.defineProperty(r, 'redirected', { value: true })
    return r
  }
  const self = {
    location: { href: `${PORTEE}sw.js?v=${version}` },
    registration: { scope: PORTEE },
    caches,
    clients: {
      get: async (id: string) => ({ id, postMessage: (data: any) => messages.push({ client: id, data }) }),
      claim: async () => {},
    },
    skipWaiting: () => {},
    addEventListener: (type: string, f: (e: any) => void) => (ecouteurs[type] = f),
  }
  new Function('self', 'fetch', CODE_SW)(self, fauxFetch)

  /** Simule un événement fetch ; renvoie la réponse, ou null si le service worker laisse passer. */
  async function demander(url: string, o: { navigation?: boolean; client?: string; methode?: string; sansAttendre?: boolean } = {}): Promise<Response | null> {
    const boite: { p: Promise<Response> | null } = { p: null }
    const attentes: Promise<unknown>[] = []
    ecouteurs.fetch({
      request: new Request(url, { method: o.methode ?? 'GET' }),
      clientId: o.navigation ? '' : (o.client ?? 'onglet-1'),
      resultingClientId: o.navigation ? (o.client ?? 'onglet-1') : '',
      respondWith: (p: Promise<Response>) => (boite.p = p),
      waitUntil: (p: Promise<unknown>) => attentes.push(p),
    })
    if (!boite.p) return null
    const r = await boite.p
    if (!o.sansAttendre) await Promise.all(attentes)
    return r
  }
  async function evenement(type: string, extra: Record<string, unknown> = {}) {
    const attentes: Promise<unknown>[] = []
    ecouteurs[type]({ ...extra, waitUntil: (p: Promise<unknown>) => attentes.push(p) })
    await Promise.all(attentes)
  }
  return { caches, messages, appels, etat, demander, evenement }
}

// Le mode de la requête (navigate) ne se règle pas sur un Request de Node : on le simule par une propriété.
const RequestOrigine = globalThis.Request
class RequeteNavigable extends RequestOrigine {
  constructor(entree: RequestInfo | URL, init?: RequestInit & { navigation?: boolean }) {
    super(entree, init)
    if (init?.navigation) Object.defineProperty(this, 'mode', { value: 'navigate' })
  }
}

async function naviguer(sw: ReturnType<typeof demarrerSw>, url: string, client = 'onglet-1') {
  vi.stubGlobal('Request', class extends RequeteNavigable {
    constructor(e: RequestInfo | URL, i?: RequestInit) {
      super(e, { ...i, navigation: true })
    }
  })
  try {
    return await sw.demander(url, { navigation: true, client })
  } finally {
    vi.stubGlobal('Request', RequestOrigine)
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('manifeste web', () => {
  const m = JSON.parse(readFileSync(join(PUBLIC, 'manifest.webmanifest'), 'utf8'))

  it('site consultable, pas une application : affichage navigateur, adresses relatives (GitHub Pages)', () => {
    expect(m.name).toBe('Le billet découpé')
    expect(m.lang).toBe('fr')
    expect(m.display).toBe('browser')
    for (const k of ['id', 'start_url', 'scope']) expect(m[k]).toBe('./')
    expect(JSON.stringify(m)).not.toMatch(/https?:|\/\//)
    expect(JSON.stringify(m)).not.toContain('—')
  })

  it('couleurs du thème et icônes tirées du logo existant, toutes présentes', () => {
    const theme = /<meta name="theme-color" content="([^"]+)"/.exec(INDEX)![1]
    expect(m.theme_color.toLowerCase()).toBe(theme.toLowerCase())
    expect(m.background_color.toLowerCase()).toBe('#f3f0ff')
    expect(m.icons.some((i: any) => i.src === 'favicon.svg')).toBe(true)
    expect(m.icons.some((i: any) => i.sizes === '512x512' && i.purpose === 'maskable')).toBe(true)
    for (const i of m.icons) {
      expect(existsSync(join(PUBLIC, i.src)), i.src).toBe(true)
      if (i.type === 'image/png') {
        const png = readFileSync(join(PUBLIC, i.src))
        const [l, h] = i.sizes.split('x').map(Number)
        expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([l, h])
      }
    }
  })

  it('index.html cite le manifeste en relatif ; la CSP autorise service worker et manifeste du site seul', () => {
    expect(INDEX).toContain('<link rel="manifest" href="./manifest.webmanifest" />')
    expect(INDEX).toContain("worker-src 'self'")
    expect(INDEX).toContain("manifest-src 'self'")
  })
})

describe('service worker : contenu', () => {
  it('aucune adresse externe, aucun import de script, aucune invite ni notification', () => {
    expect(CODE_SW).not.toMatch(/https?:\/\//)
    expect(CODE_SW).not.toMatch(/importScripts|beforeinstallprompt|showNotification|pushManager|sync\.register/)
    expect(CODE_SW).not.toContain('—')
  })
})

describe('service worker : comportement', () => {
  const ACCUEIL = `<html><head><script type="module" crossorigin src="./assets/index-AAA.js"></script><link rel="stylesheet" href="./assets/index-BBB.css"><link rel="icon" href="./favicon.svg"><link rel="canonical" href="https://exemple.org/x"></head><body><a href="./explorer">x</a></body></html>`
  const prete = () => {
    const sw = demarrerSw()
    Object.assign(sw.etat.pages, {
      [PORTEE]: { corps: ACCUEIL, type: 'text/html' },
      [`${PORTEE}assets/index-AAA.js`]: { corps: 'console.log(1)', type: 'text/javascript' },
      [`${PORTEE}assets/index-BBB.css`]: { corps: 'body{}', type: 'text/css' },
      [`${PORTEE}favicon.svg`]: { corps: '<svg/>', type: 'image/svg+xml' },
      [`${PORTEE}manifest.webmanifest`]: { corps: '{}', type: 'application/manifest+json' },
      [`${PORTEE}explorer/etat/`]: { corps: '<h1>État</h1>', type: 'text/html' },
      [`${PORTEE}data/arbre/racine.json`]: { corps: JSON.stringify({ millesime: 'Exécution 2024', source: 'x', md: 1 }) },
      [`${PORTEE}data/meta.json`]: { corps: JSON.stringify({ millesime: { a: 'LFI 2025', b: 'LFI 2025' } }) },
      [`${PORTEE}data/sans.json`]: { corps: JSON.stringify({ x: 1 }) },
    })
    return sw
  }

  it('installation : précharge la coquille de la construction (accueil, scripts, styles, icône), rien hors du site', async () => {
    const sw = prete()
    await sw.evenement('install')
    expect([...sw.caches.noms.keys()].sort()).toEqual(['ovmi-coquille-abc123', 'ovmi-pages-abc123'])
    const coquille = [...sw.caches.noms.get('ovmi-coquille-abc123')!.entrees.keys()]
    expect(coquille).toEqual(expect.arrayContaining([`${PORTEE}assets/index-AAA.js`, `${PORTEE}assets/index-BBB.css`, `${PORTEE}favicon.svg`, `${PORTEE}manifest.webmanifest`]))
    expect(sw.appels.every((u) => u.startsWith(PORTEE))).toBe(true)
  })

  it('activation : purge les caches des constructions précédentes, garde les autres', async () => {
    const sw = prete()
    await sw.caches.open('ovmi-coquille-ancien')
    await sw.caches.open('ovmi-donnees-ancien')
    await sw.caches.open('autre-site')
    await sw.caches.open('ovmi-coquille-abc123')
    await sw.evenement('activate')
    expect([...sw.caches.noms.keys()].sort()).toEqual(['autre-site', 'ovmi-coquille-abc123'])
  })

  it('coquille en cache d’abord : le fichier haché est resservi sans réseau', async () => {
    const sw = prete()
    expect(await (await sw.demander(`${PORTEE}assets/index-AAA.js`))!.text()).toBe('console.log(1)')
    sw.etat.enLigne = false
    expect(await (await sw.demander(`${PORTEE}assets/index-AAA.js`))!.text()).toBe('console.log(1)')
    const avant = sw.appels.length
    sw.etat.enLigne = true
    await sw.demander(`${PORTEE}assets/index-AAA.js`)
    expect(sw.appels.length).toBe(avant)
  })

  it('n’intercepte ni les autres domaines, ni hors de la portée, ni les envois, ni lui-même', async () => {
    const sw = prete()
    expect(await sw.demander('https://ailleurs.example/data/x.json')).toBeNull()
    expect(await sw.demander(`${ORIGINE}/autre-depot/data/x.json`)).toBeNull()
    expect(await sw.demander(`${PORTEE}data/meta.json`, { methode: 'POST' })).toBeNull()
    expect(await sw.demander(`${PORTEE}sw.js?v=1`)).toBeNull()
  })

  it('données en réseau d’abord : réponse fraîche en ligne, copie enregistrée hors ligne, signalée avec son millésime', async () => {
    const sw = prete()
    const frais = await sw.demander(`${PORTEE}data/arbre/racine.json`)
    expect(frais!.headers.get('x-ovmi-hors-ligne')).toBeNull()
    expect((await frais!.json()).millesime).toBe('Exécution 2024')
    expect(sw.messages).toEqual([])
    // Le réseau a changé (nouvelle publication) : en ligne, c'est la nouvelle version qui est servie.
    sw.etat.pages[`${PORTEE}data/arbre/racine.json`] = { corps: JSON.stringify({ millesime: 'Exécution 2025' }) }
    expect((await (await sw.demander(`${PORTEE}data/arbre/racine.json`))!.json()).millesime).toBe('Exécution 2025')
    sw.etat.enLigne = false
    const copie = await sw.demander(`${PORTEE}data/arbre/racine.json`, { client: 'onglet-7' })
    expect(copie!.headers.get('x-ovmi-hors-ligne')).toBe('1')
    expect((await copie!.json()).millesime).toBe('Exécution 2025')
    expect(sw.messages).toHaveLength(1)
    const { client, data } = sw.messages[0]
    expect(client).toBe('onglet-7')
    expect(data.type).toBe('ovmi-hors-ligne')
    expect(data.avis[0]).toMatchObject({ type: 'donnees', chemin: 'arbre/racine.json', millesime: 'Exécution 2025' })
    expect(Number.isNaN(new Date(data.avis[0].enregistre_le).getTime())).toBe(false)
  })

  it('millésime en objet résumé, absence de millésime dite (null), donnée jamais vue : erreur réseau', async () => {
    const sw = prete()
    await sw.demander(`${PORTEE}data/meta.json`)
    await sw.demander(`${PORTEE}data/sans.json`)
    sw.etat.enLigne = false
    await sw.demander(`${PORTEE}data/meta.json`)
    await sw.demander(`${PORTEE}data/sans.json`)
    expect(sw.messages.map((m) => m.data.avis[0].millesime)).toEqual(['LFI 2025', null])
    await expect(sw.demander(`${PORTEE}data/jamais.json`)).rejects.toThrow()
  })

  it('réseau trop lent : la copie est servie après le délai, et signalée', async () => {
    const sw = prete()
    await sw.demander(`${PORTEE}data/arbre/racine.json`)
    sw.etat.lent = true
    vi.useFakeTimers()
    const p = sw.demander(`${PORTEE}data/arbre/racine.json`, { sansAttendre: true })
    await vi.advanceTimersByTimeAsync(7000)
    const r = await p
    expect(r!.headers.get('x-ovmi-hors-ligne')).toBe('1')
    expect((await r!.json()).millesime).toBe('Exécution 2024')
    expect(sw.messages).toHaveLength(1)
  })

  it('page déjà vue relue hors ligne (paramètres ignorés), signalée à son onglet ; page jamais vue : avis de repli', async () => {
    const sw = prete()
    const vue = await naviguer(sw, `${PORTEE}explorer/etat/?annee=2024`)
    expect(await vue!.text()).toBe('<h1>État</h1>')
    sw.etat.enLigne = false
    const copie = await naviguer(sw, `${PORTEE}explorer/etat/?annee=2023`, 'onglet-2')
    expect(await copie!.text()).toBe('<h1>État</h1>')
    expect(sw.messages.at(-1)).toMatchObject({ client: 'onglet-2', data: { avis: [{ type: 'page', url: `${PORTEE}explorer/etat/` }] } })
    const jamais = await naviguer(sw, `${PORTEE}local/`)
    expect(jamais!.status).toBe(503)
    const texte = await jamais!.text()
    expect(texte).toContain('Pas de connexion')
    expect(texte).toContain(`href="/Ou-vont-mes-impots/"`)
    expect(jamais!.headers.get('content-security-policy')).toContain("default-src 'none'")
  })

  it('page redirigée (dossier sans barre finale) : réponse rendue utilisable par une navigation', async () => {
    const sw = prete()
    sw.etat.pages[`${PORTEE}explorer`] = { corps: '<h1>Explorer</h1>', type: 'text/html', redirige: true }
    const r = await naviguer(sw, `${PORTEE}explorer`)
    expect(r!.redirected).toBe(false)
    expect(await r!.text()).toBe('<h1>Explorer</h1>')
  })

  it('l’onglet demande l’état : les copies déjà servies lui sont redites', async () => {
    const sw = prete()
    await naviguer(sw, `${PORTEE}explorer/etat/`)
    sw.etat.enLigne = false
    await naviguer(sw, `${PORTEE}explorer/etat/`, 'onglet-3')
    const recu: any[] = []
    await sw.evenement('message', { data: { type: 'ovmi-etat' }, source: { id: 'onglet-3', postMessage: (d: any) => recu.push(d) } })
    expect(recu).toHaveLength(1)
    expect(recu[0].avis[0]).toMatchObject({ type: 'page' })
  })

  it('première visite : la page fait retenir ce qu’elle a déjà chargé (même site seulement)', async () => {
    const sw = prete()
    await sw.evenement('message', {
      data: { type: 'ovmi-retenir', adresses: [`${PORTEE}explorer/etat/?a=1`, `${PORTEE}data/meta.json`, `${PORTEE}assets/index-AAA.js`, 'https://ailleurs.example/x.js', 42] },
      source: { id: 'onglet-1', postMessage() {} },
    })
    expect([...sw.caches.noms.get('ovmi-pages-abc123')!.entrees.keys()]).toEqual([`${PORTEE}explorer/etat/`])
    expect([...sw.caches.noms.get('ovmi-donnees-abc123')!.entrees.keys()]).toEqual([`${PORTEE}data/meta.json`])
    expect(sw.appels.some((u) => u.includes('ailleurs'))).toBe(false)
  })

  it('caches versionnés par construction', async () => {
    const sw = demarrerSw('v2')
    sw.etat.pages[`${PORTEE}data/meta.json`] = { corps: '{}' }
    await sw.demander(`${PORTEE}data/meta.json`)
    expect([...sw.caches.noms.keys()]).toEqual(['ovmi-donnees-v2'])
  })
})

describe('page : branchement et avis', () => {
  const doc = () => {
    const w = new Window({ url: `${PORTEE}explorer/etat/` })
    w.document.write(INDEX.replace('<script type="module" src="./src/main.ts"></script>', ''))
    return w.document as unknown as Document
  }

  it('version de construction : stable pour les mêmes fichiers, différente sinon, « dev » sans construction', () => {
    const d = doc()
    expect(versionDuSite(d)).toBe('dev')
    const ajouter = (src: string) => {
      const s = d.createElement('script')
      s.setAttribute('src', src)
      d.head.append(s)
    }
    ajouter('../../assets/index-AAA.js')
    const v1 = versionDuSite(d)
    expect(v1).toMatch(/^[0-9a-f]{8}$/)
    const d2 = doc()
    const s2 = d2.createElement('script')
    s2.setAttribute('src', './assets/index-AAA.js')
    d2.head.append(s2)
    expect(versionDuSite(d2)).toBe(v1)
    ajouter('../../assets/index-CCC.css')
    expect(versionDuSite(d)).not.toBe(v1)
  })

  it('avis : date de la copie et millésime de chaque donnée, sous l’en-tête, sans toucher au contenu', () => {
    const d = doc()
    const main = d.getElementById('contenu')!
    const avant = main.innerHTML
    const boite = afficherAvis(
      [
        { type: 'page', url: 'p', enregistre_le: '2026-11-16T10:00:00Z' },
        { type: 'donnees', url: 'a', chemin: 'arbre/racine.json', enregistre_le: '2026-11-17T10:00:00Z', millesime: 'Exécution 2024' },
        { type: 'donnees', url: 'b', chemin: 'meta.json', enregistre_le: '2026-11-17T10:00:00Z', millesime: 'Exécution 2024' },
        { type: 'donnees', url: 'c', chemin: 'x.json', enregistre_le: null, millesime: null },
      ],
      d,
    )!
    expect(boite.previousElementSibling?.matches('header.entete')).toBe(true)
    expect(main.innerHTML).toBe(avant)
    const t = boite.textContent!.replace(/\s+/g, ' ')
    expect(boite.querySelector('[role="status"].avertissement')).not.toBeNull()
    expect(t).toContain('Pas de connexion')
    expect(t).toContain('16 novembre 2026')
    expect(t).toContain('Millésime des données enregistrées : Exécution 2024.')
    expect(t).toContain('1 fichier sans millésime indiqué.')
    expect(t).not.toContain('—')
    // Mise à jour en place : un seul avis.
    afficherAvis([{ type: 'donnees', url: 'd', enregistre_le: null, millesime: 'LFI 2025' }], d)
    expect(d.querySelectorAll('#avis-hors-ligne').length).toBe(1)
    expect(afficherAvis([], d)).toBeNull()
  })

  it('texte : millésimes uniques, dates illisibles ignorées', () => {
    expect(texteAvis([{ type: 'donnees', url: 'a', enregistre_le: 'n’importe', millesime: '2024' }])).toEqual({ date: null, millesimes: ['2024'], sansMillesime: 0 })
    expect(dateEnLettres('2026-03-01T12:00:00Z')).toBe('1er mars 2026')
    expect(dateEnLettres(null)).toBeNull()
  })

  it('sans service worker, refusé ou en erreur : rien ne casse', async () => {
    vi.stubGlobal('location', { href: `${PORTEE}explorer/etat/` })
    const d = doc()
    expect(brancherHorsLigne('../../', d, {} as Navigator)).toBe(false)
    const refus = { serviceWorker: { register: () => Promise.reject(new Error('refusé')), addEventListener() {}, ready: new Promise(() => {}) } }
    expect(brancherHorsLigne('../../', d, refus as unknown as Navigator)).toBe(true)
    const casse = { serviceWorker: { register: () => { throw new Error('SecurityError') }, addEventListener() {} } }
    expect(brancherHorsLigne('../../', d, casse as unknown as Navigator)).toBe(false)
    await new Promise((r) => setTimeout(r, 10))
  })

  it('enregistrement relatif à la racine du site (GitHub Pages), portée = racine, avis reçus affichés', async () => {
    vi.stubGlobal('location', { href: `${PORTEE}explorer/etat/` })
    const d = doc()
    const a = d.createElement('script')
    a.setAttribute('src', '../../assets/index-AAA.js')
    d.head.append(a)
    const appels: [string, { scope: string }][] = []
    const envois: any[] = []
    let ecouteur: ((e: any) => void) | null = null
    const actif = { postMessage: (m: any) => envois.push(m) }
    const nav = {
      serviceWorker: {
        register: async (u: string, o: { scope: string }) => (appels.push([u, o]), {}),
        ready: Promise.resolve({ active: actif }),
        controller: { postMessage: (m: any) => envois.push(m) },
        addEventListener: (_: string, f: (e: any) => void) => (ecouteur = f),
        startMessages() {},
      },
    }
    expect(brancherHorsLigne('../../', d, nav as unknown as Navigator)).toBe(true)
    await new Promise((r) => setTimeout(r, 10))
    expect(appels).toEqual([[`${PORTEE}sw.js?v=${versionDuSite(d)}`, { scope: '/Ou-vont-mes-impots/' }]])
    expect(envois[0]).toEqual({ type: 'ovmi-etat' })
    expect(envois[1].type).toBe('ovmi-retenir')
    expect(envois[1].adresses[0]).toBe(`${PORTEE}explorer/etat/`)
    ecouteur!({ data: { type: 'ovmi-hors-ligne', avis: [{ type: 'donnees', url: 'x', enregistre_le: '2026-11-16T10:00:00Z', millesime: 'LFI 2025' }] } })
    ecouteur!({ data: { type: 'autre' } })
    expect(d.getElementById('avis-hors-ligne')?.textContent).toContain('LFI 2025')
  })
})

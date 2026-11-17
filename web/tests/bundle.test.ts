// Échoue si le site construit (dist/) contient un appel réseau vers un domaine externe
// (fetch, XMLHttpRequest, WebSocket, sendBeacon, polices ou scripts tiers).
import { execSync } from 'node:child_process'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { gzipSync } from 'node:zlib'
import { beforeAll, describe, expect, it } from 'vitest'

const RACINE = process.cwd()
const DIST = join(RACINE, 'dist')

function fichiers(d: string): string[] {
  return readdirSync(d).flatMap((n) => {
    const p = join(d, n)
    if (n === 'data') return []
    return statSync(p).isDirectory() ? fichiers(p) : [p]
  })
}

/** Appels réseau vers une URL absolue repérés dans un code JavaScript. */
export function appelsExternes(code: string): string[] {
  const motifs = [
    /fetch\(\s*["'`](?:https?:)?\/\/[^"'`]*/g,
    /\.open\(\s*["'`][A-Z]+["'`]\s*,\s*["'`](?:https?:)?\/\/[^"'`]*/g,
    /new\s+WebSocket\(/g,
    /new\s+EventSource\(\s*["'`](?:https?:)?\/\//g,
    /sendBeacon\(/g,
    /importScripts\(\s*["'`](?:https?:)?\/\//g,
    /api\.fr\.openfisca\.org/g,
    /fonts\.(?:googleapis|gstatic)\.com/g,
  ]
  return motifs.flatMap((m) => code.match(m) ?? [])
}

beforeAll(() => {
  if (!existsSync(join(DIST, 'index.html'))) execSync('npx vite build', { cwd: RACINE, stdio: 'ignore' })
}, 300000)

describe('bundle', () => {
  it('le détecteur repère bien un appel externe (contrôle du test)', () => {
    expect(appelsExternes('a=fetch("https://exemple.org/x")')).toHaveLength(1)
    expect(appelsExternes("x.open('GET','//cdn.exemple.org/y')")).toHaveLength(1)
    expect(appelsExternes('fetch("data/meta.json");fetch(u)')).toHaveLength(0)
  })

  it('aucun appel fetch (ni XHR, WebSocket, beacon) vers un domaine externe', () => {
    const js = fichiers(DIST).filter((f) => f.endsWith('.js'))
    expect(js.length).toBeGreaterThan(3)
    for (const f of js) expect(appelsExternes(readFileSync(f, 'utf8')), f).toEqual([])
    // Le seul module qui appelle fetch est le lecteur de données du site (chemins data/).
    const avecFetch = js.filter((f) => /\bfetch\(/.test(readFileSync(f, 'utf8')))
    for (const f of avecFetch) expect(readFileSync(f, 'utf8'), f).toContain('data/')
  })

  it('HTML et CSS ne chargent rien depuis un autre domaine ; CSP stricte présente', () => {
    const html = readFileSync(join(DIST, 'index.html'), 'utf8')
    expect(html).toContain("default-src 'self'")
    expect(html).not.toMatch(/(?:src|href)=["'](?:https?:)?\/\//)
    for (const f of fichiers(DIST).filter((x) => x.endsWith('.css'))) expect(readFileSync(f, 'utf8')).not.toMatch(/url\(\s*["']?(?:https?:)?\/\//)
  })

  it('premier écran léger : moins de 200 Ko de JS compressé hors ECharts et moteur différé', () => {
    const html = readFileSync(join(DIST, 'index.html'), 'utf8')
    const entree = /src="\.\/(assets\/index-[^"]+\.js)"/.exec(html)![1]
    const code = readFileSync(join(DIST, entree), 'utf8')
    // Entrée + écran d'accueil et ses dépendances statiques.
    const lies = fichiers(join(DIST, 'assets')).filter((f) => f.endsWith('.js') && !/echarts|moteur/.test(f))
    const total = [code, ...lies.map((f) => readFileSync(f, 'utf8'))].reduce((s, c) => s + gzipSync(c).length, 0)
    expect(total).toBeLessThan(200 * 1024)
  })
})

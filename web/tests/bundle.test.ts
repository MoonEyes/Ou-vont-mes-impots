// Échoue si le site construit (dist/) contient un appel réseau vers un domaine externe
// (fetch, XMLHttpRequest, WebSocket, sendBeacon, polices ou scripts tiers).
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { gzipSync } from 'node:zlib'
import { beforeAll, describe, expect, it } from 'vitest'
import { assurerSite } from './construire'

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
  assurerSite()
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
    // Le lien canonique et les balises Open Graph nomment l'adresse publique du site : rien n'y est chargé.
    // Seule exception : le lien de navigation « Signaler une erreur » (balise <a>, rien n'est chargé) vers le
    // formulaire de ticket du dépôt public ; tout autre lien ou ressource externe reste refusé.
    const SIGNALER = /<a class="signaler-lien" href="https:\/\/github\.com\/MoonEyes\/Ou-vont-mes-impots\/issues\/new\?[^"]*"(?: rel="noopener noreferrer")?>/g
    const chargements = html.replace(/<link rel="canonical"[^>]*>/g, '').replace(SIGNALER, '')
    expect(chargements).not.toMatch(/(?:src|href)=["'](?:https?:)?\/\//)
    expect(html).not.toMatch(/<script[^>]+src=["'](?:https?:)?\/\//)
    for (const f of fichiers(DIST).filter((x) => x.endsWith('.css'))) expect(readFileSync(f, 'utf8')).not.toMatch(/url\(\s*["']?(?:https?:)?\/\//)
  })

  it('premier écran léger : moins de 200 Ko de JS compressé hors ECharts et moteur différé', () => {
    const html = readFileSync(join(DIST, 'index.html'), 'utf8')
    const entree = /src="\.\/(assets\/index-[^"]+\.js)"/.exec(html)![1]
    // Entrée + écran d'accueil et leurs dépendances statiques (import … from "./x.js"), hors ECharts et moteur différé.
    // Les autres écrans sont chargés à la demande (import()) : chacun a son propre budget, plus bas.
    const ASSETS = join(DIST, 'assets')
    const accueil = readdirSync(ASSETS).find((f) => /^accueil-[\w-]+\.js$/.test(f))!
    expect(accueil).toBeTruthy()
    const vus = new Set<string>()
    const pile = [entree.replace(/^assets\//, ''), accueil]
    while (pile.length) {
      const f = pile.pop()!
      if (vus.has(f)) continue
      vus.add(f)
      for (const m of readFileSync(join(ASSETS, f), 'utf8').matchAll(/import\s*(?:[^'"()]*?from\s*)?["']\.\/([^"']+\.js)["']/g)) if (!/echarts|moteur/.test(m[1])) pile.push(m[1])
    }
    const total = [...vus].reduce((s, f) => s + gzipSync(readFileSync(join(ASSETS, f))).length, 0)
    expect(total).toBeLessThan(200 * 1024)
  })

  it('chaque module chargé à la demande (écran, composant) reste sous 40 Ko compressés, hors ECharts et moteur', () => {
    for (const f of fichiers(join(DIST, 'assets')).filter((x) => x.endsWith('.js') && !/echarts|moteur/.test(x))) {
      expect(gzipSync(readFileSync(f)).length, f).toBeLessThan(40 * 1024)
    }
  })
})

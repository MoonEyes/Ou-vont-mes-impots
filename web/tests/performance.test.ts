// @vitest-environment happy-dom
// Poids du prérendu (docs/PERF.md, « Budgets du prérendu ») : la carte de France en trame n'est plus recopiée dans les
// 2 352 pages département et commune. Le fond est un fichier SVG partagé (src/composants/trame-france.svg), seul le
// département de la page est écrit dans le HTML. Vérifie le fichier, l'encadré « Où c'est » et les budgets mesurés
// sur le site construit (dist/prerendu.json et pages réelles).
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { gzipSync } from 'node:zlib'
import { beforeAll, describe, expect, it } from 'vitest'
import { ID_TRAME_FRANCE, ouCest, trame, trameFranceSvg } from '../src/composants/trame'
import { assurerSite } from './construire'

const RACINE = process.cwd()
const DIST = join(RACINE, 'dist')
const FICHIER = join(RACINE, 'src', 'composants', 'trame-france.svg')

/**
 * Budgets (octets), docs/PERF.md : mesure du 19/11/2026 plus 10 %. Avant la trame partagée 99,3 Mo de HTML ; avant
 * l'allègement des pages locales 69,9 Mo ; 46,3 Mo avant l'allègement du 19/11 (blancs, données structurées, encadré
 * « Signaler » posé par le script sur les pages locales) ; après 39,4 Mo (commune 15,7 Ko au plus, 4,7 Ko transférés ;
 * département 27,1 Ko au plus ; 15 360 fichiers dans dist/, 13 155 après le regroupement des tranches de revenus
 * par département du 19/11). Un nouveau bloc des pages commune ou département se rend
 * dans le navigateur (DETAIL_COMMUNE, DETAIL_DEPARTEMENT), le HTML prérendu n'en garde qu'une ligne.
 */
const BUDGET = {
  html_total: 43.3e6,
  page_commune: 17.2e3,
  page_commune_gzip: 5.2e3,
  page_departement: 29.8e3,
  fichiers_dist: 14470,
  encadre_ou_cest: 1500,
  fond_partage: 12e3,
}

const dom = (html: string) => {
  const d = document.createElement('div')
  d.innerHTML = html
  return d
}

describe('trame partagée', () => {
  it('le fichier versionné est celui que produit le code (régénérer avec trameFranceSvg() si la grille change)', () => {
    expect(readFileSync(FICHIER, 'utf8')).toBe(trameFranceSvg())
  })

  it('fond : 101 carrés numérotés, sans couleur ni police écrites, sans script ni appel externe', () => {
    const svg = readFileSync(FICHIER, 'utf8')
    expect(svg.length).toBeLessThan(BUDGET.fond_partage)
    expect(svg.match(/<rect /g)).toHaveLength(101)
    expect(svg.match(/<text /g)).toHaveLength(101)
    expect(svg).toContain(`id="${ID_TRAME_FRANCE}"`)
    expect(svg).not.toMatch(/<script|href=|style=|font-family|#[0-9a-f]{3,6}\b/i)
    for (const code of ['2A', '2B', '75', '971', '976']) expect(svg).toContain(`>${code}</text>`)
  })

  it('« Où c’est » : fond partagé par <use>, un seul lien (le département de la page), texte de légende et lien vers la carte complète', () => {
    const html = ouCest('69', 'Rhône')
    expect(html.length).toBeLessThan(BUDGET.encadre_ou_cest)
    const d = dom(html)
    expect(d.querySelector('use')?.getAttribute('href')).toMatch(new RegExp(`trame-france\\.svg#${ID_TRAME_FRANCE}$`))
    expect(d.querySelector('use')?.getAttribute('aria-hidden')).toBe('true')
    expect(d.querySelectorAll('.trame a')).toHaveLength(1)
    const ici = d.querySelector('.trame a.t-ici')!
    expect(ici.getAttribute('aria-label')).toBe('69 Rhône')
    expect(ici.getAttribute('aria-current')).toBe('true')
    expect(ici.getAttribute('href')).toBe('#/local/departement?dep=69&page=rhone')
    expect(d.querySelector('svg')?.getAttribute('aria-label')).toContain('Le département 69 est mis en avant')
    expect(d.querySelector('.legende-trame')?.textContent).toBe('Ton département : Rhône (69)')
    expect(d.querySelector('.aide a[href="#/local"]')).not.toBeNull()
  })

  it('même place que dans la carte complète, outre-mer compris', () => {
    for (const code of ['62', '2A', '974']) {
      const seul = dom(ouCest(code, 'x')).querySelector('a.t-ici rect')!
      const complet = dom(trame(code)).querySelector('a.t-ici rect')!
      expect([seul.getAttribute('x'), seul.getAttribute('y')]).toEqual([complet.getAttribute('x'), complet.getAttribute('y')])
    }
  })

  it('la carte complète (page Chez moi) garde un lien par département', () => {
    expect(dom(trame()).querySelectorAll('.trame a')).toHaveLength(101)
  })
})

describe('budgets du site construit', () => {
  let bilan: { octets_pages: number; octets_page_commune_max: number; octets_page_departement_max: number; pages_communes: number }
  beforeAll(() => {
    assurerSite()
    bilan = JSON.parse(readFileSync(join(DIST, 'prerendu.json'), 'utf8'))
  }, 600000)

  it('nombre de fichiers et poids de dist sous leur budget et sous les limites de l’hébergement (20 000 fichiers par version, 1 Go)', () => {
    // Budget : mesure plus 10 % (limite Cloudflare gratuite : 20 000) ; au-delà, regrouper les petits fichiers de
    // données (docs/PERF.md, « Nombre de fichiers »).
    const tout = { n: 0, octets: 0 }
    const parcourir = (d: string) => {
      for (const e of readdirSync(d, { withFileTypes: true })) {
        if (e.isDirectory()) parcourir(join(d, e.name))
        else {
          tout.n++
          tout.octets += statSync(join(d, e.name)).size
        }
      }
    }
    parcourir(DIST)
    expect(tout.n).toBeLessThanOrEqual(BUDGET.fichiers_dist)
    expect(tout.octets).toBeLessThan(1e9)
  })

  it('HTML prérendu et pages département et commune sous leur budget', () => {
    expect(bilan.octets_pages).toBeLessThan(BUDGET.html_total)
    if (bilan.pages_communes) {
      expect(bilan.octets_page_commune_max).toBeLessThan(BUDGET.page_commune)
      expect(bilan.octets_page_departement_max).toBeLessThan(BUDGET.page_departement)
    }
  })

  it('HTML allégé sans changer l’affichage : ni indentation, blancs de <textarea> gardés, « Signaler » posé par le script sur les pages locales', () => {
    const accueil = readFileSync(join(DIST, 'index.html'), 'utf8')
    const etat = readFileSync(join(DIST, 'explorer', 'etat', 'index.html'), 'utf8')
    for (const html of [accueil, etat]) {
      const horsTexte = html.replace(/<textarea\b[\s\S]*?<\/textarea>/g, '')
      expect(horsTexte).not.toMatch(/>\n[ \t]+</)
      expect(horsTexte).not.toMatch(/<\/(?:div|p|li|ul|h2|section|nav)>\s+</)
    }
    // Référence à copier : ses sauts de ligne sont du contenu.
    expect(/<textarea class="signaler-reference"[^>]*>Page : [^<]*\n[^<]*\n/.test(etat)).toBe(true)
    const local = join(DIST, 'local')
    const commune = existsSync(local) ? readdirSync(local).find((n) => /^\d{5}-/.test(n)) : undefined
    if (commune) expect(readFileSync(join(local, commune, 'index.html'), 'utf8')).not.toContain('class="signaler"')
  })

  it('page commune : fond de carte lu dans assets/ (chemin relatif juste), poids transféré sous budget', () => {
    const local = join(DIST, 'local')
    const commune = existsSync(local) ? readdirSync(local).find((n) => /^\d{5}-/.test(n)) : undefined
    if (!commune) return // prérendu sans pages commune (OVMI_PRERENDU_COMMUNES=0)
    const html = readFileSync(join(local, commune, 'index.html'), 'utf8')
    const use = /<use class="t-fond" href="([^"]+)"/.exec(html)?.[1]
    expect(use).toMatch(/^\.\.\/\.\.\/assets\/trame-france-[\w-]+\.svg#trame-france$/)
    expect(existsSync(join(local, commune, use!.split('#')[0]))).toBe(true)
    const carte = /<div class="trame trame-partagee">[\s\S]*?<\/svg><\/div>/.exec(html)![0]
    expect(carte.match(/<rect /g)).toHaveLength(1)
    expect(carte.match(/<a /g)).toHaveLength(1)
    expect(gzipSync(html, { level: 9 }).length).toBeLessThan(BUDGET.page_commune_gzip)
  })
})

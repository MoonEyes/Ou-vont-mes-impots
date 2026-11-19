// Référencement technique avant lancement (docs/AUDIT_SEO.md) : adresse publique centralisée, plan du site complet
// par rapport aux routes, une seule canonique par page, aucune adresse GitHub ni MoonEyes dans le site servi, image
// de partage au bon format, données structurées WebSite (avec SearchAction) et Dataset.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { versChemin } from '../src/chemins'
import { ROUTES } from '../src/routes'
import { assurerSite } from './construire'

const RACINE = process.cwd()
const DIST = join(RACINE, 'dist')
const ADRESSE = JSON.parse(readFileSync(join(RACINE, 'adresse-site.json'), 'utf8')).url as string
const INTERDIT = /github\.(?:com|io)|mooneyes/i
/**
 * Adresses github.com tolérées parce qu'elles ne désignent pas le projet (décision du 19/11/2026 : aucun renvoi vers
 * le dépôt du site) : la source officielle d'un producteur public, citée en texte (pas en lien) sous le chiffre, et un
 * message d'erreur interne de la bibliothèque de calcul modele-social. Toute autre adresse GitHub fait échouer le test.
 */
const TIERCES = ['https://github.com/DITP-pilotage/barometre-resultats', 'https://github.com/betagouv/mon-entreprise/issues/new']
const sansTierces = (texte: string) => TIERCES.reduce((t, u) => t.replaceAll(u, ''), texte)

let site = ''
let pages: { chemin: string; html: string }[] = []
let bilan: { pages_departements: number; pages_communes: number; copie_secours: boolean; image_partage: string }

function fichiers(d: string, garder: (n: string) => boolean): string[] {
  return readdirSync(d).flatMap((n) => {
    const p = join(d, n)
    if (n === 'data') return []
    return statSync(p).isDirectory() ? fichiers(p, garder) : garder(n) ? [p] : []
  })
}

beforeAll(() => {
  assurerSite()
  bilan = JSON.parse(readFileSync(join(DIST, 'prerendu.json'), 'utf8'))
  site = (bilan as unknown as { site: string }).site
  pages = fichiers(DIST, (n) => n === 'index.html').map((f) => {
    const dossier = relative(DIST, join(f, '..')).split('\\').join('/')
    return { chemin: dossier ? dossier + '/' : '', html: readFileSync(f, 'utf8') }
  })
}, 600000)

describe('adresse publique', () => {
  it('une seule source (adresse-site.json) : https, barre finale, ni GitHub ni MoonEyes', () => {
    expect(ADRESSE).toMatch(/^https:\/\/[a-z0-9.-]+\/(?:[^\s]*\/)?$/)
    expect(ADRESSE).not.toMatch(INTERDIT)
    // Le build de vérification n'a pas d'OVMI_URL_SITE : le site construit porte l'adresse du fichier.
    if (!process.env.OVMI_URL_SITE) expect(site).toBe(ADRESSE)
  })

  it('aucune adresse écrite en dur ailleurs : index.html et le code passent par la constante', () => {
    const index = readFileSync(join(RACINE, 'index.html'), 'utf8')
    expect(index).not.toMatch(INTERDIT)
    expect(index).not.toContain(new URL(ADRESSE).host)
    const sources = fichiers(join(RACINE, 'src'), (n) => /\.(ts|css)$/.test(n))
    for (const f of sources) expect(readFileSync(f, 'utf8'), f).not.toContain(new URL(ADRESSE).host)
  })
})

describe('pages construites', () => {
  it('une seule balise canonique, un seul titre, une seule description, lang="fr", pas de hreflang', () => {
    for (const p of pages) {
      const canoniques = [...p.html.matchAll(/<link rel="canonical" href="([^"]*)"/g)].map((m) => m[1].replace(/&amp;/g, '&'))
      expect(canoniques, p.chemin).toEqual([site + p.chemin])
      expect(p.html.match(/<title>/g), p.chemin).toHaveLength(1)
      expect(p.html.match(/<meta name="description"/g), p.chemin).toHaveLength(1)
      expect(p.html.match(/<h1\b/g), p.chemin).toHaveLength(1)
      expect(p.html.startsWith('<!doctype html>\n<html lang="fr"'), p.chemin).toBe(true)
      expect(p.html.includes('hreflang'), p.chemin).toBe(false)
    }
  })

  it('aucune adresse ni mention GitHub ou MoonEyes dans les pages, le plan du site, robots.txt, le manifeste et le code servi', () => {
    for (const p of pages) {
      expect(INTERDIT.exec(sansTierces(p.html))?.[0], p.chemin).toBeUndefined()
      // Même une source tierce n'est jamais un lien cliquable vers GitHub.
      expect(/<a\b[^>]*href="[^"]*github/i.test(p.html), p.chemin).toBe(false)
    }
    const autres = [join(DIST, '404.html'), join(DIST, 'sitemap.xml'), join(DIST, 'robots.txt'), join(DIST, 'manifest.webmanifest'), ...fichiers(join(DIST, 'assets'), (n) => /\.(js|css|svg)$/.test(n))]
    for (const f of autres) {
      if (!existsSync(f)) continue
      const texte = sansTierces(readFileSync(f, 'utf8'))
      // Les mentions légales nomment l'hébergeur de la copie de secours (« GitHub, Inc. ») : un nom, pas une adresse.
      expect(/https?:\/\/[^\s"'<>]*(?:github|mooneyes)/i.exec(texte)?.[0], f).toBeUndefined()
      expect(/mooneyes/i.exec(texte)?.[0], f).toBeUndefined()
    }
  })

  it('Open Graph : image de partage 1200 x 630 au format PNG, la même adresse sur chaque page, texte de remplacement', () => {
    const png = readFileSync(join(DIST, 'og.png'))
    expect(png.toString('latin1', 1, 4)).toBe('PNG')
    expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([1200, 630])
    expect(png.length).toBeLessThan(300e3)
    expect(['générée au build', 'fichier versionné']).toContain(bilan.image_partage)
    for (const p of pages) {
      expect(p.html, p.chemin).toContain(`<meta property="og:image" content="${site}og.png" />`)
      expect(p.html, p.chemin).toMatch(/<meta property="og:image:alt" content="[^"]{20,}" \/>/)
      expect(p.html, p.chemin).toContain('<meta property="og:locale" content="fr_FR" />')
    }
  })

  it('données structurées : WebSite avec recherche interne (SearchAction) et Dataset identifié sur l’accueil', () => {
    const accueil = pages.find((p) => p.chemin === '')!
    const graphe = JSON.parse(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/.exec(accueil.html)![1])['@graph'] as Record<string, any>[]
    const siteLd = graphe.find((x) => x['@type'] === 'WebSite')!
    expect(siteLd.inLanguage).toBe('fr')
    const action = siteLd.potentialAction
    expect(action['@type']).toBe('SearchAction')
    expect(action['query-input']).toBe('required name=search_term_string')
    expect(action.target.urlTemplate).toBe(`${site}${versChemin('#/recherche?q=')}{search_term_string}`)
    // La cible est la page de recherche du site (prérendue, non indexée : une page de résultats n'a pas de contenu propre).
    expect(pages.some((p) => p.chemin === versChemin('#/recherche'))).toBe(true)
    const jeu = graphe.find((x) => x['@type'] === 'Dataset')!
    expect(jeu['@id']).toBe(`${site}#donnees`)
    expect(jeu.isAccessibleForFree).toBe(true)
    expect(jeu.license).toMatch(/^https:\/\//)
  })
})

describe('plan du site', () => {
  it('XML valide : espace de noms, adresses absolues de l’adresse principale, sans doublon, sous les limites du protocole', () => {
    const xml = readFileSync(join(DIST, 'sitemap.xml'), 'utf8')
    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')).toBe(true)
    expect(xml.trimEnd().endsWith('</urlset>')).toBe(true)
    // Seules balises admises, chaque <url> fermée, aucun caractère & non échappé.
    expect(xml.replace(/<\?xml[^>]*\?>/, '').match(/<\/?([a-z]+)/g)!.every((b) => /^<\/?(urlset|url|loc|lastmod)$/.test(b))).toBe(true)
    expect((xml.match(/<url>/g) ?? []).length).toBe((xml.match(/<\/url>/g) ?? []).length)
    expect(/&(?!amp;|lt;|gt;|quot;|apos;)/.test(xml)).toBe(false)
    const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1].replace(/&amp;/g, '&'))
    expect(new Set(locs).size).toBe(locs.length)
    expect(locs.length).toBeLessThanOrEqual(50000)
    expect(Buffer.byteLength(xml)).toBeLessThan(50 * 1024 * 1024)
    for (const l of locs) expect(l.startsWith(site) && !l.includes('#') && !l.includes('?'), l).toBe(true)
    expect(readFileSync(join(DIST, 'robots.txt'), 'utf8')).toContain(`Sitemap: ${site}sitemap.xml`)
  })

  it('complet par rapport aux routes : chaque route indexable, chaque département et commune prérendus, aucune page sans index', () => {
    const xml = readFileSync(join(DIST, 'sitemap.xml'), 'utf8')
    const locs = new Set([...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1].replace(/&amp;/g, '&')))
    for (const r of ROUTES) {
      const url = site + versChemin('#' + r.chemin).split('?')[0]
      expect(locs.has(url), r.chemin).toBe(!r.sansIndex)
    }
    const locales = [...locs].filter((l) => l.startsWith(site + 'local/') && /^local\/[0-9AB]{2,5}-/.test(l.slice(site.length)))
    expect(locales.length).toBe(bilan.pages_departements + bilan.pages_communes)
    // Inversement, toute adresse du plan a sa page, sans noindex.
    for (const l of locs) {
      const p = pages.find((x) => site + x.chemin === l)
      expect(p, l).toBeTruthy()
      expect(p!.html.includes('noindex'), l).toBe(false)
    }
  })
})

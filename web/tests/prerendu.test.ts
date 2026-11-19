// Prérendu (scripts/prerendre.mjs) : chaque route a sa page HTML avec un titre, une description et une adresse
// canonique uniques ; le plan du site liste exactement les pages indexables ; rien n'est chargé d'un autre domaine.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { versChemin } from '../src/chemins'
import { ROUTES } from '../src/routes'
import { descriptionPage, titreDocument } from '../src/routeur'
import { assurerSite } from './construire'

const RACINE = process.cwd()
const DIST = join(RACINE, 'dist')

interface Page {
  chemin: string
  html: string
  titre: string
  description: string
  canonique: string
  indexable: boolean
}
let pages: Page[] = []
let site = ''
let bilan: { pages: number; pages_communes: number; pages_departements: number; fichiers_dist: number; limite_fichiers: number; date_donnees: string | null }

const balise = (html: string, re: RegExp) => (re.exec(html)?.[1] ?? '').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>')

function fichiersHtml(d: string): string[] {
  return readdirSync(d).flatMap((n) => {
    const p = join(d, n)
    if (n === 'data' || n === 'assets') return []
    return statSync(p).isDirectory() ? fichiersHtml(p) : n === 'index.html' ? [p] : []
  })
}
const compter = (d: string): number => readdirSync(d).reduce((s, n) => s + (statSync(join(d, n)).isDirectory() ? compter(join(d, n)) : 1), 0)

beforeAll(() => {
  // En intégration continue, « npm run build » a déjà tout produit ; sinon (clone propre) on copie les données et on construit.
  assurerSite()
  bilan = JSON.parse(readFileSync(join(DIST, 'prerendu.json'), 'utf8'))
  site = JSON.parse(readFileSync(join(DIST, 'prerendu.json'), 'utf8')).site
  pages = fichiersHtml(DIST).map((f) => {
    const html = readFileSync(f, 'utf8')
    const dossier = relative(DIST, join(f, '..')).split('\\').join('/')
    return {
      chemin: dossier ? dossier + '/' : '',
      html,
      titre: balise(html, /<title>([\s\S]*?)<\/title>/),
      description: balise(html, /<meta name="description" content="([^"]*)"/),
      canonique: balise(html, /<link rel="canonical" href="([^"]*)"/),
      indexable: !/<meta name="robots" content="noindex/.test(html),
    }
  })
}, 600000)

const page = (chemin: string) => pages.find((p) => p.chemin === chemin)!
const contenu = (p: Page) => /<main id="contenu"[^>]*>([\s\S]*)<\/main>/.exec(p.html)![1]
const texte = (p: Page) => contenu(p).replace(/<[^>]+>/g, ' ').replace(/&nbsp;|\u00a0|\u202f/g, ' ').replace(/\s+/g, ' ')

describe('prérendu', () => {
  it('nom du site : l’ancien nom « Où vont mes impôts » absent de toutes les pages prérendues et des fichiers publics, sauf la phrase de non-affiliation', () => {
    const NON_AFFILIATION = 'Le billet découpé est sans lien avec le site ouvontmesimpots.fr.'
    const ANCIEN_NOM = /o[uù]\s+vont\s+mes\s+imp[oô]ts/i
    // Seule exception tolérée : le producteur écrit par pipeline/formation.py dans site/data/formation/cpf_organismes.json
    // (donnée publiée, hors web/), à renommer par le pipeline formation ; à retirer d'ici dès que la donnée est régénérée.
    const DONNEE_FORMATION = 'projet Où vont mes impôts (calcul du pipeline)'
    const avecPhrase: string[] = []
    for (const p of pages) {
      const html = p.html.replace(/&nbsp;|\u00a0|\u202f/g, ' ')
      if (html.includes(NON_AFFILIATION)) avecPhrase.push(p.chemin)
      const exceptions = p.chemin === 'explorer/formation-professionnelle/' ? [NON_AFFILIATION, DONNEE_FORMATION] : [NON_AFFILIATION]
      expect(exceptions.reduce((x, e) => x.split(e).join(' '), html), p.chemin || '/').not.toMatch(ANCIEN_NOM)
      expect(p.titre.endsWith(' · Le billet découpé') || p.titre.startsWith('Le billet découpé') || !p.titre.includes('·'), p.chemin).toBe(true)
    }
    for (const f of ['manifest.webmanifest', 'sw.js', '404.html']) {
      if (existsSync(join(DIST, f))) expect(readFileSync(join(DIST, f), 'utf8'), f).not.toMatch(ANCIEN_NOM)
    }
    const manifeste = JSON.parse(readFileSync(join(DIST, 'manifest.webmanifest'), 'utf8'))
    expect([manifeste.name, manifeste.short_name]).toEqual(['Le billet découpé', 'Billet découpé'])
    expect(page('').html).toContain('"name":"Le billet découpé"')
    // Une seule fois sur le site : la page des mentions légales.
    expect(avecPhrase).toEqual(['mentions/'])
  })

  it('chaque route a sa page HTML, avec le titre et la description de src/metadonnees.ts', () => {
    for (const r of ROUTES) {
      const p = page(versChemin('#' + r.chemin))
      expect(p, r.chemin).toBeTruthy()
      expect(p.titre, r.chemin).toBe(titreDocument(r))
      expect(p.description, r.chemin).toBe(descriptionPage(r))
      expect(p.indexable, r.chemin).toBe(!r.sansIndex)
      expect(/<h1[ >]/.test(contenu(p)), `${r.chemin} : pas de h1`).toBe(true)
      expect(contenu(p).includes('class="erreur"'), `${r.chemin} : page en erreur`).toBe(false)
      expect(contenu(p).includes('Chargement…'), `${r.chemin} : section restée en attente`).toBe(false)
    }
    expect(existsSync(join(DIST, 'explorer', 'etat', 'index.html'))).toBe(true)
  })

  it('titre, description et adresse canonique : présents et uniques sur toutes les pages', () => {
    expect(pages.length).toBe(bilan.pages)
    for (const [nom, lire] of [['titre', (p: Page) => p.titre], ['description', (p: Page) => p.description], ['canonique', (p: Page) => p.canonique]] as const) {
      const vus = new Map<string, string>()
      for (const p of pages) {
        const v = lire(p)
        expect(v, `${p.chemin} : ${nom} vide`).not.toBe('')
        expect(vus.get(v), `${nom} en double : « ${v} » (${p.chemin})`).toBeUndefined()
        vus.set(v, p.chemin)
      }
    }
    for (const p of pages) {
      expect(p.canonique).toBe(site + p.chemin)
      expect(balise(p.html, /<meta property="og:url" content="([^"]*)"/)).toBe(p.canonique)
      expect(balise(p.html, /<meta property="og:title" content="([^"]*)"/)).toBe(p.titre)
      expect(balise(p.html, /<meta property="og:description" content="([^"]*)"/)).toBe(p.description)
      // Carte X/Twitter : seule twitter:card est écrite, titre, description et image sont repris d'Open Graph.
      expect(p.html.includes('<meta name="twitter:card" content="summary_large_image" />'), p.chemin).toBe(true)
    }
  })

  it('liens en vrais chemins relatifs, tous résolus vers une page ou un fichier du site', () => {
    for (const p of pages) {
      const prefixe = p.chemin ? '../'.repeat(p.chemin.split('/').filter(Boolean).length) : './'
      expect(/<html lang="fr" data-racine="([^"]*)"/.exec(p.html)?.[1], p.chemin).toBe(prefixe)
      expect(/href="#\//.test(p.html), `${p.chemin} : lien en fragment`).toBe(false)
      expect(/href=""/.test(p.html), `${p.chemin} : lien vide`).toBe(false)
      for (const m of p.html.matchAll(/<(?:a|link|script)\b[^>]*?(?:href|src)="([^"#][^"]*)"/g)) {
        const cible = m[1].replace(/&amp;/g, '&')
        if (/^[a-z]+:/i.test(cible)) continue
        expect(cible.startsWith('/'), `${p.chemin} : chemin absolu ${cible}`).toBe(false)
        const fichier = join(DIST, p.chemin, cible.split('?')[0])
        expect(existsSync(fichier.endsWith('/') || !/\.[a-z0-9]+$/i.test(fichier) ? join(fichier, 'index.html') : fichier), `${p.chemin} : ${cible} introuvable`).toBe(true)
      }
    }
  })

  it('CSP stricte conservée : ni style en ligne, ni script en ligne, ni ressource d’un autre domaine', () => {
    for (const p of pages) {
      expect(p.html.includes("default-src 'self'; script-src 'self'; style-src 'self'"), p.chemin).toBe(true)
      expect(/<[^>]+\sstyle="/.test(p.html), `${p.chemin} : attribut style`).toBe(false)
      expect(/<[^>]+\son[a-z]+="/.test(p.html), `${p.chemin} : gestionnaire en ligne`).toBe(false)
      const scripts = [...p.html.matchAll(/<script\b([^>]*)>/g)].map((m) => m[1])
      expect(scripts.length, p.chemin).toBe(2)
      expect(scripts.filter((s) => !/type="application\/ld\+json"/.test(s) && !/type="module"[^>]*src="(?:\.\.?\/)+assets\//.test(s)), p.chemin).toEqual([])
      const chargements = p.html.replace(/<link rel="canonical"[^>]*>/g, '').replace(/<a\b[^>]*>/g, '')
      expect(/(?:src|href)=["'](?:https?:)?\/\//.test(chargements), `${p.chemin} : ressource externe`).toBe(false)
    }
  })

  it('données structurées : fil d’Ariane sur chaque page, jeu de données enrichi sur l’accueil', () => {
    for (const p of pages) {
      const ld = JSON.parse(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/.exec(p.html)![1])
      const graphe = ld['@graph'] as Record<string, any>[]
      // Le site (WebSite) n'est décrit que sur l'accueil ; ailleurs, le fil d'Ariane seul (docs/PERF.md, 19/11/2026).
      expect(graphe.map((x) => x['@type']), p.chemin).toEqual(p.chemin ? ['BreadcrumbList'] : ['WebSite', 'Dataset'])
      if (!p.chemin) continue
      const fil = graphe.find((x) => x['@type'] === 'BreadcrumbList')!
      expect(fil, p.chemin).toBeTruthy()
      const items = fil.itemListElement as { position: number; name: string; item: string }[]
      expect(items.map((x) => x.position)).toEqual(items.map((_, i) => i + 1))
      expect(items[0].item).toBe(site)
      expect(items[items.length - 1].item, p.chemin).toBe(p.canonique)
      for (const x of items) {
        expect(x.name).not.toBe('')
        expect(pages.some((q) => site + q.chemin === x.item), `${p.chemin} : maillon ${x.item} sans page`).toBe(true)
      }
    }
    const ld = JSON.parse(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/.exec(page('').html)![1])
    const jeu = ld['@graph'].find((x: { '@type': string }) => x['@type'] === 'Dataset')
    expect(jeu.creator.name).toBe('Projet citoyen Le billet découpé')
    expect(jeu.url).toBe(site)
    expect(jeu.spatialCoverage).toEqual({ '@type': 'Place', name: 'France' })
    expect(jeu.dateModified).toBe(bilan.date_donnees)
    expect(jeu.license).toMatch(/licence-ouverte/)
    // Champs repris de docs/datapackage/schemaorg.jsonld (produit par le pipeline), jamais inventés ici.
    const origine = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'datapackage', 'schemaorg.jsonld'), 'utf8'))
    expect(jeu.keywords).toEqual(origine.keywords)
    expect(jeu.temporalCoverage).toBe(origine.temporalCoverage)
    expect(jeu.distribution.length).toBeGreaterThan(3)
    for (const d of jeu.distribution) {
      expect(d['@type']).toBe('DataDownload')
      expect(d.contentUrl.startsWith(site + 'data/')).toBe(true)
      expect(existsSync(join(DIST, d.contentUrl.slice(site.length))), d.contentUrl).toBe(true)
    }
  })

  it('plan du site : exactement les pages indexables, datées par les données ; robots.txt ; 404.html hors plan', () => {
    const xml = readFileSync(join(DIST, 'sitemap.xml'), 'utf8')
    const entrees = [...xml.matchAll(/<url><loc>([^<]+)<\/loc>(?:<lastmod>([^<]+)<\/lastmod>)?<\/url>/g)].map((m) => ({ loc: m[1].replace(/&amp;/g, '&'), lastmod: m[2] }))
    expect(entrees.length).toBe((xml.match(/<url>/g) ?? []).length)
    expect(entrees.map((e) => e.loc).sort()).toEqual(pages.filter((p) => p.indexable).map((p) => p.canonique).sort())
    expect(entrees.length).toBeLessThanOrEqual(50000)
    for (const e of entrees) {
      expect(e.lastmod, e.loc).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      expect(e.lastmod! <= new Date().toISOString().slice(0, 10), e.loc).toBe(true)
    }
    // lastmod = date des données publiées (mise_a_jour.json, sinon meta.json), pas la date du build.
    const source = existsSync(join(DIST, 'data', 'mise_a_jour.json')) ? 'mise_a_jour.json' : 'meta.json'
    const maj = JSON.parse(readFileSync(join(DIST, 'data', source), 'utf8')).genere_le as string
    expect(entrees[0]).toEqual({ loc: site, lastmod: maj.slice(0, 10) })
    for (const r of ROUTES.filter((x) => x.sansIndex)) expect(xml.includes(`<loc>${site}${versChemin('#' + r.chemin)}</loc>`), r.chemin).toBe(false)
    expect(readFileSync(join(DIST, 'robots.txt'), 'utf8')).toBe(`User-agent: *\nAllow: /\n\nSitemap: ${site}sitemap.xml\n`)
    // Page introuvable : servie par l'hébergeur avec le statut 404, à n'importe quelle profondeur (chemins absolus), jamais indexée.
    const introuvable = readFileSync(join(DIST, '404.html'), 'utf8')
    expect(introuvable).toContain('Ce billet-là, on ne le trouve pas')
    expect(introuvable).toContain('<meta name="robots" content="noindex, follow" />')
    const base = new URL(site).pathname
    expect(introuvable).toContain(`data-racine="${base}"`)
    expect(introuvable).not.toMatch(/(?:src|href)="\.\.?\//)
    expect(xml.includes('404.html')).toBe(false)
  })

  it('accueil et pages de recherche : contenu lisible sans JavaScript', () => {
    const accueil = page('')
    expect(texte(accueil).includes('découpé selon où va chaque euro.')).toBe(true)
    // Le billet découpé est dans la page servie, avec ses proportions (SVG en attributs), et les tuiles ont leurs chiffres.
    expect(/<svg class="billet-large"[^>]*role="group"/.test(contenu(accueil))).toBe(true)
    expect(/data-caisse="etat">[\s\S]*?<span class="t-chiffre">\d+ Md€<\/span>/.test(contenu(accueil))).toBe(true)
    expect(/<h2>À quoi servent mes impôts \?<\/h2>/.test(contenu(accueil))).toBe(true)
    expect(/Plus de \d+ sources publiques/.test(texte(accueil))).toBe(true)
    expect(contenu(accueil).includes('href="./calcul/"')).toBe(true)
    expect(page('calcul/').titre).toBe('Combien je verse d’impôts : calcul à partir du salaire')
    expect(/<h1[^>]*>(<span class="picto[^>]*>.*?<\/span>)?Budget de ma commune<\/h1>/.test(contenu(page('local/')))).toBe(true)
    expect(/sur 100 €/i.test(texte(page('explorer/etat/')))).toBe(true)
    expect(page('explorer/etat/').html.includes('data-rubrique="/explorer" aria-current="page"')).toBe(true)
    for (const p of pages) expect(p.html.includes('<noscript>'), p.chemin).toBe(true)
  })

  it('communes et départements : une page chacun, titre de recherche, trois chiffres propres en texte', () => {
    const communes = pages.filter((p) => /^local\/(\d{5}|2[AB]\d{3})-/.test(p.chemin))
    const departements = pages.filter((p) => /^local\/(\d{2,3}|2[AB])-/.test(p.chemin))
    expect(communes.length).toBe(bilan.pages_communes)
    expect(departements.length).toBe(bilan.pages_departements)
    if (!communes.length) return // prérendu lancé sans les communes (OVMI_PRERENDU_COMMUNES=0)
    expect(departements.length).toBe(readdirSync(join(DIST, 'data', 'local', 'geo')).length)
    expect(communes.length).toBeGreaterThan(1500)
    for (const p of communes) {
      expect(p.titre, p.chemin).toMatch(/^Budget (de |d’|du |des ).+ \((\d{2,3}|2[AB])\)( : dépenses(, dotations)?, impôts locaux| · Le billet découpé)?$/)
      const t = texte(p)
      // Population, dépenses totales et dépenses par habitant, ou à défaut dotation ou taux : au moins trois chiffres.
      const chiffres = [/[\d ]+ habitants/, /de dépenses en \d{4}/, /€ par habitant/, /Dette en cours : [\d, ]+/, /DGF totale/, /Taxe foncière bâti/].filter((re) => re.test(t))
      expect(chiffres.length, p.chemin).toBeGreaterThanOrEqual(3)
      expect(/href="\.\.\/\.\.\/local\/(\d{2,3}|2[AB])-[a-z0-9-]+\/"/.test(p.html), `${p.chemin} : lien vers le département`).toBe(true)
    }
    const nantes = page('local/44109-nantes/')
    if (nantes) {
      expect(nantes.titre).toBe('Budget de Nantes (44) : dépenses, dotations, impôts locaux')
      expect(contenu(page('local/44-loire-atlantique/')).includes('href="../../local/44109-nantes/"')).toBe(true)
      // Communes sous le seuil : pas de page propre ; leur liste (vers la page générique, lue avec JavaScript) n'est
      // rendue que dans le navigateur, le HTML prérendu en donne le nombre.
      const dep = contenu(page('local/44-loire-atlantique/'))
      expect(dep.includes('href="../../local/commune/?insee=44001"')).toBe(false)
      expect(/[\d ]+ communes de 5 000 habitants ou moins : leur liste/.test(texte(page('local/44-loire-atlantique/')))).toBe(true)
      expect(/<ul class="cles" aria-label="Chiffres clés de Loire-Atlantique">/.test(dep)).toBe(true)
    }
  })

  it('pages commune allégées : l’essentiel reste dans le HTML, le détail se rend dans le navigateur', () => {
    const communes = pages.filter((p) => /^local\/(\d{5}|2[AB]\d{3})-/.test(p.chemin))
    if (!communes.length) return
    for (const p of communes) {
      const c = contenu(p)
      // Titre, introduction, chiffres clés, budget de la commune et sa source, liens vers les fichiers de données.
      expect(/<h1[ >]/.test(c), p.chemin).toBe(true)
      expect(/<p class="chapeau">[\d\s\u00a0\u202f]+ habitants/.test(c), p.chemin).toBe(true)
      expect(/<p class="source">/.test(c), p.chemin).toBe(true)
      expect(/href="\.\.\/\.\.\/data\/local\/budgets\/communes\/(\d{2,3}|2[AB])\.json"/.test(c), `${p.chemin} : lien vers les données`).toBe(true)
      // Blocs repris d'une page à l'autre (intercommunalité, département, région) et tableaux du détail : absents.
      expect(/Le département&nbsp;:|La région&nbsp;:|<table/.test(c), p.chemin).toBe(false)
      expect(c.includes('s’affichent aussi'), p.chemin).toBe(true)
    }
    const nantes = page('local/44109-nantes/')
    if (nantes) expect(/<ul class="cles" aria-label="Chiffres clés de Nantes">/.test(contenu(nantes))).toBe(true)
  })

  it('nombre de fichiers sous la limite Cloudflare (20 000)', () => {
    const n = compter(DIST)
    expect(n).toBe(bilan.fichiers_dist)
    expect(n).toBeLessThan(bilan.limite_fichiers)
    expect(bilan.limite_fichiers).toBe(20000)
  })
})

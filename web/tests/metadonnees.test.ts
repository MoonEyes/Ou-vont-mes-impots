// Titres et descriptions des pages (src/metadonnees.ts, docs/SEO.md « Titres et descriptions ») : 60 caractères au plus
// pour le titre, 120 à 155 pour la description, uniques, neutres, sur toutes les pages prérendues du site construit.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { DESCRIPTION_MAX, DESCRIPTION_MIN, META_PAGES, TITRE_MAX, ajuster, deCommune, metaCommune, metaDepartement, titreSite } from '../src/metadonnees'
import { ROUTES } from '../src/routes'
import { ROUTE_INTROUVABLE, descriptionPage, titreDocument } from '../src/routeur'
import { assurerSite } from './construire'

const DIST = join(process.cwd(), 'dist')
const LEXIQUE = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as {
  regles: { termes: string[]; raison: string }[]
  niche_definie: string
}
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
const INTERDIT: [RegExp, string][] = LEXIQUE.regles.map((r) => [borne(r.termes.join('|')), r.raison])
const NICHE_DEFINIE = new RegExp(LEXIQUE.niche_definie, 'giu')

function neutre(texte: string, ou: string) {
  for (const [re, raison] of INTERDIT) expect(texte, `${ou} : ${raison}`).not.toMatch(re)
  expect(texte.replace(NICHE_DEFINIE, ' '), `${ou} : « niche » sans définition`).not.toMatch(borne('niches?'))
}

describe('règles des titres et descriptions', () => {
  it('nom du site en suffixe seulement s’il tient dans 60 caractères', () => {
    expect(titreSite('La dette publique')).toBe('La dette publique · Le billet découpé')
    const long = 'Budget de Nantes (44) : dépenses, dotations, impôts locaux'
    expect(titreSite(long)).toBe(long)
    for (const n of [30, 39, 40, 60]) expect(titreSite('x'.repeat(n)).length).toBeLessThanOrEqual(TITRE_MAX)
  })

  it('ajuster : premier candidat dans les bornes, sinon le premier assez court', () => {
    expect(ajuster(['a'.repeat(200), 'b'.repeat(130), 'c'.repeat(125)], 120, 155)).toBe('b'.repeat(130))
    expect(ajuster(['a'.repeat(200), 'b'.repeat(90)], 120, 155)).toBe('b'.repeat(90))
  })

  it('élision et contraction des noms de commune', () => {
    expect(['Nantes', 'Angers', 'Le Mans', 'Les Abymes', 'La Rochelle', 'Évreux'].map(deCommune)).toEqual(['de Nantes', 'd’Angers', 'du Mans', 'des Abymes', 'de La Rochelle', 'd’Évreux'])
  })

  it('commune et département : une seule fonction chacun, terme cherché en tête, longueurs tenues même pour un nom long', () => {
    const nantes = metaCommune('Nantes', '44', 'Loire-Atlantique', 327734)
    expect(nantes.titre).toBe('Budget de Nantes (44) : dépenses, dotations, impôts locaux')
    expect(nantes.description.startsWith('Budget de Nantes (Loire-Atlantique, 327')).toBe(true)
    const long = metaCommune('Saint-Germain-lès-Arpajon-sur-Orge-et-Environs', '91', 'Essonne', 12000)
    expect(long.titre.length).toBeLessThanOrEqual(TITRE_MAX)
    expect(long.description.length).toBeLessThanOrEqual(DESCRIPTION_MAX)
    for (const m of [nantes, metaDepartement('Alpes-de-Haute-Provence', '04', 198), metaDepartement('Ain', '01', 392)]) {
      expect(m.titre.length).toBeLessThanOrEqual(TITRE_MAX)
      expect(m.description.length).toBeGreaterThanOrEqual(DESCRIPTION_MIN)
      expect(m.description.length).toBeLessThanOrEqual(DESCRIPTION_MAX)
    }
    expect(metaDepartement('Rhône', '69', 267).titre).toBe('Rhône (69) : budget des communes et du département')
    expect(metaDepartement('Loire-Atlantique', '44', 207).titre).toBe('Loire-Atlantique (44) : budget des communes')
  })

  it('chaque route (et la page introuvable) a son titre et sa description dans src/metadonnees.ts, dans les bornes', () => {
    for (const r of [...ROUTES, ROUTE_INTROUVABLE]) {
      expect(META_PAGES[r.chemin], `${r.chemin} absent de META_PAGES`).toBeTruthy()
      if (r.chemin !== '/') expect(META_PAGES[r.chemin].titre, r.chemin).toBeTruthy()
      expect(titreDocument(r).length, r.chemin).toBeLessThanOrEqual(TITRE_MAX)
      expect(descriptionPage(r).length, r.chemin).toBeGreaterThanOrEqual(DESCRIPTION_MIN)
      expect(descriptionPage(r).length, r.chemin).toBeLessThanOrEqual(DESCRIPTION_MAX)
      neutre(titreDocument(r), `${r.chemin} (titre)`)
      neutre(descriptionPage(r), `${r.chemin} (description)`)
    }
    expect(Object.keys(META_PAGES).filter((c) => c !== ROUTE_INTROUVABLE.chemin && !ROUTES.some((r) => r.chemin === c))).toEqual([])
  })
})

describe('toutes les pages prérendues', () => {
  let pages: { chemin: string; titre: string; description: string }[] = []
  const lire = (html: string, re: RegExp) =>
    (re.exec(html)?.[1] ?? '').replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#39;/g, "'").replace(/&amp;/g, '&')
  beforeAll(() => {
    assurerSite()
    const fichiers = (d: string): string[] =>
      readdirSync(d).flatMap((n) => {
        const p = join(d, n)
        if (n === 'data' || n === 'assets') return []
        return statSync(p).isDirectory() ? fichiers(p) : n === 'index.html' || n === '404.html' ? [p] : []
      })
    pages = fichiers(DIST).map((f) => {
      const html = readFileSync(f, 'utf8')
      return { chemin: relative(DIST, f), titre: lire(html, /<title>([\s\S]*?)<\/title>/), description: lire(html, /<meta name="description" content="([^"]*)"/) }
    })
  }, 600000)

  it('titre de 60 caractères au plus, description de 120 à 155', () => {
    expect(pages.length).toBeGreaterThan(ROUTES.length)
    const hors = pages.filter((p) => !p.titre || p.titre.length > TITRE_MAX || p.description.length < DESCRIPTION_MIN || p.description.length > DESCRIPTION_MAX)
    expect(hors.slice(0, 10).map((p) => `${p.chemin} : ${p.titre.length} / ${p.description.length}`)).toEqual([])
  })

  it('titres et descriptions uniques', () => {
    for (const cle of ['titre', 'description'] as const) {
      const vus = new Map<string, string>()
      const doublons: string[] = []
      for (const p of pages) {
        if (vus.has(p[cle])) doublons.push(`${p.chemin} et ${vus.get(p[cle])} : « ${p[cle]} »`)
        vus.set(p[cle], p.chemin)
      }
      expect(doublons.slice(0, 10), cle).toEqual([])
    }
  })

  it('formulation neutre (lexique partagé) sur chaque titre et chaque description', () => {
    for (const p of pages) neutre(`${p.titre} ${p.description}`, p.chemin)
  })
})

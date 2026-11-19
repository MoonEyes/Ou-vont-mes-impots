// @vitest-environment happy-dom
// Encadrés « donnée non publiée à la source » (src/composants/manque.ts) : un seul composant, utilisé partout ;
// chaque encadré dit ce qui manque, pourquoi, depuis quand et renvoie à la source ; aucun ne porte de jugement
// (lexique partagé docs/lexique_neutre.json et mots de reproche propres à un constat de non-publication).
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { monterPage } from './aide-dom'
import { ROUTES } from '../src/routes'
import { afficher } from '../src/routeur'
import { encadreManque, MANQUES, type Manque } from '../src/composants/manque'

const RACINE = process.cwd()
const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[] }
/** Reproches possibles dans un constat de non-publication : le site constate, il ne reproche pas. */
const REPROCHES = [
  'refus\\w*',
  'opacit\\w*',
  'transparen\\w*',
  'manquement\\w*',
  'défaillan\\w*',
  'négligen\\w*',
  'retard\\w*',
  'devrai(?:t|ent)',
  'aurai(?:t|ent) dû',
  'ne respecte\\w* pas',
  'malgré',
  'pourtant',
  'regrett\\w*',
  'cach\\w+',
  'dissimul\\w*',
  'obligation\\w*',
  'illégal\\w*',
  'toujours pas',
  'encore et toujours',
]
const motifs = [...LEXIQUE.regles.flatMap((r) => r.termes), ...REPROCHES].map((t) => new RegExp(`(?<![\\p{L}\\p{N}])(?:${t})(?![\\p{L}\\p{N}])`, 'iu'))
const jugements = (t: string) => motifs.filter((m) => m.test(t)).map((m) => m.source)
const texte = (el: Element | null) => el?.textContent?.replace(/\s+/g, ' ').trim() ?? ''

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  const page = await afficher(ROUTES, main, fragment)
  return page
}

/** Tous les cas connus, avec des valeurs du type de celles que donnent les données. */
const CAS: [string, Manque][] = [
  ['Sénat', MANQUES.senatScrutins('19/11/2026')],
  ['cotisations', MANQUES.cotisationsDecret()],
  ['délibérations', MANQUES.deliberations('Lécousse', { date_releve: '2026-11-18', absence: 'ne publie pas ses délibérations en données ouvertes', absence_detail: 'aucun jeu trouvé sur data.gouv.fr le 2026-11-18', couverture: { commune: { publient: 1145, total: 34875 } } })],
  ['fonds européens', MANQUES.fondsEuropeensCommunes({ region: 'Occitanie', listes: [{ autorite_de_gestion: 'Région Bretagne', collecte_le: '2026-11-18' }], inaccessible: { url: 'https://www.europe-en-france.gouv.fr/fr', constat: 'vérification anti-robot' } })],
  ['départements', MANQUES.departementFonctions('Loire-Atlantique', 'Comptes 2025')],
]

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
  // Données des écrans concernés : jeux de test de qui_a_vote et fonds_europeens, puis jeu commun.
  const F = join(RACINE, 'tests', 'fixtures')
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url).split('?')[0]
    const f = [join(F, 'qui_a_vote', u), join(F, 'fonds_europeens', u), join(F, u)].find((x) => existsSync(x))
    if (!f) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })
})

describe('composant encadreManque', () => {
  it('chaque cas connu : quoi, pourquoi, depuis, source (lien https), sans jugement', () => {
    for (const [nom, m] of CAS) {
      for (const champ of [m.quoi, m.pourquoi, m.depuis, m.source.libelle]) expect(champ.trim().length, nom).toBeGreaterThan(10)
      expect(m.source.url, nom).toMatch(/^https:\/\//)
      const d = document.createElement('div')
      d.innerHTML = encadreManque(m)
      const aside = d.querySelector('aside.manque[role="note"]')!
      expect(Array.from(aside.querySelectorAll('dt')).map(texte), nom).toEqual(['Ce qui manque', 'Pourquoi', 'Depuis', 'Source'])
      expect(aside.querySelector('a')?.getAttribute('href')).toBe(m.source.url)
      expect(jugements(texte(aside)), `${nom} : ${texte(aside)}`).toEqual([])
      // Pas de point d'exclamation ni de majuscules d'insistance.
      expect(texte(aside)).not.toMatch(/!|\b[A-ZÉ]{5,}\b/)
    }
  })

  it('dates : relevés écrits en toutes lettres, jamais une date vide', () => {
    expect(MANQUES.senatScrutins('19/11/2026').depuis).toContain('19 novembre 2026')
    expect(MANQUES.deliberations('X', { date_releve: '2026-11-18' }).depuis).toContain('18 novembre 2026')
    expect(MANQUES.senatScrutins(null).depuis).toContain('date non publiée')
  })

  it('un seul composant : aucun écran ne fabrique son propre encadré « manque »', () => {
    const dossiers = ['ecrans', 'composants'].map((d) => join(RACINE, 'src', d))
    for (const dossier of dossiers)
      for (const f of readdirSync(dossier).filter((x) => x.endsWith('.ts') && x !== 'manque.ts')) {
        const c = readFileSync(join(dossier, f), 'utf8')
        expect(c, f).not.toMatch(/class="manque[ "]/)
      }
  })
})

describe('encadrés à l’écran, sur les cas connus', () => {
  it('Qui a voté tes impôts : votes nominatifs du Sénat et cotisations fixées par décret', async () => {
    await ecran('#/decisions/qui-a-vote')
    const encadres = Array.from(main.querySelectorAll('aside.manque'))
    const textes = encadres.map(texte)
    expect(textes.some((t) => t.includes('Le Sénat ne publie pas ses scrutins nominatifs en données ouvertes'))).toBe(true)
    expect(textes.some((t) => t.includes('fixés pour l’essentiel par décret'))).toBe(true)
    for (const t of textes) expect(jugements(t), t).toEqual([])
  })

  it('Fonds européens : listes d’opérations par commune hors listes reprises', async () => {
    await ecran('#/explorer/fonds-europeens')
    const t = Array.from(main.querySelectorAll('aside.manque')).map(texte).join(' ')
    expect(t).toContain('avec la commune de chaque opération')
    expect(t).toContain('pour les régions dont la liste n’est pas reprise')
    expect(jugements(t)).toEqual([])
  })
})

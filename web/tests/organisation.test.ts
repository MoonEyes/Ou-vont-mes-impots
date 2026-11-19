// @vitest-environment happy-dom
// Écran « Une organisation dans toutes les sources » (/beneficiaires/organisation) sur des extraits réels de
// site/data/entites (tests/fixtures/organisation/, servis avant les fixtures communes) : recherche par nom et par
// SIREN, fiche source par source, montants tels que publiés avec statut et source, sommes marquées « calculé par le
// site », rapprochements probables à part, aucune somme toutes sources, lexique neutre, accessibilité.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { picto } from '../src/composants/pictos'
import { viderCache } from '../src/donnees'
import { chercher, fichierFiche, fichiersMot, montantPublie, REGLE_LIGNES, REGLE_RESULTATS, sirenSaisi, type Fiche, type Index } from '../src/ecrans/organisation'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { attendreQue, monterPage } from './aide-dom'

const RACINE = process.cwd()
const PROPRES = join(RACINE, 'tests', 'fixtures', 'organisation')
const COMMUNES = join(RACINE, 'tests', 'fixtures')
const PAGE = '#/beneficiaires/organisation'
const SIREN = '228500013'
const lire = (rel: string) => JSON.parse(readFileSync(join(PROPRES, 'data', rel), 'utf8'))
const n = (t: string | null | undefined) => (t ?? '').replace(/\s+/g, ' ').trim()
const INDEX = lire('entites/index.json') as Index
const FICHE = (lire('entites/fiches/228.json') as { fiches: Record<string, Fiche> }).fiches[SIREN]

const requetes: string[] = []
let absents: RegExp | null = null
let main: HTMLElement

function servir() {
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const rel = u.split('?')[0]
    if (absents?.test(rel)) return new Response('introuvable', { status: 404 })
    for (const base of [PROPRES, COMMUNES]) {
      const f = join(base, rel)
      if (existsSync(f)) return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    return new Response('introuvable', { status: 404 })
  })
}

async function ecran(fragment = PAGE) {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => n(main.textContent)

// Lexique neutre partagé (docs/lexique_neutre.json), même lecture que tests/ecrans.test.ts.
const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; niche_definie: string; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function verifierLexique(t: string, ou: string) {
  let x = t.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
  expect(x.replace(new RegExp(LEXIQUE.niche_definie, 'giu'), ' '), `${ou} : « niche » sans définition`).not.toMatch(borne('niches?'))
}

function accessibilite() {
  expect(main.querySelectorAll('h1')).toHaveLength(1)
  for (const t of Array.from(main.querySelectorAll('table'))) {
    expect(n(t.querySelector('caption')?.textContent).length, 'légende de tableau').toBeGreaterThan(5)
    for (const th of Array.from(t.querySelectorAll('thead th'))) expect(th.getAttribute('scope')).toBe('col')
    for (const th of Array.from(t.querySelectorAll('tbody th'))) expect(th.getAttribute('scope')).toBe('row')
  }
  expect(main.querySelectorAll('.surligne')).toHaveLength(1)
  // Bloc « Signaler une erreur » (routeur) : texte seul, aucun lien ; aucun lien externe hors des sources.
  for (const a of Array.from(main.querySelectorAll('a[href]'))) {
    const href = a.getAttribute('href')!
    expect(href.startsWith('#/') || href.startsWith('data/') || href.startsWith('https://www.ccomptes.fr/'), href).toBe(true)
  }
}

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu') as HTMLElement
})
afterEach(() => {
  absents = null
  viderCache()
})

describe('écran organisation', () => {
  it('route : sous « Qui reçoit l’argent », thème qui reçoit, picto et voisins existants, libellés neutres', () => {
    const r = ROUTES.find((x) => x.chemin === '/beneficiaires/organisation')!
    expect(r.parent).toBe('/beneficiaires')
    expect(r.theme).toBe('qui-recoit')
    expect(picto(r.picto ?? '')).not.toBe('')
    expect(r.voisins?.length).toBeGreaterThan(0)
    for (const v of r.voisins ?? []) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    expect(r.description.length).toBeGreaterThanOrEqual(70)
    expect(r.description.length).toBeLessThanOrEqual(200)
    expect(`${r.titrePage} · Le billet découpé`.length).toBeLessThanOrEqual(100)
    expect(`${r.titre} ${r.titrePage} ${r.description}`).not.toMatch(/\b(LFI|PLF|DECP|ANR|HATVP)\b/)
    verifierLexique(`${r.titre} ${r.titrePage} ${r.description} ${r.resume}`, 'route')
  })

  it('page de recherche : phrase d’introduction, chiffre clé lu dans l’index, sources reliées, méthode', async () => {
    await ecran()
    expect(n(main.querySelector('h1')?.textContent)).toBe('Une organisation dans toutes les sources')
    expect(texte()).toContain('Elle ne fait pas de total toutes sources confondues')
    expect(n(main.querySelector('.surligne')?.textContent)).toBe(n(new Intl.NumberFormat('fr-FR').format(INDEX.comptes.organisations_avec_fiche)))
    const lignes = main.querySelectorAll('#org-canaux tbody tr')
    expect(lignes).toHaveLength(INDEX.canaux.length)
    expect(main.querySelector('label[for="org-q"]')).not.toBeNull()
    expect(main.querySelector('a[href="#/explorer/secu"]')).not.toBeNull()
    expect(texte()).toContain(n(INDEX.avertissement))
    accessibilite()
    verifierLexique(main.textContent ?? '', 'recherche')
  })

  it('recherche par nom : résultats d’après le fichier du mot, ordre écrit, lien vers la fiche, aucun appel externe', async () => {
    await ecran()
    const champ = main.querySelector<HTMLInputElement>('#org-q')!
    champ.value = 'vendée département'
    main.querySelector<HTMLFormElement>('#org-form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => !!main.querySelector('#org-liste'))
    const liens = Array.from(main.querySelectorAll<HTMLAnchorElement>('#org-liste a')).map((a) => [n(a.textContent), a.getAttribute('href')])
    expect(liens).toContainEqual(['DEPARTEMENT DE VENDEE', `${PAGE}?siren=${SIREN}`])
    expect(n(main.querySelector('#org-resultats [data-regle-ordre]')?.textContent)).toBe(REGLE_RESULTATS)
    const noms = liens.map((l) => l[0] as string)
    expect([...noms].sort((a, b) => a.localeCompare(b, 'fr'))).toEqual(noms)
    expect(requetes.some((u) => u.endsWith('data/entites/recherche/ve.json'))).toBe(true)
    expect(requetes.every((u) => !/^[a-z]+:/i.test(u))).toBe(true)
  })

  it('fonctions : SIREN saisi, fichier de fiche, fichiers d’un mot, mots trop courants', async () => {
    expect(sirenSaisi('228 500 013')).toBe(SIREN)
    expect(sirenSaisi('22850001300017')).toBe(SIREN)
    expect(sirenSaisi('2285')).toBeNull()
    expect(fichierFiche(INDEX, SIREN)).toBe('entites/fiches/228.json')
    expect(fichiersMot(INDEX, 'vendee')).toEqual(['entites/recherche/ve.json'])
    expect(montantPublie(15000)).toMatch(/^15\s000 €$/)
    const frequent = INDEX.fichiers.mots_frequents[0]?.mot
    if (frequent) {
      const r = await chercher(INDEX, frequent)
      expect(r.resultats).toHaveLength(0)
      expect(r.message).toContain('ajoute un autre mot')
    }
  })

  it('fiche : montants tels que publiés, statut et source pour chaque ligne, sommes du site marquées, aucune somme toutes sources', async () => {
    await ecran(`${PAGE}?siren=${SIREN}`)
    expect(n(main.querySelector('h1')?.textContent)).toBe(FICHE.denomination)
    expect(texte()).toContain('228 500 013')
    expect(n(main.querySelector('.surligne')?.textContent)).toBe(`${FICHE.canaux.length} sources`)
    // Chaque bloc reçu : un tableau par source, autant de lignes que de valeurs publiées, montant et statut.
    FICHE.recoit.forEach((b, i) => {
      const t = main.querySelector(`#org-bloc-${i}`)!
      expect(t, b.canal).not.toBeNull()
      const valeurs = b.series.flatMap((s) => s.valeurs)
      const lignes = Array.from(main.querySelectorAll(`#org-bloc-${i} tbody tr`))
      expect(lignes.length).toBe(Math.min(valeurs.length, 25))
      for (const tr of lignes) expect(tr.querySelector('.badge')).not.toBeNull()
      const premier = valeurs[0]
      if (premier[1] !== null) expect(n(lignes[0].querySelectorAll('td')[0].textContent)).toBe(n(montantPublie(premier[1])))
      expect(n(t.closest('section')?.querySelector('.source')?.textContent)).toContain(INDEX.canaux.find((c) => c.id === b.canal)!.titre)
    })
    // Sommes calculées par le site : seulement celles publiées dans la fiche, avec badge et méthode.
    const sommes = FICHE.recoit.flatMap((b) => b.sommes_par_annee ?? [])
    expect(sommes.length).toBeGreaterThan(0)
    const lignesSommes = Array.from(main.querySelectorAll('table.org-sommes tbody tr'))
    expect(lignesSommes).toHaveLength(sommes.length)
    for (const tr of lignesSommes) expect(n(tr.querySelector('[data-calcule]')?.textContent)).toBe('Calculé par le site')
    expect(main.querySelector('[data-sans-somme]')).not.toBeNull()
    expect(n(main.querySelector('[data-regle-ordre]')?.textContent)).toBe(REGLE_LIGNES)
    // Aucun total toutes sources : la somme de tous les montants reçus n'est écrite nulle part.
    const tout = FICHE.recoit.flatMap((b) => b.series.flatMap((s) => s.valeurs.map((v) => v[1] ?? 0))).reduce((a, x) => a + x, 0)
    expect(texte()).not.toContain(n(montantPublie(Math.round(tout * 100) / 100)))
    // Liens vers la page source quand elle existe, renvoi aux sommes versées aux ménages.
    expect(main.querySelector('a[href="#/explorer/fonds-europeens?liste=paysdelaloire"]')).not.toBeNull()
    expect(main.querySelector('a[href="#/explorer/secu"]')).not.toBeNull()
    accessibilite()
    verifierLexique(main.textContent ?? '', 'fiche')
  })

  it('fiche : rapprochements probables affichés à part, avec score, sans fusion', async () => {
    await ecran(`${PAGE}?siren=${SIREN}`)
    const p = FICHE.probables ?? []
    expect(p.length).toBeGreaterThan(0)
    const lignes = main.querySelectorAll('#org-probables tbody tr')
    expect(lignes).toHaveLength(p.length)
    expect(n(main.querySelector('[data-probables]')?.textContent)).toContain('ni fusionnées')
    expect(n(lignes[0].textContent)).toContain(p[0].nom_publie)
    expect(n(lignes[0].textContent)).toContain(p[0].score.toFixed(2).replace('.', ','))
    expect(lignes[0].querySelector('.badge')?.textContent).toBe('Approché')
  })

  it('SIREN sans fiche et index absent : messages propres, sans erreur', async () => {
    await ecran(`${PAGE}?siren=999999999`)
    expect(main.querySelector('[data-sans-fiche]')).not.toBeNull()
    absents = /entites\/index\.json$/
    viderCache()
    await ecran()
    expect(texte()).toContain('ne sont pas encore publiées')
  })
})

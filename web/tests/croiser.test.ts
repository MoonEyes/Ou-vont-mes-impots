// @vitest-environment happy-dom
// Écran « Comparer des communes qui se ressemblent » (/local/croiser) sur des extraits réels de site/data/typologies
// (tests/fixtures/croiser/data/, valeurs non modifiées ; l'index porte en plus un croisement « intrus » absent de la
// liste fermée de l'écran) : liste fermée, avertissement, mêmes axes, vue d'ensemble et vue par case, repères,
// petites communes, absence de coefficient et de droite, données absentes, aucune requête externe.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { picto } from '../src/composants/pictos'
import { viderCache } from '../src/donnees'
import { AVERTISSEMENT, CROISEMENTS_AFFICHABLES, croisementsAffiches, TITRE, valeur } from '../src/ecrans/croiser'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { monterPage } from './aide-dom'

const RACINE = process.cwd()
const MES_FIXTURES = join(RACINE, 'tests', 'fixtures', 'croiser')
const lire = (f: string) => JSON.parse(readFileSync(join(MES_FIXTURES, 'data', f), 'utf8'))
const IDX = lire('typologies/index.json')
const CR = lire('typologies/croisements/depenses_niveau_vie_2023.json')
const C44 = lire('typologies/communes/44.json')

const requetes: string[] = []
let absents: RegExp | null = null
let main: HTMLElement

function servir() {
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const f = join(MES_FIXTURES, u.split('?')[0])
    if (absents?.test(u) || !existsSync(f)) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}
const ecran = async (fragment: string) => {
  viderCache()
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''

const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; niche_definie: string; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function verifierLexique(t: string, ou: string) {
  let x = t.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
}

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu') as HTMLElement
})
afterAll(() => {
  vi.unstubAllGlobals()
})

describe('écran des territoires comparables', () => {
  it('route : parent /local, voisins, famille et picto existants', () => {
    const r = ROUTES.find((x) => x.chemin === '/local/croiser')!
    expect(r).toBeTruthy()
    expect(r.parent).toBe('/local')
    expect(r.theme).toBe('territoires')
    expect(picto(r.picto!)).not.toBe('')
    expect(r.titre).toBe(TITRE)
    for (const v of r.voisins!) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    expect(r.description.length).toBeGreaterThanOrEqual(70)
    expect(r.description.length).toBeLessThanOrEqual(200)
    verifierLexique(`${r.titre} ${r.titrePage} ${r.description} ${r.resume}`, 'route')
  })

  it('seuls les croisements prédéfinis sont affichés, même si l’index en annonce un autre', async () => {
    expect(IDX.croisements.some((c: { id: string }) => c.id === 'intrus_2023')).toBe(true)
    const ids = croisementsAffiches(IDX).map((c) => c.id)
    expect(ids).not.toContain('intrus_2023')
    expect(ids.every((id) => (CROISEMENTS_AFFICHABLES as readonly string[]).includes(id))).toBe(true)
    expect(CROISEMENTS_AFFICHABLES.length).toBeGreaterThanOrEqual(6)
    expect(CROISEMENTS_AFFICHABLES.length).toBeLessThanOrEqual(14)
    await ecran('#/local/croiser?c=intrus_2023')
    expect(texte()).not.toContain('intrus')
    expect(requetes.some((u) => u.includes('intrus'))).toBe(false)
    const menu = main.querySelector('nav[aria-label="Paires de chiffres"]')!
    const titres = Array.from(menu.querySelectorAll('li')).map((li) => li.textContent?.trim())
    expect(titres).toEqual(croisementsAffiches(IDX).map((c) => c.titre))
    // retour au premier croisement de la liste fermée
    expect(main.querySelector('#croiser-titre')?.textContent).toBe(CR.titre)
  })

  it('avertissement fixe et visible, vue d’ensemble à côté de la vue par case, mêmes axes, sans droite ni coefficient', async () => {
    await ecran('#/local/croiser?c=depenses_niveau_vie_2023&f=strate')
    expect(main.querySelector('h1')?.textContent).toBe(TITRE)
    const av = main.querySelector('#croiser-avertissement')!
    expect(av.textContent?.trim()).toBe(AVERTISSEMENT)
    expect(AVERTISSEMENT).toContain('ne dit pas que l’un explique l’autre')
    expect(AVERTISSEMENT).toContain('moyennes de communes, pas d’habitants')
    const grilles = main.querySelectorAll('.croiser-grille')
    expect(grilles).toHaveLength(2)
    expect(grilles[0].querySelector('figcaption')?.textContent).toContain('Toutes les communes')
    expect(grilles[1].querySelectorAll('figure')).toHaveLength(IDX.facettes.strate.cases.length)
    const vues = Array.from(main.querySelectorAll('svg.croiser-svg'))
    expect(new Set(vues.map((s) => s.getAttribute('viewBox'))).size).toBe(1)
    for (const s of vues) expect(s.getAttribute('aria-label')).toBeTruthy()
    // aucune droite d'ajustement, aucun coefficient
    expect(main.querySelectorAll('svg polyline, svg .croiser-droite')).toHaveLength(0)
    expect(texte()).not.toMatch(/coefficient|corrélation|régression|r²/i)
    // badge « calculé par le site » et méthode à côté
    expect(Array.from(main.querySelectorAll('.badge')).some((b) => b.textContent === 'Calculé par le site')).toBe(true)
    expect(texte()).toContain(CR.methode)
    // tableau accessible
    const table = main.querySelector('table')!
    expect(table.querySelector('caption')?.textContent).toContain('dispersion par case')
    expect(table.querySelectorAll('th[scope=col]').length).toBeGreaterThan(3)
    expect(table.querySelectorAll('tbody th[scope=row]')).toHaveLength(IDX.facettes.strate.cases.length + 1)
    verifierLexique(texte(), 'page')
  })

  it('ta commune est repérée dans chaque case, pleine dans la sienne ; ses deux chiffres avec leur année', async () => {
    await ecran('#/local/croiser?c=depenses_niveau_vie_2023&f=densite&insee=44109')
    const l = C44.communes['44109']
    const ix = C44.colonnes.indexOf(CR.x.variable)
    const iy = C44.colonnes.indexOf(CR.y.variable)
    expect(texte()).toContain(`${CR.y.libelle} (2023) : ${valeur(l.v[iy], CR.y.unite)}`.replace(/\s+/g, ' '))
    expect(texte()).toContain(`${CR.x.libelle} (2023) : ${valeur(l.v[ix], CR.x.unite)}`.replace(/\s+/g, ' '))
    const cases = main.querySelectorAll('.croiser-grille')[1].querySelectorAll('figure')
    expect(cases).toHaveLength(IDX.facettes.densite.cases.length)
    const propres = main.querySelectorAll('.croiser-case-propre')
    expect(propres).toHaveLength(1)
    expect(propres[0].textContent).toContain(IDX.facettes.densite.cases.find((c: { code: string }) => c.code === l.densite).libelle)
    expect(propres[0].querySelectorAll('.croiser-point')).toHaveLength(1)
    // repère creux dans chacune des autres cases et dans la vue d'ensemble
    expect(main.querySelectorAll('.croiser-point-ailleurs').length).toBe(cases.length - 1)
    expect(main.querySelector('a[href^="#/local/commune?insee=44109"]')).not.toBeNull()
  })

  it('petite commune : la bande de la case est mise en avant plutôt que le point', async () => {
    const [code] = Object.keys(lire('typologies/communes/05.json').communes)
    await ecran(`#/local/croiser?c=depenses_niveau_vie_2023&f=strate&insee=${code}`)
    expect(texte()).toContain('moins de 2 000 habitants')
    expect(texte()).toContain('La bande de sa case en dit plus que son point')
  })

  it('département : ses communes repérées dans leur propre case', async () => {
    await ecran('#/local/croiser?c=dgf_depenses_2024&f=densite&dep=44')
    const n = Object.values(C44.communes as Record<string, { v: (number | null)[] }>).filter((l) => l.v[C44.colonnes.indexOf('dgf_hab_2024')] !== null && l.v[C44.colonnes.indexOf('depenses_totales_hab_2024')] !== null).length
    const grilles = main.querySelectorAll('.croiser-grille')
    expect(grilles[1].querySelectorAll('.croiser-point').length).toBe(n)
    expect(texte()).toContain('Les communes du département 44 sont repérées')
  })

  it('valeur non publiée : null dit en mots, jamais 0', () => {
    expect(valeur(null, 'euros par habitant')).toBe('non publié')
    expect(valeur(0, 'euros par habitant')).toMatch(/^0 €/)
  })

  it('données absentes : la page le dit sans erreur et garde ses sorties ; aucune requête externe', async () => {
    absents = /typologies\//
    await ecran('#/local/croiser')
    expect(main.querySelector('h1')?.textContent).toBe(TITRE)
    expect(main.querySelector('.absent')).not.toBeNull()
    expect(main.querySelector('.erreur')).toBeNull()
    expect(main.querySelector('#croiser-avertissement')).not.toBeNull()
    absents = null
    for (const u of requetes) expect(u).not.toMatch(/^[a-z]+:|^\/\//i)
  })

  it('croisement entre départements : vue d’ensemble et vue par tranche, département repéré, sans droite ni coefficient', async () => {
    await ecran('#/local/croiser?c=aide_sociale_prescriptions_2024&dep=44')
    const t = texte()
    expect(t).toContain('Tous les départements')
    expect(t).toContain('Loire-Atlantique (44)')
    expect(t).toContain(AVERTISSEMENT)
    const grilles = main.querySelectorAll('.croiser-grille')
    expect(grilles).toHaveLength(2)
    expect(grilles[1].querySelectorAll('figure')).toHaveLength(IDX.facettes.strate_departement.cases.length)
    expect(main.querySelectorAll('.croiser-case-propre')).toHaveLength(1)
    expect(main.querySelectorAll('svg polyline, svg .croiser-droite')).toHaveLength(0)
    expect(t).not.toMatch(/coefficient de corrélation|r² =|droite de régression/i)
    verifierLexique(main.textContent ?? '', 'départements')
  })

  it('département hors périmètre : motif en mots, jamais 0', async () => {
    await ecran('#/local/croiser?c=aide_sociale_prescriptions_2024&dep=69')
    const t = texte()
    expect(t).toContain('territoire du département différent')
    expect(main.querySelectorAll('.croiser-point')).toHaveLength(0)
  })

  it('prérendu : les croisements ajoutés ne sont pas dans le HTML statique', () => {
    const ids = croisementsAffiches(IDX, true).map((c) => c.id)
    expect(ids).not.toContain('aide_sociale_prescriptions_2024')
    expect(croisementsAffiches(IDX, false).map((c) => c.id)).toContain('aide_sociale_prescriptions_2024')
  })
})

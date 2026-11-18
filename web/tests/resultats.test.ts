// @vitest-environment happy-dom
// Écran « Ce que l'État s'était fixé et ce qui a été mesuré » (/decisions/resultats), bloc de la fiche programme
// (/beneficiaires/programme) et lien de la page département, sur des extraits réels de site/data/performance
// (tests/fixtures/resultats/data/performance/ : programmes 102 et 141, baromètre du Rhône et de la France).
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { viderCache } from '../src/donnees'
import { depense, mois, publie } from '../src/ecrans/resultats'
import { monterPage } from './aide-dom'

const CHEMIN = '/decisions/resultats'
const FIXTURES = join(process.cwd(), 'tests', 'fixtures')
const PRIVE = join(FIXTURES, 'resultats')
let vide = false
const requetes: string[] = []

function servir() {
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const chemin = u.split('?')[0]
    if (vide && chemin.startsWith('data/performance/')) return new Response('introuvable', { status: 404 })
    const f = [join(PRIVE, chemin), join(FIXTURES, chemin)].find((c) => existsSync(c))
    if (!f) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}

const lire = (rel: string) => JSON.parse(readFileSync(join(PRIVE, 'data', 'performance', rel), 'utf8'))
const idx = lire('index.json')
const p102 = lire('programmes/102.json')
const rhone = lire('barometre/69.json')
const norm = (s: string) => s.replace(/[\s  ]+/g, ' ').trim()

let main: HTMLElement
async function ecran(fragment: string, sansDonnees = false) {
  vide = sansDonnees
  viderCache()
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  await new Promise((r) => setTimeout(r, 30))
  return main
}
const texte = () => norm(main.textContent ?? '')

const LEXIQUE = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function lexiqueNeutre(ou: string) {
  let x = (main.textContent ?? '').replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
  expect(main.textContent, ou).not.toContain('—')
}

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu') as HTMLElement
})

describe('/decisions/resultats', () => {
  it('route déclarée sous « Décisions et contrôle », avec voisins existants', () => {
    const r = ROUTES.find((x) => x.chemin === CHEMIN)!
    expect(r.parent).toBe('/decisions')
    for (const v of r.voisins ?? []) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
  })

  it('accueil : introduction, avertissements, recherche par mission ou programme, départements', async () => {
    await ecran(`#${CHEMIN}`)
    expect(main.querySelector('h1')?.textContent).toContain('Ce que l’État s’était fixé et ce qui a été mesuré')
    expect(texte()).toContain('choisis par les ministères eux-mêmes')
    expect(texte()).toContain('ni un succès ni un échec en soi')
    const items = Array.from(main.querySelectorAll<HTMLElement>('#liste-perf li'))
    expect(items.length).toBe(idx.missions.flatMap((m: any) => m.programmes).length)
    const champ = main.querySelector<HTMLInputElement>('#filtre-perf')!
    const mission = idx.missions.find((m: any) => m.programmes.some((p: any) => p.programme === '102')).mission as string
    champ.value = mission.slice(0, 12)
    champ.dispatchEvent(new Event('input'))
    const visibles = items.filter((li) => !li.hidden)
    expect(visibles.length).toBeGreaterThan(0)
    expect(visibles.every((li) => li.dataset.t!.includes(mission.slice(0, 12).toLowerCase()))).toBe(true)
    champ.value = '141'
    champ.dispatchEvent(new Event('input'))
    expect(items.filter((li) => !li.hidden).map((li) => li.querySelector('a')!.getAttribute('href'))).toEqual([`#${CHEMIN}?p=141`])
    expect(main.querySelector(`a[href="#${CHEMIN}?dep=69"]`)).not.toBeNull()
    expect(main.querySelector('.surligne')).toBeNull()
    lexiqueNeutre('accueil')
  })

  it('programme : crédits dépensés, cible et réalisé côte à côte, année par année, sans écart calculé', async () => {
    await ecran(`#${CHEMIN}?p=102`)
    expect(main.querySelector('h1')?.textContent).toContain(p102.libelle)
    const t = texte()
    expect(t).toContain('ni un succès ni un échec en soi')
    const tables = Array.from(main.querySelectorAll('details table'))
    expect(tables.length).toBeGreaterThan(0)
    const entetes = Array.from(tables[0].querySelectorAll('thead th')).map((x) => x.textContent)
    expect(entetes).toEqual(['Année', 'Crédits dépensés (programme entier)', 'Cible', 'Réalisé', 'Source'])
    // chaque ligne : la dépense constatée de la même année, la cible et le réalisé publiés tels quels
    const s = p102.series[0]
    const credits = new Map(p102.credits.map((c: any) => [c.annee, c]))
    const lignes = Array.from(tables[0].querySelectorAll('tbody tr'))
    expect(lignes.length).toBe(s.lignes.length)
    s.lignes.forEach((l: any, k: number) => {
      const cellules = lignes[k].querySelectorAll('td')
      expect(lignes[k].querySelector('th')!.textContent).toBe(String(l.annee))
      expect(norm(cellules[0].textContent!)).toBe(norm(depense(credits.get(l.annee) as any).replace(/<[^>]+>/g, '')))
      expect(norm(cellules[1].textContent!)).toContain(l.cible_publiee ?? 'non publié')
      expect(norm(cellules[2].textContent!)).toContain(l.realise_publie ?? 'non publié')
    })
    expect(t).not.toMatch(/écart à la cible\s*:/i)
    expect(main.querySelector('.surligne')).toBeNull()
    // crédits : statut tracé ou non publié, jamais 0 € pour une année sans donnée
    expect(main.querySelectorAll('.badge').length).toBeGreaterThan(0)
    if (p102.credits.some((c: any) => c.depense_constatee_eur === null)) expect(t).toContain('non publié')
    expect(t).not.toMatch(/(^|\s)0 €/)
    // correspondance des indicateurs renommés ou absents des documents 2025
    expect(t).toContain('Indicateurs renommés ou absents des documents 2025')
    expect(main.querySelector(`a[href="#/decisions/realisations?p=102"]`)).not.toBeNull()
    for (const tb of Array.from(main.querySelectorAll('table'))) {
      expect(tb.querySelector('caption')?.textContent?.length).toBeGreaterThan(5)
      expect(tb.querySelectorAll('thead th[scope="col"]').length).toBeGreaterThan(1)
    }
    lexiqueNeutre('programme 102')
  })

  it('programme : afficher tous les indicateurs', async () => {
    await ecran(`#${CHEMIN}?p=102`)
    const caches = main.querySelectorAll('details[data-plus][hidden]').length
    expect(caches).toBe(Math.max(0, p102.series.length - 15))
    if (caches) {
      ;(main.querySelector('#plus-perf') as HTMLButtonElement).click()
      expect(main.querySelectorAll('details[data-plus][hidden]').length).toBe(0)
    }
  })

  it('département : valeur initiale, dernière valeur et cible avec leur date, France à côté, aucun taux d’avancement', async () => {
    await ecran(`#${CHEMIN}?dep=69`)
    expect(main.querySelector('h1')?.textContent).toContain(`${rhone.nom} (69)`)
    const t = texte()
    const i = rhone.indicateurs.find((x: any) => x.cibles.length && x.initiale.length)
    const c = i.cibles[i.cibles.length - 1]
    expect(t).toContain(mois(c[0]))
    expect(main.querySelectorAll('tbody th[scope="row"]').length).toBeGreaterThan(rhone.indicateurs.length)
    expect(t).toContain('France')
    expect(t.toLowerCase()).not.toContain('taux d’avancement :')
    expect(main.querySelector(`a[href="#/local/departement?dep=69"]`)).not.toBeNull()
    lexiqueNeutre('département 69')
  })

  it('données absentes : messages propres, aucune erreur', async () => {
    await ecran(`#${CHEMIN}`, true)
    expect(texte()).toContain('en cours d’intégration')
    await ecran(`#${CHEMIN}?p=102`, true)
    expect(texte()).toContain('Pas de données de performance pour le programme 102')
    await ecran(`#${CHEMIN}?dep=69`, true)
    expect(texte()).toContain('Pas de données du baromètre')
  })

  it('formats : non publié jamais 0, mois en toutes lettres', () => {
    expect(publie(undefined, '%')).toContain('non publié')
    expect(publie('12,5', '%')).toContain('%')
    expect(publie('Non déterminé', '%')).not.toContain('%')
    expect(depense(undefined)).toContain('non publié')
    expect(depense({ annee: 2021, vote_lfi_eur: null, depense_constatee_eur: null, source: null, trou: 'Trou 2021', autres_montants_publies: [] })).toContain('non publié')
    expect(mois('2026-12-01')).toBe('décembre 2026')
  })

  it('fiche programme : bloc « Ce que l’État s’était fixé et ce qui a été mesuré » et lien vers la vue complète', async () => {
    await ecran('#/beneficiaires/programme?p=141')
    await new Promise((r) => setTimeout(r, 50))
    const bloc = main.querySelector('#perf-programme')!
    expect(bloc.querySelector('h2')?.textContent).toBe('Ce que l’État s’était fixé et ce qui a été mesuré')
    expect(bloc.querySelector(`a[href="#${CHEMIN}?p=141"]`)).not.toBeNull()
    expect(bloc.textContent).toContain('Crédits dépensés par le programme')
    lexiqueNeutre('fiche programme 141')
    await ecran('#/beneficiaires/programme?p=141', true)
    await new Promise((r) => setTimeout(r, 50))
    expect(main.querySelector('#perf-programme')?.innerHTML).toBe('')
  })

  it('page département : lien vers le baromètre du département', async () => {
    await ecran('#/local/departement?dep=69')
    expect(main.querySelector(`a[href="#${CHEMIN}?dep=69"]`)).not.toBeNull()
  })

  it('toutes les lectures de données sont relatives au site', () => {
    expect(requetes.length).toBeGreaterThan(0)
    for (const u of requetes) expect(u.startsWith('data/'), u).toBe(true)
  })
})

// @vitest-environment happy-dom
// Écran « Application des lois » (/decisions/application-des-lois) sur des extraits réels de site/data/application_lois
// (tests/fixtures/application_lois/data/application_lois/ : index, six lois financières, lois 2025 et 2026 réduites,
// mesures des lois concernées), et lien de la fiche programme vers les grands projets numériques qui la citent.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { viderCache } from '../src/donnees'
import { dateLongue, delaiMedian, lectureLoi, tauxPublie, type Loi } from '../src/ecrans/application_lois'
import { choisirValeur, monterPage } from './aide-dom'

const CHEMIN = '/decisions/application-des-lois'
const FIXTURES = join(process.cwd(), 'tests', 'fixtures')
const PRIVE = join(FIXTURES, 'application_lois')
let sansNumerique = false
const requetes: string[] = []

function servir() {
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const chemin = u.split('?')[0]
    if (sansNumerique && chemin.startsWith('data/numerique_etat/')) return new Response('introuvable', { status: 404 })
    const f = [join(PRIVE, chemin), join(FIXTURES, chemin)].find((c) => existsSync(c))
    if (!f) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}

const lire = (rel: string) => JSON.parse(readFileSync(join(PRIVE, 'data', 'application_lois', rel), 'utf8'))
const fin = lire('lois_finances.json')
const idx = lire('index.json')
const norm = (s: string) => s.replace(/[\s  ]+/g, ' ').trim()

let main: HTMLElement
async function ecran(fragment: string) {
  viderCache()
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  await new Promise((r) => setTimeout(r, 40))
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

describe('/decisions/application-des-lois', () => {
  it('route déclarée sous « Décisions et contrôle », avec voisins existants et limites de longueur', () => {
    const r = ROUTES.find((x) => x.chemin === CHEMIN)!
    expect(r.parent).toBe('/decisions')
    expect(r.voisins!.length).toBeLessThanOrEqual(3)
    for (const v of r.voisins ?? []) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    expect(r.description.length).toBeLessThanOrEqual(200)
    expect(`${r.titrePage} · Le billet découpé`.length).toBeLessThanOrEqual(100)
  })

  it('fonctions de lecture : taux publié, délai calculé, absence jamais lue comme zéro', () => {
    const lfi = fin.lois.find((l: Loi) => l.categorie === 'lf_initiale') as Loi
    expect(tauxPublie(lfi)).toMatch(/^\d+,\d %$/)
    expect(delaiMedian(lfi)).toMatch(/jours \(de \d/)
    const sansMesure = fin.lois.find((l: Loi) => !l.mesures_a_appliquer) as Loi
    expect(tauxPublie(sansMesure)).toBe('sans objet (aucune mesure à appliquer)')
    expect(delaiMedian(sansMesure)).toBe('aucun délai publié')
    expect(dateLongue('2026-02-19')).toBe('19 février 2026')
    expect(dateLongue('2025-12-01')).toBe('1er décembre 2025')
    expect(lectureLoi({ ...lfi, application_directe: true, mesures_a_appliquer: 0, mesures_sans_objet: 0 })).toContain('application directe')
  })

  it('page : introduction, lois financières d’abord, ordre écrit, badges et méthode, aucune requête externe', async () => {
    requetes.length = 0
    await ecran(`#${CHEMIN}`)
    expect(main.querySelector('h1')?.textContent).toBe('Application des lois : mesures prévues et publiées')
    expect(texte()).toContain('Elle ne dit pas pourquoi un texte n’est pas encore publié')
    const h2 = Array.from(main.querySelectorAll('h2')).map((x) => x.textContent)
    expect(h2[0]).toBe('Lois de finances et de financement de la Sécurité sociale')
    const items = main.querySelectorAll('#liste-al-fin li')
    expect(items.length).toBe(fin.lois.length)
    const titres = Array.from(main.querySelectorAll('#liste-al-fin summary')).map((x) => x.textContent)
    expect(titres).toEqual(fin.lois.map((l: Loi) => l.titre))
    expect(main.querySelectorAll('[data-regle-ordre]').length).toBeGreaterThanOrEqual(2)
    expect(texte()).toContain('Aucun classement par taux ni par délai')
    expect(main.querySelectorAll('[data-calcule]').length).toBeGreaterThanOrEqual(2)
    expect(texte()).toContain('Aucun taux par année n’est calculé')
    expect(texte()).toContain('taux publié par le baromètre')
    expect(requetes.every((u) => u.startsWith('data/'))).toBe(true)
    for (const t of main.querySelectorAll('table')) {
      expect(t.querySelector('caption')).not.toBeNull()
      expect(t.querySelectorAll('th[scope]').length).toBeGreaterThan(0)
    }
    lexiqueNeutre('page')
  })

  it('année par année : tableau des sommes et lois de l’année choisie', async () => {
    await ecran(`#${CHEMIN}?annee=2025`)
    const lignes = Array.from(main.querySelectorAll('table tbody tr th[scope="row"]')).map((x) => x.textContent)
    expect(lignes).toEqual(idx.par_annee.annees.map((a: { annee: number }) => String(a.annee)))
    await new Promise((r) => setTimeout(r, 40))
    expect(texte()).toMatch(/publiées? en 2025/)
    expect((main.querySelector('#al-annee') as HTMLSelectElement).value).toBe('2025')
  })

  it('filtre par type de loi', async () => {
    await ecran(`#${CHEMIN}`)
    choisirValeur(main, 'al-cat', 'lfss')
    const n = fin.lois.filter((l: Loi) => l.categorie === 'lfss').length
    expect(main.querySelectorAll('#liste-al-fin li').length).toBe(n)
  })

  it('détail d’une loi : mesures chargées à la demande, ordre de l’échéancier, liens Légifrance', async () => {
    await ecran(`#${CHEMIN}`)
    const lfi = fin.lois.find((l: Loi) => l.categorie === 'lf_initiale') as Loi
    const d = main.querySelector(`#liste-al-fin details[data-id="${lfi.id}"]`) as HTMLDetailsElement
    d.open = true
    d.dispatchEvent(new Event('toggle'))
    await new Promise((r) => setTimeout(r, 60))
    const table = d.querySelector('table')!
    expect(table.querySelector('caption')?.textContent).toContain(lfi.titre)
    const m = lire(lfi.fichier_mesures!.replace('application_lois/', ''))
    expect(table.querySelectorAll('tbody tr').length).toBe(m.mesures.length)
    const nums = Array.from(table.querySelectorAll('tbody th[scope="row"]')).map((x) => Number(x.textContent))
    expect(nums).toEqual([...nums].sort((a, b) => a - b))
    expect(d.querySelector(`a[href="${lfi.url_legifrance}"]`)).not.toBeNull()
    lexiqueNeutre('détail')
  })
})

describe('fiche programme : lien vers les grands projets numériques', () => {
  it('programme cité par le panorama : lien avec le nombre de projets', async () => {
    sansNumerique = false
    await ecran('#/beneficiaires/programme?p=141')
    const a = main.querySelector('a[href="#/explorer/numerique-etat?p=141"]')
    expect(a?.textContent).toBe('Grands projets numériques citant ce programme (1)')
  })

  it('données absentes : aucun lien', async () => {
    sansNumerique = true
    await ecran('#/beneficiaires/programme?p=141')
    expect(main.querySelector('a[href^="#/explorer/numerique-etat"]')).toBeNull()
    expect(main.querySelector('.actions')).not.toBeNull()
    sansNumerique = false
  })
})

// @vitest-environment happy-dom
// Écran « Projets subventionnés par l'État » (/local/projets) et bloc des pages commune et département, sur des
// extraits réels de site/data (tests/fixtures/projets/data/ : projets_subventionnes/index.json complet ;
// projets_subventionnes/44.json, territoires/44.json et local/geo/44.json réduits à quatre communes, valeurs non
// modifiées ; la commune 44005, sans Fonds vert, est retirée exprès de `par_commune` pour le cas « aucun projet publié »).
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { viderCache } from '../src/donnees'
import { hors, SANS_PROJET, sommes, STATUT_DGCL, STATUT_FV, TITRE } from '../src/ecrans/projets'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { attendreQue, monterPage } from './aide-dom'

const RACINE = process.cwd()
const MES_FIXTURES = join(RACINE, 'tests', 'fixtures', 'projets')
const requetes: string[] = []
let main: HTMLElement

function servir() {
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const f = join(MES_FIXTURES, u.split('?')[0])
    if (!existsSync(f)) return new Response('introuvable', { status: 404 })
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

const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function verifierLexique(t: string, ou: string) {
  let x = t.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
}
/** Statuts lus dans la dernière colonne des tableaux de projets. */
const statutsAffiches = () =>
  [...main.querySelectorAll('table')].filter((t) => t.querySelector('thead th:last-child')?.textContent === 'Statut publié').flatMap((t) => [...t.querySelectorAll('tbody tr td:last-child')].map((td) => td.textContent ?? ''))

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu') as HTMLElement
})
beforeEach(() => {
  requetes.length = 0
})
afterAll(() => {
  vi.unstubAllGlobals()
})

describe('route', () => {
  it('déclarée sous /local, avec un titre et une description aux limites', () => {
    const r = ROUTES.find((x) => x.chemin === '/local/projets')!
    expect(r.parent).toBe('/local')
    expect(r.voisins!.length).toBeGreaterThanOrEqual(1)
    expect(r.voisins!.length).toBeLessThanOrEqual(3)
    for (const v of r.voisins!) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    expect(r.description.length).toBeGreaterThanOrEqual(70)
    expect(r.description.length).toBeLessThanOrEqual(200)
    expect(`${r.titrePage} · Où vont mes impôts`.length).toBeLessThanOrEqual(100)
  })
})

describe('écran /local/projets', () => {
  it('sans lieu : phrase d’introduction, choix du département, limites, aucune requête externe', async () => {
    await ecran('#/local/projets')
    expect(main.querySelector('h1')?.textContent).toContain(TITRE)
    expect(main.querySelector('#projets-dep option[value="44"]')).not.toBeNull()
    expect(texte()).toContain('La page ne montre ni les autres aides de l’État')
    expect(requetes.every((u) => u.startsWith('data/'))).toBe(true)
    verifierLexique(texte(), 'accueil de l’écran')
  })

  it('une commune : dotations et Fonds vert, statut tel que publié, jamais additionnés', async () => {
    await ecran('#/local/projets?insee=44109')
    const t = texte()
    expect(t).toContain('Nantes (44109)')
    const statuts = statutsAffiches()
    expect(statuts.length).toBeGreaterThan(0)
    expect(new Set(statuts)).toEqual(new Set([STATUT_DGCL, STATUT_FV]))
    for (const s of statuts) expect(s).not.toMatch(/réalisé|livré/i)
    expect(t).toContain('Calculé par le site')
    expect(t).toContain('ne sont jamais additionnés')
    // tableaux accessibles
    for (const tab of main.querySelectorAll('table')) {
      expect(tab.querySelector('caption')?.textContent?.length).toBeGreaterThan(5)
      expect(tab.querySelectorAll('th[scope="col"]').length).toBeGreaterThan(2)
    }
    // sommes par année et dispositif seulement : aucune ligne qui mêle deux dispositifs
    const recap = main.querySelector('table')!
    for (const tr of recap.querySelectorAll('tbody tr')) expect(tr.querySelectorAll('td')[0].textContent).not.toMatch(/ et /)
    // intitulé retiré par le filtre de noms : mention, pas de texte inventé
    expect(t).toContain('intitulé non publié (il peut contenir un nom de personne)')
    expect(requetes.every((u) => u.startsWith('data/'))).toBe(true)
    verifierLexique(t, 'commune')
  })

  it('filtres par dispositif et par année', async () => {
    await ecran('#/local/projets?insee=44109&d=Fonds+vert&a=2024')
    const lignes = [...main.querySelectorAll('table')].at(-1)!.querySelectorAll('tbody tr')
    expect(lignes.length).toBeGreaterThan(0)
    for (const tr of lignes) {
      expect(tr.querySelector('th')?.textContent).toBe('2024')
      expect(tr.querySelector('td:last-child')?.textContent).toBe(STATUT_FV)
    }
    expect(main.querySelector('#projets-disp option[selected]')?.getAttribute('value')).toBe('Fonds vert')
    expect(main.querySelector('#projets-an option[selected]')?.getAttribute('value')).toBe('2024')
  })

  it('badges Action cœur de ville et Petites villes de demain', async () => {
    await ecran('#/local/projets?insee=44036')
    expect(texte()).toContain('Action cœur de ville')
    await ecran('#/local/projets?insee=44003')
    expect(texte()).toContain('Petites villes de demain')
  })

  it('commune sans projet : « aucun projet publié pour ces dispositifs », jamais un jugement', async () => {
    await ecran('#/local/projets?insee=44005')
    const t = texte()
    expect(t).toContain(SANS_PROJET)
    expect(t).not.toMatch(/ne fait rien|n’a rien fait|aucun effort/i)
    expect(main.querySelector('table')).toBeNull()
  })

  it('un département : sommes par année et dispositif, communes, recherche par nom', async () => {
    await ecran('#/local/projets?dep=44')
    const t = texte()
    expect(t).toContain('Département Loire-Atlantique (44)')
    expect(statutsAffiches().every((s) => s === STATUT_DGCL || s === STATUT_FV)).toBe(true)
    expect(main.querySelectorAll('.liste-colonnes li').length).toBe(4)
    expect(t).toContain(SANS_PROJET)
    await ecran('#/local/projets?dep=44&q=nant')
    expect([...main.querySelectorAll('.liste-colonnes li')].map((li) => li.querySelector('a')?.textContent)).toEqual(['Nantes'])
  })
})

describe('sommes (règle 13)', () => {
  it('même année et même dispositif seulement ; montant non communiqué hors somme', () => {
    const s = sommes([
      { annee: 2024, dispositif: 'DETR', intitule: 'a', beneficiaire: null, montant: 10, statut: STATUT_DGCL },
      { annee: 2024, dispositif: 'Fonds vert', intitule: 'b', beneficiaire: null, montant: 5, statut: STATUT_FV },
      { annee: 2024, dispositif: 'Fonds vert', intitule: 'c', beneficiaire: null, montant: null, statut: STATUT_FV },
      { annee: 2023, dispositif: 'DETR', intitule: 'd', beneficiaire: null, montant: 1, statut: STATUT_DGCL },
    ])
    expect(s).toEqual([
      { annee: 2024, dispositif: 'DETR', n: 1, montant: 10, nc: 0, statut: STATUT_DGCL },
      { annee: 2024, dispositif: 'Fonds vert', n: 2, montant: 5, nc: 1, statut: STATUT_FV },
      { annee: 2023, dispositif: 'DETR', n: 1, montant: 1, nc: 0, statut: STATUT_DGCL },
    ])
  })
})

describe('bloc des pages commune et département', () => {
  it('au prérendu (happy-dom) : rien n’est ajouté à la page', async () => {
    await ecran('#/local/commune?insee=44109')
    expect(main.querySelector('.projets-bloc')).toBeNull()
    expect(requetes.some((u) => u.includes('projets_subventionnes'))).toBe(false)
  })

  it('dans le navigateur : bloc avant « Pour aller plus loin », données chargées seulement au clic', async () => {
    const espion = vi.spyOn(hors, 'prerendu').mockReturnValue(false)
    try {
      await ecran('#/local/commune?insee=44109')
      const bloc = main.querySelector<HTMLElement>('.projets-bloc')!
      expect(bloc).not.toBeNull()
      expect(bloc.nextElementSibling?.textContent).toBe('Pour aller plus loin')
      expect(requetes.some((u) => u.includes('projets_subventionnes'))).toBe(false)
      const bouton = bloc.querySelector('button')!
      expect(bouton.getAttribute('aria-expanded')).toBe('false')
      bouton.click()
      await attendreQue(() => !!bloc.querySelector('table'))
      expect(bouton.getAttribute('aria-expanded')).toBe('true')
      expect(bloc.textContent).toContain(STATUT_FV)
      expect(bloc.querySelector('a[href*="/local/projets"]')).not.toBeNull()

      await ecran('#/local/departement?dep=44')
      const blocDep = main.querySelector<HTMLElement>('.projets-bloc')!
      expect(blocDep).not.toBeNull()
      blocDep.querySelector('button')!.click()
      await attendreQue(() => !!blocDep.querySelector('table'))
      expect(blocDep.textContent).toContain('Action cœur de ville')
      verifierLexique(blocDep.textContent ?? '', 'bloc département')
    } finally {
      espion.mockRestore()
    }
  })
})

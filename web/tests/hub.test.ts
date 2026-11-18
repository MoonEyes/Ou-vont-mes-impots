// @vitest-environment happy-dom
// Hubs : toute route déclarée avec un parent est atteignable depuis le hub de ce parent, rangée par thème,
// dans un ordre stable (alphabétique, jamais par montant) ; le hub « Explorer » garde ses 8 tuiles en tête.
import { beforeAll, describe, expect, it } from 'vitest'
import { CHEMINS_CAISSES } from '../src/composants/caisses'
import { AUTRES, THEMES, grouper, rayonsVisibles, rubriques } from '../src/composants/hub'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { monterPage } from './aide-dom'
import { ROUTES_ESSAI } from './fixtures/hub/routes'

let main: HTMLElement
const page = async (chemin: string) => {
  location.hash = '#' + chemin
  await afficher(ROUTES, main, '#' + chemin)
  return main
}
const cible = (href: string) => href.replace(/^#/, '').split('?')[0].replace(/(.)\/$/, '$1')
const liens = (el: ParentNode) => Array.from(el.querySelectorAll('a[href^="#/"]')).map((a) => cible(a.getAttribute('href')!))
const html = (s: string) => {
  const d = document.createElement('div')
  d.innerHTML = s
  return d
}

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('rubriques par thème (table d’essai)', () => {
  it('thèmes dans l’ordre déclaré, « Autres pages » en dernier, cartes par ordre alphabétique du libellé court', () => {
    const g = grouper('/essai', { routes: ROUTES_ESSAI })
    expect(g.map((x) => x.theme.cle)).toEqual(['qui-recoit', 'politiques', AUTRES.cle])
    expect(g[1].cartes.map((c) => c.chemin)).toEqual(['/essai/a', '/essai/e', '/essai/z'])
    expect(g[2].cartes.map((c) => c.chemin)).toEqual(['/essai/sans', '/essai/faute'])
  })

  it('une page à paramètre (sansIndex) et les petits-enfants ne reçoivent pas de carte dans ce hub', () => {
    const tout = grouper('/essai', { routes: ROUTES_ESSAI }).flatMap((x) => x.cartes.map((c) => c.chemin))
    expect(tout).not.toContain('/essai/parametre')
    expect(tout).not.toContain('/essai/e/sous')
    expect(rayonsVisibles('/essai/e', ROUTES_ESSAI).map((r) => r.chemin)).toEqual(['/essai/e/sous'])
  })

  it('l’ordre ne dépend pas de l’ordre de déclaration', () => {
    const inverse = [...ROUTES_ESSAI].reverse()
    expect(grouper('/essai', { routes: inverse })).toEqual(grouper('/essai', { routes: ROUTES_ESSAI }))
  })

  it('exclusion, rendu accessible : titres de rubrique, compte de pages, liens, identifiants uniques', () => {
    const d = html(rubriques('/essai', { routes: ROUTES_ESSAI, exclure: ['/essai/z'] }))
    expect(liens(d)).not.toContain('/essai/z')
    const titres = Array.from(d.querySelectorAll('.hub-rubrique > h2')).map((t) => t.textContent)
    expect(titres).toEqual(['Qui reçoit l’argent 1 page', 'Grandes politiques publiques 2 pages', 'Autres pages 2 pages'])
    d.querySelectorAll('.hub-rubrique').forEach((s) => expect(d.querySelector('#' + s.getAttribute('aria-labelledby'))).not.toBeNull())
    const ids = Array.from(d.querySelectorAll('[id]')).map((e) => e.id)
    expect(new Set(ids).size).toBe(ids.length)
    d.querySelectorAll('.cartes a').forEach((a) => expect(a.textContent!.trim().length).toBeGreaterThan(0))
  })

  it('avec un titre : section de niveau 2, rubriques de niveau 3 ; un seul thème : simple liste ; rien : chaîne vide', () => {
    const d = html(rubriques('/essai', { routes: ROUTES_ESSAI, titre: 'Dans cette rubrique' }))
    expect(d.querySelector('section.hub-rubriques > h2')?.textContent).toBe('Dans cette rubrique')
    expect(d.querySelectorAll('.hub-rubrique > h3')).toHaveLength(3)
    expect(d.querySelectorAll('.hub-rubrique > h2')).toHaveLength(0)
    const seul = html(rubriques('/seul', { routes: ROUTES_ESSAI }))
    expect(seul.querySelectorAll('h2, h3')).toHaveLength(0)
    expect(liens(seul)).toEqual(['/seul/a', '/seul/b'])
    expect(rubriques('/rien', { routes: ROUTES_ESSAI })).toBe('')
  })
})

describe('table des routes du site', () => {
  it('chaque thème déclaré dans ROUTES est un thème connu (sinon la page tombe dans « Autres pages »)', () => {
    const connus = new Set(THEMES.map((t) => t.cle))
    const inconnus = ROUTES.filter((r) => r.theme && !connus.has(r.theme)).map((r) => `${r.chemin} : ${r.theme}`)
    expect(inconnus).toEqual([])
  })

  it('chaque route avec un parent est atteignable depuis le hub de ce parent', { timeout: 120000 }, async () => {
    const parents = [...new Set(ROUTES.map((r) => r.parent).filter((p): p is string => !!p))].sort()
    const manquantes: string[] = []
    for (const p of parents) {
      expect(ROUTES.some((r) => r.chemin === p), `parent ${p} déclaré`).toBe(true)
      await page(p)
      const vus = new Set(liens(main))
      const formulaire = !!main.querySelector('form')
      for (const r of ROUTES.filter((x) => x.parent === p)) {
        // Page à paramètre (commune, résultat du calcul) : atteinte par un lien ou par le formulaire du hub.
        if (vus.has(r.chemin) || (r.sansIndex && formulaire)) continue
        manquantes.push(`${r.chemin} (hub ${p})`)
      }
    }
    expect(manquantes).toEqual([])
  })
})

describe('hub « Explorer »', () => {
  it('les 8 tuiles en tête, puis les rubriques par thème, sans doublon ni page oubliée', async () => {
    await page('/explorer')
    expect(main.querySelectorAll('.tuiles a')).toHaveLength(8)
    expect(CHEMINS_CAISSES).toHaveLength(8)
    const tuiles = main.querySelector('.tuiles')!
    const bloc = main.querySelector('.hub-rubriques')
    expect(bloc).not.toBeNull()
    expect(tuiles.compareDocumentPosition(bloc!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const dansTuiles = liens(tuiles)
    const dansRubriques = liens(bloc!)
    expect(dansRubriques.filter((c) => CHEMINS_CAISSES.includes(c))).toEqual([])
    const attendus = rayonsVisibles('/explorer').map((r) => r.chemin).sort()
    expect([...dansTuiles, ...dansRubriques].sort()).toEqual(attendus)
    // Ordre affiché = ordre calculé (thèmes déclarés, alphabétique dans chaque rubrique).
    const g = grouper('/explorer', { exclure: CHEMINS_CAISSES })
    expect(dansRubriques).toEqual(g.flatMap((x) => x.cartes.map((c) => c.chemin)))
    // Titres hiérarchisés : h1 puis des h2 de rubrique, chacun relié à sa section.
    const sections = Array.from(bloc!.querySelectorAll('.hub-rubrique'))
    if (g.length > 1) {
      expect(sections.map((s) => s.querySelector('h2')?.id)).toEqual(g.map((x) => `hub-explorer-${x.theme.cle}`))
      sections.forEach((s) => expect(s.getAttribute('aria-labelledby')).toBe(s.querySelector('h2')!.id))
    }
    expect(main.querySelectorAll('h1')).toHaveLength(1)
    expect(main.querySelector('.hub-rubriques h1, .hub-rubriques h4')).toBeNull()
    expect(main.textContent).toContain('Cet ordre ne dit rien de l’importance d’un sujet ni de son montant.')
    expect(main.textContent).not.toContain('—')
  })

  it('autres hubs : bénéficiaires, calcul, méthode, local ne listent que leurs propres rayons', async () => {
    for (const hub of ['/beneficiaires', '/calcul', '/methode', '/local']) {
      await page(hub)
      const vus = liens(main.querySelector('.hub-rubriques') ?? document.createElement('div'))
      for (const c of vus) expect(ROUTES.find((r) => r.chemin === c)?.parent, `${hub} : ${c}`).toBe(hub)
      for (const r of rayonsVisibles(hub)) expect(liens(main), `${hub} : ${r.chemin}`).toContain(r.chemin)
    }
  })
})

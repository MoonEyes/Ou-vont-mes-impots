// @vitest-environment happy-dom
// Navigation simplifiée : quatre portes sur l'accueil (dans l'ordre), menu ramené à ces portes plus Explorer et
// Méthode, plan de rubrique en haut des quatre hubs, fil d'Ariane cohérent sur toutes les routes, en-tête compact sur
// téléphone (96 px au plus à 360 px, recherche et menu accessibles au clavier). Mesure réelle dans Chrome : avant
// 181 px, après 83 px à 360 px de large (Playwright, voir le compte rendu du commit).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { monterPage } from './aide-dom'
import { ROUTES } from '../src/routes'
import { afficher, maillons, nomCourt } from '../src/routeur'
import { rayonsVisibles } from '../src/composants/hub'

const RACINE = process.cwd()
const html = readFileSync(join(RACINE, 'index.html'), 'utf8')
const css = readFileSync(join(RACINE, 'src', 'styles.css'), 'utf8')
let main: HTMLElement
const texte = (el: Element | null) => el?.textContent?.replace(/\s+/g, ' ').trim() ?? ''
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
/** Valeur en px d'une longueur CSS en rem ou px (1 rem = 16 px). */
const px = (v: string) => (v.endsWith('rem') ? parseFloat(v) * 16 : parseFloat(v))

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('menu principal et portes', () => {
  const MENU: [string, string, string][] = [
    ['Mon salaire', '#/calcul', '/calcul'],
    ['Ma commune', '#/local/ma-commune', '/local'],
    ['Qui reçoit l’argent', '#/beneficiaires', '/beneficiaires'],
    ['Qui décide', '#/decisions', '/decisions'],
    ['Explorer', '#/explorer', '/explorer'],
    ['Méthode', '#/methode', '/methode'],
  ]
  it('menu : les quatre portes dans l’ordre, puis Explorer et Méthode ; chaque entrée mène à une route existante', () => {
    const liens = Array.from(document.querySelectorAll<HTMLAnchorElement>('#menu a'))
    expect(liens.map((a) => [texte(a), a.getAttribute('href'), a.dataset.rubrique])).toEqual(MENU)
    for (const [, href] of MENU) expect(ROUTES.some((r) => '#' + r.chemin === href), href).toBe(true)
  })

  it('fil d’Ariane : le premier maillon de chaque rubrique porte le nom de son entrée de menu', () => {
    for (const [nom, , rubrique] of MENU) expect(nomCourt(ROUTES.find((r) => r.chemin === rubrique)!), rubrique).toBe(nom)
  })

  it('accueil : quatre portes dans l’ordre, la première calcule depuis l’accueil, les autres mènent à leur rubrique', async () => {
    await ecran('#/')
    const portes = Array.from(main.querySelectorAll('.portes > li'))
    expect(portes.map((p) => texte(p.querySelector('.porte-titre')))).toEqual(['Mon salaire', 'Ma commune', 'Qui reçoit l’argent', 'Qui décide'])
    expect(portes[0].querySelector('form#heros-form #heros-net')).not.toBeNull()
    expect(portes.slice(1).map((p) => p.querySelector('.porte-titre a')?.getAttribute('href'))).toEqual(['#/local/ma-commune', '#/beneficiaires', '#/decisions'])
    // Le calcul direct est chargé à la demande : rien du moteur dans le module de l'accueil.
    const accueil = readFileSync(join(RACINE, 'src', 'ecrans', 'accueil.ts'), 'utf8')
    expect(accueil).toMatch(/import\('\.\/accueil-calcul'\)/)
    expect(accueil).not.toMatch(/^import[^\n]*accueil-calcul/m)
  })

  it('aria-current : l’entrée de la rubrique courante est marquée, sur une page de rubrique comme sur une page fille', async () => {
    for (const [fragment, rubrique] of [
      ['#/decisions/votes', '/decisions'],
      ['#/local/comparer', '/local'],
      ['#/explorer/dette', '/explorer'],
      ['#/methode/glossaire', '/methode'],
    ]) {
      await ecran(fragment)
      const courants = Array.from(document.querySelectorAll('#menu [aria-current="page"]'))
      expect(courants.map((a) => a.getAttribute('data-rubrique')), fragment).toEqual([rubrique])
    }
  })
})

describe('fil d’Ariane cohérent sur toutes les pages', () => {
  it('chaque route (hors accueil) : Accueil, puis la chaîne des parents, puis la page ; chaque maillon est une route', () => {
    for (const r of ROUTES) {
      const m = maillons(ROUTES, r)
      if (r.chemin === '/') {
        expect(m).toEqual([])
        continue
      }
      expect(m[0], r.chemin).toEqual({ nom: 'Accueil', fragment: '#/' })
      expect(m[m.length - 1], r.chemin).toEqual({ nom: nomCourt(r), fragment: '#' + r.chemin })
      for (const x of m) expect(ROUTES.some((y) => '#' + y.chemin === x.fragment), x.fragment).toBe(true)
      // Trois niveaux au plus sous l'accueil.
      expect(m.length, r.chemin).toBeLessThanOrEqual(4)
    }
  })

  it('pages rendues : un seul fil d’Ariane, dernier maillon marqué aria-current', async () => {
    for (const f of ['#/explorer', '#/beneficiaires', '#/local', '#/decisions', '#/methode', '#/explorer/etat', '#/decisions/realisations']) {
      await ecran(f)
      const fils = main.querySelectorAll('nav.fil-ariane[aria-label="Fil d\'Ariane"]')
      expect(fils, f).toHaveLength(1)
      const liens = fils[0].querySelectorAll('a')
      expect(liens[liens.length - 1].getAttribute('aria-current'), f).toBe('page')
      expect(liens[0].getAttribute('href')).toBe('#/')
    }
  })
})

describe('plan de rubrique sur les quatre hubs', () => {
  for (const hub of ['/explorer', '/decisions', '/beneficiaires', '/local']) {
    it(`${hub} : plan en haut de la page, un lien vers chaque page de la rubrique`, async () => {
      await ecran('#' + hub)
      const plan = main.querySelector('nav.plan-rubrique')!
      expect(plan, hub).not.toBeNull()
      // Le plan vient avant tout le reste du contenu de la rubrique (juste après le titre et le chapeau).
      expect(plan.compareDocumentPosition(main.querySelector('h1')!) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
      const hrefs = Array.from(plan.querySelectorAll('a')).map((a) => a.getAttribute('href'))
      const attendus = rayonsVisibles(hub).map((r) => '#' + r.chemin)
      expect(new Set(hrefs)).toEqual(new Set(attendus))
      expect(plan.getAttribute('aria-labelledby')).toBeTruthy()
    })
  }
})

describe('en-tête compact à 360 px', () => {
  // Le script du site (boutons de l'en-tête) n'est branché qu'ici : avant, les écrans sont rendus sans concurrence.
  beforeAll(async () => {
    await import('../src/main')
  })
  /** Bloc de la requête « max-width: 61.99rem » qui contient ce sélecteur (la dernière, celle de l'en-tête compact). */
  const compact = () => {
    const blocs = [...css.matchAll(/@media \(max-width: 61\.99rem\) \{([\s\S]*?)\n\}/g)].map((m) => m[1])
    return blocs.find((b) => b.includes('#bouton-recherche'))!
  }
  it('budget de hauteur : bandeau d’une ligne + ligne marque, loupe, menu + filet ≤ 96 px', () => {
    const b = compact()
    const bandeau = /\.bandeau \{[^}]*font-size: ([\d.]+rem);[^}]*line-height: ([\d.]+);/.exec(b)!
    const marge = /\.bandeau \.conteneur \{[^}]*padding-block: ([\d.]+rem);/.exec(b)!
    const ligne = /\.entete-ligne \{[^}]*min-height: ([\d.]+rem);/.exec(b)!
    const hauteur = px(bandeau[1]) * Number(bandeau[2]) + 2 * px(marge[1]) + px(ligne[1]) + 2.5
    expect(hauteur).toBeLessThanOrEqual(96)
    // Une seule ligne de bandeau à 360 px : la phrase longue est masquée sous 45 rem (elle reste dans le pied de page).
    expect(css).toMatch(/@media \(max-width: 44\.99rem\) \{\s*\.bandeau-suite \{\s*display: none;/)
    expect(html).toContain('<span class="non-officiel">Site citoyen, non officiel</span>')
    expect(/<footer class="pied">[\s\S]*<\/footer>/.exec(html)![0]).toContain('Il ne remplace pas impots.gouv.fr et ne juge aucune dépense.')
    // La recherche repliée ne prend aucune place tant qu'on ne l'ouvre pas.
    expect(b).toMatch(/\.recherche-entete\.repliee \{\s*display: none;/)
  })

  it('cibles de 48 px pour la loupe et le menu ; « Menu » garde son nom accessible même en icône seule', () => {
    const loupe = /#bouton-recherche \{([\s\S]*?)\}/.exec(css)![1]
    expect(px(/min-height: (\d+px)/.exec(loupe)![1])).toBeGreaterThanOrEqual(48)
    expect(px(/min-width: (\d+px)/.exec(loupe)![1])).toBeGreaterThanOrEqual(48)
    expect(html).toContain('<button type="button" id="bouton-recherche" aria-expanded="false" aria-controls="recherche-entete" aria-label="Rechercher dans le site"></button>')
    expect(html).toContain('<span class="bouton-menu-texte">Menu</span>')
    expect(css).not.toMatch(/\.bouton-menu-texte \{[^}]*display: none/)
  })

  it('clavier : la loupe ouvre la recherche et y place le focus, Échap la referme et rend le focus ; le menu referme la recherche', () => {
    const loupe = document.getElementById('bouton-recherche') as HTMLButtonElement
    const form = document.getElementById('recherche-entete')!
    expect(form.classList.contains('repliee')).toBe(true)
    loupe.click()
    expect(loupe.getAttribute('aria-expanded')).toBe('true')
    expect(form.classList.contains('repliee')).toBe(false)
    expect(document.activeElement?.id).toBe('recherche-champ')
    document.getElementById('recherche-champ')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    expect(form.classList.contains('repliee')).toBe(true)
    expect(document.activeElement).toBe(loupe)
    loupe.click()
    const menu = document.getElementById('bouton-menu') as HTMLButtonElement
    menu.click()
    expect(menu.getAttribute('aria-expanded')).toBe('true')
    expect(form.classList.contains('repliee')).toBe(true)
    expect(loupe.getAttribute('aria-expanded')).toBe('false')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(menu.getAttribute('aria-expanded')).toBe('false')
  })

  it('raccourci « / » : ouvre la recherche repliée (le focus est ensuite donné par src/composants/recherche.ts)', () => {
    const form = document.getElementById('recherche-entete')!
    ;(document.activeElement as HTMLElement | null)?.blur?.()
    form.classList.add('repliee')
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true }))
    expect(form.classList.contains('repliee')).toBe(false)
    expect(document.getElementById('bouton-recherche')!.getAttribute('aria-expanded')).toBe('true')
  })

  it('focus visible partout : aucun outline supprimé sans remplacement dans l’en-tête', () => {
    expect(css).toMatch(/:focus-visible \{\s*outline: 3px solid var\(--contour\);/)
    expect(css).not.toMatch(/\.entete[^{]*:focus(-visible)? \{\s*outline: none/)
  })
})

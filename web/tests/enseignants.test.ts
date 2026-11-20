// @vitest-environment happy-dom
// Page « Pour les enseignants » : trois activités complètes (niveau, durée, objectif, lien, consigne en 3 à 5 étapes,
// 3 questions dont une sur la source et la limite des données, point de vigilance), liens vers des routes existantes,
// impression d'une activité seule (une par page), lexique neutre, contact en texte simple, rien de stocké.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { ACTIVITES, PRESENTATION } from '../src/ecrans/enseignants'
import { CONTACT } from '../src/composants/signaler'
import { DESCRIPTION_MAX, DESCRIPTION_MIN, META_PAGES, TITRE_MAX } from '../src/metadonnees'
import { afficher } from '../src/routeur'
import { ROUTES, route } from '../src/routes'
import { monterPage } from './aide-dom'

const RACINE = process.cwd()
const css = readFileSync(join(RACINE, 'src', 'styles.css'), 'utf8')
let main: HTMLElement
const page = async (chemin: string) => {
  location.hash = '#' + chemin
  await afficher(ROUTES, main, '#' + chemin)
  return main
}
const cheminDe = (href: string) => href.replace(/^#/, '').split('?')[0].replace(/(.)\/$/, '$1')
const texte = (el: Element) => (el.textContent ?? '').replace(/\s+/g, ' ').trim()

const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})
afterEach(() => vi.restoreAllMocks())

describe('route, métadonnées, liens d’accès', () => {
  it('route /enseignants rangée sous Méthode, titre et description dans les longueurs de src/metadonnees.ts', () => {
    const r = route('/enseignants')!
    expect(r.parent).toBe('/methode')
    expect(r.sansIndex).toBeFalsy()
    const m = META_PAGES['/enseignants']
    expect(m.titre!.length).toBeLessThanOrEqual(TITRE_MAX)
    expect(m.description.length).toBeGreaterThanOrEqual(DESCRIPTION_MIN)
    expect(m.description.length).toBeLessThanOrEqual(DESCRIPTION_MAX)
  })

  it('liée depuis le pied de page et depuis Méthode', async () => {
    expect(document.querySelector('footer.pied a[href="#/enseignants"]')?.textContent).toBe('Pour les enseignants')
    await page('/methode')
    expect(main.querySelector('a[href="#/enseignants"]')).not.toBeNull()
  })
})

describe('page rendue', () => {
  it('présentation du site, trois activités dans l’ordre, contact en texte simple', async () => {
    await page('/enseignants')
    expect(main.querySelector('h1')?.textContent).toContain('Pour les enseignants')
    expect(texte(main.querySelector('.chapeau')!)).toBe(PRESENTATION)
    for (const mot of ['gratuit', 'sans publicité ni traceur', 'sourcées et datées', 'ne juge aucune dépense', 'ne prend parti pour personne', 'n’est envoyée ni conservée']) expect(PRESENTATION).toContain(mot)
    const fiches = [...main.querySelectorAll<HTMLElement>('.fiche')]
    expect(fiches.map((f) => texte(f.querySelector('h2')!))).toEqual(['Où va l’argent d’un salaire ?', 'Le budget de ma commune', 'Comment se vote un impôt ?'])
    expect([...main.querySelectorAll('.enseignants-sommaire a')].map((a) => a.getAttribute('href'))).toEqual(fiches.map((f) => `#${f.id}`))
    const contact = main.querySelector('.enseignants-contact')!
    expect(contact.textContent).toBe(CONTACT)
    expect(main.querySelector('a[href^="mailto:"]')).toBeNull()
    expect(main.innerHTML).not.toContain('mailto')
  })

  it('chaque activité : niveau et matière, durée en minutes, objectif, page, 3 à 5 étapes, 3 questions dont une sur la source, vigilance', async () => {
    await page('/enseignants')
    for (const f of main.querySelectorAll<HTMLElement>('.fiche')) {
      const infos = Object.fromEntries([...f.querySelectorAll('.fiche-infos > div')].map((d) => [texte(d.querySelector('dt')!), d.querySelector('dd')!]))
      expect(Object.keys(infos), f.id).toEqual(['Niveau et matière', 'Durée', expect.stringMatching(/^Pages? à utiliser$/)])
      expect(texte(infos['Niveau et matière']), f.id).toMatch(/sciences économiques et sociales|enseignement moral et civique/)
      expect(texte(infos['Durée']), f.id).toMatch(/^\d{2} minutes$/)
      expect(texte(f.querySelector('.fiche-objectif')!), f.id).toMatch(/^Objectif\. .{40,}/)
      const etapes = f.querySelectorAll('ol.fiche-etapes > li')
      expect(etapes.length, f.id).toBeGreaterThanOrEqual(3)
      expect(etapes.length, f.id).toBeLessThanOrEqual(5)
      expect(f.querySelectorAll('ol.fiche-questions > li'), f.id).toHaveLength(3)
      const source = f.querySelectorAll('.question-source')
      expect(source, f.id).toHaveLength(1)
      expect(texte(source[0]), f.id).toMatch(/source/i)
      expect(texte(f.querySelector('.fiche-vigilance h3')!)).toBe('Point de vigilance pour l’enseignant')
      expect(texte(f.querySelector('.fiche-vigilance p')!).length, f.id).toBeGreaterThan(80)
      expect(f.querySelector('button[data-imprimer]')?.textContent).toBe('Imprimer cette activité')
    }
    const [salaire, commune, vote] = ACTIVITES
    expect(salaire.vigilance).toMatch(/fictif/)
    expect(salaire.vigilance).toMatch(/parents/)
    expect(commune.consigne.join(' ')).toMatch(/fonctionnement[\s\S]*investissement/)
    expect(commune.consigne.join(' ')).toMatch(/Communes semblables/)
    expect(vote.consigne.join(' ')).toMatch(/article[\s\S]*scrutin[\s\S]*groupe/)
  })

  it('liens valides : chaque lien interne mène à une route existante ; pages attendues par activité', async () => {
    await page('/enseignants')
    const chemins = new Set(ROUTES.map((r) => r.chemin))
    const liens = [...main.querySelectorAll('.enseignants a[href^="#/"]')].map((a) => cheminDe(a.getAttribute('href')!))
    expect(liens.length).toBeGreaterThan(4)
    for (const c of liens) expect(chemins.has(c), c).toBe(true)
    const pages = (id: string) => [...main.querySelectorAll(`#${id} .fiche-pages a`)].map((a) => a.getAttribute('href'))
    expect(pages('activite-salaire')).toEqual(['#/calcul', '#/suivre-un-euro'])
    expect(pages('activite-commune')).toEqual(['#/local/ma-commune'])
    expect(pages('activite-vote')).toEqual(['#/decisions/qui-a-vote'])
    // Adresse lisible, pour la feuille imprimée : en vrai chemin, jamais en fragment.
    for (const a of main.querySelectorAll('.fiche-adresse')) expect(a.textContent).toMatch(/^[a-z0-9.-]+\/[a-z0-9/-]+\/$/)
  })
})

describe('impression', () => {
  it('« Imprimer cette activité » n’imprime que cette fiche, puis tout revient ; rien n’est stocké', async () => {
    await page('/enseignants')
    const ecrit = vi.spyOn(Storage.prototype, 'setItem')
    const etat: { corps: boolean; fiches: string[] }[] = []
    window.print = vi.fn(() => {
      etat.push({ corps: document.body.classList.contains('impression-une-activite'), fiches: [...main.querySelectorAll('.fiche-imprimee')].map((f) => f.id) })
    })
    main.querySelector<HTMLButtonElement>('#activite-commune button[data-imprimer]')!.click()
    expect(window.print).toHaveBeenCalledTimes(1)
    expect(etat).toEqual([{ corps: true, fiches: ['activite-commune'] }])
    window.dispatchEvent(new Event('afterprint'))
    expect(document.body.classList.contains('impression-une-activite')).toBe(false)
    expect(main.querySelector('.fiche-imprimee')).toBeNull()
    // Deux clics sans afterprint (navigateur qui n'envoie pas l'événement) : une seule fiche marquée à la fois.
    main.querySelector<HTMLButtonElement>('#activite-salaire button[data-imprimer]')!.click()
    main.querySelector<HTMLButtonElement>('#activite-vote button[data-imprimer]')!.click()
    expect([...main.querySelectorAll('.fiche-imprimee')].map((f) => f.id)).toEqual(['activite-vote'])
    window.dispatchEvent(new Event('afterprint'))
    expect(ecrit).not.toHaveBeenCalled()
    expect(localStorage.length + sessionStorage.length).toBe(0)
    expect(document.cookie).toBe('')
    expect(readFileSync(join(RACINE, 'src', 'ecrans', 'enseignants.ts'), 'utf8')).not.toMatch(/localStorage|sessionStorage|document\.cookie|indexedDB|\.animate\(/)
  })

  it('feuille de style : une activité par page, la fiche choisie seule, boutons et sommaire masqués', () => {
    const impression = [...css.matchAll(/@media print \{([\s\S]*?)\n\}/g)].map((m) => m[1]).join('\n')
    expect(impression).toMatch(/\.fiche \{[^}]*break-before: page;/)
    expect(impression).toMatch(/\.impression-une-activite \.enseignants > :not\(\.fiche-imprimee\)[^{]*\{\s*display: none !important;/)
    expect(impression).toMatch(/\.impression-une-activite \.fiche-imprimee \{\s*break-before: auto;/)
    expect(impression).toMatch(/\.enseignants-sommaire,[^{]*\{\s*display: none !important;/)
    // Les boutons d'action ne s'impriment pas (règle commune du site).
    expect(impression).toMatch(/main button \{\s*display: none !important;/)
  })
})

describe('neutralité', () => {
  it('lexique neutre partagé (docs/lexique_neutre.json) sur toute la page et sur chaque activité', async () => {
    await page('/enseignants')
    const tout = [texte(main), ...ACTIVITES.flatMap((a) => [a.titre, a.objectif, a.niveau, ...a.notions, ...a.consigne, ...a.questions, a.vigilance])].join(' ')
    for (const r of LEXIQUE.regles) expect(tout, r.raison).not.toMatch(borne(r.termes.join('|')))
    expect(tout).not.toContain('—')
  })

  it('aucune question orientée : pas de jugement de niveau demandé aux élèves', () => {
    const ORIENTEE = /est-ce (?:trop|assez|juste|normal|raisonnable|acceptable)|faut-il (?:baisser|augmenter|supprimer)|(?:trop|pas assez) (?:cher|élevé|bas)|bonne ou mauvaise|mieux ou moins bien/i
    for (const a of ACTIVITES) for (const q of [...a.questions, ...a.consigne]) expect(q, a.id).not.toMatch(ORIENTEE)
  })

  it('programmes : aucun article ni numéro de Bulletin officiel cité sans source datée', async () => {
    await page('/enseignants')
    const t = texte(main)
    expect(t).not.toMatch(/B\.?O\.?\s*(?:spécial\s*)?n°|Bulletin officiel (?:spécial )?n°/i)
    expect(t).toMatch(/Le site ne cite pas d’article de programme/)
  })
})

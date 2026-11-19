// @vitest-environment happy-dom
// Parcours principal (docs/AUDIT_PARCOURS.md) : accueil, saisie du salaire, résultat, puis où va chaque euro
// (suivre un euro, budget de l'État, détail et Sankey). Tout au clavier : chaque action est un champ, un bouton de
// formulaire ou un lien, et le focus arrive sur le titre de chaque nouvel écran. Écran de 360 px simulé : ordre de
// lecture du résultat et règles de la feuille de style propres au téléphone.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { session } from '../src/etat'
import { attendreQue, monterPage, requetes } from './aide-dom'

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = (el: ParentNode | null = main) => (el as HTMLElement | null)?.textContent?.replace(/\s+/g, ' ').trim() ?? ''
const avant = (a: Element | null, b: Element | null) => !!a && !!b && !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
/** Élément atteignable au clavier sans script : lien avec adresse, bouton, champ ou liste. */
const focalisable = (el: Element | null) =>
  !!el && ((el.tagName === 'A' && el.hasAttribute('href')) || ['BUTTON', 'INPUT', 'SELECT', 'SUMMARY'].includes(el.tagName)) && el.getAttribute('tabindex') !== '-1'

/** Écran de 360 px : les requêtes « max-width » de 45rem ou plus répondent vrai, les « min-width » de 34rem ou plus faux. */
function ecran360() {
  Object.defineProperty(window, 'innerWidth', { value: 360, configurable: true })
  window.matchMedia = ((q: string) => {
    const max = /max-width:\s*([\d.]+)rem/.exec(q)
    const min = /min-width:\s*([\d.]+)rem/.exec(q)
    const matches = max ? 360 <= Number(max[1]) * 16 : min ? 360 >= Number(min[1]) * 16 : false
    return { matches, media: q, addEventListener() {}, removeEventListener() {} }
  }) as never
}
function ecranLarge() {
  Object.defineProperty(window, 'innerWidth', { value: 1280, configurable: true })
  window.matchMedia = ((q: string) => ({ matches: /min-width/.test(q), media: q, addEventListener() {}, removeEventListener() {} })) as never
}

const AFFECTATION = JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/data/prelevements/affectation.json'), 'utf8'))

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
  ecran360()
})

describe('parcours principal, de la saisie au Sankey', () => {
  it('accueil (360 px) : champ salaire libellé « net avant impôt », aide reliée, bouton de formulaire, moteur préchargé au focus', async () => {
    await ecran('#/')
    const champ = main.querySelector<HTMLInputElement>('#heros-net')!
    expect(texte(main.querySelector('label[for="heros-net"]'))).toBe('Ton salaire net avant impôt, par mois')
    expect(champ.getAttribute('aria-describedby')).toContain('heros-aide')
    expect(texte(main.querySelector('#heros-aide'))).toContain('Net à payer avant impôt sur le revenu')
    // Le texte d'exemple ne se confond pas avec une valeur saisie.
    expect(champ.getAttribute('placeholder')).toMatch(/^Par exemple /)
    const bouton = main.querySelector<HTMLButtonElement>('#heros-form button[type=submit]')!
    expect(focalisable(champ) && focalisable(bouton)).toBe(true)
    // Ordre de lecture : titre, champ, bouton, puis le billet d'exemple.
    expect(avant(main.querySelector('h1'), champ)).toBe(true)
    expect(avant(bouton, main.querySelector('.billet'))).toBe(true)
    // Le moteur de calcul (Web Worker) se charge dès le focus du champ, avant le clic.
    const accueil = readFileSync(join(process.cwd(), 'src/ecrans/accueil.ts'), 'utf8')
    expect(accueil).toMatch(/champ\.addEventListener\('focus', prechauffer/)
    expect(accueil).not.toMatch(/^import[^\n]*calcul\/hors-fil/m)
  })

  it('porte « Mon salaire » (touche Entrée) : calcul direct depuis l’accueil, état annoncé dans le héros, puis résultat sans passer par le formulaire', async () => {
    session.resultat = null
    session.complet = null
    session.amorce = null
    await ecran('#/')
    main.querySelector<HTMLInputElement>('#heros-net')!.value = '2100'
    // Entrée dans le champ = envoi du formulaire.
    main.querySelector<HTMLFormElement>('#heros-form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    const statut = main.querySelector('#heros-statut')
    expect(statut?.getAttribute('role')).toBe('status')
    expect(texte(statut)).toContain('Calcul en cours sur ton appareil')
    await attendreQue(() => session.resultat !== null && location.hash === '#/calcul/resultat', 60000)
    // Jamais d'écran formulaire entre les deux : rien n'a été confié au formulaire, le profil est gardé pour « Modifier ma saisie ».
    expect(session.amorce).toBeNull()
    expect(session.profil?.personnes[0].salaire_net_avant_impot_mensuel).toBe(2100)
  }, 90000)

  it('relais vers le formulaire (saisie à préciser) : état du calcul en haut de l’écran, puis résultat', async () => {
    const profil = session.profil
    const resultat = session.resultat
    session.amorce = { net: '2100' }
    await ecran('#/calcul')
    const statut = main.querySelector('#statut-haut')
    expect(statut?.getAttribute('role')).toBe('status')
    expect(texte(statut)).toContain('Calcul en cours sur ton appareil')
    expect(avant(statut, main.querySelector('#formulaire'))).toBe(true)
    await attendreQue(() => session.resultat !== resultat && location.hash === '#/calcul/resultat', 60000)
    expect(session.profil).not.toBe(profil)
  }, 90000)

  it('résultat (360 px) : total, puis la phrase « sur 100 € que tu verses », puis le profil et « Modifier ma saisie », focus sur le titre', async () => {
    await ecran('#/calcul/resultat')
    const h1 = main.querySelector('h1')!
    expect(document.activeElement).toBe(h1)
    expect(h1.classList.contains('titre-resultat')).toBe(true)
    const recap = main.querySelector('.recap')!
    const total = recap.querySelector('.grand-chiffre')!
    const phrase = recap.querySelector('.recap-sur100')!
    // Rien entre le titre et le total (le profil est passé sous la phrase-clé).
    expect(avant(h1, recap)).toBe(true)
    expect(h1.nextElementSibling?.classList.contains('colonnes')).toBe(true)
    expect(h1.nextElementSibling?.querySelector('.recap')).toBe(recap)
    expect(avant(total, phrase)).toBe(true)
    expect(avant(phrase, recap.querySelector('.recap-profil'))).toBe(true)
    if (recap.querySelector('.jauge')) expect(avant(phrase, recap.querySelector('.jauge'))).toBe(true)
    expect(texte(phrase)).toMatch(/^Sur 100 € que tu verses, \d+ € vont à la Sécurité sociale, \d+ € à l’État(, \d+ € aux collectivités locales)?( et \d+ € (aux collectivités locales|sans destinataire publié))?\.$/)
    const parts = [...texte(phrase).matchAll(/(\d+) €/g)].map((m) => Number(m[1])).slice(1)
    expect(parts.reduce((a, b) => a + b, 0)).toBe(100)
    // Chiffres sourcés : la source du calcul est dans le même bloc.
    expect(texte(recap.querySelector('.source'))).toContain('calcul sur ton appareil')
    const modifier = recap.querySelector('.recap-profil a')!
    expect(modifier.getAttribute('href')).toBe('#/calcul')
    expect(texte(recap.querySelector('.recap-profil'))).toContain('2 100 € net avant impôt par mois')
  })

  it('résultat : chaque ligne mène directement à sa piste « Suivre un euro », clé publiée dans affectation.json', async () => {
    const liens = Array.from(main.querySelectorAll<HTMLAnchorElement>('.lignes a[href^="#/suivre-un-euro"]'))
    expect(liens.length).toBeGreaterThan(5)
    for (const a of liens) {
      const cle = new URLSearchParams(a.getAttribute('href')!.split('?')[1]).get('depart')!
      expect(AFFECTATION.prelevements[cle], cle).toBeTruthy()
      // Nom accessible propre à chaque ligne (lien « Suivre 1 € » distinct pour un lecteur d'écran).
      expect(texte(a)).toMatch(/^Suivre 1 € de la ligne .+/)
    }
    const csg = liens.find((a) => a.getAttribute('href')!.includes('depart=csg_activite'))
    expect(csg).toBeTruthy()
    // Bouton principal : la piste de la ligne la plus élevée.
    const principal = main.querySelector<HTMLAnchorElement>('.actions a.bouton-principal')!
    expect(principal.getAttribute('href')).toMatch(/^#\/suivre-un-euro\?depart=\w+$/)
    expect(focalisable(principal)).toBe(true)
  })

  it('suivre un euro depuis le résultat : piste choisie, retour au résultat en haut', async () => {
    const href = main.querySelector('.actions a.bouton-principal')!.getAttribute('href')!
    const depart = new URLSearchParams(href.split('?')[1]).get('depart')!
    await ecran(href)
    expect(document.activeElement).toBe(main.querySelector('h1'))
    expect(texte(main.querySelector('h1'))).toBe('Suivre un euro')
    const retour = main.querySelector('nav.retour-resultat')!
    expect(retour.querySelector('a[href="#/calcul/resultat"]')).not.toBeNull()
    expect(retour.querySelector('a[href="#/calcul"]')).not.toBeNull()
    expect(avant(main.querySelector('h1'), retour)).toBe(true)
    expect(main.querySelector(`[data-depart="${depart}"]`)?.getAttribute('aria-pressed')).toBe('true')
  })

  it('budget de l’État depuis le billet : aucune répartition « par déduction » de ta part, blocs lents complétés après l’affichage', async () => {
    await ecran('#/calcul/resultat')
    const etat = main.querySelector<HTMLAnchorElement>('.parts a[href="#/explorer/etat"]')!
    expect(focalisable(etat)).toBe(true)
    await ecran('#/explorer/etat')
    expect(main.querySelector('nav.retour-resultat a[href="#/calcul/resultat"]')).not.toBeNull()
    expect(texte()).not.toContain('sur ce que tu verses à l’État')
    expect(texte()).toContain('le site ne la répartit donc pas entre les postes')
    // Rendu direct de l'écran : titre et billet présents avant la lecture de millesimes/index.json et tracabilite/resume.json.
    const { rendre } = await import('../src/ecrans/etat')
    const zone = document.createElement('div')
    const rendu = await rendre(zone, new URLSearchParams())
    expect(zone.querySelector('h1')).not.toBeNull()
    expect(zone.querySelector('.billet svg')).not.toBeNull()
    expect(zone.querySelector('#bloc-suivi')?.innerHTML).toBe('')
    expect(rendu && 'suite' in rendu).toBe(true)
    await (rendu as { suite: Promise<void> }).suite
    expect(zone.querySelector('#trac')?.innerHTML).not.toBe('')
  })

  it('détail : Sankey sur écran large avec nom accessible, liste équivalente toujours là ; à 360 px, pas d’ECharts chargé', async () => {
    const detail = main.querySelector<HTMLAnchorElement>('a.bouton-principal[href^="#/explorer/etat/detail"]')!
    expect(focalisable(detail)).toBe(true)
    const avantRequetes = requetes.length
    await ecran(detail.getAttribute('href')!)
    expect(main.querySelector('.sankey')).toBeNull()
    expect(main.querySelectorAll('#sankey-zone ~ * li, #sankey-zone ~ ul li').length).toBeGreaterThan(1)
    expect(requetes.slice(avantRequetes).some((u) => /echarts/.test(u))).toBe(false)
    ecranLarge()
    try {
      await ecran(detail.getAttribute('href')!)
      const sankey = main.querySelector('.sankey')!
      expect(sankey.getAttribute('role')).toBe('img')
      expect(sankey.getAttribute('aria-label')).toMatch(/Diagramme de flux .+ liste ci-dessous/)
    } finally {
      ecran360()
    }
  })

  it('feuille de style : règles du téléphone pour le héros et le résultat, focus visible, rien de retiré', () => {
    const css = readFileSync(join(process.cwd(), 'src/styles.css'), 'utf8')
    const mobile = [...css.matchAll(/@media \(max-width: 44\.99rem\) \{([\s\S]*?)\n\}/g)].map((m) => m[1]).join('\n')
    expect(mobile).toMatch(/\.heros h1,\s*h1\.titre-resultat \{\s*font-size: 2\.125rem/)
    expect(mobile).toMatch(/h1\.titre-resultat \{\s*font-size: 1\.875rem/)
    expect(css).toMatch(/:focus-visible \{\s*outline: 3px solid var\(--contour\)/)
    expect(css).toMatch(/\.retour-resultat a \{[^}]*min-height: 2\.75rem/)
  })

  it('résultat sans calcul : pas de lien de retour sur les pages suivantes', async () => {
    const r = session.resultat
    session.resultat = null
    try {
      await ecran('#/suivre-un-euro')
      expect(main.querySelector('nav.retour-resultat')).toBeNull()
    } finally {
      session.resultat = r
    }
  })
})

// @vitest-environment happy-dom
// Non-régression des corrections de la recette du 17/11/2026 (docs/RECETTE.md).
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { session } from '../src/etat'
import { destinataire } from '../src/calcul/destinataires'
import { attendreQue, monterPage } from './aide-dom'

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''
const soumettre = () => main.querySelector<HTMLFormElement>('#formulaire')!.dispatchEvent(new Event('submit', { cancelable: true }))

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('recette', () => {
  it('tableaux défilants : atteignables au clavier et nommés (WCAG 2.1.1)', async () => {
    await ecran('#/local/commune?insee=69123')
    const zones = Array.from(main.querySelectorAll<HTMLElement>('.tableau-defile'))
    expect(zones.length).toBeGreaterThan(0)
    for (const z of zones) {
      expect(z.getAttribute('tabindex')).toBe('0')
      expect(z.getAttribute('role')).toBe('region')
      expect(z.getAttribute('aria-label')).toMatch(/tableau défilant/)
    }
  })

  it('commune : rendu progressif terminé, plus aucune section en attente', async () => {
    await ecran('#/local/commune?insee=69123')
    expect(main.querySelectorAll('[aria-busy]').length).toBe(0)
    expect(texte()).not.toContain('Chargement…')
  })

  it('saisie : montant au format français (espace, virgule) lu correctement', async () => {
    await ecran('#/calcul')
    const champ = main.querySelector<HTMLInputElement>('#p1-net')!
    expect(champ.type).toBe('text')
    expect(champ.inputMode).toBe('decimal')
    champ.value = '2 100,00'
    session.resultat = null
    soumettre()
    await attendreQue(() => session.resultat !== null, 60000)
    expect(session.profil?.personnes[0].salaire_net_avant_impot_mensuel).toBe(2100)
  }, 90000)

  it('saisie : texte illisible refusé sur le champ, garde alternée supérieure au nombre d’enfants signalée', async () => {
    await ecran('#/calcul')
    main.querySelector<HTMLInputElement>('#p1-net')!.value = '21OO'
    soumettre()
    await attendreQue(() => main.querySelector('#p1-net')?.getAttribute('aria-invalid') === 'true')
    // Profil prérempli (parent isolé, un enfant) : happy-dom ne décoche pas les autres boutons radio au clic.
    session.profil = { ...session.profil!, foyer: { situation: 'parent_isole', enfants: [{ annee_naissance: 2015, garde_alternee: false }] } }
    await ecran('#/calcul')
    main.querySelector<HTMLInputElement>('#alternee')!.value = '3'
    main.querySelector<HTMLInputElement>('#p1-net')!.value = '2000'
    soumettre()
    await attendreQue(() => main.querySelector('#alternee')?.getAttribute('aria-invalid') === 'true')
    expect(main.querySelector('#msg-alternee')?.textContent).toContain('dépasse')
  })

  it('saisie : message hors V1 focalisable', async () => {
    await ecran('#/calcul')
    const s = main.querySelector<HTMLSelectElement>('#p1-statut')!
    s.value = 'demandeur_emploi'
    s.dispatchEvent(new Event('change', { bubbles: true }))
    soumettre()
    await attendreQue(() => !!main.querySelector('#retour .avertissement'))
    expect(main.querySelector('#retour .avertissement')?.getAttribute('tabindex')).toBe('-1')
    expect(main.querySelector('#retour .avertissement')?.textContent).toContain('allocations chômage')
  })

  it('destinataires : jamais d’identifiant technique affiché', () => {
    expect(destinataire('autres_taxes_produits').nom).toBe('Plusieurs bénéficiaires (répartition non sourcée)')
  })

  it('aucun lien vide (href="") dans les écrans', async () => {
    for (const f of [...ROUTES.map((r) => '#' + r.chemin), '#/decisions/votes?p=141', '#/local/commune?insee=69123']) {
      await ecran(f)
      expect(main.querySelectorAll('a[href=""], a:not([href])').length, f).toBe(0)
    }
  })

  it('mentions : information RGPD des personnes nommées, sans identité inventée', async () => {
    await ecran('#/mentions')
    const t = texte()
    expect(t).toContain('Données personnelles des élus et candidats')
    expect(t).toContain('Intérêt légitime')
    expect(t).toContain('CNCCFP')
    expect(t).toContain('Durée de conservation')
    expect(t).toContain('article 21 du RGPD')
    expect(t).toContain('CNIL')
    expect(t).not.toContain('À COMPLÉTER')
    expect(t).toContain('proton.me.easel124@passinbox.com')
    expect(t).toContain('hébergeur')
    // Décision du 19/11/2026 : plus aucun lien vers les tickets ni vers le dépôt GitHub ; l'adresse dédiée est le
    // seul contact, en texte simple (pas de lien mailto).
    expect(main.querySelector('a[href*="github.com"]')).toBeNull()
    expect(t).not.toMatch(/ticket/i)
    expect(main.querySelector('a[href^="mailto:"]')).toBeNull()
  })
})

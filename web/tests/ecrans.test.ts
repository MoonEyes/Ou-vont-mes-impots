// @vitest-environment happy-dom
// Tests de rendu des 10 écrans sur des fixtures (extraits réels de site/data).
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
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('écrans', () => {
  it('1. saisie : formulaire, aide à la saisie, mention de confidentialité', async () => {
    await ecran('#/')
    expect(main.querySelector('h1')?.textContent).toContain('Où va l’argent')
    expect(main.querySelector('#p1-net')).not.toBeNull()
    expect(texte()).toContain('Net à payer avant impôt sur le revenu')
    expect(texte()).toContain('rien de ce que tu saisis n’est envoyé')
    expect(document.querySelector('a[aria-current=page]')?.getAttribute('href')).toBe('#/')
  })

  it('1. saisie : salaire manquant signalé sur le champ', async () => {
    await ecran('#/')
    main.querySelector<HTMLFormElement>('#formulaire')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => main.querySelector('#p1-net')?.getAttribute('aria-invalid') === 'true')
    expect(main.querySelector('#p1-msg')?.textContent).toContain('supérieur à 0')
  })

  it('1. saisie : profil hors V1, message de sortie et redirection', async () => {
    await ecran('#/')
    const s = main.querySelector<HTMLSelectElement>('#p1-statut')!
    s.value = 'fonctionnaire'
    s.dispatchEvent(new Event('change', { bubbles: true }))
    main.querySelector<HTMLFormElement>('#formulaire')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => !!main.querySelector('#retour .avertissement'))
    expect(texte()).toContain('pension civile')
    expect(main.querySelector('#retour a')?.getAttribute('href')).toBe('./#/etat')
  })

  it('1 puis 2. calcul complet puis « Ce que tu paies »', async () => {
    await ecran('#/')
    ;(main.querySelector('#p1-net') as HTMLInputElement).value = '2100'
    main.querySelector<HTMLFormElement>('#formulaire')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => session.resultat !== null, 60000)
    expect(location.hash).toBe('#/paie')
    await ecran('#/paie')
    expect(texte()).toContain('Chaque année, ton foyer paie')
    expect(texte()).toContain('1 004 €') // impôt C04 (OpenFisca : 1 004 €)
    expect(texte()).toContain('CADES')
    expect(texte()).toContain('Agirc-Arrco')
    expect(texte()).toContain('ce que paie ton employeur')
    expect(texte()).toContain('Estimation à venir')
    const patronal = main.querySelector('[aria-labelledby=titre-patronal]')!
    expect(patronal.querySelectorAll('.lignes li').length).toBeGreaterThan(8)
    await attendreQue(() => main.querySelectorAll('#par-destinataire li').length > 0)
    main.querySelector<HTMLButtonElement>('#avec-patronal')!.click()
    await attendreQue(() => main.querySelector('#avec-patronal')?.getAttribute('aria-pressed') === 'true')
    expect(texte()).toContain('Assurance maladie')
  }, 90000)

  it('3. sur 100 € : grands postes, part empruntée, choix du millésime', async () => {
    await ecran('#/etat')
    expect(texte()).toContain('30,5 € empruntés')
    expect(main.querySelectorAll('.barres li').length).toBe(12)
    const somme = Array.from(main.querySelector('.empile')!.querySelectorAll<HTMLElement>('span')).reduce((s, x) => s + Number(x.dataset.l), 0)
    expect(somme).toBeGreaterThan(99.9)
    expect(somme).toBeLessThan(100.1)
    expect(texte()).toContain('sur ton impôt sur le revenu')
    expect(texte()).toContain('Traçabilité de ce bloc')
    await ecran('#/etat?m=lfi2025')
    expect(texte()).toContain('27,4 € empruntés')
  })

  it('4. détail : fil d’Ariane, barres, sous-arbre chargé à la demande', async () => {
    await ecran('#/detail?m=execution2024&id=Education%20et%20recherche%2FEnseignement%20scolaire%2F141')
    expect(main.querySelectorAll('.fil-ariane li').length).toBe(4)
    expect(texte()).toContain('Enseignement en collège')
    expect(texte()).toContain('Version texte du diagramme')
    expect(main.querySelector('a[href="#/concret?p=141"]')).not.toBeNull()
    expect(requetes).toContain('data/arbre/Education-et-recherche_Enseignement-scolaire_141.json')
  })

  it('5. concrètement : nature de la dépense et effectifs', async () => {
    await ecran('#/concret?p=141')
    expect(texte()).toContain('Salaires (rémunérations d')
    expect(texte()).toContain('452 033')
    expect(texte()).toContain('coût complet employeur')
  })

  it('5. donnée absente : bloc masqué, le reste s’affiche', async () => {
    await ecran('#/concret?p=999')
    expect(texte()).toContain('non disponible')
  })

  it('6. qui reçoit l’argent : associations, France 2030, marchés', async () => {
    await ecran('#/beneficiaires?p=141')
    expect(texte()).toContain('INGENIEURS POUR L ECOLE')
    expect(main.querySelector('.voir-plus')).not.toBeNull()
    await ecran('#/beneficiaires?onglet=france2030')
    expect(texte()).toContain('8 730 projets')
    await ecran('#/beneficiaires?onglet=marches')
    expect(texte()).toContain('6 147 marchés')
  })

  it('7. ce qui a été fait : prévu/dépensé, trous, indicateurs, Cour des comptes', async () => {
    await ecran('#/realisations?p=141')
    expect(texte()).toContain('Aucune donnée d\'exécution par programme')
    expect(texte()).toContain('Tendance')
    expect(texte()).toContain('Pourquoi')
    expect(main.querySelector('a[href^="https://www.ccomptes.fr"]')).not.toBeNull()
    expect(main.querySelector('#plus-ind')).not.toBeNull()
  })

  it('8. vie politique : programme 232, partis, candidats', async () => {
    await ecran('#/vie-politique?a=2022')
    expect(texte()).toContain('Programme 232')
    expect(texte()).toContain('RASSEMBLEMENT NATIONAL')
    const b = Array.from(main.querySelectorAll<HTMLButtonElement>('[data-fichier]')).find((x) => x.dataset.fichier?.includes('presidentielle_2022'))!
    b.click()
    await attendreQue(() => (main.querySelector('#candidats')?.textContent ?? '').includes('ARTHAUD'))
    expect(texte()).toContain('12 comptes')
  })

  it('9. recettes : chaque impôt et qui l’encaisse depuis 2005', async () => {
    await ecran('#/recettes?i=D211')
    expect(texte()).toContain('TVA en 2025')
    expect(main.querySelectorAll('tbody tr').length).toBeGreaterThanOrEqual(21)
    expect(texte()).toContain('2005')
  })

  it('10. méthode, mentions légales et confidentialité', async () => {
    await ecran('#/methode')
    expect(texte()).toContain('Doubles comptes')
    expect(texte()).toContain('Remboursements et dégrèvements'.toLowerCase().slice(0, 10))
    expect(texte()).toContain('Apache-2.0')
    await ecran('#/mentions')
    expect(texte()).toContain('Aucun cookie')
    expect(texte()).toContain('LCEN')
  })

  it('aucun attribut style en ligne (CSP) ni tiret long dans les écrans', async () => {
    for (const f of ['#/', '#/paie', '#/etat', '#/detail', '#/concret?p=141', '#/beneficiaires?p=141', '#/realisations?p=141', '#/vie-politique?a=2024', '#/recettes', '#/methode', '#/mentions']) {
      await ecran(f)
      // Seules les largeurs posées par le CSSOM (data-l, data-g) sont autorisées : pas de style en ligne dans le HTML.
      const fautifs = Array.from(main.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l') && !el.hasAttribute('data-g'))
      expect(fautifs.length, f).toBe(0)
      expect(main.textContent, f).not.toContain('\u2014')
    }
  })

  it('toutes les lectures de données sont relatives au site', () => {
    expect(requetes.length).toBeGreaterThan(10)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })
})

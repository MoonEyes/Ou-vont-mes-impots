// @vitest-environment happy-dom
// Tests de rendu des 10 écrans sur des fixtures (extraits réels de site/data).
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { session } from '../src/etat'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { attendreQue, monterPage, requetes } from './aide-dom'

const eurFr = (x: number) => `${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(Math.round(x))} €`.replace(/\s+/g, ' ')

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

  it('1 puis 2. calcul complet puis « Ce que tu finances »', async () => {
    await ecran('#/')
    ;(main.querySelector('#p1-net') as HTMLInputElement).value = '2100'
    main.querySelector<HTMLFormElement>('#formulaire')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => session.resultat !== null, 60000)
    expect(location.hash).toBe('#/paie')
    await ecran('#/paie')
    expect(texte()).toContain('Ce que tu finances en un an')
    expect(texte()).toMatch(/Sur 100 € : \d+ € Sécurité sociale/)
    expect(texte()).toContain('1 004 €') // impôt C04 (OpenFisca : 1 004 €)
    expect(texte()).toContain('CADES')
    expect(texte()).toContain('Agirc-Arrco')
    expect(texte()).toContain('ce que paie ton employeur')
    expect(texte()).toContain('Taxes sur ta consommation')
    expect(texte()).toContain('Assurance maladie 46 %, Branche autonomie 23 %, Unédic')
    const patronal = main.querySelector('[aria-labelledby=titre-patronal]')!
    expect(patronal.querySelectorAll('.lignes li').length).toBeGreaterThan(8)
    await attendreQue(() => main.querySelectorAll('#par-destinataire li').length > 0)
    main.querySelector<HTMLButtonElement>('#avec-patronal')!.click()
    await attendreQue(() => main.querySelector('#avec-patronal')?.getAttribute('aria-pressed') === 'true')
    expect(texte()).toContain('Assurance maladie')
  }, 90000)

  it('2. cas 2 100 € net, locataire à Lyon : taxes conso du 5e décile, TEOM, total complet', async () => {
    await ecran('#/')
    ;(main.querySelector('#p1-net') as HTMLInputElement).value = '2100'
    const dep = main.querySelector<HTMLSelectElement>('#departement')!
    dep.value = '69'
    dep.dispatchEvent(new Event('change', { bubbles: true }))
    await attendreQue(() => !!main.querySelector('#commune option[value="69123"]'))
    main.querySelector<HTMLSelectElement>('#commune')!.value = '69123'
    session.resultat = null
    session.complet = null
    main.querySelector<HTMLFormElement>('#formulaire')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => session.complet !== null && session.resultat !== null, 60000)
    const tva = JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/data/prelevements/tva_conso.json'), 'utf8'))
    const c = session.complet!
    expect(c.placement!.decile).toBe(5)
    const conso = c.conso.reduce((s, l) => s + l.montant_annuel_eur.central, 0)
    expect(conso).toBeCloseTo(tva.tranches[4].taxes_produits_eur_par_uc.central, 0)
    expect(c.locaux.map((l) => l.id)).toEqual(['teom'])
    expect(c.locaux[0].non_chiffre).toBeUndefined()
    await ecran('#/paie')
    expect(texte()).toContain('5e décile')
    expect(texte()).toContain('dans tes charges')
    expect(main.querySelector('.recap .surligne')?.textContent?.replace(/\s+/g, ' ')).toBe(eurFr(c.total.central))
    expect(texte()).toContain(`Fourchette : ${eurFr(c.total.bas)} à ${eurFr(c.total.haut)}`)
    // Sur 100 € : la somme des parts affichées fait 100.
    const parts = [...(main.querySelector('.recap-sur100')?.textContent ?? '').matchAll(/(\d+) €/g)].map((m) => Number(m[1]))
    expect(parts.slice(1).reduce((a, b) => a + b, 0)).toBe(100)
    writeFileSync(join(process.cwd(), 'ecarts_cas_types.json').replace('ecarts_cas_types', 'affichage_lyon'), JSON.stringify(c.total))
  }, 90000)

  it('3. sur 100 € : grands postes, part empruntée, choix du millésime', async () => {
    await ecran('#/etat')
    expect(texte()).toContain('30,5 € ont été empruntés')
    expect(main.querySelectorAll('.barres li').length).toBe(12)
    const somme = Array.from(main.querySelector('.empile')!.querySelectorAll<HTMLElement>('span')).reduce((s, x) => s + Number(x.dataset.l), 0)
    expect(somme).toBeGreaterThan(99.9)
    expect(somme).toBeLessThan(100.1)
    expect(texte()).toContain('sur ce que tu verses à l’État')
    expect(texte()).toContain('Et ce que tu finances ?')
    expect(texte()).toContain('Traçabilité de ce bloc')
    await ecran('#/etat?m=lfi2025')
    expect(texte()).toContain('27,4 € ont été empruntés')
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

  it('règles 1, 5 et surligneur : chiffre clé en euros et sur 100 €, un seul surligneur, titres sans adjectif évaluatif', async () => {
    const INTERDITS = /\b(gaspillage|seulement|énorme|opaque|scandale|trop)\b/i
    for (const f of ['#/', '#/paie', '#/etat', '#/etat?m=lfi2025', '#/detail', '#/detail?m=execution2024&id=Education%20et%20recherche%2FEnseignement%20scolaire%2F141', '#/concret?p=141', '#/beneficiaires?p=141', '#/beneficiaires?onglet=marches', '#/beneficiaires?onglet=france2030', '#/realisations?p=141', '#/vie-politique?a=2024', '#/vie-politique?a=2021', '#/recettes', '#/methode', '#/mentions']) {
      await ecran(f)
      const surlignes = main.querySelectorAll('.surligne')
      expect(surlignes.length, f).toBeLessThanOrEqual(1)
      for (const el of Array.from(surlignes)) {
        expect(el.textContent, f).toMatch(/€/)
        const cle = el.closest('[data-cle]')
        expect(cle, `${f} : chiffre clé sans conteneur data-cle`).not.toBeNull()
        expect(cle!.textContent, f).toMatch(/sur 100 €/i)
      }
      for (const t of Array.from(main.querySelectorAll('h1, h2, h3'))) expect(t.textContent ?? '', f).not.toMatch(INTERDITS)
      expect(document.title).not.toMatch(INTERDITS)
    }
  })

  it('toutes les lectures de données sont relatives au site', () => {
    expect(requetes.length).toBeGreaterThan(10)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })
})

// @vitest-environment happy-dom
// Tests de rendu des 10 écrans sur des fixtures (extraits réels de site/data).
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher, redirection } from '../src/routeur'
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
  it('accueil : promesse, action unique répétée, étapes, garanties', async () => {
    await ecran('#/')
    expect(main.querySelector('h1')?.textContent).toBe('Où va l’argent que tu paies ?')
    expect(texte()).toContain('Indique ton salaire. Tu vois ce que tu verses chaque année, à qui, et à quoi cet argent sert.')
    const boutons = Array.from(main.querySelectorAll('a.bouton-principal'))
    expect(boutons).toHaveLength(2)
    for (const b of boutons) {
      expect(b.textContent).toBe('Calculer à partir de mon salaire')
      expect(b.getAttribute('href')).toBe('#/calcul')
    }
    expect(texte()).toContain('Environ 2 minutes. Aucun compte à créer.')
    expect(main.querySelector('a[href="#/explorer"]')?.textContent).toBe('Explorer sans saisir mon salaire')
    expect(main.querySelectorAll('.etapes li')).toHaveLength(3)
    expect(texte()).toContain('Rien ne quitte ton téléphone.')
    expect(texte()).toContain('jusqu’à la ligne du budget voté')
    expect(texte()).toContain('Site non officiel, réalisé à partir de données publiques ouvertes.')
    expect(main.querySelector('.fil-ariane')).toBeNull()
    expect(document.querySelector('.navigation [aria-current=page]')?.getAttribute('href')).toBe('#/')
  })

  it('1. saisie : formulaire, aide à la saisie, mention de confidentialité', async () => {
    await ecran('#/calcul')
    expect(main.querySelector('#p1-net')).not.toBeNull()
    expect(texte()).toContain('Net à payer avant impôt sur le revenu')
    expect(texte()).toContain('rien de ce que tu saisis n’est envoyé')
    expect(document.querySelector('.navigation [aria-current=page]')?.getAttribute('href')).toBe('#/calcul')
    expect(main.querySelector('nav.fil-ariane')).toBeNull()
  })

  it('1. saisie : salaire manquant signalé sur le champ', async () => {
    await ecran('#/calcul')
    main.querySelector<HTMLFormElement>('#formulaire')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => main.querySelector('#p1-net')?.getAttribute('aria-invalid') === 'true')
    expect(main.querySelector('#p1-msg')?.textContent).toContain('supérieur à 0')
  })

  it('1. saisie : profil hors V1, message de sortie et redirection', async () => {
    await ecran('#/calcul')
    const s = main.querySelector<HTMLSelectElement>('#p1-statut')!
    s.value = 'fonctionnaire'
    s.dispatchEvent(new Event('change', { bubbles: true }))
    main.querySelector<HTMLFormElement>('#formulaire')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => !!main.querySelector('#retour .avertissement'))
    expect(texte()).toContain('pension civile')
    expect(main.querySelector('#retour a')?.getAttribute('href')).toBe('./#/explorer')
  })

  it('1 puis 2. calcul complet puis « Ce que tu finances »', async () => {
    await ecran('#/calcul')
    ;(main.querySelector('#p1-net') as HTMLInputElement).value = '2100'
    main.querySelector<HTMLFormElement>('#formulaire')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => session.resultat !== null, 60000)
    expect(location.hash).toBe('#/calcul/resultat')
    await ecran('#/calcul/resultat')
    expect(main.querySelector('nav.fil-ariane [aria-current=page]')?.textContent).toBe('Résultat')
    for (const [t, href] of [['Où va l’argent de l’État', '#/explorer/etat'], ['Ta commune', '#/local'], ['Qui le reçoit', '#/beneficiaires']])
      expect(Array.from(main.querySelectorAll('.cartes a')).find((a) => a.textContent?.includes(t))?.getAttribute('href')).toBe(href)
    expect(main.querySelector('#partager-carte')?.textContent).toBe('Partager ma carte')
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
    await ecran('#/calcul')
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
    await ecran('#/calcul/resultat')
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
    expect(main.querySelectorAll('nav[aria-label="Position dans l’arbre"] li').length).toBe(4)
    expect(main.querySelectorAll('nav[aria-label="Fil d\'Ariane"] li').length).toBe(4)
    expect(texte()).toContain('Enseignement en collège')
    expect(texte()).toContain('Version texte du diagramme')
    expect(main.querySelector('a[href="#/beneficiaires/programme?p=141"]')).not.toBeNull()
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
    for (const f of ['#/', '#/calcul', '#/calcul/resultat', ...ROUTES.map((r) => '#' + r.chemin), '#/concret?p=141', '#/beneficiaires?p=141', '#/realisations?p=141', '#/vie-politique?a=2024', '#/local/commune?insee=69123', '#/decisions/votes?p=141']) {
      await ecran(f)
      // Seules les largeurs posées par le CSSOM (data-l, data-g) sont autorisées : pas de style en ligne dans le HTML.
      const fautifs = Array.from(main.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l') && !el.hasAttribute('data-g'))
      expect(fautifs.length, f).toBe(0)
      expect(main.textContent, f).not.toContain('\u2014')
    }
  })

  it('règles 1, 5 et surligneur : chiffre clé en euros et sur 100 €, un seul surligneur, titres sans adjectif évaluatif', async () => {
    const INTERDITS = /\b(gaspillage|seulement|énorme|opaque|scandale|trop)\b/i
    for (const f of [...ROUTES.map((r) => '#' + r.chemin), '#/local/commune?insee=69123', '#/explorer/ue?dep=69', '#/etat?m=lfi2025', '#/detail', '#/detail?m=execution2024&id=Education%20et%20recherche%2FEnseignement%20scolaire%2F141', '#/concret?p=141', '#/beneficiaires?p=141', '#/beneficiaires?onglet=marches', '#/beneficiaires?onglet=france2030', '#/realisations?p=141', '#/vie-politique?a=2024', '#/vie-politique?a=2021', '#/recettes', '#/methode', '#/mentions']) {
      await ecran(f)
      const surlignes = main.querySelectorAll('.surligne')
      expect(surlignes.length, f).toBeLessThanOrEqual(1)
      for (const el of Array.from(surlignes)) {
        // Un surligneur posé sur un chiffre : montant en euros et « sur 100 € » à côté.
        if (!/\d/.test(el.textContent ?? '')) continue
        expect(el.textContent, f).toMatch(/€/)
        const cle = el.closest('[data-cle]')
        expect(cle, `${f} : chiffre clé sans conteneur data-cle`).not.toBeNull()
        expect(cle!.textContent, f).toMatch(/sur 100 €/i)
      }
      for (const t of Array.from(main.querySelectorAll('h1, h2, h3'))) expect(t.textContent ?? '', f).not.toMatch(INTERDITS)
      expect(document.title).not.toMatch(INTERDITS)
    }
  })

  it('anciennes adresses : chacune redirige vers la nouvelle, paramètres conservés', async () => {
    const cas: [string, string][] = [
      ['#/paie', '#/calcul/resultat'],
      ['#/etat?m=lfi2025', '#/explorer/etat?m=lfi2025'],
      ['#/detail?m=execution2024&id=Justice', '#/explorer/etat/detail?m=execution2024&id=Justice'],
      ['#/concret?p=141', '#/beneficiaires/programme?p=141'],
      ['#/realisations?p=141', '#/decisions/realisations?p=141'],
      ['#/vie-politique?a=2022', '#/decisions/vie-politique?a=2022'],
      ['#/recettes?i=D211', '#/explorer/recettes?i=D211'],
    ]
    for (const [ancien, nouveau] of cas) {
      expect(redirection(ancien), ancien).toBe(nouveau)
      if (ancien === '#/paie') continue
      await ecran(ancien)
      expect(location.hash, ancien).toBe(nouveau)
    }
  })

  it('résultat sans saisie : retour au formulaire avec un message', async () => {
    const r = session.resultat
    session.resultat = null
    await ecran('#/calcul/resultat')
    expect(location.hash).toBe('#/calcul?retour=resultat')
    await ecran(location.hash)
    expect(texte()).toContain('Indique d’abord ton salaire')
    session.resultat = r
  })

  it('chaque route rend un titre, un fil d’Ariane dès le niveau 2 et au moins une sortie', async () => {
    const params: Record<string, string> = {
      '/explorer/etat/detail': '?id=Justice',
      '/local/commune': '?insee=69123',
      '/beneficiaires/programme': '?p=141',
      '/decisions/realisations': '?p=141',
      '/decisions/votes': '?p=141',
      '/explorer/ue': '?dep=69',
      '/decisions/controle': '?dep=69',
    }
    for (const r of ROUTES) {
      await ecran(`#${r.chemin}${params[r.chemin] ?? ''}`)
      expect(main.querySelector('h1')?.textContent?.trim(), r.chemin).toBeTruthy()
      expect(main.querySelector('.erreur'), `${r.chemin} : erreur affichée`).toBeNull()
      if (r.parent) {
        const fil = main.querySelector('nav[aria-label="Fil d\'Ariane"]')
        expect(fil, r.chemin).not.toBeNull()
        expect(fil!.querySelector('[aria-current=page]')?.getAttribute('href'), r.chemin).toBe(`#${r.chemin}`)
      }
      const sorties = Array.from(main.querySelectorAll('a[href^="#/"]')).filter((a) => !a.closest('.fil-ariane'))
      expect(sorties.length, `${r.chemin} : aucune sortie`).toBeGreaterThan(0)
      // Ancres qui nomment leur destination (pas de « cliquez ici »).
      for (const a of sorties) expect(a.textContent ?? '', r.chemin).not.toMatch(/^\s*(ici|cliquez ici|lien|en savoir plus)\s*$/i)
    }
  }, 120000)

  it('pages des jeux branchés : secu, UE, dette, niches, commune, votes, contrôle', async () => {
    await ecran('#/explorer/secu')
    expect(texte()).toContain('Traçabilité de ce bloc')
    expect(texte()).toMatch(/sur 100 €/)
    await ecran('#/explorer/ue?dep=69')
    expect(texte()).toContain('22,3 Md€')
    expect(texte()).toContain('Principaux bénéficiaires')
    await ecran('#/explorer/dette')
    expect(texte()).toContain('Qui détient la dette')
    await ecran('#/explorer/niches')
    expect(texte()).toContain('89,4 Md€')
    await ecran('#/local/commune?insee=69123')
    expect(main.querySelector('h1')?.textContent).toBe('Lyon')
    expect(texte()).toContain('Dotation globale de fonctionnement')
    expect(texte()).toContain('Les taux d’impôts locaux votés')
    expect(main.querySelector('a[href="#/explorer/collectivites"]')).not.toBeNull()
    await ecran('#/decisions/votes?p=141')
    expect(texte()).toContain('Mouvements de crédits publiés au Journal officiel')
    await ecran('#/decisions/controle?dep=69')
    expect(texte()).toContain('représentants d’intérêts')
  }, 60000)

  it('dette et contrôle : état « en cours d’intégration » propre si les fichiers manquent', async () => {
    const { rendre } = await import('../src/ecrans/dette')
    const { viderCache } = await import('../src/donnees')
    viderCache()
    const vrai = globalThis.fetch
    globalThis.fetch = (async (u: string) => (String(u).includes('dette/') ? new Response('', { status: 404 }) : vrai(u))) as typeof fetch
    const z = document.createElement('div')
    await rendre(z)
    expect(z.textContent).toContain('Données en cours d’intégration')
    globalThis.fetch = vrai
    viderCache()
  })

  it('opérateurs : liste filtrable et triable, fiches, statuts de traçabilité, aucune personne nommée', async () => {
    await ecran('#/explorer/operateurs')
    expect(main.querySelector('h1')?.textContent).toBe('Les opérateurs de l’État')
    expect(texte()).toMatch(/sur 100 € de subventions/)
    for (const l of ['Tracé', 'Approché nommé', 'Approché par catégorie']) expect(texte()).toContain(l)
    // Filtre par catégorie d'opérateurs
    const cat = main.querySelector<HTMLSelectElement>('#op-categorie')!
    cat.value = '__categorie'
    cat.dispatchEvent(new Event('input', { bubbles: true }))
    const lignes = main.querySelectorAll('#liste-op details[data-id]')
    expect(lignes.length).toBe(4)
    // Fiche d'une catégorie : séries, LFI 2025, établissements, rémunérations en somme seulement
    const d = lignes[0] as HTMLDetailsElement
    d.open = true
    d.dispatchEvent(new Event('toggle'))
    const fiche = d.querySelector('.fiche')!.textContent ?? ''
    expect(fiche).toContain('2025 (LFI)')
    expect(fiche).toContain('Approché par catégorie')
    expect(fiche).toMatch(/dix plus hautes rémunérations 2024 \(somme\)/)
    // Tri par nom
    cat.value = ''
    const tri = main.querySelector<HTMLSelectElement>('#op-tri')!
    tri.value = 'nom'
    tri.dispatchEvent(new Event('input', { bubbles: true }))
    const noms = Array.from(main.querySelectorAll('#liste-op summary')).map((x) => x.textContent ?? '')
    expect(noms).toEqual([...noms].sort((a, b) => a.localeCompare(b, 'fr')))
    // Depuis un programme
    await ecran('#/beneficiaires/programme?p=141')
    expect(main.querySelector('a[href="#/explorer/operateurs?p=141"]')?.textContent).toBe('Opérateurs financés par ce programme')
    await ecran('#/explorer/operateurs?p=141')
    expect(texte()).toContain('Opérateurs financés par le programme 141')
    expect(main.querySelectorAll('#liste-op details[data-id]').length).toBeGreaterThan(0)
    expect(Array.from(main.querySelectorAll('.cartes a, .voir-aussi a')).length).toBeGreaterThan(0)
  })

  it('traçabilité : taux lu dans les données, lien vers les opérateurs', async () => {
    await ecran('#/methode/tracabilite')
    expect(texte()).toContain('69,14 %')
    expect(main.querySelector('a[href="#/explorer/operateurs"]')).not.toBeNull()
  })

  it('la démarche : textes, nombre de sources et part non publiée lus dans les données', async () => {
    await ecran('#/demarche')
    expect(main.querySelector('h1')?.textContent).toBe('Pourquoi ce site, et comment il est fait')
    expect(main.querySelector('.surligne')?.textContent).toBe('où va ton argent ?')
    expect(main.querySelectorAll('.etapes li')).toHaveLength(4)
    expect(texte()).toContain('Plus de 120 sources publiques ouvertes')
    expect(texte()).toContain('Et sur 100 € dépensés par l’État, 31 € n’ont pas de destinataire publié.')
    expect(main.querySelector('a[href$="/issues"]')?.textContent).toBe('Signale-la sur GitHub')
    expect(main.querySelector('a[href="#/methode"]')?.textContent).toBe('Méthode détaillée')
    expect(document.querySelector('#bouton-plus')?.getAttribute('aria-current')).toBe('page')
    await ecran('#/')
    expect(texte()).toContain('Plus de 120 sources publiques, vérifiées et reliées entre elles.')
    expect(main.querySelector('a[href="#/demarche"]')?.textContent).toBe('La démarche')
  })

  it('toutes les lectures de données sont relatives au site', () => {
    expect(requetes.length).toBeGreaterThan(10)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })
})

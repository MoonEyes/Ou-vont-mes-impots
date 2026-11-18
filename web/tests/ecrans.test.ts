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
  it('accueil : billet découpé de l’exemple, champ qui lance le calcul, étapes, garanties', async () => {
    await ecran('#/')
    expect(main.querySelector('h1')?.textContent?.replace(/\s+/g, ' ')).toBe('Tu verses 100 €. Voilà où ils partent.')
    expect(texte()).toContain('on additionne tout ce que tu verses en un an, puis on suit chaque euro jusqu’à ceux qui le reçoivent.')
    // Un seul bouton principal : celui du champ salaire, qui lance le calcul.
    const boutons = Array.from(main.querySelectorAll('.bouton-principal'))
    expect(boutons).toHaveLength(1)
    expect(boutons[0].textContent).toBe('Découper mon billet')
    expect(main.querySelector('#heros-form #heros-net')).not.toBeNull()
    expect(main.querySelector('label[for="heros-net"]')?.textContent).toBe('Ton salaire net par mois')
    expect(texte()).toContain('Aucun compte, rien n’est envoyé. Environ 2 minutes.')
    expect(main.querySelector('a.bouton[href="#/explorer"]')?.textContent).toBe('Tout explorer')
    expect(main.querySelectorAll('.etapes li')).toHaveLength(3)
    expect(texte()).toContain('Rien ne quitte ton navigateur')
    expect(texte()).toContain('jusqu’à la ligne du budget voté')
    expect(texte()).toContain('Une démarche citoyenne et indépendante')
    expect(texte()).toContain('site non officiel, gratuit, sans publicité')
    expect(main.querySelector('.fil-ariane')).toBeNull()
    expect(document.querySelector('.entete [aria-current=page]')?.getAttribute('href')).toBe('#/')
    expect(document.querySelector('.navigation [aria-current=page]')).toBeNull()
    // Le billet : parts proportionnelles en liens, dont la somme fait 100, lues dans l'exemple (jamais en dur).
    const ex = JSON.parse(readFileSync(join(process.cwd(), 'src/exemple-lyon.json'), 'utf8'))
    const billet = main.querySelector('.billet .billet-large')!
    expect(ex.profil.commune.toLowerCase()).toBe('lyon')
    expect(billet.getAttribute('aria-label')).toContain('à Lyon')
    const parts = Array.from(billet.querySelectorAll('a')).map((a) => a.getAttribute('aria-label') ?? '')
    expect(parts.map((p) => Number(/: (\d+) €/.exec(p)![1])).reduce((a, b) => a + b, 0)).toBe(100)
    expect(parts[0]).toBe(`Sécurité sociale : ${ex.sur100['Securite sociale']} € sur 100 €`)
    expect(texte()).toContain(`Billet affiché : celui d’un salaire de ${eurFr(ex.profil.net_mensuel)} net par mois, à Lyon.`)
    expect(texte()).toContain(eurFr(ex.total.central))
    expect(main.querySelectorAll('.parts li')).toHaveLength(parts.length)
    // Les 8 caisses, avec leur chiffre lu dans les données.
    expect(main.querySelectorAll('.tuiles a')).toHaveLength(8)
    expect(main.querySelector('[data-caisse="dette"] .t-chiffre')?.textContent?.replace(/\s+/g, ' ')).toBe('3 460 Md€')
    expect(main.querySelector('[data-caisse="etat"] .t-chiffre')?.textContent).toMatch(/^\d+ Md€$/)
  })

  it('accueil : le champ du héros garde le salaire en mémoire (jamais dans une adresse) et ouvre le calcul', async () => {
    await ecran('#/')
    ;(main.querySelector('#heros-net') as HTMLInputElement).value = 'deux mille'
    main.querySelector<HTMLFormElement>('#heros-form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    expect(main.querySelector('#heros-net')?.getAttribute('aria-invalid')).toBe('true')
    expect(main.querySelector('#heros-msg')?.textContent).toBe('Écris ton salaire en chiffres.')
    ;(main.querySelector('#heros-net') as HTMLInputElement).value = ''
    main.querySelector<HTMLFormElement>('#heros-form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    expect(location.hash).toBe('#/calcul')
    expect(session.amorce).toBeNull()
  })

  it('accueil : texte affiché sans attendre les données, puis nombre de sources ; recherche « à quoi servent mes impôts »', async () => {
    const { rendre } = await import('../src/ecrans/accueil')
    const zone = document.createElement('div')
    const rendu = rendre(zone)
    // Rendu synchrone : le titre, le billet, l'action et les rubriques sont là avant toute lecture de données.
    expect(zone.querySelector('h1')?.textContent).toContain('Voilà où ils partent.')
    expect(zone.querySelector('.billet svg')).not.toBeNull()
    expect(Array.from(zone.querySelectorAll('h2')).map((x) => x.textContent)).toContain('À quoi servent mes impôts ?')
    expect(zone.querySelector('#nb-sources')?.textContent).toBe('Des sources publiques')
    expect(zone.querySelector('a[href="#/local"]')?.textContent).toBe('Budget de ma commune')
    await rendu.suite
    expect(zone.querySelector('#nb-sources')?.textContent).toBe('Plus de 120 sources publiques')
  })

  it('adresse inconnue : page introuvable, avec le billet 4-0-4 et deux sorties', async () => {
    await ecran('#/nimporte-quoi')
    expect(main.querySelector('h1')?.textContent).toBe('Ce billet-là, on ne le trouve pas')
    expect(Array.from(main.querySelectorAll('.actions a')).map((a) => a.getAttribute('href'))).toEqual(['#/', '#/explorer'])
    expect(document.title).toBe('Page introuvable · Où vont mes impôts')
    expect(document.querySelector('.entete [aria-current=page]')).toBeNull()
  })

  it('titres de recherche : calcul, hub local, commune et département', async () => {
    await ecran('#/calcul')
    expect(document.title).toBe('Combien je verse d’impôts et de cotisations : calcul à partir du salaire · Où vont mes impôts')
    await ecran('#/local')
    expect(main.querySelector('h1')?.textContent).toBe('Budget de ma commune')
    expect(document.title).toBe('Budget de ma commune · Où vont mes impôts')
    expect(main.querySelectorAll('.liste-colonnes a')).toHaveLength(101)
    expect(main.querySelector('.liste-colonnes a[href="#/local/departement?dep=69&page=rhone"]')?.textContent).toBe('Rhône (69)')
    expect(main.querySelector('.trame a[href="#/local/departement?dep=69&page=rhone"]')?.getAttribute('aria-label')).toBe('69 Rhône')
    expect(main.querySelectorAll('.trame a')).toHaveLength(101)
    await ecran('#/local/commune?insee=69123')
    expect(document.title).toBe('Budget de Lyon (Rhône) : dépenses, dotations, taux · Où vont mes impôts')
    expect(Array.from(main.querySelectorAll('.fil-ariane a')).map((a) => a.textContent)).toEqual(['Accueil', 'Chez moi', 'Rhône', 'Lyon'])
    // Au moins trois chiffres propres à la commune, en texte.
    expect(texte()).toMatch(/[\d\s]+ habitants/)
    expect(texte()).toMatch(/de dépenses en \d{4}, soit [\d\s]+ € par habitant/)
    expect(texte()).toMatch(/Dette en cours : [\d,\s]+ (M€|Md€|k€|€)/)
    await ecran('#/local/departement?dep=69')
    expect(main.querySelector('h1')?.textContent).toBe('Rhône (69)\u00a0: le budget des communes')
    expect(main.querySelector('.ou-cest .trame a.t-ici')?.getAttribute('aria-label')).toBe('69 Rhône')
    expect(document.title).toBe('Rhône (69) : budget des communes, dépenses, dotations, taux · Où vont mes impôts')
    expect(main.querySelector('a[href="#/local/commune?insee=69123&page=lyon"]')?.textContent).toBe('Lyon')
    expect(texte()).toContain('Communes de plus de 5 000 habitants')
    const { deCommune } = await import('../src/ecrans/commune')
    expect(['Nantes', 'Angers', 'Le Mans', 'Les Abymes', 'La Rochelle', 'Évreux'].map(deCommune)).toEqual(['de Nantes', 'd’Angers', 'du Mans', 'des Abymes', 'de La Rochelle', 'd’Évreux'])
  })

  it('1. saisie : formulaire, aide à la saisie, mention de confidentialité', async () => {
    await ecran('#/calcul')
    expect(main.querySelector('#p1-net')).not.toBeNull()
    expect(texte()).toContain('Net à payer avant impôt sur le revenu')
    expect(texte()).toContain('rien de ce que tu saisis n’est envoyé')
    expect(document.querySelector('.navigation [aria-current=page]')?.getAttribute('href')).toBe('#/calcul')
    expect(Array.from(main.querySelectorAll('nav.fil-ariane a')).map((a) => a.textContent)).toEqual(['Accueil', 'Mon calcul'])
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
    s.value = 'demandeur_emploi'
    s.dispatchEvent(new Event('change', { bubbles: true }))
    main.querySelector<HTMLFormElement>('#formulaire')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => !!main.querySelector('#retour .avertissement'))
    expect(texte()).toContain('allocations chômage')
    expect(main.querySelector('#retour a')?.getAttribute('href')).toBe('./#/explorer')
  })

  it('1 puis 2. calcul complet puis « Ce que tu verses »', async () => {
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
    expect(texte()).toContain('Ce que tu verses en un an')
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
    // L'exemple de l'accueil (billet, total, trois sorties) est ce calcul-ci, écrit dans src/exemple-lyon.json : jamais recopié à la main.
    const { resumer } = await import('../src/composants/resume-calcul')
    const exemple = { profil: { net_mensuel: 2100, commune: session.communeNom, insee: '69123' }, ...resumer(session.resultat!, c) }
    const fichier = join(process.cwd(), 'src/exemple-lyon.json')
    const avant = readFileSync(fichier, 'utf8')
    writeFileSync(fichier, JSON.stringify(exemple) + '\n')
    expect(JSON.parse(avant), 'src/exemple-lyon.json n’était plus à jour : il vient d’être réécrit, relance les tests').toEqual(exemple)
    // Le résultat porte le billet personnel, sa version tableau, la liste des parts et le fil de l'euro.
    expect(main.querySelectorAll('.billet .billet-large a')).toHaveLength(Object.keys(exemple.sur100).length)
    expect(main.querySelector('.billet-tableau table')).not.toBeNull()
    expect(main.querySelectorAll('.parts li')).toHaveLength(Object.keys(exemple.sur100).length)
    expect(main.querySelector('.fil-euro svg')).not.toBeNull()
    expect(texte()).toContain('Le fil de l’euro')
  }, 90000)

  it('3. sur 100 € : grands postes, part empruntée, choix du millésime', async () => {
    await ecran('#/etat')
    expect(texte()).toContain('30,5 € ont été empruntés')
    expect(main.querySelectorAll('.barres li').length).toBe(12)
    const somme = Array.from(main.querySelector('.empile')!.querySelectorAll<HTMLElement>('span')).reduce((s, x) => s + Number(x.dataset.l), 0)
    expect(somme).toBeGreaterThan(99.9)
    expect(somme).toBeLessThan(100.1)
    expect(texte()).toContain('sur ce que tu verses à l’État')
    expect(texte()).toContain('Et ce que tu verses ?')
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
      const fautifs = Array.from(main.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l') && !el.hasAttribute('data-g') && !el.hasAttribute('data-f'))
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
      '/local/departement': '?dep=69',
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
        // Commune et département : le dernier maillon porte le nom du lieu et son adresse propre.
        expect(fil!.querySelector('[aria-current=page]')?.getAttribute('href')?.split('?')[0], r.chemin).toBe(`#${r.chemin}`)
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
    // Fiche d'une catégorie : séries, budget voté 2025, établissements, rémunérations en somme seulement
    const d = lignes[0] as HTMLDetailsElement
    d.open = true
    d.dispatchEvent(new Event('toggle'))
    const fiche = d.querySelector('.fiche')!.textContent ?? ''
    expect(fiche).toContain('2025 (voté)')
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
    expect(texte()).toContain('Et sur 100 € dépensés par l’État, 31 € n’ont pas de destinataire publié en données ouvertes : cela décrit l’état de la publication, pas l’usage de l’argent.')
    expect(texte()).toContain('Le site ne soutient aucun parti, aucun candidat ni aucune position sur le niveau des impôts ou des dépenses.')
    expect(texte()).toContain('Chaque sujet est présenté avec les mêmes formats : montant, source, part tracée, écarts.')
    expect(main.querySelector('a[href$="/issues"]')?.textContent).toBe('Signale-la sur GitHub')
    expect(main.querySelector('a[href="#/methode"]')?.textContent).toBe('Méthode détaillée')
    expect(document.querySelector('.navigation [aria-current=page]')?.getAttribute('href')).toBe('#/demarche')
    await ecran('#/')
    expect(main.querySelector('#nb-sources')?.textContent).toBe('Plus de 120 sources publiques')
    expect(main.querySelector('a[href="#/demarche"]')?.textContent).toBe('Lire la démarche')
  })

  // Lexique neutre (charte docs/NEUTRALITE.md, règle 2) étendu à TOUT le texte affiché, pas seulement aux titres.
  // Liste partagée avec le test des données (tests/test_neutralite.py) : docs/lexique_neutre.json, où chaque règle dit
  // pourquoi le terme est exclu (effet de cadrage, réactance, effet de média hostile ; pratiques des Décodeurs, de
  // Full Fact et de The Markup). Bornes de mot Unicode : \b de JavaScript ignore les lettres accentuées.
  const LEXIQUE = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as {
    regles: { termes: string[]; raison: string }[]
    niche_definie: string
    exceptions: string[]
  }
  const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
  const LEXIQUE_INTERDIT: [RegExp, string][] = LEXIQUE.regles.map((r) => [borne(r.termes.join('|')), r.raison])
  // Libellés officiels reproduits tels quels (titres de publications, intitulé de programme), listés dans docs/NEUTRALITE.md.
  const EXCEPTIONS_DONNEES = LEXIQUE.exceptions
  // « Niche » n'est admis qu'avec sa définition : « dépense fiscale (souvent appelée niche fiscale) ».
  const NICHE_DEFINIE = new RegExp(LEXIQUE.niche_definie, 'giu')

  function verifierLexique(t: string, ou: string) {
    // Les chemins de fichiers et adresses (site/data/niches/index.json...) ne sont pas de la rédaction.
    let x = t.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
    for (const e of EXCEPTIONS_DONNEES) x = x.split(e).join(' ')
    for (const [re, raison] of LEXIQUE_INTERDIT) expect(x, `${ou} : ${raison} (${re})`).not.toMatch(re)
    expect(x.replace(NICHE_DEFINIE, ' '), `${ou} : « niche » sans définition`).not.toMatch(borne('niches?'))
  }

  it('lexique neutre : aucun terme évaluatif dans tout le texte affiché, pages, en-tête, pied, métadonnées, image de partage', async () => {
    const pages = [
      ...ROUTES.map((r) => '#' + r.chemin),
      '#/calcul/resultat',
      '#/explorer/etat?m=lfi2025',
      '#/explorer/etat/detail?m=execution2024&id=Education%20et%20recherche%2FEnseignement%20scolaire%2F141',
      '#/explorer/ue?dep=69',
      '#/explorer/recettes?i=D211',
      '#/local/commune?insee=69123',
      '#/local/departement?dep=69',
      '#/beneficiaires?p=141',
      '#/beneficiaires?onglet=marches',
      '#/beneficiaires?onglet=france2030',
      '#/beneficiaires/programme?p=141',
      '#/decisions/realisations?p=141',
      '#/decisions/votes?p=141',
      '#/decisions/controle?dep=69',
      '#/decisions/vie-politique?a=2022',
      '#/decisions/vie-politique?a=2024',
    ]
    for (const f of pages) {
      await ecran(f)
      // Textes repliés compris (details, lignes masquées) : textContent lit tout le DOM.
      verifierLexique(document.body.textContent ?? '', f)
      verifierLexique(document.title, `${f} (titre du document)`)
      for (const el of Array.from(main.querySelectorAll('[aria-label], [title], [alt]')))
        verifierLexique(['aria-label', 'title', 'alt'].map((a) => el.getAttribute(a) ?? '').join(' '), `${f} (attribut)`)
    }
    await ecran('#/decisions/vie-politique?a=2022')
    main.querySelector<HTMLButtonElement>('[data-fichier*="presidentielle_2022"]')!.click()
    await attendreQue(() => (main.querySelector('#candidats')?.textContent ?? '').includes('ARTHAUD'))
    verifierLexique(main.textContent ?? '', 'candidats')
    // Titres et descriptions des pages prérendues (balises title et meta description de chaque route).
    for (const r of ROUTES) verifierLexique(`${r.titre} ${r.titrePage ?? ''} ${r.description}`, `${r.chemin} (titre et description)`)
    const html = readFileSync(join(process.cwd(), 'index.html'), 'utf8')
    for (const m of html.matchAll(/content="([^"]*)"/g)) verifierLexique(m[1], 'index.html (méta)')
    verifierLexique(html.replace(/<[^>]+>/g, ' '), 'index.html')
    verifierLexique(readFileSync(join(process.cwd(), 'scripts', 'og.html'), 'utf8').replace(/<style>[\s\S]*?<\/style>/, '').replace(/<[^>]+>/g, ' '), 'og.html (image de partage)')
    verifierLexique(readFileSync(join(process.cwd(), 'src', 'composants', 'carte-partage.ts'), 'utf8').match(/'[^']*'/g)!.join(' '), 'carte de partage')
  }, 180000)

  it('partis et candidats : ordre neutre, règle explicite affichée sous chaque liste', async () => {
    const { trierPartis, trierCandidats, REGLE_PARTIS, REGLE_CANDIDATS } = await import('../src/ecrans/viepolitique')
    // Règles pures : montant décroissant puis alphabétique ; circonscription puis nom.
    expect(trierPartis([{ nom: 'B', total_eur: 1 }, { nom: 'C', total_eur: 2 }, { nom: 'A', total_eur: 1 }]).map((x) => x.nom)).toEqual(['C', 'A', 'B'])
    expect(
      trierCandidats([
        { candidat: 'ZOLA Émile', circonscription: 'Ain (1re)' },
        { candidat: 'ARAGON Louis', circonscription: 'Ain (2e)' },
        { candidat: 'ÉLUARD Paul', circonscription: 'Ain (1re)' },
      ]).map((x) => x.candidat),
    ).toEqual(['ÉLUARD Paul', 'ZOLA Émile', 'ARAGON Louis'])
    await ecran('#/decisions/vie-politique?a=2022')
    const regles = Array.from(main.querySelectorAll('[data-regle-ordre]')).map((x) => x.textContent)
    expect(regles).toContain(REGLE_PARTIS)
    const lignes = Array.from(main.querySelectorAll('table')).find((t) => t.caption?.textContent?.startsWith('Aide publique par parti'))!.querySelectorAll('tbody tr')
    const partis = JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/data/vie_politique/partis/2022.json'), 'utf8')).partis as { nom: string; total_eur: number }[]
    expect(lignes.length).toBe(partis.length)
    expect(Array.from(lignes).map((tr) => tr.querySelector('td')!.textContent)).toEqual(trierPartis(partis).map((x) => x.nom))
    // Même format pour chaque parti : quatre colonnes, aucune ligne mise en avant.
    for (const tr of Array.from(lignes)) {
      expect(tr.querySelectorAll('td').length).toBe(4)
      expect(tr.querySelector('.surligne, strong, mark')).toBeNull()
    }
    main.querySelector<HTMLButtonElement>('[data-fichier*="presidentielle_2022"]')!.click()
    await attendreQue(() => (main.querySelector('#candidats')?.textContent ?? '').includes('ARTHAUD'))
    expect(main.querySelector('#candidats [data-regle-ordre]')?.textContent).toBe(REGLE_CANDIDATS)
    const cands = JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/data/vie_politique/candidats/presidentielle_2022.json'), 'utf8')).candidats as { candidat: string; circonscription?: string }[]
    const affiches = Array.from(main.querySelectorAll('#table-cand tbody tr')).map((tr) => tr.querySelector('td')!.textContent)
    expect(affiches).toEqual(trierCandidats(cands).slice(0, 50).map((x) => x.candidat))
    for (const tr of Array.from(main.querySelectorAll('#table-cand tbody tr'))) expect(tr.querySelector('.surligne, strong, mark')).toBeNull()
    // Équilibre de la sélection : les pages sur les entreprises et les organismes renvoient aux prestations aux ménages.
    for (const f of ['#/beneficiaires', '#/decisions/controle']) {
      await ecran(f)
      expect(main.querySelector('a[href="#/explorer/secu"]'), f).not.toBeNull()
    }
    // Amendements : ordre chronologique explicite.
    const { REGLE_AMENDEMENTS } = await import('../src/ecrans/votes')
    await ecran('#/decisions/votes?p=141')
    expect(main.querySelector('[data-regle-ordre]')?.textContent).toBe(REGLE_AMENDEMENTS)
    const dates = Array.from(main.querySelectorAll('[data-regle-ordre] + ul.lignes .dest')).map((d) => (d.textContent ?? '').slice(0, 10))
    expect(dates.length).toBeGreaterThan(1)
    expect([...dates].sort().reverse()).toEqual(dates)
  }, 60000)

  it('méthode : l’écart de consolidation affiché est la différence des deux montants affichés', async () => {
    const meta = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'data', 'meta.json'), 'utf8'))
    const adm = meta.controle.arbre_administrations
    await ecran('#/methode')
    const md = (x: number) => new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(x).replace(/\s+/g, ' ')
    const phrase = texte().match(/la somme des administrations \(([^)]*)\) dépasse le total consolidé \(([^)]*)\) de (.*?), à cause/)
    expect(phrase).not.toBeNull()
    // Les trois nombres viennent des données, et le troisième est bien la différence des deux premiers.
    expect(phrase![1]).toContain(md(adm.somme_md))
    expect(phrase![2]).toContain(md(adm.total_consolide_s13_md))
    expect(phrase![3]).toContain(md(adm.somme_md - adm.total_consolide_s13_md))
    expect(Math.abs(adm.somme_md - adm.total_consolide_s13_md - adm.ecart_consolidation_md)).toBeLessThan(0.051)
    expect(texte()).toContain(`tous transferts compris, l’écart est de ${md(adm.ecart_depenses_totales_md)}`)
  })

  it('votes : un montant illisible dans la source n’est jamais affiché comme 0 €', async () => {
    const { montantEtape } = await import('../src/ecrans/votes')
    expect(montantEtape({ cp: null, raison: 'valeur illisible dans la source : « #REF! »' })).toBe('non lisible (valeur illisible dans la source : « #REF! »)')
    expect(montantEtape({ cp: null })).toBe('non lisible dans la source')
    expect(montantEtape({ cp: 0 })).toMatch(/^0/)
    expect(montantEtape({ cp: -1500 })).toMatch(/^−/)
  })

  it('toutes les lectures de données sont relatives au site', () => {
    expect(requetes.length).toBeGreaterThan(10)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })
})

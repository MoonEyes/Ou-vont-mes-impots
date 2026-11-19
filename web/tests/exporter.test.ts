// @vitest-environment happy-dom
// Export CSV et citation des tableaux : contenu du fichier, texte de citation, boutons posés par le routeur.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { brancherExports, enrichirTableaux, lireNombre, nomFichier, tableauVersCsv, texteCitation, titreTableau } from '../src/composants/exporter'
import { afficher, type Route } from '../src/routeur'
import { attendre, attendreQue } from './aide-dom'

const FIXTURE = readFileSync(join(process.cwd(), 'tests', 'fixtures', 'exporter', 'ecran.html'), 'utf8')
let main: HTMLElement

beforeEach(() => {
  document.body.innerHTML = `<main id="contenu"></main><div id="annonce" aria-live="polite"></div>`
  main = document.getElementById('contenu') as HTMLElement
  main.innerHTML = FIXTURE
  window.scrollTo = (() => {}) as never
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const tables = () => Array.from(main.querySelectorAll('table'))

describe('lecture des nombres', () => {
  it('nombres français avec unité, signes et espaces fines', () => {
    expect(lireNombre('3 101,2 Md€')).toEqual({ valeur: '3101,2', unite: 'Md€' })
    expect(lireNombre('−0,4 %')).toEqual({ valeur: '-0,4', unite: '%' })
    expect(lireNombre('+5,1 %')).toEqual({ valeur: '5,1', unite: '%' })
    expect(lireNombre('2024')).toEqual({ valeur: '2024', unite: '' })
    expect(lireNombre('18/11/2026')).toBeNull()
    expect(lireNombre('Programme 101 Justice')).toBeNull()
  })
})

describe('CSV', () => {
  it('séparateur point-virgule, virgule décimale, unité dans l’en-tête, valeurs absentes gardées', () => {
    expect(tableauVersCsv(tables()[0])).toBe(
      [
        'Année;Encours (Md€);Variation (%);Statut;Note',
        '2023;3101,2;5,1;Tracé;"Compte « définitif »; révisé"',
        "2024;3305,3;-0,4;Approché;'=SOMME(A1)",
        '2025;nc;nc;Non publié;',
        'Écart des sources;;nc;;12 €',
        '',
      ].join('\r\n'),
    )
  })
  it('colonne aux unités mêlées : texte affiché gardé ; première ligne d’en-têtes sans thead', () => {
    expect(tableauVersCsv(tables()[1])).toBe('Poste;Montant\r\nIntérêts;55 Md€\r\nAutre;1,5 M€\r\n')
  })
  it('nom de fichier parlant, sans accent', () => {
    expect(nomFichier('Dette fin d’année, milliards d’euros', '2024')).toBe('ou-vont-mes-impots_dette-fin-d-annee-milliards-d-euros-2024.csv')
    expect(nomFichier('Aide publique par parti, 2024', '2024')).toBe('ou-vont-mes-impots_aide-publique-par-parti-2024.csv')
    expect(nomFichier('', null)).toBe('ou-vont-mes-impots_tableau.csv')
  })
})

describe('citation', () => {
  const date = new Date(2026, 10, 18)
  it('titre, page, site, source et millésime, adresse, date de consultation', () => {
    expect(texteCitation(tables()[0], date, 'https://exemple.test/dette/')).toBe(
      '« Dette fin d’année, milliards d’euros », page « La dette », Le billet découpé (site citoyen non officiel). Données : Insee, comptes nationaux (2024). https://exemple.test/dette/. Consulté le 18 novembre 2026.',
    )
  })
  it('sans légende ni source : titre de section, renvoi vers la méthode', () => {
    expect(titreTableau(tables()[1])).toBe('Sans légende')
    expect(texteCitation(tables()[1], date, 'https://exemple.test/dette/')).toContain('Données : sources indiquées sur la page Méthode et sources du site.')
  })
})

describe('boutons', () => {
  it('deux actions par tableau de données, une seule fois, rien pour un tableau de mise en page', () => {
    enrichirTableaux(main)
    enrichirTableaux(main)
    const blocs = main.querySelectorAll('.exporter')
    expect(blocs).toHaveLength(2)
    // Posées après l'enveloppe défilante, hors du tableau.
    expect(main.querySelector('.tableau-defile')!.nextElementSibling?.classList.contains('exporter')).toBe(true)
    const b = blocs[0].querySelectorAll('button')
    expect(b[0].textContent).toBe('Télécharger (CSV) : Dette fin d’année, milliards d’euros')
    expect(b[0].querySelector('.visuellement-cache')).not.toBeNull()
    expect(b[1].getAttribute('aria-expanded')).toBe('false')
    expect(main.querySelector('table[role="presentation"]')!.nextElementSibling).toBeNull()
  })

  it('télécharger : fichier UTF-8 avec BOM, nom parlant, annonce', async () => {
    enrichirTableaux(main)
    let blob: Blob | null = null
    vi.spyOn(URL, 'createObjectURL').mockImplementation((b) => {
      blob = b as Blob
      return 'blob:essai'
    })
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    let nom = ''
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      nom = this.download
    })
    main.querySelector<HTMLButtonElement>('[data-action="csv"]')!.click()
    expect(nom).toBe('ou-vont-mes-impots_dette-fin-d-annee-milliards-d-euros-2024.csv')
    expect(blob!.type).toContain('text/csv')
    const octets = new Uint8Array(await blob!.arrayBuffer())
    expect(Array.from(octets.slice(0, 3))).toEqual([0xef, 0xbb, 0xbf])
    expect(new TextDecoder().decode(octets.slice(3))).toContain('Année;Encours (Md€)')
    await attendreQue(() => document.getElementById('annonce')!.textContent!.includes('téléchargé'))
  })

  it('citer : texte affiché, copié dans le presse-papiers, annoncé ; second clic referme', async () => {
    enrichirTableaux(main)
    const ecrit = vi.fn(async () => {})
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: ecrit } })
    const citer = main.querySelector<HTMLButtonElement>('[data-action="citer"]')!
    const panneau = document.getElementById(citer.getAttribute('aria-controls')!)!
    expect(panneau.hidden).toBe(true)
    citer.click()
    await attendreQue(() => ecrit.mock.calls.length > 0)
    expect(citer.getAttribute('aria-expanded')).toBe('true')
    expect(panneau.hidden).toBe(false)
    const texte = panneau.querySelector('.exporter-texte')!.textContent!
    expect(texte).toMatch(/^« Dette fin d’année, milliards d’euros », page « La dette », Le billet découpé/)
    expect(texte).toMatch(/Consulté le \d{1,2} \S+ \d{4}\.$/)
    expect(ecrit).toHaveBeenCalledWith(texte)
    await attendreQue(() => panneau.querySelector('[role="status"]')!.textContent === 'Citation copiée dans le presse-papiers.')
    await attendreQue(() => document.getElementById('annonce')!.textContent === 'Citation copiée dans le presse-papiers.')
    citer.click()
    expect(panneau.hidden).toBe(true)
    expect(citer.getAttribute('aria-expanded')).toBe('false')
  })

  it('presse-papiers refusé : message pour copier à la main', async () => {
    enrichirTableaux(main)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: async () => Promise.reject(new Error('refus')) } })
    const citer = main.querySelector<HTMLButtonElement>('[data-action="citer"]')!
    citer.click()
    const etat = () => main.querySelector('.exporter [role="status"]')!.textContent ?? ''
    await attendreQue(() => etat() !== '')
    expect(etat()).toMatch(/Copie automatique impossible|Citation copiée/)
  })
})

describe('crochet du routeur', () => {
  it('tableaux de l’écran et tableaux ajoutés ensuite (suite, pagination) reçoivent leurs actions', async () => {
    let finir: () => void = () => {}
    const routes: Route[] = [
      { chemin: '/', titre: 'Accueil', description: 'Accueil', charger: async () => ({ rendre: () => {} }) },
      {
        chemin: '/essai',
        titre: 'Essai',
        description: 'Essai',
        sansVoisins: true,
        charger: async () => ({
          rendre: (cible: HTMLElement) => {
            cible.innerHTML = `<h1>Essai</h1><div class="tableau-defile"><table><caption>Premier, 2024</caption><thead><tr><th scope="col">A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table></div><div id="plus"></div>`
            const suite = new Promise<void>((r) => (finir = r)).then(() => {
              cible.querySelector('#plus')!.innerHTML = `<table><caption>Second</caption><tbody><tr><td>2</td></tr></tbody></table>`
            })
            return { suite }
          },
        }),
      },
    ]
    main.innerHTML = ''
    location.hash = '#/essai'
    const fini = afficher(routes, main, '#/essai', false)
    await attendreQue(() => !!main.querySelector('h1'))
    expect(main.querySelectorAll('.exporter')).toHaveLength(1)
    finir()
    await fini
    await attendre(0)
    expect(main.querySelectorAll('.exporter')).toHaveLength(2)
    // La pagination remplace le tableau : les actions suivent, sans doublon.
    main.querySelector('#plus')!.innerHTML = `<table><caption>Page 2</caption><tbody><tr><td>3</td></tr></tbody></table>`
    await attendre(0)
    expect(main.querySelectorAll('.exporter')).toHaveLength(2)
    brancherExports(main)
    expect(main.querySelectorAll('.exporter')).toHaveLength(2)
  })
})

// @vitest-environment happy-dom
// Écran /beneficiaires/subventions sur des fixtures (extraits réels de site/data/subventions et site/data/associations).
import { beforeAll, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { eurLisible } from '../src/util'
import { correspond, normaliser, typeBeneficiaire } from '../src/ecrans/subventions'
import { attendreQue, monterPage } from './aide-dom'

const FIX = join(process.cwd(), 'tests', 'fixtures', 'data')
const lire = (f: string) => JSON.parse(readFileSync(join(FIX, f), 'utf8'))
const ix = lire('subventions/index.json')
const ai = lire('associations/index.json')
const ben = lire('subventions/beneficiaires.json')

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = (el: Element = main) => el.textContent?.replace(/\s+/g, ' ') ?? ''

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('règles pures', () => {
  it('type de bénéficiaire lu dans la catégorie juridique', () => {
    expect(typeBeneficiaire('9220')).toBe('associations')
    expect(typeBeneficiaire('9300')).toBe('associations')
    expect(typeBeneficiaire('5599')).toBe('entreprises')
    expect(typeBeneficiaire('6540')).toBe('entreprises')
    expect(typeBeneficiaire('7210')).toBe('collectivites')
    expect(typeBeneficiaire('7346')).toBe('collectivites')
    expect(typeBeneficiaire('7354')).toBe('collectivites')
    expect(typeBeneficiaire('7389')).toBe('publics')
    expect(typeBeneficiaire('7364')).toBe('publics')
    expect(typeBeneficiaire('4110')).toBe('publics')
    expect(typeBeneficiaire('7120')).toBe('publics')
    expect(typeBeneficiaire('8110')).toBe('autres')
  })

  it('recherche : mots dans la dénomination sans accents, ou numéro SIREN exact', () => {
    expect(normaliser('Théâtre  d’Aix')).toBe('THEATRE D AIX')
    expect(correspond('carpa normandie', '1', 'CARPA NORMANDIE')).toBe(true)
    expect(correspond('normandie carpa', '1', 'CARPA NORMANDIE')).toBe(true)
    expect(correspond('carp', '1', 'CARPA NORMANDIE')).toBe(true)
    expect(correspond('carpa bretagne', '1', 'CARPA NORMANDIE')).toBe(false)
    expect(correspond('320 252 489', '320252489', 'X')).toBe(true)
    expect(correspond('320252480', '320252489', 'X')).toBe(false)
  })
})

describe('écran des subventions', () => {
  it('titre, fil d’Ariane, chiffre clé avec sur 100 €, source et statut', async () => {
    await ecran('#/beneficiaires/subventions')
    expect(main.querySelector('h1')?.textContent?.trim()).toBe('Les subventions de l’État et de ses opérateurs')
    expect(main.querySelector('.erreur')).toBeNull()
    const fil = main.querySelector('nav[aria-label="Fil d\'Ariane"]')!
    expect(fil.querySelector('a[href="#/beneficiaires"]')).not.toBeNull()
    const cle = main.querySelector('[data-cle]')!
    expect(cle.querySelector('.surligne')?.textContent).toBe(eurLisible(ix.totaux.total_additionne_eur))
    expect(texte(cle)).toMatch(/Sur 100 € publiés/)
    expect(texte(cle)).toContain('Statut')
    expect(texte(cle)).toContain('pas des paiements')
    expect(cle.querySelector('.source')?.textContent).toContain('SIRENE')
    // Relié à la page parente et aux opérateurs.
    expect(main.querySelector('a[href="#/beneficiaires"]')).not.toBeNull()
    expect(main.querySelector('a[href="#/explorer/operateurs"]')).not.toBeNull()
  })

  it('par année : tableau organisme × année, années non couvertes en « – » (jamais 0), liste des associations avec l’année non communiquée', async () => {
    await ecran('#/beneficiaires/subventions')
    const tables = Array.from(main.querySelectorAll('table'))
    for (const t of tables) {
      expect(t.querySelector('caption')?.textContent?.trim()).toBeTruthy()
      expect(t.querySelectorAll('thead th[scope="col"]').length).toBeGreaterThan(0)
    }
    const conv = tables.find((t) => t.caption?.textContent?.startsWith('Subventions par organisme qui attribue et par année'))!
    expect(conv).toBeTruthy()
    expect(conv.querySelectorAll('tbody tr').length).toBe(lire('subventions/annees.json').sources_additionnees.length + 1)
    expect(texte(conv)).toContain('–')
    expect(texte(conv)).toContain('Total des sources additionnées')
    const jaune = tables.find((t) => t.caption?.textContent?.startsWith('Liste des subventions de l’État aux associations'))!
    expect(jaune.querySelectorAll('tbody tr').length).toBe(ai.annees.length)
    const nc = Array.from(jaune.querySelectorAll('tbody tr')).find((tr) => tr.querySelector('th')?.textContent === '2022')!
    expect(texte(nc)).toContain('non communiqué')
    expect(texte(nc)).toContain('Non publié')
  })

  it('par ministère ou organisme : une fiche par source, détail chargé à l’ouverture (années, types, premiers bénéficiaires, agrégés)', async () => {
    await ecran('#/beneficiaires/subventions')
    const fiches = main.querySelectorAll<HTMLDetailsElement>('details[data-source]')
    expect(fiches.length).toBe(ix.sources.length)
    const festivals = main.querySelector('details[data-source="subv_culture_festivals_p131"]')!
    expect(texte(festivals)).toContain('jamais additionné')
    const ademe = main.querySelector<HTMLDetailsElement>('details[data-source="subv_ademe_aides"]')!
    ademe.open = true
    ademe.dispatchEvent(new Event('toggle'))
    await attendreQue(() => !!ademe.querySelector('.detail-source table'))
    const t = texte(ademe)
    expect(t).toContain('montants par année')
    expect(t).toContain('Entreprises et sociétés')
    expect(t).toContain('HEIDELBERG MATERIALS FRANCE CIMENTS')
    expect(t).toContain('agrégés et jamais nommés')
    // Source dont le fichier détaillé manque : message propre.
    const fir = main.querySelector<HTMLDetailsElement>('details[data-source="subv_ars_pdl_fir"]')!
    fir.open = true
    fir.dispatchEvent(new Event('toggle'))
    await attendreQue(() => texte(fir).includes('pas disponible'))
  })

  it('associations par mission : année choisie, programmes reliés à « Qui reçoit l’argent »', async () => {
    await ecran('#/beneficiaires/subventions')
    const z = main.querySelector<HTMLElement>('#sub-missions')!
    expect(texte(z)).toContain('Versé en 2023')
    expect(z.querySelector('a[href="#/beneficiaires?onglet=programme&p=163"]')).not.toBeNull()
    const choix = z.querySelector<HTMLSelectElement>('#sub-annee')!
    expect(Array.from(choix.options).map((o) => o.value)).not.toContain('2024')
    choix.value = '2012'
    choix.dispatchEvent(new Event('change'))
    await attendreQue(() => texte(main.querySelector('#sub-missions')!).includes('Versé en 2010'))
  })

  it('par type : seuls les premiers bénéficiaires ont un type ; autres organismes et agrégés affichés comme tels, total conservé', async () => {
    await ecran('#/beneficiaires/subventions')
    const t = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.startsWith('Conventions de subvention par type'))!
    const lignes = Array.from(t.querySelectorAll('tbody tr')).map((tr) => texte(tr))
    expect(lignes.some((l) => l.startsWith('Établissements publics et services de l’État'))).toBe(true)
    expect(lignes.some((l) => l.includes('type non réparti'))).toBe(true)
    expect(lignes.some((l) => l.includes('Agrégé, jamais nommé'))).toBe(true)
    const somme = ben.top.reduce((a: number, x: { montant_eur: number }) => a + x.montant_eur, 0) + ben.autres_personnes_morales.montant_eur + ben.exclus_personnes_physiques_ou_non_identifies.montant_eur
    expect(Math.abs(somme - ben.total_eur)).toBeLessThan(1)
  })

  it('recherche : refuse moins de 3 lettres ; trouve un organisme par SIREN dans les conventions', async () => {
    await ecran('#/beneficiaires/subventions')
    const form = main.querySelector<HTMLFormElement>('#sub-recherche')!
    const q = form.querySelector<HTMLInputElement>('#sub-q')!
    expect(form.querySelector('label[for="sub-q"]')).not.toBeNull()
    expect(texte(form)).toContain('restent agrégées')
    q.value = 'ab'
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    expect(q.getAttribute('aria-invalid')).toBe('true')
    q.value = '320252489'
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => texte(main.querySelector('#sub-resultats')!).includes('Recherche terminée'))
    const r = texte(main.querySelector('#sub-resultats')!)
    expect(r).toContain('BPIFRANCE')
    expect(r).toContain('Ministère de la Culture')
    expect(r).toContain('Entreprises et sociétés')
  })

  it('recherche dans la liste des associations, fichier par fichier : montant avec année, programme et statut', async () => {
    await ecran('#/beneficiaires/subventions')
    const form = main.querySelector<HTMLFormElement>('#sub-recherche')!
    form.querySelector<HTMLInputElement>('#sub-q')!.value = 'carpa'
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => texte(main.querySelector('#sub-resultats')!).includes('Recherche terminée'))
    const z = main.querySelector('#sub-resultats')!
    const nbFichiers = ai.programmes.flatMap((p: { fichiers: string[] }) => p.fichiers).length
    expect(texte(z)).toContain(`${nbFichiers} fichiers parcourus sur ${nbFichiers}`)
    const t = Array.from(z.querySelectorAll('table')).find((x) => x.caption?.textContent?.includes('liste des subventions aux associations'))!
    const lignes = Array.from(t.querySelectorAll('tbody tr')).map((tr) => texte(tr))
    expect(lignes.length).toBeGreaterThan(3)
    expect(lignes.some((l) => l.includes('CARPA NORMANDIE'))).toBe(true)
    for (const l of lignes) {
      expect(l).toMatch(/versé en 20\d\d \(projet de loi de finances 20\d\d\)/)
      expect(l).toContain('Programme 101')
      expect(l).toContain('Tracé')
    }
    expect(texte(z)).toContain('Classés par montant décroissant')
  })

  it('confidentialité : aucune ligne nommée sans catégorie juridique de personne morale', () => {
    for (const p of ai.programmes)
      for (const f of p.fichiers) for (const l of lire(f).lignes) expect(Number(String(l[2])[0]), l[1]).toBeGreaterThanOrEqual(2)
    for (const t of ben.top) expect(Number(t.categorie_juridique[0])).toBeGreaterThanOrEqual(2)
  })
})

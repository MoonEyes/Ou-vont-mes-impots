// @vitest-environment happy-dom
// Écran « La France et les autres pays de l'Union » sur des extraits réels de site/data/comparaison/
// (index, fiches, prélèvements, dépenses TOTAL et GF07 ; GF02 et les autres fonctions absentes exprès).
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { statutTexte, valeurTexte } from '../src/ecrans/comparaison_europe'
import { monterPage } from './aide-dom'

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''
const espaces = (s: string | null | undefined) => (s ?? '').replace(/\s+/g, ' ').trim()
/** Lignes du tableau des 27 pays : [nom, valeur, statut]. */
const lignesPays = () =>
  Array.from(main.querySelectorAll('table.tableau-comparaison'))
    .find((t) => /27 pays de l’Union/.test(t.querySelector('caption')?.textContent ?? ''))!
    .querySelectorAll('tbody tr')

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('comparaison européenne', () => {
  it('route enfant d’Explorer, voisine de la page Union européenne', () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/comparaison-europe')!
    expect(r.parent).toBe('/explorer')
    expect(r.voisins).toContain('/explorer/ue')
  })

  it('chiffre clé : dépense publique de la France par habitant et sur 100 € de richesse, avec année, statut et source', async () => {
    await ecran('#/explorer/comparaison-europe')
    expect(main.querySelector('h1')?.textContent).toBe('La France et les autres pays de l’Union')
    const cle = main.querySelector('[data-cle]')!
    expect(espaces(cle.querySelector('.surligne')?.textContent)).toBe('24 308 € par habitant')
    expect(espaces(cle.textContent)).toContain('en 2024')
    expect(espaces(cle.textContent)).toContain('57,3 € sur 100 € de richesse produite')
    expect(espaces(cle.textContent)).toContain('Statut : provisoire')
    expect(espaces(cle.textContent)).toContain('Impôts et cotisations sociales obligatoires en 2025 : 44,2 %')
    expect(cle.querySelector('.source')?.textContent).toContain('Eurostat')
    expect(main.querySelectorAll('.surligne').length).toBe(1)
  })

  it('renvoie à la page « La France et l’Union européenne » sans en reprendre le contenu', async () => {
    await ecran('#/explorer/comparaison-europe')
    expect(main.querySelector('a[href="#/explorer/ue"]')).not.toBeNull()
    expect(texte()).toContain('est un autre sujet')
    expect(texte()).not.toContain('prélèvement sur recettes')
  })

  it('neutralité : aucun rang ni palmarès, aucune couleur de valeur, France seulement repérée', async () => {
    await ecran('#/explorer/comparaison-europe')
    expect(texte()).not.toMatch(/(?<!\p{L})(rang|palmarès|podium)(?!\p{L})|\d+(e|ème|er) sur 27/iu)
    // Seules les largeurs posées par le CSSOM (data-l) portent un style ; aucune couleur en ligne.
    for (const el of Array.from(main.querySelectorAll('[style]'))) expect(el.getAttribute('style')).toMatch(/^width: [\d.]+%;?$/)
    expect(main.textContent).not.toContain('—')
    const fr = main.querySelectorAll('tr.repere-france')
    expect(fr.length).toBe(1)
    expect(fr[0].textContent).toContain('France')
    expect(fr[0].textContent).toContain('repère')
    // Toutes les barres ont la même classe : aucune n'est mise en avant.
    const classes = new Set(Array.from(main.querySelectorAll('.tableau-comparaison .barre-remplissage')).map((b) => b.className))
    expect([...classes]).toEqual(['barre-remplissage'])
    for (const tr of Array.from(main.querySelectorAll('.tableau-comparaison tbody tr'))) expect(tr.querySelector('mark, .surligne')).toBeNull()
  })

  it('tous les pays par ordre alphabétique par défaut, règle d’ordre affichée, ensembles européens à part', async () => {
    await ecran('#/explorer/comparaison-europe')
    const lignes = lignesPays()
    expect(lignes.length).toBe(27)
    expect(lignes[0].querySelector('th')?.textContent).toBe('Allemagne')
    expect(lignes[26].querySelector('th')?.textContent).toBe('Tchéquie')
    expect(texte()).toContain('Ordre : alphabétique')
    expect(texte()).toContain('Union européenne - 27 pays')
    expect(texte()).toContain('Zone euro - 20 pays')
  })

  it('santé en euros par habitant, par valeur : ordre décroissant écrit, groupes et années', async () => {
    await ecran('#/explorer/comparaison-europe?p=GF07&u=eur_hab&o=valeur&a=2024')
    const lignes = lignesPays()
    const noms = Array.from(lignes).map((l) => l.querySelector('th')?.textContent?.replace(' repère', ''))
    expect(noms.slice(0, 3)).toEqual(['Luxembourg', 'Danemark', 'Irlande'])
    const fr = Array.from(lignes).find((l) => l.classList.contains('repere-france'))!
    expect(espaces(fr.querySelector('td.nombre')?.textContent)).toBe('3 797 €')
    expect(fr.textContent).toContain('provisoire')
    expect(texte()).toContain('Ordre : valeur décroissante')
    expect(texte()).toContain('Une position décrit un niveau, pas un jugement')
    expect(texte()).toContain('Services hospitaliers')
    expect(texte()).toContain('toutes les années')
    expect(texte()).toContain('Hôpitaux, soins de ville')
  })

  it('prélèvements obligatoires : total en 2025, unités disponibles seulement', async () => {
    await ecran('#/explorer/comparaison-europe?p=PO&a=2025')
    expect(main.querySelector('h3')?.textContent).toContain('Impôts et cotisations sociales obligatoires (total)')
    expect(main.querySelector('h3')?.textContent).toContain('2025')
    const fr = Array.from(lignesPays()).find((l) => l.classList.contains('repere-france'))!
    expect(espaces(fr.querySelector('td.nombre')?.textContent)).toBe('44,2 %')
    // La part du total n'a pas de sens pour un total : l'option n'est pas proposée.
    const unites = Array.from(main.querySelectorAll<HTMLOptionElement>('#cmp-unite option')).map((o) => o.value)
    expect(unites).toEqual(['pct_pib', 'eur_hab'])
    expect(texte()).toContain('Insee')
  })

  it('fichier d’une fonction absent : message, le reste de la page s’affiche', async () => {
    await ecran('#/explorer/comparaison-europe?p=GF02')
    expect(main.querySelector('.absent')?.textContent).toContain('Défense')
    expect(texte()).toContain('Limites de la comparaison')
    expect(texte()).toContain('Repères par grand poste')
  })

  it('choix invalides dans l’adresse : retour aux valeurs par défaut', async () => {
    await ecran('#/explorer/comparaison-europe?p=XYZ&u=bidon&a=1890&o=autre')
    expect(main.querySelector('h3')?.textContent).toBe('Dépense publique totale, % du PIB, 2024')
    expect(texte()).toContain('Ordre : alphabétique')
  })

  it('changer un choix met à jour l’adresse', async () => {
    await ecran('#/explorer/comparaison-europe')
    const s = main.querySelector<HTMLSelectElement>('#cmp-poste')!
    s.value = 'GF07'
    s.dispatchEvent(new Event('change', { bubbles: true }))
    expect(location.hash).toBe('#/explorer/comparaison-europe?p=GF07&u=pct_pib&a=2024&o=alpha')
  })

  it('limites expliquées : périmètres, retraites, santé, pouvoir d’achat, citations Eurostat', async () => {
    await ecran('#/explorer/comparaison-europe')
    expect(texte()).toContain('standard de pouvoir d’achat')
    expect(texte()).toContain('Des systèmes de retraite différents')
    expect(texte()).toMatch(/Santé : seule la dépense des administrations publiques/)
    expect(texte()).toContain('classification internationale des dépenses publiques par fonction')
    const citation = main.querySelector('blockquote[lang="en"]')
    expect(citation?.textContent).toContain('COFOG data')
  })

  it('tableaux accessibles : légende et en-têtes de portée', async () => {
    await ecran('#/explorer/comparaison-europe?p=GF07')
    for (const t of Array.from(main.querySelectorAll('table'))) {
      expect(t.querySelector('caption')?.textContent?.trim()).toBeTruthy()
      expect(t.querySelectorAll('th[scope]').length).toBeGreaterThan(0)
    }
    for (const s of Array.from(main.querySelectorAll('select'))) expect(main.querySelector(`label[for="${s.id}"]`)).not.toBeNull()
  })

  it('valeur manquante : « non publiée », jamais 0', () => {
    expect(valeurTexte(null, 'pct_pib')).toBe('non publiée')
    expect(valeurTexte(undefined, 'eur_hab')).toBe('non publiée')
    expect(statutTexte({}, 'FR', 'GF07', 2024, null)).toBe('non publiée')
    expect(statutTexte({ FI: { GF07: { b: [2015] } } }, 'FI', 'GF07', 2015, 7.1)).toBe('rupture de série')
    expect(statutTexte({ FR: { GF07: { p: [2024] } } }, 'FR', 'GF07', 2023, 8.8)).toBe('publiée')
  })
})

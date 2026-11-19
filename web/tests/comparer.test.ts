// @vitest-environment happy-dom
// Écran « Comparer deux communes » (/local/comparer) sur les fixtures du Rhône (Lyon et Affoux).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { viderCache } from '../src/donnees'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { attendreQue, monterPage } from './aide-dom'

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''
const eurFr = (x: number) => `${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(Math.round(x))} €`.replace(/\s+/g, ' ')
const lire = (f: string) => JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/data', f), 'utf8'))

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('comparer deux communes', () => {
  it('sans paramètre : formulaire département puis commune, de chaque côté, et rappel sur les compétences', async () => {
    await ecran('#/local/comparer')
    expect(main.querySelector('h1')?.textContent).toBe('Comparer deux communes')
    expect(document.title).toBe('Comparer le budget de deux communes · Le billet découpé')
    expect(main.querySelectorAll('#choix-comparer fieldset')).toHaveLength(2)
    expect(main.querySelector('label[for="dep-a"]')).not.toBeNull()
    expect(main.querySelector('label[for="com-b"]')).not.toBeNull()
    expect(main.querySelector<HTMLElement>('#com-a-bloc')!.hidden).toBe(true)
    expect(texte()).toContain('Les communes n’ont ni la même taille ni les mêmes compétences')
    expect(texte()).not.toContain('Chargement…')
    expect(Array.from(main.querySelectorAll('.fil-ariane a')).map((a) => a.textContent)).toEqual(['Accueil', 'Ma commune', 'Comparer'])
  })

  it('le formulaire écrit les deux communes dans l’adresse (lien partageable)', async () => {
    await ecran('#/local/comparer')
    const choisir = async (cote: string, dep: string, insee: string) => {
      const d = main.querySelector<HTMLSelectElement>(`#dep-${cote}`)!
      d.value = dep
      d.dispatchEvent(new Event('change'))
      await attendreQue(() => !!main.querySelector(`#com-${cote} option[value="${insee}"]`))
      main.querySelector<HTMLSelectElement>(`#com-${cote}`)!.value = insee
    }
    const form = main.querySelector<HTMLFormElement>('#choix-comparer')!
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    expect(main.querySelector<HTMLElement>('#msg-comparer')!.hidden).toBe(false)
    await choisir('a', '69', '69123')
    await choisir('b', '69', '69123')
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    expect(main.querySelector('#msg-comparer')?.textContent).toBe('Choisis deux communes différentes.')
    await choisir('b', '69', '69001')
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    expect(location.hash).toBe('#/local/comparer?a=69123&b=69001')
  })

  it('deux communes : mêmes indicateurs, même année, mêmes échelles, aucun classement', async () => {
    await ecran('#/local/comparer?a=69123&b=69001')
    expect(document.title).toBe('Comparer Lyon et Affoux : budget par habitant, dette, taux')
    // Les listes sont préremplies avec le choix de l'adresse.
    expect(main.querySelector<HTMLSelectElement>('#com-a')!.value).toBe('69123')
    expect(main.querySelector<HTMLSelectElement>('#com-b')!.value).toBe('69001')
    expect(main.querySelector('a[href="#/local/commune?insee=69123&page=lyon"]')?.textContent).toBe('Lyon')
    expect(main.querySelector('a[href="#/local/commune?insee=69001"]')?.textContent).toBe('Affoux')
    // Valeurs par habitant lues dans les fixtures, dernière année commune (2025).
    const b = lire('local/budgets/communes/69.json')
    const k = (n: string) => b.agregats.indexOf(n)
    const a2025 = b.collectivites['69001']
    expect(texte()).toContain(`Dette et épargne, en euros par habitant, 2025`)
    const ligne = (caption: string, nom: string) => {
      const t = Array.from(main.querySelectorAll('table')).find((x) => x.querySelector('caption')?.textContent?.startsWith(caption))!
      const tr = Array.from(t.querySelectorAll('tbody tr')).find((r) => r.querySelector('th')?.textContent === nom)!
      return Array.from(tr.querySelectorAll('td')).map((td) => td.textContent?.replace(/\s+/g, ' '))
    }
    const l = b.collectivites['69123']
    expect(ligne('Dette et épargne', 'Dette en cours')).toEqual([
      eurFr(l.eur['2025'][k('encours_dette')] / l.population['2025']),
      eurFr(a2025.eur['2025'][k('encours_dette')] / a2025.population['2025']),
    ])
    expect(ligne('Dépenses et recettes', 'Dépenses totales')[1]).toBe(eurFr(a2025.eur['2025'][k('depenses_totales')] / a2025.population['2025']))
    expect(ligne('Investissement', 'Équipements (travaux, bâtiments)')).toHaveLength(2)
    // Tableaux accessibles : légende et en-têtes de portée.
    for (const t of Array.from(main.querySelectorAll('table'))) {
      expect(t.querySelector('caption')?.textContent).toBeTruthy()
      expect(t.querySelectorAll('th[scope="col"]').length).toBe(3)
    }
    // Taux votés et versements de l'État présents.
    expect(texte()).toContain('Taxe foncière sur le bâti, tous niveaux')
    expect(texte()).toContain('Dotation globale de fonctionnement notifiée')
    // Mêmes échelles : dans chaque paire, la barre la plus longue fait 100 %, l'autre est proportionnelle.
    const paires = Array.from(main.querySelectorAll('.comparer-paires > li'))
    expect(paires.length).toBeGreaterThan(8)
    for (const p of paires) {
      const w = Array.from(p.querySelectorAll<HTMLElement>('.barre-remplissage')).map((e) => Number(e.dataset.l))
      expect(w).toHaveLength(2)
      if (Math.max(...w) > 0) expect(Math.max(...w)).toBe(100)
    }
    // Aucune mise en avant : ni surligneur, ni barre active, ni vocabulaire de classement.
    expect(main.querySelectorAll('.surligne, .comparer-paires .actif')).toHaveLength(0)
    expect(texte()).not.toMatch(/\b(meilleure?s?|pire|classement des|gagnante?|perdante?|mieux gérée?)\b/i)
    expect(texte()).toContain('sans classement')
    // Revenu médian : axe pas encore publié, état propre.
    expect(texte()).toContain('Revenu médian des habitants : donnée en cours d’intégration.')
    // Lien d'échange de l'ordre, partageable.
    expect(main.querySelector('a[href="#/local/comparer?a=69001&b=69123"]')?.textContent).toBe('Inverser l’ordre des communes')
    expect(main.querySelector('.section-donnees[aria-busy]')).toBeNull()
  })

  it('revenu médian lu dans revenus_communes quand il est publié, secret statistique en « non publié »', async () => {
    viderCache()
    const vrai = globalThis.fetch
    globalThis.fetch = (async (u: string) =>
      String(u).includes('revenus_communes/69.json')
        ? new Response(JSON.stringify({ millesime: '2022', source: 'Insee, Filosofi', communes: { '69123': { revenu_median: 25480 }, '69001': { revenu_median: null, mention: 'secret statistique' } } }), { status: 200 })
        : vrai(u)) as typeof fetch
    try {
      await ecran('#/local/comparer?a=69123&b=69001')
      expect(texte()).toContain('Revenu médian des habitants, en euros par an')
      expect(texte()).toContain(eurFr(25480))
      expect(texte()).toContain('non publié')
      expect(texte()).toContain('secret statistique')
      expect(texte()).toContain('Insee, Filosofi (2022)')
    } finally {
      globalThis.fetch = vrai
      viderCache()
    }
  })

  it('adresse incomplète ou identique : formulaire seul, sans erreur', async () => {
    await ecran('#/local/comparer?a=69123&b=69123')
    expect(texte()).toContain('Les deux communes de l’adresse sont identiques')
    expect(main.querySelector('.comparer-paires')).toBeNull()
    await ecran('#/local/comparer?a=abc&b=69001')
    expect(main.querySelector('h1')?.textContent).toBe('Comparer deux communes')
    expect(main.querySelector('.erreur')).toBeNull()
    await ecran('#/local/comparer?a=69998&b=69001')
    expect(texte()).toContain('Commune introuvable dans les données publiées.')
  })
})

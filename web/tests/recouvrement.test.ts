// @vitest-environment happy-dom
// Écran /explorer/recouvrement sur des extraits réels de site/data/recouvrement/ (fixtures).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { developper, montant, valeurEstimation } from '../src/ecrans/recouvrement'
import { monterPage } from './aide-dom'

let main: HTMLElement
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''
const FIX = (f: string) => JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'data', 'recouvrement', f), 'utf8'))

beforeAll(async () => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
  location.hash = '#/explorer/recouvrement'
  await afficher(ROUTES, main, '#/explorer/recouvrement')
})

describe('outils', () => {
  it('montants lisibles dans l’unité de la source, fourchettes sans somme', () => {
    expect(montant(16673, 'M€')).toBe('16,7 Md€')
    expect(montant(680, 'M€')).toBe('680 M€')
    expect(montant(733994363, '€')).toBe('734 M€')
    expect(montant(1586004944, '€')).toBe('1,6 Md€')
    expect(montant(14, 'Md€')).toBe('14 Md€')
    expect(valeurEstimation({ valeur: null, valeur_basse: 4.8, valeur_haute: 6.3, unite: 'Md€' })).toBe('entre 4,8 et 6,3 Md€')
    expect(valeurEstimation({ valeur: null, valeur_basse: null, valeur_haute: null, unite: 'Md€' })).toBe('non publiée')
  })
  it('sigles développés une fois, jamais deux', () => {
    expect(developper('DGFiP, données')).toBe('Direction générale des finances publiques (DGFiP), données')
    expect(developper('Haut Conseil du financement de la protection sociale (HCFiPS)')).toBe('Haut Conseil du financement de la protection sociale (HCFiPS)')
    expect(developper('CGSS Guadeloupe')).toBe('Caisse générale de sécurité sociale (CGSS) Guadeloupe')
    expect(developper('Urssaf')).toBe('Urssaf')
    expect(developper('Hors douane (DGDDI).')).toBe('Hors douane (Direction générale des douanes et droits indirects).')
    expect(montant(346431, '€')).toBe('346 k€')
    expect(montant(5312844, '€')).toBe('5,3 M€')
  })
})

describe('écran recouvrement', () => {
  it('titre, fil d’Ariane sous Explorer, qui collecte quoi, lien vers les recettes', () => {
    expect(main.querySelector('h1')?.textContent).toContain('Collecte et contrôle des impôts et des cotisations')
    expect(main.querySelector('nav[aria-label="Fil d\'Ariane"] a[href="#/explorer"]')).not.toBeNull()
    expect(texte()).toContain('Direction générale des finances publiques')
    expect(texte()).toContain('Direction générale des douanes et droits indirects')
    expect(main.querySelector('a[href="#/explorer/recettes"]')).not.toBeNull()
  })

  it('frais de gestion de l’impôt : indicateur publié, sur 100 €, lien vers la série du programme 156', () => {
    const cle = main.querySelector('[data-cle]')!
    expect(main.querySelectorAll('.surligne')).toHaveLength(1)
    expect(cle.querySelector('.surligne')?.textContent).toBe('0,53 €')
    expect(cle.textContent).toMatch(/sur 100 €/)
    expect(cle.textContent).toContain('2025')
    expect(cle.querySelector('a[href="#/decisions/realisations?p=156"]')).not.toBeNull()
  })

  it('notifié et encaissé séparés, jamais rapportés ; restitutions à côté des redressements', () => {
    const fiscal = main.querySelector('[data-vue="controle_fiscal"]')!
    expect(fiscal.querySelector('h4[data-notion="notifie"]')!.parentElement!.textContent).toContain('16,7 Md€')
    expect(fiscal.querySelector('h4[data-notion="encaisse"]')!.parentElement!.textContent).toContain('11,4 Md€')
    const urssaf = main.querySelector('[data-vue="controle_urssaf"]')!
    expect(urssaf.querySelector('h4[data-notion="notifie"]')!.parentElement!.textContent).toContain('734 M€')
    expect(urssaf.querySelector('h4[data-notion="restitution"]')!.parentElement!.textContent).toContain('156 M€')
    const enc = urssaf.querySelector('h4[data-notion="encaisse"]')!.parentElement!.textContent!
    expect(enc).toContain('Non publié')
    expect(enc).toContain('ne sont pas publiées')
    // Aucun rapport encaissé / notifié calculé (11 442 / 16 673 = 68,6 %) : seul le taux publié est repris.
    expect(texte()).not.toContain('68,6')
    expect(texte()).toContain('67,99 %')
    expect(texte()).toContain('51,60 %')
    // Le tableau du contrôle fiscal a des colonnes distinctes pour chaque notion.
    const t = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.includes('Contrôle fiscal'))!
    expect(Array.from(t.querySelectorAll('thead th')).map((x) => x.textContent)).toEqual([
      'Année',
      'Notifié : droits et pénalités',
      'Notifié : crédits d’impôt et taxes non remboursés',
      'Encaissé dans l’année',
    ])
    expect(t.querySelector('tbody tr th')?.textContent).toBe('2024')
    const tu = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.startsWith('Contrôles des Urssaf'))!
    expect(tu.querySelector('tbody tr')?.textContent).toContain('156 M€')
  })

  it('estimations côte à côte : producteur, périmètre, méthode, citation ; aucune somme', () => {
    const est = FIX('estimations.json')
    const cartes = Array.from(main.querySelectorAll('[data-estimation]'))
    expect(cartes.map((c) => c.getAttribute('data-estimation'))).toEqual(est.estimations.map((e: { id: string }) => e.id))
    for (const c of cartes) {
      const dt = Array.from(c.querySelectorAll('dt')).map((x) => x.textContent)
      for (const k of ['Producteur', 'Publication', 'Année des données', 'Périmètre', 'Méthode']) expect(dt, c.getAttribute('data-estimation')!).toContain(k)
      expect(c.querySelector('blockquote')).not.toBeNull()
      expect(c.textContent).toContain('Approché')
    }
    const v = (id: string) => main.querySelector(`[data-estimation="${id}"] .recouvrement-valeur strong`)?.textContent
    expect(v('dgfip_tva_sous_declaration')).toBe('entre 6 et 10 Md€')
    expect(v('urssaf_cotisations_eludees')).toBe('entre 4,8 et 6,3 Md€')
    expect(v('commission_europeenne_ecart_tva')).toBe('12,1 Md€')
    expect(main.querySelector('[data-estimation="commission_europeenne_ecart_tva"] blockquote')?.getAttribute('lang')).toBe('en')
    expect(texte()).toContain('Aucune estimation officielle d’ensemble'.replace('’', "'"))
    expect(texte()).not.toMatch(/total des estimations|au total/i)
    expect(texte()).toContain('30 ou de 130 Md€')
  })

  it('impayés, créances retirées des comptes, sources inaccessibles et confidentialité', () => {
    expect(texte()).toContain('0,61 %')
    expect(texte()).toContain('mai 2026')
    expect(texte()).toContain('Admissions en non-valeur')
    expect(texte()).toContain('4,7 Md€')
    expect(texte()).toContain('429')
    expect(texte()).toContain('Aucune personne physique')
  })

  it('accessibilité et règles du site : tableaux légendés, en-têtes de portée, liens externes sûrs, sigles développés, pas de tiret long', () => {
    for (const t of Array.from(main.querySelectorAll('table'))) {
      expect(t.querySelector('caption')?.textContent?.trim()).toBeTruthy()
      for (const th of Array.from(t.querySelectorAll('th'))) expect(['col', 'row']).toContain(th.getAttribute('scope'))
    }
    const titres = Array.from(main.querySelectorAll('h1, h2, h3, h4')).map((x) => Number(x.tagName[1]))
    for (let i = 1; i < titres.length; i++) expect(titres[i] - titres[i - 1]).toBeLessThanOrEqual(1)
    for (const a of Array.from(main.querySelectorAll('a[href^="http"]'))) {
      expect(a.getAttribute('href')).toMatch(/^https:\/\//)
      expect(a.getAttribute('rel')).toBe('noopener noreferrer')
    }
    expect(main.textContent).not.toContain('—')
    expect(main.querySelectorAll('[style]').length).toBe(0)
    // Hors citations exactes et titres de documents, un sigle n'apparaît jamais sans son nom développé juste avant.
    const copie = main.cloneNode(true) as HTMLElement
    copie.querySelectorAll('blockquote, a[href^="http"]').forEach((x) => x.remove())
    const t = copie.textContent!.replace(/\s+/g, ' ')
    // Chaque texte développe le sigle à sa première apparition : le nom complet figure donc avant toute forme courte.
    for (const [s, long] of [['DGFiP', 'Direction générale des finances publiques'], ['HCFiPS', 'Haut Conseil du financement de la protection sociale'], ['STDR', 'service de traitement des déclarations rectificatives'], ['PLF', 'projet de loi de finances'], ['CGSS', 'Caisse générale de sécurité sociale']]) {
      const i = t.search(new RegExp(`(?<![\\p{L}])${s}(?![\\p{L}])`, 'u'))
      if (i < 0) continue
      expect(t.toLowerCase().indexOf(long.toLowerCase()), s).toBeGreaterThanOrEqual(0)
      expect(t.toLowerCase().indexOf(long.toLowerCase()), s).toBeLessThan(i)
    }
  })

  it('lexique neutre (docs/lexique_neutre.json) sur tout le texte affiché', () => {
    const lex = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; exceptions: string[] }
    let x = (document.body.textContent ?? '').replace(/\s+/g, ' ')
    for (const e of lex.exceptions) x = x.split(e).join(' ')
    for (const r of lex.regles) expect(x, r.raison).not.toMatch(new RegExp(`(?<![\\p{L}\\p{N}_])(?:${r.termes.join('|')})(?![\\p{L}\\p{N}_])`, 'iu'))
  })
})

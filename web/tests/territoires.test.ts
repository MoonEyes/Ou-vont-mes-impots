// @vitest-environment happy-dom
// Blocs « territoires » des pages commune et département (site/data/territoires/, site/data/local_satellites/),
// sur des extraits réels du Rhône (web/tests/fixtures/data/territoires/, web/tests/fixtures/data/local_satellites/).
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { dateFr } from '../src/ecrans/territoires'
import { monterPage } from './aide-dom'

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = (el: ParentNode | null = main) => (el as HTMLElement | null)?.textContent?.replace(/\s+/g, ' ') ?? ''
const section = (id: string) => main.querySelector<HTMLElement>(`#${id}`)

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('page commune : projets aidés par l’État, loi SRU, organismes rattachés', () => {
  it('Lyon : la commune puis son intercommunalité, chacune avec ses subventions par exercice', async () => {
    await ecran('#/local/commune?insee=69123')
    const z = section('sec-projets-etat')!
    expect(z.getAttribute('aria-busy')).toBeNull()
    expect(Array.from(z.querySelectorAll('h3')).map((x) => x.textContent)).toEqual(['Lyon', 'Métropole de Lyon'])
    expect(texte(z)).toContain('« Reorganisation de la mjc duchere »')
    expect(texte(z)).toContain('Dotation de soutien à l’investissement local (DSIL)')
    expect(texte(z)).toContain('ne pas additionner les lignes')
    for (const t of Array.from(z.querySelectorAll('table'))) {
      expect(t.querySelector('caption')).not.toBeNull()
      expect(t.querySelectorAll('th[scope="col"]').length).toBe(3)
    }
  })

  it('Lyon : inventaire SRU par édition, valeur publiée « - € » gardée telle quelle', async () => {
    await ecran('#/local/commune?insee=69123')
    const z = section('sec-sru')!
    const lignes = Array.from(z.querySelectorAll('tbody tr'))
    expect(lignes.map((l) => l.querySelector('th')?.textContent)).toEqual(['2026', '2025', '2024', '2023'])
    expect(texte(lignes[0])).toContain('66 166')
    expect(texte(lignes[0])).toContain('24,61 %')
    expect(texte(lignes[0])).toContain('déficitaire (taux sous l’objectif)')
    expect(texte(lignes[0])).toContain('« - € »')
    expect(texte(z)).toContain('solidarité et au renouvellement urbains (SRU)')
  })

  it('Affoux : absente de l’inventaire SRU, phrase explicative et non un zéro', async () => {
    await ecran('#/local/commune?insee=69001')
    const z = section('sec-sru')!
    expect(z.querySelector('table')).toBeNull()
    expect(texte(z)).toContain('ne figure dans aucune édition de l’inventaire')
  })

  it('Lyon : syndicats, centre d’action sociale, mobilité et eau, sans addition', async () => {
    await ecran('#/local/commune?insee=69123')
    const z = section('sec-organismes')!
    const t = texte(z)
    expect(t).toContain('ne pas additionner ces montants entre eux ni au budget de la commune')
    // Syndicats : 23 lignes, rattachement direct d'abord.
    const syn = z.querySelector('table')!
    expect(syn.querySelector('caption')?.textContent).toBe('Syndicats rattachés à la commune, exercice 2025 (autre exercice indiqué sous le montant)')
    const rattachements = Array.from(syn.querySelectorAll('tbody tr')).map((l) => l.querySelectorAll('td')[1].textContent)
    expect(rattachements).toHaveLength(23)
    expect(rattachements.slice(0, 5).every((r) => r === 'la commune est membre')).toBe(true)
    expect(rattachements[rattachements.length - 1]).toBe('par un autre syndicat')
    const types = Array.from(syn.querySelectorAll('tbody tr')).map((l) => l.querySelectorAll('td')[0].textContent ?? '')
    expect(types).toContain('Syndicat intercommunal à vocation unique')
    expect(types.join(' ')).not.toMatch(/\b(SMO|SMF|SIVU|SIVOM)\b/)
    expect(t).toContain('CCAS LYON (Centre communal d’action sociale)')
    expect(t).toContain('144,94 € par habitant')
    expect(t).toContain('SYTRAL Mobilités')
    expect(t).toContain('Taux en vigueur au 1er janvier 2026')
    expect(t).toContain('versement mobilité : 2,00 %')
    expect(t).toContain('ODbL')
    expect(t).toContain('Prix TTC par m³ (120 m³)')
    expect(t).toContain('Métropole de Lyon (Grand Lyon)')
    // Plusieurs entités de gestion : écart des prix montré, pas de prix désigné.
    expect(t).toContain('de 2,12 € à 2,12 €')
  })

  it('Affoux : dernier exercice publié du centre, taux de versement mobilité', async () => {
    await ecran('#/local/commune?insee=69001')
    const t = texte(section('sec-organismes'))
    // Dernier exercice publié : 2022 (les suivants sont null à la source, pas 0).
    expect(t).toContain('CCAS - AFFOUX (Centre communal d’action sociale) : 100 € de dépenses en 2022')
    expect(t).toContain('versement mobilité : 0,70 %')
    expect(main.querySelectorAll('[aria-busy]').length).toBe(0)
  })
})

describe('page département : projets, aide sociale, loi SRU, organismes', () => {
  it('Rhône : tableau par exercice et dotation, dix bénéficiaires, sigles développés', async () => {
    await ecran('#/local/departement?dep=69')
    const z = section('sec-projets-etat')!
    const t = texte(z)
    expect(z.querySelector('caption')?.textContent).toBe('Subventions attribuées par exercice et par dotation, Rhône')
    expect(Array.from(z.querySelectorAll('tbody th')).map((x) => x.textContent)[0]).toBe('2025')
    expect(t).toContain('Dotation d’équipement des territoires ruraux (DETR)')
    expect(z.querySelectorAll('ol li')).toHaveLength(10)
    expect(z.querySelector('ol li')?.textContent).toMatch(/^Métropole de Lyon : 16,4 M€ pour \d+ projets/)
    expect(t).toContain('Ordre : subvention totale décroissante')
  })

  it('Rhône : aide sociale de chaque collectivité, sur 100 €, sans les additionner', async () => {
    await ecran('#/local/departement?dep=69')
    const z = section('sec-aide-sociale')!
    expect(Array.from(z.querySelectorAll('h3')).map((x) => x.textContent)).toEqual(['Département du Rhône', 'Nouveau Rhône', 'Métropole de Lyon'])
    expect(texte(z)).toContain('1,0 Md€ de dépenses nettes en 2024, soit 706 € par habitant')
    expect(texte(z)).toContain('Aide sociale à l’enfance')
    expect(texte(z)).toContain('Périmètre : Nouveau Rhône (département, depuis 2015)')
    expect(z.querySelectorAll('.surligne')).toHaveLength(0)
  })

  it('Rhône : communes de la loi SRU et organismes départementaux', async () => {
    await ecran('#/local/departement?dep=69')
    const sru = section('sec-sru')!
    expect(sru.querySelector('caption')?.textContent).toBe('Communes de l’inventaire, édition 2026 (ordre alphabétique)')
    expect(Array.from(sru.querySelectorAll('tbody th')).map((x) => x.textContent)).toContain('Lyon')
    const org = section('sec-organismes')!
    expect(texte(org)).toContain('MAISON DEPARTEMENTALE DES PERSONNES HANDICAPEES - RHÔNE ET METROPOLE DE LYON')
    expect(texte(org)).toContain('Maison départementale des personnes handicapées')
    expect(main.querySelectorAll('[aria-busy]').length).toBe(0)
    expect(main.textContent).not.toContain('—')
  })

  it('date française du premier jour du mois', () => {
    expect(dateFr('2026-01-01')).toBe('1er janvier 2026')
    expect(dateFr('2025-07-15')).toBe('15 juillet 2025')
  })
})

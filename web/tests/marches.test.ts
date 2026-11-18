// @vitest-environment happy-dom
// Page « Les marchés publics » (/beneficiaires/marches) sur des fixtures copiées de site/data/marches.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { monterPage } from './aide-dom'

const FX = join(process.cwd(), 'tests', 'fixtures', 'data', 'marches')
const lire = (f: string) => JSON.parse(readFileSync(join(FX, f), 'utf8'))
const idx = lire('index.json')
const annees = lire('annees.json')
const titulaires = lire('titulaires.json')
const nf1 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const nf0 = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 })
const espaces = (s: string) => s.replace(/\s+/g, ' ')
const mdFr = (x: number) => espaces(`${nf1.format(x / 1e9)} Md€`)

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => espaces(main.textContent ?? '')

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('marchés publics', () => {
  it('route enfant de « Qui reçoit l’argent », titre, fil d’Ariane et année la plus récente par défaut', async () => {
    const r = ROUTES.find((x) => x.chemin === '/beneficiaires/marches')!
    expect(r.parent).toBe('/beneficiaires')
    await ecran('#/beneficiaires/marches')
    expect(main.querySelector('h1')?.textContent?.trim()).toBe('Les marchés publics')
    expect(main.querySelector('nav[aria-label="Fil d\'Ariane"] [aria-current=page]')?.getAttribute('href')).toBe('#/beneficiaires/marches')
    const derniere = annees.par_annee.filter((p: { total_eur: number | null }) => p.total_eur !== null).at(-1)
    expect(main.querySelector('.bascule [aria-current="true"]')?.textContent).toBe(String(derniere.annee))
    const cle = main.querySelector('.cles li')!
    expect(espaces(cle.querySelector('strong')!.textContent!)).toBe(mdFr(derniere.total_eur))
    expect(cle.querySelector('span')!.textContent).toBe(`de marchés notifiés en ${derniere.annee}, hors taxes`)
    expect(texte()).toContain('Ce ne sont pas des sommes payées')
    expect(main.querySelector('.erreur')).toBeNull()
  })

  it('billet « sur 100 € » par type d’achat, lu dans les données, avec son équivalent texte', async () => {
    await ecran('#/beneficiaires/marches?a=2024')
    const an = annees.par_annee.find((p: { annee: number }) => p.annee === 2024)
    const parts = Array.from(main.querySelectorAll('.billet .billet-large [aria-label]'))
      .map((e) => e.getAttribute('aria-label') ?? '')
      .filter((l) => / : [\d,]+ € sur 100 € de marchés$/.test(l))
    expect(parts.length).toBe(an.par_type.filter((t: { montant_eur: number }) => t.montant_eur > 0).length)
    const somme = parts.map((p) => Number(/: ([\d,]+) €/.exec(p)![1].replace(',', '.'))).reduce((x, y) => x + y, 0)
    expect(Math.abs(somme - 100)).toBeLessThanOrEqual(0.2)
    const travaux = an.par_type.find((t: { type: string }) => t.type === 'Travaux')
    expect(parts).toContain(`Travaux : ${nf1.format((travaux.montant_eur / an.total_eur) * 100)} € sur 100 € de marchés`)
    expect(main.querySelectorAll('.parts li').length).toBe(parts.length)
    // Un seul surligneur, posé sur un montant, dans un bloc qui dit « sur 100 € ».
    const s = main.querySelectorAll('.surligne')
    expect(s).toHaveLength(1)
    expect(s[0].closest('[data-cle]')?.textContent).toMatch(/sur 100 €/)
  })

  it('2021 : les séries de montants identiques sont écartées, comptées et montrées, jamais additionnées', async () => {
    await ecran('#/beneficiaires/marches?a=2021')
    const an = annees.par_annee.find((p: { annee: number }) => p.annee === 2021)
    const serie = an.ecartes.montant_serie_repetee
    expect(serie.lignes).toBeGreaterThan(0)
    const avert = espaces(main.querySelector('.avertissement')?.textContent ?? '')
    expect(avert).toContain(`2021 : le montant retenu (${mdFr(an.total_eur)}) ne comprend pas ${mdFr(serie.montant_eur)}`)
    expect(avert).toContain('pas additionnés')
    const premiere = idx.series_repetees.principales[0]
    expect(avert).toContain(`${nf0.format(premiere.marches)} marchés de ${premiere.denomination}`)
    // La somme retenu + écarté n'apparaît nulle part.
    expect(texte()).not.toContain(mdFr(an.total_eur + serie.montant_eur))
    // Tableau année par année : 7 lignes, compteurs de lignes écartées.
    const t = Array.from(main.querySelectorAll('table')).find((x) => x.querySelector('caption')?.textContent?.startsWith('Montants retenus et montants écartés'))!
    expect(t.querySelectorAll('tbody tr')).toHaveLength(annees.par_annee.length)
    const l2021 = espaces(Array.from(t.querySelectorAll('tbody tr')).find((tr) => tr.querySelector('th')?.textContent === '2021')!.textContent ?? '')
    expect(l2021).toContain(`${nf0.format(serie.lignes).replace(/\s/g, ' ')} lignes`)
    // Règle publiée et marques du producteur, avec leur compteur.
    expect(texte()).toContain('Série de montants identiques : au moins 3 marchés d’un même acheteur'.replace('’', "'"))
    expect(texte()).toContain(`${espaces(nf0.format(idx.anomalies_source.aberrant.lignes))} lignes « aberrant »`)
    expect(texte()).toContain('Les plus gros montants conservés')
  })

  it('par acheteur, secteur, région et titulaire, avec année, source et règle d’ordre', async () => {
    await ecran('#/beneficiaires/marches?a=2023')
    const h2 = Array.from(main.querySelectorAll('h2')).map((x) => x.textContent ?? '')
    for (const t of ['Par acheteur', 'Par secteur, en 2023', 'Par région de l’acheteur, en 2023', 'Principaux titulaires, en 2023']) expect(h2.some((x) => x.startsWith(t)), t).toBe(true)
    expect(texte()).toContain('Par type d’acheteur, en 2023')
    expect(texte()).toContain('Travaux de construction')
    expect(texte()).toContain('Île-de-France')
    const t23 = titulaires.par_annee.find((p: { annee: number }) => p.annee === 2023)
    expect(texte()).toContain(t23.titulaires[0].denomination)
    expect(texte()).toContain('Entrepreneurs individuels et titulaires non diffusibles, agrégés et jamais nommés')
    expect(main.querySelectorAll('[data-regle-ordre]').length).toBeGreaterThanOrEqual(4)
    expect(main.querySelectorAll('.source').length).toBeGreaterThanOrEqual(6)
    for (const s of Array.from(main.querySelectorAll('.source'))) expect(s.textContent).toMatch(/data\.gouv\.fr|Observatoire|recensement/)
    // Repère officiel publié à côté, sans addition.
    expect(texte()).toContain(mdFr(idx.repere_oecp.montant_eur))
    expect(texte()).toContain('ni additionnés')
    // Aucun sigle de catégorie seul.
    expect(texte()).not.toMatch(/\bEPIC\b/)
  })

  it('accessibilité : tableaux légendés avec en-têtes, pas de style en ligne ni de tiret long', async () => {
    await ecran('#/beneficiaires/marches?a=2022')
    const tables = Array.from(main.querySelectorAll('table'))
    expect(tables.length).toBeGreaterThanOrEqual(6)
    for (const t of tables) {
      expect(t.querySelector('caption')?.textContent?.trim()).toBeTruthy()
      for (const th of Array.from(t.querySelectorAll('th'))) expect(['col', 'row']).toContain(th.getAttribute('scope'))
    }
    const fautifs = Array.from(main.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l') && !el.hasAttribute('data-g') && !el.hasAttribute('data-f'))
    expect(fautifs).toHaveLength(0)
    expect(main.textContent).not.toContain('—')
    expect(main.textContent).not.toMatch(/`/)
    // Aucun sigle seul : chaque sigle du domaine est développé.
    expect(/.{60}\b(DECP|OECP|SIRENE)\b.{20}/.exec(main.textContent ?? '')?.[0]).toBeUndefined()
    const titres = Array.from(main.querySelectorAll('h1, h2, h3')).map((x) => Number(x.tagName[1]))
    expect(titres[0]).toBe(1)
    for (let k = 1; k < titres.length; k++) expect(titres[k] - titres[k - 1]).toBeLessThanOrEqual(1)
  })

  it('année inconnue : retour à la plus récente ; données absentes : état « en cours d’intégration »', async () => {
    await ecran('#/beneficiaires/marches?a=1990')
    expect(main.querySelector('.bascule [aria-current="true"]')?.textContent).toBe(String(idx.annees.at(-1)))
    const { rendre } = await import('../src/ecrans/marches')
    const { viderCache } = await import('../src/donnees')
    viderCache()
    const vrai = globalThis.fetch
    globalThis.fetch = (async (u: string) => (String(u).includes('marches/') ? new Response('', { status: 404 }) : vrai(u))) as typeof fetch
    const z = document.createElement('div')
    await rendre(z, new URLSearchParams())
    expect(z.textContent).toContain('Données en cours d’intégration')
    expect(z.querySelector('a[href="#/beneficiaires?onglet=marches"]')).not.toBeNull()
    globalThis.fetch = vrai
    viderCache()
  })
})

describe('clair', () => {
  it('retire les noms de champs et développe les sigles', async () => {
    const { clair } = await import('../src/ecrans/marches')
    expect(clair('Dernière version publiée (`donneesActuelles`), une ligne.')).toBe('Dernière version publiée, une ligne.')
    expect(clair('les DECP comptent ; le recensement de l\'OECP compte (voir `par_nature` dans annees.json).')).toBe(
      'les données essentielles de la commande publique comptent ; le recensement de l’Observatoire économique de la commande publique compte.',
    )
    expect(clair('Observatoire économique de la commande publique (OECP), direction')).toBe('Observatoire économique de la commande publique, direction')
    expect(clair('au moins 40 000 € HT')).toBe('au moins 40 000 € hors taxes')
  })
})

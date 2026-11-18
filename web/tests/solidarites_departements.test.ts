// @vitest-environment happy-dom
// Écran « Ce que les départements versent pour les solidarités » (/explorer/solidarites-departements) sur des
// extraits réels de site/data (tests/fixtures/solidarites_departements/, servis avant les fixtures communes) :
// chiffres lus dans les données, source et statut, valeur absente « non publié » (jamais 0), reste à charge calculé
// par le pipeline JAMAIS affiché (allocations et recettes côte à côte, phrase sur l'absence de chiffre officiel),
// code 67A de l'OFGL signalé, écarts entre sources montrés sans être tranchés, liens vers les pages voisines,
// lexique neutre, sigles expliqués, accessibilité, état propre quand les fichiers manquent, bloc de la page département.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { expliqueDansLeTexte, type Glossaire } from '../src/composants/sigles'
import { viderCache } from '../src/donnees'
import { ecartsCollectivite, motifInaccessible } from '../src/ecrans/solidarites_departements'
import glossaire from '../src/glossaire.json'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { entier, eurLisible, pct } from '../src/util'
import { attendreQue, monterPage } from './aide-dom'

const RACINE = process.cwd()
const PROPRES = join(RACINE, 'tests', 'fixtures', 'solidarites_departements')
const COMMUNES = join(RACINE, 'tests', 'fixtures')
const PAGE = '#/explorer/solidarites-departements'
const lire = (rel: string) => JSON.parse(readFileSync(join(PROPRES, 'data', rel), 'utf8'))
const n = (t: string | null | undefined) => (t ?? '').replace(/\s+/g, ' ').trim()
const IDX = lire('solidarites_departements/index.json')
const CPT = lire('solidarites_departements/comptes.json')
const BEN = lire('solidarites_departements/beneficiaires.json')
const ECA = lire('solidarites_departements/ecarts.json')
const TER = lire('territoires/index.json')

const requetes: string[] = []
let absents: RegExp | null = null
let main: HTMLElement

function servir() {
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const rel = u.split('?')[0]
    if (absents?.test(rel)) return new Response('introuvable', { status: 404 })
    for (const base of [PROPRES, COMMUNES]) {
      const f = join(base, rel)
      if (existsSync(f)) return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    return new Response('introuvable', { status: 404 })
  })
}
async function ecran(fragment = PAGE) {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => n(main.textContent)
const tableau = (debutLegende: string, racine: ParentNode = main) => {
  const t = Array.from(racine.querySelectorAll('table')).find((x) => n(x.querySelector('caption')?.textContent).startsWith(debutLegende))
  expect(t, `tableau « ${debutLegende} »`).toBeDefined()
  return t as HTMLTableElement
}
const ligne = (t: HTMLTableElement, entete: string) => Array.from(t.querySelectorAll('tbody tr')).find((tr) => n(tr.querySelector('th')?.textContent) === entete) as HTMLTableRowElement
const cellules = (tr: HTMLTableRowElement) => Array.from(tr.querySelectorAll('td')).map((td) => n(td.textContent))
// Formats français normalisés comme le texte lu (espaces fines insécables comprises).
const E = (x: number) => n(eurLisible(x))
const N = (x: number) => n(entier(x))
const P = (x: number) => n(pct(x))
const col = (c: string) => CPT.colonnes.indexOf(c)

/** Toutes les écritures possibles d'un montant de reste à charge calculé (Md€, M€, k€, euros, pourcentage). */
function formesResteACharge(): string[] {
  const out = new Set<string>()
  for (const t of Object.values(IDX.totaux) as any[]) {
    for (const r of Object.values(t.reste_a_charge_calcule ?? {}) as any[]) {
      if (typeof r.montant_eur === 'number') out.add(E(r.montant_eur))
      if (typeof r.part_couverte_pct === 'number') out.add(P(r.part_couverte_pct))
    }
  }
  for (const c of Object.values(CPT.collectivites) as any[])
    for (const v of Object.values(c.reste_a_charge_calcule_eur ?? {}) as (number | null)[][]) for (const x of v) if (typeof x === 'number' && Math.abs(x) >= 1e4) out.add(E(x))
  return [...out]
}
/** Montants publiés (allocations, recettes) de l'écran, pour écarter une coïncidence d'arrondi. */
function montantsPublies(): Set<string> {
  const out = new Set<string>()
  for (const t of Object.values(IDX.totaux) as any[]) for (const v of Object.values(t.eur) as (number | null)[]) if (typeof v === 'number') out.add(E(v))
  for (const c of Object.values(CPT.collectivites) as any[]) for (const v of Object.values(c.eur) as (number | null)[][]) for (const x of v) if (typeof x === 'number') out.add(E(x))
  for (const e of IDX.ecarts) for (const k of ['valeur', 'autre_valeur', 'ecart']) if (typeof e[k] === 'number') out.add(E(e[k]))
  for (const l of ECA.lignes) for (const x of l.slice(3, 6)) if (typeof x === 'number') out.add(E(x))
  for (const v of Object.values(TER.totaux.aide_sociale_drees.france['ase.brute']) as number[]) out.add(E(v))
  for (const d of ['44', '67']) {
    const t = lire(`territoires/${d}.json`)
    for (const c of t.aide_sociale.collectivites) for (const v of Object.values(c.postes.ase.brute.eur) as number[]) out.add(E(v))
  }
  for (const l of IDX.ecarts) if (typeof l.ecart_pct === 'number') out.add(P(l.ecart_pct))
  for (const l of ECA.lignes) if (typeof l[6] === 'number') out.add(P(l[6]))
  return out
}

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu') as HTMLElement
})
afterEach(() => {
  absents = null
  viderCache()
})

describe('écran solidarités des départements', () => {
  it('route : enfant de « Explorer », thème politiques, voisins existants, titres sans sigle', () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/solidarites-departements')!
    expect(r.parent).toBe('/explorer')
    expect(r.theme).toBe('politiques')
    expect(r.voisins?.length).toBeGreaterThan(0)
    expect(r.voisins?.every((v) => ROUTES.some((x) => x.chemin === v))).toBe(true)
    expect(`${r.titre} ${r.titrePage} ${r.description} ${r.resume}`).not.toMatch(/\b(RSA|APA|PCH|ASE|OFGL|DREES|CNSA|TICPE|FMDI)\b/)
  })

  it('vue nationale : allocations et recettes lues dans index.json, source OFGL, statut, introduction', async () => {
    await ecran()
    expect(n(main.querySelector('h1')?.textContent)).toBe('Ce que les départements versent pour les solidarités')
    expect(main.querySelector('.fil-ariane [aria-current=page]')?.getAttribute('href')).toBe(PAGE)
    expect(texte()).toContain('Cette page montre, de 2012 à 2025')
    expect(texte()).toContain('Elle ne montre pas ce que reçoit une personne')
    const an = String(IDX.annees_comptes[IDX.annees_comptes.length - 1])
    const cles = n(main.querySelector('ul.cles')?.textContent)
    expect(cles).toContain(E(IDX.totaux[an].eur.allocations_rsa))
    expect(cles).toContain(E(IDX.totaux[an].eur.allocations_apa))
    expect(cles).toContain(E(IDX.totaux[an].eur.allocations_pch))
    expect(cles).toContain(`comptes de ${IDX.totaux[an].collectivites_par_colonne.allocations_rsa} collectivités`)
    const alloc = tableau('Allocations versées par les départements')
    expect(cellules(ligne(alloc, '2012'))).toEqual(['allocations_rsa', 'allocations_apa', 'allocations_pch', 'frais_hebergement'].map((c) => E(IDX.totaux['2012'].eur[c])))
    const rec = tableau('Recettes rattachées aux allocations')
    expect(cellules(ligne(rec, an))).toEqual(['ticpe', 'fmdi', 'cnsa'].map((c) => E(IDX.totaux[an].eur[c])))
    expect(main.querySelector(`.source a[href="${IDX.sources.ofgl_departements.page}"]`)).not.toBeNull()
    expect(main.querySelectorAll('.source .badge').length).toBeGreaterThan(2)
  })

  it('reste à charge : jamais affiché, montants publiés côte à côte, phrase sur l’absence de chiffre officiel', async () => {
    await ecran('#/explorer/solidarites-departements?dep=67')
    await attendreQue(() => !!main.querySelector('#sol-dep-resultat table'))
    const t = texte()
    expect(t).toContain('Aucun reste à charge officiel n’est publié par département')
    expect(t).toContain('sans soustraction')
    expect(t).not.toMatch(/reste à charge calculé|part couverte|reste_a_charge/i)
    // Aucune valeur calculée par le pipeline n'apparaît (sauf coïncidence d'arrondi avec un montant publié).
    const publies = montantsPublies()
    // Montants affichés, lus cellule par cellule et dans le texte, un montant entier à la fois (« 1,2 Md€ » ≠ « 11,2 Md€ »).
    const affiches = new Set<string>()
    for (const el of Array.from(main.querySelectorAll('td, p, li, span')))
      for (const m of n(el.textContent).matchAll(/(?<![\d,])-?\d{1,3}(?: \d{3})*(?:,\d+)? ?(?:Md€|M€|k€|€|%)/g)) affiches.add(m[0])
    expect(affiches.size).toBeGreaterThan(50)
    for (const f of formesResteACharge()) if (!publies.has(f)) expect(affiches.has(f), f).toBe(false)
    // Le motif publié qui annonce le calcul est réécrit.
    const inaccessible = IDX.sources_inaccessibles.find((s: { source: string }) => /reste à charge/i.test(s.source))
    expect(motifInaccessible(inaccessible)).not.toMatch(/publie un calcul/)
    expect(t).not.toContain('le site publie un calcul')
  })

  it('aide sociale à l’enfance : total de la DREES lu dans territoires/, présenté comme une autre source', async () => {
    await ecran()
    const ase = TER.totaux.aide_sociale_drees.france['ase.brute']
    const t = tableau('Aide sociale à l’enfance, dépenses brutes')
    expect(cellules(ligne(t, '2024'))).toEqual([E(ase['2024'])])
    expect(ligne(t, '2011')).toBeUndefined()
    expect(texte()).toContain('Il ne s’ajoute pas aux montants des comptes ci-dessus')
  })

  it('bénéficiaires France : totaux publiés par la DREES, « non publié » hors séries, jamais 0', async () => {
    await ecran()
    const t = tableau('Bénéficiaires de l’aide sociale des départements, France entière')
    const rsa = BEN.series.find((s: { id: string }) => s.id === 'rsa')
    const ase = BEN.series.find((s: { id: string }) => s.id === 'ase_accueillis')
    const c24 = cellules(ligne(t, '2024'))
    expect(c24[0]).toBe(N(BEN.totaux.france.rsa[rsa.annees.indexOf(2024)]))
    expect(c24[4]).toBe(N(BEN.totaux.france.ase_accueillis[ase.annees.indexOf(2024)]))
    expect(texte()).toContain('ces nombres ne s’additionnent pas')
    // Le nom de clé technique de la rupture 2016 n'est pas affiché.
    expect(texte()).not.toContain('rsa_2016_ancien_systeme')
  })

  it('écarts nationaux : comptes et DREES côte à côte, écart calculé signalé, jamais tranché', async () => {
    await ecran()
    const e = IDX.ecarts.find((x: { grandeur: string; annee: number }) => x.grandeur === 'allocations_apa' && x.annee === 2024)
    const t = tableau('Allocation personnalisée d’autonomie : comptes')
    expect(cellules(ligne(t, '2024'))).toEqual([E(e.valeur), E(e.autre_valeur), E(e.ecart), P(e.ecart_pct)])
    expect(texte()).toContain('le site ne choisit pas entre elles et ne les additionne pas')
    expect(texte()).toContain('ne dit pas laquelle des deux sources est juste')
  })

  it('Bas-Rhin (?dep=67) : code 67A signalé, deux collectivités présentées à part, valeurs nulles « non publié »', async () => {
    await ecran('#/explorer/solidarites-departements?dep=67')
    await attendreQue(() => !!main.querySelector('#sol-dep-resultat table'))
    const z = main.querySelector('#sol-dep-resultat') as HTMLElement
    expect(n(z.textContent)).toContain('le code 67A regroupe les deux départements')
    expect(n(z.textContent)).toContain('à ne pas additionner')
    expect(main.querySelector('#sol-dep-choix option[value="67"]')?.hasAttribute('selected')).toBe(true)
    const bas = tableau('Bas-Rhin : allocations versées', z)
    expect(cellules(ligne(bas, '2020'))[0]).toBe(E(CPT.collectivites['67'].eur['2020'][col('allocations_rsa')]))
    expect(ligne(bas, '2021')).toBeUndefined()
    const alsace = tableau(`${CPT.collectivites['6AE'].nom} : allocations versées`, z)
    expect(cellules(ligne(alsace, '2024'))[1]).toBe(E(CPT.collectivites['6AE'].eur['2024'][col('allocations_apa')]))
    // Écarts du département dans un bloc repliable, avec les deux sources.
    const det = z.querySelector('details.sol-ecarts') as HTMLDetailsElement
    expect(det).not.toBeNull()
    const lignes = ecartsCollectivite(ECA, '67').get('allocations_rsa')!
    expect(lignes.length).toBeGreaterThan(0)
    const l0 = lignes[0]
    const t = tableau('Allocations du revenu de solidarité active (67)', det)
    expect(cellules(ligne(t, String(l0.annee)))[0]).toBe(E(Number(l0.valeur)))
    expect(document.title).toContain('Bas-Rhin (67)')
    expect(z.querySelector('a[href="#/explorer/prestations?dep=67"]')).not.toBeNull()
  })

  it('Seine-Saint-Denis (?dep=93) : RSA financé par l’État signalé, ligne absente « non publié », pas 0', async () => {
    await ecran('#/explorer/solidarites-departements?dep=93')
    await attendreQue(() => !!main.querySelector('#sol-dep-resultat table'))
    const z = main.querySelector('#sol-dep-resultat') as HTMLElement
    expect(n(z.textContent)).toContain('Le revenu de solidarité active est financé par l’État dans ce département')
    expect(CPT.collectivites['93'].eur['2023'][col('allocations_rsa')]).toBeNull()
    expect(cellules(ligne(tableau('Seine-Saint-Denis : allocations versées', z), '2023'))[0]).toBe('non publié')
  })

  it('choix d’un département dans la liste : le bloc se recalcule sur place', async () => {
    await ecran()
    expect(n(main.querySelector('#sol-dep-resultat')?.textContent)).toContain('Choisis un département')
    const choix = main.querySelector('#sol-dep-choix') as HTMLSelectElement
    expect(main.querySelector('label[for="sol-dep-choix"]')).not.toBeNull()
    choix.value = '44'
    choix.dispatchEvent(new Event('change'))
    await attendreQue(() => !!main.querySelector('#sol-dep-resultat table'))
    const z = main.querySelector('#sol-dep-resultat') as HTMLElement
    expect(cellules(ligne(tableau('Loire-Atlantique : allocations versées', z), '2025'))[0]).toBe(E(CPT.collectivites['44'].eur['2025'][col('allocations_rsa')]))
    const ase = lire('territoires/44.json').aide_sociale.collectivites[0].postes.ase.brute.eur
    expect(cellules(ligne(tableau('Aide sociale à l’enfance, dépenses brutes publiées par la DREES', z), '2024'))).toEqual([E(ase['2024'])])
    const b = BEN.collectivites['44'].valeurs
    const s = BEN.series.find((x: { id: string }) => x.id === 'apa')
    expect(cellules(ligne(tableau('Loire-Atlantique (44) : bénéficiaires', z), '2024'))[1]).toBe(N(b.apa[s.annees.indexOf(2024)]))
  })

  it('pages voisines reliées, sans recopier leurs montants ; aucune requête externe', async () => {
    requetes.length = 0
    await ecran()
    for (const href of ['#/explorer/prestations', '#/explorer/collectivites', '#/explorer/secu']) expect(main.querySelector(`.liens-sortie a[href="${href}"]`), href).not.toBeNull()
    expect(texte()).toContain('Ils ne sont pas recopiés ici et ne s’additionnent pas')
    expect(requetes.every((u) => u.startsWith('data/'))).toBe(true)
    expect(requetes.some((u) => u.startsWith('data/prestations/'))).toBe(false)
  })

  it('accessibilité : légende et en-têtes de portée pour chaque tableau, hiérarchie des titres, zone défilante', async () => {
    await ecran('#/explorer/solidarites-departements?dep=67')
    await attendreQue(() => !!main.querySelector('#sol-dep-resultat table'))
    for (const t of Array.from(main.querySelectorAll('table'))) {
      expect(n(t.querySelector('caption')?.textContent)).not.toBe('')
      for (const th of Array.from(t.querySelectorAll('th'))) expect(['col', 'row']).toContain(th.getAttribute('scope'))
      expect(t.closest('.tableau-defile')).not.toBeNull()
    }
    let precedent = 1
    for (const titre of Array.from(main.querySelectorAll('h1, h2, h3, h4'))) {
      const niveau = Number(titre.tagName.slice(1))
      expect(niveau - precedent, n(titre.textContent)).toBeLessThanOrEqual(1)
      precedent = niveau
    }
    expect(main.querySelectorAll('h1')).toHaveLength(1)
  })

  it('lexique neutre et sigles : aucun terme évaluatif, chaque sigle connu du glossaire ou expliqué sur place', async () => {
    await ecran('#/explorer/solidarites-departements?dep=67')
    await attendreQue(() => !!main.querySelector('#sol-dep-resultat table'))
    const LEX = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[] }[]; exceptions: string[] }
    let t = texte().replace(/[\w./:-]*\/[\w./-]+/g, ' ')
    for (const e of LEX.exceptions) t = t.split(e).join(' ')
    for (const r of LEX.regles) expect(t).not.toMatch(new RegExp(`(?<![\\p{L}\\p{N}_])(?:${r.termes.join('|')})(?![\\p{L}\\p{N}_])`, 'iu'))
    const G = glossaire as unknown as Glossaire
    const connus = new Set([...G.termes.flatMap((x) => (x.sigle ? [x.sigle, ...(x.variantes ?? [])] : [])), ...(G.pas_des_sigles ?? []).map((p) => p.mot)])
    const brut = texte().replace(/\S*[/\\]\S*|\bhttps?:\S+/g, ' ')
    const sigles = new Set([...brut.matchAll(/(?<![\p{L}\p{N}_])\p{Lu}{3,}(?![\p{L}\p{N}_])/gu)].map((m) => m[0]))
    for (const s of sigles) if (!/^[IVX]+$/.test(s)) expect(connus.has(s) || expliqueDansLeTexte(brut, s), s).toBe(true)
  })

  it('fichiers absents : page « en cours » sans erreur ; comptes absents : bloc « non disponible »', async () => {
    absents = /solidarites_departements\/index\.json/
    await ecran()
    expect(main.querySelector('.en-cours')).not.toBeNull()
    expect(main.querySelector('a[href="#/explorer/prestations"]')).not.toBeNull()
    viderCache()
    absents = /solidarites_departements\/(comptes|beneficiaires|ecarts)\.json|territoires\//
    await ecran('#/explorer/solidarites-departements?dep=44')
    await attendreQue(() => !(main.querySelector('#sol-dep-resultat')?.hasAttribute('aria-busy') ?? true))
    expect(texte()).toContain('Comptes de ce département : donnée non disponible.')
    expect(texte()).toContain('Bénéficiaires : donnée non disponible.')
    expect(texte()).toContain('Dépenses d’aide sociale à l’enfance : donnée non disponible.')
  })

  it('page département : bloc court qui renvoie à cette page avec le département choisi', async () => {
    await ecran('#/local/departement?dep=69')
    await attendreQue(() => !!main.querySelector('a[href="#/explorer/solidarites-departements?dep=69"]'))
    const a = main.querySelector('a[href="#/explorer/solidarites-departements?dep=69"]')!
    expect(n(a.textContent)).toContain('pour les solidarités')
    expect(n(main.textContent)).toContain('Les solidarités du département')
  })
})

// @vitest-environment happy-dom
// Recherche dans tout le site : index construit au build (scripts/index-recherche.mjs), moteur et champ « Rechercher »
// de l'en-tête (src/composants/recherche.ts), page de résultats (src/ecrans/recherche.ts).
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { gzipSync } from 'node:zlib'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { aUnePage, fragmentCommune, fragmentDepartement } from '../src/chemins'
import {
  adresse,
  assembler,
  brancherEntete,
  chercher,
  chercherOrganisations,
  chercherTout,
  construireMoteur,
  contexteOrg,
  distance,
  type IndexBrut,
  type Moteur,
  normaliser,
  oublierMoteur,
  precision,
  REGLE_ORDRE,
  selection,
  sirenDe,
} from '../src/composants/recherche'
import GLOSSAIRE from '../src/glossaire.json'
import { TOUS_DEPARTEMENTS } from '../src/departements'
import { viderCache } from '../src/donnees'
import { afficher, lireFragment, REDIRECTIONS } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { libelle } from '../src/util'
import { attendreQue, monterPage, requetes } from './aide-dom'

const RACINE = process.cwd()
const FIXTURES = join(RACINE, 'tests', 'fixtures', 'data')
const SITE_DATA = join(RACINE, '..', 'site', 'data')
const OUTILS = { aUnePage, libelle, departements: TOUS_DEPARTEMENTS, glossaire: GLOSSAIRE }

type Construire = (o: object) => { index: IndexBrut; bilan: Record<string, number> & { entites_sans_page: string[] } }
let construireIndex: Construire
let TAILLE_VISEE: number
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let script: any

const lecteur = (racine: string, ajouts: Record<string, unknown> = {}) => ({
  lire: (c: string) => {
    if (c in ajouts) return ajouts[c]
    try {
      return JSON.parse(readFileSync(join(racine, c), 'utf8'))
    } catch {
      return null
    }
  },
  lister: (d: string) => {
    try {
      return readdirSync(join(racine, d))
    } catch {
      return []
    }
  },
})
/** Code de l'écran d'une route, lu comme le fait le script d'index. */
const sourceEcran = (chemin: string) => {
  const nom = /ecrans\/([\w-]+)/.exec(String(ROUTES.find((r) => r.chemin === chemin)?.charger ?? ''))?.[1]
  return nom && existsSync(join(RACINE, 'src', 'ecrans', `${nom}.ts`)) ? readFileSync(join(RACINE, 'src', 'ecrans', `${nom}.ts`), 'utf8') : ''
}
// Communes : extrait de site/data/local/geo/69.json propre à ces tests (59 communes, dont toutes les « Saint- »).
const GEO69 = JSON.parse(readFileSync(join(RACINE, 'tests', 'fixtures', 'recherche', 'geo-69.json'), 'utf8')) as {
  communes: Record<string, { nom: string; population: number; epci: string | null }>
}
const construire = (racine = FIXTURES, ajouts: Record<string, unknown> = {}, routes = ROUTES, source = sourceEcran) =>
  construireIndex({ ...lecteur(racine, racine === FIXTURES ? { 'local/geo/69.json': GEO69, ...ajouts } : ajouts), routes, sourceEcran: source, outils: OUTILS })

let indexFixtures: IndexBrut
let moteur: Moteur
let servi: IndexBrut | null = null
/** Fichiers servis en plus des fixtures (chemin sous data/), et dossier de données réel lu en plus. */
const servisEnPlus = new Map<string, unknown>()
let racineEnPlus: string | null = null
const geo69 = GEO69

beforeAll(async () => {
  const mod = await import(/* @vite-ignore */ pathToFileURL(join(RACINE, 'scripts', 'index-recherche.mjs')).href)
  construireIndex = mod.construireIndex
  TAILLE_VISEE = mod.TAILLE_VISEE
  script = mod
  indexFixtures = construire().index
  moteur = construireMoteur(indexFixtures)
  monterPage()
  // L'index de recherche est servi comme les autres fichiers de données (data/_recherche.json), ou absent (404).
  const base = globalThis.fetch
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    if (u.startsWith('data/') && servisEnPlus.has(u.slice(5))) {
      requetes.push(u)
      return new Response(JSON.stringify(servisEnPlus.get(u.slice(5))), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    if (u.startsWith('data/') && racineEnPlus && existsSync(join(racineEnPlus, u.slice(5)))) {
      requetes.push(u)
      return new Response(readFileSync(join(racineEnPlus, u.slice(5)), 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    if (String(url) !== 'data/_recherche.json') return base(url)
    requetes.push(String(url))
    return servi ? new Response(JSON.stringify(servi), { status: 200, headers: { 'content-type': 'application/json' } }) : new Response('introuvable', { status: 404 })
  })
})
beforeEach(() => {
  servi = indexFixtures
  servisEnPlus.clear()
  racineEnPlus = null
  oublierMoteur()
  viderCache()
})

const premier = (q: string) => chercher(moteur, q).resultats[0]?.e

describe('moteur de recherche', () => {
  it('normalise sans accents ni casse ni ponctuation', () => {
    expect(normaliser('Saint-Étienne-du-Rouvray')).toBe('saint etienne du rouvray')
    expect(normaliser('L’Haÿ-les-Roses')).toBe('l hay les roses')
    expect(normaliser('ŒUVRES  sociales')).toBe('oeuvres sociales')
    expect(normaliser(' -- ')).toBe('')
  })

  it('distance d’édition bornée : substitution, insertion, suppression, inversion', () => {
    expect(distance('bordaux', 'bordeaux', 1)).toBe(1)
    expect(distance('nantse', 'nantes', 1)).toBe(1)
    expect(distance('lyon', 'lyon', 1)).toBe(0)
    expect(distance('abcd', 'wxyz', 1)).toBe(2)
    expect(distance('marseile', 'marseille', 2)).toBe(1)
  })

  it('insensible aux accents et à la casse, tolérante à une faute de frappe', () => {
    const lyon = premier('lyon')!
    expect(lyon.nom).toBe('Lyon')
    expect(adresse(moteur, lyon)).toBe(fragmentCommune('69123', 'Lyon', geo69.communes['69123'].population))
    for (const q of ['LYON', 'Lyôn', 'lyno', 'lyon,']) expect(premier(q)?.nom, q).toBe('Lyon')
    // « lyonn » : début de « Lyonnais » (7) avant la faute de frappe sur « Lyon » (5), sans tenir compte de la taille.
    expect(chercher(moteur, 'lyonn').resultats.map((r) => r.e.nom)).toContain('Lyon')
    expect(premier('villeurbane')?.nom).toBe('Villeurbanne')
    expect(premier('Rhône')?.nom).toBe('Rhône')
    expect(premier('rhone')?.nom).toBe('Rhône')
  })

  it('codes : INSEE, département, programme ; abréviation « st » ; petits mots ignorés', () => {
    expect(premier('69123')?.nom).toBe('Lyon')
    expect(adresse(moteur, premier('69')!)).toBe(fragmentDepartement('69', 'Rhône'))
    const p = premier('programme 141')!
    expect(p.nom).toBe('Enseignement scolaire public du second degré')
    expect(adresse(moteur, p)).toBe(`#/explorer/etat/detail?id=${encodeURIComponent('Education et recherche/Enseignement scolaire/141')}`)
    expect(premier('141')?.nom).toBe(p.nom)
    expect(premier('st genis laval')?.nom).toBe('Saint-Genis-Laval')
    expect(premier('la ville de villeurbanne')?.nom).toBe('Villeurbanne')
    // Titre exact d'une page : elle vient en tête.
    const titre = ROUTES.find((r) => r.chemin === '/explorer/etat')!.titre
    expect(premier(titre.toUpperCase())?.nom).toBe(titre)
  })

  it('tous les mots doivent figurer, dont un dans le nom ; sinon recherche élargie, annoncée', () => {
    // « rhône » ne figure que dans la précision des communes du Rhône : il affine, il ne suffit pas.
    const r = chercher(moteur, 'villeurbanne rhone')
    expect(r.elargie).toBe(false)
    expect(r.resultats.map((x) => x.e.nom)).toEqual(['Villeurbanne'])
    const deux = chercher(moteur, 'affoux villeurbanne')
    expect(deux.elargie).toBe(true)
    expect(deux.resultats.slice(0, 2).map((x) => x.e.nom).sort()).toEqual(['Affoux', 'Villeurbanne'])
    expect(chercher(moteur, 'x').resultats).toEqual([])
    expect(chercher(moteur, 'zzqxw').resultats).toEqual([])
  })

  it('suggestions variées : pas plus de n résultats d’une même famille', () => {
    const r = chercher(moteur, 'saint').resultats
    expect(r.length).toBeGreaterThan(8)
    const s = selection(r, 8, 4)
    expect(s.length).toBeLessThanOrEqual(8)
    const parFamille = new Map<number, number>()
    for (const x of s) parFamille.set(x.e.f, (parFamille.get(x.e.f) ?? 0) + 1)
    for (const n of parFamille.values()) expect(n).toBeLessThanOrEqual(4)
  })
})

describe('index construit au build', () => {
  it('familles et contenu tirés des fixtures : pages, département, communes, budget, opérateurs, Sécurité sociale, impôts', () => {
    const cles = indexFixtures.familles.map((f) => f.cle)
    for (const c of ['page', 'departement', 'commune', 'intercommunalite', 'mission', 'programme', 'action', 'operateur', 'organisme', 'impot']) expect(cles, c).toContain(c)
    // Aucune famille de personnes physiques ni de bénéficiaires privés.
    for (const c of cles) expect(c).not.toMatch(/candidat|benefic|elu|personne|dirigeant/)
    expect(JSON.stringify(indexFixtures)).not.toContain('ARTHAUD')
    // Pages : exactement les routes indexables, chacune avec son titre.
    const pages = indexFixtures.entrees.filter((e) => indexFixtures.familles[e[0]].cle === 'page')
    expect(pages.map((e) => e[2]).sort()).toEqual(ROUTES.filter((r) => !r.sansIndex).map((r) => '#' + r.chemin).sort())
    expect(pages.find((e) => e[2] === '#/explorer/etat')?.[1]).toBe(ROUTES.find((r) => r.chemin === '/explorer/etat')!.titre)
    // Chaque source citée avec son millésime.
    for (const f of indexFixtures.familles.filter((x) => x.cle !== 'page')) expect(f.source, f.cle).toBeTruthy()
  })

  it('communes : codes, noms et adresses identiques à ceux du site (page propre au-dessus de 5 000 habitants)', () => {
    const communes = moteur.entrees.filter((e) => e.page !== undefined)
    expect(communes.length).toBe(Object.keys(geo69.communes).length)
    for (const e of communes) {
      const c = geo69.communes[e.cible]
      expect(c, e.cible).toBeTruthy()
      expect(e.nom).toBe(c.nom)
      expect(e.page).toBe(aUnePage(c.population))
      expect(adresse(moteur, e)).toBe(fragmentCommune(e.cible, c.nom, c.population))
      expect(precision(moteur, e)).toBe('Commune · Rhône (69)')
    }
    // Intercommunalité : page de sa commune la plus peuplée, qui présente son budget.
    const metropole = premier('métropole de lyon')!
    expect(metropole.nom).toBe('Métropole de Lyon')
    expect(adresse(moteur, metropole)).toBe(fragmentCommune('69123', 'Lyon', geo69.communes['69123'].population))
    expect(precision(moteur, metropole)).toBe('Intercommunalité (Rhône) · présentée sur la page de Lyon, sa commune la plus peuplée')
  })

  it('chaque lien mène à une page du site, qui s’affiche sans erreur', async () => {
    const main = document.getElementById('contenu') as HTMLElement
    for (const e of moteur.entrees) {
      const chemin = lireFragment(adresse(moteur, e)).chemin
      expect(ROUTES.some((r) => r.chemin === chemin) || !!REDIRECTIONS[chemin], `${e.nom} : ${chemin}`).toBe(true)
    }
    // Un exemple par famille, rendu par le routeur du site sur les fixtures (Lyon pour les communes).
    for (let f = 0; f < moteur.familles.length; f++) {
      const e = moteur.entrees.find((x) => x.f === f && (x.page === undefined || x.nom === 'Lyon'))!
      const fragment = adresse(moteur, e)
      location.hash = fragment
      await afficher(ROUTES, main, fragment)
      expect(main.querySelector('.erreur'), `${moteur.familles[f].cle} : ${fragment}`).toBeNull()
      expect(main.querySelector('h1'), fragment).not.toBeNull()
    }
    // Opérateur : la page des opérateurs s'ouvre filtrée sur son nom (paramètre q de la page).
    const op = moteur.entrees.find((e) => moteur.familles[e.f].cle === 'operateur' && e.cible === '')!
    expect(moteur.familles[op.f].modele).toBe('#/explorer/operateurs?q=')
    location.hash = adresse(moteur, op)
    await afficher(ROUTES, main, adresse(moteur, op))
    expect((main.querySelector('#op-q') as HTMLInputElement).value).toBe(op.nom)
    const noms = Array.from(main.querySelectorAll('#liste-op summary')).map((x) => (x.textContent ?? '').toLowerCase())
    expect(noms.length).toBeGreaterThan(0)
    for (const n of noms) expect(n).toContain(op.nom.toLowerCase())
  }, 60000)

  it('prestations : la page qui les présente si elle existe, sinon le bloc de l’arbre qui les finance', () => {
    const prestations = {
      millesime: '2024',
      source: 'CNAF',
      prestations: [
        { id: 'af', nom: 'Allocations familiales', financeur: 'Sécurité sociale, branche famille', liens: [{ vue: 'secu_arbre', id: 'robss/famille' }] },
        { id: 'aah', nom: 'Allocation aux adultes handicapés (AAH)', financeur: 'État', liens: [{ vue: 'arbre_etat', id: 'Solidarite/157/157-12' }] },
      ],
    }
    const sansPage = ROUTES.filter((r) => !sourceEcran(r.chemin).includes('prestations/'))
    const a = construire(FIXTURES, { 'prestations/index.json': prestations }, sansPage).index
    const liens = a.entrees.filter((e) => a.familles[e[0]].cle === 'prestation').map((e) => [e[1], e[2]])
    expect(liens).toEqual([
      ['Allocations familiales', `#/explorer/secu?id=${encodeURIComponent('robss/famille')}`],
      ['Allocation aux adultes handicapés (AAH)', `#/explorer/etat/detail?id=${encodeURIComponent('Solidarite/157/157-12')}`],
    ])
    const avecPage = [...sansPage, { chemin: '/explorer/prestations-essai', titre: 'Prestations', description: 'Essai', charger: async () => ({ rendre: () => {} }) }]
    const b = construire(FIXTURES, { 'prestations/index.json': prestations }, avecPage, (c) => (c === '/explorer/prestations-essai' ? "chargerSiPresent('prestations/index.json')" : sourceEcran(c))).index
    expect(b.entrees.filter((e) => b.familles[e[0]].cle === 'prestation').map((e) => e[2])).toEqual(['#/explorer/prestations-essai', '#/explorer/prestations-essai'])
  })

  it('autres entités publiques : indexées seulement quand une page du site les affiche', () => {
    const regimes = { millesime: '2024', source: 'DREES', regimes: { tous: { nom: 'Tous régimes', type: 'ensemble' }, cnav: { nom: 'CNAV (salariés du privé)', type: 'base' } } }
    const sans = construire(FIXTURES, { 'retraites/regimes.json': regimes }, ROUTES, () => '')
    expect(sans.index.familles.map((f) => f.cle)).not.toContain('regime')
    expect(sans.bilan.entites_sans_page).toContain('retraites/regimes.json')
    const avec = construire(FIXTURES, { 'retraites/regimes.json': regimes }, ROUTES, (c) => (c === '/explorer/secu' ? "charger('retraites/regimes.json')" : '')).index
    const r = avec.entrees.filter((e) => avec.familles[e[0]].cle === 'regime')
    expect(r.map((e) => [e[1], e[2]])).toEqual([['CNAV (salariés du privé)', '#/explorer/secu']])
  })

  it.skipIf(!existsSync(join(SITE_DATA, 'local', 'geo')))('index réel (site/data) : noyau et morceaux sous 1 Mo, toutes les communes, recherche rapide', () => {
    const { index, bilan } = construire(SITE_DATA)
    const { noyau, morceaux } = script.decouperIndex(index)
    const texte = JSON.stringify(noyau)
    expect(Buffer.byteLength(texte)).toBeLessThan(TAILLE_VISEE)
    expect(gzipSync(texte).length).toBeLessThan(150_000)
    expect(Object.keys(noyau.morceaux).sort()).toEqual(['communes', 'parlementaires'])
    for (const m of Object.values(morceaux)) {
      const t = JSON.stringify(m)
      expect(Buffer.byteLength(t)).toBeLessThan(TAILLE_VISEE)
      expect(gzipSync(t).length).toBeLessThan(300_000)
    }
    expect(bilan.commune).toBeGreaterThan(34000)
    expect(bilan.departement).toBe(101)
    expect(bilan.parlementaire).toBeGreaterThan(577)
    expect(bilan.glossaire).toBe(GLOSSAIRE.termes.length)
    const m = construireMoteur(assembler(JSON.parse(texte), Object.values(morceaux).map((x) => JSON.parse(JSON.stringify(x)))))
    for (const [q, attendu] of [
      ['nantes', 'Nantes'],
      ['bordaux', 'Bordeaux'],
      ['st etienne', 'Saint-Étienne'],
      ['44109', 'Nantes'],
      ['finistere', 'Finistère'],
      ['allocations familiales', 'Allocations familiales'],
    ]) {
      const t = performance.now()
      const r = chercher(m, q)
      expect(performance.now() - t, q).toBeLessThan(1000)
      expect(r.resultats[0]?.e.nom, q).toBe(attendu)
    }
  }, 60000)
})

describe('champ « Rechercher » de l’en-tête (combobox)', () => {
  const champ = () => document.getElementById('recherche-champ') as HTMLInputElement
  const liste = () => document.getElementById('recherche-suggestions') as HTMLUListElement
  const taper = async (texte: string) => {
    champ().value = texte
    champ().dispatchEvent(new Event('input', { bubbles: true }))
    await attendreQue(() => !liste().hidden && liste().textContent!.includes(`« ${texte} »`))
  }
  const touche = (key: string) => champ().dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))

  it('présent dans l’en-tête de toutes les pages, hors de la navigation, avec son libellé', () => {
    const html = readFileSync(join(RACINE, 'index.html'), 'utf8')
    const entete = /<header class="entete">[\s\S]*<\/header>/.exec(html)![0]
    expect(entete).toContain('<form id="recherche-entete"')
    expect(/<nav id="navigation"[\s\S]*?<\/nav>/.exec(html)![0]).not.toContain('recherche')
    expect(document.querySelector('label[for="recherche-champ"]')?.textContent).toBe('Rechercher dans le site')
    expect(document.querySelector('#recherche-entete button[type="submit"]')?.textContent).toBe('Rechercher')
  })

  it('suggestions au clavier : flèches, Entrée, Échap ; index lu seulement à la première saisie', async () => {
    brancherEntete()
    brancherEntete()
    expect(document.querySelectorAll('#recherche-suggestions')).toHaveLength(1)
    expect(champ().getAttribute('role')).toBe('combobox')
    expect(champ().getAttribute('aria-expanded')).toBe('false')
    expect(champ().getAttribute('aria-controls')).toBe('recherche-suggestions')
    expect(liste().getAttribute('role')).toBe('listbox')
    expect(requetes).not.toContain('data/_recherche.json')
    await taper('lyon')
    expect(requetes).toContain('data/_recherche.json')
    expect(champ().getAttribute('aria-expanded')).toBe('true')
    const options = Array.from(liste().querySelectorAll('[role="option"]'))
    expect(options.length).toBeGreaterThan(1)
    expect(options[0].querySelector('.recherche-nom')?.textContent).toBe('Lyon')
    expect(options.at(-1)?.textContent).toBe('Tous les résultats pour « lyon »')
    expect(document.querySelector('#recherche-entete [role="status"]')?.textContent).toMatch(/^\d+ suggestions?, et le lien vers tous les résultats\.$/)
    touche('ArrowDown')
    expect(champ().getAttribute('aria-activedescendant')).toBe('recherche-option-0')
    expect(options[0].getAttribute('aria-selected')).toBe('true')
    touche('ArrowUp')
    expect(champ().getAttribute('aria-activedescendant')).toBe(`recherche-option-${options.length - 1}`)
    touche('ArrowDown')
    expect(champ().getAttribute('aria-activedescendant')).toBe('recherche-option-0')
    touche('Escape')
    expect(liste().hidden).toBe(true)
    expect(champ().getAttribute('aria-expanded')).toBe('false')
    // Le champ perd le focus (Tab, clic ailleurs) : la liste se ferme.
    touche('ArrowDown')
    expect(liste().hidden).toBe(false)
    champ().dispatchEvent(new FocusEvent('blur'))
    expect(liste().hidden).toBe(true)
    // Entrée sur une suggestion : sa page ; sans suggestion choisie : la page de résultats.
    touche('ArrowDown')
    document.getElementById('recherche-entete')!.dispatchEvent(new Event('submit', { cancelable: true }))
    expect(location.hash).toBe(fragmentCommune('69123', 'Lyon', geo69.communes['69123'].population))
    expect(champ().value).toBe('')
    await taper('villeurb')
    document.getElementById('recherche-entete')!.dispatchEvent(new Event('submit', { cancelable: true }))
    expect(location.hash).toBe('#/recherche?q=villeurb')
  })

  it('un clic sur une suggestion ouvre sa page', async () => {
    brancherEntete()
    await taper('villeurbanne')
    ;(liste().querySelector('[data-i="0"] .recherche-nom') as HTMLElement).click()
    expect(location.hash).toBe(fragmentCommune('69266', 'Villeurbanne', geo69.communes['69266'].population))
  })
})

describe('page « Rechercher dans le site »', () => {
  let main: HTMLElement
  const ecran = async (fragment: string) => {
    location.hash = fragment
    await afficher(ROUTES, main, fragment)
  }
  const statut = () => main.querySelector('#recherche-statut')?.textContent ?? ''
  beforeAll(() => {
    main = document.getElementById('contenu') as HTMLElement
  })

  it('sans texte : formulaire et consignes, aucun index lu', async () => {
    requetes.length = 0
    await ecran('#/recherche')
    expect(main.querySelector('h1')?.textContent).toBe('Rechercher dans le site')
    expect(main.querySelector('label[for="recherche-q"]')?.textContent).toBe('Ce que tu cherches')
    expect(main.querySelectorAll('.bouton-principal')).toHaveLength(1)
    expect(main.querySelector('#recherche-statut')?.getAttribute('role')).toBe('status')
    expect(main.querySelector('.chapeau')?.textContent).toContain('rien de ce que tu tapes n’est envoyé')
    expect(main.textContent).toContain('Elle ne cherche pas dans les montants')
    expect(main.querySelector('[data-regle-ordre]')?.textContent).toBe(REGLE_ORDRE)
    expect(Array.from(main.querySelectorAll('#recherche-consigne a')).map((a) => a.getAttribute('href'))).toContain('#/recherche?q=Lyon')
    expect(requetes).not.toContain('data/_recherche.json')
    expect(document.title).toBe('Rechercher une commune, un programme, une page')
  })

  it('avec un texte : résultats par famille, nombre annoncé, sources de l’index', async () => {
    await ecran('#/recherche?q=lyon')
    await attendreQue(() => /résultat/.test(statut()))
    expect(statut()).toMatch(/^\d+ résultats? pour « lyon »/)
    expect(document.title).toBe('Recherche « lyon » · Où vont mes impôts')
    expect((main.querySelector('#recherche-q') as HTMLInputElement).value).toBe('lyon')
    const groupe = main.querySelector('.recherche-groupe')!
    expect(groupe.querySelector('h2')?.textContent).toMatch(/^Communes \(\d+\)$/)
    const a = groupe.querySelector('a')!
    expect(a.textContent).toBe('Lyon')
    expect(a.getAttribute('href')).toBe(fragmentCommune('69123', 'Lyon', geo69.communes['69123'].population))
    expect(main.querySelector('.recherche-sources summary')?.textContent).toBe('Ce que contient la recherche')
    expect(main.querySelectorAll('.recherche-sources .source').length).toBeGreaterThan(3)
  })

  it('saisie : résultats mis à jour ; « afficher plus » donne le focus au premier ajouté ; aucun résultat dit en clair', async () => {
    await ecran('#/recherche')
    const champ = main.querySelector('#recherche-q') as HTMLInputElement
    champ.value = 'saint'
    champ.dispatchEvent(new Event('input', { bubbles: true }))
    await attendreQue(() => /pour « saint »/.test(statut()))
    const bouton = main.querySelector<HTMLButtonElement>('.recherche-plus')!
    expect(bouton.textContent).toMatch(/^Afficher plus de résultats \(\d+ autres?\)$/)
    const ul = bouton.previousElementSibling as HTMLElement
    const avant = ul.querySelectorAll('a').length
    bouton.click()
    expect(ul.querySelectorAll('a').length).toBeGreaterThan(avant)
    expect(document.activeElement).toBe(ul.querySelectorAll('a')[avant])
    champ.value = 'zzqxw'
    champ.dispatchEvent(new Event('input', { bubbles: true }))
    await attendreQue(() => /Aucun résultat/.test(statut()))
    expect(main.querySelector('#recherche-resultats')?.textContent).toContain('Vérifie l’orthographe')
  })

  it('index absent : la page le dit, sans erreur', async () => {
    servi = null
    await ecran('#/recherche?q=lyon')
    await attendreQue(() => /pas disponible/.test(statut()))
    expect(main.querySelector('#recherche-resultats .absent')).not.toBeNull()
    expect(main.querySelector('.erreur')).toBeNull()
  })

  it('lexique neutre : aucun terme évaluatif dans la page, le champ de l’en-tête et les familles de l’index', async () => {
    const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[] }[] }
    const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
    await ecran('#/recherche?q=budget')
    await attendreQue(() => /résultat/.test(statut()))
    // Texte propre à la page (les résultats et les sources reprennent des libellés officiels, contrôlés à leur source).
    const page = main.cloneNode(true) as HTMLElement
    page.querySelectorAll('#recherche-resultats, #recherche-zone-sources').forEach((x) => x.remove())
    const textes = [
      page.textContent ?? '',
      document.getElementById('recherche-entete')?.textContent ?? '',
      (document.getElementById('recherche-champ') as HTMLInputElement).placeholder,
      indexFixtures.familles.map((f) => `${f.nom} ${f.groupe}`).join(' '),
    ]
    for (const t of textes) for (const r of LEXIQUE.regles) expect(t).not.toMatch(borne(r.termes.join('|')))
  })
})

// --- Recherche globale : organisations, parlementaires, glossaire, ordre, clavier, confidentialité ---------------------

/** Petit jeu d'organisations au format publié (entites/index.json, entites/recherche/, morceaux de contexte). */
const ORG = {
  config: {
    famille: 0,
    prefixes: { as: 'entites/recherche/as.json', cr: 'entites/recherche/cr.json', ce: 'entites/recherche/ce.json' },
    tailles: { as: 3, cr: 1, ce: 1 },
    frequents: ['commune'],
    canaux: ['Crédits de l’État aux associations', 'Subventions par convention'],
    contexte: '_recherche/org/',
    morceaux: ['77', '78'],
    total: 3,
  },
  fichiers: {
    'entites/recherche/as.json': {
      entrees: [
        ['775000001', 'ASSOCIATION DES AMIS DU LIVRE', 2, '44'],
        ['775000002', 'ASSOCIATION DES AMIES DU LIVRE', 3, '69'],
        ['785000003', 'ASSOCIATION SPORTIVE DE NANTES', 2, '44'],
      ],
    },
    'entites/recherche/cr.json': { entrees: [['785000004', 'CROIX ROUGE FRANCAISE', 5, '75']] },
    '_recherche/org/77.json': {
      entrees: {
        '775000001': ['ASSOCIATION DES AMIS DU LIVRE', 2, '44', 2023, 1500, 0],
        '775000002': ['ASSOCIATION DES AMIES DU LIVRE', 3, '69', 2024, 9_000_000, 1],
      },
    },
    '_recherche/org/78.json': { entrees: { '785000004': ['CROIX ROUGE FRANCAISE', 5, '75', null, null, null] } },
  } as Record<string, unknown>,
}
const moteurOrg = () => {
  const brut: IndexBrut = {
    format: indexFixtures.format,
    familles: [{ cle: 'organisation', nom: 'Organisation', groupe: 'Entreprises, associations et autres organisations', modele: '#/beneficiaires/organisation?siren=' }],
    entrees: [],
    departements: {},
    communes: { famille: -1, par_departement: {} },
    organisations: ORG.config,
  }
  for (const [k, v] of Object.entries(ORG.fichiers)) servisEnPlus.set(k, v)
  return construireMoteur(brut)
}

describe('recherche globale : organisations (fichiers publiés par préfixe, chargés à la demande)', () => {
  it('nom, faute de frappe, SIREN et SIRET exacts ; ligne de contexte avec le dernier montant publié', async () => {
    const m = moteurOrg()
    requetes.length = 0
    const r = await chercherOrganisations(m, 'croix rouge', 5)
    expect(r.map((x) => x.e.nom)).toEqual(['CROIX ROUGE FRANCAISE'])
    expect(adresse(m, r[0].e)).toBe('#/beneficiaires/organisation?siren=785000004')
    // Seuls les fichiers du mot le plus rare et le morceau de contexte du résultat sont lus.
    expect(requetes.filter((u) => u.startsWith('data/entites/'))).toEqual(['data/entites/recherche/cr.json'])
    expect((await chercherOrganisations(m, 'assocation livre', 5)).map((x) => x.e.nom)).toContain('ASSOCIATION DES AMIS DU LIVRE')
    const s = await chercherOrganisations(m, '775 000 001', 0)
    expect(s.map((x) => x.e.nom)).toEqual(['ASSOCIATION DES AMIS DU LIVRE'])
    expect(s[0].e.precision.replace(/[\u202f\u00a0]/g, ' ')).toBe('SIREN 775 000 001 · 2 sources du site · département 44 · dernier montant publié : 1 500 € en 2023 (Crédits de l’État aux associations)')
    expect((await chercherOrganisations(m, '77500000100017', 0))[0]?.e.cible).toBe('775000001')
    expect(await chercherOrganisations(m, '999999999', 0)).toEqual([])
    expect(sirenDe('775 000 001')).toBe('775000001')
    expect(sirenDe('12345')).toBeNull()
    // Sans montant publié lisible : pas de montant dans la ligne, jamais 0.
    const croix = (await chercherOrganisations(m, 'croix rouge', 5))[0]
    expect(croix.e.precision).toBe('SIREN 785 000 004 · 5 sources du site · département 75')
    expect(contexteOrg(ORG.config, '775000002', 3, '69', ['x', 3, '69', 2024, 9_000_000, 1]).replace(/[\u202f\u00a0]/g, ' ')).toContain('9 000 000 € en 2024 (Subventions par convention)')
  })

  it('ordre : texte seulement, jamais le montant (à égalité de texte : nom le plus court, puis alphabétique)', async () => {
    const m = moteurOrg()
    const r = await chercherOrganisations(m, 'association livre', 5)
    // AMIES (9 M€) et AMIS (1 500 €) : même note du texte ; AMIS, plus court, d'abord.
    expect(r.map((x) => x.e.nom)).toEqual(['ASSOCIATION DES AMIS DU LIVRE', 'ASSOCIATION DES AMIES DU LIVRE'])
    // Même résultat en inversant les montants publiés.
    const f = ORG.fichiers['_recherche/org/77.json'] as { entrees: Record<string, unknown[]> }
    const avant = JSON.parse(JSON.stringify(f))
    ;[f.entrees['775000001'][4], f.entrees['775000002'][4]] = [f.entrees['775000002'][4], f.entrees['775000001'][4]]
    const r2 = await chercherOrganisations(moteurOrg(), 'association livre', 5)
    ORG.fichiers['_recherche/org/77.json'] = avant
    expect(r2.map((x) => x.e.nom)).toEqual(r.map((x) => x.e.nom))
  })

  it('chercherTout : organisations et index dans un même classement, groupés par famille', async () => {
    const m = moteurOrg()
    const r = await chercherTout(m, 'croix rouge')
    expect(r.resultats[0].e.nom).toBe('CROIX ROUGE FRANCAISE')
    expect(precision(m, r.resultats[0].e)).toMatch(/^Organisation · SIREN 785 000 004/)
  })

  it('montantRecent : année la plus récente avec un seul montant publié, aucun calcul, jamais additionné entre sources', () => {
    const canaux = ['a', 'b']
    const fiche = {
      recoit: [
        { canal: 'a', series: [{ valeurs: [[2022, 10], [2024, 5]] }] },
        { canal: 'b', series: [{ valeurs: [[2024, 1_000_000]] }] },
      ],
    }
    // 2024 dans les deux sources : la première dans l'ordre de la fiche, pas la plus grosse, et pas la somme.
    expect(script.montantRecent(fiche, canaux)).toEqual([2024, 5, 0])
    // Deux lignes la même année (même avec une somme publiée) : année sautée, le site n'additionne rien.
    expect(script.montantRecent({ recoit: [{ canal: 'a', series: [{ valeurs: [[2024, 1]] }, { valeurs: [[2024, 2]] }, { valeurs: [[2023, 7]] }], sommes_par_annee: [[2024, 3, 2]] }] }, canaux)).toEqual([2023, 7, 0])
    expect(script.montantRecent({ recoit: [{ canal: 'b', series: [{ valeurs: [[2024, 1]] }, { valeurs: [[2024, 2]] }] }] }, canaux)).toBeNull()
    // Montant non publié (null) : jamais 0.
    expect(script.montantRecent({ recoit: [{ canal: 'a', series: [{ valeurs: [[2024, null]] }] }] }, canaux)).toBeNull()
  })
})

describe('recherche globale : index par type, parlementaires, glossaire', () => {
  it('découpé par type : noyau et morceaux réassemblés donnent le même moteur', () => {
    const { noyau, morceaux } = script.decouperIndex(indexFixtures)
    expect(Object.keys(noyau.morceaux)).toContain('communes')
    expect(noyau.entrees.length).toBeLessThan(indexFixtures.entrees.length)
    const m = construireMoteur(assembler(noyau, Object.values(morceaux)))
    expect(m.entrees.length).toBe(moteur.entrees.length)
    expect(chercher(m, 'villeurbanne').resultats[0].e.nom).toBe('Villeurbanne')
    // Un morceau manquant : son type manque, sans erreur.
    expect(construireMoteur(assembler(noyau, [null])).entrees.length).toBe(noyau.entrees.length)
  })

  it('le moteur chargé par le site lit le noyau puis ses morceaux par type', async () => {
    const { noyau, morceaux } = script.decouperIndex(indexFixtures)
    servi = noyau
    for (const [t, x] of Object.entries(morceaux)) servisEnPlus.set(noyau.morceaux[t], x)
    requetes.length = 0
    oublierMoteur()
    const { chargerMoteur } = await import('../src/composants/recherche')
    const m = (await chargerMoteur())!
    expect(chercher(m, 'lyon').resultats[0].e.nom).toBe('Lyon')
    expect(requetes).toContain('data/_recherche/communes.json')
  })

  it('glossaire : chaque terme, avec son sigle et sa forme développée, mène à sa définition', () => {
    const g = moteur.familles.findIndex((f) => f.cle === 'glossaire')
    expect(moteur.comptes[g]).toBe(GLOSSAIRE.termes.length)
    const t = GLOSSAIRE.termes.find((x) => x.id === 'aah')!
    const r = chercher(moteur, t.forme!).resultats.find((x) => x.e.f === g)!
    expect(r.e.nom).toBe(t.terme)
    expect(adresse(moteur, r.e)).toBe('#/methode/glossaire?terme=aah')
  })

  it('parlementaires : député par sa circonscription, auteur d’amendement par la page de ses amendements, groupe tel que publié', () => {
    const lire = (c: string) =>
      ({
        'qui_a_vote/index.json': { source: 'AN', millesime: '17e', impots: [{ id: 'csg', libelle: 'CSG', fichier: 'impot_csg.json' }], departements: [{ code: '44', nom: 'Loire-Atlantique', fichier: 'departements/44.json', circonscriptions: [1] }] },
        'qui_a_vote/departements/44.json': { circonscriptions: [{ numero: 1, deputes: [{ depute: 'PA1', nom: 'Camille Exemple', fin: null, votes: [[3, 'pour', 0, 'Groupe A', null], [9, 'contre', 0, 'Groupe B', null]] }, { depute: 'PA2', nom: null, votes: [] }] }] },
        'qui_a_vote/impot_csg.json': { amendements_adoptes: [{ chambre: 'Sénat', date: '2025-01-02', auteur: { type: 'sénateur', nom: 'Dominique Essai', groupe: 'groupe Union' } }] },
        'decisions/index.json': { fichiers: ['decisions/programme_141.json'] },
        'decisions/programme_141.json': {
          programme: '141',
          annees: {
            2025: {
              amendements_adoptes: [
                { chambre: 'AN', date: '2025-11-01', auteur: { type: 'député', nom: 'Camille Exemple', groupe: 'Groupe B' } },
                { chambre: 'AN', date: '2025-11-02', auteur: { type: 'gouvernement', nom: 'Gouvernement', groupe: null } },
              ],
            },
          },
        },
      })[c] ?? null
    const existe = new Set(['/decisions/qui-a-vote', '/decisions/votes'])
    const p = script.parlementaires({ lire, qav: lire('qui_a_vote/index.json'), existe })
    expect(p.map((x: { nom: string }) => x.nom)).toEqual(['Camille Exemple', 'Dominique Essai'])
    expect(p[0].cible).toBe('#/decisions/qui-a-vote?dep=44&circo=1')
    expect(p[0].precision).toBe('Député · Loire-Atlantique (44), 1re circonscription · groupe B (dernier scrutin retenu) · 2 votes nominatifs · 1 amendement adopté')
    expect(p[1].cible).toBe('#/decisions/qui-a-vote?impot=csg')
    expect(p[1].precision).toBe('Sénat · groupe Union (dernier amendement) · 1 amendement adopté')
  })

  it('règle d’ordre identique dans l’index et à l’écran ; la taille d’une commune ne compte pas', () => {
    expect(indexFixtures.regle_ordre).toBe(REGLE_ORDRE)
    // Deux noms identiques : départagés par le code, jamais par la population.
    const brut: IndexBrut = { ...indexFixtures, entrees: [], communes: { famille: indexFixtures.communes.famille, par_departement: { '69': '001nSaint-Essai|002aSaint-Essai' } } }
    const m = construireMoteur(brut)
    expect(chercher(m, 'saint essai').resultats.map((r) => r.e.cible)).toEqual(['69001', '69002'])
    const inverse = construireMoteur({ ...brut, communes: { ...brut.communes, par_departement: { '69': '001aSaint-Essai|002nSaint-Essai' } } })
    expect(chercher(inverse, 'saint essai').resultats.map((r) => r.e.cible)).toEqual(['69001', '69002'])
  })
})

describe('recherche globale : clavier et confidentialité', () => {
  const champ = () => document.getElementById('recherche-champ') as HTMLInputElement

  it('raccourci « / » : focus dans le champ de l’en-tête, sauf pendant une saisie ailleurs', () => {
    brancherEntete()
    expect(champ().getAttribute('aria-keyshortcuts')).toBe('/')
    ;(document.activeElement as HTMLElement | null)?.blur?.()
    const ev = new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true })
    document.body.dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(champ())
    const autre = document.createElement('input')
    document.body.append(autre)
    autre.focus()
    const ev2 = new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true })
    autre.dispatchEvent(ev2)
    expect(ev2.defaultPrevented).toBe(false)
    expect(document.activeElement).toBe(autre)
    autre.remove()
  })

  it('règle d’ordre écrite sous les suggestions ; rien de la saisie n’est gardé (ni stockage, ni cookie) ni envoyé ailleurs', async () => {
    brancherEntete()
    const ecrits: string[] = []
    const espion = vi.spyOn(Storage.prototype, 'setItem').mockImplementation((k: string) => {
      ecrits.push(k)
    })
    const cookie = document.cookie
    requetes.length = 0
    champ().value = 'villeurbanne'
    champ().dispatchEvent(new Event('input', { bubbles: true }))
    const liste = document.getElementById('recherche-suggestions')!
    await attendreQue(() => !liste.hidden && liste.textContent!.includes('« villeurbanne »'))
    const regle = document.getElementById('recherche-regle-entete')!
    expect(regle.hidden).toBe(false)
    expect(regle.textContent).toBe(REGLE_ORDRE)
    expect(ecrits).toEqual([])
    expect(document.cookie).toBe(cookie)
    for (const u of requetes) expect(u).toMatch(/^data\//)
    espion.mockRestore()
    champ().dispatchEvent(new FocusEvent('blur'))
    expect(regle.hidden).toBe(true)
  })
})

describe.skipIf(!existsSync(join(SITE_DATA, 'entites', 'index.json')))('recherche globale sur les données publiées (site/data)', () => {
  // Contexte des organisations construit comme au build, puis servi comme les fichiers du site.
  let reel: { index: IndexBrut; bilan: Record<string, number> }
  let mo: { morceaux: Record<string, Record<string, [string, ...unknown[]]>> }
  const L = lecteur(SITE_DATA)
  beforeAll(() => {
    reel = construire(SITE_DATA)
    mo = script.morceauxOrganisations(L)
    ;(reel.index.organisations as { morceaux?: string[] }).morceaux = Object.keys(mo.morceaux)
  }, 120000)
  const servirReel = () => {
    racineEnPlus = SITE_DATA
    for (const [k, v] of Object.entries(mo.morceaux)) servisEnPlus.set(`_recherche/org/${k}.json`, { entrees: v })
  }

  it('règle de nommage : chaque nom indexé de personne ou d’organisation existe dans les données publiées', () => {
    // Organisations : nom identique à celui des fichiers de recherche publiés, pour le même SIREN.
    const publies = new Map<string, string>()
    const idx = L.lire('entites/index.json')
    for (const f of new Set(Object.values(idx.fichiers.recherche) as string[])) for (const e of L.lire(f)?.entrees ?? []) publies.set(e[0], e[1])
    let n = 0
    for (const m of Object.values(mo.morceaux))
      for (const [siren, c] of Object.entries(m)) {
        expect(publies.get(siren), siren).toBe(c[0])
        n++
      }
    expect(n).toBe(publies.size)
    // Parlementaires : nommés par un vote nominatif publié ou comme auteur d'un amendement adopté publié.
    const noms = new Set<string>()
    const qav = L.lire('qui_a_vote/index.json')
    for (const d of qav.departements) for (const c of L.lire(`qui_a_vote/${d.fichier}`).circonscriptions) for (const x of c.deputes) if (x.nom) noms.add(x.nom)
    for (const i of qav.impots) for (const a of L.lire(`qui_a_vote/${i.fichier}`).amendements_adoptes ?? []) if (a.auteur?.nom) noms.add(a.auteur.nom)
    for (const f of L.lire('decisions/index.json').fichiers) for (const an of Object.values(L.lire(f).annees ?? {}) as { amendements_adoptes?: { auteur: { nom: string } }[] }[]) for (const a of an.amendements_adoptes ?? []) if (a.auteur?.nom) noms.add(a.auteur.nom)
    const fp = reel.index.familles.findIndex((f) => f.cle === 'parlementaire')
    const indexes = reel.index.entrees.filter((e) => e[0] === fp)
    expect(indexes.length).toBeGreaterThan(577)
    for (const e of indexes) expect(noms.has(e[1]), e[1]).toBe(true)
    // Aucune autre famille de personnes ; aucune organisation dans le noyau (elles viennent des fichiers publiés).
    expect(reel.index.familles.map((f) => f.cle).filter((c) => /candidat|benefic|elu|personne|dirigeant/.test(c))).toEqual([])
    expect(reel.index.entrees.some((e) => reel.index.familles[e[0]].cle === 'organisation')).toBe(false)
  })

  it('temps de réponse mesuré : index complet et organisations, sous 300 ms chacun (hors premier chargement)', async () => {
    servirReel()
    const { noyau, morceaux } = script.decouperIndex(reel.index)
    const m = construireMoteur(assembler(noyau, Object.values(morceaux)))
    const mesures: Record<string, number> = {}
    for (const [q, attendu] of [
      ['cnrs', 'CENTRE NATIONAL DE LA RECHERCHE SCIENTIFIQUE (CNRS)'],
      ['180089013', 'CENTRE NATIONAL DE LA RECHERCHE SCIENTIFIQUE (CNRS)'],
      ['croix rouge francaise', 'CROIX ROUGE FRANCAISE (CRF)'],
      ['croix rouje', 'CROIX ROUGE FRANCAISE (CRF)'],
      ['nantes', 'Nantes'],
      ['tva', null],
      ['programme 141', 'Enseignement scolaire public du second degré'],
    ] as [string, string | null][]) {
      await chercherTout(m, q, 10) // premier chargement des fichiers
      const t = performance.now()
      const r = await chercherTout(m, q, 10)
      mesures[q] = Math.round(performance.now() - t)
      expect(mesures[q], q).toBeLessThan(300)
      if (attendu) expect(r.resultats.map((x) => x.e.nom).slice(0, 3), q).toContain(attendu)
    }
    const depute = reel.index.entrees.find((e) => reel.index.familles[e[0]].cle === 'parlementaire' && String(e[2]).includes('circo='))!
    expect((await chercherTout(m, depute[1])).resultats[0].e.nom).toBe(depute[1])
    console.log(`Temps de réponse (ms, après chargement) : ${JSON.stringify(mesures)}`)
  }, 120000)
})

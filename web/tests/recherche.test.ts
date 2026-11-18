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
  brancherEntete,
  chercher,
  construireMoteur,
  distance,
  type IndexBrut,
  type Moteur,
  normaliser,
  oublierMoteur,
  precision,
  selection,
} from '../src/composants/recherche'
import { TOUS_DEPARTEMENTS } from '../src/departements'
import { viderCache } from '../src/donnees'
import { afficher, lireFragment, REDIRECTIONS } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { libelle } from '../src/util'
import { attendreQue, monterPage, requetes } from './aide-dom'

const RACINE = process.cwd()
const FIXTURES = join(RACINE, 'tests', 'fixtures', 'data')
const SITE_DATA = join(RACINE, '..', 'site', 'data')
const OUTILS = { aUnePage, libelle, departements: TOUS_DEPARTEMENTS }

type Construire = (o: object) => { index: IndexBrut; bilan: Record<string, number> & { entites_sans_page: string[] } }
let construireIndex: Construire
let TAILLE_VISEE: number

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
const geo69 = GEO69

beforeAll(async () => {
  const mod = await import(/* @vite-ignore */ pathToFileURL(join(RACINE, 'scripts', 'index-recherche.mjs')).href)
  construireIndex = mod.construireIndex
  TAILLE_VISEE = mod.TAILLE_VISEE
  indexFixtures = construire().index
  moteur = construireMoteur(indexFixtures)
  monterPage()
  // L'index de recherche est servi comme les autres fichiers de données (data/_recherche.json), ou absent (404).
  const base = globalThis.fetch
  vi.stubGlobal('fetch', async (url: string) => {
    if (String(url) !== 'data/_recherche.json') return base(url)
    requetes.push(String(url))
    return servi ? new Response(JSON.stringify(servi), { status: 200, headers: { 'content-type': 'application/json' } }) : new Response('introuvable', { status: 404 })
  })
})
beforeEach(() => {
  servi = indexFixtures
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
    for (const q of ['LYON', 'Lyôn', 'lyonn', 'lyno']) expect(premier(q)?.nom, q).toBe('Lyon')
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

  it.skipIf(!existsSync(join(SITE_DATA, 'local', 'geo')))('index réel (site/data) : moins de 1 Mo, toutes les communes, recherche rapide', () => {
    const { index, bilan } = construire(SITE_DATA)
    const texte = JSON.stringify(index)
    expect(Buffer.byteLength(texte)).toBeLessThan(TAILLE_VISEE)
    expect(gzipSync(texte).length).toBeLessThan(400_000)
    expect(bilan.commune).toBeGreaterThan(34000)
    expect(bilan.departement).toBe(101)
    const m = construireMoteur(JSON.parse(texte))
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
    expect(main.textContent).toContain('ni dans les montants ni parmi les bénéficiaires nommés')
    expect(Array.from(main.querySelectorAll('#recherche-consigne a')).map((a) => a.getAttribute('href'))).toContain('#/recherche?q=Lyon')
    expect(requetes).not.toContain('data/_recherche.json')
    expect(document.title).toBe('Rechercher une commune, un programme du budget ou une page du site · Où vont mes impôts')
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

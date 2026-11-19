// @vitest-environment happy-dom
// « Ma commune » (/local/ma-commune) : recherche par code postal ou nom (sans réseau externe) et page de synthèse,
// sur des extraits réels de site/data (tests/fixtures/ma_commune/data : ma_commune/index.json complet, cp et noms
// réduits ; local/geo, local/fonctions, local/budgets réduits à Nantes 44109 et Grandchamp-des-Fontaines 44066 et à
// leurs intercommunalités ; subventions publiées de Nantes 2021 et Nantes Métropole 2025 réduites à 30 lignes ;
// opérations des fonds européens des Pays de la Loire situées dans ces deux communes ; typologies ; projets repris de
// tests/fixtures/projets). Valeurs non modifiées.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { viderCache } from '../src/donnees'
import { session } from '../src/etat'
import { chercher, compacte, fichiersNoms, normaliser, personneMorale, TITRE } from '../src/ecrans/ma_commune'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { attendreQue, monterPage } from './aide-dom'

const RACINE = process.cwd()
const MES_FIXTURES = join(RACINE, 'tests', 'fixtures', 'ma_commune')
const requetes: string[] = []
let main: HTMLElement

function servir() {
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const f = join(MES_FIXTURES, u.split('?')[0])
    if (!existsSync(f)) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}
const ecran = async (fragment: string) => {
  viderCache()
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
}
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''
const pret = () => attendreQue(() => !main.querySelector('[aria-busy="true"]'))

const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function verifierLexique(t: string, ou: string) {
  let x = t.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
}

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu') as HTMLElement
})
beforeEach(() => {
  requetes.length = 0
  viderCache()
})
afterAll(() => {
  vi.unstubAllGlobals()
})

describe('normalisation (même règle que pipeline/ma_commune.py)', () => {
  it('accents, traits d’union, apostrophes, st et ste', () => {
    expect(normaliser('Saint-Étienne-du-Rouvray')).toBe('saint etienne du rouvray')
    expect(normaliser('ST ETIENNE DU ROUVRAY')).toBe('saint etienne du rouvray')
    expect(normaliser('Ste-Foy-lès-Lyon')).toBe('sainte foy les lyon')
    expect(normaliser('L’Haÿ-les-Roses')).toBe('l hay les roses')
    expect(normaliser('Œuilly')).toBe('oeuilly')
    expect(compacte('l abergement')).toBe('labergement')
  })
  it('fichiers de noms : préfixe de la saisie, ou au plus quatre fichiers qui la prolongent', () => {
    const cles = ['g', 'n', 'sa', 'sai', 'sainta', 'saintb', 'saintc', 'saintd', 'sainth']
    expect(fichiersNoms('Grandchamp', cles)).toEqual(['g'])
    expect(fichiersNoms('Saint-Herblain', cles)).toEqual(['sa', 'sai', 'sainth'])
    expect(fichiersNoms('sain', cles)).toEqual(['sa', 'sai'])
    expect(fichiersNoms('n', cles)).toEqual([])
  })
})

describe('recherche', () => {
  it('code postal partagé : toutes les communes, et le message de choix', async () => {
    const r = await chercher('44119')
    expect(r.propositions.map((p) => p.insee)).toEqual(['44066', '44209'])
    expect(r.message).toContain('2 communes')
    expect(requetes.every((u) => u.startsWith('data/ma_commune/'))).toBe(true)
    expect(requetes).toContain('data/ma_commune/cp/44.json')
  })
  it('arrondissement de Paris : la commune de Paris, l’arrondissement en précision', async () => {
    const r = await chercher('75011')
    expect(r.propositions).toHaveLength(1)
    expect(r.propositions[0]).toMatchObject({ insee: '75056', nom: 'Paris', precision: '11e arrondissement' })
  })
  it('commune nouvelle : l’ancienne commune trouvée par son nom, rattachée à la commune actuelle', async () => {
    const r = await chercher('Beaufort en Vallée')
    const p = r.propositions.find((x) => x.type === 'localite')
    expect(p).toMatchObject({ insee: '49021', precision: 'Beaufort-en-Anjou' })
  })
  it('nom : homonymes dans l’ordre neutre (nom identique, puis début, puis alphabétique) ; filtre par département', async () => {
    const r = await chercher('grandchamp')
    expect(r.propositions[0].nom).toBe('Grandchamp')
    expect(r.propositions.map((p) => p.nom)).toContain('Grandchamp-des-Fontaines')
    const r44 = await chercher('Grandchamp 44')
    expect(r44.propositions.map((p) => p.insee)).toEqual(['44066'])
  })
  it('hors périmètre et saisies trop courtes : un message, aucune proposition', async () => {
    expect((await chercher('98000')).message).toContain('Monaco')
    expect((await chercher('97133')).message).toContain('Saint-Barthélemy')
    expect((await chercher('g')).message).toContain('deux lettres')
    expect((await chercher('zzzz')).propositions).toEqual([])
  })
})

describe('écran', () => {
  it('sans commune : champ unique, aide, sorties ; la saisie propose des liens vers la synthèse', async () => {
    await ecran('#/local/ma-commune')
    expect(main.querySelector('h1')?.textContent).toBe(TITRE)
    const champ = main.querySelector<HTMLInputElement>('#mc-recherche-saisie')!
    expect(champ).not.toBeNull()
    expect(main.querySelector('label[for="mc-recherche-saisie"]')?.textContent).toContain('Code postal ou nom')
    champ.value = '44119'
    champ.dispatchEvent(new Event('input'))
    await attendreQue(() => main.querySelectorAll('#mc-recherche-liste a').length === 2)
    const liens = [...main.querySelectorAll<HTMLAnchorElement>('#mc-recherche-liste a')].map((a) => a.getAttribute('href'))
    expect(liens).toEqual(['#/local/ma-commune?insee=44066', '#/local/ma-commune?insee=44209'])
    expect(main.querySelector('#mc-recherche-etat')?.textContent).toContain('2 communes')
    // Un seul choix possible : le formulaire mène directement à la synthèse.
    champ.value = '75011'
    main.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => location.hash === '#/local/ma-commune?insee=75056')
  })

  it('synthèse de Nantes : quatre budgets séparés, sur 100 € par fonction, bénéficiaires, fonds européens, projets, repères', async () => {
    await ecran('#/local/ma-commune?insee=44109')
    await pret()
    expect(main.querySelector('h1')?.textContent).toBe('Nantes')
    const t = texte()
    expect(t).toContain('ne pas additionner commune, intercommunalité, département et région')
    // Budgets : commune et intercommunalité par fonction (balances DGFiP), département par nature (OFGL), région par fonction.
    const commune = main.querySelector('#mc-commune')!.textContent ?? ''
    expect(commune).toContain('Sur 100 € dépensés')
    expect(commune).toContain('Services généraux')
    expect(commune).toContain('Calculé par le site')
    expect(main.querySelector('#mc-epci-titre')!.textContent).toBe('L’intercommunalité : Nantes Métropole')
    expect(main.querySelector('#mc-epci')!.textContent).toContain('Sur 100 € dépensés')
    expect(main.querySelector('#mc-departement-titre')!.textContent).toBe('Le département : Loire-Atlantique')
    expect(main.querySelector('#mc-departement')!.textContent).toContain('Par nature de dépense')
    expect(main.querySelector('#mc-departement')!.textContent).toContain('collectivités pilotes')
    expect(main.querySelector('#mc-region')!.textContent).toContain('Sur 100 € dépensés')
    for (const id of ['mc-commune', 'mc-epci', 'mc-departement', 'mc-region', 'mc-beneficiaires', 'mc-europe', 'mc-projets', 'mc-comparer'])
      expect(main.querySelector(`#${id} .source`), `${id} : source`).not.toBeNull()
    // Bénéficiaires nommés : personnes morales seulement (catégorie juridique lue dans chaque ligne).
    const benef = main.querySelector('#mc-beneficiaires')!
    expect(benef.querySelectorAll('table')).toHaveLength(2)
    expect(benef.textContent).toContain('Ordre : montant décroissant')
    // Fonds européens : opérations situées dans la commune, ou phrase qui dit pourquoi il n'y en a pas.
    expect(main.querySelector('#mc-europe')!.textContent).toMatch(/Opérations cofinancées par l’Union situées à Nantes|Aucune opération nommée située à Nantes/)
    expect(main.querySelector('#mc-comparer')!.textContent).toContain('médiane')
    // Délibérations : Nantes ne publie pas au format national, la phrase le dit.
    expect(main.querySelector('#mc-deliberations')!.textContent).toContain('ne publie pas ses délibérations')
    expect(main.querySelector('a[href="#/local/commune?insee=44109&page=nantes"]')).not.toBeNull()
    expect(main.querySelectorAll('.surligne').length).toBeLessThanOrEqual(1)
    expect(main.textContent).not.toContain('—')
    expect(main.querySelectorAll('[style]:not([data-l]):not([data-g]):not([data-f])')).toHaveLength(0)
    verifierLexique(t, 'synthèse Nantes')
    expect(requetes.every((u) => u.startsWith('data/'))).toBe(true)
    expect(document.title).toContain('Nantes')
  })

  it('commune sans liste de subventions ni délibérations : chaque bloc dit pourquoi', async () => {
    await ecran('#/local/ma-commune?insee=44066')
    await pret()
    expect(texte()).toContain('Grandchamp-des-Fontaines : aucune liste de subventions publiée en données ouvertes')
    expect(main.querySelector('#mc-epci-titre')!.textContent).toContain('Erdre et Gesvres')
    expect(main.querySelectorAll('h2').length).toBe(new Set([...main.querySelectorAll('h2')].map((x) => x.textContent)).size)
  })

  it('commune inconnue : message et champ de recherche', async () => {
    await ecran('#/local/ma-commune?insee=44999')
    expect(texte()).toContain('Commune introuvable')
    expect(main.querySelector('#mc-recherche-saisie')).not.toBeNull()
  })

  it('le lien depuis le résultat du calcul ne porte que le code Insee, jamais le salaire', async () => {
    const src = readFileSync(join(RACINE, 'src', 'ecrans', 'paie.ts'), 'utf8')
    const ligne = src.split('\n').find((l) => l.includes('#/local/ma-commune'))!
    expect(ligne).toContain('Et dans ma commune ?')
    expect(ligne).toMatch(/insee=\$\{encodeURIComponent\(session\.profil\.residence\.commune_insee\)\}/)
    expect(ligne).not.toMatch(/net|brut|salaire|resultat/i)
    // L'écran lui-même ne lit que la commune saisie, rien d'autre de la session.
    const ecranSrc = readFileSync(join(RACINE, 'src', 'ecrans', 'ma_commune.ts'), 'utf8') + readFileSync(join(RACINE, 'src', 'ecrans', 'ma_commune_recherche.ts'), 'utf8')
    expect(ecranSrc.match(/session\.[a-z]+/g)?.every((x) => x === 'session.profil')).toBe(true)
    session.profil = { residence: { commune_insee: '44066' } } as never
    await ecran('#/local/ma-commune')
    expect(main.querySelector('a[href="#/local/ma-commune?insee=44066"]')?.textContent).toContain('commune saisie dans ton calcul')
    session.profil = null
  })

  it('personnes morales seulement', () => {
    expect(personneMorale('9220')).toBe(true)
    expect(personneMorale('7344')).toBe(true)
    expect(personneMorale('1000')).toBe(false)
    expect(personneMorale('2110')).toBe(false)
    expect(personneMorale(null)).toBe(false)
  })
})

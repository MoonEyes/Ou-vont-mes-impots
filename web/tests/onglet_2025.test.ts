// @vitest-environment happy-dom
// Onglet « Dépensé en 2025 (par politique) » de l'écran /explorer/etat : exécution 2025 (grand poste > mission > programme)
// lue dans site/data/millesimes/ (contrat 2.48), sans changer la vue par défaut (exécution 2024).
// Fixtures : tests/fixtures/onglet_2025/data/millesimes/ (copie des fichiers publiés), le reste dans tests/fixtures/data/.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { definirRacine, viderCache, VUES_ARBRE, vueArbre } from '../src/donnees'
import { blocMethode, lienDonnee, md2, PHRASE_NIVEAU_2025, VUE_2025 } from '../src/ecrans/etat'
import { md } from '../src/util'
import { monterPage } from './aide-dom'

const FIXTURES = join(process.cwd(), 'tests', 'fixtures')
const PRIVE = join(FIXTURES, 'onglet_2025')
let sansIndex = false
const requetes: string[] = []

function servir() {
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const chemin = u.split('?')[0]
    if (sansIndex && chemin === 'data/millesimes/index.json') return new Response('introuvable', { status: 404 })
    const f = [join(PRIVE, chemin), join(FIXTURES, chemin)].find((c) => existsSync(c))
    if (!f) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}

const lire = (rel: string) => JSON.parse(readFileSync(join(PRIVE, 'data', rel), 'utf8'))
const index = lire('millesimes/index.json')
const racine2025 = lire('millesimes/execution2025/racine.json')
const totaux = index.comparaison.totaux
const norm = (s: string) => s.replace(/[\s  ]+/g, ' ').trim()

let main: HTMLElement
const ecran = async (fragment: string) => {
  viderCache()
  requetes.length = 0
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => norm(main.textContent ?? '')
/** Texte écrit par l'écran, hors lignes « source » (qui reprennent les intitulés des producteurs). */
const texteEcran = () => {
  const c = main.cloneNode(true) as HTMLElement
  c.querySelectorAll('.source').forEach((s) => s.remove())
  return norm(c.textContent ?? '')
}
const ongletActif = () => main.querySelector('.choix-liens [aria-current="page"]')?.textContent

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu')!
})
beforeEach(() => {
  sansIndex = false
})

describe('vues de l’État', () => {
  it('la vue par défaut reste l’exécution 2024 ; la vue 2025 lit millesimes/execution2025', () => {
    expect(VUES_ARBRE[0].cle).toBe('execution2024')
    expect(vueArbre(null).cle).toBe('execution2024')
    const v = vueArbre(VUE_2025)
    expect(v).toMatchObject({ dossier: 'millesimes/execution2025', libelle: 'Dépensé en 2025 (par politique)', millesime: 'Exécution 2025', periode: 'dépenses réelles 2025' })
    expect(VUES_ARBRE.filter((x) => x.cle === VUE_2025)).toHaveLength(1)
    // même format que les autres arbres : pas de recopie, le fichier publié est lu tel quel
    expect(racine2025.millesime).toBe(v.millesime)
    expect(index.execution_2025.fichier).toBe(`${v.dossier}/racine.json`)
  })

  it('l’arbre 2025 s’arrête au programme', () => {
    const niveaux = new Set<string>()
    const tour = (n: any) => {
      niveaux.add(n.niveau)
      ;(n.enfants ?? []).forEach(tour)
    }
    tour(racine2025)
    expect([...niveaux].sort()).toEqual(['grand_poste', 'mission', 'programme', 'racine'])
  })
})

describe('écran /explorer/etat', () => {
  it('sans paramètre : exécution 2024, onglet 2025 proposé, aucun fichier 2025 chargé', async () => {
    await ecran('#/explorer/etat')
    expect(ongletActif()).toBe('Dépensé en 2024 (par politique)')
    const onglets = [...main.querySelectorAll('.choix-liens a')].map((a) => [a.textContent, a.getAttribute('href')])
    expect(onglets).toContainEqual(['Dépensé en 2025 (par politique)', '#/explorer/etat?m=execution2025'])
    expect(onglets).toHaveLength(3)
    expect(requetes.some((r) => r.includes('millesimes/execution2025'))).toBe(false)
    // écart de méthode, avec les seuls chiffres de 2024
    const t = texte()
    expect(t).toContain(md2(totaux.execution_2024_affichee_eur))
    expect(t).toContain(md2(totaux.execution_2024_plrg_eur))
    expect(t).not.toContain(md2(totaux.execution_2025_plrg_eur))
    expect(t).not.toContain(PHRASE_NIVEAU_2025)
  })

  it('m=execution2025 : billet, total, phrase sur le niveau du programme, aucun arbre 2024 chargé', async () => {
    await ecran('#/explorer/etat?m=execution2025')
    expect(ongletActif()).toBe('Dépensé en 2025 (par politique)')
    const t = texte()
    expect(t).toContain(`${md(racine2025.md)}, dépenses réelles 2025`)
    expect(main.querySelector('#niveau-2025')?.textContent).toBe(PHRASE_NIVEAU_2025)
    expect(PHRASE_NIVEAU_2025.split('. ')).toHaveLength(1)
    expect(requetes).toContain('data/millesimes/execution2025/racine.json')
    expect(requetes.some((r) => r.startsWith('data/arbre/') || r.startsWith('data/arbre_'))).toBe(false)
    expect(main.querySelectorAll('.billet [data-v], .billet a, .billet li').length).toBeGreaterThan(0)
    expect(main.querySelector('.source')?.textContent).toContain('Exécution 2025')
  })

  it('écart de méthode : 502,96, 510,17 et 509,67 Md€, sans trancher, avec le lien vers le détail par grand poste', async () => {
    await ecran('#/explorer/etat?m=execution2025')
    const bloc = main.querySelector('section[aria-labelledby="titre-methode"]') as HTMLElement
    expect(bloc).not.toBeNull()
    const t = norm(bloc.textContent ?? '')
    for (const x of ['502,96 Md€', '510,17 Md€', '509,67 Md€', '7,20 Md€']) expect(t).toContain(x)
    expect(t).toContain('sans que l’un corrige l’autre')
    expect(bloc.querySelector('a')!.getAttribute('href')).toBe('./data/millesimes/index.json')
    expect(index.comparaison.lignes.length).toBeGreaterThan(0)
  })

  it('tous les liens vers le détail gardent le millésime 2025', async () => {
    await ecran('#/explorer/etat?m=execution2025&poste=Education%20et%20recherche')
    const liens = [...main.querySelectorAll<HTMLAnchorElement>('a[href^="#/explorer/etat"]')]
      .map((a) => a.getAttribute('href')!)
      .filter((x) => x.startsWith('#/explorer/etat/detail') || x.includes('poste='))
    expect(liens.some((x) => x.startsWith('#/explorer/etat/detail'))).toBe(true)
    for (const x of liens) expect(new URLSearchParams(x.split('?')[1] ?? '').get('m')).toBe(VUE_2025)
    // un niveau plus bas : les missions du grand poste, en 2025
    const poste = racine2025.enfants.find((p: any) => p.id === 'Education et recherche')
    expect(texte()).toContain(`Un niveau plus bas : Éducation et recherche (${md(poste.md)})`)
    // les pages d'un programme n'existent pas pour 2025 : c'est dit
    expect(texte()).toContain('ne sont pas encore construites pour 2025')
  })

  it('sans fichier d’écart publié, la page s’affiche sans le bloc de méthode', async () => {
    sansIndex = true
    await ecran('#/explorer/etat?m=execution2025')
    expect(main.querySelector('section[aria-labelledby="titre-methode"]')).toBeNull()
    expect(main.querySelector('#niveau-2025')).not.toBeNull()
  })

  it('lexique : aucun sigle seul ni tiret long dans les textes ajoutés pour les deux méthodes et la vue 2025', async () => {
    for (const f of ['#/explorer/etat?m=execution2025', '#/explorer/etat']) {
      await ecran(f)
      const t = norm(
        [...main.querySelectorAll('#niveau-2025, section[aria-labelledby="titre-methode"], .chapeau, #programmes-2025, .choix-liens')].map((e) => e.textContent).join(' '),
      )
      expect(t).not.toMatch(/\bPLRG\b|\bPLF\b|\bLFI\b/)
      expect(t).not.toContain('—')
      expect(t).toContain('loi relative aux résultats de la gestion')
    }
  })

  it('lexique neutre partagé (docs/lexique_neutre.json)', async () => {
    const lex = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[] }[] }
    const re = new RegExp(`(?<![\\p{L}\\p{N}_])(?:${lex.regles.flatMap((r) => r.termes).join('|')})(?![\\p{L}\\p{N}_])`, 'iu')
    await ecran('#/explorer/etat?m=execution2025')
    expect(texteEcran().match(re)).toBeNull()
    expect(blocMethode('execution2024', index).match(re)).toBeNull()
  })
})

describe('détail et liens vers les données', () => {
  it('/explorer/etat/detail?m=execution2025 : missions puis programmes 2025, sans niveau action', async () => {
    const mission = racine2025.enfants[0].enfants[0]
    await ecran(`#/explorer/etat/detail?m=execution2025&id=${encodeURIComponent(mission.id)}`)
    expect(ongletActif()).toBe('Dépensé en 2025 (par politique)')
    expect(main.querySelector('h1')!.textContent).toContain(mission.nom.slice(0, 10))
    expect(texte()).toContain('Exécution 2025')
    const prog = mission.enfants[0]
    await ecran(`#/explorer/etat/detail?m=execution2025&id=${encodeURIComponent(prog.id)}`)
    expect(texte()).toContain('Ce bloc n’est pas détaillé davantage dans la source.')
  })

  it('lien vers un fichier de données : relatif en développement et au prérendu, absolu sur le site publié', () => {
    expect(lienDonnee('millesimes/index.json')).toBe('./data/millesimes/index.json')
    definirRacine('/Ou-vont-mes-impots/')
    try {
      expect(lienDonnee('millesimes/index.json')).toBe('/Ou-vont-mes-impots/data/millesimes/index.json')
    } finally {
      definirRacine('')
    }
    expect(blocMethode('lfi2025', index)).toBe('')
    expect(blocMethode(VUE_2025, null)).toBe('')
  })
})

// @vitest-environment happy-dom
// Écran « Qui a voté tes impôts » (/decisions/qui-a-vote) sur des extraits réels de site/data/qui_a_vote
// (tests/fixtures/qui_a_vote/data/qui_a_vote/ : index réduit à trois départements, impôt sur le revenu réduit à deux
// scrutins, ses votes nominatifs, liste des scrutins, Loire-Atlantique). Neutralité : ordre des groupes écrit et
// alphabétique, avertissements présents, aucun classement ni qualificatif, aucun champ personnel hors nom, groupe,
// circonscription et vote ; « Ton député » : rien n'est envoyé ni conservé.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { viderCache } from '../src/donnees'
import { NOM_ABSENT, POSITIONS, rendreNominatif, SANS_POSITION, texteEnClair, type Impot, type Index } from '../src/ecrans/qui_a_vote'
import { monterPage } from './aide-dom'

const CHEMIN = '/decisions/qui-a-vote'
const FIXTURES = join(process.cwd(), 'tests', 'fixtures')
const PRIVE = join(FIXTURES, 'qui_a_vote')
const requetes: string[] = []

function servir() {
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const chemin = u.split('?')[0]
    const f = [join(PRIVE, chemin), join(FIXTURES, chemin)].find((c) => existsSync(c))
    if (!f) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}

const lire = (rel: string) => JSON.parse(readFileSync(join(PRIVE, 'data', 'qui_a_vote', rel), 'utf8'))
const idx = lire('index.json') as Index
const ir = lire('impot_impot_revenu.json') as Impot
const votes = lire(ir.fichier_votes)
const dep44 = lire('departements/44.json')
const norm = (s: string) => s.replace(/[\s  ]+/g, ' ').trim()
const ordreFr = (a: string, b: string) => a.localeCompare(b, 'fr', { sensitivity: 'base' })

let main: HTMLElement
async function ecran(fragment: string) {
  viderCache()
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  await new Promise((r) => setTimeout(r, 40))
  return main
}
const texte = () => norm(main.textContent ?? '')
const attendre = async (cond: () => boolean) => {
  for (let i = 0; i < 100 && !cond(); i++) await new Promise((r) => setTimeout(r, 20))
  expect(cond()).toBe(true)
}

const LEXIQUE = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function lexiqueNeutre(ou: string, racine: Element = main) {
  let x = (racine.textContent ?? '').replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  // les extraits de textes officiels (articles, amendements) sont cités tels quels : hors du contrôle du lexique
  for (const d of racine.querySelectorAll('details:not(.qav-scrutin):not(.carte) > p')) x = x.split(norm(d.textContent ?? '')).join(' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
  expect(racine.textContent, ou).not.toContain('—')
}
const QUALIFICATIFS = /taxeur|bon élève|mauvais élève|palmarès|classement|meilleur|\bpire\b|score|champion|record/i
const PERSONNEL = /né le|née le|date de naissance|adresse|profession|patrimoine|HATVP|photo/i
/** Texte rédigé par le site : sans les noms, objets de scrutin, extraits officiels ni la règle qui énumère ce qui
 * n'est pas publié (elle cite « date de naissance », « adresse »…). */
function texteRedige(racine: Element = main): string {
  const c = racine.cloneNode(true) as Element
  for (const x of c.querySelectorAll('td, h4, h5, a, details:not(.qav-scrutin) > p, li > strong, li > p:first-child, ul > li')) x.remove()
  // pied de page commun (« Signaler une erreur ») : « l’adresse de cette page » n’est pas une donnée personnelle
  return norm(c.textContent ?? '').split(norm(idx.regle_personnes)).join(' ').split('l’adresse de cette page').join(' ')
}

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu') as HTMLElement
})

describe('/decisions/qui-a-vote', () => {
  it('route déclarée sous « Décisions et contrôle », voisins existants, limites de longueur', () => {
    const r = ROUTES.find((x) => x.chemin === CHEMIN)!
    expect(r.parent).toBe('/decisions')
    expect(r.voisins!.length).toBeLessThanOrEqual(3)
    for (const v of r.voisins ?? []) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    expect(r.description.length).toBeLessThanOrEqual(200)
    expect(`${r.titrePage} · Où vont mes impôts`.length).toBeLessThanOrEqual(100)
  })

  it('accueil de la page : introduction, avertissements, méthode, ordre écrit, aucune requête externe, lexique neutre', async () => {
    requetes.length = 0
    await ecran(`#${CHEMIN}`)
    expect(main.querySelector('h1')?.textContent).toBe('Qui a voté tes impôts')
    expect(texte()).toContain('La page ne dit pas si une décision était bonne ou mauvaise')
    const av = main.querySelector('[data-avertissements]')!
    expect(av.querySelectorAll('li').length).toBe(idx.avertissements.length)
    const t = norm(av.textContent ?? '')
    for (const mot of ['n\'est pas un vote sur l\'impôt entier', 'non-votant n\'est pas forcément absent', 'délégation', 'mise au point']) expect(t).toContain(mot)
    expect(texte()).toContain(idx.methode)
    expect(main.querySelectorAll('[data-regle-ordre]').length).toBeGreaterThanOrEqual(1)
    const lignes = Array.from(main.querySelectorAll('table tbody th[scope="row"]')).map((x) => x.textContent)
    expect(lignes).toEqual(idx.impots.map((i) => i.libelle))
    for (const tb of main.querySelectorAll('table')) {
      expect(tb.querySelector('caption')).not.toBeNull()
      expect(tb.querySelectorAll('th[scope]').length).toBeGreaterThan(0)
    }
    expect(texte()).toContain('Cotisations sociales')
    expect(requetes.every((u) => u.startsWith('data/'))).toBe(true)
    expect(texteRedige()).not.toMatch(QUALIFICATIFS)
    expect(texteRedige()).not.toMatch(PERSONNEL)
    lexiqueNeutre('accueil')
  })

  it('un impôt : articles avec leur preuve, scrutins avec groupes dans l’ordre alphabétique écrit, amendements nommés', async () => {
    await ecran(`#${CHEMIN}?impot=impot_revenu`)
    await attendre(() => !!main.querySelector('#qav-titre-impot'))
    expect(main.querySelector('#qav-titre-impot')?.textContent).toBe(ir.impot.libelle)
    expect((main.querySelector('#qav-impot') as HTMLSelectElement).value).toBe('impot_revenu')
    expect(texte()).not.toMatch(/\bPLF(SS|G)? \d{4}/) // jamais de sigle seul
    expect(texte()).toContain(texteEnClair(ir.articles[0].texte))
    expect(texte()).toContain('Lien avec l’impôt')
    const details = main.querySelectorAll('details.qav-scrutin')
    expect(details.length).toBe(ir.scrutins.length)
    for (const [i, d] of Array.from(details).entries()) {
      const groupes = Array.from(d.querySelectorAll('tbody th[scope="row"]')).map((x) => x.textContent ?? '')
      expect(groupes).toEqual(ir.scrutins[i].groupes.map((g) => g.groupe))
      expect(groupes).toEqual([...groupes].sort(ordreFr))
      expect(d.querySelector('[data-regle-ordre]')?.textContent).toContain('alphabétique')
    }
    for (const a of ir.amendements_adoptes) if (a.auteur.nom) expect(texte()).toContain(a.auteur.nom)
    expect(main.querySelector('.qav-scrutin [style*="color"], .qav-scrutin .positif, .qav-scrutin .negatif')).toBeNull()
    expect(texteRedige()).not.toMatch(QUALIFICATIFS)
    expect(texteRedige()).not.toMatch(PERSONNEL)
    lexiqueNeutre('impôt')
  })

  it('vote nominatif chargé à la demande : noms par groupe et par position, délégations et mises au point', async () => {
    await ecran(`#${CHEMIN}?impot=impot_revenu`)
    await attendre(() => !!main.querySelector('button[data-nominatif]'))
    requetes.length = 0
    const s = ir.scrutins.find((x) => votes.votes[String(x.numero)].mises_au_point.length) ?? ir.scrutins[0]
    const b = main.querySelector<HTMLButtonElement>(`button[data-nominatif="${s.numero}"]`)!
    b.click()
    const zone = b.nextElementSibling as HTMLElement
    await attendre(() => (zone.textContent ?? '').length > 0)
    expect(requetes).toEqual([`data/qui_a_vote/${ir.fichier_votes}`])
    const v = votes.votes[String(s.numero)]
    expect(Array.from(zone.querySelectorAll('h5')).map((x) => x.textContent)).toEqual(v.groupes.map((g: { groupe: string }) => g.groupe))
    const premier = v.groupes.find((g: { pour: string[] }) => g.pour.length)
    if (premier) expect(zone.textContent).toContain(votes.deputes[premier.pour[0]] ?? NOM_ABSENT)
    if (v.mises_au_point.length) expect(zone.textContent).toContain('indique avoir voulu voter')
    else expect(zone.textContent).toContain('Aucune mise au point publiée')
    expect(zone.textContent).toContain('n’a pas de position enregistrée')
    expect(norm(zone.textContent ?? '')).not.toMatch(PERSONNEL)
  })

  it('rendreNominatif : nom absent de la source, délégation, positions en toutes lettres', () => {
    const html = rendreNominatif(
      { deputes: { PA1: 'Alice Martin', PA2: null }, votes: { '9': { groupes: [{ groupe: 'Groupe A', pour: ['PA1'], contre: ['PA2'], abstention: [], non_votant: [], par_delegation: ['PA1'] }], mises_au_point: [{ depute: 'PA1', position_souhaitee: 'contre' }] } } },
      9,
    )
    const d = document.createElement('div')
    d.innerHTML = html
    expect(d.textContent).toContain('Alice Martin (par délégation)')
    expect(d.textContent).toContain(NOM_ABSENT)
    expect(d.textContent).not.toContain('non nommé ici')
    expect(d.textContent).toContain('Alice Martin indique avoir voulu voter contre')
    expect(Object.values(POSITIONS)).toEqual(['pour', 'contre', 'abstention', 'non-votant'])
  })

  it('« Ton député » : département puis circonscription, données lues sur place, rien d’envoyé ni de conservé', async () => {
    await ecran(`#${CHEMIN}`)
    const avant = location.hash
    requetes.length = 0
    const dep = main.querySelector<HTMLSelectElement>('#qav-dep')!
    const circo = main.querySelector<HTMLSelectElement>('#qav-circo')!
    expect(circo.disabled).toBe(true)
    dep.value = '44'
    dep.dispatchEvent(new Event('change'))
    await attendre(() => !circo.disabled && circo.options.length === 11)
    circo.value = '1'
    circo.dispatchEvent(new Event('change'))
    const zone = main.querySelector<HTMLElement>('#qav-depute')!
    await attendre(() => !!zone.querySelector('h4'))
    const c = dep44.circonscriptions[0]
    expect(Array.from(zone.querySelectorAll('h4')).map((x) => x.textContent)).toEqual(c.deputes.map((x: { nom: string | null }) => x.nom ?? expect.any(String)))
    const positions = Array.from(zone.querySelectorAll('tbody td:nth-child(4)')).map((x) => x.textContent ?? '')
    expect(positions.length).toBeGreaterThan(0)
    for (const p of positions) expect(p).toMatch(new RegExp(`^(pour|contre|abstention|non-votant|${SANS_POSITION})`))
    expect(zone.querySelector('table caption')).not.toBeNull()
    expect(zone.querySelector('[data-regle-ordre]')).not.toBeNull()
    expect(new Set(requetes)).toEqual(new Set(['data/qui_a_vote/departements/44.json', 'data/qui_a_vote/scrutins.json']))
    expect(requetes.every((u) => !u.includes('?'))).toBe(true)
    expect(location.hash).toBe(avant)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(texteRedige(zone)).not.toMatch(PERSONNEL)
    expect(texteRedige(zone)).not.toMatch(QUALIFICATIFS)
    lexiqueNeutre('ton député', zone)
  })
})

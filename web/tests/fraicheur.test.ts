// @vitest-environment happy-dom
// Écran « Fraîcheur des données » (/methode/fraicheur) sur la fixture tests/fixtures/data/fraicheur/index.json,
// extrait réel de site/data/fraicheur/index.json (pipeline/fraicheur.py).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { dateLongue, filtrer, type Fraicheur, MOT_STATUT, pageDuSite, rendre, STATUTS_ORDRE, trier } from '../src/ecrans/fraicheur'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { attendreQue, monterPage, requetes } from './aide-dom'

const FX = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'data', 'fraicheur', 'index.json'), 'utf8')) as Fraicheur
const nf = (x: number) => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(x).replace(/\s+/g, ' ')

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''
const saisir = (sel: string, valeur: string) => {
  const el = main.querySelector<HTMLInputElement | HTMLSelectElement>(sel)!
  el.value = valeur
  el.dispatchEvent(new Event('input', { bubbles: true }))
}
const lignes = () => Array.from(main.querySelectorAll('#fr-liste li[data-id]'))

// Lexique neutre partagé (docs/lexique_neutre.json, charte docs/NEUTRALITE.md), mêmes bornes que ecrans.test.ts.
const LEXIQUE = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as {
  regles: { termes: string[]; raison: string }[]
  niche_definie: string
  exceptions: string[]
}
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function verifierLexique(t: string, ou: string) {
  let x = t.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
  expect(x.replace(new RegExp(LEXIQUE.niche_definie, 'giu'), ' '), `${ou} : « niche » sans définition`).not.toMatch(borne('niches?'))
}

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('fraîcheur des données', () => {
  it('route sous « Méthode et sources » : titre, fil d’Ariane, sorties, description courte et unique', async () => {
    const r = ROUTES.find((x) => x.chemin === '/methode/fraicheur')!
    expect(r.parent).toBe('/methode')
    expect(r.description.length).toBeGreaterThanOrEqual(70)
    expect(r.description.length).toBeLessThanOrEqual(200)
    for (const v of r.voisins ?? []) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    await ecran('#/methode/fraicheur')
    expect(main.querySelector('h1')?.textContent?.trim()).toBe('Fraîcheur des données')
    expect(Array.from(main.querySelectorAll('.fil-ariane a')).map((a) => a.textContent)).toEqual(['Accueil', 'Méthode', 'Fraîcheur'])
    expect(main.querySelector('.erreur')).toBeNull()
    expect(main.querySelector('a[href="#/methode/limites"]')).not.toBeNull()
    expect(document.title).toBe('Fraîcheur des données : collecte et millésime')
    // La page dit ce qu'elle montre et ce qu'elle ne montre pas.
    expect(texte()).toContain('elle ne dit rien de la qualité d’une source ni de l’usage de l’argent public')
    // Elle apparaît dans le hub de son parent.
    await ecran('#/methode')
    expect(main.querySelector('a[href="#/methode/fraicheur"]')).not.toBeNull()
  })

  it('chiffres lus dans les données : date de référence, sources par statut, mise à jour du lundi', async () => {
    await ecran('#/methode/fraicheur')
    expect(texte()).toContain(`État au ${dateLongue(FX.date_reference)}`)
    expect(texte()).toContain(`${nf(FX.total)} sources suivies`)
    const t = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.startsWith('Sources par statut'))!
    const lus = Array.from(t.querySelectorAll('tbody tr')).map((tr) => [tr.querySelector('th[scope=row]')!.textContent, Number(tr.querySelector('td')!.textContent!.replace(/\s/g, ''))])
    expect(lus).toEqual(STATUTS_ORDRE.map((s) => [FX.statuts[s].libelle, FX.comptes[s]]))
    expect(lus.reduce((n, [, v]) => n + (v as number), 0)).toBe(FX.total)
    // Mise à jour hebdomadaire : jour et heure lus dans le fichier (workflow), étapes dans l'ordre.
    const m = FX.mise_a_jour_hebdomadaire
    expect(Array.from(main.querySelectorAll('h2')).map((x) => x.textContent)).toContain(`Ce que fait la mise à jour du ${m.jour}`)
    expect(texte()).toContain(`Chaque ${m.jour} à ${Number(m.heure_utc!.slice(0, 2))} h ${m.heure_utc!.slice(3)} (temps universel)`)
    expect(texte()).toContain(`en ${m.etapes.length} étapes`)
    expect(texte()).toContain('Le premier lundi du mois, elle relit aussi toutes les sources')
    expect(texte()).toContain('Elle ne publie que si une donnée a changé')
    const etapes = Array.from(main.querySelectorAll('details')).find((d) => d.querySelector('summary')?.textContent?.includes('étapes, dans l’ordre'))!
    expect(Array.from(etapes.querySelectorAll('li')).map((li) => li.textContent)).toEqual(m.etapes.map((e) => e.libelle))
    // Définitions des statuts, en toutes lettres.
    expect(Array.from(main.querySelectorAll('dl dt')).map((d) => d.textContent)).toEqual(STATUTS_ORDRE.map((s) => FX.statuts[s].libelle))
  })

  it('table par page : légende, en-têtes de ligne, millésime et dernière collecte, liens vers des routes existantes', async () => {
    await ecran('#/methode/fraicheur')
    const t = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.startsWith('Fraîcheur par page'))!
    expect(t.closest('.tableau-defile')).not.toBeNull()
    expect(Array.from(t.querySelectorAll('thead th')).every((th) => th.getAttribute('scope') === 'col')).toBe(true)
    const rangs = Array.from(t.querySelectorAll('tbody tr'))
    expect(rangs.map((tr) => tr.querySelector('th[scope=row]')!.textContent)).toEqual(FX.etapes.map((e) => e.libelle))
    for (const [i, e] of FX.etapes.entries()) {
      const cellules = Array.from(rangs[i].querySelectorAll('td')).map((td) => td.textContent ?? '')
      expect(cellules[1]).toBe(e.millesime ?? 'non indiqué')
      expect(cellules[2]).toBe(e.derniere_collecte ? dateLongue(e.derniere_collecte) : 'aucune collecte datée')
      expect(cellules[3]).toMatch(new RegExp(`^${e.sources} source`))
    }
    // Liens posés par l'écran vers les pages du site (les sigles reçoivent par ailleurs un lien vers le glossaire).
    const liens = Array.from(t.querySelectorAll('tbody th[scope=row] a'))
    expect(liens.length).toBeGreaterThan(0)
    for (const a of liens) expect(ROUTES.some((r) => `#${r.chemin}` === a.getAttribute('href')), a.getAttribute('href') ?? '').toBe(true)
    expect(pageDuSite('base')).toBe('/explorer/etat')
    expect(pageDuSite('etape_sans_page')).toBeNull()
  })

  it('liste : chaque source avec son statut écrit, ses dates, son millésime ; filtres et tris', async () => {
    await ecran('#/methode/fraicheur')
    expect(lignes()).toHaveLength(FX.sources.length)
    expect(main.querySelector('#fr-compte')?.textContent).toBe(`${nf(FX.sources.length)} sources sur ${nf(FX.total)}.`)
    expect(main.querySelector('#fr-compte')?.getAttribute('aria-live')).toBe('polite')
    for (const li of lignes()) {
      const s = FX.sources.find((x) => x.id === li.getAttribute('data-id'))!
      // Le statut est un mot, sans couleur propre (pastille à contour).
      expect(li.querySelector('.badge')?.textContent).toBe(MOT_STATUT[s.statut])
      expect(li.textContent).toContain(s.explication)
      if (s.millesime_publie) expect(li.textContent).toContain(`Millésime publié : ${s.millesime_publie}`)
      if (s.derniere_collecte) expect(li.textContent).toContain(dateLongue(s.derniere_collecte))
      if (s.prochaine_publication) expect(li.textContent).toContain(`au plus tard le ${dateLongue(s.prochaine_publication.date)}`)
      else expect(li.textContent).toContain('aucun calendrier officiel connu')
      if (s.url) expect(li.querySelector(`a[href="${s.url}"]`)?.getAttribute('rel')).toBe('noopener noreferrer')
    }
    // Filtre par statut
    for (const st of STATUTS_ORDRE) {
      saisir('#fr-statut', st)
      expect(lignes().map((li) => li.getAttribute('data-id'))).toEqual(FX.sources.filter((s) => s.statut === st).map((s) => s.id))
    }
    saisir('#fr-statut', '')
    // Filtre par page du site, et sources rattachées à aucune page
    const etape = FX.etapes.find((e) => e.sources > 0)!.etape
    saisir('#fr-page', etape)
    expect(lignes().length).toBe(FX.sources.filter((s) => s.etapes.includes(etape)).length)
    saisir('#fr-page', '__aucune')
    expect(lignes().length).toBe(FX.sources.filter((s) => !s.etapes.length).length)
    saisir('#fr-page', '')
    // Recherche dans le titre, le producteur, l'identifiant ; aucun résultat : message, pas de liste vide
    saisir('#fr-q', 'jaune')
    expect(lignes().length).toBe(FX.sources.filter((s) => `${s.titre} ${s.producteur} ${s.id}`.toLowerCase().includes('jaune')).length)
    saisir('#fr-q', 'aucune source ne porte ce nom')
    expect(lignes()).toHaveLength(0)
    expect(main.querySelector('#fr-suite .absent')?.textContent).toBe('Aucune source ne correspond.')
    saisir('#fr-q', '')
    // Tris
    saisir('#fr-tri', 'nom')
    const noms = lignes().map((li) => li.querySelector('span')!.textContent ?? '')
    expect(noms).toEqual([...noms].sort((a, b) => a.localeCompare(b, 'fr')))
    saisir('#fr-tri', 'prochaine')
    const dates = lignes().map((li) => FX.sources.find((s) => s.id === li.getAttribute('data-id'))!.prochaine_publication?.date ?? '9999')
    expect(dates).toEqual([...dates].sort())
    saisir('#fr-tri', 'collecte')
    const collectes = lignes().map((li) => FX.sources.find((s) => s.id === li.getAttribute('data-id'))!.derniere_collecte ?? '')
    expect(collectes).toEqual([...collectes].sort().reverse())
    expect(main.querySelector('[data-regle-ordre]')?.textContent).toBe(FX.ordre!.regle)
  })

  it('filtre initial par l’adresse (?statut=en_retard)', async () => {
    await ecran('#/methode/fraicheur?statut=en_retard')
    expect((main.querySelector('#fr-statut') as HTMLSelectElement).value).toBe('en_retard')
    expect(lignes().length).toBe(FX.sources.filter((s) => s.statut === 'en_retard').length)
  })

  it('longue liste : 30 sources d’abord, puis 30 de plus sur demande', async () => {
    const zone = document.createElement('div')
    const nombreuses = { ...FX, sources: Array.from({ length: 45 }, (_, i) => ({ ...FX.sources[i % FX.sources.length], id: `s${i}`, titre: `Source ${String(i).padStart(2, '0')}` })), total: 45 }
    const vrai = globalThis.fetch
    const { viderCache } = await import('../src/donnees')
    viderCache()
    globalThis.fetch = (async (u: string) => (String(u).includes('fraicheur/') ? new Response(JSON.stringify(nombreuses), { status: 200 }) : vrai(u))) as typeof fetch
    try {
      await rendre(zone, new URLSearchParams())
      expect(zone.querySelectorAll('#fr-liste li')).toHaveLength(30)
      const plus = zone.querySelector<HTMLButtonElement>('#fr-plus')!
      expect(plus.textContent).toBe('Afficher 15 de plus')
      plus.click()
      expect(zone.querySelectorAll('#fr-liste li')).toHaveLength(45)
      expect(zone.querySelector('#fr-plus')).toBeNull()
    } finally {
      globalThis.fetch = vrai
      viderCache()
    }
  })

  it('statut jamais porté par la seule couleur ; ni style en ligne, ni tiret long, ni surligneur', async () => {
    await ecran('#/methode/fraicheur')
    expect(main.querySelectorAll('[style]')).toHaveLength(0)
    expect(main.textContent).not.toContain('—')
    expect(main.querySelectorAll('.surligne')).toHaveLength(0)
    expect(main.querySelectorAll('a[href=""], a:not([href])')).toHaveLength(0)
    for (const b of Array.from(main.querySelectorAll('#fr-liste .badge'))) expect(Object.values(MOT_STATUT)).toContain(b.textContent)
    // Chaque champ de formulaire a son étiquette.
    for (const c of Array.from(main.querySelectorAll('#fr-filtres input, #fr-filtres select'))) expect(main.querySelector(`label[for="${c.id}"]`), c.id).not.toBeNull()
  })

  it('lexique neutre sur tout le texte affiché, détails dépliables compris', async () => {
    await ecran('#/methode/fraicheur')
    verifierLexique(main.textContent ?? '', 'fraîcheur')
    for (const el of Array.from(main.querySelectorAll('[aria-label], [title], [alt]')))
      verifierLexique(['aria-label', 'title', 'alt'].map((a) => el.getAttribute(a) ?? '').join(' '), 'fraîcheur (attribut)')
    const r = ROUTES.find((x) => x.chemin === '/methode/fraicheur')!
    verifierLexique(`${r.titre} ${r.titrePage ?? ''} ${r.description} ${r.resume ?? ''}`, 'route')
  })

  it('fichier absent : état « en cours d’intégration » propre, avec une sortie', async () => {
    const vrai = globalThis.fetch
    const { viderCache } = await import('../src/donnees')
    viderCache()
    globalThis.fetch = (async (u: string) => (String(u).includes('fraicheur/') ? new Response('', { status: 404 }) : vrai(u))) as typeof fetch
    try {
      const z = document.createElement('div')
      await rendre(z, new URLSearchParams())
      expect(z.textContent).toContain('Données en cours d’intégration')
      expect(z.querySelector('a[href="#/methode"]')).not.toBeNull()
      expect(z.querySelector('.erreur')).toBeNull()
    } finally {
      globalThis.fetch = vrai
      viderCache()
    }
  })

  it('fonctions pures : dates en toutes lettres, tri stable, filtre', () => {
    expect(dateLongue('2026-10-06')).toBe('6 octobre 2026')
    expect(dateLongue('2027-05-01')).toBe('1er mai 2027')
    expect(dateLongue(null)).toBe('date inconnue')
    const a = { ...FX.sources[0], id: 'a', titre: 'Bêta', derniere_collecte: null, prochaine_publication: null }
    const b = { ...FX.sources[0], id: 'b', titre: 'Alpha', derniere_collecte: '2026-11-01', prochaine_publication: { date: '2027-04-22', edition: 'x', calendrier: 'pde', passee: false } }
    expect(trier([a, b], 'nom').map((x) => x.id)).toEqual(['b', 'a'])
    expect(trier([a, b], 'collecte').map((x) => x.id)).toEqual(['b', 'a'])
    expect(trier([a, b], 'prochaine').map((x) => x.id)).toEqual(['b', 'a'])
    expect(trier([a, b], 'page').map((x) => x.id)).toEqual(['a', 'b'])
    expect(filtrer([a, b], { q: 'ALPHA', statut: '', page: '' }).map((x) => x.id)).toEqual(['b'])
  })

  it('toutes les lectures de données sont relatives au site', async () => {
    await attendreQue(() => requetes.length > 0)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })
})

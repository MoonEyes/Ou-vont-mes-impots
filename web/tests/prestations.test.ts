// @vitest-environment happy-dom
// Écran « Les prestations versées aux ménages » (/explorer/prestations) sur des extraits réels de site/data/prestations
// (tests/fixtures/data/prestations : index et nationales entiers, fichiers départementaux réduits à quelques
// départements). Chaque attente est recalculée depuis les fixtures : aucun chiffre n'est recopié ici.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { picto } from '../src/composants/pictos'
import { viderCache } from '../src/donnees'
import { adresseBloc } from '../src/ecrans/prestations'
import { afficher, titreDocument } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { entier, eurLisible, pct, sur100 } from '../src/util'
import { attendreQue, choisirValeur, monterPage, requetes } from './aide-dom'

type Serie = Record<string, number | null>
interface Lien {
  vue: string
  fichier: string
  id: string
}
interface Ecart {
  prestation: string
  annee: number
  source: string
  autre_source: string
  ecart: number
  ecart_pct: number
  lien?: string
  grandeur?: string
}

const RACINE = process.cwd()
const FIX = join(RACINE, 'tests', 'fixtures', 'data', 'prestations')
const lire = (f: string) => JSON.parse(readFileSync(join(FIX, f), 'utf8'))
const index = lire('index.json') as {
  prestations: { id: string; nom: string; financeur: string; liens: Lien[] }[]
  totaux: { drees_cps: { montant_eur: Serie; total_prestations_protection_sociale_eur: Serie; part_du_total_pct: Serie } }
  ecarts: Ecart[]
  fichiers: { departements: Record<string, string> }
  sources: Record<string, { page?: string; url: string }>
}
const nat = lire('nationales.json') as {
  annees: number[]
  prestations: Record<
    string,
    {
      nom: string
      serie_principale: string
      sources_montant: Record<string, Serie>
      derniere_annee: number
      beneficiaires: Serie
      par_regime?: { code_secteur: string; regime: string; fichier: string }[]
    }
  >
}
const plat = (s: string | null | undefined) => (s ?? '').replace(/\s+/g, ' ').trim()
const MOINS = '−'
const signe = (x: number, f: (n: number) => string) => `${x > 0 ? '+' : x < 0 ? MOINS : ''}${f(Math.abs(x))}`
const nombre = (x: unknown): x is number => typeof x === 'number'

// Année de référence et ordre attendus, recalculés depuis les données (même source pour toutes les prestations).
const tot = index.totaux.drees_cps
const anRef = Object.keys(tot.montant_eur)
  .filter((a) => nombre(tot.montant_eur[a]) && nombre(tot.total_prestations_protection_sociale_eur[a]))
  .sort()
  .pop()!
const drees = (id: string) => nat.prestations[id].sources_montant.drees_cps?.[anRef] ?? -1
const ordre = index.prestations.map((p) => p.id).sort((a, b) => drees(b) - drees(a))
const section = (id: string) => main.querySelector(`section[aria-labelledby="pr-${id}"]`) as HTMLElement

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => plat(main.textContent)
const zoneDep = () => main.querySelector('#pr-dep-resultat') as HTMLElement
const cellules = (tr: Element) => Array.from(tr.querySelectorAll('td')).map((td) => plat(td.textContent))

// Lexique neutre partagé (docs/lexique_neutre.json), même vérification que tests/ecrans.test.ts.
const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as {
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

describe('prestations versées aux ménages', () => {
  it('route : hub Explorer, famille et picto existants, voisins existants, titre et description conformes', () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/prestations')!
    expect(r).toBeTruthy()
    expect(r.parent).toBe('/explorer')
    expect(r.famille).toBe('prestations')
    expect(picto(r.picto!)).not.toBe('')
    expect(r.voisins!.length).toBeGreaterThanOrEqual(1)
    expect(r.voisins!.length).toBeLessThanOrEqual(3)
    for (const v of r.voisins!) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    expect(r.description.length).toBeGreaterThanOrEqual(70)
    expect(r.description.length).toBeLessThanOrEqual(200)
    expect(titreDocument(r).length).toBeLessThanOrEqual(100)
    expect(ROUTES.filter((x) => titreDocument(x) === titreDocument(r))).toHaveLength(1)
    expect(ROUTES.filter((x) => x.description === r.description)).toHaveLength(1)
    verifierLexique(`${r.titre} ${r.description} ${r.resume ?? ''}`, 'route')
  })

  it('chiffre clé : une seule source, sur 100 €, un seul surligneur, statut et source citée', async () => {
    await ecran('#/explorer/prestations')
    expect(main.querySelector('h1')?.textContent).toContain('Les prestations versées aux ménages')
    const s = main.querySelectorAll('.surligne')
    expect(s).toHaveLength(1)
    expect(plat(s[0].textContent)).toBe(plat(eurLisible(tot.montant_eur[anRef]!)))
    const cle = s[0].closest('[data-cle]') as HTMLElement
    expect(plat(cle.textContent)).toContain(`${plat(sur100(tot.part_du_total_pct[anRef]!))} sur 100 €`)
    expect(plat(cle.textContent)).toContain(`versés en ${anRef}`)
    expect(plat(cle.textContent)).toContain('Tracé')
    expect(cle.querySelector('.source a')?.getAttribute('href')).toBe(index.sources.drees_cps.page)
    // L'introduction dit ce que la page montre et ce qu'elle ne montre pas.
    expect(texte()).toContain('aucune donnée sur une personne')
    expect(texte()).toContain('elle ne calcule pas tes droits')
    // Légende des trois statuts, chacun avec son motif et son mot.
    for (const m of ['Tracé', 'Approché', 'Non publié']) expect(plat(main.querySelector('.legende-statuts')?.textContent)).toContain(m)
  })

  it('barres : chaque prestation, ordre décroissant dans une même source, sur 100 €, statut tracé, règle d’ordre écrite', async () => {
    await ecran('#/explorer/prestations')
    const li = Array.from(main.querySelectorAll('ul.barres li'))
    expect(li.map((x) => plat(x.querySelector('.nom')?.textContent))).toEqual(ordre.map((id) => nat.prestations[id].nom))
    const total = tot.total_prestations_protection_sociale_eur[anRef]!
    li.forEach((x, i) => {
      const v = nat.prestations[ordre[i]].sources_montant.drees_cps[anRef]!
      expect(plat(x.querySelector('.valeur')?.textContent)).toBe(`${plat(eurLisible(v))} Tracé`)
      expect(plat(x.textContent)).toContain(`${plat(sur100((v / total) * 100))} sur 100 €`)
    })
    expect(main.querySelector('[data-regle-ordre]')?.textContent).toContain(`montant versé en ${anRef}`)
    // Le reste du total de la même source renvoie à la vue détaillée de la Sécurité sociale, sans la recopier.
    expect(main.querySelector('a[href="#/explorer/secu?m=protection2024"]')).not.toBeNull()
  })

  it('récapitulatif : dernière année de chaque prestation, effectifs absents jamais à 0', async () => {
    await ecran('#/explorer/prestations')
    const t = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.startsWith('Dernière année publiée'))!
    const lignes = Array.from(t.querySelectorAll('tbody tr'))
    expect(lignes).toHaveLength(ordre.length)
    lignes.forEach((tr, i) => {
      const p = nat.prestations[ordre[i]]
      const an = String(p.derniere_annee)
      const [m, b] = cellules(tr)
      const entete = plat(tr.querySelector('th')?.textContent)
      expect(entete).toContain(p.nom)
      expect(entete).toContain(`${an} ·`)
      expect(m).toBe(plat(eurLisible(p.sources_montant[p.serie_principale][an]!)))
      const ben = p.beneficiaires[an]
      expect(b, ordre[i]).toBe(nombre(ben) ? plat(entier(ben)) : 'Non publié')
    })
  })

  it('fiches : titre, montant de la dernière année avec sa source et son statut, qui verse, qui finance', async () => {
    await ecran('#/explorer/prestations')
    for (const p of index.prestations) {
      const sec = section(p.id)
      expect(sec, p.id).not.toBeNull()
      expect(plat(sec.querySelector('h3')?.textContent)).toBe(p.nom)
      const n = nat.prestations[p.id]
      const t = plat(sec.textContent)
      expect(t).toContain(`Montant versé en ${n.derniere_annee}`)
      expect(t).toContain(plat(eurLisible(n.sources_montant[n.serie_principale][String(n.derniere_annee)]!)))
      expect(t).toContain('Qui verse')
      expect(t).toContain('Qui finance')
      expect(t).toContain(plat(p.financeur))
      expect(t).toContain('Tracé')
      expect(sec.querySelector('.source a'), p.id).not.toBeNull()
    }
  })

  it('évolution : une ligne par source jamais additionnée, écarts publiés tels quels, années non publiées jamais à 0', async () => {
    await ecran('#/explorer/prestations')
    const annees = nat.annees.map(String)
    for (const p of index.prestations) {
      const n = nat.prestations[p.id]
      const table = section(p.id).querySelector('table') as HTMLTableElement
      expect(Array.from(table.querySelectorAll('thead th')).slice(1).map((x) => plat(x.textContent))).toEqual(annees)
      const lignes = Array.from(table.querySelectorAll('tbody tr'))
      for (const [src, serie] of Object.entries(n.sources_montant)) {
        const attendu = annees.map((a) => (nombre(serie[a]) ? plat(eurLisible(serie[a]!)) : 'Non publié'))
        expect(
          lignes.some((tr) => JSON.stringify(cellules(tr)) === JSON.stringify(attendu)),
          `${p.id} : ligne ${src}`,
        ).toBe(true)
      }
      const sources = Object.keys(n.sources_montant)
      const ecarts = index.ecarts.filter((e) => e.prestation === p.id && !e.grandeur && sources.includes(e.source) && sources.includes(e.autre_source))
      if (!ecarts.length) continue
      const ligne = lignes.find((tr) => plat(tr.querySelector('th')?.textContent).startsWith('Écart :'))!
      const c = cellules(ligne)
      for (const e of ecarts) expect(c[annees.indexOf(String(e.annee))], `${p.id} ${e.annee}`).toBe(plat(`${signe(e.ecart, eurLisible)} (${signe(e.ecart_pct, (x) => pct(x))})`))
      // Année sans écart publié : dit « sans objet », jamais 0.
      annees.filter((a) => !ecarts.some((e) => String(e.annee) === a)).forEach((a) => expect(c[annees.indexOf(a)]).toBe('sans objet'))
    }
  })

  it('financeurs : chaque bloc publié est relié à sa visionneuse, écarts avec les comptes des financeurs montrés', async () => {
    expect(adresseBloc({ vue: 'secu_cps', fichier: 'secu/cps/x.json', id: 'S1/A' })).toBe('#/explorer/secu?m=protection2024&id=S1%2FA')
    expect(adresseBloc({ vue: 'secu_arbre', fichier: 'secu/arbre/racine.json', id: 'robss/famille' })).toBe('#/explorer/secu?m=organismes2024&id=robss%2Ffamille')
    expect(adresseBloc({ vue: 'arbre_etat', fichier: 'arbre/X.json', id: 'A/B' })).toBe('#/explorer/etat/detail?m=execution2024&id=A%2FB')
    expect(adresseBloc({ vue: 'local', fichier: 'local/budgets/departements.json', id: 'collectivites' })).toBe('#/explorer/collectivites')
    await ecran('#/explorer/prestations')
    for (const p of index.prestations) {
      const parRegime = nat.prestations[p.id].par_regime
      for (const l of p.liens) {
        if (l.vue === 'secu_cps' && parRegime) continue
        expect(main.querySelector(`a[href="${adresseBloc(l)}"]`), `${p.id} : ${l.id}`).not.toBeNull()
      }
      // Pensions : un lien par régime publié, vers le régime dans les comptes de la protection sociale.
      for (const r of parRegime ?? [])
        expect(section(p.id).querySelector(`a[href="${adresseBloc({ fichier: r.fichier, id: `${r.code_secteur}/${r.regime}` })}"]`), r.regime).not.toBeNull()
    }
    // Écart publié entre une prestation et le bloc de son financeur : montré dans la fiche, tel que publié.
    for (const e of index.ecarts.filter((x) => x.lien && !x.grandeur && !x.prestation.includes('+')))
      expect(plat(section(e.prestation).textContent), `${e.prestation} : ${e.lien}`).toContain(plat(`${signe(e.ecart, eurLisible)} (${signe(e.ecart_pct, (x) => pct(x))})`))
  })

  it('département : valeurs de la source, financeur du RSA, part dans la somme des départements, statuts', async () => {
    const an = Object.keys(index.fichiers.departements).sort()[0]
    const d = lire(`departements/${an}.json`)
    const code = '93'
    await ecran(`#/explorer/prestations?dep=${code}&an=${an}`)
    expect(plat(zoneDep().querySelector('h3')?.textContent)).toBe(`Seine-Saint-Denis (${code}) en ${an}`)
    const lignes = Array.from(zoneDep().querySelectorAll('table')[0].querySelectorAll('tbody tr'))
    expect(lignes).toHaveLength(Object.keys(d.prestations).length)
    for (const tr of lignes) {
      const k = Object.keys(d.prestations).find((x) => d.prestations[x] === plat(tr.querySelector('th')?.textContent))!
      expect(k, plat(tr.querySelector('th')?.textContent)).toBeTruthy()
      const t = d.departements[code][k] as (number | null)[]
      const c = cellules(tr)
      expect(c[0].replace(' Approché', '')).toBe(nombre(t[0]) ? plat(entier(t[0])) : 'Non publié')
      expect(c[1]).toBe(nombre(t[1]) ? plat(eurLisible(t[1])) : 'Non publié')
      const somme = Object.values(d.departements as Record<string, Record<string, unknown>>)
        .map((r) => (Array.isArray(r[k]) ? (r[k] as (number | null)[])[1] : null))
        .filter(nombre)
        .reduce((s, x) => s + x, 0)
      expect(c[3]).toBe(nombre(t[1]) ? plat(sur100((t[1] / somme) * 100)) : 'Non publié')
    }
    const financeur = { etat: 'l’État', departement: 'le département', departement_puis_etat: 'le département, puis l’État' }[d.departements[code].financeur_rsa as string]
    expect(texte()).toContain(`Qui finance le revenu de solidarité active ici en ${an} : ${financeur}`)
    // Les lignes sont des prestations : aucun code hors département (Saint-Martin, résidence inconnue ou à l'étranger).
    const hors = Object.keys(d.hors_departements ?? {})
    expect(hors.length).toBeGreaterThan(0)
    for (const tr of lignes) expect(hors).not.toContain(plat(tr.querySelector('th')?.textContent))
    // Les notes de la source sont lues en mots : ni « null » ni code technique du financeur.
    expect(plat(zoneDep().textContent)).not.toMatch(/\bnull\b|departement_puis_etat/)
  })

  it('département : année incomplète à la source jamais affichée à 0 ; effectif estimé par la DREES « approché »', async () => {
    // Un département et une année où la source n'a pas de montant annuel (mois manquants) : « non publié », jamais 0.
    const ans = Object.keys(index.fichiers.departements).sort()
    let trouve: [string, string] | null = null
    for (const a of ans) {
      const d = lire(`departements/${a}.json`)
      for (const [c, r] of Object.entries(d.departements as Record<string, Record<string, unknown>>))
        if (!trouve && Array.isArray(r.rsa) && r.rsa[1] === null) trouve = [c, a]
    }
    expect(trouve).not.toBeNull()
    await ecran(`#/explorer/prestations?dep=${trouve![0]}&an=${trouve![1]}`)
    for (const tr of Array.from(zoneDep().querySelectorAll('table')[0].querySelectorAll('tbody tr'))) for (const c of cellules(tr)) expect(c).not.toMatch(/^(0|0 €|0,0 %)$/)
    expect(plat(zoneDep().textContent)).toContain('Non publié')
    // Renvoi « (1) » de la source (Corse) : effectif du minimum vieillesse estimé, statut « approché ».
    const d = lire(`departements/${ans[0]}.json`)
    const corse = Object.entries(d.departements as Record<string, { nom: string }>).find(([, r]) => /\(\d+\)\s*$/.test(r.nom))!
    await ecran(`#/explorer/prestations?dep=${corse[0]}&an=${ans[0]}`)
    const aspa = Array.from(zoneDep().querySelectorAll('tbody tr')).find((tr) => plat(tr.querySelector('th')?.textContent) === d.prestations.aspa)!
    expect(cellules(aspa)[0]).toContain('Approché')
    expect(plat(zoneDep().textContent)).toContain('estimé par la DREES')
  })

  it('département : choix sur place, sans navigation, puis évolution chargée à la demande', async () => {
    await ecran('#/explorer/prestations')
    const avant = location.hash
    expect(zoneDep().getAttribute('aria-live')).toBe('polite')
    const dep = main.querySelector<HTMLSelectElement>('#pr-dep-choix')!
    expect(dep.querySelectorAll('option')).toHaveLength(102)
    dep.value = '44'
    dep.dispatchEvent(new Event('change'))
    await attendreQue(() => (zoneDep().querySelector('h3')?.textContent ?? '').includes('Loire-Atlantique (44)'))
    const ans = Object.keys(index.fichiers.departements).sort()
    choisirValeur(main, 'pr-dep-an', ans[0])
    await attendreQue(() => (zoneDep().querySelector('h3')?.textContent ?? '').includes(`en ${ans[0]}`))
    expect(location.hash).toBe(avant)
    const evol = zoneDep().querySelector<HTMLDetailsElement>('details.pr-evolution')!
    evol.open = true
    evol.dispatchEvent(new Event('toggle'))
    await attendreQue(() => evol.querySelectorAll('table').length === 2)
    const montants = evol.querySelectorAll('table')[0]
    expect(Array.from(montants.querySelectorAll('thead th')).slice(1).map((x) => plat(x.textContent))).toEqual(ans)
    for (const a of ans) expect(requetes).toContain(`data/prestations/departements/${a}.json`)
    // Chaque cellule reprend le fichier de son année.
    const nomRsa = lire(`departements/${ans[0]}.json`).prestations.rsa
    const ligneRsa = Array.from(montants.querySelectorAll('tbody tr')).find((tr) => plat(tr.querySelector('th')?.textContent) === nomRsa)!
    ans.forEach((a, i) => {
      const v = lire(`departements/${a}.json`).departements['44'].rsa[1]
      expect(cellules(ligneRsa)[i], a).toBe(nombre(v) ? plat(eurLisible(v)) : 'Non publié')
    })
    // Retour à l'invite quand le choix est vidé.
    dep.value = ''
    dep.dispatchEvent(new Event('change'))
    await attendreQue(() => !zoneDep().querySelector('h3'))
  })

  it('neutralité et affichage : lexique neutre, aucun tiret long, aucun style en ligne, titres sans adjectif, lectures locales', async () => {
    for (const f of ['#/explorer/prestations', '#/explorer/prestations?dep=93&an=2024', '#/explorer/prestations?dep=976&an=2022']) {
      await ecran(f)
      verifierLexique(document.body.textContent ?? '', f)
      for (const el of Array.from(main.querySelectorAll('[aria-label], [title], [alt]'))) verifierLexique(['aria-label', 'title', 'alt'].map((a) => el.getAttribute(a) ?? '').join(' '), `${f} (attribut)`)
      expect(main.textContent, f).not.toContain('\u2014')
      expect(Array.from(main.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l') && !el.hasAttribute('data-g') && !el.hasAttribute('data-f'))).toHaveLength(0)
      for (const t of Array.from(main.querySelectorAll('h1, h2, h3'))) expect(t.textContent ?? '', f).not.toMatch(/\b(gaspillage|seulement|énorme|opaque|scandale|trop)\b/i)
      // Sorties nommées (pas de « cliquez ici »), et retour au hub par le fil d'Ariane.
      for (const a of Array.from(main.querySelectorAll('a[href^="#/"]'))) expect(a.textContent ?? '', f).not.toMatch(/^\s*(ici|cliquez ici|lien|en savoir plus)\s*$/i)
      expect(main.querySelector('nav.fil-ariane a[href="#/explorer"]'), f).not.toBeNull()
    }
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })

  it('données absentes : page « en cours d’intégration », sans erreur', async () => {
    const { rendre } = await import('../src/ecrans/prestations')
    viderCache()
    const vrai = globalThis.fetch
    globalThis.fetch = (async (u: string) => (String(u).includes('prestations/') ? new Response('', { status: 404 }) : vrai(u))) as typeof fetch
    const z = document.createElement('div')
    await rendre(z, new URLSearchParams())
    expect(z.textContent).toContain('Données en cours d’intégration')
    expect(z.querySelector('.erreur')).toBeNull()
    globalThis.fetch = vrai
    viderCache()
  })

  it('page Sécurité sociale : renvoi vers les prestations, sans bloc recopié', async () => {
    await ecran('#/explorer/secu')
    expect(main.querySelector('a[href="#/explorer/prestations"]')?.textContent).toContain('Les prestations versées aux ménages')
    expect(main.querySelector('section[aria-labelledby^="pr-"]')).toBeNull()
  })
})

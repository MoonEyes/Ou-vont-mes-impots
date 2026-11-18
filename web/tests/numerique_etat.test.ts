// @vitest-environment happy-dom
// Écran « Le numérique de l'État » (/explorer/numerique-etat) sur des extraits réels de site/data/numerique_etat
// (tests/fixtures/data/numerique_etat), puis contrôles de confidentialité et de lexique sur les données publiées.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { meur, moisAnnee, REGLE_MINISTERES, REGLE_PROJETS, signe, valeurReleve } from '../src/ecrans/numerique_etat'
import { attendre, monterPage } from './aide-dom'

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = (el: Element = main) => el.textContent?.replace(/\s+/g, ' ') ?? ''
const FIX = join(process.cwd(), 'tests', 'fixtures', 'data', 'numerique_etat')
const lire = (p: string) => JSON.parse(readFileSync(join(FIX, p), 'utf8'))
const choisir = (id: string, valeur: string) => {
  const s = main.querySelector<HTMLSelectElement | HTMLInputElement>(id)!
  s.value = valeur
  main.querySelector('#filtres-ne')!.dispatchEvent(new Event('input', { bubbles: true }))
}
const nomsListe = () => Array.from(main.querySelectorAll('#liste-ne details > summary')).map((s) => s.textContent)

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('numérique de l’État', () => {
  it('formats : mois en clair, écarts signés sans qualificatif, valeur absente jamais 0', () => {
    expect(moisAnnee('2025-12')).toBe('décembre 2025')
    expect(signe(17.58, meur).replace(/\s/g, ' ')).toBe('+17,6 M€')
    expect(signe(-1.96, meur)).toBe('−2,0 M€')
    expect(signe(0.01, meur)).toBe('0,0 M€')
    expect(valeurReleve(null, 'en cadrage', meur)).toBe('non publié (en cadrage)')
    expect(valeurReleve(null, null, meur)).toBe('non publié')
  })

  it('route sous Explorer : titre, fil d’Ariane, chiffres clés lus dans les données avec édition, source et statut', async () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/numerique-etat')!
    expect(r.parent).toBe('/explorer')
    await ecran('#/explorer/numerique-etat')
    expect(main.querySelector('h1')?.textContent).toContain('Le numérique de l’État')
    expect(main.querySelector('nav[aria-label="Fil d\'Ariane"] [aria-current=page]')?.getAttribute('href')).toBe('#/explorer/numerique-etat')
    const eds = lire('panorama/editions.json').editions
    const der = eds[eds.length - 1]
    const cles = Array.from(main.querySelectorAll('.cles li')).map((li) => texte(li))
    expect(cles).toHaveLength(3)
    expect(cles[0]).toContain(`${der.projets}grands projets suivis dans l’édition de décembre 2025`)
    expect(cles[1]).toContain('4,5 Md€')
    expect(cles[1]).toContain('pas une dépense annuelle')
    expect(cles[2]).toContain(`${lire('index.json').panorama.projets}projets suivis`)
    for (const li of Array.from(main.querySelectorAll('.cles li'))) expect(li.querySelector('.badge')?.textContent).toBe('Tracé')
    expect(texte(main.querySelector('.cles + .source')!)).toContain('Direction interministérielle du numérique (DINUM)')
    expect(main.querySelector('.cles + .source a')?.getAttribute('href')).toMatch(/^https:\/\/www\.data\.gouv\.fr\//)
    // Aucun chiffre mis en avant : pas de surligneur sur cette page.
    expect(main.querySelectorAll('.surligne')).toHaveLength(0)
  })

  it('édition après édition : une ligne par édition, la plus récente en tête, lien vers chaque classeur', async () => {
    await ecran('#/explorer/numerique-etat')
    const eds = lire('panorama/editions.json').editions
    const t = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.startsWith('Grands projets numériques suivis dans chaque édition'))!
    const lignes = t.querySelectorAll('tbody tr')
    expect(lignes).toHaveLength(eds.length)
    expect(lignes[0].querySelector('th a')?.getAttribute('href')).toBe(eds[eds.length - 1].url)
    expect(texte(lignes[0])).toContain('4 530,2 M€')
    expect(texte(lignes[lignes.length - 1])).toContain('novembre 2016')
    for (const th of Array.from(t.querySelectorAll('thead th'))) expect(th.getAttribute('scope')).toBe('col')
  })

  it('projets : ordre alphabétique annoncé, dernière édition par défaut, filtres ministère, recherche et période', async () => {
    await ecran('#/explorer/numerique-etat')
    expect(Array.from(main.querySelectorAll('[data-regle-ordre]')).map((x) => x.textContent)).toEqual([REGLE_PROJETS, REGLE_MINISTERES])
    const projets = lire('panorama/projets.json').projets as { nom: string; editions: { dans_la_derniere_edition: boolean } }[]
    const attendus = projets.filter((p) => p.editions.dans_la_derniere_edition).map((p) => p.nom)
    expect(nomsListe()).toEqual(attendus)
    // Aucun projet mis en avant.
    for (const li of Array.from(main.querySelectorAll('#liste-ne li'))) expect(li.querySelector('.surligne, mark, strong')).toBeNull()
    choisir('#ne-perimetre', 'tous')
    expect(nomsListe()).toEqual(projets.map((p) => p.nom))
    // Ministères : nom complet publié, jamais le sigle seul.
    const options = Array.from(main.querySelectorAll('#ne-min option')).slice(1)
    for (const o of options) expect(o.textContent).toMatch(/^(Ministère|Ministères|Premier|Services)/)
    choisir('#ne-min', 'MJ')
    expect(nomsListe()).toEqual(['ASTREA', 'ATIGIP'])
    expect(texte(main.querySelector('#liste-ne')!)).toContain('Ministère de la Justice (MJ)')
    choisir('#ne-min', '')
    choisir('#ne-q', 'sirh')
    expect(nomsListe()).toEqual(['SIRHEN'])
    expect(texte(main.querySelector('#liste-ne')!)).toContain('absent des éditions suivantes')
    choisir('#ne-q', 'introuvable')
    expect(texte(main.querySelector('#liste-ne')!)).toContain('Aucun projet ne correspond.')
  })

  it('écarts du coût estimé et de la durée : première et dernière valeur publiées, écart tel quel, bornes publiées', async () => {
    await ecran('#/explorer/numerique-etat')
    const li = Array.from(main.querySelectorAll('#liste-ne li')).find((x) => x.querySelector('summary')?.textContent === 'ASTREA')!
    const t = texte(li)
    expect(t).toContain('coût estimé publié : 20,0 M€ en novembre 2016, 37,6 M€ en décembre 2025, écart +17,6 M€ (+87,9 %) ; valeurs publiées entre 20,0 M€ et 77,3 M€')
    expect(t).toContain('durée prévue publiée : 8,0 ans en novembre 2016, 6,0 ans en décembre 2025, écart −2,0 ans')
    const seul = Array.from(main.querySelectorAll('#liste-ne li')).find((x) => x.querySelector('summary')?.textContent === 'ANEF DEC AGDREF')!
    expect(texte(seul)).toContain('une seule valeur publiée')
  })

  it('fiche d’un projet : un relevé par édition, valeur non publiée avec sa raison, programmes reliés au budget', async () => {
    await ecran('#/explorer/numerique-etat')
    choisir('#ne-perimetre', 'tous')
    const d = main.querySelector<HTMLDetailsElement>('#liste-ne details[data-id="3-pas-s-dae"]')!
    d.open = true
    d.dispatchEvent(new Event('toggle'))
    await attendre()
    const p = (lire('panorama/projets.json').projets as { id: string; releves: unknown[] }[]).find((x) => x.id === '3-pas-s-dae')!
    expect(d.querySelectorAll('tbody tr')).toHaveLength(p.releves.length)
    expect(texte(d)).toContain('non publié (en cadrage)')
    expect(d.querySelector('.motif-nonpub')).not.toBeNull()
    expect(d.querySelector('a[href="#/beneficiaires/programme?p=218"]')?.textContent).toBe('programme 218')
    expect(texte(d)).toMatch(/Minist\S+ de l.\S+conomie et des Finances \(MEF\)/)
    expect(d.querySelector('caption')?.textContent).toContain('3-PAS-S_DAE')
  })

  it('programme du budget en paramètre : seuls les projets qui le citent', async () => {
    await ecran('#/explorer/numerique-etat?p=214')
    expect(nomsListe()).toEqual(['SIRHEN'])
    expect(main.querySelector('#filtres-ne a[href="#/explorer/numerique-etat"]')).not.toBeNull()
  })

  it('fonds : un fonds par ligne avec période, montants publiés et projets sans montant à part, jamais de total', async () => {
    await ecran('#/explorer/numerique-etat')
    const t = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.startsWith('Fonds de transformation numérique'))!
    const lignes = Array.from(t.querySelectorAll('tbody tr'))
    expect(lignes).toHaveLength(5)
    expect(texte(t)).not.toMatch(/total/i)
    const fr = texte(lignes[0])
    expect(fr).toContain('3 603')
    expect(fr).toContain('285,8 M€')
    expect(lignes[0].querySelector('a[href="#/beneficiaires/programme?p=363"]')).not.toBeNull()
    expect(texte(main)).toContain('ne s’additionnent pas')
    // Sigles des fonds toujours accompagnés de leur nom en clair.
    expect(texte(t)).toContain('Fonds pour la transformation de l’action publique (FTAP)')
  })

  it('page sans données : état « en cours d’intégration »', async () => {
    const { rendre } = await import('../src/ecrans/numerique_etat')
    const { viderCache } = await import('../src/donnees')
    viderCache()
    const vrai = globalThis.fetch
    globalThis.fetch = (async (u: string) => (String(u).includes('numerique_etat/') ? new Response('', { status: 404 }) : vrai(u))) as typeof fetch
    const z = document.createElement('div')
    await rendre(z)
    expect(z.textContent).toContain('Données en cours d’intégration')
    globalThis.fetch = vrai
    viderCache()
  })
})

// Contrôles sur les données publiées (site/data/numerique_etat), quand elles sont présentes dans la copie de travail.
const DONNEES = join(process.cwd(), '..', 'site', 'data', 'numerique_etat')
const fichiers = (d: string): string[] =>
  existsSync(d) ? readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? fichiers(join(d, f)) : f.endsWith('.json') ? [join(d, f)] : [])) : []

describe.skipIf(!existsSync(DONNEES))('numérique de l’État : données publiées', () => {
  const tous = fichiers(DONNEES)
  const champs = (o: unknown, cles: Set<string>, out: string[] = [], ici = ''): string[] => {
    if (Array.isArray(o)) o.forEach((x) => champs(x, cles, out, ici))
    else if (o && typeof o === 'object') for (const [k, v] of Object.entries(o)) champs(v, cles, out, k)
    else if (typeof o === 'string' && cles.has(ici)) out.push(o)
    return out
  }

  it('aucune colonne de personne, aucun porteur ou lauréat avec civilité ou coordonnée', () => {
    expect(tous.length).toBeGreaterThan(10)
    // « nom » désigne un département, un projet ou un fonds : ses valeurs sont contrôlées comme celles des porteurs.
    const INTERDITES = /^(prenom|prénom|responsable|dirigeant|chef_de_projet|directeur|directrice|adresse|courriel|email|telephone|téléphone)$/i
    const CIVILITE = /(^|[\s(])(M\.|Mme|Mlle|Monsieur|Madame)\s/
    const COORD = /[\w.+-]+@[\w-]+\.[a-z]{2,}|\b0[1-9](?:[ .]?\d\d){4}\b|https?:\/\//
    const noms = new Set(['nom', 'porteur', 'laureat', 'collectivite', 'ministere', 'ministere_nom', 'incubateur'])
    for (const f of tous) {
      const doc = JSON.parse(readFileSync(f, 'utf8'))
      const cles: string[] = []
      const parcourir = (o: unknown) => {
        if (Array.isArray(o)) o.forEach(parcourir)
        else if (o && typeof o === 'object') for (const [k, v] of Object.entries(o)) (cles.push(k), parcourir(v))
      }
      parcourir(doc)
      for (const k of cles) expect(k, f).not.toMatch(INTERDITES)
      for (const v of champs(doc, noms)) {
        expect(v, f).not.toMatch(CIVILITE)
        expect(v, f).not.toMatch(COORD)
      }
    }
  })

  it('noms et présentations des projets affichés : lexique neutre respecté', () => {
    const lex = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[] }[] }
    const re = new RegExp(`(?<![\\p{L}\\p{N}_])(?:${lex.regles.flatMap((r) => r.termes).join('|')})(?![\\p{L}\\p{N}_])`, 'iu')
    const pj = JSON.parse(readFileSync(join(DONNEES, 'panorama', 'projets.json'), 'utf8')) as { projets: { nom: string; noms_publies: string[]; description: string | null }[] }
    for (const p of pj.projets) for (const t of [p.nom, ...p.noms_publies, p.description ?? '']) expect(t, p.nom).not.toMatch(re)
  })

  it('poids chargé par la page sous 1 Mo', () => {
    const poids = ['index.json', 'panorama/editions.json', 'panorama/projets.json', 'panorama/ministeres.json'].reduce((s, f) => s + statSync(join(DONNEES, f)).size, 0)
    expect(poids).toBeLessThan(1_000_000)
  })
})

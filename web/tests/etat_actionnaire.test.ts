// @vitest-environment happy-dom
// Écran « L’État actionnaire » (/explorer/etat-actionnaire) sur des fixtures qui sont des extraits réels de
// site/data/etat_actionnaire (tests/fixtures/data/etat_actionnaire) et de site/data/deficit.json.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { dateLongue, type Entites, type Flux, formeJuridique, type Index, montant, ordreEntites, REGLE_ENTITES, statutDe } from '../src/ecrans/etat_actionnaire'
import { attendreQue, monterPage, requetes } from './aide-dom'

const ROUTE = '#/explorer/etat-actionnaire'
const lire = <T>(chemin: string): T => JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'data', chemin), 'utf8')) as T
const idx = lire<Index>('etat_actionnaire/index.json')
const flux = lire<Flux>('etat_actionnaire/flux.json')
const ent = lire<Entites>('etat_actionnaire/entites.json')
const deficit = lire<{ etat: { annees: Record<string, { recettes_nettes_bg_md: number }> } }>('deficit.json')
const espace = (t: string | null | undefined) => (t ?? '').replace(/[\s  ]+/g, ' ').trim()
const nf1 = (x: number) => new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(x).replace(/[\s  ]+/g, ' ')

let main: HTMLElement
const ecran = async (fragment = ROUTE) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => espace(main.textContent)

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('L’État actionnaire', () => {
  it('route : parent « Explorer », picto et famille existants, titre et description dans les bornes', () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/etat-actionnaire')!
    expect(r.parent).toBe('/explorer')
    expect(r.voisins?.length).toBeGreaterThanOrEqual(1)
    for (const v of r.voisins ?? []) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    expect(r.description.length).toBeGreaterThanOrEqual(70)
    expect(r.description.length).toBeLessThanOrEqual(200)
    expect(`${r.titrePage} · Le billet découpé`.length).toBeLessThanOrEqual(100)
  })

  it('titre, fil d’Ariane, phrase d’introduction qui dit ce que la page montre et ne montre pas', async () => {
    await ecran()
    expect(main.querySelector('h1')?.textContent).toContain('L’État actionnaire')
    expect(Array.from(main.querySelectorAll('.fil-ariane a')).map((a) => a.textContent)).toEqual(['Accueil', 'Explorer', 'État actionnaire'])
    const chapeau = espace(main.querySelector('.chapeau')?.textContent)
    expect(chapeau).toContain('ce qu’il en reçoit (dividendes)')
    expect(chapeau).toContain('Elle ne porte aucune appréciation sur ces opérations')
    expect(main.querySelector('.erreur')).toBeNull()
    // titres hiérarchisés : un h1, puis des h2, des h3 seulement sous un h2
    expect(main.querySelectorAll('h1')).toHaveLength(1)
    const niveaux = Array.from(main.querySelectorAll('h1, h2, h3')).map((x) => Number(x.tagName[1]))
    for (let i = 1; i < niveaux.length; i++) expect(niveaux[i] - niveaux[i - 1]).toBeLessThanOrEqual(1)
  })

  it('chiffre clé : dividendes de 2025 et « sur 100 € » des recettes nettes du budget général, un seul surligneur', async () => {
    await ecran()
    const an = String(idx.chiffres_cles.annee)
    const div = flux.dividendes.total[an].execution_eur
    const base = deficit.etat.annees[`Exécution ${an}`].recettes_nettes_bg_md
    const surlignes = main.querySelectorAll('.surligne')
    expect(surlignes).toHaveLength(1)
    expect(espace(surlignes[0].textContent)).toBe(`${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(div / 1e9).replace(/[\s  ]+/g, ' ')} Md€`)
    const cle = surlignes[0].closest('[data-cle]')!
    expect(espace(cle.textContent)).toContain(`soit ${nf1((div / (base * 1e9)) * 100)} € sur 100 € des recettes nettes du budget général`)
    expect(cle.querySelector('.source')).not.toBeNull()
  })

  it('valeur des participations : série primaire de l’agence (approché) et bilan de l’État (tracé), jamais additionnés', async () => {
    await ecran()
    const t = texte()
    for (const p of idx.valeur_portefeuille.agence.serie) expect(t).toContain(dateLongue(p.date))
    expect(t).toContain('209,1 Md€')
    expect(t).toContain('394,5 Md€')
    expect(t).toContain('ne s’additionnent pas et ne se comparent pas terme à terme')
    // le 233 Md€ d'une source secondaire n'est repris nulle part : seules les valeurs des sources primaires s'affichent
    expect(t).not.toMatch(/233(,\d)?\s?Md€|233 milliards/)
    const barresValeur = main.querySelector('ul.barres[aria-label^="Valeur estimée du portefeuille"]')!
    expect(barresValeur.querySelectorAll('.statut-approche').length).toBe(idx.valeur_portefeuille.agence.serie.length)
    expect(main.querySelector('#valeur')?.tagName).toBe('H2')
    // les phrases citées mot pour mot, avec leur page
    const citations = Array.from(main.querySelectorAll('details q')).map((q) => espace(q.textContent))
    for (const p of idx.valeur_portefeuille.agence.serie) for (const c of p.citations) expect(citations).toContain(espace(c.texte))
    expect(t).toContain('Précision méthodologique : pour les sociétés non cotées')
  })

  it('chaque montant avec son statut et sa source : légende des trois statuts, badges, sources', async () => {
    await ecran()
    for (const s of ['Tracé', 'Approché', 'Non publié']) expect(main.querySelectorAll(`.badge`).length > 0 && texte().includes(s), s).toBe(true)
    expect(main.querySelectorAll('.legende-statuts li')).toHaveLength(3)
    expect(main.querySelectorAll('p.source').length).toBeGreaterThanOrEqual(6)
    expect(texte()).toContain("refus d'accès HTTP 403, non contourné")
    expect(espace(main.querySelector('.legende-statuts')?.textContent)).toContain('Approché : estimation publiée avec sa méthode')
  })

  it('entités : personnes morales vérifiées, ordre alphabétique écrit sous le tableau, absences jamais affichées comme 0', async () => {
    await ecran()
    const table = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.startsWith('Dividendes versés au budget général par entité'))!
    expect(table).toBeTruthy()
    for (const th of Array.from(table.querySelectorAll('thead th'))) expect(th.getAttribute('scope')).toBe('col')
    const lignes = Array.from(table.querySelectorAll('tbody tr'))
    expect(lignes).toHaveLength(ent.dividendes_par_ligne_d_execution.length)
    const attendu = ordreEntites(ent.dividendes_par_ligne_d_execution).map((l) => (l.entite ? l.entite.denomination : l.libelle_source))
    // Nom = texte avant le <br> (les sigles reliés au glossaire après le rendu découpent ce texte en plusieurs nœuds).
    const nomLigne = (th: Element) => {
      let t = ''
      for (const n of Array.from(th.childNodes)) {
        if (n.nodeName === 'BR') break
        t += n.textContent ?? ''
      }
      return espace(t)
    }
    expect(lignes.map((tr) => nomLigne(tr.querySelector('th')!))).toEqual(attendu.map(espace))
    expect(main.querySelector('[data-regle-ordre]')?.textContent).toBe(REGLE_ENTITES)
    for (const l of ent.dividendes_par_ligne_d_execution) if (l.entite) expect(Number(l.entite.categorie_juridique[0])).toBeGreaterThanOrEqual(2)
    // EDF n'a pas de ligne en 2023 : « – », pas « 0 € »
    const edf = lignes.find((tr) => tr.textContent?.includes('ELECTRICITE DE FRANCE'))!
    expect(edf.querySelectorAll('td.nombre')[0].textContent).toBe('–')
    expect(texte()).toContain('ce n’est pas un zéro')
    // rapprochements vérifiés : Bpifrance (établissement public) et TSA
    expect(texte()).toContain('« EPIC Bpifrance 100% », page 110')
    expect(texte()).toContain('« TSA 100% », page 110')
    expect(texte()).toContain('établissement public, SIREN 483790069')
    // aucune personne physique ni élu
    expect(texte()).not.toMatch(/\b(M\.|Mme|sénateur|député|rapporteur)\s/)
  })

  it('flux par année : dividendes, opérations en capital, cessions, compte, écarts entre sources non tranchés', async () => {
    await ecran()
    const t = texte()
    for (const titre of ['Ce que l’État reçoit : les dividendes', 'Ce que l’État apporte : les opérations en capital', 'Ce que l’État vend : les cessions', 'Écarts entre sources']) expect(Array.from(main.querySelectorAll('h2')).map((x) => x.textContent)).toContain(titre)
    expect(t).toContain(montant(flux.compte.depenses.programmes[0].par_annee['2025'].execution_eur))
    expect(t).toContain('L’exécution par nature d’opération n’est pas publiée')
    for (const e of flux.ecarts_entre_sources) expect(t).toContain(e.lecture)
    for (const c of Array.from(main.querySelectorAll('caption'))) expect(c.closest('table')).not.toBeNull()
    for (const th of Array.from(main.querySelectorAll('tbody th'))) expect(th.getAttribute('scope')).toBe('row')
    // série longue de l'agence : 2025 est une prévision (approché)
    expect(t).toContain('prévision au 30/08/2025')
  })

  it('neutralité : lexique partagé, pas de tiret long, pas de style en ligne, renvoi vers les prestations aux ménages', async () => {
    await ecran()
    const LEXIQUE = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; exceptions: string[] }
    const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
    let x = espace(document.body.textContent).replace(/[\w./:-]*\/[\w./-]+/g, ' ')
    for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
    for (const r of LEXIQUE.regles) expect(x, r.raison).not.toMatch(borne(r.termes.join('|')))
    expect(main.textContent).not.toContain('—')
    expect(Array.from(main.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l') && !el.hasAttribute('data-g') && !el.hasAttribute('data-f'))).toHaveLength(0)
    for (const t of Array.from(main.querySelectorAll('h1, h2, h3'))) expect(t.textContent ?? '').not.toMatch(/\b(gaspillage|seulement|énorme|opaque|scandale|trop)\b/i)
    expect(main.querySelector('a[href="#/explorer/secu"]')).not.toBeNull()
    expect(Array.from(main.querySelectorAll('.voir-aussi a')).map((a) => a.getAttribute('href'))).toEqual(['#/explorer/etat', '#/explorer/operateurs', '#/explorer'])
    for (const a of Array.from(main.querySelectorAll('a[href^="https://"]'))) expect(a.getAttribute('rel')).toBe('noopener noreferrer')
  })

  it('données absentes : état « en cours d’intégration », titre présent, aucune erreur', async () => {
    const { rendre } = await import('../src/ecrans/etat_actionnaire')
    const { viderCache } = await import('../src/donnees')
    viderCache()
    const vrai = globalThis.fetch
    globalThis.fetch = (async (u: string) => (String(u).includes('etat_actionnaire/') ? new Response('', { status: 404 }) : vrai(u))) as typeof fetch
    const z = document.createElement('div')
    await rendre(z)
    expect(z.querySelector('h1')?.textContent).toBe('L’État actionnaire')
    expect(z.textContent).toContain('Données en cours d’intégration')
    globalThis.fetch = vrai
    viderCache()
    await ecran()
    await attendreQue(() => !!main.querySelector('#valeur'))
  })

  it('outils : statut, forme juridique, montants, dates, ordre', () => {
    expect([statutDe('tracé'), statutDe('approché'), statutDe('non publié'), statutDe('prévision au 30/08/2025')]).toEqual(['trace', 'approche', 'nonpub', 'approche'])
    expect(['4120', '4160', '5599', '5710', '7490'].map(formeJuridique)).toEqual(['établissement public', 'institution publique', 'société anonyme', 'société par actions simplifiée', 'personne morale de droit public'])
    expect(espace(montant(0.75))).toBe('0,75 €')
    expect(espace(montant(6481573626.85))).toBe('6,5 Md€')
    expect(dateLongue('2025-06-30')).toBe('30 juin 2025')
    expect(dateLongue('2026-01-01')).toBe('1er janvier 2026')
    const e = (d: string | null, c: string) => ({ entite: d ? { siren: '1', denomination: d, categorie_juridique: '5599' } : null, code_execution: c })
    expect(ordreEntites([e(null, '211601'), e('ORANGE', '211688'), e('ÉLECTRICITÉ', '211631'), e('AIRBUS', '211700')]).map((x) => x.entite?.denomination ?? x.code_execution)).toEqual(['AIRBUS', 'ÉLECTRICITÉ', 'ORANGE', '211601'])
  })

  it('toutes les lectures de données sont relatives au site', () => {
    expect(requetes.some((u) => u.startsWith('data/etat_actionnaire/'))).toBe(true)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })
})

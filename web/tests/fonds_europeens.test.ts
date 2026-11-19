// @vitest-environment happy-dom
// Écran « Les fonds européens en France » (/explorer/fonds-europeens) sur des extraits réels de site/data/fonds_europeens
// (tests/fixtures/fonds_europeens/, servis avant les fixtures communes ; liste de Bretagne réduite à 60 opérations
// nommées) : chiffres lus dans les données, quatre grandeurs côte à côte sans addition ni solde, décidé au-dessus du
// prévu publié tel quel, couverture des listes régionales (7 programmes sur 51) et écarts avec la Commission,
// listes chargées à la demande, personnes morales seules nommées, domaines d'intervention traduits et libellé
// d'origine accessible, lien réciproque avec /explorer/ue, accessibilité, état propre quand les fichiers manquent.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { viderCache } from '../src/donnees'
import { DOMAINES_FR, EXPLICATIONS, filtrer, montant, traduireDomaine } from '../src/ecrans/fonds_europeens'
import type { Domaine, Index, Liste } from '../src/ecrans/fonds_europeens'
import G from '../src/glossaire.json'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { eurLisible, sur100 } from '../src/util'
import { attendreQue, choisirValeur, monterPage } from './aide-dom'

const RACINE = process.cwd()
const PROPRES = join(RACINE, 'tests', 'fixtures', 'fonds_europeens')
const COMMUNES = join(RACINE, 'tests', 'fixtures')
const PAGE = '#/explorer/fonds-europeens'
const lire = <T = any>(rel: string): T => JSON.parse(readFileSync(join(PROPRES, 'data', 'fonds_europeens', rel), 'utf8'))
const n = (t: string | null | undefined) => (t ?? '').replace(/\s+/g, ' ').trim()

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
  viderCache()
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => n(main.textContent)
const tableau = (debut: string, racine: ParentNode = main) => {
  const t = Array.from(racine.querySelectorAll('table')).find((x) => n(x.querySelector('caption')?.textContent).startsWith(debut))
  expect(t, `tableau « ${debut} »`).toBeDefined()
  return t as HTMLTableElement
}
const ligne = (t: HTMLTableElement, entete: string) =>
  Array.from(t.querySelectorAll('tbody tr, tfoot tr')).find((tr) => n(tr.querySelector('th')?.textContent).startsWith(entete)) as HTMLTableRowElement
const cellules = (tr: HTMLTableRowElement) => Array.from(tr.querySelectorAll('td')).map((td) => n(td.textContent))
const selectionner = (sel: string, valeur: string) => choisirValeur(main, sel.slice(1), valeur)

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu') as HTMLElement
})
afterEach(() => {
  absents = null
})

describe('écran fonds européens', () => {
  it('route : enfant de « Explorer », rubrique « Qui reçoit l’argent », famille Union européenne, voisins existants, titre et description sans sigle', () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/fonds-europeens')!
    expect(r.parent).toBe('/explorer')
    expect(r.theme).toBe('qui-recoit')
    expect(r.famille).toBe('ue')
    expect(r.picto).toBe('europe')
    expect(r.voisins).toContain('/explorer/ue')
    expect(r.voisins?.every((v) => ROUTES.some((x) => x.chemin === v))).toBe(true)
    expect(r.description.length).toBeGreaterThanOrEqual(70)
    expect(r.description.length).toBeLessThanOrEqual(200)
    expect(`${r.titre} ${r.titrePage} ${r.description} ${r.resume}`).not.toMatch(/\b(FEDER|FSE|FEADER|FTJ|IEJ|FEAMPA?|UE|PAC|FRR)\b/)
  })

  it('introduction, lien vers ce que la France verse, aucun solde calculé ; chiffre clé lu dans les données avec « sur 100 € », statut et source', async () => {
    await ecran()
    expect(n(main.querySelector('h1')?.textContent)).toBe('Les fonds européens en France')
    expect(main.querySelector('h1 .picto')).not.toBeNull()
    expect(main.querySelector('.fil-ariane [aria-current=page]')?.getAttribute('href')).toBe(PAGE)
    expect(texte()).toContain('Tu vois ici ce que l’Union européenne finance en France')
    expect(texte()).toContain('La page ne montre pas les aides de la politique agricole commune versées directement aux exploitants')
    expect(main.querySelector('a[href="#/explorer/ue"]')).not.toBeNull()
    expect(texte()).toContain('ne s’additionnent pas et ne se compensent pas : le site ne calcule aucun solde')
    expect(texte()).not.toMatch(/solde net/i)
    const idx = lire<Index>('index.json')
    const t21 = idx.totaux.find((t) => t.periode === '2021-2027')!.total
    const s = main.querySelectorAll('.surligne')
    expect(s).toHaveLength(1)
    expect(n(s[0].textContent)).toBe(n(eurLisible(t21.prevu_ue_eur!)))
    const cle = s[0].closest('[data-cle]')!
    const part = (t21.prevu_ue_eur! / t21.prevu_total_eur!) * 100
    expect(n(cle.textContent)).toContain(n(`Sur 100 € prévus par ces programmes, ${sur100(part)} viennent de l’Union et ${sur100(100 - part)} des financeurs français`))
    expect(Array.from(cle.querySelectorAll('.badge')).map((b) => b.textContent)).toEqual(['Tracé', 'Calculé par le site'])
    expect(n(cle.querySelector('.methode-calcul')?.textContent)).toContain('divisé par le total prévu')
    expect(n(cle.querySelector('.source')?.textContent)).toContain(idx.source)
    expect(main.querySelectorAll('.legende-statuts li').length).toBeGreaterThanOrEqual(3)
  })

  it('les fonds expliqués en langage courant, dont la facilité pour la reprise ; fonds hors périmètre publiés avec leur raison, hors totaux', async () => {
    await ecran()
    const idx = lire<Index>('index.json')
    const items = Array.from(main.querySelectorAll('ul.fe-fonds li')).map((li) => n(li.textContent))
    for (const f of idx.fonds) {
      expect(EXPLICATIONS[f.code], f.code).toBeTruthy()
      expect(items.some((x) => x.includes(n(EXPLICATIONS[f.code]))), f.code).toBe(true)
    }
    expect(items.some((x) => x.startsWith('Facilité pour la reprise et la résilience'))).toBe(true)
    expect(texte()).toContain('Les aides versées directement à chaque exploitant (paiements directs) ne sont pas reprises ici')
    const hors = tableau('Fonds hors du périmètre de la page')
    expect(hors.querySelectorAll('tbody tr')).toHaveLength(idx.perimetre.hors_perimetre.length)
    expect(n(hors.textContent)).not.toMatch(/\((AMIF|BMVI|ISF|FEAD)\)/)
  })

  it('par période : prévu, cofinancement, décidé, dépensé, payé côte à côte, lus dans index.json ; décidé au-dessus du prévu publié tel quel', async () => {
    await ecran()
    const idx = lire<Index>('index.json')
    const t14 = idx.totaux.find((t) => t.periode === '2014-2020')!
    const tab = tableau('Programmes 2014-2020 en France, par fonds')
    expect(Array.from(tab.querySelectorAll('thead th')).map((th) => n(th.textContent))).toEqual(['Fonds', 'Prévu par l’Union', 'Cofinancement national prévu', 'Décidé', 'Dépensé', 'Payé par l’Union'])
    expect(Array.from(tab.querySelectorAll('th[scope]')).length).toBe(tab.querySelectorAll('th').length)
    const b = t14.par_fonds.FEADER
    expect(cellules(ligne(tab, 'Fonds européen agricole pour le développement rural'))).toEqual(
      [b.prevu_ue_eur, b.prevu_national_eur, b.decide_eur, b.depense_eur, b.paye_ue_eur].map((x) => n(eurLisible(x!))),
    )
    expect(cellules(ligne(tab, 'Ensemble des fonds'))[0]).toBe(n(eurLisible(t14.total.prevu_ue_eur!)))
    // Décidé > prévu : phrase factuelle avec les deux montants publiés, sans interprétation.
    const decides = Array.from(main.querySelectorAll('ul.fe-decide li')).map((li) => n(li.textContent))
    expect(decides).toContain(
      n(`Fonds européen agricole pour le développement rural, 2014-2020 : le décidé publié (${eurLisible(b.decide_eur!)}) dépasse le prévu total (${eurLisible(b.prevu_total_eur!)}), de ${eurLisible(b.decide_eur! - b.prevu_total_eur!)}.`),
    )
    expect(texte()).toContain('Le décidé peut dépasser le prévu : la source le publie ainsi, sans en donner la raison')
    // 2021-2027 : cofinancement calculé, signalé « approché ».
    tableau('Programmes 2021-2027 en France, par fonds')
    expect(texte()).toContain('Pour 2021-2027, le cofinancement national Calculé par le site Méthode : total prévu moins la part de l’Union, pour le même programme et la même période de programmation')
    // Plan stratégique PAC : financements nationaux du plan à côté, sans addition.
    const pac = idx.feader_psp_2023_2027!
    expect(texte()).toContain(n(`Part de l’Union prévue : ${eurLisible(pac.prevu_ue_feader_eur!)}`))
    expect(texte()).toContain(n(`financement national obligatoire de ${eurLisible(pac.plan_strategique_pac!.financement_national_obligatoire_eur!)}`))
    expect(texte()).toContain('ils sont montrés à côté, sans addition')
  })

  it('null s’affiche « non publié », jamais 0', () => {
    expect(montant(null)).toBe('non publié')
    expect(montant(undefined)).toBe('non publié')
    expect(montant(0)).toBe(eurLisible(0))
  })

  it('par région : tableau dans l’ordre des données (code officiel), détail d’une région au choix, sans recharger la page', async () => {
    await ecran()
    const regions = lire('regions.json')
    const t = tableau('Fonds européens par région')
    expect(Array.from(t.querySelectorAll('tbody th')).map((th) => n(th.textContent))).toEqual(regions.regions.map((r: { nom: string }) => r.nom))
    const pdl = regions.regions.find((r: { code: string }) => r.code === '52')
    const p14 = pdl.periodes.find((p: { periode: string }) => p.periode === '2014-2020')
    expect(cellules(ligne(t, 'Pays de la Loire')).slice(0, 2)).toEqual([n(eurLisible(p14.total.prevu_ue_eur)), n(eurLisible(p14.total.paye_ue_eur))])
    expect(cellules(ligne(t, 'Saint-Martin'))[0]).toBe('sans programme')
    selectionner('#fe-region', '52')
    const detail = main.querySelector('#fe-region-detail')!
    expect(n(detail.querySelector('h3')?.textContent)).toBe('Pays de la Loire')
    const d14 = tableau('Pays de la Loire, programmes 2014-2020, par fonds', detail)
    expect(cellules(ligne(d14, 'Fonds européen de développement régional'))[0]).toBe(n(eurLisible(p14.par_fonds.FEDER.prevu_ue_eur)))
    tableau('Pays de la Loire, programmes 2014-2020, montants cumulés', detail)
    // Paramètre d'adresse : région affichée d'emblée.
    await ecran(`${PAGE}?region=53`)
    expect(n(main.querySelector('#fe-region-detail h3')?.textContent)).toBe('Bretagne')
  })

  it('par thème : objectifs en français, domaines d’intervention traduits par le site (signalé), libellé d’origine en anglais accessible', async () => {
    await ecran()
    const themes = lire('themes.json')
    const p21 = themes.periodes.find((p: { periode: string }) => p.periode === '2021-2027')
    const domaines: Domaine[] = p21.domaines_intervention
    // Chaque code publié a sa traduction.
    for (const d of domaines) expect(DOMAINES_FR[d.code], `${d.fonds} ${d.code} ${d.libelle_source}`).toBeTruthy()
    expect(traduireDomaine({ code: 'zzz', libelle_source: 'Other' })).toEqual({ texte: 'Other', traduit: false })
    const det = main.querySelector('#fe-domaines')!
    expect(n(det.querySelector('summary')?.textContent)).toContain('(libellés traduits par le site)')
    expect(n(det.textContent)).toContain('Le libellé en français est une traduction rédigée par le site ; le libellé d’origine est donné dessous.')
    const t = tableau('Domaines d’intervention des programmes 2021-2027', det)
    expect(t.querySelectorAll('tbody tr')).toHaveLength(domaines.length)
    expect(n(t.querySelector('thead th')?.textContent)).toBe('Domaine (traduction du site)')
    const solaire = domaines.find((d) => d.code === '048')!
    const tr = ligne(t, 'Énergie renouvelable : solaire')
    expect(n(tr.querySelector('[lang="en"]')?.textContent)).toBe(n(solaire.libelle_source))
    expect(n(tr.querySelector('th')?.textContent)).toContain('Libellé d’origine (anglais)')
    expect(t.querySelectorAll('tbody [lang="en"]')).toHaveLength(domaines.length)
    // Objectifs 2014-2020 : libellés français du fichier, sans le code anglais.
    const o14 = tableau('Programmes 2014-2020 en France, par objectif thématique')
    expect(o14.querySelectorAll('tbody tr')).toHaveLength(themes.periodes[0].themes.length)
    expect(n(o14.textContent)).not.toContain('Research & Innovation')
  })

  it('année par année : crédits, payé dans l’année (calcul signalé), cumuls ; année en cours marquée ; facilité pour la reprise (Eurostat)', async () => {
    await ecran()
    const a = lire('annees.json')
    const p = a.periodes.find((x: { periode: string }) => x.periode === '2014-2020')
    const t = tableau('Programmes 2014-2020 : crédits prévus par l’Union')
    const i = p.paiements_ue.annees.indexOf(2016)
    expect(cellules(ligne(t, '2016')).slice(1, 3)).toEqual([n(eurLisible(p.paiements_ue.annuel_total_eur[i])), n(eurLisible(p.paiements_ue.cumul_total_eur[i]))])
    expect(n(ligne(t, String(p.paiements_ue.annee_partielle)).querySelector('th')?.textContent)).toContain('(en cours)')
    expect(texte()).toContain('Le payé dans l’année est la différence entre deux cumuls publiés')
    const frr = lire('frr.json')
    const f = tableau('Facilité pour la reprise et la résilience : fonds reçus')
    expect(cellules(ligne(f, '2023'))[0]).toBe(n(eurLisible(frr.fonds_recus.total_eur[frr.annees.indexOf(2023)])))
    expect(texte()).toContain(n(`${eurLisible(frr.fonds_recus.cumul_eur)} reçus au total Calculé par le site Méthode : somme des montants reçus chaque année`))
    expect(texte()).toContain('pas par le prélèvement sur recettes')
  })

  it('listes d’opérations : couverture 7 programmes sur 51 dite ; aucune liste chargée avant le choix ; personnes morales seules nommées, le reste agrégé ; écarts avec la Commission', async () => {
    requetes.length = 0
    await ecran()
    const ops = lire('operations.json')
    expect(texte()).toContain(`elles couvrent ${ops.couverture.programmes_couverts.length} programmes régionaux sur ${ops.couverture.programmes_regionaux}`)
    expect(ops.couverture.programmes_couverts.length).toBe(7)
    expect(ops.couverture.programmes_regionaux).toBe(51)
    expect(tableau('Listes d’opérations reprises').querySelectorAll('tbody tr')).toHaveLength(6)
    expect(requetes.some((u) => u.includes('fonds_europeens/operations/'))).toBe(false)
    selectionner('#fe-ops-liste', 'iledefrance_2127')
    await attendreQue(() => n(main.querySelector('#fe-ops-statut')?.textContent).includes('trouvée'))
    expect(requetes.filter((u) => u.includes('fonds_europeens/operations/'))).toEqual(['data/fonds_europeens/operations/iledefrance_2127.json'])
    const l = lire<Liste>('operations/iledefrance_2127.json')
    const zone = main.querySelector('#fe-ops-resultats')!
    // Contribution de l'Union calculée : badge « Calculé par le site » et méthode écrite.
    expect(n(zone.textContent)).toContain('coût total de l’opération multiplié par le taux de cofinancement publié')
    expect(Array.from(zone.querySelectorAll('.badge')).map((b) => b.textContent)).toContain('Calculé par le site')
    // Écarts avec la Commission.
    const cmp = tableau('Région Île-de-France : coût des opérations de la liste et décidé transmis', zone)
    expect(cmp.querySelectorAll('tbody tr')).toHaveLength(l.comparaison_commission.length)
    expect(n(zone.textContent)).toContain(n(l.comparaison_commission[0].lecture_ecart))
    // Agrégats : autant d'opérations que les non nommées publiées.
    const ag = tableau('Région Île-de-France : opérations non nommées, agrégées', zone)
    const nbAgreges = Array.from(ag.querySelectorAll('tbody tr')).reduce((s, tr) => s + Number(cellules(tr as HTMLTableRowElement)[1].replace(/\D/g, '')), 0)
    expect(nbAgreges).toBe(l.non_nommes.reduce((s, x) => s + x.nombre, 0))
    // Opérations nommées : uniquement des dénominations de la liste (personnes morales, catégorie juridique 2 à 9), ordre alphabétique, 25 par page.
    const iDen = l.colonnes.indexOf('denomination')
    const iCat = l.colonnes.indexOf('categorie_juridique')
    expect(l.operations.every((o) => /^[2-9]/.test(String(o[iCat])))).toBe(true)
    const noms = new Set(l.operations.map((o) => String(o[iDen])))
    const res = tableau('Région Île-de-France : opérations nommées', zone)
    const affiches = Array.from(res.querySelectorAll('tbody th')).map((th) => n(th.textContent))
    expect(affiches).toHaveLength(25)
    for (const x of affiches) expect(noms.has(x), x).toBe(true)
    expect(affiches).toEqual(filtrer(l, '').slice(0, 25).map((o) => n(String(o.denomination))))
    zone.querySelector<HTMLButtonElement>('#fe-ops-plus')!.click()
    await attendreQue(() => (main.querySelector('#fe-ops-resultats table:last-of-type tbody')?.children.length ?? 0) > 25 || tableau('Région Île-de-France : opérations nommées', main).querySelectorAll('tbody tr').length > 25)
    expect(document.activeElement?.closest('tr')?.hasAttribute('data-premier')).toBe(true)
    // Recherche plein texte (accents et casse ignorés).
    const q = main.querySelector<HTMLInputElement>('#fe-ops-q')!
    q.value = 'campus cyber'
    q.dispatchEvent(new Event('input', { bubbles: true }))
    await attendreQue(() => n(main.querySelector('#fe-ops-resultats h4')?.textContent).includes('campus cyber'))
    const trouves = Array.from(tableau('Région Île-de-France : opérations nommées', main).querySelectorAll('tbody th')).map((th) => n(th.textContent))
    expect(trouves.length).toBeGreaterThan(0)
    expect(trouves.every((x) => x === 'CAMPUS CYBER')).toBe(true)
  })

  it('listes : adresse avec ?liste= et ?q= charge la liste demandée et filtre ; raisons d’agrégation en langage courant', async () => {
    requetes.length = 0
    await ecran(`${PAGE}?liste=bretagne&q=lorient`)
    await attendreQue(() => n(main.querySelector('#fe-ops-statut')?.textContent).includes('trouvée'))
    expect(requetes.filter((u) => u.includes('fonds_europeens/operations/'))).toEqual(['data/fonds_europeens/operations/bretagne.json'])
    const res = Array.from(tableau('Région Bretagne : opérations nommées contenant « lorient »').querySelectorAll('tbody th')).map((th) => n(th.textContent))
    expect(res.length).toBeGreaterThan(0)
    expect(res.every((x) => /LORIENT/.test(x))).toBe(true)
    expect(n(main.querySelector('#fe-ops-resultats')?.textContent)).toContain('Nom pouvant désigner une personne : jamais rapproché')
  })

  it('écarts entre sources : tous publiés, côte à côte, sans être tranchés', async () => {
    await ecran()
    const idx = lire<Index>('index.json')
    const t = tableau('Écarts publiés entre les jeux de données')
    expect(t.querySelectorAll('tbody tr')).toHaveLength(idx.ecarts.length)
    expect(texte()).toContain('Aucun n’est retenu contre l’autre')
    expect(texte()).toContain('Sources inaccessibles')
    expect(texte()).toContain(idx.sources_inaccessibles[0].source)
  })

  it('accessibilité et neutralité : tableaux légendés, en-têtes avec scope, aucun tiret long, aucun style en ligne, aucun terme évaluatif, aucun appel externe', async () => {
    requetes.length = 0
    await ecran()
    for (const t of Array.from(main.querySelectorAll('table'))) {
      expect(n(t.querySelector('caption')?.textContent)).not.toBe('')
      for (const th of Array.from(t.querySelectorAll('th'))) expect(th.getAttribute('scope'), n(th.textContent).slice(0, 40)).toMatch(/^(col|row)$/)
    }
    expect(main.textContent).not.toContain('—')
    expect(Array.from(main.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l'))).toHaveLength(0)
    const lexique = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[] }[] }
    for (const r of lexique.regles) expect(texte()).not.toMatch(new RegExp(`(?<![\\p{L}\\p{N}])(?:${r.termes.join('|')})(?![\\p{L}\\p{N}])`, 'iu'))
    expect(requetes.every((u) => u.startsWith('data/'))).toBe(true)
    // Titres hiérarchisés : un h1, puis des h2.
    expect(main.querySelectorAll('h1')).toHaveLength(1)
    expect(main.querySelectorAll('h2').length).toBeGreaterThanOrEqual(8)
  })

  it('sigles : tout sigle affiché (hors libellés d’origine en anglais) a son entrée dans le glossaire', async () => {
    await ecran()
    const graphies = new Set(G.termes.flatMap((t: { sigle?: string; variantes?: string[] }) => [t.sigle, ...(t.variantes ?? [])].filter(Boolean)))
    const pasDesSigles = new Set((G.pas_des_sigles ?? []).map((x: { mot: string }) => x.mot))
    const clone = main.cloneNode(true) as HTMLElement
    clone.querySelectorAll('[lang="en"], .fil-ariane').forEach((el) => el.remove())
    const t = (clone.textContent ?? '').replace(/https?:\/\/\S+/g, ' ')
    const sigles = new Set([...t.matchAll(/(?<![\p{L}\p{N}_-])(\p{Lu}{3,})(?![\p{L}\p{N}_-])/gu)].map((m) => m[1]))
    const manquants = [...sigles].filter((s) => !graphies.has(s) && !pasDesSigles.has(s))
    expect(manquants).toEqual([])
    for (const s of ['FEDER', 'FSE', 'FEADER', 'FTJ', 'IEJ', 'FEAMP', 'FEAMPA']) expect(graphies.has(s), s).toBe(true)
  })

  it('fichiers absents : page propre (titre, mention, sortie vers la page Union européenne), aucune erreur', async () => {
    absents = /fonds_europeens\//
    await ecran()
    expect(n(main.querySelector('h1')?.textContent)).toBe('Les fonds européens en France')
    expect(main.querySelector('.erreur')).toBeNull()
    expect(texte()).toContain('Données en cours d’intégration.')
    expect(main.querySelector('a[href="#/explorer/ue"]')).not.toBeNull()
    // Index présent mais listes absentes : le reste de la page s'affiche.
    absents = /fonds_europeens\/(operations|regions)/
    await ecran()
    expect(main.querySelector('.erreur')).toBeNull()
    expect(texte()).toContain('Listes d’opérations non disponibles.')
    expect(texte()).toContain('Répartition par région non disponible.')
    tableau('Programmes 2014-2020 en France, par fonds')
  })

  it('page « La France et l’Union européenne » : lien vers les fonds européens', async () => {
    await ecran('#/explorer/ue')
    const a = main.querySelector('a[href="#/explorer/fonds-europeens"]')
    expect(a).not.toBeNull()
    expect(n(a?.textContent)).toContain('Ce que l’Union européenne finance en France')
  })
})

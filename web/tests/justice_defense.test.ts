// @vitest-environment happy-dom
// Écran « Justice et défense » (/explorer/justice-defense) sur des extraits réels de site/data :
// tests/fixtures/data/justice_defense/ (fichiers de l'axe, montant calculé compris pour vérifier qu'il n'est jamais affiché)
// et tests/fixtures/justice_defense/data/ (sous-arbres de la mission Défense, effectifs, données d'exécution).
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher, titreDocument } from '../src/routeur'
import { viderCache } from '../src/donnees'
import { entier, eur, md, pct, sur100 } from '../src/util'
import { CALCUL, dateLongue, montant, nettoyer, nomRegion, sansCalcul, variation } from '../src/ecrans/justice_defense'
import { monterPage } from './aide-dom'

const CHEMIN = '/explorer/justice-defense'
const FIXTURES = join(process.cwd(), 'tests', 'fixtures')
const PRIVE = join(FIXTURES, 'justice_defense')
/** complet : fichiers de l'axe et données d'autres axes ; commun : fixtures partagées seulement (comme tests/ecrans.test.ts) ; vide : sans les fichiers de l'axe. */
type Mode = 'complet' | 'commun' | 'vide'
let mode: Mode = 'complet'
const requetes: string[] = []

function servir() {
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const chemin = u.split('?')[0]
    if (mode === 'vide' && chemin.startsWith('data/justice_defense/')) return new Response('introuvable', { status: 404 })
    const f = (mode === 'complet' ? [join(PRIVE, chemin), join(FIXTURES, chemin)] : [join(FIXTURES, chemin)]).find((c) => existsSync(c))
    if (!f) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}

const lire = (racine: string, rel: string) => JSON.parse(readFileSync(join(racine, rel), 'utf8'))
const budget = lire(FIXTURES, 'data/justice_defense/budget_justice.json')
const prisons = lire(FIXTURES, 'data/justice_defense/prisons.json')
const armement = lire(FIXTURES, 'data/justice_defense/armement.json')
const index = lire(FIXTURES, 'data/justice_defense/index.json')
const racine = lire(FIXTURES, 'data/arbre/racine.json')
const mission = (nom: string) => racine.enfants.flatMap((p: any) => p.enfants ?? []).find((x: any) => x.niveau === 'mission' && x.nom === nom)
const numero = (id: string) => /(\d{3})$/.exec(id)![1]

const norm = (s: string) => s.replace(/[\s  ]+/g, ' ').trim()
const nf = (d: number) => (x: number) => norm(new Intl.NumberFormat('fr-FR', { minimumFractionDigits: d, maximumFractionDigits: d }).format(x))
const fr1 = nf(1)
const fr2 = nf(2)

let main: HTMLElement
const ecran = async (m: Mode = 'complet') => {
  mode = m
  viderCache()
  location.hash = `#${CHEMIN}`
  await afficher(ROUTES, main, `#${CHEMIN}`)
  return main
}
const texte = () => norm(main.textContent ?? '')
const section = (id: string) => main.querySelector(`#${id}`)!.closest('section') as HTMLElement

// Lexique neutre (charte docs/NEUTRALITE.md, règle 2) : même lecture que tests/ecrans.test.ts, bornes de mot Unicode.
const LEXIQUE = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function verifier(x0: string, ou: string) {
  let x = x0.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
}
function lexiqueNeutre(ou: string) {
  verifier(main.textContent ?? '', `${ou} (texte)`)
  for (const el of Array.from(main.querySelectorAll('[aria-label], [title], [alt]'))) verifier(['aria-label', 'title', 'alt'].map((a) => el.getAttribute(a) ?? '').join(' '), `${ou} (attribut)`)
  expect(main.textContent, ou).not.toContain('\u2014')
}

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu') as HTMLElement
})
beforeEach(() => {
  requetes.length = 0
})

describe('justice et défense', () => {
  it('route : sous Explorer, famille et picto existants, voisins existants, titre et description propres', () => {
    const r = ROUTES.find((x) => x.chemin === CHEMIN)
    expect(r).toBeTruthy()
    expect(r!.parent).toBe('/explorer')
    expect(r!.famille).toBe('etat')
    expect(r!.picto).toBe('justice')
    expect(r!.voisins?.length).toBeGreaterThan(0)
    for (const v of r!.voisins ?? []) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    expect(r!.description.length).toBeGreaterThanOrEqual(70)
    expect(r!.description.length).toBeLessThanOrEqual(200)
    expect(titreDocument(r!).length).toBeLessThanOrEqual(100)
    expect(ROUTES.filter((x) => x.titre === r!.titre).length).toBe(1)
    expect(ROUTES.filter((x) => x.description === r!.description).length).toBe(1)
  })

  it('outils : dates, variations, régions, textes du pipeline nettoyés', () => {
    expect(dateLongue('2026-09-01')).toBe('1er septembre 2026')
    expect(dateLongue('2026-11-17T19:42:09+00:00')).toBe('17 novembre 2026')
    expect(norm(variation(11826.8, 12380.3))).toBe('+4,7 %')
    expect(norm(variation(12875.8, 11701.0))).toBe('−9,1 %')
    expect(norm(montant(12380.3))).toBe('12,38 Md€')
    expect(norm(montant(704))).toBe('704,0 M€')
    expect(nomRegion('ASIE DU SUD-EST')).toBe('Asie du Sud-Est')
    expect(nomRegion('PROCHE ET MOYEN-ORIENT')).toBe('Proche et Moyen-Orient')
    expect(nomRegion('AMÉRIQUE CENTRALE ET CARAÏBES')).toBe('Amérique centrale et Caraïbes')
    expect(nomRegion('UNION EUROPÉENNE')).toBe('Union européenne')
    expect(nomRegion('Multi-pays')).toBe('Multi-pays')
    expect(nettoyer('mois non repris (listés dans `couverture.mois_absents`) ; fin')).toBe('mois non repris ; fin')
    // Source des prisons : le segment qui renvoie à la dépense du programme 107 (montant calculé) est retiré.
    expect(sansCalcul(prisons.source)).not.toMatch(CALCUL)
    expect(sansCalcul(prisons.source)).toContain('Statistique mensuelle de la population écrouée')
  })

  it('sur 100 € dépensés par l’État : billet, un seul surligneur, parts lues dans l’arbre', async () => {
    await ecran()
    expect(main.querySelector('h1')?.textContent?.trim()).toBe('Justice et défense')
    expect(main.querySelector('.erreur')).toBeNull()
    const j = mission('Justice')
    const d = mission('Défense')
    const s = (x: number) => (x / racine.md) * 100
    expect(main.querySelector('.billet svg')).not.toBeNull()
    const surlignes = main.querySelectorAll('.surligne')
    expect(surlignes.length).toBe(1)
    expect(norm(surlignes[0].textContent ?? '')).toBe(norm(sur100(s(j.md + d.md))))
    expect(surlignes[0].closest('[data-cle]')?.textContent).toMatch(/sur 100 €/i)
    expect(texte()).toContain(`${norm(sur100(s(d.md)))} à la défense (${norm(md(d.md))})`)
    expect(texte()).toContain(`${norm(sur100(s(j.md)))} à la justice (${norm(md(j.md))})`)
    // Les autres missions du grand poste (police, gendarmerie...) sont nommées et dites non comptées.
    expect(texte()).toContain('la mission « Sécurités »')
    expect(texte()).toContain('ne sont pas comptées ici')
    // Équivalent texte du billet.
    expect(main.querySelector('.billet-tableau table caption')?.textContent).toMatch(/Sur 100 € dépensés par l’État en 2024/)
  })

  it('justice : chiffres clés datés, programmes dans l’ordre publié, chaque programme ouvre sa page, statut et source', async () => {
    await ecran()
    const sec = section('jd-titre-justice')
    const t = norm(sec.textContent ?? '')
    const cp = [...budget.budget.credits_paiement].sort((a: any, b: any) => a.annee - b.annee)
    const dernier = cp[cp.length - 1]
    expect(t).toContain(`${norm(montant(dernier.meur))}budget de la justice en ${dernier.annee}`)
    expect(t).toContain(`${norm(variation(cp[cp.length - 2].meur, dernier.meur))} par rapport à ${cp[cp.length - 2].annee}`)
    const liens = Array.from(sec.querySelectorAll('ul.barres a')).map((a) => a.getAttribute('href'))
    expect(liens).toEqual(budget.budget.programmes.map((p: any) => `#/beneficiaires/programme?p=${p.programme}`))
    expect(sec.querySelector('[data-regle-ordre]')?.textContent).toBe(budget.budget.ordre)
    // Chaque barre porte son statut, et le bloc sa source.
    expect(sec.querySelectorAll('ul.barres .badge').length).toBe(budget.budget.programmes.length)
    expect(t).toContain('Les chiffres clés de la Justice, édition 2026')
    // Frais de justice et aide juridictionnelle, par année ; versements aux avocats : autre source, non additionnée.
    for (const x of budget.frais_de_justice.total) expect(t).toContain(fr1(x.meur))
    for (const x of budget.aide_juridictionnelle.depenses_effectives) expect(t).toContain(fr1(x.meur))
    expect(t).toContain('ne s’additionnent pas')
    // Aucun sigle laissé seul : CARPA est développé.
    expect(t).toContain('caisses des règlements pécuniaires des avocats (CARPA)')
  })

  it('le montant calculé par journée de détention et par établissement n’est jamais affiché', async () => {
    await ecran()
    // La fixture contient bien le calcul du pipeline : c'est ce qui rend le test probant.
    expect(prisons.montant_calcule.montant_par_journee_eur).toBe(169.8)
    expect(prisons.etablissements.some((e: any) => e.montant_calcule_eur > 0)).toBe(true)
    const t = texte()
    const html = main.innerHTML
    // 169,8 est aussi une densité publiée (un établissement à 169,8 %) : c'est le montant en euros qui ne doit jamais paraître.
    expect(t).not.toMatch(/169[,.]80?\s?(€|euros?)/)
    expect(t).not.toContain('169,80')
    for (const motif of ['montant_calcule', 'calculé par le site', 'calcul du site']) {
      expect(t, motif).not.toContain(motif)
      expect(html, motif).not.toContain(motif)
    }
    for (const e of prisons.etablissements.filter((x: any) => x.montant_calcule_eur > 0)) {
      expect(t).not.toContain(norm(eur(e.montant_calcule_eur)))
      expect(t).not.toContain(norm(entier(e.montant_calcule_eur)))
    }
    expect(t).not.toContain(norm(entier(prisons.controles.somme_montants_calcules_eur)))
    // Aucune colonne de montant dans le tableau des établissements, et la page dit pourquoi elle n'affiche pas de montant par journée.
    const entetes = Array.from(section('jd-titre-prisons').querySelectorAll('thead th')).map((th) => th.textContent ?? '')
    expect(entetes.some((x) => /montant|€/i.test(x))).toBe(false)
    expect(t).toContain('Montant par journée de détention : aucun ne figure parmi les indicateurs publiés')
    expect(t).not.toMatch(/par journée[^.]*\d/)
  })

  it('prisons : situation nationale datée, 1er janvier de chaque année, mois non repris, lignes par direction, densité absente jamais 0', async () => {
    await ecran()
    const sec = section('jd-titre-prisons')
    const t = norm(sec.textContent ?? '')
    const n = prisons.national
    expect(t).toContain(`Au ${dateLongue(n.date)}, ${norm(entier(n.detenus))} personnes étaient détenues pour ${norm(entier(n.capacite_operationnelle))} places`)
    expect(t).toContain(`densité carcérale publiée : ${norm(pct(n.densite_pct))}`)
    const tables = Array.from(sec.querySelectorAll('table'))
    const annuel = tables.find((x) => x.caption?.textContent?.startsWith('Places opérationnelles, personnes détenues et densité carcérale'))!
    const lignes = Array.from(annuel.querySelectorAll('tbody tr')).map((tr) => norm(tr.textContent ?? ''))
    for (const p of prisons.serie_nationale.filter((x: any) => x.date.endsWith('-01-01')))
      expect(lignes.some((l) => l.startsWith(dateLongue(p.date)) && l.includes(norm(entier(p.detenus)))), p.date).toBe(true)
    for (const d of prisons.couverture.mois_absents.filter((x: string) => x.endsWith('-01-01')))
      expect(lignes.find((l) => l.startsWith(dateLongue(d))), d).toContain('non repris ici')
    // Détail par établissement : toutes les lignes publiées, groupées par direction, dans l'ordre publié.
    const detail = tables.find((x) => x.caption?.textContent?.includes('par établissement'))!
    const groupes = Array.from(detail.querySelectorAll('tbody'))
    expect(groupes.length).toBe(new Set(prisons.etablissements.map((e: any) => e.disp)).size)
    const rangs = Array.from(detail.querySelectorAll('tbody tr')).filter((tr) => tr.querySelector('th[scope=row]'))
    expect(rangs.length).toBe(prisons.etablissements.length)
    expect(rangs.map((tr) => tr.querySelector('th')!.textContent)).toEqual(prisons.etablissements.map((e: any) => e.etablissement))
    const sansDensite = prisons.etablissements.findIndex((e: any) => e.densite_pct === null)
    expect(sansDensite).toBeGreaterThanOrEqual(0)
    expect(rangs[sansDensite].lastElementChild!.textContent).toBe('non publiée')
    expect(sec.querySelector('[data-regle-ordre]')?.textContent).toBe(prisons.ordre.regle)
    // Totaux de direction et sommes des lignes : les deux valeurs, sans trancher.
    for (const e of prisons.controles.ecarts_totaux_directions) expect(t).toContain(e.disp)
    expect(t).toContain('Les deux valeurs sont reprises telles quelles')
  })

  it('défense : programmes par montant décroissant, opérations extérieures lues dans le détail des actions', async () => {
    await ecran()
    const sec = section('jd-titre-defense')
    const t = norm(sec.textContent ?? '')
    const d = mission('Défense')
    const progs = [...d.enfants].sort((a: any, b: any) => b.md - a.md)
    const liens = Array.from(sec.querySelectorAll('ul.barres a')).map((a) => decodeURIComponent((a.getAttribute('href') ?? '').replace(/\+/g, ' ')))
    expect(liens).toEqual(progs.map((p: any) => `#/explorer/etat/detail?m=execution2024&id=${p.id}`))
    expect(t).toContain(`la mission Défense a dépensé ${norm(md(d.md))}`)
    // Surcoûts des opérations : toutes les actions publiées, y compris la part de personnel portée par un autre programme, et leur ensemble.
    const ops = d.enfants
      .flatMap((p: any) => lire(PRIVE, `data/${p.fichier}`).enfants)
      .filter((a: any) => /surco[uû]ts liés aux opérations/i.test(a.nom))
    expect(ops.length).toBe(3)
    expect(ops.some((a: any) => /extérieures/.test(a.nom)) && ops.some((a: any) => /Personnel/.test(a.nom))).toBe(true)
    const lignes = Array.from(sec.querySelectorAll('ul.lignes li')).map((li) => norm(li.textContent ?? ''))
    expect(lignes.length).toBe(ops.length)
    for (const a of ops) expect(lignes.some((l) => l.startsWith(`« ${norm(a.nom)} »${norm(md(a.md))}`)), a.nom).toBe(true)
    expect(t).toContain(`Ensemble de ces lignes : ${norm(md(ops.reduce((x: number, a: any) => x + a.md, 0)))}`)
    expect(t).toContain('sans être répartie')
    expect(t).toContain('Équipement des forces')
  })

  it('emplois : programmes publiés, total par mission, défense 2025 non publiée en motif hachuré', async () => {
    await ecran()
    const sec = section('jd-titre-effectifs')
    const t = norm(sec.textContent ?? '')
    const justice = mission('Justice').enfants.map((p: any) => numero(p.id)).filter((n: string) => existsSync(join(PRIVE, 'data', 'effectifs', `${n}.json`)))
    const etpt = justice.map((n: string) => lire(PRIVE, `data/effectifs/${n}.json`).etpt as number)
    for (const x of etpt) expect(t).toContain(norm(entier(Math.round(x))))
    expect(t).toContain(`Ensemble des programmes de la mission Justice${norm(entier(Math.round(etpt.reduce((a: number, b: number) => a + b, 0))))}`)
    expect(t).toContain(norm(entier(Math.round(lire(PRIVE, 'data/effectifs/212.json').etpt))))
    expect(sec.querySelector('table caption')?.textContent).toContain('budget voté pour 2023 (loi de finances initiale)')
    const np = sec.querySelector('.absent')!
    expect(np.querySelector('.motif-nonpub')).not.toBeNull()
    expect(norm(np.textContent ?? '')).toContain(`constat du ${dateLongue(index.effectifs_defense.constat_le)}`)
  })

  it('évolution : sommes par mission égales aux données d’exécution, années sans données dites non publiées, écarts entre publications montrés', async () => {
    await ecran()
    const sec = section('jd-titre-evolution')
    const t = norm(sec.textContent ?? '')
    const somme = (nom: string, an: number) =>
      mission(nom)
        .enfants.map((p: any) => lire(PRIVE, `data/realisations/${numero(p.id)}.json`).prevu_depense.annees.find((x: any) => x.annee === an)?.depense_constatee_eur)
        .reduce((a: number, b: number | null) => a + (b ?? NaN), 0)
    const table = sec.querySelector('table')!
    const ligne = (an: number) => Array.from(table.querySelectorAll('tbody tr')).find((tr) => tr.querySelector('th')?.textContent === String(an))!
    for (const an of [2025, 2024, 2019]) {
      const cellules = Array.from(ligne(an).querySelectorAll('td')).map((td) => norm(td.textContent ?? ''))
      expect(cellules).toEqual([`${fr2(somme('Justice', an) / 1e9)} Md€`, `${fr2(somme('Défense', an) / 1e9)} Md€`])
    }
    // Années sans données d'exécution publiées : motif hachuré et phrase, jamais 0.
    expect(ligne(2015).querySelector('.motif-nonpub')).not.toBeNull()
    expect(norm(ligne(2015).textContent ?? '')).not.toMatch(/\b0,00\b/)
    expect(t).toContain('aucune donnée d’exécution par programme n’est publiée en données ouvertes pour 2015, 2016, 2017 et 2021')
    // Un programme sans montant une année : la somme n'est pas calculée.
    expect(norm(ligne(2010).querySelector('td')!.textContent ?? '')).toBe('somme non calculée : programme 335 sans montant publié')
    // Même année, plusieurs publications : chaque valeur est montrée avec son écart.
    const lignes = Array.from(sec.querySelectorAll('ul.lignes li')).map((li) => norm(li.textContent ?? ''))
    const justice2024 = lignes.find((l) => l.startsWith('Mission Justice, 2024'))!
    const arbre = mission('Justice').md * 1000
    const ck = budget.budget.credits_paiement.find((x: any) => x.annee === 2024).meur
    expect(justice2024).toContain(`${fr1(ck)} M€ (chiffres clés de la Justice)`)
    expect(justice2024).toContain(`${fr1(arbre)} M€ (arbre du budget de l’État`)
    expect(justice2024).toContain(`écart maximal de ${fr1(Math.max(ck, somme('Justice', 2024) / 1e6, arbre) - Math.min(ck, somme('Justice', 2024) / 1e6, arbre))} M€`)
    expect(lignes.some((l) => l.startsWith('Mission Défense, 2024'))).toBe(true)
    const e = budget.ecarts[0]
    expect(lignes.find((l) => l.toLowerCase().startsWith(e.objet.toLowerCase()))).toContain('même montant')
    // Sortie vers chaque programme.
    expect(sec.querySelectorAll('a[href^="#/decisions/realisations?p="]').length).toBe(10)
  })

  it('armement : totaux publiés par année, trois mesures non additionnées, régions dans l’ordre du rapport', async () => {
    await ecran()
    const sec = section('jd-titre-armement')
    const t = norm(sec.textContent ?? '')
    expect(t).toContain('Ce ne sont pas des dépenses de l’État')
    const i = armement.prises_de_commandes.annees.indexOf(2024)
    const ligne = Array.from(sec.querySelectorAll('table')[0].querySelectorAll('tbody tr')).find((tr) => tr.querySelector('th')?.textContent === '2024')!
    expect(Array.from(ligne.querySelectorAll('td')).map((td) => norm(td.textContent ?? ''))).toEqual([
      fr1(armement.prises_de_commandes.total_general.valeurs[i]),
      fr1(armement.livraisons.total_general.valeurs[i]),
      norm(entier(armement.licences.total_general.valeurs[i])),
    ])
    expect(t).toContain(armement.avertissement)
    const regions = Array.from(sec.querySelectorAll('details table')[0].querySelectorAll('tbody th')).map((th) => th.textContent)
    expect(regions).toEqual([...armement.prises_de_commandes.regions.map((r: any) => nomRegion(r.region)), ...armement.prises_de_commandes.hors_region.map((r: any) => r.pays)])
  })

  it('sources : documents de la page seulement, licence et date de collecte, limites sans le montant calculé', async () => {
    await ecran()
    const sec = section('jd-titre-sources')
    const t = norm(sec.textContent ?? '')
    for (const s of index.sources) {
      if (['chiffres_cles', 'population_ecrouee', 'effectifs_defense', 'armement'].includes(s.id)) expect(t).toContain(s.titre)
      else expect(t).not.toContain(s.titre)
    }
    for (const a of Array.from(sec.querySelectorAll('a[href^="https://"]'))) expect(a.getAttribute('rel')).toBe('noopener noreferrer')
    expect(t).not.toContain('calcul du site')
    // Textes du pipeline rendus lisibles : ni accent grave, ni nom de fichier interne, ni « ce module ».
    expect(t).not.toContain('`')
    expect(t).not.toMatch(/\.json\b|ce module/)
  })

  it('accessibilité et neutralité : titres, tableaux nommés et défilants au clavier, lexique neutre, ni style en ligne ni tiret long', async () => {
    await ecran()
    expect(main.querySelectorAll('h1').length).toBe(1)
    expect(main.querySelector('nav[aria-label="Fil d\'Ariane"] [aria-current=page]')?.getAttribute('href')).toBe(`#${CHEMIN}`)
    for (const s of Array.from(main.querySelectorAll('section[aria-labelledby]'))) expect(main.querySelector(`#${s.getAttribute('aria-labelledby')}`), s.getAttribute('aria-labelledby')!).not.toBeNull()
    for (const table of Array.from(main.querySelectorAll('table'))) {
      expect(table.querySelector('caption')?.textContent?.trim(), table.outerHTML.slice(0, 80)).toBeTruthy()
      expect(table.querySelectorAll('thead th:not([scope])').length).toBe(0)
      expect(table.querySelectorAll('tbody th:not([scope])').length).toBe(0)
    }
    for (const z of Array.from(main.querySelectorAll<HTMLElement>('.tableau-defile'))) {
      expect(z.getAttribute('tabindex')).toBe('0')
      expect(z.getAttribute('role')).toBe('region')
    }
    // Largeurs posées par le CSSOM seulement (CSP) : un attribut style n'existe que sur un élément data-l, data-g ou data-f.
    const fautifs = Array.from(main.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l') && !el.hasAttribute('data-g') && !el.hasAttribute('data-f'))
    expect(fautifs.length).toBe(0)
    expect(main.textContent).not.toContain('—')
    expect(main.querySelectorAll('a[href=""], a:not([href])').length).toBe(0)
    // Lexique neutre partagé (docs/lexique_neutre.json), sur tout le texte et les attributs, comme tests/ecrans.test.ts.
    lexiqueNeutre('complet')
    const r = ROUTES.find((x) => x.chemin === CHEMIN)!
    verifier(`${r.titre} ${r.titrePage ?? ''} ${r.description} ${r.resume ?? ''}`, 'route')
    // Aucune lecture hors du site.
    expect(requetes.length).toBeGreaterThan(10)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })

  it('fixtures communes seulement : page sans erreur, blocs manquants dits en mots, écart justice 2024 toujours montré', async () => {
    await ecran('commun')
    expect(main.querySelector('.erreur')).toBeNull()
    expect(main.querySelector('h1')?.textContent?.trim()).toBe('Justice et défense')
    const t = texte()
    expect(t).toContain('Emplois par programme non disponibles')
    expect(t).toContain('Données d’exécution par programme non disponibles')
    expect(t).toContain('Montant des opérations extérieures non disponible')
    expect(t).toContain('Mission Justice, 2024')
    expect(main.querySelectorAll('.surligne').length).toBe(1)
    expect(t).not.toContain('Lecture des données d’exécution')
    lexiqueNeutre('commun')
  })

  it('avant les fichiers de l’axe : état « en cours », le budget de l’État et la défense restent affichés', async () => {
    await ecran('vide')
    expect(main.querySelector('.erreur')).toBeNull()
    expect(main.querySelector('.en-cours')).not.toBeNull()
    const t = texte()
    expect(t).toContain('Budget de la justice non disponible')
    expect(t).toContain('Statistique des prisons non disponible')
    expect(t).toContain('la mission Défense a dépensé')
    expect(main.querySelectorAll('a[href^="#/"]').length).toBeGreaterThan(3)
    lexiqueNeutre('vide')
  })
})

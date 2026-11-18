// @vitest-environment happy-dom
// Écran « Les retraites » (/explorer/retraites) sur des extraits réels de site/data, servis depuis les fixtures
// propres à cet écran (tests/fixtures/retraites/data/, produites sans modification des valeurs) : montants, statuts,
// sources, règles de neutralité, accessibilité des tableaux, part de ce que verse la personne, données absentes.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { CLES_AFFECTATION_A_CREER } from '../src/calcul/moteur-etendu'
import type { Prelevement, ResultatOk } from '../src/calcul/types'
import { picto } from '../src/composants/pictos'
import { plage } from '../src/composants/resume-calcul'
import { viderCache } from '../src/donnees'
import { CAISSES_RETRAITE, ordreRegimes, partRetraite, REGLE_MONTANTS, REGLE_RECETTES, REGLE_REGIMES, RETRAITE_SANS_AFFECTATION, TITRE } from '../src/ecrans/retraites'
import { session } from '../src/etat'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { entier, eur, md, sur100 } from '../src/util'
import { monterPage } from './aide-dom'

const RACINE = process.cwd()
const MES_FIXTURES = join(RACINE, 'tests', 'fixtures', 'retraites')
const lire = (f: string) => JSON.parse(readFileSync(join(MES_FIXTURES, 'data', f), 'utf8'))
const IDX = lire('retraites/index.json')
const REG = lire('retraites/regimes.json')
const ETAT = lire('retraites/etat.json')
const PENSIONS = lire('prestations/nationales.json').prestations.pensions_retraite
const CPS = lire('secu/cps/racine.json')
const ARBRE = lire('arbre/racine.json')

const requetes: string[] = []
let absents: RegExp | null = null
let main: HTMLElement

function servir() {
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const f = join(MES_FIXTURES, u.split('?')[0])
    if (absents?.test(u) || !existsSync(f)) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}

const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''
const norm = (s: string) => s.replace(/\s+/g, ' ')

// Lexique neutre partagé (docs/lexique_neutre.json), appliqué comme dans tests/ecrans.test.ts.
const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; niche_definie: string; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function verifierLexique(t: string, ou: string) {
  let x = t.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
  expect(x.replace(new RegExp(LEXIQUE.niche_definie, 'giu'), ' '), `${ou} : « niche » sans définition`).not.toMatch(borne('niches?'))
}

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu') as HTMLElement
})
afterAll(() => {
  vi.unstubAllGlobals()
})

describe('écran des retraites', () => {
  it('route : parent, voisins, famille et picto existants ; titre et description dans les bornes', () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/retraites')!
    expect(r).toBeTruthy()
    expect(r.parent).toBe('/explorer')
    expect(r.famille).toBe('secu')
    expect(picto(r.picto!)).not.toBe('')
    expect(r.titre).toBe(TITRE)
    expect(r.voisins!.length).toBeGreaterThanOrEqual(1)
    for (const v of r.voisins!) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    expect(r.description.length).toBeGreaterThanOrEqual(70)
    expect(r.description.length).toBeLessThanOrEqual(200)
    verifierLexique(`${r.titre} ${r.description} ${r.resume}`, 'route')
  })

  it('montant de l’année, seul chiffre surligné, avec sa part sur 100 € de prestations, son année, sa source et son statut', async () => {
    await ecran('#/explorer/retraites')
    expect(main.querySelector('h1')?.textContent?.trim()).toBe(TITRE)
    expect(main.querySelector('nav[aria-label="Fil d\'Ariane"] [aria-current=page]')?.getAttribute('href')).toBe('#/explorer/retraites')
    const an = String(PENSIONS.derniere_annee)
    const total = PENSIONS.montant_eur[an]
    const surlignes = main.querySelectorAll('.surligne')
    expect(surlignes).toHaveLength(1)
    expect(norm(surlignes[0].textContent ?? '')).toBe(norm(md(total / 1e9)))
    const cle = surlignes[0].closest('[data-cle]')!
    expect(cle).not.toBeNull()
    expect(CPS.millesime).toBe(an)
    expect(norm(cle.textContent ?? '')).toContain(norm(`soit ${sur100((total / (CPS.md * 1e9)) * 100)} sur 100 € de prestations de protection sociale versées en ${an}`))
    expect(cle.querySelector('.badge')?.textContent).toBe('Tracé')
    expect(cle.querySelector('.source')?.textContent).toContain(`${CPS.source} (${an})`)
    // Chiffres clés : estimations de la DREES, chacune avec son statut.
    const t = REG.regimes.tous_regimes
    const a = String(IDX.derniere_annee)
    const cles = main.querySelector('.cles')!
    expect(norm(cles.textContent ?? '')).toContain(norm(`${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(t.retraites_droit_direct[a] / 1e6)} millions`))
    expect(norm(cles.textContent ?? '')).toContain(norm(eur(t.pension_droit_direct_eur_mois[a])))
    expect(norm(cles.textContent ?? '')).toContain(norm(entier(t.nouveaux_retraites_droit_direct[a])))
    expect(cles.querySelectorAll('.badge')).toHaveLength(3)
    for (const b of Array.from(cles.querySelectorAll('.badge'))) expect(b.textContent).toBe('Approché')
    // Autre comptabilité : comptes des caisses, jamais additionnés au montant de la DREES.
    expect(texte()).toContain('ces montants ne s’ajoutent pas au montant ci-dessus')
    expect(main.querySelector('a[href="#/explorer/secu?m=organismes2024&id=robss%2Fvieillesse"]')).not.toBeNull()
  })

  it('qui verse : chaque régime sur 100 € (somme = total publié), ordre écrit, tableau des retraités sans addition', async () => {
    await ecran('#/explorer/retraites')
    const an = String(PENSIONS.derniere_annee)
    const total = PENSIONS.montant_eur[an]
    const lignes = PENSIONS.par_regime.filter((r: { montant_eur: Record<string, number | null> }) => (r.montant_eur[an] ?? 0) > 0)
    // La ventilation publiée retombe sur le total : la page n'ajoute ni ne retranche rien.
    expect(Math.abs(lignes.reduce((s: number, r: { montant_eur: Record<string, number> }) => s + r.montant_eur[an], 0) - total)).toBeLessThan(1)
    const liste = main.querySelector('ul.parts[aria-label^="Pensions de retraite versées"]')!
    const items = Array.from(liste.querySelectorAll('li'))
    expect(items).toHaveLength(lignes.length)
    const montants = items.map((li) => Number((li.querySelector('.p-montant')?.textContent ?? '').replace(/\s/g, '').replace(',', '.').replace('€', '')))
    expect([...montants].sort((x, y) => y - x)).toEqual(montants)
    expect(items[0].textContent).toContain('Assurance retraite du régime général (CNAV)')
    expect(items[0].querySelector('a')?.getAttribute('href')).toBe('#/explorer/secu?m=protection2024&id=S13141%2FCaisse+nationale+d%E2%80%99assurance+vieillesse')
    expect(items[0].textContent).toContain('libellé de la source : « Caisse nationale d’assurance vieillesse »')
    expect(Array.from(main.querySelectorAll('[data-regle-ordre]')).map((x) => x.textContent)).toContain(REGLE_MONTANTS)
    // Billet des régimes : 5 régimes et une part « autres régimes », rien de plus.
    const billetRegimes = main.querySelector('section[aria-labelledby="titre-qui"] .billet-compact')!
    expect(billetRegimes.querySelectorAll('[aria-label]')).toHaveLength(6)
    expect(billetRegimes.querySelector('[aria-label^="14 autres régimes"]')).not.toBeNull()
    // Tableau des régimes : une ligne par régime publié l'année, « Tous régimes » d'abord, règle écrite.
    const a = String(IDX.derniere_annee)
    const table = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.startsWith(`Retraités au 31 décembre ${a}`))!
    const rangs = Array.from(table.querySelectorAll('tbody tr'))
    const attendus = Object.keys(REG.regimes).filter((id) =>
      ['retraites_droit_direct', 'retraites_tous_droits', 'nouveaux_retraites_droit_direct', 'pension_droit_direct_eur_mois'].some((k) => typeof REG.regimes[id][k][a] === 'number'),
    )
    expect(rangs).toHaveLength(attendus.length)
    // Nom du régime = texte de tête de la cellule ; les sigles reliés au glossaire après le rendu (MSA, CNAV...) découpent
    // ce texte en plusieurs nœuds : on lit jusqu'au premier élément qui n'est pas un lien de sigle.
    const nomRegime = (th: Element) => {
      let t = ''
      for (const n of Array.from(th.childNodes)) {
        if (n.nodeType === 1 && !(n as Element).classList.contains('glossaire-sigle')) break
        t += n.textContent ?? ''
      }
      return t
    }
    expect(rangs.map((tr) => nomRegime(tr.querySelector('th')!))).toEqual(ordreRegimes(attendus, REG.regimes, a).map((id) => REG.regimes[id].nom))
    expect(rangs[0].querySelector('th')?.textContent).toContain('Tous régimes')
    // Valeur absente à la source : « non publié », jamais 0.
    const cnavpl = rangs.find((tr) => tr.querySelector('th')?.textContent?.startsWith(REG.regimes.cnavpl.nom))!
    expect(REG.regimes.cnavpl.pension_droit_direct_eur_mois[a]).toBeNull()
    expect(cnavpl.querySelectorAll('td')[1].textContent).toBe('non publié')
    expect(Array.from(main.querySelectorAll('[data-regle-ordre]')).map((x) => x.textContent)).toContain(REGLE_REGIMES)
    expect(texte()).toContain('les nombres de retraités ne s’additionnent pas d’un régime à l’autre')
  })

  it('d’où vient l’argent : prélèvements affectés, compte des pensions de l’État, crédits aux régimes spéciaux, part non publiée', async () => {
    await ecran('#/explorer/retraites')
    // Répartition publiée des prélèvements : droits sur les alcools vers la retraite agricole, avec montant 2025.
    expect(texte()).toContain(norm(`Retraite de base des non-salariés agricoles (MSA), 60,3 % du produit (${md(2.489)} en 2025)`))
    expect(texte()).toContain('Assurance retraite du régime général (CNAV), 100,0 % du produit')
    // La CSG n'a aucune part vers une caisse de retraite dans la répartition publiée : elle n'est pas listée.
    const csg = lire('prelevements/affectation.json').prelevements.csg_activite.libelle
    expect(csg).toBeTruthy()
    expect(texte()).not.toContain(csg)
    // Compte d'affectation spéciale Pensions : recettes par origine, sur 100 €, dans l'ordre décroissant.
    const cas = ETAT.cas_pensions
    expect(texte()).toContain(norm(`Recettes prévues pour 2025 : ${md(cas.recettes_eur / 1e9)}`))
    const parts = Array.from(main.querySelectorAll('ul.parts[aria-label^="Recettes prévues en 2025"] li'))
    expect(parts).toHaveLength(Object.values(cas.recettes_par_origine_eur).filter((v) => (v as number) > 0).length)
    expect(parts[0].textContent).toContain('Contributions des employeurs')
    expect(norm(parts[0].querySelector('.p-montant')?.textContent ?? '')).toBe(norm(sur100(cas.recettes_par_origine_pct.contributions_employeurs)))
    expect(Array.from(main.querySelectorAll('[data-regle-ordre]')).map((x) => x.textContent)).toContain(REGLE_RECETTES)
    expect(texte()).toContain('elle ne s\'additionne pas aux dépenses du budget général')
    // Crédits de l'État aux régimes spéciaux : deux millésimes côte à côte, part du budget de l'État 2024.
    const cr = ETAT.credits_regimes_speciaux
    expect(texte()).toContain(norm(`Dépensé en 2024 : ${md(cr.total_execution_2024_eur / 1e9)}, soit ${sur100((cr.total_execution_2024_eur / (ARBRE.md * 1e9)) * 100)} sur 100 € dépensés par l’État en 2024`))
    expect(main.querySelector('a[href="#/explorer/etat/detail?m=execution2024&id=Solidarite%2C+travail+et+sante%2FR%C3%A9gimes+sociaux+et+de+retraite%2F198"]')).not.toBeNull()
    const tCredits = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.startsWith('Crédits de la mission'))!
    expect(tCredits.querySelectorAll('tbody tr')).toHaveLength(cr.programmes.length + cr.programmes.reduce((s: number, p: { actions: unknown[] }) => s + p.actions.length, 0))
    expect(tCredits.textContent).toContain('régime : SNCF (caisse de prévoyance et de retraite du personnel ferroviaire)')
    // Ce qui n'est pas publié : hachuré, dit comme un état de la publication.
    const absent = main.querySelector('.absent')!
    expect(absent.textContent).toContain('Ressources par origine (cotisations, État, transferts) des régimes hors compte d\'affectation spéciale Pensions')
    expect(texte()).toContain('Cela décrit l’état de la publication, pas l’usage de l’argent.')
    expect(Array.from(main.querySelectorAll('.badge')).some((b) => b.textContent === 'Non publié')).toBe(true)
  })

  it('évolution : montants 2020 à 2024 en barres, sélecteur de régime, cotisants et liens vers les autres vues', async () => {
    await ecran('#/explorer/retraites')
    const ans = Object.keys(PENSIONS.montant_eur).filter((a) => typeof PENSIONS.montant_eur[a] === 'number').sort()
    const barres = Array.from(main.querySelectorAll('ul.barres[aria-label^="Pensions de retraite versées, tous régimes"] li'))
    expect(barres.map((li) => li.querySelector('.nom')?.textContent)).toEqual(ans)
    expect(texte()).toContain(norm(`le montant passe de ${md(PENSIONS.montant_eur[ans[0]] / 1e9)} en ${ans[0]} à ${md(PENSIONS.montant_eur[ans[ans.length - 1]] / 1e9)} en ${ans[ans.length - 1]}`))
    const choix = main.querySelector<HTMLSelectElement>('#ret-regime')!
    expect(main.querySelector('label[for="ret-regime"]')).not.toBeNull()
    expect(choix.value).toBe('tous_regimes')
    expect(main.querySelector('#ret-serie caption')?.textContent).toContain(REG.regimes.tous_regimes.nom)
    // Tous régimes : cotisants publiés par la DREES jusqu'en 2016, rapport publié.
    expect(main.querySelector('#ret-serie')?.textContent).toContain('Rapport publié par la DREES.')
    choix.value = 'agirc_arrco'
    choix.dispatchEvent(new Event('change'))
    const serie = main.querySelector('#ret-serie')!
    expect(serie.querySelector('caption')?.textContent).toContain(REG.regimes.agirc_arrco.nom)
    const lignes = serie.querySelectorAll('tbody tr')
    expect(lignes.length).toBe(Object.keys(REG.regimes.agirc_arrco.retraites_droit_direct).filter((a) => typeof REG.regimes.agirc_arrco.retraites_droit_direct[a] === 'number').length)
    expect(serie.querySelector('a[href="#/explorer/secu?m=organismes2024&id=complementaires%2Fagirc_arrco"]')).not.toBeNull()
    expect(serie.textContent).toContain('jamais additionné')
    // Adresse avec un régime choisi : le sélecteur et le tableau suivent, cotisants de la Caisse des dépôts.
    await ecran('#/explorer/retraites?regime=cnracl')
    expect(main.querySelector<HTMLSelectElement>('#ret-regime')!.value).toBe('cnracl')
    const cot = Array.from(main.querySelectorAll<HTMLTableElement>('#ret-serie table')).find((x) => x.caption?.textContent?.includes('cotisants'))!
    expect(cot.querySelectorAll('tbody tr').length).toBe(Object.values(REG.regimes.cnracl.cotisants.valeurs).filter((v) => typeof v === 'number').length)
    expect(main.querySelector('#ret-serie')?.textContent).toContain('deux sources, deux champs ; ordre de grandeur')
  })

  it('écarts entre sources montrés sans trancher, limites et sources listées', async () => {
    await ecran('#/explorer/retraites')
    const t = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent === 'Écarts entre sources, dernière année publiée')!
    const derniers = new Set(IDX.ecarts.map((e: { regime: string; grandeur: string; objet: string; source: string; autre_source: string }) => [e.regime, e.grandeur, e.objet, e.source, e.autre_source].join('|')))
    expect(t.querySelectorAll('tbody tr')).toHaveLength(derniers.size)
    expect(t.textContent).toContain('DGFiP, Service des retraites de l\'État')
    expect(texte()).toContain('le site ne choisit pas entre les sources')
    expect(main.querySelectorAll('ul.limites li')).toHaveLength(IDX.limites.length + ETAT.limites.length)
    for (const s of Object.values(IDX.sources) as { page?: string; url: string }[]) expect(main.querySelector(`a[href="${s.page ?? s.url}"]`)).not.toBeNull()
    expect(texte()).toContain('Conseil d’orientation des retraites')
  })

  it('format et neutralité : tableaux accessibles, aucun style en ligne, aucun terme évaluatif, liens internes valides, lectures relatives', async () => {
    viderCache()
    requetes.length = 0
    await ecran('#/explorer/retraites')
    for (const t of Array.from(main.querySelectorAll('table'))) {
      expect(t.querySelector('caption')?.textContent?.trim()).toBeTruthy()
      for (const th of Array.from(t.querySelectorAll('th'))) expect(th.getAttribute('scope'), th.textContent ?? '').toMatch(/^(col|row)$/)
    }
    expect(Array.from(main.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l') && !el.hasAttribute('data-g') && !el.hasAttribute('data-f'))).toHaveLength(0)
    expect(main.textContent).not.toContain('—')
    expect(texte()).not.toMatch(/\bNaN\b|undefined|\bnull\b|Chargement…/)
    for (const x of Array.from(main.querySelectorAll('h1, h2, h3'))) expect(x.textContent ?? '').not.toMatch(/\b(gaspillage|seulement|énorme|opaque|scandale|trop)\b/i)
    verifierLexique(main.textContent ?? '', 'retraites')
    for (const el of Array.from(main.querySelectorAll('[aria-label], [title], [alt]'))) verifierLexique(['aria-label', 'title', 'alt'].map((a) => el.getAttribute(a) ?? '').join(' '), 'retraites (attribut)')
    const internes = Array.from(main.querySelectorAll('a[href^="#/"]')).map((a) => a.getAttribute('href')!)
    expect(internes.length).toBeGreaterThan(10)
    for (const href of internes) expect(ROUTES.some((r) => r.chemin === href.slice(1).split('?')[0]), href).toBe(true)
    expect(main.querySelectorAll('a[href=""], a:not([href])')).toHaveLength(0)
    expect(requetes.length).toBeGreaterThan(0)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })

  it('ce que tu verses : part retraite lue dans la répartition publiée, part employeur à part, prorata de l’État approché', async () => {
    const l = (id: string, montant: number, dest: string, extra: Partial<Prelevement> = {}): Prelevement => ({
      id,
      libelle: id,
      famille: 'cotisation_salariale',
      personne: 'declarant1',
      montant_annuel_eur: { bas: montant, central: montant, haut: montant },
      destinataire: { id: dest, nom: dest, administration: dest === 'etat' ? 'Etat' : 'Securite sociale' },
      inclus_dans_total_paye: true,
      regle: '',
      ...extra,
    })
    const lignes = [
      l('vieillesse_plafonnee_salarie', 1000, 'cnav'),
      l('retraite_complementaire_salarie', 600, 'agirc_arrco', { ventilation: [{ destinataire: 'agirc_arrco', part: 1 }] }),
      l('csg_deductible', 1500, 'plusieurs', { famille: 'csg_crds', ventilation: [{ destinataire: 'cnam', part: 0.6 }, { destinataire: 'cnaf', part: 0.4 }] }),
      l('impot_revenu', 900, 'etat', { famille: 'impot_revenu' }),
      l('alcool', 100, 'plusieurs', {
        famille: 'taxe_consommation',
        montant_annuel_eur: { bas: 80, central: 100, haut: 120 },
        ventilation: [{ destinataire: 'msa_maladie', part: 0.245352 }, { destinataire: 'msa_vieillesse', part: 0.60254 }, { destinataire: 'msa_rco', part: 0.152108 }],
      }),
      l('tabac', 50, 'plusieurs', { non_chiffre: true, ventilation: [{ destinataire: 'cnav', part: 1 }] }),
      l('retenue_pension_civile', 300, 'non_affecte'),
    ]
    const patronales = [
      l('vieillesse_plafonnee_employeur', 1200, 'cnav', { famille: 'cotisation_patronale', inclus_dans_total_paye: false }),
      l('retraite_complementaire_employeur', 900, 'agirc_arrco', { famille: 'cotisation_patronale', inclus_dans_total_paye: false }),
      l('contribution_cas_pensions', 500, 'non_affecte', { famille: 'cotisation_patronale', inclus_dans_total_paye: false }),
    ]
    const r = partRetraite(lignes)
    expect(r.caisses.map((c) => c.id)).toEqual(['cnav', 'agirc_arrco', 'msa_vieillesse', 'msa_rco'])
    expect(r.total.central).toBeCloseTo(1000 + 600 + 100 * 0.60254 + 100 * 0.152108, 6)
    expect(r.total.bas).toBeCloseTo(1000 + 600 + 80 * (0.60254 + 0.152108), 6)
    expect(r.sansAffectation.central).toBe(300)
    const total = lignes.filter((x) => !x.non_chiffre).reduce((s, x) => s + x.montant_annuel_eur.central, 0)
    session.complet = { lignes, total: { bas: total, central: total, haut: total }, placement: null, conso: [], locaux: [] }
    session.resultat = { prelevements: [...lignes, ...patronales] } as unknown as ResultatOk
    try {
      await ecran('#/explorer/retraites')
      const bloc = main.querySelector('section[aria-labelledby="titre-toi"]')!
      const t = norm(bloc.textContent ?? '')
      expect(t).toContain(norm(`Sur les ${eur(total)} que tu verses en un an (valeur centrale), ${plage(r.total)} vont aux caisses de retraite, soit ${sur100((r.total.central / total) * 100)} sur 100 €.`))
      expect(bloc.querySelector('p .badge')?.textContent).toBe('Approché')
      for (const c of r.caisses) expect(t).toContain(norm(`${CAISSES_RETRAITE[c.id]} : ${plage(c.f)}`))
      expect(t).toContain(norm(`${plage(r.sansAffectation)} de retenues de retraite n’ont pas encore de destinataire publié`))
      expect(t).toContain(norm(`Ton employeur verse en plus ${eur(2100)} par an de cotisations de retraite`))
      expect(t).toContain(norm(`Ton employeur verse aussi ${eur(500)} par an de contributions de retraite`))
      const partEtat = ETAT.credits_regimes_speciaux.total_execution_2024_eur / (ARBRE.md * 1e9)
      expect(t).toContain(norm(`Sur les ${eur(900)} que tu verses à l’État, environ ${eur(900 * partEtat)} par an vont aux régimes spéciaux de retraite`))
      expect(bloc.querySelector('.ruban')).not.toBeNull()
      expect(main.querySelectorAll('.surligne')).toHaveLength(1)
      verifierLexique(bloc.textContent ?? '', 'ce que tu verses')
    } finally {
      session.complet = null
      session.resultat = null
    }
    // Sans calcul : renvoi vers le calcul, sans montant inventé.
    await ecran('#/explorer/retraites')
    const sans = main.querySelector('section[aria-labelledby="titre-toi"]')!
    expect(sans.querySelector('a[href="#/calcul"]')?.textContent).toBe('Voir ta part personnelle')
    expect(sans.querySelector('.ruban')).toBeNull()
  })

  it('lignes de retraite sans affectation publiée : même liste que le moteur étendu', () => {
    const attendu = Object.entries(CLES_AFFECTATION_A_CREER)
      .filter(([, cle]) => Object.hasOwn(CAISSES_RETRAITE, cle))
      .sort()
    expect(Object.entries(RETRAITE_SANS_AFFECTATION).sort()).toEqual(attendu)
  })

  it('ordre des régimes : groupe de type, puis retraités décroissants, puis nom', () => {
    const g = (type: string | null, n: number | null, nom: string) => ({ nom, type, retraites_droit_direct: { '2024': n } }) as never
    const regimes = { a: g('complementaire', 10, 'A'), b: g('base', 5, 'B'), c: g('base', 50, 'C'), d: g(null, 99, 'D'), e: g('ensemble', 1, 'E'), f: g('base', null, 'F'), h: g('integre', 3, 'H') }
    expect(ordreRegimes(Object.keys(regimes), regimes, '2024')).toEqual(['e', 'c', 'b', 'f', 'h', 'a', 'd'])
  })

  it('données absentes : état « en cours d’intégration », sans erreur, avec des sorties', async () => {
    viderCache()
    absents = /^data\/retraites\//
    try {
      await ecran('#/explorer/retraites')
      expect(main.querySelector('h1')?.textContent?.trim()).toBe(TITRE)
      expect(main.querySelector('.en-cours')?.textContent).toContain('Données en cours d’intégration.')
      expect(main.querySelector('.erreur')).toBeNull()
      expect(main.querySelector('.surligne')).toBeNull()
      expect(Array.from(main.querySelectorAll('a[href^="#/"]')).filter((a) => !a.closest('.fil-ariane')).length).toBeGreaterThan(0)
    } finally {
      absents = null
      viderCache()
    }
  })
})

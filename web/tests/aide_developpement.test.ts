// @vitest-environment happy-dom
// Écran « L’aide publique au développement » (/explorer/aide-developpement) sur des extraits réels de
// site/data/aide_developpement (tests/fixtures/data/aide_developpement) et de l'arbre du budget de l'État.
// Chaque chiffre attendu est lu dans les fixtures, jamais recopié à la main.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher, lien } from '../src/routeur'
import { session } from '../src/etat'
import { viderCache } from '../src/donnees'
import { eurLisible, sur100 } from '../src/util'
import {
  AFD_PRET,
  CITATIONS,
  GLOSSAIRE,
  PAP_2026,
  REGLE_ORDRE_REGIONS,
  REGLE_ORDRE_SOURCE,
  milliards,
  parRegion,
  type ApdDeclaree,
  type Index,
} from '../src/ecrans/aide_developpement'
import { monterPage, requetes } from './aide-dom'

const F = join(process.cwd(), 'tests', 'fixtures', 'data')
const lire = (f: string) => JSON.parse(readFileSync(join(F, f), 'utf8'))
const brut = lire('aide_developpement/index.json')
const idx: Index = brut
const apd: ApdDeclaree = lire('aide_developpement/apd_declaree.json')
const afd = lire('aide_developpement/afd.json')
const proparco = lire('aide_developpement/proparco.json')
const ef = lire('aide_developpement/expertise_france.json')
const racine = lire('arbre/racine.json')
const ROUTE = '#/explorer/aide-developpement'

/** Espaces normalisés (les formats français posent des espaces insécables). */
const esp = (t: string | null | undefined) => (t ?? '').replace(/\s+/g, ' ').trim()
/** Premier nombre décimal français d'un texte : « 14,05 Md€ (…) » donne 14.05. */
const premier = (t: string) => Number(/(-?\d[\d ]*,\d+)/.exec(esp(t))![1].replace(/ /g, '').replace(',', '.'))
const tableau = (debutLegende: string) => Array.from(main.querySelectorAll('table')).find((t) => esp(t.caption?.textContent).startsWith(debutLegende)) ?? null
const entetes = (t: HTMLTableElement) => Array.from(t.querySelectorAll('thead th')).map((x) => esp(x.textContent))
const lignes = (t: HTMLTableElement) => Array.from(t.querySelectorAll('tbody tr'))
const nomsLignes = (t: HTMLTableElement) => lignes(t).map((tr) => esp(tr.querySelector('th')?.textContent))

const t = idx.totaux.apd_declaree
const derniere = Math.max(...apd.annees)
const total = (an: number, c: string) => t.lignes.find((l) => l[0] === an)![t.colonnes.indexOf(c)] as number
const vue = idx.credits_budgetaires.vues.find((v) => v.vue === 'arbre')!

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => esp(main.textContent)

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('écran aide publique au développement', () => {
  it('route : rayon d’« Explorer », voisins existants, picto et famille', () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/aide-developpement')!
    expect(r.parent).toBe('/explorer')
    expect(r.voisins).toEqual(['/explorer/etat', '/explorer/ue'])
    expect([r.famille, r.picto]).toEqual(['etat', 'monde'])
    expect(r.description.length).toBeGreaterThanOrEqual(70)
    expect(r.description.length).toBeLessThanOrEqual(200)
    for (const v of r.voisins!) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
  })

  it('page : fil d’Ariane jusqu’à la page, sorties nommées, voir aussi, aucune erreur', async () => {
    await ecran(ROUTE)
    expect(main.querySelector('.erreur')).toBeNull()
    const fil = main.querySelector('nav[aria-label="Fil d\'Ariane"]')!
    expect(Array.from(fil.querySelectorAll('a')).map((a) => a.textContent)).toEqual(['Accueil', 'Explorer', 'Aide au développement'])
    expect(fil.querySelector('[aria-current=page]')?.getAttribute('href')).toBe(ROUTE)
    const sorties = Array.from(main.querySelectorAll('a[href^="#/"]')).filter((a) => !a.closest('.fil-ariane'))
    expect(sorties.length).toBeGreaterThan(3)
    for (const a of sorties) expect(a.textContent ?? '').not.toMatch(/^\s*(ici|cliquez ici|lien|en savoir plus)\s*$/i)
    const voir = Array.from(main.querySelectorAll('.voir-aussi a')).map((a) => a.getAttribute('href'))
    expect(voir).toEqual(['#/explorer/etat', '#/explorer/ue', '#/explorer'])
    expect(document.title).toBe('Aide publique au développement de la France : montant, dons, prêts, pays · Où vont mes impôts')
  })

  it('chiffres clés de la dernière déclaration : équivalent-don, dons et prêts séparés, statut tracé', async () => {
    await ecran(ROUTE)
    expect(esp(main.querySelector('h1')?.textContent)).toBe('L’aide publique au développement')
    expect(main.querySelector('h1 .picto')).not.toBeNull()
    expect(texte()).toContain('Elle ne dit pas ce que chaque projet a produit et ne nomme aucune personne')
    const cles = Array.from(main.querySelectorAll('.cles li'))
    expect(cles).toHaveLength(3)
    expect(esp(cles[0].textContent)).toContain(esp(eurLisible(total(derniere, 'equivalent_don_eur'))))
    expect(esp(cles[0].textContent)).toContain(`pour ${derniere}`)
    expect(esp(cles[1].textContent)).toContain(esp(eurLisible(total(derniere, 'dons_verses_eur'))))
    expect(esp(cles[2].textContent)).toContain(esp(eurLisible(total(derniere, 'prets_verses_eur'))))
    // Remboursements de prêts reçus dans l'année : colonne « perçu » de la ligne « Prêt » du flux d'aide.
    const ci = (c: string) => apd.par_annee.colonnes.indexOf(c)
    const pret = apd.par_annee.lignes.find((l) => l[0] === derniere && l[ci('type_de_flux')] === 'Aide Publique au Développement' && l[ci('type_de_financement')] === 'Prêt')!
    expect(esp(cles[2].textContent)).toContain(`${esp(eurLisible(pret[ci('percu_eur')] as number))} de prêts ont été remboursés`)
    for (const li of cles) expect(esp(li.querySelector('.badge')?.textContent)).toBe('Tracé')
    // Aucune colonne ni phrase n'additionne dons et prêts.
    expect(texte()).not.toContain(esp(eurLisible(total(derniere, 'dons_verses_eur') + total(derniere, 'prets_verses_eur'))))
  })

  it('sur 100 € dépensés par l’État : un seul chiffre surligné, lu dans les données ; programmes et responsables', async () => {
    await ecran(ROUTE)
    const surlignes = main.querySelectorAll('.surligne')
    expect(surlignes).toHaveLength(1)
    expect(esp(surlignes[0].textContent)).toBe(esp(sur100((vue.mission.md / racine.md) * 100)))
    const carte = surlignes[0].closest('[data-cle]')!
    expect(esp(carte.textContent)).toMatch(/sur 100 € dépensés par l’État en 2024 sont allés à la mission « Aide publique au développement »/)
    expect(esp(carte.textContent)).toContain(`${esp(milliards(vue.mission.md * 1e9))} sur ${esp(milliards(racine.md * 1e9))}`)
    // Budget voté 2025 : même calcul sur son propre total.
    const lfi = idx.credits_budgetaires.vues.find((v) => v.vue === 'arbre_lfi2025')!
    const racineLfi = lire('arbre_lfi2025/racine.json')
    expect(esp(carte.textContent)).toContain(`Budget voté 2025 : ${esp(sur100((lfi.mission.md / racineLfi.md) * 100))} sur 100 €`)
    const progs = carte.querySelector('table')!
    expect(lignes(progs)).toHaveLength(vue.programmes.length)
    for (const p of vue.programmes) {
      const a = carte.querySelector(`a[href="${lien('/explorer/etat/detail', { m: 'execution2024', id: `${vue.mission.id}/${p.numero}` })}"]`)
      expect(a, p.numero).not.toBeNull()
      expect(esp(a!.closest('tr')!.textContent)).toContain(esp(sur100((p.md / racine.md) * 100)))
    }
    expect(esp(progs.textContent)).toContain('ministère de l’Europe et des Affaires étrangères')
    expect(carte.querySelector(`a[href="${PAP_2026.url}"]`)).not.toBeNull()
    // Le détail des programmes reste dans les pages existantes : la page y renvoie.
    expect(main.querySelector(`a[href="${lien('/beneficiaires/programme', { p: '209' })}"]`)).not.toBeNull()
  })

  it('déclaré à l’OCDE ou dépensé par l’État : écart montré, jamais tranché ; année sans déclaration signalée', async () => {
    await ecran(ROUTE)
    const tab = tableau('Crédits de la mission et aide déclarée')!
    expect(tab).not.toBeNull()
    const tr = lignes(tab)
    expect(tr).toHaveLength(idx.credits_budgetaires.vues.length)
    const c = Array.from(tr[0].querySelectorAll('td')).map((x) => esp(x.textContent))
    const budget = vue.mission.md * 1e9
    const declare = total(2024, 'equivalent_don_eur')
    expect(c[0]).toContain(esp(milliards(budget)))
    expect(c[1]).toContain(esp(milliards(declare)))
    expect(c[2]).toBe(esp(milliards(declare - budget)))
    // L'écart affiché est bien la différence des deux montants affichés.
    expect(premier(c[1]) - premier(c[0])).toBeCloseTo(premier(c[2]), 2)
    // Budget voté 2025 : la déclaration de 2025 n'est pas publiée, pas d'écart calculé.
    expect(esp(tr[1].textContent)).toContain('Non publié')
    expect(esp(tr[1].textContent)).toContain('non calculable')
    expect(texte()).toContain(esp(idx.credits_budgetaires.lecture))
    expect(texte()).toContain('Le site ne dit pas lequel des deux est le bon')
  })

  it('canaux, régions, organismes : dons et prêts séparés, ordre écrit, aucun classement par montant', async () => {
    await ecran(ROUTE)
    const canaux = tableau(`Aide déclarée pour ${derniere} par canal`)!
    expect(entetes(canaux)).toEqual(['Canal', 'Dons', 'Prêts', 'Autres instruments'])
    expect(nomsLignes(canaux)).toEqual(apd.par_canal.lignes.filter((l) => l[0] === derniere).map((l) => String(l[1])))
    // Régions : alphabétique, puis les deux regroupements sans pays ; la somme des régions retrouve le total national.
    const reg = parRegion(apd, derniere)
    const tReg = tableau(`Aide déclarée pour ${derniere} par région`)!
    expect(entetes(tReg)).toEqual(['Région', 'Dons', 'Prêts', 'Autres instruments'])
    expect(nomsLignes(tReg)).toEqual(reg.map((r) => r.nom))
    const geo = reg.slice(0, -2).map((r) => r.nom)
    expect(geo).toEqual([...geo].sort((a, b) => a.localeCompare(b, 'fr')))
    expect(reg.slice(-2).map((r) => r.nom)).toEqual(['Organisations multilatérales (non réparties par pays)', 'Pays en développement, sans pays précisé'])
    expect(reg.reduce((s, r) => s + (r.dons ?? 0), 0)).toBeCloseTo(total(derniere, 'dons_verses_eur'), -1)
    expect(reg.reduce((s, r) => s + (r.prets ?? 0), 0)).toBeCloseTo(total(derniere, 'prets_verses_eur'), -1)
    expect(esp(tReg.querySelector('tfoot')?.textContent)).toContain(esp(eurLisible(total(derniere, 'dons_verses_eur'))))
    const regles = Array.from(main.querySelectorAll('[data-regle-ordre]')).map((x) => esp(x.textContent))
    expect(regles).toContain(REGLE_ORDRE_REGIONS)
    expect(regles).toContain(REGLE_ORDRE_SOURCE)
    // Organismes : une ligne par organisme de la source, dans son ordre ; sigles écrits en toutes lettres.
    const org = tableau(`Aide déclarée pour ${derniere} par organisme`)!
    const source = apd.par_agence.lignes.filter((l) => l[0] === derniere).map((l) => String(l[1]))
    expect(lignes(org)).toHaveLength(source.length)
    expect(nomsLignes(org)).toContain('Ministère de l’équipement (libellé de la source : « MIN/EQUIPEMENT »)')
    expect(nomsLignes(org)).not.toContain('MIN/EQUIPEMENT')
    for (const tb of [canaux, tReg, org]) expect(entetes(tb).join(' ')).not.toMatch(/total/i)
    // Définitions citées depuis le glossaire officiel, avec leur source.
    for (const k of ['bilateral', 'multilateral', 'don', 'pret'] as const) expect(texte()).toContain(`« ${CITATIONS[k].texte} »`)
    expect(main.querySelector(`a[href="${GLOSSAIRE.url}"]`)).not.toBeNull()
  })

  it('financement des prêts de l’AFD : le texte sans source primaire n’est jamais affiché, les sources primaires sont citées', async () => {
    await ecran(ROUTE)
    const tout = esp(document.body.textContent)
    expect(tout).not.toContain(esp(brut.financement_des_prets.texte))
    expect(tout).not.toMatch(/non par l['’]impôt/)
    expect(tout).not.toContain('emprunts obligataires')
    expect(tout).not.toContain(esp(afd.avertissement))
    expect(tout).not.toContain(esp(proparco.avertissement))
    for (const g of brut.grandeurs as { financement: string }[]) expect(tout).not.toContain(esp(g.financement))
    for (const k of ['emprunt', 'bonification', 'fondsPropres'] as const) expect(tout).toContain(`« ${CITATIONS[k].texte} »`)
    expect(main.querySelector(`a[href="${AFD_PRET.url}"]`)).not.toBeNull()
    expect(tout).toContain(`${PAP_2026.titre}, page 43`)
    expect(tout).toContain(`${PAP_2026.titre}, page 54`)
    expect(tout).toContain('Phrases citées telles quelles, avec leur source.')
  })

  it('groupe AFD : publication de l’AFD, Proparco et Expertise France ; années incomplètes signalées ; experts individuels non ventilés', async () => {
    await ecran(ROUTE)
    const tAfd = tableau('Concours d’aide au développement publiés par l’Agence française de développement')!
    expect(lignes(tAfd)).toHaveLength(idx.totaux.afd.lignes.length)
    expect(entetes(tAfd)).toEqual(['Année', 'Dons engagés', 'Prêts engagés', 'Dons versés', 'Prêts versés'])
    expect(lignes(tAfd).filter((tr) => esp(tr.textContent).includes('(année incomplète)'))).toHaveLength(idx.totaux.afd.annees_partielles.length)
    // Proparco et Expertise France arrivent après le premier affichage (suite de l'écran).
    const tPro = tableau('Financements signés par Proparco')!
    expect(tPro).not.toBeNull()
    expect(entetes(tPro)).toContain('2026 (année en cours)')
    const instruments = new Set(proparco.par_annee.lignes.filter((l: unknown[]) => Number(l[0]) >= 2023).map((l: unknown[]) => l[1]))
    expect(lignes(tPro)).toHaveLength(instruments.size)
    const tEf = tableau('Contrats de plus de 15 000 euros conclus par Expertise France')!
    expect(lignes(tEf)).toHaveLength(ef.par_bailleur.lignes.length)
    expect(nomsLignes(tEf)).toContain('Union européenne')
    expect(nomsLignes(tEf)).toContain('Ministère de l’Europe et des affaires étrangères')
    const experts = ef.ecartes.find((e: { montant_initial_maximal_eur?: number }) => typeof e.montant_initial_maximal_eur === 'number')
    expect(texte()).toContain(`contrats d’experts individuels (personnes physiques) ne sont pas ventilés`)
    expect(texte()).toContain(esp(eurLisible(experts.montant_initial_maximal_eur)))
    expect(main.querySelector('#aide-dev-groupe .chargement')).toBeNull()
  })

  it('écarts entre sources : publiés tels quels pour l’année affichée', async () => {
    await ecran(ROUTE)
    const ec = idx.ecarts.filter((e) => e.annee === derniere)
    const tab = tableau(`Un même objet mesuré par deux sources (${derniere})`)!
    expect(lignes(tab)).toHaveLength(ec.length)
    for (const e of ec) expect(texte()).toContain(esp(e.lecture))
    expect(texte()).toContain('sans correction ni choix entre les sources')
  })

  it('choix de l’année : la déclaration demandée, la dernière si l’année est inconnue', async () => {
    await ecran(`${ROUTE}?a=2023`)
    expect(main.querySelector('.bascule [aria-current="true"]')?.textContent).toBe('2023')
    expect(tableau('Aide déclarée pour 2023 par canal')).not.toBeNull()
    expect(esp(main.querySelector('.cles li')?.textContent)).toContain(esp(eurLisible(total(2023, 'equivalent_don_eur'))))
    await ecran(`${ROUTE}?a=1990`)
    expect(main.querySelector('.bascule [aria-current="true"]')?.textContent).toBe(String(derniere))
    expect(main.querySelectorAll('.bascule a')).toHaveLength(apd.annees.length)
  })

  it('sans pays choisi, les fichiers de l’AFD et de l’OCDE ne sont pas lus', async () => {
    await ecran(ROUTE)
    expect(requetes).not.toContain('data/aide_developpement/afd.json')
    expect(requetes).not.toContain('data/aide_developpement/ocde.json')
    expect(main.querySelector('#aide-dev-pays')?.textContent).toBe('')
  })

  it('un pays : séries de la Direction générale du Trésor, de l’AFD et de l’OCDE ; statuts ; Kosovo avec le code de l’OCDE', async () => {
    await ecran(`${ROUTE}?pays=SEN`)
    const zone = main.querySelector('#aide-dev-pays')!
    expect(esp(zone.querySelector('h3')?.textContent)).toBe('Sénégal')
    expect(esp(zone.textContent)).toContain('pays les moins avancés')
    expect(esp(zone.textContent)).not.toMatch(/\bPMA\b/)
    const dgt = tableau('Sénégal : aide déclarée par la France')!
    expect(lignes(dgt)).toHaveLength(apd.par_pays.lignes.filter((l) => l[1] === 'SEN').length)
    const tAfd = tableau('Sénégal : concours d’aide au développement publiés')!
    expect(lignes(tAfd)).toHaveLength(afd.par_pays.lignes.filter((l: unknown[]) => l[1] === 'SEN' && l[2] === 'apd').length)
    expect(tableau('Sénégal : versements publiés par l’OCDE')).not.toBeNull()
    expect(esp(zone.textContent)).toContain('Approché')
    expect(requetes).toContain('data/aide_developpement/afd.json')
    expect(requetes).toContain('data/aide_developpement/ocde.json')
    await ecran(`${ROUTE}?pays=XKX`)
    expect(tableau('Kosovo : versements publiés par l’OCDE')).not.toBeNull()
    expect(esp(main.querySelector('#aide-dev-pays')?.textContent)).toContain('Aucun concours d’aide au développement publié')
  })

  it('formulaire : le choix d’un pays ouvre sa fiche ; liste complète, par ordre alphabétique', async () => {
    await ecran(ROUTE)
    const sel = main.querySelector<HTMLSelectElement>('#aide-dev-choix-pays')!
    expect(main.querySelector('label[for="aide-dev-choix-pays"]')).not.toBeNull()
    const options = Array.from(sel.options).slice(1)
    expect(options).toHaveLength(apd.pays.length)
    const tri = [...apd.pays].sort((a, b) => a.nom_tri.localeCompare(b.nom_tri, 'fr')).map((p) => p.code)
    expect(options.map((o) => o.value)).toEqual(tri)
    sel.value = 'MAR'
    main.querySelector('#aide-dev-pays-form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    expect(location.hash).toBe(`${ROUTE}?a=${derniere}&pays=MAR`)
  })

  it('ta part : la part de l’État de ce que tu verses, au prorata du budget, statut approché', async () => {
    const avant = { r: session.resultat, c: session.complet }
    session.complet = null
    session.resultat = { prelevements: [{ inclus_dans_total_paye: true, montant_annuel_eur: { central: 1000 }, destinataire: { id: 'essai', administration: 'Etat' } }] } as never
    try {
      await ecran(ROUTE)
      const attendu = esp(eurLisible((1000 * vue.mission.md) / racine.md))
      const p = Array.from(main.querySelectorAll('[data-cle] p')).find((x) => esp(x.textContent).includes('par an correspondent à cette mission'))!
      expect(esp(p.textContent)).toContain(`environ ${attendu} par an correspondent à cette mission`)
      expect(esp(p.querySelector('.badge')?.textContent)).toBe('Approché')
    } finally {
      session.resultat = avant.r
      session.complet = avant.c
    }
  })

  it('accessibilité et neutralité : tableaux légendés, titres sans saut, aucun tiret long ni style en ligne, lexique neutre, sigles développés', async () => {
    const LEX = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[] }
    const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
    for (const f of [ROUTE, `${ROUTE}?a=2019&pays=SEN`, `${ROUTE}?pays=XKX`]) {
      await ecran(f)
      expect(main.querySelectorAll('h1'), f).toHaveLength(1)
      const niveaux = Array.from(main.querySelectorAll('h1, h2, h3, h4')).map((x) => Number(x.tagName[1]))
      niveaux.forEach((n, i) => i > 0 && expect(n - niveaux[i - 1], `${f} : saut de niveau de titre`).toBeLessThanOrEqual(1))
      for (const tb of Array.from(main.querySelectorAll('table'))) {
        expect(esp(tb.caption?.textContent), f).not.toBe('')
        for (const th of Array.from(tb.querySelectorAll('thead th'))) expect(th.getAttribute('scope'), f).toBe('col')
        for (const th of Array.from(tb.querySelectorAll('tbody th, tfoot th'))) expect(th.getAttribute('scope'), f).toBe('row')
        expect(tb.closest('.tableau-defile'), f).not.toBeNull()
      }
      expect(main.textContent, f).not.toContain('—')
      expect(main.querySelectorAll('[style]:not([data-l]):not([data-g]):not([data-f])'), f).toHaveLength(0)
      // Lexique neutre partagé (docs/lexique_neutre.json), sur tout le texte affiché.
      const txt = esp(main.textContent).replace(/[\w./:-]*\/[\w./-]+/g, ' ')
      for (const r of LEX.regles) expect(txt, `${f} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
      // Aucun sigle seul dans la rédaction : budget voté, catégories de pays. Les libellés d'origine ne figurent
      // qu'entre guillemets ; les lignes « Source » reprennent le nom publié par chaque producteur.
      const copie = main.cloneNode(true) as HTMLElement
      copie.querySelectorAll('.source').forEach((x) => x.remove())
      const horsCitations = esp(copie.textContent).replace(/« [^»]* »/g, ' ')
      expect(horsCitations, f).not.toMatch(/\b(LFI|PLF|PMA|PRITI|PRITS|PFR)\b/)
      expect(main.querySelectorAll('a[href^="http"]:not([rel="noopener noreferrer"])'), f).toHaveLength(0)
    }
  })

  it('données absentes : état « en cours d’intégration », sorties vers le reste du site', async () => {
    const { rendre } = await import('../src/ecrans/aide_developpement')
    viderCache()
    const vrai = globalThis.fetch
    globalThis.fetch = (async (u: string) => (String(u).includes('aide_developpement/') ? new Response('', { status: 404 }) : vrai(u))) as typeof fetch
    try {
      const z = document.createElement('div')
      await rendre(z, new URLSearchParams())
      expect(z.textContent).toContain('Données en cours d’intégration')
      expect(z.querySelector('a[href="#/explorer/etat"]')).not.toBeNull()
    } finally {
      globalThis.fetch = vrai
      viderCache()
    }
  })

  it('toutes les lectures de données sont relatives au site', () => {
    expect(requetes.length).toBeGreaterThan(3)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })
})

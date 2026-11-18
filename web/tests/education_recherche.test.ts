// @vitest-environment happy-dom
// Écran « L’éducation et la recherche » (/explorer/education-recherche) sur des extraits réels de site/data
// (tests/fixtures/education_recherche/, servis avant les fixtures communes) : chiffres lus dans les données,
// statut et source de chaque montant, montant par étudiant signalé comme calcul du site, personnes morales seules
// nommées, écarts jamais additionnés, lexique neutre, accessibilité, état propre quand les fichiers manquent.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { viderCache } from '../src/donnees'
import { glossaire, lisible, nomRapport, premiereAnneeEsve, universitaire } from '../src/ecrans/education_recherche'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { entier, eur, eurLisible, md, sur100 } from '../src/util'
import { attendreQue, monterPage } from './aide-dom'

const RACINE = process.cwd()
const PROPRES = join(RACINE, 'tests', 'fixtures', 'education_recherche')
const COMMUNES = join(RACINE, 'tests', 'fixtures')
const PAGE = '#/explorer/education-recherche'
const lire = (rel: string) => JSON.parse(readFileSync(join(PROPRES, 'data', rel), 'utf8'))
const n = (t: string | null | undefined) => (t ?? '').replace(/\s+/g, ' ').trim()

const requetes: string[] = []
let absents: RegExp | null = null
let main: HTMLElement

/** Sert d'abord les fixtures de l'écran, puis les fixtures communes ; un motif d'absents simule un fichier manquant. */
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
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => n(main.textContent)
const tableau = (debutLegende: string) => {
  const t = Array.from(main.querySelectorAll('table')).find((x) => n(x.querySelector('caption')?.textContent).startsWith(debutLegende))
  expect(t, `tableau « ${debutLegende} »`).toBeDefined()
  return t as HTMLTableElement
}
const ligne = (t: HTMLTableElement, entete: string) => Array.from(t.querySelectorAll('tbody tr')).find((tr) => n(tr.querySelector('th')?.textContent).startsWith(entete)) as HTMLTableRowElement

beforeAll(() => {
  monterPage()
  servir()
  main = document.getElementById('contenu') as HTMLElement
})
afterEach(() => {
  absents = null
})

describe('écran éducation et recherche', () => {
  it('route : enfant de « Explorer », picto école, voisins existants, titre et description sans sigle', () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/education-recherche')!
    expect(r.parent).toBe('/explorer')
    expect(r.picto).toBe('ecole')
    expect(r.voisins?.every((v) => ROUTES.some((x) => x.chemin === v))).toBe(true)
    expect(`${r.titre} ${r.titrePage} ${r.description}`).not.toMatch(/\b(ANR|LFI|PLF|COFOG|SIES|RAP)\b/)
  })

  it('chiffre clé : dépense d’enseignement consolidée lue dans cofog.json, « sur 100 € », statut, source ; fil d’Ariane et picto', async () => {
    await ecran()
    expect(n(main.querySelector('h1')?.textContent)).toBe('L’éducation et la recherche')
    expect(main.querySelector('h1 .picto')).not.toBeNull()
    expect(main.querySelector('.fil-ariane [aria-current=page]')?.getAttribute('href')).toBe(PAGE)
    expect(texte()).toContain('Ce que versent les familles et les entreprises n’est pas dans les données reprises ici')
    const cofog = lire('cofog.json')
    const gf09 = cofog.fonctions.find((f: { code: string }) => f.code === 'GF09')
    const surlignes = main.querySelectorAll('.surligne')
    expect(surlignes).toHaveLength(1)
    expect(n(surlignes[0].textContent)).toBe(n(md(gf09.md)))
    const cle = surlignes[0].closest('[data-cle]')!
    expect(n(cle.textContent)).toContain(n(`en ${cofog.annee}, soit ${sur100((gf09.md / cofog.total) * 100)} sur 100 € de dépense publique`))
    expect(cle.querySelector('.badge')?.textContent).toBe('Tracé')
    expect(n(cle.querySelector('.source')?.textContent)).toContain(cofog.source)
    // Légende des trois statuts en tête de page.
    expect(main.querySelectorAll('.legende-statuts li').length).toBeGreaterThanOrEqual(3)
  })

  it('qui dépense : tableau par niveau et par administration lu dans l’arbre des administrations, colonnes non additionnées', async () => {
    await ecran()
    const adm = lire('arbre_administrations/racine.json')
    const fonction = (id: string) => adm.enfants.find((a: { id: string }) => a.id === id).enfants.find((f: { id: string }) => f.id.endsWith('/GF09'))
    const sous = (id: string, code: string) => fonction(id).enfants.find((s: { id: string }) => s.id.endsWith('/' + code)).md
    const t = tableau('Dépenses d’enseignement par niveau et par administration')
    expect(n(t.querySelector('caption')?.textContent)).toContain(adm.millesime)
    expect(Array.from(t.querySelectorAll('thead th')).map((th) => n(th.textContent))).toEqual(['Niveau ou domaine', 'État et ses organismes', 'Collectivités locales'])
    const ecole = Array.from(ligne(t, 'École maternelle et élémentaire').querySelectorAll('td')).map((td) => n(td.textContent))
    expect(ecole).toEqual([n(eurLisible(sous('S1311', 'GF0901') * 1e9)), n(eurLisible(sous('S1313', 'GF0901') * 1e9))])
    expect(n(ligne(t, 'Collège et lycée').querySelector('th')?.textContent)).toBe('Collège et lycée(enseignement secondaire)')
    expect(n(ligne(t, 'Autres dépenses').querySelector('th')?.textContent)).toBe('Autres dépenses d’enseignement(enseignement non classé ailleurs)')
    const total = Array.from(ligne(t, 'Total enseignement').querySelectorAll('td')).map((td) => n(td.textContent))
    expect(total).toEqual([n(eurLisible(fonction('S1311').md * 1e9)), n(eurLisible(fonction('S1313').md * 1e9))])
    expect(texte()).toContain('Les colonnes ne s’additionnent pas')
    expect(texte()).toContain('Les dépenses d’enseignement publiées sont celles de l’État et ses organismes (dont les universités) et des collectivités locales')
    // Chiffres clés par administration : montant, « sur 100 € » de ses dépenses, statut.
    const cles = Array.from(main.querySelectorAll('.cles li')).map((li) => n(li.textContent))
    const etat = adm.enfants.find((a: { id: string }) => a.id === 'S1311')
    expect(cles[0]).toContain(n(`${md(fonction('S1311').md)}pour l’enseignement par l’État et ses organismes en ${adm.millesime}, soit ${sur100((fonction('S1311').md / etat.md) * 100)} sur 100 € de leurs dépenses`))
    expect(cles[cles.length - 1]).toContain(n(entier(lire('education_recherche/index.json').totaux.etudiants.etudiants_hors_cpge)))
  })

  it('recherche : lignes « recherche et développement » écrites en toutes lettres, sans le sigle de la source', async () => {
    await ecran()
    const t = tableau('Dépenses de recherche par domaine et par administration')
    const lignes = Array.from(t.querySelectorAll('tbody th')).map((th) => n(th.textContent))
    expect(lignes).toContain('Recherche fondamentale')
    expect(lignes).toContain('Recherche et développement : santé')
    expect(lignes).toContain('Recherche et développement : affaires économiques')
    expect(Array.from(t.querySelectorAll('thead th')).map((th) => n(th.textContent))).toContain('Sécurité sociale')
    expect(texte()).not.toContain('R & D')
  })

  it('collectivités : série par année ; avant la première année publiée, la part enseignement supérieur est « non publié », jamais 0 €', async () => {
    await ecran()
    const esr = lire('education_recherche/collectivites_esr.json')
    const debut = premiereAnneeEsve(esr)!
    expect(debut).toBe(2015)
    const t = tableau('Budgets des collectivités pour la recherche et l’enseignement supérieur')
    expect(t.querySelectorAll('tbody tr')).toHaveLength(esr.national.length)
    for (const p of esr.national) {
      const cellules = Array.from(ligne(t, String(p.annee)).querySelectorAll('td'))
      expect(n(cellules[0].textContent)).toBe(p.qualite)
      expect(n(cellules[1].textContent)).toBe(n(eurLisible(p.rt_eur)))
      if (p.annee < debut) {
        expect(n(cellules[2].textContent), String(p.annee)).toBe('non publié')
        expect(cellules[2].querySelector('.motif-nonpub')).not.toBeNull()
        expect(n(cellules[3].textContent)).toBe('–')
      } else {
        expect(n(cellules[2].textContent)).toBe(n(eurLisible(p.esve_eur)))
        expect(n(cellules[3].textContent)).toBe(n(eurLisible(p.total_eur)))
      }
    }
    const der = esr.national[esr.national.length - 1]
    expect(texte()).toContain(n(`En ${der.annee} (montants ${der.qualite}s) : ${eurLisible(der.total_eur)}`))
    const types = Array.from(main.querySelectorAll('.barres[aria-label^="Montants"] .nom')).map((x) => n(x.textContent))
    expect(types.sort()).toEqual(Object.values(esr.types_collectivite as Record<string, string>).sort())
  })

  it('montant par étudiant : calcul du site signalé (statut approché), formule et limites publiées, rien avant la première année publiée', async () => {
    await ecran()
    const idx = lire('education_recherche/index.json')
    const etu = lire('education_recherche/etudiants.json')
    const nat = idx.cout_par_etudiant.national.filter((p: { annee: number }) => p.annee >= 2015)
    const der = nat[nat.length - 1]
    const para = Array.from(main.querySelectorAll('p')).find((p) => n(p.textContent).includes('Ce montant est un calcul du site, pas un chiffre publié'))!
    expect(para.querySelector('.badge')?.textContent).toBe('Approché')
    expect(n(para.textContent)).toContain(n(`donnent ${eur(der.cout_par_etudiant_eur)} par étudiant`))
    expect(n(para.textContent)).toContain(`inscrits en ${universitaire(der.annee)}`)
    expect(n(para.textContent)).toContain('Ce n’est donc pas la dépense totale pour un étudiant')
    const t = tableau('Montant par étudiant calculé par le site, à partir')
    const annees = Array.from(t.querySelectorAll('tbody th')).map((th) => Number(n(th.textContent)))
    expect(Math.min(...annees)).toBe(2015)
    expect(annees).toHaveLength(nat.length)
    // Aucun montant nul affiché pour les années où la dépense n'est pas publiée.
    expect(n(t.textContent)).not.toMatch(/(^|\s)0 €/)
    const details = Array.from(main.querySelectorAll('details')).find((d) => n(d.querySelector('summary')?.textContent) === 'Formule et limites du calcul')!
    expect(n(details.textContent)).toContain(n(lisible(idx.cout_par_etudiant.formule)))
    expect(n(details.textContent)).toContain('cout_par_etudiant_eur = budget_esve_eur / etudiants')
    expect(n(details.textContent)).toContain(n(etu.cout_par_etudiant.limites[0]))
    // Textes de données sans terme technique : ni « null », ni nom de champ, ni chemin de fichier.
    expect(n(details.textContent)).not.toMatch(/\bnull\b|correspondance_regions/)
    expect(texte()).not.toMatch(/[a-z_]+\.json/)
    // Par région : ordre du code officiel, « non calculé » quand le budget ou l'effectif manque.
    const parRegion = tableau('Montant par étudiant calculé par le site, par région')
    const noms = Array.from(parRegion.querySelectorAll('tbody th')).map((th) => n(th.textContent))
    expect(noms).toEqual(etu.cout_par_etudiant.regions.map((r: { nom: string }) => r.nom))
    expect(n(ligne(parRegion, 'Collectivités d').textContent)).toContain('non calculé')
  })

  it('montants par élève publiés par l’État : enseignement agricole, rapport en toutes lettres, lien vers les indicateurs ; rien pour l’école et l’université', async () => {
    await ecran()
    const liste = main.querySelector('ul[aria-label="Montants par élève ou par étudiant publiés par l’État"]')!
    const items = Array.from(liste.querySelectorAll('li'))
    expect(items).toHaveLength(2)
    const r143 = lire('realisations/143.json')
    const ind = r143.resultats_mesures.indicateurs.find((i: { id: string }) => i.id === '143-20')
    const der = ind.valeurs.filter((v: { valeur: number | null }) => typeof v.valeur === 'number').pop()
    expect(n(items[0].querySelector('.montant')?.textContent)).toBe(n(eur(der.valeur)))
    expect(n(items[0].textContent)).toContain(n(ind.sous_indicateur))
    expect(n(items[0].textContent)).toContain(`en ${der.annee}`)
    expect(n(items[0].textContent)).toContain('rapport annuel de performances')
    expect(items[0].querySelector('.badge')?.textContent).toBe('Tracé')
    expect(items[0].querySelector('a')?.getAttribute('href')).toBe('#/decisions/realisations?p=143')
    expect(items[1].querySelector('a')?.getAttribute('href')).toBe('#/decisions/realisations?p=142')
    expect(texte()).not.toMatch(/\b(RAP|PAP|PLR) \d{4}/)
    expect(texte()).toContain('Pour l’école, le collège, le lycée et l’université, aucun montant par élève ou par étudiant ne figure dans les données reprises par le site.')
  })

  it('lycées : région par défaut, nature des montants, personnes morales seules nommées, liste paginée, non nommés agrégés avec leur motif', async () => {
    await ecran()
    const idx = lire('education_recherche/index.json')
    const d = lire('education_recherche/lycees/11.json')
    const boutons = Array.from(main.querySelectorAll<HTMLButtonElement>('[data-region]'))
    expect(boutons.map((b) => b.dataset.region)).toEqual(Object.keys(idx.totaux.lycees).sort())
    expect(boutons.map((b) => b.getAttribute('aria-pressed'))).toEqual(['true', 'false', 'false'])
    expect(boutons.every((b) => b.type === 'button')).toBe(true)
    const zone = main.querySelector('#er-lycee')!
    expect(n(zone.querySelector('h3')?.textContent)).toBe(d.region.nom)
    expect(n(zone.textContent)).toContain(n(d.nature_des_montants))
    expect(n(zone.textContent)).toContain(n(`${eurLisible(d.total_eur)} au total`))
    expect(n(zone.textContent)).toContain(n(`${entier(d.non_nommes.nombre)} restent agrégés pour ${eurLisible(d.non_nommes.montant_eur)}`))
    expect(n(zone.textContent)).toContain('personne physique ou groupement de personnes physiques : 1')
    const c = (nom: string) => d.colonnes.indexOf(nom)
    const noms = () => Array.from(zone.querySelectorAll('#er-lycees-noms li > span:first-child')).map((s) => n(s.textContent))
    expect(noms()).toHaveLength(10)
    zone.querySelector<HTMLButtonElement>('#er-lycees-noms-plus')!.click()
    expect(noms()).toHaveLength(20)
    zone.querySelector<HTMLButtonElement>('#er-lycees-noms-plus')!.click()
    expect(noms()).toHaveLength(d.etablissements.length)
    expect(zone.querySelector('#er-lycees-noms-plus')).toBeNull()
    // Chaque nom affiché est celui d'une personne morale (catégorie juridique 2xxx à 9xxx) du fichier.
    for (const nom of noms()) {
      const e = d.etablissements.find((x: unknown[]) => x[c('nom')] === nom)
      expect(e, nom).toBeDefined()
      expect(String(e[c('categorie_juridique')]), nom).toMatch(/^[2-9]/)
    }
    expect(noms().length).toBeLessThanOrEqual(d.nommes.nombre)
    expect(n(zone.textContent)).toContain(`Ordre : ${d.ordre.regle}`)
    expect(n(zone.querySelector('.source')?.textContent)).toContain('licence Licence Ouverte 2.0')
  })

  it('lycées : changement de région sans navigation ; contrôle 2017 et sigle expliqué (Centre-Val de Loire), année publiée à 0 (Pays de la Loire)', async () => {
    await ecran()
    const zone = main.querySelector('#er-lycee')!
    main.querySelector<HTMLButtonElement>('[data-region="24"]')!.click()
    await attendreQue(() => n(zone.querySelector('h3')?.textContent) === 'Centre-Val de Loire')
    expect(location.hash).toBe(PAGE)
    expect(main.querySelector('[data-region="24"]')?.getAttribute('aria-pressed')).toBe('true')
    expect(main.querySelector('[data-region="11"]')?.getAttribute('aria-pressed')).toBe('false')
    const cvl = lire('education_recherche/lycees/24.json')
    expect(n(zone.textContent)).toContain(n(`Contrôle ${cvl.controles[0].annee} : somme des dotations ${eurLisible(cvl.controles[0].somme_des_dotations_eur)}`))
    expect(n(zone.textContent)).toContain('DGF : dotation globale de fonctionnement')
    expect(n(zone.querySelector('.source')?.textContent)).toContain('ODbL 1.0')
    main.querySelector<HTMLButtonElement>('[data-region="52"]')!.click()
    await attendreQue(() => n(zone.querySelector('h3')?.textContent) === 'Pays de la Loire')
    const t = Array.from(zone.querySelectorAll('table'))[0]
    expect(n(ligne(t, '2017').textContent)).toContain('(montants publiés à 0)')
    expect(n(ligne(t, '2018').textContent)).not.toContain('montants publiés à 0')
  })

  it('Agence nationale de la recherche : totaux, éditions, organismes nommés avec leur lecture, non nommés agrégés, sigles expliqués', async () => {
    await ecran()
    const idx = lire('education_recherche/index.json')
    const anr = lire('education_recherche/anr_projets.json')
    const etab = lire('education_recherche/anr_etablissements.json')
    const tp = idx.totaux.anr_pia_france2030
    expect(texte()).toContain(n(`${eurLisible(tp.aide_eur)} d’aide allouée à ${entier(tp.projets)} projets`))
    const t = tableau('Aide allouée par édition de l’action')
    expect(t.querySelectorAll('tbody tr')).toHaveLength(anr.pia_france2030.par_annee.length)
    const p0 = anr.pia_france2030.par_annee[0]
    expect(Array.from(ligne(t, String(p0.annee)).querySelectorAll('td')).map((td) => n(td.textContent))).toEqual([n(entier(p0.projets)), n(eurLisible(p0.aide_eur))])
    const pia = main.querySelector('#er-anr-pia')!
    const b = etab.pia_france2030
    const noms = Array.from(pia.querySelectorAll('#er-anr-pia-noms li > span:first-child')).map((s) => n(s.textContent))
    expect(noms).toHaveLength(10)
    expect(noms[0]).toBe(b.etablissements[0][b.colonnes.indexOf('denomination')])
    expect(n(pia.textContent)).toContain('ce montant n’est pas la somme reçue par l’organisme')
    expect(n(pia.textContent)).not.toContain('aide_projets_coordonnes_eur')
    expect(pia.querySelector('.badge')?.textContent).toBe('Approché')
    const cat = Array.from(pia.querySelectorAll('table tbody tr'))
    expect(cat).toHaveLength(b.non_nommes.par_categorie.length)
    expect(n(pia.textContent)).toContain('EPIC : établissement public à caractère industriel et commercial')
    expect(n(pia.textContent)).toContain('EPST : établissement public à caractère scientifique et technologique')
    // 2005-2009 : aide par partenaire publiée, statut tracé.
    const ancien = main.querySelector('#er-anr-ancien')!
    expect(ancien.querySelector('.badge')?.textContent).toBe('Tracé')
    expect(n(ancien.querySelector('#er-anr-ancien-noms li .montant')?.textContent)).toBe(
      n(eurLisible(etab.anr_2005_2009.etablissements[0][etab.anr_2005_2009.colonnes.indexOf('aide_allouee_eur')])),
    )
    expect(main.querySelector('a[href="#/beneficiaires?onglet=france2030"]')).not.toBeNull()
  })

  it('écarts entre sources : les deux montants côte à côte, l’écart publié, jamais leur somme', async () => {
    await ecran()
    const idx = lire('education_recherche/index.json')
    const t = tableau('Montants publiés par deux sources pour le même objet')
    expect(t.querySelectorAll('tbody tr')).toHaveLength(idx.ecarts.length)
    for (const e of idx.ecarts) {
      const tr = ligne(t, e.objet)
      expect(n(tr.textContent)).toContain(n(eurLisible(e.montant)))
      expect(n(tr.textContent)).toContain(n(eurLisible(e.autre_montant)))
      expect(n(tr.textContent)).toContain(n(eurLisible(e.ecart)))
      expect(n(tr.textContent)).not.toContain(n(eurLisible(e.montant + e.autre_montant)))
    }
    expect(texte()).toContain('ils ne s’additionnent pas et le site ne choisit pas entre eux')
  })

  it('sources et licences : chaque jeu cité avec producteur, millésime et licence ; aucune requête hors du site', async () => {
    requetes.length = 0
    viderCache()
    await ecran()
    const idx = lire('education_recherche/index.json')
    const h2 = Array.from(main.querySelectorAll('h2')).find((x) => n(x.textContent) === 'Sources et licences')!
    const items = Array.from(h2.nextElementSibling!.querySelectorAll('li'))
    expect(items).toHaveLength(idx.sources.length)
    for (const [i, s] of idx.sources.entries()) {
      expect(n(items[i].textContent)).toContain(n(`${s.producteur}, ${s.millesime}, ${s.licence}`))
      expect(items[i].querySelector('a')?.getAttribute('href')).toBe(s.page)
      expect(items[i].querySelector('a')?.getAttribute('rel')).toBe('noopener noreferrer')
    }
    for (const o of idx.licences.odbl) expect(texte()).toContain(o.producteur)
    expect(main.querySelector(`a[href="${idx.licences.odbl[0].url_licence}"]`)?.textContent).toBe('Open Database License 1.0')
    expect(requetes.length).toBeGreaterThan(0)
    for (const r of requetes) expect(r).toMatch(/^data\/[\w/.-]+\.json$/)
  })

  // Lexique partagé avec le test des données (docs/lexique_neutre.json), mêmes bornes de mot que web/tests/ecrans.test.ts.
  const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; exceptions: string[] }
  const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')

  it('neutralité et accessibilité : lexique partagé, ni tiret long ni style en ligne, tableaux légendés, titres hiérarchisés, sorties nommées', async () => {
    await ecran()
    let x = n(document.body.textContent).replace(/[\w./:-]*\/[\w./-]+/g, ' ')
    for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
    for (const r of LEXIQUE.regles) expect(x, r.raison).not.toMatch(borne(r.termes.join('|')))
    const route = ROUTES.find((r) => r.chemin === '/explorer/education-recherche')!
    for (const r of LEXIQUE.regles) expect(`${route.titre} ${route.titrePage} ${route.description} ${route.resume}`, r.raison).not.toMatch(borne(r.termes.join('|')))
    expect(main.textContent).not.toContain('—')
    expect(Array.from(main.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l') && !el.hasAttribute('data-g') && !el.hasAttribute('data-f'))).toHaveLength(0)
    for (const t of Array.from(main.querySelectorAll('table'))) {
      expect(n(t.querySelector('caption')?.textContent)).not.toBe('')
      for (const th of Array.from(t.querySelectorAll('th'))) expect(['col', 'row']).toContain(th.getAttribute('scope'))
      expect(t.closest('.tableau-defile')?.getAttribute('tabindex')).toBe('0')
    }
    const niveaux = Array.from(main.querySelectorAll('h1, h2, h3, h4')).map((t) => Number(t.tagName[1]))
    expect(niveaux[0]).toBe(1)
    expect(niveaux.filter((v) => v === 1)).toHaveLength(1)
    for (let i = 1; i < niveaux.length; i++) expect(niveaux[i], `titre ${i}`).toBeLessThanOrEqual(niveaux[i - 1] + 1)
    for (const b of Array.from(main.querySelectorAll('button'))) expect(b.getAttribute('type')).toBe('button')
    const sorties = Array.from(main.querySelectorAll('a[href^="#/"]')).filter((a) => !a.closest('.fil-ariane'))
    expect(sorties.length).toBeGreaterThan(4)
    for (const a of sorties) expect(n(a.textContent)).not.toMatch(/^(ici|cliquez ici|lien|en savoir plus)$/i)
    for (const a of Array.from(main.querySelectorAll('a[href^="http"]'))) {
      expect(a.getAttribute('href')).toMatch(/^https:\/\//)
      expect(a.getAttribute('rel')).toBe('noopener noreferrer')
    }
  })

  it('données absentes : état « en cours » propre, sorties présentes ; sans le fichier consolidé, pas de chiffre surligné', async () => {
    absents = /^data\/(education_recherche\/|cofog\.json|arbre_administrations\/)/
    viderCache()
    await ecran()
    expect(n(main.querySelector('h1')?.textContent)).toBe('L’éducation et la recherche')
    expect(main.querySelector('.en-cours')).not.toBeNull()
    expect(main.querySelector('.erreur')).toBeNull()
    expect(main.querySelector('a[href^="#/explorer/etat/detail"]')).not.toBeNull()
    // Situation des fixtures communes : l'arbre des administrations seul.
    absents = /^data\/(education_recherche\/|cofog\.json)/
    viderCache()
    await ecran()
    expect(main.querySelector('.surligne')).toBeNull()
    expect(main.querySelector('.erreur')).toBeNull()
    expect(main.querySelector('.en-cours')).not.toBeNull()
    tableau('Dépenses d’enseignement par niveau et par administration')
    absents = null
    viderCache()
  })

  it('outils : première année publiée, année universitaire, rapports et sigles en toutes lettres', () => {
    expect(premiereAnneeEsve(null)).toBeNull()
    expect(universitaire(2025)).toBe('2024-25')
    expect(universitaire(2010)).toBe('2009-10')
    expect(nomRapport('RAP 2025')).toBe('rapport annuel de performances 2025')
    expect(nomRapport('RAP 2015 (PLR 2015)')).toBe('rapport annuel de performances 2015 (loi de règlement 2015)')
    expect(glossaire(['Organismes de type EPST'])).toContain('EPST : ')
    expect(glossaire(['Organismes de type EPST'])).not.toContain('EPS : ')
    expect(glossaire(['Aucun sigle ici'])).toBe('')
    expect(lisible('montant (etudiants.json) ; voir beneficiaires/france2030.json')).toBe('montant ; voir France 2030 par bénéficiaire')
    expect(lisible('Valeur null quand le budget manque')).toBe('Valeur absente quand le budget manque')
  })
})

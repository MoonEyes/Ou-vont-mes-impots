// @vitest-environment happy-dom
// Écran « L’éducation et la recherche » (/explorer/education-recherche) sur des extraits réels de site/data
// (tests/fixtures/education_recherche/, servis avant les fixtures communes) : chiffres lus dans les données,
// statut et source de chaque montant, montant par étudiant signalé comme calcul du site, personnes morales seules
// nommées, écarts jamais additionnés, lexique neutre, accessibilité, état propre quand les fichiers manquent.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { viderCache } from '../src/donnees'
import { glossaire, lisible, nomNiveau, nomRapport, premiereAnneeEsve, universitaire } from '../src/ecrans/education_recherche'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { entier, eur, eurLisible, md, pct, sur100 } from '../src/util'
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
    expect(texte()).toContain('Tu vois aussi la part que paient au départ les familles et les entreprises, et la dépense moyenne par élève ou étudiant')
    expect(texte()).toContain('La page ne montre pas ce que paie une famille en particulier')
    expect(texte()).not.toContain('Ce que versent les familles et les entreprises n’est pas dans les données')
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
    const cles = Array.from(main.querySelectorAll('ul.cles[aria-label="Chiffres clés de l’éducation"] li')).map((li) => n(li.textContent))
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

  it('collectivités : série par année ; avant la première année publiée, la part enseignement supérieur et le total sont « non publié », jamais 0 €', async () => {
    await ecran()
    const esr = lire('education_recherche/collectivites_esr.json')
    const debut = premiereAnneeEsve(esr)!
    expect(debut).toBe(2015)
    // Les données publient l'absence en null (correctif du 18/11/2026), plus en 0.
    const absentes = esr.national.filter((p: { esve_eur: number | null }) => p.esve_eur === null)
    expect(absentes.map((p: { annee: number }) => p.annee)).toEqual(esr.national.filter((p: { annee: number }) => p.annee < debut).map((p: { annee: number }) => p.annee))
    expect(absentes.every((p: { total_eur: number | null }) => p.total_eur === null)).toBe(true)
    const t = tableau('Budgets des collectivités pour la recherche et l’enseignement supérieur')
    expect(t.querySelectorAll('tbody tr')).toHaveLength(esr.national.length)
    for (const p of esr.national) {
      const cellules = Array.from(ligne(t, String(p.annee)).querySelectorAll('td'))
      expect(n(cellules[0].textContent)).toBe(p.qualite)
      expect(n(cellules[1].textContent)).toBe(n(eurLisible(p.rt_eur)))
      if (p.annee < debut) {
        for (const k of [2, 3]) {
          expect(n(cellules[k].textContent), `${p.annee} colonne ${k}`).toBe('non publié')
          expect(cellules[k].querySelector('.motif-nonpub')).not.toBeNull()
        }
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

  it('compte de l’éducation : familles et entreprises (parts publiées séparément), dépense intérieure, dépense moyenne par niveau, année provisoire signalée, statut et source', async () => {
    await ecran()
    const idx = lire('education_recherche/index.json')
    const ce = lire('education_recherche/compte_education.json')
    expect(idx.fichiers.compte_education).toBe('education_recherche/compte_education.json')
    const t0 = idx.totaux.compte_education
    // Chiffres attendus du tableur de l'Insee (France, portrait social 2025), 2024 provisoire.
    expect([t0.annee, t0.provisoire, t0.menages_pct, t0.entreprises_pct, t0.die_md_eur_courants]).toEqual([2024, true, 7.7, 10.3, 197.1])
    const bloc = main.querySelector('#er-compte')!
    expect(bloc).not.toBeNull()
    expect(n(bloc.querySelector('h2')?.textContent)).toBe('Toute la dépense d’éducation, familles et entreprises comprises')
    expect(n(bloc.textContent)).toContain(n(`En 2024 (provisoire), cette dépense intérieure d’éducation est de ${md(197.1)}, soit ${pct(6.8)} de la richesse produite`))
    const cles = Array.from(bloc.querySelectorAll('ul.cles li'))
    expect(cles).toHaveLength(3)
    expect(n(cles[0].querySelector('strong')?.textContent)).toBe(n(sur100(t0.menages_pct)))
    expect(n(cles[0].textContent)).toContain('payés au départ par les familles en 2024 (provisoire)')
    expect(n(cles[1].querySelector('strong')?.textContent)).toBe(n(sur100(t0.entreprises_pct)))
    expect(n(cles[1].textContent)).toContain('par les entreprises en 2024 (provisoire)')
    expect(n(cles[2].querySelector('strong')?.textContent)).toBe(n(eur(t0.depense_moyenne_eur)))
    for (const li of cles) expect(li.querySelector('.badge')?.textContent).toBe('Tracé')
    // Les deux parts ne sont jamais additionnées.
    expect(n(bloc.textContent)).not.toContain(n(sur100(t0.menages_pct + t0.entreprises_pct)))
    expect(n(bloc.textContent)).toContain('le site ne les additionne pas')
    // Financement initial : une colonne par année publiée, la dernière marquée provisoire ; ligne « dont » présente.
    const fin = tableau('Part de chaque financeur dans la dépense intérieure d’éducation')
    const entetes = Array.from(fin.querySelectorAll('thead th')).map((th) => n(th.textContent))
    expect(entetes).toEqual(['Financeur', ...ce.financement_initial.annees.map((a: number, i: number) => (ce.financement_initial.provisoire[i] ? `${a} (provisoire)` : String(a)))])
    expect(entetes[entetes.length - 1]).toBe('2024 (provisoire)')
    const menages = Array.from(ligne(fin, 'Ménages (familles)').querySelectorAll('td')).map((td) => n(td.textContent))
    expect(menages[menages.length - 1]).toBe(n(pct(7.7)))
    expect(n(ligne(fin, 'Entreprises').querySelector('td:last-child')?.textContent)).toBe(n(pct(10.3)))
    expect(ligne(fin, 'dont ministères')).toBeDefined()
    expect(n(fin.closest('.tableau-defile')!.nextElementSibling?.textContent)).not.toMatch(/controle_somme/)
    // Dépense moyenne par niveau : chiffres publiés, sigles en toutes lettres.
    const niv = tableau('Dépense moyenne par élève ou étudiant en 2024 (provisoire)')
    const val = (debut: string) => n(ligne(niv, debut).querySelector('td')?.textContent)
    expect(val('Ensemble : premier degré (école)')).toBe(n(eur(9080)))
    expect(val('Collège')).toBe(n(eur(10450)))
    expect(val('Lycée général et technologique')).toBe(n(eur(13020)))
    expect(val('Ensemble : second degré')).toBe(n(eur(11660)))
    expect(val('Sections de technicien supérieur')).toBe(n(eur(17220)))
    expect(n(niv.textContent)).not.toMatch(/STS|CPGE|²|³/)
    expect(niv.querySelectorAll('tbody tr')).toHaveLength(ce.depense_moyenne_par_niveau.niveaux.length)
    expect(n(bloc.textContent)).toContain('Ces montants couvrent toute la dépense d’éducation, tous financeurs confondus.')
    // Série 1980-2024 en euros constants, année provisoire signalée.
    const evo = tableau('Dépense intérieure d’éducation et dépense moyenne par élève ou étudiant, 1980 à 2024')
    expect(evo.querySelectorAll('tbody tr')).toHaveLength(ce.depense_moyenne_evolution.annees.length)
    expect(n(evo.querySelector('tbody th')?.textContent)).toBe('2024 (provisoire)')
    expect(Array.from(ligne(evo, '1980').querySelectorAll('td')).map((td) => n(td.textContent))).toEqual(
      [n(md(90)), n(pct(6.6)), n(eur(3810)), n(eur(6910)), n(eur(9840)), n(eur(5520))],
    )
    expect(n(bloc.querySelector('.source')?.textContent)).toContain('Insee, France, portrait social')
    expect(n(bloc.querySelector('.source')?.textContent)).toContain('Licence Ouverte 2.0')
    expect(n(bloc.textContent)).not.toMatch(/(^|\s)0 €/)
  })

  it('montant par étudiant : calcul du site retiré (dépenses et effectifs de deux années différentes), raison écrite', async () => {
    await ecran()
    expect(texte()).toContain('Le site ne calcule pas de montant par étudiant')
    expect(texte()).not.toMatch(/par étudiant calculé par le site|calcul du site, pas un chiffre publié/)
    expect(main.querySelector('#er-cout-regions')).toBeNull()
    expect(texte()).not.toMatch(/[a-z_]+\.json/)
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
    expect(texte()).toContain('Pour l’école, le collège, le lycée et l’université, les rapports de performances repris par le site ne publient pas de dépense de l’État par élève ou par étudiant. La dépense moyenne de tous les financeurs par élève ou étudiant est donnée plus haut (compte de l’éducation).')
  })

  it('lycées : région par défaut, nature des montants, personnes morales seules nommées, liste paginée, non nommés agrégés avec leur motif', async () => {
    await ecran()
    const idx = lire('education_recherche/index.json')
    const d = lire('education_recherche/lycees/11.json')
    const boutons = Array.from(main.querySelectorAll<HTMLButtonElement>('#er-region [role="radio"]'))
    expect(boutons.map((b) => b.value)).toEqual(Object.keys(idx.totaux.lycees).sort())
    expect(boutons.map((b) => b.getAttribute('aria-checked'))).toEqual(['true', 'false', 'false'])
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
    main.querySelector<HTMLButtonElement>('#er-region [value="24"]')!.click()
    await attendreQue(() => n(zone.querySelector('h3')?.textContent) === 'Centre-Val de Loire')
    expect(location.hash).toBe(PAGE)
    expect(main.querySelector('#er-region [value="24"]')?.getAttribute('aria-checked')).toBe('true')
    expect(main.querySelector('#er-region [value="11"]')?.getAttribute('aria-checked')).toBe('false')
    const cvl = lire('education_recherche/lycees/24.json')
    expect(n(zone.textContent)).toContain(n(`Contrôle ${cvl.controles[0].annee} : somme des dotations ${eurLisible(cvl.controles[0].somme_des_dotations_eur)}`))
    expect(n(zone.textContent)).toContain('DGF : dotation globale de fonctionnement')
    expect(n(zone.querySelector('.source')?.textContent)).toContain('ODbL 1.0')
    main.querySelector<HTMLButtonElement>('#er-region [value="52"]')!.click()
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
    expect(n(pia.textContent)).toContain('montants non publiés en dernier')
    expect(n(pia.textContent)).not.toMatch(/\bnull\b/)
    expect(pia.querySelector('.badge')?.textContent).toBe('Approché')
    const cat = Array.from(pia.querySelectorAll('table tbody tr'))
    expect(cat).toHaveLength(b.non_nommes.par_categorie.length)
    // Catégorie sans projet coordonné : montant null dans les données, « non publié » à l'écran, jamais 0 €, en fin de tableau.
    const sansMontant = b.non_nommes.par_categorie.filter((k: { aide_projets_coordonnes_eur: number | null }) => k.aide_projets_coordonnes_eur === null)
    expect(sansMontant.length).toBeGreaterThan(0)
    for (const k of sansMontant) {
      const tr = cat.find((x) => n(x.querySelector('th')?.textContent) === k.categorie)!
      expect(n(tr.querySelector('td:last-child')?.textContent), k.categorie).toBe('non publié')
      expect(tr.querySelector('td:last-child .motif-nonpub')).not.toBeNull()
    }
    expect(n(cat[cat.length - 1].querySelector('td:last-child')?.textContent)).toBe('non publié')
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
    expect(main.querySelector('#er-compte')).toBeNull()
    // Situation des fixtures communes : l'arbre des administrations seul.
    absents = /^data\/(education_recherche\/|cofog\.json)/
    viderCache()
    await ecran()
    expect(main.querySelector('.surligne')).toBeNull()
    expect(main.querySelector('.erreur')).toBeNull()
    expect(main.querySelector('.en-cours')).not.toBeNull()
    tableau('Dépenses d’enseignement par niveau et par administration')
    expect(texte()).toContain('Ce que versent les familles et les entreprises n’est pas dans les données reprises ici')
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
    expect(nomNiveau('STS²')).toBe('Sections de technicien supérieur')
    expect(nomNiveau('CPGE³')).toBe('Classes préparatoires aux grandes écoles')
    expect(nomNiveau('Collège')).toBe('Collège')
    expect(lisible('montant (etudiants.json) ; voir beneficiaires/france2030.json')).toBe('montant ; voir France 2030 par bénéficiaire')
    expect(lisible('Valeur null quand le budget manque')).toBe('Valeur absente quand le budget manque')
    expect(lisible('montant décroissant (montants null en dernier)')).toBe('montant décroissant (montants non publiés en dernier)')
    expect(lisible('reprises du tableur (compte_education.json). Suite')).toBe('reprises du tableur. Suite')
  })
})

// @vitest-environment happy-dom
// Écran « La fonction publique » (/explorer/fonction-publique) sur des fixtures réelles (copies de site/data/fonction_publique,
// arbre/racine.json et effectifs/141.json déjà présents) : chaque chiffre attendu est relu dans les fixtures, jamais écrit en dur.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher, titreDocument } from '../src/routeur'
import { viderCache } from '../src/donnees'
import { eur, md, pct, sur100 } from '../src/util'
import { coutMoyen, evolution, lisible, personnes, type Programme, REGLE_MINISTERES } from '../src/ecrans/fonction_publique'
import { monterPage, requetes } from './aide-dom'

type V = number | null
interface LigneSerie {
  id: string
  libelle: string
  niveau: string
  parent: string | null
  valeurs: Record<string, V[]>
}
interface LigneTableau {
  rubrique: string | null
  libelle: string
  valeurs: V[]
}
interface Tableau {
  titre: string
  colonnes: string[]
  lignes: LigneTableau[]
}
interface Ministere {
  ministere: string
  programmes: Programme[]
  titre2_eur: number
}

const FIX = join(process.cwd(), 'tests', 'fixtures', 'data')
const lire = (f: string) => JSON.parse(readFileSync(join(FIX, f), 'utf8'))
const idx = lire('fonction_publique/index.json') as {
  reperes: { budget_etat: { titre2_eur: number; millesime_titre2: string }; conseils: { exercice: number; ae_eur: number } }
  ecarts_entre_sources: { grandeur: string; valeurs: { source: string; valeur: number }[]; note: string }[]
}
const ser = lire('fonction_publique/effectifs_series.json') as { source: string; millesime: string; series: { cle: string; annee: number; revisee: boolean }[]; lignes: LigneSerie[] }
const emp = lire('fonction_publique/emploi.json') as { annee: number; tableaux: Record<string, Tableau> }
const min = lire('fonction_publique/ministeres.json') as { ministeres: Ministere[] }
const ter = lire('fonction_publique/territoires.json') as { annee: number; colonnes: string[]; departements: Record<string, { libelle: string; valeurs: V[] }>; regions: Record<string, { libelle: string; valeurs: V[] }> }
const cab = lire('fonction_publique/cabinets.json') as { situations: { annee: number; total: { effectif_total: number; membres_cabinet: number } }[] }
const racine = lire('arbre/racine.json') as { md: number; millesime: string }

const norm = (s: string | null | undefined) => (s ?? '').replace(/\s+/g, ' ').trim()
const nf1 = (x: number) => new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(x)
const CHEMIN = '#/explorer/fonction-publique'
const dans = (id: string) => `section[aria-labelledby="${id}"]`

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => norm(main.textContent)

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('écran « La fonction publique »', () => {
  it('route : rayon du hub Explorer, famille et picto existants, titre et description dans les limites', () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/fonction-publique')!
    expect(r).toBeDefined()
    expect(r.parent).toBe('/explorer')
    expect(r.famille).toBe('etat')
    expect(r.picto).toBe('menages')
    expect(r.description.length).toBeGreaterThanOrEqual(70)
    expect(r.description.length).toBeLessThanOrEqual(200)
    expect(titreDocument(r).length).toBeLessThanOrEqual(100)
    expect((r.voisins ?? []).length).toBeGreaterThan(0)
    for (const v of r.voisins ?? []) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
  })

  it('combien de personnes : trois versants lus dans la série de l’Insee, part sur 100 agents, statut, source, autre publication signalée', async () => {
    await ecran(CHEMIN)
    expect(norm(main.querySelector('h1')?.textContent)).toBe('La fonction publique')
    expect(Array.from(main.querySelectorAll('.fil-ariane a')).map((a) => a.textContent)).toEqual(['Accueil', 'Explorer', 'Fonction publique'])
    expect(main.querySelector('.erreur')).toBeNull()
    const i = ser.series.length - 1
    const ens = ser.lignes.find((l) => l.niveau === 'ensemble')!.valeurs.ensemble[i]!
    const versants = ser.lignes.filter((l) => l.niveau === 'versant')
    const cartes = main.querySelectorAll(`${dans('fp-combien')} .cles li`)
    expect(cartes).toHaveLength(versants.length)
    versants.forEach((l, k) => {
      const t = norm(cartes[k].textContent)
      const n = l.valeurs.ensemble[i]!
      expect(t).toContain(norm(personnes(n)))
      expect(t).toContain(`${norm(nf1((n / ens) * 100))} sur 100 agents publics`)
      expect(t).toContain('Tracé')
    })
    expect(texte()).toContain(`Fin ${ser.series[i].annee}, ${norm(personnes(ens))} personnes travaillent dans la fonction publique`)
    // Détail par type d'employeur lu dans la série (ministères, établissements publics, communes...).
    const dont = ser.lignes.filter((l) => l.parent === versants[0].id && l.niveau === 'type_employeur')
    for (const d of dont) expect(norm(cartes[0].textContent)).toContain(norm(personnes(d.valeurs.ensemble[i]!)))
    // L'autre publication de l'Insee pour la même date est signalée, sans être tranchée.
    const autre = idx.ecarts_entre_sources.flatMap((e) => e.valeurs).find((v) => Math.abs(v.valeur - ens) >= 0.05 && Math.abs(v.valeur - ens) < 5)!
    expect(norm(main.querySelector(dans('fp-combien'))?.textContent)).toContain(norm(personnes(autre.valeur)))
    expect(norm(main.querySelector(`${dans('fp-combien')} .source`)?.textContent)).toBe(norm(`${ser.source} (${ser.millesime})`))
  })

  it('dépenses de personnel de l’État : un seul chiffre surligné, en euros, part sur 100 € du budget de la même année, billet et liste', async () => {
    await ecran(CHEMIN)
    const b = idx.reperes.budget_etat
    expect(racine.millesime).toBe(b.millesime_titre2)
    const surlignes = main.querySelectorAll('.surligne')
    expect(surlignes).toHaveLength(1)
    expect(norm(surlignes[0].textContent)).toBe(norm(md(b.titre2_eur / 1e9)))
    const cle = surlignes[0].closest('[data-cle]')!
    expect(cle).not.toBeNull()
    const part = (b.titre2_eur / (racine.md * 1e9)) * 100
    expect(norm(cle.textContent)).toContain(norm(`soit ${sur100(part)} sur 100 € dépensés par l’État cette année-l`))
    expect(cle.textContent).toContain('Tracé')
    expect(cle.querySelectorAll('.source')).toHaveLength(2)
    // Billet de 100 € et sa version texte : parts dont la somme fait 100 € à l'arrondi près.
    expect(main.querySelector(`${dans('fp-masse')} .billet .billet-large`)).not.toBeNull()
    const parts = Array.from(main.querySelectorAll(`${dans('fp-masse')} .parts li`))
    expect(parts.length).toBe(5)
    const somme = parts.map((li) => Number(norm(li.querySelector('.p-montant')?.textContent).replace(/[\s€]/g, '').replace(',', '.'))).reduce((a, c) => a + c, 0)
    expect(Math.abs(somme - 100)).toBeLessThan(0.3)
    const tri = [...min.ministeres].sort((a, c) => c.titre2_eur - a.titre2_eur)
    expect(norm(parts[0].textContent)).toContain(tri[0].ministere)
    // Pas de part « sur 100 € de toute la dépense publique » : dit en clair, dans le motif « non publié ».
    expect(norm(main.querySelector(`${dans('fp-masse')} .absent`)?.textContent)).toContain('pas encore repris dans les données du site')
    expect(main.querySelector(`${dans('fp-masse')} a[href="#/local"]`)?.textContent).toBe('Budget de ma commune')
    const hopitaux = ROUTES.find((r) => /hopit/i.test(r.chemin))
    if (hopitaux) expect(main.querySelector(`${dans('fp-masse')} a[href="#${hopitaux.chemin}"]`)).not.toBeNull()
  })

  it('par ministère : ordre affiché (dépenses décroissantes), totaux, coût complet moyen approché', async () => {
    await ecran(CHEMIN)
    const table = main.querySelector(`${dans('fp-ministeres')} table`)!
    expect(norm(table.querySelector('caption')?.textContent)).toMatch(/^Emplois votés pour \d{4} et dépenses de personnel \d{4}, par ministère$/)
    const lignes = Array.from(table.querySelectorAll('tbody tr'))
    const tri = [...min.ministeres].sort((a, c) => c.titre2_eur - a.titre2_eur)
    expect(lignes.map((tr) => norm(tr.querySelector('th')?.textContent))).toEqual(tri.map((m) => m.ministere))
    expect(main.querySelector(`${dans('fp-ministeres')} [data-regle-ordre]`)?.textContent).toBe(REGLE_MINISTERES)
    const tous = coutMoyen(min.ministeres.flatMap((m) => m.programmes))
    expect(norm(table.querySelector('tfoot')?.textContent)).toContain(norm(eur(tous.moyen!)))
    expect(norm(lignes[0].textContent)).toContain(norm(eur(coutMoyen(tri[0].programmes).moyen!)))
    // Les programmes exclus du calcul sont nommés, et ce sont bien ceux sans dépenses ou sans emplois publiés.
    for (const p of tous.exclus) {
      expect((p.etpt ?? 0) > 0 && (p.titre2_eur ?? 0) > 0).toBe(false)
      expect(texte()).toContain(`${p.programme} (${p.libelle})`)
    }
    expect(norm(main.querySelector(dans('fp-ministeres'))?.textContent)).toContain('Approché')
    expect(main.querySelector(`${dans('fp-ministeres')} a[href="#/beneficiaires/programme"]`)).not.toBeNull()
  })

  it('coût moyen, évolution, personnes : calculs purs', () => {
    const p = (programme: string, etpt: V, titre2_eur: V): Programme => ({ programme, libelle: programme, etpt, titre2_eur })
    const r = coutMoyen([p('1', 10, 1000), p('2', 5, null), p('3', null, 300), p('4', 30, 3000)])
    expect(r.moyen).toBe(100)
    expect(r.exclus.map((x) => x.programme)).toEqual(['2', '3'])
    expect(coutMoyen([p('2', 5, null)]).moyen).toBeNull()
    expect(norm(evolution(0.8))).toBe('+0,8 %')
    expect(norm(evolution(-0.1))).toBe('−0,1 %')
    expect(norm(evolution(0))).toBe('0,0 %')
    expect(norm(personnes(2589))).toBe('2 589 000')
  })

  it('rémunérations : moyennes seulement, salaire par catégorie signalé comme absent, rien d’individuel', async () => {
    await ecran(CHEMIN)
    const zone = norm(main.querySelector(dans('fp-remunerations'))?.textContent)
    const tous = coutMoyen(min.ministeres.flatMap((m) => m.programmes))
    expect(zone).toContain(`Coût complet moyen d’un emploi de l’État : ${norm(eur(tous.moyen!))} par an`)
    expect(zone).toContain('Approché')
    expect(zone).toContain('Ce n’est pas un salaire')
    expect(norm(main.querySelector(`${dans('fp-remunerations')} .absent`)?.textContent)).toContain('Salaire moyen par catégorie (A, B, C)')
    expect(zone).toContain('Aucune rémunération individuelle n’est publiée ici.')
    // Ni prestataires nommés ni barème des élus : ces fichiers ne sont pas lus par cette page.
    expect(requetes.some((u) => /fonction_publique\/(conseils|indemnites_elus)\.json/.test(u))).toBe(false)
  })

  it('qui sont les agents : catégories, statuts et part de femmes de l’Insee, absences dites en mots', async () => {
    await ecran(CHEMIN)
    const table = main.querySelector(`${dans('fp-qui')} table`)!
    const t = emp.tableaux.figure_3
    const a = t.lignes.find((l) => l.libelle === 'Catégorie A')!
    const tr = Array.from(table.querySelectorAll('tbody tr')).find((x) => norm(x.querySelector('th')?.textContent) === 'Catégorie A')!
    expect(Array.from(tr.querySelectorAll('td')).map((td) => norm(td.textContent))).toEqual(a.valeurs.map((v) => norm(pct(v!))))
    const mil = Array.from(table.querySelectorAll('tbody tr')).find((x) => norm(x.querySelector('th')?.textContent) === 'Militaires')!
    expect(norm(mil.textContent)).toContain('sans objet')
    expect(norm(table.textContent)).toContain('Part de femmes')
    expect(Array.from(table.querySelectorAll('thead th')).map((th) => norm(th.textContent))).toEqual(['Sur 100 agents', 'État', 'Territoriale', 'Hospitalière', 'Ensemble'])
  })

  it('évolutions : phrase de l’Insee, statuts, entrées et sorties, série longue avec les deux versions des années recalculées', async () => {
    await ecran(CHEMIN)
    const zone = main.querySelector(dans('fp-evolutions'))!
    const f1 = emp.tableaux.figure_1
    const iEvol = f1.colonnes.findIndex((c) => /Évolution/.test(c) && /Y compris/.test(c))
    const ens = f1.lignes.find((l) => /^Effectifs/.test(l.rubrique ?? '') && /^Ensemble/.test(l.libelle))!.valeurs[iEvol]!
    expect(norm(zone.textContent)).toContain(`Entre fin ${emp.annee - 1} et fin ${emp.annee}, le nombre de personnes employées dans la fonction publique ${ens >= 0 ? 'augmente' : 'diminue'} de ${norm(pct(Math.abs(ens)))}`)
    const etat = f1.lignes.find((l) => /^Effectifs/.test(l.rubrique ?? '') && /l'État/.test(l.libelle))!.valeurs[iEvol]!
    expect(norm(zone.textContent)).toContain(`État ${norm(evolution(etat))}`)
    // Série longue : les deux versions d'une année recalculée sont présentes, chacune avec sa valeur.
    const rev = ser.series.find((s) => s.revisee)!
    const iPub = ser.series.findIndex((s) => s.annee === rev.annee && !s.revisee)
    const iRev = ser.series.indexOf(rev)
    const ensSerie = ser.lignes.find((l) => l.niveau === 'ensemble')!
    const ligne = (etiquette: string) => Array.from(zone.querySelectorAll('tbody tr')).find((tr) => norm(tr.querySelector('th')?.textContent) === etiquette)
    expect(norm(ligne(`${rev.annee} (publiée à l’époque)`)?.textContent)).toContain(norm(personnes(ensSerie.valeurs.ensemble[iPub]!)))
    expect(norm(ligne(`${rev.annee} (recalculée)`)?.textContent)).toContain(norm(personnes(ensSerie.valeurs.ensemble[iRev]!)))
    expect(norm(zone.textContent)).toContain('Les deux sont données, sans choisir.')
    // Entrées et sorties de la dernière année, par versant puis par statut.
    const f5 = emp.tableaux.figure_5
    const der = String(Math.max(...f5.lignes.map((l) => Number(l.libelle))))
    const tot = f5.lignes.find((l) => l.libelle === der && /^Ensemble/.test(l.rubrique ?? ''))!
    const trTot = ligne('Ensemble de la fonction publique')
    expect(trTot).toBeDefined()
    expect(Array.from(trTot!.querySelectorAll('td')).map((td) => norm(td.textContent))).toEqual(tot.valeurs.map((v) => norm(personnes(v!))))
  })

  it('deux façons de compter et écarts entre sources : valeurs côte à côte, jamais additionnées ni tranchées', async () => {
    await ecran(CHEMIN)
    const deux = norm(main.querySelector(dans('fp-deux'))?.textContent)
    expect(deux).toContain('posés côte à côte, jamais additionnés')
    expect(main.querySelector(`${dans('fp-deux')} a[href="#/explorer/operateurs"]`)).not.toBeNull()
    const ecarts = main.querySelector(dans('fp-ecarts'))!
    for (const e of idx.ecarts_entre_sources) {
      expect(norm(ecarts.textContent)).toContain(e.note)
      for (const v of e.valeurs) expect(norm(ecarts.textContent)).toContain(norm(`${v.source} : ${nf1(v.valeur)}`))
    }
    expect(norm(ecarts.textContent)).not.toMatch(/retenue?\b|la bonne valeur|plus fiable/i)
    expect(ecarts.querySelector('table caption')).not.toBeNull()
  })

  it('département ou région : choix sans rechargement, adresse ?dep= reprise, lien vers le budget du département', async () => {
    await ecran(CHEMIN)
    const choix = main.querySelector<HTMLSelectElement>('#fp-territoire')!
    expect(choix.querySelectorAll('optgroup[label="Départements"] option')).toHaveLength(Object.keys(ter.departements).length)
    expect(choix.querySelectorAll('optgroup[label="Régions"] option')).toHaveLength(Object.keys(ter.regions).length)
    const dep = Object.keys(ter.departements).find((c) => c === '44') ?? Object.keys(ter.departements)[0]
    const d = ter.departements[dep]
    choix.value = `d-${dep}`
    choix.dispatchEvent(new Event('change', { bubbles: true }))
    const zone = main.querySelector('#fp-zone-territoire')!
    expect(norm(zone.querySelector('caption')?.textContent)).toContain(d.libelle)
    const j = ter.colonnes.indexOf('ensemble_hors_militaires_milliers')
    expect(norm(zone.textContent)).toContain(norm(personnes(d.valeurs[j]!)))
    expect(zone.querySelector(`a[href^="#/local/departement?dep=${dep}"]`)).not.toBeNull()
    expect(zone.getAttribute('aria-live')).toBe('polite')
    expect(zone.querySelector('.tableau-defile')?.getAttribute('role')).toBe('region')
    const reg = Object.keys(ter.regions)[0]
    choix.value = `r-${reg}`
    choix.dispatchEvent(new Event('change', { bubbles: true }))
    expect(norm(zone.querySelector('caption')?.textContent)).toContain(ter.regions[reg].libelle)
    await ecran(`${CHEMIN}?dep=${dep}`)
    expect(main.querySelector<HTMLSelectElement>('#fp-territoire')!.value).toBe(`d-${dep}`)
    expect(norm(main.querySelector('#fp-zone-territoire caption')?.textContent)).toContain(d.libelle)
  })

  it('cabinets et conseils : totaux seulement, règle de non-addition affichée', async () => {
    await ecran(CHEMIN)
    const zone = main.querySelector(dans('fp-cabinets'))!
    const der = [...cab.situations].sort((a, c) => a.annee - c.annee).pop()!
    expect(zone.querySelectorAll('.postes li')).toHaveLength(3)
    expect(norm(zone.textContent)).toContain(norm(new Intl.NumberFormat('fr-FR').format(der.total.effectif_total)))
    expect(norm(zone.textContent)).toContain('jamais par personne')
    expect(norm(zone.textContent)).toContain('Aucun de ces montants ne s’ajoute aux chiffres plus haut.')
    expect(norm(zone.textContent)).toContain(String(idx.reperes.conseils.exercice))
  })

  it('accessibilité et neutralité : tableaux légendés, en-têtes portés, aucun style en ligne, aucun tiret long, lexique neutre', async () => {
    await ecran(CHEMIN)
    for (const t of Array.from(main.querySelectorAll('table'))) {
      expect(norm(t.querySelector('caption')?.textContent)).not.toBe('')
      for (const th of Array.from(t.querySelectorAll('thead th'))) {
        expect(th.getAttribute('scope')).toBe('col')
        expect(norm(th.textContent)).not.toBe('')
      }
      for (const tr of Array.from(t.querySelectorAll('tbody tr, tfoot tr'))) expect(tr.querySelector('th[scope="row"], th[scope="rowgroup"]')).not.toBeNull()
    }
    for (const z of Array.from(main.querySelectorAll('.tableau-defile'))) expect(z.getAttribute('role')).toBe('region')
    expect(Array.from(main.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l') && !el.hasAttribute('data-g') && !el.hasAttribute('data-f'))).toHaveLength(0)
    expect(main.textContent).not.toContain('—')
    for (const t of Array.from(main.querySelectorAll('h1, h2, h3'))) expect(t.textContent ?? '').not.toMatch(/\b(gaspillage|seulement|énorme|opaque|scandale|trop)\b/i)
    const lexique = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; exceptions: string[] }
    const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
    const verifier = (brut: string, ou: string) => {
      let x = brut.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
      for (const e of lexique.exceptions) x = x.split(e).join(' ')
      for (const r of lexique.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
    }
    verifier(document.body.textContent ?? '', 'page')
    verifier(document.title, 'titre du document')
    for (const el of Array.from(main.querySelectorAll('[aria-label], [title], [alt]'))) verifier(['aria-label', 'title', 'alt'].map((a) => el.getAttribute(a) ?? '').join(' '), 'attribut')
    // Une sortie au moins, des ancres qui nomment leur destination.
    const sorties = Array.from(main.querySelectorAll('a[href^="#/"]')).filter((a) => !a.closest('.fil-ariane'))
    expect(sorties.length).toBeGreaterThan(3)
    for (const a of sorties) expect(a.textContent ?? '').not.toMatch(/^\s*(ici|cliquez ici|lien|en savoir plus)\s*$/i)
    expect(main.querySelectorAll('a[href=""], a:not([href])')).toHaveLength(0)
  })

  it('règles et limites : textes du pipeline rendus lisibles, sans chemin de fichier, champ technique ni sigle seul', async () => {
    expect(lisible('Un programme appartient à un seul ministère (jeu des ETPT de la LFI 2023) ; lus dans site/data/effectifs sans nouveau calcul.')).toBe(
      'Un programme appartient à un seul ministère (jeu des emplois votés (ETPT) de la loi de finances initiale pour 2023) ; lus dans les données « effectifs » du site sans nouveau calcul.',
    )
    expect(lisible('relèvent des plafonds des opérateurs (site/data/operateurs), pas des programmes')).toBe('relèvent des plafonds des opérateurs, pas des programmes')
    expect(lisible('Millésimes différents selon la mesure (voir `millesime`) : contour.')).toBe('Millésimes différents selon la mesure : contour.')
    await ecran(CHEMIN)
    const regles = main.querySelector('details.carte')!
    expect(norm(regles.querySelector('summary')?.textContent)).toBe('Règles de lecture et limites des données')
    const lignes = Array.from(regles.querySelectorAll('li')).map((li) => li.textContent ?? '')
    expect(lignes.length).toBeGreaterThan(5)
    for (const l of lignes) {
      expect(l).not.toMatch(/site\/data|`/)
      expect(l).not.toMatch(/\bLFI\b/)
    }
  })

  it('données absentes : page « en cours d’intégration » propre, sans erreur', async () => {
    const { rendre } = await import('../src/ecrans/fonction_publique')
    viderCache()
    const vrai = globalThis.fetch
    globalThis.fetch = (async (u: string) => (String(u).includes('fonction_publique/') ? new Response('', { status: 404 }) : vrai(u))) as typeof fetch
    try {
      const z = document.createElement('div')
      await rendre(z, new URLSearchParams())
      expect(z.querySelector('h1')?.textContent).toBe('La fonction publique')
      expect(z.textContent).toContain('Données en cours d’intégration')
    } finally {
      globalThis.fetch = vrai
      viderCache()
    }
  })

  it('toutes les lectures de données sont relatives au site', () => {
    expect(requetes.some((u) => u === 'data/fonction_publique/index.json')).toBe(true)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })
})

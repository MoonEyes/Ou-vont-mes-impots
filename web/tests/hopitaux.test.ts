// @vitest-environment happy-dom
// Page « Hôpitaux et établissements de santé » (/explorer/hopitaux) sur des extraits réels de site/data :
// fixtures de l'axe dans tests/fixtures/data/sante_etablissements/, compléments d'autres axes (aide sociale des
// départements, programme 379, FIR des Pays de la Loire) dans tests/fixtures/hopitaux/, servis par ce test seulement.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { viderCache } from '../src/donnees'
import { picto } from '../src/composants/pictos'
import { CONTACT } from '../src/composants/signaler'
import { attendreQue, monterPage, requetes } from './aide-dom'

const RACINE = process.cwd()
const PRIVEES = join(RACINE, 'tests', 'fixtures', 'hopitaux')
const fixture = (chemin: string) => JSON.parse(readFileSync(join(RACINE, 'tests', 'fixtures', chemin), 'utf8'))

let main: HTMLElement
let base: typeof fetch
let refus: RegExp | null = null
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = (el: Element = main) => el.textContent?.replace(/\s+/g, ' ') ?? ''
const choisir = (sel: string, valeur: string) => {
  const s = main.querySelector<HTMLSelectElement | HTMLInputElement>(sel)!
  s.value = valeur
  s.dispatchEvent(new Event('input', { bubbles: true }))
}
const ouvrir = (d: HTMLDetailsElement) => {
  d.open = true
  d.dispatchEvent(new Event('toggle'))
  return d
}

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
  base = globalThis.fetch
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    if (refus?.test(u)) {
      requetes.push(u)
      return new Response('introuvable', { status: 404 })
    }
    const f = join(PRIVEES, u.split('?')[0])
    if (!/^[a-z]+:/i.test(u) && !u.startsWith('//') && !u.includes('..') && existsSync(f)) {
      requetes.push(u)
      return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    return base(url)
  })
})

// Lexique neutre partagé (docs/lexique_neutre.json), même lecture que tests/ecrans.test.ts.
const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; niche_definie: string; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function verifierLexique(t: string, ou: string) {
  let x = t.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
  expect(x.replace(new RegExp(LEXIQUE.niche_definie, 'giu'), ' '), `${ou} : « niche » sans définition`).not.toMatch(borne('niches?'))
}

describe('page hôpitaux', () => {
  it('route : sous Explorer, famille, picto et voisins existants, titre et description aux bonnes longueurs', () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/hopitaux')!
    expect(r).toBeTruthy()
    expect(r.parent).toBe('/explorer')
    expect(r.famille).toBe('secu')
    expect(picto(r.picto ?? '')).not.toBe('')
    for (const v of r.voisins ?? []) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    expect(r.description.length).toBeGreaterThanOrEqual(70)
    expect(r.description.length).toBeLessThanOrEqual(200)
    expect(`${r.titrePage} · Où vont mes impôts`.length).toBeLessThanOrEqual(100)
    verifierLexique(`${r.titre} ${r.titrePage} ${r.description} ${r.resume}`, 'route')
  })

  it('financeurs : montants lus dans les données, chacun avec année, source et statut, jamais additionnés', async () => {
    await ecran('#/explorer/hopitaux')
    const t = texte()
    expect(main.querySelector('h1')?.textContent).toContain('Les hôpitaux et établissements de santé')
    expect(Array.from(main.querySelectorAll('.fil-ariane a')).map((a) => a.textContent)).toEqual(['Accueil', 'Explorer', 'Hôpitaux'])
    // Phrase d'introduction : ce que la page montre et ce qu'elle ne montre pas.
    expect(t).toContain('cette page montre qui leur verse de l’argent public')
    expect(t).toContain('Elle ne montre pas ce que reçoit chaque établissement depuis 2016')
    // Chiffre clé : un seul surligneur, dans un bloc data-cle avec « sur 100 € », lu dans l'arbre Sécurité sociale.
    const secu = fixture('data/secu/arbre/racine.json')
    const maladie = secu.enfants.find((x: { id: string }) => x.id === 'robss').enfants.find((x: { id: string }) => x.id === 'robss/maladie')
    const etab = maladie.enfants.find((x: { id: string }) => x.id === 'robss/maladie/ondam_etablissements')
    const nf = (x: number, d: number) => new Intl.NumberFormat('fr-FR', { minimumFractionDigits: d, maximumFractionDigits: d }).format(x).replace(/\s/g, ' ')
    const surlignes = main.querySelectorAll('.surligne')
    expect(surlignes).toHaveLength(1)
    expect(surlignes[0].textContent?.replace(/\s/g, ' ')).toBe(`${nf(etab.md, 1)} Md€`)
    const cle = surlignes[0].closest('[data-cle]')!
    expect(texte(cle)).toContain(`${nf((etab.md / maladie.md) * 100, 1)} € sur 100 €`)
    expect(texte(cle)).toContain('dépensés en 2024')
    expect(cle.querySelector('.source a')?.getAttribute('href')).toMatch(/^https:\/\//)
    // Assurance maladie et branche autonomie : un renvoi vers le nœud de la page Sécurité sociale, sans arbre dupliqué.
    expect(main.querySelector('a[href="#/explorer/secu?m=organismes2024&id=robss%2Fmaladie%2Fondam_etablissements"]')?.textContent).toBe('Établissements de santé (hôpitaux, cliniques)')
    expect(main.querySelector('a[href="#/explorer/secu?m=organismes2024&id=robss%2Fautonomie%2Fondam_pa"]')).not.toBeNull()
    expect(main.querySelector('.sankey, .billet-tableau')).toBeNull()
    for (const titre of ['Assurance maladie', 'Branche autonomie de la Sécurité sociale', 'Budget de l’État', 'Départements', 'Résidents des EHPAD'])
      expect(Array.from(main.querySelectorAll('.grille-2 h3')).map((x) => x.textContent)).toContain(titre)
    expect(t).toContain('ils ne s’additionnent pas')
    // État : la ligne « Ségur investissement » du programme 379, reversée à la Sécurité sociale.
    const p379 = JSON.parse(readFileSync(join(PRIVEES, 'data/arbre/Solidarite-travail-et-sante_Sant-_379.json'), 'utf8'))
    const segur = p379.enfants.find((x: { id: string }) => x.id.endsWith('/379-02'))
    expect(t).toContain(`Ségur investissement (plan de relance) ${nf(segur.md, 2)} Md€`)
    expect(t).toContain('il ne s’ajoute pas aux dépenses de l’assurance maladie')
    expect(main.querySelector('a[href^="#/explorer/etat/detail?id="]')?.textContent).toBe('le détail de la mission Santé du budget de l’État')
    // Départements : totaux estimés de la DREES, statut « approché ».
    const terr = JSON.parse(readFileSync(join(PRIVEES, 'data/territoires/index.json'), 'utf8'))
    const apa = terr.totaux.aide_sociale_drees.france['apa_etablissement.brute']
    expect(t).toContain(`APA en établissement ${nf(apa['2024'] / 1e9, 1)} Md€ 2024, dépense brute`)
    const carteDep = main.querySelector('#fin-departements')!.closest('section')!
    expect(texte(carteDep)).toContain('total estimé par la DREES')
    expect(carteDep.querySelectorAll('.motif-approche').length).toBe(3)
    expect(carteDep.querySelector('a[href="#/explorer/secu?id=robss%2Fautonomie%2Ftransferts"]')).not.toBeNull()
    // Résidents des EHPAD : prix médians de la dernière année, « pas une dépense publique ».
    const idx = fixture('data/sante_etablissements/index.json')
    const an = Object.keys(idx.totaux.prix_ehpad).sort().pop()!
    expect(t).toContain(`Hébergement en chambre seule ${nf(idx.totaux.prix_ehpad[an][1], 2)} € par jour`)
    expect(t).toContain('pas une dépense publique')
    // Chaque montant porte un statut écrit (motif et mot), et la légende des motifs est là.
    expect(t).toContain('Comment lire les motifs')
    for (const s of ['tracé', 'approché', 'non publié']) expect(Array.from(main.querySelectorAll('.badge')).some((b) => b.textContent?.toLowerCase() === s), s).toBe(true)
  })

  it('comptes agrégés : chiffres de l’ATIH, billet des charges, séries, regroupements qui conservent les totaux', async () => {
    await ecran('#/explorer/hopitaux')
    const f = fixture('data/sante_etablissements/finances_agregees.json')
    const t24 = f.totaux.par_annee['2024']
    const nf1 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
    expect(texte()).toContain(`${nf1.format(t24.produits_eur / 1e9).replace(/\s/g, ' ')} Md€ de produits en 2024, pour ${t24.etablissements} établissements`)
    expect(texte()).toContain('Leur différence n’est donc pas un résultat')
    const billet = main.querySelector('.billet .billet-large')!
    expect(billet.getAttribute('aria-label')).toContain('Sur 100 € de charges du compte principal')
    const parts = Array.from(billet.querySelectorAll('[role="img"]')).map((g) => g.getAttribute('aria-label'))
    expect(parts[0]).toBe(`Personnel : ${nf1.format((t24.charges_personnel_eur / t24.charges_eur) * 100)} € sur 100 €`)
    // Série 2020-2024 : une colonne par année.
    const serie = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent === 'Comptes des hôpitaux publics et privés à but non lucratif, en euros')!
    expect(Array.from(serie.querySelectorAll('thead th')).map((x) => x.textContent)).toEqual(['Grandeur', '2020', '2021', '2022', '2023', '2024'])
    // Regroupements : la somme des groupes redonne le total publié de l'année (aucun montant perdu ni ajouté).
    const { tableComptes } = await import('../src/ecrans/hopitaux')
    for (const cle of ['categorie', 'activite_principale', 'secteur'] as const) {
      const z = document.createElement('div')
      z.innerHTML = tableComptes(f, '2023', cle)
      const lignes = Array.from(z.querySelectorAll('tbody tr'))
      expect(lignes.length, cle).toBeGreaterThan(1)
      const etabs = lignes.reduce((s, tr) => s + Number(tr.querySelectorAll('td')[0].textContent!.replace(/\D/g, '')), 0)
      expect(etabs, cle).toBe(f.totaux.par_annee['2023'].etablissements)
    }
    // Bascule « Par activité » et choix de l'année : le tableau se redessine.
    main.querySelector<HTMLButtonElement>('[data-groupe="activite_principale"]')!.click()
    expect(main.querySelector('#hop-groupes caption')?.textContent).toContain('Comptes 2024 par activité principale')
    expect(main.querySelector('[data-groupe="activite_principale"]')?.getAttribute('aria-pressed')).toBe('true')
    expect(texte(main.querySelector('#hop-groupes')!)).toContain('Médecine, chirurgie, obstétrique')
    const annee = main.querySelector<HTMLSelectElement>('#hop-annee')!
    annee.value = '2020'
    annee.dispatchEvent(new Event('change'))
    expect(main.querySelector('#hop-groupes caption')?.textContent).toContain('Comptes 2020 par activité principale')
    // Investissement : absent des comptes repris, dit en toutes lettres, avec ce qui est publié au niveau national.
    const inv = Array.from(main.querySelectorAll('.absent')).find((x) => texte(x).includes('Les dépenses d’investissement des hôpitaux'))!
    expect(inv.querySelector('.motif-nonpub')).not.toBeNull()
    expect(texte(inv)).toContain('Ces deux montants ne s’additionnent pas')
  })

  it('recherche par département : résumé, liste nommée, filtre, fiche (actes, prix, FIR, comptes 2011-2015)', async () => {
    await ecran('#/explorer/hopitaux')
    const d44 = fixture('data/sante_etablissements/departements/44.json')
    choisir('#hop-dep', '44')
    await attendreQue(() => !!main.querySelector('#hop-dep-titre'))
    expect(main.querySelector('#hop-dep-titre')?.textContent).toBe('Loire-Atlantique (44)')
    expect(texte(main.querySelector('#hop-resultats')!)).toContain('1 478 établissements actifs du périmètre')
    const items = () => Array.from(main.querySelectorAll<HTMLDetailsElement>('#hop-resultats details[data-i]'))
    expect(items()).toHaveLength(d44.etablissements.lignes.length)
    expect(main.querySelector('#hop-statut')?.textContent).toContain(`Ordre de la liste : ${d44.etablissements.ordre}`)
    // Filtre EHPAD
    choisir('#hop-type', 'ehpad')
    await attendreQue(() => items().length === d44.etablissements.lignes.filter((l: string[]) => l[6] === '500').length)
    // Nom ou commune, sans accents ni casse
    choisir('#hop-type', '')
    choisir('#hop-q', 'Corolles')
    await attendreQue(() => items().length === 1)
    const fiche = ouvrir(items()[0])
    expect(texte(fiche)).toContain('Gestionnaire : CENTRE HOSPITALIER ERDRE ET LOIRE (numéro SIREN 200073047')
    expect(texte(fiche)).toContain('63,25')
    expect(texte(fiche)).toContain('pas une dépense publique')
    // Hôpital : actes publiés avec la mention exigée par l'ATIH (l'EHPAD du même gestionnaire est écarté par le type)
    choisir('#hop-type', 'hospitalier')
    choisir('#hop-q', 'erdre')
    await attendreQue(() => items().length === 1 && items()[0].querySelector('summary')?.textContent === 'CENTRE HOSPITALIER ERDRE ET LOIRE')
    const ch = ouvrir(items()[0])
    expect(texte(ch)).toContain('17 638')
    expect(texte(ch)).toContain('Source OpenCCAM, 2021, 2022, 2023, 2024, 2025, https://www.scansante.fr/')
    // Site du CHU de Nantes : subventions FIR du gestionnaire et comptes Hospi Diag de l'entité juridique
    choisir('#hop-q', 'smur ancenis')
    await attendreQue(() => items().length === 1)
    const smur = ouvrir(items()[0])
    expect(texte(smur)).toContain('Subventions du fonds d’intervention régional des Pays de la Loire reçues par le gestionnaire en 2025 : 40,7 M€ (71 conventions)')
    smur.querySelector<HTMLButtonElement>('[data-hd]')!.click()
    await attendreQue(() => !!smur.querySelector('.hd-zone table'))
    expect(smur.querySelector('.hd-zone caption')?.textContent).toContain('CENTRE HOSPITALIER REGIONAL UNIVERSITAIRE DE NANTES : comptes publiés')
    expect(texte(smur)).toContain('Comptes de l’entité juridique, tous ses sites compris.')
    expect(Array.from(smur.querySelectorAll('.hd-zone thead th')).map((x) => x.textContent)).toEqual(['Grandeur', '2011', '2012', '2013', '2014', '2015'])
    expect(texte(smur)).toContain('n’est pas publié en données ouvertes')
    // Aucune coordonnée reprise (téléphone, courriel, adresse)
    // (hors adresse de contact du site, dans le bloc « Signaler une erreur »)
    expect(texte().split(CONTACT).join(' ')).not.toMatch(/@|\b0[1-9](?:[ .]?\d{2}){4}\b/)
  })

  it('recherche dans toute la France : comptes Hospi Diag par nom, puis passage au département', async () => {
    await ecran('#/explorer/hopitaux')
    choisir('#hop-q', 'na')
    expect(texte(main.querySelector('#hop-resultats')!)).toContain('écris au moins trois lettres')
    choisir('#hop-q', 'bretèche')
    await attendreQue(() => main.querySelectorAll('#hop-resultats details[data-j]').length === 1)
    expect(main.querySelector('#hop-statut')?.textContent).toContain('Ordre de la liste : nom, alphabétique')
    const d = ouvrir(main.querySelector<HTMLDetailsElement>('#hop-resultats details[data-j]')!)
    expect(d.querySelector('caption')?.textContent).toContain('CLINIQUE BRETECHE VIAUD : comptes publiés, en euros (liasses fiscales)')
    d.querySelector<HTMLButtonElement>('[data-voir]')!.click()
    await attendreQue(() => main.querySelector('#hop-dep-titre')?.textContent === 'Loire-Atlantique (44)')
    expect(main.querySelector<HTMLSelectElement>('#hop-dep')!.value).toBe('44')
    expect(Array.from(main.querySelectorAll('#hop-resultats details[data-i] summary')).map((x) => x.textContent)).toEqual(['CLINIQUE BRETECHE VIAUD'])
    expect(document.activeElement?.id).toBe('hop-dep-titre')
  })

  it('adresse avec département et nom ; valeurs absentes à la source affichées « non publié », jamais 0', async () => {
    await ecran('#/explorer/hopitaux?dep=44&q=roche%20maillard')
    expect(Array.from(main.querySelectorAll('#hop-resultats details[data-i] summary')).map((x) => x.textContent)).toEqual(['EHPAD ROCHE MAILLARD'])
    await ecran('#/explorer/hopitaux?dep=986')
    expect(main.querySelector('#hop-dep-titre')?.textContent).toBe('Wallis-et-Futuna (986)')
    expect(texte(main.querySelector('#hop-resultats')!)).toContain('Actes médicaux publiés en 2025 : non publié')
    const tableau = Array.from(main.querySelectorAll('table')).find((x) => x.caption?.textContent?.startsWith('Établissements par département'))!
    const ligne = Array.from(tableau.querySelectorAll('tbody tr')).find((tr) => tr.querySelector('th')?.textContent === 'Wallis-et-Futuna (986)')!
    expect(Array.from(ligne.querySelectorAll('td')).map((x) => x.textContent)).toContain('non publié')
  })

  it('format du site : aucun style en ligne, aucun tiret long, lexique neutre, titres sans terme évaluatif, sorties nommées', async () => {
    await ecran('#/explorer/hopitaux')
    choisir('#hop-dep', '44')
    await attendreQue(() => !!main.querySelector('#hop-dep-titre'))
    main.querySelectorAll<HTMLDetailsElement>('#hop-resultats details[data-i]').forEach((d) => ouvrir(d))
    const fautifs = Array.from(main.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l') && !el.hasAttribute('data-g') && !el.hasAttribute('data-f'))
    expect(fautifs).toHaveLength(0)
    expect(main.textContent).not.toContain('—')
    verifierLexique(document.body.textContent ?? '', 'page hôpitaux')
    for (const el of Array.from(main.querySelectorAll('[aria-label], [title], [alt]')))
      verifierLexique(['aria-label', 'title', 'alt'].map((a) => el.getAttribute(a) ?? '').join(' '), 'attribut')
    for (const titre of Array.from(main.querySelectorAll('h1, h2, h3'))) expect(titre.textContent ?? '').not.toMatch(/\b(gaspillage|seulement|énorme|opaque|scandale|trop)\b/i)
    // Titres hiérarchisés : aucun saut de niveau.
    const niveaux = Array.from(main.querySelectorAll('h1, h2, h3, h4')).map((x) => Number(x.tagName[1]))
    niveaux.forEach((n, i) => i && expect(n - niveaux[i - 1], `titre ${i}`).toBeLessThanOrEqual(1))
    // Tableaux : légende et en-têtes portant leur portée.
    for (const tab of Array.from(main.querySelectorAll('table'))) {
      expect(tab.querySelector('caption')?.textContent?.trim()).toBeTruthy()
      for (const th of Array.from(tab.querySelectorAll('th'))) expect(['col', 'row']).toContain(th.getAttribute('scope'))
    }
    const sorties = Array.from(main.querySelectorAll('a[href^="#/"]')).filter((a) => !a.closest('.fil-ariane'))
    expect(sorties.length).toBeGreaterThan(3)
    for (const a of sorties) expect(a.textContent ?? '').not.toMatch(/^\s*(ici|cliquez ici|lien|en savoir plus)\s*$/i)
    expect(main.querySelectorAll('a[href=""], a:not([href])')).toHaveLength(0)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })

  it('ce qui n’est pas publié : chaque sujet de limites.json, sans renvoi technique', async () => {
    const lim = fixture('data/sante_etablissements/limites.json')
    const { sansRenvoisTechniques } = await import('../src/ecrans/hopitaux')
    await ecran('#/explorer/hopitaux')
    const section = Array.from(main.querySelectorAll('h2')).find((x) => x.textContent === 'Ce qui n’est pas publié')!
    expect(section).toBeTruthy()
    for (const x of lim.non_ouvert) {
      expect(texte()).toContain(x.sujet)
      const propre = sansRenvoisTechniques(x.ce_qui_existe)
      expect(propre, x.sujet).not.toMatch(/\.json|\.py|\bsecu\/|nœud|colonnes|pipeline\//)
      expect(propre.length, x.sujet).toBeGreaterThan(20)
    }
    expect(sansRenvoisTechniques('le total est dans secu/ (nœud robss/autonomie/ondam_pa).')).toBe('le total est dans les comptes de la Sécurité sociale.')
    expect(sansRenvoisTechniques('jeu non mis à jour (depuis le 18/07/2017), repris dans hospi_diag.json')).toBe('jeu non mis à jour (depuis le 18/07/2017)')
  })

  it('données absentes : page « en cours d’intégration » si l’axe manque, blocs absents signalés si un autre axe manque', async () => {
    viderCache()
    refus = /sante_etablissements\//
    await ecran('#/explorer/hopitaux')
    expect(texte()).toContain('Données en cours d’intégration')
    expect(main.querySelector('.erreur')).toBeNull()
    viderCache()
    refus = /territoires\/|arbre\/Solidarite|subventions\//
    await ecran('#/explorer/hopitaux')
    expect(main.querySelector('.erreur')).toBeNull()
    expect(texte()).toContain('Ligne « Ségur investissement » du budget de l’État : donnée non disponible.')
    expect(texte()).toContain('Dépenses d’aide sociale des départements : donnée non disponible.')
    expect(texte()).not.toContain('Les subventions du fonds d’intervention régional des Pays de la Loire font exception')
    expect(main.querySelectorAll('.surligne')).toHaveLength(1)
    refus = null
    viderCache()
  })
})

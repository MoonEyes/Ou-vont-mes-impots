// @vitest-environment happy-dom
// Glossaire et sigles (le public ne doit jamais buter sur un sigle) :
// 1. src/glossaire.json : chaque entrée est définie, sourcée, neutre, et couvre les sigles demandés ;
// 2. src/composants/sigles.ts : la première occurrence de chaque sigle connu devient un lien vers sa définition,
//    sans toucher aux titres, liens, boutons ni au texte de la page ;
// 3. l'écran /methode/glossaire : ancres par terme, recherche, focus sur le terme demandé ;
// 4. couverture : un sigle en capitales de 3 lettres ou plus affiché dans un écran sans entrée du glossaire fait
//    échouer le test (règles d'exclusion écrites plus bas, au même endroit que le test).
// Inventaire pour la maintenance : OVMI_INVENTAIRE_SIGLES=/tmp/sigles.txt npx vitest run tests/glossaire.test.ts
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { session } from '../src/etat'
import donnees from '../src/glossaire.json'
import { choisir, expliqueDansLeTexte, expliqueSurPlace, indexer, marquer, normaliser, type Glossaire, type TermeGlossaire } from '../src/composants/sigles'
import { attendre, attendreQue, monterPage } from './aide-dom'

const RACINE = process.cwd()
const G = donnees as unknown as Glossaire
const INDEX = indexer(G)
const GRAPHIES = new Set(G.termes.flatMap((t) => (t.sigle ? [t.sigle, ...(t.variantes ?? [])] : [])))
const PAR_ID = new Map(G.termes.map((t) => [t.id, t]))

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

const zone = (html: string) => {
  const z = document.createElement('div')
  z.innerHTML = html
  return z
}

describe('glossaire.json : entrées définies, sourcées et neutres', () => {
  it('identifiants uniques en ancre lisible, sans collision avec la page ni les lettres', () => {
    const ids = G.termes.map((t) => t.id)
    expect(new Set(ids).size).toBe(ids.length)
    const page = new Set([...readFileSync(join(RACINE, 'index.html'), 'utf8').matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]))
    for (const id of ids) {
      expect(id, id).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)*$/)
      expect(page.has(id), `${id} : identifiant déjà pris par la page`).toBe(false)
      expect(id.startsWith('lettre-'), id).toBe(false)
    }
  })

  it('chaque entrée : terme, définition courte, source https ; chaque sigle : sa forme développée ; renvois valides', () => {
    for (const t of G.termes) {
      expect(t.terme.trim(), t.id).toBeTruthy()
      expect(t.definition.length, `${t.id} : définition trop longue pour une définition courte`).toBeLessThanOrEqual(420)
      expect(t.definition, t.id).toMatch(/[.…]$/)
      expect(t.source.nom.trim(), t.id).toBeTruthy()
      expect(t.source.url, t.id).toMatch(/^https:\/\/[a-z0-9.-]+\.[a-z]{2,}\//)
      if (t.sigle) {
        expect(t.forme?.trim(), `${t.id} : forme développée manquante`).toBeTruthy()
        expect(t.terme, t.id).toBe(t.sigle)
      }
      for (const v of t.voir ?? []) expect(PAR_ID.has(v), `${t.id} : renvoi vers « ${v} » inconnu`).toBe(true)
    }
  })

  it('sigles demandés présents (dont ceux qui ont motivé la page : LFI, PLF)', () => {
    const demandes = ['lfi', 'plf', 'plfss', 'lfss', 'plrg', 'mission', 'programme', 'action', 'ae', 'cp', 'csg', 'crds', 'ondam', 'apul', 'apuc', 'odac', 'asso', 'cofog', 'operateur', 'depense-fiscale', 'taxe-affectee', 'dgf', 'dgfip', 'urssaf', 'insee']
    for (const id of demandes) expect(PAR_ID.has(id), id).toBe(true)
  })

  it('sens ambigus et sigles de deux lettres : chaque sens a ses indices (sinon le sigle n’est pas marqué)', () => {
    for (const [graphie, sens] of INDEX.sens) {
      if (sens.length > 1) for (const t of sens) expect(t.indices?.length, `${graphie} (${t.id}) : sens ambigu sans indice`).toBeGreaterThan(0)
      if (graphie.length === 2 && graphie !== 'UE') for (const t of sens) expect(t.indices?.length, `${graphie} : sigle de deux lettres sans indice`).toBeGreaterThan(0)
    }
    // Les indices sont cherchés comme morceaux du texte de la page : assez longs pour ne pas se trouver dans n'importe quel mot.
    for (const t of G.termes) for (const i of t.indices ?? []) expect(i.length, `${t.id} : indice « ${i} » trop court`).toBeGreaterThanOrEqual(4)
  })

  it('« pas des sigles » : mots en capitales, raison donnée, jamais une graphie du glossaire', () => {
    for (const p of G.pas_des_sigles ?? []) {
      expect(p.mot, p.mot).toMatch(/^\p{Lu}{3,}$/u)
      expect(p.raison.trim(), p.mot).toBeTruthy()
      expect(GRAPHIES.has(p.mot), p.mot).toBe(false)
    }
  })

  // Lexique neutre partagé (docs/NEUTRALITE.md, règle 2), appliqué à tout le texte du glossaire.
  const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; niche_definie: string }
  const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
  it('lexique neutre, aucun tiret long, « niche » toujours définie', () => {
    for (const t of G.termes) {
      const texte = [t.terme, t.forme ?? '', t.definition, t.source.nom].join(' ')
      for (const r of LEXIQUE.regles) expect(texte, `${t.id} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
      expect(texte.replace(new RegExp(LEXIQUE.niche_definie, 'giu'), ' '), `${t.id} : « niche » sans définition`).not.toMatch(borne('niches?'))
      expect(texte, t.id).not.toContain('—')
    }
  })
})

describe('marquage des sigles (src/composants/sigles.ts)', () => {
  it('première occurrence seulement, jamais dans un titre ni dans un lien ; texte de la page inchangé', () => {
    const z = zone('<h2>Le PLF</h2><p><a href="#/x">PLF</a> puis le PLF 2026, encore le PLF.</p>')
    const avant = z.textContent
    expect(marquer(z, INDEX)).toBe(1)
    expect(z.textContent).toBe(avant)
    expect(z.querySelector('h2')!.innerHTML).toBe('Le PLF')
    expect(z.querySelector('a[href="#/x"]')!.innerHTML).toBe('PLF')
    const abbr = z.querySelectorAll('abbr[data-sigle]')
    expect(abbr).toHaveLength(1)
    expect(abbr[0].getAttribute('title')).toBe('projet de loi de finances')
    const a = abbr[0].parentElement as HTMLAnchorElement
    expect(a.tagName).toBe('A')
    expect(a.className).toBe('glossaire-sigle')
    expect(a.getAttribute('href')).toBe('#/methode/glossaire?terme=plf')
    // Nom accessible : commence par le texte visible (WCAG 2.5.3), puis la forme développée.
    expect(a.getAttribute('aria-label')).toBe('PLF : projet de loi de finances, définition dans le glossaire')
    expect(a.previousSibling?.textContent).toBe(' puis le ')
    // Atteignable au clavier : un vrai lien, sans tabindex négatif.
    expect(a.hasAttribute('href')).toBe(true)
    expect(a.getAttribute('tabindex')).toBeNull()
    // Une seconde passe ne marque rien de plus.
    expect(marquer(z, INDEX)).toBe(0)
  })

  it('sigle déjà expliqué sur place, collé à un tiret ou à des chiffres, dans une adresse : laissé tel quel', () => {
    // Dans la phrase qui l'explique, le sigle n'est pas marqué ; il l'est à sa première occurrence suivante.
    const z = zone('<p>Dotation globale de fonctionnement (DGF), puis DGF.</p><p>NFP-LFI, PLF2025, ex-TICPE, https://exemple.fr/CSG/x, site/data/ONDAM.json, TVA (taxe sur la valeur ajoutée).</p><p>La DGF est versée chaque année.</p>')
    expect(marquer(z, INDEX)).toBe(1)
    const abbr = z.querySelector('abbr[data-sigle]')!
    expect(abbr.textContent).toBe('DGF')
    expect(abbr.parentElement!.previousSibling?.textContent).toBe('La ')
    expect(expliqueSurPlace('crédits votés (LFI 2025)', 15, 18)).toBe(false)
    expect(expliqueSurPlace('Garantie des salaires (AGS)', 23, 26)).toBe(true)
    // « forme (SIGLE, …) » : expliqué si les initiales correspondent ; « SIGLE - Forme » : expliqué.
    expect(expliqueDansLeTexte('Allocation d’aide au retour à l’emploi (ARE, y compris en formation)', 'ARE')).toBe(true)
    expect(expliqueDansLeTexte('Cotisations (CSG, CRDS)', 'CSG')).toBe(false)
    expect(expliqueDansLeTexte('ADEME - Agence de l’environnement et de la maîtrise de l’énergie (ADEME)', 'ADEME')).toBe(true)
    const op = zone('<p>ADEME - Agence de la transition écologique, puis la DGF et la DGF.</p>')
    expect(marquer(op, INDEX)).toBe(1)
    expect(op.querySelector('abbr')!.textContent).toBe('DGF')
  })

  it('valeur seule dans une cellule (code de nuance, statut) : non marquée ; même sigle dans une phrase : marqué', () => {
    const z = zone('<table><tbody><tr><td>LFI</td><td>budget voté en LFI 2025</td></tr></tbody></table>')
    expect(marquer(z, INDEX)).toBe(1)
    expect(z.querySelector('td')!.innerHTML).toBe('LFI')
    expect(z.querySelectorAll('td')[1].querySelector('abbr')?.textContent).toBe('LFI')
  })

  it('boutons, étiquettes, sommaires, graphiques, éléments masqués, fil d’Ariane, code : jamais marqués', () => {
    const z = zone(
      '<button>CSG</button><label>CSG</label><details><summary>CSG</summary></details><svg><text>CSG</text></svg><span aria-hidden="true">CSG</span><p hidden>CSG</p><p data-sans-sigles>CSG</p><nav class="fil-ariane">CSG</nav><code>CSG</code><select><option>CSG</option></select><p>la CSG</p>',
    )
    expect(marquer(z, INDEX)).toBe(1)
    expect(z.querySelector('abbr')!.parentElement!.parentElement!.textContent).toBe('la CSG')
  })

  it('sens ambigus : choisi d’après les mots de la page, sinon non marqué', () => {
    const sante = zone('<p>Les ARS pilotent la politique de santé en région.</p>')
    marquer(sante, INDEX)
    expect(sante.querySelector('a')?.getAttribute('href')).toBe('#/methode/glossaire?terme=ars-sante')
    const rentree = zone('<p>L’ARS est versée avant la rentrée scolaire.</p>')
    marquer(rentree, INDEX)
    expect(rentree.querySelector('a')?.getAttribute('href')).toBe('#/methode/glossaire?terme=ars-allocation')
    expect(marquer(zone('<p>Les ARS.</p>'), INDEX)).toBe(0)
    // Indices obligatoires : la CFE n’est marquée que si la page parle de cotisation foncière.
    expect(marquer(zone('<p>Contrôles (CFE et CSP) en cours.</p>'), INDEX)).toBe(0)
    const cfe = zone('<p>La cotisation foncière des entreprises est un impôt local ; la CFE est due chaque année.</p>')
    expect(marquer(cfe, INDEX)).toBe(1)
    expect(choisir(INDEX.sens.get('FRR')!, normaliser('Fonds de réserve pour les retraites')).map((t) => t.id)).toEqual(['frr-retraites'])
  })

  it('autres graphies (« INSEE », « Insee ») : un seul marquage par sigle', () => {
    const z = zone('<p>Données INSEE et Insee.</p>')
    expect(marquer(z, INDEX)).toBe(1)
    expect(z.querySelector('abbr')!.getAttribute('data-sigle')).toBe('Insee')
  })

  it('après le rendu d’un écran : sigles marqués dans le contenu, hors titres et liens, liens vers des entrées existantes', async () => {
    await ecran('#/explorer/etat')
    const marques = Array.from(main.querySelectorAll<HTMLAnchorElement>('a.glossaire-sigle'))
    expect(marques.length).toBeGreaterThan(0)
    expect(marques.map((a) => a.textContent)).toContain('PLF')
    for (const a of marques) {
      expect(a.closest('h1, h2, h3, h4, button, .fil-ariane, .voir-aussi'), a.textContent!).toBeNull()
      expect(a.parentElement!.closest('a'), a.textContent!).toBeNull()
      const id = /^#\/methode\/glossaire\?terme=([a-z0-9-]+)$/.exec(a.getAttribute('href') ?? '')?.[1]
      expect(!!id && PAR_ID.has(id), a.getAttribute('href')!).toBe(true)
    }
    const sigles = marques.map((a) => a.querySelector('abbr')!.getAttribute('data-sigle'))
    expect(new Set(sigles).size).toBe(sigles.length)
  })
})

describe('écran /methode/glossaire', () => {
  it('route rattachée à Méthode, carte dans le hub, titre, introduction, une ancre par terme et par lettre', async () => {
    const r = ROUTES.find((x) => x.chemin === '/methode/glossaire')!
    expect(r.parent).toBe('/methode')
    await ecran('#/methode')
    expect(main.querySelector('.cartes a[href="#/methode/glossaire"]')).not.toBeNull()
    await ecran('#/methode/glossaire')
    expect(main.querySelector('h1')?.textContent).toContain('Glossaire : sigles et mots du budget')
    expect(main.textContent).toContain('elle ne donne aucun montant')
    expect(main.querySelectorAll('.glossaire-entree')).toHaveLength(G.termes.length)
    for (const t of G.termes) expect(main.querySelector(`[id="${t.id}"] dfn`)?.textContent, t.id).toBe(t.terme)
    for (const a of Array.from(main.querySelectorAll('.glossaire-lettres a'))) expect(main.querySelector(`[id="${a.getAttribute('href')!.slice(1)}"]`), a.getAttribute('href')!).not.toBeNull()
    // Chaque définition renvoie à sa source ; la page elle-même n’est pas marquée.
    expect(main.querySelectorAll('.glossaire-entree .source a[href^="https://"]')).toHaveLength(G.termes.length)
    expect(main.querySelector('a.glossaire-sigle')).toBeNull()
    expect(main.querySelector('nav.fil-ariane [aria-current=page]')?.getAttribute('href')).toBe('#/methode/glossaire')
  })

  it('?terme=<id> : focus et contour sur l’entrée demandée', async () => {
    await ecran('#/methode/glossaire?terme=lfi')
    await attendreQue(() => document.activeElement?.id === 'lfi', 2000)
    expect(main.querySelector('#lfi')!.classList.contains('glossaire-cible')).toBe(true)
  })

  it('recherche : filtre les entrées, masque les lettres vides, annonce le nombre ; ancre de lettre sans changer d’adresse', async () => {
    await ecran('#/methode/glossaire')
    const champ = main.querySelector<HTMLInputElement>('#glossaire-filtre')!
    champ.value = 'assurance maladie'
    champ.dispatchEvent(new Event('input'))
    const visibles = Array.from(main.querySelectorAll<HTMLElement>('.glossaire-entree')).filter((e) => !e.hidden)
    expect(visibles.map((e) => e.id)).toContain('ondam')
    expect(visibles.length).toBeLessThan(G.termes.length)
    expect(main.querySelector('#glossaire-compte')?.textContent).toBe(`${visibles.length} définition${visibles.length > 1 ? 's' : ''}.`)
    expect(Array.from(main.querySelectorAll<HTMLElement>('.glossaire-section')).some((s) => s.hidden)).toBe(true)
    champ.value = 'zzzz'
    champ.dispatchEvent(new Event('input'))
    expect(main.querySelector<HTMLElement>('#glossaire-aucun')!.hidden).toBe(false)
    champ.value = ''
    champ.dispatchEvent(new Event('input'))
    const hash = location.hash
    const clic = new MouseEvent('click', { bubbles: true, cancelable: true })
    main.querySelector('.glossaire-lettres a[href="#lettre-o"]')!.dispatchEvent(clic)
    expect(clic.defaultPrevented).toBe(true)
    expect(location.hash).toBe(hash)
    expect(document.activeElement?.id).toBe('lettre-o')
  })

  it('ordre alphabétique des entrées affichées (accents ignorés)', async () => {
    const { termesTries } = await import('../src/ecrans/glossaire')
    const cles = termesTries().map((t: TermeGlossaire) => normaliser(t.terme).replace(/[^a-z0-9]+/g, ' ').trim())
    expect(cles).toEqual([...cles].sort((a, b) => a.localeCompare(b, 'fr')))
  })
})

// ---------------------------------------------------------------------------------------------------------------
// Couverture : aucun sigle affiché sans entrée dans le glossaire.
// Un « sigle » est un mot de 3 lettres capitales ou plus, sans chiffre ni lettre collés (\p{Lu}{3,}). N'en sont pas :
//   1. un mot d'une suite de mots en capitales (nom écrit en capitales : « COMMUNE - GRIGNY (RHONE) ») ;
//   2. un chiffre romain (I, V, X) ;
//   3. un morceau d'adresse, de chemin ou de nom de fichier ;
//   4. un mot qui n'apparaît dans les données de test que comme nom propre (clés nom, dénomination, candidat…) ;
//   5. un sigle expliqué sur place : « forme développée (SIGLE) » ou « SIGLE (forme développée) » ;
//   6. un mot listé dans glossaire.json, « pas_des_sigles », avec sa raison.
// Pour corriger un échec : écrire la forme développée dans l'écran (« budget voté (loi de finances initiale) »),
// ou ajouter le sigle à src/glossaire.json avec sa définition et sa source.
// ---------------------------------------------------------------------------------------------------------------
const CAPITALES = /(?<![\p{L}\p{N}_])\p{Lu}{3,}(?![\p{L}\p{N}_])/gu
const SEPARATEURS = /[\s '’.()–-]/u
const ADRESSES = /\S*[/\\]\S*|\bhttps?:\S+|\S+\.(?:md|json|csv|txt|pdf|xlsx?|zip|html?|js|ts)\b/giu

function voisinEnCapitales(texte: string, debut: number, fin: number): boolean {
  let i = debut - 1
  while (i >= 0 && SEPARATEURS.test(texte[i])) i--
  const avant = i < debut - 1 ? /(\p{L}+)$/u.exec(texte.slice(0, i + 1))?.[1] : undefined
  let j = fin
  while (j < texte.length && SEPARATEURS.test(texte[j])) j++
  const apres = j > fin ? /^(\p{L}+)/u.exec(texte.slice(j))?.[1] : undefined
  return [avant, apres].some((v) => !!v && v === v.toUpperCase() && v !== v.toLowerCase())
}

/** Sigles d'un texte affiché, après les exclusions 1, 2, 3, 5 et 6. */
function siglesAffiches(texte: string): string[] {
  const propre = texte.replace(ADRESSES, (m) => ' '.repeat(m.length))
  const exclus = new Set((G.pas_des_sigles ?? []).map((p) => p.mot))
  const out: string[] = []
  for (const m of propre.matchAll(CAPITALES)) {
    const s = m[0]
    const debut = m.index!
    if (/^[IVX]+$/.test(s) || exclus.has(s)) continue
    if (voisinEnCapitales(propre, debut, debut + s.length)) continue
    if (expliqueDansLeTexte(propre, s)) continue
    out.push(s)
  }
  return out
}

// Clés des données dont la valeur est un libellé rédigé (un sigle y doit être expliqué) ; les autres valeurs sont des
// noms (organismes, candidats, titulaires) ou des codes.
const CLE_NOM = /^(nom|noms?_\w+|nom_\w+|denomination|raison_sociale|candidat|beneficiaires?|titulaire|acheteur|auteur|parlementaire|operateurs?|membres?|sigle|id|code|siren|siret|cle)$/
const CLE_LIBELLE = /libell|source|note|method|avertiss|lecture|limit|defin|unite|perim|millesim|titre|descr|statut|categ|type|nature|forme|intitul|dispositif|regle|explic|motif|constat|traitement|publication|variante|periode|champ|producteur|sens|tendance|commentaire|precision|remarque|legende|theme|famille|fonction|secteur|indicateur|texte|usage|raison|objet|trous|contenu/

function nomsPropresDesDonnees(): Set<string> {
  const libelles = new Set<string>()
  const noms = new Set<string>()
  const parcourir = (x: unknown, cle: string) => {
    if (Array.isArray(x)) x.forEach((v) => parcourir(v, cle))
    else if (x && typeof x === 'object') for (const [k, v] of Object.entries(x)) parcourir(v, k)
    else if (typeof x === 'string') for (const m of x.matchAll(CAPITALES)) (!CLE_NOM.test(cle) && CLE_LIBELLE.test(cle) ? libelles : noms).add(m[0])
  }
  const dossier = (d: string) => {
    for (const n of readdirSync(d)) {
      const p = join(d, n)
      if (statSync(p).isDirectory()) dossier(p)
      else if (n.endsWith('.json')) {
        try {
          parcourir(JSON.parse(readFileSync(p, 'utf8')), '')
        } catch {
          // fixture illisible : ignorée ici (les tests de l'écran concerné le signalent)
        }
      }
    }
  }
  dossier(join(RACINE, 'tests', 'fixtures'))
  return new Set([...noms].filter((s) => !libelles.has(s)))
}

function textesAffiches(racine: Element): string[] {
  const out: string[] = []
  const marcher = (n: Node) => {
    if (n.nodeType === 3) out.push(n.nodeValue ?? '')
    else if (n.nodeType === 1) {
      const el = n as Element
      if (['SCRIPT', 'STYLE', 'TEMPLATE'].includes(el.tagName.toUpperCase())) return
      for (const a of ['aria-label', 'title', 'alt', 'placeholder']) {
        const v = el.getAttribute(a)
        if (v) out.push(v)
      }
      n.childNodes.forEach(marcher)
    }
  }
  marcher(racine)
  return out
}

describe('couverture du glossaire', () => {
  it('aucun sigle en capitales (3 lettres ou plus) affiché dans un écran sans entrée dans le glossaire', async () => {
    const noms = nomsPropresDesDonnees()
    const vus = new Map<string, Map<string, string>>()
    const noter = (texte: string, ou: string) => {
      for (const s of siglesAffiches(texte)) {
        if (noms.has(s)) continue
        if (!vus.has(s)) vus.set(s, new Map())
        const i = texte.indexOf(s)
        if (!vus.get(s)!.has(ou)) vus.get(s)!.set(ou, texte.slice(Math.max(0, i - 70), i + s.length + 50).replace(/\s+/g, ' ').trim())
      }
    }
    // Résultat du calcul : un calcul complet, comme le visiteur.
    await ecran('#/calcul')
    ;(main.querySelector('#p1-net') as HTMLInputElement).value = '2100'
    session.resultat = null
    main.querySelector<HTMLFormElement>('#formulaire')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreQue(() => session.resultat !== null, 90000)
    const pages = [
      ...ROUTES.map((r) => '#' + r.chemin),
      '#/calcul/resultat',
      '#/explorer/etat?m=lfi2025',
      '#/explorer/etat?m=nature2025',
      '#/explorer/etat/detail?m=execution2024&id=Education%20et%20recherche%2FEnseignement%20scolaire%2F141',
      '#/explorer/ue?dep=69',
      '#/explorer/recettes?i=D211',
      '#/explorer/operateurs?p=141',
      '#/local/commune?insee=69123',
      '#/local/departement?dep=69',
      '#/beneficiaires?p=141',
      '#/beneficiaires?onglet=marches',
      '#/beneficiaires?onglet=france2030',
      '#/beneficiaires/programme?p=141',
      '#/decisions/realisations?p=141',
      '#/decisions/votes?p=141',
      '#/decisions/controle?dep=69',
      '#/decisions/vie-politique?a=2022',
      '#/decisions/vie-politique?a=2024',
    ]
    for (const f of pages) {
      await ecran(f)
      await attendre(0)
      for (const t of textesAffiches(main)) noter(t, f)
    }
    // Titres, descriptions et résumés des routes : cartes des hubs, onglet du navigateur, résultats de recherche.
    for (const r of ROUTES) for (const t of [r.titre, r.titrePage ?? '', r.description, r.resume ?? '', r.court ?? '']) noter(t, `route ${r.chemin}`)
    if (process.env.OVMI_INVENTAIRE_SIGLES)
      writeFileSync(
        process.env.OVMI_INVENTAIRE_SIGLES,
        [...vus.entries()]
          .sort((a, b) => a[0].localeCompare(b[0]))
          .map(([s, ou]) => `${s}\t${GRAPHIES.has(s) ? 'glossaire' : 'MANQUANT'}\t${[...ou.entries()].map(([k, v]) => `${k} « ${v} »`).join(' | ')}`)
          .join('\n') + '\n',
      )
    const manquants = [...vus.entries()].filter(([s]) => !GRAPHIES.has(s))
    expect(
      manquants.map(([s, ou]) => `${s} : ${[...ou.entries()].slice(0, 2).map(([k, v]) => `${k} « ${v} »`).join(' ; ')}`),
      'Sigles affichés sans entrée dans src/glossaire.json : écrire la forme développée dans l’écran, ou ajouter le sigle au glossaire (forme, définition, source).',
    ).toEqual([])
    // Le test lit vraiment des pages : des sigles connus y sont trouvés.
    for (const s of ['LFI', 'PLF', 'CSG', 'TVA']) expect(vus.has(s), s).toBe(true)
  }, 600000)
})

describe('sigles relevés par l’audit avant lancement (18/11/2026) sur les pages prérendues', () => {
  it('chaque sigle affiché sans définition a maintenant son entrée', () => {
    for (const s of ['APL', 'ALF', 'ALS', 'PAJE', 'DGAFP', 'DARES', 'DEPP', 'SDES', 'SRE', 'CNBF', 'FNAL', 'CEG', 'CNDS', 'CNC', 'DITP', 'CIRAD'])
      expect(GRAPHIES.has(s), s).toBe(true)
  })
})

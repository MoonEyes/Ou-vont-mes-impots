// @vitest-environment happy-dom
// Lot 3 du design (audit du 19/11/2026, problèmes 2, 9, 14) : un écran de synthèse, le reste à la demande, sans perte
// d'information ; un H2 a toujours la même taille ; fil de l'euro à l'échelle 1 au téléphone, avec sa version tableau.
// Les hauteurs réelles (résultat <= 8 écrans, Ma commune <= 6 écrans à 360 px) sont mesurées dans un vrai navigateur
// (compte rendu du lot) : happy-dom ne met rien en page.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { assembler, type TvaConso } from '../src/calcul/hors-bulletin'
import { calculer } from '../src/calcul/moteur'
import type { Profil, ResultatOk } from '../src/calcul/types'
import { filEuro } from '../src/composants/fil-euro'
import { session } from '../src/etat'
import { ouvrirPourImpression, repli } from '../src/util'

const SRC = join(process.cwd(), 'src')
const css = readFileSync(join(SRC, 'styles.css'), 'utf8')
const lire = (p: string) => JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'data', p), 'utf8'))
function fichiers(d: string): string[] {
  return readdirSync(d).flatMap((f) => {
    const p = join(d, f)
    return statSync(p).isDirectory() ? fichiers(p) : /\.ts$/.test(f) ? [p] : []
  })
}
/** Règles de la feuille (sélecteur, corps), médias compris. */
const regles = () => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1].trim(), corps: m[2] }))

describe('un H2 a toujours la même taille', () => {
  it('seule la règle « h2 » fixe la taille d’un H2 (aucune variante par contexte)', () => {
    const fautes = regles()
      .filter((r) => /(^|[\s>+~,(])h2\b/.test(r.sel) && /font-size/.test(r.corps))
      .map((r) => r.sel)
      .filter((sel) => sel !== 'h2')
    expect(fautes).toEqual([])
  })

  it('aucune classe posée sur un H2 dans le code ne change sa taille', () => {
    const classes = new Set<string>()
    for (const f of fichiers(SRC)) for (const m of readFileSync(f, 'utf8').matchAll(/<h2\b[^>]*\bclass="([^"$]+)"/g)) m[1].split(/\s+/).forEach((c) => classes.add(c))
    for (const m of readFileSync(join(process.cwd(), 'index.html'), 'utf8').matchAll(/<h2\b[^>]*\bclass="([^"]+)"/g)) m[1].split(/\s+/).forEach((c) => classes.add(c))
    const fautes = regles()
      .filter((r) => /font-size/.test(r.corps))
      .flatMap((r) => [...classes].filter((c) => new RegExp(`\\.${c}(?![\\w-])`).test(r.sel)).map((c) => `${c} (${r.sel})`))
    expect(fautes).toEqual([])
  })
})

describe('sections repliées', () => {
  it('le titre reste un H2 hors du résumé, le contenu est dans la page, fermé par défaut', () => {
    const d = document.createElement('div')
    d.innerHTML = repli({ id: 'x', titre: 'Par destinataire', resume: 'Les 3 destinataires', contenu: '<p>contenu</p>' })
    const section = d.querySelector('section.repli')!
    expect(section.getAttribute('aria-labelledby')).toBe('x-titre')
    expect(section.querySelector(':scope > h2#x-titre')?.textContent).toBe('Par destinataire')
    expect(section.querySelector('summary h2')).toBeNull()
    const det = section.querySelector<HTMLDetailsElement>('details#x')!
    expect(det.open).toBe(false)
    expect(det.querySelector('summary')?.textContent).toBe('Les 3 destinataires')
    expect(det.textContent).toContain('contenu')
  })

  it('impression : tout s’ouvre le temps d’imprimer, puis reprend son état', () => {
    document.body.innerHTML = '<details id="a"><summary>a</summary>x</details><details id="b" open><summary>b</summary>y</details>'
    ouvrirPourImpression(document)
    dispatchEvent(new Event('beforeprint'))
    expect([...document.querySelectorAll('details')].every((d) => (d as HTMLDetailsElement).open)).toBe(true)
    dispatchEvent(new Event('afterprint'))
    expect((document.querySelector('#a') as HTMLDetailsElement).open).toBe(false)
    expect((document.querySelector('#b') as HTMLDetailsElement).open).toBe(true)
  })
})

describe('fil de l’euro au téléphone (problème 9)', () => {
  const html = filEuro(
    [
      { nom: 'Sur ton salaire', court: 'Salaire', texte: '7 638 €', valeur: 7638, statut: 'trace' },
      { nom: 'Sur tes achats', court: 'Achats', texte: '4 681 à 6 143 €', valeur: 5400, statut: 'approche' },
    ],
    '13 781 €',
    [
      { nom: 'Sécurité sociale', texte: '58 €', valeur: 58, famille: 'secu', pour: ['Retraités'] },
      { nom: 'Non publié', texte: '11 €', valeur: 11, famille: 'nonpub', pour: [] },
    ],
  )
  const d = document.createElement('div')
  d.innerHTML = html
  it('dessin vertical à l’échelle 1 (300 unités pour 300 px utiles à 360 px), aucun texte sous 14 px', () => {
    const svg = d.querySelector('svg.fil-compact')!
    expect(svg.getAttribute('viewBox')).toMatch(/^0 0 300 /)
    const tailles = [...svg.querySelectorAll('text')].map((t) => Number(t.getAttribute('font-size')))
    expect(Math.min(...tailles)).toBeGreaterThanOrEqual(14)
  })
  it('version tableau repliée : chaque source et chaque destinataire, avec « pour qui »', () => {
    const t = d.querySelector('details.fil-tableau')!
    expect(t.querySelector('summary')?.textContent).toBe('Lire le fil de l’euro en tableau')
    const lignes = [...t.querySelectorAll('tbody tr')].map((r) => r.textContent)
    expect(lignes).toHaveLength(4)
    expect(lignes.join(' ')).toContain('Retraités')
    expect(lignes.join(' ')).toContain('Approché')
  })
})

describe('résultat : un écran de synthèse, le reste à la demande', () => {
  it('total, billet, « Où ça va » et fil visibles ; profil, sources, lignes, destinataires, employeur repliés et complets', async () => {
    const tva: TvaConso = lire('prelevements/tva_conso.json')
    const affectation = lire('prelevements/affectation.json')
    const profil: Profil = {
      version_contrat: '1.0',
      annee_revenus: 2025,
      residence: { zone: 'metropole', alsace_moselle: false },
      foyer: { situation: 'celibataire', enfants: [] },
      logement: { statut: 'locataire' },
      personnes: [{ role: 'declarant1', statut_activite: 'salarie_prive', cadre: false, temps_travail: { type: 'temps_plein' }, salaire_net_avant_impot_mensuel: 2100 }],
    }
    const r = calculer(profil, { affectation }) as ResultatOk
    session.profil = profil
    session.resultat = r
    session.complet = assembler(profil, r, { tva, affectation, tfDep: null, ligneCommune: undefined }, { voiture: 'inconnu', fumeur: 'inconnu' })
    const main = document.createElement('main')
    document.body.append(main)
    const { rendre } = await import('../src/ecrans/paie')
    await rendre(main)
    const ouvert = (el: Element | null) => !!el && !el.closest('details:not([open])')
    expect(ouvert(main.querySelector('.grand-chiffre'))).toBe(true)
    expect(ouvert(main.querySelector('.billet'))).toBe(true)
    expect(ouvert(main.querySelector('.parts'))).toBe(true)
    expect(ouvert(main.querySelector('.fil-euro'))).toBe(true)
    // Règle 13 : le badge et la méthode du total restent visibles à côté du chiffre.
    expect(ouvert(main.querySelector('.recap [data-calcule]'))).toBe(true)
    expect(ouvert(main.querySelector('.recap .methode-calcul'))).toBe(true)
    for (const [id, titre] of [
      ['repli-sources', 'D’où ça sort'],
      ['repli-profil', 'Le profil retenu pour ce calcul'],
      ['repli-lignes', 'Ligne par ligne, et qui le reçoit'],
      ['repli-destinataires', 'Par destinataire'],
      ['repli-employeur', 'En plus : ce que paie ton employeur'],
    ]) {
      const d = main.querySelector<HTMLDetailsElement>(`details#${id}`)!
      expect(d, id).not.toBeNull()
      expect(d.open, id).toBe(false)
      expect(d.closest('section')!.querySelector(':scope > h2')?.textContent).toBe(titre)
    }
    // Rien de perdu : chaque prélèvement est dans la page (replié), avec son destinataire.
    const lignes = main.querySelectorAll('#repli-lignes .lignes li')
    expect(lignes.length).toBe(session.complet!.lignes.length)
    expect(main.querySelector('#repli-employeur')!.textContent).toContain('Ces cotisations ne sont pas prélevées sur ton salaire brut')
    // Résumé du replié : il annonce le nombre de lignes.
    expect(main.querySelector('#repli-lignes summary')?.textContent).toContain(`${lignes.length} prélèvements`)
    // Un seul niveau de taille pour les H2 : aucun H2 « petit » (le titre du total est un paragraphe).
    expect(main.querySelector('h2.recap-titre')).toBeNull()
    main.remove()
  }, 60000)
})

describe('chapeaux courts, le reste sous l’action (problème 14)', () => {
  it('qui a voté, organisation, recherche : « Ce que cette page montre et ne montre pas » placé après le formulaire', () => {
    for (const [f, formulaire] of [
      ['qui_a_vote.ts', 'id="qav-form-impot"'],
      ['organisation.ts', 'id="org-form"'],
      ['recherche.ts', 'id="recherche-page"'],
    ]) {
      const t = readFileSync(join(SRC, 'ecrans', f), 'utf8')
      const i = t.indexOf(formulaire)
      const j = t.indexOf('Ce que cette page montre et ne montre pas', i)
      expect(i, f).toBeGreaterThan(0)
      expect(j, f).toBeGreaterThan(i)
      // Aucun avertissement de neutralité placé avant le formulaire de la même page (sauf la fiche d'organisation, sans formulaire).
      if (f !== 'organisation.ts') expect(t.indexOf('Ce que cette page montre et ne montre pas'), f).toBe(j)
    }
  })
})

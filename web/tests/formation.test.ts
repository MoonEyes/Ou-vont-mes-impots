// @vitest-environment happy-dom
// Écran « La formation professionnelle » (site/data/formation/) sur des fixtures extraites des données réelles.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { attendreQue, monterPage } from './aide-dom'

const FIX = join(process.cwd(), 'tests', 'fixtures', 'data')
const lire = (f: string) => JSON.parse(readFileSync(join(FIX, f), 'utf8'))
const idx = lire('formation/index.json')
const usagers = lire('formation/cpf_usagers.json')
const orgs = lire('formation/cpf_organismes.json')
const nf = (x: number) => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(x).replace(/\s+/g, ' ')
const nf1 = (x: number) => new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(x).replace(/\s+/g, ' ')
const nf2 = (x: number) => new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(x).replace(/\s+/g, ' ')

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''
const tableau = (debut: string) => Array.from(main.querySelectorAll('table')).find((t) => (t.caption?.textContent ?? '').startsWith(debut))

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('formation professionnelle', () => {
  it('route sous Explorer, titre, fil d’Ariane et sorties', async () => {
    const r = ROUTES.find((x) => x.chemin === '/explorer/formation-professionnelle')!
    expect(r.parent).toBe('/explorer')
    await ecran('#/explorer/formation-professionnelle')
    expect(main.querySelector('h1')?.textContent?.trim()).toBe('La formation professionnelle')
    expect(main.querySelector('.erreur')).toBeNull()
    expect(main.querySelector('nav[aria-label="Fil d\'Ariane"] [aria-current=page]')?.getAttribute('href')).toBe('#/explorer/formation-professionnelle')
    expect(main.querySelector('a[href="#/explorer/operateurs"]')).not.toBeNull()
    expect(main.querySelector('a[href="#/beneficiaires/programme?p=103"]')).not.toBeNull()
    expect(main.textContent).not.toContain(String.fromCharCode(0x2014))
    // Aucun nom de champ technique ni sigle seul dans le texte affiché.
    expect(texte()).not.toMatch(/«\s?[a-z_]+\s?»/)
    // Un sigle n'apparaît qu'accompagné de son développement « Nom développé (SIGLE) » ; « CPF » n'apparaît jamais.
    expect(texte()).not.toMatch(/\bCPF\b/)
    for (const sigle of ['FIPHFP', 'DGEFP', 'SIRET', 'DARES']) if (new RegExp(`\\b${sigle}\\b`).test(texte())) expect(texte(), sigle).toContain(`(${sigle})`)
    expect(texte()).toContain('Direction de l’animation de la recherche, des études et des statistiques (DARES)')
  })

  it('chiffres clés lus dans les données : compte personnel de formation de la dernière année complète, programme 103', async () => {
    const { anneeReference } = await import('../src/ecrans/formation')
    const ref = anneeReference(idx.cpf.annees)
    expect(ref).toBe('2025')
    await ecran('#/explorer/formation-professionnelle')
    const cles = main.querySelector('.cles')!.textContent!.replace(/\s+/g, ' ')
    expect(cles).toContain(`${nf1(idx.cpf.annees[ref].montant_eur / 1e9)} Md€`)
    expect(cles).toContain(`${nf(idx.cpf.annees[ref].dossiers)} dossiers`)
    const prog = lire(idx.liens.find((l: { vue: string }) => l.vue === 'arbre_etat').fichier)
    const alt = prog.enfants.find((e: { id: string }) => e.id.endsWith('-01'))
    const dem = prog.enfants.find((e: { id: string }) => e.id.endsWith('-02'))
    expect(cles).toContain(`${nf2(alt.md)} Md€`)
    expect(cles).toContain(`${nf2(dem.md)} Md€`)
    expect(cles).toContain('2024')
    // Chaque chiffre clé porte son statut, en mot et en motif.
    expect(main.querySelectorAll('.cles .badge')).toHaveLength(3)
    expect(texte()).toContain('Ces montants ne s’additionnent pas')
  })

  it('qui verse : ressources de France compétences et financeurs du compte, ordre de la source', async () => {
    await ecran('#/explorer/formation-professionnelle')
    const op = idx.liens.find((l: { vue: string }) => l.vue === 'operateurs')
    const t = tableau('Ressources de France compétences')!
    expect(t.querySelectorAll('tbody tr')).toHaveLength(Object.keys(op.annees).length)
    expect(t.textContent!.replace(/\s+/g, ' ')).toContain(`${nf1(op.annees['2024'].taxes_affectees_eur / 1e9)} Md€`)
    expect(t.textContent!.replace(/\s+/g, ' ')).toContain(`${nf1(op.annees['2024'].financement_etat_cp_eur / 1e9)} Md€`)
    const barres = Array.from(main.querySelectorAll('ul.barres li .nom')).map((x) => x.textContent)
    expect(barres.length).toBe(Object.keys(idx.cpf.financeurs).length)
    expect(barres[1]).toBe(idx.cpf.financeurs.titulaire)
    const { REGLE_FINANCEURS } = await import('../src/ecrans/formation')
    expect(Array.from(main.querySelectorAll('[data-regle-ordre]')).map((x) => x.textContent)).toContain(REGLE_FINANCEURS)
    // Aucune barre mise en avant.
    expect(main.querySelector('ul.barres li.actif')).toBeNull()
    expect(main.querySelector('.surligne')).toBeNull()
  })

  it('choix de l’année : financeurs, situations et organismes de l’année demandée ; année en cours signalée', async () => {
    await ecran('#/explorer/formation-professionnelle?a=2022')
    const a = idx.cpf.annees['2022']
    expect(texte()).toContain(`Qui finance les formations du compte personnel de formation en 2022`)
    expect(texte()).toContain(`${nf(a.dossiers)} dossiers`)
    const sit = tableau('Dossiers entrés en formation en 2022')!
    const de = usagers.annees['2022'].situation["Demandeur d'emploi"]
    expect(sit.textContent!.replace(/\s+/g, ' ')).toContain(nf(de[0]))
    main.querySelector<HTMLSelectElement>('#formation-annee-choix')!.value = '2026'
    main.querySelector<HTMLSelectElement>('#formation-annee-choix')!.dispatchEvent(new Event('change'))
    expect(location.hash).toBe('#/explorer/formation-professionnelle?a=2026')
    await ecran(location.hash)
    expect(texte()).toContain('Année en cours')
    // Année inconnue : retour à la dernière année complète.
    await ecran('#/explorer/formation-professionnelle?a=1999')
    expect(texte()).toContain('Qui finance les formations du compte personnel de formation en 2025')
  })

  it('évolution et écarts entre sources : toutes les années, les deux montants côte à côte', async () => {
    await ecran('#/explorer/formation-professionnelle')
    const evo = tableau('Compte personnel de formation par année')!
    expect(evo.querySelectorAll('tbody tr')).toHaveLength(Object.keys(idx.cpf.annees).length)
    expect(evo.querySelectorAll('th[scope=col]').length).toBeGreaterThan(0)
    const ec = tableau('Compte personnel de formation : montant engagé selon deux sources')!
    expect(ec.querySelectorAll('tbody tr')).toHaveLength(idx.ecarts.length)
    for (const e of idx.ecarts) expect(ec.textContent).toContain(e.autre_publie)
    expect(texte()).toContain('aucun n’est retenu contre l’autre')
  })

  it('organismes : personnes morales seulement, montant approché signalé, entrepreneurs individuels additionnés', async () => {
    const { nommables, personneMorale } = await import('../src/ecrans/formation')
    expect(personneMorale('5710')).toBe(true)
    expect(personneMorale('9220')).toBe(true)
    expect(personneMorale('1000')).toBe(false)
    expect(personneMorale('2110')).toBe(false)
    expect(personneMorale('')).toBe(false)
    expect(personneMorale(null)).toBe(false)
    expect(nommables([{ siren: '1', nom: 'A', categorie_juridique: '1000', entrees_cumulees: 9, annees: {} }])).toHaveLength(0)
    await ecran('#/explorer/formation-professionnelle')
    const t = tableau('Dix organismes')!
    const lignes = Array.from(t.querySelectorAll('tbody tr'))
    expect(lignes).toHaveLength(10)
    expect(lignes[0].textContent).toContain(orgs.organismes[0].nom)
    expect(texte()).toContain(`${nf(idx.cpf.organismes.agreges.entrepreneurs_individuels_et_groupements_de_personnes)} entrepreneurs individuels`)
    expect(texte()).toContain('Approché')
    expect(texte()).toContain('Méthode de l’estimation')
  })

  it('sans données : état « en cours d’intégration », sans erreur', async () => {
    const { rendre } = await import('../src/ecrans/formation')
    const { viderCache } = await import('../src/donnees')
    viderCache()
    const vrai = globalThis.fetch
    globalThis.fetch = (async (u: string) => (String(u).includes('formation/') ? new Response('', { status: 404 }) : vrai(u))) as typeof fetch
    const z = document.createElement('div')
    await rendre(z, new URLSearchParams())
    expect(z.textContent).toContain('Données en cours d’intégration')
    globalThis.fetch = vrai
    viderCache()
    await attendreQue(() => true)
  })
})

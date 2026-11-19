// @vitest-environment happy-dom
// « Ton billet te suit » (proposition 3 de l'audit design du 19/11) : après un calcul fait pendant la visite, billet
// miniature de 32 px en tête des pages Explorer, part de la famille de la page mise en évidence, phrase accessible,
// badge « calculé par le site » et méthode (règle 13). Mémoire de la page seulement : ni stockage, ni cookie, ni adresse.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { assembler, type TvaConso } from '../src/calcul/hors-bulletin'
import { calculer } from '../src/calcul/moteur'
import type { Profil, ResultatOk } from '../src/calcul/types'
import { billetSuiveur, estPageExplorer, METHODE_PARTS } from '../src/composants/billet-suiveur'
import { resumer } from '../src/composants/resume-calcul'
import { oublier, session } from '../src/etat'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { monterPage } from './aide-dom'

const lire = (p: string) => JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'data', p), 'utf8'))
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
let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment, false)
  return main
}
const ecrit = vi.spyOn(Storage.prototype, 'setItem')
const calculer2100 = () => {
  const r = calculer(profil, { affectation }) as ResultatOk
  session.profil = profil
  session.resultat = r
  session.complet = assembler(profil, r, { tva, affectation, tfDep: null, ligneCommune: undefined }, { voiture: 'inconnu', fumeur: 'inconnu' })
}

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})
afterAll(() => oublier())

describe('ton billet te suit', () => {
  it('sans calcul pendant la visite : rien', async () => {
    oublier()
    expect(billetSuiveur('etat')).toBe('')
    await ecran('#/explorer/etat')
    expect(main.querySelector('.billet-suiveur')).toBeNull()
  })

  it('pages Explorer seulement (hub, pages, Suivre un euro), jamais ailleurs', () => {
    const r = (c: string) => ROUTES.find((x) => x.chemin === c)!
    for (const c of ['/explorer', '/explorer/etat', '/explorer/secu', '/explorer/dette', '/suivre-un-euro']) expect(estPageExplorer(r(c)), c).toBe(true)
    for (const c of ['/', '/calcul', '/calcul/resultat', '/local', '/local/ma-commune', '/beneficiaires', '/methode']) expect(estPageExplorer(r(c)), c).toBe(false)
  })

  it('budget de l’État : billet de 32 px sous le fil d’Ariane, part de l’État mise en évidence, phrase et méthode', async () => {
    calculer2100()
    const s100 = resumer(session.resultat!, session.complet).sur100
    await ecran('#/explorer/etat')
    const b = main.querySelector('.billet-suiveur')!
    expect(b).not.toBeNull()
    expect(b.previousElementSibling?.classList.contains('fil-ariane')).toBe(true)
    const svg = b.querySelector('svg')!
    expect(svg.getAttribute('height')).toBe('32')
    expect(svg.getAttribute('aria-hidden')).toBe('true')
    expect(b.querySelectorAll('.bs-part')).toHaveLength(Object.keys(s100).length)
    expect(b.querySelectorAll('.bs-ici')).toHaveLength(1)
    expect(b.querySelector('.bs-ici')?.classList.contains('fam-etat')).toBe(true)
    expect(b.querySelectorAll('.bs-eteint')).toHaveLength(Object.keys(s100).length - 1)
    expect(b.querySelector('.bs-texte')?.textContent).toContain(`Tu es dans tes ${s100.Etat} € de l’État`)
    expect(b.getAttribute('aria-label')).toBe('Ton billet')
    // Règle 13 : badge et méthode écrite à côté.
    expect(b.querySelector('[data-calcule]')?.nextElementSibling?.textContent).toBe(`Méthode : ${METHODE_PARTS}`)
    // La page a déjà son lien « Revenir à mon résultat » : pas de doublon.
    expect(main.querySelectorAll('a[href="#/calcul/resultat"]').length).toBe(1)
  })

  it('Sécurité sociale et page sans destinataire propre (dette) : bonne part, ou les parts en phrase', async () => {
    const s100 = resumer(session.resultat!, session.complet).sur100
    await ecran('#/explorer/secu')
    expect(main.querySelector('.billet-suiveur .bs-texte')?.textContent).toContain(`Tu es dans tes ${s100['Securite sociale']} € de la Sécurité sociale`)
    expect(main.querySelector('.billet-suiveur .bs-ici')?.classList.contains('fam-secu')).toBe(true)
    await ecran('#/explorer/dette')
    const t = main.querySelector('.billet-suiveur .bs-texte')?.textContent ?? ''
    expect(t).toContain('Ton billet de 100 €')
    expect(main.querySelector('.billet-suiveur .bs-ici')).toBeNull()
    expect(main.querySelector('.billet-suiveur a[href="#/calcul/resultat"]')).not.toBeNull()
  })

  it('hors Explorer : rien (Ma commune, Qui reçoit l’argent)', async () => {
    await ecran('#/local')
    expect(main.querySelector('.billet-suiveur')).toBeNull()
    await ecran('#/beneficiaires')
    expect(main.querySelector('.billet-suiveur')).toBeNull()
  })

  it('mémoire seulement : rien de stocké, rien dans l’adresse ; « oublier » efface le billet', async () => {
    expect(ecrit).not.toHaveBeenCalled()
    expect(localStorage.length + sessionStorage.length).toBe(0)
    expect(document.cookie).toBe('')
    const s100 = resumer(session.resultat!, session.complet).sur100
    await ecran('#/explorer/etat')
    expect(location.href).not.toContain(String(s100.Etat) + '%20')
    expect(location.hash).toBe('#/explorer/etat')
    const code = readFileSync(join(process.cwd(), 'src', 'composants', 'billet-suiveur.ts'), 'utf8')
    expect(code).not.toMatch(/localStorage|sessionStorage|document\.cookie|indexedDB|history\./)
    oublier()
    await ecran('#/explorer/etat')
    expect(main.querySelector('.billet-suiveur')).toBeNull()
  })
})

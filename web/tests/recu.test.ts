// @vitest-environment happy-dom
// « Le reçu de l'année » (proposition 2 de l'audit design du 19/11) : ticket imprimable et partageable, une ligne par
// destinataire, motif du statut en marge, date et millésime en pied ; sans montants par défaut ; rien de stocké.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { assembler, type TvaConso } from '../src/calcul/hors-bulletin'
import { calculer } from '../src/calcul/moteur'
import type { Profil, ResultatOk } from '../src/calcul/types'
import { lignesRecu, lignesTicket, METHODE_RECU, rendre, texteRecu, ticket } from '../src/ecrans/recu'
import { oublier, session } from '../src/etat'
import { ROUTES } from '../src/routes'
import { eur, fourchette } from '../src/util'

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
const r = calculer(profil, { affectation }) as ResultatOk
const c = assembler(profil, r, { tva, affectation, tfDep: null, ligneCommune: undefined }, { voiture: 'inconnu', fumeur: 'inconnu' })
const net = r.entree.personnes.reduce((s, p) => s + p.salaire_net_avant_impot_annuel, 0)
const JOUR = new Date(2026, 10, 19)
/** Même contrôle que tests/calcule.test.ts : chaque badge « calculé » suivi de sa méthode. */
const calculesSansMethode = (racine: ParentNode) =>
  Array.from(racine.querySelectorAll('[data-calcule]')).filter((b) => !b.nextElementSibling?.classList.contains('methode-calcul'))
const n = (x: string | null | undefined) => (x ?? '').replace(/\s+/g, ' ').trim()
const dom = (html: string) => {
  const d = document.createElement('div')
  d.innerHTML = html
  return d
}
afterEach(() => {
  vi.restoreAllMocks()
  oublier()
})

describe('le reçu de l’année', () => {
  it('route sous « Ton salaire », hors index (page personnelle), sans voisins', () => {
    const route = ROUTES.find((x) => x.chemin === '/calcul/recu')!
    expect(route.parent).toBe('/calcul')
    expect(route.sansIndex).toBe(true)
  })

  it('une ligne par destinataire : parts sur 100 € qui font 100, statut tracé, approché ou non publié', () => {
    const l = lignesRecu(r, c)
    expect(l.length).toBeGreaterThan(3)
    expect(l.reduce((s, x) => s + x.sur100, 0)).toBe(100)
    for (const x of l) expect(['trace', 'approche', 'nonpub']).toContain(x.statut)
    expect(new Set(l.map((x) => x.nom)).size).toBe(l.length)
    // Les taxes sur les achats sont des estimations : au moins une ligne approchée.
    expect(l.some((x) => x.statut === 'approche')).toBe(true)
  })

  it('ticket par défaut : aucun montant en euros (ni total, ni salaire), motif en marge, méthode, date et millésime en pied', () => {
    const d = dom(ticket(r, c, false, JOUR))
    const t = n(d.textContent)
    expect(t).not.toContain(n(eur(c.total.central)))
    expect(t).not.toContain(n(eur(net)))
    expect(n(d.querySelector('tfoot')?.textContent)).toContain('100 €')
    const lignes = d.querySelectorAll('tbody > tr')
    const { visibles, groupe } = lignesTicket(lignesRecu(r, c))
    expect(lignes.length).toBe(visibles.length + (groupe ? 1 : 0))
    for (const tr of lignes) {
      expect(tr.querySelector('.recu-marge .motif')).not.toBeNull()
      expect(tr.querySelector('.recu-marge .visuellement-cache')?.textContent).toMatch(/^(Tracé|Approché|Non publié)$/)
    }
    expect(d.querySelectorAll('.recu-legende li')).toHaveLength(3)
    expect(calculesSansMethode(d)).toEqual([])
    expect(n(d.querySelector('.methode-calcul')?.textContent)).toBe(n(`Méthode : ${METHODE_RECU}`))
    const pied = n(d.querySelector('.recu-pied')?.textContent)
    expect(pied).toContain('Édité le 19 novembre 2026')
    expect(pied).toContain(`Barèmes et législation ${r.annee_legislation}`)
    expect(d.querySelector('h2')?.textContent).toBe(`Reçu de l’année ${r.annee_legislation}`)
  })

  it('2 écrans à 360 px : destinataires de moins de 1 € sur 100 regroupés sur une ligne « autres (n destinataires) » dépliable, rien de perdu', () => {
    const toutes = lignesRecu(r, c)
    const { visibles, autres, groupe } = lignesTicket(toutes)
    expect(autres.length).toBeGreaterThanOrEqual(2)
    expect(groupe).not.toBeNull()
    expect(visibles.length + autres.length).toBe(toutes.length)
    for (const l of autres) expect(l.part).toBeLessThan(1)
    for (const l of visibles) expect(l.part).toBeGreaterThanOrEqual(1)
    // Le ticket fait toujours 100, groupe compris ; le groupe porte le statut le moins sûr de ses lignes.
    expect(visibles.reduce((s, l) => s + l.sur100, 0) + groupe!.sur100).toBe(100)
    const rang = { trace: 0, approche: 1, nonpub: 2 }
    expect(rang[groupe!.statut]).toBe(Math.max(...autres.map((l) => rang[l.statut])))
    expect(groupe!.montantEur.central).toBeCloseTo(autres.reduce((s, l) => s + l.montantEur.central, 0), 6)
    for (const montants of [false, true]) {
      const d = dom(ticket(r, c, montants, JOUR))
      const ligne = d.querySelector('tbody > tr.recu-autres')!
      const det = ligne.querySelector('details')!
      expect(det.hasAttribute('open')).toBe(false)
      expect(n(det.querySelector('summary')?.textContent)).toBe(`Autres (${autres.length} destinataires)`)
      const items = det.querySelectorAll('.recu-autres-liste li')
      expect(items).toHaveLength(autres.length)
      for (const [i, li] of [...items].entries()) {
        expect(n(li.textContent)).toContain(autres[i].nom)
        expect(li.querySelector('.motif')).not.toBeNull()
        expect(n(li.querySelector('.nombre')?.textContent)).toBe(montants ? n(autres[i].montant) : 'moins de 1 €')
      }
      expect(n(ligne.querySelector('td.nombre')?.textContent)).toBe(montants ? n(groupe!.montant) : groupe!.sur100 > 0 ? `${groupe!.sur100} €` : 'moins de 1 €')
    }
    // Le texte partagé garde chaque destinataire, groupés de même.
    const texte = texteRecu(r, c, false, JOUR)
    expect(texte).toContain(`Autres (${autres.length} destinataires)`)
    for (const l of autres) expect(texte).toContain(`dont moins de 1 € : ${l.nom}`)
    // Impression : la liste dépliée.
    const css = readFileSync(join(process.cwd(), 'src', 'styles.css'), 'utf8')
    expect(css).toMatch(/@media print \{[^@]*\.recu-autres details::details-content \{\s*content-visibility: visible;/)
  })

  it('montants seulement sur demande : total et fourchette par destinataire', () => {
    const d = dom(ticket(r, c, true, JOUR))
    expect(n(d.querySelector('tfoot')?.textContent)).toContain(n(fourchette(c.total)))
    expect(n(texteRecu(r, c, true, JOUR))).toContain(n(fourchette(c.total)))
    const sans = n(texteRecu(r, c, false, JOUR))
    expect(sans).not.toContain(n(eur(c.total.central)))
    expect(sans).toContain('Sur 100 € que je verse')
    expect(sans).toContain('Édité le 19 novembre 2026')
  })

  it('écran : case décochée par défaut, la case pilote le ticket et le partage ; imprimer ; rien de stocké', async () => {
    const ecrit = vi.spyOn(Storage.prototype, 'setItem')
    session.profil = profil
    session.resultat = r
    session.complet = c
    const main = document.createElement('main')
    document.body.append(main)
    rendre(main)
    const caseMontants = main.querySelector<HTMLInputElement>('#recu-montants')!
    expect(caseMontants.checked).toBe(false)
    expect(caseMontants.getAttribute('role')).toBe('switch')
    expect(caseMontants.closest('label')?.textContent).toContain('Afficher mes montants en euros')
    expect(n(main.querySelector('#recu-zone')?.textContent)).not.toContain(n(eur(c.total.central)))

    const imprimer = vi.fn()
    window.print = imprimer
    main.querySelector<HTMLButtonElement>('#recu-imprimer')!.click()
    expect(imprimer).toHaveBeenCalledTimes(1)

    const partage = vi.fn(async (_d: { text?: string }) => {})
    Object.defineProperty(navigator, 'share', { value: partage, configurable: true })
    main.querySelector<HTMLButtonElement>('#recu-partager')!.click()
    await vi.waitFor(() => expect(partage).toHaveBeenCalledTimes(1))
    expect(n(partage.mock.calls[0][0].text)).not.toContain(n(eur(c.total.central)))
    await vi.waitFor(() => expect(main.querySelector('#recu-info')?.textContent).toBe('Reçu partagé.'))

    caseMontants.checked = true
    caseMontants.dispatchEvent(new Event('change'))
    expect(n(main.querySelector('#recu-zone tfoot')?.textContent)).toContain(n(fourchette(c.total)))
    main.querySelector<HTMLButtonElement>('#recu-partager')!.click()
    await vi.waitFor(() => expect(partage).toHaveBeenCalledTimes(2))
    expect(n(partage.mock.calls[1][0].text)).toContain(n(fourchette(c.total)))

    expect(ecrit).not.toHaveBeenCalled()
    expect(localStorage.length + sessionStorage.length).toBe(0)
    expect(document.cookie).toBe('')
    expect(location.hash).not.toMatch(/\d{3}/)
    Reflect.deleteProperty(navigator, 'share')
    main.remove()
  })

  it('sans calcul pendant la visite : le reçu renvoie vers la saisie, sans chiffre', () => {
    const main = document.createElement('main')
    rendre(main)
    expect(main.querySelector('.recu')).toBeNull()
    expect(main.querySelector('a[href="#/calcul"]')).not.toBeNull()
  })

  it('impression : les options disparaissent, le ticket garde sa largeur de reçu ; le résultat mène au reçu', () => {
    const css = readFileSync(join(process.cwd(), 'src', 'styles.css'), 'utf8')
    expect(css).toMatch(/@media print \{\s*\.recu-options \{\s*display: none !important;/)
    expect(css).toMatch(/\.recu \{[^}]*max-width: 20rem;/)
    expect(readFileSync(join(process.cwd(), 'src', 'ecrans', 'paie.ts'), 'utf8')).toContain('href="#/calcul/recu"')
    expect(readFileSync(join(process.cwd(), 'src', 'ecrans', 'recu.ts'), 'utf8')).not.toMatch(/localStorage|sessionStorage|document\.cookie|indexedDB/)
  })
})

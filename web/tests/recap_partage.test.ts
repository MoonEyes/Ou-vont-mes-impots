// @vitest-environment happy-dom
// Récapitulatif à garder ou partager : image PNG dessinée sur l'appareil (sans montant personnel par défaut),
// case explicite pour ajouter les montants, bouton d'impression et feuille d'impression du résultat et d'Explorer.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { assembler, type TvaConso } from '../src/calcul/hors-bulletin'
import { calculer } from '../src/calcul/moteur'
import type { Profil, ResultatOk } from '../src/calcul/types'
import { ADRESSE_SITE, contenuCarte, dessinerCarte, monterPartage, partagerCarte } from '../src/composants/carte-partage'
import { session } from '../src/etat'
import { eur } from '../src/util'

const lire = (p: string) => JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'data', p), 'utf8'))
const tva: TvaConso = lire('prelevements/tva_conso.json')
const affectation = lire('prelevements/affectation.json')
const tf69 = lire('prelevements/taxe_fonciere/69.json')

const profil: Profil = {
  version_contrat: '1.0',
  annee_revenus: 2025,
  residence: { zone: 'metropole', alsace_moselle: false, commune_insee: '69123' },
  foyer: { situation: 'celibataire', enfants: [] },
  logement: { statut: 'locataire' },
  personnes: [{ role: 'declarant1', statut_activite: 'salarie_prive', cadre: false, temps_travail: { type: 'temps_plein' }, salaire_net_avant_impot_mensuel: 2100 }],
}
const r = calculer(profil, { affectation }) as ResultatOk
const c = assembler(profil, r, { tva, affectation, tfDep: tf69, ligneCommune: tf69.communes['69123'] }, { voiture: 'inconnu', fumeur: 'inconnu' })
const net = r.entree.personnes.reduce((s, p) => s + p.salaire_net_avant_impot_annuel, 0)
const norm = (x: string) => x.replace(/\s+/g, ' ')

// Canvas factice : happy-dom ne dessine pas ; on enregistre chaque texte écrit sur l'image.
let textes: string[] = []
beforeAll(() => {
  const ctx = new Proxy({} as Record<string, unknown>, {
    get: (cible, cle: string) => {
      if (cle === 'fillText') return (t: string) => textes.push(norm(t))
      if (cle === 'createPattern') return () => null
      if (cle in cible) return cible[cle]
      return () => {}
    },
    set: (cible, cle: string, v) => {
      cible[cle] = v
      return true
    },
  })
  HTMLCanvasElement.prototype.getContext = (() => ctx) as never
  HTMLCanvasElement.prototype.toBlob = function (f: BlobCallback) {
    f(new Blob(['png'], { type: 'image/png' }))
  }
})
afterEach(() => {
  textes = []
  vi.restoreAllMocks()
})

describe('récapitulatif à partager', () => {
  it('contenu par défaut : aucun montant personnel, parts sur 100 € qui font 100', () => {
    const k = contenuCarte(r, c)
    expect(k.total).toBeNull()
    expect(k.fourchette).toBeNull()
    expect(k.salaire).toBeNull()
    expect(k.sorties.every((s) => s.montant === null)).toBe(true)
    expect(k.sorties.map((s) => s.nom)).toEqual(['Sur mon salaire', 'Sur mes achats', 'Sur mes ordures'])
    expect(k.sorties.reduce((s, x) => s + x.sur100, 0)).toBe(100)
    expect(k.parts.reduce((s, x) => s + x.v, 0)).toBe(100)
    expect(k.mention).toContain('non officiel')
    expect(k.adresse).toBe(JSON.parse(readFileSync(join(process.cwd(), 'adresse-site.json'), 'utf8')).url.replace(/^https:\/\//, '').replace(/\/$/, ''))
    expect(k.adresse).not.toMatch(/github|mooneyes/i)
  })

  it('image par défaut : ni total, ni salaire, ni montant de sortie ; mention et adresse présentes', async () => {
    const blob = await dessinerCarte(r, c)
    expect(blob.type).toBe('image/png')
    const tout = textes.join(' | ')
    expect(tout).not.toContain(norm(eur(c.total.central)))
    expect(tout).not.toContain(norm(eur(net)))
    expect(tout).not.toContain('par an')
    expect(tout).toContain('Site citoyen non officiel')
    expect(tout).toContain(ADRESSE_SITE)
    expect(tout).toContain('Mon billet de 100 €')
    // Seuls des euros « sur 100 » apparaissent (valeurs ≤ 100).
    for (const m of tout.matchAll(/(\d[\d ]*) €/g)) expect(Number(m[1].replace(/ /g, ''))).toBeLessThanOrEqual(100)
  })

  it('option explicite : total, fourchette et salaire net sur l’image', async () => {
    await dessinerCarte(r, c, { montants: true })
    const tout = textes.join(' | ')
    expect(tout).toContain(norm(eur(Math.round(c.total.central))))
    expect(tout).toContain(norm(`pour ${eur(net)} net avant impôt par an`))
    expect(tout).toContain('Fourchette')
    expect(tout).toContain(ADRESSE_SITE)
  })

  it('résultat : case non cochée par défaut, la case pilote l’image, bouton Imprimer', async () => {
    session.profil = profil
    session.resultat = r
    session.complet = c
    const cible = document.createElement('main')
    document.body.append(cible)
    const { rendre } = await import('../src/ecrans/paie')
    await rendre(cible)
    const caseMontants = cible.querySelector<HTMLInputElement>('#partage-montants')!
    expect(caseMontants).not.toBeNull()
    expect(caseMontants.checked).toBe(false)
    expect(cible.querySelector('label.case')?.textContent).toContain('Ajouter mes montants à l’image')
    // Monter deux fois n'ajoute rien.
    monterPartage(cible)
    expect(cible.querySelectorAll('#partage-montants').length).toBe(1)

    const imprimer = vi.fn()
    window.print = imprimer
    const bouton = cible.querySelector<HTMLButtonElement>('#imprimer-recap')!
    expect(bouton.closest('.actions')?.querySelector('#partager-carte')).not.toBeNull()
    bouton.click()
    expect(imprimer).toHaveBeenCalledTimes(1)

    URL.createObjectURL = (() => 'blob:test') as never
    URL.revokeObjectURL = (() => {}) as never
    expect(await partagerCarte(r, c)).toBe('Image téléchargée sur ton appareil.')
    expect(textes.join(' ')).not.toContain(norm(eur(net)))
    textes = []
    caseMontants.checked = true
    await partagerCarte(r, c)
    expect(textes.join(' ')).toContain(norm(eur(net)))
    cible.remove()
  }, 60000)

  it('feuille d’impression : thème clair, sans navigation ni boutons, adresse et mention en pied', () => {
    const css = readFileSync(join(process.cwd(), 'src', 'styles.css'), 'utf8')
    const bloc = css.slice(css.indexOf('/* recap-partage */'))
    expect(bloc).toContain('@media print')
    for (const sel of ['.navigation', '.fil-ariane', '.pied', '.actions', '.partage-options', 'main button']) expect(bloc).toContain(sel)
    // Adresse reprise de l'attribut data-adresse de <main>, posé depuis web/adresse-site.json (index.html, vite.config.ts).
    expect(bloc).toMatch(/main::after\s*\{\s*content: '[^']*site citoyen non officiel[^']*' attr\(data-adresse\);/)
    expect(bloc).toContain('--fond: #ffffff')
    expect(bloc).not.toContain('—')
  })
})

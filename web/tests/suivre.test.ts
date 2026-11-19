// @vitest-environment happy-dom
// Écran « Suivre un euro » sur des extraits réels de site/data (tests/fixtures/suivre/data).
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { viderCache } from '../src/donnees'
import { montant, propre } from '../src/ecrans/suivre'
import { attendreQue, monterPage } from './aide-dom'

const FIX = join(process.cwd(), 'tests', 'fixtures', 'suivre')
const requetes: string[] = []
let absents: string[] = []
let reduit = false
let main: HTMLElement

const servir = () =>
  vi.stubGlobal('fetch', async (url: string) => {
    const u = String(url)
    requetes.push(u)
    if (/^[a-z]+:/i.test(u) || u.startsWith('//')) throw new Error(`appel externe interdit : ${u}`)
    const f = join(FIX, u.split('?')[0])
    if (absents.some((a) => u.endsWith(a)) || !existsSync(f)) return new Response('introuvable', { status: 404 })
    return new Response(readFileSync(f, 'utf8'), { status: 200, headers: { 'content-type': 'application/json' } })
  })

const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''
const etapes = () => Array.from(main.querySelectorAll('.suivre-etape'))
const cliquer = async (b: Element | null | undefined) => {
  expect(b).toBeTruthy()
  const avant = main.querySelector('#suivre-etapes')!.innerHTML
  ;(b as HTMLElement).click()
  await attendreQue(() => main.querySelector('#suivre-etapes')!.innerHTML !== avant)
}
const choix = (nom: string) => Array.from(main.querySelectorAll<HTMLButtonElement>('.suivre-choix')).find((b) => b.textContent?.includes(nom))
const aff = JSON.parse(readFileSync(join(FIX, 'data', 'prelevements', 'affectation.json'), 'utf8'))

beforeAll(() => {
  monterPage()
  servir()
  window.matchMedia = ((q: string) => ({ matches: reduit && q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} })) as never
  main = document.getElementById('contenu') as HTMLElement
})
beforeEach(() => {
  absents = []
  reduit = false
  viderCache()
})

describe('suivre un euro', () => {
  it('route sous Explorer, une seule ligne, famille et picto existants', () => {
    const r = ROUTES.filter((x) => x.chemin === '/suivre-un-euro')
    expect(r).toHaveLength(1)
    expect(r[0].parent).toBe('/explorer')
  })

  it('par défaut : la CSG, suivie par la plus grande part jusqu’à la fin de la piste', async () => {
    await ecran('#/suivre-un-euro')
    expect(main.querySelector('h1')?.textContent).toContain('Suivre un euro')
    expect(main.querySelector('[data-depart="csg_activite"]')?.getAttribute('aria-pressed')).toBe('true')
    // Étape 1 : la répartition légale, lue dans les données.
    const csg = aff.prelevements.csg_activite.ventilation as { destinataire: string; part: number }[]
    const e1 = etapes()[0]
    expect(e1.querySelectorAll('.suivre-options li')).toHaveLength(csg.length)
    const cnam = csg.find((v) => v.destinataire === 'cnam')!
    expect(e1.textContent).toContain(montant(cnam.part, 1))
    expect(e1.querySelector('[aria-pressed="true"]')?.textContent).toContain('Assurance maladie')
    // Chaque étape porte sa source et son statut en mot.
    for (const e of etapes()) expect(e.querySelector('.source')).not.toBeNull()
    expect(texte()).toMatch(/Tracé/)
    // Fin de piste dite clairement ; années différentes signalées.
    expect(etapes().length).toBeGreaterThanOrEqual(4)
    expect(etapes().at(-1)!.querySelector('.suivre-fin')?.textContent).toContain('La piste s’arrête ici')
    expect(main.querySelector('.avertissement')?.textContent).toContain('pas toutes sur la même année')
    // Dessin décoratif doublé d'un texte.
    expect(main.querySelector('.fil-piste svg')?.getAttribute('aria-hidden')).toBe('true')
    expect(main.querySelector('#suivre-dessin .visuellement-cache')?.textContent).toContain('Ta piste')
    expect(texte()).not.toContain('—')
    expect(requetes.every((u) => !/^[a-z]+:/i.test(u))).toBe(true)
  })

  it('sur 100 € : les montants changent d’échelle', async () => {
    await ecran('#/suivre-un-euro')
    await cliquer(main.querySelector('[data-base="100"]'))
    const cnam = aff.prelevements.csg_activite.ventilation.find((v: { destinataire: string }) => v.destinataire === 'cnam')
    expect(etapes()[0].textContent).toContain(montant(cnam.part, 100))
    expect(main.querySelector('[data-base="100"]')?.getAttribute('aria-pressed')).toBe('true')
  })

  it('choisir une piste : les étapes suivantes sont recalculées, le focus va à la nouvelle étape, mouvement coupé si demandé', async () => {
    reduit = true
    const appels: unknown[] = []
    Element.prototype.scrollIntoView = function (o?: unknown) {
      appels.push(o)
    } as never
    await ecran('#/suivre-un-euro')
    await cliquer(choix('Allocations familiales'))
    expect(etapes()).toHaveLength(2)
    expect(etapes()[1].querySelector('h2')?.textContent).toContain('Famille')
    expect(document.activeElement).toBe(etapes()[1].querySelector('h2'))
    expect(appels.at(-1)).toMatchObject({ behavior: 'auto' })
    // Branche sans détail : fin de piste avec la ligne la plus fine publiée.
    expect(etapes()[1].querySelector('.suivre-fin')?.textContent).toContain('ligne la plus fine publiée')
  })

  it('TVA vers l’Urssaf : la piste s’arrête avec le motif, et propose l’ensemble englobant', async () => {
    await ecran('#/suivre-un-euro?depart=tva&piste=acoss')
    const fin = etapes()[1].querySelector('.suivre-fin')!
    expect(fin.textContent).toContain('Non publié')
    expect(fin.textContent).toMatch(/répartition par branche n.est pas publiée dans les documents réunis par le site/)
    await cliquer(fin.querySelector('.suivre-choix'))
    expect(etapes()).toHaveLength(3)
    expect(etapes()[2].textContent).toContain('Régimes obligatoires de base')
  })

  it('impôt sur le revenu : budget de l’État, programme, puis destinataires connus ou non publiés', async () => {
    await ecran('#/suivre-un-euro?depart=impot_revenu&piste=etat~Education%20et%20recherche~Education%20et%20recherche%2FEnseignement%20scolaire~Education%20et%20recherche%2FEnseignement%20scolaire%2F141')
    expect(etapes()).toHaveLength(5)
    expect(etapes()[1].textContent).toContain('universalité budgétaire')
    expect(etapes()[1].textContent).toContain('Éducation et recherche')
    const dernier = etapes()[4]
    expect(dernier.textContent).toContain('Enseignement scolaire public du second degré')
    expect(dernier.textContent).toContain('Nominatif par choix')
    await cliquer(choix('Destinataire non publié'))
    expect(etapes()[5].querySelector('.suivre-fin')?.textContent).toContain('faute de publication')
    expect(etapes()[5].querySelector('.badge')?.textContent).toContain('Non publié')
  })

  it('taxe foncière vers la commune : ensemble des collectivités, approché et dit comme tel', async () => {
    await ecran('#/suivre-un-euro?depart=taxe_fonciere&piste=commune')
    expect(etapes()[1].textContent).toContain('pas de la seule collectivité')
    expect(etapes()[1].textContent).toContain('Approché')
    expect(texte()).not.toMatch(/n\.c\.a\.|R & D/)
  })

  it('organisme sans données dans le site : la page le dit sans estimer', async () => {
    await ecran('#/suivre-un-euro?depart=fnal')
    expect(etapes()[1].querySelector('.suivre-fin')?.textContent).toContain('ne font pas encore partie des données réunies par le site')
  })

  it('traçabilité absente : la piste s’arrête au programme, sans erreur', async () => {
    absents = ['tracabilite/programme_141.json']
    await ecran('#/suivre-un-euro?depart=impot_revenu')
    expect(etapes().at(-1)!.textContent).toContain('La piste s’arrête ici')
    expect(main.querySelector('.erreur')).toBeNull()
  })

  it('données absentes : page « en cours »', async () => {
    absents = ['prelevements/affectation.json']
    await ecran('#/suivre-un-euro')
    expect(main.querySelector('h1')?.textContent).toContain('Suivre un euro')
    expect(main.querySelector('.suivre-etapes')).toBeNull()
  })

  it('départ : six puces fréquentes et une liste groupée de tous les prélèvements (lot 3, pas de mur de puces)', async () => {
    await ecran('#/suivre-un-euro')
    const puces = [...main.querySelectorAll<HTMLButtonElement>('.suivre-departs [data-depart]')]
    expect(puces.length).toBeLessThanOrEqual(7)
    expect(puces.find((b) => b.dataset.depart === 'csg_activite')?.getAttribute('aria-pressed')).toBe('true')
    const liste = main.querySelector<HTMLSelectElement>('#suivre-tous')!
    expect(main.querySelector('label[for="suivre-tous"]')).not.toBeNull()
    expect(liste.querySelectorAll('optgroup').length).toBeGreaterThan(1)
    const toutes = [...liste.querySelectorAll('option')].map((o) => o.value)
    for (const p of puces) expect(toutes).toContain(p.dataset.depart)
    // Un départ hors des puces, choisi dans la liste : la piste change et le départ rejoint les puces, pressé.
    const autre = toutes.find((k) => !puces.some((p) => p.dataset.depart === k))!
    const avant = main.querySelector('#suivre-etapes')!.innerHTML
    liste.value = autre
    liste.dispatchEvent(new Event('change'))
    await attendreQue(() => main.querySelector('#suivre-etapes')!.innerHTML !== avant)
    expect(main.querySelector(`.suivre-departs [data-depart="${autre}"]`)?.getAttribute('aria-pressed')).toBe('true')
    // Piste : libellés entiers (plus de troncature « … »), montant à droite.
    expect(main.querySelector('.fil-piste')?.textContent).not.toContain('…')
  })

  it('libellés et montants', () => {
    expect(propre('ONDAM : établissements de santé')).toBe('Établissements de santé')
    expect(propre('Santé n.c.a.')).toBe('Santé (non classé ailleurs)')
    expect(montant(0.4619, 1)).toBe('0,46 €')
    expect(montant(0.004, 1)).toBe('0,40 centime')
    expect(montant(0.4619, 100).replace(/\s/g, ' ')).toBe('46,2 €')
  })
})

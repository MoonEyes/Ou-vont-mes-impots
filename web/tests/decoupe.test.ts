// @vitest-environment happy-dom
// « La découpe, une seule fois » (proposition 1 de l'audit design du 19/11) : 900 ms, un seul mouvement non demandé
// sur tout le site, coupé par prefers-reduced-motion (état final immédiat), joué une fois par visite, rien de stocké.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { billet, type Part } from '../src/composants/billet'
import { decouperQuandVisible, DUREE_DECOUPE, jouerDecoupe, oublierDecoupe } from '../src/composants/decoupe'

const SRC = join(process.cwd(), 'src')
const PARTS: Part[] = [
  { nom: 'Sécurité sociale', valeur: 58, texte: '58 €', famille: 'secu' },
  { nom: 'État', valeur: 23, texte: '23 €', famille: 'etat' },
  { nom: 'Collectivités', valeur: 8, texte: '8 €', famille: 'collectivites' },
  { nom: 'Sans destinataire publié', valeur: 11, texte: '11 €', famille: 'nonpub' },
]
type Faux = { cible: Element; images: Keyframe[]; options: KeyframeAnimationOptions; onfinish: (() => void) | null; oncancel: (() => void) | null }
let lancees: Faux[] = []
const reduit = (oui: boolean) => {
  window.matchMedia = ((q: string) => ({ matches: oui && q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} })) as never
}
const zone = () => {
  const d = document.createElement('div')
  d.innerHTML = billet(PARTS, { etiquette: 'Ton billet' })
  document.body.append(d)
  return d
}
const fichiers = (d: string): string[] =>
  readdirSync(d).flatMap((f) => {
    const p = join(d, f)
    return statSync(p).isDirectory() ? fichiers(p) : /\.ts$/.test(f) ? [p] : []
  })

beforeEach(() => {
  oublierDecoupe()
  lancees = []
  document.body.innerHTML = ''
  ;(Element.prototype as unknown as { animate: unknown }).animate = function (this: Element, images: Keyframe[], options: KeyframeAnimationOptions) {
    const a: Faux = { cible: this, images, options, onfinish: null, oncancel: null }
    lancees.push(a)
    return a as unknown as Animation
  }
  reduit(false)
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe('la découpe, une seule fois', () => {
  it('900 ms : parts jointes et alignées au départ, à leur place à la fin ; perforations posées puis retirées', () => {
    const d = zone()
    expect(jouerDecoupe(d)).toBe(true)
    const parts = lancees.filter((a) => a.cible.tagName.toLowerCase() !== 'path')
    // Deux tracés (écran large et téléphone), quatre parts chacun.
    expect(parts).toHaveLength(8)
    for (const a of parts) {
      expect(a.options.duration).toBe(DUREE_DECOUPE)
      expect(DUREE_DECOUPE).toBe(900)
      expect(a.images.at(-1)!.transform).toBe('translate(0px, 0px)')
      expect(a.options.fill).toBe('backwards')
    }
    // La deuxième part et les suivantes partent jointes à la précédente : décalage vers la gauche.
    const dx = parts.slice(1, 4).map((a) => Number(/translate\((-?[\d.]+)px/.exec(String(a.images[0].transform))![1]))
    expect(dx.every((x) => x < 0)).toBe(true)
    const perfos = d.querySelectorAll('.b-perfo')
    expect(perfos).toHaveLength(8)
    for (const a of lancees.filter((x) => x.cible.tagName.toLowerCase() === 'path')) a.onfinish?.()
    expect(d.querySelectorAll('.b-perfo')).toHaveLength(0)
  })

  it('une seule fois par visite : un second affichage du résultat ne rejoue rien', () => {
    expect(jouerDecoupe(zone())).toBe(true)
    const n = lancees.length
    expect(jouerDecoupe(zone())).toBe(false)
    expect(lancees).toHaveLength(n)
  })

  it('prefers-reduced-motion : aucun mouvement, état final immédiat (rien de posé, rien de décalé)', () => {
    reduit(true)
    const d = zone()
    const avant = d.innerHTML
    expect(jouerDecoupe(d)).toBe(false)
    expect(lancees).toHaveLength(0)
    expect(d.innerHTML).toBe(avant)
    // Et pas de rattrapage plus tard dans la visite.
    reduit(false)
    expect(jouerDecoupe(zone())).toBe(false)
  })

  it('au téléphone, attend que le billet soit visible ; sous mouvement réduit, n’observe même pas', () => {
    let rappel: IntersectionObserverCallback = () => {}
    const observe = vi.fn()
    class FauxObservateur {
      constructor(f: IntersectionObserverCallback) {
        rappel = f
      }
      observe = observe
      disconnect() {}
    }
    vi.stubGlobal('IntersectionObserver', FauxObservateur)
    const d = zone()
    decouperQuandVisible(d)
    expect(observe).toHaveBeenCalledTimes(1)
    expect(lancees).toHaveLength(0)
    rappel([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver)
    expect(lancees.length).toBeGreaterThan(0)

    oublierDecoupe()
    lancees = []
    observe.mockClear()
    reduit(true)
    decouperQuandVisible(zone())
    expect(observe).not.toHaveBeenCalled()
    expect(lancees).toHaveLength(0)
    vi.unstubAllGlobals()
  })

  it('rien n’est stocké : ni stockage local, ni stockage de session, ni cookie', () => {
    const ecrit = vi.spyOn(Storage.prototype, 'setItem')
    const cookie = document.cookie
    jouerDecoupe(zone())
    expect(ecrit).not.toHaveBeenCalled()
    expect(localStorage.length + sessionStorage.length).toBe(0)
    expect(document.cookie).toBe(cookie)
    expect(readFileSync(join(SRC, 'composants', 'decoupe.ts'), 'utf8')).not.toMatch(/localStorage|sessionStorage|document\.cookie|indexedDB/)
  })

  it('aucun autre mouvement ajouté au site : decoupe.ts est le seul à animer, pas d’animation CSS', () => {
    const animent = fichiers(SRC).filter((f) => /\.animate\(/.test(readFileSync(f, 'utf8')))
    expect(animent.map((f) => f.replace(SRC, 'src'))).toEqual(['src/composants/decoupe.ts'])
    const css = readFileSync(join(SRC, 'styles.css'), 'utf8')
    expect(css).not.toMatch(/@keyframes/)
    expect([...css.matchAll(/animation:\s*([^;]+);/g)].map((m) => m[1].trim())).toEqual(['none !important'])
  })
})

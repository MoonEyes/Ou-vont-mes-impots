// « La découpe, une seule fois » (audit design du 19/11, proposition 1) : sur le résultat, un unique mouvement de
// 900 ms. Le billet arrive entier (parts jointes et alignées), les perforations pointillées apparaissent, puis les parts
// se séparent et glissent à leur place, décalées comme les rubans du fil de l'euro. C'est le seul mouvement du site
// qui ne répond pas à un geste ; il ne se joue qu'une fois par visite (mémoire de la page, rien n'est stocké) et
// seulement quand le billet devient visible. Sous prefers-reduced-motion, rien ne bouge : l'état final est immédiat.
// Web Animations API (CSSOM) : aucun attribut style écrit, la CSP stricte reste respectée. Le dessin final est celui
// du billet statique : l'animation ne fait que partir d'un autre état, elle ne change aucune proportion.

export const DUREE_DECOUPE = 900
/** Les trois temps, en part de la durée : billet entier, perforations, séparation. */
const ENTIER = 0.25
const PERFORE = 0.5

let jouee = false

/** Pour les tests seulement : rejouable comme au premier affichage. */
export function oublierDecoupe(): void {
  jouee = false
}
export const decoupeJouee = (): boolean => jouee

export function mouvementReduit(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

const nombre = (el: Element | null, a: string) => Number(el?.getAttribute(a) ?? 0)

/** Anime un tracé du billet ; renvoie les animations lancées (vide si rien à animer). */
function animerTrace(svg: SVGSVGElement): Animation[] {
  const talon = svg.querySelector('.b-talon rect')
  const parts = [...svg.querySelectorAll<SVGElement>(':scope > a, :scope > g[role="img"]')]
  if (!talon || !parts.length || typeof (parts[0] as Element & { animate?: unknown }).animate !== 'function') return []
  const y0 = Math.min(...parts.map((p) => nombre(p.querySelector('rect.b-forme'), 'y')))
  let x = nombre(talon, 'x') + nombre(talon, 'width')
  const anims: Animation[] = []
  const ns = 'http://www.w3.org/2000/svg'
  const perfos: SVGPathElement[] = []
  parts.forEach((p) => {
    const r = p.querySelector('rect.b-forme')
    const dx = x - nombre(r, 'x')
    const dy = y0 - nombre(r, 'y')
    const haut = nombre(r, 'height')
    x += nombre(r, 'width')
    const depart = `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px)`
    anims.push(
      p.animate(
        [
          { transform: depart, offset: 0 },
          { transform: depart, offset: PERFORE },
          { transform: 'translate(0px, 0px)', offset: 1 },
        ],
        { duration: DUREE_DECOUPE, easing: 'cubic-bezier(0.2, 0.7, 0.2, 1)', fill: 'backwards' },
      ),
    )
    // Perforation au bord gauche de chaque part, sur le billet encore entier.
    const perfo = document.createElementNS(ns, 'path')
    perfo.setAttribute('class', 'b-perfo')
    perfo.setAttribute('d', `M${(x - nombre(r, 'width')).toFixed(1)} ${y0}V${(y0 + haut).toFixed(1)}`)
    perfo.setAttribute('aria-hidden', 'true')
    svg.append(perfo)
    perfos.push(perfo)
  })
  for (const perfo of perfos) {
    const a = perfo.animate(
      [
        { opacity: 0, offset: 0 },
        { opacity: 0, offset: ENTIER },
        { opacity: 1, offset: PERFORE - 0.05 },
        { opacity: 0, offset: PERFORE + 0.15 },
        { opacity: 0, offset: 1 },
      ],
      { duration: DUREE_DECOUPE, fill: 'both' },
    )
    a.onfinish = () => perfo.remove()
    a.oncancel = () => perfo.remove()
    anims.push(a)
  }
  return anims
}

/**
 * Joue la découpe sur les billets de la zone, une seule fois par visite. Renvoie true si le mouvement a été lancé.
 * Mouvement réduit demandé : rien n'est animé, la découpe est tenue pour jouée (le billet est déjà dans son état final).
 */
export function jouerDecoupe(zone: ParentNode): boolean {
  if (jouee) return false
  jouee = true
  if (mouvementReduit()) return false
  const svgs = [...zone.querySelectorAll<SVGSVGElement>('.billet svg')]
  return svgs.map(animerTrace).some((a) => a.length > 0)
}

/** Lance la découpe quand le billet devient visible (au téléphone, il est sous le total), une seule fois. */
export function decouperQuandVisible(zone: HTMLElement): void {
  if (jouee) return
  const billet = zone.querySelector('.billet')
  if (!billet) return
  if (mouvementReduit()) {
    jouee = true
    return
  }
  if (typeof IntersectionObserver !== 'function') {
    jouerDecoupe(zone)
    return
  }
  const obs = new IntersectionObserver(
    (entrees) => {
      if (!entrees.some((e) => e.isIntersecting)) return
      obs.disconnect()
      if (billet.isConnected) jouerDecoupe(zone)
    },
    { threshold: 0.6 },
  )
  obs.observe(billet)
}

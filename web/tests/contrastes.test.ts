// Règle 3 : contraste du texte >= 7:1 et de tout état >= 4,5:1, dans les deux modes (jetons de styles.css).
// Direction « le billet découpé » : les couleurs de famille ne changent pas d'un mode à l'autre et portent
// toujours un texte encre (blanc sur la famille État) ; chaque forme colorée a un contour.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(process.cwd(), 'src', 'styles.css'), 'utf8')
function jetons(bloc: string): Record<string, string> {
  return Object.fromEntries([...bloc.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]]))
}
const clair = jetons(/:root \{([\s\S]*?)\n\}/.exec(css)![1])
const sombre = { ...clair, ...jetons(/@media \(prefers-color-scheme: dark\) \{\s*:root \{([\s\S]*?)\n  \}/.exec(css)![1]) }

function luminance(hex: string) {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4))
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}
export const ratio = (a: string, b: string) => {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

const FAMILLES_ENCRE = ['secu', 'collectivites', 'ue', 'dette', 'niches', 'operateurs', 'prestations']
// Texte : couples réellement utilisés.
const TEXTE: [string, string][] = [
  ['texte', 'fond'],
  ['texte', 'papier'],
  ['secondaire', 'fond'],
  ['secondaire', 'papier'],
  ['sur-bandeau', 'bandeau'],
  ['sur-principal', 'principal'],
  ['sur-principal', 'principal-survol'],
  ['sur-etat', 'etat'],
  ['encre', 'blanc'],
  // Tons d'une famille (billet de l'État, des retraites) : texte encre sur les tons clairs, --sur-etat sur les foncés.
  ['sur-etat', 'etat-3'],
  ['encre', 'etat-2'],
  ['encre', 'etat-4'],
  ['encre', 'secu-2'],
  ['encre', 'secu-3'],
  ['encre', 'secu-4'],
  ['encre', 'collectivites-2'],
  ['encre', 'collectivites-3'],
  ['encre', 'collectivites-4'],
  ...FAMILLES_ENCRE.map((f): [string, string] => ['encre', f]),
]
// États : contours, focus, motifs de traçabilité (tracés avec le jeton de contour), saisie invalide (contour épais).
const ETATS: [string, string][] = [
  ['contour', 'fond'],
  ['contour', 'papier'],
  ['encre', 'secu'],
  ['accent', 'fond'],
  ['accent', 'papier'],
]

for (const [nom, t] of [['clair', clair], ['sombre', sombre]] as const)
  describe(`contrastes, mode ${nom}`, () => {
    for (const [a, b] of TEXTE) it(`texte ${a} sur ${b} >= 7:1`, () => expect(ratio(t[a], t[b])).toBeGreaterThanOrEqual(7))
    for (const [a, b] of ETATS) it(`état ${a} sur ${b} >= 4,5:1`, () => expect(ratio(t[a], t[b])).toBeGreaterThanOrEqual(4.5))
    it('les formes colorées restent visibles : leur contour tranche sur les deux fonds (>= 3:1)', () => {
      expect(ratio(t.contour, t.fond)).toBeGreaterThanOrEqual(3)
      expect(ratio(t.contour, t.papier)).toBeGreaterThanOrEqual(3)
      expect(ratio(t.taupe, t.fond)).toBeGreaterThanOrEqual(1.5)
    })
  })

describe('formes colorées', () => {
  const regle = (sel: string) => new RegExp(`(^|\\n)${sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')} \\{([^}]*)\\}`).exec(css)?.[2] ?? ''
  it('barres, pastilles, motifs, tuiles et segments portent un contour', () => {
    for (const sel of ['.barre', '.pastille', '.motif', '.tuiles a', '.empile', '.jauge', '.cles li', '.ruban li']) expect(regle(sel), sel).toMatch(/border: [^;]*var\(--contour\)/)
    expect(regle('.billet .b-forme')).toContain('stroke: var(--contour)')
  })
  it('les couleurs de famille ne sont pas redéfinies en mode sombre, sauf l’État (audit du 19/11 : 1,9:1 sur le papier sombre)', () => {
    const bloc = /@media \(prefers-color-scheme: dark\) \{\s*:root \{([\s\S]*?)\n  \}/.exec(css)![1]
    for (const f of ['secu', 'collectivites', 'ue', 'dette', 'niches', 'operateurs', 'prestations', 'encre', 'blanc']) expect(bloc, f).not.toMatch(new RegExp(`--${f}:`))
    expect(bloc).toMatch(/--etat: #[0-9a-f]{6}/)
    expect(bloc).toMatch(/--sur-etat: #1e1548/)
  })
  it('remplissage État et barres « par destinataire » : 3:1 au moins sur le papier, dans les deux modes (WCAG 1.4.11)', () => {
    for (const t of [clair, sombre]) {
      expect(ratio(t.etat, t.papier)).toBeGreaterThanOrEqual(3)
      expect(ratio(t.secondaire, t.papier)).toBeGreaterThanOrEqual(3)
    }
    expect(css).toMatch(/#par-destinataire \.barre-remplissage \{\s*background: var\(--secondaire\);/)
  })
  it('aucune famille tournante : un billet d’une seule famille se découpe en tons de cette famille', () => {
    const billet = readFileSync(join(process.cwd(), 'src', 'composants', 'billet.ts'), 'utf8')
    expect(billet).not.toContain('FAMILLES_TOURNANTES')
    for (const f of ['etat', 'secu', 'collectivites']) for (const n of [2, 3, 4]) {
      expect(css, `${f}-${n}`).toContain(`.fam-${f}-${n} { fill: var(--${f}-${n}); }`)
      expect(css, `${f}-${n}`).toContain(`.fond-${f}-${n} { background: var(--${f}-${n}); }`)
    }
  })
})

it('jetons demandés présents', () => {
  expect(clair).toMatchObject({ fond: '#f3f0ff', papier: '#ffffff', texte: '#1e1548', secondaire: '#4b4470', filet: '#dcd6f2', secu: '#ffc93c', etat: '#4f2fcc', collectivites: '#19c3b1', ue: '#7cc4ff', dette: '#ff8fc7', niches: '#ffa552', operateurs: '#b6e36b', prestations: '#c9b8ff' })
  expect(sombre).toMatchObject({ fond: '#15102e', papier: '#241b4f', texte: '#f3f0ff', secondaire: '#c9c2ea', contour: '#f3f0ff' })
})

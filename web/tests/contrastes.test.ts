// Règle 3 : contraste du texte >= 7:1 et de tout état >= 4,5:1, dans les deux modes (jetons de styles.css).
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

// Texte : couples réellement utilisés (le texte secondaire ne se pose que sur --fond).
const TEXTE: [string, string][] = [
  ['texte', 'fond'],
  ['texte', 'surface'],
  ['secondaire', 'fond'],
  ['accent', 'fond'],
  ['accent', 'surface'],
  ['accent-survol', 'fond'],
  ['erreur', 'fond'],
  ['erreur', 'erreur-fond'],
  ['emprunt-texte', 'fond'],
  ['ok', 'fond'],
  ['sur-accent', 'accent'],
  ['sur-accent', 'accent-survol'],
  ['fond', 'texte'],
]
// États : statuts de traçabilité, focus, saisie invalide.
const ETATS: [string, string][] = [
  ['trace', 'fond'],
  ['approche', 'fond'],
  ['nonpub', 'fond'],
  ['trace', 'surface'],
  ['approche', 'surface'],
  ['nonpub', 'surface'],
  ['accent', 'fond'],
  ['erreur', 'fond'],
]

for (const [nom, t] of [['clair', clair], ['sombre', sombre]] as const)
  describe(`contrastes, mode ${nom}`, () => {
    for (const [a, b] of TEXTE) it(`texte ${a} sur ${b} >= 7:1`, () => expect(ratio(t[a], t[b])).toBeGreaterThanOrEqual(7))
    for (const [a, b] of ETATS) it(`état ${a} sur ${b} >= 4,5:1`, () => expect(ratio(t[a], t[b])).toBeGreaterThanOrEqual(4.5))
    it('les barres actives et l’emprunt restent visibles (>= 3:1)', () => {
      expect(ratio(t.accent, t.fond)).toBeGreaterThanOrEqual(3)
      expect(ratio(t.taupe, t.fond)).toBeGreaterThanOrEqual(3)
      expect(ratio(t.emprunt, t.fond)).toBeGreaterThanOrEqual(3)
    })
  })

it('jetons demandés présents', () => {
  expect(clair).toMatchObject({ fond: '#ffffff', surface: '#f4f6f2', texte: '#1d2320', secondaire: '#4f5a54', accent: '#0b5a43', surligneur: '#e6f24a', trace: '#0b5a43', approche: '#7a5c00', nonpub: '#5f6a63' })
  expect(sombre).toMatchObject({ fond: '#121614', surface: '#1b211e', texte: '#eef2ec', secondaire: '#a8b3ac', accent: '#6fd3a8' })
})

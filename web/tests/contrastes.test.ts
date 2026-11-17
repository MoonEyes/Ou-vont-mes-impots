// Contrastes WCAG 2.1 AA des couleurs de la charte (texte >= 4,5:1, éléments graphiques >= 3:1).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(process.cwd(), 'src', 'styles.css'), 'utf8')
const v = (nom: string) => new RegExp(`--${nom}:\\s*(#[0-9a-fA-F]{6})`).exec(css)![1]

function luminance(hex: string) {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4))
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}
export const ratio = (a: string, b: string) => {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

describe('contrastes', () => {
  const texte: [string, string][] = [
    ['encre', 'fond'],
    ['encre', 'carte'],
    ['bleu', 'fond'],
    ['bleu', 'carte'],
    ['gris', 'fond'],
    ['gris', 'carte'],
    ['orange-texte', 'fond'],
    ['orange-texte', 'orange-clair'],
    ['encre', 'orange-clair'],
    ['erreur', 'fond'],
    ['ok', 'carte'],
  ]
  for (const [a, b] of texte)
    it(`texte ${a} sur ${b} >= 4,5:1`, () => expect(ratio(v(a), v(b))).toBeGreaterThanOrEqual(4.5))
  it('texte blanc sur bleu >= 4,5:1', () => expect(ratio('#ffffff', v('bleu'))).toBeGreaterThanOrEqual(4.5))
  it('barre orange (emprunt) : bordure encre sur fond >= 3:1', () => expect(ratio(v('encre'), v('orange'))).toBeGreaterThanOrEqual(3))
  it('barres bleues sur fond clair >= 3:1', () => expect(ratio(v('bleu'), v('bleu-clair'))).toBeGreaterThanOrEqual(3))
})

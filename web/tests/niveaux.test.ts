// @vitest-environment happy-dom
// Couleurs par niveau de collectivité (audit design du 19/11, problème 13) : une teinte par niveau dans la famille
// « collectivités », 3:1 au moins sur le fond et le papier en clair comme en sombre (WCAG 1.4.11), utilisée partout où
// les niveaux apparaissent, jamais seule (toujours à côté du nom du niveau).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { NIVEAUX, niveauDestinataire, pastilleNiveau } from '../src/composants/niveaux'

const SRC = join(process.cwd(), 'src')
const css = readFileSync(join(SRC, 'styles.css'), 'utf8')
const jetons = (bloc: string) => Object.fromEntries([...bloc.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]]))
const clair = jetons(/:root \{([\s\S]*?)\n\}/.exec(css)![1])
const sombre = { ...clair, ...jetons(/@media \(prefers-color-scheme: dark\) \{\s*:root \{([\s\S]*?)\n  \}/.exec(css)![1]) }
const NOMS = Object.keys(NIVEAUX)
const luminance = (hex: string) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4))
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}
const ratio = (a: string, b: string) => {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p)
  return (x + 0.05) / (y + 0.05)
}

/** Teinte (degrés) d'une couleur. */
const teinte = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const max = Math.max(r, g, b)
  const d = max - Math.min(r, g, b)
  const t = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4
  return (t * 60 + 360) % 360
}

describe('niveaux de collectivité : jetons', () => {
  it('quatre niveaux : commune, intercommunalité, département, région', () => {
    expect(NOMS).toEqual(['commune', 'epci', 'departement', 'region'])
  })
  for (const [mode, t] of [['clair', clair], ['sombre', sombre]] as const)
    it(`mode ${mode} : une teinte distincte par niveau, de la famille des sarcelles, 3:1 au moins sur le fond et le papier`, () => {
      const valeurs = NOMS.map((n) => t[`niveau-${n}`])
      expect(new Set(valeurs).size).toBe(4)
      for (const [i, v] of valeurs.entries()) {
        expect(v, NOMS[i]).toMatch(/^#[0-9a-f]{6}$/)
        expect(ratio(v, t.fond), `${NOMS[i]} sur fond`).toBeGreaterThanOrEqual(3)
        expect(ratio(v, t.papier), `${NOMS[i]} sur papier`).toBeGreaterThanOrEqual(3)
        // Sarcelles : entre le vert et le bleu (famille « collectivités », --collectivites vaut environ 174°).
        expect(teinte(v), NOMS[i]).toBeGreaterThan(150)
        expect(teinte(v), NOMS[i]).toBeLessThan(200)
      }
    })
  it('chaque niveau a sa règle CSS et la pastille un contour', () => {
    for (const n of NOMS) expect(css).toMatch(new RegExp(`\\[data-niveau='${n}'\\] \\{\\s*--niveau: var\\(--niveau-${n}\\);`))
    expect(/\.pastille-niveau \{([^}]*)\}/.exec(css)![1]).toMatch(/border: [^;]*var\(--contour\)/)
  })
})

describe('niveaux de collectivité : partout où ils apparaissent', () => {
  it('pastille décorative, cachée aux lecteurs d’écran ; destinataires du calcul reconnus', () => {
    const d = document.createElement('div')
    d.innerHTML = pastilleNiveau('epci')
    expect(d.firstElementChild?.getAttribute('aria-hidden')).toBe('true')
    expect(d.firstElementChild?.getAttribute('data-niveau')).toBe('epci')
    expect(pastilleNiveau(null)).toBe('')
    expect(['commune', 'epci', 'departement', 'region_idf', 'etat', 'cnam'].map(niveauDestinataire)).toEqual(['commune', 'epci', 'departement', 'region', null, null])
  })
  it('Ma commune : un onglet et un panneau par niveau, chacun dans sa teinte (ajout CSS seulement)', () => {
    const ecran = readFileSync(join(SRC, 'ecrans', 'ma_commune.ts'), 'utf8')
    for (const [id, n] of [['mc-commune', 'commune'], ['mc-epci', 'epci'], ['mc-departement', 'departement'], ['mc-region', 'region']]) {
      expect(ecran).toContain(`'${id}'`)
      expect(css).toMatch(new RegExp(`#${id}-onglet,\\s*#${id}-panneau \\{\\s*--niveau: var\\(--niveau-${n}\\);`))
    }
  })
  it('écrans qui montrent un niveau : pages commune et département, collectivités, résultat, reçu, Suivre un euro', () => {
    for (const f of ['commune.ts', 'departement.ts', 'collectivites.ts', 'paie.ts', 'recu.ts', 'suivre.ts']) {
      const t = readFileSync(join(SRC, 'ecrans', f), 'utf8')
      expect(t, f).toMatch(/pastilleNiveau|'(commune|epci|departement|region)'\)/)
    }
    const commune = readFileSync(join(SRC, 'ecrans', 'commune.ts'), 'utf8')
    for (const n of NOMS) expect(commune).toContain(`'${n}')`)
  })
})

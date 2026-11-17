// Règles de la direction artistique vérifiables hors navigateur (2 et 4), et identité non officielle.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { legendeStatuts, STATUTS, traitStatut } from '../src/util'

const RACINE = process.cwd()
const css = readFileSync(join(RACINE, 'src', 'styles.css'), 'utf8')
const sources = (d: string): string[] =>
  readdirSync(d).flatMap((n) => (statSync(join(d, n)).isDirectory() ? sources(join(d, n)) : /\.(ts|css|html|svg)$/.test(n) ? [join(d, n)] : []))
const tout = [...sources(join(RACINE, 'src')), join(RACINE, 'index.html'), join(RACINE, 'public', 'favicon.svg')].map((f) => [f, readFileSync(f, 'utf8')] as const)

describe('règle 2 : trois statuts distincts sans la couleur', () => {
  it('libellés distincts', () => {
    const l = Object.values(STATUTS).map((s) => s.libelle)
    expect(new Set(l).size).toBe(3)
  })
  it('motifs distincts (plein, tirets, pointillés) dans la légende et les barres', () => {
    expect(legendeStatuts()).toContain('ligne-trace')
    expect(legendeStatuts()).toContain('ligne-approche')
    expect(legendeStatuts()).toContain('ligne-nonpub')
    const dash = (c: string) => new RegExp(`\\.trait-statut \\.ligne-${c} \\{[^}]*\\}`).exec(css)![0]
    expect(dash('trace')).not.toContain('dasharray')
    expect(dash('approche')).toContain('stroke-dasharray: 8 5')
    expect(dash('nonpub')).toContain('stroke-dasharray: 2 4')
    expect(css).toMatch(/\.statut-approche,[\s\S]*?repeating-linear-gradient/)
    expect(css).toMatch(/\.statut-nonpub,[\s\S]*?radial-gradient/)
    expect(traitStatut('approche')).toContain('aria-hidden="true"')
  })
})

describe('règle 4 : valeur finale tout de suite, mouvement court et coupé sur demande', () => {
  it('transitions et animations <= 400 ms', () => {
    for (const m of css.matchAll(/(?:transition|animation)(?:-duration)?:\s*([^;]+);/g)) {
      for (const d of m[1].matchAll(/([\d.]+)(ms|s)\b/g)) {
        const ms = d[2] === 's' ? Number(d[1]) * 1000 : Number(d[1])
        expect(ms, m[0]).toBeLessThanOrEqual(400)
      }
    }
  })
  it('coupées sous prefers-reduced-motion', () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*transition: none !important[\s\S]*animation: none !important/)
  })
  it('aucun compteur défilant ni animation pilotée par script', () => {
    for (const [f, c] of tout) {
      expect(c, f).not.toMatch(/requestAnimationFrame|setInterval\(/)
      expect(c, f).not.toMatch(/@keyframes/)
    }
  })
  it('Sankey sans animation', () => {
    expect(readFileSync(join(RACINE, 'src', 'composants', 'sankey.ts'), 'utf8')).toContain('animation: false')
  })
})

describe('identité', () => {
  it('Sankey : aucune couleur en dur, lue dans les variables CSS', () => {
    const s = readFileSync(join(RACINE, 'src', 'composants', 'sankey.ts'), 'utf8')
    expect(s).not.toMatch(/#[0-9a-fA-F]{3,6}\b/)
    expect(s).toContain('getComputedStyle')
  })
  it('pas un site officiel : ni Marianne, ni DSFR, ni bleu-blanc-rouge', () => {
    for (const [f, c] of tout) {
      expect(c, f).not.toMatch(/marianne|dsfr|#000091|#e1000f|#002395|#ed2939/i)
    }
  })
  it('polices auto-hébergées de la direction hybride, plus d’Inter ni de Space Grotesk', () => {
    expect(css).toContain("font-family: 'Fraunces'")
    expect(css).toContain("'Atkinson Hyperlegible Next'")
    expect(css).toContain("'Recursive Mono'")
    expect(css).not.toMatch(/Inter|Space Grotesk/)
    expect(css).not.toMatch(/box-shadow/)
  })
})

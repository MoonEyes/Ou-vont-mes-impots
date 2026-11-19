// @vitest-environment happy-dom
// Système visuel (audit design du 19/11/2026, lot 2) : 7 crans typographiques, plancher 14 px, aucune taille écrite
// en dur hors jetons (feuille de style, dessins SVG, graphiques) ; trois boutons ; un seul composant de statut.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { CRANS_PX, cran } from '../src/typo'
import { badgeCalcule, badgeStatut } from '../src/util'

const SRC = join(process.cwd(), 'src')
const css = readFileSync(join(SRC, 'styles.css'), 'utf8')
const JETONS = ['--t-1', '--t0', '--t1', '--t2', '--t3', '--t4', '--t5']

function fichiers(d: string): string[] {
  return readdirSync(d).flatMap((f) => {
    const p = join(d, f)
    return statSync(p).isDirectory() ? fichiers(p) : /\.ts$/.test(f) ? [p] : []
  })
}

describe('échelle typographique', () => {
  it('7 jetons --t-1 à --t5, plancher 14 px (0,875rem)', () => {
    const racine = /:root \{([\s\S]*?)\n\}/.exec(css)![1]
    const def = Object.fromEntries([...racine.matchAll(/(--t-?\d): ([^;]+);/g)].map((m) => [m[1], m[2]]))
    expect(Object.keys(def)).toEqual(JETONS)
    expect(def).toEqual({ '--t-1': '0.875rem', '--t0': '1rem', '--t1': '1.125rem', '--t2': '1.375rem', '--t3': '1.75rem', '--t4': '2.5rem', '--t5': 'clamp(2.25rem, 6vw, 4.75rem)' })
  })

  it('feuille de style : chaque font-size est un jeton (aucune taille en dur, même en impression)', () => {
    const tailles = [...css.matchAll(/font-size:\s*([^;]+);/g)].map((m) => m[1].trim())
    expect(tailles.length).toBeGreaterThan(50)
    const horsJetons = tailles.filter((v) => v !== 'inherit' && !JETONS.some((j) => v === `var(${j})`))
    expect(horsJetons).toEqual([])
    // Raccourci « font: » avec une taille : interdit aussi (seul « font: inherit » est permis).
    expect([...css.matchAll(/\bfont:\s*([^;]+);/g)].map((m) => m[1].trim()).filter((v) => v !== 'inherit')).toEqual([])
  })

  it('dessins SVG et graphiques : tailles prises dans les crans (cran()), plancher 14 px', () => {
    expect([...CRANS_PX]).toEqual([14, 16, 18, 22, 28, 36, 40, 76])
    expect([cran(9), cran(14), cran(15.9), cran(21), cran(100)]).toEqual([14, 14, 14, 18, 76])
    const fautes: string[] = []
    for (const f of fichiers(SRC)) {
      if (f.endsWith('carte-partage.ts')) continue // image PNG dessinée sur un canevas, hors page
      const t = readFileSync(f, 'utf8')
      for (const m of t.matchAll(/font-size="([^"]+)"/g)) {
        const v = m[1]
        const nombres = [...v.matchAll(/\d+(?:\.\d+)?/g)].map((x) => Number(x[0]))
        const dynamique = v.startsWith('${')
        const ok = dynamique ? /^\$\{(c|grand|large \? \d+ : \d+)\}$/.test(v) && nombres.every((n) => (CRANS_PX as readonly number[]).includes(n)) : (CRANS_PX as readonly number[]).includes(Number(v))
        if (!ok) fautes.push(`${f.replace(SRC, 'src')} : font-size="${v}"`)
      }
      for (const m of t.matchAll(/fontSize:\s*(\d+(?:\.\d+)?)/g)) if (!(CRANS_PX as readonly number[]).includes(Number(m[1]))) fautes.push(`${f.replace(SRC, 'src')} : fontSize ${m[1]}`)
      if (/font-size:\s*\d/.test(t)) fautes.push(`${f.replace(SRC, 'src')} : font-size CSS en dur`)
    }
    expect(fautes).toEqual([])
  })
})

describe('composants', () => {
  it('trois boutons : seules les règles principal, secondaire et lien d’action fixent marges internes et taille', () => {
    const sansCommentaires = css.replace(/\/\*[\s\S]*?\*\//g, '')
    const regles = [...sansCommentaires.matchAll(/(^|\n)([^{}\n][^{}]*)\{([^}]*)\}/g)].map((m) => ({ sel: m[2].trim(), corps: m[3] }))
    const boutons = regles.filter((r) => /(^|[\s,])(button|\.bouton[\w-]*)\b/.test(r.sel) && !/#bouton-/.test(r.sel) && /(^|\n)\s*(padding|font-size)\b/.test(r.corps))
    const sels = boutons.map((r) => r.sel.replace(/\s+/g, ' '))
    expect(sels).toEqual(['button, .bouton, .bouton-secondaire', '.bouton-principal', 'button.bouton-lien, .bouton-lien'])
  })

  it('un seul composant de statut, quatre valeurs', () => {
    const d = document.createElement('div')
    d.innerHTML = (['trace', 'approche', 'nonpub'] as const).map(badgeStatut).join('') + badgeCalcule('somme de deux montants publiés')
    const statuts = [...d.querySelectorAll('.statut')].map((e) => e.getAttribute('data-statut'))
    expect(statuts).toEqual(['trace', 'approche', 'nonpub', 'calcule'])
    for (const e of d.querySelectorAll('.statut')) expect(e.querySelectorAll('.motif')).toHaveLength(1)
    expect(css).toMatch(/\.statut \.motif \{\s*width: 1rem;\s*height: 1rem;/)
  })
})

// @vitest-environment happy-dom
// Règle « chiffre calculé par le site » (docs/NEUTRALITE.md, page Méthode) : un ratio, une différence, une somme, une
// moyenne ou une part calculés par le site ne sont affichés qu'avec le badge distinct « Calculé par le site » et leur
// méthode écrite à côté. Test transversal : le badge refuse une méthode vide, chaque appel des écrans écrit une méthode,
// et aucun écran n'annonce un « calcul du site » sans ce badge.
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { badgeCalcule, LEGENDE_CALCULE, LIBELLE_CALCULE, memeAnnee, STATUTS } from '../src/util'

const SRC = join(process.cwd(), 'src')
const sources = ['ecrans', 'composants'].flatMap((d) =>
  readdirSync(join(SRC, d))
    .filter((f) => f.endsWith('.ts'))
    .map((f) => ({ f: `${d}/${f}`, code: readFileSync(join(SRC, d, f), 'utf8') })),
)
/** Code sans commentaires (ligne et bloc), pour ne contrôler que ce qui peut être affiché. */
const sansCommentaires = (c: string) => c.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/.*$/gm, '$1')

/** Vérifie dans un fragment rendu que chaque badge « calculé » est suivi de sa méthode, non vide. */
export function calculesSansMethode(racine: ParentNode): Element[] {
  return Array.from(racine.querySelectorAll('[data-calcule]')).filter((b) => {
    const m = b.nextElementSibling
    return !m || !m.classList.contains('methode-calcul') || (m.textContent ?? '').replace(/^\s*Méthode\s*:\s*/, '').trim().length < 10
  })
}

describe('chiffre calculé par le site', () => {
  it('badge distinct des statuts tracé, approché et non publié ; méthode obligatoire', () => {
    expect(Object.values(STATUTS).map((s) => s.libelle)).not.toContain(LIBELLE_CALCULE)
    expect(() => badgeCalcule('')).toThrow()
    expect(() => badgeCalcule('   ')).toThrow()
    const d = document.createElement('div')
    d.innerHTML = `<p>Écart ${badgeCalcule('montant A moins montant B, même année et même périmètre')}</p>`
    expect(d.querySelector('[data-calcule]')?.textContent).toBe(LIBELLE_CALCULE)
    expect(d.querySelector('.motif-calcule')).not.toBeNull()
    expect(d.querySelector('.methode-calcul')?.textContent).toBe('Méthode : montant A moins montant B, même année et même périmètre')
    expect(calculesSansMethode(d)).toEqual([])
    d.innerHTML = '<p><span class="badge" data-calcule>Calculé par le site</span></p>'
    expect(calculesSansMethode(d)).toHaveLength(1)
    expect(LEGENDE_CALCULE).toContain(LIBELLE_CALCULE)
  })

  it('même année : comparée sur le millésime écrit', () => {
    expect(memeAnnee('LFI 2023', 'Exécution 2024')).toBe(false)
    expect(memeAnnee('Exécution 2024', 2024)).toBe(true)
    expect(memeAnnee(null, 2024)).toBe(false)
    expect(memeAnnee('sans année', 'sans année')).toBe(false)
  })

  it('chaque appel de badgeCalcule dans les écrans écrit une méthode', () => {
    let appels = 0
    for (const { f, code } of sources) {
      for (const m of sansCommentaires(code).matchAll(/badgeCalcule\(\s*([^)]{0,2})/g)) {
        appels++
        expect(m[1], `${f} : badgeCalcule sans méthode`).not.toBe('')
        expect(/^(''|""|``)$/.test(m[1]), `${f} : méthode vide`).toBe(false)
      }
    }
    expect(appels).toBeGreaterThan(5)
  })

  it('aucun écran n’annonce un calcul du site sans le badge « Calculé par le site »', () => {
    const fautes: string[] = []
    for (const { f, code } of sources) {
      sansCommentaires(code)
        .split('\n')
        .forEach((l, i) => {
          if (!/calcul(?:é|ée|és|ées)? (?:par le site|par le projet)|calcul du site/i.test(l)) return
          // Phrases qui disent qu'aucun calcul n'est fait, ou ligne qui pose le badge : admises.
          if (/badgeCalcule\(|ne calcule pas|pas de |n’est pas calculé|non calculé|aucun .* calculé|« Calculé par le site »|id="methode-calcule"/i.test(l)) return
          fautes.push(`${f}:${i + 1}`)
        })
    }
    expect(fautes).toEqual([])
  })
})

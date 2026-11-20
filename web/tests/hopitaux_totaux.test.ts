// @vitest-environment happy-dom
// Bloc « Les totaux publiés par l'ATIH » de /explorer/hopitaux (site/data/hopitaux_totaux/) : totaux de la source,
// aucune addition, absence affichée « non publié ».
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { blocHopTotaux } from '../src/ecrans/hopitaux'
import { eurLisible } from '../src/util'

const D = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'hopitaux_totaux', 'data', 'hopitaux_totaux', 'index.json'), 'utf8'))
const n = (t: string | null | undefined) => (t ?? '').replace(/\s+/g, ' ').trim()

describe('totaux ATIH', () => {
  it('trois colonnes de totaux publiés, chiffres de la source', () => {
    const d = document.createElement('div')
    d.innerHTML = blocHopTotaux(D, 2024)
    expect(d.querySelectorAll('thead th')).toHaveLength(4)
    const l = D.lignes.find((x: unknown[]) => x[0] === 2024 && x[1] === 'TOT' && x[2] === 'TOT' && x[3] === 'TOT')
    const produits = Array.from(d.querySelectorAll('tbody tr')).find((tr) => n(tr.querySelector('th')?.textContent) === D.definitions.produits_eur)!
    expect(n(produits.querySelectorAll('td')[0].textContent)).toBe(n(eurLisible(l[D.colonnes.indexOf('produits_eur')])))
    expect(d.querySelector('caption')?.textContent).toContain('2024')
  })
})

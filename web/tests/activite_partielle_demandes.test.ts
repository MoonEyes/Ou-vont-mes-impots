// @vitest-environment happy-dom
// Bloc « Le chômage partiel demandé en 2020 » de /decisions/controle (site/data/activite_partielle_demandes/) :
// demandes reprises telles quelles, jamais présentées comme des montants versés.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { blocApRegion } from '../src/ecrans/controle'
import { entier } from '../src/util'

const D = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'activite_partielle_demandes', 'data', 'activite_partielle_demandes', 'index.json'), 'utf8'))
const n = (t: string | null | undefined) => (t ?? '').replace(/\s+/g, ' ').trim()

describe('activité partielle 2020', () => {
  it('une ligne par secteur, chiffres de la source, aucun montant en euros', () => {
    const d = document.createElement('div')
    d.innerHTML = blocApRegion(D, '52')
    const l = D.lignes.filter((x: string[]) => x[0] === '52')
    expect(d.querySelectorAll('tbody tr')).toHaveLength(l.length)
    expect(n(d.querySelector('tbody tr')?.textContent)).toContain(n(entier(l[0][2])))
    expect(d.textContent).not.toContain('€')
    expect(d.querySelector('caption')?.textContent).toContain('demandes')
  })
})

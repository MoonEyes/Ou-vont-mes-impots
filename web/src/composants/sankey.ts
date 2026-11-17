// Sankey sur deux niveaux (ECharts, Apache-2.0), chargé à la demande et seulement sur écran large.
// L'alternative textuelle est la liste dépliable rendue à côté par l'écran.
import type { Noeud } from '../donnees'
import { libelle, md } from '../util'

export const ECRAN_LARGE = '(min-width: 56rem)'

export function ecranLarge(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(ECRAN_LARGE).matches
}

/** Construit les nœuds et liens : nœud > enfants > petits-enfants (s'ils sont déjà chargés). */
export function donneesSankey(n: Noeud, maxEnfants = 12, maxPetits = 8) {
  const nodes: { name: string; depth: number }[] = []
  const links: { source: string; target: string; value: number }[] = []
  const vus = new Set<string>()
  const ajouter = (nom: string, depth: number) => {
    let x = nom
    let i = 2
    while (vus.has(x)) x = `${nom} (${i++})`
    vus.add(x)
    nodes.push({ name: x, depth })
    return x
  }
  const racine = ajouter(libelle(n.nom), 0)
  const enfants = [...(n.enfants ?? [])].sort((a, b) => b.md - a.md)
  const gardes = enfants.slice(0, maxEnfants)
  const reste = enfants.slice(maxEnfants).reduce((s, e) => s + e.md, 0)
  for (const e of gardes) {
    if (e.md <= 0) continue
    const ne = ajouter(libelle(e.nom), 1)
    links.push({ source: racine, target: ne, value: e.md })
    const petits = [...(e.enfants ?? [])].sort((a, b) => b.md - a.md)
    const pg = petits.slice(0, maxPetits)
    const pr = petits.slice(maxPetits).reduce((s, x) => s + x.md, 0)
    for (const p of pg) if (p.md > 0) links.push({ source: ne, target: ajouter(libelle(p.nom), 2), value: p.md })
    if (pr > 0) links.push({ source: ne, target: ajouter(`Autres (${libelle(e.nom)})`, 2), value: pr })
  }
  if (reste > 0) links.push({ source: racine, target: ajouter('Autres postes', 1), value: reste })
  return { nodes, links }
}

let echartsPromesse: Promise<typeof import('./echarts-partiel')> | null = null
function echarts() {
  if (!echartsPromesse) echartsPromesse = import('./echarts-partiel')
  return echartsPromesse
}

/** Dessine le Sankey dans conteneur ; renvoie une fonction de nettoyage. */
export async function dessinerSankey(conteneur: HTMLElement, n: Noeud): Promise<() => void> {
  const ec = await echarts()
  const graphe = ec.init(conteneur, undefined, { renderer: 'canvas' })
  const { nodes, links } = donneesSankey(n)
  graphe.setOption({
    animation: false,
    textStyle: { fontFamily: 'Inter, system-ui, sans-serif', color: '#1B1F24' },
    tooltip: {
      trigger: 'item',
      // Texte brut, sans style en ligne (CSP).
      formatter: (p: { dataType?: string; data: { source?: string; target?: string; value?: number; name?: string }; value?: number }) =>
        p.dataType === 'edge'
          ? `${p.data.source} vers ${p.data.target} : ${md(p.data.value ?? 0)}`
          : `${p.data.name} : ${md(Number(p.value ?? 0))}`,
    },
    series: [
      {
        type: 'sankey',
        data: nodes,
        links,
        nodeAlign: 'left',
        nodeGap: 6,
        layoutIterations: 0,
        emphasis: { focus: 'adjacency' },
        lineStyle: { color: 'source', opacity: 0.35 },
        itemStyle: { color: '#1F4E8C', borderColor: '#1B1F24', borderWidth: 0.5 },
        label: { color: '#1B1F24', fontSize: 12, overflow: 'truncate', width: 220 },
        levels: [
          { depth: 0, itemStyle: { color: '#1F4E8C' } },
          { depth: 1, itemStyle: { color: '#3F6FB0' } },
          { depth: 2, itemStyle: { color: '#6B93C9' } },
        ],
      },
    ],
  })
  const redim = () => graphe.resize()
  window.addEventListener('resize', redim)
  return () => {
    window.removeEventListener('resize', redim)
    graphe.dispose()
  }
}

// Méthode : limites connues, rassemblées depuis les fichiers de données (chaque limite garde sa source).
import { chargerSiPresent } from '../donnees'
import { h } from '../util'

const FICHIERS: [string, string, (d: any) => string[]][] = [
  ['prelevements/tva_conso.json', 'Taxes sur la consommation', (d) => [...(d.limites ?? []), ...(d['non_sourcé'] ?? [])]],
  ['prelevements/taxe_fonciere.json', 'Taxe foncière et TEOM', (d) => d.limites ?? []],
  ['tracabilite/resume.json', 'Traçabilité du budget de l’État', (d) => d.limites ?? []],
  ['vie_politique/annees.json', 'Vie politique', (d) => d.trous ?? []],
  ['ue/retours.json', 'Union européenne', (d) => d.limites ?? []],
  ['local/decisions/index.json', 'Subventions des collectivités', (d) => (d.limites ? [d.limites] : [])],
  ['dette/index.json', 'Dette publique', (d) => (d.sources_inaccessibles ?? []).map((s: { source: string; motif: string }) => `${s.source} : ${s.motif}`)],
  ['niches/index.json', 'Dépenses fiscales', (d) => (d.sources_inaccessibles ?? []).map((s: { source: string; motif?: string; constat?: string }) => `${s.source} : ${s.motif ?? s.constat ?? ''}`)],
]

export async function rendre(cible: HTMLElement) {
  const blocs = await Promise.all(
    FICHIERS.map(async ([f, titre, lire]) => {
      const d = await chargerSiPresent(f)
      const l = d ? lire(d).filter(Boolean) : []
      return l.length ? `<h2>${h(titre)}</h2><ul>${l.map((x) => `<li>${h(x)}</li>`).join('')}</ul><p class="source">site/data/${h(f)}</p>` : ''
    }),
  )
  cible.innerHTML = `
<h1>Limites connues</h1>
<p class="chapeau">Ce que les données publiques ne permettent pas de dire, et les sources qui n’ont pas pu être lues. Le site ne comble jamais un trou par une estimation sans le signaler.</p>
<h2>Ton calcul personnel</h2>
<ul>
  <li>Pas de prestations sociales, d’autres revenus, de frais réels ni de réductions ou crédits d’impôt.</li>
  <li>Complémentaire santé et prévoyance d’entreprise non comptées (variables d’un employeur à l’autre).</li>
  <li>Taxes sur la consommation : moyenne de ton décile de niveau de vie, pas ta consommation réelle.</li>
  <li>Hors V1 : fonctionnaires, indépendants, retraités, outre-mer, Alsace-Moselle.</li>
</ul>
${blocs.join('')}
<p>Méthode complète : <a href="#/methode">Méthode et sources</a>.</p>`
}

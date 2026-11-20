// Dépenses fiscales et exonérations de cotisations (site/data/niches/) : moindres recettes estimées, mesure par mesure.
import { partPersonnelle } from '../composants/hub'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { barres, entier, eurLisible, h, md, source } from '../util'
import { enCours } from './dette'

interface Index {
  millesime: string
  source: string
  totaux: Record<string, { statut: string; chiffre_meur: number; mesures: number; chiffrees: number; nc: number; total_publie_meur: number | null; ecart_meur?: number; ecart_explication?: string }>
  top_2025: { id: string; libelle: string; impot: string; meur: number; statut: string; programme: string | null }[]
  par_impot_2025: { impot: string; mesures: number; chiffre_2025_meur: number }[]
  niches_sociales: { exonerations_robss_md: Record<string, number>; exemptions_assiette_nettes_md: Record<string, number> }
  beneficiaires_nommes: { constat: string }
}

export async function rendre(cible: HTMLElement) {
  const idx = await chargerSiPresent<Index>('niches/index.json')
  if (!idx) {
    cible.innerHTML = enCours('Dépenses fiscales et exonérations de cotisations', 'Réductions d’impôt et de cotisations, mesure par mesure.') + partPersonnelle()
    return
  }
  const t24 = idx.totaux['2024']
  const annees = Object.keys(idx.totaux).sort()
  cible.innerHTML = `
<h1>Dépenses fiscales et exonérations de cotisations</h1>
<p class="chapeau">Une dépense fiscale (souvent appelée niche fiscale) est une disposition qui réduit l’impôt dû par certains contribuables ou certaines activités : crédit d’impôt, taux réduit, exonération. Elle n’est pas versée : elle diminue les recettes publiques. L’administration en publie une estimation, mesure par mesure.</p>
<div class="carte" data-cle>
  <p class="grand-chiffre">${h(md(t24.chiffre_meur / 1000))}</p>
  <p class="sous-chiffre">de dépenses fiscales chiffrées en 2024 (${h(t24.statut)}, ${h(entier(t24.chiffrees))} mesures chiffrées sur ${h(entier(t24.mesures))}).</p>
  <p class="aide" data-sans-ratio>Ce montant n’est pas rapporté aux dépenses de l’État : une dépense fiscale est une recette en moins, pas une dépense versée, et les deux ne portent pas sur le même périmètre.</p>
  ${source(idx.source, idx.millesime)}
</div>
<h2>Les mesures au montant estimé le plus élevé en 2025</h2>
${barres(
  idx.top_2025.slice(0, 12).map((m) => ({
    nom: m.libelle,
    valeur: m.meur,
    texte: eurLisible(m.meur * 1e6),
    lien: m.programme ? lien('/beneficiaires/programme', { p: m.programme }) : undefined,
    detail: `${m.impot}${m.programme ? ` · programme ${m.programme}` : ''}`,
    statut: 'approche' as const,
  })),
  undefined,
  'Mesures au montant estimé le plus élevé en 2025',
)}
<h2>Par impôt, en 2025</h2>
${barres(
  idx.par_impot_2025.map((x) => ({ nom: x.impot, valeur: x.chiffre_2025_meur, texte: eurLisible(x.chiffre_2025_meur * 1e6), detail: `${x.mesures} mesures` })),
  undefined,
  'Dépenses fiscales par impôt',
)}
<div class="tableau-defile"><table><caption>Total chiffré par année, millions d’euros</caption><thead><tr><th scope="col">Année</th><th scope="col">Statut</th><th scope="col" class="nombre">Somme des mesures</th><th scope="col" class="nombre">Total publié</th><th scope="col" class="nombre">Non chiffrées</th></tr></thead><tbody>${annees
    .map((a) => {
      const x = idx.totaux[a]
      return `<tr><th scope="row">${a}</th><td>${h(x.statut)}</td><td class="nombre">${h(entier(x.chiffre_meur))}</td><td class="nombre">${x.total_publie_meur !== null ? h(entier(x.total_publie_meur)) : '–'}</td><td class="nombre">${h(entier(x.nc))}</td></tr>`
    })
    .join('')}</tbody></table></div>
<p class="aide">Les mesures « non chiffrées » par l’administration ne sont jamais comptées pour zéro : elles sont exclues de la somme.${annees
    .filter((a) => idx.totaux[a].ecart_meur && idx.totaux[a].ecart_explication)
    .map((a) => ` ${a} : écart avec le total publié, ${h(idx.totaux[a].ecart_explication!)}.`)
    .join('')}</p>
<h2>Exonérations de cotisations sociales (souvent appelées niches sociales)</h2>
<p>Exonérations et allègements de cotisations : ${h(md(idx.niches_sociales.exonerations_robss_md['2024']))} en 2024. Elles sont en grande partie compensées à la Sécurité sociale par l’État : ne pas les ajouter aux dépenses fiscales.</p>
<p class="aide">${h(idx.beneficiaires_nommes.constat)}</p>
<p class="liens-sortie"><a href="#/explorer/recettes">Les recettes : chaque impôt et qui l’encaisse</a></p>
${partPersonnelle()}`
}

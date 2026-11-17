// Écran 3 : où va l'argent de l'État « sur 100 € », avec la part empruntée.
import { blocTracabilite } from '../composants/tracabilite'
import { charger, chargerSiPresent, type Noeud, VUES_ARBRE, vueArbre } from '../donnees'
import { session } from '../etat'
import { lien } from '../routeur'
import { absent, eur, h, libelle, md, pct, source, sur100 } from '../util'

interface Deficit {
  etat: { lecture: string; perimetre: string; comptabilite: string; annees: Record<string, { part_empruntee: number; solde_budgetaire_md: number }> }
  administrations_publiques: { comptabilite: string; annees: Record<string, { part_empruntee: number; B9_md: number; TE_md: number }> }
  source: string
  avertissement: string
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const vue = vueArbre(params.get('m'))
  const vues = VUES_ARBRE.filter((v) => v.cle !== 'nature2025')
  const v = vues.includes(vue) ? vue : vues[0]
  const [racine, deficit] = await Promise.all([charger<Noeud>(`${v.dossier}/racine.json`), chargerSiPresent<Deficit>('deficit.json')])
  const total = racine.md
  const postes = racine.enfants ?? []
  const emprunt = deficit?.etat.annees[racine.millesime ?? v.millesime]
  const annees = deficit ? Object.keys(deficit.administrations_publiques.annees).sort() : []
  const derniere = annees[annees.length - 1]
  const apu = derniere ? deficit!.administrations_publiques.annees[derniere] : null

  const ir = session.resultat?.prelevements.filter((l) => l.famille === 'impot_revenu').reduce((s, l) => s + l.montant_annuel_eur.central, 0) ?? 0

  cible.innerHTML = `
<h1>Sur 100 € dépensés par l’État</h1>
<p class="chapeau">Le budget de l’État (${h(md(total))}, ${h(racine.millesime ?? v.millesime)}) découpé en grands postes, ramené à 100 €. Les remboursements et dégrèvements d’impôts ne sont pas comptés : c’est de l’argent rendu, pas dépensé.</p>
<div class="bascule" role="group" aria-label="Millésime">
  ${vues.map((x) => `<a class="bouton" href="${lien('/etat', { m: x.cle })}"${x === v ? ' aria-current="true"' : ''}>${h(x.libelle)}</a>`).join('')}
</div>
<div class="carte">
  <div class="empile" role="img" aria-label="Répartition des 100 € par grand poste, détaillée dans la liste ci-dessous">
    ${postes.map((p, i) => `<span class="c${i % 12}" data-l="${((p.md / total) * 100).toFixed(3)}"></span>`).join('')}
  </div>
  ${
    emprunt
      ? `<div class="emprunt-regle" aria-hidden="true"><span data-g="${(100 - emprunt.part_empruntee * 100).toFixed(2)}" data-l="${(emprunt.part_empruntee * 100).toFixed(2)}"></span></div>
  <p class="legende-orange">Dont ${h(sur100(emprunt.part_empruntee * 100))} empruntés : sur 100 € dépensés, environ ${h(sur100(emprunt.part_empruntee * 100))} ne sont pas couverts par les recettes de l’année (${h(racine.millesime ?? v.millesime)}).</p>`
      : absent('Part empruntée non disponible pour ce millésime.')
  }
  <ul class="barres">
    ${postes
      .map(
        (p, i) =>
          `<li><div class="barre-tete"><a href="${lien('/detail', { m: v.cle, id: p.id })}"><span class="pastille c${i % 12}" aria-hidden="true"></span>${h(libelle(p.nom))}</a><span class="valeur">${h(sur100((p.md / total) * 100))}</span></div><div class="aide">${h(md(p.md))}${
            ir > 0 ? ` · sur ton impôt sur le revenu : ${h(eur((ir * p.md) / total))} par an` : ''
          }</div></li>`,
      )
      .join('')}
  </ul>
  ${source(racine.source ?? '', racine.millesime)}
</div>
${
  ir > 0
    ? `<p class="aide">Ton impôt sur le revenu (${h(eur(ir))} par an) n’est pas fléché vers un poste : la répartition ci-dessus l’applique au prorata du budget de l’État, pour donner un ordre de grandeur. Tes cotisations et ta CSG vont, elles, à la Sécurité sociale (écran 2).</p>`
    : ''
}
${
  emprunt && deficit
    ? `<details class="carte"><summary>Comment est calculée la part empruntée ?</summary>
  <p>${h(deficit.etat.lecture)}</p>
  <p>Solde budgétaire ${h(racine.millesime ?? v.millesime)} : ${h(md(emprunt.solde_budgetaire_md))} (comptabilité ${h(deficit.etat.comptabilite)}). ${h(deficit.etat.perimetre)}</p>
  ${
    apu && derniere
      ? `<p>Pour l’ensemble des administrations publiques (État, Sécurité sociale, collectivités), en comptabilité nationale, la part empruntée est de ${h(pct(apu.part_empruntee * 100))} en ${h(derniere)} (déficit ${h(md(-apu.B9_md))} pour ${h(md(apu.TE_md))} de dépenses). ${h(deficit.avertissement)}</p>`
      : ''
  }
  ${source(deficit.source)}
</details>`
    : ''
}
<div id="trac"></div>
<div class="actions"><a class="bouton bouton-principal" href="${lien('/detail', { m: v.cle })}">Voir le détail, aussi loin que tu veux</a><a class="bouton" href="#/recettes">D’où vient l’argent ?</a></div>`
  const t = await blocTracabilite('racine', 'racine', racine.millesime ?? v.millesime)
  ;(cible.querySelector('#trac') as HTMLElement).innerHTML = t
}

// Écran 3 : où va l'argent de l'État « sur 100 € », avec la part empruntée.
import { blocTracabilite } from '../composants/tracabilite'
import { charger, chargerSiPresent, type Noeud, VUES_ARBRE, vueArbre } from '../donnees'
import { LIBELLE_ADMINISTRATION } from '../calcul/destinataires'
import { parAdministration, sur100Entiers } from '../calcul/repartition'
import { session } from '../etat'
import { lien } from '../routeur'
import { absent, barres, eur, h, libelle, md, pct, source, sur100, surligne } from '../util'

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

  // Ce que tu verses (écran 2), réparti par administration selon les destinataires de chaque prélèvement.
  const lignes = session.complet?.lignes ?? session.resultat?.prelevements.filter((l) => l.inclus_dans_total_paye) ?? []
  const parAdmin = parAdministration(lignes)
  const s100Admin = sur100Entiers(parAdmin)
  const totalPaye = session.complet?.total.central ?? Object.values(parAdmin).reduce((a, b) => a + b, 0)
  const ir = parAdmin.Etat ?? 0

  cible.innerHTML = `
<h1>Sur 100 € dépensés par l’État</h1>
<p class="chapeau">Le budget de l’État (${h(md(total))}, ${h(racine.millesime ?? v.millesime)}) découpé en grands postes, ramené à 100 €. Les remboursements et dégrèvements d’impôts ne sont pas comptés : c’est de l’argent rendu, pas dépensé.</p>
<div class="bascule" role="group" aria-label="Millésime">
  ${vues.map((x) => `<a class="bouton" href="${lien('/explorer/etat', { m: x.cle })}"${x === v ? ' aria-current="true"' : ''}>${h(x.libelle)}</a>`).join('')}
</div>
${
  emprunt
    ? `<div class="carte" data-cle>
  <div class="empile" aria-hidden="true"><span class="recettes-seg" data-l="${(100 - emprunt.part_empruntee * 100).toFixed(2)}"></span><span class="emprunt-seg" data-l="${(emprunt.part_empruntee * 100).toFixed(2)}"></span></div>
  <p>Sur 100 € dépensés par l’État (${h(md(total))} au total) : <strong class="texte-accent">${h(sur100(100 - emprunt.part_empruntee * 100))}</strong> venaient des recettes de l’année, <strong class="texte-emprunt">${surligne(sur100(emprunt.part_empruntee * 100))}</strong> ont été empruntés (${h(racine.millesime ?? v.millesime)}).</p>
</div>`
    : absent('Part empruntée non disponible pour ce millésime.')
}
<div class="carte">
  ${barres(
    postes.map((p) => ({
      nom: libelle(p.nom),
      valeur: p.md,
      texte: sur100((p.md / total) * 100),
      lien: lien('/explorer/etat/detail', { m: v.cle, id: p.id }),
      detail: `${md(p.md)}${ir > 0 ? ` · sur ce que tu verses à l’État : ${eur((ir * p.md) / total)} par an` : ''}`,
    })),
    undefined,
    'Grands postes, en euros sur 100 €',
  )}
  ${source(racine.source ?? '', racine.millesime)}
</div>
${
  ir > 0
    ? `<div class="carte"><h2>Et ce que tu verses ?</h2><p>Sur les ${h(eur(totalPaye))} que ton foyer verse chaque année (écran 2, valeur centrale), environ :</p><ul>${Object.entries(parAdmin)
        .sort((a, b) => b[1] - a[1])
        .map(
          ([a, v]) =>
            `<li>${h(eur(v))}, soit ${s100Admin[a] ?? 0} € sur 100 €, ${a === 'Plusieurs' ? 'sans destinataire publié' : `pour : ${h(LIBELLE_ADMINISTRATION[a as 'Etat'])}`}</li>`,
        )
        .join('')}</ul><p class="aide">La part qui va à l’État (${h(eur(ir))}) n’est pas fléchée vers un poste : la liste ci-dessus l’applique au prorata du budget de l’État, pour donner un ordre de grandeur. Le reste va à la Sécurité sociale et aux collectivités.</p></div>`
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
<div class="actions"><a class="bouton bouton-principal" href="${lien('/explorer/etat/detail', { m: v.cle })}">Voir le détail, aussi loin que tu veux</a><a class="bouton" href="#/explorer/recettes">D’où vient l’argent ?</a></div>`
  const t = await blocTracabilite('racine', 'racine', racine.millesime ?? v.millesime)
  ;(cible.querySelector('#trac') as HTMLElement).innerHTML = t
}

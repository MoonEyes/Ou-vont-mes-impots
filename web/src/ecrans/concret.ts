// Écran 5 : concrètement, à quoi sert l'argent d'un programme (nature de la dépense, effectifs).
import { brancherFiltre, choixProgramme } from '../composants/choix-programme'
import { blocTracabilite } from '../composants/tracabilite'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { absent, barres, entier, eur, eurLisible, h, pct, source, sur100 } from '../util'

interface Nature {
  millesime: string
  source: string
  programme: string
  libelle: string
  mission: string
  total_eur: number
  eur_sur_100: number
  postes: { id: string; libelle: string; eur: number; part_programme_pct: number; eur_sur_100: number; categories: string[] }[]
  controle_arbre: { ecart_pct: number; explication: string } | null
}
interface Effectifs {
  millesime: string
  source: string
  etpt: number | null
  millesime_etpt: string
  nature_etpt?: string
  categories_emploi: { categorie_emploi: string; etpt: number }[]
  titre2_eur: number
  millesime_titre2: string
  eur_sur_100_titre2: number
  cout_moyen_par_etpt_eur: number | null
  avertissement: string | null
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const p = params.get('p')
  if (!p || !/^\d{3}$/.test(p)) {
    cible.innerHTML = await choixProgramme('/concret', 'Concrètement', 'Choisis un programme du budget de l’État pour voir à quoi sert son argent : salaires, fonctionnement, aides, investissements, et combien de personnes y travaillent.')
    brancherFiltre(cible)
    return
  }
  const [nat, eff] = await Promise.all([chargerSiPresent<Nature>(`nature/${p}.json`), chargerSiPresent<Effectifs>(`effectifs/${p}.json`)])
  const titre = nat?.libelle ?? `Programme ${p}`
  const blocNature = nat
    ? `<div class="carte">
  <p>Dépense 2024 : <strong>${h(eurLisible(nat.total_eur))}</strong>, soit ${h(sur100(nat.eur_sur_100))} sur 100 € du budget de l’État.</p>
  ${barres(
    nat.postes.map((x) => ({
      nom: x.libelle,
      valeur: x.eur,
      texte: eurLisible(x.eur),
      detail: `${pct(x.part_programme_pct)} du programme · ${sur100(x.eur_sur_100)} sur 100 € du budget`,
    })),
    undefined,
    'Nature de la dépense',
  )}
  ${nat.controle_arbre && Math.abs(nat.controle_arbre.ecart_pct) > 3 ? `<p class="avertissement">Écart de ${h(pct(nat.controle_arbre.ecart_pct))} avec l’arbre du budget : ${h(nat.controle_arbre.explication)}</p>` : ''}
  ${source(nat.source, nat.millesime)}
</div>`
    : absent('Nature de la dépense non disponible pour ce programme.')

  const blocEff = eff
    ? `<div class="carte">
  <h2>Les personnes qui y travaillent</h2>
  ${
    eff.etpt
      ? `<p class="grand-chiffre">${h(entier(Math.round(eff.etpt)))}</p><p class="sous-chiffre">emplois en équivalent temps plein (${h(eff.millesime_etpt)}${eff.nature_etpt ? `, ${h(eff.nature_etpt)}` : ''})</p>`
      : absent('Pas d’effectif publié pour ce programme.')
  }
  <p>Dépenses de personnel : ${h(eurLisible(eff.titre2_eur))} (${h(eff.millesime_titre2)}), ${h(sur100(eff.eur_sur_100_titre2))} sur 100 € du budget.${
    eff.cout_moyen_par_etpt_eur ? ` Coût complet moyen par emploi : ${h(eur(eff.cout_moyen_par_etpt_eur))} par an (salaire, cotisations et pensions, pas un salaire net).` : ''
  }</p>
  ${
    eff.categories_emploi?.length
      ? barres(
          eff.categories_emploi.map((c) => ({ nom: c.categorie_emploi, valeur: c.etpt, texte: `${entier(Math.round(c.etpt))} ETPT` })),
          undefined,
          'Emplois par catégorie',
        )
      : ''
  }
  ${eff.avertissement ? `<p class="avertissement">${h(eff.avertissement)}</p>` : ''}
  ${source(eff.source, eff.millesime)}
</div>`
    : ''

  cible.innerHTML = `
<h1>${h(titre)}</h1>
<p class="chapeau">Programme ${h(p)}${nat ? ` · mission ${h(nat.mission)}` : ''}. À quoi sert concrètement l’argent : la nature réelle de la dépense en 2024.</p>
<p><a href="${lien('/concret')}">Choisir un autre programme</a></p>
<h2>Où part l’argent</h2>
${blocNature}
${blocEff}
<div id="trac"></div>
<div class="actions"><a class="bouton" href="${lien('/beneficiaires', { p })}">Qui reçoit l’argent</a><a class="bouton" href="${lien('/realisations', { p })}">Ce qui a été fait</a></div>`
  ;(cible.querySelector('#trac') as HTMLElement).innerHTML = await blocTracabilite('programme', p, 'Exécution 2024')
}

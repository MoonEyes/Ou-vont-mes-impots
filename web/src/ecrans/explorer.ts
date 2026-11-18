// Hub « Explorer » : les caisses de l'argent public, en tuiles à la même échelle, puis toutes les autres pages
// du hub en rubriques par thème, lues dans la table des routes (une page ajoutée avec parent '/explorer' y apparaît d'elle-même).
import { CHEMINS_CAISSES, remplirTuiles, tuiles } from '../composants/caisses'
import { rubriques } from '../composants/hub'

export function rendre(cible: HTMLElement) {
  const autres = rubriques('/explorer', { exclure: CHEMINS_CAISSES })
  cible.innerHTML = `
<h1>Explorer les dépenses publiques</h1>
<p class="chapeau">L’argent public passe par plusieurs caisses : l’État, la Sécurité sociale, les collectivités locales, l’Union européenne. Choisis par où commencer. Les petits carrés sont tous à la même échelle, pour comparer d’un coup d’œil.</p>
${tuiles(true)}
${autres ? `<p class="aide">En dessous, les autres pages, rangées par thème et par ordre alphabétique. Cet ordre ne dit rien de l’importance d’un sujet ni de son montant.</p>${autres}` : ''}
<p>Pour une commune précise, va dans <a href="#/local">Budget de ma commune</a>. Pour les bénéficiaires nommés, va dans <a href="#/beneficiaires">Qui reçoit l’argent</a>.</p>
<section class="carte carte-contour appel" aria-labelledby="titre-appel">
  <div>
    <h2 id="titre-appel">Tu préfères partir de ton salaire ?</h2>
    <p class="chapeau">En deux minutes, tu vois ce que tu verses en un an et où part chaque euro.</p>
  </div>
  <a class="bouton bouton-principal" href="#/calcul">Voir ta part personnelle</a>
</section>`
  return { suite: remplirTuiles(cible) }
}

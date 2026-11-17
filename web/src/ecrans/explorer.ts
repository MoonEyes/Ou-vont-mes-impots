// Hub « Explorer » : les grands ensembles de la dépense et des recettes publiques.
import { cartesRayons, partPersonnelle } from '../composants/hub'

export function rendre(cible: HTMLElement) {
  cible.innerHTML = `
<h1>Explorer les dépenses publiques</h1>
<p class="chapeau">L’argent public passe par plusieurs caisses : l’État, la Sécurité sociale, les collectivités locales, l’Union européenne. Choisis par où commencer.</p>
${cartesRayons('/explorer')}
<p>Pour une commune précise, va dans <a href="#/local">Budget de ma commune</a>. Pour les bénéficiaires nommés, va dans <a href="#/beneficiaires">Qui reçoit l’argent</a>.</p>
${partPersonnelle()}`
}

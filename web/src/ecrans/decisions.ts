// Hub « Décisions et contrôle » : qui décide, ce qui a été fait, qui contrôle.
import { cartesRayons } from '../composants/hub'

export function rendre(cible: HTMLElement) {
  cible.innerHTML = `
<h1>Décisions et contrôle</h1>
<p class="chapeau">Qui vote le budget, qui le modifie en cours d’année, ce qui a été réalisé, et qui contrôle.</p>
${cartesRayons('/decisions')}
<p>Pour un programme précis, commence par <a href="#/beneficiaires/programme">un programme en détail</a> : il renvoie à ses votes, ses réalisations et ses bénéficiaires.</p>`
}

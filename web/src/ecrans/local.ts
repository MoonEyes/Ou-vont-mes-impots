// Hub « Chez moi » : choisir sa commune (fichiers par département, chargés à la demande).
import { fragmentCommune, fragmentDepartement } from '../chemins'
import { cartesRayons, partPersonnelle } from '../composants/hub'
import { trame } from '../composants/trame'
import { TOUS_DEPARTEMENTS, departementDe } from '../departements'
import { chargerSiPresent } from '../donnees'
import { session } from '../etat'
import { lien } from '../routeur'
import { h } from '../util'
import { brancherFormulaire, formulaire } from './ma_commune_recherche'

export async function rendre(cible: HTMLElement) {
  const insee = session.profil?.residence.commune_insee
  cible.innerHTML = `
<h1>Budget de ma commune</h1>
<p class="chapeau">Ce que dépensent ta commune, ton intercommunalité, ton département et ta région, ce que l’État leur verse, et les taux d’impôts locaux votés.</p>
<div class="colonnes c-6-6">
  <div>
    <h2>Ma commune en un écran</h2>
    ${formulaire('local-recherche')}
    <h2>Chercher une commune par département</h2>
    <form id="choix-commune" class="carte carte-contour">
      <label for="dep-local">Département</label>
      <select id="dep-local"><option value="">Choisir</option>${TOUS_DEPARTEMENTS.map(([c, n]) => `<option value="${c}">${c} ${h(n)}</option>`).join('')}</select>
      <div id="com-local-bloc" hidden>
        <label for="com-local">Commune</label>
        <select id="com-local"></select>
      </div>
      <p class="actions"><button type="submit" class="bouton-principal">Voir ma commune</button></p>
      <p id="msg-local" class="message-champ" hidden></p>
    </form>
    ${insee ? `<p class="actions"><a class="bouton" href="${lien('/local/commune', { insee })}">Voir la commune saisie dans ton calcul</a></p>` : ''}
    <p>Vue d’ensemble nationale : <a href="#/explorer/collectivites">les collectivités locales</a>.</p>
  </div>
  <section class="carte carte-contour seulement-large" aria-labelledby="titre-trame">
    <h2 id="titre-trame">Où c’est</h2>
    ${trame(insee ? departementDe(insee) : undefined)}
    <p class="aide">Un carré par département, placé à peu près où il se trouve. Chaque carré ouvre sa fiche.</p>
  </section>
</div>
<h2>Par département</h2>
<ul class="liste-colonnes">${TOUS_DEPARTEMENTS.map(([c, n]) => `<li><a href="${fragmentDepartement(c, n)}">${h(n)} (${c})</a></li>`).join('')}</ul>
${cartesRayons('/local')}
${partPersonnelle()}`
  brancherFormulaire(cible, 'local-recherche')
  const dep = cible.querySelector<HTMLSelectElement>('#dep-local')!
  const com = cible.querySelector<HTMLSelectElement>('#com-local')!
  let communes: Record<string, { nom: string; population?: number }> = {}
  const charger = async (d: string, choisie?: string) => {
    cible.querySelector<HTMLElement>('#com-local-bloc')!.hidden = !d
    if (!d) return
    com.innerHTML = '<option value="">Chargement…</option>'
    const g = await chargerSiPresent<{ communes: Record<string, { nom: string; population?: number }> }>(`local/geo/${d}.json`)
    communes = g?.communes ?? {}
    const liste = Object.entries(g?.communes ?? {}).sort((a, b) => a[1].nom.localeCompare(b[1].nom, 'fr'))
    com.innerHTML = liste.map(([c, v]) => `<option value="${c}"${c === choisie ? ' selected' : ''}>${h(v.nom)}</option>`).join('')
  }
  dep.addEventListener('change', () => charger(dep.value))
  if (insee) {
    dep.value = departementDe(insee)
    await charger(dep.value, insee)
  }
  cible.querySelector('#choix-commune')!.addEventListener('submit', (e) => {
    e.preventDefault()
    if (!com.value) {
      const m = cible.querySelector<HTMLElement>('#msg-local')!
      m.textContent = 'Choisis d’abord un département puis une commune.'
      m.hidden = false
      return
    }
    const c = communes[com.value]
    location.hash = c ? fragmentCommune(com.value, c.nom, c.population) : lien('/local/commune', { insee: com.value })
  })
}

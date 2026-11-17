// Hub « Chez moi » : choisir sa commune (fichiers par département, chargés à la demande).
import { partPersonnelle } from '../composants/hub'
import { DEPARTEMENTS, departementDe } from '../departements'
import { chargerSiPresent } from '../donnees'
import { session } from '../etat'
import { lien } from '../routeur'
import { h } from '../util'

export async function rendre(cible: HTMLElement) {
  const insee = session.profil?.residence.commune_insee
  cible.innerHTML = `
<h1>Chez moi : ta commune</h1>
<p class="chapeau">Ce que dépensent ta commune, ton intercommunalité, ton département et ta région, ce que l’État leur verse, et les taux d’impôts locaux votés.</p>
${insee ? `<p><a class="bouton bouton-principal" href="${lien('/local/commune', { insee })}">Voir la commune saisie dans ton calcul</a></p>` : ''}
<form id="choix-commune" class="carte">
  <label for="dep-local">Département</label>
  <select id="dep-local"><option value="">Choisir</option>${DEPARTEMENTS.map(([c, n]) => `<option value="${c}">${c} ${h(n)}</option>`).join('')}</select>
  <div id="com-local-bloc" hidden>
    <label for="com-local">Commune</label>
    <select id="com-local"></select>
  </div>
  <p class="actions"><button type="submit" class="bouton-principal">Voir ma commune</button></p>
  <p id="msg-local" class="message-champ" hidden></p>
</form>
<p>Vue d’ensemble nationale : <a href="#/explorer/collectivites">les collectivités locales</a>.</p>
${partPersonnelle()}`
  const dep = cible.querySelector<HTMLSelectElement>('#dep-local')!
  const com = cible.querySelector<HTMLSelectElement>('#com-local')!
  const charger = async (d: string, choisie?: string) => {
    cible.querySelector<HTMLElement>('#com-local-bloc')!.hidden = !d
    if (!d) return
    com.innerHTML = '<option value="">Chargement…</option>'
    const g = await chargerSiPresent<{ communes: Record<string, { nom: string }> }>(`local/geo/${d}.json`)
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
    location.hash = lien('/local/commune', { insee: com.value })
  })
}

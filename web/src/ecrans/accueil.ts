// Accueil : quatre portes (mon salaire, ma commune, qui reçoit l'argent, qui décide), le billet découpé d'un exemple,
// trois étapes, les caisses à explorer.
// Le texte et le billet s'affichent tout de suite (l'exemple est un petit fichier du site, écrit par les tests à
// partir du vrai calcul) ; les chiffres des tuiles et le nombre de sources, lus dans les données, complètent ensuite.
import { billet, listeParts, partsAdministrations } from '../composants/billet'
import { remplirTuiles, tuiles } from '../composants/caisses'
import { plusDeSources } from '../composants/chiffres-site'
import { sorties } from '../composants/resume-calcul'
import { ORDRE_ADMIN } from '../calcul/repartition'
import { DEPARTEMENTS } from '../departements'
import { chargerSiPresent } from '../donnees'
import { session } from '../etat'
import exemple from '../exemple-lyon.json'
import { METHODE_TOTAL, phrasePosition, positionCentrale } from '../calcul/fourchette'
import { badgeCalcule, badgeStatut, entier, eur, h, jaugeFourchette, nomVille } from '../util'

export function rendre(cible: HTMLElement) {
  const ex = exemple
  const net = `${entier(ex.profil.net_mensuel)} €`
  const ville = nomVille(ex.profil.commune)
  const parts = partsAdministrations(ex.sur100, ORDRE_ADMIN)
  const lignes = sorties(ex.sources)
  const etendue = ex.total.haut - ex.total.bas
  cible.innerHTML = `
<div class="heros heros-portes">
  <div class="heros-intro">
    <h1>Tu verses 100 €. Voilà où ils partent.</h1>
    <p class="chapeau">Cotisations, impôt sur le revenu, TVA, taxes locales : on additionne tout ce que tu verses en un an, puis on suit chaque euro jusqu’à ceux qui le reçoivent.</p>
  </div>
  <ol class="portes" aria-label="Par où commencer">
    <li class="porte porte-salaire">
      <form id="heros-form" class="carte carte-principale heros-form" novalidate aria-labelledby="porte-salaire">
        <h2 id="porte-salaire" class="porte-titre">Mon salaire</h2>
        <p class="porte-texte">Ton billet à toi : ce que tu verses en un an et à qui, calculé tout de suite.</p>
        <div class="heros-champs">
          <div>
            <label for="heros-net">Ton salaire net avant impôt, par mois</label>
            <span class="champ-euro"><input id="heros-net" type="text" inputmode="decimal" autocomplete="off" spellcheck="false" placeholder="Par exemple ${h(entier(ex.profil.net_mensuel))}" aria-describedby="heros-aide heros-msg" /></span>
            <p class="aide" id="heros-aide">Ligne « Net à payer avant impôt sur le revenu » de ta fiche de paie.</p>
          </div>
          <div>
            <label for="heros-dep">Ton département</label>
            <select id="heros-dep"><option value="">Ne pas préciser</option>${DEPARTEMENTS.map(([c, n]) => `<option value="${c}">${c} ${h(n)}</option>`).join('')}</select>
          </div>
          <div id="heros-com-bloc" hidden>
            <label for="heros-com">Ta commune</label>
            <select id="heros-com"></select>
          </div>
        </div>
        <p class="message-champ" id="heros-msg" hidden></p>
        <button type="submit" class="bouton-principal">Découper mon billet</button>
        <p class="calcul-en-cours" id="heros-statut" role="status" hidden></p>
        <p class="aide">Le calcul se fait dans ton navigateur. Aucun compte, rien n’est envoyé. Environ 2 minutes. Situation par défaut : personne seule, salariée du privé, à temps plein ; tu la précises ensuite avec <a href="#/calcul">le formulaire complet</a>.</p>
      </form>
    </li>
    <li class="porte">
      <h2 class="porte-titre"><a href="#/local/ma-commune">Ma commune</a></h2>
      <p class="porte-texte">Code postal ou nom : ce que ta commune, ton intercommunalité, ton département et ta région font de l’argent public.</p>
    </li>
    <li class="porte">
      <h2 class="porte-titre"><a href="#/beneficiaires">Qui reçoit l’argent</a></h2>
      <p class="porte-texte">Subventions, marchés publics, opérateurs : les organismes qui reçoivent de l’argent public, nommés quand ce sont des personnes morales.</p>
    </li>
    <li class="porte">
      <h2 class="porte-titre"><a href="#/decisions">Qui décide</a></h2>
      <p class="porte-texte">Votes du Parlement, mouvements de crédits, ce qui a été fait et qui contrôle.</p>
    </li>
  </ol>
</div>

${billet(parts, { etiquette: `Billet de 100 € découpé : exemple d’un salaire de ${net} net par mois, à ${ville}`, legendes: true })}
<div class="seulement-compact">${listeParts(parts, 'Où vont 100 € versés, dans cet exemple')}</div>
<p class="billet-note"><span>Billet affiché : celui d’un salaire de ${h(net)} net par mois, à ${h(ville)}.</span> <a href="#/calcul" id="voir-exemple">Voir ce résultat en entier</a></p>

<section class="bande" aria-labelledby="titre-etapes">
  <h2 id="titre-etapes">Trois étapes, pas plus</h2>
  <ol class="etapes">
    <li><strong>Tu donnes ton salaire</strong><span>Ton net avant impôt par mois, ta commune, ta situation de famille. Rien d’autre.</span></li>
    <li><strong>Ton navigateur calcule</strong><span>Cotisations, CSG, impôt sur le revenu, TVA estimée, impôts locaux : le total de ce que tu verses en un an.</span></li>
    <li><strong>Tu suis chaque euro</strong><span>Retraites, santé, école, dette, ta commune, jusqu’aux organismes qui reçoivent l’argent.</span></li>
  </ol>
</section>

<div class="entete-section">
  <div>
    <h2>Explorer sans donner ton salaire</h2>
    <p class="chapeau">L’argent public passe par plusieurs caisses. Choisis-en une, on suit l’argent ensemble.</p>
  </div>
  <a class="bouton" href="#/explorer">Tout explorer</a>
</div>
${tuiles()}

<div class="colonnes">
  <section class="carte carte-principale" aria-labelledby="titre-exemple-total" data-cle>
    <p id="titre-exemple-total" class="recap-titre">Ce que tu verses en un an${etendue > 0 ? ', estimation de référence' : ''}</p>
    <p class="grand-chiffre">${h(eur(ex.total.central))}</p>
    ${
      etendue > 0
        ? `<p class="recap-fourchette">Fourchette : <strong>entre ${h(eur(ex.total.bas))} et ${h(eur(ex.total.haut))}</strong></p>
    ${jaugeFourchette(ex.total)}
    <p class="aide">${h(phrasePosition(positionCentrale(ex.total)))} La fourchette dépend de ce que tu achètes et de ta taxe sur les ordures.</p>`
        : ''
    }
    <p class="aide">${badgeCalcule(METHODE_TOTAL.replace('ton foyer', 'ce foyer'))}</p>
  </section>
  <div>
    <h2>Un exemple : ${h(net)} net à ${h(ville)}</h2>
    <p class="chapeau">Sur une année, cette personne verse ${h(eur(ex.total.central))} selon l’estimation de référence. Une partie est connue à l’euro près, une autre dépend de ses achats : on te montre toujours la fourchette.</p>
    <ul class="postes">${lignes
      .map((l) => `<li><span class="p-nom">${h(l.nom)}<small>${h(l.detail)}</small></span><span class="p-montant">${h(l.texte)}</span>${badgeStatut(l.statut)}</li>`)
      .join('')}</ul>
  </div>
</div>

<h2>À quoi servent mes impôts ?</h2>
<p>Ce que tu verses en impôts, en cotisations et en taxes va à quatre ensembles : l’État, la Sécurité sociale, les collectivités locales et l’Union européenne. Le site suit chaque montant jusqu’au document public d’où il vient, jusqu’à la ligne du budget voté.</p>
<ul class="liens-sortie">
  <li><a href="#/explorer/etat">Le budget de l’État, sur 100 € dépensés</a></li>
  <li><a href="#/explorer/secu">Sécurité sociale : retraites, santé, famille</a></li>
  <li><a href="#/explorer/recettes">D’où vient l’argent : les recettes</a></li>
  <li><a href="#/explorer/dette">La dette publique</a></li>
  <li><a href="#/local">Budget de ma commune</a></li>
</ul>

<section class="demarche-bloc" aria-labelledby="titre-demarche">
  <div>
    <h2 id="titre-demarche">Une démarche citoyenne</h2>
    <p>Ce site n’appartient ni à l’État ni à un parti. Il montre où va l’argent, sans dire si c’est bien ou mal.</p>
    <p><strong>Une démarche citoyenne et indépendante :</strong> site non officiel, gratuit, sans publicité, réalisé à partir de données publiques ouvertes.</p>
    <p><a class="bouton" href="#/demarche">Lire la démarche</a></p>
  </div>
  <ul class="garanties">
    <li><strong>Rien ne quitte ton navigateur</strong>Pas de compte, pas de cookie, pas de mesure d’audience.</li>
    <li><strong id="nb-sources">Des sources publiques</strong>Vérifiées et reliées entre elles. Chaque montant renvoie au document public d’où il vient.</li>
    <li><strong>Gratuit et ouvert</strong>Le code est public, chacun peut le vérifier. Il ne remplace pas impots.gouv.fr ni ta fiche de paie.</li>
  </ul>
</section>
<p class="source">data.economie.gouv.fr, Insee, Eurostat, DGFiP, Urssaf (modele-social), Assemblée nationale, Cour des comptes, CNCCFP. <a href="#/methode">Méthode et sources</a></p>`

  // Le héros lance le calcul : salaire et commune restent en mémoire (jamais écrits dans une adresse), le résultat
  // s'ouvre directement. Sans salaire, on arrive sur le formulaire vide.
  const champ = cible.querySelector<HTMLInputElement>('#heros-net')!
  const dep = cible.querySelector<HTMLSelectElement>('#heros-dep')!
  const com = cible.querySelector<HTMLSelectElement>('#heros-com')!
  const msg = cible.querySelector<HTMLElement>('#heros-msg')!
  // Le moteur de calcul (Web Worker, environ 160 Ko compressés) se charge pendant que l'on écrit son salaire,
  // et non plus après le clic : le résultat arrive plus vite.
  const prechauffer = () => void import('../calcul/hors-fil').then((m) => m.prechauffer()).catch(() => {})
  champ.addEventListener('focus', prechauffer, { once: true })
  dep.addEventListener('change', async () => {
    cible.querySelector<HTMLElement>('#heros-com-bloc')!.hidden = !dep.value
    if (!dep.value) return
    com.innerHTML = '<option value="">Chargement…</option>'
    const d = await chargerSiPresent<{ communes: Record<string, [string, number | null, number | null]> }>(`communes/${dep.value}.json`)
    const liste = Object.entries(d?.communes ?? {}).sort((a, b) => a[1][0].localeCompare(b[1][0], 'fr'))
    com.innerHTML = '<option value="">Ne pas préciser</option>' + liste.map(([c, v]) => `<option value="${c}">${h(v[0])}</option>`).join('')
  })
  cible.querySelector('#heros-form')!.addEventListener('submit', (e) => {
    e.preventDefault()
    const brut = champ.value.trim().replace(/\s/g, '').replace(',', '.')
    if (brut && !(Number(brut) > 0)) {
      champ.setAttribute('aria-invalid', 'true')
      msg.textContent = 'Écris ton salaire en chiffres.'
      msg.hidden = false
      champ.focus()
      return
    }
    if (!brut) {
      session.amorce = null
      location.hash = '#/calcul'
      return
    }
    // Porte « Mon salaire » : calcul direct, puis l'écran résultat. Si le chemin simple ne suffit pas (saisie à
    // préciser, moteur indisponible), le formulaire prend le relais avec le salaire déjà saisi.
    const insee = com.value || undefined
    const bouton = cible.querySelector<HTMLButtonElement>('#heros-form button[type=submit]')!
    const statut = cible.querySelector<HTMLElement>('#heros-statut')!
    bouton.disabled = true
    statut.hidden = false
    statut.textContent = 'Calcul en cours sur ton appareil… Le résultat s’affiche dans un instant.'
    const relais = () => {
      session.amorce = { net: brut, insee }
      location.hash = '#/calcul'
    }
    import('./accueil-calcul')
      .then((m) => m.calculerDepuisAccueil(brut, insee))
      .then((issue) => {
        if (issue === 'resultat') location.hash = '#/calcul/resultat'
        else relais()
      })
      .catch((err) => {
        console.error(err)
        relais()
      })
      .finally(() => {
        bouton.disabled = false
      })
  })
  cible.querySelector('#voir-exemple')!.addEventListener('click', () => {
    session.amorce = { net: String(ex.profil.net_mensuel), insee: ex.profil.insee }
  })

  return {
    suite: Promise.all([
      plusDeSources().then((n) => {
        const p = cible.querySelector('#nb-sources')
        if (p && n) p.textContent = `Plus de ${n} sources publiques`
      }),
      remplirTuiles(cible),
    ]).then(() => undefined),
  }
}

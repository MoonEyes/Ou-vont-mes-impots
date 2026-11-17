// La démarche : pourquoi ce site, comment il est fait, ses règles et ce qu'il ne peut pas dire.
import { eurosNonPublies, plusDeSources } from '../composants/chiffres-site'
import { h } from '../util'

const DEPOT = 'https://github.com/MoonEyes/Ou-vont-mes-impots'

export async function rendre(cible: HTMLElement) {
  const [n, x] = await Promise.all([plusDeSources(), eurosNonPublies()])
  cible.innerHTML = `
<p class="surtitre">Une démarche citoyenne</p>
<h1>Pourquoi ce site, et comment il est fait</h1>
<p class="chapeau">Chaque année, tu verses une part de ton revenu en cotisations, CSG, impôts et TVA. Ce que deviennent ces montants est public, mais dispersé dans des milliers de documents. Ce site les rassemble pour répondre à une question : <span class="surligne">où va ton argent ?</span></p>

<h2>Une démarche citoyenne</h2>
<p>Ce site est porté par un citoyen, pas par une administration, un parti ou une entreprise. Il est gratuit, sans publicité et ne collecte aucune donnée. Chacun peut vérifier le travail, signaler une erreur ou y contribuer.</p>

<h2>En 4 étapes</h2>
<ol class="etapes">
  <li><span><strong>Récupérer.</strong> ${n ? `Plus de ${h(String(n))} sources publiques ouvertes` : 'Des sources publiques ouvertes'} : budget de l’État, Sécurité sociale, collectivités, Union européenne, Assemblée, Sénat, Cour des comptes. Mise à jour chaque semaine.</span></li>
  <li><span><strong>Vérifier.</strong> Chaque total est comparé au chiffre officiel publié. Les écarts restent affichés.</span></li>
  <li><span><strong>Relier.</strong> Chaque euro est relié à une politique, puis à l’organisme qui le reçoit, puis au bénéficiaire quand il est publié.</span></li>
  <li><span><strong>Montrer.</strong> Ce qui est tracé, ce qui est approché, et ce qui n’est pas publié.</span></li>
</ol>

<h2>Nos règles</h2>
<ul>
  <li>Aucun jugement sur les dépenses : des montants, des sources, des écarts.</li>
  <li>Rien sur toi : le calcul se fait dans ton téléphone.</li>
  <li>Aucune personne nommée, sauf les élus et candidats pour l’argent public de leurs campagnes.</li>
  <li>Aucun accès forcé : une source qui refuse l’accès est signalée, pas contournée.</li>
  <li>Code et données ouverts : tout est vérifiable et réutilisable (<a href="${DEPOT}" rel="noopener noreferrer">dépôt public sur GitHub</a>, code sous licence MIT, données sous leurs licences d’origine).</li>
</ul>

<div class="carte encadre">
  <h2>Ce qu’on ne peut pas dire</h2>
  <p>Un euro de TVA n’est pas fléché vers une dépense précise : on montre une répartition.${
    x ? ` Et sur 100 € dépensés par l’État, ${h(String(x.euros))} € n’ont pas de destinataire publié.` : ''
  }</p>
</div>
${x ? `<p class="source">site/data/tracabilite/resume.json (${h(x.millesime)})</p>` : ''}

<p class="liens-sortie">Une erreur ? <a href="${DEPOT}/issues" rel="noopener noreferrer">Signale-la sur GitHub</a> · <a href="#/methode">Méthode détaillée</a></p>
${n ? `<p class="source">nombre de sources : collecte/catalogue.json, compté à chaque construction du site</p>` : ''}`
}

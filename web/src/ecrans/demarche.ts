// La démarche : pourquoi ce site, comment il est fait, ses règles et ce qu'il ne peut pas dire.
import { eurosNonPublies, plusDeSources } from '../composants/chiffres-site'
import { picto } from '../composants/pictos'
import { CONTACT } from '../composants/signaler'
import { h } from '../util'

export async function rendre(cible: HTMLElement) {
  const [n, x] = await Promise.all([plusDeSources(), eurosNonPublies()])
  const regle = (p: string, texte: string) => `<li>${picto(p)}<span>${texte}</span></li>`
  cible.innerHTML = `
<div class="heros">
  <div>
    <h1>Pourquoi ce site, et comment il est fait</h1>
    <p class="chapeau">Chaque année, tu verses une part de ton revenu en cotisations, CSG, impôts et TVA. Ce que deviennent ces montants est public, mais dispersé dans des milliers de documents. Ce site les rassemble pour répondre à une question : <span class="surligne">où va ton argent ?</span></p>
  </div>
  <svg class="illustration" viewBox="0 0 420 280" aria-hidden="true" focusable="false">
    <g transform="rotate(-6 100 130)"><rect class="i-papier" x="20" y="24" width="150" height="206" rx="14"/><path class="i-trait" d="M48 78h88M48 108h88M48 138h60"/></g>
    <path class="i-points" d="M186 122c26 0 22-44 62-46"/>
    <rect class="i-forme fam-secu" x="262" y="20" width="46" height="118" rx="12"/><rect class="i-forme fam-etat" x="316" y="38" width="34" height="118" rx="11"/><rect class="i-forme fam-collectivites" x="358" y="26" width="22" height="118" rx="9"/><rect class="i-forme i-hach" x="386" y="42" width="24" height="118" rx="9"/>
    <circle class="i-forme fam-prestations" cx="298" cy="216" r="34"/><path class="i-manche" d="M324 242l26 26"/>
  </svg>
</div>

<h2>Une démarche citoyenne</h2>
<p>Ce site est porté par un citoyen, pas par une administration, un parti ou une entreprise. Il est gratuit, sans publicité et ne collecte aucune donnée. Chacun peut vérifier le travail, signaler une erreur ou y contribuer. Le site ne soutient aucun parti, aucun candidat ni aucune position sur le niveau des impôts ou des dépenses.</p>

<section class="bande" aria-labelledby="titre-etapes">
<h2 id="titre-etapes">En 4 étapes</h2>
<ol class="etapes par-4">
  <li><span><strong>Récupérer.</strong> ${n ? `Plus de ${h(String(n))} sources publiques ouvertes` : 'Des sources publiques ouvertes'} : budget de l’État, Sécurité sociale, collectivités, Union européenne, Assemblée, Sénat, Cour des comptes. Mise à jour chaque semaine.</span></li>
  <li><span><strong>Vérifier.</strong> Chaque total est comparé au chiffre officiel publié. Les écarts restent affichés.</span></li>
  <li><span><strong>Relier.</strong> Chaque euro est relié à une politique, puis à l’organisme qui le reçoit, puis au bénéficiaire quand il est publié.</span></li>
  <li><span><strong>Montrer.</strong> Ce qui est tracé, ce qui est approché, et ce qui n’est pas publié.</span></li>
</ol>
</section>

<div class="colonnes c-6-6">
  <div>
    <h2>Nos règles</h2>
    <ul class="regles">
      ${regle('justice', 'Aucun jugement sur les dépenses : des montants, des sources, des écarts.')}
      ${regle('methode', 'Chaque sujet est présenté avec les mêmes formats : montant, source, part tracée, écarts.')}
      ${regle('vote', 'Partis et candidats : même tableau pour tous, dans un ordre neutre affiché sous chaque liste.')}
      ${regle('defense', 'Rien sur toi : le calcul se fait dans ton téléphone.')}
      ${regle('menages', 'Aucune personne nommée, sauf les élus et candidats pour l’argent public de leurs campagnes.')}
      ${regle('controle', 'Aucun accès forcé : une source qui refuse l’accès est signalée, pas contournée.')}
      ${regle('ecole', `Code et données ouverts : tout est vérifiable et réutilisable (code source ouvert sous licence MIT, données sous leurs licences d’origine).`)}
    </ul>
  </div>
  <div>
    <h2>Ce qu’on ne peut pas dire</h2>
    <ul class="limites">
      <li><span class="motif motif-approche" aria-hidden="true"></span><span>Un euro de TVA n’est pas fléché vers une dépense précise : on montre une répartition.</span></li>
      ${
        x
          ? `<li><span class="motif motif-nonpub" aria-hidden="true"></span><span>Et sur 100 € dépensés par l’État, ${h(String(x.euros))} € n’ont pas de destinataire publié en données ouvertes : cela décrit l’état de la publication, pas l’usage de l’argent.</span></li>`
          : ''
      }
    </ul>
    ${x ? `<p class="source">site/data/tracabilite/resume.json (${h(x.millesime)})</p>` : ''}
    <p class="liens-sortie">Une erreur ? Écris à ${h(CONTACT)}</p>
    <p class="actions"><a class="bouton" href="#/methode">Méthode détaillée</a></p>
  </div>
</div>
${n ? `<p class="source">nombre de sources : collecte/catalogue.json, compté à chaque construction du site</p>` : ''}`
}

// Mentions légales (LCEN) et confidentialité.
const DEPOT = 'https://github.com/MoonEyes/Ou-vont-mes-impots'

export function rendre(cible: HTMLElement) {
  cible.innerHTML = `
<h1>Mentions légales et confidentialité</h1>
<p><strong>Site citoyen indépendant, sans lien avec l’administration</strong> : ce n’est pas un site officiel de l’État.</p>
<h2>Éditeur</h2>
<p>« Où vont mes impôts » est un projet citoyen non commercial, publié à titre non professionnel. Conformément à l’article 6, III, 2 de la loi n° 2004-575 du 21 juin 2004 pour la confiance dans l’économie numérique (LCEN), l’éditeur non professionnel a communiqué ses éléments d’identification à l’hébergeur. Contact : <a href="${DEPOT}/issues" rel="noopener noreferrer">ouvrir un ticket sur le dépôt public</a>.</p>
<h2>Hébergeur</h2>
<p>GitHub, Inc. (GitHub Pages), 88 Colin P. Kelly Jr. Street, San Francisco, CA 94107, États-Unis.</p>
<h2>Confidentialité</h2>
<ul>
<li><strong>Aucune donnée saisie ne quitte ton appareil.</strong> Le calcul est fait par ton navigateur ; le site ne fait aucun appel réseau autre que le chargement de ses propres fichiers (pages, polices, données publiques).</li>
<li><strong>Aucun cookie</strong>, aucune mesure d’audience, aucun traceur, aucune police ou bibliothèque chargée depuis un autre site.</li>
<li><strong>Rien n’est enregistré</strong>, même sur ton appareil : ta saisie reste en mémoire le temps de la visite et disparaît quand tu fermes l’onglet.</li>
<li>Comme tout hébergeur, GitHub peut conserver des journaux techniques de connexion (adresse IP) : voir la déclaration de confidentialité de GitHub.</li>
<li>Une politique de sécurité du contenu (CSP) interdit techniquement au site de contacter un autre domaine.</li>
</ul>
<h2>Propriété intellectuelle</h2>
<p>Code sous licence MIT. Données publiques sous Licence Ouverte 2.0 (Etalab) et conditions de réutilisation d’Eurostat. Polices Fraunces, Atkinson Hyperlegible Next et Recursive sous SIL Open Font License 1.1.</p>
<h2>Responsabilité</h2>
<p>Les chiffres sont des estimations construites à partir de données publiques, avec leurs limites (voir <a href="#/methode">méthode</a>). Ils ne remplacent ni ta fiche de paie, ni ton avis d’impôt.</p>`
}

// Accueil (page de démarrage) : une seule action principale, comment ça marche, garanties, limites.
export function rendre(cible: HTMLElement) {
  const bouton = `<p class="actions"><a class="bouton bouton-principal bouton-grand" href="#/calcul">Calculer à partir de mon salaire</a></p>`
  cible.innerHTML = `
<div class="accueil-tete">
  <h1>Où va l’argent que tu paies ?</h1>
  <p class="chapeau">Indique ton salaire. Tu vois ce que tu verses chaque année, à qui, et à quoi cet argent sert.</p>
  ${bouton}
  <p class="aide">Environ 2 minutes. Aucun compte à créer.</p>
  <p><a href="#/explorer">Explorer sans saisir mon salaire</a></p>
</div>

<h2>Comment ça marche</h2>
<ol class="etapes">
  <li><span>Tu indiques ton salaire net avant impôt et ta situation de famille.</span></li>
  <li><span>Ton téléphone calcule ce que tu paies : cotisations, CSG, impôt sur le revenu, TVA estimée, impôts locaux.</span></li>
  <li><span>Tu suis chaque euro : retraites, santé, école, dette, ta commune, et les organismes qui le reçoivent.</span></li>
</ol>

<div class="garantie">
  <p><strong><span class="surligne">Rien ne quitte ton téléphone.</span></strong> Le calcul se fait dans ton navigateur : pas de compte, pas de cookie, pas de mesure d’audience.</p>
  <p>Chaque montant renvoie au document public d’où il vient, jusqu’à la ligne du budget voté.</p>
</div>

<h2>Ce que le site fait, et ce qu’il ne fait pas</h2>
<div class="grille-2">
  <div>
    <h3>Il fait</h3>
    <ul>
      <li>Estimer ce que tu verses à partir de ton salaire, avec les règles officielles de calcul.</li>
      <li>Montrer à qui va chaque euro, avec la source et l’année de chaque chiffre.</li>
      <li>Dire quand une donnée manque ou n’est qu’une estimation.</li>
    </ul>
  </div>
  <div>
    <h3>Il ne fait pas</h3>
    <ul>
      <li>Il ne remplace pas impots.gouv.fr ni ta fiche de paie.</li>
      <li>Il ne juge aucune dépense.</li>
      <li>Il ne garde aucune donnée.</li>
    </ul>
  </div>
</div>
<p><strong>Site non officiel, réalisé à partir de données publiques ouvertes.</strong></p>
<p class="source">data.economie.gouv.fr, Insee, Eurostat, DGFiP, Urssaf (modele-social), Assemblée nationale, Cour des comptes, CNCCFP. <a href="#/methode">Méthode et sources</a></p>
${bouton}`
}

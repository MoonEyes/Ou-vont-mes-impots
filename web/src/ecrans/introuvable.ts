// Page introuvable : le billet 4-0-4, et deux sorties.
export function rendre(cible: HTMLElement) {
  cible.innerHTML = `
<div class="introuvable">
  <div class="billet"><svg viewBox="0 0 540 214" aria-hidden="true" focusable="false">
    <defs><pattern id="b404-h" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect class="b-hach-fond" width="14" height="14"/><rect class="b-hach-trait" width="5" height="14"/></pattern></defs>
    <g class="b-talon"><rect class="b-forme b-papier" x="2" y="10" width="92" height="198" rx="18"/><circle class="b-pointille" cx="48" cy="58" r="20"/><text x="48" y="67" font-size="22" text-anchor="middle">€</text><text x="48" y="146" font-size="40" text-anchor="middle">?</text><text class="b-petit" x="48" y="178" font-size="18" text-anchor="middle">euros</text></g>
    <rect class="b-forme fam-secu" x="100" y="2" width="142" height="198" rx="18"/><text x="171" y="132" font-size="76" text-anchor="middle">4</text>
    <rect class="b-forme" fill="url(#b404-h)" x="248" y="16" width="142" height="198" rx="18"/><rect class="b-etiquette" x="278" y="62" width="82" height="106" rx="16"/><text x="319" y="148" font-size="76" text-anchor="middle">0</text>
    <rect class="b-forme fam-ue" x="396" y="6" width="142" height="198" rx="18"/><text x="467" y="136" font-size="76" text-anchor="middle">4</text>
  </svg></div>
  <div>
    <h1>Ce billet-là, on ne le trouve pas</h1>
    <p class="chapeau">La page a changé d’adresse ou n’existe pas. Tes euros, eux, sont toujours suivis.</p>
    <p class="actions"><a class="bouton bouton-principal" href="#/">Revenir à l’accueil</a><a class="bouton" href="#/explorer">Explorer les thèmes</a></p>
  </div>
</div>`
}

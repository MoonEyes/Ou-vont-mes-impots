// Mentions légales (LCEN), confidentialité des visiteurs et information des personnes nommées
// (élus, candidats : article 14 du RGPD). Aucune identité d'éditeur n'est inventée : les champs
// Contact privé de l'éditeur : alias dédié au site (aucune identité publiée).
import { CONTACT } from '../composants/signaler'
import { chargerSiPresent } from '../donnees'
import { h } from '../util'

/** « 2026-11-16T12:30:17Z » ou « 2026-11-16 » vers « 16/11/2026 » ; null si illisible. */
function dateFr(x: unknown): string | null {
  const m = typeof x === 'string' ? /^(\d{4})-(\d{2})-(\d{2})/.exec(x) : null
  return m ? `${m[3]}/${m[2]}/${m[1]}` : null
}

export async function rendre(cible: HTMLElement) {
  const [vp, dec] = await Promise.all([
    chargerSiPresent<{ millesime?: string; collecte_le?: string }>('vie_politique/annees.json'),
    chargerSiPresent<{ millesime?: string; genere_le?: string; regle_personnes?: string }>('decisions/index.json'),
  ])
  const dateVp = dateFr(vp?.collecte_le)
  const dateDec = dateFr(dec?.genere_le)
  cible.innerHTML = `
<h1>Mentions légales et confidentialité</h1>
<p><strong>Site citoyen indépendant, sans lien avec l’administration</strong> : ce n’est pas un site officiel de l’État.</p>
<h2>Éditeur</h2>
<p>« Le billet découpé » est un projet citoyen non commercial, publié à titre non professionnel.</p>
<p>Le billet découpé est sans lien avec le site ouvontmesimpots.fr.</p>
<p>Identité de l’éditeur : l’éditeur, une personne physique agissant à titre non professionnel, a communiqué ses éléments d’identification (nom, prénom, domicile, numéro de téléphone) à l’hébergeur, comme le permet l’article 1-1, II, de la loi n° 2004-575 du 21 juin 2004 pour la confiance dans l’économie numérique (LCEN) ; seules les coordonnées de l’hébergeur sont donc publiées.</p>
<p>Contact : ${h(CONTACT)} (seul moyen de contact du site, y compris pour signaler une erreur).</p>
<h2>Hébergeur</h2>
<p>Cloudflare, Inc. (Cloudflare Workers), 101 Townsend Street, San Francisco, CA 94107, États-Unis.</p>
<p>Copie de secours : GitHub, Inc. (GitHub Pages), 88 Colin P. Kelly Jr. Street, San Francisco, CA 94107, États-Unis.</p>
<h2>Confidentialité des visiteurs</h2>
<ul>
<li><strong>Aucune donnée saisie ne quitte ton appareil.</strong> Le calcul est fait par ton navigateur ; le site ne fait aucun appel réseau autre que le chargement de ses propres fichiers (pages, polices, données publiques).</li>
<li><strong>Aucun cookie</strong>, aucune mesure d’audience, aucun traceur, aucune police ou bibliothèque chargée depuis un autre site.</li>
<li><strong>Rien n’est enregistré</strong>, même sur ton appareil : ta saisie reste en mémoire le temps de la visite et disparaît quand tu fermes l’onglet.</li>
<li>Comme tout hébergeur, Cloudflare (et GitHub pour la copie de secours) peut conserver des journaux techniques de connexion (adresse IP) : voir leurs politiques de confidentialité.</li>
<li>Une politique de sécurité du contenu (CSP) interdit techniquement au site de contacter un autre domaine.</li>
</ul>
<h2 id="personnes-nommees">Données personnelles des élus et candidats</h2>
<p>Le site republie des données personnelles déjà rendues publiques par l’administration. Il n’en collecte aucune autre.</p>
<dl class="fiche-rgpd">
  <dt>Personnes concernées et données</dt>
  <dd>Candidats aux élections : nom, nuance politique, circonscription, montants du compte de campagne et décision de la Commission nationale des comptes de campagne et des financements politiques (CNCCFP).</dd>
  <dd>Parlementaires et membres du Gouvernement : nom, groupe politique, amendements déposés et votes publiés.${dec?.regle_personnes ? ` ${h(dec.regle_personnes)}` : ''}</dd>
  <dt>Finalité</dt>
  <dd>Information du public sur l’usage de l’argent public et sur les décisions budgétaires.</dd>
  <dt>Base légale</dt>
  <dd>Intérêt légitime (article 6, paragraphe 1, f du RGPD) : information du public, à partir de données dont la publication est prévue par la loi (Journal officiel, CNCCFP, données ouvertes du Parlement). La réutilisation de ces informations publiques reste soumise au RGPD (article L. 322-2 du code des relations entre le public et l’administration).</dd>
  <dt>Sources et date</dt>
  <dd>Comptes de campagne : CNCCFP (data.gouv.fr) et décisions publiées au Journal officiel${vp?.millesime ? ` ; ${h(vp.millesime)}` : ''}${dateVp ? ` ; collecte du ${h(dateVp)}` : ''}.</dd>
  <dd>Amendements et votes : données ouvertes de l’Assemblée nationale et du Sénat${dec?.millesime ? ` ; ${h(dec.millesime)}` : ''}${dateDec ? ` ; données produites le ${h(dateDec)}` : ''}.</dd>
  <dd>Détail jeu par jeu : <a href="#/methode">méthode et sources</a>.</dd>
  <dt>Durée de conservation</dt>
  <dd>Les données sont affichées tant que la source officielle les publie. Une donnée retirée ou corrigée à la source est retirée ou corrigée à la mise à jour suivante du site. Le site ne collecte ni ne conserve aucune autre donnée personnelle.</dd>
  <dt>Destinataires et hébergement</dt>
  <dd>Les données sont publiques et consultables par tout visiteur. Hébergement : Cloudflare (États-Unis), copie de secours sur GitHub Pages (États-Unis).</dd>
  <dt>Tes droits</dt>
  <dd>Si tu es une personne nommée sur ce site, tu peux demander l’accès aux données te concernant, leur rectification ou leur effacement, la limitation de leur affichage, et t’opposer à leur publication pour des raisons tenant à ta situation particulière (article 21 du RGPD).</dd>
  <dd>Pour une erreur de recopie, la correction est faite d’après la source officielle. Si la donnée est erronée à la source, la rectification relève de l’organisme qui l’a publiée (CNCCFP, Assemblée nationale, Sénat).</dd>
  <dd>Demande à adresser à : ${h(CONTACT)}</dd>
  <dd>Réponse dans un délai d’un mois. Tu peux aussi adresser une réclamation à la Commission nationale de l’informatique et des libertés (CNIL) : <a href="https://www.cnil.fr/fr/plaintes" rel="noopener noreferrer">cnil.fr/fr/plaintes</a>.</dd>
</dl>
<h2>Propriété intellectuelle</h2>
<p>Code source ouvert sous licence MIT. Données publiques sous Licence Ouverte 2.0 (Etalab) et conditions de réutilisation d’Eurostat. Polices Bricolage Grotesque et Figtree sous SIL Open Font License 1.1.</p>
<h2>Responsabilité</h2>
<p>Les chiffres sont des estimations construites à partir de données publiques, avec leurs limites (voir <a href="#/methode">méthode</a>). Ils ne remplacent ni ta fiche de paie, ni ton avis d’impôt.</p>`
}

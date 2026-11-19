// Écran 1 : saisie du salaire net avant impôt (chemin simple, par défaut) et, dans « Préciser ma situation », des
// autres profils calculés par calculerProfil : fonction publique, apprentissage, retraite, micro-entreprise.
// Contrôle léger sur le fil principal (perimetre-etendu.ts), calcul dans un Web Worker : rien n'est envoyé.
import { TERRITOIRES_DOM, saisieInvalide, territoireDeCommune, verifierProfilEtendu } from '../calcul/perimetre-etendu'
import { ANNEE_NAISSANCE_65_ANS } from '../calcul/profils-ui'
import type { ActiviteMicro, PersonneEtendue, ProfilEtendu, ResultatErreurEtendu, StatutActivite, TauxCsgRetraite, TerritoireOutreMer, Versant } from '../calcul/types'
import { enregistrerDestinataires } from '../calcul/destinataires'
import { ALSACE_MOSELLE, TOUS_DEPARTEMENTS, departementDe } from '../departements'
import { chargerSiPresent } from '../donnees'
import { session } from '../etat'
import { cartesRayons } from '../composants/hub'
import { annoncer, h } from '../util'

/** Situations proposées d'abord, avant le montant ; les autres sont regroupées ensuite. */
const STATUTS: [StatutActivite, string][] = [
  ['salarie_prive', 'Salarié·e du secteur privé'],
  ['fonctionnaire', 'Fonctionnaire titulaire'],
  ['retraite', 'Retraité·e'],
  ['independant', 'Micro-entrepreneur·se'],
]
const AUTRES_STATUTS: [StatutActivite, string][] = [
  ['contractuel_public', 'Contractuel·le de la fonction publique'],
  ['apprenti', 'Apprenti·e'],
  ['sans_activite', 'Sans activité professionnelle'],
  ['demandeur_emploi', 'Demandeur·se d’emploi indemnisé·e (pas encore couvert)'],
  ['etudiant', 'Étudiant·e'],
]

/** Territoires proposés avec la case « J'habite en outre-mer » (les cas non calculés renvoient un message). */
const TERRITOIRES: [TerritoireOutreMer, string][] = [
  ['guadeloupe', 'Guadeloupe'],
  ['martinique', 'Martinique'],
  ['guyane', 'Guyane'],
  ['reunion', 'La Réunion'],
  ['mayotte', 'Mayotte (pas encore couvert)'],
  ['autre_com', 'Autre collectivité d’outre-mer (pas couvert)'],
]

/** Libellé du montant principal selon la situation (salaire, traitement et primes). */
const LIBELLE_NET: Partial<Record<StatutActivite, string>> = {
  fonctionnaire: 'Salaire net avant impôt, par mois, primes comprises (en euros)',
}
const LIBELLE_NET_DEFAUT = 'Salaire net avant impôt, par mois (en euros)'

/** Situations dont le calcul part du salaire net avant impôt (le champ du chemin simple). */
const AVEC_SALAIRE = new Set<StatutActivite>(['salarie_prive', 'fonctionnaire', 'contractuel_public', 'apprenti'])
/** Situations dont les précisions facultatives (cadre, temps partiel, frontalier) sont dans « Préciser ma situation ». */
const AVEC_PRECISIONS = new Set<StatutActivite>(['salarie_prive', 'contractuel_public'])

/** Précision affichée sous la situation choisie : ce qui n'est pas couvert, et vers quel choix aller. */
const NOTES_STATUT: Partial<Record<StatutActivite, string>> = {
  independant: 'Seul le régime de la micro-entreprise est calculé : les cotisations des indépendants au régime réel n’ont pas pu être vérifiées contre une autre source.',
  demandeur_emploi: 'Les prélèvements sur les allocations chômage ne sont pas encore couverts.',
  etudiant: 'Avec un emploi salarié ou un contrat d’apprentissage, choisis « Salarié·e du secteur privé » ou « Apprenti·e ». Sans revenu, dans un couple : « Sans activité professionnelle ».',
}

const AIDE_SALAIRE =
  'Prends sur ta fiche de paie la ligne <strong>Net à payer avant impôt sur le revenu</strong>. Si tu touches des primes ou un 13e mois, fais la moyenne sur 12 mois : additionne le net avant impôt de tes 12 dernières fiches et divise par 12. N’utilise ni le <em>net imposable</em>, ni le <em>montant net social</em>, ni le <em>net payé</em> (après prélèvement à la source).'

const radios = (nom: string, options: [string, string][], courant?: string) =>
  options.map(([v, l]) => `<label><input type="radio" name="${nom}" value="${v}"${v === courant ? ' checked' : ''} /> ${h(l)}</label>`).join('')

/** Groupe de boutons radio : fieldset et legend ; aide et message d'erreur reliés au groupe (aria-describedby). */
function groupe(id: string, legende: string, contenu: string, aide = ''): string {
  return `<fieldset class="choix saisie-groupe" id="${id}" aria-describedby="${aide ? `${id}-aide ` : ''}${id}-msg">
      <legend>${h(legende)}</legend>
      ${aide ? `<p class="aide" id="${id}-aide">${h(aide)}</p>` : ''}
      <p class="message-champ" id="${id}-msg" hidden></p>
      ${contenu}
    </fieldset>`
}

/** Champ de montant : libellé, aide et message d'erreur reliés au champ (aria-describedby). */
function champ(id: string, libelle: string, valeur: number | undefined, aide = ''): string {
  return `<label for="${id}">${h(libelle)}</label>
      ${aide ? `<p class="aide" id="${id}-aide">${h(aide)}</p>` : ''}
      <input id="${id}" type="text" inputmode="decimal" spellcheck="false" autocomplete="off" aria-describedby="${aide ? `${id}-aide ` : ''}${id}-msg" value="${valeur ?? ''}" />
      <p class="message-champ" id="${id}-msg" hidden></p>`
}

function blocPersonne(n: 1 | 2, p?: PersonneEtendue): string {
  const id = (x: string) => `p${n}-${x}`
  const statut = p?.statut_activite ?? 'salarie_prive'
  const tp = p?.temps_travail?.type === 'temps_partiel' ? p.temps_travail.quotite : null
  const ind = p?.independant
  const c = p?.csg_pension
  const csg = c ? ('taux' in c ? c.taux : 'rfr') : undefined
  const rfr = c && 'revenu_fiscal_reference' in c ? c : undefined
  const age = p?.annee_naissance === undefined ? undefined : p.annee_naissance <= ANNEE_NAISSANCE_65_ANS ? 'plus65' : 'moins65'
  const contrat = p?.apprentissage ? (p.apprentissage.contrat_avant_mars_2025 ? 'avant' : 'depuis') : undefined
  // Précisions ouvertes au retour sur la saisie si elles ont servi (cadre, temps partiel, frontalier).
  const ouvert = !!p?.cadre || tp !== null || !!p?.frontalier
  const options = (l: [StatutActivite, string][]) => l.map(([v, lib]) => `<option value="${v}"${v === statut ? ' selected' : ''}>${h(lib)}</option>`).join('')
  return `<fieldset id="${id('bloc')}" ${n === 2 ? 'hidden' : ''}>
  <legend>${n === 1 ? 'Toi' : 'Ton ou ta conjoint·e'}</legend>
  <label for="${id('statut')}">${n === 1 ? 'Ta situation' : 'Sa situation'}</label>
  <select id="${id('statut')}" name="${id('statut')}" aria-describedby="${id('note-statut')}">
    ${options(STATUTS)}
    <optgroup label="Autres situations">${options(AUTRES_STATUTS)}</optgroup>
  </select>
  <p class="aide" id="${id('note-statut')}"${NOTES_STATUT[statut] ? '' : ' hidden'}>${h(NOTES_STATUT[statut] ?? '')}</p>
  <div id="${id('salaire')}">
    <label for="${id('net')}" id="${id('net-libelle')}">${h(LIBELLE_NET[statut] ?? LIBELLE_NET_DEFAUT)}</label>
    <input id="${id('net')}" name="${id('net')}" type="text" inputmode="decimal" spellcheck="false" autocomplete="off" aria-describedby="${id('aide')} ${id('msg')}" value="${p?.salaire_net_avant_impot_mensuel ?? ''}" />
    <p class="message-champ" id="${id('msg')}" hidden></p>
    <details><summary>Où trouver ce montant ?</summary><p class="aide" id="${id('aide')}">${AIDE_SALAIRE}</p></details>
  </div>
  <div id="${id('opt-fonctionnaire')}">
    ${groupe(id('versant'), 'Versant de la fonction publique', radios(id('versant'), [['etat', 'Fonction publique de l’État'], ['territoriale', 'Fonction publique territoriale'], ['hospitaliere', 'Fonction publique hospitalière']], p?.versant))}
    ${champ(id('primes'), 'Primes et indemnités, total brut par mois (en euros)', p?.primes_mensuelles, 'Additionne les primes et indemnités de la fiche de paie : indemnité de résidence, supplément familial de traitement, primes ; outre-mer, la majoration de traitement. Écris 0 s’il n’y en a pas.')}
    ${champ(id('traitement'), 'Traitement indiciaire brut, par mois (facultatif)', p?.traitement_indiciaire_brut_mensuel, 'Ligne « traitement brut » de la fiche de paie. S’il est indiqué, le calcul part de ce traitement et des primes, et le salaire net est recalculé.')}
  </div>
  <div id="${id('opt-apprenti')}">
    ${groupe(id('contrat'), 'Signature du contrat d’apprentissage', radios(id('contrat'), [['avant', 'Avant le 1er mars 2025'], ['depuis', 'Le 1er mars 2025 ou après']], contrat), 'Pour un contrat signé depuis le 1er mars 2025, la part du salaire exonérée de cotisations est plus basse et la CSG est due.')}
  </div>
  <div id="${id('opt-retraite')}">
    ${champ(id('pension-base'), 'Pension de retraite de base, par mois (en euros)', p?.pension_base_mensuelle, 'Régime général, fonction publique, régime agricole ou autre régime de base.')}
    ${champ(id('pension-compl'), 'Pension de retraite complémentaire, par mois (en euros)', p?.pension_complementaire_mensuelle || undefined, 'Agirc-Arrco, Ircantec, retraite additionnelle de la fonction publique. Laisse vide s’il n’y en a pas.')}
    ${groupe(id('pension-saisie'), 'Ces montants sont', radios(id('pension-saisie'), [['nette_avant_impot', 'Nets avant impôt (versés avant le prélèvement à la source)'], ['brute', 'Bruts (avant CSG et cotisations)']], p?.pension_saisie ?? 'nette_avant_impot'))}
    ${groupe(id('csg'), `Taux de CSG sur ${n === 1 ? 'ta' : 'sa'} pension`, radios(id('csg'), [['normal', 'Taux normal (8,3 %)'], ['median', 'Taux médian (6,6 %)'], ['reduit', 'Taux réduit (3,8 %)'], ['exonere', 'Exonération de CSG'], ['rfr', 'Je ne sais pas : le déduire de l’avis d’impôt (métropole seulement)']], csg), 'Il figure sur le relevé de pension et dépend du revenu fiscal de référence d’il y a deux ans.')}
    <div id="${id('rfr-bloc')}"${csg === 'rfr' ? '' : ' hidden'}>
      ${champ(id('rfr'), 'Revenu fiscal de référence de l’avis d’impôt 2024 (revenus 2023)', rfr?.revenu_fiscal_reference)}
      ${champ(id('parts'), 'Nombre de parts de cet avis', rfr?.parts, 'Par exemple 1 pour une personne seule, 2 pour un couple marié ou pacsé.')}
    </div>
    ${groupe(id('age'), 'Âge au 31 décembre 2025', radios(id('age'), [['plus65', '65 ans ou plus (né·e en 1960 ou avant)'], ['moins65', 'Moins de 65 ans']], age), 'Sert à l’abattement d’impôt des personnes de 65 ans ou plus.')}
  </div>
  <div id="${id('opt-independant')}">
    ${champ(id('ca'), 'Chiffre d’affaires encaissé en 2025, hors taxes (en euros, sur l’année)', ind?.chiffre_affaires_annuel)}
    ${groupe(id('activite'), 'Nature de l’activité', radios(id('activite'), [['vente', 'Vente de marchandises'], ['service_bic', 'Prestations de services commerciales ou artisanales'], ['service_bnc', 'Activité libérale, affiliée au régime général']], ind?.activite))}
    <div id="${id('artisan-bloc')}"><label class="case"><input type="checkbox" id="${id('artisan')}"${ind?.artisan ? ' checked' : ''} /> Activité artisanale (inscrite au répertoire des métiers)</label></div>
    ${groupe(id('vl'), 'Versement libératoire de l’impôt sur le revenu', radios(id('vl'), [['oui', 'Oui, l’impôt est versé avec les cotisations'], ['non', 'Non']], ind?.versement_liberatoire === undefined ? undefined : ind.versement_liberatoire ? 'oui' : 'non'))}
  </div>
  <details id="${id('preciser')}"${ouvert ? ' open' : ''}>
    <summary>Préciser ${n === 1 ? 'ma' : 'sa'} situation</summary>
    <p class="aide">Par défaut, le calcul retient un emploi à temps plein, non cadre. Temps partiel, statut cadre ou travail hors de France : précise-le ici.</p>
    <div id="${id('opt-salarie')}">
      <label class="case"><input type="checkbox" id="${id('cadre')}"${p?.cadre ? ' checked' : ''} /> Statut cadre</label>
      <label class="case"><input type="checkbox" id="${id('frontalier')}"${p?.frontalier ? ' checked' : ''} /> Travail hors de France (frontalier)</label>
    </div>
    <div id="${id('opt-partiel')}">
      <label class="case"><input type="checkbox" id="${id('partiel')}"${tp !== null ? ' checked' : ''} /> Temps partiel</label>
      <div id="${id('quotite-bloc')}" ${tp === null ? 'hidden' : ''}>
        <label for="${id('quotite')}">Quotité de travail (en % d’un temps plein)</label>
        <input id="${id('quotite')}" type="text" inputmode="decimal" spellcheck="false" autocomplete="off" value="${tp !== null ? Math.round(tp * 100) : 80}" aria-describedby="${id('msg-q')}" />
        <p class="message-champ" id="${id('msg-q')}" hidden></p>
      </div>
    </div>
  </details>
</fieldset>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams = new URLSearchParams()) {
  const pr = session.profil
  const sit = pr?.foyer.situation ?? 'celibataire'
  const nbEnfants = pr?.foyer.enfants.length ?? 0
  const nbAlternee = pr?.foyer.enfants.filter((e) => e.garde_alternee).length ?? 0
  const logement = pr?.logement?.statut ?? 'locataire'
  const outremer = pr?.residence.zone === 'dom'
  const territoire = (pr as ProfilEtendu | null)?.residence.territoire ?? ''
  const zone = outremer ? 'metropole' : pr?.residence.zone === 'metropole' && pr.residence.alsace_moselle ? 'alsace_moselle' : (pr?.residence.zone ?? 'metropole')
  const choix = (nom: string, valeur: string, courant: string, texte: string) =>
    `<label><input type="radio" name="${nom}" value="${valeur}"${valeur === courant ? ' checked' : ''} /> ${texte}</label>`

  // Arrivée depuis l'accueil avec un salaire : le calcul part tout de suite ; l'état est dit en haut de l'écran
  // (et non sous le formulaire, hors de la vue sur un téléphone).
  const depuisAccueil = !!session.amorce
  cible.innerHTML = `
<h1>Ton salaire</h1>
${depuisAccueil ? '<p class="calcul-en-cours" id="statut-haut" role="status">Calcul en cours sur ton appareil… Le résultat s’affiche dans un instant. Tu pourras ensuite préciser ta situation ici.</p>' : ''}
${params.get('retour') ? '<p class="avertissement" role="status">Indique d’abord ton salaire : le résultat se calcule à partir de ta saisie, et rien n’est gardé d’une visite à l’autre.</p>' : ''}
<p class="chapeau">Indique ton salaire : le site calcule ce que tu verses chaque année, à qui va l’argent, puis montre où va l’argent public. Le calcul se fait <strong>sur ton appareil</strong> : rien de ce que tu saisis n’est envoyé ni enregistré.</p>
<p class="aide">Revenus 2025, en France métropolitaine (Alsace-Moselle comprise), en Guadeloupe, en Martinique, en Guyane et à La Réunion. Choisis d’abord ta situation (salarié·e du secteur privé, fonctionnaire, retraité·e, micro-entrepreneur·se), puis le montant demandé : salaire net avant impôt, pension ou chiffre d’affaires. Pas encore couverts : Mayotte et les collectivités d’outre-mer, étranger, travail frontalier, allocations chômage, indépendants au régime réel.</p>
<form id="formulaire" novalidate>
  <fieldset class="choix">
    <legend>Ton foyer</legend>
    ${choix('situation', 'celibataire', sit, 'Seul·e, sans enfant à charge')}
    ${choix('situation', 'parent_isole', sit, 'Seul·e avec enfant(s) à charge')}
    ${choix('situation', 'couple_marie_pacse', sit, 'En couple, marié·es ou pacsé·es')}
    ${choix('situation', 'couple_union_libre', sit, 'En couple, sans être marié·es ni pacsé·es')}
    <div id="enfants-bloc">
      <label for="enfants">Nombre d’enfants à charge</label>
      <input id="enfants" type="number" inputmode="numeric" min="0" max="10" step="1" value="${nbEnfants}" />
      <label for="alternee">Dont en garde alternée</label>
      <input id="alternee" type="number" inputmode="numeric" min="0" max="10" step="1" value="${nbAlternee}" aria-describedby="msg-alternee" />
      <p class="message-champ" id="msg-alternee" hidden></p>
    </div>
  </fieldset>
  <fieldset class="choix" id="bloc-outremer">
    <legend>Outre-mer</legend>
    <label class="case"><input type="checkbox" id="outremer"${outremer ? ' checked' : ''} /> J’habite en outre-mer</label>
    <div id="territoire-bloc"${outremer ? '' : ' hidden'}>
      <label for="territoire">Territoire</label>
      <select id="territoire" aria-describedby="territoire-aide territoire-msg">
        <option value="">Choisir</option>
        ${TERRITOIRES.map(([v, l]) => `<option value="${v}"${v === territoire ? ' selected' : ''}>${h(l)}</option>`).join('')}
      </select>
      <p class="aide" id="territoire-aide">Impôt sur le revenu réduit de 30 % (Guadeloupe, Martinique, La Réunion) ou de 40 % (Guyane), dans une limite. Les taxes sur la consommation (TVA à taux propres, octroi de mer) ne sont pas chiffrées.</p>
      <p class="message-champ" id="territoire-msg" hidden></p>
    </div>
  </fieldset>
  ${blocPersonne(1, pr?.personnes[0])}
  ${blocPersonne(2, pr?.personnes[1])}
  <fieldset class="choix">
    <legend>Ton logement (facultatif)</legend>
    ${choix('logement', 'locataire', logement, 'Locataire')}
    ${choix('logement', 'proprietaire', logement, 'Propriétaire')}
    ${choix('logement', 'loge_gratuitement', logement, 'Logé·e gratuitement')}
    <div id="tf-bloc" hidden>
      <label for="tf">Montant de ta taxe foncière sur l’avis, par an (facultatif)</label>
      <input id="tf" type="text" inputmode="decimal" spellcheck="false" autocomplete="off" value="${pr?.logement?.taxe_fonciere_annuelle_eur ?? ''}" />
    </div>
  </fieldset>
  <fieldset class="choix">
    <legend>Ta consommation (facultatif)</legend>
    <p class="aide">Sert à affiner les taxes sur la consommation (carburant, tabac).</p>
    <p id="voiture-titre"><strong>Le foyer a-t-il une voiture ?</strong></p>
    <div role="radiogroup" aria-labelledby="voiture-titre">
      ${choix('voiture', 'inconnu', session.habitudes.voiture, 'Ne pas préciser')}
      ${choix('voiture', 'oui', session.habitudes.voiture, 'Oui')}
      ${choix('voiture', 'non', session.habitudes.voiture, 'Non')}
    </div>
    <p id="fumeur-titre"><strong>Quelqu’un fume-t-il dans le foyer ?</strong></p>
    <div role="radiogroup" aria-labelledby="fumeur-titre">
      ${choix('fumeur', 'inconnu', session.habitudes.fumeur, 'Ne pas préciser')}
      ${choix('fumeur', 'oui', session.habitudes.fumeur, 'Oui')}
      ${choix('fumeur', 'non', session.habitudes.fumeur, 'Non')}
    </div>
  </fieldset>
  <fieldset>
    <legend>Où tu vis</legend>
    <div id="zone-bloc"${outremer ? ' hidden' : ''}>
      <label for="zone">Lieu de résidence</label>
      <select id="zone" aria-describedby="zone-msg">
        <option value="metropole"${zone === 'metropole' ? ' selected' : ''}>France métropolitaine (hors Alsace-Moselle)</option>
        <option value="alsace_moselle"${zone === 'alsace_moselle' ? ' selected' : ''}>Alsace-Moselle (Bas-Rhin, Haut-Rhin, Moselle)</option>
        <option value="etranger"${zone === 'etranger' ? ' selected' : ''}>À l’étranger</option>
      </select>
      <p class="message-champ" id="zone-msg" hidden></p>
    </div>
    <label for="departement">Département (facultatif, pour les taux locaux)</label>
    <select id="departement">
      <option value="">Ne pas préciser</option>
      ${TOUS_DEPARTEMENTS.map(([c, n]) => `<option value="${c}">${c} ${h(n)}</option>`).join('')}
    </select>
    <div id="commune-bloc" hidden>
      <label for="commune">Commune</label>
      <select id="commune" aria-describedby="commune-msg"></select>
      <p class="message-champ" id="commune-msg" hidden></p>
    </div>
  </fieldset>
  <div class="actions"><button class="bouton-principal" type="submit">Calculer</button></div>
  <div id="retour" aria-live="polite"></div>
</form>
<p class="aide">Aucune donnée ne quitte ton téléphone ou ton ordinateur : pas de cookie, pas de mesure d’audience. Voir <a href="#/mentions">confidentialité</a>.</p>
<p><a href="#/explorer">Explorer sans saisir mon salaire</a></p>
${cartesRayons('/calcul')}`

  const $ = <T extends HTMLElement>(s: string) => cible.querySelector(s) as T
  const form = $<HTMLFormElement>('#formulaire')
  const situation = () => (form.querySelector('input[name=situation]:checked') as HTMLInputElement).value as ProfilEtendu['foyer']['situation']
  const radio = (nom: string) => (form.querySelector(`input[name="${nom}"]:checked`) as HTMLInputElement | null)?.value
  // Listes reposées par le script : l'attribut selected d'une option insérée par innerHTML est mal lu par certains
  // moteurs de rendu (happy-dom des tests lit la 2e option dès que la 3e ou une suivante est choisie).
  for (const n of [1, 2] as const) $<HTMLSelectElement>(`#p${n}-statut`).value = pr?.personnes[n - 1]?.statut_activite ?? 'salarie_prive'
  $<HTMLSelectElement>('#zone').value = zone
  $<HTMLSelectElement>('#territoire').value = territoire

  const majVisibilite = () => {
    const s = situation()
    const couple = s.startsWith('couple')
    $('#p2-bloc').hidden = !couple
    $('#enfants-bloc').hidden = s === 'celibataire'
    for (const n of [1, 2]) {
      const st = $<HTMLSelectElement>(`#p${n}-statut`).value as StatutActivite
      $(`#p${n}-salaire`).hidden = !AVEC_SALAIRE.has(st)
      $(`#p${n}-net-libelle`).textContent = LIBELLE_NET[st] ?? LIBELLE_NET_DEFAUT
      $(`#p${n}-preciser`).hidden = !AVEC_PRECISIONS.has(st)
      $(`#p${n}-opt-salarie`).hidden = st !== 'salarie_prive'
      $(`#p${n}-opt-partiel`).hidden = st !== 'salarie_prive' && st !== 'contractuel_public'
      $(`#p${n}-quotite-bloc`).hidden = !$<HTMLInputElement>(`#p${n}-partiel`).checked
      for (const o of ['fonctionnaire', 'apprenti', 'retraite', 'independant']) $(`#p${n}-opt-${o}`).hidden = st !== o
      $(`#p${n}-artisan-bloc`).hidden = radio(`p${n}-activite`) === 'service_bnc'
      $(`#p${n}-rfr-bloc`).hidden = radio(`p${n}-csg`) !== 'rfr'
      const note = $(`#p${n}-note-statut`)
      note.textContent = NOTES_STATUT[st] ?? ''
      note.hidden = !NOTES_STATUT[st]
    }
    $('#tf-bloc').hidden = radio('logement') !== 'proprietaire'
    const om = $<HTMLInputElement>('#outremer').checked
    $('#territoire-bloc').hidden = !om
    $('#zone-bloc').hidden = om
  }
  form.addEventListener('change', majVisibilite)
  majVisibilite()

  // Commune : fichier du département chargé à la demande.
  let communes: Record<string, [string, number | null, number | null]> = {}
  const depSel = $<HTMLSelectElement>('#departement')
  const comSel = $<HTMLSelectElement>('#commune')
  const chargerCommunes = async (dep: string, choisie?: string) => {
    $('#commune-bloc').hidden = !dep
    if (!dep) return
    comSel.innerHTML = '<option value="">Chargement…</option>'
    const d = await chargerSiPresent<{ communes: typeof communes; millesime?: string }>(`communes/${dep}.json`)
    communes = d?.communes ?? {}
    const liste = Object.entries(communes).sort((a, b) => a[1][0].localeCompare(b[1][0], 'fr'))
    comSel.innerHTML =
      '<option value="">Ne pas préciser</option>' +
      liste.map(([c, v]) => `<option value="${c}"${c === choisie ? ' selected' : ''}>${h(v[0])}</option>`).join('')
    if (choisie && communes[choisie]) comSel.value = choisie
    if (ALSACE_MOSELLE.has(dep)) $<HTMLSelectElement>('#zone').value = 'alsace_moselle'
    const t = territoireDeCommune(dep + '00')
    if (t) {
      $<HTMLInputElement>('#outremer').checked = true
      $<HTMLSelectElement>('#territoire').value = t
      majVisibilite()
    }
  }
  depSel.addEventListener('change', () => {
    // Département d'outre-mer choisi : la case et le territoire suivent (et inversement plus bas).
    const t = territoireDeCommune(depSel.value + '00')
    if (t) {
      $<HTMLInputElement>('#outremer').checked = true
      $<HTMLSelectElement>('#territoire').value = t
    } else if (depSel.value) $<HTMLInputElement>('#outremer').checked = false
    majVisibilite()
    return chargerCommunes(depSel.value)
  })
  $('#territoire').addEventListener('change', () => {
    const t = $<HTMLSelectElement>('#territoire').value as TerritoireOutreMer
    const dep = t && t in TERRITOIRES_DOM ? TERRITOIRES_DOM[t as keyof typeof TERRITOIRES_DOM].departement : ''
    if (dep && depSel.value !== dep) {
      depSel.value = dep
      void chargerCommunes(dep)
    }
  })
  const insee = pr?.residence.commune_insee
  if (insee) {
    depSel.value = departementDe(insee)
    await chargerCommunes(depSel.value, insee)
  }

  // Arrivée depuis le héros de l'accueil : salaire et commune repris de la mémoire de la page (jamais d'une adresse),
  // puis calcul lancé tout de suite avec la situation par défaut, que l'on peut modifier ensuite.
  const amorce = session.amorce
  session.amorce = null
  if (amorce) {
    $<HTMLInputElement>('#p1-net').value = amorce.net
    if (amorce.insee && /^(\d{5}|2[AB]\d{3})$/.test(amorce.insee)) {
      depSel.value = departementDe(amorce.insee)
      if (depSel.value) await chargerCommunes(depSel.value, amorce.insee)
    }
  }

  // Le moteur de calcul (environ 160 Ko compressés, exécuté dans un Web Worker) est préchargé dès que l'on commence la saisie.
  const precharger = () => void import('../calcul/hors-fil').then((m) => m.prechauffer()).catch(() => {})
  $('#p1-net').addEventListener('focus', precharger, { once: true })
  $('#p1-statut').addEventListener('focus', precharger, { once: true })

  const retour = $('#retour')
  /** Le calcul lancé depuis l'accueil s'est arrêté (saisie à compléter, erreur) : le message du haut renvoie au formulaire. */
  const statutHaut = (texte: string) => {
    const p = cible.querySelector<HTMLElement>('#statut-haut')
    if (p) p.textContent = texte
  }
  const effacerErreurs = () => {
    cible.querySelectorAll('[aria-invalid]').forEach((el) => el.removeAttribute('aria-invalid'))
    cible.querySelectorAll<HTMLElement>('.message-champ').forEach((el) => (el.hidden = true))
    retour.innerHTML = ''
  }

  // Montants saisis en texte : « 2 100,50 », « 2100.5 » ; une saisie illisible donne NaN (refusée ensuite).
  const nombre = (v: string) => {
    const t = v.replace(/[\s\u00a0\u202f]/g, '').replace(',', '.').replace(/€$/, '')
    return t === '' ? NaN : Number(t)
  }

  /** Montant facultatif : undefined si le champ est vide, NaN s'il est illisible. */
  const facultatif = (sel: string) => {
    const v = $<HTMLInputElement>(sel).value.trim()
    return v === '' ? undefined : nombre(v)
  }
  const fini = (x: number | undefined) => (x !== undefined && Number.isFinite(x) ? x : undefined)

  /** Une personne du foyer, telle que calculerProfil l'attend : seuls les champs de sa situation sont lus. */
  const lirePersonne = (n: 1 | 2): PersonneEtendue => {
    const statut = $<HTMLSelectElement>(`#p${n}-statut`).value as StatutActivite
    const p: PersonneEtendue = { role: n === 1 ? 'declarant1' : 'declarant2', statut_activite: statut, frontalier: false }
    const net = () => {
      const x = nombre($<HTMLInputElement>(`#p${n}-net`).value)
      return Number.isFinite(x) ? x : 0
    }
    const tempsTravail = (): PersonneEtendue['temps_travail'] => {
      if (!$<HTMLInputElement>(`#p${n}-partiel`).checked) return { type: 'temps_plein' }
      const q = nombre($<HTMLInputElement>(`#p${n}-quotite`).value.replace(/%$/, '')) / 100
      return { type: 'temps_partiel', quotite: Number.isFinite(q) ? q : 0 }
    }
    switch (statut) {
      case 'salarie_prive':
        p.salaire_net_avant_impot_mensuel = net()
        p.cadre = $<HTMLInputElement>(`#p${n}-cadre`).checked
        p.frontalier = $<HTMLInputElement>(`#p${n}-frontalier`).checked
        p.temps_travail = tempsTravail()
        break
      case 'contractuel_public':
        p.salaire_net_avant_impot_mensuel = net()
        p.temps_travail = tempsTravail()
        break
      case 'apprenti': {
        p.salaire_net_avant_impot_mensuel = net()
        const c = radio(`p${n}-contrat`)
        if (c) p.apprentissage = { contrat_avant_mars_2025: c === 'avant' }
        break
      }
      case 'fonctionnaire': {
        const v = radio(`p${n}-versant`)
        if (v) p.versant = v as Versant
        const primes = fini(facultatif(`#p${n}-primes`))
        if (primes !== undefined) p.primes_mensuelles = primes
        // Traitement indiqué : le calcul part du traitement et des primes, le net saisi n'est pas utilisé.
        const traitement = facultatif(`#p${n}-traitement`)
        if (traitement !== undefined) p.traitement_indiciaire_brut_mensuel = Number.isFinite(traitement) ? traitement : 0
        else p.salaire_net_avant_impot_mensuel = net()
        break
      }
      case 'retraite': {
        const base = fini(facultatif(`#p${n}-pension-base`))
        if (base !== undefined) p.pension_base_mensuelle = base
        // Retraite complémentaire laissée vide : aucune, comme le dit l'aide du champ.
        const compl = facultatif(`#p${n}-pension-compl`)
        if (compl === undefined) p.pension_complementaire_mensuelle = 0
        else if (Number.isFinite(compl)) p.pension_complementaire_mensuelle = compl
        p.pension_saisie = radio(`p${n}-pension-saisie`) === 'brute' ? 'brute' : 'nette_avant_impot'
        const csg = radio(`p${n}-csg`)
        if (csg === 'rfr') {
          const rfr = fini(facultatif(`#p${n}-rfr`))
          const parts = fini(facultatif(`#p${n}-parts`))
          if (rfr !== undefined && parts !== undefined) p.csg_pension = { revenu_fiscal_reference: rfr, parts }
        } else if (csg) p.csg_pension = { taux: csg as TauxCsgRetraite }
        // Seul l'âge pivot compte (65 ans au 31 décembre) : né en 1960 ou avant, ou après.
        const age = radio(`p${n}-age`)
        if (age) p.annee_naissance = age === 'plus65' ? ANNEE_NAISSANCE_65_ANS : ANNEE_NAISSANCE_65_ANS + 1
        break
      }
      case 'independant': {
        const activite = radio(`p${n}-activite`) as ActiviteMicro | undefined
        const ca = facultatif(`#p${n}-ca`)
        const vl = radio(`p${n}-vl`)
        p.independant = {
          regime: 'micro',
          ...(activite ? { activite } : {}),
          artisan: activite !== 'service_bnc' && $<HTMLInputElement>(`#p${n}-artisan`).checked,
          ...(ca !== undefined ? { chiffre_affaires_annuel: Number.isFinite(ca) ? ca : 0 } : {}),
          ...(vl ? { versement_liberatoire: vl === 'oui' } : {}),
        }
        break
      }
      default:
        break
    }
    return p
  }

  const lireProfil = (): ProfilEtendu => {
    const s = situation()
    const couple = s.startsWith('couple')
    const nb = s === 'celibataire' ? 0 : Math.max(0, Math.min(10, Math.floor(Number($<HTMLInputElement>('#enfants').value) || 0)))
    const alt = Math.max(0, Math.min(nb, Math.floor(Number($<HTMLInputElement>('#alternee').value) || 0)))
    const om = $<HTMLInputElement>('#outremer').checked
    const territoire = $<HTMLSelectElement>('#territoire').value as TerritoireOutreMer | ''
    const z = om ? 'dom' : $<HTMLSelectElement>('#zone').value
    const logement = (form.querySelector('input[name=logement]:checked') as HTMLInputElement).value as 'locataire'
    const tf = nombre($<HTMLInputElement>('#tf').value)
    const commune = comSel.value
    return {
      version_contrat: '1.0',
      annee_revenus: 2025,
      residence: {
        zone: z === 'alsace_moselle' ? 'metropole' : (z as 'metropole'),
        alsace_moselle: z === 'alsace_moselle',
        ...(om && territoire ? { territoire } : {}),
        ...(commune ? { commune_insee: commune } : {}),
      },
      foyer: {
        situation: s,
        enfants: Array.from({ length: nb }, (_, i) => ({ annee_naissance: 2015, garde_alternee: i < alt })),
      },
      logement: {
        statut: logement,
        ...(logement === ('proprietaire' as string) && Number.isFinite(tf) && tf > 0 ? { taxe_fonciere_annuelle_eur: tf } : {}),
      },
      personnes: couple ? [lirePersonne(1), lirePersonne(2)] : [lirePersonne(1)],
    }
  }

  /** Contrôle propre à la saisie, après celui du calcul : l'âge d'un·e retraité·e (abattement des 65 ans et plus). */
  const verifierSaisie = (p: ProfilEtendu): ResultatErreurEtendu | null => {
    const i = p.personnes.findIndex((q) => q.statut_activite === 'retraite' && q.annee_naissance === undefined)
    if (i < 0) return null
    return saisieInvalide(`/personnes/${i}/annee_naissance`, i === 0 ? 'Indique si tu as 65 ans ou plus au 31 décembre 2025.' : 'Indique si ton ou ta conjoint·e a 65 ans ou plus au 31 décembre 2025.')
  }

  /** Champ (ou groupe de boutons) et message de la saisie pour un pointeur d'erreur du calcul (/personnes/<i>/<champ>). */
  const valide = (sel: string) => {
    const x = facultatif(sel)
    return x !== undefined && Number.isFinite(x) && x >= 0
  }
  const CHAMPS: Record<string, (n: number) => string> = {
    salaire_net_avant_impot_mensuel: (n) => `#p${n}-net`,
    'temps_travail/quotite': (n) => `#p${n}-quotite`,
    versant: (n) => `#p${n}-versant`,
    primes_mensuelles: (n) => `#p${n}-primes`,
    traitement_indiciaire_brut_mensuel: (n) => `#p${n}-traitement`,
    'apprentissage/contrat_avant_mars_2025': (n) => `#p${n}-contrat`,
    // Pension de base lisible mais complémentaire illisible : l'erreur porte sur la complémentaire.
    pension_base_mensuelle: (n) => (valide(`#p${n}-pension-base`) && $<HTMLInputElement>(`#p${n}-pension-compl`).value.trim() && !valide(`#p${n}-pension-compl`) ? `#p${n}-pension-compl` : `#p${n}-pension-base`),
    // Outre-mer, le taux de CSG doit être lu sur le relevé : l'erreur porte sur le choix du taux.
    csg_pension: (n) => (radio(`p${n}-csg`) !== 'rfr' || $<HTMLInputElement>('#outremer').checked ? `#p${n}-csg` : valide(`#p${n}-rfr`) ? `#p${n}-parts` : `#p${n}-rfr`),
    annee_naissance: (n) => `#p${n}-age`,
    'independant/activite': (n) => `#p${n}-activite`,
    'independant/chiffre_affaires_annuel': (n) => `#p${n}-ca`,
    'independant/versement_liberatoire': (n) => `#p${n}-vl`,
  }
  /** Champs du lieu de résidence (pointeurs /residence/...). */
  const CHAMPS_RESIDENCE: Record<string, string> = {
    '/residence/territoire': '#territoire',
    '/residence/commune_insee': '#commune',
    '/residence/zone': '#outremer',
    '/residence/alsace_moselle': '#territoire',
  }
  /** Message d'erreur d'un champ : ceux du chemin simple gardent leurs identifiants (p1-msg, p1-msg-q). */
  const messageDe = (sel: string) =>
    /-net$/.test(sel) ? sel.replace(/-net$/, '-msg') : /-quotite$/.test(sel) ? sel.replace(/-quotite$/, '-msg-q') : sel === '#outremer' ? '#zone-msg' : `${sel}-msg`

  const montrerErreur = (err: ResultatErreurEtendu) => {
    statutHaut('Le calcul n’a pas abouti : le message est affiché à côté du champ concerné, plus bas.')
    const e = err.erreur
    if (e.code === 'SAISIE_INVALIDE' && e.champ) {
      const m = /^\/personnes\/(\d)\/(.+)$/.exec(e.champ)
      const sel = m ? CHAMPS[m[2]]?.(Number(m[1]) + 1) : CHAMPS_RESIDENCE[e.champ]
      if (sel) {
        const champ = $(sel)
        const msg = $(messageDe(sel))
        msg.textContent = e.message
        msg.hidden = false
        // Champ des précisions repliées : le bloc s'ouvre pour montrer l'erreur.
        const details = champ.closest('details')
        if (details) details.open = true
        if (champ.tagName === 'FIELDSET') champ.querySelector<HTMLInputElement>('input')?.focus()
        else {
          champ.setAttribute('aria-invalid', 'true')
          champ.focus()
        }
        return
      }
    }
    if (e.code === 'PROFIL_HORS_V1') {
      retour.innerHTML = `<div class="avertissement" tabindex="-1"><p><strong>Ce cas n’est pas encore couvert par le calcul.</strong></p><p>${h(e.message)}</p>${
        e.redirection ? `<p><a class="bouton" href="${h(e.redirection.url)}">${h(e.redirection.libelle)}</a></p>` : ''
      }</div>`
    } else retour.innerHTML = `<p class="erreur" tabindex="-1">${h(e.message)}</p>`
    retour.querySelector<HTMLElement>('[tabindex="-1"]')?.focus?.()
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault()
    effacerErreurs()
    const s = situation()
    const nbE = Math.floor(Number($<HTMLInputElement>('#enfants').value) || 0)
    const nbA = Math.floor(Number($<HTMLInputElement>('#alternee').value) || 0)
    if (s !== 'celibataire' && nbA > nbE) {
      const champ = $<HTMLInputElement>('#alternee')
      const msg = $('#msg-alternee')
      champ.setAttribute('aria-invalid', 'true')
      msg.textContent = `Le nombre d’enfants en garde alternée (${nbA}) dépasse le nombre d’enfants à charge (${nbE}).`
      msg.hidden = false
      champ.focus()
      return
    }
    const profil = lireProfil()
    const err = verifierProfilEtendu(profil) ?? verifierSaisie(profil)
    if (err) return montrerErreur(err)
    retour.innerHTML = '<p class="chargement">Calcul en cours sur ton appareil…</p>'
    annoncer('Calcul en cours')
    try {
      const communeCode = profil.residence.commune_insee
      const dep = communeCode ? departementDe(communeCode) : null
      const [horsFil, hb, affectation, tva, tfDep] = await Promise.all([
        import('../calcul/hors-fil'),
        import('../calcul/hors-bulletin'),
        chargerSiPresent('prelevements/affectation.json'),
        chargerSiPresent('prelevements/tva_conso.json'),
        dep ? chargerSiPresent(`prelevements/taxe_fonciere/${dep}.json`) : Promise.resolve(null),
      ])
      const commune = communeCode ? (communes[communeCode] ?? null) : undefined
      // Destinataires propres à affectation.json : enregistrés ici aussi, le moteur tournant dans un worker.
      enregistrerDestinataires((affectation as { destinataires?: Record<string, { nom: string; administration: string }> } | null)?.destinataires)
      const res = await horsFil.calculerProfilHorsFil(profil, { affectation, commune })
      if (res.statut === 'erreur') return montrerErreur(res)
      const valeur = (n: string) => ((form.querySelector(`input[name=${n}]:checked`) as HTMLInputElement | null)?.value ?? 'inconnu') as 'oui'
      session.habitudes = { voiture: valeur('voiture'), fumeur: valeur('fumeur') }
      session.complet = hb.assembler(
        profil,
        res,
        { tva, affectation, tfDep, ligneCommune: communeCode && tfDep ? (tfDep.communes[communeCode] ?? null) : undefined },
        session.habitudes,
      )
      session.profil = profil
      session.resultat = res
      session.communeNom = commune ? commune[0] : null
      session.communeTaux = commune ? [commune[1], commune[2]] : null
      location.hash = '#/calcul/resultat'
    } catch (e) {
      console.error(e)
      statutHaut('Le calcul est indisponible pour le moment : voir le message sous le formulaire.')
      retour.innerHTML = '<p class="erreur">Le calcul est indisponible pour le moment. Tu peux toujours <a href="#/explorer/etat">explorer le budget</a>.</p>'
    }
  })
  if (amorce) form.dispatchEvent(new Event('submit', { cancelable: true }))
}

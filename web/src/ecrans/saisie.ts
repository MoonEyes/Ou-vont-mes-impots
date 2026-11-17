// Écran 1 : saisie du salaire net avant impôt et du profil facultatif.
import { verifierProfil } from '../calcul/perimetre'
import type { Personne, Profil, ResultatErreur, StatutActivite } from '../calcul/types'
import { ALSACE_MOSELLE, DEPARTEMENTS, departementDe } from '../departements'
import { chargerSiPresent } from '../donnees'
import { session } from '../etat'
import { annoncer, h } from '../util'

const STATUTS: [StatutActivite, string][] = [
  ['salarie_prive', 'Salarié·e du secteur privé'],
  ['sans_activite', 'Sans activité professionnelle'],
  ['fonctionnaire', 'Fonctionnaire'],
  ['contractuel_public', 'Contractuel·le de la fonction publique'],
  ['independant', 'Indépendant·e ou micro-entrepreneur·se'],
  ['retraite', 'Retraité·e'],
  ['demandeur_emploi', 'Demandeur·se d’emploi indemnisé·e'],
  ['apprenti', 'Apprenti·e'],
  ['etudiant', 'Étudiant·e'],
]

const AIDE_SALAIRE =
  'Prends sur ta fiche de paie la ligne <strong>Net à payer avant impôt sur le revenu</strong>. Si tu touches des primes ou un 13e mois, fais la moyenne sur 12 mois : additionne le net avant impôt de tes 12 dernières fiches et divise par 12. N’utilise ni le <em>net imposable</em>, ni le <em>montant net social</em>, ni le <em>net payé</em> (après prélèvement à la source).'

function blocPersonne(n: 1 | 2, p?: Personne): string {
  const id = (x: string) => `p${n}-${x}`
  const statut = p?.statut_activite ?? (n === 1 ? 'salarie_prive' : 'salarie_prive')
  const tp = p?.temps_travail?.type === 'temps_partiel' ? p.temps_travail.quotite : null
  return `<fieldset id="${id('bloc')}" ${n === 2 ? 'hidden' : ''}>
  <legend>${n === 1 ? 'Toi' : 'Ton ou ta conjoint·e'}</legend>
  <label for="${id('statut')}">Situation professionnelle</label>
  <select id="${id('statut')}" name="${id('statut')}">
    ${STATUTS.map(([v, l]) => `<option value="${v}"${v === statut ? ' selected' : ''}>${h(l)}</option>`).join('')}
  </select>
  <div id="${id('salarie')}">
    <label for="${id('net')}">Salaire net avant impôt, par mois (en euros)</label>
    <input id="${id('net')}" name="${id('net')}" type="number" inputmode="decimal" min="1" step="any" autocomplete="off" aria-describedby="${id('aide')} ${id('msg')}" value="${p?.salaire_net_avant_impot_mensuel ?? ''}" />
    <p class="message-champ" id="${id('msg')}" hidden></p>
    <details><summary>Où trouver ce montant ?</summary><p class="aide" id="${id('aide')}">${AIDE_SALAIRE}</p></details>
    <label class="case"><input type="checkbox" id="${id('cadre')}"${p?.cadre ? ' checked' : ''} /> Statut cadre</label>
    <label class="case"><input type="checkbox" id="${id('partiel')}"${tp !== null ? ' checked' : ''} /> Temps partiel</label>
    <div id="${id('quotite-bloc')}" ${tp === null ? 'hidden' : ''}>
      <label for="${id('quotite')}">Quotité de travail (en % d’un temps plein)</label>
      <input id="${id('quotite')}" type="number" inputmode="decimal" min="1" max="100" step="any" value="${tp !== null ? Math.round(tp * 100) : 80}" aria-describedby="${id('msg-q')}" />
      <p class="message-champ" id="${id('msg-q')}" hidden></p>
    </div>
    <label class="case"><input type="checkbox" id="${id('frontalier')}"${p?.frontalier ? ' checked' : ''} /> Je travaille hors de France (frontalier)</label>
  </div>
</fieldset>`
}

export async function rendre(cible: HTMLElement) {
  const pr = session.profil
  const sit = pr?.foyer.situation ?? 'celibataire'
  const nbEnfants = pr?.foyer.enfants.length ?? 0
  const nbAlternee = pr?.foyer.enfants.filter((e) => e.garde_alternee).length ?? 0
  const logement = pr?.logement?.statut ?? 'locataire'
  const zone = pr?.residence.zone === 'metropole' && pr.residence.alsace_moselle ? 'alsace_moselle' : (pr?.residence.zone ?? 'metropole')
  const choix = (nom: string, valeur: string, courant: string, texte: string) =>
    `<label><input type="radio" name="${nom}" value="${valeur}"${valeur === courant ? ' checked' : ''} /> ${texte}</label>`

  cible.innerHTML = `
<h1>Où va l’argent que tu paies ?</h1>
<p class="chapeau">Indique ton salaire : le site calcule ce que tu finances chaque année, à qui va l’argent, puis montre où va l’argent public. Le calcul se fait <strong>sur ton appareil</strong> : rien de ce que tu saisis n’est envoyé ni enregistré.</p>
<p class="aide">Version 1 : salarié·es du secteur privé vivant en métropole (hors Alsace-Moselle), revenus 2025.</p>
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
      <input id="alternee" type="number" inputmode="numeric" min="0" max="10" step="1" value="${nbAlternee}" />
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
      <input id="tf" type="number" inputmode="decimal" min="0" step="any" value="${pr?.logement?.taxe_fonciere_annuelle_eur ?? ''}" />
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
    <label for="zone">Lieu de résidence</label>
    <select id="zone">
      <option value="metropole"${zone === 'metropole' ? ' selected' : ''}>France métropolitaine (hors Alsace-Moselle)</option>
      <option value="alsace_moselle"${zone === 'alsace_moselle' ? ' selected' : ''}>Alsace-Moselle (Bas-Rhin, Haut-Rhin, Moselle)</option>
      <option value="dom"${zone === 'dom' ? ' selected' : ''}>Outre-mer</option>
      <option value="etranger"${zone === 'etranger' ? ' selected' : ''}>À l’étranger</option>
    </select>
    <label for="departement">Département (facultatif, pour les taux locaux)</label>
    <select id="departement">
      <option value="">Ne pas préciser</option>
      ${DEPARTEMENTS.map(([c, n]) => `<option value="${c}">${c} ${h(n)}</option>`).join('')}
    </select>
    <div id="commune-bloc" hidden>
      <label for="commune">Commune</label>
      <select id="commune"></select>
    </div>
  </fieldset>
  <div class="actions"><button class="bouton-principal" type="submit">Calculer</button></div>
  <div id="retour" aria-live="polite"></div>
</form>
<p class="aide">Aucune donnée ne quitte ton téléphone ou ton ordinateur : pas de cookie, pas de mesure d’audience. Voir <a href="#/mentions">confidentialité</a>.</p>
<p><a href="#/etat">Explorer le budget sans calcul personnel</a></p>`

  const $ = <T extends HTMLElement>(s: string) => cible.querySelector(s) as T
  const form = $<HTMLFormElement>('#formulaire')
  const situation = () => (form.querySelector('input[name=situation]:checked') as HTMLInputElement).value as Profil['foyer']['situation']

  const majVisibilite = () => {
    const s = situation()
    const couple = s.startsWith('couple')
    $('#p2-bloc').hidden = !couple
    $('#enfants-bloc').hidden = s === 'celibataire'
    for (const n of [1, 2]) {
      const st = $<HTMLSelectElement>(`#p${n}-statut`).value
      $(`#p${n}-salarie`).hidden = st !== 'salarie_prive'
      $(`#p${n}-quotite-bloc`).hidden = !$<HTMLInputElement>(`#p${n}-partiel`).checked
    }
    $('#tf-bloc').hidden = (form.querySelector('input[name=logement]:checked') as HTMLInputElement).value !== 'proprietaire'
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
    if (ALSACE_MOSELLE.has(dep)) $<HTMLSelectElement>('#zone').value = 'alsace_moselle'
  }
  depSel.addEventListener('change', () => chargerCommunes(depSel.value))
  const insee = pr?.residence.commune_insee
  if (insee) {
    depSel.value = departementDe(insee)
    await chargerCommunes(depSel.value, insee)
  }

  // Le moteur de calcul (environ 160 Ko compressés) est préchargé dès que l'on commence la saisie.
  const precharger = () => void import('../calcul/moteur').catch(() => {})
  $('#p1-net').addEventListener('focus', precharger, { once: true })

  const retour = $('#retour')
  const effacerErreurs = () => {
    cible.querySelectorAll('[aria-invalid]').forEach((el) => el.removeAttribute('aria-invalid'))
    cible.querySelectorAll<HTMLElement>('.message-champ').forEach((el) => (el.hidden = true))
    retour.innerHTML = ''
  }

  const lireProfil = (): Profil => {
    const s = situation()
    const couple = s.startsWith('couple')
    const personne = (n: 1 | 2): Personne => {
      const statut = $<HTMLSelectElement>(`#p${n}-statut`).value as StatutActivite
      const p: Personne = { role: n === 1 ? 'declarant1' : 'declarant2', statut_activite: statut, frontalier: false }
      if (statut === 'salarie_prive') {
        const net = parseFloat($<HTMLInputElement>(`#p${n}-net`).value.replace(',', '.'))
        p.salaire_net_avant_impot_mensuel = Number.isFinite(net) ? net : 0
        p.cadre = $<HTMLInputElement>(`#p${n}-cadre`).checked
        p.frontalier = $<HTMLInputElement>(`#p${n}-frontalier`).checked
        const partiel = $<HTMLInputElement>(`#p${n}-partiel`).checked
        const q = parseFloat($<HTMLInputElement>(`#p${n}-quotite`).value.replace(',', '.')) / 100
        p.temps_travail = partiel ? { type: 'temps_partiel', quotite: Number.isFinite(q) ? q : 0 } : { type: 'temps_plein' }
      }
      return p
    }
    const nb = s === 'celibataire' ? 0 : Math.max(0, Math.min(10, Math.floor(Number($<HTMLInputElement>('#enfants').value) || 0)))
    const alt = Math.max(0, Math.min(nb, Math.floor(Number($<HTMLInputElement>('#alternee').value) || 0)))
    const z = $<HTMLSelectElement>('#zone').value
    const logement = (form.querySelector('input[name=logement]:checked') as HTMLInputElement).value as 'locataire'
    const tf = parseFloat($<HTMLInputElement>('#tf').value.replace(',', '.'))
    const commune = comSel.value
    return {
      version_contrat: '1.0',
      annee_revenus: 2025,
      residence: {
        zone: z === 'alsace_moselle' ? 'metropole' : (z as 'metropole'),
        alsace_moselle: z === 'alsace_moselle',
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
      personnes: couple ? [personne(1), personne(2)] : [personne(1)],
    }
  }

  const montrerErreur = (err: ResultatErreur) => {
    const e = err.erreur
    if (e.code === 'SAISIE_INVALIDE' && e.champ) {
      const m = /^\/personnes\/(\d)\/(salaire_net_avant_impot_mensuel|temps_travail\/quotite)/.exec(e.champ)
      if (m) {
        const n = Number(m[1]) + 1
        const champ = $<HTMLInputElement>(m[2].startsWith('temps') ? `#p${n}-quotite` : `#p${n}-net`)
        const msg = $(m[2].startsWith('temps') ? `#p${n}-msg-q` : `#p${n}-msg`)
        champ.setAttribute('aria-invalid', 'true')
        msg.textContent = e.message
        msg.hidden = false
        champ.focus()
        return
      }
    }
    if (e.code === 'PROFIL_HORS_V1') {
      retour.innerHTML = `<div class="avertissement"><p><strong>Ce cas n’est pas encore couvert par la version 1.</strong></p><p>${h(e.message)}</p>${
        e.redirection ? `<p><a class="bouton" href="${h(e.redirection.url)}">${h(e.redirection.libelle)}</a></p>` : ''
      }</div>`
    } else retour.innerHTML = `<p class="erreur">${h(e.message)}</p>`
    retour.querySelector<HTMLElement>('a, p')?.focus?.()
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault()
    effacerErreurs()
    const profil = lireProfil()
    const err = verifierProfil(profil)
    if (err) return montrerErreur(err)
    retour.innerHTML = '<p class="chargement">Calcul en cours sur ton appareil…</p>'
    annoncer('Calcul en cours')
    try {
      const communeCode = profil.residence.commune_insee
      const dep = communeCode ? departementDe(communeCode) : null
      const [moteur, hb, affectation, tva, tfDep] = await Promise.all([
        import('../calcul/moteur'),
        import('../calcul/hors-bulletin'),
        chargerSiPresent('prelevements/affectation.json'),
        chargerSiPresent('prelevements/tva_conso.json'),
        dep ? chargerSiPresent(`prelevements/taxe_fonciere/${dep}.json`) : Promise.resolve(null),
      ])
      const commune = communeCode ? (communes[communeCode] ?? null) : undefined
      const res = moteur.calculer(profil, { affectation, commune })
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
      location.hash = '#/paie'
    } catch (e) {
      console.error(e)
      retour.innerHTML = '<p class="erreur">Le calcul est indisponible pour le moment. Tu peux toujours <a href="#/etat">explorer le budget</a>.</p>'
    }
  })
}

// Écran 6 : qui reçoit l'argent (associations, opérateurs, France 2030, marchés de l'État).
// Seules des personnes morales sont nommées ; le reste est agrégé (règle du pipeline).
import { charger, chargerSiPresent, listeProgrammes, type Noeud } from '../donnees'
import { cartesRayons, planRubrique } from '../composants/hub'
import { lien } from '../routeur'
import { absent, entier, eurLisible, h, source, sur100, surligne } from '../util'

interface Top {
  siren: string
  denomination: string
  categorie_juridique: string
  montant_eur: number
  eur_sur_100?: number
  objet?: string
  nombre_marches?: number
  projets?: number
}
interface Groupe {
  top: Top[]
  autres_personnes_morales?: { nombre: number; montant_eur: number }
  autres_non_verifies?: { nombre: number; montant_eur: number; note?: string }
  exclus_personnes_physiques_ou_non_identifies?: { montant_eur: number; lignes: number }
  total_eur?: number
  total_source_eur?: number
  millesime?: string
  source?: string
}

const ONGLETS: [string, string][] = [
  ['programme', 'Par programme'],
  ['france2030', 'France 2030'],
  ['marches', 'Marchés de l’État'],
]

function tableGroupe(g: Groupe, legende: string, colonne?: 'objet' | 'nombre_marches' | 'projets'): string {
  const lignes = g.top
    .map(
      (t, i) => `<tr${i >= 20 ? ' data-plus hidden' : ''}><td>${h(t.denomination)}${colonne === 'objet' && t.objet ? `<div class="aide">${h(t.objet)}</div>` : ''}</td>${
        colonne && colonne !== 'objet' ? `<td class="nombre">${h(entier(Number(t[colonne] ?? 0)))}</td>` : ''
      }<td class="nombre">${h(eurLisible(t.montant_eur))}</td>${g.top.some((x) => x.eur_sur_100 !== undefined) ? `<td class="nombre">${t.eur_sur_100 !== undefined ? h(sur100(t.eur_sur_100)) : ''}</td>` : ''}</tr>`,
    )
    .join('')
  const avecSur100 = g.top.some((x) => x.eur_sur_100 !== undefined)
  const autres = [
    g.autres_personnes_morales && g.autres_personnes_morales.nombre
      ? `${entier(g.autres_personnes_morales.nombre)} autres personnes morales : ${eurLisible(g.autres_personnes_morales.montant_eur)}`
      : '',
    g.autres_non_verifies && g.autres_non_verifies.nombre
      ? `${entier(g.autres_non_verifies.nombre)} bénéficiaires non vérifiés (jamais nommés) : ${eurLisible(g.autres_non_verifies.montant_eur)}`
      : '',
    g.exclus_personnes_physiques_ou_non_identifies && g.exclus_personnes_physiques_ou_non_identifies.montant_eur
      ? `Personnes physiques ou bénéficiaires non identifiés, agrégés et non nommés : ${eurLisible(g.exclus_personnes_physiques_ou_non_identifies.montant_eur)}`
      : '',
  ].filter(Boolean)
  return `<div class="tableau-defile"><table>
  <caption>${h(legende)}</caption>
  <thead><tr><th scope="col">Bénéficiaire (personne morale)</th>${
    colonne === 'nombre_marches' ? '<th scope="col" class="nombre">Marchés</th>' : colonne === 'projets' ? '<th scope="col" class="nombre">Projets</th>' : ''
  }<th scope="col" class="nombre">Montant</th>${avecSur100 ? '<th scope="col" class="nombre">Sur 100 € du budget</th>' : ''}</tr></thead>
  <tbody>${lignes}</tbody></table></div>
  ${g.top.length > 20 ? `<button type="button" class="voir-plus">Afficher les ${g.top.length} premiers</button>` : ''}
  ${autres.length ? `<ul>${autres.map((a) => `<li>${h(a)}</li>`).join('')}</ul>` : ''}`
}

function brancherVoirPlus(cible: HTMLElement) {
  cible.querySelectorAll<HTMLButtonElement>('.voir-plus').forEach((b) =>
    b.addEventListener('click', () => {
      b.previousElementSibling?.querySelectorAll<HTMLElement>('[data-plus]').forEach((tr) => (tr.hidden = false))
      b.remove()
    }),
  )
}

async function ongletProgramme(p: string | null): Promise<string> {
  const progs = (await listeProgrammes()).sort((a, b) => Number(a.numero) - Number(b.numero))
  const choix = `<label for="prog">Programme</label><select id="prog">${progs
    .map((x) => `<option value="${x.numero}"${x.numero === p ? ' selected' : ''}>${h(x.numero)} ${h(x.nom)}</option>`)
    .join('')}</select>`
  const num = p ?? progs[0]?.numero
  const d = await chargerSiPresent<{
    libelle: string
    millesime: string
    source: string
    associations: (Groupe & { millesime: string; source: string }) | null
    operateurs: { millesime: string; source: string; note?: string; liste: { operateur: string; categorie?: string; statut?: string }[] } | null
  }>(`beneficiaires/programme_${num}.json`)
  if (!d) return choix + absent('Pas de données de bénéficiaires pour ce programme.')
  const a = d.associations as (Groupe & { eur_sur_100?: number; millesime: string }) | null
  const asso = a
    ? `<h3>Associations subventionnées</h3>
<p class="carte" data-cle>Total versé aux associations (${h(a.millesime)}) : <strong>${surligne(eurLisible(a.total_source_eur ?? 0))}</strong>${
        typeof a.eur_sur_100 === 'number' ? `, soit ${h(sur100(a.eur_sur_100))} sur 100 € du budget de l’État` : ', part sur 100 € non publiée'
      }.</p>${tableGroupe(a, `Associations, ${a.millesime}`, 'objet')}${source(d.associations!.source)}`
    : absent('Aucune subvention à une association publiée pour ce programme.')
  const ops = d.operateurs?.liste?.length
    ? `<h3>Opérateurs rattachés</h3><p>${h(d.operateurs.note ?? '')}</p><ul>${d.operateurs.liste
        .map((o) => `<li>${h(o.operateur)}${o.categorie ? ` <span class="aide">(${h(o.categorie)})</span>` : ''}</li>`)
        .join('')}</ul>${source(d.operateurs.source, d.operateurs.millesime)}`
    : ''
  return `${choix}<h2>${h(d.libelle)}</h2>${asso}${ops}`
}

async function ongletFrance2030(): Promise<string> {
  const d = await chargerSiPresent<{ millesime: string; source: string; note: string; ensemble: Groupe & { total_eur: number; projets: number }; par_operateur: Record<string, Groupe & { total_eur: number }> }>(
    'beneficiaires/france2030.json',
  )
  if (!d) return absent()
  return `<p>${h(d.millesime)} : <strong>${h(eurLisible(d.ensemble.total_eur))}</strong> pour ${h(entier(d.ensemble.projets))} projets.</p>
<p class="avertissement">${h(d.note)}</p>
${tableGroupe(d.ensemble, 'Principaux bénéficiaires de France 2030', 'projets')}
<h3>Par opérateur</h3>
<ul>${Object.entries(d.par_operateur)
    .map(([k, g]) => `<li>${h(k)} : ${h(eurLisible(g.total_eur))}</li>`)
    .join('')}</ul>
${source(d.source)}`
}

async function ongletMarches(): Promise<string> {
  const d = await chargerSiPresent<{ millesime: string; source: string; perimetre: string; unite: string; ensemble: Groupe & { total_eur: number; nombre_marches: number }; par_ministere: Record<string, Groupe & { total_eur: number; nombre_marches: number }> }>(
    'beneficiaires/marches_etat.json',
  )
  if (!d) return absent()
  const budget = (await charger<Noeud>('arbre/racine.json')).md * 1e9
  return `<p class="carte" data-cle>${h(d.millesime)} : <strong>${surligne(eurLisible(d.ensemble.total_eur))}</strong> (${h(d.unite)}), ${h(entier(d.ensemble.nombre_marches))} marchés, l’équivalent de ${h(
    sur100((d.ensemble.total_eur / budget) * 100),
  )} sur 100 € du budget de l’État (montants notifiés, pas des paiements).</p>
<p class="aide">${h(d.perimetre)}</p>
${tableGroupe(d.ensemble, 'Principaux titulaires de marchés de l’État', 'nombre_marches')}
<h3>Par ministère</h3>
<ul>${Object.entries(d.par_ministere)
    .sort((a, b) => b[1].total_eur - a[1].total_eur)
    .map(([k, g]) => `<li>${h(k)} : ${h(eurLisible(g.total_eur))} (${h(entier(g.nombre_marches))} marchés)</li>`)
    .join('')}</ul>
${source(d.source)}`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const p = params.get('p')
  const onglet = params.get('onglet') ?? 'programme'
  const contenu = onglet === 'france2030' ? await ongletFrance2030() : onglet === 'marches' ? await ongletMarches() : await ongletProgramme(p)
  cible.innerHTML = `<h1>Qui reçoit l’argent</h1>
<p>Pour un programme : <a href="${lien('/beneficiaires/programme', { p: p ?? undefined })}">à quoi sert son argent (nature de la dépense, effectifs)</a>${p ? ` · <a href="${lien('/decisions/votes', { p })}">ses votes et mouvements de crédits</a> · <a href="${lien('/decisions/realisations', { p })}">ce qui a été fait</a>` : ''}.</p>
<p class="chapeau">Les bénéficiaires connus de l’argent de l’État : associations, opérateurs, entreprises soutenues par France 2030, titulaires de marchés publics. Seules des personnes morales sont nommées. Les prestations versées aux personnes (retraites, santé, famille, chômage) ne sont pas nominatives : elles sont présentées par branche dans <a href="#/explorer/secu">Sécurité sociale et protection sociale</a>.</p>
${planRubrique('/beneficiaires')}
<p>Toutes les subventions publiées, par année, par ministère et par type de bénéficiaire, avec une recherche par organisme : <a href="${lien('/beneficiaires/subventions')}">Les subventions de l’État et de ses opérateurs</a>.</p>
<div class="bascule" role="group" aria-label="Catégorie de bénéficiaires">${ONGLETS.map(
    ([k, l]) => `<a class="bouton" href="${lien('/beneficiaires', { onglet: k, p: k === 'programme' ? p : undefined })}"${k === onglet ? ' aria-current="true"' : ''}>${h(l)}</a>`,
  ).join('')}</div>
${contenu}
${cartesRayons('/beneficiaires')}`
  brancherVoirPlus(cible)
  cible.querySelector<HTMLSelectElement>('#prog')?.addEventListener('change', (e) => {
    location.hash = lien('/beneficiaires', { onglet: 'programme', p: (e.target as HTMLSelectElement).value })
  })
}

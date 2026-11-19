// Opérateurs de l'État (site/data/operateurs/) : financement par l'État, taxes affectées, ressources
// propres, emplois, séries 2020-2024 et LFI 2025, statut de traçabilité. Rémunérations : seule la
// somme des dix plus hautes, telle que publiée ; aucun nom de personne.
import { choix, listeRecherche, valeurChoix } from '../composants/choix'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { absent, badgeCalcule, entier, eurLisible, h, type Statut, STATUTS, sur100, surligne, traitStatut } from '../util'
import { enCours } from './dette'

interface Montant {
  ae_eur?: number
  cp_eur?: number
}
interface Annee {
  nature: 'execution' | 'lfi'
  financement_etat?: Record<string, Montant>
  financement_etat_total_cp_eur?: number
  credits_votes_lfi?: Record<string, Montant>
  credits_votes_lfi_total_cp_eur?: number
  programmes_financeurs?: string[]
  taxes_affectees_eur?: number | null
  taxes_affectees_prevision_eur?: number | null
  ressources_propres_eur?: number | null
  masse_salariale_eur?: number | null
  etpt_sous_plafond?: number | null
  etpt_hors_plafond?: number | null
  plafond_emplois_lfi?: number | null
  dix_plus_hautes_remunerations_eur?: number | null
  sources?: Record<string, string>
}
interface Operateur {
  id: string
  nom: string
  sigle: string | null
  statut?: string | null
  niveau: 'operateur' | 'categorie'
  programme_chef_de_file: string | null
  programme_chef_de_file_libelle?: string
  mission_chef_de_file?: string
  membres?: { nom: string; statut?: string; dix_plus_hautes_remunerations_eur?: Record<string, number> }[]
  annees: Record<string, Annee>
}
interface Fichier {
  millesime: string
  source: string
  operateurs: Operateur[]
}
interface Index {
  limites: string[]
  couverture: { lignes_jaune: number; categories: number; operateurs_liste_plf2026: number }
}

const ANNEE_REF = '2024'
const PAR_PAGE = 30

/** Statut de traçabilité de la subvention d'un opérateur, avec sa raison (limites publiées dans index.json). */
export function statutOperateur(o: Operateur, limites: string[]): { statut: Statut; libelle: string; raison: string } {
  const lim = (mot: string) => limites.find((l) => l.toLowerCase().includes(mot)) ?? ''
  if (o.niveau === 'categorie')
    return { statut: 'approche', libelle: 'Approché par catégorie', raison: lim('catégories d') || 'Montant publié pour la catégorie, pas par établissement.' }
  const progs = o.annees[ANNEE_REF]?.programmes_financeurs ?? []
  if (progs.length > 1) return { statut: 'approche', libelle: 'Approché nommé', raison: lim('ventile pas') || 'Subvention non ventilée entre les programmes financeurs.' }
  if (o.annees[ANNEE_REF]?.financement_etat_total_cp_eur) return { statut: 'trace', libelle: STATUTS.trace.libelle, raison: 'Opérateur nommé, un seul programme financeur : la subvention lui est rattachée en entier.' }
  return { statut: 'nonpub', libelle: STATUTS.nonpub.libelle, raison: `Pas de financement de l’État publié pour ${ANNEE_REF}.` }
}

const scsp = (a?: Annee) => a?.financement_etat?.scsp?.cp_eur ?? 0
const financement = (a?: Annee) => (a?.nature === 'lfi' ? a?.credits_votes_lfi_total_cp_eur : a?.financement_etat_total_cp_eur) ?? null
const val = (x: number | null | undefined, f: (n: number) => string) => (typeof x === 'number' ? f(x) : '–')

function fiche(o: Operateur, totalScsp: number, limites: string[]): string {
  const annees = Object.keys(o.annees).sort()
  const s = statutOperateur(o, limites)
  const ref = o.annees[ANNEE_REF]
  const ligne = (titre: string, f: (a: Annee) => string) =>
    `<tr><th scope="row">${h(titre)}</th>${annees.map((y) => `<td class="nombre">${f(o.annees[y])}</td>`).join('')}</tr>`
  const remu = o.niveau === 'operateur' ? annees.map((y) => o.annees[y].dix_plus_hautes_remunerations_eur).some((x) => typeof x === 'number') : false
  return `
<p>${traitStatut(s.statut)}<strong>${h(s.libelle)}</strong> : ${h(s.raison)}</p>
${scsp(ref) > 0 ? `<p>Subvention pour charges de service public ${ANNEE_REF} : ${h(eurLisible(scsp(ref)))}, soit ${h(sur100((scsp(ref) / totalScsp) * 100))} sur 100 € de subventions de l’État aux opérateurs.</p>` : ''}
<div class="tableau-defile"><table><caption>${h(o.nom)} : exécution ${annees.filter((y) => o.annees[y].nature === 'execution').join(', ')}${annees.some((y) => o.annees[y].nature === 'lfi') ? ' ; budget voté pour ' + annees.filter((y) => o.annees[y].nature === 'lfi').join(', ') : ''}</caption>
<thead><tr><th scope="col">Euros</th>${annees.map((y) => `<th scope="col" class="nombre">${y}${o.annees[y].nature === 'lfi' ? ' (voté)' : ''}</th>`).join('')}</tr></thead>
<tbody>
${ligne('Subvention pour charges de service public', (a) => val(a.nature === 'lfi' ? a.credits_votes_lfi?.scsp?.cp_eur : a.financement_etat?.scsp?.cp_eur, eurLisible))}
${ligne('Transferts', (a) => val(a.nature === 'lfi' ? a.credits_votes_lfi?.transferts?.cp_eur : a.financement_etat?.transferts?.cp_eur, eurLisible))}
${ligne('Total versé par l’État', (a) => val(financement(a), eurLisible))}
${ligne('Taxes affectées', (a) => val(a.taxes_affectees_eur ?? a.taxes_affectees_prevision_eur, eurLisible))}
${ligne('Ressources propres', (a) => val(a.ressources_propres_eur, eurLisible))}
${ligne('Masse salariale', (a) => val(a.masse_salariale_eur, eurLisible))}
${ligne('Emplois (ETPT sous plafond)', (a) => val(a.etpt_sous_plafond, (n) => entier(Math.round(n))))}
${ligne('Emplois hors plafond', (a) => val(a.etpt_hors_plafond, (n) => entier(Math.round(n))))}
${ligne('Plafond d’emplois voté', (a) => val(a.plafond_emplois_lfi, (n) => entier(Math.round(n))))}
${remu ? ligne('Dix plus hautes rémunérations (somme)', (a) => val(a.dix_plus_hautes_remunerations_eur, eurLisible)) : ''}
</tbody></table></div>
${
  o.membres?.length
    ? `<details><summary>Les ${o.membres.length} établissements de la catégorie</summary><ul>${o.membres
        .map((m) => {
          const r = m.dix_plus_hautes_remunerations_eur?.[ANNEE_REF]
          return `<li>${h(m.nom)}${m.statut ? ` (${h(m.statut)})` : ''}${typeof r === 'number' ? ` · dix plus hautes rémunérations ${ANNEE_REF} (somme) : ${h(eurLisible(r))}` : ''}</li>`
        })
        .join('')}</ul></details>`
    : ''
}
<p class="aide">Rémunérations : somme des dix plus hautes rémunérations brutes publiée par la loi de finances, jamais un montant individuel. Programmes financeurs ${ANNEE_REF} : ${(ref?.programmes_financeurs ?? []).map((p) => `<a href="${lien('/beneficiaires/programme', { p })}">${h(p)}</a>`).join(', ') || '–'}.</p>
<p class="source">${h([...new Set(annees.flatMap((y) => Object.values(o.annees[y].sources ?? {})))].join(', '))}</p>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const [f, idx] = await Promise.all([chargerSiPresent<Fichier>('operateurs/operateurs.json'), chargerSiPresent<Index>('operateurs/index.json')])
  if (!f) {
    cible.innerHTML = enCours('Les opérateurs de l’État', 'Universités, agences, établissements publics : ce que l’État leur verse et leurs emplois.')
    return
  }
  const limites = idx?.limites ?? []
  const ops = f.operateurs
  const totalScsp = ops.reduce((s, o) => s + scsp(o.annees[ANNEE_REF]), 0)
  const missions = [...new Set(ops.map((o) => o.mission_chef_de_file).filter((x): x is string => !!x))].sort((a, b) => a.localeCompare(b, 'fr'))
  const statuts = [...new Set(ops.map((o) => o.statut).filter((x): x is string => !!x))].sort()
  const p = params.get('p') ?? ''
  const etat = { mission: params.get('mission') ?? '', categorie: params.get('categorie') ?? '', q: params.get('q') ?? '', tri: 'scsp', page: 1 }

  cible.innerHTML = `
<h1>Les opérateurs de l’État</h1>
<p class="chapeau">Universités, agences régionales de santé, agences de l’eau, établissements publics : ils reçoivent une subvention de l’État, parfois des taxes affectées, et emploient leurs propres agents.</p>
<div class="carte" data-cle>
  <p class="grand-chiffre">${surligne(eurLisible(totalScsp))}</p>
  <p class="sous-chiffre">de subventions pour charges de service public versées par l’État aux opérateurs en ${ANNEE_REF} (${h(String(ops.length))} lignes du jaune budgétaire). Chaque fiche donne la part de l’opérateur sur 100 € de ce total.</p>
  <p class="aide">Ce total n’est pas publié tel quel : l’annexe « Opérateurs de l’État » donne l’exécution ${ANNEE_REF} opérateur par opérateur, sans total. ${badgeCalcule(`somme des subventions pour charges de service public exécutées en ${ANNEE_REF} (crédits de paiement), ligne par ligne du jaune budgétaire, même année`)}</p>
  <p class="source">${h(f.source)} (${h(f.millesime)})</p>
</div>
<ul class="legende-statuts" aria-label="Statuts de traçabilité">
  <li>${traitStatut('trace')}<span><strong>Tracé</strong> : opérateur nommé, un seul programme financeur</span></li>
  <li>${traitStatut('approche')}<span><strong>Approché nommé</strong> : opérateur nommé, subvention non ventilée entre ses programmes</span></li>
  <li>${traitStatut('approche')}<span><strong>Approché par catégorie</strong> : montant publié pour une catégorie (universités, ARS...)</span></li>
  <li>${traitStatut('nonpub')}<span><strong>Non publié</strong> : pas de financement publié pour ${ANNEE_REF}</span></li>
</ul>
<form id="filtres-op" class="carte">
  ${p ? `<p>Opérateurs financés par le programme ${h(p)} · <a href="${lien('/explorer/operateurs')}">voir tous les opérateurs</a></p>` : ''}
  <label for="op-q">Chercher un opérateur</label>
  <input id="op-q" type="search" autocomplete="off" value="${h(etat.q)}" />
  ${listeRecherche({ id: 'op-mission', etiquette: 'Mission', options: [], optionsHtml: `<option value="">Toutes</option>${missions.map((m) => `<option${m === etat.mission ? ' selected' : ''}>${h(m)}</option>`).join('')}` })}
  ${choix({ id: 'op-categorie', etiquette: 'Catégorie', options: [{ valeur: '', libelle: 'Toutes' }, { valeur: '__categorie', libelle: 'Catégories d’opérateurs (universités, ARS, agences de l’eau...)' }, ...statuts.map((s) => ({ valeur: s, libelle: `Statut ${s}` }))], valeur: etat.categorie })}
  ${choix({ id: 'op-tri', etiquette: 'Trier par', options: [{ valeur: 'scsp', libelle: `Subvention ${ANNEE_REF}` }, { valeur: 'financement', libelle: `Total versé par l’État ${ANNEE_REF}` }, { valeur: 'etpt', libelle: `Emplois ${ANNEE_REF}` }, { valeur: 'nom', libelle: 'Nom' }], valeur: etat.tri })}
</form>
<div id="liste-op" aria-live="polite"></div>
${idx ? `<details><summary>Limites des données</summary><ul>${limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul></details>` : ''}`

  const zone = cible.querySelector('#liste-op') as HTMLElement
  const dessiner = () => {
    const q = etat.q.toLowerCase()
    let liste = ops.filter(
      (o) =>
        (!p || (o.annees[ANNEE_REF]?.programmes_financeurs ?? []).includes(p) || o.programme_chef_de_file === p) &&
        (!etat.mission || o.mission_chef_de_file === etat.mission) &&
        (!etat.categorie || (etat.categorie === '__categorie' ? o.niveau === 'categorie' : o.statut === etat.categorie)) &&
        (!q || `${o.nom} ${o.sigle ?? ''}`.toLowerCase().includes(q)),
    )
    const cle: Record<string, (o: Operateur) => number | string> = {
      scsp: (o) => scsp(o.annees[ANNEE_REF]),
      financement: (o) => financement(o.annees[ANNEE_REF]) ?? 0,
      etpt: (o) => o.annees[ANNEE_REF]?.etpt_sous_plafond ?? 0,
      nom: (o) => o.nom,
    }
    const k = cle[etat.tri]
    liste = [...liste].sort((a, b) => (etat.tri === 'nom' ? String(k(a)).localeCompare(String(k(b)), 'fr') : Number(k(b)) - Number(k(a))))
    const visibles = liste.slice(0, etat.page * PAR_PAGE)
    zone.innerHTML = liste.length
      ? `<p>${h(String(liste.length))} opérateur${liste.length > 1 ? 's' : ''} ou catégorie${liste.length > 1 ? 's' : ''}.</p>
<ul class="lignes">${visibles
          .map((o) => {
            const s = statutOperateur(o, limites)
            const sc = scsp(o.annees[ANNEE_REF])
            return `<li><details data-id="${h(o.id)}"><summary>${h(o.nom)}${o.sigle ? ` (${h(o.sigle)})` : ''}</summary><div class="fiche"></div></details><span class="montant">${sc > 0 ? h(eurLisible(sc)) : '–'}</span><span class="dest">${traitStatut(s.statut)}<strong>${h(s.libelle)}</strong> · ${h(o.mission_chef_de_file ?? 'mission non renseignée')}${o.statut ? ` · ${h(o.statut)}` : ''}${
              sc > 0 && totalScsp > 0 ? ` · ${h(sur100((sc / totalScsp) * 100))} sur 100 € de subventions` : ''
            }${o.annees[ANNEE_REF]?.etpt_sous_plafond ? ` · ${h(entier(Math.round(o.annees[ANNEE_REF].etpt_sous_plafond!)))} emplois` : ''}</span></li>`
          })
          .join('')}</ul>
${liste.length > visibles.length ? `<button type="button" id="op-plus">Afficher ${Math.min(PAR_PAGE, liste.length - visibles.length)} de plus</button>` : ''}`
      : absent('Aucun opérateur ne correspond.')
    zone.querySelectorAll<HTMLDetailsElement>('details[data-id]').forEach((d) =>
      d.addEventListener('toggle', () => {
        const fz = d.querySelector('.fiche') as HTMLElement
        if (d.open && !fz.innerHTML) {
          const o = ops.find((x) => x.id === d.dataset.id)
          if (o) fz.innerHTML = fiche(o, totalScsp, limites)
        }
      }),
    )
    zone.querySelector('#op-plus')?.addEventListener('click', () => {
      etat.page += 1
      dessiner()
    })
  }
  const form = cible.querySelector('#filtres-op') as HTMLFormElement
  form.addEventListener('submit', (e) => e.preventDefault())
  form.addEventListener('input', (e) => {
    if ((e.target as HTMLElement).matches('.choix-filtre')) return
    etat.q = (cible.querySelector('#op-q') as HTMLInputElement).value.trim()
    etat.mission = (cible.querySelector('#op-mission') as HTMLSelectElement).value
    etat.categorie = valeurChoix(cible, 'op-categorie')
    etat.tri = valeurChoix(cible, 'op-tri') as typeof etat.tri
    etat.page = 1
    dessiner()
  })
  dessiner()
}

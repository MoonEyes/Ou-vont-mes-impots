// Le numérique de l'État (site/data/numerique_etat/) : grands projets informatiques suivis par le panorama de la
// direction interministérielle du numérique (coût estimé et durée publiés à chaque édition, ministère qui conduit le
// projet), puis les fonds de transformation numérique. Valeurs telles que publiées : les écarts entre éditions sont
// donnés sans qualificatif, une valeur non publiée reste « non publiée » (jamais 0). Aucun nom de personne : le
// « ministère porteur » du panorama est un ministère, les porteurs des fonds sont des administrations.
import { choix, listeRecherche, valeurChoix } from '../composants/choix'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { absent, badgeStatut, entier, eurLisible, h, traitStatut } from '../util'
import { enCours } from './dette'

interface Source {
  id: string
  titre: string
  producteur: string
  licence: string
  url: string
  ressource_modifiee_le?: string
  collecte_le?: string
}
interface Fonds {
  id: string
  nom: string
  millesime: string
  projets?: number
  montant_publie_eur?: number
  projets_sans_montant_publie?: number
  fitn8?: { projets: number; montant_publie_eur: number; projets_sans_montant_publie: number }
  itn7_volet1?: { projets: number; montant_publie_eur: number; projets_sans_montant_publie: number }
  arbre_etat?: { programme: string; nom_programme: string; action: string; nom_action: string }
}
interface Index {
  millesime: string
  source: string
  collecte_le: string
  avertissement: string
  sources: Source[]
  panorama: { editions: number; premiere_edition: string; derniere_edition: string; projets: number; projets_dans_la_derniere_edition: number; cout_publie_derniere_edition_meur: number; projets_sans_cout_publie_derniere_edition: number }
  fonds: Fonds[]
}
interface Edition {
  edition: string
  numero: number
  url: string
  projets: number
  cout_publie_meur: number
  projets_sans_cout_publie: number
  entrants: string[] | null
  sortants: string[] | null
  par_ministere: { ministere: string; projets: number; cout_publie_meur: number; projets_sans_cout_publie: number }[]
}
interface Editions {
  source: string
  avertissement: string
  editions: Edition[]
}
interface Evolution {
  premiere: { edition: string; valeur: number }
  derniere: { edition: string; valeur: number }
  ecart: number
  ecart_pct: number | null
  minimum: number
  maximum: number
  valeurs_publiees: number
}
interface Releve {
  edition: string
  nom: string
  ministere: string | null
  debut: string | null
  duree_ans: number | null
  duree_mention: string | null
  cout_meur: number | null
  cout_mention: string | null
  phase: string | null
  programmes: string[]
}
export interface Projet {
  id: string
  nom: string
  noms_publies: string[]
  ministere: string | null
  ministere_nom: string | null
  description: string | null
  editions: { nombre: number; premiere: string; derniere: string; dans_la_derniere_edition: boolean }
  debuts_publies: string[]
  evolution_cout_meur: Evolution | null
  evolution_duree_ans: Evolution | null
  programmes: { programme: string; dans_arbre: boolean }[]
  releves: Releve[]
}
interface Projets {
  source: string
  avertissement: string
  methode: { regles: { id: string; regle: string }[]; limites: string }
  non_rapproches: unknown[]
  projets: Projet[]
}
interface Ministeres {
  ministeres: { ministere: string; noms_publies: string[] }[]
}

const PAR_PAGE = 30
const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
const nf1 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
export const REGLE_PROJETS = 'Ordre des projets : alphabétique, d’après le dernier nom publié. Aucun classement par montant ni par écart.'
export const REGLE_MINISTERES = 'Ordre des ministères : alphabétique, d’après le nom publié.'

/** « 2025-12 » devient « décembre 2025 ». */
export const moisAnnee = (m: string) => {
  const r = /^(\d{4})-(\d{2})$/.exec(m)
  return r ? `${MOIS[Number(r[2]) - 1]} ${r[1]}` : m
}
/** Millions d'euros avec une décimale : « 496,5 M€ ». */
export const meur = (x: number) => `${nf1.format(x)} M€`
const ans = (x: number) => `${nf1.format(x)} an${Math.round(Math.abs(x) * 10) >= 20 ? 's' : ''}`
/** Écart signé, sans qualificatif : « +12,3 M€ », « −2,0 ans », « 0,0 M€ ». */
export function signe(x: number, f: (n: number) => string): string {
  const t = f(Math.abs(x))
  if (Math.abs(x) < 0.05) return f(0)
  return `${x > 0 ? '+' : '−'}${t}`
}
const pctSigne = (x: number | null) => (x === null ? '' : ` (${signe(x, (n) => `${nf1.format(n)} %`)})`)

/** Coût ou durée d'un relevé : la valeur publiée, ou la raison de son absence (jamais 0). */
export function valeurReleve(v: number | null, mention: string | null, f: (n: number) => string): string {
  if (typeof v === 'number') return f(v)
  return mention ? `non publié (${mention})` : 'non publié'
}

/** Ligne de lecture du coût estimé publié : première et dernière valeur, écart tel quel. */
export function lectureCout(p: Projet): string {
  const e = p.evolution_cout_meur
  if (!e) {
    const seul = p.releves.find((r) => typeof r.cout_meur === 'number')
    return seul ? `coût estimé publié : ${meur(seul.cout_meur!)} (${moisAnnee(seul.edition)}), une seule valeur publiée` : 'coût estimé non publié'
  }
  return `coût estimé publié : ${meur(e.premiere.valeur)} en ${moisAnnee(e.premiere.edition)}, ${meur(e.derniere.valeur)} en ${moisAnnee(e.derniere.edition)}, écart ${signe(e.ecart, meur)}${pctSigne(e.ecart_pct)}${entre(e, meur)}`
}
/** Bornes publiées quand une valeur intermédiaire sort de l'intervalle entre la première et la dernière. */
function entre(e: Evolution, f: (n: number) => string): string {
  const bas = Math.min(e.premiere.valeur, e.derniere.valeur)
  const haut = Math.max(e.premiere.valeur, e.derniere.valeur)
  return e.minimum < bas - 0.05 || e.maximum > haut + 0.05 ? ` ; valeurs publiées entre ${f(e.minimum)} et ${f(e.maximum)}` : ''
}
export function lectureDuree(p: Projet): string {
  const e = p.evolution_duree_ans
  if (!e) {
    const seul = p.releves.find((r) => typeof r.duree_ans === 'number')
    return seul ? `durée prévue publiée : ${ans(seul.duree_ans!)} (${moisAnnee(seul.edition)})` : 'durée prévue non publiée'
  }
  return `durée prévue publiée : ${ans(e.premiere.valeur)} en ${moisAnnee(e.premiere.edition)}, ${ans(e.derniere.valeur)} en ${moisAnnee(e.derniere.edition)}, écart ${signe(e.ecart, ans)}${entre(e, ans)}`
}

/** Nom complet d'un ministère d'après son sigle publié (jamais le sigle seul). */
function nommer(ministeres: Ministeres | null, projets: Projet[]) {
  const noms = new Map<string, string>()
  for (const m of ministeres?.ministeres ?? []) if (m.noms_publies.length) noms.set(m.ministere, m.noms_publies[m.noms_publies.length - 1])
  for (const p of projets) if (p.ministere && p.ministere_nom && !noms.has(p.ministere)) noms.set(p.ministere, p.ministere_nom)
  return (sigle: string | null) => (sigle ? (noms.has(sigle) ? `${noms.get(sigle)} (${sigle})` : `ministère publié sous le sigle ${sigle}`) : 'ministère non publié')
}

function fiche(p: Projet, ministere: (s: string | null) => string, urls: Map<string, string>): string {
  const progs = p.programmes.map((x) => (x.dans_arbre ? `<a href="${lien('/beneficiaires/programme', { p: x.programme })}">programme ${h(x.programme)}</a>` : `programme ${h(x.programme)}`))
  return `
${p.description ? `<p>Présentation publiée par la direction interministérielle du numérique : « ${h(p.description)} »</p>` : ''}
<p>Conduit par : ${h(ministere(p.ministere))}. Financement publié : ${progs.length ? progs.join(', ') : 'aucun programme du budget cité'}.${p.noms_publies.length > 1 ? ` Noms publiés au fil des éditions : ${h(p.noms_publies.join(', '))}.` : ''}${p.debuts_publies.length ? ` Début publié : ${h(p.debuts_publies.map(moisAnnee).join(', puis '))}.` : ''}</p>
<div class="tableau-defile"><table><caption>${h(p.nom)} : valeurs publiées dans chaque édition du panorama</caption>
<thead><tr><th scope="col">Édition</th><th scope="col" class="nombre">Coût estimé</th><th scope="col" class="nombre">Durée prévue</th><th scope="col">Phase publiée</th><th scope="col">Ministère publié</th></tr></thead>
<tbody>${p.releves
    .map(
      (r) =>
        `<tr><th scope="row">${urls.has(r.edition) ? `<a href="${h(urls.get(r.edition))}">${h(moisAnnee(r.edition))}</a>` : h(moisAnnee(r.edition))}</th><td class="nombre">${
          typeof r.cout_meur === 'number' ? h(meur(r.cout_meur)) : `${traitStatut('nonpub')}${h(valeurReleve(null, r.cout_mention, meur))}`
        }</td><td class="nombre">${h(valeurReleve(r.duree_ans, r.duree_mention, ans))}</td><td>${h(r.phase && r.phase.length < 60 ? r.phase : r.phase ? 'éléments chiffrés non publiés pendant une procédure en cours' : '–')}</td><td>${h(ministere(r.ministere))}</td></tr>`,
    )
    .join('')}</tbody></table></div>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams = new URLSearchParams()) {
  const [idx, eds, pj, mi] = await Promise.all([
    chargerSiPresent<Index>('numerique_etat/index.json'),
    chargerSiPresent<Editions>('numerique_etat/panorama/editions.json'),
    chargerSiPresent<Projets>('numerique_etat/panorama/projets.json'),
    chargerSiPresent<Ministeres>('numerique_etat/panorama/ministeres.json'),
  ])
  if (!idx || !eds || !pj) {
    cible.innerHTML = enCours('Le numérique de l’État', 'Grands projets informatiques de l’État : coût estimé, durée prévue et ministère qui les conduit.')
    return
  }
  const pano = idx.panorama
  const editions = eds.editions
  const derniere = editions[editions.length - 1]
  const urls = new Map(editions.map((e) => [e.edition, e.url]))
  const ministere = nommer(mi, pj.projets)
  const srcPano = idx.sources.find((s) => s.id === 'numerique_panorama_projets')
  const projets = pj.projets
  const programme = params.get('p') ?? ''
  const etat = { q: '', min: '', perimetre: programme ? 'tous' : 'derniere', page: 1 }
  const sigles = [...new Set(projets.map((p) => p.ministere).filter((x): x is string => !!x))]
  const optionsMin = sigles.map((s) => ({ s, nom: ministere(s) })).sort((a, b) => a.nom.localeCompare(b.nom, 'fr'))
  const parMin = [...derniere.par_ministere].map((m) => ({ ...m, nom: ministere(m.ministere) })).sort((a, b) => a.nom.localeCompare(b.nom, 'fr'))
  const fonds = (id: string) => idx.fonds.find((f) => f.id === id)
  const lignesFonds: { nom: string; f: Fonds | undefined; v?: { projets: number; montant_publie_eur: number; projets_sans_montant_publie: number } }[] = [
    { nom: 'France Relance, mise à niveau numérique de l’État et des territoires (enveloppe du ministère de la Transformation et de la Fonction publiques)', f: fonds('france_relance') },
    { nom: 'France Relance, projets nationaux de la direction interministérielle de la transformation publique (guichet FITN8)', f: fonds('ditp'), v: fonds('ditp')?.fitn8 },
    { nom: 'France Relance, fonds déconcentré pour les collectivités de la direction interministérielle de la transformation publique (guichet ITN7)', f: fonds('ditp'), v: fonds('ditp')?.itn7_volet1 },
    { nom: 'Fonds pour la transformation de l’action publique (FTAP), guichets numériques', f: fonds('ftap') },
    { nom: 'Fonds d’accélération des startups d’État et de territoires (FAST)', f: fonds('fast') },
  ]

  cible.innerHTML = `
<h1>Le numérique de l’État : grands projets et fonds</h1>
<p class="chapeau">L’État suit ses grands projets informatiques dans un panorama publié deux fois par an par la direction interministérielle du numérique. Pour chaque projet : le ministère qui le conduit, la date de début, la durée prévue et le coût estimé sur toute la durée du projet. Ici, les valeurs publiées édition après édition, et les écarts entre elles tels quels : la source n’en donne pas la raison.</p>
<ul class="cles" aria-label="Chiffres clés du panorama des grands projets numériques">
  <li class="cle-famille"><strong>${h(entier(derniere.projets))}</strong><span>grands projets suivis dans l’édition de ${h(moisAnnee(derniere.edition))}</span>${badgeStatut('trace')}</li>
  <li><strong>${h(eurLisible(derniere.cout_publie_meur * 1e6))}</strong><span>somme des coûts estimés publiés dans cette édition (${h(entier(derniere.projets_sans_cout_publie))} projet${derniere.projets_sans_cout_publie > 1 ? 's' : ''} sans coût publié), sur toute la durée des projets : ce n’est pas une dépense annuelle</span>${badgeStatut('trace')}</li>
  <li><strong>${h(entier(pano.projets))}</strong><span>projets suivis dans au moins une des ${h(entier(pano.editions))} éditions, de ${h(moisAnnee(pano.premiere_edition))} à ${h(moisAnnee(pano.derniere_edition))}</span>${badgeStatut('trace')}</li>
</ul>
<p class="source">${h(srcPano ? `${srcPano.producteur}, « ${srcPano.titre} », ${srcPano.licence}, ressource mise à jour le ${srcPano.ressource_modifiee_le ?? 'non précisé'}, collectée le ${srcPano.collecte_le ?? idx.collecte_le}` : eds.source)}${srcPano ? ` · <a href="${h(srcPano.url)}">jeu de données</a>` : ''}</p>
<ul class="legende-statuts" aria-label="Lecture des valeurs">
  <li>${traitStatut('trace')}<span><strong>Tracé</strong> : valeur publiée dans le panorama, reprise telle quelle</span></li>
  <li>${traitStatut('nonpub')}<span><strong>Non publié</strong> : coût ou durée « en cadrage » ou non communiqué ; jamais compté pour zéro</span></li>
</ul>

<h2>Édition après édition</h2>
<div class="tableau-defile"><table><caption>Grands projets numériques suivis dans chaque édition du panorama, coûts estimés en millions d’euros</caption>
<thead><tr><th scope="col">Édition</th><th scope="col" class="nombre">Projets suivis</th><th scope="col" class="nombre">Somme des coûts estimés publiés</th><th scope="col" class="nombre">Projets sans coût publié</th><th scope="col" class="nombre">Projets entrés</th><th scope="col" class="nombre">Projets sortis</th></tr></thead>
<tbody>${[...editions]
    .reverse()
    .map(
      (e) =>
        `<tr><th scope="row"><a href="${h(e.url)}">${h(moisAnnee(e.edition))}</a></th><td class="nombre">${h(entier(e.projets))}</td><td class="nombre">${h(meur(e.cout_publie_meur))}</td><td class="nombre">${h(entier(e.projets_sans_cout_publie))}</td><td class="nombre">${e.entrants ? h(entier(e.entrants.length)) : '–'}</td><td class="nombre">${e.sortants ? h(entier(e.sortants.length)) : '–'}</td></tr>`,
    )
    .join('')}</tbody></table></div>
<p class="aide">${h(eds.avertissement)} La liste des projets suivis change d’une édition à l’autre (projets entrés, projets sortis) : la somme d’une édition change donc aussi avec cette liste.</p>
<p class="source">${h(eds.source)}</p>

<h2>Projet par projet : coût estimé et durée publiés</h2>
<p>Pour chaque projet : la première et la dernière valeur publiées du coût estimé et de la durée prévue, et l’écart entre les deux. La première valeur est celle de la première édition où le projet figure (le panorama commence en ${h(moisAnnee(pano.premiere_edition))}), pas forcément l’estimation faite au lancement du projet. Un écart peut venir d’un changement de périmètre, de calendrier ou de méthode d’estimation.</p>
<form id="filtres-ne" class="carte">
  ${programme ? `<p>Projets dont le financement publié cite le programme ${h(programme)} · <a href="${lien('/explorer/numerique-etat')}">voir tous les projets</a></p>` : ''}
  <label for="ne-q">Chercher un projet</label>
  <input id="ne-q" type="search" autocomplete="off" />
  ${listeRecherche({ id: 'ne-min', etiquette: 'Ministère', options: [], optionsHtml: `<option value="">Tous</option>${optionsMin.map((o) => `<option value="${h(o.s)}">${h(o.nom)}</option>`).join('')}` })}
  ${choix({ id: 'ne-perimetre', etiquette: 'Projets', options: [{ valeur: 'derniere', libelle: `Suivis dans l’édition de ${moisAnnee(derniere.edition)}` }, { valeur: 'tous', libelle: `Tous les projets depuis ${moisAnnee(pano.premiere_edition)}` }], valeur: etat.perimetre })}
</form>
<p class="aide" data-regle-ordre>${h(REGLE_PROJETS)}</p>
<div id="liste-ne" aria-live="polite"></div>

<h2>Par ministère, dans l’édition de ${h(moisAnnee(derniere.edition))}</h2>
<div class="tableau-defile"><table><caption>Grands projets numériques par ministère qui les conduit, édition de ${h(moisAnnee(derniere.edition))}, coûts estimés en millions d’euros</caption>
<thead><tr><th scope="col">Ministère</th><th scope="col" class="nombre">Projets</th><th scope="col" class="nombre">Somme des coûts estimés publiés</th><th scope="col" class="nombre">Sans coût publié</th></tr></thead>
<tbody>${parMin
    .map((m) => `<tr><th scope="row">${h(m.nom)}</th><td class="nombre">${h(entier(m.projets))}</td><td class="nombre">${h(meur(m.cout_publie_meur))}</td><td class="nombre">${h(entier(m.projets_sans_cout_publie))}</td></tr>`)
    .join('')}</tbody></table></div>
<p class="aide" data-regle-ordre>${h(REGLE_MINISTERES)}</p>
<p class="aide">Le « ministère porteur » du panorama est le ministère qui conduit le projet, désigné par son sigle. Les périmètres des ministères changent avec les gouvernements : deux sigles successifs ne sont pas rapprochés.</p>

<h2>Les fonds de transformation numérique</h2>
<p>À côté des grands projets, l’État a financé des projets numériques plus petits par des fonds attribués sur dossier. Chaque fonds est donné avec son périmètre et sa période ; les jeux se recoupent en partie et ne s’additionnent pas entre eux ni avec le panorama.</p>
<div class="tableau-defile"><table><caption>Fonds de transformation numérique : projets et montants publiés, en euros</caption>
<thead><tr><th scope="col">Fonds</th><th scope="col">Période publiée</th><th scope="col" class="nombre">Projets</th><th scope="col" class="nombre">Montant publié</th><th scope="col" class="nombre">Projets sans montant publié</th><th scope="col">Dans le budget de l’État</th></tr></thead>
<tbody>${lignesFonds
    .filter((l) => l.f)
    .map((l) => {
      const v = l.v ?? { projets: l.f!.projets ?? 0, montant_publie_eur: l.f!.montant_publie_eur ?? 0, projets_sans_montant_publie: l.f!.projets_sans_montant_publie ?? 0 }
      const a = l.f!.arbre_etat
      return `<tr><th scope="row">${h(l.nom)}</th><td>${h(l.f!.millesime)}</td><td class="nombre">${h(entier(v.projets))}</td><td class="nombre">${h(eurLisible(v.montant_publie_eur))}</td><td class="nombre">${h(entier(v.projets_sans_montant_publie))}</td><td>${
        a ? `<a href="${lien('/beneficiaires/programme', { p: a.programme })}">programme ${h(a.programme)} « ${h(a.nom_programme)} »</a>, action « ${h(a.nom_action)} »` : '–'
      }</td></tr>`
    })
    .join('')}</tbody></table></div>
<p class="aide">Le montant publié n’additionne que les projets dont le montant figure dans la source ; les projets sans montant publié sont comptés à part, jamais pour zéro. Les porteurs de projets nommés par ces jeux sont des administrations, des établissements publics et des collectivités : aucun nom de personne n’est repris.</p>

<details><summary>Méthode, limites et sources</summary>
<p>${h(idx.avertissement)}</p>
<p>${h(pj.avertissement)}</p>
<p>Un projet peut changer de nom d’une édition à l’autre. Règles de rapprochement appliquées :</p>
<ul>${pj.methode.regles.map((r) => `<li>${h(r.regle)}</li>`).join('')}</ul>
<p>${h(pj.methode.limites)} Changements de nom non rapprochés : ${h(entier(pj.non_rapproches.length))}.</p>
<ul>${idx.sources
    .map((s) => `<li><a href="${h(s.url)}">${h(s.titre)}</a> : ${h(s.producteur)}, ${h(s.licence)}${s.ressource_modifiee_le ? `, ressource mise à jour le ${h(s.ressource_modifiee_le)}` : ''}${s.collecte_le ? `, collectée le ${h(s.collecte_le)}` : ''}.</li>`)
    .join('')}</ul>
</details>
<p class="liens-sortie"><a href="${lien('/explorer/etat')}">Le budget de l’État, sur 100 € dépensés</a> <a href="${lien('/decisions/realisations')}">Prévu et dépensé, programme par programme</a></p>`

  const zone = cible.querySelector('#liste-ne') as HTMLElement
  const dessiner = () => {
    const q = etat.q.toLowerCase()
    const liste = projets.filter(
      (p) =>
        (etat.perimetre === 'tous' || p.editions.dans_la_derniere_edition) &&
        (!etat.min || p.ministere === etat.min) &&
        (!programme || p.programmes.some((x) => x.programme === programme)) &&
        (!q || p.noms_publies.join(' ').toLowerCase().includes(q) || p.nom.toLowerCase().includes(q)),
    )
    const visibles = liste.slice(0, etat.page * PAR_PAGE)
    zone.innerHTML = liste.length
      ? `<p>${h(entier(liste.length))} projet${liste.length > 1 ? 's' : ''}.</p>
<ul class="lignes">${visibles
          .map((p) => {
            const dernier = [...p.releves].reverse().find((r) => typeof r.cout_meur === 'number')
            return `<li><details data-id="${h(p.id)}"><summary>${h(p.nom)}</summary><div class="fiche"></div></details><span class="montant">${dernier ? h(meur(dernier.cout_meur!)) : `${traitStatut('nonpub')}non publié`}</span><span class="dest">${h(ministere(p.ministere))} · ${h(lectureCout(p))} · ${h(lectureDuree(p))} · ${h(
              p.editions.dans_la_derniere_edition ? `suivi de ${moisAnnee(p.editions.premiere)} à ${moisAnnee(p.editions.derniere)}` : `suivi de ${moisAnnee(p.editions.premiere)} à ${moisAnnee(p.editions.derniere)}, absent des éditions suivantes`,
            )}</span></li>`
          })
          .join('')}</ul>
${liste.length > visibles.length ? `<button type="button" id="ne-plus">Afficher ${Math.min(PAR_PAGE, liste.length - visibles.length)} de plus</button>` : ''}`
      : absent('Aucun projet ne correspond.')
    zone.querySelectorAll<HTMLDetailsElement>('details[data-id]').forEach((d) =>
      d.addEventListener('toggle', () => {
        const fz = d.querySelector('.fiche') as HTMLElement
        if (d.open && !fz.innerHTML) {
          const p = projets.find((x) => x.id === d.dataset.id)
          if (p) fz.innerHTML = fiche(p, ministere, urls)
        }
      }),
    )
    zone.querySelector('#ne-plus')?.addEventListener('click', () => {
      etat.page += 1
      dessiner()
    })
  }
  const form = cible.querySelector('#filtres-ne') as HTMLFormElement
  form.addEventListener('submit', (e) => e.preventDefault())
  form.addEventListener('input', (e) => {
    if ((e.target as HTMLElement).matches('.choix-filtre')) return
    etat.q = (cible.querySelector('#ne-q') as HTMLInputElement).value.trim()
    etat.min = (cible.querySelector('#ne-min') as HTMLSelectElement).value
    etat.perimetre = valeurChoix(cible, 'ne-perimetre') as typeof etat.perimetre
    etat.page = 1
    dessiner()
  })
  dessiner()
}

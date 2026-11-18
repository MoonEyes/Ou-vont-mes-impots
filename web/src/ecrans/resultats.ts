// Écran « Ce que l'État s'était fixé et ce qui a été mesuré » (/decisions/resultats) : pour un programme, crédits
// dépensés, cibles et valeurs réalisées des indicateurs, année par année (site/data/performance/programmes/<p>.json) ;
// pour un département, indicateurs du baromètre des résultats de l'action publique (performance/barometre/<code>.json).
// Aucun écart, ratio, note ni classement : les valeurs sont posées côte à côte, telles que publiées.
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import type { Rendu } from '../routeur'
import { absent, badgeStatut, entier, eurLisible, h, rendreDefilables, source } from '../util'

const CHEMIN = '/decisions/resultats'

export interface Ligne {
  annee: number
  cible?: number | null
  cible_publiee?: string
  source_cible?: string
  cible_note?: string
  realise?: number | null
  realise_publie?: string
  source_realise?: string
}
export interface Serie {
  serie: string
  objectif: string | null
  indicateur: string
  sous_indicateur: string | null
  unite: string | null
  indicateur_de_contexte: boolean | null
  lignes: Ligne[]
}
export interface Credit {
  annee: number
  vote_lfi_eur: number | null
  depense_constatee_eur: number | null
  source: string | null
  trou: string | null
  autres_montants_publies: { montant_eur: number; fichier: string; source: string; millesime: string; perimetre: string; egal_a_la_depense_constatee: boolean }[]
}
export interface Correspondance {
  serie: string
  code_indicateur: string | null
  indicateur: string
  sous_indicateur: string | null
  statuts: string[]
  libelles_anterieurs: string[]
  derniere_source: string | null
  premiere_annee: number | null
  derniere_annee: number | null
  meme_code_au_rap_2025: string[] | null
}
export interface Programme {
  millesime: string
  source: string
  programme: string
  libelle: string
  mission: string
  avertissement: string
  sources: Record<string, string>
  credits: Credit[]
  credits_lecture: string
  credits_source: string
  nombre_indicateurs: number
  series: Serie[]
  correspondance: Correspondance[]
  note: string | null
}
interface Index {
  millesime: string
  source: string
  presentation: string
  avertissements: string[]
  limites: string[]
  non_exploites: { source: string; motif: string }[]
  missions: { mission: string; programmes: { programme: string; libelle: string; mission: string; nombre_indicateurs: number; annees: number[] }[] }[]
}
interface IndicateurBaro {
  id: string
  chantier: string | null
  engagement: string | null
  intitule: string
  description_publiee: string | null
  sens_publie: string | null
}
interface IndexBaro {
  millesime: string
  source: string
  presentation: string
  avertissement: string
  regle: string
  indicateurs: IndicateurBaro[]
  departements: { code: string; nom: string; nombre_indicateurs: number }[]
}
type Paire = [string, number]
interface Zone {
  millesime: string
  source: string
  code: string
  nom: string
  lecture: string
  indicateurs: { id: string; initiale: Paire[]; valeurs: Paire[]; cibles: Paire[] }[]
}

/** Texte publié d'une cible ou d'un réalisé ; rien de publié : « non publié » (jamais 0). */
export const publie = (texte: string | undefined, unite: string | null) =>
  texte === undefined ? `<span class="absent">non publié</span>` : `${h(texte)}${unite && /\d/.test(texte) ? ` <span class="aide">${h(unite)}</span>` : ''}`

/** Dépense constatée d'une année, ou la raison de son absence. */
export function depense(c: Credit | undefined): string {
  if (!c || c.depense_constatee_eur === null) return `<span class="absent">${h(c?.trou ? 'non publié en données ouvertes' : 'non publié')}</span>`
  return h(eurLisible(c.depense_constatee_eur))
}

/** Date « 2024-12-01 » en « décembre 2024 ». */
export function mois(date: string): string {
  const [a, m] = date.split('-').map(Number)
  const noms = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
  return m >= 1 && m <= 12 ? `${noms[m - 1]} ${a}` : date
}
const nombre = (x: number) => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 }).format(x)

function avertissements(av: string[]): string {
  return `<div class="carte carte-contour"><h2>Avant de lire</h2><ul>${av.map((a) => `<li>${h(a)}</li>`).join('')}</ul></div>`
}

function tableSerie(s: Serie, credits: Map<number, Credit>, k: number): string {
  const titre = s.sous_indicateur || s.indicateur
  return `<details class="carte"${k >= 15 ? ' data-plus hidden' : ''}>
  <summary>${h(titre)}${s.unite ? ` (${h(s.unite)})` : ''}</summary>
  ${s.sous_indicateur ? `<p><strong>${h(s.indicateur)}</strong></p>` : ''}
  ${s.objectif ? `<p class="aide">Objectif publié : ${h(s.objectif)}</p>` : ''}
  ${s.indicateur_de_contexte ? '<p><span class="badge">indicateur de contexte</span> : il décrit une situation, sans cible à atteindre.</p>' : ''}
  <div class="tableau-defile"><table><caption>${h(titre)} : crédits dépensés du programme, cible et valeur mesurée, par année</caption>
  <thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Crédits dépensés (programme entier)</th><th scope="col" class="nombre">Cible</th><th scope="col" class="nombre">Réalisé</th><th scope="col">Source</th></tr></thead>
  <tbody>${s.lignes
    .map(
      (l) =>
        `<tr><th scope="row">${l.annee}</th><td class="nombre">${depense(credits.get(l.annee))}</td><td class="nombre">${publie(l.cible_publiee, s.unite)}${l.cible_note ? ` <span class="aide">(${h(l.cible_note)})</span>` : ''}</td><td class="nombre">${publie(l.realise_publie, s.unite)}</td><td>${h(
          [...new Set([l.source_cible, l.source_realise].filter(Boolean))].join(', '),
        )}</td></tr>`,
    )
    .join('')}</tbody></table></div>
</details>`
}

function tableCorrespondance(c: Correspondance[]): string {
  if (!c.length) return ''
  return `<details class="carte"><summary>Indicateurs renommés ou absents des documents 2025 (${h(entier(c.length))})</summary>
<p class="aide">Un indicateur absent des documents 2025 a pu être supprimé, remplacé ou renuméroté : la source ne publie pas de table de passage. Les intitulés publiés au rapport 2025 sous le même code sont cités sans affirmer d’équivalence.</p>
<div class="tableau-defile"><table><caption>Correspondance des indicateurs du programme</caption>
<thead><tr><th scope="col">Indicateur</th><th scope="col">Constat</th><th scope="col">Années publiées</th><th scope="col">Libellés antérieurs ou même code en 2025</th></tr></thead>
<tbody>${c
    .map(
      (x) =>
        `<tr><th scope="row">${h(x.sous_indicateur || x.indicateur)}${x.code_indicateur ? ` <span class="aide">${h(x.code_indicateur)}</span>` : ''}</th><td>${h(x.statuts.join(', '))}${
          x.derniere_source ? ` <span class="aide">(dernier document : ${h(x.derniere_source)})</span>` : ''
        }</td><td>${x.premiere_annee !== null ? `${x.premiere_annee} à ${x.derniere_annee}` : ''}</td><td>${h(
          [...x.libelles_anterieurs, ...(x.meme_code_au_rap_2025 ?? []).map((l) => `rapport 2025, même code : ${l}`)].join(' ; '),
        )}</td></tr>`,
    )
    .join('')}</tbody></table></div></details>`
}

function tableCredits(d: Programme): string {
  return `<div class="tableau-defile"><table><caption>Crédits du programme ${h(d.programme)} par année (crédits de paiement)</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Voté (loi de finances initiale)</th><th scope="col" class="nombre">Dépensé</th><th scope="col">Statut</th><th scope="col">Autre montant publié pour la même année</th></tr></thead>
<tbody>${d.credits
    .map(
      (c) =>
        `<tr><th scope="row">${c.annee}</th><td class="nombre">${c.vote_lfi_eur !== null ? h(eurLisible(c.vote_lfi_eur)) : '<span class="absent">non publié</span>'}</td><td class="nombre">${depense(c)}</td><td>${badgeStatut(
          c.depense_constatee_eur !== null ? 'trace' : 'nonpub',
        )}</td><td>${c.autres_montants_publies
          .filter((a) => !a.egal_a_la_depense_constatee)
          .map((a) => `${h(eurLisible(a.montant_eur))} <span class="aide">(${h(a.perimetre)})</span>`)
          .join(' ; ')}</td></tr>`,
    )
    .join('')}</tbody></table></div>
<p class="aide">${h(d.credits_lecture)} Deux montants d’une même année aux périmètres différents sont montrés tous les deux, sans choisir.</p>
${source(d.credits_source)}`
}

async function vueProgramme(cible: HTMLElement, p: string, idx: Index | null): Promise<Rendu | void> {
  const d = await chargerSiPresent<Programme>(`performance/programmes/${p}.json`)
  if (!d) {
    cible.innerHTML = `<h1>Ce que l’État s’était fixé et ce qui a été mesuré</h1>${absent(`Pas de données de performance pour le programme ${p}.`)}<p><a href="${lien(CHEMIN)}">Choisir un autre programme</a></p>`
    return
  }
  const credits = new Map(d.credits.map((c) => [c.annee, c]))
  cible.innerHTML = `
<h1>${h(d.libelle)} : ce que l’État s’était fixé et ce qui a été mesuré</h1>
<p class="chapeau">Programme ${h(d.programme)} · mission ${h(d.mission)}. Pour chaque indicateur publié par le ministère : la cible annoncée et la valeur mesurée, année par année, à côté des crédits dépensés par le programme la même année. La page ne dit pas si l’argent a produit le résultat.</p>
${avertissements(idx?.avertissements ?? [d.avertissement])}
<p><a href="${lien(CHEMIN)}">Choisir un autre programme</a></p>
<h2>Crédits du programme</h2>
<div class="carte">${tableCredits(d)}</div>
<h2>Indicateurs : cible et réalisé</h2>
${
  d.series.length
    ? `<p>${h(entier(d.series.length))} indicateur${d.series.length > 1 ? 's' : ''} publié${d.series.length > 1 ? 's' : ''}, dans l’ordre des documents du ministère. « Non publié » : aucune valeur dans les documents ouverts pour cette année.</p>
${d.series.map((s, k) => tableSerie(s, credits, k)).join('')}
${d.series.length > 15 ? `<button type="button" id="plus-perf">Afficher les ${h(entier(d.series.length))} indicateurs</button>` : ''}`
    : absent(d.note ?? 'Aucun indicateur publié pour ce programme.')
}
${tableCorrespondance(d.correspondance)}
${source(Object.entries(d.sources).map(([k, v]) => `${k} : ${v}`).join(' ; ') || d.source, d.millesime)}
<div class="actions"><a class="bouton" href="${lien('/decisions/realisations', { p })}">Ce qui a été fait (programme ${h(p)})</a><a class="bouton" href="${lien('/beneficiaires/programme', { p })}">Le programme ${h(p)} en détail</a></div>`
  cible.querySelector('#plus-perf')?.addEventListener('click', (e) => {
    cible.querySelectorAll<HTMLElement>('details[data-plus]').forEach((x) => (x.hidden = false))
    ;(e.target as HTMLElement).remove()
  })
  rendreDefilables(cible)
  return { titre: `${d.libelle} (programme ${d.programme}) : cibles et résultats mesurés`, description: `Programme ${d.programme}, ${d.libelle} : cibles et valeurs mesurées des indicateurs de performance, année par année, à côté des crédits dépensés.` }
}

const derniere = (x: Paire[]) => (x.length ? x[x.length - 1] : null)
const paire = (x: Paire | null) => (x ? `${h(nombre(x[1]))} <span class="aide">(${h(mois(x[0]))})</span>` : '<span class="absent">non publié</span>')

async function vueDepartement(cible: HTMLElement, dep: string): Promise<Rendu | void> {
  const [bi, z, fr] = await Promise.all([
    chargerSiPresent<IndexBaro>('performance/barometre/index.json'),
    chargerSiPresent<Zone>(`performance/barometre/${dep}.json`),
    chargerSiPresent<Zone>('performance/barometre/FR.json'),
  ])
  if (!bi || !z) {
    cible.innerHTML = `<h1>Baromètre des résultats par département</h1>${absent(`Pas de données du baromètre pour le département ${dep}.`)}<p><a href="${lien(CHEMIN)}">Choisir un département</a></p>`
    return
  }
  const defs = new Map(bi.indicateurs.map((i) => [i.id, i]))
  const france = new Map((fr?.indicateurs ?? []).map((i) => [i.id, i]))
  const parChantier = new Map<string, typeof z.indicateurs>()
  for (const i of z.indicateurs) {
    const ch = defs.get(i.id)?.chantier ?? 'Chantier non précisé'
    parChantier.set(ch, [...(parChantier.get(ch) ?? []), i])
  }
  const chantiers = [...parChantier.keys()].sort((a, b) => a.localeCompare(b, 'fr'))
  cible.innerHTML = `
<h1>${h(z.nom)} (${h(z.code)}) : baromètre des résultats de l’action publique</h1>
<p class="chapeau">${h(bi.presentation)}</p>
${avertissements([bi.avertissement, bi.regle])}
<p><a href="${lien(CHEMIN)}">Choisir un autre département ou un programme</a></p>
${chantiers
  .map(
    (ch) => `<h2>${h(ch)}</h2>
${parChantier
  .get(ch)!
  .map((i) => {
    const d = defs.get(i.id)
    const f = france.get(i.id)
    return `<details class="carte"><summary>${h(d?.intitule ?? i.id)}</summary>
${d?.description_publiee ? `<p class="aide">${h(d.description_publiee)}</p>` : ''}
${d?.sens_publie ? `<p>Sens recherché publié par la DITP : ${h(d.sens_publie)}.</p>` : ''}
<div class="tableau-defile"><table><caption>${h(d?.intitule ?? i.id)} : ${h(z.nom)} et France</caption>
<thead><tr><th scope="col">Territoire</th><th scope="col" class="nombre">Valeur initiale</th><th scope="col" class="nombre">Dernière valeur publiée</th><th scope="col" class="nombre">Cible</th></tr></thead>
<tbody><tr><th scope="row">${h(z.nom)}</th><td class="nombre">${paire(derniere(i.initiale))}</td><td class="nombre">${paire(derniere(i.valeurs))}</td><td class="nombre">${paire(derniere(i.cibles))}</td></tr>
${f ? `<tr><th scope="row">France</th><td class="nombre">${paire(derniere(f.initiale))}</td><td class="nombre">${paire(derniere(f.valeurs))}</td><td class="nombre">${paire(derniere(f.cibles))}</td></tr>` : ''}</tbody></table></div>
${
  i.valeurs.length > 1
    ? `<details><summary>Toutes les valeurs publiées pour ${h(z.nom)} (${h(entier(i.valeurs.length))})</summary><div class="tableau-defile"><table><caption>Valeurs successives, ${h(z.nom)}</caption><thead><tr><th scope="col">Date</th><th scope="col" class="nombre">Valeur</th></tr></thead><tbody>${i.valeurs
        .map((v) => `<tr><th scope="row">${h(mois(v[0]))}</th><td class="nombre">${h(nombre(v[1]))}</td></tr>`)
        .join('')}</tbody></table></div></details>`
    : ''
}
</details>`
  })
  .join('')}`,
  )
  .join('')}
${z.indicateurs.length ? '' : absent('Aucune valeur départementale publiée.')}
${source(z.source, z.millesime)}
<ul class="liens-sortie"><li><a href="${lien('/local/departement', { dep: z.code })}">Les communes du département ${h(z.nom)}</a></li><li><a href="${lien(CHEMIN)}">Les indicateurs des programmes du budget de l’État</a></li></ul>`
  rendreDefilables(cible)
  return { titre: `${z.nom} (${z.code}) : baromètre des résultats de l’action publique`, description: `${z.nom} : valeur initiale, dernière valeur publiée et cible des indicateurs du baromètre des résultats de l’action publique, à côté de la France.` }
}

async function vueAccueil(cible: HTMLElement, idx: Index | null) {
  const bi = await chargerSiPresent<IndexBaro>('performance/barometre/index.json')
  const progs = (idx?.missions ?? []).flatMap((m) => m.programmes)
  cible.innerHTML = `
<h1>Ce que l’État s’était fixé et ce qui a été mesuré</h1>
<p class="chapeau">${h(
    idx?.presentation ??
      'Pour chaque programme du budget de l’État : les objectifs et indicateurs fixés par le ministère, la cible annoncée et la valeur mesurée, année par année, à côté des crédits dépensés.',
  )}</p>
${idx ? avertissements(idx.avertissements) : ''}
<h2>Par programme du budget de l’État</h2>
${
  progs.length
    ? `<label for="filtre-perf">Chercher une mission ou un programme (nom ou numéro)</label>
<input id="filtre-perf" type="search" autocomplete="off" />
<ul class="lignes" id="liste-perf">${progs
        .map(
          (p) =>
            `<li data-t="${h((p.programme + ' ' + p.libelle + ' ' + p.mission).toLowerCase())}"><a href="${lien(CHEMIN, { p: p.programme })}">${h(p.libelle)}</a><span class="montant">${h(entier(p.nombre_indicateurs))} indicateur${p.nombre_indicateurs > 1 ? 's' : ''}</span><span class="dest">Programme ${h(p.programme)} · ${h(p.mission)}${
              p.annees.length ? ` · ${p.annees[0]} à ${p.annees[p.annees.length - 1]}` : ''
            }</span></li>`,
        )
        .join('')}</ul>
<p class="aide">Ordre : missions par ordre alphabétique, puis programmes par numéro. Aucun classement par résultat.</p>`
    : absent('Indicateurs de performance en cours d’intégration.')
}
<h2>Par département : baromètre des résultats de l’action publique</h2>
${
  bi
    ? `<p>${h(bi.presentation)}</p>
<label for="choix-dep-perf">Choisir un département</label>
<select id="choix-dep-perf"><option value="">Département…</option>${bi.departements.map((d) => `<option value="${h(d.code)}">${h(d.code)} ${h(d.nom)}</option>`).join('')}</select>
<ul class="liste-colonnes">${bi.departements.map((d) => `<li><a href="${lien(CHEMIN, { dep: d.code })}">${h(d.nom)} (${h(d.code)})</a></li>`).join('')}</ul>
${source(bi.source, bi.millesime)}`
    : absent('Baromètre en cours d’intégration.')
}
${
  idx
    ? `<h2>Ce que la page ne montre pas</h2><ul>${[...idx.limites, ...idx.non_exploites.filter((n) => !/sécurité sociale/i.test(n.source)).map((n) => `${n.source} : ${n.motif}`)].map((l) => `<li>${h(l)}</li>`).join('')}</ul>${source(idx.source, idx.millesime)}`
    : ''
}
<ul class="liens-sortie"><li><a href="${lien('/decisions/realisations')}">Ce qui a été fait, programme par programme</a></li><li><a href="${lien('/decisions/votes')}">Votes et mouvements de crédits</a></li></ul>`
  const f = cible.querySelector<HTMLInputElement>('#filtre-perf')
  f?.addEventListener('input', () => {
    const q = f.value.trim().toLowerCase()
    cible.querySelectorAll<HTMLElement>('#liste-perf li').forEach((li) => {
      li.hidden = !!q && !(li.dataset.t ?? '').includes(q)
    })
  })
  const s = cible.querySelector<HTMLSelectElement>('#choix-dep-perf')
  s?.addEventListener('change', () => {
    if (s.value) location.hash = lien(CHEMIN, { dep: s.value })
  })
}

export async function rendre(cible: HTMLElement, params: URLSearchParams): Promise<Rendu | void> {
  const p = params.get('p')
  const dep = params.get('dep')
  const idx = await chargerSiPresent<Index>('performance/index.json')
  if (p && /^\d{3}$/.test(p)) return vueProgramme(cible, p, idx)
  if (dep && /^(\d{2,3}|2[AB]|FR)$/.test(dep)) return vueDepartement(cible, dep)
  return vueAccueil(cible, idx)
}

/**
 * Bloc de la fiche programme (/beneficiaires/programme) : dernière année où cible et réalisé sont publiés, quelques
 * indicateurs côte à côte avec les crédits dépensés la même année, et le lien vers la vue complète.
 */
export async function blocProgramme(p: string): Promise<string> {
  const d = await chargerSiPresent<Programme>(`performance/programmes/${p}.json`)
  if (!d) return ''
  const titre = '<h2>Ce que l’État s’était fixé et ce qui a été mesuré</h2>'
  const plus = `<p><a href="${lien(CHEMIN, { p })}">Tous les indicateurs du programme ${h(p)}, année par année</a></p>`
  if (!d.series.length) return `${titre}${absent(d.note ?? 'Aucun indicateur publié pour ce programme.')}${plus}`
  const avecLesDeux = d.series.flatMap((s) => s.lignes.filter((l) => l.cible_publiee !== undefined && l.realise_publie !== undefined).map((l) => ({ s, l })))
  const annee = Math.max(...avecLesDeux.map((x) => x.l.annee), -Infinity)
  const choix = avecLesDeux.filter((x) => x.l.annee === annee).slice(0, 6)
  const c = d.credits.find((x) => x.annee === annee)
  return `${titre}
<div class="carte">
<p class="avertissement">${h(d.avertissement)}</p>
${
  choix.length
    ? `<p>Crédits dépensés par le programme en ${annee} : ${depense(c)}${c?.source ? ` <span class="aide">(${h(c.source)})</span>` : ''}.</p>
<div class="tableau-defile"><table><caption>Cible et valeur mesurée en ${annee}, quelques indicateurs du programme ${h(p)}</caption>
<thead><tr><th scope="col">Indicateur</th><th scope="col" class="nombre">Cible ${annee}</th><th scope="col" class="nombre">Réalisé ${annee}</th><th scope="col">Source</th></tr></thead>
<tbody>${choix
        .map(
          ({ s, l }) =>
            `<tr><th scope="row">${h(s.sous_indicateur || s.indicateur)}</th><td class="nombre">${publie(l.cible_publiee, s.unite)}</td><td class="nombre">${publie(l.realise_publie, s.unite)}</td><td>${h(
              [...new Set([l.source_cible, l.source_realise].filter(Boolean))].join(', '),
            )}</td></tr>`,
        )
        .join('')}</tbody></table></div>`
    : `<p>${h(entier(d.series.length))} indicateurs publiés, sans année où cible et valeur mesurée figurent toutes les deux.</p>`
}
${plus}
</div>`
}

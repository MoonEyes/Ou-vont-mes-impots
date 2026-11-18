// L'État actionnaire (site/data/etat_actionnaire/, produit par pipeline/etat_actionnaire.py) : les entreprises dont
// l'État est actionnaire, ce qu'il en reçoit (dividendes), ce qu'il y apporte (opérations en capital), ce qu'il vend
// (cessions) et la valeur publiée de ses participations, année par année.
// Règles reprises des données : flux bruts sans qualification ; deux sources ou deux périmètres ne s'additionnent
// jamais ; un écart entre sources est montré sans être tranché ; chaque montant porte son année, sa source et son
// statut (tracé, approché, non publié). Seules des personnes morales vérifiées au répertoire Sirene sont nommées.
import { mdCourt } from '../composants/caisses'
import { partPersonnelle } from '../composants/hub'
import { chargerSiPresent } from '../donnees'
import { absent, badgeStatut, barres, entier, eur2, eurLisible, h, md, type Statut, STATUTS, source, sur100, surligne, traitStatut } from '../util'
import { enCours } from './dette'

type ParAnnee = Record<string, Record<string, number>>
interface Ligne {
  code: string
  libelle: string
  par_annee: ParAnnee
}
interface Citation {
  page: number
  texte: string
}
interface Releve {
  date: string
  annee: number
  source: string
  url: string
  citations: Citation[]
  note?: string
  valeur_md?: number
  valeur_cotee_md?: number
  entreprises?: number
  entreprises_cotees?: number
  entites?: number
}
export interface Index {
  millesime: string
  source: string
  avertissement: string
  collecte_le: string
  chiffres_cles: { annee: number; dividendes_eur: number | null; depenses_programme_731_eur: number | null; societes_controlees: { annee: number; nombre: number } }
  valeur_portefeuille: {
    definition: string
    agence: {
      producteur: string
      perimetre: string
      methode: string
      methode_citation: { source: string; page: number; texte: string }
      statut: string
      serie: Releve[]
      cotees_fin_2025: Releve & { statut: string }
    }
    bilan_etat: Releve & {
      producteur: string
      perimetre: string
      methode: string
      statut: string
      entites_controlees_md: number
      entites_non_controlees_md: number
      entites_controlees: number
      entites_non_controlees: number
    }
  }
  sources: { id: string; titre: string; url: string; licence: string }[]
  sources_inaccessibles: { source: string; motif: string; constate_le: string }[]
  limites: string[]
}
export interface Flux {
  millesime: string
  source: string
  avertissement: string
  dividendes: {
    definition: string
    lignes: Ligne[]
    total: ParAnnee
    serie_longue: { source: string; perimetre: string; annees: number[]; numeraire_md: number[]; actions_md: number[]; total_md: number[]; statuts: Record<string, string> }
  }
  compte: {
    nom: string
    recettes: { lignes: (Ligne & { nature: string })[]; total: ParAnnee; note: string }
    depenses: {
      programmes: (Ligne & { actions: Ligne[] })[]
      note: string
      composition_2025_citee: { source: string; note: string; elements: { libelle: string; annee: number; montant_eur: number; citation: string; page: number }[] }
    }
    solde: { definition: string; par_annee: Record<string, { debut_eur: number; recettes_eur: number; depenses_eur: number; fin_eur: number }> }
  }
  ecarts_entre_sources: { objet: string; annee: number; valeurs: { source: string; montant_eur: number }[]; ecart_eur: number; lecture: string }[]
}
interface Entite {
  siren: string
  denomination: string
  categorie_juridique: string
}
export interface Entites {
  source: string
  avertissement: string
  regle_personnes: string
  annees: number[]
  dividendes_par_ligne_d_execution: { ligne: string; code_execution: string; libelle_source: string; categorie_source: string | null; entite: Entite | null; execution_eur: Record<string, number | null>; note?: string }[]
  non_verifiees: { nombre: number; execution_eur: Record<string, number> }
  operations_citees: { source: string; note: string; operations: { annee: number; entite: Entite; mentions: { nature: string; montant_eur: number; citation: string; page: number }[] }[]; non_nommees: number }
}
interface Societes {
  source: string
  avertissement: string
  serie: { annee: number; societes: number; effectifs_milliers: number | null }[]
}
interface Deficit {
  source: string
  etat: { annees: Record<string, { recettes_nettes_bg_md?: number }> }
}

/** Statut publié par les données (« tracé », « approché », « non publié ») vers le code d'affichage. */
export function statutDe(s: string | undefined): Statut {
  const n = (s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
  if (n.startsWith('approch') || n.startsWith('prevision')) return 'approche'
  if (n.startsWith('non')) return 'nonpub'
  return 'trace'
}

/** Montant en euros lisible ; un petit montant garde ses centimes (0,75 € n'est pas arrondi à 1 €). */
export const montant = (x: number) => (Math.abs(x) >= 1e4 ? eurLisible(x) : eur2(x))
const cellule = (x: number | null | undefined) => (typeof x === 'number' ? h(montant(x)) : '–')

/** Forme juridique lisible d'après la catégorie juridique Insee (deux premiers chiffres). */
export function formeJuridique(cj: string): string {
  if (cj === '4160') return 'institution publique'
  const deux = cj.slice(0, 2)
  if (deux === '41') return 'établissement public'
  if (deux === '55' || deux === '56') return 'société anonyme'
  if (deux === '57') return 'société par actions simplifiée'
  if (cj.startsWith('7')) return 'personne morale de droit public'
  return 'personne morale'
}

/** « 2025-06-30 » devient « 30 juin 2025 ». */
export function dateLongue(iso: string): string {
  const [a, m, j] = iso.split('-').map(Number)
  const mois = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'][m - 1]
  return `${j === 1 ? '1er' : j} ${mois} ${a}`
}

const cleTri = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase()
export const REGLE_ENTITES = 'Ordre : alphabétique de la dénomination au répertoire Sirene, puis les lignes de la source qui ne désignent aucune entité.'

/** Entités nommées par ordre alphabétique, lignes sans entité ensuite (ordre de la nomenclature). */
export function ordreEntites<T extends { entite: Entite | null; code_execution: string }>(lignes: T[]): T[] {
  const nommees = lignes.filter((l) => l.entite).sort((a, b) => cleTri(a.entite!.denomination).localeCompare(cleTri(b.entite!.denomination), 'fr') || a.code_execution.localeCompare(b.code_execution))
  const autres = lignes.filter((l) => !l.entite).sort((a, b) => a.code_execution.localeCompare(b.code_execution))
  return [...nommees, ...autres]
}

const citer = (c: { texte: string; page: number }, titre: string) => `<li><q>${h(c.texte)}</q> <span class="aide">(${h(titre)}, page ${c.page})</span></li>`
/** Texte repris des données, commencé par une majuscule pour être affiché seul. */
const phrase = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** Les trois statuts, rapportés aux montants de cette page (motif, mot et phrase : jamais la couleur seule). */
export const LEGENDE: Record<Statut, string> = {
  trace: 'montant publié tel quel dans un document public : exécution, comptes, prévision votée ou proposée',
  approche: 'estimation publiée avec sa méthode : valeur des participations, prévision en cours d’année',
  nonpub: 'information absente des données ouvertes, par exemple l’exécution par nature d’opération',
}
const legende = () =>
  `<ul class="legende-statuts" aria-label="Statut des montants de cette page">${(['trace', 'approche', 'nonpub'] as Statut[])
    .map((s) => `<li>${traitStatut(s)}<span><strong>${STATUTS[s].libelle}</strong> : ${h(LEGENDE[s])}</span></li>`)
    .join('')}</ul>`

function blocValeur(v: Index['valeur_portefeuille']): string {
  const a = v.agence
  const b = v.bilan_etat
  const der = a.serie[a.serie.length - 1]
  const st = statutDe(a.statut)
  return `
<h2 id="valeur">La valeur des participations</h2>
<p>${h(v.definition)}</p>
<h3>Estimation de l’Agence des participations de l’État, au 30 juin de chaque année</h3>
<p>${badgeStatut(st)} ${h(phrase(a.perimetre))}. Méthode : ${h(a.methode)}.</p>
${barres(
  a.serie.map((p) => ({ nom: dateLongue(p.date), valeur: p.valeur_md ?? 0, texte: mdCourt(p.valeur_md ?? 0), detail: p.valeur_cotee_md !== undefined ? `dont sociétés cotées : ${mdCourt(p.valeur_cotee_md)}` : 'part des sociétés cotées non publiée dans ce rapport', statut: st })),
  undefined,
  'Valeur estimée du portefeuille de l’Agence des participations de l’État, en milliards d’euros',
  -1,
)}
<div class="tableau-defile"><table><caption>Valeur estimée des participations suivies par l’Agence des participations de l’État (milliards d’euros)</caption>
<thead><tr><th scope="col">Date</th><th scope="col" class="nombre">Valeur totale</th><th scope="col" class="nombre">Dont sociétés cotées</th><th scope="col" class="nombre">Entreprises</th><th scope="col">Source</th></tr></thead>
<tbody>${a.serie
    .map(
      (p) =>
        `<tr><th scope="row">${h(dateLongue(p.date))}</th><td class="nombre">${h(mdCourt(p.valeur_md ?? 0))}</td><td class="nombre">${p.valeur_cotee_md !== undefined ? h(mdCourt(p.valeur_cotee_md)) : 'non publié'}</td><td class="nombre">${p.entreprises !== undefined ? h(entier(p.entreprises)) : 'non publié'}</td><td>${h(p.source)}, page${p.citations.length > 1 ? 's' : ''} ${h([...new Set(p.citations.map((c) => c.page))].join(', '))}</td></tr>`,
    )
    .join('')}</tbody></table></div>
<p class="aide">Statut « approché » : c’est une estimation de l’agence, dont la méthode est publiée. ${h(a.methode_citation.source)}, page ${a.methode_citation.page} : <q>${h(a.methode_citation.texte)}</q></p>
${a.serie.filter((p) => p.note).map((p) => `<p class="aide">${h(dateLongue(p.date))} : ${h(p.note!)}</p>`).join('')}
<details><summary>Les phrases citées, mot pour mot</summary><ul>${a.serie.flatMap((p) => p.citations.map((c) => citer(c, p.source))).join('')}</ul></details>
<p>Au ${h(dateLongue(a.cotees_fin_2025.date))}, la valeur boursière des participations cotées de l’État est de <strong>${h(mdCourt(a.cotees_fin_2025.valeur_cotee_md ?? 0))}</strong>, pour ${h(entier(a.cotees_fin_2025.entites ?? 0))} entités suivies par l’agence. ${badgeStatut(statutDe(a.cotees_fin_2025.statut))}</p>
${source(a.cotees_fin_2025.source)}
<h3>Valeur au bilan de l’État (compte général), au ${h(dateLongue(b.date))}</h3>
<ul class="deux-chiffres" aria-label="Valeur au bilan de l’État, par catégorie d’entités"><li><strong>${h(mdCourt(b.entites_controlees_md))}</strong> pour ${h(entier(b.entites_controlees))} entités contrôlées</li><li><strong>${h(mdCourt(b.entites_non_controlees_md))}</strong> pour ${h(entier(b.entites_non_controlees))} entités non contrôlées</li></ul>
<p>Ensemble publié par le compte général : <strong>${h(mdCourt(b.valeur_md ?? 0))}</strong> pour ${h(entier(b.entites ?? 0))} entités. ${badgeStatut(statutDe(b.statut))}</p>
<p>Périmètre : ${h(b.perimetre)}. Méthode : ${h(b.methode)}.</p>
${source(`${b.producteur} : ${b.source}, page ${[...new Set(b.citations.map((c) => c.page))].join(', ')}`)}
<p class="avertissement">Deux mesures, deux périmètres, deux méthodes : l’estimation de l’agence au ${h(dateLongue(der.date))} (${h(mdCourt(der.valeur_md ?? 0))}) et la valeur au bilan de l’État au ${h(dateLongue(b.date))} (${h(mdCourt(b.valeur_md ?? 0))}) ne s’additionnent pas et ne se comparent pas terme à terme.</p>`
}

export async function rendre(cible: HTMLElement) {
  const [idx, flux, ent, soc, deficit] = await Promise.all([
    chargerSiPresent<Index>('etat_actionnaire/index.json'),
    chargerSiPresent<Flux>('etat_actionnaire/flux.json'),
    chargerSiPresent<Entites>('etat_actionnaire/entites.json'),
    chargerSiPresent<Societes>('etat_actionnaire/societes_controlees.json'),
    chargerSiPresent<Deficit>('deficit.json'),
  ])
  if (!idx || !flux || !ent) {
    cible.innerHTML = enCours('L’État actionnaire', 'Entreprises dont l’État est actionnaire, dividendes reçus, apports en capital et valeur des participations.') + partPersonnelle()
    return
  }
  const an = String(idx.chiffres_cles.annee)
  const div = flux.dividendes
  const divAn = div.total[an]?.execution_eur
  const p731 = flux.compte.depenses.programmes.find((p) => p.code === '731')
  const p732 = flux.compte.depenses.programmes.find((p) => p.code === '732')
  const capAn = p731?.par_annee[an]?.execution_eur
  const v = idx.valeur_portefeuille
  const derVal = v?.agence.serie[v.agence.serie.length - 1]
  const annees = ent.annees.map(String)
  const anneesCompte = Object.keys(flux.compte.solde.par_annee).sort()
  const cessions = flux.compte.recettes.lignes.find((l) => l.nature === 'cession')
  const versementBG = flux.compte.recettes.lignes.find((l) => l.nature === 'versement_budget_general')

  // Chiffre clé : dividendes de l'année rapportés aux recettes nettes du budget général de la même année (même comptabilité budgétaire).
  const base = deficit?.etat.annees[`Exécution ${an}`]?.recettes_nettes_bg_md
  const part = typeof divAn === 'number' && typeof base === 'number' && base > 0 ? (divAn / (base * 1e9)) * 100 : null

  const lignesEnt = ordreEntites(ent.dividendes_par_ligne_d_execution)
  const notes = lignesEnt.filter((l) => l.note && l.entite)
  const serie = div.serie_longue
  const derSoc = soc?.serie[soc.serie.length - 1]

  cible.innerHTML = `
<h1>L’État actionnaire</h1>
<p class="chapeau">L’État détient des parts d’entreprises et d’établissements publics. Cette page montre, année par année, ce qu’il en reçoit (dividendes), ce qu’il y apporte (augmentations de capital et autres opérations en capital), ce qu’il vend (cessions) et la valeur publiée de ces participations, avec l’année, la source et le statut de chaque montant. Elle ne montre pas les subventions ni les commandes publiques reçues par ces entreprises (voir <a href="#/beneficiaires">Qui reçoit l’argent</a>). Elle ne porte aucune appréciation sur ces opérations.</p>
<ul class="cles" aria-label="Chiffres clés de l’État actionnaire">
  ${typeof divAn === 'number' ? `<li class="cle-famille"><strong>${h(md(divAn / 1e9))}</strong><span>de dividendes et recettes assimilées reçus par le budget de l’État en ${h(an)}</span>${badgeStatut('trace')}</li>` : ''}
  ${typeof capAn === 'number' ? `<li><strong>${h(md(capAn / 1e9))}</strong><span>versés en opérations en capital en ${h(an)} (augmentations de capital, achats de titres, autres investissements)</span>${badgeStatut('trace')}</li>` : ''}
  ${derVal ? `<li><strong>${h(mdCourt(derVal.valeur_md ?? 0))}</strong><span>valeur estimée des ${h(entier(derVal.entreprises ?? 0))} entreprises suivies par l’Agence des participations de l’État, au ${h(dateLongue(derVal.date))}</span>${badgeStatut(statutDe(v.agence.statut))}</li>` : ''}
</ul>
${legende()}
${
  typeof divAn === 'number'
    ? `<div class="carte" data-cle>
  <p>Dividendes et recettes assimilées reçus par le budget général en ${h(an)} :</p>
  <p class="grand-chiffre">${part !== null ? surligne(md(divAn / 1e9)) : h(md(divAn / 1e9))}</p>
  ${part !== null ? `<p class="sous-chiffre">soit ${h(sur100(part))} sur 100 € des recettes nettes du budget général de la même année (${h(md(base!))}).</p>` : ''}
  ${source(`Dividendes : ${flux.source}. Recettes nettes du budget général : ${deficit?.source ?? 'non disponible'}`, `exécution ${an}`)}
</div>`
    : absent('Dividendes de la dernière année : non publiés.')
}

<h2>Les entreprises dont l’État est actionnaire</h2>
<p>Trois publications comptent les participations de l’État, chacune sur son périmètre : les nombres ne s’additionnent pas.</p>
<div class="tableau-defile"><table><caption>Nombre de participations de l’État selon la source</caption>
<thead><tr><th scope="col">Source et périmètre</th><th scope="col" class="nombre">Nombre</th><th scope="col">Date</th><th scope="col">Statut</th></tr></thead>
<tbody>
${derVal?.entreprises !== undefined ? `<tr><th scope="row">Agence des participations de l’État : entreprises de son périmètre${derVal.entreprises_cotees !== undefined ? `, dont ${h(entier(derVal.entreprises_cotees))} cotées` : ''}</th><td class="nombre">${h(entier(derVal.entreprises))}</td><td>${h(dateLongue(derVal.date))}</td><td>${badgeStatut('trace')}</td></tr>` : ''}
${v ? `<tr><th scope="row">Compte général de l’État : ${h(entier(v.bilan_etat.entites_controlees))} entités contrôlées et ${h(entier(v.bilan_etat.entites_non_controlees))} non contrôlées, établissements publics compris</th><td class="nombre">${h(entier(v.bilan_etat.entites ?? 0))}</td><td>${h(dateLongue(v.bilan_etat.date))}</td><td>${badgeStatut('trace')}</td></tr>` : ''}
${derSoc ? `<tr><th scope="row">Insee : sociétés contrôlées majoritairement par l’État, hors filiales à l’étranger</th><td class="nombre">${h(entier(derSoc.societes))}</td><td>fin ${h(String(derSoc.annee))}</td><td>${badgeStatut('trace')}</td></tr>` : ''}
</tbody></table></div>
${soc ? `<p class="aide">${h(soc.avertissement)}</p>` : ''}

<h3>Les entités qui versent des dividendes au budget de l’État</h3>
<p>${h(ent.regle_personnes)}</p>
<div class="tableau-defile"><table><caption>Dividendes versés au budget général par entité, en euros (exécution ${h(annees.join(', '))})</caption>
<thead><tr><th scope="col">Entité</th><th scope="col">Catégorie dans la source</th>${annees.map((a) => `<th scope="col" class="nombre">${h(a)}</th>`).join('')}</tr></thead>
<tbody>${lignesEnt
    .map((l) => {
      const nom = l.entite ? `${h(l.entite.denomination)}<br><span class="aide">${h(formeJuridique(l.entite.categorie_juridique))}, SIREN ${h(l.entite.siren)}</span>` : `${h(l.libelle_source)}<br><span class="aide">ligne sans entité désignée</span>`
      return `<tr><th scope="row">${nom}</th><td>${h(l.categorie_source ?? 'non précisée')}</td>${annees.map((a) => `<td class="nombre">${cellule(l.execution_eur[a])}</td>`).join('')}</tr>`
    })
    .join('')}${
    ent.non_verifiees.nombre > 0
      ? `<tr><th scope="row">${h(entier(ent.non_verifiees.nombre))} lignes dont l’entité n’est pas vérifiée (regroupées, sans nom)</th><td>–</td>${annees.map((a) => `<td class="nombre">${cellule(ent.non_verifiees.execution_eur[a])}</td>`).join('')}</tr>`
      : ''
  }</tbody></table></div>
<p class="aide" data-regle-ordre>${h(REGLE_ENTITES)}</p>
<p class="aide">« – » : aucune ligne publiée pour cette entité cette année-là (ce n’est pas un zéro). Tous ces montants sont constatés à l’exécution : ${badgeStatut('trace')}</p>
${notes.map((l) => `<p class="aide"><strong>${h(l.entite!.denomination)}</strong> : ${h(l.note!)}</p>`).join('')}
${source(ent.source)}
<p class="aide">${h(ent.avertissement)}</p>

<h2>Ce que l’État reçoit : les dividendes</h2>
<p>${h(div.definition)}</p>
<div class="tableau-defile"><table><caption>Dividendes et recettes assimilées du budget général, en euros (exécution)</caption>
<thead><tr><th scope="col">Ligne de recette</th>${annees.map((a) => `<th scope="col" class="nombre">${h(a)}</th>`).join('')}</tr></thead>
<tbody>${div.lignes.map((l) => `<tr><th scope="row">${h(l.code)} : ${h(l.libelle)}</th>${annees.map((a) => `<td class="nombre">${cellule(l.par_annee[a]?.execution_eur)}</td>`).join('')}</tr>`).join('')}
<tr><th scope="row">Ensemble des trois lignes</th>${annees.map((a) => `<td class="nombre">${cellule(div.total[a]?.execution_eur)}</td>`).join('')}</tr></tbody></table></div>
${typeof div.total[an]?.plf_eur === 'number' ? `<p>Prévu par le projet de loi de finances pour ${h(an)} : ${h(montant(div.total[an].plf_eur))} ${badgeStatut('trace')}.</p>` : ''}
${source(`Exécution : annexes des PLRG (data.economie.gouv.fr) ; prévision : jeux des lois de finances`, `${annees[0]} à ${annees[annees.length - 1]}`)}
<h3>Une autre série : les dividendes perçus par l’État actionnaire, ${h(String(serie.annees[0]))} à ${h(String(serie.annees[serie.annees.length - 1]))}</h3>
<p>${h(phrase(serie.perimetre))}.</p>
${barres(
  serie.annees.map((a, i) => ({
    nom: String(a),
    valeur: serie.total_md[i],
    texte: md(serie.total_md[i]),
    detail: `en numéraire ${md(serie.numeraire_md[i])}, en actions ${md(serie.actions_md[i])}${serie.statuts[String(a)] ? ` · ${serie.statuts[String(a)]}` : ''}`,
    statut: (serie.statuts[String(a)] ? 'approche' : 'trace') as Statut,
  })),
  undefined,
  'Dividendes perçus par l’État actionnaire, en milliards d’euros',
  -1,
)}
${source(serie.source)}

<h2>Ce que l’État apporte : les opérations en capital</h2>
<p>${h(flux.compte.depenses.note)}</p>
${
  p731
    ? `<div class="tableau-defile"><table><caption>Programme 731 « ${h(p731.libelle)} », en euros</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Prévu (loi de finances initiale)</th><th scope="col" class="nombre">Crédits ouverts</th><th scope="col" class="nombre">Dépensé</th></tr></thead>
<tbody>${anneesCompte.map((a) => `<tr><th scope="row">${h(a)}</th><td class="nombre">${cellule(p731.par_annee[a]?.lfi_plrg_eur)}</td><td class="nombre">${cellule(p731.par_annee[a]?.credits_ouverts_eur)}</td><td class="nombre">${cellule(p731.par_annee[a]?.execution_eur)}</td></tr>`).join('')}</tbody></table></div>`
    : absent('Programme 731 : données non disponibles.')
}
${
  p731
    ? `<h3>Par nature d’opération, en prévision</h3>
<ul class="lignes">${p731.actions
        .map(
          (a) =>
            `<li><span>${h(a.libelle)}</span><span class="montant">${cellule(a.par_annee['2026']?.plf_eur)}</span><span class="dest">prévu pour 2026 (projet de loi de finances) ; ${typeof a.par_annee['2025']?.lfi_eur === 'number' ? `${h(montant(a.par_annee['2025'].lfi_eur))} prévus pour 2025 (loi de finances initiale)` : 'pas de montant prévu publié pour 2025'}</span></li>`,
        )
        .join('')}</ul>
<p>${badgeStatut('nonpub')} L’exécution par nature d’opération n’est pas publiée par les annexes du projet de loi relative aux résultats de la gestion : seul le total dépensé du programme l’est.</p>`
    : ''
}
<h3>En 2025, d’après le Sénat</h3>
<ul class="lignes">${flux.compte.depenses.composition_2025_citee.elements
    .map((e) => `<li><span>${h(e.libelle)}</span><span class="montant">${h(montant(e.montant_eur))}</span><span class="dest"><q>${h(e.citation)}</q> (page ${e.page})</span></li>`)
    .join('')}</ul>
<p class="aide">${h(flux.compte.depenses.composition_2025_citee.note)}</p>
<h3>Opérations de 2025 citées par entreprise</h3>
<ul class="lignes">${ent.operations_citees.operations
    .map(
      (o) =>
        `<li><span>${h(o.entite.denomination)}</span><span class="montant">${o.mentions.length} mention${o.mentions.length > 1 ? 's' : ''}</span><span class="dest">${o.mentions
          .map((m) => `${h(m.nature)} : ${h(montant(m.montant_eur))}, <q>${h(m.citation)}</q> (page ${m.page})`)
          .join(' ; ')}</span></li>`,
    )
    .join('')}</ul>
<p class="aide">${h(ent.operations_citees.note)}</p>
${source(ent.operations_citees.source)}
${
  p732
    ? `<h3>Programme 732 « ${h(p732.libelle)} »</h3>
<p>Dépensé : ${anneesCompte.map((a) => `${h(a)} : ${cellule(p732.par_annee[a]?.execution_eur)}`).join(' ; ')} ${badgeStatut('trace')}. Ces crédits remboursent de la dette : ils ne sont pas des apports aux entreprises.</p>`
    : ''
}

<h2>Ce que l’État vend : les cessions</h2>
${
  cessions
    ? `<p>${h(cessions.libelle)} (ligne ${h(cessions.code)} des recettes du compte).</p>
<ul class="lignes">${anneesCompte
        .map((a) => `<li><span>${h(a)}</span><span class="montant">${cellule(cessions.par_annee[a]?.execution_eur)}</span><span class="dest">encaissé ${badgeStatut('trace')}${typeof cessions.par_annee[a]?.lfi_eur === 'number' ? ` ; prévu en loi de finances initiale : ${h(montant(cessions.par_annee[a].lfi_eur))}` : ''}</span></li>`)
        .join('')}${
        typeof cessions.par_annee['2026']?.plf_eur === 'number'
          ? `<li><span>2026</span><span class="montant">${h(montant(cessions.par_annee['2026'].plf_eur))}</span><span class="dest">prévision du projet de loi de finances ${badgeStatut('trace')}</span></li>`
          : ''
      }</ul>
<p class="aide">Les cessions ne sont pas publiées par entreprise en données ouvertes.</p>`
    : absent('Cessions : données non disponibles.')
}

<h2>Le compte « ${h(flux.compte.nom)} », année par année</h2>
<p>${h(phrase(flux.compte.solde.definition))}.</p>
<div class="tableau-defile"><table><caption>Compte d’affectation spéciale « ${h(flux.compte.nom)} », en euros (exécution)</caption>
<thead><tr><th scope="col">Poste</th>${anneesCompte.map((a) => `<th scope="col" class="nombre">${h(a)}</th>`).join('')}</tr></thead>
<tbody>
<tr><th scope="row">Solde en début d’année</th>${anneesCompte.map((a) => `<td class="nombre">${cellule(flux.compte.solde.par_annee[a].debut_eur)}</td>`).join('')}</tr>
<tr><th scope="row">Recettes</th>${anneesCompte.map((a) => `<td class="nombre">${cellule(flux.compte.solde.par_annee[a].recettes_eur)}</td>`).join('')}</tr>
${versementBG ? `<tr><th scope="row">dont versement du budget général</th>${anneesCompte.map((a) => `<td class="nombre">${cellule(versementBG.par_annee[a]?.execution_eur)}</td>`).join('')}</tr>` : ''}
<tr><th scope="row">Dépenses</th>${anneesCompte.map((a) => `<td class="nombre">${cellule(flux.compte.solde.par_annee[a].depenses_eur)}</td>`).join('')}</tr>
<tr><th scope="row">Solde en fin d’année</th>${anneesCompte.map((a) => `<td class="nombre">${cellule(flux.compte.solde.par_annee[a].fin_eur)}</td>`).join('')}</tr>
</tbody></table></div>
<p class="aide">${h(flux.compte.recettes.note)} Le versement du budget général au compte est un mouvement interne à l’État.</p>
${source(flux.source, flux.millesime)}

${v ? blocValeur(v) : absent('Valeur des participations : non publiée dans les fichiers du site.')}

<h2>Écarts entre sources</h2>
${
  flux.ecarts_entre_sources.length
    ? `<ul class="lignes">${flux.ecarts_entre_sources
        .map((e) => `<li><span>${h(e.objet)}</span><span class="montant">écart ${h(montant(Math.abs(e.ecart_eur)))}</span><span class="dest">${e.valeurs.map((x) => `${h(montant(x.montant_eur))} selon ${h(x.source)}`).join(' ; ')}. ${h(e.lecture)}</span></li>`)
        .join('')}</ul>`
    : '<p>Aucun écart publié.</p>'
}

<p class="avertissement">${h(idx.avertissement)}</p>
<details><summary>Limites des données</summary><ul>${idx.limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul></details>
<details><summary>Sources (${h(String(idx.sources.length))}) et source inaccessible</summary>
<ul>${idx.sources.map((s) => `<li><a href="${h(s.url)}" rel="noopener noreferrer">${h(s.titre)}</a> (${h(s.licence)})</li>`).join('')}</ul>
<ul>${idx.sources_inaccessibles.map((s) => `<li>${h(s.source)} : ${h(s.motif)}, constaté le ${h(s.constate_le)}.</li>`).join('')}</ul>
<p class="aide">Données collectées le ${h(idx.collecte_le)}. ${h(idx.millesime)}.</p>
</details>
<p class="liens-sortie"><a href="#/explorer/etat">Le budget de l’État, sur 100 € dépensés</a> <a href="#/explorer/recettes">D’où vient l’argent : les recettes</a> <a href="#/explorer/secu">Les prestations versées aux ménages : Sécurité sociale</a></p>
${partPersonnelle()}`
}

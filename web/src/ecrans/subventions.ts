// Écran « Les subventions de l'État et de ses opérateurs » (/beneficiaires/subventions).
// Complète « Qui reçoit l'argent » (une année, un programme) : séries par année, par organisme qui attribue
// (ministère ou opérateur), par type de bénéficiaire, et recherche d'un organisme.
// Données : site/data/subventions/ (conventions de subvention, pipeline/subventions.py) et
// site/data/associations/ (liste annexée au projet de loi de finances, pipeline/associations.py).
// Seules des personnes morales sont nommées ; le reste est affiché agrégé, comme les fichiers le publient.
// Les deux familles de sources se recouvrent : montrées côte à côte, jamais additionnées.
import { listeRecherche } from '../composants/choix'
import { chargerSiPresent, listeProgrammes, viderCache } from '../donnees'
import { lien } from '../routeur'
import { absent, annoncer, appliquerLargeurs, badgeStatut, barres, entier, eurLisible, h, source, sur100, surligne } from '../util'

// ---------- Types des fichiers lus ----------
interface Montant {
  nombre: number
  montant_eur: number
}
interface SourceSubv {
  id: string
  titre: string
  attribuant: string
  producteur: string
  page: string
  licence: string
  millesime: string
  rattachement: { type: string; programmes?: string[]; operateur?: string; programme_chef_de_file?: string; note?: string }
  additionne: boolean
  inclus_dans: string | null
  annees: number[]
  conventions: number
  lignes_montant_non_communique: number
  total_eur: number
  montant_retire_des_totaux_eur?: number
  nommes: Montant
  agrege_confidentialite: { montant_eur: number; part_pct: number }
  fichier: string
}
interface IndexSubv {
  millesime: string
  source: string
  collecte_le?: string
  note: string
  limites: string[]
  totaux: { total_additionne_eur: number; nommes_additionnes: Montant; agrege_confidentialite: { montant_eur: number; part_pct: number } }
  sources: SourceSubv[]
  recouvrements: { source: string; autre_source: string; lecture: string }[]
  sources_inaccessibles: unknown[]
}
interface AnneesSubv {
  sources_additionnees: string[]
  annees: { annee: number; total_additionne_eur: number; conventions: number; par_source: Record<string, { montant_eur: number; conventions: number; lignes_montant_non_communique: number }> }[]
}
interface Top {
  siren: string
  denomination: string
  categorie_juridique: string
  montant_eur: number
  conventions?: number
  sources?: string[]
}
interface Exclus {
  montant_eur: number
  lignes?: number
  dont_personnes_physiques_eur?: number
  dont_sans_siren_eur?: number
  dont_siren_introuvable_eur?: number
  dont_nom_de_personne_possible_eur?: number
}
interface Groupe {
  total_eur: number
  top: Top[]
  autres_personnes_morales?: Montant
  exclus_personnes_physiques_ou_non_identifies?: Exclus
}
interface Attribuant {
  millesime: string
  source: string
  licence?: string
  par_annee: { annee: number; montant_eur: number; conventions: number; lignes_montant_non_communique: number; montant_nomme_eur: number }[]
  beneficiaires?: Groupe
  titres?: { top: { titre: string; montant_eur: number; lignes: number }[]; autres_titres?: Montant; titres_non_nommes?: Montant }
}
type Valeur = number | 'nc' | null
interface AnneeJaune {
  annee: number
  annee_credits: number
  statut: 'publie' | 'nc'
  total_source_eur: number | 'nc'
  nommes_eur: number | 'nc'
  exclus_personnes_physiques_ou_non_identifies_eur: number | 'nc'
  associations_nommees: number | 'nc'
  raison?: string
  correction?: { raison?: string }
}
interface IndexAssoc {
  millesime: string
  source: string
  note: string
  annees: AnneeJaune[]
  programmes: { programme: string; libelle: string; fichiers: string[]; associations_nommees: number; totaux_eur: Valeur[] }[]
  sources_inaccessibles?: { annee?: number; constat?: string }[]
}
interface ProgrammeJaune {
  programme: string
  libelle: string
  annees: number[]
  annees_credits: number[]
  lignes: [string, string, string, number, Valeur[]][]
}

// ---------- Règles pures (testées) ----------

/** Type de bénéficiaire d'après la catégorie juridique SIRENE (nomenclature de l'Insee, niveaux 1 et 2). */
export type TypeBeneficiaire = 'associations' | 'entreprises' | 'collectivites' | 'publics' | 'autres'
export const TYPES: Record<TypeBeneficiaire, string> = {
  associations: 'Associations et fondations',
  entreprises: 'Entreprises et sociétés',
  collectivites: 'Collectivités locales et leurs groupements',
  publics: 'Établissements publics et services de l’État',
  autres: 'Autres organismes (mutuelles, syndicats, organismes étrangers...)',
}
export function typeBeneficiaire(cj: string): TypeBeneficiaire {
  const c = String(cj ?? '')
  if (/^9[23]/.test(c)) return 'associations' // 92xx associations, 93xx fondations
  if (/^[56]/.test(c)) return 'entreprises' // sociétés commerciales et civiles
  if (/^72/.test(c) || /^73[45]/.test(c)) return 'collectivites' // collectivités, intercommunalités, syndicats mixtes
  if (/^(4|71|73|74)/.test(c)) return 'publics' // établissements publics, administrations de l'État
  return 'autres'
}

/** Texte comparable : sans accents, en capitales, ponctuation réduite à des espaces. */
export const normaliser = (s: string) =>
  String(s ?? '')
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, ' ')
    .trim()

/** Un organisme correspond à la recherche : numéro SIREN exact (9 chiffres) ou tous les mots dans la dénomination. */
export function correspond(q: string, siren: string, denomination: string): boolean {
  const n = normaliser(q)
  if (!n) return false
  const chiffres = n.replace(/ /g, '')
  if (/^\d{9}$/.test(chiffres)) return siren === chiffres
  const d = ` ${normaliser(denomination)} `
  return n.split(' ').every((m) => d.includes(m))
}

const LOT = 10
const MAX_RESULTATS = 50
const REGLE_ORDRE = 'Classés par montant décroissant, puis par nom.'

// ---------- Aides d'affichage ----------
const nb = (x: number | 'nc' | null | undefined) => (typeof x === 'number' ? x : null)
const montant = (x: number | 'nc' | null | undefined) => (typeof x === 'number' ? eurLisible(x) : x === 'nc' ? 'non communiqué' : '–')
const traceAgrege = '<span class="badge">Agrégé, jamais nommé</span>'
const lienExterne = (url: string, texte: string) => `<a href="${h(url)}" rel="noopener noreferrer">${h(texte)}</a>`

function rattachement(s: SourceSubv): string {
  const r = s.rattachement
  if (r.type === 'operateur') return `ressources propres de l’opérateur (${r.operateur ?? ''}), rattaché au programme ${r.programme_chef_de_file ?? ''} du budget de l’État`
  if (r.type === 'hors_budget_etat') return r.note ?? 'hors budget de l’État'
  if (r.type === 'programme_source') return 'programme du budget de l’État publié ligne par ligne'
  return `programme${(r.programmes ?? []).length > 1 ? 's' : ''} ${(r.programmes ?? []).join(' et ')} du budget de l’État`
}

function statutSource(s: SourceSubv, tous: SourceSubv[]): string {
  if (s.additionne) return `${badgeStatut('trace')} additionné au total`
  const autre = tous.find((x) => x.id === s.inclus_dans)
  return `${badgeStatut('trace')} détaille ${h(autre?.attribuant ?? s.inclus_dans ?? 'une autre source')} : publié à part, jamais additionné`
}

function lignesExclus(e: Exclus | undefined): string[] {
  if (!e || !e.montant_eur) return []
  const dont = [
    e.dont_personnes_physiques_eur ? `personnes physiques : ${eurLisible(e.dont_personnes_physiques_eur)}` : '',
    e.dont_sans_siren_eur ? `identifiant absent ou illisible : ${eurLisible(e.dont_sans_siren_eur)}` : '',
    e.dont_siren_introuvable_eur ? `identifiant absent de la base des entreprises : ${eurLisible(e.dont_siren_introuvable_eur)}` : '',
    e.dont_nom_de_personne_possible_eur ? `nom de personne possible dans la dénomination : ${eurLisible(e.dont_nom_de_personne_possible_eur)}` : '',
  ].filter(Boolean)
  return [`Personnes physiques ou bénéficiaires non identifiés, agrégés et jamais nommés : ${eurLisible(e.montant_eur)}${dont.length ? ` (dont ${dont.join(' ; ')})` : ''}`]
}

/** Répartition par type d'un groupe : seuls les organismes nommés ont un type ; le reste est montré tel quel. */
function tableTypes(g: Groupe, legende: string): string {
  const parType = new Map<TypeBeneficiaire, { montant: number; nombre: number }>()
  for (const t of g.top) {
    const k = typeBeneficiaire(t.categorie_juridique)
    const v = parType.get(k) ?? { montant: 0, nombre: 0 }
    v.montant += t.montant_eur
    v.nombre += 1
    parType.set(k, v)
  }
  const total = g.total_eur || 1
  const lignes = (Object.keys(TYPES) as TypeBeneficiaire[])
    .filter((k) => parType.has(k))
    .map((k) => ({ k, ...parType.get(k)! }))
    .sort((a, b) => b.montant - a.montant || TYPES[a.k].localeCompare(TYPES[b.k], 'fr'))
  const ligne = (nom: string, m: number, n: string, statut: string) =>
    `<tr><th scope="row">${h(nom)}</th><td class="nombre">${h(eurLisible(m))}</td><td class="nombre">${h(sur100((m / total) * 100))}</td><td class="nombre">${h(n)}</td><td>${statut}</td></tr>`
  const autres = g.autres_personnes_morales
  const exclus = g.exclus_personnes_physiques_ou_non_identifies
  return `<div class="tableau-defile"><table>
<caption>${h(legende)}</caption>
<thead><tr><th scope="col">Type de bénéficiaire</th><th scope="col" class="nombre">Montant</th><th scope="col" class="nombre">Sur 100 € du total</th><th scope="col" class="nombre">Organismes</th><th scope="col">Statut</th></tr></thead>
<tbody>${lignes.map((l) => ligne(`${TYPES[l.k]} (parmi les ${g.top.length} premiers)`, l.montant, entier(l.nombre), badgeStatut('trace'))).join('')}${
    autres && autres.nombre ? ligne('Autres personnes morales, type non réparti dans les fichiers publiés', autres.montant_eur, entier(autres.nombre), `${badgeStatut('trace')} type non publié`) : ''
  }${exclus && exclus.montant_eur ? ligne('Personnes physiques ou bénéficiaires non identifiés', exclus.montant_eur, '–', traceAgrege) : ''}</tbody>
</table></div>`
}

function tableTop(top: Top[], legende: string, nomsSources?: Map<string, string>): string {
  return `<div class="tableau-defile"><table>
<caption>${h(legende)}</caption>
<thead><tr><th scope="col">Organisme (personne morale)</th><th scope="col">Type</th>${nomsSources ? '<th scope="col">Attribué par</th>' : ''}<th scope="col" class="nombre">Montant</th></tr></thead>
<tbody>${top
    .map(
      (t) =>
        `<tr><th scope="row">${h(t.denomination)}<div class="aide">numéro SIREN ${h(t.siren)}</div></th><td>${h(TYPES[typeBeneficiaire(t.categorie_juridique)])}</td>${
          nomsSources ? `<td>${h((t.sources ?? []).map((s) => nomsSources.get(s) ?? s).join(' ; '))}</td>` : ''
        }<td class="nombre">${h(eurLisible(t.montant_eur))}</td></tr>`,
    )
    .join('')}</tbody></table></div><p class="aide">${h(REGLE_ORDRE)}</p>`
}

// ---------- Blocs de la page ----------

function blocAnneesConventions(ix: IndexSubv, an: AnneesSubv): string {
  const sources = an.sources_additionnees.map((id) => ix.sources.find((s) => s.id === id)).filter((s): s is SourceSubv => !!s)
  const annees = an.annees.map((a) => a.annee)
  const cellule = (a: AnneesSubv['annees'][number], id: string) => {
    const v = a.par_source[id]
    if (!v) return '<td class="nombre">–</td>'
    return `<td class="nombre">${h(eurLisible(v.montant_eur))}${v.lignes_montant_non_communique ? `<div class="aide">${h(entier(v.lignes_montant_non_communique))} sans montant</div>` : ''}</td>`
  }
  const totalParAnnee = barres(
    an.annees.map((a) => ({ nom: String(a.annee), valeur: a.total_additionne_eur, texte: `${eurLisible(a.total_additionne_eur)}, ${entier(a.conventions)} conventions`, statut: 'trace' as const })),
    undefined,
    'Total additionné par année de signature ou d’engagement',
    -1,
  )
  return `<h3>Conventions de subvention publiées</h3>
<p>Montants engagés ou attribués l’année de la signature de la convention (pas des paiements), pour les ${h(entier(sources.length))} sources additionnées. Le total d’une année dépend des sources qui la couvrent : ses variations reflètent d’abord la couverture des publications.</p>
${totalParAnnee}
<div class="tableau-defile"><table>
<caption>Subventions par organisme qui attribue et par année (euros engagés ou attribués)</caption>
<thead><tr><th scope="col">Attribué par</th>${annees.map((y) => `<th scope="col" class="nombre">${y}</th>`).join('')}</tr></thead>
<tbody>${sources
    .map((s) => `<tr><th scope="row">${h(s.attribuant)}</th>${an.annees.map((a) => cellule(a, s.id)).join('')}</tr>`)
    .join('')}<tr><th scope="row">Total des sources additionnées</th>${an.annees.map((a) => `<td class="nombre"><strong>${h(eurLisible(a.total_additionne_eur))}</strong></td>`).join('')}</tr></tbody>
</table></div>
<p class="aide">« – » : année non couverte par la source (jamais compté 0). Statut : ${badgeStatut('trace')} destinataire publié par la source.</p>`
}

function blocAnneesJaunes(ai: IndexAssoc): string {
  return `<h3>Subventions de l’État aux associations (liste annexée au projet de loi de finances)</h3>
<p>Chaque projet de loi de finances publie la liste des subventions versées aux associations deux ans plus tôt, programme par programme. Des organismes qui ne sont pas des associations y figurent aussi. ${h(ai.note)}</p>
<div class="tableau-defile"><table>
<caption>Liste des subventions de l’État aux associations, par année de versement</caption>
<thead><tr><th scope="col">Versé en</th><th scope="col">Liste du projet de loi de finances</th><th scope="col" class="nombre">Total publié</th><th scope="col" class="nombre">Organismes nommés</th><th scope="col" class="nombre">Montant nommé</th><th scope="col" class="nombre">Agrégé, jamais nommé</th><th scope="col">Statut</th></tr></thead>
<tbody>${ai.annees
    .map(
      (a) =>
        `<tr><th scope="row">${a.annee_credits}</th><td>${a.annee}</td><td class="nombre">${h(montant(a.total_source_eur))}</td><td class="nombre">${h(
          typeof a.associations_nommees === 'number' ? entier(a.associations_nommees) : montant(a.associations_nommees),
        )}</td><td class="nombre">${h(montant(a.nommes_eur))}</td><td class="nombre">${h(montant(a.exclus_personnes_physiques_ou_non_identifies_eur))}</td><td>${
          a.statut === 'nc' ? `${badgeStatut('nonpub')}${a.raison ? `<div class="aide">${h(a.raison)}</div>` : ''}` : `${badgeStatut('trace')}${a.correction ? '<div class="aide">montants corrigés, raison dans la méthode du fichier</div>' : ''}`
        }</td></tr>`,
    )
    .join('')}</tbody></table></div>
${source(ai.source, ai.millesime)}`
}

/** Les associations par mission du budget (regroupement des programmes d'après le budget 2024). */
async function blocMissions(ai: IndexAssoc, annee: number): Promise<string> {
  const i = ai.annees.findIndex((a) => a.annee === annee)
  const a = ai.annees[i]
  const progs = await listeProgrammes()
  const mission = new Map(progs.map((p) => [p.numero, p.mission]))
  const groupes = new Map<string, { total: number; programmes: { numero: string; libelle: string; montant: number }[] }>()
  const HORS = 'Programmes absents du budget 2024 (renumérotés ou clos)'
  for (const p of ai.programmes) {
    const v = nb(p.totaux_eur[i])
    if (v === null || v === 0) continue
    const m = mission.get(p.programme) || HORS
    const g = groupes.get(m) ?? { total: 0, programmes: [] }
    g.total += v
    g.programmes.push({ numero: p.programme, libelle: p.libelle, montant: v })
    groupes.set(m, g)
  }
  const choix = `${listeRecherche({ id: 'sub-annee', etiquette: 'Année de versement', options: [], optionsHtml: `${ai.annees
    .filter((x) => x.statut === 'publie')
    .map((x) => `<option value="${x.annee}"${x.annee === annee ? ' selected' : ''}>${x.annee_credits} (projet de loi de finances ${x.annee})</option>`)
    .join('')}` })}`
  if (!a || a.statut !== 'publie' || !groupes.size) return choix + absent('Pas de liste publiée pour cette année.')
  const total = nb(a.total_source_eur) ?? 0
  const liste = [...groupes.entries()].sort((x, y) => y[1].total - x[1].total || x[0].localeCompare(y[0], 'fr'))
  return `${choix}
<p>Versé en ${a.annee_credits}, liste du projet de loi de finances ${a.annee} : ${h(eurLisible(total))} au total. Une mission regroupe des programmes conduits le plus souvent par un même ministère.</p>
${barres(
  liste.map(([m, g]) => ({ nom: m, valeur: g.total, texte: `${eurLisible(g.total)}, soit ${sur100((g.total / (total || 1)) * 100)} sur 100 €`, statut: 'trace' as const })),
  undefined,
  `Subventions aux associations par mission, versées en ${a.annee_credits}`,
  -1,
)}
<details><summary>Le détail par programme</summary>
<div class="tableau-defile"><table>
<caption>Subventions aux associations par programme, versées en ${a.annee_credits}</caption>
<thead><tr><th scope="col">Programme</th><th scope="col">Mission</th><th scope="col" class="nombre">Montant</th></tr></thead>
<tbody>${liste
  .flatMap(([m, g]) => g.programmes.map((p) => ({ ...p, m })))
  .sort((x, y) => y.montant - x.montant || x.numero.localeCompare(y.numero))
  .map(
    (p) =>
      `<tr><th scope="row">${mission.has(p.numero) ? `<a href="${lien('/beneficiaires', { onglet: 'programme', p: p.numero })}">${h(p.numero)} ${h(p.libelle)}</a>` : `${h(p.numero)} ${h(p.libelle)}`}</th><td>${h(
        p.m,
      )}</td><td class="nombre">${h(eurLisible(p.montant))}</td></tr>`,
  )
  .join('')}</tbody></table></div>
<p class="aide">Les noms des associations de chaque programme pour la dernière année publiée sont sur la page <a href="${lien('/beneficiaires')}">Qui reçoit l’argent</a>. ${h(REGLE_ORDRE)}</p>
</details>`
}

function blocSources(ix: IndexSubv): string {
  return ix.sources
    .map(
      (s) => `<details class="carte" data-source="${h(s.id)}"><summary><strong>${h(s.attribuant)}</strong> : ${h(eurLisible(s.total_eur))} (${h(s.millesime)})</summary>
<ul>
<li>Statut : ${statutSource(s, ix.sources)}${s.montant_retire_des_totaux_eur ? ` ; ${h(eurLisible(s.montant_retire_des_totaux_eur))} retirés du total (projets pouvant figurer aussi dans une autre source)` : ''}.</li>
<li>Rattachement : ${h(rattachement(s))}.</li>
<li>${h(entier(s.conventions))} conventions ou aides${s.lignes_montant_non_communique ? `, dont ${h(entier(s.lignes_montant_non_communique))} sans montant publié (comptées à part, jamais 0)` : ''}.</li>
<li>Organismes nommés : ${h(entier(s.nommes.nombre))}, ${h(eurLisible(s.nommes.montant_eur))}. Agrégé, jamais nommé : ${h(eurLisible(s.agrege_confidentialite.montant_eur))}, soit ${h(sur100(s.agrege_confidentialite.part_pct))} sur 100 €.</li>
</ul>
<div class="detail-source" aria-live="polite"></div>
<p class="source">${h(s.titre)}, ${lienExterne(s.page, 'page de la source')}, ${h(s.licence)}</p>
</details>`,
    )
    .join('')
}

async function detailSource(s: SourceSubv): Promise<string> {
  const d = await chargerSiPresent<Attribuant>(s.fichier)
  if (!d) return absent('Le détail de cette source n’est pas disponible.')
  const parAnnee = `<div class="tableau-defile"><table>
<caption>${h(s.attribuant)} : montants par année</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Montant</th><th scope="col" class="nombre">Conventions</th><th scope="col" class="nombre">Dont organismes nommés</th><th scope="col" class="nombre">Sans montant publié</th></tr></thead>
<tbody>${d.par_annee
    .map(
      (a) =>
        `<tr><th scope="row">${a.annee}</th><td class="nombre">${h(eurLisible(a.montant_eur))}</td><td class="nombre">${h(entier(a.conventions))}</td><td class="nombre">${h(
          eurLisible(a.montant_nomme_eur),
        )}</td><td class="nombre">${h(entier(a.lignes_montant_non_communique))}</td></tr>`,
    )
    .join('')}</tbody></table></div>`
  let qui = ''
  if (d.beneficiaires?.top?.length) {
    const g = d.beneficiaires
    qui = `${tableTypes(g, `${s.attribuant} : par type de bénéficiaire (${s.millesime})`)}
${tableTop(g.top.slice(0, 10), `${s.attribuant} : premiers bénéficiaires nommés (${s.millesime})`)}
<ul>${lignesExclus(g.exclus_personnes_physiques_ou_non_identifies).map((l) => `<li>${h(l)}</li>`).join('')}</ul>`
  } else if (d.titres?.top?.length) {
    const t = d.titres
    qui = `<p>Les aides à la presse sont publiées par titre de presse, sans numéro SIREN : les titres ne sont pas cherchables par organisme.</p>
<ul>${t.top
      .slice(0, 10)
      .map((x) => `<li>${h(x.titre)} : ${h(eurLisible(x.montant_eur))}</li>`)
      .join('')}${t.autres_titres?.nombre ? `<li>${h(entier(t.autres_titres.nombre))} autres titres : ${h(eurLisible(t.autres_titres.montant_eur))}</li>` : ''}${
      t.titres_non_nommes?.nombre ? `<li>${h(entier(t.titres_non_nommes.nombre))} titres agrégés, jamais nommés : ${h(eurLisible(t.titres_non_nommes.montant_eur))}</li>` : ''
    }</ul><p class="aide">${h(REGLE_ORDRE)}</p>`
  }
  return `${parAnnee}${qui}${source(d.source, d.millesime)}`
}

// ---------- Recherche ----------
interface Trouve {
  siren: string
  denomination: string
  cj: string
  ou: string
  periode: string
  montant: number
  statut: string
}

function tableTrouves(t: Trouve[], legende: string): string {
  if (!t.length) return ''
  const tri = [...t].sort((a, b) => b.montant - a.montant || a.denomination.localeCompare(b.denomination, 'fr'))
  const vus = tri.slice(0, MAX_RESULTATS)
  return `<div class="tableau-defile"><table>
<caption>${h(legende)}</caption>
<thead><tr><th scope="col">Organisme</th><th scope="col">Type</th><th scope="col">Source</th><th scope="col">Année</th><th scope="col" class="nombre">Montant</th><th scope="col">Statut</th></tr></thead>
<tbody>${vus
    .map(
      (x) =>
        `<tr><th scope="row">${h(x.denomination)}<div class="aide">numéro SIREN ${h(x.siren)}</div></th><td>${h(TYPES[typeBeneficiaire(x.cj)])}</td><td>${h(x.ou)}</td><td>${h(x.periode)}</td><td class="nombre">${h(
          eurLisible(x.montant),
        )}</td><td>${x.statut}</td></tr>`,
    )
    .join('')}</tbody></table></div>
<p class="aide">${h(REGLE_ORDRE)}${tri.length > vus.length ? ` ${h(entier(vus.length))} lignes affichées sur ${h(entier(tri.length))} : précise ta recherche.` : ''}</p>`
}

/** Conventions : les premiers bénéficiaires publiés par chaque source et toutes sources additionnées. */
async function chercherConventions(q: string, ix: IndexSubv): Promise<Trouve[]> {
  const out: Trouve[] = []
  const fichiers = await Promise.all(ix.sources.map((s) => chargerSiPresent<Attribuant>(s.fichier)))
  ix.sources.forEach((s, i) => {
    for (const t of fichiers[i]?.beneficiaires?.top ?? [])
      if (correspond(q, t.siren, t.denomination))
        out.push({ siren: t.siren, denomination: t.denomination, cj: t.categorie_juridique, ou: s.attribuant, periode: s.millesime, montant: t.montant_eur, statut: `${badgeStatut('trace')} engagé ou attribué${s.additionne ? '' : ', détaille une autre source'}` })
  })
  return out
}

function chercherDansProgramme(q: string, d: ProgrammeJaune): Trouve[] {
  const out: Trouve[] = []
  for (const [siren, denomination, cj, , montants] of d.lignes) {
    if (!correspond(q, siren, denomination)) continue
    // Dernier montant publié de la série (jamais un « nc » ni une absence compté 0).
    for (let i = montants.length - 1; i >= 0; i--) {
      const v = montants[i]
      if (typeof v !== 'number') continue
      out.push({
        siren,
        denomination,
        cj,
        ou: `Programme ${d.programme} ${d.libelle}`,
        periode: `versé en ${d.annees_credits[i]} (projet de loi de finances ${d.annees[i]})`,
        montant: v,
        statut: `${badgeStatut('trace')} dernier montant publié`,
      })
      break
    }
  }
  return out
}

function brancherRecherche(cible: HTMLElement, ix: IndexSubv, ai: IndexAssoc | null) {
  const form = cible.querySelector<HTMLFormElement>('#sub-recherche')
  const zone = cible.querySelector<HTMLElement>('#sub-resultats')
  if (!form || !zone) return
  const fichiers = (ai?.programmes ?? []).flatMap((p) => p.fichiers)
  let jeton = 0
  let trouvesJaunes: Trouve[] = []
  let parcourus = 0
  let requete = ''
  let blocConventions = ''

  const afficher = () => {
    const reste = fichiers.length - parcourus
    zone.innerHTML = `${blocConventions}
<h3>Dans la liste des subventions aux associations</h3>
<p id="sub-progression">${h(entier(parcourus))} fichiers parcourus sur ${h(entier(fichiers.length))} (un fichier par programme du budget).</p>
${tableTrouves(trouvesJaunes, `« ${requete} » dans la liste des subventions aux associations`) || (parcourus ? absent('Aucun organisme trouvé dans les fichiers parcourus.') : '')}
${reste > 0 ? `<button type="button" id="sub-suite">Chercher dans les ${h(entier(Math.min(LOT, reste)))} fichiers suivants</button>` : fichiers.length ? '<p>Recherche terminée dans tous les fichiers.</p>' : ''}`
    appliquerLargeurs(zone)
    zone.querySelector<HTMLButtonElement>('#sub-suite')?.addEventListener('click', () => void lot())
  }

  // Un lot de fichiers à la fois : seuls les organismes trouvés sont gardés en mémoire.
  const lot = async () => {
    const moi = jeton
    const bouton = zone.querySelector<HTMLButtonElement>('#sub-suite')
    if (bouton) {
      bouton.disabled = true
      bouton.textContent = 'Chargement…'
    }
    const morceau = fichiers.slice(parcourus, parcourus + LOT)
    for (const f of morceau) {
      const d = await chargerSiPresent<ProgrammeJaune>(f)
      if (moi !== jeton) return
      if (d) trouvesJaunes.push(...chercherDansProgramme(requete, d))
      parcourus++
    }
    // Les listes complètes sont lourdes : on ne les garde pas en cache une fois parcourues.
    viderCache()
    afficher()
    annoncer(`${parcourus} fichiers parcourus sur ${fichiers.length}, ${trouvesJaunes.length} lignes trouvées.`)
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault()
    const q = (form.querySelector<HTMLInputElement>('#sub-q')?.value ?? '').trim()
    const msg = form.querySelector<HTMLElement>('#sub-msg')!
    const champ = form.querySelector<HTMLInputElement>('#sub-q')!
    if (normaliser(q).replace(/ /g, '').length < 3) {
      champ.setAttribute('aria-invalid', 'true')
      msg.textContent = 'Écris au moins 3 lettres ou un numéro SIREN à 9 chiffres.'
      return
    }
    champ.removeAttribute('aria-invalid')
    msg.textContent = ''
    const moi = ++jeton
    requete = q
    trouvesJaunes = []
    parcourus = 0
    zone.innerHTML = '<p class="chargement">Recherche…</p>'
    const conv = await chercherConventions(q, ix)
    if (moi !== jeton) return
    blocConventions = `<h3>Dans les conventions de subvention</h3>
<p class="aide">Les fichiers des conventions ne nomment que les premiers bénéficiaires de chaque source ; les autres organismes sont comptés ensemble (« autres personnes morales »).</p>
${tableTrouves(conv, `« ${q} » parmi les premiers bénéficiaires des conventions de subvention`) || absent('Aucun organisme trouvé parmi les premiers bénéficiaires des conventions.')}`
    afficher()
    if (fichiers.length) await lot()
  })
}

// ---------- Écran ----------
export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const [ix, an, ben, ai] = await Promise.all([
    chargerSiPresent<IndexSubv>('subventions/index.json'),
    chargerSiPresent<AnneesSubv>('subventions/annees.json'),
    chargerSiPresent<Groupe & { source: string; millesime: string; note?: string }>('subventions/beneficiaires.json'),
    chargerSiPresent<IndexAssoc>('associations/index.json'),
  ])
  const intro = `<h1>Les subventions de l’État et de ses opérateurs</h1>
<p class="chapeau">Une subvention est une somme versée par l’État ou par l’un de ses opérateurs (agences, établissements publics) à un organisme pour un projet ou une activité. Deux familles de publications existent : les conventions de subvention publiées par chaque organisme qui attribue, et la liste annuelle des subventions de l’État aux associations, annexée au projet de loi de finances. Elles se recouvrent en partie : elles sont montrées côte à côte, jamais additionnées.</p>
<p>Cette page complète <a href="${lien('/beneficiaires')}">Qui reçoit l’argent</a> (associations d’un programme, France 2030, marchés de l’État) et <a href="${lien('/explorer/operateurs')}">Les opérateurs de l’État</a>.</p>`
  if (!ix) {
    cible.innerHTML = intro + absent('Données en cours d’intégration.')
    return
  }
  const t = ix.totaux
  const total = t.total_additionne_eur || 1
  const derniere = ai ? [...ai.annees].reverse().find((a) => a.statut === 'publie') : undefined
  const nomsSources = new Map(ix.sources.map((s) => [s.id, s.attribuant]))
  const anneeMissions = Number(params.get('annee')) || derniere?.annee || 0

  const cle = `<div class="carte" data-cle>
  <p class="grand-chiffre">${surligne(eurLisible(t.total_additionne_eur))}</p>
  <p class="sous-chiffre">de subventions engagées ou attribuées dans les conventions publiées par ${h(entier(ix.sources.filter((s) => s.additionne).length))} sources additionnées (${h(ix.millesime)}). Sur 100 € publiés, ${h(
    sur100((t.nommes_additionnes.montant_eur / total) * 100),
  )} vont à des organismes nommés (personnes morales) et ${h(sur100((t.agrege_confidentialite.montant_eur / total) * 100))} restent agrégés : personnes physiques ou bénéficiaires sans identifiant.</p>
  <p>Statut : ${badgeStatut('trace')} montants engagés ou attribués publiés par chaque source (pas des paiements).</p>
  ${source(ix.source, ix.collecte_le ? `collecte du ${ix.collecte_le}` : undefined)}
</div>${
    derniere && typeof derniere.total_source_eur === 'number'
      ? `<div class="carte"><p>Liste des subventions de l’État aux associations : <strong>${h(eurLisible(derniere.total_source_eur))}</strong> versés en ${derniere.annee_credits} (projet de loi de finances ${derniere.annee}), ${h(
          typeof derniere.associations_nommees === 'number' ? entier(derniere.associations_nommees) : '',
        )} organismes nommés. Statut : ${badgeStatut('trace')} montants versés publiés.</p>${source(ai!.source, ai!.millesime)}</div>`
      : ''
  }`

  const types = ben
    ? `<h2>À quels types de bénéficiaires</h2>
<p>Le type vient de la catégorie juridique de chaque organisme dans la base des entreprises de l’Insee (SIRENE). Les fichiers publiés ne donnent le type que des ${h(entier(ben.top.length))} premiers bénéficiaires, toutes sources additionnées ; pour les autres organismes, le montant est publié sans répartition par type.</p>
${tableTypes(ben, `Conventions de subvention par type de bénéficiaire (${ben.millesime})`)}
<details><summary>Les ${h(entier(ben.top.length))} premiers bénéficiaires, toutes sources additionnées</summary>
${tableTop(ben.top, `Premiers bénéficiaires des conventions de subvention (${ben.millesime})`, nomsSources)}
</details>
<ul>${lignesExclus(ben.exclus_personnes_physiques_ou_non_identifies).map((l) => `<li>${h(l)}</li>`).join('')}</ul>
${ben.note ? `<p class="aide">${h(ben.note)}</p>` : ''}${source(ben.source, ben.millesime)}`
    : ''

  const exclusConv = ben?.exclus_personnes_physiques_ou_non_identifies?.montant_eur ?? t.agrege_confidentialite.montant_eur
  const exclusJaune = derniere ? nb(derniere.exclus_personnes_physiques_ou_non_identifies_eur) : null
  const recherche = `<h2>Chercher un organisme</h2>
<form id="sub-recherche" class="carte" novalidate role="search">
  <label for="sub-q">Nom ou numéro SIREN de l’organisme</label>
  <input id="sub-q" type="search" autocomplete="off" aria-describedby="sub-aide sub-msg" />
  <p id="sub-msg" class="aide" aria-live="polite"></p>
  <button type="submit">Chercher</button>
  <p id="sub-aide" class="aide">Seuls les organismes qui sont des personnes morales (associations, entreprises, collectivités, établissements publics) peuvent être trouvés. Les sommes versées à des personnes physiques ou à des bénéficiaires sans identifiant restent agrégées et ne sont pas cherchables : ${h(
    eurLisible(exclusConv),
  )} dans les conventions de subvention${derniere && exclusJaune !== null ? `, ${h(eurLisible(exclusJaune))} dans la liste des associations versée en ${derniere.annee_credits}` : ''}. La liste des associations est lue par lots de ${LOT} fichiers.</p>
</form>
<div id="sub-resultats" aria-live="polite"></div>`

  const recouvrements = ix.recouvrements.length
    ? `<h3>Sources qui se recouvrent</h3><ul>${ix.recouvrements.map((r) => `<li>${h(r.lecture)}</li>`).join('')}</ul>`
    : ''
  const inaccessibles = [...(ai?.sources_inaccessibles ?? []).map((s) => (s.constat ? `${s.annee ?? ''} : ${s.constat}` : '')), ...ix.sources_inaccessibles.map((s) => String(s))].filter(Boolean)

  cible.innerHTML = `${intro}${cle}
<h2>Par année</h2>
${an ? blocAnneesConventions(ix, an) : absent('Série par année non disponible.')}
${ai ? blocAnneesJaunes(ai) : ''}
<h2>Par ministère ou organisme qui attribue</h2>
<p>Chaque source correspond à un ministère, à un service de l’État ou à un opérateur. Ouvre une source pour voir ses montants par année et ses premiers bénéficiaires.</p>
${blocSources(ix)}
${ai ? `<h3>Associations : par mission du budget de l’État</h3><div id="sub-missions">${await blocMissions(ai, anneeMissions)}</div>` : ''}
${types}
${recherche}
<h2>Limites</h2>
<ul>${ix.limites.map((l) => `<li>${h(l)}</li>`).join('')}<li>${h(ix.note)}</li></ul>
${recouvrements}
${inaccessibles.length ? `<h3>Sources non exploitables</h3><ul>${inaccessibles.map((x) => `<li>${h(x)}</li>`).join('')}</ul>` : ''}
<p>Pour la méthode et la part de l’argent dont le destinataire est publié : <a href="${lien('/methode/tracabilite')}">Traçabilité : d’où vient chaque montant</a>.</p>`

  // Détail d'une source chargé à l'ouverture.
  cible.querySelectorAll<HTMLDetailsElement>('details[data-source]').forEach((d) =>
    d.addEventListener('toggle', async () => {
      const z = d.querySelector<HTMLElement>('.detail-source')!
      if (!d.open || z.dataset.charge) return
      z.dataset.charge = '1'
      const s = ix.sources.find((x) => x.id === d.dataset.source)!
      z.innerHTML = '<p class="chargement">Chargement…</p>'
      z.innerHTML = await detailSource(s)
      appliquerLargeurs(z)
    }),
  )
  if (ai) {
    const brancherAnnee = () =>
      cible.querySelector<HTMLSelectElement>('#sub-annee')?.addEventListener('change', async (e) => {
        const z = cible.querySelector<HTMLElement>('#sub-missions')!
        z.innerHTML = await blocMissions(ai, Number((e.target as HTMLSelectElement).value))
        appliquerLargeurs(z)
        brancherAnnee()
      })
    brancherAnnee()
  }
  brancherRecherche(cible, ix, ai)
}

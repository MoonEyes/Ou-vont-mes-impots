// Les retraites (site/data/retraites/, contrat 2.40) : montant des pensions versées chaque année, régimes qui les
// versent, retraités et pension moyenne, origine de l'argent quand elle est publiée, et part de ce que verse la
// personne. Les montants de pensions sont lus dans les fichiers liés (prestations/, secu/, arbre/), jamais recopiés
// ni recalculés à partir d'un effectif et d'une moyenne. Les effectifs des régimes ne s'additionnent pas, deux
// comptabilités ne s'additionnent jamais, et une valeur absente de la source reste « non publié », jamais 0.
import { parAdministration } from '../calcul/repartition'
import type { Fourchette, Prelevement } from '../calcul/types'
import { billet, FAMILLES_TOURNANTES, listeParts, type Part } from '../composants/billet'
import { partPersonnelle } from '../composants/hub'
import { plage, statutPlage } from '../composants/resume-calcul'
import { chargerSiPresent, type Noeud } from '../donnees'
import { session } from '../etat'
import { lien } from '../routeur'
import { ROUTES } from '../routes'
import { badgeStatut, barres, entier, eur, eurLisible, h, md, pct, source, sur100, surligne, traitStatut } from '../util'

type Serie = Record<string, number | null>

interface Lien {
  vue: string
  fichier: string
  id: string
  nom: string
  md?: number
  millesime?: string
  lecture: string
}
interface RegimeIndex {
  id: string
  nom: string
  type: string | null
  liens: Lien[]
}
interface SourceRet {
  url: string
  page?: string
  titre: string
  producteur: string
  millesime: string
  licence: string
}
interface Ecart {
  objet: string
  regime: string
  annee: number
  grandeur: string
  source: string
  valeur: number
  autre_source: string
  autre_valeur: number
  ecart: number
  ecart_pct: number
  lecture_ecart: string
}
interface Index {
  derniere_annee: number
  regimes: RegimeIndex[]
  tous_regimes?: { note?: string }
  types: Record<string, string>
  definitions: Record<string, string>
  ecarts: Ecart[]
  ecarts_msa?: { constat: string; lecture_ecart: string }
  regle: string
  limites: string[]
  sources: Record<string, SourceRet>
  sources_inaccessibles: { source: string; motif: string }[]
}
interface Cotisants {
  source: string
  definition: string
  valeurs: Serie
  rapport_cotisants_retraites_publie?: Serie
  rapport_cotisants_retraites_droit_direct?: Serie
  rapport_methode?: string
}
interface Regime {
  nom: string
  type: string | null
  premiere_annee: number
  derniere_annee: number
  retraites_droit_direct: Serie
  retraites_tous_droits: Serie
  nouveaux_retraites_droit_direct: Serie
  pension_droit_direct_eur_mois: Serie
  cotisants?: Cotisants
  zeros_source?: Record<string, number[]>
}
interface Regimes {
  regimes: Record<string, Regime>
}
interface Section {
  section: string
  nom: string
  recettes_eur: number
  depenses_cp_eur: number
  recettes_moins_depenses_eur: number
}
interface Credit {
  nom: string
  regime?: string | null
  execution_2024_eur: number | null
  plf_2025_cp_eur: number | null
  id: string
}
interface Etat {
  limites: string[]
  cas_pensions?: {
    definition: string
    depenses_cp_eur: number
    recettes_eur: number
    recettes_par_origine_eur: Record<string, number>
    recettes_par_origine_pct: Record<string, number>
    origines: Record<string, string>
    sections: Section[]
    methode: string
  }
  retraites_etat?: {
    definition: string
    populations: Record<string, { nom: string; effectif: Serie; pension_moyenne_eur_mois: Serie }>
    note: string
  }
  credits_regimes_speciaux?: {
    definition: string
    programmes: (Credit & { programme: string; actions: (Credit & { action: string })[] })[]
    total_execution_2024_eur: number
    total_plf_2025_cp_eur: number
  }
}
interface Pensions {
  montant_eur: Serie
  derniere_annee: number
  par_regime: { code_secteur: string; regime: string; montant_eur: Serie }[]
}
type Racine = Noeud & { millesime?: string; source?: string; tracabilite_pct?: number; note?: string }
interface Affectation {
  millesime: string
  source: string
  prelevements: Record<string, { libelle: string; ventilation?: { destinataire: string; part: number; montant_md?: number }[]; note?: string }>
}

export const TITRE = 'Les retraites : montants, régimes et financement'
const NON_PUBLIE = 'non publié'
const nf1 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const num = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x)
const nb = (x: number | null | undefined) => (num(x) ? entier(x) : NON_PUBLIE)
const millions = (x: number) => `${nf1.format(x / 1e6)} millions`
const mensuel = (x: number | null | undefined) => (num(x) ? eur(x) : NON_PUBLIE)
const milliards = (x: number | null | undefined) => (num(x) ? md(x / 1e9) : NON_PUBLIE)
const anneesDe = (s: Serie) => Object.keys(s).filter((a) => num(s[a])).sort()
/** Montant en euros lisible : milliards au-delà d'un milliard, sinon millions ou milliers (jamais « 0,00 Md€ »). */
const lisible = (x: number | null | undefined) => (!num(x) ? NON_PUBLIE : Math.abs(x) >= 1e9 ? md(x / 1e9) : eurLisible(x))

// Sigles des textes explicatifs écrits par le pipeline, développés pour le grand public. Les titres des sources
// (citations) restent tels quels.
const SIGLES: [RegExp, string][] = [
  [/\bdu PLF (\d{4})\b/g, 'du projet de loi de finances $1'],
  [/\bdu PLF\b/g, 'du projet de loi de finances'],
  [/\bPLF (\d{4})\b/g, 'projet de loi de finances $1'],
  [/\bPLF\b/g, 'projet de loi de finances'],
  [/\bdu CAS Pensions\b/g, 'du compte d’affectation spéciale Pensions'],
  [/\bCAS Pensions\b/g, 'compte d’affectation spéciale Pensions'],
  [/\bl['’]EACR\b/g, 'l’enquête annuelle auprès des caisses de retraite'],
  [/(?<!\()\bEACR\b(?!\))/g, 'enquête annuelle auprès des caisses de retraite'],
  [/\bdu COR\b/g, 'du Conseil d’orientation des retraites'],
  // Renvois aux noms de champs du fichier (« règles dans `origines` ») : utiles aux réutilisateurs, pas au lecteur.
  [/\s*\([^()]*`[^`]*`[^()]*\)/g, ''],
]
const sansSigle = (t: string) => SIGLES.reduce((x, [re, par]) => x.replace(re, par), t)
const finale = (x: string) => (/[.!?]$/.test(x) ? x : `${x}.`)
/** Texte des données en phrase autonome : sigles développés, majuscule initiale, point final s'il manque. */
const phrase = (t: string) => {
  const x = sansSigle(t.trim())
  return x ? finale(`${x[0].toUpperCase()}${x.slice(1)}`) : ''
}
/** Texte des données après deux-points : sigles développés, minuscule conservée, point final s'il manque. */
const fin = (t: string) => {
  const x = sansSigle(t.trim())
  return x ? finale(x) : ''
}

/** Caisses de retraite parmi les destinataires des prélèvements (contrat 3.5, prelevements/affectation.json, moteur étendu). */
export const CAISSES_RETRAITE: Record<string, string> = {
  cnav: 'Assurance retraite du régime général (CNAV)',
  agirc_arrco: 'Retraite complémentaire des salariés du privé (Agirc-Arrco)',
  msa_vieillesse: 'Retraite de base des non-salariés agricoles (MSA)',
  msa_rco: 'Retraite complémentaire des non-salariés agricoles (MSA)',
  pension_civile_etat: 'Pensions des fonctionnaires de l’État',
  cnracl: 'Retraite des agents des collectivités et des hôpitaux (CNRACL)',
  rafp: 'Retraite additionnelle de la fonction publique',
  ircantec: 'Retraite complémentaire des agents non titulaires (Ircantec)',
  independants_retraite_base: 'Retraite de base des indépendants',
  independants_retraite_complementaire: 'Retraite complémentaire des indépendants',
}

/**
 * Lignes de retraite du moteur étendu dont l'affectation n'est pas encore publiée (src/calcul/moteur-etendu.ts,
 * CLES_AFFECTATION_A_CREER ; le test vérifie l'égalité) : affichées à part, jamais comptées dans la part retraite
 * (une part introuvable n'est jamais complétée par une estimation).
 */
export const RETRAITE_SANS_AFFECTATION: Record<string, string> = {
  retenue_pension_civile: 'pension_civile_etat',
  contribution_cas_pensions: 'pension_civile_etat',
  retenue_cnracl: 'cnracl',
  contribution_cnracl: 'cnracl',
  rafp_salarie: 'rafp',
  rafp_employeur: 'rafp',
  ircantec_salarie: 'ircantec',
  ircantec_employeur: 'ircantec',
  micro_retraite_base: 'independants_retraite_base',
  micro_retraite_complementaire: 'independants_retraite_complementaire',
  independant_retraite_base: 'independants_retraite_base',
  independant_retraite_complementaire: 'independants_retraite_complementaire',
}

const zero = (): Fourchette => ({ bas: 0, central: 0, haut: 0 })
function ajouter(f: Fourchette, g: Fourchette, k = 1) {
  f.bas += g.bas * k
  f.central += g.central * k
  f.haut += g.haut * k
}

export interface PartRetraite {
  total: Fourchette
  caisses: { id: string; nom: string; f: Fourchette }[]
  /** lignes de retraite dont le destinataire n'est pas publié dans les données du site */
  sansAffectation: Fourchette
}

/** Part des prélèvements qui va aux caisses de retraite, d'après le destinataire ou la ventilation publiée de chaque ligne. */
export function partRetraite(lignes: Prelevement[]): PartRetraite {
  const par = new Map<string, Fourchette>()
  const sans = zero()
  for (const l of lignes) {
    if (l.non_chiffre) continue
    const parts = l.ventilation?.length ? l.ventilation : [{ destinataire: String(l.destinataire.id), part: 1 }]
    let compte = false
    for (const v of parts) {
      if (!Object.hasOwn(CAISSES_RETRAITE, v.destinataire)) continue
      const f = par.get(v.destinataire) ?? zero()
      ajouter(f, l.montant_annuel_eur, v.part)
      par.set(v.destinataire, f)
      compte = true
    }
    if (!compte && Object.hasOwn(RETRAITE_SANS_AFFECTATION, l.id)) ajouter(sans, l.montant_annuel_eur)
  }
  const caisses = [...par.entries()]
    .map(([id, f]) => ({ id, nom: CAISSES_RETRAITE[id], f }))
    .sort((a, b) => b.f.central - a.f.central || a.nom.localeCompare(b.nom, 'fr'))
  const total = zero()
  for (const c of caisses) ajouter(total, c.f)
  return { total, caisses, sansAffectation: sans }
}

/** Libellés lisibles des régimes des comptes de la protection sociale (DREES) ; le libellé de la source reste affiché. */
const NOMS_DREES: Record<string, string> = {
  'Caisse nationale d’assurance vieillesse': 'Assurance retraite du régime général (CNAV)',
  'Association générale des institutions de retraite des cadres et association des régimes de retraite complémentaire des salariés':
    'Retraite complémentaire des salariés du privé (Agirc-Arrco)',
  "Régimes pour les agents de l'État (y compris ex-L)": 'Régimes des agents de l’État',
  'Exploitants agricoles': 'Exploitants agricoles (MSA)',
  'Régime des salariés agricoles': 'Salariés agricoles (MSA)',
  'CNAVPL base complementaire': 'Professions libérales (CNAVPL), base et complémentaire',
  'Institution de retraite complémentaire des agents non titulaires de l’État et des collectivités publiques':
    'Retraite complémentaire des agents non titulaires de l’État et des collectivités (Ircantec)',
}
const nomDrees = (r: string) => NOMS_DREES[r] ?? r

const TYPES_ORDRE = ['ensemble', 'base', 'integre', 'complementaire', 'autre']
const groupe = (t: string | null) => (t && TYPES_ORDRE.includes(t) ? t : 'autre')
export const REGLE_REGIMES =
  'Ordre : ensemble des régimes, puis régimes de base, régimes intégrés, régimes complémentaires et régimes au type non précisé ; dans chaque groupe, du plus grand au plus petit nombre de retraités de droit direct.'
export const REGLE_MONTANTS = 'Ordre : montant versé, du plus grand au plus petit.'
export const REGLE_RECETTES = 'Ordre : montant prévu, du plus grand au plus petit.'

/** Ordre neutre et écrit des régimes : groupe de type, puis nombre de retraités de droit direct décroissant, puis nom. */
export function ordreRegimes(ids: string[], regimes: Record<string, Regime>, annee: string): string[] {
  const rang = (id: string) => TYPES_ORDRE.indexOf(groupe(regimes[id].type))
  const dd = (id: string) => regimes[id].retraites_droit_direct[annee] ?? -1
  return [...ids].sort((a, b) => rang(a) - rang(b) || dd(b) - dd(a) || regimes[a].nom.localeCompare(regimes[b].nom, 'fr'))
}

function trouver(n: Noeud, id: string): Racine | null {
  if (n.id === id) return n
  for (const e of n.enfants ?? []) {
    const x = trouver(e, id)
    if (x) return x
  }
  return null
}

/** Statut d'un montant des comptes des caisses : tracé s'il est lu en entier dans une source, sinon approché avec sa méthode. */
const statutNoeud = (n: Racine) =>
  num(n.tracabilite_pct) && n.tracabilite_pct >= 99.95
    ? badgeStatut('trace')
    : `${badgeStatut('approche')}<span class="aide">${num(n.tracabilite_pct) && n.tracabilite_pct > 0 ? ` part lue directement dans une source : ${h(pct(n.tracabilite_pct))}.` : ''}${n.note ? ` Calcul publié : ${h(fin(n.note))}` : ''}</span>`

/** Lien vers la vue qui publie le même argent (Sécurité sociale, budget de l'État) ; null quand aucune page ne la montre. */
function lienVue(l: Lien): string | null {
  if (l.vue === 'secu_cps') return lien('/explorer/secu', { m: 'protection2024', id: l.id })
  if (l.vue === 'secu_arbre') return lien('/explorer/secu', { m: 'organismes2024', id: l.id })
  if (l.vue === 'arbre_etat') return lien('/explorer/etat/detail', { m: 'execution2024', id: l.id })
  return null
}

function nomSource(idx: Index, cle: string): string {
  const noms = cle.split(' + ').map((k) => idx.sources[k.trim()]?.producteur ?? k.trim())
  return [...new Set(noms)].join(' et ')
}

const enCours = () => `<h1>${h(TITRE)}</h1>
<div class="en-cours"><p><strong>Données en cours d’intégration.</strong> Montant des pensions versées chaque année, régimes qui les versent, nombre de retraités, pension moyenne et origine de l’argent.</p><p>Cette page se remplira dès que les fichiers seront publiés.</p></div>
<p class="liens-sortie"><a href="#/explorer/secu">Les dépenses de la Sécurité sociale</a></p>
${partPersonnelle()}`

// ---------- Combien chaque année ----------

function blocMontant(p: Pensions | undefined, cps: Racine | null, org: Racine | null): string {
  const an = p ? String(p.derniere_annee) : ''
  const total = p?.montant_eur[an]
  if (!p || !num(total)) return ''
  const base = cps && cps.millesime === an && cps.md > 0 ? cps.md * 1e9 : null
  const part = base ? (total / base) * 100 : null
  const noeuds = org ? ['robss/vieillesse', 'complementaires/agirc_arrco', 'complementaires/autres_regimes'].map((i) => trouver(org, i)).filter((n): n is Racine => !!n) : []
  return `<section class="carte" data-cle aria-labelledby="titre-montant">
  <h2 id="titre-montant">Combien chaque année</h2>
  <p>Pensions de retraite versées en ${h(an)}, tous régimes (base, complémentaires et supplémentaires), droit direct et réversion :</p>
  <p class="grand-chiffre">${part !== null ? surligne(md(total / 1e9)) : h(md(total / 1e9))}</p>
  <p class="sous-chiffre">${part !== null ? `soit ${h(sur100(part))} sur 100 € de prestations de protection sociale versées en ${h(an)} (santé, famille, chômage, logement, retraites et autres). ` : ''}${badgeStatut('trace')}</p>
  ${source(cps?.source ?? 'DREES, comptes de la protection sociale', an)}
</section>
${
  noeuds.length && org
    ? `<details class="carte"><summary>Une autre façon de compter : les comptes des caisses (${h(org.millesime ?? '')})</summary>
  <p>Les caisses publient aussi leurs propres comptes (droits constatés). C’est une autre comptabilité que celle de la DREES : ces montants ne s’ajoutent pas au montant ci-dessus.</p>
  <div class="tableau-defile"><table><caption>Dépenses des caisses de retraite, ${h(org.millesime ?? '')}, en milliards d’euros</caption><thead><tr><th scope="col">Caisses</th><th scope="col" class="nombre">Montant</th><th scope="col">Statut</th></tr></thead><tbody>${noeuds
    .map((n) => `<tr><th scope="row"><a href="${h(lien('/explorer/secu', { m: 'organismes2024', id: n.id }))}">${h(n.nom)}</a></th><td class="nombre">${h(md(n.md))}</td><td>${statutNoeud(n)}</td></tr>`)
    .join('')}</tbody></table></div>
  ${source(org.source ?? '', org.millesime)}
</details>`
    : ''
}`
}

function blocCles(reg: Regimes, idx: Index, srcEacr: string): string {
  const t = reg.regimes.tous_regimes
  if (!t) return ''
  const an = String(idx.derniere_annee)
  const items: string[] = []
  const dd = t.retraites_droit_direct[an]
  if (num(dd)) items.push(`<li class="cle-famille"><strong>${h(millions(dd))}</strong><span>de personnes touchent une pension de retraite de droit direct fin ${h(an)}, chacune comptée une fois</span>${badgeStatut('approche')}</li>`)
  const pm = t.pension_droit_direct_eur_mois[an]
  if (num(pm)) items.push(`<li><strong>${h(eur(pm))}</strong><span>par mois : pension moyenne de droit direct en décembre ${h(an)}, tous régimes, hors réversion et hors majorations</span>${badgeStatut('approche')}</li>`)
  const nl = t.nouveaux_retraites_droit_direct[an]
  if (num(nl)) items.push(`<li><strong>${h(entier(nl))}</strong><span>personnes sont parties à la retraite en ${h(an)} (premier droit direct)</span>${badgeStatut('approche')}</li>`)
  if (!items.length) return ''
  return `<ul class="cles" aria-label="Chiffres clés des retraites en ${h(an)}">${items.join('')}</ul>
<p class="aide">${h(phrase(idx.tous_regimes?.note ?? 'estimation de la DREES : chaque personne comptée une fois'))}</p>
${source(srcEacr, an)}`
}

// ---------- Et ce que tu verses ? ----------

function blocPersonnel(partEtat: number | null): string {
  const lignes = session.complet?.lignes ?? session.resultat?.prelevements.filter((l) => l.inclus_dans_total_paye) ?? []
  const totalVerse = session.complet?.total.central ?? lignes.reduce((s, l) => s + (l.non_chiffre ? 0 : l.montant_annuel_eur.central), 0)
  if (!lignes.length || totalVerse <= 0)
    return `<section class="carte" aria-labelledby="titre-toi">
  <h2 id="titre-toi">Et ce que tu verses ?</h2>
  <p>Les cotisations de retraite prises sur ton salaire vont à l’Assurance retraite et à la retraite complémentaire. Fais le calcul pour voir combien, et ce que cela représente sur 100 € de ce que tu verses.</p>
  ${partPersonnelle()}
</section>`
  const r = partRetraite(lignes)
  const s100 = (r.total.central / totalVerse) * 100
  const patronal = session.resultat ? partRetraite(session.resultat.prelevements.filter((l) => l.famille === 'cotisation_patronale')) : null
  const versEtat = parAdministration(lignes).Etat ?? 0
  return `<section class="carte" aria-labelledby="titre-toi">
  <h2 id="titre-toi">Et ce que tu verses ?</h2>
  ${
    r.total.central > 0
      ? `<ul class="ruban" aria-hidden="true"><li class="r-tete">Tes 100 € versés</li><li class="r-etroit" data-f="${s100.toFixed(2)}"></li><li class="fond-papier r-reste" data-f="${(100 - s100).toFixed(2)}">${h(sur100(100 - s100))} vont ailleurs</li></ul>
  <p>Sur les ${h(eur(totalVerse))} que tu verses en un an (valeur centrale), <strong>${h(plage(r.total))}</strong> vont aux caisses de retraite, soit ${h(sur100(s100))} sur 100 €. ${badgeStatut(statutPlage(r.total))}</p>
  <ul>${r.caisses.map((c) => `<li>${h(c.nom)} : ${h(plage(c.f))}</li>`).join('')}</ul>`
      : `<p>Dans ton calcul, aucun prélèvement n’a de caisse de retraite comme destinataire publié.</p>`
  }
  ${r.sansAffectation.central > 0 ? `<p>${h(plage(r.sansAffectation))} de retenues de retraite n’ont pas encore de destinataire publié dans les données du site : ils ne sont pas comptés ci-dessus. ${badgeStatut('nonpub')}</p>` : ''}
  ${
    patronal && patronal.total.central > 0
      ? `<p>Ton employeur verse en plus ${h(plage(patronal.total))} par an de cotisations de retraite : elles ne sont pas comptées dans ce que tu verses.</p>`
      : ''
  }
  ${
    patronal && patronal.sansAffectation.central > 0
      ? `<p>Ton employeur verse aussi ${h(plage(patronal.sansAffectation))} par an de contributions de retraite dont le destinataire n’est pas encore publié dans les données du site. ${badgeStatut('nonpub')}</p>`
      : ''
  }
  ${
    versEtat > 0 && partEtat !== null
      ? `<p>Sur les ${h(eur(versEtat))} que tu verses à l’État, environ ${h(eur(versEtat * partEtat))} par an vont aux régimes spéciaux de retraite (crédits de la mission « Régimes sociaux et de retraite »), au prorata du budget de l’État 2024 : un ordre de grandeur. ${badgeStatut('approche')}</p>`
      : ''
  }
  <p class="aide">Calcul fait sur ton appareil, avec la répartition publiée de chaque prélèvement entre ses destinataires (site/data/prelevements/affectation.json).</p>
</section>`
}

// ---------- Qui verse les pensions ----------

function blocRegimesMontants(p: Pensions | undefined, cps: Racine | null): string {
  const an = p ? String(p.derniere_annee) : ''
  const total = p?.montant_eur[an]
  if (!p || !num(total) || total <= 0) return ''
  const lienOk = cps?.millesime === an
  const lignes = p.par_regime
    .filter((r) => num(r.montant_eur[an]) && (r.montant_eur[an] as number) > 0)
    .sort((a, b) => (b.montant_eur[an] as number) - (a.montant_eur[an] as number) || a.regime.localeCompare(b.regime, 'fr'))
  const parts: Part[] = lignes.map((r, i) => {
    const v = r.montant_eur[an] as number
    const nom = nomDrees(r.regime)
    return {
      nom,
      valeur: (v / total) * 100,
      texte: sur100((v / total) * 100),
      famille: i < 5 ? FAMILLES_TOURNANTES[i % FAMILLES_TOURNANTES.length] : 'papier',
      lien: lienOk ? lien('/explorer/secu', { m: 'protection2024', id: `${r.code_secteur}/${r.regime}` }) : undefined,
      detail: `${lisible(v)}${nom !== r.regime ? ` · libellé de la source : « ${r.regime} »` : ''}`,
    }
  })
  const reste = parts.slice(5)
  const sommeReste = reste.reduce((s, x) => s + x.valeur, 0)
  const pourBillet: Part[] = reste.length ? [...parts.slice(0, 5), { nom: `${reste.length} autres régimes`, valeur: sommeReste, texte: sur100(sommeReste), famille: 'papier' }] : parts
  return `<h3>Ce que chaque régime a versé en ${h(an)}</h3>
${billet(pourBillet, { etiquette: `Sur 100 € de pensions de retraite versées en ${an}, la part de chaque régime` })}
${listeParts(parts, `Pensions de retraite versées en ${an} par régime, sur 100 €`)}
<p class="aide" data-regle-ordre>${h(REGLE_MONTANTS)}</p>
<p class="aide">Montants publiés par la DREES, régime par régime ; leur somme est le montant de ${h(md(total / 1e9))}. Chaque régime ouvre son détail dans les comptes de la protection sociale. ${badgeStatut('trace')}</p>
${source(cps?.source ?? 'DREES, comptes de la protection sociale', an)}`
}

function blocRegimesTable(reg: Regimes, idx: Index, srcEacr: string): string {
  const an = String(idx.derniere_annee)
  const ids = Object.keys(reg.regimes).filter((id) => {
    const g = reg.regimes[id]
    return [g.retraites_droit_direct, g.retraites_tous_droits, g.nouveaux_retraites_droit_direct, g.pension_droit_direct_eur_mois].some((s) => num(s[an]))
  })
  if (!ids.length) return ''
  const typeLibelle = (t: string | null) => (t ? (idx.types[t] ?? t) : 'type non précisé dans la documentation de l’enquête')
  return `<h3>Retraités et pension moyenne, régime par régime, fin ${h(an)}</h3>
<div class="tableau-defile"><table><caption>Retraités au 31 décembre ${h(an)} et pension moyenne de décembre, par régime</caption><thead><tr><th scope="col">Régime</th><th scope="col" class="nombre">Retraités de droit direct</th><th scope="col" class="nombre">Pension moyenne de droit direct, par mois</th><th scope="col" class="nombre">Partis à la retraite en ${h(an)}</th></tr></thead><tbody>${ordreRegimes(ids, reg.regimes, an)
    .map((id) => {
      const g = reg.regimes[id]
      return `<tr><th scope="row">${h(g.nom)}<br /><span class="aide">${h(typeLibelle(g.type))}${id === 'tous_regimes' ? ' · estimation' : ''}</span></th><td class="nombre">${h(nb(g.retraites_droit_direct[an]))}</td><td class="nombre">${h(mensuel(g.pension_droit_direct_eur_mois[an]))}</td><td class="nombre">${h(nb(g.nouveaux_retraites_droit_direct[an]))}</td></tr>`
    })
    .join('')}</tbody></table></div>
<p class="aide" data-regle-ordre>${h(REGLE_REGIMES)}</p>
<p class="avertissement">Une personne qui a travaillé dans plusieurs régimes est comptée dans chacun : les nombres de retraités ne s’additionnent pas d’un régime à l’autre (seule la ligne « Tous régimes » compte chaque personne une fois). La pension moyenne d’un régime est la part versée par ce régime, pas la pension totale de la personne.</p>
<p class="aide">Statut : ${badgeStatut('trace')} valeurs transmises par les caisses à la DREES ; ${badgeStatut('approche')} ligne « Tous régimes », estimée par la DREES. « ${NON_PUBLIE} » : valeur absente de la source pour cette année.</p>
${source(srcEacr, an)}`
}

function blocEtatSre(etat: Etat | null, idx: Index): string {
  const re = etat?.retraites_etat
  if (!re) return ''
  const pops = Object.entries(re.populations)
  const an = pops.flatMap(([, p]) => anneesDe(p.effectif)).sort().pop()
  if (!an) return ''
  return `<h3>Les retraités de l’État, fin ${h(an)}</h3>
<p>Le Service des retraites de l’État publie ses propres chiffres, jusqu’en ${h(an)} : ${h(fin(re.definition))}</p>
<div class="tableau-defile"><table><caption>Pensions de droit direct de l’État en paiement au 31 décembre ${h(an)}</caption><thead><tr><th scope="col">Pensions</th><th scope="col" class="nombre">Nombre</th><th scope="col" class="nombre">Pension moyenne, par mois</th></tr></thead><tbody>${pops
    .map(([, p]) => `<tr><th scope="row">${h(p.nom)}</th><td class="nombre">${h(nb(p.effectif[an]))}</td><td class="nombre">${h(mensuel(p.pension_moyenne_eur_mois[an]))}</td></tr>`)
    .join('')}</tbody></table></div>
<p class="aide">Les mêmes pensions figurent dans l’enquête de la DREES, avec un champ différent : les écarts entre les deux sources sont détaillés plus bas. ${badgeStatut('trace')}</p>
${source(idx.sources.sre_civils?.titre ?? 'Service des retraites de l’État', idx.sources.sre_civils?.millesime)}`
}

// ---------- D'où vient l'argent ----------

const NOMS_ORIGINES: Record<string, string> = {
  contributions_employeurs: 'Contributions des employeurs',
  cotisations_salariales: 'Retenues sur la paie des agents',
  contribution_fspoeie_ratocem: 'Contribution aux fonds des ouvriers de l’État (pensions et rentes d’accident du travail)',
  transferts: 'Transferts d’autres caisses et du Fonds de solidarité vieillesse',
  budget_general: 'Budget général de l’État',
  cotisations_salariales_et_patronales: 'Cotisations des ouvriers de l’État et de leurs employeurs',
  autres: 'Autres recettes',
}

function blocAffectation(aff: Affectation | null): string {
  if (!aff) return ''
  const lignes = Object.values(aff.prelevements)
    .map((p) => ({ p, parts: (p.ventilation ?? []).filter((v) => Object.hasOwn(CAISSES_RETRAITE, v.destinataire)) }))
    .filter((x) => x.parts.length)
  if (!lignes.length) return ''
  return `<h3>Les prélèvements affectés aux caisses de retraite</h3>
<p>La répartition publiée de chaque prélèvement (${h(aff.millesime)}) envoie aux caisses de retraite :</p>
<ul>${lignes
    .map(
      ({ p, parts }) =>
        `<li><strong>${h(p.libelle)}</strong> : ${parts
          .map((v) => `${h(CAISSES_RETRAITE[v.destinataire])}, ${h(pct(v.part * 100))} du produit${num(v.montant_md) ? ` (${h(md(v.montant_md))} en ${h(aff.millesime)})` : ''}`)
          .join(' ; ')}.${p.note ? ` <span class="aide">${h(phrase(p.note))}</span>` : ''}</li>`,
    )
    .join('')}</ul>
<p class="aide" data-regle-ordre>Ordre : celui du fichier de répartition. ${badgeStatut('trace')}</p>
${source(aff.source, aff.millesime)}`
}

function blocCas(etat: Etat | null, idx: Index): string {
  const cas = etat?.cas_pensions
  if (!cas || !(cas.recettes_eur > 0)) return ''
  const origines = Object.entries(cas.recettes_par_origine_eur)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  const parts: Part[] = origines.map(([k, v], i) => {
    const s = cas.recettes_par_origine_pct[k] ?? (v / cas.recettes_eur) * 100
    return { nom: NOMS_ORIGINES[k] ?? k, valeur: s, texte: sur100(s), famille: FAMILLES_TOURNANTES[i % FAMILLES_TOURNANTES.length], detail: `${lisible(v)} · ${fin(cas.origines[k] ?? '')}` }
  })
  const src = idx.sources.plf25_recettes_cas
  return `<h3>Le compte des pensions de l’État (prévision pour 2025)</h3>
<p>Les pensions des fonctionnaires de l’État, des militaires et des ouvriers de l’État sont payées par un compte à part du budget de l’État, le compte d’affectation spéciale « Pensions ». Recettes prévues pour 2025 : <strong>${h(milliards(cas.recettes_eur))}</strong> ; dépenses prévues : ${h(milliards(cas.depenses_cp_eur))} (projet de loi de finances 2025, avant le vote et l’exécution). ${badgeStatut('trace')}</p>
${billet(parts, { etiquette: 'Sur 100 € de recettes prévues en 2025 pour le compte des pensions de l’État, la part de chaque origine' })}
${listeParts(parts, 'Recettes prévues en 2025 pour le compte des pensions de l’État, sur 100 €')}
<p class="aide" data-regle-ordre>${h(REGLE_RECETTES)}</p>
<p class="aide">${h(phrase(cas.methode))}</p>
<div class="tableau-defile"><table><caption>Compte des pensions de l’État : recettes et dépenses prévues pour 2025, par section</caption><thead><tr><th scope="col">Section</th><th scope="col" class="nombre">Recettes prévues</th><th scope="col" class="nombre">Dépenses prévues</th><th scope="col" class="nombre">Recettes moins dépenses</th></tr></thead><tbody>${cas.sections
    .map((s) => `<tr><th scope="row">${h(s.nom)}</th><td class="nombre">${h(lisible(s.recettes_eur))}</td><td class="nombre">${h(lisible(s.depenses_cp_eur))}</td><td class="nombre">${h(lisible(s.recettes_moins_depenses_eur))}</td></tr>`)
    .join('')}</tbody></table></div>
${source(src?.titre ?? 'Direction du budget', src?.millesime)}`
}

function blocCredits(etat: Etat | null, idx: Index, partEtat: number | null): string {
  const cr = etat?.credits_regimes_speciaux
  if (!cr || !cr.programmes.length) return ''
  const nomRegime = (id: string | null | undefined) => (id ? (idx.regimes.find((r) => r.id === id)?.nom ?? '') : '')
  const src = idx.sources.plf25_depenses
  return `<h3>Les crédits de l’État aux régimes spéciaux</h3>
<p>L’État verse chaque année des crédits à des régimes spéciaux de retraite (SNCF, RATP, mines, marins et autres). Dépensé en 2024 : <strong>${h(milliards(cr.total_execution_2024_eur))}</strong>${partEtat !== null ? `, soit ${h(sur100(partEtat * 100))} sur 100 € dépensés par l’État en 2024` : ''}. ${badgeStatut('trace')}</p>
<div class="tableau-defile"><table><caption>Crédits de la mission « Régimes sociaux et de retraite », par programme et par action, en milliards d’euros</caption><thead><tr><th scope="col">Programme et action</th><th scope="col" class="nombre">Dépensé en 2024</th><th scope="col" class="nombre">Prévu pour 2025 (projet de loi de finances)</th></tr></thead><tbody>${cr.programmes
    .map(
      (p) =>
        `<tr><th scope="row"><a href="${h(lien('/explorer/etat/detail', { m: 'execution2024', id: p.id }))}">${h(p.programme)} · ${h(p.nom)}</a></th><td class="nombre">${h(lisible(p.execution_2024_eur))}</td><td class="nombre">${h(lisible(p.plf_2025_cp_eur))}</td></tr>${p.actions
          .map(
            (a) =>
              `<tr><th scope="row"><span class="aide">${h(a.nom)}${nomRegime(a.regime) ? ` · régime : ${h(nomRegime(a.regime))}` : ''}</span></th><td class="nombre">${h(lisible(a.execution_2024_eur))}</td><td class="nombre">${h(lisible(a.plf_2025_cp_eur))}</td></tr>`,
          )
          .join('')}`,
    )
    .join('')}</tbody></table></div>
<p class="aide" data-regle-ordre>Ordre : celui des programmes et des actions du budget.</p>
<p class="aide">${h(phrase(cr.definition))}</p>
${source(`Budget de l’État, exécution 2024 ; ${src?.titre ?? 'Direction du budget'}`, '2024 et 2025')}`
}

function blocNonPublie(idx: Index): string {
  const s = idx.sources_inaccessibles.find((x) => /ressources par origine/i.test(x.source))
  return `<h3>Ce qui n’est pas publié en données ouvertes</h3>
<p class="absent">${s ? `${h(sansSigle(s.source))} : ${h(fin(s.motif))}` : 'Ressources par origine des autres caisses de retraite : non publiées en données ouvertes.'}</p>
<p>${badgeStatut('nonpub')} Cela décrit l’état de la publication, pas l’usage de l’argent. Pour voir chaque grand prélèvement (cotisations, CSG, TVA) et l’administration qui l’encaisse : <a href="#/explorer/recettes">D’où vient l’argent : les recettes</a>.</p>`
}

// ---------- L'évolution ----------

function serieRegime(id: string, reg: Regimes, idx: Index): string {
  const g = reg.regimes[id]
  if (!g) return ''
  const series = [g.retraites_droit_direct, g.retraites_tous_droits, g.nouveaux_retraites_droit_direct, g.pension_droit_direct_eur_mois]
  const ans = Object.keys(g.retraites_droit_direct)
    .filter((a) => series.some((s) => num(s[a])))
    .sort()
    .reverse()
  const zeros = Object.entries(g.zeros_source ?? {}).filter(([, l]) => l.length)
  const c = g.cotisants
  const cotAns = c ? anneesDe(c.valeurs).reverse() : []
  const rapport = c?.rapport_cotisants_retraites_publie ?? c?.rapport_cotisants_retraites_droit_direct
  const liens = (idx.regimes.find((r) => r.id === id)?.liens ?? []).map((l) => ({ l, href: lienVue(l) })).filter((x) => x.href)
  return `<div class="tableau-defile"><table><caption>${h(g.nom)} : retraités au 31 décembre et pension moyenne de décembre, ${h(ans[ans.length - 1] ?? '')} à ${h(ans[0] ?? '')}</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Retraités de droit direct</th><th scope="col" class="nombre">Retraités, droit direct ou réversion</th><th scope="col" class="nombre">Partis à la retraite dans l’année</th><th scope="col" class="nombre">Pension moyenne de droit direct, par mois</th></tr></thead><tbody>${ans
    .map(
      (a) =>
        `<tr><th scope="row">${h(a)}</th><td class="nombre">${h(nb(g.retraites_droit_direct[a]))}</td><td class="nombre">${h(nb(g.retraites_tous_droits[a]))}</td><td class="nombre">${h(nb(g.nouveaux_retraites_droit_direct[a]))}</td><td class="nombre">${h(mensuel(g.pension_droit_direct_eur_mois[a]))}</td></tr>`,
    )
    .join('')}</tbody></table></div>
<p class="aide">Montants en euros courants, sans correction de l’inflation. ${id === 'tous_regimes' ? `${badgeStatut('approche')} estimation de la DREES.` : `${badgeStatut('trace')} valeurs transmises par la caisse à la DREES.`}${
    zeros.length ? ` Années où la source donne une pension moyenne égale à 0 (valeur non reprise) : ${zeros.map(([k, l]) => `${k === 'pension_droit_direct_eur_mois' ? 'droit direct' : k === 'pension_totale_eur_mois' ? 'pension totale' : 'réversion'} ${l.join(', ')}`).join(' ; ')}.` : ''
  }</p>
${
  c && cotAns.length
    ? `<div class="tableau-defile"><table><caption>${h(g.nom)} : cotisants, ${h(cotAns[cotAns.length - 1])} à ${h(cotAns[0])}</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Cotisants</th><th scope="col" class="nombre">Cotisants pour un retraité de droit direct</th></tr></thead><tbody>${cotAns
        .map((a) => `<tr><th scope="row">${h(a)}</th><td class="nombre">${h(nb(c.valeurs[a]))}</td><td class="nombre">${num(rapport?.[a]) ? h(new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rapport![a] as number)) : NON_PUBLIE}</td></tr>`)
        .join('')}</tbody></table></div>
<p class="aide">Cotisants : ${h(fin(c.definition))}${c.rapport_methode ? ` Rapport : ${h(fin(c.rapport_methode))}` : c.rapport_cotisants_retraites_publie ? ' Rapport publié par la DREES.' : ''}</p>
${source(idx.sources[c.source]?.titre ?? c.source, idx.sources[c.source]?.millesime)}`
    : ''
}
${
  liens.length
    ? `<p>Montants de ce régime publiés dans d’autres vues (même argent vu d’ailleurs, jamais additionné) :</p><ul>${liens
        .map(({ l, href }) => `<li><a href="${h(href)}">${h(l.nom)}</a>${num(l.md) ? ` : ${h(md(l.md))}` : ''}${l.millesime ? ` (${h(l.millesime)})` : ''}. <span class="aide">${h(phrase(l.lecture))}</span></li>`)
        .join('')}</ul>`
    : ''
}`
}

function blocEvolution(p: Pensions | undefined, reg: Regimes, idx: Index, choisi: string, srcEacr: string, srcCps: string): string {
  const ans = p ? anneesDe(p.montant_eur) : []
  const options = [...new Set(['tous_regimes', ...idx.regimes.map((r) => r.id)])].filter((id) => reg.regimes[id])
  const premier = ans[0]
  const dernier = ans[ans.length - 1]
  return `<section aria-labelledby="titre-evolution">
<h2 id="titre-evolution">L’évolution</h2>
${
  p && ans.length
    ? `<h3>Montant des pensions versées, ${h(premier)} à ${h(dernier)}</h3>
${barres(
  ans.map((a) => ({ nom: a, valeur: p.montant_eur[a] as number, texte: md((p.montant_eur[a] as number) / 1e9) })),
  undefined,
  'Pensions de retraite versées, tous régimes, par année, en milliards d’euros',
  -1,
)}
<p>En euros courants (sans correction de l’inflation), le montant passe de ${h(md((p.montant_eur[premier] as number) / 1e9))} en ${h(premier)} à ${h(md((p.montant_eur[dernier] as number) / 1e9))} en ${h(dernier)}. Série reprise à partir de 2020 : c’est la première année du détail par prestation publié par la DREES. ${badgeStatut('trace')}</p>
${source(srcCps, `${premier} à ${dernier}`)}`
    : ''
}
<h3>Retraités et pension moyenne, année par année</h3>
<label for="ret-regime">Régime</label>
<select id="ret-regime">${options.map((id) => `<option value="${h(id)}"${id === choisi ? ' selected' : ''}>${h(reg.regimes[id].nom)}</option>`).join('')}</select>
<div id="ret-serie" aria-live="polite">${serieRegime(choisi, reg, idx)}</div>
${source(srcEacr, idx.sources.drees_eacr?.millesime)}
</section>`
}

// ---------- Écarts, limites, sources ----------

function blocEcarts(idx: Index, reg: Regimes): string {
  const derniers = new Map<string, Ecart>()
  for (const e of idx.ecarts) {
    const k = [e.regime, e.grandeur, e.objet, e.source, e.autre_source].join('|')
    const d = derniers.get(k)
    if (!d || e.annee > d.annee) derniers.set(k, e)
  }
  const lignes = [...derniers.values()]
  if (!lignes.length && !idx.ecarts_msa) return ''
  const valeur = (e: Ecart, x: number) => (e.grandeur === 'eur_mois' ? `${eur(x)} par mois` : entier(x))
  return `<details class="carte"><summary>Quand deux sources publient des chiffres différents</summary>
<p>Les écarts sont publiés tels quels : le site ne choisit pas entre les sources. Voici le dernier écart publié pour chaque régime et chaque grandeur.</p>
${
  lignes.length
    ? `<div class="tableau-defile"><table><caption>Écarts entre sources, dernière année publiée</caption><thead><tr><th scope="col">Régime et grandeur</th><th scope="col">Année</th><th scope="col" class="nombre">Une source</th><th scope="col" class="nombre">L’autre source</th><th scope="col" class="nombre">Écart</th><th scope="col">Lecture</th></tr></thead><tbody>${lignes
        .map(
          (e) =>
            `<tr><th scope="row">${h(reg.regimes[e.regime]?.nom ?? e.regime)}<br /><span class="aide">${h(e.objet)}</span></th><td>${h(e.annee)}</td><td class="nombre">${h(valeur(e, e.valeur))}<br /><span class="aide">${h(nomSource(idx, e.source))}</span></td><td class="nombre">${h(valeur(e, e.autre_valeur))}<br /><span class="aide">${h(nomSource(idx, e.autre_source))}</span></td><td class="nombre">${h(valeur(e, e.ecart))} (${h(pct(e.ecart_pct === 0 ? 0 : e.ecart_pct))})</td><td>${h(phrase(e.lecture_ecart))}</td></tr>`,
        )
        .join('')}</tbody></table></div>`
    : ''
}
${idx.ecarts_msa ? `<p>Retraités de la MSA : ${h(fin(idx.ecarts_msa.constat))} ${h(phrase(idx.ecarts_msa.lecture_ecart))}</p>` : ''}
</details>`
}

function blocLimites(idx: Index, etat: Etat | null): string {
  const limites = [...idx.limites, ...(etat?.limites ?? [])]
  const sources = Object.values(idx.sources)
  return `<h2>Ce que ces chiffres ne disent pas</h2>
<ul class="limites">${limites.map((l) => `<li>${traitStatut('approche')}<span>${h(phrase(l))}</span></li>`).join('')}</ul>
<p class="aide">Règles de cette page : seuls des totaux publiés sont repris ; aucun montant de pensions n’est recalculé à partir d’un nombre de retraités et d’une pension moyenne ; une valeur absente de la source est affichée « ${NON_PUBLIE} », jamais 0 ; les écarts entre sources sont montrés sans choisir l’une d’elles.</p>
<details class="carte"><summary>Sources et données non reprises</summary>
<ul>${sources
    .map((s) => `<li><a href="${h(s.page ?? s.url)}" rel="noopener noreferrer">${h(s.titre)}</a> (${h(s.producteur)}, ${h(s.millesime)}, ${h(s.licence)})</li>`)
    .join('')}</ul>
<p>Non repris :</p>
<ul>${idx.sources_inaccessibles.map((s) => `<li>${h(sansSigle(s.source))} : ${h(fin(s.motif))}</li>`).join('')}</ul>
</details>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const [idx, reg, etat, nat, cps, org, arbre, aff] = await Promise.all([
    chargerSiPresent<Index>('retraites/index.json'),
    chargerSiPresent<Regimes>('retraites/regimes.json'),
    chargerSiPresent<Etat>('retraites/etat.json'),
    chargerSiPresent<{ prestations: Record<string, Pensions> }>('prestations/nationales.json'),
    chargerSiPresent<Racine>('secu/cps/racine.json'),
    chargerSiPresent<Racine>('secu/arbre/racine.json'),
    chargerSiPresent<Racine>('arbre/racine.json'),
    chargerSiPresent<Affectation>('prelevements/affectation.json'),
  ])
  if (!idx || !reg) {
    cible.innerHTML = enCours()
    return
  }
  const pensions = nat?.prestations?.pensions_retraite
  const cr = etat?.credits_regimes_speciaux
  // Part des crédits aux régimes spéciaux dans la dépense de l'État : même millésime (exécution 2024) des deux côtés.
  const partEtat = cr && arbre && arbre.md > 0 && /2024/.test(arbre.millesime ?? '') && num(cr.total_execution_2024_eur) ? cr.total_execution_2024_eur / (arbre.md * 1e9) : null
  const srcEacr = idx.sources.drees_eacr?.titre ?? 'DREES, enquête annuelle auprès des caisses de retraite'
  const srcCps = cps?.source ?? 'DREES, comptes de la protection sociale'
  const an = String(idx.derniere_annee)
  const dd = reg.regimes.tous_regimes?.retraites_droit_direct[an]
  const demande = params.get('regime') ?? ''
  const choisi = Object.hasOwn(reg.regimes, demande) ? demande : reg.regimes.tous_regimes ? 'tous_regimes' : Object.keys(reg.regimes)[0]
  // Page des prestations versées aux ménages, quand elle existe : même argent présenté parmi toutes les prestations.
  const prestations = ROUTES.find((r) => /\/prestations$/.test(r.chemin))

  cible.innerHTML = `
<h1>${h(TITRE)}</h1>
<p class="chapeau">${num(dd) ? `Fin ${h(an)}, ${h(millions(dd))} de personnes touchent une pension de retraite de droit direct. ` : ''}Cette page montre combien les caisses de retraite versent chaque année, quelles caisses les versent, combien de personnes partent à la retraite, la pension moyenne et, quand c’est publié, d’où vient l’argent. Elle ne montre ni la pension d’une personne, ni de projection : les séries du Conseil d’orientation des retraites ne sont pas reprises, leur réutilisation étant soumise à son accord.</p>
${blocMontant(pensions, cps, org)}
${blocCles(reg, idx, srcEacr)}
${blocPersonnel(partEtat)}
<section aria-labelledby="titre-qui">
<h2 id="titre-qui">Qui verse les pensions</h2>
<p>Une même personne peut toucher plusieurs pensions : celle d’un régime de base (par exemple le régime général pour les salariés du privé), celle d’un régime complémentaire (par exemple l’Agirc-Arrco), ou une seule pension d’un régime intégré, qui fait les deux (fonctionnaires, SNCF, RATP et d’autres).</p>
${blocRegimesMontants(pensions, cps)}
${blocRegimesTable(reg, idx, srcEacr)}
${blocEtatSre(etat, idx)}
</section>
<section aria-labelledby="titre-origine">
<h2 id="titre-origine">D’où vient l’argent</h2>
<p>Les caisses de retraite reçoivent des cotisations (prises sur les salaires et versées par les employeurs), des impôts et taxes qui leur sont affectés, et des transferts de l’État ou d’autres caisses. En données ouvertes, cette origine n’est publiée que par morceaux : la répartition des prélèvements entre leurs destinataires, le compte des pensions de l’État et les crédits de l’État aux régimes spéciaux.</p>
${blocAffectation(aff)}
${blocCas(etat, idx)}
${blocCredits(etat, idx, partEtat)}
${blocNonPublie(idx)}
</section>
${blocEvolution(pensions, reg, idx, choisi, srcEacr, srcCps)}
${blocEcarts(idx, reg)}
${blocLimites(idx, etat)}
<p class="liens-sortie"><a href="#/explorer/secu">Les dépenses de la Sécurité sociale</a> <a href="#/explorer/recettes">D’où vient l’argent : les recettes</a> <a href="${h(lien('/explorer/etat/detail', { m: 'execution2024', id: 'Solidarite, travail et sante/Régimes sociaux et de retraite' }))}">Les régimes de retraite dans le budget de l’État</a>${prestations ? ` <a href="#${h(prestations.chemin)}">${h(prestations.titre)}</a>` : ''}</p>`

  const choix = cible.querySelector<HTMLSelectElement>('#ret-regime')
  const zone = cible.querySelector<HTMLElement>('#ret-serie')
  // L'attribut « selected » porte le choix dans la page prérendue ; la valeur est aussi posée ici (happy-dom l'ignore).
  if (choix) choix.value = choisi
  choix?.addEventListener('change', () => {
    if (zone) zone.innerHTML = serieRegime(choix.value, reg, idx)
  })
}

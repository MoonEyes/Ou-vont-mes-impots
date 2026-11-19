// Écran « Et si mon salaire changeait ? » (/calcul/et-si).
// Deux salaires nets avant impôt comparés, calculés sur l'appareil par le moteur du site (calcul/moteur-etendu.ts,
// exécuté dans son Web Worker par calcul/hors-fil.ts), avec la répartition entre destinataires du résultat
// (prelevements/affectation.json). La page montre la différence de ce que tu verses en un an, au total, par
// prélèvement et par destinataire (en euros et sur 100 €), puis le taux marginal : ce que deviennent 100 € de
// salaire brut en plus, à partir du salaire choisi. Des montants et leur explication, sans appréciation.
// Aucun montant n'est mis dans une adresse ni envoyé : tout reste en mémoire, sur l'appareil.
import exemple from '../exemple-lyon.json'
import { parDestinataire, type Affectation } from '../calcul/agregats'
import { destinataire, enregistrerDestinataires, LIBELLE_ADMINISTRATION } from '../calcul/destinataires'
import { ORDRE_ADMIN, parAdministration, sur100Entiers } from '../calcul/repartition'
import type { Administration, Destinataire, Fourchette, PersonneEtendue, Prelevement, ProfilEtendu, ResultatEtendu, ResultatOkEtendu, StatutActivite } from '../calcul/types'
import { billet, FAMILLE_ADMIN, listeParts, tableauBillet, type Part } from '../composants/billet'
import { chargerSiPresent } from '../donnees'
import { session } from '../etat'
import type { Rendu } from '../routeur'
import { appliquerLargeurs, badgeStatut, eur, h, legendeStatuts, pct, source, sur100, surligne, type Statut } from '../util'

export type Role = 'declarant1' | 'declarant2'

/** Statuts dont les prélèvements se calculent à partir du salaire net avant impôt : c'est ce salaire qui varie ici. */
export const STATUTS_VARIABLES: readonly StatutActivite[] = ['salarie_prive', 'apprenti', 'contractuel_public', 'fonctionnaire']

/** Exemple du site (celui de l'accueil, src/exemple-lyon.json) : personne seule, salariée du privé à temps plein, non cadre. */
export const EXEMPLE: ProfilEtendu = {
  version_contrat: '1.0',
  annee_revenus: 2025,
  residence: { zone: 'metropole', alsace_moselle: false },
  foyer: { situation: 'celibataire', enfants: [] },
  logement: { statut: 'locataire' },
  personnes: [
    {
      role: 'declarant1',
      statut_activite: 'salarie_prive',
      frontalier: false,
      cadre: false,
      temps_travail: { type: 'temps_plein' },
      salaire_net_avant_impot_mensuel: exemple.profil.net_mensuel,
    },
  ],
}

/** Curseur : bornes et pas (euros nets par mois) ; PageUp, PageDown et les boutons changent le salaire de SAUT euros. */
export const CURSEUR = { min: 100, max: 10000, pas: 10 }
export const SAUT = 100
/** Montant mensuel au-delà duquel le moteur refuse la saisie (calcul/moteur-etendu.ts). */
const PLAFOND_SAISIE = 100000
/** Délai sans nouvelle saisie avant de lancer le calcul (le curseur envoie un événement par cran). */
export const ATTENTE_MS = 300

/**
 * Lecture du taux de l'impôt sur le revenu : barème de l'article 197 du code général des impôts (tranches à 11, 30,
 * 41 et 45 %), appliqué au revenu imposable après l'abattement de 10 % sur les salaires ; décote égale au plafond moins
 * 45,25 % de l'impôt brut, qui fait monter l'impôt de 1,4525 fois le taux de la tranche tant qu'elle s'applique.
 */
const TAUX_BAREME = [0.11, 0.3, 0.41, 0.45]
const PART_IMPOSEE = 0.9
const TAUX_DECOTE = 0.4525
const TOLERANCE_TAUX = 0.006

const MOINS = '\u2212'

// --- Saisie ------------------------------------------------------------------------------------------------------

/** Montant saisi en texte : « 2 100,50 », « 2100.5 », « 2100 € » ; une saisie illisible donne NaN. */
export function lireMontant(v: string): number {
  const t = v.replace(/[\s\u00a0\u202f]/g, '').replace(',', '.').replace(/€$/, '')
  return t === '' ? NaN : Number(t)
}

/** Message d'erreur d'un salaire mensuel saisi, ou null s'il est utilisable. */
export function erreurMontant(x: number): string | null {
  if (!Number.isFinite(x)) return 'Écris un montant en chiffres, par exemple 2300.'
  if (x <= 0) return 'Indique un salaire supérieur à 0 €.'
  if (x > PLAFOND_SAISIE) return `Montant mensuel au-delà de ce que ce calcul gère (${eur(PLAFOND_SAISIE)}).`
  return null
}

/** Salaire comparé proposé au départ : environ 10 % de plus, arrondi à 50 €. */
export const salairePropose = (depart: number) => Math.max(depart + 50, Math.round((depart * 1.1) / 50) * 50)

const arrondi2 = (x: number) => Math.round(x * 100) / 100

/** Personnes du foyer dont le salaire peut varier ici. */
export function personnesVariables(p: ProfilEtendu): PersonneEtendue[] {
  return p.personnes.filter((q) => STATUTS_VARIABLES.includes(q.statut_activite) && !q.frontalier)
}

/** Même foyer, avec le salaire net avant impôt d'une personne changé (un traitement indiciaire saisi est alors retrouvé à partir du net). */
export function avecSalaire(p: ProfilEtendu, role: Role, net: number): ProfilEtendu {
  return {
    ...p,
    personnes: p.personnes.map((q) => {
      if (q.role !== role) return q
      const r: PersonneEtendue = { ...q, salaire_net_avant_impot_mensuel: arrondi2(net) }
      delete r.traitement_indiciaire_brut_mensuel
      return r
    }),
  }
}

// --- Résumé d'un calcul et différences ----------------------------------------------------------------------------

/** Ce que verse le foyer pour un salaire donné, regroupé comme la page l'affiche (montants centraux, par an). */
export interface Point {
  /** salaire net avant impôt mensuel de la personne dont le salaire change */
  net_mensuel: number
  net_annuel: number
  brut_annuel: number
  /** revenu imposable de la personne, avant l'abattement de 10 % */
  imposable_annuel: number
  /** ce que verse le foyer (lignes comptées dans le total versé), par an */
  total: number
  impot: number
  familles: Record<string, number>
  administrations: Record<string, number>
  destinataires: Record<string, number>
  /** montant de chaque destinataire, par famille de prélèvement */
  famillesDestinataires: Record<string, Record<string, number>>
  lignes: Record<string, number>
  /** ligne de prélèvement par identifiant (libellé, destinataire, ventilation) */
  infos: Record<string, Prelevement>
  noms: Record<string, Destinataire>
  statuts: Record<string, Statut>
  /** cotisations patronales du foyer (hors total versé), fourchette selon l'employeur */
  patronal: Fourchette
  reductionGenerale: boolean
  avertissements: string[]
  moteur: string
}

const GRAVITE: Record<Statut, number> = { trace: 0, approche: 1, nonpub: 2 }
const ajouter = (o: Record<string, number>, k: string, x: number) => (o[k] = (o[k] ?? 0) + x)
export const idLigne = (base: string, role: Role) => (role === 'declarant1' ? base : `${base}_${role}`)

export function resumerPoint(r: ResultatOkEtendu, role: Role): Point {
  const lignes = r.prelevements.filter((l) => l.inclus_dans_total_paye && !l.non_chiffre)
  const familles: Record<string, number> = {}
  const famillesDestinataires: Record<string, Record<string, number>> = {}
  const parLigne: Record<string, number> = {}
  const infos: Record<string, Prelevement> = {}
  const noms: Record<string, Destinataire> = {}
  const statuts: Record<string, Statut> = {}
  for (const l of lignes) {
    const m = (l.nature === 'reduction' ? -1 : 1) * l.montant_annuel_eur.central
    ajouter(familles, l.famille, m)
    ajouter(parLigne, l.id, m)
    infos[l.id] = l
    const parts = l.ventilation?.length ? l.ventilation.map((v) => ({ d: destinataire(v.destinataire), part: v.part })) : [{ d: l.destinataire, part: 1 }]
    const fd = (famillesDestinataires[l.famille] ??= {})
    for (const { d, part } of parts) {
      noms[d.id] ??= d
      ajouter(fd, d.id, m * part)
      const s: Statut = d.administration === 'Plusieurs' ? 'nonpub' : l.statut_affectation === 'non sourcee' ? 'approche' : 'trace'
      if (!statuts[d.id] || GRAVITE[s] > GRAVITE[statuts[d.id]]) statuts[d.id] = s
    }
  }
  const destinataires: Record<string, number> = {}
  for (const x of parDestinataire(lignes, false)) destinataires[x.destinataire] = x.montant_annuel_eur.central
  const p = r.entree.personnes.find((x) => x.role === role) ?? r.entree.personnes[0]
  return {
    net_mensuel: arrondi2(p.salaire_net_avant_impot_annuel / 12),
    net_annuel: p.salaire_net_avant_impot_annuel,
    brut_annuel: p.salaire_brut_annuel_estime.central,
    imposable_annuel: p.revenu_imposable_annuel ?? 0,
    total: Object.values(familles).reduce((s, x) => s + x, 0),
    impot: familles.impot_revenu ?? 0,
    familles,
    administrations: parAdministration(lignes),
    destinataires,
    famillesDestinataires,
    lignes: parLigne,
    infos,
    noms,
    statuts,
    patronal: r.totaux.patronal,
    reductionGenerale: r.prelevements.some((l) => l.id === idLigne('reduction_generale', role) && l.montant_annuel_eur.haut > 0.005),
    avertissements: r.avertissements.filter((a) => a.code !== 'DONNEE_ABSENTE').map((a) => a.message),
    moteur: `modele-social ${r.moteur.version}${r.moteur.publicodes ? ` et publicodes ${r.moteur.publicodes}` : ''}`,
  }
}

const difference = (x: Record<string, number>, y: Record<string, number>): Record<string, number> =>
  Object.fromEntries([...new Set([...Object.keys(x), ...Object.keys(y)])].map((k) => [k, (y[k] ?? 0) - (x[k] ?? 0)]))

export interface Ecart {
  total: number
  impot: number
  brut: number
  net: number
  imposable: number
  familles: Record<string, number>
  administrations: Record<string, number>
  destinataires: Record<string, number>
  lignes: Record<string, number>
  patronal: Fourchette
}

/** Ce qui change entre deux salaires (b moins a), par an. */
export function ecart(a: Point, b: Point): Ecart {
  return {
    total: b.total - a.total,
    impot: b.impot - a.impot,
    brut: b.brut_annuel - a.brut_annuel,
    net: b.net_annuel - a.net_annuel,
    imposable: b.imposable_annuel - a.imposable_annuel,
    familles: difference(a.familles, b.familles),
    administrations: difference(a.administrations, b.administrations),
    destinataires: difference(a.destinataires, b.destinataires),
    lignes: difference(a.lignes, b.lignes),
    patronal: { bas: b.patronal.bas - a.patronal.bas, central: b.patronal.central - a.patronal.central, haut: b.patronal.haut - a.patronal.haut },
  }
}

/** Taux marginal : chaque différence ramenée à 100 € de salaire brut en plus. */
export interface Marginal extends Ecart {
  /** versé sur 100 € de salaire brut en plus (cotisations, CSG, CRDS, impôt sur le revenu) */
  verse: number
  /** ce qui s'ajoute au salaire net, après impôt sur le revenu */
  reste: number
}

export function marginal(a: Point, b: Point): Marginal | null {
  const e = ecart(a, b)
  if (!(e.brut > 1)) return null
  const k = 100 / e.brut
  const fois = (o: Record<string, number>) => Object.fromEntries(Object.entries(o).map(([c, v]) => [c, v * k]))
  const p = [e.patronal.bas * k, e.patronal.central * k, e.patronal.haut * k]
  return {
    total: e.total * k,
    impot: e.impot * k,
    brut: 100,
    net: e.net * k,
    imposable: e.imposable * k,
    familles: fois(e.familles),
    administrations: fois(e.administrations),
    destinataires: fois(e.destinataires),
    lignes: fois(e.lignes),
    patronal: { bas: Math.min(...p), central: p[1], haut: Math.max(...p) },
    verse: e.total * k,
    reste: (e.net - e.impot) * k,
  }
}

export type LectureImpot = { cas: 'nul' } | { cas: 'seuil' } | { cas: 'tranche'; taux: number } | { cas: 'decote'; taux: number } | { cas: 'autre' }

/**
 * Ce qui explique la hausse de l'impôt : aucun impôt à verser, passage du seuil où l'impôt commence, taux d'une
 * tranche du barème, zone de la décote, ou autre combinaison (changement de tranche, quotient familial plafonné).
 * dImposable : revenu imposable en plus, avant l'abattement de 10 %.
 */
export function lireImpot(dImpot: number, dImposable: number, impotDepart: number): LectureImpot {
  if (impotDepart < 0.5) return Math.abs(dImpot) < 0.5 ? { cas: 'nul' } : { cas: 'seuil' }
  if (!(dImposable > 0)) return { cas: 'autre' }
  const r = dImpot / dImposable
  for (const t of TAUX_BAREME) if (Math.abs(r - PART_IMPOSEE * t) < TOLERANCE_TAUX) return { cas: 'tranche', taux: t }
  if (Math.abs(r - PART_IMPOSEE * TAUX_BAREME[0] * (1 + TAUX_DECOTE)) < TOLERANCE_TAUX) return { cas: 'decote', taux: TAUX_BAREME[0] }
  return { cas: 'autre' }
}

/** Répartition sur 100 € d'une différence, par clé, en euros entiers dont la somme fait 100 (clés de même signe que le total). */
export function sur100Difference(parCle: Record<string, number>, total: number): Record<string, number> {
  if (Math.abs(total) < 0.5) return {}
  const memeSens = Object.fromEntries(Object.entries(parCle).filter(([, v]) => v * total > 0 && Math.abs(v) >= 0.005).map(([k, v]) => [k, Math.abs(v)]))
  return sur100Entiers(memeSens)
}

// --- Formats -----------------------------------------------------------------------------------------------------

/** Montant signé à l'euro : « +1 105 € », « −240 € », « 0 € ». */
export function signe(x: number): string {
  const r = Math.round(x)
  if (r === 0) return '0 €'
  return `${r > 0 ? '+' : MOINS}${eur(Math.abs(r))}`
}
const signePct = (x: number) => (Math.abs(x) < 0.05 ? '0 %' : `${x > 0 ? '+' : MOINS}${pct(Math.abs(x))}`)
/** Montant sur 100 €, au centime près pour les petites valeurs. */
const s100 = (x: number) => (Math.abs(x) < 0.005 ? '0 €' : `${x < 0 ? MOINS : ''}${sur100(Math.abs(x))}`)
const parMois = (net: number) => `${eur(net)} net par mois`

// --- Calcul (Web Worker, résultats gardés en mémoire pendant la visite) ------------------------------------------

const memoire = new Map<string, Promise<ResultatEtendu>>()
async function calculer(profil: ProfilEtendu, affectation: Affectation | null): Promise<ResultatEtendu> {
  const cle = JSON.stringify([profil, !!affectation])
  let p = memoire.get(cle)
  if (!p) {
    p = import('../calcul/hors-fil').then((m) => m.calculerProfilHorsFil(profil, affectation ? { affectation } : {}))
    memoire.set(cle, p)
    p.catch(() => memoire.delete(cle))
    while (memoire.size > 80) memoire.delete(memoire.keys().next().value as string)
  }
  return p
}

// --- Textes ------------------------------------------------------------------------------------------------------

const SITUATIONS: Record<string, string> = {
  celibataire: 'seul·e',
  parent_isole: 'seul·e avec enfant(s)',
  couple_marie_pacse: 'en couple marié ou pacsé',
  couple_union_libre: 'en couple, sans être marié·es ni pacsé·es',
}
const STATUT_TEXTE: Record<string, string> = {
  salarie_prive: 'salarié·e du secteur privé',
  apprenti: 'apprenti·e',
  contractuel_public: 'contractuel·le de la fonction publique',
  fonctionnaire: 'fonctionnaire',
}

const FAMILLES_VERSEES: [string, string, string][] = [
  ['cotisation_salariale', 'Cotisations sociales prélevées sur ton salaire', 'retraite, chômage et les autres caisses'],
  ['csg_crds', 'CSG et CRDS', 'contribution sociale généralisée et contribution au remboursement de la dette sociale'],
  ['impot_revenu', 'Impôt sur le revenu', 'impôt du foyer, au barème'],
  ['impot_local', 'Impôts locaux (montant de ton avis)', 'ils ne dépendent pas de ton salaire'],
]

interface Etat {
  profil: ProfilEtendu
  exemple: boolean
  /** la saisie existe mais ne comporte aucun salaire qui puisse varier */
  sansSalaire: boolean
  role: Role
  variables: PersonneEtendue[]
}

function etatInitial(): Etat {
  const p = session.profil as ProfilEtendu | null
  const variables = p ? personnesVariables(p) : []
  if (p && variables.length) return { profil: p, exemple: false, sansSalaire: false, role: variables[0].role, variables }
  return { profil: EXEMPLE, exemple: true, sansSalaire: !!p, role: 'declarant1', variables: personnesVariables(EXEMPLE) }
}

function texteProfil(e: Etat): string {
  if (e.exemple)
    return `${e.sansSalaire ? 'Ta saisie ne comporte pas de salaire qui puisse varier ici (retraite, activité indépendante) : la page reprend l’exemple du site. ' : ''}Calcul pour l’exemple du site : une personne seule, sans enfant, salariée du secteur privé à temps plein, non cadre, en métropole. <a href="#/calcul">Indique ta situation</a> pour comparer avec ton propre foyer.`
  const p = e.profil
  const n = p.foyer.enfants.length
  const q = p.personnes.find((x) => x.role === e.role)!
  const autre = p.personnes.find((x) => x.role !== e.role)
  const qui = e.role === 'declarant1' ? 'le tien' : 'celui de ton ou ta conjoint·e'
  const reste = !autre
    ? ''
    : autre.salaire_net_avant_impot_mensuel && STATUTS_VARIABLES.includes(autre.statut_activite)
      ? ` ; ${e.role === 'declarant1' ? 'celui de ton ou ta conjoint·e' : 'le tien'} reste à ${h(parMois(autre.salaire_net_avant_impot_mensuel))}`
      : ` ; les revenus de l’autre personne restent ceux de ta saisie`
  return `Calcul pour ta situation saisie : ${h(SITUATIONS[p.foyer.situation] ?? '')}, ${n ? `${n} enfant${n > 1 ? 's' : ''} à charge` : 'sans enfant à charge'}. Le salaire qui change est ${qui} (${h(STATUT_TEXTE[q.statut_activite] ?? '')})${reste}. <a href="#/calcul">Modifier ma situation</a>`
}

function choixPersonne(e: Etat): string {
  if (e.variables.length < 2) return ''
  const option = (r: Role, texte: string) => `<label><input type="radio" name="es-personne" value="${r}"${r === e.role ? ' checked' : ''} /> ${texte}</label>`
  return `<p id="es-personne-titre"><strong>Le salaire qui change</strong></p>
      <div class="choix" role="radiogroup" aria-labelledby="es-personne-titre">${option('declarant1', 'Le tien')}${option('declarant2', 'Celui de ton ou ta conjoint·e')}</div>`
}

/** Noms des destinataires d'une famille de prélèvements, du montant le plus élevé au plus faible. */
function nomsFamille(b: Point, famille: string, max = 5): string {
  const d = Object.entries(b.famillesDestinataires[famille] ?? {})
    .filter(([, v]) => Math.abs(v) >= 0.5)
    .sort((x, y) => y[1] - x[1])
    .map(([id]) => b.noms[id]?.nom ?? destinataire(id).nom)
  return d.length > max ? `${d.slice(0, max).join(', ')} et ${d.length - max} autre${d.length - max > 1 ? 's' : ''}` : d.join(', ')
}

function phraseSur100(parts: Record<string, number>): string {
  return ORDRE_ADMIN.filter((a) => (parts[a] ?? 0) > 0)
    .map((a) => `<strong>${parts[a]} €</strong> ${h(FAMILLE_ADMIN[a]?.nom ?? a)}`)
    .join(', ')
}

// --- Blocs de résultat ------------------------------------------------------------------------------------------

function blocCle(a: Point, b: Point, e: Ecart, m: Marginal | null): string {
  const sens = e.total >= 0.5 ? 'plus' : e.total <= -0.5 ? 'moins' : null
  const parts = sens ? sur100Difference(e.administrations, e.total) : {}
  const phrase = phraseSur100(parts)
  const verse = m ? versePour100(m) : null
  const chiffre = sens || m ? surligne(signe(e.total)) : h(signe(e.total))
  return `<section class="recap" data-cle aria-labelledby="es-titre-cle">
    <p id="es-titre-cle" class="recap-titre">${sens ? `Ce que tu verserais en ${sens}, en un an` : 'Ce que tu verserais en plus, en un an'}</p>
    <p class="grand-chiffre">${chiffre}</p>
    <p>${sens ? `Soit ${h(signe(e.total / 12))} par mois. ` : 'Les deux salaires sont égaux : aucune différence. '}Avec ${h(parMois(b.net_mensuel))}, tu verserais ${h(eur(b.total))} par an ; avec ${h(parMois(a.net_mensuel))}, ${h(eur(a.total))}.</p>
    ${phrase ? `<p class="recap-sur100">Sur 100 € versés en ${sens} : ${phrase}.</p>` : ''}
    ${verse !== null ? `<p>Sur 100 € de salaire brut en plus à partir de ${h(parMois(b.net_mensuel))}, <strong>${verse} €</strong> seraient versés : c’est le taux marginal (${verse} %).</p>` : ''}
    <p class="source">calcul sur ton appareil (${h(b.moteur)}, règles de l’Urssaf), revenus 2025 ; destinataires : projet de loi de financement de la Sécurité sociale pour 2026 (annexe 3) et projet de loi de finances pour 2026 (évaluation des voies et moyens). <a href="#/methode">Méthode</a></p>
  </section>`
}

function blocFamilles(a: Point, b: Point, e: Ecart): string {
  const items = FAMILLES_VERSEES.filter(([f]) => Math.abs(a.familles[f] ?? 0) >= 0.5 || Math.abs(b.familles[f] ?? 0) >= 0.5).map(([f, libelle, detail]) => {
    const d = e.familles[f] ?? 0
    const dest = nomsFamille(b, f)
    return `<li>
      <span>${h(libelle)}</span>
      <span class="montant">${h(Math.round(d) === 0 ? 'inchangé' : signe(d))}<span class="visuellement-cache"> par an</span></span>
      <span class="dest">${h(detail)} · de ${h(eur(a.familles[f] ?? 0))} à ${h(eur(b.familles[f] ?? 0))} par an${dest ? ` · Va à : ${h(dest)}` : ''}</span>
    </li>`
  })
  return `<h2>Ce qui change, prélèvement par prélèvement</h2>
<p class="chapeau">Différence par an entre ${h(parMois(b.net_mensuel))} et ${h(parMois(a.net_mensuel))}.</p>
<ul class="lignes">${items.join('')}
  <li><span>Total de ce que tu verses</span><span class="montant">${h(signe(e.total))}<span class="visuellement-cache"> par an</span></span><span class="dest">de ${h(eur(a.total))} à ${h(eur(b.total))} par an</span></li>
</ul>`
}

function blocDestinataires(a: Point, b: Point, e: Ecart): string {
  const nom = (id: string): Destinataire => b.noms[id] ?? a.noms[id] ?? destinataire(id)
  const ids = Object.keys(e.destinataires).filter((id) => Math.abs(a.destinataires[id] ?? 0) >= 0.5 || Math.abs(b.destinataires[id] ?? 0) >= 0.5)
  const rang = (id: string) => {
    const i = ORDRE_ADMIN.indexOf(nom(id).administration as (typeof ORDRE_ADMIN)[number])
    return i < 0 ? ORDRE_ADMIN.length : i
  }
  ids.sort((x, y) => rang(x) - rang(y) || (b.destinataires[y] ?? 0) - (b.destinataires[x] ?? 0) || nom(x).nom.localeCompare(nom(y).nom, 'fr'))
  const avecPart = Math.abs(e.total) >= 0.5
  const sens = e.total > 0 ? 'plus' : 'moins'
  const statuts = new Set<Statut>()
  const lignes = ids.map((id) => {
    const d = nom(id)
    const st = b.statuts[id] ?? a.statuts[id] ?? 'trace'
    statuts.add(st)
    const diff = e.destinataires[id] ?? 0
    const part = avecPart && diff * e.total > 0 ? s100((Math.abs(diff) / Math.abs(e.total)) * 100) : '0 €'
    return `<tr><th scope="row">${h(d.nom)}<br /><span class="aide">${h(LIBELLE_ADMINISTRATION[d.administration as Administration] ?? d.administration)} · ${h(eur(a.destinataires[id] ?? 0))} puis ${h(eur(b.destinataires[id] ?? 0))} par an</span> ${badgeStatut(st)}</th><td class="nombre">${h(signe(diff))}</td>${avecPart ? `<td class="nombre">${h(part)}</td>` : ''}</tr>`
  })
  return `<h2>Ce qui change, par destinataire</h2>
<div class="tableau-defile"><table>
  <caption>Ce que reçoit chaque destinataire : différence par an entre les deux salaires</caption>
  <thead><tr><th scope="col">Destinataire</th><th scope="col" class="nombre">Différence par an</th>${avecPart ? `<th scope="col" class="nombre">Sur 100 € versés en ${sens}</th>` : ''}</tr></thead>
  <tbody>${lignes.join('')}</tbody>
  <tfoot><tr><th scope="row">Total</th><td class="nombre">${h(signe(e.total))}</td>${avecPart ? '<td class="nombre">100 €</td>' : ''}</tr></tfoot>
</table></div>
<p class="aide" data-regle-ordre>Ordre : Sécurité sociale, État, collectivités, puis sans destinataire publié ; dans chaque groupe, du montant le plus élevé au plus faible avec le salaire comparé.</p>
${legendeStatuts([...statuts].sort((x, y) => GRAVITE[x] - GRAVITE[y]))}`
}

/** Parts du billet « 100 € de salaire brut en plus » : destinataires, puis ce qui s'ajoute au salaire net après impôt. */
export function partsMarginal(m: Marginal): Part[] {
  const valeurs: Record<string, number> = {}
  for (const a of ORDRE_ADMIN) if ((m.administrations[a] ?? 0) >= 0.005) valeurs[a] = m.administrations[a]
  valeurs.reste = Math.max(0, m.reste)
  const ent = sur100Entiers(valeurs)
  const detail: Record<string, string> = {
    'Securite sociale': 'cotisations, CSG et CRDS',
    Etat: 'impôt sur le revenu',
    'Collectivites locales': 'commune, département, région',
    Plusieurs: 'les documents publics ne disent pas qui reçoit',
  }
  const parts: Part[] = ORDRE_ADMIN.filter((a) => (ent[a] ?? 0) > 0 && FAMILLE_ADMIN[a]).map((a) => ({
    nom: FAMILLE_ADMIN[a].nom,
    valeur: ent[a],
    texte: `${ent[a]} €`,
    famille: FAMILLE_ADMIN[a].famille,
    lien: FAMILLE_ADMIN[a].lien,
    detail: detail[a],
  }))
  if ((ent.reste ?? 0) > 0) parts.push({ nom: 'Ton salaire net après impôt', valeur: ent.reste, texte: `${ent.reste} €`, famille: 'papier', detail: 'ce qui s’ajoute à ton salaire' })
  return parts
}

/** Taux marginal affiché, en euros entiers sur 100 € : la somme des parts versées du billet (le même nombre partout). */
export const versePour100 = (m: Marginal) =>
  partsMarginal(m)
    .filter((p) => p.famille !== 'papier')
    .reduce((s, p) => s + p.valeur, 0)

function ligneMarginale(id: string, x: number, c: Point): string {
  const l = c.infos[id]
  const v = l?.ventilation && l.ventilation.length > 1 ? l.ventilation : null
  const dest = v ? v.map((p) => `${destinataire(p.destinataire).nom} ${pct(p.part * 100, p.part < 0.01 ? 1 : 0)}`).join(', ') : (l?.destinataire.nom ?? '')
  return `<li><span>${h(l?.libelle ?? id)}</span><span class="montant">${h(s100(x))}</span><span class="dest">${dest ? `Va à : ${h(dest)}` : ''}</span></li>`
}

function explications(b: Point, c: Point, m: Marginal, role: Role): string[] {
  const out: string[] = []
  const social = (m.familles.cotisation_salariale ?? 0) + (m.familles.csg_crds ?? 0)
  out.push(
    `Cotisations sociales, CSG et CRDS : <strong>${h(s100(social))}</strong> sur 100 €. Elles sont calculées en pourcentage du salaire brut, à des taux fixés par la loi et par les accords de retraite complémentaire.`,
  )
  const plafonnee = idLigne('vieillesse_plafonnee_salarie', role)
  if ((b.lignes[plafonnee] ?? 0) > 0.5 && Math.abs(m.lignes[plafonnee] ?? 0) < 0.05)
    out.push('Ton salaire brut dépasse le plafond de la Sécurité sociale : la cotisation de retraite de base plafonnée ne change plus (le détail ligne par ligne montre les autres taux).')
  const lecture = lireImpot(m.impot, m.imposable, b.impot)
  const imp = `Impôt sur le revenu : <strong>${h(s100(m.impot))}</strong> sur 100 €.`
  const base = `Ton revenu imposable augmente de ${h(s100(m.imposable))} (le salaire brut moins les cotisations et la CSG déductible) ; après l’abattement de 10 % pour frais professionnels`
  if (lecture.cas === 'nul') out.push(`${imp} À ce niveau de revenu, ton foyer n’a pas d’impôt sur le revenu à verser, et 100 € de plus n’en créent pas (abattement, barème et décote).`)
  else if (lecture.cas === 'seuil')
    out.push(`${imp} À ce niveau de revenu, ton foyer n’a pas d’impôt sur le revenu à verser ; avec ces 100 €, il passe le seuil à partir duquel l’impôt est dû (après l’abattement de 10 %, le barème et la décote).`)
  else if (lecture.cas === 'tranche') out.push(`${imp} ${base}, il est imposé au taux de ${pct(lecture.taux * 100, 0)} : c’est la tranche du barème où se situe ton foyer.`)
  else if (lecture.cas === 'decote')
    out.push(
      `${imp} ${base}, il est imposé au taux de ${pct(lecture.taux * 100, 0)}. Ton impôt est aussi dans la zone de la décote, la réduction prévue pour les impôts faibles : elle diminue quand l’impôt augmente, si bien que l’impôt monte de ${pct(lecture.taux * (1 + TAUX_DECOTE) * 100, 0)} du revenu imposé, et non de ${pct(lecture.taux * 100, 0)}.`,
    )
  else out.push(`${imp} Il dépend du revenu imposable du foyer, du nombre de parts (quotient familial), du barème par tranches et de la décote : ici, ces 100 € font passer ton foyer d’une règle à une autre.`)
  const reste = Math.round(m.reste * 10) / 10
  out.push(`Le reste, <strong>${h(s100(reste))}</strong>, s’ajoute à ton salaire net après impôt.`)
  const pat = m.patronal
  const montant = Math.round(pat.bas) === Math.round(pat.haut) ? `${h(s100(pat.central))}` : `entre ${h(s100(pat.bas))} et ${h(s100(pat.haut))}`
  out.push(
    `En plus, ton employeur verserait ${montant} de cotisations patronales pour ces 100 €, selon l’entreprise (taux d’accidents du travail, versement mobilité, effectif, réduction générale). Elles ne sont pas comptées dans ce que tu verses.${
      c.reductionGenerale || b.reductionGenerale ? ' À ce niveau de salaire s’applique la réduction générale de cotisations patronales : elle diminue quand le salaire augmente, ce qui explique une partie de ce montant.' : ''
    }`,
  )
  return out
}

function blocMarginal(b: Point, c: Point, m: Marginal, role: Role): string {
  const parts = partsMarginal(m)
  const verse = versePour100(m)
  const lignes = Object.entries(m.lignes)
    .filter(([, x]) => Math.abs(x) >= 0.005)
    .sort((x, y) => y[1] - x[1])
    .map(([id, x]) => ligneMarginale(id, x, c))
  const etiquette = `Billet de 100 € de salaire brut en plus, découpé : ${parts.map((p) => `${p.nom} ${p.texte}`).join(', ')}`
  return `<section aria-labelledby="es-titre-marginal">
<h2 id="es-titre-marginal">Sur 100 € de salaire brut en plus</h2>
<p class="chapeau">Le taux marginal est la part de 100 € de salaire brut en plus qui serait versée en cotisations, CSG, CRDS et impôt sur le revenu. À partir de ${h(parMois(b.net_mensuel))} (${h(eur(b.brut_annuel / 12))} brut par mois) : <strong>${verse} € sur 100 €</strong>.</p>
${billet(parts, { etiquette, talon: { grand: '100', petit: 'euros brut' } })}
${listeParts(parts, 'Ce que deviennent 100 € de salaire brut en plus')}
${tableauBillet(parts, 'Ce que deviennent 100 € de salaire brut en plus', ['Part', 'Sur 100 € brut'])}
<details>
  <summary>Ligne par ligne, sur 100 € de salaire brut en plus</summary>
  <ul class="lignes">${lignes.join('')}<li><span>S’ajoute au salaire net après impôt</span><span class="montant">${h(s100(m.reste))}</span><span class="dest">salaire brut moins ce qui est versé</span></li></ul>
</details>
<h3>Ce qui explique ce montant</h3>
<ul>${explications(b, c, m, role)
    .map((t) => `<li>${t}</li>`)
    .join('')}</ul>
<p class="aide">Calcul fait pour une hausse d’environ 100 € brut par mois à partir du salaire comparé, puis ramené à 100 €.</p>
</section>`
}

/** Phrase annoncée aux lecteurs d'écran une fois le calcul fini (une seule, après la dernière saisie). */
export function phraseAnnonce(a: Point, b: Point, e: Ecart, m: Marginal | null): string {
  const diff =
    Math.abs(e.total) < 0.5
      ? `Même salaire qu’au départ, ${parMois(b.net_mensuel)} : aucune différence.`
      : `Avec ${parMois(b.net_mensuel)} au lieu de ${eur(a.net_mensuel)}, tu verserais ${eur(Math.abs(e.total))} de ${e.total > 0 ? 'plus' : 'moins'} par an.`
  return m ? `${diff} Sur 100 € de salaire brut en plus, ${versePour100(m)} € seraient versés.` : diff
}

// --- Écran -------------------------------------------------------------------------------------------------------

export function rendre(cible: HTMLElement): Rendu {
  const etat = etatInitial()
  const q0 = etat.profil.personnes.find((x) => x.role === etat.role)
  const net0 = q0?.salaire_net_avant_impot_mensuel ?? NaN
  const depart0 = Number.isFinite(net0) ? arrondi2(net0) : NaN
  const nouveau0 = Number.isFinite(depart0) ? salairePropose(depart0) : NaN
  const valeur = (x: number) => (Number.isFinite(x) ? String(x) : '')
  const borne = (x: number) => Math.min(Math.max(x, CURSEUR.min), Math.max(CURSEUR.max, x))

  cible.innerHTML = `
<h1>Et si mon salaire changeait ?</h1>
<p class="chapeau">Change ton salaire net avant impôt : le site recalcule, sur ton appareil, ce que tu verserais en un an (cotisations sociales, contribution sociale généralisée ou CSG, contribution au remboursement de la dette sociale ou CRDS, impôt sur le revenu) et à qui cela irait, puis ce que deviennent 100 € de salaire brut en plus. La page ne compte pas les prestations qui dépendent aussi du revenu (prime d’activité, aides au logement), ni les taxes sur tes achats, ni tes impôts locaux.</p>
<p class="aide" id="es-profil">${texteProfil(etat)}</p>
<div class="colonnes">
  <form id="es-form" novalidate>
    <fieldset>
      <legend>Les deux salaires comparés</legend>
      ${choixPersonne(etat)}
      <label for="es-depart">Salaire de départ : net avant impôt, par mois (en euros)</label>
      <input id="es-depart" type="text" inputmode="decimal" spellcheck="false" autocomplete="off" value="${valeur(depart0)}" aria-describedby="es-depart-aide es-depart-msg" />
      <p class="aide" id="es-depart-aide">${etat.exemple ? 'Celui de l’exemple du site.' : 'Celui de ta saisie.'} La ligne « Net à payer avant impôt sur le revenu » de ta fiche de paie.</p>
      <p class="message-champ" id="es-depart-msg" hidden></p>
      <label for="es-nouveau">Et s’il était de : net avant impôt, par mois (en euros)</label>
      <input id="es-nouveau" type="text" inputmode="decimal" spellcheck="false" autocomplete="off" value="${valeur(nouveau0)}" aria-describedby="es-ecart es-nouveau-msg" />
      <p class="message-champ" id="es-nouveau-msg" hidden></p>
      <label for="es-curseur">Ou règle le salaire comparé au curseur</label>
      <input id="es-curseur" class="et-si-curseur" type="range" min="${CURSEUR.min}" max="${Math.max(CURSEUR.max, Math.ceil((Number.isFinite(nouveau0) ? nouveau0 : 0) / 1000) * 1000)}" step="${CURSEUR.pas}" value="${Number.isFinite(nouveau0) ? borne(nouveau0) : CURSEUR.min}" aria-valuetext="${h(Number.isFinite(nouveau0) ? parMois(nouveau0) : '')}" aria-describedby="es-ecart es-curseur-aide" />
      <p class="aide" id="es-curseur-aide">Au clavier : flèches pour ${CURSEUR.pas} €, Page précédente et Page suivante pour ${SAUT} €.</p>
      <div class="actions">
        <button type="button" data-pas="-${SAUT}" aria-label="${MOINS}${SAUT} € sur le salaire comparé">${MOINS}${SAUT} €</button>
        <button type="button" data-pas="${SAUT}" aria-label="+${SAUT} € sur le salaire comparé">+${SAUT} €</button>
      </div>
      <p id="es-ecart"></p>
      <p class="chargement" id="es-etat">Calcul en cours sur ton appareil…</p>
    </fieldset>
    <p class="aide">Rien de ce que tu saisis n’est envoyé ni enregistré, et aucun montant n’est mis dans l’adresse de la page.</p>
  </form>
  <div id="es-cle"></div>
</div>
<p id="es-annonce" class="visuellement-cache" role="status" aria-live="polite" aria-atomic="true"></p>
<div id="es-detail"></div>
<h2>Ce que ce calcul ne compte pas</h2>
<ul>
  <li>Les prestations qui dépendent aussi du revenu (prime d’activité, aides au logement, bourses) : un autre salaire peut les changer ; le site ne les calcule pas.</li>
  <li>Les taxes sur tes achats (TVA, carburant, tabac, alcool) : le site les estime par dixième de la population classée selon le niveau de vie, une moyenne qui change par paliers ; elles ne sont pas recalculées ici. Tes impôts locaux ne dépendent pas de ton salaire.</li>
  <li>L’impôt sur le revenu est celui d’un foyer sans autres revenus, sans frais réels, réductions ni crédits d’impôt. Revenus 2025 : cotisations au barème du 1er janvier 2025, impôt au barème appliqué en 2026.</li>
  <li>Les cotisations de ton employeur ne font pas partie de ce que tu verses : elles sont indiquées à part, en fourchette.</li>
</ul>
${source('calcul sur ton appareil avec modele-social (règles de l’Urssaf, licence MIT) et publicodes ; répartition entre destinataires : site/data/prelevements/affectation.json', 'revenus 2025')}
<h2>Et maintenant ?</h2>
<ul class="cartes par-3">
  <li><a href="${session.resultat && !etat.exemple ? '#/calcul/resultat' : '#/calcul'}"><strong>${session.resultat && !etat.exemple ? 'Ce que tu verses, ligne par ligne' : 'Calculer pour ta situation'}</strong><span>Ton résultat complet, avec les taxes sur tes achats et tes impôts locaux.</span></a></li>
  <li><a href="#/explorer/secu"><strong>La Sécurité sociale</strong><span>Retraites, santé, famille, chômage : les dépenses des organismes sociaux.</span></a></li>
  <li><a href="#/explorer/etat"><strong>Où va l’argent de l’État</strong><span>Les grands postes du budget, jusqu’à la ligne votée.</span></a></li>
</ul>`

  const $ = <T extends HTMLElement>(s: string) => cible.querySelector(s) as T
  const champDepart = $<HTMLInputElement>('#es-depart')
  const champNouveau = $<HTMLInputElement>('#es-nouveau')
  const curseur = $<HTMLInputElement>('#es-curseur')
  const zoneEcart = $('#es-ecart')
  const zoneEtat = $('#es-etat')
  const zoneCle = $('#es-cle')
  const zoneDetail = $('#es-detail')
  const zoneAnnonce = $('#es-annonce')
  let affectation: Affectation | null = null
  let jeton = 0
  let minuterie: ReturnType<typeof setTimeout> | undefined
  let derniereAnnonce = ''

  const message = (champ: HTMLInputElement, texte: string | null) => {
    const msg = $(`#${champ.id}-msg`)
    if (texte) {
      champ.setAttribute('aria-invalid', 'true')
      msg.textContent = texte
      msg.hidden = false
    } else {
      champ.removeAttribute('aria-invalid')
      msg.textContent = ''
      msg.hidden = true
    }
  }

  /** Lit les deux champs ; signale une saisie illisible sur son champ. */
  const lire = (): { depart: number; nouveau: number } | null => {
    const depart = lireMontant(champDepart.value)
    const nouveau = lireMontant(champNouveau.value)
    const ed = erreurMontant(depart)
    const en = erreurMontant(nouveau)
    message(champDepart, ed)
    message(champNouveau, en)
    return ed || en ? null : { depart, nouveau }
  }

  /** Curseur et phrase d'écart suivent le salaire comparé, tout de suite (sans calcul). */
  const suivre = (nouveau: number) => {
    if (!Number.isFinite(nouveau) || nouveau <= 0) return
    if (nouveau > Number(curseur.max)) curseur.max = String(Math.ceil(nouveau / 1000) * 1000)
    curseur.value = String(Math.min(Math.max(nouveau, Number(curseur.min)), Number(curseur.max)))
    curseur.setAttribute('aria-valuetext', parMois(nouveau))
  }
  const majEcart = () => {
    const d = lireMontant(champDepart.value)
    const n = lireMontant(champNouveau.value)
    zoneEcart.textContent =
      erreurMontant(d) || erreurMontant(n)
        ? ''
        : Math.abs(n - d) < 0.005
          ? 'Même salaire qu’au départ.'
          : `Soit ${signe(n - d)} par mois par rapport au départ (${signePct(((n - d) / d) * 100)}).`
  }

  const montrerErreur = (texte: string) => {
    zoneCle.innerHTML = `<p class="erreur" tabindex="-1">${h(texte)}</p>`
    zoneDetail.innerHTML = ''
  }

  /** Région polie : une phrase par calcul fini (ou par erreur de saisie), jamais deux fois la même à la suite. */
  const dire = (texte: string) => {
    if (!texte || texte === derniereAnnonce) return
    derniereAnnonce = texte
    zoneAnnonce.textContent = texte
  }

  async function actualiser(interaction: boolean) {
    const moi = ++jeton
    const v = lire()
    if (!v) {
      zoneEtat.hidden = true
      const champ = [champDepart, champNouveau].find((c) => c.hasAttribute('aria-invalid'))
      if (interaction && champ) dire(`${champ === champDepart ? 'Salaire de départ' : 'Salaire comparé'} : ${$(`#${champ.id}-msg`).textContent ?? ''}`)
      return
    }
    zoneEtat.hidden = false
    try {
      const { profil, role } = etat
      const [ra, rb] = await Promise.all([calculer(avecSalaire(profil, role, v.depart), affectation), calculer(avecSalaire(profil, role, v.nouveau), affectation)])
      if (moi !== jeton) return
      for (const [r, champ] of [[ra, champDepart], [rb, champNouveau]] as const)
        if (r.statut === 'erreur') {
          if (r.erreur.code === 'SAISIE_INVALIDE') message(champ, r.erreur.message)
          else montrerErreur(r.erreur.message || 'Le calcul est indisponible pour ce cas.')
          if (interaction) dire(r.erreur.message)
          return
        }
      const a = resumerPoint(ra as ResultatOkEtendu, role)
      const b = resumerPoint(rb as ResultatOkEtendu, role)
      // Taux marginal : environ 100 € brut de plus par mois, d'après le rapport net sur brut du salaire comparé.
      const pas = arrondi2((SAUT * b.net_annuel) / b.brut_annuel)
      const rc = Number.isFinite(pas) && pas > 0 ? await calculer(avecSalaire(profil, role, v.nouveau + pas), affectation) : null
      if (moi !== jeton) return
      const c = rc && rc.statut === 'ok' ? resumerPoint(rc as ResultatOkEtendu, role) : null
      const e = ecart(a, b)
      const m = c ? marginal(b, c) : null
      const avertissements = [...new Set([...a.avertissements, ...b.avertissements])]
      zoneCle.innerHTML = blocCle(a, b, e, m)
      zoneDetail.innerHTML = `${avertissements.map((x) => `<p class="avertissement">${h(x)}</p>`).join('')}${
        affectation ? '' : '<p class="aide">La répartition de la CSG entre les branches de la Sécurité sociale n’est pas disponible : elle apparaît comme « plusieurs branches ».</p>'
      }${blocFamilles(a, b, e)}${blocDestinataires(a, b, e)}${m && c ? blocMarginal(b, c, m, role) : ''}`
      appliquerLargeurs(zoneCle)
      appliquerLargeurs(zoneDetail)
      if (interaction) dire(phraseAnnonce(a, b, e, m))
    } catch (err) {
      console.error(err)
      if (moi === jeton) montrerErreur('Le calcul est indisponible pour le moment. Tu peux toujours explorer le budget.')
    } finally {
      if (moi === jeton) zoneEtat.hidden = true
    }
  }

  const planifier = () => {
    zoneEtat.hidden = false
    clearTimeout(minuterie)
    minuterie = setTimeout(() => void actualiser(true), ATTENTE_MS)
  }

  champNouveau.addEventListener('input', () => {
    suivre(lireMontant(champNouveau.value))
    majEcart()
    planifier()
  })
  champDepart.addEventListener('input', () => {
    majEcart()
    planifier()
  })
  curseur.addEventListener('input', () => {
    champNouveau.value = curseur.value
    curseur.setAttribute('aria-valuetext', parMois(Number(curseur.value)))
    message(champNouveau, null)
    majEcart()
    planifier()
  })
  const decaler = (x: number) => {
    const n = lireMontant(champNouveau.value)
    const base = Number.isFinite(n) ? n : Number(curseur.value)
    const suivant = Math.min(PLAFOND_SAISIE, Math.max(CURSEUR.pas, arrondi2(base + x)))
    champNouveau.value = String(suivant)
    suivre(suivant)
    majEcart()
    planifier()
  }
  curseur.addEventListener('keydown', (ev) => {
    if (ev.key !== 'PageUp' && ev.key !== 'PageDown') return
    ev.preventDefault()
    decaler(ev.key === 'PageUp' ? SAUT : -SAUT)
  })
  cible.querySelectorAll<HTMLButtonElement>('button[data-pas]').forEach((b) => b.addEventListener('click', () => decaler(Number(b.dataset.pas))))
  /** Salaire net de départ d'une personne : celui de la saisie, ou celui que retrouve le calcul (traitement indiciaire saisi). */
  const departDe = async (role: Role): Promise<number> => {
    const q = etat.profil.personnes.find((x) => x.role === role)
    if (q?.salaire_net_avant_impot_mensuel) return arrondi2(q.salaire_net_avant_impot_mensuel)
    const r = await calculer(etat.profil, affectation)
    const p = r.statut === 'ok' ? r.entree.personnes.find((x) => x.role === role) : undefined
    return p ? arrondi2(p.salaire_net_avant_impot_annuel / 12) : NaN
  }
  const poserDepart = (net: number) => {
    if (!Number.isFinite(net)) return
    champDepart.value = String(net)
    champNouveau.value = String(salairePropose(net))
    suivre(salairePropose(net))
    majEcart()
  }
  cible.querySelectorAll<HTMLInputElement>('input[name="es-personne"]').forEach((r) =>
    r.addEventListener('change', () => {
      if (!r.checked) return
      etat.role = r.value as Role
      $('#es-profil').innerHTML = texteProfil(etat)
      const q = etat.profil.personnes.find((x) => x.role === etat.role)
      // Salaire saisi : repris tout de suite ; traitement indiciaire : retrouvé par le calcul.
      if (q?.salaire_net_avant_impot_mensuel) poserDepart(arrondi2(q.salaire_net_avant_impot_mensuel))
      void departDe(etat.role).then((net) => {
        poserDepart(net)
        return actualiser(true)
      })
    }),
  )
  $<HTMLFormElement>('#es-form').addEventListener('submit', (ev) => {
    ev.preventDefault()
    clearTimeout(minuterie)
    void actualiser(true)
  })
  majEcart()

  // Le moteur (environ 160 Ko compressés) se charge dans son Web Worker pendant que la page s'affiche.
  void import('../calcul/hors-fil').then((m) => m.prechauffer()).catch(() => {})
  const suite = (async () => {
    try {
      affectation = await chargerSiPresent<Affectation>('prelevements/affectation.json')
      // Destinataires propres à affectation.json : enregistrés ici aussi, le moteur tournant dans un worker.
      enregistrerDestinataires(affectation?.destinataires)
      // Fonctionnaire saisi par son traitement indiciaire : le salaire net de départ est celui du calcul.
      if (!Number.isFinite(depart0)) poserDepart(await departDe(etat.role))
    } catch (err) {
      console.error(err)
    }
    await actualiser(false)
  })()
  return { suite }
}

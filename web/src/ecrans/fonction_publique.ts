// La fonction publique (site/data/fonction_publique/ et site/data/effectifs/) : combien de personnes travaillent pour
// l'État, les collectivités locales et les hôpitaux publics (Insee), ce que l'État dépense pour ses agents (titre 2 du
// budget) sur 100 € de son budget, le coût complet moyen d'un emploi (calcul du site, approché), les évolutions publiées
// par l'Insee et les écarts entre sources, posés côte à côte sans arbitrage ni addition. Rien d'individuel : aucune
// rémunération d'une personne, aucun nom ; les cabinets ministériels ne sont repris que par totaux.
import { listeRecherche, segmente, valeurChoix } from '../composants/choix'
import { fragmentDepartement } from '../chemins'
import { billet, listeParts, type Part } from '../composants/billet'
import { partPersonnelle } from '../composants/hub'
import { TOUS_DEPARTEMENTS } from '../departements'
import { chargerSiPresent, type Noeud } from '../donnees'
import { lien } from '../routeur'
import { ROUTES } from '../routes'
import { absent, badgeStatut, entier, eur, eurLisible, h, md, pct, rendreDefilables, source, sur100, surligne, traitStatut, badgeCalcule, LEGENDE_CALCULE, memeAnnee } from '../util'
import { enCours } from './dette'

type Valeur = number | null

interface BudgetEtat {
  etpt: number
  millesime_etpt: string
  titre2_eur: number
  millesime_titre2: string
  nb_ministeres: number
  nb_programmes: number
}
interface Index {
  millesime: string
  source: string
  reperes: {
    budget_etat: BudgetEtat
    conseils?: { exercice: number; ae_eur: number; cp_eur: number; edition: string }
  }
  regles: string[]
  ecarts_entre_sources: { grandeur: string; valeurs: { source: string; valeur: number }[]; note: string }[]
  regle_personnes: string
  limites: string[]
}
interface Serie {
  cle: string
  annee: number
  revisee: boolean
}
interface LigneSerie {
  id: string
  libelle: string
  niveau: string
  parent: string | null
  valeurs: Record<string, Valeur[]>
}
interface Series {
  millesime: string
  source: string
  statuts: { id: string; libelle: string }[]
  series: Serie[]
  lignes: LigneSerie[]
  notes_source: string[]
}
interface LigneTableau {
  rubrique: string | null
  libelle: string
  valeurs: Valeur[]
  absences?: Record<string, string>
}
interface Tableau {
  titre: string
  unite?: string | null
  colonnes: string[]
  lignes: LigneTableau[]
  notes_source: string[]
}
interface Emploi {
  millesime: string
  source: string
  annee: number
  tableaux: Record<string, Tableau | undefined>
}
export interface Programme {
  programme: string
  libelle: string
  etpt: Valeur
  titre2_eur: Valeur
  fichier_effectifs?: string
}
interface Ministere {
  id: string
  ministere: string
  programmes: Programme[]
  etpt: number
  titre2_eur: number
}
interface Ministeres {
  millesime: string
  source: string
  limites: string[]
  totaux: { etpt: number; titre2_eur: number; nb_programmes: number; titre2_programmes_sans_ministere_eur: number }
  ministeres: Ministere[]
  programmes_sans_ministere: Programme[]
  groupes_insee: { groupe_insee: string; effectif_milliers: Record<string, number>; etpt_ministeres_budget: number; titre2_ministeres_budget_eur: number }[]
}
interface Zone {
  libelle: string
  valeurs: Valeur[]
}
export interface Territoires {
  millesime: string
  source: string
  annee: number
  colonnes: string[]
  champ: string
  departements: Record<string, Zone>
  regions: Record<string, Zone>
  ensembles: Record<string, Zone>
}
interface Situation {
  annee: number
  date_situation: string
  total: { effectif_total: number; membres_cabinet: number; fonctions_support: number; dotation_isp_eur: number }
  nb_cabinets: number
  edition: string
  source: string
}
interface Cabinets {
  source: string
  definitions?: Record<string, string>
  limites: string[]
  situations: Situation[]
}
interface EffectifsProgramme {
  millesime: string
  source: string
}

const nf1 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
/** Milliers de personnes (unité de l'Insee) en personnes : 2 589,0 devient « 2 589 000 ». */
export const personnes = (milliers: number) => entier(Math.round(milliers * 1000))
/** Évolution signée, sans couleur : « +0,8 % », « −0,1 % ». */
export const evolution = (x: number) => `${x > 0 ? '+' : x < 0 ? '−' : ''}${pct(Math.abs(x))}`
/** Année lue dans un millésime (« Exécution 2024 » donne « 2024 ») : aucune année n'est écrite en dur. */
const anneeDe = (m: string | undefined) => /\b(?:19|20)\d\d\b/.exec(m ?? '')?.[0] ?? ''
/** Titre d'une source, sans son adresse. */
const titreSource = (s: string) => s.split(/ : https?:\/\//)[0]
const minuscule = (s: string) => s.charAt(0).toLowerCase() + s.slice(1)
const majuscule = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
/**
 * Texte rédigé par le pipeline, rendu lisible : sans renvoi à un champ technique ni chemin de fichier,
 * sans sigle seul (« LFI 2023 » devient « loi de finances initiale pour 2023 », « ETPT » est expliqué).
 */
export const lisible = (t: string) =>
  t
    .replace(/\s*\(voir `[^`]*`\)/g, '')
    .replace(/\s*\(site\/data\/[^)]*\)/g, '')
    .replace(/site\/data\/([\w-]+)/g, 'les données « $1 » du site')
    .replace(/\bLFI (\d{4})\b/g, 'loi de finances initiale pour $1')
    .replace(/\bETPT\b/g, 'emplois votés (ETPT)')
/** Note de bas de figure sans son numéro d'appel (« 1. Une catégorie... » devient « Une catégorie... »). */
const sansAppel = (n: string) => n.replace(/^\d+\.\s*/, '')
const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
const dateLongue = (iso: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m) return iso
  const j = Number(m[3])
  return `${j === 1 ? '1er' : j} ${MOIS[Number(m[2]) - 1]} ${m[1]}`
}
/** Valeur d'un tableau de l'Insee ; une absence est dite en mots (« /// » : sans objet, sinon non disponible), jamais 0. */
function cellule(v: Valeur | undefined, absence: string | undefined, f: (x: number) => string): string {
  if (typeof v === 'number') return h(f(v))
  return absence === '///' ? 'sans objet' : 'non disponible'
}
/** En-tête de colonne : aligné à droite et sans retour à la ligne s'il est court, libre de passer à la ligne sinon. */
const colonne = (texte: string) => `<th scope="col"${texte.length <= 14 ? ' class="nombre"' : ''}>${h(texte)}</th>`

interface Versant {
  famille: 'etat' | 'collectivites' | 'secu'
  court: string
  pour: string
}
/** Les trois versants, reconnus à leur libellé (« Fonction publique de l'État (FPE) »...). */
function versant(libelle: string): Versant | null {
  if (/l[’']État/i.test(libelle)) return { famille: 'etat', court: 'État', pour: 'pour l’État (fonction publique de l’État)' }
  if (/territoriale/i.test(libelle)) return { famille: 'collectivites', court: 'Territoriale', pour: 'pour les collectivités locales (fonction publique territoriale)' }
  if (/hospitali/i.test(libelle)) return { famille: 'secu', court: 'Hospitalière', pour: 'pour les hôpitaux publics (fonction publique hospitalière)' }
  return null
}
const court = (libelle: string) => versant(libelle)?.court ?? (/^Ensemble/i.test(libelle) ? 'Ensemble' : libelle)
/** Nom court dans une phrase : « État » garde sa majuscule, « territoriale » non. */
const dansPhrase = (c: string) => (c === 'État' ? c : minuscule(c))

/**
 * Coût complet moyen par emploi : dépenses de personnel divisées par les emplois votés, sur les seuls programmes
 * qui publient les deux (les autres sont rendus dans « exclus »). Calcul du site, statut « approché ».
 */
export function coutMoyen(programmes: Programme[]): { titre2: number; etpt: number; moyen: number | null; exclus: Programme[] } {
  const ok = programmes.filter((p) => (p.etpt ?? 0) > 0 && (p.titre2_eur ?? 0) > 0)
  const titre2 = ok.reduce((s, p) => s + (p.titre2_eur ?? 0), 0)
  const etpt = ok.reduce((s, p) => s + (p.etpt ?? 0), 0)
  return { titre2, etpt, moyen: etpt > 0 ? titre2 / etpt : null, exclus: programmes.filter((p) => !ok.includes(p)) }
}

export const REGLE_MINISTERES = 'Ordre : dépenses de personnel décroissantes.'

function blocPersonnes(ser: Series, idx: Index): string {
  const i = ser.series.length - 1
  const s = ser.series[i]
  const val = (l: LigneSerie | undefined): Valeur => (l ? l.valeurs.ensemble?.[i] ?? null : null)
  const ens = val(ser.lignes.find((l) => l.niveau === 'ensemble'))
  const versants = ser.lignes
    .filter((l) => l.niveau === 'versant')
    .map((l) => ({ l, v: versant(l.libelle), n: val(l) }))
    .filter((x): x is { l: LigneSerie; v: Versant; n: number } => !!x.v && typeof x.n === 'number')
  if (!s || typeof ens !== 'number' || ens <= 0 || !versants.length) return absent('Effectifs par versant non disponibles.')
  const dont = (id: string) =>
    ser.lignes
      .filter((l) => l.parent === id && l.niveau === 'type_employeur')
      .map((l) => ({ nom: l.libelle, n: val(l) }))
      .filter((x): x is { nom: string; n: number } => typeof x.n === 'number')
  const champ = ser.notes_source.find((n) => n.startsWith('Champ'))
  const statuts = ser.statuts.filter((x) => x.id !== 'ensemble').map((x) => minuscule(x.libelle))
  const ecart = idx.ecarts_entre_sources.find((e) => e.valeurs.some((x) => Math.abs(x.valeur - ens) < 0.05))
  const ailleurs = ecart ? ecart.valeurs.filter((x) => Math.abs(x.valeur - ens) >= 0.05) : []
  return `<p>Fin ${s.annee}, <strong>${h(personnes(ens))} personnes</strong> travaillent dans la fonction publique. ${badgeStatut('trace')}</p>
<div class="empile" aria-hidden="true">${versants.map((x) => `<span class="fond-${x.v.famille}" data-l="${((x.n / ens) * 100).toFixed(2)}"></span>`).join('')}</div>
<ul class="cles" aria-label="Personnes employées par versant de la fonction publique, fin ${s.annee}">${versants
    .map((x) => {
      const d = dont(x.l.id)
      return `<li><strong>${h(personnes(x.n))}</strong><span><span class="pastille fond-${x.v.famille}" aria-hidden="true"></span>personnes ${h(x.v.pour)}, soit ${h(nf1.format((x.n / ens) * 100))} sur 100 agents publics.${
        d.length ? ` Dont ${d.map((y) => `${h(minuscule(y.nom))} : ${h(personnes(y.n))}`).join(' ; ')}.` : ''
      }</span>${badgeStatut('trace')}</li>`
    })
    .join('')}</ul>
<p class="aide">${champ ? `${h(champ)} ` : ''}Tous statuts compris : ${h(statuts.join(', '))}.</p>
${
  ailleurs.length
    ? `<p class="aide">Pour la même date, ${ailleurs.map((x) => `${h(titreSource(x.source))} donne ${h(personnes(x.valeur))}`).join(' ; ')} : les valeurs sont posées côte à côte plus bas, dans « Écarts entre sources ».</p>`
    : ''
}
${source(ser.source, ser.millesime)}`
}

function blocMasse(idx: Index, min: Ministeres | null, racine: Noeud | null, eff: EffectifsProgramme | null): string {
  const b = idx.reperes.budget_etat
  const an = anneeDe(b.millesime_titre2)
  // Le total du budget de l'État n'est un dénominateur que s'il porte sur la même année que les dépenses de personnel.
  const total = racine && racine.millesime === b.millesime_titre2 && racine.md > 0 ? racine.md * 1e9 : null
  const s100 = total ? (b.titre2_eur / total) * 100 : null
  let figure = ''
  if (min && total && s100 !== null) {
    const tri = [...min.ministeres].sort((a, c) => c.titre2_eur - a.titre2_eur)
    const tete = tri.slice(0, 3)
    const reste = tri.slice(3)
    const sommeReste = reste.reduce((s, m) => s + m.titre2_eur, 0)
    // Valeurs « sur 100 € » : le billet découpe en proportion, la liste trace ses barres sur 100.
    const part = (nom: string, eurMontant: number): Part => ({
      nom,
      valeur: (eurMontant / total) * 100,
      texte: sur100((eurMontant / total) * 100),
      famille: 'etat',
      detail: `personnel, ${eurLisible(eurMontant)}`,
    })
    const parts: Part[] = [
      ...tete.map((m) => part(m.ministere, m.titre2_eur)),
      ...(reste.length ? [part(`${reste.length} autres ministères`, sommeReste)] : []),
      { nom: 'Le reste du budget de l’État', valeur: 100 - s100, texte: sur100(100 - s100), famille: 'papier', detail: 'hors dépenses de personnel des ministères' },
    ]
    const etiquette = `Sur 100 € dépensés par l’État en ${an} : dépenses de personnel par ministère, puis le reste du budget`
    figure = `${billet(parts, { etiquette: `Billet de 100 € dépensés par l’État en ${an}, découpé : dépenses de personnel par ministère, puis le reste du budget` })}
${listeParts(parts, etiquette)}`
  }
  const hopitaux = ROUTES.find((r) => /hopit/i.test(r.chemin))
  const lignePart =
    s100 !== null && racine
      ? `soit ${h(sur100(s100))} sur 100 € dépensés par l’État cette année-là (${h(md(racine.md))} au total).`
      : 'Total du budget de l’État non disponible pour la même année : pas de part sur 100 €.'
  return `<div class="carte"${s100 !== null ? ' data-cle' : ''}>
  <p>Ce que l’État a dépensé pour ses agents en ${h(an)} :</p>
  <p class="grand-chiffre">${s100 !== null ? surligne(md(b.titre2_eur / 1e9)) : h(md(b.titre2_eur / 1e9))}</p>
  <p class="sous-chiffre">${lignePart} ${badgeStatut('trace')}</p>
  <p>C’est le « titre 2 » du budget, celui des dépenses de personnel : les rémunérations, les cotisations sociales payées par l’employeur et la contribution de l’État employeur au financement des pensions de ses agents. Il réunit ${h(String(b.nb_programmes))} programmes du budget, rattachés à ${h(String(b.nb_ministeres))} ministères.</p>
  ${source(`dépenses de personnel : ${eff?.source ?? min?.source ?? idx.source}`, b.millesime_titre2)}
  ${total && racine ? source(`total du budget de l’État : ${racine.source ?? ''}`, racine.millesime) : ''}
</div>
${figure}
<h3>Et les collectivités, les hôpitaux ?</h3>
<p>Les collectivités locales et les hôpitaux publics paient leurs agents sur leurs propres budgets, pas sur celui de l’État. La part du personnel dans les dépenses de ta commune, de ton intercommunalité, de ton département et de ta région est dans <a href="${lien('/local')}">Budget de ma commune</a>.${
    hopitaux ? ` Pour les hôpitaux : <a href="${lien(hopitaux.chemin)}">${h(hopitaux.titre)}</a>.` : ''
  }</p>
${absent('Total des rémunérations de toutes les administrations publiques (État, collectivités, hôpitaux, Sécurité sociale) : pas encore repris dans les données du site. La page ne donne donc pas de part « sur 100 € de toute la dépense publique » : la part donnée plus haut porte sur le budget de l’État.')}`
}

function blocMinisteres(min: Ministeres, total: number | null, b: BudgetEtat): string {
  const anE = anneeDe(b.millesime_etpt)
  const anT = anneeDe(b.millesime_titre2)
  const tri = [...min.ministeres].sort((a, c) => c.titre2_eur - a.titre2_eur || a.ministere.localeCompare(c.ministere, 'fr'))
  const s100 = (x: number) => (total ? sur100((x / total) * 100) : 'non disponible')
  const moyen = (x: number | null) => (x === null ? 'non disponible' : eur(x))
  const tous = coutMoyen(min.ministeres.flatMap((m) => m.programmes))
  // Règle « chiffre calculé par le site » : coût moyen seulement si emplois et dépenses portent sur la même année.
  const avecMoyen = memeAnnee(anE, anT)
  const colMoyen = (x: string) => (avecMoyen ? x : '')
  const sans = min.programmes_sans_ministere
  const exclus = tous.exclus.map((p) => `${h(p.programme)} (${h(p.libelle)})`)
  const exclusBruts = tous.exclus.map((p) => `${p.programme} (${p.libelle})`)
  return `<div class="tableau-defile"><table><caption>Emplois votés pour ${h(anE)} et dépenses de personnel ${h(anT)}, par ministère</caption>
<thead><tr><th scope="col">Ministère</th>${colonne(`Emplois votés ${anE}`)}${colonne(`Dépenses de personnel ${anT}`)}${colonne('Sur 100 € du budget de l’État')}${colMoyen(colonne('Coût complet moyen par emploi'))}</tr></thead>
<tbody>${tri
    .map(
      (m) =>
        `<tr><th scope="row">${h(m.ministere)}</th><td class="nombre">${h(entier(Math.round(m.etpt)))}</td><td class="nombre">${h(eurLisible(m.titre2_eur))}</td><td class="nombre">${h(s100(m.titre2_eur))}</td>${colMoyen(`<td class="nombre">${h(moyen(coutMoyen(m.programmes).moyen))}</td>`)}</tr>`,
    )
    .join('')}</tbody>
<tfoot><tr><th scope="row">Ensemble (${tri.length} ministères)</th><td class="nombre">${h(entier(Math.round(min.totaux.etpt)))}</td><td class="nombre">${h(eurLisible(min.totaux.titre2_eur))}</td><td class="nombre">${h(s100(min.totaux.titre2_eur))}</td>${colMoyen(`<td class="nombre">${h(moyen(tous.moyen))}</td>`)}</tr></tfoot>
</table></div>
<p class="aide" data-regle-ordre>${REGLE_MINISTERES}</p>
<p class="aide">Emplois votés : plafond d’emplois voté pour ${h(anE)} par le Parlement (loi de finances initiale), en équivalent temps plein travaillé : une personne à temps partiel ou présente une partie de l’année compte pour moins de 1. Ce n’est pas le nombre de personnes en poste. Emplois et dépenses de personnel : ${badgeStatut('trace')}</p>
${
  avecMoyen
    ? `<p class="aide">Coût complet moyen par emploi ${badgeCalcule(`dépenses de personnel ${anT} divisées par les emplois votés pour la même année, sur les programmes qui publient les deux${
        exclusBruts.length ? ` (sans ${exclusBruts.length > 1 ? `les programmes ${exclusBruts.slice(0, -1).join(', ')} et ${exclus[exclusBruts.length - 1]}` : `le programme ${exclusBruts[0]}`}, qui ne publient pas l’un des deux)` : ''
      } ; rémunération brute, cotisations de l’employeur et contribution aux pensions comprises, ce n’est pas un salaire`)}</p>`
    : `<p class="aide">Pas de coût moyen par emploi : les emplois votés (${h(anE)}) et les dépenses de personnel (${h(anT)}) ne portent pas sur la même année, et le site ne divise pas deux montants de deux années différentes.</p>`
}
${
  sans.length
    ? `<p class="aide">Hors tableau : ${sans.length} programmes sans emplois votés publiés par programme (${h(eurLisible(min.totaux.titre2_programmes_sans_ministere_eur))} de dépenses de personnel en ${h(anT)}), rattachés à aucun ministère.</p>`
    : ''
}
<p class="aide">Le détail d’un programme (emplois par catégorie, nature de la dépense) est dans <a href="${lien('/beneficiaires/programme')}">Un programme en détail</a>.</p>
${source(lisible(min.source), lisible(min.millesime))}`
}

function blocRemunerations(min: Ministeres | null, b: BudgetEtat): string {
  const tous = min && memeAnnee(b.millesime_titre2, b.millesime_etpt) ? coutMoyen(min.ministeres.flatMap((m) => m.programmes)) : null
  return `${
    tous?.moyen
      ? `<p>Coût complet moyen d’un emploi de l’État : <strong>${h(eur(tous.moyen))} par an</strong> ${badgeCalcule(`dépenses de personnel ${anneeDe(b.millesime_titre2)} divisées par les emplois votés de la même année, tous ministères ; ce n’est pas un salaire : la rémunération brute, les cotisations de l’employeur et sa contribution aux pensions y sont comprises`)}</p>`
      : '<p class="aide">Pas de coût complet moyen d’un emploi de l’État : les emplois votés et les dépenses de personnel publiés ne portent pas sur la même année.</p>'
  }
${absent('Salaire moyen par catégorie (A, B, C) ou par versant : pas encore repris dans les données du site. La page donne la part des agents de chaque catégorie, pas leur salaire.')}
<p>Aucune rémunération individuelle n’est publiée ici. Les indemnités des cabinets ministériels sont données plus bas en enveloppe globale, jamais par personne.</p>`
}

interface OptionsTableau {
  legende: string
  /** en-tête de la première colonne (ce que nomme chaque ligne) */
  premiere: string
  formats: ((x: number) => string)[]
  /** une ligne d'en-tête par rubrique */
  groupe?: boolean
  entetes?: string[]
}
/** Tableau d'une figure de l'Insee : lignes choisies, une colonne par valeur, un format par colonne. */
function tableauInsee(t: Tableau, lignes: LigneTableau[], o: OptionsTableau): string {
  const entetes = o.entetes ?? t.colonnes
  const tr = (l: LigneTableau) =>
    `<tr><th scope="row">${h(l.libelle)}</th>${l.valeurs.map((v, i) => `<td class="nombre">${cellule(v, l.absences?.[String(i)], o.formats[i] ?? ((x) => nf1.format(x)))}</td>`).join('')}</tr>`
  const corps = o.groupe
    ? [...new Set(lignes.map((l) => l.rubrique ?? ''))]
        .map((r) => `<tbody><tr><th scope="rowgroup" colspan="${entetes.length + 1}">${h(r)}</th></tr>${lignes.filter((l) => (l.rubrique ?? '') === r).map(tr).join('')}</tbody>`)
        .join('')
    : `<tbody>${lignes.map(tr).join('')}</tbody>`
  return `<div class="tableau-defile"><table><caption>${h(o.legende)}</caption><thead><tr><th scope="col">${h(o.premiere)}</th>${entetes.map(colonne).join('')}</tr></thead>${corps}</table></div>`
}

function blocQui(emp: Emploi): string {
  const t = emp.tableaux.figure_3
  if (!t) return absent('Caractéristiques des agents non disponibles.')
  const femmes = emp.tableaux.figure_4?.lignes.find((l) => l.libelle === 'Ensemble')
  const lignes = [...t.lignes, ...(femmes ? [{ ...femmes, rubrique: 'Femmes', libelle: 'Part de femmes' }] : [])]
  const notes = t.notes_source.filter((n) => /^\d\.|^Champ/.test(n)).map(sansAppel)
  return `${tableauInsee(t, lignes, { legende: `${t.titre}, sur 100 agents de chaque versant`, premiere: 'Sur 100 agents', formats: t.colonnes.map(() => (x: number) => pct(x)), groupe: true, entetes: t.colonnes.map(court) })}
<p class="aide">La catégorie A regroupe les emplois de conception et d’encadrement, la catégorie B les emplois d’application, la catégorie C les emplois d’exécution. ${notes.map(h).join(' ')} ${badgeStatut('trace')}</p>
${source(emp.source, emp.millesime)}`
}

function blocEvolutions(emp: Emploi | null, ser: Series): string {
  const out: string[] = []
  const f1 = emp?.tableaux.figure_1
  if (emp && f1) {
    const iEvol = f1.colonnes.findIndex((c) => /Évolution/.test(c) && /Y compris/.test(c))
    const lignes = f1.lignes.filter((l) => /^Effectifs/.test(l.rubrique ?? ''))
    const ens = lignes.find((l) => /^Ensemble/.test(l.libelle))?.valeurs[iEvol]
    const verbe = (x: number) => (x > 0 ? `augmente de ${pct(x)}` : x < 0 ? `diminue de ${pct(-x)}` : 'ne change pas')
    if (iEvol >= 0 && typeof ens === 'number')
      out.push(
        `<p>Entre fin ${emp.annee - 1} et fin ${emp.annee}, le nombre de personnes employées dans la fonction publique ${h(verbe(ens))} : ${lignes
          .filter((l) => versant(l.libelle) && typeof l.valeurs[iEvol] === 'number')
          .map((l) => `${h(dansPhrase(court(l.libelle)))} ${h(evolution(l.valeurs[iEvol] as number))}`)
          .join(', ')}. ${badgeStatut('trace')}</p>`,
      )
  }
  const tc1 = emp?.tableaux.tableau_complementaire_1
  if (emp && tc1) {
    const formats = tc1.colonnes.map((c) => (/Évolution/.test(c) ? evolution : personnes))
    const ensemble = tc1.lignes.filter((l) => /^Ensemble/.test(l.rubrique ?? ''))
    out.push(`<h3>Par statut</h3>
${tableauInsee(tc1, ensemble, { legende: `Personnes employées au 31 décembre par statut, ensemble de la fonction publique, fin ${emp.annee - 1} et fin ${emp.annee}`, premiere: 'Statut', formats })}
<details><summary>Par statut dans chaque versant</summary>${tableauInsee(
      tc1,
      tc1.lignes.filter((l) => !/^Ensemble/.test(l.rubrique ?? '')),
      { legende: `Personnes employées au 31 décembre, par versant et par statut, fin ${emp.annee - 1} et fin ${emp.annee}`, premiere: 'Statut', formats, groupe: true },
    )}</details>
<p class="aide">Les fonctionnaires sont des agents titulaires ; les contractuels sont recrutés par contrat. ${badgeStatut('trace')}</p>
${source(emp.source, emp.millesime)}`)
  }
  const f5 = emp?.tableaux.figure_5
  if (emp && f5) {
    const der = String(Math.max(...f5.lignes.map((l) => Number(l.libelle)).filter((x) => Number.isFinite(x))))
    const formats = f5.colonnes.map(() => personnes)
    out.push(`<h3>Entrées et sorties</h3>
${tableauInsee(
  f5,
  f5.lignes.filter((l) => l.libelle === der).map((l) => ({ ...l, libelle: l.rubrique ?? l.libelle })),
  { legende: `Personnels civils entrés dans la fonction publique et sortis en ${der}, par versant puis par statut`, premiere: 'Versant ou statut', formats },
)}
<details><summary>Entrées et sorties, toutes les années publiées</summary>${tableauInsee(f5, f5.lignes, { legende: f5.titre, premiere: 'Année', formats, groupe: true })}</details>
<p class="aide">${f5.notes_source.filter((n) => /^Champ/.test(n)).map(h).join(' ')} ${badgeStatut('trace')}</p>
${source(emp.source, emp.millesime)}`)
  }
  // Série longue : les années recalculées par l'Insee sont posées à côté de celles publiées à l'époque, jamais fondues.
  const lignes = [...ser.lignes.filter((l) => l.niveau === 'versant'), ...ser.lignes.filter((l) => l.niveau === 'ensemble')]
  const revisees = [...new Set(ser.series.filter((s) => s.revisee).map((s) => s.annee))].sort()
  const etiquette = (s: Serie) => (s.revisee ? `${s.annee} (recalculée)` : revisees.includes(s.annee) ? `${s.annee} (publiée à l’époque)` : String(s.annee))
  const rangs = ser.series.map((s, i) => ({ s, i })).reverse()
  const comparabilite = ser.notes_source.find((n) => /comparables/.test(n))
  const f2 = emp?.tableaux.figure_2
  out.push(`<details><summary>Série longue depuis ${h(String(ser.series[0]?.annee ?? ''))} : personnes employées et évolution d’une année sur l’autre</summary>
<div class="tableau-defile"><table><caption>Personnes employées au 31 décembre, par versant, ${h(ser.millesime)}</caption>
<thead><tr><th scope="col">Année</th>${lignes.map((l) => colonne(court(l.libelle))).join('')}</tr></thead>
<tbody>${rangs.map(({ s, i }) => `<tr><th scope="row">${h(etiquette(s))}</th>${lignes.map((l) => `<td class="nombre">${cellule(l.valeurs.ensemble?.[i], undefined, personnes)}</td>`).join('')}</tr>`).join('')}</tbody>
</table></div>
<p class="aide">${revisees.length ? `Les années ${h(revisees.join(', '))} existent en deux versions : celle publiée à l’époque et celle recalculée par l’Insee, comparable à l’année suivante. Les deux sont données, sans choisir. ` : ''}${comparabilite ? h(sansAppel(comparabilite)) : ''} ${badgeStatut('trace')}</p>
${source(ser.source, ser.millesime)}
${
  f2 && emp
    ? `${tableauInsee(f2, [...f2.lignes].reverse(), { legende: `${f2.titre}, d’une année sur l’autre`, premiere: 'Année', formats: f2.colonnes.map(() => evolution), entetes: f2.colonnes.map(court) })}
<p class="aide">${f2.notes_source.filter((n) => /^Champ/.test(n)).map(h).join(' ')} ${badgeStatut('trace')}</p>
${source(emp.source, emp.millesime)}`
    : ''
}
</details>`)
  return out.join('\n')
}

function blocDeuxComptes(min: Ministeres | null, ser: Series, emp: Emploi | null, b: BudgetEtat): string {
  const anE = anneeDe(b.millesime_etpt)
  const anT = anneeDe(b.millesime_titre2)
  const i = ser.series.length - 1
  const fpe = ser.lignes.find((l) => l.niveau === 'versant' && versant(l.libelle)?.famille === 'etat')
  const epa = fpe ? ser.lignes.find((l) => l.parent === fpe.id && /administratif/i.test(l.libelle)) : undefined
  const nEpa = epa?.valeurs.ensemble?.[i]
  const f1 = emp?.tableaux.figure_1
  const iEtp = f1 && emp ? f1.colonnes.findIndex((c) => c.startsWith(String(emp.annee)) && /Y compris/.test(c)) : -1
  const etp = f1 && iEtp >= 0 ? f1.lignes.find((l) => /équivalent temps plein/.test(l.rubrique ?? '') && /^Ensemble/.test(l.libelle))?.valeurs[iEtp] : null
  let tableau = ''
  if (min?.groupes_insee.length) {
    const groupes = min.groupes_insee
    const anG = String(Math.max(...groupes.flatMap((g) => Object.keys(g.effectif_milliers).map(Number))))
    const contour = min.limites.find((l) => /ordre de grandeur/.test(l))
    tableau = `<div class="tableau-defile"><table><caption>Agents de l’État : personnes comptées par l’Insee fin ${h(anG)} et emplois votés pour ${h(anE)}, par groupe de ministères</caption>
<thead><tr><th scope="col">Groupe de ministères (Insee)</th>${colonne(`Personnes fin ${anG} (Insee)`)}${colonne(`Emplois votés ${anE} (budget)`)}${colonne(`Dépenses de personnel ${anT}`)}</tr></thead>
<tbody>${groupes
      .map(
        (g) =>
          `<tr><th scope="row">${h(g.groupe_insee)}</th><td class="nombre">${cellule(g.effectif_milliers[anG], undefined, personnes)}</td><td class="nombre">${h(entier(Math.round(g.etpt_ministeres_budget)))}</td><td class="nombre">${h(eurLisible(g.titre2_ministeres_budget_eur))}</td></tr>`,
      )
      .join('')}</tbody></table></div>
<p class="aide">${contour ? `${h(lisible(contour))} ` : ''}Rapprochement des groupes de l’Insee et des ministères du budget fait par le site, d’après les intitulés. ${badgeStatut('approche')}</p>
${source(lisible(min.source), lisible(min.millesime))}`
  }
  return `<p>L’Insee compte des personnes en poste au 31 décembre. Le budget de l’État compte des emplois votés, en équivalent temps plein. Les deux mesurent la même population de deux façons : ils sont posés côte à côte, jamais additionnés.</p>
${tableau}
${
  typeof nEpa === 'number' && epa
    ? `<p>L’Insee compte aussi ${h(personnes(nEpa))} personnes dans les ${h(minuscule(epa.libelle))} (fin ${h(String(ser.series[i].annee))}), hors ministères : leurs emplois relèvent des plafonds des <a href="${lien('/explorer/operateurs')}">opérateurs de l’État</a>, pas des emplois votés des ministères. ${badgeStatut('trace')}</p>`
    : ''
}
${
  typeof etp === 'number' && emp
    ? `<p>Autre mesure de l’Insee : le volume de travail en équivalent temps plein, tout poste actif dans l’année compris, est de ${h(personnes(etp))} pour l’ensemble de la fonction publique en ${emp.annee}. ${badgeStatut('trace')}</p>`
    : ''
}`
}

function blocEcarts(idx: Index, ser: Series, emp: Emploi | null): string {
  const liste = idx.ecarts_entre_sources
    .map(
      (e) =>
        `<li><strong>${h(majuscule(e.grandeur))}</strong><ul>${e.valeurs.map((v) => `<li>${h(v.source)} : <strong>${h(nf1.format(v.valeur))}</strong></li>`).join('')}</ul><p class="aide">${h(e.note)}</p></li>`,
    )
    .join('')
  // Même date, même champ, deux publications de l'Insee : chaque versant, valeur par valeur.
  const f1 = emp?.tableaux.figure_1
  const i = ser.series.length - 1
  const an = ser.series[i]?.annee
  const iCol = f1 ? f1.colonnes.findIndex((c) => c.startsWith(String(an)) && /Y compris/.test(c)) : -1
  const lignes = [...ser.lignes.filter((l) => l.niveau === 'versant'), ...ser.lignes.filter((l) => l.niveau === 'ensemble')]
  const ip = (nom: string) => f1?.lignes.find((l) => /^Effectifs/.test(l.rubrique ?? '') && court(l.libelle) === nom)?.valeurs[iCol]
  const tableau =
    f1 && emp && iCol >= 0
      ? `<div class="tableau-defile"><table><caption>Personnes employées fin ${h(String(an))}, par versant, selon deux publications de l’Insee</caption>
<thead><tr><th scope="col">Versant</th>${colonne(titreSource(ser.source))}${colonne(titreSource(emp.source))}</tr></thead>
<tbody>${lignes
          .map((l) => `<tr><th scope="row">${h(court(l.libelle))}</th><td class="nombre">${cellule(l.valeurs.ensemble?.[i], undefined, personnes)}</td><td class="nombre">${cellule(ip(court(l.libelle)), undefined, personnes)}</td></tr>`)
          .join('')}</tbody></table></div>`
      : ''
  return `<p>Quand deux publications donnent des valeurs différentes pour la même grandeur, le site les montre l’une à côté de l’autre, sans choisir ni additionner.</p>
<ul>${liste}</ul>
${tableau}
<p class="aide">Valeurs publiées telles quelles. ${badgeStatut('trace')}</p>`
}

const TERRITOIRE: Record<string, { nom: string; f: (x: number) => string }> = {
  ensemble_hors_militaires_milliers: { nom: 'Personnes employées (hors militaires)', f: personnes },
  fpe_hors_militaires_milliers: { nom: 'dont État (hors militaires)', f: personnes },
  fpt_milliers: { nom: 'dont collectivités locales (territoriale)', f: personnes },
  fph_milliers: { nom: 'dont hôpitaux publics (hospitalière)', f: personnes },
  pour_100_habitants: { nom: 'Pour 100 habitants', f: (x) => nf1.format(x) },
  pour_100_emplois_salaries: { nom: 'Pour 100 emplois salariés', f: (x) => nf1.format(x) },
  part_femmes_pct: { nom: 'Part de femmes', f: (x) => pct(x) },
}

/** Valeur du choix « Département ou région » : « d-44 », « r-52 », ou vide pour les repères nationaux. */
export function zoneTerritoire(ter: Territoires, choix: string): string {
  const [type, code] = choix.split('-')
  const zone = type === 'd' ? ter.departements[code] : type === 'r' ? ter.regions[code] : undefined
  const reperes = Object.values(ter.ensembles)
  const colonnes = zone ? [zone, ...reperes.slice(0, 1)] : reperes
  const ordre = [...Object.keys(TERRITOIRE).filter((k) => ter.colonnes.includes(k)), ...ter.colonnes.filter((k) => !TERRITOIRE[k])]
  const lienDep = zone && type === 'd' ? `<p><a href="${fragmentDepartement(code, zone.libelle)}">Le budget des communes et du département : ${h(zone.libelle)}</a></p>` : ''
  return `<div class="tableau-defile"><table><caption>Fonction publique fin ${h(String(ter.annee))}, hors militaires : ${h(colonnes.map((c) => c.libelle).join(', '))}</caption>
<thead><tr><th scope="col">Indicateur</th>${colonnes.map((c) => colonne(c.libelle)).join('')}</tr></thead>
<tbody>${ordre
    .map((k) => {
      const j = ter.colonnes.indexOf(k)
      const d = TERRITOIRE[k] ?? { nom: k, f: (x: number) => nf1.format(x) }
      return `<tr><th scope="row">${h(d.nom)}</th>${colonnes.map((c) => `<td class="nombre">${cellule(c.valeurs[j], undefined, d.f)}</td>`).join('')}</tr>`
    })
    .join('')}</tbody></table></div>${lienDep}`
}

function blocTerritoires(ter: Territoires, dep: string | null): string {
  const presents = new Set(Object.keys(ter.departements))
  const deps: [string, string][] = [
    ...TOUS_DEPARTEMENTS.filter(([c]) => presents.has(c)).map(([c]): [string, string] => [c, ter.departements[c].libelle]),
    ...Object.keys(ter.departements)
      .filter((c) => !TOUS_DEPARTEMENTS.some(([x]) => x === c))
      .map((c): [string, string] => [c, ter.departements[c].libelle]),
  ]
  const regions = Object.entries(ter.regions).sort((a, c) => a[1].libelle.localeCompare(c[1].libelle, 'fr'))
  const initial = dep && presents.has(dep) ? `d-${dep}` : ''
  return `<form id="fp-territoire-form">${listeRecherche({ id: 'fp-territoire', etiquette: 'Département ou région', options: [], optionsHtml: `<option value="">France (repères nationaux)</option><optgroup label="Départements">${deps
    .map(([c, n]) => `<option value="d-${h(c)}"${`d-${c}` === initial ? ' selected' : ''}>${h(c)} ${h(n)}</option>`)
    .join('')}</optgroup><optgroup label="Régions">${regions.map(([c, z]) => `<option value="r-${h(c)}">${h(z.libelle)}</option>`).join('')}</optgroup>` })}</form>
<div id="fp-zone-territoire" aria-live="polite">${zoneTerritoire(ter, initial)}</div>
<p class="aide">${h(ter.champ)} ${badgeStatut('trace')}</p>
${source(ter.source, ter.millesime)}`
}

function blocCabinetsConseils(idx: Index, cab: Cabinets | null): string {
  const sits = cab ? [...cab.situations].sort((a, c) => a.annee - c.annee) : []
  const der = sits[sits.length - 1]
  const avant = sits.length > 1 ? sits[sits.length - 2] : null
  const co = idx.reperes.conseils
  const srcConseils = co ? idx.source.split(' ; ').filter((s) => /conseils/i.test(s) && s.includes(`pour ${anneeDe(co.edition)}`)) : []
  const comparables = cab?.limites.find((l) => /comparables/.test(l))
  const items: string[] = []
  if (der)
    items.push(
      `<li><span class="p-nom">Personnes affectées dans les cabinets ministériels<small>au ${h(dateLongue(der.date_situation))}, dans ${h(String(der.nb_cabinets))} cabinets : ${h(entier(der.total.membres_cabinet))} membres de cabinet et ${h(entier(der.total.fonctions_support))} personnes chargées des fonctions support</small></span><span class="p-montant">${h(entier(der.total.effectif_total))}</span>${badgeStatut('trace')}</li>`,
      `<li><span class="p-nom">Enveloppe annuelle d’indemnités pour sujétions particulières des cabinets<small>${h(String(der.annee))}, par pôle ministériel, jamais par personne</small></span><span class="p-montant">${h(eurLisible(der.total.dotation_isp_eur))}</span>${badgeStatut('trace')}</li>`,
    )
  if (co)
    items.push(
      `<li><span class="p-nom">Dépenses de conseil extérieur de l’État<small>${h(String(co.exercice))}, montants engagés (autorisations d’engagement consommées) ; montants payés la même année : ${h(eurLisible(co.cp_eur))}</small></span><span class="p-montant">${h(eurLisible(co.ae_eur))}</span>${badgeStatut('trace')}</li>`,
    )
  if (!items.length) return absent('Cabinets ministériels et conseils extérieurs : données non disponibles.')
  return `<ul class="postes">${items.join('')}</ul>
<p>Les personnels des cabinets sont déjà compris dans les effectifs des ministères. Les dépenses de conseil sont des dépenses de fonctionnement, distinctes des dépenses de personnel. Aucun de ces montants ne s’ajoute aux chiffres plus haut.</p>
${avant ? `<p class="aide">Au ${h(dateLongue(avant.date_situation))}, les cabinets comptaient ${h(entier(avant.total.effectif_total))} personnes.${comparables ? ` ${h(comparables)}` : ''}</p>` : ''}
${cab?.definitions?.dotation_isp_eur ? `<p class="aide">Indemnités pour sujétions particulières : ${h(cab.definitions.dotation_isp_eur)}.</p>` : ''}
${der ? source(der.source, `situation au ${dateLongue(der.date_situation)}`) : ''}
${avant ? source(avant.source, `situation au ${dateLongue(avant.date_situation)}`) : ''}
${co ? source(srcConseils.length ? srcConseils.join(' ; ') : `annexe « Recours aux conseils extérieurs » (${co.edition})`, `exercice ${co.exercice}`) : ''}`
}

function blocRegles(idx: Index, min: Ministeres | null): string {
  const li = (x: string) => `<li>${h(lisible(x))}</li>`
  // Une limite qui ne renvoie qu'à un champ technique (déjà dite en clair plus haut) n'est pas reprise.
  const limites = [...idx.limites, ...(min?.limites ?? [])].filter((x) => !lisible(x).includes('`'))
  return `<details class="carte"><summary>Règles de lecture et limites des données</summary>
<h3>Pas de double compte</h3>
<ul>${idx.regles.map(li).join('')}</ul>
<h3>Limites</h3>
<ul>${limites.map(li).join('')}</ul>
<p>${h(idx.regle_personnes)}</p>
${source(idx.source, idx.millesime)}
</details>`
}


// ---------- Salaires nets moyens publiés par l'Insee (site/data/salaires_fonction_publique/) ----------
type ObsSal = (string | number | null)[]
interface Nomenclature {
  libelle: string
  modalites: Record<string, string>
}
interface SalIndex {
  millesime: string
  jeux: Record<'series_longues' | 'annuel', { nomenclatures: Record<string, Nomenclature>; annees: number[]; source: string; millesime: string }>
  definitions: Record<string, string>
  regles: string[]
  limites: string[]
}
interface SalTable {
  source: string
  millesime: string
  colonnes: string[]
  observations: ObsSal[]
}
const VERSANTS = [
  { valeur: '_T', libelle: 'Ensemble' },
  { valeur: '1', libelle: 'État' },
  { valeur: '2', libelle: 'Territoriale' },
  { valeur: '3', libelle: 'Hospitalière' },
]
const SAL_PLACE = `<section id="fp-salaires" aria-labelledby="fp-salaires-titre"><h2 id="fp-salaires-titre">Salaires nets moyens depuis 1995 (Insee)</h2><p class="aide">Chargement…</p></section>`
const nfSal = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

/** Valeur d'une observation dont chaque dimension vaut le code demandé (« _T » par défaut) ; null si non publiée. */
function obs(t: SalTable, filtre: Record<string, string>, annee: number): number | null {
  const dims = t.colonnes.slice(1, -1)
  const o = t.observations.find((x) => x[0] === annee && dims.every((d, i) => x[i + 1] === (filtre[d] ?? '_T') || (d === 'UNIT_MEASURE' && !(d in filtre))))
  const v = o?.[o.length - 1]
  return typeof v === 'number' ? v : null
}
const euros = (v: number | null) => (v === null ? `${badgeStatut('nonpub')} non publié` : h(eur(v)))

export function blocSalaires(idx: SalIndex, sl: SalTable, an: SalTable | null, versant: string): string {
  const M = 'SALAIRE_NET_EQTP_MENSUEL_MOYEN_EUROS_CONSTANTS'
  const E = 'SALAIRE_NET_EQTP_MENSUEL_MOYEN_EVOLUTION_CONSTANT'
  const nomV = versant === '_T' ? 'Ensemble de la fonction publique' : (idx.jeux.series_longues.nomenclatures.PUBLIC_LEGAL_FORM?.modalites[versant] ?? versant)
  const annees = [...new Set(sl.observations.filter((x) => x[1] === M && x[2] === versant).map((x) => x[0] as number))].sort((a, b) => b - a)
  if (!annees.length) return absent('Salaires non publiés pour ce versant.')
  const der = annees[0]
  const parAn = annees
    .map((a) => {
      const ev = obs(sl, { DERA_MEASURE: E, PUBLIC_LEGAL_FORM: versant }, a)
      return `<tr><th scope="row">${a}</th><td class="nombre">${euros(obs(sl, { DERA_MEASURE: M, PUBLIC_LEGAL_FORM: versant }, a))}</td><td class="nombre">${ev === null ? `${badgeStatut('nonpub')} non publié` : `${ev > 0 ? '+' : ''}${h(nfSal.format(ev))} %`}</td></tr>`
    })
    .join('')
  const statuts = idx.jeux.series_longues.nomenclatures.CIVILSERVANT_STATUS?.modalites ?? {}
  const parStatut = Object.keys(statuts)
    .filter((k) => k !== '_T')
    .map((k) => `<tr><th scope="row">${h(statuts[k])}</th><td class="nombre">${euros(obs(sl, { DERA_MEASURE: M, PUBLIC_LEGAL_FORM: versant, CIVILSERVANT_STATUS: k }, der))}</td></tr>`)
    .join('')
  const centiles = Object.keys(idx.jeux.series_longues.nomenclatures.QUANTILE?.modalites ?? {})
    .filter((k) => k.startsWith('CENTILE_'))
    .sort((a, b) => Number(a.slice(8)) - Number(b.slice(8)))
  const parCentile = centiles
    .map((k) => `<tr><th scope="row">${h(k.slice(8))} % des agents gagnent moins que</th><td class="nombre">${euros(obs(sl, { DERA_MEASURE: M, PUBLIC_LEGAL_FORM: versant, QUANTILE: k }, der))}</td></tr>`)
    .join('')
  let metiers = ''
  if (an) {
    const a = idx.jeux.annuel.annees[idx.jeux.annuel.annees.length - 1]
    const pcs = idx.jeux.annuel.nomenclatures.PCS_ESE?.modalites ?? {}
    const lignes = Object.keys(pcs)
      .filter((k) => k !== '_T')
      .map((k) => {
        const s = obs(an, { DERA_MEASURE: 'SALAIRE_NET_EQTP_MENSUEL_MOYENNE', PUBLIC_LEGAL_FORM: versant, PCS_ESE: k }, a)
        const e = obs(an, { DERA_MEASURE: 'EFFECTIFS_EQTP', PUBLIC_LEGAL_FORM: versant, PCS_ESE: k }, a)
        return s === null && e === null ? '' : `<tr><th scope="row">${h(pcs[k])}</th><td class="nombre">${euros(s)}</td><td class="nombre">${e === null ? `${badgeStatut('nonpub')} non publié` : h(entier(Math.round(e)))}</td></tr>`
      })
      .join('')
    metiers = `<details><summary>Par métier en ${a} (euros courants)</summary>
<div class="tableau-defile"><table><caption>${h(nomV)} : salaire net mensuel moyen en équivalent temps plein et effectifs en équivalent temps plein, par métier, ${a} (euros courants)</caption><thead><tr><th scope="col">Métier (nomenclature de l’Insee)</th><th scope="col" class="nombre">Salaire net moyen</th><th scope="col" class="nombre">Effectifs en EQTP</th></tr></thead><tbody>${lignes}</tbody></table></div>
<p class="aide">Euros courants de ${a} : ces montants ne se comparent pas aux séries en euros constants ci-dessus.</p>${source(an.source, an.millesime)}</details>`
  }
  return `<p>${badgeStatut('trace')} Salaire net mensuel moyen en équivalent temps plein, ${h(nomV.toLowerCase())}, en euros constants (corrigés de la hausse des prix), et évolution d’une année sur l’autre, toutes deux publiées par l’Insee.</p>
<div class="tableau-defile"><table><caption>${h(nomV)} : salaire net mensuel moyen en équivalent temps plein, euros constants, et évolution publiée</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Salaire net moyen</th><th scope="col" class="nombre">Évolution publiée</th></tr></thead><tbody>${parAn}</tbody></table></div>
<details><summary>En ${der}, par statut et catégorie</summary><div class="tableau-defile"><table><caption>${h(nomV)} : salaire net mensuel moyen en ${der} par statut, euros constants</caption><thead><tr><th scope="col">Statut</th><th scope="col" class="nombre">Salaire net moyen</th></tr></thead><tbody>${parStatut}</tbody></table></div></details>
<details><summary>En ${der}, du salaire le plus bas au plus haut (centiles)</summary><div class="tableau-defile"><table><caption>${h(nomV)} : centiles du salaire net mensuel en ${der}, euros constants</caption><thead><tr><th scope="col">Centile</th><th scope="col" class="nombre">Salaire net mensuel</th></tr></thead><tbody>${parCentile}</tbody></table></div>
<p class="aide">${h(idx.definitions.centile ?? '')}.</p></details>
${metiers}
${source(sl.source, sl.millesime)}`
}

async function salairesInsee(cible: HTMLElement, versant: string | null): Promise<void> {
  const [idx, sl, an] = await Promise.all([
    chargerSiPresent<SalIndex>('salaires_fonction_publique/index.json'),
    chargerSiPresent<SalTable>('salaires_fonction_publique/series_longues.json'),
    chargerSiPresent<SalTable>('salaires_fonction_publique/annuel.json'),
  ])
  const zone = cible.querySelector<HTMLElement>('#fp-salaires')
  if (!zone) return
  if (!idx || !sl) {
    zone.innerHTML = `<h2 id="fp-salaires-titre">Salaires nets moyens depuis 1995 (Insee)</h2>${absent('Salaires de l’Insee non disponibles.')}`
    return
  }
  const v = VERSANTS.some((x) => x.valeur === versant) ? versant! : '_T'
  zone.innerHTML = `<h2 id="fp-salaires-titre">Salaires nets moyens depuis 1995 (Insee)</h2>
<p>Ce que gagne en moyenne un agent public par mois, après cotisations et avant impôt sur le revenu, ramené à un temps plein : des moyennes et des centiles publiés par l’Insee, jamais le salaire d’une personne.</p>
${segmente({ id: 'fp-sal-versant', etiquette: 'Fonction publique', options: VERSANTS, valeur: v })}
<div id="fp-sal-detail" aria-live="polite">${blocSalaires(idx, sl, an, v)}</div>
<ul class="limites">${[...idx.regles, ...idx.limites].map((x) => `<li>${h(x)}</li>`).join('')}</ul>`
  zone.querySelector('#fp-sal-versant')?.addEventListener('change', () => {
    zone.querySelector<HTMLElement>('#fp-sal-detail')!.innerHTML = blocSalaires(idx, sl, an, valeurChoix(zone, 'fp-sal-versant'))
  })
}

const section = (id: string, titre: string, corps: string) => (corps ? `<section aria-labelledby="${id}"><h2 id="${id}">${h(titre)}</h2>${corps}</section>` : '')

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const [idx, ser, emp, min, ter, cab, racine] = await Promise.all([
    chargerSiPresent<Index>('fonction_publique/index.json'),
    chargerSiPresent<Series>('fonction_publique/effectifs_series.json'),
    chargerSiPresent<Emploi>('fonction_publique/emploi.json'),
    chargerSiPresent<Ministeres>('fonction_publique/ministeres.json'),
    chargerSiPresent<Territoires>('fonction_publique/territoires.json'),
    chargerSiPresent<Cabinets>('fonction_publique/cabinets.json'),
    chargerSiPresent<Noeud>('arbre/racine.json'),
  ])
  if (!idx || !ser) {
    cible.innerHTML = enCours('La fonction publique', 'Effectifs des fonctions publiques de l’État, territoriale et hospitalière, dépenses de personnel de l’État et leur évolution.') + partPersonnelle()
    return
  }
  // Source des dépenses de personnel : le fichier par programme (site/data/effectifs) du programme le plus important.
  const grand = min?.ministeres
    .flatMap((m) => m.programmes)
    .filter((p) => p.fichier_effectifs && (p.titre2_eur ?? 0) > 0)
    .sort((a, c) => (c.titre2_eur ?? 0) - (a.titre2_eur ?? 0))[0]
  const eff = grand?.fichier_effectifs ? await chargerSiPresent<EffectifsProgramme>(grand.fichier_effectifs) : null
  const b = idx.reperes.budget_etat
  const total = racine && racine.millesime === b.millesime_titre2 && racine.md > 0 ? racine.md * 1e9 : null
  const anSer = ser.series[ser.series.length - 1]?.annee

  cible.innerHTML = `
<h1>La fonction publique</h1>
<p class="chapeau">Combien de personnes travaillent pour l’État, les collectivités locales et les hôpitaux publics, ce que l’État dépense pour ses agents sur 100 € de son budget, et comment ces effectifs évoluent d’une année sur l’autre.</p>
<p>Ce que la page ne montre pas : aucun salaire ni aucun nom de personne, uniquement des totaux et des moyennes (les salaires moyens et les centiles publiés par l’Insee) ; les dépenses de personnel des collectivités et des hôpitaux, qui figurent dans leurs propres comptes.</p>
<ul class="legende-statuts" aria-label="Statut des chiffres de cette page">
  <li>${traitStatut('trace')}<span><strong>Tracé</strong> : chiffre lu tel quel dans une publication (Insee, budget de l’État, annexes du projet de loi de finances)</span></li>
  <li>${traitStatut('approche')}<span><strong>Approché</strong> : rapprochement fait par le site entre deux nomenclatures publiées, méthode écrite à côté</span></li>
  ${LEGENDE_CALCULE}
  <li>${traitStatut('nonpub')}<span><strong>Non publié</strong> : donnée absente des fichiers publiés par le site, la phrase dit ce qui manque</span></li>
</ul>
${section('fp-combien', `Combien de personnes${anSer ? ` fin ${anSer}` : ''}`, blocPersonnes(ser, idx))}
${section('fp-masse', 'Ce que l’État dépense pour ses agents', blocMasse(idx, min, racine, eff))}
${section('fp-ministeres', 'Par ministère : emplois votés et dépenses de personnel', min ? blocMinisteres(min, total, b) : absent('Détail par ministère non disponible.'))}
${section('fp-remunerations', 'Rémunérations : des moyennes, jamais un salaire individuel', blocRemunerations(min, b))}
${SAL_PLACE}
${section('fp-qui', 'Qui sont les agents', emp ? blocQui(emp) : absent('Caractéristiques des agents non disponibles.'))}
${section('fp-evolutions', 'Comment les effectifs évoluent', blocEvolutions(emp, ser))}
${section('fp-deux', 'Deux façons de compter les agents de l’État', blocDeuxComptes(min, ser, emp, b))}
${section('fp-ecarts', 'Écarts entre sources', blocEcarts(idx, ser, emp))}
${section('fp-territoires', 'Dans ton département ou ta région', ter ? blocTerritoires(ter, params.get('dep')) : absent('Effectifs par département non disponibles.'))}
${section('fp-cabinets', 'Cabinets ministériels et conseils extérieurs', blocCabinetsConseils(idx, cab))}
${blocRegles(idx, min)}
<ul class="liens-sortie">
  <li><a href="${lien('/beneficiaires/programme')}">Un programme en détail : emplois par catégorie et dépenses de personnel</a></li>
  <li><a href="${lien('/local')}">Budget de ma commune : la part du personnel dans les dépenses locales</a></li>
  <li><a href="${lien('/explorer/collectivites')}">Les collectivités locales</a></li>
</ul>
${partPersonnelle()}`

  cible.querySelector<HTMLFormElement>('#fp-territoire-form')?.addEventListener('submit', (e) => e.preventDefault())
  const choix = cible.querySelector<HTMLSelectElement>('#fp-territoire')
  const zone = cible.querySelector<HTMLElement>('#fp-zone-territoire')
  if (choix && zone && ter) {
    const t = ter
    // Choix repris de l'adresse (?dep=44) : l'attribut selected suffit au navigateur, la propriété le confirme partout.
    const dep = params.get('dep')
    if (dep && t.departements[dep]) choix.value = `d-${dep}`
    choix.addEventListener('change', () => {
      zone.innerHTML = zoneTerritoire(t, choix.value)
      rendreDefilables(zone)
    })
  }
  return { suite: salairesInsee(cible, params.get('versant')) }
}

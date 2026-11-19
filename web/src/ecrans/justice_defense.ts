// Justice et défense : budget de la justice (chiffres clés publiés par le ministère), prisons, défense, emplois,
// évolutions, sur 100 € dépensés par l'État. Données : site/data/justice_defense/ (pipeline/justice_defense.py) ; pour la
// défense et les séries longues, l'arbre du budget de l'État, les effectifs et les données d'exécution que le site publie
// déjà. Les pages qui détaillent ces données (détail du budget, programme, ce qui a été fait) sont liées, pas recopiées.
// Le montant par journée de détention et le montant par établissement calculés par le pipeline (prisons.json,
// montant_calcule et montant_calcule_eur) attendent l'arbitrage de l'éditeur : ils ne sont jamais lus ni affichés. Seul un
// montant publié par une source officielle, cité tel quel, pourrait l'être ; aucun ne figure dans les données reprises.
import { billet, type Famille, type Part, tableauBillet, ton } from '../composants/billet'
import { partPersonnelle } from '../composants/hub'
import { chargerSiPresent, type Noeud, VUES_ARBRE } from '../donnees'
import { lien, type Rendu } from '../routeur'
import { absent, appliquerLargeurs, badgeStatut, barres, entier, h, libelle, md, numeroProgramme, pct, source, type Statut, STATUTS, sur100, surligne, traitStatut } from '../util'

interface SourceIndex {
  id: string
  titre: string
  page: string
  licence: string
  collecte_le: string
  statut: string
}
interface Index {
  millesime: string
  source: string
  avertissement?: string
  effectifs_defense?: { statut: string; constat_le: string }
  limites?: string[]
  sources?: SourceIndex[]
  sources_inaccessibles?: { source: string; motif: string }[]
}
interface Annuel {
  annee: number
  meur: number
}
interface Ecart {
  objet: string
  source: string
  montant: number
  autre_source: string
  autre_montant: number
  ecart: number
  lecture?: string
}
interface BudgetJustice {
  millesime: string
  source: string
  avertissement?: string
  budget: {
    credits_paiement: Annuel[]
    dont_personnel?: Annuel[]
    autorisations_engagement?: Annuel[]
    annee_programmes: number
    programmes: { programme: string; libelle: string; cp_meur: number; part_pct: number }[]
    ordre?: string
  }
  frais_de_justice?: { total: Annuel[]; civile_et_commerciale?: Annuel[]; criminelle_correctionnelle_contraventionnelle?: Annuel[] }
  aide_juridictionnelle?: {
    depenses_effectives: Annuel[]
    note?: string
    verse_aux_avocats?: { annee: number; total_meur: number; aide_juridictionnelle_meur?: number; civil_meur?: number; penal_meur?: number; administratif_meur?: number; aide_intervention_avocat_meur?: number }
  }
  ecarts?: Ecart[]
}
interface Situation {
  capacite_operationnelle: number | null
  detenus: number | null
  densite_pct: number | null
}
interface Prisons {
  source: string
  date_reference: string
  definitions?: Record<string, string>
  ordre?: { regle: string }
  national: Situation & { date: string }
  etablissements: (Situation & { etablissement: string; quartier: string; disp: string })[]
  controles?: {
    somme_detenus_lignes?: number
    detenus_total_national?: number
    ecarts_totaux_directions?: { disp: string; source: string; montant: number; autre_source: string; autre_montant: number; ecart: number }[]
  }
  serie_nationale: (Situation & { date: string; metropole?: Situation; outre_mer?: Situation })[]
  couverture?: { premiere_date: string; derniere_date: string; mois_absents?: string[] }
  limites?: string[]
}
interface Mesure {
  unite: string
  annees: number[]
  regions: { region: string; valeurs: (number | null)[] }[]
  hors_region?: { pays: string; valeurs: (number | null)[] }[]
  total_general: { valeurs: (number | null)[] }
  controles?: { ecarts_regions?: { region: string; annee: number; source: string; montant: number; autre_source: string; autre_montant: number; ecart: number }[] }
}
interface Armement {
  source: string
  millesime: string
  avertissement?: string
  notes?: Record<string, string>
  prises_de_commandes: Mesure
  livraisons: Mesure
  licences: Mesure
}
interface Effectifs {
  programme: string
  libelle: string
  etpt: number | null
  millesime_etpt: string
  source: string
  millesime: string
}
interface Realisations {
  programme: string
  libelle: string
  prevu_depense: { annees: { annee: number; source: string | null; depense_constatee_eur: number | null; trou?: string }[]; note_perimetre?: string }
}
interface Mission {
  poste: Noeud
  mission: Noeud
}
interface Missions {
  justice?: Mission
  defense?: Mission
}

/** Arbre d'exécution : vue par défaut du site, celle des « sur 100 € ». */
const VUE = VUES_ARBRE[0]
/** Sources de justice_defense/index.json réellement utilisées sur cette page (les ressorts des juridictions n'y sont pas). */
const SOURCES_PAGE = ['chiffres_cles', 'population_ecrouee', 'effectifs_defense', 'armement']
/** Textes du pipeline qui portent sur le montant calculé par établissement (en attente d'arbitrage) : jamais affichés. */
export const CALCUL = /montant|journ[ée]e de d[ée]tention|programme 107|realisations\/107/i

/** Ce que finance chaque programme, en mots courants (texte du site ; les montants viennent toujours des données). */
export const EN_CLAIR: Record<string, string> = {
  '166': 'les tribunaux et les cours : magistrats, greffes, frais de justice',
  '107': 'les prisons et le suivi des personnes condamnées hors de prison',
  '182': 'la prise en charge des mineurs suivis par la justice',
  '101': 'surtout l’aide juridictionnelle, qui prend en charge les frais d’avocat des personnes aux revenus modestes, et l’aide aux victimes',
  '310': 'l’administration centrale du ministère, son informatique et son action sociale',
  '335': 'l’instance chargée de la nomination et de la discipline des magistrats',
  '212': 'surtout la rémunération des militaires et des civils du ministère, aussi l’immobilier et les systèmes d’information',
  '146': 'l’achat et le développement des équipements des armées, dont la dissuasion nucléaire',
  '178': 'l’entraînement des armées, l’entretien des matériels et les opérations',
  '144': 'le renseignement, la recherche et les relations internationales de défense',
}

const nf1 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
/** Millions d'euros avec une décimale, comme dans les tableaux publiés. */
const meur = (x: number) => `${nf1.format(x)} M€`
/** Millions d'euros en écriture courante : « 12,38 Md€ », « 704,0 M€ ». */
export const montant = (x: number) => (Math.abs(x) >= 1000 ? `${nf2.format(x / 1000)} Md€` : meur(x))
/** Euros en milliards, deux décimales (séries d'exécution). */
const mdEur = (x: number) => `${nf2.format(x / 1e9)} Md€`
/** Variation entre deux montants : signe écrit (+ ou −), jamais de couleur. */
export const variation = (avant: number, apres: number) => {
  const v = ((apres - avant) / avant) * 100
  return `${v < 0 ? '−' : '+'}${nf1.format(Math.abs(v))} %`
}
const annee = (millesime?: string) => /\b(20\d\d)\b/.exec(millesime ?? '')?.[1]
const trier = (s: Annuel[] = []) => [...s].sort((a, b) => a.annee - b.annee)
const valeurAn = (s: Annuel[] | undefined, an: number) => s?.find((x) => x.annee === an)?.meur

const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
/** « 2026-09-01 » devient « 1er septembre 2026 ». */
export function dateLongue(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return iso
  const j = Number(m[3])
  return `${j === 1 ? '1er' : j} ${MOIS[Number(m[2]) - 1]} ${m[1]}`
}

/** Retire des textes du pipeline les renvois techniques entre accents graves (noms de champs, de fichiers). */
export const nettoyer = (t: string) =>
  t
    .replace(/\s*\([^()]*`[^()]*\)/g, '')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\s+([.,])/g, '$1')
    .trim()
/** Motif rédigé par le pipeline, sans ses renvois aux fichiers internes. */
const lisible = (t: string) =>
  nettoyer(t)
    .split(' ; ')
    .filter((s) => !/\.json\b/.test(s))
    .join(' ; ')
    .replace(/\bce module\b/g, 'le site')
/** Segments d'un texte du pipeline, sans ceux qui portent sur le montant calculé. */
export const sansCalcul = (t: string, separateur = ' ; ') =>
  t
    .split(separateur)
    .filter((s) => !CALCUL.test(s))
    .join(separateur)

/** Régions du rapport sur l'armement, publiées en capitales : « ASIE DU SUD-EST » devient « Asie du Sud-Est ». */
const MAJUSCULE = new Set(['afrique', 'amérique', 'asie', 'océanie', 'caraïbe', 'caraïbes', 'nord', 'sud', 'est', 'ouest', 'nord-est', 'nord-ouest', 'sud-est', 'sud-ouest', 'moyen-orient', 'union'])
export function nomRegion(r: string): string {
  if (r !== r.toUpperCase()) return r
  return r
    .toLowerCase()
    .split(' ')
    .map((w, i) => (i === 0 || MAJUSCULE.has(w) ? w.split('-').map((x) => x.charAt(0).toUpperCase() + x.slice(1)).join('-') : w))
    .join(' ')
}

/** Statut d'un chiffre : motif et mot, puis ce qu'il veut dire ici. */
const STATUT_ICI: Record<Statut, string> = {
  trace: 'chaque chiffre figure dans le document cité sous ce bloc',
  approche: 'estimation dont la méthode est publiée',
  nonpub: 'aucune donnée ouverte pour ce chiffre',
}
const statut = (s: Statut, texte = STATUT_ICI[s]) => `<p class="aide">${badgeStatut(s)} ${h(texte)}</p>`

function legende(): string {
  return `<ul class="legende-statuts" aria-label="Légende des statuts des chiffres">
<li>${traitStatut('trace')}<span><strong>${STATUTS.trace.motif} : ${STATUTS.trace.libelle.toLowerCase()}.</strong> Le chiffre figure dans un document public, cité sous chaque bloc avec son année.</span></li>
<li>${traitStatut('nonpub')}<span><strong>${STATUTS.nonpub.motif} : ${STATUTS.nonpub.libelle.toLowerCase()}.</strong> Aucune donnée ouverte pour ce chiffre : cela décrit l’état de la publication, pas l’usage de l’argent.</span></li>
</ul>`
}

/** Missions Justice et Défense dans l'arbre du budget de l'État (exécution, vue par défaut). */
function trouverMissions(racine: Noeud | null): Missions {
  const toutes = (racine?.enfants ?? []).flatMap((poste) => (poste.enfants ?? []).filter((x) => x.niveau === 'mission').map((mission) => ({ poste, mission })))
  return { justice: toutes.find((x) => x.mission.nom === 'Justice'), defense: toutes.find((x) => x.mission.nom === 'Défense') }
}
const numeros = (mission?: Noeud) => (mission?.enfants ?? []).map((p) => numeroProgramme(p.id)).filter((x): x is string => !!x)

interface Valeur {
  montant: number
  libelle: string
}
/** Ligne « même chose, plusieurs publications » : toutes les valeurs (M€) et leur écart ; aucune n'est retenue à la place des autres. */
export function ligneEcart(objet: string, valeurs: Valeur[], lecture = 'Les montants sont repris tels quels, sans choisir entre eux.'): string {
  const ms = valeurs.map((v) => v.montant)
  const e = Math.max(...ms) - Math.min(...ms)
  const texte = e < 0.05 ? 'même montant' : `écart${valeurs.length > 2 ? ' maximal' : ''} de ${meur(e)}`
  return `<li><span>${h(objet)}</span><span class="montant">${h(texte)}</span><span class="dest">${h(valeurs.map((v) => `${meur(v.montant)} (${v.libelle})`).join(' ; '))}. ${h(lecture)}</span></li>`
}
/** « realisations/107.json (dépense constatée) » devient une phrase lisible. */
const nomSource = (s: string) =>
  s.replace(/realisations\/(\d{3})\.json(?:\s*\(([^)]*)\))?/, (_, n: string, precision?: string) => `données d’exécution du programme ${n}${precision ? `, ${precision}` : ''}, page « Ce qui a été fait »`)

function tableauAnnuel(legendeTableau: string, entete: string, lignes: [string, Annuel[] | undefined][], avecVariation = false): string {
  const annees = [...new Set(lignes.flatMap(([, s]) => (s ?? []).map((x) => x.annee)))].sort((a, b) => a - b)
  const derniers = annees.slice(-2)
  return `<div class="tableau-defile"><table><caption>${h(legendeTableau)}</caption><thead><tr><th scope="col">${h(entete)}</th>${annees
    .map((a) => `<th scope="col" class="nombre">${a}</th>`)
    .join('')}${avecVariation && derniers.length === 2 ? `<th scope="col" class="nombre">De ${derniers[0]} à ${derniers[1]}</th>` : ''}</tr></thead><tbody>${lignes
    .filter(([, s]) => s?.length)
    .map(([nom, s]) => {
      const valeurs = annees.map((a) => valeurAn(s, a))
      const [x, y] = derniers.map((a) => valeurAn(s, a))
      return `<tr><th scope="row">${h(nom)}</th>${valeurs.map((val) => `<td class="nombre">${val === undefined ? 'non publié' : h(nf1.format(val))}</td>`).join('')}${
        avecVariation && derniers.length === 2 ? `<td class="nombre">${x !== undefined && y !== undefined && x !== 0 ? h(variation(x, y)) : ''}</td>` : ''
      }</tr>`
    })
    .join('')}</tbody></table></div>`
}

function blocSur100(racine: Noeud | null, m: Missions): string {
  const titre = '<h2 id="jd-titre-100">Sur 100 € dépensés par l’État</h2>'
  if (!racine || !m.justice || !m.defense || !(racine.md > 0))
    return `<section aria-labelledby="jd-titre-100">${titre}${absent('Arbre du budget de l’État non disponible : la part de la justice et de la défense n’est pas calculée.')}</section>`
  const total = racine.md
  const an = annee(racine.millesime) ?? VUE.millesime
  const s = (x: number) => (x / total) * 100
  const j = m.justice.mission
  const d = m.defense.mission
  const famille = (poste: Noeud): Famille => ton('etat', Math.max(0, (racine.enfants ?? []).indexOf(poste)))
  const deux = [
    { nom: d.nom, noeud: d, famille: famille(m.defense.poste) },
    { nom: j.nom, noeud: j, famille: famille(m.justice.poste) },
  ].sort((a, b) => b.noeud.md - a.noeud.md)
  const reste = total - j.md - d.md
  const parts: Part[] = [
    ...deux.map((x) => ({ nom: x.nom, valeur: x.noeud.md, texte: sur100(s(x.noeud.md)), famille: x.famille, lien: lien('/explorer/etat/detail', { m: VUE.cle, id: x.noeud.id }), detail: md(x.noeud.md) })),
    { nom: 'Le reste du budget de l’État', valeur: reste, texte: sur100(s(reste)), famille: 'papier', lien: lien('/explorer/etat', { m: VUE.cle }), detail: md(reste) },
  ]
  const autres = (m.defense.poste.enfants ?? []).filter((x) => x !== d && x.md > 0)
  return `<section aria-labelledby="jd-titre-100">
${titre}
${billet(parts, { etiquette: `Billet de 100 € dépensés par l’État en ${an} : défense, justice et le reste du budget`, legendes: true })}
<div class="carte" data-cle>
  <p>Sur 100 € dépensés par l’État en ${h(an)} (${h(md(total))} au total), <strong>${surligne(sur100(s(j.md + d.md)))}</strong> sont allés à la défense et à la justice : ${h(sur100(s(d.md)))} à la défense (${h(md(d.md))}) et ${h(sur100(s(j.md)))} à la justice (${h(md(j.md))}).</p>
  ${statut('trace')}
  ${
    autres.length
      ? `<p class="aide">Le grand poste « ${h(libelle(m.defense.poste.nom))} » de la page <a href="${lien('/explorer/etat', { m: VUE.cle, poste: m.defense.poste.id })}">Le budget de l’État</a> compte aussi ${autres
          .map((x) => `la mission « ${h(x.nom)} » (${h((x.enfants ?? []).map((p) => p.nom).join(', '))} : ${h(md(x.md))})`)
          .join(' et ')} : ${autres.length > 1 ? 'elles ne sont pas comptées' : 'elle n’est pas comptée'} ici.</p>`
      : ''
  }
  ${source(racine.source ?? '', racine.millesime)}
</div>
${tableauBillet(parts, `Sur 100 € dépensés par l’État en ${an}`)}
</section>`
}

function blocJustice(b: BudgetJustice | null): string {
  const titre = '<h2 id="jd-titre-justice">La justice</h2>'
  if (!b) return `<section aria-labelledby="jd-titre-justice">${titre}${absent('Budget de la justice non disponible : le fichier des chiffres clés de la Justice n’est pas encore produit.')}</section>`
  const cp = trier(b.budget.credits_paiement)
  const dernier = cp[cp.length - 1]
  const avant = cp[cp.length - 2]
  const personnel = dernier ? valeurAn(b.budget.dont_personnel, dernier.annee) : undefined
  const aj = trier(b.aide_juridictionnelle?.depenses_effectives)
  const ajDernier = aj[aj.length - 1]
  const cles = [
    dernier
      ? `<li class="cle-famille"><strong>${h(montant(dernier.meur))}</strong><span>budget de la justice en ${dernier.annee} (crédits de paiement consommés)${avant ? `, ${h(variation(avant.meur, dernier.meur))} par rapport à ${avant.annee}` : ''}</span>${badgeStatut('trace')}</li>`
      : '',
    dernier && personnel !== undefined ? `<li><strong>${h(montant(personnel))}</strong><span>dont dépenses de personnel en ${dernier.annee}</span>${badgeStatut('trace')}</li>` : '',
    ajDernier ? `<li><strong>${h(montant(ajDernier.meur))}</strong><span>d’aide juridictionnelle en ${ajDernier.annee} (dépenses effectives)</span>${badgeStatut('trace')}</li>` : '',
  ].join('')
  const progs = b.budget.programmes
  const frais = b.frais_de_justice
  const avocats = b.aide_juridictionnelle?.verse_aux_avocats
  const note = b.aide_juridictionnelle?.note ?? ''
  return `<section aria-labelledby="jd-titre-justice">
${titre}
<ul class="cles" aria-label="Chiffres clés du budget de la justice">${cles}</ul>
<h3>Où va le budget de la justice en ${b.budget.annee_programmes}</h3>
<div class="carte">
  ${barres(
    progs.map((p) => ({
      nom: `${p.libelle} (programme ${p.programme})`,
      valeur: p.cp_meur,
      texte: montant(p.cp_meur),
      lien: lien('/beneficiaires/programme', { p: p.programme }),
      detail: [EN_CLAIR[p.programme], `${pct(p.part_pct)} du budget de la justice`].filter(Boolean).join(' · '),
      statut: 'trace' as const,
    })),
    undefined,
    `Budget de la justice en ${b.budget.annee_programmes}, par programme`,
  )}
  ${b.budget.ordre ? `<p class="aide" data-regle-ordre>${h(b.budget.ordre)}</p>` : ''}
  <p class="aide">Chaque programme ouvre sa page : nature de la dépense et emplois.</p>
  ${statut('trace')}
  ${source(b.source, b.millesime)}
</div>
<h3>D’une année à l’autre</h3>
${tableauAnnuel(
  'Budget de la justice, en millions d’euros',
  'Montant',
  [
    ['Crédits de paiement', b.budget.credits_paiement],
    ['dont dépenses de personnel', b.budget.dont_personnel],
    ['Autorisations d’engagement', b.budget.autorisations_engagement],
  ],
  true,
)}
<p class="aide">Crédits de paiement : ce qui est payé dans l’année. Autorisations d’engagement : ce que l’État s’engage à dépenser (contrats, marchés, constructions), payé parfois sur plusieurs années.</p>
${
  frais?.total.length
    ? `<h3>Les frais de justice</h3>
<p>Dépenses engagées pendant les procédures : expertises, analyses, traductions, interceptions judiciaires.</p>
${tableauAnnuel('Frais de justice, en millions d’euros', 'Procédures', [
  ['Toutes procédures', frais.total],
  ['Civiles et commerciales', frais.civile_et_commerciale],
  ['Pénales (criminelles, correctionnelles, contraventionnelles)', frais.criminelle_correctionnelle_contraventionnelle],
])}`
    : ''
}
${
  aj.length
    ? `<h3>L’aide juridictionnelle</h3>
<p>L’État prend en charge tout ou partie des frais de justice et d’avocat des personnes aux revenus modestes.</p>
${tableauAnnuel('Aide juridictionnelle, en millions d’euros', 'Montant', [['Dépenses effectives', aj]])}
${/CARPA/.test(note) ? '<p class="aide">Dépenses effectives : dotation versée chaque année aux caisses des règlements pécuniaires des avocats (CARPA), et sommes versées aux huissiers, experts et enquêteurs, selon la note du document.</p>' : ''}
${
  avocats
    ? `<p>Autre source, autre périmètre : en ${avocats.annee}, ${h(meur(avocats.total_meur))} ont été versés aux avocats au titre de l’aide${
        avocats.aide_juridictionnelle_meur !== undefined && avocats.aide_intervention_avocat_meur !== undefined
          ? `, dont ${h(meur(avocats.aide_juridictionnelle_meur))} d’aide juridictionnelle${
              avocats.civil_meur !== undefined && avocats.penal_meur !== undefined && avocats.administratif_meur !== undefined
                ? ` (affaires civiles ${h(meur(avocats.civil_meur))}, pénales ${h(meur(avocats.penal_meur))}, administratives ${h(meur(avocats.administratif_meur))})`
                : ''
            } et ${h(meur(avocats.aide_intervention_avocat_meur))} d’aide à l’intervention de l’avocat`
          : ''
      }${/UNCA/.test(note) ? ' (statistiques de l’Union nationale des CARPA)' : ''}. Ces montants et les dépenses effectives ne s’additionnent pas.</p>`
    : ''
}`
    : ''
}
${b.avertissement ? `<p class="aide">${h(b.avertissement)}</p>` : ''}
<p class="aide">Les écarts entre ces montants et d’autres publications sont réunis plus bas, sous « Même année, plusieurs publications ».</p>
</section>`
}

function blocPrisons(p: Prisons | null): string {
  const titre = '<h2 id="jd-titre-prisons">Les prisons</h2>'
  if (!p) return `<section aria-labelledby="jd-titre-prisons">${titre}${absent('Statistique des prisons non disponible : le fichier n’est pas encore produit.')}</section>`
  const n = p.national
  const date = dateLongue(n.date)
  const point = p.serie_nationale.find((x) => x.date === n.date)
  const sourceP = sansCalcul(p.source)
  // Valeur absente à la source : dite en mots, jamais 0.
  const nb = (x: number | null) => (x === null ? 'non publié' : entier(x))
  const zones =
    point?.metropole && point.outre_mer
      ? `<p class="aide">${(
          [
            ['Métropole', point.metropole],
            ['Outre-mer', point.outre_mer],
          ] as [string, Situation][]
        )
          .map(([nom, x]) => `${nom} : ${h(nb(x.detenus))} personnes détenues pour ${h(nb(x.capacite_operationnelle))} places${x.densite_pct === null ? '' : ` (densité ${h(pct(x.densite_pct))})`}`)
          .join(' ; ')}.</p>`
      : ''
  // Évolution : la situation au 1er janvier de chaque année, et la dernière situation publiée.
  const parDate = new Map(p.serie_nationale.map((x) => [x.date, x]))
  const absents = new Set(p.couverture?.mois_absents ?? [])
  const debut = Number((p.couverture?.premiere_date ?? p.serie_nationale[0]?.date ?? n.date).slice(0, 4))
  const fin = Number(n.date.slice(0, 4))
  const lignes: string[] = []
  const cellules = (x: Situation) =>
    `<td class="nombre">${h(nb(x.capacite_operationnelle))}</td><td class="nombre">${h(nb(x.detenus))}</td><td class="nombre">${x.densite_pct === null ? 'non publiée' : h(pct(x.densite_pct))}</td>`
  if (!n.date.endsWith('-01-01')) lignes.push(`<tr><th scope="row">${h(date)}</th>${cellules(n)}</tr>`)
  for (let a = fin; a >= debut; a--) {
    const d = `${a}-01-01`
    const x = parDate.get(d)
    if (x) lignes.push(`<tr><th scope="row">${h(dateLongue(d))}</th>${cellules(x)}</tr>`)
    else if (absents.has(d)) lignes.push(`<tr><th scope="row">${h(dateLongue(d))}</th><td colspan="3">publié en PDF ou dans un ancien format de tableur, non repris ici</td></tr>`)
  }
  // Détail par établissement : une ligne par établissement et type de quartier, groupées par direction interrégionale.
  const groupes = new Map<string, Prisons['etablissements']>()
  for (const e of p.etablissements) groupes.set(e.disp, [...(groupes.get(e.disp) ?? []), e])
  const c = p.controles
  const ecartsDirections = (c?.ecarts_totaux_directions ?? []).map(
    (e) => `${e.disp} : ${entier(e.montant)} (${e.source}) et ${entier(e.autre_montant)} (${e.autre_source}), écart ${e.ecart < 0 ? '−' : '+'}${entier(Math.abs(e.ecart))}`,
  )
  const limites = (p.limites ?? []).filter((l) => !CALCUL.test(l)).map(nettoyer)
  return `<section aria-labelledby="jd-titre-prisons">
${titre}
<div class="carte">
  <p>Au ${h(date)}, <strong>${h(nb(n.detenus))} personnes</strong> étaient détenues pour <strong>${h(nb(n.capacite_operationnelle))} places</strong> opérationnelles${
    n.densite_pct !== null ? ` : ${h(entier(Math.round(n.densite_pct)))} personnes pour 100 places (densité carcérale publiée : ${h(pct(n.densite_pct))})` : ''
  }.</p>
  ${barres(
    (
      [
        ['Places opérationnelles', n.capacite_operationnelle],
        ['Personnes détenues', n.detenus],
      ] as [string, number | null][]
    )
      .filter((x): x is [string, number] => x[1] !== null)
      .map(([nom, v]) => ({ nom, valeur: v, texte: entier(v), statut: 'trace' as const })),
    undefined,
    `Places et personnes détenues au ${date}`,
  )}
  ${zones}
  ${p.definitions?.capacite_operationnelle ? `<p class="aide">Places opérationnelles : ${h(p.definitions.capacite_operationnelle)}. Personnes détenues : ${h(p.definitions.detenus ?? '')}.</p>` : ''}
  ${statut('trace')}
  ${source(sourceP, `situation au ${date}`)}
</div>
<h3>Au 1er janvier de chaque année</h3>
<div class="tableau-defile"><table><caption>Places opérationnelles, personnes détenues et densité carcérale, France entière</caption><thead><tr><th scope="col">Date</th><th scope="col" class="nombre">Places opérationnelles</th><th scope="col" class="nombre">Personnes détenues</th><th scope="col" class="nombre">Densité</th></tr></thead><tbody>${lignes.join('')}</tbody></table></div>
${statut('trace', 'chaque chiffre figure dans la statistique mensuelle publiée par l’administration pénitentiaire')}
<details>
  <summary>Les ${h(entier(p.etablissements.length))} lignes publiées au ${h(date)}, établissement par établissement</summary>
  ${p.definitions?.quartier ? `<p class="aide">Type de quartier : ${h(p.definitions.quartier)}.</p>` : ''}
  <div class="tableau-defile"><table><caption>Places opérationnelles, personnes détenues et densité par établissement et type de quartier, au ${h(date)}</caption><thead><tr><th scope="col">Établissement</th><th scope="col">Quartier</th><th scope="col" class="nombre">Places</th><th scope="col" class="nombre">Personnes détenues</th><th scope="col" class="nombre">Densité</th></tr></thead>${[
    ...groupes,
  ]
    .map(
      ([disp, es]) =>
        `<tbody><tr><th scope="rowgroup" colspan="5">${h(disp)}</th></tr>${es
          .map((e) => `<tr><th scope="row">${h(e.etablissement)}</th><td>${h(e.quartier)}</td>${cellules(e)}</tr>`)
          .join('')}</tbody>`,
    )
    .join('')}</table></div>
  ${p.ordre?.regle ? `<p class="aide" data-regle-ordre>${h(p.ordre.regle)}</p>` : ''}
  ${
    c?.somme_detenus_lignes !== undefined && c.detenus_total_national !== undefined
      ? `<p class="aide">Somme des lignes publiées : ${h(entier(c.somme_detenus_lignes))} personnes détenues ; total national publié : ${h(entier(c.detenus_total_national))}. ${
          ecartsDirections.length ? `Totaux de direction publiés et sommes des lignes : ${h(ecartsDirections.join(' ; '))}. ` : ''
        }Les deux valeurs sont reprises telles quelles.</p>`
      : ''
  }
</details>
${limites.length ? `<details><summary>Limites de ces chiffres</summary><ul>${limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul></details>` : ''}
<p class="aide">Montant par journée de détention : aucun ne figure parmi les indicateurs publiés du programme « Administration pénitentiaire » (rapports annuels de performance, page <a href="${lien('/decisions/realisations', { p: '107' })}">Ce qui a été fait</a>). La page n’en affiche donc pas.</p>
</section>`
}

function blocDefense(racine: Noeud | null, m: Missions, sousArbres: (Noeud | null)[]): string {
  const titre = '<h2 id="jd-titre-defense">La défense</h2>'
  if (!racine || !m.defense || !(racine.md > 0)) return `<section aria-labelledby="jd-titre-defense">${titre}${absent('Arbre du budget de l’État non disponible : le budget de la défense n’est pas affiché.')}</section>`
  const total = racine.md
  const an = annee(racine.millesime) ?? VUE.millesime
  const s = (x: number) => (x / total) * 100
  const d = m.defense.mission
  const programmes = [...(d.enfants ?? [])].sort((a, b) => b.md - a.md)
  // Surcoûts des opérations : actions publiées dans plusieurs programmes (fonctionnement dans « Préparation et emploi des
  // forces », personnel dans « Soutien de la politique de la défense », extérieures et intérieures ensemble pour le personnel).
  const actions = (d.enfants ?? []).flatMap((p, i) => (sousArbres[i]?.enfants ?? []).map((a) => ({ action: a, programme: p, source: sousArbres[i] })))
  const ops = actions.filter((x) => /surco[uû]ts liés aux opérations/i.test(x.action.nom)).sort((a, b) => b.action.md - a.action.md)
  const totalOps = ops.reduce((t, x) => t + x.action.md, 0)
  const sourceOps = ops[0]?.source ?? null
  const equipement = programmes.find((p) => /équipement/i.test(p.nom))
  return `<section aria-labelledby="jd-titre-defense">
${titre}
<div class="carte">
  <p>En ${h(an)}, la mission Défense a dépensé <strong>${h(md(d.md))}</strong>, soit ${h(sur100(s(d.md)))} sur 100 € dépensés par l’État.</p>
  ${barres(
    programmes.map((p) => {
      const n = numeroProgramme(p.id) ?? ''
      return {
        nom: `${p.nom} (programme ${n})`,
        valeur: p.md,
        texte: md(p.md),
        lien: lien('/explorer/etat/detail', { m: VUE.cle, id: p.id }),
        detail: [EN_CLAIR[n], `${sur100(s(p.md))} sur 100 € dépensés par l’État`].filter(Boolean).join(' · '),
        statut: 'trace' as const,
      }
    }),
    undefined,
    `Mission Défense en ${an}, par programme`,
  )}
  <p class="aide" data-regle-ordre>Programmes par montant décroissant. Chaque programme ouvre son détail action par action${equipement ? ` : pour les équipements, « ${h(equipement.nom)} »` : ''}.</p>
  ${statut('trace')}
  ${source(racine.source ?? '', racine.millesime)}
</div>
<h3>Les opérations extérieures et intérieures</h3>
${
  ops.length
    ? `<div class="carte">
  <p>Le budget publie à part ce que les opérations ajoutent au fonctionnement courant des armées : les « surcoûts ». En ${h(an)} :</p>
  <ul class="lignes">${ops
    .map((x) => `<li><span>« ${h(x.action.nom)} »</span><span class="montant">${h(md(x.action.md))}</span><span class="dest">programme « ${h(x.programme.nom)} » · ${h(sur100(s(x.action.md)))} sur 100 € dépensés par l’État</span></li>`)
    .join('')}</ul>
  ${ops.length > 1 ? `<p>Ensemble de ces lignes : <strong>${h(md(totalOps))}</strong>, soit ${h(sur100(s(totalOps)))} sur 100 € dépensés par l’État.</p>` : ''}
  <p class="aide" data-regle-ordre>Lignes par montant décroissant. Une ligne de dépenses de personnel qui ne sépare pas les opérations extérieures des opérations intérieures est montrée telle quelle, sans être répartie.</p>
  ${statut('trace')}
  ${sourceOps ? source(sourceOps.source ?? racine.source ?? '', sourceOps.millesime ?? racine.millesime) : ''}
</div>`
    : absent('Montant des opérations extérieures non disponible : le détail des actions de la mission Défense n’a pas pu être lu.')
}
</section>`
}

function blocEffectifs(eff: (Effectifs | null)[], m: Missions, idx: Index | null): string {
  const titre = '<h2 id="jd-titre-effectifs">Les emplois</h2>'
  const groupes: [string, Noeud | undefined][] = [
    ['Justice', m.justice?.mission],
    ['Défense', m.defense?.mission],
  ]
  const parNumero = new Map(eff.filter((e): e is Effectifs => !!e && e.etpt !== null).map((e) => [e.programme, e]))
  const lignes = groupes.flatMap(([nom, mission]) => {
    const es = numeros(mission)
      .map((n) => parNumero.get(n))
      .filter((e): e is Effectifs => !!e)
    if (!es.length) return []
    const total = es.reduce((t, e) => t + (e.etpt ?? 0), 0)
    return [
      `<tbody><tr><th scope="rowgroup" colspan="2">Mission ${h(nom)}</th></tr>${es
        .map((e) => `<tr><th scope="row"><a href="${lien('/beneficiaires/programme', { p: e.programme })}">${h(e.libelle)} (programme ${h(e.programme)})</a></th><td class="nombre">${h(entier(Math.round(e.etpt ?? 0)))}</td></tr>`)
        .join('')}${es.length > 1 ? `<tr><th scope="row">Ensemble des programmes de la mission ${h(nom)}</th><td class="nombre">${h(entier(Math.round(total)))}</td></tr>` : ''}</tbody>`,
    ]
  })
  const premier = [...parNumero.values()][0]
  const millesime = premier ? premier.millesime_etpt.replace(/\bLFI (\d{4})\b/, 'budget voté pour $1 (loi de finances initiale)') : ''
  const sourceDefense = idx?.sources?.find((s) => s.id === 'effectifs_defense')
  const anDefense = annee(sourceDefense?.titre)
  const nonPublie =
    idx?.effectifs_defense?.statut === 'donnee_absente_a_la_source'
      ? `<p class="absent">${badgeStatut('nonpub')} Emplois militaires et civils de la défense${anDefense ? ` en ${h(anDefense)}` : ''}, par catégorie : le fichier mis en ligne par le ministère des Armées ne contient que sa fiche descriptive, sans aucun effectif (constat du ${h(dateLongue(idx.effectifs_defense.constat_le))}). Cela décrit l’état de la publication.</p>`
      : ''
  return `<section aria-labelledby="jd-titre-effectifs">
${titre}
${
  lignes.length
    ? `<p>Emplois votés pour chaque programme, en équivalents temps plein travaillé : une personne à mi-temps compte pour un demi. C’est un plafond voté, pas le nombre de personnes réellement employées.</p>
<div class="tableau-defile"><table><caption>Emplois votés par programme${millesime ? `, ${h(millesime)}` : ''}, en équivalents temps plein travaillé</caption><thead><tr><th scope="col">Programme</th><th scope="col" class="nombre">Emplois</th></tr></thead>${lignes.join('')}</table></div>
<p class="aide">Le jeu publié ne donne pas d’emplois pour les autres programmes de ces deux missions. Chaque programme ouvre sa page, avec les emplois par catégorie.</p>
${statut('trace')}
${premier ? source(premier.source, premier.millesime) : ''}`
    : absent('Emplois par programme non disponibles.')
}
${nonPublie}
</section>`
}

function blocArmement(a: Armement | null): string {
  if (!a) return ''
  const mesures: [string, Mesure, (x: number) => string][] = [
    ['Prises de commandes (millions d’euros courants)', a.prises_de_commandes, (x) => nf1.format(x)],
    ['Livraisons (millions d’euros courants)', a.livraisons, (x) => nf1.format(x)],
    ['Licences acceptées (nombre)', a.licences, (x) => entier(x)],
  ]
  const annees = [...a.prises_de_commandes.annees].sort((x, y) => y - x)
  const cellule = (mes: Mesure, an: number, f: (x: number) => string) => {
    const i = mes.annees.indexOf(an)
    const v = i < 0 ? undefined : mes.total_general.valeurs[i]
    return `<td class="nombre">${v === null || v === undefined ? 'aucune valeur publiée' : h(f(v))}</td>`
  }
  const dernier = annees[0]
  const parRegion = mesures
    .map(([nom, mes, f]) => {
      const i = mes.annees.indexOf(dernier)
      if (i < 0) return ''
      const lignes = [...mes.regions.map((r) => [nomRegion(r.region), r.valeurs[i]] as const), ...(mes.hors_region ?? []).map((r) => [r.pays, r.valeurs[i]] as const)]
      const ecarts = (mes.controles?.ecarts_regions ?? []).map(
        (e) => `${nomRegion(e.region)}, ${e.annee} : ${nf1.format(e.montant)} (${e.source}) et ${nf1.format(e.autre_montant)} (${e.autre_source}), écart ${e.ecart < 0 ? '−' : '+'}${nf1.format(Math.abs(e.ecart))}`,
      )
      return `<div class="tableau-defile"><table><caption>${h(nom)}, par région, en ${dernier}</caption><thead><tr><th scope="col">Région</th><th scope="col" class="nombre">${dernier}</th></tr></thead><tbody>${lignes
        .map(([r, v]) => `<tr><th scope="row">${h(r)}</th><td class="nombre">${v === null || v === undefined ? 'aucune valeur publiée' : h(f(v))}</td></tr>`)
        .join('')}</tbody></table></div>${ecarts.length ? `<p class="aide">Total publié et somme des pays : ${h(ecarts.join(' ; '))}. Les deux valeurs sont reprises telles quelles.</p>` : ''}`
    })
    .join('')
  return `<section aria-labelledby="jd-titre-armement">
<h2 id="jd-titre-armement">À part : les exportations d’armement</h2>
<p>Ce ne sont pas des dépenses de l’État : ces chiffres décrivent les ventes de matériels de guerre et assimilés à l’étranger, que l’État autorise et dont il rend compte chaque année au Parlement.</p>
<ul>
  <li>Prises de commandes : contrats signés avec des clients étrangers et entrés en vigueur.</li>
  <li>Livraisons : matériels livrés dans l’année.</li>
  <li>Licences acceptées : autorisations d’exporter accordées par l’État.</li>
</ul>
<div class="tableau-defile"><table><caption>Exportations d’armement de la France, par année</caption><thead><tr><th scope="col">Année</th>${mesures
    .map(([nom]) => `<th scope="col" class="nombre">${h(nom)}</th>`)
    .join('')}</tr></thead><tbody>${annees.map((an) => `<tr><th scope="row">${an}</th>${mesures.map(([, mes, f]) => cellule(mes, an, f)).join('')}</tr>`).join('')}</tbody></table></div>
${a.avertissement ? `<p class="avertissement">${h(a.avertissement)}</p>` : ''}
<p class="aide">${a.notes?.zero ? `${h(a.notes.zero)} ` : ''}Un tiret dans le tableau publié est affiché « aucune valeur publiée », jamais 0.</p>
<details>
  <summary>Par région, en ${dernier}</summary>
  ${parRegion}
  ${a.notes?.hors_region ? `<p class="aide">${h(a.notes.hors_region)}</p>` : ''}
</details>
${statut('trace')}
${source(a.source, a.millesime)}
</section>`
}

function blocSources(idx: Index | null): string {
  if (!idx) return ''
  const sources = (idx.sources ?? []).filter((s) => SOURCES_PAGE.includes(s.id))
  // Limites générales du jeu ; celles des prisons et des emplois sont dites dans leur bloc, les ressorts ne sont pas sur cette page.
  const limites = (idx.limites ?? []).filter((l) => !CALCUL.test(l) && !/^(Ressorts|Effectifs|Établissements|Montant)\b/.test(l)).map(nettoyer)
  const lienSource = (s: SourceIndex) => (/^https:\/\//.test(s.page) ? `<a href="${h(s.page)}" rel="noopener noreferrer">${h(s.titre)}</a>` : h(s.titre))
  return `<section aria-labelledby="jd-titre-sources">
<h2 id="jd-titre-sources">Sources, statuts et limites</h2>
${legende()}
${idx.avertissement ? `<p>${h(idx.avertissement)}</p>` : ''}
${
  sources.length
    ? `<h3>Documents repris sur cette page</h3><ul>${sources
        .map((s) => `<li>${lienSource(s)} (${h(s.licence)}, collecté le ${h(dateLongue(s.collecte_le))} : ${h(s.statut)})</li>`)
        .join('')}</ul><p class="aide">Le budget de la défense, les emplois et les séries depuis 2010 viennent des données du budget de l’État déjà publiées par le site, citées sous chaque bloc.</p>`
    : ''
}
${limites.length ? `<h3>Limites</h3><ul>${limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul>` : ''}
${
  idx.sources_inaccessibles?.length
    ? `<h3>Ce qui n’a pas pu être repris</h3><ul>${idx.sources_inaccessibles.map((s) => `<li>${h(s.source)} : ${h(lisible(s.motif))}</li>`).join('')}</ul>`
    : ''
}
</section>`
}

/** Séries longues : dépense constatée de chaque mission, somme de ses programmes (données d'exécution du site). */
async function evolution(cible: HTMLElement, m: Missions, b: BudgetJustice | null, racine: Noeud | null): Promise<void> {
  const corps = cible.querySelector<HTMLElement>('#jd-evolution')
  if (!corps) return
  const groupes = (
    [
      ['Justice', m.justice?.mission],
      ['Défense', m.defense?.mission],
    ] as [string, Noeud | undefined][]
  ).filter((g): g is [string, Noeud] => !!g[1] && numeros(g[1]).length > 0)
  const series = await Promise.all(
    groupes.map(async ([nom, mission]) => {
      const nums = numeros(mission)
      const fichiers = await Promise.all(nums.map((n) => chargerSiPresent<Realisations>(`realisations/${n}.json`)))
      return { nom, mission, nums, fichiers: fichiers.every((f) => !!f) ? (fichiers as Realisations[]) : null }
    }),
  )
  const lues = series.filter((x): x is typeof x & { fichiers: Realisations[] } => !!x.fichiers)
  type Cellule = { total: number; source: string | null } | { trou: string } | { manquants: string[] }
  // Somme d'une année : seulement si chaque programme de la mission a un montant publié ; sinon on dit ce qui manque.
  const cellule = (fichiers: Realisations[], nums: string[], an: number): Cellule | null => {
    const lignes = fichiers.map((f) => f.prevu_depense.annees.find((x) => x.annee === an))
    if (lignes.every((l) => !l)) return null
    if (lignes.every((l) => l && l.depense_constatee_eur !== null)) return { total: lignes.reduce((t, l) => t + (l!.depense_constatee_eur ?? 0), 0), source: lignes[0]!.source }
    const trou = lignes.find((l) => l?.trou)?.trou
    if (lignes.every((l) => !l || l.depense_constatee_eur === null) && trou) return { trou }
    return { manquants: nums.filter((_, i) => !lignes[i] || lignes[i]!.depense_constatee_eur === null) }
  }
  const annees = [...new Set(lues.flatMap((g) => g.fichiers.flatMap((f) => f.prevu_depense.annees.map((x) => x.annee))))].sort((a, b) => b - a)
  const sources = new Map<number, string>()
  const anneesTrou = new Set<number>()
  const lignes = annees
    .map((an) => {
      const cs = lues.map((g) => cellule(g.fichiers, g.nums, an))
      if (cs.every((c) => !c)) return ''
      return `<tr><th scope="row">${an}</th>${cs
        .map((c) => {
          if (!c) return '<td class="nombre">non disponible</td>'
          if ('total' in c) {
            if (c.source && !sources.has(an)) sources.set(an, c.source.split(' ; ')[0])
            return `<td class="nombre">${h(mdEur(c.total))}</td>`
          }
          if ('trou' in c) {
            anneesTrou.add(an)
            return `<td class="nombre">${traitStatut('nonpub')} non publié</td>`
          }
          return `<td class="nombre">somme non calculée : programme${c.manquants.length > 1 ? 's' : ''} ${h(c.manquants.join(', '))} sans montant publié</td>`
        })
        .join('')}</tr>`
    })
    .filter(Boolean)
  const trous = [...anneesTrou].sort((a, b) => a - b)
  const enumerer = (xs: (string | number)[]) => (xs.length > 1 ? `${xs.slice(0, -1).join(', ')} et ${xs[xs.length - 1]}` : String(xs[0] ?? ''))
  // Même mission, même année, plusieurs publications : écarts publiés par le pipeline, données d'exécution, chiffres clés
  // de la Justice et arbre du budget de l'État (celui des « sur 100 € »). Toutes les valeurs sont montrées, aucune n'est retenue.
  const anArbre = Number(annee(racine?.millesime))
  const comparaisons = (b?.ecarts ?? []).map((e) =>
    ligneEcart(`${e.objet.charAt(0).toUpperCase()}${e.objet.slice(1)}`, [
      { montant: e.montant, libelle: nomSource(e.source) },
      { montant: e.autre_montant, libelle: nomSource(e.autre_source) },
    ], e.lecture),
  )
  for (const [nom, mission] of groupes) {
    const g = lues.find((x) => x.nom === nom)
    const cles = nom === 'Justice' ? (b?.budget.credits_paiement ?? []) : []
    const ans = [...new Set([...cles.map((x) => x.annee), ...(anArbre ? [anArbre] : [])])].sort((x, y) => x - y)
    for (const an of ans) {
      const valeurs: Valeur[] = []
      const c = g ? cellule(g.fichiers, g.nums, an) : null
      if (c && 'total' in c) valeurs.push({ montant: c.total / 1e6, libelle: 'données d’exécution, somme des programmes' })
      const v = valeurAn(cles, an)
      if (v !== undefined) valeurs.push({ montant: v, libelle: 'chiffres clés de la Justice' })
      if (an === anArbre) valeurs.push({ montant: mission.md * 1000, libelle: 'arbre du budget de l’État, celui des « sur 100 € »' })
      if (valeurs.length > 1) comparaisons.push(ligneEcart(`Mission ${nom}, ${an}`, valeurs))
    }
  }
  const note = lues[0]?.fichiers[0]?.prevu_depense.note_perimetre
  const tableau = lues.length
    ? `<p>Dépense constatée chaque année, mission par mission : somme des programmes de la mission, en milliards d’euros courants (sans correction de l’inflation).</p>
<div class="tableau-defile"><table><caption>Dépense constatée par mission et par année, en milliards d’euros courants</caption><thead><tr><th scope="col">Année</th>${lues
        .map((g) => `<th scope="col" class="nombre">${h(g.nom)} (${g.nums.length} programmes)</th>`)
        .join('')}</tr></thead><tbody>${lignes.join('')}</tbody></table></div>
${statut('trace', 'chaque montant est la somme de dépenses publiées, programme par programme')}
${trous.length ? statut('nonpub', `aucune donnée d’exécution par programme n’est publiée en données ouvertes pour ${enumerer(trous)}`) : ''}
${note ? `<p class="aide">${h(note)}</p>` : ''}
<details><summary>Source de chaque année</summary><ul>${[...sources]
        .sort((x, y) => y[0] - x[0])
        .map(([an, s]) => `<li>${an} : ${h(s)}</li>`)
        .join('')}</ul></details>`
    : absent('Données d’exécution par programme non disponibles : les montants année par année ne sont pas affichés.')
  corps.innerHTML = `${tableau}
${comparaisons.length ? `<h3>Même année, plusieurs publications</h3><ul class="lignes">${comparaisons.join('')}</ul>` : ''}
${
  lues.length
    ? `<p>Programme par programme, avec le budget voté et l’écart entre voté et dépensé :</p>
<ul class="liste-colonnes">${lues
        .flatMap((g) => g.fichiers)
        .map((f) => `<li><a href="${lien('/decisions/realisations', { p: f.programme })}">${h(f.libelle)} (programme ${h(f.programme)})</a></li>`)
        .join('')}</ul>`
    : ''
}`
  appliquerLargeurs(corps)
}

export async function rendre(cible: HTMLElement): Promise<Rendu> {
  const [idx, budget, prisons, armement, racine] = await Promise.all([
    chargerSiPresent<Index>('justice_defense/index.json'),
    chargerSiPresent<BudgetJustice>('justice_defense/budget_justice.json'),
    chargerSiPresent<Prisons>('justice_defense/prisons.json'),
    chargerSiPresent<Armement>('justice_defense/armement.json'),
    chargerSiPresent<Noeud>(`${VUE.dossier}/racine.json`),
  ])
  const m = trouverMissions(racine)
  const nums = [...numeros(m.justice?.mission), ...numeros(m.defense?.mission)]
  const [sousArbres, effectifs] = await Promise.all([
    Promise.all((m.defense?.mission.enfants ?? []).map((p) => (p.enfants ? Promise.resolve(p) : p.fichier ? chargerSiPresent<Noeud>(p.fichier) : Promise.resolve(null)))),
    Promise.all(nums.map((n) => chargerSiPresent<Effectifs>(`effectifs/${n}.json`))),
  ])
  const branche = !!(idx || budget || prisons || armement)
  // Sorties vers le détail ligne par ligne ; le budget de l'État et « Ce qui a été fait » sont déjà dans « Voir aussi ».
  const sorties = (
    [
      ['La justice ligne par ligne', m.justice?.mission],
      ['La défense ligne par ligne', m.defense?.mission],
    ] as [string, Noeud | undefined][]
  )
    .filter((x): x is [string, Noeud] => !!x[1])
    .map(([nom, n]) => `<li><a href="${lien('/explorer/etat/detail', { m: VUE.cle, id: n.id })}">${h(nom)}</a></li>`)
  cible.innerHTML = `
<h1>Justice et défense</h1>
<p class="chapeau">Ce que l’État dépense pour la justice (tribunaux, prisons, protection judiciaire de la jeunesse, aide juridictionnelle) et pour la défense (armées, équipements, opérations), les emplois votés et l’évolution des montants, avec l’année, la source et le statut de chaque chiffre.</p>
<p class="chapeau">La page ne montre pas ce que tu verses toi-même (<a href="${lien('/')}">calcule-le depuis l’accueil</a>), ni la police et la gendarmerie, ni les résultats mesurés de ces dépenses, qui sont dans <a href="${lien('/decisions/realisations')}">Ce qui a été fait</a>.</p>
${branche ? '' : `<div class="en-cours"><p><strong>Données en cours d’intégration.</strong> Budget de la justice, prisons et exportations d’armement : cette partie se remplira dès que les fichiers seront publiés.</p></div>`}
${blocSur100(racine, m)}
${blocJustice(budget)}
${blocPrisons(prisons)}
${blocDefense(racine, m, sousArbres)}
${blocEffectifs(effectifs, m, idx)}
<section aria-labelledby="jd-titre-evolution">
<h2 id="jd-titre-evolution">Ce qui a été dépensé, année après année</h2>
<div id="jd-evolution"><p class="aide">Lecture des données d’exécution…</p></div>
</section>
${blocArmement(armement)}
${blocSources(idx)}
${sorties.length ? `<ul class="liens-sortie">${sorties.join('')}</ul>` : ''}
${partPersonnelle()}`
  return { suite: evolution(cible, m, budget, racine) }
}

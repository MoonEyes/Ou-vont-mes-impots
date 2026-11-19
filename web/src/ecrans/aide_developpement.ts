// Aide publique au développement (site/data/aide_developpement/, produit par pipeline/aide_developpement.py) :
// montant déclaré à l'OCDE, dons et prêts, canaux, régions et pays, organismes qui versent, part du budget de l'État.
// Règles des données reprises ici : les grandeurs ne s'additionnent jamais, dons et prêts restent dans des colonnes
// séparées, les écarts entre sources sont montrés sans être arbitrés, aucun ordre par montant (règle écrite sous chaque tableau).
// Déjà ailleurs, donc pas refait : le détail des programmes (« Le détail du budget de l'État », « Un programme en détail »),
// vers lequel la page renvoie.
// Financement des prêts de l'AFD : le pipeline ne publie plus de texte rédigé à ce sujet (« financement_des_prets »
// d'index.json ne contient que le périmètre et les identifiants des citations ; les champs « financement » des grandeurs
// sont vides). La page cite, mot pour mot, la page de l'AFD et le projet annuel de performances 2026 (CITATIONS,
// documents consultés le 18/11/2026).
import { choixLiens, listeRecherche } from '../composants/choix'
import { parAdministration } from '../calcul/repartition'
import { partPersonnelle } from '../composants/hub'
import { chargerSiPresent, VUES_ARBRE } from '../donnees'
import { session } from '../etat'
import { lien } from '../routeur'
import { absent, badgeStatut, eurLisible, h, pct, source, sur100, surligne, badgeCalcule } from '../util'

const ROUTE = '/explorer/aide-developpement'

type Cellule = string | number | null
interface Tableau {
  colonnes: string[]
  lignes: Cellule[][]
}
interface VueCredits {
  vue: string
  millesime: string
  fichier_racine: string
  mission: { id: string; nom: string; md: number }
  programmes: { numero: string; nom: string; md: number; fichier: string }[]
}
interface Ecart {
  annee: number
  comparaison: string
  unite: string
  source: string
  montant: number | null
  autre_source: string
  autre_montant: number | null
  ecart: number | null
  ecart_pct: number | null
  lecture: string
}
export interface Index {
  regle: string
  credits_budgetaires: { unite: string; source: string; vues: VueCredits[]; lecture: string }
  totaux: {
    apd_declaree: Tableau & { perimetre: string }
    afd: Tableau & { perimetre: string; annees_partielles: number[] }
  }
  ecarts: Ecart[]
  ecarts_note: string
  sources: { id: string; nom: string; url: string; licence: string; producteur: string; collecte_le: string }[]
  sources_inaccessibles: { source: string; constat: string }[]
  limites: string[]
}
interface Pays {
  code: string
  nom: string
  nom_tri: string
  type: string
  categorie_cad: string
  region: string
}
export interface ApdDeclaree {
  millesime: string
  source: string
  definitions: Record<string, string>
  annees: number[]
  par_annee: Tableau
  perimetre_ventilations: string
  colonnes_ventilations: string[]
  par_canal: Tableau
  par_agence: Tableau
  par_pays: Tableau
  pays: Pays[]
  limites: string[]
  collecte_le: string
}
interface Afd {
  source: string
  annees_partielles: number[]
  colonnes_montants: string[]
  par_pays: Tableau
  limites: string[]
}
interface Ocde {
  source: string
  versements_par_pays: { colonnes: string[]; lignes: Cellule[][]; note: string }
}
interface Proparco {
  millesime: string
  source: string
  definitions: Record<string, string>
  par_annee: Tableau
  limites: string[]
  collecte_le: string
}
interface ExpertiseFrance {
  millesime: string
  source: string
  definitions: Record<string, string>
  par_bailleur: Tableau
  ecartes: { motif: string; contrats?: number; montant_initial_maximal_eur?: number }[]
}
interface Racine {
  md: number
  millesime?: string
  source?: string
}

// Documents cités mot pour mot, vérifiés le 18/11/2026 chez leurs auteurs.
export const PAP_2026 = {
  titre: 'Projet annuel de performances 2026 de la mission « Aide publique au développement » (annexe au projet de loi de finances pour 2026)',
  url: 'https://www.assemblee-nationale.fr/dyn/contenu/visualisation/1087948/file/PAP2026_BG_Aide_publique_developpement_AD.pdf',
}
export const AFD_PRET = {
  titre: 'Agence française de développement, « Le prêt, premier outil financier du groupe AFD », publié le 14 janvier 2026',
  url: 'https://www.afd.fr/fr/actualites/pret-finance-developpement-afd',
}
export const GLOSSAIRE = {
  titre: 'Glossaire de l’aide publique au développement, Direction générale du Trésor et ministère de l’Europe et des affaires étrangères (termes mis à jour le 16 juin 2022, Licence Ouverte 2.0)',
  url: 'https://data.aide-developpement.gouv.fr/explore/dataset/glossaire-apd/',
}
interface Citation {
  texte: string
  qui: string
  ref: { titre: string; url: string }
  page?: number
}
export const CITATIONS: Record<'emprunt' | 'bonification' | 'fondsPropres' | 'bilateral' | 'multilateral' | 'don' | 'pret', Citation> = {
  emprunt: {
    texte: 'Pour réunir ces sommes, le Groupe emprunte lui-même sur les marchés financiers auprès d’investisseurs privés, de fonds de pension et de banques centrales.',
    qui: 'L’Agence française de développement, à propos des prêts qu’elle accorde',
    ref: AFD_PRET,
  },
  bonification: {
    texte: 'Les bonifications d’intérêt versées par l’État permettent d’abaisser le taux d’intérêt des prêts octroyés par l’AFD au bénéfice de ses contreparties.',
    qui: 'Programme 110 « Aide économique et financière au développement »',
    ref: PAP_2026,
    page: 43,
  },
  fondsPropres: {
    texte: 'Les crédits du programme 365 permettent de doter en capital l’Agence française de développement (AFD).',
    qui: 'Programme 365 « Renforcement des fonds propres de l’Agence française de développement »',
    ref: PAP_2026,
    page: 54,
  },
  bilateral: { texte: 'Flux transmis directement par un pays donateur à un pays bénéficiaire de l’aide.', qui: 'Aide bilatérale', ref: GLOSSAIRE },
  multilateral: { texte: 'Flux d’aide acheminés par le biais d’une organisation internationale active dans le domaine du développement.', qui: 'Aide multilatérale', ref: GLOSSAIRE },
  don: { texte: 'Le don correspond à un transfert en espèces ou en nature qui n’entraîne pas d’obligation juridique de remboursement pour le bénéficiaire.', qui: 'Don', ref: GLOSSAIRE },
  pret: { texte: 'Transferts financiers pour lesquels un remboursement est requis.', qui: 'Prêt', ref: GLOSSAIRE },
}

/** Ministère ou direction responsable de chaque programme, d'après le projet annuel de performances 2026 (pages 14 et 54). */
export const RESPONSABLES: Record<string, string> = {
  '110': 'ministère de l’Économie, des Finances et de la Souveraineté industrielle et énergétique',
  '209': 'ministère de l’Europe et des Affaires étrangères',
  '365': 'Direction générale du Trésor',
  '384': 'les deux ministères, conjointement',
}
/** Catégories de la liste des bénéficiaires, en toutes lettres d'après le glossaire officiel de l'aide. */
const CATEGORIES: Record<string, string> = {
  PMA: 'pays les moins avancés',
  'Autres PFR': 'autres pays à faible revenu',
  PRITI: 'pays à revenu intermédiaire de la tranche inférieure',
  PRITS: 'pays à revenu intermédiaire de la tranche supérieure',
  Régional: 'regroupement régional',
  Multilatéral: 'organisations multilatérales',
}
// Libellés de la source qui sont des sigles ou des codes : écrits en toutes lettres.
const ORGANISMES: Record<string, string> = {
  'MIN/EQUIPEMENT': 'Ministère de l’équipement (libellé de la source : « MIN/EQUIPEMENT »)',
  'MINEFI/BDF': 'Ministère de l’économie et des finances, Banque de France (libellé de la source : « MINEFI/BDF »)',
  'MINEFI/NATIXIS': 'Ministère de l’économie et des finances, Natixis (libellé de la source : « MINEFI/NATIXIS »)',
}
const BAILLEURS: Record<string, string> = {
  'Agence des Nations Unies - UN': 'Agence des Nations unies',
  'Agence Française de Développement - AFD': 'Agence française de développement',
  'Autre Bailleur Français - FR': 'Autre bailleur français',
  'Autre Ministère Français - FR': 'Autre ministère français',
  'MEAE - FR': 'Ministère de l’Europe et des affaires étrangères',
  'MINEFI - FR': 'Ministère de l’économie et des finances',
  'Multi - Bailleur': 'Plusieurs bailleurs',
  'Organisation Internationale/multilatérale - OI': 'Organisation internationale ou multilatérale',
  'Union Européenne - UE': 'Union européenne',
}
const INSTRUMENTS: Record<string, string> = {
  pret: 'Prêts',
  participation: 'Prises de participation',
  garantie: 'Garanties',
  don: 'Subventions',
  accompagnement_technique: 'Accompagnement technique',
  obligation: 'Obligations',
  non_renseigne: 'Type non renseigné',
}
const COMPARAISONS: Record<string, string> = {
  'APD bilatérale, dons versés': 'Aide bilatérale, dons versés',
  'APD bilatérale, prêts bruts versés': 'Aide bilatérale, prêts versés (avant remboursements)',
  "AFD, dons d'APD versés": 'Agence française de développement, dons versés',
  "AFD, prêts d'APD versés": 'Agence française de développement, prêts versés',
}
const ECART_SOURCES: Record<string, string> = {
  ocde_dac2a: 'OCDE, versements par pays (table DAC2A)',
  'apd_declaree (bilatéral)': 'Direction générale du Trésor, aide bilatérale déclarée',
  afd_iati: 'Agence française de développement, publication au standard international de l’aide (IATI)',
  'apd_declaree (agence AFD)': 'Direction générale du Trésor, lignes déclarées pour l’Agence française de développement',
}
/** Regroupements sans pays : placés après les régions, avec un libellé explicite. */
const HORS_REGIONS: Record<string, string> = {
  Multilatéral: 'Organisations multilatérales (non réparties par pays)',
  'Pays en développement, non spécifié': 'Pays en développement, sans pays précisé',
}
export const REGLE_ORDRE_REGIONS = 'Régions par ordre alphabétique, puis les deux regroupements sans pays ; aucun classement par montant.'
export const REGLE_ORDRE_SOURCE = 'Ordre alphabétique, comme dans la source ; aucun classement par montant.'
/** Kosovo : XKX pour la Direction générale du Trésor et l'AFD, XKV pour l'OCDE (contrat d'interface, section 2.31). */
const CODE_OCDE: Record<string, string> = { XKX: 'XKV' }

const NON_PUBLIE = 'non publié'
const nf1 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const nf0 = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 })
const num = (x: Cellule | undefined): number | null => (typeof x === 'number' ? x : null)
/** Montant en euros lisible ; une valeur absente de la source reste « non publié », jamais 0. */
export const montant = (x: Cellule | undefined) => (typeof x === 'number' ? eurLisible(x) : NON_PUBLIE)
/** Milliards d'euros à deux décimales : la même précision pour deux montants et leur écart. */
export const milliards = (eur: number) => `${nf2.format(eur / 1e9)} Md€`
const dollars = (x: Cellule | undefined) => (typeof x === 'number' ? nf1.format(x) : NON_PUBLIE)
/** Première lettre en capitale (définitions des données, écrites en minuscules). */
const majuscule = (t: string) => t.charAt(0).toUpperCase() + t.slice(1)
const anneeDe = (texte: string) => Number(/(20\d\d)/.exec(texte)?.[1] ?? NaN)
const periode = (v: VueCredits) => VUES_ARBRE.find((x) => x.dossier === v.vue)?.periode ?? v.millesime
const td = (texte: string) => `<td class="nombre">${h(texte)}</td>`
const regleOrdre = (texte: string) => `<p class="aide" data-regle-ordre>${h(texte)}</p>`
const ancre = (ref: { titre: string; url: string }, page?: number) => `<a href="${h(ref.url)}" rel="noopener noreferrer">${h(ref.titre)}</a>${page ? `, page ${page}` : ''}`
/** Citation mot pour mot : qui parle, le texte entre guillemets, le document et sa page. */
const citer = (c: Citation) => `<li><span>${h(c.qui)}</span><span class="dest">« ${h(c.texte)} » ${ancre(c.ref, c.page)}.</span></li>`
const somme = (xs: (number | null)[]) => (xs.some((x) => x !== null) ? xs.reduce<number>((s, x) => s + (x ?? 0), 0) : null)
/** Lignes d'un tableau compact pour une année. */
const deLAnnee = (t: Tableau | undefined, an: number) => (t?.lignes ?? []).filter((l) => l[0] === an)

/** Valeurs d'une ventilation (canal, organisme, pays) : dons, prêts, autres, équivalent-don, perçu. */
function ventilation(apd: ApdDeclaree, l: Cellule[], cles: number) {
  const v = (c: string) => num(l[cles + apd.colonnes_ventilations.indexOf(c)])
  return { dons: v('dons_verses_eur'), prets: v('prets_verses_eur'), autres: v('autres_verses_eur'), equivalent: v('equivalent_don_eur'), percu: v('percu_eur') }
}

/** Dons, prêts et autres instruments versés par région pour une année : somme, colonne par colonne, des lignes publiées. */
export function parRegion(apd: ApdDeclaree, an: number) {
  const region = new Map(apd.pays.map((p) => [p.code, p.region]))
  const acc = new Map<string, { dons: (number | null)[]; prets: (number | null)[]; autres: (number | null)[] }>()
  for (const l of deLAnnee(apd.par_pays, an)) {
    const r = region.get(String(l[1])) ?? 'Non classé'
    const v = ventilation(apd, l, 2)
    const a = acc.get(r) ?? { dons: [], prets: [], autres: [] }
    a.dons.push(v.dons)
    a.prets.push(v.prets)
    a.autres.push(v.autres)
    acc.set(r, a)
  }
  const cle = (r: string) => (r in HORS_REGIONS ? `1 ${Object.keys(HORS_REGIONS).indexOf(r)}` : `0 ${r}`)
  return [...acc.entries()]
    .sort((a, b) => cle(a[0]).localeCompare(cle(b[0]), 'fr'))
    .map(([r, a]) => ({ region: r, nom: HORS_REGIONS[r] ?? r, dons: somme(a.dons), prets: somme(a.prets), autres: somme(a.autres) }))
}

function enCours(): string {
  return `<h1>L’aide publique au développement</h1><div class="en-cours"><p><strong>Données en cours d’intégration.</strong> Montant déclaré, dons et prêts, pays bénéficiaires et part du budget de l’État.</p><p>Cette page se remplira dès que les fichiers seront publiés.</p></div><p class="liens-sortie"><a href="${lien('/explorer/etat')}">Le budget de l’État, sur 100 € dépensés</a></p>${partPersonnelle()}`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const [idx, apd] = await Promise.all([chargerSiPresent<Index>('aide_developpement/index.json'), chargerSiPresent<ApdDeclaree>('aide_developpement/apd_declaree.json')])
  if (!idx || !apd) {
    cible.innerHTML = enCours()
    return
  }
  const vues = idx.credits_budgetaires.vues
  const racines = await Promise.all(vues.map((v) => chargerSiPresent<Racine>(v.fichier_racine)))
  const annees = [...apd.annees].sort((a, b) => a - b)
  const demandee = Number(params.get('a'))
  const an = annees.includes(demandee) ? demandee : annees[annees.length - 1]
  const choixPays = apd.pays.find((p) => p.code === params.get('pays')) ?? null
  const srcApd = `${apd.source}, collecté le ${apd.collecte_le}`

  const choixAnnee = choixLiens({ etiquette: 'Année de la déclaration', liens: annees.map((a) => ({ href: lien(ROUTE, { a, pays: choixPays?.code }), libelle: String(a), courant: a === an })) })

  cible.innerHTML = `
<h1>L’aide publique au développement</h1>
<p class="chapeau">L’aide publique au développement (APD) regroupe les dons, les prêts et d’autres apports que la France accorde aux pays en développement, directement ou par des organisations internationales. Cette page montre le montant déclaré chaque année à l’Organisation de coopération et de développement économiques (OCDE), ses canaux, les régions et pays qui la reçoivent, les organismes qui la versent, dont l’Agence française de développement (AFD), et la part du budget de l’État.</p>
<p class="chapeau">Elle ne dit pas ce que chaque projet a produit et ne nomme aucune personne : les montants sont regroupés par pays, par région ou par organisme. Les montants de producteurs différents ne s’additionnent pas.</p>
${choixAnnee}
${cles(apd, idx, an, srcApd)}
${blocSur100(vues, racines)}
${blocComparaison(idx, apd, vues, racines)}
${blocCanaux(apd, an, srcApd)}
${blocRegions(apd, an, srcApd, choixPays)}
${blocOrganismes(apd, idx, an, srcApd)}
${blocEcarts(idx, an)}
${blocSources(idx)}
<p class="liens-sortie"><a href="${lien('/explorer/etat/detail', { m: 'execution2024', id: vues[0]?.mission.id })}">La mission « Aide publique au développement » dans le détail du budget de l’État</a> · <a href="${lien('/beneficiaires/programme', { p: '209' })}">Le programme 209 en détail : nature de la dépense et bénéficiaires</a></p>
${partPersonnelle()}`

  cible.querySelector<HTMLFormElement>('#aide-dev-pays-form')?.addEventListener('submit', (e) => {
    e.preventDefault()
    const code = cible.querySelector<HTMLSelectElement>('#aide-dev-choix-pays')?.value ?? ''
    location.hash = lien(ROUTE, { a: an, pays: code })
  })
  const suite = (async () => {
    const [proparco, ef, afd, ocde] = await Promise.all([
      chargerSiPresent<Proparco>('aide_developpement/proparco.json'),
      chargerSiPresent<ExpertiseFrance>('aide_developpement/expertise_france.json'),
      choixPays ? chargerSiPresent<Afd>('aide_developpement/afd.json') : Promise.resolve(null),
      choixPays ? chargerSiPresent<Ocde>('aide_developpement/ocde.json') : Promise.resolve(null),
    ])
    const groupe = cible.querySelector('#aide-dev-groupe')
    if (groupe) groupe.innerHTML = `${proparco ? blocProparco(proparco) : absent('Données de Proparco non disponibles.')}${ef ? blocExpertise(ef) : absent('Données d’Expertise France non disponibles.')}`
    const zone = cible.querySelector('#aide-dev-pays')
    if (zone && choixPays) zone.innerHTML = fichePays(choixPays, apd, afd, ocde)
  })()
  return { suite }
}

function cles(apd: ApdDeclaree, idx: Index, an: number, src: string): string {
  const t = idx.totaux.apd_declaree
  const ligne = t.lignes.find((l) => l[0] === an)
  const v = (c: string) => num(ligne?.[t.colonnes.indexOf(c)])
  const [dons, prets, equivalent] = [v('dons_verses_eur'), v('prets_verses_eur'), v('equivalent_don_eur')]
  // Remboursements reçus dans l'année sur des prêts d'aide : colonne « perçu » de la ligne « Prêt ».
  const ci = (c: string) => apd.par_annee.colonnes.indexOf(c)
  const pret = deLAnnee(apd.par_annee, an).find((l) => l[ci('type_de_flux')] === 'Aide Publique au Développement' && l[ci('type_de_financement')] === 'Prêt')
  const rembourse = num(pret?.[ci('percu_eur')])
  const statut = (x: number | null) => badgeStatut(x === null ? 'nonpub' : 'trace')
  return `<ul class="cles" aria-label="Chiffres clés de l’aide déclarée pour ${an}">
  <li class="cle-famille"><strong>${h(montant(equivalent))}</strong><span>d’aide déclarée pour ${an}, en équivalent-don : la mesure de l’OCDE depuis 2018</span>${statut(equivalent)}</li>
  <li><strong>${h(montant(dons))}</strong><span>de dons versés en ${an}, sans remboursement</span>${statut(dons)}</li>
  <li><strong>${h(montant(prets))}</strong><span>de prêts versés en ${an}, à rembourser${rembourse !== null ? ` ; la même année, ${h(montant(rembourse))} de prêts ont été remboursés` : ''}</span>${statut(prets)}</li>
</ul>
<p class="aide">Dons et prêts sont donnés à part et ne s’additionnent pas : un don n’est pas remboursé, un prêt l’est. ${h(majuscule(apd.definitions.equivalent_don ?? ''))}. Dans les tableaux, « ${NON_PUBLIE} » signale une case sans montant dans la source : le site n’y écrit pas 0.</p>
${source(src, `déclaration ${an}`)}`
}

function blocSur100(vues: VueCredits[], racines: (Racine | null)[]): string {
  const i = vues.findIndex((v, k) => v.vue === 'arbre' && racines[k])
  if (i < 0) return `<h2>Sur 100 € dépensés par l’État</h2>${absent('Budget de l’État non disponible.')}`
  const v = vues[i]
  const total = racines[i]!.md
  const an = anneeDe(v.millesime)
  const autres = vues.map((x, k) => ({ x, r: racines[k] })).filter((o, k) => k !== i && o.r)
  // Ce que tu verses : la part qui va à l'État, appliquée au prorata du budget (même méthode que l'écran « Budget de l'État »).
  const lignes = session.complet?.lignes ?? session.resultat?.prelevements.filter((l) => l.inclus_dans_total_paye) ?? []
  const etat = parAdministration(lignes).Etat ?? 0
  const perso =
    etat > 0
      ? `<p>Sur ce que tu verses à l’État (${h(eurLisible(etat))} par an, valeur centrale de ton calcul), environ <strong>${h(eurLisible((etat * v.mission.md) / total))}</strong> par an correspondent à cette mission, au prorata du budget de ${an}. ${badgeStatut('approche')}</p><p class="aide">Ce que tu verses n’est pas fléché vers une mission : le prorata donne un ordre de grandeur.</p>`
      : `<p class="aide">Pour voir ta part, <a href="${lien('/calcul')}">calcule ce que tu verses à partir de ton salaire</a>.</p>`
  return `<section class="carte carte-principale" data-cle aria-labelledby="titre-sur100">
<h2 id="titre-sur100">Sur 100 € dépensés par l’État</h2>
<p class="grand-chiffre">${surligne(sur100((v.mission.md / total) * 100))}</p>
<p class="sous-chiffre">sur 100 € dépensés par l’État en ${an} sont allés à la mission « ${h(v.mission.nom)} » : ${h(milliards(v.mission.md * 1e9))} sur ${h(milliards(total * 1e9))} (${h(periode(v))}). ${badgeStatut('trace')}</p>
${autres.map((o) => `<p>${h(majuscule(periode(o.x)))} : ${h(sur100((o.x.mission.md / o.r!.md) * 100))} sur 100 € (${h(milliards(o.x.mission.md * 1e9))} sur ${h(milliards(o.r!.md * 1e9))}).</p>`).join('')}
${perso}
<div class="tableau-defile"><table><caption>Les programmes de la mission, en milliards d’euros (crédits de paiement)</caption>
<thead><tr><th scope="col">Programme</th><th scope="col">Responsable</th>${vues.map((x) => `<th scope="col" class="nombre">${h(periode(x))}</th>`).join('')}<th scope="col" class="nombre">Sur 100 € (${an})</th></tr></thead>
<tbody>${v.programmes
    .map(
      (p) =>
        `<tr><th scope="row"><a href="${lien('/explorer/etat/detail', { m: 'execution2024', id: `${v.mission.id}/${p.numero}` })}">${h(p.numero)} « ${h(p.nom)} »</a></th><td>${h(RESPONSABLES[p.numero] ?? NON_PUBLIE)}</td>${vues
          .map((x) => {
            const q = x.programmes.find((y) => y.numero === p.numero)
            return td(q ? milliards(q.md * 1e9) : NON_PUBLIE)
          })
          .join('')}${td(sur100((p.md / total) * 100))}</tr>`,
    )
    .join('')}</tbody></table></div>
<p class="aide">Responsables : ${ancre(PAP_2026, 14)} et page 54. Le détail de chaque programme (actions, bénéficiaires) est dans le budget de l’État.</p>
${source(racines[i]!.source ?? '', vues.map(periode).join(', '))}
</section>`
}

function blocComparaison(idx: Index, apd: ApdDeclaree, vues: VueCredits[], racines: (Racine | null)[]): string {
  const t = idx.totaux.apd_declaree
  const eq = t.colonnes.indexOf('equivalent_don_eur')
  const lignes = vues
    .map((v) => {
      const a = anneeDe(v.millesime)
      const declare = num(t.lignes.find((l) => l[0] === a)?.[eq])
      const budget = v.mission.md * 1e9
      return `<tr><th scope="row">${a}</th><td class="nombre">${h(milliards(budget))} (${h(periode(v))}) ${badgeStatut('trace')}</td><td class="nombre">${declare !== null ? `${h(milliards(declare))} ${badgeStatut('trace')}` : badgeStatut('nonpub')}</td><td class="nombre">${declare !== null ? h(milliards(declare - budget)) : 'non calculable : un des deux montants manque'}</td></tr>`
    })
    .join('')
  const r = racines.find((x) => x?.source)
  return `<section aria-labelledby="titre-deux">
<h2 id="titre-deux">Déclaré à l’OCDE ou dépensé par l’État : deux montants</h2>
<p>La France déclare son aide au Comité d’aide au développement de l’OCDE. Le budget de l’État en porte une partie, dans la mission « Aide publique au développement ». Voici les deux montants côte à côte, pour les années où ils existent.</p>
<div class="tableau-defile"><table><caption>Crédits de la mission et aide déclarée (équivalent-don), en milliards d’euros</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Crédits de la mission (budget de l’État)</th><th scope="col" class="nombre">Aide déclarée à l’OCDE</th><th scope="col" class="nombre">Écart entre les deux</th></tr></thead>
<tbody>${lignes}</tbody></table></div>
<p class="avertissement">${h(idx.credits_budgetaires.lecture)}</p>
<p class="aide">Écart ${badgeCalcule('crédits de la mission moins aide déclarée à l’OCDE, même année, sans correction')}. Le site ne dit pas lequel des deux est le bon : ils ne mesurent pas la même chose.</p>
${source(`${r?.source ?? 'budget de l’État'} ; ${apd.source}`)}
</section>`
}

function blocCanaux(apd: ApdDeclaree, an: number, src: string): string {
  const canaux = deLAnnee(apd.par_canal, an).map((l) => ({ nom: String(l[1]), ...ventilation(apd, l, 2) }))
  const ci = (c: string) => apd.par_annee.colonnes.indexOf(c)
  const flux = deLAnnee(apd.par_annee, an)
  const types = [...new Set(flux.map((l) => String(l[ci('type_de_flux')])))]
  return `<section aria-labelledby="titre-canaux">
<h2 id="titre-canaux">Dons et prêts, aide bilatérale et multilatérale</h2>
<ul class="lignes" aria-label="Définitions">${(['bilateral', 'multilateral', 'don', 'pret'] as const).map((k) => citer(CITATIONS[k])).join('')}</ul>
${
  canaux.length
    ? `<div class="tableau-defile"><table><caption>Aide déclarée pour ${an} par canal, montants versés</caption>
<thead><tr><th scope="col">Canal</th><th scope="col" class="nombre">Dons</th><th scope="col" class="nombre">Prêts</th><th scope="col" class="nombre">Autres instruments</th></tr></thead>
<tbody>${canaux.map((c) => `<tr><th scope="row">${h(c.nom)}</th>${td(montant(c.dons))}${td(montant(c.prets))}${td(montant(c.autres))}</tr>`).join('')}</tbody></table></div>
<p class="aide">${h(apd.perimetre_ventilations)} Autres instruments : prises de participation, garanties, obligations, opérations sur la dette. ${badgeStatut('trace')}</p>`
    : absent(`Pas de ventilation par canal publiée pour ${an}.`)
}
<details class="carte"><summary>Tous les flux déclarés pour ${an}, par type de financement</summary>
${types
  .map(
    (t) => `<div class="tableau-defile"><table><caption>${h(t)} (${an})</caption>
<thead><tr><th scope="col">Type de financement</th><th scope="col" class="nombre">Versé</th><th scope="col" class="nombre">Équivalent-don</th><th scope="col" class="nombre">Reçu dans l’année</th></tr></thead>
<tbody>${flux
      .filter((l) => l[ci('type_de_flux')] === t)
      .map((l) => `<tr><th scope="row">${h(l[ci('type_de_financement')])}</th>${td(montant(l[ci('verse_eur')]))}${td(montant(l[ci('equivalent_don_eur')]))}${td(montant(l[ci('percu_eur')]))}</tr>`)
      .join('')}</tbody></table></div>`,
  )
  .join('')}
<p class="aide">Reçu dans l’année : ${h(apd.definitions.percu ?? '')}. Depuis les déclarations 2023, la source classe à part les instruments du secteur privé (prêts, participations et garanties à des entreprises) : ils figurent dans ce détail, pas dans les tableaux par canal, région et organisme. ${badgeStatut('trace')}</p>
${regleOrdre(REGLE_ORDRE_SOURCE)}
</details>
${source(src, `déclaration ${an}`)}
</section>`
}

function blocRegions(apd: ApdDeclaree, an: number, src: string, choix: Pays | null): string {
  const regions = parRegion(apd, an)
  const pays = [...apd.pays].sort((a, b) => a.nom_tri.localeCompare(b.nom_tri, 'fr'))
  return `<section aria-labelledby="titre-regions">
<h2 id="titre-regions">Où va l’aide : régions et pays</h2>
${
  regions.length
    ? `<div class="tableau-defile"><table><caption>Aide déclarée pour ${an} par région, montants versés</caption>
<thead><tr><th scope="col">Région</th><th scope="col" class="nombre">Dons</th><th scope="col" class="nombre">Prêts</th><th scope="col" class="nombre">Autres instruments</th></tr></thead>
<tbody>${regions.map((r) => `<tr><th scope="row">${h(r.nom)}</th>${td(montant(r.dons))}${td(montant(r.prets))}${td(montant(r.autres))}</tr>`).join('')}</tbody>
<tfoot><tr><th scope="row">Ensemble</th>${td(montant(somme(regions.map((r) => r.dons))))}${td(montant(somme(regions.map((r) => r.prets))))}${td(montant(somme(regions.map((r) => r.autres))))}</tr></tfoot></table></div>
${regleOrdre(REGLE_ORDRE_REGIONS)}
<p class="aide">Chaque région additionne, colonne par colonne, les pays et regroupements régionaux publiés par la Direction générale du Trésor. Les lignes régionales et « non spécifié » de la source restent des regroupements : elles ne sont pas réparties entre pays. ${badgeStatut('trace')}</p>`
    : absent(`Pas de ventilation par pays publiée pour ${an}.`)
}
<form id="aide-dev-pays-form">
${listeRecherche({ id: 'aide-dev-choix-pays', etiquette: 'Voir un pays ou un regroupement, année par année', options: [], optionsHtml: `<option value="">Choisir</option>${pays.map((p) => `<option value="${h(p.code)}"${p.code === choix?.code ? ' selected' : ''}>${h(p.nom)}</option>`).join('')}` })}
<button type="submit" class="bouton">Afficher</button>
</form>
<div id="aide-dev-pays" aria-live="polite">${choix ? '<p class="chargement">Chargement…</p>' : ''}</div>
${source(src, `déclaration ${an}`)}
</section>`
}

function fichePays(p: Pays, apd: ApdDeclaree, afd: Afd | null, ocde: Ocde | null): string {
  const lignes = apd.par_pays.lignes.filter((l) => l[1] === p.code).sort((a, b) => Number(a[0]) - Number(b[0]))
  const tete = `<h3>${h(p.nom)}</h3><p>Région : ${h(HORS_REGIONS[p.region] ?? p.region)}. Catégorie dans la liste des pays qui peuvent recevoir l’aide : ${h(CATEGORIES[p.categorie_cad] ?? p.categorie_cad)}.</p>`
  const tDgt = lignes.length
    ? `<div class="tableau-defile"><table><caption>${h(p.nom)} : aide déclarée par la France, montants versés</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Dons</th><th scope="col" class="nombre">Prêts</th><th scope="col" class="nombre">Reçu dans l’année</th></tr></thead>
<tbody>${lignes
        .map((l) => {
          const v = ventilation(apd, l, 2)
          return `<tr><th scope="row">${h(l[0])}</th>${td(montant(v.dons))}${td(montant(v.prets))}${td(montant(v.percu))}</tr>`
        })
        .join('')}</tbody></table></div><p class="aide">Montants publiés par la Direction générale du Trésor. ${badgeStatut('trace')}</p>${source(apd.source, apd.millesime)}`
    : absent('Aucune ligne publiée par la Direction générale du Trésor pour ce pays.')
  let tAfd = ''
  if (afd) {
    const c = (n: string) => 3 + afd.colonnes_montants.indexOf(n)
    const l2 = afd.par_pays.lignes.filter((l) => l[1] === p.code && l[2] === 'apd').sort((a, b) => Number(a[0]) - Number(b[0]))
    tAfd = l2.length
      ? `<div class="tableau-defile"><table><caption>${h(p.nom)} : concours d’aide au développement publiés par l’Agence française de développement, montants versés</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Dons</th><th scope="col" class="nombre">Prêts</th></tr></thead>
<tbody>${l2.map((l) => `<tr><th scope="row">${h(l[0])}${afd.annees_partielles.includes(Number(l[0])) ? ' (année incomplète)' : ''}</th>${td(montant(l[c('dons_verses_eur')]))}${td(montant(l[c('prets_verses_eur')]))}</tr>`).join('')}</tbody></table></div>
<p class="aide">${h(afd.limites[0] ?? '')} ${badgeStatut('trace')}</p>${source(afd.source)}`
      : `<p class="aide">Aucun concours d’aide au développement publié par l’Agence française de développement pour ce pays.</p>`
  }
  let tOcde = ''
  if (ocde) {
    const vp = ocde.versements_par_pays
    const code = CODE_OCDE[p.code] ?? p.code
    const c = (n: string) => vp.colonnes.indexOf(n)
    const l3 = vp.lignes.filter((l) => l[1] === code).sort((a, b) => Number(a[0]) - Number(b[0]))
    tOcde = l3.length
      ? `<div class="tableau-defile"><table><caption>${h(p.nom)} : versements publiés par l’OCDE, en millions de dollars courants</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Dons</th><th scope="col" class="nombre">Prêts (avant remboursements)</th><th scope="col" class="nombre">Part des contributions multilatérales attribuée au pays (estimation de l’OCDE)</th></tr></thead>
<tbody>${l3.map((l) => `<tr><th scope="row">${h(l[0])}</th>${td(dollars(l[c('dons_musd')]))}${td(dollars(l[c('prets_bruts_musd')]))}${td(dollars(l[c('multilaterale_imputee_musd')]))}</tr>`).join('')}</tbody></table></div>
<p class="aide">${h(vp.note)} Montants en dollars : ils ne se comparent pas directement aux montants en euros. Dons et prêts : ${badgeStatut('trace')} ; dernière colonne : ${badgeStatut('approche')}</p>${source(ocde.source)}`
      : ''
  }
  return `${tete}${tDgt}${tAfd}${tOcde}`
}

function blocOrganismes(apd: ApdDeclaree, idx: Index, an: number, src: string): string {
  const lignes = deLAnnee(apd.par_agence, an).map((l) => ({ nom: ORGANISMES[String(l[1])] ?? String(l[1]), ...ventilation(apd, l, 2) }))
  return `<section aria-labelledby="titre-organismes">
<h2 id="titre-organismes">Qui verse l’aide</h2>
<p>La déclaration détaille l’aide par organisme : ministères, Agence française de développement, collectivités locales, organismes de recherche.</p>
${
  lignes.length
    ? `<div class="tableau-defile"><table><caption>Aide déclarée pour ${an} par organisme, montants versés</caption>
<thead><tr><th scope="col">Organisme</th><th scope="col" class="nombre">Dons</th><th scope="col" class="nombre">Prêts</th><th scope="col" class="nombre">Autres instruments</th></tr></thead>
<tbody>${lignes.map((o) => `<tr><th scope="row">${h(o.nom)}</th>${td(montant(o.dons))}${td(montant(o.prets))}${td(montant(o.autres))}</tr>`).join('')}</tbody></table></div>
${regleOrdre(REGLE_ORDRE_SOURCE)}
<p class="aide">Libellés des organismes tels que publiés par la Direction générale du Trésor, sigles écrits en toutes lettres. ${badgeStatut('trace')}</p>`
    : absent(`Pas de ventilation par organisme publiée pour ${an}.`)
}
${source(src, `déclaration ${an}`)}
<h3>Le groupe Agence française de développement</h3>
<p>Le groupe réunit l’Agence française de développement (AFD), Proparco, sa filiale pour le secteur privé, et Expertise France, pour la coopération technique. Chacun publie ses propres données, sur un périmètre différent de la déclaration : elles ne s’ajoutent pas aux montants ci-dessus.</p>
<h4>Comment l’AFD finance ses prêts : ce qu’écrivent les sources</h4>
<ul class="lignes" aria-label="Citations sur le financement des prêts de l’AFD">${citer(CITATIONS.emprunt)}${citer(CITATIONS.bonification)}${citer(CITATIONS.fondsPropres)}</ul>
<p class="aide">Phrases citées telles quelles, avec leur source. Les crédits des programmes 110 et 365 figurent dans le tableau « Sur 100 € dépensés par l’État ».</p>
${blocAfd(idx)}
<div id="aide-dev-groupe"><p class="chargement">Chargement des données de Proparco et d’Expertise France…</p></div>
</section>`
}

function blocAfd(idx: Index): string {
  const t = idx.totaux.afd
  const c = (n: string) => t.colonnes.indexOf(n)
  const src = idx.sources.find((s) => s.id === 'apd_afd_iati')
  const lecture = idx.ecarts.find((e) => e.source === 'afd_iati')?.lecture
  return `<details class="carte"><summary>Agence française de développement : dons et prêts publiés, par année</summary>
<div class="tableau-defile"><table><caption>Concours d’aide au développement publiés par l’Agence française de développement, en euros</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Dons engagés</th><th scope="col" class="nombre">Prêts engagés</th><th scope="col" class="nombre">Dons versés</th><th scope="col" class="nombre">Prêts versés</th></tr></thead>
<tbody>${t.lignes
    .map(
      (l) =>
        `<tr><th scope="row">${h(l[0])}${t.annees_partielles.includes(Number(l[0])) ? ' (année incomplète)' : ''}</th>${td(montant(l[c('dons_engages_eur')]))}${td(montant(l[c('prets_engages_eur')]))}${td(montant(l[c('dons_verses_eur')]))}${td(montant(l[c('prets_verses_eur')]))}</tr>`,
    )
    .join('')}</tbody></table></div>
<p class="aide">Publication au standard international de l’aide (IATI). ${lecture ? h(lecture) : ''} ${badgeStatut('trace')}</p>
${src ? source(`${src.nom}, licence : ${src.licence}, collecté le ${src.collecte_le}`) : ''}
</details>`
}

function blocProparco(p: Proparco): string {
  const ans = [...new Set(p.par_annee.lignes.map((l) => Number(l[0])))].sort((a, b) => a - b).slice(-4)
  const instr = [...new Set(p.par_annee.lignes.filter((l) => ans.includes(Number(l[0]))).map((l) => String(l[1])))].sort((a, b) => (INSTRUMENTS[a] ?? a).localeCompare(INSTRUMENTS[b] ?? b, 'fr'))
  const enCoursAn = anneeDe(p.collecte_le)
  const cel = (a: number, i: string) => {
    const l = p.par_annee.lignes.find((x) => x[0] === a && x[1] === i)
    return l ? `${montant(l[3])} (${nf0.format(Number(l[2]))} financement${Number(l[2]) > 1 ? 's' : ''})` : 'aucun'
  }
  return `<details class="carte"><summary>Proparco : financements signés, par instrument</summary>
<div class="tableau-defile"><table><caption>Financements signés par Proparco, en euros</caption>
<thead><tr><th scope="col">Instrument</th>${ans.map((a) => `<th scope="col" class="nombre">${a}${a === enCoursAn ? ' (année en cours)' : ''}</th>`).join('')}</tr></thead>
<tbody>${instr.map((i) => `<tr><th scope="row">${h(INSTRUMENTS[i] ?? i)}</th>${ans.map((a) => td(cel(a, i))).join('')}</tr>`).join('')}</tbody></table></div>
<p class="aide">${h(majuscule(p.definitions.garantie ?? ''))}. ${h(p.limites.find((l) => l.startsWith('Les instruments')) ?? '')} ${badgeStatut('trace')}</p>
${regleOrdre('Instruments par ordre alphabétique ; aucun classement par montant.')}
${source(p.source, p.millesime)}
</details>`
}

function blocExpertise(e: ExpertiseFrance): string {
  const c = (n: string) => e.par_bailleur.colonnes.indexOf(n)
  const experts = e.ecartes.find((x) => typeof x.montant_initial_maximal_eur === 'number')
  return `<details class="carte"><summary>Expertise France : contrats par organisme qui finance le projet</summary>
<div class="tableau-defile"><table><caption>Contrats de plus de 15 000 euros conclus par Expertise France (${h(e.millesime)})</caption>
<thead><tr><th scope="col">Organisme qui finance</th><th scope="col" class="nombre">Contrats</th><th scope="col" class="nombre">Montant initial maximal</th><th scope="col" class="nombre">Accords-cadres</th><th scope="col" class="nombre">Plafonds des accords-cadres</th></tr></thead>
<tbody>${e.par_bailleur.lignes
    .map((l) => `<tr><th scope="row">${h(BAILLEURS[String(l[0])] ?? l[0])}</th>${td(nf0.format(Number(l[c('contrats')])))}${td(montant(l[c('montant_initial_maximal_eur')]))}${td(nf0.format(Number(l[c('accords_cadres')])))}${td(montant(l[c('plafonds_accords_cadres_eur')]))}</tr>`)
    .join('')}</tbody></table></div>
<p class="aide">Montant initial maximal : un plafond fixé au contrat, pas une dépense constatée. ${h(majuscule(e.definitions.accord_cadre ?? ''))}.${experts ? ` Les contrats d’experts individuels (personnes physiques) ne sont pas ventilés : ${h(nf0.format(experts.contrats ?? 0))} contrats, ${h(montant(experts.montant_initial_maximal_eur))} au total.` : ''} ${badgeStatut('trace')}</p>
${regleOrdre(REGLE_ORDRE_SOURCE)}
${source(e.source, e.millesime)}
</details>`
}

function blocEcarts(idx: Index, an: number): string {
  const ecarts = idx.ecarts.filter((e) => e.annee === an)
  const val = (e: Ecart, x: number | null) => (x === null ? NON_PUBLIE : e.unite === 'euros' ? eurLisible(x) : dollars(x))
  return `<section aria-labelledby="titre-ecarts">
<h2 id="titre-ecarts">Écarts entre sources pour ${an}</h2>
<p>${h(idx.ecarts_note)}</p>
${
  ecarts.length
    ? `<div class="tableau-defile"><table><caption>Un même objet mesuré par deux sources (${an})</caption>
<thead><tr><th scope="col">Objet</th><th scope="col">Première source</th><th scope="col" class="nombre">Montant</th><th scope="col">Seconde source</th><th scope="col" class="nombre">Montant</th><th scope="col" class="nombre">Écart</th><th scope="col">Unité</th></tr></thead>
<tbody>${ecarts
        .map(
          (e) =>
            `<tr><th scope="row">${h(COMPARAISONS[e.comparaison] ?? e.comparaison)}</th><td>${h(ECART_SOURCES[e.source] ?? e.source)}</td>${td(val(e, e.montant))}<td>${h(ECART_SOURCES[e.autre_source] ?? e.autre_source)}</td>${td(val(e, e.autre_montant))}${td(`${val(e, e.ecart)}${e.ecart_pct !== null ? ` (${pct(e.ecart_pct)})` : ''}`)}<td>${h(e.unite)}</td></tr>`,
        )
        .join('')}</tbody></table></div>
<ul class="aide">${[...new Set(ecarts.map((e) => e.lecture))].map((l) => `<li>${h(l)}</li>`).join('')}</ul>
<p class="aide">Les deux montants sont publiés ; l’écart est donné tel quel, sans correction ni choix entre les sources. ${badgeStatut('trace')}</p>`
    : absent(`Aucune comparaison publiée pour ${an}.`)
}
${source(idx.sources.filter((s) => ['etat_aide_publique_developpement', 'apd_afd_iati', 'apd_ocde_dac2a'].includes(s.id)).map((s) => s.nom).join(' ; '))}
</section>`
}

function blocSources(idx: Index): string {
  return `<section aria-labelledby="titre-sources">
<h2 id="titre-sources">Sources et limites</h2>
<ul>${idx.sources.map((s) => `<li><a href="${h(s.url)}" rel="noopener noreferrer">${h(s.nom)}</a> : ${h(s.producteur)} ; licence : ${h(s.licence)} ; collecté le ${h(s.collecte_le)}.</li>`).join('')}</ul>
<p>Textes cités sur cette page :</p>
<ul><li>${ancre(AFD_PRET)}</li><li>${ancre(PAP_2026)}</li><li>${ancre(GLOSSAIRE)}</li></ul>
${idx.sources_inaccessibles.length ? `<p>Sources inaccessibles :</p><ul>${idx.sources_inaccessibles.map((s) => `<li>${h(s.source)} : ${h(s.constat)}</li>`).join('')}</ul>` : ''}
<p class="avertissement">${h(idx.regle)}</p>
<ul class="aide">${idx.limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul>
</section>`
}

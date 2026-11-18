// Les marchés publics de tous les acheteurs (site/data/marches/, pipeline/marches.py), 2019 à 2025.
// Montants notifiés hors taxes, jamais des paiements. Les lignes écartées (marques du producteur du jeu, séries de
// montants identiques) sont comptées et montrées à part, jamais ajoutées aux totaux. Seules des personnes morales
// sont nommées ; entrepreneurs individuels et unités non diffusibles sont agrégés.
import { billet, listeParts, tableauBillet, type Famille, type Part } from '../composants/billet'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { badgeStatut, barres, entier, eurLisible, h, pct, source, sur100, surligne } from '../util'
import { enCours } from './dette'

type Serie = (number | null)[]
interface Montant {
  montant_eur: number
}
interface Confidentialite {
  montant_eur: number
  part_pct: number | null
  dont_personnes_physiques_eur: number
  dont_diffusion_partielle_eur: number
  dont_siren_introuvable_eur: number
}
interface Entete {
  millesime: string
  source: string
  unite: string
  collecte_le: string
  annees: number[]
  ordre?: string
  note?: string
}
interface Regle {
  id: string
  regle: string
  lignes: number
  montant_eur: number | null
}
interface Serie8 {
  annee: number
  siren: string | null
  denomination: string | null
  categorie: string
  marches: number
  montant_unitaire_eur: number
  montant_declare_eur: number
}
interface Gros {
  annee: number
  acheteur: string | null
  categorie: string
  type: string
  division_cpv: string
  montant_eur: number
}
interface Index extends Entete {
  version_source?: string | null
  perimetre: string
  methode: string[]
  limites: string[]
  regle_personnes: string
  regles_qualite: Regle[]
  anomalies_source: { note: string; aberrant: { lignes: number; montant_declare_eur: number }; suspect: { lignes: number; montant_declare_eur: number } }
  totaux: { total_retenu_eur: number; marches_retenus: number; acheteurs: number; agrege_confidentialite: Confidentialite }
  series_repetees?: {
    regle: string
    pourquoi: string
    seuil_eur: number
    marches_minimum: number
    par_annee: { annee: number; series: number; marches: number; lignes: number; montant_declare_eur: number }[]
    principales: Serie8[]
    ordre: string
  }
  plus_gros_marches?: { note: string; marches: Gros[]; ordre: string }
  repere_oecp?: {
    annee: number
    montant_eur: number | null
    nombre_marches: number
    producteur: string
    publication: string
    perimetre: string
    montant_ici_eur: number | null
    marches_ici: number | null
    lecture_ecart: string
    page_consultee: { titre: string; url: string } | null
  }
  centrales_achat?: { note: string }
  sources_inaccessibles?: { source: string; motif: string }[]
}
interface Ecartes {
  lignes: number
  montant_eur: number | null
}
interface Annee {
  annee: number
  marches: number
  lignes: number
  acheteurs: number
  total_eur: number | null
  agrege_confidentialite?: Confidentialite
  par_type?: ({ type: string; marches: number } & Montant)[]
  ecartes?: Record<string, Ecartes>
}
interface Categorie {
  categorie: string
  definition: string
  par_annee: ({ annee: number; marches: number } & Montant)[]
}
interface Region {
  region: string
  nom: string
  total_eur: number
  montants_eur: Serie
}
interface Secteur {
  division: string
  libelle: string
  total_eur: number
  montants_eur: Serie
  marches_par_annee: number[]
}
interface Titulaire {
  siren: string
  denomination: string
  marches: number
  montant_eur: number
}
interface Titulaires extends Entete {
  titulaires: { siren: string; denomination: string; marches: number; total_eur: number; montants_eur: Serie }[]
  autres_personnes_morales: { nombre: number; montant_eur: number }
  agrege_confidentialite: Confidentialite
  par_annee: { annee: number; titulaires: Titulaire[]; autres_personnes_morales: { nombre: number; montant_eur: number }; agrege_confidentialite: Confidentialite | null }[]
  regle_personnes: string
}
interface Acheteurs extends Entete {
  acheteurs: { siren: string; denomination: string; categorie: string; marches: number; departements: number; total_eur: number; montants_eur: Serie; centrale_achat: boolean }[]
  autres_acheteurs_nommes: { nombre: number; montant_eur: number }
  acheteurs_non_nommes: { nombre: number; marches: number; montant_eur: number }
}

const CHEMIN = '/beneficiaires/marches'
/** Couleur fixe de chaque type d'achat (aucune n'est mise en avant). */
const FAMILLE_TYPE: Record<string, Famille> = { Travaux: 'collectivites', Services: 'operateurs', Fournitures: 'niches', 'Non catégorisé': 'papier' }
const nbsp = (s: string) => s.replace(/\s+/g, ' ')
const md = (x: number | null | undefined) => (x === null || x === undefined ? 'non publié' : nbsp(eurLisible(x)))
const auNom = (x: string | null) => x ?? 'acheteur non nommé (règle des personnes)'
/** Catégories d'acheteur dont le libellé publié est un sigle : développé pour le public. */
const CATEGORIES_CLAIRES: Record<string, string> = { EPIC: 'Établissement public industriel et commercial' }
const categorie = (c: string) => CATEGORIES_CLAIRES[c] ?? c

/** Tableau simple : légende, en-têtes (la première colonne est un en-tête de ligne), lignes. */
function tableau(legende: string, entetes: string[], lignes: string[][], nombres: number[] = []): string {
  const cls = (i: number) => (nombres.includes(i) ? ' class="nombre"' : '')
  return `<div class="tableau-defile"><table><caption>${h(legende)}</caption><thead><tr>${entetes
    .map((e, i) => `<th scope="col"${cls(i)}>${h(e)}</th>`)
    .join('')}</tr></thead><tbody>${lignes
    .map((l) => `<tr>${l.map((c, i) => (i === 0 ? `<th scope="row">${c}</th>` : `<td${cls(i)}>${c}</td>`)).join('')}</tr>`)
    .join('')}</tbody></table></div>`
}

const ordre = (texte?: string) => (texte ? `<p class="aide" data-regle-ordre>${h(texte)}</p>` : '')

/**
 * Texte des données rendu lisible pour le public : noms de champs techniques retirés, sigles développés
 * (le site n'affiche jamais un sigle seul).
 */
export function clair(t: string): string {
  return t
    .replace(/,?\s*dans l'ordre de `regles_qualite`/g, ", dans l'ordre du tableau des règles")
    .replace(/\s*\([^()]*`[^()]*\)/g, '')
    .replace(/`donneesActuelles`/g, '« données actuelles »')
    .replace(/`[^`]*`/g, '')
    .replace(/\s*\((?:OECP|DECP)\)/g, '')
    .replace(/\bDECP\b/g, 'données essentielles de la commande publique')
    .replace(/\bl'OECP\b/g, 'l’Observatoire économique de la commande publique')
    .replace(/\bOECP\b/g, 'Observatoire économique de la commande publique')
    .replace(/\bSIRENE\b/g, 'Sirene (répertoire des entreprises)')
    .replace(/\bSIRET\b/g, 'numéro SIRET d’établissement')
    .replace(/(?<!\()\bCPV\b/g, 'de la nomenclature des marchés (CPV)')
    .replace(/\bHT\b/g, 'hors taxes')
    .replace(/\bUGAP\b/g, 'Union des groupements d’achats publics')
    .replace(/\s+([,.)])/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Libellés des règles de qualité, en clair, par identifiant (repli : le texte publié, nettoyé). */
const REGLES_CLAIRES: Record<string, string> = {
  versions_anterieures: 'Anciennes versions d’un marché modifié : seule la dernière version publiée est lue',
  doublons_uid_titulaire: 'Doublons : même marché, même titulaire',
  nature_hors_champ: 'Concessions et délégations de service public : hors du champ des marchés',
  date_absente: 'Date de notification absente',
  date_impossible: 'Date de notification impossible (avant 2000 ou après la collecte)',
  hors_periode: 'Marché notifié avant 2019 ou après 2025',
  montant_non_renseigne: 'Montant non renseigné (jamais compté comme 0)',
  montant_aberrant: 'Montant marqué « aberrant » par le producteur des données',
  montant_suspect: 'Montant marqué « suspect » par le producteur des données',
  montant_negatif: 'Montant négatif',
  montant_serie_repetee: 'Série de montants identiques (règle du site, détaillée plus haut)',
  siret_titulaire_invalide: 'Identifiant du titulaire qui n’est pas un numéro SIRET d’établissement valide (identifiant étranger, numéro de TVA, valeur tronquée ou vide)',
}

const REGLE_PERSONNES =
  'Un acheteur ou un titulaire n’est nommé que s’il est une personne morale (entreprise, association, collectivité, établissement public) d’après le répertoire des entreprises Sirene, et si sa fiche y est diffusée en entier ; le nom affiché est celui du répertoire. Les entrepreneurs individuels et les fiches à diffusion partielle sont additionnés à part, jamais nommés.'

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const [idx, ans, cats, regs, secs, tits, achs] = await Promise.all([
    chargerSiPresent<Index>('marches/index.json'),
    chargerSiPresent<Entete & { par_annee: Annee[]; note: string }>('marches/annees.json'),
    chargerSiPresent<Entete & { categories: Categorie[] }>('marches/categories.json'),
    chargerSiPresent<Entete & { regions: Region[]; non_localise: { total_eur: number; montants_eur: Serie } | null }>('marches/regions.json'),
    chargerSiPresent<Entete & { secteurs: Secteur[]; nomenclature: string }>('marches/secteurs.json'),
    chargerSiPresent<Titulaires>('marches/titulaires.json'),
    chargerSiPresent<Acheteurs>('marches/acheteurs.json'),
  ])
  if (!idx || !ans) {
    cible.innerHTML = `${enCours('Les marchés publics', 'Montants des marchés publics par année, par acheteur, par type, par secteur et par région, et principaux titulaires.')}
<p class="liens-sortie"><a href="${lien('/beneficiaires', { onglet: 'marches' })}">Les marchés des services de l’État</a></p>`
    return
  }
  const annees = ans.par_annee.filter((p) => p.total_eur !== null).map((p) => p.annee)
  const demandee = Number(params.get('a'))
  const a = annees.includes(demandee) ? demandee : annees[annees.length - 1]
  const i = idx.annees.indexOf(a)
  const an = ans.par_annee.find((p) => p.annee === a)!
  const total = an.total_eur ?? 0
  // Source complète une fois (méthode), forme courte sous chaque section.
  const version = idx.version_source ?? idx.collecte_le
  const src = (_texte?: string) =>
    source('Données essentielles de la commande publique consolidées, data.gouv.fr (Licence Ouverte 2.0) ; répertoire des entreprises Sirene, Insee', `version du ${version}, marchés notifiés de 2019 à 2025`)
  const statutTrace = badgeStatut('trace')

  // --- Sur 100 € : répartition par type ---------------------------------------------------------------------------------
  const types = (an.par_type ?? []).filter((t) => t.montant_eur > 0)
  const parts: Part[] = types.map((t) => {
    const v = total > 0 ? (t.montant_eur / total) * 100 : 0
    return { nom: t.type, valeur: v, texte: sur100(v), famille: FAMILLE_TYPE[t.type] ?? 'papier', detail: `${md(t.montant_eur)}, ${entier(t.marches)} marchés` }
  })

  // --- Année par année ----------------------------------------------------------------------------------------------------
  const sr = idx.series_repetees
  const ligneAnnee = (p: Annee) => {
    const e = p.ecartes ?? {}
    const prod = (e.montant_aberrant?.montant_eur ?? 0) + (e.montant_suspect?.montant_eur ?? 0)
    const nProd = (e.montant_aberrant?.lignes ?? 0) + (e.montant_suspect?.lignes ?? 0)
    const s = e.montant_serie_repetee
    return [
      p.annee === a ? `<a href="${lien(CHEMIN, { a: p.annee })}" aria-current="true">${p.annee}</a>` : `<a href="${lien(CHEMIN, { a: p.annee })}">${p.annee}</a>`,
      h(md(p.total_eur)),
      h(entier(p.marches)),
      `${h(md(prod))}<br /><span class="aide">${h(entier(nProd))} lignes</span>`,
      s ? `${h(md(s.montant_eur))}<br /><span class="aide">${h(entier(s.lignes))} lignes</span>` : 'non calculé',
    ]
  }
  const plusSerie = sr ? [...sr.par_annee].sort((x, y) => y.montant_declare_eur - x.montant_declare_eur || x.annee - y.annee)[0] : undefined
  const premiere = sr?.principales.find((s) => s.annee === plusSerie?.annee)
  const retenuSerie = plusSerie ? ans.par_annee.find((p) => p.annee === plusSerie.annee) : undefined

  const blocSeries = sr
    ? `<h3>Règle du site : les séries de montants identiques</h3>
<p>${h(clair(sr.regle))}</p>
<p>${h(clair(sr.pourquoi))}</p>
${tableau(
  'Séries écartées des totaux, par année (montants déclarés)',
  ['Année', 'Séries', 'Marchés', 'Lignes', 'Montant déclaré écarté'],
  sr.par_annee.map((p) => [String(p.annee), h(entier(p.series)), h(entier(p.marches)), h(entier(p.lignes)), h(md(p.montant_declare_eur))]),
  [1, 2, 3, 4],
)}
<details><summary>Les ${h(String(sr.principales.length))} plus grandes séries écartées</summary>
${tableau(
  'Plus grandes séries de montants identiques écartées des totaux',
  ['Année', 'Acheteur', 'Marchés', 'Montant de chaque marché', 'Montant déclaré écarté'],
  sr.principales.map((s) => [String(s.annee), `${h(auNom(s.denomination))}<br /><span class="aide">${h(categorie(s.categorie))}</span>`, h(entier(s.marches)), h(md(s.montant_unitaire_eur)), h(md(s.montant_declare_eur))]),
  [2, 3, 4],
)}${ordre(sr.ordre)}</details>`
    : ''

  const gros = idx.plus_gros_marches
  const blocGros = gros
    ? `<h3>Les plus gros montants conservés</h3>
<p>${h(clair(gros.note))}</p>
<details><summary>Les ${h(String(gros.marches.length))} plus gros montants unitaires retenus</summary>
${tableau(
  'Plus gros montants unitaires retenus dans les totaux, 2019 à 2025',
  ['Année', 'Acheteur', 'Type', 'Montant notifié'],
  gros.marches.map((g) => [String(g.annee), `${h(auNom(g.acheteur))}<br /><span class="aide">${h(categorie(g.categorie))}</span>`, h(g.type), h(md(g.montant_eur))]),
  [3],
)}${ordre(gros.ordre)}</details>`
    : ''

  // --- Par acheteur ----------------------------------------------------------------------------------------------------
  const catAn = (cats?.categories ?? [])
    .map((c) => ({ c, v: c.par_annee.find((p) => p.annee === a) }))
    .filter((x): x is { c: Categorie; v: { annee: number; marches: number; montant_eur: number } } => !!x.v)
    .sort((x, y) => y.v.montant_eur - x.v.montant_eur || x.c.categorie.localeCompare(y.c.categorie, 'fr'))
  const blocCategories = catAn.length
    ? `<h3>Par type d’acheteur, en ${a}</h3>
${barres(
  catAn.map(({ c, v }) => ({ nom: categorie(c.categorie), valeur: v.montant_eur, texte: md(v.montant_eur), detail: `${entier(v.marches)} marchés · ${sur100(total > 0 ? (v.montant_eur / total) * 100 : 0)} sur 100 €` })),
  undefined,
  `Montants notifiés en ${a} par type d’acheteur`,
)}<p class="aide" data-regle-ordre>Types d’acheteur par montant décroissant ; l’ordre ne porte aucune appréciation.</p>${src(cats!.source)}`
    : ''
  const blocAcheteurs = achs
    ? `<h3>Principaux acheteurs, de 2019 à 2025</h3>
${tableau(
  `Les 20 premiers acheteurs nommés, tous départements réunis (montant ${a} et total 2019 à 2025)`,
  ['Acheteur', `En ${a}`, '2019 à 2025', 'Marchés'],
  achs.acheteurs.slice(0, 20).map((x) => [
    `${h(x.denomination)}<br /><span class="aide">${h(categorie(x.categorie))}${x.centrale_achat ? ' · centrale d’achat, voir la note' : ''}</span>`,
    h(md(x.montants_eur[i])),
    h(md(x.total_eur)),
    h(entier(x.marches)),
  ]),
  [1, 2, 3],
)}
<ul><li>${h(entier(achs.autres_acheteurs_nommes.nombre))} autres acheteurs nommés : ${h(md(achs.autres_acheteurs_nommes.montant_eur))} sur 2019 à 2025.</li>
<li>${h(entier(achs.acheteurs_non_nommes.nombre))} acheteurs non nommés (catégorie juridique d’une personne physique, diffusion partielle ou absents du répertoire des entreprises) : ${h(md(achs.acheteurs_non_nommes.montant_eur))}.</li></ul>
${idx.centrales_achat ? `<p class="avertissement">${h(clair(idx.centrales_achat.note))}</p>` : ''}${ordre(achs.ordre)}${src(achs.source)}`
    : ''

  // --- Par secteur ------------------------------------------------------------------------------------------------------
  const secAn = (secs?.secteurs ?? [])
    .map((s) => ({ s, v: s.montants_eur[i], n: s.marches_par_annee[i] ?? 0 }))
    .filter((x): x is { s: Secteur; v: number; n: number } => typeof x.v === 'number' && x.v > 0)
    .sort((x, y) => y.v - x.v || x.s.division.localeCompare(y.s.division))
  const blocSecteurs = secs
    ? `<h2>Par secteur, en ${a}</h2>
<p>Le secteur est la division du vocabulaire commun des marchés publics (nomenclature européenne dite CPV) choisie par l’acheteur pour le marché.</p>
${barres(
  secAn.slice(0, 10).map(({ s, v, n }) => ({ nom: s.libelle, valeur: v, texte: md(v), detail: `${entier(n)} marchés · ${sur100(total > 0 ? (v / total) * 100 : 0)} sur 100 €` })),
  undefined,
  `Les 10 premiers secteurs en ${a}`,
)}
<details><summary>Les ${h(String(secAn.length))} secteurs de ${a}</summary>
${tableau(
  `Montants notifiés en ${a} par secteur (division de la nomenclature)`,
  ['Secteur', 'Division', 'Marchés', `Montant ${a}`],
  secAn.map(({ s, v, n }) => [h(s.libelle), h(s.division), h(entier(n)), h(md(v))]),
  [2, 3],
)}<p class="aide">${h(clair(secs.nomenclature))}</p></details>
<p class="aide" data-regle-ordre>Secteurs par montant décroissant ; l’ordre ne porte aucune appréciation.</p>${src(secs.source)}`
    : ''

  // --- Par région -------------------------------------------------------------------------------------------------------
  const blocRegions = regs
    ? `<h2>Par région de l’acheteur, en ${a}</h2>
<p>La région est celle de l’établissement acheteur, pas celle du chantier ni de l’entreprise titulaire.</p>
${tableau(
  `Montants notifiés par région de l’acheteur (${a} et total 2019 à 2025)`,
  ['Région', `En ${a}`, '2019 à 2025'],
  [
    ...regs.regions.map((r) => [h(r.nom), h(md(r.montants_eur[i])), h(md(r.total_eur))]),
    ...(regs.non_localise ? [['Département de l’acheteur absent de la source', h(md(regs.non_localise.montants_eur[i])), h(md(regs.non_localise.total_eur))]] : []),
  ],
  [1, 2],
)}${ordre(regs.ordre)}${src(regs.source)}`
    : ''

  // --- Principaux titulaires ------------------------------------------------------------------------------------------------
  const tAn = tits?.par_annee.find((p) => p.annee === a)
  const conf = tAn?.agrege_confidentialite
  const blocTitulaires =
    tits && tAn
      ? `<h2>Principaux titulaires, en ${a}</h2>
<p>Le titulaire est l’entreprise ou l’organisme qui exécute le marché. Seules les personnes morales sont nommées.</p>
${tableau(
  `Les ${tAn.titulaires.length} premiers titulaires nommés en ${a} (personnes morales)`,
  ['Titulaire', 'Marchés', `Montant ${a}`],
  tAn.titulaires.map((t) => [h(t.denomination), h(entier(t.marches)), h(md(t.montant_eur))]),
  [1, 2],
)}
<ul>
<li>${h(entier(tAn.autres_personnes_morales.nombre))} autres personnes morales : ${h(md(tAn.autres_personnes_morales.montant_eur))}.</li>
${conf ? `<li>Entrepreneurs individuels et titulaires non diffusibles, agrégés et jamais nommés : ${h(md(conf.montant_eur))}${conf.part_pct !== null ? ` (${h(pct(conf.part_pct, 2))} du montant de l’année)` : ''}, dont ${h(md(conf.dont_personnes_physiques_eur))} pour des entrepreneurs individuels.</li>` : ''}
</ul>
<p class="aide">${h(REGLE_PERSONNES)}</p>
<details><summary>Les 20 premiers titulaires de 2019 à 2025</summary>
${tableau(
  'Les 20 premiers titulaires nommés, total de 2019 à 2025',
  ['Titulaire', 'Marchés', '2019 à 2025'],
  tits.titulaires.slice(0, 20).map((t) => [h(t.denomination), h(entier(t.marches)), h(md(t.total_eur))]),
  [1, 2],
)}</details>
${ordre(tits.ordre)}${src(tits.source)}`
      : ''

  // --- Repère officiel ------------------------------------------------------------------------------------------------------
  const r = idx.repere_oecp
  const blocRepere =
    r && r.montant_eur !== null
      ? `<h2>Un autre décompte : le recensement de l’Observatoire économique de la commande publique</h2>
<p>${h(clair(r.producteur))} : <strong>${h(md(r.montant_eur))}</strong> pour ${h(entier(r.nombre_marches))} marchés en ${r.annee} ${statutTrace}. Ici, pour ${r.annee} : <strong>${h(md(r.montant_ici_eur))}</strong> pour ${h(entier(r.marches_ici ?? 0))} marchés ${statutTrace}.</p>
<p>${h(clair(r.lecture_ecart))}</p>
<p class="aide">${h(clair(r.perimetre))}</p>
${source(clair(`${r.producteur}, ${r.publication}${r.page_consultee ? ` ; chiffre relevé sur ${r.page_consultee.titre}` : ''}`))}`
      : ''

  // --- Méthode, limites ----------------------------------------------------------------------------------------------------
  const blocMethode = `<h2>Méthode et limites</h2>
<p>${h(clair(idx.perimetre))}</p>
<ul>${idx.limites.map((l) => `<li>${h(clair(l))}</li>`).join('')}</ul>
<details><summary>La méthode, règle par règle</summary>
<ul>${idx.methode.map((m) => `<li>${h(clair(m))}</li>`).join('')}</ul>
${tableau(
  'Lignes écartées par règle, 2019 à 2025 (une ligne est comptée dans la première règle rencontrée)',
  ['Règle', 'Lignes', 'Montant déclaré'],
  idx.regles_qualite.map((q) => [h(REGLES_CLAIRES[q.id] ?? clair(q.regle)), h(entier(q.lignes)), h(q.montant_eur === null ? 'sans montant' : md(q.montant_eur))]),
  [1, 2],
)}</details>
${(idx.sources_inaccessibles ?? []).map((s) => `<p class="aide">Page non lue par le site : ${h(s.source)}. Elle refuse les programmes de lecture automatique ; ce refus n’est pas contourné.</p>`).join('')}
${source(clair(idx.source), clair(idx.millesime))}
<p class="aide">Données collectées le ${h(idx.collecte_le)}. Unité : ${h(clair(idx.unite))}.</p>`

  const anomalies = idx.anomalies_source
  cible.innerHTML = `
<h1>Les marchés publics</h1>
<p class="chapeau">Un marché public est un achat d’un acheteur public (État, commune, département, région, hôpital, établissement public…) à une entreprise ou à un organisme : des travaux, des fournitures ou des services. Les montants ci-dessous sont ceux publiés à la signature du marché, hors taxes : pour un accord-cadre, c’est un montant maximum sur plusieurs années. Ce ne sont pas des sommes payées.</p>
<div class="bascule" role="group" aria-label="Année de notification">${annees
    .map((y) => `<a class="bouton" href="${lien(CHEMIN, { a: y })}"${y === a ? ' aria-current="true"' : ''}>${y}</a>`)
    .join('')}</div>
<ul class="cles" aria-label="Chiffres clés des marchés publics en ${a}">
  <li class="cle-famille"><strong>${h(md(total))}</strong><span>de marchés notifiés en ${a}, hors taxes</span>${statutTrace}</li>
  <li><strong>${h(entier(an.marches))}</strong><span>marchés publiés en ${a}, par ${h(entier(an.acheteurs))} acheteurs</span>${statutTrace}</li>
  <li><strong>${h(md(idx.totaux.total_retenu_eur))}</strong><span>de 2019 à 2025, ${h(entier(idx.totaux.marches_retenus))} marchés</span>${statutTrace}</li>
</ul>
<p class="aide">Tracé : chaque montant retenu figure ligne à ligne dans les données essentielles de la commande publique publiées par les acheteurs.</p>

<h2>Travaux, fournitures, services : sur 100 € de marchés de ${a}</h2>
<div class="carte" data-cle>
<p>En ${a}, les marchés notifiés représentent <strong>${surligne(md(total))}</strong>. Sur 100 € de ce montant :</p>
${billet(parts, { etiquette: `Billet de 100 € : marchés publics notifiés en ${a}, par type d’achat`, unite: 'sur 100 € de marchés' })}
${listeParts(parts, `Marchés de ${a} par type d’achat, sur 100 €`)}
${tableauBillet(parts, `Marchés notifiés en ${a} par type d’achat, sur 100 €`, ['Type d’achat', 'Sur 100 €'])}
${src(ans.source)}
</div>

<h2>Année par année</h2>
${barres(
  ans.par_annee.filter((p) => p.total_eur !== null).map((p) => ({ nom: String(p.annee), valeur: p.total_eur ?? 0, texte: md(p.total_eur), detail: `${entier(p.marches)} marchés`, lien: lien(CHEMIN, { a: p.annee }), statut: 'trace' as const })),
  undefined,
  'Montants notifiés retenus, par année',
  annees.indexOf(a),
)}
<p class="aide">L’année est celle de la notification du marché. Un marché sur plusieurs années est compté en entier l’année où il est notifié.</p>
${tableau(
  'Montants retenus et montants écartés par année (montants écartés jamais ajoutés aux totaux)',
  ['Année', 'Montant retenu', 'Marchés', 'Écarté : marques du producteur', 'Écarté : séries identiques'],
  ans.par_annee.map(ligneAnnee),
  [1, 2, 3, 4],
)}
${
  plusSerie && plusSerie.montant_declare_eur > 0 && retenuSerie
    ? `<p class="avertissement">${plusSerie.annee} : le montant retenu (${h(md(retenuSerie.total_eur))}) ne comprend pas ${h(md(plusSerie.montant_declare_eur))} déclarés dans ${h(entier(plusSerie.series))} séries de montants identiques${
        premiere ? `, dont ${h(entier(premiere.marches))} marchés de ${h(auNom(premiere.denomination))} déclarés chacun à ${h(md(premiere.montant_unitaire_eur))}` : ''
      }. Ces montants sont écartés et comptés à part, pas additionnés.</p>`
    : ''
}
${src(ans.source)}

<h2>Les montants écartés : règles et compteurs</h2>
<p>Certains montants publiés sont des erreurs de saisie probables dans la source. Aucun n’est corrigé : les lignes concernées sont écartées des totaux, comptées, et leur montant déclaré est montré à part. Deux règles s’appliquent, l’une du producteur des données, l’autre du site.</p>
<h3>Marques du producteur du jeu de données</h3>
<p>Le producteur des données consolidées marque certains montants « aberrant » ou « suspect ». Sur toutes les années : ${h(entier(anomalies.aberrant.lignes))} lignes « aberrant » (${h(md(anomalies.aberrant.montant_declare_eur))} déclarés) et ${h(entier(anomalies.suspect.lignes))} lignes « suspect » (${h(md(anomalies.suspect.montant_declare_eur))} déclarés), jamais ajoutés aux totaux.</p>
${blocSeries}
${blocGros}

<h2>Par acheteur</h2>
${blocCategories}
${blocAcheteurs}
${blocSecteurs}
${blocRegions}
${blocTitulaires}
${blocRepere}
${blocMethode}
<p class="liens-sortie"><a href="${lien('/beneficiaires', { onglet: 'marches' })}">Les marchés des services de l’État par ministère</a> · <a href="#/explorer/collectivites">Les comptes des collectivités locales</a> · <a href="#/methode/limites">Les limites connues du site</a></p>`
}

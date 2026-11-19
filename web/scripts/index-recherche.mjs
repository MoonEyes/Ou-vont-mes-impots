// Index de la recherche dans tout le site, construit au build juste après la copie des données (npm run copier-donnees).
//
// Contenu : les pages de la table des routes, les parlementaires nommés par les fichiers publiés (votes nominatifs,
// amendements adoptés), les termes du glossaire, les impôts de « Qui a voté tes impôts », les départements et les communes (données locales), les grands postes,
// missions, programmes et actions du budget de l'État, les opérateurs de l'État, les prestations sociales, les
// organismes de la Sécurité sociale, les grands impôts, les intercommunalités, et les entités publiques d'autres
// fichiers dès qu'une page du site les affiche (page trouvée dans le code de ses écrans). Rien n'est ajouté aux données
// publiées (site/data) : l'index est un fichier dérivé, écrit à côté de leur copie (public/data/_recherche.json, comme
// _manifeste.json), lu par le navigateur à la première recherche (src/composants/recherche.ts). Aucune personne
// physique : seules des pages, des collectivités, des lignes du budget, des organismes et des personnes morales
// déjà nommées par les fichiers publiés.
//
// Format compact, pour rester sous 1 Mo avant compression : une entrée est un tableau [famille, nom, cible, précision,
// mots-clés]. La cible est une adresse interne (« #/… ») ou, quand la famille a un modèle d'adresse, la valeur à y
// ajouter (le nom de l'entrée si elle est vide) ; « @commune » et « @departement » : code INSEE ou code du
// département, dont le site construit l'adresse (src/chemins.ts). Les communes tiennent en une chaîne par
// département, dans l'ordre des codes INSEE : « 001aAbergement » = suffixe du code (omis quand il suit le précédent),
// une lettre de taille (a à n : 100 habitants ou moins à plus de 500 000 ; en majuscule quand la commune a sa propre
// page), puis le nom ; entrées séparées par « | ».
//
// Organisations (entreprises, associations : fiches /beneficiaires/organisation) : pas dans l'index, trop nombreuses.
// La recherche lit à la demande les fichiers publiés par préfixe de mot (entites/recherche/<préfixe>.json) et, pour la
// ligne de contexte, un morceau par 2 premiers chiffres du SIREN écrit à côté de l'index (_recherche/org/<nn>.json).
//
// Usage : node scripts/index-recherche.mjs [--donnees <dossier>] [--sortie <fichier>]
//         par défaut : données de OVMI_DONNEES ou ../site/data, index écrit dans public/data/_recherche.json
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { gzipSync } from 'node:zlib'

export const FORMAT = 'recherche-2'
/** Taille visée pour l'index, avant compression (le serveur le compresse en plus à l'envoi). */
export const TAILLE_VISEE = 1_000_000
/** Bornes des classes de taille des communes (habitants) : la classe sert au classement, jamais à l'affichage. */
export const BORNES_POPULATION = [100, 200, 500, 1000, 2000, 3500, 5000, 10000, 20000, 50000, 100000, 200000, 500000]

const premierNombre = (x) => /(\d{3})$/.exec(x)?.[1] ?? null

/** Classe de taille d'une commune : 0 (100 habitants ou moins) à 13 (plus de 500 000). */
export const classePopulation = (p) => BORNES_POPULATION.filter((b) => (p ?? 0) > b).length

/** Encode les communes d'un département (codes INSEE croissants) en une chaîne. */
export function encoderCommunes(dep, communes, aUnePage) {
  let precedent = 0
  return Object.keys(communes)
    .sort()
    .map((insee) => {
      const c = communes[insee]
      // Le format suppose un code du département et un nom sans chiffre en tête ni « | » (vrai de tout le COG).
      if (!insee.startsWith(dep) || !/^\D[^|]*$/.test(c.nom)) throw new Error(`Index de recherche : commune ${insee} « ${c.nom} » hors du format attendu`)
      const nombre = Number(insee.slice(dep.length))
      const lettre = String.fromCharCode(97 + classePopulation(c.population))
      const suffixe = nombre === precedent + 1 ? '' : insee.slice(dep.length)
      precedent = nombre
      return `${suffixe}${aUnePage(c.population) ? lettre.toUpperCase() : lettre}${c.nom}`
    })
    .join('|')
}

/** Familles de l'index, dans l'ordre d'affichage par défaut. Les libellés sont ceux du site (src/composants/recherche.ts les affiche). */
const DETAIL_ETAT = '#/explorer/etat/detail?id='
const FAMILLES = {
  page: { nom: 'Page du site', groupe: 'Pages du site' },
  departement: { nom: 'Département', groupe: 'Départements', modele: '@departement' },
  commune: { nom: 'Commune', groupe: 'Communes' },
  intercommunalite: { nom: 'Intercommunalité', groupe: 'Intercommunalités', modele: '@commune' },
  mission: { nom: 'Budget de l’État', groupe: 'Grands postes et missions du budget de l’État', modele: DETAIL_ETAT },
  programme: { nom: 'Programme du budget de l’État', groupe: 'Programmes du budget de l’État', modele: DETAIL_ETAT },
  action: { nom: 'Action d’un programme', groupe: 'Actions des programmes du budget de l’État', modele: DETAIL_ETAT },
  operateur: { nom: 'Opérateur de l’État', groupe: 'Opérateurs de l’État' },
  prestation: { nom: 'Prestation sociale', groupe: 'Prestations sociales' },
  organisme: { nom: 'Sécurité sociale', groupe: 'Sécurité sociale : organismes et branches', modele: '#/explorer/secu?id=' },
  impot: { nom: 'Impôt ou cotisation', groupe: 'Impôts et cotisations', modele: '#/explorer/recettes?i=' },
  parlementaire: { nom: 'Parlementaire', groupe: 'Parlementaires : votes et amendements' },
  glossaire: { nom: 'Glossaire', groupe: 'Mots et sigles du glossaire', modele: '#/methode/glossaire?terme=' },
  organisation: { nom: 'Organisation', groupe: 'Entreprises, associations et autres organisations', modele: '#/beneficiaires/organisation?siren=' },
}

/**
 * Entités publiques d'autres fichiers : indexées seulement quand une page du site les affiche, c'est-à-dire quand le
 * code de l'écran d'une route lit le fichier. Le lien mène à cette page. Extraction prudente : un format inattendu
 * laisse la famille vide (signalée dans le bilan), jamais une erreur de build.
 */
const AUTRES_ENTITES = [
  {
    cle: 'entite_etat',
    fichier: 'etat_actionnaire/entites.json',
    nom: 'Entité contrôlée par l’État',
    groupe: 'Entités contrôlées par l’État',
    extraire: (d) =>
      (d.dividendes_par_ligne_d_execution ?? [])
        .filter((x) => x?.entite?.siren && typeof x.libelle_source === 'string')
        .map((x) => ({ nom: x.libelle_source.replace(/^[^:]*:\s*/, ''), precision: 'Dividendes versés au budget de l’État', cles: x.entite.denomination })),
  },
  {
    cle: 'prison',
    fichier: 'justice_defense/prisons.json',
    nom: 'Établissement pénitentiaire',
    groupe: 'Établissements pénitentiaires',
    // Noms publiés en sigles (« MA LYON CORBAS ») : la nature de l'établissement et « saint » écrits en toutes lettres
    // dans les mots-clés, pour les retrouver comme on les nomme.
    extraire: (d) =>
      (d.etablissements ?? [])
        .filter((x) => typeof x?.etablissement === 'string')
        .map((x) => ({
          nom: x.etablissement,
          precision: x.disp ?? '',
          cles: [SIGLES_PENITENTIAIRES[x.etablissement.split(' ')[0]], /\bSTE?\b/.test(x.etablissement) ? x.etablissement.replace(/\bST(E?)\b/g, 'SAINT$1') : ''].filter(Boolean).join(' '),
        })),
  },
  {
    cle: 'regime',
    fichier: 'retraites/regimes.json',
    nom: 'Régime de retraite',
    groupe: 'Régimes de retraite',
    extraire: (d) =>
      Object.values(d.regimes ?? {})
        .filter((x) => typeof x?.nom === 'string' && x.type !== 'ensemble')
        .map((x) => ({ nom: x.nom, precision: '', cles: x.libelle_source })),
  },
  {
    cle: 'ministere',
    fichier: 'fonction_publique/ministeres.json',
    nom: 'Ministère',
    groupe: 'Ministères',
    extraire: (d) => (d.ministeres ?? []).filter((x) => typeof x?.ministere === 'string').map((x) => ({ nom: x.ministere, precision: 'Effectifs et masse salariale' })),
  },
]

/** Sigles des établissements pénitentiaires (direction de l'administration pénitentiaire). */
const SIGLES_PENITENTIAIRES = {
  CD: 'centre de détention',
  CP: 'centre pénitentiaire',
  MA: 'maison d’arrêt',
  MC: 'maison centrale',
  CSL: 'centre de semi-liberté',
  EPM: 'établissement pénitentiaire pour mineurs',
  CPA: 'centre pour peines aménagées',
}

/** Ordre des résultats, écrit à l'écran (page de résultats et suggestions de l'en-tête). */
export const REGLE_ORDRE =
  'Ordre des résultats : correspondance du texte seulement (nom identique, puis début du nom, puis mot approchant), à égalité nom le plus court puis ordre alphabétique ; jamais par montant, par taille ni par groupe politique.'

/** Noms d'usage des impôts de « Qui a voté tes impôts ». */
const NOMS_IMPOTS_VOTES = { tva: 'TVA', csg: 'CSG', crds: 'CRDS', impot_revenu: 'IR prélèvement à la source', taxe_fonciere: 'TFPB', teom: 'TEOM ordures ménagères', accises_energie: 'TICPE carburants accise électricité gaz' }

/** Noms courants des grands impôts (codes Eurostat de recettes.json), pour les retrouver par leur nom d'usage. */
const NOMS_IMPOTS = {
  D211: 'TVA taxe sur la valeur ajoutée',
  D51A_C1: 'impôt sur le revenu IR CSG CRDS prélèvement à la source',
  D51B: 'impôt sur les sociétés IS',
  D61: 'cotisations sociales',
  D214A: 'accises carburants TICPE tabac alcool',
  D29: 'impôts sur la production taxe foncière des entreprises',
  D91: 'droits de succession donation',
}

const ordinal = (n) => (n === 1 ? '1re' : `${n}e`)
const cleNom = (x) =>
  String(x)
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()

/**
 * Parlementaires nommés par les fichiers publiés : députés des circonscriptions (qui_a_vote/departements, vote
 * nominatif aux scrutins publics retenus) et auteurs d'amendements adoptés (decisions/programme_*.json et
 * qui_a_vote/impot_*.json). Groupe : celui que la source écrit au dernier vote ou au dernier amendement.
 */
export function parlementaires({ lire, qav, existe }) {
  const out = []
  const parNom = new Map()
  // Auteurs d'amendements adoptés (Assemblée et Sénat), avec la page où l'amendement est montré.
  const auteurs = new Map()
  const noter = (a, chambre, page, programme) => {
    const au = a?.auteur
    if (!au || typeof au.nom !== 'string' || !au.nom.trim() || !['député', 'sénateur', 'rapporteur'].includes(au.type)) return
    const k = cleNom(au.nom)
    const x = auteurs.get(k) ?? { nom: au.nom, chambres: new Set(), n: 0, date: '', groupe: null, programmes: new Set(), pages: new Set() }
    x.n++
    x.chambres.add(/s[ée]nat/i.test(chambre) ? 'Sénat' : 'Assemblée nationale')
    if (programme) x.programmes.add(programme)
    x.pages.add(page)
    if (String(a.date ?? '') >= x.date) {
      x.date = String(a.date ?? '')
      if (au.groupe) x.groupe = au.groupe
    }
    auteurs.set(k, x)
  }
  if (existe.has('/decisions/votes')) {
    const di = lire('decisions/index.json')
    for (const f of di?.fichiers ?? []) {
      const d = lire(f)
      const programme = String(d?.programme ?? '')
      for (const an of Object.values(d?.annees ?? {})) for (const a of an?.amendements_adoptes ?? []) noter(a, a.chambre ?? '', `#/decisions/votes?p=${encodeURIComponent(programme)}`, programme)
    }
  }
  if (existe.has('/decisions/qui-a-vote'))
    for (const i of qav?.impots ?? []) {
      const d = lire(`qui_a_vote/${i.fichier}`)
      for (const a of d?.amendements_adoptes ?? []) noter(a, a.chambre ?? '', `#/decisions/qui-a-vote?impot=${encodeURIComponent(i.id)}`, null)
    }
  const amendements = (x) => (x ? ` · ${x.n} amendement${x.n > 1 ? 's' : ''} adopté${x.n > 1 ? 's' : ''}` : '')
  const groupe = (g) => `groupe ${String(g).replace(/^groupe\s+/i, '')}`

  // Députés par circonscription : la page « Qui a voté tes impôts » ouverte sur leur circonscription.
  if (existe.has('/decisions/qui-a-vote'))
    for (const dep of qav?.departements ?? []) {
      const d = lire(`qui_a_vote/${dep.fichier}`)
      for (const c of d?.circonscriptions ?? [])
        for (const x of c.deputes ?? []) {
          if (typeof x?.nom !== 'string' || !x.nom.trim()) continue
          let dernier = null
          for (const v of x.votes ?? []) if (Array.isArray(v) && (!dernier || v[0] > dernier[0])) dernier = v
          const k = cleNom(x.nom)
          const a = auteurs.get(k)
          if (a) a.vu = true
          parNom.set(k, true)
          out.push({
            nom: x.nom,
            cible: `#/decisions/qui-a-vote?dep=${encodeURIComponent(dep.code)}&circo=${c.numero}`,
            precision: `Député · ${dep.nom} (${dep.code}), ${ordinal(c.numero)} circonscription${x.fin ? ` · mandat terminé le ${x.fin.split('-').reverse().join('/')}` : ''}${dernier?.[3] ? ` · ${groupe(dernier[3])} (dernier scrutin retenu)` : ''} · ${x.votes?.length ?? 0} vote${(x.votes?.length ?? 0) > 1 ? 's' : ''} nominatif${(x.votes?.length ?? 0) > 1 ? 's' : ''}${amendements(a)}`,
            cles: `député ${dep.nom}`,
          })
        }
    }
  // Auteurs sans circonscription dans les fichiers (sénateurs, anciens députés) : la page de leurs amendements.
  for (const [, a] of [...auteurs.entries()].sort((x, y) => (x[0] < y[0] ? -1 : 1))) {
    if (a.vu) continue
    const programmes = [...a.programmes].sort()
    const page = [...a.pages].sort()[0]
    const chambre = [...a.chambres].sort().join(' et ')
    out.push({
      nom: a.nom,
      cible: page,
      precision: `${chambre === 'Sénat' ? 'Sénat' : `Parlementaire, ${chambre}`}${a.groupe ? ` · ${groupe(a.groupe)} (dernier amendement)` : ''}${amendements(a)}${programmes.length ? ` (programme${programmes.length > 1 ? 's' : ''} ${programmes.slice(0, 4).join(', ')}${programmes.length > 4 ? '…' : ''})` : ''}`,
      cles: chambre === 'Sénat' ? 'sénateur sénatrice' : 'député',
    })
  }
  return out
}

/** Configuration de la recherche des organisations : fichiers de recherche publiés par préfixe de mot. */
export function configOrganisations(idx, existe) {
  const f = idx?.fichiers
  if (!f?.recherche || typeof f.recherche !== 'object' || !existe.has('/beneficiaires/organisation')) return null
  return {
    prefixes: f.recherche,
    ...(f.recherche_entrees ? { tailles: f.recherche_entrees } : {}),
    frequents: (f.mots_frequents ?? []).map((m) => m.mot).filter((m) => typeof m === 'string'),
    canaux: (idx.canaux ?? []).map((c) => String(c.titre ?? c.id)),
    contexte: MORCEAUX_ORGANISATIONS,
    total: idx.comptes?.organisations_avec_fiche ?? null,
  }
}

/** Taille visée d'un morceau de contexte des organisations (octets, avant compression). */
export const TAILLE_MORCEAU_ORG = 200_000

/** Dossier des morceaux de contexte des organisations (à côté de l'index), un fichier par 2 premiers chiffres du SIREN. */
export const MORCEAUX_ORGANISATIONS = '_recherche/org/'

/**
 * Montant le plus récent d'une fiche, tel que publié, sans aucun calcul du site : l'année la plus récente pour
 * laquelle une source publie un seul montant (une seule série, une seule valeur). Une année avec plusieurs lignes
 * (qu'il faudrait additionner) est sautée. Plusieurs sources la même année : la première dans l'ordre de la fiche
 * (identifiant de la source), jamais la plus grosse. Rien n'est additionné, ni dans une source ni entre sources.
 */
export function montantRecent(fiche, canaux) {
  let choix = null
  for (const b of fiche?.recoit ?? []) {
    const canal = canaux.indexOf(b.canal)
    const parAnnee = new Map()
    for (const s of b.series ?? [])
      for (const [an, m] of s.valeurs ?? []) {
        if (typeof an !== 'number') continue
        const x = parAnnee.get(an) ?? { n: 0, m }
        x.n++
        parAnnee.set(an, x)
      }
    const annees = [...parAnnee.keys()].filter((an) => parAnnee.get(an).n === 1 && typeof parAnnee.get(an).m === 'number').sort((a, b) => b - a)
    if (annees.length && (!choix || annees[0] > choix[0])) choix = [annees[0], parAnnee.get(annees[0]).m, canal]
  }
  return choix
}

/**
 * Morceaux de contexte des organisations qui ont une fiche : { siren: [dénomination, nombre de sources,
 * département ou null, année, montant publié, indice de la source] }, regroupés par 2 premiers chiffres
 * du SIREN. La dénomination est celle des fichiers de recherche publiés (entites/recherche/), jamais une autre.
 */
export function morceauxOrganisations({ lire, lister }) {
  const idx = lire('entites/index.json')
  if (!idx?.fichiers?.recherche) return null
  const noms = new Map()
  for (const f of new Set(Object.values(idx.fichiers.recherche))) for (const e of lire(f)?.entrees ?? []) if (Array.isArray(e) && /^\d{9}$/.test(e[0])) noms.set(e[0], e)
  const canaux = (idx.canaux ?? []).map((c) => c.id)
  const morceaux = {}
  const fichiers = new Set(Object.values(idx.fichiers.fiches ?? {}))
  if (!fichiers.size) for (const n of lister('entites/fiches')) if (n.endsWith('.json')) fichiers.add(`entites/fiches/${n}`)
  const vus = new Set()
  for (const f of [...fichiers].sort())
    for (const [siren, fiche] of Object.entries(lire(f)?.fiches ?? {})) {
      const e = noms.get(siren)
      if (!e || vus.has(siren)) continue
      vus.add(siren)
      const m = montantRecent(fiche, canaux)
      ;(morceaux[siren.slice(0, 2)] ??= {})[siren] = [e[1], e[2] ?? null, e[3] ?? null, ...(m ?? [null, null, null])]
    }
  // Organisations des fichiers de recherche sans fiche lue : nom seul.
  for (const [siren, e] of noms) if (!vus.has(siren)) (morceaux[siren.slice(0, 2)] ??= {})[siren] = [e[1], e[2] ?? null, e[3] ?? null, null, null, null]
  // Un morceau trop gros (communes et groupements : SIREN 21…) est redécoupé par un chiffre de plus.
  const decoupe = {}
  const placer = (k, contenu) => {
    if (JSON.stringify(contenu).length <= TAILLE_MORCEAU_ORG || k.length >= 6) {
      decoupe[k] = contenu
      return
    }
    const sous = {}
    for (const [siren, v] of Object.entries(contenu)) (sous[siren.slice(0, k.length + 1)] ??= {})[siren] = v
    for (const [kk, c] of Object.entries(sous)) placer(kk, c)
  }
  for (const [k, c] of Object.entries(morceaux)) placer(k, c)
  const tries = {}
  for (const k of Object.keys(decoupe).sort()) tries[k] = Object.fromEntries(Object.entries(decoupe[k]).sort((a, b) => (a[0] < b[0] ? -1 : 1)))
  return { format: FORMAT, millesime: String(idx.millesime ?? ''), source: String(idx.source ?? ''), morceaux: tries }
}

/**
 * Construit l'index.
 * @param {object} o
 * @param {(chemin: string) => any} o.lire  lit un fichier de données (JSON) ; null s'il manque ou s'il est illisible
 * @param {(dossier: string) => string[]} o.lister  noms des fichiers d'un dossier de données ([] s'il manque)
 * @param {{ chemin: string, titre: string, titrePage?: string, court?: string, description: string, resume?: string, sansIndex?: boolean }[]} o.routes
 * @param {(chemin: string) => string} o.sourceEcran  code source de l'écran d'une route ('' si inconnu)
 * @param {{ aUnePage: (population: number) => boolean, libelle?: (x: string) => string, departements?: [string, string][] }} o.outils
 *        règle des pages de commune (src/chemins.ts), libellés accentués (src/util.ts), noms des départements (src/departements.ts)
 */
export function construireIndex({ lire, lister, routes, sourceEcran, outils }) {
  const familles = []
  const entrees = []
  const bilan = {}
  const libelle = outils.libelle ?? ((x) => x)
  const famille = (cle, def, origine, modele = def.modele) => {
    let i = familles.findIndex((f) => f.cle === cle)
    if (i < 0) {
      familles.push({ cle, nom: def.nom, groupe: def.groupe, ...(modele ? { modele } : {}), ...origine })
      i = familles.length - 1
    }
    return i
  }
  const ajouter = (cle, nom, cible, precision = '', cles = '') => {
    const f = familles.findIndex((x) => x.cle === cle)
    const e = [f, nom, cible]
    if (precision || cles) e.push(precision)
    if (cles) e.push(cles)
    entrees.push(e)
    bilan[cle] = (bilan[cle] ?? 0) + 1
  }
  const origine = (d) => ({ ...(d?.source ? { source: String(d.source) } : {}), ...(d?.millesime ? { millesime: String(d.millesime) } : {}) })
  const existe = new Set(routes.map((r) => r.chemin))
  /** Route dont l'écran lit le fichier (chemin exact d'abord, puis son dossier). */
  const pageQuiLit = (fichier) => {
    for (const motif of [fichier, fichier.replace(/[^/]+$/, '')]) {
      const r = routes.find((x) => !x.sansIndex && sourceEcran(x.chemin).includes(motif))
      if (r) return r
    }
    return null
  }

  // Pages : toutes les routes indexables (les pages à paramètre, commune ou département, sont indexées une à une plus bas).
  famille('page', FAMILLES.page, { source: 'Table des pages du site' })
  for (const r of routes) {
    if (r.sansIndex) continue
    const cles = [r.court, r.titrePage].filter((x) => x && x !== r.titre).join(' ; ')
    ajouter('page', r.titre, '#' + r.chemin, r.resume ?? r.description, cles)
  }

  // Départements et communes : fichiers local/geo/<dep>.json (code officiel géographique, populations légales).
  const deps = lister('local/geo')
    .filter((f) => f.endsWith('.json'))
    .map((f) => f.slice(0, -5))
    .sort()
  const nomsDep = new Map(outils.departements ?? [])
  const departements = {}
  const communes = {}
  const epci = new Map()
  let geo0 = null
  for (const dep of deps) {
    const g = lire(`local/geo/${dep}.json`)
    if (!g?.communes) continue
    geo0 ??= g
    const nom = nomsDep.get(dep) ?? g.departement?.nom ?? dep
    departements[dep] = nom
    famille('departement', FAMILLES.departement, origine(g))
    ajouter('departement', nom, dep, `Département${g.region?.nom ? ` · région ${g.region.nom}` : ''}`, dep)
    famille('commune', FAMILLES.commune, origine(g))
    communes[dep] = encoderCommunes(dep, g.communes, outils.aUnePage)
    bilan.commune = (bilan.commune ?? 0) + Object.keys(g.communes).length
    for (const [insee, c] of Object.entries(g.communes)) {
      if (!c.epci || !g.epci?.[c.epci]) continue
      const e = epci.get(c.epci) ?? { nom: g.epci[c.epci].nom, siege: g.epci[c.epci].departement_siege, meilleure: null }
      if (!e.meilleure || (c.population ?? 0) > e.meilleure.population) e.meilleure = { insee, nom: c.nom, population: c.population ?? 0 }
      epci.set(c.epci, e)
    }
  }
  // Intercommunalités : pas de page propre ; leur budget est présenté sur la page de chacune de leurs communes, et la
  // recherche mène à celle de la plus peuplée. Précision : code du département du siège (le site écrit la phrase).
  if (epci.size) {
    famille('intercommunalite', FAMILLES.intercommunalite, origine(geo0))
    for (const [, e] of [...epci.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
      const siege = String(e.siege ?? '').split(',')[0]
      ajouter('intercommunalite', e.nom, e.meilleure.insee, departements[siege] ? siege : '')
    }
  }

  // Budget de l'État : arbre de l'exécution (vue par défaut du site), grands postes, missions, programmes et actions.
  const arbre = lire('arbre/racine.json')
  if (arbre?.enfants) {
    const o = origine(arbre)
    famille('mission', FAMILLES.mission, o)
    famille('programme', FAMILLES.programme, o)
    famille('action', FAMILLES.action, o)
    for (const gp of arbre.enfants) {
      ajouter('mission', libelle(gp.nom), gp.id, 'Grand poste du budget de l’État (missions regroupées)')
      for (const mi of gp.enfants ?? []) {
        ajouter('mission', libelle(mi.nom), mi.id, `Mission du budget de l’État · ${libelle(gp.nom)}`)
        for (const pr of mi.enfants ?? []) {
          const n = premierNombre(pr.id)
          ajouter('programme', pr.nom, pr.id, `Programme${n ? ` ${n}` : ''} · mission ${mi.nom}`, n ? `programme ${n}` : '')
          const sous = pr.enfants ?? (pr.fichier ? lire(pr.fichier)?.enfants : null) ?? []
          const parcourir = (noeuds) => {
            for (const a of noeuds) {
              if (typeof a?.nom !== 'string' || typeof a?.id !== 'string') continue
              ajouter('action', a.nom, a.id, `${a.niveau === 'sous_action' ? 'Sous-action' : 'Action'} du programme${n ? ` ${n}` : ''} · ${pr.nom}`)
              if (Array.isArray(a.enfants)) parcourir(a.enfants)
            }
          }
          parcourir(sous)
        }
      }
    }
  }

  // Opérateurs de l'État : chaque opérateur, chaque catégorie et chaque établissement d'une catégorie.
  const ops = lire('operateurs/operateurs.json')
  if (Array.isArray(ops?.operateurs) && existe.has('/explorer/operateurs')) {
    // Recherche dans la page par son paramètre q (nom de l'opérateur ou de sa catégorie), quand l'écran le lit ;
    // sinon, filtre par mission.
    const avecQ = /params\.get\(\s*['"]q['"]\s*\)/.test(sourceEcran('/explorer/operateurs'))
    famille('operateur', FAMILLES.operateur, origine(ops), avecQ ? '#/explorer/operateurs?q=' : '#/explorer/operateurs?mission=')
    const versOperateur = (o, membre) => (avecQ ? (membre ? o.nom : '') : o.mission_chef_de_file ?? '#/explorer/operateurs')
    const vus = new Set()
    for (const o of ops.operateurs) {
      if (typeof o?.nom !== 'string') continue
      const mission = o.mission_chef_de_file ? ` · mission ${o.mission_chef_de_file}` : ''
      ajouter('operateur', o.nom, versOperateur(o, false), `${o.niveau === 'categorie' ? 'Catégorie d’opérateurs de l’État' : 'Opérateur de l’État'}${mission}`, o.sigle ?? '')
      vus.add(o.nom.toLowerCase())
      for (const m of o.membres ?? []) {
        if (typeof m?.nom !== 'string' || vus.has(m.nom.toLowerCase())) continue
        vus.add(m.nom.toLowerCase())
        ajouter('operateur', m.nom, versOperateur(o, true), `Opérateur de l’État, catégorie « ${o.nom} »`)
      }
    }
  }

  // Prestations sociales : la page qui les présente si elle existe, sinon le bloc de l'arbre qui les finance.
  const pres = lire('prestations/index.json')
  if (Array.isArray(pres?.prestations)) {
    const page = pageQuiLit('prestations/index.json')
    const versBloc = (p) => {
      for (const l of p.liens ?? []) {
        if (l?.vue === 'secu_arbre' && l.id && existe.has('/explorer/secu')) return `#/explorer/secu?id=${encodeURIComponent(l.id)}`
        if (l?.vue === 'arbre_etat' && l.id && existe.has('/explorer/etat/detail')) return `#/explorer/etat/detail?id=${encodeURIComponent(l.id)}`
      }
      return existe.has('/explorer/secu') ? '#/explorer/secu' : null
    }
    famille('prestation', FAMILLES.prestation, origine(pres))
    for (const p of pres.prestations) {
      const lien = page ? '#' + page.chemin : versBloc(p)
      if (typeof p?.nom !== 'string' || !lien) continue
      ajouter('prestation', p.nom, lien, p.financeur ? `Prestation sociale · ${p.financeur}` : 'Prestation sociale')
    }
  }

  // Sécurité sociale : organismes, branches et postes des comptes des organismes (vue par défaut de la page).
  const secu = lire('secu/arbre/racine.json')
  if (secu?.enfants && existe.has('/explorer/secu')) {
    famille('organisme', FAMILLES.organisme, origine(secu))
    const parcourir = (n, parent, profondeur) => {
      for (const e of n.enfants ?? []) {
        if (typeof e?.nom !== 'string' || !(e.md > 0) || /^(Arrondis|Autres charges|Autres dépenses|Autres transferts|Transferts versés|Transferts entre)/.test(e.nom)) continue
        ajouter('organisme', e.nom, e.id, `Sécurité sociale, comptes des organismes${parent ? ` · ${parent}` : ''}`)
        if (profondeur < 2) parcourir(e, e.nom, profondeur + 1)
      }
    }
    parcourir(secu, '', 0)
  }

  // Impôts et cotisations : les grandes catégories de recettes (page des recettes, choix par code).
  const rec = lire('recettes.json')
  if (rec?.impots && existe.has('/explorer/recettes')) {
    famille('impot', FAMILLES.impot, origine(rec))
    for (const code of Object.keys(rec.impots).sort()) {
      const x = rec.impots[code]
      if (typeof x?.nom !== 'string') continue
      ajouter('impot', x.nom, code, 'Recettes publiques, qui encaisse chaque impôt', [NOMS_IMPOTS[code], code].filter(Boolean).join(' '))
    }
  }

  // Impôts suivis par « Qui a voté tes impôts » : la page de l'impôt (articles, scrutins, amendements adoptés).
  const qav = lire('qui_a_vote/index.json')
  if (Array.isArray(qav?.impots) && existe.has('/decisions/qui-a-vote')) {
    famille('impot', FAMILLES.impot, origine(rec ?? qav))
    for (const i of qav.impots) {
      if (typeof i?.id !== 'string' || typeof i?.libelle !== 'string') continue
      ajouter('impot', i.libelle, `#/decisions/qui-a-vote?impot=${encodeURIComponent(i.id)}`, 'Qui a voté cet impôt : articles des lois de finances, scrutins et amendements (17e législature)', NOMS_IMPOTS_VOTES[i.id] ?? '')
    }
  }

  // Parlementaires : seulement ceux que les fichiers publiés nomment (vote nominatif aux scrutins publics retenus,
  // auteur d'un amendement adopté), avec leur groupe tel que publié. Aucune autre donnée personnelle.
  const parl = parlementaires({ lire, lister, qav, existe })
  if (parl.length) {
    famille('parlementaire', FAMILLES.parlementaire, { source: String(qav?.source ?? lire('decisions/index.json')?.source ?? ''), millesime: String(qav?.millesime ?? '') })
    for (const x of parl) ajouter('parlementaire', x.nom, x.cible, x.precision, x.cles)
  }

  // Glossaire du site (src/glossaire.json) : chaque terme, avec son sigle, ses variantes et sa forme développée.
  const glo = outils.glossaire
  if (Array.isArray(glo?.termes) && existe.has('/methode/glossaire')) {
    famille('glossaire', FAMILLES.glossaire, { source: 'Glossaire du site', ...(glo.maj ? { millesime: String(glo.maj) } : {}) })
    for (const t of glo.termes) {
      if (typeof t?.id !== 'string' || typeof t?.terme !== 'string') continue
      const def = String(t.forme ?? t.definition ?? '')
      ajouter('glossaire', t.terme, t.id, `Glossaire${def ? ` · ${def.length > 90 ? def.slice(0, 89).replace(/\s+\S*$/, '') + '…' : def}` : ''}`, [t.sigle, ...(t.variantes ?? []), t.forme].filter((x) => typeof x === 'string' && x).join(' ; '))
    }
  }

  // Autres entités publiques déjà publiées : seulement si une page les affiche.
  const sansPage = []
  for (const a of AUTRES_ENTITES) {
    const d = lire(a.fichier)
    if (!d) continue
    const page = pageQuiLit(a.fichier)
    if (!page) {
      sansPage.push(a.fichier)
      continue
    }
    let liste = []
    try {
      liste = a.extraire(d)
    } catch {
      liste = []
    }
    const vus = new Set()
    famille(a.cle, a, origine(d))
    for (const x of liste) {
      if (typeof x?.nom !== 'string' || !x.nom.trim() || vus.has(x.nom.toLowerCase())) continue
      vus.add(x.nom.toLowerCase())
      ajouter(a.cle, x.nom, x.cible ?? '#' + page.chemin, [a.nom, x.precision].filter(Boolean).join(' · '), x.cles ?? '')
    }
  }

  // Organisations (fiches /beneficiaires/organisation) : pas d'entrée ici, la recherche lit à la demande les fichiers
  // de recherche publiés par préfixe de mot (entites/recherche/) et le contexte de chaque organisation (morceaux par
  // début de SIREN, écrits à côté de l'index).
  const org = configOrganisations(lire('entites/index.json'), existe)
  if (org) famille('organisation', FAMILLES.organisation, origine(lire('entites/index.json')))

  // Familles sans entrée (fichier absent ou vide) : retirées, les indices des entrées restent cohérents.
  const avecEntrees = new Set(entrees.map((e) => e[0]))
  const utilisees = familles.map((f, i) => i).filter((i) => avecEntrees.has(i) || (familles[i].cle === 'commune' && Object.keys(communes).length) || (familles[i].cle === 'organisation' && org))
  const renum = new Map(utilisees.map((ancien, nouveau) => [ancien, nouveau]))
  const date = [lire('mise_a_jour.json')?.genere_le, lire('meta.json')?.genere_le].find((x) => typeof x === 'string' && /^\d{4}-\d{2}-\d{2}/.test(x))
  const index = {
    format: FORMAT,
    ...(date ? { date_donnees: date.slice(0, 10) } : {}),
    familles: utilisees.map((i) => familles[i]),
    entrees: entrees.map((e) => [renum.get(e[0]), ...e.slice(1)]),
    departements,
    communes: { famille: renum.get(familles.findIndex((f) => f.cle === 'commune')) ?? -1, par_departement: communes },
    ...(org ? { organisations: { famille: renum.get(familles.findIndex((f) => f.cle === 'organisation')), ...org } } : {}),
    regle_ordre: REGLE_ORDRE,
  }
  return { index, bilan: { ...bilan, entites_sans_page: sansPage } }
}

/** Morceaux par type, lus seulement à la première recherche, en même temps que le noyau. */
export const MORCEAUX_TYPES = { communes: ['commune', 'intercommunalite'], parlementaires: ['parlementaire'] }

/**
 * Découpe l'index par type : un noyau (pages, budget, impôts, glossaire, départements...) et un morceau par type
 * volumineux (communes et intercommunalités, parlementaires). Le site les réassemble (src/composants/recherche.ts).
 */
export function decouperIndex(index) {
  const noyau = { ...index, entrees: [], communes: { famille: index.communes.famille, par_departement: {} }, morceaux: {} }
  const morceaux = {}
  const typeDe = new Map()
  for (const [nom, cles] of Object.entries(MORCEAUX_TYPES)) for (const c of cles) typeDe.set(index.familles.findIndex((f) => f.cle === c), nom)
  for (const e of index.entrees) {
    const t = typeDe.get(e[0])
    if (t) (morceaux[t] ??= { format: index.format, entrees: [] }).entrees.push(e)
    else noyau.entrees.push(e)
  }
  if (Object.keys(index.communes.par_departement).length) (morceaux.communes ??= { format: index.format, entrees: [] }).communes = index.communes.par_departement
  for (const t of Object.keys(morceaux).sort()) noyau.morceaux[t] = `_recherche/${t}.json`
  return { noyau, morceaux }
}

/** Écrit l'index (JSON compact, ordre stable) et renvoie ses tailles brute et compressée. */
export function ecrireIndex(index, sortie) {
  const texte = JSON.stringify(index)
  mkdirSync(dirname(sortie), { recursive: true })
  writeFileSync(sortie, texte)
  return { octets: Buffer.byteLength(texte), octets_gzip: gzipSync(texte).length }
}

// --- Exécution en ligne de commande ------------------------------------------------------------------------------
async function principal() {
  const WEB = join(dirname(fileURLToPath(import.meta.url)), '..')
  const arg = (nom) => {
    const i = process.argv.indexOf(nom)
    return i > 0 ? process.argv[i + 1] : undefined
  }
  const donnees = arg('--donnees') ?? process.env.OVMI_DONNEES ?? join(WEB, '..', 'site', 'data')
  const sortie = arg('--sortie') ?? join(WEB, 'public', 'data', '_recherche.json')
  if (!existsSync(donnees)) {
    console.error(`Index de recherche : données introuvables (${donnees}).`)
    process.exit(1)
  }
  const lire = (chemin) => {
    if (chemin.includes('..')) return null
    try {
      return JSON.parse(readFileSync(join(donnees, chemin), 'utf8'))
    } catch {
      return null
    }
  }
  const lister = (dossier) => {
    try {
      return readdirSync(join(donnees, dossier))
    } catch {
      return []
    }
  }
  // Le code du site (table des routes, adresses des communes et départements, libellés), chargé par Vite comme au prérendu.
  const { createServer } = await import('vite')
  const vite = await createServer({ root: WEB, logLevel: 'error', appType: 'custom', server: { middlewareMode: true, hmr: false, ws: false, watch: null }, optimizeDeps: { noDiscovery: true, include: [] } })
  let routes, outils
  try {
    const { ROUTES } = await vite.ssrLoadModule('/src/routes.ts')
    const chemins = await vite.ssrLoadModule('/src/chemins.ts')
    const { TOUS_DEPARTEMENTS } = await vite.ssrLoadModule('/src/departements.ts')
    const { libelle } = await vite.ssrLoadModule('/src/util.ts')
    routes = ROUTES.map((r) => ({ ...r, ecran: /(\/src\/[\w/.-]+\.ts)/.exec(String(r.charger))?.[1] ?? null }))
    outils = { aUnePage: chemins.aUnePage, libelle, departements: TOUS_DEPARTEMENTS, glossaire: JSON.parse(readFileSync(join(WEB, 'src', 'glossaire.json'), 'utf8')) }
  } finally {
    await vite.close()
  }
  const sources = new Map()
  const sourceEcran = (chemin) => {
    const r = routes.find((x) => x.chemin === chemin)
    if (!r?.ecran) return ''
    if (!sources.has(r.ecran)) {
      try {
        sources.set(r.ecran, readFileSync(join(WEB, r.ecran), 'utf8'))
      } catch {
        sources.set(r.ecran, '')
      }
    }
    return sources.get(r.ecran)
  }
  const { index, bilan } = construireIndex({ lire, lister, routes, sourceEcran, outils })
  // Morceaux à côté de l'index (un dossier régénéré à chaque construction) : types volumineux, contexte des organisations.
  rmSync(join(dirname(sortie), '_recherche'), { recursive: true, force: true })
  const dossierOrg = join(dirname(sortie), MORCEAUX_ORGANISATIONS)
  let org = { n: 0, octets: 0, max: 0 }
  const mo = index.organisations ? morceauxOrganisations({ lire, lister }) : null
  if (mo) index.organisations.morceaux = Object.keys(mo.morceaux)
  const { noyau, morceaux } = decouperIndex(index)
  const tailles = ecrireIndex(noyau, sortie)
  const parType = Object.entries(morceaux).map(([t, m]) => [t, ecrireIndex(m, join(dirname(sortie), noyau.morceaux[t]))])
  if (mo) {
    for (const [k, entrees] of Object.entries(mo.morceaux)) {
      const t = ecrireIndex({ format: mo.format, millesime: mo.millesime, source: mo.source, entrees }, join(dossierOrg, `${k}.json`))
      org = { n: org.n + Object.keys(entrees).length, octets: org.octets + t.octets, max: Math.max(org.max, t.octets), fichiers: (org.fichiers ?? 0) + 1 }
    }
  }
  const parts = Object.entries(bilan)
    .filter(([k]) => k !== 'entites_sans_page')
    .map(([k, v]) => `${v} ${k}`)
  console.log(
    `Index de recherche : ${parts.join(', ')} ; noyau ${(tailles.octets / 1e6).toFixed(2)} Mo (${(tailles.octets_gzip / 1e3).toFixed(0)} Ko compressé) dans ${relative(process.cwd(), sortie) || sortie}` +
      parType.map(([t, x]) => `, ${t} ${(x.octets / 1e6).toFixed(2)} Mo (${(x.octets_gzip / 1e3).toFixed(0)} Ko compressé)`).join('') +
      '.' +
      (mo ? ` Organisations : ${org.n} dans ${org.fichiers} morceaux (${(org.octets / 1e6).toFixed(2)} Mo, ${(org.max / 1e3).toFixed(0)} Ko au plus).` : '') +
      (bilan.entites_sans_page.length ? ` Pas encore de page pour : ${bilan.entites_sans_page.join(', ')}.` : ''),
  )
  for (const [t, x] of [['noyau', tailles], ...parType]) if (x.octets > TAILLE_VISEE) console.warn(`Index de recherche (${t}) : ${x.octets} octets, au-delà des ${TAILLE_VISEE} visés.`)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await principal()

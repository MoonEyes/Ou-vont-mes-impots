// La France et les autres pays de l'Union (site/data/comparaison/) : dépense publique par fonction et
// prélèvements obligatoires, en part du PIB, par habitant et en part du total, sur les années publiées par Eurostat.
// Autre sujet que /explorer/ue (ce que la France verse au budget de l'Union) : les deux pages se renvoient l'une à l'autre.
// Neutralité : aucun rang, aucune couleur de valeur ; la France est seulement repérée (mot et contour) ; ordre affiché.
import { choixLiens, listeRecherche } from '../composants/choix'
import { partPersonnelle } from '../composants/hub'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { absent, eur, h, pct, source, sur100, surligne } from '../util'

const CHEMIN = '/explorer/comparaison-europe'
const FR = 'FR'
const UE27 = 'EU27_2020'
const ZONE_EURO = 'EA20'
/** Code Eurostat du total des impôts et cotisations sociales obligatoires, raccourci en « PO » dans l'adresse. */
const ALIAS_PO = 'PO'

type Unite = 'pct_pib' | 'eur_hab' | 'part_total'
type Serie = Partial<Record<Unite, (number | null)[]>>
type Statuts = Record<string, Record<string, { p?: number[]; b?: number[] }>>

interface Pays {
  geo: string
  nom: string
  nom_tri: string
}
interface Avertissement {
  id: string
  theme: string
  texte: string
  citation?: string
  langue_citation?: string
  source?: { url?: string }
}
interface Index {
  millesime: string
  source: string
  avertissement: string
  collecte_le?: string
  sources: Record<string, { dataset: string; unite: string; maj_eurostat: string; url: string }>
  agregats: { geo: string; nom: string }[]
  pays: Pays[]
  ordre?: { regle: string }
  unites?: Partial<Record<Unite, string>>
  depenses: { annees: number[]; fichiers: { code: string; nom: string; fichier: string }[] }
  prelevements: { annees: number[]; fichier: string }
  avertissements: Avertissement[]
}
interface Fonction {
  millesime: string
  source: string
  fonction: { code: string; nom: string }
  sous_fonctions: { code: string; nom: string }[]
  annees: number[]
  series: Record<string, Record<string, Serie>>
  statuts: Statuts
}
interface Prelevements {
  millesime: string
  source: string
  note?: string
  categories: { code: string; nom: string; parent: string | null }[]
  annees: number[]
  series: Record<string, Record<string, Serie>>
  statuts: Statuts
}
interface Valeurs {
  pct_pib: number | null
  eur_hab: number | null
  part_total: number | null
}
interface Fiche {
  id: string
  titre: string
  type: string
  codes: { code: string; nom: string }[]
  mode: string
  fichier: string
  annee: number
  pays_publies: number
  france: Valeurs
  ue27: Valeurs
  zone_euro?: Valeurs
  mediane_ue_pct_pib: number | null
  voir_aussi?: { code: string; nom: string; annee: number; france: Valeurs; ue27: Valeurs }[]
  avertissements?: string[]
}
interface Fiches {
  millesime: string
  source: string
  avertissement: string
  fiches: Fiche[]
}

/** La classification des dépenses par fonction (COFOG), en mots de tous les jours. */
export const FONCTIONS_EXPLIQUEES: Record<string, string> = {
  TOTAL: 'Toutes les dépenses des administrations publiques : État, Sécurité sociale, collectivités locales et organismes qui en dépendent.',
  GF01: 'Fonctionnement des institutions (assemblées, administrations centrales), collecte des impôts, relations avec l’étranger, aide au développement, intérêts de la dette publique.',
  GF02: 'Armées, défense civile, aide militaire à l’étranger, recherche de défense.',
  GF03: 'Police, gendarmerie, pompiers, tribunaux, prisons.',
  GF04: 'Transports, énergie, agriculture, industrie, aides aux entreprises et à l’emploi, recherche appliquée.',
  GF05: 'Collecte et traitement des déchets, eaux usées, lutte contre la pollution, protection de la nature.',
  GF06: 'Construction et aménagement de logements, eau potable, éclairage public, urbanisme. Les aides au logement versées aux ménages sont rangées en protection sociale.',
  GF07: 'Hôpitaux, soins de ville, médicaments et appareils remboursés, prévention et santé publique.',
  GF08: 'Sport, culture, audiovisuel public, édition, cultes.',
  GF09: 'Écoles, collèges, lycées, universités, formation, bourses et restauration scolaire.',
  GF10: 'Retraites, maladie et invalidité, famille et enfants, chômage, aides au logement, lutte contre l’exclusion.',
}

const UNITES: { cle: Unite; libelle: string; entete: string }[] = [
  { cle: 'pct_pib', libelle: 'En part de la richesse produite (% du PIB)', entete: '% du PIB' },
  { cle: 'eur_hab', libelle: 'En euros par habitant', entete: 'euros par habitant' },
  { cle: 'part_total', libelle: 'En part du total (des dépenses ou des prélèvements)', entete: '% du total' },
]
const ORDRES = [
  { cle: 'alpha', libelle: 'Ordre alphabétique' },
  { cle: 'valeur', libelle: 'Valeur, de la plus haute à la plus basse' },
]

const nb = (v: number) => (Math.round(v * 10) === v * 10 ? pct(v, 1) : pct(v, 2))
/** Une valeur dans son unité ; null reste « non publiée », jamais 0. */
export function valeurTexte(v: number | null | undefined, u: Unite): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return 'non publiée'
  return u === 'eur_hab' ? eur(v) : nb(v)
}
/** Statut publié par Eurostat pour une valeur : provisoire (p), rupture de série (b), ou non publiée. */
export function statutTexte(statuts: Statuts | undefined, geo: string, code: string, annee: number, v: number | null | undefined): string {
  if (v === null || v === undefined) return 'non publiée'
  const s = statuts?.[geo]?.[code]
  const mots = [s?.p?.includes(annee) ? 'provisoire' : '', s?.b?.includes(annee) ? 'rupture de série' : ''].filter(Boolean)
  return mots.length ? mots.join(', ') : 'publiée'
}

interface Vue {
  /** code de la série dans le fichier */
  code: string
  nom: string
  type: 'depense' | 'prelevement'
  explication: string
  fichier: Fonction | Prelevements | null
  sousCodes: { code: string; nom: string }[]
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const [idx, fiches, total, prel] = await Promise.all([
    chargerSiPresent<Index>('comparaison/index.json'),
    chargerSiPresent<Fiches>('comparaison/fiches.json'),
    chargerSiPresent<Fonction>('comparaison/depenses/TOTAL.json'),
    chargerSiPresent<Prelevements>('comparaison/prelevements.json'),
  ])
  const titre = '<h1>La France et les autres pays de l’Union</h1>'
  const renvoiUe = `<p>Cette page compare les pays entre eux. Ce que la France verse au budget de l’Union européenne, et ce qui revient en France, est un autre sujet : <a href="${lien('/explorer/ue')}">La France et l’Union européenne</a>.</p>`
  if (!idx) {
    cible.innerHTML = `${titre}${absent('Données en cours d’intégration.')}${renvoiUe}`
    return
  }

  // Choix lus dans l'adresse, chacun vérifié contre la liste des valeurs possibles.
  const codesDep = idx.depenses.fichiers.map((f) => f.code)
  const categories = prel?.categories ?? []
  const codePo = categories.find((c) => c.parent === null && c.code.includes('_'))?.code ?? categories[0]?.code
  const demande = params.get('p') ?? 'TOTAL'
  const codePrel = demande === ALIAS_PO ? codePo : categories.find((c) => c.code === demande && c.code !== codePo)?.code
  const type: 'depense' | 'prelevement' = codePrel ? 'prelevement' : 'depense'
  const codeDep = codesDep.includes(demande) ? demande : 'TOTAL'

  let vue: Vue
  if (type === 'prelevement') {
    const cat = categories.find((c) => c.code === codePrel)!
    vue = {
      code: cat.code,
      nom: cat.code === codePo ? 'Impôts et cotisations sociales obligatoires (total)' : cat.nom,
      type,
      explication: prel?.note ?? '',
      fichier: prel,
      sousCodes: [],
    }
  } else {
    const f = idx.depenses.fichiers.find((x) => x.code === codeDep)!
    const fichier = codeDep === 'TOTAL' ? total : await chargerSiPresent<Fonction>(f.fichier)
    vue = {
      code: codeDep,
      nom: codeDep === 'TOTAL' ? 'Dépense publique totale' : f.nom,
      type,
      explication: FONCTIONS_EXPLIQUEES[codeDep] ?? '',
      fichier,
      sousCodes: (fichier as Fonction | null)?.sous_fonctions ?? [],
    }
  }

  const serie = (geo: string, code: string, u: Unite) => vue.fichier?.series[geo]?.[code]?.[u]
  const annees = vue.fichier?.annees ?? []
  const val = (geo: string, code: string, u: Unite, a: number) => {
    const i = annees.indexOf(a)
    return i < 0 ? null : (serie(geo, code, u)?.[i] ?? null)
  }
  // Unités où la France a au moins une valeur (la part du total n'existe pas pour un total).
  const unitesDispo = UNITES.filter(
    (u) => !(vue.type === 'prelevement' && vue.code === codePo && u.cle === 'part_total') && (serie(FR, vue.code, u.cle) ?? []).some((x) => x !== null),
  )
  const uDemandee = params.get('u') as Unite | null
  const unite: Unite = unitesDispo.find((u) => u.cle === uDemandee)?.cle ?? unitesDispo[0]?.cle ?? 'pct_pib'
  const uInfo = UNITES.find((u) => u.cle === unite)!
  const anneesFr = annees.filter((a) => val(FR, vue.code, unite, a) !== null)
  const aDemandee = Number(params.get('a'))
  const annee = annees.includes(aDemandee) ? aDemandee : (anneesFr[anneesFr.length - 1] ?? annees[annees.length - 1])
  const ordre = params.get('o') === 'valeur' ? 'valeur' : 'alpha'

  cible.innerHTML = `
${titre}
<p class="chapeau">La dépense publique et les impôts et cotisations obligatoires de la France et des 26 autres pays de l’Union européenne, avec les mêmes séries d’Eurostat, l’office statistique de l’Union, pour chaque pays.</p>
${renvoiUe}
${carteCle(fiches, total, prel)}
<h2>Comment lire ces chiffres</h2>
<ul>
  <li><strong>En part de la richesse produite</strong> : le montant divisé par le produit intérieur brut (PIB) du pays la même année. 50 % veut dire 50 € sur 100 € de richesse produite.</li>
  <li><strong>En euros par habitant</strong> : le montant divisé par la population. Ce sont des euros courants, sans correction des écarts de prix entre pays : les fichiers du site ne contiennent pas de conversion en standard de pouvoir d’achat, l’unité d’Eurostat qui neutralise ces écarts. Un euro n’achète pas la même chose dans chaque pays.</li>
  <li><strong>En part du total</strong> : la part d’une fonction dans l’ensemble des dépenses publiques du pays, ou d’un impôt dans l’ensemble des prélèvements.</li>
  <li><strong>Statut</strong> : « publiée » pour une valeur sans indicateur, « provisoire » quand Eurostat la signale comme telle, « rupture de série » quand la méthode change cette année-là, « non publiée » quand la valeur manque (jamais remplacée par 0).</li>
</ul>
<p class="aide">${h(idx.avertissement)}</p>
${tableauFiches(fiches, total, prel)}
<h2 id="choisir">Tous les pays, fonction par fonction</h2>
<p>Les dépenses sont rangées selon la classification internationale des dépenses publiques par fonction (dite COFOG), la même dans tous les pays de l’Union : dix grandes fonctions, chacune découpée en groupes.</p>
${formulaire(idx, prel, vue, codePo, unitesDispo, unite, annees, annee, ordre)}
${
  vue.fichier
    ? `<h3>${h(vue.nom)}, ${h(uInfo.entete)}, ${annee}</h3>
${vue.explication ? `<p class="aide">${h(vue.explication)}</p>` : ''}
${tableauPays(idx, vue, unite, annee, ordre, val)}
${vue.sousCodes.length ? tableauGroupes(vue, unite, annee, val) : ''}
${tableauAnnees(idx, vue, unite, annees, val)}
${source(vue.fichier.source, vue.fichier.millesime)}`
    : absent(`${vue.nom} : fichier non disponible pour l’instant. Les autres fonctions restent consultables.`)
}
${limites(idx)}
<h2>Sources</h2>
<ul>${Object.values(idx.sources)
    .map((s) => `<li>Eurostat, jeu ${h(s.dataset)}, mis à jour par Eurostat le ${h(s.maj_eurostat)}</li>`)
    .join('')}</ul>
${source(idx.source, idx.collecte_le ? `collecté le ${idx.collecte_le}` : idx.millesime)}
<p class="liens-sortie"><a href="${lien('/explorer/ue')}">Ce que la France verse au budget de l’Union européenne</a></p>
<p class="liens-sortie"><a href="${lien('/explorer/recettes')}">Les recettes publiques en France, impôt par impôt</a></p>
${partPersonnelle()}`

  const form = cible.querySelector<HTMLFormElement>('#choix-comparaison')
  form?.addEventListener('change', () => {
    const v = (id: string) => form.querySelector<HTMLSelectElement>(`#${id}`)?.value
    const courant = (id: string) => new URLSearchParams(form.querySelector<HTMLAnchorElement>(`#${id} [aria-current="page"]`)?.hash.split('?')[1] ?? '')
    location.hash = lien(CHEMIN, { p: v('cmp-poste'), u: courant('cmp-unite').get('u') ?? undefined, a: v('cmp-annee'), o: courant('cmp-ordre').get('o') ?? undefined })
  })
  form?.addEventListener('submit', (e) => e.preventDefault())
}

function carteCle(fiches: Fiches | null, total: Fonction | null, prel: Prelevements | null): string {
  const dep = fiches?.fiches.find((f) => f.id === 'depenses_totales')
  const po = fiches?.fiches.find((f) => f.id === 'prelevements_obligatoires')
  if (!dep || dep.france.eur_hab === null || dep.france.pct_pib === null) return ''
  const stDep = statutTexte(total?.statuts, FR, 'TOTAL', dep.annee, dep.france.pct_pib)
  const stPo = po ? statutTexte(prel?.statuts, FR, po.codes[0]?.code ?? '', po.annee, po.france.pct_pib) : ''
  return `<div class="carte" data-cle>
  <p class="grand-chiffre">${surligne(`${eur(dep.france.eur_hab)} par habitant`)}</p>
  <p class="sous-chiffre">de dépense publique en France en ${dep.annee} (toutes administrations publiques), soit ${h(sur100(dep.france.pct_pib))} sur 100 € de richesse produite. Statut : ${h(stDep)}.</p>
  <p>Union européenne à 27, même année : ${h(valeurTexte(dep.ue27.pct_pib, 'pct_pib'))} de la richesse produite, ${h(valeurTexte(dep.ue27.eur_hab, 'eur_hab'))} par habitant.</p>
  ${
    po && po.france.pct_pib !== null
      ? `<p>Impôts et cotisations sociales obligatoires en ${po.annee} : ${h(valeurTexte(po.france.pct_pib, 'pct_pib'))} de la richesse produite en France (${h(valeurTexte(po.france.eur_hab, 'eur_hab'))} par habitant, statut : ${h(stPo)}) ; Union européenne à 27 : ${h(valeurTexte(po.ue27.pct_pib, 'pct_pib'))} (${h(valeurTexte(po.ue27.eur_hab, 'eur_hab'))} par habitant).</p>`
      : ''
  }
  ${source(fiches!.source, fiches!.millesime)}
</div>`
}

function tableauFiches(fiches: Fiches | null, total: Fonction | null, prel: Prelevements | null): string {
  if (!fiches) return ''
  const lignes = fiches.fiches.flatMap((f) => {
    // Lien vers la fonction entière (division) qui contient le poste ; les prélèvements vers leur total.
    const estPrel = f.fichier.includes('prelevements')
    const code = estPrel ? ALIAS_PO : (/depenses\/(\w+)\.json$/.exec(f.fichier)?.[1] ?? 'TOTAL')
    // Statut de la France : indicateurs du total des dépenses (mêmes années provisoires pour chaque fonction) ou des prélèvements.
    const st = estPrel ? statutTexte(prel?.statuts, FR, f.codes[0]?.code ?? '', f.annee, f.france.pct_pib) : statutTexte(total?.statuts, FR, 'TOTAL', f.annee, f.france.pct_pib)
    const ligne = (nom: string, a: number, fr: Valeurs, ue: Valeurs, med: number | null | undefined, statut: string) =>
      `<tr><th scope="row">${nom}</th><td class="nombre">${a}</td><td class="nombre">${h(valeurTexte(fr.pct_pib, 'pct_pib'))}</td><td class="nombre">${h(valeurTexte(fr.eur_hab, 'eur_hab'))}</td><td class="nombre">${h(valeurTexte(ue.pct_pib, 'pct_pib'))}</td><td class="nombre">${med === undefined ? '–' : h(valeurTexte(med, 'pct_pib'))}</td><td>${h(statut)}</td></tr>`
    return [
      ligne(`<a href="${lien(CHEMIN, { p: code })}">${h(f.titre)}</a>`, f.annee, f.france, f.ue27, f.mediane_ue_pct_pib, st),
      ...(f.voir_aussi ?? []).map((v) => ligne(`${h(v.nom)}, publié à côté de « ${h(f.titre)} »`, v.annee, v.france, v.ue27, undefined, statutTexte(total?.statuts, FR, 'TOTAL', v.annee, v.france.pct_pib))),
    ]
  })
  return `<h2>Repères par grand poste</h2>
<div class="tableau-defile"><table class="tableau-comparaison">
<caption>France, Union européenne à 27 et médiane des 27 pays, dernière année publiée</caption>
<thead><tr><th scope="col">Poste</th><th scope="col" class="nombre">Année</th><th scope="col" class="nombre">France, % du PIB</th><th scope="col" class="nombre">France, euros par habitant</th><th scope="col" class="nombre">Union à 27, % du PIB</th><th scope="col" class="nombre">Médiane des 27 pays, % du PIB</th><th scope="col">Statut (France)</th></tr></thead>
<tbody>${lignes.join('')}</tbody></table></div>
<p class="aide">Union à 27 : ensemble des 27 pays, calculé par Eurostat (chaque pays compte selon sa taille). Médiane : la valeur du milieu quand les 27 pays sont rangés par valeur, chacun comptant pour un. Les postes ne s’additionnent pas : certains sont des groupes à l’intérieur d’une fonction (retraites, transports, intérêts de la dette).</p>
${source(fiches.source, fiches.millesime)}`
}

function formulaire(idx: Index, prel: Prelevements | null, vue: Vue, codePo: string | undefined, unites: typeof UNITES, unite: Unite, annees: number[], annee: number, ordre: string): string {
  const sel = (c: boolean) => (c ? ' selected' : '')
  const courant = vue.type === 'prelevement' ? (vue.code === codePo ? ALIAS_PO : vue.code) : vue.code
  const optDep = idx.depenses.fichiers
    .map((f) => `<option value="${h(f.code)}"${sel(f.code === courant)}>${h(f.code === 'TOTAL' ? 'Dépense publique totale' : f.nom)}</option>`)
    .join('')
  const optPrel = (prel?.categories ?? [])
    .map((c) => {
      const v = c.code === codePo ? ALIAS_PO : c.code
      return `<option value="${h(v)}"${sel(v === courant)}>${h(c.code === codePo ? 'Impôts et cotisations sociales obligatoires (total)' : c.nom)}</option>`
    })
    .join('')
  return `<form id="choix-comparaison" class="carte">
  ${listeRecherche({ id: 'cmp-poste', etiquette: 'Poste', options: [], optionsHtml: `<optgroup label="Dépenses publiques par fonction">${optDep}</optgroup>${optPrel ? `<optgroup label="Impôts et cotisations obligatoires">${optPrel}</optgroup>` : ''}` })}
  ${choixLiens({ id: 'cmp-unite', etiquette: 'Unité', liens: unites.map((u) => ({ href: lien(CHEMIN, { p: courant, u: u.cle, a: annee, o: ordre }), libelle: u.libelle, courant: u.cle === unite })) })}
  ${listeRecherche({ id: 'cmp-annee', etiquette: 'Année', options: [], optionsHtml: `${[...annees]
    .reverse()
    .map((a) => `<option value="${a}"${sel(a === annee)}>${a}</option>`)
    .join('')}` })}
  ${choixLiens({ id: 'cmp-ordre', etiquette: 'Ordre des pays', liens: ORDRES.map((o) => ({ href: lien(CHEMIN, { p: courant, u: unite, a: annee, o: o.cle }), libelle: o.libelle, courant: o.cle === ordre })) })}
</form>`
}

type Lecteur = (geo: string, code: string, u: Unite, a: number) => number | null

function tableauPays(idx: Index, vue: Vue, unite: Unite, annee: number, ordre: string, val: Lecteur): string {
  const lignes = idx.pays.map((p) => ({ ...p, v: val(p.geo, vue.code, unite, annee) }))
  if (ordre === 'valeur') lignes.sort((a, b) => (b.v ?? -Infinity) - (a.v ?? -Infinity) || a.nom_tri.localeCompare(b.nom_tri))
  else lignes.sort((a, b) => a.nom_tri.localeCompare(b.nom_tri))
  const max = Math.max(0, ...lignes.map((l) => l.v ?? 0))
  const statuts = vue.fichier?.statuts
  const regle =
    ordre === 'valeur'
      ? 'Ordre : valeur décroissante, puis ordre alphabétique en cas d’égalité ; les valeurs non publiées en fin de liste. Une position décrit un niveau, pas un jugement.'
      : 'Ordre : alphabétique, d’après le nom du pays en français.'
  const ligne = (geo: string, nom: string, v: number | null, france = false) =>
    `<tr${france ? ' class="repere-france"' : ''}><th scope="row">${h(nom)}${france ? ' <span class="badge">repère</span>' : ''}</th><td class="nombre">${h(valeurTexte(v, unite))}</td><td class="barre-cellule"><span class="barre" aria-hidden="true"><span class="barre-remplissage" data-l="${(max > 0 && v !== null ? Math.max(0, Math.min(100, (v / max) * 100)) : 0).toFixed(2)}"></span></span></td><td>${h(statutTexte(statuts, geo, vue.code, annee, v))}</td></tr>`
  const agregats = idx.agregats
    .map((a) => ({ ...a, v: val(a.geo, vue.code, unite, annee) }))
    .map((a) => `<tr><th scope="row">${h(a.nom)}</th><td class="nombre">${h(valeurTexte(a.v, unite))}</td><td>${h(statutTexte(statuts, a.geo, vue.code, annee, a.v))}</td></tr>`)
    .join('')
  return `<div class="tableau-defile"><table class="tableau-comparaison">
<caption>${h(vue.nom)} en ${annee}, ${h(UNITES.find((u) => u.cle === unite)!.entete)}, 27 pays de l’Union</caption>
<thead><tr><th scope="col">Pays</th><th scope="col" class="nombre">Valeur</th><th scope="col"><span class="visuellement-cache">Barre proportionnelle</span></th><th scope="col">Statut</th></tr></thead>
<tbody>${lignes.map((l) => ligne(l.geo, l.nom, l.v, l.geo === FR)).join('')}</tbody></table></div>
<p class="aide">${h(regle)} La France est repérée par le mot « repère » et un trait, sans couleur propre. Les barres sont à la même échelle pour tous les pays.</p>
<div class="tableau-defile"><table>
<caption>Ensembles calculés par Eurostat, ${annee}</caption>
<thead><tr><th scope="col">Ensemble</th><th scope="col" class="nombre">Valeur</th><th scope="col">Statut</th></tr></thead>
<tbody>${agregats}</tbody></table></div>
<p class="aide">Les indicateurs « provisoire » des ensembles européens ne figurent pas dans les séries du site : Eurostat les donne dans ses métadonnées (voir « Chiffres provisoires et changements de méthode », plus bas).</p>`
}

function tableauGroupes(vue: Vue, unite: Unite, annee: number, val: Lecteur): string {
  const statuts = vue.fichier?.statuts
  return `<details><summary>Le détail de ${h(vue.nom.toLowerCase())}, groupe par groupe</summary>
<div class="tableau-defile"><table>
<caption>Groupes de la fonction « ${h(vue.nom)} » en ${annee}, ${h(UNITES.find((u) => u.cle === unite)!.entete)}</caption>
<thead><tr><th scope="col">Groupe</th><th scope="col" class="nombre">France</th><th scope="col">Statut (France)</th><th scope="col" class="nombre">Union à 27</th></tr></thead>
<tbody>${vue.sousCodes
    .map((s) => {
      const fr = val(FR, s.code, unite, annee)
      return `<tr><th scope="row">${h(s.nom)}</th><td class="nombre">${h(valeurTexte(fr, unite))}</td><td>${h(statutTexte(statuts, FR, s.code, annee, fr))}</td><td class="nombre">${h(valeurTexte(val(UE27, s.code, unite, annee), unite))}</td></tr>`
    })
    .join('')}</tbody></table></div>
<p class="aide">« n.c.a. » : non classé ailleurs, ce qui relève de la fonction sans entrer dans un autre groupe.</p></details>`
}

function tableauAnnees(idx: Index, vue: Vue, unite: Unite, annees: number[], val: Lecteur): string {
  const nomAgregat = (geo: string) => idx.agregats.find((a) => a.geo === geo)?.nom ?? geo
  const statuts = vue.fichier?.statuts
  return `<details><summary>${h(vue.nom)} : toutes les années, France et ensembles européens</summary>
<div class="tableau-defile"><table>
<caption>${h(vue.nom)}, ${h(UNITES.find((u) => u.cle === unite)!.entete)}, de ${annees[0]} à ${annees[annees.length - 1]}</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">France</th><th scope="col">Statut (France)</th><th scope="col" class="nombre">${h(nomAgregat(UE27))}</th><th scope="col" class="nombre">${h(nomAgregat(ZONE_EURO))}</th></tr></thead>
<tbody>${[...annees]
    .reverse()
    .map((a) => {
      const fr = val(FR, vue.code, unite, a)
      return `<tr><th scope="row">${a}</th><td class="nombre">${h(valeurTexte(fr, unite))}</td><td>${h(statutTexte(statuts, FR, vue.code, a, fr))}</td><td class="nombre">${h(valeurTexte(val(UE27, vue.code, unite, a), unite))}</td><td class="nombre">${h(valeurTexte(val(ZONE_EURO, vue.code, unite, a), unite))}</td></tr>`
    })
    .join('')}</tbody></table></div></details>`
}

const THEMES: Record<string, string> = {
  'périmètres': 'Ce que chaque pays range dans ses dépenses publiques',
  'prestations fiscalisées': 'Prestations comptées avant impôt',
  'systèmes de retraite': 'Des systèmes de retraite différents',
  'révisions': 'Chiffres provisoires et changements de méthode',
}

function limites(idx: Index): string {
  const themes = [...new Set(idx.avertissements.map((a) => a.theme))]
  return `<h2>Limites de la comparaison</h2>
<p>Les pays n’organisent pas leurs services publics de la même façon. Un écart entre deux pays peut venir de ce qui est compté comme public, et pas seulement d’un niveau de service différent.</p>
<ul>
  <li><strong>Retraites</strong> : selon les pays, les pensions passent surtout par des régimes publics (comptés ici) ou par des régimes privés, obligatoires ou non (absents ici). La dépense publique de retraite ne mesure donc pas toutes les pensions versées.</li>
  <li><strong>Santé</strong> : seule la dépense des administrations publiques est comptée. Les soins payés directement par les ménages ou par des assurances complémentaires n’y figurent pas, et leur part varie d’un pays à l’autre.</li>
  <li><strong>Périmètre</strong> : le partage des tâches entre État, régions, communes, Sécurité sociale et organismes privés diffère d’un pays à l’autre ; Eurostat demande d’en tenir compte.</li>
</ul>
${themes
  .map(
    (t) => `<h3>${h(THEMES[t] ?? t.charAt(0).toUpperCase() + t.slice(1))}</h3><ul>${idx.avertissements
      .filter((a) => a.theme === t)
      .map(
        (a) =>
          `<li>${h(a.texte)}${
            a.citation
              ? `<details><summary>Texte publié par Eurostat${a.langue_citation === 'en' ? ' (en anglais)' : ''}</summary><blockquote${a.langue_citation ? ` lang="${h(a.langue_citation)}"` : ''}>${h(a.citation)}</blockquote>${a.source?.url ? `<p class="source">${h(a.source.url)}</p>` : ''}</details>`
              : ''
          }</li>`,
      )
      .join('')}</ul>`,
  )
  .join('')}`
}

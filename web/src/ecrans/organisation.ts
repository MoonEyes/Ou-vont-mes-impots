// Une organisation dans toutes les sources du site (site/data/entites/, produit par pipeline/entites.py) : recherche
// par nom ou par SIREN, puis fiche « tout ce qu'elle reçoit de l'argent public, source par source, année par année ».
// Règles reprises des données : une organisation n'est reliée d'une source à l'autre que par son SIREN ; les montants
// de sources différentes n'ont pas la même définition et ne s'additionnent jamais ; une somme n'est affichée que pour
// des lignes d'une même source, d'une même année et d'une même notion de montant, avec la mention « calculé par le
// site » ; une ligne publiée sans SIREN et rattachée par le nom et le département est affichée à part, avec son
// score, jamais fusionnée. Seules des personnes morales sont nommées.
import { mots } from '../composants/recherche'
import { partPersonnelle } from '../composants/hub'
import { chargerSiPresent, urlDonnee } from '../donnees'
import { lien, type Rendu } from '../routeur'
import { ROUTES } from '../routes'
import { absent, badgeStatut, entier, eur, eur2, h, legendeStatuts, source, surligne, badgeCalcule } from '../util'

type Valeur = [number | string | null, number | null]
interface Serie {
  precision: string
  lien?: string
  statut?: 'approche'
  valeurs: Valeur[]
}
interface Bloc {
  canal: string
  notion: string
  fichiers: string[]
  nombre_lignes: number
  sommes_par_annee?: [number, number, number, string?][]
  series_non_affichees?: { nombre: number; regle: string }
  series: Serie[]
}
interface Probable {
  canal: string
  notion: string
  nom_publie: string
  departement: string
  score: number
  decision: 'probable'
  precision: string
  lien?: string | null
  annee?: number | null
}
export interface Fiche {
  siren: string
  denomination: string
  categorie_juridique: string
  departements: string[]
  canaux: string[]
  recoit: Bloc[]
  autres: Bloc[]
  sommes_entre_canaux?: { annee: number; groupe: string; montant_eur: number; canaux: string[]; statut: string }[]
  probables?: Probable[]
}
interface Canal {
  id: string
  titre: string
  chemins_source: string
  axe: string
  page: string | null
  organisations: number
  organisations_avec_fiche: number
  lignes: number
  notions: string[]
}
export interface Index {
  millesime: string
  source: string
  avertissement: string
  regle_personnes: string
  methode: { etapes: string[]; splink: { seuil_probable: number; seuil_incertain: number; version?: string }; modele: string }
  notions: Record<string, { libelle: string; sens: 'recoit' | 'verse' | 'mention'; somme_canal: boolean; cumulable_entre_canaux: string | null }>
  canaux: Canal[]
  comptes: {
    organisations_reliees_par_siren: number
    organisations_avec_fiche: number
    regle_fiche?: string
    par_nombre_de_canaux: Record<string, number>
    exclusions: Record<string, number>
    lignes_sans_siren: { total: number; decisions: Record<string, number> }
  }
  fichiers: { fiches: Record<string, string>; recherche: Record<string, string>; recherche_entrees?: Record<string, number>; mots_frequents: { mot: string; organisations: number }[] }
  ordre: { regle: string }
  limites: string[]
  recherche_publique: { date: string; trouvailles: { nom: string; url: string; licence: string; verdict: string }[] }
}
interface FichierFiches {
  fiches: Record<string, Fiche>
}
interface FichierRecherche {
  entrees: [string, string, number, string | null][]
}

const PAGE = '/beneficiaires/organisation'
/** Ordre des résultats et des lignes, écrit sous chaque liste. */
export const REGLE_RESULTATS = 'Résultats par ordre alphabétique de la dénomination, puis par SIREN ; aucun classement par montant.'
export const REGLE_LIGNES = 'Lignes par année croissante (périodes pluriannuelles ensuite), puis par montant publié décroissant à l’intérieur d’une même année.'
const MAX_RESULTATS = 50
const MAX_FICHIERS_RECHERCHE = 4
const MAX_LIGNES_VISIBLES = 25
const MOTS_VIDES = new Set(['de', 'du', 'des', 'la', 'le', 'les', 'l', 'd', 'et', 'a', 'au', 'aux', 'en', 'pour', 'sur', 'the', 'of'])


/** Montant tel que publié : à l'euro, centimes gardés quand la source en publie. */
export const montantPublie = (x: number) => (Number.isInteger(x) ? eur(x) : eur2(x))

/** SIREN lisible : « 130 006 372 ». */
export const sirenLisible = (s: string) => s.replace(/^(\d{3})(\d{3})(\d{3})$/, '$1 $2 $3')

/** SIREN à 9 chiffres d'après une saisie (espaces retirés ; un SIRET est ramené à son SIREN) ; null sinon. */
export function sirenSaisi(q: string): string | null {
  const t = q.replace(/[\s.]/g, '')
  if (/^\d{14}$/.test(t)) return t.slice(0, 9)
  return /^\d{9}$/.test(t) ? t : null
}

/** Forme juridique lisible d'après la catégorie juridique Insee. */
export function formeJuridique(cj: string): string {
  const noms: Record<string, string> = { '7210': 'commune', '7220': 'département', '7230': 'région' }
  if (noms[cj]) return noms[cj]
  if (cj.startsWith('71')) return 'service de l’État'
  if (cj.startsWith('72')) return 'collectivité territoriale'
  if (cj.startsWith('73')) return 'établissement public administratif ou groupement de collectivités'
  if (cj.startsWith('7')) return 'personne morale de droit public'
  if (cj.startsWith('41')) return 'établissement public industriel et commercial'
  if (cj.startsWith('92') || cj.startsWith('93')) return 'association'
  if (cj.startsWith('94')) return 'fondation ou fonds de dotation'
  if (cj.startsWith('5') || cj.startsWith('6')) return 'société'
  return 'personne morale'
}

/** Fichier de fiches d'un SIREN : le plus long préfixe présent dans l'index. */
export function fichierFiche(idx: Index, siren: string): string | null {
  const k = Object.keys(idx.fichiers.fiches)
    .filter((p) => siren.startsWith(p))
    .sort((a, b) => b.length - a.length)[0]
  return k ? idx.fichiers.fiches[k] : null
}

/** Nombre d'organisations des fichiers de recherche d'un mot (inconnu : compté comme très grand). */
function poidsMot(idx: Index, fichiers: string[]): number {
  const parFichier = new Map(Object.entries(idx.fichiers.recherche).map(([k, f]) => [f, idx.fichiers.recherche_entrees?.[k] ?? 1e6]))
  return fichiers.reduce((a, f) => a + (parFichier.get(f) ?? 1e6), 0)
}

/** Fichiers de recherche qui peuvent contenir un mot commençant par `w`. */
export function fichiersMot(idx: Index, w: string): string[] {
  const out = new Set<string>()
  const cles = Object.keys(idx.fichiers.recherche)
  const prefixes = cles.filter((k) => !k.endsWith('_') && w.startsWith(k)).sort((a, b) => b.length - a.length)
  if (prefixes[0]) out.add(idx.fichiers.recherche[prefixes[0]])
  for (const k of cles) {
    const base = k.endsWith('_') ? k.slice(0, -1) : k
    if (base.startsWith(w) && base !== prefixes[0]) out.add(idx.fichiers.recherche[k])
  }
  return [...out].sort()
}

/** Adresse d'une page du site si la route existe (sinon null : le site renvoie alors au fichier de données). */
function pageSiExiste(chemin: string | null | undefined): string | null {
  if (!chemin || !chemin.startsWith('/')) return null
  const [route, requete] = chemin.split('?')
  return ROUTES.some((r) => r.chemin === route) ? `#${route}${requete ? '?' + requete : ''}` : null
}

function lienLigne(l: string | null | undefined, texte: string): string {
  if (!l) return ''
  if (/^https:\/\/www\.ccomptes\.fr\//.test(l)) return ` <a href="${h(l)}" rel="noopener">${h(texte)} (ccomptes.fr)</a>`
  const p = pageSiExiste(l)
  return p ? ` <a href="${h(p)}">${h(texte)}</a>` : ''
}

const quand = (t: number | string | null) => (t === null ? 'année non publiée' : typeof t === 'number' ? String(t) : `période ${t.replace('-', ' à ')}`)

function canalDe(idx: Index, id: string): Canal | undefined {
  return idx.canaux.find((c) => c.id === id)
}

function renvoiSource(idx: Index, b: Bloc): string {
  const c = canalDe(idx, b.canal)
  const page = pageSiExiste(c?.page)
  const route = ROUTES.find((r) => r.chemin === c?.page)
  const fichiers = b.fichiers.map((f) => `<a href="${h(urlDonnee(f))}">${h(f)}</a>`).join(', ')
  return `<p class="source">Source : ${h(c?.titre ?? b.canal)}${page && route ? ` · page du site : <a href="${h(page)}">${h(route.court ?? route.titre)}</a>` : ''} · fichier${b.fichiers.length > 1 ? 's' : ''} de données : ${fichiers}</p>`
}

function tableBloc(idx: Index, b: Bloc, n: number): string {
  const notion = idx.notions[b.notion]
  const lignes: string[] = []
  for (const s of b.series)
    for (const [t, m] of s.valeurs) {
      const statut = m === null ? badgeStatut('nonpub') : badgeStatut(s.statut === 'approche' ? 'approche' : 'trace')
      lignes.push(
        `<tr><th scope="row">${h(quand(t))}</th><td class="nombre">${m === null ? 'non publié' : h(montantPublie(m))}</td><td>${h(s.precision)}${lienLigne(s.lien, 'voir')}</td><td>${statut}</td></tr>`,
      )
    }
  const tete = `<thead><tr><th scope="col">Année ou période</th><th scope="col" class="nombre">Montant tel que publié</th><th scope="col">Précision</th><th scope="col">Statut</th></tr></thead>`
  const legende = `${h(canalDe(idx, b.canal)?.titre ?? b.canal)} : ${h(notion?.libelle ?? b.notion)}`
  const visibles = lignes.slice(0, MAX_LIGNES_VISIBLES)
  const reste = lignes.slice(MAX_LIGNES_VISIBLES)
  let html = `<div class="tableau-defile"><table id="org-bloc-${n}"><caption>${legende}</caption>${tete}<tbody>${visibles.join('')}</tbody></table></div>`
  if (reste.length)
    html += `<details><summary>Voir les ${h(entier(reste.length))} autres lignes</summary><div class="tableau-defile"><table><caption>${legende} (suite)</caption>${tete}<tbody>${reste.join('')}</tbody></table></div></details>`
  if (b.series_non_affichees) html += `<p class="aide">${h(entier(b.series_non_affichees.nombre))} autres lignes : ${h(b.series_non_affichees.regle)}.</p>`
  if (b.sommes_par_annee?.length) {
    html += `<div class="tableau-defile"><table class="org-sommes"><caption>Sommes par année de cette source</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Somme</th><th scope="col">Méthode</th></tr></thead><tbody>${b.sommes_par_annee
      .map(
        ([an, somme, nb, groupe]) =>
          `<tr><th scope="row">${h(String(an))}</th><td class="nombre">${h(montantPublie(somme))}</td><td>${badgeCalcule(`somme de ${entier(nb)} lignes publiées de la même année, même source et même notion de montant${groupe ? ` (${groupe})` : ''}`)}</td></tr>`,
      )
      .join('')}</tbody></table></div>`
  }
  return html + renvoiSource(idx, b)
}

function sectionBlocs(idx: Index, blocs: Bloc[], depart: number): string {
  return blocs
    .map((b, i) => {
      const c = canalDe(idx, b.canal)
      return `<section class="carte carte-contour" aria-labelledby="org-titre-${depart + i}"><h3 id="org-titre-${depart + i}">${h(c?.titre ?? b.canal)}</h3><p>${h(majuscule(idx.notions[b.notion]?.libelle ?? b.notion))}.</p>${tableBloc(idx, b, depart + i)}</section>`
    })
    .join('')
}

const majuscule = (t: string) => (t ? t[0].toUpperCase() + t.slice(1) : t)

function sectionProbables(idx: Index, f: Fiche): string {
  const p = f.probables ?? []
  if (!p.length) return ''
  return `<h2>Rapprochements probables, non fusionnés</h2>
<p class="carte carte-contour" data-probables>Ces lignes sont publiées <strong>sans SIREN</strong>. Le site les rattache à cette organisation <strong>à titre probable</strong>, d’après le nom et le département, avec le score de vraisemblance ci-dessous (au moins ${h(String(idx.methode.splink.seuil_probable).replace('.', ','))} sur 1). Elles ne sont ni fusionnées avec les lignes reliées par le SIREN, ni additionnées.</p>
<div class="tableau-defile"><table id="org-probables"><caption>Lignes publiées sans SIREN, rattachées à titre probable</caption><thead><tr><th scope="col">Source</th><th scope="col">Nom publié</th><th scope="col">Département</th><th scope="col">Année</th><th scope="col">Précision</th><th scope="col" class="nombre">Score</th><th scope="col">Statut</th></tr></thead><tbody>${p
    .map(
      (x) =>
        `<tr><th scope="row">${h(canalDe(idx, x.canal)?.titre ?? x.canal)}</th><td>${h(x.nom_publie)}</td><td>${h(x.departement)}</td><td>${h(x.annee ? String(x.annee) : 'non publiée')}</td><td>${h(x.precision)}${lienLigne(x.lien, 'voir')}</td><td class="nombre">${h(x.score.toFixed(2).replace('.', ','))}</td><td>${badgeStatut('approche')}</td></tr>`,
    )
    .join('')}</tbody></table></div>`
}

function renduFiche(idx: Index, f: Fiche): string {
  const n = f.canaux.length
  const recoit = f.recoit
  const autres = f.autres
  const se = f.sommes_entre_canaux ?? []
  return `
<p class="aide"><a href="${h(lien(PAGE))}">Chercher une autre organisation</a></p>
<h1>${h(f.denomination)}</h1>
<p class="chapeau">Tout ce que cette organisation reçoit de l’argent public d’après les sources publiées sur le site, source par source et année par année, avec le montant tel que chaque source le publie. Les sources n’ont ni la même définition du montant (engagé, attribué, notifié, versé, programmé) ni la même période : leurs montants sont montrés côte à côte, jamais additionnés. Cette page ne montre pas ce que les sources ne publient pas : une absence ne veut pas dire qu’aucun montant n’a été reçu.</p>
<ul class="cles" aria-label="Identité de l’organisation">
  <li class="cle-famille"><strong>${surligne(`${entier(n)} source${n > 1 ? 's' : ''}`)}</strong><span>du site où figure cette organisation, reliées par son SIREN</span></li>
  <li><strong>${h(sirenLisible(f.siren))}</strong><span>SIREN · ${h(formeJuridique(f.categorie_juridique))} (catégorie juridique ${h(f.categorie_juridique)})</span></li>
  ${f.departements.length ? `<li><strong>${h(f.departements.slice(0, 6).join(', '))}${f.departements.length > 6 ? '…' : ''}</strong><span>département${f.departements.length > 1 ? 's' : ''} cité${f.departements.length > 1 ? 's' : ''} par les sources</span></li>` : ''}
</ul>
${legendeStatuts()}
<h2>Ce qu’elle reçoit, source par source</h2>
${recoit.length ? sectionBlocs(idx, recoit, 0) : absent('Aucune source du site ne publie de montant reçu par cette organisation.')}
<p class="aide" data-regle-ordre>${h(REGLE_LIGNES)}</p>
${
  se.length
    ? `<h3>Sommes de plusieurs sources</h3><ul>${se.map((x) => `<li>${h(String(x.annee))} : ${h(montantPublie(x.montant_eur))} (${h(x.canaux.join(', '))}) ${badgeCalcule('somme des montants de la même année et de la même notion de montant, publiés par chacune des sources citées')}</li>`).join('')}</ul>`
    : `<p class="aide" data-sans-somme>Aucune somme toutes sources confondues : les sources n’ont pas la même année, la même définition du montant ou le même périmètre. Une somme n’est calculée que pour des lignes d’une même source, d’une même année et d’une même notion de montant.</p>`
}
${autres.length ? `<h2>Autres mentions dans les sources du site</h2><p>Montants qu’elle verse (comme acheteur ou au budget de l’État) et mentions sans argent reçu (rapports de contrôle, répertoires, effectifs). Ils ne s’ajoutent pas à ce qu’elle reçoit.</p>${sectionBlocs(idx, autres, recoit.length)}` : ''}
${sectionProbables(idx, f)}
<h2>Comment la page est faite</h2>
<p>${h(idx.avertissement)}</p>
<details><summary>Méthode et limites</summary><ol>${idx.methode.etapes.map((e) => `<li>${h(e.replace(/^\d+\.\s*/, ''))}</li>`).join('')}</ol><ul>${idx.limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul><p class="aide">${h(idx.regle_personnes)}</p></details>
${source(idx.source, idx.millesime)}
<ul class="liens-sortie"><li><a href="#/beneficiaires">Qui reçoit l’argent : programmes et bénéficiaires</a></li><li><a href="#/explorer/secu">Les sommes versées aux ménages par la Sécurité sociale</a></li></ul>
${partPersonnelle()}`
}

function renduRecherche(idx: Index, q: string): string {
  const c = idx.comptes
  return `
<h1>Une organisation dans toutes les sources</h1>
<p class="chapeau">Cherche une association, une entreprise, une commune ou un établissement public par son nom ou son SIREN : sa fiche réunit ce qu’elle reçoit de l’argent public dans toutes les sources du site (subventions, crédits aux associations, marchés publics, aides aux entreprises, fonds européens, opérateurs, hôpitaux, recherche), source par source et année par année. Elle ne fait pas de total toutes sources confondues, et ne montre que ce qui est publié en données ouvertes. Seules les personnes morales sont nommées.</p>
<div class="carte" data-cle>
  <p class="grand-chiffre">${surligne(entier(c.organisations_avec_fiche))}</p>
  <p class="sous-chiffre">organisations ont une fiche : elles figurent dans au moins deux sources du site (ou dans une source et un rapprochement probable). ${h(entier(c.organisations_reliees_par_siren))} organisations au total sont reliées par leur SIREN ; celles qui ne figurent que dans une source sont sur la page de cette source.</p>
</div>
<form id="org-form" class="carte" role="search" aria-label="Chercher une organisation">
  <label for="org-q">Nom ou SIREN de l’organisation</label>
  <input id="org-q" name="q" type="search" autocomplete="off" value="${h(q)}" />
  <button type="submit" class="bouton">Chercher</button>
</form>
<p id="org-statut" class="aide" aria-live="polite"></p>
<div id="org-resultats"><p>Écris au moins trois lettres d’un mot du nom, ou les 9 chiffres du SIREN.</p></div>
<h2>Les sources reliées</h2>
<div class="tableau-defile"><table id="org-canaux"><caption>Sources du site relues pour relier les organisations</caption><thead><tr><th scope="col">Source</th><th scope="col" class="nombre">Organisations reliées</th><th scope="col" class="nombre">dont avec une fiche</th><th scope="col">Page du site</th></tr></thead><tbody>${idx.canaux
    .map((k) => {
      const p = pageSiExiste(k.page)
      return `<tr><th scope="row">${h(k.titre)}</th><td class="nombre">${h(entier(k.organisations))}</td><td class="nombre">${h(entier(k.organisations_avec_fiche))}</td><td>${p ? `<a href="${h(p)}">${h(ROUTES.find((r) => r.chemin === k.page)?.court ?? 'voir')}</a>` : 'pas encore de page'}</td></tr>`
    })
    .join('')}</tbody></table></div>
<p class="aide">Ordre des sources : celui de l’index publié (familles de sources), sans classement.</p>
<h2>Comment les organisations sont reliées</h2>
<p>${h(idx.avertissement)}</p>
<ol>${idx.methode.etapes.map((e) => `<li>${h(e.replace(/^\d+\.\s*/, ''))}</li>`).join('')}</ol>
<p>Lignes publiées sans SIREN : ${h(entier(c.lignes_sans_siren.total))}, dont ${h(entier(c.lignes_sans_siren.decisions.probable ?? 0))} rattachées à titre probable, ${h(entier(c.lignes_sans_siren.decisions.incertain ?? 0))} incertaines (non affichées), ${h(entier(c.lignes_sans_siren.decisions.different ?? 0))} sans correspondance et ${h(entier(c.lignes_sans_siren.decisions.non_rapprochable ?? 0))} sans département ou dont le nom peut être celui d’une personne.</p>
<p class="aide">${h(idx.regle_personnes)} Organisations écartées : ${h(
    Object.entries(c.exclusions)
      .map(([k, v]) => `${entier(v)} (${MOTIFS[k] ?? k.replace(/_/g, ' ')})`)
      .join(', ') || 'aucune',
  )}.</p>
<details><summary>Limites</summary><ul>${idx.limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul></details>
<details><summary>Outils publics réutilisés</summary><ul>${idx.recherche_publique.trouvailles.map((t) => `<li>${h(t.nom)} (${h(t.licence)}) : ${h(t.verdict)}</li>`).join('')}</ul></details>
${source(idx.source, idx.millesime)}
<ul class="liens-sortie"><li><a href="#/beneficiaires">Qui reçoit l’argent : programmes et bénéficiaires</a></li><li><a href="#/explorer/secu">Les sommes versées aux ménages par la Sécurité sociale</a></li></ul>
${partPersonnelle()}`
}

const MOTIFS: Record<string, string> = {
  nom_de_personne_possible: 'nom qui peut être celui d’une personne',
  diffusion_partielle: 'diffusion partielle au répertoire SIRENE',
  personne_physique_ou_groupement: 'personne physique ou groupement de personnes physiques',
  categorie_inconnue: 'catégorie juridique inconnue',
  sans_denomination: 'sans dénomination',
  sans_siren_valide: 'sans SIREN valide',
}

/** Cherche les organisations dont chaque mot saisi commence un mot du nom. */
export async function chercher(idx: Index, q: string): Promise<{ resultats: FichierRecherche['entrees']; message: string | null }> {
  const frequents = new Set(idx.fichiers.mots_frequents.map((m) => m.mot))
  const ms = mots(q).filter((m) => m.length >= 2 && !MOTS_VIDES.has(m))
  if (!ms.some((m) => m.length >= 3)) return { resultats: [], message: 'Écris au moins trois lettres d’un mot du nom, ou les 9 chiffres du SIREN.' }
  const candidats = ms
    .filter((m) => !frequents.has(m))
    .map((m) => ({ m, f: fichiersMot(idx, m) }))
    .filter((x) => x.f.length > 0)
    .sort((a, b) => poidsMot(idx, a.f) - poidsMot(idx, b.f) || b.m.length - a.m.length || a.m.localeCompare(b.m))
  if (!candidats.length)
    return { resultats: [], message: ms.some((m) => frequents.has(m)) ? 'Ce mot figure dans le nom de plusieurs milliers d’organisations : ajoute un autre mot du nom (par exemple la commune).' : null }
  const choix = candidats[0]
  if (choix.f.length > MAX_FICHIERS_RECHERCHE) return { resultats: [], message: 'Précise un peu plus le mot (une ou deux lettres de plus).' }
  const fichiers = await Promise.all(choix.f.map((f) => chargerSiPresent<FichierRecherche>(f)))
  const vus = new Map<string, FichierRecherche['entrees'][number]>()
  for (const fr of fichiers) for (const e of fr?.entrees ?? []) vus.set(e[0], e)
  const resultats = [...vus.values()]
    .filter((e) => {
      const nom = mots(e[1])
      return ms.every((w) => nom.some((x) => x.startsWith(w)))
    })
    .sort((a, b) => a[1].localeCompare(b[1], 'fr') || a[0].localeCompare(b[0]))
  return { resultats, message: null }
}

function listeResultats(r: FichierRecherche['entrees']): string {
  if (!r.length)
    return `<p>Aucune organisation trouvée parmi celles qui ont une fiche. Une organisation présente dans une seule source du site n’a pas de fiche : elle figure sur la page de cette source (tableau « Les sources reliées » ci-dessous).</p>`
  return `<p>${h(entier(r.length))} organisation${r.length > 1 ? 's' : ''} trouvée${r.length > 1 ? 's' : ''}${r.length > MAX_RESULTATS ? `, ${MAX_RESULTATS} premières affichées` : ''}.</p><ul class="lignes" id="org-liste">${r
    .slice(0, MAX_RESULTATS)
    .map((e) => `<li><a href="${h(lien(PAGE, { siren: e[0] }))}">${h(e[1])}</a> <span class="aide">SIREN ${h(sirenLisible(e[0]))} · ${h(entier(e[2]))} sources${e[3] ? ` · département ${h(e[3])}` : ''}</span></li>`)
    .join('')}</ul><p class="aide" data-regle-ordre>${h(REGLE_RESULTATS)}</p>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams): Promise<void | Rendu> {
  const idx = await chargerSiPresent<Index>('entites/index.json')
  if (!idx) {
    cible.innerHTML = `<h1>Une organisation dans toutes les sources</h1>${absent('Les organisations reliées ne sont pas encore publiées.')}${partPersonnelle()}`
    return
  }
  const siren = sirenSaisi(params.get('siren') ?? '')
  if (siren) {
    const rel = fichierFiche(idx, siren)
    const fichier = rel ? await chargerSiPresent<FichierFiches>(rel) : null
    const f = fichier?.fiches[siren]
    if (f) {
      cible.innerHTML = renduFiche(idx, f)
      return {
        titre: `${f.denomination} : ce qu’elle reçoit, source par source`,
        description: `Ce que ${f.denomination} (SIREN ${siren}) reçoit de l’argent public dans ${f.canaux.length} sources du site, année par année, montants tels que publiés, sans total toutes sources confondues.`,
        fil: [{ nom: f.denomination, fragment: lien(PAGE, { siren }) }],
      }
    }
    cible.innerHTML = renduRecherche(idx, '')
    const zone = cible.querySelector<HTMLElement>('#org-resultats')
    if (zone)
      zone.innerHTML = `<p data-sans-fiche>Pas de fiche pour le SIREN ${h(sirenLisible(siren))} : l’organisation ne figure pas dans au moins deux sources du site, ou ce n’est pas une personne morale reprise par le site.</p>`
    brancher(cible, idx)
    return
  }
  const q = (params.get('q') ?? '').slice(0, 80)
  cible.innerHTML = renduRecherche(idx, q)
  const suite = brancher(cible, idx)
  if (q) return { suite: lancer(cible, idx, q) }
  return { suite }
}

async function lancer(cible: HTMLElement, idx: Index, q: string): Promise<void> {
  const zone = cible.querySelector<HTMLElement>('#org-resultats')
  const statut = cible.querySelector<HTMLElement>('#org-statut')
  if (!zone || !statut) return
  const s = sirenSaisi(q)
  if (s) {
    location.hash = lien(PAGE, { siren: s })
    return
  }
  statut.textContent = 'Recherche en cours…'
  const { resultats, message } = await chercher(idx, q)
  zone.innerHTML = message ? `<p>${h(message)}</p>` : listeResultats(resultats)
  statut.textContent = message ? '' : `${resultats.length} résultat${resultats.length > 1 ? 's' : ''}.`
}

async function brancher(cible: HTMLElement, idx: Index): Promise<void> {
  const form = cible.querySelector<HTMLFormElement>('#org-form')
  const champ = cible.querySelector<HTMLInputElement>('#org-q')
  if (!form || !champ) return
  form.addEventListener('submit', (e) => {
    e.preventDefault()
    void lancer(cible, idx, champ.value.trim().slice(0, 80))
  })
}

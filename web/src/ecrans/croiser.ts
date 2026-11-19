// Territoires comparables (/local/croiser) : pour une liste FERMÉE de paires de chiffres d'une même année
// (site/data/typologies, pipeline/typologies.py), comment ces chiffres se répartissent entre les communes qui se
// ressemblent (niveau de densité, strate de population, place dans l'aire d'attraction d'une ville). Petits multiples
// en SVG, mêmes axes dans toutes les cases ; bandes de dispersion, jamais de droite ni de coefficient ; vue d'ensemble
// toujours à côté de la vue par case ; la commune choisie (ou les communes d'un département) repérée dans chaque case.
import { fragmentCommune } from '../chemins'
import { departementDe } from '../departements'
import { chargerSiPresent } from '../donnees'
import { lien, type Rendu } from '../routeur'
import { absent, entier, enPrerendu, h, source, badgeCalcule } from '../util'

export const TITRE = 'Comparer des communes qui se ressemblent'
export const AVERTISSEMENT = 'Mettre deux chiffres côte à côte ne dit pas que l’un explique l’autre ; ce sont des moyennes de communes, pas d’habitants.'
/** Seuls croisements que l'écran sait afficher (contrat 2.x, typologies) : tout autre identifiant est ignoré. */
export const CROISEMENTS_AFFICHABLES = [
  'depenses_niveau_vie_2023',
  'dette_niveau_vie_2023',
  'dgf_niveau_vie_2023',
  'taux_fb_niveau_vie_2023',
  'impots_locaux_rfr_2023',
  'depenses_taux_fb_2024',
  'equipement_dette_2024',
  'dgf_depenses_2024',
  'equipement_paye_niveau_vie_2023',
  'dotations_etat_equipement_2024',
  'impot_revenu_impots_locaux_2023',
  'produit_fb_niveau_vie_2023',
  'aide_sociale_prescriptions_2024',
] as const
/** Croisements ajoutés après la première liste : rendus dans le navigateur seulement (rien de plus dans le HTML prérendu). */
const AJOUTES_HORS_PRERENDU: readonly string[] = ['equipement_paye_niveau_vie_2023', 'dotations_etat_equipement_2024', 'impot_revenu_impots_locaux_2023', 'produit_fb_niveau_vie_2023', 'aide_sociale_prescriptions_2024']
export const FACETTES = { densite: 'par niveau de densité', strate: 'par strate de population', aav: 'par place dans l’aire d’attraction d’une ville' } as const
type Facette = keyof typeof FACETTES
/** Facette unique des croisements entre départements (tranche de population fixée par le site). */
const FACETTE_DEP = 'strate_departement'
/** Strates de l'OFGL jusqu'à 1 999 habitants : la bande de la case est mise en avant plutôt que le point. */
const STRATE_PETITE_MAX = 3

interface Axe { variable: string; libelle: string; unite: string; annee: number; statut: string }
interface Resume { q: (number | null)[]; moyenne_communes: number | null }
interface Case { code?: string; n: number; x: Resume | null; y: Resume | null; bandes: { n: number; y: number[] | null }[]; motif?: string }
interface Croisement {
  millesime: string; source: string; id: string; titre: string; annee: number; x: Axe; y: Axe; perimetre: string; methode: string
  n_min: number; bandes_bornes: number[]; axes: { x: [number, number]; y: [number, number] }; communes: number; ensemble: Case
  facettes: Record<string, { cases: Case[]; communes_sans_case: number }>
  /** Croisement entre départements : points = départements, valeurs publiées par département. */
  niveau?: 'departement'
  avertissement?: string
  territoires_croises?: number
  territoires?: Record<string, { nom: string; strate: string | null; x: number | null; y: number | null; motifs?: Record<string, string> }>
}
interface Index {
  millesime: string; source: string; presentation: string; avertissement: string
  variables: Record<string, { libelle: string; annee: number; unite: string; statut: string; source: string; methode: string; definition: string }>
  croisements: { id: string; titre: string; annee: number; x: string; y: string; fichier: string; communes: number; niveau?: string }[]
  facettes: Record<string, { libelle: string; cases: { code: string; libelle: string }[] }>
  sources: Record<string, { titre: string; millesime?: string; page?: string }>
  limites: string[]
}
interface Ligne { nom: string; population: number | null; densite: string | null; aav: string | null; strate: string | null; v: (number | null)[]; motifs?: Record<string, string> }
interface Communes { millesime: string; source: string; colonnes: string[]; communes: Record<string, Ligne> }

const nf = (d: number) => new Intl.NumberFormat('fr-FR', { maximumFractionDigits: d, minimumFractionDigits: d })
export function valeur(x: number | null | undefined, unite: string): string {
  if (x === null || x === undefined) return 'non publié'
  if (unite === '%') return `${nf(2).format(x)} %`
  if (unite === 'euros par habitant') return `${nf(0).format(x)} € par habitant`
  if (unite === 'euros par an') return `${nf(0).format(x)} € par an`
  if (unite === 'euros par foyer') return `${nf(0).format(x)} € par foyer`
  return `${nf(1).format(x)} ${unite}`
}
const court = (x: number, unite: string) => (unite === '%' ? `${nf(1).format(x)} %` : `${nf(0).format(x)} €`)
const MOTIFS: Record<string, string> = {
  absente: 'aucune ligne de la source',
  perimetre: 'territoire de la commune modifié depuis l’année des données',
  non_publie: 'valeur non publiée par la source',
  secret: 'secret statistique de l’Insee',
  hors_champ: 'hors du champ de la source',
  valeur_manquante: 'valeur manquante à la source',
  non_communique: 'valeur non communiquée par la source',
  incomplete: 'anciennes communes incomplètes dans la source',
}

// Géométrie des petits multiples : mêmes dimensions et mêmes axes dans toutes les cases.
const L = 240
const H = 170
const M = { g: 8, d: 8, h: 8, b: 8 }
const borne = (v: number, a: number, b: number) => Math.min(Math.max(v, a), b)

function echelles(c: Croisement) {
  const [x0, x1] = c.axes.x
  const [y0, y1] = c.axes.y
  const sx = (x: number) => M.g + ((borne(x, x0, x1) - x0) / (x1 - x0 || 1)) * (L - M.g - M.d)
  const sy = (y: number) => H - M.b - ((borne(y, y0, y1) - y0) / (y1 - y0 || 1)) * (H - M.h - M.b)
  const dehors = (x: number, y: number) => x < x0 || x > x1 || y < y0 || y > y1
  return { sx, sy, dehors }
}

export interface Repere { nom: string; x: number; y: number; propre: boolean }

/** Une case : bandes (10 à 90 % clair, 25 à 75 % foncé), médiane par tranche, repères de commune. */
export function caseSvg(c: Croisement, cs: Case, etiquette: string, reperes: Repere[]): string {
  const { sx, sy, dehors } = echelles(c)
  const formes: string[] = [`<rect class="croiser-cadre" x="${M.g}" y="${M.h}" width="${L - M.g - M.d}" height="${H - M.h - M.b}"/>`]
  cs.bandes.forEach((b, k) => {
    if (!b.y) return
    const xa = sx(c.bandes_bornes[k])
    const xb = sx(c.bandes_bornes[k + 1])
    const w = Math.max(xb - xa, 1)
    const [p10, p25, p50, p75, p90] = b.y
    formes.push(`<rect class="croiser-bande-large" x="${xa.toFixed(1)}" y="${sy(p90).toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(sy(p10) - sy(p90), 0.5).toFixed(1)}"/>`)
    formes.push(`<rect class="croiser-bande-centre" x="${xa.toFixed(1)}" y="${sy(p75).toFixed(1)}" width="${w.toFixed(1)}" height="${Math.max(sy(p25) - sy(p75), 0.5).toFixed(1)}"/>`)
    formes.push(`<line class="croiser-mediane" x1="${xa.toFixed(1)}" x2="${(xa + w).toFixed(1)}" y1="${sy(p50).toFixed(1)}" y2="${sy(p50).toFixed(1)}"/>`)
  })
  for (const r of reperes) {
    const x = sx(r.x)
    const y = sy(r.y)
    const classe = r.propre ? 'croiser-point' : 'croiser-point-ailleurs'
    formes.push(
      dehors(r.x, r.y)
        ? `<path class="${classe}" d="M${x.toFixed(1)} ${(y - 5).toFixed(1)}l5 5l-5 5l-5-5z"/>`
        : `<circle class="${classe}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.propre ? 4.5 : 3.5}"/>`,
    )
  }
  return `<svg class="croiser-svg" viewBox="0 0 ${L} ${H}" role="img" aria-label="${h(etiquette)}" focusable="false">${formes.join('')}</svg>`
}

/** Mot des points d'un croisement : communes, ou départements pour un croisement entre départements. */
const points = (c: Pick<Croisement, 'niveau'>, n = 2) => (c.niveau === 'departement' ? (n > 1 ? 'départements' : 'département') : n > 1 ? 'communes' : 'commune')

function phraseCase(c: Croisement, cs: Case): string {
  if (!cs.y || !cs.x || cs.n < c.n_min) return `<p class="absent">${h(entier(cs.n))} ${points(c, cs.n)} : moins de ${h(c.n_min)} ${points(c)}, dispersion non publiée.</p>`
  const [, y25, y50, y75] = cs.y.q
  return `<p class="aide">${h(entier(cs.n))} ${points(c)}. ${h(c.y.libelle[0].toUpperCase() + c.y.libelle.slice(1))} : la moitié des ${points(c)} entre ${h(valeur(y25, c.y.unite))} et ${h(valeur(y75, c.y.unite))}, médiane ${h(valeur(y50, c.y.unite))}.</p>`
}

function tableau(c: Croisement, cases: { libelle: string; cs: Case }[], legende: string): string {
  const q = (r: Resume | null, k: number, u: string) => (r ? h(valeur(r.q[k], u)) : 'non publié')
  return `<details><summary>Les chiffres de chaque case, en tableau</summary><div class="tableau-defile"><table><caption>${h(legende)}</caption><thead><tr><th scope="col">Case</th><th scope="col" class="nombre">${points(c)[0].toUpperCase() + points(c).slice(1)}</th><th scope="col" class="nombre">${h(c.x.libelle)} : médiane</th><th scope="col" class="nombre">${h(c.y.libelle)} : 1er quart</th><th scope="col" class="nombre">médiane</th><th scope="col" class="nombre">3e quart</th><th scope="col" class="nombre">moyenne des ${points(c)}</th></tr></thead><tbody>${cases
    .map(
      ({ libelle, cs }) =>
        `<tr><th scope="row">${h(libelle)}</th><td class="nombre">${h(entier(cs.n))}</td><td class="nombre">${q(cs.x, 2, c.x.unite)}</td><td class="nombre">${q(cs.y, 1, c.y.unite)}</td><td class="nombre">${q(cs.y, 2, c.y.unite)}</td><td class="nombre">${q(cs.y, 3, c.y.unite)}</td><td class="nombre">${cs.y ? h(valeur(cs.y.moyenne_communes, c.y.unite)) : 'non publié'}</td></tr>`,
    )
    .join('')}</tbody></table></div></details>`
}

/** Identifiants affichés : ceux de l'index qui sont aussi dans la liste fermée de l'écran, dans l'ordre de l'index. */
export const croisementsAffiches = (idx: Pick<Index, 'croisements'>, prerendu = enPrerendu()) =>
  idx.croisements.filter((c) => (CROISEMENTS_AFFICHABLES as readonly string[]).includes(c.id) && /^[a-z0-9_]+$/.test(c.id) && !(prerendu && AJOUTES_HORS_PRERENDU.includes(c.id)))

export async function rendre(cible: HTMLElement, params: URLSearchParams): Promise<Rendu | void> {
  const idx = await chargerSiPresent<Index>('typologies/index.json')
  const insee = /^(\d{5}|2[AB]\d{3})$/.test(params.get('insee') ?? '') ? params.get('insee')! : ''
  const depDemande = /^(\d{2,3}|2[AB])$/.test(params.get('dep') ?? '') ? params.get('dep')! : ''
  const dep = insee ? departementDe(insee) : depDemande
  const intro = `<h1>${h(TITRE)}</h1>
<p class="chapeau">${h(idx?.presentation ?? 'Des communes qui se ressemblent et, pour quelques paires de chiffres choisies d’avance, comment ces chiffres se répartissent entre elles. La page ne dit pas pourquoi une commune dépense plus ou moins qu’une autre.')}</p>
<p class="avertissement" id="croiser-avertissement"><strong>${h(AVERTISSEMENT)}</strong></p>`
  const sorties = `<h2>Pour aller plus loin</h2>
<ul class="liens-sortie">
  <li><a href="#/local">Le budget de ma commune</a></li>
  <li><a href="#/explorer/collectivites">Les collectivités locales en France</a></li>
</ul>`
  if (!idx) {
    cible.innerHTML = `${intro}${absent('Les données des territoires comparables ne sont pas disponibles.')}${sorties}`
    return
  }
  const liste = croisementsAffiches(idx)
  const choisi = liste.find((c) => c.id === params.get('c')) ?? liste[0]
  const facette: Facette = (Object.keys(FACETTES) as Facette[]).find((f) => f === params.get('f')) ?? 'densite'
  if (!choisi) {
    cible.innerHTML = `${intro}${absent('Aucun croisement disponible.')}${sorties}`
    return
  }
  const [cr, communes] = await Promise.all([
    chargerSiPresent<Croisement>(`typologies/${choisi.fichier}`),
    dep && choisi.niveau !== 'departement' ? chargerSiPresent<Communes>(`typologies/communes/${dep}.json`) : Promise.resolve(null),
  ])
  const garde = { insee: insee || undefined, dep: !insee && depDemande ? depDemande : undefined }
  const menuCroisements = `<nav aria-label="Paires de chiffres"><h2>Choisis deux chiffres</h2><ul class="liens-sortie">${liste
    .map((c) => `<li>${c.id === choisi.id ? `<strong aria-current="page">${h(c.titre)}</strong>` : `<a href="${lien('/local/croiser', { c: c.id, f: facette, ...garde })}">${h(c.titre)}</a>`}</li>`)
    .join('')}</ul></nav>`
  const menuFacettes = `<nav aria-label="Regrouper les communes"><h2>Regrouper les communes</h2><ul class="liens-sortie">${(Object.keys(FACETTES) as Facette[])
    .map((f) => `<li>${f === facette ? `<strong aria-current="page">${h(FACETTES[f])}</strong>` : `<a href="${lien('/local/croiser', { c: choisi.id, f, ...garde })}">${h(FACETTES[f])}</a>`}</li>`)
    .join('')}</ul></nav>`
  const formulaire = `<form id="croiser-lieu" role="search"><h2>Repérer ta commune ou ton département</h2>
<label for="croiser-insee">Code Insee de la commune (5 caractères)</label><input type="text" id="croiser-insee" name="insee" inputmode="text" autocomplete="off" pattern="(\\d{5}|2[ABab]\\d{3})" value="${h(insee)}">
<label for="croiser-dep">ou numéro du département</label><input type="text" id="croiser-dep" name="dep" autocomplete="off" pattern="(\\d{2,3}|2[ABab])" value="${h(!insee ? depDemande : '')}">
<p><button class="bouton" type="submit">Repérer</button></p></form>`

  if (!cr) {
    cible.innerHTML = `${intro}${menuCroisements}${absent('Ce croisement n’est pas disponible.')}${sorties}`
    return
  }
  if (cr.niveau === 'departement') {
    cible.innerHTML = renduDepartements(idx, cr, dep, { intro, menuCroisements, formulaire, sorties })
    brancherFormulaire(cible, choisi.id, facette)
    return
  }
  // Repères : la commune choisie dans chaque case, ou les communes du département dans leur propre case.
  const ix = communes ? communes.colonnes.indexOf(cr.x.variable) : -1
  const iy = communes ? communes.colonnes.indexOf(cr.y.variable) : -1
  const ligne = insee ? communes?.communes[insee] : undefined
  const caseDe = (l: Ligne) => (facette === 'densite' ? l.densite : facette === 'strate' ? l.strate : l.aav)
  const paire = (l: Ligne) => (ix >= 0 && iy >= 0 && l.v[ix] !== null && l.v[iy] !== null ? { x: l.v[ix] as number, y: l.v[iy] as number } : null)
  const reperesDe = (code: string | null): Repere[] => {
    if (ligne) {
      const p = paire(ligne)
      return p ? [{ nom: ligne.nom, ...p, propre: code === null || caseDe(ligne) === code }] : []
    }
    if (communes && depDemande) {
      return Object.values(communes.communes)
        .filter((l) => code === null || caseDe(l) === code)
        .map((l) => ({ l, p: paire(l) }))
        .filter((o) => o.p)
        .map(({ l, p }) => ({ nom: l.nom, ...p!, propre: true }))
    }
    return []
  }
  const libCases = new Map(idx.facettes[facette].cases.map((c) => [c.code, c.libelle]))
  const cases = cr.facettes[facette].cases.map((cs) => ({ libelle: libCases.get(cs.code ?? '') ?? cs.code ?? '', cs }))
  const vignette = (titre: string, cs: Case, code: string | null, propre: boolean) => {
    const rep = reperesDe(code)
    const etiquette = `${titre} : bandes de dispersion de ${cr.y.libelle} selon ${cr.x.libelle}, ${cr.annee}${rep.length ? `, ${rep.length === 1 ? rep[0].nom : `${rep.length} communes du département`} repérée${rep.length > 1 ? 's' : ''}` : ''}`
    return `<figure class="croiser-case${propre ? ' croiser-case-propre' : ''}"><figcaption><strong>${h(titre)}</strong>${propre && ligne ? ` <span class="aide">(case de ${h(ligne.nom)})</span>` : ''}</figcaption>${caseSvg(cr, cs, etiquette, rep)}${phraseCase(cr, cs)}</figure>`
  }

  // Ta commune : ses deux valeurs, ou le motif de leur absence.
  let blocLieu = ''
  if (insee && communes && ligne) {
    const p = paire(ligne)
    const motif = (v: string) => MOTIFS[ligne.motifs?.[v] ?? ''] ?? 'non publié'
    const petite = ligne.strate !== null && Number(ligne.strate) <= STRATE_PETITE_MAX
    blocLieu = `<section aria-labelledby="croiser-ta-commune"><h2 id="croiser-ta-commune">${h(ligne.nom)}</h2>
<ul>
<li>${h(cr.x.libelle)} (${h(cr.x.annee)}) : ${p ? h(valeur(p.x, cr.x.unite)) : h(ligne.v[ix] === null ? motif(cr.x.variable) : valeur(ligne.v[ix], cr.x.unite))}</li>
<li>${h(cr.y.libelle)} (${h(cr.y.annee)}) : ${p ? h(valeur(p.y, cr.y.unite)) : h(ligne.v[iy] === null ? motif(cr.y.variable) : valeur(ligne.v[iy], cr.y.unite))}</li>
</ul>
${!p ? '<p class="aide">Les deux chiffres de la même année ne sont pas tous deux publiés pour cette commune : elle n’est pas repérée dans les cases.</p>' : ''}
${petite ? '<p class="aide">Commune de moins de 2 000 habitants : ses montants par habitant changent beaucoup d’une année à l’autre (un équipement, un emprunt). La bande de sa case en dit plus que son point.</p>' : ''}
<p class="actions"><a href="${fragmentCommune(insee, ligne.nom, ligne.population)}">Le budget de ${h(ligne.nom)}</a></p></section>`
  } else if (insee) {
    blocLieu = absent('Commune introuvable dans les données des territoires comparables.')
  } else if (depDemande && communes) {
    blocLieu = `<p class="aide">Les communes du département ${h(depDemande)} sont repérées par un point dans leur propre case (${h(entier(Object.keys(communes.communes).length))} communes ; seules celles dont les deux chiffres sont publiés apparaissent). <a href="${lien('/local/departement', { dep: depDemande })}">Les communes du département ${h(depDemande)}</a></p>`
  } else if (depDemande) {
    blocLieu = absent('Département introuvable dans les données des territoires comparables.')
  }

  const sources = [cr.x, cr.y]
    .map((a) => {
      const v = idx.variables[a.variable]
      const s = v ? idx.sources[v.source] : undefined
      return `<li><strong>${h(a.libelle)}</strong> (${h(a.annee)}) : ${h(v?.definition ?? '')}. ${a.statut === 'calculé par le site' && v?.methode ? badgeCalcule(v.methode) : ''}${source(s?.titre ?? cr.source, String(a.annee))}</li>`
    })
    .join('')

  cible.innerHTML = `${intro}
${menuCroisements}
${menuFacettes}
${formulaire}
${blocLieu}
<section aria-labelledby="croiser-titre"><h2 id="croiser-titre">${h(cr.titre)}</h2>
<p>En abscisse (de gauche à droite) : ${h(cr.x.libelle)}, de ${h(court(cr.axes.x[0], cr.x.unite))} à ${h(court(cr.axes.x[1], cr.x.unite))}. En ordonnée (de bas en haut) : ${h(cr.y.libelle)}, de ${h(court(cr.axes.y[0], cr.y.unite))} à ${h(court(cr.axes.y[1], cr.y.unite))}. Mêmes axes dans toutes les cases. Chaque bande est une tranche de communes : la partie claire va de 10 à 90 % des communes, la partie foncée de 25 à 75 %, le trait est la médiane. Un losange marque une commune au-delà des bornes des axes.</p>
<p class="aide">Dispersion ${badgeCalcule(cr.methode)}</p>
<div class="croiser-grille">
${vignette('Toutes les communes', cr.ensemble, null, false)}
</div>
<h3>${h(idx.facettes[facette].libelle[0].toUpperCase() + idx.facettes[facette].libelle.slice(1))}</h3>
<p class="aide">La vue d’ensemble reste à côté de la vue par case : une tendance visible sur toutes les communes peut disparaître ou s’inverser à l’intérieur de chaque case.</p>
<div class="croiser-grille">
${cases.map(({ libelle, cs }) => vignette(libelle, cs, cs.code ?? '', !!ligne && caseDe(ligne) === cs.code)).join('')}
</div>
${tableau(cr, [{ libelle: 'Toutes les communes', cs: cr.ensemble }, ...cases], `${cr.titre}, ${FACETTES[facette]}, dispersion par case`)}
</section>
<h2>D’où viennent ces chiffres</h2>
<ul>${sources}</ul>
<p class="aide">Périmètre : ${h(cr.perimetre)}.</p>
<h2>Ce que la page ne montre pas</h2>
<ul>${idx.limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul>
${source(idx.source, idx.millesime)}
${sorties}`

  brancherFormulaire(cible, choisi.id, facette)
  // Sans commune choisie : titre et description de la table des routes (page prérendue et partagée).
  return ligne
    ? {
        titre: `${TITRE} : ${ligne.nom}`,
        description: `${cr.titre} : dispersion entre communes ${FACETTES[facette]}, mêmes axes dans toutes les cases, sans droite ni coefficient.`,
      }
    : {}
}

function brancherFormulaire(cible: HTMLElement, id: string, facette: Facette): void {
  cible.querySelector<HTMLFormElement>('#croiser-lieu')?.addEventListener('submit', (e) => {
    e.preventDefault()
    const f = e.target as HTMLFormElement
    const i = (f.querySelector<HTMLInputElement>('#croiser-insee')?.value ?? '').trim().toUpperCase()
    const d = (f.querySelector<HTMLInputElement>('#croiser-dep')?.value ?? '').trim().toUpperCase()
    location.hash = lien('/local/croiser', { c: id, f: facette, insee: /^(\d{5}|2[AB]\d{3})$/.test(i) ? i : undefined, dep: !i && /^(\d{2,3}|2[AB])$/.test(d) ? d : undefined })
  })
}

/** Croisement entre départements : une seule facette (tranche de population), le département repéré dans sa case. */
export function renduDepartements(
  idx: Index,
  cr: Croisement,
  dep: string,
  morceaux: { intro: string; menuCroisements: string; formulaire: string; sorties: string },
): string {
  const t = dep ? cr.territoires?.[dep] : undefined
  const fac = idx.facettes[FACETTE_DEP]
  const libCases = new Map((fac?.cases ?? []).map((c) => [c.code, c.libelle]))
  const cases = (cr.facettes[FACETTE_DEP]?.cases ?? []).map((cs) => ({ libelle: libCases.get(cs.code ?? '') ?? cs.code ?? '', cs }))
  const p = t && t.x !== null && t.y !== null ? { x: t.x, y: t.y } : null
  const reperes = (code: string | null): Repere[] => (t && p ? [{ nom: t.nom, ...p, propre: code === null || t.strate === code }] : [])
  const vignette = (titre: string, cs: Case, code: string | null, propre: boolean) => {
    const rep = reperes(code)
    const etiquette = `${titre} : bandes de dispersion de ${cr.y.libelle} selon ${cr.x.libelle}, ${cr.annee}${rep.length ? `, ${rep[0].nom} repéré` : ''}`
    return `<figure class="croiser-case${propre ? ' croiser-case-propre' : ''}"><figcaption><strong>${h(titre)}</strong>${propre && t ? ` <span class="aide">(case de ${h(t.nom)})</span>` : ''}</figcaption>${caseSvg(cr, cs, etiquette, rep)}${phraseCase(cr, cs)}</figure>`
  }
  let blocLieu = ''
  if (dep && t) {
    const motifs: Record<string, string> = { ...MOTIFS, perimetre: 'territoire du département différent de celui d’une seule collectivité départementale publiée par l’OFGL' }
    const motif = (v: string) => motifs[t.motifs?.[v] ?? ''] ?? 'non publié'
    blocLieu = `<section aria-labelledby="croiser-ton-departement"><h2 id="croiser-ton-departement">${h(t.nom)} (${h(dep)})</h2>
<ul>
<li>${h(cr.x.libelle)} (${h(cr.x.annee)}) : ${h(t.x === null ? motif(cr.x.variable) : valeur(t.x, cr.x.unite))}</li>
<li>${h(cr.y.libelle)} (${h(cr.y.annee)}) : ${h(t.y === null ? motif(cr.y.variable) : valeur(t.y, cr.y.unite))}</li>
</ul>
${!p ? '<p class="aide">Les deux chiffres de la même année ne sont pas tous deux publiés pour ce département : il n’est pas repéré dans les cases.</p>' : ''}
<p class="actions"><a href="${lien('/local/departement', { dep })}">Les communes du département ${h(dep)}</a></p></section>`
  } else if (dep) {
    blocLieu = absent('Département introuvable dans ce croisement.')
  }
  const sources = [cr.x, cr.y]
    .map((a) => {
      const v = idx.variables[a.variable]
      const s = v ? idx.sources[v.source] : undefined
      return `<li><strong>${h(a.libelle)}</strong> (${h(a.annee)}) : ${h(v?.definition ?? '')}. ${a.statut === 'calculé par le site' && v?.methode ? badgeCalcule(v.methode) : ''}${source(s?.titre ?? cr.source, String(a.annee))}</li>`
    })
    .join('')
  return `${morceaux.intro}
${morceaux.menuCroisements}
<p class="aide">Ce croisement compare des départements, pas des communes : ils sont regroupés ${h(fac?.libelle ?? 'par tranche de population')}. ${h(cr.avertissement ?? '')}</p>
${morceaux.formulaire}
${blocLieu}
<section aria-labelledby="croiser-titre"><h2 id="croiser-titre">${h(cr.titre)}</h2>
<p>En abscisse (de gauche à droite) : ${h(cr.x.libelle)}, de ${h(court(cr.axes.x[0], cr.x.unite))} à ${h(court(cr.axes.x[1], cr.x.unite))}. En ordonnée (de bas en haut) : ${h(cr.y.libelle)}, de ${h(court(cr.axes.y[0], cr.y.unite))} à ${h(court(cr.axes.y[1], cr.y.unite))}. Mêmes axes dans toutes les cases. Chaque bande est une tranche de départements : la partie claire va de 10 à 90 % des départements, la partie foncée de 25 à 75 %, le trait est la médiane ; une tranche de moins de ${h(cr.n_min)} départements n’a pas de bande. ${h(entier(cr.territoires_croises ?? 0))} départements ont les deux chiffres.</p>
<p class="aide">Dispersion ${badgeCalcule(cr.methode)}</p>
<div class="croiser-grille">
${vignette('Tous les départements', cr.ensemble, null, false)}
</div>
<h3>${h((fac?.libelle ?? 'par tranche de population')[0].toUpperCase() + (fac?.libelle ?? 'par tranche de population').slice(1))}</h3>
<p class="aide">La vue d’ensemble reste à côté de la vue par case : une tendance visible sur tous les départements peut disparaître ou s’inverser à l’intérieur de chaque case.</p>
<div class="croiser-grille">
${cases.map(({ libelle, cs }) => vignette(libelle, cs, cs.code ?? '', !!t && t.strate === cs.code)).join('')}
</div>
${tableau(cr, [{ libelle: 'Tous les départements', cs: cr.ensemble }, ...cases], `${cr.titre}, par tranche de population, dispersion par case`)}
</section>
<h2>D’où viennent ces chiffres</h2>
<ul>${sources}</ul>
<p class="aide">Périmètre : ${h(cr.perimetre)}.</p>
<h2>Ce que la page ne montre pas</h2>
<ul>${idx.limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul>
${source(idx.source, idx.millesime)}
${morceaux.sorties}`
}

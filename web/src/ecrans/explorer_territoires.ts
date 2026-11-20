// Tableaux par département ajoutés aux écrans Explorer (lot 2, contrat 2.72, 2.76, 2.77) : comptes des services
// d'incendie et de secours (Collectivités), assurance chômage (Prestations), patients par pathologie (Hôpitaux).
// Chaque tableau est replié et lu à sa première ouverture ; valeurs telles que publiées, ordre des départements par
// code (aucun classement), source et millésime sous chaque tableau.
import { chargerSiPresent } from '../donnees'
import { absent, appliquerLargeurs, entier, eur, h, pct, repli, source } from '../util'

interface Sdis { millesime: string; source: string; annees: string[]; sdis: Record<string, { departement: string; annees: Record<string, (number | null)[]>; par_habitant: Record<string, (number | null)[]> }> }
interface Unedic { millesime: string; source: string; dernier_mois: string; departements: Record<string, { nom: string; mois: Record<string, (number | null)[]> }> }
interface Patho { millesime: string; source: string; mention: string; pathologies: string[]; departements: Record<string, { nom: string; annees: Record<string, ([number | null, number | null] | null)[]> }> }
interface PathoIndex { pathologies: Record<string, { libelle: string; niveau: number }> }

const val = (v: number | null | undefined, f: (x: number) => string) => (v === null || v === undefined ? 'non publié' : f(v))
const parCode = (a: string, b: string) => a.localeCompare(b, 'fr', { numeric: true })
const tableau = (caption: string, entetes: string[], lignes: string[][]) =>
  `<div class="tableau-defile"><table><caption>${caption}</caption><thead><tr>${entetes.map((e, i) => `<th scope="col"${i ? ' class="nombre"' : ''}>${e}</th>`).join('')}</tr></thead><tbody>${lignes.map((l) => `<tr><th scope="row">${l[0]}</th>${l.slice(1).map((c) => `<td class="nombre">${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`

export async function tableauSdis(): Promise<string> {
  const s = await chargerSiPresent<Sdis>('ofgl_complements/sdis.json')
  if (!s) return absent('Comptes des SDIS non disponibles.')
  const an = s.annees[s.annees.length - 1]
  const lignes = Object.keys(s.sdis).sort(parCode).map((d) => {
    const x = s.sdis[d]
    return [h(`${x.departement} (${d})`), h(val(x.annees[an]?.[0], eur)), h(val(x.par_habitant[an]?.[0], eur)), h(val(x.annees[an]?.[4], eur)), h(val(x.annees[an]?.[5], eur))]
  })
  return `${tableau(`Services départementaux d’incendie et de secours, ${h(an)}, budget principal`, ['Département', 'Dépenses totales (hors remboursements d’emprunts)', 'Par habitant (OFGL)', 'Participation du département', 'Participations des communes'], lignes)}
<p class="aide">Ordre : code du département. Paris et petite couronne : brigade de sapeurs-pompiers de Paris, sans comptes de SDIS. Les participations figurent déjà dans les budgets des départements et des communes : ne pas les ajouter.</p>
${source(s.source, s.millesime)}`
}

export async function tableauUnedic(): Promise<string> {
  const u = await chargerSiPresent<Unedic>('emploi_territoires/departements.json')
  if (!u) return absent('Indicateurs de l’Assurance chômage non disponibles.')
  const m = u.dernier_mois
  const lignes = Object.keys(u.departements).sort(parCode).map((d) => {
    const v = u.departements[d].mois[m] ?? []
    return [h(`${u.departements[d].nom} (${d})`), h(val(v[0], entier)), h(val(v[1], entier)), h(val(v[2], eur)), h(val(v[3], eur))]
  })
  return `${tableau(`Assurance chômage par département, ${h(m)}`, ['Département', 'Allocataires', 'Indemnisés', 'Montant moyen mensuel net', 'Dépense du mois'], lignes)}
<p class="aide">Ordre : code du département. Valeurs publiées par l’Unédic pour le mois indiqué.</p>
${source(u.source, u.millesime)}`
}

export async function tableauPathologies(): Promise<string> {
  const [p, pi] = await Promise.all([chargerSiPresent<Patho>('pathologies_departements/departements.json'), chargerSiPresent<PathoIndex>('pathologies_departements/index.json')])
  if (!p || !pi) return absent('Effectifs de patients non disponibles.')
  const i = p.pathologies.indexOf('DIA_CAT_CAT')
  const iCan = p.pathologies.findIndex((c) => pi.pathologies[c]?.niveau === 1 && /^Cancers/.test(pi.pathologies[c].libelle))
  const an = Object.keys(Object.values(p.departements)[0]?.annees ?? {}).sort().pop() ?? ''
  const lignes = Object.keys(p.departements).sort(parCode).map((d) => {
    const v = p.departements[d].annees[an] ?? []
    return [h(`${p.departements[d].nom} (${d})`), h(val(v[0]?.[0], entier)), h(val(v[i]?.[0], entier)), h(val(v[i]?.[1], (x) => pct(x))), h(val(v[iCan]?.[0], entier)), h(val(v[iCan]?.[1], (x) => pct(x)))]
  })
  return `${tableau(`Patients pris en charge par département, ${h(an)} : diabète et cancers`, ['Département', 'Population de référence', 'Diabète', 'Prévalence', 'Cancers', 'Prévalence'], lignes)}
<p class="aide">Ordre : code du département. Effectifs et prévalences publiés par la Cnam ; tous les groupes de pathologies figurent dans la page de chaque commune (onglet du département). Les dépenses par pathologie ne sont publiées qu’au niveau national.</p>
${source(p.source, p.millesime)}<p class="aide">${h(p.mention)}</p>`
}

const TABLEAUX = { sdis: tableauSdis, unedic: tableauUnedic, pathologies: tableauPathologies }
export type Tableau = keyof typeof TABLEAUX

/** Section repliée, à ajouter en fin de page, puis à brancher. */
export function repliTerritoire(cle: Tableau, titre: string, resume: string): string {
  return repli({ id: `et-${cle}-repli`, titre, resume: h(resume), contenu: `<div id="et-${cle}" class="section-donnees"><p class="chargement">Chargement…</p></div>` })
}

export function brancherTerritoire(racine: HTMLElement, cle: Tableau): void {
  const d = racine.querySelector<HTMLDetailsElement>(`#et-${cle}-repli`)
  if (!d) return
  let fait = false
  const charger = async () => {
    if (fait || !d.open) return
    fait = true
    const z = racine.querySelector<HTMLElement>(`#et-${cle}`)!
    z.setAttribute('aria-busy', 'true')
    try {
      z.innerHTML = await TABLEAUX[cle]()
    } catch (e) {
      console.error(e)
      z.innerHTML = absent()
    }
    z.removeAttribute('aria-busy')
    appliquerLargeurs(z)
  }
  d.addEventListener('toggle', () => void charger())
}

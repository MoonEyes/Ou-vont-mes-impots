// Les communes d'un département (site/data/local/geo/<dep>.json) : budget du département, puis la liste des
// communes. Celles de plus de 5 000 habitants ont leur propre page (/local/<insee>-<nom>/), les autres passent
// par la page commune générique.
import { fragmentCommune, fragmentDepartement, SEUIL_PAGE_COMMUNE } from '../chemins'
import { partPersonnelle } from '../composants/hub'
import { chargerSiPresent } from '../donnees'
import type { Rendu } from '../routeur'
import { absent, appliquerLargeurs, entier, h, source } from '../util'
import { blocBudget, type Budgets, type Geo } from './commune'

export const titreDepartement = (nom: string, code: string) => `${nom} (${code}) : budget des communes, dépenses, dotations, taux`

export async function rendre(cible: HTMLElement, params: URLSearchParams): Promise<Rendu | void> {
  const dep = params.get('dep') ?? ''
  const geo = /^(\d{2,3}|2[AB])$/.test(dep) ? await chargerSiPresent<Geo>(`local/geo/${dep}.json`) : null
  if (!geo) {
    location.hash = '#/local'
    return
  }
  const communes = Object.entries(geo.communes).sort((a, b) => a[1].nom.localeCompare(b[1].nom, 'fr'))
  const population = communes.reduce((s, [, c]) => s + (c.population ?? 0), 0)
  const grandes = communes.filter(([, c]) => c.population > SEUIL_PAGE_COMMUNE).sort((a, b) => b[1].population - a[1].population)
  const autres = communes.filter(([, c]) => !(c.population > SEUIL_PAGE_COMMUNE))
  const item = ([insee, c]: (typeof communes)[number], avecPopulation: boolean) =>
    `<li><a href="${fragmentCommune(insee, c.nom, c.population)}">${h(c.nom)}</a>${avecPopulation ? ` <span class="aide">${h(entier(c.population))} habitants</span>` : ''}</li>`
  const nom = geo.departement.nom
  cible.innerHTML = `
<h1>${h(nom)} (${h(dep)}) : le budget des communes</h1>
<p class="chapeau">${h(entier(communes.length))} commune${communes.length > 1 ? 's' : ''} · ${h(entier(population))} habitants · ${h(geo.region.nom)}</p>
<p class="aide">Pour chaque commune : ses dépenses, ce que l’État lui verse, les taux d’impôts locaux votés. Chaque collectivité a son propre budget : ne pas additionner commune, intercommunalité, département et région.</p>
<div id="sec-budget-dep" class="section-donnees" aria-busy="true"><p class="chargement">Chargement…</p></div>
${
  grandes.length
    ? `<h2>Communes de plus de ${h(entier(SEUIL_PAGE_COMMUNE))} habitants</h2>
<p class="aide">Ordre : population décroissante.</p>
<ul class="liste-colonnes">${grandes.map((c) => item(c, true)).join('')}</ul>`
    : ''
}
${
  autres.length
    ? `<h2>${grandes.length ? 'Les autres communes' : 'Les communes'}</h2>
<p class="aide">Ordre alphabétique.</p>
<ul class="liste-colonnes">${autres.map((c) => item(c, false)).join('')}</ul>`
    : ''
}
${source(geo.source, geo.millesime)}
<h2>Pour aller plus loin</h2>
<ul class="liens-sortie">
  <li><a href="#/explorer/collectivites">Les collectivités locales en France</a></li>
  <li><a href="#/decisions/controle?dep=${h(dep)}">Les rapports de contrôle dans le département ${h(nom)}</a></li>
  <li><a href="#/local">Choisir un autre département</a></li>
</ul>
${partPersonnelle()}`

  const suite = (async () => {
    const z = cible.querySelector<HTMLElement>('#sec-budget-dep')!
    const bd = await chargerSiPresent<Budgets>('local/budgets/departements.json')
    const dpt = bd?.collectivites[dep]
    z.innerHTML = bd && dpt ? blocBudget(bd, dpt, `Le budget du département : ${dpt.nom}`, true) : `<h2>Le budget du département</h2>${absent('Budget du département non disponible.')}`
    z.removeAttribute('aria-busy')
    appliquerLargeurs(z)
  })()
  return {
    suite,
    titre: titreDepartement(nom, dep),
    fil: [{ nom, fragment: fragmentDepartement(dep, nom) }],
    description: `${nom} (${dep}) : le budget de chacune des ${entier(communes.length)} communes (dépenses par habitant, dotations de l’État, taux d’impôts locaux votés) et celui du département.`,
  }
}

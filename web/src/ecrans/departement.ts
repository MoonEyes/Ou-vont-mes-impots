// Les communes d'un département (site/data/local/geo/<dep>.json) : budget du département, puis la liste des
// communes. Celles de plus de 5 000 habitants ont leur propre page (/local/<insee>-<nom>/), les autres passent
// par la page commune générique.
import { fragmentCommune, fragmentDepartement, SEUIL_PAGE_COMMUNE } from '../chemins'
import { partPersonnelle } from '../composants/hub'
import { ouCest } from '../composants/trame'
import { chargerSiPresent } from '../donnees'
import type { Rendu } from '../routeur'
import { AFFICHE_DANS_LE_NAVIGATEUR, absent, appliquerLargeurs, enPrerendu, entier, h, source } from '../util'
import { blocBudget, clesBudget, type Budgets, type Geo } from './commune'
import { blocAideSociale, blocInvestissementDepartement, blocOrganismesDepartement, blocSruDepartement, type FichierCcas, type FichierSyndicats, type Territoire } from './territoires'
import { brancherProjets } from './projets'

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
<div class="entete-local">
  <div>
    <h1>${h(nom)} (${h(dep)}) : le budget des communes</h1>
    <p class="chapeau">${h(entier(communes.length))} commune${communes.length > 1 ? 's' : ''}, ${h(entier(population))} habitants, région ${h(geo.region.nom)}.</p>
    <p class="aide">Pour chaque commune : ses dépenses, ce que l’État lui verse, les taux d’impôts locaux votés. Chaque collectivité a son propre budget : ne pas additionner commune, intercommunalité, département et région.</p>
    <p class="actions"><a class="bouton" href="#/local">Chercher une autre commune</a></p>
  </div>
  ${ouCest(dep, nom)}
</div>
<div id="sec-budget-dep" class="section-donnees" aria-busy="true"><p class="chargement">Chargement…</p></div>
<h2>Les projets aidés par l’État dans le département</h2>
<div id="sec-projets-etat" class="section-donnees" aria-busy="true"><p class="chargement">Chargement…</p></div>
<h2>L’aide sociale du département</h2>
<div id="sec-aide-sociale" class="section-donnees" aria-busy="true"><p class="chargement">Chargement…</p></div>
<h2>Logement social : les communes de la loi SRU</h2>
<div id="sec-sru" class="section-donnees" aria-busy="true"><p class="chargement">Chargement…</p></div>
<h2>Syndicats et organismes départementaux</h2>
<div id="sec-organismes" class="section-donnees" aria-busy="true"><p class="chargement">Chargement…</p></div>
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
<h2>Les solidarités du département</h2>
<p>Ce que le département verse pour le revenu de solidarité active, l’allocation personnalisée d’autonomie, la prestation de compensation du handicap et l’aide sociale à l’enfance, combien de personnes les reçoivent et les recettes qu’il reçoit pour ces allocations, de 2012 à 2025.</p>
<p class="liens-sortie"><a href="#/explorer/solidarites-departements?dep=${h(dep)}">Ce que verse le département ${h(nom)} pour les solidarités</a></p>
<h2>Pour aller plus loin</h2>
<ul class="liens-sortie">
  <li><a href="#/explorer/collectivites">Les collectivités locales en France</a></li>
  <li><a href="#/decisions/controle?dep=${h(dep)}">Les rapports de contrôle dans le département ${h(nom)}</a></li>
  <li><a href="#/decisions/resultats?dep=${h(dep)}">Le baromètre des résultats de l’action publique dans le département ${h(nom)}</a></li>
  <li><a href="#/local">Choisir un autre département</a></li>
</ul>
${partPersonnelle()}`

  brancherProjets(cible, { dep, nom })
  const remplir = (id: string, html: string) => {
    const z = cible.querySelector<HTMLElement>(`#${id}`)
    if (!z) return
    z.innerHTML = html
    z.removeAttribute('aria-busy')
    appliquerLargeurs(z)
  }
  const budget = (async () => {
    const z = cible.querySelector<HTMLElement>('#sec-budget-dep')!
    const bd = await chargerSiPresent<Budgets>('local/budgets/departements.json')
    const dpt = bd?.collectivites[dep]
    z.innerHTML = bd && dpt ? clesBudget(bd, dpt) + blocBudget(bd, dpt, `Le budget du département : ${dpt.nom}`, true) : `<h2>Le budget du département</h2>${absent('Budget du département non disponible.')}`
    z.removeAttribute('aria-busy')
    appliquerLargeurs(z)
  })()
  // Données par département : projets aidés par l'État, aide sociale, inventaire SRU (territoires/), syndicats et
  // centres d'action sociale (local_satellites/). Demandées après le budget du département.
  const territoires = budget.then(async () => {
    if (enPrerendu()) {
      for (const id of ['sec-projets-etat', 'sec-aide-sociale', 'sec-sru', 'sec-organismes']) remplir(id, AFFICHE_DANS_LE_NAVIGATEUR)
      return
    }
    const [ter, syn, ccas] = await Promise.all([
      chargerSiPresent<Territoire>(`territoires/${dep}.json`),
      chargerSiPresent<FichierSyndicats>(`local_satellites/syndicats/${dep}.json`),
      chargerSiPresent<FichierCcas>(`local_satellites/ccas/${dep}.json`),
    ])
    remplir('sec-projets-etat', ter ? blocInvestissementDepartement(ter) : absent('Projets non disponibles.'))
    remplir('sec-aide-sociale', ter ? blocAideSociale(ter) : absent('Aide sociale non disponible.'))
    remplir('sec-sru', ter ? blocSruDepartement(ter) : absent('Inventaire non disponible.'))
    remplir('sec-organismes', blocOrganismesDepartement(syn, ccas))
  })
  const suite = Promise.all([budget, territoires])
    .then(() => undefined)
    .catch((e) => {
      console.error(e)
      cible.querySelectorAll<HTMLElement>('.section-donnees[aria-busy]').forEach((z) => {
        z.innerHTML = absent()
        z.removeAttribute('aria-busy')
      })
    })
  return {
    suite,
    titre: titreDepartement(nom, dep),
    fil: [{ nom, fragment: fragmentDepartement(dep, nom) }],
    description: `${nom} (${dep}) : le budget de chacune des ${entier(communes.length)} communes (dépenses par habitant, dotations de l’État, taux d’impôts locaux votés) et celui du département.`,
  }
}

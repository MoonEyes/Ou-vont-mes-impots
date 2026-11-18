// Ta commune (site/data/local/) : budget de la commune, bloc communal, département, région,
// dotations de l'État, taux votés, subventions publiées. Chaque niveau à part : on n'additionne jamais.
import { fragmentCommune, fragmentDepartement } from '../chemins'
import { partPersonnelle } from '../composants/hub'
import { ouCest } from '../composants/trame'
import { departementDe } from '../departements'
import { chargerSiPresent } from '../donnees'
import { lien, type Rendu } from '../routeur'
import { AFFICHE_DANS_LE_NAVIGATEUR, absent, appliquerLargeurs, enPrerendu, badgeStatut, barres, eur, eurLisible, h, pct, source, sur100, surligne } from '../util'
import { blocInvestissementCommune, blocOrganismesCommune, blocSruCommune, type Beneficiaire, type FichierCcas, type FichierEau, type FichierMobilite, type FichierSyndicats, type Territoire } from './territoires'

export interface Geo {
  millesime: string
  source: string
  departement: { code: string; nom: string }
  region: { code: string; nom: string }
  communes: Record<string, { nom: string; population: number; siren: string; epci: string | null; departement: string; region: string }>
  epci: Record<string, { nom: string; population: number; departement_siege: string }>
}
export interface Budgets {
  millesime: string
  source: string
  annees: string[]
  agregats: string[]
  collectivites: Record<string, { nom: string; population: Record<string, number>; eur: Record<string, (number | null)[]> }>
  bloc_communal_consolide?: Budgets['collectivites']
}

const DEPENSES: [string, string][] = [
  ['frais_personnel', 'Personnel'],
  ['achats_charges_externes', 'Achats et services'],
  ['depenses_intervention', 'Aides et subventions versées'],
  ['charges_financieres', 'Intérêts de la dette'],
  ['depenses_equipement', 'Équipements (travaux, bâtiments)'],
  ['remboursement_dette', 'Remboursement d’emprunts'],
]

function lire(b: Budgets, eur: Record<string, (number | null)[]>, an: string, k: string): number | null {
  const v = eur[an]?.[b.agregats.indexOf(k)]
  return typeof v === 'number' ? v : null
}

export function blocBudget(b: Budgets, c: Budgets['collectivites'][string], titre: string, cle: boolean): string {
  const an = [...b.annees].reverse().find((a) => c.eur[a]) ?? b.annees[b.annees.length - 1]
  const total = lire(b, c.eur, an, 'depenses_totales')
  if (total === null || total <= 0) return `<h2>${h(titre)}</h2>${absent()}`
  const pop = c.population[an]
  const rec = lire(b, c.eur, an, 'recettes_fonctionnement')
  const etat = lire(b, c.eur, an, 'concours_etat')
  const impots = lire(b, c.eur, an, 'impots_locaux')
  const dette = lire(b, c.eur, an, 'encours_dette')
  const lignes = DEPENSES.map(([k, n]) => ({ k, n, v: lire(b, c.eur, an, k) })).filter((x) => x.v !== null && x.v > 0)
  return `<h2>${h(titre)}</h2>
<div class="carte"${cle ? ' data-cle' : ''}>
  <p class="grand-chiffre">${cle ? surligne(eurLisible(total)) : h(eurLisible(total))}</p>
  <p class="sous-chiffre">de dépenses en ${h(an)}${pop ? `, soit ${h(eur(total / pop))} par habitant` : ''}. Sur 100 € dépensés :</p>
  ${barres(
    lignes.map((x) => ({ nom: x.n, valeur: x.v!, texte: sur100((x.v! / total) * 100), detail: eurLisible(x.v!) })),
    undefined,
    `Dépenses de ${c.nom}, en euros sur 100 €`,
    -1,
  )}
  <ul>
    ${impots !== null && rec ? `<li>Impôts locaux perçus : ${h(eurLisible(impots))}, soit ${h(sur100((impots / rec) * 100))} sur 100 € de recettes de fonctionnement.</li>` : ''}
    ${etat !== null && rec ? `<li>Versé par l’État (dotations, compensations) : ${h(eurLisible(etat))}, soit ${h(sur100((etat / rec) * 100))} sur 100 € de recettes de fonctionnement.</li>` : ''}
    ${dette !== null ? `<li>Dette en cours : ${h(eurLisible(dette))}${pop ? ` (${h(eur(dette / pop))} par habitant)` : ''}.</li>` : ''}
  </ul>
  ${source(b.source, an)}
</div>`
}

/** Trois chiffres clés d'une collectivité, en cartes : par habitant, total, versé par l'État. */
export function clesBudget(b: Budgets, c: Budgets['collectivites'][string]): string {
  const an = [...b.annees].reverse().find((a) => c.eur[a]) ?? b.annees[b.annees.length - 1]
  const total = lire(b, c.eur, an, 'depenses_totales')
  if (total === null || total <= 0) return ''
  const pop = c.population[an]
  const etat = lire(b, c.eur, an, 'concours_etat')
  const dette = lire(b, c.eur, an, 'encours_dette')
  const items = [
    pop ? `<li class="cle-famille"><strong>${h(eur(total / pop))}</strong><span>dépensés par habitant en ${h(an)}</span>${badgeStatut('trace')}</li>` : '',
    etat !== null ? `<li><strong>${h(eurLisible(etat))}</strong><span>versés par l’État : dotations et compensations</span>${badgeStatut('trace')}</li>` : '',
    dette !== null ? `<li><strong>${h(eurLisible(dette))}</strong><span>de dette en cours${pop ? `, soit ${h(eur(dette / pop))} par habitant` : ''}</span>${badgeStatut('trace')}</li>` : '',
  ].filter(Boolean)
  return items.length ? `<ul class="cles" aria-label="Chiffres clés de ${h(c.nom)}">${items.join('')}</ul>` : ''
}

/** « de Nantes », « d’Angers », « du Mans », « des Abymes ». */
export function deCommune(nom: string): string {
  if (/^Le /.test(nom)) return `du ${nom.slice(3)}`
  if (/^Les /.test(nom)) return `des ${nom.slice(4)}`
  return /^[AEIOUYÀÂÉÈÊËÎÏÔÛÙŒ]/i.test(nom) ? `d’${nom}` : `de ${nom}`
}
export const titreCommune = (nom: string, departement: string) => `Budget ${deCommune(nom)} (${departement}) : dépenses, dotations, taux`

export async function rendre(cible: HTMLElement, params: URLSearchParams): Promise<Rendu | void> {
  const insee = params.get('insee') ?? ''
  if (!/^(\d{5}|2[AB]\d{3})$/.test(insee)) {
    location.hash = '#/local'
    return
  }
  const dep = departementDe(insee)
  const geo = await chargerSiPresent<Geo>(`local/geo/${dep}.json`)
  const g = geo?.communes[insee]
  if (!geo || !g) {
    cible.innerHTML = `<h1>Ta commune</h1>${absent('Commune introuvable dans les données publiées.')}<p><a href="#/local">Choisir une autre commune</a></p>`
    return
  }
  const epci = g.epci ? geo.epci[g.epci] : null
  const attente = (id: string, classe = '') => `<div id="${id}" class="section-donnees${classe}" aria-busy="true"><p class="chargement">Chargement…</p></div>`

  // Rendu progressif (recette perf, docs/RECETTE.md) : le titre et les liens s'affichent dès la géographie
  // chargée (environ 100 Ko) ; les budgets puis les dotations, taux et subventions arrivent ensuite.
  cible.innerHTML = `
<div class="entete-local">
  <div>
    <h1>${h(g.nom)}</h1>
    <p class="chapeau">${h(new Intl.NumberFormat('fr-FR').format(g.population))} habitants${epci ? `, ${h(epci.nom)}` : ''}, ${h(geo.departement.nom)} (${h(dep)}), région ${h(geo.region.nom)}. Ce que la commune dépense, ce qu’elle prélève et ce que l’État lui verse.</p>
    <p class="aide">Chaque collectivité a son propre budget : ne pas additionner commune, intercommunalité, département et région (une partie de l’argent passe de l’une à l’autre).</p>
    <p class="actions"><a class="bouton" href="#/local">Chercher une autre commune</a></p>
  </div>
  ${ouCest(dep, geo.departement.nom)}
</div>
${attente('sec-budgets', ' section-attente')}
<h2>Ce que l’État verse à la commune</h2>
${attente('sec-dotations')}
<h2>Les taux d’impôts locaux votés</h2>
${attente('sec-taux')}
<h2>Subventions votées et publiées</h2>
${attente('sec-subventions')}
<h2>Les projets aidés par l’État, de la commune et de son intercommunalité</h2>
${attente('sec-projets-etat')}
<h2>Logement social : la loi SRU</h2>
${attente('sec-sru')}
<h2>Syndicats, action sociale, transports, eau : les organismes rattachés</h2>
${attente('sec-organismes')}
<h2>Pour aller plus loin</h2>
<ul class="liens-sortie">
  <li><a href="#/explorer/collectivites">Les collectivités locales en France</a></li>
  <li><a href="${lien('/decisions/controle', { dep })}">Les rapports de contrôle dans le département ${h(geo.departement.nom)}</a></li>
  <li><a href="${lien('/explorer/ue', { dep })}">Les fonds européens dans le département ${h(geo.departement.nom)}</a></li>
  <li><a href="${fragmentDepartement(dep, geo.departement.nom)}">Les communes du département ${h(geo.departement.nom)}</a></li>
  <li><a href="${lien('/local/croiser', { insee })}">Comparer ${h(g.nom)} avec des communes qui se ressemblent</a></li>
  <li><a href="#/local">Choisir une autre commune</a></li>
</ul>
${partPersonnelle()}`

  const remplir = (id: string, html: string) => {
    const z = cible.querySelector<HTMLElement>(`#${id}`)
    if (!z) return
    z.innerHTML = html
    z.removeAttribute('aria-busy')
    z.classList.remove('section-attente')
    appliquerLargeurs(z)
  }

  const budgets = (async () => {
    const [bc, be, bd, br] = await Promise.all([
      chargerSiPresent<Budgets>(`local/budgets/communes/${dep}.json`),
      epci ? chargerSiPresent<Budgets>(`local/budgets/epci/${epci.departement_siege}.json`) : Promise.resolve(null),
      chargerSiPresent<Budgets>('local/budgets/departements.json'),
      chargerSiPresent<Budgets>('local/budgets/regions.json'),
    ])
    const commune = bc?.collectivites[insee]
    const ep = g.epci && be ? be.collectivites[g.epci] : null
    const bloc = g.epci && be?.bloc_communal_consolide ? be.bloc_communal_consolide[g.epci] : null
    const dpt = bd?.collectivites[g.departement]
    const reg = br?.collectivites[g.region]
    remplir(
      'sec-budgets',
      `${commune && bc ? clesBudget(bc, commune) : ''}${commune && bc ? blocBudget(bc, commune, `Le budget ${deCommune(commune.nom)}`, true) : absent('Budget de la commune non disponible.')}
${bloc && be ? blocBudget(be, bloc, `Le bloc communal (communes et intercommunalité, sans double compte)`, false) : ep && be ? blocBudget(be, ep, `L’intercommunalité : ${ep.nom}`, false) : ''}
${dpt && bd ? blocBudget(bd, dpt, `Le département : ${dpt.nom}`, false) : ''}
${reg && br ? blocBudget(br, reg, `La région : ${reg.nom}`, false) : ''}`,
    )
  })()

  // Fichiers plus bas dans la page : demandés après les budgets pour ne pas leur prendre la bande passante.
  const locales = budgets.then(async () => {
    const [dot, taux, dec] = await Promise.all([
      chargerSiPresent<{ source: string; millesime: string; annees: string[]; communes: Record<string, { eur: Record<string, Record<string, number>> }>; investissement_etat: Record<string, Record<string, { total: number; nb_projets: number; projets: [string, string | null, number, number][] }>> }>(`local/dotations/communes/${dep}.json`),
      chargerSiPresent<{ source: string; colonnes: string[]; communes: Record<string, Record<string, number[]>> }>(`local/taux/${dep}.json`),
      chargerSiPresent<{ source: string; limites: string; collectivites: Record<string, { type: string; code: string; nom: string; lignes: number; total_eur: number; annees: string[] }> }>('local/decisions/index.json'),
    ])
    const d = dot?.communes[insee]
    const t = taux?.communes[insee]
    const inv = dot?.investissement_etat[insee]
    const subv = dec ? Object.values(dec.collectivites).filter((c) => c.type === 'commune' && c.code === insee) : []
    const derniereDot = d ? Object.keys(d.eur).sort().pop() : undefined
    const tExo = t ? Object.keys(t).sort().pop() : undefined
    const col = (k: string) => taux?.colonnes.indexOf(k) ?? -1
    remplir(
      'sec-dotations',
      d && derniereDot && dot
        ? `<div class="tableau-defile"><table><caption>Dotation globale de fonctionnement (DGF), euros</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">DGF totale</th><th scope="col" class="nombre">Par habitant</th></tr></thead><tbody>${Object.keys(d.eur)
            .sort()
            .reverse()
            .map((a) => `<tr><th scope="row">${a}</th><td class="nombre">${d.eur[a].dgf_totale !== undefined ? h(eur(d.eur[a].dgf_totale)) : '–'}</td><td class="nombre">${d.eur[a].dgf_totale !== undefined ? h(eur(d.eur[a].dgf_totale / g.population)) : '–'}</td></tr>`)
            .join('')}</tbody></table></div>
${
  inv
    ? `<h3>Subventions de l’État aux projets d’investissement</h3><ul>${Object.keys(inv)
        .sort()
        .reverse()
        .slice(0, 4)
        .map((a) => `<li>${a} : ${h(eurLisible(inv[a].total))} pour ${inv[a].nb_projets} projet${inv[a].nb_projets > 1 ? 's' : ''}${inv[a].projets[0]?.[1] ? ` (dont « ${h(inv[a].projets[0][1])} »)` : ''}</li>`)
        .join('')}</ul>`
    : ''
}${source(dot.source, dot.millesime)}`
        : absent('Dotations non disponibles.'),
    )
    remplir(
      'sec-taux',
      t && tExo && taux
        ? `<div class="tableau-defile"><table><caption>Taux votés en % (commune, intercommunalité et taxes annexes)</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Taxe foncière bâti</th><th scope="col" class="nombre">Taxe foncière non bâti</th><th scope="col" class="nombre">Taxe d’habitation (résidences secondaires)</th><th scope="col" class="nombre">Ordures ménagères</th></tr></thead><tbody>${Object.keys(t)
            .sort()
            .reverse()
            .map(
              (a) =>
                `<tr><th scope="row">${a}</th>${['tfb_global', 'tfnb_global', 'thrs_global', 'teom_taux_plein']
                  .map((k) => `<td class="nombre">${col(k) >= 0 && t[a][col(k)] !== null && t[a][col(k)] !== undefined ? h(pct(t[a][col(k)], 2)) : '–'}</td>`)
                  .join('')}</tr>`,
            )
            .join('')}</tbody></table></div>${source(taux.source)}`
        : absent('Taux non disponibles.'),
    )
    remplir(
      'sec-subventions',
      `${
        subv.length
          ? `<ul>${subv.map((s) => `<li>${h(s.nom)} : ${h(eurLisible(s.total_eur))} sur ${s.lignes} ligne${s.lignes > 1 ? 's' : ''} publiées${s.annees.length ? ` (${h(s.annees.join(', '))})` : ''}</li>`).join('')}</ul>`
          : '<p>Aucune liste de subventions publiée en données ouvertes pour cette commune.</p>'
      }
${dec ? `<p class="aide">${h(dec.limites)}</p>` : ''}`,
    )
  })
  // Données par département (territoires, local_satellites) : projets aidés par l'État, logement social, organismes.
  const territoires = budgets.then(async () => {
    if (enPrerendu()) {
      for (const id of ['sec-projets-etat', 'sec-sru', 'sec-organismes']) remplir(id, AFFICHE_DANS_LE_NAVIGATEUR)
      return
    }
    const [ter, syn, ccas, mob, eau] = await Promise.all([
      chargerSiPresent<Territoire>(`territoires/${dep}.json`),
      chargerSiPresent<FichierSyndicats>(`local_satellites/syndicats/${dep}.json`),
      chargerSiPresent<FichierCcas>(`local_satellites/ccas/${dep}.json`),
      chargerSiPresent<FichierMobilite>(`local_satellites/mobilite/${dep}.json`),
      chargerSiPresent<FichierEau>(`local_satellites/eau/${dep}.json`),
    ])
    let projets = absent('Projets non disponibles.')
    if (ter) {
      // Un bénéficiaire (l'intercommunalité) peut être publié dans le fichier d'un autre département.
      const refs = ter.investissement_etat.par_commune[insee] ?? []
      const autres = [...new Set(refs.map(([, d]) => d).filter((d) => d !== dep))]
      const fichiers = new Map<string, Territoire | null>([[dep, ter]])
      for (const d of autres) fichiers.set(d, /^(\d{2,3}|2[AB])$/.test(d) ? await chargerSiPresent<Territoire>(`territoires/${d}.json`) : null)
      const benef = refs
        .map(([id, d]) => fichiers.get(d)?.investissement_etat.beneficiaires.find((b) => b.id === id))
        .filter((b): b is Beneficiaire => !!b)
        .sort((a, b) => (a.type === 'commune' ? 0 : 1) - (b.type === 'commune' ? 0 : 1) || a.nom.localeCompare(b.nom, 'fr'))
      projets = blocInvestissementCommune(benef, ter)
    }
    remplir('sec-projets-etat', projets)
    remplir('sec-sru', ter ? blocSruCommune(ter.sru?.communes[insee], ter) : absent('Inventaire non disponible.'))
    remplir('sec-organismes', blocOrganismesCommune(insee, syn, ccas, mob, eau))
  })
  const suite = Promise.all([locales, territoires]).then(() => undefined)
  return {
    titre: titreCommune(g.nom, geo.departement.nom),
    adresse: fragmentCommune(insee, g.nom, g.population),
    fil: [
      { nom: geo.departement.nom, fragment: fragmentDepartement(dep, geo.departement.nom) },
      { nom: g.nom, fragment: fragmentCommune(insee, g.nom, g.population) },
    ],
    description: `Budget ${deCommune(g.nom)} (${geo.departement.nom}, ${new Intl.NumberFormat('fr-FR').format(g.population)} habitants) : dépenses de la commune et par habitant, dotations versées par l’État, taux d’impôts locaux votés, budgets de l’intercommunalité, du département et de la région.`,
    suite: suite.catch((e) => {
      console.error(e)
      cible.querySelectorAll<HTMLElement>('.section-donnees[aria-busy]').forEach((z) => {
        z.innerHTML = absent()
        z.removeAttribute('aria-busy')
        z.classList.remove('section-attente')
      })
    }),
  }
}

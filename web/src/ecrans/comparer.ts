// Comparer deux communes côte à côte (site/data/local/ et, s'il est publié, site/data/revenus_communes/).
// Mêmes indicateurs, mêmes unités (euros par habitant, taux en %), même année quand les deux communes l'ont publiée,
// et pour chaque indicateur des barres sur la même échelle. Aucun classement, aucune couleur de valeur :
// les deux communes portent la couleur de la famille, dans l'ordre choisi par la personne.
// Adresse partageable : #/local/comparer?a=<insee>&b=<insee>.
import { fragmentCommune } from '../chemins'
import { partPersonnelle } from '../composants/hub'
import { TOUS_DEPARTEMENTS, departementDe } from '../departements'
import { chargerSiPresent } from '../donnees'
import { lien, type Rendu } from '../routeur'
import { absent, appliquerLargeurs, barres, entier, eur, h, pct, source } from '../util'
import { deCommune, type Budgets, type Geo } from './commune'

const INSEE = /^(\d{5}|2[AB]\d{3})$/

interface Dotations {
  source: string
  millesime: string
  communes: Record<string, { eur: Record<string, Record<string, number>> }>
}
interface Taux {
  source: string
  colonnes: string[]
  communes: Record<string, Record<string, (number | null)[]>>
}
/**
 * Revenu fiscal médian par commune, produit par l'axe revenus_communes (site/data/revenus_communes/<dep>.json).
 * Forme attendue : { millesime, source, communes: { <insee>: { revenu_median: number | null, annee?: string, mention?: string } } }.
 * Lecture tolérante (revenu_fiscal_median, mediane) tant que le contrat de cet axe n'est pas publié.
 */
interface Revenus {
  millesime?: string
  source?: string
  annee?: string
  communes?: Record<string, Record<string, unknown>>
}

/** Une commune choisie et ses fichiers. */
interface Cote {
  insee: string
  dep: string
  geo: Geo
  nom: string
  population: number
  epci: string | null
  budgets: Budgets | null
  dotations: Dotations | null
  taux: Taux | null
  revenus: Revenus | null
}

/** Indicateurs du budget, en euros par habitant (agrégats OFGL des comptes de gestion). */
const BUDGET: { titre: string; lignes: [string, string][] }[] = [
  {
    titre: 'Dépenses et recettes',
    lignes: [
      ['depenses_totales', 'Dépenses totales'],
      ['depenses_fonctionnement', 'Dépenses de fonctionnement'],
      ['recettes_fonctionnement', 'Recettes de fonctionnement'],
      ['impots_locaux', 'Impôts locaux perçus'],
    ],
  },
  {
    titre: 'Dette et épargne',
    lignes: [
      ['encours_dette', 'Dette en cours'],
      ['epargne_brute', 'Épargne brute (recettes moins dépenses de fonctionnement)'],
      ['remboursement_dette', 'Remboursement d’emprunts dans l’année'],
    ],
  },
  {
    titre: 'Investissement',
    lignes: [
      ['depenses_investissement', 'Dépenses d’investissement'],
      ['depenses_equipement', 'Équipements (travaux, bâtiments)'],
    ],
  },
]

const TAUX: [string, string][] = [
  ['tfb_commune', 'Taxe foncière sur le bâti, part de la commune'],
  ['tfb_global', 'Taxe foncière sur le bâti, tous niveaux'],
  ['tfnb_global', 'Taxe foncière sur le non bâti, tous niveaux'],
  ['thrs_global', 'Taxe d’habitation sur les résidences secondaires, tous niveaux'],
  ['teom_taux_plein', 'Taxe d’enlèvement des ordures ménagères'],
]

type Valeur = number | null

function lireBudget(b: Budgets | null, insee: string, an: string, k: string): Valeur {
  const c = b?.collectivites[insee]
  const v = c?.eur[an]?.[b!.agregats.indexOf(k)]
  return typeof v === 'number' ? v : null
}

/** Dernière année publiée pour les deux, sinon la dernière de chacune. */
function annees(a: string[], b: string[]): [string | undefined, string | undefined] {
  const commune = [...a].filter((x) => b.includes(x)).sort().pop()
  if (commune) return [commune, commune]
  return [[...a].sort().pop(), [...b].sort().pop()]
}

export function revenuMedian(r: Revenus | null, insee: string): { valeur: Valeur; annee?: string; mention?: string } | null {
  const c = r?.communes?.[insee]
  if (!r || !c) return null
  const brut = c.revenu_median ?? c.revenu_fiscal_median ?? c.mediane
  return {
    valeur: typeof brut === 'number' ? brut : null,
    annee: typeof c.annee === 'string' ? c.annee : (r.annee ?? r.millesime),
    mention: typeof c.mention === 'string' ? c.mention : undefined,
  }
}

const cellule = (v: Valeur, f: (x: number) => string, mention = 'non publié') => (v === null ? `<td class="nombre">${h(mention)}</td>` : `<td class="nombre">${h(f(v))}</td>`)

/**
 * Un tableau (lecture exacte, accessible) et, pour chaque ligne, deux barres sur la même échelle.
 * L'ordre des communes est celui du choix ; aucune n'est mise en avant.
 */
function comparaison(
  caption: string,
  noms: [string, string],
  entetes: [string, string],
  lignes: { nom: string; a: Valeur; b: Valeur }[],
  format: (x: number) => string,
): string {
  const utiles = lignes.filter((l) => l.a !== null || l.b !== null)
  if (!utiles.length) return absent('Donnée non publiée pour ces deux communes.')
  const tableau = `<div class="tableau-defile"><table><caption>${h(caption)}</caption><thead><tr><th scope="col">Indicateur</th><th scope="col" class="nombre">${h(entetes[0])}</th><th scope="col" class="nombre">${h(entetes[1])}</th></tr></thead><tbody>${utiles
    .map((l) => `<tr><th scope="row">${h(l.nom)}</th>${cellule(l.a, format)}${cellule(l.b, format)}</tr>`)
    .join('')}</tbody></table></div>`
  const paires = utiles
    .map((l) => {
      const max = Math.max(Math.abs(l.a ?? 0), Math.abs(l.b ?? 0))
      const el = (nom: string, v: Valeur) => ({ nom, valeur: v !== null && v > 0 ? v : 0, texte: v === null ? 'non publié' : format(v) })
      return `<li><p class="comparer-indicateur">${h(l.nom)}</p>${barres([el(noms[0], l.a), el(noms[1], l.b)], max, `${l.nom} : ${noms[0]} et ${noms[1]}, même échelle`, -1)}</li>`
    })
    .join('')
  return `${tableau}<ul class="comparer-paires" aria-label="${h(caption)}, en barres sur la même échelle">${paires}</ul>`
}

async function chargerCote(insee: string): Promise<Cote | null> {
  const dep = departementDe(insee)
  const geo = await chargerSiPresent<Geo>(`local/geo/${dep}.json`)
  const g = geo?.communes[insee]
  if (!geo || !g) return null
  const [budgets, dotations, taux, revenus] = await Promise.all([
    chargerSiPresent<Budgets>(`local/budgets/communes/${dep}.json`),
    chargerSiPresent<Dotations>(`local/dotations/communes/${dep}.json`),
    chargerSiPresent<Taux>(`local/taux/${dep}.json`),
    chargerSiPresent<Revenus>(`revenus_communes/${dep}.json`),
  ])
  return { insee, dep, geo, nom: g.nom, population: g.population, epci: g.epci, budgets, dotations, taux, revenus }
}

function formulaire(a: string, b: string): string {
  const options = TOUS_DEPARTEMENTS.map(([c, n]) => `<option value="${c}">${c} ${h(n)}</option>`).join('')
  const bloc = (cote: 'a' | 'b', titre: string) => `<fieldset>
  <legend>${titre}</legend>
  <label for="dep-${cote}">Département</label>
  <select id="dep-${cote}" data-cote="${cote}"><option value="">Choisir</option>${options}</select>
  <div id="com-${cote}-bloc" hidden>
    <label for="com-${cote}">Commune</label>
    <select id="com-${cote}" name="${cote}"></select>
  </div>
</fieldset>`
  return `<form id="choix-comparer" class="carte carte-contour" data-a="${h(a)}" data-b="${h(b)}">
  <div class="colonnes c-6-6">
    ${bloc('a', 'Première commune')}
    ${bloc('b', 'Deuxième commune')}
  </div>
  <p class="actions"><button type="submit" class="bouton-principal">Comparer</button></p>
  <p id="msg-comparer" class="message-champ" hidden></p>
</form>`
}

/** Branche les listes : la commune se choisit après le département (fichiers chargés à la demande). */
async function brancher(cible: HTMLElement, a: string, b: string) {
  const form = cible.querySelector<HTMLFormElement>('#choix-comparer')!
  const charger = async (cote: 'a' | 'b', dep: string, choisie?: string) => {
    const com = cible.querySelector<HTMLSelectElement>(`#com-${cote}`)!
    cible.querySelector<HTMLElement>(`#com-${cote}-bloc`)!.hidden = !dep
    if (!dep) return
    com.innerHTML = '<option value="">Chargement…</option>'
    const g = await chargerSiPresent<{ communes: Record<string, { nom: string }> }>(`local/geo/${dep}.json`)
    const liste = Object.entries(g?.communes ?? {}).sort((x, y) => x[1].nom.localeCompare(y[1].nom, 'fr'))
    com.innerHTML = `<option value="">Choisir</option>${liste.map(([c, v]) => `<option value="${c}"${c === choisie ? ' selected' : ''}>${h(v.nom)}</option>`).join('')}`
    if (choisie) com.value = choisie
  }
  const prets: Promise<void>[] = []
  for (const [cote, insee] of [['a', a], ['b', b]] as const) {
    const dep = cible.querySelector<HTMLSelectElement>(`#dep-${cote}`)!
    dep.addEventListener('change', () => charger(cote, dep.value))
    if (insee) {
      dep.value = departementDe(insee)
      prets.push(charger(cote, dep.value, insee))
    }
  }
  form.addEventListener('submit', (e) => {
    e.preventDefault()
    const va = cible.querySelector<HTMLSelectElement>('#com-a')!.value
    const vb = cible.querySelector<HTMLSelectElement>('#com-b')!.value
    const m = cible.querySelector<HTMLElement>('#msg-comparer')!
    if (!va || !vb) {
      m.textContent = 'Choisis un département puis une commune, de chaque côté.'
      m.hidden = false
      return
    }
    if (va === vb) {
      m.textContent = 'Choisis deux communes différentes.'
      m.hidden = false
      return
    }
    location.hash = lien('/local/comparer', { a: va, b: vb })
  })
  await Promise.all(prets)
}

const RAPPEL =
  'Les communes n’ont ni la même taille ni les mêmes compétences : selon l’intercommunalité, une partie des services (eau, déchets, voirie, transports) est payée par la commune ou par l’intercommunalité, ce qui change les montants par habitant. Ces chiffres se lisent côte à côte, sans classement.'

function rendreComparaison(x: Cote, y: Cote): string {
  const noms: [string, string] = [x.nom, y.nom]
  const epci = (c: Cote) => (c.epci ? c.geo.epci[c.epci]?.nom : null)
  const fiche = (c: Cote) => `<div class="carte carte-contour">
  <h3><a href="${fragmentCommune(c.insee, c.nom, c.population)}">${h(c.nom)}</a></h3>
  <p>${h(entier(c.population))} habitants, ${h(c.geo.departement.nom)} (${h(c.dep)})${epci(c) ? `, ${h(epci(c))}` : ''}.</p>
</div>`

  // Budgets : euros par habitant, même année quand c'est possible.
  const ansBudget = (c: Cote) => Object.keys(c.budgets?.collectivites[c.insee]?.eur ?? {})
  const [anA, anB] = annees(ansBudget(x), ansBudget(y))
  const parHab = (c: Cote, an: string | undefined, k: string): Valeur => {
    if (!an) return null
    const v = lireBudget(c.budgets, c.insee, an, k)
    const pop = c.budgets?.collectivites[c.insee]?.population[an]
    return v !== null && pop ? v / pop : null
  }
  const entetesAn = (a?: string, b?: string): [string, string] => [a ? `${x.nom} (${a})` : x.nom, b ? `${y.nom} (${b})` : y.nom]
  const memeAnnee = anA === anB
  const sourceBudget = x.budgets ?? y.budgets
  const budget = anA || anB
    ? BUDGET.map(
        (s) => `<h3>${h(s.titre)}</h3>
${comparaison(
  `${s.titre}, en euros par habitant${memeAnnee && anA ? `, ${anA}` : ''}`,
  noms,
  entetesAn(anA, anB),
  s.lignes.map(([k, n]) => ({ nom: n, a: parHab(x, anA, k), b: parHab(y, anB, k) })),
  eur,
)}`,
      ).join('') +
      (memeAnnee ? '' : `<p class="aide">Années différentes : la dernière année publiée n’est pas la même pour les deux communes.</p>`) +
      (sourceBudget ? source(sourceBudget.source, sourceBudget.millesime) : '')
    : absent('Budgets non disponibles pour ces deux communes.')

  // Dotations de l'État : concours de l'État dans les comptes, et dotation globale de fonctionnement notifiée.
  const ansDot = (c: Cote) => Object.keys(c.dotations?.communes[c.insee]?.eur ?? {}).filter((a) => typeof c.dotations?.communes[c.insee]?.eur[a]?.dgf_totale === 'number')
  const [dA, dB] = annees(ansDot(x), ansDot(y))
  const dgf = (c: Cote, an?: string): Valeur => {
    const v = an ? c.dotations?.communes[c.insee]?.eur[an]?.dgf_totale : undefined
    return typeof v === 'number' && c.population ? v / c.population : null
  }
  const sourceDot = x.dotations ?? y.dotations
  const etat = `${comparaison(
    `Versé par l’État, en euros par habitant`,
    noms,
    [x.nom, y.nom],
    [
      { nom: `Dotations et compensations dans les comptes${memeAnnee && anA ? ` (${anA})` : ''}`, a: parHab(x, anA, 'concours_etat'), b: parHab(y, anB, 'concours_etat') },
      { nom: `Dotation globale de fonctionnement notifiée${dA === dB && dA ? ` (${dA})` : ''}`, a: dgf(x, dA), b: dgf(y, dB) },
    ],
    eur,
  )}
<p class="aide">Deux sources distinctes, montrées l’une à côté de l’autre et jamais additionnées : les comptes de la commune (tout ce que l’État verse, y compris les compensations d’impôts) et la dotation globale de fonctionnement notifiée par l’État, rapportée à la population légale.</p>
${sourceDot ? source(sourceDot.source, sourceDot.millesime) : ''}`

  // Taux votés.
  const ansTaux = (c: Cote) => Object.keys(c.taux?.communes[c.insee] ?? {})
  const [tA, tB] = annees(ansTaux(x), ansTaux(y))
  const taux = (c: Cote, an: string | undefined, k: string): Valeur => {
    const i = c.taux?.colonnes.indexOf(k) ?? -1
    const v = an && i >= 0 ? c.taux?.communes[c.insee]?.[an]?.[i] : null
    return typeof v === 'number' ? v : null
  }
  const sourceTaux = x.taux ?? y.taux
  const tauxHtml = `${comparaison(
    `Taux d’imposition votés, en %${tA === tB && tA ? `, ${tA}` : ''}`,
    noms,
    entetesAn(tA, tB),
    TAUX.map(([k, n]) => ({ nom: n, a: taux(x, tA, k), b: taux(y, tB, k) })),
    (v) => pct(v, 2),
  )}
<p class="aide">Un taux s’applique à une base (la valeur locative cadastrale) qui diffère d’une commune à l’autre : deux taux égaux ne donnent pas le même impôt.</p>
${sourceTaux ? source(sourceTaux.source) : ''}`

  // Revenu fiscal médian : seulement si l'axe revenus_communes est publié.
  const rx = revenuMedian(x.revenus, x.insee)
  const ry = revenuMedian(y.revenus, y.insee)
  const sourceRev = x.revenus ?? y.revenus
  const revenu = sourceRev
    ? `${comparaison(
        `Revenu médian des habitants, en euros par an`,
        noms,
        entetesAn(rx?.annee, ry?.annee),
        [{ nom: 'Revenu médian', a: rx?.valeur ?? null, b: ry?.valeur ?? null }],
        eur,
      )}
${[rx, ry].some((r) => r && r.valeur === null) ? `<p class="aide">Non publié : valeur couverte par le secret statistique ou absente de la source${[rx?.mention, ry?.mention].filter(Boolean).length ? ` (${h([rx?.mention, ry?.mention].filter(Boolean).join(' ; '))})` : ''}.</p>` : ''}
${source(sourceRev.source ?? '', sourceRev.millesime)}`
    : absent('Revenu médian des habitants : donnée en cours d’intégration.')

  return `<h2>Les deux communes</h2>
<div class="colonnes c-6-6">${fiche(x)}${fiche(y)}</div>
<p class="aide">${h(RAPPEL)}</p>
<h2>Budget, en euros par habitant</h2>
${budget}
<h2>Ce que l’État verse</h2>
${etat}
<h2>Les taux d’impôts locaux votés</h2>
${tauxHtml}
<h2>Revenu des habitants</h2>
${revenu}
<h2>Partager cette comparaison</h2>
<p>L’adresse de cette page garde les deux communes choisies : tu peux la copier pour la partager.</p>
<p class="actions"><a class="bouton" href="${lien('/local/comparer', { a: y.insee, b: x.insee })}">Inverser l’ordre des communes</a></p>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams): Promise<Rendu | void> {
  const a = INSEE.test(params.get('a') ?? '') ? params.get('a')! : ''
  const b = INSEE.test(params.get('b') ?? '') ? params.get('b')! : ''
  const complet = !!a && !!b && a !== b
  cible.innerHTML = `
<h1>Comparer deux communes</h1>
<p class="chapeau">Deux communes côte à côte, avec les mêmes indicateurs et les mêmes échelles : dépenses et recettes par habitant, dette, épargne, investissement, versements de l’État, taux d’impôts locaux votés.</p>
<p class="aide">${h(RAPPEL)}</p>
${formulaire(a, b)}
${a && b && a === b ? '<p class="message-champ">Les deux communes de l’adresse sont identiques : choisis-en une autre.</p>' : ''}
<div id="sec-comparer"${complet ? ' class="section-donnees" aria-busy="true"><p class="chargement">Chargement…</p>' : '>'}</div>
<h2>Pour aller plus loin</h2>
<ul class="liens-sortie">
  <li><a href="#/local">Budget de ma commune</a></li>
  <li><a href="#/local/croiser">Comparer des communes qui se ressemblent</a> : même densité, même strate de population, même aire d’attraction</li>
  <li><a href="#/explorer/collectivites">Les collectivités locales en France</a></li>
</ul>
${partPersonnelle()}`
  const listes = brancher(cible, a, b)
  if (!complet) {
    await listes
    return
  }
  const [x, y] = await Promise.all([chargerCote(a), chargerCote(b), listes]).then(([p, q]) => [p, q] as const)
  const z = cible.querySelector<HTMLElement>('#sec-comparer')!
  z.removeAttribute('aria-busy')
  if (!x || !y) {
    z.innerHTML = absent('Commune introuvable dans les données publiées.')
    return
  }
  z.innerHTML = rendreComparaison(x, y)
  appliquerLargeurs(z)
  return {
    titre: `Comparer ${x.nom} et ${y.nom} : budget par habitant, dette, taux`,
    description: `Budget ${deCommune(x.nom)} et ${deCommune(y.nom)} côte à côte : dépenses et dette par habitant, versements de l’État, taux d’impôts locaux votés, mêmes échelles, sans classement.`,
  }
}

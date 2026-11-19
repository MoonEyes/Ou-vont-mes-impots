// Bloc « Investissement réalisé et délibérations publiées » de la page commune (site/data/investissement_communes/
// et site/data/deliberations/). Rien dans le HTML prérendu : le bloc est ajouté par le navigateur quand la section
// des subventions approche de l'écran (IntersectionObserver, absent du prérendu), et ses données ne sont chargées
// qu'au clic. Montants tracés (balances DGFiP), somme « équipement » calculée par le site, crédits votés tracés
// (document budgétaire publié par la commune) ; aucun taux ni écart calculé (règle 13).
import { chargerSiPresent } from '../donnees'
import { absent, badgeStatut, eur, h, pct, source, traitStatut, badgeCalcule } from '../util'
import { encadreManque, MANQUES } from '../composants/manque'

export interface InvIndex {
  millesime: string
  source: string
  annees: string[]
  colonnes: string[]
  definitions: Record<string, string>
  presentation: string
  methode: string
  methode_vote: string
  regle_null: string
}
export interface InvDep {
  millesime: string
  source: string
  annees: string[]
  colonnes: string[]
  communes: Record<string, { nom: string; siren: string; m: Record<string, number[]>; vote?: Record<string, { budget_primitif?: number[]; credits_ouverts?: number[]; jeux: string[] }> }>
}
export interface Couverture {
  publient: number
  total: number | null
  libelle: string
  part_nombre: number | null
  part_population?: number
}
export interface DelibIndex {
  millesime: string
  source: string
  date_releve: string
  presentation: string
  absence: string
  absence_detail: string
  methode: string
  regle: string
  couverture: Record<string, Couverture>
  matieres: Record<string, string>
  collectivites: Record<string, { nom: string; type: string; code: string | null; total: number; annees: string[] }>
}
export interface DelibColl {
  millesime: string
  source: string
  nom: string
  jeux: { id: string; titre: string; url: string; licence: string }[]
  matieres: Record<string, string>
  comptes: Record<string, Record<string, number>>
  exclus: Record<string, Record<string, number>>
  motifs: Record<string, string>
  recentes: Record<string, [string, string | null, string, string | null, number][]>
  par_matiere: number
}
export interface BudgetsPublies {
  millesime: string
  source: string
  etapes: Record<string, string>
  collectivites: Record<string, { nom: string; documents: [string, string, string][] }>
}
export interface Contexte {
  insee: string
  dep: string
  nom: string
  siren: string | null
  epci: string | null
  nomEpci: string | null
}

export const TITRE = 'Investissement réalisé et délibérations publiées'
const montant = (x: number | undefined | null) => (x === undefined || x === null ? '–' : h(eur(x)))
const nonPublie = () => `<span class="badge">${traitStatut('nonpub')}Non publié</span>`

/** Tableau des dépenses d'équipement mandatées, exercice par exercice, avec les crédits votés quand ils sont publiés. */
export function blocInvestissement(idx: InvIndex, dep: InvDep | null, ctx: Contexte): string {
  const c = dep?.communes[ctx.insee]
  if (!dep || !c) return absent(`Aucune balance comptable publiée sous le SIREN de ${ctx.nom} dans les exercices ${idx.annees[0]} à ${idx.annees[idx.annees.length - 1]}.`)
  const col = (k: string) => dep.colonnes.indexOf(k)
  const avecVote = !!c.vote && Object.keys(c.vote).length > 0
  const annees = [...dep.annees].sort().reverse()
  const ligne = (a: string) => {
    const m = c.m[a]
    const v = c.vote?.[a]
    const vote = avecVote ? `<td class="nombre">${v?.budget_primitif ? montant(v.budget_primitif[0]) : '–'}</td><td class="nombre">${v?.credits_ouverts ? montant(v.credits_ouverts[0]) : '–'}</td>` : ''
    if (!m) return `<tr><th scope="row">${h(a)}</th><td colspan="5">${nonPublie()}</td>${vote}</tr>`
    return `<tr><th scope="row">${h(a)}</th><td class="nombre">${montant(m[col('equipement')])}</td><td class="nombre">${montant(m[col('c21')])}</td><td class="nombre">${montant(m[col('c23')])}</td><td class="nombre">${montant(m[col('c20_hors_204')])}</td><td class="nombre">${montant(m[col('c204')])}</td>${vote}</tr>`
  }
  const enteteVote = avecVote ? '<th scope="col" class="nombre">Crédits votés au budget primitif</th><th scope="col" class="nombre">Crédits ouverts sur l’année (compte administratif)</th>' : ''
  return `<p>${h(idx.presentation)}</p>
<p class="aide">${badgeStatut('trace')} : montants de la balance comptable (DGFiP). Colonne « Équipement » ${badgeCalcule('somme des comptes 20 hors 204, 21 et 23 d’une même balance (même commune, même exercice)')} ${nonPublie()} : aucune balance publiée pour cet exercice sous le numéro SIREN de la commune actuelle (commune créée plus tard, fusion ou comptes non publiés) ; ce n’est pas un montant nul.</p>
<div class="tableau-defile"><table><caption>Dépenses d’équipement réellement payées par ${h(c.nom)} (budget principal), en euros, par exercice</caption><thead><tr><th scope="col">Exercice</th><th scope="col" class="nombre">Équipement (20 hors 204, 21, 23)</th><th scope="col" class="nombre">dont achats et biens achevés (21)</th><th scope="col" class="nombre">dont travaux en cours (23)</th><th scope="col" class="nombre">dont études et logiciels (20 hors 204)</th><th scope="col" class="nombre">Subventions d’équipement versées (204, à part)</th>${enteteVote}</tr></thead><tbody>${annees.map(ligne).join('')}</tbody></table></div>
${
  avecVote
    ? `<p class="aide">${h(idx.methode_vote)}</p>`
    : `<p class="aide">${h(c.nom)} ne publie pas son budget au format national sur data.gouv.fr : les crédits votés ne peuvent pas être mis à côté des dépenses payées.</p>`
}
<details><summary>Définitions et méthode</summary><ul>${idx.colonnes.map((k) => `<li>${h(idx.definitions[k] ?? k)}</li>`).join('')}</ul><p>${h(idx.methode)}</p></details>
${source(dep.source, dep.millesime)}`
}

/** Phrase de couverture : collectivités qui publient, part en nombre et en population (calculées par le site). */
export function phraseCouverture(d: DelibIndex): string {
  const c = d.couverture.commune
  if (!c) return ''
  const parts = [c.part_nombre !== null ? `${pct(100 * c.part_nombre, 1)} des communes` : null, c.part_population !== undefined ? `${pct(100 * c.part_population, 1)} de la population` : null].filter(Boolean)
  const autres = ['epci', 'departement', 'region']
    .map((t) => d.couverture[t])
    .filter((x): x is Couverture => !!x)
    .map((x) => `${x.publient} ${x.libelle}${x.total ? ` sur ${x.total}` : ''}`)
  return `<p>${new Intl.NumberFormat('fr-FR').format(c.publient)} communes sur ${new Intl.NumberFormat('fr-FR').format(c.total ?? 0)} publient leurs délibérations en données ouvertes au format national${parts.length ? `, soit ${parts.join(' et ')}` : ''} ${badgeCalcule(d.methode)} ; ${h(autres.join(', '))}.</p>`
}

/** Délibérations d'une collectivité : comptes par année, récentes par matière, exclusions comptées. */
export function blocDeliberations(d: DelibIndex, coll: DelibColl | null, nom: string): string {
  if (!coll) return encadreManque(MANQUES.deliberations(nom, d))
  const annees = Object.keys(coll.comptes).sort().reverse()
  const total = annees.reduce((s, a) => s + Object.values(coll.comptes[a]).reduce((x, y) => x + y, 0), 0)
  const exclus = Object.values(coll.exclus).reduce((s, v) => s + Object.values(v).reduce((x, y) => x + y, 0), 0)
  const mats = Object.keys(coll.matieres).sort()
  const tableau = `<div class="tableau-defile"><table><caption>Délibérations publiées par ${h(coll.nom)}, par année et par thème (matière de la nomenclature des actes)</caption><thead><tr><th scope="col">Année</th>${mats.map((m) => `<th scope="col" class="nombre">${h(coll.matieres[m])}</th>`).join('')}</tr></thead><tbody>${annees
    .map((a) => `<tr><th scope="row">${h(a)}</th>${mats.map((m) => `<td class="nombre">${coll.comptes[a][m] ?? 0}</td>`).join('')}</tr>`)
    .join('')}</tbody></table></div>`
  const recentes = Object.keys(coll.recentes)
    .sort()
    .map(
      (m) =>
        `<details><summary>${h(d.matieres[m] ?? m)} : les plus récentes</summary><ul>${coll.recentes[m]
          .map(([date, code, objet, lien]) => `<li><time datetime="${h(date)}">${h(new Date(date + 'T00:00:00Z').toLocaleDateString('fr-FR', { timeZone: 'UTC' }))}</time>${code ? ` (${h(code)})` : ''} : ${h(objet)}${lien ? ` <a href="${h(lien)}" rel="noopener noreferrer">acte sur le site de la collectivité</a>` : ''}</li>`)
          .join('')}</ul></details>`,
    )
    .join('')
  const motifs = Object.keys(coll.motifs)
  return `<h4>${h(coll.nom)}</h4>
<p>${new Intl.NumberFormat('fr-FR').format(total)} délibérations publiées en données ouvertes${annees.length ? ` (${h(annees[annees.length - 1])} à ${h(annees[0])})` : ''}.${exclus ? ` ${new Intl.NumberFormat('fr-FR').format(exclus)} n’apparaissent pas ci-dessous : leur objet peut désigner une personne (${h(motifs.map((k) => coll.motifs[k]).join(' ; '))}) ; elles sont comptées dans le tableau.` : ''}</p>
${tableau}${recentes}
${source(`${coll.source} ; jeux : ${coll.jeux.map((j) => `${j.titre} (${j.licence})`).join(', ')}`, coll.millesime)}`
}

export function blocBudgetsPublies(b: BudgetsPublies | null, siren: string | null, nom: string): string {
  const c = b && siren ? b.collectivites[siren] : null
  if (!b || !c) return ''
  return `<p>${h(nom)} publie aussi ses documents budgétaires au format national : ${h(c.documents.map(([a, e]) => `${b.etapes[e] ?? e} ${a}`).join(', '))}.</p>${source(b.source, b.millesime)}`
}

/** Charge les fichiers et remplit la zone (au clic). */
export async function remplir(zone: HTMLElement, ctx: Contexte): Promise<void> {
  zone.setAttribute('aria-busy', 'true')
  zone.innerHTML = '<p class="chargement">Chargement…</p>'
  const [idx, dep, di, bp] = await Promise.all([
    chargerSiPresent<InvIndex>('investissement_communes/index.json'),
    chargerSiPresent<InvDep>(`investissement_communes/communes/${ctx.dep}.json`),
    chargerSiPresent<DelibIndex>('deliberations/index.json'),
    chargerSiPresent<BudgetsPublies>('deliberations/budgets.json'),
  ])
  const sirens = [ctx.siren, ctx.epci].filter((s): s is string => !!s)
  const colls = await Promise.all(sirens.map((s) => (di?.collectivites[s] ? chargerSiPresent<DelibColl>(`deliberations/collectivites/${s}.json`) : Promise.resolve(null))))
  const noms = [ctx.nom, ctx.nomEpci ?? 'L’intercommunalité']
  zone.innerHTML = `<h3>Ce que ${h(ctx.nom)} a payé pour ses équipements</h3>
${idx ? blocInvestissement(idx, dep, ctx) : absent('Investissement réalisé non disponible.')}
<h3>Délibérations publiées</h3>
${
  di
    ? `<p>${h(di.presentation)}</p>${sirens.map((_, i) => blocDeliberations(di, colls[i], noms[i])).join('')}${blocBudgetsPublies(bp, ctx.siren, ctx.nom)}${phraseCouverture(di)}<p class="aide">${h(di.regle)}</p>${source(di.source, di.millesime)}`
    : absent('Délibérations non disponibles.')
}`
  zone.removeAttribute('aria-busy')
}

/** Section ajoutée après les subventions ; données chargées au clic sur le bouton. */
export function section(ctx: Contexte): HTMLElement {
  const s = document.createElement('section')
  s.className = 'section-donnees'
  s.setAttribute('aria-labelledby', 'titre-investissement')
  s.innerHTML = `<h2 id="titre-investissement">${TITRE}</h2>
<p>Ce que la commune a réellement payé pour ses équipements chaque année depuis 2010, à côté du budget voté quand il est publié, et les délibérations qu’elle publie en données ouvertes. Les projets un par un et les budgets annexes ne sont pas détaillés.</p>
<p><button type="button" class="bouton" aria-controls="zone-investissement" aria-expanded="false">Afficher l’investissement et les délibérations</button></p>
<div id="zone-investissement" class="section-donnees"></div>`
  const bouton = s.querySelector('button') as HTMLButtonElement
  const zone = s.querySelector('#zone-investissement') as HTMLElement
  bouton.addEventListener('click', () => {
    bouton.setAttribute('aria-expanded', 'true')
    bouton.disabled = true
    remplir(zone, ctx)
      .then(() => {
        bouton.closest('p')?.remove()
        zone.querySelector('h3')?.setAttribute('tabindex', '-1')
        zone.querySelector<HTMLElement>('h3')?.focus()
      })
      .catch((e) => {
        console.error(e)
        zone.innerHTML = absent()
        zone.removeAttribute('aria-busy')
        bouton.disabled = false
      })
  })
  return s
}

/**
 * Appelé par la page commune. Sans IntersectionObserver (prérendu au build), ne fait rien : le HTML statique des
 * pages communes reste inchangé. Dans le navigateur, la section apparaît quand les subventions approchent de l'écran.
 */
export function brancher(cible: HTMLElement, ctx: Contexte): void {
  if (typeof IntersectionObserver === 'undefined') return
  const ancre = cible.querySelector<HTMLElement>('#sec-subventions')
  if (!ancre || cible.querySelector('#titre-investissement')) return
  const obs = new IntersectionObserver(
    (entrees) => {
      if (!entrees.some((e) => e.isIntersecting)) return
      obs.disconnect()
      if (!cible.querySelector('#titre-investissement')) ancre.insertAdjacentElement('afterend', section(ctx))
    },
    { rootMargin: '400px 0px' },
  )
  obs.observe(ancre)
}

// Crédits de l'État dans les six territoires d'outre-mer que « Budget de ma commune » ne couvre pas (site/data/outremer/) :
// par territoire, par mission, par habitant et dans le temps. Deux sources de périmètres différents (Cour des comptes 2018 à 2020,
// document de politique transversale 2024 à 2026) : montrées côte à côte, jamais raccordées ni additionnées.
import { partPersonnelle } from '../composants/hub'
import { chargerSiPresent, type Noeud } from '../donnees'
import { lien } from '../routeur'
import { absent, badgeStatut, barres, entier, eur, eurLisible, h, source, sur100, surligne } from '../util'
import { enCours } from './dette'

type Valeurs = (number | null)[]

interface Source {
  titre: string
  producteur?: string
  url?: string
  licence?: string
  collecte_le?: string
}

export interface IndexOutremer {
  millesime: string
  collecte_le: string
  territoires: { code: string; nom: string; statut_juridique: string; population: number | null; fichier: string; blocs: Record<string, string> }[]
  blocs: Record<string, string>
  ecarts: { territoire: string; annee: string; montant: number; autre_montant: number; ecart: number; ecart_pct: number; lecture_ecart: string }[]
  limites: string[]
  sources: Record<string, Source>
}

interface Mission {
  mission: string
  valeurs: Valeurs
  programmes: { code: string; libelle: string; valeurs: Valeurs }[]
}

export interface TerritoireOutremer {
  territoire: { code: string; nom: string; population: number | null }
  blocs: Record<string, { statut: string; motif?: string }>
  credits_etat: {
    cour_des_comptes_2018_2020: {
      statut: string
      motif?: string
      annees?: Record<string, { execution_cp_eur: number | null }>
      population_2018?: number | null
      cp_executes_par_habitant_eur?: Record<string, number | null>
    }
    dpt_plf2026: { statut: string; motif?: string; colonnes?: string[]; total_general?: Valeurs; missions?: Mission[] }
  }
}

interface NichesProgrammes {
  millesime: string
  source: string
  programmes: { programme: string; nom: string; mission: string; fiscal_meur: Record<string, number | null>; non_chiffrees: Record<string, number>; mesures: string[] }[]
}

/** Les trois colonnes en crédits de paiement, avec leur nature : elles ne sont pas de même nature et ne s'additionnent pas. */
export const COLONNES_CP = [
  { cle: 'execution_2024_cp', annee: '2024', nature: 'dépensé', libelle: 'Dépensé en 2024' },
  { cle: 'lfi_2025_cp', annee: '2025', nature: 'voté', libelle: 'Voté pour 2025' },
  { cle: 'plf_2026_cp', annee: '2026', nature: 'proposé', libelle: 'Proposé pour 2026' },
] as const

export const REGLE_TERRITOIRES = 'Ordre des territoires : leur code officiel, du plus petit au plus grand.'
export const REGLE_MISSIONS = 'Ordre des missions : montant dépensé en 2024, du plus élevé au plus faible, puis ordre alphabétique.'

/** Valeur d'une colonne du document de politique transversale, ou null si la colonne ou la valeur manque. */
export function valeurColonne(colonnes: string[] | undefined, valeurs: Valeurs | undefined, cle: string): number | null {
  const i = (colonnes ?? []).indexOf(cle)
  if (i < 0 || !valeurs) return null
  const v = valeurs[i]
  return typeof v === 'number' ? v : null
}

/** Montant par habitant calculé par le site ; null sans population publiée ou sans montant. */
export function parHabitant(montant: number | null, population: number | null | undefined): number | null {
  if (montant === null || !population || population <= 0) return null
  return montant / population
}

const montant = (x: number | null) => (x === null ? 'non publié' : eurLisible(x))

/** Missions des territoires choisis, montants additionnés colonne par colonne (même source, même colonne). */
export function missionsCumulees(terrs: TerritoireOutremer[]): { colonnes: string[]; missions: Mission[] } {
  const avecDpt = terrs.filter((t) => t.credits_etat.dpt_plf2026.statut === 'publié' && t.credits_etat.dpt_plf2026.missions)
  const colonnes = avecDpt[0]?.credits_etat.dpt_plf2026.colonnes ?? []
  const parNom = new Map<string, Mission>()
  const ajouter = (a: Valeurs, b: Valeurs): Valeurs => a.map((x, i) => (x === null && b[i] === null ? null : (x ?? 0) + (b[i] ?? 0)))
  for (const t of avecDpt) {
    for (const m of t.credits_etat.dpt_plf2026.missions!) {
      const deja = parNom.get(m.mission)
      if (!deja) {
        parNom.set(m.mission, { mission: m.mission, valeurs: [...m.valeurs], programmes: m.programmes.map((p) => ({ ...p, valeurs: [...p.valeurs] })) })
        continue
      }
      deja.valeurs = ajouter(deja.valeurs, m.valeurs)
      for (const p of m.programmes) {
        const dp = deja.programmes.find((x) => x.code === p.code)
        if (dp) dp.valeurs = ajouter(dp.valeurs, p.valeurs)
        else deja.programmes.push({ ...p, valeurs: [...p.valeurs] })
      }
    }
  }
  return { colonnes, missions: [...parNom.values()] }
}

/** Tri neutre et explicite : montant dépensé en 2024 décroissant, puis nom. */
export function trierMissions(missions: Mission[], colonnes: string[]): Mission[] {
  const v = (m: Mission) => valeurColonne(colonnes, m.valeurs, 'execution_2024_cp') ?? -1
  return [...missions].sort((a, b) => v(b) - v(a) || a.mission.localeCompare(b.mission, 'fr'))
}

const nonNul = (colonnes: string[], v: Valeurs) => COLONNES_CP.some((c) => (valeurColonne(colonnes, v, c.cle) ?? 0) !== 0)

function tableauTerritoires(_idx: IndexOutremer, terrs: TerritoireOutremer[]): string {
  const lignes = terrs
    .map((t) => {
      const d = t.credits_etat.dpt_plf2026
      const pop = t.territoire.population
      const cellules = COLONNES_CP.map((c) => {
        const v = d.statut === 'publié' ? valeurColonne(d.colonnes, d.total_general, c.cle) : null
        return `<td class="nombre">${h(montant(v))}</td>`
      }).join('')
      return `<tr><th scope="row"><a href="${lien('/explorer/outre-mer', { t: t.territoire.code })}">${h(t.territoire.nom)}</a></th><td class="nombre">${pop ? h(entier(pop)) : 'non publiée'}</td>${cellules}</tr>`
    })
    .join('')
  return `<div class="tableau-defile"><table><caption>Crédits de paiement de l’État par territoire, tous ministères, d’après le document de politique transversale « Outre-mer » (projet de loi de finances pour 2026)</caption><thead><tr><th scope="col">Territoire</th><th scope="col" class="nombre">Habitants</th>${COLONNES_CP.map((c) => `<th scope="col" class="nombre">${h(c.libelle)}</th>`).join('')}</tr></thead><tbody>${lignes}</tbody></table></div>
<p class="aide" data-regle-ordre>${h(REGLE_TERRITOIRES)}</p>
<p class="aide">Les trois colonnes ne sont pas de même nature : la première est ce qui a été dépensé, la deuxième ce que le Parlement a voté, la troisième ce que le Gouvernement propose. Elles se lisent côte à côte, sans s’additionner. Le site ne calcule pas de montant par habitant : la population publiée ne porte pas sur la même année que les crédits dépensés.</p>`
}

function tableauCour(terrs: TerritoireOutremer[]): string {
  const annees = ['2018', '2019', '2020']
  const lignes = terrs
    .map((t) => {
      const c = t.credits_etat.cour_des_comptes_2018_2020
      if (c.statut !== 'publié') return `<tr><th scope="row">${h(t.territoire.nom)}</th><td colspan="4">${h(c.motif ?? 'non publié en données ouvertes')}</td></tr>`
      const hab = c.cp_executes_par_habitant_eur?.['2018'] ?? null
      return `<tr><th scope="row">${h(t.territoire.nom)}</th>${annees.map((a) => `<td class="nombre">${h(montant(c.annees?.[a]?.execution_cp_eur ?? null))}</td>`).join('')}<td class="nombre">${hab === null ? 'non publié' : h(eur(hab))}</td></tr>`
    })
    .join('')
  return `<div class="tableau-defile"><table><caption>Crédits de paiement de l’État dépensés par territoire, 2018 à 2020, d’après la Cour des comptes</caption><thead><tr><th scope="col">Territoire</th>${annees.map((a) => `<th scope="col" class="nombre">Dépensé en ${a}</th>`).join('')}<th scope="col" class="nombre">Par habitant en 2018 (calcul de la Cour)</th></tr></thead><tbody>${lignes}</tbody></table></div>`
}

function blocMissions(choix: TerritoireOutremer[], nom: string): string {
  const { colonnes, missions } = missionsCumulees(choix)
  if (!missions.length) return absent(`Crédits par mission : non publiés en données ouvertes pour ${nom}.`)
  const triees = trierMissions(missions, colonnes)
  const avecDepense = triees.filter((m) => (valeurColonne(colonnes, m.valeurs, 'execution_2024_cp') ?? 0) > 0)
  const aZero = triees.length - avecDepense.length
  const lignesMissions = triees
    .filter((m) => nonNul(colonnes, m.valeurs))
    .map((m) => `<tr><th scope="row">${h(m.mission)}</th>${COLONNES_CP.map((c) => `<td class="nombre">${h(montant(valeurColonne(colonnes, m.valeurs, c.cle)))}</td>`).join('')}</tr>`)
    .join('')
  const lignesProgrammes = triees
    .flatMap((m) => m.programmes.filter((p) => nonNul(colonnes, p.valeurs)).map((p) => ({ m: m.mission, p })))
    .map(({ m, p }) => `<tr><th scope="row">${h(p.code)} ${h(p.libelle)}</th><td>${h(m)}</td>${COLONNES_CP.map((c) => `<td class="nombre">${h(montant(valeurColonne(colonnes, p.valeurs, c.cle)))}</td>`).join('')}</tr>`)
    .join('')
  return `${barres(
    avecDepense.map((m) => {
      const v = valeurColonne(colonnes, m.valeurs, 'execution_2024_cp')!
      return { nom: m.mission, valeur: v, texte: eurLisible(v) }
    }),
    undefined,
    `Crédits de paiement dépensés en 2024 par mission, ${nom}`,
  )}
<p class="aide" data-regle-ordre>${h(REGLE_MISSIONS)}</p>
${aZero ? `<p class="aide">${h(entier(aZero))} mission${aZero > 1 ? 's' : ''} du tableau n’${aZero > 1 ? 'ont' : 'a'} aucun crédit dépensé en 2024 pour ${h(nom)} dans le document : ${aZero > 1 ? 'elles ne sont pas listées' : 'elle n’est pas listée'} ci-dessus.</p>` : ''}
<div class="tableau-defile"><table><caption>Crédits de paiement par mission, ${h(nom)}, 2024 à 2026</caption><thead><tr><th scope="col">Mission</th>${COLONNES_CP.map((c) => `<th scope="col" class="nombre">${h(c.libelle)}</th>`).join('')}</tr></thead><tbody>${lignesMissions}</tbody></table></div>
<details><summary>Le détail par programme</summary>
<p class="aide">Les codes à quatre chiffres sont des prélèvements sur les recettes de l’État au profit des collectivités : le document les compte dans la mission « Relations avec les collectivités territoriales ».</p>
<div class="tableau-defile"><table><caption>Crédits de paiement par programme, ${h(nom)}, 2024 à 2026</caption><thead><tr><th scope="col">Programme</th><th scope="col">Mission</th>${COLONNES_CP.map((c) => `<th scope="col" class="nombre">${h(c.libelle)}</th>`).join('')}</tr></thead><tbody>${lignesProgrammes}</tbody></table></div>
</details>`
}

/** Sigles cités par les sources, en toutes lettres. */
const SIGLES = 'Sigles des sources : DGCL, direction générale des collectivités locales ; OFGL, Observatoire des finances et de la gestion publique locales.'

const LIBELLES_BLOCS: Record<string, string> = {
  credits_etat_2018_2020: 'Crédits de l’État 2018 à 2020',
  credits_etat_plf2026: 'Crédits de l’État 2024 à 2026',
  dotations_communes: 'Dotations de l’État aux communes',
  dotations_intercommunalites: 'Dotations de l’État aux intercommunalités',
  dotations_collectivite: 'Dotations de l’État à la collectivité',
  budget_collectivite: 'Budget de la collectivité',
  budget_communes: 'Budget des communes',
  impots_territoriaux: 'Impôts votés par la collectivité',
}

function blocTerritoire(idx: IndexOutremer, t: TerritoireOutremer): string {
  const ecarts = idx.ecarts.filter((e) => e.territoire === t.territoire.code)
  const blocs = Object.keys(LIBELLES_BLOCS)
    .filter((k) => t.blocs[k])
    .map((k) => {
      const b = t.blocs[k]
      const pub = b.statut === 'publié'
      return `<li>${pub ? '' : `${badgeStatut('nonpub')} `}<strong>${h(LIBELLES_BLOCS[k])}</strong> : ${h(pub ? 'publié en données ouvertes' : b.motif ?? b.statut)}</li>`
    })
    .join('')
  return `<h3>Ce qui est publié pour ${h(t.territoire.nom)}</h3>
<ul class="lignes">${blocs}</ul>
<p class="aide">« Non publié » décrit l’état de la publication à la date de collecte, pas l’usage de l’argent : aucune valeur n’est estimée à la place. ${SIGLES}</p>
${
  ecarts.length
    ? `<div class="tableau-defile"><table><caption>Dotation globale de fonctionnement, ${h(t.territoire.nom)} : deux sources comparées</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Document de politique transversale</th><th scope="col" class="nombre">Montants notifiés (Observatoire des finances et de la gestion publique locales)</th><th scope="col" class="nombre">Écart</th></tr></thead><tbody>${ecarts
        .map((e) => `<tr><th scope="row">${h(e.annee)}</th><td class="nombre">${h(eur(e.montant))}</td><td class="nombre">${h(eur(e.autre_montant))}</td><td class="nombre">${h(eur(e.ecart))}</td></tr>`)
        .join('')}</tbody></table></div><p class="aide">${h(ecarts[0].lecture_ecart)}.</p>`
    : ''
}`
}

function blocFiscal(n: NichesProgrammes | null): string {
  const progs = n?.programmes.filter((p) => p.mission === 'Outre-mer') ?? []
  if (!progs.length)
    return `<p>Les dépenses fiscales propres à l’outre-mer sont présentées mesure par mesure dans <a href="#/explorer/niches">Dépenses fiscales et exonérations de cotisations</a>.</p>`
  const annees = ['2024', '2025', '2026']
  const lignes = progs
    .map((p) => `<tr><th scope="row">${h(p.programme)} ${h(p.nom)}</th><td class="nombre">${h(entier(p.mesures.length))}</td>${annees.map((a) => `<td class="nombre">${p.fiscal_meur[a] === null || p.fiscal_meur[a] === undefined ? 'non chiffré' : h(eurLisible(p.fiscal_meur[a]! * 1e6))}</td>`).join('')}<td class="nombre">${h(entier(p.non_chiffrees['2024'] ?? 0))}</td></tr>`)
    .join('')
  return `<p>Une dépense fiscale (souvent appelée niche fiscale) réduit l’impôt dû au lieu d’être versée : réduction d’impôt, taux réduit, abattement. L’administration en estime le montant, mesure par mesure, et rattache chaque mesure à un programme du budget. Ces montants ne sont pas répartis par territoire et ne s’ajoutent pas aux crédits ci-dessus : ce sont des recettes en moins, estimées, pas des dépenses constatées. ${badgeStatut('approche')}</p>
<div class="tableau-defile"><table><caption>Dépenses fiscales rattachées aux programmes de la mission « Outre-mer », tous territoires d’outre-mer</caption><thead><tr><th scope="col">Programme</th><th scope="col" class="nombre">Mesures</th><th scope="col" class="nombre">2024 (constaté)</th><th scope="col" class="nombre">2025 (estimé)</th><th scope="col" class="nombre">2026 (estimé)</th><th scope="col" class="nombre">Mesures non chiffrées en 2024</th></tr></thead><tbody>${lignes}</tbody></table></div>
<p class="aide">Les mesures non chiffrées par l’administration ne sont jamais comptées pour zéro : elles sont exclues des montants.</p>
${source(n!.source, n!.millesime)}
<p><a href="#/explorer/niches">Toutes les dépenses fiscales, mesure par mesure</a></p>`
}

function dateFr(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso
}

function sourcesTexte(idx: IndexOutremer, cles: string[]): string {
  return cles
    .map((k) => idx.sources[k])
    .filter((s): s is Source => !!s)
    .map((s) => `${s.titre}${s.producteur ? `, ${s.producteur}` : ''}${s.licence ? `, ${s.licence}` : ''}${s.collecte_le ? `, collecté le ${dateFr(s.collecte_le)}` : ''}`)
    .join(' ; ')
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const idx = await chargerSiPresent<IndexOutremer>('outremer/index.json')
  if (!idx) {
    cible.innerHTML = enCours('L’État dans les collectivités d’outre-mer', 'Crédits de l’État par territoire, par mission et par habitant.') + partPersonnelle()
    return
  }
  const lus = await Promise.all(idx.territoires.map((t) => chargerSiPresent<TerritoireOutremer>(t.fichier)))
  const terrs = lus.filter((t): t is TerritoireOutremer => !!t).sort((a, b) => a.territoire.code.localeCompare(b.territoire.code))
  const [racine, niches] = await Promise.all([chargerSiPresent<Noeud>('arbre/racine.json'), chargerSiPresent<NichesProgrammes>('niches/programmes.json')])

  const code = params.get('t')
  const choisi = terrs.find((t) => t.territoire.code === code) ?? null
  const choix = choisi ? [choisi] : terrs
  const nomChoix = choisi ? choisi.territoire.nom : 'les six territoires ensemble'

  // Chiffre clé : somme des six territoires, même source et même colonne (dépensé en 2024).
  const dep2024 = terrs.map((t) => (t.credits_etat.dpt_plf2026.statut === 'publié' ? valeurColonne(t.credits_etat.dpt_plf2026.colonnes, t.credits_etat.dpt_plf2026.total_general, 'execution_2024_cp') : null))
  const complet = dep2024.every((v) => v !== null)
  const total2024 = dep2024.reduce<number>((s, v) => s + (v ?? 0), 0)
  const budgetEtat = racine?.md ? racine.md * 1e9 : null
  const noms = terrs.map((t) => t.territoire.nom)
  const listeNoms = noms.length > 1 ? `${noms.slice(0, -1).join(', ')} et ${noms[noms.length - 1]}` : noms.join('')

  const cle =
    complet && budgetEtat
      ? `<div class="carte" data-cle>
  <p class="grand-chiffre">${surligne(eurLisible(total2024))}</p>
  <p class="sous-chiffre">de crédits de paiement de l’État dépensés en 2024 dans les ${h(entier(terrs.length))} territoires, tous ministères confondus, l’équivalent de ${h(sur100((total2024 / budgetEtat) * 100))} sur 100 € dépensés par l’État en 2024.</p>
  ${source(sourcesTexte(idx, ['dpt_plf2026']), 'exécution 2024')}
</div>`
      : `<div class="carte"><p class="sous-chiffre">Crédits de paiement de l’État dépensés en 2024 dans les ${h(entier(terrs.length))} territoires : ${complet ? h(eurLisible(total2024)) : 'non publié pour au moins un territoire, aucun total n’est affiché'}.</p>${source(sourcesTexte(idx, ['dpt_plf2026']), 'exécution 2024')}</div>`

  cible.innerHTML = `
<h1>L’État dans les collectivités d’outre-mer</h1>
<p class="chapeau">Ce que l’État dépense, tous ministères confondus, dans ${h(entier(terrs.length))} territoires (${h(listeNoms)}) : par territoire, par mission, par habitant et d’une année à l’autre. Ces territoires ont leurs propres règles fiscales et budgétaires ; ils ne figurent pas dans <a href="#/local">Budget de ma commune</a>, qui couvre les 101 départements, dont la Guadeloupe, la Martinique, la Guyane, La Réunion et Mayotte.</p>
${cle}
<h2>Par territoire, de 2024 à 2026</h2>
${tableauTerritoires(idx, terrs)}
${source(sourcesTexte(idx, ['dpt_plf2026', 'geo']), idx.millesime)}
<h2 id="missions">Par mission : ${h(nomChoix)}</h2>
<div class="bascule" role="group" aria-label="Territoire">${[
    `<a class="bouton" href="${lien('/explorer/outre-mer')}"${choisi ? '' : ' aria-current="true"'}>Les six ensemble</a>`,
    ...terrs.map((t) => `<a class="bouton" href="${lien('/explorer/outre-mer', { t: t.territoire.code })}"${choisi === t ? ' aria-current="true"' : ''}>${h(t.territoire.nom)}</a>`),
  ].join('')}</div>
<p>Une mission regroupe les crédits d’une politique de l’État (justice, enseignement scolaire, sécurités, outre-mer…). Le document répartit par territoire les crédits de tous les ministères ; une partie des dépenses n’est pas répartie par territoire et n’apparaît pas ici.</p>
${blocMissions(choix, nomChoix)}
${choisi ? blocTerritoire(idx, choisi) : ''}
${source(sourcesTexte(idx, ['dpt_plf2026']), 'exécution 2024, loi de finances 2025, projet de loi de finances 2026')}
<h2>Avant 2021 : les chiffres de la Cour des comptes</h2>
<p>La Cour des comptes a publié les crédits de l’État par territoire pour 2018 à 2020. Son périmètre n’est pas celui du document de politique transversale : les deux séries ne se raccordent pas et ne s’additionnent pas.</p>
${tableauCour(terrs)}
<p class="aide">Le montant par habitant est celui calculé par la Cour (crédits dépensés divisés par la population estimée au 1er janvier 2018) ; elle ne le publie pas pour 2019 et 2020.</p>
${source(sourcesTexte(idx, ['cour_des_comptes']), '2018 à 2020')}
<h2>Dépenses fiscales liées à l’outre-mer</h2>
${blocFiscal(niches)}
<h2>Limites</h2>
<ul>${idx.limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul>
<p class="aide">${SIGLES}</p>
<p class="liens-sortie"><a href="#/local">Budget de ma commune, dont les départements d’outre-mer</a> <a href="#/explorer/etat">Le budget de l’État, sur 100 € dépensés</a> <a href="#/explorer/collectivites">Les collectivités locales</a></p>
${partPersonnelle()}`
}

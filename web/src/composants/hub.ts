// Cartes d'un hub vers ses rayons, rangées en rubriques par thème, et sortie commune « Voir ta part personnelle ».
// Aucune liste n'est écrite à la main : toute route de ROUTES (src/routes.ts) qui a un `parent` apparaît d'elle-même
// dans le hub de ce parent, dans la rubrique de son `theme` (THEMES ci-dessous, dans cet ordre) ; une route sans
// thème connu apparaît quand même, dans « Autres pages ». Dans une rubrique, les cartes sont triées par ordre
// alphabétique du libellé court, jamais par montant : l'ordre ne dit rien de l'importance d'une page.
import { lien, nomCourt, type Route } from '../routeur'
import { ROUTES } from '../routes'
import { h } from '../util'
import { picto } from './pictos'

export interface Theme {
  cle: string
  nom: string
  /** une phrase factuelle sous le titre de la rubrique */
  intro: string
}

/** Thèmes des rubriques, dans l'ordre d'affichage. Valeurs admises pour le champ `theme` d'une route. */
export const THEMES: Theme[] = [
  { cle: 'qui-recoit', nom: 'Qui reçoit l’argent', intro: 'Les ménages, les agents publics, les organismes et les entreprises qui reçoivent de l’argent public.' },
  { cle: 'politiques', nom: 'Grandes politiques publiques', intro: 'Ce que l’argent public finance, politique par politique.' },
  { cle: 'collecte', nom: 'Comment l’argent est collecté', intro: 'Impôts, cotisations, réductions d’impôt, emprunt et recouvrement.' },
  { cle: 'comparer', nom: 'Comparer et suivre dans le temps', intro: 'Séries sur plusieurs années et comparaisons avec d’autres pays.' },
  { cle: 'territoires', nom: 'Près de chez toi', intro: 'Communes, départements, régions et outre-mer.' },
  { cle: 'ton-calcul', nom: 'Ton calcul en détail', intro: 'Ce que tu verses, ligne par ligne, et ce qui changerait avec un autre salaire.' },
  { cle: 'decisions', nom: 'Décider et contrôler', intro: 'Qui vote le budget, ce qui a été fait, qui contrôle.' },
  { cle: 'comprendre', nom: 'Comprendre les chiffres', intro: 'D’où viennent les montants, ce qu’ils veulent dire et ce qu’ils ne disent pas.' },
  { cle: 'cadre', nom: 'À propos du site', intro: 'Éditeur, données personnelles et cadre du site.' },
]
/** Rubrique des routes sans thème (ou d'un thème inconnu) : elles restent accessibles. */
export const AUTRES: Theme = { cle: 'autres', nom: 'Autres pages', intro: 'Pages pas encore rangées dans un thème.' }

export interface Carte {
  chemin: string
  titre: string
  resume: string
  picto?: string
  famille?: string
  /** clé de tri : libellé court */
  tri?: string
}
export interface Rubrique {
  theme: Theme
  cartes: Carte[]
}

const COLLATION = new Intl.Collator('fr', { sensitivity: 'base', ignorePunctuation: true })
const comparer = (a: Carte, b: Carte) => COLLATION.compare(a.tri ?? a.titre, b.tri ?? b.titre) || (a.chemin < b.chemin ? -1 : a.chemin > b.chemin ? 1 : 0)

/** Rayons d'un hub qui reçoivent une carte : ses enfants déclarés, hors pages à paramètre (sansIndex), atteintes par un formulaire. */
export const rayonsVisibles = (parent: string, routes: Route[] = ROUTES) => routes.filter((r) => r.parent === parent && !r.sansIndex)

const versCarte = (r: Route): Carte => ({ chemin: r.chemin, titre: r.titre, resume: r.resume ?? '', picto: r.picto, famille: r.famille, tri: nomCourt(r) })

/** Rubriques d'un hub : thèmes dans l'ordre de THEMES, « Autres pages » en dernier, rubriques vides omises. */
export function grouper(parent: string, o: { exclure?: string[]; extra?: Carte[]; routes?: Route[] } = {}): Rubrique[] {
  const exclure = new Set(o.exclure ?? [])
  const parTheme = new Map<string, Carte[]>()
  const connus = new Set(THEMES.map((t) => t.cle))
  for (const r of rayonsVisibles(parent, o.routes)) {
    if (exclure.has(r.chemin)) continue
    const cle = r.theme && connus.has(r.theme) ? r.theme : AUTRES.cle
    parTheme.set(cle, [...(parTheme.get(cle) ?? []), versCarte(r)])
  }
  if (o.extra?.length) parTheme.set(AUTRES.cle, [...(parTheme.get(AUTRES.cle) ?? []), ...o.extra])
  return [...THEMES, AUTRES].filter((t) => parTheme.has(t.cle)).map((t) => ({ theme: t, cartes: [...parTheme.get(t.cle)!].sort(comparer) }))
}

const ident = (x: string) => x.replace(/^\//, '').replace(/[^a-z0-9]+/gi, '-').replace(/-+$/, '') || 'racine'

function liste(cartes: Carte[]): string {
  return `<ul class="cartes">${cartes
    .map(
      (c) =>
        `<li${c.famille ? ` class="f-${h(c.famille)}"` : ''}><a href="${lien(c.chemin)}"><strong>${c.picto ? picto(c.picto) : ''}<span>${h(c.titre)}</span></strong>${
          c.resume ? `<span>${h(c.resume)}</span>` : ''
        }</a></li>`,
    )
    .join('')}</ul>`
}

/**
 * Rubriques d'un hub, prêtes à insérer. Sans `titre`, chaque rubrique porte un titre de niveau 2 ; avec `titre`,
 * l'ensemble est une section de niveau 2 et chaque rubrique un niveau 3. Une seule rubrique : simple liste de cartes.
 * Rien à montrer : chaîne vide.
 */
export function rubriques(parent: string, o: { exclure?: string[]; extra?: Carte[]; titre?: string; routes?: Route[] } = {}): string {
  const groupes = grouper(parent, o)
  if (!groupes.length) return ''
  const base = `hub-${ident(parent)}`
  const niveau = o.titre ? 'h3' : 'h2'
  const corps =
    groupes.length === 1
      ? liste(groupes[0].cartes)
      : groupes
          .map((g) => {
            const id = `${base}-${g.theme.cle}`
            const n = g.cartes.length
            return `<section class="hub-rubrique" aria-labelledby="${id}"><${niveau} id="${id}">${h(g.theme.nom)} <span class="hub-compte">${n} page${n > 1 ? 's' : ''}</span></${niveau}><p class="aide">${h(g.theme.intro)}</p>${liste(g.cartes)}</section>`
          })
          .join('')
  return o.titre
    ? `<section class="hub-rubriques" aria-labelledby="${base}"><h2 id="${base}">${h(o.titre)}</h2>${corps}</section>`
    : `<div class="hub-rubriques">${corps}</div>`
}

/**
 * Plan d'une rubrique : toutes ses pages en liens courts, rangées par thème (même ordre que les cartes), posé en haut
 * du hub pour voir d'un coup d'œil ce que la rubrique contient. Les cartes détaillées restent plus bas.
 */
export function planRubrique(parent: string, o: { exclure?: string[]; extra?: Carte[]; routes?: Route[] } = {}): string {
  const groupes = grouper(parent, o)
  if (!groupes.length) return ''
  const id = `plan-${ident(parent)}`
  const n = groupes.reduce((s, g) => s + g.cartes.length, 0)
  return `<nav class="plan-rubrique" aria-labelledby="${id}"><h2 id="${id}">Dans cette rubrique <span class="hub-compte">${n} page${n > 1 ? 's' : ''}</span></h2><div class="plan-groupes">${groupes
    .map(
      (g) =>
        `<div class="plan-groupe"><p class="plan-theme">${h(g.theme.nom)}</p><ul>${g.cartes.map((c) => `<li><a href="${lien(c.chemin)}">${h(c.tri ?? c.titre)}</a></li>`).join('')}</ul></div>`,
    )
    .join('')}</div></nav>`
}

/** Compatibilité : cartes d'un hub vers ses rayons, rangées par thème quand il y en a plusieurs. */
export function cartesRayons(parent: string, extra: { chemin: string; titre: string; resume: string }[] = []): string {
  return rubriques(parent, { extra })
}

export const partPersonnelle = () =>
  `<p class="actions"><a class="bouton bouton-principal" href="#/calcul">Voir ta part personnelle</a></p>`

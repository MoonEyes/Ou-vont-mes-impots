// Outils d'affichage : échappement, formats français, barres proportionnelles.
import type { Fourchette } from './calcul/types'

const ECHAP: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
/** Échappe un texte venant des données avant insertion dans du HTML. */
export const h = (x: unknown): string => String(x ?? '').replace(/[&<>"']/g, (c) => ECHAP[c])

const nf0 = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export const entier = (x: number) => nf0.format(x)
export const eur = (x: number) => `${nf0.format(Math.round(x))} €`
export const eur2 = (x: number) => `${nf2.format(x)} €`
export const pct = (x: number, d = 1) => `${(d === 0 ? nf0 : d === 2 ? nf2 : nf1).format(x)} %`
/** Milliards d'euros. */
export const md = (x: number) => (Math.abs(x) >= 10 ? `${nf1.format(x)} Md€` : `${nf2.format(x)} Md€`)
/** Montant en euros, exprimé en unité lisible (Md€, M€, k€). */
export function eurLisible(x: number): string {
  const a = Math.abs(x)
  if (a >= 1e9) return `${nf1.format(x / 1e9)} Md€`
  if (a >= 1e6) return `${nf1.format(x / 1e6)} M€`
  if (a >= 1e4) return `${nf0.format(x / 1e3)} k€`
  return eur(x)
}
/** « X € sur 100 € » avec la précision adaptée aux petites valeurs. */
export function sur100(x: number): string {
  if (x >= 1) return `${nf1.format(x)} €`
  if (x >= 0.01) return `${nf2.format(x)} €`
  const c = x * 100
  return c >= 0.01 ? `${nf2.format(c)} centime${c >= 2 ? 's' : ''}` : 'moins d’un centime'
}

export function fourchette(f: Fourchette, diviseur = 1): string {
  const b = Math.round(f.bas / diviseur)
  const hh = Math.round(f.haut / diviseur)
  if (b === hh) return eur(f.central / diviseur)
  return `entre ${eur(b)} et ${eur(hh)}`
}
export const estFourchette = (f: Fourchette) => Math.round(f.bas) !== Math.round(f.haut)

/**
 * Jauge d'une fourchette : plein jusqu'à la borne basse, pointillé jusqu'à la borne haute, et un repère (trait jaune,
 * comme le surligneur du chiffre clé) à l'estimation de référence. Les deux bornes sont écrites aux deux bouts.
 */
export function jaugeFourchette(f: Fourchette): string {
  const pc = (x: number) => ((x / f.haut) * 100).toFixed(1)
  return `<div class="jauge" aria-hidden="true"><span class="j-plein" data-l="${pc(f.bas)}"></span><span class="j-points" data-l="${pc(f.haut - f.bas)}"></span><span class="j-repere" data-g="${pc(f.central)}"></span></div>
    <p class="jauge-bornes"><span>${h(eur(f.bas))}</span><span>${h(eur(f.haut))}</span></p>`
}

/** Libellés accentués pour les clés de l'arbre (le pipeline les livre sans accent). */
const ACCENTS: Record<string, string> = {
  'Education et recherche': 'Éducation et recherche',
  'Defense et securite': 'Défense et sécurité',
  'Prelevements sur recettes': 'Prélèvements sur recettes (collectivités, Union européenne)',
  'Solidarite, travail et sante': 'Solidarité, travail et santé',
  'Dette et engagements financiers': 'Dette et engagements financiers',
  'Fonctionnement de l\'Etat': 'Fonctionnement de l’État',
  'Ecologie et transports': 'Écologie et transports',
  'Economie et agriculture': 'Économie et agriculture',
  'Culture et medias': 'Culture et médias',
  'International et immigration': 'International et immigration',
  'Logement et territoires': 'Logement et territoires',
  Justice: 'Justice',
  "Budget de l'Etat": 'Budget de l’État',
  Etat: 'État',
  'Collectivites locales': 'Collectivités locales',
  'Securite sociale': 'Sécurité sociale',
  Ensemble: 'Ensemble des administrations publiques',
}
export const libelle = (x: string) => ACCENTS[x] ?? x

/** Statuts de traçabilité, toujours codés par un motif et un mot : plein (tracé), pointillé (approché), hachuré (non publié). */
export type Statut = 'trace' | 'approche' | 'nonpub'
export const STATUTS: Record<Statut, { libelle: string; lecture: string; motif: string; phrase: string }> = {
  trace: { libelle: 'Tracé', lecture: 'destinataire publié', motif: 'Plein', phrase: 'Le montant figure dans un document public.' },
  approche: { libelle: 'Approché', lecture: 'estimé, méthode publiée', motif: 'Pointillé', phrase: 'Une fourchette ou une estimation, dont la méthode est publiée.' },
  nonpub: { libelle: 'Non publié', lecture: 'aucune donnée ouverte', motif: 'Hachuré', phrase: 'Le destinataire n’apparaît dans aucun document public.' },
}
/** Pastille du motif du statut, décorative : le libellé l'accompagne toujours. */
export const traitStatut = (s: Statut) => `<span class="motif motif-${s}" aria-hidden="true"></span>`
/** Motif et mot, côte à côte : « ▪ tracé ». */
export const badgeStatut = (s: Statut) => `<span class="badge">${traitStatut(s)}${STATUTS[s].libelle}</span>`
/**
 * Règle « chiffre calculé par le site » (docs/NEUTRALITE.md, page Méthode) : un ratio, une différence, une somme, une
 * moyenne ou une part calculés par le site ne sont affichés que si tous leurs montants portent sur la même année et le
 * même périmètre, avec ce badge distinct et la méthode écrite à côté. Méthode vide : erreur (rien n'est affiché).
 */
export const LIBELLE_CALCULE = 'Calculé par le site'
export function badgeCalcule(methode: string): string {
  if (!methode || !methode.trim()) throw new Error('chiffre calculé par le site sans méthode écrite')
  return `<span class="badge badge-calcule" data-calcule><span class="motif motif-calcule" aria-hidden="true"></span>${LIBELLE_CALCULE}</span> <span class="methode-calcul">Méthode : ${h(methode.trim())}</span>`
}
/** Ligne de légende du badge « Calculé par le site » (à poser dans une liste .legende-statuts). */
export const LEGENDE_CALCULE = `<li><span class="motif motif-calcule" aria-hidden="true"></span><span><strong>${LIBELLE_CALCULE}</strong> : ratio, différence, somme ou part calculés par le site à partir de chiffres publiés de la même année et du même périmètre, méthode écrite à côté</span></li>`
/** Vrai si deux millésimes (« LFI 2023 », « Exécution 2024 », 2024…) portent sur la même année. */
export const memeAnnee = (a: string | number | null | undefined, b: string | number | null | undefined): boolean => {
  const an = (x: string | number | null | undefined) => (x === null || x === undefined ? null : /(\d{4})/.exec(String(x))?.[1] ?? null)
  return an(a) !== null && an(a) === an(b)
}
export function legendeStatuts(statuts: Statut[] = ['trace', 'approche', 'nonpub']): string {
  return `<ul class="legende-statuts" aria-label="Légende de la traçabilité">${statuts
    .map((s) => `<li>${traitStatut(s)}<span><strong>${STATUTS[s].libelle}</strong> : ${STATUTS[s].lecture}</span></li>`)
    .join('')}</ul>`
}
/** Légende longue « Comment lire les motifs ». */
export function lireLesMotifs(): string {
  return `<div class="carte carte-contour"><h3>Comment lire les motifs</h3><ul class="legende-statuts">${(['trace', 'approche', 'nonpub'] as Statut[])
    .map((s) => `<li>${traitStatut(s)}<span><strong>${STATUTS[s].motif} : ${STATUTS[s].libelle.toLowerCase()}.</strong> ${STATUTS[s].phrase}</span></li>`)
    .join('')}</ul></div>`
}

/** Le chiffre clé de l'écran (un seul surligneur par écran). */
export const surligne = (texte: string) => `<span class="surligne">${h(texte)}</span>`

export interface ElementBarre {
  nom: string
  valeur: number
  texte: string
  lien?: string
  detail?: string
  statut?: Statut
}

/**
 * Liste de barres proportionnelles (largeur appliquée ensuite par appliquerLargeurs, compatible CSP).
 * Toutes les barres portent la couleur de famille de la page et un contour : aucune n'est mise en avant par la couleur.
 */
export function barres(elements: ElementBarre[], max?: number, etiquette?: string, actif = 0): string {
  const m = max ?? Math.max(...elements.map((e) => e.valeur), 0)
  return `<ul class="barres"${etiquette ? ` aria-label="${h(etiquette)}"` : ''}>${elements
    .map((e, i) => {
      const w = m > 0 ? Math.max(0, Math.min(100, (e.valeur / m) * 100)) : 0
      const nom = e.lien ? `<a href="${h(e.lien)}">${h(e.nom)}</a>` : `<span class="nom">${h(e.nom)}</span>`
      const statut = e.statut ? ` statut-${e.statut}` : ''
      return `<li${i === actif ? ' class="actif"' : ''}><div class="barre-tete">${nom}<span class="valeur">${h(e.texte)}${
        e.statut ? ` ${badgeStatut(e.statut)}` : ''
      }</span></div>${e.detail ? `<div class="aide">${h(e.detail)}</div>` : ''}<div class="barre" aria-hidden="true"><span class="barre-remplissage${statut}" data-l="${w.toFixed(2)}"></span></div></li>`
    })
    .join('')}</ul>`
}

/** Applique les largeurs via le CSSOM (les attributs style sont interdits par la CSP). */
export function appliquerLargeurs(racine: ParentNode) {
  racine.querySelectorAll<HTMLElement>('[data-l]').forEach((el) => {
    el.style.width = `${el.dataset.l}%`
  })
  racine.querySelectorAll<HTMLElement>('[data-g]').forEach((el) => {
    el.style.left = `${el.dataset.g}%`
  })
  racine.querySelectorAll<HTMLElement>('[data-f]').forEach((el) => {
    el.style.flexGrow = el.dataset.f ?? '1'
  })
  rendreDefilables(racine)
}

/**
 * Zones de tableau défilantes atteignables au clavier (WCAG 2.1.1, RGAA 7.3) : focus possible,
 * rôle de région nommée d'après la légende du tableau.
 */
export function rendreDefilables(racine: ParentNode) {
  racine.querySelectorAll<HTMLElement>('.tableau-defile:not([tabindex])').forEach((el) => {
    el.tabIndex = 0
    el.setAttribute('role', 'region')
    const legende = el.querySelector('caption')?.textContent?.trim()
    el.setAttribute('aria-label', legende ? `${legende} (tableau défilant)` : 'Tableau défilant')
  })
}

export function source(texte: string, millesime?: string): string {
  return `<p class="source">${h(texte)}${millesime ? ` (${h(millesime)})` : ''}</p>`
}

export function absent(texte = 'Donnée non disponible.'): string {
  return `<p class="absent">${h(texte)}</p>`
}

export function annoncer(texte: string) {
  const z = document.getElementById('annonce')
  if (z) {
    z.textContent = ''
    window.setTimeout(() => (z.textContent = texte), 50)
  }
}

/** « LYON » ou « SAINT-ETIENNE » (fichiers fiscaux en capitales) deviennent « Lyon », « Saint-Etienne ». */
export const nomVille = (nom: string) => (nom === nom.toUpperCase() ? nom.toLowerCase().replace(/(^|[\s'’-])(\p{L})/gu, (_, a, b) => a + b.toUpperCase()) : nom)

export const numeroProgramme = (id: string) => {
  const m = /(?:^|\/)(\d{3})$/.exec(id)
  return m ? m[1] : null
}

/**
 * Vrai pendant le prérendu au build (scripts/prerendre.mjs charge les écrans par ssrLoadModule, comme
 * src/composants/exporter.ts le détecte déjà). Sert à laisser hors du HTML statique les blocs lourds des pages commune
 * et département (budgets de poids, docs/PERF.md) : ils sont rendus dans le navigateur, à l'ouverture de la page.
 */
export const enPrerendu = (): boolean => !!import.meta.env?.SSR

/** Texte du HTML prérendu à la place d'un bloc rendu seulement dans le navigateur. */
export const AFFICHE_DANS_LE_NAVIGATEUR = '<p class="aide">Ces données s’affichent à l’ouverture de la page dans le navigateur (JavaScript activé).</p>'

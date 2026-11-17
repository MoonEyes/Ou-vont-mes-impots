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

export interface ElementBarre {
  nom: string
  valeur: number
  texte: string
  lien?: string
  orange?: boolean
  detail?: string
}

/** Liste de barres proportionnelles (largeur appliquée ensuite par appliquerLargeurs, compatible CSP). */
export function barres(elements: ElementBarre[], max?: number, etiquette?: string): string {
  const m = max ?? Math.max(...elements.map((e) => e.valeur), 0)
  return `<ul class="barres"${etiquette ? ` aria-label="${h(etiquette)}"` : ''}>${elements
    .map((e) => {
      const w = m > 0 ? Math.max(0, Math.min(100, (e.valeur / m) * 100)) : 0
      const nom = e.lien ? `<a href="${h(e.lien)}">${h(e.nom)}</a>` : `<span class="nom">${h(e.nom)}</span>`
      return `<li><div class="barre-tete">${nom}<span class="valeur">${h(e.texte)}</span></div>${
        e.detail ? `<div class="aide">${h(e.detail)}</div>` : ''
      }<div class="barre" aria-hidden="true"><span class="barre-remplissage${e.orange ? ' orange' : ''}" data-l="${w.toFixed(2)}"></span></div></li>`
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

export const numeroProgramme = (id: string) => {
  const m = /(?:^|\/)(\d{3})$/.exec(id)
  return m ? m[1] : null
}

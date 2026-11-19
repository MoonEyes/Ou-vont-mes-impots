// Fourchette du total « ce que tu verses en un an » : où se place l'estimation de référence, et comment la lire.
//
// Le total est une somme calculée par le site (règle 13 de docs/NEUTRALITE.md : même année, même périmètre, méthode
// écrite, badge « calculé par le site »). Ce n'est pas une moyenne de deux bornes : l'estimation de référence suit
// l'hypothèse de référence de l'Insee pour les taxes sur les achats (taxes réparties comme la consommation) ; la
// fourchette ajoute la variante Insee où ces taxes suivent les revenus, et les bornes des impôts locaux. Pour les
// niveaux de vie des déciles 1 à 7, l'hypothèse de référence donne le montant le plus élevé : l'estimation est alors
// la borne haute. Le site l'écrit au lieu de laisser croire à un milieu de fourchette.
import type { Fourchette } from './types'

/** Place de l'estimation de référence dans la fourchette ; « hors » ne doit jamais arriver (tests/fourchette.test.ts). */
export type PositionCentrale = 'unique' | 'bas' | 'haut' | 'dedans' | 'hors'

/** Comparaison à l'euro près, comme l'affichage (montants arrondis). */
export function positionCentrale(t: Fourchette): PositionCentrale {
  const [b, c, hh] = [t.bas, t.central, t.haut].map(Math.round)
  if (!(b <= c && c <= hh)) return 'hors'
  if (b === hh) return 'unique'
  if (c === hh) return 'haut'
  if (c === b) return 'bas'
  return 'dedans'
}

/** Méthode du total, écrite à côté du badge « calculé par le site ». */
export const METHODE_TOTAL =
  'somme des lignes 2025 de ton foyer (cotisations, CSG et CRDS, impôt sur le revenu, taxes sur tes achats, impôts locaux). Estimation de référence : hypothèse de référence de l’Insee pour les taxes sur les achats (réparties selon la consommation) et estimation centrale des impôts locaux ; bornes : variante de l’Insee où ces taxes suivent les revenus, et bornes des impôts locaux.'

/** Phrase qui dit où se trouve l'estimation de référence, sans laisser croire à un milieu de fourchette. */
export function phrasePosition(p: PositionCentrale): string {
  switch (p) {
    case 'haut':
      return 'L’estimation retenue est le haut de la fourchette : pour ton niveau de vie, l’hypothèse de référence de l’Insee sur les taxes de tes achats donne le montant le plus élevé.'
    case 'bas':
      return 'L’estimation retenue est le bas de la fourchette : pour ton niveau de vie, l’hypothèse de référence de l’Insee sur les taxes de tes achats donne le montant le plus bas.'
    case 'dedans':
      return 'L’estimation retenue se place entre les deux bornes (repère sur la jauge).'
    default:
      return ''
  }
}

// Échelle typographique du site, côté SVG : les tailles écrites dans un dessin (billet, fil de l'euro, trame) sont
// prises dans les mêmes crans que les jetons --t-1 à --t5 de styles.css (en pixels, 16 px = 1rem), plancher 14 px.
// tests/typographie.test.ts vérifie que ces valeurs suivent les jetons et qu'aucune autre taille n'est écrite.

/** Crans en pixels : --t-1, --t0, --t1, --t2, --t3, --t4, puis --t5 au téléphone (36) et sur ordinateur (76). */
export const CRANS_PX = [14, 16, 18, 22, 28, 36, 40, 76] as const

/** Plus grand cran qui ne dépasse pas x (la place disponible), 14 px au moins. */
export function cran(x: number): number {
  let c: number = CRANS_PX[0]
  for (const v of CRANS_PX) if (v <= x) c = v
  return c
}

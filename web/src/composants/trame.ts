// Carte de France en trame : un carré par département, placé à peu près où il se trouve. Chaque carré ouvre sa fiche.
// SVG en attributs (CSP stricte). Les positions viennent de la maquette W_ChezMoi ; l'outre-mer est rangé en bas.
//
// Deux formes :
// - trame() : la carte complète, un lien par département (page « Chez moi », une seule page) ;
// - ouCest() : l'encadré des 2 352 pages département et commune. Les 101 carrés y sont dessinés par un fichier SVG
//   partagé (trame-france.svg, mis en cache par le navigateur, référencé par <use href>), seul le département de la
//   page est écrit dans le HTML, avec son lien. Avant : 17 Ko de carte recopiés dans chaque page (docs/PERF.md).
import { fragmentDepartement } from '../chemins'
import { TOUS_DEPARTEMENTS } from '../departements'
import { h } from '../util'
import urlTrameFrance from './trame-france.svg?url'

const GRILLE =
  '62:5,0 59:6,0 50:3,1 76:4,1 80:5,1 02:6,1 08:7,1 29:0,2 22:1,2 14:3,2 27:4,2 95:5,2 60:6,2 51:7,2 55:8,2 57:9,2 67:10,2 56:0,3 35:1,3 53:2,3 61:3,3 78:4,3 92:5,3 93:6,3 77:7,3 10:8,3 54:9,3 88:10,3 68:11,3 44:1,4 49:2,4 72:3,4 28:4,4 91:5,4 75:6,4 94:7,4 52:8,4 70:9,4 90:10,4 85:1,5 79:2,5 37:3,5 41:4,5 45:5,5 89:6,5 21:7,5 39:8,5 25:9,5 17:1,6 86:2,6 36:3,6 18:4,6 58:5,6 71:6,6 01:7,6 74:8,6 16:1,7 87:2,7 23:3,7 03:4,7 42:5,7 69:6,7 38:7,7 73:8,7 33:1,8 24:2,8 19:3,8 63:4,8 43:5,8 07:6,8 26:7,8 05:8,8 40:1,9 47:2,9 46:3,9 15:4,9 48:5,9 30:6,9 84:7,9 04:8,9 06:9,9 64:1,10 32:2,10 82:3,10 12:4,10 34:5,10 13:6,10 83:7,10 2B:10,10 65:1,11 31:2,11 81:3,11 11:4,11 2A:10,11 09:2,12 66:3,12 971:5,13 972:6,13 973:7,13 974:8,13 976:9,13'

const VUE = '0 0 539 644'
/** Identifiant du groupe dessiné dans trame-france.svg (cible de <use href="…#trame-france">). */
export const ID_TRAME_FRANCE = 'trame-france'

interface Case {
  code: string
  nom: string
  px: number
  py: number
}

/** Les carrés de la grille, dans l'ordre de la maquette (les codes sans nom connu sont ignorés). */
function cases(): Case[] {
  const noms = new Map(TOUS_DEPARTEMENTS)
  return GRILLE.split(' ').flatMap((c) => {
    const [code, pos] = c.split(':')
    const [x, y] = pos.split(',').map(Number)
    const nom = noms.get(code)
    if (!nom) return []
    return [{ code, nom, px: 2 + x * 45, py: 2 + y * 45 + (y === 13 ? 12 : 0) }]
  })
}

const carre = (c: Case) => `<rect x="${c.px}" y="${c.py}" width="40" height="40" rx="10"/>`
const numero = (c: Case) => `<text x="${c.px + 20}" y="${c.py + 25.5}"${c.code.length > 2 ? ' font-size="12.5"' : ''}>${c.code}</text>`
const lien = (c: Case, ici?: string) =>
  `<a href="${fragmentDepartement(c.code, c.nom)}" aria-label="${c.code} ${h(c.nom)}"${c.code === ici ? ' class="t-ici" aria-current="true"' : ''}>${carre(c)}${numero(c)}</a>`

/** ici : code du département mis en avant (motif plein et libellé « ton département » dans la légende). */
export function trame(ici?: string): string {
  const liens = cases()
    .map((c) => lien(c, ici))
    .join('')
  return `<div class="trame"><svg viewBox="${VUE}" role="group" aria-label="Carte de France en trame : un carré par département${ici ? `. Le département ${h(ici)} est mis en avant` : ''}" focusable="false">${liens}</svg></div>`
}

/**
 * Contenu du fichier partagé trame-france.svg : les 101 carrés et leurs numéros, sans couleur ni police. Couleurs,
 * contour et police viennent de l'élément <use> de la page (propriétés héritées, donc thème clair ou sombre suivi) ;
 * les numéros prennent la couleur du texte (currentColor). Le fichier versionné est vérifié par tests/performance.test.ts.
 */
export function trameFranceSvg(): string {
  const cs = cases()
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${VUE}"><g id="${ID_TRAME_FRANCE}"><g>${cs.map(carre).join('')}</g><g fill="currentColor" stroke="none">${cs.map(numero).join('')}</g></g></svg>\n`
}

/** Carte allégée : le fond partagé (sans lien) et, par-dessus, le seul département de la page, avec son lien. */
export function trameIci(code: string): string {
  const c = cases().find((x) => x.code === code)
  return `<div class="trame trame-partagee"><svg viewBox="${VUE}" role="group" aria-label="Carte de France en trame : un carré par département. Le département ${h(code)} est mis en avant" focusable="false"><use class="t-fond" href="${urlTrameFrance}#${ID_TRAME_FRANCE}" aria-hidden="true"/>${c ? lien(c, code) : ''}</svg></div>`
}

/** Encadré « Où c'est » : la trame avec le département mis en avant et sa légende (pages département et commune). */
export function ouCest(code: string, nom: string): string {
  return `<section class="carte carte-contour ou-cest seulement-large" aria-labelledby="titre-ou-cest">
  <h2 id="titre-ou-cest">Où c’est</h2>
  ${trameIci(code)}
  <p class="legende-trame"><span class="t-pastille" aria-hidden="true"></span>Ton département : ${h(nom)} (${h(code)})</p>
  <p class="aide">Un carré par département, placé à peu près où il se trouve. <a href="#/local">La carte de tous les départements</a> ouvre chaque fiche.</p>
</section>`
}

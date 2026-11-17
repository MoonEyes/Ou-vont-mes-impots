// Carte de France en trame : un carré par département, placé à peu près où il se trouve. Chaque carré ouvre sa fiche.
// SVG en attributs (CSP stricte). Les positions viennent de la maquette W_ChezMoi ; l'outre-mer est rangé en bas.
import { fragmentDepartement } from '../chemins'
import { TOUS_DEPARTEMENTS } from '../departements'
import { h } from '../util'

const GRILLE =
  '62:5,0 59:6,0 50:3,1 76:4,1 80:5,1 02:6,1 08:7,1 29:0,2 22:1,2 14:3,2 27:4,2 95:5,2 60:6,2 51:7,2 55:8,2 57:9,2 67:10,2 56:0,3 35:1,3 53:2,3 61:3,3 78:4,3 92:5,3 93:6,3 77:7,3 10:8,3 54:9,3 88:10,3 68:11,3 44:1,4 49:2,4 72:3,4 28:4,4 91:5,4 75:6,4 94:7,4 52:8,4 70:9,4 90:10,4 85:1,5 79:2,5 37:3,5 41:4,5 45:5,5 89:6,5 21:7,5 39:8,5 25:9,5 17:1,6 86:2,6 36:3,6 18:4,6 58:5,6 71:6,6 01:7,6 74:8,6 16:1,7 87:2,7 23:3,7 03:4,7 42:5,7 69:6,7 38:7,7 73:8,7 33:1,8 24:2,8 19:3,8 63:4,8 43:5,8 07:6,8 26:7,8 05:8,8 40:1,9 47:2,9 46:3,9 15:4,9 48:5,9 30:6,9 84:7,9 04:8,9 06:9,9 64:1,10 32:2,10 82:3,10 12:4,10 34:5,10 13:6,10 83:7,10 2B:10,10 65:1,11 31:2,11 81:3,11 11:4,11 2A:10,11 09:2,12 66:3,12 971:5,13 972:6,13 973:7,13 974:8,13 976:9,13'

/** ici : code du département mis en avant (motif plein et libellé « ton département » dans la légende). */
export function trame(ici?: string): string {
  const noms = new Map(TOUS_DEPARTEMENTS)
  const cases = GRILLE.split(' ')
    .map((c) => {
      const [code, pos] = c.split(':')
      const [x, y] = pos.split(',').map(Number)
      const nom = noms.get(code)
      if (!nom) return ''
      const px = 2 + x * 45
      const py = 2 + y * 45 + (y === 13 ? 12 : 0)
      return `<a href="${fragmentDepartement(code, nom)}" aria-label="${code} ${h(nom)}"${code === ici ? ' class="t-ici" aria-current="true"' : ''}><rect x="${px}" y="${py}" width="40" height="40" rx="10"/><text x="${px + 20}" y="${py + 25.5}"${code.length > 2 ? ' font-size="12.5"' : ''}>${code}</text></a>`
    })
    .join('')
  return `<div class="trame"><svg viewBox="0 0 539 644" role="group" aria-label="Carte de France en trame : un carré par département${ici ? `. Le département ${h(ici)} est mis en avant` : ''}" focusable="false">${cases}</svg></div>`
}

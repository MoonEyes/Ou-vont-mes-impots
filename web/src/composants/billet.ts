// Le billet découpé : un billet de 100 € coupé en parts proportionnelles et décalées (maquette W_Systeme).
// Tout est en SVG, donc en attributs : rien ne dépend d'un style en ligne (CSP stricte) et la page prérendue
// porte déjà les bonnes proportions. Deux tracés sont produits, l'un pour les écrans larges, l'autre pour le
// téléphone ; la feuille de style n'en montre qu'un. Chaque part est un lien quand elle mène quelque part.
import { h } from '../util'

export type Famille = 'secu' | 'etat' | 'collectivites' | 'ue' | 'dette' | 'niches' | 'operateurs' | 'prestations' | 'papier' | 'nonpub'

export interface Part {
  nom: string
  /** poids de la part (les largeurs sont proportionnelles) */
  valeur: number
  /** texte posé sur la part : « 57 € » */
  texte: string
  famille: Famille
  /** adresse interne « #/… » */
  lien?: string
  /** précision de la légende : « retraites, santé, famille » */
  detail?: string
}

export interface OptionsBillet {
  /** nom lu par les lecteurs d'écran : « Billet de 100 € : … » */
  etiquette: string
  /** talon à gauche : « 100 » et « euros » par défaut */
  talon?: { grand: string; petit: string }
  /** légendes sous les parts (écran large seulement) */
  legendes?: boolean
  /** ce que mesure une part, pour le nom accessible : « sur 100 € » */
  unite?: string
  /** montant que représente le billet entier (100 par défaut) : sert au texte de la part « autres postes » */
  base?: number
}

/** Familles tournantes pour des postes sans couleur attitrée (grands postes de l'État, missions). */
export const FAMILLES_TOURNANTES: Famille[] = ['ue', 'dette', 'niches', 'prestations', 'operateurs', 'collectivites', 'secu']

let compteur = 0

interface Trace {
  l: number
  hauteur: number
  talon: number
  ecart: number
  min: number
  max: number
  decalages: number[]
  rayon: number
  corps: [number, number]
}
const LARGE: Trace = { l: 1200, hauteur: 208, talon: 128, ecart: 6, min: 60, max: 12, decalages: [0, 18, 6, 24, 10, 20], rayon: 20, corps: [22, 100] }
const COMPACT: Trace = { l: 350, hauteur: 118, talon: 56, ecart: 4, min: 30, max: 6, decalages: [0, 10, 3, 13, 6], rayon: 10, corps: [13, 44] }

/** Au-delà du nombre de parts lisibles, les plus petites sont regroupées dans une part « Autres postes ». */
function regrouper(parts: Part[], max: number, base: number): Part[] {
  const utiles = parts.filter((p) => p.valeur > 0)
  if (utiles.length <= max) return utiles
  const tete = utiles.slice(0, max - 1)
  const reste = utiles.slice(max - 1)
  const somme = reste.reduce((s, p) => s + p.valeur, 0)
  const total = utiles.reduce((s, p) => s + p.valeur, 0)
  const nf = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 })
  return [...tete, { nom: `${reste.length} autres postes`, valeur: somme, texte: `${nf.format((somme / total) * base)} €`, famille: 'papier' }]
}

/** Largeurs proportionnelles, avec un minimum lisible pour les petites parts (le surplus est pris aux grandes). */
function largeurs(parts: Part[], dispo: number, min: number): number[] {
  const total = parts.reduce((s, p) => s + p.valeur, 0) || 1
  let l = parts.map((p) => (p.valeur / total) * dispo)
  for (let tour = 0; tour < 4; tour++) {
    const petites = l.map((x) => x < min)
    if (!petites.some(Boolean)) break
    const pris = petites.reduce((s, p) => s + (p ? min : 0), 0)
    const libres = l.reduce((s, x, i) => s + (petites[i] ? 0 : x), 0)
    l = l.map((x, i) => (petites[i] ? min : (x / libres) * (dispo - pris)))
  }
  return l
}

function tracer(parts0: Part[], o: OptionsBillet, t: Trace, classe: string): string {
  const parts = regrouper(parts0, t.max, o.base ?? 100)
  const id = `b${++compteur}`
  const large = t === LARGE
  const dispo = t.l - t.talon - t.ecart * parts.length
  const ls = largeurs(parts, dispo, t.min)
  const haut = t.hauteur
  const bas = haut + Math.max(...t.decalages)
  const talon = o.talon ?? { grand: '100', petit: 'euros' }
  const unite = o.unite ?? 'sur 100 €'
  let x = t.talon + t.ecart
  const formes: string[] = []
  const legendes: string[] = []
  const finRangee = [0, 0]
  parts.forEach((p, i) => {
    const w = ls[i]
    const y = 2 + t.decalages[i % t.decalages.length]
    // Corps du texte : limité par la largeur de la part ; l'unité tombe quand la part est étroite.
    let texte = p.texte
    const corps = (s: string) => Math.max(t.corps[0], Math.min(t.corps[1], (w - 12) / (s.length * 0.6), haut * 0.5))
    if ((w - 12) / (texte.length * 0.6) < t.corps[0] * 1.25) texte = texte.replace(/\s*(€|Md€|M€|%)$/, '')
    const c = corps(texte)
    const cx = x + w / 2
    const cy = y + haut / 2
    const nonpub = p.famille === 'nonpub'
    const fond = `<rect class="b-forme ${nonpub ? '' : `fam-${p.famille}`}"${nonpub ? ` fill="url(#${id}-h)"` : ''} x="${x.toFixed(1)}" y="${y}" width="${w.toFixed(1)}" height="${haut}" rx="${t.rayon}"/>`
    const rond = !nonpub && i === 0 && w > haut * 1.2 ? `<circle class="b-pointille" cx="${cx.toFixed(1)}" cy="${cy}" r="${(haut * 0.43).toFixed(1)}"/>` : ''
    const lt = texte.length * c * 0.6 + c * 0.5
    const etiquette = nonpub
      ? `<rect class="b-etiquette" x="${(cx - Math.min(lt, w - 10) / 2).toFixed(1)}" y="${(cy - c * 0.72).toFixed(1)}" width="${Math.min(lt, w - 10).toFixed(1)}" height="${(c * 1.44).toFixed(1)}" rx="${(c * 0.3).toFixed(1)}"/>`
      : ''
    const mot = `<text class="${p.famille === 'etat' ? 'b-clair' : p.famille === 'papier' ? 'b-sur-papier' : ''}" x="${cx.toFixed(1)}" y="${(cy + c * 0.35).toFixed(1)}" font-size="${c.toFixed(1)}" text-anchor="middle">${h(texte)}</text>`
    const nom = `${p.nom} : ${p.texte}${/sur 100/.test(p.texte) ? '' : ` ${unite}`}`
    const contenu = `${fond}${rond}${etiquette}${mot}`
    formes.push(p.lien ? `<a href="${h(p.lien)}" aria-label="${h(nom)}">${contenu}</a>` : `<g role="img" aria-label="${h(nom)}">${contenu}</g>`)
    if (large && o.legendes) {
      // Légende sous la part : le nom, et la précision s'il reste de la place avant la légende suivante.
      const largeurNom0 = p.nom.length * 11.8
      const dernier = (i === parts.length - 1 && i > 0) || x + 18 + largeurNom0 > t.l - 8
      const largeurNom = p.nom.length * 11.8
      const largeurTout = largeurNom + (p.detail ? (p.detail.length + 1) * 10.4 : 0)
      const limite = dernier ? t.l : x + w + t.ecart + (i === parts.length - 2 ? -40 : 12)
      const avecDetail = !!p.detail && !dernier && x + 18 + largeurTout < limite
      const longueur = avecDetail ? largeurTout : largeurNom
      const ancre = dernier ? Math.min(t.l - 14, x + w - 15) : x + 18
      const debut = dernier ? ancre - longueur : ancre
      const rangee = debut < finRangee[0] + 14 ? 1 : 0
      finRangee[rangee] = Math.max(finRangee[rangee], dernier ? ancre : ancre + longueur)
      const ly = bas + 44 + rangee * 36
      const rx = dernier ? Math.min(t.l - 5, x + w - 6) : x + 6
      legendes.push(
        `<path class="b-repere" d="M${rx.toFixed(1)} ${y + haut + 8}V${ly + 4}"/><text class="b-legende" x="${ancre.toFixed(1)}" y="${ly}" font-size="21"${dernier ? ' text-anchor="end"' : ''}><tspan>${h(p.nom)}</tspan>${avecDetail ? `<tspan> ${h(p.detail)}</tspan>` : ''}</text>`,
      )
    }
    x += w + t.ecart
  })
  const totalH = bas + 6 + (legendes.length ? 34 + (finRangee[1] ? 68 : 34) : 0)
  const ty = 2 + t.decalages[2 % t.decalages.length]
  const tw = t.talon
  const corpsTalon = large ? 50 : 22
  const grand = talon.grand.length > 3 ? corpsTalon * 0.7 : corpsTalon
  const talonSvg = `<g class="b-talon"><rect class="b-forme b-papier" x="2" y="${ty}" width="${tw - 2}" height="${haut}" rx="${t.rayon}"/><circle class="b-pointille" cx="${tw / 2 + 1}" cy="${ty + haut * 0.24}" r="${large ? 22 : 10}"/><text x="${tw / 2 + 1}" y="${ty + haut * 0.24 + (large ? 9 : 4.5)}" font-size="${large ? 26 : 13}" text-anchor="middle">€</text><text x="${tw / 2 + 1}" y="${ty + haut * 0.68}" font-size="${grand}" text-anchor="middle">${h(talon.grand)}</text><text class="b-petit" x="${tw / 2 + 1}" y="${ty + haut * 0.68 + (large ? 32 : 16)}" font-size="${large ? 20 : 11}" text-anchor="middle">${h(talon.petit)}</text></g>`
  const motif = large ? [14, 5] : [7, 2.6]
  return `<svg class="${classe}" viewBox="0 0 ${t.l} ${totalH}" role="group" aria-label="${h(o.etiquette)}" focusable="false"><defs><pattern id="${id}-h" width="${motif[0]}" height="${motif[0]}" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect class="b-hach-fond" width="${motif[0]}" height="${motif[0]}"/><rect class="b-hach-trait" width="${motif[1]}" height="${motif[0]}"/></pattern></defs>${talonSvg}${formes.join('')}${legendes.join('')}</svg>`
}

/** Le billet, en figure. Le contenu textuel équivalent (liste ou tableau) est posé à côté par l'écran. */
export function billet(parts: Part[], o: OptionsBillet): string {
  return `<div class="billet">${tracer(parts, o, LARGE, 'billet-large')}${tracer(parts, o, COMPACT, 'billet-compact')}</div>`
}

/** Version tableau du billet, repliée : la même information sans le dessin. */
export function tableauBillet(parts: Part[], legende: string, colonnes: [string, string] = ['Part', 'Sur 100 €']): string {
  return `<details class="billet-tableau"><summary>Lire ce billet en tableau</summary><div class="tableau-defile"><table><caption>${h(legende)}</caption><thead><tr><th scope="col">${h(colonnes[0])}</th><th scope="col" class="nombre">${h(colonnes[1])}</th></tr></thead><tbody>${parts
    .filter((p) => p.valeur > 0)
    .map((p) => `<tr><th scope="row">${p.lien ? `<a href="${h(p.lien)}">${h(p.nom)}</a>` : h(p.nom)}${p.detail ? `<br /><span class="aide">${h(p.detail)}</span>` : ''}</th><td class="nombre">${h(p.texte)}</td></tr>`)
    .join('')}</tbody></table></div></details>`
}

/** Les quatre destinataires de ce que verse un foyer, dans l'ordre fixe du site. */
export const FAMILLE_ADMIN: Record<string, { famille: Famille; nom: string; detail: string; lien?: string }> = {
  'Securite sociale': { famille: 'secu', nom: 'Sécurité sociale', detail: 'retraites, santé, famille', lien: '#/explorer/secu' },
  Etat: { famille: 'etat', nom: 'État', detail: 'école, défense, justice, dette', lien: '#/explorer/etat' },
  'Collectivites locales': { famille: 'collectivites', nom: 'Collectivités', detail: 'commune, département, région', lien: '#/explorer/collectivites' },
  Plusieurs: { famille: 'nonpub', nom: 'Sans destinataire publié', detail: 'les documents publics ne disent pas qui reçoit', lien: '#/methode/tracabilite' },
}

/** Parts du billet personnel à partir de la répartition « sur 100 € » par administration. */
export function partsAdministrations(s100: Record<string, number>, ordre: readonly string[]): Part[] {
  return ordre
    .filter((a) => (s100[a] ?? 0) > 0 && FAMILLE_ADMIN[a])
    .map((a) => ({ nom: FAMILLE_ADMIN[a].nom, valeur: s100[a], texte: `${s100[a]} €`, famille: FAMILLE_ADMIN[a].famille, lien: FAMILLE_ADMIN[a].lien, detail: FAMILLE_ADMIN[a].detail }))
}

/** Liste des parts : pastille de famille, nom, précision, montant. C'est l'équivalent texte du billet. */
export function listeParts(parts: Part[], etiquette: string): string {
  return `<ul class="parts" aria-label="${h(etiquette)}">${parts
    .filter((p) => p.valeur > 0)
    .map((p) => {
      const corps = `<span class="pastille ${p.famille === 'nonpub' ? 'motif-nonpub' : `fond-${p.famille}`}" aria-hidden="true"></span><span class="p-nom"><strong>${h(p.nom)}</strong>${p.detail ? `<small>${h(p.detail)}</small>` : ''}</span><span class="p-montant">${h(p.texte)}</span>`
      return `<li>${p.lien ? `<a href="${h(p.lien)}">${corps}</a>` : `<span class="part-ligne">${corps}</span>`}</li>`
    })
    .join('')}</ul>`
}

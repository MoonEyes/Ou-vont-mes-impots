// Le fil de l'euro : de ce qui sort de la poche jusqu'à ceux qui reçoivent. L'épaisseur de chaque ruban suit le montant.
// SVG en attributs seulement (CSP stricte) ; un tracé horizontal pour les écrans larges, un tracé vertical pour le téléphone.
import { cran } from '../typo'
import { h, type Statut, STATUTS } from '../util'
import type { Famille } from './billet'

export interface SourceFil {
  nom: string
  /** montant affiché : « 7 638 € » ou « 4 681 à 6 143 € » */
  texte: string
  valeur: number
  statut: Statut
  court?: string
}
export interface DestFil {
  nom: string
  /** « 57 € » */
  texte: string
  valeur: number
  famille: Famille
  /** exemples de bénéficiaires, sans montant */
  pour: string[]
}

let compteur = 0
const n = (x: number) => x.toFixed(1)

/** Empile des éléments proportionnels avec une taille minimale ; renvoie [début, taille] pour chacun. */
function empiler(valeurs: number[], depart: number, longueur: number, ecart: number, min: number): [number, number][] {
  const total = valeurs.reduce((a, b) => a + b, 0) || 1
  const dispo = longueur - ecart * (valeurs.length - 1)
  let t = valeurs.map((v) => (v / total) * dispo)
  for (let i = 0; i < 4; i++) {
    const petits = t.map((x) => x < min)
    if (!petits.some(Boolean)) break
    const pris = petits.filter(Boolean).length * min
    const libres = t.reduce((s, x, k) => s + (petits[k] ? 0 : x), 0)
    t = t.map((x, k) => (petits[k] ? min : (x / libres) * (dispo - pris)))
  }
  let p = depart
  return t.map((x) => {
    const r: [number, number] = [p, x]
    p += x + ecart
    return r
  })
}
/** Segments contigus et strictement proportionnels (le pilier du total). */
function contigus(valeurs: number[], depart: number, longueur: number): [number, number][] {
  const total = valeurs.reduce((a, b) => a + b, 0) || 1
  let p = depart
  return valeurs.map((v) => {
    const r: [number, number] = [p, (v / total) * longueur]
    p += r[1]
    return r
  })
}

const rubanH = (x0: number, a: [number, number], x1: number, b: [number, number]) => {
  const m = (x0 + x1) / 2
  return `M${n(x0)} ${n(a[0])}C${n(m)} ${n(a[0])} ${n(m)} ${n(b[0])} ${n(x1)} ${n(b[0])}V${n(b[0] + b[1])}C${n(m)} ${n(b[0] + b[1])} ${n(m)} ${n(a[0] + a[1])} ${n(x0)} ${n(a[0] + a[1])}Z`
}
const rubanV = (y0: number, a: [number, number], y1: number, b: [number, number]) => {
  const m = (y0 + y1) / 2
  return `M${n(a[0])} ${n(y0)}C${n(a[0])} ${n(m)} ${n(b[0])} ${n(m)} ${n(b[0])} ${n(y1)}H${n(b[0] + b[1])}C${n(b[0] + b[1])} ${n(m)} ${n(a[0] + a[1])} ${n(m)} ${n(a[0] + a[1])} ${n(y0)}Z`
}

function motifs(id: string): string {
  return `<defs><pattern id="${id}-p" width="7" height="7" patternUnits="userSpaceOnUse"><rect class="fe-points-fond" width="7" height="7"/><circle class="fe-points" cx="3.5" cy="3.5" r="1.5"/></pattern><pattern id="${id}-h" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect class="fe-hach-fond" width="9" height="9"/><rect class="fe-hach" width="3.4" height="9"/></pattern></defs>`
}
const remplissage = (id: string, s: Statut) => (s === 'trace' ? 'class="fe-flux fam-prestations"' : `class="fe-flux" fill="url(#${id}-${s === 'approche' ? 'p' : 'h'})"`)
const remplissageFamille = (id: string, f: Famille) => (f === 'nonpub' ? `class="fe-flux" fill="url(#${id}-h)"` : `class="fe-flux fam-${f}"`)
const surFamille = (f: Famille) => (f === 'etat' ? 'fe-sur-etat' : f === 'nonpub' ? '' : 'fe-sur')

function large(sources: SourceFil[], total: string, dest: DestFil[], id: string): string {
  const H = 300
  const y0 = 44
  const s = empiler(sources.map((x) => x.valeur), y0, H, 8, 40)
  const ps = contigus(sources.map((x) => x.valeur), y0 + 14, H - 28)
  const pd = contigus(dest.map((x) => x.valeur), y0 + 14, H - 28)
  const d = empiler(dest.map((x) => x.valeur), y0, H, 8, 36)
  const out: string[] = [motifs(id)]
  out.push(`<text class="fe-titre" x="0" y="24" font-size="18">Ce que tu verses</text><text class="fe-titre" x="431" y="24" font-size="18" text-anchor="middle">En un an</text><text class="fe-titre" x="610" y="24" font-size="18">Qui reçoit</text><text class="fe-titre" x="828" y="24" font-size="18">Pour qui</text>`)
  sources.forEach((x, i) => {
    out.push(`<path ${remplissage(id, x.statut)} d="${rubanH(210, s[i], 410, ps[i])}"/>`)
    const [y, hh] = s[i]
    out.push(`<rect class="fe-boite" x="1.5" y="${n(y)}" width="208" height="${n(hh)}" rx="12"/>`)
    if (hh >= 78) out.push(`<text x="16" y="${n(y + 26)}" font-size="16">${h(x.nom)}</text><text class="fe-titre" x="16" y="${n(y + 52)}" font-size="18">${h(x.texte)}</text><text class="fe-leger" x="16" y="${n(y + 73)}" font-size="14">${h(STATUTS[x.statut].libelle.toLowerCase())}</text>`)
    else if (hh >= 50) out.push(`<text x="16" y="${n(y + 21)}" font-size="14">${h(x.nom)}</text><text class="fe-titre" x="16" y="${n(y + 42)}" font-size="16">${h(x.texte)}</text>`)
    else out.push(`<text x="14" y="${n(y + hh / 2 - 2)}" font-size="14">${h(x.nom)}</text><text class="fe-titre" x="14" y="${n(y + hh / 2 + 13)}" font-size="14">${h(x.texte)}</text>`)
  })
  out.push(`<rect class="fe-boite" x="410" y="${y0 + 12}" width="42" height="${H - 24}" rx="12"/><text class="fe-titre" x="431" y="${y0 + H + 22}" font-size="18" text-anchor="middle">${h(total)}</text>`)
  dest.forEach((x, i) => {
    out.push(`<path ${remplissageFamille(id, x.famille)} d="${rubanH(452, pd[i], 610, d[i])}"/>`)
    const [y, hh] = d[i]
    out.push(`<rect ${remplissageFamille(id, x.famille).replace('fe-flux', 'fe-flux fe-dest')} x="610" y="${n(y)}" width="178" height="${n(hh)}" rx="12" stroke-width="2.5"/>`)
    const sur = surFamille(x.famille)
    if (x.famille === 'nonpub') out.push(`<rect class="fe-boite" x="620" y="${n(y + hh / 2 - 13)}" width="158" height="26" rx="8"/>`)
    if (hh >= 60 && x.famille !== 'nonpub') out.push(`<text class="${sur}" x="626" y="${n(y + hh / 2 - 4)}" font-size="14">${h(x.nom)}</text><text class="fe-titre ${sur}" x="626" y="${n(y + hh / 2 + 19)}" font-size="18">${h(x.texte)}</text>`)
    else out.push(`<text class="${sur}" x="628" y="${n(y + hh / 2 + 5)}" font-size="14">${h(x.nom)}</text><text class="fe-titre ${sur}" x="772" y="${n(y + hh / 2 + 5)}" font-size="14" text-anchor="end">${h(x.texte)}</text>`)
    const pas = Math.min(22, hh / Math.max(1, x.pour.length))
    x.pour.forEach((b, k) => {
      const by = y + hh / 2 + (k - (x.pour.length - 1) / 2) * pas
      out.push(`<path class="fe-lien" d="M790 ${n(y + hh / 2)}Q806 ${n(y + hh / 2)} 820 ${n(by)}"/><text class="fe-leger" x="828" y="${n(by + 5)}" font-size="14">${h(b)}</text>`)
    })
  })
  return `<svg class="fil-large" viewBox="0 0 1000 ${y0 + H + 34}" aria-hidden="true" focusable="false">${out.join('')}</svg>`
}

function compact(sources: SourceFil[], total: string, dest: DestFil[], id: string): string {
  const L = 350
  const s = empiler(sources.map((x) => x.valeur), 1.5, L - 3, 5, 78)
  const ps = contigus(sources.map((x) => x.valeur), 14, L - 28)
  const pd = contigus(dest.map((x) => x.valeur), 14, L - 28)
  const d = empiler(dest.map((x) => x.valeur), 1.5, L - 3, 5, 34)
  const out: string[] = [motifs(id)]
  sources.forEach((x, i) => {
    out.push(`<path ${remplissage(id, x.statut)} d="${rubanV(58, s[i], 118, ps[i])}"/>`)
    const [px, w] = s[i]
    out.push(`<rect class="fe-boite" x="${n(px)}" y="1.5" width="${n(w)}" height="56" rx="10"/><text x="${n(px + w / 2)}" y="23" font-size="14" text-anchor="middle">${h(x.court ?? x.nom)}</text><text class="fe-titre" x="${n(px + w / 2)}" y="43" font-size="14" text-anchor="middle">${h(x.texte)}</text>`)
  })
  out.push(`<rect class="fe-boite" x="12" y="118" width="${L - 24}" height="40" rx="12"/><text class="fe-titre" x="${L / 2}" y="144" font-size="16" text-anchor="middle">${h(total)} en un an</text>`)
  dest.forEach((x, i) => {
    out.push(`<path ${remplissageFamille(id, x.famille)} d="${rubanV(158, pd[i], 218, d[i])}"/>`)
    const [px, w] = d[i]
    out.push(`<rect ${remplissageFamille(id, x.famille)} x="${n(px)}" y="218" width="${n(w)}" height="62" rx="10" stroke-width="2.5"/>`)
    const court = x.texte.replace(/\s*€$/, '')
    const c = cran(Math.min(30, Math.max(14, (w - 10) / (court.length * 0.6))))
    if (x.famille === 'nonpub') out.push(`<rect class="fe-boite" x="${n(px + w / 2 - Math.min(w - 8, 30) / 2)}" y="${n(249 - c * 0.75)}" width="${n(Math.min(w - 8, 30))}" height="${n(c * 1.5)}" rx="6"/>`)
    out.push(`<text class="fe-titre ${surFamille(x.famille)}" x="${n(px + w / 2)}" y="${n(249 + c * 0.36)}" font-size="${c}" text-anchor="middle">${h(court)}</text>`)
  })
  return `<svg class="fil-compact" viewBox="0 0 ${L} 284" aria-hidden="true" focusable="false">${out.join('')}</svg>`
}

/** Le dessin est décoratif (aria-hidden) : la phrase qui le suit dit la même chose en texte. */
export function filEuro(sources: SourceFil[], total: string, dest: DestFil[]): string {
  const src = sources.filter((x) => x.valeur > 0)
  const dst = dest.filter((x) => x.valeur > 0)
  if (!src.length || !dst.length) return ''
  const id = `f${++compteur}`
  const lecture = `${src.map((x) => `${x.nom.toLowerCase()} : ${x.texte}`).join(' ; ')}. Au total ${total} en un an. Sur 100 € : ${dst.map((x) => `${x.texte} ${x.nom}`).join(', ')}.`
  return `<div class="fil-euro">${large(src, total, dst, id)}${compact(src, total, dst, `${id}c`)}<p class="visuellement-cache">${h(lecture)}</p></div>`
}

/** Un maillon de la piste d'un euro : nom, montant affiché, valeur suivie (1 = l'euro de départ) et statut de la source. */
export interface MaillonPiste {
  nom: string
  texte: string
  valeur: number
  statut: Statut
}

/**
 * La piste d'un euro, étape par étape : un ruban vertical qui s'amincit à chaque étape (épaisseur proportionnelle à la part suivie,
 * avec un minimum visible) et garde le motif du statut de chaque étape. Décoratif : la liste des étapes dit la même chose en texte.
 */
export function filPiste(maillons: MaillonPiste[]): string {
  if (!maillons.length) return ''
  const id = `p${++compteur}`
  const L = 120
  const pas = 58
  const haut = 26
  const c = L / 2
  const larg = (v: number) => Math.max(3, Math.min(1, Math.max(0, v)) * L)
  const out: string[] = [motifs(id)]
  maillons.forEach((m, i) => {
    const w = larg(m.valeur)
    const y = i * pas + 1.5
    if (i > 0) {
      const wp = larg(maillons[i - 1].valeur)
      out.push(`<path ${remplissage(id, m.statut)} d="${rubanV(y - pas + haut, [c - wp / 2, wp], y, [c - w / 2, w])}"/>`)
    }
    out.push(`<rect ${remplissage(id, m.statut)} x="${n(c - w / 2)}" y="${n(y)}" width="${n(w)}" height="${haut}" rx="${w > 12 ? 6 : 1.5}"/>`)
    const nom = m.nom.length > 34 ? `${m.nom.slice(0, 33)}…` : m.nom
    out.push(`<text x="${L + 16}" y="${n(y + 11)}" font-size="14">${h(nom)}</text><text class="fe-titre" x="${L + 16}" y="${n(y + 29)}" font-size="14">${h(m.texte)}</text>`)
  })
  const H = (maillons.length - 1) * pas + haut + 3
  return `<div class="fil-euro fil-piste"><svg viewBox="0 0 400 ${H}" aria-hidden="true" focusable="false">${out.join('')}</svg></div>`
}

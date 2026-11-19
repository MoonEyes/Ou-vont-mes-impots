// « Ton billet te suit » (audit design du 19/11, proposition 3) : une fois le calcul fait pendant la visite, un billet
// miniature de 32 px de haut se pose en haut de chaque page Explorer ; la part de la famille de la page est mise en
// évidence (« tu es dans tes 23 € de l'État »). Le calcul reste en mémoire de la page (src/etat.ts) : rien n'est
// stocké sur l'appareil, rien n'est mis dans une adresse. Le dessin est décoratif ; la phrase dit la même chose.
import { ORDRE_ADMIN } from '../calcul/repartition'
import { session } from '../etat'
import { badgeCalcule, h } from '../util'
import { resumer } from './resume-calcul'

/** Méthode des parts sur 100 € (règle 13 : badge « calculé par le site » et méthode écrite à côté). */
export const METHODE_PARTS =
  'part de chaque destinataire dans ce que tu verses en 2025 (calcul sur ton appareil), arrondie à l’euro sur 100 €'

/** Famille de couleur d'une page (routes.ts) vers le destinataire du billet personnel. */
export const ADMIN_DE_FAMILLE: Record<string, string> = { secu: 'Securite sociale', etat: 'Etat', collectivites: 'Collectivites locales' }
const FAMILLE_DE_ADMIN: Record<string, string> = { 'Securite sociale': 'secu', Etat: 'etat', 'Collectivites locales': 'collectivites', Plusieurs: 'nonpub' }
const NOM: Record<string, string> = { 'Securite sociale': 'Sécurité sociale', Etat: 'État', 'Collectivites locales': 'collectivités locales', Plusieurs: 'sans destinataire publié' }
const DE: Record<string, string> = { 'Securite sociale': 'de la Sécurité sociale', Etat: 'de l’État', 'Collectivites locales': 'des collectivités locales' }

/** Pages Explorer : le hub, ses pages et celles qu'il range (Suivre un euro). */
export const estPageExplorer = (r: { chemin: string; parent?: string }) => r.chemin === '/explorer' || r.chemin.startsWith('/explorer/') || r.parent === '/explorer'

let compteur = 0

/** Billet miniature (32 px de haut) et sa phrase ; '' sans calcul pendant la visite. */
export function billetSuiveur(famillePage?: string, avecLien = true): string {
  const r = session.resultat
  if (!r) return ''
  const s100 = resumer(r, session.complet).sur100
  const admins = ORDRE_ADMIN.filter((a) => (s100[a] ?? 0) > 0)
  if (!admins.length) return ''
  const ici = famillePage ? ADMIN_DE_FAMILLE[famillePage] : undefined
  const actif = ici && s100[ici] ? ici : undefined
  const id = `bs${++compteur}`
  const L = 160
  const H = 32
  const ecart = 2
  const dispo = L - ecart * (admins.length - 1) - 3
  let x = 1.5
  const formes = admins
    .map((a) => {
      const w = Math.max(4, (s100[a] / 100) * dispo)
      const fam = FAMILLE_DE_ADMIN[a] ?? 'nonpub'
      const classe = `bs-part${actif && a !== actif ? ' bs-eteint' : ''}${a === actif ? ' bs-ici' : ''}`
      const forme = fam === 'nonpub' ? `<rect class="${classe}" fill="url(#${id}-h)"` : `<rect class="${classe} fam-${fam}"`
      const out = `${forme} x="${x.toFixed(1)}" y="1.5" width="${w.toFixed(1)}" height="${H - 3}" rx="5"/>`
      x += w + ecart
      return out
    })
    .join('')
  const svg = `<svg class="bs-dessin" viewBox="0 0 ${L} ${H}" width="${L}" height="${H}" aria-hidden="true" focusable="false"><defs><pattern id="${id}-h" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect class="bs-hach-fond" width="6" height="6"/><rect class="bs-hach-trait" width="2.2" height="6"/></pattern></defs>${formes}</svg>`
  const phrase = actif
    ? `Tu es dans tes <strong>${s100[actif]} €</strong> ${h(DE[actif])}, sur 100 € que tu verses.`
    : `Ton billet de 100 € : ${admins.map((a) => `<strong>${s100[a]} €</strong> ${h(NOM[a])}`).join(', ')}.`
  return `<aside class="billet-suiveur" aria-label="Ton billet">${svg}<p class="bs-texte">${phrase}${avecLien ? ` <a href="#/calcul/resultat">Mon résultat</a>` : ''}</p><p class="aide bs-methode">${badgeCalcule(METHODE_PARTS)}</p></aside>`
}

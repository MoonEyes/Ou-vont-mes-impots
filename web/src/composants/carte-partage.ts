// « Partager ma carte » : image PNG du récapitulatif (ce que je verse, d'où ça sort, où ça va), dessinée sur
// l'appareil (canvas), partagée par le système (navigator.share avec fichier) ou téléchargée. Rien n'est envoyé
// au site ni mis dans une adresse. Par défaut l'image ne porte aucun montant personnel (ni total ni salaire) :
// seulement des parts sur 100 €. Une case explicite ajoute les montants. Le bouton « Imprimer » ouvre
// l'impression du navigateur (feuille d'impression : bloc « recap-partage » à la fin de styles.css).
import type { Complet } from '../calcul/hors-bulletin'
import { NOM_SUR100, ORDRE_ADMIN, sur100Entiers } from '../calcul/repartition'
import type { ResultatOk } from '../calcul/types'
import { session } from '../etat'
import { eur } from '../util'
import { estPlage, plage, resumer } from './resume-calcul'

/** Adresse publique du site, imprimée en pied d'image. */
export const ADRESSE_SITE = 'mooneyes.github.io/Ou-vont-mes-impots'
export const MENTION = 'Site citoyen non officiel, calcul fait sur mon appareil'

export interface OptionsCarte {
  /** true seulement si la personne coche la case : total versé, fourchette et salaire net sur l'image. */
  montants: boolean
}

export interface ContenuCarte {
  titre: string
  /** null sans l'option montants */
  total: string | null
  fourchette: string | null
  salaire: string | null
  sorties: { nom: string; sur100: number; montant: string | null }[]
  parts: { cle: string; nom: string; v: number }[]
  mention: string
  adresse: string
}

const majuscule = (x: string) => x.charAt(0).toUpperCase() + x.slice(1)

/** Ce que porte l'image, sans dessin : testable et relu par le test de confidentialité. */
export function contenuCarte(r: ResultatOk, c: Complet | null, o: OptionsCarte = { montants: false }): ContenuCarte {
  const res = resumer(r, c)
  const proprietaire = session.profil?.logement?.statut === 'proprietaire'
  const brutes = [
    { cle: 'salaire', nom: 'Sur mon salaire', f: res.sources.salaire },
    ...(res.sources.achats ? [{ cle: 'achats', nom: 'Sur mes achats', f: res.sources.achats }] : []),
    ...(res.sources.ordures ? [{ cle: 'ordures', nom: proprietaire ? 'Sur mon logement' : 'Sur mes ordures', f: res.sources.ordures }] : []),
  ]
  const s100 = sur100Entiers(Object.fromEntries(brutes.map((b) => [b.cle, Math.max(0, b.f.central)])))
  const net = r.entree.personnes.reduce((s, p) => s + p.salaire_net_avant_impot_annuel, 0)
  return {
    titre: o.montants ? 'Ce que je verse en un an' : 'Où va ce que je verse',
    total: o.montants ? `${estPlage(res.total) ? 'environ ' : ''}${eur(res.total.central)}` : null,
    fourchette: o.montants && estPlage(res.total) ? `Fourchette : ${eur(res.total.bas)} à ${eur(res.total.haut)}` : null,
    salaire: o.montants ? `pour ${eur(net)} net avant impôt par an` : null,
    sorties: brutes.map((b) => ({ nom: b.nom, sur100: s100[b.cle] ?? 0, montant: o.montants ? plage(b.f) : null })),
    parts: ORDRE_ADMIN.filter((a) => (res.sur100[a] ?? 0) > 0).map((a) => ({ cle: a as string, nom: majuscule(NOM_SUR100[a]), v: res.sur100[a] })),
    mention: MENTION,
    adresse: ADRESSE_SITE,
  }
}

// La carte garde toujours le thème clair de la direction « billet découpé », lisible partout.
const K = {
  fond: '#f3f0ff',
  papier: '#ffffff',
  encre: '#1e1548',
  secondaire: '#4b4470',
  filet: '#dcd6f2',
  familles: { 'Securite sociale': '#ffc93c', Etat: '#4f2fcc', 'Collectivites locales': '#19c3b1', Plusieurs: '' } as Record<string, string>,
}

function arrondi(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, hh: number, r: number) {
  const rr = Math.min(r, w / 2, hh / 2)
  ctx.beginPath()
  ctx.moveTo(x + rr, y)
  ctx.arcTo(x + w, y, x + w, y + hh, rr)
  ctx.arcTo(x + w, y + hh, x, y + hh, rr)
  ctx.arcTo(x, y + hh, x, y, rr)
  ctx.arcTo(x, y, x + w, y, rr)
  ctx.closePath()
}

/** Motif hachuré (non publié) : trame encre sur blanc. */
function hachures(ctx: CanvasRenderingContext2D): CanvasPattern | string {
  const m = document.createElement('canvas')
  m.width = 24
  m.height = 24
  const c = m.getContext('2d')
  if (!c) return K.papier
  c.fillStyle = K.papier
  c.fillRect(0, 0, 24, 24)
  c.strokeStyle = K.encre
  c.lineWidth = 7
  for (const d of [-24, 0, 24]) {
    c.beginPath()
    c.moveTo(d, 24)
    c.lineTo(d + 24, 0)
    c.stroke()
  }
  return ctx.createPattern(m, 'repeat') ?? K.papier
}

/** Carte principale à contour et ombre pleine (motif « billet découpé »). */
function carte(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, hh: number) {
  ctx.fillStyle = K.encre
  arrondi(ctx, x, y + 12, w, hh, 44)
  ctx.fill()
  ctx.fillStyle = K.papier
  arrondi(ctx, x, y, w, hh, 44)
  ctx.fill()
  ctx.lineWidth = 6
  ctx.strokeStyle = K.encre
  ctx.stroke()
}

export async function dessinerCarte(r: ResultatOk, c: Complet | null, o: OptionsCarte = { montants: false }): Promise<Blob> {
  const k = contenuCarte(r, c, o)
  const W = 1080
  const M = 70
  // Hauteurs calculées d'avance : la carte du haut grandit avec l'option montants.
  const hSortie = 64
  const hCarte = 110 + k.sorties.length * hSortie + (k.total ? 226 + (k.fourchette ? 46 : 0) : 0)
  const yCarte = 210
  const yBillet = yCarte + hCarte + 12 + 110
  const hBillet = 230
  const lignesLegende = Math.ceil(k.parts.length / 2)
  const yLegende = yBillet + 30 + hBillet + 100
  const hPied = 150
  const H = yLegende + (lignesLegende - 1) * 62 + 70 + hPied

  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('canvas indisponible')
  try {
    await Promise.all([document.fonts.load('800 64px "Bricolage Grotesque"'), document.fonts.load('400 32px Figtree'), document.fonts.load('700 32px Figtree')])
  } catch {
    /* polices système en repli */
  }
  const titre = '"Bricolage Grotesque", "Arial Black", sans-serif'
  const texte = 'Figtree, system-ui, sans-serif'
  ctx.fillStyle = K.fond
  ctx.fillRect(0, 0, W, H)
  ctx.textAlign = 'left'

  // Titre.
  ctx.fillStyle = K.encre
  ctx.font = `800 72px ${titre}`
  ctx.fillText(k.titre, M, 140, W - 2 * M)

  // Carte du haut : total (option), puis d'où ça sort, sur 100 €.
  carte(ctx, M, yCarte, W - 2 * M, hCarte)
  let y = yCarte + 70
  const gauche = M + 46
  const droite = W - M - 46
  if (k.total) {
    ctx.fillStyle = K.encre
    ctx.font = `800 120px ${titre}`
    ctx.fillText(k.total, gauche - 4, y + 90, droite - gauche)
    y += 140
    if (k.fourchette) {
      ctx.font = `600 30px ${texte}`
      ctx.fillStyle = K.secondaire
      ctx.fillText(k.fourchette, gauche, y, droite - gauche)
      y += 46
    }
    ctx.font = `600 30px ${texte}`
    ctx.fillStyle = K.secondaire
    ctx.fillText(k.salaire ?? '', gauche, y, droite - gauche)
    y += 50
    ctx.fillStyle = K.filet
    ctx.fillRect(gauche, y - 14, droite - gauche, 3)
    y += 36
  }
  ctx.fillStyle = K.encre
  ctx.font = `700 34px ${texte}`
  ctx.fillText('D’où ça sort, sur 100 € versés', gauche, y)
  y += 64
  for (const s of k.sorties) {
    ctx.fillStyle = K.encre
    ctx.font = `800 40px ${titre}`
    ctx.fillText(`${s.sur100} €`, gauche, y)
    ctx.font = `600 32px ${texte}`
    ctx.fillText(s.nom, gauche + 130, y - 2, s.montant ? 420 : droite - gauche - 130)
    if (s.montant) {
      ctx.textAlign = 'right'
      ctx.fillStyle = K.secondaire
      ctx.fillText(`${s.montant} par an`, droite, y - 2, 360)
      ctx.textAlign = 'left'
    }
    y += hSortie
  }

  // Le billet de 100 € découpé : talon puis une part par destinataire, décalées.
  ctx.fillStyle = K.encre
  ctx.font = `800 52px ${titre}`
  ctx.fillText('Mon billet de 100 €, par destinataire', M, yBillet - 30, W - 2 * M)
  const y0 = yBillet
  const ecart = 8
  const talon = 130
  const dispo = W - 2 * M - talon - ecart * k.parts.length
  const min = 76
  let larg = k.parts.map((p) => (p.v / 100) * dispo)
  const petites = larg.map((x) => x < min)
  const pris = petites.filter(Boolean).length * min
  const libres = larg.reduce((s, x, i) => s + (petites[i] ? 0 : x), 0)
  larg = larg.map((x, i) => (petites[i] ? min : (x / libres) * (dispo - pris)))
  const motif = hachures(ctx)
  ctx.lineWidth = 6
  ctx.strokeStyle = K.encre
  arrondi(ctx, M, y0 + 8, talon, hBillet, 28)
  ctx.fillStyle = K.papier
  ctx.fill()
  ctx.stroke()
  ctx.fillStyle = K.encre
  ctx.textAlign = 'center'
  ctx.font = `800 56px ${titre}`
  ctx.fillText('100', M + talon / 2, y0 + 150)
  ctx.font = `600 26px ${texte}`
  ctx.fillText('euros', M + talon / 2, y0 + 190)
  let x = M + talon + ecart
  const decalages = [0, 22, 6, 28]
  k.parts.forEach((p, i) => {
    const w = larg[i]
    const yp = y0 + decalages[i % decalages.length]
    arrondi(ctx, x, yp, w, hBillet, 28)
    ctx.fillStyle = K.familles[p.cle] || motif
    ctx.fill()
    ctx.stroke()
    const corps = Math.max(34, Math.min(110, (w - 16) / (String(p.v).length * 0.62)))
    ctx.font = `800 ${corps}px ${titre}`
    if (p.cle === 'Plusieurs') {
      const lt = Math.min(w - 12, String(p.v).length * corps * 0.62 + 24)
      arrondi(ctx, x + w / 2 - lt / 2, yp + hBillet / 2 - corps * 0.7, lt, corps * 1.4, 12)
      ctx.fillStyle = K.papier
      ctx.fill()
      ctx.stroke()
    }
    ctx.fillStyle = p.cle === 'Etat' ? K.papier : K.encre
    ctx.fillText(String(p.v), x + w / 2, yp + hBillet / 2 + corps * 0.35)
    x += w + ecart
  })
  ctx.textAlign = 'left'

  // Légende : une pastille à contour et un libellé par part (la couleur ne porte jamais seule le sens).
  y = yLegende
  k.parts.forEach((p, i) => {
    const col = M + (i % 2) * 480
    if (i > 0 && i % 2 === 0) y += 62
    arrondi(ctx, col, y - 34, 40, 40, 10)
    ctx.fillStyle = K.familles[p.cle] || motif
    ctx.fill()
    ctx.lineWidth = 5
    ctx.stroke()
    ctx.fillStyle = K.encre
    ctx.font = `800 36px ${titre}`
    ctx.fillText(`${p.v} €`, col + 58, y)
    ctx.font = `600 30px ${texte}`
    ctx.fillText(p.nom, col + 150, y - 2, 320)
  })

  // Pied : nom, mention non officielle et adresse du site.
  ctx.fillStyle = K.encre
  ctx.fillRect(0, H - hPied, W, hPied)
  ctx.fillStyle = K.papier
  ctx.font = `800 40px ${titre}`
  ctx.fillText('Où vont mes impôts', M, H - hPied + 62)
  ctx.font = `400 26px ${texte}`
  ctx.fillText(k.mention, M, H - hPied + 108, W - 2 * M)
  ctx.font = `700 26px ${texte}`
  ctx.textAlign = 'right'
  ctx.fillText(k.adresse, W - M, H - hPied + 62, 520)
  ctx.textAlign = 'left'

  return new Promise((ok, ko) => canvas.toBlob((b) => (b ? ok(b) : ko(new Error('image vide'))), 'image/png'))
}

/** Option lue sur la page : la case « montants » n'est cochée que par la personne. */
function optionsPage(): OptionsCarte {
  const caseMontants = document.getElementById('partage-montants') as HTMLInputElement | null
  return { montants: !!caseMontants?.checked }
}

export async function partagerCarte(r: ResultatOk, c: Complet | null, o: OptionsCarte = optionsPage()): Promise<string> {
  const blob = await dessinerCarte(r, c, o)
  const fichier = new File([blob], 'ou-vont-mes-impots.png', { type: 'image/png' })
  const nav = navigator as Navigator & { canShare?: (d: { files: File[] }) => boolean }
  if (nav.share && nav.canShare?.({ files: [fichier] })) {
    try {
      await nav.share({ files: [fichier], title: 'Où va ce que je verse' })
      return 'Carte partagée.'
    } catch {
      return 'Partage annulé.'
    }
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fichier.name
  document.body.append(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
  return 'Image téléchargée sur ton appareil.'
}

/** Ajoute au résultat la case « montants » et le bouton « Imprimer », à côté de « Partager ma carte ». */
export function monterPartage(cible: ParentNode) {
  const bouton = cible.querySelector('#partager-carte')
  const actions = bouton?.parentElement
  if (!bouton || !actions || cible.querySelector('#partage-montants')) return
  const imprimer = document.createElement('button')
  imprimer.type = 'button'
  imprimer.id = 'imprimer-recap'
  imprimer.textContent = 'Imprimer'
  imprimer.addEventListener('click', () => window.print())
  actions.append(imprimer)
  const options = document.createElement('div')
  options.className = 'partage-options'
  options.innerHTML = `<label class="case"><input type="checkbox" id="partage-montants" aria-describedby="partage-montants-aide" /> Ajouter mes montants à l’image</label>
<p class="aide" id="partage-montants-aide">Sans cette case, l’image montre seulement les parts sur 100 € : ni ce que tu verses en euros, ni ton salaire. Avec, elle montre ton total, sa fourchette et ton salaire net.</p>`
  actions.after(options)
}

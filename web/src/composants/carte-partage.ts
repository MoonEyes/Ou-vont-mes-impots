// « Partager ma carte » : image PNG dessinée sur l'appareil (canvas), partagée par le système
// (navigator.share avec fichier) ou téléchargée. Aucun montant dans une URL, rien envoyé au site.
import type { Complet } from '../calcul/hors-bulletin'
import { NOM_SUR100, ORDRE_ADMIN, parAdministration, sur100Entiers } from '../calcul/repartition'
import type { ResultatOk } from '../calcul/types'
import { eur } from '../util'

// La carte garde toujours le thème clair de la direction « billet découpé », lisible partout.
const K = {
  fond: '#f3f0ff',
  papier: '#ffffff',
  encre: '#1e1548',
  secondaire: '#4b4470',
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

export async function dessinerCarte(r: ResultatOk, c: Complet | null): Promise<Blob> {
  const W = 1080
  const H = 1080
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

  // Carte principale : le total, contour et ombre pleine.
  const total = c ? c.total : r.totaux.paye_par_le_foyer
  ctx.fillStyle = K.encre
  arrondi(ctx, 70, 82, W - 140, 300, 44)
  ctx.fill()
  ctx.fillStyle = K.papier
  arrondi(ctx, 70, 70, W - 140, 300, 44)
  ctx.fill()
  ctx.lineWidth = 6
  ctx.strokeStyle = K.encre
  ctx.stroke()
  ctx.fillStyle = K.encre
  ctx.font = `600 36px ${texte}`
  ctx.fillText('Ce que je verse en un an', 116, 140)
  ctx.font = `800 132px ${titre}`
  ctx.fillText(eur(total.central), 110, 270)
  if (Math.round(total.bas) !== Math.round(total.haut)) {
    ctx.font = `600 30px ${texte}`
    ctx.fillStyle = K.secondaire
    ctx.fillText(`Fourchette : ${eur(total.bas)} à ${eur(total.haut)}`, 116, 330)
  }

  // Le billet de 100 € découpé : talon puis une part par destinataire, décalées.
  const admin = parAdministration(c?.lignes ?? r.prelevements.filter((l) => l.inclus_dans_total_paye))
  const s100 = sur100Entiers(admin)
  const parts = ORDRE_ADMIN.filter((a) => (s100[a] ?? 0) > 0).map((a) => ({ cle: a as string, nom: NOM_SUR100[a], v: s100[a] }))
  ctx.fillStyle = K.encre
  ctx.font = `800 52px ${titre}`
  ctx.fillText('Mon billet de 100 €', 70, 470)
  const y0 = 510
  const haut = 230
  const ecart = 8
  const talon = 130
  const dispo = W - 140 - talon - ecart * parts.length
  const min = 76
  let larg = parts.map((p) => (p.v / 100) * dispo)
  const petites = larg.map((x) => x < min)
  const pris = petites.filter(Boolean).length * min
  const libres = larg.reduce((s, x, i) => s + (petites[i] ? 0 : x), 0)
  larg = larg.map((x, i) => (petites[i] ? min : (x / libres) * (dispo - pris)))
  const motif = hachures(ctx)
  ctx.lineWidth = 6
  ctx.strokeStyle = K.encre
  arrondi(ctx, 70, y0 + 8, talon, haut, 28)
  ctx.fillStyle = K.papier
  ctx.fill()
  ctx.stroke()
  ctx.fillStyle = K.encre
  ctx.textAlign = 'center'
  ctx.font = `800 56px ${titre}`
  ctx.fillText('100', 70 + talon / 2, y0 + 150)
  ctx.font = `600 26px ${texte}`
  ctx.fillText('euros', 70 + talon / 2, y0 + 190)
  let x = 70 + talon + ecart
  const decalages = [0, 22, 6, 28]
  parts.forEach((p, i) => {
    const w = larg[i]
    const y = y0 + decalages[i % decalages.length]
    arrondi(ctx, x, y, w, haut, 28)
    ctx.fillStyle = K.familles[p.cle] || motif
    ctx.fill()
    ctx.stroke()
    const corps = Math.max(34, Math.min(110, (w - 16) / (String(p.v).length * 0.62)))
    ctx.font = `800 ${corps}px ${titre}`
    if (p.cle === 'Plusieurs') {
      const lt = Math.min(w - 12, String(p.v).length * corps * 0.62 + 24)
      arrondi(ctx, x + w / 2 - lt / 2, y + haut / 2 - corps * 0.7, lt, corps * 1.4, 12)
      ctx.fillStyle = K.papier
      ctx.fill()
      ctx.stroke()
    }
    ctx.fillStyle = p.cle === 'Etat' ? K.papier : K.encre
    ctx.fillText(String(p.v), x + w / 2, y + haut / 2 + corps * 0.35)
    x += w + ecart
  })
  ctx.textAlign = 'left'

  // Légende : une pastille à contour et un libellé par part.
  let y = 850
  parts.forEach((p, i) => {
    const col = 70 + (i % 2) * 480
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
    ctx.fillText(p.nom, col + 150, y - 2)
  })

  ctx.fillStyle = K.encre
  ctx.fillRect(0, H - 110, W, 110)
  ctx.fillStyle = K.papier
  ctx.font = `800 38px ${titre}`
  ctx.fillText('Où vont mes impôts', 70, H - 46)
  ctx.font = `400 24px ${texte}`
  ctx.textAlign = 'right'
  ctx.fillText('Site citoyen non officiel, calcul fait sur mon appareil', W - 70, H - 48)
  ctx.textAlign = 'left'

  return new Promise((ok, ko) => canvas.toBlob((b) => (b ? ok(b) : ko(new Error('image vide'))), 'image/png'))
}

export async function partagerCarte(r: ResultatOk, c: Complet | null): Promise<string> {
  const blob = await dessinerCarte(r, c)
  const fichier = new File([blob], 'ou-vont-mes-impots.png', { type: 'image/png' })
  const nav = navigator as Navigator & { canShare?: (d: { files: File[] }) => boolean }
  if (nav.share && nav.canShare?.({ files: [fichier] })) {
    try {
      await nav.share({ files: [fichier], title: 'Ce que je verse en un an' })
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

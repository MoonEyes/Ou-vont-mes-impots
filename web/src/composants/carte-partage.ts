// « Partager ma carte » : image PNG dessinée sur l'appareil (canvas), partagée par le système
// (navigator.share avec fichier) ou téléchargée. Aucun montant dans une URL, rien envoyé au site.
import type { Complet } from '../calcul/hors-bulletin'
import { NOM_SUR100, ORDRE_ADMIN, parAdministration, sur100Entiers } from '../calcul/repartition'
import type { ResultatOk } from '../calcul/types'
import { eur } from '../util'

function couleurs() {
  const st = getComputedStyle(document.documentElement)
  const v = (n: string, defaut: string) => st.getPropertyValue(n).trim() || defaut
  // La carte garde toujours le thème clair, lisible partout.
  return {
    fond: '#ffffff',
    surface: '#f4f6f2',
    texte: '#1d2320',
    secondaire: '#4f5a54',
    accent: '#0b5a43',
    surligneur: '#e6f24a',
    cats: [1, 2, 3, 4].map((i) => v(`--cat-${i}`, '#0b5a43')),
  }
}

export async function dessinerCarte(r: ResultatOk, c: Complet | null): Promise<Blob> {
  const W = 1080
  const H = 1080
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('canvas indisponible')
  const k = couleurs()
  try {
    await Promise.all([document.fonts.load('700 64px Fraunces'), document.fonts.load('400 32px "Atkinson Hyperlegible Next"')])
  } catch {
    /* polices système en repli */
  }
  const titre = 'Fraunces, Georgia, serif'
  const texte = '"Atkinson Hyperlegible Next", system-ui, sans-serif'
  ctx.fillStyle = k.fond
  ctx.fillRect(0, 0, W, H)
  ctx.fillStyle = k.accent
  ctx.fillRect(0, 0, W, 16)

  const total = c ? c.total : r.totaux.paye_par_le_foyer
  ctx.fillStyle = k.secondaire
  ctx.font = `400 36px ${texte}`
  ctx.fillText('Ce que je verse en un an', 80, 150)
  const montant = eur(total.central)
  ctx.font = `700 120px ${titre}`
  const largeur = ctx.measureText(montant).width
  ctx.fillStyle = k.surligneur
  ctx.fillRect(72, 230, largeur + 16, 54)
  ctx.fillStyle = k.texte
  ctx.fillText(montant, 80, 270)
  if (Math.round(total.bas) !== Math.round(total.haut)) {
    ctx.font = `400 30px ${texte}`
    ctx.fillStyle = k.secondaire
    ctx.fillText(`Fourchette : ${eur(total.bas)} à ${eur(total.haut)}`, 80, 330)
  }

  // Sur 100 € : barre empilée et légende.
  const admin = parAdministration(c?.lignes ?? r.prelevements.filter((l) => l.inclus_dans_total_paye))
  const s100 = sur100Entiers(admin)
  const parts = ORDRE_ADMIN.filter((a) => (s100[a] ?? 0) > 0).map((a, i) => ({ nom: NOM_SUR100[a], v: s100[a], coul: a === 'Plusieurs' ? '#8c8577' : k.cats[i] }))
  ctx.font = `700 44px ${titre}`
  ctx.fillStyle = k.texte
  ctx.fillText('Sur 100 € :', 80, 450)
  let x = 80
  const barre = W - 160
  for (const p of parts) {
    const w = (p.v / 100) * barre
    ctx.fillStyle = p.coul
    ctx.fillRect(x, 490, Math.max(0, w - 4), 40)
    x += w
  }
  let y = 600
  for (const p of parts) {
    ctx.fillStyle = p.coul
    ctx.fillRect(80, y - 30, 32, 32)
    ctx.fillStyle = k.texte
    ctx.font = `700 40px ${texte}`
    ctx.fillText(`${p.v} €`, 132, y)
    ctx.font = `400 40px ${texte}`
    ctx.fillText(p.nom, 260, y)
    y += 70
  }
  ctx.fillStyle = k.surface
  ctx.fillRect(0, H - 170, W, 170)
  ctx.fillStyle = k.texte
  ctx.font = `700 40px ${titre}`
  ctx.fillText('Où vont mes impôts', 80, H - 100)
  ctx.font = `400 26px ${texte}`
  ctx.fillStyle = k.secondaire
  ctx.fillText('Site citoyen non officiel · calcul fait sur mon téléphone · données publiques', 80, H - 55)

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

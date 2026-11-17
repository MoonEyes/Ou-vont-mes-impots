// Chiffres sur le site lui-même, toujours lus dans les données (jamais codés en dur).
import { chargerSiPresent } from '../donnees'

/** « 120 » pour 129 sources collectées (arrondi à la dizaine inférieure), ou null. */
export async function plusDeSources(): Promise<number | null> {
  const s = await chargerSiPresent<{ sources_collectees?: number }>('_sources.json')
  const n = s?.sources_collectees
  if (typeof n !== 'number' || n < 10) return null
  return Math.floor(n / 10) * 10
}

/** Euros sans destinataire publié sur 100 € dépensés par l'État (100 moins le taux tracé, arrondi). */
export async function eurosNonPublies(): Promise<{ euros: number; millesime: string } | null> {
  const r = await chargerSiPresent<{ millesime: string; global?: { taux_tracabilite_pct?: number } }>('tracabilite/resume.json')
  const t = r?.global?.taux_tracabilite_pct
  return typeof t === 'number' ? { euros: Math.round(100 - t), millesime: r!.millesime } : null
}

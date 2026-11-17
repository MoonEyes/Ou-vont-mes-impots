// Répartition de ce que paie le foyer entre administrations, d'après les destinataires (et leurs ventilations).
import { destinataire } from './destinataires'
import type { Prelevement } from './types'

export const ORDRE_ADMIN = ['Securite sociale', 'Etat', 'Collectivites locales', 'Plusieurs'] as const
export const NOM_SUR100: Record<string, string> = {
  'Securite sociale': 'Sécurité sociale',
  Etat: 'État',
  'Collectivites locales': 'collectivités',
  Plusieurs: 'sans destinataire publié',
}

export function parAdministration(lignes: Prelevement[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const l of lignes) {
    if (l.non_chiffre) continue
    const parts = l.ventilation?.length ? l.ventilation : [{ destinataire: String(l.destinataire.id), part: 1 }]
    for (const v of parts) {
      const a = v.destinataire === l.destinataire.id ? l.destinataire.administration : destinataire(v.destinataire).administration
      out[a] = (out[a] ?? 0) + l.montant_annuel_eur.central * v.part
    }
  }
  return out
}

/** Arrondis à l'euro sur 100 € dont la somme fait exactement 100 (méthode du plus fort reste). */
export function sur100Entiers(valeurs: Record<string, number>): Record<string, number> {
  const total = Object.values(valeurs).reduce((a, b) => a + b, 0)
  if (total <= 0) return {}
  const brut = Object.entries(valeurs).map(([k, v]) => ({ k, x: (v / total) * 100 }))
  const base = brut.map((b) => ({ ...b, e: Math.floor(b.x) }))
  let reste = 100 - base.reduce((s, b) => s + b.e, 0)
  for (const b of [...base].sort((p, q) => q.x - q.e - (p.x - p.e))) {
    if (reste <= 0) break
    b.e += 1
    reste--
  }
  return Object.fromEntries(base.map((b) => [b.k, b.e]))
}

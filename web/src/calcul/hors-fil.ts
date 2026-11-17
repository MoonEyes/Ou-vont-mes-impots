// Appel du moteur de calcul dans un Web Worker (même origine, autorisé par la CSP worker-src 'self').
// Repli sur le fil principal si le navigateur refuse le worker (ou dans les tests).
import type { OptionsCalcul } from './moteur'
import type { Profil, Resultat } from './types'

let travailleur: Worker | null = null
let indisponible = typeof Worker === 'undefined' || import.meta.env?.MODE === 'test'
let suivant = 0
const attentes = new Map<number, { ok: (r: Resultat) => void; ko: (e: Error) => void }>()

function obtenir(): Worker | null {
  if (indisponible) return null
  if (travailleur) return travailleur
  try {
    travailleur = new Worker(new URL('./moteur-travailleur.ts', import.meta.url), { type: 'module' })
    travailleur.onmessage = (e: MessageEvent<{ id: number; resultat?: Resultat; echec?: string }>) => {
      const a = attentes.get(e.data.id)
      if (!a) return
      attentes.delete(e.data.id)
      if (e.data.resultat) a.ok(e.data.resultat)
      else a.ko(new Error(e.data.echec ?? 'calcul impossible'))
    }
    travailleur.onerror = () => {
      // Worker non chargé (navigateur ancien, politique de sécurité) : on repasse sur le fil principal.
      indisponible = true
      travailleur = null
      for (const a of attentes.values()) a.ko(new Error('worker indisponible'))
      attentes.clear()
    }
  } catch {
    indisponible = true
    travailleur = null
  }
  return travailleur
}

/** Démarre le worker à l'avance (le moteur, environ 160 Ko compressés, se charge pendant la saisie). */
export function prechauffer() {
  obtenir()
}

async function surFilPrincipal(profil: Profil, options: OptionsCalcul): Promise<Resultat> {
  const m = await import('./moteur')
  return m.calculer(profil, options)
}

export async function calculerHorsFil(profil: Profil, options: OptionsCalcul): Promise<Resultat> {
  const w = obtenir()
  if (!w) return surFilPrincipal(profil, options)
  const id = ++suivant
  try {
    return await new Promise<Resultat>((ok, ko) => {
      attentes.set(id, { ok, ko })
      w.postMessage({ id, profil, options })
    })
  } catch {
    return surFilPrincipal(profil, options)
  }
}

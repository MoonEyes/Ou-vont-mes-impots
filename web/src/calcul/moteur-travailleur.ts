// Web Worker du calcul : le moteur publicodes (environ 2 s de calcul sur un téléphone moyen) tourne hors
// du fil principal, la page reste réactive. Aucun appel réseau : le profil arrive par message et repart calculé.
import { calculer, type OptionsCalcul } from './moteur'
import type { Profil } from './types'

self.onmessage = (e: MessageEvent<{ id: number; profil: Profil; options: OptionsCalcul }>) => {
  const { id, profil, options } = e.data
  try {
    self.postMessage({ id, resultat: calculer(profil, options) })
  } catch (err) {
    self.postMessage({ id, echec: String(err) })
  }
}

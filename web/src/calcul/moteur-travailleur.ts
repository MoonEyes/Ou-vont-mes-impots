// Web Worker du calcul : le moteur publicodes (environ 2 s de calcul sur un téléphone moyen) tourne hors
// du fil principal, la page reste réactive. Aucun appel réseau : le profil arrive par message et repart calculé.
import { calculer, type OptionsCalcul } from './moteur'
import { calculerProfil, type OptionsCalculEtendu } from './moteur-etendu'
import type { Profil, ProfilEtendu } from './types'

// etendu : calcul de tous les profils (calculerProfil) au lieu du calcul du contrat 1.0 (calculer).
self.onmessage = (e: MessageEvent<{ id: number; profil: Profil | ProfilEtendu; options: OptionsCalcul | OptionsCalculEtendu; etendu?: boolean }>) => {
  const { id, profil, options, etendu } = e.data
  try {
    self.postMessage({ id, resultat: etendu ? calculerProfil(profil as ProfilEtendu, options) : calculer(profil as Profil, options) })
  } catch (err) {
    self.postMessage({ id, echec: String(err) })
  }
}

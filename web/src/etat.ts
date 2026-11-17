// État de la session, en mémoire seulement : rien n'est écrit sur l'appareil
// (ni cookie, ni stockage local) et rien n'est envoyé. Fermer l'onglet efface tout.
import type { Profil, ResultatOk } from './calcul/types'

export const session: {
  profil: Profil | null
  resultat: ResultatOk | null
  communeNom: string | null
  communeTaux: [number | null, number | null] | null
} = { profil: null, resultat: null, communeNom: null, communeTaux: null }

export function oublier() {
  session.profil = null
  session.resultat = null
  session.communeNom = null
  session.communeTaux = null
}

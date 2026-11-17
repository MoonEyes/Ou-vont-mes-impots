// État de la session, en mémoire seulement : rien n'est écrit sur l'appareil
// (ni cookie, ni stockage local) et rien n'est envoyé. Fermer l'onglet efface tout.
import type { Complet, HabitudesConso } from './calcul/hors-bulletin'
import type { Profil, ResultatOk } from './calcul/types'

export const session: {
  profil: Profil | null
  resultat: ResultatOk | null
  communeNom: string | null
  communeTaux: [number | null, number | null] | null
  habitudes: HabitudesConso
  complet: Complet | null
  /** saisie commencée dans le héros de l'accueil (salaire, commune) : reprise une fois par le formulaire, jamais mise dans une adresse */
  amorce: { net: string; insee?: string } | null
} = { profil: null, resultat: null, communeNom: null, communeTaux: null, habitudes: { voiture: 'inconnu', fumeur: 'inconnu' }, complet: null, amorce: null }

export function oublier() {
  session.profil = null
  session.resultat = null
  session.communeNom = null
  session.communeTaux = null
  session.complet = null
}

// Retour au résultat du calcul, posé en haut des pages du parcours (budget de l'État, suivre un euro, fiche de paie)
// quand un calcul a été fait pendant la visite : le résultat reste à un clic, sans repasser par le formulaire.
// Rien n'est lu dans une adresse : le calcul reste en mémoire de la page (src/etat.ts), jamais enregistré.
import { session } from '../etat'

export function retourResultat(): string {
  if (!session.resultat) return ''
  return `<nav class="retour-resultat" aria-label="Ton calcul"><a href="#/calcul/resultat">Revenir à mon résultat</a><a href="#/calcul">Modifier mon salaire</a></nav>`
}

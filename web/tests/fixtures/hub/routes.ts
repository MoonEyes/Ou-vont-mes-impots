// Table de routes d'essai pour tests/hub.test.ts : un hub « /essai » dont les rayons sont déclarés dans le désordre,
// avec un thème connu, un thème inconnu, une route sans thème et une page à paramètre (sansIndex).
import type { Route } from '../../../src/routeur'

const vide = async () => ({ rendre: () => {} })

export const ROUTES_ESSAI: Route[] = [
  { chemin: '/essai', titre: 'Hub d’essai', description: 'Hub d’essai.', charger: vide },
  { chemin: '/essai/z', theme: 'politiques', titre: 'Zones humides', resume: 'Dernière par l’alphabet.', description: 'z', parent: '/essai', charger: vide },
  { chemin: '/essai/e', theme: 'politiques', titre: 'L’école', court: 'École', resume: 'Triée sur son libellé court, accent ignoré.', description: 'e', parent: '/essai', charger: vide },
  { chemin: '/essai/a', theme: 'politiques', titre: 'Armées', resume: 'Première par l’alphabet.', description: 'a', parent: '/essai', charger: vide },
  { chemin: '/essai/sans', titre: 'Page sans thème', resume: 'Toujours affichée.', description: 's', parent: '/essai', charger: vide },
  { chemin: '/essai/faute', theme: 'politique-de-faute', titre: 'Thème inconnu', resume: 'Rangée dans les autres pages.', description: 'f', parent: '/essai', charger: vide },
  { chemin: '/essai/recu', theme: 'qui-recoit', titre: 'Bénéficiaires', resume: 'Avant les politiques : ordre des thèmes.', description: 'r', parent: '/essai', charger: vide },
  { chemin: '/essai/parametre', theme: 'qui-recoit', titre: 'Fiche à paramètre', description: 'p', sansIndex: true, parent: '/essai', charger: vide },
  { chemin: '/essai/e/sous', theme: 'politiques', titre: 'Sous-page', description: 'sous', parent: '/essai/e', charger: vide },
  { chemin: '/seul', titre: 'Hub à un thème', description: 'seul', charger: vide },
  { chemin: '/seul/b', theme: 'comprendre', titre: 'Bêta', description: 'b', parent: '/seul', charger: vide },
  { chemin: '/seul/a', theme: 'comprendre', titre: 'Alpha', description: 'a', parent: '/seul', charger: vide },
]

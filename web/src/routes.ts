import type { Route } from './routeur'

// Table des routes : chemin, parent (hub) et voisins servent au fil d'Ariane et au maillage.
export const ROUTES: Route[] = [
  { chemin: '/', titre: 'Accueil', charger: () => import('./ecrans/accueil') },
  { chemin: '/calcul', titre: 'Ton salaire', court: 'Mon calcul', charger: () => import('./ecrans/saisie'), sansVoisins: true },
  { chemin: '/calcul/resultat', titre: 'Ce que tu finances', court: 'Résultat', parent: '/calcul', charger: () => import('./ecrans/paie'), sansVoisins: true },

  { chemin: '/explorer', titre: 'Explorer les dépenses publiques', court: 'Explorer', charger: () => import('./ecrans/explorer') },
  { chemin: '/explorer/etat', titre: 'Sur 100 € dépensés par l’État', court: 'Budget de l’État', parent: '/explorer', voisins: ['/explorer/secu', '/explorer/collectivites'], resume: 'Les grands postes du budget de l’État et la part payée par l’emprunt.', charger: () => import('./ecrans/etat') },
  { chemin: '/explorer/etat/detail', titre: 'Le détail du budget de l’État', court: 'Détail', parent: '/explorer/etat', voisins: ['/beneficiaires', '/decisions/realisations'], charger: () => import('./ecrans/detail') },
  { chemin: '/explorer/secu', titre: 'Sécurité sociale et protection sociale', court: 'Sécurité sociale', parent: '/explorer', voisins: ['/explorer/etat', '/explorer/dette'], resume: 'Retraites, santé, famille, chômage : les dépenses des organismes sociaux.', charger: () => import('./ecrans/secu') },
  { chemin: '/explorer/collectivites', titre: 'Les collectivités locales', court: 'Collectivités', parent: '/explorer', voisins: ['/local', '/explorer/etat'], resume: 'Communes, départements, régions : leurs recettes, leurs dépenses, ce que l’État leur verse.', charger: () => import('./ecrans/collectivites') },
  { chemin: '/explorer/ue', titre: 'La France et l’Union européenne', court: 'Union européenne', parent: '/explorer', voisins: ['/explorer/etat', '/explorer/recettes'], resume: 'Ce que la France verse au budget européen, ce qui revient, qui le reçoit.', charger: () => import('./ecrans/ue') },
  { chemin: '/explorer/recettes', titre: 'D’où vient l’argent : les recettes', court: 'Recettes', parent: '/explorer', voisins: ['/explorer/niches', '/explorer/dette'], resume: 'Chaque grand impôt et l’administration qui l’encaisse, depuis 2005.', charger: () => import('./ecrans/recettes') },
  { chemin: '/explorer/dette', titre: 'La dette publique', court: 'Dette', parent: '/explorer', voisins: ['/explorer/recettes', '/explorer/secu'], resume: 'Encours, intérêts payés chaque année et détenteurs de la dette.', charger: () => import('./ecrans/dette') },
  { chemin: '/explorer/operateurs', titre: 'Les opérateurs de l’État', court: 'Opérateurs', parent: '/explorer', voisins: ['/explorer/etat', '/beneficiaires'], resume: 'Universités, ARS, agences de l’eau : ce que l’État leur verse, leurs emplois.', charger: () => import('./ecrans/operateurs') },
  { chemin: '/explorer/niches', titre: 'Dépenses fiscales et niches sociales', court: 'Niches fiscales', parent: '/explorer', voisins: ['/explorer/recettes', '/explorer/etat'], resume: 'Les réductions d’impôt et de cotisations, mesure par mesure.', charger: () => import('./ecrans/niches') },

  { chemin: '/local', titre: 'Chez moi : ta commune', court: 'Chez moi', charger: () => import('./ecrans/local') },
  { chemin: '/local/commune', titre: 'Ta commune', court: 'Ta commune', parent: '/local', voisins: ['/explorer/collectivites', '/decisions/controle'], charger: () => import('./ecrans/commune') },

  { chemin: '/beneficiaires', titre: 'Qui reçoit l’argent', court: 'Qui reçoit l’argent', charger: () => import('./ecrans/beneficiaires') },
  { chemin: '/beneficiaires/programme', titre: 'Un programme en détail', court: 'Programme', parent: '/beneficiaires', voisins: ['/decisions/realisations', '/decisions/votes'], resume: 'À quoi sert l’argent d’un programme : nature de la dépense et effectifs.', charger: () => import('./ecrans/concret') },

  { chemin: '/decisions', titre: 'Décisions et contrôle', court: 'Décisions et contrôle', charger: () => import('./ecrans/decisions') },
  { chemin: '/decisions/votes', titre: 'Votes, amendements et mouvements de crédits', court: 'Votes', parent: '/decisions', voisins: ['/decisions/realisations', '/decisions/controle'], resume: 'Ce que le Parlement a voté et ce que le Gouvernement a modifié en cours d’année.', charger: () => import('./ecrans/votes') },
  { chemin: '/decisions/realisations', titre: 'Ce qui a été fait', court: 'Réalisations', parent: '/decisions', voisins: ['/decisions/votes', '/decisions/controle'], resume: 'Prévu, dépensé, indicateurs de résultat et notes de la Cour des comptes.', charger: () => import('./ecrans/realisations') },
  { chemin: '/decisions/controle', titre: 'Contrôle, influence et aides aux entreprises', court: 'Contrôle', parent: '/decisions', voisins: ['/decisions/realisations', '/decisions/vie-politique'], resume: 'Rapports des juridictions financières, représentants d’intérêts, aides aux entreprises.', charger: () => import('./ecrans/controle') },
  { chemin: '/decisions/vie-politique', titre: 'Vie politique', court: 'Vie politique', parent: '/decisions', voisins: ['/decisions/votes', '/decisions/controle'], resume: 'Élections, aide publique aux partis, comptes de campagne.', charger: () => import('./ecrans/viepolitique') },

  { chemin: '/methode', titre: 'Méthode et sources', court: 'Méthode', charger: () => import('./ecrans/methode') },
  { chemin: '/methode/tracabilite', titre: 'Traçabilité : d’où vient chaque montant', court: 'Traçabilité', parent: '/methode', voisins: ['/methode/limites', '/mentions'], resume: 'Part de l’argent dont le destinataire est publié, bloc par bloc.', charger: () => import('./ecrans/tracabilite') },
  { chemin: '/methode/limites', titre: 'Limites connues', court: 'Limites', parent: '/methode', voisins: ['/methode/tracabilite', '/mentions'], resume: 'Ce que les données ne permettent pas de dire.', charger: () => import('./ecrans/limites') },
  { chemin: '/mentions', titre: 'Mentions légales et confidentialité', court: 'Mentions', parent: '/methode', voisins: ['/methode/tracabilite', '/methode/limites'], resume: 'Éditeur, hébergeur, données personnelles.', charger: () => import('./ecrans/mentions') },
]

export const route = (chemin: string) => ROUTES.find((r) => r.chemin === chemin)
export const rayons = (parent: string) => ROUTES.filter((r) => r.parent === parent)

// Destinataires des prélèvements (contrat, section 3.5).
import type { Administration, Destinataire, IdDestinataire } from './types'

const D = (id: IdDestinataire, nom: string, administration: Administration): Destinataire => ({ id, nom, administration })

export const DESTINATAIRES: Record<IdDestinataire, Destinataire> = {
  cnam: D('cnam', 'Assurance maladie', 'Securite sociale'),
  cnav: D('cnav', 'Assurance retraite (branche vieillesse)', 'Securite sociale'),
  cnaf: D('cnaf', 'Allocations familiales', 'Securite sociale'),
  branche_atmp: D('branche_atmp', 'Accidents du travail et maladies professionnelles', 'Securite sociale'),
  cnsa: D('cnsa', 'Branche autonomie', 'Securite sociale'),
  cades: D('cades', "Caisse d'amortissement de la dette sociale (CADES)", 'Securite sociale'),
  agirc_arrco: D('agirc_arrco', 'Agirc-Arrco (retraite complémentaire)', 'Securite sociale'),
  unedic: D('unedic', 'Unédic (assurance chômage)', 'Securite sociale'),
  ags: D('ags', 'AGS (garantie des salaires)', 'Securite sociale'),
  apec: D('apec', "Apec (association pour l'emploi des cadres)", 'Securite sociale'),
  fnal: D('fnal', "Fonds national d'aide au logement", 'Etat'),
  france_competences: D('france_competences', 'Formation professionnelle et apprentissage', 'Etat'),
  aom: D('aom', 'Autorité organisatrice de la mobilité (transports)', 'Collectivites locales'),
  etat: D('etat', 'État', 'Etat'),
  commune: D('commune', 'Commune et intercommunalité', 'Collectivites locales'),
  epci: D('epci', 'Intercommunalité', 'Collectivites locales'),
  departement: D('departement', 'Département', 'Collectivites locales'),
  plusieurs: D('plusieurs', 'Sécurité sociale (plusieurs branches)', 'Securite sociale'),
  // Destinataires des profils étendus (prelevements/affectation.json, commit 32e891c) : libellés lisibles, famille de
  // couleur de leur administration (billet.ts, FAMILLE_ADMIN).
  fsv: D('fsv', 'Fonds de solidarité vieillesse', 'Securite sociale'),
  cas_pensions: D('cas_pensions', 'État, compte des pensions des fonctionnaires de l’État', 'Etat'),
  cnracl: D('cnracl', 'Caisse de retraite des fonctionnaires territoriaux et hospitaliers (CNRACL)', 'Securite sociale'),
  ircantec: D('ircantec', 'Retraite complémentaire des agents publics contractuels (Ircantec)', 'Securite sociale'),
  erafp: D('erafp', 'Retraite additionnelle de la fonction publique (ERAFP)', 'Securite sociale'),
  rci_independants: D('rci_independants', 'Retraite complémentaire des indépendants (Assurance retraite)', 'Securite sociale'),
  regime_local_am: D('regime_local_am', 'Assurance maladie du régime local d’Alsace-Moselle', 'Securite sociale'),
}

/** Destinataires lus dans prelevements/affectation.json (contrat 1.4), ajoutés au registre du contrat. */
const SUPPLEMENTAIRES: Record<string, Destinataire> = {
  // Taxes sur la consommation sans affectation publiée (calcul/hors-bulletin.ts) : libellé lisible, jamais l'identifiant.
  autres_taxes_produits: { id: 'autres_taxes_produits', nom: 'Plusieurs bénéficiaires (répartition non sourcée)', administration: 'Plusieurs' },
  // Lignes des profils étendus sans entrée dans affectation.json (moteur-etendu.ts, NON_AFFECTE) : aucune répartition supposée.
  non_affecte: { id: 'non_affecte', nom: 'Destinataire non publié dans les données du site', administration: 'Plusieurs' },
  // Ligne répartie entre organismes de plusieurs administrations (agregats.ts) : le détail est dans sa ventilation.
  plusieurs_organismes: { id: 'plusieurs_organismes', nom: 'Plusieurs organismes (répartition publiée)', administration: 'Plusieurs' },
}
export function enregistrerDestinataires(d: Record<string, { nom: string; administration: string }> | undefined) {
  for (const [id, v] of Object.entries(d ?? {}))
    if (!(id in DESTINATAIRES)) SUPPLEMENTAIRES[id] = { id, nom: v.nom, administration: v.administration as Administration }
}
export function destinataire(id: string): Destinataire {
  return (DESTINATAIRES as Record<string, Destinataire>)[id] ?? SUPPLEMENTAIRES[id] ?? { id, nom: id, administration: 'Plusieurs' }
}

export const LIBELLE_ADMINISTRATION: Record<Administration, string> = {
  Plusieurs: 'Plusieurs administrations',
  Etat: 'État',
  'Collectivites locales': 'Collectivités locales',
  'Securite sociale': 'Sécurité sociale',
}

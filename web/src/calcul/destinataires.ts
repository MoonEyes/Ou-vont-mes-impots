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
}

export const LIBELLE_ADMINISTRATION: Record<Administration, string> = {
  Etat: 'État',
  'Collectivites locales': 'Collectivités locales',
  'Securite sociale': 'Sécurité sociale',
}

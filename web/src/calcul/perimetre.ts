// Contrôles de saisie et de périmètre V1 (contrat, sections 3.2 et 4).
import type { MotifHorsV1, Profil, ResultatErreur } from './types'

const REDIRECTION = { libelle: "Explorer le budget sans calcul personnel", url: './#/explorer' }

export const MESSAGES_HORS_V1: Record<MotifHorsV1, string> = {
  dom: "Les taux et abattements propres aux départements d'outre-mer ne sont pas encore couverts. Tu peux explorer le budget sans calcul personnel.",
  etranger: "Les non-résidents sont imposés différemment : ce cas n'est pas encore couvert.",
  alsace_moselle: "Le régime local d'assurance maladie d'Alsace-Moselle (cotisation supplémentaire) n'est pas encore couvert.",
  frontalier: "Un travailleur frontalier paie ses cotisations dans le pays où il travaille : ce cas n'est pas couvert.",
  fonctionnaire: "Les fonctionnaires cotisent à d'autres régimes (pension civile, RAFP) : ce cas n'est pas encore couvert.",
  contractuel_public: "Les contractuels de la fonction publique cotisent à l'Ircantec : ce cas n'est pas encore couvert.",
  independant: "Les indépendants et micro-entrepreneurs ont d'autres cotisations : ce cas n'est pas encore couvert.",
  retraite: "La CSG et la Casa sur les pensions de retraite ne sont pas encore couvertes.",
  demandeur_emploi: "Les prélèvements sur les allocations chômage ne sont pas encore couverts.",
  apprenti: "Les apprentis bénéficient d'exonérations propres : ce cas n'est pas encore couvert.",
  etudiant: "Sans salaire, il n'y a pas de fiche de paie à analyser.",
  sans_activite_seul: "Sans salaire du privé dans le foyer, il n'y a pas de fiche de paie à analyser.",
}

function horsV1(motif: MotifHorsV1): ResultatErreur {
  return {
    statut: 'erreur',
    version_contrat: '1.0',
    erreur: { code: 'PROFIL_HORS_V1', motif, message: MESSAGES_HORS_V1[motif], redirection: REDIRECTION },
  }
}

function invalide(champ: string, message: string): ResultatErreur {
  return { statut: 'erreur', version_contrat: '1.0', erreur: { code: 'SAISIE_INVALIDE', champ, message } }
}

/** Vérifie la saisie (schéma) puis le périmètre V1 ; renvoie null si le profil est calculable. */
export function verifierProfil(p: Profil): ResultatErreur | null {
  if (!p || p.version_contrat !== '1.0') return invalide('/version_contrat', 'Version de profil inconnue.')
  if (!Number.isInteger(p.annee_revenus) || p.annee_revenus < 2025 || p.annee_revenus > 2030)
    return invalide('/annee_revenus', "Année de revenus hors de la plage gérée.")
  const couple = p.foyer.situation === 'couple_marie_pacse' || p.foyer.situation === 'couple_union_libre'
  if (couple && p.personnes.length !== 2) return invalide('/personnes', 'Un couple compte deux personnes.')
  if (!couple && p.personnes.length !== 1) return invalide('/personnes', 'Une seule personne attendue.')
  if (p.foyer.enfants.length > 10) return invalide('/foyer/enfants', '10 enfants au plus.')
  if (p.residence.commune_insee && !/^(([0-9]{2}|2[AB])[0-9]{3}|97[0-9]{3})$/.test(p.residence.commune_insee))
    return invalide('/residence/commune_insee', 'Code commune INSEE invalide.')
  for (let i = 0; i < p.personnes.length; i++) {
    const q = p.personnes[i]
    if (q.statut_activite !== 'salarie_prive') continue
    const net = q.salaire_net_avant_impot_mensuel
    if (typeof net !== 'number' || !Number.isFinite(net) || net <= 0)
      return invalide(`/personnes/${i}/salaire_net_avant_impot_mensuel`, 'Indique un salaire net mensuel supérieur à 0 €.')
    if (net > 100000)
      return invalide(`/personnes/${i}/salaire_net_avant_impot_mensuel`, 'Montant mensuel trop élevé pour ce simulateur.')
    const t = q.temps_travail
    if (t && t.type === 'temps_partiel' && !(t.quotite > 0 && t.quotite <= 1))
      return invalide(`/personnes/${i}/temps_travail/quotite`, 'La quotité doit être comprise entre 1 % et 100 %.')
  }

  // Périmètre V1, dans l'ordre du contrat (3.2).
  if (p.residence.zone === 'dom') return horsV1('dom')
  if (p.residence.zone === 'etranger') return horsV1('etranger')
  if (p.residence.alsace_moselle) return horsV1('alsace_moselle')
  if (p.personnes.some((q) => q.frontalier)) return horsV1('frontalier')
  const ordre: MotifHorsV1[] = ['fonctionnaire', 'contractuel_public', 'independant', 'retraite', 'demandeur_emploi', 'apprenti']
  for (const m of ordre) if (p.personnes.some((q) => q.statut_activite === m)) return horsV1(m)
  if (p.personnes.some((q) => q.statut_activite === 'etudiant' && !q.salaire_net_avant_impot_mensuel)) return horsV1('etudiant')
  if (!p.personnes.some((q) => q.statut_activite === 'salarie_prive')) return horsV1('sans_activite_seul')
  if (p.personnes.some((q) => q.statut_activite === 'etudiant')) return horsV1('etudiant')
  return null
}

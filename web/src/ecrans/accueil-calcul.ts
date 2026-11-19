// Porte « Mon salaire » de l'accueil : calcul lancé directement depuis le héros, sans passer par l'écran de saisie.
// Situation par défaut, celle que le formulaire (src/ecrans/saisie.ts) retient quand on ne précise rien : une
// personne seule, salariée du secteur privé, à temps plein, locataire, en France métropolitaine (Alsace-Moselle
// selon la commune). Même moteur et mêmes données que le formulaire ; le profil est gardé en mémoire, si bien que
// « Modifier ma saisie » rouvre le formulaire prérempli. Chargé à la demande (import()) : rien ne pèse sur l'accueil.
import { enregistrerDestinataires } from '../calcul/destinataires'
import { verifierProfilEtendu } from '../calcul/perimetre-etendu'
import type { ProfilEtendu } from '../calcul/types'
import { ALSACE_MOSELLE, departementDe } from '../departements'
import { chargerSiPresent } from '../donnees'
import { session } from '../etat'

const INSEE = /^(\d{5}|2[AB]\d{3})$/

/** Profil du chemin simple, tel que le formulaire le construit sans aucune précision. */
export function profilParDefaut(net: number, insee?: string): ProfilEtendu {
  const commune = insee && INSEE.test(insee) ? insee : undefined
  const dep = commune ? departementDe(commune) : null
  return {
    version_contrat: '1.0',
    annee_revenus: 2025,
    residence: { zone: 'metropole', alsace_moselle: !!dep && ALSACE_MOSELLE.has(dep), ...(commune ? { commune_insee: commune } : {}) },
    foyer: { situation: 'celibataire', enfants: [] },
    logement: { statut: 'locataire' },
    personnes: [{ role: 'declarant1', statut_activite: 'salarie_prive', frontalier: false, salaire_net_avant_impot_mensuel: net, cadre: false, temps_travail: { type: 'temps_plein' } }],
  }
}

/**
 * Calcule et range le résultat dans la session. Renvoie 'resultat' quand l'écran résultat peut s'ouvrir,
 * 'saisie' quand le formulaire doit prendre le relais (saisie hors du chemin simple, message à côté du champ).
 */
export async function calculerDepuisAccueil(netTexte: string, insee?: string): Promise<'resultat' | 'saisie'> {
  const net = Number(netTexte)
  if (!(net > 0)) return 'saisie'
  const profil = profilParDefaut(net, insee)
  if (verifierProfilEtendu(profil)) return 'saisie'
  const communeCode = profil.residence.commune_insee
  const dep = communeCode ? departementDe(communeCode) : null
  const [horsFil, hb, affectation, tva, tfDep, communes] = await Promise.all([
    import('../calcul/hors-fil'),
    import('../calcul/hors-bulletin'),
    chargerSiPresent('prelevements/affectation.json'),
    chargerSiPresent('prelevements/tva_conso.json'),
    dep ? chargerSiPresent(`prelevements/taxe_fonciere/${dep}.json`) : Promise.resolve(null),
    dep ? chargerSiPresent<{ communes: Record<string, [string, number | null, number | null]> }>(`communes/${dep}.json`) : Promise.resolve(null),
  ])
  const commune = communeCode ? (communes?.communes[communeCode] ?? null) : undefined
  enregistrerDestinataires((affectation as { destinataires?: Record<string, { nom: string; administration: string }> } | null)?.destinataires)
  const res = await horsFil.calculerProfilHorsFil(profil, { affectation, commune })
  if (res.statut === 'erreur') return 'saisie'
  session.habitudes = { voiture: 'inconnu', fumeur: 'inconnu' }
  session.complet = hb.assembler(
    profil,
    res,
    { tva, affectation, tfDep, ligneCommune: communeCode && tfDep ? (tfDep.communes[communeCode] ?? null) : undefined },
    session.habitudes,
  )
  session.profil = profil
  session.resultat = res
  session.communeNom = commune ? commune[0] : null
  session.communeTaux = commune ? [commune[1], commune[2]] : null
  return 'resultat'
}

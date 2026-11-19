// Contrôle de saisie et de périmètre des profils étendus (verifierProfilEtendu), sans le moteur publicodes :
// l'écran de saisie l'utilise sur le fil principal, avant de charger le calcul (Web Worker). Le calcul
// (moteur-etendu.ts) appelle la même fonction : un profil refusé ici l'est aussi là, avec le même message.
import { BAREMES_2025 as B, MILLESIME_BAREMES } from './baremes-2025'
import type { ActiviteMicro, MotifHorsPerimetre, PersonneEtendue, ProfilCalcule, ProfilEtendu, ResultatErreurEtendu, TerritoireOutreMer } from './types'

/** Départements d'outre-mer calculés, avec le code INSEE de leur département. */
export const TERRITOIRES_DOM: Record<Exclude<TerritoireOutreMer, 'autre_com'>, { nom: string; departement: string }> = {
  guadeloupe: { nom: 'Guadeloupe', departement: '971' },
  martinique: { nom: 'Martinique', departement: '972' },
  guyane: { nom: 'Guyane', departement: '973' },
  reunion: { nom: 'La Réunion', departement: '974' },
  mayotte: { nom: 'Mayotte', departement: '976' },
}

/** Territoire d'outre-mer d'un code commune INSEE (971 à 976), sinon null. */
export function territoireDeCommune(insee: string | undefined): Exclude<TerritoireOutreMer, 'autre_com'> | null {
  if (!insee) return null
  const t = Object.entries(TERRITOIRES_DOM).find(([, v]) => insee.startsWith(v.departement))
  return t ? (t[0] as Exclude<TerritoireOutreMer, 'autre_com'>) : null
}

/** Messages des profils hors périmètre (motif de l'erreur PROFIL_HORS_V1). */
export const MESSAGES_HORS_PERIMETRE: Partial<Record<MotifHorsPerimetre, string>> = {
  dom: "Les taux et abattements propres aux départements d'outre-mer ne sont pas encore couverts. Tu peux explorer le budget sans calcul personnel.",
  mayotte:
    "À Mayotte, la sécurité sociale a ses propres cotisations et la CSG ne s'applique pas aux pensions : ces règles ne sont pas modélisées par le site. Tu peux explorer le budget sans calcul personnel.",
  collectivite_outre_mer:
    "Saint-Martin, Saint-Barthélemy, Saint-Pierre-et-Miquelon, la Polynésie française, la Nouvelle-Calédonie et Wallis-et-Futuna ont leurs propres impôts : ces cas ne sont pas couverts.",
  independant_reel_outre_mer: "Les cotisations des indépendants au régime réel ne sont pas calculées outre-mer.",
  etranger: "Les non-résidents sont imposés différemment : ce cas n'est pas encore couvert.",
  frontalier: "Un travailleur frontalier verse ses cotisations dans le pays où il travaille : ce cas n'est pas couvert.",
  demandeur_emploi: 'Les prélèvements sur les allocations chômage ne sont pas encore couverts.',
  etudiant: "Sans revenu d'activité ni pension, il n'y a pas de prélèvement à calculer.",
  sans_activite_seul: "Sans revenu d'activité ni pension dans le foyer, il n'y a pas de prélèvement à calculer.",
  annee_non_couverte: `Les barèmes de ce calcul sont ceux des revenus ${MILLESIME_BAREMES} : une autre année n'est pas couverte.`,
  independant_reel_non_verifie: "Les cotisations des indépendants au régime réel n'ont pas pu être vérifiées contre une autre source : ce cas n'est pas proposé.",
  retraite_alsace_moselle: "La cotisation du régime local d'Alsace-Moselle sur les pensions n'a pas pu être vérifiée : ce cas n'est pas proposé.",
  independant_alsace_moselle_non_verifie: "Le régime local d'Alsace-Moselle n'a été vérifié que pour les salariés du privé : cette combinaison n'est pas proposée.",
}

const REDIRECTION = { libelle: 'Explorer le budget sans calcul personnel', url: './#/explorer' }

/** Erreur « profil hors périmètre », avec son message et la redirection vers l'exploration du budget. */
export function horsPerimetre(motif: MotifHorsPerimetre): ResultatErreurEtendu {
  return { statut: 'erreur', version_contrat: '1.0', erreur: { code: 'PROFIL_HORS_V1', motif, message: MESSAGES_HORS_PERIMETRE[motif] ?? '', redirection: REDIRECTION } }
}
/** Erreur de saisie rattachée à un champ du profil (pointeur JSON, ex. /personnes/0/versant). */
export function saisieInvalide(champ: string, message: string): ResultatErreurEtendu {
  return { statut: 'erreur', version_contrat: '1.0', erreur: { code: 'SAISIE_INVALIDE', champ, message } }
}
const positif = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x) && x > 0
const positifOuNul = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x) && x >= 0

/** Profil de calcul d'une personne, d'après son statut et son régime. */
export function profilDe(p: PersonneEtendue): ProfilCalcule | null {
  switch (p.statut_activite) {
    case 'salarie_prive':
    case 'fonctionnaire':
    case 'contractuel_public':
    case 'retraite':
    case 'apprenti':
    case 'sans_activite':
      return p.statut_activite
    case 'independant':
      return p.independant?.regime === 'reel' ? 'independant_reel' : 'micro_entrepreneur'
    default:
      return null
  }
}

/** Vérifie la saisie puis le périmètre ; renvoie null si le profil est calculable. */
export function verifierProfilEtendu(p: ProfilEtendu, options: { autoriserNonVerifie?: boolean } = {}): ResultatErreurEtendu | null {
  const invalide = saisieInvalide
  const hors = horsPerimetre
  if (!p || p.version_contrat !== '1.0') return invalide('/version_contrat', 'Version de profil inconnue.')
  if (!Number.isInteger(p.annee_revenus)) return invalide('/annee_revenus', 'Année de revenus invalide.')
  const couple = p.foyer.situation === 'couple_marie_pacse' || p.foyer.situation === 'couple_union_libre'
  if (couple && p.personnes.length !== 2) return invalide('/personnes', 'Un couple compte deux personnes.')
  if (!couple && p.personnes.length !== 1) return invalide('/personnes', 'Une seule personne attendue.')
  if (p.foyer.enfants.length > 10) return invalide('/foyer/enfants', '10 enfants au plus.')
  if (p.residence.commune_insee && !/^(([0-9]{2}|2[AB])[0-9]{3}|97[0-9]{3})$/.test(p.residence.commune_insee))
    return invalide('/residence/commune_insee', 'Code commune INSEE invalide.')

  for (let i = 0; i < p.personnes.length; i++) {
    const q = p.personnes[i]
    const champ = (c: string) => `/personnes/${i}/${c}`
    const net = q.salaire_net_avant_impot_mensuel
    const exigerNet = () => {
      if (!positif(net)) return invalide(champ('salaire_net_avant_impot_mensuel'), 'Indique un salaire net mensuel supérieur à 0 €.')
      if (net > 100000) return invalide(champ('salaire_net_avant_impot_mensuel'), 'Montant mensuel au-delà de ce que ce simulateur gère.')
      return null
    }
    const t = q.temps_travail
    if (t && t.type === 'temps_partiel' && !(t.quotite > 0 && t.quotite <= 1))
      return invalide(champ('temps_travail/quotite'), 'La quotité doit être comprise entre 1 % et 100 %.')
    switch (profilDe(q)) {
      case 'salarie_prive':
      case 'contractuel_public': {
        const e = exigerNet()
        if (e) return e
        break
      }
      case 'apprenti': {
        const e = exigerNet()
        if (e) return e
        if (typeof q.apprentissage?.contrat_avant_mars_2025 !== 'boolean')
          return invalide(champ('apprentissage/contrat_avant_mars_2025'), "Indique si le contrat d'apprentissage a été conclu avant le 1er mars 2025.")
        break
      }
      case 'fonctionnaire': {
        if (q.versant !== 'etat' && q.versant !== 'territoriale' && q.versant !== 'hospitaliere')
          return invalide(champ('versant'), 'Indique le versant de la fonction publique : État, territoriale ou hospitalière.')
        if (!positifOuNul(q.primes_mensuelles))
          return invalide(champ('primes_mensuelles'), 'Indique le total mensuel brut des primes et indemnités (0 s’il n’y en a pas).')
        if (q.traitement_indiciaire_brut_mensuel === undefined) {
          const e = exigerNet()
          if (e) return e
        } else if (!positif(q.traitement_indiciaire_brut_mensuel))
          return invalide(champ('traitement_indiciaire_brut_mensuel'), 'Indique un traitement indiciaire brut mensuel supérieur à 0 €.')
        break
      }
      case 'retraite': {
        if (!positifOuNul(q.pension_base_mensuelle) || !positifOuNul(q.pension_complementaire_mensuelle))
          return invalide(champ('pension_base_mensuelle'), 'Indique les montants mensuels de pension de base et de pension complémentaire (0 si aucune).')
        if (!(q.pension_base_mensuelle + q.pension_complementaire_mensuelle > 0))
          return invalide(champ('pension_base_mensuelle'), 'Indique une pension supérieure à 0 €.')
        const c = q.csg_pension
        const tauxOk = !!c && 'taux' in c && ['exonere', 'reduit', 'median', 'normal'].includes(c.taux)
        const rfrOk = !!c && 'revenu_fiscal_reference' in c && positifOuNul(c.revenu_fiscal_reference) && positif(c.parts)
        if (!tauxOk && !rfrOk)
          return invalide(champ('csg_pension'), 'Indique le taux de CSG de ta pension, ou ton revenu fiscal de référence d’il y a deux ans et ton nombre de parts.')
        break
      }
      case 'micro_entrepreneur': {
        const ind = q.independant
        if (!ind || !['vente', 'service_bic', 'service_bnc'].includes(ind.activite ?? ''))
          return invalide(champ('independant/activite'), "Indique la nature de l'activité : vente, prestation de service commerciale ou artisanale, prestation libérale.")
        if (!positif(ind.chiffre_affaires_annuel))
          return invalide(champ('independant/chiffre_affaires_annuel'), "Indique un chiffre d'affaires annuel supérieur à 0 €.")
        if (ind.chiffre_affaires_annuel > B.impot.plafondMicro[ind.activite as ActiviteMicro])
          return invalide(champ('independant/chiffre_affaires_annuel'), "Ce chiffre d'affaires dépasse le plafond du régime micro pour cette activité.")
        if (typeof ind.versement_liberatoire !== 'boolean')
          return invalide(champ('independant/versement_liberatoire'), "Indique si tu as opté pour le versement libératoire de l'impôt.")
        break
      }
      case 'independant_reel': {
        const ind = q.independant
        if (!ind || !['artisan', 'commercant', 'liberale'].includes(ind.categorie ?? ''))
          return invalide(champ('independant/categorie'), "Indique la nature de l'activité : artisan, commerçant ou profession libérale.")
        if (!positif(ind.revenu_professionnel_annuel))
          return invalide(champ('independant/revenu_professionnel_annuel'), 'Indique un revenu professionnel annuel supérieur à 0 €.')
        break
      }
      default:
        break
    }
  }

  if (p.residence.zone === 'dom') {
    const t = p.residence.territoire
    if (!t || !(t in TERRITOIRES_DOM || t === 'autre_com')) return invalide('/residence/territoire', 'Indique le territoire d’outre-mer où tu vis.')
    if (t === 'autre_com') return hors('collectivite_outre_mer')
    if (p.residence.alsace_moselle) return invalide('/residence/alsace_moselle', 'Alsace-Moselle et outre-mer ne vont pas ensemble.')
    const tc = territoireDeCommune(p.residence.commune_insee)
    if (p.residence.commune_insee && tc !== t) return invalide('/residence/commune_insee', `Cette commune n’est pas en ${TERRITOIRES_DOM[t].nom}.`)
    if (t === 'mayotte') return hors('mayotte')
    for (let i = 0; i < p.personnes.length; i++) {
      const c = p.personnes[i].csg_pension
      if (p.personnes[i].statut_activite === 'retraite' && c && !('taux' in c))
        return invalide(
          `/personnes/${i}/csg_pension`,
          'Outre-mer, indique le taux de CSG lu sur le relevé de pension : les seuils de revenu fiscal de référence propres à l’outre-mer pour 2025 ne figurent pas dans les données du site.',
        )
    }
    if (p.personnes.some((q) => profilDe(q) === 'independant_reel')) return hors('independant_reel_outre_mer')
  } else if (territoireDeCommune(p.residence.commune_insee)) return invalide('/residence/zone', 'Cette commune est en outre-mer : choisis « J’habite en outre-mer » et le territoire.')
  if (p.residence.zone === 'etranger') return hors('etranger')
  if (p.personnes.some((q) => q.frontalier)) return hors('frontalier')
  if (p.personnes.some((q) => q.statut_activite === 'demandeur_emploi')) return hors('demandeur_emploi')
  if (p.personnes.some((q) => q.statut_activite === 'etudiant')) return hors('etudiant')
  if (p.personnes.every((q) => q.statut_activite === 'sans_activite')) return hors('sans_activite_seul')
  if (p.annee_revenus !== MILLESIME_BAREMES) return hors('annee_non_couverte')
  const profils = p.personnes.map(profilDe)
  if (!options.autoriserNonVerifie) {
    if (profils.includes('independant_reel')) return hors('independant_reel_non_verifie')
    if (p.residence.alsace_moselle) {
      if (profils.includes('retraite')) return hors('retraite_alsace_moselle')
      // Régime local vérifié pour les salariés du privé seulement ; un fonctionnaire titulaire n'y cotise pas.
      const artisanMicro = p.personnes.some((q) => profilDe(q) === 'micro_entrepreneur' && q.independant?.artisan)
      if (profils.includes('contractuel_public') || profils.includes('apprenti') || artisanMicro) return hors('independant_alsace_moselle_non_verifie')
    }
  } else if (p.residence.alsace_moselle && profils.includes('retraite')) return hors('retraite_alsace_moselle')
  return null
}

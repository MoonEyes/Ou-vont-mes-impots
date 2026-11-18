// Profils du calcul personnel, pour l'affichage (saisie et résultat) : libellés, profil retenu, vérifications et
// limites (« ce qui n'est pas calculé »). Aucun calcul ni moteur ici (module léger, fil principal) : les limites
// reprennent calcul/README.md (section « Limites ») et les vérifications viennent du résultat (VERIFICATIONS).
import { BAREMES_2025, MILLESIME_BAREMES, tauxCsgPension } from './baremes-2025'
import type {
  ActiviteMicro,
  EntreePersonneEtendue,
  PersonneEtendue,
  Prelevement,
  ProfilEtendu,
  ResultatOk,
  ResultatOkEtendu,
  TauxCsgRetraite,
  VerificationProfil,
  Versant,
} from './types'
import { eur } from '../util'

/** Résultat de calculerProfil (profils étendus) : il porte ses vérifications et son millésime. */
export const estResultatEtendu = (r: ResultatOk | null | undefined): r is ResultatOkEtendu =>
  !!r && Array.isArray((r as ResultatOkEtendu).verifications) && !!(r as ResultatOkEtendu).millesime

export const LIBELLE_PROFIL: Record<VerificationProfil['profil'], string> = {
  salarie_prive: 'Salarié·e du secteur privé',
  fonctionnaire: 'Fonctionnaire titulaire',
  contractuel_public: 'Contractuel·le de la fonction publique',
  retraite: 'Retraité·e',
  micro_entrepreneur: 'Micro-entrepreneur·se',
  independant_reel: 'Indépendant·e au régime réel',
  apprenti: 'Apprenti·e',
  sans_activite: 'Sans activité professionnelle',
  alsace_moselle: 'Régime local d’Alsace-Moselle',
  foyer: 'Impôt sur le revenu du foyer',
}
export const LIBELLE_VERSANT: Record<Versant, string> = {
  etat: 'fonction publique de l’État',
  territoriale: 'fonction publique territoriale',
  hospitaliere: 'fonction publique hospitalière',
}
export const LIBELLE_ACTIVITE: Record<ActiviteMicro, string> = {
  vente: 'vente de marchandises',
  service_bic: 'prestations de services commerciales ou artisanales',
  service_bnc: 'activité libérale',
}
export const LIBELLE_TAUX_CSG: Record<TauxCsgRetraite, string> = {
  exonere: 'exonération de CSG',
  reduit: 'CSG au taux réduit de 3,8 %',
  median: 'CSG au taux médian de 6,6 %',
  normal: 'CSG au taux normal de 8,3 %',
}
export const QUI: Record<'declarant1' | 'declarant2', string> = { declarant1: 'Toi', declarant2: 'Ton ou ta conjoint·e' }

/** Âge pivot de l'abattement des plus de 65 ans : né en 1960 ou avant pour les revenus 2025. */
export const ANNEE_NAISSANCE_65_ANS = MILLESIME_BAREMES - BAREMES_2025.impot.abattementAge.ageMinimum

/** Nature des revenus du foyer, pour les libellés (« sur ton salaire », « sur ta pension »...). */
export type NatureRevenus = 'salaire' | 'pension' | 'micro' | 'mixte'
export function natureRevenus(r: ResultatOk): NatureRevenus {
  if (!estResultatEtendu(r)) return 'salaire'
  const natures = new Set(
    r.entree.personnes.map((p) => (p.profil === 'retraite' ? 'pension' : p.profil === 'micro_entrepreneur' || p.profil === 'independant_reel' ? 'micro' : 'salaire')),
  )
  return natures.size === 1 ? ([...natures][0] as NatureRevenus) : natures.size ? 'mixte' : 'salaire'
}
/** « sur ton salaire », « sur ta pension », « sur ton chiffre d'affaires », « sur tes revenus ». */
export const SUR: Record<NatureRevenus, string> = { salaire: 'sur ton salaire', pension: 'sur ta pension', micro: 'sur ton chiffre d’affaires', mixte: 'sur les revenus du foyer' }

/** Profil retenu pour une personne, d'après sa saisie (le calcul confirme ensuite). */
export function profilSaisi(p: PersonneEtendue): VerificationProfil['profil'] | null {
  switch (p.statut_activite) {
    case 'independant':
      return p.independant?.regime === 'reel' ? 'independant_reel' : 'micro_entrepreneur'
    case 'salarie_prive':
    case 'fonctionnaire':
    case 'contractuel_public':
    case 'retraite':
    case 'apprenti':
    case 'sans_activite':
      return p.statut_activite
    default:
      return null
  }
}

/** Taux de CSG d'une pension : lu sur le relevé, ou déduit du revenu fiscal de référence (même règle que le calcul). */
export function tauxCsgRetenu(p: PersonneEtendue): { taux: TauxCsgRetraite; deduit: boolean } | null {
  const c = p.csg_pension
  if (!c) return null
  if ('taux' in c) return { taux: c.taux, deduit: false }
  return { taux: tauxCsgPension(c.revenu_fiscal_reference, c.parts), deduit: true }
}

const mois = (annuel: number) => eur(annuel / 12)
const brutRetrouve = (e?: EntreePersonneEtendue) => (e ? ` (salaire brut retrouvé : ${mois(e.salaire_brut_annuel_estime.central)} par mois)` : '')
const tempsDeTravail = (p: PersonneEtendue) =>
  p.temps_travail?.type === 'temps_partiel' ? `à temps partiel (${Math.round(p.temps_travail.quotite * 100)} %)` : 'à temps plein'

/** Une phrase par personne : profil, montants saisis, montants retrouvés par le calcul. */
export function descriptionPersonne(p: PersonneEtendue, e?: EntreePersonneEtendue): string {
  const net = e ? e.salaire_net_avant_impot_annuel : (p.salaire_net_avant_impot_mensuel ?? 0) * 12
  switch (profilSaisi(p)) {
    case 'salarie_prive':
      return `${LIBELLE_PROFIL.salarie_prive}, ${p.cadre ? 'cadre' : 'non cadre'}, ${tempsDeTravail(p)} : ${mois(net)} net avant impôt par mois${brutRetrouve(e)}.`
    case 'apprenti':
      return `${LIBELLE_PROFIL.apprenti}, contrat signé ${p.apprentissage?.contrat_avant_mars_2025 ? 'avant le 1er mars 2025' : 'le 1er mars 2025 ou après'} : ${mois(net)} net avant impôt par mois${brutRetrouve(e)}. Salaire exonéré d’impôt sur le revenu jusqu’à ${eur(BAREMES_2025.impot.exonerationApprenti)} par an.`
    case 'contractuel_public':
      return `${LIBELLE_PROFIL.contractuel_public}, ${tempsDeTravail(p)} : ${mois(net)} net avant impôt par mois${brutRetrouve(e)}, retraite complémentaire à l’Ircantec.`
    case 'fonctionnaire': {
      const versant = p.versant ? `, ${LIBELLE_VERSANT[p.versant]}` : ''
      const primes = `${eur(p.primes_mensuelles ?? 0)} brut par mois`
      if (p.traitement_indiciaire_brut_mensuel !== undefined)
        return `${LIBELLE_PROFIL.fonctionnaire}${versant} : traitement indiciaire brut de ${eur(p.traitement_indiciaire_brut_mensuel)} par mois et primes de ${primes}, soit ${mois(net)} net avant impôt par mois.`
      const traitement = e?.detail?.traitement_indiciaire_brut_annuel
      return `${LIBELLE_PROFIL.fonctionnaire}${versant} : ${mois(net)} net avant impôt par mois, dont primes et indemnités de ${primes}${
        typeof traitement === 'number' ? ` (traitement indiciaire brut retrouvé : ${mois(traitement)} par mois)` : ''
      }.`
    }
    case 'retraite': {
      const base = e?.detail?.pension_base_brute_annuelle
      const compl = e?.detail?.pension_complementaire_brute_annuelle
      const csg = tauxCsgRetenu(p)
      const age =
        p.annee_naissance === undefined ? '' : p.annee_naissance <= ANNEE_NAISSANCE_65_ANS ? ', 65 ans ou plus fin 2025' : ', moins de 65 ans fin 2025'
      const brut = e ? `pensions de ${mois(e.salaire_brut_annuel_estime.central)} brut par mois${typeof base === 'number' && typeof compl === 'number' ? ` (base ${mois(base)}, complémentaire ${mois(compl)})` : ''}, soit ` : ''
      return `${LIBELLE_PROFIL.retraite}${age} : ${brut}${mois(net)} net avant impôt par mois${
        csg ? ` ; ${LIBELLE_TAUX_CSG[csg.taux]} (${csg.deduit ? 'déduit de ton revenu fiscal de référence' : 'lu sur ton relevé de pension'})` : ''
      }.`
    }
    case 'micro_entrepreneur': {
      const ind = p.independant
      const activite = ind?.activite ? `, ${LIBELLE_ACTIVITE[ind.activite]}${ind.artisan && ind.activite !== 'service_bnc' ? ' (artisanale)' : ''}` : ''
      const vl = ind?.versement_liberatoire ? 'avec versement libératoire de l’impôt' : 'sans versement libératoire'
      return `${LIBELLE_PROFIL.micro_entrepreneur}${activite}, ${vl} : chiffre d’affaires de ${eur(ind?.chiffre_affaires_annuel ?? 0)} en ${MILLESIME_BAREMES}${
        e ? `, soit ${eur(net)} après cotisations et contributions` : ''
      }.`
    }
    case 'independant_reel':
      return `${LIBELLE_PROFIL.independant_reel} : revenu professionnel de ${eur(p.independant?.revenu_professionnel_annuel ?? 0)} en ${MILLESIME_BAREMES}.`
    case 'sans_activite':
      return `${LIBELLE_PROFIL.sans_activite} : pas de revenu d’activité ni de pension dans ce calcul.`
    default:
      return ''
  }
}

const SITUATIONS: Record<ProfilEtendu['foyer']['situation'], string> = {
  celibataire: 'Seul·e',
  parent_isole: 'Seul·e avec enfant(s) à charge',
  couple_marie_pacse: 'En couple, marié·es ou pacsé·es',
  couple_union_libre: 'En couple, sans être marié·es ni pacsé·es',
}
function enfantsTexte(profil: ProfilEtendu): string {
  const n = profil.foyer.enfants.length
  const alt = profil.foyer.enfants.filter((x) => x.garde_alternee).length
  return n ? `${n} enfant${n > 1 ? 's' : ''} à charge${alt ? `, dont ${alt} en garde alternée` : ''}` : 'sans enfant à charge'
}
export function descriptionFoyer(profil: ProfilEtendu): string {
  const s = profil.foyer.situation
  const n = profil.foyer.enfants.length
  if (s === 'couple_marie_pacse') return `${SITUATIONS[s]}, ${enfantsTexte(profil)} : une seule déclaration d’impôt pour le foyer.`
  if (s === 'couple_union_libre') return `${SITUATIONS[s]}, ${enfantsTexte(profil)} : deux déclarations d’impôt${n ? ', enfants rattachés à la tienne' : ''}.`
  if (s === 'parent_isole') return `Seul·e, ${enfantsTexte(profil)} (parent isolé).`
  return `${SITUATIONS[s]}, ${enfantsTexte(profil)}.`
}
export function descriptionLieu(profil: ProfilEtendu, commune: string | null): string {
  const lieu = profil.residence.alsace_moselle
    ? 'Alsace-Moselle : cotisation maladie du régime local appliquée aux salaires du secteur privé'
    : 'France métropolitaine, hors Alsace-Moselle'
  return `${lieu} ; ${commune ? `commune : ${commune}` : 'commune non précisée'}.`
}
export const DESCRIPTION_BAREMES = `Revenus ${MILLESIME_BAREMES} : cotisations et contributions au barème ${MILLESIME_BAREMES}, impôt sur le revenu au barème appliqué en ${MILLESIME_BAREMES + 1}.`

/** Courte description du foyer pour le chapeau du résultat. */
export function resumeProfil(profil: ProfilEtendu, r: ResultatOk): string {
  const sit: Record<string, string> = {
    celibataire: 'Seul·e',
    parent_isole: 'Seul·e avec enfant(s)',
    couple_marie_pacse: 'En couple marié ou pacsé',
    couple_union_libre: 'En couple',
  }
  const n = profil.foyer.enfants.length
  const tete = `${sit[profil.foyer.situation]}, ${n ? `${n} enfant${n > 1 ? 's' : ''}` : 'sans enfant'}`
  // Salariés du privé (avec ou sans conjoint sans activité) : la phrase d'origine, montants saisis.
  if (profil.personnes.every((p) => p.statut_activite === 'salarie_prive' || p.statut_activite === 'sans_activite')) {
    const nets = profil.personnes.filter((x) => x.salaire_net_avant_impot_mensuel).map((x) => eur(x.salaire_net_avant_impot_mensuel!))
    return `${tete}, ${nets.join(' et ')} net avant impôt par mois`
  }
  const entrees = estResultatEtendu(r) ? r.entree.personnes : []
  const morceaux = profil.personnes.map((p) => {
    const e = entrees.find((x) => x.role === p.role)
    const type = profilSaisi(p)
    const libelle = type ? LIBELLE_PROFIL[type].toLowerCase() : ''
    const net = e ? e.salaire_net_avant_impot_annuel / 12 : (p.salaire_net_avant_impot_mensuel ?? 0)
    const montant =
      type === 'retraite'
        ? `, ${eur(net)} de pension nette avant impôt par mois`
        : type === 'micro_entrepreneur'
          ? `, chiffre d’affaires de ${eur(p.independant?.chiffre_affaires_annuel ?? 0)} par an`
          : type === 'sans_activite' || !net
            ? ''
            : `, ${eur(net)} net avant impôt par mois`
    const qui = profil.personnes.length > 1 ? `${QUI[p.role].toLowerCase()} : ` : ''
    return `${qui}${libelle}${montant}`
  })
  return `${tete} ; ${morceaux.join(' ; ')}`
}

/** Vérifications du calcul, une phrase par profil (référence et tolérance publiées dans web/ECARTS.md). */
export function phrasesVerifications(r: ResultatOk): string[] {
  if (!estResultatEtendu(r)) return []
  return r.verifications.map((v) => `${LIBELLE_PROFIL[v.profil]} : ${v.statut === 'verifie' ? 'vérifié' : 'non vérifié'} (${v.reference}).`)
}

/** Lignes sans destinataire publié dans les données du site (aucune répartition supposée). */
export function lignesSansDestinataire(prelevements: Prelevement[]): { verse: string[]; employeur: number } {
  const sans = prelevements.filter((l) => l.destinataire.id === 'non_affecte' && !l.non_chiffre)
  const verse = [...new Set(sans.filter((l) => l.inclus_dans_total_paye).map((l) => l.libelle))]
  const employeur = new Set(sans.filter((l) => !l.inclus_dans_total_paye).map((l) => l.id.replace(/_declarant2$/, ''))).size
  return { verse, employeur }
}

/**
 * Ce que le calcul ne compte pas, pour le profil retenu : limites générales de l'impôt, limites propres à chaque
 * profil (calcul/README.md), lignes sans destinataire publié, impôts locaux sans commune.
 */
export function limitesDuCalcul(profil: ProfilEtendu, r: ResultatOk, communeConnue: boolean): string[] {
  const types = new Set(profil.personnes.map(profilSaisi))
  const out = [
    'Impôt sur le revenu : sans autres revenus (épargne, loyers), sans frais réels, sans réductions ni crédits d’impôt (dons, emploi à domicile, garde d’enfants).',
    'Prestations et aides reçues (allocations familiales, aides au logement, prime d’activité) : non déduites, le calcul porte sur ce que tu verses.',
  ]
  if (types.has('salarie_prive') || types.has('apprenti') || types.has('contractuel_public'))
    out.push('Complémentaire santé et prévoyance d’entreprise : non comptées, elles varient d’un employeur à l’autre.')
  if (types.has('fonctionnaire'))
    out.push(
      'Contributions de l’employeur au Centre national de la fonction publique territoriale, aux centres de gestion et à l’Association nationale pour la formation permanente du personnel hospitalier : non comptées.',
      'Militaires et magistrats : non distingués des autres fonctionnaires. Indemnité de résidence, supplément familial de traitement et indemnité compensatrice de CSG : comptés s’ils sont inclus dans les primes saisies.',
    )
  if (types.has('contractuel_public')) out.push('Contribution de l’employeur public à l’assurance chômage : non comptée (auto-assurance ou adhésion, selon l’employeur).')
  if (types.has('retraite'))
    out.push(
      'CSG sur les pensions : pas de lissage en cas de franchissement d’un seuil une seule année ; seuils de France métropolitaine.',
      'Cotisation maladie de 1 % : appliquée à toute la pension saisie comme complémentaire ; taux relu dans OpenFisca, montant non recoupé par un autre calcul.',
    )
  if (types.has('micro_entrepreneur'))
    out.push(
      'Micro-entreprise : aide à la création ou à la reprise d’entreprise (Acre), activité mixte et professions libérales affiliées à la caisse interprofessionnelle de prévoyance et d’assurance vieillesse (Cipav) non couvertes ; plafond de revenu fiscal de référence ouvrant droit au versement libératoire non contrôlé.',
      'Cotisation foncière des entreprises (impôt local dû par l’entreprise) : non comptée.',
    )
  if (estResultatEtendu(r)) {
    const nonVerifies = r.verifications.filter((v) => v.statut !== 'verifie').map((v) => LIBELLE_PROFIL[v.profil].toLowerCase())
    if (nonVerifies.length) out.push(`Non vérifié contre une autre source : ${nonVerifies.join(', ')}.`)
  }
  const { verse, employeur } = lignesSansDestinataire(r.prelevements)
  if (verse.length || employeur)
    out.push(
      `Répartition entre organismes non publiée dans les données du site pour : ${[
        ...verse,
        ...(employeur ? [`${employeur} ligne${employeur > 1 ? 's' : ''} de la part de l’employeur`] : []),
      ].join(', ')}. Ces montants apparaissent comme « sans destinataire publié », sans répartition supposée : cela décrit l’état des données, pas l’usage de l’argent.`,
    )
  if (!communeConnue && profil.logement?.statut !== 'loge_gratuitement')
    out.push('Commune non précisée : taxe foncière et taxe d’enlèvement des ordures ménagères non chiffrées.')
  return out
}

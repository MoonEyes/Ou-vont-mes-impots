// Écran « Ta fiche de paie expliquée » (/calcul/bulletin). Chaque ligne d'une fiche de paie, rangée dans les rubriques
// du modèle réglementaire du secteur privé (arrêté du 31 janvier 2023) : son montant calculé sur l'appareil par le
// moteur du site (src/calcul, modele-social), une phrase d'explication, l'organisme qui la reçoit
// (prelevements/affectation.json) et la page du site qui montre où va cet argent (secu/index.json relie chaque caisse à
// son bloc de dépenses). Fiche de la saisie de la session (mémoire de la page, jamais une adresse) ou, à défaut, celle
// de l'exemple de l'accueil (src/exemple-lyon.json). Ce qui dépend de l'entreprise (taux d'accidents du travail,
// mutuelle, prévoyance, répartition de la retraite complémentaire) est signalé, jamais inventé.
import exemple from '../exemple-lyon.json'
import { additionner, type Affectation } from '../calcul/agregats'
import { destinataire, enregistrerDestinataires, LIBELLE_ADMINISTRATION } from '../calcul/destinataires'
import { sur100Entiers } from '../calcul/repartition'
import type { Administration, Fourchette, Personne, Prelevement, Profil, ResultatOk } from '../calcul/types'
import { retourResultat } from '../composants/retour-resultat'
import { chargerSiPresent } from '../donnees'
import { session } from '../etat'
import { lien, type Rendu } from '../routeur'
import { route } from '../routes'
import { annoncer, entier, eur, h, pct, rendreDefilables, source, STATUTS, surligne, traitStatut } from '../util'

type Role = 'declarant1' | 'declarant2'
type Periode = 'mois' | 'an'

/** Personne du résultat : champs du contrat 1.0, plus ceux du calcul étendu (calculerProfil) quand il a servi. */
interface PersonneCalculee {
  role: Role
  salaire_net_avant_impot_annuel: number
  salaire_brut_annuel_estime: Fourchette
  profil?: string
  revenu_imposable_annuel?: number
}

/** Profils qui reçoivent une fiche de paie : une pension ou un revenu d'indépendant n'en a pas. */
const AVEC_FICHE = new Set(['salarie_prive', 'apprenti', 'contractuel_public', 'fonctionnaire'])
/** Profils dont le revenu imposable entre dans le taux de prélèvement à la source du foyer, tel que le site le calcule. */
const DANS_LE_TAUX = new Set([...AVEC_FICHE, 'retraite', 'sans_activite'])
const FAMILLES_FICHE = new Set(['cotisation_salariale', 'csg_crds', 'cotisation_patronale'])
/** Plafond mensuel de la Sécurité sociale et seuil de la réduction générale, par année de législation. */
const PLAFOND_MENSUEL: Record<number, number> = { 2025: 3925 }
const SEUIL_REDUCTION: Record<number, string> = { 2025: '1,6 SMIC' }

const cle = (id: string) => id.replace(/_declarant2$/, '')
const patronale = (l: Prelevement) => l.famille === 'cotisation_patronale'
const central = (ls: Prelevement[]) => ls.reduce((s, l) => s + (l.non_chiffre ? 0 : (l.nature === 'reduction' ? -1 : 1) * l.montant_annuel_eur.central), 0)

// ---------------------------------------------------------------------------------------------------------------
// Le modèle de fiche : rubriques du modèle réglementaire, lignes du moteur qui les composent, une phrase par ligne.
// ---------------------------------------------------------------------------------------------------------------

interface Contexte {
  lignes: Prelevement[]
  brut: number
  annee: number
}
interface Lien {
  href: string
  texte: string
}
interface LigneCalculee {
  libelle: string
  /** identifiants du moteur (sans suffixe de personne), parts salarié et employeur confondues */
  ids: string[]
  explication: string | ((c: Contexte) => string)
}
/** Ligne d'une vraie fiche que le site ne calcule pas : elle dépend de l'entreprise ou du contrat. */
interface LigneHorsCalcul {
  libelle: string
  explication: string
  recu?: string
  lien?: Lien
}
interface Rubrique {
  titre: string
  lignes: (LigneCalculee | LigneHorsCalcul)[]
  note?: string
}
const estCalculee = (l: LigneCalculee | LigneHorsCalcul): l is LigneCalculee => 'ids' in l

const DREES: Lien = {
  href: lien('/explorer/secu', { m: 'protection2024' }),
  texte: 'les prestations de protection sociale, dont celles des mutuelles et institutions de prévoyance (statistiques de la DREES)',
}
const taux = (c: Contexte) => (c.lignes[0]?.taux ? ` (${pct(c.lignes[0].taux * 100, 1)})` : '')
const assiette = (c: Contexte) => {
  const a = c.lignes[0]?.assiette_annuelle_eur
  return a && c.brut > 0 ? pct((a / c.brut) * 100, 2) : 'presque tout'
}

/** Cotisations et contributions obligatoires, dans l'ordre des rubriques du modèle de fiche. */
export const OBLIGATOIRES: Rubrique[] = [
  {
    titre: 'Santé',
    lignes: [
      {
        libelle: 'Sécurité sociale maladie, maternité, invalidité, décès',
        ids: ['maladie_salarie', 'maladie_regime_local', 'maladie_employeur'],
        explication: 'Finance les remboursements de soins, les indemnités versées pendant un arrêt maladie ou un congé maternité et les pensions d’invalidité.',
      },
      {
        libelle: 'Complémentaire santé obligatoire (mutuelle d’entreprise)',
        explication: 'Contrat collectif de ton entreprise, obligatoire pour les salariés du privé depuis 2016, dont l’employeur paie au moins la moitié ; le montant dépend de ce contrat.',
        recu: 'l’organisme choisi par ton entreprise (mutuelle, institution de prévoyance ou assureur), hors administrations publiques',
        lien: DREES,
      },
    ],
  },
  {
    titre: 'Accidents du travail et maladies professionnelles',
    lignes: [
      {
        libelle: 'Accidents du travail et maladies professionnelles',
        ids: ['atmp'],
        explication: 'Finance les soins et les indemnités des victimes d’accidents du travail et de maladies professionnelles ; seul l’employeur cotise, à un taux qui dépend de son secteur d’activité et, à partir de 20 salariés, de ses accidents passés.',
      },
      {
        libelle: 'Allocation temporaire d’invalidité',
        ids: ['ati', 'atiacl'],
        explication: 'Finance l’allocation versée aux fonctionnaires qui gardent une invalidité après un accident de service ou une maladie professionnelle.',
      },
    ],
  },
  {
    titre: 'Retraite',
    lignes: [
      {
        libelle: 'Sécurité sociale vieillesse plafonnée',
        ids: ['vieillesse_plafonnee_salarie', 'vieillesse_plafonnee_employeur'],
        explication: (c) =>
          `Finance les retraites de base versées aujourd’hui et t’ouvre des droits pour la tienne, sur ton salaire jusqu’au plafond de la Sécurité sociale${
            PLAFOND_MENSUEL[c.annee] ? ` (${eur(PLAFOND_MENSUEL[c.annee])} brut par mois en ${c.annee})` : ''
          }.`,
      },
      {
        libelle: 'Sécurité sociale vieillesse déplafonnée',
        ids: ['vieillesse_deplafonnee_salarie', 'vieillesse_deplafonnee_employeur'],
        explication: 'Complète le financement des retraites de base, sur la totalité de ton salaire brut.',
      },
      {
        libelle: 'Retraite complémentaire (Agirc-Arrco)',
        ids: ['retraite_complementaire_salarie', 'retraite_complementaire_employeur'],
        explication: 'T’apporte des points de retraite complémentaire, qui s’ajoutent à la retraite de base de tous les salariés du privé.',
      },
      {
        libelle: 'Contribution d’équilibre général (CEG)',
        ids: ['ceg_salarie', 'ceg_employeur'],
        explication: 'Contribution au régime Agirc-Arrco qui sert à son équilibre financier ; elle ne donne pas de points de retraite.',
      },
      {
        libelle: 'Contribution d’équilibre technique (CET)',
        ids: ['cet_salarie', 'cet_employeur'],
        explication: 'Due quand le salaire dépasse le plafond de la Sécurité sociale ; elle sert à l’équilibre du régime Agirc-Arrco et ne donne pas de points de retraite.',
      },
      {
        libelle: 'Retenue pour pension civile',
        ids: ['retenue_pension_civile', 'contribution_cas_pensions'],
        explication: 'Finance les pensions de retraite des fonctionnaires de l’État ; elle porte sur le traitement indiciaire, sans les primes.',
      },
      {
        libelle: 'Retraite des agents territoriaux et hospitaliers (CNRACL)',
        ids: ['retenue_cnracl', 'contribution_cnracl'],
        explication: 'Finance les pensions des fonctionnaires territoriaux et hospitaliers ; elle porte sur le traitement indiciaire, sans les primes.',
      },
      {
        libelle: 'Retraite additionnelle de la fonction publique (RAFP)',
        ids: ['rafp_salarie', 'rafp_employeur'],
        explication: 'T’apporte des points de retraite sur tes primes, dans la limite de 20 % de ton traitement indiciaire.',
      },
      {
        libelle: 'Retraite complémentaire Ircantec',
        ids: ['ircantec_salarie', 'ircantec_employeur'],
        explication: 'Retraite complémentaire par points des agents contractuels de la fonction publique.',
      },
    ],
  },
  {
    titre: 'Famille',
    lignes: [
      {
        libelle: 'Famille',
        ids: ['allocations_familiales'],
        explication: 'Finance la branche famille de la Sécurité sociale, qui verse notamment les allocations familiales et les aides pour faire garder les jeunes enfants.',
      },
    ],
  },
  {
    titre: 'Assurance chômage',
    lignes: [
      {
        libelle: 'Assurance chômage',
        ids: ['chomage'],
        explication: 'Finance les allocations des demandeurs d’emploi, versées par France Travail pour le compte de l’Unédic ; seul l’employeur cotise.',
      },
      {
        libelle: 'Garantie des salaires (AGS)',
        ids: ['ags'],
        explication: 'Paie les salaires dus aux salariés quand leur entreprise est en redressement ou en liquidation judiciaire.',
      },
    ],
  },
  {
    titre: 'Apec',
    lignes: [
      {
        libelle: 'Apec',
        ids: ['apec_salarie', 'apec_employeur'],
        explication: 'Finance l’Association pour l’emploi des cadres, qui conseille les cadres et les jeunes diplômés ; elle est due pour les cadres.',
      },
    ],
  },
  {
    titre: 'Autres contributions dues par l’employeur',
    lignes: [
      {
        libelle: 'Contribution solidarité autonomie',
        ids: ['csa'],
        explication: 'Finance l’aide aux personnes âgées et aux personnes handicapées (branche autonomie) ; elle va de pair avec la journée de solidarité.',
      },
      {
        libelle: 'Fonds national d’aide au logement (FNAL)',
        ids: ['fnal'],
        explication: 'Finance les aides personnelles au logement (aide personnalisée au logement et allocations de logement).',
      },
      {
        libelle: 'Contribution à la formation professionnelle',
        ids: ['formation_professionnelle'],
        explication: 'Finance la formation des salariés et des demandeurs d’emploi, dont le compte personnel de formation, par l’intermédiaire de France compétences.',
      },
      {
        libelle: 'Taxe d’apprentissage',
        ids: ['taxe_apprentissage'],
        explication: 'Finance l’apprentissage et les formations technologiques et professionnelles.',
      },
      {
        libelle: 'Versement mobilité',
        ids: ['versement_mobilite'],
        explication: 'Finance les transports publics de la zone où tu travailles ; il est dû par les employeurs de 11 salariés et plus, à un taux fixé localement.',
      },
      {
        libelle: 'Forfait social',
        ids: ['forfait_social'],
        explication: 'Contribution de l’employeur sur certains compléments de rémunération, comme l’épargne salariale.',
      },
      {
        libelle: 'Fonds pour l’emploi hospitalier',
        ids: ['fonds_emploi_hospitalier'],
        explication: 'Finance des congés de formation et des études promotionnelles des agents hospitaliers.',
      },
      {
        libelle: 'Contribution au dialogue social',
        explication: 'Finance un fonds paritaire qui soutient les organisations syndicales et patronales ; elle figure sur ta fiche (0,016 % du brut) mais n’est pas comptée ici.',
        recu: 'un fonds paritaire, hors administrations publiques',
      },
    ],
  },
  {
    titre: 'Cotisations statutaires ou prévues par la convention collective',
    lignes: [
      {
        libelle: 'Cotisations statutaires ou conventionnelles',
        explication: 'Cotisations propres à ta branche professionnelle ou à ton entreprise, quand il y en a ; le site ne les connaît pas.',
      },
    ],
  },
  {
    titre: 'CSG et CRDS',
    note: 'Sur ta fiche, la CSG non déductible et la CRDS sont souvent réunies sur une seule ligne : « CSG/CRDS non déductible de l’impôt sur le revenu ».',
    lignes: [
      {
        libelle: 'CSG déductible de l’impôt sur le revenu',
        ids: ['csg_deductible'],
        explication: (c) =>
          `Contribution sociale généralisée${taux(c)}, prélevée sur ${assiette(c)} de ton salaire brut, qui finance plusieurs branches de la Sécurité sociale ; cette part n’est pas comptée dans ton revenu imposable.`,
      },
      {
        libelle: 'CSG non déductible de l’impôt sur le revenu',
        ids: ['csg_non_deductible'],
        explication: (c) => `Même contribution${taux(c)}, sur la même base ; cette part reste comptée dans ton revenu imposable.`,
      },
      {
        libelle: 'CRDS',
        ids: ['crds'],
        explication: (c) =>
          `Contribution au remboursement de la dette sociale${taux(c)}, sur la même base : elle rembourse la dette de la Sécurité sociale confiée à la Caisse d’amortissement de la dette sociale (CADES).`,
      },
    ],
  },
  {
    titre: 'Exonérations et allègements de cotisations',
    lignes: [
      {
        libelle: 'Réduction générale des cotisations patronales',
        ids: ['reduction_generale'],
        explication: (c) =>
          `Baisse des cotisations patronales prévue par la loi pour les salaires ${
            SEUIL_REDUCTION[c.annee] ? `inférieurs à ${SEUIL_REDUCTION[c.annee]} en ${c.annee}` : 'proches du SMIC'
          } ; son montant dépend notamment de l’effectif de l’entreprise.`,
      },
    ],
  },
]

/** Cotisations facultatives : propres à l'entreprise, jamais calculées par le site. */
export const FACULTATIVES: Rubrique = {
  titre: 'Cotisations et contributions facultatives',
  lignes: [
    {
      libelle: 'Prévoyance (incapacité, invalidité, décès)',
      explication: 'Assurance de ton entreprise qui complète tes revenus en cas d’arrêt de travail long, d’invalidité ou de décès ; obligatoire pour les cadres (au moins 1,50 % du salaire jusqu’au plafond de la Sécurité sociale, payé par l’employeur), elle dépend sinon de ta convention collective.',
      recu: 'l’organisme choisi par ton entreprise (institution de prévoyance, mutuelle ou assureur), hors administrations publiques',
      lien: DREES,
    },
    {
      libelle: 'Retraite supplémentaire',
      explication: 'Épargne retraite proposée par certaines entreprises, par exemple un plan d’épargne retraite obligatoire ; elle dépend de ton entreprise.',
      recu: 'l’organisme qui gère le contrat, hors administrations publiques',
      lien: DREES,
    },
  ],
}

/** Explication de repli d'une ligne que le modèle ne connaît pas encore (nouvelle ligne du moteur) : jamais perdue. */
const EXPLICATION_REPLI: Record<string, string> = {
  cotisation_salariale: 'Cotisation prélevée sur ton salaire brut, comptée par le moteur de calcul ; le site ne la détaille pas encore.',
  csg_crds: 'Contribution prélevée sur ton salaire, comptée par le moteur de calcul ; le site ne la détaille pas encore.',
  cotisation_patronale: 'Cotisation versée par ton employeur en plus de ton salaire brut, comptée par le moteur de calcul ; le site ne la détaille pas encore.',
}

// ---------------------------------------------------------------------------------------------------------------
// Où va cet argent : chaque destinataire mène à la page du site qui montre ses dépenses.
// ---------------------------------------------------------------------------------------------------------------

/** Destinataires de la Sécurité sociale reliés à un bloc de la page Sécurité sociale (secu/index.json). */
const PAGE_SECU: Record<string, string> = {
  cnam: 'les dépenses de l’Assurance maladie',
  cnav: 'les dépenses de la retraite de base',
  cnaf: 'les dépenses de la branche famille',
  cnsa: 'les dépenses de la branche autonomie',
  branche_atmp: 'les dépenses de la branche accidents du travail',
  agirc_arrco: 'les pensions de l’Agirc-Arrco',
  unedic: 'les dépenses de l’assurance chômage',
  cades: 'le remboursement de la dette sociale',
}
const PAGES: Record<string, Lien> = {
  etat: { href: '#/explorer/etat', texte: 'le budget de l’État, sur 100 € dépensés' },
  plusieurs: { href: '#/explorer/secu', texte: 'les dépenses de la Sécurité sociale' },
  aom: { href: '#/explorer/collectivites', texte: 'les budgets des collectivités locales' },
  france_competences: { href: lien('/explorer/operateurs', { p: '103' }), texte: 'les opérateurs de l’État du programme 103, dont France compétences' },
  non_affecte: { href: '#/methode/tracabilite', texte: 'la part des montants dont le destinataire est publié' },
}
const PAR_ADMINISTRATION: Record<string, Lien> = { 'Securite sociale': PAGES.plusieurs, Etat: PAGES.etat, 'Collectivites locales': PAGES.aom }
/** Organismes dont les comptes ne sont pas dans les données du site : la phrase le dit, avec une page voisine s'il y en a. */
const SANS_PAGE: Record<string, Lien | null> = {
  ags: null,
  apec: null,
  fnal: { href: lien('/beneficiaires/programme', { p: '109' }), texte: 'le programme 109 du budget de l’État (aide à l’accès au logement), qui verse aussi à ce fonds' },
}
/** Pages thématiques plus précises, ajoutées seulement quand la route existe dans la table du site. */
const VOIR_AUSSI: Record<string, string[]> = {
  cnav: ['/explorer/retraites'],
  agirc_arrco: ['/explorer/retraites'],
  cnam: ['/explorer/hopitaux'],
  cnaf: ['/explorer/prestations'],
  unedic: ['/explorer/prestations'],
  fnal: ['/explorer/prestations'],
}

/** La page d'une adresse interne existe-t-elle dans la table des routes ? (prérendu : aucun lien mort) */
const existe = (href: string) => !!route(href.replace(/^#/, '').split('?')[0])
const ancres = (ls: Lien[]) => ls.map((l) => `<a href="${h(l.href)}">${h(l.texte)}</a>`).join(', ')

function pagesDe(id: string, administration: string, noeuds: Record<string, string>, voirAussi = true): Lien[] {
  const out: Lien[] = []
  if (PAGE_SECU[id]) out.push({ href: noeuds[id] ? lien('/explorer/secu', { id: noeuds[id] }) : '#/explorer/secu', texte: PAGE_SECU[id] })
  else if (PAGES[id]) out.push(PAGES[id])
  else if (!(id in SANS_PAGE)) out.push(PAR_ADMINISTRATION[administration] ?? PAGES.non_affecte)
  for (const chemin of voirAussi ? (VOIR_AUSSI[id] ?? []) : []) {
    const r = route(chemin)
    if (r) out.push({ href: '#' + chemin, texte: r.titre.charAt(0).toLowerCase() + r.titre.slice(1) })
  }
  return out.filter((l) => existe(l.href))
}

interface Destinataire_ {
  id: string
  nom: string
  administration: Administration
  part?: number
}
/** Destinataires d'un groupe de lignes : parts publiées quand la ligne est ventilée, sinon son destinataire. */
function destinataires(ls: Prelevement[]): Destinataire_[] {
  const out: Destinataire_[] = []
  for (const l of ls) {
    const parts: Destinataire_[] =
      l.ventilation && l.ventilation.length > 1
        ? l.ventilation.map((v) => ({ ...destinataire(v.destinataire), id: v.destinataire, part: v.part }))
        : [{ ...(l.ventilation?.length === 1 ? destinataire(l.ventilation[0].destinataire) : l.destinataire), id: String(l.ventilation?.[0]?.destinataire ?? l.destinataire.id) }]
    for (const p of parts) if (!out.some((x) => x.id === p.id)) out.push(p)
  }
  return out
}

/** « Reçu par » (noms, parts publiées, administration en pastille) et « où va cet argent » (liens vers les pages). */
function recuPar(ls: Prelevement[], noeuds: Record<string, string>): { recu: string; ou: string } {
  const d = destinataires(ls)
  const admins = [...new Set(d.map((x) => x.administration))]
  const admin = admins.length === 1 && admins[0] !== 'Plusieurs' ? LIBELLE_ADMINISTRATION[admins[0]] : null
  const noms = d.map((x) => `${x.nom}${x.part !== undefined ? ` ${pct(x.part * 100, x.part < 0.01 ? 1 : 0)}` : ''}`).join(', ')
  const recu = `${h(noms)}${admin && !d.some((x) => x.nom.includes(admin)) ? ` <span class="badge badge-admin">${h(admin)}</span>` : ''}${
    ls.some((l) => l.statut_affectation === 'non sourcee') ? ' · répartition non sourcée' : ''
  }`
  const liens: Lien[] = []
  const sans: Destinataire_[] = []
  // Ligne partagée entre plusieurs caisses (CSG) : un lien par caisse, sans les pages thématiques voisines.
  for (const x of d) {
    const pages = pagesDe(x.id, x.administration, noeuds, d.length === 1)
    if (!pages.length && x.id in SANS_PAGE) sans.push(x)
    for (const l of pages) if (!liens.some((y) => y.href === l.href)) liens.push(l)
  }
  const voisines = sans.map((x) => SANS_PAGE[x.id]).filter((l): l is Lien => !!l && existe(l.href))
  const phrases = [
    ...(liens.length ? [ancres(liens)] : []),
    ...(sans.length
      ? [`les comptes de ${sans.length > 1 ? 'ces organismes' : 'cet organisme'} ne sont pas dans les données du site${voisines.length ? `, voir aussi ${ancres(voisines)}` : ''}`]
      : []),
  ]
  return { recu, ou: phrases.join(' ; ') || 'pas de page du site sur ce destinataire' }
}

// ---------------------------------------------------------------------------------------------------------------
// La fiche d'une personne : lignes du moteur, net imposable et prélèvement à la source au taux du foyer.
// ---------------------------------------------------------------------------------------------------------------

interface TauxFoyer {
  taux: number
  /** impôt du foyer calculé par le moteur et revenus nets imposables qui servent de base au taux */
  impot: number
  base: number
}
export interface Fiche {
  role: Role
  brut: number
  net: number
  imposable: number
  lignes: Prelevement[]
  cotisations: number
  csgCrds: number
  patronal: Fourchette
  pas: TauxFoyer | null
  /** raison de l'absence du prélèvement à la source */
  sansPas?: string
  personne: Personne | null
}

const personnesAvecFiche = (r: ResultatOk) => (r.entree.personnes as PersonneCalculee[]).filter((p) => !p.profil || AVEC_FICHE.has(p.profil))

function imposableDe(r: ResultatOk, p: PersonneCalculee): number {
  if (typeof p.revenu_imposable_annuel === 'number') return p.revenu_imposable_annuel
  // Contrat 1.0 : net imposable = net avant impôt + CSG non déductible + CRDS (sans mutuelle d'entreprise, non comptée).
  return p.salaire_net_avant_impot_annuel + central(r.prelevements.filter((l) => l.personne === p.role && ['csg_non_deductible', 'crds'].includes(cle(l.id))))
}

function tauxFoyer(r: ResultatOk, p: PersonneCalculee): { pas: TauxFoyer | null; raison?: string } {
  const unionLibre = r.prelevements.some((l) => l.id === 'impot_revenu_declarant2' && l.famille === 'impot_revenu')
  const id = unionLibre && p.role === 'declarant2' ? 'impot_revenu_declarant2' : 'impot_revenu'
  const ir = r.prelevements.find((l) => l.id === id && l.famille === 'impot_revenu')
  const membres = unionLibre ? [p] : (r.entree.personnes as PersonneCalculee[])
  if (!ir) return { pas: null, raison: 'l’impôt sur le revenu du foyer n’est pas dans le calcul' }
  if (membres.some((m) => m.profil && !DANS_LE_TAUX.has(m.profil)))
    return { pas: null, raison: 'le taux de ton foyer dépend aussi de revenus d’indépendant, que le site ne ramène pas à une base comparable' }
  const base = membres.reduce((s, m) => s + imposableDe(r, m), 0)
  if (base <= 0) return { pas: null, raison: 'le foyer n’a pas de revenu imposable' }
  // Taux personnalisé du foyer : impôt ÷ revenus nets imposables, arrondi au dixième de point comme celui de l'administration.
  return { pas: { taux: Math.round((ir.montant_annuel_eur.central / base) * 1000) / 1000, impot: ir.montant_annuel_eur.central, base } }
}

export function fichesDe(r: ResultatOk, profil: Profil | null): Fiche[] {
  return personnesAvecFiche(r).map((p) => {
    const lignes = r.prelevements.filter((l) => l.personne === p.role && FAMILLES_FICHE.has(l.famille))
    const t = tauxFoyer(r, p)
    return {
      role: p.role,
      brut: p.salaire_brut_annuel_estime.central,
      net: p.salaire_net_avant_impot_annuel,
      imposable: imposableDe(r, p),
      lignes,
      cotisations: central(lignes.filter((l) => l.famille === 'cotisation_salariale')),
      csgCrds: central(lignes.filter((l) => l.famille === 'csg_crds')),
      patronal: additionner(lignes.filter(patronale)),
      pas: t.pas,
      ...(t.raison ? { sansPas: t.raison } : {}),
      personne: profil?.personnes.find((x) => x.role === p.role) ?? null,
    }
  })
}

/** Prélèvement à la source de l'année : taux du foyer appliqué au net imposable de la personne. */
export const montantPas = (f: Fiche) => (f.pas ? Math.round(f.pas.taux * f.imposable * 100) / 100 : 0)

// ---------------------------------------------------------------------------------------------------------------
// Affichage
// ---------------------------------------------------------------------------------------------------------------

/** Montant d'une période : « 186 € », « 12 à 108 € » pour une fourchette, « − 45 € » pour une réduction. */
function texte(f: Fourchette, d: number): string {
  const negatif = f.haut < 0 || (f.central < 0 && f.bas <= 0)
  const g = negatif ? { bas: -f.haut, central: -f.central, haut: -f.bas } : f
  // « + 0 » : un zéro négatif (réduction nulle dans un scénario) s'écrirait « -0 ».
  const b = Math.round(g.bas / d) + 0
  const hh = Math.round(g.haut / d) + 0
  const t = b === hh ? eur(g.central / d) : `${entier(b)} à ${eur(hh)}`
  return negatif ? `− ${t}` : t
}
/** Somme d'un groupe de lignes, réductions déduites (sans plancher : une réduction seule reste négative). */
function somme(ls: Prelevement[]): Fourchette | null {
  const utiles = ls.filter((l) => !l.non_chiffre)
  if (!utiles.length) return null
  const t = { bas: 0, central: 0, haut: 0 }
  for (const l of utiles) {
    const m = l.montant_annuel_eur
    if (l.nature === 'reduction') {
      t.bas -= m.haut
      t.central -= m.central
      t.haut -= m.bas
    } else {
      t.bas += m.bas
      t.central += m.central
      t.haut += m.haut
    }
  }
  return t
}
const estPlage = (f: Fourchette | null, d: number) => !!f && Math.round(f.bas / d) !== Math.round(f.haut / d)
const totalEmployeur = (f: Fiche): Fourchette => ({ bas: f.brut + f.patronal.bas, central: f.brut + f.patronal.central, haut: f.brut + f.patronal.haut })

const SUFFIXE: Record<Periode, string> = { mois: ' par mois', an: ' par an' }
const cache = (p: Periode) => `<span class="visuellement-cache">${SUFFIXE[p]}</span>`
const approche = () => `${traitStatut('approche')}<strong>${STATUTS.approche.libelle}</strong> · dépend de ton entreprise (voir plus bas) · `

interface Vue {
  fiche: Fiche
  periode: Periode
  annee: number
  noeuds: Record<string, string>
  exemple: boolean
}
interface Groupe {
  modele: LigneCalculee | LigneHorsCalcul
  moteur: Prelevement[]
}

/** Rubriques obligatoires présentes dans la fiche, et lignes du moteur restées sans place dans le modèle. */
function rubriquesDe(f: Fiche): { rubriques: { titre: string; note?: string; groupes: Groupe[] }[]; restes: Prelevement[] } {
  const prises = new Set<Prelevement>()
  const rubriques = OBLIGATOIRES.map((r) => ({
    titre: r.titre,
    note: r.note,
    groupes: r.lignes
      .map((l) => {
        const moteur = estCalculee(l) ? f.lignes.filter((x) => l.ids.includes(cle(x.id))) : []
        moteur.forEach((x) => prises.add(x))
        return { modele: l, moteur }
      })
      .filter((g) => !estCalculee(g.modele) || g.moteur.length > 0),
  })).filter((r) => r.groupes.length > 0)
  return { rubriques, restes: f.lignes.filter((x) => !prises.has(x)) }
}

function liCalculee(libelle: string, moteur: Prelevement[], explication: string, v: Vue): string {
  const d = v.periode === 'mois' ? 12 : 1
  const sal = somme(moteur.filter((l) => !patronale(l)))
  const emp = somme(moteur.filter(patronale))
  const reduction = moteur.every((l) => l.nature === 'reduction')
  const parts = [
    sal ? `<span class="aide">ta part</span> ${h(texte(sal, d))}${cache(v.periode)}` : '',
    emp ? `<span class="aide">employeur</span> ${h(texte(emp, d))}${cache(v.periode)}` : '',
  ].filter(Boolean)
  const { recu, ou } = recuPar(moteur, v.noeuds)
  const notes = moteur.map((l) => l.note).filter(Boolean)
  return `<li data-ligne="moteur"${reduction ? ' class="reduction"' : ''}>
    <span>${h(libelle)}</span>
    <span class="montant">${parts.join('<br />')}</span>
    <span class="dest">${estPlage(sal, d) || estPlage(emp, d) ? approche() : ''}${h(explication)}<br />${reduction ? 'Diminue ce que reçoit' : 'Reçu par'} : ${recu}.<br />${
      reduction ? 'Où ce montant est suivi : <a href="#/explorer/niches">les exonérations de cotisations sociales, mesure par mesure</a>' : `Où va cet argent : ${ou}`
    }.${notes.length ? `<br />${h(notes.join(' '))}` : ''}</span>
  </li>`
}

function liHorsCalcul(l: LigneHorsCalcul): string {
  return `<li>
    <span>${h(l.libelle)}</span>
    <span class="montant">non calculé</span>
    <span class="dest">${h(l.explication)}${l.recu ? `<br />Reçu par : ${h(l.recu)}.` : ''}${
      l.lien && existe(l.lien.href) ? `<br />Où va cet argent : ${ancres([l.lien])}.` : ''
    }</span>
  </li>`
}

/** Ligne à un seul montant (brut, net, total) : l'explication est déjà échappée. */
function liMontant(libelle: string, montant: string, explication: string, p: Periode, plage = false): string {
  return `<li><span>${h(libelle)}</span><span class="montant">${h(montant)}${cache(p)}</span><span class="dest">${plage ? approche() : ''}${explication}</span></li>`
}

function liTotal(f: Fiche, v: Vue): string {
  const d = v.periode === 'mois' ? 12 : 1
  return `<li>
    <span>Total des cotisations et contributions</span>
    <span class="montant"><span class="aide">ta part</span> ${h(eur((f.cotisations + f.csgCrds) / d))}${cache(v.periode)}<br /><span class="aide">employeur</span> ${h(texte(f.patronal, d))}${cache(v.periode)}</span>
    <span class="dest">${estPlage(f.patronal, d) ? approche() : ''}${h('Somme des lignes ci-dessus : ce qui est prélevé sur ton brut (ta part) et ce que ton employeur verse en plus (sa part), réduction générale déduite.')}</span>
  </li>`
}

function lignesImpot(v: Vue): string[] {
  const f = v.fiche
  const d = v.periode === 'mois' ? 12 : 1
  const attendu = f.net + central(f.lignes.filter((l) => ['csg_non_deductible', 'crds'].includes(cle(l.id))))
  const imposable = liMontant(
    'Montant net imposable',
    eur(f.imposable / d),
    h(
      Math.abs(attendu - f.imposable) <= 1
        ? 'Base du prélèvement à la source : ton net avant impôt plus la CSG non déductible et la CRDS (et, sur une vraie fiche, la part de ta mutuelle payée par l’employeur).'
        : 'Base du prélèvement à la source, telle que le moteur du site la calcule pour ton profil.',
    ),
    v.periode,
  )
  if (!f.pas)
    return [
      imposable,
      liHorsCalcul({
        libelle: 'Impôt sur le revenu prélevé à la source',
        explication: `Ton employeur retient chaque mois ton impôt sur le revenu au taux transmis par l’administration fiscale ; le site ne le calcule pas ici : ${f.sansPas ?? 'donnée absente'}.`,
      }),
    ]
  const p = f.pas
  const pas = montantPas(f)
  const ecart = Math.round(pas - (p.impot * f.imposable) / p.base)
  return [
    imposable,
    `<li><span>Impôt sur le revenu prélevé à la source</span><span class="montant">${h(pas > 0 ? `− ${eur(pas / d)}` : eur(0))}${cache(v.periode)}</span><span class="dest">${h(
      `Taux de ${pct(p.taux * 100, 1)} appliqué à ton montant net imposable. Ton employeur retient chaque mois ton impôt au taux que lui transmet l’administration fiscale d’après ta dernière déclaration, puis le reverse à l’État ; le site applique le taux qui correspond à l’impôt calculé sur tes revenus ${v.annee}.`,
    )}<br />Reçu par : État (administration fiscale).<br />Où va cet argent : ${ancres(pagesDe('etat', 'Etat', v.noeuds))}.<br />${h(
      `Taux du foyer : impôt calculé de ${eur(p.impot)} pour ${eur(p.base)} de revenus nets imposables, arrondi au dixième de point comme le fait l’administration${
        ecart ? ` ; sur l’année, cet arrondi donne un écart de ${eur(Math.abs(ecart))} avec l’impôt calculé, régularisé l’année suivante` : ''
      }. Avec un taux individualisé ou le taux non personnalisé, le montant diffère.`,
    )}</span></li>`,
  ]
}

/** Les rubriques de la fiche, ligne par ligne, du brut au total versé par l'employeur. */
function lignesFiche(v: Vue): string {
  const f = v.fiche
  const d = v.periode === 'mois' ? 12 : 1
  const { rubriques, restes } = rubriquesDe(f)
  const bloc = (titre: string, items: string[], note?: string) => `<h3>${h(titre)}</h3><ul class="lignes">${items.join('')}</ul>${note ? `<p class="aide">${h(note)}</p>` : ''}`
  const groupe = (g: Groupe) => {
    if (!estCalculee(g.modele)) return liHorsCalcul(g.modele)
    const e = g.modele.explication
    return liCalculee(g.modele.libelle, g.moteur, typeof e === 'function' ? e({ lignes: g.moteur, brut: f.brut, annee: v.annee }) : e, v)
  }
  const pas = montantPas(f)
  const total = totalEmployeur(f)
  return [
    bloc('Montant brut', [
      liMontant('Montant brut', eur(f.brut / d), h(`Ton salaire avant toute retenue, base de la plupart des cotisations ; le site le retrouve à partir ${v.exemple ? 'du net avant impôt de l’exemple' : 'de ton net avant impôt'}.`), v.periode),
    ]),
    ...rubriques.map((r) => bloc(r.titre, r.groupes.map(groupe), r.note)),
    restes.length ? bloc('Autres lignes du calcul', restes.map((l) => liCalculee(l.libelle, [l], EXPLICATION_REPLI[l.famille] ?? EXPLICATION_REPLI.cotisation_salariale, v))) : '',
    bloc('Total des cotisations et contributions', [liTotal(f, v)]),
    bloc(FACULTATIVES.titre, FACULTATIVES.lignes.map((l) => liHorsCalcul(l as LigneHorsCalcul))),
    bloc('Montants nets avant impôt', [
      liHorsCalcul({
        libelle: 'Montant net social',
        explication: 'Montant à déclarer pour demander la prime d’activité ou le revenu de solidarité active (RSA) ; il dépend d’éléments propres à ton contrat (complémentaire santé, prévoyance, avantages en nature) que le site ne connaît pas.',
      }),
      liHorsCalcul({
        libelle: 'Remboursements et déductions diverses',
        explication: 'Remboursement d’au moins la moitié de ton abonnement de transport en commun, titres-restaurant, chèques-vacances : ces lignes dépendent de ton entreprise.',
      }),
      liMontant(
        'Montant net à payer avant impôt sur le revenu',
        eur(f.net / d),
        h(`Ce qui reste du salaire brut après les cotisations, la CSG et la CRDS ; c’est ${v.exemple ? 'le montant de l’exemple' : 'le montant que tu as saisi'}.`),
        v.periode,
      ),
    ]),
    bloc('Impôt sur le revenu', lignesImpot(v)),
    bloc('Montant net à payer', [
      liMontant('Montant net à payer', eur((f.net - pas) / d), h('Ce qui arrive sur ton compte : le net avant impôt moins le prélèvement à la source, hors primes, absences et remboursements.'), v.periode),
    ]),
    bloc('Total versé par l’employeur', [
      liMontant('Total versé par l’employeur', texte(total, d), h('Ton salaire brut plus les cotisations patronales : ce que ton employeur verse en tout pour ton emploi.'), v.periode, estPlage(total, d)),
    ]),
  ].join('')
}

/** Version tableau : la fiche telle qu'elle se lit, part salarié et part employeur en colonnes. */
function tableau(v: Vue): string {
  const f = v.fiche
  const d = v.periode === 'mois' ? 12 : 1
  const { rubriques, restes } = rubriquesDe(f)
  const ligne = (libelle: string, sal: string, emp: string) => `<tr><th scope="row">${h(libelle)}</th><td class="nombre">${h(sal)}</td><td class="nombre">${h(emp)}</td></tr>`
  const seule = (libelle: string, val: string) => `<tr><th scope="row">${h(libelle)}</th><td class="nombre" colspan="2">${h(val)}</td></tr>`
  const groupe = (titre: string, lignes: string[]) => `<tbody><tr><th scope="rowgroup" colspan="3">${h(titre)}</th></tr>${lignes.join('')}</tbody>`
  const parts = (moteur: Prelevement[]): [string, string] => {
    const sal = somme(moteur.filter((x) => !patronale(x)))
    const emp = somme(moteur.filter(patronale))
    return [sal ? texte(sal, d) : '–', emp ? texte(emp, d) : '–']
  }
  const pas = montantPas(f)
  const corps = [
    groupe('Montant brut', [seule('Montant brut', eur(f.brut / d))]),
    ...rubriques.map((r) => groupe(r.titre, r.groupes.map((g) => (estCalculee(g.modele) ? ligne(g.modele.libelle, ...parts(g.moteur)) : ligne(g.modele.libelle, 'non calculé', 'non calculé'))))),
    ...(restes.length ? [groupe('Autres lignes du calcul', restes.map((l) => ligne(l.libelle, ...parts([l]))))] : []),
    groupe(FACULTATIVES.titre, FACULTATIVES.lignes.map((l) => ligne(l.libelle, 'non calculé', 'non calculé'))),
    groupe('Totaux et montants nets', [
      ligne('Total des cotisations et contributions', eur((f.cotisations + f.csgCrds) / d), texte(f.patronal, d)),
      seule('Montant net à payer avant impôt sur le revenu', eur(f.net / d)),
      seule('Montant net imposable', eur(f.imposable / d)),
      seule(`Impôt sur le revenu prélevé à la source${f.pas ? ` (taux ${pct(f.pas.taux * 100, 1)})` : ''}`, f.pas ? (pas > 0 ? `− ${eur(pas / d)}` : eur(0)) : 'non calculé'),
      seule('Montant net à payer', eur((f.net - pas) / d)),
      seule('Total versé par l’employeur', texte(totalEmployeur(f), d)),
    ]),
  ]
  return `<details><summary>Lire ta fiche en tableau</summary><div class="tableau-defile"><table>
<caption>Ta fiche de paie ${v.periode === 'mois' ? 'par mois' : 'sur un an'}, en euros arrondis, revenus ${h(v.annee)}</caption>
<thead><tr><th scope="col">Ligne</th><th scope="col" class="nombre">Part salarié</th><th scope="col" class="nombre">Part employeur</th></tr></thead>
${corps.join('')}</table></div></details>`
}

/** Carte du chiffre clé : montant net à payer, du brut au net, et « sur 100 € de salaire brut ». */
function recap(v: Vue, r: ResultatOk): string {
  const f = v.fiche
  const d = v.periode === 'mois' ? 12 : 1
  const pas = montantPas(f)
  const parts = sur100Entiers({ cotisations: f.cotisations, csg: f.csgCrds, ...(f.pas ? { impot: pas } : {}), verse: f.net - pas })
  const periode = v.periode === 'mois' ? 'par mois' : 'sur un an'
  return `<section class="recap" data-cle aria-labelledby="titre-bulletin-net">
  <p id="titre-bulletin-net" class="recap-titre">Montant net à payer, ${periode}${f.pas ? '' : ', avant impôt sur le revenu'}</p>
  <p class="grand-chiffre">${surligne(eur((f.net - pas) / d))}</p>
  <ul class="recap-lignes">
    <li><span>Montant brut</span><span>${h(eur(f.brut / d))}</span></li>
    <li><span>Cotisations, CSG et CRDS (ta part)</span><span>− ${h(eur((f.cotisations + f.csgCrds) / d))}</span></li>
    <li><span>Net à payer avant impôt sur le revenu</span><span>${h(eur(f.net / d))}</span></li>
    ${f.pas ? `<li><span>Impôt prélevé à la source (taux ${h(pct(f.pas.taux * 100, 1))})</span><span>${pas > 0 ? '− ' : ''}${h(eur(pas / d))}</span></li>` : ''}
  </ul>
  <p class="recap-sur100">Sur 100 € de salaire brut : ${h(String(parts.cotisations))} € de cotisations sociales, ${h(String(parts.csg))} € de CSG et de CRDS${
    f.pas ? `, ${h(String(parts.impot))} € d’impôt sur le revenu prélevé à la source` : ''
  }, et ${h(String(parts.verse))} € te sont versés.</p>
  <p class="aide">Ton employeur verse en plus ${h(texte(f.patronal, d))} de cotisations patronales${estPlage(f.patronal, d) ? ' selon ton entreprise' : ''} : total versé par l’employeur ${h(texte(totalEmployeur(f), d))} ${periode}. Montants arrondis à l’euro : la somme des lignes peut différer d’un euro.</p>
  ${source(`calcul sur ton appareil avec modele-social ${r.moteur.version} (règles de l’Urssaf, licence MIT) et publicodes ${r.moteur.publicodes ?? ''}, législation ${r.annee_legislation}`, `revenus ${r.annee_legislation}`)}
</section>`
}

/** Ce qui dépend de l'entreprise : signalé avec la fourchette du site, ou « non calculé ». */
function variable(v: Vue): string {
  const f = v.fiche
  const d = v.periode === 'mois' ? 12 : 1
  const atmp = somme(f.lignes.filter((l) => cle(l.id) === 'atmp'))
  const hypothese = f.lignes.find((l) => patronale(l) && l.hypothese_fourchette)?.hypothese_fourchette
  const prive = !f.personne || ['salarie_prive', 'apprenti'].includes(f.personne.statut_activite)
  const item = (motif: string, titre: string, phrase: string) => `<li><span class="motif ${motif}" aria-hidden="true"></span><span><strong>${h(titre)}</strong> ${h(phrase)}</span></li>`
  return `<p>Le site ne connaît pas ton employeur : ces lignes sont signalées par une fourchette ou par « non calculé », jamais par un montant inventé.</p>
<ul class="limites">
  ${item(
    'motif-approche',
    'Taux accidents du travail.',
    `Il est fixé chaque année pour ton établissement, selon son secteur d’activité et, à partir de 20 salariés, ses accidents passés${
      atmp ? ` : la cotisation va ici de ${texte(atmp, d)} ${v.periode === 'mois' ? 'par mois' : 'sur un an'}, selon le taux retenu` : ''
    }.`,
  )}
  ${item('motif-vide', 'Mutuelle (complémentaire santé).', 'Son montant et la part payée par ton employeur dépendent du contrat de ton entreprise : non calculée.')}
  ${item('motif-vide', 'Prévoyance.', 'Prévue par ta convention collective ou un accord d’entreprise, obligatoire pour les cadres : non calculée.')}
  ${
    prive
      ? item(
          'motif-vide',
          'Retraite complémentaire selon ton statut.',
          `Cadre ou non, les taux Agirc-Arrco sont les mêmes depuis 2019 ; le site applique la répartition de droit commun (60 % pour l’employeur, 40 % pour le salarié), que certaines entreprises aménagent. ${
            f.personne?.cadre
              ? 'Tu as indiqué le statut cadre : la cotisation Apec est comptée, la prévoyance des cadres payée par l’employeur ne l’est pas.'
              : 'Pour un cadre, la fiche porte en plus l’Apec et une prévoyance des cadres payée par l’employeur.'
          }`,
        )
      : ''
  }
  ${item('motif-approche', 'Taille et lieu de l’entreprise.', 'Versement mobilité, fonds d’aide au logement, formation professionnelle et réduction générale changent avec l’effectif et la commune de l’établissement : le site montre une fourchette.')}
  ${item('motif-vide', 'Éléments propres à ton contrat.', 'Primes, heures supplémentaires, absences, titres-restaurant, remboursement des transports, avantages en nature : absents de ce calcul.')}
</ul>
${hypothese ? `<details><summary>Hypothèses des fourchettes</summary><p class="aide">${h(hypothese.replace(/AT-MP/g, 'accidents du travail'))}</p></details>` : ''}`
}

// ---------------------------------------------------------------------------------------------------------------
// Écran
// ---------------------------------------------------------------------------------------------------------------

/** Profil de l'exemple de l'accueil : salaire net et commune de src/exemple-lyon.json, situation par défaut de la saisie. */
export const PROFIL_EXEMPLE: Profil = {
  version_contrat: '1.0',
  annee_revenus: 2025,
  residence: { zone: 'metropole', alsace_moselle: false, commune_insee: exemple.profil.insee },
  foyer: { situation: 'celibataire', enfants: [] },
  logement: { statut: 'locataire' },
  personnes: [{ role: 'declarant1', statut_activite: 'salarie_prive', frontalier: false, cadre: false, temps_travail: { type: 'temps_plein' }, salaire_net_avant_impot_mensuel: exemple.profil.net_mensuel }],
}

let calculExemple: Promise<ResultatOk | null> | null = null
/** Fiche de l'exemple, calculée une fois par visite sur l'appareil (Web Worker, ou fil principal à défaut). */
function exempleCalcule(affectation: Affectation | null): Promise<ResultatOk | null> {
  calculExemple ??= import('../calcul/hors-fil')
    .then((m) => m.calculerHorsFil(PROFIL_EXEMPLE, { affectation }))
    .then((r) => (r.statut === 'ok' ? r : null))
    .catch(() => null)
    .then((r) => {
      if (!r) calculExemple = null
      return r
    })
  return calculExemple
}

function origine(r: ResultatOk | null, profil: Profil | null): string {
  if (!r) {
    return `Exemple du site : ${h(`${entier(exemple.profil.net_mensuel)} €`)} net avant impôt par mois, salarié·e du privé non cadre à temps plein, seul·e sans enfant, revenus ${h(
      PROFIL_EXEMPLE.annee_revenus,
    )}. <a href="#/calcul">Calculer ma propre fiche</a>`
  }
  const nets = personnesAvecFiche(r).map((p) => eur(p.salaire_net_avant_impot_annuel / 12))
  const p1 = profil?.personnes.find((x) => AVEC_FICHE.has(x.statut_activite))
  const precisions =
    nets.length === 1 && p1 ? [p1.cadre ? 'cadre' : '', p1.temps_travail?.type === 'temps_partiel' ? `temps partiel à ${pct(p1.temps_travail.quotite * 100, 0)}` : ''].filter(Boolean) : []
  return `Calculée pour ta saisie : ${h(nets.join(' et '))} net avant impôt par mois${precisions.length ? `, ${h(precisions.join(', '))}` : ''}, revenus ${h(r.annee_legislation)}. <a href="#/calcul">Modifier ma saisie</a>`
}

const NOMS: Record<Role, string> = { declarant1: 'Toi', declarant2: 'Ton ou ta conjoint·e' }

export function rendre(cible: HTMLElement): Rendu {
  const r0 = session.resultat
  const saisie = r0 && personnesAvecFiche(r0).length ? r0 : null
  const annuel = session.resultat ? '#/calcul/resultat' : '#/calcul'
  cible.innerHTML = `
<h1>Ta fiche de paie expliquée</h1>
${retourResultat()}
<p class="chapeau">Chaque ligne d’une fiche de paie, rangée comme sur le modèle officiel : son montant, ce qu’elle finance, qui la reçoit et où va cet argent. Ce qui dépend de ton entreprise (mutuelle, prévoyance, taux d’accidents du travail) est signalé, pas inventé ; tes primes, absences et remboursements n’y sont pas.</p>
<p class="aide">${origine(saisie, saisie ? session.profil : null)}</p>
${r0 && !saisie ? '<p class="avertissement">Ta saisie ne comporte pas de salaire, et une pension ou un revenu d’indépendant n’a pas de fiche de paie : voici celle de l’exemple du site.</p>' : ''}
<div id="bulletin-reglages"></div>
<div id="bulletin-zone"><p class="chargement">Calcul de la fiche de paie sur ton appareil…</p></div>
<h2>Ce qui dépend de ton entreprise</h2>
<div id="bulletin-variable"></div>
<h2>Ce qui n’est pas sur ta fiche de paie</h2>
<p>La TVA et les autres taxes sur ta consommation, la taxe foncière et la taxe d’enlèvement des ordures ménagères ne passent pas par ta fiche de paie : <a href="${annuel}">ce que tu verses en un an</a> les ajoute.</p>
<h2>Et maintenant ?</h2>
<ul class="cartes par-3">
  <li><a href="#/explorer/secu"><strong>La Sécurité sociale</strong><span>Retraites, santé, famille, chômage : les dépenses des caisses qui reçoivent les cotisations.</span></a></li>
  <li><a href="#/explorer/etat"><strong>Le budget de l’État</strong><span>Où va l’impôt sur le revenu, sur 100 € dépensés.</span></a></li>
  <li><a href="${annuel}"><strong>Ce que tu verses en un an</strong><span>Fiche de paie, taxes sur ta consommation et impôts locaux, avec qui reçoit chaque euro.</span></a></li>
</ul>`
  return { suite: completer(cible, saisie) }
}

async function completer(cible: HTMLElement, saisie: ResultatOk | null): Promise<void> {
  const zone = cible.querySelector<HTMLElement>('#bulletin-zone')!
  const [affectation, secu] = await Promise.all([
    chargerSiPresent<Affectation>('prelevements/affectation.json'),
    chargerSiPresent<{ liens_affectation?: { noeuds?: Record<string, string> } }>('secu/index.json'),
  ])
  enregistrerDestinataires(affectation?.destinataires)
  const r = saisie ?? (await exempleCalcule(affectation))
  if (!r) {
    zone.innerHTML = '<p class="avertissement">La fiche n’a pas pu être calculée sur cet appareil. <a href="#/calcul">Saisir mon salaire</a> relance le calcul.</p>'
    return
  }
  const fiches = fichesDe(r, saisie ? session.profil : PROFIL_EXEMPLE)
  const etat = { periode: 'mois' as Periode, personne: 0 }
  const reglages = cible.querySelector<HTMLElement>('#bulletin-reglages')!
  const bascule = (nom: string, etiquette: string, options: [string, string][]) =>
    `<div class="bascule" role="group" aria-label="${h(etiquette)}">${options.map(([valeur, t]) => `<button type="button" data-${nom}="${h(valeur)}" aria-pressed="false">${h(t)}</button>`).join('')}</div>`
  reglages.innerHTML = `${fiches.length > 1 ? bascule('personne', 'Fiche de paie de', fiches.map((x, i) => [String(i), NOMS[x.role]])) : ''}${bascule('periode', 'Période des montants', [
    ['mois', 'Par mois'],
    ['an', 'Sur un an'],
  ])}`
  const sources = `${affectation?.source ? source(`destinataires : ${affectation.source}`, affectation.millesime) : ''}${source(
    'rubriques : modèle de bulletin de paie de l’arrêté du 31 janvier 2023 (salariés du privé)',
  )}`
  const dessiner = () => {
    const v: Vue = { fiche: fiches[etat.personne], periode: etat.periode, annee: r.annee_legislation, noeuds: secu?.liens_affectation?.noeuds ?? {}, exemple: !saisie }
    zone.innerHTML = `${recap(v, r)}
<h2>Ta fiche, ligne par ligne</h2>
<p class="aide">Ton employeur verse la plupart de ces montants à l’Urssaf, qui les répartit entre les caisses nommées ici ; la retraite complémentaire va à l’Agirc-Arrco et l’impôt prélevé à la source à l’administration fiscale.</p>
${lignesFiche(v)}
${tableau(v)}
${sources}`
    cible.querySelector<HTMLElement>('#bulletin-variable')!.innerHTML = variable(v)
    reglages.querySelectorAll<HTMLButtonElement>('button').forEach((b) =>
      b.setAttribute('aria-pressed', String(b.dataset.periode ? b.dataset.periode === etat.periode : b.dataset.personne === String(etat.personne))),
    )
    rendreDefilables(zone)
  }
  reglages.addEventListener('click', (e) => {
    const b = (e.target as HTMLElement).closest<HTMLButtonElement>('button')
    if (!b) return
    if (b.dataset.periode) etat.periode = b.dataset.periode as Periode
    else if (b.dataset.personne) etat.personne = Number(b.dataset.personne)
    dessiner()
    annoncer(b.dataset.periode ? (etat.periode === 'mois' ? 'Montants par mois' : 'Montants sur un an') : `Fiche de paie : ${NOMS[fiches[etat.personne].role]}`)
  })
  dessiner()
}

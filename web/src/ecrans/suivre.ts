// Suivre un euro : un parcours pas à pas, de ce que tu verses jusqu'au dernier niveau publié.
// Étape 1 : la répartition légale du prélèvement (prelevements/affectation.json). Puis les comptes de l'organisme qui le reçoit :
// Sécurité sociale (secu/arbre, liens_affectation de secu/index.json), budget de l'État (arbre/ puis tracabilite/),
// collectivités locales (arbre_administrations/). La piste s'arrête là où plus rien n'est publié, et la page le dit.
// Mouvement seulement après un choix de la personne (jauge et défilement), coupé sous prefers-reduced-motion.
import { filPiste, type MaillonPiste } from '../composants/fil-euro'
import { statutPart } from '../composants/tracabilite'
import { retourResultat } from '../composants/retour-resultat'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { annoncer, badgeStatut, h, legendeStatuts, libelle, md, STATUTS, sur100, type Statut } from '../util'
import { enCours } from './dette'

// ---------- Données lues ----------
interface Ventilation {
  destinataire: string
  part: number
  source?: string
}
interface Affectation {
  millesime: string
  source: string
  methode?: string
  destinataires: Record<string, { nom: string; administration?: string }>
  prelevements: Record<string, { libelle: string; statut: string; ventilation?: Ventilation[]; reference_juridique?: string }>
  correspondance_calcul?: Record<string, string>
}
interface NoeudSecu {
  id: string
  nom: string
  md: number
  enfants?: NoeudSecu[]
  mode?: string
  tracabilite_pct?: number
  sources?: string[]
  note?: string
  ref?: string
  ecarts?: { source: string; md: number | null; libelle: string }[]
}
type RacineSecu = NoeudSecu & { millesime: string; source: string; sources_detail?: Record<string, { titre: string; url?: string }> }
interface IndexSecu {
  liens_affectation?: {
    noeuds: Record<string, string>
    sans_noeud?: Record<string, { motif: string; noeud_englobant: string | null }>
  }
}
interface NoeudSimple {
  id: string
  nom: string
  md: number
  niveau?: string
  enfants?: NoeudSimple[]
}
type RacineSimple = NoeudSimple & { millesime: string; source: string }
interface PartTrac {
  libelle: string
  pct: number
  statut?: string
  ecart_millesime_ans?: number
}
interface FichierTrac {
  millesime: string
  source: string
  libelle?: string
  parts: Record<string, PartTrac>
}

// ---------- Modèle du parcours ----------
/** Une piste possible à une étape : part de l'étape (fraction, négative pour une ligne en déduction). */
interface Option {
  cle: string
  nom: string
  part: number
  statut: Statut
  detail?: string
  suite?: () => Promise<Niveau>
}
/** Une étape : soit des pistes à choisir, soit la fin de la piste. */
interface Niveau {
  titre: string
  millesime: string
  source: string
  note?: string
  options: Option[]
  fin?: { statut?: Statut; texte: string; liens?: { href: string; texte: string }[]; alternative?: Option }
}

const ORDRE_TRAC = ['beneficiaire_identifie', 'nominatif_par_choix', 'anonyme_par_nature', 'non_publie']

/** Noms courts des prélèvements de départ, sans sigle seul. */
const COURTS: Record<string, string> = {
  csg_activite: 'Contribution sociale généralisée (CSG)',
  crds: 'Remboursement de la dette sociale (CRDS)',
  impot_revenu: 'Impôt sur le revenu',
  vieillesse_plafonnee: 'Retraite de base, part plafonnée',
  vieillesse_deplafonnee: 'Retraite de base, part déplafonnée',
  agirc_arrco: 'Retraite complémentaire Agirc-Arrco',
  ceg: 'Contribution d’équilibre général (retraite complémentaire)',
  maladie: 'Cotisation maladie (employeur)',
  famille: 'Cotisation allocations familiales (employeur)',
  atmp: 'Cotisation accidents du travail (employeur)',
  chomage: 'Cotisation chômage (employeur)',
  fnal: 'Contribution au fonds d’aide au logement',
  csa: 'Contribution solidarité autonomie',
  tva: 'Taxe sur la valeur ajoutée (TVA)',
  ticpe: 'Taxe sur les carburants et l’énergie',
  tabac: 'Taxe sur le tabac',
  alcool: 'Taxes sur l’alcool',
  taxe_fonciere: 'Taxe foncière',
  teom: 'Taxe d’enlèvement des ordures ménagères',
}
const ACHATS = ['tva', 'ticpe', 'tabac', 'alcool']
const LOGEMENT = ['taxe_fonciere', 'teom']
const COLLECTIVITES = ['collectivites_territoriales', 'commune', 'epci', 'syndicats', 'region_idf', 'bloc_communal_dechets']
/** Destinataires que le budget de l'État retrace : nœud de l'arbre d'exécution. */
const NOEUDS_ETAT: Record<string, string> = { etat: 'racine', audiovisuel_public: "Culture et medias/Avances à l'audiovisuel public" }
/** Prélèvements sur recettes : leur traçabilité est publiée à part (tracabilite/noeud_psr_*.json). */
const PSR: Record<string, string> = {
  'Prelevements sur recettes/Collectivités territoriales': 'tracabilite/noeud_psr_collectivites.json',
  'Prelevements sur recettes/Union européenne': 'tracabilite/noeud_psr_union_europeenne.json',
}

/** Libellés sans sigle seul ni abréviation : « ONDAM : », « n.c.a. », « R & D ». */
export function propre(x: string): string {
  const t = libelle(x)
    .replace(/^ONDAM : /, '')
    .replace(/\bn\.c\.a\./g, '(non classé ailleurs)')
    .replace(/R & D/g, 'Recherche et développement')
  return t.charAt(0).toUpperCase() + t.slice(1)
}

/** Montant suivi, sur 1 € ou sur 100 €. */
export function montant(x: number, base: 1 | 100): string {
  if (base === 100) return sur100(x * 100)
  const c = x * 100
  if (x >= 0.01) return `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(x)} €`
  if (c >= 0.01) return `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(c)} centime`
  return 'moins d’un centième de centime'
}

const annee = (m: string) => /(\d{4})/.exec(m)?.[1] ?? m

// ---------- Construction des étapes ----------
class Lecteur {
  constructor(public aff: Affectation) {}

  async secu() {
    const [index, racine] = await Promise.all([chargerSiPresent<IndexSecu>('secu/index.json'), chargerSiPresent<RacineSecu>('secu/arbre/racine.json')])
    return { index, racine }
  }

  depart(cle: string): Niveau {
    const p = this.aff.prelevements[cle]
    const base: Niveau = {
      titre: `${propre(COURTS[cle] ?? p.libelle)} : qui le reçoit`,
      millesime: this.aff.millesime,
      source: `Répartition ${this.aff.millesime} : ${this.aff.source}`,
      note: `${p.libelle}. La loi fixe qui reçoit ce prélèvement${p.reference_juridique ? ` (${p.reference_juridique})` : ''}.`,
      options: [],
    }
    if (p.statut !== 'sourcee' || !p.ventilation?.length) {
      base.fin = { statut: 'nonpub', texte: 'La répartition de ce prélèvement n’est pas publiée dans les documents réunis par le site : la piste s’arrête dès le départ.' }
      return base
    }
    base.options = p.ventilation
      .map((v) => ({
        cle: v.destinataire,
        nom: this.aff.destinataires[v.destinataire]?.nom ?? v.destinataire,
        part: v.part,
        statut: 'trace' as Statut,
        detail: v.source,
        suite: () => this.destinataire(v.destinataire),
      }))
      .sort((a, b) => b.part - a.part)
    return base
  }

  async destinataire(d: string): Promise<Niveau> {
    const nom = this.aff.destinataires[d]?.nom ?? d
    const { index, racine } = await this.secu()
    const noeud = index?.liens_affectation?.noeuds[d]
    if (noeud && racine) return this.secuNoeud(racine, noeud)
    const sans = index?.liens_affectation?.sans_noeud?.[d]
    if (sans) {
      const englobant = sans.noeud_englobant && racine ? trouver(racine, sans.noeud_englobant) : null
      return {
        titre: nom,
        millesime: racine?.millesime ?? '',
        source: racine?.source ?? 'secu/index.json',
        options: [],
        fin: {
          statut: 'nonpub',
          texte: sans.motif.replace(/ dans prelevements\/affectation\.json/, ' dans les documents réunis par le site'),
          alternative: englobant
            ? { cle: `~${englobant.id}`, nom: `Suivre plutôt l’ensemble : ${propre(englobant.nom)}`, part: 1, statut: 'approche', suite: () => Promise.resolve(this.secuNoeud(racine!, englobant.id)) }
            : undefined,
        },
      }
    }
    if (NOEUDS_ETAT[d]) return this.etat(NOEUDS_ETAT[d], d === 'etat' ? undefined : nom)
    if (COLLECTIVITES.includes(d)) return this.administrations('S1313', d === 'collectivites_territoriales' ? undefined : nom)
    return {
      titre: nom,
      millesime: this.aff.millesime,
      source: this.aff.source,
      options: [],
      fin: {
        texte: `La piste s’arrête ici dans ce site : les dépenses de cet organisme ne font pas encore partie des données réunies par le site. Elles peuvent être publiées ailleurs (rapport annuel, comptes de l’organisme) ; le site ne les estime pas.`,
      },
    }
  }

  secuNoeud(racine: RacineSecu, id: string): Niveau {
    const n = trouver(racine, id)
    const titres = (n?.sources ?? []).map((s) => racine.sources_detail?.[s]?.titre ?? s)
    const niveau: Niveau = {
      titre: n ? propre(n.nom) : id,
      millesime: racine.millesime,
      source: titres.length ? titres.join(' ; ') : racine.source,
      options: [],
    }
    if (!n) {
      niveau.fin = { texte: 'Ce poste est absent des comptes chargés : la piste s’arrête ici.' }
      return niveau
    }
    const notes: string[] = []
    if (n.note) notes.push(`Calcul : ${n.note}.`)
    for (const e of n.ecarts ?? [])
      notes.push(`Autre source : ${racine.sources_detail?.[e.source]?.titre ?? e.source}, ${e.libelle}${typeof e.md === 'number' ? ` : ${md(e.md)}` : ''} (écart montré, non tranché).`)
    if (notes.length) niveau.note = notes.join(' ')
    if (!n.enfants?.length) {
      niveau.fin = finSecu(n)
      return niveau
    }
    niveau.options = n.enfants
      .map((e) => ({
        cle: e.id,
        nom: propre(e.nom),
        part: n.md ? e.md / n.md : 0,
        statut: statutSecu(e),
        detail: e.note ? `Calcul : ${e.note}` : e.ref,
        suite: () => Promise.resolve(this.secuNoeud(racine, e.id)),
      }))
      .sort((a, b) => b.part - a.part)
    return niveau
  }

  async etat(id: string, via?: string): Promise<Niveau> {
    const racine = await chargerSiPresent<RacineSimple>('arbre/racine.json')
    if (!racine) return { titre: 'Budget de l’État', millesime: '', source: '', options: [], fin: { texte: 'Les comptes de l’État ne sont pas disponibles : la piste s’arrête ici.' } }
    const n = id === 'racine' ? racine : trouver(racine, id)
    const niveau: Niveau = { titre: n ? propre(n.nom) : id, millesime: racine.millesime, source: racine.source, options: [] }
    if (id === 'racine')
      niveau.note = 'Les recettes de l’État ne sont pas attribuées à une dépense précise (principe d’universalité budgétaire) : ton euro se fond dans le budget, et la piste suit la répartition des dépenses de l’année.'
    else if (via) niveau.note = `${via} : ces crédits sont retracés dans le budget de l’État.`
    if (!n) {
      niveau.fin = { texte: 'Ce poste est absent des comptes chargés : la piste s’arrête ici.' }
      return niveau
    }
    if (n.niveau === 'programme') return this.tracabilite(`tracabilite/programme_${/(\d{3})$/.exec(n.id)?.[1]}.json`, niveau, racine.millesime, /(\d{3})$/.exec(n.id)?.[1])
    if (PSR[n.id]) return this.tracabilite(PSR[n.id], niveau, racine.millesime)
    if (!n.enfants?.length) {
      niveau.fin = { texte: 'Le budget de l’État ne détaille pas ce poste plus finement dans les données du site : la piste s’arrête ici.' }
      return niveau
    }
    niveau.options = n.enfants
      .map((e) => ({ cle: e.id, nom: propre(e.nom), part: n.md ? e.md / n.md : 0, statut: 'trace' as Statut, suite: () => this.etat(e.id) }))
      .sort((a, b) => b.part - a.part)
    return niveau
  }

  async tracabilite(fichier: string, niveau: Niveau, millesime: string, programme?: string): Promise<Niveau> {
    const t = await chargerSiPresent<FichierTrac>(fichier)
    if (!t || t.millesime !== millesime || !t.parts) {
      niveau.fin = { texte: 'Les destinataires de ce poste ne sont pas disponibles pour la même année : la piste s’arrête ici.' }
      return niveau
    }
    niveau.titre = `${niveau.titre} : à qui va l’argent`
    niveau.source = t.source
    niveau.note = 'Dernière étape publiée : la part de l’argent dont le destinataire est connu, mesurée par le site (méthode sur la page Traçabilité).'
    niveau.options = ORDRE_TRAC.filter((k) => t.parts[k] && t.parts[k].pct > 0).map((k) => {
      const p = t.parts[k]
      const s = statutPart(k, p.statut)
      return {
        cle: k,
        nom: p.libelle,
        part: p.pct / 100,
        statut: s,
        detail: s === 'approche' && p.ecart_millesime_ans ? `Données décalées de ${p.ecart_millesime_ans} an.` : undefined,
        suite: () => Promise.resolve(finTrac(k, p.libelle, s, millesime, programme)),
      }
    })
    return niveau
  }

  async administrations(id: string, via?: string): Promise<Niveau> {
    const racine = await chargerSiPresent<RacineSimple>('arbre_administrations/racine.json')
    const n = racine ? trouver(racine, id) : null
    if (!racine || !n) return { titre: via ?? 'Collectivités locales', millesime: '', source: '', options: [], fin: { texte: 'Les dépenses des collectivités locales ne sont pas disponibles : la piste s’arrête ici.' } }
    const niveau: Niveau = {
      titre: n.id === 'S1313' ? 'Collectivités locales (ensemble)' : propre(n.nom),
      millesime: racine.millesime,
      source: racine.source,
      options: [],
    }
    if (via && n.id === 'S1313')
      niveau.note = `${via} : la répartition ci-dessous est celle de l’ensemble des collectivités locales (comptabilité nationale), pas de la seule collectivité qui reçoit ton euro. Le budget de ta commune est sur la page Budget de ma commune.`
    if (!n.enfants?.length) {
      niveau.fin = {
        statut: 'trace',
        texte: 'Dernier niveau publié par la comptabilité nationale (fonctions des administrations) : les bénéficiaires ne sont pas détaillés à ce niveau. La piste s’arrête ici.',
        liens: [
          { href: lien('/explorer/collectivites'), texte: 'Les collectivités locales' },
          { href: lien('/local'), texte: 'Budget de ma commune' },
        ],
      }
      return niveau
    }
    const statut: Statut = via ? 'approche' : 'trace'
    niveau.options = n.enfants
      .map((e) => ({ cle: e.id, nom: propre(e.nom), part: n.md ? e.md / n.md : 0, statut, suite: () => this.administrations(e.id, via) }))
      .sort((a, b) => b.part - a.part)
    return niveau
  }
}

function trouver<T extends { id: string; enfants?: T[] }>(n: T | { id: string; enfants?: T[] }, id: string): T | null {
  if (n.id === id) return n as T
  for (const e of n.enfants ?? []) {
    if (id === e.id || id.startsWith(e.id + '/')) {
      const r = trouver(e, id)
      if (r) return r
    }
  }
  return null
}

function statutSecu(n: NoeudSecu): Statut {
  if (n.mode === 'ecart') return 'nonpub'
  if (n.mode === 'derive') return 'approche'
  if (n.mode) return 'trace'
  return (n.tracabilite_pct ?? 0) >= 99.5 ? 'trace' : 'approche'
}

function finSecu(n: NoeudSecu): NonNullable<Niveau['fin']> {
  const statut = statutSecu(n)
  const liens = [{ href: lien('/explorer/secu'), texte: 'Sécurité sociale et protection sociale' }]
  if (statut === 'nonpub')
    return { statut, texte: 'Ce montant n’est ventilé dans aucune source publiée : la piste s’arrête faute de publication.', liens }
  if (statut === 'approche')
    return { statut, texte: 'Ce montant est déduit par calcul à partir d’autres lignes publiées ; aucun détail plus fin n’est publié. La piste s’arrête ici.', liens }
  return {
    statut,
    texte: `C’est la ligne la plus fine publiée dans les comptes${n.ref ? ` (${n.ref})` : ''}. Les bénéficiaires finaux (personnes, établissements, professionnels) ne sont pas détaillés : la piste s’arrête ici.`,
    liens,
  }
}

function finTrac(cle: string, nom: string, statut: Statut, millesime: string, programme?: string): Niveau {
  const textes: Record<string, string> = {
    beneficiaire_identifie: 'Bénéficiaires identifiés : entreprises, associations, opérateurs de l’État ou collectivités nommés dans les données publiées (personnes morales seulement). La piste continue sur la page du programme.',
    nominatif_par_choix: 'Rémunérations des agents publics : la catégorie d’agents est publiée, pas le nom des personnes. La piste s’arrête ici par choix de protection des personnes.',
    anonyme_par_nature: 'Porteurs de la dette de l’État : les titres s’échangent sur les marchés et leurs détenteurs ne sont pas nommés. La piste s’arrête ici.',
    non_publie: 'Le destinataire de cette part n’apparaît dans aucune donnée ouverte réunie par le site : la piste s’arrête faute de publication. Cela ne dit rien de la régularité ni de l’utilité de la dépense.',
  }
  const liens = [{ href: lien('/methode/tracabilite'), texte: 'Traçabilité : d’où vient chaque montant' }]
  if (cle === 'beneficiaire_identifie') liens.unshift(programme ? { href: lien('/beneficiaires/programme', { p: programme }), texte: `Le programme ${programme} en détail` } : { href: lien('/beneficiaires'), texte: 'Qui reçoit l’argent' })
  return { titre: nom, millesime, source: '', options: [], fin: { statut, texte: textes[cle] ?? '', liens } }
}

// ---------- Rendu ----------
interface Etat {
  depart: string
  base: 1 | 100
  /** clés choisies, une par étape */
  piste: string[]
  niveaux: Niveau[]
}

const groupes = (aff: Affectation) => {
  const paie = [...new Set(Object.values(aff.correspondance_calcul ?? {}))].filter((k) => aff.prelevements[k])
  const toutes = Object.keys(aff.prelevements)
  const achats = ACHATS.filter((k) => aff.prelevements[k])
  const logement = LOGEMENT.filter((k) => aff.prelevements[k])
  const autres = toutes.filter((k) => !paie.includes(k) && !achats.includes(k) && !logement.includes(k))
  return [
    { titre: 'Sur ta fiche de paie', cles: paie },
    { titre: 'Quand tu achètes', cles: achats },
    { titre: 'Pour ton logement', cles: logement },
    { titre: 'Autres prélèvements', cles: autres },
  ].filter((g) => g.cles.length)
}

/** Construit les étapes d'une piste ; sans piste donnée, suit la plus grande part à chaque étape. */
async function construire(lecteur: Lecteur, depart: string, piste: string[] | null): Promise<{ niveaux: Niveau[]; piste: string[] }> {
  const niveaux: Niveau[] = [lecteur.depart(depart)]
  const suivie: string[] = []
  for (let i = 0; i < 12; i++) {
    const n = niveaux[i]
    const voulu = piste ? piste[i] : n.options.find((o) => o.part > 0 && o.suite)?.cle
    if (!voulu) break
    const o = n.options.find((x) => x.cle === voulu) ?? (n.fin?.alternative?.cle === voulu ? n.fin.alternative : undefined)
    if (!o || !o.suite || o.part <= 0) break
    suivie.push(o.cle)
    niveaux.push(await o.suite())
  }
  return { niveaux, piste: suivie }
}

/** Part cumulée de l'euro de départ arrivée à chaque étape (index 0 : 1 €). */
function cumuls(e: Etat): number[] {
  const out = [1]
  e.piste.forEach((cle, i) => {
    const n = e.niveaux[i]
    const o = n.options.find((x) => x.cle === cle) ?? n.fin?.alternative
    out.push(out[i] * (o?.part ?? 0))
  })
  return out
}

function optionChoisie(n: Niveau, cle: string | undefined) {
  return cle ? n.options.find((x) => x.cle === cle) ?? (n.fin?.alternative?.cle === cle ? n.fin.alternative : undefined) : undefined
}

function rendreEtapes(aff: Affectation, e: Etat): string {
  const c = cumuls(e)
  const nomDepart = propre(COURTS[e.depart] ?? aff.prelevements[e.depart].libelle)
  const surBase = `Sur ${e.base === 1 ? '1 €' : '100 €'} de ${nomDepart.charAt(0).toLowerCase()}${nomDepart.slice(1)}`
  const etapes = e.niveaux.map((n, i) => {
    const choisi = e.piste[i]
    const arrive = i === 0 ? '' : `<p class="suivre-arrive">${h(surBase)}, <strong>${h(montant(c[i], e.base))}</strong> arrivent à cette étape.</p>`
    const options = n.options.length
      ? `<ul class="suivre-options" aria-label="Pistes possibles à l’étape ${i + 1}">${n.options
          .map((o) => {
            const negatif = o.part < 0
            const valeur = negatif ? `en déduction : ${montant(-o.part * c[i], e.base)}` : montant(o.part * c[i], e.base)
            const nom = o.suite && !negatif
              ? `<button type="button" class="suivre-choix" data-etape="${i}" data-cle="${h(o.cle)}" aria-pressed="${choisi === o.cle}">${h(o.nom)}</button>`
              : `<span class="nom">${h(o.nom)}</span>`
            return `<li${choisi === o.cle ? ' class="actif"' : ''}><div class="barre-tete">${nom}<span class="valeur">${h(valeur)} ${badgeStatut(o.statut)}</span></div>${
              o.detail ? `<div class="aide">${h(o.detail)}</div>` : ''
            }<div class="barre" aria-hidden="true"><span class="barre-remplissage statut-${o.statut}" data-l="${Math.max(0, Math.min(100, Math.abs(o.part) * 100)).toFixed(2)}"></span></div></li>`
          })
          .join('')}</ul>`
      : ''
    const fin = n.fin
      ? `<div class="suivre-fin">
  <h3>${n.fin.statut ? `${badgeStatut(n.fin.statut)} ` : ''}La piste s’arrête ici</h3>
  <p>${h(n.fin.texte)}</p>
  ${n.fin.alternative ? `<p><button type="button" class="suivre-choix" data-etape="${i}" data-cle="${h(n.fin.alternative.cle)}" aria-pressed="${choisi === n.fin.alternative.cle}">${h(n.fin.alternative.nom)}</button> ${badgeStatut(n.fin.alternative.statut)}</p>` : ''}
  ${n.fin.liens?.length ? `<ul>${n.fin.liens.map((l) => `<li><a href="${h(l.href)}">${h(l.texte)}</a></li>`).join('')}</ul>` : ''}
</div>`
      : ''
    const consigne = n.options.some((o) => o.suite && o.part > 0) && !choisi ? '<p class="aide">Choisis une piste pour continuer.</p>' : ''
    return `<li class="carte carte-contour suivre-etape" id="suivre-etape-${i}">
  <h2 tabindex="-1">Étape ${i + 1} · ${h(n.titre)}</h2>
  ${arrive}
  ${n.note ? `<p class="aide">${h(n.note)}</p>` : ''}
  ${options}
  ${consigne}
  ${fin}
  ${n.source ? `<p class="source">${h(n.source)}${n.millesime ? ` (${h(n.millesime)})` : ''}</p>` : ''}
</li>`
  })
  const annees = [...new Set(e.niveaux.map((n) => n.millesime).filter(Boolean).map(annee))]
  const melange = annees.length > 1
    ? `<p class="avertissement">Les étapes ne portent pas toutes sur la même année (${annees.map(h).join(', ')}) : la répartition du prélèvement et les dépenses des organismes viennent de documents différents. Le montant suivi est un ordre de grandeur.</p>`
    : ''
  return `${melange}<ol class="suivre-etapes">${etapes.join('')}</ol>`
}

function maillons(aff: Affectation, e: Etat): MaillonPiste[] {
  const c = cumuls(e)
  const out: MaillonPiste[] = [{ nom: propre(COURTS[e.depart] ?? aff.prelevements[e.depart].libelle), texte: montant(1, e.base), valeur: 1, statut: 'trace' }]
  e.piste.forEach((cle, i) => {
    const o = optionChoisie(e.niveaux[i], cle)
    if (o) out.push({ nom: o.nom, texte: montant(c[i + 1], e.base), valeur: c[i + 1], statut: o.statut })
  })
  return out
}

function resume(aff: Affectation, e: Etat): string {
  const m = maillons(aff, e)
  const lecture = m.map((x) => `${x.nom} : ${x.texte} (${STATUTS[x.statut].libelle.toLowerCase()})`).join(', puis ')
  return `${filPiste(m)}<p class="visuellement-cache">Ta piste : ${h(lecture)}.</p>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const aff = await chargerSiPresent<Affectation>('prelevements/affectation.json')
  if (!aff || !Object.keys(aff.prelevements ?? {}).length) {
    cible.innerHTML = enCours('Suivre un euro', 'Suivre 1 € de ce que tu verses jusqu’à son dernier usage publié.')
    return
  }
  const lecteur = new Lecteur(aff)
  const demande = params.get('depart') ?? ''
  const depart = aff.prelevements[demande] ? demande : aff.prelevements.csg_activite ? 'csg_activite' : Object.keys(aff.prelevements)[0]
  const pisteDemandee = params.get('piste')
  const base: 1 | 100 = params.get('base') === '100' ? 100 : 1
  const e: Etat = { depart, base, piste: [], niveaux: [] }
  Object.assign(e, await construire(lecteur, depart, pisteDemandee ? pisteDemandee.split('~').filter(Boolean) : null))

  const boutonsDepart = groupes(aff)
    .map(
      (g) => `<h3>${h(g.titre)}</h3><div class="bascule suivre-departs">${g.cles
        .map((k) => `<button type="button" data-depart="${h(k)}" aria-pressed="${k === e.depart}">${h(propre(COURTS[k] ?? aff.prelevements[k].libelle))}</button>`)
        .join('')}</div>`,
    )
    .join('')

  cible.innerHTML = `
<h1>Suivre un euro</h1>
${retourResultat()}
<p class="chapeau">Choisis un prélèvement : le site suit 1 € de ce que tu verses, étape par étape, de l’organisme qui le reçoit jusqu’au dernier niveau publié. Là où plus rien n’est publié, la piste s’arrête et la page le dit.</p>
${legendeStatuts()}
<section class="carte" aria-labelledby="suivre-titre-depart">
  <h2 id="suivre-titre-depart">D’où part ton euro</h2>
  ${boutonsDepart}
  <h3>Montant suivi</h3>
  <div class="bascule"><button type="button" data-base="1" aria-pressed="${e.base === 1}">Sur 1 €</button><button type="button" data-base="100" aria-pressed="${e.base === 100}">Sur 100 €</button></div>
</section>
<section class="carte" aria-labelledby="suivre-titre-piste">
  <h2 id="suivre-titre-piste">Ta piste</h2>
  <p id="suivre-jauge-texte"></p>
  <div class="barre" aria-hidden="true"><span class="barre-remplissage" id="suivre-jauge" data-l="100"></span></div>
  <div id="suivre-dessin"></div>
  <p class="aide">Au départ, la piste suit la plus grande part à chaque étape. Choisis une autre piste à n’importe quelle étape. Chaque part est celle de l’étape précédente : l’argent d’un organisme n’est pas fléché ligne à ligne, ton euro suit donc la répartition de ses dépenses.</p>
</section>
<div id="suivre-etapes"></div>`

  const zoneEtapes = cible.querySelector('#suivre-etapes') as HTMLElement
  const jauge = cible.querySelector('#suivre-jauge') as HTMLElement
  const jaugeTexte = cible.querySelector('#suivre-jauge-texte') as HTMLElement
  const dessin = cible.querySelector('#suivre-dessin') as HTMLElement

  const peindre = (focusEtape?: number) => {
    zoneEtapes.innerHTML = rendreEtapes(aff, e)
    dessin.innerHTML = resume(aff, e)
    const c = cumuls(e)
    const dernier = c[c.length - 1]
    jaugeTexte.innerHTML = `Sur ${e.base === 1 ? '1 €' : '100 €'} au départ, <strong>${h(montant(dernier, e.base))}</strong> suivis jusqu’à la dernière étape (${c.length} étape${c.length > 1 ? 's' : ''}).`
    jauge.dataset.l = Math.max(0.5, dernier * 100).toFixed(2)
    jauge.style.width = `${jauge.dataset.l}%`
    zoneEtapes.querySelectorAll<HTMLElement>('[data-l]').forEach((el) => (el.style.width = `${el.dataset.l}%`))
    if (focusEtape !== undefined) {
      const cibleEtape = zoneEtapes.querySelector<HTMLElement>(`#suivre-etape-${focusEtape} h2`)
      if (cibleEtape) {
        const reduit = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
        cibleEtape.focus({ preventScroll: true })
        cibleEtape.scrollIntoView?.({ behavior: reduit ? 'auto' : 'smooth', block: 'start' })
      }
    }
  }
  peindre()

  let enCoursDeCalcul = false
  cible.addEventListener('click', async (ev) => {
    const b = (ev.target as HTMLElement).closest('button')
    if (!b || !cible.contains(b) || enCoursDeCalcul) return
    enCoursDeCalcul = true
    try {
      if (b.dataset.depart) {
        e.depart = b.dataset.depart
        Object.assign(e, await construire(lecteur, e.depart, null))
        cible.querySelectorAll('[data-depart]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)))
        peindre()
        annoncer(`Piste de départ : ${b.textContent ?? ''}`)
      } else if (b.dataset.base) {
        e.base = b.dataset.base === '100' ? 100 : 1
        cible.querySelectorAll('[data-base]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)))
        peindre()
      } else if (b.dataset.etape !== undefined && b.dataset.cle) {
        const i = Number(b.dataset.etape)
        const r = await construire(lecteur, e.depart, [...e.piste.slice(0, i), b.dataset.cle])
        Object.assign(e, r)
        peindre(Math.min(i + 1, e.niveaux.length - 1))
        annoncer(`Étape ${i + 2} : ${e.niveaux[i + 1]?.titre ?? ''}`)
      }
    } finally {
      enCoursDeCalcul = false
    }
  })
}

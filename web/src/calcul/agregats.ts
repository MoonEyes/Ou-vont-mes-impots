// Agrégats légers du calcul (affectation, totaux, regroupement par destinataire), sans le moteur publicodes :
// utilisables sur le fil principal pendant que le moteur tourne dans un Web Worker (recette perf, docs/RECETTE.md).
import { BAREMES_2025 } from './baremes-2025'
import { DESTINATAIRES, destinataire, enregistrerDestinataires } from './destinataires'
import type { Destinataire, Fourchette, Prelevement, TauxCsgRetraite } from './types'

const arrondi = (x: number) => Math.round(x * 100) / 100

/** Affectation de chaque prélèvement (site/data/prelevements/affectation.json, contrat 1.4). */
export interface Affectation {
  annee?: string | number
  millesime?: string
  source?: string
  destinataires?: Record<string, { nom: string; administration: string }>
  prelevements: Record<
    string,
    { libelle?: string; statut?: 'sourcee' | 'non sourcee'; ventilation: { destinataire: string; part: number; source?: string }[]; note?: string }
  >
  correspondance_calcul?: Record<string, string>
  /** lignes dont la répartition dépend du taux de CSG de la personne : ligne du calcul, puis taux, vers la clé (contrat 1.4) */
  correspondance_calcul_selon_taux?: Record<string, Partial<Record<TauxCsgRetraite, string>>>
}

/** Lignes de CSG sur les pensions (moteur-etendu.ts) : leur taux cumulé désigne la catégorie de la personne. */
export const LIGNES_CSG_PENSION = ['csg_pension_deductible', 'csg_pension_non_deductible'] as const

/**
 * Taux de CSG sur les pensions de la personne (normal 8,3 %, médian 6,6 %, réduit 3,8 %), retrouvé dans ses lignes :
 * somme des taux de CSG déductible et non déductible, comparée aux barèmes 2025 (baremes-2025.ts). null si aucune ligne
 * ou si la somme ne correspond à aucun barème (jamais de catégorie supposée).
 */
export function tauxCsgPensionDesLignes(lignes: Prelevement[], personne: Prelevement['personne']): TauxCsgRetraite | null {
  const csg = lignes.filter((l) => l.personne === personne && (LIGNES_CSG_PENSION as readonly string[]).includes(l.id.replace(/_declarant2$/, '')))
  if (!csg.length) return null
  const somme = csg.reduce((s, l) => s + (l.taux ?? 0), 0)
  const taux = BAREMES_2025.pensions.taux
  for (const c of Object.keys(taux) as TauxCsgRetraite[]) {
    if (c === 'exonere') continue
    if (Math.abs(taux[c].deductible + taux[c].nonDeductible - somme) < 1e-9) return c
  }
  return null
}

/** Clé de affectation.json d'une ligne du calcul : selon le taux de CSG d'abord, puis correspondances publiée et locale. */
export function cleAffectation(l: Prelevement, lignes: Prelevement[], affectation?: Affectation | null): string {
  const base = l.id.replace(/_declarant2$/, '')
  const selonTaux = affectation?.correspondance_calcul_selon_taux?.[base]
  if (selonTaux) {
    const taux = tauxCsgPensionDesLignes(lignes, l.personne)
    const cle = taux ? selonTaux[taux] : undefined
    if (cle) return cle
  }
  return affectation?.correspondance_calcul?.[base] ?? CORRESPONDANCE_LOCALE[base] ?? base
}

/** Destinataire affiché d'une ligne répartie entre plusieurs organismes qui n'en avait pas de publié. */
function destinataireReparti(ventilation: { destinataire: string }[]): Destinataire {
  const admins = new Set(ventilation.map((v) => destinataire(v.destinataire).administration))
  return admins.size === 1 && admins.has('Securite sociale') ? DESTINATAIRES.plusieurs : destinataire('plusieurs_organismes')
}

// Correspondances absentes de correspondance_calcul (identifiants propres au module de calcul).
const CORRESPONDANCE_LOCALE: Record<string, string> = {
  allocations_familiales: 'famille',
  chomage: 'chomage',
  ceg_employeur: 'ceg',
  maladie_salarie: 'maladie',
  // Profils étendus (moteur-etendu.ts) : CSG du forfait micro-social et versement libératoire de l'impôt.
  csg_micro: 'csg_activite',
  impot_revenu_versement_liberatoire: 'impot_revenu',
}

/** Remplace les destinataires par la ventilation sourcée de affectation.json, quand elle existe. */
export function appliquerAffectation(lignes: Prelevement[], affectation?: Affectation | null): Prelevement[] {
  if (!affectation?.prelevements) return lignes
  enregistrerDestinataires(affectation.destinataires)
  return lignes.map((l) => {
    const a = affectation.prelevements[cleAffectation(l, lignes, affectation)]
    if (!a?.ventilation?.length) return l
    if (l.ventilation?.length) return { ...l, statut_affectation: l.statut_affectation ?? a.statut ?? 'sourcee' }
    const somme = a.ventilation.reduce((x, v) => x + v.part, 0)
    if (Math.abs(somme - 1) > 0.001) return l
    const ventilation = a.ventilation.map((v) => ({ destinataire: v.destinataire, part: v.part, ...(v.source ? { source: v.source } : {}) }))
    const unique = ventilation.length === 1 ? destinataire(ventilation[0].destinataire) : null
    // Ligne sans destinataire publié (profils étendus) devenue répartie : elle n'est plus « sans destinataire publié ».
    const reparti = !unique && l.destinataire.id === 'non_affecte' ? destinataireReparti(ventilation) : null
    return {
      ...l,
      ...(unique ? { destinataire: unique } : reparti ? { destinataire: reparti } : {}),
      ventilation,
      statut_affectation: a.statut ?? 'sourcee',
    }
  })
}

export function additionner(lignes: Prelevement[]): Fourchette {
  const t = { bas: 0, central: 0, haut: 0 }
  for (const l of lignes) {
    if (l.non_chiffre) continue
    if (l.nature === 'reduction') {
      t.bas -= l.montant_annuel_eur.haut
      t.central -= l.montant_annuel_eur.central
      t.haut -= l.montant_annuel_eur.bas
    } else {
      t.bas += l.montant_annuel_eur.bas
      t.central += l.montant_annuel_eur.central
      t.haut += l.montant_annuel_eur.haut
    }
  }
  return { bas: arrondi(Math.max(0, t.bas)), central: arrondi(Math.max(0, t.central)), haut: arrondi(Math.max(0, t.haut)) }
}

/** Totaux par destinataire ; avec inclutPatronal, ajoute les cotisations patronales (réductions déduites). */
export function parDestinataire(prelevements: Prelevement[], inclutPatronal: boolean) {
  const groupes = new Map<string, Prelevement[]>()
  for (const l of prelevements) {
    if (l.non_chiffre) continue
    if (!l.inclus_dans_total_paye && !inclutPatronal) continue
    if (l.ventilation && l.ventilation.length) {
      for (const v of l.ventilation) {
        const part: Prelevement = {
          ...l,
          montant_annuel_eur: {
            bas: l.montant_annuel_eur.bas * v.part,
            central: l.montant_annuel_eur.central * v.part,
            haut: l.montant_annuel_eur.haut * v.part,
          },
        }
        const g = groupes.get(v.destinataire) ?? []
        g.push(part)
        groupes.set(v.destinataire, g)
      }
    } else {
      const g = groupes.get(l.destinataire.id) ?? []
      g.push(l)
      groupes.set(l.destinataire.id, g)
    }
  }
  return [...groupes.entries()]
    .map(([destinataire, ls]) => ({ destinataire, montant_annuel_eur: additionner(ls), inclut_patronal: inclutPatronal }))
    .sort((a, b) => b.montant_annuel_eur.central - a.montant_annuel_eur.central)
}

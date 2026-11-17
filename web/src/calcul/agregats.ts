// Agrégats légers du calcul (affectation, totaux, regroupement par destinataire), sans le moteur publicodes :
// utilisables sur le fil principal pendant que le moteur tourne dans un Web Worker (recette perf, docs/RECETTE.md).
import { destinataire, enregistrerDestinataires } from './destinataires'
import type { Fourchette, Prelevement } from './types'

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
}

// Correspondances absentes de correspondance_calcul (identifiants propres au module de calcul).
const CORRESPONDANCE_LOCALE: Record<string, string> = {
  allocations_familiales: 'famille',
  chomage: 'chomage',
  ceg_employeur: 'ceg',
  maladie_salarie: 'maladie',
}

/** Remplace les destinataires par la ventilation sourcée de affectation.json, quand elle existe. */
export function appliquerAffectation(lignes: Prelevement[], affectation?: Affectation | null): Prelevement[] {
  if (!affectation?.prelevements) return lignes
  enregistrerDestinataires(affectation.destinataires)
  return lignes.map((l) => {
    const base = l.id.replace(/_declarant2$/, '')
    const cle = affectation.correspondance_calcul?.[base] ?? CORRESPONDANCE_LOCALE[base] ?? base
    const a = affectation.prelevements[cle]
    if (!a?.ventilation?.length) return l
    if (l.ventilation?.length) return { ...l, statut_affectation: l.statut_affectation ?? a.statut ?? 'sourcee' }
    const somme = a.ventilation.reduce((x, v) => x + v.part, 0)
    if (Math.abs(somme - 1) > 0.001) return l
    const ventilation = a.ventilation.map((v) => ({ destinataire: v.destinataire, part: v.part, ...(v.source ? { source: v.source } : {}) }))
    const unique = ventilation.length === 1 ? destinataire(ventilation[0].destinataire) : null
    return {
      ...l,
      ...(unique ? { destinataire: unique } : {}),
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

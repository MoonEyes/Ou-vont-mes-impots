// Résumé d'un calcul personnel pour l'affichage : total, parts « sur 100 € » par destinataire, et les trois sorties
// (pris sur le salaire, versé en achetant, taxe sur les ordures). Sert au résultat, à la carte partagée et à
// l'exemple de l'accueil (src/exemple-lyon.json, écrit par tests/ecrans.test.ts à partir du même calcul).
import type { Complet } from '../calcul/hors-bulletin'
import { ORDRE_ADMIN, parAdministration, sur100Entiers } from '../calcul/repartition'
import type { Fourchette, Prelevement, ResultatOk } from '../calcul/types'
import { entier, eur, type Statut } from '../util'

export interface ResumeCalcul {
  total: Fourchette
  /** euros entiers sur 100 €, par administration (somme = 100) */
  sur100: Record<string, number>
  sources: { salaire: Fourchette; achats: Fourchette | null; ordures: Fourchette | null }
}

export function sousTotal(ls: Prelevement[]): Fourchette {
  const t = { bas: 0, central: 0, haut: 0 }
  for (const l of ls) {
    if (l.non_chiffre) continue
    t.bas += l.montant_annuel_eur.bas
    t.central += l.montant_annuel_eur.central
    t.haut += l.montant_annuel_eur.haut
  }
  return t
}

const arrondir = (f: Fourchette): Fourchette => ({ bas: Math.round(f.bas), central: Math.round(f.central), haut: Math.round(f.haut) })

export function resumer(r: ResultatOk, c: Complet | null): ResumeCalcul {
  const lignes = c?.lignes ?? r.prelevements.filter((l) => l.inclus_dans_total_paye)
  const s100 = sur100Entiers(parAdministration(lignes))
  return {
    total: arrondir(c ? c.total : r.totaux.paye_par_le_foyer),
    sur100: Object.fromEntries(ORDRE_ADMIN.filter((a) => (s100[a] ?? 0) > 0).map((a) => [a, s100[a]])),
    sources: {
      salaire: arrondir(sousTotal(lignes.filter((l) => ['cotisation_salariale', 'csg_crds', 'impot_revenu'].includes(l.famille)))),
      // Outre-mer, les taxes sur la consommation sont toutes « non chiffré » : pas de montant à afficher.
      achats: c && c.conso.some((l) => !l.non_chiffre) ? arrondir(sousTotal(c.conso)) : null,
      ordures: c && c.locaux.some((l) => !l.non_chiffre) ? arrondir(sousTotal(c.locaux)) : null,
    },
  }
}

export const estPlage = (f: Fourchette) => Math.round(f.bas) !== Math.round(f.haut)
/** « 7 638 € » ou « 4 681 à 6 143 € ». */
export const plage = (f: Fourchette) => (estPlage(f) ? `${entier(Math.round(f.bas))} à ${eur(f.haut)}` : eur(f.central))
export const statutPlage = (f: Fourchette): Statut => (estPlage(f) ? 'approche' : 'trace')

/** Les trois sorties, prêtes pour la liste « D'où ça sort » et le fil de l'euro. */
export function sorties(s: ResumeCalcul['sources'], locataire = true) {
  return [
    { nom: 'Sur ton salaire', court: 'Salaire', detail: 'Cotisations, CSG et impôt sur le revenu', f: s.salaire },
    ...(s.achats ? [{ nom: 'Sur tes achats', court: 'Achats', detail: 'TVA, carburant, tabac, alcool', f: s.achats }] : []),
    ...(s.ordures ? [{ nom: locataire ? 'Sur tes ordures' : 'Sur ton logement', court: locataire ? 'Ordures' : 'Logement', detail: locataire ? 'Taxe d’enlèvement (TEOM), dans tes charges' : 'Taxe foncière et TEOM', f: s.ordures }] : []),
  ].map((x) => ({ ...x, texte: plage(x.f), statut: statutPlage(x.f) }))
}

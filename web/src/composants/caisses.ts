// Les caisses de l'argent public, en tuiles : une couleur de famille, un picto, un chiffre lu dans les données
// et un mini-visuel à la même échelle d'une tuile à l'autre (1 carré = 50 Md€). Aucun chiffre n'est écrit ici.
import { chargerSiPresent } from '../donnees'
import { entier, h } from '../util'
import { picto } from './pictos'

const nf1 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
/** Milliards d'euros, forme courte des tuiles : « 503 Md€ », « 22,3 Md€ ». */
export const mdCourt = (x: number) => (x >= 1000 || Math.abs(x - Math.round(x)) < 0.05 ? `${entier(Math.round(x))} Md€` : `${nf1.format(x)} Md€`)

interface Mesure {
  /** valeur chiffrée : milliards d'euros, ou un nombre d'unités */
  valeur: number
  texte: string
  legende?: string
}
interface Caisse {
  cle: string
  famille: string
  picto: string
  nom: string
  lien: string
  legende: string
  /** unité du mini-visuel : carrés de 50 Md€ ou points de n unités */
  visuel: { forme: 'carre'; pas: number; unite: string } | { forme: 'point'; pas: number; unite: string }
  lire: () => Promise<Mesure | null>
}

const annee = (millesime?: string) => /\b(20\d\d)\b/.exec(millesime ?? '')?.[1]

const CAISSES: Caisse[] = [
  {
    cle: 'etat', famille: 'etat', picto: 'etat', nom: 'L’État', lien: '#/explorer/etat', legende: 'dépensés par l’État',
    visuel: { forme: 'carre', pas: 50, unite: '1 carré = 50 Md€' },
    lire: async () => {
      const r = await chargerSiPresent<{ md: number; millesime?: string }>('arbre/racine.json')
      return r ? { valeur: r.md, texte: mdCourt(r.md), legende: annee(r.millesime) ? `dépensés en ${annee(r.millesime)}` : undefined } : null
    },
  },
  {
    cle: 'secu', famille: 'secu', picto: 'secu', nom: 'La Sécurité sociale', lien: '#/explorer/secu', legende: 'retraites, santé, famille',
    visuel: { forme: 'carre', pas: 50, unite: '1 carré = 50 Md€' },
    lire: async () => {
      const r = await chargerSiPresent<{ vues?: { arbre?: { total_md?: number } } }>('secu/index.json')
      const v = r?.vues?.arbre?.total_md
      return typeof v === 'number' ? { valeur: v, texte: mdCourt(v) } : null
    },
  },
  {
    cle: 'collectivites', famille: 'collectivites', picto: 'logement', nom: 'Les collectivités', lien: '#/explorer/collectivites', legende: 'communes, chacune avec son budget',
    visuel: { forme: 'point', pas: 500, unite: '1 point = 500 communes' },
    lire: async () => {
      const r = await chargerSiPresent<{ controle?: { communes?: number } }>('meta.json')
      const v = r?.controle?.communes
      return typeof v === 'number' ? { valeur: v, texte: entier(v) } : null
    },
  },
  {
    cle: 'ue', famille: 'ue', picto: 'europe', nom: 'L’Union européenne', lien: '#/explorer/ue', legende: 'versés par la France',
    visuel: { forme: 'carre', pas: 50, unite: '1 carré = 50 Md€' },
    lire: async () => {
      const r = await chargerSiPresent<{ psr_ue?: { md?: number } }>('ue/contribution.json')
      const v = r?.psr_ue?.md
      return typeof v === 'number' ? { valeur: v, texte: mdCourt(v) } : null
    },
  },
  {
    cle: 'dette', famille: 'dette', picto: 'dette', nom: 'La dette', lien: '#/explorer/dette', legende: 'de dette publique',
    visuel: { forme: 'carre', pas: 50, unite: '1 carré = 50 Md€' },
    lire: async () => {
      const r = await chargerSiPresent<{ synthese?: { encours_maastricht?: { md?: number } } }>('dette/index.json')
      const v = r?.synthese?.encours_maastricht?.md
      return typeof v === 'number' ? { valeur: v, texte: mdCourt(v) } : null
    },
  },
  {
    cle: 'niches', famille: 'niches', picto: 'niches', nom: 'Les dépenses fiscales', lien: '#/explorer/niches', legende: 'd’impôts non perçus',
    visuel: { forme: 'carre', pas: 50, unite: '1 carré = 50 Md€' },
    lire: async () => {
      const r = await chargerSiPresent<{ totaux?: Record<string, { statut?: string; chiffre_meur?: number }> }>('niches/index.json')
      const an = Object.keys(r?.totaux ?? {}).sort().reverse().find((a) => r!.totaux![a].statut === 'constaté' && typeof r!.totaux![a].chiffre_meur === 'number')
      return an ? { valeur: r!.totaux![an].chiffre_meur! / 1000, texte: mdCourt(r!.totaux![an].chiffre_meur! / 1000), legende: `d’impôts non perçus en ${an}` } : null
    },
  },
  {
    cle: 'operateurs', famille: 'operateurs', picto: 'operateurs', nom: 'Les opérateurs', lien: '#/explorer/operateurs', legende: 'organismes financés par l’État',
    visuel: { forme: 'point', pas: 10, unite: '1 point = 10 organismes' },
    lire: async () => {
      const r = await chargerSiPresent<{ couverture?: { operateurs_liste_plf2026?: number } }>('operateurs/index.json')
      const v = r?.couverture?.operateurs_liste_plf2026
      return typeof v === 'number' ? { valeur: v, texte: entier(v) } : null
    },
  },
  {
    cle: 'recettes', famille: 'prestations', picto: 'recettes', nom: 'Les recettes', lien: '#/explorer/recettes', legende: 'd’impôts et de cotisations encaissés',
    visuel: { forme: 'carre', pas: 50, unite: '1 carré = 50 Md€' },
    lire: async () => {
      const r = await chargerSiPresent<{ annees?: Record<string, { Ensemble?: { TR?: number } }> }>('administrations.json')
      const an = Object.keys(r?.annees ?? {}).sort().pop()
      const v = an ? r!.annees![an].Ensemble?.TR : undefined
      return typeof v === 'number' ? { valeur: v, texte: mdCourt(v), legende: `de recettes publiques en ${an}` } : null
    },
  },
]

/** Mini-visuel : des carrés (ou des points) tous à la même échelle ; le dernier est entamé au prorata. */
function visuel(c: Caisse, valeur: number): string {
  const n = valeur / c.visuel.pas
  const pleins = Math.floor(n)
  const reste = n - pleins
  const parLigne = 14
  const formes: string[] = []
  const total = Math.min(pleins + (reste > 0.02 ? 1 : 0), parLigne * 6)
  for (let i = 0; i < total; i++) {
    const x = (i % parLigne) * 18
    const y = Math.floor(i / parLigne) * 18
    const part = i < pleins ? 1 : reste
    formes.push(
      c.visuel.forme === 'carre'
        ? `<rect x="${x}" y="${y}" width="${(14 * part).toFixed(1)}" height="14" rx="${part < 0.4 ? 1.5 : 3}"/>`
        : `<circle cx="${x + 7}" cy="${y + 7}" r="${(6.5 * Math.sqrt(part)).toFixed(1)}"/>`,
    )
  }
  const lignes = Math.max(1, Math.ceil(total / parLigne))
  return `<svg viewBox="0 0 248 ${lignes * 18 - 4}" aria-hidden="true" focusable="false">${formes.join('')}</svg><span>${h(c.visuel.unite)}</span>`
}

/** Les tuiles s'affichent tout de suite ; remplirTuiles pose ensuite chiffres et visuels sans déplacer la page. */
export function tuiles(avecVisuels = false): string {
  return `<ul class="tuiles${avecVisuels ? ' tuiles-visuels' : ''}">${CAISSES.map(
    (c) =>
      `<li class="f-${c.famille}"><a href="${c.lien}" data-caisse="${c.cle}"><span class="t-tete">${picto(c.picto)}<span class="t-nom">${h(c.nom)}</span></span><span class="t-visuel"></span><span class="t-pied"><span class="t-chiffre"></span><span class="t-legende">${h(c.legende)}</span></span></a></li>`,
  ).join('')}</ul>`
}

export async function remplirTuiles(cible: ParentNode): Promise<void> {
  await Promise.all(
    CAISSES.map(async (c) => {
      const m = await c.lire().catch(() => null)
      const a = cible.querySelector(`[data-caisse="${c.cle}"]`)
      if (!a || !m) return
      a.querySelector('.t-chiffre')!.textContent = m.texte
      if (m.legende) a.querySelector('.t-legende')!.textContent = m.legende
      a.querySelector('.t-visuel')!.innerHTML = visuel(c, m.valeur)
    }),
  )
}

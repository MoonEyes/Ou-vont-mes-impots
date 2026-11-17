// Sécurité sociale et protection sociale (site/data/secu/) : même visionneuse que le budget de l'État.
import { chargerSiPresent, type Noeud, type VueArbre } from '../donnees'
import { h, legendeStatuts, md, pct, STATUTS, sur100, traitStatut } from '../util'
import { rendreArbre } from './detail'

const VUES: VueArbre[] = [
  { cle: 'organismes2024', dossier: 'secu/arbre', libelle: 'Comptes des organismes 2024', millesime: 'Exécution 2024' },
  { cle: 'organismes2025', dossier: 'secu/arbre_2025', libelle: 'Comptes des organismes 2025', millesime: 'Exécution 2025' },
  { cle: 'protection2024', dossier: 'secu/cps', libelle: 'Protection sociale 2024 (DREES)', millesime: '2024' },
]

type NoeudSecu = Noeud & {
  tracabilite_pct?: number
  modes_md?: Record<string, number>
  mode?: string
  sources?: string[]
  destinataire?: string
  note?: string
  ecarts?: { source: string; md: number | null; libelle: string }[]
}
type RacineSecu = NoeudSecu & {
  sources_detail?: Record<string, { titre: string; url: string; millesime: string; licence: string }>
  methode?: string
  avertissement?: string
}

const DESTINATAIRES: Record<string, string> = {
  cnam: 'l’Assurance maladie',
  branche_atmp: 'la branche accidents du travail',
  cnav: 'l’Assurance retraite',
  cnaf: 'les Allocations familiales',
  cnsa: 'la branche autonomie',
  agirc_arrco: 'l’Agirc-Arrco',
  unedic: 'l’Unédic',
  cades: 'la CADES',
}

async function complement(n: Noeud, racine: Noeud): Promise<string> {
  const x = n as NoeudSecu
  const r = racine as RacineSecu
  const modes = x.modes_md ?? (x.mode ? { [x.mode]: x.md } : {})
  const total = Object.values(modes).reduce((s, v) => s + Math.abs(v), 0)
  const traceMd = Math.abs(modes.publie ?? 0) + Math.abs(modes.tableau_image ?? 0)
  const approcheMd = Math.abs(modes.derive ?? 0) + Math.abs(modes.ecart ?? 0)
  const parts: [keyof typeof STATUTS, number, string][] = [
    ['trace', traceMd, 'lu directement dans une source publiée (texte ou tableau)'],
    ['approche', approcheMd, 'déduit (part publiée × total, différence ou écart entre sources)'],
  ]
  const index = await chargerSiPresent<{ liens_affectation?: { noeuds: Record<string, string> } }>('secu/index.json')
  const destinataire = x.destinataire ?? Object.entries(index?.liens_affectation?.noeuds ?? {}).find(([, id]) => id === x.id)?.[0]
  return `
${
  total > 0
    ? `<div class="carte"><h2>Traçabilité de ce bloc</h2>
  <p>Sur 100 € de ce bloc, ${h(sur100(typeof x.tracabilite_pct === 'number' ? x.tracabilite_pct : (traceMd / total) * 100))} sont lus directement dans une source publiée.</p>
  ${legendeStatuts(['trace', 'approche'])}
  <div class="empile" aria-hidden="true">${parts.map(([s, v]) => `<span class="statut-${s}" data-l="${((v / total) * 100).toFixed(2)}"></span>`).join('')}</div>
  <ul class="legende-statuts">${parts
    .map(([s, v, t]) => `<li>${traitStatut(s)}<span><strong>${STATUTS[s].libelle}</strong> · ${h(md(v))} ${h(t)} (${h(pct((v / total) * 100))})</span></li>`)
    .join('')}</ul>
  ${x.note ? `<p class="aide">${h(x.note)}</p>` : ''}
  ${
    x.ecarts?.length
      ? `<p class="aide">Autres montants publiés pour ce bloc : ${x.ecarts.map((e) => `${h(e.libelle)} ${e.md === null ? '(autre vue)' : h(md(e.md))}`).join(' ; ')}.</p>`
      : ''
  }
</div>`
    : ''
}
${
  destinataire && DESTINATAIRES[destinataire]
    ? `<p>Une partie de tes cotisations et de ta CSG va à ${h(DESTINATAIRES[destinataire])} : <a href="#/calcul">calcule ta part</a>.</p>`
    : ''
}
${
  x.sources?.length && r.sources_detail
    ? `<details><summary>Sources de ce montant</summary><ul>${x.sources
        .map((k) => r.sources_detail![k])
        .filter(Boolean)
        .map((s) => `<li><a href="${h(s.url)}" rel="noopener noreferrer">${h(s.titre)}</a> (${h(s.millesime)}, ${h(s.licence)})</li>`)
        .join('')}</ul></details>`
    : ''
}
${n.id === 'racine' && r.avertissement ? `<p class="avertissement">${h(r.avertissement)}</p>` : ''}
<p class="aide">Deux comptabilités, jamais additionnées : les comptes des organismes (droits constatés) et les comptes de la protection sociale de la DREES (prestations, tous financeurs).</p>`
}

export function rendre(cible: HTMLElement, params: URLSearchParams) {
  return rendreArbre(cible, params, {
    page: '/explorer/secu',
    vues: VUES,
    ensemble: 'des dépenses de cette vue',
    complement,
    niveaux: { organisme: 'Organisme', branche: 'Branche', poste: 'Poste', sous_poste: 'Sous-poste', detail: 'Détail', secteur: 'Secteur', regime: 'Régime', risque: 'Risque', sous_risque: 'Sous-risque', groupe: 'Groupe', prestation: 'Prestation' },
  })
}

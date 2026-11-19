// Écran 4 : détail à profondeur libre (arbre chargé à la demande, fil d'Ariane, barres, Sankey).
import { choixLiens } from '../composants/choix'
import { dessinerSankey, ecranLarge } from '../composants/sankey'
import { blocTracabilite } from '../composants/tracabilite'
import { charger, deplier, type Noeud, trouverNoeud, type VueArbre, VUES_ARBRE } from '../donnees'
import { lien } from '../routeur'
import { appliquerLargeurs, barres, h, surligne, libelle, md, numeroProgramme, pct, source, sur100 } from '../util'

const NIVEAUX: Record<string, string> = {
  racine: 'Budget',
  grand_poste: 'Grand poste',
  mission: 'Mission',
  programme: 'Programme',
  action: 'Action',
  sous_action: 'Sous-action',
  titre: 'Titre (nature)',
  categorie: 'Catégorie (nature)',
}

let nettoyer: (() => void) | null = null

/** Paramètres d'une visionneuse d'arbre (budget de l'État, Sécurité sociale...). */
export interface ConfigArbre {
  page: string
  vues: VueArbre[]
  /** « du budget de l'État », « des dépenses sociales »... */
  ensemble: string
  /** compléments propres au nœud (traçabilité, liens) */
  complement?: (n: Noeud, racine: Noeud, vue: VueArbre) => Promise<string>
  niveaux?: Record<string, string>
}

const CONFIG_ETAT: ConfigArbre = {
  page: '/explorer/etat/detail',
  vues: VUES_ARBRE,
  ensemble: 'du budget de l’État',
  complement: async (n, _r, vue) => (vue.cle === 'execution2024' ? blocTracabilite(n.niveau, n.id, vue.millesime) : ''),
}

export function rendre(cible: HTMLElement, params: URLSearchParams) {
  return rendreArbre(cible, params, CONFIG_ETAT)
}

export async function rendreArbre(cible: HTMLElement, params: URLSearchParams, cfg: ConfigArbre) {
  nettoyer?.()
  nettoyer = null
  const vue = cfg.vues.find((v) => v.cle === params.get('m')) ?? cfg.vues[0]
  // Vue choisie transmise aux pages du programme (m), sauf la vue par défaut (adresse courte).
  const mVue = vue === cfg.vues[0] ? undefined : vue.cle
  const id = params.get('id') ?? params.get('n') ?? 'racine'
  const NIV = { ...NIVEAUX, ...(cfg.niveaux ?? {}) }
  const { noeud, chemin, racine } = await trouverNoeud(vue.dossier, id)
  const enfants = await Promise.all((noeud.enfants ?? []).map((e) => deplier(e)))
  const complet: Noeud = { ...noeud, enfants }
  const parent = chemin.length > 1 ? chemin[chemin.length - 2] : null
  const prog = noeud.niveau === 'programme' ? numeroProgramme(noeud.id) : null
  const tete = await charger<Noeud & { avertissement?: string; millesime?: string; source?: string }>(`${vue.dossier}/racine.json`)

  const ariane = `<nav class="fil-ariane" aria-label="Position dans l’arbre"><ol>${chemin
    .map((n, i) =>
      i === chemin.length - 1
        ? `<li aria-current="page">${h(libelle(n.nom))}</li>`
        : `<li><a href="${lien(cfg.page, { m: vue.cle, id: n.id === 'racine' ? undefined : n.id })}">${h(libelle(n.nom))}</a></li>`,
    )
    .join('')}</ol></nav>`

  const listeEnfants = enfants.length
    ? barres(
        enfants.map((e) => ({
          nom: libelle(e.nom),
          valeur: e.md,
          texte: md(e.md),
          lien: e.enfants || e.fichier ? lien(cfg.page, { m: vue.cle, id: e.id }) : undefined,
          detail: `${sur100((e.md / racine.md) * 100)} sur 100 € ${cfg.ensemble} · ${pct(noeud.md > 0 ? (e.md / noeud.md) * 100 : 0)} de ce bloc${
            e.niveau === 'programme' && numeroProgramme(e.id) ? ` · programme ${numeroProgramme(e.id)}` : ''
          }`,
        })),
        undefined,
        `Répartition de ${libelle(noeud.nom)}`,
      )
    : '<p>Ce bloc n’est pas détaillé davantage dans la source.</p>'

  const alternative = enfants.length
    ? `<details><summary>Version texte du diagramme (deux niveaux)</summary><ul>${enfants
        .map(
          (e) =>
            `<li>${h(libelle(e.nom))} : ${h(md(e.md))}${
              e.enfants?.length
                ? `<ul>${[...e.enfants]
                    .sort((a, b) => b.md - a.md)
                    .map((p) => `<li>${h(libelle(p.nom))} : ${h(md(p.md))}</li>`)
                    .join('')}</ul>`
                : ''
            }</li>`,
        )
        .join('')}</ul></details>`
    : ''

  cible.innerHTML = `
<h1>${h(libelle(noeud.nom))}</h1>
${choixLiens({ etiquette: 'Vue du budget', liens: cfg.vues.map((x) => ({ href: lien(cfg.page, { m: x.cle }), libelle: x.libelle, courant: x === vue })) })}
${ariane}
<div class="carte" data-cle>
  <p class="grand-chiffre">${surligne(md(noeud.md))}</p>
  <p class="sous-chiffre">${h(NIV[noeud.niveau] ?? noeud.niveau)}${prog ? ` ${h(prog)}` : ''} · ${h(sur100((noeud.md / racine.md) * 100))} sur 100 € ${h(cfg.ensemble)}${
    parent ? ` · ${h(pct(parent.md > 0 ? (noeud.md / parent.md) * 100 : 0))} de « ${h(libelle(parent.nom))} »` : ''
  }</p>
  ${tete.avertissement ? `<p class="avertissement">${h(tete.avertissement)}</p>` : ''}
  ${source(tete.source ?? '', tete.millesime ?? vue.millesime)}
</div>
${
  prog
    ? `<div class="actions"><a class="bouton" href="${lien('/beneficiaires/programme', { p: prog, m: mVue })}">Le programme ${h(prog)} en détail</a><a class="bouton" href="${lien('/beneficiaires', { p: prog, m: mVue })}">Qui reçoit l’argent du programme ${h(prog)}</a><a class="bouton" href="${lien('/decisions/realisations', { p: prog, m: mVue })}">Ce qui a été fait (programme ${h(prog)})</a><a class="bouton" href="${lien('/decisions/votes', { p: prog, m: mVue })}">Votes et mouvements (programme ${h(prog)})</a></div>${
        mVue ? `<p class="aide">Ces pages montrent les montants de leur propre millésime, indiqué sur chacune, et non ceux de la vue « ${h(vue.libelle)} ».</p>` : ''
      }`
    : ''
}
<h2>Ce que contient ce bloc</h2>
<div id="sankey-zone"></div>
${listeEnfants}
${alternative}
<div id="trac"></div>`

  const zone = cible.querySelector('#sankey-zone') as HTMLElement
  if (enfants.length > 1 && ecranLarge()) {
    zone.innerHTML = `<div class="sankey" role="img" aria-label="Diagramme de flux de ${h(libelle(noeud.nom))} vers ses sous-blocs ; le même contenu est donné en liste ci-dessous."></div>`
    const div = zone.firstElementChild as HTMLElement
    // Le conteneur doit être dans le document pour avoir une taille : on attend l'insertion.
    const tenter = (essais: number) => {
      if (div.isConnected && div.clientWidth > 0) {
        dessinerSankey(div, complet, racine.md)
          .then((f) => (nettoyer = f))
          .catch(() => (zone.innerHTML = ''))
      } else if (essais > 0) window.setTimeout(() => tenter(essais - 1), 60)
    }
    window.setTimeout(() => tenter(20), 0)
  }
  if (cfg.complement) {
    const z = cible.querySelector('#trac') as HTMLElement
    z.innerHTML = await cfg.complement(noeud, tete, vue)
    appliquerLargeurs(z)
  }
}

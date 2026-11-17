// Écran 4 : détail à profondeur libre (arbre chargé à la demande, fil d'Ariane, barres, Sankey).
import { dessinerSankey, ecranLarge } from '../composants/sankey'
import { blocTracabilite } from '../composants/tracabilite'
import { charger, deplier, type Noeud, trouverNoeud, VUES_ARBRE, vueArbre } from '../donnees'
import { lien } from '../routeur'
import { appliquerLargeurs, barres, h, libelle, md, numeroProgramme, pct, source, sur100 } from '../util'

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

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  nettoyer?.()
  nettoyer = null
  const vue = vueArbre(params.get('m'))
  const id = params.get('id') ?? 'racine'
  const { noeud, chemin, racine } = await trouverNoeud(vue.dossier, id)
  const enfants = await Promise.all((noeud.enfants ?? []).map((e) => deplier(e)))
  const complet: Noeud = { ...noeud, enfants }
  const parent = chemin.length > 1 ? chemin[chemin.length - 2] : null
  const prog = noeud.niveau === 'programme' ? numeroProgramme(noeud.id) : null
  const tete = await charger<Noeud & { avertissement?: string; millesime?: string; source?: string }>(`${vue.dossier}/racine.json`)

  const ariane = `<nav class="fil-ariane" aria-label="Fil d’Ariane"><ol>${chemin
    .map((n, i) =>
      i === chemin.length - 1
        ? `<li aria-current="page">${h(libelle(n.nom))}</li>`
        : `<li><a href="${lien('/detail', { m: vue.cle, id: n.id === 'racine' ? undefined : n.id })}">${h(libelle(n.nom))}</a></li>`,
    )
    .join('')}</ol></nav>`

  const listeEnfants = enfants.length
    ? barres(
        enfants.map((e) => ({
          nom: libelle(e.nom),
          valeur: e.md,
          texte: md(e.md),
          lien: e.enfants || e.fichier ? lien('/detail', { m: vue.cle, id: e.id }) : undefined,
          detail: `${sur100((e.md / racine.md) * 100)} sur 100 € du budget · ${pct(noeud.md > 0 ? (e.md / noeud.md) * 100 : 0)} de ce bloc${
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
<div class="bascule" role="group" aria-label="Vue du budget">
  ${VUES_ARBRE.map((x) => `<a class="bouton" href="${lien('/detail', { m: x.cle })}"${x === vue ? ' aria-current="true"' : ''}>${h(x.libelle)}</a>`).join('')}
</div>
${ariane}
<div class="carte">
  <p class="grand-chiffre">${h(md(noeud.md))}</p>
  <p class="sous-chiffre">${h(NIVEAUX[noeud.niveau] ?? noeud.niveau)}${prog ? ` ${h(prog)}` : ''} · ${h(sur100((noeud.md / racine.md) * 100))} sur 100 € du budget de l’État${
    parent ? ` · ${h(pct(parent.md > 0 ? (noeud.md / parent.md) * 100 : 0))} de « ${h(libelle(parent.nom))} »` : ''
  }</p>
  ${tete.avertissement ? `<p class="avertissement">${h(tete.avertissement)}</p>` : ''}
  ${source(tete.source ?? '', tete.millesime ?? vue.millesime)}
</div>
${
  prog
    ? `<div class="actions"><a class="bouton" href="${lien('/concret', { p: prog })}">Concrètement</a><a class="bouton" href="${lien('/beneficiaires', { p: prog })}">Qui reçoit l’argent</a><a class="bouton" href="${lien('/realisations', { p: prog })}">Ce qui a été fait</a></div>`
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
        dessinerSankey(div, complet)
          .then((f) => (nettoyer = f))
          .catch(() => (zone.innerHTML = ''))
      } else if (essais > 0) window.setTimeout(() => tenter(essais - 1), 60)
    }
    window.setTimeout(() => tenter(20), 0)
  }
  if (vue.cle === 'execution2024') {
    const t = await blocTracabilite(noeud.niveau, noeud.id, tete.millesime ?? vue.millesime)
    const z = cible.querySelector('#trac') as HTMLElement
    z.innerHTML = t
    appliquerLargeurs(z)
  }
}

// Écran 3 : où va l'argent de l'État « sur 100 € », avec la part empruntée.
import { billet, FAMILLES_TOURNANTES, type Part, partsAdministrations } from '../composants/billet'
import { eurosNonPublies } from '../composants/chiffres-site'
import { blocTracabilite } from '../composants/tracabilite'
import { charger, chargerSiPresent, deplier, type Noeud, urlDonnee, VUES_ARBRE, vueArbre } from '../donnees'
import { LIBELLE_ADMINISTRATION } from '../calcul/destinataires'
import { ORDRE_ADMIN, parAdministration, sur100Entiers } from '../calcul/repartition'
import { session } from '../etat'
import { lien } from '../routeur'
import { retourResultat } from '../composants/retour-resultat'
import { absent, appliquerLargeurs, barres, eur, h, libelle, lireLesMotifs, md, pct, source, sur100, surligne } from '../util'

interface Deficit {
  etat: { lecture: string; perimetre: string; comptabilite: string; annees: Record<string, { part_empruntee: number; solde_budgetaire_md: number }> }
  administrations_publiques: { comptabilite: string; annees: Record<string, { part_empruntee: number; B9_md: number; TE_md: number }> }
  source: string
  avertissement: string
}

/** Totaux publiés par pipeline/millesimes.py (site/data/millesimes/index.json, contrat 2.48), en euros. */
export interface Millesimes {
  comparaison?: {
    totaux?: { execution_2024_affichee_eur: number; execution_2024_plrg_eur: number; execution_2025_plrg_eur: number; ecart_methode_2024_eur: number }
  }
}

/** Vue de l'exécution 2025 (dépenses constatées, grand poste > mission > programme). */
export const VUE_2025 = 'execution2025'
export const FICHIER_MILLESIMES = 'millesimes/index.json'

const nf2 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
/** Milliards d'euros à deux décimales (502,96 Md€) : l'écart entre les deux méthodes se lit au centième. */
export const md2 = (euros: number) => `${nf2.format(euros / 1e9)} Md€`

/** Lien vers un fichier de données : absolu sur le site publié, « ./data/… » au prérendu (réécrit vers la racine) et en développement. */
export function lienDonnee(chemin: string): string {
  const u = urlDonnee(chemin)
  return u.startsWith('/') ? u : `./${u}`
}

/** Phrase de la vue 2025 : où elle s'arrête et pourquoi. */
export const PHRASE_NIVEAU_2025 =
  'Cette vue s’arrête au niveau du programme, car la loi relative aux résultats de la gestion publie les dépenses constatées par programme et non par action ; le niveau de l’action viendra du budget vert du projet de loi de finances 2027, quand il sera publié en données ouvertes.'

/**
 * Écart de méthode entre l'exécution 2024 affichée (budget vert retraité) et les lois relatives aux résultats de la gestion,
 * publié tel quel : aucun des deux montants ne corrige l'autre. Vue 2024 : chiffres 2024 seulement.
 */
export function blocMethode(cle: string, idx: Millesimes | null): string {
  const t = idx?.comparaison?.totaux
  if (!t || (cle !== 'execution2024' && cle !== VUE_2025)) return ''
  const affichee = md2(t.execution_2024_affichee_eur)
  const constatee2024 = md2(t.execution_2024_plrg_eur)
  const phrase =
    cle === VUE_2025
      ? `Cette vue reprend les dépenses constatées publiées avec la loi relative aux résultats de la gestion 2025 (${md2(t.execution_2025_plrg_eur)}) ; la même méthode donne ${constatee2024} pour 2024, alors que la vue « Dépensé en 2024 » affiche ${affichee}, car elle reprend le budget vert du projet de loi de finances 2026, retraité au format de ce projet par la direction du budget : l’écart de ${md2(t.ecart_methode_2024_eur)} tient à la méthode, et les deux montants sont publiés sans que l’un corrige l’autre.`
      : `Cette vue affiche ${affichee} pour 2024, car elle reprend le budget vert du projet de loi de finances 2026, retraité au format de ce projet par la direction du budget ; les dépenses constatées publiées avec la loi relative aux résultats de la gestion 2024 donnent ${constatee2024} pour la même année : l’écart de ${md2(t.ecart_methode_2024_eur)} tient à la méthode, et les deux montants sont publiés sans que l’un corrige l’autre.`
  return `<section class="carte" aria-labelledby="titre-methode">
  <h2 id="titre-methode">Deux méthodes pour les dépenses réelles</h2>
  <p>${h(phrase)}</p>
  <p><a href="${h(lienDonnee(FICHIER_MILLESIMES))}">L’écart de méthode grand poste par grand poste (fichier de données, rubrique « comparaison »)</a></p>
</section>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const vue = vueArbre(params.get('m'))
  const vues = VUES_ARBRE.filter((v) => v.cle !== 'nature2025')
  const v = vues.includes(vue) ? vue : vues[0]
  const en2025 = v.cle === VUE_2025
  // Seuls l'arbre et la part empruntée retiennent l'affichage ; les blocs « deux méthodes », « jusqu'où on suit
  // l'argent » et la traçabilité (millesimes/index.json, tracabilite/resume.json) se complètent ensuite.
  const [racine, deficit] = await Promise.all([charger<Noeud>(`${v.dossier}/racine.json`), chargerSiPresent<Deficit>('deficit.json')])
  const total = racine.md
  const postes = racine.enfants ?? []
  const emprunt = deficit?.etat.annees[racine.millesime ?? v.millesime]
  const annees = deficit ? Object.keys(deficit.administrations_publiques.annees).sort() : []
  const derniere = annees[annees.length - 1]
  const apu = derniere ? deficit!.administrations_publiques.annees[derniere] : null

  // Ce que tu verses (écran 2), réparti par administration selon les destinataires de chaque prélèvement.
  const lignes = session.complet?.lignes ?? session.resultat?.prelevements.filter((l) => l.inclus_dans_total_paye) ?? []
  const parAdmin = parAdministration(lignes)
  const s100Admin = sur100Entiers(parAdmin)
  const totalPaye = session.complet?.total.central ?? Object.values(parAdmin).reduce((a, b) => a + b, 0)
  const ir = parAdmin.Etat ?? 0

  // Le billet de l'État : une part par grand poste, chacune ouvre ses missions un niveau plus bas.
  const an = racine.millesime ?? v.millesime
  const periode = v.periode ?? an
  const partsPostes: Part[] = postes.map((p, i) => ({
    nom: libelle(p.nom),
    valeur: p.md,
    texte: sur100((p.md / total) * 100),
    famille: FAMILLES_TOURNANTES[i % FAMILLES_TOURNANTES.length],
    lien: lien('/explorer/etat', { m: v.cle, poste: p.id }),
    detail: md(p.md),
  }))
  const choisi = postes.find((p) => p.id === params.get('poste'))
  const ouvert = choisi ? await deplier(choisi) : null
  const missions = (ouvert?.enfants ?? []).filter((e) => e.md > 0)
  const partChoisie = choisi ? (choisi.md / total) * 100 : 0
  const nf1 = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 })
  const niveauBas =
    choisi && missions.length
      ? `<section aria-labelledby="titre-niveau">
<h2 id="titre-niveau" class="titre-niveau">Un niveau plus bas : ${h(libelle(choisi.nom))} (${h(md(choisi.md))}), mission par mission</h2>
${billet(
  missions.map((e, i) => ({
    nom: libelle(e.nom),
    valeur: e.md,
    texte: sur100((e.md / total) * 100),
    famille: FAMILLES_TOURNANTES[(i + 2) % FAMILLES_TOURNANTES.length],
    lien: lien('/explorer/etat/detail', { m: v.cle, id: e.id }),
    detail: md(e.md),
  })),
  { etiquette: `${libelle(choisi.nom)} : ${sur100(partChoisie)} sur 100 € dépensés par l’État, découpés par mission`, talon: { grand: nf1.format(partChoisie), petit: 'euros' }, legendes: missions.length <= 4, base: partChoisie },
)}
<ul class="liste-niveau">${missions.map((e) => `<li><a href="${lien('/explorer/etat/detail', { m: v.cle, id: e.id })}">${h(libelle(e.nom))}</a> : ${h(sur100((e.md / total) * 100))} sur 100 €, ${h(md(e.md))}</li>`).join('')}</ul>
</section>`
      : `<p class="aide">Chaque part se clique pour descendre d’un niveau : l’État, puis un grand poste, puis une mission. La liste « Les grands postes » plus bas donne les mêmes montants en texte.</p>`
  // Vue 2025 : le détail du budget suit le millésime (paramètre m) ; les pages d'un programme n'existent pas encore pour 2025.
  const noteProgrammes = en2025
    ? `<p class="aide" id="programmes-2025">Le détail du budget, mission par mission puis programme par programme, reste sur 2025. Les pages consacrées à un programme (nature de la dépense, bénéficiaires, réalisations, votes) ne sont pas encore construites pour 2025 : elles portent sur les années publiées par leurs sources, indiquées sur chaque page.</p>`
    : ''
  const perso = Object.keys(s100Admin).length
    ? `<ul class="ruban" aria-label="Rappel : sur 100 € que tu verses"><li class="r-tete">Tes 100 € versés</li>${partsAdministrations(s100Admin, ORDRE_ADMIN)
        .map((p) => `<li class="${p.famille === 'nonpub' ? 'r-nonpub' : `f-${p.famille}`}${p.famille === 'etat' ? ' r-actif' : ''}" data-f="${p.valeur}"><span>${p.famille === 'etat' ? `État : ${h(p.texte)}` : h(p.texte)}</span><span class="visuellement-cache"> ${h(p.nom)}</span></li>`)
        .join('')}</ul><p class="aide">Tu as ouvert la part de l’État. Voici ses 100 € à lui :</p>`
    : ''
  const blocSuivi = (nonPub: Awaited<ReturnType<typeof eurosNonPublies>>) =>
    nonPub && nonPub.millesime === an
      ? `<section class="carte carte-principale" aria-labelledby="titre-suivi">
  <h2 id="titre-suivi">Jusqu’où on suit l’argent</h2>
  <div class="jauge" aria-hidden="true"><span class="statut-trace" data-l="${100 - nonPub.euros}"></span><span class="statut-nonpub" data-l="${nonPub.euros}"></span></div>
  <ul class="deux-chiffres"><li><strong>${100 - nonPub.euros} €</strong> tracés jusqu’à un destinataire</li><li><strong>${nonPub.euros} €</strong> sans destinataire publié</li></ul>
  <p>Ces ${nonPub.euros} € ont bien été dépensés. Les documents publics ne disent pas qui les a reçus.</p>
  <p><a href="#/methode/tracabilite">Voir ce qui manque</a></p>
</section>`
      : ''

  cible.innerHTML = `
<div class="entete-section">
  <div>
    <h1>Le budget de l’État, sur 100 € dépensés</h1>
    <p class="chapeau">Ici, ce n’est plus ton argent : c’est toute la dépense de l’État, quelle que soit la personne qui la paie. ${ir > 0 ? 'Ta part est en bas de page.' : `Pour voir ta part, <a href="${lien('/')}">calcule-la depuis l’accueil</a>.`}</p>
    <p class="chapeau">Le budget de l’État (${h(md(total))}, ${h(periode)}) découpé en grands postes, ramené à 100 €. Les remboursements et dégrèvements d’impôts ne sont pas comptés : c’est de l’argent rendu, pas dépensé.</p>
    ${en2025 ? `<p class="chapeau" id="niveau-2025">${h(PHRASE_NIVEAU_2025)}</p>` : ''}
  </div>
  <div class="bascule" role="group" aria-label="Millésime">
    ${vues.map((x) => `<a class="bouton" href="${lien('/explorer/etat', { m: x.cle })}"${x === v ? ' aria-current="true"' : ''}>${h(x.libelle)}</a>`).join('')}
  </div>
</div>
${retourResultat()}
${perso}
${billet(partsPostes, { etiquette: `Billet de 100 € dépensés par l’État en grands postes (${periode})` })}
${niveauBas}
${noteProgrammes}
<div id="bloc-methode"></div>
<div class="colonnes c-8-4">
  <div>
    <h2>Les grands postes</h2>
    <div class="carte">
      <p class="aide">${h(periode)}, ramené à 100 €.</p>
      ${barres(
        postes.map((p) => ({
          nom: libelle(p.nom),
          valeur: p.md,
          texte: sur100((p.md / total) * 100),
          lien: lien('/explorer/etat/detail', { m: v.cle, id: p.id }),
          detail: md(p.md),
        })),
        undefined,
        'Grands postes, en euros sur 100 €',
      )}
      ${source(racine.source ?? '', racine.millesime)}
    </div>
  </div>
  <div>
    <div id="bloc-suivi"></div>
    ${lireLesMotifs()}
  </div>
</div>
<h2>D’où vient cet argent</h2>
${
  emprunt
    ? `<div class="carte" data-cle>
  <div class="empile" aria-hidden="true"><span class="recettes-seg" data-l="${(100 - emprunt.part_empruntee * 100).toFixed(2)}"></span><span class="emprunt-seg" data-l="${(emprunt.part_empruntee * 100).toFixed(2)}"></span></div>
  <p>Sur 100 € dépensés par l’État (${h(md(total))} au total) : <strong class="texte-accent">${h(sur100(100 - emprunt.part_empruntee * 100))}</strong> venaient des recettes de l’année, <strong class="texte-emprunt">${surligne(sur100(emprunt.part_empruntee * 100))}</strong> ont été empruntés (${h(periode)}).</p>
</div>`
    : absent('Part empruntée non disponible pour ce millésime.')
}
${
  ir > 0
    ? `<div class="carte"><h2>Et ce que tu verses ?</h2><p>Sur les ${h(eur(totalPaye))} que ton foyer verse chaque année (écran 2, valeur centrale), environ :</p><ul>${Object.entries(parAdmin)
        .sort((a, b) => b[1] - a[1])
        .map(
          ([a, v]) =>
            `<li>${h(eur(v))}, soit ${s100Admin[a] ?? 0} € sur 100 €, ${a === 'Plusieurs' ? 'sans destinataire publié' : `pour : ${h(LIBELLE_ADMINISTRATION[a as 'Etat'])}`}</li>`,
        )
        .join('')}</ul><p class="aide">La part qui va à l’État (${h(eur(ir))}) n’est pas fléchée vers un poste du budget : aucun document public ne dit quel poste elle finance, le site ne la répartit donc pas entre les postes. Le reste va à la Sécurité sociale et aux collectivités.</p></div>`
    : ''
}
${
  emprunt && deficit
    ? `<details class="carte"><summary>Comment est calculée la part empruntée ?</summary>
  <p>${h(deficit.etat.lecture)}</p>
  <p>Solde budgétaire ${h(racine.millesime ?? v.millesime)} : ${h(md(emprunt.solde_budgetaire_md))} (comptabilité ${h(deficit.etat.comptabilite)}). ${h(deficit.etat.perimetre)}</p>
  ${
    apu && derniere
      ? `<p>Pour l’ensemble des administrations publiques (État, Sécurité sociale, collectivités), en comptabilité nationale, la part empruntée est de ${h(pct(apu.part_empruntee * 100))} en ${h(derniere)} (déficit ${h(md(-apu.B9_md))} pour ${h(md(apu.TE_md))} de dépenses). ${h(deficit.avertissement)}</p>`
      : ''
  }
  ${source(deficit.source)}
</details>`
    : ''
}
<div id="trac"></div>
<div class="actions"><a class="bouton bouton-principal" href="${lien('/explorer/etat/detail', { m: v.cle })}">Voir le détail, aussi loin que tu veux</a><a class="bouton" href="#/explorer/recettes">D’où vient l’argent ?</a></div>`
  const poser = (id: string, html: string) => {
    const z = cible.querySelector<HTMLElement>(id)
    if (z) {
      z.innerHTML = html
      appliquerLargeurs(z)
    }
  }
  return {
    suite: Promise.all([
      (v.cle === 'execution2024' || en2025 ? chargerSiPresent<Millesimes>(FICHIER_MILLESIMES) : Promise.resolve(null)).then((m) => poser('#bloc-methode', blocMethode(v.cle, m))),
      eurosNonPublies().then((n) => poser('#bloc-suivi', blocSuivi(n))),
      blocTracabilite('racine', 'racine', racine.millesime ?? v.millesime).then((t) => poser('#trac', t)),
    ]).then(() => undefined),
  }
}

// Méthode : traçabilité. D'où vient chaque montant, et quelle part de l'argent a un destinataire publié.
import { blocTracabilite } from '../composants/tracabilite'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { barres, h, legendeStatuts, libelle, pct, source, sur100, surligne } from '../util'
import { enCours } from './dette'

interface Resume {
  millesime: string
  source: string
  methode: string
  limites: string[]
  global: { taux_tracabilite_pct: number }
  grands_postes: { id: string; nom: string; taux_tracabilite_pct?: number; parts?: Record<string, { pct: number }> }[]
}

export async function rendre(cible: HTMLElement) {
  const r = await chargerSiPresent<Resume>('tracabilite/resume.json')
  if (!r) {
    cible.innerHTML = enCours('Traçabilité : d’où vient chaque montant', 'Part de l’argent dont le destinataire est publié, bloc par bloc.')
    return
  }
  const taux = (g: Resume['grands_postes'][number]) =>
    g.taux_tracabilite_pct ?? (g.parts ? 100 - (g.parts.non_publie?.pct ?? 0) : 0)
  cible.innerHTML = `
<h1>Traçabilité : d’où vient chaque montant</h1>
<p class="chapeau">Chaque montant du site porte sa source et son année. Pour le budget de l’État, le site mesure aussi quelle part de l’argent va à un destinataire connu.</p>
${legendeStatuts()}
<p class="carte" data-cle>Taux de traçabilité ${h(r.millesime)} : <strong>${h(pct(r.global.taux_tracabilite_pct, 2))}</strong>. Sur 100 € du budget de l’État, ${surligne(sur100(r.global.taux_tracabilite_pct))} vont à un destinataire connu : bénéficiaire nommé, catégorie d’agents publiée, opérateur financé ou porteurs de la dette. Une part « non publiée » signifie que le destinataire n’est pas publié en données ouvertes ; elle ne dit rien de la régularité ni de l’utilité de la dépense.</p>
<p>Les subventions aux opérateurs de l’État sont comptées à partir du jaune budgétaire : <a href="#/explorer/operateurs">voir les opérateurs et leur statut de traçabilité</a>.</p>
<div id="trac-global"></div>
<h2>Par grand poste</h2>
${barres(
  [...r.grands_postes].sort((a, b) => taux(b) - taux(a)).map((g) => ({
    nom: libelle(g.nom),
    valeur: taux(g),
    texte: `${sur100(taux(g))} sur 100 €`,
    lien: lien('/explorer/etat/detail', { id: g.id }),
    detail: `${pct(taux(g))} avec un destinataire connu`,
  })),
  100,
  'Part tracée par grand poste',
  -1,
)}
<h2>Méthode</h2>
<p>${h(r.methode)}</p>
<ul>${r.limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul>
${source(r.source, r.millesime)}
<p>Autres traçabilités : <a href="#/explorer/secu">Sécurité sociale (part lue directement dans les comptes publiés)</a>.</p>`
  ;(cible.querySelector('#trac-global') as HTMLElement).innerHTML = await blocTracabilite('racine', 'racine', r.millesime)
}

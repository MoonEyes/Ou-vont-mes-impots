// La France et l'Union européenne (site/data/ue/) : contribution, usage, retours, bénéficiaires nommés.
import { partPersonnelle } from '../composants/hub'
import { DEPARTEMENTS } from '../departements'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { absent, barres, eurLisible, h, md, pct, source, sur100, surligne } from '../util'

interface Contribution {
  millesime: string
  source: string
  avertissement: string
  psr_ue: { annee: number; md: number; eur_sur_100_budget_etat: number; source: string }
  serie_psr_ue: { annee: number; vote_md: number; execute_md: number; statut: string }[]
  usage: { rubriques: { code: string; nom: string; contribution_france_md: number; eur_sur_100: number }[]; source: string }
  next_generation_eu?: { total_md: number; note: string }
}
interface Retours {
  source: string
  lecture: string
  limites?: string[]
  annees: { annee: number; retours_md: number; solde_net_comptable_md: number; contribution_comptable_md: number; solde_net_pct_rnb: number }[]
  beneficiaires_nommes?: { nombre: number; total_nomme_eur: number; total_eur: number; part_nommee: number }
}
interface BenefDep {
  nom: string
  millesime: string
  source: string
  totaux: Record<string, { total_eur: number; nomme_eur: number; non_nomme_eur: number }>
  beneficiaires: { siren: string; denomination: string; montant_eur: number; detail: [string, number, string, number, number][] }[]
}

const NOMS_SOURCES: Record<string, string> = {
  kohesio_2014_2020: 'Fonds de cohésion 2014-2020 (Kohesio)',
  kohesio_2021_2027: 'Fonds de cohésion 2021-2027 (Kohesio)',
  fts: 'Gestion directe de la Commission (FTS 2023-2025)',
  horizon: 'Recherche Horizon Europe',
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const [c, r] = await Promise.all([chargerSiPresent<Contribution>('ue/contribution.json'), chargerSiPresent<Retours>('ue/retours.json')])
  const dep = params.get('dep')
  const b = dep ? await chargerSiPresent<BenefDep>(`ue/beneficiaires/${dep}.json`) : null
  if (!c) {
    cible.innerHTML = `<h1>La France et l’Union européenne</h1>${absent('Données en cours d’intégration.')}`
    return
  }
  cible.innerHTML = `
<h1>La France et l’Union européenne</h1>
<p class="chapeau">Ce que la France verse au budget de l’Union, à quoi sert ce budget, et ce qui revient en France.</p>
<div class="carte" data-cle>
  <p class="grand-chiffre">${surligne(md(c.psr_ue.md))}</p>
  <p class="sous-chiffre">versés au budget de l’Union en ${c.psr_ue.annee} (prélèvement sur recettes), soit ${h(sur100(c.psr_ue.eur_sur_100_budget_etat))} sur 100 € du budget de l’État.</p>
  ${source(c.psr_ue.source)}
</div>
<h2>À quoi sert le budget européen</h2>
<p class="avertissement">${h(c.avertissement)}</p>
${barres(
  c.usage.rubriques.map((x) => ({ nom: x.nom, valeur: x.eur_sur_100, texte: sur100(x.eur_sur_100), detail: `${md(x.contribution_france_md)} de la contribution française` })),
  undefined,
  'Sur 100 € versés par la France',
)}
${source(c.usage.source)}
${
  r
    ? `<h2>Ce qui revient en France</h2>
<div class="tableau-defile"><table><caption>Milliards d’euros (hors plan de relance)</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Versé</th><th scope="col" class="nombre">Revenu en France</th><th scope="col" class="nombre">Solde net</th></tr></thead>
<tbody>${r.annees
        .map((a) => `<tr><th scope="row">${a.annee}</th><td class="nombre">${h(md(a.contribution_comptable_md))}</td><td class="nombre">${h(md(a.retours_md))}</td><td class="nombre">${h(md(a.solde_net_comptable_md))}</td></tr>`)
        .join('')}</tbody></table></div>
<p class="aide">${h(r.lecture)}</p>${r.limites?.length ? `<ul class="aide">${r.limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul>` : ''}${source(r.source)}`
    : ''
}
<h2>Qui reçoit les fonds européens près de chez toi</h2>
${
  r?.beneficiaires_nommes
    ? `<p>${h(String(r.beneficiaires_nommes.nombre))} organismes nommés reçoivent ${h(eurLisible(r.beneficiaires_nommes.total_nomme_eur))}, soit ${h(pct(r.beneficiaires_nommes.part_nommee * 100, 0))} des fonds suivis. Seules des personnes morales sont nommées.</p>`
    : ''
}
<form id="dep-ue"><label for="dep-ue-choix">Département</label><select id="dep-ue-choix"><option value="">Choisir</option>${DEPARTEMENTS.map(
    ([k, n]) => `<option value="${k}"${k === dep ? ' selected' : ''}>${k} ${h(n)}</option>`,
  ).join('')}</select></form>
${
  b
    ? `<h3>${h(b.nom)}</h3><ul>${Object.entries(b.totaux)
        .map(([k, t]) => `<li>${h(NOMS_SOURCES[k] ?? k)} : ${h(eurLisible(t.total_eur))}, dont ${h(eurLisible(t.nomme_eur))} à des bénéficiaires nommés</li>`)
        .join('')}</ul>
<div class="tableau-defile"><table><caption>Principaux bénéficiaires</caption><thead><tr><th scope="col">Bénéficiaire</th><th scope="col" class="nombre">Montant</th></tr></thead><tbody>${b.beneficiaires
        .slice(0, 20)
        .map((x) => `<tr><td>${h(x.denomination)}</td><td class="nombre">${h(eurLisible(x.montant_eur))}</td></tr>`)
        .join('')}</tbody></table></div>${source(b.source, b.millesime)}`
    : dep
      ? absent('Pas de données pour ce département.')
      : ''
}
<p class="liens-sortie"><a href="#/explorer/fonds-europeens">Ce que l’Union européenne finance en France : les fonds européens par fonds, région et thème</a></p>
<p class="liens-sortie"><a href="#/explorer/etat">Le budget de l’État, dont la contribution européenne</a></p>
${partPersonnelle()}`
  cible.querySelector<HTMLSelectElement>('#dep-ue-choix')?.addEventListener('change', (e) => {
    location.hash = lien('/explorer/ue', { dep: (e.target as HTMLSelectElement).value })
  })
}

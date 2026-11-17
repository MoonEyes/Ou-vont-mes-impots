// Contrôle, représentation d'intérêts et aides aux entreprises (site/data/controle/).
import { DEPARTEMENTS } from '../departements'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { absent, entier, eurLisible, h, md, source } from '../util'
import { enCours } from './dette'

interface Index {
  source: string
  millesime: string
  controle: { programmes: { publications_rattachees: number; neb: number }; collectivites: { publications_rattachees: number }; couverture_ccomptes: { lecture: string } }
  influence: { organisations_publiees: number; annee_reference: number; depenses_annee_reference: { organisations_declarantes: number; depense_min_eur: number; activites: number } }
  regle_personnes: string
}
interface Aides {
  source: string
  avertissement: string
  estimations: { id: string; auteur: string; annee_donnees: number | null; annee_donnees_note?: string; publication: string; variante?: string; md: number; md_haut?: number; perimetre: string }[]
  fourchette: { basse_md: number; haute_md: number; note: string }
}
interface Pub {
  titre: string
  date: string
  type: string
  juridiction: string
  url: string
  url_document?: string
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const dep = params.get('dep')
  const [idx, aides, min, depPubs] = await Promise.all([
    chargerSiPresent<Index>('controle/index.json'),
    chargerSiPresent<Aides>('controle/aides_entreprises.json'),
    chargerSiPresent<{ source: string; cibles: { fonction: string; cible: string | null; actions: number; organisations: number }[] }>('controle/lobbying/ministeres.json'),
    dep ? chargerSiPresent<{ source: string; publications: Pub[] }>(`controle/publications/collectivites/${dep}.json`) : Promise.resolve(null),
  ])
  if (!idx) {
    cible.innerHTML = enCours('Contrôle, représentation d’intérêts et aides aux entreprises', 'Rapports des juridictions financières, représentants d’intérêts, aides aux entreprises.')
    return
  }
  const cibles = (min?.cibles ?? []).filter((c) => c.cible).sort((a, b) => b.actions - a.actions).slice(0, 8)
  cible.innerHTML = `
<h1>Contrôle, représentation d’intérêts et aides aux entreprises</h1>
<p class="chapeau">Qui contrôle l’usage de l’argent public, quelles organisations déclarent des actions de représentation d’intérêts auprès des décideurs publics, et ce que les études publiées comptent comme aides aux entreprises.</p>
<h2>Les rapports de contrôle</h2>
<p>${h(entier(idx.controle.collectivites.publications_rattachees))} rapports des chambres régionales des comptes rattachés à une collectivité ; ${h(entier(idx.controle.programmes.neb))} notes d’exécution budgétaire de la Cour des comptes rattachées aux missions de l’État.</p>
<form><label for="dep-controle">Rapports sur les collectivités d’un département</label><select id="dep-controle"><option value="">Choisir</option>${DEPARTEMENTS.map(
    ([k, n]) => `<option value="${k}"${k === dep ? ' selected' : ''}>${k} ${h(n)}</option>`,
  ).join('')}</select></form>
${
  depPubs
    ? `<ul class="lignes">${depPubs.publications
        .slice(0, 25)
        .map((p) => `<li><span><a href="${h(p.url_document ?? p.url)}" rel="noopener noreferrer">${h(p.titre)}</a></span><span class="montant">${h(p.date)}</span><span class="dest">${h(p.type)} · ${h(p.juridiction)}</span></li>`)
        .join('')}</ul>${source(depPubs.source)}`
    : dep
      ? absent('Aucun rapport rattaché à ce département.')
      : ''
}
<p class="aide">${h(idx.controle.couverture_ccomptes.lecture)}</p>
<h2>Les représentants d’intérêts</h2>
<p>${h(entier(idx.influence.organisations_publiees))} organisations inscrites au répertoire de la HATVP. En ${idx.influence.annee_reference}, ${h(entier(idx.influence.depenses_annee_reference.organisations_declarantes))} ont déclaré au moins ${h(eurLisible(idx.influence.depenses_annee_reference.depense_min_eur))} de dépenses de représentation et ${h(entier(idx.influence.depenses_annee_reference.activites))} activités.</p>
${
  cibles.length
    ? `<div class="tableau-defile"><table><caption>Ministères les plus souvent désignés comme destinataires d’actions déclarées (2018 à 2026), par nombre d’actions</caption><thead><tr><th scope="col">Cible</th><th scope="col" class="nombre">Actions</th><th scope="col" class="nombre">Organisations</th></tr></thead><tbody>${cibles
        .map((c) => `<tr><td>${h(c.cible!)}</td><td class="nombre">${h(entier(c.actions))}</td><td class="nombre">${h(entier(c.organisations))}</td></tr>`)
        .join('')}</tbody></table></div>${source(min!.source)}`
    : ''
}
${
  aides
    ? `<h2>Les aides aux entreprises</h2>
<p>Selon le périmètre retenu, les estimations publiées vont de ${h(md(aides.fourchette.basse_md))} à ${h(md(aides.fourchette.haute_md))} par an. ${h(aides.fourchette.note)}</p>
<div class="tableau-defile"><table><caption>Estimations publiées (elles ne s’additionnent pas)</caption><thead><tr><th scope="col">Auteur et publication</th><th scope="col">Périmètre</th><th scope="col" class="nombre">Montant</th></tr></thead><tbody>${aides.estimations
        .map((e) => `<tr><td>${h(e.auteur)} : « ${h(e.publication)} »${e.variante ? `, ${h(e.variante)}` : ''} (${typeof e.annee_donnees === 'number' ? `données ${e.annee_donnees}` : h(e.annee_donnees_note ?? 'année des données non publiée')})</td><td>${h(e.perimetre)}</td><td class="nombre">${h(md(e.md))}${e.md_haut ? ` à ${h(md(e.md_haut))}` : ''}</td></tr>`)
        .join('')}</tbody></table></div>
<p class="avertissement">${h(aides.avertissement)}</p>${source(aides.source)}
<p class="aide">Les intitulés entre guillemets sont les titres des publications citées. Les sommes versées aux ménages (retraites, santé, famille, chômage) sont présentées avec le même format dans <a href="#/explorer/secu">Sécurité sociale et protection sociale</a>.</p>`
    : ''
}
<p class="aide">${h(idx.regle_personnes)}</p>`
  cible.querySelector<HTMLSelectElement>('#dep-controle')?.addEventListener('change', (e) => {
    location.hash = lien('/decisions/controle', { dep: (e.target as HTMLSelectElement).value })
  })
}

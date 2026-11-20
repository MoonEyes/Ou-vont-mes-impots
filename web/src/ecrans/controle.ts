// Contrôle, représentation d'intérêts et aides aux entreprises (site/data/controle/).
import { listeRecherche, valeurChoix } from '../composants/choix'
import { encadreManque, type Manque } from '../composants/manque'
import { DEPARTEMENTS } from '../departements'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { absent, badgeStatut, entier, eur, eurLisible, h, md, source } from '../util'
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


// ---------- Fonds de solidarité (site/data/fonds_solidarite/, pipeline/fonds_solidarite.py) ----------
type LigneFsd = [string, string, number | null, number | null, number | null]
interface FsdIndex {
  millesime: string
  source: string
  volets: Record<string, string>
  instantanes: { volet1_dernier: string; volet2_dernier: string; fins_de_mois: string[] }
  sections: Record<string, string>
  categories_juridiques: Record<string, string>
  classes_effectif: Record<string, string>
  regions: Record<string, string>
  departements: Record<string, string>
  region_des_departements: Record<string, string>
  manques: Manque[]
  regles: string[]
  limites: string[]
}
interface FsdDeps {
  source: string
  instantane: string
  par_section: { lignes: LigneFsd[] }
  par_categorie_juridique: { lignes: LigneFsd[] }
  par_classe_effectif: { lignes: LigneFsd[] }
}
interface FsdMois {
  source: string
  millesime: string
  lignes: [string, number, string, string, number | null, number | null, number | null][]
}
const FSD_PLACE = `<section id="fsd" aria-labelledby="fsd-titre"><h2 id="fsd-titre">Le fonds de solidarité dans ton département (Covid-19)</h2><p class="aide">Chargement…</p></section>`
const nb = (x: number | null) => (typeof x === 'number' ? h(entier(x)) : `${badgeStatut('nonpub')} non publié`)
const mt = (x: number | null) => (typeof x === 'number' ? h(eur(x)) : `${badgeStatut('nonpub')} non publié`)
const dateFr = (d: string) => d.split('-').reverse().join('/')

function tableFsd(lignes: LigneFsd[], noms: Record<string, string>, legende: string, premier: string): string {
  if (!lignes.length) return absent('Aucune ligne publiée pour ce département.')
  return `<div class="tableau-defile"><table><caption>${h(legende)}</caption><thead><tr><th scope="col">${h(premier)}</th><th scope="col" class="nombre">Aides</th><th scope="col" class="nombre">Entreprises aidées</th><th scope="col" class="nombre">Montant cumulé</th></tr></thead><tbody>${lignes
    .map((l) => `<tr><th scope="row">${h(noms[l[1]] ?? l[1])}</th><td class="nombre">${nb(l[2])}</td><td class="nombre">${nb(l[3])}</td><td class="nombre">${mt(l[4])}</td></tr>`)
    .join('')}</tbody></table></div>`
}

export function blocFondsSolidarite(idx: FsdIndex, d: FsdDeps, dep: string): string {
  const nom = idx.departements[dep] ?? dep
  const date = dateFr(d.instantane)
  const de = (t: { lignes: LigneFsd[] }) => t.lignes.filter((l) => l[0] === dep)
  return `<p>${badgeStatut('trace')} Aides du volet 1 (versées par l’État) aux entreprises de ${h(nom)} (${h(dep)}), cumulées depuis le début du dispositif, d’après le fichier publié le ${h(date)}. Le site n’additionne pas les lignes.</p>
${tableFsd(de(d.par_section), idx.sections, `${nom} : aides par secteur d’activité, cumul au ${date}`, 'Secteur d’activité')}
<details><summary>Par forme juridique</summary>${tableFsd(de(d.par_categorie_juridique), idx.categories_juridiques, `${nom} : aides par forme juridique, cumul au ${date}`, 'Forme juridique')}
<p class="aide">Une ligne regroupe toutes les entreprises de la même forme juridique : aucune entreprise n’est nommée, entrepreneurs individuels compris.</p></details>
<details><summary>Par taille d’entreprise</summary>${tableFsd(de(d.par_classe_effectif), idx.classes_effectif, `${nom} : aides par nombre de salariés, cumul au ${date}`, 'Nombre de salariés')}</details>`
}

export function blocFondsMois(idx: FsdIndex, m: FsdMois, region: string, section: string): string {
  const lignes = m.lignes.filter((l) => l[2] === region && l[3] === section)
  const dates = [...new Set(lignes.map((l) => l[0]))].sort()
  if (!dates.length) return absent('Aucun cumul publié pour ce secteur dans cette région.')
  const cellule = (date: string, volet: number) => {
    const l = lignes.find((x) => x[0] === date && x[1] === volet)
    return l ? mt(l[6]) : `${badgeStatut('nonpub')} non publié`
  }
  return `<div class="tableau-defile"><table><caption>${h(idx.regions[region] ?? region)}, ${h(idx.sections[section] ?? section)} : montants cumulés publiés à la fin de chaque mois, par volet (jamais additionnés)</caption><thead><tr><th scope="col">Fichier du</th><th scope="col" class="nombre">Volet 1 (État)</th><th scope="col" class="nombre">Volet 2 (régions)</th></tr></thead><tbody>${dates
    .map((d) => `<tr><th scope="row">${h(dateFr(d))}</th><td class="nombre">${cellule(d, 1)}</td><td class="nombre">${cellule(d, 2)}</td></tr>`)
    .join('')}</tbody></table></div>`
}

async function fondsSolidarite(cible: HTMLElement, depDemande: string | null): Promise<void> {
  const [idx, d, m] = await Promise.all([
    chargerSiPresent<FsdIndex>('fonds_solidarite/index.json'),
    chargerSiPresent<FsdDeps>('fonds_solidarite/departements.json'),
    chargerSiPresent<FsdMois>('fonds_solidarite/regions_mois.json'),
  ])
  const zone = cible.querySelector<HTMLElement>('#fsd')
  if (!zone) return
  if (!idx || !d) {
    zone.innerHTML = `<h2 id="fsd-titre">Le fonds de solidarité dans ton département (Covid-19)</h2>${absent('Données du fonds de solidarité non disponibles.')}`
    return
  }
  const deps = Object.keys(idx.departements).filter((k) => d.par_section.lignes.some((l) => l[0] === k))
  const dep = depDemande && deps.includes(depDemande) ? depDemande : deps[0]
  const regionDe = (k: string) => idx.region_des_departements[k] ?? ''
  const sections = Object.keys(idx.sections)
  zone.innerHTML = `<h2 id="fsd-titre">Le fonds de solidarité dans ton département (Covid-19)</h2>
<p>De 2020 à 2022, l’État et les régions ont versé une aide aux petites entreprises, aux indépendants et aux micro-entrepreneurs dont l’activité a été réduite par la crise sanitaire. La page montre ce que l’État a publié : des nombres d’aides et des montants regroupés par département, secteur, forme juridique et taille. Elle ne montre aucune entreprise en particulier.</p>
${listeRecherche({ id: 'fsd-dep', etiquette: 'Département', options: deps.map((k) => ({ valeur: k, libelle: `${k} ${idx.departements[k]}` })), valeur: dep, recherche: true })}
<div id="fsd-detail" aria-live="polite">${blocFondsSolidarite(idx, d, dep)}</div>
${
  m
    ? `<h3>Mois après mois, dans la région</h3>
<p>Chaque ligne est le cumul publié à la fin du mois. Le site ne calcule pas le montant versé au cours d’un mois.</p>
${listeRecherche({ id: 'fsd-section', etiquette: 'Secteur d’activité', options: sections.map((k) => ({ valeur: k, libelle: idx.sections[k] })), valeur: sections.includes('I') ? 'I' : sections[0], recherche: true })}
<div id="fsd-mois" aria-live="polite">${blocFondsMois(idx, m, regionDe(dep), sections.includes('I') ? 'I' : sections[0])}</div>${source(m.source, m.millesime)}`
    : ''
}
${idx.manques.map((x) => encadreManque(x)).join('')}
<ul class="limites">${idx.limites.map((x) => `<li>${h(x)}</li>`).join('')}</ul>
${source(d.source, idx.millesime)}`
  const majMois = () => {
    const z = zone.querySelector<HTMLElement>('#fsd-mois')
    if (z && m) z.innerHTML = blocFondsMois(idx, m, regionDe(valeurChoix(zone, 'fsd-dep')), valeurChoix(zone, 'fsd-section'))
  }
  zone.querySelector('#fsd-dep')?.addEventListener('change', () => {
    zone.querySelector<HTMLElement>('#fsd-detail')!.innerHTML = blocFondsSolidarite(idx, d, valeurChoix(zone, 'fsd-dep'))
    majMois()
  })
  zone.querySelector('#fsd-section')?.addEventListener('change', majMois)
}


// ---------- Justice administrative : décisions sur l'impôt et le budget (site/data/jurisprudence/) ----------
interface JurIndex {
  millesime: string
  source: string
  lien_modele: string
  criteres: Record<string, string>
  sous_rubriques: Record<string, string>
  juridictions: string[]
  fichiers: { decisions: Record<string, { chemin: string; decisions: number }> }
  manques: Manque[]
  regles: string[]
  limites: string[]
}
interface JurComptes {
  source: string
  millesime: string
  lignes: [number, string, number, number, number, number, number][]
}
interface JurDecisions {
  annee: number
  decisions: [string, number, string, string | null, 'fiscale' | 'budgetaire', string | null, string[]][]
}
const JUR_PLACE = `<section id="jur" aria-labelledby="jur-titre"><h2 id="jur-titre">Les décisions de la justice administrative sur l’impôt et le budget</h2><p class="aide">Chargement…</p></section>`
const JUR_MAX_LIENS = 200

export function blocJurComptes(idx: JurIndex, c: JurComptes, j: string): string {
  const lignes = c.lignes.filter((l) => l[1] === j).sort((a, b) => b[0] - a[0])
  if (!lignes.length) return absent('Aucune décision de cette juridiction dans la base.')
  return `<div class="tableau-defile"><table><caption>${h(j)} : décisions publiées dans la base JADE, par année de décision</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Décisions</th><th scope="col" class="nombre">dont classées</th><th scope="col" class="nombre">Impôt (classement)</th><th scope="col" class="nombre">Impôt (type de recours)</th><th scope="col" class="nombre">Budget et comptabilité publique</th></tr></thead><tbody>${lignes
    .map((l) => `<tr><th scope="row">${l[0]}</th><td class="nombre">${h(entier(l[2]))}</td><td class="nombre">${h(entier(l[3]))}</td><td class="nombre">${h(entier(l[4]))}</td><td class="nombre">${h(entier(l[5]))}</td><td class="nombre">${h(entier(l[6]))}</td></tr>`)
    .join('')}</tbody></table></div>
<p class="aide">Impôt (classement) : ${h(idx.criteres.fiscale_classement)}. Impôt (type de recours) : ${h(idx.criteres.fiscale_type_recours)}. Budget : ${h(idx.criteres.budgetaire_classement)}.</p>`
}

export function blocJurDecisions(idx: JurIndex, d: JurDecisions, rangJ: number | null): string {
  const l = d.decisions.filter((x) => rangJ === null || x[1] === rangJ)
  if (!l.length) return absent(`Aucune décision fiscale ou budgétaire classée en ${d.annee} pour cette juridiction.`)
  const vues = l.slice(0, JUR_MAX_LIENS)
  return `<p>${h(entier(l.length))} décision${l.length > 1 ? 's' : ''} classée${l.length > 1 ? 's' : ''} en matière fiscale ou budgétaire en ${d.annee}${l.length > vues.length ? ` ; les ${vues.length} premières par date sont listées` : ''}. Chaque lien ouvre la décision sur Légifrance, où elle est publiée par l’État.</p>
<ul class="lignes">${vues
    .map((x) => {
      const sous = x[6].map((c) => idx.sous_rubriques[c]).filter(Boolean).join(', ')
      return `<li><span><a href="${h(idx.lien_modele.replace('{id}', x[0]))}" rel="noopener noreferrer">${h(idx.juridictions[x[1]] ?? '')}, ${h(x[2].split('-').reverse().join('/'))}${x[3] ? `, n° ${h(x[3])}` : ''}</a></span><span class="dest">${x[4] === 'fiscale' ? 'Impôt' : 'Budget et comptabilité publique'}${sous ? ` · ${h(sous.toLowerCase())}` : ''}</span></li>`
    })
    .join('')}</ul>`
}

async function jurisprudence(cible: HTMLElement, jDemande: string | null): Promise<void> {
  const [idx, c] = await Promise.all([chargerSiPresent<JurIndex>('jurisprudence/index.json'), chargerSiPresent<JurComptes>('jurisprudence/comptes.json')])
  const zone = cible.querySelector<HTMLElement>('#jur')
  if (!zone) return
  if (!idx || !c) {
    zone.innerHTML = `<h2 id="jur-titre">Les décisions de la justice administrative sur l’impôt et le budget</h2>${absent('Décisions non disponibles.')}`
    return
  }
  const rang = jDemande && /^\d+$/.test(jDemande) && idx.juridictions[Number(jDemande)] ? Number(jDemande) : 0
  const annees = Object.keys(idx.fichiers.decisions).sort().reverse()
  zone.innerHTML = `<h2 id="jur-titre">Les décisions de la justice administrative sur l’impôt et le budget</h2>
<p>Quand une personne ou une entreprise conteste un impôt, ou qu’un litige porte sur le budget d’une administration, le Conseil d’État et les cours administratives d’appel tranchent. La page compte leurs décisions publiées par la DILA et renvoie au texte de chacune sur Légifrance ; elle n’en reprend aucun extrait ni aucun nom.</p>
${listeRecherche({ id: 'jur-j', etiquette: 'Juridiction', options: idx.juridictions.map((j, i) => ({ valeur: String(i), libelle: j })), valeur: String(rang), recherche: true })}
<div id="jur-comptes" aria-live="polite">${blocJurComptes(idx, c, idx.juridictions[rang])}</div>
<h3>Les décisions d’une année</h3>
${listeRecherche({ id: 'jur-an', etiquette: 'Année de décision', options: annees.map((a) => ({ valeur: a, libelle: a })), valeur: annees[0], recherche: true })}
<div id="jur-liste" aria-live="polite"><p class="aide">Chargement…</p></div>
${idx.manques.map((x) => encadreManque(x)).join('')}
<ul class="limites">${[...idx.regles, ...idx.limites].map((x) => `<li>${h(x)}</li>`).join('')}</ul>
${source(c.source, c.millesime)}`
  const liste = async () => {
    const an = valeurChoix(zone, 'jur-an')
    const f = idx.fichiers.decisions[an]
    const z = zone.querySelector<HTMLElement>('#jur-liste')!
    const d = f ? await chargerSiPresent<JurDecisions>(f.chemin) : null
    if (valeurChoix(zone, 'jur-an') !== an) return
    z.innerHTML = d ? blocJurDecisions(idx, d, Number(valeurChoix(zone, 'jur-j'))) : absent('Liste non disponible.')
  }
  zone.querySelector('#jur-j')?.addEventListener('change', () => {
    zone.querySelector<HTMLElement>('#jur-comptes')!.innerHTML = blocJurComptes(idx, c, idx.juridictions[Number(valeurChoix(zone, 'jur-j'))])
    void liste()
  })
  zone.querySelector('#jur-an')?.addEventListener('change', () => void liste())
  await liste()
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
<form>${listeRecherche({ id: 'dep-controle', etiquette: 'Rapports sur les collectivités d’un département', options: [], optionsHtml: `<option value="">Choisir</option>${DEPARTEMENTS.map(
    ([k, n]) => `<option value="${k}"${k === dep ? ' selected' : ''}>${k} ${h(n)}</option>`,
  ).join('')}` })}</form>
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
${FSD_PLACE}
${JUR_PLACE}
<p class="aide">${h(idx.regle_personnes)}</p>`
  cible.querySelector<HTMLSelectElement>('#dep-controle')?.addEventListener('change', (e) => {
    location.hash = lien('/decisions/controle', { dep: (e.target as HTMLSelectElement).value })
  })
  return { suite: Promise.all([fondsSolidarite(cible, params.get('fsd') ?? dep), jurisprudence(cible, params.get('jur'))]).then(() => undefined) }
}

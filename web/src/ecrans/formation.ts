// Formation professionnelle (site/data/formation/) : compte personnel de formation, alternance et formation des
// demandeurs d'emploi côté budget de l'État, ressources de France compétences, financeurs, personnes, écarts entre sources.
// Les montants de périmètres différents sont montrés côte à côte, jamais additionnés.
import { partPersonnelle } from '../composants/hub'
import { chargerSiPresent, type Noeud } from '../donnees'
import { lien } from '../routeur'
import { absent, badgeStatut, barres, entier, eur, eurLisible, h, md, pct, source, sur100 } from '../util'
import { enCours } from './dette'

type Montants = Record<string, number>
interface AnneeCpf {
  dossiers: number
  montant_eur: number
  financeurs_eur: Montants
  financeurs_pct: Montants
  dossiers_cofinances: Montants
  par_statut: Record<string, { dossiers: number; montant_eur: number }>
  complete: boolean
  prix_moyen_eur: number
}
interface Ecart {
  annee: number
  montant: number
  autre_montant: number
  autre_publie: string
  ecart: number
  ecart_pct: number
  dossiers: number
  autre_dossiers: number
  lecture_ecart: string
}
interface Lien {
  vue: string
  fichier: string
  id: string
  nom: string
  programme?: string
  programme_chef_de_file?: string
  md?: number
  millesime?: string
  annees?: Record<string, { financement_etat_cp_eur?: number | null; taxes_affectees_eur?: number | null }>
  lecture: string
}
export interface IndexFormation {
  millesime: string
  source: string
  avertissement: string
  collecte_le?: string
  cpf: {
    definition: string
    regle: string
    financeurs: Record<string, string>
    note_financeurs: string
    annees: Record<string, AnneeCpf>
    organismes: { agreges: Record<string, number> }
  }
  elus?: { annees: string[]; totaux: Record<string, number[]>; organismes_nommes: number; organismes_agreges: number }
  liens?: Lien[]
  ecarts?: Ecart[]
  ecarts_source?: { document: string; url: string; champ: string; non_compare?: { periode: string; montant: string; dossiers: string; raison: string } }
  confidentialite?: { regle: string }
  limites?: string[]
  sources?: Record<string, { jeu: string; page: string; licence: string }>
  sources_inaccessibles?: { source: string; motif: string }[]
}
interface Usagers {
  source: string
  avertissement: string
  libelles: Record<string, string>
  annees: Record<string, { total: number[]; situation: Record<string, number[]> }>
}
export interface OrganismeCpf {
  siren: string
  nom: string
  categorie_juridique: string
  entrees_cumulees: number
  annees: Record<string, number[]>
}
interface Organismes {
  source: string
  avertissement: string
  estimation: { producteur: string; methode: string; limites: string[] }
  ordre: { regle: string }
  organismes: OrganismeCpf[]
  agreges: Record<string, { organismes: number }>
}

/** Même règle que pipeline/sirene.py : catégories juridiques 2xxx à 9xxx, hors groupements de personnes physiques. */
const CJ_PERSONNES_PHYSIQUES = new Set(['2110', '2210', '2310', '2385'])
export const personneMorale = (cj: unknown): boolean => {
  const s = typeof cj === 'string' ? cj : ''
  return /^\d{4}$/.test(s) && '23456789'.includes(s[0]) && !CJ_PERSONNES_PHYSIQUES.has(s)
}
/** Organismes affichables : personnes morales vérifiées seulement (contrôle redondant avec le pipeline). */
export const nommables = (liste: OrganismeCpf[]) => liste.filter((o) => personneMorale(o.categorie_juridique))

export const REGLE_FINANCEURS = 'Financeurs dans l’ordre de la source (Caisse des dépôts), pas un classement.'

const SITUATIONS_NC = 'NC'

/** Textes de la source destinés au public : sans nom de champ technique, sigles développés. */
const sansChamp = (t: string) => !/«\s?[a-z_]+\s?»/.test(t)
const SIGLES: [RegExp, string][] = [
  [/\bDARES\b/, 'Direction de l’animation de la recherche, des études et des statistiques (DARES)'],
  [/\bFIPHFP\b/, 'Fonds pour l’insertion des personnes handicapées dans la fonction publique (FIPHFP)'],
  [/\bDGEFP\b/, 'Délégation générale à l’emploi et à la formation professionnelle (DGEFP)'],
  [/\bSIRET\b/, 'numéro d’établissement (SIRET)'],
  [/\b(d|D)roits CPF\b/g, '$1roits du compte personnel de formation'],
  [/\b(au|du|le) montant CPF\b/g, '$1 montant du compte personnel de formation'],
  [/\b(du|le) CPF\b/g, '$1 compte personnel de formation'],
  [/\bCPF\b/g, 'compte personnel de formation'],
]
/** Noms des jeux de données de la Caisse des dépôts, pour la liste des sources. */
const JEUX: Record<string, string> = {
  moncompteformation_formations_engagees: 'Mon compte formation : les formations engagées',
  entree_sortie_formation: 'Mon compte formation : entrées et sorties de formation',
  'moncompteformation-les-usagers': 'Mon compte formation : les usagers',
  'moncompteelu-formations-elus': 'Mon compte élu : les formations réalisées par les élus',
  fiphfp_financement_aidesplateforme_dpt: 'Fonds pour l’insertion des personnes handicapées dans la fonction publique : aides par département',
  fiphfp_financement_conv_employeur_reg: 'Fonds pour l’insertion des personnes handicapées dans la fonction publique : conventions par région',
}
export const REGLE_ORGANISMES =
  'Personnes morales classées par entrées en formation cumulées depuis 2022, de la plus grande à la plus petite, puis par numéro d’entreprise. Les dix premières sont affichées ; les autres sont additionnées.'
export const clair = (t: string) => SIGLES.reduce((x, [re, v]) => x.replace(re, v), t)
/** Texte de la source, échappé et rendu lisible. */
const hc = (t: string) => h(clair(t))

/** Dernière année complète du compte personnel de formation. */
export function anneeReference(annees: Record<string, AnneeCpf>): string {
  const completes = Object.keys(annees).filter((a) => annees[a].complete).sort()
  return completes[completes.length - 1] ?? Object.keys(annees).sort().pop() ?? ''
}

const action = (n: Noeud | null, suffixe: string) => n?.enfants?.find((e) => e.id.endsWith(suffixe)) ?? null

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const idx = await chargerSiPresent<IndexFormation>('formation/index.json')
  if (!idx) {
    cible.innerHTML = enCours('La formation professionnelle', 'Compte personnel de formation, alternance et formation des demandeurs d’emploi : montants, financeurs et personnes concernées.') + partPersonnelle()
    return
  }
  const lienArbre = idx.liens?.find((l) => l.vue === 'arbre_etat')
  const lienOp = idx.liens?.find((l) => l.vue === 'operateurs')
  const [usagers, orgs, prog] = await Promise.all([
    chargerSiPresent<Usagers>('formation/cpf_usagers.json'),
    chargerSiPresent<Organismes>('formation/cpf_organismes.json'),
    lienArbre ? chargerSiPresent<Noeud>(lienArbre.fichier) : Promise.resolve(null),
  ])
  const annees = idx.cpf.annees
  const liste = Object.keys(annees).sort()
  const ref = anneeReference(annees)
  const demande = params.get('a') ?? ''
  const a = annees[demande] ? demande : ref
  const cpf = annees[a]
  const cpfRef = annees[ref]
  const alternance = action(prog, '-01')
  const demandeurs = action(prog, '-02')
  const millProg = lienArbre?.millesime ?? prog?.millesime ?? ''
  const anneeProg = /\d{4}/.exec(millProg)?.[0] ?? ''
  const progLien = lienArbre ? lien('/explorer/etat/detail', { m: 'execution2024', id: lienArbre.id }) : ''
  const srcCpf = 'Caisse des dépôts, Mon compte formation, formations engagées (données ouvertes, Licence Ouverte 2.0)'
  const srcProg = `Budget de l’État, programme ${lienArbre?.programme ?? '103'} « ${lienArbre?.nom ?? ''} », ${millProg}`

  const cles = `<ul class="cles" aria-label="Chiffres clés de la formation professionnelle">
  <li class="cle-famille"><strong>${h(eurLisible(cpfRef.montant_eur))}</strong><span>engagés en ${h(ref)} sur le compte personnel de formation, pour ${h(entier(cpfRef.dossiers))} dossiers (Caisse des dépôts)</span>${badgeStatut('trace')}</li>
  ${alternance ? `<li><strong>${h(md(alternance.md))}</strong><span>dépensés par l’État en ${h(anneeProg)} pour l’alternance, dont l’apprentissage (budget de l’État)</span>${badgeStatut('trace')}</li>` : ''}
  ${demandeurs ? `<li><strong>${h(md(demandeurs.md))}</strong><span>dépensés par l’État en ${h(anneeProg)} pour la formation des demandeurs d’emploi (budget de l’État)</span>${badgeStatut('trace')}</li>` : ''}
</ul>`

  const dispositifs = `<h2>Trois dispositifs, trois périmètres</h2>
<div class="tableau-defile"><table><caption>Montants publiés par dispositif, avec leur année, leur source et leur statut</caption>
<thead><tr><th scope="col">Dispositif</th><th scope="col" class="nombre">Montant</th><th scope="col">Année</th><th scope="col">Source</th><th scope="col">Statut</th></tr></thead><tbody>
${alternance ? `<tr><th scope="row">Alternance, dont l’apprentissage : part du budget de l’État</th><td class="nombre">${h(md(alternance.md))}</td><td>${h(anneeProg)}</td><td>${h(srcProg)}, action « ${h(alternance.nom)} »</td><td>${badgeStatut('trace')}</td></tr>` : ''}
${demandeurs ? `<tr><th scope="row">Formation des demandeurs d’emploi : part du budget de l’État</th><td class="nombre">${h(md(demandeurs.md))}</td><td>${h(anneeProg)}</td><td>${h(srcProg)}, action « ${h(demandeurs.nom)} »</td><td>${badgeStatut('trace')}</td></tr>` : ''}
<tr><th scope="row">Compte personnel de formation : montant engagé</th><td class="nombre">${h(eurLisible(cpfRef.montant_eur))}</td><td>${h(ref)}</td><td>${h(srcCpf)}</td><td>${badgeStatut('trace')}</td></tr>
</tbody></table></div>
${!prog ? absent('Le détail du programme du budget de l’État consacré à l’alternance et à la formation des demandeurs d’emploi n’est pas disponible.') : ''}
<p class="aide">Ces montants ne s’additionnent pas : la part de l’État dans l’alternance passe en partie par France compétences, qui finance aussi le compte personnel de formation. Les sommes versées par France compétences aux centres de formation d’apprentis, et ce que dépensent les régions et France Travail pour former les demandeurs d’emploi, ne figurent pas dans les données reprises par le site.</p>`

  const ops = lienOp?.annees ? Object.keys(lienOp.annees).sort() : []
  const ressources = lienOp && ops.length
    ? `<h3>Les ressources de France compétences</h3>
<p>${hc(lienOp.lecture)}</p>
<div class="tableau-defile"><table><caption>Ressources de France compétences par année</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Impôts et contributions affectés (versés par les employeurs)</th><th scope="col" class="nombre">Crédits versés par l’État</th></tr></thead><tbody>
${ops
  .map((y) => {
    const v = lienOp.annees![y]
    const cell = (x: number | null | undefined) => (typeof x === 'number' ? h(eurLisible(x)) : 'non publié')
    return `<tr><th scope="row">${h(y)}</th><td class="nombre">${cell(v.taxes_affectees_eur)}</td><td class="nombre">${cell(v.financement_etat_cp_eur)}</td></tr>`
  })
  .join('')}</tbody></table></div>
<p class="aide">Statut : ${badgeStatut('trace')} Montants exécutés publiés dans l’annexe « Opérateurs de l’État » des projets de loi de finances. Détail de l’opérateur : <a href="${lien('/explorer/operateurs', { p: lienOp.programme_chef_de_file ?? '103' })}">France compétences parmi les opérateurs de l’État</a>.</p>`
    : ''

  const financeurs = Object.keys(idx.cpf.financeurs)
  const choix = `<form id="formation-annee"><label for="formation-annee-choix">Année du compte personnel de formation</label><select id="formation-annee-choix">${liste
    .map((y) => `<option value="${h(y)}"${y === a ? ' selected' : ''}>${h(y)}${annees[y].complete ? '' : ' (année en cours)'}</option>`)
    .join('')}</select></form>`
  const parFinanceur = `<h3>Qui finance les formations du compte personnel de formation en ${h(a)}</h3>
${choix}
<div class="carte" data-cle>
<p>Sur 100 € engagés en ${h(a)} (${h(eurLisible(cpf.montant_eur))}, ${h(entier(cpf.dossiers))} dossiers) :</p>
${barres(
  financeurs.map((f) => ({
    nom: clair(idx.cpf.financeurs[f]),
    valeur: cpf.financeurs_pct[f] ?? 0,
    texte: typeof cpf.financeurs_pct[f] === 'number' ? sur100(cpf.financeurs_pct[f]) : 'non publié',
    detail: `${typeof cpf.financeurs_eur[f] === 'number' ? eurLisible(cpf.financeurs_eur[f]) : 'montant non publié'}${typeof cpf.dossiers_cofinances[f] === 'number' ? `, ${entier(cpf.dossiers_cofinances[f])} dossiers avec une part de ce financeur` : ''}`,
  })),
  100,
  `Financeurs du compte personnel de formation en ${a}, en euros sur 100 €`,
  -1,
)}
<p class="aide" data-regle-ordre>${h(REGLE_FINANCEURS)}</p>
<p class="aide">${h(idx.cpf.note_financeurs)} ${cpf.complete ? '' : 'Année en cours : moins de douze mois, et des dossiers récents peuvent encore être annulés.'}</p>
${source(srcCpf, a)}
</div>`

  const evolution = `<h2>Combien de dossiers, et l’évolution</h2>
<p>${h(idx.cpf.definition)}</p>
<div class="tableau-defile"><table><caption>Compte personnel de formation par année de validation des dossiers</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Dossiers validés</th><th scope="col" class="nombre">Montant engagé</th><th scope="col" class="nombre">Prix moyen</th><th scope="col" class="nombre">Dossiers annulés ou rejetés</th><th scope="col">Année</th></tr></thead><tbody>
${liste
  .map((y) => {
    const x = annees[y]
    const ann = x.par_statut.annule
    return `<tr><th scope="row">${h(y)}</th><td class="nombre">${h(entier(x.dossiers))}</td><td class="nombre">${h(eurLisible(x.montant_eur))}</td><td class="nombre">${h(eur(x.prix_moyen_eur))}</td><td class="nombre">${ann ? h(entier(ann.dossiers)) : 'non publié'}</td><td>${x.complete ? 'complète' : 'en cours'}</td></tr>`
  })
  .join('')}</tbody></table></div>
<p class="aide">Dossiers validés : formations réalisées, réalisées en partie ou en cours ; les dossiers annulés ou rejetés sont comptés à part. Montant engagé : prix des formations des dossiers validés, pas un montant payé.</p>
${source(srcCpf, `dossiers validés de ${liste[0]} à ${liste[liste.length - 1]}${idx.collecte_le ? `, données collectées le ${idx.collecte_le}` : ''}`)}`

  const u = usagers?.annees[a]
  const personnes = u
    ? `<h3>Qui suit ces formations en ${h(a)}</h3>
<div class="tableau-defile"><table><caption>Dossiers entrés en formation en ${h(a)}, selon la situation du titulaire</caption>
<thead><tr><th scope="col">Situation</th><th scope="col" class="nombre">Dossiers</th><th scope="col" class="nombre">Montant</th><th scope="col" class="nombre">Sur 100 dossiers</th></tr></thead><tbody>
${Object.entries(u.situation)
  .map(([s, v]) => `<tr><th scope="row">${h(s === SITUATIONS_NC ? usagers!.libelles.NC ?? 'non communiqué' : s)}</th><td class="nombre">${h(entier(v[0]))}</td><td class="nombre">${h(eurLisible(v[1]))}</td><td class="nombre">${h(pct(u.total[0] > 0 ? (v[0] / u.total[0]) * 100 : 0))}</td></tr>`)
  .join('')}
<tr><th scope="row">Ensemble</th><td class="nombre">${h(entier(u.total[0]))}</td><td class="nombre">${h(eurLisible(u.total[1]))}</td><td class="nombre">100 %</td></tr></tbody></table></div>
<p class="aide">${hc(usagers!.avertissement)} Situations dans l’ordre de la source.</p>
${source(clair(usagers!.source), a)}`
    : ''

  const ecarts = idx.ecarts?.length
    ? `<h2>Deux sources pour le même montant</h2>
<p>La Caisse des dépôts publie les dossiers en données ouvertes ; France compétences publie un montant annuel dans son rapport sur l’usage des fonds. Les deux chiffres sont montrés, aucun n’est retenu contre l’autre.</p>
<div class="tableau-defile"><table><caption>Compte personnel de formation : montant engagé selon deux sources</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Caisse des dépôts (données ouvertes)</th><th scope="col" class="nombre">France compétences (rapport)</th><th scope="col" class="nombre">Écart</th><th scope="col" class="nombre">Dossiers (deux sources)</th></tr></thead><tbody>
${idx.ecarts
  .map((e) => `<tr><th scope="row">${h(String(e.annee))}</th><td class="nombre">${h(eurLisible(e.montant))}</td><td class="nombre">${h(e.autre_publie)}</td><td class="nombre">${h(eurLisible(e.ecart))} (${h(pct(e.ecart_pct))})</td><td class="nombre">${h(entier(e.dossiers))} et ${h(entier(e.autre_dossiers))}</td></tr>`)
  .join('')}</tbody></table></div>
<p class="aide">${h(idx.ecarts[0].lecture_ecart)}${idx.ecarts_source?.non_compare ? ` Non comparé : ${h(idx.ecarts_source.non_compare.periode)} (${h(idx.ecarts_source.non_compare.montant)}), car ${h(idx.ecarts_source.non_compare.raison)}.` : ''}</p>
${idx.ecarts_source ? `<p class="source"><a href="${h(idx.ecarts_source.url)}" rel="noopener noreferrer">${h(idx.ecarts_source.document)}</a></p>` : ''}`
    : ''

  const listes = orgs ? nommables(orgs.organismes).slice(0, 10) : []
  const agreges = idx.cpf.organismes.agreges
  const organismes = orgs
    ? `<h2>Les organismes de formation</h2>
<p>Seules les personnes morales sont nommées, sous leur nom au répertoire des entreprises de l’Insee. ${h(entier(agreges.personnes_morales_non_listees ?? 0))} autres personnes morales et ${h(entier(agreges.entrepreneurs_individuels_et_groupements_de_personnes ?? 0))} entrepreneurs individuels ou groupements de personnes sont additionnés, jamais nommés.</p>
${
  listes.length
    ? `<div class="tableau-defile"><table><caption>Dix organismes aux entrées en formation cumulées les plus nombreuses, chiffres de ${h(a)}</caption>
<thead><tr><th scope="col">Organisme</th><th scope="col" class="nombre">Entrées en formation en ${h(a)}</th><th scope="col" class="nombre">Montant approché en ${h(a)}</th></tr></thead><tbody>
${listes
  .map((o) => {
    const v = o.annees[a]
    return `<tr><td>${h(o.nom)} <span class="aide">(numéro d’entreprise ${h(o.siren)})</span></td><td class="nombre">${v ? h(entier(v[0])) : 'aucune entrée publiée'}</td><td class="nombre">${v && typeof v[3] === 'number' ? h(eurLisible(v[3])) : 'non publié'}</td></tr>`
  })
  .join('')}</tbody></table></div>
<p class="aide" data-regle-ordre>${h(REGLE_ORGANISMES)}</p>`
    : absent('Aucun organisme publié pour cette année.')
}
<p>Montant approché ${badgeStatut('approche')} : la source publie des effectifs par organisme, pas des montants. Le montant approché est une estimation du projet, pas un montant versé ni un chiffre d’affaires ; il ne doit pas être cité comme une donnée de la Caisse des dépôts.</p>
<details><summary>Méthode de l’estimation</summary><p>Producteur : ${h(orgs.estimation.producteur)}. ${h(orgs.estimation.methode)}</p><ul>${orgs.estimation.limites.filter(sansChamp).map((l) => `<li>${h(l)}</li>`).join('')}</ul></details>
${source(clair(orgs.source))}`
    : ''

  const el = idx.elus
  const elus = el
    ? `<h2>La formation des élus locaux</h2>
<p>Un autre dispositif géré par la Caisse des dépôts, publié à part et jamais additionné au compte personnel de formation. Agrégats seulement : aucun élu nommé.</p>
<div class="tableau-defile"><table><caption>Droit individuel à la formation des élus locaux, par année de validation</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Dossiers</th><th scope="col" class="nombre">Montant engagé</th><th scope="col" class="nombre">Heures</th></tr></thead><tbody>
${el.annees
  .map((y) => {
    const t = el.totaux[y]
    return t ? `<tr><th scope="row">${h(y)}</th><td class="nombre">${h(entier(t[0]))}</td><td class="nombre">${h(eurLisible(t[1]))}</td><td class="nombre">${h(entier(t[3]))}</td></tr>` : ''
  })
  .join('')}</tbody></table></div>
<p class="aide">Statut : ${badgeStatut('trace')} ${h(entier(el.organismes_nommes))} organismes de formation sont nommés dans le fichier des élus, ${h(entier(el.organismes_agreges))} sont additionnés.</p>
${source('Caisse des dépôts, Mon compte élu (données ouvertes, Licence Ouverte 2.0)', el.annees.join(', '))}`
    : ''

  const sources = `<details><summary>Sources, limites et confidentialité</summary>
${idx.sources ? `<ul>${Object.values(idx.sources)
    .filter((s, i, t) => t.findIndex((x) => x.page === s.page) === i)
    .map((s) => `<li><a href="${h(s.page)}" rel="noopener noreferrer">Caisse des dépôts, ${h(JEUX[s.jeu] ?? s.page)}</a> (${h(s.licence)})</li>`)
    .join('')}</ul>` : ''}
${idx.limites?.length ? `<h3>Limites</h3><ul>${idx.limites.filter(sansChamp).map((l) => `<li>${h(l)}</li>`).join('')}</ul>` : ''}
${idx.sources_inaccessibles?.length ? `<h3>Sources non reprises</h3><ul>${idx.sources_inaccessibles.map((s) => `<li>${hc(`${s.source} : ${s.motif}`)}</li>`).join('')}</ul>` : ''}
${idx.confidentialite ? `<h3>Confidentialité</h3><p>${hc(idx.confidentialite.regle)}</p>` : ''}
${source(clair(idx.source), idx.collecte_le ? `données collectées le ${idx.collecte_le}` : undefined)}
</details>`

  cible.innerHTML = `
<h1>La formation professionnelle</h1>
<p class="chapeau">Apprentissage, compte personnel de formation, formation des demandeurs d’emploi : les montants publiés, qui les verse et combien de personnes sont concernées. Chaque chiffre porte son année, sa source et son statut.</p>
${cles}
<p class="avertissement">${hc(idx.avertissement)}</p>
${dispositifs}
<h2>Qui verse l’argent</h2>
<p>Sur ta paie, ton employeur verse la contribution à la formation professionnelle et la taxe d’apprentissage, en plus de ton salaire brut. Elles vont à France compétences, qui les répartit.</p>
${ressources}
${parFinanceur}
${evolution}
${personnes}
${ecarts}
${organismes}
${elus}
${sources}
<p class="liens-sortie">${progLien ? `<a href="${h(progLien)}">Le programme ${h(lienArbre!.programme ?? '103')} dans le budget de l’État</a> · ` : ''}<a href="${lien('/beneficiaires/programme', { p: lienArbre?.programme ?? '103' })}">Qui reçoit l’argent du programme ${h(lienArbre?.programme ?? '103')}</a> · <a href="${lien('/explorer/operateurs')}">Les opérateurs de l’État</a></p>
${partPersonnelle()}`
  cible.querySelector<HTMLSelectElement>('#formation-annee-choix')?.addEventListener('change', (e) => {
    location.hash = lien('/explorer/formation-professionnelle', { a: (e.target as HTMLSelectElement).value })
  })
}

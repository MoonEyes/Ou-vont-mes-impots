// « Ma commune » : blocs complémentaires du lot 2 (inventaire du 20/11/2026), chargés à l'ouverture de leur section
// repliée (rien n'est lu tant que la section reste fermée). Chaque bloc porte sa source et son millésime ; un bloc sans
// donnée pour la commune affiche l'encadré « Donnée non publiée à la source » (composants/manque.ts). Montants et
// effectifs repris tels que les sources les publient : aucun total, ratio ni moyenne calculés ici, rien n'est
// additionné aux budgets des collectivités ni d'un bloc à l'autre.
// Sources : site/data/ofgl_complements, elus_indemnites, caf_communes, ifi_communes, emploi_territoires,
// pathologies_departements, police_municipale (contrat 2.72 à 2.78).
import { encadreManque, MANQUES } from '../composants/manque'
import { chargerSiPresent } from '../donnees'
import { absent, entier, eur, eurLisible, h, pct, source } from '../util'

type Annees<T> = Record<string, T>

export interface OfglDep {
  millesime: string
  source: string
  colonnes: { fpic: string[]; flux_communes: string[]; flux_epci: string[]; patrimoine: string[]; sdis: string[]; epl: string[] }
  annee_flux_communes: string | null
  annee_patrimoine: string | null
  communes: Record<string, { flux?: (number | null)[]; patrimoine?: (number | null)[]; fpic?: Annees<(number | null)[]> }>
  epci: Record<string, { nom: string; fpic?: Annees<(number | null)[]>; flux?: Annees<(number | null)[]>; patrimoine?: (number | null)[] }>
  sdis: { departement: string; annees: Annees<(number | null)[]>; par_habitant: Annees<(number | null)[]>; population: Annees<number> } | null
  organismes: [string | null, string | null, string | null, string | null, Annees<(number | null)[]>][]
}
interface ElusDep { millesime: string; source: string; communes: Record<string, Annees<(number | null)[]>> }
interface ElusIndex { definitions: Record<string, string>; plafond: string; methode: string }
interface CafDep {
  millesime: string
  source: string
  colonnes: string[]
  communes: Record<string, { annees: Annees<(number | null)[]>; iris?: [string, string | null, string, (number | null)[]][]; qpv?: [string, string | null, string, (number | null)[]][]; arrondissements?: Record<string, Annees<(number | null)[]>> }>
  epci: Record<string, { annees: Annees<(number | null)[]>; aah_aeeh: Annees<(number | null)[]> }>
}
interface CafIndex { prestations: Record<string, string>; secret_statistique: string; montant: string; aah: string }
interface Ifi { millesime: string; source: string; communes: Record<string, { nom: string; annees: Annees<number[]>; arrondissements?: Record<string, { nom_source: string; annees: Annees<number[]> }> }> }
interface IfiIndex { seuil: string; rupture: string; annees: string[]; fiche: string }
interface Dares { millesime: string; source: string; annees: string[]; communes: Record<string, (number | null)[]> }
interface Unedic { millesime: string; source: string; colonnes: string[]; dernier_mois: string; departements: Record<string, { nom: string; mois: Record<string, (number | null)[]> }> }
interface Police { millesime: string; source: string; communes: Record<string, Annees<(number | null)[]>> }
interface PoliceIndex { annees: string[]; fiche: string }
interface Patho { millesime: string; source: string; mention: string; pathologies: string[]; departements: Record<string, { nom: string; annees: Annees<([number | null, number | null] | null)[]> }> }
interface PathoIndex { pathologies: Record<string, { libelle: string; niveau: number }> }

const nul = (v: number | null | undefined): v is null | undefined => v === null || v === undefined
const montant = (v: number | null | undefined) => (nul(v) ? 'non publié' : eur(v))
const effectif = (v: number | null | undefined) => (nul(v) ? 'non diffusé' : entier(v))
const derniere = <T>(a: Annees<T> | undefined) => (a ? Object.keys(a).sort().pop() : undefined)
const ligneTableau = (cellules: string[]) => `<tr><th scope="row">${cellules[0]}</th>${cellules.slice(1).map((c) => `<td class="nombre">${c}</td>`).join('')}</tr>`
const tableau = (caption: string, entetes: string[], lignes: string[][]) =>
  `<div class="tableau-defile"><table><caption>${caption}</caption><thead><tr>${entetes.map((e, i) => `<th scope="col"${i ? ' class="nombre"' : ''}>${e}</th>`).join('')}</tr></thead><tbody>${lignes.map(ligneTableau).join('')}</tbody></table></div>`

/** Les cinq dernières années d'une série, dans l'ordre chronologique. */
const cinqDernieres = (annees: string[]) => [...annees].sort().slice(-5)

// ------------------------------------------------------------------------------------------- commune et intercommunalité

export const LIBELLES_FLUX_COMMUNE = [
  'Attribution de compensation reçue (fonctionnement)',
  'Attribution de compensation versée (fonctionnement)',
  'Attribution de compensation reçue (investissement)',
  'Attribution de compensation versée (investissement)',
  'Dotation de solidarité communautaire reçue',
  'Dotation de solidarité communautaire versée',
]

/** Flux 2025 entre la commune et son intercommunalité, puis FPIC de l'ensemble intercommunal. */
export function blocSolidarite(insee: string, nom: string, epci: { siren: string; nom: string } | null, o: OfglDep | null, oSiege: OfglDep | null): string {
  if (!o) return absent('Données de l’OFGL non disponibles.')
  const c = o.communes[insee]
  const morceaux: string[] = ['<h3>Flux avec l’intercommunalité</h3>']
  if (c?.flux) {
    const lignes = c.flux.map((v, i) => [h(LIBELLES_FLUX_COMMUNE[i]), h(montant(v))]).filter((_, i) => !nul(c.flux![i]) && c.flux![i] !== 0)
    morceaux.push(
      lignes.length
        ? tableau(`Flux entre ${h(nom)} et ${h(epci?.nom ?? 'son intercommunalité')}, ${h(o.annee_flux_communes ?? '')}, budget principal de la commune`, ['Flux', `Montant ${h(o.annee_flux_communes ?? '')}`], lignes)
        : `<p>Aucune attribution de compensation ni dotation de solidarité communautaire dans les comptes ${h(o.annee_flux_communes ?? '')} de ${h(nom)} (budget principal).</p>`,
      '<p class="aide">Attribution de compensation : ce que l’intercommunalité reverse à la commune (ou lui demande) pour compenser les impôts et les charges transférés. Ces montants figurent déjà dans le budget de la commune et dans celui de l’intercommunalité : ne pas les ajouter.</p>',
    )
  } else morceaux.push(encadreManque(MANQUES.fluxIntercommunalite(nom, o.annee_flux_communes)))
  const ens = epci ? oSiege?.epci[epci.siren] : null
  const fpic = ens?.fpic ?? c?.fpic
  morceaux.push('<h3>Solidarité entre territoires (FPIC)</h3>')
  if (fpic) {
    const ans = cinqDernieres(Object.keys(fpic))
    morceaux.push(
      `<p>Fonds national de péréquation des ressources intercommunales et communales : montants de l’ensemble ${h(epci ? `formé par ${epci.nom} et ses communes` : `de la commune isolée ${nom}`)}, avant répartition entre ${epci ? 'l’intercommunalité et ses communes' : 'les budgets'}.</p>`,
      tableau(`Fonds de péréquation (FPIC), ${h(epci?.nom ?? nom)}`, ['Année', 'Prélèvement', 'Reversement', 'Solde publié'], ans.map((a) => [h(a), h(montant(fpic[a][0])), h(montant(fpic[a][1])), h(montant(fpic[a][2]))])),
      '<p class="aide">Solde : reversement moins prélèvement, tel que publié par la DGCL.</p>',
    )
  } else morceaux.push(absent('Pas de montant du FPIC publié pour cet ensemble intercommunal.'))
  return `${morceaux.join('')}${source(o.source.split(' ; ').filter((s) => /fpic|flux/.test(s)).join(' ; '), o.millesime)}`
}

/** Patrimoine réévalué, dépenses pour les élus (total), police municipale. */
export function blocMoyens(insee: string, nom: string, o: OfglDep | null, e: ElusDep | null, ei: ElusIndex | null, p: Police | null, pi: PoliceIndex | null): string {
  const m: string[] = ['<h3>Patrimoine</h3>']
  const pat = o?.communes[insee]?.patrimoine
  if (o && pat) {
    m.push(
      tableau(`Patrimoine de ${h(nom)} au 31 décembre ${h(o.annee_patrimoine ?? '')}, réévalué par l’OFGL`, ['Indicateur', 'Valeur publiée'], [
        ['Actif brut (valeur d’acquisition des biens)', h(montant(pat[0]))],
        ['Actif net (après amortissements)', h(montant(pat[1]))],
        ['Actif brut par habitant', h(montant(pat[2]))],
        ['Taux de vétusté', nul(pat[4]) ? 'non publié' : h(pct(pat[4]))],
        ['Dotation aux amortissements de l’année', h(montant(pat[5]))],
      ]),
      '<p class="aide">Valeurs calculées par l’OFGL à partir des comptes de gestion, selon sa méthode de réévaluation.</p>',
      source(o.source.split(' ; ').filter((s) => /actifs/.test(s)).join(' ; '), o.millesime),
    )
  } else m.push(absent('Patrimoine réévalué non publié pour cette commune.'))
  m.push('<h3>Indemnités et frais des élus</h3>')
  const s = e?.communes[insee]
  if (e && s) {
    const ans = cinqDernieres(Object.keys(s))
    m.push(
      tableau(`Dépenses pour les élus de ${h(nom)} (compte 653, budget principal), total de la commune`, ['Exercice', 'Montant mandaté'], ans.map((a) => [h(a), h(montant(s[a][0]))])),
      `<p class="aide">${h(ei?.definitions.c653 ?? '')} Montant global : la source ne publie ni le nombre d’élus indemnisés ni le montant de chacun. ${h(ei?.plafond ?? '')}</p>`,
      source(e.source, e.millesime),
    )
  } else m.push(absent('Aucune balance comptable du budget principal publiée sous le SIREN de cette commune.'))
  m.push('<h3>Police municipale</h3>')
  const pm = p?.communes[insee]
  if (p && pm) {
    const ans = cinqDernieres(Object.keys(pm))
    m.push(
      tableau(`Effectifs déclarés par ${h(nom)} à l’enquête du ministère de l’Intérieur`, ['Année', 'Policiers municipaux', 'ASVP', 'Gardes champêtres'], ans.map((a) => [h(a), ...pm[a].map((v) => h(nul(v) ? 'non publié' : entier(v)))])),
      '<p class="aide">ASVP : agents de surveillance de la voie publique. Rattachement par le nom de la commune (la source ne donne pas de code Insee).</p>',
      source(p.source, p.millesime),
    )
  } else if (p) m.push(encadreManque(MANQUES.policeMunicipale(nom, pi?.annees, pi?.fiche)))
  else m.push(absent('Effectifs de police municipale non disponibles.'))
  return m.join('')
}

// ------------------------------------------------------------------------------------------------------- habitants

const CLES_CAF = ['ndur', 'rsa', 'ppa', 'ndural', 'apl', 'af', 'ndurpaje']

/** Prestations de la CAF, inscrits à France Travail, impôt sur la fortune immobilière. */
export function blocHabitants(insee: string, nom: string, epci: { siren: string; nom: string } | null, caf: CafDep | null, cafSiege: CafDep | null, ci: CafIndex | null, dares: Dares | null, ifi: Ifi | null, ii: IfiIndex | null): string {
  const m: string[] = ['<h3>Prestations de la CAF</h3>']
  const c = caf?.communes[insee]
  const iF = (cle: string) => caf!.colonnes.indexOf(`${cle}_foyers`)
  const iM = (cle: string) => caf!.colonnes.indexOf(`${cle}_montant_decembre`)
  const lignesCaf = (v: (number | null)[]) => CLES_CAF.map((k) => [h(ci?.prestations[k] ?? k), h(effectif(v[iF(k)])), h(montant(v[iM(k)]))])
  if (caf && c && (derniere(c.annees) || c.arrondissements)) {
    const an = derniere(c.annees)
    if (an) m.push(tableau(`Foyers allocataires de ${h(nom)} et montant versé au titre de décembre ${h(an)}`, ['Prestation', 'Foyers', 'Montant de décembre'], lignesCaf(c.annees[an])))
    if (c.arrondissements) {
      const codes = Object.keys(c.arrondissements).sort()
      const a2 = derniere(c.arrondissements[codes[0]])!
      m.push(
        `<p>La CNAF publie ${h(nom)} par arrondissement : chiffres de chaque arrondissement, non additionnés.</p>`,
        tableau(`Foyers allocataires par arrondissement, décembre ${h(a2)}`, ['Arrondissement', 'Au moins une prestation', 'RSA', 'Prime d’activité', 'Aides au logement'], codes.map((k) => {
          const v = c.arrondissements![k][a2] ?? []
          return [h(k), ...['ndur', 'rsa', 'ppa', 'ndural'].map((x) => h(effectif(v[iF(x)])))]
        })),
      )
    }
    const quartiers = (c.qpv ?? []).filter((q) => q[3])
    if (quartiers.length)
      m.push(tableau(`Quartiers prioritaires de ${h(nom)} : foyers allocataires, décembre ${h(quartiers[0][2])}`, ['Quartier', 'Au moins une prestation', 'RSA', 'Prime d’activité', 'Aides au logement'], quartiers.map((q) => [h(q[1] ?? q[0]), ...['ndur', 'rsa', 'ppa', 'ndural'].map((x) => h(effectif(q[3][iF(x)])))])))
    if ((c.iris ?? []).length > 1) m.push(`<p class="aide">${h(entier(c.iris!.length))} quartiers statistiques (IRIS) publiés par la CNAF pour ${h(nom)} ; chiffres par quartier dans le fichier de données de la page.</p>`)
    m.push(`<p class="aide">${h(ci?.secret_statistique ?? '')} ${h(ci?.montant ?? '')}</p>`)
  } else m.push(absent('Prestations de la CAF non publiées pour cette commune.'))
  const e = epci ? cafSiege?.epci[epci.siren] : null
  const aAah = derniere(e?.aah_aeeh)
  m.push(encadreManque(MANQUES.aahCommune(nom)))
  if (e && aAah) m.push(`<p>À l’échelle de ${h(epci!.nom)} : ${h(effectif(e.aah_aeeh[aAah][0]))} bénéficiaires de l’allocation aux adultes handicapés et ${h(effectif(e.aah_aeeh[aAah][1]))} de l’allocation d’éducation de l’enfant handicapé (décembre ${h(aAah)}).</p>`)
  if (caf) m.push(source(caf.source, caf.millesime))

  m.push('<h3>Inscrits à France Travail</h3>')
  const d = dares?.communes[insee]
  if (dares && d) {
    const idx = dares.annees.map((a, i) => [a, i] as const).slice(-5)
    m.push(
      tableau(`Demandeurs d’emploi inscrits en catégories A, B et C domiciliés à ${h(nom)}, moyenne du 4e trimestre`, ['Année', 'Inscrits'], idx.map(([a, i]) => [h(a), h(effectif(d[i]))])),
      '<p class="aide">Effectifs arrondis à 5 par la Dares. Ce n’est pas un montant versé : contexte local des dépenses pour l’emploi.</p>',
      source(dares.source, dares.millesime),
    )
  } else m.push(absent('Inscrits à France Travail non publiés pour cette commune.'))

  m.push('<h3>Impôt sur la fortune immobilière</h3>')
  const f = ifi?.communes[insee]
  if (ifi && f && (derniere(f.annees) || f.arrondissements)) {
    const ans = cinqDernieres(Object.keys(f.annees))
    if (ans.length)
      m.push(tableau(`Foyers redevables de l’impôt sur la fortune immobilière domiciliés à ${h(nom)}`, ['Année', 'Redevables', 'Patrimoine moyen', 'Impôt moyen'], ans.map((a) => [h(a), h(entier(f.annees[a][0])), h(eurLisible(f.annees[a][1])), h(eur(f.annees[a][2]))])))
    if (f.arrondissements) {
      const codes = Object.keys(f.arrondissements).sort()
      const a2 = derniere(f.arrondissements[codes[0]].annees)!
      m.push(tableau(`Par arrondissement, ${h(a2)} (non additionnés)`, ['Arrondissement', 'Redevables', 'Patrimoine moyen', 'Impôt moyen'], codes.filter((k) => f.arrondissements![k].annees[a2]).map((k) => {
        const v = f.arrondissements![k].annees[a2]
        return [h(f.arrondissements![k].nom_source), h(entier(v[0])), h(eurLisible(v[1])), h(eur(v[2]))]
      })))
    }
    m.push(`<p class="aide">Moyennes publiées par la DGFiP. ${h(ii?.rupture ?? '')}</p>`, source(ifi.source, ifi.millesime))
  } else if (ifi) m.push(encadreManque(MANQUES.ifiSousSeuil(nom, ii?.annees, ii?.fiche)))
  else m.push(absent('Impôt sur la fortune immobilière non disponible.'))
  return m.join('')
}

// --------------------------------------------------------------------------------------------------------- département

const LIBELLES_SDIS = ['Dépenses totales (hors remboursements d’emprunts)', 'Dépenses de fonctionnement', 'Dépenses d’investissement (hors remboursements)', 'Frais de personnel', 'Participations des départements', 'Participations des communes', 'Participations des intercommunalités', 'Encours de dette']
const LIBELLES_UNEDIC = ['Allocataires pris en charge', 'Allocataires indemnisés', 'Montant moyen d’indemnisation mensuel net', 'Dépense d’allocations du mois', 'Part des allocataires ayant travaillé dans le mois']

/** Pompiers (SDIS), assurance chômage, patients par pathologie, établissements publics locaux du département. */
export function blocDepartementServices(dep: string, nomDep: string, o: OfglDep | null, u: Unedic | null, pa: Patho | null, pi: PathoIndex | null): string {
  const m: string[] = ['<h3>Service d’incendie et de secours</h3>']
  const s = o?.sdis
  const an = derniere(s?.annees)
  if (o && s && an) {
    m.push(
      tableau(`Comptes du SDIS de ${h(nomDep)}, ${h(an)}, budget principal`, ['Poste', 'Montant', 'Par habitant (OFGL)'], LIBELLES_SDIS.map((l, i) => [h(l), h(montant(s.annees[an][i])), h(montant(s.par_habitant[an]?.[i]))])),
      '<p class="aide">Les participations des communes, des intercommunalités et du département figurent déjà dans leurs propres budgets : ne pas les ajouter.</p>',
      source(o.source.split(' ; ').filter((x) => /sdis/.test(x)).join(' ; '), o.millesime),
    )
  } else m.push(encadreManque(MANQUES.sdisAbsent(nomDep)))
  m.push('<h3>Assurance chômage</h3>')
  const ud = u?.departements[dep]
  const mois = ud ? Object.keys(ud.mois).sort().pop() : undefined
  if (u && ud && mois) {
    const v = ud.mois[mois]
    m.push(
      tableau(`Assurance chômage dans le département, ${h(mois)}`, ['Indicateur', 'Valeur publiée'], LIBELLES_UNEDIC.map((l, i) => [h(l), h(nul(v[i]) ? 'non publié' : i === 4 ? pct(v[i]!) : i >= 2 ? eur(v[i]!) : entier(v[i]!))])),
      source(u.source, u.millesime),
    )
  } else m.push(absent('Indicateurs de l’Assurance chômage non publiés pour ce département.'))
  m.push('<h3>Patients par pathologie</h3>')
  const pd = pa?.departements[dep]
  const ap = derniere(pd?.annees)
  if (pa && pd && ap && pi) {
    const lignes = pa.pathologies
      .map((code, i) => ({ p: pi.pathologies[code], v: pd.annees[ap][i] }))
      .filter((x) => x.p && x.p.niveau <= 1 && x.v)
      .map((x) => [h(x.p.libelle), h(effectif(x.v![0])), x.p.niveau === 0 ? '' : h(nul(x.v![1]) ? 'non publiée' : pct(x.v![1]!))])
    m.push(
      tableau(`Patients pris en charge par l’Assurance maladie dans le département, ${h(ap)}`, ['Groupe de pathologies', 'Patients', 'Prévalence publiée'], lignes),
      '<p class="aide">Ordre de présentation de la Cnam. Effectifs, pas des montants : les dépenses par pathologie ne sont publiées qu’au niveau national.</p>',
      source(pa.source, pa.millesime),
      `<p class="aide">${h(pa.mention)}</p>`,
    )
  } else m.push(absent('Effectifs de patients non publiés pour ce département.'))
  m.push('<h3>Établissements publics locaux</h3>')
  if (o) {
    const parCat = new Map<string, number>()
    for (const x of o.organismes) parCat.set(x[2] ?? 'Autre', (parCat.get(x[2] ?? 'Autre') ?? 0) + 1)
    const nommes = o.organismes
      .map((x) => ({ nom: x[1], cat: x[2], act: x[3], an: derniere(x[4]), v: x[4] }))
      .filter((x) => x.nom && x.an)
      .map((x) => ({ ...x, dep: x.v[x.an!][0] }))
      .filter((x) => !nul(x.dep))
      .sort((a, b) => (b.dep as number) - (a.dep as number) || a.nom!.localeCompare(b.nom!, 'fr'))
    m.push(
      `<p>${h(entier(o.organismes.length))} établissements publics locaux (EPA, régies personnalisées, groupements d’intérêt public) publiés par l’OFGL dans le département : ${[...parCat.entries()].sort((a, b) => a[0].localeCompare(b[0], 'fr')).map(([k, n]) => `${h(k)} ${h(entier(n))}`).join(', ')}.</p>`,
      nommes.length ? tableau(`Les ${Math.min(5, nommes.length)} dépenses les plus élevées du dernier exercice publié`, ['Établissement', 'Exercice', 'Dépenses totales'], nommes.slice(0, 5).map((x) => [h(`${x.nom}${x.act ? ` (${x.act})` : ''}`), h(x.an!), h(montant(x.dep))])) : '',
      '<p class="aide">Ordre : dépenses décroissantes, puis nom. Établissements nommés : personnes morales seulement (répertoire SIRENE). Leurs dépenses ne s’ajoutent pas aux budgets des collectivités.</p>',
      source(o.source.split(' ; ').filter((x) => /epl/.test(x)).join(' ; '), o.millesime),
    )
  }
  return m.join('')
}

// ------------------------------------------------------------------------------------------------------ chargement

export interface Contexte { insee: string; nom: string; dep: string; nomDep: string; epci: { siren: string; nom: string; siege: string } | null }

/** Contenu de chaque section, chargé à la demande. */
export const CHARGEURS: Record<string, (c: Contexte) => Promise<string>> = {
  'mc-solidarite': async (c) => {
    const [o, os] = await Promise.all([chargerSiPresent<OfglDep>(`ofgl_complements/communes/${c.dep}.json`), c.epci && c.epci.siege !== c.dep ? chargerSiPresent<OfglDep>(`ofgl_complements/communes/${c.epci.siege}.json`) : Promise.resolve(null)])
    return blocSolidarite(c.insee, c.nom, c.epci, o, os ?? o)
  },
  'mc-moyens': async (c) => {
    const [o, e, ei, p, pi] = await Promise.all([
      chargerSiPresent<OfglDep>(`ofgl_complements/communes/${c.dep}.json`),
      chargerSiPresent<ElusDep>(`elus_indemnites/communes/${c.dep}.json`),
      chargerSiPresent<ElusIndex>('elus_indemnites/index.json'),
      chargerSiPresent<Police>('police_municipale/communes.json'),
      chargerSiPresent<PoliceIndex>('police_municipale/index.json'),
    ])
    return blocMoyens(c.insee, c.nom, o, e, ei, p, pi)
  },
  'mc-habitants': async (c) => {
    const [caf, cafS, ci, d, f, fi] = await Promise.all([
      chargerSiPresent<CafDep>(`caf_communes/communes/${c.dep}.json`),
      c.epci && c.epci.siege !== c.dep ? chargerSiPresent<CafDep>(`caf_communes/communes/${c.epci.siege}.json`) : Promise.resolve(null),
      chargerSiPresent<CafIndex>('caf_communes/index.json'),
      chargerSiPresent<Dares>(`emploi_territoires/communes/${c.dep}.json`),
      chargerSiPresent<Ifi>('ifi_communes/communes.json'),
      chargerSiPresent<IfiIndex>('ifi_communes/index.json'),
    ])
    return blocHabitants(c.insee, c.nom, c.epci, caf, cafS ?? caf, ci, d, f, fi)
  },
  'mc-dep-services': async (c) => {
    const [o, u, pa, pi] = await Promise.all([
      chargerSiPresent<OfglDep>(`ofgl_complements/communes/${c.dep}.json`),
      chargerSiPresent<Unedic>('emploi_territoires/departements.json'),
      chargerSiPresent<Patho>('pathologies_departements/departements.json'),
      chargerSiPresent<PathoIndex>('pathologies_departements/index.json'),
    ])
    return blocDepartementServices(c.dep, c.nomDep, o, u, pa, pi)
  },
}

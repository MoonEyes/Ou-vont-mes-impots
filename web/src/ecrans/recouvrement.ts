// Collecte, contrôle et recouvrement (site/data/recouvrement/) : qui collecte, les frais de gestion de l'impôt
// quand c'est publié, montants notifiés et encaissés après contrôle (jamais confondus ni rapportés l'un à l'autre),
// estimations d'écart ou de fraude côte à côte avec producteur, méthode et fourchette (jamais additionnées).
import { partPersonnelle } from '../composants/hub'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { badgeStatut, entier, h, pct, source, sur100, surligne } from '../util'
import { enCours } from './dette'

type Valeur = number | null
interface Source {
  id: string
  url: string
  page: number | null
}
interface Montant {
  libelle: string
  valeur: number
  unite: string
  precision?: string | null
}
interface Vue {
  id: string
  sphere: string
  titre: string
  producteur: string
  annee: number
  notifie: Montant[]
  encaisse: Montant[]
  restitution: Montant[]
  estimation: (Montant & { valeur_basse?: number; valeur_haute?: number })[]
  encaisse_note?: string
}
interface Index {
  millesime: string
  source: string
  avertissement: string
  notions: Record<string, { libelle: string; definition: string }>
  regles: string[]
  vues: Vue[]
  sources: { id: string; titre: string; producteur: string; url: string; licence: string }[]
  sources_inaccessibles: { source: string; motif: string }[]
  confidentialite: string
  limites: string[]
}
interface Serie {
  id: string
  libelle: string
  notion: string
  annees: number[]
  valeurs: Valeur[]
}
interface ControleFiscal {
  millesime: string
  source: string
  perimetre: string
  methode: string
  series: Serie[]
  ruptures: { annee: number; texte: string }[]
  lecture_ecart: string
  ecarts_entre_sources: { serie: string; annee: number; valeur: number; autre_valeur: number; ecart: number }[]
  taux_recouvrement: { date: string; taux_net_pct: number; taux_brut_pct: number; perimetre: string; methode: string; citation: string }
}
interface ControleUrssaf {
  millesime: string
  source: string
  avertissement: string
  perimetre: string
  annees: number[]
  controle: { total: { nombre_actions: Valeur[]; redressements_eur: Valeur[]; restitutions_eur: Valeur[] } }
  travail_dissimule: { total: { nombre_actions: Valeur[]; redressements_eur: Valeur[] } }
  regle: string
  organismes: { organisme: string; region: string; controle: { redressements_eur: Valeur[]; restitutions_eur: Valeur[] }; travail_dissimule: { redressements_eur: Valeur[] } }[]
}
interface Estimation {
  id: string
  sphere: string
  objet: string
  producteur: string
  publication: string
  annee_donnees: number | null
  annee_donnees_note?: string
  perimetre: string
  methode: string
  valeur: Valeur
  valeur_basse: Valeur
  valeur_haute: Valeur
  unite: string
  repere: string | null
  citation: string
  langue_citation: string
  source: Source
}
interface Estimations {
  millesime: string
  source: string
  avertissement: string
  regle: string
  estimations: Estimation[]
  estimation_ensemble_fraude_fiscale: { valeur: null; note: string }
  constats: { id: string; sphere: string; producteur: string; texte: string; citation: string; source: Source }[]
  securite_sociale_detecte_recouvre: {
    perimetre: string
    methode: string
    montants: { id: string; notion: string; terme_source: string; libelle: string; annee: number; valeur: number; unite: string; precision: string | null; citation: string; source: Source }[]
  }
}
interface Apurements {
  millesime: string
  source: string
  avertissement: string
  definitions: Record<string, string>
  annees: number[]
  comptes: { compte: string; categorie: string; champ: string; montants_eur: Valeur[] }[]
}
interface Impayes {
  millesime: string
  source: string
  avertissement: string
  perimetre: string
  taux: Record<string, string>
  national: { mois: string[]; fin_mois: Valeur[]; fin_mois_suivant: Valeur[]; a_90_jours: Valeur[] }
  regions: { region: string; mois: string[]; fin_mois: Valeur[]; fin_mois_suivant: Valeur[]; a_90_jours: Valeur[] }[]
}
interface Indicateur {
  sous_indicateur: string
  unite: string
  valeurs: { annee: number; valeur: number; source: string }[]
}

// Aucun sigle seul : chaque sigle est développé à sa première apparition dans un texte (sauf dans les citations exactes).
const SIGLES: [string, string][] = [
  ['DGFiP', 'Direction générale des finances publiques'],
  ['DGDDI', 'Direction générale des douanes et droits indirects'],
  ['HCFiPS', 'Haut Conseil du financement de la protection sociale'],
  ['DG TAXUD', 'direction générale de la fiscalité et de l’union douanière'],
  ['Acoss', 'Agence centrale des organismes de sécurité sociale'],
  ['STDR', 'service de traitement des déclarations rectificatives'],
  ['PLF', 'projet de loi de finances'],
  ['MSA', 'Mutualité sociale agricole'],
  ['CGSS', 'Caisse générale de sécurité sociale'],
  ['CSS', 'Caisse de sécurité sociale'],
]
const sansAccent = (t: string) => t.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
export function developper(texte: string): string {
  let t = texte
  for (const [sigle, long] of SIGLES) {
    const re = new RegExp(`(?<![\\p{L}\\p{N}])${sigle}(?![\\p{L}\\p{N}])`, 'u')
    const m = re.exec(t)
    if (!m || sansAccent(t).includes(sansAccent(long))) continue
    // Déjà entre parenthèses (« hors douane (DGDDI) ») : le nom complet remplace le sigle, sans parenthèses imbriquées.
    const avant = t.slice(0, m.index)
    const ouvert = (avant.match(/\(/g) ?? []).length > (avant.match(/\)/g) ?? []).length
    t = t.slice(0, m.index) + (ouvert ? long : `${long} (${sigle})`) + t.slice(m.index + sigle.length)
  }
  return t
}
const d = (t: string) => h(developper(t))

const nf1 = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
/** Montant lisible dans l'unité de la source : M€ au-delà de 1 000 passent en Md€, € en M€ ou Md€. */
export function montant(valeur: number, unite: string): string {
  if (unite === '€') {
    const a = Math.abs(valeur)
    if (a >= 1e9) return `${nf1.format(valeur / 1e9)} Md€`
    if (a >= 1e7) return `${entier(Math.round(valeur / 1e6))} M€`
    if (a >= 1e6) return `${nf1.format(valeur / 1e6)} M€`
    return `${entier(Math.round(valeur / 1e3))} k€`
  }
  if (unite === 'M€') return Math.abs(valeur) >= 1000 ? `${nf1.format(valeur / 1000)} Md€` : `${entier(valeur)} M€`
  return `${nf1.format(valeur)} ${unite}`
}
export function valeurEstimation(e: { valeur: Valeur; valeur_basse?: Valeur; valeur_haute?: Valeur; unite: string }): string {
  if (e.valeur !== null && e.valeur !== undefined) return montant(e.valeur, e.unite)
  if (e.valeur_basse != null && e.valeur_haute != null) return `entre ${nf1.format(e.valeur_basse)} et ${montant(e.valeur_haute, e.unite)}`
  return 'non publiée'
}
const avecPrecision = (m: { valeur: number; unite: string; precision?: string | null }) => `${m.precision ? `${m.precision} ` : ''}${montant(m.valeur, m.unite)}`
const cellule = (v: Valeur, unite: string) => `<td class="nombre">${v === null || v === undefined ? 'non publié' : h(montant(v, unite))}</td>`
const lienExterne = (url: string, texte: string) => (/^https:\/\//.test(url) ? `<a href="${h(url)}" rel="noopener noreferrer">${h(texte)}</a>` : h(texte))
const citation = (texte: string, langue: string, src: Source | undefined, titres: Map<string, string>) =>
  `<blockquote class="recouvrement-citation"${langue && langue !== 'fr' ? ` lang="${h(langue)}"` : ''}><p>« ${h(texte)} »</p>${
    src ? `<footer class="aide">${lienExterne(src.url, titres.get(src.id) ?? 'Document source')}${src.page ? `, page ${h(src.page)}` : ''}${langue === 'en' ? ' (citation en anglais)' : ''}</footer>` : ''
  }</blockquote>`

export async function rendre(cible: HTMLElement) {
  const [idx, cf, cu, est, apu, imp, p156] = await Promise.all([
    chargerSiPresent<Index>('recouvrement/index.json'),
    chargerSiPresent<ControleFiscal>('recouvrement/controle_fiscal.json'),
    chargerSiPresent<ControleUrssaf>('recouvrement/controle_urssaf.json'),
    chargerSiPresent<Estimations>('recouvrement/estimations.json'),
    chargerSiPresent<Apurements>('recouvrement/apurements_etat.json'),
    chargerSiPresent<Impayes>('recouvrement/impayes.json'),
    chargerSiPresent<{ resultats_mesures?: { indicateurs?: Indicateur[] } }>('realisations/156.json'),
  ])
  if (!idx) {
    cible.innerHTML =
      enCours('Collecte et contrôle des impôts et des cotisations', 'Qui collecte, montants notifiés et encaissés après contrôle, estimations publiées.') + partPersonnelle()
    return
  }
  const titres = new Map(idx.sources.map((s) => [s.id, s.titre]))
  const notion = (n: string) => idx.notions[n]

  // Coût de gestion de l'impôt : indicateur publié du programme 156 (taux d'intervention sur l'impôt), dernière année.
  const ti = p156?.resultats_mesures?.indicateurs?.find((i) => i.sous_indicateur === 'Taux d’intervention sur l’impôt' || i.sous_indicateur === "Taux d'intervention sur l'impôt")
  const tiDernier = ti?.valeurs.length ? [...ti.valeurs].sort((a, b) => a.annee - b.annee)[ti.valeurs.length - 1] : null
  const cout = tiDernier
    ? `<div class="carte" data-cle>
  <p>Pour 100 € d’impôts gérés par la Direction générale des finances publiques, ses frais de gestion de l’impôt représentent en ${h(tiDernier.annee)} :</p>
  <p class="grand-chiffre">${surligne(sur100(tiDernier.valeur))}</p>
  <p class="sous-chiffre">sur 100 € (taux d’intervention sur l’impôt : ${h(nf2.format(tiDernier.valeur))} %, indicateur de performance du programme 156 « Gestion fiscale et financière de l’État et du secteur public local »).</p>
  ${source(`${tiDernier.source}, indicateur publié par l’administration`)}
  <p><a href="${lien('/decisions/realisations', { p: '156' })}">Toutes les années de cet indicateur et la dépense du programme 156</a></p>
</div>`
    : `<p class="absent">Le taux d’intervention sur l’impôt n’est pas disponible dans les données chargées.</p>`

  // Vues par producteur : notifié, encaissé, restitution, estimation, toujours séparés.
  const ligneMontants = (titre: string, cle: string, liste: Montant[], note?: string) =>
    `<div><h4 data-notion="${cle}">${h(titre)}</h4>${
      liste.length
        ? `<ul>${liste.map((m) => `<li><strong>${h(avecPrecision(m))}</strong> : ${d(m.libelle)}</li>`).join('')}</ul>`
        : `<p class="aide">${badgeStatut('nonpub')} ${note ? d(note) : 'Non publié.'}</p>`
    }</div>`
  const vue = (v: Vue) => `<article class="carte recouvrement-vue" data-vue="${h(v.id)}">
  <h3>${d(v.titre)} (${h(v.annee)})</h3>
  <p class="aide">Producteur : ${d(v.producteur)}</p>
  <div class="recouvrement-notions">
    ${ligneMontants(notion('notifie').libelle, 'notifie', v.notifie)}
    ${ligneMontants(notion('encaisse').libelle, 'encaisse', v.encaisse, v.encaisse_note)}
    ${v.restitution.length ? ligneMontants(notion('restitution').libelle, 'restitution', v.restitution) : ''}
  </div>
</article>`

  const parSphere = (s: string) => idx.vues.filter((v) => v.sphere === s)

  // Contrôle fiscal : tableau 2016-2024 du document budgétaire (notifié et encaissé dans deux colonnes distinctes).
  const serie = (id: string) => cf?.series.find((s) => s.id === id)
  const tf = serie('dpt_total_droits_penalites')
  const tc = serie('dpt_credits_non_rembourses')
  const te = serie('dpt_encaissements_total')
  const tAnnu = serie('annuaire_total_droits')
  const fiscal =
    cf && tf && te
      ? `<div class="tableau-defile"><table>
<caption>Contrôle fiscal de la Direction générale des finances publiques, par année : montants notifiés et montants encaissés (deux notions distinctes)</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Notifié : droits et pénalités</th><th scope="col" class="nombre">Notifié : crédits d’impôt et taxes non remboursés</th><th scope="col" class="nombre">Encaissé dans l’année</th></tr></thead>
<tbody>${[...tf.annees]
          .reverse()
          .map((a) => {
            const i = tf.annees.indexOf(a)
            const ic = tc ? tc.annees.indexOf(a) : -1
            const ie = te.annees.indexOf(a)
            return `<tr><th scope="row">${h(a)}</th>${cellule(tf.valeurs[i], 'M€')}${cellule(ic >= 0 ? tc!.valeurs[ic] : null, 'M€')}${cellule(ie >= 0 ? te.valeurs[ie] : null, 'M€')}</tr>`
          })
          .join('')}</tbody></table></div>
<p class="aide">${d(cf.perimetre)}</p>
<p class="aide">Les encaissements d’une année portent sur des contrôles de plusieurs années : aucun rapport entre la colonne « encaissé » et les colonnes « notifié » n’est calculé ici.</p>
<div class="carte carte-contour">
  <h3>Taux de recouvrement publié par l’administration</h3>
  <p>Au ${h(new Date(cf.taux_recouvrement.date + 'T00:00:00Z').toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }))} : <strong>${h(pct(cf.taux_recouvrement.taux_net_pct, 2))}</strong> (taux net) et <strong>${h(pct(cf.taux_recouvrement.taux_brut_pct, 2))}</strong> (taux brut) des créances issues du contrôle fiscal.</p>
  <p class="aide">${d(cf.taux_recouvrement.methode)}</p>
  ${citation(cf.taux_recouvrement.citation, 'fr', { id: 'dpt_2026', url: idx.sources.find((s) => s.id === 'dpt_2026')?.url ?? '', page: 63 }, titres)}
</div>
${
  tAnnu
    ? `<details><summary>Série longue 1996 à 2019 (annuaires statistiques) et écarts entre les deux sources</summary>
<div class="tableau-defile"><table><caption>Droits simples rappelés après contrôle sur place et sur pièces, annuaires statistiques (montants notifiés)</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Droits simples rappelés</th></tr></thead>
<tbody>${[...tAnnu.annees]
        .reverse()
        .map((a, k) => `<tr><th scope="row">${h(a)}</th>${cellule(tAnnu.valeurs[tAnnu.annees.length - 1 - k], 'M€')}</tr>`)
        .join('')}</tbody></table></div>
<p class="aide">${d(cf.lecture_ecart)}</p>
<ul>${cf.ruptures.map((r) => `<li>${h(r.annee)} : ${d(r.texte)}</li>`).join('')}</ul>
<div class="tableau-defile"><table><caption>Même série, mêmes années, deux sources : droits simples rappelés (millions d’euros)</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Annuaires statistiques</th><th scope="col" class="nombre">Document annexé au projet de loi de finances 2026</th><th scope="col" class="nombre">Écart (document annexé moins annuaires)</th></tr></thead>
<tbody>${cf.ecarts_entre_sources
        .filter((e) => e.serie === 'total_droits')
        .map((e) => `<tr><th scope="row">${h(e.annee)}</th><td class="nombre">${h(entier(e.valeur))}</td><td class="nombre">${h(entier(e.autre_valeur))}</td><td class="nombre">${h(entier(e.ecart))}</td></tr>`)
        .join('')}</tbody></table></div>
</details>`
    : ''
}
${source(developper(cf.source), cf.millesime)}`
      : '<p class="absent">Le détail du contrôle fiscal n’est pas disponible.</p>'

  // Urssaf : redressements et restitutions toujours côte à côte ; travail dissimulé à part, non additionné.
  const urssaf = cu
    ? `<div class="tableau-defile"><table>
<caption>Contrôles des Urssaf par année : redressements notifiés, restitutions aux cotisants, redressements pour travail dissimulé (séries publiées séparément, non additionnées)</caption>
<thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Contrôles d’assiette : redressements</th><th scope="col" class="nombre">Contrôles d’assiette : restitutions</th><th scope="col" class="nombre">Travail dissimulé : redressements</th></tr></thead>
<tbody>${[...cu.annees]
        .map((a, i) => ({ a, i }))
        .reverse()
        .map(({ a, i }) => `<tr><th scope="row">${h(a)}</th>${cellule(cu.controle.total.redressements_eur[i], '€')}${cellule(cu.controle.total.restitutions_eur[i], '€')}${cellule(cu.travail_dissimule.total.redressements_eur[i], '€')}</tr>`)
        .join('')}</tbody></table></div>
<p class="aide">${d(cu.avertissement)}</p>
<p class="aide">${d(cu.regle)}</p>
<p class="aide">${d(cu.perimetre)}</p>
<details><summary>Par organisme en ${h(cu.annees[cu.annees.length - 1])} (${h(cu.organismes.length)} organismes, ordre alphabétique)</summary>
<div class="tableau-defile"><table><caption>Contrôles par organisme de recouvrement en ${h(cu.annees[cu.annees.length - 1])}</caption>
<thead><tr><th scope="col">Organisme</th><th scope="col" class="nombre">Redressements</th><th scope="col" class="nombre">Restitutions</th><th scope="col" class="nombre">Travail dissimulé : redressements</th></tr></thead>
<tbody>${cu.organismes
        .map((o) => {
          const i = cu.annees.length - 1
          return `<tr><th scope="row">${d(o.organisme)}</th>${cellule(o.controle.redressements_eur[i], '€')}${cellule(o.controle.restitutions_eur[i], '€')}${cellule(o.travail_dissimule.redressements_eur[i], '€')}</tr>`
        })
        .join('')}</tbody></table></div>
</details>
${source(developper(cu.source), cu.millesime)}`
    : '<p class="absent">Le détail des contrôles des Urssaf n’est pas disponible.</p>'

  // Sécurité sociale, toutes branches : ordres de grandeur du Haut Conseil (détecté = notifié, recouvré = encaissé).
  const ss = est?.securite_sociale_detecte_recouvre
  const secu = ss
    ? `<p class="aide">Pour la sécurité sociale, la source parle de montants « ${h(ss.montants.find((m) => m.notion === 'notifie')?.terme_source ?? 'détecté')} » (rangés ici avec les montants notifiés) et « ${h(
        ss.montants.find((m) => m.notion === 'encaisse')?.terme_source ?? 'recouvré',
      )} » (rangés avec les montants encaissés). ${d(ss.perimetre)} ${d(ss.methode)}</p>`
    : ''

  // Estimations : côte à côte, chacune avec producteur, périmètre, méthode, année, fourchette et citation.
  const carteEstimation = (e: Estimation) => `<li class="carte recouvrement-estimation" data-estimation="${h(e.id)}">
  <h4>${d(e.objet)}</h4>
  <p class="recouvrement-valeur"><strong>${h(valeurEstimation(e))}</strong> ${badgeStatut('approche')}</p>
  <dl>
    <dt>Producteur</dt><dd>${d(e.producteur)}</dd>
    <dt>Publication</dt><dd>${d(e.publication)}</dd>
    <dt>Année des données</dt><dd>${e.annee_donnees !== null ? h(e.annee_donnees) : d(e.annee_donnees_note ?? 'non précisée par la source')}</dd>
    <dt>Périmètre</dt><dd>${d(e.perimetre)}</dd>
    <dt>Méthode</dt><dd>${d(e.methode)}</dd>
    ${e.repere ? `<dt>Repère donné par la source</dt><dd>${d(e.repere)}</dd>` : ''}
  </dl>
  ${citation(e.citation, e.langue_citation, e.source, titres)}
</li>`
  const constats = (s: string) =>
    (est?.constats ?? [])
      .filter((c) => c.sphere === s)
      .map((c) => `<li><p>${d(c.texte)}</p>${citation(c.citation, 'fr', c.source, titres)}</li>`)
      .join('')
  const estimations = est
    ? `<p class="avertissement">${d(est.avertissement)}</p>
<h3>Sphère fiscale (impôts)</h3>
<p>${d(est.estimation_ensemble_fraude_fiscale.note)}</p>
<ul class="recouvrement-estimations">${est.estimations.filter((e) => e.sphere === 'fiscale').map(carteEstimation).join('')}</ul>
<h3>Sphère sociale (cotisations et prestations)</h3>
<ul class="recouvrement-estimations">${est.estimations.filter((e) => e.sphere === 'sociale').map(carteEstimation).join('')}</ul>
<p class="aide" data-regle-ordre>${d(est.regle)}</p>
<details><summary>Ce que disent la Cour des comptes et le Haut Conseil sur ces estimations</summary>
<h4>Sphère fiscale</h4><ul class="recouvrement-constats">${constats('fiscale')}</ul>
<h4>Sphère sociale</h4><ul class="recouvrement-constats">${constats('sociale')}</ul>
</details>
${source(developper(est.source), est.millesime)}`
    : '<p class="absent">Les estimations ne sont pas disponibles.</p>'

  // Créances retirées des comptes de l'État.
  const apurements = apu
    ? `<h2>Créances que l’État cesse de poursuivre</h2>
<p>${d(notion('apurement').definition)}</p>
<div class="tableau-defile"><table><caption>Admissions en non-valeur et décisions gracieuses inscrites dans les comptes de l’État, par année</caption>
<thead><tr><th scope="col">Année</th>${apu.comptes.map((c) => `<th scope="col" class="nombre">${h(c.categorie === 'admission_en_non_valeur' ? 'Admissions en non-valeur' : 'Décisions gracieuses')} : ${h(c.champ)}</th>`).join('')}</tr></thead>
<tbody>${[...apu.annees]
        .map((a, i) => ({ a, i }))
        .reverse()
        .map(({ a, i }) => `<tr><th scope="row">${h(a)}</th>${apu.comptes.map((c) => cellule(c.montants_eur[i], '€')).join('')}</tr>`)
        .join('')}</tbody></table></div>
<p class="aide">${d(apu.avertissement)}</p>
${source(developper(apu.source), apu.millesime)}`
    : ''

  // Taux d'impayés des cotisations : dernier mois connu pour chaque taux (le taux à 90 jours arrive trois mois plus tard).
  const dernierConnu = (mois: string[], v: Valeur[]) => {
    for (let i = v.length - 1; i >= 0; i--) if (v[i] !== null && v[i] !== undefined) return { mois: mois[i], v: v[i] as number }
    return null
  }
  const moisLisible = (m: string) => new Date(m + '-01T00:00:00Z').toLocaleDateString('fr-FR', { month: 'long', year: 'numeric', timeZone: 'UTC' })
  const impayes = imp
    ? `<h2>Cotisations restant à payer après l’échéance</h2>
<p>${d(notion('taux_impayes').definition)}</p>
<ul class="cles" aria-label="Taux d’impayés des cotisations, dernier mois publié">${(['fin_mois', 'fin_mois_suivant', 'a_90_jours'] as const)
        .map((k) => {
          const x = dernierConnu(imp.national.mois, imp.national[k])
          return x ? `<li><strong>${h(pct(x.v, 2))}</strong><span>${d(imp.taux[k])} (${h(moisLisible(x.mois))})</span></li>` : ''
        })
        .join('')}</ul>
<p class="aide">${d(imp.perimetre)} ${d(imp.avertissement)}</p>
<details><summary>Par région (${h(imp.regions.length)} régions, ordre alphabétique)</summary>
<div class="tableau-defile"><table><caption>Taux d’impayés à 90 jours, dernier mois publié pour chaque région</caption>
<thead><tr><th scope="col">Région</th><th scope="col">Mois</th><th scope="col" class="nombre">Taux à 90 jours</th></tr></thead>
<tbody>${imp.regions
        .map((r) => {
          const x = dernierConnu(r.mois, r.a_90_jours)
          return `<tr><th scope="row">${h(r.region)}</th><td>${x ? h(moisLisible(x.mois)) : 'non publié'}</td><td class="nombre">${x ? h(pct(x.v, 2)) : 'non publié'}</td></tr>`
        })
        .join('')}</tbody></table></div>
</details>
${source(developper(imp.source), imp.millesime)}`
    : ''

  cible.innerHTML = `
<h1>Collecte et contrôle des impôts et des cotisations</h1>
<p class="chapeau">Qui collecte ce que tu verses, ce que la gestion de l’impôt représente quand c’est publié, ce que les contrôles réclament et ce qui est ensuite payé, et les estimations publiées de ce qui n’est pas déclaré, chacune avec son auteur et sa méthode.</p>
<h2>Qui collecte quoi</h2>
<ul>
  <li><strong>Les impôts</strong> (impôt sur le revenu, TVA, impôt sur les sociétés, impôts locaux) : la Direction générale des finances publiques, qui les contrôle aussi.</li>
  <li><strong>Les cotisations et contributions sociales</strong> versées sur les salaires : le réseau des Urssaf (et, outre-mer, les caisses générales de sécurité sociale), qui les contrôle aussi. Le régime agricole a sa propre caisse.</li>
  <li><strong>Une partie des droits indirects</strong>, par exemple sur le tabac : la Direction générale des douanes et droits indirects. Ses contrôles ne sont pas détaillés sur cette page.</li>
</ul>
<p>Combien rapporte chaque impôt et quelle administration en reçoit le produit : <a href="${lien('/explorer/recettes')}">D’où vient l’argent : les recettes</a>.</p>
<h2>Les frais de gestion de l’impôt</h2>
${cout}
<p class="aide">Pour les Urssaf et la douane, aucun indicateur comparable n’est repris dans les données du site.</p>
<h2>Trois notions à ne pas confondre</h2>
<dl class="recouvrement-definitions">${(['notifie', 'encaisse', 'estimation', 'restitution'] as const)
    .map((n) => `<dt>${h(notion(n).libelle)}</dt><dd>${d(notion(n).definition)}</dd>`)
    .join('')}</dl>
<ul>${idx.regles.map((r) => `<li>${d(r)}</li>`).join('')}</ul>
<h2>Après les contrôles : notifié et encaissé</h2>
<p class="aide">Les montants de chaque producteur, dernière année publiée. La sphère fiscale et la sphère sociale ne sont ni additionnées ni rapportées l’une à l’autre.</p>
<h3>Sphère fiscale (impôts)</h3>
<div class="recouvrement-vues">${parSphere('fiscale').map(vue).join('')}</div>
<h3>Sphère sociale (cotisations et prestations)</h3>
<div class="recouvrement-vues">${parSphere('sociale').map(vue).join('')}</div>
${secu}
<h2>Le contrôle fiscal année par année</h2>
${fiscal}
<h2>Les contrôles des Urssaf année par année</h2>
${urssaf}
<h2>Les estimations publiées, côte à côte</h2>
${estimations}
${apurements}
${impayes}
<h2>Limites et sources</h2>
<ul>${idx.limites.map((l) => `<li>${d(l)}</li>`).join('')}</ul>
<p class="aide">${d(idx.confidentialite)}</p>
<details><summary>Sources inaccessibles ou non publiées</summary><ul>${idx.sources_inaccessibles.map((s) => `<li><strong>${d(s.source)}</strong> : ${d(s.motif)}</li>`).join('')}</ul></details>
<details><summary>Documents et jeux de données utilisés (${h(idx.sources.length)})</summary><ul>${idx.sources
    .map((s) => `<li>${lienExterne(s.url, s.titre)} : ${d(s.producteur)}, ${h(s.licence)}</li>`)
    .join('')}</ul></details>
${source(developper(idx.source), idx.millesime)}
<p class="liens-sortie"><a href="${lien('/explorer/niches')}">Dépenses fiscales et exonérations de cotisations</a></p>
${partPersonnelle()}`
}

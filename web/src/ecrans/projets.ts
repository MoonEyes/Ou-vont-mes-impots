// Projets subventionnés par l'État (/local/projets) : pour une commune ou un département, les projets publiés par la
// DGCL (DETR, DSIL, DPV, DSID : « subvention attribuée », site/data/territoires/<dep>.json) et par le ministère de la
// Transition écologique (Fonds vert : « montant engagé », site/data/projets_subventionnes/<dep>.json), et les badges
// Action cœur de ville et Petites villes de demain. Statut affiché tel que publié : jamais « réalisé » ni « livré ».
// Les deux sources ne sont jamais additionnées ; une somme n'est faite que pour une même année et un même dispositif.
//
// Le même module fournit le bloc des pages commune et département (brancherProjets) : il n'est inséré que dans le
// navigateur et son contenu n'est chargé qu'au clic, pour ne rien ajouter au HTML prérendu des pages locales.
import { fragmentCommune, fragmentDepartement } from '../chemins'
import { departementDe, TOUS_DEPARTEMENTS } from '../departements'
import { chargerSiPresent } from '../donnees'
import { lien, type Rendu } from '../routeur'
import { absent, badgeStatut, entier, eur, h, source, badgeCalcule } from '../util'

export const TITRE = 'Projets subventionnés par l’État'
export const SANS_PROJET = 'aucun projet publié pour ces dispositifs'
export const STATUT_DGCL = 'subvention attribuée'
export const STATUT_FV = 'montant engagé'
const FV = 'Fonds vert'

// --- Données ----------------------------------------------------------------------------------------------------------

type ProjetDgcl = [number, string, string | null, number | null, number | null, number | null]
interface BeneficiaireDgcl { id: string; siren: string | null; insee: string | null; type: string; nom: string | null; projets: ProjetDgcl[] }
export interface Territoires {
  millesime: string
  source: string
  investissement_etat: {
    beneficiaires: BeneficiaireDgcl[]
    par_commune: Record<string, [string, string][]>
    totaux: Record<string, Record<string, { projets: number; subvention_eur: number }>>
  }
}
type ProjetFv = [number, string, number | null, string | null, number | null, string, string | null]
interface Badge { id: string | null; programme?: string | null; date_signature: string | null }
export interface ProjetsDep {
  millesime: string
  source: string
  departement: { code: string; nom: string }
  liens: { dgcl: string | null }
  demarches: string[]
  beneficiaires: Record<string, { nom: string; categorie_juridique: string }>
  communes: Record<string, { nom: string; badges?: { acv?: Badge; pvd?: Badge }; fonds_vert?: ProjetFv[] }>
  fonds_vert_totaux: { statut: string; methode: string; par_annee: Record<string, { projets: number; montant_eur: number; lignes_montant_non_communique: number }> }
  exclus_personnes_physiques_ou_non_identifies: { par_annee: Record<string, { projets: number; montant_eur: number }> }
}
export interface Index {
  millesime: string
  source: string
  dispositifs: { id: string; libelle: string; source: 'dgcl' | 'fonds_vert'; programme: string; statut: string }[]
  badges: Record<'acv' | 'pvd', { libelle: string; definition: string }>
  departements: { code: string; nom: string; fichier: string; fichier_dgcl: string | null }[]
  sources: { id: string; titre: string; page: string; millesime?: string }[]
  limites: string[]
  fonds_vert: { methode: string }
}
interface Geo { communes: Record<string, { nom: string; population: number; epci: string | null }> }

/** Une ligne de projet, quelle que soit la source. */
export interface Projet {
  annee: number
  dispositif: string
  intitule: string | null
  beneficiaire: string | null
  montant: number | null
  statut: string
  detail?: string
}

const libelles = new Map<string, string>()
export const libelleDispositif = (id: string) => libelles.get(id) ?? id

/** Projets des dotations (territoires) qui concernent une commune : ceux de la commune et de son intercommunalité. */
export async function projetsDgcl(insee: string, dep: string, terr: Territoires | null): Promise<Projet[]> {
  if (!terr) return []
  const refs = terr.investissement_etat.par_commune[insee] ?? []
  const res: Projet[] = []
  for (const [id, depFichier] of refs) {
    const t = depFichier === dep ? terr : await chargerSiPresent<Territoires>(`territoires/${depFichier}.json`)
    const b = t?.investissement_etat.beneficiaires.find((x) => x.id === id)
    if (!b) continue
    for (const p of b.projets)
      res.push({
        annee: p[0],
        dispositif: p[1],
        intitule: p[2],
        beneficiaire: b.nom,
        montant: p[4],
        statut: STATUT_DGCL,
        detail: p[3] !== null ? `coût du projet hors taxes publié : ${eur(p[3])}` : undefined,
      })
  }
  return res
}

export function projetsFv(insee: string, d: ProjetsDep | null): Projet[] {
  const c = d?.communes[insee]
  if (!d || !c?.fonds_vert) return []
  return c.fonds_vert.map((p) => ({
    annee: p[0],
    dispositif: FV,
    intitule: p[3],
    beneficiaire: d.beneficiaires[p[5]]?.nom ?? null,
    montant: p[4],
    statut: STATUT_FV,
    detail: [p[2] !== null ? d.demarches[p[2]] : null, `programme ${p[1]}`, p[6] ? `engagement juridique n° ${p[6]}` : null].filter(Boolean).join(' ; '),
  }))
}

const triProjets = (a: Projet, b: Projet) => b.annee - a.annee || (b.montant ?? -1) - (a.montant ?? -1) || (a.intitule ?? '').localeCompare(b.intitule ?? '', 'fr')

/** Sommes par année et par dispositif (même année, même dispositif : règle 13), montants non communiqués à part. */
export function sommes(projets: Projet[]): { annee: number; dispositif: string; n: number; montant: number; nc: number; statut: string }[] {
  const m = new Map<string, { annee: number; dispositif: string; n: number; montant: number; nc: number; statut: string }>()
  for (const p of projets) {
    const k = `${p.annee}|${p.dispositif}`
    const e = m.get(k) ?? { annee: p.annee, dispositif: p.dispositif, n: 0, montant: 0, nc: 0, statut: p.statut }
    e.n++
    if (p.montant === null) e.nc++
    else e.montant += p.montant
    m.set(k, e)
  }
  return [...m.values()].sort((a, b) => b.annee - a.annee || a.dispositif.localeCompare(b.dispositif, 'fr'))
}

// --- Rendu -----------------------------------------------------------------------------------------------------------

const montant = (x: number | null) => (x === null ? 'non communiqué' : eur(x))

export function badges(c: ProjetsDep['communes'][string] | undefined, idx: Index | null): string {
  const b = c?.badges
  if (!b) return ''
  const li = (['acv', 'pvd'] as const)
    .filter((k) => b[k])
    .map((k) => {
      const x = b[k]!
      const nom = idx?.badges[k]?.libelle ?? (k === 'acv' ? 'Action cœur de ville' : 'Petites villes de demain')
      return `<li><span class="badge">${h(nom)}</span>${x.date_signature ? ` convention signée le ${h(new Date(x.date_signature + 'T00:00:00Z').toLocaleDateString('fr-FR', { timeZone: 'UTC' }))}` : ''}${idx?.badges[k] ? ` <span class="aide">(${h(idx.badges[k].definition)})</span>` : ''}</li>`
    })
  return li.length ? `<ul aria-label="Programmes nationaux">${li.join('')}</ul>` : ''
}

export function tableauSommes(projets: Projet[], legende: string): string {
  const s = sommes(projets)
  if (!s.length) return ''
  return `<div class="tableau-defile"><table><caption>${h(legende)}</caption><thead><tr><th scope="col">Année</th><th scope="col">Dispositif</th><th scope="col" class="nombre">Projets</th><th scope="col" class="nombre">Somme des montants publiés</th><th scope="col">Statut publié</th></tr></thead><tbody>${s
    .map((x) => `<tr><th scope="row">${x.annee}</th><td>${h(libelleDispositif(x.dispositif))}</td><td class="nombre">${h(entier(x.n))}</td><td class="nombre">${h(eur(x.montant))}${x.nc ? ` <span class="aide">(${x.nc} montant${x.nc > 1 ? 's' : ''} non communiqué${x.nc > 1 ? 's' : ''}, hors somme)</span>` : ''}</td><td>${h(x.statut)}</td></tr>`)
    .join('')}</tbody></table></div>
<p class="aide">Somme ${badgeCalcule('montants publiés d’une même année et d’un même dispositif, additionnés ligne par ligne')}. Les dotations (subventions attribuées) et le Fonds vert (montants engagés) ne sont jamais additionnés entre eux.</p>`
}

export function tableauProjets(projets: Projet[], legende: string): string {
  if (!projets.length) return ''
  return `<div class="tableau-defile"><table><caption>${h(legende)}</caption><thead><tr><th scope="col">Année</th><th scope="col">Dispositif</th><th scope="col">Projet</th><th scope="col">Bénéficiaire</th><th scope="col" class="nombre">Montant</th><th scope="col">Statut publié</th></tr></thead><tbody>${[...projets]
    .sort(triProjets)
    .map(
      (p) =>
        `<tr><th scope="row">${p.annee}</th><td>${h(libelleDispositif(p.dispositif))}</td><td>${p.intitule ? h(p.intitule) : '<span class="aide">intitulé non publié (il peut contenir un nom de personne)</span>'}${p.detail ? `<br><span class="aide">${h(p.detail)}</span>` : ''}</td><td>${p.beneficiaire ? h(p.beneficiaire) : '<span class="aide">non publié</span>'}</td><td class="nombre">${h(montant(p.montant))}</td><td>${h(p.statut)}</td></tr>`,
    )
    .join('')}</tbody></table></div>`
}

const PHRASE_STATUT = `Statut tel que publié : « ${STATUT_DGCL} » pour les dotations, « ${STATUT_FV} » pour le Fonds vert. Les listes ne disent pas si le projet est terminé, ni ce qui a été payé.`

async function chargerIndex(): Promise<Index | null> {
  const idx = await chargerSiPresent<Index>('projets_subventionnes/index.json')
  for (const d of idx?.dispositifs ?? []) libelles.set(d.id, d.libelle)
  return idx
}

/** Contenu du bloc d'une commune (page commune et écran). */
export async function contenuCommune(insee: string, nom: string, limite?: number): Promise<string> {
  const dep = departementDe(insee)
  const [idx, d, terr] = await Promise.all([chargerIndex(), chargerSiPresent<ProjetsDep>(`projets_subventionnes/${dep}.json`), chargerSiPresent<Territoires>(`territoires/${dep}.json`)])
  if (!d && !terr) return absent('Projets subventionnés non disponibles.')
  const tous = [...(await projetsDgcl(insee, dep, terr)), ...projetsFv(insee, d)].sort(triProjets)
  const b = badges(d?.communes[insee], idx)
  const sources = `${terr ? source(`Dotations : ${terr.source}`, terr.millesime) : ''}${d ? source(d.source, d.millesime) : ''}`
  if (!tous.length) return `${b}<p>${h(nom)} : ${SANS_PROJET} (dotations d’investissement de l’État, Fonds vert).</p>${sources}`
  const montres = limite ? tous.slice(0, limite) : tous
  return `${b}<p>${h(entier(tous.length))} projet${tous.length > 1 ? 's' : ''} publié${tous.length > 1 ? 's' : ''} pour ${h(nom)} ou son intercommunalité. ${badgeStatut('trace')}</p>
<p class="aide">${h(PHRASE_STATUT)}</p>
${tableauSommes(tous, `Projets subventionnés par l’État concernant ${nom}, par année et par dispositif`)}
${tableauProjets(montres, limite && tous.length > limite ? `Les ${limite} projets les plus récents (sur ${tous.length})` : `Projets concernant ${nom}`)}
${sources}`
}

/** Contenu du bloc d'un département : sommes par année et dispositif, publiées par chaque source, badges. */
export async function contenuDepartement(dep: string): Promise<string> {
  const [, d, terr] = await Promise.all([chargerIndex(), chargerSiPresent<ProjetsDep>(`projets_subventionnes/${dep}.json`), chargerSiPresent<Territoires>(`territoires/${dep}.json`)])
  if (!d && !terr) return absent('Projets subventionnés non disponibles.')
  const lignes: { annee: string; dispositif: string; n: number; montant: number; statut: string }[] = []
  for (const [a, parDisp] of Object.entries(terr?.investissement_etat.totaux ?? {}))
    for (const [k, v] of Object.entries(parDisp)) if (k !== 'non_nommes') lignes.push({ annee: a, dispositif: k, n: v.projets, montant: v.subvention_eur, statut: STATUT_DGCL })
  for (const [a, v] of Object.entries(d?.fonds_vert_totaux.par_annee ?? {})) lignes.push({ annee: a, dispositif: FV, n: v.projets, montant: v.montant_eur, statut: STATUT_FV })
  lignes.sort((x, y) => y.annee.localeCompare(x.annee) || x.dispositif.localeCompare(y.dispositif, 'fr'))
  const coms = Object.values(d?.communes ?? {})
  const acv = coms.filter((c) => c.badges?.acv).length
  const pvd = coms.filter((c) => c.badges?.pvd).length
  return `${lignes.length ? `<div class="tableau-defile"><table><caption>Projets publiés dans le département, par année et par dispositif</caption><thead><tr><th scope="col">Année</th><th scope="col">Dispositif</th><th scope="col" class="nombre">Projets</th><th scope="col" class="nombre">Somme des montants publiés</th><th scope="col">Statut publié</th></tr></thead><tbody>${lignes
    .map((x) => `<tr><th scope="row">${h(x.annee)}</th><td>${h(libelleDispositif(x.dispositif))}</td><td class="nombre">${h(entier(x.n))}</td><td class="nombre">${h(eur(x.montant))}</td><td>${h(x.statut)}</td></tr>`)
    .join('')}</tbody></table></div>
<p class="aide">Somme ${badgeCalcule('projets dont le bénéficiaire est nommé, d’une même année et d’un même dispositif')}. Les dotations et le Fonds vert ne sont jamais additionnés entre eux. ${h(PHRASE_STATUT)}</p>` : `<p>${h(SANS_PROJET)}.</p>`}
<p>${h(entier(acv))} commune${acv > 1 ? 's' : ''} du programme Action cœur de ville, ${h(entier(pvd))} du programme Petites villes de demain (listes sans montant).</p>
${terr ? source(`Dotations : ${terr.source}`, terr.millesime) : ''}${d ? source(d.source, d.millesime) : ''}`
}

/** Le bloc des pages commune et département ne s'insère que dans le navigateur (jamais au prérendu, qui tourne
 *  dans happy-dom) : le HTML statique des pages locales reste inchangé. Remplaçable dans les tests. */
export const hors = { prerendu: () => typeof navigator !== 'undefined' && /HappyDOM/.test(navigator.userAgent ?? '') }

/** Insère le bloc « Projets subventionnés par l'État » avant « Pour aller plus loin » ; contenu chargé au clic. */
export function brancherProjets(zone: HTMLElement, cible: { insee: string; nom: string } | { dep: string; nom: string }) {
  if (hors.prerendu()) return
  const ancre = [...zone.querySelectorAll('h2')].find((t) => t.textContent?.trim() === 'Pour aller plus loin')
  const id = 'insee' in cible ? cible.insee : cible.dep
  const page = 'insee' in cible ? lien('/local/projets', { insee: cible.insee }) : lien('/local/projets', { dep: cible.dep })
  const html = `<section class="projets-bloc" aria-labelledby="projets-titre-${h(id)}"><h2 id="projets-titre-${h(id)}">${TITRE}</h2>
<p>Les projets que l’État a subventionnés ${'insee' in cible ? `à ${h(cible.nom)} ou à son intercommunalité` : `dans le département ${h(cible.nom)}`} : dotations d’investissement (subventions attribuées) et Fonds vert (montants engagés), d’après les listes publiées.</p>
<p class="actions"><button type="button" class="bouton" aria-expanded="false" aria-controls="projets-contenu-${h(id)}">Afficher les projets</button> <a href="${page}">Tous les projets, avec filtres</a></p>
<div id="projets-contenu-${h(id)}" class="section-donnees" hidden></div></section>`
  if (ancre) ancre.insertAdjacentHTML('beforebegin', html)
  else zone.insertAdjacentHTML('beforeend', html)
  const bouton = zone.querySelector<HTMLButtonElement>(`#projets-titre-${id} ~ .actions button`)
  const contenu = zone.querySelector<HTMLElement>(`#projets-contenu-${id}`)
  if (!bouton || !contenu) return
  let charge = false
  bouton.addEventListener('click', async () => {
    const ouvert = bouton.getAttribute('aria-expanded') === 'true'
    bouton.setAttribute('aria-expanded', String(!ouvert))
    bouton.textContent = ouvert ? 'Afficher les projets' : 'Masquer les projets'
    contenu.hidden = ouvert
    if (ouvert || charge) return
    charge = true
    contenu.setAttribute('aria-busy', 'true')
    contenu.innerHTML = '<p class="chargement">Chargement…</p>'
    try {
      contenu.innerHTML = 'insee' in cible ? await contenuCommune(cible.insee, cible.nom, 10) : await contenuDepartement(cible.dep)
    } catch {
      contenu.innerHTML = absent()
      charge = false
    }
    contenu.removeAttribute('aria-busy')
  })
}

// --- Écran /local/projets ---------------------------------------------------------------------------------------------

export async function rendre(cible: HTMLElement, params: URLSearchParams): Promise<Rendu | void> {
  const inseeP = (params.get('insee') ?? '').toUpperCase()
  const insee = /^(\d{5}|2[AB]\d{3})$/.test(inseeP) ? inseeP : ''
  const depP = (params.get('dep') ?? '').toUpperCase()
  const dep = insee ? departementDe(insee) : /^(\d{2,3}|2[AB])$/.test(depP) ? depP : ''
  const q = (params.get('q') ?? '').trim()
  const filtreDisp = params.get('d') ?? ''
  const filtreAn = /^\d{4}$/.test(params.get('a') ?? '') ? Number(params.get('a')) : null
  const idx = await chargerIndex()
  const nomDep = idx?.departements.find((x) => x.code === dep)?.nom ?? TOUS_DEPARTEMENTS.find(([c]) => c === dep)?.[1] ?? dep

  const intro = `<h1>${TITRE}</h1>
<p class="chapeau">Les projets d’une commune ou d’un département que l’État a subventionnés : dotations d’investissement des collectivités (DETR, DSIL, DPV, DSID) et Fonds vert, avec leur bénéficiaire, leur montant et leur année.</p>
<p class="aide">${h(PHRASE_STATUT)} La page ne montre ni les autres aides de l’État, ni les fonds européens, ni les financements des collectivités.</p>`
  const formulaire = `<form id="projets-lieu" class="choix" role="search"><h2>Choisir un lieu</h2>
<label for="projets-dep">Département</label><select id="projets-dep" name="dep"><option value="">Choisir</option>${(idx?.departements.map((x) => [x.code, x.nom] as [string, string]) ?? TOUS_DEPARTEMENTS)
    .map(([c, n]) => `<option value="${h(c)}"${c === dep ? ' selected' : ''}>${h(c)} ${h(n)}</option>`)
    .join('')}</select>
<label for="projets-q">Commune (nom ou code Insee)</label><input type="search" id="projets-q" name="q" autocomplete="off" value="${h(insee || q)}">
<p><button class="bouton" type="submit">Afficher</button></p></form>`
  const sorties = `<h2>Pour aller plus loin</h2><ul class="liens-sortie">
${insee ? `<li><a href="${lien('/local/commune', { insee })}">Le budget de la commune</a></li>` : ''}
${dep ? `<li><a href="${fragmentDepartement(dep, nomDep)}">Les communes du département ${h(nomDep)}</a></li>` : ''}
<li><a href="#/explorer/collectivites">Les collectivités locales en France</a></li>
<li><a href="#/beneficiaires">Qui reçoit l’argent public</a></li></ul>`
  const brancherFormulaire = () =>
    cible.querySelector<HTMLFormElement>('#projets-lieu')?.addEventListener('submit', (e) => {
      e.preventDefault()
      const f = e.target as HTMLFormElement
      const d = f.querySelector<HTMLSelectElement>('#projets-dep')?.value ?? ''
      const t = (f.querySelector<HTMLInputElement>('#projets-q')?.value ?? '').trim()
      const code = t.toUpperCase()
      location.hash = /^(\d{5}|2[AB]\d{3})$/.test(code) ? lien('/local/projets', { insee: code }) : lien('/local/projets', { dep: d, q: t })
    })

  if (!dep) {
    cible.innerHTML = `${intro}${formulaire}${idx ? `<h2>Ce que la page ne montre pas</h2><ul>${idx.limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul>${source(idx.source, idx.millesime)}` : ''}${sorties}`
    brancherFormulaire()
    return
  }

  const [geo, d, terr] = await Promise.all([
    chargerSiPresent<Geo>(`local/geo/${dep}.json`),
    chargerSiPresent<ProjetsDep>(`projets_subventionnes/${dep}.json`),
    chargerSiPresent<Territoires>(`territoires/${dep}.json`),
  ])
  if (!geo) {
    cible.innerHTML = `${intro}${formulaire}${absent('Département introuvable dans les données publiées.')}${sorties}`
    brancherFormulaire()
    return
  }

  if (!insee) {
    // Département : sommes par année et dispositif, puis les communes (filtrées par le nom saisi).
    const norm = (s: string) => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
    const avec = new Set([...Object.keys(d?.communes ?? {}), ...Object.keys(terr?.investissement_etat.par_commune ?? {})])
    const liste = Object.entries(geo.communes)
      .filter(([, c]) => !q || norm(c.nom).includes(norm(q)))
      .sort((a, b) => a[1].nom.localeCompare(b[1].nom, 'fr'))
    cible.innerHTML = `${intro}${formulaire}
<h2>Département ${h(nomDep)} (${h(dep)})</h2>
${await contenuDepartement(dep)}
<h2>${q ? `Communes dont le nom contient « ${h(q)} »` : 'Les communes'}</h2>
<p class="aide">Ordre alphabétique. Une commune sans projet publié pour ces dispositifs est signalée comme telle.</p>
${liste.length ? `<ul class="liste-colonnes">${liste.map(([i, c]) => `<li><a href="${lien('/local/projets', { insee: i })}">${h(c.nom)}</a>${avec.has(i) ? '' : ` <span class="aide">(${SANS_PROJET})</span>`}</li>`).join('')}</ul>` : absent('Aucune commune ne correspond.')}
${sorties}`
    brancherFormulaire()
    return { titre: `${TITRE} : ${nomDep}`, description: `Projets subventionnés par l’État dans le département ${nomDep} : dotations d’investissement et Fonds vert, par année et par dispositif.` }
  }

  // Commune : projets filtrés par dispositif et par année.
  const c = geo.communes[insee]
  if (!c) {
    cible.innerHTML = `${intro}${formulaire}${absent('Commune introuvable dans les données publiées.')}${sorties}`
    brancherFormulaire()
    return
  }
  const tous = [...(await projetsDgcl(insee, dep, terr)), ...projetsFv(insee, d)]
  const disps = [...new Set(tous.map((p) => p.dispositif))].sort((a, b) => a.localeCompare(b, 'fr'))
  const annees = [...new Set(tous.map((p) => p.annee))].sort((a, b) => b - a)
  const filtres = tous.filter((p) => (!filtreDisp || p.dispositif === filtreDisp) && (filtreAn === null || p.annee === filtreAn))
  const filtresForm = tous.length
    ? `<form id="projets-filtres" class="choix"><h2>Filtrer</h2><input type="hidden" name="insee" value="${h(insee)}">
<label for="projets-disp">Dispositif</label><select id="projets-disp" name="d"><option value="">Tous les dispositifs</option>${disps.map((x) => `<option value="${h(x)}"${x === filtreDisp ? ' selected' : ''}>${h(libelleDispositif(x))}</option>`).join('')}</select>
<label for="projets-an">Année</label><select id="projets-an" name="a"><option value="">Toutes les années</option>${annees.map((a) => `<option value="${a}"${a === filtreAn ? ' selected' : ''}>${a}</option>`).join('')}</select>
<p><button class="bouton" type="submit">Filtrer</button></p></form>`
    : ''
  const filtreTexte = [filtreDisp ? libelleDispositif(filtreDisp) : '', filtreAn !== null ? String(filtreAn) : ''].filter(Boolean).join(', ')
  cible.innerHTML = `${intro}${formulaire}
<h2>${h(c.nom)} (${h(insee)})</h2>
${badges(d?.communes[insee], idx)}
${
  tous.length
    ? `<p>${h(entier(tous.length))} projet${tous.length > 1 ? 's' : ''} publié${tous.length > 1 ? 's' : ''} pour la commune ou son intercommunalité. ${badgeStatut('trace')}</p>
${filtresForm}
${filtres.length ? `${tableauSommes(filtres, `Par année et par dispositif${filtreTexte ? ` (${filtreTexte})` : ''}`)}${tableauProjets(filtres, `Projets concernant ${c.nom}${filtreTexte ? ` (${filtreTexte})` : ''}`)}` : `<p>${h(SANS_PROJET)} avec ces filtres.</p>`}`
    : `<p>${h(c.nom)} : ${h(SANS_PROJET)} (dotations d’investissement de l’État, Fonds vert).</p>`
}
${terr ? source(`Dotations : ${terr.source}`, terr.millesime) : ''}${d ? source(d.source, d.millesime) : ''}
<p class="actions"><a href="${fragmentCommune(insee, c.nom, c.population)}">Le budget de ${h(c.nom)}</a> <a href="${lien('/local/projets', { dep })}">Les projets du département ${h(nomDep)}</a></p>
${sorties}`
  brancherFormulaire()
  cible.querySelector<HTMLFormElement>('#projets-filtres')?.addEventListener('submit', (e) => {
    e.preventDefault()
    const f = e.target as HTMLFormElement
    location.hash = lien('/local/projets', {
      insee,
      d: f.querySelector<HTMLSelectElement>('#projets-disp')?.value,
      a: f.querySelector<HTMLSelectElement>('#projets-an')?.value,
    })
  })
  return { titre: `${TITRE} : ${c.nom}`, description: `Projets subventionnés par l’État pour ${c.nom} (${nomDep}) : dotations d’investissement et Fonds vert, avec leur année, leur bénéficiaire et leur montant publié.` }
}

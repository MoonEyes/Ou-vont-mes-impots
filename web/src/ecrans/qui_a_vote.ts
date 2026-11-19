// Qui a voté tes impôts (site/data/qui_a_vote/, contrat 2.70) : pour chaque impôt que le simulateur montre, les
// articles des lois de finances et de financement de la sécurité sociale qui l'ont fixé ou modifié pendant la
// 17e législature, les scrutins publics (décompte publié par groupe, vote de chaque député chargé à la demande) et
// les amendements adoptés avec leur auteur. Entrée « Ton député » : département puis circonscription, dans le
// navigateur, rien n'est envoyé ni conservé (aucune adresse, aucun stockage). Neutralité : aucun classement, score
// ni qualificatif ; groupes dans l'ordre alphabétique écrit à l'écran ; positions écrites en toutes lettres, sans
// couleur ; décomptes tels que publiés (aucun pourcentage calculé).
import { charger, chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { absent, entier, h, rendreDefilables, source } from '../util'
import { enCours } from './dette'

const CHEMIN = '/decisions/qui-a-vote'

interface Rattachement {
  methode: 'intitule' | 'code_cite' | 'intitule_et_code_cite' | 'article_vise'
  preuves: string[]
  article_entier?: boolean
}
interface ImpotCourt {
  id: string
  libelle: string
  articles: number
  scrutins: number
  amendements_adoptes: number
  amendements_adoptes_assemblee?: number
  amendements_adoptes_senat?: number
  fichier: string
  fichier_votes: string
}
interface Departement {
  code: string
  nom: string
  circonscriptions: number[]
  fichier: string
}
export interface Index {
  millesime: string
  source: string
  donnees_au: string | null
  presentation: string
  methode: string
  avertissements: string[]
  regle_ordre: string
  regle_ordre_groupes: string
  regle_personnes: string
  confidentialite: string
  impots: ImpotCourt[]
  non_couverts: { id: string; libelle: string; motif: string }[]
  departements: Departement[]
  limites: string[]
}
interface Groupe {
  groupe: string
  membres: number
  pour: number
  contre: number
  abstentions: number
  non_votants: number
}
export interface Scrutin {
  numero: number
  date: string
  texte: string
  lecture: string | null
  objet: string
  type: 'article' | 'amendement'
  article: string | null
  amendement: string | null
  rattachement: Rattachement
  resultat: string
  votants: number
  pour: number
  contre: number
  abstentions: number
  non_votants: number
  groupes: Groupe[]
  url: string
}
interface Article {
  texte: string
  texte_libelle: string
  lecture: string
  document: string
  url_document: string
  article: string
  intitule: string | null
  intitule_source: string | null
  extrait: string
  rattachement: Rattachement
  scrutins: number[]
}
interface Amendement {
  chambre: string
  texte: string
  lecture: string | null
  numero: string
  article_vise: string | null
  date: string | null
  sort: string
  auteur: { type: string; nom: string | null; groupe: string | null }
  cosignataires: number
  dispositif: string
  rattachement: Rattachement
  scrutin: number | null
  url: string
}
export interface Impot {
  millesime: string
  source: string
  donnees_au: string | null
  impot: { id: string; libelle: string; lignes_simulateur: string[]; bases_texte: string[] }
  methode: string
  avertissements: string[]
  regle_ordre: string
  regle_ordre_groupes: string
  regle_personnes: string
  articles: Article[]
  scrutins: Scrutin[]
  amendements_adoptes: Amendement[]
  fichier_votes: string
}
interface VoteGroupe {
  groupe: string
  pour: string[]
  contre: string[]
  abstention: string[]
  non_votant: string[]
  par_delegation: string[]
}
interface Votes {
  deputes: Record<string, string | null>
  votes: Record<string, { groupes: VoteGroupe[]; mises_au_point: { depute: string; position_souhaitee: string }[] }>
}
type VoteDepute = [number, string | null, 0 | 1, string | null, string | null]
interface DepFichier {
  departement: { code: string; nom: string }
  circonscriptions: { numero: number; deputes: { depute: string; nom: string | null; debut: string | null; fin: string | null; votes: VoteDepute[] }[] }[]
}
interface ScrutinsListe {
  scrutins: { numero: number; date: string; texte: string; lecture: string | null; objet: string; impots: string[]; resultat: string; url: string }[]
}

/** Identifiant de l’Assemblée sans nom dans son fichier des acteurs (aucun nom n’est retiré par le site). */
export const NOM_ABSENT = 'nom absent du fichier des députés de l’Assemblée'

export const POSITIONS: Record<string, string> = {
  pour: 'pour',
  contre: 'contre',
  abstention: 'abstention',
  non_votant: 'non-votant',
}
export const SANS_POSITION = 'aucune position enregistrée'
const METHODES: Record<Rattachement['methode'], string> = {
  intitule: 'l’intitulé officiel de l’article nomme l’impôt',
  code_cite: 'le texte cite un article de code qui fixe un paramètre de l’impôt',
  intitule_et_code_cite: 'l’intitulé officiel nomme l’impôt et le texte cite un article de code qui fixe un de ses paramètres',
  article_vise: 'l’amendement porte sur un article dont toutes les dispositions relèvent de l’impôt',
}

const lienSiUrl = (url: string | null | undefined, texte: string) =>
  url && /^https:\/\//.test(url) ? `<a href="${h(url)}" rel="noopener noreferrer">${h(texte)}</a>` : h(texte)
const dateFr = (d: string | null) => (d ? new Date(`${d}T12:00:00Z`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }) : 'date non publiée')
const LIBELLES_TEXTE: Record<string, string> = {
  PLF: 'projet de loi de finances',
  PLFSS: 'projet de loi de financement de la sécurité sociale',
  PLFG: 'projet de loi de finances de fin de gestion',
  PLFR: 'projet de loi de finances rectificative',
  PLFRSS: 'projet de loi de financement rectificative de la sécurité sociale',
}
/** « PLF 2026 » -> « projet de loi de finances pour 2026 » (jamais de sigle seul à l’écran). */
export const texteEnClair = (cle: string) => {
  const [t, a] = cle.split(' ')
  return `${LIBELLES_TEXTE[t] ?? t} pour ${a}`
}
const preuve = (r: Rattachement) => `<p class="aide">Lien avec l’impôt : ${h(METHODES[r.methode])} (${h(r.preuves.join(' ; '))}).</p>`

export function avertissements(liste: string[]): string {
  return `<div class="avertissement" role="note" data-avertissements><p><strong>À lire avant les votes</strong></p><ul>${liste.map((a) => `<li>${h(a)}</li>`).join('')}</ul></div>`
}

/** Tableau des groupes d’un scrutin : décompte publié par l’Assemblée, groupes dans l’ordre alphabétique. */
export function tableauGroupes(s: Scrutin, regle: string): string {
  return `<p class="aide" data-regle-ordre>${h(regle)}</p>
<div class="tableau-defile"><table><caption>Scrutin n° ${h(String(s.numero))} : vote par groupe (décompte publié)</caption>
<thead><tr><th scope="col">Groupe</th><th scope="col" class="nombre">Pour</th><th scope="col" class="nombre">Contre</th><th scope="col" class="nombre">Abstention</th><th scope="col" class="nombre">Non-votants</th></tr></thead>
<tbody>${s.groupes
    .map((g) => `<tr><th scope="row">${h(g.groupe)}</th><td class="nombre">${entier(g.pour)}</td><td class="nombre">${entier(g.contre)}</td><td class="nombre">${entier(g.abstentions)}</td><td class="nombre">${entier(g.non_votants)}</td></tr>`)
    .join('')}</tbody></table></div>`
}

function scrutinHtml(s: Scrutin, d: Impot): string {
  return `<details class="qav-scrutin" data-scrutin="${s.numero}"><summary>${h(dateFr(s.date))} · scrutin n° ${h(String(s.numero))} : ${h(s.resultat)}</summary>
<p>${lienSiUrl(s.url, `Sur ${s.objet}`)}</p>
<p>Décompte publié : ${entier(s.votants)} votants, ${entier(s.pour)} pour, ${entier(s.contre)} contre, ${entier(s.abstentions)} abstentions, ${entier(s.non_votants)} non-votants.</p>
${preuve(s.rattachement)}
${tableauGroupes(s, d.regle_ordre_groupes)}
<button type="button" class="bouton" data-nominatif="${s.numero}">Voir le vote de chaque député</button>
<div class="qav-nominatif" aria-live="polite"></div>
</details>`
}

function articleHtml(a: Article): string {
  const intit = a.intitule ? `<p><em>${h(a.intitule)}</em>${a.intitule_source === 'projet déposé' ? ' (intitulé dans le projet déposé)' : ''}</p>` : '<p class="aide">Pas d’intitulé dans ce texte.</p>'
  return `<li><p><strong>Article ${h(a.article)}</strong>, ${h(texteEnClair(a.texte))}, ${h(a.lecture)} · ${lienSiUrl(a.url_document, 'texte examiné')}</p>
${intit}
${preuve(a.rattachement)}
<details><summary>Début du texte de l’article</summary><p>${h(a.extrait)}</p></details>
${a.scrutins.length ? `<p class="aide">Scrutin public sur l’article : n° ${a.scrutins.map((n) => h(String(n))).join(', ')}.</p>` : '<p class="aide">Pas de scrutin public sur l’article lui-même (vote à main levée ou article non mis aux voix séparément).</p>'}</li>`
}

function amendementHtml(a: Amendement): string {
  const au = a.auteur
  const qui = au.nom ? `${au.nom}${au.groupe ? ` (${au.groupe})` : ''}` : au.type
  return `<li><p><strong>${h(qui)}</strong> · ${h(a.chambre)}, ${h(texteEnClair(a.texte))}${a.lecture ? `, ${h(a.lecture)}` : ''}, amendement ${lienSiUrl(a.url, `n° ${a.numero}`)}${a.article_vise ? ` à l’article ${h(a.article_vise)}` : ''}, adopté${a.date ? ` le ${h(dateFr(a.date))}` : ''}${a.cosignataires ? ` (${entier(a.cosignataires)} cosignataires)` : ''}${a.scrutin ? `, scrutin public n° ${h(String(a.scrutin))}` : ''}</p>
<details><summary>Texte de l’amendement (début)</summary><p>${h(a.dispositif)}</p></details>
${preuve(a.rattachement)}</li>`
}

function parTexte<T extends { texte: string }>(liste: T[]): [string, T[]][] {
  const m = new Map<string, T[]>()
  for (const x of liste) m.set(x.texte, [...(m.get(x.texte) ?? []), x])
  return [...m.entries()]
}

export function rendreImpot(d: Impot): string {
  const arts = parTexte(d.articles)
  return `<h2 id="qav-titre-impot">${h(d.impot.libelle)}</h2>
<p>Dans ton calcul : ${h(d.impot.lignes_simulateur.join(' ; '))}.</p>
<details><summary>Articles de code qui fixent les règles de cet impôt appliquées par le simulateur</summary><ul>${d.impot.bases_texte.map((b) => `<li>${h(b)}</li>`).join('')}</ul></details>
<p class="aide" data-regle-ordre>${h(d.regle_ordre)}</p>
<h3>Articles des projets de loi qui l’ont fixé ou modifié</h3>
${
  arts.length
    ? arts.map(([t, l]) => `<h4>${h(texteEnClair(t))}</h4><ul class="qav-liste">${l.map(articleHtml).join('')}</ul>`).join('')
    : absent('Aucun article relié à cet impôt dans les textes examinés pendant la législature (selon la méthode ci-dessus).')
}
<h3>Scrutins publics (${entier(d.scrutins.length)})</h3>
${d.scrutins.length ? d.scrutins.map((s) => scrutinHtml(s, d)).join('') : absent('Aucun scrutin public relié à cet impôt.')}
<h3>Amendements adoptés (${entier(d.amendements_adoptes.length)})</h3>
<p class="aide" data-regle-ordre>Amendements par date d’adoption, du plus récent au plus ancien, quel que soit le groupe de l’auteur.</p>
${d.amendements_adoptes.length ? `<ul class="qav-liste">${d.amendements_adoptes.map(amendementHtml).join('')}</ul>` : absent('Aucun amendement adopté relié à cet impôt.')}
${source(d.source, d.millesime)}`
}

/** Listes nominatives d’un scrutin : par groupe (ordre alphabétique), puis par position, noms dans l’ordre alphabétique. */
export function rendreNominatif(v: Votes, numero: number): string {
  const s = v.votes[String(numero)]
  if (!s) return absent('Vote nominatif non publié pour ce scrutin.')
  const nom = (pa: string) => v.deputes[pa] ?? NOM_ABSENT
  const deleg = (g: VoteGroupe) => new Set(g.par_delegation)
  const liste = (g: VoteGroupe, cle: 'pour' | 'contre' | 'abstention' | 'non_votant') =>
    g[cle].length ? `<li><strong>${h(POSITIONS[cle])}</strong> (${entier(g[cle].length)}) : ${g[cle].map((pa) => h(nom(pa)) + (deleg(g).has(pa) ? ' (par délégation)' : '')).join(', ')}</li>` : ''
  const mises = s.mises_au_point.length
    ? `<p><strong>Mises au point publiées</strong> : ${s.mises_au_point.map((m) => `${h(nom(m.depute))} indique avoir voulu voter ${h(POSITIONS[m.position_souhaitee] ?? m.position_souhaitee)}`).join(' ; ')}.</p>`
    : '<p class="aide">Aucune mise au point publiée pour ce scrutin.</p>'
  return `${s.groupes.map((g) => `<h5>${h(g.groupe)}</h5><ul>${(['pour', 'contre', 'abstention', 'non_votant'] as const).map((c) => liste(g, c)).join('')}</ul>`).join('')}${mises}
<p class="aide">Un député absent de ces listes n’a pas de position enregistrée pour ce scrutin.</p>`
}

/** Votes d’un député sur les scrutins retenus pendant son mandat, ordre chronologique. */
export function rendreDepute(x: DepFichier['circonscriptions'][number]['deputes'][number], scrutins: ScrutinsListe['scrutins'], impots: Map<string, string>): string {
  const par = new Map(x.votes.map((v) => [v[0], v]))
  const pendant = scrutins.filter((s) => (!x.debut || s.date >= x.debut) && (!x.fin || s.date <= x.fin))
  const qui = x.nom ?? NOM_ABSENT
  const lignes = pendant
    .map((s) => {
      const v = par.get(s.numero)
      const pos = v && v[1] ? POSITIONS[v[1]] : SANS_POSITION
      const notes = [v && v[2] ? 'par délégation' : '', v && v[4] ? `mise au point : souhaitait voter ${POSITIONS[v[4]] ?? v[4]}` : ''].filter(Boolean).join(' ; ')
      return `<tr><th scope="row">${h(dateFr(s.date))}</th><td>${lienSiUrl(s.url, `n° ${s.numero} : ${s.objet}`)}</td><td>${h(s.impots.map((i) => impots.get(i) ?? i).join(', '))}</td><td>${h(pos)}${notes ? ` (${h(notes)})` : ''}</td><td>${h(v?.[3] ?? '')}</td></tr>`
    })
    .join('')
  return `<h4>${h(qui)}</h4>
<p>Député de la circonscription du ${h(dateFr(x.debut))}${x.fin ? ` au ${h(dateFr(x.fin))}` : ' à aujourd’hui'}.</p>
${
  pendant.length
    ? `<div class="tableau-defile"><table><caption>Votes de ${h(qui)} aux scrutins publics sur ces impôts</caption><thead><tr><th scope="col">Date</th><th scope="col">Scrutin</th><th scope="col">Impôt concerné</th><th scope="col">Position publiée</th><th scope="col">Groupe au moment du vote</th></tr></thead><tbody>${lignes}</tbody></table></div>`
    : absent('Aucun scrutin public relié à ces impôts pendant ce mandat.')
}`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams = new URLSearchParams()) {
  const idx = await chargerSiPresent<Index>('qui_a_vote/index.json')
  if (!idx) {
    cible.innerHTML = enCours('Qui a voté tes impôts', 'Articles, scrutins publics et amendements adoptés pour chaque impôt du simulateur.')
    return
  }
  const choisi = idx.impots.find((i) => i.id === params.get('impot'))
  const nomsImpots = new Map(idx.impots.map((i) => [i.id, i.libelle]))
  cible.innerHTML = `<h1>Qui a voté tes impôts</h1>
<p class="chapeau">${h(idx.presentation)} Elle montre les décisions publiées par l’Assemblée nationale et le Sénat depuis juillet 2024 ; elle ne montre ni les votes à main levée ni les scrutins nominatifs du Sénat, qui ne sont pas publiés en données ouvertes.</p>
${avertissements(idx.avertissements)}
<details class="carte"><summary>Comment un vote est relié à un impôt</summary><p>${h(idx.methode)}</p><p>${h(idx.regle_personnes)}</p><ul>${idx.limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul></details>
<h2>Choisis un impôt</h2>
<form class="carte" id="qav-form-impot"><label for="qav-impot">Impôt</label><select id="qav-impot"><option value="">Choisir…</option>${idx.impots
    .map((i) => `<option value="${h(i.id)}"${choisi?.id === i.id ? ' selected' : ''}>${h(i.libelle)}</option>`)
    .join('')}</select></form>
<div class="tableau-defile"><table><caption>Décisions reliées à chaque impôt du simulateur (17e législature)</caption><thead><tr><th scope="col">Impôt</th><th scope="col" class="nombre">Articles</th><th scope="col" class="nombre">Scrutins publics</th><th scope="col" class="nombre">Amendements adoptés</th></tr></thead><tbody>${idx.impots
    .map((i) => `<tr><th scope="row"><a href="${lien(CHEMIN, { impot: i.id })}">${h(i.libelle)}</a></th><td class="nombre">${entier(i.articles)}</td><td class="nombre">${entier(i.scrutins)}</td><td class="nombre">${entier(i.amendements_adoptes)}</td></tr>`)
    .join('')}</tbody></table></div>
<p class="aide" data-regle-ordre>Impôts dans l’ordre du calcul du simulateur.</p>
${idx.non_couverts.map((n) => `<p class="aide">${h(n.libelle)} : non couvert, ${h(n.motif)}.</p>`).join('')}
<div id="qav-impot-detail" aria-live="polite"></div>
<h2 id="qav-ton-depute">Ton député</h2>
<p>${h(idx.confidentialite)}</p>
<form class="carte" id="qav-form-depute">
  <label for="qav-dep">Département</label>
  <select id="qav-dep"><option value="">Choisir…</option>${idx.departements.map((d) => `<option value="${h(d.code)}">${h(d.code)} ${h(d.nom)}</option>`).join('')}</select>
  <label for="qav-circo">Circonscription</label>
  <select id="qav-circo" disabled><option value="">Choisis d’abord un département</option></select>
</form>
<div id="qav-depute" aria-live="polite"></div>
${source(idx.source, `${idx.millesime}${idx.donnees_au ? `, scrutins jusqu’au ${dateFr(idx.donnees_au)}` : ''}`)}
<ul class="liens-sortie"><li><a href="${lien('/decisions/votes')}">Votes sur les crédits du budget de l’État</a></li><li><a href="${lien('/calcul')}">Calculer ce que tu verses</a></li></ul>`

  cible.querySelector<HTMLSelectElement>('#qav-impot')?.addEventListener('change', (e) => {
    location.hash = lien(CHEMIN, { impot: (e.target as HTMLSelectElement).value })
  })

  const zoneImpot = cible.querySelector<HTMLElement>('#qav-impot-detail')!
  if (choisi) {
    const d = await chargerSiPresent<Impot>(`qui_a_vote/${choisi.fichier}`)
    zoneImpot.innerHTML = d ? rendreImpot(d) : absent('Données de cet impôt non disponibles.')
    rendreDefilables(zoneImpot)
    if (d)
      zoneImpot.addEventListener('click', async (e) => {
        const b = (e.target as HTMLElement).closest<HTMLButtonElement>('button[data-nominatif]')
        if (!b) return
        const zone = b.nextElementSibling as HTMLElement
        b.disabled = true
        const v = await chargerSiPresent<Votes>(`qui_a_vote/${d.fichier_votes}`)
        zone.innerHTML = v ? `<p class="aide" data-regle-ordre>${h(d.regle_ordre_groupes)}</p>${rendreNominatif(v, Number(b.dataset.nominatif))}` : absent('Vote nominatif non disponible.')
        b.hidden = true
      })
  }

  const dep = cible.querySelector<HTMLSelectElement>('#qav-dep')!
  const circo = cible.querySelector<HTMLSelectElement>('#qav-circo')!
  const zoneDep = cible.querySelector<HTMLElement>('#qav-depute')!
  let fichierDep: DepFichier | null = null
  const choisirDep = async () => {
    const d = idx.departements.find((x) => x.code === dep.value)
    zoneDep.innerHTML = ''
    fichierDep = null
    circo.disabled = !d
    circo.innerHTML = d
      ? `<option value="">Choisir…</option>${d.circonscriptions.map((c) => `<option value="${c}">${c === 1 ? '1re' : `${c}e`} circonscription</option>`).join('')}`
      : '<option value="">Choisis d’abord un département</option>'
    if (d) fichierDep = await chargerSiPresent<DepFichier>(`qui_a_vote/${d.fichier}`)
  }
  const choisirCirco = async () => {
    const d = idx.departements.find((x) => x.code === dep.value)
    if (!d || !circo.value) return
    fichierDep = fichierDep ?? (await chargerSiPresent<DepFichier>(`qui_a_vote/${d.fichier}`))
    const sc = await charger<ScrutinsListe>('qui_a_vote/scrutins.json').catch(() => null)
    const c = fichierDep?.circonscriptions.find((x) => x.numero === Number(circo.value))
    if (!c || !sc) {
      zoneDep.innerHTML = absent('Données de cette circonscription non disponibles.')
      return
    }
    zoneDep.innerHTML = `<h3>${h(d.nom)}, ${c.numero === 1 ? '1re' : `${c.numero}e`} circonscription</h3>
<p class="aide" data-regle-ordre>Députés dans l’ordre de début de mandat ; scrutins dans l’ordre chronologique.</p>
${c.deputes.map((x) => rendreDepute(x, sc.scrutins, nomsImpots)).join('')}
<p class="aide">« ${h(SANS_POSITION)} » : le député était en fonction mais n’apparaît dans aucune liste du scrutin ; la source ne dit pas pourquoi.</p>`
    rendreDefilables(zoneDep)
  }
  dep.addEventListener('change', choisirDep)
  circo.addEventListener('change', choisirCirco)
  // Lien venu de la recherche du site : ?dep=<code>&circo=<numéro> ouvre directement cette circonscription.
  const depVoulu = idx.departements.find((x) => x.code === params.get('dep'))
  if (depVoulu) {
    dep.value = depVoulu.code
    await choisirDep()
    const n = Number(params.get('circo'))
    if (depVoulu.circonscriptions.includes(n)) {
      circo.value = String(n)
      await choisirCirco()
    }
  }
}

// Méthode : fraîcheur des données (site/data/fraicheur/index.json, écrit par pipeline/fraicheur.py).
// Pour chaque source : dernière collecte, millésime publié, date de publication par la source, prochaine édition
// attendue (calendrier officiel, sinon rien), statut. Liste filtrable et triable ; ce que fait la mise à jour du lundi.
import { choix, fixerChoix, listeRecherche, valeurChoix } from '../composants/choix'
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { route } from '../routes'
import { absent, entier, h, source } from '../util'
import { enCours } from './dette'

export type StatutFraicheur = 'a_jour' | 'en_retard' | 'inaccessible' | 'non_verifiee'

export interface SourceFraicheur {
  id: string
  titre: string
  producteur: string
  url: string | null
  origine: string
  etapes: string[]
  derniere_collecte: string | null
  derniere_verification: string | null
  collecte_origine: 'manifeste' | 'verification' | 'page' | null
  statut_collecte: string | null
  millesime_publie: string | null
  millesime_origine: 'source' | 'page' | null
  fichier_millesime: string | null
  publication_source: { date: string; nature: string } | null
  famille: string | null
  edition: number | null
  prochaine_publication: { date: string; edition: string; calendrier: string; passee: boolean } | null
  statut: StatutFraicheur
  explication: string
}

interface EtapeFraicheur {
  etape: string
  libelle: string
  statut_passage: string | null
  statut_passage_le: string | null
  statut_passage_origine: 'rapport' | 'passage_en_cours' | null
  millesime: string | null
  sources: number
  par_statut: Record<StatutFraicheur, number>
  derniere_collecte: string | null
  sources_inaccessibles_passage: string[]
  signalements: { source: string; constat: string; fichier: string }[]
}

export interface Fraicheur {
  millesime: string
  source: string
  date_reference: string
  rapport_passage: { genere_le: string | null; mode?: string | null }
  mise_a_jour_hebdomadaire: {
    jour: string | null
    heure_utc: string | null
    relecture_mensuelle: boolean
    budget_s?: number | null
    etapes: { etape: string; libelle: string }[]
  }
  statuts: Record<StatutFraicheur, { libelle: string; definition: string }>
  calendriers: { id: string; libelle: string; regle: string; reference: string; url: string; familles: { libelle: string; derniere_edition: number | null }[] }[]
  comptes: Record<StatutFraicheur, number>
  total: number
  etapes: EtapeFraicheur[]
  sources: SourceFraicheur[]
  non_collectables: { source: string; motif: string }[]
  ordre?: { regle: string }
  limites: string[]
  recherche_prealable?: { date: string; conclusion: string; trouvailles: { nom: string; licence: string | null; dernier_commit: string | null; verdict: string }[] }
}

export const STATUTS_ORDRE: StatutFraicheur[] = ['a_jour', 'en_retard', 'inaccessible', 'non_verifiee']
/** Mot court du statut, toujours écrit (aucune couleur ne porte le sens). */
export const MOT_STATUT: Record<StatutFraicheur, string> = {
  a_jour: 'à jour',
  en_retard: 'en retard',
  inaccessible: 'inaccessible',
  non_verifiee: 'non vérifiée',
}
const PAR_PAGE = 30
const AUCUNE = '__aucune'

// Page du site qui montre les données d'une étape ; le lien n'est posé que si la route existe.
const PAGES: Record<string, string> = {
  base: '/explorer/etat',
  beneficiaires: '/beneficiaires',
  operateurs: '/explorer/operateurs',
  vie_politique: '/decisions/vie-politique',
  realisations: '/decisions/realisations',
  decisions: '/decisions/votes',
  secu: '/explorer/secu',
  niches: '/explorer/niches',
  ue: '/explorer/ue',
  dette: '/explorer/dette',
  tracabilite: '/methode/tracabilite',
  local: '/local',
  controle: '/decisions/controle',
  local_fonctions: '/explorer/collectivites',
  territoires: '/explorer/collectivites',
  sante_etablissements: '/explorer/hopitaux',
}
export function pageDuSite(etape: string): string | null {
  for (const c of [PAGES[etape], `/explorer/${etape.replace(/_/g, '-')}`]) if (c && route(c)) return c
  return null
}

const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
/** « 6 octobre 2026 » à partir de « 2026-10-06 » ; « date inconnue » si absente. */
export function dateLongue(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  if (!m) return 'date inconnue'
  const j = Number(m[3])
  return `${j === 1 ? '1er' : j} ${MOIS[Number(m[2]) - 1]} ${m[1]}`
}

const PASSAGE: Record<string, string> = {
  produit: 'refaite',
  partiel: 'en partie refaite',
  conserve: 'version précédente gardée',
  echec: 'erreur, version précédente gardée',
  reporte: 'reportée, version précédente gardée',
}
function passage(e: EtapeFraicheur): string {
  if (!e.statut_passage) return 'pas encore passée'
  const quand = e.statut_passage_le ? ` le ${dateLongue(e.statut_passage_le)}` : ''
  return `${PASSAGE[e.statut_passage] ?? e.statut_passage}${quand}`
}

function comptesEtape(p: Record<StatutFraicheur, number>, total: number): string {
  const parts = STATUTS_ORDRE.filter((s) => p[s]).map((s) => `${entier(p[s])} ${MOT_STATUT[s]}`)
  return `${entier(total)} source${total > 1 ? 's' : ''}${parts.length ? ` : ${parts.join(', ')}` : ''}`
}

/** Tri de la liste : page (ordre de la mise à jour, celui du fichier), dernière collecte, prochaine édition, nom. */
export function trier(liste: SourceFraicheur[], tri: string): SourceFraicheur[] {
  const nom = (a: SourceFraicheur, b: SourceFraicheur) => a.titre.localeCompare(b.titre, 'fr')
  const copie = [...liste]
  if (tri === 'nom') return copie.sort(nom)
  if (tri === 'collecte')
    return copie.sort((a, b) => (b.derniere_collecte ?? '').localeCompare(a.derniere_collecte ?? '') || nom(a, b))
  if (tri === 'prochaine')
    return copie.sort((a, b) => (a.prochaine_publication?.date ?? '9999').localeCompare(b.prochaine_publication?.date ?? '9999') || nom(a, b))
  return copie
}

export function filtrer(liste: SourceFraicheur[], f: { q: string; statut: string; page: string }): SourceFraicheur[] {
  const q = f.q.trim().toLocaleLowerCase('fr')
  return liste.filter(
    (s) =>
      (!f.statut || s.statut === f.statut) &&
      (!f.page || (f.page === AUCUNE ? s.etapes.length === 0 : s.etapes.includes(f.page))) &&
      (!q || `${s.titre} ${s.producteur} ${s.id}`.toLocaleLowerCase('fr').includes(q)),
  )
}

function ligne(s: SourceFraicheur, libelles: Map<string, string>): string {
  const pages = s.etapes
    .map((e) => {
      const c = pageDuSite(e)
      const nom = h(libelles.get(e) ?? e)
      return c ? `<a href="${lien(c)}">${nom}</a>` : nom
    })
    .join(', ')
  const collecte = s.derniere_collecte
    ? `${s.collecte_origine === 'verification' ? 'Version vérifiée le' : 'Dernière collecte le'} ${dateLongue(s.derniere_collecte)}${s.collecte_origine === 'page' ? ' (date publiée par la page)' : ''}`
    : s.derniere_verification
      ? `Dernière tentative de collecte le ${dateLongue(s.derniere_verification)}`
      : 'Aucune collecte datée'
  const pub = s.publication_source ? `Publiée par la source le ${dateLongue(s.publication_source.date)} (${h(s.publication_source.nature)})` : 'Date de publication non déclarée par la source'
  const prochaine = s.prochaine_publication
    ? `Prochaine édition attendue : ${h(s.prochaine_publication.edition)}, au plus tard le ${dateLongue(s.prochaine_publication.date)}${s.prochaine_publication.passee ? ' (date passée)' : ''}`
    : 'Prochaine édition : aucun calendrier officiel connu'
  return `<li data-id="${h(s.id)}"><span>${h(s.titre)}</span><span class="badge badge-admin">${h(MOT_STATUT[s.statut])}</span><span class="dest">${h(s.producteur)}${
    pages ? ` · ${s.etapes.length > 1 ? 'Pages' : 'Page'} : ${pages}` : ' · Aucune page rattachée'
  }<br>${collecte} · Millésime publié : ${s.millesime_publie ? h(s.millesime_publie) : 'non indiqué'}<br>${pub}<br>${prochaine}<br>${h(s.explication)}${
    s.url ? `<br><a href="${h(s.url)}" rel="noopener noreferrer">Page de la source chez ${h(s.producteur)}</a>` : ''
  }</span></li>`
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const f = await chargerSiPresent<Fraicheur>('fraicheur/index.json')
  if (!f) {
    cible.innerHTML =
      enCours('Fraîcheur des données', 'Date de la dernière collecte, année couverte et prochaine édition attendue de chaque source publique.') +
      `<p class="liens-sortie"><a href="${lien('/methode')}">Méthode et sources</a></p>`
    return
  }
  const maj = f.mise_a_jour_hebdomadaire
  const libelles = new Map<string, string>([...maj.etapes.map((e) => [e.etape, e.libelle] as [string, string]), ...f.etapes.map((e) => [e.etape, e.libelle] as [string, string])])
  const statutInitial = STATUTS_ORDRE.includes(params.get('statut') as StatutFraicheur) ? (params.get('statut') as string) : ''
  const pageInitiale = params.get('page') && (libelles.has(params.get('page')!) || params.get('page') === AUCUNE) ? (params.get('page') as string) : ''
  const etat = { q: '', statut: statutInitial, page: pageInitiale, tri: 'page', vus: PAR_PAGE }
  const signales = f.etapes.filter((e) => e.signalements.length || e.sources_inaccessibles_passage.length)
  const heure = maj.heure_utc ? `${Number(maj.heure_utc.slice(0, 2))} h ${maj.heure_utc.slice(3, 5)}` : null
  const duree = maj.budget_s ? `${Math.floor(maj.budget_s / 3600)} h ${String(Math.round((maj.budget_s % 3600) / 60)).padStart(2, '0')}` : null

  cible.innerHTML = `
<h1>Fraîcheur des données</h1>
<p class="chapeau">Pour chaque source publique lue par le site : la date de sa dernière collecte, l’année couverte par les chiffres publiés, la date de publication déclarée par la source et la date de la prochaine édition quand un calendrier officiel la fixe. La page décrit l’état de la collecte : elle ne dit rien de la qualité d’une source ni de l’usage de l’argent public.</p>
<div class="carte">
  <p>État au <strong>${h(dateLongue(f.date_reference))}</strong>, date de la dernière collecte : ${h(entier(f.total))} sources suivies.</p>
  <div class="tableau-defile"><table><caption>Sources par statut au ${h(dateLongue(f.date_reference))}</caption>
  <thead><tr><th scope="col">Statut</th><th scope="col" class="nombre">Sources</th></tr></thead>
  <tbody>${STATUTS_ORDRE.map((s) => `<tr><th scope="row">${h(f.statuts[s]?.libelle ?? MOT_STATUT[s])}</th><td class="nombre">${h(entier(f.comptes[s] ?? 0))}</td></tr>`).join('')}</tbody></table></div>
  ${source(f.source, f.millesime)}
</div>

<h2>Ce que fait la mise à jour ${maj.jour ? `du ${h(maj.jour)}` : 'de chaque semaine'}</h2>
<ol>
  <li>${maj.jour && heure ? `Chaque ${h(maj.jour)} à ${h(heure)} (temps universel)` : 'Chaque semaine'}, la mise à jour automatique démarre, sans intervention.</li>
  <li>Elle reprend les fichiers bruts de la semaine précédente et télécharge ceux qui manquent.${maj.relecture_mensuelle ? ' Le premier lundi du mois, elle relit aussi toutes les sources pour repérer une nouvelle version.' : ''}</li>
  <li>Elle refait les pages du site dans l’ordre, en ${h(entier(maj.etapes.length))} étapes : collecte des sources de la page, puis calcul des fichiers publiés. Une source qui refuse l’accès ou ne répond pas n’arrête pas la semaine : la page garde sa dernière version publiée et cette page-ci le signale.</li>
  <li>Elle vérifie le format de chaque fichier, le contrat d’interface et les tests automatiques.</li>
  <li>Elle ne publie que si une donnée a changé ; sinon le site reste tel quel.${duree ? ` Elle s’arrête au plus tard après ${h(duree)} : une page non traitée garde sa dernière version.` : ''}</li>
</ol>
<details><summary>Les ${h(entier(maj.etapes.length))} étapes, dans l’ordre</summary><ol>${maj.etapes.map((e) => `<li>${h(e.libelle)}</li>`).join('')}</ol></details>

<h2>Les statuts</h2>
<dl>${STATUTS_ORDRE.map((s) => `<dt>${h(f.statuts[s]?.libelle ?? MOT_STATUT[s])}</dt><dd>${h(f.statuts[s]?.definition ?? '')}</dd>`).join('')}</dl>

<h2>Par page du site</h2>
<div class="tableau-defile"><table><caption>Fraîcheur par page : dernier passage, millésime publié, dernière collecte et sources par statut</caption>
<thead><tr><th scope="col">Page</th><th scope="col">Dernier passage</th><th scope="col">Millésime publié</th><th scope="col">Dernière collecte</th><th scope="col">Sources</th></tr></thead>
<tbody>${f.etapes
    .map((e) => {
      const c = pageDuSite(e.etape)
      return `<tr><th scope="row">${c ? `<a href="${lien(c)}">${h(e.libelle)}</a>` : h(e.libelle)}</th><td>${h(passage(e))}</td><td>${h(e.millesime ?? 'non indiqué')}</td><td>${h(e.derniere_collecte ? dateLongue(e.derniere_collecte) : 'aucune collecte datée')}</td><td>${h(comptesEtape(e.par_statut, e.sources))}</td></tr>`
    })
    .join('')}</tbody></table></div>
${
  signales.length
    ? `<details><summary>Sources signalées inaccessibles ou non publiées par les pages (${h(entier(signales.reduce((n, e) => n + e.signalements.length + e.sources_inaccessibles_passage.length, 0)))})</summary>${signales
        .map(
          (e) =>
            `<h3>${h(e.libelle)}</h3><ul>${[
              ...e.sources_inaccessibles_passage.map((c) => `<li>Dernier passage : ${h(c)}</li>`),
              ...e.signalements.map((s) => `<li>${h(s.source)} : ${h(s.constat)}</li>`),
            ].join('')}</ul>`,
        )
        .join('')}</details>`
    : ''
}

<h2>Toutes les sources</h2>
<form id="fr-filtres" class="carte">
  <label for="fr-q">Chercher une source</label>
  <input id="fr-q" type="search" autocomplete="off" />
  ${choix({ id: 'fr-statut', etiquette: 'Statut', options: [{ valeur: '', libelle: 'Tous' }, ...STATUTS_ORDRE.map((s) => ({ valeur: s, libelle: `${f.statuts[s]?.libelle ?? MOT_STATUT[s]} (${entier(f.comptes[s] ?? 0)})` }))], valeur: etat.statut })}
  ${listeRecherche({ id: 'fr-page', etiquette: 'Page du site', options: [], optionsHtml: `<option value="">Toutes</option>${f.etapes
    .filter((e) => e.sources)
    .map((e) => `<option value="${h(e.etape)}"${e.etape === etat.page ? ' selected' : ''}>${h(e.libelle)}</option>`)
    .join('')}<option value="${AUCUNE}"${etat.page === AUCUNE ? ' selected' : ''}>Aucune page rattachée</option>` })}
  ${choix({ id: 'fr-tri', etiquette: 'Trier par', options: [{ valeur: 'page', libelle: 'Page du site, dans l’ordre de la mise à jour' }, { valeur: 'collecte', libelle: 'Dernière collecte, la plus récente d’abord' }, { valeur: 'prochaine', libelle: 'Prochaine édition attendue, la plus proche d’abord' }, { valeur: 'nom', libelle: 'Nom de la source' }], valeur: etat.tri })}
</form>
<p id="fr-compte" aria-live="polite"></p>
<ul class="lignes" id="fr-liste"></ul>
<p id="fr-suite"></p>
${f.ordre?.regle ? `<p class="aide" data-regle-ordre>${h(f.ordre.regle)}</p>` : ''}

<h2>Calendriers officiels utilisés</h2>
<ul>${f.calendriers
    .map(
      (c) =>
        `<li><strong>${h(c.libelle)}</strong> : ${h(c.regle)}. Texte : <a href="${h(c.url)}" rel="noopener noreferrer">${h(c.reference)}</a>.${
          c.familles.length ? ` Publications suivies : ${c.familles.map((x) => `${h(x.libelle)}${x.derniere_edition ? ` (dernière édition collectée : ${h(x.derniere_edition)})` : ''}`).join(' ; ')}.` : ''
        }</li>`,
    )
    .join('')}</ul>
<p>Une source sans calendrier officiel connu n’a pas de date de prochaine édition : la page ne l’estime pas.</p>
${
  f.non_collectables.length
    ? `<details><summary>Sources non collectables automatiquement (${h(entier(f.non_collectables.length))})</summary><ul>${f.non_collectables.map((x) => `<li>${h(x.source)} : ${h(x.motif)}</li>`).join('')}</ul></details>`
    : ''
}

<h2>Limites</h2>
<ul>${f.limites.map((l) => `<li>${h(l)}</li>`).join('')}</ul>
${
  f.recherche_prealable
    ? `<details><summary>Outils publics examinés avant d’écrire cette page</summary><p>${h(f.recherche_prealable.conclusion)}</p><ul>${f.recherche_prealable.trouvailles
        .map((t) => `<li>${h(t.nom)} (licence ${h(t.licence ?? 'non précisée')}${t.dernier_commit ? `, dernière version ${h(t.dernier_commit)}` : ''}) : ${h(t.verdict)}</li>`)
        .join('')}</ul></details>`
    : ''
}
<p>Ce que les données ne permettent pas de dire : <a href="${lien('/methode/limites')}">limites connues</a>. Rapport du dernier passage écrit : ${h(f.rapport_passage.genere_le ? dateLongue(f.rapport_passage.genere_le) : 'non disponible')}.</p>`

  const zone = cible.querySelector('#fr-liste') as HTMLElement
  const compte = cible.querySelector('#fr-compte') as HTMLElement
  const suite = cible.querySelector('#fr-suite') as HTMLElement
  const dessiner = () => {
    const liste = trier(filtrer(f.sources, etat), etat.tri)
    const visibles = liste.slice(0, etat.vus)
    compte.textContent = liste.length ? `${entier(liste.length)} source${liste.length > 1 ? 's' : ''} sur ${entier(f.total)}.` : ''
    zone.innerHTML = visibles.map((s) => ligne(s, libelles)).join('')
    zone.hidden = !liste.length
    suite.innerHTML = liste.length
      ? liste.length > visibles.length
        ? `<button type="button" id="fr-plus">Afficher ${h(entier(Math.min(PAR_PAGE, liste.length - visibles.length)))} de plus</button>`
        : ''
      : absent('Aucune source ne correspond.')
    suite.querySelector('#fr-plus')?.addEventListener('click', () => {
      etat.vus += PAR_PAGE
      dessiner()
    })
  }
  const form = cible.querySelector('#fr-filtres') as HTMLFormElement
  // Filtres demandés par l'adresse (?statut=, ?page=) : valeur posée aussi par le DOM, pas seulement par « selected ».
  fixerChoix(cible, 'fr-statut', etat.statut)
  fixerChoix(cible, 'fr-page', etat.page)
  form.addEventListener('submit', (e) => e.preventDefault())
  form.addEventListener('input', (e) => {
    if ((e.target as HTMLElement).matches('.choix-filtre')) return
    etat.q = (cible.querySelector('#fr-q') as HTMLInputElement).value
    etat.statut = valeurChoix(cible, 'fr-statut')
    etat.page = valeurChoix(cible, 'fr-page')
    etat.tri = valeurChoix(cible, 'fr-tri') as typeof etat.tri
    etat.vus = PAR_PAGE
    dessiner()
  })
  dessiner()
}

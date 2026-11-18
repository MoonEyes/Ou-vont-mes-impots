// Application des lois (site/data/application_lois/) : pour chaque loi publiée depuis juillet 2002, les mesures
// d'application prévues par l'échéancier de Légifrance, celles dont le texte est publié, celles en attente, et les
// délais, d'après le baromètre de l'Assemblée nationale et de LexImpact. Lois de finances et de financement de la
// Sécurité sociale d'abord. Aucun classement ni qualificatif : ordre par date de publication, valeurs telles que
// publiées ; le taux est celui du baromètre (calcul de LexImpact) ; délais par loi et sommes par année portent le
// badge « calculé par le site » avec leur méthode. Aucun nom de personne (colonnes retirées par le pipeline).
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { absent, badgeStatut, entier, h, pct, rendreDefilables, traitStatut } from '../util'
import { enCours } from './dette'

const CHEMIN = '/decisions/application-des-lois'

interface Delais {
  mesures: number
  minimum_jours: number
  mediane_jours: number
  maximum_jours: number
  methode: string
}
export interface Loi {
  id: string
  titre: string
  date_publication: string
  annee: number
  categorie: string | null
  categorie_libelle: string | null
  commission_saisie_au_fond: string | null
  application_directe: boolean | null
  sans_echeancier: boolean | null
  mesures_a_appliquer: number | null
  mesures_appliquees: number | null
  mesures_en_attente: number
  mesures_sans_objet: number
  taux_application_publie: number | null
  taux_note: string
  delais: Delais | null
  url_legifrance: string
  url_dossier_legislatif: string | null
  fichier_mesures: string | null
}
export interface Mesure {
  numero: number | null
  articles: string | null
  base_legale: string | null
  objet: string | null
  observations: string | null
  etat: string | null
  date_prevue: string | null
  decret: string | null
  decret_url: string | null
  delai_jours: number | null
  textes_non_repris?: Record<string, string>
}
interface Annee {
  annee: number
  fichier: string
  lois: number
  lois_application_directe: number
  lois_sans_echeancier: number
  lois_avec_mesures: number
  mesures_a_appliquer: number
  mesures_appliquees: number
  mesures_en_attente: number
  mesures_sans_objet: number
}
interface Index {
  millesime: string
  source: string
  collecte_le: string
  avertissement: string
  definitions: Record<string, string>
  confidentialite: string
  sources: { fichier: string; titre: string; producteur: string; licence: string; url: string; url_fichier: string | null; ressource_modifiee_le: string | null; collecte_le: string }[]
  comptes: { lois: number; mesures: number; lois_finances: number; textes_non_repris: number }
  par_annee: { methode: string; annees: Annee[] }
  lois_finances: { categories: { categorie: string; libelle: string; lois: number }[] }
}
interface Liste {
  source: string
  ordre: { regle: string }
  avertissement: string
  lois: Loi[]
}
interface Mesures {
  source: string
  ordre: { regle: string }
  mesures: Mesure[]
}

const LIBELLE_CALCULE = 'Calculé par le site'
/** Badge de la règle « chiffre calculé par le site » (même balisage que util.badgeCalcule de la branche d'intégration). */
const badgeCalcule = () => `<span class="badge badge-calcule" data-calcule><span class="motif motif-calcule" aria-hidden="true"></span>${LIBELLE_CALCULE}</span>`
export const METHODE_DELAIS =
  'pour une loi, plus petit, médian et plus grand des délais publiés par LexImpact pour ses mesures appliquées (jours entre la publication de la loi et celle du texte d’application). Les mesures en attente n’ont pas de délai.'
export const REGLE_ORDRE = 'Ordre des lois : de la plus récente à la plus ancienne, par date de publication au Journal officiel. Aucun classement par taux ni par délai.'

const LIBELLES: Record<string, string> = {
  mesures_a_appliquer: 'Mesures à appliquer',
  mesures_appliquees: 'Mesures appliquées',
  mesures_en_attente: 'Mesures en attente',
  mesures_sans_objet: 'Mesures sans objet',
  taux_application_publie: 'Taux publié par le baromètre',
  delai_jours: 'Délai d’une mesure',
  date_prevue: 'Date prévue',
  application_directe: 'Loi d’application directe',
  sans_echeancier: 'Loi sans échéancier',
  categorie: 'Type de loi financière',
}
const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
/** « 2026-02-19 » devient « 19 février 2026 ». */
export const dateLongue = (d: string | null) => {
  const m = d ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(d) : null
  return m ? `${Number(m[3])}${m[3] === '01' ? 'er' : ''} ${MOIS[Number(m[2]) - 1]} ${m[1]}` : 'non publiée'
}
const nb = (x: number | null) => (typeof x === 'number' ? entier(x) : 'non publié')
const jours = (x: number) => `${entier(x)} jour${Math.abs(x) >= 2 ? 's' : ''}`

/** Taux tel que publié par le baromètre, ou la raison de son absence (jamais 0 à la place). */
export function tauxPublie(l: Loi): string {
  return typeof l.taux_application_publie === 'number' ? pct(l.taux_application_publie * 100, 1) : 'sans objet (aucune mesure à appliquer)'
}
/** Délai médian (calculé par le site) ou la raison de son absence. */
export function delaiMedian(l: Loi): string {
  return l.delais ? `${jours(l.delais.mediane_jours)} (de ${entier(l.delais.minimum_jours)} à ${entier(l.delais.maximum_jours)}, ${entier(l.delais.mesures)} mesure${l.delais.mesures > 1 ? 's' : ''})` : 'aucun délai publié'
}
/** Phrase de lecture d'une loi, sans qualificatif. */
export function lectureLoi(l: Loi): string {
  if (l.application_directe && !l.mesures_a_appliquer && !l.mesures_sans_objet) return 'loi d’application directe : aucune mesure d’application prévue'
  if (l.sans_echeancier && !l.fichier_mesures) return 'pas d’échéancier publié par Légifrance pour cette loi'
  return `${nb(l.mesures_a_appliquer)} mesure${(l.mesures_a_appliquer ?? 0) > 1 ? 's' : ''} à appliquer, ${nb(l.mesures_appliquees)} appliquée${(l.mesures_appliquees ?? 0) > 1 ? 's' : ''}, ${entier(l.mesures_en_attente)} en attente, ${entier(l.mesures_sans_objet)} sans objet`
}

function ligneLoi(l: Loi): string {
  return `<li><details data-id="${h(l.id)}"${l.fichier_mesures ? ` data-fichier="${h(l.fichier_mesures)}"` : ''}><summary>${h(l.titre)}</summary><div class="fiche"></div></details><span class="dest">${h(
    l.categorie_libelle ? `${l.categorie_libelle} · ` : '',
  )}publiée le ${h(dateLongue(l.date_publication))} · ${h(lectureLoi(l))}${
    l.mesures_a_appliquer ? ` · taux publié par le baromètre : ${h(tauxPublie(l))} · délai médian (calculé par le site) : ${h(delaiMedian(l))}` : ''
  }</span></li>`
}

/** Tableau des mesures d'une loi, dans l'ordre de l'échéancier. */
export function tableauMesures(l: Loi, m: Mesures): string {
  const nonRepris = (x: Mesure, k: string) => (x.textes_non_repris?.[k] ? `${traitStatut('nonpub')}texte non repris (filtre de noms de personnes du site)` : '–')
  return `<p><a href="${h(l.url_legifrance)}">Texte de la loi sur Légifrance</a>${l.url_dossier_legislatif ? ` · <a href="${h(l.url_dossier_legislatif)}">dossier législatif et échéancier</a>` : ''}${
    l.commission_saisie_au_fond ? ` · commission de l’Assemblée saisie au fond : ${h(l.commission_saisie_au_fond)}` : ''
  }</p>
<p class="aide">${h(l.taux_note)}.</p>
<div class="tableau-defile"><table><caption>Mesures d’application prévues par l’échéancier : ${h(l.titre)}</caption>
<thead><tr><th scope="col">N°</th><th scope="col">Article</th><th scope="col">Objet</th><th scope="col">État publié</th><th scope="col">Date prévue</th><th scope="col">Texte d’application</th><th scope="col" class="nombre">Délai publié (LexImpact)</th></tr></thead>
<tbody>${m.mesures
    .map(
      (x) =>
        `<tr><th scope="row">${x.numero ?? '–'}</th><td>${h(x.articles ?? '–')}${x.base_legale ? `<br><span class="aide">${h(x.base_legale)}</span>` : ''}</td><td>${x.objet ? h(x.objet) : nonRepris(x, 'objet')}${
          x.observations ? `<br><span class="aide">Observation de la DILA : ${h(x.observations)}</span>` : ''
        }</td><td>${h(x.etat ?? 'non publié')}</td><td>${x.date_prevue ? h(dateLongue(x.date_prevue)) : '–'}</td><td>${x.decret_url ? `<a href="${h(x.decret_url)}">${h(x.decret)}</a>` : '–'}</td><td class="nombre">${
          typeof x.delai_jours === 'number' ? h(jours(x.delai_jours)) : '–'
        }</td></tr>`,
    )
    .join('')}</tbody></table></div>
<p class="aide" data-regle-ordre>${h(m.ordre.regle)}</p>`
}

function brancherFiches(zone: HTMLElement, lois: Map<string, Loi>) {
  zone.querySelectorAll<HTMLDetailsElement>('details[data-id]').forEach((d) =>
    d.addEventListener('toggle', async () => {
      const fz = d.querySelector('.fiche') as HTMLElement
      if (!d.open || fz.innerHTML) return
      const l = lois.get(d.dataset.id ?? '')
      if (!l) return
      if (!d.dataset.fichier) {
        fz.innerHTML = `<p>${h(lectureLoi(l))}.</p><p><a href="${h(l.url_legifrance)}">Texte de la loi sur Légifrance</a></p>`
        return
      }
      fz.innerHTML = '<p class="aide">Chargement des mesures…</p>'
      const m = await chargerSiPresent<Mesures>(d.dataset.fichier.replace(/^\//, ''))
      fz.innerHTML = m ? tableauMesures(l, m) : absent('Mesures non disponibles pour cette loi.')
      rendreDefilables(fz)
    }),
  )
}

export async function rendre(cible: HTMLElement, params: URLSearchParams = new URLSearchParams()) {
  const [idx, fin] = await Promise.all([chargerSiPresent<Index>('application_lois/index.json'), chargerSiPresent<Liste>('application_lois/lois_finances.json')])
  if (!idx || !fin) {
    cible.innerHTML = enCours('Application des lois', 'Mesures d’application prévues et publiées, loi par loi.')
    return
  }
  const annees = idx.par_annee.annees
  const anneeDemandee = Number(params.get('annee'))
  const etat = { cat: '', annee: annees.some((a) => a.annee === anneeDemandee) ? anneeDemandee : annees[0].annee, q: '' }
  const src = idx.sources[0]
  const derniereLfi = fin.lois.find((l) => l.categorie === 'lf_initiale')
  const derniereLfss = fin.lois.find((l) => l.categorie === 'lfss')
  const cle = (l: Loi | undefined) =>
    l
      ? `<li><strong>${h(tauxPublie(l))}</strong><span>des ${h(nb(l.mesures_a_appliquer))} mesures à appliquer de la ${h(l.titre.replace(/^LOI\s+/i, 'loi '))} ont leur texte publié, selon le baromètre au ${h(src.ressource_modifiee_le ?? idx.collecte_le)}</span>${badgeStatut('trace')}</li>`
      : ''
  const cats = idx.lois_finances.categories.filter((c) => c.lois > 0)

  cible.innerHTML = `
<h1>Application des lois : mesures prévues et publiées</h1>
<p class="chapeau">Une loi renvoie souvent une partie de ses règles à des textes pris ensuite par le Gouvernement (décrets, arrêtés) : ce sont ses mesures d’application. Pour chaque loi publiée depuis juillet 2002, cette page donne les mesures prévues par l’échéancier de Légifrance, celles dont le texte est publié, celles en attente, et les délais. Elle ne dit pas pourquoi un texte n’est pas encore publié : la source ne le précise pas.</p>
<ul class="cles" aria-label="Chiffres clés de l’application des lois de finances">
  ${cle(derniereLfi)}
  ${cle(derniereLfss)}
</ul>
<p class="source">${h(`${src.producteur}, « ${src.titre} », ${src.licence}, ressources du ${src.ressource_modifiee_le ?? 'non précisé'}, collectées le ${src.collecte_le}`)} · <a href="${h(src.url)}">jeu de données</a></p>
<ul class="legende-statuts" aria-label="Lecture des valeurs">
  <li>${traitStatut('trace')}<span><strong>Tracé</strong> : valeur publiée par le baromètre, reprise telle quelle (le taux et les délais par mesure sont des calculs de LexImpact)</span></li>
  <li><span class="motif motif-calcule" aria-hidden="true"></span><span><strong>${LIBELLE_CALCULE}</strong> : délai médian d’une loi et sommes par année, calculés par le site à partir de valeurs publiées pour la même loi ou la même année, méthode écrite à côté</span></li>
  <li>${traitStatut('nonpub')}<span><strong>Non publié</strong> : valeur absente de la source ou texte non repris ; jamais compté pour zéro</span></li>
</ul>

<h2>Lois de finances et de financement de la Sécurité sociale</h2>
<p>Le budget de l’État est voté chaque année par une loi de finances, celui de la Sécurité sociale par une loi de financement. Leurs articles renvoient eux aussi à des décrets et arrêtés.</p>
<form id="filtres-al-fin" class="carte">
  <label for="al-cat">Type de loi</label>
  <select id="al-cat"><option value="">Toutes (${h(entier(fin.lois.length))})</option>${cats.map((c) => `<option value="${h(c.categorie)}">${h(c.libelle)} (${h(entier(c.lois))})</option>`).join('')}</select>
</form>
<p class="aide" data-regle-ordre>${h(REGLE_ORDRE)}</p>
<p class="aide">Délai médian ${badgeCalcule()} <span class="methode-calcul">Méthode : ${h(METHODE_DELAIS)}</span></p>
<div id="liste-al-fin" aria-live="polite"></div>

<h2>Toutes les lois, année par année</h2>
<div class="tableau-defile"><table><caption>Lois publiées chaque année et mesures d’application prévues par leurs échéanciers, état au ${h(src.ressource_modifiee_le ?? idx.collecte_le)}</caption>
<thead><tr><th scope="col">Année de publication des lois</th><th scope="col" class="nombre">Lois</th><th scope="col" class="nombre">dont d’application directe</th><th scope="col" class="nombre">Mesures à appliquer</th><th scope="col" class="nombre">Appliquées</th><th scope="col" class="nombre">En attente</th><th scope="col" class="nombre">Sans objet</th></tr></thead>
<tbody>${annees
    .map(
      (a) =>
        `<tr><th scope="row"><a href="${lien(CHEMIN, { annee: a.annee })}">${a.annee}</a></th><td class="nombre">${h(entier(a.lois))}</td><td class="nombre">${h(entier(a.lois_application_directe))}</td><td class="nombre">${h(entier(a.mesures_a_appliquer))}</td><td class="nombre">${h(entier(a.mesures_appliquees))}</td><td class="nombre">${h(entier(a.mesures_en_attente))}</td><td class="nombre">${h(entier(a.mesures_sans_objet))}</td></tr>`,
    )
    .join('')}</tbody></table></div>
<p class="aide">${badgeCalcule()} <span class="methode-calcul">Méthode : ${h(idx.par_annee.methode)}</span> Une loi récente a eu moins de temps pour recevoir ses textes d’application qu’une loi ancienne : deux années ne se comparent pas directement.</p>
<form id="filtres-al-annee" class="carte">
  <label for="al-annee">Année</label>
  <select id="al-annee">${annees.map((a) => `<option value="${a.annee}"${a.annee === etat.annee ? ' selected' : ''}>${a.annee} (${h(entier(a.lois))} lois)</option>`).join('')}</select>
  <label for="al-q">Chercher dans les titres</label>
  <input id="al-q" type="search" autocomplete="off" />
</form>
<p class="aide" data-regle-ordre>${h(REGLE_ORDRE)}</p>
<div id="liste-al-annee" aria-live="polite"></div>

<details><summary>Méthode, limites et sources</summary>
<p>${h(idx.avertissement)}</p>
<ul>${Object.entries(idx.definitions)
    .map(([k, v]) => `<li><strong>${h(LIBELLES[k] ?? k.replace(/_/g, ' '))}</strong> : ${h(v)}</li>`)
    .join('')}</ul>
<p>${h(idx.confidentialite)} Textes non repris : ${h(entier(idx.comptes.textes_non_repris))}.</p>
<ul>${idx.sources
    .map((s) => `<li>${h(s.fichier === 'lois' ? 'Liste des lois' : 'Liste des mesures')} : ${s.url_fichier ? `<a href="${h(s.url_fichier)}">fichier</a>` : 'fichier'} (${h(s.producteur)}, ${h(s.licence)}, ressource du ${h(s.ressource_modifiee_le ?? 'non précisé')}, collectée le ${h(s.collecte_le)}).</li>`)
    .join('')}</ul>
</details>
<p class="liens-sortie"><a href="${lien('/decisions/votes')}">Ce que le Parlement a voté</a> <a href="${lien('/decisions/resultats')}">Cibles et résultats des programmes</a></p>`

  const zoneFin = cible.querySelector('#liste-al-fin') as HTMLElement
  const lois = new Map(fin.lois.map((l) => [l.id, l]))
  const dessinerFin = () => {
    const liste = fin.lois.filter((l) => !etat.cat || l.categorie === etat.cat)
    zoneFin.innerHTML = liste.length ? `<p>${h(entier(liste.length))} loi${liste.length > 1 ? 's' : ''}.</p><ul class="lignes">${liste.map(ligneLoi).join('')}</ul>` : absent('Aucune loi de ce type.')
    brancherFiches(zoneFin, lois)
  }
  ;(cible.querySelector('#al-cat') as HTMLSelectElement).addEventListener('change', (e) => {
    etat.cat = (e.target as HTMLSelectElement).value
    dessinerFin()
  })
  dessinerFin()

  const zoneAn = cible.querySelector('#liste-al-annee') as HTMLElement
  const dessinerAnnee = async () => {
    const a = annees.find((x) => x.annee === etat.annee)!
    const d = await chargerSiPresent<Liste>(a.fichier)
    if (!d) {
      zoneAn.innerHTML = absent('Lois de cette année non disponibles.')
      return
    }
    for (const l of d.lois) lois.set(l.id, l)
    const q = etat.q.toLowerCase()
    const liste = d.lois.filter((l) => !q || l.titre.toLowerCase().includes(q))
    zoneAn.innerHTML = liste.length ? `<p>${h(entier(liste.length))} loi${liste.length > 1 ? 's' : ''} publiée${liste.length > 1 ? 's' : ''} en ${a.annee}.</p><ul class="lignes">${liste.map(ligneLoi).join('')}</ul>` : absent('Aucune loi ne correspond.')
    brancherFiches(zoneAn, lois)
  }
  const formAn = cible.querySelector('#filtres-al-annee') as HTMLFormElement
  formAn.addEventListener('submit', (e) => e.preventDefault())
  formAn.addEventListener('input', () => {
    etat.annee = Number((cible.querySelector('#al-annee') as HTMLSelectElement).value)
    etat.q = (cible.querySelector('#al-q') as HTMLInputElement).value.trim()
    void dessinerAnnee()
  })
  await dessinerAnnee()
  rendreDefilables(cible)
}

// Lien « Signaler une erreur sur cette page » : ouvre un ticket GitHub public, pré-rempli avec l'adresse de la page,
// les fichiers de données qu'elle affiche et leur millésime. Rien n'est envoyé par le site : le lien mène à GitHub,
// où la personne relit et publie elle-même le ticket (gabarit .github/ISSUE_TEMPLATE/erreur-donnee.yml).
// Aucune donnée personnelle n'est reprise : ni salaire (jamais dans une adresse), ni saisie, ni identité.
import { versChemin } from '../chemins'
import { fichiersLus, lectureEnCache } from '../donnees'
import { h } from '../util'

export const DEPOT = 'https://github.com/MoonEyes/Ou-vont-mes-impots'
export const GABARIT = 'erreur-donnee.yml'
/** Adresse publique du site quand la page ne la porte pas (développement, tests, prérendu). */
export const SITE_DEFAUT = 'https://mooneyes.github.io/Ou-vont-mes-impots/'
/** Au-delà, la liste des fichiers est tronquée (adresse de ticket de taille raisonnable). */
export const MAX_FICHIERS = 40
const MAX_ADRESSE = 7000

export interface FichierAffiche {
  /** chemin sous data/ (« arbre/racine.json ») */
  chemin: string
  /** millésime déclaré par le fichier, null s'il n'en déclare pas un seul ; absent : fichier non disponible */
  millesime?: string | null
  absent?: boolean
}

export interface PageSignalee {
  /** titre de la page affichée */
  titre: string
  /** adresse interne « #/… » */
  adresse: string
  fichiers?: FichierAffiche[]
}

/** Adresse publique de la page (vrai chemin, paramètres de vue compris). */
export function adressePublique(fragment: string): string {
  const site = (typeof document !== 'undefined' && document.documentElement?.dataset?.site) || SITE_DEFAUT
  return site.replace(/\/*$/, '/') + versChemin(fragment)
}

const ligneFichier = (f: FichierAffiche) =>
  `- data/${f.chemin}${f.absent ? ' (fichier non disponible)' : f.millesime ? ` (millésime : ${f.millesime})` : ''}`

/** Texte du champ « fichiers » du ticket. */
export function texteFichiers(fichiers: FichierAffiche[]): string {
  if (!fichiers.length) return 'Aucun fichier de données lu par cette page.'
  const vus = fichiers.slice(0, MAX_FICHIERS).map(ligneFichier)
  if (fichiers.length > MAX_FICHIERS) vus.push(`- et ${fichiers.length - MAX_FICHIERS} autres fichiers`)
  return vus.join('\n')
}

const code = (x: string) => encodeURIComponent(x)

/** Adresse du nouveau ticket, pré-rempli (les clés reprennent les identifiants des champs du gabarit). */
export function lienTicket(p: PageSignalee): string {
  const champs = (fichiers: string) =>
    `${DEPOT}/issues/new?template=${code(GABARIT)}&title=${code(`Erreur sur la page « ${p.titre} »`)}&page=${code(adressePublique(p.adresse))}&fichiers=${code(fichiers)}`
  const fichiers = p.fichiers ?? []
  let url = champs(texteFichiers(fichiers))
  // Adresse trop longue (page qui lit beaucoup de fichiers) : la liste est raccourcie, jamais coupée au milieu d'une ligne.
  for (let n = Math.min(fichiers.length, MAX_FICHIERS) - 1; url.length > MAX_ADRESSE && n >= 0; n--) {
    const garde = fichiers.slice(0, n).map(ligneFichier)
    garde.push(`- et ${fichiers.length - n} autres fichiers`)
    url = champs(garde.join('\n'))
  }
  return url
}

/** Bloc de fin de page : le lien et l'avertissement (ticket public, aucune donnée personnelle). */
export function blocSignaler(p: PageSignalee): string {
  return `<aside class="signaler" aria-label="Signaler une erreur"><p><a class="signaler-lien" href="${h(lienTicket(p))}">Signaler une erreur sur cette page</a></p><p class="aide">Le lien ouvre un ticket sur GitHub (compte gratuit nécessaire), pré-rempli avec l’adresse de cette page et les fichiers de données affichés. Ce ticket est public : n’y écris aucune donnée personnelle, ni ton nom, ni ton salaire.</p></aside>`
}

/** Fichiers lus par la page affichée, avec le millésime qu'ils déclarent (lus dans le cache, sans nouvelle requête). */
export async function fichiersAffiches(): Promise<FichierAffiche[]> {
  const out: FichierAffiche[] = []
  for (const chemin of fichiersLus()) {
    if (chemin === '_manifeste.json') continue // fichier technique du site (liste des données optionnelles)
    const lecture = lectureEnCache(chemin)
    if (!lecture) {
      out.push({ chemin, absent: true })
      continue
    }
    let contenu: unknown = null
    try {
      contenu = await lecture
    } catch {
      out.push({ chemin, absent: true })
      continue
    }
    const m = (contenu as { millesime?: unknown } | null)?.millesime
    out.push({ chemin, millesime: typeof m === 'string' || typeof m === 'number' ? String(m) : null })
  }
  return out
}

/** Met à jour le lien de la page affichée une fois tout chargé (le bloc est ajouté s'il manque). */
export async function majSignaler(cible: HTMLElement, p: PageSignalee): Promise<void> {
  const fichiers = await fichiersAffiches()
  const lien = cible.querySelector<HTMLAnchorElement>('.signaler-lien')
  const page = { ...p, fichiers }
  if (lien) lien.setAttribute('href', lienTicket(page))
  else (cible.querySelector('.ecran') ?? cible).insertAdjacentHTML('beforeend', blocSignaler(page))
}

// Bloc « Signaler une erreur sur cette page » : invite à écrire à l'adresse de contact dédiée du site, avec une
// référence prête à copier (adresse de la page, fichiers de données qu'elle affiche et leur millésime).
// Rien n'est envoyé par le site : aucun lien, aucun formulaire ni bouton d'envoi, aucun appel réseau ; la personne
// copie la référence (champ en lecture seule) dans son propre courriel. Aucune donnée personnelle n'est reprise : ni salaire, ni saisie, ni identité.
import { versChemin } from '../chemins'
import { fichiersLus, lectureEnCache } from '../donnees'
import { enPrerendu, h } from '../util'

/** Seul moyen de contact du site (alias dédié, aussi cité dans les mentions légales), affiché en texte simple. */
export const CONTACT = 'proton.me.easel124@passinbox.com'
/** Adresse publique du site quand la page ne la porte pas (développement, tests, prérendu). */
export const SITE_DEFAUT = __URL_SITE__
/** Au-delà, la liste des fichiers est tronquée (référence de taille raisonnable). */
export const MAX_FICHIERS = 40

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

/** Liste des fichiers de données affichés, une ligne par fichier. */
export function texteFichiers(fichiers: FichierAffiche[]): string {
  if (!fichiers.length) return 'Aucun fichier de données lu par cette page.'
  const vus = fichiers.slice(0, MAX_FICHIERS).map(ligneFichier)
  if (fichiers.length > MAX_FICHIERS) vus.push(`- et ${fichiers.length - MAX_FICHIERS} autres fichiers`)
  return vus.join('\n')
}

/** Référence à copier dans le courriel : page et fichiers affichés (liste ajoutée dans le navigateur). */
export function texteReference(p: PageSignalee): string {
  const lignes = [`Page : ${adressePublique(p.adresse)}`, 'Fichiers de données affichés :']
  // HTML prérendu : référence courte sans liste de fichiers (poids des pages, docs/PERF.md) ; la liste est ajoutée
  // dans le navigateur par majSignaler.
  lignes.push(enPrerendu() || !p.fichiers ? '(liste ajoutée une fois la page chargée)' : texteFichiers(p.fichiers))
  return lignes.join('\n')
}

/** Bloc de fin de page : l'adresse de contact, la référence à copier et l'avertissement (aucune donnée personnelle).
 * Dans le navigateur, le champ est rempli par majSignaler (valeur seulement) : l'adresse de la page, ses paramètres et
 * la liste des fichiers restent hors du texte de la page ; le HTML prérendu porte la référence courte. */
export function blocSignaler(p: PageSignalee): string {
  return `<aside class="signaler" aria-label="Signaler une erreur"><p class="signaler-titre"><strong>Signaler une erreur sur cette page</strong></p><p class="aide">Écris à <span class="signaler-contact">${h(CONTACT)}</span> en indiquant l’adresse de cette page et les fichiers de données affichés : la référence ci-dessous est prête à copier. Le site n’envoie rien lui-même. N’ajoute aucune donnée personnelle inutile, ni ton salaire, ni ta saisie.</p><textarea class="signaler-reference" readonly rows="4" aria-label="Référence de la page à copier dans ton courriel">${enPrerendu() ? h(texteReference(p)) : ''}</textarea></aside>`
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

/** Met à jour la référence de la page affichée une fois tout chargé (le bloc est ajouté s'il manque). */
export async function majSignaler(cible: HTMLElement, p: PageSignalee): Promise<void> {
  if (enPrerendu()) return
  const fichiers = await fichiersAffiches()
  if (!cible.querySelector('.signaler-reference')) (cible.querySelector('.ecran') ?? cible).insertAdjacentHTML('beforeend', blocSignaler(p))
  // Valeur du champ seulement : adresse et fichiers restent hors du texte de la page (sigles, noms de fichiers).
  const ref = cible.querySelector<HTMLTextAreaElement>('.signaler-reference')
  if (ref) ref.value = texteReference({ ...p, fichiers })
}

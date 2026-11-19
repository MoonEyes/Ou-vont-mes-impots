// Composants de choix partagés (audit ergonomie des choix, 19/11/2026, docs/AUDIT_CHOIX.md).
// Un seul jeu pour tout le site ; tests/choix.test.ts échoue si un écran écrit un choix à la main.
//
// Quel composant pour quel choix (règle du nombre d'options) :
//   - 2 à 4 options courtes, effet dans la page  -> segmente()      (groupe radio ARIA de boutons, flèches clavier)
//   - 5 à 12 options, ou libellés longs          -> radioListe()    (boutons radio natifs, en liste ou en grille)
//   - plus de 12 options                         -> listeRecherche() (liste native précédée d'un champ qui la filtre)
//   - choix() applique cette règle seul, à partir des options.
//   - choix qui change d'adresse (année, vue)    -> choixLiens()    (liens, la page courante marquée aria-current)
//   - panneaux d'une même page                   -> listeOnglets()  (onglets ARIA, flèches, Début, Fin)
//   - réglage immédiat oui/non                   -> interrupteur()  (case native, rôle switch)
//   - option d'un formulaire                     -> caseACocher()
// L'état choisi se voit autrement que par la couleur : coche dessinée, graisse, trait épais sous l'onglet, position du
// curseur de l'interrupteur, pastille du bouton radio. Cibles de 44 px au moins (feuille de style, .choix-*).
// Aucun stockage : l'état vit dans la page (attributs ARIA, valeur des champs) et, pour les liens, dans l'adresse.
import { h } from '../util'

export interface OptionChoix {
  valeur: string
  libelle: string
  /** Groupe d'options (optgroup) : seulement pour listeRecherche. */
  groupe?: string
}

interface BaseChoix {
  /** Identifiant du groupe (segmenté, liste radio) ou de la liste native. */
  id: string
  etiquette: string
  options: OptionChoix[]
  valeur?: string
  /** Texte d'aide affiché sous l'étiquette, relié au choix. */
  aide?: string
  /** Identifiants d'éléments décrivant le choix (message d'erreur, note). */
  decritPar?: string
  /** Message d'erreur du champ (id « <id>-msg »), masqué tant qu'il est vide. */
  message?: boolean
  /** Étiquette lue mais non affichée (le titre voisin la dit déjà). */
  etiquetteCachee?: boolean
  classe?: string
}

/** Seuils de la règle (documentés dans docs/AUDIT_CHOIX.md). */
export const SEUIL_SEGMENTE = 4
export const SEUIL_LISTE = 12
/** Au-delà de ce nombre de caractères, un libellé ne tient pas dans un segment à 360 px : liste radio. */
export const LIBELLE_COURT = 26

const attrDecrit = (c: BaseChoix) => {
  const ids = [c.aide ? `${c.id}-aide` : '', c.decritPar ?? '', c.message ? `${c.id}-msg` : ''].filter(Boolean).join(' ')
  return ids ? ` aria-describedby="${h(ids)}"` : ''
}
const aide = (c: BaseChoix) =>
  (c.aide ? `<p class="aide" id="${h(c.id)}-aide">${h(c.aide)}</p>` : '') + (c.message ? `<p class="message-champ" id="${h(c.id)}-msg" hidden></p>` : '')
const classeEtiquette = (c: BaseChoix) => (c.etiquetteCachee ? 'choix-etiquette visuellement-cache' : 'choix-etiquette')

/** Segmenté : 2 à 4 options courtes. Boutons de rôle radio, un seul atteint par Tab, flèches pour changer. */
export function segmente(c: BaseChoix): string {
  const v = c.valeur ?? c.options[0]?.valeur
  return `<div class="choix-bloc${c.classe ? ` ${h(c.classe)}` : ''}"><p class="${classeEtiquette(c)}" id="${h(c.id)}-etiquette">${h(c.etiquette)}</p>${aide(c)}<div class="choix-segmente" role="radiogroup" id="${h(c.id)}" data-choix="segmente" aria-labelledby="${h(c.id)}-etiquette"${attrDecrit(c)}>${c.options
    .map(
      (o) =>
        `<button type="button" role="radio" class="choix-segment" value="${h(o.valeur)}" aria-checked="${o.valeur === v}" tabindex="${o.valeur === v ? 0 : -1}">${h(o.libelle)}</button>`,
    )
    .join('')}</div></div>`
}

/** Liste radio : 5 à 12 options, ou libellés longs. Boutons radio natifs (flèches du navigateur), dans un fieldset. */
export function radioListe(c: BaseChoix & { nom?: string; grille?: boolean }): string {
  const nom = c.nom ?? c.id
  const grille = c.grille ?? c.options.every((o) => o.libelle.length <= 14)
  return `<fieldset class="choix-liste${grille ? ' choix-liste-grille' : ''}${c.classe ? ` ${h(c.classe)}` : ''}" id="${h(c.id)}" data-choix="liste"${attrDecrit(c)}><legend class="${classeEtiquette(c)}">${h(c.etiquette)}</legend>${aide(c)}<div class="choix-options">${c.options
    .map((o) => `<label class="choix-option"><input type="radio" name="${h(nom)}" value="${h(o.valeur)}"${o.valeur === c.valeur ? ' checked' : ''} /><span>${h(o.libelle)}</span></label>`)
    .join('')}</div></fieldset>`
}

/** Options d'une liste native (groupes conservés, dans l'ordre d'apparition). */
export function optionsListe(options: OptionChoix[], valeur?: string): string {
  let html = ''
  let groupe: string | undefined
  for (const o of options) {
    if (o.groupe !== groupe) {
      if (groupe !== undefined) html += '</optgroup>'
      if (o.groupe !== undefined) html += `<optgroup label="${h(o.groupe)}">`
      groupe = o.groupe
    }
    html += `<option value="${h(o.valeur)}"${o.valeur === valeur ? ' selected' : ''}>${h(o.libelle)}</option>`
  }
  return groupe !== undefined ? html + '</optgroup>' : html
}

/**
 * Liste avec recherche : plus de 12 options. La liste native reste la source de la valeur (id inchangé, événement
 * change) ; le champ au-dessus ne garde que les options qui contiennent le texte tapé (sans accents ni majuscules).
 * Entrée choisit la première option gardée. Avec `recherche: false`, la liste native seule (liste remplie plus tard).
 */
export function listeRecherche(c: BaseChoix & { recherche?: boolean; desactivee?: boolean; nom?: string; optionsHtml?: string; attributs?: string }): string {
  const opts = c.optionsHtml ?? optionsListe(c.options, c.valeur)
  const recherche = c.recherche ?? (c.optionsHtml ? (opts.match(/<option[\s>]/g) ?? []).length : c.options.length) > SEUIL_LISTE
  return `<div class="choix-bloc choix-recherche${c.classe ? ` ${h(c.classe)}` : ''}" data-choix="recherche"><label class="${classeEtiquette(c)}" for="${h(c.id)}">${h(c.etiquette)}</label>${aide(c)}<div class="choix-recherche-ligne"${recherche ? '' : ' data-sans-filtre'}><label class="visuellement-cache" for="${h(c.id)}-filtre">Rechercher dans la liste : ${h(c.etiquette)}</label><input type="search" class="choix-filtre" id="${h(c.id)}-filtre" data-filtre-pour="${h(c.id)}" aria-controls="${h(c.id)}" aria-describedby="${h(c.id)}-compte" placeholder="Rechercher" autocomplete="off" spellcheck="false"${recherche ? '' : ' hidden'} /><select id="${h(c.id)}"${c.nom ? ` name="${h(c.nom)}"` : ''}${attrDecrit(c)}${c.desactivee ? ' disabled' : ''}${c.attributs ? ` ${c.attributs}` : ''}>${opts}</select></div><p class="choix-compte" id="${h(c.id)}-compte" role="status"></p></div>`
}

/** Applique la règle du nombre d'options. Les choix d'un formulaire ou d'une page passent tous par ici. */
export function choix(c: BaseChoix & { nom?: string; grille?: boolean }): string {
  const n = c.options.length
  if (n <= SEUIL_SEGMENTE && c.options.every((o) => o.libelle.length <= LIBELLE_COURT)) return segmente(c)
  if (n <= SEUIL_LISTE) return radioListe(c)
  return listeRecherche({ ...c, recherche: true })
}

/** Choix qui change d'adresse (année, vue, territoire) : liens, la page courante marquée aria-current="page".
 *  Libellés longs (plus de 26 caractères) : une colonne de lignes alignées à gauche, comme une liste radio. */
export function choixLiens(c: { etiquette: string; liens: { href: string; libelle: string; courant: boolean }[]; id?: string; classe?: string }): string {
  const courts = c.liens.every((l) => l.libelle.length <= LIBELLE_COURT)
  // Libellés courts : pastilles (segmenté jusqu'à 4, en grille au-delà) ; libellés longs : une colonne de lignes.
  const disposition = !courts ? ' choix-liens-colonne' : c.liens.length > SEUIL_SEGMENTE ? ' choix-liens-liste' : ''
  return `<div class="choix-liens${disposition}${c.classe ? ` ${h(c.classe)}` : ''}" role="group" aria-label="${h(c.etiquette)}"${c.id ? ` id="${h(c.id)}"` : ''} data-choix="liens">${c.liens
    .map((l) => `<a class="choix-lien" href="${h(l.href)}"${l.courant ? ' aria-current="page"' : ''}>${h(l.libelle)}</a>`)
    .join('')}</div>`
}

/** Liste d'onglets (motif « tabs » de l'APG ARIA) ; les panneaux portent role="tabpanel" et aria-labelledby. */
export function listeOnglets(c: { etiquette: string; onglets: { id: string; libelle: string; panneau: string }[]; actif?: string; classe?: string }): string {
  const actif = c.actif ?? c.onglets[0]?.id
  return `<div role="tablist" aria-label="${h(c.etiquette)}" class="choix-onglets${c.classe ? ` ${h(c.classe)}` : ''}" data-choix="onglets">${c.onglets
    .map(
      (o) =>
        `<button type="button" role="tab" class="choix-onglet" id="${h(o.id)}" aria-controls="${h(o.panneau)}" aria-selected="${o.id === actif}" tabindex="${o.id === actif ? 0 : -1}">${h(o.libelle)}</button>`,
    )
    .join('')}</div>`
}

/**
 * Option d'une liste détaillée (barre, montant et statut à côté) : bouton à état pressé, une seule pressée par étape.
 * Pour une suite d'étapes (Suivre un euro) où chaque option porte d'autres informations qu'un libellé.
 */
export function optionRiche(c: { html: string; choisi: boolean; classe?: string; attributs?: string }): string {
  return `<button type="button" class="choix-riche${c.classe ? ` ${h(c.classe)}` : ''}" aria-pressed="${c.choisi}"${c.attributs ? ` ${c.attributs}` : ''}>${c.html}</button>`
}

/** Interrupteur : réglage oui/non à effet immédiat (case native de rôle switch ; Espace bascule). */
export function interrupteur(c: { id: string; libelle: string; coche?: boolean; decritPar?: string; attributs?: string }): string {
  return `<label class="choix-interrupteur"><input type="checkbox" role="switch" id="${h(c.id)}"${c.coche ? ' checked' : ''}${c.decritPar ? ` aria-describedby="${h(c.decritPar)}"` : ''}${c.attributs ? ` ${c.attributs}` : ''} /><span class="choix-piste" aria-hidden="true"></span><span>${h(c.libelle)}</span></label>`
}

/** Case à cocher : option d'un formulaire, prise en compte à l'envoi. */
export function caseACocher(c: { id: string; libelle: string; coche?: boolean; attributs?: string }): string {
  return `<label class="case"><input type="checkbox" id="${h(c.id)}"${c.coche ? ' checked' : ''}${c.attributs ? ` ${c.attributs}` : ''} /> <span>${h(c.libelle)}</span></label>`
}

// ---------- Lecture et écriture de la valeur, quel que soit le composant ----------

// Types reconnus par le nom de balise : le prérendu (scripts/prerendre.mjs) n'a pas les classes HTML*Element.
const estListe = (e: Element | null | undefined): e is HTMLSelectElement => e?.tagName === 'SELECT'
const estChamp = (e: Element | null | undefined): e is HTMLInputElement => e?.tagName === 'INPUT'
const estGroupe = (e: Element | null | undefined): e is HTMLOptGroupElement => e?.tagName === 'OPTGROUP'
const estOption = (e: Element | null | undefined): e is HTMLOptionElement => e?.tagName === 'OPTION'

const echapper = (s: string) => (typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(s) : s.replace(/([^\w-])/g, '\\$1'))

/** Valeur choisie d'un choix (segmenté, liste radio, liste native) ; chaîne vide si rien n'est choisi. */
export function valeurChoix(racine: ParentNode, id: string): string {
  const e = racine.querySelector<HTMLElement>(`#${echapper(id)}`)
  if (!e) return ''
  if (estListe(e) || estChamp(e)) return e.value
  if (e.dataset.choix === 'segmente') return e.querySelector<HTMLButtonElement>('[role="radio"][aria-checked="true"]')?.value ?? ''
  return e.querySelector<HTMLInputElement>('input[type="radio"]:checked')?.value ?? ''
}

/** Fixe la valeur d'un choix sans déclencher d'événement (retour sur une page, état lu dans l'adresse). */
export function fixerChoix(racine: ParentNode, id: string, valeur: string): void {
  const e = racine.querySelector<HTMLElement>(`#${echapper(id)}`)
  if (!e) return
  if (estListe(e)) {
    reinitialiserFiltre(e)
    e.value = valeur
    return
  }
  if (e.dataset.choix === 'segmente') {
    for (const b of e.querySelectorAll<HTMLButtonElement>('[role="radio"]')) marquer(b, b.value === valeur)
    return
  }
  for (const i of e.querySelectorAll<HTMLInputElement>('input[type="radio"]')) i.checked = i.value === valeur
}

/** Remplace les options d'une liste native (communes d'un département) ; le champ de recherche est remis à zéro. */
export function remplirListe(liste: HTMLSelectElement, options: OptionChoix[] | string, valeur?: string): void {
  reinitialiserFiltre(liste)
  liste.innerHTML = typeof options === 'string' ? options : optionsListe(options, valeur)
  if (valeur !== undefined) liste.value = valeur
  const bloc = liste.closest<HTMLElement>('[data-choix="recherche"]')
  const filtre = bloc?.querySelector<HTMLInputElement>('.choix-filtre')
  const ligne = bloc?.querySelector<HTMLElement>('.choix-recherche-ligne')
  // Le champ de recherche n'apparaît qu'au-delà de 12 options : un département de 8 communes n'en a pas besoin.
  if (filtre && ligne && !ligne.hasAttribute('data-sans-filtre-fixe')) {
    const avec = liste.options.length > SEUIL_LISTE
    filtre.hidden = !avec
    ligne.toggleAttribute('data-sans-filtre', !avec)
  }
}

function marquer(b: HTMLElement, actif: boolean) {
  b.setAttribute(b.getAttribute('role') === 'tab' ? 'aria-selected' : 'aria-checked', String(actif))
  b.tabIndex = actif ? 0 : -1
}

// ---------- Filtre des listes longues ----------

const reserve = new WeakMap<HTMLSelectElement, HTMLElement[]>()
export const normaliser = (s: string) =>
  s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[’'-]/g, ' ')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()

function reinitialiserFiltre(liste: HTMLSelectElement) {
  const tout = reserve.get(liste)
  if (tout) {
    for (const g of tout) {
      const orig = (g as HTMLOptGroupElement & { _options?: HTMLOptionElement[] })._options
      if (orig) g.replaceChildren(...orig)
    }
    liste.replaceChildren(...tout)
    reserve.delete(liste)
  }
  const bloc = liste.closest('[data-choix="recherche"]')
  const filtre = bloc?.querySelector<HTMLInputElement>('.choix-filtre')
  if (filtre) filtre.value = ''
  const compte = bloc?.querySelector<HTMLElement>('.choix-compte')
  if (compte) compte.textContent = ''
}

/** Garde les options qui contiennent le texte (la valeur vide « Choisir » et l'option choisie restent). */
export function filtrerListe(liste: HTMLSelectElement, texte: string): number {
  if (!reserve.has(liste)) reserve.set(liste, [...liste.children] as HTMLElement[])
  const tout = reserve.get(liste)!
  const q = normaliser(texte)
  const choisie = liste.value
  const garde = (o: HTMLOptionElement) => !q || o.value === '' || o.value === choisie || normaliser(o.textContent ?? '').includes(q)
  let n = 0
  const enfants: HTMLElement[] = []
  for (const e of tout) {
    if (estGroupe(e)) {
      // Groupe reconstruit à partir des options d'origine (gardées dans la réserve).
      const orig = (e as HTMLOptGroupElement & { _options?: HTMLOptionElement[] })._options ?? [...e.querySelectorAll('option')]
      ;(e as HTMLOptGroupElement & { _options?: HTMLOptionElement[] })._options = orig
      const gardees = orig.filter(garde)
      e.replaceChildren(...gardees)
      n += gardees.filter((o) => o.value !== '').length
      if (gardees.length) enfants.push(e)
    } else if (estOption(e) && garde(e)) {
      enfants.push(e)
      if (e.value !== '') n++
    }
  }
  liste.replaceChildren(...enfants)
  liste.value = choisie
  return n
}

const compteTexte = (n: number, total: number) => (n === 0 ? 'Aucune proposition ne contient ce texte.' : n === total ? '' : `${n} proposition${n > 1 ? 's' : ''} sur ${total}.`)

// ---------- Comportements, branchés une fois sur le document ----------

function groupeDe(b: HTMLElement): HTMLElement[] {
  const g = b.closest('[data-choix="segmente"], [data-choix="onglets"]')
  if (!g) return []
  return [...g.querySelectorAll<HTMLElement>(':scope > [role="radio"], :scope > [role="tab"]')].filter((x) => !(x as HTMLButtonElement).disabled)
}

/** Choisit un segment ou un onglet : état ARIA, tabulation, panneaux ; événement change si la valeur change. */
export function choisir(b: HTMLElement): void {
  const items = groupeDe(b)
  const role = b.getAttribute('role')
  const avant = items.find((x) => x.getAttribute(role === 'tab' ? 'aria-selected' : 'aria-checked') === 'true')
  for (const x of items) {
    marquer(x, x === b)
    if (role === 'tab') {
      const p = document.getElementById(x.getAttribute('aria-controls') ?? '')
      if (p) p.hidden = x !== b
    }
  }
  // Mêmes événements qu'un bouton radio natif : input puis change, seulement si la valeur change.
  if (avant !== b) {
    b.dispatchEvent(new Event('input', { bubbles: true }))
    b.dispatchEvent(new Event('change', { bubbles: true }))
  }
}

function clic(e: Event) {
  const b = (e.target as HTMLElement | null)?.closest?.<HTMLElement>('[data-choix="segmente"] > [role="radio"], [data-choix="onglets"] > [role="tab"]')
  if (b && !(b as HTMLButtonElement).disabled) choisir(b)
}

function touche(e: KeyboardEvent) {
  const cible = e.target as HTMLElement
  // Segmentés et onglets : flèches (gauche/haut, droite/bas), Début, Fin ; la sélection suit le focus.
  const b = cible.closest?.<HTMLElement>('[data-choix="segmente"] > [role="radio"], [data-choix="onglets"] > [role="tab"]')
  if (b) {
    const items = groupeDe(b)
    const i = items.indexOf(b)
    const k = e.key
    const j =
      k === 'ArrowRight' || k === 'ArrowDown' ? (i + 1) % items.length : k === 'ArrowLeft' || k === 'ArrowUp' ? (i - 1 + items.length) % items.length : k === 'Home' ? 0 : k === 'End' ? items.length - 1 : -1
    if (j < 0) return
    e.preventDefault()
    items[j].focus()
    items[j].click()
    return
  }
  // Champ de recherche d'une liste longue : Entrée choisit la première option gardée, Échap vide le champ.
  if (estChamp(cible) && cible.dataset.filtrePour) {
    const liste = document.getElementById(cible.dataset.filtrePour) as HTMLSelectElement | null
    if (!liste) return
    if (e.key === 'Enter') {
      e.preventDefault()
      const premiere = [...liste.options].find((o) => o.value !== '')
      if (premiere && liste.value !== premiere.value) {
        liste.value = premiere.value
        liste.dispatchEvent(new Event('change', { bubbles: true }))
      }
      liste.focus()
    } else if (e.key === 'Escape' && cible.value) {
      e.preventDefault()
      cible.value = ''
      cible.dispatchEvent(new Event('input', { bubbles: true }))
    }
    return
  }
  // Champ avec propositions (liens) : flèche bas vers la première proposition, flèches entre elles, Échap revient.
  const champ = cible.closest?.<HTMLInputElement>('[data-propositions]')
  if (champ && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    const liens = [...(document.getElementById(champ.dataset.propositions ?? '')?.querySelectorAll<HTMLElement>('a, button') ?? [])]
    if (!liens.length) return
    e.preventDefault()
    liens[e.key === 'ArrowDown' ? 0 : liens.length - 1].focus()
    return
  }
  const liste = cible.closest?.<HTMLElement>('[data-propositions-de]')
  if (liste && (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Escape')) {
    const champ2 = document.getElementById(liste.dataset.propositionsDe ?? '') as HTMLInputElement | null
    const liens = [...liste.querySelectorAll<HTMLElement>('a, button')]
    const i = liens.indexOf(cible)
    e.preventDefault()
    if (e.key === 'Escape') return champ2?.focus()
    const j = e.key === 'ArrowDown' ? i + 1 : i - 1
    if (j < 0 || j >= liens.length) champ2?.focus()
    else liens[j].focus()
  }
}

function saisie(e: Event) {
  const cible = e.target as HTMLElement
  if (!estChamp(cible) || !cible.dataset.filtrePour) return
  const liste = document.getElementById(cible.dataset.filtrePour) as HTMLSelectElement | null
  if (!liste) return
  const n = filtrerListe(liste, cible.value)
  const total = (reserve.get(liste) ?? []).reduce((s, x) => s + (estGroupe(x) ? ((x as HTMLOptGroupElement & { _options?: HTMLOptionElement[] })._options ?? []).length : (x as HTMLOptionElement).value ? 1 : 0), 0)
  const compte = document.getElementById(`${liste.id}-compte`)
  if (compte) compte.textContent = cible.value.trim() ? compteTexte(n, total) : ''
}

let branche: Document | null = null
/** Branche les comportements sur le document (une fois ; appelé à l'import du module). */
export function brancherChoix(doc: Document = document): void {
  if (branche === doc) return
  branche = doc
  doc.addEventListener('click', clic, true)
  doc.addEventListener('keydown', touche)
  doc.addEventListener('input', saisie)
}
if (typeof document !== 'undefined') brancherChoix(document)

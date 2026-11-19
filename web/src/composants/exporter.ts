// Export et citation des tableaux de données, en amélioration progressive.
// Après le rendu d'un écran, chaque <table> du contenu principal reçoit deux actions discrètes :
// « Télécharger (CSV) » (fichier fabriqué dans le navigateur, pour Excel en français : séparateur point-virgule,
// virgule décimale, UTF-8 avec BOM) et « Citer » (texte de citation copié dans le presse-papiers, annoncé).
// Aucune bibliothèque, aucune requête : tout est lu dans le tableau affiché et dans la page.
// Rien n'est ajouté au prérendu (pages statiques) : sans JavaScript, des boutons ne feraient rien.
import { annoncer, h } from '../util'

/** Nom du site (le même que NOM_SITE du routeur, recopié pour ne pas créer d'import circulaire). */
const NOM_SITE_EXPORT = 'Le billet découpé'

const SEP = ';'
const ESPACES = /[\s   ]+/g
/** Valeurs absentes ou non publiées : gardées telles quelles, jamais changées en 0. */
const MANQUANTES = /^(|nc|n\.?\s?c\.?|n\.?\s?d\.?|s\.?\s?o\.?|\u2014|\u2013|-|non (publiée?s?|disponibles?|chiffrée?s?|connue?s?)|secret statistique)$/i
/** Nombre au format français, avec une unité courte éventuelle : « 1 234,5 Md€ », « −3,2 % », « 2024 ». */
const NOMBRE = /^([+\-−]?)(\d+(?:,\d+)?)(?:\s*([^\d\s][^\d]{0,19}))?$/

const texteVisible = (el: Element): string => {
  const copie = el.cloneNode(true) as Element
  copie.querySelectorAll('[aria-hidden="true"], .exporter, script, style').forEach((x) => x.remove())
  return (copie.textContent ?? '').replace(ESPACES, ' ').trim()
}

interface Nombre {
  valeur: string
  unite: string
}
/** Lit un nombre français ; null si la cellule n'est pas un nombre seul. */
export function lireNombre(texte: string): Nombre | null {
  const t = texte.trim().replace(/(\d)[\s   ]+(?=\d)/g, '$1')
  const m = NOMBRE.exec(t)
  if (!m) return null
  return { valeur: `${/[-−]/.test(m[1]) ? '-' : ''}${m[2]}`.replace(/^-(0(,0+)?)$/, '$1'), unite: (m[3] ?? '').trim() }
}

/** Champ CSV : guillemets si besoin, et neutralisation des débuts de formule dans un tableur. */
function champ(x: string): string {
  let v = x
  if (/^[=+\-@\t\r]/.test(v) && !/^[+\-−]?\d/.test(v)) v = `'${v}`
  return /[";\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v
}

function lignes(table: HTMLTableElement): { tete: string[][]; corps: string[][] } {
  const tete: string[][] = []
  const corps: string[][] = []
  for (const tr of Array.from(table.rows)) {
    const cellules: string[] = []
    for (const c of Array.from(tr.cells)) {
      cellules.push(texteVisible(c))
      for (let i = 1; i < (c.colSpan || 1); i++) cellules.push('')
    }
    if (tr.parentElement?.tagName === 'THEAD') tete.push(cellules)
    else corps.push(cellules)
  }
  // Tableau sans thead dont la première ligne n'a que des en-têtes de colonne.
  if (!tete.length && table.rows.length && Array.from(table.rows[0].cells).every((c) => c.tagName === 'TH')) tete.push(corps.shift()!)
  return { tete, corps }
}

/**
 * Contenu CSV d'un tableau (sans BOM). Une colonne dont toutes les valeurs sont des nombres de même unité
 * est écrite en nombres purs (virgule décimale) et son unité passe dans l'en-tête ; sinon le texte affiché est gardé.
 */
export function tableauVersCsv(table: HTMLTableElement): string {
  const { tete, corps } = lignes(table)
  const largeur = Math.max(0, ...tete.map((l) => l.length), ...corps.map((l) => l.length))
  for (let j = 0; j < largeur; j++) {
    const lus = corps.map((l) => (MANQUANTES.test(l[j] ?? '') ? undefined : lireNombre(l[j] ?? '')))
    const nombres = lus.filter((n): n is Nombre => !!n)
    if (!nombres.length || lus.some((n) => n === null)) continue
    const unite = nombres[0].unite
    if (nombres.some((n) => n.unite !== unite)) continue
    corps.forEach((l, i) => {
      const n = lus[i]
      if (n) l[j] = n.valeur
    })
    const derniere = tete[tete.length - 1]
    if (unite && derniere && derniere[j] !== undefined && !derniere[j].includes(`(${unite})`)) derniere[j] = `${derniere[j]} (${unite})`
  }
  return [...tete, ...corps].map((l) => l.map(champ).join(SEP)).join('\r\n') + '\r\n'
}

/** Nom de fichier lisible, sans accent ni espace. */
export function nomFichier(titre: string, millesime?: string | null): string {
  const slug = (s: string) =>
    s
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/[’']/g, '-')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
  let base = slug(titre).slice(0, 70).replace(/-+$/, '') || 'tableau'
  if (millesime && !base.includes(slug(millesime))) base += `-${slug(millesime)}`
  return `ou-vont-mes-impots_${base}.csv`
}

/** Bloc (enveloppe défilante ou tableau) après lequel les actions sont posées. */
const bloc = (table: HTMLTableElement): Element => {
  const p = table.parentElement
  return p && p.classList.contains('tableau-defile') ? p : table
}

/** Titre du tableau : sa légende, sinon le titre de section qui le précède, sinon le titre de la page. */
export function titreTableau(table: HTMLTableElement): string {
  const legende = table.caption ? texteVisible(table.caption) : ''
  if (legende) return legende
  let el: Element | null = bloc(table)
  while (el) {
    let s: Element | null = el.previousElementSibling
    while (s) {
      if (/^H[2-6]$/.test(s.tagName)) return texteVisible(s)
      s = s.previousElementSibling
    }
    el = el.parentElement
    if (!el || el.classList.contains('ecran') || el.tagName === 'MAIN') break
  }
  return titrePage(table)
}

function titrePage(table: Element): string {
  const ecran = table.closest('.ecran') ?? table.closest('main') ?? document
  const t = ecran.querySelector('h1')
  return t ? texteVisible(t) : document.title
}

/** Mention de source la plus proche après le tableau (dans son bloc, puis en remontant), sinon null. */
export function sourceTableau(table: HTMLTableElement): string | null {
  let el: Element | null = bloc(table)
  while (el && !el.classList.contains('ecran') && el.tagName !== 'MAIN') {
    let s: Element | null = el.nextElementSibling
    while (s) {
      if (s.matches('.source')) return texteVisible(s)
      const dedans = s.querySelector('.source')
      if (dedans && !s.querySelector('table')) return texteVisible(dedans)
      if (/^H[1-3]$/.test(s.tagName) || s.querySelector('table')) break
      s = s.nextElementSibling
    }
    el = el.parentElement
  }
  return null
}

/** Millésime des données : année entre parenthèses de la source, sinon année de la légende. */
export function millesimeTableau(titre: string, source: string | null): string | null {
  const entre = source ? /\(([^()]*\b(?:19|20)\d{2}\b[^()]*)\)\s*$/.exec(source) : null
  if (entre) return entre[1].trim()
  const annees = titre.match(/\b(?:19|20)\d{2}\b/g)
  if (annees) return annees.length > 1 ? `${annees[0]} à ${annees[annees.length - 1]}` : annees[0]
  return null
}

const dateLongue = (d: Date) => new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }).format(d)

/** Adresse de la page à citer : l'adresse affichée (paramètres compris, ils choisissent l'année ou la commune). */
const adressePage = () => (typeof location !== 'undefined' ? location.href : '')

/** Texte de citation d'un tableau, prêt à coller. */
export function texteCitation(table: HTMLTableElement, consultation: Date = new Date(), url = adressePage()): string {
  const titre = titreTableau(table)
  const page = titrePage(table)
  const source = sourceTableau(table)
  const millesime = millesimeTableau(titre, source)
  const morceaux = [`« ${titre} »${page && page !== titre ? `, page « ${page} »` : ''}, ${NOM_SITE_EXPORT} (site citoyen non officiel).`]
  morceaux.push(
    source
      ? `Données : ${source.replace(/\.$/, '')}${millesime && !source.includes(millesime) ? `, millésime ${millesime}` : ''}.`
      : `Données : sources indiquées sur la page Méthode et sources du site${millesime ? `, millésime ${millesime}` : ''}.`,
  )
  if (url) morceaux.push(`${url}.`)
  morceaux.push(`Consulté le ${dateLongue(consultation)}.`)
  return morceaux.join(' ')
}

function telecharger(table: HTMLTableElement) {
  const titre = titreTableau(table)
  const nom = nomFichier(titre, millesimeTableau(titre, sourceTableau(table)))
  const blob = new Blob(['﻿', tableauVersCsv(table)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = nom
  a.hidden = true
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  annoncer(`Fichier ${nom} téléchargé.`)
}

async function copier(texte: string, repli: HTMLElement): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(texte)
      return true
    }
  } catch {
    /* presse-papiers refusé : sélection du texte à la place */
  }
  try {
    const sel = window.getSelection?.()
    const plage = document.createRange()
    plage.selectNodeContents(repli)
    sel?.removeAllRanges()
    sel?.addRange(plage)
    return typeof document.execCommand === 'function' && document.execCommand('copy')
  } catch {
    return false
  }
}

let compteur = 0

function actions(table: HTMLTableElement): HTMLElement {
  const n = ++compteur
  const titre = titreTableau(table)
  const div = document.createElement('div')
  div.className = 'exporter'
  // Espace final : le texte du bloc ne se colle pas à celui qui suit (lecture du texte de la page, copie).
  div.innerHTML = `<div class="exporter-boutons"><button type="button" class="bouton-lien" data-action="csv">Télécharger (CSV)<span class="visuellement-cache"> : ${h(titre)}</span></button><button type="button" class="bouton-lien" data-action="citer" aria-expanded="false" aria-controls="citation-${n}">Citer<span class="visuellement-cache"> : ${h(titre)}</span></button></div><div class="exporter-citation" id="citation-${n}" hidden><p class="exporter-texte"></p><p class="aide" role="status"></p></div> `
  const panneau = div.querySelector<HTMLElement>('.exporter-citation')!
  const texte = div.querySelector<HTMLElement>('.exporter-texte')!
  const etat = div.querySelector<HTMLElement>('[role="status"]')!
  const citer = div.querySelector<HTMLButtonElement>('[data-action="citer"]')!
  div.querySelector('[data-action="csv"]')!.addEventListener('click', () => telecharger(table))
  citer.addEventListener('click', async () => {
    if (!panneau.hidden) {
      panneau.hidden = true
      citer.setAttribute('aria-expanded', 'false')
      return
    }
    texte.textContent = texteCitation(table)
    etat.textContent = ''
    panneau.hidden = false
    citer.setAttribute('aria-expanded', 'true')
    const ok = await copier(texte.textContent, texte)
    const message = ok ? 'Citation copiée dans le presse-papiers.' : 'Copie automatique impossible : sélectionne le texte ci-dessus pour le copier.'
    etat.textContent = message
    annoncer(message)
  })
  return div
}

const EXCLUS = 'table[role="presentation"], table[role="none"], table.sans-export, .exporter table'

/** Ajoute les actions à chaque tableau de données de racine qui ne les a pas encore. */
export function enrichirTableaux(racine: ParentNode) {
  if (import.meta.env?.SSR) return
  racine.querySelectorAll<HTMLTableElement>('table:not([data-exporte])').forEach((table) => {
    if (table.matches(EXCLUS) || !table.rows.length) return
    table.setAttribute('data-exporte', '')
    bloc(table).insertAdjacentElement('afterend', actions(table))
  })
}

const observes = new WeakSet<Node>()

/** Crochet du routeur : enrichit le contenu affiché, puis les tableaux ajoutés plus tard (suite, onglets, pages). */
export function brancherExports(cible: HTMLElement) {
  if (import.meta.env?.SSR) return
  enrichirTableaux(cible)
  if (observes.has(cible) || typeof MutationObserver === 'undefined') return
  observes.add(cible)
  let prevu = false
  new MutationObserver(() => {
    if (prevu) return
    prevu = true
    queueMicrotask(() => {
      prevu = false
      enrichirTableaux(cible)
    })
  }).observe(cible, { childList: true, subtree: true })
}

// Séries longues (/explorer/series) : les grandes masses depuis 2005, en euros courants, en euros constants ou en part
// du PIB. Les montants sont lus dans les fichiers déjà publiés (recettes.json, administrations.json, dette/) ; l'indice
// des prix, le PIB et les dépenses par fonction viennent de site/data/series/ (pipeline/series.py).
// Chaque graphique a sa phrase de lecture et son tableau ; les valeurs provisoires sont en pointillé, les ruptures
// de série écrites sous le graphique concerné.
import { chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { annoncer, h, md, pct, rendreDefilables, source } from '../util'

type Serie = Record<string, number | null | undefined>
export type Mode = 'courants' | 'constants' | 'pib'

interface Rupture {
  serie: string
  annee: string | null
  type: string
  lecture: string
}
export interface Index {
  millesime: string
  source: string
  avertissement: string
  annee_debut: string
  annee_reference: string
  prix: { indice: Record<string, number>; coefficient: Record<string, number>; methode: string; source: { titre: string; maj: string } }
  pib: { md: Record<string, number>; methode: string; definition: string; source: { titre: string; maj: string } }
  ruptures: Rupture[]
}
interface Fonctions {
  source: string
  definition: string
  avertissement: string
  annees: string[]
  fonctions: { code: string; nom: string; md: Serie; provisoire: string[] }[]
  ecarts: { annee: string; ecart_md: number; total_cofog_md: number; depenses_totales_md: number }[]
}
interface Recettes {
  source: string
  millesime: string
  impots: Record<string, { nom: string; par_administration: Record<string, Serie> }>
}
interface Administrations {
  source: string
  millesime: string
  annees: Record<string, Record<string, Record<string, number>>>
}
interface Encours {
  source: string
  definition: string
  insee: Record<string, { libelle: string; md: Serie }>
}
interface Interets {
  avertissement: string
  nationale: { eurostat: { source: { titre: string }; secteurs: Record<string, { libelle: string; md: Serie }> } }
}

interface Ligne {
  nom: string
  md: Serie
  provisoire: string[]
}
interface Bloc {
  id: string
  titre: string
  intro: string
  principal?: Ligne
  composantes: Ligne[]
  titreComposantes?: string
  notes: string[]
  source: string
  liens: [string, string][]
}

const MODES: { id: Mode; libelle: string }[] = [
  { id: 'courants', libelle: 'Euros courants' },
  { id: 'constants', libelle: 'Euros constants' },
  { id: 'pib', libelle: 'Part du PIB' },
]

// Grands impôts suivis (codes de la comptabilité nationale, libellés de l'écran Recettes).
const IMPOTS: [string, string][] = [
  ['D211', 'TVA'],
  ['D51A_C1', 'Impôt sur le revenu des ménages (y compris CSG)'],
  ['D61', 'Cotisations sociales'],
  ['D51B', 'Impôt sur les sociétés'],
  ['D214A', 'Droits d’accise (carburants, tabac, alcool...)'],
  ['D29', 'Autres impôts sur la production'],
]
const ADMINS: [string, string][] = [
  ['Etat', 'État et organismes nationaux'],
  ['Securite sociale', 'Sécurité sociale'],
  ['Collectivites locales', 'Collectivités locales'],
]

/** Conversion d'un montant (milliards d'euros courants) dans le mode choisi ; null si l'indice ou le PIB manque. */
export function convertir(v: number | null | undefined, annee: string, mode: Mode, idx: Pick<Index, 'prix' | 'pib'>): number | null {
  if (v === null || v === undefined || !Number.isFinite(v)) return null
  if (mode === 'courants') return v
  if (mode === 'constants') {
    const c = idx.prix.coefficient[annee]
    return c === undefined ? null : v * c
  }
  const p = idx.pib.md[annee]
  return p ? (v / p) * 100 : null
}

export const uniteMode = (mode: Mode, ref: string) =>
  mode === 'courants' ? 'milliards d’euros courants' : mode === 'constants' ? `milliards d’euros de ${ref}` : 'part du PIB, en %'

const formater = (x: number, mode: Mode) => (mode === 'pib' ? pct(x, 1) : md(x))

/** Phrase de lecture factuelle : première et dernière valeur publiées, sans qualificatif. */
export function phraseLecture(nom: string, valeurs: [string, number | null][], mode: Mode, ref: string): string {
  const pleines = valeurs.filter((x): x is [string, number] => x[1] !== null)
  if (pleines.length < 2) return `${nom} : pas assez de valeurs publiées pour décrire une évolution.`
  const [a0, v0] = pleines[0]
  const [a1, v1] = pleines[pleines.length - 1]
  const suffixe = mode === 'pib' ? ' du PIB' : mode === 'constants' ? ` (en euros de ${ref})` : ' (en euros courants)'
  const verbe = v1 === v0 ? 'reste à' : 'passe de'
  const fin = v1 === v0 ? `${formater(v0, mode)}` : `${formater(v0, mode)} en ${a0} à ${formater(v1, mode)} en ${a1}`
  return `${nom} : ${verbe} ${fin}${suffixe}.`
}

// ---------------------------------------------------------------------------------------------------------------
// Courbe SVG (sans style en ligne : classes CSS seulement)
// ---------------------------------------------------------------------------------------------------------------

interface Echelle {
  min: number
  max: number
}
let compteur = 0

export function courbe(nom: string, valeurs: [string, number | null][], provisoire: string[], echelle: Echelle, mode: Mode, grand: boolean, idLecture: string): string {
  const W = grand ? 640 : 320
  const H = grand ? 240 : 150
  const g = grand ? 76 : 64 // marge gauche (étiquettes)
  const d = 14
  const hh = 14
  const b = 26
  const n = valeurs.length
  const x = (i: number) => g + (n <= 1 ? 0 : (i * (W - g - d)) / (n - 1))
  const etendue = echelle.max - echelle.min || 1
  const y = (v: number) => hh + (1 - (v - echelle.min) / etendue) * (H - hh - b)
  const traits: string[] = []
  for (let i = 1; i < n; i++) {
    const [, v0] = valeurs[i - 1]
    const [a1, v1] = valeurs[i]
    if (v0 === null || v1 === null) continue
    const classe = provisoire.includes(a1) ? 'sl-trait sl-provisoire' : 'sl-trait'
    traits.push(`<path class="${classe}" d="M${x(i - 1).toFixed(1)} ${y(v0).toFixed(1)}L${x(i).toFixed(1)} ${y(v1).toFixed(1)}"/>`)
  }
  const points = valeurs
    .map(([, v], i) => (v === null ? '' : `<circle class="sl-point" cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="${grand ? 2.6 : 2.2}"/>`))
    .join('')
  const reperes = [echelle.min, echelle.max, ...(echelle.min < 0 && echelle.max > 0 ? [0] : [])]
  const grille = reperes
    .map(
      (v) =>
        `<line class="${v === 0 ? 'sl-zero' : 'sl-grille'}" x1="${g}" x2="${W - d}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/>` +
        `<text class="sl-etiquette" x="${g - 6}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${h(etiquetteAxe(v, mode))}</text>`,
    )
    .join('')
  const annees = n
    ? `<text class="sl-etiquette" x="${g}" y="${H - 6}" text-anchor="start">${h(valeurs[0][0])}</text><text class="sl-etiquette" x="${W - d}" y="${H - 6}" text-anchor="end">${h(valeurs[n - 1][0])}</text>`
    : ''
  compteur += 1
  return `<svg class="sl-courbe${grand ? ' sl-grand' : ''}" viewBox="0 0 ${W} ${H}" role="img" aria-labelledby="sl-t${compteur} ${idLecture}"><title id="sl-t${compteur}">Courbe : ${h(nom)}</title>${grille}${traits.join('')}${points}${annees}</svg>`
}

function etiquetteAxe(v: number, mode: Mode): string {
  if (mode === 'pib') return pct(v, Math.abs(v) < 10 ? 1 : 0)
  const a = Math.abs(v)
  return `${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: a < 10 ? 1 : 0 }).format(v)} Md€`
}

/** Échelle commune à plusieurs courbes : du minimum (ou 0) au maximum, arrondis. */
export function echelleCommune(series: (number | null)[][]): Echelle {
  const toutes = series.flat().filter((v): v is number => v !== null)
  if (!toutes.length) return { min: 0, max: 1 }
  const max = Math.max(0, ...toutes)
  const min = Math.min(0, ...toutes)
  const arrondi = (v: number) => {
    const a = Math.abs(v)
    if (a === 0) return 0
    const pas = 10 ** Math.floor(Math.log10(a)) / 2
    return (v > 0 ? Math.ceil(v / pas) : Math.floor(v / pas)) * pas
  }
  return { min: arrondi(min), max: arrondi(max) || 1 }
}

// ---------------------------------------------------------------------------------------------------------------
// Rendu
// ---------------------------------------------------------------------------------------------------------------

function blocHtml(bloc: Bloc, annees: string[], mode: Mode, idx: Index): string {
  const ref = idx.annee_reference
  const conv = (l: Ligne): [string, number | null][] => annees.map((a) => [a, convertir(l.md[a], a, mode, idx)])
  const unite = uniteMode(mode, ref)
  let corps = ''
  if (bloc.principal) {
    const v = conv(bloc.principal)
    const idL = `sl-l-${bloc.id}-p`
    corps += `<figure class="sl-figure carte"><figcaption><strong>${h(bloc.principal.nom)}</strong> <span class="aide">${h(unite)}</span></figcaption>${courbe(
      bloc.principal.nom,
      v,
      bloc.principal.provisoire,
      echelleCommune([v.map((x) => x[1])]),
      mode,
      true,
      idL,
    )}<p class="sl-lecture" id="${idL}">${h(phraseLecture(bloc.principal.nom, v, mode, ref))}</p></figure>`
  }
  if (bloc.composantes.length) {
    const vals = bloc.composantes.map(conv)
    const ech = echelleCommune(vals.map((v) => v.map((x) => x[1])))
    corps += `${bloc.titreComposantes ? `<h3>${h(bloc.titreComposantes)}</h3>` : ''}<p class="aide">Petites courbes à la même échelle (${h(unite)}), pour comparer d’une courbe à l’autre.</p><ul class="sl-multiples">${bloc.composantes
      .map((l, i) => {
        const idL = `sl-l-${bloc.id}-${i}`
        return `<li class="carte"><p class="sl-nom">${h(l.nom)}</p>${courbe(l.nom, vals[i], l.provisoire, ech, mode, false, idL)}<p class="sl-lecture" id="${idL}">${h(phraseLecture(l.nom, vals[i], mode, ref))}</p></li>`
      })
      .join('')}</ul>`
  }
  const lignes = [...(bloc.principal ? [bloc.principal] : []), ...bloc.composantes]
  const aEtoile = lignes.some((l) => l.provisoire.length > 0)
  const tableau = `<details class="sl-details"><summary>Tableau des valeurs : ${h(bloc.titre.toLowerCase())}</summary><div class="tableau-defile"><table>
<caption>${h(bloc.titre)}, ${h(unite)}, de ${h(annees[0])} à ${h(annees[annees.length - 1])}</caption>
<thead><tr><th scope="col">Année</th>${lignes.map((l) => `<th scope="col" class="nombre">${h(l.nom)}</th>`).join('')}</tr></thead>
<tbody>${[...annees]
    .reverse()
    .map(
      (a) =>
        `<tr><th scope="row">${h(a)}</th>${lignes
          .map((l) => {
            const v = convertir(l.md[a], a, mode, idx)
            return `<td class="nombre">${v === null ? 'non publié' : h(formater(v, mode)) + (l.provisoire.includes(a) ? ' *' : '')}</td>`
          })
          .join('')}</tr>`,
    )
    .join('')}</tbody></table></div>${aEtoile ? '<p class="aide">* valeur provisoire, révisable par le producteur (trait en pointillé sur la courbe).</p>' : ''}</details>`
  const notes = bloc.notes.length ? `<ul class="sl-notes" aria-label="Précautions de lecture : ${h(bloc.titre.toLowerCase())}">${bloc.notes.map((n) => `<li>${h(n)}</li>`).join('')}</ul>` : ''
  const liens = bloc.liens.length ? `<p class="liens-sortie">${bloc.liens.map(([href, t]) => `<a href="${h(href)}">${h(t)}</a>`).join(' ')}</p>` : ''
  return `<section class="sl-bloc" aria-labelledby="sl-h-${bloc.id}"><h2 id="sl-h-${bloc.id}">${h(bloc.titre)}</h2><p>${h(bloc.intro)}</p>${corps}${tableau}${notes}${source(bloc.source)}${liens}</section>`
}

function ruptures(idx: Index, serie: string): string[] {
  return idx.ruptures.filter((r) => r.serie === serie).map((r) => r.lecture)
}

export function construireBlocs(
  idx: Index,
  r: Recettes | null,
  ad: Administrations | null,
  fct: Fonctions | null,
  enc: Encours | null,
  itr: Interets | null,
): Bloc[] {
  const derniereComptes = idx.ruptures.find((x) => x.serie === 'comptes')?.annee
  const provComptes = derniereComptes ? [derniereComptes] : []
  const parAdmin = (admin: string, cle: string): Serie => Object.fromEntries(Object.entries(ad?.annees ?? {}).map(([a, v]) => [a, v[admin]?.[cle] ?? null]))
  const blocs: Bloc[] = []
  if (ad || r) {
    blocs.push({
      id: 'recettes',
      titre: 'Les recettes et les grands impôts',
      intro: 'Ce que les administrations publiques encaissent chaque année, puis les principaux impôts et cotisations, toutes administrations réunies.',
      principal: ad ? { nom: 'Recettes de l’ensemble des administrations publiques', md: parAdmin('Ensemble', 'TR'), provisoire: provComptes } : undefined,
      composantes: r
        ? IMPOTS.filter(([c]) => r.impots[c]).map(([c, nom]) => ({ nom, md: r.impots[c].par_administration.Ensemble ?? {}, provisoire: provComptes }))
        : [],
      titreComposantes: 'Les grands impôts et cotisations',
      notes: [
        'Les recettes comprennent aussi d’autres impôts et des recettes qui ne sont pas des impôts (ventes, revenus du patrimoine) : les impôts montrés ici ne s’additionnent pas pour faire le total.',
        'Impôt sur le revenu des ménages : la comptabilité nationale y range la CSG et la CRDS.',
      ],
      source: [ad?.source, r ? `${r.source} (${r.millesime})` : ''].filter(Boolean).join(' ; '),
      liens: [[lien('/explorer/recettes'), 'Chaque impôt et l’administration qui l’encaisse']],
    })
  }
  if (ad) {
    blocs.push({
      id: 'administrations',
      titre: 'Les dépenses par administration',
      intro: 'Dépenses de l’ensemble des administrations publiques, puis de chacune : État et organismes nationaux, Sécurité sociale, collectivités locales.',
      principal: { nom: 'Dépenses de l’ensemble des administrations publiques', md: parAdmin('Ensemble', 'TE'), provisoire: provComptes },
      composantes: ADMINS.map(([k, nom]) => ({ nom, md: parAdmin(k, 'TE'), provisoire: provComptes })),
      titreComposantes: 'Chaque administration',
      notes: ruptures(idx, 'depenses_administration'),
      source: `${ad.source} (${ad.millesime})`,
      liens: [
        [lien('/explorer/etat'), 'Le budget de l’État'],
        [lien('/explorer/secu'), 'La Sécurité sociale'],
        [lien('/explorer/collectivites'), 'Les collectivités locales'],
      ],
    })
  }
  if (fct) {
    const ecarts = fct.ecarts.map((e) => `En ${e.annee}, le total par fonction (${md(e.total_cofog_md)}) et les dépenses totales (${md(e.depenses_totales_md)}) diffèrent de ${md(Math.abs(e.ecart_md))} : deux tables Eurostat, écart montré tel quel.`)
    blocs.push({
      id: 'fonctions',
      titre: 'Les dépenses par fonction',
      intro: `${fct.definition} Données de ${fct.annees[0]} à ${fct.annees[fct.annees.length - 1]}.`,
      composantes: fct.fonctions.map((f) => ({ nom: f.nom, md: f.md, provisoire: f.provisoire })),
      notes: [fct.avertissement, ...ruptures(idx, 'fonctions'), ...ecarts],
      source: fct.source,
      liens: [[lien('/explorer/secu'), 'La protection sociale en détail']],
    })
  }
  if (ad) {
    blocs.push({
      id: 'solde',
      titre: 'Le solde : déficit ou excédent',
      intro: 'Recettes moins dépenses de l’année. Un nombre négatif est un déficit : la différence est empruntée.',
      principal: { nom: 'Solde de l’ensemble des administrations publiques', md: parAdmin('Ensemble', 'B9'), provisoire: provComptes },
      composantes: ADMINS.map(([k, nom]) => ({ nom, md: parAdmin(k, 'B9'), provisoire: provComptes })),
      titreComposantes: 'Solde de chaque administration',
      notes: ['Le solde de l’ensemble tient compte des transferts entre administrations : il n’est pas la somme des soldes affichés pour chacune.'],
      source: `${ad.source} (${ad.millesime})`,
      liens: [[lien('/explorer/etat'), 'La part du budget de l’État payée par l’emprunt']],
    })
  }
  const ens = enc?.insee.Ensemble
  if (ens) {
    blocs.push({
      id: 'dette',
      titre: 'La dette publique',
      intro: 'Ce que doivent l’ensemble des administrations publiques en fin d’année.',
      principal: { nom: 'Dette publique en fin d’année', md: ens.md, provisoire: provComptes },
      composantes: [],
      notes: [enc!.definition],
      source: enc!.source,
      liens: [[lien('/explorer/dette'), 'La dette publique en détail']],
    })
  }
  const s13 = itr?.nationale.eurostat.secteurs.S13
  if (s13) {
    blocs.push({
      id: 'interets',
      titre: 'Les intérêts de la dette',
      intro: 'Intérêts dus chaque année par l’ensemble des administrations publiques (comptabilité nationale).',
      principal: { nom: 'Intérêts de la dette', md: s13.md, provisoire: provComptes },
      composantes: [],
      notes: [itr!.avertissement],
      source: itr!.nationale.eurostat.source.titre,
      liens: [[lien('/explorer/dette'), 'Deux façons de compter les intérêts']],
    })
  }
  return blocs
}

export async function rendre(cible: HTMLElement, params?: URLSearchParams) {
  const [idx, r, ad, fct, enc, itr] = await Promise.all([
    chargerSiPresent<Index>('series/index.json'),
    chargerSiPresent<Recettes>('recettes.json'),
    chargerSiPresent<Administrations>('administrations.json'),
    chargerSiPresent<Fonctions>('series/fonctions.json'),
    chargerSiPresent<Encours>('dette/encours.json'),
    chargerSiPresent<Interets>('dette/interets.json'),
  ])
  if (!idx) {
    cible.innerHTML = `<h1>Les finances publiques depuis 2005</h1><div class="en-cours"><p><strong>Données en cours d’intégration.</strong> Indice des prix et PIB nécessaires aux euros constants et à la part du PIB.</p><p>En attendant, les montants année par année sont dans <a href="${lien('/explorer/recettes')}">les recettes</a> et <a href="${lien('/explorer/dette')}">la dette publique</a>.</p></div>`
    return
  }
  const demande = params?.get('u') as Mode | null
  let mode: Mode = MODES.some((m) => m.id === demande) ? demande! : 'courants'
  const debut = Number(idx.annee_debut)
  const fin = Math.max(...Object.keys(idx.pib.md).map(Number))
  const annees = Array.from({ length: fin - debut + 1 }, (_, i) => String(debut + i))
  const blocs = construireBlocs(idx, r, ad, fct, enc, itr)
  const ref = idx.annee_reference
  const generales = [...ruptures(idx, 'comptes'), ...ruptures(idx, 'pib').slice(0, 1)]
  const dessiner = () => blocs.map((b) => blocHtml(b, annees, mode, idx)).join('')
  const explication = () =>
    mode === 'courants'
      ? 'Montants tels que publiés, chaque année en euros de l’année.'
      : mode === 'constants'
        ? `Montants corrigés de la hausse des prix à la consommation, exprimés en euros de ${ref}. ${idx.prix.methode}`
        : `${idx.pib.definition} ${idx.pib.methode}`
  const notesMode = () => (mode === 'constants' ? ruptures(idx, 'prix') : mode === 'pib' ? ruptures(idx, 'pib').slice(1) : [])

  cible.innerHTML = `
<h1>Les finances publiques depuis 2005</h1>
<p class="chapeau">Recettes, dépenses, solde, dette et intérêts de l’ensemble des administrations publiques, année par année de ${h(annees[0])} à ${h(annees[annees.length - 1])}. Choisis comment lire les montants : tels que publiés, corrigés de la hausse des prix, ou rapportés à ce que le pays produit en un an.</p>
<div class="bascule" role="group" aria-label="Unité des montants">${MODES.map((m) => `<button type="button" data-mode="${m.id}" aria-pressed="${m.id === mode}">${h(m.id === 'constants' ? `${m.libelle} (de ${ref})` : m.libelle)}</button>`).join('')}</div>
<div class="carte carte-contour sl-mode"><p id="sl-explication">${h(explication())}</p><ul class="sl-notes" id="sl-notes-mode">${notesMode().map((n) => `<li>${h(n)}</li>`).join('')}</ul></div>
<p class="avertissement">${h(idx.avertissement)}</p>
<ul class="sl-legende" aria-label="Légende des courbes"><li><span class="sl-motif" aria-hidden="true"></span>Trait plein : valeur publiée</li><li><span class="sl-motif sl-motif-provisoire" aria-hidden="true"></span>Pointillé : valeur provisoire, révisable</li></ul>
<div id="sl-blocs">${dessiner()}</div>
<section aria-labelledby="sl-h-sources"><h2 id="sl-h-sources">Ruptures de série et sources</h2>
<ul class="sl-notes">${generales.map((n) => `<li>${h(n)}</li>`).join('')}</ul>
${source(`Indice des prix : ${idx.prix.source.titre}, mise à jour ${idx.prix.source.maj}`)}
${source(`PIB : ${idx.pib.source.titre}, mise à jour ${idx.pib.source.maj}`)}
${source(idx.source, idx.millesime)}
<p class="liens-sortie"><a href="${lien('/methode')}">Méthode et sources du site</a></p>
</section>`

  const zone = cible.querySelector<HTMLElement>('#sl-blocs')!
  cible.querySelectorAll<HTMLButtonElement>('[data-mode]').forEach((bouton) =>
    bouton.addEventListener('click', () => {
      const m = bouton.dataset.mode as Mode
      if (m === mode) return
      mode = m
      cible.querySelectorAll<HTMLButtonElement>('[data-mode]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)))
      // Détails ouverts conservés d'un mode à l'autre.
      const section = (d: Element) => d.closest('section')?.getAttribute('aria-labelledby') ?? ''
      const ouverts = new Set(Array.from(zone.querySelectorAll('details[open]')).map(section))
      zone.innerHTML = dessiner()
      zone.querySelectorAll<HTMLDetailsElement>('details').forEach((d) => {
        if (ouverts.has(section(d))) d.open = true
      })
      cible.querySelector('#sl-explication')!.textContent = explication()
      cible.querySelector('#sl-notes-mode')!.innerHTML = notesMode().map((n) => `<li>${h(n)}</li>`).join('')
      rendreDefilables(zone)
      annoncer(`Montants affichés : ${uniteMode(mode, ref)}.`)
    }),
  )
}

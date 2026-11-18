// Glossaire : les sigles et les mots techniques du site, définis en langage courant avec leur source
// (src/glossaire.json). Une ancre par terme (id), une ancre par lettre ; « ?terme=<id> » place le focus sur l'entrée
// (liens posés par src/composants/sigles.ts). La page elle-même n'est pas marquée (data-sans-sigles).
import donnees from '../glossaire.json'
import { normaliser, type Glossaire, type TermeGlossaire } from '../composants/sigles'
import { h } from '../util'

const GLOSSAIRE = donnees as unknown as Glossaire
const DEPOT = 'https://github.com/MoonEyes/Ou-vont-mes-impots'

/** Clé de tri et lettre d'un terme : sans accents ni ponctuation. */
const cleTri = (t: TermeGlossaire) => normaliser(t.terme).replace(/[^a-z0-9]+/g, ' ').trim()
const lettre = (t: TermeGlossaire) => cleTri(t).charAt(0).toUpperCase()

export function termesTries(g: Glossaire = GLOSSAIRE): TermeGlossaire[] {
  return [...g.termes].sort((a, b) => cleTri(a).localeCompare(cleTri(b), 'fr') || (a.forme ?? '').localeCompare(b.forme ?? '', 'fr'))
}

const pluriel = (n: number) => `${n} définition${n > 1 ? 's' : ''}`

function entree(t: TermeGlossaire, parId: Map<string, TermeGlossaire>): string {
  const renvois = (t.voir ?? []).map((id) => parId.get(id)).filter((x): x is TermeGlossaire => !!x)
  return `<div class="glossaire-entree" id="${h(t.id)}">
<dt><dfn>${h(t.terme)}</dfn>${t.forme ? ` <span class="glossaire-forme">${h(t.forme)}</span>` : ''}</dt>
<dd><p>${h(t.definition)}</p>${t.variantes?.length ? `<p class="aide">Aussi écrit : ${t.variantes.map(h).join(', ')}.</p>` : ''}${
    renvois.length ? `<p class="aide">Voir aussi : ${renvois.map((r) => `<a href="#${h(r.id)}">${h(r.terme)}${r.forme && r.sigle ? ` (${h(r.forme)})` : ''}</a>`).join(', ')}.</p>` : ''
  }<p class="source">Source : <a href="${h(t.source.url)}" rel="noopener noreferrer">${h(t.source.nom)}</a></p></dd>
</div>`
}

/** Place le focus sur une entrée ou un titre de lettre (sans défilement animé) et la signale par un contour. */
function cibler(cible: HTMLElement, el: HTMLElement) {
  cible.querySelectorAll('.glossaire-cible').forEach((x) => x.classList.remove('glossaire-cible'))
  if (el.classList.contains('glossaire-entree')) el.classList.add('glossaire-cible')
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1')
  el.focus()
}

export function rendre(cible: HTMLElement, params: URLSearchParams) {
  const termes = termesTries()
  const parId = new Map(termes.map((t) => [t.id, t]))
  const lettres = [...new Set(termes.map(lettre))]
  // Les sigles de cette page ne sont pas transformés en liens vers… cette page.
  cible.setAttribute('data-sans-sigles', '')
  cible.innerHTML = `
<h1>Glossaire : sigles et mots du budget</h1>
<p class="chapeau">Ce que veulent dire les sigles (LFI, PLF, CSG…) et les mots techniques du site, en langage courant. Chaque définition renvoie à sa source officielle. Cette page explique des mots : elle ne donne aucun montant.</p>
<p>Sur les autres pages, la première fois qu’un sigle apparaît, il est souligné en pointillé : il mène à sa définition ici. Sa forme complète s’affiche au survol et elle est lue par les lecteurs d’écran.</p>
<form class="carte" role="search" id="glossaire-form">
  <label for="glossaire-filtre">Chercher un sigle ou un mot</label>
  <input id="glossaire-filtre" type="search" autocomplete="off" aria-describedby="glossaire-compte" />
  <p id="glossaire-compte" class="aide" aria-live="polite">${pluriel(termes.length)}.</p>
</form>
<nav aria-label="Lettres du glossaire"><ul class="glossaire-lettres">${lettres.map((l) => `<li><a href="#lettre-${l.toLowerCase()}">${l}</a></li>`).join('')}</ul></nav>
${lettres
  .map(
    (l) => `<section class="glossaire-section" aria-labelledby="lettre-${l.toLowerCase()}"><h2 id="lettre-${l.toLowerCase()}">${l}</h2>
<dl class="glossaire-liste">${termes
      .filter((t) => lettre(t) === l)
      .map((t) => entree(t, parId))
      .join('')}</dl></section>`,
  )
  .join('')}
<p id="glossaire-aucun" class="absent" hidden>Aucune définition ne correspond. Essaie le sigle seul (par exemple « CSG ») ou un mot de sa forme complète.</p>
<p>Une définition manque ou te semble inexacte ? <a href="${DEPOT}/issues" rel="noopener noreferrer">Signale-la sur GitHub</a>. Comment les chiffres du site sont obtenus : <a href="#/methode">Méthode et sources</a>.</p>`

  // Recherche : filtre les entrées affichées, masque les lettres vides et annonce le nombre de résultats.
  const champ = cible.querySelector<HTMLInputElement>('#glossaire-filtre')!
  const compte = cible.querySelector<HTMLElement>('#glossaire-compte')!
  const aucun = cible.querySelector<HTMLElement>('#glossaire-aucun')!
  cible.querySelector('#glossaire-form')!.addEventListener('submit', (e) => e.preventDefault())
  // Texte cherché : celui affiché par l'entrée (terme, forme, autres graphies, définition, source), lu une fois.
  let index: [HTMLElement, string][] | null = null
  champ.addEventListener('input', () => {
    index ??= Array.from(cible.querySelectorAll<HTMLElement>('.glossaire-entree')).map((el) => [el, normaliser(el.textContent ?? '')])
    const q = normaliser(champ.value.trim())
    let n = 0
    for (const [el, texte] of index) {
      const visible = !q || texte.includes(q)
      el.hidden = !visible
      if (visible) n++
    }
    cible.querySelectorAll<HTMLElement>('.glossaire-section').forEach((s) => (s.hidden = !s.querySelector('.glossaire-entree:not([hidden])')))
    compte.textContent = `${pluriel(n)}.`
    aucun.hidden = n > 0
  })

  // Ancres de la page (lettres, renvois) : focus sur la cible sans changer d'adresse (le fragment sert au routage).
  cible.addEventListener('click', (e) => {
    const a = (e.target as Element | null)?.closest?.('a[href^="#"]')
    const href = a?.getAttribute('href') ?? ''
    if (!a || href.startsWith('#/')) return
    const el = cible.querySelector<HTMLElement>(`[id="${href.slice(1).replace(/"/g, '')}"]`)
    if (!el) return
    e.preventDefault()
    const entreeMasquee = el.closest<HTMLElement>('[hidden]')
    if (entreeMasquee) {
      champ.value = ''
      champ.dispatchEvent(new Event('input'))
    }
    cibler(cible, el)
  })

  // Lien venu d'un sigle marqué ailleurs : ?terme=<id>. Après le placement du focus sur le titre par le routeur.
  const terme = params.get('terme')
  if (terme && parId.has(terme))
    setTimeout(() => {
      const el = cible.querySelector<HTMLElement>(`[id="${terme}"]`)
      if (el && el.isConnected) cibler(cible, el)
    }, 0)
}

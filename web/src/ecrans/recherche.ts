// Page « Rechercher dans le site » : tous les résultats d'une recherche, par famille (pages, communes, budget de
// l'État, organisations, parlementaires, glossaire...), avec le nombre de résultats annoncé et la règle d'ordre. La recherche se fait dans le navigateur (src/composants/recherche.ts)
// sur l'index construit au build ; il n'est lu qu'au moment de chercher.
import { adresse, chargerMoteur, chercherTout, grouper, type Moteur, moteurCharge, pluriel, precision, REGLE_ORDRE, type Resultat } from '../composants/recherche'
import { lien } from '../routeur'
import { absent, h, source } from '../util'

const PAR_GROUPE = 10
const DE_PLUS = 50
const EXEMPLES = ['Lyon', 'programme 141', 'CNRS', 'CSG']

const ligne = (m: Moteur, r: Resultat) => `<li><a href="${h(adresse(m, r.e))}">${h(r.e.nom)}</a><span class="dest">${h(precision(m, r.e, false))}</span></li>`

/** D'où viennent les résultats : chaque famille de l'index, son nombre d'entrées, sa source et son millésime. */
function sources(m: Moteur): string {
  return `<details class="recherche-sources"><summary>Ce que contient la recherche</summary><ul>${m.familles
    .map((f, i) => `<li><strong>${h(f.groupe)}</strong> : ${h(pluriel(m.comptes[i], 'entrée'))}.${f.source ? source(f.source, f.millesime) : ''}</li>`)
    .join('')}</ul>${m.date ? `<p class="aide">Index construit à partir des données publiées le ${h(m.date.split('-').reverse().join('/'))}.</p>` : ''}</details>`
}

export function rendre(cible: HTMLElement, params: URLSearchParams) {
  const q = (params.get('q') ?? '').trim().slice(0, 120)
  cible.innerHTML = `
<h1>Rechercher dans le site</h1>
<p class="chapeau">Une organisation, un parlementaire, une commune, un programme du budget, un impôt, un mot ou une page du site. La recherche se fait sur ton appareil : rien de ce que tu tapes n’est envoyé ni gardé.</p>
<form id="recherche-page" class="carte carte-contour recherche-formulaire" role="search" aria-label="Recherche dans le site, page de résultats">
  <label for="recherche-q">Ce que tu cherches</label>
  <div class="recherche-ligne"><input id="recherche-q" name="q" type="search" value="${h(q)}" autocomplete="off" spellcheck="false" enterkeyhint="search" aria-describedby="recherche-consigne" /><button type="submit" class="bouton-principal">Rechercher</button></div>
  <p id="recherche-consigne" class="aide">Accents et majuscules ne comptent pas, une faute de frappe par mot est tolérée. Exemples : ${EXEMPLES.map((x) => `<a href="${h(lien('/recherche', { q: x }))}">${h(x)}</a>`).join(', ')}.</p>
</form>
<p id="recherche-statut" class="recherche-statut" role="status"></p>
<div id="recherche-resultats"></div>
<details class="avant-lecture"><summary>Ce que cette page montre et ne montre pas</summary>
<p>Entreprises et associations (nom ou SIREN), députés et sénateurs, communes, départements, missions et programmes du budget de l’État, impôts, mots du glossaire, pages du site. Elle ne cherche pas dans les montants. Seuls les noms que le site publie déjà sont cherchés : les organisations qui ont une fiche (personnes morales présentes dans au moins deux sources), les parlementaires nommés par leurs votes publics ou leurs amendements adoptés.</p>
<p class="aide" data-regle-ordre>${h(REGLE_ORDRE)}</p>
</details>
<div id="recherche-zone-sources"></div>`

  const champ = cible.querySelector<HTMLInputElement>('#recherche-q')!
  const statut = cible.querySelector<HTMLElement>('#recherche-statut')!
  const zone = cible.querySelector<HTMLElement>('#recherche-resultats')!
  let tour = 0
  let minuterie = 0
  let annonce = 0
  // Le texte du statut est posé un instant après : un lecteur d'écran annonce le changement, même juste après l'affichage.
  const dire = (texte: string) => {
    const n = ++annonce
    statut.textContent = ''
    window.setTimeout(() => {
      if (n === annonce) statut.textContent = texte
    }, 60)
  }

  const montrer = async (texte: string) => {
    const moi = ++tour
    if (texte.length < 2) {
      zone.innerHTML = ''
      dire(texte ? 'Écris au moins deux lettres ou chiffres.' : '')
      return
    }
    if (!moteurCharge()) dire('Recherche en cours…')
    const m = await chargerMoteur()
    if (moi !== tour) return
    if (!m) {
      zone.innerHTML = absent('La recherche n’est pas disponible pour le moment : son index n’a pas été trouvé. Les pages restent accessibles par le menu.')
      dire('La recherche n’est pas disponible pour le moment.')
      return
    }
    const z = cible.querySelector<HTMLElement>('#recherche-zone-sources')
    if (z && !z.innerHTML) z.innerHTML = sources(m)
    const { resultats, elargie } = await chercherTout(m, texte, PAR_GROUPE)
    if (moi !== tour) return
    const groupes = grouper(resultats)
    if (!resultats.length) {
      zone.innerHTML = `<p>Aucun résultat pour « ${h(texte)} ». Vérifie l’orthographe ou essaie un seul mot. Tu peux aussi parcourir <a href="#/explorer">les dépenses publiques</a>, <a href="#/local">le budget de ta commune</a> ou <a href="#/beneficiaires">qui reçoit l’argent</a>.</p>`
      dire(`Aucun résultat pour « ${texte} ».`)
      return
    }
    zone.innerHTML =
      (elargie ? `<p class="aide">Aucun résultat ne contient tous les mots cherchés : voici ceux qui en contiennent une partie.</p>` : '') +
      groupes
        .map(({ f, resultats: liste }) => {
          const fam = m.familles[f]
          return `<section class="recherche-groupe" aria-labelledby="rg-${h(fam.cle)}">
<h2 id="rg-${h(fam.cle)}">${h(fam.groupe)} <span class="recherche-compte">(${h(new Intl.NumberFormat('fr-FR').format(liste.length))})</span></h2>
<ul class="lignes recherche-liste" id="rl-${h(fam.cle)}">${liste.slice(0, PAR_GROUPE).map((r) => ligne(m, r)).join('')}</ul>
${liste.length > PAR_GROUPE ? `<button type="button" class="recherche-plus" data-f="${f}" aria-controls="rl-${h(fam.cle)}">Afficher plus de résultats (${h(pluriel(liste.length - PAR_GROUPE, 'autre'))})</button>` : ''}
</section>`
        })
        .join('')
    zone.querySelectorAll<HTMLButtonElement>('.recherche-plus').forEach((b) => {
      const liste = groupes.find((g) => String(g.f) === b.dataset.f)!.resultats
      let vus = PAR_GROUPE
      b.addEventListener('click', () => {
        const ul = b.previousElementSibling as HTMLElement
        ul.insertAdjacentHTML('beforeend', liste.slice(vus, vus + DE_PLUS).map((r) => ligne(m, r)).join(''))
        // Le focus va au premier résultat ajouté : la lecture reprend où la liste s'est allongée.
        ul.querySelectorAll<HTMLAnchorElement>('a')[vus]?.focus()
        vus += DE_PLUS
        if (vus >= liste.length) b.remove()
        else b.textContent = `Afficher plus de résultats (${pluriel(liste.length - vus, 'autre')})`
      })
    })
    dire(
      `${pluriel(resultats.length, 'résultat')} pour « ${texte} »${groupes.length > 1 ? `, en ${groupes.length} rubriques` : ''}${elargie ? ', qui contiennent une partie des mots' : ''}.`,
    )
  }

  champ.addEventListener('input', () => {
    window.clearTimeout(minuterie)
    minuterie = window.setTimeout(() => montrer(champ.value.trim()), 200)
  })
  cible.querySelector('#recherche-page')!.addEventListener('submit', (e) => {
    e.preventDefault()
    window.clearTimeout(minuterie)
    const texte = champ.value.trim()
    const voulu = lien('/recherche', texte ? { q: texte } : {})
    // Même recherche que l'adresse : résultats rafraîchis sur place ; sinon nouvelle adresse (historique, partage).
    if (location.hash === voulu || (!location.hash && new URLSearchParams(location.search).get('q') === texte)) montrer(texte)
    else location.hash = voulu
  })
  return q ? { titre: `Recherche « ${q} »`, suite: montrer(q) } : undefined
}

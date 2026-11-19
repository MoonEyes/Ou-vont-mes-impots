// Règles de la direction artistique vérifiables hors navigateur (2 et 4), et identité non officielle.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { badgeStatut, legendeStatuts, STATUTS, traitStatut } from '../src/util'

const RACINE = process.cwd()
const css = readFileSync(join(RACINE, 'src', 'styles.css'), 'utf8')
const sources = (d: string): string[] =>
  readdirSync(d).flatMap((n) => (statSync(join(d, n)).isDirectory() ? sources(join(d, n)) : /\.(ts|css|html|svg)$/.test(n) ? [join(d, n)] : []))
const tout = [...sources(join(RACINE, 'src')), join(RACINE, 'index.html'), join(RACINE, 'public', 'favicon.svg')].map((f) => [f, readFileSync(f, 'utf8')] as const)

describe('règle 2 : trois statuts distincts sans la couleur', () => {
  it('libellés distincts', () => {
    const l = Object.values(STATUTS).map((s) => s.libelle)
    expect(new Set(l).size).toBe(3)
  })
  it('motifs distincts (plein, pointillé, hachuré) dans la légende, les pastilles et les barres', () => {
    for (const c of ['trace', 'approche', 'nonpub']) expect(legendeStatuts()).toContain(`motif-${c}`)
    const fond = (c: string) => new RegExp(`\\.motif-${c},\\n\\.statut-${c},\\n\\.barres li \\.barre-remplissage\\.statut-${c} \\{([^}]*)\\}`).exec(css)![1]
    expect(fond('trace')).toMatch(/background: var\(--contour\);/)
    expect(fond('approche')).toContain('radial-gradient')
    expect(fond('nonpub')).toContain('repeating-linear-gradient(45deg')
    expect(new Set(['trace', 'approche', 'nonpub'].map(fond)).size).toBe(3)
    // Le motif n'est jamais seul : chaque statut a son mot (« tracé », « approché », « non publié »).
    for (const c of ['trace', 'approche', 'nonpub'] as const) expect(badgeStatut(c)).toContain(STATUTS[c].libelle)
    expect(traitStatut('approche')).toContain('aria-hidden="true"')
  })
})

describe('règle 4 : valeur finale tout de suite, mouvement court et coupé sur demande', () => {
  it('transitions et animations <= 400 ms', () => {
    for (const m of css.matchAll(/(?:transition|animation)(?:-duration)?:\s*([^;]+);/g)) {
      for (const d of m[1].matchAll(/([\d.]+)(ms|s)\b/g)) {
        const ms = d[2] === 's' ? Number(d[1]) * 1000 : Number(d[1])
        expect(ms, m[0]).toBeLessThanOrEqual(400)
      }
    }
  })
  it('coupées sous prefers-reduced-motion', () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*transition: none !important[\s\S]*animation: none !important/)
  })
  it('aucun compteur défilant ni animation pilotée par script', () => {
    for (const [f, c] of tout) {
      expect(c, f).not.toMatch(/requestAnimationFrame|setInterval\(/)
      expect(c, f).not.toMatch(/@keyframes/)
    }
  })
  it('Sankey sans animation', () => {
    expect(readFileSync(join(RACINE, 'src', 'composants', 'sankey.ts'), 'utf8')).toContain('animation: false')
  })
})

describe('identité', () => {
  it('Sankey : aucune couleur en dur, lue dans les variables CSS', () => {
    const s = readFileSync(join(RACINE, 'src', 'composants', 'sankey.ts'), 'utf8')
    expect(s).not.toMatch(/#[0-9a-fA-F]{3,6}\b/)
    expect(s).toContain('getComputedStyle')
  })
  it('pas un site officiel : ni Marianne, ni DSFR, ni bleu-blanc-rouge', () => {
    for (const [f, c] of tout) {
      expect(c, f).not.toMatch(/marianne|dsfr|#000091|#e1000f|#002395|#ed2939/i)
    }
  })
  it('polices auto-hébergées de la direction « billet découpé » : Bricolage Grotesque et Figtree, rien d’autre', () => {
    expect(css).toContain("font-family: 'Bricolage Grotesque'")
    expect(css).toContain("font-family: 'Figtree'")
    expect([...css.matchAll(/@font-face/g)]).toHaveLength(2)
    for (const m of css.matchAll(/url\('([^']+\.woff2)'\)/g)) expect(m[1]).toMatch(/^\.\.\/node_modules\/@fontsource-variable\//)
    expect(css).not.toMatch(/Inter|Space Grotesk|Fraunces|Atkinson|Recursive/)
    // Pas de police à chasse fixe, pas de capitales forcées pour les libellés.
    expect(css).not.toMatch(/monospace|text-transform:\s*uppercase/)
  })
  it('ombres pleines seulement (effet autocollant) : aucun flou, aucune ombre grise', () => {
    const ombres = [...css.matchAll(/box-shadow:\s*([^;]+);/g)].map((m) => m[1])
    expect(ombres.length).toBeGreaterThan(0)
    for (const o of ombres) expect(o).toMatch(/^0 \dpx 0 var\(--[a-z-]+\)$/)
    expect(css).not.toMatch(/rgba?\(|linear-gradient\([^)]*transparent\s+\d+%,\s*#/)
  })
})

describe('navigation et métadonnées', () => {
  const html = readFileSync(join(RACINE, 'index.html'), 'utf8')
  it('site web : navigation horizontale à 6 entrées (les 4 portes, Explorer, Méthode), bouton « Menu » sur téléphone, plus de barre d’onglets', () => {
    const nav = /<nav id="navigation"[\s\S]*?<\/nav>/.exec(html)![0]
    const entrees = [...nav.matchAll(/data-rubrique="([^"]+)"/g)].map((m) => m[1])
    expect(entrees).toEqual(['/calcul', '/local', '/beneficiaires', '/decisions', '/explorer', '/methode'])
    expect([...nav.matchAll(/<a [^>]*>([^<]+)<\/a>/g)].map((m) => m[1])).toEqual(['Mon salaire', 'Ma commune', 'Qui reçoit l’argent', 'Qui décide', 'Explorer', 'Méthode'])
    expect(nav).not.toMatch(/>\s*\d+\.\s/)
    expect(nav).toMatch(/<button type="button" id="bouton-menu" aria-expanded="false" aria-controls="menu">/)
    expect(html).toMatch(/<header class="entete">[\s\S]*<nav id="navigation"[\s\S]*<\/header>/)
    expect(html).not.toMatch(/bouton-plus|feuille-plus/)
    // La navigation n'est jamais fixée en bas de l'écran.
    expect(css).not.toMatch(/position:\s*fixed/)
    expect(css).not.toMatch(/safe-area-inset-bottom/)
  })
  it('pied de page complet : le site, sources et méthode, le projet et les mentions', () => {
    const pied = /<footer class="pied">[\s\S]*?<\/footer>/.exec(html)![0]
    // Titres du pied en H3 (lot 3 du design : un H2 a toujours la même taille, les petits titres sont des H3).
    for (const t of ['Le site', 'Sources et méthode', 'Le projet']) expect(pied).toContain(`>${t}</h3>`)
    for (const l of ['#/calcul', '#/explorer', '#/local', '#/beneficiaires', '#/decisions', '#/methode', '#/methode/tracabilite', '#/methode/limites', '#/demarche', '#/mentions']) expect(pied).toContain(`href="${l}"`)
    expect(pied).toContain('Aucun cookie, aucune mesure d’audience')
  })
  it('pied replié au téléphone (finitions du 19/11 : 745 px avant, 216 px après à 360 px) : marque et liens essentiels visibles, le reste dans un repli ouvert sur grand écran', () => {
    const pied = /<footer class="pied">[\s\S]*?<\/footer>/.exec(html)![0]
    const tete = /<div class="pied-tete">([\s\S]*?)<details/.exec(pied)![1]
    for (const l of ['#/calcul', '#/local', '#/methode', '#/mentions']) expect(tete).toContain(`href="${l}"`)
    expect(tete).toContain('class="marque"')
    const repli = /<details class="pied-plus">([\s\S]*?)<\/details>/.exec(pied)![1]
    expect(repli).toMatch(/^\s*<summary>[^<]+<\/summary>/)
    for (const t of ['Le site', 'Sources et méthode', 'Le projet', 'Aucun cookie']) expect(repli).toContain(t)
    // Grand écran : repli affiché sans résumé seulement là où le navigateur sait l'ouvrir par la feuille de style.
    expect(css).toMatch(/@supports selector\(::details-content\) \{\s*@media \(min-width: 45rem\) \{[\s\S]*?\.pied-plus::details-content \{\s*content-visibility: visible;/)
  })
  it('cibles de la navigation >= 48 px, bouton « Menu » compris', () => {
    const bloc = /\.navigation ul a \{([\s\S]*?)\}/.exec(css)![1]
    expect(Number(/min-height: (\d+)px/.exec(bloc)![1])).toBeGreaterThanOrEqual(48)
    const menu = /#bouton-menu \{([\s\S]*?)\}/.exec(css)![1]
    expect(Number(/min-height: (\d+)px/.exec(menu)![1])).toBeGreaterThanOrEqual(48)
  })
  it('titre, Open Graph, carte Twitter et JSON-LD vérifiables', () => {
    expect(html).toContain('<title>Où vont mes impôts : vois où va l’argent que tu verses</title>')
    for (const p of ['og:title', 'og:description', 'og:image', 'og:url']) expect(html).toContain(`property="${p}"`)
    expect(html).toContain('name="twitter:card" content="summary_large_image"')
    const ld = JSON.parse(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/.exec(html)![1])
    const types = ld['@graph'].map((x: { '@type': string }) => x['@type'])
    expect(types).toEqual(['WebSite', 'Dataset'])
    for (const x of ld['@graph']) expect(x.creator.name).toBe('Projet citoyen Où vont mes impôts')
    const png = readFileSync(join(RACINE, 'public', 'og.png'))
    expect(png.readUInt32BE(16)).toBe(1200)
    expect(png.readUInt32BE(20)).toBe(630)
    // Le billet de l'image de partage reprend les parts de l'exemple calculé (src/exemple-lyon.json), sans chiffre inventé.
    const og = readFileSync(join(RACINE, 'scripts', 'og.html'), 'utf8')
    const ex = JSON.parse(readFileSync(join(RACINE, 'src', 'exemple-lyon.json'), 'utf8'))
    expect([...og.matchAll(/data-part="(\d+)"/g)].map((m) => Number(m[1]))).toEqual(Object.values(ex.sur100))
  })
})

describe('aucun taux codé en dur', () => {
  it('accueil et méthode lisent leurs pourcentages et parts dans les données', () => {
    for (const f of ['accueil.ts', 'methode.ts', 'tracabilite.ts', 'demarche.ts']) {
      const c = readFileSync(join(RACINE, 'src', 'ecrans', f), 'utf8')
      // Taux de traçabilité publiés par le pipeline (actuels et passés) : jamais recopiés dans le code.
      expect(c, f).not.toMatch(/(62|69|78|95)[,.]\d+\s*%/)
      if (f === 'accueil.ts') expect(c, f).not.toMatch(/\d\s*%/)
      // Nombre de sources et euros sans destinataire : lus dans _sources.json et tracabilite/resume.json.
      if (f === 'accueil.ts' || f === 'demarche.ts') expect(c, f).not.toMatch(/(Plus de|plus de) \d|\d+ € n’ont pas/)
      expect(c, f).not.toMatch(/\?\?\s*\d+\.\d+/)
    }
  })
})

// Charte de neutralité (docs/NEUTRALITE.md), règles 7 et 10 : couleurs sans valeur morale, aucun code institutionnel.
describe('neutralité : couleurs et identité visuelle', () => {
  const regle = (sel: string) => new RegExp(`(^|\\n)[^{}]*${sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[^{]*\\{([^}]*)\\}`).exec(css)?.[2] ?? ''
  it('tendances et réductions : même couleur que le texte, ni vert « bon » ni rouge « mauvais »', () => {
    for (const sel of ['.tendance-progres', '.tendance-recul', '.reduction .montant']) {
      const r = regle(sel)
      expect(r, sel).toContain('color: var(--texte)')
      expect(r, sel).not.toMatch(/--(ok|erreur|accent)\b/)
    }
  })
  it('aucun code visuel institutionnel (bleu et rouge de l’État, Marianne, DSFR)', () => {
    for (const [f, c] of tout) expect(c, f).not.toMatch(/#000091|#e1000f|#6a6af4|marianne|\bdsfr\b|République française/i)
    const html = readFileSync(join(RACINE, 'index.html'), 'utf8')
    expect(html).toContain('<span class="non-officiel">Site citoyen, non officiel</span>')
    expect(html).toContain('Il ne remplace pas impots.gouv.fr et ne juge aucune dépense.')
  })
})

// @vitest-environment happy-dom
// Composants de choix partagés (audit ergonomie des choix du 19/11/2026, docs/AUDIT_CHOIX.md) : clavier, états ARIA,
// cibles de 44 px, règle du nombre d'options ; et garde-fou : aucun écran n'écrit un choix à la main.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { beforeEach, describe, expect, it } from 'vitest'
import {
  LIBELLE_COURT,
  SEUIL_LISTE,
  SEUIL_SEGMENTE,
  caseACocher,
  choix,
  choixLiens,
  filtrerListe,
  fixerChoix,
  interrupteur,
  listeOnglets,
  listeRecherche,
  optionRiche,
  radioListe,
  remplirListe,
  segmente,
  valeurChoix,
} from '../src/composants/choix'

const SRC = join(process.cwd(), 'src')
const css = readFileSync(join(SRC, 'styles.css'), 'utf8')
const opts = (...l: string[]) => l.map((x) => ({ valeur: x.toLowerCase(), libelle: x }))
const touche = (e: Element, key: string) => e.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
let zone: HTMLElement
const monter = (html: string) => {
  zone.innerHTML = html
  return zone
}
beforeEach(() => {
  document.body.innerHTML = '<main id="z"></main>'
  zone = document.getElementById('z')!
})

/** Corps de la règle CSS dont le sélecteur (liste) contient exactement `sel`. */
function regle(sel: string): string {
  const sansCommentaires = css.replace(/\/\*[\s\S]*?\*\//g, '')
  for (const m of sansCommentaires.matchAll(/(^|\n)([^{}\n][^{}]*)\{([^}]*)\}/g)) {
    if (m[2].split(',').map((s) => s.trim()).includes(sel)) return m[3]
  }
  throw new Error(`règle absente : ${sel}`)
}
const px = (v: string) => (v.endsWith('rem') ? parseFloat(v) * 16 : parseFloat(v))
const minHauteur = (sel: string) => px(/min-height:\s*([^;]+);/.exec(regle(sel))![1].trim())

describe('segmenté (2 à 4 options courtes)', () => {
  const html = () => segmente({ id: 'vue', etiquette: 'Vue', options: opts('Mois', 'An', 'Total'), valeur: 'an' })

  it('groupe radio ARIA nommé, un seul bouton atteint par Tab, état aria-checked', () => {
    monter(html())
    const g = zone.querySelector('#vue')!
    expect(g.getAttribute('role')).toBe('radiogroup')
    expect(document.getElementById(g.getAttribute('aria-labelledby')!)?.textContent).toBe('Vue')
    const b = [...g.querySelectorAll<HTMLButtonElement>('[role="radio"]')]
    expect(b.map((x) => x.getAttribute('aria-checked'))).toEqual(['false', 'true', 'false'])
    expect(b.map((x) => x.tabIndex)).toEqual([-1, 0, -1])
    expect(b.every((x) => x.type === 'button')).toBe(true)
    expect(valeurChoix(zone, 'vue')).toBe('an')
  })

  it('clavier : flèches (avec retour au début), Début et Fin ; la sélection suit le focus et prévient une fois', () => {
    monter(html())
    const b = [...zone.querySelectorAll<HTMLButtonElement>('#vue [role="radio"]')]
    const changes: string[] = []
    zone.querySelector('#vue')!.addEventListener('change', (e) => changes.push((e.target as HTMLButtonElement).value))
    touche(b[1], 'ArrowRight')
    expect(document.activeElement).toBe(b[2])
    expect(valeurChoix(zone, 'vue')).toBe('total')
    touche(b[2], 'ArrowRight')
    expect(document.activeElement).toBe(b[0])
    touche(b[0], 'ArrowLeft')
    expect(valeurChoix(zone, 'vue')).toBe('total')
    touche(b[2], 'Home')
    expect(valeurChoix(zone, 'vue')).toBe('mois')
    touche(b[0], 'End')
    expect(valeurChoix(zone, 'vue')).toBe('total')
    touche(b[2], 'ArrowDown')
    expect(valeurChoix(zone, 'vue')).toBe('mois')
    expect(changes).toEqual(['total', 'mois', 'total', 'mois', 'total', 'mois'])
    expect(b.map((x) => x.tabIndex)).toEqual([0, -1, -1])
    // Clic sur le bouton déjà choisi : aucun événement.
    b[0].click()
    expect(changes).toHaveLength(6)
  })

  it('fixerChoix : change l’état sans événement', () => {
    monter(html())
    let n = 0
    zone.addEventListener('change', () => n++)
    fixerChoix(zone, 'vue', 'mois')
    expect(valeurChoix(zone, 'vue')).toBe('mois')
    expect(n).toBe(0)
  })
})

describe('liste radio (5 à 12 options, ou libellés longs)', () => {
  it('fieldset et legend, boutons radio natifs d’un même nom (flèches du navigateur), valeur lue et posée', () => {
    monter(radioListe({ id: 'annee', etiquette: 'Année', options: opts('2019', '2020', '2021', '2022', '2023'), valeur: '2021', aide: 'Année de versement.', message: true }))
    const f = zone.querySelector('#annee')!
    expect(f.tagName).toBe('FIELDSET')
    expect(f.querySelector(':scope > legend')?.textContent).toBe('Année')
    const r = [...f.querySelectorAll<HTMLInputElement>('input[type="radio"]')]
    expect(r).toHaveLength(5)
    expect(new Set(r.map((x) => x.name))).toEqual(new Set(['annee']))
    expect(r.every((x) => x.closest('label.choix-option'))).toBe(true)
    expect(valeurChoix(zone, 'annee')).toBe('2021')
    expect(f.getAttribute('aria-describedby')).toBe('annee-aide annee-msg')
    expect(zone.querySelector<HTMLElement>('#annee-msg')!.hidden).toBe(true)
    fixerChoix(zone, 'annee', '2023')
    expect(valeurChoix(zone, 'annee')).toBe('2023')
    // Libellés courts : grille de pastilles ; libellés longs : liste.
    expect(f.classList.contains('choix-liste-grille')).toBe(true)
    monter(radioListe({ id: 'tri', etiquette: 'Trier par', options: opts('Dernière collecte, la plus récente d’abord', 'Nom') }))
    expect(zone.querySelector('#tri')!.classList.contains('choix-liste-grille')).toBe(false)
    expect(valeurChoix(zone, 'tri')).toBe('')
  })
})

describe('liste avec recherche (plus de 12 options)', () => {
  const deps = [{ valeur: '', libelle: 'Choisir' }, ...['Ain', 'Aisne', 'Allier', 'Hautes-Alpes', 'Ardèche', 'Ariège', 'Aube', 'Loire', 'Loire-Atlantique', 'Haute-Loire', 'Loiret', 'Rhône', 'Savoie'].map((n, i) => ({ valeur: String(i + 1).padStart(2, '0'), libelle: n }))]

  it('champ relié à la liste native (id inchangé), libellés, compteur annoncé', () => {
    monter(listeRecherche({ id: 'dep', etiquette: 'Département', options: deps }))
    const filtre = zone.querySelector<HTMLInputElement>('#dep-filtre')!
    expect(filtre.hidden).toBe(false)
    expect(filtre.getAttribute('aria-controls')).toBe('dep')
    expect(zone.querySelector('label[for="dep-filtre"]')?.textContent).toContain('Département')
    expect(zone.querySelector('label[for="dep"]')?.textContent).toBe('Département')
    expect(zone.querySelector('#dep-compte')?.getAttribute('role')).toBe('status')
    filtre.value = 'loire'
    filtre.dispatchEvent(new Event('input', { bubbles: true }))
    const liste = zone.querySelector<HTMLSelectElement>('#dep')!
    expect([...liste.options].map((o) => o.textContent)).toEqual(['Choisir', 'Loire', 'Loire-Atlantique', 'Haute-Loire', 'Loiret'])
    expect(zone.querySelector('#dep-compte')?.textContent).toBe('4 propositions sur 13.')
    // Sans accents ni majuscules : « ardeche » trouve « Ardèche ».
    filtre.value = 'ARDECHE'
    filtre.dispatchEvent(new Event('input', { bubbles: true }))
    expect([...liste.options].map((o) => o.textContent)).toEqual(['Choisir', 'Ardèche'])
  })

  it('Entrée choisit la première option gardée (événement change) ; Échap vide le champ et rend toute la liste', () => {
    monter(listeRecherche({ id: 'dep', etiquette: 'Département', options: deps }))
    const filtre = zone.querySelector<HTMLInputElement>('#dep-filtre')!
    const liste = zone.querySelector<HTMLSelectElement>('#dep')!
    const vus: string[] = []
    liste.addEventListener('change', () => vus.push(liste.value))
    filtre.value = 'rhô'
    filtre.dispatchEvent(new Event('input', { bubbles: true }))
    touche(filtre, 'Enter')
    expect(vus).toEqual(['12'])
    expect(document.activeElement).toBe(liste)
    touche(filtre, 'Escape')
    expect(filtre.value).toBe('')
    expect(liste.options).toHaveLength(14)
    expect(liste.value).toBe('12')
  })

  it('groupes conservés ; remplirListe remet le filtre à zéro et ne montre le champ qu’au-delà de 12 options', () => {
    monter(listeRecherche({ id: 'p', etiquette: 'Prélèvement', options: [...opts('TVA', 'Tabac').map((o) => ({ ...o, groupe: 'Achats' })), ...opts('CSG', 'CRDS', 'Impôt sur le revenu').map((o) => ({ ...o, groupe: 'Fiche de paie' }))] }))
    const liste = zone.querySelector<HTMLSelectElement>('#p')!
    expect(zone.querySelector<HTMLInputElement>('#p-filtre')!.hidden).toBe(true)
    // L'option choisie (TVA, la première) reste toujours visible.
    expect(filtrerListe(liste, 'c')).toBe(4)
    expect([...liste.querySelectorAll('optgroup')].map((g) => g.getAttribute('label'))).toEqual(['Achats', 'Fiche de paie'])
    expect(filtrerListe(liste, 'csg')).toBe(2)
    expect([...liste.options].map((o) => o.value)).toEqual(['tva', 'csg'])
    remplirListe(liste, deps, '03')
    expect(liste.options).toHaveLength(14)
    expect(liste.value).toBe('03')
    expect(zone.querySelector<HTMLInputElement>('#p-filtre')!.hidden).toBe(false)
    remplirListe(liste, deps.slice(0, 4))
    expect(zone.querySelector<HTMLInputElement>('#p-filtre')!.hidden).toBe(true)
  })
})

describe('règle du nombre d’options : choix()', () => {
  const type = (html: string) => (/data-choix="(\w+)"/.exec(html) ?? [])[1]
  it(`<= ${SEUIL_SEGMENTE} options courtes : segmenté ; ${SEUIL_SEGMENTE + 1} à ${SEUIL_LISTE} : liste radio ; au-delà : recherche`, () => {
    const n = (k: number, l = 'Option') => Array.from({ length: k }, (_, i) => ({ valeur: String(i), libelle: `${l} ${i}` }))
    expect(type(choix({ id: 'a', etiquette: 'A', options: n(2) }))).toBe('segmente')
    expect(type(choix({ id: 'a', etiquette: 'A', options: n(4) }))).toBe('segmente')
    expect(type(choix({ id: 'a', etiquette: 'A', options: n(5) }))).toBe('liste')
    expect(type(choix({ id: 'a', etiquette: 'A', options: n(12) }))).toBe('liste')
    expect(type(choix({ id: 'a', etiquette: 'A', options: n(13) }))).toBe('recherche')
    // Libellé trop long pour un segment à 360 px : liste radio, même à 2 options.
    expect(type(choix({ id: 'a', etiquette: 'A', options: n(2, 'x'.repeat(LIBELLE_COURT)) }))).toBe('liste')
    expect(listeRecherche({ id: 'a', etiquette: 'A', options: [], optionsHtml: '<option>1</option>'.repeat(13) })).not.toContain('data-sans-filtre')
    expect(listeRecherche({ id: 'a', etiquette: 'A', options: [], optionsHtml: '<option>1</option>'.repeat(12) })).toContain('data-sans-filtre')
  })
})

describe('liens de choix, onglets, interrupteur, case, option détaillée', () => {
  it('liens : la page courante marquée aria-current="page", segmentés jusqu’à 4, en grille au-delà, en colonne si libellés longs', () => {
    monter(choixLiens({ etiquette: 'Millésime', liens: [2023, 2024, 2025].map((a) => ({ href: `#/x?a=${a}`, libelle: String(a), courant: a === 2024 })) }))
    const g = zone.querySelector('[data-choix="liens"]')!
    expect(g.getAttribute('role')).toBe('group')
    expect(g.getAttribute('aria-label')).toBe('Millésime')
    expect([...g.querySelectorAll('a')].map((a) => a.getAttribute('aria-current'))).toEqual([null, 'page', null])
    expect(g.classList.contains('choix-liens-liste')).toBe(false)
    monter(choixLiens({ etiquette: 'Année', liens: [1, 2, 3, 4, 5].map((a) => ({ href: `#/x?a=${a}`, libelle: String(a), courant: false })) }))
    expect(zone.querySelector('.choix-liens-liste')).not.toBeNull()
    monter(choixLiens({ etiquette: 'Impôt', liens: ['Impôt sur le revenu des ménages (y compris CSG)', 'TVA'].map((l) => ({ href: '#/x', libelle: l, courant: false })) }))
    expect(zone.querySelector('.choix-liens-colonne')).not.toBeNull()
  })

  it('onglets : aria-selected, un seul atteint par Tab, flèches, Début, Fin, panneaux masqués', () => {
    monter(
      listeOnglets({ etiquette: 'Collectivités', onglets: ['a', 'b', 'c'].map((x) => ({ id: `o-${x}`, libelle: x.toUpperCase(), panneau: `p-${x}` })) }) +
        ['a', 'b', 'c'].map((x, i) => `<section role="tabpanel" id="p-${x}" aria-labelledby="o-${x}"${i ? ' hidden' : ''}></section>`).join(''),
    )
    const o = [...zone.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
    const visibles = () => [...zone.querySelectorAll<HTMLElement>('[role="tabpanel"]')].filter((p) => !p.hidden).map((p) => p.id)
    expect(zone.querySelector('[role="tablist"]')?.getAttribute('aria-label')).toBe('Collectivités')
    expect(o.map((x) => x.getAttribute('aria-selected'))).toEqual(['true', 'false', 'false'])
    expect(o.map((x) => x.tabIndex)).toEqual([0, -1, -1])
    touche(o[0], 'ArrowRight')
    expect(visibles()).toEqual(['p-b'])
    expect(document.activeElement).toBe(o[1])
    touche(o[1], 'End')
    expect(visibles()).toEqual(['p-c'])
    touche(o[2], 'ArrowRight')
    expect(visibles()).toEqual(['p-a'])
    touche(o[0], 'ArrowLeft')
    expect(o.map((x) => x.getAttribute('aria-selected'))).toEqual(['false', 'false', 'true'])
    o[1].click()
    expect(visibles()).toEqual(['p-b'])
    expect(o.map((x) => x.tabIndex)).toEqual([-1, 0, -1])
  })

  it('interrupteur : case native de rôle switch, état coché lu par aria-checked implicite ; case à cocher d’un formulaire', () => {
    monter(interrupteur({ id: 'montants', libelle: 'Afficher mes montants', decritPar: 'aide' }) + caseACocher({ id: 'cadre', libelle: 'Statut cadre', coche: true }))
    const i = zone.querySelector<HTMLInputElement>('#montants')!
    expect(i.type).toBe('checkbox')
    expect(i.getAttribute('role')).toBe('switch')
    expect(i.checked).toBe(false)
    expect(i.closest('label')?.textContent).toBe('Afficher mes montants')
    expect(i.getAttribute('aria-describedby')).toBe('aide')
    const c = zone.querySelector<HTMLInputElement>('#cadre')!
    expect(c.checked).toBe(true)
    expect(c.getAttribute('role')).toBeNull()
    expect(c.closest('label.case')?.textContent?.trim()).toBe('Statut cadre')
  })

  it('option détaillée : bouton à état pressé, attributs conservés', () => {
    monter(optionRiche({ html: 'Assurance maladie', choisi: true, classe: 'suivre-choix', attributs: 'data-cle="maladie"' }))
    const b = zone.querySelector<HTMLButtonElement>('.choix-riche')!
    expect(b.getAttribute('aria-pressed')).toBe('true')
    expect(b.dataset.cle).toBe('maladie')
    expect(b.type).toBe('button')
  })

  it('champ avec propositions : flèche bas vers la première, flèches entre elles, Échap revient au champ', () => {
    monter('<input id="q" data-propositions="l"><ul id="l" data-propositions-de="q"><li><a href="#/a">A</a></li><li><a href="#/b">B</a></li></ul>')
    const q = zone.querySelector<HTMLInputElement>('#q')!
    const [a, b] = [...zone.querySelectorAll<HTMLAnchorElement>('a')]
    touche(q, 'ArrowDown')
    expect(document.activeElement).toBe(a)
    touche(a, 'ArrowDown')
    expect(document.activeElement).toBe(b)
    touche(b, 'ArrowDown')
    expect(document.activeElement).toBe(q)
    touche(q, 'ArrowUp')
    expect(document.activeElement).toBe(b)
    touche(b, 'Escape')
    expect(document.activeElement).toBe(q)
  })
})

describe('feuille de style des choix', () => {
  it('cibles de 44 px au moins : segments, liens, options radio, onglets, interrupteur, listes', () => {
    for (const sel of ['.choix-segment', '.choix-lien', 'label.choix-option', '.choix-onglet', 'label.choix-interrupteur', 'label.case']) expect(minHauteur(sel), sel).toBeGreaterThanOrEqual(44)
    expect(/min-width:\s*44px/.test(regle('.choix-segment'))).toBe(true)
    // Listes natives et champs : 3,25rem (52 px).
    expect(minHauteur('select')).toBeGreaterThanOrEqual(44)
  })

  it('état choisi visible sans la couleur : coche dessinée, graisse, contour, trait sous l’onglet, curseur déplacé', () => {
    const coche = regle(".choix-segment[aria-checked='true']::before")
    expect(coche).toMatch(/content: ''/)
    expect(coche).toMatch(/border-width: 0 0\.1875em 0\.1875em 0/)
    expect(regle(".choix-lien[aria-current='page']::before")).toBe(coche)
    expect(regle(".choix-riche[aria-pressed='true']::before")).toBe(coche)
    expect(regle(".choix-segment[aria-checked='true']")).toMatch(/font-weight: 800/)
    expect(regle('label.choix-option:has(input:checked)')).toMatch(/font-weight: 700/)
    expect(regle('label.choix-option:has(input:checked)')).toMatch(/border-color: var\(--contour\)/)
    expect(regle(".choix-onglet[aria-selected='true']")).toMatch(/text-decoration: underline/)
    expect(regle('.choix-interrupteur input:checked + .choix-piste::after')).toMatch(/right: 0\.28rem/)
    expect(regle('.choix-interrupteur input:focus-visible + .choix-piste')).toMatch(/outline: 3px solid/)
  })

  it('aucun reste de l’ancienne réglette (.bascule) ni d’état porté par aria-pressed hors composant', () => {
    expect(css).not.toMatch(/\.bascule\b/)
    expect(css).not.toMatch(/button\[aria-pressed/)
  })
})

describe('garde-fou : tout choix passe par composants/choix.ts', () => {
  function fichiers(d: string): string[] {
    return readdirSync(d).flatMap((f) => {
      const p = join(d, f)
      return statSync(p).isDirectory() ? fichiers(p) : /\.ts$/.test(f) ? [p] : []
    })
  }
  // Marques d'un choix écrit à la main : liste native, bouton radio, case, état pressé ou coché, onglet, réglette.
  const INTERDITS: [string, RegExp][] = [
    ['liste native <select>', /<select\b/],
    ['bouton radio', /type=["']radio["']|type = ['"]radio['"]/],
    ['case à cocher', /type=["']checkbox["']|type = ['"]checkbox['"]/],
    ['état aria-pressed', /aria-pressed/],
    ['état aria-checked', /aria-checked/],
    ['rôle radio, radiogroup, tab, tablist ou switch', /role=["'](radio|radiogroup|tab|tablist|switch)["']/],
    ['ancienne réglette .bascule', /class="[^"]*\bbascule\b/],
    ['élément de choix créé par script', /createElement\(['"](select|option)['"]\)/],
  ]

  it('aucun écran ni composant n’écrit un choix à la main (seul composants/choix.ts le fait)', () => {
    const fautes: string[] = []
    for (const f of fichiers(SRC)) {
      if (f.endsWith(join('composants', 'choix.ts'))) continue
      const t = readFileSync(f, 'utf8')
      for (const [nom, re] of INTERDITS) if (re.test(t)) fautes.push(`${f.replace(SRC, 'src')} : ${nom}`)
    }
    expect(fautes, 'utiliser segmente, radioListe, listeRecherche, choix, choixLiens, listeOnglets, interrupteur, caseACocher ou optionRiche').toEqual([])
  })

  it('le garde-fou détecte bien un choix écrit à la main', () => {
    const faux = ['<select id="x"></select>', '<input type="radio" name="a">', '<button aria-pressed="true">', '<div role="tablist">', '<div class="bascule">']
    for (const t of faux) expect(INTERDITS.some(([, re]) => re.test(t)), t).toBe(true)
  })
})

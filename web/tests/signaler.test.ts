// @vitest-environment happy-dom
// Lien « Signaler une erreur sur cette page » : ticket GitHub public pré-rempli, sans donnée personnelle.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { blocSignaler, DEPOT, GABARIT, lienTicket, MAX_FICHIERS, SITE_DEFAUT, texteFichiers } from '../src/composants/signaler'
import { monterPage } from './aide-dom'

const params = (url: string) => new URL(url).searchParams
let main: HTMLElement

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('lien de ticket', () => {
  it('pointe vers le gabarit du dépôt public, avec la page et les fichiers affichés', () => {
    const url = lienTicket({
      titre: 'Budget de l’État',
      adresse: '#/explorer/etat?m=lfi2025',
      fichiers: [{ chemin: 'arbre_lfi2025/racine.json', millesime: 'LFI 2025' }, { chemin: 'meta.json', millesime: null }, { chemin: 'dette/x.json', absent: true }],
    })
    expect(url.startsWith(`${DEPOT}/issues/new?`)).toBe(true)
    expect(DEPOT).toBe('https://github.com/MoonEyes/Ou-vont-mes-impots')
    const p = params(url)
    expect(p.get('template')).toBe(GABARIT)
    expect(p.get('title')).toBe('Erreur sur la page « Budget de l’État »')
    expect(p.get('page')).toBe(`${SITE_DEFAUT}explorer/etat/?m=lfi2025`)
    expect(p.get('fichiers')).toBe('- data/arbre_lfi2025/racine.json (millésime : LFI 2025)\n- data/meta.json\n- data/dette/x.json (fichier non disponible)')
    // Rien d'autre que ces quatre champs : aucune saisie, aucune donnée de la personne.
    expect([...p.keys()]).toEqual(['template', 'title', 'page', 'fichiers'])
  })

  it('page sans donnée et liste longue raccourcie', () => {
    expect(texteFichiers([])).toBe('Aucun fichier de données lu par cette page.')
    const beaucoup = Array.from({ length: 300 }, (_, i) => ({ chemin: `local/communes/commune-tres-longue-${i}.json`, millesime: '2024' }))
    const t = texteFichiers(beaucoup)
    expect(t.split('\n')).toHaveLength(MAX_FICHIERS + 1)
    expect(t.endsWith(`- et ${300 - MAX_FICHIERS} autres fichiers`)).toBe(true)
    const url = lienTicket({ titre: 'Ta commune', adresse: '#/local', fichiers: beaucoup })
    expect(url.length).toBeLessThanOrEqual(7000)
    expect(params(url).get('fichiers')).toMatch(/- et \d+ autres fichiers$/)
  })

  it('bloc : lien, avertissement de ticket public, texte échappé, aucun formulaire', () => {
    const zone = document.createElement('div')
    zone.innerHTML = blocSignaler({ titre: '<b>x</b>', adresse: '#/' })
    const a = zone.querySelector('a.signaler-lien')!
    expect(a.textContent).toBe('Signaler une erreur sur cette page')
    expect(params(a.getAttribute('href')!).get('title')).toBe('Erreur sur la page « <b>x</b> »')
    expect(zone.querySelector('b')).toBeNull()
    expect(zone.textContent).toContain('Ce ticket est public : n’y écris aucune donnée personnelle')
    expect(zone.querySelector('form, input, textarea')).toBeNull()
    expect(zone.textContent).not.toContain('—')
  })
})

describe('sur les pages', () => {
  it('chaque page porte le lien, avec les fichiers lus et leur millésime', async () => {
    location.hash = '#/explorer/etat'
    await afficher(ROUTES, main, '#/explorer/etat')
    const liens = main.querySelectorAll<HTMLAnchorElement>('.signaler a.signaler-lien')
    expect(liens).toHaveLength(1)
    const p = params(liens[0].href)
    expect(p.get('page')).toBe(`${SITE_DEFAUT}explorer/etat/`)
    const racine = JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/data/arbre/racine.json'), 'utf8'))
    expect(p.get('fichiers')).toContain(`- data/arbre/racine.json (millésime : ${racine.millesime})`)
    expect(p.get('fichiers')).not.toContain('_manifeste.json')
  })

  it('le journal repart de zéro à chaque page, et la page introuvable a aussi son lien', async () => {
    location.hash = '#/methode'
    await afficher(ROUTES, main, '#/methode')
    const f = params(main.querySelector<HTMLAnchorElement>('.signaler-lien')!.href).get('fichiers')!
    expect(f).not.toContain('arbre/racine.json')
    location.hash = '#/nulle-part'
    await afficher(ROUTES, main, '#/nulle-part')
    expect(main.querySelectorAll('.signaler-lien')).toHaveLength(1)
  })

  it('toutes les routes sans paramètre affichent un seul lien', async () => {
    for (const r of ROUTES) {
      location.hash = '#' + r.chemin
      await afficher(ROUTES, main, '#' + r.chemin)
      // Page qui renvoie ailleurs sans saisie (résultat du calcul) : c'est la page d'arrivée qui porte le lien.
      if (location.hash !== '#' + r.chemin) continue
      expect(main.querySelectorAll('.signaler-lien').length, r.chemin).toBe(1)
    }
  }, 120000)
})

describe('gabarit de ticket', () => {
  const yml = readFileSync(join(process.cwd(), '..', '.github', 'ISSUE_TEMPLATE', 'erreur-donnee.yml'), 'utf8')
  it('champs pré-remplis par le lien, ce qui est faux et la source exigés', () => {
    const ids = [...yml.matchAll(/^\s+id: (\S+)$/gm)].map((m) => m[1])
    expect(ids).toEqual(['page', 'fichiers', 'constat', 'source', 'attendu', 'confidentialite'])
    for (const id of ['constat', 'source']) expect(new RegExp(`id: ${id}\\n[\\s\\S]*?required: true`).test(yml)).toBe(true)
  })
  it('avertit que le ticket est public et ne demande aucune donnée personnelle', () => {
    expect(yml).toContain('**Ce ticket est public**')
    const libelles = [...yml.matchAll(/^\s+label: (.+)$/gm)].map((m) => m[1].toLowerCase())
    for (const mot of ['salaire', 'courriel', 'e-mail', 'téléphone', 'adresse postale', 'revenu']) expect(libelles.filter((l) => l.includes(mot) && !l.includes('aucune'))).toEqual([])
    expect(yml).not.toContain('—')
  })
})

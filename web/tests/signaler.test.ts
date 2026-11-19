// @vitest-environment happy-dom
// Bloc « Signaler une erreur sur cette page » : adresse de contact dédiée en texte simple et référence à copier
// (page, fichiers affichés), sans lien, sans envoi, sans donnée personnelle. Décision du 19/11/2026 : aucune page ne
// renvoie vers les tickets ni vers le compte ou le dépôt GitHub.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { blocSignaler, CONTACT, MAX_FICHIERS, SITE_DEFAUT, texteFichiers, texteReference } from '../src/composants/signaler'
import { monterPage } from './aide-dom'

let main: HTMLElement
const reference = () => main.querySelector<HTMLTextAreaElement>('.signaler-reference')?.value ?? ''

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('référence à copier', () => {
  it('adresse de la page, titre et fichiers affichés avec leur millésime', () => {
    const t = texteReference({
      titre: 'Budget de l’État',
      adresse: '#/explorer/etat?m=lfi2025',
      fichiers: [{ chemin: 'arbre_lfi2025/racine.json', millesime: 'LFI 2025' }, { chemin: 'meta.json', millesime: null }, { chemin: 'dette/x.json', absent: true }],
    })
    expect(t).toBe(
      `Page : ${SITE_DEFAUT}explorer/etat/?m=lfi2025\nFichiers de données affichés :\n- data/arbre_lfi2025/racine.json (millésime : LFI 2025)\n- data/meta.json\n- data/dette/x.json (fichier non disponible)`,
    )
  })

  it('page sans donnée et liste longue raccourcie', () => {
    expect(texteFichiers([])).toBe('Aucun fichier de données lu par cette page.')
    const beaucoup = Array.from({ length: 300 }, (_, i) => ({ chemin: `local/communes/commune-tres-longue-${i}.json`, millesime: '2024' }))
    const t = texteFichiers(beaucoup)
    expect(t.split('\n')).toHaveLength(MAX_FICHIERS + 1)
    expect(t.endsWith(`- et ${300 - MAX_FICHIERS} autres fichiers`)).toBe(true)
  })

  it('bloc : adresse dédiée en texte simple, aucun lien ni envoi, référence en lecture seule échappée', () => {
    const zone = document.createElement('div')
    zone.innerHTML = blocSignaler({ titre: 'x', adresse: '#/?q=<b>x</b>' })
    expect(CONTACT).toBe('proton.me.easel124@passinbox.com')
    expect(zone.querySelector('.signaler-contact')?.textContent).toBe(CONTACT)
    expect(zone.querySelector('a, form, input, button, select')).toBeNull()
    const ref = zone.querySelector<HTMLTextAreaElement>('textarea.signaler-reference')!
    expect(ref.hasAttribute('readonly')).toBe(true)
    expect(ref.getAttribute('aria-label')).toBeTruthy()
    // Rempli par majSignaler (valeur du champ) : rien de la référence dans le texte de la page.
    expect(ref.textContent).toBe('')
    expect(zone.querySelector('b')).toBeNull()
    expect(zone.textContent).toContain('Signaler une erreur sur cette page')
    // Replié : un lien discret (résumé d'un <details>), la référence n'apparaît qu'à l'ouverture.
    expect(zone.querySelector('details > summary')?.textContent).toBe('Signaler une erreur sur cette page')
    expect(zone.querySelector('details')?.hasAttribute('open')).toBe(false)
    expect(zone.querySelector('details .signaler-reference')).not.toBeNull()
    expect(zone.textContent).toContain('N’ajoute aucune donnée personnelle inutile')
    expect(zone.innerHTML).not.toMatch(/github\.com|\/issues|ticket|mailto:/i)
    expect(zone.textContent).not.toContain('—')
  })
})

describe('sur les pages', () => {
  it('chaque page porte la référence, avec les fichiers lus et leur millésime', async () => {
    location.hash = '#/explorer/etat'
    await afficher(ROUTES, main, '#/explorer/etat')
    expect(main.querySelectorAll('.signaler .signaler-reference')).toHaveLength(1)
    expect(reference()).toContain(`Page : ${SITE_DEFAUT}explorer/etat/`)
    const racine = JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/data/arbre/racine.json'), 'utf8'))
    expect(reference()).toContain(`- data/arbre/racine.json (millésime : ${racine.millesime})`)
    expect(reference()).not.toContain('_manifeste.json')
  })

  it('le journal repart de zéro à chaque page, et la page introuvable a aussi son bloc', async () => {
    location.hash = '#/methode'
    await afficher(ROUTES, main, '#/methode')
    expect(reference()).not.toContain('arbre/racine.json')
    location.hash = '#/nulle-part'
    await afficher(ROUTES, main, '#/nulle-part')
    expect(main.querySelectorAll('.signaler-reference')).toHaveLength(1)
  })

  it('toutes les routes : un seul bloc, et aucun renvoi vers GitHub (dépôt, compte ou tickets)', async () => {
    const vues = ROUTES.map((r) => '#' + r.chemin).concat(['#/decisions/votes?p=141', '#/local/commune?insee=69123', '#/nulle-part'])
    for (const f of vues) {
      location.hash = f
      await afficher(ROUTES, main, f)
      const page = document.body.innerHTML
      expect(page, f).not.toContain('github.com/MoonEyes')
      expect(page, f).not.toContain('/issues')
      expect(document.body.querySelector('a[href*="github.com"]'), f).toBeNull()
      // Page qui renvoie ailleurs sans saisie (résultat du calcul) : c'est la page d'arrivée qui porte le bloc.
      if (location.hash !== f) continue
      // Accueil : pas de bloc (audit design du 19/11, problème 12).
      expect(main.querySelectorAll('.signaler-reference').length, f).toBe(f === '#/' ? 0 : 1)
    }
  }, 180000)
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

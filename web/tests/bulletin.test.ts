// @vitest-environment happy-dom
// Écran « Ta fiche de paie expliquée » (/calcul/bulletin) : exemple du site sans saisie, saisie de la session (cadre,
// couple), montants comparés au moteur lui-même (jamais recopiés), organisme et lien « où va cet argent » pour chaque
// ligne, ce qui dépend de l'entreprise signalé, bascules, accessibilité, lexique neutre et liens tous résolus.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { agregatsPersonne, calculer } from '../src/calcul/moteur'
import { DESTINATAIRES } from '../src/calcul/destinataires'
import type { Prelevement, Profil, ResultatOk } from '../src/calcul/types'
import { picto } from '../src/composants/pictos'
import { fichesDe, montantPas, PROFIL_EXEMPLE } from '../src/ecrans/bulletin'
import { session } from '../src/etat'
import { afficher, lien } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { attendreQue, monterPage, requetes } from './aide-dom'

const RACINE = process.cwd()
const AFFECTATION = JSON.parse(readFileSync(join(RACINE, 'tests/fixtures/data/prelevements/affectation.json'), 'utf8'))
const nf0 = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 })
const eurFr = (x: number) => `${nf0.format(Math.round(x))} €`.replace(/\s+/g, ' ')
const pctFr = (x: number) => `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(x)} %`.replace(/\s+/g, ' ')
const net = (t: string | null | undefined) => (t ?? '').replace(/\s+/g, ' ').trim()

let main: HTMLElement
const ecran = async (fragment = '#/calcul/bulletin') => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => net(main.textContent)
const lignes = () => Array.from(main.querySelectorAll<HTMLLIElement>('#bulletin-zone ul.lignes > li'))
const ligne = (nom: string) => {
  const li = lignes().find((x) => net(x.querySelector('span')?.textContent) === nom)
  if (!li) throw new Error(`ligne absente : ${nom}`)
  return li
}
/** Montant tel qu'il se lit à l'écran : sans le texte réservé aux lecteurs d'écran (« par mois »), sauts de ligne en espaces. */
const montant = (li: Element) => {
  const c = li.querySelector('.montant')!.cloneNode(true) as HTMLElement
  c.querySelectorAll('.visuellement-cache').forEach((x) => x.remove())
  c.querySelectorAll('br').forEach((x) => x.replaceWith(document.createTextNode(' ')))
  return net(c.textContent)
}
const moteur = (r: ResultatOk, id: string) => r.prelevements.find((l) => l.id === id)!.montant_annuel_eur.central

const salarie = (net: number, extra: Partial<Profil['personnes'][number]> = {}): Profil['personnes'][number] => ({ ...PROFIL_EXEMPLE.personnes[0], salaire_net_avant_impot_mensuel: net, ...extra })
const calcul = (p: Profil) => {
  const r = calculer(p, { affectation: AFFECTATION })
  if (r.statut !== 'ok') throw new Error(r.erreur.message)
  return r
}

let exemple: ResultatOk

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
  exemple = calcul(PROFIL_EXEMPLE)
}, 120000)

describe('fiche de paie expliquée', () => {
  it('route : enfant de /calcul, voisins existants, picto et famille existants', () => {
    const r = ROUTES.find((x) => x.chemin === '/calcul/bulletin')!
    expect(r).toBeTruthy()
    expect(r.parent).toBe('/calcul')
    expect(r.titre).toBe('Ta fiche de paie expliquée')
    expect(r.sansIndex).toBeFalsy()
    expect(r.voisins!.length).toBeGreaterThanOrEqual(1)
    expect(r.voisins!.length).toBeLessThanOrEqual(3)
    for (const v of r.voisins!) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    expect(picto(r.picto!)).not.toBe('')
    expect(['secu', 'etat', 'collectivites', 'ue', 'dette', 'niches', 'operateurs', 'prestations']).toContain(r.famille)
  })

  it('sans saisie : la fiche de l’exemple du site, calculée sur l’appareil par le moteur', async () => {
    session.resultat = null
    session.profil = null
    await ecran()
    expect(net(main.querySelector('h1')?.textContent)).toBe('Ta fiche de paie expliquée')
    expect(Array.from(main.querySelectorAll('nav.fil-ariane a')).map((a) => a.textContent)).toEqual(['Accueil', 'Mon salaire', 'Fiche de paie'])
    expect(texte()).toContain(`Exemple du site : ${eurFr(PROFIL_EXEMPLE.personnes[0].salaire_net_avant_impot_mensuel!)} net avant impôt par mois`)
    expect(main.querySelector('a[href="#/calcul"]')).not.toBeNull()
    expect(main.querySelector('.erreur')).toBeNull()
    expect(texte()).not.toContain('Chargement')
    // Les montants affichés sont ceux du moteur, ramenés au mois.
    const [f] = fichesDe(exemple, PROFIL_EXEMPLE)
    expect(f.net).toBeCloseTo(PROFIL_EXEMPLE.personnes[0].salaire_net_avant_impot_mensuel! * 12, 0)
    expect(montant(ligne('Montant brut'))).toBe(eurFr(f.brut / 12))
    expect(montant(ligne('Montant net à payer avant impôt sur le revenu'))).toBe(eurFr(f.net / 12))
    expect(montant(ligne('Sécurité sociale vieillesse plafonnée'))).toBe(`ta part ${eurFr(moteur(exemple, 'vieillesse_plafonnee_salarie') / 12)} employeur ${eurFr(moteur(exemple, 'vieillesse_plafonnee_employeur') / 12)}`)
    expect(montant(ligne('CRDS'))).toBe(`ta part ${eurFr(moteur(exemple, 'crds') / 12)}`)
    expect(net(main.querySelector('.surligne')?.textContent)).toBe(eurFr((f.net - montantPas(f)) / 12))
    expect(montant(ligne('Montant net à payer'))).toBe(eurFr((f.net - montantPas(f)) / 12))
  }, 120000)

  it('prélèvement à la source : taux du foyer = impôt du moteur ÷ net imposable, arrondi au dixième de point', () => {
    const [f] = fichesDe(exemple, PROFIL_EXEMPLE)
    const ir = moteur(exemple, 'impot_revenu')
    expect(ir).toBe(1004) // cas C04, OpenFisca : 1 004 €
    // Net imposable du site = salaire imposable de modele-social (net + CSG non déductible + CRDS).
    expect(Math.abs(f.imposable - agregatsPersonne(PROFIL_EXEMPLE, 'declarant1').salaire_imposable)).toBeLessThan(1)
    expect(f.pas!.base).toBeCloseTo(f.imposable, 2)
    expect(f.pas!.taux).toBe(Math.round((ir / f.imposable) * 1000) / 1000)
    expect(Math.abs(montantPas(f) - ir)).toBeLessThan(0.0005 * f.imposable + 1)
    const li = ligne('Impôt sur le revenu prélevé à la source')
    expect(montant(li)).toBe(`− ${eurFr(montantPas(f) / 12)}`)
    expect(net(li.textContent)).toContain(`Taux de ${pctFr(f.pas!.taux * 100)}`)
    expect(net(li.textContent)).toContain(`impôt calculé de ${eurFr(ir)}`)
    expect(li.querySelector('a[href="#/explorer/etat"]')).not.toBeNull()
  })

  it('chaque ligne calculée : explication, organisme qui la reçoit, page qui montre où va cet argent', () => {
    const calculees = lignes().filter((li) => montant(li) !== 'non calculé')
    expect(calculees.length).toBeGreaterThan(15)
    for (const li of calculees) expect(net(li.querySelector('.dest')?.textContent).length, net(li.textContent)).toBeGreaterThan(50)
    // Toutes les lignes venues du moteur : chacune a son organisme et sa page « où va cet argent ».
    const duMoteur = Array.from(main.querySelectorAll('#bulletin-zone li[data-ligne="moteur"]'))
    const attendues = fichesDe(exemple, PROFIL_EXEMPLE)[0].lignes.length
    expect(duMoteur.length).toBeGreaterThan(12)
    expect(duMoteur.length).toBeLessThanOrEqual(attendues)
    for (const li of duMoteur) {
      const t = net(li.querySelector('.dest')?.textContent)
      expect(t, t).toMatch(/Reçu par : |Diminue ce que reçoit : /)
      expect(t, t).toMatch(/Où va cet argent : |Où ce montant est suivi : /)
    }
    // Retraite de base : Assurance retraite, bloc « retraite de base » de la page Sécurité sociale.
    const plafonnee = ligne('Sécurité sociale vieillesse plafonnée')
    expect(net(plafonnee.textContent)).toContain('Reçu par : Assurance retraite (branche vieillesse) Sécurité sociale.')
    expect(plafonnee.querySelector(`a[href="${lien('/explorer/secu', { id: 'robss/vieillesse' })}"]`)).not.toBeNull()
    // CSG : parts publiées (affectation.json), un lien par branche qui la reçoit.
    const csg = ligne('CSG déductible de l’impôt sur le revenu')
    const parts = AFFECTATION.prelevements.csg_activite.ventilation as { destinataire: string; part: number }[]
    for (const p of parts) expect(net(csg.textContent)).toContain(`${DESTINATAIRES[p.destinataire as keyof typeof DESTINATAIRES].nom} ${Math.round(p.part * 100)} %`)
    for (const id of ['robss/maladie', 'robss/autonomie', 'unedic', 'robss/famille', 'cades']) expect(csg.querySelector(`a[href="${lien('/explorer/secu', { id })}"]`), id).not.toBeNull()
    expect(net(csg.textContent)).toContain('Contribution sociale généralisée (6,8 %), prélevée sur 98,25 % de ton salaire brut')
    expect(ligne('CRDS').querySelector(`a[href="${lien('/explorer/secu', { id: 'cades' })}"]`)).not.toBeNull()
    expect(ligne('Retraite complémentaire (Agirc-Arrco)').querySelector(`a[href="${lien('/explorer/secu', { id: 'complementaires/agirc_arrco' })}"]`)).not.toBeNull()
    expect(ligne('Versement mobilité').querySelector('a[href="#/explorer/collectivites"]')).not.toBeNull()
    expect(ligne('Taxe d’apprentissage').querySelector(`a[href="${lien('/explorer/operateurs', { p: '103' })}"]`)).not.toBeNull()
    // Organisme dont les comptes ne sont pas dans les données du site : la phrase le dit.
    expect(net(ligne('Garantie des salaires (AGS)').textContent)).toContain('les comptes de cet organisme ne sont pas dans les données du site')
    // Réduction générale : signe moins, et la page qui suit les exonérations de cotisations.
    const reduction = ligne('Réduction générale des cotisations patronales')
    expect(reduction.classList.contains('reduction')).toBe(true)
    expect(montant(reduction)).toMatch(/^employeur − \d/)
    expect(montant(reduction)).not.toContain('-') // signe moins typographique, jamais « -0 »
    expect(reduction.querySelector('a[href="#/explorer/niches"]')).not.toBeNull()
  })

  it('ce qui dépend de l’entreprise : fourchette ou « non calculé », jamais un montant inventé', () => {
    const atmp = ligne('Accidents du travail et maladies professionnelles')
    expect(net(atmp.textContent)).toContain('Approché')
    const f = exemple.prelevements.find((l) => l.id === 'atmp')!.montant_annuel_eur
    expect(montant(atmp)).toBe(`employeur ${nf0.format(Math.round(f.bas / 12))} à ${eurFr(f.haut / 12)}`.replace(/\s+/g, ' '))
    for (const nom of ['Complémentaire santé obligatoire (mutuelle d’entreprise)', 'Prévoyance (incapacité, invalidité, décès)', 'Retraite supplémentaire', 'Cotisations statutaires ou conventionnelles', 'Contribution au dialogue social', 'Montant net social', 'Remboursements et déductions diverses'])
      expect(montant(ligne(nom)), nom).toBe('non calculé')
    const section = net(main.querySelector('#bulletin-variable')?.textContent)
    for (const t of ['Taux accidents du travail.', 'Mutuelle (complémentaire santé).', 'Prévoyance.', 'Retraite complémentaire selon ton statut.', 'Pour un cadre, la fiche porte en plus l’Apec'])
      expect(section, t).toContain(t)
    expect(section).toContain(`la cotisation va ici de ${nf0.format(Math.round(f.bas / 12))} à ${eurFr(f.haut / 12)} par mois`.replace(/\s+/g, ' '))
    expect(net(main.querySelector('#bulletin-variable details')?.textContent)).toContain('Bas : taux accidents du travail 0,45 %')
    expect(texte()).not.toMatch(/AT-MP/)
    // Non cadre : pas de ligne Apec.
    expect(lignes().some((li) => net(li.querySelector('span')?.textContent) === 'Apec')).toBe(false)
  })

  it('chiffre clé : un seul surligneur, dans une carte qui dit « sur 100 € de salaire brut », parts qui font 100', () => {
    expect(main.querySelectorAll('.surligne')).toHaveLength(1)
    const cle = main.querySelector('.surligne')!.closest('[data-cle]')!
    expect(net(cle.textContent)).toMatch(/Sur 100 € de salaire brut : \d+ € de cotisations sociales, \d+ € de CSG et de CRDS, \d+ € d’impôt sur le revenu prélevé à la source, et \d+ € te sont versés\./)
    const parts = [...net(cle.querySelector('.recap-sur100')?.textContent).matchAll(/(\d+) €/g)].map((m) => Number(m[1]))
    expect(parts[0]).toBe(100)
    expect(parts.slice(1).reduce((a, b) => a + b, 0)).toBe(100)
    expect(cle.querySelector('.source')?.textContent).toContain('modele-social')
  })

  it('bascule : montants par mois ou sur un an, état annoncé par aria-pressed', () => {
    const [f] = fichesDe(exemple, PROFIL_EXEMPLE)
    const an = main.querySelector<HTMLButtonElement>('button[data-periode="an"]')!
    expect(main.querySelector('button[data-periode="mois"]')?.getAttribute('aria-pressed')).toBe('true')
    expect(an.getAttribute('aria-pressed')).toBe('false')
    an.click()
    expect(an.getAttribute('aria-pressed')).toBe('true')
    expect(main.querySelector('button[data-periode="mois"]')?.getAttribute('aria-pressed')).toBe('false')
    expect(net(main.querySelector('.surligne')?.textContent)).toBe(eurFr(f.net - montantPas(f)))
    expect(montant(ligne('Montant net à payer avant impôt sur le revenu'))).toBe(eurFr(f.net))
    expect(net(main.querySelector('#titre-bulletin-net')?.textContent)).toBe('Montant net à payer, sur un an')
    expect(main.querySelector('caption')?.textContent).toContain('sur un an')
    main.querySelector<HTMLButtonElement>('button[data-periode="mois"]')!.click()
    expect(net(main.querySelector('#titre-bulletin-net')?.textContent)).toBe('Montant net à payer, par mois')
  })

  it('accessibilité : titres hiérarchisés, tableau avec légende et en-têtes, bascules nommées', () => {
    const niveaux = Array.from(main.querySelectorAll('h1, h2, h3')).map((x) => Number(x.tagName[1]))
    expect(niveaux.filter((n) => n === 1)).toHaveLength(1)
    for (let i = 1; i < niveaux.length; i++) expect(niveaux[i], `titre ${i}`).toBeLessThanOrEqual(niveaux[i - 1] + 1)
    const table = main.querySelector('#bulletin-zone table')!
    expect(table.querySelector('caption')?.textContent).toMatch(/Ta fiche de paie par mois, en euros arrondis, revenus \d{4}/)
    expect(Array.from(table.querySelectorAll('thead th')).map((x) => x.getAttribute('scope'))).toEqual(['col', 'col', 'col'])
    expect(table.querySelectorAll('tbody th[scope="rowgroup"]').length).toBeGreaterThan(5)
    expect(table.querySelectorAll('tbody th[scope="row"]').length).toBeGreaterThan(15)
    expect((table.closest('.tableau-defile') as HTMLElement).tabIndex).toBe(0)
    expect(table.closest('.tableau-defile')?.getAttribute('role')).toBe('region')
    for (const g of Array.from(main.querySelectorAll('#bulletin-reglages [role="group"]'))) expect(g.getAttribute('aria-label')).toBeTruthy()
    for (const b of Array.from(main.querySelectorAll('#bulletin-reglages button'))) expect(['true', 'false']).toContain(b.getAttribute('aria-pressed'))
  })

  it('saisie de la session : cadre à 3 000 €, ligne Apec, lien vers ce que tu verses en un an', async () => {
    const profil: Profil = { ...PROFIL_EXEMPLE, personnes: [salarie(3000, { cadre: true })] }
    const r = calcul(profil)
    session.profil = profil
    session.resultat = r
    await ecran()
    expect(texte()).toContain(`Calculée pour ta saisie : ${eurFr(3000)} net avant impôt par mois, cadre`)
    expect(texte()).not.toContain('Exemple du site')
    expect(montant(ligne('Montant net à payer avant impôt sur le revenu'))).toBe(eurFr(3000))
    const apec = ligne('Apec')
    expect(montant(apec)).toBe(`ta part ${eurFr(moteur(r, 'apec_salarie') / 12)} employeur ${eurFr(moteur(r, 'apec_employeur') / 12)}`)
    expect(net(apec.textContent)).toContain('les comptes de cet organisme ne sont pas dans les données du site')
    expect(net(main.querySelector('#bulletin-variable')?.textContent)).toContain('Tu as indiqué le statut cadre')
    expect(main.querySelector('a[href="#/calcul/resultat"]')).not.toBeNull()
  }, 120000)

  it('couple marié : une fiche par personne, même taux de prélèvement (celui du foyer)', async () => {
    const profil: Profil = { ...PROFIL_EXEMPLE, foyer: { situation: 'couple_marie_pacse', enfants: [] }, personnes: [salarie(2500), salarie(1800, { role: 'declarant2' })] }
    const r = calcul(profil)
    session.profil = profil
    session.resultat = r
    const [f1, f2] = fichesDe(r, profil)
    expect(f1.pas!.taux).toBe(f2.pas!.taux)
    expect(f1.pas!.base).toBeCloseTo(f1.imposable + f2.imposable, 2)
    expect(f1.pas!.taux).toBe(Math.round((moteur(r, 'impot_revenu') / (f1.imposable + f2.imposable)) * 1000) / 1000)
    await ecran()
    const personnes = Array.from(main.querySelectorAll<HTMLButtonElement>('button[data-personne]'))
    expect(personnes.map((b) => b.textContent)).toEqual(['Toi', 'Ton ou ta conjoint·e'])
    expect(montant(ligne('Montant net à payer avant impôt sur le revenu'))).toBe(eurFr(2500))
    personnes[1].click()
    expect(personnes[1].getAttribute('aria-pressed')).toBe('true')
    expect(montant(ligne('Montant net à payer avant impôt sur le revenu'))).toBe(eurFr(1800))
    expect(montant(ligne('Montant brut'))).toBe(eurFr(f2.brut / 12))
    expect(texte()).toContain(`Calculée pour ta saisie : ${eurFr(2500)} et ${eurFr(1800)} net avant impôt par mois`)
  }, 120000)

  it('union libre : deux foyers, chacun son impôt et son taux', () => {
    const profil: Profil = { ...PROFIL_EXEMPLE, foyer: { situation: 'couple_union_libre', enfants: [] }, personnes: [salarie(2500), salarie(1800, { role: 'declarant2' })] }
    const r = calcul(profil)
    const [f1, f2] = fichesDe(r, profil)
    expect(f1.pas!.impot).toBe(moteur(r, 'impot_revenu'))
    expect(f2.pas!.impot).toBe(moteur(r, 'impot_revenu_declarant2'))
    expect(f1.pas!.base).toBeCloseTo(f1.imposable, 2)
    expect(f2.pas!.base).toBeCloseTo(f2.imposable, 2)
  }, 120000)

  it('profils étendus : revenu d’indépendant dans le foyer, taux non reconstitué et dit ; pension seule, retour à l’exemple', async () => {
    const etendu = { ...exemple, entree: { personnes: [{ ...exemple.entree.personnes[0], profil: 'salarie_prive' }, { role: 'declarant2', profil: 'micro_entrepreneur', salaire_net_avant_impot_annuel: 15000, salaire_brut_annuel_estime: { bas: 20000, central: 20000, haut: 20000 }, revenu_imposable_annuel: 20000 }] } } as unknown as ResultatOk
    const [f] = fichesDe(etendu, null)
    expect(fichesDe(etendu, null)).toHaveLength(1)
    expect(f.pas).toBeNull()
    expect(f.sansPas).toContain('revenus d’indépendant')
    session.profil = null
    session.resultat = { ...exemple, prelevements: [], entree: { personnes: [{ role: 'declarant1', profil: 'retraite', salaire_net_avant_impot_annuel: 20000, salaire_brut_annuel_estime: { bas: 21000, central: 21000, haut: 21000 }, revenu_imposable_annuel: 21000 }] } } as unknown as ResultatOk
    await ecran()
    expect(main.querySelector('.avertissement')?.textContent).toContain('une pension ou un revenu d’indépendant n’a pas de fiche de paie')
    expect(texte()).toContain('Exemple du site')
    expect(lignes().length).toBeGreaterThan(20)
  }, 120000)

  it('ligne inconnue du moteur : rangée dans « Autres lignes du calcul », jamais perdue', async () => {
    const nouvelle: Prelevement = {
      id: 'contribution_nouvelle',
      libelle: 'Contribution nouvelle',
      famille: 'cotisation_salariale',
      personne: 'declarant1',
      montant_annuel_eur: { bas: 120, central: 120, haut: 120 },
      destinataire: DESTINATAIRES.cnav,
      inclus_dans_total_paye: true,
      regle: 'test',
    }
    session.profil = PROFIL_EXEMPLE
    session.resultat = { ...exemple, prelevements: [...exemple.prelevements, nouvelle] }
    await ecran()
    expect(Array.from(main.querySelectorAll('h3')).map((x) => x.textContent)).toContain('Autres lignes du calcul')
    const li = ligne('Contribution nouvelle')
    expect(montant(li)).toBe(`ta part ${eurFr(10)}`)
    expect(net(li.textContent)).toContain('le site ne la détaille pas encore')
  }, 120000)

  // Lexique neutre partagé (docs/lexique_neutre.json, charte docs/NEUTRALITE.md) : même contrôle que ecrans.test.ts.
  const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; niche_definie: string; exceptions: string[] }
  const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
  function verifierLexique(t: string, ou: string) {
    let x = t.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
    for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
    for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
    expect(x.replace(new RegExp(LEXIQUE.niche_definie, 'giu'), ' '), `${ou} : « niche » sans définition`).not.toMatch(borne('niches?'))
  }

  it('lexique neutre, ni tiret long ni style en ligne, liens internes tous résolus, aucune requête externe', async () => {
    const cadre: Profil = { ...PROFIL_EXEMPLE, personnes: [salarie(5200, { cadre: true })] }
    for (const [nom, profil, resultat] of [
      ['exemple', null, null],
      ['cadre au-dessus du plafond', cadre, calcul(cadre)],
    ] as const) {
      session.profil = profil
      session.resultat = resultat
      await ecran()
      for (const periode of ['mois', 'an']) {
        main.querySelector<HTMLButtonElement>(`button[data-periode="${periode}"]`)!.click()
        verifierLexique(document.body.textContent ?? '', `${nom}, ${periode}`)
        for (const el of Array.from(main.querySelectorAll('[aria-label], [title], [alt]'))) verifierLexique(['aria-label', 'title', 'alt'].map((a) => el.getAttribute(a) ?? '').join(' '), `${nom} (attribut)`)
        expect(main.textContent, nom).not.toContain('—')
        expect(main.querySelectorAll('[style]').length, nom).toBe(0)
        for (const a of Array.from(main.querySelectorAll('a[href^="#/"]'))) {
          const chemin = a.getAttribute('href')!.slice(1).split('?')[0]
          expect(ROUTES.some((r) => r.chemin === chemin), `${nom} : lien mort ${chemin}`).toBe(true)
        }
      }
      if (profil) expect(net(ligne('Contribution d’équilibre technique (CET)').textContent)).toContain('Agirc-Arrco')
    }
    const r = ROUTES.find((x) => x.chemin === '/calcul/bulletin')!
    verifierLexique(`${r.titre} ${r.titrePage ?? ''} ${r.description} ${r.resume ?? ''}`, 'route')
    await attendreQue(() => requetes.length > 0)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  }, 180000)
})

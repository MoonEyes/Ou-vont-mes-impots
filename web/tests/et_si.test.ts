// @vitest-environment happy-dom
// Écran « Et si mon salaire changeait ? » (/calcul/et-si) : calculs (cohérence avec le moteur, taux marginal, lecture
// du barème), rendu, clavier, annonces aux lecteurs d'écran sans répétition, profils repris de la saisie, neutralité.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import type { Affectation } from '../src/calcul/agregats'
import { enregistrerDestinataires } from '../src/calcul/destinataires'
import { calculerProfil } from '../src/calcul/moteur-etendu'
import type { ProfilEtendu, ResultatOkEtendu } from '../src/calcul/types'
import {
  avecSalaire,
  ecart,
  erreurMontant,
  EXEMPLE,
  lireImpot,
  lireMontant,
  marginal,
  partsMarginal,
  personnesVariables,
  phraseAnnonce,
  rendre,
  resumerPoint,
  salairePropose,
  signe,
  sur100Difference,
  versePour100,
  type Point,
  type Role,
} from '../src/ecrans/et_si'
import { session } from '../src/etat'
import { afficher } from '../src/routeur'
import { ROUTES } from '../src/routes'
import { attendre, attendreQue, monterPage } from './aide-dom'

const AFFECTATION = JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/data/prelevements/affectation.json'), 'utf8')) as Affectation
const texte = (el: Element | null) => (el?.textContent ?? '').replace(/[\s\u00a0\u202f]+/g, ' ').trim()
const eurFr = (x: number) => `${new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(Math.round(x))} €`.replace(/[\s\u00a0\u202f]+/g, ' ')

/** Calcul direct (sans l'écran) d'un foyer pour un salaire donné. */
function point(profil: ProfilEtendu, role: Role, net: number): Point {
  const r = calculerProfil(avecSalaire(profil, role, net), { affectation: AFFECTATION })
  if (r.statut !== 'ok') throw new Error(JSON.stringify(r.erreur))
  return resumerPoint(r as ResultatOkEtendu, role)
}
/** Point à environ 100 € brut de plus par mois à partir du salaire net saisi, comme l'écran. */
const pointPlus100 = (profil: ProfilEtendu, role: Role, net: number, b: Point) => point(profil, role, net + Math.round(((100 * b.net_annuel) / b.brut_annuel) * 100) / 100)

const COUPLE: ProfilEtendu = {
  version_contrat: '1.0',
  annee_revenus: 2025,
  residence: { zone: 'metropole', alsace_moselle: false },
  foyer: { situation: 'couple_marie_pacse', enfants: [{ annee_naissance: 2015 }, { annee_naissance: 2018 }] },
  logement: { statut: 'locataire' },
  personnes: [
    { role: 'declarant1', statut_activite: 'salarie_prive', frontalier: false, cadre: true, temps_travail: { type: 'temps_plein' }, salaire_net_avant_impot_mensuel: 3200 },
    { role: 'declarant2', statut_activite: 'salarie_prive', frontalier: false, cadre: false, temps_travail: { type: 'temps_partiel', quotite: 0.8 }, salaire_net_avant_impot_mensuel: 1500 },
  ],
}

beforeAll(() => {
  monterPage()
  enregistrerDestinataires(AFFECTATION.destinataires)
})

describe('et si : saisie et fonctions pures', () => {
  it('montants saisis en texte, erreurs dites en mots', () => {
    expect(lireMontant('2 100,50')).toBe(2100.5)
    expect(lireMontant('2\u202f300 €')).toBe(2300)
    expect(lireMontant('2100.5')).toBe(2100.5)
    expect(lireMontant('')).toBeNaN()
    expect(lireMontant('deux mille')).toBeNaN()
    expect(erreurMontant(NaN)).toBe('Écris un montant en chiffres, par exemple 2300.')
    expect(erreurMontant(0)).toBe('Indique un salaire supérieur à 0 €.')
    expect(erreurMontant(100001)).toMatch(/^Montant mensuel au-delà/)
    expect(erreurMontant(2100)).toBeNull()
    expect(salairePropose(2100)).toBe(2300)
    expect(salairePropose(100)).toBe(150)
    expect(signe(1105.4)).toBe('+1\u202f105 €')
    expect(signe(-240.2)).toBe('\u2212240 €')
    expect(signe(0.3)).toBe('0 €')
  })

  it('le salaire change pour une seule personne ; un traitement indiciaire saisi est retrouvé à partir du net', () => {
    const p = avecSalaire(COUPLE, 'declarant2', 1712.345)
    expect(p.personnes[0].salaire_net_avant_impot_mensuel).toBe(3200)
    expect(p.personnes[1].salaire_net_avant_impot_mensuel).toBe(1712.35)
    expect(COUPLE.personnes[1].salaire_net_avant_impot_mensuel).toBe(1500)
    const f: ProfilEtendu = { ...EXEMPLE, personnes: [{ role: 'declarant1', statut_activite: 'fonctionnaire', versant: 'etat', primes_mensuelles: 300, traitement_indiciaire_brut_mensuel: 2500 }] }
    const g = avecSalaire(f, 'declarant1', 2000)
    expect(g.personnes[0].traitement_indiciaire_brut_mensuel).toBeUndefined()
    expect(g.personnes[0].salaire_net_avant_impot_mensuel).toBe(2000)
    expect(personnesVariables(COUPLE).map((x) => x.role)).toEqual(['declarant1', 'declarant2'])
    expect(personnesVariables({ ...EXEMPLE, personnes: [{ role: 'declarant1', statut_activite: 'retraite' }] })).toEqual([])
  })

  it('répartition sur 100 € : entiers dont la somme fait 100, dans le sens du total', () => {
    expect(sur100Difference({ 'Securite sociale': 600, Etat: 300, Plusieurs: 0 }, 900)).toEqual({ 'Securite sociale': 67, Etat: 33 })
    expect(sur100Difference({ 'Securite sociale': -600, Etat: -300 }, -900)).toEqual({ 'Securite sociale': 67, Etat: 33 })
    expect(sur100Difference({ Etat: 10 }, 0.2)).toEqual({})
  })

  it('lecture de l’impôt : aucun impôt, tranche du barème, zone de la décote, autre cas', () => {
    expect(lireImpot(0, 70, 0)).toEqual({ cas: 'nul' })
    expect(lireImpot(4, 70, 0)).toEqual({ cas: 'seuil' })
    expect(lireImpot(0.3 * 0.9 * 70, 70, 2500)).toEqual({ cas: 'tranche', taux: 0.3 })
    expect(lireImpot(0.11 * 0.9 * 70, 70, 900)).toEqual({ cas: 'tranche', taux: 0.11 })
    expect(lireImpot(0.11 * 1.4525 * 0.9 * 70, 70, 900)).toEqual({ cas: 'decote', taux: 0.11 })
    expect(lireImpot(0.2 * 70, 70, 900)).toEqual({ cas: 'autre' })
  })
})

describe('et si : cohérence avec le moteur de calcul', () => {
  it('2 100 € puis 2 300 € net : différence = écart des totaux du moteur, par famille, administration et destinataire', () => {
    const a = point(EXEMPLE, 'declarant1', 2100)
    const b = point(EXEMPLE, 'declarant1', 2300)
    const ra = calculerProfil(avecSalaire(EXEMPLE, 'declarant1', 2100), { affectation: AFFECTATION }) as ResultatOkEtendu
    const rb = calculerProfil(avecSalaire(EXEMPLE, 'declarant1', 2300), { affectation: AFFECTATION }) as ResultatOkEtendu
    const e = ecart(a, b)
    expect(e.total).toBeCloseTo(rb.totaux.paye_par_le_foyer.central - ra.totaux.paye_par_le_foyer.central, 1)
    const somme = (o: Record<string, number>) => Object.values(o).reduce((s, x) => s + x, 0)
    for (const parts of [e.familles, e.administrations, e.destinataires]) expect(somme(parts)).toBeCloseTo(e.total, 1)
    expect(e.total).toBeGreaterThan(0)
    // Ni l'État ni la Sécurité sociale ne reçoivent moins quand le salaire augmente.
    for (const v of Object.values(e.administrations)) expect(v).toBeGreaterThan(-0.01)
    expect(e.net).toBeCloseTo(2400, 0)
    expect(e.brut).toBeGreaterThan(e.net)
  })

  it('taux marginal : versé et reste font 100 €, billet en euros entiers', () => {
    for (const net of [1500, 2300, 4000, 9000]) {
      const b = point(EXEMPLE, 'declarant1', net)
      const c = pointPlus100(EXEMPLE, 'declarant1', net, b)
      const m = marginal(b, c)!
      expect(m.brut).toBe(100)
      expect(m.verse + m.reste, `${net}`).toBeCloseTo(100, 1)
      const parts = partsMarginal(m)
      expect(parts.reduce((s, p) => s + p.valeur, 0)).toBe(100)
      expect(parts.at(-1)?.famille).toBe('papier')
      expect(Math.abs(versePour100(m) - m.verse)).toBeLessThanOrEqual(1)
    }
  })

  it('lecture du barème sur des cas connus : pas d’impôt, décote, tranches à 30 % et 41 %', () => {
    const lecture = (profil: ProfilEtendu, role: Role, net: number) => {
      const b = point(profil, role, net)
      const m = marginal(b, pointPlus100(profil, role, net, b))!
      return lireImpot(m.impot, m.imposable, b.impot)
    }
    expect(lecture(EXEMPLE, 'declarant1', 1300)).toEqual({ cas: 'nul' })
    // À 1 500 € net, 100 € brut de plus font passer le seuil où l'impôt commence (zone de la décote).
    expect(lecture(EXEMPLE, 'declarant1', 1500)).toEqual({ cas: 'seuil' })
    expect(lecture(EXEMPLE, 'declarant1', 2300)).toEqual({ cas: 'decote', taux: 0.11 })
    expect(lecture(EXEMPLE, 'declarant1', 4000)).toEqual({ cas: 'tranche', taux: 0.3 })
    expect(lecture(EXEMPLE, 'declarant1', 9000)).toEqual({ cas: 'tranche', taux: 0.41 })
  })

  it('couple : seul le salaire choisi change, l’impôt du foyer suit', () => {
    const a = point(COUPLE, 'declarant2', 1500)
    const b = point(COUPLE, 'declarant2', 1700)
    const e = ecart(a, b)
    expect(e.net).toBeCloseTo(2400, 0)
    // Les cotisations de la personne 1 ne bougent pas.
    for (const [id, v] of Object.entries(e.lignes)) if (!id.endsWith('_declarant2') && !id.startsWith('impot_revenu')) expect(Math.abs(v), id).toBeLessThan(0.01)
    expect(e.impot).toBeGreaterThan(0)
  })
})

/** Écran rendu dans une zone de la page, comme le fait le routeur. */
async function monter(): Promise<HTMLElement> {
  const zone = document.createElement('div')
  zone.className = 'ecran'
  document.getElementById('contenu')!.replaceChildren(zone)
  const r = rendre(zone)
  await r.suite
  return zone
}
const saisir = (zone: HTMLElement, sel: string, valeur: string) => {
  const champ = zone.querySelector<HTMLInputElement>(sel)!
  champ.value = valeur
  champ.dispatchEvent(new Event('input', { bubbles: true }))
}
const attendreCalcul = (zone: HTMLElement, cond: () => boolean) => attendreQue(() => zone.querySelector<HTMLElement>('#es-etat')!.hidden && cond(), 60000)

const LEXIQUE = JSON.parse(readFileSync(join(process.cwd(), '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; niche_definie: string; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
function verifierLexique(t: string, ou: string) {
  let x = t.replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
  for (const e of LEXIQUE.exceptions) x = x.split(e).join(' ')
  for (const r of LEXIQUE.regles) expect(x, `${ou} : ${r.raison}`).not.toMatch(borne(r.termes.join('|')))
}

describe('et si : écran', () => {
  it('exemple du site : formulaire accessible, chiffre clé, sur 100 €, billet du taux marginal, sources', async () => {
    session.profil = null
    session.resultat = null
    const zone = await monter()
    expect(texte(zone.querySelector('h1'))).toBe('Et si mon salaire changeait ?')
    expect(texte(zone.querySelector('.chapeau'))).toContain('La page ne compte pas les prestations qui dépendent aussi du revenu')
    expect(texte(zone.querySelector('#es-profil'))).toContain('Calcul pour l’exemple du site')
    // Champs et curseur : étiquettes, valeur lue en clair, description, équivalent texte du curseur.
    for (const id of ['es-depart', 'es-nouveau', 'es-curseur']) expect(zone.querySelector(`label[for="${id}"]`), id).not.toBeNull()
    const curseur = zone.querySelector<HTMLInputElement>('#es-curseur')!
    expect(curseur.type).toBe('range')
    expect(curseur.getAttribute('aria-valuetext')).toBe('2\u202f300 € net par mois')
    expect(curseur.getAttribute('aria-describedby')).toContain('es-ecart')
    expect(zone.querySelector<HTMLInputElement>('#es-depart')!.value).toBe('2100')
    expect(zone.querySelector<HTMLInputElement>('#es-nouveau')!.value).toBe('2300')
    expect(texte(zone.querySelector('#es-ecart'))).toBe('Soit +200 € par mois par rapport au départ (+9,5 %).')
    // Région d'annonce polie, vide au premier affichage (le titre de la page est déjà annoncé par le routeur).
    const annonce = zone.querySelector('#es-annonce')!
    expect(annonce.getAttribute('role')).toBe('status')
    expect(annonce.getAttribute('aria-live')).toBe('polite')
    expect(annonce.textContent).toBe('')
    expect(zone.querySelector<HTMLElement>('#es-etat')!.hidden).toBe(true)
    // Chiffre clé : un seul surligneur, en euros, dans une carte qui donne aussi la répartition sur 100 €.
    const a = point(EXEMPLE, 'declarant1', 2100)
    const b = point(EXEMPLE, 'declarant1', 2300)
    const e = ecart(a, b)
    const m = marginal(b, pointPlus100(EXEMPLE, 'declarant1', 2300, b))!
    const surlignes = zone.querySelectorAll('.surligne')
    expect(surlignes).toHaveLength(1)
    expect(texte(surlignes[0])).toBe(signe(e.total).replace(/[\s\u00a0\u202f]+/g, ' '))
    const cle = surlignes[0].closest('[data-cle]')!
    expect(texte(cle)).toMatch(/Sur 100 € versés en plus : \d+ € Sécurité sociale, \d+ € État\./)
    const parts = [...texte(cle.querySelector('.recap-sur100')).matchAll(/(\d+) €/g)].map((x) => Number(x[1])).slice(1)
    expect(parts.reduce((s, x) => s + x, 0)).toBe(100)
    expect(texte(cle)).toContain(`${versePour100(m)} € seraient versés : c’est le taux marginal (${versePour100(m)} %)`)
    expect(texte(cle)).toContain(`tu verserais ${eurFr(b.total)} par an`)
    expect(texte(cle.querySelector('.source'))).toContain('revenus 2025')
    // Prélèvement par prélèvement, destinataires en tableau (légende, en-têtes de colonne et de ligne), ordre écrit.
    expect(texte(zone)).toContain('Cotisations sociales prélevées sur ton salaire')
    expect(texte(zone)).toContain('Impôt sur le revenu')
    const table = zone.querySelector('#es-detail table')!
    expect(texte(table.querySelector('caption'))).toBe('Ce que reçoit chaque destinataire : différence par an entre les deux salaires')
    expect(table.querySelectorAll('thead th[scope="col"]')).toHaveLength(3)
    expect(table.querySelectorAll('tbody th[scope="row"]').length).toBeGreaterThan(4)
    expect(texte(table)).toContain("Caisse d'amortissement de la dette sociale")
    expect(texte(zone.querySelector('[data-regle-ordre]'))).toMatch(/^Ordre : Sécurité sociale, État, collectivités/)
    // Ordre des lignes : administration d'abord (Sécurité sociale avant l'État).
    const lignes = Array.from(table.querySelectorAll('tbody th')).map((th) => texte(th))
    expect(lignes.findIndex((l) => l.startsWith('État'))).toBe(lignes.length - 1)
    // Taux marginal : billet de 100 € (parts qui font 100), sa version liste et tableau, explication de l'impôt.
    const billet = zone.querySelector('.billet .billet-large')!
    const valeurs = Array.from(billet.querySelectorAll('[aria-label]'))
      .map((x) => /: (\d+) €/.exec(x.getAttribute('aria-label') ?? ''))
      .filter((x): x is RegExpExecArray => !!x)
      .map((x) => Number(x[1]))
    expect(valeurs.reduce((s, x) => s + x, 0)).toBe(100)
    expect(zone.querySelector('.billet-tableau table caption')).not.toBeNull()
    expect(texte(zone.querySelector('.parts'))).toContain('Ton salaire net après impôt')
    expect(texte(zone)).toContain('Ton impôt est aussi dans la zone de la décote')
    expect(texte(zone)).toContain('cotisations patronales')
    // Sorties, aucune couleur seule : statuts avec leur mot.
    expect(zone.querySelector('a[href="#/calcul"]')).not.toBeNull()
    expect(zone.querySelector('a[href="#/explorer/secu"]')).not.toBeNull()
    expect(texte(zone.querySelector('.legende-statuts'))).toContain('Tracé')
    // Règles du site : pas de style en ligne hors largeurs, pas de tiret long, lexique neutre partout.
    const fautifs = Array.from(zone.querySelectorAll('[style]')).filter((el) => !el.hasAttribute('data-l') && !el.hasAttribute('data-g') && !el.hasAttribute('data-f'))
    expect(fautifs).toHaveLength(0)
    expect(zone.textContent).not.toContain('\u2014')
    verifierLexique(zone.textContent ?? '', 'et si (texte)')
    for (const el of Array.from(zone.querySelectorAll('[aria-label], [title], [alt]'))) verifierLexique(['aria-label', 'title', 'alt'].map((x) => el.getAttribute(x) ?? '').join(' '), 'et si (attribut)')
    for (const t of Array.from(zone.querySelectorAll('h1, h2, h3'))) expect(t.textContent ?? '').not.toMatch(/\b(gaspillage|seulement|énorme|opaque|scandale|trop)\b/i)
    expect(zone.querySelector('.erreur')).toBeNull()
  }, 120000)

  it('curseur, clavier et boutons : le salaire comparé suit, une seule annonce une fois la saisie finie', async () => {
    session.profil = null
    const zone = await monter()
    const annonce = zone.querySelector('#es-annonce')!
    const annonces: string[] = []
    new MutationObserver(() => annonces.push(annonce.textContent ?? '')).observe(annonce, { childList: true, characterData: true, subtree: true })
    const curseur = zone.querySelector<HTMLInputElement>('#es-curseur')!
    const nouveau = zone.querySelector<HTMLInputElement>('#es-nouveau')!
    // Trois crans de suite (glissement) : un seul calcul annoncé, celui du dernier salaire.
    for (const v of ['2500', '2600', '2700']) {
      curseur.value = v
      curseur.dispatchEvent(new Event('input', { bubbles: true }))
      await attendre(30)
    }
    expect(nouveau.value).toBe('2700')
    expect(curseur.getAttribute('aria-valuetext')).toContain('2\u202f700')
    expect(zone.querySelector<HTMLElement>('#es-etat')!.hidden).toBe(false)
    await attendreCalcul(zone, () => annonce.textContent !== '')
    await attendre(50)
    expect(annonces).toHaveLength(1)
    expect(annonces[0]).toMatch(/^Avec 2\u202f700 € net par mois au lieu de 2\u202f100 €, tu verserais [\d\u202f]+ € de plus par an\. Sur 100 € de salaire brut en plus, \d+ € seraient versés\.$/)
    expect(texte(zone.querySelector('.recap'))).toContain('Avec 2 700 € net par mois')
    // Page suivante : 100 € de plus ; boutons : 100 € de moins.
    curseur.dispatchEvent(new KeyboardEvent('keydown', { key: 'PageUp', bubbles: true, cancelable: true }))
    expect(nouveau.value).toBe('2800')
    expect(curseur.value).toBe('2800')
    zone.querySelector<HTMLButtonElement>('button[data-pas="-100"]')!.click()
    zone.querySelector<HTMLButtonElement>('button[data-pas="-100"]')!.click()
    expect(nouveau.value).toBe('2600')
    expect(texte(zone.querySelector('#es-ecart'))).toBe('Soit +500 € par mois par rapport au départ (+23,8 %).')
    await attendreCalcul(zone, () => texte(zone.querySelector('.recap')).includes('Avec 2 600 € net par mois'))
    await attendre(50)
    expect(annonces).toHaveLength(2)
    expect(annonces[1]).toContain('2\u202f600 €')
    // Même salaire : rien de neuf à annoncer.
    zone.querySelector<HTMLFormElement>('#es-form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await attendreCalcul(zone, () => true)
    await attendre(400)
    expect(annonces).toHaveLength(2)
  }, 120000)

  it('saisie illisible : signalée sur le champ, sans calcul ni annonce ; salaire de départ égal : aucune différence', async () => {
    session.profil = null
    const zone = await monter()
    const annonce = zone.querySelector('#es-annonce')!
    saisir(zone, '#es-nouveau', 'deux mille')
    await attendre(ATTENTE_TEST)
    const champ = zone.querySelector('#es-nouveau')!
    expect(champ.getAttribute('aria-invalid')).toBe('true')
    expect(texte(zone.querySelector('#es-nouveau-msg'))).toBe('Écris un montant en chiffres, par exemple 2300.')
    expect(zone.querySelector<HTMLElement>('#es-etat')!.hidden).toBe(true)
    // L'erreur est dite une fois aux lecteurs d'écran, après la pause de saisie (critère 4.1.3).
    expect(annonce.textContent).toBe('Salaire comparé : Écris un montant en chiffres, par exemple 2300.')
    saisir(zone, '#es-nouveau', 'deux mille deux')
    await attendre(ATTENTE_TEST)
    expect(annonce.textContent).toBe('Salaire comparé : Écris un montant en chiffres, par exemple 2300.')
    saisir(zone, '#es-nouveau', '2100')
    await attendreCalcul(zone, () => texte(zone.querySelector('.recap')).includes('aucune différence'))
    expect(champ.hasAttribute('aria-invalid')).toBe(false)
    expect(texte(zone.querySelector('#es-ecart'))).toBe('Même salaire qu’au départ.')
    expect(texte(zone.querySelector('.recap .grand-chiffre'))).toBe('0 €')
    expect(texte(zone.querySelector('.recap'))).toMatch(/sur 100 € de salaire brut en plus/i)
    expect(annonce.textContent).toMatch(/^Même salaire qu’au départ/)
    // Baisse de salaire : « en moins », répartition sur 100 € versés en moins.
    saisir(zone, '#es-nouveau', '1800')
    await attendreCalcul(zone, () => texte(zone.querySelector('.recap')).includes('Avec 1 800 € net par mois'))
    expect(texte(zone.querySelector('.recap-titre'))).toBe('Ce que tu verserais en moins, en un an')
    expect(texte(zone.querySelector('.recap .surligne'))).toMatch(/^\u2212[\d\s]+ €$/)
    expect(texte(zone.querySelector('.recap-sur100'))).toMatch(/^Sur 100 € versés en moins : /)
  }, 120000)

  it('situation saisie : couple, choix du salaire qui change ; saisie sans salaire : exemple du site', async () => {
    session.profil = COUPLE as never
    const zone = await monter()
    expect(texte(zone.querySelector('#es-profil'))).toContain('Calcul pour ta situation saisie : en couple marié ou pacsé, 2 enfants à charge. Le salaire qui change est le tien')
    expect(texte(zone.querySelector('#es-profil'))).toContain('celui de ton ou ta conjoint·e reste à 1 500 € net par mois')
    expect(zone.querySelector('[role="radiogroup"][aria-labelledby="es-personne-titre"]')).not.toBeNull()
    expect(zone.querySelector<HTMLInputElement>('#es-depart')!.value).toBe('3200')
    const radio = zone.querySelector<HTMLInputElement>('input[name="es-personne"][value="declarant2"]')!
    radio.checked = true
    radio.dispatchEvent(new Event('change', { bubbles: true }))
    expect(zone.querySelector<HTMLInputElement>('#es-depart')!.value).toBe('1500')
    expect(zone.querySelector<HTMLInputElement>('#es-nouveau')!.value).toBe('1650')
    expect(texte(zone.querySelector('#es-profil'))).toContain('Le salaire qui change est celui de ton ou ta conjoint·e')
    await attendreCalcul(zone, () => texte(zone.querySelector('.recap')).includes('Avec 1 650 € net par mois'))
    const a = point(COUPLE, 'declarant2', 1500)
    const b = point(COUPLE, 'declarant2', 1650)
    expect(texte(zone.querySelector('.recap .surligne'))).toBe(signe(ecart(a, b).total).replace(/[\s\u00a0\u202f]+/g, ' '))
    expect(zone.querySelector('#es-annonce')!.textContent).toBe(phraseAnnonce(a, b, ecart(a, b), marginal(b, pointPlus100(COUPLE, 'declarant2', 1650, b))))
    // Fonctionnaire saisi par son traitement indiciaire : le salaire net de départ est retrouvé par le calcul.
    session.profil = { ...EXEMPLE, personnes: [{ role: 'declarant1', statut_activite: 'fonctionnaire', versant: 'etat', primes_mensuelles: 300, traitement_indiciaire_brut_mensuel: 2500 }] } as never
    const zf = await monter()
    const departF = Number(zf.querySelector<HTMLInputElement>('#es-depart')!.value)
    expect(departF).toBeGreaterThan(2000)
    expect(departF).toBeLessThan(2800)
    expect(zf.querySelector<HTMLInputElement>('#es-nouveau')!.value).toBe(String(salairePropose(departF)))
    expect(texte(zf.querySelector('#es-profil'))).toContain('Le salaire qui change est le tien (fonctionnaire)')
    expect(zf.querySelectorAll('.recap .surligne')).toHaveLength(1)
    expect(zf.querySelector('.erreur')).toBeNull()
    // Retraité seul : aucun salaire à faire varier, l'exemple du site est repris et la raison est dite.
    session.profil = { ...EXEMPLE, personnes: [{ role: 'declarant1', statut_activite: 'retraite', pension_base_mensuelle: 1500, pension_complementaire_mensuelle: 500, csg_pension: { taux: 'normal' } }] } as never
    const z2 = await monter()
    expect(texte(z2.querySelector('#es-profil'))).toMatch(/^Ta saisie ne comporte pas de salaire qui puisse varier ici/)
    expect(z2.querySelector<HTMLInputElement>('#es-depart')!.value).toBe('2100')
    session.profil = null
  }, 120000)

  it('route : sous « Mon salaire », fil d’Ariane, voisins existants, lien depuis le résultat', async () => {
    const r = ROUTES.find((x) => x.chemin === '/calcul/et-si')!
    expect(r).toBeTruthy()
    expect(r.parent).toBe('/calcul')
    for (const v of r.voisins ?? []) expect(ROUTES.some((x) => x.chemin === v), v).toBe(true)
    verifierLexique(`${r.titre} ${r.titrePage ?? ''} ${r.description} ${r.resume ?? ''}`, 'route')
    const main = document.getElementById('contenu') as HTMLElement
    session.profil = null
    location.hash = '#/calcul/et-si'
    await afficher(ROUTES, main, '#/calcul/et-si')
    expect(Array.from(main.querySelectorAll('nav.fil-ariane a')).map((a) => texte(a))).toEqual(['Accueil', 'Mon salaire', r.court ?? r.titre])
    expect(main.querySelector('nav.fil-ariane [aria-current=page]')?.getAttribute('href')).toBe('#/calcul/et-si')
    expect(main.querySelector('h1 .picto')).not.toBeNull()
    expect(main.querySelector('.voir-aussi a[href="#/calcul"]')).not.toBeNull()
    expect(main.querySelectorAll('.surligne')).toHaveLength(1)
    expect(document.title).toBe('Et si mon salaire changeait ? Impôts et cotisations')
    const paie = readFileSync(join(process.cwd(), 'src/ecrans/paie.ts'), 'utf8')
    expect(paie).toContain('href="#/calcul/et-si"')
  }, 120000)
})

const ATTENTE_TEST = 450

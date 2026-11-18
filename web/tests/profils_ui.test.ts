// @vitest-environment happy-dom
// Profils étendus dans le parcours de calcul (agent « profils-calcul ») : le chemin simple (salaire seul) ne change ni
// d'aspect ni de résultat ; « Préciser ma situation » ouvre les autres profils, saisis puis recalculés exactement comme
// calculerProfil le fait sur les cas types ; l'écran résultat montre le profil retenu et ce qui n'est pas calculé ;
// erreurs reliées aux champs ; tout est calculé sur l'appareil (aucune requête hors des données du site).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'
import { ROUTES } from '../src/main'
import { afficher } from '../src/routeur'
import { session } from '../src/etat'
import { calculer } from '../src/calcul/moteur'
import * as etendu from '../src/calcul/moteur-etendu'
import { calculerProfil } from '../src/calcul/moteur-etendu'
import * as perimetre from '../src/calcul/perimetre-etendu'
import { descriptionPersonne, LIBELLE_PROFIL, limitesDuCalcul, natureRevenus, resumeProfil } from '../src/calcul/profils-ui'
import type { Affectation } from '../src/calcul/agregats'
import type { PersonneEtendue, ProfilEtendu, ResultatOk, ResultatOkEtendu } from '../src/calcul/types'
import { attendreQue, monterPage, requetes } from './aide-dom'

const RACINE = process.cwd()
const affectation = JSON.parse(readFileSync(join(RACINE, 'tests/fixtures/data/prelevements/affectation.json'), 'utf8')) as Affectation
const CAS = JSON.parse(readFileSync(join(RACINE, '..', 'tests', 'cas_types', 'cas_types_profils.json'), 'utf8')).cas as { id: string; groupe: string; profil: ProfilEtendu }[]
const LEXIQUE = JSON.parse(readFileSync(join(RACINE, '..', 'docs', 'lexique_neutre.json'), 'utf8')) as { regles: { termes: string[]; raison: string }[]; exceptions: string[] }
const borne = (corps: string) => new RegExp(`(?<![\\p{L}\\p{N}_])(?:${corps})(?![\\p{L}\\p{N}_])`, 'iu')
const INTERDITS: [RegExp, string][] = LEXIQUE.regles.map((r) => [borne(r.termes.join('|')), r.raison])

let main: HTMLElement
const ecran = async (fragment: string) => {
  location.hash = fragment
  await afficher(ROUTES, main, fragment)
  return main
}
const texte = () => main.textContent?.replace(/\s+/g, ' ') ?? ''
/** Espaces insécables des montants (séparateur de milliers) ramenées à des espaces simples. */
const norm = (s: string) => s.replace(/\s+/g, ' ')
const $ = <T extends HTMLElement = HTMLElement>(s: string) => main.querySelector(s) as T
const soumettre = () => $<HTMLFormElement>('#formulaire').dispatchEvent(new Event('submit', { cancelable: true }))
const remplir = (sel: string, valeur: string) => ($<HTMLInputElement>(sel).value = valeur)
const choisirStatut = (n: 1 | 2, statut: string) => {
  const s = $<HTMLSelectElement>(`#p${n}-statut`)
  s.value = statut
  s.dispatchEvent(new Event('change', { bubbles: true }))
}
/** Coche un bouton radio (happy-dom ne décoche pas les autres boutons du groupe : on le fait ici). */
const cocher = (nom: string, valeur: string) => {
  main.querySelectorAll<HTMLInputElement>(`input[name="${nom}"]`).forEach((r) => (r.checked = r.value === valeur))
  $(`input[name="${nom}"][value="${valeur}"]`).dispatchEvent(new Event('change', { bubbles: true }))
}
const visible = (sel: string) => {
  let el: HTMLElement | null = $(sel)
  for (; el && el !== main; el = el.parentElement) if (el.hidden) return false
  return true
}
/** Soumet et attend le résultat (ou une erreur affichée). */
async function calculerParLaSaisie(): Promise<ResultatOkEtendu> {
  session.resultat = null
  session.complet = null
  soumettre()
  await attendreQue(() => session.resultat !== null || !!main.querySelector('#retour .erreur, #retour .avertissement, .message-champ:not([hidden])'), 60000)
  const erreur = main.querySelector('#retour .erreur, #retour .avertissement, .message-champ:not([hidden])')?.textContent
  expect(erreur, 'erreur inattendue').toBeUndefined()
  return session.resultat as unknown as ResultatOkEtendu
}
/** Soumet et attend l'erreur affichée sur un champ ou un groupe ; renvoie son message. */
async function erreurSur(selMessage: string): Promise<string> {
  session.resultat = null
  soumettre()
  await attendreQue(() => !$(selMessage).hidden, 30000)
  return $(selMessage).textContent ?? ''
}

/** Un cas type ramené à ce que la saisie produit : sans commune, enfants de 2015, âge pivot des 65 ans pour les retraités. */
function versSaisie(p: ProfilEtendu): ProfilEtendu {
  return {
    ...p,
    residence: { zone: p.residence.zone, alsace_moselle: p.residence.alsace_moselle },
    foyer: { situation: p.foyer.situation, enfants: p.foyer.enfants.map(() => ({ annee_naissance: 2015, garde_alternee: false })) },
    logement: { statut: p.logement?.statut ?? 'locataire' },
    personnes: p.personnes.map(({ annee_naissance, ...q }): PersonneEtendue =>
      q.statut_activite === 'retraite' ? { ...q, annee_naissance: (annee_naissance ?? 1950) <= 1960 ? 1960 : 1961 } : q,
    ),
  }
}

beforeAll(() => {
  monterPage()
  main = document.getElementById('contenu') as HTMLElement
})

describe('profils étendus : module de contrôle léger', () => {
  it('le moteur réexporte le contrôle léger : un seul contrôle, partagé avec la saisie', () => {
    expect(etendu.verifierProfilEtendu).toBe(perimetre.verifierProfilEtendu)
    expect(etendu.profilDe).toBe(perimetre.profilDe)
  })
})

describe('chemin simple : salaire net avant impôt seul, par défaut', () => {
  it('les profils sont repliés dans « Préciser ma situation », le salaire reste le seul champ à remplir', async () => {
    session.profil = null
    session.resultat = null
    await ecran('#/calcul')
    const preciser = $<HTMLDetailsElement>('#p1-preciser')
    expect(preciser.tagName).toBe('DETAILS')
    expect(preciser.open).toBe(false)
    expect(preciser.querySelector('summary')?.textContent).toBe('Préciser ma situation')
    // Le salaire est hors du bloc replié ; la situation professionnelle et tous les champs des profils y sont.
    expect(preciser.contains($('#p1-net'))).toBe(false)
    expect(visible('#p1-net')).toBe(true)
    for (const id of ['statut', 'cadre', 'partiel', 'primes', 'traitement', 'versant', 'pension-base', 'csg', 'age', 'ca', 'vl', 'activite', 'contrat'])
      expect(preciser.contains($(`#p1-${id}`)), id).toBe(true)
    // Salarié du privé par défaut : aucun champ d'un autre profil n'est affiché, même bloc ouvert.
    for (const o of ['fonctionnaire', 'apprenti', 'retraite', 'independant']) expect($(`#p1-opt-${o}`).hidden, o).toBe(true)
    expect(texte()).toContain('Alsace-Moselle comprise')
    expect(texte()).not.toContain('Version 1')
  })

  it('2 100 € net : même résultat que le calcul du contrat 1.0, même phrase de profil', async () => {
    await ecran('#/calcul')
    remplir('#p1-net', '2100')
    const r = await calculerParLaSaisie()
    const v1 = calculer(session.profil!, { affectation }) as ResultatOk
    expect(v1.statut).toBe('ok')
    expect(r.prelevements).toEqual(v1.prelevements)
    expect(r.totaux).toEqual(v1.totaux)
    expect(r.avertissements).toEqual(v1.avertissements)
    expect(session.profil?.personnes).toEqual([{ role: 'declarant1', statut_activite: 'salarie_prive', frontalier: false, salaire_net_avant_impot_mensuel: 2100, cadre: false, temps_travail: { type: 'temps_plein' } }])
    expect(norm(resumeProfil(session.profil as ProfilEtendu, r))).toBe('Seul·e, sans enfant, 2 100 € net avant impôt par mois')
    await ecran('#/calcul/resultat')
    expect(texte()).toContain('Seul·e, sans enfant, 2 100 € net avant impôt par mois')
    expect(texte()).toContain('Cotisations sociales prélevées sur ton salaire')
    expect($('#titre-profil')?.textContent).toBe('Le profil retenu pour ce calcul')
    expect(texte()).toContain('Salarié·e du secteur privé, non cadre, à temps plein : 2 100 € net avant impôt par mois')
    expect(texte()).toContain('Salarié·e du secteur privé : vérifié (OpenFisca, 20 cas types de salariés')
    expect(texte()).toContain('Complémentaire santé et prévoyance d’entreprise : non comptées')
    expect($('#titre-patronal')).not.toBeNull()
    expect($('#avec-patronal')).not.toBeNull()
  }, 120000)
})

// Chaque cas type passe par le formulaire (prérempli depuis le profil, comme au retour sur la saisie) : le profil relu
// et le calcul obtenu sont ceux de calculerProfil sur le même cas, vérifié par ailleurs face à OpenFisca.
const ATTENDUS: Record<string, { limite: string; nature: string; patronal: boolean }> = {
  F03: { limite: 'Militaires et magistrats', nature: 'Cotisations sociales prélevées sur ton salaire', patronal: true },
  P01: { limite: 'assurance chômage', nature: 'Cotisations sociales prélevées sur ton salaire', patronal: true },
  R03: { limite: 'Cotisation maladie de 1 %', nature: 'Cotisations sociales prélevées sur ta pension', patronal: false },
  M06: { limite: 'Cotisation foncière des entreprises', nature: 'Cotisations sociales sur ton chiffre d’affaires', patronal: false },
  E02: { limite: 'Complémentaire santé', nature: 'Cotisations sociales prélevées sur ton salaire', patronal: true },
  X02: { limite: 'Cotisation maladie de 1 %', nature: 'Cotisations sociales sur les revenus du foyer', patronal: true },
  X03: { limite: 'Cipav', nature: 'Cotisations sociales sur les revenus du foyer', patronal: true },
  A02: { limite: 'Complémentaire santé', nature: 'Cotisations sociales prélevées sur ton salaire', patronal: true },
  T03: { limite: 'Complémentaire santé', nature: 'Cotisations sociales prélevées sur ton salaire', patronal: true },
}

describe('« Préciser ma situation » : chaque profil du moteur étendu, de la saisie au résultat', () => {
  for (const [id, attendu] of Object.entries(ATTENDUS)) {
    it(`${id} : saisie, calcul identique à calculerProfil, profil retenu et limites à l’écran`, async () => {
      const cas = CAS.find((c) => c.id === id)!
      const profil = versSaisie(cas.profil)
      session.profil = profil
      await ecran('#/calcul')
      // Profil autre que le salaire par défaut : les précisions sont ouvertes au retour sur la saisie.
      if (profil.personnes.some((p) => p.statut_activite !== 'salarie_prive' || p.cadre || p.temps_travail?.type === 'temps_partiel'))
        expect($<HTMLDetailsElement>('#p1-preciser').open || $<HTMLDetailsElement>('#p2-preciser').open).toBe(true)
      const r = await calculerParLaSaisie()
      const direct = calculerProfil(profil, { affectation })
      if (direct.statut !== 'ok') throw new Error(JSON.stringify(direct.erreur))
      expect(r.prelevements).toEqual(direct.prelevements)
      expect(r.totaux).toEqual(direct.totaux)
      expect(r.entree.personnes.map((p) => p.profil)).toEqual(direct.entree.personnes.map((p) => p.profil))
      expect(perimetre.verifierProfilEtendu(session.profil as ProfilEtendu)).toBeNull()

      await ecran('#/calcul/resultat')
      const t = texte()
      const fiche = $('[aria-labelledby="titre-profil"]')
      expect(fiche).not.toBeNull()
      for (const p of r.entree.personnes) expect(fiche.textContent, p.profil).toContain(LIBELLE_PROFIL[p.profil])
      for (const v of r.verifications) expect(fiche.textContent, v.profil).toContain(`${LIBELLE_PROFIL[v.profil]} : vérifié (`)
      expect(fiche.textContent).toContain('Ce qui n’est pas calculé')
      expect(fiche.textContent).toContain(attendu.limite)
      expect(fiche.textContent).toContain('Revenus 2025')
      expect(t).toContain(attendu.nature)
      // Part employeur : affichée seulement s'il y en a une (pas pour une pension ni une micro-entreprise seules).
      expect(!!$('#titre-patronal'), 'section employeur').toBe(attendu.patronal)
      expect(!!$('#avec-patronal'), 'bascule employeur').toBe(attendu.patronal)
      if (!attendu.patronal) expect(t).toContain('Pas de cotisations d’employeur')
      // Aucun identifiant technique ni « plusieurs administrations » pour une ligne sans destinataire publié.
      expect(t).not.toContain('non_affecte')
      await attendreQue(() => main.querySelectorAll('#par-destinataire li').length > 0)
      if (r.prelevements.some((l) => l.destinataire.id === 'non_affecte')) {
        expect(t).toContain('Répartition entre organismes non publiée dans les données du site')
      }
      // Vue par défaut sans la part employeur : la ligne « non publié » n'y figure que si une ligne versée en est.
      if (r.prelevements.some((l) => l.destinataire.id === 'non_affecte' && l.inclus_dans_total_paye && l.famille !== 'cotisation_patronale')) {
        expect($('#par-destinataire').textContent).toContain('Destinataire non publié dans les données du site')
        expect($('#par-destinataire').textContent).not.toContain('Destinataire non publié dans les données du site (')
      }
      expect(t).not.toContain('—')
      expect(main.querySelectorAll('[style]:not([data-l]):not([data-g]):not([data-f])')).toHaveLength(0)
      // Lexique neutre (docs/lexique_neutre.json), sur tout le texte de la page.
      let tout = (document.body.textContent ?? '').replace(/\s+/g, ' ').replace(/[\w./:-]*\/[\w./-]+/g, ' ')
      for (const e of LEXIQUE.exceptions) tout = tout.split(e).join(' ')
      for (const [re, raison] of INTERDITS) expect(tout, `${id} : ${raison}`).not.toMatch(re)
      expect($$surligne()).toBeLessThanOrEqual(1)
    }, 120000)
  }
})
const $$surligne = () => main.querySelectorAll('.surligne').length

describe('saisie pas à pas : champs révélés, erreurs reliées aux champs', () => {
  it('fonctionnaire : versant, primes, puis calcul ; erreurs sur le groupe puis sur le champ, bloc ouvert', async () => {
    session.profil = null
    await ecran('#/calcul')
    choisirStatut(1, 'fonctionnaire')
    expect(visible('#p1-opt-fonctionnaire')).toBe(true)
    expect($('#p1-salaire').hidden).toBe(false)
    expect($('#p1-opt-salarie').hidden).toBe(true)
    expect($('#p1-opt-retraite').hidden).toBe(true)
    remplir('#p1-net', '2300')
    // Bloc replié au moment de l'erreur : il s'ouvre, le message est dans le groupe et relié à lui, le focus va au premier choix.
    $<HTMLDetailsElement>('#p1-preciser').open = false
    expect(await erreurSur('#p1-versant-msg')).toContain('versant de la fonction publique')
    expect($<HTMLDetailsElement>('#p1-preciser').open).toBe(true)
    expect($('#p1-versant').tagName).toBe('FIELDSET')
    expect($('#p1-versant').getAttribute('aria-describedby')).toContain('p1-versant-msg')
    expect($('#p1-versant').contains($('#p1-versant-msg'))).toBe(true)
    expect(document.activeElement).toBe($('#p1-versant input'))
    cocher('p1-versant', 'territoriale')
    expect(await erreurSur('#p1-primes-msg')).toContain('primes et indemnités')
    expect($('#p1-primes').getAttribute('aria-invalid')).toBe('true')
    expect($('#p1-primes').getAttribute('aria-describedby')).toContain('p1-primes-msg')
    expect(document.activeElement).toBe($('#p1-primes'))
    remplir('#p1-primes', '450')
    const r = await calculerParLaSaisie()
    expect(r.entree.personnes[0].profil).toBe('fonctionnaire')
    expect(r.prelevements.map((l) => l.id)).toContain('retenue_cnracl')
    // Le traitement indiciaire retrouvé à partir du net saisi est montré dans le profil retenu.
    await ecran('#/calcul/resultat')
    expect(texte()).toMatch(/Fonctionnaire titulaire, fonction publique territoriale : 2 300 € net avant impôt par mois, dont primes et indemnités de 450 € brut par mois \(traitement indiciaire brut retrouvé : [\d\s]+ € par mois\)/)
    expect(texte()).toContain('la contribution au Fonds national d’aide au logement et le versement mobilité de l’employeur public')
  }, 120000)

  it('retraité·e : pension, taux de CSG déduit de l’avis, âge ; le salaire disparaît, chaque oubli est signalé sur son champ', async () => {
    session.profil = null
    await ecran('#/calcul')
    choisirStatut(1, 'retraite')
    expect($('#p1-salaire').hidden).toBe(true)
    expect(visible('#p1-pension-base')).toBe(true)
    expect(await erreurSur('#p1-pension-base-msg')).toContain('pension de base')
    expect($('#p1-pension-base').getAttribute('aria-invalid')).toBe('true')
    remplir('#p1-pension-base', '1 300')
    remplir('#p1-pension-compl', 'six cents')
    expect(await erreurSur('#p1-pension-compl-msg')).toContain('pension complémentaire')
    remplir('#p1-pension-compl', '600,50')
    expect(await erreurSur('#p1-csg-msg')).toContain('taux de CSG')
    cocher('p1-csg', 'rfr')
    expect($('#p1-rfr-bloc').hidden).toBe(false)
    expect(await erreurSur('#p1-rfr-msg')).toContain('revenu fiscal de référence')
    remplir('#p1-rfr', '21 000')
    expect(await erreurSur('#p1-parts-msg')).toContain('nombre de parts')
    remplir('#p1-parts', '1')
    // L'âge (abattement des 65 ans et plus) est demandé par la saisie elle-même.
    expect(await erreurSur('#p1-age-msg')).toContain('65 ans ou plus')
    expect($('#p1-age').getAttribute('aria-describedby')).toContain('p1-age-msg')
    cocher('p1-age', 'plus65')
    const r = await calculerParLaSaisie()
    const p = session.profil!.personnes[0] as PersonneEtendue
    expect(p).toMatchObject({ statut_activite: 'retraite', pension_base_mensuelle: 1300, pension_complementaire_mensuelle: 600.5, pension_saisie: 'nette_avant_impot', csg_pension: { revenu_fiscal_reference: 21000, parts: 1 }, annee_naissance: 1960 })
    expect(r.entree.personnes[0].detail?.taux_csg).toBe('taux médian de 6,6 %')
    await ecran('#/calcul/resultat')
    expect(texte()).toContain('Sur ta pension')
    expect(texte()).toContain('de pension nette avant impôt par an')
    expect(texte()).toContain('CSG au taux médian de 6,6 % (déduit de ton revenu fiscal de référence)')
    expect(texte()).toContain('65 ans ou plus fin 2025')
    expect($('#titre-patronal')).toBeNull()
  }, 120000)

  it('micro-entreprise : chiffre d’affaires au-delà du plafond refusé sur le champ ; activité libérale sans case « artisanale »', async () => {
    session.profil = null
    await ecran('#/calcul')
    choisirStatut(1, 'independant')
    expect($('#p1-salaire').hidden).toBe(true)
    expect($('#p1-note-statut').textContent).toContain('régime réel')
    expect(await erreurSur('#p1-activite-msg')).toContain('nature de l')
    cocher('p1-activite', 'service_bnc')
    expect($('#p1-artisan-bloc').hidden).toBe(true)
    remplir('#p1-ca', '90000')
    expect(await erreurSur('#p1-ca-msg')).toContain('plafond')
    expect($('#p1-ca').getAttribute('aria-invalid')).toBe('true')
    remplir('#p1-ca', '36000')
    expect(await erreurSur('#p1-vl-msg')).toContain('versement libératoire')
    cocher('p1-vl', 'oui')
    const r = await calculerParLaSaisie()
    expect(r.prelevements.map((l) => l.id)).toContain('impot_revenu_versement_liberatoire')
    expect(natureRevenus(r)).toBe('micro')
  }, 120000)

  it('apprenti·e : la date du contrat est demandée ; couple : la personne 2 a ses propres précisions', async () => {
    session.profil = null
    await ecran('#/calcul')
    choisirStatut(1, 'apprenti')
    remplir('#p1-net', '1000')
    expect(await erreurSur('#p1-contrat-msg')).toContain('1er mars 2025')
    cocher('p1-contrat', 'depuis')
    cocher('situation', 'couple_union_libre')
    expect($('#p2-bloc').hidden).toBe(false)
    expect($('#p2-preciser summary').textContent).toBe('Préciser sa situation')
    choisirStatut(2, 'sans_activite')
    expect($('#p2-salaire').hidden).toBe(true)
    const r = await calculerParLaSaisie()
    expect(session.profil!.personnes.map((p) => p.statut_activite)).toEqual(['apprenti', 'sans_activite'])
    expect(r.entree.personnes.map((p) => p.profil)).toEqual(['apprenti'])
    await ecran('#/calcul/resultat')
    expect(texte()).toContain('Ton ou ta conjoint·e')
    expect(texte()).toContain('Sans activité professionnelle : pas de revenu d’activité ni de pension dans ce calcul.')
    expect(texte()).toContain('deux déclarations d’impôt')
  }, 120000)

  it('hors périmètre : message de sortie focalisable, avec la redirection vers l’exploration', async () => {
    for (const [statut, zone, message] of [
      ['demandeur_emploi', 'metropole', 'allocations chômage'],
      ['retraite', 'alsace_moselle', 'régime local'],
    ]) {
      session.profil = null
      await ecran('#/calcul')
      choisirStatut(1, statut)
      if (statut === 'retraite') {
        remplir('#p1-pension-base', '1500')
        cocher('p1-csg', 'median')
        cocher('p1-age', 'plus65')
      }
      $<HTMLSelectElement>('#zone').value = zone
      soumettre()
      await attendreQue(() => !!main.querySelector('#retour .avertissement'))
      expect(main.querySelector('#retour .avertissement')?.getAttribute('tabindex')).toBe('-1')
      expect(texte()).toContain(message)
      expect(texte()).toContain('Ce cas n’est pas encore couvert par le calcul.')
      expect(main.querySelector('#retour a')?.getAttribute('href')).toBe('./#/explorer')
    }
  })
})

describe('accessibilité du formulaire', () => {
  it('chaque champ a son libellé, chaque groupe de choix son fieldset et sa legend, chaque message est relié', async () => {
    session.profil = null
    await ecran('#/calcul')
    const champs = Array.from(main.querySelectorAll<HTMLInputElement | HTMLSelectElement>('#formulaire input, #formulaire select'))
    expect(champs.length).toBeGreaterThan(40)
    for (const c of champs) {
      const libelle = c.closest('label') ?? (c.id ? main.querySelector(`label[for="${c.id}"]`) : null)
      expect(libelle, `${c.id || c.getAttribute('name')} sans libellé`).not.toBeNull()
    }
    // Boutons radio des personnes : dans un fieldset avec legend (les autres groupes du formulaire aussi, ou role=radiogroup nommé).
    for (const r of Array.from(main.querySelectorAll<HTMLInputElement>('#p1-bloc input[type=radio], #p2-bloc input[type=radio]'))) {
      const groupe = r.closest('fieldset')!
      expect(groupe.querySelector(':scope > legend')?.textContent?.trim(), r.name).toBeTruthy()
      expect(groupe.id, r.name).toBe(r.name)
    }
    const decrits = new Set(Array.from(main.querySelectorAll('[aria-describedby]')).flatMap((el) => el.getAttribute('aria-describedby')!.split(/\s+/)))
    for (const m of Array.from(main.querySelectorAll('.message-champ'))) expect(decrits.has(m.id), `${m.id} non relié`).toBe(true)
    for (const id of decrits) expect(document.getElementById(id), `aria-describedby vers ${id} absent`).not.toBeNull()
    const ids = Array.from(main.querySelectorAll('[id]')).map((x) => x.id)
    expect(ids.length).toBe(new Set(ids).size)
  })
})

describe('textes du profil retenu', () => {
  it('description des personnes, limites propres à chaque profil, lignes sans destinataire publié', () => {
    const profil = versSaisie(CAS.find((c) => c.id === 'X01')!.profil)
    const r = calculerProfil(profil, { affectation })
    if (r.statut !== 'ok') throw new Error('X01')
    expect(norm(descriptionPersonne(profil.personnes[0], r.entree.personnes[0]))).toMatch(/^Fonctionnaire titulaire, fonction publique de l’État : traitement indiciaire brut de 2 600 € par mois et primes de 400 € brut par mois, soit [\d\s]+ € net avant impôt par mois\.$/)
    const limites = norm(limitesDuCalcul(profil, r, false).join(' '))
    expect(limites).toContain('Centre national de la fonction publique territoriale')
    expect(limites).toContain('Complémentaire santé')
    // Retenue pour pension civile : destinataire publié depuis l'affectation étendue (vague 3), plus dans les limites.
    expect(limites).not.toContain('Retenue pour pension civile')
    // Lignes de l'employeur sans destinataire publié : citées seulement s'il en reste avec l'affectation publiée.
    const employeurSans = r.prelevements.some((l) => l.destinataire.id === 'non_affecte' && l.famille === 'cotisation_patronale')
    expect(limites.includes('de la part de l’employeur')).toBe(employeurSans)
    expect(limites).toContain('Commune non précisée')
    expect(limites).not.toContain('Cipav')
    expect(norm(resumeProfil(profil, r))).toMatch(/^En couple marié ou pacsé, 2 enfants ; toi : fonctionnaire titulaire, [\d\s]+ € net avant impôt par mois ; ton ou ta conjoint·e : salarié·e du secteur privé, 2 100 € net avant impôt par mois$/)
  })

  it('calcul sur l’appareil : seules les données du site sont lues (aucune requête externe)', () => {
    expect(requetes.length).toBeGreaterThan(0)
    for (const u of requetes) expect(u).toMatch(/^data\//)
  })
})

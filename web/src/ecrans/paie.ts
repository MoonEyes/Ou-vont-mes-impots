// Écran 2 : ce que tu paies (total annuel, ligne par ligne avec destinataire, patronal à part).
import { DESTINATAIRES, LIBELLE_ADMINISTRATION } from '../calcul/destinataires'
import type { Famille, Prelevement, ResultatOk } from '../calcul/types'
import { charger, manifeste } from '../donnees'
import { session } from '../etat'
import { appliquerLargeurs, barres, eur, estFourchette, fourchette, h, pct, source } from '../util'

const FAMILLES: [Famille, string][] = [
  ['cotisation_salariale', 'Cotisations sociales prélevées sur ton salaire'],
  ['csg_crds', 'CSG et CRDS'],
  ['impot_revenu', 'Impôt sur le revenu'],
  ['impot_local', 'Impôts locaux'],
]

const PERSONNES: Record<string, string> = { declarant1: '', declarant2: ' (personne 2)', foyer: '', logement: '' }

function ligne(l: Prelevement, couple: boolean): string {
  const m = l.montant_annuel_eur
  const dest = l.ventilation?.length
    ? l.ventilation.map((v) => `${DESTINATAIRES[v.destinataire].nom} ${pct(v.part * 100, 0)}`).join(', ')
    : l.destinataire.nom
  const admin = LIBELLE_ADMINISTRATION[l.destinataire.administration]
  return `<li${l.nature === 'reduction' ? ' class="reduction"' : ''}>
    <span>${h(l.libelle)}${couple ? h(PERSONNES[l.personne] ?? '') : ''}</span>
    <span class="montant">${l.nature === 'reduction' ? '− ' : ''}${h(fourchette(m))}<span class="visuellement-cache"> par an</span></span>
    <span class="dest">Va à : ${h(dest)}${admin !== dest ? ` <span class="badge">${h(admin)}</span>` : ''}${
      estFourchette(m) ? ` · estimation (central ${h(eur(m.central))})` : ''
    }</span>
  </li>`
}

function blocTotal(r: ResultatOk): string {
  const t = r.totaux.paye_par_le_foyer
  const net = r.entree.personnes.reduce((s, p) => s + p.salaire_net_avant_impot_annuel, 0)
  const brut = r.entree.personnes.reduce((s, p) => s + p.salaire_brut_annuel_estime.central, 0)
  return `<div class="carte">
    <p>Chaque année, ton foyer paie</p>
    <p class="grand-chiffre">${h(fourchette(t))}</p>
    <p class="sous-chiffre">soit ${h(fourchette(t, 12))} par mois, pour un salaire brut de ${h(eur(brut))} par an (${h(eur(net))} net avant impôt).</p>
    <p class="aide">Hors TVA et autres taxes sur ta consommation, et hors cotisations payées par ton employeur (bloc séparé plus bas).</p>
  </div>`
}

async function blocConsommation(): Promise<string> {
  const m = await manifeste()
  const fichiers = m.optionnels.prelevements
  if (!fichiers || !fichiers.length)
    return `<div class="carte"><h2>TVA et taxe foncière</h2><p><strong>Estimation à venir.</strong> La TVA que tu paies en consommant et la taxe foncière estimée pour ta commune seront ajoutées quand les données seront publiées par le site.</p></div>`
  // Dossier prelevements/ présent : on affiche sa provenance ; le chiffrage personnel suit son contrat.
  const infos: string[] = []
  for (const f of fichiers.slice(0, 5)) {
    try {
      const d = await charger<{ millesime?: string; source?: string; libelle?: string }>(f)
      infos.push(`${d.libelle ?? f}${d.millesime ? `, ${d.millesime}` : ''}${d.source ? ` (${d.source})` : ''}`)
    } catch {
      /* fichier illisible : ignoré, signalé par l'absence */
    }
  }
  return `<div class="carte"><h2>TVA et taxe foncière</h2><p><strong>Estimation à venir sur cet écran.</strong> Les données sont publiées et en cours d’intégration :</p><ul>${infos
    .map((i) => `<li>${h(i)}</li>`)
    .join('')}</ul></div>`
}

function blocTaxeFonciere(): string {
  const taux = session.communeTaux
  if (!session.communeNom || !taux) return ''
  const [tfb, teom] = taux
  return `<div class="carte"><h3>Taux locaux de ${h(session.communeNom)}</h3>
    <p>Taxe foncière sur les propriétés bâties : <strong>${tfb === null ? 'non publié' : h(pct(tfb, 2))}</strong> de la valeur locative cadastrale (commune, intercommunalité et taxes annexes).</p>
    <p>Taxe d’enlèvement des ordures ménagères : <strong>${teom === null ? 'pas de TEOM (redevance ou budget général)' : h(pct(teom, 2))}</strong>.</p>
    ${source('data.economie.gouv.fr, fiscalité locale des particuliers (DGFiP)', 'exercice 2025')}</div>`
}

export async function rendre(cible: HTMLElement) {
  const r = session.resultat
  if (!r) {
    cible.innerHTML = `<h1>Ce que tu paies</h1><p>Indique d’abord ton salaire pour voir ce que tu paies et à qui.</p><p><a class="bouton bouton-principal" href="#/">Saisir mon salaire</a></p><p><a href="#/etat">Ou explorer le budget de l’État</a></p>`
    return
  }
  const couple = r.entree.personnes.length > 1
  const groupes = FAMILLES.map(([fam, titre]) => {
    const ls = r.prelevements.filter((l) => l.famille === fam)
    if (!ls.length) return ''
    return `<h3>${h(titre)}</h3><ul class="lignes">${ls.map((l) => ligne(l, couple)).join('')}</ul>`
  }).join('')

  const patronales = r.prelevements.filter((l) => l.famille === 'cotisation_patronale')
  const avert = r.avertissements
    .filter((a) => a.code !== 'DONNEE_ABSENTE')
    .map((a) => `<p class="avertissement">${h(a.message)}</p>`)
    .join('')
  const csgAbsente = r.avertissements.find((a) => a.code === 'DONNEE_ABSENTE')

  const parDest = (avecPatronal: boolean) => {
    const moteur = import('../calcul/moteur')
    return moteur.then((m) => {
      const lignes = m.parDestinataire(r.prelevements, avecPatronal)
      return barres(
        lignes.map((x) => ({
          nom: `${DESTINATAIRES[x.destinataire].nom} (${LIBELLE_ADMINISTRATION[DESTINATAIRES[x.destinataire].administration]})`,
          valeur: x.montant_annuel_eur.central,
          texte: fourchette(x.montant_annuel_eur),
        })),
        undefined,
        'Montant annuel par destinataire',
      )
    })
  }

  cible.innerHTML = `
<h1>Ce que tu paies</h1>
${blocTotal(r)}
${avert}
<h2>Ligne par ligne, et qui le reçoit</h2>
${groupes}
${csgAbsente ? `<p class="aide">${h(csgAbsente.message)}</p>` : ''}
${blocTaxeFonciere()}
<div id="conso"><p class="chargement">Chargement…</p></div>
<h2>Par destinataire</h2>
<div class="bascule" role="group" aria-label="Contenu de la répartition">
  <button type="button" id="sans-patronal" aria-pressed="true">Ce que tu paies</button>
  <button type="button" id="avec-patronal" aria-pressed="false">Avec la part de l’employeur</button>
</div>
<div id="par-destinataire" aria-live="polite"></div>
<section class="carte" aria-labelledby="titre-patronal">
  <h2 id="titre-patronal">En plus : ce que paie ton employeur</h2>
  <p>Ces cotisations ne sont pas prélevées sur ton salaire brut : ton employeur les verse en plus. Elles financent les mêmes caisses. Total annuel : <strong>${h(fourchette(r.totaux.patronal))}</strong>${
    r.totaux.cout_total_employeur ? `. Coût total pour l’employeur (brut et cotisations patronales) : ${h(fourchette(r.totaux.cout_total_employeur))}` : ''
  }.</p>
  ${estFourchette(r.totaux.patronal) ? `<p class="aide">Fourchette : le taux d’accidents du travail, le versement mobilité, la taille de l’entreprise et la réduction générale dépendent de ton employeur, que le site ne connaît pas.</p>` : ''}
  <ul class="lignes">${patronales.map((l) => ligne(l, couple)).join('')}</ul>
  <p class="aide">Non comptées : participation à l’effort de construction (Action Logement) et contribution au dialogue social, versées à des organismes hors administrations publiques ; complémentaire santé et prévoyance d’entreprise, variables d’un employeur à l’autre.</p>
</section>
<p class="source">Calcul sur ton appareil avec modele-social ${h(r.moteur.version)} (règles de l’Urssaf, licence MIT) et publicodes ${h(r.moteur.publicodes ?? '')}, législation ${h(r.annee_legislation)}. Vérifié sur 20 cas types face à OpenFisca : écart inférieur à 1 % sur le brut, les cotisations salariales, la CSG, la CRDS et l’impôt (voir <a href="#/methode">méthode</a>).</p>
<div class="actions">
  <a class="bouton" href="#/">Modifier ma saisie</a>
  <a class="bouton bouton-principal" href="#/etat">Où va l’argent de l’État ?</a>
</div>`

  const zone = cible.querySelector('#par-destinataire') as HTMLElement
  const montrer = async (avec: boolean) => {
    zone.innerHTML = await parDest(avec)
    appliquerLargeurs(zone)
    cible.querySelector('#sans-patronal')?.setAttribute('aria-pressed', String(!avec))
    cible.querySelector('#avec-patronal')?.setAttribute('aria-pressed', String(avec))
  }
  cible.querySelector('#sans-patronal')?.addEventListener('click', () => montrer(false))
  cible.querySelector('#avec-patronal')?.addEventListener('click', () => montrer(true))
  await montrer(false)
  const conso = cible.querySelector('#conso') as HTMLElement
  conso.innerHTML = await blocConsommation()
}

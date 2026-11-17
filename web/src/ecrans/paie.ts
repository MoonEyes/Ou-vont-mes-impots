// Écran 2 : ce que tu verses (total annuel, ligne par ligne avec destinataire, patronal à part).
import { parDestinataire } from '../calcul/agregats'
import { destinataire, LIBELLE_ADMINISTRATION } from '../calcul/destinataires'
import type { Complet } from '../calcul/hors-bulletin'
import type { Famille, Prelevement, ResultatOk } from '../calcul/types'
import { session } from '../etat'
import { ORDRE_ADMIN, NOM_SUR100 } from '../calcul/repartition'
import { billet, type Famille as FamilleBillet, FAMILLE_ADMIN, listeParts, partsAdministrations, tableauBillet } from '../composants/billet'
import { filEuro } from '../composants/fil-euro'
import { resumer, sorties } from '../composants/resume-calcul'
import { appliquerLargeurs, badgeStatut, barres, entier, eur, estFourchette, fourchette, h, lireLesMotifs, nomVille, pct, source, type Statut, STATUTS, surligne, traitStatut } from '../util'

const FAMILLES: [Famille, string][] = [
  ['cotisation_salariale', 'Cotisations sociales prélevées sur ton salaire'],
  ['csg_crds', 'CSG et CRDS'],
  ['impot_revenu', 'Impôt sur le revenu'],
  ['taxe_consommation', 'Taxes sur ta consommation (estimation)'],
  ['impot_local', 'Impôts locaux'],
]

const PERSONNES: Record<string, string> = { declarant1: '', declarant2: ' (personne 2)', foyer: '', logement: '' }

/** Statut d'une ligne (motif + libellé) : non chiffré, ou estimation ; rien pour un calcul exact. */
function statutLigne(l: Prelevement): string {
  const s: Statut | null = l.non_chiffre
    ? 'nonpub'
    : l.famille === 'taxe_consommation' || estFourchette(l.montant_annuel_eur) || (l.famille === 'impot_local' && l.regle.startsWith('prelevements/'))
      ? 'approche'
      : null
  return s ? `${traitStatut(s)}<strong>${STATUTS[s].libelle}</strong> · ` : ''
}

function ligne(l: Prelevement, couple: boolean): string {
  const m = l.montant_annuel_eur
  const admin = LIBELLE_ADMINISTRATION[l.destinataire.administration]
  const parts = l.ventilation && l.ventilation.length > 1
  const dest = parts
    ? l.ventilation!.map((v) => `${destinataire(v.destinataire).nom} ${pct(v.part * 100, v.part < 0.01 ? 1 : 0)}`).join(', ')
    : l.destinataire.nom
  const nonSourcee = l.statut_affectation === 'non sourcee' ? ' · répartition non sourcée' : ''
  const montant = l.non_chiffre ? 'non chiffré' : `${l.nature === 'reduction' ? '− ' : ''}${fourchette(m)}`
  return `<li${l.nature === 'reduction' ? ' class="reduction"' : ''}>
    <span>${h(l.libelle)}${couple ? h(PERSONNES[l.personne] ?? '') : ''}</span>
    <span class="montant">${h(montant)}${l.non_chiffre ? '' : '<span class="visuellement-cache"> par an</span>'}</span>
    <span class="dest">${statutLigne(l)}Va à : ${h(dest)}${!parts && admin !== dest ? ` <span class="badge badge-admin">${h(admin)}</span>` : ''}${h(nonSourcee)}${
      !l.non_chiffre && estFourchette(m) ? ` · estimation (central ${h(eur(m.central))})` : ''
    }${l.note ? `<br />${h(l.note)}` : ''}</span>
  </li>`
}

function profilTexte(): string {
  const p = session.profil
  if (!p) return ''
  const sit: Record<string, string> = {
    celibataire: 'Seul·e',
    parent_isole: 'Seul·e avec enfant(s)',
    couple_marie_pacse: 'En couple marié ou pacsé',
    couple_union_libre: 'En couple',
  }
  const n = p.foyer.enfants.length
  const nets = p.personnes.filter((x) => x.salaire_net_avant_impot_mensuel).map((x) => eur(x.salaire_net_avant_impot_mensuel!))
  return `${sit[p.foyer.situation]}, ${n ? `${n} enfant${n > 1 ? 's' : ''}` : 'sans enfant'}, ${nets.join(' et ')} net avant impôt par mois`
}

/** Qui bénéficie, en exemples sans montant (les montants sont dans chaque thème d'Explorer). */
const POUR_QUI: Record<string, string[]> = {
  'Securite sociale': ['Retraités', 'Malades et hôpitaux', 'Familles'],
  Etat: ['Élèves et enseignants', 'Armées, police, justice'],
  'Collectivites locales': ['Ta commune'],
  Plusieurs: ['Destinataire non publié'],
}

/** Carte principale « Ce que tu verses en un an » : total, jauge de la fourchette, répartition sur 100 €. */
function blocTotal(r: ResultatOk, c: Complet | null): string {
  const t = c ? c.total : r.totaux.paye_par_le_foyer
  const net = r.entree.personnes.reduce((s, p) => s + p.salaire_net_avant_impot_annuel, 0)
  const s100 = resumer(r, c).sur100
  const phrase = ORDRE_ADMIN.filter((a) => s100[a] !== undefined)
    .map((a) => `<strong>${s100[a]} €</strong> ${h(NOM_SUR100[a])}`)
    .join(', ')
  const plage = estFourchette(t)
  return `<section class="recap" data-cle aria-labelledby="titre-recap">
    <h2 id="titre-recap" class="recap-titre">Ce que tu verses en un an${plage ? ', environ' : ''}</h2>
    <p class="grand-chiffre">${surligne(eur(t.central))}</p>
    ${
      plage
        ? `<div class="jauge" aria-hidden="true"><span class="j-plein" data-l="${((t.bas / t.haut) * 100).toFixed(1)}"></span><span class="j-points" data-l="${(((t.haut - t.bas) / t.haut) * 100).toFixed(1)}"></span></div>
    <p class="jauge-bornes">Fourchette : ${h(eur(t.bas))} à ${h(eur(t.haut))}</p>
    <p class="aide">La fourchette dépend de ce que tu achètes et de tes impôts locaux.</p>`
        : ''
    }
    <p class="recap-sur100">Sur 100 € : ${phrase}.</p>
    <p class="aide">Soit ${h(eur(t.central / 12))} par mois, pour ${h(eur(net))} net avant impôt par an. Hors cotisations de ton employeur (plus bas)${
      c?.lignes.some((l) => l.non_chiffre) ? ' ; les montants « non chiffré » ne sont pas comptés' : ''
    }.</p>
    <p class="source">calcul sur ton appareil (modele-social, vérifié face à OpenFisca), Insee, PLF et PLFSS 2026, DGFiP. <a href="#/methode">Méthode</a></p>
  </section>`
}

/** Billet personnel, parts sur 100 €, les trois sorties et le fil de l'euro. */
function blocBillet(r: ResultatOk, c: Complet | null): { gauche: string; droite: string; fil: string } {
  const res = resumer(r, c)
  const parts = partsAdministrations(res.sur100, ORDRE_ADMIN)
  const locataire = session.profil?.logement?.statut !== 'proprietaire'
  const lignes = sorties(res.sources, locataire)
  const consoAbsente = !res.sources.achats
  const orduresNonChiffre = !!c && c.locaux.length > 0 && c.locaux.every((l) => l.non_chiffre)
  return {
    gauche: `<h2>Ton billet de 100 €</h2>
${billet(parts, { etiquette: 'Ton billet de 100 € découpé par destinataire' })}
${tableauBillet(parts, 'Sur 100 € que tu verses, par destinataire')}`,
    droite: `<h2>Où ça va, sur 100 €</h2>
${listeParts(parts, 'Où vont 100 € que tu verses')}
<h2>D’où ça sort</h2>
<p class="chapeau">${lignes.length > 1 ? 'Ce qui est pris sur ton salaire, ce que tu verses en achetant, et tes impôts locaux.' : 'Ce qui est pris sur ton salaire.'}</p>
<ul class="postes">${lignes
      .map((l) => `<li><span class="p-nom">${h(l.nom)}<small>${h(l.detail)}</small></span><span class="p-montant">${h(l.texte)}</span>${badgeStatut(l.statut)}</li>`)
      .join('')}${consoAbsente ? `<li><span class="p-nom">Sur tes achats<small>TVA et taxes sur la consommation</small></span><span class="p-montant">non disponible</span>${badgeStatut('nonpub')}</li>` : ''}${
      orduresNonChiffre ? `<li><span class="p-nom">Impôts locaux<small>${locataire ? 'TEOM (dans tes charges)' : 'Taxe foncière et TEOM'}</small></span><span class="p-montant">non chiffré</span>${badgeStatut('nonpub')}</li>` : ''
    }</ul>`,
    fil: `<h2>Le fil de l’euro</h2>
<p class="chapeau">De ce qui sort de ta poche jusqu’à ceux qui reçoivent. L’épaisseur de chaque ruban suit le montant.</p>
${filEuro(
  lignes.map((l) => ({ nom: l.nom, court: l.court, texte: l.texte, valeur: l.f.central, statut: l.statut })),
  eur(res.total.central),
  ORDRE_ADMIN.filter((a) => res.sur100[a] !== undefined).map((a) => ({ nom: FAMILLE_ADMIN[a].nom.replace('Sans destinataire publié', 'Non publié'), texte: `${res.sur100[a]} €`, valeur: res.sur100[a], famille: FAMILLE_ADMIN[a].famille as FamilleBillet, pour: POUR_QUI[a] ?? [] })),
)}
<p class="aide">Les bénéficiaires cités sont des exemples. Leurs montants sont dans chaque thème d’<a href="#/explorer">Explorer</a>.</p>`,
  }
}

function blocPlacement(c: Complet | null): string {
  const p = c?.placement
  if (!p) return ''
  return `<p class="aide">Pour estimer tes taxes sur la consommation, ton foyer compte ${h(String(p.unites_consommation).replace('.', ','))} unité${
    p.unites_consommation > 1 ? 's' : ''
  } de consommation ; revenu disponible estimé ${h(eur(p.revenu_disponible_eur))} par an (salaires nets moins impôt sur le revenu, sans prestations ni autres revenus), soit un niveau de vie de ${h(
    eur(p.niveau_de_vie_eur),
  )} : <strong>${h(entier(p.decile))}e décile</strong> sur 10. Montants moyens de ce décile, recalés sur 2025.</p>
  <p class="source">Insee (comptes nationaux distribués 2019, Budget de famille 2017, ERFS 2024), Eurostat ; site/data/prelevements/tva_conso.json</p>`
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
    // Pas de saisie : retour au formulaire, avec un message.
    location.hash = '#/calcul?retour=resultat'
    cible.innerHTML = `<h1>Ce que tu verses</h1><p>Indique d’abord ton salaire.</p><p><a href="#/calcul">Saisir mon salaire</a></p>`
    return
  }
  const c = session.complet
  const patronales = r.prelevements.filter((l) => l.famille === 'cotisation_patronale')
  const couple = r.entree.personnes.length > 1
  const toutes = c ? c.lignes : r.prelevements.filter((l) => l.inclus_dans_total_paye)
  const groupes = FAMILLES.map(([fam, titre]) => {
    const ls = toutes.filter((l) => l.famille === fam)
    if (!ls.length) return fam === 'taxe_consommation' ? `<h3>${h(titre)}</h3><p class="absent">Donnée non disponible.</p>` : ''
    return `<h3>${h(titre)}</h3>${fam === 'taxe_consommation' ? blocPlacement(c) : ''}<ul class="lignes">${ls.map((l) => ligne(l, couple)).join('')}</ul>`
  }).join('')

  const avert = r.avertissements
    .filter((a) => a.code !== 'DONNEE_ABSENTE')
    .map((a) => `<p class="avertissement">${h(a.message)}</p>`)
    .join('')
  const csgAbsente = r.avertissements.find((a) => a.code === 'DONNEE_ABSENTE')

  const parDest = (avecPatronal: boolean) => {
    return Promise.resolve().then(() => {
      const lignes = parDestinataire(avecPatronal ? [...toutes, ...patronales] : toutes, avecPatronal)
      return barres(
        lignes.map((x) => ({
          nom: `${destinataire(x.destinataire).nom} (${LIBELLE_ADMINISTRATION[destinataire(x.destinataire).administration]})`,
          valeur: x.montant_annuel_eur.central,
          texte: fourchette(x.montant_annuel_eur),
        })),
        undefined,
        'Montant annuel par destinataire',
      )
    })
  }

  const bb = blocBillet(r, c)
  cible.innerHTML = `
<h1>Ce que tu verses en un an</h1>
<p class="chapeau">${h(profilTexte())}${session.communeNom ? `, à ${h(nomVille(session.communeNom))}` : ''}. <a href="#/calcul">Modifier mon salaire</a></p>
<div class="colonnes">
  <div>
    ${blocTotal(r, c)}
    ${bb.gauche}
    <div class="actions">
      <a class="bouton bouton-principal" href="#/explorer/etat">Suivre mes euros</a>
      <button type="button" id="partager-carte">Partager ma carte</button>
    </div>
    <p class="aide" id="partage-info">La carte est une image de ton billet, créée sur ton appareil. Aucun montant n’est mis dans une adresse ni envoyé au site.</p>
    ${lireLesMotifs()}
  </div>
  <div>
    ${bb.droite}
  </div>
</div>
${bb.fil}
${avert}
<h2>Ligne par ligne, et qui le reçoit</h2>
${groupes}
${csgAbsente ? `<p class="aide">${h(csgAbsente.message)}</p>` : ''}
${blocTaxeFonciere()}
<h2>Par destinataire</h2>
<div class="bascule" role="group" aria-label="Contenu de la répartition">
  <button type="button" id="sans-patronal" aria-pressed="true">Ce que tu verses</button>
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
<div class="actions"><a class="bouton" href="#/calcul">Modifier ma saisie</a></div>
<h2>Et maintenant ?</h2>
<ul class="cartes par-3">
  <li><a href="#/explorer/etat"><strong>Où va l’argent de l’État</strong><span>Les grands postes du budget, jusqu’à la ligne votée.</span></a></li>
  <li><a href="${session.profil?.residence.commune_insee ? `#/local/commune?insee=${encodeURIComponent(session.profil.residence.commune_insee)}` : '#/local'}"><strong>Ta commune</strong><span>Son budget, ses impôts locaux, ce que l’État lui verse.</span></a></li>
  <li><a href="#/beneficiaires"><strong>Qui le reçoit</strong><span>Associations, entreprises, organismes : les bénéficiaires nommés.</span></a></li>
</ul>`

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
  cible.querySelector('#partager-carte')?.addEventListener('click', async () => {
    const info = cible.querySelector('#partage-info') as HTMLElement
    try {
      const { partagerCarte } = await import('../composants/carte-partage')
      info.textContent = await partagerCarte(r, c)
    } catch {
      info.textContent = 'Impossible de créer l’image sur cet appareil.'
    }
  })
}

// « Le reçu de l'année » (audit design du 19/11, proposition 2) : ce que tu verses en un an, une ligne par
// destinataire, au format ticket de caisse (colonne de 20rem, chiffres en Bricolage, perforation en haut et en bas),
// le motif tracé / approché / non publié dans la marge, la date et le millésime des barèmes en pied. Un reçu constate,
// il ne juge pas. Imprimable et partageable ; par défaut, sans aucun montant en euros (parts sur 100 € seulement),
// comme la carte du résultat : une case explicite ajoute les montants. Tout reste en mémoire de la page.
import { parDestinataire } from '../calcul/agregats'
import { destinataire } from '../calcul/destinataires'
import { sur100Entiers } from '../calcul/repartition'
import type { Prelevement, ResultatOk } from '../calcul/types'
import type { Complet } from '../calcul/hors-bulletin'
import { ADRESSE_SITE, MENTION } from '../composants/carte-partage'
import { type NiveauCollectivite, niveauDestinataire, pastilleNiveau } from '../composants/niveaux'
import { session } from '../etat'
import { annoncer, badgeCalcule, estFourchette, fourchette, h, STATUTS, type Statut, traitStatut } from '../util'

export const METHODE_RECU =
  'somme des lignes 2025 de ton foyer qui vont à chaque destinataire (une ligne partagée entre plusieurs destinataires l’est selon sa répartition légale) ; sur 100 € : cette somme divisée par ce que tu verses en un an, arrondie à l’euro pour que les lignes fassent 100'

export interface LigneRecu {
  nom: string
  /** niveau de collectivité du destinataire (pastille de couleur), null sinon */
  niveau: NiveauCollectivite | null
  statut: Statut
  sur100: number
  montant: string
}

const RANG: Record<Statut, number> = { trace: 0, approche: 1, nonpub: 2 }

/** Statut d'une ligne du calcul : même règle que la liste « Ligne par ligne » du résultat. */
function statutLigne(l: Prelevement): Statut {
  return l.famille === 'taxe_consommation' || estFourchette(l.montant_annuel_eur) || (l.famille === 'impot_local' && l.regle.startsWith('prelevements/')) ? 'approche' : 'trace'
}

/** Une ligne par destinataire : statut le moins sûr de ce qui lui arrive, part sur 100 €, montant (fourchette). */
export function lignesRecu(r: ResultatOk, c: Complet | null): LigneRecu[] {
  const toutes = (c ? c.lignes : r.prelevements.filter((l) => l.inclus_dans_total_paye)).filter((l) => !l.non_chiffre)
  const statuts = new Map<string, Statut>()
  const noter = (id: string, s: Statut) => {
    const avant = statuts.get(id)
    if (!avant || RANG[s] > RANG[avant]) statuts.set(id, s)
  }
  for (const l of toutes) {
    const s = statutLigne(l)
    if (l.ventilation?.length) for (const v of l.ventilation) noter(v.destinataire, l.statut_affectation === 'non sourcee' ? 'nonpub' : s)
    else noter(l.destinataire.id, l.statut_affectation === 'non sourcee' ? 'nonpub' : s)
  }
  const groupes = parDestinataire(toutes, false).filter((g) => g.montant_annuel_eur.central > 0)
  const s100 = sur100Entiers(Object.fromEntries(groupes.map((g) => [g.destinataire, g.montant_annuel_eur.central])))
  return groupes.map((g) => {
    const d = destinataire(g.destinataire)
    return {
      // Nom seul, comme sur un ticket : la famille (Sécurité sociale, État…) est déjà dans le billet du résultat.
      nom: d.nom,
      niveau: niveauDestinataire(g.destinataire),
      statut: g.destinataire === 'non_affecte' ? 'nonpub' : (statuts.get(g.destinataire) ?? 'trace'),
      sur100: s100[g.destinataire] ?? 0,
      montant: fourchette(g.montant_annuel_eur),
    }
  })
}

/** « 0 € » sur 100 ne veut pas dire rien : la part arrondie à l'euro est sous 1 €. */
const part100 = (x: number) => (x > 0 ? `${x} €` : 'moins de 1 €')

const dateFr = (d: Date) => new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }).format(d)

/** Le ticket : sans montants par défaut ; avec montants seulement si la personne le demande. */
export function ticket(r: ResultatOk, c: Complet | null, montants: boolean, aujourdhui = new Date()): string {
  const lignes = lignesRecu(r, c)
  const total = c ? c.total : r.totaux.paye_par_le_foyer
  const colonne = montants ? 'En un an' : 'Sur 100 €'
  return `<article class="recu" aria-labelledby="recu-titre">
  <p class="recu-marque">Où vont mes impôts</p>
  <h2 id="recu-titre">Reçu de l’année ${h(r.annee_legislation)}</h2>
  <p class="recu-sous">${montants ? 'Ce que tu verses en un an, par destinataire' : 'Sur 100 € que tu verses, par destinataire'}</p>
  <table class="recu-lignes"><caption class="visuellement-cache">${montants ? 'Montant annuel' : 'Part sur 100 €'} par destinataire, avec le statut de chaque ligne</caption>
  <thead><tr><th scope="col"><span class="visuellement-cache">Statut</span></th><th scope="col">Destinataire</th><th scope="col" class="nombre">${colonne}</th></tr></thead>
  <tbody>${lignes
    .map((l) => `<tr><td class="recu-marge">${traitStatut(l.statut)}<span class="visuellement-cache">${h(STATUTS[l.statut].libelle)}</span></td><th scope="row">${pastilleNiveau(l.niveau)}${h(l.nom)}</th><td class="nombre">${h(montants ? l.montant : part100(l.sur100))}</td></tr>`)
    .join('')}</tbody>
  <tfoot><tr><td></td><th scope="row">Total</th><td class="nombre">${h(montants ? fourchette(total) : '100 €')}</td></tr></tfoot>
  </table>
  <ul class="recu-legende" aria-label="Motifs de la marge">${(['trace', 'approche', 'nonpub'] as Statut[]).map((s) => `<li>${traitStatut(s)}${h(STATUTS[s].libelle)}</li>`).join('')}</ul>
  <p class="recu-methode">${badgeCalcule(METHODE_RECU)}</p>
  <p class="recu-pied">Édité le ${h(dateFr(aujourdhui))}<br />Barèmes et législation ${h(r.annee_legislation)}<br />${h(MENTION)}<br />${h(ADRESSE_SITE)}</p>
</article>`
}

/** Version texte du reçu, pour le partage : sans montants par défaut, comme le ticket. */
export function texteRecu(r: ResultatOk, c: Complet | null, montants: boolean, aujourdhui = new Date()): string {
  const lignes = lignesRecu(r, c)
  const total = c ? c.total : r.totaux.paye_par_le_foyer
  return [
    `Mon reçu de l’année ${r.annee_legislation} (Où vont mes impôts)`,
    montants ? 'Ce que je verse en un an, par destinataire :' : 'Sur 100 € que je verse :',
    ...lignes.map((l) => `${montants ? l.montant : part100(l.sur100)} : ${l.nom} (${STATUTS[l.statut].libelle.toLowerCase()})`),
    montants ? `Total : ${fourchette(total)}` : 'Total : 100 €',
    `Édité le ${dateFr(aujourdhui)}, barèmes ${r.annee_legislation}. ${MENTION}.`,
    ADRESSE_SITE,
  ].join('\n')
}

export async function partagerRecu(texte: string): Promise<string> {
  const nav = navigator as Navigator & { share?: (d: { title?: string; text?: string }) => Promise<void> }
  if (nav.share) {
    try {
      await nav.share({ title: 'Mon reçu de l’année', text: texte })
      return 'Reçu partagé.'
    } catch {
      return 'Partage annulé.'
    }
  }
  if (nav.clipboard?.writeText) {
    try {
      await nav.clipboard.writeText(texte)
      return 'Reçu copié : tu peux le coller où tu veux.'
    } catch {
      /* copie refusée : message ci-dessous */
    }
  }
  return 'Partage impossible sur cet appareil : utilise « Imprimer ».'
}

export function rendre(cible: HTMLElement) {
  const r = session.resultat
  if (!r) {
    cible.innerHTML = `<h1>Ton reçu de l’année</h1><p>Le reçu se fait à partir de ton calcul, qui reste sur ton appareil. Indique d’abord ton salaire.</p><p class="actions"><a class="bouton bouton-principal" href="#/calcul">Saisir mon salaire</a></p>`
    return
  }
  const c = session.complet
  cible.innerHTML = `<h1>Ton reçu de l’année</h1>
<p class="chapeau">Ce que tu verses, une ligne par destinataire, à imprimer ou partager. Un reçu constate : il ne juge aucune dépense.</p>
<div class="recu-options">
  <label class="case"><input type="checkbox" id="recu-montants" aria-describedby="recu-montants-aide" /> Afficher mes montants en euros</label>
  <p class="aide" id="recu-montants-aide">Sans cette case, le reçu montre seulement les parts sur 100 € : ni ce que tu verses en euros, ni ton salaire. Le partage suit ce choix.</p>
  <div class="actions"><button type="button" id="recu-imprimer">Imprimer</button><button type="button" id="recu-partager">Partager</button><a class="bouton-lien" href="#/calcul/resultat">Revenir à mon résultat</a></div>
  <p class="aide" id="recu-info" role="status"></p>
</div>
<div id="recu-zone" aria-live="polite">${ticket(r, c, false)}</div>`
  const caseMontants = cible.querySelector<HTMLInputElement>('#recu-montants')!
  const zone = cible.querySelector<HTMLElement>('#recu-zone')!
  const info = cible.querySelector<HTMLElement>('#recu-info')!
  caseMontants.addEventListener('change', () => {
    zone.innerHTML = ticket(r, c, caseMontants.checked)
    annoncer(caseMontants.checked ? 'Montants en euros affichés sur le reçu.' : 'Reçu sans montants : parts sur 100 € seulement.')
  })
  cible.querySelector('#recu-imprimer')!.addEventListener('click', () => window.print())
  cible.querySelector('#recu-partager')!.addEventListener('click', async () => {
    info.textContent = await partagerRecu(texteRecu(r, c, caseMontants.checked))
  })
}

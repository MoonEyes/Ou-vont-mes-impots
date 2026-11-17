// Écran 8 : vie politique par année (programme 232, aide publique aux partis, comptes de campagne).
// Seuls les candidats et les partis sont nommés (données publiques de la CNCCFP).
import { charger, chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { absent, entier, eur, eurLisible, h, source, sur100, surligne } from '../util'

interface AnneeVP {
  annee: number
  programme_232: {
    millesime: string
    source: string
    actions_eur: Record<string, number>
    total_actions_01_a_03_eur: number
    euros_sur_100_euros_etat?: number
    note?: string
    estimations?: string[]
  } | null
  programme_232_manquant?: string
  aide_publique_partis: { total_eur: number; premiere_fraction_eur: number; seconde_fraction_eur: number; nombre_partis: number; fichier: string; source: string } | null
  remboursements_campagne: { scrutin: string; libelle: string; remboursement_etat_total_eur: number; fichier: string }[]
  remboursements_campagne_total_eur: number
}
interface VP {
  millesime: string
  source: string
  perimetre: string
  annees: AnneeVP[]
  trous: string[]
}
interface Candidat {
  candidat: string
  nuance?: string
  circonscription?: string
  depenses_eur: number | null
  remboursement_eur: number | null
  decision?: string
}

const ACTIONS: Record<string, string> = {
  financement_des_partis: 'Financement des partis',
  organisation_des_elections: 'Organisation des élections',
  cnccfp: 'Commission des comptes de campagne (CNCCFP)',
}

const PAR_PAGE = 50

// Ordre d'affichage neutre et explicite (charte docs/NEUTRALITE.md) : jamais l'ordre brut du fichier source.
const alpha = (a: string, b: string) => a.localeCompare(b, 'fr', { sensitivity: 'base', numeric: true })
export const REGLE_PARTIS =
  'Ordre du tableau : aide publique totale, de la plus élevée à la plus faible (montant fixé par la loi d’après les résultats aux élections législatives et le nombre de parlementaires rattachés) ; à égalité, ordre alphabétique.'
export const REGLE_CANDIDATS = 'Ordre du tableau : circonscription, puis nom du candidat, par ordre alphabétique.'
export function trierPartis<T extends { nom: string; nom_tri?: string; total_eur: number }>(l: T[]): T[] {
  return [...l].sort((a, b) => b.total_eur - a.total_eur || alpha(a.nom_tri ?? a.nom, b.nom_tri ?? b.nom))
}
export function trierCandidats<T extends { candidat: string; circonscription?: string }>(l: T[]): T[] {
  return [...l].sort((a, b) => alpha(a.circonscription ?? '', b.circonscription ?? '') || alpha(a.candidat, b.candidat))
}

async function afficherCandidats(zone: HTMLElement, fichier: string, libelle: string) {
  zone.innerHTML = '<p class="chargement">Chargement des comptes de campagne…</p>'
  const d = await chargerSiPresent<{ millesime: string; source: string; candidats: Candidat[]; regle?: string }>(fichier)
  if (!d) {
    zone.innerHTML = absent()
    return
  }
  const candidats = trierCandidats(d.candidats)
  let page = 0
  let filtre = ''
  zone.innerHTML = `<h3>Candidats : ${h(libelle)}</h3>
<p class="aide" data-regle-ordre>${h(REGLE_CANDIDATS)}</p>
<label for="filtre-cand">Chercher un candidat, une nuance ou une circonscription</label>
<input id="filtre-cand" type="search" autocomplete="off" />
<div id="table-cand"></div>
${source(d.source, d.millesime)}`
  const table = zone.querySelector('#table-cand') as HTMLElement
  const dessiner = () => {
    const liste = candidats.filter((c) => !filtre || `${c.candidat} ${c.nuance ?? ''} ${c.circonscription ?? ''}`.toLowerCase().includes(filtre))
    const pages = Math.max(1, Math.ceil(liste.length / PAR_PAGE))
    page = Math.min(page, pages - 1)
    const tranche = liste.slice(page * PAR_PAGE, (page + 1) * PAR_PAGE)
    table.innerHTML = `<div class="tableau-defile"><table><caption>${h(entier(liste.length))} comptes, page ${page + 1} sur ${pages}</caption>
<thead><tr><th scope="col">Candidat</th><th scope="col">Nuance</th><th scope="col">Circonscription</th><th scope="col" class="nombre">Dépenses</th><th scope="col" class="nombre">Remboursé par l’État</th></tr></thead>
<tbody>${tranche
      .map(
        (c) =>
          `<tr><td>${h(c.candidat)}</td><td>${h(c.nuance ?? '')}</td><td>${h(c.circonscription ?? '')}</td><td class="nombre">${c.depenses_eur !== null ? h(eur(c.depenses_eur)) : ''}</td><td class="nombre">${
            c.remboursement_eur !== null ? h(eur(c.remboursement_eur)) : ''
          }</td></tr>`,
      )
      .join('')}</tbody></table></div>
<div class="pagination"><button type="button" data-p="-1"${page === 0 ? ' disabled' : ''}>Page précédente</button><button type="button" data-p="1"${page >= pages - 1 ? ' disabled' : ''}>Page suivante</button></div>`
    table.querySelectorAll<HTMLButtonElement>('[data-p]').forEach((b) =>
      b.addEventListener('click', () => {
        page += Number(b.dataset.p)
        dessiner()
      }),
    )
  }
  zone.querySelector<HTMLInputElement>('#filtre-cand')?.addEventListener('input', (e) => {
    filtre = (e.target as HTMLInputElement).value.trim().toLowerCase()
    page = 0
    dessiner()
  })
  dessiner()
}

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const vp = await charger<VP>('vie_politique/annees.json')
  const annees = vp.annees.map((a) => a.annee).sort((a, b) => b - a)
  const choisie = Number(params.get('a')) || annees.find((a) => vp.annees.find((x) => x.annee === a)?.programme_232) || annees[0]
  const a = vp.annees.find((x) => x.annee === choisie) ?? vp.annees[0]
  const p = a.programme_232
  const partis = a.aide_publique_partis ? await chargerSiPresent<{ millesime: string; source: string; definition: string; partis: { nom: string; nom_tri?: string; premiere_fraction_eur: number; seconde_fraction_eur: number; total_eur: number }[] }>(`vie_politique/${a.aide_publique_partis.fichier}`) : null

  cible.innerHTML = `
<h1>Vie politique en ${a.annee}</h1>
<p class="chapeau">Ce que l’État dépense au titre de la vie politique : organisation des élections, aide publique aux partis, remboursement des campagnes des candidats.</p>
<label for="annee-vp">Année</label>
<select id="annee-vp">${annees.map((x) => `<option value="${x}"${x === a.annee ? ' selected' : ''}>${x}</option>`).join('')}</select>
<h2>Programme 232 « Vie politique »</h2>
${
  p
    ? `<div class="carte" data-cle><p class="grand-chiffre">${surligne(eurLisible(p.total_actions_01_a_03_eur))}</p>${
        p.euros_sur_100_euros_etat !== undefined
          ? `<p class="sous-chiffre">soit ${h(sur100(p.euros_sur_100_euros_etat))} sur 100 € du budget général de l’État</p>`
          : '<p class="sous-chiffre">Part sur 100 € du budget général non calculable cette année (dépense totale de référence non publiée).</p>'
      }<ul>${Object.entries(p.actions_eur)
        .map(([k, v]) => `<li>${h(ACTIONS[k] ?? k)} : ${h(eurLisible(v))}${p.estimations?.includes(k) ? ' (estimation)' : ''}</li>`)
        .join('')}</ul>${p.note ? `<p class="aide">${h(p.note)}</p>` : ''}${source(p.source, p.millesime)}</div>`
    : absent(a.programme_232_manquant ?? 'Exécution par action non disponible pour cette année.')
}
<h2>Aide publique aux partis</h2>
${
  a.aide_publique_partis
    ? `<div class="carte"><p><strong>${h(eurLisible(a.aide_publique_partis.total_eur))}</strong> versés à ${h(a.aide_publique_partis.nombre_partis)} partis (1re fraction, selon les résultats aux législatives : ${h(eurLisible(a.aide_publique_partis.premiere_fraction_eur))} ; 2de fraction, selon les parlementaires rattachés : ${h(eurLisible(a.aide_publique_partis.seconde_fraction_eur))}).</p>
${
  partis
    ? `<div class="tableau-defile"><table><caption>Aide publique par parti, ${h(partis.millesime)}</caption><thead><tr><th scope="col">Parti</th><th scope="col" class="nombre">1re fraction</th><th scope="col" class="nombre">2de fraction</th><th scope="col" class="nombre">Total</th></tr></thead><tbody>${trierPartis(partis.partis)
        .map((x) => `<tr><td>${h(x.nom)}</td><td class="nombre">${h(eur(x.premiere_fraction_eur))}</td><td class="nombre">${h(eur(x.seconde_fraction_eur))}</td><td class="nombre">${h(eur(x.total_eur))}</td></tr>`)
        .join('')}</tbody></table></div><p class="aide" data-regle-ordre>${h(REGLE_PARTIS)}</p><p class="aide">${h(partis.definition)}</p>`
    : ''
}
${source(a.aide_publique_partis.source)}</div>`
    : absent('Comptes des partis pas encore publiés pour cette année.')
}
<h2>Remboursement des campagnes</h2>
${
  a.remboursements_campagne.length
    ? `<ul class="lignes">${a.remboursements_campagne
        .map(
          (s) =>
            `<li><span>${h(s.libelle)}</span><span class="montant">${h(eurLisible(s.remboursement_etat_total_eur))}</span><span class="dest"><button type="button" data-fichier="${h(s.fichier.replace('scrutins/', 'candidats/'))}" data-libelle="${h(s.libelle)}">Voir les candidats</button></span></li>`,
        )
        .join('')}</ul>`
    : '<p>Aucun scrutin remboursé cette année.</p>'
}
<div id="candidats" aria-live="polite"></div>
<details><summary>Limites des données</summary><ul>${vp.trous.map((t) => `<li>${h(t)}</li>`).join('')}</ul><p class="aide">${h(vp.perimetre)}</p></details>
${source(vp.source, vp.millesime)}`

  cible.querySelector<HTMLSelectElement>('#annee-vp')?.addEventListener('change', (e) => {
    location.hash = lien('/decisions/vie-politique', { a: (e.target as HTMLSelectElement).value })
  })
  const zone = cible.querySelector('#candidats') as HTMLElement
  cible.querySelectorAll<HTMLButtonElement>('[data-fichier]').forEach((b) =>
    b.addEventListener('click', () => afficherCandidats(zone, `vie_politique/${b.dataset.fichier}`, b.dataset.libelle ?? '')),
  )
}

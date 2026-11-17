// La dette publique (site/data/dette/) : encours, intérêts, détenteurs ; deux comptabilités jamais additionnées.
import { parAdministration } from '../calcul/repartition'
import { partPersonnelle } from '../composants/hub'
import { chargerSiPresent } from '../donnees'
import { session } from '../etat'
import { barres, eur, h, md, pct, source, sur100, surligne } from '../util'

type Serie = Record<string, number>
interface Index {
  millesime: string
  source: string
  avertissement: string
  synthese: {
    encours_maastricht: { annee: string; md: number; pct_pib: number; source: string }
    interets_apu_d41: { annee: string; md: number; pct_pib: number; source: string }
    programme_117: Record<string, number | string>
    interets_sur_100_eur_cas_c04?: number
  }
  dette_sociale?: { definition: string; asso_maastricht_md: Serie }
}
interface Interets {
  source: string
  avertissement: string
  nationale: { eurostat: { secteurs: Record<string, { libelle: string; md: Serie; part_depenses?: Serie }> } }
  cas_type?: { profil: { libelle: string }; par_administration: Record<string, { part_interets_dans_depenses: number }>; interets_sur_100_eur: number; methode: string }
}
interface Encours {
  source: string
  definition: string
  insee: Record<string, { libelle: string; md: Serie; pct_pib?: Serie }>
}
interface Detenteurs {
  source: string
  definition: string
  derniere_annee: string
  eurostat: Record<string, { libelle: string; md: Serie; part: Serie }>
}

/** État propre quand les fichiers ne sont pas encore produits. */
export const enCours = (titre: string, texte: string) =>
  `<h1>${titre}</h1><div class="en-cours"><p><strong>Données en cours d’intégration.</strong> ${texte}</p><p>Cette page se remplira dès que les fichiers seront publiés.</p></div>`

export async function rendre(cible: HTMLElement) {
  const [idx, int, enc, det] = await Promise.all([
    chargerSiPresent<Index>('dette/index.json'),
    chargerSiPresent<Interets>('dette/interets.json'),
    chargerSiPresent<Encours>('dette/encours.json'),
    chargerSiPresent<Detenteurs>('dette/detenteurs.json'),
  ])
  if (!idx) {
    cible.innerHTML = enCours('La dette publique', 'Encours de la dette, intérêts payés chaque année et détenteurs.') + partPersonnelle()
    return
  }
  const s = idx.synthese
  const s13 = int?.nationale.eurostat.secteurs.S13
  const partDep = s13?.part_depenses?.[s.interets_apu_d41.annee]
  // Ta part : chaque euro versé à une administration × part des intérêts dans ses dépenses.
  let perso = ''
  if (session.complet && int?.cas_type) {
    const parAdmin = parAdministration(session.complet.lignes)
    const ratios = int.cas_type.par_administration
    const interets = Object.entries(parAdmin).reduce((t, [a, v]) => t + v * (ratios[a]?.part_interets_dans_depenses ?? 0), 0)
    const total = Object.values(parAdmin).reduce((a, b) => a + b, 0)
    if (total > 0) perso = `<p>Pour toi : environ <strong>${h(eur(interets))}</strong> par an de ce que tu verses servent à payer des intérêts, soit ${h(sur100((interets / total) * 100))} sur 100 €.</p>`
  }
  const ensemble = enc?.insee.Ensemble
  const annees = ensemble ? Object.keys(ensemble.md).sort().filter((a) => Number(a) >= 2005) : []
  const derniere = det?.derniere_annee
  cible.innerHTML = `
<h1>La dette publique</h1>
<p class="chapeau">Ce que doivent l’État, la Sécurité sociale et les collectivités, ce que coûtent les intérêts chaque année, et qui détient cette dette.</p>
<div class="carte" data-cle>
  <p>Intérêts payés par l’ensemble des administrations en ${h(s.interets_apu_d41.annee)} :</p>
  <p class="grand-chiffre">${surligne(md(s.interets_apu_d41.md))}</p>
  <p class="sous-chiffre">${partDep !== undefined ? `soit ${h(sur100(partDep * 100))} sur 100 € de dépense publique, ` : ''}${h(pct(s.interets_apu_d41.pct_pib))} du PIB.</p>
  ${s.interets_sur_100_eur_cas_c04 !== undefined ? `<p>Pour un salarié seul au salaire médian (2 100 € net par mois), ${h(sur100(s.interets_sur_100_eur_cas_c04))} sur 100 € de ce qu’il verse servent aux intérêts.</p>` : ''}
  ${perso}
  ${source(s.interets_apu_d41.source)}
</div>
<h2>Combien est dû</h2>
<p>Dette au sens de Maastricht fin ${h(s.encours_maastricht.annee)} : <strong>${h(md(s.encours_maastricht.md))}</strong>, soit ${h(pct(s.encours_maastricht.pct_pib))} du PIB.</p>
${
  ensemble
    ? `<div class="tableau-defile"><table><caption>Dette de Maastricht fin d’année, milliards d’euros</caption><thead><tr><th scope="col">Année</th><th scope="col" class="nombre">Encours</th><th scope="col" class="nombre">% du PIB</th></tr></thead><tbody>${[...annees]
        .reverse()
        .map((a) => `<tr><th scope="row">${a}</th><td class="nombre">${h(md(ensemble.md[a]))}</td><td class="nombre">${ensemble.pct_pib?.[a] !== undefined ? h(pct(ensemble.pct_pib[a])) : ''}</td></tr>`)
        .join('')}</tbody></table></div><p class="aide">${h(enc!.definition)}</p>${source(enc!.source)}`
    : ''
}
${
  det && derniere
    ? `<h2>Qui détient la dette</h2>${barres(
        Object.values(det.eurostat).map((x) => ({ nom: x.libelle, valeur: x.part[derniere] ?? 0, texte: sur100((x.part[derniere] ?? 0) * 100), detail: md(x.md[derniere] ?? 0) })),
        undefined,
        `Détenteurs fin ${derniere}, en euros sur 100 €`,
      )}<p class="aide">${h(det.definition)}</p>${source(det.source, derniere)}`
    : ''
}
<h2>Deux façons de compter les intérêts</h2>
<p>Budget de l’État (programme 117, crédits payés) : ${h(md(Number(s.programme_117['2025'] ?? 0)))} en 2025. Comptabilité nationale (intérêts dus par toutes les administrations) : ${h(md(s.interets_apu_d41.md))}. Les deux ne s’additionnent pas.</p>
<p class="avertissement">${h(idx.avertissement)}</p>
<p class="liens-sortie"><a href="${'#/explorer/etat/detail?id=Dette%20et%20engagements%20financiers'}">La dette dans le budget de l’État</a></p>
${partPersonnelle()}`
}

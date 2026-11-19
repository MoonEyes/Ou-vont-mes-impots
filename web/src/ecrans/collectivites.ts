// Les collectivités locales, vue nationale : comptes (Eurostat), fonctions (COFOG), régions et départements (OFGL).
import { partPersonnelle } from '../composants/hub'
import { pastilleNiveau } from '../composants/niveaux'
import { chargerSiPresent, type Noeud } from '../donnees'
import { absent, badgeCalcule, barres, eurLisible, h, md, source, sur100, surligne } from '../util'

interface Budgets {
  millesime: string
  source: string
  annees: string[]
  agregats: string[]
  collectivites: Record<string, { nom: string; population: Record<string, number>; eur: Record<string, (number | null)[]> }>
}

function totalNational(b: Budgets | null, agregat: string) {
  if (!b) return null
  const i = b.agregats.indexOf(agregat)
  const an = b.annees[b.annees.length - 1]
  let t = 0
  for (const c of Object.values(b.collectivites)) t += Number(c.eur[an]?.[i] ?? 0)
  return { annee: an, eur: t }
}

export async function rendre(cible: HTMLElement) {
  const [adm, arbre, regions, deps] = await Promise.all([
    chargerSiPresent<{ source: string; annees: Record<string, Record<string, { TR: number; TE: number; B9: number; D73PAY?: number }>> }>('administrations.json'),
    chargerSiPresent<Noeud & { millesime: string; source: string }>('arbre_administrations/racine.json'),
    chargerSiPresent<Budgets>('local/budgets/regions.json'),
    chargerSiPresent<Budgets>('local/budgets/departements.json'),
  ])
  const annees = adm ? Object.keys(adm.annees).sort() : []
  const an = annees[annees.length - 1]
  const cl = an ? adm!.annees[an]['Collectivites locales'] : null
  const ens = an ? adm!.annees[an].Ensemble : null
  const coll = arbre?.enfants?.find((e) => e.nom === 'Collectivites locales')
  const reg = totalNational(regions, 'depenses_totales')
  const dep = totalNational(deps, 'depenses_totales')
  cible.innerHTML = `
<h1>Les collectivités locales</h1>
<p class="chapeau">Communes, intercommunalités, départements et régions : ce qu’elles dépensent, à quoi, et comment elles se financent.</p>
${
  cl && ens
    ? `<div class="carte" data-cle>
  <p class="grand-chiffre">${surligne(md(cl.TE))}</p>
  <p class="sous-chiffre">dépensés par les collectivités locales en ${h(an)}, soit ${h(sur100((cl.TE / ens.TE) * 100))} sur 100 € de dépense publique (${h(md(ens.TE))} pour l’ensemble, transferts entre administrations comptés une fois).</p>
  <p>Recettes ${h(md(cl.TR))}, solde ${h(md(cl.B9))}.</p>
  ${source(adm!.source, an)}
</div>`
    : absent('Comptes des collectivités non disponibles.')
}
${
  coll?.enfants?.length
    ? `<h2>À quoi sert leur argent</h2>${barres(
        [...coll.enfants].sort((a, b) => b.md - a.md).map((f) => ({ nom: f.nom, valeur: f.md, texte: sur100((f.md / coll.md) * 100), detail: md(f.md) })),
        undefined,
        'Dépenses des collectivités par fonction, en euros sur 100 €',
      )}${source(arbre!.source, arbre!.millesime)}`
    : ''
}
<h2>Régions et départements</h2>
<ul class="liste-niveaux">
  ${reg ? `<li>${pastilleNiveau('region')}Les régions et collectivités à statut particulier (${h(String(Object.keys(regions!.collectivites).length))} comptes publiés par l’OFGL ; Mayotte est comptée avec les départements) : ${h(eurLisible(reg.eur))} de dépenses en ${h(reg.annee)}. ${badgeCalcule(`somme des dépenses totales de chaque compte publié par l’OFGL pour ${reg.annee}, même année et même base`)}</li>` : ''}
  ${dep ? `<li>${pastilleNiveau('departement')}Les départements (${h(String(Object.keys(deps!.collectivites).length))} comptes publiés par l’OFGL, dont Paris et la métropole de Lyon) : ${h(eurLisible(dep.eur))} de dépenses en ${h(dep.annee)}. ${badgeCalcule(`somme des dépenses totales de chaque compte publié par l’OFGL pour ${dep.annee}, même année et même base`)}</li>` : ''}
</ul>
${regions ? source(regions.source, regions.millesime) : ''}
<p class="aide">Ne pas additionner les niveaux : une partie de l’argent passe de l’un à l’autre (dotations, reversements).</p>
<p class="liens-sortie"><a href="#/local">Ta commune, ton département, ta région</a></p>
${partPersonnelle()}`
}

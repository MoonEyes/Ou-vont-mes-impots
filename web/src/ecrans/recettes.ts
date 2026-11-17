// Écran 9 : les recettes. Chaque impôt et qui l'encaisse, depuis 2005 (Eurostat, comptabilité nationale).
import { charger, chargerSiPresent } from '../donnees'
import { lien } from '../routeur'
import { barres, h, libelle, md, pct, source } from '../util'

interface Recettes {
  millesime: string
  source: string
  unite: string
  annees: string[]
  impots: Record<string, { nom: string; par_administration: Record<string, Record<string, number>> }>
}

const NOMS: Record<string, string> = {
  D211: 'TVA',
  D51A_C1: 'Impôt sur le revenu des ménages (y compris CSG)',
  D61: 'Cotisations sociales',
  D51B: 'Impôt sur les sociétés',
  D214A: 'Droits d’accise (carburants, tabac, alcool...)',
  D29: 'Autres impôts sur la production (dont taxes foncières des entreprises)',
  D2: 'Tous les impôts sur la production et les importations',
  D5: 'Tous les impôts courants sur le revenu et le patrimoine',
  D91: 'Impôts en capital (droits de succession...)',
}
const ADMINS = ['Etat', 'Securite sociale', 'Collectivites locales']

export async function rendre(cible: HTMLElement, params: URLSearchParams) {
  const r = await charger<Recettes>('recettes.json')
  const admin = await chargerSiPresent<{ annees: Record<string, Record<string, Record<string, number>>> }>('administrations.json')
  const code = params.get('i') && r.impots[params.get('i')!] ? params.get('i')! : 'D211'
  const imp = r.impots[code]
  const annees = [...r.annees].sort()
  const derniere = annees[annees.length - 1]
  const val = (a: string, ad: string) => imp.par_administration[ad]?.[a]
  const totalDerniere = val(derniere, 'Ensemble') ?? ADMINS.reduce((s, ad) => s + (val(derniere, ad) ?? 0), 0)
  const ordre = Object.keys(r.impots).sort((a, b) => (NOMS[a] ? 0 : 1) - (NOMS[b] ? 0 : 1))

  const ad = admin?.annees[derniere]
  cible.innerHTML = `
<h1>D’où vient l’argent : les recettes</h1>
<p class="chapeau">Chaque grand impôt et qui l’encaisse (État, Sécurité sociale, collectivités locales), de ${h(annees[0])} à ${h(derniere)}.</p>
<label for="impot">Impôt</label>
<select id="impot">${ordre.map((c) => `<option value="${c}"${c === code ? ' selected' : ''}>${h(NOMS[c] ?? r.impots[c].nom)}</option>`).join('')}</select>
<h2>${h(NOMS[code] ?? imp.nom)} en ${h(derniere)}</h2>
<div class="carte">
  <p class="grand-chiffre">${h(md(totalDerniere))}</p>
  <p class="sous-chiffre">Intitulé Eurostat : ${h(imp.nom)} (${h(code)})</p>
  ${barres(
    ADMINS.map((a) => ({
      nom: libelle(a),
      valeur: val(derniere, a) ?? 0,
      texte: val(derniere, a) !== undefined ? `${md(val(derniere, a)!)} (${pct(((val(derniere, a) ?? 0) / totalDerniere) * 100, 0)})` : 'aucune recette déclarée',
    })),
    totalDerniere,
    'Qui encaisse cet impôt',
  )}
  ${source(r.source, r.millesime)}
</div>
<div class="tableau-defile"><table>
<caption>${h(NOMS[code] ?? imp.nom)}, en milliards d’euros, par administration qui l’encaisse</caption>
<thead><tr><th scope="col">Année</th>${ADMINS.map((a) => `<th scope="col" class="nombre">${h(libelle(a))}</th>`).join('')}<th scope="col" class="nombre">Ensemble</th></tr></thead>
<tbody>${[...annees]
    .reverse()
    .map(
      (a) =>
        `<tr><th scope="row">${h(a)}</th>${ADMINS.map((x) => `<td class="nombre">${val(a, x) !== undefined ? h(md(val(a, x)!)) : '–'}</td>`).join('')}<td class="nombre">${
          val(a, 'Ensemble') !== undefined ? h(md(val(a, 'Ensemble')!)) : '–'
        }</td></tr>`,
    )
    .join('')}</tbody></table></div>
<p class="aide">Comptabilité nationale : « impôt sur le revenu des ménages » inclut la CSG et la CRDS ; une case vide signifie que l’administration ne déclare pas cette recette cette année-là.</p>
${
  ad
    ? `<h2>Recettes et dépenses des administrations en ${h(derniere)}</h2><div class="tableau-defile"><table><caption>Milliards d’euros (Eurostat gov_10a_main)</caption><thead><tr><th scope="col">Administration</th><th scope="col" class="nombre">Recettes</th><th scope="col" class="nombre">Dépenses</th><th scope="col" class="nombre">Solde</th></tr></thead><tbody>${['Etat', 'Securite sociale', 'Collectivites locales', 'Ensemble']
        .filter((x) => ad[x])
        .map((x) => `<tr><th scope="row">${h(libelle(x))}</th><td class="nombre">${h(md(ad[x].TR))}</td><td class="nombre">${h(md(ad[x].TE))}</td><td class="nombre">${h(md(ad[x].B9))}</td></tr>`)
        .join('')}</tbody></table></div><p class="aide">La somme des administrations dépasse l’ensemble : les transferts entre elles (par exemple les dotations de l’État aux collectivités) ne sont comptés qu’une fois dans l’ensemble.</p>`
    : ''
}`
  cible.querySelector<HTMLSelectElement>('#impot')?.addEventListener('change', (e) => {
    location.hash = lien('/recettes', { i: (e.target as HTMLSelectElement).value })
  })
}

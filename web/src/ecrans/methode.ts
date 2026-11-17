// Écran 10 : méthode et sources (conventions, exclusions, doubles comptes, limites, licences).
import { charger, chargerSiPresent, manifeste } from '../donnees'
import { h, libelle, md, pct } from '../util'

const DEPOT = 'https://github.com/MoonEyes/Ou-vont-mes-impots'

interface Meta {
  genere_le: string
  version_contrat?: string
  sources: Record<string, { source: string; maj_source: string | null }>
  millesime?: { etat_defaut: string; etat_disponibles: string[] }
  controle: {
    etat?: Record<string, {
      millesime: string
      total_md: number
      hors_perimetre_md: Record<string, number>
      prelevements_sur_recettes_md: Record<string, number>
      remboursements_et_degrevements: { montant_md: number; motif: string; traitement: string }
      rapprochement_plrg?: { ecart_md: number; lecture: string; source: string }
    }>
    arbre_administrations?: { annee: string; somme_md: number; total_consolide_s13_md: number; ecart_consolidation_md: number }
    part_empruntee_etat?: Record<string, number>
    communes?: number
  }
}

const date = (x: string | null) => (x ? new Date(x).toLocaleDateString('fr-FR', { year: 'numeric', month: 'long', day: 'numeric' }) : 'non déclarée')

export async function rendre(cible: HTMLElement) {
  const meta = await charger<Meta>('meta.json')
  const man = await manifeste()
  const benef = await chargerSiPresent<{ controle?: { nature?: { ecart_global_pct?: number; tolerance_pct?: number } } }>('beneficiaires/index.json')
  const real = await chargerSiPresent<{ fiabilite_regle_position_cibles?: { concordance_pct?: number } | number }>('realisations/index.json')
  const etats = Object.values(meta.controle.etat ?? {}).filter((e) => e && typeof e === 'object' && 'total_md' in e && 'millesime' in e)
  const ex = etats[0]
  const adm = meta.controle.arbre_administrations
  const fiab = real?.fiabilite_regle_position_cibles
  const fiabPct = typeof fiab === 'number' ? fiab : fiab?.concordance_pct

  cible.innerHTML = `
<h1>Méthode et sources</h1>
<p class="chapeau">Comment les chiffres sont obtenus, ce qui est exclu, ce qui pourrait être compté deux fois, et les limites. Chaque chiffre du site indique sa source et son millésime.</p>

<h2>Ton calcul personnel</h2>
<ul>
<li>Le calcul se fait entièrement dans ton navigateur avec <strong>modele-social</strong> ${h(__VERSION_MODELE_SOCIAL__)} (règles de l’Urssaf utilisées par mon-entreprise.urssaf.fr) et <strong>publicodes</strong> ${h(__VERSION_PUBLICODES__)}. Rien n’est envoyé.</li>
<li>Point de départ : ton salaire <strong>net avant impôt</strong> mensuel, primes lissées sur 12 mois. Le brut est retrouvé par calcul inverse.</li>
<li>Revenus 2025, législation 2025 pour les cotisations. Impôt sur le revenu : barème appliqué aux revenus 2025 (déclarés en 2026), abattement de 10 % par salaire, quotient familial et décote.</li>
<li>modele-social 11 ne code que la loi 2026 pour certaines cotisations patronales. Pour 2025, le site applique la réduction générale de 2025 (jusqu’à 1,6 SMIC) et les taux réduits maladie (7 % jusqu’à 2,25 SMIC) et allocations familiales (3,45 % jusqu’à 3,3 SMIC).</li>
<li>Non pris en compte : complémentaire santé et prévoyance d’entreprise (variables d’un employeur à l’autre), autres revenus du foyer, frais réels, réductions et crédits d’impôt. Ces limites sont rappelées à côté des chiffres concernés.</li>
<li><strong>Fourchettes</strong> : le site ne connaît pas ton employeur. Pour les cotisations patronales, la borne basse suppose un taux d’accidents du travail de 0,45 %, pas de versement mobilité, moins de 11 salariés et la réduction générale ; la borne haute 4 %, un versement mobilité de 3,2 % (Paris), 250 salariés et plus, sans réduction générale. La valeur centrale reprend les valeurs par défaut de modele-social.</li>
<li><strong>Vérification</strong> : 20 cas types (célibataires, parents isolés, couples, cadres, temps partiels, de 0,5 SMIC à 10 000 € net par mois) sont recalculés à chaque modification du site et comparés à OpenFisca, le moteur public de microsimulation. Écart inférieur à 1 % exigé sur le brut, les cotisations salariales, la CSG, la CRDS et l’impôt du foyer. Écarts détaillés : <a href="${DEPOT}/blob/main/web/ECARTS.md" rel="noopener noreferrer">ECARTS.md</a>.</li>
<li><strong>Destinataires</strong> : Agirc-Arrco, Unédic et CADES sont rattachés à la Sécurité sociale, comme en comptabilité nationale. La CSG est affichée « plusieurs branches » tant que sa répartition légale n’est pas publiée par le site${man.optionnels.affectation_prelevements ? ' (répartition disponible et appliquée)' : ''}.</li>
<li>Hors V1 : fonctionnaires, contractuels du public, indépendants, retraités, demandeurs d’emploi, apprentis, frontaliers, outre-mer, Alsace-Moselle. Un message l’explique au lieu d’afficher un chiffre faux.</li>
</ul>

<h2>Le budget de l’État</h2>
<ul>
<li>Vue par défaut : <strong>${h(meta.millesime?.etat_defaut ?? 'Exécution 2024')}</strong> (dépenses réellement payées, crédits de paiement), autre vue : ${h((meta.millesime?.etat_disponibles ?? []).join(', '))}. Source : budget vert du PLF 2026 (data.economie.gouv.fr), complété par le PLRG.</li>
${
  ex
    ? `<li>Total retenu (${h(ex.millesime)}) : ${h(md(ex.total_md))}, budget général et prélèvements sur recettes (${Object.entries(ex.prelevements_sur_recettes_md)
        .map(([k, v]) => `${h(k)} ${h(md(v))}`)
        .join(', ')}).</li>
<li><strong>Exclus</strong> : remboursements et dégrèvements d’impôts (${h(md(ex.remboursements_et_degrevements.montant_md))}). ${h(ex.remboursements_et_degrevements.motif)}</li>
<li><strong>Hors périmètre</strong> (comptes spéciaux et budgets annexes, pour éviter les doubles comptes) : ${Object.entries(ex.hors_perimetre_md)
        .map(([k, v]) => `${h(k)} ${h(md(v))}`)
        .join(' ; ')}.</li>
${ex.rapprochement_plrg ? `<li>Contrôle : écart de ${h(md(ex.rapprochement_plrg.ecart_md))} avec le PLRG. ${h(ex.rapprochement_plrg.lecture)}</li>` : ''}`
    : ''
}
<li><strong>Part empruntée</strong> : pour l’État, comptabilité budgétaire (solde de l’année rapporté aux dépenses) ; pour l’ensemble des administrations, comptabilité nationale (Eurostat). Les deux ne sont jamais additionnées ni comparées.</li>
<li>Vue « par nature » : projet de loi de finances 2025, vue séparée, aucun prorata appliqué aux montants exécutés.</li>
</ul>

<h2>Doubles comptes</h2>
<ul>
${adm ? `<li>Administrations publiques ${h(adm.annee)} : la somme des administrations (${h(md(adm.somme_md))}) dépasse le total consolidé (${h(md(adm.total_consolide_s13_md))}) de ${h(md(adm.ecart_consolidation_md))}, à cause des transferts entre administrations (dotations de l’État aux collectivités, à la Sécurité sociale).</li>` : ''}
<li>Les prélèvements sur recettes au profit des collectivités apparaissent dans le budget de l’État et dans les recettes des collectivités : ne pas les additionner.</li>
<li>Les montants France 2030 sont des engagements cumulés 2021 à 2025, à ne pas comparer à la dépense d’une année.</li>
<li>Les marchés publics sont des montants notifiés (pour un accord-cadre, le maximum estimé), pas des paiements.</li>
</ul>

<h2>Limites connues</h2>
<ul>
<li>Nature de la dépense : écart global de ${h(pct(benef?.controle?.nature?.ecart_global_pct ?? 1.93, 2))} avec l’arbre (tolérance publiée ${h(pct(benef?.controle?.nature?.tolerance_pct ?? 3, 0))}), dû aux retraitements du budget vert.</li>
<li>Effectifs : plafonds d’emplois votés en LFI 2023, dernier millésime publié par programme, rapportés aux dépenses de personnel 2024.</li>
<li>Associations : crédits versés en 2023 (dernier « jaune » publié).</li>
<li>Indicateurs de performance : choisis par l’administration ; une évolution ne prouve pas l’effet de la dépense. Quand le sens souhaité n’est pas publié, il est déduit de la position des cibles${fiabPct ? ` (règle concordante à ${h(pct(fiabPct, 0))} avec le sens publié là où les deux existent)` : ''}.</li>
<li>Années sans données d’exécution par programme en données ouvertes : 2015, 2016, 2017 et 2021.</li>
<li>TVA et taxe foncière estimées : à venir.</li>
</ul>

<h2>Personnes nommées</h2>
<p>Le site nomme uniquement des personnes morales (entreprises, associations, établissements publics), les partis politiques et les candidats aux élections (comptes de campagne publiés par la CNCCFP). Les montants versés à d’autres personnes physiques sont agrégés, jamais nommés.</p>

<h2>Sources et mises à jour</h2>
<div class="tableau-defile"><table><caption>Jeux de données utilisés (passage du pipeline du ${h(date(meta.genere_le))})</caption>
<thead><tr><th scope="col">Jeu</th><th scope="col">Source</th><th scope="col">Mise à jour déclarée</th></tr></thead>
<tbody>${Object.entries(meta.sources)
    .map(([k, s]) => `<tr><td>${h(k)}</td><td>${h(s.source)}</td><td>${h(date(s.maj_source))}</td></tr>`)
    .join('')}</tbody></table></div>
<p>Autres sources : jaunes budgétaires (associations, opérateurs), DECP (marchés), France 2030, RAP et PAP (performance), Cour des comptes (notes d’exécution budgétaire), CNCCFP (partis et campagnes), Eurostat (recettes, administrations, déficit), DGFiP (taux communaux).</p>

<h2>Licences</h2>
<ul>
<li>Données : Licence Ouverte 2.0 (Etalab) ; Eurostat : réutilisation libre avec mention de la source.</li>
<li>Code du site : MIT. <a href="${DEPOT}" rel="noopener noreferrer">Dépôt public</a>.</li>
<li>Bibliothèques : modele-social ${h(__VERSION_MODELE_SOCIAL__)} (MIT), publicodes ${h(__VERSION_PUBLICODES__)} (MIT), Apache ECharts ${h(__VERSION_ECHARTS__)} (Apache-2.0), polices Inter et Space Grotesk (SIL Open Font License 1.1), hébergées avec le site.</li>
</ul>
<p class="aide">Contrat d’interface des données : version ${h(meta.version_contrat ?? '1.0')}. Administrations : ${['Etat', 'Securite sociale', 'Collectivites locales'].map(libelle).join(', ')}.</p>`
}

import { cartesRayons } from '../composants/hub'
// Écran 10 : méthode et sources (conventions, exclusions, doubles comptes, limites, licences).
import { charger, chargerSiPresent } from '../donnees'
import { h, libelle, md, pct, source } from '../util'

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
    arbre_administrations?: { annee: string; somme_md: number; total_consolide_s13_md: number; ecart_consolidation_md: number; ecart_depenses_totales_md?: number }
    part_empruntee_etat?: Record<string, number>
    communes?: number
  }
}

const date = (x: string | null) => (x ? new Date(x).toLocaleDateString('fr-FR', { year: 'numeric', month: 'long', day: 'numeric' }) : 'non déclarée')

export async function rendre(cible: HTMLElement) {
  const meta = await charger<Meta>('meta.json')
  const benef = await chargerSiPresent<{ controle?: { nature?: { ecart_global_pct?: number; tolerance_pct?: number } } }>('beneficiaires/index.json')
  const real = await chargerSiPresent<{ fiabilite_regle_position_cibles?: { concordance_pct?: number } | number }>('realisations/index.json')
  const tva = await chargerSiPresent<{ millesime: string; source: string; methode: string[]; limites: string[]; ecarts_au_total_national: Record<string, { estime_md: number; reel_md: number; ecart_pct: number }>; recalage?: { lecture_ecart?: string }; non_sourcé?: string[] }>('prelevements/tva_conso.json')
  const tf = await chargerSiPresent<{ millesime: string; source: string; methode: string[]; limites: string[] }>('prelevements/taxe_fonciere.json')
  const aff = await chargerSiPresent<{ millesime: string; source: string; methode?: string; destinataires?: Record<string, { nom: string }>; prelevements?: Record<string, { points?: Record<string, number> }> }>('prelevements/affectation.json')
  const points = aff?.prelevements?.csg_activite?.points
  const nf = (x: number) => x.toLocaleString('fr-FR', { maximumFractionDigits: 2 })
  const exempleCsg = points
    ? `(par exemple la CSG sur les salaires : ${Object.entries(points)
        .map(([k, v]) => `${nf(v)} point${v >= 2 ? 's' : ''} pour ${h(aff?.destinataires?.[k]?.nom ?? k)}`)
        .join(', ')}, sur ${nf(Object.values(points).reduce((a, b) => a + b, 0))})`
    : ''
  const NOMS_TAXES: Record<string, string> = { tva: 'TVA', ticpe: 'Carburants (ex-TICPE)', tabac: 'Tabac', alcool: 'Alcools', autres: 'Autres taxes sur les produits', total_taxes_produits: 'Total des taxes sur les produits' }
  const etats = Object.values(meta.controle.etat ?? {}).filter((e) => e && typeof e === 'object' && 'total_md' in e && 'millesime' in e)
  const ex = etats[0]
  const adm = meta.controle.arbre_administrations
  const fiab = real?.fiabilite_regle_position_cibles
  const fiabPct = typeof fiab === 'number' ? fiab : fiab?.concordance_pct

  cible.innerHTML = `
<h1>Méthode et sources</h1>
<p class="chapeau">Comment les chiffres sont obtenus, ce qui est exclu, ce qui pourrait être compté deux fois, et les limites. Chaque chiffre du site indique sa source et son millésime.</p>
${cartesRayons('/methode')}

<h2>Ton calcul personnel</h2>
<ul>
<li>Le calcul se fait entièrement dans ton navigateur avec <strong>modele-social</strong> ${h(__VERSION_MODELE_SOCIAL__)} (règles de l’Urssaf utilisées par mon-entreprise.urssaf.fr) et <strong>publicodes</strong> ${h(__VERSION_PUBLICODES__)}. Rien n’est envoyé.</li>
<li>Point de départ : ton salaire <strong>net avant impôt</strong> mensuel, primes lissées sur 12 mois. Le brut est retrouvé par calcul inverse.</li>
<li>Revenus 2025, législation 2025 pour les cotisations. Impôt sur le revenu : barème appliqué aux revenus 2025 (déclarés en 2026), abattement de 10 % par salaire, quotient familial et décote.</li>
<li>modele-social 11 ne code que la loi 2026 pour certaines cotisations patronales. Pour 2025, le site applique la réduction générale de 2025 (jusqu’à 1,6 SMIC) et les taux réduits maladie (7 % jusqu’à 2,25 SMIC) et allocations familiales (3,45 % jusqu’à 3,3 SMIC).</li>
<li>Non pris en compte : complémentaire santé et prévoyance d’entreprise (variables d’un employeur à l’autre), autres revenus du foyer, frais réels, réductions et crédits d’impôt. Ces limites sont rappelées à côté des chiffres concernés.</li>
<li><strong>Fourchettes</strong> : le site ne connaît pas ton employeur. Pour les cotisations patronales, la borne basse suppose un taux d’accidents du travail de 0,45 %, pas de versement mobilité, moins de 11 salariés et la réduction générale ; la borne haute 4 %, un versement mobilité de 3,2 % (Paris), 250 salariés et plus, sans réduction générale. La valeur centrale reprend les valeurs par défaut de modele-social.</li>
<li><strong>Vérification</strong> : 20 cas types (célibataires, parents isolés, couples, cadres, temps partiels, de 0,5 SMIC à 10 000 € net par mois) sont recalculés à chaque modification du site et comparés à OpenFisca, le moteur public de microsimulation. Écart inférieur à 1 % exigé sur le brut, les cotisations salariales, la CSG, la CRDS et l’impôt du foyer. Écarts détaillés : fichier web/ECARTS.md du code source.</li>
<li><strong>Destinataires</strong> : Agirc-Arrco, Unédic et CADES sont rattachés à la Sécurité sociale, comme en comptabilité nationale. ${aff ? 'Chaque prélèvement est réparti selon prelevements/affectation.json (voir plus bas).' : 'La CSG est affichée « plusieurs branches » faute de répartition publiée.'}</li>
<li>Hors V1 : fonctionnaires, contractuels du public, indépendants, retraités, demandeurs d’emploi, apprentis, frontaliers, outre-mer, Alsace-Moselle. Un message l’explique au lieu d’afficher un chiffre faux.</li>
</ul>

<h2>Taxes sur la consommation, impôts locaux, destinataires</h2>
${
  tva
    ? `<ul>
<li>Ton foyer est placé dans un décile de niveau de vie : revenu disponible (salaires nets moins impôt sur le revenu, sans prestations) divisé par le nombre d’unités de consommation (1 pour le premier adulte, 0,5 par autre personne de 14 ans ou plus, 0,3 par enfant de moins de 14 ans ; enfant en garde alternée compté pour moitié). Les taxes affichées sont la moyenne de ce décile, multipliée par tes unités de consommation.</li>
${tva.methode.map((m) => `<li>${h(m)}</li>`).join('')}
<li>Ajustements appliqués seulement là où la source les publie : voiture (carburant) et absence de tabac. Le montant payé par un fumeur n’est pas publié : il est affiché « non chiffré ».</li>
</ul>
<div class="tableau-defile"><table><caption>Recalage sur le total national 2025 : écart publié entre l’estimation par déciles et le total réel</caption>
<thead><tr><th scope="col">Taxe</th><th scope="col" class="nombre">Estimé</th><th scope="col" class="nombre">Réel</th><th scope="col" class="nombre">Écart</th></tr></thead>
<tbody>${Object.entries(tva.ecarts_au_total_national)
        .map(([k, e]) => `<tr><th scope="row">${h(NOMS_TAXES[k] ?? k)}</th><td class="nombre">${h(md(e.estime_md))}</td><td class="nombre">${h(md(e.reel_md))}</td><td class="nombre">${h((e.ecart_pct > 0 ? '+' : '') + pct(e.ecart_pct))}</td></tr>`)
        .join('')}</tbody></table></div>
${tva.recalage?.lecture_ecart ? `<p class="aide">${h(tva.recalage.lecture_ecart)}</p>` : ''}
<p class="aide">Limites : ${tva.limites.map(h).join(' ')}${tva.non_sourcé?.length ? ` Non sourcé : ${tva.non_sourcé.map(h).join(' ')}` : ''}</p>
${source(tva.source, tva.millesime)}`
    : '<p class="absent">Taxes sur la consommation : donnée non disponible.</p>'
}
${
  tf
    ? `<h3>Taxe foncière et TEOM</h3><ul>${tf.methode.map((m) => `<li>${h(m)}</li>`).join('')}</ul><p class="aide">Limites : ${tf.limites.map(h).join(' ')}</p>${source(tf.source, tf.millesime)}`
    : ''
}
${
  aff
    ? `<h3>Qui reçoit chaque prélèvement</h3><p>Chaque prélèvement est réparti entre ses destinataires selon les parts fixées par la loi (${h(aff.millesime)}) ${exempleCsg}. Une répartition sans source publiée est affichée « non sourcée », jamais estimée.</p>${source(aff.source, aff.millesime)}`
    : ''
}

<h2 id="methode-non-salaries">Retraités, agents publics et indépendants : qui reçoit ce que tu verses</h2>
<p>Cette partie explique comment le site répartit les prélèvements propres aux retraités, aux fonctionnaires, aux contractuels du public, aux indépendants et à l’Alsace-Moselle. Elle ne dit pas comment ces montants sont dépensés ensuite. Chaque répartition vient d’un document officiel cité dans prelevements/affectation.json ; sans document, le montant reste « sans destinataire publié ».</p>
<ul>
<li><strong>Retraité·e</strong> : la contribution sociale généralisée (CSG) sur ta pension n’a pas la même répartition selon son taux (réduit 3,8 %, médian 6,6 %, normal 8,3 %). Les points de chaque destinataire pour 2025 sont lus dans l’annexe 3 du projet de loi de financement de la sécurité sociale pour 2026${(() => {
    const pts = aff?.prelevements?.csg_remplacement_taux_normal?.points
    return pts ? ` (au taux normal : ${Object.entries(pts).map(([k, v]) => `${nf(v)} point${v >= 2 ? 's' : ''} pour ${h(aff?.destinataires?.[k]?.nom ?? k)}`).join(', ')})` : ''
  })()}. La contribution additionnelle de solidarité pour l’autonomie (Casa, 0,3 %) va en totalité à la branche autonomie.</li>
<li><strong>Fonctionnaire de l’État</strong> : la retenue pour pension civile et la contribution de ton employeur sont des recettes du compte d’affectation spéciale « Pensions », géré par le Service des retraites de l’État (projet annuel de performances 2026 de ce compte). La contribution employeur est payée par l’État à un compte de l’État : c’est un flux interne à l’État.</li>
<li><strong>Fonctionnaire territorial ou hospitalier, contractuel·le du public, primes</strong> : retenue et contribution employeur vont à la Caisse nationale de retraites des agents des collectivités locales (CNRACL) ; les cotisations des contractuels à l’Institution de retraite complémentaire des agents non titulaires de l’État et des collectivités publiques (Ircantec) ; celles sur les primes à la retraite additionnelle de la fonction publique. Source : rapport sur les pensions de retraite de la fonction publique annexé au projet de loi de finances pour 2026.</li>
<li><strong>Micro-entrepreneur·e et indépendant·e</strong> : le forfait est d’abord découpé par risque selon les clés publiées par l’Assurance retraite (circulaire de la Caisse nationale d’assurance vieillesse n° 2024-23). La part retraite de base va au régime général, la part retraite complémentaire au régime complémentaire des indépendants. Les parts maladie-maternité et invalidité-décès, la contribution à la formation professionnelle et la taxe pour frais de chambre consulaire n’ont pas de destinataire dans une source primaire que le site a pu consulter : elles restent « sans destinataire publié ».</li>
<li><strong>Alsace-Moselle</strong> : la cotisation salariale de 1,3 % va au régime local d’assurance maladie (annexe 3 du projet de loi de financement de la sécurité sociale pour 2026).</li>
<li><strong>Tracé ou approché</strong> : une répartition est « tracée » quand le document désigne un seul destinataire ou publie les points de chacun ; « approchée » quand le destinataire publié vaut pour le cas le plus courant mais dépend d’une situation que le calcul ne connaît pas. Exemple : une profession libérale réglementée cotise pour sa retraite à une caisse propre (Cipav ou autre section des professions libérales), pas au régime général.</li>
</ul>

<h2>Le budget de l’État</h2>
<ul>
<li>Vue par défaut : <strong>${h(meta.millesime?.etat_defaut ?? 'Exécution 2024')}</strong> (dépenses réellement payées, crédits de paiement), autre vue : ${h((meta.millesime?.etat_disponibles ?? []).join(', '))}. Source : budget vert du projet de loi de finances 2026 (PLF, data.economie.gouv.fr), complété par la loi qui arrête les comptes de l’année (PLRG, projet de loi relatif aux résultats de la gestion).</li>
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

<h2 id="methode-calcule">Chiffres calculés par le site</h2>
<p>Quand le site fait lui-même un calcul à partir de montants publiés (un rapport, une différence, une somme, une moyenne ou une part), ce chiffre n’est affiché que si tous ses montants portent sur la même année et sur le même périmètre. Il porte alors la mention « Calculé par le site », avec un motif quadrillé distinct des autres statuts, et sa méthode est écrite juste à côté.</p>
<p>Si les montants portent sur deux années ou deux périmètres différents, le chiffre n’est pas affiché : par exemple, aucun montant par étudiant (dépenses d’une année civile, étudiants d’une année universitaire) ni coût moyen par emploi de l’État (emplois votés et dépenses de personnel d’années différentes) n’est publié.</p>

<h2>Doubles comptes</h2>
<ul>
${adm ? `<li>Administrations publiques ${h(adm.annee)} : la somme des administrations (${h(md(adm.somme_md))}) dépasse le total consolidé (${h(md(adm.total_consolide_s13_md))}) de ${h(md(adm.ecart_consolidation_md))}, à cause des transferts entre administrations qui restent dans cette somme (dotations de l’État aux collectivités, à la Sécurité sociale).${adm.ecart_depenses_totales_md !== undefined ? ` Sur les dépenses totales de chaque administration, tous transferts compris, l’écart est de ${h(md(adm.ecart_depenses_totales_md))}.` : ''}</li>` : ''}
<li>Les prélèvements sur recettes au profit des collectivités apparaissent dans le budget de l’État et dans les recettes des collectivités : ne pas les additionner.</li>
<li>Les montants France 2030 sont des engagements cumulés 2021 à 2025, à ne pas comparer à la dépense d’une année.</li>
<li>Les marchés publics sont des montants notifiés (pour un accord-cadre, le maximum estimé), pas des paiements.</li>
</ul>

<h2>Limites connues</h2>
<ul>
${
  benef?.controle?.nature?.ecart_global_pct !== undefined
    ? `<li>Nature de la dépense : écart global de ${h(pct(benef.controle.nature.ecart_global_pct, 2))} avec l’arbre${
        benef.controle.nature.tolerance_pct !== undefined ? ` (tolérance publiée ${h(pct(benef.controle.nature.tolerance_pct, 0))})` : ''
      }, dû aux retraitements du budget vert.</li>`
    : ''
}
<li>Effectifs : plafonds d’emplois votés dans le budget 2023 (loi de finances initiale, LFI), dernier millésime publié par programme, rapportés aux dépenses de personnel 2024.</li>
<li>Associations : crédits versés en 2023 (dernier « jaune » publié).</li>
<li>Indicateurs de performance : choisis par l’administration ; une évolution ne prouve pas l’effet de la dépense. Quand le sens souhaité n’est pas publié, il est déduit de la position des cibles${fiabPct ? ` (règle concordante à ${h(pct(fiabPct, 0))} avec le sens publié là où les deux existent)` : ''}.</li>
<li>Années sans données d’exécution par programme en données ouvertes : 2015, 2016, 2017 et 2021.</li>
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
<li>Données : Licence Ouverte 2.0 (Etalab) ; Eurostat : réutilisation libre avec mention de la source. Exception : les fichiers produits à partir d’un jeu publié sous Open Database License 1.0 (par exemple les données de data.ameli.fr de l’Assurance maladie) sont publiés sous la même licence ODbL 1.0, avec partage à l’identique ; la licence de chaque fichier est écrite dans le Data Package du dépôt (docs/datapackage).</li>
<li>Code du site : code source ouvert sous licence MIT.</li>
<li>Bibliothèques : modele-social ${h(__VERSION_MODELE_SOCIAL__)} (MIT), publicodes ${h(__VERSION_PUBLICODES__)} (MIT), Apache ECharts ${h(__VERSION_ECHARTS__)} (Apache-2.0), polices Bricolage Grotesque et Figtree (SIL Open Font License 1.1), hébergées avec le site.</li>
</ul>
<p class="aide">Contrat d’interface des données : version ${h(meta.version_contrat ?? '1.0')}. Administrations : ${['Etat', 'Securite sociale', 'Collectivites locales'].map(libelle).join(', ')}.</p>`
}

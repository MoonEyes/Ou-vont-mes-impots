// Encadré « donnée non publiée à la source » : un seul composant pour tout le site.
// Il dit ce qui manque, pourquoi (qui ne publie pas, ou pourquoi la donnée n'existe pas), depuis quand, et renvoie à
// la source. Ton neutre : un constat daté, jamais un jugement sur l'organisme qui ne publie pas
// (tests/manque.test.ts applique le lexique partagé docs/lexique_neutre.json et une liste de mots de reproche).
// Les cas connus sont écrits ici une fois (MANQUES) ; les dates et les comptes viennent des données quand elles les donnent.
import { h } from '../util'

export interface Manque {
  /** ce qui manque, en une phrase */
  quoi: string
  /** pourquoi : qui ne publie pas, ou pourquoi la donnée n'existe pas */
  pourquoi: string
  /** depuis quand, ou date du constat */
  depuis: string
  source: { libelle: string; url: string }
}

/** Encadré prêt à insérer. role="note" : un lecteur d'écran l'annonce comme une remarque liée au contenu. */
export function encadreManque(m: Manque): string {
  return `<aside class="manque" role="note" aria-label="Donnée non publiée à la source">
<p class="manque-titre">Donnée non publiée à la source</p>
<dl>
<div><dt>Ce qui manque</dt><dd>${h(m.quoi)}</dd></div>
<div><dt>Pourquoi</dt><dd>${h(m.pourquoi)}</dd></div>
<div><dt>Depuis</dt><dd>${h(m.depuis)}</dd></div>
<div><dt>Source</dt><dd><a href="${h(m.source.url)}" rel="noopener noreferrer">${h(m.source.libelle)}</a></dd></div>
</dl>
</aside>`
}

/** Date ISO (2026-11-18) ou française (18/11/2026) écrite en toutes lettres ; texte laissé tel quel sinon. */
export function dateLisible(d: string | null | undefined): string {
  if (!d) return 'date non publiée'
  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(d)
  const fr = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(d)
  const [a, m, j] = iso ? [iso[1], iso[2], iso[3]] : fr ? [fr[3], fr[2], fr[1]] : [null, null, null]
  if (!a) return d
  return new Date(`${a}-${m}-${j}T00:00:00Z`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
}

const entier = (n: number) => new Intl.NumberFormat('fr-FR').format(n)

/** Cas connus. Chaque fonction reçoit ce que les données disent (dates de relevé, comptes) et rend un Manque. */
export const MANQUES = {
  /** Qui a voté tes impôts : votes de chaque sénateur. */
  senatScrutins: (releve: string | null): Manque => ({
    quoi: 'Le vote de chaque sénatrice et de chaque sénateur lors des scrutins publics du Sénat.',
    pourquoi: 'Le Sénat ne publie pas ses scrutins nominatifs en données ouvertes. La page reprend les amendements adoptés au Sénat, avec leur auteur, et les scrutins de l’Assemblée nationale.',
    depuis: `Toute la période couverte par la page (17e législature, depuis juillet 2024). Constat du relevé du ${dateLisible(releve)}.`,
    source: { libelle: 'Données ouvertes du Sénat (data.senat.fr)', url: 'https://data.senat.fr/' },
  }),
  /** Qui a voté tes impôts : cotisations sociales. */
  cotisationsDecret: (): Manque => ({
    quoi: 'Un vote du Parlement rattaché aux taux des cotisations sociales (salariales et patronales).',
    pourquoi: 'Ces taux sont fixés pour l’essentiel par décret du Gouvernement, sans article de loi unique qui les porte : il n’existe pas de scrutin à relier à chaque taux.',
    depuis: 'Règle de fixation en vigueur sur toute la période couverte par la page (17e législature, depuis juillet 2024).',
    source: { libelle: 'Code de la sécurité sociale (Légifrance)', url: 'https://www.legifrance.gouv.fr/codes/texte_lc/LEGITEXT000006073189' },
  }),
  /** Délibérations d'une collectivité qui ne publie pas le jeu national. */
  deliberations: (nom: string, d: { date_releve?: string; absence?: string; absence_detail?: string; couverture?: { commune?: { publient: number; total: number | null } } }): Manque => {
    const c = d.couverture?.commune
    return {
      quoi: `Les délibérations de ${nom} en données ouvertes.`,
      pourquoi:
        d.absence && d.absence_detail
          ? `${nom} ${d.absence} : ${d.absence_detail}`
          : `Aucun jeu au schéma national « Délibérations » publié par ${nom} n’a été trouvé sur data.gouv.fr. La collectivité peut publier ses actes autrement (site, recueil des actes administratifs).`,
      depuis: `Constat du relevé du ${dateLisible(d.date_releve)}${c && c.total ? ` : ${entier(c.publient)} communes sur ${entier(c.total)} publient ce jeu` : ''}.`,
      source: { libelle: 'Schéma national « Délibérations » (schema.data.gouv.fr)', url: 'https://schema.data.gouv.fr/scdl/deliberations.html' },
    }
  },
  /** Fonds européens : listes d'opérations commune par commune, hors listes reprises. */
  fondsEuropeensCommunes: (o: { region?: string; listes: { autorite_de_gestion: string; collecte_le?: string }[]; inaccessible?: { url?: string; constat: string } }): Manque => {
    const autorites = [...new Set(o.listes.map((l) => l.autorite_de_gestion))]
    const collecte = o.listes.map((l) => l.collecte_le).filter((x): x is string => !!x).sort().pop() ?? null
    return {
      quoi: `La liste des opérations cofinancées par l’Union européenne, avec la commune de chaque opération${o.region ? `, pour la région ${o.region}` : ', pour les régions dont la liste n’est pas reprise'}.`,
      pourquoi: `Le site reprend ${entier(o.listes.length)} listes publiées en données ouvertes par ${entier(autorites.length)} autorités de gestion (${autorites.join(', ')}). Les listes des autres autorités de gestion sont publiées sur Europe en France${
        o.inaccessible ? `, qui renvoie une vérification anti-robot aux requêtes automatiques : elles ne sont pas reprises` : ' : elles ne sont pas reprises'
      }.`,
      depuis: `Constat de la collecte du ${dateLisible(collecte)} (programmations 2014-2020 et 2021-2027).`,
      source: { libelle: 'Europe en France, listes des opérations', url: o.inaccessible?.url ?? 'https://www.europe-en-france.gouv.fr/fr' },
    }
  },
  /**
   * Département : les comptes par fonction sont repris (présentation fonctionnelle de l'OFGL) ; ce qui manque est le
   * budget voté par fonction (prévisionnel) en données ouvertes, que seules quelques collectivités pilotes publient.
   */
  departementFonctions: (nom: string, millesime?: string, couverts?: number): Manque => ({
    quoi: `Le budget voté (prévisionnel) par fonction de ${nom} en données ouvertes, au format national d’échange des budgets (SCDL Budget).`,
    pourquoi: `Les montants par fonction de cette page sont ceux des comptes de l’exercice (dépenses réalisées), publiés par l’OFGL${couverts ? ` pour ${entier(couverts)} département${couverts > 1 ? 's' : ''}` : ''}. Le budget voté par fonction n’est publié au format national que par quelques collectivités pilotes (adhérents de Mégalis Bretagne, Nantes Métropole) ; aucun jeu de ${nom} à ce format n’a été trouvé dans les sources lues par le site.`,
    depuis: `Constat de la collecte${millesime ? ` (${millesime})` : ''}.`,
    source: { libelle: 'Schéma national « Budget » (schema.data.gouv.fr)', url: 'https://schema.data.gouv.fr/scdl/budget.html' },
  }),
  /** Ma commune : flux entre la commune et son intercommunalité absents des comptes repris par l'OFGL. */
  fluxIntercommunalite: (nom: string, annee?: string | null): Manque => ({
    quoi: `Les attributions de compensation et la dotation de solidarité communautaire entre ${nom} et son intercommunalité${annee ? ` en ${annee}` : ''}.`,
    pourquoi: 'L’OFGL publie ces flux à partir des comptes de gestion de l’année ; les comptes de quelques communes n’étaient pas encore intégrés à la date de collecte (intégration annoncée avec les balances définitives de la DGFiP), et une commune sans intercommunalité à fiscalité propre n’a pas de tels flux.',
    depuis: `Comptes de gestion ${annee ?? 'de la dernière année'}, base communale des flux de l’OFGL.`,
    source: { libelle: 'OFGL, flux financiers entre communes et intercommunalités', url: 'https://data.ofgl.fr/explore/dataset/base-communale-flux-financiers/' },
  }),
  /** Ma commune : effectifs de police municipale non rattachés à la commune. */
  policeMunicipale: (nom: string, annees?: string[], fiche?: string): Manque => ({
    quoi: `Des effectifs de police municipale déclarés sous le nom de ${nom}.`,
    pourquoi: 'L’enquête annuelle du ministère de l’Intérieur liste les communes et intercommunalités qui ont un service de police municipale, sans code Insee. La commune n’y figure pas sous son nom : pas de service déclaré, service porté par l’intercommunalité ou mis en commun avec d’autres communes, ou nom écrit autrement.',
    depuis: annees?.length ? `Enquêtes ${annees[0]} à ${annees[annees.length - 1]}.` : 'Enquêtes lues par le site.',
    source: { libelle: 'Police municipale : effectifs par commune (data.gouv.fr)', url: fiche ?? 'https://www.data.gouv.fr/datasets/police-municipale-effectifs-par-commune' },
  }),
  /** Ma commune : allocation aux adultes handicapés publiée à l'échelle de l'intercommunalité seulement. */
  aahCommune: (nom: string): Manque => ({
    quoi: `Le nombre de bénéficiaires de l’allocation aux adultes handicapés (AAH) domiciliés à ${nom}.`,
    pourquoi: 'La CNAF publie l’AAH et l’allocation d’éducation de l’enfant handicapé à l’échelle de l’intercommunalité, du département et de la France, pas de la commune.',
    depuis: 'Jeux de la CNAF publiés depuis décembre 2020.',
    source: { libelle: 'CNAF, répartition des allocataires par intercommunalité (data.caf.fr)', url: 'https://data.caf.fr/explore/dataset/s_ben_epci_f/' },
  }),
  /** Ma commune : impôt sur la fortune immobilière publié au-dessus de seuils seulement. */
  ifiSousSeuil: (nom: string, annees?: string[], fiche?: string): Manque => ({
    quoi: `Le nombre de foyers de ${nom} redevables de l’impôt sur la fortune immobilière, leur patrimoine moyen et leur impôt moyen.`,
    pourquoi: 'La DGFiP ne publie ces chiffres par commune que pour les villes de plus de 20 000 habitants comptant plus de 50 foyers redevables (secret fiscal). La commune est sous l’un de ces seuils dans les classeurs lus.',
    depuis: annees?.length ? `Classeurs ${annees[0]} à ${annees[annees.length - 1]}.` : 'Classeurs lus par le site.',
    source: { libelle: 'DGFiP, impôt sur la fortune immobilière par collectivité (data.gouv.fr)', url: fiche ?? 'https://www.data.gouv.fr/datasets/5369965ea3a729239d204992' },
  }),
  /** Ma commune, onglet département : pas de comptes de SDIS publiés pour ce département. */
  sdisAbsent: (nomDep: string): Manque => ({
    quoi: `Les comptes d’un service départemental d’incendie et de secours (SDIS) pour ${nomDep}.`,
    pourquoi: 'À Paris et dans les Hauts-de-Seine, la Seine-Saint-Denis et le Val-de-Marne, les secours sont assurés par la brigade de sapeurs-pompiers de Paris, unité militaire financée par l’État et les collectivités : il n’existe pas de SDIS dont l’OFGL publie les comptes. Ailleurs, les comptes du SDIS ne figurent pas dans la base de l’OFGL lue par le site.',
    depuis: 'Comptes des SDIS 2012 à 2025.',
    source: { libelle: 'OFGL, comptes des SDIS', url: 'https://data.ofgl.fr/explore/dataset/ofgl-base-sdis/' },
  }),
}

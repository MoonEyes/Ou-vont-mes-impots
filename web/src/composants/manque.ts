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
  /** Budget d'un département par fonction, au format national des budgets. */
  departementFonctions: (nom: string, millesime?: string): Manque => ({
    quoi: `Le budget voté par fonction de ${nom} au format national d’échange des budgets (SCDL Budget).`,
    pourquoi: 'Ce format est publié en données ouvertes par quelques collectivités pilotes (adhérents de Mégalis Bretagne, Nantes Métropole) ; les autres départements ne le publient pas. Cette page montre donc le département par nature de dépense ; la présentation par fonction que l’OFGL calcule à partir des comptes n’y est pas encore reprise.',
    depuis: `Constat de la collecte${millesime ? ` (${millesime})` : ''}.`,
    source: { libelle: 'Schéma national « Budget » (schema.data.gouv.fr)', url: 'https://schema.data.gouv.fr/scdl/budget.html' },
  }),
}
